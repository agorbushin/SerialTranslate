#!/usr/bin/env python3
"""
LLM Judge for translation quality evaluation.

Evaluates tier_1_translations.csv against three criteria:
  1. All words translated and correct within the series context
  2. No made-up words, character names, place names, or non-English entities in the source list
  3. Words being translated are at C level English (CEFR C1/C2)

Uses ChatGPT (GPT-4o by default) as the reasoning judge model.
Does NOT modify any existing system files.

Usage:
    python translation_judge.py --translations-dir translations/Narcos\ S1\ E1/Season\ 1/1
    python translation_judge.py --translations-dir translations/Narcos\ S1\ E1/Season\ 1/1 \
        --subtitle Subtitle/Narcos/Season\ 1/narcos_s1_e1.srt \
        --output judge_report.json
"""

import argparse
import csv
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

JUDGE_MODEL = "gpt-5.4-mini"
SUBTITLE_CONTEXT_CHARS = 4000
MAX_EXAMPLE_LINE_CHARS = 200
EXAMPLES_PER_WORD = 2

TRANSLATIONS_CSV = "tier_1_translations.csv"
TRANSLATION_INFO_JSON = "translation_info.json"

BASE_DIR = Path(__file__).resolve().parent
SUBTITLE_BASE = BASE_DIR / "Subtitle"


# ---------------------------------------------------------------------------
# API key resolution (same pattern as other modules)
# ---------------------------------------------------------------------------

def _load_api_key(api_key: Optional[str] = None) -> str:
    if api_key and api_key.strip():
        return api_key.strip()
    key = os.environ.get("OPENAI_API_KEY", "")
    if key and key.strip():
        return key.strip()
    try:
        root = Path(__file__).resolve().parent
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        from telegram_bot import OPENAI_API_KEY as _k  # type: ignore
        if _k and str(_k).strip():
            return str(_k).strip()
    except Exception:
        pass
    return ""


# ---------------------------------------------------------------------------
# Subtitle helpers (standalone copies so judge has no dependency on translate_tier_translations)
# ---------------------------------------------------------------------------

def _get_subtitle_text(subtitle_path: Path) -> str:
    """Extract clean plain text from an SRT file."""
    if not subtitle_path.exists():
        return ""
    try:
        content = subtitle_path.read_text(encoding="utf-8", errors="ignore")
        content = re.sub(
            r"\d{2}:\d{2}:\d{2}[,.]\d{3}\s*-->\s*\d{2}:\d{2}:\d{2}[,.]\d{3}", "", content
        )
        content = re.sub(r"^\d+$", "", content, flags=re.MULTILINE)
        content = re.sub(r"<[^>]+>", "", content)
        content = re.sub(r"\[.*?\]", "", content)
        return " ".join(content.split())
    except Exception as e:
        print(f"  Warning: could not read subtitle: {e}")
        return ""


def _extract_examples(
    subtitle_path: Path, words: List[str], max_per_word: int = EXAMPLES_PER_WORD
) -> Dict[str, List[str]]:
    """Return up to max_per_word subtitle lines per word (word-boundary match)."""
    examples: Dict[str, List[str]] = {w: [] for w in words}
    if not subtitle_path.exists():
        return examples
    try:
        content = subtitle_path.read_text(encoding="utf-8", errors="ignore")
        blocks = re.split(r"\n\s*\n", content)
        for block in blocks:
            lines = [ln.strip() for ln in block.split("\n") if ln.strip()]
            text_lines = [
                ln
                for ln in lines
                if not re.match(r"^\d+$", ln)
                and not re.match(
                    r"\d{2}:\d{2}:\d{2}[,.]\d{3}\s*-->\s*\d{2}:\d{2}:\d{2}[,.]\d{3}", ln
                )
            ]
            if not text_lines:
                continue
            subtitle_line = re.sub(r"<[^>]+>", "", " ".join(text_lines))
            subtitle_line = re.sub(r"\[.*?\]", "", subtitle_line)
            subtitle_line = " ".join(subtitle_line.split())
            if len(subtitle_line) < 8:
                continue
            sub_lower = subtitle_line.lower()
            for word in words:
                if len(examples[word]) >= max_per_word:
                    continue
                if re.search(r"\b" + re.escape(word) + r"\b", sub_lower, re.IGNORECASE):
                    short = subtitle_line[:MAX_EXAMPLE_LINE_CHARS]
                    if short and short not in examples[word]:
                        examples[word].append(short)
    except Exception as e:
        print(f"  Warning: could not extract examples: {e}")
    return examples


