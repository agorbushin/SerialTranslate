#!/usr/bin/env python3
"""
Translate tier-1 (hard usable) words to Russian using ChatGPT.
Reads words from tier_1_hard_usable_words.csv and subtitle context from an SRT file.
Sends up to 10 words per API request and saves results under translations/{series}/Season {N}/{episode}/.
"""

import csv
import json
import re
import os
from pathlib import Path
from typing import List, Dict, Optional, Any
import argparse

BATCH_SIZE = 10
SUBTITLE_CONTEXT_CHARS = 6000
TRANSLATIONS_BASE_DIR = Path("translations")
SUBTITLE_BASE_DIR = Path("Subtitle")
TIER_1_CSV = "tier_1_hard_usable_words.csv"
EPISODE_INFO_JSON = "episode_info.json"


def get_subtitle_text(subtitle_path: Path) -> str:
    """Extract clean text from subtitle file for context."""
    if not subtitle_path.exists():
        return ""
    try:
        with open(subtitle_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
        content = re.sub(r"\d{2}:\d{2}:\d{2}[,.]\d{3}\s*-->\s*\d{2}:\d{2}:\d{2}[,.]\d{3}", "", content)
        content = re.sub(r"^\d+$", "", content, flags=re.MULTILINE)
        content = re.sub(r"<[^>]+>", "", content)
        content = re.sub(r"\[.*?\]", "", content)
        content = " ".join(content.split())
        return content
    except Exception as e:
        print(f"Warning: Could not read subtitle file: {e}")
        return ""


MAX_EXAMPLE_LINE_CHARS = 200


def extract_examples_from_subtitle(
    subtitle_path: Path,
    words: List[str],
    max_per_word: int = 2,
) -> Dict[str, List[str]]:
    """Extract example lines from SRT where each word appears (word-boundary match).
    Returns word -> list of cleaned subtitle lines, each truncated to MAX_EXAMPLE_LINE_CHARS."""
    examples: Dict[str, List[str]] = {w: [] for w in words}
    if not subtitle_path.exists():
        return examples
    try:
        content = subtitle_path.read_text(encoding="utf-8", errors="ignore")
        blocks = re.split(r"\n\s*\n", content)
        for block in blocks:
            lines = [line.strip() for line in block.split("\n") if line.strip()]
            if len(lines) < 3:
                continue
            text_lines = []
            for line in lines:
                if re.match(r"^\d+$", line):
                    continue
                if re.match(
                    r"\d{2}:\d{2}:\d{2}[,.]\d{3}\s*-->\s*\d{2}:\d{2}:\d{2}[,.]\d{3}", line
                ):
                    continue
                text_lines.append(line)
            if not text_lines:
                continue
            subtitle_line = " ".join(text_lines)
            subtitle_line = re.sub(r"<[^>]+>", "", subtitle_line)
            subtitle_line = re.sub(r"\[.*?\]", "", subtitle_line)
            subtitle_line = " ".join(subtitle_line.split())
            if len(subtitle_line) < 10:
                continue
            subtitle_lower = subtitle_line.lower()
            for word in words:
                if len(examples[word]) >= max_per_word:
                    continue
                pattern = r"\b" + re.escape(word) + r"\b"
                if re.search(pattern, subtitle_lower, re.IGNORECASE):
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
    season_number = episode_info.get("season_number")
    subtitle_file = episode_info.get("subtitle_file") or ""
    if not series or season_number is None or not subtitle_file:
        return None
    season_name = f"Season {season_number}"
    path = subtitle_base_dir / series / season_name / subtitle_file
    return path if path.exists() else None


def translate_batch(
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
    context = subtitle_context[:SUBTITLE_CONTEXT_CHARS] if len(subtitle_context) > SUBTITLE_CONTEXT_CHARS else subtitle_context

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
- If a word is a character name, fantasy entity, or a geographical/place name (city, region, kingdom, river, etc.), do NOT translate it: output an empty string for that key.
- Avoid generic or default dictionary sense when the context clearly suggests a more specific sense (e.g. beating in a fight context; raped as in the dialogue).
- Output ONLY a JSON object with the exact English word as key and the {target_language} translation as value. No explanation.
- Example format: {{"word1": "translation1", "word2": "translation2"}}

Respond with a single JSON object only."""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You respond only with valid JSON. No markdown, no extra text."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            timeout=60.0,
        )
        if not response or not response.choices or not response.choices[0].message:
            return {}
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
    except Exception as e:
        print(f"  API error: {e}")
        return {}


def run(
    episode_dir: Path,
    subtitle_path: Optional[Path] = None,
    api_key: Optional[str] = None,
    translations_base: Optional[Path] = None,
    subtitle_base: Optional[Path] = None,
) -> tuple[bool, Optional[str]]:
    """Load words and subtitle, translate in batches, save to translations dir.
    Returns (success, error_message). On success error_message is None."""
    episode_dir = episode_dir.resolve()
    if not episode_dir.is_dir():
        msg = f"Episode directory not found: {episode_dir}"
        print(msg)
        return False, msg

    episode_info = load_episode_info(episode_dir)
    if not episode_info:
        msg = "Could not load episode_info.json; need series, season_number, episode_number for output path."
        print(msg)
        return False, msg

    series_name = episode_info.get("series") or "Unknown"
    season_number = int(episode_info.get("season_number", 0))
    episode_number = int(episode_info.get("episode_number", 0))

    subtitle_base_dir = (subtitle_base or SUBTITLE_BASE_DIR).resolve()
    srt_path = resolve_subtitle_path(episode_dir, episode_info, subtitle_base_dir, subtitle_path)
    if not srt_path:
        msg = "Subtitle file not found for this episode."
        print(msg)
        return False, msg

    words = load_tier1_words(episode_dir)
    if not words:
        msg = "No words in tier list to translate."
        print(msg)
        return False, msg

    subtitle_text = get_subtitle_text(srt_path)
    examples = extract_examples_from_subtitle(srt_path, words, max_per_word=2)
    print(f"Loaded {len(words)} words, subtitle context {len(subtitle_text)} chars.")

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
        return False, msg

    try:
        from openai import OpenAI
    except ImportError:
        msg = "OpenAI package not installed."
        print(msg)
        return False, msg

    client = OpenAI(api_key=api_key)
    all_translations: Dict[str, str] = {}

    try:
        for i in range(0, len(words), BATCH_SIZE):
            batch = words[i : i + BATCH_SIZE]
            print(f"  Translating batch {i // BATCH_SIZE + 1}/{(len(words) + BATCH_SIZE - 1) // BATCH_SIZE} ({len(batch)} words)...")
            batch_result = translate_batch(
                client, batch, subtitle_text, series_name, examples
            )
            for w in batch:
                all_translations[w] = batch_result.get(w) or ""
    except Exception as e:
        msg = f"Translation API error: {str(e)[:80]}"
        print(msg)
        return False, msg

    base = (translations_base or TRANSLATIONS_BASE_DIR).resolve()
    from download_subtitles import get_translations_episode_dir
    out_dir = get_translations_episode_dir(base, series_name, season_number, episode_number)
    out_dir.mkdir(parents=True, exist_ok=True)

    csv_path = out_dir / "tier_1_translations.csv"
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
    (out_dir / "translation_info.json").write_text(
        json.dumps(info, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print(f"Saved {csv_path} and translation_info.json to {out_dir}/")
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
