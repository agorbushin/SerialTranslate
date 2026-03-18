"""
Test name/fantasy filter: after filtering, character names are removed and normal words kept.
Uses Game of Thrones S02E02 tier list (e.g. stannis, joffrey, cersei out; armor, commander, seagull in).
"""

import csv
import json
import pytest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
import sys
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from filter_tier_names import (
    get_subtitle_text,
    get_all_words_from_episode_tiers,
    filter_tier_csv,
    DEFAULT_TIER_FILES,
)


def test_get_subtitle_text() -> None:
    srt = ROOT / "Subtitle" / "Game of Thrones" / "Season 2" / "game_of_thrones_s2_e2.srt"
    if not srt.exists():
        pytest.skip("Subtitle file not found")
    text = get_subtitle_text(srt)
    assert len(text) > 1000
    assert "Cersei" in text or "cersei" in text or "armor" in text.lower()


def test_get_all_words_from_episode_tiers() -> None:
    episode_dir = ROOT / "Tier_lists" / "Game of Thrones" / "Season 2" / "2"
    if not episode_dir.exists():
        pytest.skip("Tier list episode dir not found")
    words = get_all_words_from_episode_tiers(episode_dir, DEFAULT_TIER_FILES)
    assert len(words) >= 5
    words_lower = [w.lower() for w in words]
    assert "stannis" in words_lower or "armor" in words_lower


def test_filter_tier_csv_removes_given_words() -> None:
    import tempfile
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["word", "series_frequency", "english_frequency", "vocabulary_level"])
        w.writerow(["stannis", 11, 0, "N/A"])
        w.writerow(["armor", 7, 6094107, "N/A"])
        w.writerow(["joffrey", 7, 74077, "N/A"])
        path = Path(f.name)
    try:
        removed = filter_tier_csv(path, {"stannis", "joffrey"})
        assert removed == 2
        with open(path, "r", encoding="utf-8") as f:
            words_left = [row["word"] for row in csv.DictReader(f)]
        assert "armor" in words_left
        assert "stannis" not in words_left
        assert "joffrey" not in words_left
    finally:
        path.unlink(missing_ok=True)


def test_after_filter_names_fantasy_removed_and_normal_kept() -> None:
    """
    If excluded_names_fantasy.json exists (filter was run), tier_1 must not contain
    any excluded word, and must still contain at least one normal word (armor, commander, seagull).
    Run: python3 filter_tier_names.py "Tier_lists/Game of Thrones/Season 2/2" --subtitle "Subtitle/Game of Thrones/Season 2/game_of_thrones_s2_e2.srt" --series "Game of Thrones" (with OPENAI_API_KEY set).
    """
    episode_dir = ROOT / "Tier_lists" / "Game of Thrones" / "Season 2" / "2"
    tier1 = episode_dir / "tier_1_hard_usable_words.csv"
    excluded_file = episode_dir / "excluded_names_fantasy.json"
    if not tier1.exists():
        pytest.skip("Tier 1 file not found")
    if not excluded_file.exists():
        pytest.skip("Run filter_tier_names.py on this episode first to create excluded_names_fantasy.json")

    excluded = set(json.loads(excluded_file.read_text()).get("excluded", []))
    assert len(excluded) > 0, "Expected some excluded words"

    words_in_tier1 = []
    with open(tier1, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            w = (row.get("word") or "").strip().lower()
            if w:
                words_in_tier1.append(w)

    for w in excluded:
        assert w.lower() not in words_in_tier1, f"Excluded word '{w}' should not be in tier_1"

    normal_should_remain = {"armor", "commander", "seagull"}
    found = [x for x in normal_should_remain if x in words_in_tier1]
    assert len(found) >= 1, f"At least one of {normal_should_remain} should remain in tier_1; found: {words_in_tier1[:20]}"
