#!/usr/bin/env python3
"""
LLM judge for idiomatic_expressions.csv (translations + validity).

Parallel to phrasal_judge.py; does not modify project data files.

Usage:
    python idiomatic_judge.py --output-dir path/to/episode --subtitle path/to.srt
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

from translation_judge import (  # reuse key loading, subtitle text
    JUDGE_MODEL,
    _get_subtitle_text,
    _load_api_key,
)

IDIOMATIC_CSV = "idiomatic_expressions.csv"
EXTRACTION_INFO_JSON = "idiomatic_extraction_info.json"

SUBTITLE_CONTEXT_CHARS = 4000
MAX_EXAMPLE_LINE_CHARS = 220
EXAMPLES_PER_PHRASE = 2


def _phrase_boundary_pattern(phrase: str):
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
        print(f"  Warning: could not extract idiom examples: {e}")
    return examples


def load_idiomatic_list(output_dir: Path) -> Tuple[List[Dict[str, str]], Dict[str, Any]]:
    csv_path = output_dir / IDIOMATIC_CSV
    if not csv_path.exists():
        raise FileNotFoundError(f"Idiomatic CSV not found: {csv_path}")

    pairs: List[Dict[str, str]] = []
    with open(csv_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            expr = (row.get("expression") or "").strip()
            if expr:
                pairs.append(
                    {
                        "expression": expr,
                        "translation_ru": (row.get("translation") or "").strip(),
                        "example": (row.get("example") or "").strip(),
                        "frequency": (row.get("frequency") or "").strip(),
                    }
                )

    info_path = output_dir / EXTRACTION_INFO_JSON
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
        ex = p["expression"]
        tr = p["translation_ru"] or "(empty)"
        fr = p.get("frequency") or ""
        extra = f" [freq={fr}]" if fr else ""
        lines.append(f'  "{ex}" → "{tr}"{extra}')
    list_block = "\n".join(lines)

    ex_lines = []
    for p in pairs:
        ex = p["expression"]
        exs = examples.get(ex, [])
        if exs:
            for line in exs:
                ex_lines.append(f'  "{ex}": {line}')
        else:
            ex_lines.append(f'  "{ex}": (no subtitle line matched)')
    examples_block = "\n".join(ex_lines)

    context_snippet = (
        subtitle_context[:SUBTITLE_CONTEXT_CHARS]
        if len(subtitle_context) > SUBTITLE_CONTEXT_CHARS
        else subtitle_context
    )

    return f"""You are an expert evaluator of English idiomatic / formulaic expressions
and their Russian translations for learners watching a TV series episode.

SERIES: {series_name}, Season {season}, Episode {episode}

IDIOM LIST (English → Russian translation):
{list_block}

SUBTITLE EXAMPLES (lines where each expression appears, when found):
{examples_block}

GENERAL SUBTITLE CONTEXT (first portion of episode dialogue):
{context_snippet}

---
Evaluate this output against TWO criteria. Reason step by step for each before scoring.

=== CRITERION 1: Translation completeness & contextual correctness ===
For every expression–translation pair:
- Is the Russian translation present (not empty, not "N/A", not a dash, not left in English)?
- Is the gloss correct for how the expression is used IN THIS EPISODE? Use examples and context.
- Flag: missing translation, wrong sense, transliteration instead of real Russian, overly generic gloss.

Score 0–10 (10 = all translations correct and complete; 0 = all wrong or missing).

=== CRITERION 2: Genuine idiomatic / formulaic expressions ===
For every English SOURCE string:
- Is it a real idiom, discourse formula, or strong opaque collocation worth studying — NOT plain compositional grammar?
- Reject high-frequency transparent chunks, accidental n-grams, or standard phrasal verbs that belong in a separate phrasal-verb list.
- The list should favor **repeated** episode-specific formulas that are still general English.

Score 0–10 (10 = every entry is a valid idiom-type unit; 0 = most are false positives).

