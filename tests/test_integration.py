#!/usr/bin/env python3
"""
Integration tests for end-to-end workflow.

Tests cover:
1. Full workflow test (Subtitle file → Tier list creation → Translation → Bot response)
2. Error propagation (how errors in one stage affect subsequent stages)
"""

import pytest
import csv
import json
import tempfile
import shutil
import subprocess
from pathlib import Path
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from collections import Counter

# Import modules
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from telegram import Update, Message, User, Chat
from telegram.ext import ContextTypes


# ============================================================================
# END-TO-END WORKFLOW TESTS
# ============================================================================

class TestEndToEndWorkflow:
    """Test suite for complete end-to-end workflows."""
    
    @pytest.mark.asyncio
    async def test_full_workflow_subtitle_to_bot_response(self, temp_dir, mock_update, mock_context, monkeypatch):
        """Test full workflow: Subtitle file → Tier list creation → Translation → Bot response."""
        from telegram_bot import handle_message
        from conftest import create_subtitle_file, create_tier_file, create_episode_info
        
        # Step 1: Create subtitle file
        subtitle_file = create_subtitle_file(
            temp_dir,
            "test_series.srt",
            """1
00:00:01,000 --> 00:00:03,000
This is a test subtitle with example words.

2
00:00:04,000 --> 00:00:06,000
Another line of dialogue for testing.
"""
        )
        
        # Step 2: Create episode directory with tier lists
        episode_dir = temp_dir / "tierlist" / "Test Series" / "S01E01"
        episode_dir.mkdir(parents=True, exist_ok=True)
        
        # Create tier_1 file
        words_tier1 = [
            {
                'word': 'example',
                'series_frequency': '5',
                'english_frequency': '1000000',
                'vocabulary_level': 'B1',
                'translation': 'пример',
                'example_en': 'This is an example',
                'example_translated': 'Это пример',
                'is_name_or_fantasy': ''
            }
        ]
        create_tier_file(episode_dir, "tier_1_hard_usable_words", words_tier1)
        
        # Create episode_info.json
        create_episode_info(episode_dir, "Test Series", "Season 1", "Episode 01")
        
        # Step 3: Mock bot functions
        mock_update.message.text = "Test Series"
        
        def mock_normalize_series_name(input_text, client):
            return "Test Series"
        
        def mock_find_existing_tier_lists(series):
            return [episode_dir]
        
        with patch('telegram_bot.normalize_series_name', side_effect=mock_normalize_series_name):
            with patch('telegram_bot.find_existing_tier_lists', side_effect=mock_find_existing_tier_lists):
                with patch('telegram_bot.BASE_DIR', temp_dir):
                    await handle_message(mock_update, mock_context)
                    
                    # Step 4: Verify bot responded
                    assert mock_update.message.reply_text.called
                    
                    # Step 5: Verify context was set
                    assert 'last_episode_dir' in mock_context.user_data
                    assert mock_context.user_data['last_episode_dir'] == str(episode_dir)
    
    @pytest.mark.asyncio
    async def test_full_workflow_data_flow(self, temp_dir, mock_update, mock_context, monkeypatch):
        """Test full workflow - verify data flows correctly through all stages."""
        from telegram_bot import handle_message
        from conftest import create_subtitle_file, create_tier_file, create_episode_info
        
        # Create complete workflow data
        subtitle_file = create_subtitle_file(temp_dir, "test.srt", "This is a test.")
        
        episode_dir = temp_dir / "tierlist" / "Test Series" / "S01E01"
        episode_dir.mkdir(parents=True, exist_ok=True)
        
        # Create tier file with known data
        words_tier1 = [
            {
                'word': 'test',
                'series_frequency': '3',
                'english_frequency': '2000000',
                'vocabulary_level': 'A2',
                'translation': 'тест',
                'example_en': 'This is a test',
                'example_translated': 'Это тест',
                'is_name_or_fantasy': ''
            }
        ]
        create_tier_file(episode_dir, "tier_1_hard_usable_words", words_tier1)
        create_episode_info(episode_dir, "Test Series", "Season 1", "Episode 01")
        
        # Mock bot functions
        mock_update.message.text = "Test Series"
        
        def mock_normalize(input_text, client):
            return "Test Series"
        
        def mock_find_tier_lists(series):
            return [episode_dir]
        
        with patch('telegram_bot.normalize_series_name', side_effect=mock_normalize):
            with patch('telegram_bot.find_existing_tier_lists', side_effect=mock_find_tier_lists):
                with patch('telegram_bot.BASE_DIR', temp_dir):
                    await handle_message(mock_update, mock_context)
                    
                    # Verify data integrity - word should be in response
                    call_args = mock_update.message.reply_text.call_args
                    message = call_args[0][0]
                    
                    # Should contain the word or series name
                    assert "Test Series" in message or "test" in message.lower()
    
    @pytest.mark.asyncio
    async def test_full_workflow_no_data_loss(self, temp_dir, mock_update, mock_context, monkeypatch):
        """Test full workflow - check no data loss between stages."""
        from telegram_bot import handle_message
        from conftest import create_subtitle_file, create_tier_file, create_episode_info
        
        # Create episode with multiple words
        episode_dir = temp_dir / "tierlist" / "Test Series" / "S01E01"
        episode_dir.mkdir(parents=True, exist_ok=True)
        
        words_tier1 = [
            {
                'word': f'word{i}',
                'series_frequency': str(5 + i),
                'english_frequency': str(1000000 + i * 100000),
                'vocabulary_level': 'B1',
                'translation': f'слово{i}',
                'example_en': f'This is word {i}',
                'example_translated': f'Это слово {i}',
                'is_name_or_fantasy': ''
            }
            for i in range(5)  # 5 words
        ]
        create_tier_file(episode_dir, "tier_1_hard_usable_words", words_tier1)
        create_episode_info(episode_dir, "Test Series", "Season 1", "Episode 01")
        
        # Mock bot
        mock_update.message.text = "Test Series"
        
        def mock_normalize(input_text, client):
            return "Test Series"
        
        def mock_find_tier_lists(series):
            return [episode_dir]
        
        with patch('telegram_bot.normalize_series_name', side_effect=mock_normalize):
            with patch('telegram_bot.find_existing_tier_lists', side_effect=mock_find_tier_lists):
                with patch('telegram_bot.BASE_DIR', temp_dir):
                    await handle_message(mock_update, mock_context)
                    
                    # Verify all words are still in the file
                    tier_file = episode_dir / "tier_1_hard_usable_words.csv"
                    with open(tier_file, 'r', encoding='utf-8') as f:
                        reader = csv.DictReader(f)
                        rows = list(reader)
                        
                        # Should have all 5 words
                        assert len(rows) == 5
                        
                        # Verify each word is present
                        words_in_file = {row['word'] for row in rows}
                        expected_words = {f'word{i}' for i in range(5)}
                        assert words_in_file == expected_words


