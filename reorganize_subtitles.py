#!/usr/bin/env python3
"""
Reorganize subtitles from flat structure to SeriesName/Season/Episode structure.
"""

import re
from pathlib import Path
from typing import Optional, Tuple


def extract_series_info_from_filename(filename: str) -> Tuple[Optional[str], Optional[int], Optional[int]]:
    """Extract series name, season, and episode from subtitle filename.
    
    Args:
        filename: Subtitle filename
        
    Returns:
        Tuple of (series_name, season, episode)
    """
    # Remove extension
    name = Path(filename).stem
    
    # Try to extract season and episode
    # Patterns: S01E01, S1E1, Season 1 Episode 1, etc.
    season = None
    episode = None
    
    # Try S##E## or S#E# pattern
    match = re.search(r'[Ss](\d+)[Ee](\d+)', name)
    if match:
        season = int(match.group(1))
        episode = int(match.group(2))
    else:
        # Try Season X Episode Y
        match = re.search(r'[Ss]eason\s*(\d+).*?[Ee]pisode\s*(\d+)', name, re.IGNORECASE)
        if match:
            season = int(match.group(1))
            episode = int(match.group(2))
    
    # Extract series name - remove common patterns
    series_name = name
    
    # Remove year patterns (e.g., 2024, (2024))
    series_name = re.sub(r'\s*\(\d{4}\)', '', series_name)
    series_name = re.sub(r'\.\d{4}\.', '.', series_name)
    
    # Remove season/episode patterns
    series_name = re.sub(r'[Ss]\d+[Ee]\d+', '', series_name)
    series_name = re.sub(r'[Ss]eason\s*\d+', '', series_name, flags=re.IGNORECASE)
    series_name = re.sub(r'[Ee]pisode\s*\d+', '', series_name, flags=re.IGNORECASE)
    
    # Remove quality/resolution patterns
    series_name = re.sub(r'\d+p', '', series_name, flags=re.IGNORECASE)
    series_name = re.sub(r'WEB[- ]?DL', '', series_name, flags=re.IGNORECASE)
    series_name = re.sub(r'HDTV', '', series_name, flags=re.IGNORECASE)
    series_name = re.sub(r'BluRay', '', series_name, flags=re.IGNORECASE)
    series_name = re.sub(r'DVDrip', '', series_name, flags=re.IGNORECASE)
    series_name = re.sub(r'AMZN', '', series_name, flags=re.IGNORECASE)
    series_name = re.sub(r'x264', '', series_name, flags=re.IGNORECASE)
    series_name = re.sub(r'H\.?264', '', series_name, flags=re.IGNORECASE)
    series_name = re.sub(r'DDP?5\.?1', '', series_name, flags=re.IGNORECASE)
    series_name = re.sub(r'Atmos', '', series_name, flags=re.IGNORECASE)
    
    # Remove release group patterns (usually at the end, uppercase)
    series_name = re.sub(r'-[A-Z0-9-]+$', '', series_name)
    series_name = re.sub(r'\([A-Z0-9-]+\)$', '', series_name)
    
    # Clean up: remove multiple dots/spaces, trim
    series_name = re.sub(r'\.+', '.', series_name)
    series_name = re.sub(r'\s+', ' ', series_name)
    series_name = series_name.strip(' .-_')
    
    # Remove common prefixes/suffixes
    series_name = re.sub(r'^The\.', 'The ', series_name)
    series_name = re.sub(r'^Game\.of\.', 'Game of ', series_name, flags=re.IGNORECASE)
    
    # Title case
    series_name = series_name.replace('.', ' ').replace('_', ' ')
    series_name = ' '.join(word.capitalize() for word in series_name.split())
    
    # Special cases
    if 'Game of Thrones' in series_name or 'game.of.thrones' in name.lower():
        series_name = 'Game of Thrones'
    elif 'The Boys' in series_name or 'the.boys' in name.lower():
        series_name = 'The Boys'
    elif 'Fallout' in series_name or 'fallout' in name.lower():
        series_name = 'Fallout'
    elif 'Friends' in series_name or 'friends' in name.lower():
        series_name = 'Friends'
    
    return series_name if series_name else None, season, episode


def reorganize_subtitles(subtitles_dir: Path):
    """Reorganize subtitles into SeriesName/Season/Episode structure.
    
    Args:
        subtitles_dir: Path to Subtitles directory
    """
    if not subtitles_dir.exists():
        print(f"Subtitles directory not found: {subtitles_dir}")
        return
    
    # Find all subtitle files (not directories)
    subtitle_files = [f for f in subtitles_dir.iterdir() if f.is_file() and (f.suffix == '.srt' or f.suffix == '.zip')]
    
    moved_count = 0
    skipped_count = 0
    
    for subtitle_file in subtitle_files:
        series_name, season, episode = extract_series_info_from_filename(subtitle_file.name)
        
        if not series_name:
            print(f"⚠️  Could not extract series name from: {subtitle_file.name}")
            skipped_count += 1
            continue
        
        if not season or not episode:
            print(f"⚠️  Could not extract season/episode from: {subtitle_file.name}")
            # Still move it, but to a generic location
            season = 1
            episode = 1
            print(f"   Using default: Season {season}, Episode {episode}")
        
        # Create new directory structure
        new_dir = subtitles_dir / series_name / f"Season {season}" / f"Episode {episode:02d}"
        new_dir.mkdir(parents=True, exist_ok=True)
        
        # Move file
        new_path = new_dir / subtitle_file.name
        
        if new_path.exists():
            print(f"⏭️  Already exists: {new_path}")
            skipped_count += 1
        else:
            subtitle_file.rename(new_path)
            print(f"✅ Moved: {subtitle_file.name} → {new_path}")
            moved_count += 1
    
    print()
    print("="*70)
    print(f"Reorganization complete!")
    print(f"  Moved: {moved_count} files")
    print(f"  Skipped: {skipped_count} files")
    print("="*70)


if __name__ == '__main__':
    import sys
    base_dir = Path(__file__).parent
    subtitles_dir = base_dir / "Subtitles"
    
    if len(sys.argv) > 1:
        subtitles_dir = Path(sys.argv[1])
    
    reorganize_subtitles(subtitles_dir)
