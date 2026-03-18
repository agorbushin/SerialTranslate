# SerialTranslate: System and Analysis Pipeline

This document describes the overall system architecture and the end-to-end pipeline for subtitle analysis, word tiering, and translation in the Telegram bot.

---

## 1. System Overview

**SerialTranslate** is a Telegram bot that:

1. Accepts a TV series name (and optional season/episode) from the user.
2. Standardizes the series name (e.g. "got s2 e3" → "Game of Thrones") and downloads English subtitles from OpenSubtitles.
3. Analyzes the subtitle text to extract words and assigns them to **five tiers** based on frequency in the series vs. frequency in general English.
4. Translates selected tiers (e.g. hard usable words, rare-in-series words) into a target language (e.g. Russian) using OpenAI, with context from the subtitle.
5. Presents the user with **Hard Words Frequent in Series** (Tier 1), **Rare in Series Hard Words** (Tier 2), **Full List**, and **Phrasal Verbs**, with optional translation.

### 1.1 Main Components

| Component | Role |
|-----------|------|
| **telegram_bot.py** | Entry point: handles messages, commands, callbacks; orchestrates standardization, download, analysis, translation, and UI. |
| **download_subtitles.py** | OpenSubtitles API client: search by query + season/episode, score results, download best match. |
| **subtitle_analyzer.py** | Word extraction from SRT/ZIP, frequency counting, tier categorization, writing CSVs and metadata. |
| **translate_words.py** | Translates words in tier CSVs using OpenAI with subtitle context; name/fantasy tagging; writes translation columns. |
| **phrasal_verbs.py** | Extracts phrasal verbs from subtitle text; optional ChatGPT verification; translation. |
| **api_health_check.py** | Lightweight checks for OpenAI and OpenSubtitles (quota, rate limit, auth) before heavy API use. |
| **lemmatizer.py** | Optional lemmatization for word normalization (used by analyzer and filters). |

### 1.2 Directory Layout

```
SerialTranslate/
├── telegram_bot.py          # Bot entry point
├── download_subtitles.py     # OpenSubtitles download
├── subtitle_analyzer.py      # Word extraction & tiering
├── translate_words.py       # Word translation (OpenAI)
├── phrasal_verbs.py         # Phrasal verb extraction & translation
├── api_health_check.py      # API health checks
├── lemmatizer.py            # Lemmatization (optional)
├── Subtitles/               # Downloaded/uploaded subtitles
│   ├── SeriesName/
│   │   └── Season N/
│   │       └── Episode NN/
│   │           └── *.srt
│   └── uploads/             # User-uploaded files
├── tierlist/                # Analysis output per series/episode
│   └── SeriesName/
│       └── S01E02/
│           ├── episode_info.json
│           ├── tier_1_hard_usable_words.csv
│           ├── tier_2_random_words.csv
│           ├── tier_3_common_words.csv
│           ├── tier_4_rare_in_series.csv
│           ├── tier_5_filtered_words.csv
│           ├── phrasal_verbs.csv
│           └── README.md
├── output/                  # Debug output from subtitle_analyzer (e.g. frequency plot)
├── Frequency list/English/   # unigram_freq.csv, oxford list, vocabulary levels
├── filters/                 # CSV word lists (names, contractions, Oxford, etc.)
└── docs/
```

---

## 2. End-to-End Pipeline

### 2.1 User Message Flow (High Level)

```
User: "game of thrones series 2 episode 3"
  │
  ├─► Extract season/episode (2, 3)
  ├─► Standardize series name (ChatGPT) → "Game of Thrones"
  ├─► Check existing tier lists for that series + S02E03
  │     ├─ If found and translations exist → show Hard Words (Tier 1)
  │     └─ If found but no translations → run translation then show
  │
  ├─► If no tier list: check/download subtitle (OpenSubtitles)
  ├─► Run subtitle_analyzer → create tierlist/Game of Thrones/S02E03/
  ├─► Run translate_words (tier_1 + tier_2)
  └─► Send Hard Words (Tier 1) + inline buttons (Full List, Phrasal Verbs, Rare in Series Hard Words, New Series)
```

### 2.2 Step-by-Step Pipeline

#### Step 1: Parse user input

- **Handler:** `handle_message()` in `telegram_bot.py`.
- **Season/episode extraction:** `extract_season_episode(user_message)`.
  - Supports: `S02E03`, `s2 e3`, `season 2 episode 3`, `series 2 episode 3`, `episode 3 series 2`, `Ep 3`, etc.
  - Returns `(season, episode)` or `(None, None)`; missing season defaults to 1 when an episode is given.
