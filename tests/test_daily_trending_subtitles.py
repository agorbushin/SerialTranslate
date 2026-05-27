"""Unit tests for daily trending subtitle planning (no live API calls)."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
import sys

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from daily_trending_subtitles import (
    SubtitleJob,
    TrendingMovie,
    TrendingShow,
    build_movie_jobs,
    build_tv_jobs,
    interleave_queues,
    load_local_title_lists,
    load_daily_state,
    round_robin_episode_queue,
    save_plan_file,
    save_daily_state,
)


def test_round_robin_episode_queue() -> None:
    shows = [
        ("A", 1, 2),
        ("B", 1, 3),
    ]
    q = round_robin_episode_queue(shows)
    assert q == [
        ("A", 1, 1),
        ("B", 1, 1),
        ("A", 1, 2),
        ("B", 1, 2),
        ("B", 1, 3),
    ]


def test_round_robin_empty() -> None:
    assert round_robin_episode_queue([]) == []


def test_build_tv_jobs_round_robin_with_metadata() -> None:
    shows = [
        TrendingShow(tmdb_id=10, name="A", season_number=1, episode_count=2),
        TrendingShow(tmdb_id=20, name="B", season_number=3, episode_count=1),
    ]
    jobs = build_tv_jobs(shows)
    assert jobs == [
        SubtitleJob("tv", "A", 10, season_number=1, episode_number=1),
        SubtitleJob("tv", "B", 20, season_number=3, episode_number=1),
        SubtitleJob("tv", "A", 10, season_number=1, episode_number=2),
    ]


def test_movie_jobs_and_interleave() -> None:
    movies = [
        TrendingMovie(tmdb_id=100, title="Movie A", year=2024, imdb_id="tt1"),
        TrendingMovie(tmdb_id=200, title="Movie B", year=2025, imdb_id=None),
    ]
    movie_jobs = build_movie_jobs(movies)
    tv_jobs = [
        SubtitleJob("tv", "Show A", 10, season_number=1, episode_number=1),
    ]
    assert interleave_queues([movie_jobs, tv_jobs]) == [
        SubtitleJob("movie", "Movie A", 100, year=2024, imdb_id="tt1"),
        SubtitleJob("tv", "Show A", 10, season_number=1, episode_number=1),
        SubtitleJob("movie", "Movie B", 200, year=2025, imdb_id=None),
    ]


def test_save_plan_file(tmp_path: Path) -> None:
    p = tmp_path / "plan.json"
    save_plan_file(
        p,
        iso_date="2026-05-27",
        source="trending_day",
        media="all",
        max_new_per_day=80,
        remaining_budget=80,
        shows=[TrendingShow(tmdb_id=10, name="Show", season_number=1, episode_count=2)],
        movies=[TrendingMovie(tmdb_id=100, title="Movie", year=2026, imdb_id="tt100")],
        queue=[SubtitleJob("movie", "Movie", 100, year=2026, imdb_id="tt100")],
    )
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["max_new_per_day"] == 80
    assert data["top_series"][0]["name"] == "Show"
    assert data["top_movies"][0]["title"] == "Movie"
    assert data["queue"][0]["media_type"] == "movie"


def test_load_local_title_lists(tmp_path: Path) -> None:
    p = tmp_path / "titles.json"
    p.write_text(
        json.dumps(
            {
                "series": [{"name": "Show", "season": 2, "episodes": 3}],
                "movies": [{"title": "Movie", "year": 1999, "imdb_id": "tt123"}],
            }
        ),
        encoding="utf-8",
    )
    shows, movies = load_local_title_lists(p)
    assert shows == [TrendingShow(tmdb_id=-1, name="Show", season_number=2, episode_count=3)]
    assert movies == [TrendingMovie(tmdb_id=-1, title="Movie", year=1999, imdb_id="tt123")]


def test_daily_state_reset_new_day(tmp_path: Path) -> None:
    p = tmp_path / "state.json"
    p.write_text(
        json.dumps({"date": "1999-01-01", "new_downloads_today": 99}),
        encoding="utf-8",
    )
    d, n = load_daily_state(p)
    assert n == 0
    assert d  # iso today


def test_daily_state_same_day(tmp_path: Path) -> None:
    from datetime import date

    today = date.today().isoformat()
    p = tmp_path / "state.json"
    p.write_text(
        json.dumps({"date": today, "new_downloads_today": 3}),
        encoding="utf-8",
    )
    d, n = load_daily_state(p)
    assert d == today
    assert n == 3


def test_save_daily_state_roundtrip(tmp_path: Path) -> None:
    from datetime import date

    today = date.today().isoformat()
    p = tmp_path / "state.json"
    save_daily_state(p, today, 7)
    d, n = load_daily_state(p)
    assert d == today
    assert n == 7
