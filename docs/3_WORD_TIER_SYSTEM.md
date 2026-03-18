# 3. Word-Tier System: Description and Inputs

This document describes the word-tier system: its role, how it works, and the inputs it needs from the rest of the system and from data sources (including APIs and local datasets).

---

## 3.1 Role of the Word-Tier System

The **word-tier system** (`subtitle_analyzer.py`, run as a subprocess by the bot) is responsible for:

1. **Extracting words** from a subtitle file (SRT or ZIP containing SRT).
2. **Counting word frequencies** in that episode (series frequency).
3. **Comparing** those counts to **general English frequencies** (from a reference list).
4. **Categorizing words into five tiers** based on “high/low” series frequency and “high/low” English frequency, and applying filters (Oxford 3000, easy words, max English frequency).
5. **Writing** tier CSVs and metadata under `tierlist/SeriesName/S02E03/`.

It does **not** translate words or call the translation system; it only produces the tier lists that the translation system (and the bot) later use.

---

## 3.2 Pipeline Overview

```
Inputs: subtitle_path, output_dir, max_english_freq, filters_dir, freq_list, vocabulary file
    │
    ▼
Load resources (filters, English frequencies, vocabulary levels)
    │
    ▼
Parse subtitle (SRT/ZIP) → series_freqs (Counter: word → count in episode)
    │
    ▼
Calculate thresholds (percentiles on series and English frequencies)
    │
    ▼
Categorize words → 5 tiers (tier_1 … tier_5)
    │
    ▼
Save: episode_info.json, tier_1 … tier_5 CSVs, README.md (and optional debug output)
```

---

## 3.3 Tier Logic (short)

- **Tier 1 – Hard Usable:** Low English freq, high series freq; filtered by max_english_freq, Oxford 3000, easy_words. “Best to learn” for this show.
- **Tier 2 – Random:** Low English freq, low series freq.
- **Tier 3 – Common:** High English freq, high series freq.
- **Tier 4 – Rare in Series:** High English freq, low series freq.
- **Tier 5 – Filtered:** Words that would be Tier 1/2 but excluded (Oxford, easy, or high English freq); stored with `filter_reason`.

Thresholds are percentile-based (e.g. 33rd percentile) on both series and English frequencies.

---

## 3.4 Inputs the Word-Tier System Needs

The word-tier system is **invoked by the bot** with a subtitle path and parameters. It **does not call** OpenSubtitles or the bot; it reads from the **filesystem** and from **local data files**. So “inputs from API” below means: inputs that ultimately come from **external or upstream sources** (APIs or local datasets the system depends on).

### 3.4.1 Inputs from the bot / orchestrator

| Input | Passed how | Used for |
|-------|------------|----------|
| **Subtitle file path** | `--subtitle <path>` (from bot: result of download or existing file) | Parse SRT (or ZIP) to extract text and compute word counts (series_freqs). |
| **Output directory** | `--output output` | Debug CSVs and frequency plot (e.g. `output/`). |
| **max_english_freq** | `--max-english-freq 10000000` (bot uses fixed value for level C) | Exclude from Tier 1 words with English frequency above this (easy-words filter). |

So from the “orchestrator” (bot), the word-tier system needs: **subtitle path**, **output dir**, **max_english_freq**.

### 3.4.2 Inputs from local data (no HTTP API)

These are **not** HTTP APIs; they are files the word-tier system reads from disk. They are the “API” in the sense of “data interface” the tier system depends on.

| Input | Location | Format | Used for |
|-------|----------|--------|----------|
| **English frequency list** | `Frequency list/English/unigram_freq.csv` | CSV: `word`, `count` | English frequency per word; compare with series frequency to assign tiers. |
| **Filters (basic)** | `filters/*.csv` (e.g. contractions, exclamations, names, swear_words, custom, subtitle_metadata) | CSV (e.g. first column = word) | Words to exclude from extraction (not counted in series_freqs). |
| **Oxford 3000** | `filters/oxford_3000.csv` | CSV | Exclude these from Tier 1 (categorization only, not extraction). |
| **Easy words** | `filters/easy_words.csv` | CSV | Exclude these from Tier 1 (categorization only). |
| **Vocabulary levels** | `Frequency list/English/complete english vocabulary.xlsx` | Excel: `word`, `level` (A1–C2) | Add `vocabulary_level` column to tier CSVs. |
| **Lemmatizer (optional)** | `lemmatizer.py` | Python module | Normalize word forms before filtering and before grouping with frequency list. |

### 3.4.3 Inputs from “API” (external services)

The word-tier system **itself does not call any HTTP API**. It:

- Does **not** call OpenSubtitles (the bot does that before passing a subtitle path).
- Does **not** call OpenAI (the bot uses OpenAI for name normalization; the translation system uses it for translation and name tagging).

So **from the point of view of the word-tier system**, there are **no inputs from external APIs**. All inputs are:

- From the **bot**: subtitle path, output dir, max_english_freq.
- From **local data**: frequency list, filters (basic + Oxford + easy_words), vocabulary levels file, optional lemmatizer.

If the **subtitle content** is considered as “from the download API” (OpenSubtitles), then indirectly the word-tier system depends on that API’s **output** (the file the bot saved), but the tier system only sees a **local file path**, not the API.

---

## 3.5 Summary: List of Inputs the Word-Tier System Needs

**From the bot / orchestrator:**

1. **Subtitle path** – path to the episode’s SRT (or ZIP containing SRT).
2. **Output directory** – for debug CSVs and plots.
3. **max_english_freq** – threshold for excluding high-frequency English words from Tier 1.

**From local data / “data APIs”:**

4. **English frequency list** – `unigram_freq.csv` (word → count).
5. **Basic filters** – CSVs in `filters/` (contractions, exclamations, names, etc.) for word extraction.
6. **Oxford 3000 filter** – for Tier 1 categorization.
7. **Easy words filter** – for Tier 1 categorization.
8. **Vocabulary levels** – `complete english vocabulary.xlsx` (word → A1–C2).
9. **Optional:** Lemmatizer module for word normalization.

**From external APIs:**

- **None** – the word-tier system does not call OpenSubtitles or OpenAI. It only reads the subtitle file that the bot has already obtained (e.g. via OpenSubtitles) and the local datasets above.

---

See **SYSTEM_AND_PIPELINE.md** for the full pipeline and **4_APIS.md** for which components use which external APIs.