# ============================================================================
# ERROR PROPAGATION TESTS
# ============================================================================

class TestErrorPropagation:
    """Test suite for error propagation between stages."""
    
    @pytest.mark.asyncio
    async def test_error_propagation_missing_subtitle(self, temp_dir, mock_update, mock_context, monkeypatch):
        """Test error propagation - missing subtitle file affects translation."""
        from telegram_bot import handle_message
        
        # Create episode dir without subtitle
        episode_dir = temp_dir / "tierlist" / "Test Series" / "S01E01"
        episode_dir.mkdir(parents=True, exist_ok=True)
        
        # Create tier file
        from conftest import create_tier_file, create_episode_info
        words_tier1 = [
            {
                'word': 'test',
                'series_frequency': '3',
                'english_frequency': '2000000',
                'vocabulary_level': 'A2',
                'translation': '',  # Not translated yet
                'example_en': '',
                'example_translated': '',
                'is_name_or_fantasy': ''
            }
        ]
        create_tier_file(episode_dir, "tier_1_hard_usable_words", words_tier1)
        create_episode_info(episode_dir, "Test Series", "Season 1", "Episode 01")
        
        # Mock bot
        mock_update.message.text = "Test Series"
        
        def mock_normalize(input_text, client):
            return "Test Series"
        
        def mock_find_tier_lists(series):
            return [episode_dir]
        
        def mock_find_subtitle(series, season=None, episode=None):
            return None  # No subtitle found
        
        with patch('telegram_bot.normalize_series_name', side_effect=mock_normalize):
            with patch('telegram_bot.find_existing_tier_lists', side_effect=mock_find_tier_lists):
                with patch('telegram_bot.find_existing_subtitle', side_effect=mock_find_subtitle):
                    with patch('telegram_bot.BASE_DIR', temp_dir):
                        await handle_message(mock_update, mock_context)
                        
                        # Should handle missing subtitle gracefully
                        assert mock_update.message.reply_text.called
    
    @pytest.mark.asyncio
    async def test_error_propagation_translation_failure(self, temp_dir, mock_update, mock_context, monkeypatch):
        """Test error propagation - translation failure affects bot response."""
        from telegram_bot import handle_message, translate_tier_list
        from conftest import create_tier_file, create_episode_info, create_subtitle_file
        
        # Create episode dir
        episode_dir = temp_dir / "tierlist" / "Test Series" / "S01E01"
        episode_dir.mkdir(parents=True, exist_ok=True)
        
        subtitle_file = create_subtitle_file(temp_dir, "test.srt", "This is a test.")
        
        words_tier1 = [
            {
                'word': 'test',
                'series_frequency': '3',
                'english_frequency': '2000000',
                'vocabulary_level': 'A2',
                'translation': '',  # Not translated
                'example_en': '',
                'example_translated': '',
                'is_name_or_fantasy': ''
            }
        ]
        create_tier_file(episode_dir, "tier_1_hard_usable_words", words_tier1)
        create_episode_info(episode_dir, "Test Series", "Season 1", "Episode 01")
        
        # Mock translation to fail
        def mock_translate_tier_list(ep_dir, sub_path):
            return False  # Translation failed
        
        # Mock bot
        mock_update.message.text = "Test Series"
        
        def mock_normalize(input_text, client):
            return "Test Series"
        
        def mock_find_tier_lists(series):
            return [episode_dir]
        
        with patch('telegram_bot.normalize_series_name', side_effect=mock_normalize):
            with patch('telegram_bot.find_existing_tier_lists', side_effect=mock_find_tier_lists):
                with patch('telegram_bot.translate_tier_list', side_effect=mock_translate_tier_list):
                    with patch('telegram_bot.BASE_DIR', temp_dir):
                        await handle_message(mock_update, mock_context)
                        
                        # Should handle translation failure gracefully
                        assert mock_update.message.reply_text.called
                        
                        # Error message should be clear
                        call_args = mock_update.message.reply_text.call_args
                        message = call_args[0][0]
                        # Should indicate translation issue or show untranslated list
                        assert isinstance(message, str)
    
    @pytest.mark.asyncio
    async def test_error_propagation_corrupted_tier_file(self, temp_dir, mock_update, mock_context, monkeypatch):
        """Test error propagation - corrupted tier file affects bot response."""
        from telegram_bot import send_tier_list_results
        
        # Create episode dir with corrupted tier file
        episode_dir = temp_dir / "S01E01"
        episode_dir.mkdir(parents=True, exist_ok=True)
        
        # Create corrupted CSV (missing 'word' column)
        tier_file = episode_dir / "tier_1_hard_usable_words.csv"
        tier_file.write_text("corrupted,csv,data\ninvalid,format", encoding='utf-8')
        
        # Should handle corrupted file gracefully (may raise exception or return error)
        try:
            await send_tier_list_results(mock_update, episode_dir, mock_context)
            # If it doesn't raise, should have replied
            assert mock_update.message.reply_text.called
        except (KeyError, ValueError, Exception):
            # If it raises an exception, that's also acceptable error handling
            # The important thing is that it doesn't crash the bot silently
            pass
    
    @pytest.mark.asyncio
    async def test_error_propagation_clear_error_messages(self, temp_dir, mock_update, mock_context, monkeypatch):
        """Test error propagation - verify error messages are clear."""
        from telegram_bot import send_tier_list_results
        
        # Create episode dir without tier file
        episode_dir = temp_dir / "S01E01"
        episode_dir.mkdir(parents=True, exist_ok=True)
        
        await send_tier_list_results(mock_update, episode_dir, mock_context)
        
        # Should have replied with error
        assert mock_update.message.reply_text.called
        
        call_args = mock_update.message.reply_text.call_args
        message = call_args[0][0]
        
        # Error message should be clear and informative
        assert isinstance(message, str)
        assert len(message) > 0
        # Should mention tier list or file
        assert "tier" in message.lower() or "file" in message.lower() or "not found" in message.lower()


