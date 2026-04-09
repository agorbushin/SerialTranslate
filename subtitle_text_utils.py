"""Shared subtitle cleaning for GPT context (name filter, translation, judges)."""

import re
from pathlib import Path
from typing import Dict, List

TIMING_LINE_RE = re.compile(
    r"\d{2}:\d{2}:\d{2}[,.]\d{3}\s*-->\s*\d{2}:\d{2}:\d{2}[,.]\d{3}"
)

_INDEX_LINE_RE = re.compile(r"^\d+$")
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_BRACKET_RE = re.compile(r"\[.*?\]")
_SRT_BLOCK_SPLIT_RE = re.compile(r"\n\s*\n")


def get_subtitle_text_from_content(content: str) -> str:
    """Strip timing lines, indices, HTML, brackets; collapse whitespace."""
    try:
        content = TIMING_LINE_RE.sub("", content)
        content = re.sub(r"^\d+$", "", content, flags=re.MULTILINE)
        content = re.sub(r"<[^>]+>", "", content)
        content = re.sub(r"\[.*?\]", "", content)
        content = " ".join(content.split())
        return content
    except Exception:
        return ""


def get_subtitle_text(subtitle_path: Path) -> str:
    """Read file and return cleaned text for LLM context."""
    if not subtitle_path.exists():
        return ""
    try:
        content = subtitle_path.read_text(encoding="utf-8", errors="ignore")
        return get_subtitle_text_from_content(content)
    except Exception:
        return ""


def extract_word_examples_from_srt_content(
    subtitle_content: str,
    words: List[str],
    *,
    max_per_word: int = 2,
    max_line_chars: int = 200,
    min_subtitle_line_len: int = 10,
) -> Dict[str, List[str]]:
    """Extract example dialogue lines from raw SRT where each word appears (word-boundary match)."""
    examples: Dict[str, List[str]] = {w: [] for w in words}
    if not subtitle_content:
        return examples
    try:
        blocks = _SRT_BLOCK_SPLIT_RE.split(subtitle_content)
        word_patterns: Dict[str, re.Pattern[str]] = {
            w: re.compile(r"\b" + re.escape(w) + r"\b", re.IGNORECASE) for w in words
        }
        for block in blocks:
            lines = [line.strip() for line in block.split("\n") if line.strip()]
            if len(lines) < 3:
                continue
            text_lines: List[str] = []
            for line in lines:
                if _INDEX_LINE_RE.match(line):
                    continue
                if TIMING_LINE_RE.match(line):
                    continue
                text_lines.append(line)
            if not text_lines:
                continue
            subtitle_line = " ".join(text_lines)
            subtitle_line = _HTML_TAG_RE.sub("", subtitle_line)
            subtitle_line = _BRACKET_RE.sub("", subtitle_line)
            subtitle_line = " ".join(subtitle_line.split())
            if len(subtitle_line) < min_subtitle_line_len:
                continue
            subtitle_lower = subtitle_line.lower()
            for word in words:
                if len(examples[word]) >= max_per_word:
                    continue
                if word_patterns[word].search(subtitle_lower):
                    short = (
                        subtitle_line[:max_line_chars]
                        if len(subtitle_line) > max_line_chars
                        else subtitle_line
                    )
                    if short and short not in examples[word]:
                        examples[word].append(short)
    except Exception as e:
        print(f"Warning: Could not extract examples from subtitle: {e}")
    return examples


def extract_word_examples_from_srt_path(
    subtitle_path: Path,
    words: List[str],
    *,
    max_per_word: int = 2,
    max_line_chars: int = 200,
    min_subtitle_line_len: int = 10,
) -> Dict[str, List[str]]:
    """Load SRT from disk and extract per-word example lines (same rules as extract_word_examples_from_srt_content)."""
    if not subtitle_path.exists():
        return {w: [] for w in words}
    try:
        content = subtitle_path.read_text(encoding="utf-8", errors="ignore")
    except Exception as e:
        print(f"  Warning: could not read subtitle: {e}")
        return {w: [] for w in words}
    return extract_word_examples_from_srt_content(
        content,
        words,
        max_per_word=max_per_word,
        max_line_chars=max_line_chars,
        min_subtitle_line_len=min_subtitle_line_len,
    )
