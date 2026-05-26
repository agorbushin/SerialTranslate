#!/usr/bin/env python3
"""
Telegram bot: request by series name → (use cache if present) → analyze subtitle → translate hard words → save to translations folder.
Uses existing tier lists and translations when found; shows step-by-step status like the archive.
"""

import asyncio
import csv
import hashlib
import json
import os
import re
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Collection, Dict, List, Literal, Optional, Tuple

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest
from telegram.helpers import escape_markdown
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)

from env_config import get_openai_api_key, get_opensubtitles_api_key, resolve_openai_api_key
from title_resolution import (
    ResolvedTitle,
    new_pending_token,
    pending_to_dict,
    resolve_movie_async,
    resolve_tv_async,
)
from translation_modes import DEFAULT_TRANSLATION_MODE

TELEGRAM_BOT_TOKEN = (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
OPENAI_API_KEY = get_openai_api_key()
OPENSUBTITLES_API_KEY = get_opensubtitles_api_key()

# Build/start time set when main() runs (see main())
BOT_BUILD_DATETIME = ""
# Shown in /start (tests assert this appears in the welcome text)
BOT_VERSION = "0.1"
BASE_DIR = Path(__file__).resolve().parent
SUBTITLE_BASE = BASE_DIR / "Subtitle"
TIERLIST_BASE = BASE_DIR / "Tier_lists"
TRANSLATIONS_BASE = BASE_DIR / "translations"
USER_DICTIONARY_JSON = BASE_DIR / "user_dictionary.json"
WORD_LINK_INDEX_JSON = BASE_DIR / "word_link_index.json"
# Rare-in-series lists (high English frequency, low frequency in this episode); see subtitle_analyzer tier_4 split
TIER_4_RARE_C_TRANSLATIONS_CSV = "tier_4_rare_c_translations.csv"
TIER_4_RARE_B_TRANSLATIONS_CSV = "tier_4_rare_b_translations.csv"
PHRASAL_VERBS_CSV = "phrasal_verbs.csv"
PHRASAL_VERBS_PREVIEW_LIMIT = 15
IDIOMATIC_EXPRESSIONS_CSV = "idiomatic_expressions.csv"
IDIOMS_PREVIEW_LIMIT = 15
# When False, /idioms and the Idioms button show a placeholder instead of extraction / CSV.
IDIOMS_FEATURE_ENABLED = False

_IDIOMS_WIP_MESSAGE = (
    "🚧 *Idioms — work in progress*\n\n"
    "We're polishing this feature so lists are clearer and more reliable.\n\n"
    "✨ *Still available:* word tiers, rare lists, and phrasal verbs — same as before.\n\n"
    "_Thanks for your patience._"
)
LATENCY_METRICS_BASE = BASE_DIR / "latency_metrics"
OPENAI_HTTP_TIMEOUT_SEC = 45.0


def _md1(text: str) -> str:
    """Escape for Telegram legacy Markdown when embedding user/model-derived titles."""
    return escape_markdown((text or "").strip(), version=1)


def _safe_user_id(update: Update, *, query=None) -> Optional[int]:
    user = query.from_user if query else update.effective_user
    if not user:
        return None
    try:
        return int(user.id)
    except (TypeError, ValueError):
        return None


def _load_user_dictionary_map() -> Dict[str, Dict[str, Dict[str, str]]]:
    if not USER_DICTIONARY_JSON.exists():
        return {}
    try:
        data = json.loads(USER_DICTIONARY_JSON.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {}
        out: Dict[str, Dict[str, Dict[str, str]]] = {}
        for uid, words in data.items():
            if isinstance(words, dict):
                out[str(uid)] = words
        return out
    except Exception:
        return {}


def _save_user_dictionary_map(data: Dict[str, Dict[str, Dict[str, str]]]) -> None:
    USER_DICTIONARY_JSON.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _dict_entry_key(word: str, translation: str) -> str:
    return f"{word.strip().lower()}::{translation.strip().lower()}"


def _load_word_link_index() -> Dict[str, Dict[str, str]]:
    if not WORD_LINK_INDEX_JSON.exists():
        return {}
    try:
        raw = json.loads(WORD_LINK_INDEX_JSON.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return {}
        return {str(k): v for k, v in raw.items() if isinstance(v, dict)}
    except Exception:
        return {}


def _save_word_link_index(data: Dict[str, Dict[str, str]]) -> None:
    WORD_LINK_INDEX_JSON.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _register_word_link_tokens(rows: List[Tuple[str, str, str]]) -> Dict[str, str]:
    """Map dict entry key → short token for t.me deep links."""
    index = _load_word_link_index()
    mapping: Dict[str, str] = {}
    for word, translation, example in rows:
        key = _dict_entry_key(word, translation)
        token = hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
        mapping[key] = token
        index[token] = {
            "word": word,
            "translation": translation,
            "example": example or "",
        }
    _save_word_link_index(index)
    return mapping


def _deep_link_for_word_token(bot_username: str, token: Optional[str]) -> Optional[str]:
    if not bot_username or not token:
        return None
    return f"https://t.me/{bot_username}?start=dw_{token}"


def _toggle_dictionary_word_by_token(user_id: int, token: str) -> bool:
    payload = _load_word_link_index().get(token)
    if not payload:
        return False
    word = (payload.get("word") or "").strip()
    translation = (payload.get("translation") or "").strip()
    if not word or not translation:
        return False
    words_map = _get_user_dictionary(user_id)
    key = _dict_entry_key(word, translation)
    if key in words_map:
        words_map.pop(key, None)
    else:
        words_map[key] = {
            "word": word,
            "translation": translation,
            "example": payload.get("example") or "",
            "saved_at": datetime.now().isoformat(),
        }
    _set_user_dictionary(user_id, words_map)
    return True


def _bot_username_from_context(context: ContextTypes.DEFAULT_TYPE) -> str:
    bot = getattr(context, "bot", None)
    if not bot:
        return ""
    return (getattr(bot, "username", None) or "").strip().lstrip("@")


def _persist_word_list_anchor(
    context: ContextTypes.DEFAULT_TYPE,
    *,
    chat_id: int,
    message_id: int,
    view: Dict[str, Any],
) -> None:
    context.user_data["word_list_anchor"] = {
        "chat_id": chat_id,
        "message_id": message_id,
        "view": view,
    }


def _get_user_dictionary(user_id: int) -> Dict[str, Dict[str, str]]:
    data = _load_user_dictionary_map()
    return data.get(str(user_id), {})


def _set_user_dictionary(user_id: int, words_map: Dict[str, Dict[str, str]]) -> None:
    data = _load_user_dictionary_map()
    data[str(user_id)] = words_map
    _save_user_dictionary_map(data)


def _is_show_my_words_text(text: str) -> bool:
    t = (text or "").strip().lower()
    return t in {"показать мои слова", "мои слова", "my words", "show my words"}


def _ms_since(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


# Tier folders often use Season 1/1 while the display title already includes the real ep (e.g. "Fallout S2 E5").
# Avoid showing "Fallout S2 E5 S1E1" by not appending folder S/E when the name already has an S…E… label.
_EPISODE_LABEL_IN_SERIES_NAME = re.compile(
    r"\bS\s*\d{1,2}\s*E\s*\d{1,2}\b",
    re.IGNORECASE,
)


def _tv_episode_suffix(series_name: str, season: int, episode: int) -> str:
    """Return ' S1E2' for TV display lines unless series_name already encodes an episode label."""
    name = (series_name or "").strip()
    if name and _EPISODE_LABEL_IN_SERIES_NAME.search(name):
        return ""
    if season <= 0 and episode <= 0:
        return ""
    return f" S{season}E{episode}"


def _new_latency(raw_input: str, mode: str) -> Dict[str, Any]:
    return {
        "request_id": uuid.uuid4().hex,
        "mode": mode,
        "raw_input": raw_input,
        "started_at": datetime.now().isoformat(),
        "finished_at": None,
        "status": "in_progress",
        "branch": "",
        "identity": {},
        "phase_timings_ms": {},
        "timings_ms": {"total_e2e_ms": 0},
        "analyze_metrics": None,
        "translator_metrics": None,
        "error": None,
    }


def _write_latency(metrics: Dict[str, Any]) -> None:
    try:
        LATENCY_METRICS_BASE.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        req_id = metrics.get("request_id", "unknown")
        out = LATENCY_METRICS_BASE / f"{ts}_{req_id}.json"
        out.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"Warning: could not write latency metrics: {e}")


async def _write_latency_async(metrics: Dict[str, Any]) -> None:
    await asyncio.to_thread(_write_latency, metrics)


def keyboard_discovery(context: ContextTypes.DEFAULT_TYPE) -> InlineKeyboardMarkup:
    """Pre-load: start another TV show. Movies: use /movie."""
    _ = context  # reserved for future (e.g. optional Next movie)
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("📺 Next series", callback_data="next_series")]]
    )


def keyboard_loaded(
    context: ContextTypes.DEFAULT_TYPE,
    *,
    extra_phrasal_count: Optional[int] = None,
    extra_idiom_count: Optional[int] = None,
) -> InlineKeyboardMarkup:
    """After a title is loaded: word lists, phrasal, idioms, optional full-list rows, next series."""
    _ = context
    rows: List[List[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton("📗 Frequent C", callback_data="frequent_c_words"),
            InlineKeyboardButton("📗 Frequent B", callback_data="b_level_words"),
        ],
        [
            InlineKeyboardButton("📉 Rare C", callback_data="rare_c_series"),
            InlineKeyboardButton("📉 Rare B", callback_data="rare_b_series"),
        ],
        [
            InlineKeyboardButton("🔤 Phrasal verbs", callback_data="phrasal_verbs"),
            InlineKeyboardButton("💬 Idioms", callback_data="idiomatic_expressions"),
        ],
    ]
    if (
        extra_phrasal_count is not None
        and extra_phrasal_count > PHRASAL_VERBS_PREVIEW_LIMIT
    ):
        rows.append(
            [
                InlineKeyboardButton(
                    f"📋 All phrasal verbs ({extra_phrasal_count})",
                    callback_data="phrasal_verbs_all",
                )
            ]
        )
    if extra_idiom_count is not None and extra_idiom_count > IDIOMS_PREVIEW_LIMIT:
        rows.append(
            [
                InlineKeyboardButton(
                    f"📋 All idioms ({extra_idiom_count})",
                    callback_data="idiomatic_expressions_all",
                )
            ]
        )
    rows.append([InlineKeyboardButton("📺 Next series", callback_data="next_series")])
    rows.append([InlineKeyboardButton("📚 My dictionary", callback_data="show_my_words")])
    return InlineKeyboardMarkup(rows)


def _csv_data_row_count(csv_path: Path) -> int:
    """Number of data rows (excluding header)."""
    if not csv_path.is_file():
        return 0
    try:
        with open(csv_path, encoding="utf-8") as f:
            return max(0, sum(1 for _ in f) - 1)
    except OSError:
        return 0


def _extra_preview_count(csv_path: Path, preview_limit: int) -> Optional[int]:
    """If file has more than preview_limit rows, return total count for 'show all' button."""
    n = _csv_data_row_count(csv_path)
    return n if n > preview_limit else None


def _parse_series_input(text: str) -> Tuple[str, int, int]:
    """
    Parse user message into series name and optional season/episode (simple regex only).
    Examples: "Game of Thrones", "Fallout s2 e3", "Breaking Bad S01E05"
    Returns (series_name, season, episode); season/episode default to 1.
    """
    text = (text or "").strip()
    season, episode = 1, 1
    m = None
    # Match "season N episode M" or "s N e M" at end (season first)
    m = re.search(
        r"\b[sS](?:eason)?\s*(\d+)\s*[eE](?:p(?:isode)?)?\s*(\d+)\s*$",
        text,
    )
    if m:
        season = int(m.group(1))
        episode = int(m.group(2))
        text = text[: m.start()].strip(" .,;")
    # Match "ep N season M" at end (episode first)
    if not m:
        m = re.search(
            r"\b[eE](?:p(?:isode)?)?\s*(\d+)\s*[sS](?:eason)?\s*(\d+)\s*$",
            text,
        )
        if m:
            episode = int(m.group(1))
            season = int(m.group(2))
            text = text[: m.start()].strip(" .,;")
    # S01E05 style at end
    if not m:
        m = re.search(r"\b[Ss]\s*(\d+)\s*[Ee]\s*(\d+)\s*$", text)
        if m:
            season = int(m.group(1))
            episode = int(m.group(2))
            text = text[: m.start()].strip(" .,;")
    series_name = re.sub(r"\s+", " ", text).strip()
    if not series_name:
        series_name = "Unknown"
    elif len(series_name) > 1 and not any(c.isupper() for c in series_name[1:]):
        series_name = series_name.title()
    return series_name, season, episode


def _raw_looks_like_tv_season_episode(text: str) -> bool:
    """True if text contains explicit TV season/episode cues (not a bare trailing year)."""
    t = (text or "").strip()
    if not t:
        return False
    if re.search(
        r"\b[sS](?:eason)?\s*\d+\s*[eE](?:p(?:isode)?)?\s*\d+",
        t,
    ):
        return True
    if re.search(
        r"\b[eE](?:p(?:isode)?)?\s*\d+\s*[sS](?:eason)?\s*\d+",
        t,
    ):
        return True
    if re.search(r"\b[Ss]\s*\d+\s*[Ee]\s*\d+", t):
        return True
    if re.search(r"\b(?:season|episode)\s+\d+", t, re.I):
        return True
    return False


def _should_auto_route_movie_from_series_mode(raw: str) -> bool:
    """Title + trailing year (movie-shaped) while mode is still series — use movie pipeline."""
    _, year = _parse_movie_input(raw)
    if year <= 0:
        return False
    if _raw_looks_like_tv_season_episode(raw):
        return False
    return True


def _parse_movie_input(text: str) -> Tuple[str, int]:
    """
    Parse user message into movie name and optional year.
    Examples: "Inception", "The Matrix 1999", "Dune (2021)"
    Returns (movie_name, year); year defaults to 0 if not found.
    """
    text = (text or "").strip()
    year = 0
    # Match year at end: 1999, (1999), (2021)
    m = re.search(r"\(?(19\d{2}|20\d{2})\)?\s*$", text)
    if m:
        year = int(m.group(1))
        text = text[: m.start()].strip(" .,;()")
    movie_name = re.sub(r"\s+", " ", text).strip()
    if not movie_name:
        movie_name = "Unknown"
    elif len(movie_name) > 1 and not any(c.isupper() for c in movie_name[1:]):
        movie_name = movie_name.title()
    return movie_name, year


