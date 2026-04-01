#!/usr/bin/env python3
"""
Filter tier lists: remove words that are character names or fantasy entities
using ChatGPT (OpenAI API). Based on archive telegram_bot.filter_names_and_fantasy_entities.
"""

import asyncio
import csv
import json
import os
import re
from pathlib import Path
from typing import Dict, List, Set, Tuple, Union

from openai import AsyncOpenAI, OpenAI

# Model for name/fantasy filtering
NAME_FILTER_MODEL = "gpt-4o-mini"
MAX_CONCURRENT_BATCHES = 5

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
    from subtitle_text_utils import get_subtitle_text as _gst

    return _gst(subtitle_path)


def _build_filter_prompt(words_batch: List[str], subtitle_text: str, series_name: str) -> str:
    """Build the prompt for a single batch of words."""
    context = subtitle_text[:4000] if len(subtitle_text) > 4000 else subtitle_text
    words_text = ", ".join(f'"{w}"' for w in words_batch)
    return f"""You are analyzing words from the TV series "{series_name}".

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

1. **exclude**: List words that must be removed from a vocabulary learning list:
   - Character names (e.g. "walter", "tyrion", "escobar")
   - Real people's names (e.g. "nixon", "pinochet")
   - Geographical names: countries, cities, regions (e.g. "colombia", "peru", "aspen", "brooklyn")
   - Brand names (e.g. "twitter", "prozac")
   - Made-up/non-English words not in a standard English dictionary
   Do NOT exclude real English vocabulary even if it sounds foreign (e.g. "armor", "smuggling", "seagull").

2. **c1_assessment**: For EVERY word, assign exactly one value.
   C1 (CEFR) speakers are advanced — they have a large active vocabulary but may not know rare,
   specialized, or literary words. Use these benchmarks:

   - **"high"** — genuinely advanced; a C1 speaker would LIKELY NOT know it.
     Examples: "laconic", "usurp", "nefarious", "skulk", "obsequious", "phosphine",
               "aberrant", "decommission", "trafficker", "contraband", "volumetric"

   - **"medium"** — uncommon but not rare; a C1 speaker MIGHT not know it.
     Examples: "smuggling", "bookmaker", "blinder", "diagnostic", "eggplant", "emerald"

   - **"low"** — common; a C1 speaker almost certainly knows it. DO NOT use "low" sparingly —
     be strict. If in doubt between "low" and "medium", choose "low".
     Examples: "loved", "stopped", "sitting", "dude", "garbage", "elevator", "mommy",
               "fake", "lying", "drunk", "cop", "punch", "drove", "tired", "smiled",
               "eating", "running", "shooting", "talking", "crying", "listening"

   - **"name/fantasy"** — if the word is in "exclude".

Return the JSON:"""


def _build_cefr_triage_prompt(words_batch: List[str], subtitle_text: str, series_name: str) -> str:
    context = subtitle_text[:4000] if len(subtitle_text) > 4000 else subtitle_text
    words_text = ", ".join(f'"{w}"' for w in words_batch)
    return f"""You assign coarse English learning difficulty for words from "{series_name}".

WORDS (each must appear as a key in cefr_coarse):
{words_text}

SUBTITLE CONTEXT:
{context[:2000]}

Return ONLY a JSON object:
{{"cefr_coarse": {{"word1": "c", "word2": "b", ...}}}}

Rules for cefr_coarse values (lowercase only: "c", "b", "a"):
- **c** — C-level: advanced / specialized / literary or clearly low-frequency for a B learner.
- **b** — B-level: general intermediate or upper-intermediate vocabulary.
- **a** — A-level: basic everyday words a pre-intermediate learner likely knows.

Include every word from the list exactly once as a key. Use only "c", "b", or "a" as values.
"""


