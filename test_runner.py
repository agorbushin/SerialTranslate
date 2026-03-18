#!/usr/bin/env python3
"""
Test runner for the full translation pipeline.

Runs the complete pipeline for 10 different TV series:
  1. Clear existing tier lists and translations for the series under test
  2. Download subtitle from OpenSubtitles
  3. Run subtitle_analyzer (tier list generation + name/fantasy filtering)
  4. Run translate_tier_translations (translate tier-1 words to Russian)
  5. Run translation_judge (LLM quality evaluation of translations)

Saves all results to test_results/run_{timestamp}/.

Usage:
    python test_runner.py
    python test_runner.py --model gpt-4o
    python test_runner.py --series "Breaking Bad" --season 1 --episode 2
    python test_runner.py --dry-run   # print plan without running
"""

import argparse
import json
import shutil
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

BASE_DIR = Path(__file__).resolve().parent
SUBTITLE_BASE = BASE_DIR / "Subtitle"
TIERLIST_BASE = BASE_DIR / "Tier_lists"
TRANSLATIONS_BASE = BASE_DIR / "translations"
TEST_RESULTS_BASE = BASE_DIR / "test_results"

# ---------------------------------------------------------------------------
# 10 test series (well-known shows with reliable subtitles on OpenSubtitles)
# ---------------------------------------------------------------------------

TEST_SERIES: List[Dict[str, Any]] = [
    {"series": "Game of Thrones",   "season": 1, "episode": 1},
    {"series": "Breaking Bad",       "season": 1, "episode": 1},
    {"series": "Narcos",             "season": 1, "episode": 1},
    {"series": "The Sopranos",       "season": 1, "episode": 1},
    {"series": "The Wire",           "season": 1, "episode": 1},
    {"series": "Westworld",          "season": 1, "episode": 1},
    {"series": "Peaky Blinders",     "season": 1, "episode": 1},
    {"series": "Sherlock",           "season": 1, "episode": 1},
    {"series": "Black Mirror",       "season": 1, "episode": 1},
    {"series": "Succession",         "season": 1, "episode": 1},
]

# ---------------------------------------------------------------------------
# Helpers: API keys
# ---------------------------------------------------------------------------

def _get_openai_key() -> str:
    import os
    key = os.environ.get("OPENAI_API_KEY", "")
    if key and key.strip():
        return key.strip()
    try:
        if str(BASE_DIR) not in sys.path:
            sys.path.insert(0, str(BASE_DIR))
        from telegram_bot import OPENAI_API_KEY as _k  # type: ignore
        if _k and str(_k).strip():
            return str(_k).strip()
    except Exception:
        pass
    return ""


def _get_opensubtitles_key() -> str:
    import os
    return os.environ.get("OPENSUBTITLES_API_KEY", "8FcGUu17mWuXoaqMxKQisSvjXhvjZdct")


# ---------------------------------------------------------------------------
# Step 0: Clear existing tier lists and translations for a series/episode
# ---------------------------------------------------------------------------

def clear_existing_data(series: str, season: int, episode: int) -> Dict[str, Any]:
    """
    Remove Tier_lists and translations directories for the given series/episode.
    Returns a dict describing what was cleared.
    """
    from download_subtitles import (  # type: ignore
        get_tierlist_episode_dir,
        get_translations_episode_dir,
    )

    cleared: Dict[str, Any] = {"tier_list_dir": None, "translations_dir": None}

    tier_dir = get_tierlist_episode_dir(TIERLIST_BASE, series, season, episode)
    if tier_dir.exists():
        shutil.rmtree(tier_dir)
        cleared["tier_list_dir"] = str(tier_dir)
        print(f"    Cleared tier lists: {tier_dir.relative_to(BASE_DIR)}")
    else:
        print(f"    No tier list dir to clear: {tier_dir.relative_to(BASE_DIR)}")

    trans_dir = get_translations_episode_dir(TRANSLATIONS_BASE, series, season, episode)
    if trans_dir.exists():
        shutil.rmtree(trans_dir)
        cleared["translations_dir"] = str(trans_dir)
        print(f"    Cleared translations: {trans_dir.relative_to(BASE_DIR)}")
    else:
        print(f"    No translations dir to clear: {trans_dir.relative_to(BASE_DIR)}")

    return cleared


