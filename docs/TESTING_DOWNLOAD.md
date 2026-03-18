# Testing Subtitle Download

## What You Need to Test

### Minimum Required Information

**Only one thing is required:**
- **Query string**: The name of the movie or TV show (e.g., "Fallout", "The Matrix", "Game of Thrones")

### Optional Information (for better results)

1. **For TV Shows**:
   - `--season`: Season number (e.g., `--season 2`)
   - `--episode`: Episode number (e.g., `--episode 1`)

2. **For More Precise Matching**:
   - `--imdb-id`: IMDB ID (e.g., `tt12692526` for Fallout)
   - Find IMDB ID at: https://www.imdb.com/

3. **For Different Languages**:
   - `--language`: Language code (default: `en`)
   - Examples: `en`, `es`, `fr`, `de`, `ru`

4. **Output Location**:
   - `--output` or `-o`: Directory to save subtitle (default: `Subtitles/`)

## Test Examples

### Basic Test (Just Movie/Show Name)
```bash
python3 download_subtitles.py "The Matrix"
```
✅ **Works!** This is the minimum needed.

### TV Show with Season/Episode
```bash
python3 download_subtitles.py "Fallout" --season 2 --episode 1
```

### With IMDB ID (Most Precise)
```bash
python3 download_subtitles.py "Fallout" --imdb-id tt12692526 --season 2 --episode 1
```

### Different Language
```bash
python3 download_subtitles.py "The Matrix" --language es
```

## What Happens

1. **Search**: The API searches for subtitles matching your query
2. **Select Best Match**: Automatically picks the most popular subtitle (by download count)
3. **Download**: Downloads the subtitle file (usually SRT format)
4. **Save**: Saves to the output directory

## Current Status

✅ **API Key**: Already configured (`8FcGUu17mWuXoaqMxKQisSvjXhvjZdct`)
✅ **Tested**: Successfully downloaded a test subtitle
✅ **Ready to Use**: No additional setup needed

## What Gets Downloaded

- File format: Usually `.srt` (SubRip) or `.zip` (if multiple files)
- File location: `Subtitles/` directory (or your specified `--output` directory)
- File naming: Based on the subtitle file name from OpenSubtitles

## Next Steps After Download

After downloading, you can immediately analyze it:

```bash
# Download
python3 download_subtitles.py "Fallout" --season 2 --episode 1

# Analyze
python3 subtitle_analyzer.py --subtitle Subtitles/downloaded_file.srt
```

## Troubleshooting

If download fails, check:
1. **Internet connection**: API requires internet access
2. **API key**: Already configured, but can be overridden with `--api-key`
3. **Query accuracy**: Try more specific queries or use IMDB ID
4. **Rate limits**: If too many requests, wait a few seconds

## No Additional Information Needed!

The downloader is ready to use with just a movie/show name. All other parameters are optional for better precision.
