"""Tests for tier-scoped translation (frequent vs deferred rare tiers)."""

from pathlib import Path


def test_frequent_tier_ids_are_subset_of_all():
    from translate_tier_translations import (
        ALL_TRANSLATION_TIER_IDS,
        FREQUENT_TRANSLATION_TIER_IDS,
        TIER_ID_TIER_4B,
        TIER_ID_TIER_4C,
    )

    assert FREQUENT_TRANSLATION_TIER_IDS <= ALL_TRANSLATION_TIER_IDS
    assert TIER_ID_TIER_4C not in FREQUENT_TRANSLATION_TIER_IDS
    assert TIER_ID_TIER_4B not in FREQUENT_TRANSLATION_TIER_IDS


def test_translation_csv_files_present_empty_dir(tmp_path: Path):
    from translate_tier_translations import translation_csv_files_present

    assert translation_csv_files_present(tmp_path) == []


def test_run_rejects_unknown_tier_ids(tmp_path: Path):
    import json

    from translate_tier_translations import TIER_1_CSV, run

    ep = tmp_path / "episode"
    ep.mkdir()
    (ep / "episode_info.json").write_text(
        json.dumps(
            {
                "series": "TestShow",
                "season_number": 1,
                "episode_number": 1,
                "subtitle_file": "dummy.srt",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (ep / TIER_1_CSV).write_text("word\nhello\n", encoding="utf-8")

    srt = tmp_path / "dummy.srt"
    srt.write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nHello world.\n\n",
        encoding="utf-8",
    )

    ok, err = run(
        episode_dir=ep,
        subtitle_path=srt,
        api_key="dummy-will-not-be-used",
        translations_base=tmp_path / "out_base",
        subtitle_base=tmp_path / "sub_base",
        tier_ids=["not_a_real_tier"],
    )
    assert ok is False
    assert err is not None
    assert "Unknown tier_ids" in err
