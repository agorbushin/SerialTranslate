#!/usr/bin/env python3
"""
Run LLM judges for every bot output part across many episodes.

All judge calls (every part × every episode) are submitted to one thread pool so work
runs in parallel up to --max-workers (default: many concurrent API calls for speed).

Parts: frequent_c, frequent_b (merged b1+b2), rare_c, rare_b, phrasal, idioms.

Requires OPENAI_API_KEY. Writes under reports/bot_judge_matrix/<run_label>/.

Usage:
    python run_bot_output_judge_matrix.py --run myrun \\
        --manifest reports/bot_judge_matrix/manifests/default_10.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

_REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(_REPO))

from env_config import resolve_openai_api_key
from translation_judge import (
    LEVEL_PROFILE_FREQUENT_B_MERGED,
    LEVEL_PROFILE_FREQUENT_C,
    LEVEL_PROFILE_RARE_B,
    LEVEL_PROFILE_RARE_C,
    SUBTITLE_BASE,
    TRANSLATION_INFO_JSON,
    judge_translations,
)
from phrasal_judge import judge_phrasal_translations
from idiomatic_judge import judge_idiomatic_output

TIER_1 = "tier_1_translations.csv"
TIER_B1 = "tier_b1_translations.csv"
TIER_B2 = "tier_b2_translations.csv"
TIER_RARE_C = "tier_4_rare_c_translations.csv"
TIER_RARE_B = "tier_4_rare_b_translations.csv"
PHRASAL_CSV = "phrasal_verbs.csv"
IDIOMS_CSV = "idiomatic_expressions.csv"

PART_FILES = {
    "frequent_c": (TIER_1,),
    "frequent_b": (TIER_B1, TIER_B2),
    "rare_c": (TIER_RARE_C,),
    "rare_b": (TIER_RARE_B,),
    "phrasal": (PHRASAL_CSV,),
    "idioms": (IDIOMS_CSV,),
}


def _slug_from_dir(translations_dir: Path, repo: Path) -> str:
    try:
        rel = translations_dir.resolve().relative_to(repo.resolve())
    except ValueError:
        rel = translations_dir.resolve()
    s = str(rel).replace("/", "__").replace(" ", "_")
    return re.sub(r"[^a-zA-Z0-9_.-]+", "_", s).strip("_") or "episode"


def _load_translation_info(translations_dir: Path) -> Dict[str, Any]:
    p = translations_dir / TRANSLATION_INFO_JSON
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def resolve_subtitle_path(
    translations_dir: Path,
    subtitle_override: Optional[str],
    subtitle_base: Path,
) -> Optional[Path]:
    """Match translation_judge subtitle inference when override not set."""
    translations_dir = translations_dir.resolve()
    sub_base = subtitle_base.resolve()

    if subtitle_override:
        cand = Path(subtitle_override)
        if not cand.is_absolute():
            cand = _REPO / cand
        cand = cand.resolve()
        if cand.is_file():
            return cand
        return None

    info = _load_translation_info(translations_dir)
    series_name = info.get("series") or "Unknown Series"
    season = int(info.get("season_number", 1))
    episode = int(info.get("episode_number", 1))

    source_sub = info.get("source_subtitle", "")
    if source_sub:
        inferred = sub_base / str(series_name) / f"Season {season}" / source_sub
        if inferred.is_file():
            return inferred

    try:
        from download_subtitles import get_subtitle_path  # type: ignore

        candidate = get_subtitle_path(sub_base, series_name, season, episode)
        if candidate.exists():
            return candidate
    except Exception:
        pass
    return None


def _missing_reason(translations_dir: Path, part: str) -> str:
    names = PART_FILES[part]
    missing = [n for n in names if not (translations_dir / n).is_file()]
    return f"missing {', '.join(missing)}"


def _part_callables_for_episode(
    td: Path,
    subtitle_path: Optional[Path],
    model: str,
    subtitle_base: Path,
) -> Tuple[Dict[str, str], List[Tuple[str, Callable[[], Dict[str, Any]]]]]:
    """Return (skip_reasons_by_part, list of (part_name, judge_fn))."""
    skips: Dict[str, str] = {}
    jobs: List[Tuple[str, Callable[[], Dict[str, Any]]]] = []

    if (td / TIER_1).is_file():

        def _fc() -> Dict[str, Any]:
            return judge_translations(
                td,
                subtitle_path=subtitle_path,
                model=model,
                subtitle_base=subtitle_base,
                translation_csvs=[TIER_1],
                level_profile=LEVEL_PROFILE_FREQUENT_C,
            )

        jobs.append(("frequent_c", _fc))
    else:
        skips["frequent_c"] = _missing_reason(td, "frequent_c")

    if (td / TIER_B1).is_file() and (td / TIER_B2).is_file():

        def _fb() -> Dict[str, Any]:
            return judge_translations(
                td,
                subtitle_path=subtitle_path,
                model=model,
                subtitle_base=subtitle_base,
                translation_csvs=[TIER_B1, TIER_B2],
                level_profile=LEVEL_PROFILE_FREQUENT_B_MERGED,
            )

        jobs.append(("frequent_b", _fb))
    else:
        skips["frequent_b"] = _missing_reason(td, "frequent_b")

    if (td / TIER_RARE_C).is_file():

        def _rc() -> Dict[str, Any]:
            return judge_translations(
                td,
                subtitle_path=subtitle_path,
                model=model,
                subtitle_base=subtitle_base,
                translation_csvs=[TIER_RARE_C],
                level_profile=LEVEL_PROFILE_RARE_C,
            )

        jobs.append(("rare_c", _rc))
    else:
        skips["rare_c"] = _missing_reason(td, "rare_c")

    if (td / TIER_RARE_B).is_file():

        def _rb() -> Dict[str, Any]:
            return judge_translations(
                td,
                subtitle_path=subtitle_path,
                model=model,
                subtitle_base=subtitle_base,
                translation_csvs=[TIER_RARE_B],
                level_profile=LEVEL_PROFILE_RARE_B,
            )

        jobs.append(("rare_b", _rb))
    else:
        skips["rare_b"] = _missing_reason(td, "rare_b")

    if (td / PHRASAL_CSV).is_file():

        def _pv() -> Dict[str, Any]:
            return judge_phrasal_translations(
                td,
                subtitle_path=subtitle_path,
                model=model,
                subtitle_base=subtitle_base,
            )

        jobs.append(("phrasal", _pv))
    else:
        skips["phrasal"] = _missing_reason(td, "phrasal")

    if (td / IDIOMS_CSV).is_file():

        def _idioms() -> Dict[str, Any]:
            return judge_idiomatic_output(
                td,
                subtitle_path=subtitle_path,
                model=model,
            )

        jobs.append(("idioms", _idioms))
    else:
        skips["idioms"] = _missing_reason(td, "idioms")

    return skips, jobs


def _write_part_json(episode_out_dir: Path, part: str, payload: Dict[str, Any]) -> None:
    path = episode_out_dir / f"{part}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _prepare_episode(
    entry: Dict[str, Any],
    repo: Path,
    run_root: Path,
    model: str,
    subtitle_base: Path,
    episode_index: int,
) -> Tuple[Dict[str, Any], List[Tuple[int, str, Path, str, Callable[[], Dict[str, Any]]]]]:
    """Return (episode record, list of parallel judge jobs for this episode)."""
    rel = entry.get("translations_dir")
    if not rel:
        return (
            {
                "key": entry.get("key") or "unknown",
                "error": "manifest entry missing translations_dir",
                "status": "failed",
                "episode_index": episode_index,
                "parts": {},
            },
            [],
        )

    td = Path(rel)
    if not td.is_absolute():
        td = (repo / td).resolve()

    if not td.is_dir():
        return (
            {
                "key": entry.get("key") or _slug_from_dir(td, repo),
                "error": f"translations_dir not found: {td}",
                "status": "failed",
                "episode_index": episode_index,
                "parts": {},
            },
            [],
        )

    key = entry.get("key") or _slug_from_dir(td, repo)
    episode_out = run_root / key
    episode_out.mkdir(parents=True, exist_ok=True)

    sub_ov = entry.get("subtitle")
    subtitle_path = resolve_subtitle_path(td, sub_ov, subtitle_base)

    skips, jobs = _part_callables_for_episode(td, subtitle_path, model, subtitle_base)

    record: Dict[str, Any] = {
        "key": key,
        "translations_dir": str(td),
        "subtitle_used": str(subtitle_path) if subtitle_path else None,
        "started_at": datetime.now().isoformat(),
        "episode_index": episode_index,
        "status": "ok",
        "parts": {},
    }
    for part, reason in skips.items():
        record["parts"][part] = {"skipped": True, "skipped_reason": reason}

    parallel_jobs: List[Tuple[int, str, Path, str, Callable[[], Dict[str, Any]]]] = []
    for part, fn in jobs:
        parallel_jobs.append((episode_index, key, episode_out, part, fn))

    return record, parallel_jobs


def _run_single_judge_job(
    episode_index: int,
    key: str,
    episode_out: Path,
    part: str,
    fn: Callable[[], Dict[str, Any]],
) -> Tuple[int, str, str, Dict[str, Any]]:
    """Execute one judge; used inside thread pool."""
    try:
        payload = fn()
        _write_part_json(episode_out, part, payload)
        overall = payload.get("overall_score")
        err = payload.get("error")
        summary_entry: Dict[str, Any] = {
            "overall_score": overall,
            "error": err,
            "report_path": str(episode_out / f"{part}.json"),
        }
        return episode_index, key, part, summary_entry
    except Exception as e:
        err_payload = {
            "overall_score": None,
            "error": str(e),
            "report_path": None,
            "exception": True,
            "traceback": traceback.format_exc(),
        }
        return episode_index, key, part, err_payload


def _finalize_episode_record(rec: Dict[str, Any]) -> None:
    """Set skip_count, error_count, completed_at on a finished episode record."""
    if rec.get("status") != "ok":
        rec["completed_at"] = datetime.now().isoformat()
        return
    parts = rec.get("parts") or {}
    rec["skip_count"] = sum(1 for p in parts.values() if p.get("skipped"))
    rec["error_count"] = sum(
        1
        for p in parts.values()
        if not p.get("skipped") and (p.get("error") or p.get("exception"))
    )
    rec["completed_at"] = datetime.now().isoformat()


def _summarize(episode_records: List[Dict[str, Any]]) -> Dict[str, Any]:
    part_names = list(PART_FILES.keys())
    scores_by_part: Dict[str, List[float]] = {p: [] for p in part_names}
    skipped_by_part = {p: 0 for p in part_names}
    errors_by_part = {p: 0 for p in part_names}

    for ep in episode_records:
        if ep.get("status") != "ok":
            continue
        parts = ep.get("parts") or {}
        for p in part_names:
            info = parts.get(p) or {}
            if info.get("skipped"):
                skipped_by_part[p] += 1
                continue
            if info.get("error"):
                errors_by_part[p] += 1
                continue
            os_ = info.get("overall_score")
            if isinstance(os_, (int, float)):
                scores_by_part[p].append(float(os_))

    means = {
        p: (round(sum(v) / len(v), 2) if v else None) for p, v in scores_by_part.items()
    }
    return {
        "episodes_ok": sum(1 for e in episode_records if e.get("status") == "ok"),
        "episodes_failed": sum(1 for e in episode_records if e.get("status") != "ok"),
        "mean_overall_score_by_part": means,
        "skipped_count_by_part": skipped_by_part,
        "judge_error_count_by_part": errors_by_part,
    }


def load_manifest(path: Path) -> List[Dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("Manifest must be a JSON array")
    return data


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Run bot-output judge matrix (all judge calls parallelized up to --max-workers)."
    )
    ap.add_argument("--run", type=str, required=True, help="Label for reports/bot_judge_matrix/<run>/")
    ap.add_argument(
        "--manifest",
        type=Path,
        default=_REPO / "reports/bot_judge_matrix/manifests/default_10.json",
        help="JSON array of {translations_dir, optional subtitle, optional key}",
    )
    ap.add_argument("--model", type=str, default=None, help="OpenAI judge model (default: each module default)")
    ap.add_argument(
        "--max-workers",
        type=int,
        default=48,
        help="Max concurrent judge API calls (threads); default 48 for faster runs",
    )
    ap.add_argument(
        "--subtitle-base-dir",
        type=Path,
        default=SUBTITLE_BASE,
        help=f"Subtitle root (default: {SUBTITLE_BASE})",
    )
    args = ap.parse_args()

    api_key = resolve_openai_api_key(None)
    if not api_key:
        print("OPENAI_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    manifest_path = args.manifest
    if not manifest_path.is_absolute():
        manifest_path = _REPO / manifest_path
    entries = load_manifest(manifest_path)

    from translation_judge import JUDGE_MODEL

    model = args.model or JUDGE_MODEL

    run_root = _REPO / "reports" / "bot_judge_matrix" / args.run
    run_root.mkdir(parents=True, exist_ok=True)

    subtitle_base = args.subtitle_base_dir
    if not subtitle_base.is_absolute():
        subtitle_base = _REPO / subtitle_base
    subtitle_base = subtitle_base.resolve()

    episode_records: List[Dict[str, Any]] = []
    all_jobs: List[Tuple[int, str, Path, str, Callable[[], Dict[str, Any]]]] = []

    for i, entry in enumerate(entries):
        rec, jobs = _prepare_episode(
            entry, _REPO, run_root, model, subtitle_base, i
        )
        episode_records.append(rec)
        all_jobs.extend(jobs)

    n_tasks = len(all_jobs)
    max_workers = max(1, min(max(1, args.max_workers), n_tasks or 1))

    if all_jobs:
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            future_map = {
                ex.submit(
                    _run_single_judge_job,
                    ei,
                    key,
                    ep_out,
                    part,
                    fn,
                ): (ei, part)
                for (ei, key, ep_out, part, fn) in all_jobs
            }
            for fut in as_completed(future_map):
                ei, pt = future_map[fut]
                try:
                    ep_idx, _key, part_name, summary_part = fut.result()
                    episode_records[ep_idx]["parts"][part_name] = summary_part
                except Exception as e:
                    episode_records[ei]["parts"][pt] = {
                        "overall_score": None,
                        "error": str(e),
                        "report_path": None,
                        "exception": True,
                    }

    for rec in episode_records:
        _finalize_episode_record(rec)

    summary = {
        "run_label": args.run,
        "manifest": str(manifest_path),
        "model": model,
        "max_workers": max_workers,
        "parallel_judge_tasks": n_tasks,
        "finished_at": datetime.now().isoformat(),
        "episodes": episode_records,
        **_summarize(episode_records),
    }
    summary_path = run_root / "summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {summary_path}")


if __name__ == "__main__":
    main()
