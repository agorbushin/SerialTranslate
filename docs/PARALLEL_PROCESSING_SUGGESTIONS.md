# Parallel Processing Suggestions for ChatGPT API Calls

## Overview

This document outlines strategies to implement parallel processing for ChatGPT API calls to make the bot more responsive. Currently, most ChatGPT operations are sequential, which significantly slows down the bot.

## Current Bottlenecks

### 1. Name/Fantasy Entity Filtering (`filter_names_and_fantasy_entities_with_reasons`)
- **Location**: `telegram_bot.py` lines 197-420
- **Current**: Sequential processing of batches (50 words per batch)
- **Impact**: For 200 words = 4 batches × ~3-5 seconds each = **12-20 seconds**
- **Potential Speedup**: 3-4x with parallel processing

### 2. Word Translation (`translate_tier_file`)
- **Location**: `translate_words.py` lines 298-730
- **Current**: Sequential processing of batches (10 words per batch)
- **Impact**: For 100 words = 10 batches × ~2-3 seconds each = **20-30 seconds**
- **Potential Speedup**: 5-10x with parallel processing

### 3. Phrasal Verb Verification (`verify_phrasal_verbs_with_chatgpt`)
- **Location**: `telegram_bot.py` lines 1988-2074
- **Current**: Sequential processing of batches (20 phrasal verbs per batch)
- **Impact**: For 100 phrasal verbs = 5 batches × ~3-4 seconds each = **15-20 seconds**
- **Potential Speedup**: 3-5x with parallel processing

## Implementation Strategy

### Approach 1: Async Batch Processing (Recommended)

Use `asyncio.gather()` to process multiple batches concurrently while respecting rate limits.

#### Benefits:
- ✅ Significant speedup (3-10x depending on operation)
- ✅ Respects API rate limits with semaphore
- ✅ Maintains code structure
- ✅ Easy to implement

#### Implementation Example for Name Filtering:

```python
import asyncio
from typing import List, Dict, Set
from openai import AsyncOpenAI

async def filter_names_and_fantasy_entities_with_reasons_parallel(
    words: List[str], 
    subtitle_text: str, 
    series_name: str, 
    openai_client: AsyncOpenAI,
    max_concurrent: int = 5  # Process 5 batches at once
) -> tuple[Set[str], Dict[str, str]]:
    """Parallel version of name/fantasy entity filtering."""
    if not words:
        return set(), {}
    
    all_tags = {}
    batch_size = 50
    semaphore = asyncio.Semaphore(max_concurrent)  # Limit concurrent requests
    
    async def process_batch(batch_words: List[str], batch_num: int) -> Dict[str, str]:
        """Process a single batch of words."""
        async with semaphore:  # Acquire semaphore before API call
            subtitle_context = subtitle_text[:4000] if len(subtitle_text) > 4000 else subtitle_text
            words_text = ", ".join([f'"{w}"' for w in batch_words])
            
            prompt = f"""You are analyzing words from the TV series "{series_name}". 
            
WORDS TO CHECK:
{words_text}

SUBTITLE CONTEXT:
{subtitle_context[:2000]}

For EACH word in the list above, assign ONE of these tags:
1. "name/fantasy entity" - if it's a proper noun, character name, place name, or fantasy entity
2. "normal word" - if it's a regular English word that can be learned as vocabulary

Return ONLY a JSON object with this structure (MUST include ALL words from the list):
{{
    "tags": {{
        "word1": "name/fantasy entity - character name",
        "word2": "normal word",
        "word3": "name/fantasy entity - place name",
        "word4": "normal word"
    }}
}}

CRITICAL: You MUST provide a tag for EVERY word in the list. Use "normal word" for words that don't fit any exclusion category.

[Rest of prompt...]"""
            
            try:
                response = await openai_client.chat.completions.create(
                    model=NAME_FILTER_MODEL,
                    messages=[
                        {"role": "system", "content": "You are a word classifier..."},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.2,
                    response_format={"type": "json_object"}
                )
                
                result = json.loads(response.choices[0].message.content)
                batch_tags = result.get("tags", {})
                
                print(f"ChatGPT batch {batch_num}: Processed {len(batch_words)} words")
                return batch_tags
                
            except Exception as e:
                print(f"Error filtering batch {batch_num}: {e}")
                return {}
    
    # FIRST PASS: Process all batches in parallel
    print("\n" + "="*60)
    print("FIRST PASS: Tagging all words with ChatGPT (parallel)...")
    print("="*60)
    
    batches = [
        (words[i:i+batch_size], i//batch_size + 1)
        for i in range(0, len(words), batch_size)
    ]
    
    # Process all batches concurrently
    batch_results = await asyncio.gather(*[
        process_batch(batch_words, batch_num)
        for batch_words, batch_num in batches
    ])
    
    # Merge results
    for batch_tags in batch_results:
        for word, tag in batch_tags.items():
            all_tags[word] = tag
    
    # SECOND PASS: Process untagged words in parallel
    untagged_words = [w for w in words if w not in all_tags and w.lower() not in {k.lower() for k in all_tags.keys()}]
    
    if untagged_words:
        print(f"\nSECOND PASS: Tagging {len(untagged_words)} untagged words (parallel)...")
        untagged_batches = [
            (untagged_words[i:i+batch_size], i//batch_size + 1)
            for i in range(0, len(untagged_words), batch_size)
        ]
        
        untagged_results = await asyncio.gather(*[
            process_batch(batch_words, batch_num)
            for batch_words, batch_num in untagged_batches
        ])
        
        for batch_tags in untagged_results:
            for word, tag in batch_tags.items():
                all_tags[word] = tag
    
    # Extract names/fantasy entities
    names_set = {word for word, tag in all_tags.items() 
                 if 'name/fantasy entity' in tag.lower()}
    
    return names_set, all_tags
```

