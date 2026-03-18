# Subtitle to Tier List to Translation - Complete Flow

This document describes the complete step-by-step process of how a subtitle file is processed into translated tier lists.

## Overview

The system processes subtitles through three main stages:
1. **Subtitle Analysis** - Extract words and categorize into tiers
2. **Name/Fantasy Entity Filtering** - Identify and flag names/fantasy entities
3. **Translation** - Translate words with context

---

## Stage 1: User Request → Subtitle Analysis

### Step 1.1: User Sends Series Name
**Location**: `telegram_bot.py` → `handle_message()`

- User sends a message like "Fallout S02E01" or "Game of Thrones"
- Bot validates input (minimum 3 characters)
- Bot shows processing status message

### Step 1.2: Series Name Normalization
**Location**: `telegram_bot.py` → `normalize_series_name()`

- Extracts season/episode numbers from input (e.g., "S02E01" → season=2, episode=1)
- Uses **GPT-4o-mini** to normalize series name
  - Example: "got" → "Game of Thrones"
  - Example: "fallout" → "Fallout"
- Returns normalized series name

### Step 1.3: Search for Existing Tier Lists
**Location**: `telegram_bot.py` → `find_existing_tier_lists()`

- Searches `tierlist/` directory for existing tier lists
- Looks for: `tierlist/{SeriesName}/{SeasonEpisode}/tier_1_hard_usable_words.csv`
- If found, skips to translation stage
- If not found, proceeds to subtitle analysis

### Step 1.4: Find or Download Subtitle
**Location**: `telegram_bot.py` → `find_existing_subtitle()` or `download_subtitle()`

**Option A: Find Existing Subtitle**
- Searches `Subtitles/` directory structure
- Looks for files matching series name, season, episode
- Supports nested structure: `Subtitles/{Series}/Season {N}/Episode {M}/`

**Option B: Download Subtitle**
- Uses OpenSubtitles API to search and download
- Extracts subtitle from ZIP if needed
- Saves to `Subtitles/` directory

### Step 1.5: Analyze Subtitle
**Location**: `telegram_bot.py` → `analyze_subtitle()`

Calls `subtitle_analyzer.py` as subprocess:

```bash
python3 subtitle_analyzer.py \
  --subtitle {subtitle_path} \
  --output {output_dir} \
  --max-english-freq 5000000
```

---

## Stage 2: Subtitle Analysis → Tier Lists

### Step 2.1: Load Filters
**Location**: `subtitle_analyzer.py` → `load_all_filters()`

Loads filter CSV files from `filters/` directory:
- **Basic filters** (applied during word extraction):
  - `contractions.csv` - "don't", "can't", etc.
  - `exclamations.csv` - "oh", "ah", etc.
  - `swear_words.csv` - Profanity
  - `names_male.csv`, `names_female.csv`, `names_last.csv`, `names_characters.csv` - Name databases
  - `custom.csv` - Custom exclusions
  
- **Categorization filters** (applied during tier assignment):
  - `oxford_3000.csv` - Common words (moved to Tier 5)
  - `easy_words.csv` - Simple words (moved to Tier 5)

### Step 2.2: Parse Subtitle File
**Location**: `subtitle_analyzer.py` → `parse_srt_file()` or `extract_words_from_zip()`

- Reads SRT subtitle file
- Removes timing information (e.g., "00:00:01,000 --> 00:00:03,000")
- Removes subtitle numbers
- Removes HTML tags
- Removes sound effects `[sound]`
- Extracts clean text

### Step 2.3: Extract Words
**Location**: `subtitle_analyzer.py` → Word extraction logic

- Splits text into words
- Converts to lowercase
- Removes punctuation
- Filters out:
  - Words shorter than 3 characters
  - Words in basic filters
  - Numbers
- Counts word frequencies in the series

### Step 2.4: Load Vocabulary Levels
**Location**: `subtitle_analyzer.py` → `load_vocabulary_levels()`

