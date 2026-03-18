# Word Translation Guide

This guide explains how to add translations to tier lists using the ChatGPT API.

## Overview

The `translate_words.py` script adds translations to words in the Tier 1 (Hard Usable Words) CSV files. Each word gets:
- **Translation**: The word translated to your target language
- **Example (English)**: A sentence showing how the word is used
- **Example (Translated)**: The example sentence translated

## Usage

### Translate a Single Episode

```bash
python3 translate_words.py --episode-dir tierlist/Fallout/S02E01
```

### Translate a Specific Tier File

```bash
python3 translate_words.py --tier-file tierlist/Fallout/S02E01/tier_1_hard_usable_words.csv
```

### Change Target Language

```bash
python3 translate_words.py --episode-dir tierlist/Fallout/S02E01 --language Spanish
```

### Adjust API Call Delay

```bash
python3 translate_words.py --episode-dir tierlist/Fallout/S02E01 --delay 0.3
```

## Options

- `--episode-dir, -e`: Path to episode directory (translates `tier_1_hard_usable_words.csv`)
- `--tier-file, -f`: Path to specific tier CSV file
- `--api-key`: OpenAI API key (default: configured key)
- `--language, -l`: Target language (default: Russian)
- `--delay`: Delay between API calls in seconds (default: 0.5)

## Output Format

The CSV file will have additional columns:
- `translation`: Translated word
- `example_en`: Example sentence in English
- `example_translated`: Example sentence translated

Example:
```csv
word,series_frequency,english_frequency,translation,example_en,example_translated
vault,30,7241615,свод,The ancient church had a beautiful stone vault.,Старая церковь имела красивый каменный свод.
```

## Notes

- Translations are saved directly to the CSV file
- If translations already exist, you'll be prompted to overwrite
- Rate limiting: Default delay is 0.5 seconds between calls
- API key is configured by default, but can be overridden

## Cost Estimate

For 31 words (typical Tier 1 size):
- ~31 API calls
- Using gpt-4o-mini: ~$0.01-0.02 per episode
- For 5000 episodes: ~$50-100 total

## Integration with Analysis

After running the subtitle analyzer, you can immediately translate:

```bash
# Analyze subtitle
python3 subtitle_analyzer.py --subtitle Subtitles/Fallout.S02E01.srt

# Translate Tier 1 words
python3 translate_words.py --episode-dir tierlist/Fallout/S02E01
```
