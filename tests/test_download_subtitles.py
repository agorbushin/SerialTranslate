"""
Test subtitle download: path layout and Game of Thrones S02E02 download.
"""

import pytest
from pathlib import Path

# Project root
import sys
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from download_subtitles import (
    get_subtitle_path,
    download_subtitle,
    _normalize_series_for_filename,
    _episode_filename,
    _season_folder_name,
)


def test_path_helpers() -> None:
    assert _normalize_series_for_filename("Game of Thrones") == "game_of_thrones"
    assert _season_folder_name(2) == "Season 2"
    assert _episode_filename("Game of Thrones", 2, 2) == "game_of_thrones_s2_e2.srt"


def test_get_subtitle_path() -> None:
    base = Path("Subtitle")
    path = get_subtitle_path(base, "Game of Thrones", 2, 2)
    assert path == base / "Game of Thrones" / "Season 2" / "game_of_thrones_s2_e2.srt"


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