- **User level:** Fixed to `'C'` (Advanced) for analysis (e.g. `max_english_freq`).

#### Step 2: Standardize series name and download subtitle

- **Function:** `standardize_and_download_series(user_input, openai_client, season, episode, ...)`.
- **Name normalization:**
  - Input is cleaned of season/episode tokens, then sent to **ChatGPT** (`normalize_series_name`) to get an official series name (e.g. for IMDb/OpenSubtitles).
  - On failure or weak result, a **manual fallback** map is used for common variants (e.g. "Marvelous Mrs. Maisel", "Game of Thrones").
- **Download:**
  - `download_subtitle(series_name, season, episode)`:
    - Optional **OpenSubtitles health check** (`api_health_check`).
    - Look for **existing subtitle** under `Subtitles/SeriesName/Season N/Episode NN/` (and optionally `uploads/`).
    - If not found: **OpenSubtitlesDownloader.search_subtitles** with query + season/episode, then **download_best_match** (scoring by name match + popularity), save to the same folder.
  - If download fails, **alternative name** is requested from ChatGPT and download is retried.
- **Output:** `(series_name, subtitle_path)` or `(series_name, None)`.

#### Step 3: Find or create tier lists

- **Existing tier lists:** `find_existing_tier_lists(series_name)` returns episode dirs under `tierlist/SeriesName/` that contain `tier_1_hard_usable_words.csv`.
- If user specified season/episode, results are **filtered** to the folder matching `S{season:02d}E{episode:02d}` (e.g. `S02E03`). If none match, existing list is ignored and the pipeline continues to download/analyze.
- If a matching **existing episode dir** is found:
  - Check if Tier 1 has a `translation` column with at least one non-empty value.
  - If **translations missing**: resolve subtitle path (from `episode_info.json` or `find_existing_subtitle`), optionally run **OpenAI health check**, then call `translate_tier_list(episode_dir, subtitle_path)` (which runs `translate_words.py --episode-dir` for tier_1 and tier_2).
  - Then **send_tier_list_results(update, episode_dir, context)** to show Tier 1 and buttons.
- If **no existing tier list** (or we deliberately cleared it to force re-download):
  - Ensure we have a **subtitle path** (from standardization step or `find_existing_subtitle`). If still missing, try `download_subtitle` again.
  - Call **analyze_subtitle(subtitle_path, user_level)**.

#### Step 4: Subtitle analysis (when no tier list exists)

- **Function:** `analyze_subtitle(subtitle_path, user_level)` in `telegram_bot.py`.
- **Implementation:** Runs the **subtitle_analyzer** as a subprocess:
  ```bash
  python3 subtitle_analyzer.py --subtitle <path> --output output --max-english-freq 10000000
  ```
- **Inside subtitle_analyzer.py:**
  1. **Load resources:**
     - **Filters:** `load_all_filters(filters_dir, exclude_oxford=True)` → basic (contractions, exclamations, names, swear words, etc.), Oxford 3000, easy_words.
     - **English frequencies:** `load_english_frequencies(unigram_freq.csv)` (per-word counts, combined by lemma when lemmatization is used).
     - **Vocabulary levels:** `load_vocabulary_levels(complete english vocabulary.xlsx)` (A1–C2) for tier metadata.
  2. **Extract words from subtitle:**
     - **ZIP:** `extract_words_from_zip` (find .srt in archive, parse); **SRT:** `parse_srt_file`.
     - Strip timestamps, numbers, HTML, `[brackets]`, metadata/URLs; tokenize; optional **lemmatization**; remove filtered words and words shorter than `--min-length`.
     - Result: **Counter** of (word → count) in this episode = **series_freqs**.
  3. **Categorize into tiers:** `categorize_words(series_freqs, english_freqs, max_english_freq, oxford_filter, easy_words_filter, vocabulary_levels)`.
     - **Thresholds:** Percentiles on series and English frequencies (e.g. 33rd percentile) to define “high” vs “low” in series and in English.
     - **Tier logic:**
       - **Tier 1 (Hard Usable):** Low English freq, High series freq. Best to learn for this show. Filtered by max_english_freq, Oxford, easy_words.
       - **Tier 2 (Random):** Low English freq, Low series freq.
       - **Tier 3 (Common):** High English freq, High series freq.
       - **Tier 4 (Rare in Series):** High English freq, Low series freq.
       - **Tier 5 (Filtered):** Words that would have been Tier 1/2 but were excluded (Oxford, easy, high English freq); stored with filter_reason.
  4. **Save results:** `save_tierlist_results(...)` writes:
     - `tierlist/SeriesName/S02E03/episode_info.json` (series, season, episode, subtitle_file, thresholds, word_counts),
     - `tier_1_hard_usable_words.csv` … `tier_5_filtered_words.csv` (columns: word, series_frequency, english_frequency, vocabulary_level [and filter_reason for tier_5]),
     - `README.md` summary.
  5. **Optional:** `save_results_to_csv` to `output/` and `create_frequency_plot` (PNG/PDF) for debugging.