def _simple_parse_likely_failed(raw: str, series_name: str, season: int, episode: int) -> bool:
    """True if the raw input looks like it had season/episode info that simple parse may have missed."""
    raw_lower = raw.lower()
    has_ep_or_season = "ep " in raw_lower or "episode" in raw_lower or "season" in raw_lower
    # Using defaults while user typed something like "ep 2 season 2"
    if (season, episode) == (1, 1) and has_ep_or_season:
        return True
    # Series name still contains episode-like tokens (e.g. "Game Of Thrones Ep 2 Season 2")
    name_lower = series_name.lower()
    if " ep " in name_lower or " season " in name_lower or " episode " in name_lower:
        return True
    return False


async def _normalize_with_chatgpt(user_input: str) -> Optional[Tuple[str, int, int]]:
    """
    Ask ChatGPT to normalize user input into (series_name, season, episode).
    Returns None if API key missing, request fails, or result is UNKNOWN.
    """
    api_key = resolve_openai_api_key()
    if not api_key or not user_input.strip():
        return None
    prompt = f"""The user wants frequent hard words from a TV series (with English dictionary-style glosses). They entered: "{user_input}"

Extract:
1. The official TV series name (as used on IMDb / OpenSubtitles), e.g. "Game of Thrones", "Breaking Bad".
2. Season number (integer, default 1 if not mentioned).
3. Episode number (integer, default 1 if not mentioned).

Return ONLY a JSON object with exactly these keys: "series_name", "season", "episode".
Examples:
- "game of thrones ep 2 season 2" -> {{"series_name": "Game of Thrones", "season": 2, "episode": 2}}
- "fallout s1 e3" -> {{"series_name": "Fallout", "season": 1, "episode": 3}}
- "breaking bad" -> {{"series_name": "Breaking Bad", "season": 1, "episode": 1}}
If the input is too vague or not a series name, set series_name to "UNKNOWN". Return only valid JSON, no markdown."""

    def _normalize_sync() -> Optional[Tuple[str, int, int]]:
        from openai import OpenAI
        client = OpenAI(api_key=api_key, timeout=OPENAI_HTTP_TIMEOUT_SEC)
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You extract TV series name and season/episode from user text. Reply only with a JSON object."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_tokens=80,
        )
        content = (response.choices[0].message.content or "").strip()
        # Strip markdown code block if present
        if content.startswith("```"):
            content = re.sub(r"^```\w*\n?", "", content)
            content = re.sub(r"\n?```\s*$", "", content)
        data = json.loads(content)
        sn = (data.get("series_name") or "").strip() or "UNKNOWN"
        if sn.upper() == "UNKNOWN":
            return None
        season = int(data.get("season", 1))
        episode = int(data.get("episode", 1))
        if season < 1:
            season = 1
        if episode < 1:
            episode = 1
        return (sn, season, episode)
    try:
        return await asyncio.to_thread(_normalize_sync)
    except Exception as e:
        print(f"ChatGPT normalization failed: {e}")
        return None


async def _correct_series_title_typos(series_name: str) -> str:
    """
    Fix obvious typos in a parsed TV series title using a small chat model.
    Returns the original string if the API key is missing, the title is empty/Unknown, or on failure.
    """
    name = (series_name or "").strip()
    api_key = resolve_openai_api_key()
    if not api_key or not name or name.upper() == "UNKNOWN":
        return name
    model = (os.environ.get("OPENAI_SERIES_SPELLCHECK_MODEL") or "").strip() or "gpt-4o-mini"
    prompt = f"""The following string is a TV series title (season/episode was already removed). Fix only clear spelling mistakes or obvious typos to the usual IMDb-style official title. Do not substitute a different show. If the title is already correct or you are uncertain, return it unchanged.

Title: "{name}"

Return ONLY a JSON object with exactly this key: "series_name". No markdown."""

    def _spellfix_sync() -> str:
        from openai import OpenAI

        client = OpenAI(api_key=api_key, timeout=OPENAI_HTTP_TIMEOUT_SEC)
        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": 'You fix TV series title spelling only. Reply with a single JSON object {"series_name": "..."}.',
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            max_tokens=60,
        )
        content = (response.choices[0].message.content or "").strip()
        if content.startswith("```"):
            content = re.sub(r"^```\w*\n?", "", content)
            content = re.sub(r"\n?```\s*$", "", content)
        data = json.loads(content)
        sn = (data.get("series_name") or "").strip()
        if not sn:
            return name
        return sn

    try:
        return await asyncio.to_thread(_spellfix_sync)
    except Exception as e:
        print(f"ChatGPT title spellfix failed: {e}")
        return name


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data["mode"] = "series"
    args = context.args if isinstance(getattr(context, "args", None), list) else []
    if args and str(args[0]).startswith("dw_"):
        await _handle_dictionary_deep_link(update, context, str(args[0])[3:])
        return
    build = BOT_BUILD_DATETIME or "unknown"
    await update.message.reply_text(
        "👋 Welcome to **SerialTranslate**.\n\n"
        "**What you get:** harder English words that show up *often* in a specific TV episode or "
        "movie — with short English dictionary glosses, built from real subtitles.\n\n"
        "**What to do:** tap **Next series**, then send the show name (with season/episode if you want). "
        "For a **movie**, use the /movie command, then send the title.\n\n"
        "Examples: _Fallout s2 e3_, _Inception_, _The Matrix 1999_.\n\n"
        f"_v{BOT_VERSION} · {build}_",
        parse_mode="Markdown",
        reply_markup=keyboard_discovery(context),
    )


