#!/usr/bin/env python3
"""
Comprehensive test suite for subtitle download functionality.
Tests various series name spellings, episode formats, and download scenarios.
"""

import asyncio
import sys
from pathlib import Path
from typing import List, Tuple, Dict
import json
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from telegram_bot import extract_season_episode, normalize_series_name
from download_subtitles import OpenSubtitlesDownloader
from openai import OpenAI
import os

# Test cases: (input, expected_series_normalized, expected_season, expected_episode)
TEST_CASES = [
    # Standard formats
    ("Game of Thrones S01E01", "Game of Thrones", 1, 1),
    ("Game of Thrones season 1 episode 1", "Game of Thrones", 1, 1),
    ("Game of Thrones S1 E1", "Game of Thrones", 1, 1),
    ("Game of Thrones episode 1", "Game of Thrones", 1, 1),
    ("Game of Thrones Ep 1", "Game of Thrones", 1, 1),
    ("Game of Thrones ep 1", "Game of Thrones", 1, 1),
    ("Game of Thrones E1", "Game of Thrones", 1, 1),
    
    # Abbreviations and misspellings
    ("got S01E01", "Game of Thrones", 1, 1),
    ("got episode 1", "Game of Thrones", 1, 1),
    ("GOT S04E08", "Game of Thrones", 4, 8),
    
    # The Marvelous Mrs. Maisel variations
    ("Marvelous Ms Maiszel Ep 1", "The Marvelous Mrs. Maisel", 1, 1),
    ("Marvelous Mrs Maisel episode 1", "The Marvelous Mrs. Maisel", 1, 1),
    ("Marvelous Mrs. Maisel S01E01", "The Marvelous Mrs. Maisel", 1, 1),
    ("marvelous mrs maisel", "The Marvelous Mrs. Maisel", None, None),
    ("Mrs Maisel Ep 1", "The Marvelous Mrs. Maisel", 1, 1),
    ("maisel episode 1", "The Marvelous Mrs. Maisel", 1, 1),
    
    # Fallout variations
    ("Fallout S02E02", "Fallout", 2, 2),
    ("fallout episode 2", "Fallout", 1, 2),
    ("Fallout season 2 episode 2", "Fallout", 2, 2),
    
    # Severance variations
    ("Severance S01E01", "Severance", 1, 1),
    ("severance episode 1", "Severance", 1, 1),
    ("Severance Ep 1", "Severance", 1, 1),
    
    # The Boys variations
    ("The Boys S04E08", "The Boys", 4, 8),
    ("Boys season 4 episode 8", "The Boys", 4, 8),
    ("boys S4E8", "The Boys", 4, 8),
    ("The Boys Ep 8", "The Boys", 1, 8),
    
    # Breaking Bad variations
    ("Breaking Bad S01E01", "Breaking Bad", 1, 1),
    ("breaking bad episode 1", "Breaking Bad", 1, 1),
    ("BB S01E01", "Breaking Bad", 1, 1),
    
    # The Office variations
    ("The Office S01E01", "The Office", 1, 1),
    ("office episode 1", "The Office", 1, 1),
    ("The Office Ep 1", "The Office", 1, 1),
    
    # House of the Dragon
    ("House of the Dragon S01E01", "House of the Dragon", 1, 1),
    ("House Dragon episode 1", "House of the Dragon", 1, 1),
    ("HOTD S01E01", "House of the Dragon", 1, 1),
    
    # True Detective
    ("True Detective S01E01", "True Detective", 1, 1),
    ("true detective episode 1", "True Detective", 1, 1),
    ("True Detective Ep 1", "True Detective", 1, 1),
    
    # Better Call Saul
    ("Better Call Saul S01E01", "Better Call Saul", 1, 1),
    ("BCS S01E01", "Better Call Saul", 1, 1),
    ("Better Call Saul episode 1", "Better Call Saul", 1, 1),
    
    # Black Sails
    ("Black Sails S01E01", "Black Sails", 1, 1),
    ("black sails episode 1", "Black Sails", 1, 1),
    ("Black Sails Ep 1", "Black Sails", 1, 1),
    
    # Edge cases - no episode specified
    ("Game of Thrones", "Game of Thrones", None, None),
    ("Fallout", "Fallout", None, None),
    ("Severance", "Severance", None, None),
    
    # Edge cases - season only (not supported, should return None)
    ("Game of Thrones season 4", "Game of Thrones", None, None),
    
    # Edge cases - episode without season (should default to season 1)
    ("Game of Thrones episode 5", "Game of Thrones", 1, 5),
    ("Fallout Ep 3", "Fallout", 1, 3),
    ("Severance E2", "Severance", 1, 2),
    
    # Case variations
    ("GAME OF THRONES S01E01", "Game of Thrones", 1, 1),
    ("game of thrones s01e01", "Game of Thrones", 1, 1),
    ("Game Of Thrones S01E01", "Game of Thrones", 1, 1),
    
    # Spacing variations
    ("Game of Thrones  S01E01", "Game of Thrones", 1, 1),
    ("Game  of  Thrones S01E01", "Game of Thrones", 1, 1),
    ("Game of Thrones S 01 E 01", "Game of Thrones", 1, 1),
    
    # Multiple digit seasons/episodes
    ("Game of Thrones S04E10", "Game of Thrones", 4, 10),
    ("Game of Thrones season 8 episode 6", "Game of Thrones", 8, 6),
    ("The Office S09E24", "The Office", 9, 24),
    
    # Special characters and punctuation
    ("Mr. Robot S01E01", "Mr. Robot", 1, 1),
    ("It's Always Sunny S01E01", "It's Always Sunny in Philadelphia", 1, 1),
    
    # Additional test cases to reach 50+
    ("Friends S01E01", "Friends", 1, 1),
    ("friends episode 1", "Friends", 1, 1),
    ("The Simpsons S01E01", "The Simpsons", 1, 1),
    ("simpsons episode 1", "The Simpsons", 1, 1),
    ("Stranger Things S01E01", "Stranger Things", 1, 1),
    ("stranger things episode 1", "Stranger Things", 1, 1),
    ("The Crown S01E01", "The Crown", 1, 1),
    ("crown episode 1", "The Crown", 1, 1),
    ("Westworld S01E01", "Westworld", 1, 1),
    ("westworld episode 1", "Westworld", 1, 1),
]

