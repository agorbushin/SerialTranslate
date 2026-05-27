#!/usr/bin/env python3
"""
OpenSubtitles API subtitle downloader for the word-tier system.
Downloads subtitles to: Subtitle/{series_name}/{season_name}/{series_name_sX_eY}.srt
"""

import io
import math
import re
import zipfile
from pathlib import Path
from typing import Optional, List, Dict

import requests


def _default_api_key() -> str:
    from env_config import get_opensubtitles_api_key

    return get_opensubtitles_api_key()


def _filename_has_season_episode(
    fname: str, season_number: int, episode_number: int
) -> bool:
    """
    True if filename (or path string) plausibly tags this season/episode.
    Accepts zero-padded (s01e04) and compact (s1e4) forms, and NxM variants.
    """
    fn = (fname or "").lower()
    padded = f"s{season_number:02d}e{episode_number:02d}"
    if padded in fn:
        return True
    for s_fmt in (str(season_number), f"{season_number:02d}"):
        for e_fmt in (str(episode_number), f"{episode_number:02d}"):
            if f"{s_fmt}x{e_fmt}" in fn:
                return True
    # s1e4 but not s1e40 / s1e22 as "s1e2"
    pat = rf"(?<![0-9])s0*{season_number}e0*{episode_number}(?![0-9])"
    return re.search(pat, fn, re.IGNORECASE) is not None


def _normalize_series_for_filename(series_name: str) -> str:
    """Normalize series name for filename: lowercase, spaces -> underscores, remove unsafe chars."""
    s = series_name.strip().lower()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[-\s]+", "_", s).strip("_")
    return s or "series"


def _season_folder_name(season_number: int) -> str:
    """e.g. 2 -> 'Season 2'."""
    return f"Season {season_number}"


def _episode_filename(series_name: str, season_number: int, episode_number: int) -> str:
    """e.g. 'Game of Thrones', 2, 2 -> 'game_of_thrones_s2_e2.srt'."""
    base = _normalize_series_for_filename(series_name)
    return f"{base}_s{season_number}_e{episode_number}.srt"


def get_subtitle_path(
    base_dir: Path,
    series_name: str,
    season_number: int,
    episode_number: int,
) -> Path:
    """
    Return the path where a subtitle file should be stored (does not download).
    Path: base_dir / series_name / Season X / {series_name_sX_eY}.srt
    """
    season_name = _season_folder_name(season_number)
    filename = _episode_filename(series_name, season_number, episode_number)
    return base_dir / series_name / season_name / filename


def get_tierlist_episode_dir(
    base_dir: Path,
    series_name: str,
    season_number: int,
    episode_number: int,
) -> Path:
    """
    Return the directory where tier list files for an episode should be stored.
    Path: base_dir / series_name / Season X / episode_number /
    """
    season_name = _season_folder_name(season_number)
    return base_dir / series_name / season_name / str(episode_number)


def get_translations_episode_dir(
    base_dir: Path,
    series_name: str,
    season_number: int,
    episode_number: int,
) -> Path:
    """
    Return the directory where translation files for an episode should be stored.
    Path: base_dir / series_name / Season X / episode_number /
    Same layout as get_tierlist_episode_dir; typically base_dir is "translations".
    """
    season_name = _season_folder_name(season_number)
    return base_dir / series_name / season_name / str(episode_number)


def _normalize_movie_for_filename(movie_name: str) -> str:
    """Normalize movie name for filename: same as series."""
    return _normalize_series_for_filename(movie_name)


def get_movie_subtitle_path(base_dir: Path, movie_name: str, year: int) -> Path:
    """
    Return the path where a movie subtitle file should be stored (does not download).
    Path: base_dir / Movies / movie_name / {movie_name}_{year}.srt
    """
    base = _normalize_movie_for_filename(movie_name)
    filename = f"{base}_{year}.srt" if year else f"{base}.srt"
    return base_dir / "Movies" / movie_name / filename