- Reads `Frequency list/English/complete english vocabulary.xlsx`
- Maps words to CEFR levels (A1, A2, B1, B2, C1, C2)
- For duplicate words, keeps the **lowest** (most basic) level
- Example: "just" appears as both A2 and C1 → keeps A2

### Step 2.5: Load English Frequency Data
**Location**: `subtitle_analyzer.py` → `load_english_frequency()`

- Reads `Frequency list/English/unigram_freq.csv`
- Maps words to their frequency in general English
- Used to compare series frequency vs English frequency

### Step 2.6: Categorize Words into Tiers
**Location**: `subtitle_analyzer.py` → `categorize_words()`

Words are categorized into 5 tiers based on:
- **Series frequency** (how often word appears in this episode)
- **English frequency** (how common word is in general English)
- **Vocabulary level** (CEFR level: A1-C2)

**Tier 1: Hard Usable Words** (Best for learning)
- Low English frequency (< 5,000,000)
- High series frequency (≥ threshold, typically 2+)
- **NOT** in Oxford 3000
- **NOT** in easy_words filter
- **NOT** flagged as simple words

**Tier 2: Random Words**
- Low English frequency (< 5,000,000)
- Low series frequency (< threshold)
- Rare words that appear infrequently

**Tier 3: Common Words**
- High English frequency (≥ 5,000,000)
- High series frequency (≥ threshold)
- Common words used frequently

**Tier 4: Rare in Series**
- High English frequency (≥ 5,000,000)
- Low series frequency (< threshold)
- Common words but rare in this series

**Tier 5: Filtered Words**
- Words from Tier 1 that were filtered out:
  - In Oxford 3000
  - In easy_words filter
  - High English frequency (> 5,000,000)
  - Simple words (A1/A2 vocabulary level)

### Step 2.7: Save Tier Lists
**Location**: `subtitle_analyzer.py` → `save_tierlist_results()`

Creates directory structure:
```
tierlist/
  {SeriesName}/
    {SeasonEpisode}/  (e.g., "S02E01")
      tier_1_hard_usable_words.csv
      tier_2_random_words.csv
      tier_3_common_words.csv
      tier_4_rare_in_series.csv
      tier_5_filtered_words.csv
      episode_info.json
      README.md
```

**CSV Format** (Tier 1):
```csv
word,series_frequency,english_frequency,vocabulary_level
example,5,1000000,B1
test,3,2000000,A2
```

**episode_info.json**:
```json
{
  "series": "Fallout",
  "season": "Season 2",
  "episode": "Episode 01",
  "subtitle_file": "Fallout.S02E01.srt",
  "analysis_date": "2025-01-18T23:30:00",
  "thresholds": {
    "series_threshold": 2,
    "english_threshold": 5000000,
    "max_english_freq": 5000000
  }
}
```

---

## Stage 3: Translation Process

### Step 3.1: Check for Existing Translations
**Location**: `telegram_bot.py` → `send_tier_list_results()`

- Reads `tier_1_hard_usable_words.csv`
- Checks if `translation` column exists and has values
- If missing, triggers translation

### Step 3.2: Call Translation Function
**Location**: `telegram_bot.py` → `translate_tier_list()`

Calls `translate_words.py` as subprocess:

```bash
python3 translate_words.py \
  --episode-dir {episode_dir} \
  --subtitle {subtitle_path} \
  --api-key {api_key} \
  --overwrite
```

### Step 3.3: Load Name Filters (Pre-filtering)
**Location**: `translate_words.py` → `translate_tier_file()`

Loads name databases before ChatGPT filtering:
- `names_male.csv`
- `names_female.csv`
- `names_last.csv`
- `names_characters.csv`

These are checked first (fast, no API cost).

### Step 3.4: STAGE 1 - Name/Fantasy Entity Detection
**Location**: `translate_words.py` → `translate_tier_file()` → STAGE 1