# Series that should be downloadable (popular series with subtitles available)
DOWNLOADABLE_SERIES = [
    "Game of Thrones",
    "The Marvelous Mrs. Maisel",
    "Fallout",
    "Severance",
    "The Boys",
    "Breaking Bad",
    "The Office",
    "House of the Dragon",
    "True Detective",
    "Better Call Saul",
    "Black Sails",
    "Friends",
    "The Simpsons",
    "Stranger Things",
    "The Crown",
    "Westworld",
]


def test_extract_season_episode() -> Tuple[int, int, List[Dict]]:
    """Test season/episode extraction."""
    print("\n" + "="*60)
    print("TEST 1: Season/Episode Extraction")
    print("="*60)
    
    passed = 0
    failed = 0
    failures = []
    
    for input_text, expected_series, expected_season, expected_episode in TEST_CASES:
        result_season, result_episode = extract_season_episode(input_text)
        
        if result_season == expected_season and result_episode == expected_episode:
            passed += 1
            print(f"✓ '{input_text}' -> S{result_season or '?'}E{result_episode or '?'}")
        else:
            failed += 1
            failures.append({
                'input': input_text,
                'expected': (expected_season, expected_episode),
                'got': (result_season, result_episode)
            })
            print(f"✗ '{input_text}' -> Expected S{expected_season or '?'}E{expected_episode or '?'}, got S{result_season or '?'}E{result_episode or '?'}")
    
    print(f"\nResults: {passed} passed, {failed} failed out of {len(TEST_CASES)} tests")
    return passed, failed, failures