- **Back in telegram_bot:** `extract_series_info(subtitle_path)` gives series name and SxxExx; the episode dir is `tierlist/SeriesName/S02E03/`. User level and max_english_freq are written into `episode_info.json`. Returns this **episode_dir**.

#### Step 5: Translation of tier lists

- **Function:** `translate_tier_list(episode_dir, subtitle_path)` in `telegram_bot.py`.
- **Implementation:** Subprocess:
  ```bash
  python3 translate_words.py --episode-dir <episode_dir> --subtitle <subtitle_path> --api-key <key>
  ```
- **Inside translate_words.py (`translate_episode`):**
  - Translates **tier_1_hard_usable_words.csv** and **tier_2_random_words.csv** (and tier_4 on-demand when user opens “Rare in Series” and translation is triggered).
  - For each tier file:
    1. **Read CSV** (word, series_frequency, english_frequency, vocabulary_level [and translation if present]).
    2. **Determine which rows need translation:** no translation, or value is `N/A` or `[Translation failed]`. In non-interactive (bot) mode, always retry those; no overwrite prompt.
    3. **STAGE 1 – Name/fantasy tagging:** Send word list to **ChatGPT** to mark names and series-specific/fantasy entities. Results stored in column **is_name_or_fantasy** (not used to remove rows, but used later when displaying in the bot to filter or label).
    4. **STAGE 2 – Translation:**  
       - **Subtitle context:** `get_subtitle_text(subtitle_path)` for full text; **examples:** `extract_examples_from_subtitle(subtitle_path, words)` (up to N example sentences per word).  
       - Words are batched; for each batch, **translate_words_with_context_async** (or sync) calls OpenAI with word list + short context/examples and asks for JSON: `word → { translation, example_en, example_translated }`.  
       - Writes **translation** (and optionally example columns) back into the CSV.
  - **Phrasal verbs** are not translated inside `translate_words.py`; they are handled by **phrasal_verbs.py** when the user taps “Phrasal Verbs”.

#### Step 6: Sending results and menus

- **Hard Words (Tier 1):** `send_tier_list_results(update, episode_dir, context)`.
  - Reads `tier_1_hard_usable_words.csv`.
  - If **translation** column missing or empty for key rows, can trigger **translate_tier_list** (and optionally health check) then re-read.
  - **Filtering for display:** Drops or labels rows with `is_name_or_fantasy` (and optionally vocabulary_level below Advanced), then takes top 10 (or full list when “Full List” is pressed).
  - Builds message: series name, season/episode from `episode_info.json`, word count, top 10 “word → translation”, “... and N more”.
  - **Inline keyboard:** Full List, Phrasal Verbs, Rare in Series Hard Words, New Series.
  - Saves `context.user_data['last_episode_dir']`, `last_series_name`, `last_tier_type='tier_1'`.

- **Rare in Series Hard Words (Tier 2):** `send_rare_hard_words(update, context)`.
  - Uses `last_episode_dir`; reads `tier_2_random_words.csv`.
  - If translations missing, may run **translate_specific_tier_file(tier_2_random_words.csv, subtitle_path)** (same translation pipeline as tier_1).
  - Same style of message and filtering; sets `last_tier_type='tier_2'`.
  - **Inline keyboard:** Full List, Phrasal Verbs, **Hard Words Frequent in Series**, New Series.

- **Full List:** `send_full_list(update, context)`.
  - Uses `last_episode_dir` and **last_tier_type** to choose file:
    - `tier_1` → `tier_1_hard_usable_words.csv`
    - `tier_2` → `tier_2_random_words.csv`
    - `tier_4` → `tier_4_rare_in_series.csv`
  - Sends full list (with same filtering logic) in one or more messages; keyboard again offers Full List, Phrasal Verbs, Rare in Series Hard Words, New Series.

