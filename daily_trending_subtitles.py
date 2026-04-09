#!/usr/bin/env python3
"""
Daily subtitle fetch for currently popular TV (via TMDB) with a configurable cap.

1) Most-viewed proxy: TMDB ``trending/tv/day`` (default) or ``tv/popular``.
2) OpenSubtitles: downloads English .srt into ``Subtitle/{series}/Season N/`` using
   the existing downloader (skips files that already exist).

State file (default ``daily_subtitle_state.json``) tracks how many *new* files were
saved per local calendar day so reruns do not exceed your daily budget.

OpenSubtitles advises ~40 requests / 10s; this script spaces calls and stops on
repeated failures (e.g. quota).

Example (cron once per day):
  cd /path/to/SerialTranslate && python3 daily_trending_subtitles.py
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import requests

from download_subtitles import OpenSubtitlesDownloader, get_subtitle_path
from env_config import get_opensubtitles_api_key, get_tmdb_api_key

TMDB_BASE = "https://api.themoviedb.org/3"

# OpenSubtitles: stay under ~40 requests / 10s (search + download link + file GET).
_OS_MIN_INTERVAL_S = 0.35


@dataclass(frozen=True)
class TrendingShow:
    """One row from TMDB trending/popular, resolved for subtitle search."""

    tmdb_id: int
    name: str
    season_number: int
    episode_count: int


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


def _show_display_name(item: Dict[str, Any]) -> str:
    return (item.get("name") or item.get("original_name") or "").strip() or "Unknown"


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


def run_daily_downloads(
    *,
    tmdb_key: str,
    opensubs_key: str,
    base_dir: Path,
    state_path: Path,
    max_new_per_day: int,
    max_shows: int,
    source: str,
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

    shows = build_trending_show_list(
        tmdb_key, source, max_shows, fixed_season=season
    )
    if not shows:
        print("No shows resolved from TMDB (check API key and network).")
        return 0

    queue = round_robin_episode_queue(
        [(s.name, s.season_number, s.episode_count) for s in shows]
    )

    print(
        f"TMDB source={source!r} shows={len(shows)} "
        f"queued_episodes={len(queue)} "
        f"budget_left_today={remaining_budget}"
    )

    if dry_run:
        for name, sn, en in queue[:30]:
            print(f"  [dry-run] {name} S{sn:02d}E{en:02d}")
        if len(queue) > 30:
            print(f"  ... and {len(queue) - 30} more")
        return 0

    downloader = OpenSubtitlesDownloader(api_key=opensubs_key)
    saved_this_run = 0
    failures_in_row = 0

    for series_name, season_number, episode_number in queue:
        if saved_this_run >= remaining_budget:
            break
        out_path = get_subtitle_path(base_dir, series_name, season_number, episode_number)
        if out_path.exists():
            continue

        time.sleep(_OS_MIN_INTERVAL_S)
        path = downloader.download_episode(
            series_name=series_name,
            season_number=season_number,
            episode_number=episode_number,
            base_dir=base_dir,
            languages=languages,
        )
        if path and path.exists():
            saved_this_run += 1
            failures_in_row = 0
            print(f"OK {series_name} S{season_number:02d}E{episode_number:02d} -> {path}")
        else:
            failures_in_row += 1
            print(
                f"SKIP {series_name} S{season_number:02d}E{episode_number:02d} "
                f"(no subtitle or match)"
            )
            if failures_in_row >= 8:
                print("Too many consecutive failures; stopping (possible API limit).")
                break

    new_total = used + saved_this_run
    save_daily_state(state_path, today, new_total)
    print(f"Saved {saved_this_run} new file(s) this run; day total {new_total}/{max_new_per_day}.")
    return saved_this_run


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Download subtitles for TMDB trending/popular TV (daily cap)."
    )
    parser.add_argument(
        "--source",
        choices=("trending_day", "popular"),
        default="trending_day",
        help="trending_day = TMDB trending TV today; popular = TMDB popular page 1",
    )
    parser.add_argument(
        "--max-downloads",
        type=int,
        default=100,
        help="Max new subtitle files to save per local calendar day (default 100)",
    )
    parser.add_argument(
        "--max-shows",
        type=int,
        default=20,
        help="How many top TMDB shows to consider (default 20)",
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
        "--dry-run",
        action="store_true",
        help="Only list TMDB shows and planned episode order; no OpenSubtitles calls",
    )
    parser.add_argument(
        "--language",
        default="en",
        help="Subtitle language code (default en)",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    tmdb_key = get_tmdb_api_key()
    if not tmdb_key:
        print("Missing TMDB_API_KEY (.env or environment).", file=sys.stderr)
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
        max_new_per_day=args.max_downloads,
        max_shows=args.max_shows,
        source=args.source,
        season=args.season,
        dry_run=args.dry_run,
        languages=[args.language],
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