# ---------------------------------------------------------------------------
# Step 1: Download subtitle
# ---------------------------------------------------------------------------

def step_download(series: str, season: int, episode: int) -> Optional[Path]:
    """Download subtitle. Returns path or None on failure."""
    from download_subtitles import download_subtitle  # type: ignore

    print(f"  [1/4] Downloading subtitle for {series} S{season}E{episode}...")
    try:
        path = download_subtitle(
            series_name=series,
            season_number=season,
            episode_number=episode,
            base_dir=SUBTITLE_BASE,
            api_key=_get_opensubtitles_key(),
            languages=["en"],
        )
        if path and path.exists():
            print(f"         ✓ Downloaded: {path.relative_to(BASE_DIR)}")
            return path
        print(f"         ✗ Download returned no path.")
        return None
    except Exception as e:
        print(f"         ✗ Download error: {e}")
        return None


# ---------------------------------------------------------------------------
# Step 2: Run tier list analysis
# ---------------------------------------------------------------------------

def step_analyze(subtitle_path: Path, series: str, season: int, episode: int) -> Optional[Path]:
    """Run subtitle_analyzer pipeline. Returns episode tier-list dir or None."""
    from subtitle_analyzer import run_pipeline  # type: ignore

    print(f"  [2/4] Analyzing subtitle → tier lists...")
    try:
        episode_dir = run_pipeline(
            subtitle_path=subtitle_path,
            base_dir=BASE_DIR,
            tierlist_base_dir=TIERLIST_BASE,
            series_name=series,
            season_number=season,
            episode_number=episode,
            max_english_freq=20_000_000,
            openai_api_key=_get_openai_key() or None,
        )
        if episode_dir and (episode_dir / "tier_1_hard_usable_words.csv").exists():
            print(f"         ✓ Tier lists saved: {episode_dir.relative_to(BASE_DIR)}")
            return episode_dir
        print(f"         ✗ Tier list generation failed or produced no tier_1 file.")
        return None
    except Exception as e:
        print(f"         ✗ Analysis error: {e}")
        traceback.print_exc()
        return None


# ---------------------------------------------------------------------------
# Step 3: Translate tier-1 words
# ---------------------------------------------------------------------------

def step_translate(
    episode_dir: Path, subtitle_path: Optional[Path]
) -> Optional[Path]:
    """Run translate_tier_translations. Returns translations dir or None."""
    from translate_tier_translations import run as run_translate  # type: ignore
    from download_subtitles import get_translations_episode_dir  # type: ignore

    print(f"  [3/4] Translating tier-1 words...")
    try:
        ok, err = run_translate(
            episode_dir=episode_dir,
            subtitle_path=subtitle_path,
            api_key=_get_openai_key() or None,
            translations_base=TRANSLATIONS_BASE,
            subtitle_base=SUBTITLE_BASE,
        )
        if not ok:
            print(f"         ✗ Translation failed: {err}")
            return None

        import json as _json
        info_file = episode_dir / "episode_info.json"
        series_name = "Unknown"
        season_num = episode_num = 1
        if info_file.exists():
            data = _json.loads(info_file.read_text(encoding="utf-8"))
            series_name = data.get("series") or series_name
            season_num = int(data.get("season_number", 1))
            episode_num = int(data.get("episode_number", 1))

        trans_dir = get_translations_episode_dir(
            TRANSLATIONS_BASE, series_name, season_num, episode_num
        )
        if (trans_dir / "tier_1_translations.csv").exists():
            print(f"         ✓ Translations saved: {trans_dir.relative_to(BASE_DIR)}")
            return trans_dir
        print(f"         ✗ Translation CSV not found after run.")
        return None
    except Exception as e:
        print(f"         ✗ Translation error: {e}")
        traceback.print_exc()
        return None