async def assign_coarse_cefr_for_unlabeled_async(
    words: List[str],
    subtitle_text: str,
    series_name: str,
    async_client: AsyncOpenAI,
    batch_size: int = 20,
    max_concurrent: int = MAX_CONCURRENT_BATCHES,
) -> Dict[str, str]:
    """GPT labels for lemmas missing xlsx CEFR. Returns word -> 'c'|'b'|'a' (lowercase)."""
    if not words:
        return {}
    out: Dict[str, str] = {}
    semaphore = asyncio.Semaphore(max_concurrent)

    async def process_batch(words_batch: List[str], batch_num: int) -> Dict[str, str]:
        async with semaphore:
            prompt = _build_cefr_triage_prompt(words_batch, subtitle_text, series_name)
            try:
                response = await async_client.chat.completions.create(
                    model=NAME_FILTER_MODEL,
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "You assign coarse CEFR-style difficulty labels c, b, or a for English words. "
                                "Respond with valid JSON only, one object with key cefr_coarse mapping each "
                                "input word to exactly one of c, b, a."
                            ),
                        },
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.1,
                    response_format={"type": "json_object"},
                )
                raw = (response.choices[0].message.content or "").strip()
                result = json.loads(raw)
                batch_map = result.get("cefr_coarse") or {}
                print(
                    f"  CEFR triage batch {batch_num}: labeled {len(batch_map)} words"
                )
                normalized: Dict[str, str] = {}
                for k, v in batch_map.items():
                    if not isinstance(k, str) or not isinstance(v, str):
                        continue
                    val = v.strip().lower()
                    if val in ("c", "b", "a"):
                        normalized[k.strip()] = val
                return normalized
            except Exception as e:
                print(f"  Error CEFR triage batch {batch_num}: {e}")
                return {}

    batches = [
        (words[i : i + batch_size], i // batch_size + 1)
        for i in range(0, len(words), batch_size)
    ]
    results = await asyncio.gather(*[
        process_batch(wb, num) for wb, num in batches
    ])
    for (words_batch, _), batch_map in zip(batches, results):
        for w in words_batch:
            w_lower = w.lower()
            if w in batch_map:
                out[w] = batch_map[w]
            elif w_lower in batch_map:
                out[w] = batch_map[w_lower]
            else:
                for k, v in batch_map.items():
                    if k.lower() == w_lower:
                        out[w] = v
                        break
    return out


def assign_coarse_cefr_for_unlabeled(
    words: List[str],
    subtitle_text: str,
    series_name: str,
    openai_client: Union[OpenAI, AsyncOpenAI],
    batch_size: int = 20,
) -> Dict[str, str]:
    """Sync entry: batched GPT coarse C/B/A for unlabeled lemmas."""
    if not words:
        return {}
    if isinstance(openai_client, AsyncOpenAI):
        return asyncio.run(
            assign_coarse_cefr_for_unlabeled_async(
                words, subtitle_text, series_name, openai_client, batch_size
            )
        )
    api_key = getattr(openai_client, "api_key", None)
    if not api_key:
        raise ValueError("OpenAI client must have api_key for CEFR triage")
    async_client = AsyncOpenAI(api_key=api_key)

    async def _run() -> Dict[str, str]:
        try:
            return await assign_coarse_cefr_for_unlabeled_async(
                words, subtitle_text, series_name, async_client, batch_size
            )
        finally:
            await async_client.close()

    return asyncio.run(_run())


async def filter_names_and_fantasy_entities_async(
    words: List[str],
    subtitle_text: str,
    series_name: str,
    async_client: AsyncOpenAI,
    batch_size: int = 20,
    max_concurrent: int = MAX_CONCURRENT_BATCHES,
) -> Tuple[Set[str], Dict[str, str]]:
    """
    Async version: Use ChatGPT to identify character names and fantasy entities.
    Processes batches in parallel with a semaphore for rate limiting.
    Returns (excluded_set, c1_assessment).
    """
    if not words:
        return set(), {}
    all_excluded: Set[str] = set()
    c1_assessment: Dict[str, str] = {}
    semaphore = asyncio.Semaphore(max_concurrent)

    async def process_batch(words_batch: List[str], batch_num: int) -> Tuple[Set[str], Dict[str, str]]:
        async with semaphore:
            prompt = _build_filter_prompt(words_batch, subtitle_text, series_name)
            try:
                response = await async_client.chat.completions.create(
                    model=NAME_FILTER_MODEL,
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "You identify names, geographical names, brand names, and made-up words "
                                "that should be excluded from English vocabulary learning lists. "
                                "For real English words, you rate whether a C1 (CEFR advanced) speaker "
                                "would likely know them: 'high' = probably unknown, 'medium' = possibly unknown, "
                                "'low' = almost certainly known. Be strict: everyday verbs, common nouns, and "
                                "basic adjectives are always 'low'. Respond with valid JSON only."
                            ),
                        },
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.1,
                    response_format={"type": "json_object"},
                )
                result = json.loads(response.choices[0].message.content)
                batch_excluded = set(result.get("exclude", []))
                batch_c1 = result.get("c1_assessment") or {}
                print(f"  Batch {batch_num}: flagged {len(batch_excluded)} words, C1 assessment for {len(batch_c1)} words")
                return batch_excluded, batch_c1
            except Exception as e:
                print(f"  Error filtering batch {batch_num}: {e}")
                return set(), {}

    batches = [
        (words[i : i + batch_size], i // batch_size + 1)
        for i in range(0, len(words), batch_size)
    ]
    results = await asyncio.gather(*[
        process_batch(words_batch, batch_num)
        for words_batch, batch_num in batches
    ])

    for (words_batch, _), (batch_excluded, batch_c1) in zip(batches, results):
        for w in batch_excluded:
            all_excluded.add(w.lower() if isinstance(w, str) else str(w).lower())
        for w, val in batch_c1.items():
            if isinstance(w, str) and isinstance(val, str):
                c1_assessment[w.strip()] = val.strip().lower()
        for w in words_batch:
            w_lower = w.lower()
            if w_lower not in c1_assessment and w not in c1_assessment:
                for k, v in list(batch_c1.items()):
                    if k.lower() == w_lower:
                        c1_assessment[w] = v.strip().lower()
                        break
    return all_excluded, c1_assessment


def filter_names_and_fantasy_entities(
    words: List[str],
    subtitle_text: str,
    series_name: str,
    openai_client: Union[OpenAI, AsyncOpenAI],
    batch_size: int = 20,
) -> Tuple[Set[str], Dict[str, str]]:
    """
    Use ChatGPT to identify character names and fantasy entities to exclude, and for
    non-excluded words assess how likely a C1-level English speaker would NOT know the word.
    Returns (excluded_set, c1_assessment) where c1_assessment[word] is "high"|"medium"|"low"
    (likelihood unknown to C1) or "name/fantasy" for excluded words.

    Processes batches in parallel when given an AsyncOpenAI client; otherwise uses
    asyncio.run() with AsyncOpenAI created from the sync client's api_key.
    """
    if not words:
        return set(), {}
    if isinstance(openai_client, AsyncOpenAI):
        return asyncio.run(filter_names_and_fantasy_entities_async(
            words, subtitle_text, series_name, openai_client, batch_size
        ))
    api_key = getattr(openai_client, "api_key", None)
    if not api_key:
        raise ValueError("OpenAI client must have api_key for parallel filtering")
    async_client = AsyncOpenAI(api_key=api_key)

    async def _run() -> Tuple[Set[str], Dict[str, str]]:
        try:
            return await filter_names_and_fantasy_entities_async(
                words, subtitle_text, series_name, async_client, batch_size
            )
        finally:
            await async_client.close()

    return asyncio.run(_run())


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
    "tier_4_rare_c_words.csv",
    "tier_4_rare_b_words.csv",
    "tier_5_filtered_words.csv",
    "tier_b1_words.csv",
    "tier_b2_words.csv",
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
