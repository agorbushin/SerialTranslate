# Three Approaches to Filter Easy Words from Hard Words Tier

## Problem
Tier 1 (Hard Usable Words) currently contains many easy/common words like "dad" (15M), "wife" (46M), "okay" (15M), "maybe" (51M), "kind" (70M), "nice" (69M), "guy" (45M), "hope" (74M), "believe" (75M), etc. These are clearly common vocabulary that learners likely already know.

## Current Situation
- **114 out of 203 words (56%)** in Tier 1 have English frequency > 20M
- Examples of easy words in Tier 1:
  - "someone" (76M), "anything" (75M), "believe" (75M)
  - "hope" (74M), "came" (73M), "fine" (71M)
  - "woman" (70M), "kind" (70M), "nice" (69M)
  - "dad" (15M), "wife" (46M), "father" (48M), "son" (58M)

---

## Approach 1: Filter CSV File (Manual Curation)
**Concept**: Create a CSV filter file with manually curated easy/common words.

**Implementation**:
- Create `filters/easy_words.csv` with common words like "dad", "wife", "okay", "maybe", "kind", "nice", "guy", "hope", "believe", etc.
- Leverages existing filter system - no code changes needed
- Can be based on common vocabulary lists (Oxford 3000, General Service List, etc.)

**Pros**:
- ✅ **Easiest to implement** - just add a CSV file
- ✅ Uses existing filter infrastructure
- ✅ Can be manually curated for specific needs
- ✅ Can include words that are easy but have low frequency (e.g., "okay")
- ✅ No code changes required

**Cons**:
- Requires manual maintenance
- May miss some easy words
- Subjective - what's "easy" varies by learner

**Example Implementation**:
```csv
word
dad
wife
okay
maybe
kind
nice
guy
hope
believe
came
fine
woman
coming
actually
leave
move
lead
went
allow
button
```

**Best for**: Quick implementation, manual control, specific word lists

---

## Approach 2: Absolute English Frequency Threshold
**Concept**: Filter out words that exceed a specific English frequency threshold.

**Implementation**:
- Add parameter `--max-english-freq` (default: 20,000,000)
- During categorization, exclude words from Tier 1 if `english_frequency > threshold`
- Can be combined with filter CSV for flexibility

**Pros**:
- ✅ **Automatic** - no manual word list needed
- ✅ Data-driven based on actual frequency
- ✅ Easy to tune (adjust threshold for different proficiency levels)
- ✅ Can be combined with other approaches

**Cons**:
- Arbitrary threshold choice
- May filter out domain-specific terms that happen to be common
- Doesn't account for relative rarity

**Code Changes Needed**:
```python
# In categorize_words() function
if not is_high_english and is_high_series:
    # Additional check: exclude if English frequency too high
    if english_count <= max_english_freq:  # New parameter
        tiers['tier_1_hard_usable'].append((word, series_count, english_count))
```

**Example**: Filter out words with English frequency > 20M
- Would remove: "dad" (15M - kept), "wife" (46M - removed), "maybe" (51M - removed)
- Would keep: "vault" (5M), "overseer" (374K), "wasteland" (821K)

**Best for**: Automatic filtering, data-driven approach, easy to adjust

---

## Approach 3: Top N Most Common Words (Frequency-Based)
**Concept**: Automatically generate a filter from the top N most common words in the English frequency database.

**Implementation**:
- Load English frequency list, sort by frequency
- Take top N words (e.g., top 2000 or top 5000)
- Either:
  - Option A: Auto-generate `filters/easy_words_auto.csv` on first run
  - Option B: Filter programmatically during categorization
- Parameter: `--exclude-top-n` (default: 2000)

**Pros**:
- ✅ **Fully automatic** - based on actual frequency rankings
- ✅ Can use percentile instead of absolute count (e.g., top 5%)
- ✅ Adapts to the actual frequency distribution
- ✅ Can be cached/generated once

**Cons**:
- Requires processing full frequency database
- May need caching for performance
- Still somewhat arbitrary (which N to choose?)

**Code Changes Needed**:
```python
def get_top_n_common_words(english_freqs: Dict[str, int], n: int) -> Set[str]:
    """Get top N most common words by frequency."""
    sorted_words = sorted(english_freqs.items(), key=lambda x: x[1], reverse=True)
    return {word.lower() for word, _ in sorted_words[:n]}

# In main()
top_n_words = get_top_n_common_words(english_freqs, args.exclude_top_n)
excluded_words.update(top_n_words)
```

**Example**: Exclude top 2000 most common words
- Would remove: All words ranked 1-2000 by English frequency
- Would keep: Words ranked 2001+ (less common words)

**Best for**: Automatic, data-driven, percentile-based filtering

---

## Recommendation: Hybrid Approach

**Best Solution**: **Combine Approach 1 + Approach 2**

1. **Start with Approach 1** (Filter CSV):
   - Create `filters/easy_words.csv` with obviously easy words
   - Quick win, no code changes
   - Can include words that are easy but have low frequency

2. **Add Approach 2** (Frequency Threshold):
   - Add `--max-english-freq` parameter (default: 20M)
   - Catches common words automatically
   - Easy to adjust for different proficiency levels

**Why This Combination**:
- Approach 1 handles edge cases (e.g., "okay" has 15M but is very easy)
- Approach 2 handles the bulk automatically (catches 114 easy words)
- Both use existing infrastructure (filters system + simple code addition)
- Easy to maintain and adjust

**Implementation Priority**:
1. ✅ **Approach 1** - Create `filters/easy_words.csv` (5 minutes)
2. ✅ **Approach 2** - Add frequency threshold parameter (15 minutes)
3. ⏭️ **Approach 3** - Add if needed for more sophisticated filtering

---

## Suggested Defaults

- **Filter CSV**: `filters/easy_words.csv` with ~50-100 obviously easy words
- **Frequency Threshold**: `--max-english-freq 20000000` (20M)
- **Combined**: Word excluded if it's in CSV OR has frequency > 20M

This would filter out ~114 easy words from Tier 1, leaving only truly hard usable words.
