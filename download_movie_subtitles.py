#!/usr/bin/env python3
"""
OpenSubtitles API movie subtitle downloader.
Downloads subtitles to: Subtitle/Movies/{movie_name}/{movie_name}_{year}.srt
Separate from series download; movies use no season/episode.
"""

import math
import re
from pathlib import Path
from typing import Optional, List, Dict

from download_subtitles import (
    OpenSubtitlesDownloader,
    get_movie_subtitle_path,
    _default_api_key,
)


def _normalize_imdb_id(imdb_id: Optional[str]) -> Optional[str]:
    """Extract numeric part from tt1375666 or 1375666."""
    if not imdb_id:
        return None
    s = str(imdb_id).strip()
    m = re.search(r"\d+", s)
    return m.group() if m else None


def download_movie_subtitle(
    movie_title: str,
    year: int = 0,
    imdb_id: Optional[str] = None,
    base_dir: Optional[Path] = None,
    api_key: Optional[str] = None,
    languages: Optional[List[str]] = None,
) -> Optional[Path]:
    """
    Download a movie subtitle from OpenSubtitles and save to:
    base_dir / Movies / movie_name / {movie_name}_{year}.srt

    Args:
        movie_title: e.g. "Inception"
        year: Release year (e.g. 2010). Used for disambiguation and filename. Use 0 if unknown.
        imdb_id: Optional IMDb ID (e.g. "tt1375666") for precise match.
        base_dir: Base folder (default: Subtitle).
        api_key: OpenSubtitles API key (optional).
        languages: e.g. ["en"].

    Returns:
        Path to the saved .srt file, or None on failure.
    """
    base_dir = Path(base_dir) if base_dir is not None else Path("Subtitle")
    languages = languages or ["en"]
    output_path = get_movie_subtitle_path(base_dir, movie_title, year)

    if output_path.exists():
        return output_path

    downloader = OpenSubtitlesDownloader(api_key=api_key or _default_api_key())

    # Search: use imdb_id if provided, else query + year
    imdb_numeric = _normalize_imdb_id(imdb_id)
    if imdb_numeric:
        params: Dict[str, str] = {
            "languages": ",".join(languages),
            "imdb_id": imdb_numeric,
        }
    else:
        params = {
            "languages": ",".join(languages),
            "query": movie_title,
        }
        if year and year > 0:
            params["year"] = str(year)

    try:
        results = downloader.search_subtitles_with_params(params)
    except Exception as e:
        raise RuntimeError(f"OpenSubtitles search failed: {e}") from e

    if not results:
        return None

    # Score by name/year match and popularity (no S##E## requirement for movies)
    scored = []
    year_str = str(year) if year and year > 0 else ""
    for item in results:
        attrs = item.get("attributes", {})
        files = attrs.get("files") or []
        file_info = files[0] if files else {}
        filename = file_info.get("file_name", "")
        release = attrs.get("release") or attrs.get("movie_name") or ""
        score = downloader._match_score(movie_title, filename, release)
        # Bonus if year appears in filename/release
        if year_str and (year_str in filename or year_str in release):
            score = min(1.0, score + 0.3)
        dl = attrs.get("download_count", 0)
        pop = math.log10(dl + 1) / 10.0
        scored.append((score * 0.7 + min(pop, 1.0) * 0.3, score, item))

    scored.sort(key=lambda x: x[0], reverse=True)
    _, best_match_score, best = scored[0]

    if best_match_score < 0.15:
        return None

    file_id = (best.get("attributes") or {}).get("files") or [{}]
    fid = (file_id[0] or {}).get("file_id")
    if not fid:
        return None

    try:
        content = downloader._download_file(str(fid))
        downloader._save_subtitle_content(content, output_path)
        return output_path
    except Exception:
        return None


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Download movie subtitles from OpenSubtitles")
    parser.add_argument("movie", help="Movie title (e.g. 'Inception')")
    parser.add_argument("--year", type=int, default=0, help="Release year (recommended for disambiguation)")
    parser.add_argument("--imdb-id", default=None, help="IMDb ID (e.g. tt1375666) for precise match")
    parser.add_argument("--base-dir", type=Path, default=Path("Subtitle"), help="Base directory")
    parser.add_argument("--api-key", default=None, help="OpenSubtitles API key")
    parser.add_argument("--language", default="en", help="Language code")
    args = parser.parse_args()
    path = download_movie_subtitle(
        args.movie,
        year=args.year,
        imdb_id=args.imdb_id,
        base_dir=args.base_dir,
        api_key=args.api_key,
        languages=[args.language],
    )
    if path:
        print(f"Downloaded: {path}")
    else:
        print("Download failed.")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