async def next_series(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data["mode"] = "series"
    await update.message.reply_text(
        "📺 **Which TV series?**\n\n"
        "Send the show name and, if you want a specific episode, season/episode "
        "(e.g. _Fallout_, _Game of Thrones s2 e3_).",
        parse_mode="Markdown",
        reply_markup=keyboard_discovery(context),
    )


async def next_movie(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data["mode"] = "movie"
    await update.message.reply_text(
        "🎬 **Which movie?**\n\n"
        "Send the title (optional year helps), e.g. _Inception_, _The Matrix 1999_, _Dune (2021)_.",
        parse_mode="Markdown",
        reply_markup=keyboard_discovery(context),
    )


def _find_existing(
    series_name: str, season: int, episode: int
) -> Tuple[Optional[Path], Optional[Path], Optional[Path]]:
    """
    Look for existing tier list and/or translations for this series/season/episode.
    Returns (episode_dir, translations_dir, subtitle_path).
    - episode_dir: Tier_lists/.../tier_1_hard_usable_words.csv exists
    - translations_dir: translations/.../tier_1_translations.csv exists
    - subtitle_path: Subtitle file path (from get_subtitle_path or episode_info)
    """
    from download_subtitles import (
        get_tierlist_episode_dir,
        get_translations_episode_dir,
        get_subtitle_path,
    )

    episode_dir = get_tierlist_episode_dir(TIERLIST_BASE, series_name, season, episode)
    has_tier = episode_dir.exists() and (episode_dir / "tier_1_hard_usable_words.csv").exists()

    translations_dir = get_translations_episode_dir(
        TRANSLATIONS_BASE, series_name, season, episode
    )
    has_translations = (translations_dir / "tier_1_translations.csv").exists()

    subtitle_path = get_subtitle_path(SUBTITLE_BASE, series_name, season, episode)
    if not subtitle_path.exists() and episode_dir.exists():
        info_file = episode_dir / "episode_info.json"
        if info_file.exists():
            try:
                info = json.loads(info_file.read_text(encoding="utf-8"))
                sn = info.get("series") or series_name
                s = int(info.get("season_number", season))
                e = int(info.get("episode_number", episode))
                sub_name = info.get("subtitle_file")
                if sub_name:
                    subtitle_path = (
                        SUBTITLE_BASE / sn / f"Season {s}" / sub_name
                    )
            except Exception:
                pass

    return (
        episode_dir if has_tier else None,
        translations_dir if has_translations else None,
        subtitle_path if subtitle_path.exists() else None,
    )


def _find_existing_movie(
    movie_name: str, year: int
) -> Tuple[Optional[Path], Optional[Path], Optional[Path]]:
    """
    Look for existing tier list and/or translations for this movie.
    Returns (episode_dir, translations_dir, subtitle_path).
    """
    from download_subtitles import (
        get_tierlist_movie_dir,
        get_translations_movie_dir,
        get_movie_subtitle_path,
    )

    episode_dir = get_tierlist_movie_dir(TIERLIST_BASE, movie_name, year)
    has_tier = episode_dir.exists() and (episode_dir / "tier_1_hard_usable_words.csv").exists()

    translations_dir = get_translations_movie_dir(TRANSLATIONS_BASE, movie_name, year)
    has_translations = (translations_dir / "tier_1_translations.csv").exists()

    subtitle_path = get_movie_subtitle_path(SUBTITLE_BASE, movie_name, year)
    if not subtitle_path.exists() and episode_dir.exists():
        info_file = episode_dir / "episode_info.json"
        if info_file.exists():
            try:
                info = json.loads(info_file.read_text(encoding="utf-8"))
                mn = info.get("series") or movie_name
                yr = int(info.get("year", year))
                sub_name = info.get("subtitle_file")
                if sub_name:
                    subtitle_path = SUBTITLE_BASE / "Movies" / mn / sub_name
            except Exception:
                pass

    return (
        episode_dir if has_tier else None,
        translations_dir if has_translations else None,
        subtitle_path if subtitle_path.exists() else None,
    )


def _do_download(series_name: str, season: int, episode: int) -> Optional[Path]:
    """Download subtitle. Returns subtitle path or None."""
    from download_subtitles import get_subtitle_path, download_subtitle

    path = download_subtitle(
        series_name,
        season,
        episode,
        base_dir=SUBTITLE_BASE,
        api_key=OPENSUBTITLES_API_KEY,
    )
    return path


def _do_analyze(
    subtitle_path: Path,
) -> Tuple[Optional[Path], Dict[str, int], Optional[str]]:
    """Run tier pipeline for series. Returns (episode_dir_or_none, analyze_metrics, subtitle_raw_for_translate)."""
    from subtitle_analyzer import run_pipeline

    analyze_metrics: Dict[str, int] = {}
    handoff: Dict[str, Any] = {}
    oa_key = resolve_openai_api_key() or None
    episode_dir = run_pipeline(
        subtitle_path=subtitle_path,
        base_dir=BASE_DIR,
        tierlist_base_dir=TIERLIST_BASE,
        max_english_freq=20_000_000,
        openai_api_key=oa_key,
        metrics_out=analyze_metrics,
        handoff_out=handoff,
        skip_if_outputs_fresh=True,
    )
    if not episode_dir or not (episode_dir / "tier_1_hard_usable_words.csv").exists():
        return None, analyze_metrics, None
    raw = handoff.get("subtitle_raw")
    return episode_dir, analyze_metrics, raw if isinstance(raw, str) else None


def _do_download_movie(
    movie_name: str,
    year: int,
    *,
    imdb_id: Optional[str] = None,
) -> Optional[Path]:
    """Download movie subtitle. Returns subtitle path or None."""
    from download_movie_subtitles import download_movie_subtitle

    path = download_movie_subtitle(
        movie_title=movie_name,
        year=year,
        imdb_id=imdb_id,
        base_dir=SUBTITLE_BASE,
        api_key=OPENSUBTITLES_API_KEY,
    )
    return path


def _movie_label(movie_name: str, year: int) -> str:
    return f"*{_md1(movie_name)}*" + (f" ({year})" if year else "")


def _identity_from_resolved(resolved: ResolvedTitle) -> Dict[str, Any]:
    d = resolved.to_identity_dict()
    if resolved.media_type == "movie":
        d["movie_name"] = resolved.canonical_title
    else:
        d["series_name"] = resolved.canonical_title
    return d


def _identity_from_pending_choice(
    pending: Dict[str, Any], choice: str, pick_index: Optional[int] = None
) -> Dict[str, Any]:
    mt = pending.get("media_type") or "movie"
    if choice == "keep":
        up = dict(pending.get("user_parsed") or {})
        if mt == "movie":
            name = str(up.get("movie_name") or "Unknown")
            return {
                "media_type": "movie",
                "movie_name": name,
                "canonical_title": name,
                "year": int(up.get("year") or 0),
            }
        name = str(up.get("series_name") or "Unknown")
        return {
            "media_type": "tv",
            "series_name": name,
            "canonical_title": name,
            "season": int(up.get("season") or 1),
            "episode": int(up.get("episode") or 1),
        }
    if choice == "pick" and pick_index is not None:
        alts = pending.get("alternatives") or []
        if 0 <= pick_index < len(alts):
            alt = dict(alts[pick_index])
            if mt == "movie":
                alt["movie_name"] = alt.get("canonical_title") or alt.get("movie_name")
            else:
                alt["series_name"] = alt.get("canonical_title") or alt.get("series_name")
            alt["media_type"] = mt
            return alt
    sug = dict(pending.get("suggestion") or {})
    if mt == "movie":
        sug["movie_name"] = sug.get("canonical_title") or sug.get("movie_name")
    else:
        sug["series_name"] = sug.get("canonical_title") or sug.get("series_name")
    sug["media_type"] = mt
    return sug


def _title_confirmation_keyboard(token: str, pending: Dict[str, Any]) -> InlineKeyboardMarkup:
    rows: List[List[InlineKeyboardButton]] = [
        [InlineKeyboardButton("✅ Use suggestion", callback_data=f"title_use:{token}")]
    ]
    alts = pending.get("alternatives") or []
    for i, alt in enumerate(alts[:2]):
        title = alt.get("canonical_title") or "?"
        yr = alt.get("year") or 0
        if pending.get("media_type") == "movie":
            label = f"{title} ({yr})" if yr else title
        else:
            label = f"{title} S{alt.get('season', 1)}E{alt.get('episode', 1)}"
        rows.append(
            [InlineKeyboardButton(f"📌 {label[:40]}", callback_data=f"title_pick:{token}:{i}")]
        )
    rows.append(
        [InlineKeyboardButton("↩️ Keep what I typed", callback_data=f"title_keep:{token}")]
    )
    rows.append([InlineKeyboardButton("❌ Cancel", callback_data=f"title_cancel:{token}")])
    return InlineKeyboardMarkup(rows)


def _title_confirmation_text(pending: Dict[str, Any], resolved: ResolvedTitle) -> str:
    raw = pending.get("raw") or ""
    mt = pending.get("media_type") or resolved.media_type
    issue = pending.get("issue") or resolved.issue or ""
    if mt == "movie":
        up = pending.get("user_parsed") or {}
        entered = f"*{_md1(up.get('movie_name', raw))}*"
        uy = int(up.get("year") or 0)
        if uy:
            entered += f" ({uy})"
        suggested = _movie_label(resolved.canonical_title, resolved.year)
        if issue == "year_mismatch":
            body = f"You entered: {entered}\nBest match: {suggested} — use this year?"
        elif issue == "ambiguous":
            body = f"You entered: {entered}\nDid you mean {suggested}?"
        else:
            body = f"You entered: {entered}\nSuggested: {suggested}"
    else:
        up = pending.get("user_parsed") or {}
        sn = up.get("series_name") or raw
        s, e = int(up.get("season", 1)), int(up.get("episode", 1))
        entered = f"*{_md1(sn)}*{_tv_episode_suffix(sn, s, e)}"
        suggested = (
            f"*{_md1(resolved.canonical_title)}*"
            f"{_tv_episode_suffix(resolved.canonical_title, resolved.season, resolved.episode)}"
        )
        if issue == "episode_out_of_range":
            body = f"You entered: {entered}\n{resolved.reason}\nSuggested: {suggested}"
        else:
            body = f"You entered: {entered}\nDid you mean {suggested}?"
    return f"🔍 **Confirm title**\n\n{body}\n\nTap a button to continue."


async def _send_title_confirmation(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    resolved: ResolvedTitle,
    token: str,
    raw: str,
    latency: Dict[str, Any],
    req_started: float,
) -> None:
    pending = pending_to_dict(resolved, token, raw)
    pending["latency"] = latency
    pending["req_started"] = req_started
    context.user_data["pending_title"] = pending
    await update.message.reply_text(
        _title_confirmation_text(pending, resolved),
        parse_mode="Markdown",
        reply_markup=_title_confirmation_keyboard(token, pending),
    )


async def _run_movie_pipeline(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    identity: Dict[str, Any],
    latency: Dict[str, Any],
    req_started: float,
) -> None:
    movie_name = str(identity.get("movie_name") or identity.get("canonical_title") or "Unknown")
    year = int(identity.get("year") or 0)
    imdb_id = identity.get("imdb_id")
    latency["identity"] = {"movie_name": movie_name, "year": year, "imdb_id": imdb_id}
    label = _movie_label(movie_name, year)
    loop = asyncio.get_running_loop()
    timeout = 600.0

    try:
        phase_started = time.perf_counter()
        episode_dir, translations_dir, subtitle_path = await asyncio.wait_for(
            loop.run_in_executor(
                None,
                lambda: _find_existing_movie(movie_name, year),
            ),
            timeout=timeout,
        )
        latency["phase_timings_ms"]["find_existing"] = _ms_since(phase_started)

        if translations_dir is not None:
            latency["branch"] = "cache_hit_translations"
            await update.message.reply_text(
                f"🎬 Processing: {label}\n"
                f"✅ Found existing translations.\n\n"
                f"📁 Saved to: `{translations_dir.relative_to(BASE_DIR)}/`",
                parse_mode="Markdown",
                reply_markup=keyboard_discovery(context),
            )
            await _send_translations_list(
                update,
                context,
                translations_dir,
                movie_name,
                0,
                0,
                is_movie=True,
                year=year,
                latency_ms=_ms_since(req_started),
            )
            _persist_loaded_title_context(
                context,
                translations_dir=translations_dir,
                series_name=movie_name,
                episode_dir=episode_dir,
            )
            latency["status"] = "success"
            return

        if episode_dir is not None:
            latency["branch"] = "tier_exists_translate_only"
            await update.message.reply_text(
                f"🎬 Processing: {label}\n"
                f"✅ Found existing hard words list.\n\n"
                "⏳ Translating words…",
                parse_mode="Markdown",
                reply_markup=keyboard_discovery(context),
            )
            if subtitle_path is None:
                await update.message.reply_text(
                    f"🎬 Processing: {label}\n"
                    "⏳ Subtitle file missing, downloading…",
                    parse_mode="Markdown",
                    reply_markup=keyboard_discovery(context),
                )
                phase_started = time.perf_counter()
                subtitle_path = await asyncio.wait_for(
                    loop.run_in_executor(
                        None,
                        lambda m=movie_name, y=year, imdb=imdb_id: _do_download_movie(
                            m, y, imdb_id=imdb
                        ),
                    ),
                    timeout=timeout,
                )
                latency["phase_timings_ms"]["download_subtitle"] = _ms_since(phase_started)
                if not subtitle_path:
                    await update.message.reply_text(
                        f"❌ **Subtitle download failed** for {label}.\n\n"
                        "Possible causes: wrong movie name, or subtitle not on OpenSubtitles.",
                        parse_mode="Markdown",
                        reply_markup=keyboard_discovery(context),
                    )
                    latency["status"] = "failed"
                    latency["error"] = "subtitle_download_failed"
                    return
            phase_started = time.perf_counter()
            ok, out_dir, trans_err, translator_metrics = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: _do_translate(episode_dir, subtitle_path),
                ),
                timeout=timeout,
            )
            latency["phase_timings_ms"]["translate"] = _ms_since(phase_started)
            latency["translator_metrics"] = translator_metrics
            if not ok or not out_dir:
                reason = (trans_err or "Translation failed.").strip()
                await update.message.reply_text(
                    f"❌ **Translation failed.**\n\n{_md1(reason)}",
                    parse_mode="Markdown",
                    reply_markup=keyboard_discovery(context),
                )
                latency["status"] = "failed"
                latency["error"] = reason
                return
            rel = out_dir.relative_to(BASE_DIR)
            await update.message.reply_text(
                f"✅ {label}\n\n"
                f"📁 C-level words translated and saved to: `{rel}/`",
                parse_mode="Markdown",
                reply_markup=keyboard_discovery(context),
            )
            await _send_translations_list(
                update,
                context,
                out_dir,
                movie_name,
                0,
                0,
                is_movie=True,
                year=year,
                latency_ms=_ms_since(req_started),
            )
            _persist_loaded_title_context(
                context,
                translations_dir=out_dir,
                series_name=movie_name,
                episode_dir=episode_dir,
            )
            latency["status"] = "success"
            return

        latency["branch"] = "full_pipeline"
        await update.message.reply_text(
            f"🎬 Processing: {label}\n\n"
            "⏳ Downloading subtitle…",
            parse_mode="Markdown",
            reply_markup=keyboard_discovery(context),
        )
        phase_started = time.perf_counter()
        subtitle_path = await asyncio.wait_for(
            loop.run_in_executor(
                None,
                lambda m=movie_name, y=year, imdb=imdb_id: _do_download_movie(m, y, imdb_id=imdb),
            ),
            timeout=timeout,
        )
        latency["phase_timings_ms"]["download_subtitle"] = _ms_since(phase_started)
        if not subtitle_path:
            await update.message.reply_text(
                f"❌ **Subtitle download failed** for {label}.\n\n"
                "Possible causes: wrong movie name, or subtitle not on OpenSubtitles.",
                parse_mode="Markdown",
                reply_markup=keyboard_discovery(context),
            )
            latency["status"] = "failed"
            latency["error"] = "subtitle_download_failed"
            return

        await update.message.reply_text(
            f"🎬 Processing: {label}\n"
            f"✅ Subtitle downloaded.\n\n"
            "⏳ Building the hard-word list from the subtitle…",
            parse_mode="Markdown",
            reply_markup=keyboard_discovery(context),
        )
        phase_started = time.perf_counter()
        episode_dir, analyze_metrics, subtitle_raw_handoff = await asyncio.wait_for(
            loop.run_in_executor(
                None,
                lambda sp=subtitle_path, mn=movie_name, y=year: _do_analyze_movie(sp, mn, y),
            ),
            timeout=timeout,
        )
        latency["phase_timings_ms"]["analyze_subtitle"] = _ms_since(phase_started)
        latency["analyze_metrics"] = analyze_metrics
        if not episode_dir:
            await update.message.reply_text(
                "❌ **Hard-word list build failed** (could not read the subtitle).\n\n"
                "The file may be invalid or empty.",
                parse_mode="Markdown",
                reply_markup=keyboard_discovery(context),
            )
            latency["status"] = "failed"
            latency["error"] = "tier_list_build_failed"
            return

        await update.message.reply_text(
            f"🎬 Processing: {label}\n"
            f"✅ C-level list ready.\n\n"
            "⏳ Translating words…",
            parse_mode="Markdown",
            reply_markup=keyboard_discovery(context),
        )
        phase_started = time.perf_counter()
        ok, out_dir, trans_err, translator_metrics = await asyncio.wait_for(
            loop.run_in_executor(
                None,
                lambda ed=episode_dir, sp=subtitle_path, raw=subtitle_raw_handoff: _do_translate(
                    ed, sp, subtitle_raw=raw
                ),
            ),
            timeout=timeout,
        )
        latency["phase_timings_ms"]["translate"] = _ms_since(phase_started)
        latency["translator_metrics"] = translator_metrics
        if not ok or not out_dir:
            reason = (trans_err or "Translation failed.").strip()
            await update.message.reply_text(
                f"❌ **Translation failed.**\n\n{_md1(reason)}",
                parse_mode="Markdown",
                reply_markup=keyboard_discovery(context),
            )
            latency["status"] = "failed"
            latency["error"] = reason
            return

        rel = out_dir.relative_to(BASE_DIR)
        await update.message.reply_text(
            f"✅ {label}\n\n"
            f"📁 C-level words translated and saved to: `{rel}/`",
            parse_mode="Markdown",
            reply_markup=keyboard_discovery(context),
        )
        await _send_translations_list(
            update,
            context,
            out_dir,
            movie_name,
            0,
            0,
            is_movie=True,
            year=year,
            latency_ms=_ms_since(req_started),
        )
        _persist_loaded_title_context(
            context,
            translations_dir=out_dir,
            series_name=movie_name,
            episode_dir=episode_dir,
        )
        latency["status"] = "success"

    except asyncio.TimeoutError:
        await update.message.reply_text(
            "❌ **Request timed out** (download/analysis/translation took too long).",
            parse_mode="Markdown",
            reply_markup=keyboard_discovery(context),
        )
        latency["status"] = "timeout"
        latency["error"] = "request_timeout"
    except Exception as e:
        await update.message.reply_text(
            f"❌ **Error:** {_md1(str(e)[:150])}",
            parse_mode="Markdown",
            reply_markup=keyboard_discovery(context),
        )
        latency["status"] = "failed"
        latency["error"] = str(e)[:200]
    finally:
        latency["finished_at"] = datetime.now().isoformat()
        latency["timings_ms"]["total_e2e_ms"] = _ms_since(req_started)
        await _write_latency_async(latency)


