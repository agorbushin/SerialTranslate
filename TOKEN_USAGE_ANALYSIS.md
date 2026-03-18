# Token Usage Analysis for Word Translation

## Translation Configuration

- **Model**: GPT-4o (line 257 in `translate_words.py`)
- **Batch Size**: 10 words per batch (line 788)
- **Processing**: Parallel batches (5 concurrent batches)

## Token Calculation Per Batch

### Input Tokens (Per Batch of 10 Words)

1. **System Message**: ~25 tokens
   ```
   "You are a helpful translator specializing in TV series translations. Always respond with valid JSON."
   ```

2. **User Prompt Components**:
   - **Base prompt text**: ~450 tokens
     - Instructions, guidelines, format requirements
   - **Subtitle context**: Up to 8,000 characters
     - Average: ~4,000-6,000 characters per episode
     - Tokens: ~1,000-1,500 tokens (roughly 4 chars per token)
   - **Words list**: ~25-35 tokens
     - 10 words formatted as: `"word1", "word2", ...`
   - **Examples**: ~80-150 tokens
     - Example sentences for each word (if available)
     - Format: `- 'word': example sentence\n`

   **Total Input per Batch**: ~1,580-2,160 tokens

### Output Tokens (Per Batch of 10 Words)

- **JSON Response**: ~250-400 tokens
  - Structure: `{"word1": {"translation": "...", "example_en": "...", "example_translated": "..."}, ...}`
  - Average: ~25-40 tokens per word

**Total Output per Batch**: ~250-400 tokens

### Total Tokens Per Batch

- **Input**: ~1,580-2,160 tokens
- **Output**: ~250-400 tokens
- **Total**: ~1,830-2,560 tokens per batch

## Token Usage Per Single Word

Since batches contain 10 words:

- **Input tokens per word**: ~158-216 tokens
- **Output tokens per word**: ~25-40 tokens
- **Total tokens per word**: ~183-256 tokens

**Average**: ~220 tokens per word

## Cost Calculation (GPT-4o Pricing)

Based on OpenAI pricing (as of 2024):
- **Input**: $2.50 per 1M tokens
- **Output**: $10.00 per 1M tokens

### Per Word Cost:
- **Input cost**: (220 tokens × 0.6 input ratio) × $2.50 / 1,000,000 = **$0.00033**
- **Output cost**: (220 tokens × 0.4 output ratio) × $10.00 / 1,000,000 = **$0.00088**
- **Total per word**: **~$0.00121** (0.12 cents per word)

### Per 100 Words:
- **~22,000 tokens** (input + output)
- **Cost**: ~$0.12

### Per 1,000 Words:
- **~220,000 tokens** (input + output)
- **Cost**: ~$1.20

## Factors Affecting Token Usage

### 1. Subtitle Length
- **Short episode** (2,000 chars): ~500 tokens for context
- **Average episode** (4,000-6,000 chars): ~1,000-1,500 tokens
- **Long episode** (8,000+ chars): ~2,000 tokens (capped at 8,000 chars)

### 2. Example Sentences
- **With examples**: +50-100 tokens per batch
- **Without examples**: Base prompt only

### 3. Word Complexity
- **Simple words**: Shorter translations, fewer output tokens
- **Complex words**: Longer translations, more output tokens

### 4. Batch Efficiency
- **10 words per batch**: Shares subtitle context (efficient)
- **1 word per batch**: Would use ~180-200 tokens per word (less efficient)

## Optimization Opportunities

### Current Efficiency
- ✅ **Batch processing**: Shares subtitle context across 10 words
- ✅ **Context limiting**: Caps subtitle at 8,000 chars
- ✅ **Parallel processing**: 5 batches concurrently

### Potential Improvements
1. **Increase batch size** (if API allows): More words share context
2. **Reduce subtitle context**: Use only relevant portions
3. **Cache subtitle context**: Reuse for multiple batches
4. **Use GPT-4o-mini for simple words**: Lower cost model

## Real-World Examples

### Example 1: Game of Thrones S03E04
- **Tier 1 words**: 18 words
- **Tier 2 words**: 210 words
- **Total**: 228 words
- **Estimated tokens**: ~50,160 tokens
- **Estimated cost**: ~$0.28

### Example 2: Fallout S02E01
- **Tier 1 words**: 15 words
- **Tier 2 words**: 167 words
- **Total**: 182 words
- **Estimated tokens**: ~40,040 tokens
- **Estimated cost**: ~$0.22

## Summary

| Metric | Value |
|--------|-------|
| **Tokens per word** | ~220 tokens |
| **Cost per word** | ~$0.00121 (0.12 cents) |
| **Cost per 100 words** | ~$0.12 |
| **Cost per 1,000 words** | ~$1.20 |
| **Batch size** | 10 words |
| **Model** | GPT-4o |

**Note**: Actual token usage may vary based on:
- Subtitle length
- Word complexity
- Example sentence availability
- API response format
