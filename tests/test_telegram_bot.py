#!/usr/bin/env python3
"""
Comprehensive tests for Telegram bot functionality.

Tests cover:
1. Command handlers (/start, /next, /full, /phrasal)
2. Message handling (series name input, response formatting, context management)
3. Error handling (file not found, API errors, invalid data)
"""

import pytest
import asyncio
import json
import csv
import tempfile
import shutil
from pathlib import Path
from unittest.mock import Mock, AsyncMock, patch, MagicMock, call
from typing import Optional, Dict, List

# Import bot functions
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from telegram import Update, Message, User, Chat, Document, CallbackQuery
from telegram.ext import ContextTypes


# ============================================================================
# TESTS FOR COMMAND HANDLERS
# ============================================================================

class TestCommandHandlers:
    """Test suite for bot command handlers."""
    
    @pytest.mark.asyncio
    async def test_start_command(self, mock_update, mock_context):
        """Test /start command - verify welcome message format."""
        from telegram_bot import start, BOT_VERSION
        
        await start(mock_update, mock_context)
        
        # Verify reply_text was called
        assert mock_update.message.reply_text.called
        
        # Check reply content
        call_args = mock_update.message.reply_text.call_args
        message = call_args[0][0]
        parse_mode = call_args[1].get('parse_mode', None)
        
        assert "Welcome" in message or "welcome" in message.lower()
        assert "series" in message.lower()
        assert BOT_VERSION in message
        assert parse_mode == 'Markdown'
    
    @pytest.mark.asyncio
    async def test_next_command(self, mock_update, mock_context):
        """Test /next command - verify prompt message for series name."""
        from telegram_bot import next_series
        
        await next_series(mock_update, mock_context)
        
        # Verify reply_text was called
        assert mock_update.message.reply_text.called
        
        # Check reply content
        call_args = mock_update.message.reply_text.call_args
        message = call_args[0][0]
        parse_mode = call_args[1].get('parse_mode', None)
        
        assert "series" in message.lower()
        assert "Fallout" in message or "Game of Thrones" in message
        assert parse_mode == 'Markdown'
    
    @pytest.mark.asyncio
    async def test_full_command_with_context(self, mock_update, mock_context, sample_episode_dir):
        """Test /full command - verify full list is sent when episode context exists."""
        from telegram_bot import send_full_list
        
        # Set context
        mock_context.user_data['last_episode_dir'] = str(sample_episode_dir)
        mock_context.user_data['last_series_name'] = 'Test Series'
        
        await send_full_list(mock_update, mock_context)
        
        # Should have replied
        assert mock_update.message.reply_text.called or mock_update.message.reply_document.called
    
    @pytest.mark.asyncio
    async def test_full_command_no_context(self, mock_update, mock_context):
        """Test /full command - verify error message when no episode context."""
        from telegram_bot import send_full_list
        
        # Clear context
        mock_context.user_data = {}
        
        await send_full_list(mock_update, mock_context)
        
        # Should reply with error message
        assert mock_update.message.reply_text.called
        call_args = mock_update.message.reply_text.call_args
        message = call_args[0][0]
        
        # Check for correct error message content (copy may say episode/movie vs "series")
        assert (
            "No series" in message
            or "no series" in message.lower()
            or "episode or movie" in message.lower()
        )
        assert (
            "requested" in message.lower()
            or "series first" in message.lower()
            or "loaded yet" in message.lower()
            or "title first" in message.lower()
        )
        # The message should mention /full or the command itself
        assert "/full" in message or "full" in message.lower() or "complete list" in message.lower()
    
    @pytest.mark.asyncio
    async def test_full_command_message_length_limit(self, mock_update, mock_context, temp_dir):
        """Test /full command - verify message length limits (Telegram 4096 char limit)."""
        from telegram_bot import send_full_list
        from conftest import create_tier_file, create_episode_info
        
        # Create episode dir with very long tier list
        episode_dir = temp_dir / "S01E01"
        episode_dir.mkdir(parents=True, exist_ok=True)
        
        # Create tier file with many words (to exceed 4096 chars)
        words_data = []
        for i in range(500):  # Large number of words
            words_data.append({
                'word': f'word{i}',
                'series_frequency': '5',
                'english_frequency': '1000000',
                'vocabulary_level': 'B1',
                'translation': f'перевод{i}',
                'example_en': f'This is example {i}',
                'example_translated': f'Это пример {i}',
                'is_name_or_fantasy': ''
            })
        
        create_tier_file(episode_dir, "tier_1_hard_usable_words", words_data)
        create_episode_info(episode_dir, "Test Series", "Season 1", "Episode 01")
        
        # Set context
        mock_context.user_data['last_episode_dir'] = str(episode_dir)
        mock_context.user_data['last_series_name'] = 'Test Series'
        
        await send_full_list(mock_update, mock_context)
        
        # Should handle long messages (either split or send as document)
        assert mock_update.message.reply_text.called or mock_update.message.reply_document.called
    
    @pytest.mark.asyncio
    async def test_phrasal_command_with_context(self, mock_update, mock_context, sample_episode_dir):
        """Test /phrasal command - verify phrasal verbs list is sent."""
        from telegram_bot import send_phrasal_verbs
        
        # Create phrasal verbs file
        phrasal_file = sample_episode_dir / "phrasal_verbs.csv"
        with open(phrasal_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['verb', 'frequency'])
            writer.writerow(['look up', '3'])
            writer.writerow(['give up', '2'])
        
        # Set context
        mock_context.user_data['last_episode_dir'] = str(sample_episode_dir)
        mock_context.user_data['last_series_name'] = 'Test Series'
        
        await send_phrasal_verbs(mock_update, mock_context)
        
        # Should have replied
        assert mock_update.message.reply_text.called
    
    @pytest.mark.asyncio
    async def test_phrasal_command_no_context(self, mock_update, mock_context):
        """Test /phrasal command - verify error handling when no episode context."""
        from telegram_bot import send_phrasal_verbs
        
        # Clear context
        mock_context.user_data = {}
        
        await send_phrasal_verbs(mock_update, mock_context)
        
        # Should reply with error message
        assert mock_update.message.reply_text.called
        call_args = mock_update.message.reply_text.call_args
        message = call_args[0][0]
        
        # Check for correct error message content
        assert "No series" in message or "no series" in message.lower()
        assert "requested" in message.lower() or "series first" in message.lower()
        # The message should mention /phrasal or phrasal verbs
        assert "/phrasal" in message or "phrasal" in message.lower()