async def _run_series_pipeline(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    identity: Dict[str, Any],
    latency: Dict[str, Any],
    req_started: float,
) -> None:
    series_name = str(identity.get("series_name") or identity.get("canonical_title") or "Unknown")
    season = int(identity.get("season") or 1)
    episode = int(identity.get("episode") or 1)
    latency["identity"] = {
        "series_name": series_name,
        "season": season,
        "episode": episode,
    }
    loop = asyncio.get_running_loop()
    timeout = 600.0

    try:
        phase_started = time.perf_counter()
        episode_dir, translations_dir, subtitle_path = await asyncio.wait_for(
            loop.run_in_executor(
                None,
                lambda sn=series_name, s=season, e=episode: _find_existing(sn, s, e),
            ),
            timeout=timeout,
        )
        latency["phase_timings_ms"]["find_existing"] = _ms_since(phase_started)

        if translations_dir is not None:
            latency["branch"] = "cache_hit_translations"
            await update.message.reply_text(
                f"🔍 Processing: *{_md1(series_name)}*{_tv_episode_suffix(series_name, season, episode)}\n"
                f"✅ Found existing translations.\n\n"
                f"📁 Saved to: `{translations_dir.relative_to(BASE_DIR)}/`",
                parse_mode="Markdown",
                reply_markup=keyboard_discovery(context),
            )
            await _send_translations_list(
                update,
                context,
                translations_dir,
                series_name,
                season,
                episode,
                latency_ms=_ms_since(req_started),
            )
            _persist_loaded_title_context(
                context,
                translations_dir=translations_dir,
                series_name=series_name,
                episode_dir=episode_dir,
            )
            latency["status"] = "success"
            return

        if episode_dir is not None:
            latency["branch"] = "tier_exists_translate_only"
            await update.message.reply_text(
                f"🔍 Processing: *{_md1(series_name)}*{_tv_episode_suffix(series_name, season, episode)}\n"
                f"✅ Found existing hard words list.\n\n"
                "⏳ Translating words…",
                parse_mode="Markdown",
                reply_markup=keyboard_discovery(context),
            )
            if subtitle_path is None:
                await update.message.reply_text(
                    f"🔍 Processing: *{_md1(series_name)}*{_tv_episode_suffix(series_name, season, episode)}\n"
                    "⏳ Subtitle file missing, downloading…",
                    parse_mode="Markdown",
                    reply_markup=keyboard_discovery(context),
                )
                phase_started = time.perf_counter()
                subtitle_path = await asyncio.wait_for(
                    loop.run_in_executor(
                        None,
                        lambda sn=series_name, s=season, e=episode: _do_download(sn, s, e),
                    ),
                    timeout=timeout,
                )
                latency["phase_timings_ms"]["download_subtitle"] = _ms_since(phase_started)
                if not subtitle_path:
                    await update.message.reply_text(
                        f"❌ **Subtitle download failed** for *{_md1(series_name)}*{_tv_episode_suffix(series_name, season, episode)}.\n\n"
                        "Possible causes: wrong series/episode name, or subtitle not on OpenSubtitles.",
                        parse_mode="Markdown",
                        reply_markup=keyboard_discovery(context),
                    )
                    latency["status"] = "failed"
                    latency["error"] = "subtitle_download_failed"
                    return
            phase_started = time.perf_counter()
            ok, out_dir, trans_err, translator_metrics = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda ed=episode_dir, sp=subtitle_path: _do_translate(ed, sp),
                ),
                timeout=timeout,
            )
            latency["phase_timings_ms"]["translate"] = _ms_since(phase_started)
            latency["translator_metrics"] = translator_metrics
            if not ok or not out_dir:
                reason = (trans_err or "Translation failed.").strip()
                await update.message.reply_text(
                    f"❌ **Translation failed.**\n\n{_md1(reason)}\n\n💡 Use /next or **Next series** to try another title.",
                    parse_mode="Markdown",
                    reply_markup=keyboard_discovery(context),
                )
                latency["status"] = "failed"
                latency["error"] = reason
                return
            rel = out_dir.relative_to(BASE_DIR)
            await update.message.reply_text(
                f"✅ *{_md1(series_name)}*{_tv_episode_suffix(series_name, season, episode)}\n\n"
                f"📁 C-level words translated and saved to: `{rel}/`",
                parse_mode="Markdown",
                reply_markup=keyboard_discovery(context),
            )
            await _send_translations_list(
                update,
                context,
                out_dir,
                series_name,
                season,
                episode,
                latency_ms=_ms_since(req_started),
            )
            _persist_loaded_title_context(
                context,
                translations_dir=out_dir,
                series_name=series_name,
                episode_dir=episode_dir,
            )
            latency["status"] = "success"
            return

        latency["branch"] = "full_pipeline"
        await update.message.reply_text(
            f"🔍 Processing: *{_md1(series_name)}*{_tv_episode_suffix(series_name, season, episode)}\n\n"
            "⏳ Downloading subtitle…",
            parse_mode="Markdown",
            reply_markup=keyboard_discovery(context),
        )
        phase_started = time.perf_counter()
        subtitle_path = await asyncio.wait_for(
            loop.run_in_executor(
                None,
                lambda sn=series_name, s=season, e=episode: _do_download(sn, s, e),
            ),
            timeout=timeout,
        )
        latency["phase_timings_ms"]["download_subtitle"] = _ms_since(phase_started)
        if not subtitle_path:
            await update.message.reply_text(
                f"❌ **Subtitle download failed** for *{_md1(series_name)}*{_tv_episode_suffix(series_name, season, episode)}.\n\n"
                "Possible causes: wrong series/episode name, or subtitle not on OpenSubtitles.",
                parse_mode="Markdown",
                reply_markup=keyboard_discovery(context),
            )
            latency["status"] = "failed"
            latency["error"] = "subtitle_download_failed"
            return

        await update.message.reply_text(
            f"🔍 Processing: *{_md1(series_name)}*{_tv_episode_suffix(series_name, season, episode)}\n"
            f"✅ Subtitle downloaded.\n\n"
            "⏳ Building the hard-word list from the subtitle…",
            parse_mode="Markdown",
            reply_markup=keyboard_discovery(context),
        )
        phase_started = time.perf_counter()
        episode_dir, analyze_metrics, subtitle_raw_handoff = await asyncio.wait_for(
            loop.run_in_executor(None, lambda sp=subtitle_path: _do_analyze(sp)),
            timeout=timeout,
        )
        latency["phase_timings_ms"]["analyze_subtitle"] = _ms_since(phase_started)
        latency["analyze_metrics"] = analyze_metrics
        if not episode_dir:
            await update.message.reply_text(
                "❌ **Hard-word list build failed** (could not read the subtitle).\n\n"
                "The file may be invalid or empty.",
                parse_mode="Markdown",
                reply_markup=keyboard_discovery(context),
            )
            latency["status"] = "failed"
            latency["error"] = "tier_list_build_failed"
            return

        await update.message.reply_text(
            f"🔍 Processing: *{_md1(series_name)}*{_tv_episode_suffix(series_name, season, episode)}\n"
            f"✅ C-level list ready.\n\n"
            "⏳ Translating words…",
            parse_mode="Markdown",
            reply_markup=keyboard_discovery(context),
        )
        phase_started = time.perf_counter()
        ok, out_dir, trans_err, translator_metrics = await asyncio.wait_for(
            loop.run_in_executor(
                None,
                lambda ed=episode_dir, sp=subtitle_path, raw=subtitle_raw_handoff: _do_translate(
                    ed, sp, subtitle_raw=raw
                ),
            ),
            timeout=timeout,
        )
        latency["phase_timings_ms"]["translate"] = _ms_since(phase_started)
        latency["translator_metrics"] = translator_metrics
        if not ok or not out_dir:
            reason = (trans_err or "Translation failed.").strip()
            await update.message.reply_text(
                f"❌ **Translation failed.**\n\n{_md1(reason)}",
                parse_mode="Markdown",
                reply_markup=keyboard_discovery(context),
            )
            latency["status"] = "failed"
            latency["error"] = reason
            return

        rel = out_dir.relative_to(BASE_DIR)
        await update.message.reply_text(
            f"✅ *{_md1(series_name)}*{_tv_episode_suffix(series_name, season, episode)}\n\n"
            f"📁 C-level words translated and saved to: `{rel}/`",
            parse_mode="Markdown",
            reply_markup=keyboard_discovery(context),
        )
        await _send_translations_list(
            update,
            context,
            out_dir,
            series_name,
            season,
            episode,
            latency_ms=_ms_since(req_started),
        )
        _persist_loaded_title_context(
            context,
            translations_dir=out_dir,
            series_name=series_name,
            episode_dir=episode_dir,
        )
        latency["status"] = "success"

    except asyncio.TimeoutError:
        await update.message.reply_text(
            "❌ **Request timed out** (download/analysis/translation took too long).",
            parse_mode="Markdown",
            reply_markup=keyboard_discovery(context),
        )
        latency["status"] = "timeout"
        latency["error"] = "request_timeout"
    except Exception as e:
        await update.message.reply_text(
            f"❌ **Error:** {_md1(str(e)[:150])}",
            parse_mode="Markdown",
            reply_markup=keyboard_discovery(context),
        )
        latency["status"] = "failed"
        latency["error"] = str(e)[:200]
    finally:
        latency["finished_at"] = datetime.now().isoformat()
        latency["timings_ms"]["total_e2e_ms"] = _ms_since(req_started)
        await _write_latency_async(latency)


def _do_analyze_movie(
    subtitle_path: Path, movie_name: str, year: int
) -> Tuple[Optional[Path], Dict[str, int], Optional[str]]:
    """Run tier pipeline for movie. Returns (episode_dir_or_none, analyze_metrics, subtitle_raw_for_translate)."""
    from subtitle_analyzer import run_pipeline

    analyze_metrics: Dict[str, int] = {}
    handoff: Dict[str, Any] = {}
    oa_key = resolve_openai_api_key() or None
    episode_dir = run_pipeline(
        subtitle_path=subtitle_path,
        base_dir=BASE_DIR,
        tierlist_base_dir=TIERLIST_BASE,
        max_english_freq=20_000_000,
        openai_api_key=oa_key,
        is_movie=True,
        series_name=movie_name,
        year=year if year > 0 else None,
        metrics_out=analyze_metrics,
        handoff_out=handoff,
        skip_if_outputs_fresh=True,
    )
    if not episode_dir or not (episode_dir / "tier_1_hard_usable_words.csv").exists():
        return None, analyze_metrics, None
    raw = handoff.get("subtitle_raw")
    return episode_dir, analyze_metrics, raw if isinstance(raw, str) else None


def _do_translate(
    episode_dir: Path,
    subtitle_path: Optional[Path],
    subtitle_raw: Optional[str] = None,
    translation_overwrite: bool = False,
    *,
    tier_ids: Optional[Collection[str]] = None,
) -> Tuple[bool, Optional[Path], Optional[str], Optional[Dict[str, Any]]]:
    """Translate selected tiers and save to translations/. Returns (success, out_dir, error_reason, metrics).

    tier_ids None: frequent lists only (tier_1, B1, B2). Pass explicit ids for on-demand rare tiers.
    """
    from download_subtitles import get_translations_episode_dir, get_translations_movie_dir
    from translate_tier_translations import FREQUENT_TRANSLATION_TIER_IDS, run as run_translate

    metrics: Dict[str, Any] = {}
    tiers = FREQUENT_TRANSLATION_TIER_IDS if tier_ids is None else tier_ids
    oa_key = resolve_openai_api_key() or None
    ok, err = run_translate(
        episode_dir=episode_dir,
        subtitle_path=subtitle_path,
        api_key=oa_key,
        translations_base=TRANSLATIONS_BASE,
        subtitle_base=SUBTITLE_BASE,
        metrics_out=metrics,
        subtitle_raw=subtitle_raw,
        translation_overwrite=translation_overwrite,
        tier_ids=tiers,
        translation_mode=DEFAULT_TRANSLATION_MODE,
    )
    if not ok:
        return False, None, err or "Translation failed.", metrics
    info = episode_dir / "episode_info.json"
    series_name = "Unknown"
    season_num = episode_num = 1
    is_movie = False
    year = 0
    if info.exists():
        try:
            data = json.loads(info.read_text(encoding="utf-8"))
            series_name = data.get("series") or series_name
            season_num = int(data.get("season_number", 1))
            episode_num = int(data.get("episode_number", 1))
            is_movie = bool(data.get("is_movie", False))
            year = int(data.get("year", 0))
        except Exception:
            pass
    if is_movie:
        out_dir = get_translations_movie_dir(TRANSLATIONS_BASE, series_name, year)
    else:
        out_dir = get_translations_episode_dir(
            TRANSLATIONS_BASE, series_name, season_num, episode_num
        )
    return True, out_dir, None, metrics


async def _handle_message_movie(
    update: Update, context: ContextTypes.DEFAULT_TYPE, raw: str
) -> None:
    """Handle movie search flow: parse, resolve title, confirm if needed, then pipeline."""
    context.user_data.pop("pending_title", None)
    req_started = time.perf_counter()
    latency = _new_latency(raw, "movie")
    phase_started = time.perf_counter()
    movie_name, year = _parse_movie_input(raw)
    latency["phase_timings_ms"]["parse_input"] = _ms_since(phase_started)

    label = _movie_label(movie_name, year)
    await update.message.reply_text(
        f"🎬 Processing request for: {label}\n\n"
        "⏳ Resolving title…",
        parse_mode="Markdown",
        reply_markup=keyboard_discovery(context),
    )

    phase_started = time.perf_counter()
    resolved = await resolve_movie_async(movie_name, year, raw_input=raw)
    latency["phase_timings_ms"]["resolve_title"] = _ms_since(phase_started)
    latency["title_resolution"] = {
        "confidence": resolved.confidence,
        "issue": resolved.issue,
        "canonical_title": resolved.canonical_title,
        "year": resolved.year,
    }

    if resolved.confidence == "high":
        identity = _identity_from_resolved(resolved)
        await update.message.reply_text(
            f"🎬 Processing: {_movie_label(identity['movie_name'], identity['year'])}\n\n"
            "⏳ Looking for a saved word list or translations…",
            parse_mode="Markdown",
            reply_markup=keyboard_discovery(context),
        )
        await _run_movie_pipeline(update, context, identity, latency, req_started)
        return

    token = new_pending_token()
    await _send_title_confirmation(update, context, resolved, token, raw, latency, req_started)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        await update.message.reply_text(
            "❌ Please send a TV series or movie title.",
            reply_markup=keyboard_discovery(context),
        )
        return

    raw = update.message.text.strip()
    if _is_show_my_words_text(raw):
        await show_my_words(update, context)
        return
    req_started = time.perf_counter()
    latency = _new_latency(raw, "series")
    if len(raw) < 2:
        await update.message.reply_text(
            "❌ Name too short. Try e.g. _Fallout_, _Inception_, _Game of Thrones_.",
            parse_mode="Markdown",
            reply_markup=keyboard_discovery(context),
        )
        latency["status"] = "failed"
        latency["error"] = "name_too_short"
        latency["finished_at"] = datetime.now().isoformat()
        latency["timings_ms"]["total_e2e_ms"] = _ms_since(req_started)
        _write_latency(latency)
        return

    mode = context.user_data.get("mode", "series")
    if mode == "movie":
        await _handle_message_movie(update, context, raw)
        return

    if _should_auto_route_movie_from_series_mode(raw):
        await _handle_message_movie(update, context, raw)
        return

    context.user_data.pop("pending_title", None)
    phase_started = time.perf_counter()
    series_name, season, episode = _parse_series_input(raw)
    latency["phase_timings_ms"]["parse_input"] = _ms_since(phase_started)
    latency["identity"] = {
        "series_name": series_name,
        "season": season,
        "episode": episode,
    }
    await update.message.reply_text(
        f"🔍 Processing request for: *{_md1(raw)}*\n\n"
        "⏳ Resolving title…",
        parse_mode="Markdown",
        reply_markup=keyboard_discovery(context),
    )

    if _simple_parse_likely_failed(raw, series_name, season, episode):
        phase_started = time.perf_counter()
        chatgpt_result = await _normalize_with_chatgpt(raw)
        latency["phase_timings_ms"]["normalize_input"] = _ms_since(phase_started)
        if chatgpt_result is not None:
            series_name, season, episode = chatgpt_result
            latency["identity"] = {
                "series_name": series_name,
                "season": season,
                "episode": episode,
            }

    phase_started = time.perf_counter()
    resolved = await resolve_tv_async(series_name, season, episode, raw_input=raw)
    latency["phase_timings_ms"]["resolve_title"] = _ms_since(phase_started)
    latency["title_resolution"] = {
        "confidence": resolved.confidence,
        "issue": resolved.issue,
        "canonical_title": resolved.canonical_title,
        "season": resolved.season,
        "episode": resolved.episode,
    }

    if resolved.confidence == "high":
        identity = _identity_from_resolved(resolved)
        await update.message.reply_text(
            f"🔍 Processing: *{_md1(identity['series_name'])}*"
            f"{_tv_episode_suffix(identity['series_name'], identity['season'], identity['episode'])}\n\n"
            "⏳ Looking for a saved word list or translations…",
            parse_mode="Markdown",
            reply_markup=keyboard_discovery(context),
        )
        await _run_series_pipeline(update, context, identity, latency, req_started)
        return

    token = new_pending_token()
    await _send_title_confirmation(update, context, resolved, token, raw, latency, req_started)


