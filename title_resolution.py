#!/usr/bin/env python3
"""
Resolve user-entered movie/TV titles against TMDB (or GPT fallback) before subtitle download.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any, Dict, List, Literal, Optional, Tuple

import requests

from env_config import get_tmdb_api_key, resolve_openai_api_key

TMDB_BASE = "https://api.themoviedb.org/3"
OPENAI_HTTP_TIMEOUT_SEC = 45.0

Confidence = Literal["high", "low"]
MediaType = Literal["movie", "tv"]

_TITLE_SCORE_HIGH = 0.88
_TITLE_SCORE_MIN = 0.70
_AMBIGUITY_GAP = 0.12
_CLEAR_WINNER_GAP = 0.15


def _normalize_title(text: str) -> str:
    t = re.sub(r"[^\w\s]", " ", (text or "").lower())
    return re.sub(r"\s+", " ", t).strip()


def _title_similarity(a: str, b: str) -> float:
    na, nb = _normalize_title(a), _normalize_title(b)
    if not na or not nb:
        return 0.0
    return SequenceMatcher(None, na, nb).ratio()


def _release_year(release_date: str) -> int:
    if not release_date or len(release_date) < 4:
        return 0
    try:
        return int(release_date[:4])
    except ValueError:
        return 0


def _tmdb_get(path: str, api_key: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    q: Dict[str, Any] = {"api_key": api_key}
    if params:
        q.update(params)
    url = f"{TMDB_BASE}{path}"
    r = requests.get(url, params=q, timeout=20)
    r.raise_for_status()
    return r.json()


def _movie_display_name(item: Dict[str, Any]) -> str:
    return (item.get("title") or item.get("original_title") or "").strip() or "Unknown"


def _tv_display_name(item: Dict[str, Any]) -> str:
    return (item.get("name") or item.get("original_name") or "").strip() or "Unknown"


def _fetch_imdb_id(api_key: str, media_type: MediaType, tmdb_id: int) -> Optional[str]:
    try:
        path = f"/movie/{tmdb_id}/external_ids" if media_type == "movie" else f"/tv/{tmdb_id}/external_ids"
        data = _tmdb_get(path, api_key)
        imdb = (data.get("imdb_id") or "").strip()
        if imdb:
            return imdb
    except Exception:
        pass
    return None


@dataclass
class ResolvedTitle:
    media_type: MediaType
    canonical_title: str
    year: int = 0
    season: int = 1
    episode: int = 1
    tmdb_id: Optional[int] = None
    imdb_id: Optional[str] = None
    confidence: Confidence = "low"
    issue: Optional[str] = None
    user_parsed: Dict[str, Any] = field(default_factory=dict)
    alternatives: List["ResolvedTitle"] = field(default_factory=list)
    reason: str = ""

    def to_identity_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "media_type": self.media_type,
            "canonical_title": self.canonical_title,
            "year": self.year,
            "season": self.season,
            "episode": self.episode,
            "tmdb_id": self.tmdb_id,
            "imdb_id": self.imdb_id,
        }
        return d

    @classmethod
    def from_user_parsed(cls, user_parsed: Dict[str, Any]) -> "ResolvedTitle":
        mt = user_parsed.get("media_type", "movie")
        if mt == "tv":
            return cls(
                media_type="tv",
                canonical_title=str(user_parsed.get("series_name") or user_parsed.get("canonical_title") or "Unknown"),
                season=int(user_parsed.get("season", 1)),
                episode=int(user_parsed.get("episode", 1)),
                confidence="high",
                user_parsed=dict(user_parsed),
            )
        return cls(
            media_type="movie",
            canonical_title=str(user_parsed.get("movie_name") or user_parsed.get("canonical_title") or "Unknown"),
            year=int(user_parsed.get("year", 0)),
            confidence="high",
            user_parsed=dict(user_parsed),
        )


def _candidate_from_movie_item(
    item: Dict[str, Any],
    *,
    season: int = 1,
    episode: int = 1,
    score: float = 0.0,
) -> ResolvedTitle:
    title = _movie_display_name(item)
    year = _release_year(item.get("release_date") or "")
    return ResolvedTitle(
        media_type="movie",
        canonical_title=title,
        year=year,
        season=season,
        episode=episode,
        tmdb_id=int(item.get("id") or 0) or None,
        confidence="low",
        reason=f"score={score:.2f}",
    )


def _candidate_from_tv_item(
    item: Dict[str, Any],
    *,
    season: int,
    episode: int,
    score: float = 0.0,
) -> ResolvedTitle:
    title = _tv_display_name(item)
    return ResolvedTitle(
        media_type="tv",
        canonical_title=title,
        season=season,
        episode=episode,
        tmdb_id=int(item.get("id") or 0) or None,
        confidence="low",
        reason=f"score={score:.2f}",
    )


def _search_movies(api_key: str, query: str, year: int = 0) -> List[Dict[str, Any]]:
    params: Dict[str, Any] = {"query": query}
    if year and year > 0:
        params["year"] = str(year)
    data = _tmdb_get("/search/movie", api_key, params)
    return list(data.get("results") or [])


def _search_tv(api_key: str, query: str) -> List[Dict[str, Any]]:
    data = _tmdb_get("/search/tv", api_key, {"query": query})
    return list(data.get("results") or [])


def _score_movie_results(
    results: List[Dict[str, Any]], query_title: str
) -> List[Tuple[float, ResolvedTitle]]:
    scored: List[Tuple[float, ResolvedTitle]] = []
    for item in results:
        name = _movie_display_name(item)
        score = _title_similarity(query_title, name)
        scored.append((score, _candidate_from_movie_item(item, score=score)))
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored


def _score_tv_results(
    results: List[Dict[str, Any]],
    query_title: str,
    season: int,
    episode: int,
) -> List[Tuple[float, ResolvedTitle]]:
    scored: List[Tuple[float, ResolvedTitle]] = []
    for item in results:
        name = _tv_display_name(item)
        score = _title_similarity(query_title, name)
        scored.append(
            (score, _candidate_from_tv_item(item, season=season, episode=episode, score=score))
        )
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored


def _tv_season_episode_count(api_key: str, tmdb_id: int, season: int) -> int:
    try:
        data = _tmdb_get(f"/tv/{tmdb_id}/season/{season}", api_key)
        eps = data.get("episodes") or []
        return len(eps)
    except Exception:
        return 0


def resolve_movie(
    movie_name: str,
    year: int,
    *,
    raw_input: str = "",
    tmdb_api_key: Optional[str] = None,
) -> ResolvedTitle:
    """Resolve movie title via TMDB; falls back to GPT when key missing or no results."""
    user_parsed: Dict[str, Any] = {
        "media_type": "movie",
        "movie_name": movie_name,
        "year": year,
        "raw": raw_input or f"{movie_name} {year}".strip(),
    }
    api_key = (tmdb_api_key or get_tmdb_api_key() or "").strip()
    if api_key:
        result = _resolve_movie_tmdb(movie_name, year, api_key, user_parsed)
        if result.confidence == "high" or result.issue in (
            "year_mismatch",
            "ambiguous",
            "episode_out_of_range",
        ):
            return result
        if result.canonical_title and result.tmdb_id:
            return result
    gpt = _resolve_movie_gpt(movie_name, year, raw_input or user_parsed["raw"], user_parsed)
    return gpt


def _resolve_movie_tmdb(
    movie_name: str, year: int, api_key: str, user_parsed: Dict[str, Any]
) -> ResolvedTitle:
    query = movie_name.strip()
    results: List[Dict[str, Any]] = []
    if year > 0:
        results = _search_movies(api_key, query, year)
    if not results:
        results = _search_movies(api_key, query, 0)

    if not results:
        return ResolvedTitle(
            media_type="movie",
            canonical_title=movie_name,
            year=year,
            confidence="low",
            issue="not_found",
            user_parsed=user_parsed,
            reason="TMDB returned no results",
        )

    scored = _score_movie_results(results, query)
    if not scored:
        return ResolvedTitle(
            media_type="movie",
            canonical_title=movie_name,
            year=year,
            confidence="low",
            issue="not_found",
            user_parsed=user_parsed,
        )

    top_score, best = scored[0]
    second_score = scored[1][0] if len(scored) > 1 else 0.0
    best.user_parsed = user_parsed

    if top_score < _TITLE_SCORE_MIN:
        gpt = _resolve_movie_gpt(movie_name, year, user_parsed.get("raw", ""), user_parsed)
        if gpt.confidence == "high":
            return gpt
        best.issue = "not_found"
        best.confidence = "low"
        best.alternatives = [c for _, c in scored[1:3]]
        return best

    if best.tmdb_id:
        best.imdb_id = _fetch_imdb_id(api_key, "movie", best.tmdb_id)

    # Year mismatch: title matches but user year wrong
    user_year = year
    tmdb_year = best.year
    if user_year > 0 and tmdb_year > 0 and user_year != tmdb_year and top_score >= _TITLE_SCORE_MIN:
        best.confidence = "low"
        best.issue = "year_mismatch"
        best.alternatives = [c for _, c in scored[1:3] if c.tmdb_id != best.tmdb_id]
        return best

    if len(scored) > 1 and (top_score - second_score) < _AMBIGUITY_GAP and top_score >= _TITLE_SCORE_MIN:
        best.confidence = "low"
        best.issue = "ambiguous"
        best.alternatives = [c for _, c in scored[1:3]]
        return best

    if top_score >= _TITLE_SCORE_HIGH and (
        user_year <= 0 or user_year == tmdb_year or (top_score - second_score) >= _CLEAR_WINNER_GAP
    ):
        best.confidence = "high"
        best.issue = None
        return best

    if top_score >= _TITLE_SCORE_MIN:
        best.confidence = "low"
        best.issue = "uncertain"
        best.alternatives = [c for _, c in scored[1:3]]
        return best

    best.confidence = "low"
    best.issue = "not_found"
    best.alternatives = [c for _, c in scored[1:3]]
    return best


def resolve_tv(
    series_name: str,
    season: int,
    episode: int,
    *,
    raw_input: str = "",
    tmdb_api_key: Optional[str] = None,
) -> ResolvedTitle:
    user_parsed: Dict[str, Any] = {
        "media_type": "tv",
        "series_name": series_name,
        "season": season,
        "episode": episode,
        "raw": raw_input or series_name,
    }
    api_key = (tmdb_api_key or get_tmdb_api_key() or "").strip()
    if api_key:
        result = _resolve_tv_tmdb(series_name, season, episode, api_key, user_parsed)
        if result.confidence == "high" or result.issue:
            return result
    return _resolve_tv_gpt(series_name, season, episode, raw_input or series_name, user_parsed)


def _resolve_tv_tmdb(
    series_name: str,
    season: int,
    episode: int,
    api_key: str,
    user_parsed: Dict[str, Any],
) -> ResolvedTitle:
    results = _search_tv(api_key, series_name.strip())
    if not results:
        return _resolve_tv_gpt(
            series_name, season, episode, user_parsed.get("raw", ""), user_parsed
        )

    scored = _score_tv_results(results, series_name, season, episode)
    if not scored:
        return ResolvedTitle(
            media_type="tv",
            canonical_title=series_name,
            season=season,
            episode=episode,
            confidence="low",
            issue="not_found",
            user_parsed=user_parsed,
        )

    top_score, best = scored[0]
    second_score = scored[1][0] if len(scored) > 1 else 0.0
    best.user_parsed = user_parsed

    if top_score < _TITLE_SCORE_MIN:
        return _resolve_tv_gpt(
            series_name, season, episode, user_parsed.get("raw", ""), user_parsed
        )

    if best.tmdb_id:
        best.imdb_id = _fetch_imdb_id(api_key, "tv", best.tmdb_id)
        ep_count = _tv_season_episode_count(api_key, best.tmdb_id, season)
        if ep_count > 0 and episode > ep_count:
            best.confidence = "low"
            best.issue = "episode_out_of_range"
            best.reason = f"Season {season} has {ep_count} episodes"
            best.alternatives = [c for _, c in scored[1:3]]
            return best

    if len(scored) > 1 and (top_score - second_score) < _AMBIGUITY_GAP and top_score >= _TITLE_SCORE_MIN:
        best.confidence = "low"
        best.issue = "ambiguous"
        best.alternatives = [c for _, c in scored[1:3]]
        return best

    if top_score >= _TITLE_SCORE_HIGH or (
        top_score >= _TITLE_SCORE_MIN and (top_score - second_score) >= _CLEAR_WINNER_GAP
    ):
        best.confidence = "high"
        best.issue = None
        return best

    best.confidence = "low"
    best.issue = "uncertain"
    best.alternatives = [c for _, c in scored[1:3]]
    return best


def _parse_gpt_json(content: str) -> Dict[str, Any]:
    text = (content or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```\w*\n?", "", text)
        text = re.sub(r"\n?```\s*$", "", text)
    return json.loads(text)


def _resolve_movie_gpt(
    movie_name: str, year: int, raw_input: str, user_parsed: Dict[str, Any]
) -> ResolvedTitle:
    api_key = resolve_openai_api_key()
    fallback = ResolvedTitle(
        media_type="movie",
        canonical_title=movie_name,
        year=year,
        confidence="low",
        issue="not_found",
        user_parsed=user_parsed,
        reason="GPT unavailable",
    )
    if not api_key:
        return fallback

    prompt = f"""The user wants English vocabulary from a movie subtitle. They entered: "{raw_input or movie_name}"