def get_tierlist_movie_dir(base_dir: Path, movie_name: str, year: int) -> Path:
    """
    Return the directory where tier list files for a movie should be stored.
    Path: base_dir / Movies / movie_name / {movie_name}_{year}/
    """
    base = _normalize_movie_for_filename(movie_name)
    folder = f"{base}_{year}" if year else base
    return base_dir / "Movies" / movie_name / folder


def get_translations_movie_dir(base_dir: Path, movie_name: str, year: int) -> Path:
    """
    Return the directory where translation files for a movie should be stored.
    Path: base_dir / Movies / movie_name / {movie_name}_{year}/
    Same layout as get_tierlist_movie_dir; typically base_dir is "translations".
    """
    base = _normalize_movie_for_filename(movie_name)
    folder = f"{base}_{year}" if year else base
    return base_dir / "Movies" / movie_name / folder


def _normalize_youtube_for_filename(video_title: str) -> str:
    """Normalize YouTube title for filenames/folders."""
    return _normalize_series_for_filename(video_title) or "youtube_video"


def _youtube_folder_name(video_title: str) -> str:
    title = (video_title or "").strip()
    return title or "YouTube Video"


def _youtube_slug(video_title: str, video_id: str) -> str:
    base = _normalize_youtube_for_filename(video_title)
    vid = re.sub(r"[^\w-]", "", (video_id or "").strip())
    return f"{base}_{vid}" if vid else base


def get_youtube_subtitle_path(base_dir: Path, video_title: str, video_id: str) -> Path:
    """
    Return where a YouTube subtitle should be stored.
    Path: base_dir / YouTube / video_title / {video_title}_{video_id}.srt
    """
    slug = _youtube_slug(video_title, video_id)
    return base_dir / "YouTube" / _youtube_folder_name(video_title) / f"{slug}.srt"


def get_tierlist_youtube_dir(base_dir: Path, video_title: str, video_id: str) -> Path:
    """
    Return where tier list files for a YouTube video should be stored.
    Path: base_dir / YouTube / video_title / {video_title}_{video_id}/
    """
    return base_dir / "YouTube" / _youtube_folder_name(video_title) / _youtube_slug(video_title, video_id)


def get_translations_youtube_dir(base_dir: Path, video_title: str, video_id: str) -> Path:
    """
    Return where translations for a YouTube video should be stored.
    Same layout as get_tierlist_youtube_dir; typically base_dir is "translations".
    """
    return base_dir / "YouTube" / _youtube_folder_name(video_title) / _youtube_slug(video_title, video_id)


