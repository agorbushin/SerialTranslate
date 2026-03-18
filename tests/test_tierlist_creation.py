#!/usr/bin/env python3
"""
Comprehensive tests for tier list creation functionality.

Tests cover:
1. Categorization logic (categorize_words function)
2. File generation (save_tierlist_results function)
3. Data integrity (word frequency mapping, word coverage, sorting)
4. Edge cases (empty subtitles, special characters, large files)
"""

import pytest
import csv
import json
import tempfile
import shutil
from pathlib import Path
from collections import Counter
from typing import Dict, List, Set
from unittest.mock import patch

# Import analyzer modules
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from subtitle_analyzer import categorize_words, save_tierlist_results


# ============================================================================
# TESTS FOR CATEGORIZATION LOGIC
# ============================================================================

class TestCategorizationLogic:
    """Test suite for word categorization logic."""
    
    def test_categorize_words_tier_1(self, sample_series_freq_data, sample_english_freq_data):
        """Test categorize_words - Tier 1: Low English freq, High series freq (not filtered)."""
        # Tier 1: Low English freq (< threshold), High series freq (>= threshold), not filtered
        series_freqs = Counter({'example': 5, 'test': 3})
        english_freqs = {'example': 1000000, 'test': 2000000}  # Low English freq
        
        # Set thresholds so words are in Tier 1
        # Series threshold should be low enough, English threshold should be high enough
        tiers = categorize_words(
            series_freqs,
            english_freqs,
            max_english_freq=5000000,
            oxford_filter=set(),
            easy_words_filter=set(),
            vocabulary_levels={'example': 'B1', 'test': 'B2'}
        )
        
        # Should have words in tier_1_hard_usable
        assert len(tiers['tier_1_hard_usable']) > 0
    
    def test_categorize_words_tier_2(self, sample_series_freq_data, sample_english_freq_data):
        """Test categorize_words - Tier 2: Low English freq, Low series freq (not filtered)."""
        # Tier 2: Low English freq, Low series freq (< threshold)
        # Need multiple words for threshold calculation
        series_freqs = Counter({'rare1': 1, 'rare2': 1, 'rare3': 1, 'word1': 5, 'word2': 5})  # Mix of low and high
        english_freqs = {'rare1': 100000, 'rare2': 200000, 'rare3': 300000, 'word1': 1000000, 'word2': 2000000}  # Low English freq
        
        tiers = categorize_words(
            series_freqs,
            english_freqs,
            max_english_freq=5000000,
            oxford_filter=set(),
            easy_words_filter=set(),
            vocabulary_levels={'rare1': 'C1', 'rare2': 'C1', 'rare3': 'C1', 'word1': 'B1', 'word2': 'B2'}
        )
        
        # Should have words in tier_2_random (low series freq, low english freq)
        assert len(tiers['tier_2_random']) > 0
    
    def test_categorize_words_tier_3(self, sample_series_freq_data, sample_english_freq_data):
        """Test categorize_words - Tier 3: High English freq, High series freq."""
        # Tier 3: High English freq (>= threshold), High series freq (>= threshold)
        series_freqs = Counter({'common': 10})  # High series freq
        english_freqs = {'common': 10000000}  # High English freq
        
        tiers = categorize_words(
            series_freqs,
            english_freqs,
            max_english_freq=5000000,
            oxford_filter=set(),
            easy_words_filter=set(),
            vocabulary_levels={'common': 'A1'}
        )
        
        # Should have words in tier_3_common
        assert len(tiers['tier_3_common']) > 0
    
    def test_categorize_words_tier_4(self, sample_series_freq_data, sample_english_freq_data):
        """Test categorize_words - Tier 4: High English freq, Low series freq."""
        # Tier 4: High English freq, Low series freq (< threshold)
        # Need multiple words for threshold calculation
        series_freqs = Counter({'the': 1, 'is': 1, 'a': 1, 'word1': 5, 'word2': 5})  # Mix
        english_freqs = {'the': 50000000, 'is': 40000000, 'a': 45000000, 'word1': 1000000, 'word2': 2000000}  # High English freq
        
        tiers = categorize_words(
            series_freqs,
            english_freqs,
            max_english_freq=5000000,
            oxford_filter=set(),
            easy_words_filter=set(),
            vocabulary_levels={'the': 'A1', 'is': 'A1', 'a': 'A1', 'word1': 'B1', 'word2': 'B2'}
        )
        
        # Should have words in tier_4_rare_in_series (high english freq, low series freq)
        assert len(tiers['tier_4_rare_in_series']) > 0
    
    def test_categorize_words_tier_5_filtered(self, sample_series_freq_data, sample_english_freq_data):
        """Test categorize_words - Tier 5: Filtered words (Oxford 3000, easy_words, high freq)."""
        # Tier 5: Words that would be Tier 1 or 2 but are filtered
        # Need multiple words for threshold calculation
        series_freqs = Counter({'example': 5, 'word1': 3, 'word2': 2, 'word3': 1})
        english_freqs = {'example': 1000000, 'word1': 2000000, 'word2': 500000, 'word3': 300000}
        
        # Add to Oxford filter (should be filtered to Tier 5)
        oxford_filter = {'example'}
        
        tiers = categorize_words(
            series_freqs,
            english_freqs,
            max_english_freq=5000000,
            oxford_filter=oxford_filter,
            easy_words_filter=set(),
            vocabulary_levels={'example': 'B1', 'word1': 'B1', 'word2': 'B2', 'word3': 'C1'}
        )
        
        # Should be in tier_5_filtered
        tier_5_words = [word for word, _, _, _, _ in tiers['tier_5_filtered']]
        assert 'example' in tier_5_words
    
    def test_categorize_words_threshold_calculation(self, sample_series_freq_data, sample_english_freq_data):
        """Test threshold calculation - verify thresholds are reasonable."""
        from subtitle_analyzer import calculate_thresholds
        
        series_freqs = Counter({'word1': 10, 'word2': 5, 'word3': 2, 'word4': 1})
        english_freqs = {'word1': 10000000, 'word2': 5000000, 'word3': 1000000, 'word4': 500000}
        
        series_threshold, english_threshold, _, _ = calculate_thresholds(series_freqs, english_freqs)
        
        # Thresholds should be reasonable values
        assert series_threshold > 0
        assert english_threshold > 0
        assert series_threshold <= max(series_freqs.values())
        assert english_threshold <= max(english_freqs.values())
    
    def test_categorize_words_oxford_filter(self, sample_series_freq_data, sample_english_freq_data):
        """Test filtering logic - Oxford 3000 filter application."""
        # Need multiple words for threshold calculation
        series_freqs = Counter({'oxford_word': 5, 'word1': 3, 'word2': 2})
        english_freqs = {'oxford_word': 1000000, 'word1': 2000000, 'word2': 500000}
        
        oxford_filter = {'oxford_word'}
        
        tiers = categorize_words(
            series_freqs,
            english_freqs,
            max_english_freq=5000000,
            oxford_filter=oxford_filter,
            easy_words_filter=set(),
            vocabulary_levels={'oxford_word': 'B1', 'word1': 'B1', 'word2': 'B2'}
        )
        
        # Should be filtered to Tier 5
        tier_5_words = [word for word, _, _, _, _ in tiers['tier_5_filtered']]
        assert 'oxford_word' in tier_5_words
    
    def test_categorize_words_easy_words_filter(self, sample_series_freq_data, sample_english_freq_data):
        """Test filtering logic - Easy words filter application."""
        # Need multiple words for threshold calculation
        series_freqs = Counter({'easy_word': 5, 'word1': 3, 'word2': 2})
        english_freqs = {'easy_word': 1000000, 'word1': 2000000, 'word2': 500000}
        
        easy_words_filter = {'easy_word'}
        
        tiers = categorize_words(
            series_freqs,
            english_freqs,
            max_english_freq=5000000,
            oxford_filter=set(),
            easy_words_filter=easy_words_filter,
            vocabulary_levels={'easy_word': 'B1', 'word1': 'B1', 'word2': 'B2'}
        )
        
        # Should be filtered to Tier 5
        tier_5_words = [word for word, _, _, _, _ in tiers['tier_5_filtered']]
        assert 'easy_word' in tier_5_words
    
    def test_categorize_words_high_frequency_filter(self, sample_series_freq_data, sample_english_freq_data):
        """Test filtering logic - High frequency filter (max_english_freq)."""
        # Need multiple words for threshold calculation
        series_freqs = Counter({'high_freq_word': 5, 'word1': 3, 'word2': 2})
        english_freqs = {'high_freq_word': 6000000, 'word1': 2000000, 'word2': 500000}  # Above max_english_freq
        
        tiers = categorize_words(
            series_freqs,
            english_freqs,
            max_english_freq=5000000,  # Threshold
            oxford_filter=set(),
            easy_words_filter=set(),
            vocabulary_levels={'high_freq_word': 'B1', 'word1': 'B1', 'word2': 'B2'}
        )
        
        # Should be filtered to Tier 5
        tier_5_words = [word for word, _, _, _, _ in tiers['tier_5_filtered']]
        assert 'high_freq_word' in tier_5_words


