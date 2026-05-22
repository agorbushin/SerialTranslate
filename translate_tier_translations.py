#!/usr/bin/env python3
"""
Translate tier words to Russian using ChatGPT (subtitle context, one word per request).

Reads tier_1_hard_usable_words.csv, tier_b1_words.csv, tier_b2_words.csv,
tier_4_rare_c_words.csv, tier_4_rare_b_words.csv when present.
Writes matching *_translations.csv files.

``run(tier_ids=...)`` limits which bands are translated in one invocation (CLI default:
all tiers that have words). The Telegram bot translates frequent tiers first and rare
tiers on user request.
"""

import csv
import json
import re
import os
import asyncio
import time
from pathlib import Path
from typing import List, Dict, Optional, Any, Tuple, Collection, FrozenSet
import argparse

# Internal tier keys used by run(tier_ids=...). CLI uses tier_ids=None (all tiers that have words).
TIER_ID_TIER_1 = "tier_1"
TIER_ID_B1 = "b1"
TIER_ID_B2 = "b2"
TIER_ID_TIER_4C = "tier_4c"
TIER_ID_TIER_4B = "tier_4b"

ALL_TRANSLATION_TIER_IDS: FrozenSet[str] = frozenset(
    {TIER_ID_TIER_1, TIER_ID_B1, TIER_ID_B2, TIER_ID_TIER_4C, TIER_ID_TIER_4B}
)
# Bot first pass: Frequent C + Frequent B; rare-in-series tiers translate on demand.
FREQUENT_TRANSLATION_TIER_IDS: FrozenSet[str] = frozenset(
    {TIER_ID_TIER_1, TIER_ID_B1, TIER_ID_B2}
)

from subtitle_text_utils import (
    extract_word_examples_from_srt_content,
    get_subtitle_text_from_content,
)

BATCH_SIZE = 1
MAX_CONCURRENT_BATCHES = 5
SUBTITLE_CONTEXT_CHARS = 6000
TRANSLATIONS_BASE_DIR = Path("translations")
SUBTITLE_BASE_DIR = Path("Subtitle")
TIER_1_CSV = "tier_1_hard_usable_words.csv"
TIER_B1_CSV = "tier_b1_words.csv"
TIER_B2_CSV = "tier_b2_words.csv"
TIER_4_RARE_C_CSV = "tier_4_rare_c_words.csv"
TIER_4_RARE_B_CSV = "tier_4_rare_b_words.csv"
TIER_1_TRANSLATIONS_CSV = "tier_1_translations.csv"
TIER_B1_TRANSLATIONS_CSV = "tier_b1_translations.csv"
TIER_B2_TRANSLATIONS_CSV = "tier_b2_translations.csv"
TIER_4_RARE_C_TRANSLATIONS_CSV = "tier_4_rare_c_translations.csv"
TIER_4_RARE_B_TRANSLATIONS_CSV = "tier_4_rare_b_translations.csv"
EPISODE_INFO_JSON = "episode_info.json"

TRANSLATION_OUTPUT_CSVS: Tuple[str, ...] = (
    TIER_1_TRANSLATIONS_CSV,
    TIER_B1_TRANSLATIONS_CSV,
    TIER_B2_TRANSLATIONS_CSV,
    TIER_4_RARE_C_TRANSLATIONS_CSV,
    TIER_4_RARE_B_TRANSLATIONS_CSV,
)


def translation_csv_files_present(translations_dir: Path) -> List[str]:
    """Basenames of known translation CSVs that exist under translations_dir."""
    out: List[str] = []
    for name in TRANSLATION_OUTPUT_CSVS:
        if (translations_dir / name).is_file():
            out.append(name)
    return out


def get_subtitle_text(subtitle_path: Path) -> str:
    """Extract clean text from subtitle file for context."""
    from subtitle_text_utils import get_subtitle_text as _gst

    return _gst(subtitle_path)


MAX_EXAMPLE_LINE_CHARS = 200


def extract_examples_from_subtitle(
    subtitle_content: str,
    words: List[str],
    max_per_word: int = 2,
) -> Dict[str, List[str]]:
    """Extract example lines from SRT where each word appears (word-boundary match).
    Returns word -> list of cleaned subtitle lines, each truncated to MAX_EXAMPLE_LINE_CHARS."""
    return extract_word_examples_from_srt_content(
        subtitle_content,
        words,
        max_per_word=max_per_word,
        max_line_chars=MAX_EXAMPLE_LINE_CHARS,
    )


