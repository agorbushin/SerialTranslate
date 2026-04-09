#!/usr/bin/env python3
r"""
LLM Judge for translation quality evaluation.

Evaluates translation CSVs (default tier_1_translations.csv) against three criteria:
  1. All words translated and correct within the series context
  2. No made-up words, character names, place names, or non-English entities in the source list
  3. CEFR band appropriateness (depends on level_profile)

Uses ChatGPT as the reasoning judge model. Does NOT modify any existing system files.

Usage:
    python translation_judge.py --translations-dir "translations/Narcos S1 E1/Season 1/1"
    python translation_judge.py --translations-dir ... \\
        --translations-csv tier_b1_translations.csv --translations-csv tier_b2_translations.csv \\
        --level-profile frequent_b_merged
"""

import argparse
import csv
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from subtitle_text_utils import extract_word_examples_from_srt_path, get_subtitle_text as _get_subtitle_text

JUDGE_MODEL = "gpt-5.4-mini"
SUBTITLE_CONTEXT_CHARS = 4000
MAX_EXAMPLE_LINE_CHARS = 200
EXAMPLES_PER_WORD = 2

TRANSLATIONS_CSV = "tier_1_translations.csv"
TRANSLATION_INFO_JSON = "translation_info.json"

# level_profile values for criterion 3 wording
LEVEL_PROFILE_FREQUENT_C = "frequent_c"
LEVEL_PROFILE_FREQUENT_B_MERGED = "frequent_b_merged"
LEVEL_PROFILE_RARE_C = "rare_c"
LEVEL_PROFILE_RARE_B = "rare_b"

# When loading these CSVs together, prefix rows with [B1]/[B2] for the judge.
_CSV_BAND_LABEL: Dict[str, str] = {
    "tier_b1_translations.csv": "B1",
    "tier_b2_translations.csv": "B2",
}

BASE_DIR = Path(__file__).resolve().parent
SUBTITLE_BASE = BASE_DIR / "Subtitle"


# ---------------------------------------------------------------------------
# API key resolution (same pattern as other modules)
# ---------------------------------------------------------------------------

def _load_api_key(api_key: Optional[str] = None) -> str:
    from env_config import resolve_openai_api_key

    return resolve_openai_api_key(api_key)


# ---------------------------------------------------------------------------
# Subtitle helpers (shared with translator via subtitle_text_utils)
# ---------------------------------------------------------------------------


def _extract_examples(
    subtitle_path: Path, words: List[str], max_per_word: int = EXAMPLES_PER_WORD
) -> Dict[str, List[str]]:
    """Return up to max_per_word subtitle lines per word (word-boundary match)."""
    return extract_word_examples_from_srt_path(
        subtitle_path,
        words,
        max_per_word=max_per_word,
        max_line_chars=MAX_EXAMPLE_LINE_CHARS,
    )


# ---------------------------------------------------------------------------
# Load translations
# ---------------------------------------------------------------------------