- **Phrasal Verbs:**
  - Load or generate `phrasal_verbs.csv` in the same episode dir (extract from subtitle with **phrasal_verbs.py**; optionally verify with ChatGPT).
  - Translate and show list; keyboard: Full List, Phrasal Verbs, Rare in Series Hard Words, New Series.

- **Callbacks:** `button_callback` dispatches:
  - `full_list` → `send_full_list`
  - `rare_hard_words` → `send_rare_hard_words`
  - `hard_words_frequent` → `send_tier_list_results(..., episode_dir, ...)`
  - `phrasal_verbs` → phrasal verbs flow
  - `next_series` → prompt for new series name

---

## 3. Data and File Formats

### 3.1 Tier CSVs (after analysis)

- **Columns (Tiers 1–4):** `word`, `series_frequency`, `english_frequency`, `vocabulary_level`.
- **Tier 5:** `word`, `series_frequency`, `english_frequency`, `filter_reason`, `vocabulary_level`.
- **After translation:** Added columns such as `translation`, `is_name_or_fantasy`, and optionally example columns.

### 3.2 episode_info.json

- `series`, `season`, `episode`, `subtitle_file`, `analysis_date`, `user_level`, `max_english_freq`, `thresholds`, `word_counts` (per tier).

### 3.3 Subtitles

- Stored under `Subtitles/SeriesName/Season N/Episode NN/`. Filename is preserved from OpenSubtitles (or upload). Used for analysis, translation context, and example extraction.

---

## 4. External APIs and Health Checks

- **OpenAI (ChatGPT):**
  - Used for: series name normalization, alternative name, name/fantasy tagging, word translation, phrasal verb verification.
  - **api_health_check:** `quick_openai_test` / `APIHealthChecker.test_openai_api` before translation; can detect quota, rate_limit, authentication and surface a message to the user (e.g. billing link).
- **OpenSubtitles:**
  - Search (query + language + season/episode) and file download.
  - **api_health_check:** `quick_opensubtitles_test` before download; logs issues; bot may still attempt download.

---

## 5. Summary Diagram (Pipeline)

```
User message
    │
    ▼
extract_season_episode ──► (season, episode)
    │
    ▼
standardize_and_download_series
    │
    ├─ normalize_series_name (OpenAI)
    ├─ download_subtitle (OpenSubtitles or existing file)
    └─► (series_name, subtitle_path)
    │
    ▼
find_existing_tier_lists(series_name) [filter by SxxExx if specified]
    │
    ├─ Found + has translations ──► send_tier_list_results (Tier 1 + buttons)
    ├─ Found + no translations ──► translate_tier_list ──► send_tier_list_results
    │
    └─ Not found
            │
            ▼
    [Ensure subtitle_path]
            │
            ▼
    analyze_subtitle(subtitle_path)
            │
            ├─ subprocess: subtitle_analyzer.py
            │     ├─ Load filters, english_freqs, vocabulary_levels
            │     ├─ Parse SRT → series_freqs (Counter)
            │     ├─ categorize_words → 5 tiers
            │     └─ save_tierlist_results → tierlist/SeriesName/S02E03/
            │
            ▼
    translate_tier_list(episode_dir, subtitle_path)
            │
            ├─ subprocess: translate_words.py --episode-dir
            │     ├─ tier_1: name/fantasy tag + translate
            │     └─ tier_2: name/fantasy tag + translate
            │
            ▼
    send_tier_list_results (Tier 1, inline buttons)
```

---

## 6. Key Conventions

- **Season/episode folder:** `S02E03` (from `extract_series_info` on subtitle filename or from user input).
- **Subtitles folder:** `Subtitles/Series Name/Season N/Episode NN/`.
- **Tier 1** = “Hard Words Frequent in Series” (low English freq, high series freq, filtered).
- **Tier 2** = “Rare in Series Hard Words” (low English freq, low series freq).
- **Tier 4** = “Rare in Series” (high English freq, low series freq); shown in Full List when that view was last used.
- **Translation** is Russian by default; controlled inside `translate_words.py` and phrasal verb code.
- **User level** is fixed to Advanced (C); only one difficulty profile is used for analysis and filtering in the bot.

This document reflects the codebase as of the last update; for implementation details, refer to the source files listed in §1.1.
