#!/usr/bin/env python3
"""
Translate tier-1 (hard usable) words to Russian using ChatGPT.
Reads words from tier_1_hard_usable_words.csv and subtitle context from an SRT file.
Sends 1 word per API request (gpt-4o-mini) for maximum per-word context focus.
"""

import csv
import json
import re
import os
import asyncio
import time
from pathlib import Path
from typing import List, Dict, Optional, Any
import argparse

BATCH_SIZE = 1
MAX_CONCURRENT_BATCHES = 5
SUBTITLE_CONTEXT_CHARS = 6000
TRANSLATIONS_BASE_DIR = Path("translations")
SUBTITLE_BASE_DIR = Path("Subtitle")
TIER_1_CSV = "tier_1_hard_usable_words.csv"
EPISODE_INFO_JSON = "episode_info.json"
TIMING_LINE_RE = re.compile(
    r"\d{2}:\d{2}:\d{2}[,.]\d{3}\s*-->\s*\d{2}:\d{2}:\d{2}[,.]\d{3}"
)
INDEX_LINE_RE = re.compile(r"^\d+$")
HTML_TAG_RE = re.compile(r"<[^>]+>")
BRACKET_RE = re.compile(r"\[.*?\]")
SRT_BLOCK_SPLIT_RE = re.compile(r"\n\s*\n")


def get_subtitle_text_from_content(content: str) -> str:
    """Extract clean text from subtitle content for context."""
    try:
        content = TIMING_LINE_RE.sub("", content)
        content = re.sub(r"^\d+$", "", content, flags=re.MULTILINE)
        content = HTML_TAG_RE.sub("", content)
        content = BRACKET_RE.sub("", content)
        content = " ".join(content.split())
        return content
    except Exception as e:
        print(f"Warning: Could not clean subtitle content: {e}")
        return ""


def get_subtitle_text(subtitle_path: Path) -> str:
    """Extract clean text from subtitle file for context."""
    if not subtitle_path.exists():
        return ""
    try:
        content = subtitle_path.read_text(encoding="utf-8", errors="ignore")
        return get_subtitle_text_from_content(content)
    except Exception as e:
        print(f"Warning: Could not read subtitle file: {e}")
        return ""


MAX_EXAMPLE_LINE_CHARS = 200


def extract_examples_from_subtitle(
    subtitle_content: str,
    words: List[str],
    max_per_word: int = 2,
) -> Dict[str, List[str]]:
    """Extract example lines from SRT where each word appears (word-boundary match).
    Returns word -> list of cleaned subtitle lines, each truncated to MAX_EXAMPLE_LINE_CHARS."""
    examples: Dict[str, List[str]] = {w: [] for w in words}
    if not subtitle_content:
        return examples
    try:
        blocks = SRT_BLOCK_SPLIT_RE.split(subtitle_content)
        word_patterns: Dict[str, re.Pattern[str]] = {
            w: re.compile(r"\b" + re.escape(w) + r"\b", re.IGNORECASE) for w in words
        }
        for block in blocks:
            lines = [line.strip() for line in block.split("\n") if line.strip()]
            if len(lines) < 3:
                continue
            text_lines = []
            for line in lines:
                if INDEX_LINE_RE.match(line):
                    continue
                if TIMING_LINE_RE.match(line):
                    continue
                text_lines.append(line)
            if not text_lines:
                continue
            subtitle_line = " ".join(text_lines)
            subtitle_line = HTML_TAG_RE.sub("", subtitle_line)
            subtitle_line = BRACKET_RE.sub("", subtitle_line)
            subtitle_line = " ".join(subtitle_line.split())
            if len(subtitle_line) < 10:
                continue
            subtitle_lower = subtitle_line.lower()
            for word in words:
                if len(examples[word]) >= max_per_word:
                    continue
                if word_patterns[word].search(subtitle_lower):
                    short = (
                        subtitle_line[:MAX_EXAMPLE_LINE_CHARS]
                        if len(subtitle_line) > MAX_EXAMPLE_LINE_CHARS
                        else subtitle_line
                    )
                    if short and short not in examples[word]:
                        examples[word].append(short)
    except Exception as e:
        print(f"Warning: Could not extract examples from subtitle: {e}")
    return examples


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


def load_tier1_words(episode_dir: Path) -> List[str]:
    """Load word column from tier_1_hard_usable_words.csv."""
    path = episode_dir / TIER_1_CSV
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
    if not series or not subtitle_file:
        return None
    if episode_info.get("is_movie"):
        path = subtitle_base_dir / "Movies" / series / subtitle_file
    else:
        season_number = episode_info.get("season_number")
        if season_number is None:
            return None
        season_name = f"Season {season_number}"
        path = subtitle_base_dir / series / season_name / subtitle_file
    return path if path.exists() else None


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
                model="gpt-4o-mini",
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


