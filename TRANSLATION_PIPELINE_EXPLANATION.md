# Translation Pipeline Explanation

## Complete Translation Pipeline Flow

### Stage 1: User Request → Tier List Creation

```
User Input: "Game of Thrones S03E04"
    ↓
[telegram_bot.py: handle_message()]
    ├─ normalize_series_name() → "Game of Thrones"
    ├─ find_existing_tier_lists() → Check if tier lists exist
    ├─ find_existing_subtitle() → Find subtitle file
    └─ analyze_subtitle() → Create tier lists (if needed)
        ↓
[subtitle_analyzer.py] (subprocess)
    ├─ Parse subtitle → Extract words
    ├─ Categorize into 5 tiers:
    │   ├─ tier_1_hard_usable_words.csv (best for learning)
    │   ├─ tier_2_random_words.csv (rare words)
    │   ├─ tier_3_common_words.csv (common words)
    │   ├─ tier_4_rare_in_series.csv (common words rare in series) ⚠️
    │   └─ tier_5_filtered_words.csv (filtered out)
    └─ Save to tierlist/Game of Thrones/S03E04/
```

### Stage 2: Translation Process

#### Default Translation (tier_1 and tier_2 only)

When user requests a series, the system translates:

```
[telegram_bot.py: translate_tier_list()]
    ↓
[translate_words.py: translate_episode()]
    ├─ Translate tier_1_hard_usable_words.csv ✅
    └─ Translate tier_2_random_words.csv ✅
    └─ tier_4_rare_in_series.csv ❌ NOT TRANSLATED
```

**Current Behavior:**
- `translate_episode()` only translates tier_1 and tier_2 (lines 1220-1248)
- tier_4_rare_in_series.csv is **NOT** translated by default
- tier_3 and tier_5 are also not translated

#### Telegram bot path (`translate_tier_translations.py`)

The live bot uses **`translate_tier_translations.run()`**, not `translate_episode()`. On first load it passes **`tier_ids` = frequent bands only** (`tier_1`, `b1`, `b2`), so users are not blocked on API work for rare-in-series lists they may never open. **`tier_4c` / `tier_4b`** are translated **on demand** when the user taps **Rare C** / **Rare B** or uses **`/full`** (same list as Rare C).

#### Translation Steps (for tier_1 and tier_2)

For each tier file that gets translated:

```
[translate_words.py: translate_tier_file()]
    ↓
STAGE 1: Name/Fantasy Entity Detection
    ├─ Load name databases (fast pre-filter)
    ├─ ChatGPT filtering (GPT-4o, batches of 50)
    └─ Add is_name_or_fantasy column
    ↓
STAGE 1.5: Simple Word Detection
    ├─ Check vocabulary level (A1/A2 = simple)
    ├─ Check easy_words filter
    ├─ Check high frequency (>2M)
    └─ Update is_name_or_fantasy column
    ↓
STAGE 2: Translation
    ├─ Extract example sentences from subtitles
    ├─ Translate in batches (10 words, parallel processing)
    ├─ Use GPT-4o-mini with subtitle context
    ├─ Validate translations (reject N/A, empty, [Translation failed])
    ├─ Retry failed translations individually
    └─ Save translations to CSV
```

### Stage 3: Display Results

#### Main Tier List (tier_1)

```
User clicks "Rare in Series Hard Words" button
    ↓
[telegram_bot.py: send_rare_hard_words()]
    ├─ Uses tier_2_random_words.csv (NOT tier_4!)
    ├─ Checks for translations
    ├─ Triggers translation if needed
    └─ Displays results
```

#### Full List (can use tier_4)

```
User clicks "Full List" button
    ↓
[telegram_bot.py: send_full_list()]
    ├─ Determines tier file based on last_tier_type
    │   ├─ tier_1 → tier_1_hard_usable_words.csv
    │   ├─ tier_2 → tier_2_random_words.csv
    │   └─ tier_4 → tier_4_rare_in_series.csv ⚠️
    ├─ ❌ NO TRANSLATION CHECK/TRIGGER
    └─ Displays results (may show N/A if not translated)
```

## Problem: tier_4 Translation Failure

### Root Cause

**tier_4_rare_in_series.csv is never translated by the default pipeline:**

1. `translate_episode()` only translates tier_1 and tier_2
2. `send_full_list()` can display tier_4 but doesn't check/trigger translation
3. Result: tier_4 files have no translation column or show "N/A"

### Current Status

- ✅ tier_1_hard_usable_words.csv → Translated by default
- ✅ tier_2_random_words.csv → Translated by default
- ❌ tier_4_rare_in_series.csv → **NOT translated by default**
- ❌ tier_3_common_words.csv → Not translated
- ❌ tier_5_filtered_words.csv → Not translated

### Why tier_4 Failed

When `send_full_list()` displays tier_4:
1. File exists but has no `translation` column
2. No translation check/trigger in `send_full_list()`
3. System shows "N/A" for all words

## Solution Options

### Option 1: Add tier_4 to Default Translation
- Modify `translate_episode()` to also translate tier_4
- Pros: All tiers translated automatically
- Cons: More API calls, longer processing time

### Option 2: Add Translation Check to send_full_list
- Add translation detection logic (like in `send_tier_list_results`)
- Trigger translation if tier_4 needs it
- Pros: Translates on-demand, only when needed
- Cons: Requires user to click "Full List" first

### Option 3: Translate All Tiers by Default
- Modify `translate_episode()` to translate tier_1, tier_2, tier_3, tier_4
- Pros: Complete coverage
- Cons: Most API calls, longest processing time

## Recommendation

**Option 2** is best: Add translation check to `send_full_list()` for tier_4, similar to what exists in `send_tier_list_results()` and `send_rare_hard_words()`.

This ensures:
- tier_4 is translated when user requests it
- No unnecessary API calls for unused tiers
- Consistent behavior across all tier display functions