def load_episode_info(episode_dir: Path) -> Optional[Dict[str, Any]]:
    """Load episode_info.json from episode directory."""
    path = episode_dir / EPISODE_INFO_JSON
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"Warning: Could not read {EPISODE_INFO_JSON}: {e}")
        return None


def load_tier_words(episode_dir: Path, csv_name: str) -> List[str]:
    """Load word column from a tier CSV in episode_dir."""
    path = episode_dir / csv_name
    if not path.exists():
        return []
    words: List[str] = []
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            w = (row.get("word") or "").strip()
            if w:
                words.append(w)
    return words


def load_tier1_words(episode_dir: Path) -> List[str]:
    """Load word column from tier_1_hard_usable_words.csv."""
    return load_tier_words(episode_dir, TIER_1_CSV)


def load_existing_translations(csv_path: Path) -> Dict[str, str]:
    """Load word -> translation_ru from an existing tier_1_translations.csv."""
    out: Dict[str, str] = {}
    if not csv_path.is_file():
        return out
    try:
        with open(csv_path, "r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                w = (row.get("word") or "").strip()
                t = (row.get("translation_ru") or "").strip()
                if w:
                    out[w] = t
    except OSError:
        pass
    return out


def _pick_subtitle_from_matches(
    matches: List[Path],
    *,
    season_number: Optional[int],
    episode_number: Optional[int],
) -> Optional[Path]:
    """If multiple files share the same basename, prefer name containing _sN_eM."""
    if not matches:
        return None
    if len(matches) == 1:
        return matches[0]
    if season_number is not None and episode_number is not None:
        token = f"_s{season_number}_e{episode_number}"
        for p in matches:
            if token in p.name.lower():
                return p
    return matches[0]


def _find_subtitle_under_base(
    subtitle_base_dir: Path,
    subtitle_file: str,
    *,
    season_number: Optional[int],
    episode_number: Optional[int],
) -> Optional[Path]:
    """
    Fallback when metadata series/season folder does not match on-disk layout
    (e.g. tier folder "Fallout S2 E5/Season 1" vs file at Subtitle/Fallout/Season 2/...).
    """
    if not subtitle_base_dir.is_dir():
        return None
    base = Path(subtitle_file).name
    if not base or base == "unknown.srt":
        return None
    try:
        found = sorted(subtitle_base_dir.rglob(base))
    except OSError:
        return None
    files = [p for p in found if p.is_file()]
    return _pick_subtitle_from_matches(
        files,
        season_number=season_number,
        episode_number=episode_number,
    )


def resolve_subtitle_path(
    episode_dir: Path,
    episode_info: Dict[str, Any],
    subtitle_base_dir: Path,
    explicit_subtitle: Optional[Path],
) -> Optional[Path]:
    """Resolve subtitle file path from episode_info or explicit path."""
    if explicit_subtitle is not None:
        return explicit_subtitle if explicit_subtitle.exists() else None
    series = episode_info.get("series") or ""
    subtitle_file = episode_info.get("subtitle_file") or ""
    if not subtitle_file:
        return None
    season_number = episode_info.get("season_number")
    episode_number = episode_info.get("episode_number")
    if isinstance(season_number, str) and season_number.isdigit():
        season_number = int(season_number)
    if isinstance(episode_number, str) and episode_number.isdigit():
        episode_number = int(episode_number)

    path: Optional[Path] = None
    if episode_info.get("is_movie"):
        if not series:
            return _find_subtitle_under_base(
                subtitle_base_dir,
                subtitle_file,
                season_number=None,
                episode_number=None,
            )
        path = subtitle_base_dir / "Movies" / series / subtitle_file
    else:
        if season_number is None:
            return None
        season_name = f"Season {season_number}"
        if series:
            path = subtitle_base_dir / series / season_name / subtitle_file
        else:
            path = None

    if path is not None and path.exists():
        return path
    return _find_subtitle_under_base(
        subtitle_base_dir,
        subtitle_file,
        season_number=season_number if isinstance(season_number, int) else None,
        episode_number=episode_number if isinstance(episode_number, int) else None,
    )


async def translate_batch(
    client: Any,
    words: List[str],
    subtitle_context: str,
    series_name: str,
    examples: Dict[str, List[str]],
    target_language: str = "Russian",
) -> Dict[str, str]:
    """Call OpenAI to translate a batch of words. Returns dict word -> translation_ru."""
    if not words:
        return {}
    words_list = ", ".join([f'"{w}"' for w in words])
    context = subtitle_context

    examples_lines = []
    for w in words:
        ex = examples.get(w, [])
        if ex:
            for i, line in enumerate(ex[:2]):
                examples_lines.append(f'  "{w}": "{line}"')
        else:
            examples_lines.append(f'  "{w}": (no example in subtitle)')
    examples_block = "\n".join(examples_lines)

    prompt = f"""Series: {series_name}. Use the meaning that fits this show's setting (e.g. medieval/fantasy: maid = handmaid/servant = служанка; crow can be the bird or to crow; choose based on the example lines below).

You are a dictionary translator. Translate the following English words into {target_language}.

EXAMPLE LINES FROM THE EPISODE (use these to choose the correct sense):
{examples_block}

SUBTITLE CONTEXT (fallback when a word has no example above):
{context}

WORDS TO TRANSLATE: {words_list}

RULES:
- Translation must be short and dictionary-like: maximum 4-5 words.
- Prefer the meaning that appears in the EXAMPLE LINES above; if there are no examples for a word, use the subtitle context and the series setting.
- For period/fantasy series, prefer setting-appropriate terms (e.g. maid as servant = служанка; appropriate register for nobility/war).
- Avoid generic or default dictionary sense when the context clearly suggests a more specific sense (e.g. beating in a fight context; raped as in the dialogue).
- NEVER phonetically transcribe English sounds into Russian. Always use a real Russian dictionary word.
  Wrong: "cockroach" → "Кокроча"   Right: "cockroach" → "таракан"
  Wrong: "erm" → "эм"              Right: "erm" → "э-э (звук колебания)"
  If a word has no clean Russian equivalent, use the closest semantic meaning — never a phonetic copy.
- IMPORTANT NAME RULE: if the EXAMPLE LINES show that this token is used as a character/person name in the episode,
  output this exact pattern:
  "<русская передача имени> (имя в сериале), словарный перевод — <обычный перевод слова>"
  Example: "destiny" when used as a name → "Дестини (имя в сериале), словарный перевод — судьба"
- The "maximum 4-5 words" rule does NOT apply to this special NAME RULE format.
- If you are genuinely unsure of a word's meaning in context, leave its value as an empty string "".
- Output ONLY a JSON object with the exact English word as key and the {target_language} translation as value. No explanation.
- Example format: {{"word1": "translation1", "word2": "translation2"}}

Respond with a single JSON object only."""

    response = None
    for attempt in range(4):
        if attempt > 0:
            wait = 15 * (2 ** (attempt - 1))  # 15s, 30s, 60s
            print(f"    translate retry {attempt}/3 after {wait}s...")
            await asyncio.sleep(wait)
        try:
            response = await client.chat.completions.create(
                model="gpt-5.4",
                messages=[
                    {"role": "system", "content": "You are a precise Russian dictionary translator. You respond only with valid JSON. No markdown, no extra text. Never phonetically transcribe — always use real Russian words."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                timeout=90.0,
            )
            break
        except Exception as e:
            err = str(e)
            if "429" not in err and "rate" not in err.lower():
                print(f"  API error: {e}")
                return {}
            if attempt == 3:
                print(f"  API error after retries: {e}")
                return {}

    if not response or not response.choices or not response.choices[0].message:
        return {}
    try:
        content = (response.choices[0].message.content or "").strip()
        # Strip markdown code block if present
        if content.startswith("```"):
            content = re.sub(r"^```\w*\n?", "", content)
            content = re.sub(r"\n?```\s*$", "", content)
        result = json.loads(content)
        if not isinstance(result, dict):
            return {}
        return {k: (v if isinstance(v, str) else str(v)).strip() for k, v in result.items()}
    except json.JSONDecodeError as e:
        print(f"  JSON error for batch: {e}")
        return {}


async def _run_translate_batches_for_words(
    async_client: Any,
    words_for_examples: List[str],
    words_to_translate: List[str],
    subtitle_content: str,
    prompt_context: str,
    series_name: str,
    translations: Dict[str, str],
    *,
    tier_label: str = "",
) -> Dict[str, int]:
    """
    Fill translations[w] for each w in words_to_translate via API (1 word per batch).
    Uses words_for_examples for subtitle example extraction. Returns timing ms:
    primary_translate_ms, retry_translate_ms.
    """
    timings = {"primary_translate_ms": 0, "retry_translate_ms": 0}
    if not words_to_translate:
        return timings
    examples = extract_examples_from_subtitle(
        subtitle_content, words_for_examples, max_per_word=3
    )
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_BATCHES)
    n_batches = max(1, (len(words_to_translate) + BATCH_SIZE - 1) // BATCH_SIZE)
    prefix = f"[{tier_label}] " if tier_label else ""

    async def translate_one(batch_words: List[str], batch_index: int) -> Dict[str, str]:
        async with semaphore:
            print(
                f"  {prefix}Translating batch {batch_index}/{n_batches}: {batch_words[0]!r}..."
            )
            return await translate_batch(
                async_client, batch_words, prompt_context, series_name, examples
            )

    batches: List[List[str]] = [
        words_to_translate[i : i + BATCH_SIZE]
        for i in range(0, len(words_to_translate), BATCH_SIZE)
    ]
    tasks = [
        translate_one(batch_words, idx + 1) for idx, batch_words in enumerate(batches)
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for batch_words, result in zip(batches, results):
        if isinstance(result, Exception):
            continue
        for w in batch_words:
            translations[w] = result.get(w) or ""

    primary_started = time.perf_counter()
    empty_started = 0.0
    empty_words = [
        w for w in words_to_translate if not translations.get(w, "").strip()
    ]
    if empty_words:
        print(f"  {prefix}Retry pass: {len(empty_words)} empty translations...")
        empty_started = time.perf_counter()

        async def retry_one(batch_words: List[str]) -> Dict[str, str]:
            async with semaphore:
                return await translate_batch(
                    async_client,
                    batch_words,
                    prompt_context,
                    series_name,
                    examples,
                )

        retry_batches: List[List[str]] = [
            empty_words[i : i + BATCH_SIZE]
            for i in range(0, len(empty_words), BATCH_SIZE)
        ]
        rtasks = [retry_one(b) for b in retry_batches]
        rresults = await asyncio.gather(*rtasks, return_exceptions=True)
        for batch_words, result in zip(retry_batches, rresults):
            if isinstance(result, Exception):
                continue
            for w in batch_words:
                filled = (result.get(w) or "").strip()
                if filled:
                    translations[w] = filled

    timings["primary_translate_ms"] = int(
        ((empty_started or time.perf_counter()) - primary_started) * 1000
    )
    if empty_started:
        timings["retry_translate_ms"] = int(
            (time.perf_counter() - empty_started) * 1000
        )
    return timings


def run(
    episode_dir: Path,
    subtitle_path: Optional[Path] = None,
    api_key: Optional[str] = None,
    translations_base: Optional[Path] = None,
    subtitle_base: Optional[Path] = None,
    metrics_out: Optional[Dict[str, Any]] = None,
    subtitle_raw: Optional[str] = None,
    translation_overwrite: bool = False,
    tier_ids: Optional[Collection[str]] = None,
) -> tuple[bool, Optional[str]]:
    """Load words and subtitle, translate in batches, save to translations dir.

    tier_ids: If None, translate every tier that has words (CLI default). If set, only those
    tier ids are translated and written; other translation CSVs on disk are left unchanged.
    Known ids: tier_1, b1, b2, tier_4c, tier_4b (see ALL_TRANSLATION_TIER_IDS).

    Returns (success, error_message). On success error_message is None."""
    started_total = time.perf_counter()
    started_phase = started_total
    timings_ms: Dict[str, Any] = {
        "prepare_ms": 0,
        "primary_translate_ms": 0,
        "retry_translate_ms": 0,
        "write_outputs_ms": 0,
        "total_ms": 0,
    }
    tier_metrics_detail: Dict[str, Dict[str, Any]] = {}
    scoped_word_count = 0
    requested_tier_ids: Optional[FrozenSet[str]] = None

    def _set_metrics(status: str, error: Optional[str] = None) -> None:
        timings_ms["total_ms"] = int((time.perf_counter() - started_total) * 1000)
        if metrics_out is None:
            return
        metrics_out.clear()
        payload: Dict[str, Any] = {
            "status": status,
            "error": error,
            "word_count": scoped_word_count,
            "timings_ms": dict(timings_ms),
        }
        if requested_tier_ids is not None:
            payload["last_run_tier_ids"] = sorted(requested_tier_ids)
        if "words_b1" in locals():
            payload["tier_b1_word_count"] = len(words_b1)
            payload["tier_b2_word_count"] = len(words_b2)
        if "words_4c" in locals():
            payload["tier_4_rare_c_word_count"] = len(words_4c)
            payload["tier_4_rare_b_word_count"] = len(words_4b)
        if tier_metrics_detail:
            payload["tiers"] = dict(tier_metrics_detail)
        metrics_out.update(payload)

    episode_dir = episode_dir.resolve()
    if not episode_dir.is_dir():
        msg = f"Episode directory not found: {episode_dir}"
        print(msg)
        _set_metrics("error", msg)
        return False, msg

    episode_info = load_episode_info(episode_dir)
    if not episode_info:
        msg = "Could not load episode_info.json; need series, season_number, episode_number for output path."
        print(msg)
        _set_metrics("error", msg)
        return False, msg

    series_name = episode_info.get("series") or "Unknown"
    season_number = int(episode_info.get("season_number", 0))
    episode_number = int(episode_info.get("episode_number", 0))

    subtitle_base_dir = (subtitle_base or SUBTITLE_BASE_DIR).resolve()
    srt_path = resolve_subtitle_path(episode_dir, episode_info, subtitle_base_dir, subtitle_path)
    if subtitle_raw is None and not srt_path:
        msg = "Subtitle file not found for this episode."
        print(msg)
        _set_metrics("error", msg)
        return False, msg

    words = load_tier1_words(episode_dir)
    words_b1 = load_tier_words(episode_dir, TIER_B1_CSV)
    words_b2 = load_tier_words(episode_dir, TIER_B2_CSV)
    words_4c = load_tier_words(episode_dir, TIER_4_RARE_C_CSV)
    words_4b = load_tier_words(episode_dir, TIER_4_RARE_B_CSV)

    if tier_ids is None:
        requested_tier_ids = frozenset(ALL_TRANSLATION_TIER_IDS)
    else:
        req = frozenset(str(x).strip() for x in tier_ids if str(x).strip())
        unknown = req - ALL_TRANSLATION_TIER_IDS
        if unknown:
            msg = f"Unknown tier_ids: {sorted(unknown)}"
            print(msg)
            _set_metrics("error", msg)
            return False, msg
        requested_tier_ids = req

    tier_lists: Dict[str, List[str]] = {
        TIER_ID_TIER_1: words,
        TIER_ID_B1: words_b1,
        TIER_ID_B2: words_b2,
        TIER_ID_TIER_4C: words_4c,
        TIER_ID_TIER_4B: words_4b,
    }
    scoped_word_count = sum(
        len(tier_lists[tid]) for tid in requested_tier_ids if len(tier_lists[tid]) > 0
    )
    if not any(len(tier_lists[tid]) > 0 for tid in requested_tier_ids):
        msg = "No words in tier lists to translate."
        print(msg)
        _set_metrics("error", msg)
        return False, msg

    base = (translations_base or TRANSLATIONS_BASE_DIR).resolve()
    from download_subtitles import get_translations_episode_dir, get_translations_movie_dir

    if episode_info.get("is_movie"):
        year = int(episode_info.get("year", 0))
        out_dir_early = get_translations_movie_dir(base, series_name, year)
    else:
        out_dir_early = get_translations_episode_dir(
            base, series_name, season_number, episode_number
        )
    out_dir_early.mkdir(parents=True, exist_ok=True)

    if subtitle_raw is not None:
        subtitle_content = subtitle_raw
        timings_ms["subtitle_read_skipped"] = 1
    else:
        subtitle_content = srt_path.read_text(encoding="utf-8", errors="ignore")
        timings_ms["subtitle_read_skipped"] = 0
    subtitle_text = get_subtitle_text_from_content(subtitle_content)
    prompt_context = (
        subtitle_text[:SUBTITLE_CONTEXT_CHARS]
        if len(subtitle_text) > SUBTITLE_CONTEXT_CHARS
        else subtitle_text
    )
    timings_ms["prepare_ms"] = int((time.perf_counter() - started_phase) * 1000)

    from env_config import resolve_openai_api_key

    api_key = resolve_openai_api_key(api_key)
    if not api_key:
        msg = "OpenAI API key not set (OPENAI_API_KEY environment variable)."
        print(msg)
        _set_metrics("error", msg)
        return False, msg

    try:
        from openai import AsyncOpenAI
    except ImportError:
        msg = "OpenAI package not installed."
        print(msg)
        _set_metrics("error", msg)
        return False, msg

    out_dir = out_dir_early

    tier_specs: List[Tuple[str, List[str], str, str]] = [
        ("tier_1", words, TIER_1_TRANSLATIONS_CSV, "tier_1"),
        ("b1", words_b1, TIER_B1_TRANSLATIONS_CSV, "B1"),
        ("b2", words_b2, TIER_B2_TRANSLATIONS_CSV, "B2"),
        ("tier_4c", words_4c, TIER_4_RARE_C_TRANSLATIONS_CSV, "C1C2-rare"),
        ("tier_4b", words_4b, TIER_4_RARE_B_TRANSLATIONS_CSV, "B1B2-rare"),
    ]

    async def run_all_translation_passes() -> Dict[str, Dict[str, str]]:
        async_client = AsyncOpenAI(api_key=api_key)
        results_by_id: Dict[str, Dict[str, str]] = {}
        try:
            for tier_id, wlist, out_csv, label in tier_specs:
                if tier_id not in requested_tier_ids:
                    continue
                if not wlist:
                    results_by_id[tier_id] = {}
                    tier_metrics_detail[tier_id] = {
                        "word_count": 0,
                        "to_translate": 0,
                        "reused": 0,
                        "primary_translate_ms": 0,
                        "retry_translate_ms": 0,
                    }
                    continue
                out_p = out_dir_early / out_csv
                existing = (
                    {}
                    if translation_overwrite
                    else load_existing_translations(out_p)
                )
                trans: Dict[str, str] = {}
                for ww in wlist:
                    trans[ww] = (
                        ""
                        if translation_overwrite
                        else (existing.get(ww) or "").strip()
                    )
                to_tr = [ww for ww in wlist if not trans[ww].strip()]
                reused = len(wlist) - len(to_tr)
                tms = await _run_translate_batches_for_words(
                    async_client,
                    wlist,
                    to_tr,
                    subtitle_content,
                    prompt_context,
                    series_name,
                    trans,
                    tier_label=label,
                )
                results_by_id[tier_id] = trans
                tier_metrics_detail[tier_id] = {
                    "word_count": len(wlist),
                    "to_translate": len(to_tr),
                    "reused": reused,
                    **tms,
                }
        finally:
            await async_client.close()
        return results_by_id

    print(
        f"Loaded tier_1={len(words)}, B1={len(words_b1)}, B2={len(words_b2)}, "
        f"rare_C={len(words_4c)}, rare_B={len(words_4b)}; "
        f"tier_ids={sorted(requested_tier_ids)}; subtitle context {len(subtitle_text)} chars."
    )

    try:
        all_by_tier = asyncio.run(run_all_translation_passes())
        timings_ms["primary_translate_ms"] = sum(
            int(tier_metrics_detail[t]["primary_translate_ms"])
            for t in tier_metrics_detail
        )
        timings_ms["retry_translate_ms"] = sum(
            int(tier_metrics_detail[t]["retry_translate_ms"])
            for t in tier_metrics_detail
        )
        t1d = tier_metrics_detail.get("tier_1", {})
        timings_ms["translations_reused"] = int(t1d.get("reused", 0))
    except Exception as e:
        msg = str(e) or f"Translation API error: {str(e)[:80]}"
        print(msg)
        _set_metrics("error", msg)
        return False, msg

    started_phase = time.perf_counter()

    def _write_translation_csv(filename: str, wlist: List[str], trans: Dict[str, str]) -> None:
        if not wlist:
            return
        tier_examples = extract_examples_from_subtitle(
            subtitle_content, wlist, max_per_word=1
        )
        path = out_dir / filename
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["word", "translation_ru", "example_en"])
            for w in wlist:
                ex_lines = tier_examples.get(w, [])
                example_en = ex_lines[0] if ex_lines else ""
                writer.writerow([w, trans.get(w, ""), example_en])

    if TIER_ID_TIER_1 in requested_tier_ids:
        _write_translation_csv(
            TIER_1_TRANSLATIONS_CSV, words, all_by_tier.get("tier_1", {})
        )
    if TIER_ID_B1 in requested_tier_ids:
        _write_translation_csv(
            TIER_B1_TRANSLATIONS_CSV, words_b1, all_by_tier.get("b1", {})
        )
    if TIER_ID_B2 in requested_tier_ids:
        _write_translation_csv(
            TIER_B2_TRANSLATIONS_CSV, words_b2, all_by_tier.get("b2", {})
        )
    if TIER_ID_TIER_4C in requested_tier_ids:
        _write_translation_csv(
            TIER_4_RARE_C_TRANSLATIONS_CSV, words_4c, all_by_tier.get("tier_4c", {})
        )
    if TIER_ID_TIER_4B in requested_tier_ids:
        _write_translation_csv(
            TIER_4_RARE_B_TRANSLATIONS_CSV, words_4b, all_by_tier.get("tier_4b", {})
        )

    source_subtitle_name = (
        srt_path.name
        if srt_path is not None
        else (episode_info.get("subtitle_file") or "unknown.srt")
    )
    written_this_run: List[str] = []
    if TIER_ID_TIER_1 in requested_tier_ids and words:
        written_this_run.append(TIER_1_TRANSLATIONS_CSV)
    if TIER_ID_B1 in requested_tier_ids and words_b1:
        written_this_run.append(TIER_B1_TRANSLATIONS_CSV)
    if TIER_ID_B2 in requested_tier_ids and words_b2:
        written_this_run.append(TIER_B2_TRANSLATIONS_CSV)
    if TIER_ID_TIER_4C in requested_tier_ids and words_4c:
        written_this_run.append(TIER_4_RARE_C_TRANSLATIONS_CSV)
    if TIER_ID_TIER_4B in requested_tier_ids and words_4b:
        written_this_run.append(TIER_4_RARE_B_TRANSLATIONS_CSV)

    info = {
        "series": series_name,
        "season_number": season_number,
        "episode_number": episode_number,
        "source_subtitle": source_subtitle_name,
        "translated_at": __import__("datetime").datetime.now().isoformat(),
        "tier_word_counts": {
            "tier_1": len(words),
            "b1": len(words_b1),
            "b2": len(words_b2),
            "tier_4_rare_c": len(words_4c),
            "tier_4_rare_b": len(words_4b),
        },
        "translation_csv_files": translation_csv_files_present(out_dir),
        "last_run_tier_ids": sorted(requested_tier_ids),
        "written_translation_csvs_this_run": written_this_run,
    }
    if episode_info.get("is_movie"):
        info["is_movie"] = True
        info["year"] = int(episode_info.get("year", 0))
    (out_dir / "translation_info.json").write_text(
        json.dumps(info, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    timings_ms["write_outputs_ms"] = int((time.perf_counter() - started_phase) * 1000)

    print(
        f"Saved {', '.join(written_this_run) or '(no new CSV rows)'} "
        f"and translation_info.json to {out_dir}/"
    )
    _set_metrics("ok")
    return True, None


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Translate tier_1, B1, and B2 words to Russian using ChatGPT and subtitle context."
    )
    parser.add_argument(
        "--episode-dir",
        type=Path,
        required=True,
        help="Episode directory (e.g. Tier_lists/Game of Thrones/Season 2/2)",
    )
    parser.add_argument(
        "--subtitle",
        type=Path,
        default=None,
        help="Subtitle file path (default: inferred from episode_info.json and Subtitle/)",
    )
    parser.add_argument(
        "--openai-api-key",
        type=str,
        default=None,
        help="OpenAI API key (default: OPENAI_API_KEY env)",
    )
    parser.add_argument(
        "--translations-base-dir",
        type=Path,
        default=TRANSLATIONS_BASE_DIR,
        help=f"Base directory for translations output (default: {TRANSLATIONS_BASE_DIR})",
    )
    parser.add_argument(
        "--subtitle-base-dir",
        type=Path,
        default=SUBTITLE_BASE_DIR,
        help=f"Base directory for subtitles when inferring path (default: {SUBTITLE_BASE_DIR})",
    )
    parser.add_argument(
        "--force-translate",
        action="store_true",
        help="Re-translate all words for tier_1, B1, and B2; ignore existing translation CSVs",
    )
    args = parser.parse_args()

    ok, err = run(
        episode_dir=args.episode_dir,
        subtitle_path=args.subtitle,
        api_key=args.openai_api_key,
        translations_base=args.translations_base_dir,
        subtitle_base=args.subtitle_base_dir,
        translation_overwrite=args.force_translate,
    )
    if not ok and err:
        print(f"Error: {err}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
