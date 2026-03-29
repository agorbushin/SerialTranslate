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
from typing import Any, Dict, List, Optional, Tuple

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
LATENCY_METRICS_BASE = BASE_DIR / "latency_metrics"


def _ms_since(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


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


def _cmd_keyboard() -> "InlineKeyboardMarkup":
    """Inline actions: pick TV vs movie, then full list or phrasals (when available)."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📺 TV series", callback_data="next_series"),
            InlineKeyboardButton("🎬 Movie", callback_data="next_movie"),
        ],
        [
            InlineKeyboardButton("📋 Full word list", callback_data="full_list"),
            InlineKeyboardButton("🔤 Phrasal verbs", callback_data="phrasal_verbs"),
        ],
    ])


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
    build = BOT_BUILD_DATETIME or "unknown"
    await update.message.reply_text(
        "👋 Welcome to **SerialTranslate**.\n\n"
        "**What you get:** harder English words that show up *often* in a specific TV episode or "
        "movie — with Russian glosses, built from real subtitles.\n\n"
        "**What to do:** tap **TV series** or **Movie**, then send the title (add season/episode "
        "for a show).\n\n"
        "Examples: _Fallout s2 e3_, _Inception_, _The Matrix 1999_.\n\n"
        f"_v{BOT_VERSION} · {build}_",
        parse_mode="Markdown",
        reply_markup=_cmd_keyboard(),
    )


async def next_series(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data["mode"] = "series"
    await update.message.reply_text(
        "📺 **Which TV series?**\n\n"
        "Send the show name and, if you want a specific episode, season/episode "
        "(e.g. _Fallout_, _Game of Thrones s2 e3_).",
        parse_mode="Markdown",
        reply_markup=_cmd_keyboard(),
    )


async def next_movie(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data["mode"] = "movie"
    await update.message.reply_text(
        "🎬 **Which movie?**\n\n"
        "Send the title (optional year helps), e.g. _Inception_, _The Matrix 1999_, _Dune (2021)_.",
        parse_mode="Markdown",
        reply_markup=_cmd_keyboard(),
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


def _do_analyze(subtitle_path: Path) -> Tuple[Optional[Path], Dict[str, int]]:
    """Run tier pipeline for series. Returns (episode_dir_or_none, analyze_metrics)."""
    from subtitle_analyzer import run_pipeline

    analyze_metrics: Dict[str, int] = {}
    episode_dir = run_pipeline(
        subtitle_path=subtitle_path,
        base_dir=BASE_DIR,
        tierlist_base_dir=TIERLIST_BASE,
        max_english_freq=20_000_000,
        openai_api_key=OPENAI_API_KEY or None,
        metrics_out=analyze_metrics,
    )
    if not episode_dir or not (episode_dir / "tier_1_hard_usable_words.csv").exists():
        return None, analyze_metrics
    return episode_dir, analyze_metrics


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
) -> Tuple[Optional[Path], Dict[str, int]]:
    """Run tier pipeline for movie. Returns (episode_dir_or_none, analyze_metrics)."""
    from subtitle_analyzer import run_pipeline

    analyze_metrics: Dict[str, int] = {}
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
    )
    if not episode_dir or not (episode_dir / "tier_1_hard_usable_words.csv").exists():
        return None, analyze_metrics
    return episode_dir, analyze_metrics


def _do_translate(
    episode_dir: Path, subtitle_path: Optional[Path]
) -> Tuple[bool, Optional[Path], Optional[str], Optional[Dict[str, Any]]]:
    """Translate tier 1 and save to translations/. Returns (success, out_dir, error_reason, metrics)."""
    from download_subtitles import get_translations_episode_dir, get_translations_movie_dir
    from translate_tier_translations import run as run_translate

    metrics: Dict[str, Any] = {}
    ok, err = run_translate(
        episode_dir=episode_dir,
        subtitle_path=subtitle_path,
        api_key=OPENAI_API_KEY or None,
        translations_base=TRANSLATIONS_BASE,
        subtitle_base=SUBTITLE_BASE,
        metrics_out=metrics,
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
            )
            await _send_translations_list(
                update, translations_dir, movie_name, 0, 0,
                is_movie=True, year=year,
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
            )
            if subtitle_path is None:
                await status_msg.edit_text(
                    f"🎬 Processing: {label}\n"
                    "⏳ Subtitle file missing, downloading…",
                    parse_mode="Markdown",
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
                        reply_markup=_cmd_keyboard(),
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
                    reply_markup=_cmd_keyboard(),
                )
                latency["status"] = "failed"
                latency["error"] = reason
                return
            rel = out_dir.relative_to(BASE_DIR)
            await status_msg.edit_text(
                f"✅ {label}\n\n"
                f"📁 Hard words translated and saved to: `{rel}/`",
                parse_mode="Markdown",
            )
            await _send_translations_list(
                update, out_dir, movie_name, 0, 0,
                is_movie=True, year=year,
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
                reply_markup=_cmd_keyboard(),
            )
            latency["status"] = "failed"
            latency["error"] = "subtitle_download_failed"
            return

        await status_msg.edit_text(
            f"🎬 Processing: {label}\n"
            f"✅ Subtitle downloaded.\n\n"
            "⏳ Building the hard-word list from the subtitle…",
            parse_mode="Markdown",
        )
        phase_started = time.perf_counter()
        episode_dir, analyze_metrics = await asyncio.wait_for(
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
                reply_markup=_cmd_keyboard(),
            )
            latency["status"] = "failed"
            latency["error"] = "tier_list_build_failed"
            return

        await status_msg.edit_text(
            f"🎬 Processing: {label}\n"
            f"✅ Hard words list ready.\n\n"
            "⏳ Translating words…",
            parse_mode="Markdown",
        )
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
                reply_markup=_cmd_keyboard(),
            )
            latency["status"] = "failed"
            latency["error"] = reason
            return

        rel = out_dir.relative_to(BASE_DIR)
        await status_msg.edit_text(
            f"✅ {label}\n\n"
            f"📁 Hard words translated and saved to: `{rel}/`",
            parse_mode="Markdown",
            reply_markup=_cmd_keyboard(),
        )
        await _send_translations_list(
            update, out_dir, movie_name, 0, 0,
            is_movie=True, year=year,
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
            reply_markup=_cmd_keyboard(),
        )
        latency["status"] = "timeout"
        latency["error"] = "request_timeout"
    except Exception as e:
        await status_msg.edit_text(
            f"❌ **Error:** {str(e)[:150]}",
            parse_mode="Markdown",
            reply_markup=_cmd_keyboard(),
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
            reply_markup=_cmd_keyboard(),
        )
        return

    raw = update.message.text.strip()
    req_started = time.perf_counter()
    latency = _new_latency(raw, "series")
    if len(raw) < 2:
        await update.message.reply_text(
            "❌ Name too short. Try e.g. _Fallout_, _Inception_, _Game of Thrones_.",
            parse_mode="Markdown",
            reply_markup=_cmd_keyboard(),
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
    )

    # If simple parse likely failed (e.g. "ep 2 season 2" left in series name), ask ChatGPT
    if _simple_parse_likely_failed(raw, series_name, season, episode):
        await status_msg.edit_text(
            f"🔍 Processing request for: *{raw}*\n\n"
            "⏳ Normalizing with ChatGPT…",
            parse_mode="Markdown",
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
                f"🔍 Processing: *{series_name}* S{season}E{episode}\n\n"
                "⏳ Looking for a saved word list or translations…",
                parse_mode="Markdown",
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
                f"🔍 Processing: *{series_name}* S{season}E{episode}\n"
                f"✅ Found existing translations.\n\n"
                f"📁 Saved to: `{translations_dir.relative_to(BASE_DIR)}/`",
                parse_mode="Markdown",
            )
            await _send_translations_list(
                update,
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
                f"🔍 Processing: *{series_name}* S{season}E{episode}\n"
                f"✅ Found existing hard words list.\n\n"
                "⏳ Translating words…",
                parse_mode="Markdown",
            )
            if subtitle_path is None:
                # Try to get subtitle path from episode_info and download if missing
                await status_msg.edit_text(
                    f"🔍 Processing: *{series_name}* S{season}E{episode}\n"
                    "⏳ Subtitle file missing, downloading…",
                    parse_mode="Markdown",
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
                        f"❌ **Subtitle download failed** for *{series_name}* S{season}E{episode}.\n\n"
                        "Possible causes: wrong series/episode name, or subtitle not on OpenSubtitles.",
                        parse_mode="Markdown",
                        reply_markup=_cmd_keyboard(),
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
                    f"❌ **Translation failed.**\n\n{reason}\n\n💡 Use /next or **TV series** to try another title.",
                    parse_mode="Markdown",
                )
                latency["status"] = "failed"
                latency["error"] = reason
                return
            rel = out_dir.relative_to(BASE_DIR)
            await status_msg.edit_text(
                f"✅ *{series_name}* S{season}E{episode}\n\n"
                f"📁 Hard words translated and saved to: `{rel}/`",
                parse_mode="Markdown",
            )
            await _send_translations_list(
                update,
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
            f"🔍 Processing: *{series_name}* S{season}E{episode}\n\n"
            "⏳ Downloading subtitle…",
            parse_mode="Markdown",
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
                f"❌ **Subtitle download failed** for *{series_name}* S{season}E{episode}.\n\n"
                "Possible causes: wrong series/episode name, or subtitle not on OpenSubtitles.",
                parse_mode="Markdown",
                reply_markup=_cmd_keyboard(),
            )
            latency["status"] = "failed"
            latency["error"] = "subtitle_download_failed"
            return

        await status_msg.edit_text(
            f"🔍 Processing: *{series_name}* S{season}E{episode}\n"
            f"✅ Subtitle downloaded.\n\n"
            "⏳ Building the hard-word list from the subtitle…",
            parse_mode="Markdown",
        )
        phase_started = time.perf_counter()
        episode_dir, analyze_metrics = await asyncio.wait_for(
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
                reply_markup=_cmd_keyboard(),
            )
            latency["status"] = "failed"
            latency["error"] = "tier_list_build_failed"
            return

        await status_msg.edit_text(
            f"🔍 Processing: *{series_name}* S{season}E{episode}\n"
            f"✅ Hard words list ready.\n\n"
            "⏳ Translating words…",
            parse_mode="Markdown",
        )
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
                reply_markup=_cmd_keyboard(),
            )
            latency["status"] = "failed"
            latency["error"] = reason
            return

        rel = out_dir.relative_to(BASE_DIR)
        await status_msg.edit_text(
            f"✅ *{series_name}* S{season}E{episode}\n\n"
            f"📁 Hard words translated and saved to: `{rel}/`",
            parse_mode="Markdown",
            reply_markup=_cmd_keyboard(),
        )
        await _send_translations_list(
            update,
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
            reply_markup=_cmd_keyboard(),
        )
        latency["status"] = "timeout"
        latency["error"] = "request_timeout"
    except Exception as e:
        await status_msg.edit_text(
            f"❌ **Error:** {str(e)[:150]}",
            parse_mode="Markdown",
            reply_markup=_cmd_keyboard(),
        )
        latency["status"] = "failed"
        latency["error"] = str(e)[:200]
    finally:
        latency["finished_at"] = datetime.now().isoformat()
        latency["timings_ms"]["total_e2e_ms"] = _ms_since(req_started)
        await _write_latency_async(latency)


def _load_translations_list(translations_dir: Path) -> List[Tuple[str, str]]:
    """Load word → translation from tier_1_translations.csv. Returns [(word, translation_ru), ...].
    Excludes words with empty or placeholder translations (—, N/A, [Translation failed])."""
    path = translations_dir / "tier_1_translations.csv"
    if not path.exists():
        return []
    out = []
    empty_values = {"", "—", "n/a", "na", "[translation failed]"}
    try:
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                w = (row.get("word") or "").strip()
                t = (row.get("translation_ru") or "").strip()
                if not w:
                    continue
                t_lower = t.lower()
                if t_lower in empty_values or not t:
                    continue  # Skip words with empty translation
                out.append((w, t))
    except Exception:
        pass
    return out


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
        header = f"🎬 *{series_name}*" + (f" ({year})" if year else "") + f"\n\n📊 *Hard words: {n}*\n\n"
    else:
        header = f"📺 *{series_name}* S{season}E{episode}\n\n📊 *Hard words: {n}*\n\n"
    if not pairs:
        return header + "_No words._"
    show = pairs[:max_lines]
    lines = [f"{i}. *{w}* → {t}" for i, (w, t) in enumerate(show, 1)]
    body = "\n".join(lines)
    if n > max_lines:
        body += f"\n\n… and {n - max_lines} more words."
    return header + body


def _format_full_list(
    series_name: str,
    season: int,
    episode: int,
    pairs: List[Tuple[str, str]],
    *,
    is_movie: bool = False,
    year: int = 0,
) -> str:
    """Format header + full numbered word list (all pairs)."""
    n = len(pairs)
    if is_movie:
        header = f"📋 *Full list* — *{series_name}*" + (f" ({year})" if year else "") + f"\n\n📊 *{n} words*\n\n"
    else:
        header = f"📋 *Full list* — *{series_name}* S{season}E{episode}\n\n📊 *{n} words*\n\n"
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
    translations_dir: Path,
    series_name: str,
    season: int,
    episode: int,
    *,
    is_movie: bool = False,
    year: int = 0,
    latency_ms: Optional[int] = None,
) -> None:
    """Load translations from CSV and send word list in chat (chunked if >4096 chars)."""
    pairs = _load_translations_list(translations_dir)
    latency_suffix = (
        f"\n⏱ *Latency:* {latency_ms / 1000:.2f}s"
        if isinstance(latency_ms, int) and latency_ms >= 0
        else ""
    )
    if not pairs:
        header = f"🎬 *{series_name}*" + (f" ({year})" if year else "") if is_movie else f"📺 *{series_name}* S{season}E{episode}"
        await update.message.reply_text(
            f"{header}\n\n📁 Saved to: `{translations_dir.relative_to(BASE_DIR)}/`{latency_suffix}\n\n_No words in CSV._",
            parse_mode="Markdown",
            reply_markup=_cmd_keyboard(),
        )
        return
    text = _format_word_list(series_name, season, episode, pairs, is_movie=is_movie, year=year)
    if latency_suffix:
        text += f"\n\n{latency_suffix}"
    max_len = 4096
    kb = _cmd_keyboard()
    if len(text) <= max_len:
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=kb)
    else:
        parts = _split_message_chunks(text, max_len=max_len)
        for i, part in enumerate(parts):
            await update.message.reply_text(
                part, parse_mode="Markdown", reply_markup=kb if i == len(parts) - 1 else None
            )


def _rel_path(path_str: str) -> str:
    try:
        p = Path(path_str).resolve()
        return str(p.relative_to(BASE_DIR.resolve()))
    except (ValueError, TypeError):
        return path_str


async def send_full_list(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    query=None,
) -> None:
    """Send full list of words from last translations. Use query= when invoked from inline button."""
    last_dir = context.user_data.get("last_translations_dir")
    if not last_dir:
        msg = (
            "❌ No episode or movie loaded yet.\n\n"
            "Send a title first (e.g. _Game of Thrones s2 e3_, _Inception_), then use /full or **Full word list**."
        )
        kb = _cmd_keyboard()
        if query:
            await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=kb)
        else:
            await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=kb)
        return

    translations_dir = Path(last_dir).resolve()
    if not translations_dir.exists():
        msg = f"❌ Translations folder not found: `{_rel_path(last_dir)}/`"
        kb = _cmd_keyboard()
        if query:
            await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=kb)
        else:
            await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=kb)
        return

    pairs = _load_translations_list(translations_dir)
    series_name, season, episode, is_movie, year = _get_translations_header(translations_dir, context)
    if not pairs:
        header = f"🎬 *{series_name}*" + (f" ({year})" if year else "") if is_movie else f"📺 *{series_name}* S{season}E{episode}"
        msg = f"{header}\n\n📁 `{_rel_path(last_dir)}/`\n\n_No words in CSV._"
        kb = _cmd_keyboard()
        if query:
            await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=kb)
        else:
            await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=kb)
        return

    full_text = _format_full_list(series_name, season, episode, pairs, is_movie=is_movie, year=year)
    chunks = _split_message_chunks(full_text)
    kb = _cmd_keyboard()

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


async def send_phrasal_placeholder(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    last_dir = context.user_data.get("last_translations_dir")
    kb = _cmd_keyboard()
    if last_dir:
        await update.message.reply_text(
            "🔤 Phrasal verbs: *coming soon.*\n\n"
            f"Last word list: `{_rel_path(last_dir)}/`",
            parse_mode="Markdown",
            reply_markup=kb,
        )
    else:
        await update.message.reply_text(
            "❌ No title loaded yet.\n\n"
            "Send a TV series or movie first, then tap **Phrasal verbs** or use /phrasal.",
            parse_mode="Markdown",
            reply_markup=kb,
        )


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

    if data == "full_list":
        await send_full_list(wrapped, context, query=query)
    elif data == "phrasal_verbs":
        await send_phrasal_placeholder(wrapped, context)
    elif data == "rare_hard_words":
        await query.edit_message_text(
            "📊 Rare hard words in this title: *coming soon.*",
            parse_mode="Markdown",
            reply_markup=_cmd_keyboard(),
        )
    elif data == "hard_words_frequent":
        await query.edit_message_text(
            "📊 Frequent hard words (this title): *coming soon.*",
            parse_mode="Markdown",
            reply_markup=_cmd_keyboard(),
        )
    elif data == "next_series":
        await next_series(wrapped, context)
    elif data == "next_movie":
        await next_movie(wrapped, context)
    else:
        await query.edit_message_text(
            "Unknown action.",
            reply_markup=_cmd_keyboard(),
        )


async def handle_document_placeholder(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "📥 Subtitle file upload: *coming soon.*\n\n"
        "For now, send a TV series or movie title (e.g. _Game of Thrones s2 e3_) to build a word list.",
        parse_mode="Markdown",
        reply_markup=_cmd_keyboard(),
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
