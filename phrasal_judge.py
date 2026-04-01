#!/usr/bin/env python3
"""
LLM judge for phrasal-verb list quality (translations + validity).

Evaluates phrasal_verbs.csv against two criteria (parallel in spirit to
translation_judge.py for tier-1 hard words, but without CEFR):

  1. Translation completeness and contextual correctness (Russian glosses)
  2. Each source string is a genuine English phrasal / verb–particle idiom,
     not random adjacency or tokenizer noise

Does not modify project data files.

Usage:
    python phrasal_judge.py --translations-dir translations/Some\ Show/Season\ 1/1
    python phrasal_judge.py --translations-dir ... --subtitle Subtitle/.../file.srt \\
        --output phrasal_judge_report.json
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from translation_judge import (  # reuse key loading, subtitle text, paths
    JUDGE_MODEL,
    SUBTITLE_BASE,
    _get_subtitle_text,
    _load_api_key,
)

PHRASAL_CSV = "phrasal_verbs.csv"
TRANSLATION_INFO_JSON = "translation_info.json"

SUBTITLE_CONTEXT_CHARS = 4000
MAX_EXAMPLE_LINE_CHARS = 220
EXAMPLES_PER_PHRASE = 2


def _phrase_boundary_pattern(phrase: str):
    """Regex matching phrase as whole tokens (lowercased text)."""
    parts = phrase.lower().split()
    if not parts:
        return re.compile(r"^$")
    inner = r"\s+".join(re.escape(p) for p in parts)
    return re.compile(rf"\b{inner}\b", re.IGNORECASE)


def _extract_examples_phrases(
    subtitle_path: Path,
    phrases: List[str],
    max_per_phrase: int = EXAMPLES_PER_PHRASE,
) -> Dict[str, List[str]]:
    """Up to max_per_phrase subtitle lines per phrasal (substring token match)."""
    examples: Dict[str, List[str]] = {p: [] for p in phrases}
    if not subtitle_path.exists():
        return examples
    try:
        content = subtitle_path.read_text(encoding="utf-8", errors="ignore")
        blocks = re.split(r"\n\s*\n", content)
        patterns = {p: _phrase_boundary_pattern(p) for p in phrases}
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
            for phrase in phrases:
                if len(examples[phrase]) >= max_per_phrase:
                    continue
                if patterns[phrase].search(sub_lower):
                    short = subtitle_line[:MAX_EXAMPLE_LINE_CHARS]
                    if short and short not in examples[phrase]:
                        examples[phrase].append(short)
    except Exception as e:
        print(f"  Warning: could not extract phrasal examples: {e}")
    return examples


def load_phrasal_list(
    translations_dir: Path,
) -> Tuple[List[Dict[str, str]], Dict[str, Any]]:
    """Load phrasal rows and translation_info.json."""
    csv_path = translations_dir / PHRASAL_CSV
    if not csv_path.exists():
        raise FileNotFoundError(f"Phrasal verbs CSV not found: {csv_path}")

    pairs: List[Dict[str, str]] = []
    with open(csv_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            pv = (row.get("phrasal_verb") or row.get("verb") or "").strip()
            translation = (row.get("translation") or "").strip()
            if pv:
                pairs.append(
                    {
                        "phrasal_verb": pv,
                        "translation_ru": translation,
                        "example": (row.get("example") or "").strip(),
                    }
                )

    info_path = translations_dir / TRANSLATION_INFO_JSON
    info: Dict[str, Any] = {}
    if info_path.exists():
        try:
            info = json.loads(info_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    return pairs, info


def _build_prompt(
    pairs: List[Dict[str, str]],
    series_name: str,
    season: int,
    episode: int,
    subtitle_context: str,
    examples: Dict[str, List[str]],
) -> str:
    lines = []
    for p in pairs:
        pv = p["phrasal_verb"]
        tr = p["translation_ru"] or "(empty)"
        ex_cell = p.get("example") or ""
        extra = f" [stored example: {ex_cell}]" if ex_cell else ""
        lines.append(f'  "{pv}" → "{tr}"{extra}')
    list_block = "\n".join(lines)

    ex_lines = []
    for p in pairs:
        pv = p["phrasal_verb"]
        ex = examples.get(pv, [])
        if ex:
            for line in ex:
                ex_lines.append(f'  "{pv}": {line}')
        else:
            ex_lines.append(f'  "{pv}": (no subtitle line matched)')
    examples_block = "\n".join(ex_lines)

    context_snippet = (
        subtitle_context[:SUBTITLE_CONTEXT_CHARS]
        if len(subtitle_context) > SUBTITLE_CONTEXT_CHARS
        else subtitle_context
    )

    return f"""You are an expert evaluator of English phrasal verbs and their Russian translations
