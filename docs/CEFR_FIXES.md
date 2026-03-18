# CEFR Approach - Issues and Fixes

## Test Results Summary
- **Total tests**: 9 (3 series × 3 levels: B1, B2, C1)
- **Valid**: 0
- **Invalid**: 9
- **Average score**: 40/100

## Main Issues Identified

### 1. Simple/Common Words in Advanced Lists
**Problem**: Words like "crawl", "though", "before", "lad", "fool", "spin", "relish", "ruin", "timber", "scheduled", "saying", "chill", "ally", "joint", "vice", "genius", "monster" appear in B1+, B2+, and C1+ lists.

**Root Cause**: 
- These words may be marked as B2/C1/C2 in the CEFR database but are actually common words
- The CEFR database may have some inaccuracies
- Need additional filtering beyond CEFR level

**Fix**: 
- Add English frequency check to exclude very common words
- Enhance easy_words.csv filter with problematic words
- Apply stricter filtering for CEFR-based approach

### 2. Missing Name Filtering
**Problem**: Names filtering (capital letter detection + ChatGPT) is not applied to CEFR outputs.

**Fix**: Apply the same name filtering logic used in frequency approach to CEFR outputs.

### 3. Missing Translation
**Problem**: All words show "N/A" for translation.

**Fix**: Ensure translation process works for CEFR files (hard_words_for_LEVEL.csv).

## Fixes to Implement

1. ✅ **Add English frequency check to CEFR categorization**
   - Load English frequency data
   - Exclude words with frequency > threshold (e.g., top 10,000 most common)
   - This will filter out common words regardless of CEFR level

2. ✅ **Enhance easy_words.csv filter**
   - Add problematic words found in tests: crawl, though, before, lad, fool, spin, relish, ruin, timber, scheduled, saying, chill, ally, joint, vice, genius, monster, gasp, feast, bark, groan, grim, sacred, intact, distant, superficial, desperation

3. ✅ **Apply name filtering to CEFR outputs**
   - Use same detect_names_from_capitals function
   - Use same filter_names_and_fantasy_entities function
   - Apply in send_tier_list_results and send_full_list for CEFR approach

4. ✅ **Ensure translation works for CEFR files**
   - Update translate_episode to handle hard_words_for_LEVEL.csv
   - Test translation process

5. ✅ **Add minimum CEFR level gap**
   - Only include words that are at least 2 levels above user level (e.g., B1 user → only C1, C2 words)
   - This ensures words are clearly advanced