**Process:**
1. **Pre-filter with name databases** (fast check)
   - If word is in name databases → flag as name

2. **ChatGPT filtering** (for remaining words)
   - Uses **GPT-4o** (configurable via `NAME_FILTER_MODEL`)
   - Processes words in batches of 50
   - Provides subtitle context (first 2000 chars)
   - Returns JSON with excluded words and reasons

**ChatGPT Prompt:**
- Analyzes words from TV series
- Identifies:
  - Character names
  - Place names
  - Fantasy entities
  - Fictional organizations
- Returns: `{"exclude": [...], "reason": {...}}`

**Result**: Adds `is_name_or_fantasy` column to CSV
- Format: `"name/fantasy entity (ChatGPT: character name)"`
- Format: `"name/fantasy entity (name filter: {word})"`

### Step 3.5: STAGE 1.5 - Simple Word Detection
**Location**: `translate_words.py` → `translate_tier_file()` → STAGE 1.5

Flags simple words based on:
1. **Vocabulary level A1 or A2** → Simple word
2. **In easy_words.csv filter** → Simple word
3. **High English frequency (> 1M) + not in vocabulary list** → Simple word
4. **Informal spelling** (repeated letters like "wassuuuup") → Simple word
5. **Short words (≤4 chars) with high frequency (> 1M)** → Simple word

**Result**: Updates `is_name_or_fantasy` column with simple word flags

### Step 3.6: STAGE 2 - Translation
**Location**: `translate_words.py` → `translate_tier_file()` → STAGE 2

**Process:**

1. **Extract Example Sentences**
   - For each word, finds example sentences from subtitle
   - Uses context around word occurrences
   - Stores in `examples` dictionary

2. **Translate in Batches**
   - Processes 10 words at a time
   - Uses **GPT-4o-mini** for translation
   - Provides:
     - Full subtitle context (up to 8000 chars)
     - Example sentences for each word
     - Series name for context

3. **Translation Prompt:**
   ```
   Translate words from TV series "{series_name}"
   
   SUBTITLE TEXT: {subtitle_context}
   WORDS TO TRANSLATE: {words_list}
   EXAMPLES: {examples}
   
   For each word, provide:
   - Translation to Russian
   - Example sentence from series
   - Translated example sentence
   ```

4. **Validate Translations**
   - Rejects empty translations
   - Rejects "N/A" translations
   - Retries failed translations individually
   - Uses case-insensitive key matching

5. **Update CSV**
   - Adds columns:
     - `translation` - Russian translation
     - `example_en` - Example sentence in English
     - `example_translated` - Example sentence in Russian
     - `is_name_or_fantasy` - Filtering flags (from Stage 1)

**Final CSV Format:**
```csv
word,series_frequency,english_frequency,vocabulary_level,translation,example_en,example_translated,is_name_or_fantasy
example,5,1000000,B1,пример,This is an example.,Это пример.,
test,3,2000000,A2,тест,Let's test this.,Давайте проверим это.,simple word (vocabulary level: A2)
```

### Step 3.7: Final Validation
**Location**: `translate_words.py` → `translate_tier_file()` → Final validation

- Checks all words have valid translations
- Reports any words without translations
- Provides summary statistics:
  - Total words
  - Words with valid translations
  - Words flagged as names/fantasy entities

---

## Stage 4: Display Results

### Step 4.1: Filter Words for Display
**Location**: `telegram_bot.py` → `send_tier_list_results()`

**Filtering Logic:**
1. **Exclude names/fantasy entities** (if `is_name_or_fantasy` column has value)
   - **EXCEPT**: Words with high vocabulary levels bypass filters
   - Level C (Advanced): C2 words always included
   - Level B: B2/C1/C2 words always included
   - Level A: A2/B1/B2/C1/C2 words always included

2. **Filter by vocabulary level** (based on user level)
   - Level C: Shows all levels (A1-C2)
   - Level B: Shows B1-C2
   - Level A: Shows A1-C2

