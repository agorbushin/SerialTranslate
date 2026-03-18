#!/usr/bin/env python3
"""
Test script to verify name filtering works generally across different series.
Tests the zero-frequency check and post-translation filter logic.
"""

import csv
from pathlib import Path
from collections import Counter

def analyze_tier_file(tier_file: Path) -> dict:
    """Analyze a tier file to check name filtering."""
    results = {
        'total_words': 0,
        'zero_freq_words': [],
        'failed_translations': [],
        'names_tagged': [],
        'names_missed': [],
        'normal_words_with_zero_freq': []
    }
    
    if not tier_file.exists():
        return results
    
    with open(tier_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            results['total_words'] += 1
            word = row.get('word', '')
            english_freq = int(row.get('english_frequency', 0) or 0)
            is_name_tag = row.get('is_name_or_fantasy', '').strip().lower()
            translation = row.get('translation', '').strip()
            
            # Check zero frequency
            if english_freq == 0:
                results['zero_freq_words'].append(word)
                if 'normal word' in is_name_tag:
                    results['normal_words_with_zero_freq'].append(word)
                elif 'name/fantasy entity' in is_name_tag:
                    results['names_tagged'].append(word)
            
            # Check failed translations
            if translation == '[Translation failed]':
                results['failed_translations'].append(word)
                if 'normal word' in is_name_tag:
                    results['names_missed'].append(word)
    
    return results

def test_series(series_name: str, episode_dir: Path):
    """Test name filtering for a series."""
    tier_file = episode_dir / "tier_1_hard_usable_words.csv"
    
    if not tier_file.exists():
        print(f"  ⚠️  Tier file not found: {tier_file}")
        return None
    
    print(f"\n{'='*60}")
    print(f"Testing: {series_name}")
    print(f"Episode: {episode_dir.name}")
    print(f"{'='*60}")
    
    results = analyze_tier_file(tier_file)
    
    print(f"Total words: {results['total_words']}")
    print(f"Zero frequency words: {len(results['zero_freq_words'])}")
    print(f"Failed translations: {len(results['failed_translations'])}")
    print(f"Names tagged correctly: {len(results['names_tagged'])}")
    print(f"Names missed (zero freq but tagged as normal): {len(results['normal_words_with_zero_freq'])}")
    print(f"Names missed (failed translation but tagged as normal): {len(results['names_missed'])}")
    
    if results['normal_words_with_zero_freq']:
        print(f"\n⚠️  Zero frequency words tagged as 'normal word' (should be names):")
        for word in results['normal_words_with_zero_freq'][:10]:
            print(f"    - {word}")
    
    if results['names_missed']:
        print(f"\n⚠️  Failed translations tagged as 'normal word' (should be names):")
        for word in results['names_missed'][:10]:
            print(f"    - {word}")
    
    if results['names_tagged']:
        print(f"\n✓ Names correctly tagged (zero frequency):")
        for word in results['names_tagged'][:10]:
            print(f"    - {word}")
    
    return results

def main():
    """Test name filtering across multiple series."""
    base_dir = Path(__file__).parent / "tierlist"
    
    test_cases = [
        ("Severance", base_dir / "Severance" / "S01E01"),
        ("Fallout", base_dir / "Fallout" / "S01E01"),
        ("Better Call Saul", base_dir / "Better Call Saul" / "S01E01"),
        ("Game of Thrones", base_dir / "Game of Thrones" / "S01E06"),
    ]
    
    print("="*60)
    print("Testing Name Filtering Across Multiple Series")
    print("="*60)
    print("\nThis test verifies:")
    print("1. Zero frequency words are flagged as names")
    print("2. Failed translations tagged as 'normal word' are caught")
    print("3. General applicability (not series-specific)")
    
    all_results = {}
    for series_name, episode_dir in test_cases:
        if episode_dir.exists():
            results = test_series(series_name, episode_dir)
            if results:
                all_results[series_name] = results
        else:
            print(f"\n⚠️  Episode directory not found: {episode_dir}")
    
    # Summary
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    
    total_zero_freq_missed = sum(len(r['normal_words_with_zero_freq']) for r in all_results.values())
    total_failed_missed = sum(len(r['names_missed']) for r in all_results.values())
    
    print(f"\nTotal series tested: {len(all_results)}")
    print(f"Zero frequency words missed (tagged as normal): {total_zero_freq_missed}")
    print(f"Failed translations missed (tagged as normal): {total_failed_missed}")
    
    if total_zero_freq_missed == 0 and total_failed_missed == 0:
        print("\n✅ All name filtering checks passed!")
    else:
        print(f"\n⚠️  Some names may need better filtering")
        print(f"   (Note: API quota issues may cause all translations to fail)")
        print(f"   (Note: Existing tier lists were created before fixes were applied)")

if __name__ == "__main__":
    main()
