#!/usr/bin/env python3
"""HTTP API for the SerialTranslate mobile app.

This module keeps the existing Telegram pipeline as the source of truth and exposes
the same product actions over JSON: load a title, fetch word bands, generate
on-demand rare/phrasal/idiom lists, and maintain a personal dictionary.
"""

from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Literal, Optional, Tuple

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

import telegram_bot as bot
from title_resolution import ResolvedTitle, detect_media_intent, resolve_input


app = FastAPI(title="SerialTranslate Mobile API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

MediaMode = Literal["auto", "series", "movie"]
ListKind = Literal[
    "frequent_c",
    "frequent_b",
    "rare_c",
    "rare_b",
    "phrasal",
    "idioms",
]


class TitleSelection(BaseModel):
    media_type: Literal["tv", "movie"]
    canonical_title: str
    season: int = 1
    episode: int = 1
    year: int = 0
    imdb_id: Optional[str] = None


class LoadTitleRequest(BaseModel):
    query: str = Field(..., min_length=2)
    mode: MediaMode = "auto"
    selection: Optional[TitleSelection] = None


class DictionaryToggleRequest(BaseModel):
    user_id: str = Field(..., min_length=1)
    word: str = Field(..., min_length=1)
    translation: str = ""
    example: str = ""
    source_title: str = ""
    source_id: str = ""


class WordItem(BaseModel):
    word: str
    translation: str
    example: str = ""
    saved: bool = False
    frequency: str = ""
    score: str = ""


class ListResponse(BaseModel):
    id: str
    kind: ListKind
    title: str
    subtitle: str = ""
    total: int
    items: List[WordItem]
    truncated: bool = False


class TitleSummary(BaseModel):
    id: str
    media_type: Literal["tv", "movie"]
    title: str
    subtitle: str = ""
    translations_dir: str
    available_lists: List[ListKind]
    lists: Dict[str, ListResponse]


class LoadTitleResponse(BaseModel):
    status: Literal["ready", "needs_confirmation"]
    resolved: Optional[Dict[str, Any]] = None
    alternatives: List[Dict[str, Any]] = []
    title: Optional[TitleSummary] = None


def _encode_id(path: Path) -> str:
    rel = path.resolve().relative_to(bot.BASE_DIR.resolve()).as_posix()
    return base64.urlsafe_b64encode(rel.encode("utf-8")).decode("ascii").rstrip("=")


def _decode_id(value: str) -> Path:
    padding = "=" * (-len(value) % 4)
    try:
        rel = base64.urlsafe_b64decode((value + padding).encode("ascii")).decode("utf-8")
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid title id") from exc
    path = (bot.BASE_DIR / rel).resolve()
    try:
        path.relative_to(bot.TRANSLATIONS_BASE.resolve())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Title id is outside translations") from exc
    if not path.exists():
        raise HTTPException(status_code=404, detail="Title not found")
    return path


def _resolved_to_dict(resolved: ResolvedTitle) -> Dict[str, Any]:
    return {
        "media_type": resolved.media_type,
        "canonical_title": resolved.canonical_title,
        "season": resolved.season,
        "episode": resolved.episode,
        "year": resolved.year,
        "imdb_id": resolved.imdb_id,
        "confidence": resolved.confidence,
        "issue": resolved.issue,
        "reason": resolved.reason,
    }


def _mode_for_query(query: str, requested: MediaMode) -> str:
    if requested == "movie":
        return "movie"
    if requested == "series":
        return "series"
    return "movie" if detect_media_intent(query, "series") == "movie" else "series"


def _selection_to_identity(selection: TitleSelection) -> Dict[str, Any]:
    if selection.media_type == "movie":
        return {
            "media_type": "movie",
            "canonical_title": selection.canonical_title,
            "movie_name": selection.canonical_title,
            "year": selection.year,
            "imdb_id": selection.imdb_id,
        }
    return {
        "media_type": "tv",
        "canonical_title": selection.canonical_title,
        "series_name": selection.canonical_title,
        "season": selection.season,
        "episode": selection.episode,
    }


def _resolve_or_confirm(req: LoadTitleRequest) -> Tuple[Optional[Dict[str, Any]], Optional[LoadTitleResponse]]:
    if req.selection is not None:
        return _selection_to_identity(req.selection), None

    mode = _mode_for_query(req.query, req.mode)
    if mode == "movie":
        movie_name, year = bot._parse_movie_input(req.query)
        resolved = resolve_input(req.query, mode="movie", movie_name=movie_name, year=year)
    else:
        series_name, season, episode = bot._parse_series_input(req.query)
        resolved = resolve_input(
            req.query,
            mode="series",
            series_name=series_name,
            season=season,
            episode=episode,
        )

    if resolved.confidence != "high":
        alternatives = [_resolved_to_dict(a) for a in resolved.alternatives[:5]]
        return None, LoadTitleResponse(
            status="needs_confirmation",
            resolved=_resolved_to_dict(resolved),
            alternatives=alternatives,
        )

    identity = bot._identity_from_resolved(resolved)
    return identity, None


def _ensure_series_loaded(identity: Dict[str, Any]) -> Path:
    series_name = str(identity.get("series_name") or identity.get("canonical_title") or "Unknown")
    season = int(identity.get("season") or 1)
    episode = int(identity.get("episode") or 1)

    episode_dir, translations_dir, subtitle_path = bot._find_existing(series_name, season, episode)
    if translations_dir is not None:
        return translations_dir

    if episode_dir is None:
        subtitle_path = bot._do_download(series_name, season, episode)
        if not subtitle_path:
            raise HTTPException(status_code=404, detail="Subtitle download failed")
        episode_dir, _metrics, subtitle_raw = bot._do_analyze(subtitle_path)
        if episode_dir is None:
            raise HTTPException(status_code=500, detail="Could not build hard-word list")
    else:
        subtitle_raw = None
        if subtitle_path is None:
            subtitle_path = bot._do_download(series_name, season, episode)
            if not subtitle_path:
                raise HTTPException(status_code=404, detail="Subtitle download failed")

    ok, out_dir, err, _metrics = bot._do_translate(
        episode_dir, subtitle_path, subtitle_raw=subtitle_raw
    )
    if not ok or out_dir is None:
        raise HTTPException(status_code=500, detail=err or "Translation failed")
    return out_dir


def _ensure_movie_loaded(identity: Dict[str, Any]) -> Path:
    movie_name = str(identity.get("movie_name") or identity.get("canonical_title") or "Unknown")
    year = int(identity.get("year") or 0)
    imdb_id = identity.get("imdb_id")

    episode_dir, translations_dir, subtitle_path = bot._find_existing_movie(movie_name, year)
    if translations_dir is not None:
        return translations_dir

    if episode_dir is None:
        subtitle_path = bot._do_download_movie(movie_name, year, imdb_id=imdb_id)
        if not subtitle_path:
            raise HTTPException(status_code=404, detail="Subtitle download failed")
        episode_dir, _metrics, subtitle_raw = bot._do_analyze_movie(subtitle_path, movie_name, year)
        if episode_dir is None:
            raise HTTPException(status_code=500, detail="Could not build hard-word list")
    else:
        subtitle_raw = None
        if subtitle_path is None:
            subtitle_path = bot._do_download_movie(movie_name, year, imdb_id=imdb_id)
            if not subtitle_path:
                raise HTTPException(status_code=404, detail="Subtitle download failed")

    ok, out_dir, err, _metrics = bot._do_translate(
        episode_dir, subtitle_path, subtitle_raw=subtitle_raw
    )
    if not ok or out_dir is None:
        raise HTTPException(status_code=500, detail=err or "Translation failed")
    return out_dir


def _fake_context(translations_dir: Path) -> SimpleNamespace:
    info = bot._read_translation_info_json(translations_dir) or {}
    return SimpleNamespace(
        user_data={
            "last_translations_dir": str(translations_dir.resolve()),
            "last_series_name": str(info.get("series") or ""),
            "last_episode_dir": "",
        }
    )


def _header(translations_dir: Path) -> Tuple[str, str, bool, int, int, int]:
    info = bot._read_translation_info_json(translations_dir) or {}
    title = str(info.get("series") or translations_dir.parts[-3] if len(translations_dir.parts) >= 3 else "Unknown")
    is_movie = bool(info.get("is_movie", False))
    season = int(info.get("season_number", 0) or 0)
    episode = int(info.get("episode_number", 0) or 0)
    year = int(info.get("year", 0) or 0)
    if is_movie:
        subtitle = str(year) if year else ""
    else:
        subtitle = f"S{season} E{episode}" if season and episode else ""
    return title, subtitle, is_movie, season, episode, year


def _dictionary(user_id: str) -> Dict[str, Dict[str, str]]:
    data = bot._load_user_dictionary_map()
    return data.get(str(user_id), {})


def _set_dictionary(user_id: str, words: Dict[str, Dict[str, str]]) -> None:
    data = bot._load_user_dictionary_map()
    data[str(user_id)] = words
    bot._save_user_dictionary_map(data)


def _item_key(word: str, translation: str) -> str:
    return bot._dict_entry_key(word, translation)


def _word_items(
    rows: List[Tuple[str, str, str]],
    *,
    user_id: str = "",
    limit: int = 80,
) -> Tuple[List[WordItem], int, bool]:
    saved = _dictionary(user_id) if user_id else {}
    total = len(rows)
    visible = rows[:limit]
    items = [
        WordItem(
            word=w,
            translation=t,
            example=ex,
            saved=_item_key(w, t) in saved,
        )
        for w, t, ex in visible
    ]
    return items, total, total > len(visible)


def _subtitle_path(translations_dir: Path) -> Optional[Path]:
    ctx = _fake_context(translations_dir)
    title, _subtitle, is_movie, season, episode, year = _header(translations_dir)
    episode_dir = bot._resolve_episode_dir(translations_dir, ctx)
    return bot._subtitle_path_for_loaded_title(
        title,
        season,
        episode,
        is_movie=is_movie,
        year=year,
        episode_dir=episode_dir,
        translations_dir=translations_dir,
    )


def _available_lists(translations_dir: Path) -> List[ListKind]:
    lists: List[ListKind] = ["frequent_c", "frequent_b", "rare_c", "rare_b", "phrasal", "idioms"]
    return lists


def _ensure_rare(translations_dir: Path, kind: ListKind) -> None:
    from translate_tier_translations import (
        TIER_4_RARE_B_CSV,
        TIER_4_RARE_C_CSV,
        TIER_ID_TIER_4B,
        TIER_ID_TIER_4C,
        load_tier_words,
    )

    if kind == "rare_c":
        out_name = bot.TIER_4_RARE_C_TRANSLATIONS_CSV
        tier_csv = TIER_4_RARE_C_CSV
        tier_id = TIER_ID_TIER_4C
    elif kind == "rare_b":
        out_name = bot.TIER_4_RARE_B_TRANSLATIONS_CSV
        tier_csv = TIER_4_RARE_B_CSV
        tier_id = TIER_ID_TIER_4B
    else:
        return
    if (translations_dir / out_name).is_file():
        return
    ctx = _fake_context(translations_dir)
    episode_dir = bot._resolve_episode_dir(translations_dir, ctx)
    if episode_dir is None:
        raise HTTPException(status_code=404, detail="Tier list folder not found")
    if not load_tier_words(episode_dir, tier_csv):
        return
    ok, _out_dir, err, _metrics = bot._do_translate(
        episode_dir, _subtitle_path(translations_dir), tier_ids=frozenset({tier_id})
    )
    if not ok:
        raise HTTPException(status_code=500, detail=err or "Rare list translation failed")


def _ensure_phrasal_or_idioms(translations_dir: Path, kind: ListKind) -> None:
    if kind == "phrasal" and (translations_dir / bot.PHRASAL_VERBS_CSV).is_file():
        return
    if kind == "idioms" and (translations_dir / bot.IDIOMATIC_EXPRESSIONS_CSV).is_file():
        return

    api_key = bot.resolve_openai_api_key() or ""
    if not api_key:
        raise HTTPException(status_code=500, detail="OpenAI API key is missing")
    title, _subtitle, _is_movie, season, episode, _year = _header(translations_dir)
    subtitle_path = _subtitle_path(translations_dir)
    if subtitle_path is None:
        raise HTTPException(status_code=404, detail="Subtitle file not found")
    if kind == "phrasal":
        ok = bot._run_extract_phrasal_verbs(subtitle_path, translations_dir, title, api_key)
    elif kind == "idioms":
        ok = bot._run_extract_idiomatic_expressions(
            subtitle_path, translations_dir, title, api_key, season, episode
        )
    else:
        return
    if not ok:
        raise HTTPException(status_code=500, detail=f"{kind} extraction failed")


def _list_response(
    translations_dir: Path,
    kind: ListKind,
    *,
    user_id: str = "",
    limit: int = 80,
) -> ListResponse:
    title, subtitle, _is_movie, _season, _episode, _year = _header(translations_dir)
    source_id = _encode_id(translations_dir)
    sp = _subtitle_path(translations_dir)

    if kind == "frequent_c":
        rows = bot._attach_subtitle_examples(bot._load_translations_list(translations_dir), sp)
        items, total, truncated = _word_items(rows, user_id=user_id, limit=limit)
    elif kind == "frequent_b":
        b1, b2 = bot._load_b_level_pairs(translations_dir)
        rows = bot._attach_subtitle_examples([*b1, *b2], sp)
        items, total, truncated = _word_items(rows, user_id=user_id, limit=limit)
    elif kind == "rare_c":
        _ensure_rare(translations_dir, kind)
        rows = bot._attach_subtitle_examples(
            bot._load_translation_pairs_csv(translations_dir / bot.TIER_4_RARE_C_TRANSLATIONS_CSV),
            sp,
        )
        items, total, truncated = _word_items(rows, user_id=user_id, limit=limit)
    elif kind == "rare_b":
        _ensure_rare(translations_dir, kind)
        rows = bot._attach_subtitle_examples(
            bot._load_translation_pairs_csv(translations_dir / bot.TIER_4_RARE_B_TRANSLATIONS_CSV),
            sp,
        )
        items, total, truncated = _word_items(rows, user_id=user_id, limit=limit)
    elif kind == "phrasal":
        _ensure_phrasal_or_idioms(translations_dir, kind)
        rows = [
            WordItem(word=w, translation=t, example=ex, frequency=freq, score=score)
            for w, freq, t, ex, score in bot._load_phrasal_rows(translations_dir)[:limit]
        ]
        total = bot._csv_data_row_count(translations_dir / bot.PHRASAL_VERBS_CSV)
        items = rows
        truncated = total > len(items)
    elif kind == "idioms":
        _ensure_phrasal_or_idioms(translations_dir, kind)
        rows = [
            WordItem(word=w, translation=t, example=ex, frequency=freq, score=score)
            for w, freq, t, ex, score in bot._load_idiom_rows(translations_dir)[:limit]
        ]
        total = bot._csv_data_row_count(translations_dir / bot.IDIOMATIC_EXPRESSIONS_CSV)
        items = rows
        truncated = total > len(items)
    else:
        raise HTTPException(status_code=404, detail="Unknown list kind")

    return ListResponse(
        id=source_id,
        kind=kind,
        title=title,
        subtitle=subtitle,
        total=total,
        items=items,
        truncated=truncated,
    )


def _title_summary(translations_dir: Path, user_id: str = "") -> TitleSummary:
    title, subtitle, is_movie, _season, _episode, _year = _header(translations_dir)
    lists = {
        "frequent_c": _list_response(
            translations_dir, "frequent_c", user_id=user_id, limit=25
        ),
        "frequent_b": _list_response(
            translations_dir, "frequent_b", user_id=user_id, limit=25
        ),
    }
    return TitleSummary(
        id=_encode_id(translations_dir),
        media_type="movie" if is_movie else "tv",
        title=title,
        subtitle=subtitle,
        translations_dir=str(translations_dir.relative_to(bot.BASE_DIR)),
        available_lists=_available_lists(translations_dir),
        lists=lists,
    )


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.post("/api/titles/load", response_model=LoadTitleResponse)
async def load_title(req: LoadTitleRequest, user_id: str = "") -> LoadTitleResponse:
    identity, confirmation = _resolve_or_confirm(req)
    if confirmation is not None:
        return confirmation
    if identity is None:
        raise HTTPException(status_code=400, detail="Could not resolve title")

    def _work() -> Path:
        if identity.get("media_type") == "movie":
            return _ensure_movie_loaded(identity)
        return _ensure_series_loaded(identity)

    translations_dir = await asyncio.to_thread(_work)
    return LoadTitleResponse(
        status="ready",
        title=_title_summary(translations_dir, user_id=user_id),
    )


@app.get("/api/titles/{title_id}/lists/{kind}", response_model=ListResponse)
async def get_list(
    title_id: str,
    kind: ListKind,
    user_id: str = "",
    limit: int = 80,
) -> ListResponse:
    translations_dir = _decode_id(title_id)
    return await asyncio.to_thread(
        lambda: _list_response(translations_dir, kind, user_id=user_id, limit=limit)
    )


@app.get("/api/dictionary")
def get_dictionary(user_id: str) -> Dict[str, List[WordItem]]:
    rows = list(_dictionary(user_id).values())
    return {
        "items": [
            WordItem(
                word=str(row.get("word") or ""),
                translation=str(row.get("translation") or ""),
                example=str(row.get("example") or ""),
                saved=True,
            )
            for row in rows
        ]
    }


@app.post("/api/dictionary/toggle")
def toggle_dictionary(req: DictionaryToggleRequest) -> Dict[str, Any]:
    words = _dictionary(req.user_id)
    key = _item_key(req.word, req.translation)
    if key in words:
        words.pop(key, None)
        saved = False
    else:
        words[key] = {
            "word": req.word,
            "translation": req.translation,
            "example": req.example,
            "source_title": req.source_title,
            "source_id": req.source_id,
        }
        saved = True
    _set_dictionary(req.user_id, words)
    return {"saved": saved, "count": len(words)}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("mobile_api:app", host="0.0.0.0", port=8000, reload=True)
