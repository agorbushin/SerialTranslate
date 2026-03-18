# Translation Code Location Guide

## Main Translation File

**File:** `translate_words.py`

This is where all the core translation logic lives.

## Key Functions and Their Locations

### 1. Main Entry Point: `translate_tier_file()`
**Location:** `translate_words.py` lines **465-1137**

**Purpose:** Main function that orchestrates the entire translation process for a tier CSV file.

**Process Flow:**
```
translate_tier_file()
    ├─ Read CSV file
    ├─ Check existing translations
    ├─ STAGE 1: Name/Fantasy Entity Detection (line 570)
    ├─ STAGE 1.5: Simple Word Detection (line 659)
    └─ STAGE 2: Translation (line 779)
```

### 2. Core Translation Function: `translate_words_with_context_async()`
**Location:** `translate_words.py` lines **174-303**

**Purpose:** The actual OpenAI API call that translates words with context.

**Key Features:**
- Uses `AsyncOpenAI` for parallel processing
- Takes subtitle text for context
- Uses GPT-4o model
- Returns JSON with translations, examples

**API Call:**
```python
response = await client.chat.completions.create(
    model="gpt-4o",
    messages=[...],
    temperature=0.3,
    response_format={"type": "json_object"}
)
```

### 3. Sync Version: `translate_words_with_context()`
**Location:** `translate_words.py` lines **304-413**

**Purpose:** Synchronous version (legacy, but still available).

### 4. Batch Translation: `translate_batch()`
**Location:** `translate_words.py` lines **415-463**

**Purpose:** Wraps `translate_words_with_context_async()` for batch processing.

### 5. Episode Translation: `translate_episode()`
**Location:** `translate_words.py` lines **1187-1263**

**Purpose:** Translates tier_1 and tier_2 for an entire episode.

**Note:** Only translates tier_1 and tier_2 by default (tier_4 is skipped).

## Translation Pipeline Stages

### STAGE 1: Name/Fantasy Entity Detection
**Location:** `translate_words.py` lines **570-658**

**Function:** `filter_names_and_fantasy_entities_with_reasons()`
- Uses GPT-4o to identify proper nouns and fantasy entities
- Adds `is_name_or_fantasy` column to CSV
- Processes in batches of 50 words

### STAGE 1.5: Simple Word Detection
**Location:** `translate_words.py` lines **659-678**

**Checks:**
- Vocabulary level (A1/A2 = simple)
- Easy words filter
- High frequency words (>2M)

### STAGE 2: Translation
**Location:** `translate_words.py` lines **779-1137**

**Process:**
1. Extract example sentences from subtitles (line 775)
2. Translate in batches of 10 words (parallel processing)
3. Use `translate_words_with_context_async()` (line 174)
4. Validate translations (reject N/A, empty, [Translation failed])
5. Retry failed translations individually
6. Save to CSV

## How Translation is Triggered

### From Telegram Bot

1. **Initial Request:** `telegram_bot.py` → `handle_message()` (line 1580)
   - Calls `translate_tier_list()` (line 1244)
   - Which calls `translate_episode()` in `translate_words.py`

2. **Tier 1 Display:** `telegram_bot.py` → `send_tier_list_results()` (line 2036)
   - Checks if translation needed
   - Calls `translate_tier_list()` if needed

3. **Tier 2 Display:** `telegram_bot.py` → `send_rare_hard_words()` (line 2349)
   - Checks if translation needed
   - Calls `translate_specific_tier_file()` (line 1244)
   - Which calls `translate_tier_file()` in `translate_words.py`

### Direct Command Line

```bash
# Translate specific tier file
python3 translate_words.py --tier-file tierlist/Game of Thrones/S03E04/tier_2_random_words.csv

# Translate episode (tier_1 and tier_2)
python3 translate_words.py --episode-dir tierlist/Game of Thrones/S03E04
```

## Translation Data Flow

```
CSV File (tier_X_words.csv)
    ↓
translate_tier_file()
    ↓
STAGE 1: Name Filtering
    ↓
STAGE 1.5: Simple Word Detection
    ↓
STAGE 2: Translation
    ├─ Extract examples from subtitles
    ├─ translate_words_with_context_async()
    │   └─ OpenAI API (GPT-4o)
    ├─ Validate results
    ├─ Retry failures
    └─ Save to CSV
```

## Key Translation Logic Details

### Translation Prompt
**Location:** `translate_words.py` lines **210-252** (async) and **340-383** (sync)

**Key Requirements:**
- Contextual translations (1-5 words)
- Use series context
- Never use N/A
- Never use transliteration
- Provide example sentences

### Error Handling
**Location:** `translate_words.py` lines **254-303** (async)

**Handles:**
- API errors (401, 429, 500, 503)
- JSON decode errors
- Timeout errors
- Empty responses

### Retry Logic
**Location:** `translate_words.py` lines **854-865**

**Retries:**
- Words with "[Translation failed]"
- Words with "N/A"
- Words with empty translations

## Summary

**Main Translation Code:** `translate_words.py`
- **Entry Point:** `translate_tier_file()` (line 465)
- **Core Translation:** `translate_words_with_context_async()` (line 174)
- **API Model:** GPT-4o
- **Processing:** Parallel batches of 10 words
- **Context:** Subtitle text + example sentences

**Triggered From:**
- `telegram_bot.py` → `translate_tier_list()` or `translate_specific_tier_file()`
- Command line → `translate_words.py --tier-file` or `--episode-dir`