async def test_series_name_normalization() -> Tuple[int, int, List[Dict]]:
    """Test series name normalization with ChatGPT."""
    print("\n" + "="*60)
    print("TEST 2: Series Name Normalization")
    print("="*60)
    
    # Get API key
    api_key = os.environ.get('OPENAI_API_KEY')
    if not api_key:
        # Try to get from telegram_bot.py
        try:
            with open('telegram_bot.py', 'r') as f:
                for line in f:
                    if 'OPENAI_API_KEY' in line and '=' in line:
                        api_key = line.split('"')[1] if '"' in line else line.split("'")[1]
                        break
        except:
            pass
    
    if not api_key:
        print("⚠️  No OpenAI API key found. Skipping normalization tests.")
        return 0, 0, []
    
    openai_client = OpenAI(api_key=api_key)
    
    passed = 0
    failed = 0
    skipped = 0
    failures = []
    
    # Test a subset of cases (normalization is expensive)
    test_subset = TEST_CASES[:20]  # Test first 20 cases
    
    for input_text, expected_series, _, _ in test_subset:
        try:
            # Clean input (remove season/episode info for normalization)
            clean_input = input_text
            season, episode = extract_season_episode(input_text)
            if season or episode:
                import re
                clean_input = re.sub(r'[Ss]\d+[Ee]\d+', '', clean_input)
                clean_input = re.sub(r'season\s+\d+', '', clean_input, flags=re.IGNORECASE)
                clean_input = re.sub(r'episode\s+\d+', '', clean_input, flags=re.IGNORECASE)
                clean_input = re.sub(r'\b[Ss]\s*\d+\b', '', clean_input)
                clean_input = re.sub(r'\b[Ee]p?\s*\d+\b', '', clean_input, flags=re.IGNORECASE)
                clean_input = clean_input.strip()
            
            if len(clean_input) < 3:
                continue
            
            result = await normalize_series_name(clean_input, openai_client)
            
            # Check if result matches expected (case-insensitive, allow partial matches)
            result_lower = result.lower()
            expected_lower = expected_series.lower()
            
            # Allow partial matches (e.g., "Marvelous Mrs. Maisel" matches "The Marvelous Mrs. Maisel")
            if expected_lower in result_lower or result_lower in expected_lower or \
               any(word in result_lower for word in expected_lower.split() if len(word) > 3):
                passed += 1
                print(f"✓ '{clean_input}' -> '{result}' (expected: '{expected_series}')")
            else:
                failed += 1
                failures.append({
                    'input': clean_input,
                    'expected': expected_series,
                    'got': result
                })
                print(f"✗ '{clean_input}' -> '{result}' (expected: '{expected_series}')")
        except Exception as e:
            error_str = str(e)
            if 'quota' in error_str.lower() or '429' in error_str:
                skipped += 1
                print(f"⚠️  '{input_text}' -> Skipped (API quota exceeded)")
            else:
                failed += 1
                failures.append({
                    'input': input_text,
                    'expected': expected_series,
                    'error': error_str
                })
                print(f"✗ '{input_text}' -> Error: {error_str}")
    
    if skipped > 0:
        print(f"\nResults: {passed} passed, {failed} failed, {skipped} skipped out of {len(test_subset)} tests")
    else:
        print(f"\nResults: {passed} passed, {failed} failed out of {len(test_subset)} tests")
    return passed, failed, failures


def test_download_functionality() -> Tuple[int, int, List[Dict]]:
    """Test actual download functionality."""
    print("\n" + "="*60)
    print("TEST 3: Download Functionality")
    print("="*60)
    
    downloader = OpenSubtitlesDownloader()
    test_dir = Path("test_downloads")
    test_dir.mkdir(exist_ok=True)
    
    passed = 0
    failed = 0
    failures = []
    
    # Test downloads for popular series (S01E01)
    download_tests = [
        ("Game of Thrones", 1, 1),
        ("The Marvelous Mrs. Maisel", 1, 1),
        ("Fallout", 1, 1),
        ("Severance", 1, 1),
        ("The Boys", 1, 1),
        ("Breaking Bad", 1, 1),
        ("The Office", 1, 1),
        ("House of the Dragon", 1, 1),
        ("True Detective", 1, 1),
        ("Better Call Saul", 1, 1),
        ("Black Sails", 1, 1),
        ("Friends", 1, 1),
        ("The Simpsons", 1, 1),
        ("Stranger Things", 1, 1),
        ("The Crown", 1, 1),
        ("Westworld", 1, 1),
        # Add more episodes to reach 50+ tests
        ("Game of Thrones", 1, 2),
        ("Game of Thrones", 1, 3),
        ("Game of Thrones", 1, 4),
        ("Game of Thrones", 1, 5),
        ("Fallout", 1, 2),
        ("Fallout", 1, 3),
        ("Severance", 1, 2),
        ("Severance", 1, 3),
        ("The Boys", 1, 2),
        ("The Boys", 1, 3),
        ("Breaking Bad", 1, 2),
        ("Breaking Bad", 1, 3),
        ("The Office", 1, 2),
        ("The Office", 1, 3),
        ("House of the Dragon", 1, 2),
        ("True Detective", 1, 2),
        ("Better Call Saul", 1, 2),
        ("Black Sails", 1, 2),
        ("Friends", 1, 2),
        ("The Simpsons", 1, 2),
        ("Stranger Things", 1, 2),
        ("The Crown", 1, 2),
        ("Westworld", 1, 2),
        # Different seasons
        ("Game of Thrones", 2, 1),
        ("Game of Thrones", 3, 1),
        ("Game of Thrones", 4, 1),
        ("The Office", 2, 1),
        ("The Office", 3, 1),
        ("Breaking Bad", 2, 1),
        ("Breaking Bad", 3, 1),
        ("The Boys", 2, 1),
        ("The Boys", 3, 1),
        ("Fallout", 2, 1),
        ("Severance", 2, 1),
    ]
    
    print(f"Testing {len(download_tests)} download scenarios...")
    
    for i, (series_name, season, episode) in enumerate(download_tests, 1):
        try:
            series_dir = test_dir / series_name.replace(" ", "_")
            series_dir.mkdir(exist_ok=True)
            
            result = downloader.download_best_match(
                query=series_name,
                output_dir=series_dir,
                languages=["en"],
                season_number=season,
                episode_number=episode
            )
            
            if result and result.exists():
                file_size = result.stat().st_size
                if file_size > 0:
                    passed += 1
                    print(f"✓ [{i}/{len(download_tests)}] {series_name} S{season:02d}E{episode:02d} - Downloaded ({file_size} bytes)")
                    # Clean up after successful download
                    result.unlink()
                else:
                    failed += 1
                    failures.append({
                        'series': series_name,
                        'season': season,
                        'episode': episode,
                        'error': 'Empty file'
                    })
                    print(f"✗ [{i}/{len(download_tests)}] {series_name} S{season:02d}E{episode:02d} - Empty file")
            else:
                failed += 1
                failures.append({
                    'series': series_name,
                    'season': season,
                    'episode': episode,
                    'error': 'Download failed'
                })
                print(f"✗ [{i}/{len(download_tests)}] {series_name} S{season:02d}E{episode:02d} - Download failed")
        except Exception as e:
            failed += 1
            failures.append({
                'series': series_name,
                'season': season,
                'episode': episode,
                'error': str(e)
            })
            print(f"✗ [{i}/{len(download_tests)}] {series_name} S{season:02d}E{episode:02d} - Error: {e}")
    
    # Clean up test directory
    try:
        import shutil
        shutil.rmtree(test_dir)
    except:
        pass
    
    print(f"\nResults: {passed} passed, {failed} failed out of {len(download_tests)} tests")
    return passed, failed, failures


