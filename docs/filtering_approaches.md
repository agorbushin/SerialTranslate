# Three Approaches to Filter Easy Words from Tier 1

## Problem
Currently, Tier 1 (Hard Usable Words) contains many easy/common words like "okay", "dad", "maybe", "kind", "nice", "guy", "hope", "believe", etc. These have high English frequencies (20M+) and are clearly common vocabulary that learners likely already know.

## Analysis
- 113 out of 213 words (53%) in Tier 1 have English frequency > 20M
- Examples: "someone" (76M), "anything" (75M), "believe" (75M), "hope" (74M), "came" (73M), "fine" (71M)

## Three Filtering Approaches

### Approach 1: Absolute English Frequency Threshold
**Concept**: Filter out words that exceed a specific English frequency threshold, regardless of their series frequency.

**Implementation**:
- Add a parameter `--max-english-freq` (default: 20,000,000)
- Words with English frequency > threshold are excluded from Tier 1
- Simple and intuitive
- Easy to tune based on learner level

**Pros**:
- Simple to understand and implement
- Easy to adjust for different proficiency levels
- No external data needed

**Cons**:
- Arbitrary threshold choice
- Doesn't account for relative rarity
- May filter out domain-specific terms that happen to be common

**Example**: Filter out words with English frequency > 20M
- Would remove: "okay", "dad", "maybe", "kind", "nice", "guy", "hope", "believe", etc.
- Would keep: "vault", "maximus", "knight", "overseer", "wasteland", etc.

---

### Approach 2: Top N Most Common Words Exclusion List
**Concept**: Use a curated list of the most common English words (e.g., top 1000, 2000, 5000) and exclude those from Tier 1.

**Implementation**:
- Create/load a list of the top N most common words from the English frequency database
- Words appearing in this list are excluded from Tier 1
- Parameter: `--exclude-top-n` (default: 2000 or 5000)
- Can be based on actual frequency ranking or a standard word list

**Pros**:
- Based on actual word frequency rankings
- Can use established word lists (e.g., Oxford 3000, General Service List)
- More nuanced than absolute threshold
- Can exclude by rank percentile (e.g., top 5% most common)

**Cons**:
- Requires maintaining/loading a word list
- May need different lists for different proficiency levels
- Still somewhat arbitrary (which N to choose?)

**Example**: Exclude top 2000 most common words
- Would remove: "okay", "dad", "maybe", "kind", "nice", "guy", "hope", "believe", "came", "fine", etc.
- Would keep: "vault", "maximus", "knight", "overseer", "wasteland", "bounty", etc.

---

### Approach 3: Relative Frequency Percentile/Ranking
**Concept**: Calculate each word's percentile rank in the English frequency database and filter out words in the top X percentile.

**Implementation**:
- Calculate percentile rank for each word: `rank = (words_with_lower_freq / total_words) * 100`
- Filter out words above a certain percentile (e.g., top 10% or top 5%)
- Parameter: `--exclude-top-percentile` (default: 10, meaning exclude top 10% most common)
- More sophisticated: uses relative ranking rather than absolute values

**Pros**:
- Most sophisticated and data-driven approach
- Automatically adapts to the frequency distribution
- No arbitrary thresholds - based on actual distribution
- Can be combined with other approaches

**Cons**:
- More complex to implement (requires ranking calculation)
- Requires processing the full frequency database
- May need caching for performance

**Example**: Exclude words in top 10% by English frequency
- Would remove: Words ranked in top 10% (highest frequency)
- Would keep: Words in bottom 90% (relatively less common)
- Automatically adapts to the actual distribution

---

## Recommendation

**Best Approach**: **Approach 3 (Percentile-based)** combined with **Approach 1 (Absolute threshold)** as a fallback

**Why**:
1. Percentile-based is most sophisticated and adapts to data
2. Absolute threshold provides a simple safety net
3. Can be combined: exclude if word is in top 10% OR has frequency > 20M

**Implementation Priority**:
1. Start with Approach 1 (easiest, immediate improvement)
2. Add Approach 3 (more sophisticated, better long-term)
3. Optionally add Approach 2 (if you want to use curated word lists)

## Suggested Defaults
- `--max-english-freq 20000000` (20M) - filter very common words
- `--exclude-top-percentile 10` - exclude top 10% most common words
- Both can be used together (word excluded if it meets either condition)
