#!/usr/bin/env python3
"""Tests for title_resolution (TMDB + GPT movie/TV title matching)."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from title_resolution import (
    ResolvedTitle,
    resolve_movie,
    resolve_tv,
    _resolve_movie_tmdb,
    _title_similarity,
)


def test_title_similarity_exact():
    assert _title_similarity("Inception", "Inception") >= 0.99


@pytest.fixture
def inception_2010_results():
    return [
        {
            "id": 27205,
            "title": "Inception",
            "release_date": "2010-07-16",
        }
    ]


@pytest.fixture
def dune_ambiguous_results():
    return [
        {"id": 1, "title": "Dune", "release_date": "2021-12-15"},
        {"id": 2, "title": "Dune", "release_date": "1984-12-14"},
    ]


def test_resolve_movie_year_mismatch(inception_2010_results):
    user_parsed = {"media_type": "movie", "movie_name": "Inception", "year": 2000, "raw": "Inception 2000"}

    def fake_search(api_key, query, year=0):
        if year == 2000:
            return []
        return inception_2010_results

    with patch("title_resolution._search_movies", side_effect=fake_search):
        with patch("title_resolution._fetch_imdb_id", return_value="tt1375666"):
            result = _resolve_movie_tmdb("Inception", 2000, "fake-key", user_parsed)

    assert result.confidence == "low"
    assert result.issue == "year_mismatch"
    assert result.year == 2010
    assert result.canonical_title == "Inception"


def test_resolve_movie_high_confidence_correct_year(inception_2010_results):
    user_parsed = {"media_type": "movie", "movie_name": "Inception", "year": 2010, "raw": "Inception 2010"}

    with patch("title_resolution._search_movies", return_value=inception_2010_results):
        with patch("title_resolution._fetch_imdb_id", return_value="tt1375666"):
            result = _resolve_movie_tmdb("Inception", 2010, "fake-key", user_parsed)

    assert result.confidence == "high"
    assert result.year == 2010


def test_resolve_movie_ambiguous(dune_ambiguous_results):
    user_parsed = {"media_type": "movie", "movie_name": "Dune", "year": 0, "raw": "Dune"}

    with patch("title_resolution._search_movies", return_value=dune_ambiguous_results):
        with patch("title_resolution._fetch_imdb_id", return_value=None):
            result = _resolve_movie_tmdb("Dune", 0, "fake-key", user_parsed)

    assert result.confidence == "low"
    assert result.issue == "ambiguous"
    assert len(result.alternatives) >= 1


def test_resolve_movie_gpt_fallback_no_tmdb():
    mock_resp = MagicMock()
    mock_resp.choices = [
        MagicMock(
            message=MagicMock(
                content='{"canonical_title": "Inception", "year": 2010, "confidence": "high", "reason": "ok"}'
            )
        )
    ]
    with patch("title_resolution.get_tmdb_api_key", return_value=""):
        with patch("title_resolution.resolve_openai_api_key", return_value="sk-test"):
            with patch("openai.OpenAI") as mock_openai:
                mock_openai.return_value.chat.completions.create.return_value = mock_resp
                result = resolve_movie("Inception", 2000, raw_input="Inception 2000")

    assert result.confidence == "high"
    assert result.year == 2010


def test_resolve_tv_episode_out_of_range():
    tv_results = [{"id": 100, "name": "Fallout", "first_air_date": "2024-04-10"}]
    user_parsed = {
        "media_type": "tv",
        "series_name": "Fallout",
        "season": 1,
        "episode": 99,
        "raw": "Fallout s1 e99",
    }

    with patch("title_resolution._search_tv", return_value=tv_results):
        with patch("title_resolution._fetch_imdb_id", return_value=None):
            with patch("title_resolution._tv_season_episode_count", return_value=8):
                from title_resolution import _resolve_tv_tmdb

                result = _resolve_tv_tmdb("Fallout", 1, 99, "fake-key", user_parsed)

    assert result.confidence == "low"
    assert result.issue == "episode_out_of_range"


def test_resolved_title_from_user_parsed_movie():
    r = ResolvedTitle.from_user_parsed(
        {"media_type": "movie", "movie_name": "Inception", "year": 2000}
    )
    assert r.canonical_title == "Inception"
    assert r.year == 2000
