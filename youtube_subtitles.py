#!/usr/bin/env python3
"""
Download YouTube captions and save them as SRT files for the existing analyzer.

This module intentionally keeps YouTube as an ingestion layer: once captions are on
disk, subtitle_analyzer.py and translate_tier_translations.py do the normal work.
"""

from __future__ import annotations

import html
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from download_subtitles import get_youtube_subtitle_path

YOUTUBE_URL_RE = re.compile(
    r"(?:https?://)?(?:www\.|m\.)?"
    r"(?:youtube\.com/(?:watch\?v=|shorts/|embed/)|youtu\.be/)"
    r"(?P<id>[A-Za-z0-9_-]{6,})"
)


@dataclass(frozen=True)
class YouTubeSubtitleResult:
    subtitle_path: Path
    video_title: str
    video_id: str
    webpage_url: str
    language: str
    is_auto_generated: bool
    channel: str = ""


def is_youtube_url(text: str) -> bool:
    """True when text looks like a YouTube watch/short/youtu.be URL."""
    return bool(YOUTUBE_URL_RE.search(text or ""))


def extract_youtube_video_id(text: str) -> str:
    match = YOUTUBE_URL_RE.search(text or "")
    return match.group("id") if match else ""


def _yt_dlp_command() -> Optional[List[str]]:
    exe = shutil.which("yt-dlp")
    if exe:
        return [exe]
    if importlib.util.find_spec("yt_dlp") is not None:
        return [sys.executable, "-m", "yt_dlp"]
    python3 = shutil.which("python3")
    if python3:
        proc = subprocess.run(
            [python3, "-c", "import yt_dlp"],
            text=True,
            capture_output=True,
            check=False,
        )
        if proc.returncode == 0:
            return [python3, "-m", "yt_dlp"]
    return None


def _yt_dlp_available() -> bool:
    return importlib.util.find_spec("yt_dlp") is not None or _yt_dlp_command() is not None


def _require_yt_dlp() -> None:
    if not _yt_dlp_available():
        raise RuntimeError(
            "yt-dlp is required for YouTube captions. Install it with: pip install yt-dlp"
        )


def _select_caption(
    info: Dict[str, Any],
    preferred_languages: Iterable[str],
) -> Tuple[str, bool]:
    subtitles = info.get("subtitles") or {}
    automatic = info.get("automatic_captions") or {}
    preferred = [lang for lang in preferred_languages if lang]
    for lang in preferred:
        if lang in subtitles:
            return lang, False
    for lang in preferred:
        if lang in automatic:
            return lang, True
    for lang in sorted(subtitles):
        return lang, False
    for lang in sorted(automatic):
        return lang, True
    raise RuntimeError("No captions found for this YouTube video.")


def _extract_info_with_python_api(url: str) -> Dict[str, Any]:
    from yt_dlp import YoutubeDL

    opts = {
        "quiet": True,
        "skip_download": True,
        "no_warnings": True,
    }
    with YoutubeDL(opts) as ydl:
        return ydl.extract_info(url, download=False)


def _download_caption_with_python_api(
    url: str,
    temp_dir: Path,
    language: str,
    auto_subs: bool,
) -> Dict[str, Any]:
    from yt_dlp import YoutubeDL

    opts = {
        "quiet": True,
        "skip_download": True,
        "no_warnings": True,
        "outtmpl": str(temp_dir / "%(id)s.%(ext)s"),
        "subtitleslangs": [language],
        "subtitlesformat": "vtt/srt/best",
        "writesubtitles": not auto_subs,
        "writeautomaticsub": auto_subs,
    }
    with YoutubeDL(opts) as ydl:
        return ydl.extract_info(url, download=True)


def _extract_info_with_cli(url: str) -> Dict[str, Any]:
    cmd = _yt_dlp_command()
    if not cmd:
        raise RuntimeError("yt-dlp executable not found.")
    proc = subprocess.run(
        [*cmd, "--dump-single-json", "--skip-download", "--no-warnings", url],
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "yt-dlp metadata failed").strip())
    return json.loads(proc.stdout)


def _download_caption_with_cli(
    url: str,
    temp_dir: Path,
    language: str,
    auto_subs: bool,
) -> Dict[str, Any]:
    cmd = _yt_dlp_command()
    if not cmd:
        raise RuntimeError("yt-dlp executable not found.")
    args = [
        *cmd,
        "--skip-download",
        "--no-warnings",
        "--sub-langs",
        language,
        "--sub-format",
        "vtt/srt/best",
        "-o",
        str(temp_dir / "%(id)s.%(ext)s"),
    ]
    args.append("--write-auto-subs" if auto_subs else "--write-subs")
    args.append(url)
    proc = subprocess.run(args, text=True, capture_output=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "yt-dlp subtitle download failed").strip())
    return _extract_info_with_cli(url)


def _caption_files(temp_dir: Path, video_id: str) -> List[Path]:
    files = [p for p in temp_dir.glob(f"{video_id}.*") if p.is_file()]
    return sorted(
        [p for p in files if p.suffix.lower() in {".srt", ".vtt"}],
        key=lambda p: (p.suffix.lower() != ".srt", p.name),
    )