def _load_translation_pairs_csv(csv_path: Path) -> List[Tuple[str, str, str]]:
    """Load word → translation_ru (+ optional example_en) from a translations CSV."""
    if not csv_path.exists():
        return []
    out: List[Tuple[str, str, str]] = []
    empty_values = {"", "—", "n/a", "na", "[translation failed]"}
    try:
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                w = (row.get("word") or "").strip()
                t = (row.get("translation_ru") or "").strip()
                if not w:
                    continue
                t_lower = t.lower()
                if t_lower in empty_values or not t:
                    continue
                ex = (row.get("example_en") or "").strip()
                out.append((w, t, ex))
    except Exception:
        pass
    return out


def _attach_subtitle_examples(
    rows: List[Tuple[str, str, str]],
    subtitle_path: Optional[Path],
) -> List[Tuple[str, str, str]]:
    """Attach one subtitle dialogue line per word when an .srt is available."""
    if not rows or subtitle_path is None or not subtitle_path.is_file():
        return rows
    from subtitle_text_utils import extract_word_examples_from_srt_path

    words = [w for w, _t, _ex in rows]
    ex_map = extract_word_examples_from_srt_path(subtitle_path, words, max_per_word=1)
    filled: List[Tuple[str, str, str]] = []
    for w, t, ex in rows:
        lines = ex_map.get(w, [])
        if lines:
            filled.append((w, t, lines[0]))
        elif ex and ex.upper() != "N/A":
            filled.append((w, t, ex))
        else:
            filled.append((w, t, ""))
    return filled


def _fill_missing_word_examples(
    rows: List[Tuple[str, str, str]],
    subtitle_path: Optional[Path],
) -> List[Tuple[str, str, str]]:
    """Back-compat alias: always prefer subtitle examples when possible."""
    return _attach_subtitle_examples(rows, subtitle_path)


def _word_list_example_suffix(example: str, *, max_len: int = 180) -> str:
    """Italic example line under a word entry (same style as phrasal verbs)."""
    ex = (example or "").strip()
    if not ex or ex.upper() == "N/A":
        return ""
    short = ex[:max_len] + ("…" if len(ex) > max_len else "")
    return f"\n   _{short}_"


def _format_word_entry_line(
    index: int,
    word: str,
    translation: str,
    example: str = "",
    *,
    is_saved: bool = False,
    word_link: Optional[str] = None,
) -> str:
    shown_word = f"{word} 📚" if is_saved else word
    if word_link:
        word_part = f"[{_md1(shown_word)}]({word_link})"
    else:
        word_part = f"*{_md1(shown_word)}*"
    line = f"{index}. {word_part} → {_md1(translation)}"
    line += _word_list_example_suffix(example)
    return line


def _load_translations_list(translations_dir: Path) -> List[Tuple[str, str]]:
    """Load word → translation from tier_1_translations.csv."""
    return _load_translation_pairs_csv(translations_dir / "tier_1_translations.csv")


def _load_b_level_pairs(
    translations_dir: Path,
) -> Tuple[List[Tuple[str, str]], List[Tuple[str, str]]]:
    """B-level translation pairs loaded from internal B-tier CSVs."""
    b1 = _load_translation_pairs_csv(translations_dir / "tier_b1_translations.csv")
    b2 = _load_translation_pairs_csv(translations_dir / "tier_b2_translations.csv")
    return b1, b2


def _format_b_level_list(
    series_name: str,
    season: int,
    episode: int,
    b1: List[Tuple[str, str, str]],
    b2: List[Tuple[str, str, str]],
    *,
    is_movie: bool = False,
    year: int = 0,
    max_lines_per_band: int = 40,
    saved_keys: Optional[Collection[str]] = None,
    word_tokens: Optional[Dict[str, str]] = None,
    bot_username: str = "",
) -> str:
    """Format a single B-level list; truncates with '… and N more'."""
    if is_movie:
        title = f"🎬 *{_md1(series_name)}*" + (f" ({year})" if year else "")
    else:
        title = f"📺 *{_md1(series_name)}*{_tv_episode_suffix(series_name, season, episode)}"
    merged: List[Tuple[str, str, str]] = []
    seen = set()
    for w, t, ex in [*b1, *b2]:
        key = (w.strip().lower(), t.strip().lower())
        if key in seen:
            continue
        seen.add(key)
        merged.append((w, t, ex))
    n = len(merged)
    header = f"📗 *B-level words* — {title}\n\n📊 *B-level words: {n}*\n\n"
    if not merged:
        return header + "_No words._"
    show = merged[:max_lines_per_band]
    saved = set(saved_keys or [])
    tokens = word_tokens or {}
    lines = [
        _format_word_entry_line(
            i,
            w,
            t,
            ex,
            is_saved=_dict_entry_key(w, t) in saved,
            word_link=_deep_link_for_word_token(
                bot_username, tokens.get(_dict_entry_key(w, t))
            ),
        )
        for i, (w, t, ex) in enumerate(show, 1)
    ]
    body = "\n".join(lines)
    if n > max_lines_per_band:
        body += f"\n\n… and {n - max_lines_per_band} more."
    return header + body


def _format_word_list(
    series_name: str,
    season: int,
    episode: int,
    pairs: List[Tuple[str, str, str]],
    max_lines: int = 25,
    *,
    is_movie: bool = False,
    year: int = 0,
    saved_keys: Optional[Collection[str]] = None,
    word_tokens: Optional[Dict[str, str]] = None,
    bot_username: str = "",
) -> str:
    """Format header + numbered word list. If pairs > max_lines, show first max_lines and '... and N more'."""
    n = len(pairs)
    if is_movie:
        header = f"🎬 *{_md1(series_name)}*" + (f" ({year})" if year else "") + f"\n\n📊 *C-level words: {n}*\n\n"
    else:
        header = f"📺 *{_md1(series_name)}*{_tv_episode_suffix(series_name, season, episode)}\n\n📊 *C-level words: {n}*\n\n"
    if not pairs:
        return header + "_No words._"
    show = pairs[:max_lines]
    saved = set(saved_keys or [])
    tokens = word_tokens or {}
    lines = [
        _format_word_entry_line(
            i,
            w,
            t,
            ex,
            is_saved=_dict_entry_key(w, t) in saved,
            word_link=_deep_link_for_word_token(
                bot_username, tokens.get(_dict_entry_key(w, t))
            ),
        )
        for i, (w, t, ex) in enumerate(show, 1)
    ]
    body = "\n".join(lines)
    if n > max_lines:
        body += f"\n\n… and {n - max_lines} more words."
    return header + body


def _format_rare_in_series_full_list(
    series_name: str,
    season: int,
    episode: int,
    pairs: List[Tuple[str, str, str]],
    *,
    is_movie: bool = False,
    year: int = 0,
    band: str = "c",
    saved_keys: Optional[Collection[str]] = None,
    word_tokens: Optional[Dict[str, str]] = None,
    bot_username: str = "",
) -> str:
    """Full numbered list for rare-in-series translations (C-level vs B-level band)."""
    n = len(pairs)
    label = "Rare in series (C1–C2)" if band == "c" else "Rare in series (B1–B2)"
    if is_movie:
        header = f"📋 *{label}* — *{_md1(series_name)}*" + (f" ({year})" if year else "") + f"\n\n📊 *{n} words*\n\n"
    else:
        header = f"📋 *{label}* — *{_md1(series_name)}*{_tv_episode_suffix(series_name, season, episode)}\n\n📊 *{n} words*\n\n"
    if not pairs:
        return header + "_No words._"
    saved = set(saved_keys or [])
    tokens = word_tokens or {}
    lines = [
        _format_word_entry_line(
            i,
            w,
            t,
            ex,
            is_saved=_dict_entry_key(w, t) in saved,
            word_link=_deep_link_for_word_token(
                bot_username, tokens.get(_dict_entry_key(w, t))
            ),
        )
        for i, (w, t, ex) in enumerate(pairs, 1)
    ]
    return header + "\n".join(lines)


def _split_message_chunks(text: str, max_len: int = 4096) -> List[str]:
    """Split text into chunks of at most max_len, breaking at newlines."""
    if len(text) <= max_len:
        return [text] if text else []
    chunks = []
    start = 0
    while start < len(text):
        end = start + max_len
        if end >= len(text):
            chunks.append(text[start:])
            break
        # Break at last newline in this range
        segment = text[start:end]
        last_nl = segment.rfind("\n")
        if last_nl != -1:
            end = start + last_nl + 1
        chunks.append(text[start:end])
        start = end
    return chunks


def _chat_message(update: Update, *, query=None):
    """Message object to reply on — callback queries use the message that held the button."""
    return query.message if query else update.message


async def _reply_bot_message(
    update: Update,
    *,
    query=None,
    text: str,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
    parse_mode: str = "Markdown",
) -> Any:
    """Send bot text as a new chat message (append to history, never edit prior messages)."""
    msg = _chat_message(update, query=query)
    try:
        return await msg.reply_text(text, parse_mode=parse_mode, reply_markup=reply_markup)
    except BadRequest:
        if parse_mode is None:
            raise
    return await msg.reply_text(text, parse_mode=None, reply_markup=reply_markup)


async def _reply_bot_chunks(
    update: Update,
    *,
    query=None,
    chunks: List[str],
    reply_markup: Optional[InlineKeyboardMarkup] = None,
    parse_mode: str = "Markdown",
) -> None:
    """Send chunked bot text as new messages; keyboard on the last chunk only."""
    if not chunks:
        return
    msg = _chat_message(update, query=query)
    last = len(chunks) - 1
    for i, part in enumerate(chunks):
        markup = reply_markup if i == last else None
        try:
            await msg.reply_text(part, parse_mode=parse_mode, reply_markup=markup)
        except BadRequest:
            if parse_mode is None:
                raise
            await msg.reply_text(part, parse_mode=None, reply_markup=markup)


def _tier_episode_dir_ready(episode_dir: Path) -> bool:
    return (episode_dir / "tier_1_hard_usable_words.csv").is_file()


