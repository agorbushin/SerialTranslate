# Name/Fantasy Entity Filtering - Current Status & Improvements

## Current Implementation

### Model Used
- **Model**: `gpt-4o-mini`
- **Temperature**: `0.2` (low for consistency)
- **Location**: `telegram_bot.py` lines 170, 273
- **Functions**: 
  - `filter_names_and_fantasy_entities()` (line 65)
  - `filter_names_and_fantasy_entities_with_reasons()` (line 193)

### Current Settings
```python
model="gpt-4o-mini"
temperature=0.2
response_format={"type": "json_object"}
```

### Prompt Quality
- ✅ Very detailed with many examples
- ✅ Clear exclusion/inclusion rules
- ✅ Series-specific context provided
- ⚠️ Could benefit from more recent examples
- ⚠️ Could use better structure for edge cases

## Improvement Options

### Option 1: Upgrade to GPT-4o (Recommended for Accuracy)
**Pros:**
- Better accuracy in detecting names vs common words
- Better understanding of context
- Fewer false positives/negatives

**Cons:**
- ~10x more expensive than gpt-4o-mini
- Slightly slower

**Cost Comparison:**
- gpt-4o-mini: ~$0.15 per 1M input tokens, $0.60 per 1M output tokens
- gpt-4o: ~$2.50 per 1M input tokens, $10.00 per 1M output tokens

### Option 2: Hybrid Approach (Best Balance)
**Strategy:**
1. First pass with gpt-4o-mini (fast, cheap)
2. Second pass with gpt-4o only for uncertain cases

**Implementation:**
- Use gpt-4o-mini for initial filtering
- Flag words with low confidence
- Re-check flagged words with gpt-4o

### Option 3: Improve Prompt (Free, Quick Win)
**Enhancements:**
- Add more recent series examples
- Better structure for edge cases
- Add confidence scoring
- More explicit instructions for ambiguous cases

### Option 4: Two-Stage Filtering
**Strategy:**
1. Stage 1: Pre-filter with name databases (already done)
2. Stage 2: ChatGPT for remaining words (current)
3. Stage 3: Optional verification with gpt-4o for edge cases

## Recommended Implementation

### Immediate (Free):
1. ✅ Improve prompt structure
2. ✅ Add more examples
3. ✅ Better error handling

### Short-term (Cost-effective):
1. Add configurable model selection
2. Implement hybrid approach (gpt-4o-mini + gpt-4o verification)
3. Add confidence scoring

### Long-term (Best accuracy):
1. Use gpt-4o for all filtering
2. Add caching for known words
3. Fine-tune on series-specific data