def _vtt_timestamp_to_srt(timestamp: str) -> str:
    ts = timestamp.strip()
    if re.match(r"^\d{1,2}:\d{2}\.\d{3}$", ts):
        ts = "00:" + ts
    elif re.match(r"^\d{1,2}\.\d{3}$", ts):
        ts = "00:00:" + ts
    return ts.replace(".", ",")


def _clean_caption_text(text: str) -> str:
    text = re.sub(r"<\d{1,2}:\d{2}:\d{2}\.\d{3}>", "", text)
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text).strip()


def vtt_to_srt(vtt_content: str) -> str:
    """Convert a plain WebVTT caption file into SRT text."""
    lines = vtt_content.replace("\ufeff", "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    blocks: List[str] = []
    cue_text: List[str] = []
    start = end = ""

    def flush() -> None:
        nonlocal start, end, cue_text
        if start and end and cue_text:
            text = "\n".join(t for t in (_clean_caption_text(x) for x in cue_text) if t)
            if text:
                blocks.append(
                    f"{len(blocks) + 1}\n{_vtt_timestamp_to_srt(start)} --> {_vtt_timestamp_to_srt(end)}\n{text}"
                )
        start = end = ""
        cue_text = []

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            flush()
            continue
        if line == "WEBVTT" or line.startswith(("NOTE", "STYLE", "REGION", "Kind:", "Language:")):
            continue
        if "-->" in line:
            flush()
            left, right = line.split("-->", 1)
            start = left.strip()
            end = right.strip().split()[0]
            continue
        if start and end:
            cue_text.append(raw_line.strip())

    flush()
    return "\n\n".join(blocks).strip() + ("\n" if blocks else "")


def _write_srt_from_caption(caption_path: Path, output_path: Path) -> None:
    content = caption_path.read_text(encoding="utf-8", errors="ignore")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if caption_path.suffix.lower() == ".srt":
        output_path.write_text(content, encoding="utf-8")
        return
    srt = vtt_to_srt(content)
    if not srt.strip():
        raise RuntimeError("Downloaded captions were empty after VTT conversion.")
    output_path.write_text(srt, encoding="utf-8")


def download_youtube_subtitle(
    url: str,
    *,
    base_dir: Path,
    preferred_languages: Optional[Iterable[str]] = None,
    overwrite: bool = False,
) -> YouTubeSubtitleResult:
    """
    Download captions for a YouTube URL and save them as an SRT file.

    Manual captions are preferred over auto-generated captions. If English is not
    available, the first available caption language is used.
    """
    _require_yt_dlp()
    preferred = list(preferred_languages or ("en", "en-US", "en-GB"))
    try:
        info = _extract_info_with_python_api(url)
        use_python_api = True
    except Exception:
        info = _extract_info_with_cli(url)
        use_python_api = False

    video_id = str(info.get("id") or extract_youtube_video_id(url) or "").strip()
    if not video_id:
        raise RuntimeError("Could not determine YouTube video id.")
    title = str(info.get("title") or f"YouTube {video_id}").strip()
    webpage_url = str(info.get("webpage_url") or url).strip()
    channel = str(info.get("channel") or info.get("uploader") or "").strip()
    language, is_auto = _select_caption(info, preferred)
    output_path = get_youtube_subtitle_path(base_dir, title, video_id)
    if output_path.exists() and not overwrite:
        return YouTubeSubtitleResult(
            subtitle_path=output_path,
            video_title=title,
            video_id=video_id,
            webpage_url=webpage_url,
            language=language,
            is_auto_generated=is_auto,
            channel=channel,
        )

    with tempfile.TemporaryDirectory(prefix="serialtranslate_yt_") as tmp:
        tmp_dir = Path(tmp)
        if use_python_api:
            _download_caption_with_python_api(url, tmp_dir, language, is_auto)
        else:
            _download_caption_with_cli(url, tmp_dir, language, is_auto)
        captions = _caption_files(tmp_dir, video_id)
        if not captions:
            raise RuntimeError("yt-dlp did not produce a caption file.")
        _write_srt_from_caption(captions[0], output_path)

    return YouTubeSubtitleResult(
        subtitle_path=output_path,
        video_title=title,
        video_id=video_id,
        webpage_url=webpage_url,
        language=language,
        is_auto_generated=is_auto,
        channel=channel,
    )


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Download YouTube captions as SRT")
    parser.add_argument("url", help="YouTube video URL")
    parser.add_argument("--output-base", type=Path, default=Path("Subtitle"))
    parser.add_argument("--language", action="append", help="Preferred caption language; can be repeated")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    result = download_youtube_subtitle(
        args.url,
        base_dir=args.output_base,
        preferred_languages=args.language,
        overwrite=args.overwrite,
    )
    kind = "auto-generated" if result.is_auto_generated else "manual"
    print(f"Saved {kind} {result.language} captions to {result.subtitle_path}")


if __name__ == "__main__":
    main()
