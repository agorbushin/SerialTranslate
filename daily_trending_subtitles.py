#!/usr/bin/env python3
"""
Daily subtitle fetch for a curated list of popular movies and TV.

1) Default source: local JSON title list; no TMDB registration required.
2) OpenSubtitles: downloads English .srt into the existing ``Subtitle/`` layout
   and skips files that already exist.
3) Plan file: writes the current top movies/series and queued download order.

State file (default ``daily_subtitle_state.json``) tracks how many *new* files were
saved per local calendar day so reruns do not exceed your daily budget.

OpenSubtitles advises ~40 requests / 10s; this script spaces calls and stops on
repeated failures (e.g. quota).

Example:
  cd /path/to/SerialTranslate && scripts/run_daily_top_subtitles.sh
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import requests

from download_movie_subtitles import download_movie_subtitle
from download_subtitles import (
    OpenSubtitlesDownloader,
    get_movie_subtitle_path,
    get_subtitle_path,
)
from env_config import get_opensubtitles_api_key, get_tmdb_api_key

TMDB_BASE = "https://api.themoviedb.org/3"
DEFAULT_TITLE_FILE = Path("config/top_subtitle_titles.json")

# OpenSubtitles: stay under ~40 requests / 10s (search + download link + file GET).
_OS_MIN_INTERVAL_S = 0.35


@dataclass(frozen=True)
class TrendingShow:
    """One row from TMDB trending/popular, resolved for subtitle search."""

    tmdb_id: int
    name: str
    season_number: int
    episode_count: int


@dataclass(frozen=True)
class TrendingMovie:
    """One row from TMDB trending/popular movies, resolved for subtitle search."""

    tmdb_id: int
    title: str
    year: int
    imdb_id: Optional[str] = None


@dataclass(frozen=True)
class SubtitleJob:
    """One subtitle the routine may try to download."""

    media_type: str
    title: str
    tmdb_id: int
    season_number: Optional[int] = None
    episode_number: Optional[int] = None
    year: int = 0
    imdb_id: Optional[str] = None


def round_robin_episode_queue(
    shows: Sequence[Tuple[str, int, int]],
) -> List[Tuple[str, int, int]]:
    """
    Build (series_name, season, episode) in round-robin episode order across shows.

    ``shows`` items are (name, season_number, episode_count) for one season each.
    """
    if not shows:
        return []
    max_ep = max(ep_count for _, _, ep_count in shows)
    out: List[Tuple[str, int, int]] = []
    for ep in range(1, max_ep + 1):
        for name, season, ep_count in shows:
            if ep <= ep_count:
                out.append((name, season, ep))
    return out


def interleave_queues(
    queues: Sequence[Sequence[SubtitleJob]],
) -> List[SubtitleJob]:
    """Interleave media queues so movies and shows both get a chance each run."""
    if not queues:
        return []
    max_len = max((len(q) for q in queues), default=0)
    out: List[SubtitleJob] = []
    for idx in range(max_len):
        for q in queues:
            if idx < len(q):
                out.append(q[idx])
    return out


def _tmdb_get(path: str, api_key: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    q = {"api_key": api_key}
    if params:
        q.update(params)
    url = f"{TMDB_BASE}{path}"
    r = requests.get(url, params=q, timeout=20)
    r.raise_for_status()
    return r.json()


def fetch_trending_tv_day(api_key: str, limit: int) -> List[Dict[str, Any]]:
    data = _tmdb_get("/trending/tv/day", api_key)
    results = data.get("results") or []
    return results[:limit]


def fetch_popular_tv(api_key: str, limit: int, page: int = 1) -> List[Dict[str, Any]]:
    data = _tmdb_get("/tv/popular", api_key, {"page": str(page)})
    results = data.get("results") or []
    return results[:limit]


def fetch_trending_movies_day(api_key: str, limit: int) -> List[Dict[str, Any]]:
    data = _tmdb_get("/trending/movie/day", api_key)
    results = data.get("results") or []
    return results[:limit]


def fetch_popular_movies(api_key: str, limit: int, page: int = 1) -> List[Dict[str, Any]]:
    data = _tmdb_get("/movie/popular", api_key, {"page": str(page)})
    results = data.get("results") or []
    return results[:limit]


def _show_display_name(item: Dict[str, Any]) -> str:
    return (item.get("name") or item.get("original_name") or "").strip() or "Unknown"


def _movie_display_title(item: Dict[str, Any]) -> str:
    return (item.get("title") or item.get("original_title") or "").strip() or "Unknown"


def _release_year(item: Dict[str, Any]) -> int:
    raw = (item.get("release_date") or "").strip()
    if len(raw) >= 4 and raw[:4].isdigit():
        return int(raw[:4])
    return 0


def _first_usable_season_number(tv_detail: Dict[str, Any]) -> int:
    seasons = tv_detail.get("seasons") or []
    candidates = [
        s.get("season_number")
        for s in seasons
        if isinstance(s.get("season_number"), int) and s["season_number"] >= 1
    ]
    return min(candidates) if candidates else 1


def resolve_show_season_episode_count(
    api_key: str, tmdb_id: int, season_number: int
) -> int:
    data = _tmdb_get(f"/tv/{tmdb_id}/season/{season_number}", api_key)
    eps = data.get("episodes") or []
    return len(eps)


def resolve_movie_imdb_id(api_key: str, tmdb_id: int) -> Optional[str]:
    data = _tmdb_get(f"/movie/{tmdb_id}/external_ids", api_key)
    imdb_id = data.get("imdb_id")
    return str(imdb_id).strip() if imdb_id else None


def build_trending_show_list(
    api_key: str,
    source: str,
    max_shows: int,
    *,
    fixed_season: Optional[int] = None,
) -> List[TrendingShow]:
    """
    Fetch TMDB list and attach first usable season + episode count.
    ``source``: ``trending_day`` | ``popular``.
    """
    if source == "trending_day":
        raw = fetch_trending_tv_day(api_key, max_shows)
    elif source == "popular":
        raw = fetch_popular_tv(api_key, max_shows)
    else:
        raise ValueError(f"Unknown source: {source}")

    out: List[TrendingShow] = []
    for item in raw:
        tid = item.get("id")
        if not isinstance(tid, int):
            continue
        name = _show_display_name(item)
        detail = _tmdb_get(f"/tv/{tid}", api_key)
        season = fixed_season if fixed_season is not None else _first_usable_season_number(detail)
        try:
            n_ep = resolve_show_season_episode_count(api_key, tid, season)
        except requests.HTTPError:
            continue
        if n_ep < 1:
            continue
        out.append(
            TrendingShow(
                tmdb_id=tid,
                name=name,
                season_number=season,
                episode_count=n_ep,
            )
        )
        time.sleep(0.05)
    return out


def build_trending_movie_list(
    api_key: str,
    source: str,
    max_movies: int,
) -> List[TrendingMovie]:
    """
    Fetch TMDB movie list and attach release year + IMDb ID when available.
    ``source``: ``trending_day`` | ``popular``.
    """
    if source == "trending_day":
        raw = fetch_trending_movies_day(api_key, max_movies)
    elif source == "popular":
        raw = fetch_popular_movies(api_key, max_movies)
    else:
        raise ValueError(f"Unknown source: {source}")

    out: List[TrendingMovie] = []
    for item in raw:
        tid = item.get("id")
        if not isinstance(tid, int):
            continue
        try:
            imdb_id = resolve_movie_imdb_id(api_key, tid)
        except requests.HTTPError:
            imdb_id = None
        out.append(
            TrendingMovie(
                tmdb_id=tid,
                title=_movie_display_title(item),
                year=_release_year(item),
                imdb_id=imdb_id,
            )
        )
        time.sleep(0.05)
    return out


def build_tv_jobs(shows: Sequence[TrendingShow]) -> List[SubtitleJob]:
    """Build round-robin TV episode download jobs across resolved shows."""
    if not shows:
        return []
    max_ep = max(show.episode_count for show in shows)
    jobs: List[SubtitleJob] = []
    for ep in range(1, max_ep + 1):
        for show in shows:
            if ep <= show.episode_count:
                jobs.append(
                    SubtitleJob(
                        media_type="tv",
                        title=show.name,
                        tmdb_id=show.tmdb_id,
                        season_number=show.season_number,
                        episode_number=ep,
                    )
                )
    return jobs


def build_movie_jobs(movies: Sequence[TrendingMovie]) -> List[SubtitleJob]:
    return [
        SubtitleJob(
            media_type="movie",
            title=movie.title,
            tmdb_id=movie.tmdb_id,
            year=movie.year,
            imdb_id=movie.imdb_id,
        )
        for movie in movies
    ]


def load_local_title_lists(path: Path) -> Tuple[List[TrendingShow], List[TrendingMovie]]:
    """Load editable local movie/show targets from JSON."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError(f"Local title list not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Local title list is invalid JSON: {path}") from exc

    shows: List[TrendingShow] = []
    for index, item in enumerate(data.get("series") or [], start=1):
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        shows.append(
            TrendingShow(
                tmdb_id=int(item.get("tmdb_id") or -index),
                name=name,
                season_number=int(item.get("season") or 1),
                episode_count=int(item.get("episodes") or 1),
            )
        )

    movies: List[TrendingMovie] = []
    for index, item in enumerate(data.get("movies") or [], start=1):
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        imdb_id = item.get("imdb_id")
        movies.append(
            TrendingMovie(
                tmdb_id=int(item.get("tmdb_id") or -index),
                title=title,
                year=int(item.get("year") or 0),
                imdb_id=str(imdb_id).strip() if imdb_id else None,
            )
        )

    return shows, movies


