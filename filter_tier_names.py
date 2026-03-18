#!/usr/bin/env python3
"""
Filter tier lists: remove words that are character names or fantasy entities
using ChatGPT (OpenAI API). Based on archive telegram_bot.filter_names_and_fantasy_entities.
"""

import csv
import json
import os
import re
from pathlib import Path
from typing import Dict, List, Set, Tuple

from openai import OpenAI

# Model for name/fantasy filtering (same as archive)
NAME_FILTER_MODEL = "gpt-4o"

# Default API key: env, then fallback from project telegram_bot (which may load from archive)
def _default_api_key() -> str:
    key = os.environ.get("OPENAI_API_KEY", "")
    if key and key.strip():
        return key.strip()
    try:
        import sys
        from pathlib import Path
        _root = Path(__file__).resolve().parent
        if str(_root) not in sys.path:
            sys.path.insert(0, str(_root))
        from telegram_bot import OPENAI_API_KEY as _k
        if _k and _k.strip():
            return _k.strip()
    except Exception:
        pass
    return ""


def get_subtitle_text(subtitle_path: Path) -> str:
    """Extract clean text from SRT for context (no timestamps, no HTML)."""
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
        content = " ".join(content.split())
        return content
    except Exception as e:
        print(f"Warning: Could not read subtitle: {e}")
        return ""


