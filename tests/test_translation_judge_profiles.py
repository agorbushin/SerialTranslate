"""Unit tests for translation_judge multi-CSV load and level profiles (no API calls)."""

from __future__ import annotations

import json
from pathlib import Path

from translation_judge import (
    LEVEL_PROFILE_FREQUENT_B_MERGED,
    LEVEL_PROFILE_FREQUENT_C,
    LEVEL_PROFILE_RARE_B,
    LEVEL_PROFILE_RARE_C,
    TRANSLATION_INFO_JSON,
    _build_prompt,
    _criterion_3_block,
    load_translations,
)


def test_load_translations_default_tier1(tmp_path: Path) -> None:
    csv_path = tmp_path / "tier_1_translations.csv"
    csv_path.write_text("word,translation_ru\nalpha,альфа\n", encoding="utf-8")
    (tmp_path / TRANSLATION_INFO_JSON).write_text(
        json.dumps({"series": "Test", "season_number": 1, "episode_number": 1}),
        encoding="utf-8",
    )
    pairs, info = load_translations(tmp_path)
    assert len(pairs) == 1
    assert pairs[0]["word"] == "alpha"
    assert pairs[0]["translation_ru"] == "альфа"
    assert "band_label" not in pairs[0]
    assert info.get("series") == "Test"


def test_load_translations_merged_b_bands(tmp_path: Path) -> None:
    (tmp_path / "tier_b1_translations.csv").write_text(
        "word,translation_ru\none,один\n", encoding="utf-8"
    )
    (tmp_path / "tier_b2_translations.csv").write_text(
        "word,translation_ru\ntwo,два\n", encoding="utf-8"
    )
    pairs, _ = load_translations(
        tmp_path,
        translation_csvs=[
            "tier_b1_translations.csv",
            "tier_b2_translations.csv",
        ],
    )
    assert len(pairs) == 2
    assert pairs[0]["band_label"] == "B1"
    assert pairs[1]["band_label"] == "B2"


def test_criterion_3_block_profiles() -> None:
    assert "C1" in _criterion_3_block(LEVEL_PROFILE_FREQUENT_C)
    assert "[B1]" in _criterion_3_block(LEVEL_PROFILE_FREQUENT_B_MERGED)
    assert "rare" in _criterion_3_block(LEVEL_PROFILE_RARE_C).lower()
    assert "B1" in _criterion_3_block(LEVEL_PROFILE_RARE_B)


def test_build_prompt_prefixes_b1_b2(tmp_path: Path) -> None:
    pairs = [
        {"word": "w1", "translation_ru": "т1", "band_label": "B1"},
        {"word": "w2", "translation_ru": "т2", "band_label": "B2"},
    ]
    prompt = _build_prompt(
        pairs,
        "S",
        1,
        1,
        "",
        {"w1": ["line"], "w2": []},
        level_profile=LEVEL_PROFILE_FREQUENT_B_MERGED,
    )
    assert '[B1] "w1"' in prompt
    assert '[B2] "w2"' in prompt
    assert "B-Level English" in prompt