def load_daily_state(path: Path) -> Tuple[str, int]:
    """Return (iso_date, new_downloads_count_for_that_date)."""
    today = date.today().isoformat()
    if not path.is_file():
        return today, 0
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return today, 0
    d = data.get("date")
    n = data.get("new_downloads_today", 0)
    if d != today:
        return today, 0
    try:
        return today, int(n)
    except (TypeError, ValueError):
        return today, 0


def save_daily_state(path: Path, iso_date: str, new_downloads_today: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {"date": iso_date, "new_downloads_today": new_downloads_today},
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def save_plan_file(
    path: Path,
    *,
    iso_date: str,
    source: str,
    media: str,
    max_new_per_day: int,
    remaining_budget: int,
    shows: Sequence[TrendingShow],
    movies: Sequence[TrendingMovie],
    queue: Sequence[SubtitleJob],
) -> None:
    """Save the current title list and the exact subtitle queue for review."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "date": iso_date,
        "source": source,
        "media": media,
        "max_new_per_day": max_new_per_day,
        "remaining_budget": remaining_budget,
        "top_series": [asdict(show) for show in shows],
        "top_movies": [asdict(movie) for movie in movies],
        "queue": [asdict(job) for job in queue],
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _job_label(job: SubtitleJob) -> str:
    if job.media_type == "movie":
        year = f" ({job.year})" if job.year else ""
        return f"{job.title}{year}"
    season = int(job.season_number or 0)
    episode = int(job.episode_number or 0)
    return f"{job.title} S{season:02d}E{episode:02d}"


def run_daily_downloads(
    *,
    tmdb_key: str,
    opensubs_key: str,
    base_dir: Path,
    state_path: Path,
    plan_path: Path,
    max_new_per_day: int,
    max_shows: int,
    max_movies: int,
    media: str,
    source: str,
    title_file: Path,
    season: Optional[int],
    dry_run: bool,
    languages: List[str],
) -> int:
    """
    Download up to ``max_new_per_day`` new subtitle files for today.
    Returns number of new files saved in this invocation.
    """
    today, used = load_daily_state(state_path)
    remaining_budget = max(0, max_new_per_day - used)
    if remaining_budget == 0:
        print(f"Daily budget already reached ({used}/{max_new_per_day}) for {today}.")
        return 0

    shows: List[TrendingShow] = []
    movies: List[TrendingMovie] = []

    if source == "local":
        local_shows, local_movies = load_local_title_lists(title_file)
        if media in ("all", "tv"):
            shows = local_shows[:max_shows]
        if media in ("all", "movies"):
            movies = local_movies[:max_movies]
    elif media in ("all", "tv"):
        shows = build_trending_show_list(
            tmdb_key, source, max_shows, fixed_season=season
        )
    if source != "local" and media in ("all", "movies"):
        movies = build_trending_movie_list(tmdb_key, source, max_movies)

    if not shows and not movies:
        print("No titles resolved (check the local list or API configuration).")
        return 0

    queue = interleave_queues([build_movie_jobs(movies), build_tv_jobs(shows)])
    save_plan_file(
        plan_path,
        iso_date=today,
        source=source,
        media=media,
        max_new_per_day=max_new_per_day,
        remaining_budget=remaining_budget,
        shows=shows,
        movies=movies,
        queue=queue,
    )

    print(
        f"source={source!r} media={media!r} "
        f"movies={len(movies)} shows={len(shows)} queued_subtitles={len(queue)} "
        f"budget_left_today={remaining_budget}"
    )
    print(f"Saved top-title plan to {plan_path}")

    if dry_run:
        for job in queue[:40]:
            print(f"  [dry-run] {_job_label(job)}")
        if len(queue) > 40:
            print(f"  ... and {len(queue) - 40} more")
        return 0

    downloader = OpenSubtitlesDownloader(api_key=opensubs_key)
    saved_this_run = 0
    failures_in_row = 0

    for job in queue:
        if saved_this_run >= remaining_budget:
            break
        if job.media_type == "movie":
            out_path = get_movie_subtitle_path(base_dir, job.title, job.year)
        else:
            out_path = get_subtitle_path(
                base_dir,
                job.title,
                int(job.season_number or 1),
                int(job.episode_number or 1),
            )
        if out_path.exists():
            continue

        time.sleep(_OS_MIN_INTERVAL_S)
        if job.media_type == "movie":
            try:
                path = download_movie_subtitle(
                    job.title,
                    year=job.year,
                    imdb_id=job.imdb_id,
                    base_dir=base_dir,
                    api_key=opensubs_key,
                    languages=languages,
                )
            except RuntimeError as exc:
                print(f"OpenSubtitles movie search failed for {_job_label(job)}: {exc}")
                path = None
        else:
            path = downloader.download_episode(
                series_name=job.title,
                season_number=int(job.season_number or 1),
                episode_number=int(job.episode_number or 1),
                base_dir=base_dir,
                languages=languages,
            )
        if path and path.exists():
            saved_this_run += 1
            failures_in_row = 0
            print(f"OK {_job_label(job)} -> {path}")
        else:
            failures_in_row += 1
            print(f"SKIP {_job_label(job)} (no subtitle or match)")
            if failures_in_row >= 8:
                print("Too many consecutive failures; stopping (possible API limit).")
                break

    new_total = used + saved_this_run
    save_daily_state(state_path, today, new_total)
    print(f"Saved {saved_this_run} new file(s) this run; day total {new_total}/{max_new_per_day}.")
    return saved_this_run


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Download subtitles for popular movies and TV (daily cap)."
    )
    parser.add_argument(
        "--source",
        choices=("local", "trending_day", "popular"),
        default="local",
        help="local = editable JSON list; trending_day/popular use TMDB",
    )
    parser.add_argument(
        "--media",
        choices=("all", "tv", "movies"),
        default="all",
        help="Which media types to download (default all)",
    )
    parser.add_argument(
        "--max-downloads",
        type=int,
        default=80,
        help="Max new subtitle files to save per local calendar day (default 80)",
    )
    parser.add_argument(
        "--max-shows",
        type=int,
        default=20,
        help="How many top TMDB shows to consider (default 20)",
    )
    parser.add_argument(
        "--max-movies",
        type=int,
        default=40,
        help="How many top TMDB movies to consider (default 40)",
    )
    parser.add_argument(
        "--season",
        type=int,
        default=None,
        help="Force season number (default: first season >= 1 from TMDB)",
    )
    parser.add_argument(
        "--base-dir",
        type=Path,
        default=Path("Subtitle"),
        help="Subtitle root directory",
    )
    parser.add_argument(
        "--state-file",
        type=Path,
        default=Path("daily_subtitle_state.json"),
        help="JSON file for per-day download counts",
    )
    parser.add_argument(
        "--plan-file",
        type=Path,
        default=Path("daily_top_subtitle_plan.json"),
        help="JSON file with current top titles and queued downloads",
    )
    parser.add_argument(
        "--title-file",
        type=Path,
        default=DEFAULT_TITLE_FILE,
        help=f"Local JSON title list for --source local (default {DEFAULT_TITLE_FILE})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only list TMDB titles and planned subtitle order; no OpenSubtitles calls",
    )
    parser.add_argument(
        "--language",
        default="en",
        help="Subtitle language code (default en)",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    tmdb_key = get_tmdb_api_key()
    if args.source != "local" and not tmdb_key:
        print(
            "Missing TMDB_API_KEY (.env or environment) for TMDB source.",
            file=sys.stderr,
        )
        return 1

    opensubs_key = get_opensubtitles_api_key()
    if not args.dry_run and not opensubs_key:
        print("Missing OPENSUBTITLES_API_KEY (.env or environment).", file=sys.stderr)
        return 1

    run_daily_downloads(
        tmdb_key=tmdb_key,
        opensubs_key=opensubs_key or "",
        base_dir=args.base_dir,
        state_path=args.state_file,
        plan_path=args.plan_file,
        max_new_per_day=args.max_downloads,
        max_shows=args.max_shows,
        max_movies=args.max_movies,
        media=args.media,
        source=args.source,
        title_file=args.title_file,
        season=args.season,
        dry_run=args.dry_run,
        languages=[args.language],
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
