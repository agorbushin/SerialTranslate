"""
Test tier list creation: path layout, Game of Thrones S02E02 tier list, and integrated name/fantasy filtering.
"""

import csv
import json
import tempfile
import pytest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
import sys
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from download_subtitles import get_tierlist_episode_dir
from subtitle_analyzer import save_tierlist_results_to_dir


def test_get_tierlist_episode_dir() -> None:
    base = Path("Tier_lists")
    path = get_tierlist_episode_dir(base, "Game of Thrones", 2, 2)
    assert path == base / "Game of Thrones" / "Season 2" / "2"


def test_tierlist_game_of_thrones_s02e02_exists_and_has_hard_words() -> None:
    """After running pipeline, Tier_lists/Game of Thrones/Season 2/2/ exists and Tier 1 has at least 5 words."""
    episode_dir = ROOT / "Tier_lists" / "Game of Thrones" / "Season 2" / "2"
    tier1_file = episode_dir / "tier_1_hard_usable_words.csv"
    if not episode_dir.exists() or not tier1_file.exists():
        pytest.skip("Run subtitle_analyzer on Game of Thrones S02E02 first to create tier lists")
    with open(tier1_file, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    assert len(rows) >= 5, "Tier 1 (hard words, frequency in series) should have at least 5 words"
    # Sanity: each row has word and series_frequency
    for row in rows[:5]:
        assert "word" in row and "series_frequency" in row
        assert int(row["series_frequency"]) >= 1


def test_tierlist_pipeline_produces_all_tiers() -> None:
    """Tier list episode dir contains all 5 tier CSVs and episode_info.json."""
    episode_dir = ROOT / "Tier_lists" / "Game of Thrones" / "Season 2" / "2"
    if not episode_dir.exists():
        pytest.skip("Tier list not yet created")
    expected = [
        "tier_1_hard_usable_words.csv",
        "tier_2_random_words.csv",
        "tier_3_common_words.csv",
        "tier_4_rare_in_series.csv",
        "tier_5_filtered_words.csv",
        "episode_info.json",
        "README.md",
    ]
    for name in expected:
        assert (episode_dir / name).exists(), f"Missing {name}"


def test_save_tierlist_excluded_words_omits_names() -> None:
    """save_tierlist_results_to_dir with excluded_words does not write those words to tier CSVs."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out"
        tiers = {
            "tier_1_hard_usable": [
                ("stannis", 11, 0, "N/A"),
                ("armor", 7, 6094107, "N/A"),
                ("joffrey", 7, 74077, "N/A"),
                ("commander", 6, 11832701, "C2"),
            ],
            "tier_2_random": [],
            "tier_3_common": [],
            "tier_4_rare_in_series": [],
            "tier_5_filtered": [],
        }
        subtitle_path = ROOT / "Subtitle" / "Game of Thrones" / "Season 2" / "game_of_thrones_s2_e2.srt"
        if not subtitle_path.exists():
            subtitle_path = Path(tmp) / "dummy.srt"
            subtitle_path.write_text("1\n00:00:00,000 --> 00:00:01,000\nTest\n")
        save_tierlist_results_to_dir(
            tiers,
            out,
            subtitle_path,
            series_threshold=2,
            english_threshold=1000,
            max_english_freq=20_000_000,
            series_name="Game of Thrones",
            season_number=2,
            episode_number=2,
            excluded_words={"stannis", "joffrey", "cersei"},
        )
        tier1 = out / "tier_1_hard_usable_words.csv"
        assert tier1.exists()
        with open(tier1, "r", encoding="utf-8") as f:
            words = [row["word"].lower() for row in csv.DictReader(f)]
        assert "stannis" not in words
        assert "joffrey" not in words
        assert "armor" in words
        assert "commander" in words


def test_save_tierlist_splits_tier4_into_rare_c_and_rare_b() -> None:
    """tier_4_rare_in_series is split: B1/B2 → tier_4_rare_b_words.csv; C1/C2 → tier_4_rare_c_words.csv; A-tier skipped."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "ep"
        tiers = {
            "tier_1_hard_usable": [],
            "tier_2_random": [],
            "tier_3_common": [],
            "tier_4_rare_in_series": [
                ("bword", 1, 50_000_000, "B1"),
                ("cword", 1, 50_000_000, "C1"),
                ("aword", 1, 50_000_000, "A1"),
            ],
            "tier_5_filtered": [],
        }
        subtitle_path = Path(tmp) / "dummy.srt"
        subtitle_path.write_text("1\n00:00:00,000 --> 00:00:01,000\nTest\n", encoding="utf-8")
        save_tierlist_results_to_dir(
            tiers,
            out,
            subtitle_path,
            series_threshold=2,
            english_threshold=5_000_000,
            max_english_freq=20_000_000,
            series_name="Test Show",
            season_number=1,
            episode_number=1,
        )
        rare_b = out / "tier_4_rare_b_words.csv"
        rare_c = out / "tier_4_rare_c_words.csv"
        assert rare_b.exists()
        assert rare_c.exists()
        with open(rare_b, "r", encoding="utf-8") as f:
            b_words = [row["word"] for row in csv.DictReader(f)]
        with open(rare_c, "r", encoding="utf-8") as f:
            c_words = [row["word"] for row in csv.DictReader(f)]
        assert "bword" in b_words
        assert "cword" in c_words
        assert "aword" not in b_words and "aword" not in c_words

        meta = json.loads((out / "episode_info.json").read_text(encoding="utf-8"))
        wc = meta["word_counts"]
        assert wc["tier_4_rare_c_words"] == 1
        assert wc["tier_4_rare_b_words"] == 1


def test_save_tierlist_tier4_na_not_in_rare_c() -> None:
    """N/A in tier_4 must not be written to rare_c (only C1/C2 are)."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "ep"
        tiers = {
            "tier_1_hard_usable": [],
            "tier_2_random": [],
            "tier_3_common": [],
            "tier_4_rare_in_series": [
                ("na_word", 1, 50_000_000, "N/A"),
                ("cword", 1, 50_000_000, "C2"),
            ],
            "tier_5_filtered": [],
        }
        subtitle_path = Path(tmp) / "dummy.srt"
        subtitle_path.write_text("1\n00:00:00,000 --> 00:00:01,000\nTest\n", encoding="utf-8")
        save_tierlist_results_to_dir(
            tiers,
            out,
            subtitle_path,
            series_threshold=2,
            english_threshold=5_000_000,
            max_english_freq=20_000_000,
            series_name="Test Show",
            season_number=1,
            episode_number=1,
        )
        with open(out / "tier_4_rare_c_words.csv", "r", encoding="utf-8") as f:
            c_words = [row["word"] for row in csv.DictReader(f)]
        assert "cword" in c_words
        assert "na_word" not in c_words
