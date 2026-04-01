#!/usr/bin/env python3
"""
Telegram bot: request by series name → (use cache if present) → analyze subtitle → translate hard words → save to translations folder.
Uses existing tier lists and translations when found; shows step-by-step status like the archive.
"""

import asyncio
import csv
import json
import os
import re
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Collection, Dict, List, Optional, Tuple

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)

# Telegram bot token (from archive codebase)
TELEGRAM_BOT_TOKEN = os.environ.get(
    "TELEGRAM_BOT_TOKEN",
    "8525395469:AAG5uDLN0kmUYyZAMvfVI_0LrIO4RnCcR54",
)
def _openai_key_from_archive() -> str:
    """Fallback: load OpenAI API key from Archieve/Code archive/telegram_bot.py when env is not set."""
    try:
        archive_dir = Path(__file__).resolve().parent / "Archieve" / "Code archive"
        if archive_dir.exists():
            import importlib.util
            spec = importlib.util.spec_from_file_location("archive_telegram_bot", archive_dir / "telegram_bot.py")
            if spec and spec.loader:
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                key = getattr(mod, "OPENAI_API_KEY", None)
                if key and isinstance(key, str) and key.strip():
                    return key.strip()
    except Exception:
        pass
    return ""


OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY") or _openai_key_from_archive() or ""
OPENSUBTITLES_API_KEY = os.environ.get("OPENSUBTITLES_API_KEY", "8FcGUu17mWuXoaqMxKQisSvjXhvjZdct")