Extract the official movie title (IMDb/OpenSubtitles style) and release year.
Return ONLY JSON: {{"canonical_title": "...", "year": 2010, "confidence": "high"|"low", "reason": "..."}}
Use confidence "high" only when you are sure of title AND year. Wrong or guessed years → "low".
If not a movie title, confidence "low"."""

    try:
        from openai import OpenAI

        client = OpenAI(api_key=api_key, timeout=OPENAI_HTTP_TIMEOUT_SEC)
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": "Reply with a single JSON object for movie title resolution.",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_tokens=120,
        )
        data = _parse_gpt_json(response.choices[0].message.content or "")
        title = (data.get("canonical_title") or movie_name).strip()
        yr = int(data.get("year", year) or 0)
        conf: Confidence = "high" if (data.get("confidence") or "").lower() == "high" else "low"
        issue = None if conf == "high" else "gpt_uncertain"
        if year > 0 and yr > 0 and year != yr and _title_similarity(title, movie_name) >= 0.85:
            issue = "year_mismatch"
        return ResolvedTitle(
            media_type="movie",
            canonical_title=title,
            year=yr,
            confidence=conf,
            issue=issue,
            user_parsed=user_parsed,
            reason=(data.get("reason") or "")[:200],
        )
    except Exception as e:
        fallback.reason = str(e)[:200]
        return fallback


def _resolve_tv_gpt(
    series_name: str,
    season: int,
    episode: int,
    raw_input: str,
    user_parsed: Dict[str, Any],
) -> ResolvedTitle:
    api_key = resolve_openai_api_key()
    fallback = ResolvedTitle(
        media_type="tv",
        canonical_title=series_name,
        season=season,
        episode=episode,
        confidence="low",
        issue="not_found",
        user_parsed=user_parsed,
    )
    if not api_key:
        return fallback

    prompt = f"""The user wants vocabulary from a TV series subtitle. They entered: "{raw_input}"

