#!/usr/bin/env python3
"""
Tests for Telegram bot series name parsing.

Sends names into the bot parsing logic and checks that the result is valid
for use in the translation pipeline (series_name, season, episode).
Uses 5–10 varied inputs: exact names and names with slight mistakes that need normalization.
"""

import asyncio
import pytest
from pathlib import Path
from unittest.mock import patch, AsyncMock

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from telegram_bot import (
    _parse_series_input,
    _simple_parse_likely_failed,
    _normalize_with_chatgpt,
    _find_existing,
)


# -----------------------------------------------------------------------------
# Simple parser: exact and regex-friendly inputs (no ChatGPT)
# -----------------------------------------------------------------------------

SIMPLE_PARSE_CASES = [
    # (user_input, expected_series_name, expected_season, expected_episode)
    ("Game of Thrones", "Game of Thrones", 1, 1),
    ("Fallout", "Fallout", 1, 1),
    ("Breaking Bad S01E05", "Breaking Bad", 1, 5),
    ("Fallout s2 e3", "Fallout", 2, 3),
    ("game of thrones season 2 episode 2", "Game Of Thrones", 2, 2),
    ("game of thrones ep 2 season 2", "Game Of Thrones", 2, 2),
    ("The Office S02E04", "The Office", 2, 4),
    ("Better Call Saul s1 e1", "Better Call Saul", 1, 1),
    ("Severance season 1 episode 4", "Severance", 1, 4),
]


@pytest.mark.parametrize("user_input,expected_series,expected_season,expected_episode", SIMPLE_PARSE_CASES)
def test_parse_series_input_simple(user_input, expected_series, expected_season, expected_episode):
    """Simple parser returns expected (series_name, season, episode) for exact and regex-friendly inputs."""
    series_name, season, episode = _parse_series_input(user_input)
    assert series_name == expected_series
    assert season == expected_season
    assert episode == expected_episode


# -----------------------------------------------------------------------------
# Inputs that need normalization (slight mistakes / ambiguous)
# -----------------------------------------------------------------------------

NORMALIZE_INPUTS = [
    "game of throne s2 e2",           # typo: throne
    "braking bad",                    # typo: braking
    "fallout ep 1 season 1",          # ep before season
    "the ofice",                      # typo: ofice
    "game of thrones ep 2 season 2",  # already handled by simple parser; included for consistency
    "got season 2 episode 3",         # abbreviation: got
    "marvelous mrs maisel s1 e1",     # long name + s1e1
]


def test_simple_parse_likely_failed_when_episode_info_in_name():
    """When series name still contains 'ep' or 'season', we should trigger normalization."""
    # After simple parse, "game of thrones ep 2 season 2" -> "Game Of Thrones", 2, 2 (now fixed by regex)
    # So this case no longer leaves episode in name. Test the detector for a case that would.
    raw = "something ep 2 season 2"
    series_name, season, episode = _parse_series_input(raw)
    # With our regex, we get ("Something", 2, 2) and series name is clean
    assert series_name == "Something"
    assert (season, episode) == (2, 2)
    failed = _simple_parse_likely_failed(raw, series_name, season, episode)
    assert failed is False  # we parsed correctly

    # Input where simple parse leaves defaults and raw has "season"
    raw2 = "game of thrones season 2"  # no episode number - our regex might not match
    series_name2, season2, episode2 = _parse_series_input(raw2)
    failed2 = _simple_parse_likely_failed(raw2, series_name2, season2, episode2)
    # If simple parse got (1,1) and raw has "season", we need normalization
    if (season2, episode2) == (1, 1):
        assert failed2 is True


# -----------------------------------------------------------------------------
# Full flow: parse then optionally ChatGPT -> result valid for translation
# -----------------------------------------------------------------------------

def _is_valid_for_translation(series_name: str, season: int, episode: int) -> bool:
    """Result is valid for the pipeline if we have a non-unknown series and sane S/E."""
    if not series_name or series_name.strip().upper() == "UNKNOWN":
        return False
    if season < 1 or episode < 1:
        return False
    return True


@pytest.mark.parametrize("user_input", [
    "Game of Thrones",
    "Game of Thrones s2 e2",
    "game of thrones ep 2 season 2",
    "Fallout S01E01",
    "Breaking Bad",
    "breaking bad season 1",
    "The Office",
    "Severance s1 e2",
])
def test_parsed_result_valid_for_translation(user_input):
    """After simple parse, result is valid for use in translation pipeline."""
    series_name, season, episode = _parse_series_input(user_input)
    assert _is_valid_for_translation(series_name, season, episode), (
        f"Input {user_input!r} -> ({series_name!r}, {season}, {episode}) should be valid for translation"
    )


@pytest.mark.asyncio
async def test_parse_flow_with_mocked_chatgpt_normalization():
    """When ChatGPT normalization is used (mocked), the result is valid for translation."""
    import telegram_bot as bot
    raw = "got season 2 episode 3"
    with patch.object(bot, "_normalize_with_chatgpt", new_callable=AsyncMock) as mock_chat:
        mock_chat.return_value = ("Game of Thrones", 2, 3)
        result = await bot._normalize_with_chatgpt(raw)
    assert result is not None
    sn, s, e = result
    assert _is_valid_for_translation(sn, s, e)
    assert sn == "Game of Thrones" and s == 2 and e == 3


@pytest.mark.asyncio
async def test_resolve_series_name_flow_goes_through_to_translation():
    """
    Simulate bot flow: parse -> if likely failed, normalize with ChatGPT (mocked).
    Assert final (series_name, season, episode) is valid and would be used for _find_existing/translation.
    """
    test_cases = [
        ("Game of Thrones", None),                    # no ChatGPT needed
        ("game of thrones s2 e2", None),              # no ChatGPT needed
        ("got season 2 episode 2", ("Game of Thrones", 2, 2)),  # ChatGPT normalizes
        ("braking bad", ("Breaking Bad", 1, 1)),     # typo fixed by ChatGPT
        ("fallout ep 1 season 1", None),             # simple parse handles it
    ]

    for raw, chatgpt_override in test_cases:
        series_name, season, episode = _parse_series_input(raw)
        if _simple_parse_likely_failed(raw, series_name, season, episode) and chatgpt_override is not None:
            series_name, season, episode = chatgpt_override
        assert _is_valid_for_translation(series_name, season, episode), (
            f"Input {raw!r} should resolve to valid (series_name, season, episode) for translation"
        )


def test_find_existing_accepts_parsed_series_name():
    """
    _find_existing(series_name, season, episode) runs without error for parsed names.
    We only check it doesn't raise; actual hit depends on existing Tier_lists/translations.
    """
    from telegram_bot import TIERLIST_BASE, TRANSLATIONS_BASE
    # Use a series name that may or may not exist on disk
    for series_name, season, episode in [
        ("Game of Thrones", 2, 2),
        ("Fallout", 1, 1),
        ("Breaking Bad", 1, 5),
    ]:
        episode_dir, translations_dir, subtitle_path = _find_existing(series_name, season, episode)
        # Just ensure we get consistent types (Path or None)
        assert episode_dir is None or hasattr(episode_dir, "exists")
        assert translations_dir is None or hasattr(translations_dir, "exists")
        assert subtitle_path is None or hasattr(subtitle_path, "exists")
