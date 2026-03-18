# Quality Improvement Suggestions

## Current Issues (from TEST_REPORT.md)
- **Names**: 65.1% of issues (character names like "hughie", "neuman", "stark")
- **Fictional Entities**: 16.3% (like "vought", "dothraki")
- **Simple Words**: 16.3% (like "superhero", "furnace", "bro")
- **Swear Words**: 2.3%

---

## Improvement Ideas

### 1. **Names Detection Improvements**

#### A. Pre-filter with Comprehensive Name Databases
**Idea**: Check words against large name databases before ChatGPT analysis
- **Pros**: Fast, catches common names immediately
- **Cons**: Requires maintaining/updating databases
- **Implementation**: 
  - Use existing `names_male.csv`, `names_female.csv`, `names_last.csv` more effectively
  - Add popular name databases (e.g., US Social Security name lists, Wikipedia name lists)
  - Check if word matches any name pattern (capitalization, common name endings)

#### B. Enhanced Capitalization Pattern Detection
**Idea**: Bring back capitalization detection but make it smarter
- **Pros**: Catches names that appear capitalized in subtitles
- **Cons**: Can have false positives (sentence starts)
- **Implementation**:
  - Check if word appears capitalized in middle of sentences (not just at start)
  - Track capitalization frequency: if word is capitalized >50% of time, likely a name
  - Combine with other signals (not in dictionary, low frequency, etc.)

#### C. Multiple ChatGPT Passes with Different Prompts
**Idea**: Run ChatGPT filtering 2-3 times with different prompts/approaches
- **Pros**: More thorough, catches edge cases
- **Cons**: More API calls, slower
- **Implementation**:
  - Pass 1: Focus on character names
  - Pass 2: Focus on place names and organizations
  - Pass 3: Focus on series-specific entities
  - Combine results (if any pass flags it, exclude)

#### D. Use NER (Named Entity Recognition) Libraries
**Idea**: Use spaCy or similar libraries for name detection
- **Pros**: Industry-standard, well-tested
- **Cons**: Requires additional dependency, may need fine-tuning
- **Implementation**:
  - Use spaCy's NER model to identify PERSON, ORG, GPE entities
  - Combine with ChatGPT results
  - Fallback to ChatGPT if NER doesn't catch it

#### E. Series-Specific Name Databases
**Idea**: Build and maintain character name lists per series
- **Pros**: Very accurate for known series
- **Cons**: Requires manual maintenance, doesn't help with new series
- **Implementation**:
  - Create `filters/series_names/` directory
  - Add `the_boys_characters.csv`, `game_of_thrones_characters.csv`, etc.
  - Check against these before ChatGPT

#### F. Dictionary Lookup Verification
**Idea**: Check if word exists in standard English dictionaries
- **Pros**: Real words are less likely to be names
- **Cons**: Some names are also real words (e.g., "butcher", "cookie")
- **Implementation**:
  - Use PyDictionary or similar to check if word has dictionary definitions
  - If no definition found AND flagged by ChatGPT, more likely a name
  - Combine signals: no dictionary + ChatGPT flag + low frequency = name

---

### 2. **Simple Words Detection Improvements**

#### A. Lower Frequency Threshold
**Idea**: Reduce the 2M frequency threshold for simple words
- **Pros**: Catches more common words
- **Cons**: Might exclude some legitimate hard words
- **Implementation**:
  - Change from 2M to 1M or 500K
  - Make it configurable per user level (but we removed levels, so just one threshold)

#### B. Use ChatGPT to Identify Simple Words
**Idea**: Add ChatGPT pass specifically for simple word detection
- **Pros**: Context-aware, can identify informal/slang
- **Cons**: Additional API calls
- **Implementation**:
  - After name filtering, send remaining words to ChatGPT
  - Ask: "Which of these are simple/common words that a beginner would know?"
  - Flag words that ChatGPT identifies as simple

#### C. Expand easy_words.csv Filter
**Idea**: Add more words to the easy_words filter
- **Pros**: Simple, fast, no API calls
- **Cons**: Requires manual curation
- **Implementation**:
  - Review test results and add all flagged simple words
  - Add common informal words ("bro", "kidding", "superhero")
  - Add high-frequency words from Oxford 3000

#### D. Check Against Multiple Word Lists
**Idea**: Use multiple "common word" lists
- **Pros**: More comprehensive coverage
- **Cons**: Need to maintain multiple lists
- **Implementation**:
  - Check against Oxford 3000 (already have)
  - Check against most common 1000/2000/5000 words
  - Check against academic word lists
  - If word in ANY common list, flag as simple

#### E. Vocabulary Level Stricter Enforcement
**Idea**: Always exclude A1/A2 words, and be stricter with B1
- **Pros**: Uses existing vocabulary level data
- **Cons**: Might be too strict
- **Implementation**:
  - Exclude A1, A2 (already doing)
  - Consider excluding B1 if frequency > 1M
  - Only show B2, C1, C2 for Advanced level

#### F. Word Length + Frequency Combination
**Idea**: Short words with high frequency are likely simple
- **Pros**: Catches words like "bro", "peg"
- **Cons**: Might miss some legitimate short words
- **Implementation**:
  - If word length <= 4 AND frequency > 1M → simple
  - If word length <= 3 AND frequency > 500K → simple
  - Already partially implemented, but could be stricter