class OpenSubtitlesDownloader:
    """Download subtitles from OpenSubtitles API and save under Subtitle/{series}/{season}/."""

    BASE_URL = "https://api.opensubtitles.com/api/v1"
    FALLBACK_STATUS_CODES = {401, 403, 406, 429}

    def __init__(
        self,
        api_key: Optional[str] = None,
        user_agent: str = "SerialTranslate SubtitleDownloader 1.0",
    ):
        from env_config import get_opensubtitles_api_keys

        self.api_keys = get_opensubtitles_api_keys(api_key)
        self.api_key = self.api_keys[0] if self.api_keys else ""
        self.user_agent = user_agent
        self.headers = {
            "User-Agent": user_agent,
            "Accept": "application/json",
            "Api-Key": self.api_key,
        }

    def _set_active_key(self, index: int) -> None:
        self.api_key = self.api_keys[index]
        self.headers["Api-Key"] = self.api_key

    def _request_with_key_fallback(
        self, method: str, url: str, **kwargs
    ) -> requests.Response:
        """Send an OpenSubtitles API request, retrying fallback keys on auth/quota failures."""
        if not self.api_keys:
            response = requests.request(method, url, headers=self.headers, **kwargs)
            response.raise_for_status()
            return response

        last_error: Optional[Exception] = None
        try:
            start_index = self.api_keys.index(self.api_key)
        except ValueError:
            start_index = 0
        key_indices = list(range(start_index, len(self.api_keys))) + list(
            range(0, start_index)
        )
        for attempt_index, index in enumerate(key_indices):
            key = self.api_keys[index]
            self._set_active_key(index)
            headers = dict(self.headers)
            headers["Api-Key"] = key
            try:
                if method.lower() == "get":
                    response = requests.get(url, headers=headers, **kwargs)
                elif method.lower() == "post":
                    response = requests.post(url, headers=headers, **kwargs)
                else:
                    response = requests.request(method, url, headers=headers, **kwargs)
                response.raise_for_status()
                return response
            except requests.HTTPError as e:
                last_error = e
                status_code = e.response.status_code if e.response is not None else None
                if (
                    status_code in self.FALLBACK_STATUS_CODES
                    and attempt_index < len(key_indices) - 1
                ):
                    print(
                        f"OpenSubtitles API key failed with HTTP {status_code}; "
                        f"retrying with fallback key {attempt_index + 2}/{len(key_indices)}."
                    )
                    continue
                raise
        if last_error:
            raise last_error
        raise RuntimeError("OpenSubtitles request failed before sending")

    def search_subtitles_with_params(self, params: Dict[str, str]) -> List[Dict]:
        """Search for subtitles using already-built OpenSubtitles API params."""
        url = f"{self.BASE_URL}/subtitles"
        try:
            response = self._request_with_key_fallback(
                "get", url, params=params, timeout=15
            )
            data = response.json()
            return data.get("data") or []
        except Exception as e:
            raise RuntimeError(f"OpenSubtitles search failed: {e}") from e

    def search_subtitles(
        self,
        query: str,
        languages: List[str],
        season_number: Optional[int] = None,
        episode_number: Optional[int] = None,
    ) -> List[Dict]:
        """Search for subtitles. Returns list of result items from API."""
        params: Dict[str, str] = {
            "languages": ",".join(languages),
            "query": query,
        }
        if season_number is not None:
            params["season_number"] = str(season_number)
        if episode_number is not None:
            params["episode_number"] = str(episode_number)

        return self.search_subtitles_with_params(params)

    def _download_file(self, file_id: str) -> bytes:
        """Get download link and return file bytes."""
        url = f"{self.BASE_URL}/download"
        payload = {"file_id": file_id}
        response = self._request_with_key_fallback(
            "post", url, json=payload, timeout=30
        )
        result = response.json()
        link = result.get("link")
        if not link:
            raise RuntimeError("OpenSubtitles download: no link in response")
        file_response = requests.get(link, timeout=30)
        file_response.raise_for_status()
        return file_response.content

    def _save_subtitle_content(self, content: bytes, output_path: Path) -> None:
        """Write content to output_path; if content is zip, extract first .srt."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if content[:4] == b"PK\x03\x04":
            with zipfile.ZipFile(io.BytesIO(content), "r") as zf:
                srt_names = [n for n in zf.namelist() if n.lower().endswith(".srt")]
                if not srt_names:
                    raise ValueError("ZIP contains no .srt file")
                with zf.open(srt_names[0]) as src:
                    output_path.write_bytes(src.read())
        else:
            output_path.write_bytes(content)

    def _normalize_for_matching(self, text: str) -> str:
        t = text.lower()
        t = re.sub(r"[^a-z0-9\s]", "", t)
        return " ".join(t.split())

    def _match_score(self, query: str, filename: str, release: str = "") -> float:
        qw = set(self._normalize_for_matching(query).split())
        if not qw:
            return 0.0
        fn_lower = filename.lower()
        rel_lower = release.lower() if release else ""
        matches = sum(1 for w in qw if w in fn_lower or w in rel_lower)
        score = matches / len(qw)
        if matches < len(qw) * 0.5:
            score *= 0.3
        return score

    def download_episode(
        self,
        series_name: str,
        season_number: int,
        episode_number: int,
        base_dir: Optional[Path] = None,
        languages: Optional[List[str]] = None,
    ) -> Optional[Path]:
        """
        Search OpenSubtitles for the episode, download the best match, and save to:
        base_dir / series_name / Season X / {series_name_sX_eY}.srt

        Returns:
            Path to the saved .srt file, or None if search/download failed.
        """
        base_dir = base_dir or Path("Subtitle")
        languages = languages or ["en"]
        output_path = get_subtitle_path(base_dir, series_name, season_number, episode_number)

        if output_path.exists():
            return output_path

        try:
            results = self.search_subtitles(
                series_name,
                languages,
                season_number=season_number,
                episode_number=episode_number,
            )
        except Exception as e:
            print(f"OpenSubtitles search failed: {e}")
            return None
        if not results:
            return None

        # Score by name match and popularity
        scored = []
        for item in results:
            attrs = item.get("attributes", {})
            files = attrs.get("files") or []
            file_info = files[0] if files else {}
            filename = file_info.get("file_name", "")
            release = attrs.get("release") or attrs.get("movie_name") or ""
            score = self._match_score(series_name, filename, release)
            dl = attrs.get("download_count", 0)
            pop = math.log10(dl + 1) / 10.0
            scored.append((score * 0.7 + min(pop, 1.0) * 0.3, score, item))

        scored.sort(key=lambda x: x[0], reverse=True)
        best_score, best_match_score, best = scored[0]

        # Require season/episode in filename when specified (padded + compact s1e4, etc.)
        file_info = (best.get("attributes") or {}).get("files") or [{}]
        fname = (file_info[0] or {}).get("file_name", "").lower()
        if not _filename_has_season_episode(fname, season_number, episode_number):
            if best_match_score < 0.5:
                return None

        if best_match_score < 0.15:
            return None

        file_id = (best.get("attributes") or {}).get("files") or [{}]
        fid = (file_id[0] or {}).get("file_id")
        if not fid:
            return None

        try:
            content = self._download_file(str(fid))
            self._save_subtitle_content(content, output_path)
            return output_path
        except Exception:
            return None


def download_subtitle(
    series_name: str,
    season_number: int,
    episode_number: int,
    base_dir: Optional[Path] = None,
    api_key: Optional[str] = None,
    languages: Optional[List[str]] = None,
) -> Optional[Path]:
    """
    Download a subtitle from OpenSubtitles and save to:
    base_dir / series_name / season_name / {series_name_sX_eY}.srt

    Args:
        series_name: e.g. "Game of Thrones"
        season_number: e.g. 2
        episode_number: e.g. 2
        base_dir: Base folder (default: Subtitle).
        api_key: OpenSubtitles API key (optional).
        languages: e.g. ["en"].

    Returns:
        Path to the saved .srt file, or None on failure.
    """
    base_dir = Path(base_dir) if base_dir is not None else Path("Subtitle")
    downloader = OpenSubtitlesDownloader(api_key=api_key)
    return downloader.download_episode(
        series_name=series_name,
        season_number=season_number,
        episode_number=episode_number,
        base_dir=base_dir,
        languages=languages or ["en"],
    )


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Download subtitles from OpenSubtitles")
    parser.add_argument("series", help="Series name (e.g. 'Game of Thrones')")
    parser.add_argument("season", type=int, help="Season number")
    parser.add_argument("episode", type=int, help="Episode number")
    parser.add_argument("--base-dir", type=Path, default=Path("Subtitle"), help="Base directory")
    parser.add_argument("--api-key", default=None, help="OpenSubtitles API key")
    parser.add_argument("--language", default="en", help="Language code")
    args = parser.parse_args()
    path = download_subtitle(
        args.series,
        args.season,
        args.episode,
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