for learners watching a TV series episode.

SERIES: {series_name}, Season {season}, Episode {episode}

PHRASAL LIST (English phrasal → Russian translation):
{list_block}

SUBTITLE EXAMPLES (lines where each phrasal appears, when found):
{examples_block}

GENERAL SUBTITLE CONTEXT (first portion of episode dialogue):
{context_snippet}

---
Evaluate this output against TWO criteria. Reason step by step for each before scoring.

=== CRITERION 1: Translation completeness & contextual correctness ===
For every phrasal–translation pair:
- Is the Russian translation present (not empty, not "N/A", not a dash, not left in English)?
- Is the gloss correct for how the phrasal is used IN THIS EPISODE? Use examples and context.
- Flag: missing translation, wrong sense, transliteration instead of real Russian, overly generic gloss.

Score 0–10 (10 = all translations correct and complete; 0 = all wrong or missing).

=== CRITERION 2: Genuine phrasal / verb–particle idioms ===
For every English SOURCE string (the multi-word phrase):
- Is it a real phrasal verb or established verb–particle / verb–preposition idiom in English?
- Reject strings that are only accidental adjacency (e.g. "you in", "man in"), tokenizer garbage,
  or ordinary grammar rather than a lexical phrasal idiom (same standard as a phrasal-verb textbook).
- Multi-word idioms like "put up with" count as valid when genuinely idiomatic.

Score 0–10 (10 = every entry is a valid phrasal-type idiom; 0 = most are false positives).

