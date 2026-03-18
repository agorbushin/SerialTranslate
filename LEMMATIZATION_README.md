# Lemmatization Module

## Overview

The lemmatization module (`lemmatizer.py`) provides advanced word normalization using spaCy. It can be easily enabled/disabled or modified.

## Features

- **Separate Module**: Completely isolated in `lemmatizer.py`
- **Easy to Disable**: Set `USE_LEMMATIZATION = False` to revert to simple singularization
- **Automatic Fallback**: Falls back to `to_singular()` if spaCy is not available
- **Configurable**: Change spaCy model or lemmatization logic easily

## Installation

1. Install spaCy:
```bash
pip install spacy
```

2. Download the English model:
```bash
python -m spacy download en_core_web_sm
```

## Configuration

### Enable/Disable Lemmatization

Edit `lemmatizer.py`:
```python
USE_LEMMATIZATION = True   # Enable lemmatization
USE_LEMMATIZATION = False  # Disable (use simple singularization)
```

### Change spaCy Model

Edit `lemmatizer.py`:
```python
SPACY_MODEL = 'en_core_web_sm'  # Lightweight (recommended)
SPACY_MODEL = 'en_core_web_md'  # Medium (more accurate, slower)
SPACY_MODEL = 'en_core_web_lg'  # Large (most accurate, slowest)
```

## How It Works

1. **When Enabled**: Uses spaCy to convert words to their base form (lemma)
   - "thinking" → "think"
   - "thought" → "think"
   - "thinks" → "think"
   - "cities" → "city"
   - "went" → "go"

2. **When Disabled**: Falls back to simple singularization (`to_singular()`)
   - "thinking" → "thinking" (no change)
   - "cities" → "city"
   - "boxes" → "box"

3. **If spaCy Not Available**: Automatically falls back to simple singularization

## Integration Points

The lemmatization is integrated into:

1. **`parse_srt_file()`** - Word extraction from subtitles
2. **`load_english_frequencies()`** - Frequency list grouping
3. **`load_filter_from_csv()`** - Filter word normalization

## Reverting to Previous Version

To completely remove lemmatization:

1. Set `USE_LEMMATIZATION = False` in `lemmatizer.py`
   OR
2. Remove the `lemmatizer.py` file (code will automatically fall back)

The code will automatically use `to_singular()` if lemmatization is disabled or unavailable.

## Testing

Test the lemmatization module:
```bash
python3 lemmatizer.py
```

This will show:
- Whether lemmatization is enabled
- Whether spaCy is available
- Example lemmatizations

## Benefits

- **Better Word Grouping**: Groups word variations (thinking/thought/thinks → think)
- **More Accurate Frequencies**: Combines counts for all word forms
- **Cleaner Word Lists**: Shows base forms instead of variations

## Performance

- **With spaCy**: Slightly slower but more accurate
- **Without spaCy**: Fast, uses simple rules
- **Batch Processing**: Processes words in batches for efficiency