def _resolve_episode_dir(
    translations_dir: Path,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    episode_dir_hint: Optional[Path] = None,
) -> Optional[Path]:
    """
    Locate Tier_lists episode folder for a loaded translations dir.
    Handles cache hits where translations exist but last_episode_dir was empty or path mismatched.
    """
    from download_subtitles import get_tierlist_episode_dir, get_tierlist_movie_dir

    if episode_dir_hint is not None:
        hinted = Path(episode_dir_hint).resolve()
        if _tier_episode_dir_ready(hinted):
            return hinted

    led = (context.user_data.get("last_episode_dir") or "").strip()
    if led:
        cached = Path(led).resolve()
        if _tier_episode_dir_ready(cached):
            return cached

    ti = _read_translation_info_json(translations_dir)
    if ti:
        series = str(ti.get("series") or context.user_data.get("last_series_name") or "").strip()
        if series:
            if ti.get("is_movie"):
                yr = int(ti.get("year", 0))
                candidate = get_tierlist_movie_dir(TIERLIST_BASE, series, yr)
            else:
                candidate = get_tierlist_episode_dir(
                    TIERLIST_BASE,
                    series,
                    int(ti.get("season_number", 1)),
                    int(ti.get("episode_number", 1)),
                )
            if _tier_episode_dir_ready(candidate):
                return candidate.resolve()

    try:
        mirrored = (TIERLIST_BASE / translations_dir.resolve().relative_to(TRANSLATIONS_BASE.resolve())).resolve()
        if _tier_episode_dir_ready(mirrored):
            return mirrored
    except ValueError:
        pass

    sub_name = (ti or {}).get("source_subtitle") or ""
    if sub_name:
        for info_path in TIERLIST_BASE.rglob("episode_info.json"):
            try:
                data = json.loads(info_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if data.get("subtitle_file") != sub_name:
                continue
            parent = info_path.parent.resolve()
            if _tier_episode_dir_ready(parent):
                return parent
    return None


def _persist_loaded_title_context(
    context: ContextTypes.DEFAULT_TYPE,
    *,
    translations_dir: Path,
    series_name: str,
    episode_dir: Optional[Path] = None,
) -> Optional[Path]:
    """Store last_translations_dir and a reliable last_episode_dir for list buttons."""
    resolved = _resolve_episode_dir(
        translations_dir, context, episode_dir_hint=episode_dir
    )
    context.user_data["last_translations_dir"] = str(translations_dir.resolve())
    context.user_data["last_series_name"] = series_name
    context.user_data["last_episode_dir"] = str(resolved) if resolved else ""
    return resolved


def _get_translations_header(
    translations_dir: Path, context: ContextTypes.DEFAULT_TYPE
) -> Tuple[str, int, int, bool, int]:
    """Get (series_name, season, episode, is_movie, year) from translation_info.json or context."""
    info_path = translations_dir / "translation_info.json"
    if info_path.exists():
        try:
            data = json.loads(info_path.read_text(encoding="utf-8"))
            return (
                data.get("series") or context.user_data.get("last_series_name") or "Unknown",
                int(data.get("season_number", 0)),
                int(data.get("episode_number", 0)),
                bool(data.get("is_movie", False)),
                int(data.get("year", 0)),
            )
        except Exception:
            pass
    return (
        context.user_data.get("last_series_name") or "Unknown",
        0,
        0,
        False,
        0,
    )


async def _send_translations_list(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    translations_dir: Path,
    series_name: str,
    season: int,
    episode: int,
    *,
    is_movie: bool = False,
    year: int = 0,
    latency_ms: Optional[int] = None,
    query=None,
) -> None:
    """Load tier_1 translations and send frequent C-level list (chunked). Supports callback via query=."""
    episode_dir = _resolve_episode_dir(translations_dir, context)
    pairs = _load_translations_list(translations_dir)
    user_id = _safe_user_id(update, query=query)
    saved_keys: Collection[str] = ()
    if user_id is not None:
        saved_keys = set(_get_user_dictionary(user_id).keys())
    sp = _subtitle_path_for_loaded_title(
        series_name,
        season,
        episode,
        is_movie=is_movie,
        year=year,
        episode_dir=episode_dir,
        translations_dir=translations_dir,
    )
    pairs = _attach_subtitle_examples(pairs, sp)
    latency_suffix = (
        f"\n⏱ *Latency:* {latency_ms / 1000:.2f}s"
        if isinstance(latency_ms, int) and latency_ms >= 0
        else ""
    )
    kb = keyboard_loaded(context)
    rel = f"`{translations_dir.relative_to(BASE_DIR)}/`"
    if not pairs:
        header = f"🎬 *{_md1(series_name)}*" + (f" ({year})" if year else "") if is_movie else f"📺 *{_md1(series_name)}*{_tv_episode_suffix(series_name, season, episode)}"
        body = f"{header}\n\n📁 Saved to: {rel}{latency_suffix}\n\n_No words in CSV._"
        await _reply_bot_message(update, query=query, text=body, reply_markup=kb)
        return
    shown_rows = pairs[:25]
    bot_username = _bot_username_from_context(context)
    word_tokens = _register_word_link_tokens(shown_rows)
    text = _format_word_list(
        series_name,
        season,
        episode,
        pairs,
        is_movie=is_movie,
        year=year,
        saved_keys=saved_keys,
        word_tokens=word_tokens,
        bot_username=bot_username,
    )
    if latency_suffix:
        text += f"\n\n{latency_suffix}"
    max_len = 4096
    if len(text) <= max_len:
        sent = await _reply_bot_message(update, query=query, text=text, reply_markup=kb)
        if sent and hasattr(sent, "chat_id") and hasattr(sent, "message_id"):
            _persist_word_list_anchor(
                context,
                chat_id=int(sent.chat_id),
                message_id=int(sent.message_id),
                view={
                    "kind": "frequent_c",
                    "series_name": series_name,
                    "season": season,
                    "episode": episode,
                    "is_movie": is_movie,
                    "year": year,
                    "rows": shown_rows,
                },
            )
    else:
        parts = _split_message_chunks(text, max_len=max_len)
        await _reply_bot_chunks(update, query=query, chunks=parts, reply_markup=kb)


async def send_frequent_c_words(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    query=None,
) -> None:
    """Send frequent C-level list (tier_1_translations) for last loaded title."""
    last_dir = context.user_data.get("last_translations_dir")
    if not last_dir:
        msg = (
            "❌ No episode or movie loaded yet.\n\n"
            "Send a title first, then tap **Frequent C**."
        )
        kbd = keyboard_discovery(context)
        await _reply_bot_message(update, query=query, text=msg, reply_markup=kbd)
        return
    translations_dir = Path(last_dir).resolve()
    if not translations_dir.exists():
        msg = f"❌ Translations folder not found: `{_rel_path(last_dir)}/`"
        kbd = keyboard_discovery(context)
        await _reply_bot_message(update, query=query, text=msg, reply_markup=kbd)
        return
    series_name, season, episode, is_movie, year = _get_translations_header(
        translations_dir, context
    )
    await _send_translations_list(
        update,
        context,
        translations_dir,
        series_name,
        season,
        episode,
        is_movie=is_movie,
        year=year,
        query=query,
    )


def _rel_path(path_str: str) -> str:
    try:
        p = Path(path_str).resolve()
        return str(p.relative_to(BASE_DIR.resolve()))
    except (ValueError, TypeError):
        return path_str


def _subtitle_path_for_loaded_title(
    series_name: str,
    season: int,
    episode: int,
    *,
    is_movie: bool,
    year: int,
    episode_dir: Optional[Path] = None,
    translations_dir: Optional[Path] = None,
) -> Optional[Path]:
    """Resolved .srt path for the loaded title, or None if missing."""
    from download_subtitles import get_movie_subtitle_path, get_subtitle_path
    from translate_tier_translations import load_episode_info, resolve_subtitle_path

    if episode_dir is not None:
        ei = load_episode_info(episode_dir)
        if ei:
            p = resolve_subtitle_path(episode_dir, ei, SUBTITLE_BASE, None)
            if p and p.is_file():
                return p

    if translations_dir is not None:
        ti = _read_translation_info_json(translations_dir)
        if ti:
            ep = _episode_info_from_translation_info(ti)
            if ep.get("subtitle_file"):
                p = resolve_subtitle_path(translations_dir, ep, SUBTITLE_BASE, None)
                if p and p.is_file():
                    return p

    if is_movie:
        p = get_movie_subtitle_path(SUBTITLE_BASE, series_name, year)
    else:
        p = get_subtitle_path(SUBTITLE_BASE, series_name, season, episode)
    return p if p.is_file() else None


async def _send_rare_series_full_list(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    query=None,
    band: Literal["c", "b"],
) -> None:
    """Send full rare-in-series list (C1–C2 or B) from tier_4_rare_*_translations.csv."""
    from translate_tier_translations import (
        TIER_4_RARE_B_CSV,
        TIER_4_RARE_C_CSV,
        TIER_ID_TIER_4B,
        TIER_ID_TIER_4C,
        load_tier_words,
    )

    if band == "c":
        translations_csv = TIER_4_RARE_C_TRANSLATIONS_CSV
        tier_words_csv = TIER_4_RARE_C_CSV
        tier_id = TIER_ID_TIER_4C
        not_loaded_hint = "Send a title first, then use /full or tap **Rare C**."
        missing_episode_hint = "Send the episode title again, then tap **Rare C**."
        empty_tier_msg = (
            "_No rare-in-series (C1–C2) words in this episode’s tier list._ "
            "Re-run analysis if you expect `tier_4_rare_c_words.csv` to be non-empty."
        )
        progress = "⏳ Translating rare-in-series (C1–C2) list…"
        timeout_band = "(C)"
        retry_button = "**Rare C**"
        format_band: Literal["c", "b"] = "c"
    else:
        translations_csv = TIER_4_RARE_B_TRANSLATIONS_CSV
        tier_words_csv = TIER_4_RARE_B_CSV
        tier_id = TIER_ID_TIER_4B
        not_loaded_hint = "Send a title first, then tap **Rare B**."
        missing_episode_hint = "Send the episode title again, then tap **Rare B**."
        empty_tier_msg = "_No rare-in-series (B) words in this episode’s tier list._"
        progress = "⏳ Translating rare-in-series (B) list…"
        timeout_band = "(B)"
        retry_button = "**Rare B**"
        format_band = "b"

    last_dir = context.user_data.get("last_translations_dir")
    if not last_dir:
        msg = f"❌ No episode or movie loaded yet.\n\n{not_loaded_hint}"
        kb = keyboard_discovery(context)
        await _reply_bot_message(update, query=query, text=msg, reply_markup=kb)
        return

    translations_dir = Path(last_dir).resolve()
    if not translations_dir.exists():
        msg = f"❌ Translations folder not found: `{_rel_path(last_dir)}/`"
        kb = keyboard_discovery(context)
        await _reply_bot_message(update, query=query, text=msg, reply_markup=kb)
        return

    series_name, season, episode, is_movie, year = _get_translations_header(
        translations_dir, context
    )
    episode_dir = _resolve_episode_dir(translations_dir, context)
    pairs = _load_translation_pairs_csv(translations_dir / translations_csv)
    sp = _subtitle_path_for_loaded_title(
        series_name,
        season,
        episode,
        is_movie=is_movie,
        year=year,
        episode_dir=episode_dir,
        translations_dir=translations_dir,
    )
    if not pairs:
        header = (
            f"🎬 *{_md1(series_name)}*" + (f" ({year})" if year else "")
            if is_movie
            else f"📺 *{_md1(series_name)}*{_tv_episode_suffix(series_name, season, episode)}"
        )
        kb_loaded = keyboard_loaded(context)

        if episode_dir is None:
            msg = (
                f"{header}\n\n📁 `{_rel_path(last_dir)}/`\n\n"
                "_Could not locate the tier list folder to translate rare words._ "
                f"{missing_episode_hint}"
            )
            await _reply_bot_message(
                update, query=query, text=msg, reply_markup=kb_loaded
            )
            return

        episode_dir = episode_dir.resolve()
        if not load_tier_words(episode_dir, tier_words_csv):
            msg = f"{header}\n\n📁 `{_rel_path(last_dir)}/`\n\n{empty_tier_msg}"
            await _reply_bot_message(
                update, query=query, text=msg, reply_markup=kb_loaded
            )
            return

        await _reply_bot_message(
            update, query=query, text=progress, reply_markup=kb_loaded
        )

        sp = _subtitle_path_for_loaded_title(
            series_name,
            season,
            episode,
            is_movie=is_movie,
            year=year,
            episode_dir=episode_dir,
            translations_dir=translations_dir,
        )
        loop = asyncio.get_running_loop()
        timeout = 600.0
        tid = tier_id
        ed = episode_dir
        try:
            ok, _out_dir, trans_err, _metrics = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda ed=ed, p=sp, t=tid: _do_translate(ed, p, tier_ids=frozenset({t})),
                ),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            msg = (
                f"{header}\n\n❌ **Timed out** translating the rare-in-series {timeout_band} list.\n\n"
                f"Try {retry_button} again."
            )
            await _reply_bot_message(
                update, query=query, text=msg, reply_markup=kb_loaded
            )
            return

        if not ok:
            reason = (trans_err or "Translation failed.").strip()
            msg = f"{header}\n\n❌ **Rare list translation failed.**\n\n{_md1(reason)}"
            await _reply_bot_message(
                update, query=query, text=msg, reply_markup=kb_loaded
            )
            return

        pairs = _load_translation_pairs_csv(translations_dir / translations_csv)
        if not pairs:
            msg = (
                f"{header}\n\n📁 `{_rel_path(last_dir)}/`\n\n"
                "_Rare list translation produced no usable rows._"
            )
            await _reply_bot_message(
                update, query=query, text=msg, reply_markup=kb_loaded
            )
            return

    pairs = _attach_subtitle_examples(pairs, sp)
    user_id = _safe_user_id(update, query=query)
    saved_keys: Collection[str] = ()
    if user_id is not None:
        saved_keys = set(_get_user_dictionary(user_id).keys())
    bot_username = _bot_username_from_context(context)
    word_tokens = _register_word_link_tokens(pairs)
    full_text = _format_rare_in_series_full_list(
        series_name,
        season,
        episode,
        pairs,
        is_movie=is_movie,
        year=year,
        band=format_band,
        saved_keys=saved_keys,
        word_tokens=word_tokens,
        bot_username=bot_username,
    )
    chunks = _split_message_chunks(full_text)
    kb = keyboard_loaded(context)
    if len(chunks) == 1:
        sent = await _reply_bot_message(update, query=query, text=chunks[0], reply_markup=kb)
        if sent and hasattr(sent, "chat_id") and hasattr(sent, "message_id"):
            _persist_word_list_anchor(
                context,
                chat_id=int(sent.chat_id),
                message_id=int(sent.message_id),
                view={
                    "kind": f"rare_{format_band}",
                    "series_name": series_name,
                    "season": season,
                    "episode": episode,
                    "is_movie": is_movie,
                    "year": year,
                    "rows": pairs,
                    "band": format_band,
                },
            )
    else:
        await _reply_bot_chunks(update, query=query, chunks=chunks, reply_markup=kb)


async def send_rare_c_series_full_list(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    query=None,
) -> None:
    """Send full rare-in-series (C1–C2) list from tier_4_rare_c_translations.csv. /full"""
    await _send_rare_series_full_list(update, context, query=query, band="c")


async def send_rare_b_series_full_list(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    query=None,
) -> None:
    """Send full rare-in-series (B-level) list from tier_4_rare_b_translations.csv."""
    await _send_rare_series_full_list(update, context, query=query, band="b")


# Backwards compatibility for tests and /full
async def send_full_list(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    query=None,
) -> None:
    await send_rare_c_series_full_list(update, context, query=query)


async def send_b_level_words(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    query=None,
) -> None:
    """Send B-level translations for the last loaded title. Use query= when invoked from inline button."""
    last_dir = context.user_data.get("last_translations_dir")
    if not last_dir:
        msg = (
            "❌ No episode or movie loaded yet.\n\n"
            "Send a title first, then tap **Frequent B**."
        )
        kb = keyboard_discovery(context)
        await _reply_bot_message(update, query=query, text=msg, reply_markup=kb)
        return

    translations_dir = Path(last_dir).resolve()
    if not translations_dir.exists():
        msg = f"❌ Translations folder not found: `{_rel_path(last_dir)}/`"
        kb = keyboard_discovery(context)
        await _reply_bot_message(update, query=query, text=msg, reply_markup=kb)
        return

    series_name, season, episode, is_movie, year = _get_translations_header(
        translations_dir, context
    )
    episode_dir = _resolve_episode_dir(translations_dir, context)
    b1, b2 = _load_b_level_pairs(translations_dir)
    sp = _subtitle_path_for_loaded_title(
        series_name,
        season,
        episode,
        is_movie=is_movie,
        year=year,
        episode_dir=episode_dir,
        translations_dir=translations_dir,
    )
    kb = keyboard_loaded(context)
    user_id = _safe_user_id(update, query=query)
    saved_keys: Collection[str] = ()
    if user_id is not None:
        saved_keys = set(_get_user_dictionary(user_id).keys())
    title = (
        f"🎬 *{_md1(series_name)}*" + (f" ({year})" if year else "")
        if is_movie
        else f"📺 *{_md1(series_name)}*{_tv_episode_suffix(series_name, season, episode)}"
    )

    if not b1 and not b2:
        from translate_tier_translations import (
            TIER_B1_CSV,
            TIER_B2_CSV,
            TIER_ID_B1,
            TIER_ID_B2,
            load_tier_words,
        )

        has_b_words = episode_dir is not None and bool(
            load_tier_words(episode_dir, TIER_B1_CSV)
            or load_tier_words(episode_dir, TIER_B2_CSV)
        )
        if has_b_words and episode_dir is not None:
            await _reply_bot_message(
                update,
                query=query,
                text=f"📗 *B-level words* — {title}\n\n⏳ Translating B-level list…",
                reply_markup=kb,
            )
            loop = asyncio.get_running_loop()
            ed = episode_dir.resolve()
            try:
                ok, _out_dir, trans_err, _metrics = await asyncio.wait_for(
                    loop.run_in_executor(
                        None,
                        lambda: _do_translate(
                            ed,
                            sp,
                            tier_ids=frozenset({TIER_ID_B1, TIER_ID_B2}),
                        ),
                    ),
                    timeout=600.0,
                )
            except asyncio.TimeoutError:
                await _reply_bot_message(
                    update,
                    query=query,
                    text=f"{title}\n\n❌ **Timed out** translating B-level words.",
                    reply_markup=kb,
                )
                return
            if not ok:
                reason = (trans_err or "Translation failed.").strip()
                await _reply_bot_message(
                    update,
                    query=query,
                    text=f"{title}\n\n❌ **B-level translation failed.**\n\n{_md1(reason)}",
                    reply_markup=kb,
                )
                return
            b1, b2 = _load_b_level_pairs(translations_dir)
        else:
            hint = (
                "\n\n_If this title has B-level words in tier output, re-run translation "
                "to generate the B-level translation file._"
            )
            if episode_dir is None:
                hint = (
                    "\n\n_Could not find the tier list folder for this title. "
                    "Send the episode name again, then tap **Frequent B**._"
                )
            msg = f"📗 *B-level words* — {title}\n\n_No B-level translations in this folder yet._{hint}"
            await _reply_bot_message(update, query=query, text=msg, reply_markup=kb)
            return

    b1 = _attach_subtitle_examples(b1, sp)
    b2 = _attach_subtitle_examples(b2, sp)

    if not b1 and not b2:
        msg = (
            f"📗 *B-level words* — {title}\n\n"
            "_B-level translation produced no usable rows._"
        )
        await _reply_bot_message(update, query=query, text=msg, reply_markup=kb)
        return

    shown_rows = [*b1, *b2][:40]
    bot_username = _bot_username_from_context(context)
    word_tokens = _register_word_link_tokens(shown_rows)
    full_text = _format_b_level_list(
        series_name,
        season,
        episode,
        b1,
        b2,
        is_movie=is_movie,
        year=year,
        saved_keys=saved_keys,
        word_tokens=word_tokens,
        bot_username=bot_username,
    )
    chunks = _split_message_chunks(full_text)
    if len(chunks) == 1:
        sent = await _reply_bot_message(update, query=query, text=chunks[0], reply_markup=kb)
        if sent and hasattr(sent, "chat_id") and hasattr(sent, "message_id"):
            _persist_word_list_anchor(
                context,
                chat_id=int(sent.chat_id),
                message_id=int(sent.message_id),
                view={
                    "kind": "b_level",
                    "series_name": series_name,
                    "season": season,
                    "episode": episode,
                    "is_movie": is_movie,
                    "year": year,
                    "rows": shown_rows,
                },
            )
    else:
        await _reply_bot_chunks(update, query=query, chunks=chunks, reply_markup=kb)