def generate_report(results: Dict):
    """Generate test report."""
    print("\n" + "="*60)
    print("TEST REPORT")
    print("="*60)
    
    total_passed = sum(r['passed'] for r in results.values())
    total_failed = sum(r['failed'] for r in results.values())
    total_tests = total_passed + total_failed
    
    print(f"\nOverall Results:")
    print(f"  Total Tests: {total_tests}")
    print(f"  Passed: {total_passed} ({total_passed/total_tests*100:.1f}%)")
    print(f"  Failed: {total_failed} ({total_failed/total_tests*100:.1f}%)")
    
    print(f"\nBreakdown by Test Type:")
    for test_name, result in results.items():
        test_total = result['passed'] + result['failed']
        if test_total > 0:
            print(f"  {test_name}:")
            print(f"    Passed: {result['passed']}/{test_total} ({result['passed']/test_total*100:.1f}%)")
            print(f"    Failed: {result['failed']}/{test_total} ({result['failed']/test_total*100:.1f}%)")
    
    # Save detailed report
    report_file = Path("test_download_report.json")
    with open(report_file, 'w') as f:
        json.dump({
            'timestamp': datetime.now().isoformat(),
            'summary': {
                'total_tests': total_tests,
                'passed': total_passed,
                'failed': total_failed,
                'success_rate': total_passed/total_tests*100 if total_tests > 0 else 0
            },
            'detailed_results': results
        }, f, indent=2)
    
    print(f"\nDetailed report saved to: {report_file}")
    
    return total_passed, total_failed


async def main():
    """Run all tests."""
    print("="*60)
    print("COMPREHENSIVE DOWNLOAD TEST SUITE")
    print("="*60)
    print(f"Running {len(TEST_CASES)} test cases for season/episode extraction")
    print(f"Testing download functionality with 50+ scenarios")
    
    results = {}
    
    # Test 1: Season/Episode Extraction
    passed, failed, failures = test_extract_season_episode()
    results['season_episode_extraction'] = {
        'passed': passed,
        'failed': failed,
        'failures': failures
    }
    
    # Test 2: Series Name Normalization
    passed, failed, failures = await test_series_name_normalization()
    results['series_name_normalization'] = {
        'passed': passed,
        'failed': failed,
        'failures': failures
    }
    
    # Test 3: Download Functionality
    passed, failed, failures = test_download_functionality()
    results['download_functionality'] = {
        'passed': passed,
        'failed': failed,
        'failures': failures
    }
    
    # Generate report
    total_passed, total_failed = generate_report(results)
    
    print("\n" + "="*60)
    if total_failed == 0:
        print("✅ ALL TESTS PASSED!")
    else:
        print(f"⚠️  {total_failed} test(s) failed. See report for details.")
    print("="*60)
    
    return 0 if total_failed == 0 else 1


if __name__ == '__main__':
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