def run(
    episode_dir: Path,
    subtitle_path: Optional[Path] = None,
    api_key: Optional[str] = None,
    translations_base: Optional[Path] = None,
    subtitle_base: Optional[Path] = None,
    metrics_out: Optional[Dict[str, Any]] = None,
) -> tuple[bool, Optional[str]]:
    """Load words and subtitle, translate in batches, save to translations dir.
    Returns (success, error_message). On success error_message is None."""
    started_total = time.perf_counter()
    started_phase = started_total
    timings_ms: Dict[str, int] = {
        "prepare_ms": 0,
        "primary_translate_ms": 0,
        "retry_translate_ms": 0,
        "write_outputs_ms": 0,
        "total_ms": 0,
    }

    def _set_metrics(status: str, error: Optional[str] = None) -> None:
        timings_ms["total_ms"] = int((time.perf_counter() - started_total) * 1000)
        if metrics_out is None:
            return
        metrics_out.clear()
        metrics_out.update(
            {
                "status": status,
                "error": error,
                "word_count": len(words) if "words" in locals() else 0,
                "timings_ms": dict(timings_ms),
            }
        )

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
    if not srt_path:
        msg = "Subtitle file not found for this episode."
        print(msg)
        _set_metrics("error", msg)
        return False, msg

    words = load_tier1_words(episode_dir)
    if not words:
        msg = "No words in tier list to translate."
        print(msg)
        _set_metrics("error", msg)
        return False, msg

    subtitle_content = srt_path.read_text(encoding="utf-8", errors="ignore")
    subtitle_text = get_subtitle_text_from_content(subtitle_content)
    prompt_context = (
        subtitle_text[:SUBTITLE_CONTEXT_CHARS]
        if len(subtitle_text) > SUBTITLE_CONTEXT_CHARS
        else subtitle_text
    )
    examples = extract_examples_from_subtitle(subtitle_content, words, max_per_word=3)
    print(f"Loaded {len(words)} words, subtitle context {len(subtitle_text)} chars.")
    timings_ms["prepare_ms"] = int((time.perf_counter() - started_phase) * 1000)

    api_key = api_key or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        try:
            import sys
            from pathlib import Path
            _root = Path(__file__).resolve().parent
            if str(_root) not in sys.path:
                sys.path.insert(0, str(_root))
            from telegram_bot import OPENAI_API_KEY as _bot_key
            if _bot_key and _bot_key.strip():
                api_key = _bot_key.strip()
        except Exception:
            pass
    if not api_key:
        msg = "OpenAI API key not set (OPENAI_API_KEY or telegram_bot fallback)."
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

    all_translations: Dict[str, str] = {}

    async def run_translation_passes() -> None:
        nonlocal all_translations
        async_client = AsyncOpenAI(api_key=api_key)
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_BATCHES)

        async def translate_one(
            batch_words: List[str], batch_index: int
        ) -> Dict[str, str]:
            async with semaphore:
                # One request per batch (BATCH_SIZE currently 1)
                print(
                    f"  Translating batch {batch_index}/{(len(words) + BATCH_SIZE - 1) // BATCH_SIZE}: {batch_words[0]!r}..."
                )
                return await translate_batch(
                    async_client, batch_words, prompt_context, series_name, examples
                )

        batches: List[List[str]] = [
            words[i : i + BATCH_SIZE] for i in range(0, len(words), BATCH_SIZE)
        ]
        tasks = [
            translate_one(batch_words, idx + 1) for idx, batch_words in enumerate(batches)
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for batch_words, result in zip(batches, results):
            if isinstance(result, Exception):
                continue
            for w in batch_words:
                all_translations[w] = result.get(w) or ""

        try:
            primary_started = time.perf_counter()
            empty_started = 0.0

            # Retry pass: re-translate any words that came back empty
            empty_words = [w for w in words if not all_translations.get(w, "").strip()]
            if empty_words:
                print(f"  Retry pass: {len(empty_words)} empty translations...")
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
                tasks = [retry_one(b) for b in retry_batches]
                results = await asyncio.gather(*tasks, return_exceptions=True)
                for batch_words, result in zip(retry_batches, results):
                    if isinstance(result, Exception):
                        continue
                    for w in batch_words:
                        filled = (result.get(w) or "").strip()
                        if filled:
                            all_translations[w] = filled

            timings_ms["primary_translate_ms"] = int(
                ((empty_started or time.perf_counter()) - primary_started) * 1000
            )
            if empty_started:
                timings_ms["retry_translate_ms"] = int(
                    (time.perf_counter() - empty_started) * 1000
                )
        except Exception as e:
            msg = f"Translation API error: {str(e)[:80]}"
            print(msg)
            raise RuntimeError(msg) from e
        finally:
            await async_client.close()

    try:
        asyncio.run(run_translation_passes())
    except Exception as e:
        msg = str(e) or f"Translation API error: {str(e)[:80]}"
        print(msg)
        _set_metrics("error", msg)
        return False, msg

    base = (translations_base or TRANSLATIONS_BASE_DIR).resolve()
    from download_subtitles import get_translations_episode_dir, get_translations_movie_dir
    if episode_info.get("is_movie"):
        year = int(episode_info.get("year", 0))
        out_dir = get_translations_movie_dir(base, series_name, year)
    else:
        out_dir = get_translations_episode_dir(base, series_name, season_number, episode_number)
    out_dir.mkdir(parents=True, exist_ok=True)

    csv_path = out_dir / "tier_1_translations.csv"
    started_phase = time.perf_counter()
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["word", "translation_ru"])
        for w in words:
            writer.writerow([w, all_translations.get(w, "")])

    info = {
        "series": series_name,
        "season_number": season_number,
        "episode_number": episode_number,
        "source_subtitle": srt_path.name,
        "translated_at": __import__("datetime").datetime.now().isoformat(),
    }
    if episode_info.get("is_movie"):
        info["is_movie"] = True
        info["year"] = int(episode_info.get("year", 0))
    (out_dir / "translation_info.json").write_text(
        json.dumps(info, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    timings_ms["write_outputs_ms"] = int((time.perf_counter() - started_phase) * 1000)

    print(f"Saved {csv_path} and translation_info.json to {out_dir}/")
    _set_metrics("ok")
    return True, None


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Translate tier-1 words to Russian using ChatGPT and subtitle context."
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
    args = parser.parse_args()

    ok, err = run(
        episode_dir=args.episode_dir,
        subtitle_path=args.subtitle,
        api_key=args.openai_api_key,
        translations_base=args.translations_base_dir,
        subtitle_base=args.subtitle_base_dir,
    )
    if not ok and err:
        print(f"Error: {err}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
