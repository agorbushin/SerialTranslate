#!/usr/bin/env python3
"""
Test script to verify tier list filtering logic works correctly on multiple series.

This script tests the filtering logic from telegram_bot.py to ensure:
1. Words are not incorrectly filtered out
2. Results are reasonable (> 0 words for each episode)
3. Filtering works consistently across different series
"""

import csv
from pathlib import Path
from typing import List, Dict

# Test episodes
TEST_EPISODES = [
    "tierlist/Game of Thrones/S01E06/tier_1_hard_usable_words.csv",
    "tierlist/Game of Thrones/S01E01/tier_1_hard_usable_words.csv",
    "tierlist/Severance/S02E02/tier_1_hard_usable_words.csv",
    "tierlist/Fallout/S02E01/tier_1_hard_usable_words.csv",
]


def apply_filtering_logic(words_data: List[Dict]) -> tuple[List[Dict], Dict[str, int]]:
    """
    Apply the same filtering logic as send_tier_list_results() in telegram_bot.py
    
    Returns:
        (filtered_words, stats) where stats contains counts of filtered words
    """
    stats = {
        'original_count': len(words_data),
        'name_filtered': 0,
        'vocab_filtered': 0,
        'final_count': 0
    }
    
    # Define vocabulary levels that bypass name/fantasy entity filtering
    bypass_levels = {'B1', 'B2', 'C1', 'C2'}
    
    # Filter out names and fantasy entities
    original_count = len(words_data)
    words_data = [
        row for row in words_data 
        if not row.get('is_name_or_fantasy', '').strip() or 
           'normal word' in row.get('is_name_or_fantasy', '').lower() or
           row.get('vocabulary_level', 'N/A').upper() in bypass_levels
    ]
    stats['name_filtered'] = original_count - len(words_data)
    
    # Filter by vocabulary level (Advanced: B2, C1, C2, N/A)
    original_vocab_count = len(words_data)
    allowed_levels = {'B2', 'C1', 'C2', 'N/A', ''}
    words_data = [row for row in words_data if row.get('vocabulary_level', 'N/A').upper() in allowed_levels]
    stats['vocab_filtered'] = original_vocab_count - len(words_data)
    
    # Fallback logic if no words remain
    if not words_data:
        print(f"    ⚠️  All words filtered out, applying fallback logic...")
        # Note: In real code, we'd reload from file, but here we use the original data
        # For testing, we'll just note that fallback would be needed
        pass
    
    stats['final_count'] = len(words_data)
    return words_data, stats


def test_episode(tier_file_path: Path) -> Dict:
    """Test filtering on a single episode tier list."""
    print(f"\n{'='*60}")
    print(f"Testing: {tier_file_path}")
    print(f"{'='*60}")
    
    if not tier_file_path.exists():
        return {
            'file': str(tier_file_path),
            'exists': False,
            'error': 'File not found'
        }
    
    # Load tier list
    words_data = []
    try:
        with open(tier_file_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            words_data = [row for row in reader]
    except Exception as e:
        return {
            'file': str(tier_file_path),
            'exists': True,
            'error': f'Error reading file: {e}'
        }
    
    if not words_data:
        return {
            'file': str(tier_file_path),
            'exists': True,
            'original_count': 0,
            'final_count': 0,
            'error': 'File is empty'
        }
    
    # Analyze original data
    print(f"Original word count: {len(words_data)}")
    
    # Count by is_name_or_fantasy tags
    name_tags = {}
    vocab_levels = {}
    for row in words_data:
        tag = row.get('is_name_or_fantasy', '').strip() or 'empty'
        name_tags[tag] = name_tags.get(tag, 0) + 1
        
        vocab = row.get('vocabulary_level', 'N/A').upper()
        vocab_levels[vocab] = vocab_levels.get(vocab, 0) + 1
    
    print(f"\nTags breakdown:")
    for tag, count in sorted(name_tags.items(), key=lambda x: -x[1])[:5]:
        tag_short = tag[:50] + "..." if len(tag) > 50 else tag
        print(f"  {tag_short}: {count}")
    
    print(f"\nVocabulary levels:")
    for level, count in sorted(vocab_levels.items()):
        print(f"  {level}: {count}")
    
    # Apply filtering
    filtered_words, stats = apply_filtering_logic(words_data)
    
    print(f"\nFiltering results:")
    print(f"  Original: {stats['original_count']}")
    print(f"  Filtered by name/fantasy: {stats['name_filtered']}")
    print(f"  Filtered by vocabulary level: {stats['vocab_filtered']}")
    print(f"  Final count: {stats['final_count']}")
    
    # Show sample of filtered words
    if filtered_words:
        print(f"\nSample of filtered words (first 5):")
        for i, word_data in enumerate(filtered_words[:5], 1):
            word = word_data.get('word', 'N/A')
            vocab = word_data.get('vocabulary_level', 'N/A')
            tag = word_data.get('is_name_or_fantasy', '').strip()[:40] or 'empty'
            print(f"  {i}. {word} (vocab: {vocab}, tag: {tag})")
    
    return {
        'file': str(tier_file_path),
        'exists': True,
        'original_count': stats['original_count'],
        'name_filtered': stats['name_filtered'],
        'vocab_filtered': stats['vocab_filtered'],
        'final_count': stats['final_count'],
        'success': stats['final_count'] > 0
    }


def main():
    """Run tests on all episodes."""
    print("="*60)
    print("Tier List Filtering Test")
    print("="*60)
    
    base_dir = Path(__file__).parent
    results = []
    
    for episode_path in TEST_EPISODES:
        full_path = base_dir / episode_path
        result = test_episode(full_path)
        results.append(result)
    
    # Summary
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    
    print(f"\n{'Episode':<50} {'Original':<10} {'Final':<10} {'Status':<10}")
    print("-" * 80)
    
    all_passed = True
    for result in results:
        if not result.get('exists', False):
            status = "❌ NOT FOUND"
            all_passed = False
        elif result.get('error'):
            status = f"❌ ERROR"
            all_passed = False
        elif result.get('final_count', 0) == 0:
            status = "❌ 0 WORDS"
            all_passed = False
        else:
            status = "✅ PASS"
        
        episode_name = Path(result['file']).parent.name
        original = result.get('original_count', 0)
        final = result.get('final_count', 0)
        
        print(f"{episode_name:<50} {original:<10} {final:<10} {status:<10}")
    
    print(f"\n{'='*60}")
    if all_passed:
        print("✅ All tests passed!")
    else:
        print("❌ Some tests failed - check output above")
    print(f"{'='*60}\n")
    
    return 0 if all_passed else 1


if __name__ == '__main__':
    exit(main())