# Build/start time set when main() runs (see main())
BOT_BUILD_DATETIME = ""
# Shown in /start (tests assert this appears in the welcome text)
BOT_VERSION = "0.1"
BASE_DIR = Path(__file__).resolve().parent
SUBTITLE_BASE = BASE_DIR / "Subtitle"
TIERLIST_BASE = BASE_DIR / "Tier_lists"
TRANSLATIONS_BASE = BASE_DIR / "translations"
# Rare-in-series lists (high English frequency, low frequency in this episode); see subtitle_analyzer tier_4 split
TIER_4_RARE_C_TRANSLATIONS_CSV = "tier_4_rare_c_translations.csv"
TIER_4_RARE_B_TRANSLATIONS_CSV = "tier_4_rare_b_translations.csv"
PHRASAL_VERBS_CSV = "phrasal_verbs.csv"
PHRASAL_VERBS_PREVIEW_LIMIT = 15
LATENCY_METRICS_BASE = BASE_DIR / "latency_metrics"


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
) -> InlineKeyboardMarkup:
    """After a title is loaded: frequent/rare lists, phrasal, optional full-phrasal row, next series."""
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
        [InlineKeyboardButton("🔤 Phrasal verbs", callback_data="phrasal_verbs")],
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
    rows.append([InlineKeyboardButton("📺 Next series", callback_data="next_series")])
    return InlineKeyboardMarkup(rows)


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
    if not OPENAI_API_KEY or not user_input.strip():
        return None
    prompt = f"""The user wants frequent hard words from a TV series (with Russian glosses). They entered: "{user_input}"

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
        client = OpenAI(api_key=OPENAI_API_KEY)
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


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data["mode"] = "series"
    build = BOT_BUILD_DATETIME or "unknown"
    await update.message.reply_text(
        "👋 Welcome to **SerialTranslate**.\n\n"
        "**What you get:** harder English words that show up *often* in a specific TV episode or "
        "movie — with Russian glosses, built from real subtitles.\n\n"
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
    episode_dir = run_pipeline(
        subtitle_path=subtitle_path,
        base_dir=BASE_DIR,
        tierlist_base_dir=TIERLIST_BASE,
        max_english_freq=20_000_000,
        openai_api_key=OPENAI_API_KEY or None,
        metrics_out=analyze_metrics,
        handoff_out=handoff,
        skip_if_outputs_fresh=True,
    )
    if not episode_dir or not (episode_dir / "tier_1_hard_usable_words.csv").exists():
        return None, analyze_metrics, None
    raw = handoff.get("subtitle_raw")
    return episode_dir, analyze_metrics, raw if isinstance(raw, str) else None


def _do_download_movie(movie_name: str, year: int) -> Optional[Path]:
    """Download movie subtitle. Returns subtitle path or None."""
    from download_movie_subtitles import download_movie_subtitle

    path = download_movie_subtitle(
        movie_title=movie_name,
        year=year,
        base_dir=SUBTITLE_BASE,
        api_key=OPENSUBTITLES_API_KEY,
    )
    return path


def _do_analyze_movie(
    subtitle_path: Path, movie_name: str, year: int
) -> Tuple[Optional[Path], Dict[str, int], Optional[str]]:
    """Run tier pipeline for movie. Returns (episode_dir_or_none, analyze_metrics, subtitle_raw_for_translate)."""
    from subtitle_analyzer import run_pipeline

    analyze_metrics: Dict[str, int] = {}
    handoff: Dict[str, Any] = {}
    episode_dir = run_pipeline(
        subtitle_path=subtitle_path,
        base_dir=BASE_DIR,
        tierlist_base_dir=TIERLIST_BASE,
        max_english_freq=20_000_000,
        openai_api_key=OPENAI_API_KEY or None,
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
    ok, err = run_translate(
        episode_dir=episode_dir,
        subtitle_path=subtitle_path,
        api_key=OPENAI_API_KEY or None,
        translations_base=TRANSLATIONS_BASE,
        subtitle_base=SUBTITLE_BASE,
        metrics_out=metrics,
        subtitle_raw=subtitle_raw,
        translation_overwrite=translation_overwrite,
        tier_ids=tiers,
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
    """Handle movie search flow: parse, find existing, download, analyze, translate."""
    req_started = time.perf_counter()
    latency = _new_latency(raw, "movie")
    phase_started = time.perf_counter()
    movie_name, year = _parse_movie_input(raw)
    latency["phase_timings_ms"]["parse_input"] = _ms_since(phase_started)
    latency["identity"] = {"movie_name": movie_name, "year": year}
    label = f"*{movie_name}*" + (f" ({year})" if year else "")
    status_msg = await update.message.reply_text(
        f"🎬 Processing request for: {label}\n\n"
        "⏳ Looking for a saved word list or translations…",
        parse_mode="Markdown",
        reply_markup=keyboard_discovery(context),
    )

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

        # Case A: translations already exist
        if translations_dir is not None:
            latency["branch"] = "cache_hit_translations"
            await status_msg.edit_text(
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
            context.user_data["last_episode_dir"] = str(episode_dir) if episode_dir else ""
            context.user_data["last_series_name"] = movie_name
            context.user_data["last_translations_dir"] = str(translations_dir)
            latency["status"] = "success"
            return

        # Case B: tier list exists but no translations
        if episode_dir is not None:
            latency["branch"] = "tier_exists_translate_only"
            await status_msg.edit_text(
                f"🎬 Processing: {label}\n"
                f"✅ Found existing hard words list.\n\n"
                "⏳ Translating words…",
                parse_mode="Markdown",
                reply_markup=keyboard_discovery(context),
            )
            if subtitle_path is None:
                await status_msg.edit_text(
                    f"🎬 Processing: {label}\n"
                    "⏳ Subtitle file missing, downloading…",
                    parse_mode="Markdown",
                    reply_markup=keyboard_discovery(context),
                )
                phase_started = time.perf_counter()
                subtitle_path = await asyncio.wait_for(
                    loop.run_in_executor(
                        None,
                        lambda: _do_download_movie(movie_name, year),
                    ),
                    timeout=timeout,
                )
                latency["phase_timings_ms"]["download_subtitle"] = _ms_since(phase_started)
                if not subtitle_path:
                    await status_msg.edit_text(
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
                await status_msg.edit_text(
                    f"❌ **Translation failed.**\n\n{reason}",
                    parse_mode="Markdown",
                    reply_markup=keyboard_discovery(context),
                )
                latency["status"] = "failed"
                latency["error"] = reason
                return
            rel = out_dir.relative_to(BASE_DIR)
            await status_msg.edit_text(
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
            context.user_data["last_episode_dir"] = str(episode_dir)
            context.user_data["last_series_name"] = movie_name
            context.user_data["last_translations_dir"] = str(out_dir)
            latency["status"] = "success"
            return

        # Case C: nothing exists — download, analyze, translate
        latency["branch"] = "full_pipeline"
        await status_msg.edit_text(
            f"🎬 Processing: {label}\n\n"
            "⏳ Downloading subtitle…",
            parse_mode="Markdown",
            reply_markup=keyboard_discovery(context),
        )
        phase_started = time.perf_counter()
        subtitle_path = await asyncio.wait_for(
            loop.run_in_executor(
                None,
                lambda: _do_download_movie(movie_name, year),
            ),
            timeout=timeout,
        )
        latency["phase_timings_ms"]["download_subtitle"] = _ms_since(phase_started)
        if not subtitle_path:
            await status_msg.edit_text(
                f"❌ **Subtitle download failed** for {label}.\n\n"
                "Possible causes: wrong movie name, or subtitle not on OpenSubtitles.",
                parse_mode="Markdown",
                reply_markup=keyboard_discovery(context),
            )
            latency["status"] = "failed"
            latency["error"] = "subtitle_download_failed"
            return

        await status_msg.edit_text(
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
                lambda: _do_analyze_movie(subtitle_path, movie_name, year),
            ),
            timeout=timeout,
        )
        latency["phase_timings_ms"]["analyze_subtitle"] = _ms_since(phase_started)
        latency["analyze_metrics"] = analyze_metrics
        if not episode_dir:
            await status_msg.edit_text(
                "❌ **Hard-word list build failed** (could not read the subtitle).\n\n"
                "The file may be invalid or empty.",
                parse_mode="Markdown",
                reply_markup=keyboard_discovery(context),
            )
            latency["status"] = "failed"
            latency["error"] = "tier_list_build_failed"
            return

        await status_msg.edit_text(
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
                lambda: _do_translate(
                    episode_dir, subtitle_path, subtitle_raw=subtitle_raw_handoff
                ),
            ),
            timeout=timeout,
        )
        latency["phase_timings_ms"]["translate"] = _ms_since(phase_started)
        latency["translator_metrics"] = translator_metrics
        if not ok or not out_dir:
            reason = (trans_err or "Translation failed.").strip()
            await status_msg.edit_text(
                f"❌ **Translation failed.**\n\n{reason}",
                parse_mode="Markdown",
                reply_markup=keyboard_discovery(context),
            )
            latency["status"] = "failed"
            latency["error"] = reason
            return

        rel = out_dir.relative_to(BASE_DIR)
        await status_msg.edit_text(
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
        context.user_data["last_episode_dir"] = str(episode_dir)
        context.user_data["last_series_name"] = movie_name
        context.user_data["last_translations_dir"] = str(out_dir)
        latency["status"] = "success"

    except asyncio.TimeoutError:
        await status_msg.edit_text(
            "❌ **Request timed out** (download/analysis/translation took too long).",
            parse_mode="Markdown",
            reply_markup=keyboard_discovery(context),
        )
        latency["status"] = "timeout"
        latency["error"] = "request_timeout"
    except Exception as e:
        await status_msg.edit_text(
            f"❌ **Error:** {str(e)[:150]}",
            parse_mode="Markdown",
            reply_markup=keyboard_discovery(context),
        )
        latency["status"] = "failed"
        latency["error"] = str(e)[:200]
    finally:
        latency["finished_at"] = datetime.now().isoformat()
        latency["timings_ms"]["total_e2e_ms"] = _ms_since(req_started)
        await _write_latency_async(latency)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        await update.message.reply_text(
            "❌ Please send a TV series or movie title.",
            reply_markup=keyboard_discovery(context),
        )
        return

    raw = update.message.text.strip()
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

    phase_started = time.perf_counter()
    series_name, season, episode = _parse_series_input(raw)
    latency["phase_timings_ms"]["parse_input"] = _ms_since(phase_started)
    latency["identity"] = {
        "series_name": series_name,
        "season": season,
        "episode": episode,
    }
    status_msg = await update.message.reply_text(
        f"🔍 Processing request for: *{raw}*\n\n"
        "⏳ Looking for a saved word list or translations…",
        parse_mode="Markdown",
        reply_markup=keyboard_discovery(context),
    )

    # If simple parse likely failed (e.g. "ep 2 season 2" left in series name), ask ChatGPT
    if _simple_parse_likely_failed(raw, series_name, season, episode):
        await status_msg.edit_text(
            f"🔍 Processing request for: *{raw}*\n\n"
            "⏳ Normalizing with ChatGPT…",
            parse_mode="Markdown",
            reply_markup=keyboard_discovery(context),
        )
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
            await status_msg.edit_text(
                f"🔍 Processing: *{series_name}*{_tv_episode_suffix(series_name, season, episode)}\n\n"
                "⏳ Looking for a saved word list or translations…",
                parse_mode="Markdown",
                reply_markup=keyboard_discovery(context),
            )

    loop = asyncio.get_running_loop()
    timeout = 600.0

    try:
        # Step 1: look for existing tier list and translations
        phase_started = time.perf_counter()
        episode_dir, translations_dir, subtitle_path = await asyncio.wait_for(
            loop.run_in_executor(
                None,
                lambda: _find_existing(series_name, season, episode),
            ),
            timeout=timeout,
        )
        latency["phase_timings_ms"]["find_existing"] = _ms_since(phase_started)

        # Case A: translations already exist — send word list in chat
        if translations_dir is not None:
            latency["branch"] = "cache_hit_translations"
            await status_msg.edit_text(
                f"🔍 Processing: *{series_name}*{_tv_episode_suffix(series_name, season, episode)}\n"
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
            context.user_data["last_episode_dir"] = str(episode_dir) if episode_dir else ""
            context.user_data["last_series_name"] = series_name
            context.user_data["last_translations_dir"] = str(translations_dir)
            latency["status"] = "success"
            return

        # Case B: tier list exists but no translations — translate only
        if episode_dir is not None:
            latency["branch"] = "tier_exists_translate_only"
            await status_msg.edit_text(
                f"🔍 Processing: *{series_name}*{_tv_episode_suffix(series_name, season, episode)}\n"
                f"✅ Found existing hard words list.\n\n"
                "⏳ Translating words…",
                parse_mode="Markdown",
                reply_markup=keyboard_discovery(context),
            )
            if subtitle_path is None:
                # Try to get subtitle path from episode_info and download if missing
                await status_msg.edit_text(
                    f"🔍 Processing: *{series_name}*{_tv_episode_suffix(series_name, season, episode)}\n"
                    "⏳ Subtitle file missing, downloading…",
                    parse_mode="Markdown",
                    reply_markup=keyboard_discovery(context),
                )
                phase_started = time.perf_counter()
                subtitle_path = await asyncio.wait_for(
                    loop.run_in_executor(
                        None,
                        lambda: _do_download(series_name, season, episode),
                    ),
                    timeout=timeout,
                )
                latency["phase_timings_ms"]["download_subtitle"] = _ms_since(phase_started)
                if not subtitle_path:
                    await status_msg.edit_text(
                        f"❌ **Subtitle download failed** for *{series_name}*{_tv_episode_suffix(series_name, season, episode)}.\n\n"
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
                    lambda: _do_translate(episode_dir, subtitle_path),
                ),
                timeout=timeout,
            )
            latency["phase_timings_ms"]["translate"] = _ms_since(phase_started)
            latency["translator_metrics"] = translator_metrics
            if not ok or not out_dir:
                reason = (trans_err or "Translation failed.").strip()
                await status_msg.edit_text(
                    f"❌ **Translation failed.**\n\n{reason}\n\n💡 Use /next or **Next series** to try another title.",
                    parse_mode="Markdown",
                    reply_markup=keyboard_discovery(context),
                )
                latency["status"] = "failed"
                latency["error"] = reason
                return
            rel = out_dir.relative_to(BASE_DIR)
            await status_msg.edit_text(
                f"✅ *{series_name}*{_tv_episode_suffix(series_name, season, episode)}\n\n"
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
            context.user_data["last_episode_dir"] = str(episode_dir)
            context.user_data["last_series_name"] = series_name
            context.user_data["last_translations_dir"] = str(out_dir)
            latency["status"] = "success"
            return

        # Case C: nothing exists — download, analyze, translate
        latency["branch"] = "full_pipeline"
        await status_msg.edit_text(
            f"🔍 Processing: *{series_name}*{_tv_episode_suffix(series_name, season, episode)}\n\n"
            "⏳ Downloading subtitle…",
            parse_mode="Markdown",
            reply_markup=keyboard_discovery(context),
        )
        phase_started = time.perf_counter()
        subtitle_path = await asyncio.wait_for(
            loop.run_in_executor(
                None,
                lambda: _do_download(series_name, season, episode),
            ),
            timeout=timeout,
        )
        latency["phase_timings_ms"]["download_subtitle"] = _ms_since(phase_started)
        if not subtitle_path:
            await status_msg.edit_text(
                f"❌ **Subtitle download failed** for *{series_name}*{_tv_episode_suffix(series_name, season, episode)}.\n\n"
                "Possible causes: wrong series/episode name, or subtitle not on OpenSubtitles.",
                parse_mode="Markdown",
                reply_markup=keyboard_discovery(context),
            )
            latency["status"] = "failed"
            latency["error"] = "subtitle_download_failed"
            return

        await status_msg.edit_text(
            f"🔍 Processing: *{series_name}*{_tv_episode_suffix(series_name, season, episode)}\n"
            f"✅ Subtitle downloaded.\n\n"
            "⏳ Building the hard-word list from the subtitle…",
            parse_mode="Markdown",
            reply_markup=keyboard_discovery(context),
        )
        phase_started = time.perf_counter()
        episode_dir, analyze_metrics, subtitle_raw_handoff = await asyncio.wait_for(
            loop.run_in_executor(None, lambda: _do_analyze(subtitle_path)),
            timeout=timeout,
        )
        latency["phase_timings_ms"]["analyze_subtitle"] = _ms_since(phase_started)
        latency["analyze_metrics"] = analyze_metrics
        if not episode_dir:
            await status_msg.edit_text(
                "❌ **Hard-word list build failed** (could not read the subtitle).\n\n"
                "The file may be invalid or empty.",
                parse_mode="Markdown",
                reply_markup=keyboard_discovery(context),
            )
            latency["status"] = "failed"
            latency["error"] = "tier_list_build_failed"
            return

        await status_msg.edit_text(
            f"🔍 Processing: *{series_name}*{_tv_episode_suffix(series_name, season, episode)}\n"
            f"✅ C-level list ready.\n\n"
            "⏳ Translating words…",
            parse_mode="Markdown",
            reply_markup=keyboard_discovery(context),
        )
        phase_started = time.perf_counter()
        ok, out_dir, trans_err, translator_metrics = await asyncio.wait_for(
            loop.run_in_executor(
                None,
                lambda: _do_translate(
                    episode_dir, subtitle_path, subtitle_raw=subtitle_raw_handoff
                ),
            ),
            timeout=timeout,
        )
        latency["phase_timings_ms"]["translate"] = _ms_since(phase_started)
        latency["translator_metrics"] = translator_metrics
        if not ok or not out_dir:
            reason = (trans_err or "Translation failed.").strip()
            await status_msg.edit_text(
                f"❌ **Translation failed.**\n\n{reason}",
                parse_mode="Markdown",
                reply_markup=keyboard_discovery(context),
            )
            latency["status"] = "failed"
            latency["error"] = reason
            return

        rel = out_dir.relative_to(BASE_DIR)
        await status_msg.edit_text(
            f"✅ *{series_name}*{_tv_episode_suffix(series_name, season, episode)}\n\n"
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
        context.user_data["last_episode_dir"] = str(episode_dir)
        context.user_data["last_series_name"] = series_name
        context.user_data["last_translations_dir"] = str(out_dir)
        latency["status"] = "success"

    except asyncio.TimeoutError:
        await status_msg.edit_text(
            "❌ **Request timed out** (download/analysis/translation took too long).",
            parse_mode="Markdown",
            reply_markup=keyboard_discovery(context),
        )
        latency["status"] = "timeout"
        latency["error"] = "request_timeout"
    except Exception as e:
        await status_msg.edit_text(
            f"❌ **Error:** {str(e)[:150]}",
            parse_mode="Markdown",
            reply_markup=keyboard_discovery(context),
        )
        latency["status"] = "failed"
        latency["error"] = str(e)[:200]
    finally:
        latency["finished_at"] = datetime.now().isoformat()
        latency["timings_ms"]["total_e2e_ms"] = _ms_since(req_started)
        await _write_latency_async(latency)


def _load_translation_pairs_csv(csv_path: Path) -> List[Tuple[str, str]]:
    """Load word → translation_ru from a translations CSV. Skips empty / placeholder cells."""
    if not csv_path.exists():
        return []
    out: List[Tuple[str, str]] = []
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
                out.append((w, t))
    except Exception:
        pass
    return out


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
    b1: List[Tuple[str, str]],
    b2: List[Tuple[str, str]],
    *,
    is_movie: bool = False,
    year: int = 0,
    max_lines_per_band: int = 40,
) -> str:
    """Format a single B-level list; truncates with '… and N more'."""
    if is_movie:
        title = f"🎬 *{series_name}*" + (f" ({year})" if year else "")
    else:
        title = f"📺 *{series_name}*{_tv_episode_suffix(series_name, season, episode)}"
    merged: List[Tuple[str, str]] = []
    seen = set()
    for w, t in [*b1, *b2]:
        key = (w.strip().lower(), t.strip().lower())
        if key in seen:
            continue
        seen.add(key)
        merged.append((w, t))
    n = len(merged)
    header = f"📗 *B-level words* — {title}\n\n📊 *B-level words: {n}*\n\n"
    if not merged:
        return header + "_No words._"
    show = merged[:max_lines_per_band]
    lines = [f"{i}. *{w}* → {t}" for i, (w, t) in enumerate(show, 1)]
    body = "\n".join(lines)
    if n > max_lines_per_band:
        body += f"\n\n… and {n - max_lines_per_band} more."
    return header + body


def _format_word_list(
    series_name: str,
    season: int,
    episode: int,
    pairs: List[Tuple[str, str]],
    max_lines: int = 25,
    *,
    is_movie: bool = False,
    year: int = 0,
) -> str:
    """Format header + numbered word list. If pairs > max_lines, show first max_lines and '... and N more'."""
    n = len(pairs)
    if is_movie:
        header = f"🎬 *{series_name}*" + (f" ({year})" if year else "") + f"\n\n📊 *C-level words: {n}*\n\n"
    else:
        header = f"📺 *{series_name}*{_tv_episode_suffix(series_name, season, episode)}\n\n📊 *C-level words: {n}*\n\n"
    if not pairs:
        return header + "_No words._"
    show = pairs[:max_lines]
    lines = [f"{i}. *{w}* → {t}" for i, (w, t) in enumerate(show, 1)]
    body = "\n".join(lines)
    if n > max_lines:
        body += f"\n\n… and {n - max_lines} more words."
    return header + body


def _format_rare_in_series_full_list(
    series_name: str,
    season: int,
    episode: int,
    pairs: List[Tuple[str, str]],
    *,
    is_movie: bool = False,
    year: int = 0,
    band: str = "c",
) -> str:
    """Full numbered list for rare-in-series translations (C-level vs B-level band)."""
    n = len(pairs)
    label = "Rare in series (C1–C2)" if band == "c" else "Rare in series (B1–B2)"
    if is_movie:
        header = f"📋 *{label}* — *{series_name}*" + (f" ({year})" if year else "") + f"\n\n📊 *{n} words*\n\n"
    else:
        header = f"📋 *{label}* — *{series_name}*{_tv_episode_suffix(series_name, season, episode)}\n\n📊 *{n} words*\n\n"
    if not pairs:
        return header + "_No words._"
    lines = [f"{i}. *{w}* → {t}" for i, (w, t) in enumerate(pairs, 1)]
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
    pairs = _load_translations_list(translations_dir)
    latency_suffix = (
        f"\n⏱ *Latency:* {latency_ms / 1000:.2f}s"
        if isinstance(latency_ms, int) and latency_ms >= 0
        else ""
    )
    kb = keyboard_loaded(context)
    rel = f"`{translations_dir.relative_to(BASE_DIR)}/`"
    if not pairs:
        header = f"🎬 *{series_name}*" + (f" ({year})" if year else "") if is_movie else f"📺 *{series_name}*{_tv_episode_suffix(series_name, season, episode)}"
        body = f"{header}\n\n📁 Saved to: {rel}{latency_suffix}\n\n_No words in CSV._"
        if query:
            await query.edit_message_text(body, parse_mode="Markdown", reply_markup=kb)
        else:
            await update.message.reply_text(body, parse_mode="Markdown", reply_markup=kb)
        return
    text = _format_word_list(series_name, season, episode, pairs, is_movie=is_movie, year=year)
    if latency_suffix:
        text += f"\n\n{latency_suffix}"
    max_len = 4096
    if query:
        if len(text) <= max_len:
            await query.edit_message_text(text, parse_mode="Markdown", reply_markup=kb)
        else:
            parts = _split_message_chunks(text, max_len=max_len)
            await query.edit_message_text(parts[0], parse_mode="Markdown", reply_markup=kb)
            for part in parts[1:]:
                await query.message.reply_text(part, parse_mode="Markdown")
        return
    if len(text) <= max_len:
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=kb)
    else:
        parts = _split_message_chunks(text, max_len=max_len)
        for i, part in enumerate(parts):
            await update.message.reply_text(
                part, parse_mode="Markdown", reply_markup=kb if i == len(parts) - 1 else None
            )


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
        if query:
            await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=kbd)
        else:
            await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=kbd)
        return
    translations_dir = Path(last_dir).resolve()
    if not translations_dir.exists():
        msg = f"❌ Translations folder not found: `{_rel_path(last_dir)}/`"
        kbd = keyboard_discovery(context)
        if query:
            await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=kbd)
        else:
            await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=kbd)
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
) -> Optional[Path]:
    """Resolved .srt path for the loaded title, or None if missing."""
    from download_subtitles import get_movie_subtitle_path, get_subtitle_path

    if is_movie:
        p = get_movie_subtitle_path(SUBTITLE_BASE, series_name, year)
    else:
        p = get_subtitle_path(SUBTITLE_BASE, series_name, season, episode)
    return p if p.is_file() else None


async def send_rare_c_series_full_list(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    query=None,
) -> None:
    """Send full rare-in-series (C1–C2) list from tier_4_rare_c_translations.csv. /full"""
    last_dir = context.user_data.get("last_translations_dir")
    if not last_dir:
        msg = (
            "❌ No episode or movie loaded yet.\n\n"
            "Send a title first, then use /full or tap **Rare C**."
        )
        kb = keyboard_discovery(context)
        if query:
            await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=kb)
        else:
            await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=kb)
        return

    translations_dir = Path(last_dir).resolve()
    if not translations_dir.exists():
        msg = f"❌ Translations folder not found: `{_rel_path(last_dir)}/`"
        kb = keyboard_discovery(context)
        if query:
            await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=kb)
        else:
            await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=kb)
        return

    series_name, season, episode, is_movie, year = _get_translations_header(
        translations_dir, context
    )
    pairs = _load_translation_pairs_csv(translations_dir / TIER_4_RARE_C_TRANSLATIONS_CSV)
    if not pairs:
        from translate_tier_translations import (
            TIER_4_RARE_C_CSV,
            TIER_ID_TIER_4C,
            load_tier_words,
        )

        episode_dir_str = context.user_data.get("last_episode_dir")
        header = (
            f"🎬 *{series_name}*" + (f" ({year})" if year else "")
            if is_movie
            else f"📺 *{series_name}*{_tv_episode_suffix(series_name, season, episode)}"
        )
        kb_loaded = keyboard_loaded(context)

        if not episode_dir_str:
            msg = (
                f"{header}\n\n📁 `{_rel_path(last_dir)}/`\n\n"
                "_Could not locate the tier list folder to translate rare words._ "
                "Send the episode title again, then tap **Rare C**."
            )
            if query:
                await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=kb_loaded)
            else:
                await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=kb_loaded)
            return

        episode_dir = Path(episode_dir_str).resolve()
        if not load_tier_words(episode_dir, TIER_4_RARE_C_CSV):
            msg = (
                f"{header}\n\n📁 `{_rel_path(last_dir)}/`\n\n"
                "_No rare-in-series (C1–C2) words in this episode’s tier list._ "
                "Re-run analysis if you expect `tier_4_rare_c_words.csv` to be non-empty."
            )
            if query:
                await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=kb_loaded)
            else:
                await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=kb_loaded)
            return

        progress = "⏳ Translating rare-in-series (C1–C2) list…"
        if query:
            await query.edit_message_text(
                progress, parse_mode="Markdown", reply_markup=kb_loaded
            )
        else:
            await update.message.reply_text(
                progress, parse_mode="Markdown", reply_markup=kb_loaded
            )

        sp = _subtitle_path_for_loaded_title(
            series_name, season, episode, is_movie=is_movie, year=year
        )
        loop = asyncio.get_running_loop()
        timeout = 600.0
        try:
            ok, _out_dir, trans_err, _metrics = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda ed=episode_dir, p=sp: _do_translate(
                        ed, p, tier_ids=frozenset({TIER_ID_TIER_4C})
                    ),
                ),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            msg = (
                f"{header}\n\n❌ **Timed out** translating the rare-in-series (C) list.\n\n"
                "Try **Rare C** again."
            )
            if query:
                await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=kb_loaded)
            else:
                await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=kb_loaded)
            return

        if not ok:
            reason = (trans_err or "Translation failed.").strip()
            msg = f"{header}\n\n❌ **Rare list translation failed.**\n\n{reason}"
            if query:
                await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=kb_loaded)
            else:
                await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=kb_loaded)
            return

        pairs = _load_translation_pairs_csv(
            translations_dir / TIER_4_RARE_C_TRANSLATIONS_CSV
        )
        if not pairs:
            msg = (
                f"{header}\n\n📁 `{_rel_path(last_dir)}/`\n\n"
                "_Rare list translation produced no usable rows._"
            )
            if query:
                await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=kb_loaded)
            else:
                await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=kb_loaded)
            return

    full_text = _format_rare_in_series_full_list(
        series_name, season, episode, pairs, is_movie=is_movie, year=year, band="c"
    )
    chunks = _split_message_chunks(full_text)
    kb = keyboard_loaded(context)

    if query:
        await query.edit_message_text(chunks[0], parse_mode="Markdown", reply_markup=kb)
        for part in chunks[1:]:
            await query.message.reply_text(part, parse_mode="Markdown")
    else:
        for i, part in enumerate(chunks):
            await update.message.reply_text(
                part, parse_mode="Markdown",
                reply_markup=kb if i == len(chunks) - 1 else None,
            )


async def send_rare_b_series_full_list(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    query=None,
) -> None:
    """Send full rare-in-series (B-level) list from tier_4_rare_b_translations.csv."""
    last_dir = context.user_data.get("last_translations_dir")
    if not last_dir:
        msg = (
            "❌ No episode or movie loaded yet.\n\n"
            "Send a title first, then tap **Rare B**."
        )
        kb = keyboard_discovery(context)
        if query:
            await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=kb)
        else:
            await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=kb)
        return

    translations_dir = Path(last_dir).resolve()
    if not translations_dir.exists():
        msg = f"❌ Translations folder not found: `{_rel_path(last_dir)}/`"
        kb = keyboard_discovery(context)
        if query:
            await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=kb)
        else:
            await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=kb)
        return

    series_name, season, episode, is_movie, year = _get_translations_header(
        translations_dir, context
    )
    pairs = _load_translation_pairs_csv(translations_dir / TIER_4_RARE_B_TRANSLATIONS_CSV)
    if not pairs:
        from translate_tier_translations import (
            TIER_4_RARE_B_CSV,
            TIER_ID_TIER_4B,
            load_tier_words,
        )

        episode_dir_str = context.user_data.get("last_episode_dir")
        header = (
            f"🎬 *{series_name}*" + (f" ({year})" if year else "")
            if is_movie
            else f"📺 *{series_name}*{_tv_episode_suffix(series_name, season, episode)}"
        )
        kb_loaded = keyboard_loaded(context)

        if not episode_dir_str:
            msg = (
                f"{header}\n\n📁 `{_rel_path(last_dir)}/`\n\n"
                "_Could not locate the tier list folder to translate rare words._ "
                "Send the episode title again, then tap **Rare B**."
            )
            if query:
                await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=kb_loaded)
            else:
                await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=kb_loaded)
            return

        episode_dir = Path(episode_dir_str).resolve()
        if not load_tier_words(episode_dir, TIER_4_RARE_B_CSV):
            msg = (
                f"{header}\n\n📁 `{_rel_path(last_dir)}/`\n\n"
                "_No rare-in-series (B) words in this episode’s tier list._"
            )
            if query:
                await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=kb_loaded)
            else:
                await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=kb_loaded)
            return

        progress = "⏳ Translating rare-in-series (B) list…"
        if query:
            await query.edit_message_text(
                progress, parse_mode="Markdown", reply_markup=kb_loaded
            )
        else:
            await update.message.reply_text(
                progress, parse_mode="Markdown", reply_markup=kb_loaded
            )

        sp = _subtitle_path_for_loaded_title(
            series_name, season, episode, is_movie=is_movie, year=year
        )
        loop = asyncio.get_running_loop()
        timeout = 600.0
        try:
            ok, _out_dir, trans_err, _metrics = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda ed=episode_dir, p=sp: _do_translate(
                        ed, p, tier_ids=frozenset({TIER_ID_TIER_4B})
                    ),
                ),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            msg = (
                f"{header}\n\n❌ **Timed out** translating the rare-in-series (B) list.\n\n"
                "Try **Rare B** again."
            )
            if query:
                await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=kb_loaded)
            else:
                await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=kb_loaded)
            return

        if not ok:
            reason = (trans_err or "Translation failed.").strip()
            msg = f"{header}\n\n❌ **Rare list translation failed.**\n\n{reason}"
            if query:
                await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=kb_loaded)
            else:
                await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=kb_loaded)
            return

        pairs = _load_translation_pairs_csv(
            translations_dir / TIER_4_RARE_B_TRANSLATIONS_CSV
        )
        if not pairs:
            msg = (
                f"{header}\n\n📁 `{_rel_path(last_dir)}/`\n\n"
                "_Rare list translation produced no usable rows._"
            )
            if query:
                await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=kb_loaded)
            else:
                await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=kb_loaded)
            return

    full_text = _format_rare_in_series_full_list(
        series_name, season, episode, pairs, is_movie=is_movie, year=year, band="b"
    )
    chunks = _split_message_chunks(full_text)
    kb = keyboard_loaded(context)

    if query:
        await query.edit_message_text(chunks[0], parse_mode="Markdown", reply_markup=kb)
        for part in chunks[1:]:
            await query.message.reply_text(part, parse_mode="Markdown")
    else:
        for i, part in enumerate(chunks):
            await update.message.reply_text(
                part, parse_mode="Markdown",
                reply_markup=kb if i == len(chunks) - 1 else None,
            )


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
        if query:
            await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=kb)
        else:
            await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=kb)
        return

    translations_dir = Path(last_dir).resolve()
    if not translations_dir.exists():
        msg = f"❌ Translations folder not found: `{_rel_path(last_dir)}/`"
        kb = keyboard_discovery(context)
        if query:
            await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=kb)
        else:
            await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=kb)
        return

    b1, b2 = _load_b_level_pairs(translations_dir)
    series_name, season, episode, is_movie, year = _get_translations_header(
        translations_dir, context
    )
    kb = keyboard_loaded(context)

    if not b1 and not b2:
        hint = (
            "\n\n_If this title has B-level words in tier output, re-run translation "
            "to generate the B-level translation file._"
        )
        title = (
            f"🎬 *{series_name}*" + (f" ({year})" if year else "")
            if is_movie
            else f"📺 *{series_name}*{_tv_episode_suffix(series_name, season, episode)}"
        )
        msg = f"📗 *B-level words* — {title}\n\n_No B-level translations in this folder yet._{hint}"
        if query:
            await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=kb)
        else:
            await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=kb)
        return

    full_text = _format_b_level_list(
        series_name, season, episode, b1, b2, is_movie=is_movie, year=year
    )
    chunks = _split_message_chunks(full_text)

    if query:
        await query.edit_message_text(chunks[0], parse_mode="Markdown", reply_markup=kb)
        for part in chunks[1:]:
            await query.message.reply_text(part, parse_mode="Markdown")
    else:
        for i, part in enumerate(chunks):
            await update.message.reply_text(
                part,
                parse_mode="Markdown",
                reply_markup=kb if i == len(chunks) - 1 else None,
            )


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


def _load_phrasal_rows(translations_dir: Path) -> List[Tuple[str, str, str, str]]:
    """Rows: phrasal_verb, frequency, translation, example (supports legacy 'verb' column)."""
    path = translations_dir / PHRASAL_VERBS_CSV
    rows: List[Tuple[str, str, str, str]] = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            pv = (row.get("phrasal_verb") or row.get("verb") or "").strip()
            if not pv:
                continue
            rows.append(
                (
                    pv,
                    (row.get("frequency") or "").strip(),
                    (row.get("translation") or "").strip(),
                    (row.get("example") or "").strip(),
                )
            )
    return rows


def _format_phrasal_list(
    series_name: str,
    season: int,
    episode: int,
    rows: List[Tuple[str, str, str, str]],
    *,
    is_movie: bool = False,
    year: int = 0,
    full_total: Optional[int] = None,
) -> str:
    """Format phrasal list. If ``full_total`` is set and greater than ``len(rows)``, label as a preview."""
    shown = len(rows)
    if is_movie:
        title = (
            f"🔤 *Phrasal verbs* — 🎬 *{series_name}*"
            + (f" ({year})" if year else "")
        )
    else:
        title = (
            f"🔤 *Phrasal verbs* — 📺 *{series_name}*"
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
    for i, (pv, _freq, tr, ex) in enumerate(rows, 1):
        disp = tr if tr else "N/A"
        line = f"{i}. *{pv}* → {disp}"
        if ex and ex not in ("N/A", ""):
            short = ex[:180] + ("…" if len(ex) > 180 else "")
            line += f"\n   _{short}_"
        lines.append(line)
    return header + "\n".join(lines)


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
    kb_after = keyboard_loaded(context)

    if not last_dir:
        msg = (
            "❌ No episode or movie loaded yet.\n\n"
            "Send a title first, then tap **Phrasal verbs** or use /phrasal."
        )
        if query:
            await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=kb_empty)
        else:
            await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=kb_empty)
        return

    translations_dir = Path(last_dir).resolve()
    if not translations_dir.exists():
        msg = f"❌ Translations folder not found: `{_rel_path(last_dir)}/`"
        if query:
            await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=kb_empty)
        else:
            await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=kb_empty)
        return

    series_name, season, episode, is_movie, year = _get_translations_header(
        translations_dir, context
    )
    csv_path = translations_dir / PHRASAL_VERBS_CSV
    loop = asyncio.get_running_loop()
    status_message = None

    if not csv_path.exists():
        if not OPENAI_API_KEY.strip():
            msg = (
                "❌ *OPENAI_API_KEY* is not set.\n\n"
                "Set it to extract and translate phrasal verbs."
            )
            if query:
                await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=kb_after)
            else:
                await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=kb_after)
            return

        subtitle_path = _resolve_subtitle_for_phrasal(translations_dir, context)
        if not subtitle_path:
            msg = (
                "❌ Could not find the subtitle file for this title.\n\n"
                "Ensure subtitles exist under `Subtitle/` for this episode or movie."
            )
            if query:
                await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=kb_after)
            else:
                await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=kb_after)
            return

        sn = _series_name_for_phrasal(translations_dir, context)
        loading = "🔤 *Phrasal verbs*\n\n⏳ Extracting and translating…"
        if query:
            await query.edit_message_text(
                loading, parse_mode="Markdown", reply_markup=kb_after
            )
        else:
            status_message = await update.message.reply_text(
                loading, parse_mode="Markdown", reply_markup=kb_after
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
            if query:
                await query.edit_message_text(err, parse_mode="Markdown", reply_markup=kb_after)
            else:
                if status_message is not None:
                    await status_message.edit_text(
                        err, parse_mode="Markdown", reply_markup=kb_after
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
        kb = keyboard_loaded(context)
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
        kb = keyboard_loaded(context, extra_phrasal_count=total_n)

    chunks = _split_message_chunks(full_text)

    if query:
        await query.edit_message_text(chunks[0], parse_mode="Markdown", reply_markup=kb)
        for part in chunks[1:]:
            await query.message.reply_text(part, parse_mode="Markdown")
    else:
        if status_message is not None:
            await status_message.edit_text(chunks[0], parse_mode="Markdown", reply_markup=kb)
            for part in chunks[1:]:
                await update.message.reply_text(part, parse_mode="Markdown")
        else:
            for i, part in enumerate(chunks):
                await update.message.reply_text(
                    part,
                    parse_mode="Markdown",
                    reply_markup=kb if i == len(chunks) - 1 else None,
                )


# Registered in main() as /phrasal; keep name so main() stays unchanged.
send_phrasal_placeholder = send_phrasal_verbs


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

    if data == "frequent_c_words":
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
    elif data == "next_series":
        await next_series(wrapped, context)
    elif data == "next_movie":
        await next_movie(wrapped, context)
    else:
        await query.edit_message_text(
            "Unknown action.",
            reply_markup=keyboard_discovery(context),
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
        print("Set TELEGRAM_BOT_TOKEN or add token in code.")
        return
    BOT_BUILD_DATETIME = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"Bot build (start) time: {BOT_BUILD_DATETIME}", flush=True)
    print("Bot running. Real output: hard-word translations saved under translations/", flush=True)
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("next", next_series))
    app.add_handler(CommandHandler("movie", next_movie))
    app.add_handler(CommandHandler("full", send_full_list))
    app.add_handler(CommandHandler("phrasal", send_phrasal_placeholder))
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
