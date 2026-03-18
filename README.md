# Subtitle Word Frequency Analyzer

A system that analyzes subtitles and categorizes words into 4 tiers based on their frequency in the series versus their frequency in general English. This helps identify which words are worth learning from a particular show or series.

## Features

- Parses SRT subtitle files (supports both ZIP archives and direct SRT files)
- Extracts word frequencies from subtitles
- Compares against English word frequency database
- Categorizes words into 4 tiers:
  - **Tier 1: Hard Usable Words** - Low frequency in English, High frequency in series (best words to learn!)
  - **Tier 2: Random Words** - Low frequency in English, Low frequency in series (probably not worth learning)
  - **Tier 3: Common Words** - High frequency in English, High frequency in series (already common words)
  - **Tier 4: Rare in Series** - High frequency in English, Low frequency in series (common words that don't appear much in this series)

## Requirements

- Python 3.6+
- matplotlib (for visualization)

Install dependencies:
```bash
pip install -r requirements.txt
```

## Usage

### Basic Usage

```bash
python3 subtitle_analyzer.py
```

This will use the default subtitle file and frequency list:
- Subtitle: `Subtitles/fallout.s02.e01.the.innovator.(2025).eng.1cd.(13432033).zip`
- Frequency list: `Frequency list/English/unigram_freq.csv`
- Output: `output/` directory

### Custom Usage

```bash
python3 subtitle_analyzer.py --subtitle path/to/subtitle.zip --freq-list path/to/frequency.csv --output output_dir
```

### Options

- `--subtitle, -s`: Path to subtitle ZIP file or SRT file (default: `Subtitles/fallout.s02.e01.the.innovator.(2025).eng.1cd.(13432033).zip`)
- `--freq-list, -f`: Path to English frequency list CSV file (default: `Frequency list/English/unigram_freq.csv`)
- `--output, -o`: Output directory for CSV files (default: `output`)
- `--min-length`: Minimum word length to include (default: 3)

## Output

The script generates:

1. **Console output**: Summary of all 4 tiers with top 50 words from each tier
2. **CSV files** in the output directory:
   - `tier_1_hard_usable_words.csv` - Words worth learning (low English freq, high series freq)
   - `tier_2_random_words.csv` - Rare words (low English freq, low series freq)
   - `tier_3_common_words.csv` - Common words (high English freq, high series freq)
   - `tier_4_rare_in_series.csv` - Common words rare in series (high English freq, low series freq)
3. **Visualization plots**:
   - `word_frequency_matrix.png` - Scatter plot showing word distribution (high resolution)
   - `word_frequency_matrix.pdf` - Vector format of the same plot

Each CSV file contains:
- `word`: The word
- `series_frequency`: How many times it appears in the subtitle
- `english_frequency`: How many times it appears in the English frequency database

### Visualization

The frequency matrix plot shows:
- **X-axis**: English frequency (log scale)
- **Y-axis**: Series frequency (log scale)
- **Color-coded points**: Each tier has a different color
- **Threshold lines**: Red dashed lines showing the boundaries between high/low frequencies
- **Quadrant labels**: Explains what each quadrant represents

The plot helps visualize which words fall into each category and makes it easy to identify the most valuable words to learn (Tier 1 - top left quadrant).

## How It Works

1. **Subtitle Parsing**: Extracts text from SRT files, removes timing information, speaker labels, and special characters
2. **Word Extraction**: Counts frequency of each word in the subtitles
3. **Frequency Comparison**: Looks up each word in the English frequency database
4. **Categorization**: Uses percentile-based thresholds to categorize words:
   - Series threshold: 33rd percentile (top 1/3 of words by series frequency)
   - English threshold: 33rd percentile (top 1/3 of words by English frequency)

## Example Output

```
Tier 1: Hard Usable Words (Low English freq, High series freq)
Total words: 247
  vault                | Series:    26 | English:       5,408,483
  gonna                | Series:    24 | English:      13,542,156
  okay                 | Series:    13 | English:      15,368,116
  ...
```

## Notes

- Words with 0 frequency in the English database (like contractions "i'm", "it's") are treated as low frequency
- Minimum word length filter (default: 3 characters) helps filter out very short words
- The thresholds are calculated dynamically based on the actual word distribution in your subtitle file