def _read_translation_info_json(translations_dir: Path) -> Optional[Dict[str, Any]]:
    p = translations_dir / "translation_info.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _episode_info_from_translation_info(data: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "series": data.get("series") or "",
        "subtitle_file": data.get("source_subtitle") or "",
        "season_number": int(data.get("season_number", 0)),
        "episode_number": int(data.get("episode_number", 0)),
        "is_movie": bool(data.get("is_movie", False)),
        "year": int(data.get("year", 0)),
    }


def _resolve_subtitle_for_phrasal(
    translations_dir: Path,
    context: ContextTypes.DEFAULT_TYPE,
) -> Optional[Path]:
    """Locate .srt for phrasal extraction using translation_info.json or tier list episode_info."""
    from translate_tier_translations import load_episode_info, resolve_subtitle_path

    ti = _read_translation_info_json(translations_dir)
    if ti:
        ep = _episode_info_from_translation_info(ti)
        # subtitle_file alone is enough; resolve_subtitle_path can locate by basename under Subtitle/
        if ep.get("subtitle_file"):
            p = resolve_subtitle_path(translations_dir, ep, SUBTITLE_BASE, None)
            if p and p.exists():
                return p

    led = context.user_data.get("last_episode_dir")
    if led:
        ed = Path(led)
        ei = load_episode_info(ed)
        if ei:
            p = resolve_subtitle_path(ed, ei, SUBTITLE_BASE, None)
            if p and p.exists():
                return p
    return None


def _series_name_for_phrasal(translations_dir: Path, context: ContextTypes.DEFAULT_TYPE) -> str:
    ti = _read_translation_info_json(translations_dir)
    if ti and ti.get("series"):
        return str(ti["series"])
    return str(context.user_data.get("last_series_name") or "Unknown")


def _run_extract_phrasal_verbs(
    subtitle_path: Path,
    translations_dir: Path,
    series_name: str,
    api_key: str,
) -> bool:
    from phrasal_verbs import extract_phrasal_verbs_from_episode

    return extract_phrasal_verbs_from_episode(
        subtitle_path, translations_dir, series_name, api_key
    )


def _run_extract_idiomatic_expressions(
    subtitle_path: Path,
    translations_dir: Path,
    series_name: str,
    api_key: str,
    season: int,
    episode: int,
) -> bool:
    from idiomatic_expressions import extract_idioms_from_episode

    s = season if season > 0 else 1
    e = episode if episode > 0 else 1
    return extract_idioms_from_episode(
        subtitle_path,
        translations_dir,
        series_name,
        api_key,
        season_number=s,
        episode_number=e,
    )


def _load_phrasal_rows(translations_dir: Path) -> List[Tuple[str, str, str, str, str]]:
    """Rows for display: pv, freq, translation, example, optional score note (legacy CSVs supported)."""
    path = translations_dir / PHRASAL_VERBS_CSV
    rows: List[Tuple[str, str, str, str, str]] = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            pv = (row.get("phrasal_verb") or row.get("verb") or "").strip()
            if not pv:
                continue
            freq = (row.get("frequency") or "").strip()
            tr = (row.get("translation") or "").strip()
            ex = (row.get("example") or "").strip()
            idi = (row.get("idiomaticity_score") or "").strip()
            lit = (row.get("literality_score") or "").strip()
            if idi or lit:
                note = f"id{idi}/lit{lit}" if idi and lit else (idi or lit)
            else:
                note = (row.get("phrasality_score") or "").strip()
            rows.append((pv, freq, tr, ex, note))
    return rows


def _load_idiom_rows(translations_dir: Path) -> List[Tuple[str, str, str, str, str]]:
    """Rows: expression, freq, translation, example, idiomacy_rating (or legacy idiomaticity_score)."""
    path = translations_dir / IDIOMATIC_EXPRESSIONS_CSV
    rows: List[Tuple[str, str, str, str, str]] = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            expr = (row.get("expression") or "").strip()
            if not expr:
                continue
            freq = (row.get("frequency") or "").strip()
            tr = (row.get("translation") or "").strip()
            ex = (row.get("example") or "").strip()
            rating = (row.get("idiomacy_rating") or row.get("idiomaticity_score") or "").strip()
            rows.append((expr, freq, tr, ex, rating))
    return rows


def _format_phrasal_list(
    series_name: str,
    season: int,
    episode: int,
    rows: List[Tuple[str, str, str, str, str]],
    *,
    is_movie: bool = False,
    year: int = 0,
    full_total: Optional[int] = None,
) -> str:
    """Format phrasal list. If ``full_total`` is set and greater than ``len(rows)``, label as a preview."""
    shown = len(rows)
    if is_movie:
        title = (
            f"🔤 *Phrasal verbs* — 🎬 *{_md1(series_name)}*"
            + (f" ({year})" if year else "")
        )
    else:
        title = (
            f"🔤 *Phrasal verbs* — 📺 *{_md1(series_name)}*"
            f"{_tv_episode_suffix(series_name, season, episode)}"
        )
    if not rows:
        return f"{title}\n\n_No phrasal verbs._"

    if full_total is not None and full_total > shown:
        stats = (
            f"📊 *Top {shown} of {full_total}* phrasal verbs"
            f" — _Use the 📋 All phrasal verbs button for the rest._\n\n"
        )
    else:
        stats = f"📊 *{shown}* phrasal verbs\n\n"

    header = f"{title}\n\n{stats}"
    lines: List[str] = []
    for i, row in enumerate(rows, 1):
        pv, _freq, tr, ex = row[0], row[1], row[2], row[3]
        disp = tr if tr else "N/A"
        line = f"{i}. *{pv}* → {disp}"
        if ex and ex not in ("N/A", ""):
            short = ex[:180] + ("…" if len(ex) > 180 else "")
            line += f"\n   _{short}_"
        lines.append(line)
    return header + "\n".join(lines)


def _format_idiom_list(
    series_name: str,
    season: int,
    episode: int,
    rows: List[Tuple[str, str, str, str, str]],
    *,
    is_movie: bool = False,
    year: int = 0,
    full_total: Optional[int] = None,
) -> str:
    """Format repeated idioms list (preview or full)."""
    shown = len(rows)
    if is_movie:
        title = (
            f"💬 *Idioms* — 🎬 *{_md1(series_name)}*"
            + (f" ({year})" if year else "")
        )
    else:
        title = (
            f"💬 *Idioms* — 📺 *{_md1(series_name)}*"
            f"{_tv_episode_suffix(series_name, season, episode)}"
        )
    if not rows:
        return f"{title}\n\n_No idioms._"

    if full_total is not None and full_total > shown:
        stats = (
            f"📊 *Top {shown} of {full_total}* idioms"
            f" — _Use the 📋 All idioms button for the rest._\n\n"
        )
    else:
        stats = f"📊 *{shown}* idioms\n\n"

    header = f"{title}\n\n{stats}"
    lines: List[str] = []
    for i, row in enumerate(rows, 1):
        expr, _freq, tr, ex, rating = row[0], row[1], row[2], row[3], row[4]
        disp = tr if tr else "N/A"
        line = f"{i}. *{expr}* → {disp}"
        if rating:
            line += f" _(idiomacy {rating}/10)_"
        if ex and ex not in ("N/A", ""):
            short = ex[:180] + ("…" if len(ex) > 180 else "")
            line += f"\n   _{short}_"
        lines.append(line)
    return header + "\n".join(lines)


def _keyboard_with_list_extras(
    context: ContextTypes.DEFAULT_TYPE,
    translations_dir: Path,
    *,
    phrasal_all_count: Optional[int] = None,
    hide_phrasal_all_button: bool = False,
    idiom_all_count: Optional[int] = None,
    hide_idiom_all_button: bool = False,
) -> InlineKeyboardMarkup:
    """Build loaded keyboard; optional overrides for 'show all' rows (e.g. after preview)."""
    if hide_phrasal_all_button:
        pc: Optional[int] = None
    elif phrasal_all_count is not None:
        pc = (
            phrasal_all_count
            if phrasal_all_count > PHRASAL_VERBS_PREVIEW_LIMIT
            else None
        )
    else:
        pc = _extra_preview_count(
            translations_dir / PHRASAL_VERBS_CSV, PHRASAL_VERBS_PREVIEW_LIMIT
        )

    if hide_idiom_all_button:
        ic: Optional[int] = None
    elif idiom_all_count is not None:
        ic = idiom_all_count if idiom_all_count > IDIOMS_PREVIEW_LIMIT else None
    else:
        ic = _extra_preview_count(
            translations_dir / IDIOMATIC_EXPRESSIONS_CSV, IDIOMS_PREVIEW_LIMIT
        )

    return keyboard_loaded(context, extra_phrasal_count=pc, extra_idiom_count=ic)


async def send_phrasal_verbs(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    query=None,
    show_all: bool = False,
) -> None:
    """Load or generate phrasal_verbs.csv; send top N preview unless ``show_all``."""
    last_dir = context.user_data.get("last_translations_dir")
    kb_empty = keyboard_discovery(context)

    if not last_dir:
        msg = (
            "❌ No episode or movie loaded yet.\n\n"
            "Send a title first, then tap **Phrasal verbs** or use /phrasal."
        )
        await _reply_bot_message(
            update, query=query, text=msg, reply_markup=kb_empty
        )
        return

    translations_dir = Path(last_dir).resolve()
    if not translations_dir.exists():
        msg = f"❌ Translations folder not found: `{_rel_path(last_dir)}/`"
        await _reply_bot_message(
            update, query=query, text=msg, reply_markup=kb_empty
        )
        return

    kb_after = _keyboard_with_list_extras(context, translations_dir)

    series_name, season, episode, is_movie, year = _get_translations_header(
        translations_dir, context
    )
    csv_path = translations_dir / PHRASAL_VERBS_CSV
    loop = asyncio.get_running_loop()

    if not csv_path.exists():
        if not OPENAI_API_KEY.strip():
            msg = (
                "❌ *OPENAI_API_KEY* is not set.\n\n"
                "Set it to extract and translate phrasal verbs and idioms."
            )
            await _reply_bot_message(
                update, query=query, text=msg, reply_markup=kb_after
            )
            return

        subtitle_path = _resolve_subtitle_for_phrasal(translations_dir, context)
        if not subtitle_path:
            msg = (
                "❌ Could not find the subtitle file for this title.\n\n"
                "Ensure subtitles exist under `Subtitle/` for this episode or movie."
            )
            await _reply_bot_message(
                update, query=query, text=msg, reply_markup=kb_after
            )
            return

        sn = _series_name_for_phrasal(translations_dir, context)
        loading = "🔤 *Phrasal verbs*\n\n⏳ Extracting and translating…"
        await _reply_bot_message(
            update, query=query, text=loading, reply_markup=kb_after
        )

        ok = await loop.run_in_executor(
            None,
            lambda: _run_extract_phrasal_verbs(
                subtitle_path, translations_dir, sn, OPENAI_API_KEY.strip()
            ),
        )
        if not ok:
            err = (
                "❌ Could not build a phrasal verb list (no matches or read error).\n\n"
                f"📁 `{_rel_path(str(translations_dir))}/`"
            )
            await _reply_bot_message(
                update, query=query, text=err, reply_markup=kb_after
            )
            return

    rows = _load_phrasal_rows(translations_dir)
    total_n = len(rows)
    if show_all or total_n <= PHRASAL_VERBS_PREVIEW_LIMIT:
        display_rows = rows
        full_text = _format_phrasal_list(
            series_name,
            season,
            episode,
            display_rows,
            is_movie=is_movie,
            year=year,
        )
        kb = _keyboard_with_list_extras(
            context, translations_dir, hide_phrasal_all_button=True
        )
    else:
        display_rows = rows[:PHRASAL_VERBS_PREVIEW_LIMIT]
        full_text = _format_phrasal_list(
            series_name,
            season,
            episode,
            display_rows,
            is_movie=is_movie,
            year=year,
            full_total=total_n,
        )
        kb = _keyboard_with_list_extras(
            context, translations_dir, phrasal_all_count=total_n
        )

    chunks = _split_message_chunks(full_text)
    await _reply_bot_chunks(update, query=query, chunks=chunks, reply_markup=kb)


