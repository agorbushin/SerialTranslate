#!/usr/bin/env python3
"""
Clean up wrong subtitles from Subtitles directory.
Removes subtitles that don't match their folder's series name.
"""

import re
from pathlib import Path
from subtitle_analyzer import extract_series_info

def normalize_series_name(name: str) -> str:
    """Normalize series name for comparison."""
    name = name.lower()
    # Remove common words
    name = re.sub(r'\b(the|a|an)\b', '', name)
    # Remove special chars
    name = re.sub(r'[^a-z0-9\s]', '', name)
    # Normalize whitespace
    name = ' '.join(name.split())
    return name

def validate_subtitle_matches_series(subtitle_path: Path, expected_series: str) -> bool:
    """Validate that a subtitle file matches the expected series name."""
    try:
        extracted_info = extract_series_info(subtitle_path)
        extracted_series = extracted_info.get("series", "").lower()
        expected_series_lower = expected_series.lower()
        
        extracted_norm = normalize_series_name(extracted_series)
        expected_norm = normalize_series_name(expected_series_lower)
        
        # Check if they match (at least 60% word overlap)
        extracted_words = set(extracted_norm.split())
        expected_words = set(expected_norm.split())
        
        if not extracted_words or not expected_words:
            return False
        
        overlap = len(extracted_words & expected_words)
        match_ratio = overlap / max(len(extracted_words), len(expected_words))
        
        return match_ratio >= 0.6
    except Exception as e:
        print(f"Warning: Could not validate {subtitle_path.name}: {e}")
        return True  # Default to True if validation fails (don't delete)

def cleanup_wrong_subtitles(subtitles_dir: Path):
    """Remove subtitles that don't match their folder's series name."""
    if not subtitles_dir.exists():
        print(f"Subtitles directory not found: {subtitles_dir}")
        return
    
    removed_count = 0
    checked_count = 0
    
    print("="*70)
    print("CLEANING UP WRONG SUBTITLES")
    print("="*70)
    print()
    
    # Go through each series folder
    for series_dir in sorted(subtitles_dir.iterdir()):
        if not series_dir.is_dir():
            continue
        
        series_name = series_dir.name
        print(f"Checking: {series_name}/")
        
        # Find all subtitle files recursively
        for subtitle_file in series_dir.rglob("*"):
            if not subtitle_file.is_file():
                continue
            
            if subtitle_file.suffix not in ['.srt', '.zip']:
                continue
            
            checked_count += 1
            relative_path = subtitle_file.relative_to(subtitles_dir)
            
            # Validate subtitle matches folder name
            if not validate_subtitle_matches_series(subtitle_file, series_name):
                try:
                    extracted_info = extract_series_info(subtitle_file)
                    extracted_series = extracted_info.get("series", "Unknown")
                    
                    print(f"  ❌ MISMATCH: {relative_path}")
                    print(f"     Expected: '{series_name}'")
                    print(f"     Found: '{extracted_series}'")
                    
                    # Remove the file
                    subtitle_file.unlink()
                    removed_count += 1
                    print(f"     ✅ Removed")
                except Exception as e:
                    print(f"     ⚠️  Error removing {subtitle_file.name}: {e}")
            else:
                # Valid match
                print(f"  ✅ OK: {subtitle_file.name}")
    
    print()
    print("="*70)
    print(f"SUMMARY:")
    print(f"  Checked: {checked_count} subtitle files")
    print(f"  Removed: {removed_count} mismatched files")
    print("="*70)

if __name__ == "__main__":
    base_dir = Path(__file__).parent
    subtitles_dir = base_dir / "Subtitles"
    
    cleanup_wrong_subtitles(subtitles_dir)