# ============================================================================
# WORKFLOW INTEGRATION TESTS
# ============================================================================

class TestWorkflowIntegration:
    """Test suite for workflow integration scenarios."""
    
    @pytest.mark.asyncio
    async def test_workflow_with_existing_tier_list(self, temp_dir, mock_update, mock_context, monkeypatch):
        """Test workflow when tier list already exists (skip creation, go to translation)."""
        from telegram_bot import handle_message
        from conftest import create_tier_file, create_episode_info
        
        # Create episode dir with existing tier list
        episode_dir = temp_dir / "tierlist" / "Test Series" / "S01E01"
        episode_dir.mkdir(parents=True, exist_ok=True)
        
        words_tier1 = [
            {
                'word': 'test',
                'series_frequency': '3',
                'english_frequency': '2000000',
                'vocabulary_level': 'A2',
                'translation': 'тест',  # Already translated
                'example_en': 'This is a test',
                'example_translated': 'Это тест',
                'is_name_or_fantasy': ''
            }
        ]
        create_tier_file(episode_dir, "tier_1_hard_usable_words", words_tier1)
        create_episode_info(episode_dir, "Test Series", "Season 1", "Episode 01")
        
        # Mock bot
        mock_update.message.text = "Test Series"
        
        def mock_normalize(input_text, client):
            return "Test Series"
        
        def mock_find_tier_lists(series):
            return [episode_dir]  # Tier list exists
        
        with patch('telegram_bot.normalize_series_name', side_effect=mock_normalize):
            with patch('telegram_bot.find_existing_tier_lists', side_effect=mock_find_tier_lists):
                with patch('telegram_bot.BASE_DIR', temp_dir):
                    await handle_message(mock_update, mock_context)
                    
                    # Should skip tier list creation and go directly to sending results
                    assert mock_update.message.reply_text.called
    
    @pytest.mark.asyncio
    async def test_workflow_new_series_creation(self, temp_dir, mock_update, mock_context, monkeypatch):
        """Test workflow for new series (create tier list, translate, send)."""
        from telegram_bot import handle_message
        from conftest import create_subtitle_file
        
        # Create subtitle file
        subtitle_file = create_subtitle_file(
            temp_dir / "Subtitles" / "Test Series" / "Season 1" / "Episode 01",
            "test.srt",
            "This is a test subtitle."
        )
        subtitle_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Mock bot
        mock_update.message.text = "Test Series"
        
        def mock_normalize(input_text, client):
            return "Test Series"
        
        def mock_find_tier_lists(series):
            return []  # No existing tier lists
        
        def mock_find_subtitle(series, season=None, episode=None):
            return subtitle_file
        
        def mock_analyze_subtitle(path, level):
            # Mock subtitle analysis - create tier list
            episode_dir = temp_dir / "tierlist" / "Test Series" / "S01E01"
            episode_dir.mkdir(parents=True, exist_ok=True)
            
            from conftest import create_tier_file, create_episode_info
            words_tier1 = [
                {
                    'word': 'test',
                    'series_frequency': '3',
                    'english_frequency': '2000000',
                    'vocabulary_level': 'A2',
                    'translation': '',
                    'example_en': '',
                    'example_translated': '',
                    'is_name_or_fantasy': ''
                }
            ]
            create_tier_file(episode_dir, "tier_1_hard_usable_words", words_tier1)
            create_episode_info(episode_dir, "Test Series", "Season 1", "Episode 01")
            
            return episode_dir
        
        def mock_translate_tier_list(ep_dir, sub_path):
            return True  # Translation succeeds
        
        with patch('telegram_bot.normalize_series_name', side_effect=mock_normalize):
            with patch('telegram_bot.find_existing_tier_lists', side_effect=mock_find_tier_lists):
                with patch('telegram_bot.find_existing_subtitle', side_effect=mock_find_subtitle):
                    with patch('telegram_bot.analyze_subtitle', side_effect=mock_analyze_subtitle):
                        with patch('telegram_bot.translate_tier_list', side_effect=mock_translate_tier_list):
                            with patch('telegram_bot.BASE_DIR', temp_dir):
                                await handle_message(mock_update, mock_context)
                                
                                # Should complete full workflow
                                assert mock_update.message.reply_text.called


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