Return ONLY JSON: {{"series_name": "...", "season": 1, "episode": 1, "confidence": "high"|"low", "reason": "..."}}
Official IMDb-style series name. confidence "high" only when sure."""

    try:
        from openai import OpenAI

        client = OpenAI(api_key=api_key, timeout=OPENAI_HTTP_TIMEOUT_SEC)
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": "Reply with a single JSON object for TV series resolution.",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_tokens=120,
        )
        data = _parse_gpt_json(response.choices[0].message.content or "")
        sn = (data.get("series_name") or series_name).strip()
        s = max(1, int(data.get("season", season)))
        e = max(1, int(data.get("episode", episode)))
        conf: Confidence = "high" if (data.get("confidence") or "").lower() == "high" else "low"
        changed = _title_similarity(sn, series_name) < 0.95 and conf != "high"
        issue = None if conf == "high" and not changed else "gpt_uncertain"
        if changed and conf == "high":
            issue = "title_corrected"
            conf = "low"
        return ResolvedTitle(
            media_type="tv",
            canonical_title=sn,
            season=s,
            episode=e,
            confidence=conf,
            issue=issue,
            user_parsed=user_parsed,
            reason=(data.get("reason") or "")[:200],
        )
    except Exception as e:
        fallback.reason = str(e)[:200]
        return fallback


async def resolve_movie_async(
    movie_name: str, year: int, *, raw_input: str = ""
) -> ResolvedTitle:
    import asyncio

    return await asyncio.to_thread(
        resolve_movie, movie_name, year, raw_input=raw_input
    )


async def resolve_tv_async(
    series_name: str, season: int, episode: int, *, raw_input: str = ""
) -> ResolvedTitle:
    import asyncio

    return await asyncio.to_thread(
        resolve_tv, series_name, season, episode, raw_input=raw_input
    )


def new_pending_token() -> str:
    return uuid.uuid4().hex[:12]


def _identity_dict_for_pending(resolved: ResolvedTitle) -> Dict[str, Any]:
    d = resolved.to_identity_dict()
    if resolved.media_type == "movie":
        d["movie_name"] = resolved.canonical_title
    else:
        d["series_name"] = resolved.canonical_title
    return d


def pending_to_dict(resolved: ResolvedTitle, token: str, raw: str) -> Dict[str, Any]:
    return {
        "token": token,
        "raw": raw,
        "suggestion": _identity_dict_for_pending(resolved),
        "user_parsed": resolved.user_parsed,
        "alternatives": [_identity_dict_for_pending(a) for a in resolved.alternatives[:3]],
        "issue": resolved.issue,
        "confidence": resolved.confidence,
        "canonical_title": resolved.canonical_title,
        "year": resolved.year,
        "season": resolved.season,
        "episode": resolved.episode,
        "media_type": resolved.media_type,
    }
