#!/usr/bin/env python3
"""Re-run subtitle_analyzer for tier lists missing rare B/C CSVs."""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from env_config import resolve_openai_api_key
from subtitle_analyzer import run_pipeline

# Stale caches (tier_1 exists, rare B/C CSVs missing) + two extra series with subtitles.
JOBS: list[tuple[str, int, int, str]] = [
    ("Black Mirror", 1, 1, "Subtitle/Black Mirror/Season 1/black_mirror_s1_e1.srt"),
    ("Euphoria S1 E3", 1, 1, "Subtitle/Euphoria/Season 1/euphoria_s1_e3.srt"),
    ("Fallout S2 E5", 1, 1, "Subtitle/Fallout/Season 2/fallout_s2_e5.srt"),
    (
        "Game Of Thrones S2 E3 S1 E1",
        1,
        1,
        "Subtitle/game of Thrones s2 e3)/Season 1/game_of_thrones_s2_e3_s1_e1.srt",
    ),
    ("Game of Thrones", 2, 2, "Subtitle/Game of Thrones/Season 2/game_of_thrones_s2_e2.srt"),
    ("Narcos", 1, 1, "Subtitle/Narcos/Season 1/narcos_s1_e1.srt"),
    ("Peaky Blinders", 1, 1, "Subtitle/Peaky Blinders/Season 1/peaky_blinders_s1_e1.srt"),
    ("Succession", 1, 1, "Subtitle/Succession/Season 1/succession_s1_e1.srt"),
    ("The Sopranos", 1, 1, "Subtitle/The Sopranos/Season 1/the_sopranos_s1_e1.srt"),
    ("The Wire", 1, 1, "Subtitle/The Wire/Season 1/the_wire_s1_e1.srt"),
    ("True Detective", 1, 1, "Subtitle/True Detective/Season 1/true_detective_s1_e1.srt"),
    ("True Detective S1 E1", 1, 1, "Subtitle/True Detective/Season 1/true_detective_s1_e1.srt"),
    ("True Detective S1 E2", 1, 1, "Subtitle/True Detective/Season 1/true_detective_s1_e2.srt"),
    ("Westworld", 1, 1, "Subtitle/Westworld/Season 1/westworld_s1_e1.srt"),
    ("Lost", 1, 1, "Subtitle/Lost/Season 1/lost_s1_e1.srt"),
    ("Game of Thrones", 3, 4, "Subtitle/Game of Thrones/Season 3/game_of_thrones_s3_e4.srt"),
]


def main() -> int:
    api_key = resolve_openai_api_key(None)
    ok, fail = 0, 0
    for series, season, episode, sub_rel in JOBS:
        sub = (REPO / sub_rel).resolve()
        label = f"{series} S{season}E{episode}"
        if not sub.is_file():
            print(f"SKIP {label}: subtitle missing ({sub_rel})")
            fail += 1
            continue
        print(f"\n=== {label} ===")
        out = run_pipeline(
            subtitle_path=sub,
            base_dir=REPO,
            tierlist_base_dir=REPO / "Tier_lists",
            series_name=series,
            season_number=season,
            episode_number=episode,
            openai_api_key=api_key,
            skip_if_outputs_fresh=False,
        )
        if out is None:
            print(f"FAIL {label}")
            fail += 1
            continue
        info_path = out / "episode_info.json"
        wc = {}
        if info_path.is_file():
            wc = json.loads(info_path.read_text(encoding="utf-8")).get("word_counts", {})
        print(
            f"OK {label} -> {out.relative_to(REPO)} "
            f"rare_c={wc.get('tier_4_rare_c_words', '?')} "
            f"rare_b={wc.get('tier_4_rare_b_words', '?')}"
        )
        ok += 1
    print(f"\nDone: {ok} ok, {fail} failed/skipped")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