def filter_names_and_fantasy_entities(
    words: List[str],
    subtitle_text: str,
    series_name: str,
    openai_client: OpenAI,
    batch_size: int = 50,
) -> Tuple[Set[str], Dict[str, str]]:
    """
    Use ChatGPT to identify character names and fantasy entities to exclude, and for
    non-excluded words assess how likely a C1-level English speaker would NOT know the word.
    Returns (excluded_set, c1_assessment) where c1_assessment[word] is "high"|"medium"|"low"
    (likelihood unknown to C1) or "name/fantasy" for excluded words.
    """
    if not words:
        return set(), {}
    all_excluded: Set[str] = set()
    c1_assessment: Dict[str, str] = {}
    for batch_start in range(0, len(words), batch_size):
        words_batch = words[batch_start : batch_start + batch_size]
        context = subtitle_text[:4000] if len(subtitle_text) > 4000 else subtitle_text
        words_text = ", ".join(f'"{w}"' for w in words_batch)
        prompt = f"""You are analyzing words from the TV series "{series_name}".

WORDS TO CHECK:
{words_text}

SUBTITLE CONTEXT:
{context[:2000]}

Return ONLY a JSON object with this structure (you MUST include every word from the list in both "exclude" and "c1_assessment"):
{{
    "exclude": ["word1", "word2", ...],
    "c1_assessment": {{
        "word1": "high" or "medium" or "low" or "name/fantasy",
        "word2": "high" or "medium" or "low" or "name/fantasy",
        ...
    }}
}}

Rules:
1. **exclude**: List only words that are fantasy/character names, geographical names (places, countries, cities, regions), or made-up (not real English). Do NOT exclude real English vocabulary (e.g. armor, commander, seagull, knight, heir, crying).

2. **c1_assessment**: For EVERY word in the list, set exactly one value:
   - **"name/fantasy"** — if the word is in "exclude" (character name, geographical name, or made-up word).
   - **"high"** — if it is real English and a C1-level speaker is LIKELY NOT to know it (specialized, rare, or advanced vocabulary).
   - **"medium"** — if it is real English and a C1 speaker MIGHT not know it (uncommon but not rare).
   - **"low"** — if it is real English and a C1 speaker is LIKELY to know it (common vocabulary).

Use C1 (Common European Framework) as reference: C1 speakers have a large vocabulary but may not know specialized, literary, or very rare words.

Return the JSON:"""

        try:
            response = openai_client.chat.completions.create(
                model=NAME_FILTER_MODEL,
                messages=[
                    {
                        "role": "system",
                        "content": "You identify fantasy names, geographical names (places, countries, cities, regions), and made-up words vs real English. Rate how likely a C1 speaker would NOT know each real English word. Respond with valid JSON only. Include every word in c1_assessment.",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
                response_format={"type": "json_object"},
            )
            result = json.loads(response.choices[0].message.content)
            batch_excluded = set(result.get("exclude", []))
            batch_c1 = result.get("c1_assessment") or {}
            for w in batch_excluded:
                all_excluded.add(w.lower() if isinstance(w, str) else str(w).lower())
            for w, val in batch_c1.items():
                if isinstance(w, str) and isinstance(val, str):
                    c1_assessment[w.strip()] = val.strip().lower()
            # Normalize keys to match original casing from words_batch where possible
            for w in words_batch:
                w_lower = w.lower()
                if w_lower not in c1_assessment and w not in c1_assessment:
                    for k, v in list(batch_c1.items()):
                        if k.lower() == w_lower:
                            c1_assessment[w] = v.strip().lower()
                            break
            print(f"  Batch {batch_start // batch_size + 1}: flagged {len(batch_excluded)} words, C1 assessment for {len(batch_c1)} words")
        except Exception as e:
            print(f"  Error filtering batch: {e}")
    return all_excluded, c1_assessment


def get_all_words_from_episode_tiers(
    episode_dir: Path,
    tier_files: List[str],
) -> List[str]:
    """Collect unique words from tier CSVs (word column)."""
    words = []
    seen = set()
    for name in tier_files:
        path = episode_dir / name
        if not path.exists():
            continue
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            if "word" not in (reader.fieldnames or []):
                continue
            for row in reader:
                w = (row.get("word") or "").strip()
                if w and w.lower() not in seen:
                    seen.add(w.lower())
                    words.append(w)
    return words


def filter_tier_csv(
    tier_path: Path,
    excluded_words: Set[str],
) -> int:
    """
    Remove rows whose word (lowercase) is in excluded_words. Overwrites the file.
    Returns number of rows removed.
    """
    excluded_lower = {w.lower() for w in excluded_words}
    rows = []
    fieldnames = None
    removed = 0
    with open(tier_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        for row in reader:
            w = (row.get("word") or "").strip().lower()
            if w in excluded_lower:
                removed += 1
                continue
            rows.append(row)
    if fieldnames is None:
        return 0
    with open(tier_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return removed


# Default tier filenames in episode dir
DEFAULT_TIER_FILES = [
    "tier_1_hard_usable_words.csv",
    "tier_2_random_words.csv",
    "tier_3_common_words.csv",
    "tier_4_rare_in_series.csv",
    "tier_5_filtered_words.csv",
]


def filter_episode_tier_lists(
    episode_dir: Path,
    subtitle_path: Path,
    series_name: str,
    api_key: str,
    tier_files: List[str],
) -> Dict[str, int]:
    """
    Remove name/fantasy words from all tier CSVs in episode_dir using ChatGPT.
    Returns dict tier_filename -> number of rows removed.
    """
    episode_dir = Path(episode_dir)
    subtitle_path = Path(subtitle_path)
    words = get_all_words_from_episode_tiers(episode_dir, tier_files)
    if not words:
        print("No words found in tier files.")
        return {}
    subtitle_text = get_subtitle_text(subtitle_path)
    if not subtitle_text:
        print("Warning: No subtitle context; filtering may be less accurate.")
    client = OpenAI(api_key=api_key)
    print(f"Checking {len(words)} words with ChatGPT for names/fantasy entities...")
    excluded, c1_assessment = filter_names_and_fantasy_entities(
        words, subtitle_text, series_name, client
    )
    print(f"Excluding {len(excluded)} words: {sorted(excluded)}")
    counts = {}
    for name in tier_files:
        path = episode_dir / name
        if path.exists():
            n = filter_tier_csv(path, excluded)
            counts[name] = n
            if n:
                print(f"  {name}: removed {n} rows")
    if excluded or c1_assessment:
        audit_path = episode_dir / "excluded_names_fantasy.json"
        payload: Dict = {"excluded": sorted(excluded), "series": series_name}
        if c1_assessment:
            payload["c1_assessment"] = c1_assessment
        audit_path.write_text(
            json.dumps(payload, indent=2),
            encoding="utf-8",
        )
        print(f"  Wrote {audit_path.name}")
    return counts


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(
        description="Remove character names and fantasy entities from tier lists using ChatGPT"
    )
    parser.add_argument(
        "episode_dir",
        type=Path,
        help="Episode directory (e.g. Tier_lists/Game of Thrones/Season 2/2)",
    )
    parser.add_argument(
        "--subtitle",
        "-s",
        type=Path,
        required=True,
        help="Path to subtitle SRT file",
    )
    parser.add_argument(
        "--series",
        type=str,
        required=True,
        help="Series name (e.g. Game of Thrones)",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="OpenAI API key (default: OPENAI_API_KEY env)",
    )
    args = parser.parse_args()
    api_key = args.api_key or _default_api_key()
    if not api_key:
        print("Error: Set OPENAI_API_KEY or pass --api-key")
        raise SystemExit(1)
    base = Path(__file__).resolve().parent
    episode_dir = base / args.episode_dir if not args.episode_dir.is_absolute() else args.episode_dir
    subtitle_path = base / args.subtitle if not args.subtitle.is_absolute() else args.subtitle
    if not episode_dir.exists():
        print(f"Error: Episode dir not found: {episode_dir}")
        raise SystemExit(1)
    if not subtitle_path.exists():
        print(f"Error: Subtitle not found: {subtitle_path}")
        raise SystemExit(1)
    filter_episode_tier_lists(
        episode_dir,
        subtitle_path,
        args.series,
        api_key,
        DEFAULT_TIER_FILES,
    )
    print("Done.")


if __name__ == "__main__":
    main()