async def _send_idioms_disabled_placeholder(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    query=None,
) -> None:
    """Telegram Markdown message when idioms are temporarily unavailable."""
    last_dir = context.user_data.get("last_translations_dir")
    kb_empty = keyboard_discovery(context)
    kb: InlineKeyboardMarkup
    if last_dir:
        td = Path(last_dir).resolve()
        if td.is_dir():
            kb = _keyboard_with_list_extras(
                context, td, hide_idiom_all_button=True
            )
        else:
            kb = kb_empty
    else:
        kb = kb_empty
    await _reply_bot_message(
        update, query=query, text=_IDIOMS_WIP_MESSAGE, reply_markup=kb
    )


async def send_idiomatic_expressions(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    query=None,
    show_all: bool = False,
) -> None:
    """Load or generate idiomatic_expressions.csv; send top N preview unless ``show_all``."""
    if not IDIOMS_FEATURE_ENABLED:
        await _send_idioms_disabled_placeholder(update, context, query=query)
        return

    last_dir = context.user_data.get("last_translations_dir")
    kb_empty = keyboard_discovery(context)

    if not last_dir:
        msg = (
            "❌ No episode or movie loaded yet.\n\n"
            "Send a title first, then tap **Idioms** or use /idioms."
        )
        await _reply_bot_message(
            update, query=query, text=msg, reply_markup=kb_empty
        )
        return

    translations_dir = Path(last_dir).resolve()
    if not translations_dir.exists():
        msg = f"❌ Translations folder not found: `{_rel_path(last_dir)}/`"
        await _reply_bot_message(
            update, query=query, text=msg, reply_markup=kb_empty
        )
        return

    kb_after = _keyboard_with_list_extras(context, translations_dir)

    series_name, season, episode, is_movie, year = _get_translations_header(
        translations_dir, context
    )
    csv_path = translations_dir / IDIOMATIC_EXPRESSIONS_CSV
    loop = asyncio.get_running_loop()

    if not csv_path.exists():
        if not OPENAI_API_KEY.strip():
            msg = (
                "❌ *OPENAI_API_KEY* is not set.\n\n"
                "Set it to extract and translate idioms."
            )
            await _reply_bot_message(
                update, query=query, text=msg, reply_markup=kb_after
            )
            return

        subtitle_path = _resolve_subtitle_for_phrasal(translations_dir, context)
        if not subtitle_path:
            msg = (
                "❌ Could not find the subtitle file for this title.\n\n"
                "Ensure subtitles exist under `Subtitle/` for this episode or movie."
            )
            await _reply_bot_message(
                update, query=query, text=msg, reply_markup=kb_after
            )
            return

        sn = _series_name_for_phrasal(translations_dir, context)
        loading = "💬 *Idioms*\n\n⏳ Extracting repeated expressions and translating…"
        await _reply_bot_message(
            update, query=query, text=loading, reply_markup=kb_after
        )

        ok = await loop.run_in_executor(
            None,
            lambda: _run_extract_idiomatic_expressions(
                subtitle_path,
                translations_dir,
                sn,
                OPENAI_API_KEY.strip(),
                season,
                episode,
            ),
        )
        if not ok:
            err = (
                "❌ Could not build an idiom list (no repeated matches or read error).\n\n"
                f"📁 `{_rel_path(str(translations_dir))}/`"
            )
            await _reply_bot_message(
                update, query=query, text=err, reply_markup=kb_after
            )
            return

    rows = _load_idiom_rows(translations_dir)
    total_n = len(rows)
    if show_all or total_n <= IDIOMS_PREVIEW_LIMIT:
        display_rows = rows
        full_text = _format_idiom_list(
            series_name,
            season,
            episode,
            display_rows,
            is_movie=is_movie,
            year=year,
        )
        kb = _keyboard_with_list_extras(
            context, translations_dir, hide_idiom_all_button=True
        )
    else:
        display_rows = rows[:IDIOMS_PREVIEW_LIMIT]
        full_text = _format_idiom_list(
            series_name,
            season,
            episode,
            display_rows,
            is_movie=is_movie,
            year=year,
            full_total=total_n,
        )
        kb = _keyboard_with_list_extras(
            context, translations_dir, idiom_all_count=total_n
        )

    chunks = _split_message_chunks(full_text)
    await _reply_bot_chunks(update, query=query, chunks=chunks, reply_markup=kb)


async def show_my_words(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    query=None,
) -> None:
    user_id = _safe_user_id(update, query=query)
    if user_id is None:
        await _reply_bot_message(
            update,
            query=query,
            text="❌ Could not identify the user for personal dictionary.",
            reply_markup=keyboard_discovery(context),
        )
        return
    words_map = _get_user_dictionary(user_id)
    if not words_map:
        await _reply_bot_message(
            update,
            query=query,
            text="📚 Личный словарь пока пуст.\n\nДобавляй слова кликом по ним в списках перевода.",
            reply_markup=keyboard_loaded(context),
            parse_mode=None,
        )
        return
    rows: List[Tuple[str, str, str]] = []
    for payload in words_map.values():
        rows.append(
            (
                payload.get("word", ""),
                payload.get("translation", ""),
                payload.get("example", ""),
            )
        )
    rows.sort(key=lambda item: item[0].lower())
    text = (
        "📚 *My words*\n\n"
        f"📊 *Saved words: {len(rows)}*\n\n"
        + "\n".join(
            _format_word_entry_line(i, w, t, ex, is_saved=True)
            for i, (w, t, ex) in enumerate(rows, 1)
        )
    )
    for part in _split_message_chunks(text):
        await _reply_bot_message(
            update,
            query=query,
            text=part,
            reply_markup=keyboard_loaded(context),
        )


def _render_word_view_text(
    view: Dict[str, Any],
    saved_keys: Collection[str],
    *,
    bot_username: str = "",
) -> str:
    kind = view.get("kind", "")
    rows = view.get("rows", [])
    series_name = view.get("series_name", "Unknown")
    season = int(view.get("season", 0))
    episode = int(view.get("episode", 0))
    is_movie = bool(view.get("is_movie", False))
    year = int(view.get("year", 0))
    word_tokens = _register_word_link_tokens(rows)
    if kind == "b_level":
        return _format_b_level_list(
            series_name,
            season,
            episode,
            rows,
            [],
            is_movie=is_movie,
            year=year,
            saved_keys=saved_keys,
            word_tokens=word_tokens,
            bot_username=bot_username,
        )
    if kind.startswith("rare_"):
        return _format_rare_in_series_full_list(
            series_name,
            season,
            episode,
            rows,
            is_movie=is_movie,
            year=year,
            band=view.get("band", "c"),
            saved_keys=saved_keys,
            word_tokens=word_tokens,
            bot_username=bot_username,
        )
    return _format_word_list(
        series_name,
        season,
        episode,
        rows,
        is_movie=is_movie,
        year=year,
        max_lines=max(1, len(rows)),
        saved_keys=saved_keys,
        word_tokens=word_tokens,
        bot_username=bot_username,
    )


async def _refresh_word_list_anchor(
    context: ContextTypes.DEFAULT_TYPE,
    *,
    saved_keys: Collection[str],
) -> None:
    anchor = context.user_data.get("word_list_anchor")
    if not anchor or not getattr(context, "bot", None):
        return
    bot_username = _bot_username_from_context(context)
    text = _render_word_view_text(
        anchor["view"], saved_keys, bot_username=bot_username
    )
    kb = keyboard_loaded(context)
    try:
        await context.bot.edit_message_text(
            chat_id=int(anchor["chat_id"]),
            message_id=int(anchor["message_id"]),
            text=text,
            parse_mode="Markdown",
            reply_markup=kb,
        )
    except BadRequest:
        await context.bot.edit_message_text(
            chat_id=int(anchor["chat_id"]),
            message_id=int(anchor["message_id"]),
            text=text,
            parse_mode=None,
            reply_markup=kb,
        )


async def _handle_dictionary_deep_link(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    token: str,
) -> None:
    user_id = _safe_user_id(update)
    if user_id is None:
        return
    if not _toggle_dictionary_word_by_token(user_id, token):
        await update.message.reply_text(
            "Не удалось найти слово. Откройте список слов заново.",
            reply_markup=keyboard_loaded(context),
        )
        return
    try:
        await update.message.delete()
    except Exception:
        pass
    saved_keys = set(_get_user_dictionary(user_id).keys())
    await _refresh_word_list_anchor(context, saved_keys=saved_keys)


# Registered in main() as /phrasal; keep name so main() stays unchanged.
send_phrasal_placeholder = send_phrasal_verbs
send_idioms_placeholder = send_idiomatic_expressions


async def _handle_title_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    query: Any,
    data: str,
    wrapped: Any,
) -> None:
    parts = data.split(":")
    if len(parts) < 2:
        await query.answer("Invalid action.", show_alert=True)
        return
    action, token = parts[0], parts[1]
    pick_index: Optional[int] = None
    if len(parts) > 2 and action == "title_pick":
        try:
            pick_index = int(parts[2])
        except ValueError:
            pick_index = None

    pending = context.user_data.get("pending_title")
    if not pending or pending.get("token") != token:
        await query.answer("Confirmation expired — send the title again.", show_alert=True)
        return

    latency = pending.get("latency")
    req_started = float(pending.get("req_started") or time.perf_counter())
    context.user_data.pop("pending_title", None)

    if action == "title_cancel":
        if isinstance(latency, dict):
            latency["status"] = "cancelled"
            latency["error"] = "user_cancelled"
            latency["finished_at"] = datetime.now().isoformat()
            latency["timings_ms"]["total_e2e_ms"] = _ms_since(req_started)
            await _write_latency_async(latency)
        await _reply_bot_message(
            wrapped,
            query=query,
            text="Cancelled. Send another title or tap **Next series**.",
            reply_markup=keyboard_discovery(context),
            parse_mode="Markdown",
        )
        return

    if action == "title_use":
        identity = _identity_from_pending_choice(pending, "use")
    elif action == "title_keep":
        identity = _identity_from_pending_choice(pending, "keep")
    elif action == "title_pick":
        identity = _identity_from_pending_choice(pending, "pick", pick_index)
    else:
        await query.answer("Unknown action.", show_alert=True)
        return

    if not isinstance(latency, dict):
        latency = _new_latency(pending.get("raw") or "", pending.get("media_type") or "series")

    mt = identity.get("media_type") or pending.get("media_type")
    if mt == "movie":
        label = _movie_label(
            identity.get("movie_name") or identity.get("canonical_title") or "?",
            int(identity.get("year") or 0),
        )
    else:
        sn = identity.get("series_name") or identity.get("canonical_title") or "?"
        label = f"*{_md1(sn)}*{_tv_episode_suffix(sn, int(identity.get('season', 1)), int(identity.get('episode', 1)))}"

    await _reply_bot_message(
        wrapped,
        query=query,
        text=f"⏳ Processing {label}…",
        reply_markup=keyboard_discovery(context),
        parse_mode="Markdown",
    )

    if mt == "movie":
        await _run_movie_pipeline(wrapped, context, identity, latency, req_started)
    else:
        await _run_series_pipeline(wrapped, context, identity, latency, req_started)


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    await query.answer()
    data = query.data or ""
    if not query.message:
        return

    class WrappedUpdate:
        def __init__(self, msg):
            self.message = msg

    wrapped = WrappedUpdate(query.message)

    try:
        if data.startswith("title_"):
            await _handle_title_callback(update, context, query, data, wrapped)
        elif data == "frequent_c_words":
            await send_frequent_c_words(wrapped, context, query=query)
        elif data == "rare_c_series":
            await send_rare_c_series_full_list(wrapped, context, query=query)
        elif data == "rare_b_series":
            await send_rare_b_series_full_list(wrapped, context, query=query)
        elif data == "b_level_words":
            await send_b_level_words(wrapped, context, query=query)
        elif data == "phrasal_verbs":
            await send_phrasal_verbs(wrapped, context, query=query)
        elif data == "phrasal_verbs_all":
            await send_phrasal_verbs(wrapped, context, query=query, show_all=True)
        elif data == "idiomatic_expressions":
            await send_idiomatic_expressions(wrapped, context, query=query)
        elif data == "idiomatic_expressions_all":
            await send_idiomatic_expressions(wrapped, context, query=query, show_all=True)
        elif data == "show_my_words":
            await show_my_words(wrapped, context, query=query)
        elif data == "next_series":
            await next_series(wrapped, context)
        elif data == "next_movie":
            await next_movie(wrapped, context)
        else:
            await _reply_bot_message(
                wrapped,
                query=query,
                text="Unknown action.",
                reply_markup=keyboard_discovery(context),
                parse_mode=None,
            )
    except Exception as e:
        print(f"button_callback error ({data}): {e}", flush=True)
        kb = keyboard_loaded(context) if context.user_data.get("last_translations_dir") else keyboard_discovery(context)
        await _reply_bot_message(
            wrapped,
            query=query,
            text=(
                "❌ **Could not show that list.**\n\n"
                f"{_md1(str(e)[:200])}\n\n"
                "Try sending the title again, or tap the button once more."
            ),
            reply_markup=kb,
        )


async def handle_document_placeholder(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "📥 Subtitle file upload: *coming soon.*\n\n"
        "For now, send a TV series or movie title (e.g. _Game of Thrones s2 e3_) to build a word list.",
        parse_mode="Markdown",
        reply_markup=keyboard_discovery(context),
    )


def main() -> None:
    global BOT_BUILD_DATETIME
    if not TELEGRAM_BOT_TOKEN:
        print("Set TELEGRAM_BOT_TOKEN in the environment.")
        return
    BOT_BUILD_DATETIME = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"Bot build (start) time: {BOT_BUILD_DATETIME}", flush=True)
    print("Bot running. Real output: hard-word translations saved under translations/", flush=True)
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("next", next_series))
    app.add_handler(CommandHandler("movie", next_movie))
    app.add_handler(CommandHandler("full", send_full_list))
    app.add_handler(CommandHandler("mywords", show_my_words))
    app.add_handler(CommandHandler("phrasal", send_phrasal_placeholder))
    app.add_handler(CommandHandler("idioms", send_idioms_placeholder))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document_placeholder))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    # Retry bootstrap forever to survive transient Telegram/network hiccups.
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        bootstrap_retries=-1,
    )


if __name__ == "__main__":
    main()
