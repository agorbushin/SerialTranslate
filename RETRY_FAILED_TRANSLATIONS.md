# Retry Failed Translations Feature

## Overview

The system now automatically retries words with failed or missing translations when translation is requested, without requiring the `--overwrite` flag.

## Behavior

### Automatic Retry Logic

When `translate_tier_file()` is called:

1. **Identifies words needing translation:**
   - Words with empty translation
   - Words with "N/A" translation
   - Words with "[Translation failed]" translation

2. **Preserves valid translations:**
   - Words with valid translations are preserved
   - Only words needing retry are translated

3. **Overwrite flag behavior:**
   - `--overwrite` flag: Retranslates ALL words (including valid ones)
   - No flag: Only retries words with failed/missing translations

### Example Scenarios

#### Scenario 1: Some words failed, some succeeded
```
Word 1: "hello" → "привет" (valid) ✓
Word 2: "world" → "[Translation failed]" (needs retry) ⚠️
Word 3: "test" → "N/A" (needs retry) ⚠️
```

**Result:** Only Word 2 and Word 3 are retried. Word 1 is preserved.

#### Scenario 2: All words have valid translations
```
Word 1: "hello" → "привет" (valid) ✓
Word 2: "world" → "мир" (valid) ✓
```

**Result:** No translation needed. Returns early with success message.

#### Scenario 3: Using --overwrite flag
```
Word 1: "hello" → "привет" (valid) ✓
Word 2: "world" → "мир" (valid) ✓
```

**Result:** Both words are retranslated (even though they're valid).

## Implementation Details

### Code Changes

1. **`translate_words.py` - `translate_tier_file()`:**
   - Added logic to identify `words_needing_translation` and `words_with_valid_translation`
   - Modified `words_to_translate` to only include words needing retry (unless overwrite is True)
   - Added early return if all words have valid translations and overwrite is False

2. **`telegram_bot.py` - `translate_tier_list()`:**
   - Removed `--overwrite` flag from default command
   - System now automatically retries failed translations without overwriting valid ones

### Translation Status Detection

Words are considered to need retry if:
- `translation` field is empty or missing
- `translation` is "N/A" (case-insensitive)
- `translation` is "[Translation failed]"

Words are considered valid if:
- `translation` field has a non-empty value
- `translation` is not "N/A"
- `translation` is not "[Translation failed]"

## User Experience

### From Bot
When user requests translation:
- System automatically identifies words with failed/missing translations
- Only retries those words
- Preserves existing valid translations
- Shows progress: "Retrying translation for X words with failed/missing translations"

### From Command Line
```bash
# Retry only failed translations (default)
python3 translate_words.py --episode-dir tierlist/Series/S01E01 --subtitle Subtitles/...

# Retranslate all words (including valid ones)
python3 translate_words.py --episode-dir tierlist/Series/S01E01 --subtitle Subtitles/... --overwrite
```

## Benefits

1. **Efficient:** Only retries words that actually need translation
2. **Preserves work:** Doesn't waste API calls retranslating valid translations
3. **Automatic:** No need to manually identify failed words
4. **Flexible:** `--overwrite` flag still available for full retranslation

## Testing

To test the feature:

1. Create a tier file with some valid translations and some "[Translation failed]"
2. Run translation without `--overwrite` flag
3. Verify only failed words are retried
4. Verify valid translations are preserved