---
Return ONLY valid JSON with EXACTLY this structure (no markdown, no extra text):
{{
  "criterion_1": {{
    "score": <integer 0-10>,
    "reasoning": "<detailed step-by-step reasoning>",
    "issues": [
      {{"expression": "<english>", "translation": "<russian>", "issue": "<description>"}}
    ]
  }},
  "criterion_2": {{
    "score": <integer 0-10>,
    "reasoning": "<detailed reasoning>",
    "invalid_expressions": [
      {{"expression": "<english>", "reason": "<why not a useful idiom>"}}
    ]
  }},
  "overall_score": <float: average of criterion_1 and criterion_2 scores, 1 decimal>,
  "summary": "<2-3 sentence overall assessment>",
  "improvement_suggestions": [
    "<concrete suggestion for the extraction pipeline or prompts>"
  ]
}}"""


def judge_idiomatic_output(
    output_dir: Path,
    subtitle_path: Optional[Path] = None,
    api_key: Optional[str] = None,
    model: str = JUDGE_MODEL,
) -> Dict[str, Any]:
    output_dir = Path(output_dir).resolve()
    result: Dict[str, Any] = {
        "output_dir": str(output_dir),
        "judged_at": datetime.now().isoformat(),
        "model": model,
        "judge_kind": "idiomatic_expressions",
    }

    try:
        pairs, info = load_idiomatic_list(output_dir)
    except FileNotFoundError as e:
        result["error"] = str(e)
        return result

    if not pairs:
        result["error"] = "No rows in idiomatic_expressions.csv."
        return result

    series_name = str(info.get("series") or "Unknown Series")
    season = int(info.get("season_number", 1))
    episode = int(info.get("episode_number", 1))
    result["series"] = series_name
    result["season"] = season
    result["episode"] = episode
    result["expression_count"] = len(pairs)

    subtitle_context = ""
    examples: Dict[str, List[str]] = {}
    phrases = [p["expression"] for p in pairs]
    if subtitle_path and Path(subtitle_path).exists():
        result["subtitle_used"] = str(subtitle_path)
        subtitle_context = _get_subtitle_text(Path(subtitle_path))
        examples = _extract_examples_phrases(Path(subtitle_path), phrases)
    else:
        result["subtitle_used"] = None
        print(
            f"  Warning: no subtitle for judge; using list + stored examples only.",
            file=sys.stderr,
        )

    prompt = _build_prompt(pairs, series_name, season, episode, subtitle_context, examples)

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
    print(
        f"  Calling {model} idiomatic judge for {series_name} S{season}E{episode} "
        f"({len(pairs)} expressions)...",
        file=sys.stderr,
    )

    response = None
    last_error: Optional[str] = None
    for attempt in range(4):
        if attempt > 0:
            wait = 30 * (2 ** (attempt - 1))
            print(f"  Idiomatic judge retry {attempt}/3 after {wait}s...", file=sys.stderr)
            time.sleep(wait)
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a rigorous evaluator of idiomatic expressions and Russian glosses. "
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

    for key in (
        "criterion_1",
        "criterion_2",
        "overall_score",
        "summary",
        "improvement_suggestions",
    ):
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
        description="LLM judge for idiomatic_expressions.csv (read-only)."
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Directory containing idiomatic_expressions.csv",
    )
    parser.add_argument("--subtitle", type=Path, default=None)
    parser.add_argument("--model", type=str, default=JUDGE_MODEL)
    parser.add_argument("--openai-api-key", type=str, default=None)
    parser.add_argument("--write-report", type=Path, default=None)
    args = parser.parse_args()

    base = Path(__file__).resolve().parent
    out_dir = (
        base / args.output_dir if not args.output_dir.is_absolute() else args.output_dir
    )
    sub = None
    if args.subtitle:
        sub = base / args.subtitle if not args.subtitle.is_absolute() else args.subtitle

    result = judge_idiomatic_output(out_dir, subtitle_path=sub, api_key=args.openai_api_key, model=args.model)

    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.write_report:
        wr = base / args.write_report if not args.write_report.is_absolute() else args.write_report
        wr.parent.mkdir(parents=True, exist_ok=True)
        wr.write_text(text, encoding="utf-8")
        print(f"Idiomatic judge report saved to: {wr}")
    else:
        print(text)

    err = result.get("error", "")
    if err:
        print(f"\n[IDIOMATIC JUDGE ERROR] {err}", file=sys.stderr)
    else:
        c1 = result.get("criterion_1", {}).get("score", "?")
        c2 = result.get("criterion_2", {}).get("score", "?")
        o = result.get("overall_score", "N/A")
        print(f"\n[IDIOMATIC JUDGE] C1={c1}/10  C2={c2}/10  Overall={o}/10", file=sys.stderr)
        s = result.get("summary", "")
        if s:
            print(f"[SUMMARY] {s}", file=sys.stderr)


if __name__ == "__main__":
    main()
