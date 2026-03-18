#!/usr/bin/env python3
"""Test script to verify rare words translation functionality."""

import csv
from pathlib import Path
import sys

BASE_DIR = Path(__file__).parent

def test_tier2_file_structure(episode_dir: Path):
    """Test if tier_2 file exists and check its structure."""
    tier_file = episode_dir / "tier_2_random_words.csv"
    
    print(f"\n{'='*60}")
    print(f"Testing: {tier_file}")
    print(f"{'='*60}")
    
    if not tier_file.exists():
        print(f"❌ File does not exist: {tier_file}")
        return False
    
    print(f"✅ File exists: {tier_file}")
    
    # Read and check structure
    with open(tier_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)
    
    print(f"\n📋 File Structure:")
    print(f"  - Fieldnames: {fieldnames}")
    print(f"  - Total rows: {len(rows)}")
    
    # Check for translation columns
    has_translation = 'translation' in fieldnames if fieldnames else False
    has_example_en = 'example_en' in fieldnames if fieldnames else False
    has_example_translated = 'example_translated' in fieldnames if fieldnames else False
    
    print(f"\n📊 Translation Columns:")
    print(f"  - 'translation' column: {'✅' if has_translation else '❌'}")
    print(f"  - 'example_en' column: {'✅' if has_example_en else '❌'}")
    print(f"  - 'example_translated' column: {'✅' if has_example_translated else '❌'}")
    
    if rows:
        first_row = rows[0]
        print(f"\n📝 First Row Sample:")
        print(f"  - Word: {first_row.get('word', 'N/A')}")
        print(f"  - Translation: {first_row.get('translation', 'N/A')}")
        print(f"  - Example EN: {first_row.get('example_en', 'N/A')[:50] if first_row.get('example_en') else 'N/A'}")
        
        # Count rows with translations
        if has_translation:
            translated_count = sum(1 for r in rows if r.get('translation', '').strip() and r.get('translation', '').strip().upper() != 'N/A')
            print(f"\n📈 Translation Status:")
            print(f"  - Words with translations: {translated_count}/{len(rows)}")
            print(f"  - Words without translations: {len(rows) - translated_count}/{len(rows)}")
            
            if translated_count == 0:
                print(f"\n⚠️  WARNING: No translations found in file!")
                print(f"   This file needs to be translated.")
                return False
        else:
            print(f"\n⚠️  WARNING: Translation column does not exist!")
            print(f"   This file needs to be translated.")
            return False
    
    return True

def test_translation_check_logic(episode_dir: Path):
    """Test the translation check logic used in send_rare_hard_words."""
    tier_file = episode_dir / "tier_2_random_words.csv"
    
    print(f"\n{'='*60}")
    print(f"Testing Translation Check Logic")
    print(f"{'='*60}")
    
    if not tier_file.exists():
        print(f"❌ File does not exist")
        return False
    
    needs_translation = False
    try:
        with open(tier_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames
            first_row = next(reader, None)
            if first_row:
                print(f"  - Fieldnames: {fieldnames}")
                print(f"  - First row keys: {list(first_row.keys())}")
                
                # Check if translation column exists in fieldnames and has values
                if fieldnames and 'translation' not in fieldnames:
                    # Column doesn't exist at all - need translation
                    print(f"  - Translation column missing in fieldnames: ✅ Would trigger translation")
                    needs_translation = True
                elif not first_row.get('translation', '').strip() or first_row.get('translation', '').strip().upper() == 'N/A':
                    # Column exists but is empty or N/A - need translation
                    print(f"  - Translation column exists but is empty/N/A: ✅ Would trigger translation")
                    needs_translation = True
                else:
                    print(f"  - Translation exists: ✅ Would NOT trigger translation")
    except Exception as e:
        print(f"  - Error: {e}")
        import traceback
        traceback.print_exc()
        needs_translation = True
    
    print(f"\n  Result: needs_translation = {needs_translation}")
    return needs_translation

def test_episode_info(episode_dir: Path):
    """Test if episode_info.json exists and has necessary info."""
    episode_info_file = episode_dir / "episode_info.json"
    
    print(f"\n{'='*60}")
    print(f"Testing Episode Info")
    print(f"{'='*60}")
    
    if not episode_info_file.exists():
        print(f"❌ Episode info file does not exist: {episode_info_file}")
        return False
    
    print(f"✅ Episode info file exists")
    
    import json
    try:
        with open(episode_info_file, 'r', encoding='utf-8') as f:
            info = json.load(f)
        
        print(f"\n📋 Episode Info:")
        print(f"  - Series: {info.get('series', 'N/A')}")
        print(f"  - Season: {info.get('season', 'N/A')}")
        print(f"  - Episode: {info.get('episode', 'N/A')}")
        
        return True
    except Exception as e:
        print(f"❌ Error reading episode info: {e}")
        return False

def main():
    """Run all tests."""
    print("="*60)
    print("Rare Words Translation Test")
    print("="*60)
    
    # Test with Severance S01E01
    episode_dir = BASE_DIR / "tierlist" / "Severance" / "S01E01"
    
    if not episode_dir.exists():
        print(f"❌ Episode directory does not exist: {episode_dir}")
        sys.exit(1)
    
    print(f"\n📁 Testing episode directory: {episode_dir}")
    
    # Test 1: File structure
    test1_passed = test_tier2_file_structure(episode_dir)
    
    # Test 2: Translation check logic
    test2_passed = test_translation_check_logic(episode_dir)
    
    # Test 3: Episode info
    test3_passed = test_episode_info(episode_dir)
    
    # Summary
    print(f"\n{'='*60}")
    print("Test Summary")
    print(f"{'='*60}")
    print(f"  File Structure Test: {'✅ PASSED' if test1_passed else '❌ FAILED'}")
    # test2_passed means translation is needed (needs_translation = True)
    # If translations exist, test2_passed will be False, which is correct
    if test1_passed:
        # File has translations, so test2 should show translation NOT needed
        print(f"  Translation Check Logic: {'✅ PASSED (translations exist, no translation needed)' if not test2_passed else '⚠️  WARNING (would trigger translation)'}")
    else:
        print(f"  Translation Check Logic: {'✅ PASSED (would trigger translation)' if test2_passed else '❌ FAILED'}")
    print(f"  Episode Info Test: {'✅ PASSED' if test3_passed else '❌ FAILED'}")
    
    if not test1_passed:
        print(f"\n⚠️  ACTION REQUIRED: Tier 2 file needs translation!")
        print(f"   Run: python3 translate_words.py --episode-dir tierlist/Severance/S01E01 --overwrite")
    else:
        print(f"\n✅ All tests passed! File is properly translated and ready to use.")
    
    return test1_passed and test3_passed

if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)
