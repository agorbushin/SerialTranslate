"""Shared subtitle cleaning for GPT context (name filter, translation)."""

import re
from pathlib import Path

TIMING_LINE_RE = re.compile(
    r"\d{2}:\d{2}:\d{2}[,.]\d{3}\s*-->\s*\d{2}:\d{2}:\d{2}[,.]\d{3}"
)


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