---
Return ONLY valid JSON with EXACTLY this structure (no markdown, no extra text):
{{
  "criterion_1": {{
    "score": <integer 0-10>,
    "reasoning": "<detailed step-by-step reasoning>",
    "issues": [
      {{"phrasal_verb": "<english>", "translation": "<russian>", "issue": "<description>"}}
    ]
  }},
  "criterion_2": {{
    "score": <integer 0-10>,
    "reasoning": "<detailed reasoning>",
    "invalid_phrasals": [
      {{"phrase": "<english>", "reason": "<why not a real phrasal idiom>"}}
    ]
  }},
  "overall_score": <float: average of criterion_1 and criterion_2 scores, 1 decimal>,
  "summary": "<2-3 sentence overall assessment>"
}}"""


def judge_phrasal_translations(
    translations_dir: Path,
    subtitle_path: Optional[Path] = None,
    api_key: Optional[str] = None,
    model: str = JUDGE_MODEL,
    subtitle_base: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    LLM-judge phrasal_verbs.csv in translations_dir.

    Returns dict with criterion_1, criterion_2, overall_score, summary, metadata;
    on failure includes "error".
    """
    translations_dir = Path(translations_dir).resolve()
    result: Dict[str, Any] = {
        "translations_dir": str(translations_dir),
        "judged_at": datetime.now().isoformat(),
        "model": model,
        "judge_kind": "phrasal_verbs",
    }

    try:
        pairs, info = load_phrasal_list(translations_dir)
    except FileNotFoundError as e:
        result["error"] = str(e)
        return result

    if not pairs:
        result["error"] = "No phrasal verb rows found in phrasal_verbs.csv."
        return result

    series_name = info.get("series") or "Unknown Series"
    season = int(info.get("season_number", 1))
    episode = int(info.get("episode_number", 1))
    result["series"] = series_name
    result["season"] = season
    result["episode"] = episode
    result["phrasal_count"] = len(pairs)

    sub_base = (subtitle_base or SUBTITLE_BASE).resolve()
    if subtitle_path is None:
        source_sub = info.get("source_subtitle", "")
        if source_sub:
            inferred = sub_base / series_name / f"Season {season}" / source_sub
            if inferred.exists():
                subtitle_path = inferred
        if subtitle_path is None:
            try:
                from download_subtitles import get_subtitle_path  # type: ignore

                candidate = get_subtitle_path(sub_base, series_name, season, episode)
                if candidate.exists():
                    subtitle_path = candidate
            except Exception:
                pass

    subtitle_context = ""
    examples: Dict[str, List[str]] = {}
    phrases = [p["phrasal_verb"] for p in pairs]
    if subtitle_path and Path(subtitle_path).exists():
        result["subtitle_used"] = str(subtitle_path)
        subtitle_context = _get_subtitle_text(Path(subtitle_path))
        examples = _extract_examples_phrases(Path(subtitle_path), phrases)
    else:
        result["subtitle_used"] = None
        print(
            f"  Warning: no subtitle for {series_name} S{season}E{episode}; "
            "phrasal judge uses list + stored examples only."
        )

    prompt = _build_prompt(pairs, series_name, season, episode, subtitle_context, examples)

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
    print(
        f"  Calling {model} phrasal judge for {series_name} S{season}E{episode} "
        f"({len(pairs)} phrasal verbs)..."
    )

    response = None
    last_error: Optional[str] = None
    for attempt in range(4):
        if attempt > 0:
            wait = 30 * (2 ** (attempt - 1))
            print(f"  Phrasal judge retry {attempt}/3 after {wait}s (rate limit)...")
            time.sleep(wait)
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a rigorous evaluator of phrasal verbs and Russian glosses. "
                            "You reason through each criterion before scoring. "
                            "Respond only with valid JSON — no markdown fences, no extra text."
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
                break

    if response is None:
        result["error"] = f"OpenAI API call failed: {(last_error or 'unknown')[:120]}"
        return result

    raw_content = (response.choices[0].message.content or "").strip()
    try:
        judgment = json.loads(raw_content)
    except json.JSONDecodeError as e:
        result["error"] = f"JSON parse error: {e}"
        result["raw_response"] = raw_content[:500]
        return result

    for key in ("criterion_1", "criterion_2", "overall_score", "summary"):
        if key in judgment:
            result[key] = judgment[key]

    if "overall_score" not in result:
        scores: List[float] = []
        for c in ("criterion_1", "criterion_2"):
            if c in result and isinstance(result[c], dict):
                s = result[c].get("score")
                if isinstance(s, (int, float)):
                    scores.append(float(s))
        result["overall_score"] = round(sum(scores) / len(scores), 1) if scores else 0.0

    if response.usage:
        result["tokens_used"] = {
            "prompt": response.usage.prompt_tokens,
            "completion": response.usage.completion_tokens,
            "total": response.usage.total_tokens,
        }

    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="LLM judge for phrasal_verbs.csv (does not modify data files)."
    )
    parser.add_argument(
        "--translations-dir",
        type=Path,
        required=True,
        help="Directory containing phrasal_verbs.csv and translation_info.json",
    )
    parser.add_argument("--subtitle", type=Path, default=None, help="Optional SRT path")
    parser.add_argument(
        "--subtitle-base-dir",
        type=Path,
        default=SUBTITLE_BASE,
        help=f"Subtitle base dir (default: {SUBTITLE_BASE})",
    )
    parser.add_argument("--model", type=str, default=JUDGE_MODEL, help="OpenAI judge model")
    parser.add_argument("--openai-api-key", type=str, default=None)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    base = Path(__file__).resolve().parent
    translations_dir = (
        base / args.translations_dir
        if not args.translations_dir.is_absolute()
        else args.translations_dir
    )
    subtitle_path = None
    if args.subtitle:
        subtitle_path = base / args.subtitle if not args.subtitle.is_absolute() else args.subtitle

    result = judge_phrasal_translations(
        translations_dir=translations_dir,
        subtitle_path=subtitle_path,
        api_key=args.openai_api_key,
        model=args.model,
        subtitle_base=args.subtitle_base_dir,
    )

    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        out = base / args.output if not args.output.is_absolute() else args.output
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        print(f"Phrasal judge report saved to: {out}")
    else:
        print(text)

    err = result.get("error", "")
    if err:
        print(f"\n[PHRASAL JUDGE ERROR] {err}", file=sys.stderr)
    else:
        c1 = result.get("criterion_1", {}).get("score", "?")
        c2 = result.get("criterion_2", {}).get("score", "?")
        o = result.get("overall_score", "N/A")
        print(f"\n[PHRASAL JUDGE] C1={c1}/10  C2={c2}/10  Overall={o}/10", file=sys.stderr)
        s = result.get("summary", "")
        if s:
            print(f"[SUMMARY] {s}", file=sys.stderr)


if __name__ == "__main__":
    main()
