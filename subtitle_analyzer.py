#!/usr/bin/env python3
"""
Subtitle Word Frequency Analyzer
Analyzes subtitles and categorizes words into tiers based on frequency in series vs English.
Writes tier lists to Tier_lists/{series_name}/Season N/{episode_number}/.
"""

import csv
import json
import re
import threading
import zipfile
from concurrent.futures import ThreadPoolExecutor
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import argparse

# Optional: matplotlib and pandas (for plot and vocabulary xlsx)
try:
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False
try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False

PIPELINE_FINGERPRINT_VERSION = 2
DEFAULT_MIN_EPISODE_COUNT = 3
FINGERPRINT_FILENAME = ".pipeline_fingerprint.json"
TIER_4_RARE_B_WORDS_CSV = "tier_4_rare_b_words.csv"
TIER_4_RARE_C_WORDS_CSV = "tier_4_rare_c_words.csv"


def _rare_tier_outputs_complete(episode_dir: Path) -> bool:
    """True when post-split rare-in-series word lists exist (added after early tier caches)."""
    return (
        (episode_dir / TIER_4_RARE_B_WORDS_CSV).is_file()
        and (episode_dir / TIER_4_RARE_C_WORDS_CSV).is_file()
    )

_preload_lock = threading.Lock()
_preload_cache: Dict[str, Tuple[Set[str], Set[str], Set[str], Dict[str, int], Dict[str, str]]] = {}