# ---------------------------------------------------------------------------
# Step 4: Judge translations
# ---------------------------------------------------------------------------

def step_judge(
    translations_dir: Path,
    subtitle_path: Optional[Path],
    model: str,
) -> Dict[str, Any]:
    """Run translation_judge on the translations dir."""
    from translation_judge import judge_translations  # type: ignore

    print(f"  [4/4] Running LLM judge ({model})...")
    try:
        result = judge_translations(
            translations_dir=translations_dir,
            subtitle_path=subtitle_path,
            model=model,
            subtitle_base=SUBTITLE_BASE,
        )
        overall = result.get("overall_score", "N/A")
        error = result.get("error")
        if error:
            print(f"         ✗ Judge error: {error}")
        else:
            c1 = result.get("criterion_1", {}).get("score", "?")
            c2 = result.get("criterion_2", {}).get("score", "?")
            c3 = result.get("criterion_3", {}).get("score", "?")
            print(f"         ✓ Scores — C1:{c1}/10  C2:{c2}/10  C3:{c3}/10  Overall:{overall}/10")
        return result
    except Exception as e:
        print(f"         ✗ Judge exception: {e}")
        traceback.print_exc()
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# Run a single series end-to-end
# ---------------------------------------------------------------------------

def run_single(
    series: str,
    season: int,
    episode: int,
    model: str,
    skip_download: bool = False,
) -> Dict[str, Any]:
    """
    Run the full pipeline for one series/episode.
    Returns a result dict suitable for the JSON report.
    """
    label = f"{series} S{season}E{episode}"
    print(f"\n{'=' * 60}")
    print(f"  TESTING: {label}")
    print(f"{'=' * 60}")

    record: Dict[str, Any] = {
        "series": series,
        "season": season,
        "episode": episode,
        "label": label,
        "started_at": datetime.now().isoformat(),
        "steps": {},
    }

    # Step 0 — clear existing data
    print(f"  [0/4] Clearing existing tier lists and translations...")
    cleared = clear_existing_data(series, season, episode)
    record["cleared"] = cleared

    # Step 1 — download subtitle
    subtitle_path: Optional[Path] = None
    if not skip_download:
        subtitle_path = step_download(series, season, episode)
    else:
        # Check if subtitle already exists
        from download_subtitles import get_subtitle_path  # type: ignore
        candidate = get_subtitle_path(SUBTITLE_BASE, series, season, episode)
        if candidate.exists():
            subtitle_path = candidate
            print(f"  [1/4] Using existing subtitle: {candidate.relative_to(BASE_DIR)}")
        else:
            print(f"  [1/4] Skipped download (--skip-download) and no cached subtitle found.")

    record["steps"]["download"] = {
        "success": subtitle_path is not None,
        "subtitle_path": str(subtitle_path) if subtitle_path else None,
    }
    if subtitle_path is None:
        record["status"] = "FAILED_DOWNLOAD"
        record["completed_at"] = datetime.now().isoformat()
        return record

    # Step 2 — analyze
    episode_dir = step_analyze(subtitle_path, series, season, episode)
    record["steps"]["analyze"] = {
        "success": episode_dir is not None,
        "episode_dir": str(episode_dir) if episode_dir else None,
    }
    if episode_dir is None:
        record["status"] = "FAILED_ANALYZE"
        record["completed_at"] = datetime.now().isoformat()
        return record

    # Count tier-1 words
    tier1_csv = episode_dir / "tier_1_hard_usable_words.csv"
    word_count = 0
    if tier1_csv.exists():
        import csv as _csv
        with open(tier1_csv, encoding="utf-8") as f:
            word_count = sum(1 for row in _csv.DictReader(f))
    record["steps"]["analyze"]["tier1_word_count"] = word_count

    # Step 3 — translate
    translations_dir = step_translate(episode_dir, subtitle_path)
    record["steps"]["translate"] = {
        "success": translations_dir is not None,
        "translations_dir": str(translations_dir) if translations_dir else None,
    }
    if translations_dir is None:
        record["status"] = "FAILED_TRANSLATE"
        record["completed_at"] = datetime.now().isoformat()
        return record

    # Step 4 — judge
    judgment = step_judge(translations_dir, subtitle_path, model)
    record["steps"]["judge"] = judgment
    record["overall_score"] = judgment.get("overall_score")
    record["judge_error"] = judgment.get("error")

    record["status"] = "ERROR_JUDGE" if judgment.get("error") else "PASSED"
    record["completed_at"] = datetime.now().isoformat()
    return record


