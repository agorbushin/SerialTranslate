# Tier 2 Translation Fix - Unified Translation Process

## Problem

When user clicks "Rare in Series Hard Words" button:
- `send_rare_hard_words()` was calling `translate_tier_list()` 
- `translate_tier_list()` translates both tier_1 and tier_2
- User wanted tier_2 to be translated directly using the same process as tier_1
- Same checks, same filters, same translation logic

## Solution

Created a unified wrapper function `translate_specific_tier_file()` that:
1. Translates a specific tier file directly (tier_1, tier_2, tier_4, etc.)
2. Uses the exact same translation process as tier_1
3. Same checks, same filters, same translation logic via `translate_tier_file()`

## Changes Made

### 1. New Function: `translate_specific_tier_file()`
**Location:** `telegram_bot.py` lines 1244-1310

**Purpose:** Translate a specific tier file using the same process as tier_1

**Process:**
- Calls `translate_words.py --tier-file` with the specific tier file
- Uses `translate_tier_file()` which applies:
  - STAGE 1: Name/Fantasy Entity Detection (same as tier_1)
  - STAGE 1.5: Simple Word Detection (same as tier_1)
  - STAGE 2: Translation with context (same as tier_1)
  - Same validation, same retry logic, same filters

### 2. Updated `send_rare_hard_words()`
**Location:** `telegram_bot.py` lines 2478-2520

**Changes:**
- Now calls `translate_specific_tier_file(tier_file, subtitle_path)` instead of `translate_tier_list()`
- Translates tier_2 directly (tier_2_random_words.csv)
- Uses the exact same process as tier_1
- Added API health check (matching tier_1 behavior)

## Translation Pipeline for Tier 2

When "Rare in Series Hard Words" button is clicked:

```
User clicks button
    ↓
[send_rare_hard_words()]
    ├─ Check if tier_2 needs translation
    ├─ Get subtitle path
    ├─ API health check
    └─ translate_specific_tier_file(tier_2_random_words.csv)
        ↓
[translate_words.py: translate_tier_file()]
    ├─ STAGE 1: Name/Fantasy Entity Detection ✅ (same as tier_1)
    ├─ STAGE 1.5: Simple Word Detection ✅ (same as tier_1)
    ├─ STAGE 2: Translation with Context ✅ (same as tier_1)
    ├─ Validation & Retry ✅ (same as tier_1)
    └─ Save translations to CSV ✅
```

## Benefits

1. **Consistent Process:** tier_2 now uses the exact same translation process as tier_1
2. **Same Checks:** Name filtering, simple word detection, validation - all identical
3. **Same Filters:** Vocabulary level filtering, name/fantasy entity filtering - all identical
4. **Direct Translation:** tier_2 is translated directly, not as part of a batch
5. **Reusable:** Function can be used for tier_4 and other tiers in the future

## Testing

To verify the fix works:

1. Request a series (e.g., "Game of Thrones S03E04")
2. Click "Rare in Series Hard Words" button
3. System should:
   - Detect if tier_2 needs translation
   - Show "⏳ Translating rare in series hard words..."
   - Translate tier_2 using the same process as tier_1
   - Display translated words

## Code Comparison

### Before:
```python
# Translated both tier_1 and tier_2
translate_success = await loop.run_in_executor(
    None,
    translate_tier_list,  # Translates both tiers
    episode_dir,
    subtitle_path
)
```

### After:
```python
# Translates tier_2 directly using same process as tier_1
translate_success = await loop.run_in_executor(
    None,
    translate_specific_tier_file,  # Translates specific tier file
    tier_file,  # tier_2_random_words.csv
    subtitle_path
)
```

## Result

✅ **tier_2 now uses the exact same translation process as tier_1**
- Same name filtering
- Same simple word detection
- Same translation logic
- Same validation and retry
- Same filters

The wrapper function ensures consistency across all tiers.
