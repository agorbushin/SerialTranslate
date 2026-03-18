#!/usr/bin/env python3
"""
Test translation functionality to identify N/A issue.
"""

import csv
import json
import tempfile
from pathlib import Path
from openai import OpenAI
import os
from translate_words import translate_tier_file, translate_words_with_context

def create_test_tier_file() -> Path:
    """Create a test tier CSV file."""
    temp_dir = Path(tempfile.mkdtemp())
    tier_file = temp_dir / "tier_1_hard_usable_words.csv"
    
    # Create test CSV with sample words
    words_data = [
        {
            'word': 'example',
            'frequency': '5',
            'english_frequency': '1000000',
            'vocabulary_level': 'B1',
            'translation': '',  # Empty - should be translated
            'example_en': '',
            'example_translated': ''
        },
        {
            'word': 'test',
            'frequency': '3',
            'english_frequency': '2000000',
            'vocabulary_level': 'A2',
            'translation': '',  # Empty - should be translated
            'example_en': '',
            'example_translated': ''
        },
        {
            'word': 'sample',
            'frequency': '2',
            'english_frequency': '500000',
            'vocabulary_level': 'B2',
            'translation': '',  # Empty - should be translated
            'example_en': '',
            'example_translated': ''
        }
    ]
    
    fieldnames = ['word', 'frequency', 'english_frequency', 'vocabulary_level', 
                  'translation', 'example_en', 'example_translated']
    
    with open(tier_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(words_data)
    
    return tier_file, temp_dir

def create_test_subtitle() -> Path:
    """Create a test subtitle file."""
    temp_dir = Path(tempfile.mkdtemp())
    subtitle_file = temp_dir / "test.srt"
    
    subtitle_content = """1
00:00:01,000 --> 00:00:03,000
This is an example sentence.

2
00:00:04,000 --> 00:00:06,000
Let's test this functionality.

3
00:00:07,000 --> 00:00:09,000
Here is a sample phrase.
"""
    
    with open(subtitle_file, 'w', encoding='utf-8') as f:
        f.write(subtitle_content)
    
    return subtitle_file

def test_translation_response_parsing():
    """Test how translation responses are parsed."""
    print("="*70)
    print("TEST 1: Translation Response Parsing")
    print("="*70)
    
    # Simulate a ChatGPT response that might have issues
    test_responses = [
        # Case 1: Normal response
        {
            "example": {
                "translation": "пример",
                "example_en": "This is an example",
                "example_translated": "Это пример"
            }
        },
        # Case 2: Response with "N/A"
        {
            "test": {
                "translation": "N/A",
                "example_en": "N/A",
                "example_translated": "N/A"
            }
        },
        # Case 3: Response with empty translation
        {
            "sample": {
                "translation": "",
                "example_en": "Here is a sample",
                "example_translated": ""
            }
        },
        # Case 4: Response with different case key
        {
            "Example": {  # Different case
                "translation": "пример",
                "example_en": "This is an example",
                "example_translated": "Это пример"
            }
        }
    ]
    
    words = ["example", "test", "sample"]
    
    for i, response in enumerate(test_responses, 1):
        print(f"\nTest Case {i}:")
        print(f"Response: {json.dumps(response, indent=2, ensure_ascii=False)}")
        
        for word in words:
            # Try exact match
            if word in response:
                trans_data = response[word]
                translation = trans_data.get('translation', '').strip()
                print(f"  '{word}' (exact match): translation = '{translation}'")
            else:
                # Try case-insensitive match
                found = False
                for key in response.keys():
                    if key.lower() == word.lower():
                        trans_data = response[key]
                        translation = trans_data.get('translation', '').strip()
                        print(f"  '{word}' (case-insensitive match with '{key}'): translation = '{translation}'")
                        found = True
                        break
                
                if not found:
                    print(f"  '{word}': NOT FOUND in response")
            
            # Check if translation is valid
            if word in response or any(k.lower() == word.lower() for k in response.keys()):
                key = word if word in response else next(k for k in response.keys() if k.lower() == word.lower())
                trans_data = response[key]
                translation = trans_data.get('translation', '').strip()
                
                if not translation or translation.upper() == 'N/A':
                    print(f"    ⚠️  INVALID TRANSLATION: '{translation}'")
                else:
                    print(f"    ✅ Valid translation: '{translation}'")

def test_actual_translation():
    """Test actual translation with OpenAI API."""
    print("\n" + "="*70)
    print("TEST 2: Actual Translation Test")
    print("="*70)
    
    api_key = os.getenv('OPENAI_API_KEY')
    if not api_key:
        print("⚠️  OPENAI_API_KEY not set. Skipping actual translation test.")
        return
    
    tier_file, tier_dir = create_test_tier_file()
    subtitle_file = create_test_subtitle()
    
    print(f"\nCreated test tier file: {tier_file}")
    print(f"Created test subtitle file: {subtitle_file}")
    
    # Test translation
    print("\nRunning translation...")
    try:
        success = translate_tier_file(
            tier_file=tier_file,
            subtitle_path=subtitle_file,
            api_key=api_key,
            target_language="Russian",
            overwrite=True
        )
        
        if success:
            print("✅ Translation completed successfully")
            
            # Check results
            print("\nChecking translation results...")
            with open(tier_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    word = row['word']
                    translation = row.get('translation', '').strip()
                    
                    if not translation or translation.upper() == 'N/A':
                        print(f"  ❌ '{word}': INVALID translation = '{translation}'")
                    else:
                        print(f"  ✅ '{word}': translation = '{translation}'")
        else:
            print("❌ Translation failed")
            
    except Exception as e:
        print(f"❌ Error during translation: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Cleanup
        import shutil
        shutil.rmtree(tier_dir.parent, ignore_errors=True)

if __name__ == "__main__":
    test_translation_response_parsing()
    test_actual_translation()