# ============================================================================
# TESTS FOR FILE GENERATION
# ============================================================================

class TestFileGeneration:
    """Test suite for file generation functionality."""
    
    def test_save_tierlist_results_directory_structure(self, temp_dir, sample_subtitle_file):
        """Test save_tierlist_results - directory structure creation."""
        from subtitle_analyzer import extract_series_info
        
        # Create sample tiers
        tiers = {
            'tier_1_hard_usable': [('word1', 5, 1000000, 'B1')],
            'tier_2_random': [('word2', 3, 2000000, 'A2')],
            'tier_3_common': [],
            'tier_4_rare_in_series': [],
            'tier_5_filtered': []
        }
        
        # Mock extract_series_info to return test data
        def mock_extract_series_info(path):
            return {
                'series': 'Test Series',
                'season': 'Season 1',
                'episode': 'Episode 01'
            }
        
        with patch('subtitle_analyzer.extract_series_info', side_effect=mock_extract_series_info):
            save_tierlist_results(
                tiers,
                sample_subtitle_file,
                series_threshold=2,
                english_threshold=5000000,
                max_english_freq=5000000,
                base_dir=temp_dir
            )
            
            # Verify directory structure
            expected_dir = temp_dir / "tierlist" / "Test Series" / "Season 1Episode 01"
            assert expected_dir.exists()
    
    def test_save_tierlist_results_csv_generation(self, temp_dir, sample_subtitle_file):
        """Test save_tierlist_results - CSV file generation for all 5 tiers."""
        from subtitle_analyzer import extract_series_info
        
        tiers = {
            'tier_1_hard_usable': [('word1', 5, 1000000, 'B1')],
            'tier_2_random': [('word2', 3, 2000000, 'A2')],
            'tier_3_common': [('word3', 10, 10000000, 'A1')],
            'tier_4_rare_in_series': [('word4', 1, 50000000, 'A1')],
            'tier_5_filtered': [('word5', 5, 1000000, 'B1', 'Oxford 3000', 'B1')]
        }
        
        def mock_extract_series_info(path):
            return {
                'series': 'Test Series',
                'season': 'Season 1',
                'episode': 'Episode 01'
            }
        
        with patch('subtitle_analyzer.extract_series_info', side_effect=mock_extract_series_info):
            save_tierlist_results(
                tiers,
                sample_subtitle_file,
                series_threshold=2,
                english_threshold=5000000,
                max_english_freq=5000000,
                base_dir=temp_dir
            )
            
            # Verify all tier files exist
            tierlist_dir = temp_dir / "tierlist" / "Test Series" / "Season 1Episode 01"
            assert (tierlist_dir / "tier_1_hard_usable_words.csv").exists()
            assert (tierlist_dir / "tier_2_random_words.csv").exists()
            assert (tierlist_dir / "tier_3_common_words.csv").exists()
            assert (tierlist_dir / "tier_4_rare_in_series.csv").exists()
            assert (tierlist_dir / "tier_5_filtered_words.csv").exists()
    
    def test_save_tierlist_results_csv_format(self, temp_dir, sample_subtitle_file):
        """Test save_tierlist_results - CSV format (column headers are correct)."""
        from subtitle_analyzer import extract_series_info
        
        tiers = {
            'tier_1_hard_usable': [('word1', 5, 1000000, 'B1')],
            'tier_2_random': [],
            'tier_3_common': [],
            'tier_4_rare_in_series': [],
            'tier_5_filtered': [('word5', 5, 1000000, 'B1', 'Oxford 3000', 'B1')]
        }
        
        def mock_extract_series_info(path):
            return {
                'series': 'Test Series',
                'season': 'Season 1',
                'episode': 'Episode 01'
            }
        
        with patch('subtitle_analyzer.extract_series_info', side_effect=mock_extract_series_info):
            save_tierlist_results(
                tiers,
                sample_subtitle_file,
                series_threshold=2,
                english_threshold=5000000,
                max_english_freq=5000000,
                base_dir=temp_dir
            )
            
            # Check Tier 1 format
            tier1_file = temp_dir / "tierlist" / "Test Series" / "Season 1Episode 01" / "tier_1_hard_usable_words.csv"
            with open(tier1_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                fieldnames = reader.fieldnames
                assert 'word' in fieldnames
                assert 'series_frequency' in fieldnames
                assert 'english_frequency' in fieldnames
                assert 'vocabulary_level' in fieldnames
            
            # Check Tier 5 format (has filter_reason)
            tier5_file = temp_dir / "tierlist" / "Test Series" / "Season 1Episode 01" / "tier_5_filtered_words.csv"
            with open(tier5_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                fieldnames = reader.fieldnames
                assert 'word' in fieldnames
                assert 'filter_reason' in fieldnames
                assert 'vocabulary_level' in fieldnames
    
    def test_save_tierlist_results_episode_info_json(self, temp_dir, sample_subtitle_file):
        """Test save_tierlist_results - episode_info.json creation with metadata."""
        from subtitle_analyzer import extract_series_info
        
        tiers = {
            'tier_1_hard_usable': [('word1', 5, 1000000, 'B1')],
            'tier_2_random': [('word2', 3, 2000000, 'A2')],
            'tier_3_common': [],
            'tier_4_rare_in_series': [],
            'tier_5_filtered': []
        }
        
        def mock_extract_series_info(path):
            return {
                'series': 'Test Series',
                'season': 'Season 1',
                'episode': 'Episode 01'
            }
        
        with patch('subtitle_analyzer.extract_series_info', side_effect=mock_extract_series_info):
            save_tierlist_results(
                tiers,
                sample_subtitle_file,
                series_threshold=2,
                english_threshold=5000000,
                max_english_freq=5000000,
                base_dir=temp_dir
            )
            
            # Verify episode_info.json exists
            tierlist_dir = temp_dir / "tierlist" / "Test Series" / "Season 1Episode 01"
            episode_info_file = tierlist_dir / "episode_info.json"
            assert episode_info_file.exists()
            
            # Verify metadata content
            with open(episode_info_file, 'r', encoding='utf-8') as f:
                info = json.load(f)
                assert info['series'] == 'Test Series'
                assert info['season'] == 'Season 1'
                assert info['episode'] == 'Episode 01'
                assert 'thresholds' in info
                assert 'word_counts' in info
                assert 'analysis_date' in info
    
    def test_save_tierlist_results_word_counts_match(self, temp_dir, sample_subtitle_file):
        """Test save_tierlist_results - word counts match actual tier sizes."""
        from subtitle_analyzer import extract_series_info
        
        tiers = {
            'tier_1_hard_usable': [('word1', 5, 1000000, 'B1'), ('word2', 3, 2000000, 'A2')],
            'tier_2_random': [('word3', 2, 500000, 'B2')],
            'tier_3_common': [],
            'tier_4_rare_in_series': [],
            'tier_5_filtered': []
        }
        
        def mock_extract_series_info(path):
            return {
                'series': 'Test Series',
                'season': 'Season 1',
                'episode': 'Episode 01'
            }
        
        with patch('subtitle_analyzer.extract_series_info', side_effect=mock_extract_series_info):
            save_tierlist_results(
                tiers,
                sample_subtitle_file,
                series_threshold=2,
                english_threshold=5000000,
                max_english_freq=5000000,
                base_dir=temp_dir
            )
            
            # Verify word counts in episode_info.json match actual tier sizes
            tierlist_dir = temp_dir / "tierlist" / "Test Series" / "Season 1Episode 01"
            episode_info_file = tierlist_dir / "episode_info.json"
            
            with open(episode_info_file, 'r', encoding='utf-8') as f:
                info = json.load(f)
                word_counts = info['word_counts']
                
                assert word_counts['tier_1_hard_usable'] == 2
                assert word_counts['tier_2_random'] == 1
                assert word_counts['tier_3_common'] == 0


# ============================================================================
# TESTS FOR DATA INTEGRITY
# ============================================================================

class TestDataIntegrity:
    """Test suite for data integrity."""
    
    def test_word_frequency_mapping_accuracy(self, sample_series_freq_data, sample_english_freq_data):
        """Test word frequency mapping - series frequency accuracy."""
        series_freqs = Counter({'example': 5, 'test': 3})
        english_freqs = {'example': 1000000, 'test': 2000000}
        
        tiers = categorize_words(
            series_freqs,
            english_freqs,
            max_english_freq=5000000,
            oxford_filter=set(),
            easy_words_filter=set(),
            vocabulary_levels={'example': 'B1', 'test': 'A2'}
        )
        
        # Verify frequencies are preserved
        tier_1_words = tiers['tier_1_hard_usable']
        for word, series_count, english_count, vocab_level in tier_1_words:
            assert series_count == series_freqs[word]
            assert english_count == english_freqs[word]
    
    def test_word_coverage_all_words_categorized(self, sample_series_freq_data, sample_english_freq_data):
        """Test word coverage - all words from subtitle are categorized."""
        series_freqs = Counter({'word1': 5, 'word2': 3, 'word3': 10, 'word4': 1})
        english_freqs = {'word1': 1000000, 'word2': 2000000, 'word3': 10000000, 'word4': 50000000}
        
        tiers = categorize_words(
            series_freqs,
            english_freqs,
            max_english_freq=5000000,
            oxford_filter=set(),
            easy_words_filter=set(),
            vocabulary_levels={'word1': 'B1', 'word2': 'A2', 'word3': 'A1', 'word4': 'A1'}
        )
        
        # Count words in all tiers
        total_categorized = (
            len(tiers['tier_1_hard_usable']) +
            len(tiers['tier_2_random']) +
            len(tiers['tier_3_common']) +
            len(tiers['tier_4_rare_in_series']) +
            len(tiers['tier_5_filtered'])
        )
        
        # All words should be categorized
        assert total_categorized == len(series_freqs)
    
    def test_word_coverage_no_words_lost(self, sample_series_freq_data, sample_english_freq_data):
        """Test word coverage - no words are lost in categorization."""
        series_freqs = Counter({'word1': 5, 'word2': 3, 'word3': 10})
        english_freqs = {'word1': 1000000, 'word2': 2000000, 'word3': 10000000}
        
        original_words = set(series_freqs.keys())
        
        tiers = categorize_words(
            series_freqs,
            english_freqs,
            max_english_freq=5000000,
            oxford_filter=set(),
            easy_words_filter=set(),
            vocabulary_levels={'word1': 'B1', 'word2': 'A2', 'word3': 'A1'}
        )
        
        # Collect all categorized words
        categorized_words = set()
        for tier_name in tiers:
            for item in tiers[tier_name]:
                word = item[0]
                categorized_words.add(word)
        
        # All original words should be in categorized words
        assert original_words == categorized_words
    
    def test_sorting_by_series_frequency(self, sample_series_freq_data, sample_english_freq_data):
        """Test sorting - tiers sorted by series frequency (descending)."""
        series_freqs = Counter({'word1': 10, 'word2': 5, 'word3': 2})
        english_freqs = {'word1': 1000000, 'word2': 2000000, 'word3': 500000}
        
        tiers = categorize_words(
            series_freqs,
            english_freqs,
            max_english_freq=5000000,
            oxford_filter=set(),
            easy_words_filter=set(),
            vocabulary_levels={'word1': 'B1', 'word2': 'A2', 'word3': 'B2'}
        )
        
        # Check sorting in tier_1_hard_usable
        tier_1_words = tiers['tier_1_hard_usable']
        if len(tier_1_words) > 1:
            frequencies = [item[1] for item in tier_1_words]  # series_frequency is second element
            # Should be in descending order
            assert frequencies == sorted(frequencies, reverse=True)


# ============================================================================
# TESTS FOR EDGE CASES
# ============================================================================

class TestEdgeCases:
    """Test suite for edge cases."""
    
    def test_empty_subtitles(self, temp_dir):
        """Test empty subtitles - no words found."""
        series_freqs = Counter()  # Empty
        english_freqs = {}
        
        tiers = categorize_words(
            series_freqs,
            english_freqs,
            max_english_freq=5000000,
            oxford_filter=set(),
            easy_words_filter=set(),
            vocabulary_levels={}
        )
        
        # All tiers should be empty
        for tier_name in tiers:
            assert len(tiers[tier_name]) == 0
    
    def test_empty_tier_lists(self, temp_dir, sample_subtitle_file):
        """Test empty tier lists."""
        from subtitle_analyzer import extract_series_info
        
        tiers = {
            'tier_1_hard_usable': [],
            'tier_2_random': [],
            'tier_3_common': [],
            'tier_4_rare_in_series': [],
            'tier_5_filtered': []
        }
        
        def mock_extract_series_info(path):
            return {
                'series': 'Test Series',
                'season': 'Season 1',
                'episode': 'Episode 01'
            }
        
        with patch('subtitle_analyzer.extract_series_info', side_effect=mock_extract_series_info):
            save_tierlist_results(
                tiers,
                sample_subtitle_file,
                series_threshold=2,
                english_threshold=5000000,
                max_english_freq=5000000,
                base_dir=temp_dir
            )
            
            # Should still create files (even if empty)
            tierlist_dir = temp_dir / "tierlist" / "Test Series" / "Season 1Episode 01"
            assert (tierlist_dir / "tier_1_hard_usable_words.csv").exists()
            
            # Files should have headers but no data rows
            with open(tierlist_dir / "tier_1_hard_usable_words.csv", 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                rows = list(reader)
                assert len(rows) == 0
    
    def test_special_characters_in_series_name(self, temp_dir, sample_subtitle_file):
        """Test special characters - Unicode in series names."""
        from subtitle_analyzer import extract_series_info
        
        tiers = {
            'tier_1_hard_usable': [('word1', 5, 1000000, 'B1')],
            'tier_2_random': [],
            'tier_3_common': [],
            'tier_4_rare_in_series': [],
            'tier_5_filtered': []
        }
        
        def mock_extract_series_info(path):
            return {
                'series': 'Test Séries',  # Unicode character
                'season': 'Season 1',
                'episode': 'Episode 01'
            }
        
        with patch('subtitle_analyzer.extract_series_info', side_effect=mock_extract_series_info):
            save_tierlist_results(
                tiers,
                sample_subtitle_file,
                series_threshold=2,
                english_threshold=5000000,
                max_english_freq=5000000,
                base_dir=temp_dir
            )
            
            # Should handle Unicode in directory names
            tierlist_dir = temp_dir / "tierlist" / "Test Séries" / "Season 1Episode 01"
            assert tierlist_dir.exists()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