#### Implementation Example for Translation:

```python
async def translate_words_parallel(
    words_data: List[Dict],
    subtitle_text: str,
    series_name: str,
    client: AsyncOpenAI,
    max_concurrent: int = 10  # Process 10 batches at once
) -> List[Dict]:
    """Parallel version of word translation."""
    batch_size = 10
    semaphore = asyncio.Semaphore(max_concurrent)
    
    async def translate_batch(batch: List[Dict], batch_num: int) -> List[Dict]:
        """Translate a single batch of words."""
        async with semaphore:
            words_list = [row['word'] for row in batch]
            words_text = ", ".join([f'"{w}"' for w in words_list])
            
            prompt = f"""Translate the following words from the TV series "{series_name}" to Russian.
            
WORDS TO TRANSLATE:
{words_text}

SUBTITLE CONTEXT:
{subtitle_text[:3000]}

Return ONLY a JSON object with translations:
{{
    "translations": {{
        "word1": "translation1",
        "word2": "translation2"
    }},
    "examples": {{
        "word1": ["example sentence 1", "example sentence 2"],
        "word2": ["example sentence 1"]
    }}
}}"""
            
            try:
                response = await client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": "You are a helpful translator..."},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.3,
                    response_format={"type": "json_object"}
                )
                
                result = json.loads(response.choices[0].message.content)
                translations = result.get("translations", {})
                examples = result.get("examples", {})
                
                # Update batch with translations
                for row in batch:
                    word = row['word']
                    if word in translations:
                        row['translation'] = translations[word]
                    if word in examples:
                        row['example_en'] = examples[word][0] if examples[word] else ''
                
                print(f"Translated batch {batch_num}: {len(batch)} words")
                return batch
                
            except Exception as e:
                print(f"Error translating batch {batch_num}: {e}")
                return batch
    
    # Split into batches
    batches = [
        (words_data[i:i+batch_size], i//batch_size + 1)
        for i in range(0, len(words_data), batch_size)
    ]
    
    # Process all batches concurrently
    print(f"Translating {len(words_data)} words in {len(batches)} batches (parallel)...")
    results = await asyncio.gather(*[
        translate_batch(batch, batch_num)
        for batch, batch_num in batches
    ])
    
    # Flatten results
    translated_words = []
    for batch_result in results:
        translated_words.extend(batch_result)
    
    return translated_words
```

### Approach 2: Thread Pool Executor (Alternative)

For synchronous code that can't be easily converted to async:

```python
from concurrent.futures import ThreadPoolExecutor, as_completed
import asyncio

def translate_batch_sync(batch: List[Dict], subtitle_text: str, series_name: str, api_key: str) -> List[Dict]:
    """Synchronous batch translation."""
    client = OpenAI(api_key=api_key)
    # ... translation logic ...
    return batch

async def translate_words_threaded(
    words_data: List[Dict],
    subtitle_text: str,
    series_name: str,
    api_key: str,
    max_workers: int = 10
) -> List[Dict]:
    """Use thread pool for parallel processing."""
    batch_size = 10
    batches = [
        words_data[i:i+batch_size]
        for i in range(0, len(words_data), batch_size)
    ]
    
    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all batches
        futures = [
            loop.run_in_executor(
                executor,
                translate_batch_sync,
                batch,
                subtitle_text,
                series_name,
                api_key
            )
            for batch in batches
        ]
        
        # Wait for all to complete
        results = await asyncio.gather(*futures)
    
    # Flatten results
    translated_words = []
    for batch_result in results:
        translated_words.extend(batch_result)
    
    return translated_words
```

## Rate Limiting Considerations

### OpenAI API Rate Limits:
- **Free tier**: 3 requests/minute
- **Tier 1**: 500 requests/minute
- **Tier 2**: 3,500 requests/minute
- **Tier 3**: 10,000 requests/minute

### Recommended Settings:

```python
# For name filtering (uses GPT-4o)
MAX_CONCURRENT_NAME_FILTERING = 3  # Conservative for GPT-4o

# For translation (uses GPT-4o-mini)
MAX_CONCURRENT_TRANSLATION = 10  # Can be higher for cheaper model

# For phrasal verb verification (uses GPT-4o-mini)
MAX_CONCURRENT_PHRASAL = 10
```

### Dynamic Rate Limiting:

