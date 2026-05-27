"""
Test subtitle download: path layout and Game of Thrones S02E02 download.
"""

import pytest
import requests
from pathlib import Path

# Project root
import sys
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from download_subtitles import (
    OpenSubtitlesDownloader,
    get_subtitle_path,
    download_subtitle,
    _normalize_series_for_filename,
    _episode_filename,
    _season_folder_name,
    _filename_has_season_episode,
)
from env_config import get_opensubtitles_api_keys


class FakeResponse:
    def __init__(self, status_code: int, payload=None, content: bytes = b""):
        self.status_code = status_code
        self._payload = payload or {}
        self.content = content

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            err = requests.HTTPError(f"HTTP {self.status_code}")
            err.response = self
            raise err

    def json(self):
        return self._payload


def test_path_helpers() -> None:
    assert _normalize_series_for_filename("Game of Thrones") == "game_of_thrones"
    assert _season_folder_name(2) == "Season 2"
    assert _episode_filename("Game of Thrones", 2, 2) == "game_of_thrones_s2_e2.srt"


@pytest.mark.parametrize(
    "fname,season,ep,expected",
    [
        ("Show.S01E04.1080p.mkv", 1, 4, True),
        ("show.s1e4.720p.srt", 1, 4, True),
        ("release.1x4.eng.srt", 1, 4, True),
        ("release.01x04.eng.srt", 1, 4, True),
        ("Show.S01E40.1080p.mkv", 1, 4, False),
        ("Show.S02E04.1080p.mkv", 1, 4, False),
    ],
)
def test_filename_has_season_episode(fname: str, season: int, ep: int, expected: bool) -> None:
    assert _filename_has_season_episode(fname, season, ep) is expected


def test_get_subtitle_path() -> None:
    base = Path("Subtitle")
    path = get_subtitle_path(base, "Game of Thrones", 2, 2)
    assert path == base / "Game of Thrones" / "Season 2" / "game_of_thrones_s2_e2.srt"


def test_opensubtitles_api_keys_include_fallbacks(monkeypatch) -> None:
    for name in (
        "OPENSUBTITLES_API_KEY",
        "OPENSUBTITLES_API_KEY_2",
        "OPENSUBTITLES_API_KEY_ALT",
        "OPENSUBTITLES_API_ALTERNATIVE_KEY",
        "OPENSUBTITLES_API_KEY_FALLBACK",
        "opensubtitles_api_alternative_key",
        "OPENSUBTITLES_API_KEYS",
    ):
        monkeypatch.delenv(name, raising=False)

    monkeypatch.setenv("OPENSUBTITLES_API_KEY", "primary")
    monkeypatch.setenv("OPENSUBTITLES_API_KEY_2", "secondary")
    monkeypatch.setenv("OPENSUBTITLES_API_KEY_ALT", "primary")
    monkeypatch.setenv("OPENSUBTITLES_API_KEYS", "tertiary, secondary")

    assert get_opensubtitles_api_keys() == ["primary", "secondary", "tertiary"]


def test_opensubtitles_search_retries_with_fallback_key(monkeypatch) -> None:
    for name in (
        "OPENSUBTITLES_API_KEY",
        "OPENSUBTITLES_API_KEY_2",
        "OPENSUBTITLES_API_KEY_ALT",
        "OPENSUBTITLES_API_ALTERNATIVE_KEY",
        "OPENSUBTITLES_API_KEY_FALLBACK",
        "opensubtitles_api_alternative_key",
        "OPENSUBTITLES_API_KEYS",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OPENSUBTITLES_API_KEY", "primary")
    monkeypatch.setenv("OPENSUBTITLES_API_KEY_2", "fallback")

    seen_keys = []

    def fake_get(url, *, headers, **kwargs):
        seen_keys.append(headers.get("Api-Key"))
        if len(seen_keys) == 1:
            return FakeResponse(401)
        return FakeResponse(200, {"data": [{"id": "ok"}]})

    monkeypatch.setattr("download_subtitles.requests.get", fake_get)

    downloader = OpenSubtitlesDownloader()
    results = downloader.search_subtitles("Friends", ["en"], 1, 1)

    assert results == [{"id": "ok"}]
    assert seen_keys == ["primary", "fallback"]


def test_opensubtitles_api_keys_include_lowercase_alternative_alias(monkeypatch) -> None:
    for name in (
        "OPENSUBTITLES_API_KEY",
        "OPENSUBTITLES_API_KEY_2",
        "OPENSUBTITLES_API_KEY_ALT",
        "OPENSUBTITLES_API_ALTERNATIVE_KEY",
        "OPENSUBTITLES_API_KEY_FALLBACK",
        "opensubtitles_api_alternative_key",
        "OPENSUBTITLES_API_KEYS",
    ):
        monkeypatch.delenv(name, raising=False)

    monkeypatch.setenv("OPENSUBTITLES_API_KEY", "primary")
    monkeypatch.setenv("opensubtitles_api_alternative_key", "fallback")

    assert get_opensubtitles_api_keys() == ["primary", "fallback"]


@pytest.mark.skipif(
    not Path(ROOT / "download_subtitles.py").exists(),
    reason="download_subtitles module not in project root",
)
def test_download_game_of_thrones_s02e02() -> None:
    """Download Game of Thrones S02E02 and assert file exists at expected path."""
    base_dir = ROOT / "Subtitle"
    path = download_subtitle(
        series_name="Game of Thrones",
        season_number=2,
        episode_number=2,
        base_dir=base_dir,
    )
    assert path is not None, "Download should succeed"
    assert path == get_subtitle_path(base_dir, "Game of Thrones", 2, 2)
    assert path.exists()
    assert path.suffix.lower() == ".srt"
    content = path.read_text(encoding="utf-8", errors="replace")
    assert len(content) > 100
    # SRT has numeric sequence and timestamps
    assert "1\n" in content or "00:" in content or " --> " in content