---

### 3. **Fictional Entities Detection Improvements**

#### A. Enhanced ChatGPT Prompt with Series Context
**Idea**: Provide more series-specific context to ChatGPT
- **Pros**: Better understanding of what's fictional
- **Cons**: Requires more subtitle text, more tokens
- **Implementation**:
  - Include more subtitle context (currently 2000 chars, could be 5000)
  - Add series description/summary to prompt
  - Ask ChatGPT to identify series-specific terms

#### B. Dictionary Lookup for Fictional Entities
**Idea**: Check if word exists in dictionaries
- **Pros**: Real words are less likely to be fictional entities
- **Cons**: Some fictional entities use real words (e.g., "brotherhood")
- **Implementation**:
  - Use PyDictionary to check if word has standard definitions
  - If no definition AND ChatGPT flags it → likely fictional
  - If has definition → less likely fictional (but could still be series-specific usage)

#### C. Series-Specific Entity Databases
**Idea**: Maintain lists of known fictional entities per series
- **Pros**: Very accurate for known series
- **Cons**: Requires manual maintenance
- **Implementation**:
  - Create `filters/fictional_entities/` directory
  - Add `the_boys_entities.csv`, `fallout_entities.csv`, etc.
  - Check against these before ChatGPT

#### D. Frequency Analysis for Fictional Entities
**Idea**: Fictional entities often have very low English frequency
- **Pros**: Simple heuristic
- **Cons**: Some real words also have low frequency
- **Implementation**:
  - If English frequency < 100K AND ChatGPT flags it → likely fictional
  - Combine with dictionary lookup

---

### 4. **Combined/Multi-Stage Approaches**

#### A. Three-Stage Filtering Pipeline
**Idea**: Pre-filter → ChatGPT → Post-filter
- **Stage 1 (Pre-filter)**: Name databases, easy_words, swear_words, frequency checks
- **Stage 2 (ChatGPT)**: Context-aware analysis for names, fictional entities
- **Stage 3 (Post-filter)**: Dictionary lookup, final frequency checks, vocabulary level
- **Pros**: Comprehensive, catches issues at multiple levels
- **Cons**: More complex, slower

#### B. Confidence Scoring System
**Idea**: Assign confidence scores to each filter decision
- **Pros**: Can make nuanced decisions (e.g., "probably a name" vs "definitely a name")
- **Cons**: More complex logic
- **Implementation**:
  - Each filter gives a score (0-1)
  - Combine scores: if total > threshold, exclude
  - Example: Name database match (0.8) + ChatGPT flag (0.7) + no dictionary (0.3) = 1.8 → exclude

#### C. Machine Learning Approach
**Idea**: Train a model to classify words as name/simple/fictional
- **Pros**: Could be very accurate with enough training data
- **Cons**: Requires training data, model maintenance
- **Implementation**:
  - Collect labeled data from test results
  - Train classifier (features: frequency, length, vocabulary level, ChatGPT flags, etc.)
  - Use model to predict if word should be excluded

---

## Recommended Implementation Priority

### Phase 1 (Quick Wins - High Impact)
1. **Expand easy_words.csv** - Add all simple words from test results
2. **Lower frequency threshold** - From 2M to 1M for simple words
3. **Use name filters more effectively** - Check against existing name CSV files
4. **Enhanced ChatGPT prompt** - Add more examples, better instructions

### Phase 2 (Medium Effort - Good Impact)
5. **Dictionary lookup verification** - Check if words exist in dictionaries
6. **Multiple ChatGPT passes** - 2-3 passes with different focuses
7. **Series-specific name databases** - For popular series
8. **ChatGPT for simple words** - Add dedicated simple word detection pass

### Phase 3 (Higher Effort - Advanced)
9. **NER library integration** - Use spaCy for name detection
10. **Three-stage filtering pipeline** - Comprehensive multi-stage approach
11. **Confidence scoring** - More nuanced filtering decisions
12. **Machine learning model** - Train classifier for word classification

---

## Quick Implementation Suggestions

### Option 1: Conservative (Low Risk)
- Expand `easy_words.csv` with test results
- Lower frequency threshold to 1M
- Enhance ChatGPT prompt with more examples
- Use existing name filters more effectively

### Option 2: Moderate (Balanced)
- All of Option 1, plus:
- Dictionary lookup for verification
- Two ChatGPT passes (names + simple words)
- Series-specific name databases for top 5 series

### Option 3: Aggressive (Maximum Quality)
- All of Option 2, plus:
- NER library integration
- Three-stage filtering pipeline
- Confidence scoring system
- Machine learning classifier

---

## Questions to Consider

1. **Speed vs Quality**: How much slower can the process be? (More ChatGPT passes = slower)
2. **Maintenance**: How much manual curation are you willing to do? (Name databases, entity lists)
3. **Dependencies**: Are you okay adding new libraries? (spaCy, PyDictionary, etc.)
4. **Cost**: More ChatGPT calls = more API costs. Acceptable?
5. **Accuracy Target**: What's the acceptable error rate? (Currently ~7 issues per episode)