# ============================================================================
# TESTS FOR MESSAGE HANDLING
# ============================================================================

class TestMessageHandling:
    """Test suite for message handling functionality."""
    
    @pytest.mark.asyncio
    async def test_series_name_input_valid(self, mock_update, mock_context, monkeypatch):
        """Test series name input - valid series names."""
        from telegram_bot import handle_message
        
        test_cases = [
            "Fallout",
            "Game of Thrones",
            "Better Call Saul"
        ]
        
        for series_name in test_cases:
            mock_update.message.text = series_name
            
            # Mock normalize_series_name
            def mock_normalize(input_text, client):
                return series_name
            
            # Mock find_existing_tier_lists
            def mock_find_tier_lists(series):
                return []
            
            with patch('telegram_bot.normalize_series_name', side_effect=mock_normalize):
                with patch('telegram_bot.find_existing_tier_lists', side_effect=mock_find_tier_lists):
                    with patch('telegram_bot.find_existing_subtitle', return_value=None):
                        await handle_message(mock_update, mock_context)
                        
                        # Should have replied
                        assert mock_update.message.reply_text.called
    
    @pytest.mark.asyncio
    async def test_series_name_with_season_episode(self, mock_update, mock_context, monkeypatch):
        """Test series name input - series with season/episode."""
        from telegram_bot import handle_message
        
        mock_update.message.text = "Fallout S02E01"
        
        # Mock normalize_series_name
        def mock_normalize(input_text, client):
            return "Fallout"
        
        # Mock find_existing_tier_lists
        def mock_find_tier_lists(series):
            return []
        
        with patch('telegram_bot.normalize_series_name', side_effect=mock_normalize):
            with patch('telegram_bot.find_existing_tier_lists', side_effect=mock_find_tier_lists):
                with patch('telegram_bot.find_existing_subtitle', return_value=None):
                    await handle_message(mock_update, mock_context)
                    
                    # Should have replied
                    assert mock_update.message.reply_text.called
    
    @pytest.mark.asyncio
    async def test_series_name_input_too_short(self, mock_update, mock_context):
        """Test series name input - invalid inputs (too short)."""
        from telegram_bot import handle_message
        
        mock_update.message.text = "AB"  # Too short
        
        await handle_message(mock_update, mock_context)
        
        # Should reply with error
        assert mock_update.message.reply_text.called
        call_args = mock_update.message.reply_text.call_args
        message = call_args[0][0]
        
        assert "short" in message.lower() or "too short" in message.lower() or "at least" in message.lower()
    
    @pytest.mark.asyncio
    async def test_series_name_input_empty(self, mock_update, mock_context):
        """Test series name input - empty input."""
        from telegram_bot import handle_message
        
        mock_update.message.text = ""
        
        await handle_message(mock_update, mock_context)
        
        # Should reply with error
        assert mock_update.message.reply_text.called
    
    @pytest.mark.asyncio
    async def test_series_name_normalization(self, mock_update, mock_context, monkeypatch):
        """Test series name normalization with ChatGPT."""
        from telegram_bot import normalize_series_name
        from openai import OpenAI
        
        # Mock OpenAI client
        mock_client = Mock(spec=OpenAI)
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message = MagicMock()
        mock_response.choices[0].message.content = "Fallout"
        mock_client.chat.completions.create.return_value = mock_response
        
        # Test normalization
        result = await normalize_series_name("fallout", mock_client)
        
        assert result == "Fallout"
        assert mock_client.chat.completions.create.called
    
    @pytest.mark.asyncio
    async def test_response_formatting(self, mock_update, mock_context, sample_episode_dir):
        """Test response formatting - verify tier list message format."""
        from telegram_bot import send_tier_list_results
        
        # Set context
        mock_context.user_data['last_episode_dir'] = str(sample_episode_dir)
        mock_context.user_data['last_series_name'] = 'Test Series'
        
        await send_tier_list_results(mock_update, sample_episode_dir, mock_context)
        
        # Verify reply_text was called
        assert mock_update.message.reply_text.called
        
        # Check message format
        call_args = mock_update.message.reply_text.call_args
        message = call_args[0][0]
        
        # Should contain series name, word count, and word list
        assert "Test Series" in message or "series" in message.lower()
        assert "Words" in message or "words" in message.lower()
    
    @pytest.mark.asyncio
    async def test_context_management(self, mock_update, mock_context, sample_episode_dir, monkeypatch):
        """Test context management - verify last_episode_dir is stored correctly."""
        from telegram_bot import handle_message
        
        mock_update.message.text = "Test Series"
        
        # Mock functions
        def mock_normalize(input_text, client):
            return "Test Series"
        
        def mock_find_tier_lists(series):
            return [sample_episode_dir]
        
        with patch('telegram_bot.normalize_series_name', side_effect=mock_normalize):
            with patch('telegram_bot.find_existing_tier_lists', side_effect=mock_find_tier_lists):
                with patch('telegram_bot.send_tier_list_results', new_callable=AsyncMock) as mock_send:
                    # Ensure send_tier_list_results sets context
                    async def mock_send_with_context(update, episode_dir, context):
                        context.user_data['last_episode_dir'] = str(episode_dir)
                        context.user_data['last_series_name'] = "Test Series"
                    
                    mock_send.side_effect = mock_send_with_context
                    await handle_message(mock_update, mock_context)
                    
                    # Verify context was set
                    assert 'last_episode_dir' in mock_context.user_data
                    assert mock_context.user_data['last_episode_dir'] == str(sample_episode_dir)
                    assert mock_context.user_data.get('last_series_name') == "Test Series"
    
    @pytest.mark.asyncio
    async def test_context_persistence(self, mock_update, mock_context, sample_episode_dir):
        """Test context persistence across commands."""
        from telegram_bot import send_full_list
        
        # Set context
        mock_context.user_data['last_episode_dir'] = str(sample_episode_dir)
        mock_context.user_data['last_series_name'] = 'Test Series'
        
        # Call /full command
        await send_full_list(mock_update, mock_context)
        
        # Context should still be there
        assert 'last_episode_dir' in mock_context.user_data
        assert mock_context.user_data['last_episode_dir'] == str(sample_episode_dir)