# ---------------------------------------------------------------------------
# Load translations
# ---------------------------------------------------------------------------

def load_translations(
    translations_dir: Path,
) -> Tuple[List[Dict[str, str]], Dict[str, Any]]:
    """Load word-translation pairs and episode info.

    Returns:
        (pairs, info) where pairs is list of {"word": ..., "translation_ru": ...}
        and info is the translation_info.json dict (or empty dict if missing).
    """
    csv_path = translations_dir / TRANSLATIONS_CSV
    if not csv_path.exists():
        raise FileNotFoundError(f"Translations CSV not found: {csv_path}")

    pairs: List[Dict[str, str]] = []
    with open(csv_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            word = (row.get("word") or "").strip()
            translation = (row.get("translation_ru") or "").strip()
            if word:
                pairs.append({"word": word, "translation_ru": translation})

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

def _build_prompt(
    pairs: List[Dict[str, str]],
    series_name: str,
    season: int,
    episode: int,
    subtitle_context: str,
    examples: Dict[str, List[str]],
) -> str:
    # Build word list table
    word_lines = []
    for p in pairs:
        word = p["word"]
        tr = p["translation_ru"] or "(empty)"
        word_lines.append(f'  "{word}" → "{tr}"')
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

=== CRITERION 3: C-Level English Vocabulary (CEFR C1/C2) ===
The purpose of this word list is to teach advanced (C-level) vocabulary to Russian speakers.
For every source word, assess its CEFR difficulty:
- Words SHOULD be C1 or C2 — advanced, specialized, or uncommon vocabulary.
- Flag words that are too basic for a C-level learning list:
  * A1/A2: extremely common words (e.g. "loved", "stopped", "fake", "tire", "flip")
  * B1/B2: fairly common words that most intermediate learners would already know
- Do NOT flag words that are legitimately difficult even if they look simple.
Score 0–10 (10 = all words are genuinely C1/C2 level; 0 = list is full of basic vocabulary).

---
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
      {{"word": "<english_word>", "estimated_level": "<A1/A2/B1/B2>", "reason": "<why too basic>"}}
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
) -> Dict[str, Any]:
    """
    Evaluate translations in translations_dir using an LLM judge.

    Args:
        translations_dir: Directory containing tier_1_translations.csv and translation_info.json
        subtitle_path:    Explicit subtitle file path (optional; inferred from info if omitted)
        api_key:          OpenAI API key (falls back to OPENAI_API_KEY env / telegram_bot fallback)
        model:            OpenAI model to use (default: gpt-4o)
        subtitle_base:    Base directory for subtitles when inferring path (default: Subtitle/)

    Returns:
        Dict with judgment results, including scores and reasoning per criterion.
        Always includes "judged_at" timestamp and "translations_dir" path.
        On error, includes "error" key with description.
    """
    translations_dir = Path(translations_dir).resolve()
    result: Dict[str, Any] = {
        "translations_dir": str(translations_dir),
        "judged_at": datetime.now().isoformat(),
        "model": model,
    }

    # --- Load translations ---
    try:
        pairs, info = load_translations(translations_dir)
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
    prompt = _build_prompt(pairs, series_name, season, episode, subtitle_context, examples)

    # --- Call OpenAI ---
    resolved_key = _load_api_key(api_key)
    if not resolved_key:
        result["error"] = "OpenAI API key not set (OPENAI_API_KEY env or telegram_bot fallback)."
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
        help="Directory containing tier_1_translations.csv and translation_info.json",
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

    result = judge_translations(
        translations_dir=translations_dir,
        subtitle_path=subtitle_path,
        api_key=args.openai_api_key,
        model=args.model,
        subtitle_base=args.subtitle_base_dir,
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
