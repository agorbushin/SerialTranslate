# Subtitle Downloader

A separate module for downloading subtitles from the OpenSubtitles API.

## Setup

1. **Get OpenSubtitles API Key** (optional but recommended):
   - Visit https://www.opensubtitles.com/
   - Create an account
   - Get your API key from the developer section

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

## Usage

### Basic Usage

```bash
python3 download_subtitles.py "Fallout Season 2 Episode 1"
```

### With API Key (Recommended)

```bash
python3 download_subtitles.py "Fallout" --api-key YOUR_API_KEY --season 2 --episode 1
```

### With Authentication

```bash
python3 download_subtitles.py "Movie Name" --username YOUR_USERNAME --password YOUR_PASSWORD
```

### With IMDB ID (Most Precise)

```bash
python3 download_subtitles.py "Fallout" --imdb-id tt12692526 --season 2 --episode 1
```

### Options

- `query`: Movie/show name to search for (required)
- `--output, -o`: Output directory (default: `Subtitles/`)
- `--api-key`: OpenSubtitles API key (optional, but recommended)
- `--username`: OpenSubtitles username (optional, for authenticated access)
- `--password`: OpenSubtitles password (optional, for authenticated access)
- `--imdb-id`: IMDB ID for more precise search
- `--season`: Season number (for TV shows)
- `--episode`: Episode number (for TV shows)
- `--language`: Language code (default: `en`)

## Examples

```bash
# Download English subtitles for a movie
python3 download_subtitles.py "The Matrix" --output Subtitles/

# Download specific TV episode
python3 download_subtitles.py "Game of Thrones" --season 1 --episode 1

# Download with API key for better rate limits
python3 download_subtitles.py "Breaking Bad" --api-key YOUR_KEY --season 5 --episode 16
```

## Integration with Subtitle Analyzer

After downloading, you can analyze the subtitle:

```bash
# Download subtitle
python3 download_subtitles.py "Fallout" --season 2 --episode 1 --output Subtitles/

# Analyze it
python3 subtitle_analyzer.py --subtitle Subtitles/fallout.s02.e01.srt
```

## API Documentation

For more details, see: https://opensubtitles.stoplight.io/docs/opensubtitles-api/e3750fd63a100-getting-started

## Rate Limits

- Without API key: Limited requests
- With API key: Higher rate limits
- With authentication: Best rate limits

## Notes

- The downloader automatically selects the most popular subtitle (by download count)
- Downloaded files are saved in the specified output directory
- Files are typically in SRT or ZIP format
