"""Unit tests for daily trending subtitle planning (no live API calls)."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
import sys

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from daily_trending_subtitles import (
    load_daily_state,
    round_robin_episode_queue,
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
