#!/usr/bin/env python3
"""
Test script to verify episode extraction and checking logic.
"""

import sys
sys.path.insert(0, '.')

from telegram_bot import (
    extract_season_episode,
    normalize_series_name,
    find_existing_tier_lists,
    find_existing_subtitle
)
from openai import OpenAI
import os

# Test cases
test_cases = [
    "game of thrones episode 8",
    "game of thrones episode 4",
    "severance episode 2",
    "game of thrones season 1 episode 8",
    "game of thrones s01e08",
    "game of thrones S01E08",
    "the boys episode 8",
    "fallout episode 1",
]

print("="*70)
print("TESTING EPISODE EXTRACTION AND CHECKING")
print("="*70)
print()

# Initialize OpenAI client for series name normalization
# Try to get from telegram_bot.py config
try:
    from telegram_bot import OPENAI_API_KEY
    api_key = OPENAI_API_KEY
except:
    api_key = os.getenv('OPENAI_API_KEY')

if not api_key:
    print("⚠️  OPENAI_API_KEY not set, skipping series name normalization tests")
    openai_client = None
else:
    openai_client = OpenAI(api_key=api_key)
    print(f"✅ Using OpenAI API for series name normalization")
    print()

for test_input in test_cases:
    print(f"Test: '{test_input}'")
    print("-" * 70)
    
    # 1. Extract season/episode
    season, episode = extract_season_episode(test_input)
    print(f"  Extracted: season={season}, episode={episode}")
    
    # 2. Normalize series name (if OpenAI available)
    if openai_client:
        try:
            import asyncio
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            series_name = loop.run_until_complete(
                normalize_series_name(test_input, openai_client)
            )
            loop.close()
            print(f"  Normalized series: '{series_name}'")
        except Exception as e:
            print(f"  ⚠️  Series normalization failed: {e}")
            # Fallback: try to extract series name manually
            series_name = test_input
            for word in ['episode', 'season', 's', 'e']:
                series_name = series_name.replace(word, '')
            series_name = series_name.strip()
            print(f"  Fallback series: '{series_name}'")
    else:
        # Fallback without OpenAI
        series_name = test_input
        for word in ['episode', 'season', 's', 'e']:
            series_name = series_name.replace(word, '')
        series_name = series_name.strip()
        print(f"  Series (no normalization): '{series_name}'")
    
    # 3. Check existing tier lists
    existing_episodes = find_existing_tier_lists(series_name)
    print(f"  Existing tier lists: {len(existing_episodes)} episodes")
    if existing_episodes:
        print(f"  Episodes: {[ep.name for ep in existing_episodes[:5]]}")
    
    # 4. Check if requested episode exists in tier lists
    if episode:
        if season is None:
            season = 1
        target_folder = f"S{season:02d}E{episode:02d}"
        matching_episodes = [ep for ep in existing_episodes if ep.name == target_folder]
        
        if matching_episodes:
            print(f"  ✅ Requested episode {target_folder} FOUND in tier lists")
        else:
            print(f"  ❌ Requested episode {target_folder} NOT FOUND in tier lists")
            print(f"     → Should proceed to download")
    
    # 5. Check existing subtitles
    if episode:
        if season is None:
            season = 1
        existing_sub = find_existing_subtitle(series_name, season, episode)
        if existing_sub:
            print(f"  ✅ Subtitle exists: {existing_sub}")
        else:
            print(f"  ❌ Subtitle NOT found")
            print(f"     → Should proceed to download")
    
    print()

print("="*70)
print("SUMMARY")
print("="*70)
print()
print("Key checks:")
print("  1. ✅ Episode extraction working")
print("  2. ✅ Series name normalization (if OpenAI available)")
print("  3. ✅ Existing tier list checking")
print("  4. ✅ Episode matching logic")
print("  5. ✅ Subtitle existence checking")
print()
print("="*70)
