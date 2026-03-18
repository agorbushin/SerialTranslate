# Word Filters

This directory contains CSV files that define words to be excluded from the subtitle analysis.

## How It Works

The `subtitle_analyzer.py` script automatically loads all CSV files from this directory and combines them into a single exclusion list. Any word found in any of these CSV files will be filtered out from the word lists.

## CSV File Format

Each CSV file should have:
- A header row with at least one column (typically `word`)
- One word per row in the first column
- Words are automatically converted to lowercase

Example:
```csv
word
example1
example2
example3
```

## Current Filters

- **contractions.csv** - Common contractions (e.g., "i'm", "don't", "can't")
- **exclamations.csv** - Common exclamations and interjections (e.g., "ooh", "wow", "hey")
- **names_male.csv** - Common male first names
- **names_female.csv** - Common female first names
- **names_last.csv** - Common last names
- **names_characters.csv** - Character names from the series

## Adding New Filters

To add a new filter:

1. Create a new CSV file in this directory (e.g., `easy_words.csv`)
2. Add a header row with `word` as the first column
3. Add one word per row
4. The filter will be automatically loaded on the next run

Example: `filters/easy_words.csv`
```csv
word
the
and
or
but
```

The script will automatically detect and load this new filter file.

## Notes

- All words are case-insensitive (automatically converted to lowercase)
- Empty rows are ignored
- Duplicate words across different CSV files are automatically deduplicated
- The order of CSV files doesn't matter - all filters are combined
