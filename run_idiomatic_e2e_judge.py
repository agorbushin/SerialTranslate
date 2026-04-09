#!/usr/bin/env python3
"""
End-to-end: extract idiomatic expressions for 3 series, run ChatGPT judge on each.

Requires OPENAI_API_KEY. Writes reports under reports/idiomatic_e2e/<run_label>/.

Usage:
    python run_idiomatic_e2e_judge.py --run run1
    python run_idiomatic_e2e_judge.py --run run2
    python run_idiomatic_e2e_judge.py --compare run1 run2
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from statistics import mean
from typing import Any, Dict, List

_REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(_REPO))

from env_config import resolve_openai_api_key
from idiomatic_expressions import extract_idioms_from_episode
from idiomatic_judge import judge_idiomatic_output

EPISODES: List[Dict[str, Any]] = [
    {
        "key": "game_of_thrones_s1e1",
        "series": "Game of Thrones",
        "subtitle": _REPO / "Subtitle/Game of Thrones/Season 1/game_of_thrones_s1_e1.srt",
        "season": 1,
        "episode": 1,
    },
    {
        "key": "euphoria_s1e4",
        "series": "Euphoria S1 E4",
        "subtitle": _REPO / "Subtitle/Euphoria/Season 1/euphoria_s1_e4.srt",
        "season": 1,
        "episode": 4,
    },
    {
        "key": "fallout_s2e3",
        "series": "Fallout S2 E3",
        "subtitle": _REPO / "Subtitle/Fallout/Season 2/fallout_s2_e3.srt",
        "season": 2,
        "episode": 3,
    },
]


def _reports_dir(run_label: str) -> Path:
    p = _REPO / "reports" / "idiomatic_e2e" / run_label
    p.mkdir(parents=True, exist_ok=True)
    return p


def run_pipeline(run_label: str, api_key: str) -> Dict[str, Any]:
    root = _reports_dir(run_label)
    summary: Dict[str, Any] = {
        "run_label": run_label,
        "episodes": [],
        "mean_overall_score": None,
    }
    scores: List[float] = []

    for ep in EPISODES:
        sub = Path(ep["subtitle"])
        out_dir = root / ep["key"]
        out_dir.mkdir(parents=True, exist_ok=True)
        entry: Dict[str, Any] = {
            "key": ep["key"],
            "series": ep["series"],
            "subtitle": str(sub),
            "output_dir": str(out_dir),
            "extract_ok": False,
            "judge": None,
        }

        if not sub.is_file():
            entry["error"] = f"Subtitle missing: {sub}"
            summary["episodes"].append(entry)
            continue

        ok = extract_idioms_from_episode(
            sub,
            out_dir,
            ep["series"],
            api_key,
            season_number=int(ep["season"]),
            episode_number=int(ep["episode"]),
        )
        entry["extract_ok"] = ok
        if not ok:
            entry["error"] = "extract_idioms_from_episode returned False"
            summary["episodes"].append(entry)
            continue

        j = judge_idiomatic_output(out_dir, subtitle_path=sub, api_key=api_key)
        entry["judge"] = j
        if j.get("error"):
            entry["judge_error"] = j["error"]
        else:
            os_ = j.get("overall_score")
            if isinstance(os_, (int, float)):
                scores.append(float(os_))

        report_path = out_dir / "idiomatic_judge_report.json"
        report_path.write_text(json.dumps(j, ensure_ascii=False, indent=2), encoding="utf-8")
        entry["judge_report_path"] = str(report_path)
        summary["episodes"].append(entry)

    summary["mean_overall_score"] = round(mean(scores), 2) if scores else None
    summary_path = root / "summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {summary_path}")

    sugg_lines: List[str] = [f"# Judge improvement_suggestions ({run_label})\n"]
    for ep in summary["episodes"]:
        j = ep.get("judge") or {}
        for s in j.get("improvement_suggestions") or []:
            if isinstance(s, str) and s.strip():
                sugg_lines.append(f"- [{ep.get('key')}] {s.strip()}")
    if len(sugg_lines) > 1:
        (root / "judge_suggestions.md").write_text("\n".join(sugg_lines) + "\n", encoding="utf-8")

    return summary


def compare_runs(label_a: str, label_b: str) -> None:
    pa = _REPO / "reports" / "idiomatic_e2e" / label_a / "summary.json"
    pb = _REPO / "reports" / "idiomatic_e2e" / label_b / "summary.json"
    if not pa.is_file() or not pb.is_file():
        print("Missing summary.json for one of the runs.", file=sys.stderr)
        sys.exit(1)
    a = json.loads(pa.read_text(encoding="utf-8"))
    b = json.loads(pb.read_text(encoding="utf-8"))
    print(f"=== Compare {label_a} vs {label_b} ===")
    print(f"Mean overall: {a.get('mean_overall_score')} -> {b.get('mean_overall_score')}")
    for ea, eb in zip(a.get("episodes", []), b.get("episodes", [])):
        key = ea.get("key")
        ja = (ea.get("judge") or {}).get("overall_score")
        jb = (eb.get("judge") or {}).get("overall_score")
        print(f"  {key}: {ja} -> {jb}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", type=str, default="", help="Label e.g. run1, run2")
    ap.add_argument("--compare", nargs=2, metavar=("A", "B"))
    args = ap.parse_args()

    if args.compare:
        compare_runs(args.compare[0], args.compare[1])
        return

    if not args.run:
        ap.error("Provide --run <label> or --compare A B")

    key = resolve_openai_api_key(None)
    if not key:
        print("OPENAI_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    run_pipeline(args.run, key)


if __name__ == "__main__":
    main()
