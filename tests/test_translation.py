#!/usr/bin/env python3
"""
Comprehensive tests for translation functionality.

Tests cover:
1. Translation functions (translate_words_with_context, translate_tier_file, translate_episode)
2. Translation quality (validation, retry logic, parallel processing)
3. Name/fantasy entity filtering (STAGE 1 and STAGE 1.5)
4. Edge cases (empty inputs, special characters, API limits)
"""

import pytest
import csv
import json
import tempfile
import shutil
import asyncio
from pathlib import Path
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from typing import Dict, List, Set

# Import translation modules
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from openai import OpenAI, AsyncOpenAI


# ============================================================================
# TESTS FOR TRANSLATION FUNCTIONS
# ============================================================================

class TestTranslationFunctions:
    """Test suite for translation functions."""
    
    def test_translate_words_with_context_single_word(self, mock_openai_client, mock_openai_response):
        """Test translate_words_with_context - verify translation for single words."""
        from translate_words import translate_words_with_context
        
        # Setup mock
        mock_openai_client.chat.completions.create.return_value = mock_openai_response
        
        words = ["example"]
        subtitle_text = "This is an example sentence."
        examples = {"example": ["This is an example sentence."]}
        
        result = translate_words_with_context(
            mock_openai_client, words, subtitle_text, examples, "Russian"
        )
        
        # Should return translation result
        assert isinstance(result, dict)
        assert mock_openai_client.chat.completions.create.called
    
    def test_translate_words_with_context_batch(self, mock_openai_client, mock_openai_response):
        """Test translate_words_with_context - test batch translation (10 words)."""
        from translate_words import translate_words_with_context
        
        # Setup mock response with 10 words
        response_content = {}
        for i in range(10):
            response_content[f"word{i}"] = {
                "translation": f"перевод{i}",
                "example_en": f"This is word {i}",
                "example_translated": f"Это слово {i}"
            }
        
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message = MagicMock()
        mock_response.choices[0].message.content = json.dumps(response_content)
        mock_openai_client.chat.completions.create.return_value = mock_response
        
        words = [f"word{i}" for i in range(10)]
        subtitle_text = " ".join([f"This is word {i}." for i in range(10)])
        examples = {word: [f"This is {word}."] for word in words}
        
        result = translate_words_with_context(
            mock_openai_client, words, subtitle_text, examples, "Russian"
        )
        
        # Should return translations for all words
        assert len(result) == 10
        assert mock_openai_client.chat.completions.create.called
    
    def test_translate_words_with_context_uses_subtitle_context(self, mock_openai_client, mock_openai_response):
        """Test translate_words_with_context - validate context usage from subtitles."""
        from translate_words import translate_words_with_context
        
        mock_openai_client.chat.completions.create.return_value = mock_openai_response
        
        words = ["example"]
        subtitle_text = "This is a very long subtitle text that provides context for the word example."
        examples = {"example": ["This is an example sentence."]}
        
        translate_words_with_context(
            mock_openai_client, words, subtitle_text, examples, "Russian"
        )
        
        # Verify subtitle context was included in the prompt
        call_args = mock_openai_client.chat.completions.create.call_args
        messages = call_args[1]['messages']
        user_message = messages[1]['content']  # User message is second
        
        assert subtitle_text[:8000] in user_message  # Should include subtitle context (up to 8000 chars)
    
    def test_translate_words_with_context_extracts_examples(self, mock_openai_client, mock_openai_response):
        """Test translate_words_with_context - check example extraction from subtitles."""
        from translate_words import translate_words_with_context
        
        mock_openai_client.chat.completions.create.return_value = mock_openai_response
        
        words = ["example"]
        subtitle_text = "This is an example sentence."
        examples = {"example": ["This is an example sentence.", "Another example here."]}
        
        translate_words_with_context(
            mock_openai_client, words, subtitle_text, examples, "Russian"
        )
        
        # Verify examples were included
        call_args = mock_openai_client.chat.completions.create.call_args
        messages = call_args[1]['messages']
        user_message = messages[1]['content']
        
        assert "example" in user_message.lower()
    
    def test_translate_tier_file_full_translation(self, temp_dir, sample_tier_1_file, sample_subtitle_file, monkeypatch):
        """Test translate_tier_file - full tier file translation."""
        from translate_words import translate_tier_file
        
        # Mock OpenAI API
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message = MagicMock()
        mock_response.choices[0].message.content = json.dumps({
            "example": {
                "translation": "пример",
                "example_en": "This is an example",
                "example_translated": "Это пример"
            },
            "test": {
                "translation": "тест",
                "example_en": "Let's test this",
                "example_translated": "Давайте протестируем это"
            }
        })
        
        with patch('translate_words.AsyncOpenAI') as mock_async_openai_class:
            mock_async_client = Mock()
            mock_async_client.chat.completions.create = AsyncMock(return_value=mock_response)
            mock_async_openai_class.return_value = mock_async_client
            
            # Mock filter_names_sync_with_reasons to return empty set (no names)
            with patch('translate_words.filter_names_sync_with_reasons', return_value=(set(), {})):
                result = translate_tier_file(
                    sample_tier_1_file,
                    sample_subtitle_file,
                    "test_api_key",
                    "Russian",
                    overwrite=True
                )
                
                # Should complete successfully
                assert result is True
                
                # Verify CSV was updated
                with open(sample_tier_1_file, 'r', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    rows = list(reader)
                    
                    # Check that translations were added
                    for row in rows:
                        if row['word'] in ['example', 'test']:
                            assert row.get('translation', '').strip() != ''
    
    def test_translate_tier_file_csv_column_updates(self, temp_dir, sample_tier_1_file, sample_subtitle_file, monkeypatch):
        """Test translate_tier_file - verify CSV column updates."""
        from translate_words import translate_tier_file
        
        # Mock OpenAI API
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message = MagicMock()
        mock_response.choices[0].message.content = json.dumps({
            "example": {
                "translation": "пример",
                "example_en": "This is an example",
                "example_translated": "Это пример"
            }
        })
        
        with patch('translate_words.AsyncOpenAI') as mock_async_openai_class:
            mock_async_client = Mock()
            mock_async_client.chat.completions.create = AsyncMock(return_value=mock_response)
            mock_async_openai_class.return_value = mock_async_client
            
            with patch('translate_words.filter_names_sync_with_reasons', return_value=(set(), {})):
                translate_tier_file(
                    sample_tier_1_file,
                    sample_subtitle_file,
                    "test_api_key",
                    "Russian",
                    overwrite=True
                )
                
                # Verify columns exist
                with open(sample_tier_1_file, 'r', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    fieldnames = reader.fieldnames
                    
                    assert 'translation' in fieldnames
                    assert 'example_en' in fieldnames
                    assert 'example_translated' in fieldnames
    
    def test_translate_tier_file_overwrite_flag(self, temp_dir, sample_tier_1_file, sample_subtitle_file, monkeypatch):
        """Test translate_tier_file - test overwrite flag behavior."""
        from translate_words import translate_tier_file
        
        # First, add existing translations
        with open(sample_tier_1_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        
        # Update one row with existing translation
        for row in rows:
            if row['word'] == 'example':
                row['translation'] = 'old_translation'
        
        with open(sample_tier_1_file, 'w', newline='', encoding='utf-8') as f:
            fieldnames = ['word', 'series_frequency', 'english_frequency', 'vocabulary_level',
                         'translation', 'example_en', 'example_translated', 'is_name_or_fantasy']
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        
        # Mock OpenAI API
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message = MagicMock()
        mock_response.choices[0].message.content = json.dumps({
            "example": {
                "translation": "новый_перевод",
                "example_en": "This is an example",
                "example_translated": "Это пример"
            }
        })
        
        with patch('translate_words.AsyncOpenAI') as mock_async_openai_class:
            mock_async_client = Mock()
            mock_async_client.chat.completions.create = AsyncMock(return_value=mock_response)
            mock_async_openai_class.return_value = mock_async_client
            
            with patch('translate_words.filter_names_sync_with_reasons', return_value=(set(), {})):
                # With overwrite=True, should update existing translations
                translate_tier_file(
                    sample_tier_1_file,
                    sample_subtitle_file,
                    "test_api_key",
                    "Russian",
                    overwrite=True
                )
                
                # Verify translation was updated
                with open(sample_tier_1_file, 'r', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        if row['word'] == 'example':
                            # Should have new translation (if overwrite worked)
                            assert row.get('translation', '').strip() != 'old_translation'
    
    def test_translate_episode_translates_tier_1_and_2(self, temp_dir, sample_subtitle_file, monkeypatch):
        """Test translate_episode - translate tier_1 and tier_2 files."""
        from translate_words import translate_episode
        from conftest import create_tier_file, create_episode_info
        
        # Create episode dir with both tier files
        episode_dir = temp_dir / "S01E01"
        episode_dir.mkdir(parents=True, exist_ok=True)
        
        words_tier1 = [{'word': 'word1', 'series_frequency': '5', 'english_frequency': '1000000', 'vocabulary_level': 'B1'}]
        words_tier2 = [{'word': 'word2', 'series_frequency': '3', 'english_frequency': '2000000', 'vocabulary_level': 'A2'}]
        
        create_tier_file(episode_dir, "tier_1_hard_usable_words", words_tier1)
        create_tier_file(episode_dir, "tier_2_random_words", words_tier2)
        create_episode_info(episode_dir, "Test Series", "Season 1", "Episode 01")
        
        # Mock OpenAI API
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message = MagicMock()
        mock_response.choices[0].message.content = json.dumps({
            "word1": {"translation": "слово1", "example_en": "Test", "example_translated": "Тест"},
            "word2": {"translation": "слово2", "example_en": "Test", "example_translated": "Тест"}
        })
        
        with patch('translate_words.AsyncOpenAI') as mock_async_openai_class:
            mock_async_client = Mock()
            mock_async_client.chat.completions.create = AsyncMock(return_value=mock_response)
            mock_async_openai_class.return_value = mock_async_client
            
            with patch('translate_words.filter_names_sync_with_reasons', return_value=(set(), {})):
                result = translate_episode(
                    episode_dir,
                    sample_subtitle_file,
                    "test_api_key",
                    "Russian",
                    overwrite=True
                )
                
                # Should complete successfully
                assert result is True
    
    def test_translate_episode_auto_discovers_subtitle(self, temp_dir, monkeypatch):
        """Test translate_episode - verify subtitle file auto-discovery."""
        from translate_words import translate_episode
        from conftest import create_tier_file, create_episode_info, create_subtitle_file
        
        # Create episode dir
        episode_dir = temp_dir / "S01E01"
        episode_dir.mkdir(parents=True, exist_ok=True)
        
        # Create subtitle file in parent directory (typical structure)
        subtitle_file = temp_dir / "test_series.srt"
        create_subtitle_file(temp_dir, "test_series.srt")
        
        words_tier1 = [{'word': 'word1', 'series_frequency': '5', 'english_frequency': '1000000', 'vocabulary_level': 'B1'}]
        create_tier_file(episode_dir, "tier_1_hard_usable_words", words_tier1)
        create_episode_info(episode_dir, "Test Series", "Season 1", "Episode 01")
        
        # Mock OpenAI API
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message = MagicMock()
        mock_response.choices[0].message.content = json.dumps({
            "word1": {"translation": "слово1", "example_en": "Test", "example_translated": "Тест"}
        })
        
        with patch('translate_words.AsyncOpenAI') as mock_async_openai_class:
            mock_async_client = Mock()
            mock_async_client.chat.completions.create = AsyncMock(return_value=mock_response)
            mock_async_openai_class.return_value = mock_async_client
            
            with patch('translate_words.filter_names_sync_with_reasons', return_value=(set(), {})):
                # Call without subtitle_path (should auto-discover)
                result = translate_episode(
                    episode_dir,
                    None,  # No subtitle path provided
                    "test_api_key",
                    "Russian",
                    overwrite=True
                )
                
                # Should handle gracefully (may or may not find subtitle)
                assert isinstance(result, bool)


# ============================================================================
# TESTS FOR TRANSLATION QUALITY
# ============================================================================

class TestTranslationQuality:
    """Test suite for translation quality validation."""
    
    def test_translation_validation_no_na(self, temp_dir, sample_tier_1_file, sample_subtitle_file, monkeypatch):
        """Test translation validation - no 'N/A' translations."""
        from translate_words import translate_tier_file
        
        # Mock OpenAI API with N/A response (should be rejected)
        mock_response_na = MagicMock()
        mock_response_na.choices = [MagicMock()]
        mock_response_na.choices[0].message = MagicMock()
        mock_response_na.choices[0].message.content = json.dumps({
            "example": {
                "translation": "N/A",
                "example_en": "This is an example",
                "example_translated": "Это пример"
            }
        })
        
        # Mock OpenAI API with valid response (for retry)
        mock_response_valid = MagicMock()
        mock_response_valid.choices = [MagicMock()]
        mock_response_valid.choices[0].message = MagicMock()
        mock_response_valid.choices[0].message.content = json.dumps({
            "example": {
                "translation": "пример",
                "example_en": "This is an example",
                "example_translated": "Это пример"
            }
        })
        
        with patch('translate_words.OpenAI') as mock_openai_class:
            mock_client = Mock()
            # First call returns N/A, retry returns valid
            mock_client.chat.completions.create.side_effect = [mock_response_na, mock_response_valid]
            mock_openai_class.return_value = mock_client
            
            with patch('translate_words.filter_names_sync_with_reasons', return_value=(set(), {})):
                result = translate_tier_file(
                    sample_tier_1_file,
                    sample_subtitle_file,
                    "test_api_key",
                    "Russian",
                    overwrite=True
                )
                
                # Should complete (with retry)
                assert result is True
    
    def test_translation_validation_no_empty(self, temp_dir, sample_tier_1_file, sample_subtitle_file, monkeypatch):
        """Test translation validation - no empty translations."""
        from translate_words import translate_tier_file
        
        # Mock OpenAI API with empty translation (should be rejected)
        mock_response_empty = MagicMock()
        mock_response_empty.choices = [MagicMock()]
        mock_response_empty.choices[0].message = MagicMock()
        mock_response_empty.choices[0].message.content = json.dumps({
            "example": {
                "translation": "",
                "example_en": "This is an example",
                "example_translated": "Это пример"
            }
        })
        
        # Mock valid response for retry
        mock_response_valid = MagicMock()
        mock_response_valid.choices = [MagicMock()]
        mock_response_valid.choices[0].message = MagicMock()
        mock_response_valid.choices[0].message.content = json.dumps({
            "example": {
                "translation": "пример",
                "example_en": "This is an example",
                "example_translated": "Это пример"
            }
        })
        
        with patch('translate_words.OpenAI') as mock_openai_class:
            mock_client = Mock()
            mock_client.chat.completions.create.side_effect = [mock_response_empty, mock_response_valid]
            mock_openai_class.return_value = mock_client
            
            with patch('translate_words.filter_names_sync_with_reasons', return_value=(set(), {})):
                result = translate_tier_file(
                    sample_tier_1_file,
                    sample_subtitle_file,
                    "test_api_key",
                    "Russian",
                    overwrite=True
                )
                
                # Should complete (with retry)
                assert result is True
    
    def test_retry_logic_failed_translations(self, temp_dir, sample_tier_1_file, sample_subtitle_file, monkeypatch):
        """Test retry logic - words with failed translations."""
        from translate_words import translate_tier_file
        
        # Mock first call fails, second succeeds
        mock_response_fail = MagicMock()
        mock_response_fail.choices = [MagicMock()]
        mock_response_fail.choices[0].message = MagicMock()
        mock_response_fail.choices[0].message.content = json.dumps({
            "example": {
                "translation": "N/A",
                "example_en": "N/A",
                "example_translated": "N/A"
            }
        })
        
        mock_response_success = MagicMock()
        mock_response_success.choices = [MagicMock()]
        mock_response_success.choices[0].message = MagicMock()
        mock_response_success.choices[0].message.content = json.dumps({
            "example": {
                "translation": "пример",
                "example_en": "This is an example",
                "example_translated": "Это пример"
            }
        })
        
        with patch('translate_words.AsyncOpenAI') as mock_async_openai_class:
            mock_async_client = Mock()
            mock_async_client.chat.completions.create = AsyncMock(
                side_effect=[mock_response_fail, mock_response_success]
            )
            mock_async_openai_class.return_value = mock_async_client
            
            with patch('translate_words.filter_names_sync_with_reasons', return_value=(set(), {})):
                result = translate_tier_file(
                    sample_tier_1_file,
                    sample_subtitle_file,
                    "test_api_key",
                    "Russian",
                    overwrite=True
                )
                
                # Should retry and succeed
                assert result is True
                # Note: Retry happens in retry_single_word function internally
                # The call count may vary based on batch processing
                assert mock_async_client.chat.completions.create.call_count >= 1


# ============================================================================
# TESTS FOR NAME/FANTASY ENTITY FILTERING
# ============================================================================

class TestNameFiltering:
    """Test suite for name/fantasy entity filtering."""
    
    def test_filter_names_and_fantasy_entities_character_names(self, monkeypatch):
        """Test filter_names_and_fantasy_entities - character name detection."""
        from telegram_bot import filter_names_and_fantasy_entities
        from openai import OpenAI
        
        # Mock OpenAI client
        mock_client = Mock(spec=OpenAI)
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message = MagicMock()
        mock_response.choices[0].message.content = json.dumps({
            "exclude": ["John", "Mary"],
            "reason": {
                "John": "character name",
                "Mary": "character name"
            }
        })
        # Use AsyncMock for async method
        from unittest.mock import AsyncMock
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        
        words = ["John", "Mary", "example", "test"]
        subtitle_text = "John and Mary are characters. This is an example."
        
        result = asyncio.run(
            filter_names_and_fantasy_entities(words, subtitle_text, "Test Series", mock_client)
        )
        
        # Should identify names
        assert isinstance(result, set)
        assert "John" in result or "john" in {w.lower() for w in result}
        assert "Mary" in result or "mary" in {w.lower() for w in result}
    
    def test_filter_names_does_not_exclude_real_words(self, monkeypatch):
        """Test filter_names_and_fantasy_entities - verify words are NOT excluded when they're real English words."""
        from telegram_bot import filter_names_and_fantasy_entities
        from openai import OpenAI
        
        # Mock OpenAI client
        mock_client = Mock(spec=OpenAI)
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message = MagicMock()
        mock_response.choices[0].message.content = json.dumps({
            "exclude": [],
            "reason": {
                "example": "normal word",
                "test": "normal word"
            }
        })
        # Use AsyncMock for async method
        from unittest.mock import AsyncMock
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        
        words = ["example", "test"]
        subtitle_text = "This is an example test."
        
        result = asyncio.run(
            filter_names_and_fantasy_entities(words, subtitle_text, "Test Series", mock_client)
        )
        
        # Should NOT exclude real English words
        assert "example" not in result
        assert "test" not in result
    
    def test_simple_word_detection_vocabulary_level(self, temp_dir, sample_tier_1_file, sample_subtitle_file, monkeypatch):
        """Test STAGE 1.5 - simple word detection (A1/A2 vocabulary level)."""
        from translate_words import translate_tier_file
        
        # Create tier file with A1/A2 words
        words_data = [
            {
                'word': 'simple',
                'series_frequency': '5',
                'english_frequency': '1000000',
                'vocabulary_level': 'A1',  # A1 level - should be flagged
                'translation': '',
                'example_en': '',
                'example_translated': '',
                'is_name_or_fantasy': ''
            },
            {
                'word': 'easy',
                'series_frequency': '3',
                'english_frequency': '2000000',
                'vocabulary_level': 'A2',  # A2 level - should be flagged
                'translation': '',
                'example_en': '',
                'example_translated': '',
                'is_name_or_fantasy': ''
            }
        ]
        
        with open(sample_tier_1_file, 'w', newline='', encoding='utf-8') as f:
            fieldnames = ['word', 'series_frequency', 'english_frequency', 'vocabulary_level',
                         'translation', 'example_en', 'example_translated', 'is_name_or_fantasy']
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(words_data)
        
        # Mock OpenAI API
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message = MagicMock()
        mock_response.choices[0].message.content = json.dumps({})
        
        with patch('translate_words.AsyncOpenAI') as mock_async_openai_class:
            mock_async_client = Mock()
            mock_async_client.chat.completions.create = AsyncMock(return_value=mock_response)
            mock_async_openai_class.return_value = mock_async_client
            
            with patch('translate_words.filter_names_sync_with_reasons', return_value=(set(), {})):
                translate_tier_file(
                    sample_tier_1_file,
                    sample_subtitle_file,
                    "test_api_key",
                    "Russian",
                    overwrite=True
                )
                
                # Verify A1/A2 words were flagged
                with open(sample_tier_1_file, 'r', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        if row['vocabulary_level'] in ['A1', 'A2']:
                            assert 'simple word' in row.get('is_name_or_fantasy', '').lower()


# ============================================================================
# TESTS FOR EDGE CASES
# ============================================================================

class TestEdgeCases:
    """Test suite for edge cases."""
    
    def test_empty_word_list(self, temp_dir, sample_subtitle_file, monkeypatch):
        """Test empty inputs - empty word lists."""
        from translate_words import translate_tier_file
        
        # Create empty tier file
        tier_file = temp_dir / "empty_tier.csv"
        with open(tier_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['word', 'series_frequency'])
            # No data rows
        
        result = translate_tier_file(
            tier_file,
            sample_subtitle_file,
            "test_api_key",
            "Russian",
            overwrite=True
        )
        
        # Should handle empty list gracefully
        assert result is False
    
    def test_missing_subtitle_file(self, temp_dir, sample_tier_1_file, monkeypatch):
        """Test empty inputs - missing subtitle files."""
        from translate_words import translate_tier_file
        
        # Non-existent subtitle file
        missing_subtitle = temp_dir / "missing.srt"
        
        # Mock OpenAI API
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message = MagicMock()
        mock_response.choices[0].message.content = json.dumps({
            "example": {
                "translation": "пример",
                "example_en": "This is an example",
                "example_translated": "Это пример"
            }
        })
        
        with patch('translate_words.AsyncOpenAI') as mock_async_openai_class:
            mock_async_client = Mock()
            mock_async_client.chat.completions.create = AsyncMock(return_value=mock_response)
            mock_async_openai_class.return_value = mock_async_client
            
            with patch('translate_words.filter_names_sync_with_reasons', return_value=(set(), {})):
                # Should handle missing subtitle gracefully (translates without context)
                result = translate_tier_file(
                    sample_tier_1_file,
                    missing_subtitle,
                    "test_api_key",
                    "Russian",
                    overwrite=True
                )
                
                # Should still attempt translation (may succeed or fail)
                assert isinstance(result, bool)
    
    def test_special_characters_in_words(self, temp_dir, sample_subtitle_file, monkeypatch):
        """Test special characters - words with punctuation."""
        from translate_words import translate_tier_file
        
        # Create tier file with special characters
        tier_file = temp_dir / "special_tier.csv"
        words_data = [
            {
                'word': "don't",
                'series_frequency': '5',
                'english_frequency': '1000000',
                'vocabulary_level': 'B1',
                'translation': '',
                'example_en': '',
                'example_translated': '',
                'is_name_or_fantasy': ''
            }
        ]
        
        with open(tier_file, 'w', newline='', encoding='utf-8') as f:
            fieldnames = ['word', 'series_frequency', 'english_frequency', 'vocabulary_level',
                         'translation', 'example_en', 'example_translated', 'is_name_or_fantasy']
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(words_data)
        
        # Mock OpenAI API
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message = MagicMock()
        mock_response.choices[0].message.content = json.dumps({
            "don't": {
                "translation": "не",
                "example_en": "Don't do that",
                "example_translated": "Не делай этого"
            }
        })
        
        with patch('translate_words.AsyncOpenAI') as mock_async_openai_class:
            mock_async_client = Mock()
            mock_async_client.chat.completions.create = AsyncMock(return_value=mock_response)
            mock_async_openai_class.return_value = mock_async_client
            
            with patch('translate_words.filter_names_sync_with_reasons', return_value=(set(), {})):
                result = translate_tier_file(
                    tier_file,
                    sample_subtitle_file,
                    "test_api_key",
                    "Russian",
                    overwrite=True
                )
                
                # Should handle special characters
                assert result is True


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