def load_filter_from_csv(filter_file: Path, singularize: bool = True) -> Set[str]:
    """Load words from a filter CSV file (first column = word)."""
    words = set()
    if not filter_file.exists():
        return words
    try:
        with open(filter_file, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames:
                word_column = reader.fieldnames[0]
                loaded_words: List[str] = []
                for row in reader:
                    word = row[word_column].strip().lower()
                    if word:
                        loaded_words.append(word)
                words.update(loaded_words)
                if singularize and loaded_words:
                    try:
                        from lemmatizer import lemmatize_words, is_lemmatization_enabled
                        if is_lemmatization_enabled():
                            words.update(lemmatize_words(loaded_words))
                        else:
                            words.update(to_singular(w) for w in loaded_words)
                    except ImportError:
                        words.update(to_singular(w) for w in loaded_words)
    except Exception as e:
        print(f"Warning: Could not load filter from {filter_file}: {e}")
    return words


def load_all_filters(
    filters_dir: Path, exclude_oxford: bool = False
) -> Tuple[Set[str], Set[str], Set[str]]:
    """Load filters. Returns (basic_filters, oxford_filter, easy_words_filter)."""
    basic_filters = set()
    oxford_filter = set()
    easy_words_filter = set()
    if not filters_dir.exists():
        return basic_filters, oxford_filter, easy_words_filter
    for csv_file in sorted(filters_dir.glob("*.csv")):
        words = load_filter_from_csv(csv_file)
        if exclude_oxford:
            if "oxford" in csv_file.name.lower():
                oxford_filter.update(words)
            elif "easy" in csv_file.name.lower():
                easy_words_filter.update(words)
            else:
                basic_filters.update(words)
        else:
            basic_filters.update(words)
    return basic_filters, oxford_filter, easy_words_filter


def to_singular(word: str) -> str:
    """Simple rule-based singular form."""
    if len(word) <= 3:
        return word
    word_lower = word.lower()
    if word_lower.endswith("ies") and len(word_lower) > 4:
        return word_lower[:-3] + "y"
    if word_lower.endswith(("ches", "shes", "xes", "zes", "ses")) and len(word_lower) > 4:
        return word_lower[:-2]
    if word_lower.endswith("ves") and len(word_lower) > 4:
        return word_lower[:-3] + "f"
    if word_lower.endswith("s") and not word_lower.endswith(("ss", "us", "is", "as", "os")):
        if len(word_lower) > 3:
            return word_lower[:-1]
    return word_lower


def parse_srt_content(content: str, excluded_words: Set[str]) -> List[str]:
    """Parse SRT text and return list of words (lowercase, filtered)."""
    content = re.sub(
        r"\d{2}:\d{2}:\d{2}[,.]\d{3}\s*-->\s*\d{2}:\d{2}:\d{2}[,.]\d{3}", "", content
    )
    content = re.sub(r"^\d+$", "", content, flags=re.MULTILINE)
    content = re.sub(r"<[^>]+>", "", content)
    content = re.sub(r"\[.*?\]", "", content)
    content = re.sub(r"[^\w\s']", " ", content)
    words = re.findall(r"\b[a-z']+\b", content.lower())
    words = [w for w in words if "'" not in w]
    try:
        from lemmatizer import lemmatize_words, is_lemmatization_enabled
        if is_lemmatization_enabled():
            words = lemmatize_words(words)
        else:
            words = [to_singular(w) for w in words]
    except ImportError:
        words = [to_singular(w) for w in words]
    words = [w for w in words if w not in excluded_words]
    return words


def parse_srt_file_with_content(srt_path: Path, excluded_words: Set[str]) -> Tuple[List[str], str]:
    """Read SRT once; return (word list for tiering, raw file text for LLM / translate handoff)."""
    with open(srt_path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()
    return parse_srt_content(content, excluded_words), content


def parse_srt_file(srt_path: Path, excluded_words: Set[str]) -> List[str]:
    """Parse SRT file and return list of words (lowercase, filtered)."""
    words, _ = parse_srt_file_with_content(srt_path, excluded_words)
    return words


def extract_words_from_zip_with_content(
    zip_path: Path, excluded_words: Set[str]
) -> Tuple[Counter, str]:
    """Extract first .srt from ZIP; return (word Counter, raw SRT text)."""
    with zipfile.ZipFile(zip_path, "r") as zf:
        srt_files = [f for f in zf.namelist() if f.endswith(".srt")]
        if not srt_files:
            raise ValueError(f"No SRT in {zip_path}")
        content = zf.read(srt_files[0]).decode("utf-8", errors="ignore")
        words = parse_srt_content(content, excluded_words)
    return Counter(words), content


def extract_words_from_zip(zip_path: Path, excluded_words: Set[str]) -> Counter:
    """Extract SRT from ZIP and return word Counter."""
    c, _ = extract_words_from_zip_with_content(zip_path, excluded_words)
    return c


def load_vocabulary_levels(vocab_file: Path) -> Dict[str, str]:
    """Load word -> level (A1–C2) from Excel. Returns {} if missing or no pandas."""
    if not HAS_PANDAS or not vocab_file.exists():
        return {}
    try:
        df = pd.read_excel(vocab_file)
        if "word" not in df.columns or "level" not in df.columns:
            return {}
        word_levels = {}
        level_order = {"A1": 0, "A2": 1, "B1": 2, "B2": 3, "C1": 4, "C2": 5}
        for _, row in df.iterrows():
            word = str(row["word"]).lower().strip()
            level = str(row["level"]).strip().upper()
            if level in level_order:
                if word not in word_levels or level_order[level] < level_order[word_levels[word]]:
                    word_levels[word] = level
        return word_levels
    except Exception as e:
        print(f"Warning: Could not load vocabulary levels: {e}")
        return {}


_VALID_XLSX_CEFR_LEVELS = frozenset({"A1", "A2", "B1", "B2", "C1", "C2"})


def word_has_xlsx_cefr(word: str, vocabulary_levels: Dict[str, str]) -> bool:
    """True if word appears in the vocabulary workbook with a standard CEFR band."""
    w = (word or "").strip().lower()
    if not w:
        return False
    lvl = vocabulary_levels.get(w)
    if not lvl:
        return False
    return str(lvl).strip().upper() in _VALID_XLSX_CEFR_LEVELS


def map_gpt_coarse_to_xlsx_level(coarse: str) -> str:
    """Map GPT coarse label to a fine level understood by categorize_words."""
    c = (coarse or "").strip().lower()
    if c == "c":
        return "C1"
    if c == "b":
        return "B2"
    if c == "a":
        return "A2"
    return "N/A"


def collect_words_needing_gpt_cefr(
    series_freqs: Counter,
    english_freqs: Dict[str, int],
    vocabulary_levels: Dict[str, str],
    series_threshold: int,
    english_threshold: int,
    min_episode_count: int,
    oxford_filter: Set[str],
    easy_words_filter: Set[str],
) -> List[str]:
    """
    Lemmas frequent enough in the episode, in low-English learner quadrants, lacking xlsx CEFR,
    and not Oxford/easy (filtered later anyway).
    """
    out: List[str] = []
    seen: Set[str] = set()
    for word, series_count in series_freqs.items():
        if series_count < min_episode_count:
            continue
        if word in easy_words_filter or word in oxford_filter:
            continue
        if word_has_xlsx_cefr(word, vocabulary_levels):
            continue
        english_count = english_freqs.get(word, 0)
        is_high_series = series_count >= series_threshold
        is_high_english = english_count >= english_threshold
        would_be_tier1 = not is_high_english and is_high_series
        would_be_tier2 = not is_high_english and not is_high_series
        if not (would_be_tier1 or would_be_tier2):
            continue
        wl = word.lower()
        if wl not in seen:
            seen.add(wl)
            out.append(word)
    out.sort(key=str.lower)
    return out


def build_effective_vocabulary_levels(
    vocabulary_levels: Dict[str, str],
    gpt_coarse_by_word: Dict[str, str],
) -> Dict[str, str]:
    """Copy xlsx map and overlay GPT coarse labels (normalized to C1/B2/A2)."""
    effective = dict(vocabulary_levels)
    for w, coarse in gpt_coarse_by_word.items():
        key = (w or "").strip().lower()
        if not key:
            continue
        mapped = map_gpt_coarse_to_xlsx_level(coarse)
        if mapped != "N/A":
            effective[key] = mapped
    return effective


def load_english_frequencies(freq_file: Path) -> Dict[str, int]:
    """Load English word frequencies (word -> count), combined by lemma/singular."""
    frequencies = {}
    with open(freq_file, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            word = row["word"].lower()
            count = int(row["count"])
            frequencies[word] = count
    try:
        from lemmatizer import lemmatize_words, is_lemmatization_enabled
        use_lemma = is_lemmatization_enabled()
    except ImportError:
        use_lemma = False
        lemmatize_words = None  # type: ignore
    singular_freqs = {}
    words_in_order = list(frequencies.keys())
    if use_lemma and lemmatize_words is not None:
        lemmas = lemmatize_words(words_in_order)
    else:
        lemmas = [to_singular(w) for w in words_in_order]
    for word, lemma in zip(words_in_order, lemmas):
        count = frequencies[word]
        singular_freqs[lemma] = singular_freqs.get(lemma, 0) + count
    for word, count in frequencies.items():
        if word not in singular_freqs:
            singular_freqs[word] = count
    return singular_freqs


def calculate_thresholds(
    series_freqs: Counter, english_freqs: Dict[str, int]
) -> Tuple[int, int, int, int]:
    """Return (series_threshold, english_threshold, series_median, english_median)."""
    series_values = sorted(series_freqs.values())
    if not series_values:
        return 1, 1, 1, 1
    idx = len(series_values) * 2 // 3
    series_threshold = series_values[min(idx, len(series_values) - 1)]
    series_median = series_values[len(series_values) // 2]
    english_values = [english_freqs.get(w, 0) for w in series_freqs if english_freqs.get(w, 0) > 0]
    if not english_values:
        return series_threshold, 1, series_median, 1
    english_values_sorted = sorted(english_values)
    idx_e = len(english_values_sorted) * 2 // 3
    english_threshold = english_values_sorted[min(idx_e, len(english_values_sorted) - 1)]
    english_median = english_values_sorted[len(english_values_sorted) // 2]
    return series_threshold, english_threshold, series_median, english_median


def categorize_words(
    series_freqs: Counter,
    english_freqs: Dict[str, int],
    max_english_freq: Optional[int] = None,
    oxford_filter: Optional[Set[str]] = None,
    easy_words_filter: Optional[Set[str]] = None,
    vocabulary_levels: Optional[Dict[str, str]] = None,
    series_threshold: Optional[int] = None,
    english_threshold: Optional[int] = None,
    min_episode_count: Optional[int] = DEFAULT_MIN_EPISODE_COUNT,
) -> Dict[str, List[Tuple]]:
    """Categorize words into 5 tiers. Returns dict of tier_key -> list of (word, series_count, english_count, ...).
    If min_episode_count is set and > 0, low-English learner quadrants with fewer episode mentions go to tier_2_random.
    Pass None to disable."""
    if series_threshold is None or english_threshold is None:
        series_threshold, english_threshold, _, _ = calculate_thresholds(
            series_freqs, english_freqs
        )
    oxford_filter = oxford_filter or set()
    easy_words_filter = easy_words_filter or set()
    vocabulary_levels = vocabulary_levels or {}
    tiers = {
        "tier_1_hard_usable": [],
        "tier_2_random": [],
        "tier_3_common": [],
        "tier_4_rare_in_series": [],
        "tier_5_filtered": [],
        "tier_b1_words": [],
        "tier_b2_words": [],
    }
    LEVELS_BELOW_C = ("A1", "A2", "B1", "B2")
    for word, series_count in series_freqs.items():
        english_count = english_freqs.get(word, 0)
        # Case-insensitive lookup: vocabulary file keys are lowercase
        vocab_level = vocabulary_levels.get(word, "N/A")
        level_str = str(vocab_level).strip().upper()
        is_high_series = series_count >= series_threshold
        is_high_english = english_count >= english_threshold
        would_be_tier1 = not is_high_english and is_high_series
        would_be_tier2 = not is_high_english and not is_high_series
        freq_ok = True
        if min_episode_count is not None and min_episode_count > 0:
            freq_ok = series_count >= min_episode_count
        if (would_be_tier1 or would_be_tier2) and not freq_ok:
            tiers["tier_2_random"].append((word, series_count, english_count, vocab_level))
            continue
        is_filtered = False
        filter_reason = ""
        if word in easy_words_filter:
            is_filtered, filter_reason = True, "Easy word (easy_words.csv)"
        elif word in oxford_filter:
            is_filtered, filter_reason = True, "Oxford 3000"
        elif (would_be_tier1 or would_be_tier2) and max_english_freq is not None and english_count > max_english_freq:
            is_filtered, filter_reason = True, f"High English frequency ({english_count:,} > {max_english_freq:,})"
        elif (would_be_tier1 or would_be_tier2) and level_str in ("A1", "A2"):
            is_filtered, filter_reason = True, f"Vocabulary level below C ({level_str})"
        if is_filtered and (would_be_tier1 or would_be_tier2):
            tiers["tier_5_filtered"].append((word, series_count, english_count, filter_reason, vocab_level))
            continue
        if (would_be_tier1 or would_be_tier2) and level_str == "B1":
            tiers["tier_b1_words"].append((word, series_count, english_count, vocab_level))
            continue
        if (would_be_tier1 or would_be_tier2) and level_str == "B2":
            tiers["tier_b2_words"].append((word, series_count, english_count, vocab_level))
            continue
        if (would_be_tier1 or would_be_tier2) and level_str in LEVELS_BELOW_C:
            tiers["tier_5_filtered"].append(
                (word, series_count, english_count, f"Vocabulary level below C ({level_str})", vocab_level)
            )
            continue
        if would_be_tier1:
            tiers["tier_1_hard_usable"].append((word, series_count, english_count, vocab_level))
        elif would_be_tier2:
            tiers["tier_2_random"].append((word, series_count, english_count, vocab_level))
        elif is_high_english and is_high_series:
            tiers["tier_3_common"].append((word, series_count, english_count, vocab_level))
        elif is_high_english and not is_high_series:
            tiers["tier_4_rare_in_series"].append((word, series_count, english_count, vocab_level))
    for key in tiers:
        tiers[key].sort(key=lambda x: x[1], reverse=True)
    return tiers


def extract_series_info(subtitle_path: Path) -> Dict[str, Optional[str]]:
    """Extract series name and S##E## from filename."""
    filename = subtitle_path.stem
    m = re.search(r"[Ss](\d+)[Ee](\d+)", filename)
    season = episode = None
    series_name = filename
    if m:
        season = f"S{int(m.group(1)):02d}"
        episode = f"E{int(m.group(2)):02d}"
        series_name = filename[: m.start()].strip("._")
    series_name = re.sub(r"\.(19|20)\d{2}$", "", series_name)
    series_name = series_name.replace(".", " ").replace("_", " ").strip()
    if series_name and not any(c.isupper() for c in series_name[1:]):
        series_name = series_name.title()
    return {"series": series_name or "Unknown", "season": season, "episode": episode}


def extract_movie_info(subtitle_path: Path) -> Dict[str, Optional[str]]:
    """Extract movie name and year from path like .../Movies/Inception/Inception_2010.srt."""
    parts = subtitle_path.parts
    movie_name = None
    year = None
    if "Movies" in parts:
        idx = parts.index("Movies")
        if idx + 1 < len(parts):
            movie_name = parts[idx + 1]
        m = re.search(r"_?(19|20)\d{2}$", subtitle_path.stem)
        if m:
            year = m.group(0).lstrip("_")  # e.g. "2010"
    if not movie_name:
        stem = subtitle_path.stem
        m = re.search(r"^(.+?)_((?:19|20)\d{2})$", stem)
        if m:
            movie_name = m.group(1).replace("_", " ").replace(".", " ").strip().title()
            year = m.group(2)  # full 4-digit year
        else:
            movie_name = stem.replace("_", " ").replace(".", " ").strip().title() or "Unknown"
    return {"series": movie_name or "Unknown", "year": year}


def save_tierlist_results_to_dir(
    tiers: Dict[str, List],
    output_episode_dir: Path,
    subtitle_path: Path,
    series_threshold: int,
    english_threshold: int,
    max_english_freq: int,
    series_name: str,
    season_number: int,
    episode_number: int,
    excluded_words: Optional[Set[str]] = None,
    c1_assessment: Optional[Dict[str, str]] = None,
    is_movie: bool = False,
    movie_year: Optional[int] = None,
    min_episode_count: Optional[int] = None,
    gpt_coarse_cefr: Optional[Dict[str, str]] = None,
) -> None:
    """Write tier CSVs, episode_info.json, and README to output_episode_dir (Tier_lists layout).
    If excluded_words is set, rows whose word (lowercase) is in it are omitted (name/fantasy filter).
    Words with vocabulary level below C (A1, A2, B1, B2) are omitted when level is determined,
    except dedicated B1/B2 tier outputs.
    For tier-1 specifically, words rated "low" by c1_assessment (C1 speakers likely know them)
    are also excluded so the list contains only genuinely advanced vocabulary.
    """
    excluded_lower = {w.lower() for w in (excluded_words or set())}
    LEVELS_BELOW_C = ("A1", "A2", "B1", "B2")

    # Build lowercase c1_assessment lookup for fast filtering
    c1_lower: Dict[str, str] = {}
    if c1_assessment:
        for w, v in c1_assessment.items():
            c1_lower[w.lower()] = str(v).lower()

    def keep(item: tuple, *, apply_level_filter: bool = True, apply_c1_filter: bool = False) -> bool:
        word = (item[0] or "").strip().lower()
        if word in excluded_lower:
            return False
        # Drop words the GPT c1_assessment rated "low" (C1 speakers very likely know them)
        if apply_c1_filter and c1_lower:
            rating = c1_lower.get(word, "")
            if rating == "low":
                return False
        if apply_level_filter:
            vocab = (item[-1] if item else None) or ""
            level = str(vocab).strip().upper()
            if level in LEVELS_BELOW_C:
                return False
        return True

    output_episode_dir.mkdir(parents=True, exist_ok=True)
    season_label = (
        f"Movie ({movie_year})" if is_movie and movie_year
        else "Movie" if is_movie
        else f"Season {season_number}"
    )
    tier_files_map = {
        "tier_1_hard_usable": "tier_1_hard_usable_words.csv",
        "tier_2_random": "tier_2_random_words.csv",
        "tier_3_common": "tier_3_common_words.csv",
        "tier_4_rare_in_series": "tier_4_rare_in_series.csv",
        "tier_5_filtered": "tier_5_filtered_words.csv",
        "tier_b1_words": "tier_b1_words.csv",
        "tier_b2_words": "tier_b2_words.csv",
    }
    word_counts = {}
    def _write_tier_csv(tier_key: str, filename: str) -> Tuple[str, int]:
        # Tier 5 holds filtered-out words; do not re-filter by level or c1 when writing
        apply_level = tier_key not in ("tier_5_filtered", "tier_b1_words", "tier_b2_words")
        # Only apply the c1_assessment "low" filter to tier-1 (the "hard words to learn" list)
        apply_c1 = tier_key == "tier_1_hard_usable"
        items = [it for it in tiers.get(tier_key, []) if keep(it, apply_level_filter=apply_level, apply_c1_filter=apply_c1)]
        count = len(items)
        filepath = output_episode_dir / filename
        with open(filepath, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if tier_key == "tier_5_filtered":
                w.writerow(["word", "series_frequency", "english_frequency", "filter_reason", "vocabulary_level"])
                for item in items:
                    if len(item) >= 5:
                        w.writerow(list(item[:5]))
                    elif len(item) == 4:
                        w.writerow([*item[:3], item[3], "N/A"])
                    else:
                        w.writerow([*item[:3], "Unknown", "N/A"])
            else:
                w.writerow(["word", "series_frequency", "english_frequency", "vocabulary_level"])
                for item in items:
                    if len(item) >= 4:
                        w.writerow(list(item[:4]))
                    else:
                        w.writerow([*item[:3], "N/A"])
        return tier_key, count

    with ThreadPoolExecutor(max_workers=len(tier_files_map)) as pool:
        futures = [
            pool.submit(_write_tier_csv, tier_key, filename)
            for tier_key, filename in tier_files_map.items()
        ]
        for future in futures:
            tier_key, count = future.result()
            word_counts[tier_key] = count

    # Split tier 4 (high English freq, low series freq) into C1–C2 vs B1–B2 rare-in-series lists.
    # Only true CEFR C1/C2 go to rare_c; N/A/unknown must not (they are not "C-level" — often basic words
    # missing from the vocabulary sheet, e.g. men, color).
    raw_t4 = tiers.get("tier_4_rare_in_series", [])
    rare_c_items: List[Tuple] = []
    rare_b_items: List[Tuple] = []
    for item in raw_t4:
        if len(item) < 4:
            continue
        word = (item[0] or "").strip()
        if not word or word.lower() in excluded_lower:
            continue
        lvl = str(item[3]).strip().upper()
        if lvl in ("B1", "B2"):
            rare_b_items.append(item)
        elif lvl in ("C1", "C2"):
            rare_c_items.append(item)
        # A1, A2, N/A, unknown: omit from both rare-in-series translation lists
    for fname, items in (
        ("tier_4_rare_c_words.csv", rare_c_items),
        ("tier_4_rare_b_words.csv", rare_b_items),
    ):
        path = output_episode_dir / fname
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["word", "series_frequency", "english_frequency", "vocabulary_level"])
            for it in items:
                if len(it) >= 4:
                    w.writerow(list(it[:4]))
                else:
                    w.writerow([*it[:3], "N/A"])
    word_counts["tier_4_rare_c_words"] = len(rare_c_items)
    word_counts["tier_4_rare_b_words"] = len(rare_b_items)

    metadata = {
        "series": series_name,
        "season": season_label,
        "season_number": season_number,
        "episode_number": episode_number,
        "subtitle_file": subtitle_path.name,
        "analysis_date": datetime.now().isoformat(),
        "thresholds": {
            "series_threshold": series_threshold,
            "english_threshold": english_threshold,
            "max_english_freq": max_english_freq,
            **({"min_episode_count": min_episode_count} if min_episode_count is not None else {}),
        },
        "word_counts": word_counts,
    }
    if is_movie and movie_year is not None:
        metadata["is_movie"] = True
        metadata["year"] = movie_year
    if excluded_words:
        metadata["excluded_names_fantasy_count"] = len(excluded_words)
    if excluded_words is not None or c1_assessment or gpt_coarse_cefr:
        payload: Dict = {"excluded": sorted(excluded_words or []), "series": series_name}
        if c1_assessment:
            payload["c1_assessment"] = c1_assessment
        if gpt_coarse_cefr:
            payload["gpt_coarse_cefr"] = dict(sorted(gpt_coarse_cefr.items(), key=lambda x: x[0].lower()))
        (output_episode_dir / "excluded_names_fantasy.json").write_text(
            json.dumps(payload, indent=2),
            encoding="utf-8",
        )
    (output_episode_dir / "episode_info.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    ep_label = "" if is_movie else f", Episode {episode_number}"
    readme = (
        f"# {series_name} - Word Tier List\n\n"
        f"**{season_label}{ep_label}**\n\n"
        f"**Subtitle**: `{subtitle_path.name}`\n\n"
        f"**Analysis**: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
        "## Word counts\n\n"
        f"- Tier 1 (Hard Usable): {word_counts.get('tier_1_hard_usable', 0)}\n"
        f"- Tier 2 (Random): {word_counts.get('tier_2_random', 0)}\n"
        f"- Tier 3 (Common): {word_counts.get('tier_3_common', 0)}\n"
        f"- Tier 4 (Rare in Series): {word_counts.get('tier_4_rare_in_series', 0)}\n"
        f"- Rare in series (C1–C2): {word_counts.get('tier_4_rare_c_words', 0)}\n"
        f"- Rare in series (B1–B2): {word_counts.get('tier_4_rare_b_words', 0)}\n"
        f"- Tier 5 (Filtered): {word_counts.get('tier_5_filtered', 0)}\n"
        f"- Tier B1 (Intermediate): {word_counts.get('tier_b1_words', 0)}\n"
        f"- Tier B2 (Upper-Intermediate): {word_counts.get('tier_b2_words', 0)}\n"
    )
    (output_episode_dir / "README.md").write_text(readme, encoding="utf-8")
    print(f"Saved tier lists to {output_episode_dir}/")
    print(f"  Tier 1 (hard usable): {word_counts.get('tier_1_hard_usable', 0)} words")


def create_frequency_plot(
    tiers: Dict[str, List],
    series_threshold: int,
    english_threshold: int,
    output_dir: Path,
) -> None:
    """Optional: save frequency matrix plot."""
    if not HAS_MATPLOTLIB:
        return
    try:
        fig, ax = plt.subplots(figsize=(10, 8))
        colors = {
            "tier_1_hard_usable": "#2E7D32",
            "tier_2_random": "#9E9E9E",
            "tier_3_common": "#1976D2",
            "tier_4_rare_in_series": "#F57C00",
        }
        for tier_key, label in [
            ("tier_1_hard_usable", "Tier 1"),
            ("tier_2_random", "Tier 2"),
            ("tier_3_common", "Tier 3"),
            ("tier_4_rare_in_series", "Tier 4"),
        ]:
            words = tiers.get(tier_key, [])
            if not words:
                continue
            ax.scatter(
                [x[2] for x in words],
                [x[1] for x in words],
                c=colors[tier_key],
                label=label,
                alpha=0.6,
                s=30,
            )
        ax.axhline(y=series_threshold, color="red", linestyle="--", alpha=0.7)
        ax.axvline(x=english_threshold, color="red", linestyle="--", alpha=0.7)
        ax.set_xscale("log")
        ax.set_yscale("log")
        ax.legend()
        ax.set_xlabel("English frequency")
        ax.set_ylabel("Series frequency")
        plt.tight_layout()
        out = output_dir / "word_frequency_matrix.png"
        plt.savefig(out, dpi=150, bbox_inches="tight")
        plt.close()
        print(f"Saved plot to {out}")
    except Exception as e:
        print(f"Could not create plot: {e}")


def _fingerprint_preload_sources(filters_dir: Path, freq_path: Path, vocab_file: Path) -> str:
    parts: List[str] = []
    if filters_dir.exists():
        for p in sorted(filters_dir.glob("*.csv")):
            try:
                st = p.stat()
                parts.append(f"{p.name}:{st.st_mtime_ns}:{st.st_size}")
            except OSError:
                parts.append(f"{p.name}:missing")
    else:
        parts.append("no_filters_dir")
    if freq_path.exists():
        try:
            st = freq_path.stat()
            parts.append(f"freq:{st.st_mtime_ns}:{st.st_size}")
        except OSError:
            parts.append("freq:missing")
    else:
        parts.append("no_freq")
    if vocab_file.exists():
        try:
            st = vocab_file.stat()
            parts.append(f"vocab:{st.st_mtime_ns}:{st.st_size}")
        except OSError:
            parts.append("vocab:missing")
    else:
        parts.append("no_vocab")
    return "|".join(parts)


def _get_preloaded_bundle(
    filters_dir: Path, freq_path: Path, vocab_file: Path
) -> Tuple[Set[str], Set[str], Set[str], Dict[str, int], Dict[str, str], bool]:
    """Load filters, freqs, vocab; use process cache when inputs unchanged. Returns (..., cache_hit)."""
    key = _fingerprint_preload_sources(filters_dir, freq_path, vocab_file)
    with _preload_lock:
        cached = _preload_cache.get(key)
    if cached is not None:
        ex, ox, ez, ef, vl = cached
        return ex, ox, ez, ef, vl, True
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {
            "filters": pool.submit(load_all_filters, filters_dir, True),
            "freqs": pool.submit(load_english_frequencies, freq_path),
            "vocab": pool.submit(load_vocabulary_levels, vocab_file),
        }
        excluded_words, oxford_filter, easy_words_filter = futures["filters"].result()
        english_freqs = futures["freqs"].result()
        vocabulary_levels = futures["vocab"].result()
    bundle = (excluded_words, oxford_filter, easy_words_filter, english_freqs, vocabulary_levels)
    with _preload_lock:
        _preload_cache[key] = bundle
    return excluded_words, oxford_filter, easy_words_filter, english_freqs, vocabulary_levels, False


def _subtitle_source_fingerprint(subtitle_path: Path) -> Dict[str, Any]:
    st = subtitle_path.stat()
    return {
        "version": PIPELINE_FINGERPRINT_VERSION,
        "mtime_ns": st.st_mtime_ns,
        "size": st.st_size,
        "path_suffix": subtitle_path.suffix.lower(),
    }


def _try_skip_fresh_pipeline(
    subtitle_path: Path,
    tierlist_base_dir: Path,
    is_movie: bool,
    series_name: Optional[str],
    season_number: Optional[int],
    episode_number: Optional[int],
    year: Optional[int],
) -> Optional[Path]:
    """If tier outputs exist and fingerprint matches subtitle file stat, return episode dir."""
    from download_subtitles import get_tierlist_episode_dir, get_tierlist_movie_dir

    sn = series_name
    sea_n = season_number
    ep_n = episode_number
    yr = year
    if is_movie:
        if sn is None or yr is None:
            info = extract_movie_info(subtitle_path)
            if sn is None:
                sn = info["series"]
            if yr is None and info.get("year"):
                yr = int(info["year"])
        if not sn:
            return None
        output_episode_dir = get_tierlist_movie_dir(tierlist_base_dir, sn, yr or 0)
    else:
        if sn is None or sea_n is None or ep_n is None:
            info = extract_series_info(subtitle_path)
            if sn is None:
                sn = info["series"]
            if sea_n is None or ep_n is None:
                if info["season"] and info["episode"]:
                    sea_n = int(re.search(r"\d+", info["season"]).group())
                    ep_n = int(re.search(r"\d+", info["episode"]).group())
                else:
                    if sea_n is None:
                        sea_n = 1
                    if ep_n is None:
                        ep_n = 1
        output_episode_dir = get_tierlist_episode_dir(
            tierlist_base_dir, sn, sea_n, ep_n
        )
    tier1 = output_episode_dir / "tier_1_hard_usable_words.csv"
    fp_path = output_episode_dir / FINGERPRINT_FILENAME
    if not tier1.is_file() or not fp_path.is_file():
        return None
    try:
        stored = json.loads(fp_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    current = _subtitle_source_fingerprint(subtitle_path)
    if (
        stored.get("version") != PIPELINE_FINGERPRINT_VERSION
        or stored.get("mtime_ns") != current["mtime_ns"]
        or stored.get("size") != current["size"]
        or stored.get("path_suffix") != current["path_suffix"]
    ):
        return None
    if not _rare_tier_outputs_complete(output_episode_dir):
        return None
    return output_episode_dir


def run_pipeline(
    subtitle_path: Path,
    base_dir: Path,
    tierlist_base_dir: Optional[Path] = None,
    series_name: Optional[str] = None,
    season_number: Optional[int] = None,
    episode_number: Optional[int] = None,
    is_movie: bool = False,
    year: Optional[int] = None,
    freq_path: Optional[Path] = None,
    filters_dir: Optional[Path] = None,
    max_english_freq: int = 20_000_000,
    min_episode_count: int = DEFAULT_MIN_EPISODE_COUNT,
    min_length: int = 3,
    save_debug_csv: bool = False,
    debug_output_dir: Optional[Path] = None,
    openai_api_key: Optional[str] = None,
    metrics_out: Optional[Dict[str, int]] = None,
    handoff_out: Optional[Dict[str, Any]] = None,
    skip_if_outputs_fresh: bool = False,
) -> Optional[Path]:
    """
    Run full pipeline: load resources, parse subtitle, categorize, optionally filter
    names/fantasy with ChatGPT, save to Tier_lists.
    Returns the episode dir path where tier lists were written, or None.
    If openai_api_key is set, character names and fantasy entities are excluded from tier CSVs.

    handoff_out: if provided, sets key "subtitle_raw" (decoded SRT text) for reuse in translate.
    skip_if_outputs_fresh: when True, skip work if tier_1 exists, rare B/C CSVs exist, and
    .pipeline_fingerprint.json matches subtitle file mtime/size/suffix (PIPELINE_FINGERPRINT_VERSION).
    """
    import time
    t0 = time.perf_counter()
    phase_started = t0
    timings_ms: Dict[str, int] = {
        "preload_ms": 0,
        "parse_subtitle_ms": 0,
        "gpt_cefr_ms": 0,
        "tier_build_ms": 0,
        "gpt_filter_ms": 0,
        "save_outputs_ms": 0,
        "total_ms": 0,
        "preload_cache_hit": 0,
        "pipeline_skipped": 0,
    }

    def _set_metrics() -> None:
        timings_ms["total_ms"] = int((time.perf_counter() - t0) * 1000)
        if metrics_out is None:
            return
        metrics_out.clear()
        metrics_out.update(timings_ms)

    base_dir = base_dir.resolve()
    subtitle_path = subtitle_path.resolve()
    if not subtitle_path.exists():
        print(f"Subtitle not found: {subtitle_path}")
        _set_metrics()
        return None
    filters_dir = filters_dir or base_dir / "filters"
    freq_path = freq_path or base_dir / "Frequency list" / "English" / "unigram_freq.csv"
    if not freq_path.exists():
        print(f"Frequency list not found: {freq_path}")
        _set_metrics()
        return None
    vocab_file = base_dir / "Frequency list" / "English" / "complete english vocabulary.xlsx"

    tierlist_base_resolved = tierlist_base_dir.resolve() if tierlist_base_dir else None
    if skip_if_outputs_fresh and tierlist_base_resolved:
        skipped_dir = _try_skip_fresh_pipeline(
            subtitle_path,
            tierlist_base_resolved,
            is_movie,
            series_name,
            season_number,
            episode_number,
            year,
        )
        if skipped_dir is not None:
            timings_ms["pipeline_skipped"] = 1
            _set_metrics()
            return skipped_dir
    timings_ms["pipeline_skipped"] = 0

    (
        excluded_words,
        oxford_filter,
        easy_words_filter,
        english_freqs,
        vocabulary_levels,
        preload_hit,
    ) = _get_preloaded_bundle(filters_dir, freq_path, vocab_file)
    timings_ms["preload_cache_hit"] = 1 if preload_hit else 0
    timings_ms["preload_ms"] = int((time.perf_counter() - phase_started) * 1000)

    phase_started = time.perf_counter()
    if subtitle_path.suffix.lower() == ".zip":
        series_freqs, subtitle_raw = extract_words_from_zip_with_content(
            subtitle_path, excluded_words
        )
    else:
        word_list, subtitle_raw = parse_srt_file_with_content(subtitle_path, excluded_words)
        series_freqs = Counter(word_list)
    if handoff_out is not None:
        handoff_out["subtitle_raw"] = subtitle_raw
    series_freqs = Counter({w: c for w, c in series_freqs.items() if len(w) >= min_length})
    timings_ms["parse_subtitle_ms"] = int((time.perf_counter() - phase_started) * 1000)

    # Resolve series/episode for GPT prompts (same logic as output paths)
    if is_movie:
        if series_name is None or year is None:
            info = extract_movie_info(subtitle_path)
            if series_name is None:
                series_name = info["series"]
            if year is None and info.get("year"):
                year = int(info["year"])
        season_number = 0
        episode_number = 0
    elif series_name is None or season_number is None or episode_number is None:
        info = extract_series_info(subtitle_path)
        if series_name is None:
            series_name = info["series"]
        if info["season"] and info["episode"]:
            season_number = int(re.search(r"\d+", info["season"]).group())
            episode_number = int(re.search(r"\d+", info["episode"]).group())
        else:
            if season_number is None:
                season_number = 1
            if episode_number is None:
                episode_number = 1

    phase_started = time.perf_counter()
    series_threshold, english_threshold, _, _ = calculate_thresholds(series_freqs, english_freqs)
    gpt_coarse_cefr: Dict[str, str] = {}
    effective_vocab = vocabulary_levels
    if openai_api_key and min_episode_count > 0:
        try:
            from subtitle_text_utils import get_subtitle_text_from_content
            from filter_tier_names import assign_coarse_cefr_for_unlabeled
            from openai import OpenAI

            need_cefr = collect_words_needing_gpt_cefr(
                series_freqs,
                english_freqs,
                vocabulary_levels,
                series_threshold,
                english_threshold,
                min_episode_count,
                oxford_filter,
                easy_words_filter,
            )
            if need_cefr:
                subtitle_text_cefr = get_subtitle_text_from_content(subtitle_raw)
                print(
                    f"CEFR triage (GPT) for {len(need_cefr)} unlabeled frequent learner lemmas..."
                )
                client_cefr = OpenAI(api_key=openai_api_key)
                gpt_coarse_cefr = assign_coarse_cefr_for_unlabeled(
                    need_cefr,
                    subtitle_text_cefr,
                    series_name or "Unknown",
                    client_cefr,
                )
                print(f"  Received coarse labels for {len(gpt_coarse_cefr)} words")
            if gpt_coarse_cefr:
                effective_vocab = build_effective_vocabulary_levels(
                    vocabulary_levels, gpt_coarse_cefr
                )
        except Exception as e:
            print(f"Warning: CEFR GPT triage failed ({e}), using xlsx levels only")
            gpt_coarse_cefr = {}
            effective_vocab = vocabulary_levels
    timings_ms["gpt_cefr_ms"] = int((time.perf_counter() - phase_started) * 1000)

    phase_started = time.perf_counter()
    tiers = categorize_words(
        series_freqs,
        english_freqs,
        max_english_freq=max_english_freq,
        oxford_filter=oxford_filter,
        easy_words_filter=easy_words_filter,
        vocabulary_levels=effective_vocab,
        series_threshold=series_threshold,
        english_threshold=english_threshold,
        min_episode_count=min_episode_count if min_episode_count > 0 else None,
    )
    timings_ms["tier_build_ms"] = int((time.perf_counter() - phase_started) * 1000)
    if save_debug_csv and debug_output_dir:
        debug_output_dir.mkdir(parents=True, exist_ok=True)
        for tier_key, fname in [
            ("tier_1_hard_usable", "tier_1_hard_usable_words.csv"),
            ("tier_2_random", "tier_2_random_words.csv"),
            ("tier_3_common", "tier_3_common_words.csv"),
            ("tier_4_rare_in_series", "tier_4_rare_in_series.csv"),
            ("tier_5_filtered", "tier_5_filtered_words.csv"),
            ("tier_b1_words", "tier_b1_words.csv"),
            ("tier_b2_words", "tier_b2_words.csv"),
        ]:
            path = debug_output_dir / fname
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                items = tiers.get(tier_key, [])
                if tier_key == "tier_5_filtered":
                    w.writerow(["word", "series_frequency", "english_frequency", "filter_reason", "vocabulary_level"])
                    for it in items:
                        w.writerow(it[:5] if len(it) >= 5 else [*it[:3], "Unknown", "N/A"])
                else:
                    w.writerow(["word", "series_frequency", "english_frequency", "vocabulary_level"])
                    for it in items:
                        w.writerow(it[:4] if len(it) >= 4 else [*it[:3], "N/A"])
    if not tierlist_base_dir:
        _set_metrics()
        return None
    tierlist_base_dir = tierlist_base_dir.resolve()

    excluded_words: Optional[Set[str]] = None
    c1_assessment: Optional[Dict[str, str]] = None
    phase_started = time.perf_counter()
    if openai_api_key:
        try:
            from subtitle_text_utils import get_subtitle_text_from_content
            from filter_tier_names import filter_names_and_fantasy_entities
            from openai import OpenAI
            seen_lower = set()
            words_to_check = []
            for tier_key in (
                "tier_1_hard_usable",
                "tier_2_random",
                "tier_3_common",
                "tier_4_rare_in_series",
                "tier_5_filtered",
                "tier_b1_words",
                "tier_b2_words",
            ):
                for item in tiers.get(tier_key, []):
                    w = (item[0] or "").strip().lower()
                    if w and w not in seen_lower:
                        seen_lower.add(w)
                        words_to_check.append((item[0] or "").strip())
            if words_to_check:
                subtitle_text = get_subtitle_text_from_content(subtitle_raw)
                client = OpenAI(api_key=openai_api_key)
                print("Filtering names and fantasy entities with ChatGPT...")
                excluded_words, c1_assessment = filter_names_and_fantasy_entities(
                    words_to_check, subtitle_text, series_name, client
                )
                print(f"  Excluding {len(excluded_words)} words from tier lists")
        except Exception as e:
            print(f"Warning: Name/fantasy filter failed ({e}), saving tier lists without filtering")
    timings_ms["gpt_filter_ms"] = int((time.perf_counter() - phase_started) * 1000)

    from download_subtitles import get_tierlist_episode_dir, get_tierlist_movie_dir
    if is_movie:
        output_episode_dir = get_tierlist_movie_dir(
            tierlist_base_dir, series_name, year or 0
        )
    else:
        output_episode_dir = get_tierlist_episode_dir(
            tierlist_base_dir, series_name, season_number, episode_number
        )
    phase_started = time.perf_counter()
    save_tierlist_results_to_dir(
        tiers,
        output_episode_dir,
        subtitle_path,
        series_threshold,
        english_threshold,
        max_english_freq,
        series_name,
        season_number,
        episode_number,
        excluded_words=excluded_words,
        c1_assessment=c1_assessment,
        is_movie=is_movie,
        movie_year=year if is_movie else None,
        min_episode_count=min_episode_count if min_episode_count > 0 else None,
        gpt_coarse_cefr=gpt_coarse_cefr if gpt_coarse_cefr else None,
    )
    timings_ms["save_outputs_ms"] = int((time.perf_counter() - phase_started) * 1000)
    try:
        fp_payload = json.dumps(
            _subtitle_source_fingerprint(subtitle_path), indent=2, ensure_ascii=False
        )
        (output_episode_dir / FINGERPRINT_FILENAME).write_text(fp_payload, encoding="utf-8")
    except OSError:
        pass
    if debug_output_dir and HAS_MATPLOTLIB:
        create_frequency_plot(tiers, series_threshold, english_threshold, debug_output_dir)
    _set_metrics()
    return output_episode_dir


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze subtitles and create tier lists")
    parser.add_argument("--subtitle", "-s", required=True, help="Path to SRT or ZIP subtitle")
    parser.add_argument("--tierlist-base-dir", type=Path, default=Path("Tier_lists"), help="Base dir for tier lists")
    parser.add_argument("--series", type=str, help="Series name (default: from filename)")
    parser.add_argument("--season", type=int, help="Season number (default: from filename)")
    parser.add_argument("--episode", type=int, help="Episode number (default: from filename)")
    parser.add_argument("--movie", action="store_true", help="Treat as movie (use Tier_lists/Movies/... path)")
    parser.add_argument("--year", type=int, default=None, help="Movie release year (for movies)")
    parser.add_argument("--freq-list", type=Path, help="English frequency CSV")
    parser.add_argument("--max-english-freq", type=int, default=20_000_000, help="Max English freq for Tier 1")
    parser.add_argument(
        "--min-episode-count",
        type=int,
        default=DEFAULT_MIN_EPISODE_COUNT,
        help="Min mentions in this episode for learner-tier paths (B/C/A); 0 disables",
    )
    parser.add_argument("--min-length", type=int, default=3, help="Min word length")
    parser.add_argument("--output", "-o", type=Path, help="Debug output dir (optional)")
    parser.add_argument("--openai-api-key", type=str, default=None, help="OpenAI API key for name/fantasy filter (or set OPENAI_API_KEY)")
    args = parser.parse_args()
    from env_config import resolve_openai_api_key

    openai_key = resolve_openai_api_key(args.openai_api_key)
    base_dir = Path(__file__).resolve().parent
    subtitle_path = (base_dir / args.subtitle) if not Path(args.subtitle).is_absolute() else Path(args.subtitle)
    tierlist_base = (base_dir / args.tierlist_base_dir) if not args.tierlist_base_dir.is_absolute() else args.tierlist_base_dir
    out = run_pipeline(
        subtitle_path=subtitle_path,
        base_dir=base_dir,
        tierlist_base_dir=tierlist_base,
        series_name=args.series,
        season_number=args.season,
        episode_number=args.episode,
        is_movie=args.movie,
        year=args.year,
        freq_path=args.freq_list or base_dir / "Frequency list" / "English" / "unigram_freq.csv",
        max_english_freq=args.max_english_freq,
        min_episode_count=args.min_episode_count,
        min_length=args.min_length,
        save_debug_csv=bool(args.output),
        debug_output_dir=args.output and (base_dir / args.output),
        openai_api_key=openai_key,
    )
    if out:
        print(f"Done. Tier lists in {out}")
    else:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