# ---------------------------------------------------------------------------
# Save report
# ---------------------------------------------------------------------------

def save_report(results: List[Dict[str, Any]], run_dir: Path) -> None:
    """Save JSON report and human-readable markdown summary."""
    run_dir.mkdir(parents=True, exist_ok=True)

    # Full JSON
    json_path = run_dir / "full_report.json"
    json_path.write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\nFull JSON report: {json_path.relative_to(BASE_DIR)}")

    # Markdown summary
    md_lines = [
        "# Translation Pipeline Test Report",
        f"\nRun: {run_dir.name}",
        f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "\n## Results Summary\n",
        "| Series | S/E | Status | C1 Trans | C2 Entities | C3 C-Level | Overall |",
        "|--------|-----|--------|----------|-------------|------------|---------|",
    ]

    for r in results:
        label = r.get("label", "?")
        s, e = r.get("season", "?"), r.get("episode", "?")
        status = r.get("status", "?")
        judgment = r.get("steps", {}).get("judge", {})
        c1 = judgment.get("criterion_1", {}).get("score", "—")
        c2 = judgment.get("criterion_2", {}).get("score", "—")
        c3 = judgment.get("criterion_3", {}).get("score", "—")
        overall = r.get("overall_score", "—")
        series = r.get("series", "?")
        md_lines.append(
            f"| {series} | S{s}E{e} | {status} | {c1}/10 | {c2}/10 | {c3}/10 | {overall}/10 |"
        )

    # Averages
    scores = [r.get("overall_score") for r in results if isinstance(r.get("overall_score"), (int, float))]
    if scores:
        avg = round(sum(scores) / len(scores), 1)
        md_lines.append(f"\n**Average overall score: {avg}/10** (across {len(scores)} completed judgments)")

    md_lines.append("\n## Per-Series Details\n")
    for r in results:
        label = r.get("label", "?")
        md_lines.append(f"### {label}")
        status = r.get("status", "?")
        md_lines.append(f"- **Status:** {status}")
        step_analyze = r.get("steps", {}).get("analyze", {})
        if step_analyze.get("tier1_word_count"):
            md_lines.append(f"- **Tier-1 words:** {step_analyze['tier1_word_count']}")
        judgment = r.get("steps", {}).get("judge", {})
        if judgment.get("error"):
            md_lines.append(f"- **Judge error:** {judgment['error']}")
        else:
            summary = judgment.get("summary", "")
            if summary:
                md_lines.append(f"- **Judge summary:** {summary}")
            for cname, clabel in [
                ("criterion_1", "Completeness & Correctness"),
                ("criterion_2", "No Non-English Entities"),
                ("criterion_3", "C-Level Vocabulary"),
            ]:
                c = judgment.get(cname, {})
                if c:
                    score = c.get("score", "?")
                    reasoning = c.get("reasoning", "")[:300]
                    md_lines.append(f"- **{clabel}:** {score}/10 — {reasoning}")
                    issues = c.get("issues") or c.get("violations") or c.get("not_c_level") or []
                    if issues:
                        issue_words = []
                        for item in issues[:5]:
                            if isinstance(item, dict):
                                issue_words.append(item.get("word") or str(item))
                            else:
                                issue_words.append(str(item))
                        if issue_words:
                            md_lines.append(f"  - Issues/violations: {', '.join(issue_words)}")
        md_lines.append("")

    md_path = run_dir / "summary.md"
    md_path.write_text("\n".join(md_lines), encoding="utf-8")
    print(f"Markdown summary:   {md_path.relative_to(BASE_DIR)}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Test runner: clears tier lists, downloads subtitles, runs analysis + translation + judge "
            "for 10 predefined TV series."
        )
    )
    parser.add_argument(
        "--model",
        default="gpt-4o",
        help="OpenAI model for the LLM judge (default: gpt-4o)",
    )
    parser.add_argument(
        "--series",
        default=None,
        help="Run only this series (case-sensitive, must match TEST_SERIES list or be a new name)",
    )
    parser.add_argument(
        "--season",
        type=int,
        default=None,
        help="Season number when --series is specified",
    )
    parser.add_argument(
        "--episode",
        type=int,
        default=None,
        help="Episode number when --series is specified",
    )
    parser.add_argument(
        "--skip-download",
        action="store_true",
        help="Skip subtitle download (use cached subtitle if present); useful for re-running judge",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the test plan without executing anything",
    )
    args = parser.parse_args()

    # Build series list to test
    if args.series:
        season = args.season or 1
        episode = args.episode or 1
        series_to_test: List[Dict[str, Any]] = [
            {"series": args.series, "season": season, "episode": episode}
        ]
    else:
        series_to_test = TEST_SERIES

    if args.dry_run:
        print("DRY RUN — test plan (no changes will be made):")
        print(f"  Judge model: {args.model}")
        print(f"  Series to test ({len(series_to_test)}):")
        for s in series_to_test:
            print(f"    - {s['series']} S{s['season']}E{s['episode']}")
        print("\n  Steps per series:")
        print("    0. Clear Tier_lists/{series}/Season N/E and translations/{series}/Season N/E")
        print("    1. Download subtitle from OpenSubtitles")
        print("    2. Run subtitle_analyzer (tier lists + name filter)")
        print("    3. Run translate_tier_translations (GPT-4o-mini)")
        print(f"    4. Run translation_judge ({args.model})")
        print("\n  Results will be saved to test_results/run_YYYYMMDD_HHMMSS/")
        return

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = TEST_RESULTS_BASE / f"run_{timestamp}"
    run_dir.mkdir(parents=True, exist_ok=True)

    print(f"Test run started: {timestamp}")
    print(f"Series to test: {len(series_to_test)}")
    print(f"Judge model: {args.model}")
    print(f"Results dir: {run_dir.relative_to(BASE_DIR)}")

    all_results: List[Dict[str, Any]] = []
    for spec in series_to_test:
        result = run_single(
            series=spec["series"],
            season=spec["season"],
            episode=spec["episode"],
            model=args.model,
            skip_download=args.skip_download,
        )
        all_results.append(result)

        # Save incremental JSON after each series so partial results are preserved
        (run_dir / "full_report.json").write_text(
            json.dumps(all_results, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    save_report(all_results, run_dir)

    # Print final score summary
    print(f"\n{'=' * 60}")
    print("FINAL SUMMARY")
    print(f"{'=' * 60}")
    passed = sum(1 for r in all_results if r.get("status") == "PASSED")
    failed = len(all_results) - passed
    scores = [
        r.get("overall_score")
        for r in all_results
        if isinstance(r.get("overall_score"), (int, float))
    ]
    print(f"  Passed: {passed}/{len(all_results)}")
    print(f"  Failed: {failed}/{len(all_results)}")
    if scores:
        print(f"  Average judge score: {round(sum(scores) / len(scores), 1)}/10")
    for r in all_results:
        label = r.get("label", "?")
        status = r.get("status", "?")
        overall = r.get("overall_score", "—")
        print(f"    {label:40s} {status:20s} {overall}/10")

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