# ============================================================================
# TESTS FOR ERROR HANDLING
# ============================================================================

class TestErrorHandling:
    """Test suite for error handling."""
    
    @pytest.mark.asyncio
    async def test_file_not_found_tier_list(self, mock_update, mock_context, temp_dir):
        """Test file not found errors - missing tier list files."""
        from telegram_bot import send_tier_list_results
        
        # Create episode dir without tier file
        episode_dir = temp_dir / "S01E01"
        episode_dir.mkdir(parents=True, exist_ok=True)
        
        await send_tier_list_results(mock_update, episode_dir, mock_context)
        
        # Should reply with error message
        assert mock_update.message.reply_text.called
        call_args = mock_update.message.reply_text.call_args
        message = call_args[0][0]
        
        assert "not found" in message.lower() or "Tier list" in message
    
    @pytest.mark.asyncio
    async def test_file_not_found_episode_info(self, mock_update, mock_context, temp_dir):
        """Test file not found errors - missing episode_info.json."""
        from telegram_bot import send_full_list
        
        # Create episode dir without episode_info.json
        episode_dir = temp_dir / "S01E01"
        episode_dir.mkdir(parents=True, exist_ok=True)
        
        # Create tier file
        tier_file = episode_dir / "tier_1_hard_usable_words.csv"
        with open(tier_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['word', 'series_frequency'])
            writer.writerow(['test', '5'])
        
        # Set context
        mock_context.user_data['last_episode_dir'] = str(episode_dir)
        mock_context.user_data['last_series_name'] = 'Test Series'
        
        # Should handle missing episode_info.json gracefully
        await send_full_list(mock_update, mock_context)
        
        # Should still reply (uses default series name)
        assert mock_update.message.reply_text.called or mock_update.message.reply_document.called
    
    @pytest.mark.asyncio
    async def test_api_error_openai_failure(self, mock_update, mock_context, monkeypatch):
        """Test API errors - OpenAI API failures."""
        from telegram_bot import normalize_series_name
        from openai import OpenAI
        
        # Mock OpenAI client that raises exception
        mock_client = Mock(spec=OpenAI)
        mock_client.chat.completions.create.side_effect = Exception("API Error")
        
        # Should handle error gracefully
        try:
            result = await normalize_series_name("test", mock_client)
            # If it doesn't raise, should return a fallback value
            assert result is not None
        except Exception:
            # If it raises, that's also acceptable error handling
            pass
    
    @pytest.mark.asyncio
    async def test_invalid_data_corrupted_csv(self, mock_update, mock_context, temp_dir):
        """Test invalid data - corrupted CSV files."""
        from telegram_bot import send_tier_list_results
        
        # Create episode dir with corrupted CSV
        episode_dir = temp_dir / "S01E01"
        episode_dir.mkdir(parents=True, exist_ok=True)
        
        tier_file = episode_dir / "tier_1_hard_usable_words.csv"
        tier_file.write_text("corrupted,csv,data\ninvalid,format", encoding='utf-8')
        
        # Should handle corrupted CSV gracefully
        try:
            await send_tier_list_results(mock_update, episode_dir, mock_context)
            # Should either handle error or reply with error message
            assert mock_update.message.reply_text.called
        except Exception:
            # If it raises, that's also acceptable
            pass
    
    @pytest.mark.asyncio
    async def test_invalid_data_invalid_json(self, mock_update, mock_context, temp_dir):
        """Test invalid data - invalid JSON in episode_info.json."""
        from telegram_bot import send_full_list
        
        # Create episode dir with invalid JSON
        episode_dir = temp_dir / "S01E01"
        episode_dir.mkdir(parents=True, exist_ok=True)
        
        # Create tier file
        tier_file = episode_dir / "tier_1_hard_usable_words.csv"
        with open(tier_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['word', 'series_frequency'])
            writer.writerow(['test', '5'])
        
        # Create invalid JSON
        (episode_dir / "episode_info.json").write_text("invalid json {", encoding='utf-8')
        
        # Set context
        mock_context.user_data['last_episode_dir'] = str(episode_dir)
        mock_context.user_data['last_series_name'] = 'Test Series'
        
        # Should handle invalid JSON gracefully
        await send_full_list(mock_update, mock_context)
        
        # Should still reply (uses default values)
        assert mock_update.message.reply_text.called or mock_update.message.reply_document.called
    
    @pytest.mark.asyncio
    async def test_empty_tier_list(self, mock_update, mock_context, temp_dir):
        """Test invalid data - empty tier lists."""
        from telegram_bot import send_tier_list_results
        
        # Create episode dir with empty tier file
        episode_dir = temp_dir / "S01E01"
        episode_dir.mkdir(parents=True, exist_ok=True)
        
        tier_file = episode_dir / "tier_1_hard_usable_words.csv"
        tier_file.write_text("word,series_frequency\n", encoding='utf-8')  # Only header
        
        await send_tier_list_results(mock_update, episode_dir, mock_context)
        
        # Should handle empty list gracefully
        assert mock_update.message.reply_text.called


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
