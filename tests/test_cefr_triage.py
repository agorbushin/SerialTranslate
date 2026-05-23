"""Unit tests for xlsx CEFR detection, GPT coarse mapping, and min_episode_count gate."""

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from subtitle_analyzer import (
    build_effective_vocabulary_levels,
    categorize_words,
    map_gpt_coarse_to_xlsx_level,
    word_has_xlsx_cefr,
)


def test_word_has_xlsx_cefr():
    v = {"hello": "A1", "rare": "C2"}
    assert word_has_xlsx_cefr("hello", v) is True
    assert word_has_xlsx_cefr("missing", v) is False
    assert word_has_xlsx_cefr("", v) is False


def test_map_gpt_coarse():
    assert map_gpt_coarse_to_xlsx_level("c") == "C1"
    assert map_gpt_coarse_to_xlsx_level("B") == "B2"
    assert map_gpt_coarse_to_xlsx_level("a") == "A2"
    assert map_gpt_coarse_to_xlsx_level("") == "N/A"


def test_build_effective_vocabulary_levels():
    base = {"known": "B1"}
    gpt = {"newword": "c", "Other": "a"}
    eff = build_effective_vocabulary_levels(base, gpt)
    assert eff["known"] == "B1"
    assert eff["newword"] == "C1"
    assert eff["other"] == "A2"


def test_min_episode_count_routes_fewer_than_three_mentions_to_tier2():
    # High series, low english -> learner tier, but count < min_episode_count (default 3)
    series_freqs = Counter({"lonely": 2})
    english_freqs = {"lonely": 100}
    tiers = categorize_words(
        series_freqs,
        english_freqs,
        max_english_freq=20_000_000,
        oxford_filter=set(),
        easy_words_filter=set(),
        vocabulary_levels={"lonely": "C1"},
        series_threshold=1,
        english_threshold=1_000_000,
        min_episode_count=3,
    )
    words_t2 = [t[0] for t in tiers["tier_2_random"]]
    assert "lonely" in words_t2
    assert all(t[0] != "lonely" for t in tiers["tier_1_hard_usable"])


def test_min_episode_count_three_mentions_in_frequent_tier():
    series_freqs = Counter({"often": 3})
    english_freqs = {"often": 100}
    tiers = categorize_words(
        series_freqs,
        english_freqs,
        max_english_freq=20_000_000,
        oxford_filter=set(),
        easy_words_filter=set(),
        vocabulary_levels={"often": "C1"},
        series_threshold=1,
        english_threshold=1_000_000,
        min_episode_count=3,
    )
    words_t1 = [t[0] for t in tiers["tier_1_hard_usable"]]
    assert "often" in words_t1


def test_min_episode_count_disabled():
    series_freqs = Counter({"lonely": 1})
    english_freqs = {"lonely": 100}
    tiers = categorize_words(
        series_freqs,
        english_freqs,
        max_english_freq=20_000_000,
        oxford_filter=set(),
        easy_words_filter=set(),
        vocabulary_levels={"lonely": "C1"},
        series_threshold=1,
        english_threshold=1_000_000,
        min_episode_count=None,
    )
    words_t1 = [t[0] for t in tiers["tier_1_hard_usable"]]
    assert "lonely" in words_t1