3. **Limit results** (first message shows top 20)

### Step 4.2: Format and Send Results
**Location**: `telegram_bot.py` → `send_tier_list_results()`

Formats message:
```
📺 Fallout - Season 2, Episode 01

📚 Top 20 words to learn:

1. example → пример
   "This is an example."
   "Это пример."

2. test → тест
   "Let's test this."
   "Давайте проверим это."
...
```

---

## File Flow Diagram

```
User Input: "Fallout S02E01"
    ↓
[telegram_bot.py]
    ├─ normalize_series_name() → "Fallout"
    ├─ find_existing_tier_lists() → Not found
    ├─ find_existing_subtitle() → "Subtitles/Fallout/Season 2/Episode 01/..."
    └─ analyze_subtitle()
        ↓
[subtitle_analyzer.py] (subprocess)
    ├─ Load filters
    ├─ Parse subtitle → Extract words
    ├─ Load vocabulary levels
    ├─ Load English frequency
    ├─ Categorize into tiers
    └─ Save to tierlist/Fallout/S02E01/
        ↓
[telegram_bot.py]
    └─ translate_tier_list()
        ↓
[translate_words.py] (subprocess)
    ├─ STAGE 1: Name/fantasy entity detection (GPT-4o)
    ├─ STAGE 1.5: Simple word detection
    ├─ STAGE 2: Translation (GPT-4o-mini)
    └─ Save updated CSV with translations
        ↓
[telegram_bot.py]
    └─ send_tier_list_results()
        ├─ Filter words
        └─ Display to user
```

---

## Key Configuration

### Models Used

| Task | Model | Location | Configurable |
|------|-------|----------|--------------|
| Series name normalization | gpt-4o-mini | `telegram_bot.py:371` | No |
| Name/fantasy entity filtering | **gpt-4o** | `telegram_bot.py:NAME_FILTER_MODEL` | **Yes** (line 28) |
| Word translation | gpt-4o-mini | `translate_words.py:239` | No |

### Thresholds

| Setting | Value | Location |
|---------|-------|----------|
| Max English frequency (Tier 1) | 5,000,000 | `telegram_bot.py:573` |
| Series frequency threshold | 2 | `subtitle_analyzer.py` |
| Simple word frequency threshold | 1,000,000 | `translate_words.py:448` |
| Translation batch size | 10 | `translate_words.py:500` |
| Name filtering batch size | 50 | `telegram_bot.py:84` |

### Directories

| Directory | Purpose |
|-----------|---------|
| `Subtitles/` | Subtitle files (SRT or ZIP) |
| `tierlist/` | Generated tier lists and translations |
| `filters/` | Filter CSV files (names, easy words, etc.) |
| `Frequency list/English/` | Vocabulary levels and English frequency data |
| `output/` | Temporary output (legacy) |

---

## Error Handling

### Translation Failures
- If translation fails, shows "⚠️ Translation failed. Showing untranslated list."
- Bot still displays words without translations
- Errors logged to console and `bot.log`

### Missing Subtitles
- If subtitle not found, tries to download from OpenSubtitles
- If download fails, shows error message
- Translation can proceed without subtitle (generic translations)

### Missing Tier Lists
- If tier list not found, analyzes subtitle first
- If analysis fails, shows error message

---

## Performance Notes

- **Subtitle Analysis**: ~5-30 seconds (depends on file size)
- **Name Filtering**: ~10-60 seconds (depends on word count, GPT-4o is slower)
- **Translation**: ~30-120 seconds (depends on word count)
- **Total**: ~45 seconds to 3.5 minutes for new episode

---

## Future Improvements

1. **Caching**: Cache name/fantasy entity results to avoid re-checking
2. **Parallel Processing**: Process multiple episodes in parallel
3. **Incremental Updates**: Only translate new words when subtitle updates
4. **Hybrid Model**: Use gpt-4o-mini for initial filtering, gpt-4o for edge cases