def _load_one_translation_csv(
    translations_dir: Path,
    basename: str,
    *,
    band_label: str = "",
) -> List[Dict[str, str]]:
    csv_path = translations_dir / basename
    if not csv_path.exists():
        raise FileNotFoundError(f"Translations CSV not found: {csv_path}")
    out: List[Dict[str, str]] = []
    with open(csv_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            word = (row.get("word") or "").strip()
            translation = (row.get("translation_ru") or "").strip()
            if word:
                item: Dict[str, str] = {"word": word, "translation_ru": translation}
                if band_label:
                    item["band_label"] = band_label
                out.append(item)
    return out


def load_translations(
    translations_dir: Path,
    *,
    translation_csvs: Optional[Sequence[str]] = None,
) -> Tuple[List[Dict[str, str]], Dict[str, Any]]:
    """Load word-translation pairs and episode info.

    Args:
        translations_dir: Episode directory with CSVs and translation_info.json.
        translation_csvs: Basenames to load (in order). Default: tier_1 only.
            For merged Frequent B pass
            ["tier_b1_translations.csv", "tier_b2_translations.csv"] — rows get band_label B1/B2.

    Returns:
        (pairs, info) where each pair has word, translation_ru, and optional band_label.
    """
    translations_dir = Path(translations_dir)
    basenames = (
        list(translation_csvs)
        if translation_csvs is not None
        else [TRANSLATIONS_CSV]
    )
    if not basenames:
        raise FileNotFoundError("translation_csvs is empty.")

    pairs: List[Dict[str, str]] = []
    for bn in basenames:
        label = _CSV_BAND_LABEL.get(bn, "")
        pairs.extend(_load_one_translation_csv(translations_dir, bn, band_label=label))

    info_path = translations_dir / TRANSLATION_INFO_JSON
    info: Dict[str, Any] = {}
    if info_path.exists():
        try:
            info = json.loads(info_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    return pairs, info


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

def _criterion_3_block(level_profile: str) -> str:
    if level_profile == LEVEL_PROFILE_FREQUENT_C:
        return """=== CRITERION 3: C-Level English Vocabulary (CEFR C1/C2) ===
The purpose of this word list is to teach advanced (C-level) vocabulary to Russian speakers.
For every source word, assess its CEFR difficulty:
- Words SHOULD be C1 or C2 — advanced, specialized, or uncommon vocabulary.
- Flag words that are too basic for a C-level learning list:
  * A1/A2: extremely common words (e.g. "loved", "stopped", "fake", "tire", "flip")
  * B1/B2: fairly common words that most intermediate learners would already know
- Do NOT flag words that are legitimately difficult even if they look simple.
Score 0–10 (10 = all words are genuinely C1/C2 level; 0 = list is full of basic vocabulary)."""

    if level_profile == LEVEL_PROFILE_FREQUENT_B_MERGED:
        return """=== CRITERION 3: B-Level English Vocabulary (CEFR B1 / B2) ===
Each row is prefixed with [B1] or [B2] showing which sub-band it belongs to.
- Rows marked [B1]: should be genuine B1-level vocabulary — not trivial A1/A2.
- Rows marked [B2]: should be genuine B2-level vocabulary — not mostly A1/A2/B1-easy.
- Flag words that are clearly the wrong band (e.g. [B2] row that is only A2; [B1] row that is C1 specialist jargon with no B1 justification).
Score 0–10 (10 = band tags match actual difficulty; 0 = badly miscalibrated list)."""

    if level_profile == LEVEL_PROFILE_RARE_C:
        return """=== CRITERION 3: Advanced (C-band) words rare in this series ===
This list is meant to highlight advanced English vocabulary that appears rarely in THIS episode/series.
- Words should be genuine C1/C2-level English vocabulary (not basic A/B junk).
- Flag entries that are too elementary for an "advanced rare" list, or that are mislabeled (e.g. ultra-common words).
- The "rare in series" idea is contextual frequency; still enforce that items belong in an advanced learning band.
Score 0–10 (10 = appropriate advanced band; 0 = list misfits the intended band)."""

    if level_profile == LEVEL_PROFILE_RARE_B:
        return """=== CRITERION 3: B-band words rare in this series ===
This list is meant for B1/B2-level vocabulary that appears rarely in THIS episode/series.
- Words should sit in the B1–B2 range — not mostly A1/A2 trivia, and not specialist C1/C2-only jargon unless context justifies it.
- Flag clear band mismatches and entries that do not belong on a B-learner list.
Score 0–10 (10 = band-appropriate; 0 = poorly calibrated)."""

    # Fallback: same as frequent C
    return _criterion_3_block(LEVEL_PROFILE_FREQUENT_C)


def _pair_display_prefix(p: Dict[str, str]) -> str:
    bl = (p.get("band_label") or "").strip()
    return f"[{bl}] " if bl else ""


def _build_prompt(
    pairs: List[Dict[str, str]],
    series_name: str,
    season: int,
    episode: int,
    subtitle_context: str,
    examples: Dict[str, List[str]],
    *,
    level_profile: str = LEVEL_PROFILE_FREQUENT_C,
) -> str:
    # Build word list table
    word_lines = []
    for p in pairs:
        word = p["word"]
        tr = p["translation_ru"] or "(empty)"
        prefix = _pair_display_prefix(p)
        word_lines.append(f'  {prefix}"{word}" → "{tr}"')
    word_block = "\n".join(word_lines)

    # Build examples block
    ex_lines = []
    for p in pairs:
        word = p["word"]
        ex = examples.get(word, [])
        if ex:
            for line in ex:
                ex_lines.append(f'  "{word}": {line}')
        else:
            ex_lines.append(f'  "{word}": (no subtitle example found)')
    examples_block = "\n".join(ex_lines)

    context_snippet = (
        subtitle_context[:SUBTITLE_CONTEXT_CHARS]
        if len(subtitle_context) > SUBTITLE_CONTEXT_CHARS
        else subtitle_context
    )

    crit3 = _criterion_3_block(level_profile)

    return f"""You are an expert evaluator of English vocabulary translation quality.
Your task is to judge a list of English words and their Russian translations taken from a TV series episode.

SERIES: {series_name}, Season {season}, Episode {episode}

WORD LIST (English → Russian translation):
{word_block}

SUBTITLE EXAMPLES (lines from the episode where each word appears):
{examples_block}

GENERAL SUBTITLE CONTEXT (first portion of episode dialogue):
{context_snippet}

---
Evaluate this translation output against THREE criteria. Think carefully and reason step by step for each before scoring.

=== CRITERION 1: Translation Completeness & Contextual Correctness ===
For every word-translation pair:
- Is the word actually translated (translation is not empty, not a dash, not untranslated English)?
- Is the Russian translation semantically correct for the meaning this word has IN THIS SERIES?
  Use the subtitle examples above to verify the correct sense was chosen.
- Flag these issues:
  * Missing/empty translation
  * Wrong sense chosen (e.g. "crow" translated as the bird when it means to boast in context)
  * Phonetic transliteration instead of a real Russian word (e.g. "Кокроча" for cockroach)
  * Completely wrong meaning
  * Translation that is too generic when context requires specific meaning
Score 0–10 (10 = all translations correct and complete; 0 = all wrong or missing).

=== CRITERION 2: No Non-English Entities in the Source Word List ===
For every SOURCE English word:
- Is it a real English vocabulary word?
- Identify any that should NOT be in a vocabulary list:
  * Character names (e.g. "tyrion", "walter", "escobar")
  * Place names / geographical names (countries, cities, regions — e.g. "colombia", "peru")
  * Real people's names (e.g. "nixon", "pinochet")
  * Invented fantasy/sci-fi terms that are not real English
  * Words from other languages used as-is
These should have been filtered before translation. Identify any that slipped through.
Score 0–10 (10 = no violations — all words are genuine English vocabulary; 0 = many violations).

{crit3}

---
For criterion_3, always use the key "not_c_level" for words that fail the band check (use estimated_level like A1/A2/B1/B2/C1/C2 as appropriate, and reason explaining the mismatch).

Return ONLY a valid JSON object with EXACTLY this structure (no markdown, no extra text):
{{
  "criterion_1": {{
    "score": <integer 0-10>,
    "reasoning": "<detailed step-by-step reasoning>",
    "issues": [
      {{"word": "<english_word>", "translation": "<russian_translation>", "issue": "<description>"}}
    ]
  }},
  "criterion_2": {{
    "score": <integer 0-10>,
    "reasoning": "<detailed reasoning>",
    "violations": ["<word1>", "<word2>"]
  }},
  "criterion_3": {{
    "score": <integer 0-10>,
    "reasoning": "<detailed reasoning>",
    "not_c_level": [
      {{"word": "<english_word>", "estimated_level": "<A1/A2/B1/B2/C1/C2>", "reason": "<why it fails criterion 3>"}}
    ]
  }},
  "overall_score": <float: average of 3 scores rounded to 1 decimal>,
  "summary": "<2-3 sentence overall assessment of this translation output>"
}}"""


# ---------------------------------------------------------------------------
# Core judge function
# ---------------------------------------------------------------------------

def judge_translations(
    translations_dir: Path,
    subtitle_path: Optional[Path] = None,
    api_key: Optional[str] = None,
    model: str = JUDGE_MODEL,
    subtitle_base: Optional[Path] = None,
    *,
    translation_csvs: Optional[Sequence[str]] = None,
    level_profile: str = LEVEL_PROFILE_FREQUENT_C,
) -> Dict[str, Any]:
    """
    Evaluate translations in translations_dir using an LLM judge.

    Args:
        translations_dir: Directory containing translation CSVs and translation_info.json
        subtitle_path:    Explicit subtitle file path (optional; inferred from info if omitted)
        api_key:          OpenAI API key (falls back to OPENAI_API_KEY env)
        model:            OpenAI model to use (default: gpt-4o)
        subtitle_base:    Base directory for subtitles when inferring path (default: Subtitle/)
        translation_csvs: Optional list of CSV basenames (default: tier_1 only)
        level_profile:    frequent_c | frequent_b_merged | rare_c | rare_b (criterion 3 wording)

    Returns:
        Dict with judgment results, including scores and reasoning per criterion.
        Always includes "judged_at" timestamp and "translations_dir" path.
        On error, includes "error" key with description.
    """
    translations_dir = Path(translations_dir).resolve()
    csvs_list = list(translation_csvs) if translation_csvs is not None else None
    result: Dict[str, Any] = {
        "translations_dir": str(translations_dir),
        "judged_at": datetime.now().isoformat(),
        "model": model,
        "level_profile": level_profile,
        "translation_csvs": csvs_list or [TRANSLATIONS_CSV],
    }

    # --- Load translations ---
    try:
        pairs, info = load_translations(
            translations_dir, translation_csvs=translation_csvs
        )
    except FileNotFoundError as e:
        result["error"] = str(e)
        return result

    if not pairs:
        result["error"] = "No word-translation pairs found in translations CSV."
        return result

    series_name = info.get("series") or "Unknown Series"
    season = int(info.get("season_number", 1))
    episode = int(info.get("episode_number", 1))
    result["series"] = series_name
    result["season"] = season
    result["episode"] = episode
    result["word_count"] = len(pairs)

    # --- Resolve subtitle path ---
    sub_base = (subtitle_base or SUBTITLE_BASE).resolve()
    if subtitle_path is None:
        # Try info["source_subtitle"] first
        source_sub = info.get("source_subtitle", "")
        if source_sub:
            inferred = sub_base / series_name / f"Season {season}" / source_sub
            if inferred.exists():
                subtitle_path = inferred
        # Fall back to normalized download path
        if subtitle_path is None:
            try:
                from download_subtitles import get_subtitle_path  # type: ignore
                candidate = get_subtitle_path(sub_base, series_name, season, episode)
                if candidate.exists():
                    subtitle_path = candidate
            except Exception:
                pass

    # --- Load subtitle context ---
    subtitle_context = ""
    examples: Dict[str, List[str]] = {}
    words = [p["word"] for p in pairs]
    if subtitle_path and Path(subtitle_path).exists():
        result["subtitle_used"] = str(subtitle_path)
        subtitle_context = _get_subtitle_text(Path(subtitle_path))
        examples = _extract_examples(Path(subtitle_path), words)
    else:
        result["subtitle_used"] = None
        print(f"  Warning: no subtitle found for {series_name} S{season}E{episode}; judge will use word list only.")

    # --- Build prompt ---
    prompt = _build_prompt(
        pairs,
        series_name,
        season,
        episode,
        subtitle_context,
        examples,
        level_profile=level_profile,
    )

    # --- Call OpenAI ---
    resolved_key = _load_api_key(api_key)
    if not resolved_key:
        result["error"] = "OpenAI API key not set (OPENAI_API_KEY environment variable)."
        return result

    try:
        from openai import OpenAI  # type: ignore
    except ImportError:
        result["error"] = "openai package not installed."
        return result

    client = OpenAI(api_key=resolved_key)
    print(f"  Calling {model} judge for {series_name} S{season}E{episode} ({len(pairs)} words)...")

    response = None
    last_error: Optional[str] = None
    for attempt in range(4):
        if attempt > 0:
            wait = 30 * (2 ** (attempt - 1))  # 30s, 60s, 120s
            print(f"  Judge retry {attempt}/3 after {wait}s (rate limit)...")
            time.sleep(wait)
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a rigorous translation quality evaluator. "
                            "You reason carefully through each criterion before scoring. "
                            "You respond only with valid JSON — no markdown fences, no extra text."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                response_format={"type": "json_object"},
                timeout=120.0,
            )
            last_error = None
            break
        except Exception as e:
            last_error = str(e)
            if "429" not in last_error and "rate" not in last_error.lower():
                break  # non-rate-limit error — no point retrying

    if response is None:
        result["error"] = f"OpenAI API call failed: {(last_error or 'unknown')[:120]}"
        return result

    # --- Parse response ---
    raw_content = (response.choices[0].message.content or "").strip()
    try:
        judgment = json.loads(raw_content)
    except json.JSONDecodeError as e:
        result["error"] = f"JSON parse error: {e}"
        result["raw_response"] = raw_content[:500]
        return result

    # Attach judgment fields
    for key in ("criterion_1", "criterion_2", "criterion_3", "overall_score", "summary"):
        if key in judgment:
            result[key] = judgment[key]

    # Ensure overall_score is computed even if model omits it
    if "overall_score" not in result:
        scores = []
        for c in ("criterion_1", "criterion_2", "criterion_3"):
            if c in result and isinstance(result[c], dict):
                s = result[c].get("score")
                if isinstance(s, (int, float)):
                    scores.append(float(s))
        result["overall_score"] = round(sum(scores) / len(scores), 1) if scores else 0.0

    # Token usage
    if response.usage:
        result["tokens_used"] = {
            "prompt": response.usage.prompt_tokens,
            "completion": response.usage.completion_tokens,
            "total": response.usage.total_tokens,
        }

    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="LLM judge for translation quality (reads from translations dir, does not modify system)."
    )
    parser.add_argument(
        "--translations-dir",
        type=Path,
        required=True,
        help="Directory containing translation CSVs and translation_info.json",
    )
    parser.add_argument(
        "--translations-csv",
        action="append",
        default=None,
        metavar="BASENAME",
        help=(
            "Translation CSV basename inside the dir (repeat for merged load). "
            "Default: tier_1_translations.csv only."
        ),
    )
    parser.add_argument(
        "--level-profile",
        type=str,
        default=None,
        choices=(
            LEVEL_PROFILE_FREQUENT_C,
            LEVEL_PROFILE_FREQUENT_B_MERGED,
            LEVEL_PROFILE_RARE_C,
            LEVEL_PROFILE_RARE_B,
        ),
        help=(
            "CEFR framing for criterion 3. "
            "Default: frequent_c for a single CSV; frequent_b_merged when multiple --translations-csv."
        ),
    )
    parser.add_argument(
        "--subtitle",
        type=Path,
        default=None,
        help="Subtitle SRT path (default: inferred from translation_info.json and Subtitle/ base)",
    )
    parser.add_argument(
        "--subtitle-base-dir",
        type=Path,
        default=SUBTITLE_BASE,
        help=f"Base directory for subtitles (default: {SUBTITLE_BASE})",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=JUDGE_MODEL,
        help=f"OpenAI model to use as judge (default: {JUDGE_MODEL})",
    )
    parser.add_argument(
        "--openai-api-key",
        type=str,
        default=None,
        help="OpenAI API key (default: OPENAI_API_KEY env)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Save JSON result to this file (default: print to stdout)",
    )
    args = parser.parse_args()

    base = Path(__file__).resolve().parent
    translations_dir = (
        base / args.translations_dir
        if not args.translations_dir.is_absolute()
        else args.translations_dir
    )
    subtitle_path = None
    if args.subtitle:
        subtitle_path = (
            base / args.subtitle if not args.subtitle.is_absolute() else args.subtitle
        )

    csvs = args.translations_csv
    translation_csvs = csvs if csvs else None
    if args.level_profile:
        level_profile = args.level_profile
    elif csvs and len(csvs) > 1:
        level_profile = LEVEL_PROFILE_FREQUENT_B_MERGED
    else:
        level_profile = LEVEL_PROFILE_FREQUENT_C

    result = judge_translations(
        translations_dir=translations_dir,
        subtitle_path=subtitle_path,
        api_key=args.openai_api_key,
        model=args.model,
        subtitle_base=args.subtitle_base_dir,
        translation_csvs=translation_csvs,
        level_profile=level_profile,
    )

    output_text = json.dumps(result, ensure_ascii=False, indent=2)

    if args.output:
        out_path = base / args.output if not args.output.is_absolute() else args.output
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output_text, encoding="utf-8")
        print(f"Judge report saved to: {out_path}")
    else:
        print(output_text)

    # Print quick summary to stderr for readability
    overall = result.get("overall_score", "N/A")
    summary = result.get("summary", "")
    error = result.get("error", "")
    if error:
        print(f"\n[JUDGE ERROR] {error}", file=sys.stderr)
    else:
        c1 = result.get("criterion_1", {}).get("score", "?")
        c2 = result.get("criterion_2", {}).get("score", "?")
        c3 = result.get("criterion_3", {}).get("score", "?")
        print(
            f"\n[JUDGE SCORES] C1={c1}/10  C2={c2}/10  C3={c3}/10  Overall={overall}/10",
            file=sys.stderr,
        )
        if summary:
            print(f"[SUMMARY] {summary}", file=sys.stderr)


if __name__ == "__main__":
    main()
