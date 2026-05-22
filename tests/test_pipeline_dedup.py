"""Tests for duplicate-work reductions: parse handoff, fingerprint skip, preload cache, translations merge."""

import json
from pathlib import Path

import pytest


def test_parse_srt_file_with_content_matches_parse_srt_file(tmp_path: Path) -> None:
    from subtitle_analyzer import parse_srt_file, parse_srt_file_with_content

    srt = tmp_path / "Sample_Show_S01E01.srt"
    srt.write_text(
        "1\n00:00:01,000 --> 00:00:02,000\nHello world test\n\n",
        encoding="utf-8",
    )
    excluded: set[str] = set()
    words_a = parse_srt_file(srt, excluded)
    words_b, raw = parse_srt_file_with_content(srt, excluded)
    assert words_a == words_b
    assert "Hello" in raw


def test_try_skip_fresh_pipeline_when_fingerprint_matches(tmp_path: Path) -> None:
    from subtitle_analyzer import (
        FINGERPRINT_FILENAME,
        TIER_4_RARE_B_WORDS_CSV,
        TIER_4_RARE_C_WORDS_CSV,
        _subtitle_source_fingerprint,
        _try_skip_fresh_pipeline,
    )

    srt = tmp_path / "Sample_Show_S01E01.srt"
    srt.write_text("subtitle body", encoding="utf-8")
    tier_root = tmp_path / "Tier_lists"
    ep = tier_root / "Sample Show" / "Season 1" / "1"
    ep.mkdir(parents=True)
    (ep / "tier_1_hard_usable_words.csv").write_text(
        "word,series_frequency,english_frequency,vocabulary_level\n"
        "wibble,1,100,C1\n",
        encoding="utf-8",
    )
    (ep / TIER_4_RARE_B_WORDS_CSV).write_text(
        "word,series_frequency,english_frequency,vocabulary_level\n",
        encoding="utf-8",
    )
    (ep / TIER_4_RARE_C_WORDS_CSV).write_text(
        "word,series_frequency,english_frequency,vocabulary_level\n",
        encoding="utf-8",
    )
    fp = _subtitle_source_fingerprint(srt)
    (ep / FINGERPRINT_FILENAME).write_text(
        json.dumps(fp, indent=2), encoding="utf-8"
    )
    out = _try_skip_fresh_pipeline(
        srt, tier_root, False, None, None, None, None
    )
    assert out == ep.resolve()


def test_try_skip_fresh_pipeline_requires_rare_tier_csvs(tmp_path: Path) -> None:
    from subtitle_analyzer import (
        FINGERPRINT_FILENAME,
        TIER_4_RARE_B_WORDS_CSV,
        TIER_4_RARE_C_WORDS_CSV,
        _subtitle_source_fingerprint,
        _try_skip_fresh_pipeline,
    )

    srt = tmp_path / "Sample_Show_S01E01.srt"
    srt.write_text("subtitle body", encoding="utf-8")
    tier_root = tmp_path / "Tier_lists"
    ep = tier_root / "Sample Show" / "Season 1" / "1"
    ep.mkdir(parents=True)
    (ep / "tier_1_hard_usable_words.csv").write_text(
        "word,series_frequency,english_frequency,vocabulary_level\n"
        "wibble,1,100,C1\n",
        encoding="utf-8",
    )
    fp = _subtitle_source_fingerprint(srt)
    (ep / FINGERPRINT_FILENAME).write_text(
        json.dumps(fp, indent=2), encoding="utf-8"
    )
    assert (
        _try_skip_fresh_pipeline(srt, tier_root, False, None, None, None, None)
        is None
    )
    (ep / TIER_4_RARE_B_WORDS_CSV).write_text(
        "word,series_frequency,english_frequency,vocabulary_level\n",
        encoding="utf-8",
    )
    (ep / TIER_4_RARE_C_WORDS_CSV).write_text(
        "word,series_frequency,english_frequency,vocabulary_level\n",
        encoding="utf-8",
    )
    assert (
        _try_skip_fresh_pipeline(srt, tier_root, False, None, None, None, None)
        == ep.resolve()
    )


def test_get_preloaded_bundle_cache_hit(project_root: Path) -> None:
    from subtitle_analyzer import _get_preloaded_bundle, _preload_cache

    filters_dir = project_root / "filters"
    freq_path = project_root / "Frequency list" / "English" / "unigram_freq.csv"
    vocab_file = (
        project_root / "Frequency list" / "English" / "complete english vocabulary.xlsx"
    )
    if not freq_path.is_file():
        pytest.skip("unigram_freq.csv not present")
    _preload_cache.clear()
    *_, hit1 = _get_preloaded_bundle(filters_dir, freq_path, vocab_file)
    *_, hit2 = _get_preloaded_bundle(filters_dir, freq_path, vocab_file)
    assert hit1 is False
    assert hit2 is True


def test_load_existing_translations(tmp_path: Path) -> None:
    from translate_tier_translations import load_existing_translations

    p = tmp_path / "tier_1_translations.csv"
    p.write_text("word,translation_ru\nfoo,бар\n", encoding="utf-8")
    assert load_existing_translations(p) == {"foo": "бар"}


def test_subtitle_text_utils_cleaning() -> None:
    from subtitle_text_utils import get_subtitle_text_from_content

    raw = (
        "1\n00:00:01,000 --> 00:00:02,000\n"
        "Hello <b>world</b>\n\n"
    )
    t = get_subtitle_text_from_content(raw)
    assert "Hello" in t
    assert "world" in t
    assert "<b>" not in t


@pytest.fixture
def project_root() -> Path:
    return Path(__file__).resolve().parent.parent
