"""Tests for tier-scoped translation (frequent vs deferred rare tiers)."""

import csv
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


def test_write_translation_csv_includes_example_en(tmp_path: Path, monkeypatch):
    """Translation output CSV stores subtitle example lines per word."""
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
        "1\n00:00:00,000 --> 00:00:01,000\nHello world from the show.\n\n",
        encoding="utf-8",
    )
    out_base = tmp_path / "out_base"

    async def fake_translate_batch(*_a, **_k):
        return {"hello": "привет"}

    monkeypatch.setattr(
        "translate_tier_translations.translate_batch", fake_translate_batch
    )

    ok, err = run(
        episode_dir=ep,
        subtitle_path=srt,
        api_key="sk-test",
        translations_base=out_base,
        subtitle_base=tmp_path / "sub_base",
        tier_ids=["tier_1"],
        translation_overwrite=True,
    )
    assert ok is True, err
    from download_subtitles import get_translations_episode_dir

    out_csv = (
        get_translations_episode_dir(out_base, "TestShow", 1, 1)
        / "tier_1_translations.csv"
    )
    assert out_csv.is_file()
    with open(out_csv, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["word"] == "hello"
    assert "Hello world" in rows[0]["example_en"]