```python
import time
from collections import deque

class RateLimiter:
    def __init__(self, max_requests: int, time_window: int = 60):
        self.max_requests = max_requests
        self.time_window = time_window
        self.requests = deque()
    
    async def acquire(self):
        """Wait if rate limit would be exceeded."""
        now = time.time()
        # Remove old requests outside time window
        while self.requests and self.requests[0] < now - self.time_window:
            self.requests.popleft()
        
        # Wait if at limit
        if len(self.requests) >= self.max_requests:
            sleep_time = self.time_window - (now - self.requests[0])
            if sleep_time > 0:
                await asyncio.sleep(sleep_time)
                # Clean up again after sleep
                while self.requests and self.requests[0] < now:
                    self.requests.popleft()
        
        self.requests.append(time.time())

# Usage:
rate_limiter = RateLimiter(max_requests=500, time_window=60)

async def process_with_rate_limit():
    await rate_limiter.acquire()
    # Make API call
    response = await client.chat.completions.create(...)
```

## Migration Strategy

### Phase 1: Convert to AsyncOpenAI
1. Replace `OpenAI` with `AsyncOpenAI` in all functions
2. Convert API calls to `await` syntax
3. Test with single batch first

### Phase 2: Add Parallel Processing
1. Implement `asyncio.gather()` for batch processing
2. Add semaphore for rate limiting
3. Test with small datasets

### Phase 3: Optimize
1. Tune `max_concurrent` based on API tier
2. Add retry logic with exponential backoff
3. Monitor performance and adjust

## Expected Performance Improvements

### Before (Sequential):
- **Name Filtering**: 200 words = 4 batches × 4s = **16 seconds**
- **Translation**: 100 words = 10 batches × 2.5s = **25 seconds**
- **Phrasal Verbs**: 100 verbs = 5 batches × 3.5s = **17.5 seconds**
- **Total**: ~58.5 seconds

### After (Parallel, max_concurrent=5):
- **Name Filtering**: 200 words = 4 batches / 4 concurrent = 1 round × 4s = **4 seconds** (4x faster)
- **Translation**: 100 words = 10 batches / 5 concurrent = 2 rounds × 2.5s = **5 seconds** (5x faster)
- **Phrasal Verbs**: 100 verbs = 5 batches / 5 concurrent = 1 round × 3.5s = **3.5 seconds** (5x faster)
- **Total**: ~12.5 seconds (**4.7x faster overall**)

## Code Changes Required

### 1. Update Imports

```python
# telegram_bot.py
from openai import AsyncOpenAI  # Instead of OpenAI
```

### 2. Update Function Signatures

```python
# Before:
async def filter_names_and_fantasy_entities_with_reasons(
    words: List[str], 
    subtitle_text: str, 
    series_name: str, 
    openai_client: OpenAI  # Change to AsyncOpenAI
) -> tuple[Set[str], Dict[str, str]]:

# After:
async def filter_names_and_fantasy_entities_with_reasons(
    words: List[str], 
    subtitle_text: str, 
    series_name: str, 
    openai_client: AsyncOpenAI  # Changed
) -> tuple[Set[str], Dict[str, str]]:
```

### 3. Update API Calls

```python
# Before:
response = openai_client.chat.completions.create(...)

# After:
response = await openai_client.chat.completions.create(...)
```

### 4. Update Client Initialization

```python
# Before:
openai_client = OpenAI(api_key=OPENAI_API_KEY)

# After:
openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
```

## Error Handling

Add retry logic with exponential backoff:

```python
import asyncio
from tenacity import retry, stop_after_attempt, wait_exponential

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10)
)
async def process_batch_with_retry(batch_words, batch_num):
    """Process batch with automatic retry on failure."""
    try:
        response = await openai_client.chat.completions.create(...)
        return process_response(response)
    except Exception as e:
        print(f"Error in batch {batch_num}: {e}, retrying...")
        raise  # Let retry decorator handle it
```

## Testing Recommendations

1. **Start Small**: Test with 2-3 concurrent batches first
2. **Monitor Rate Limits**: Watch for 429 errors
3. **Gradually Increase**: Increase `max_concurrent` until optimal
4. **Measure Performance**: Compare before/after timing
5. **Test Edge Cases**: Empty batches, API failures, etc.

## Additional Optimizations

### 1. Batch Size Tuning
- Larger batches = fewer API calls but slower individual calls
- Smaller batches = more API calls but faster individual calls
- **Optimal**: 20-50 words per batch for name filtering, 10-15 for translation

### 2. Caching
- Cache ChatGPT responses for identical word lists
- Use Redis or in-memory cache for frequently requested series

### 3. Progressive Loading
- Show results as they become available (streaming)
- Update UI incrementally instead of waiting for all batches

### 4. Background Processing
- Process name filtering and translation in background
- Show "processing" status while user can still interact

## Conclusion

Implementing parallel processing for ChatGPT API calls can provide **4-10x speedup** depending on the operation. The recommended approach is:

1. ✅ Use `AsyncOpenAI` for async API calls
2. ✅ Process batches concurrently with `asyncio.gather()`
3. ✅ Use semaphore to respect rate limits
4. ✅ Add retry logic for reliability
5. ✅ Monitor and tune `max_concurrent` based on API tier

This will significantly improve bot responsiveness and user experience.
