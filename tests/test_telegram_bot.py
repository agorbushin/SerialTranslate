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
    async def test_full_command_with_context(self, mock_update, mock_context, temp_dir):
        """Test /full command - verify rare-in-series (C) full list when translations exist."""
        from telegram_bot import send_full_list

        trans_dir = temp_dir / "translations" / "Test Series" / "Season 1" / "1"
        trans_dir.mkdir(parents=True)
        (trans_dir / "translation_info.json").write_text(
            json.dumps(
                {"series": "Test Series", "season_number": 1, "episode_number": 1},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        with open(trans_dir / "tier_4_rare_c_translations.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["word", "translation_ru"])
            w.writerow(["alpha", "альфа"])
            w.writerow(["beta", "бета"])

        mock_context.user_data["last_translations_dir"] = str(trans_dir)
        mock_context.user_data["last_series_name"] = "Test Series"

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
        # The message should mention /full or rare-in-series prompt
        assert "/full" in message or "full" in message.lower() or "rare" in message.lower()
    
    @pytest.mark.asyncio
    async def test_full_command_message_length_limit(self, mock_update, mock_context, temp_dir):
        """Test /full command - verify message length limits (Telegram 4096 char limit)."""
        from telegram_bot import send_full_list

        trans_dir = temp_dir / "translations" / "Test Series" / "Season 1" / "1"
        trans_dir.mkdir(parents=True)
        (trans_dir / "translation_info.json").write_text(
            json.dumps(
                {"series": "Test Series", "season_number": 1, "episode_number": 1},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        with open(trans_dir / "tier_4_rare_c_translations.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["word", "translation_ru"])
            for i in range(500):
                w.writerow([f"word{i}", f"перевод{i}"])

        mock_context.user_data["last_translations_dir"] = str(trans_dir)
        mock_context.user_data["last_series_name"] = "Test Series"

        await send_full_list(mock_update, mock_context)
        
        # Should handle long messages (either split or send as document)
        assert mock_update.message.reply_text.called or mock_update.message.reply_document.called
    
    @pytest.mark.asyncio
    async def test_phrasal_command_with_context(self, mock_update, mock_context, temp_dir):
        """Test /phrasal command - verify phrasal verbs list is sent."""
        from telegram_bot import send_phrasal_verbs

        trans_dir = temp_dir / "translations" / "Test Series" / "Season 1" / "1"
        trans_dir.mkdir(parents=True)
        (trans_dir / "translation_info.json").write_text(
            json.dumps(
                {"series": "Test Series", "season_number": 1, "episode_number": 1},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        phrasal_file = trans_dir / "phrasal_verbs.csv"
        with open(phrasal_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "phrasal_verb",
                    "frequency",
                    "translation",
                    "idiomaticity_score",
                    "literality_score",
                    "score_rationale",
                    "example",
                ]
            )
            writer.writerow(
                ["look up", "3", "искать", "7", "3", "mixed collocation", ""]
            )
            writer.writerow(
                ["give up", "2", "сдаваться", "9", "2", "opaque particle", ""]
            )

        mock_context.user_data["last_translations_dir"] = str(trans_dir)
        mock_context.user_data["last_series_name"] = "Test Series"

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
        
        # Check for correct error message content (aligned with send_full_list / send_b_level_words)
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
        assert "/phrasal" in message or "phrasal" in message.lower()

    @pytest.mark.asyncio
    async def test_idioms_command_with_context(self, mock_update, mock_context, temp_dir):
        """Test /idioms with episode context — idioms feature shows WIP placeholder when disabled."""
        from telegram_bot import send_idiomatic_expressions

        trans_dir = temp_dir / "translations" / "Test Series" / "Season 1" / "1"
        trans_dir.mkdir(parents=True)
        (trans_dir / "translation_info.json").write_text(
            json.dumps(
                {"series": "Test Series", "season_number": 1, "episode_number": 1},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        idiom_file = trans_dir / "idiomatic_expressions.csv"
        with open(idiom_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "expression",
                    "frequency",
                    "translation",
                    "idiomacy_rating",
                    "example",
                ]
            )
            writer.writerow(
                ["fair enough", "2", "справедливо", "8", ""]
            )

        mock_context.user_data["last_translations_dir"] = str(trans_dir)
        mock_context.user_data["last_series_name"] = "Test Series"

        await send_idiomatic_expressions(mock_update, mock_context)

        assert mock_update.message.reply_text.called
        call_args = mock_update.message.reply_text.call_args
        message = call_args[0][0]
        assert "work in progress" in message.lower()
        assert "idioms" in message.lower()

    @pytest.mark.asyncio
    async def test_idioms_command_no_context(self, mock_update, mock_context):
        """Test idioms with no episode context — WIP placeholder (no 'load title first' gate)."""
        from telegram_bot import send_idiomatic_expressions

        mock_context.user_data = {}

        await send_idiomatic_expressions(mock_update, mock_context)

        assert mock_update.message.reply_text.called
        call_args = mock_update.message.reply_text.call_args
        message = call_args[0][0]
        assert "idioms" in message.lower() or "Idioms" in message
        assert "work in progress" in message.lower()


# ============================================================================
# TESTS FOR MESSAGE HANDLING
# ============================================================================

def test_should_auto_route_movie_from_series_mode() -> None:
    from telegram_bot import _should_auto_route_movie_from_series_mode

    assert _should_auto_route_movie_from_series_mode("the matrix 1999")
    assert _should_auto_route_movie_from_series_mode("Dune (2021)")
    assert not _should_auto_route_movie_from_series_mode("Fallout s2 e3")
    assert not _should_auto_route_movie_from_series_mode("Game of Thrones")
    assert not _should_auto_route_movie_from_series_mode("breaking bad season 1")


class TestMessageHandling:
    """Test suite for message handling functionality."""

    @pytest.mark.asyncio
    async def test_series_mode_auto_routes_title_with_year_to_movie(
        self, mock_update, mock_context
    ):
        """Movie-shaped text (title + year) in series mode delegates to movie handler."""
        mock_context.user_data["mode"] = "series"
        mock_update.message.text = "the matrix 1999"
        with patch("telegram_bot._handle_message_movie", new_callable=AsyncMock) as m_movie:
            from telegram_bot import handle_message

            await handle_message(mock_update, mock_context)
        m_movie.assert_called_once()
        assert m_movie.call_args[0][0] is mock_update
        assert m_movie.call_args[0][1] is mock_context
        assert m_movie.call_args[0][2] == "the matrix 1999"
    
    @pytest.mark.asyncio
    async def test_series_name_input_valid(self, mock_update, mock_context, monkeypatch):
        """Test series name input - valid series names."""
        from telegram_bot import handle_message

        test_cases = [
            "Fallout",
            "Game of Thrones",
            "Better Call Saul",
        ]

        from title_resolution import ResolvedTitle

        high = ResolvedTitle(
            media_type="tv",
            canonical_title="Fallout",
            season=1,
            episode=1,
            confidence="high",
        )
        for series_name in test_cases:
            mock_update.message.text = series_name
            with patch(
                "telegram_bot.resolve_input_async",
                new_callable=AsyncMock,
                return_value=high,
            ):
                with patch(
                    "telegram_bot._find_existing",
                    return_value=(None, None, None),
                ):
                    with patch("telegram_bot._do_download", return_value=None):
                        await handle_message(mock_update, mock_context)
                        assert mock_update.message.reply_text.called
    
    @pytest.mark.asyncio
    async def test_series_name_with_season_episode(self, mock_update, mock_context, monkeypatch):
        """Test series name input - series with season/episode."""
        from telegram_bot import handle_message

        from title_resolution import ResolvedTitle

        mock_update.message.text = "Fallout S02E01"
        with patch(
            "telegram_bot.resolve_input_async",
            new_callable=AsyncMock,
            return_value=ResolvedTitle(
                media_type="tv",
                canonical_title="Fallout",
                season=2,
                episode=1,
                confidence="high",
            ),
        ):
            with patch("telegram_bot._find_existing", return_value=(None, None, None)):
                with patch("telegram_bot._do_download", return_value=None):
                    await handle_message(mock_update, mock_context)
                    assert mock_update.message.reply_text.called
    
    @pytest.mark.asyncio
    async def test_series_name_input_too_short(self, mock_update, mock_context):
        """Test series name input - invalid inputs (too short)."""
        from telegram_bot import handle_message
        
        mock_update.message.text = "A"  # len(raw) < 2 triggers too-short branch

        await handle_message(mock_update, mock_context)

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
        """Test ChatGPT JSON normalization path used by the bot."""
        import telegram_bot as tb

        with patch.object(tb, "resolve_openai_api_key", return_value="sk-test"):
            with patch("openai.OpenAI") as m_oa:
                inst = m_oa.return_value
                inst.chat.completions.create.return_value = MagicMock(
                    choices=[
                        MagicMock(
                            message=MagicMock(
                                content='{"series_name": "Fallout", "season": 1, "episode": 1}'
                            )
                        )
                    ]
                )
                result = await tb._normalize_with_chatgpt("fallout")
        assert result == ("Fallout", 1, 1)
        assert inst.chat.completions.create.called
    
    @pytest.mark.skip(reason="send_tier_list_results was removed; lists are sent via _send_translations_list")
    @pytest.mark.asyncio
    async def test_response_formatting(self, mock_update, mock_context, sample_episode_dir):
        """Test response formatting - verify tier list message format."""
    
    @pytest.mark.asyncio
    async def test_context_management(
        self, mock_update, mock_context, sample_episode_dir, temp_dir, monkeypatch
    ):
        """Test context management - verify last_episode_dir is stored on cache hit."""
        import json
        import telegram_bot as tb
        from telegram_bot import handle_message

        monkeypatch.setattr(tb, "BASE_DIR", temp_dir)

        trans_dir = temp_dir / "translations" / "Test Series" / "Season 1" / "1"
        trans_dir.mkdir(parents=True)
        (trans_dir / "tier_1_translations.csv").write_text(
            "word,translation_ru\nhello,привет\n", encoding="utf-8"
        )
        (trans_dir / "translation_info.json").write_text(
            json.dumps(
                {
                    "series": "Test Series",
                    "season_number": 1,
                    "episode_number": 1,
                }
            ),
            encoding="utf-8",
        )

        mock_update.message.text = "Test Series"
        status_msg = Mock()
        status_msg.chat_id = 12345
        status_msg.message_id = 200
        status_msg.edit_text = AsyncMock()
        mock_update.message.reply_text = AsyncMock(return_value=status_msg)

        from title_resolution import ResolvedTitle

        with patch(
            "telegram_bot.resolve_input_async",
            new_callable=AsyncMock,
            return_value=ResolvedTitle(
                media_type="tv",
                canonical_title="Test Series",
                season=1,
                episode=1,
                confidence="high",
            ),
        ):
            with patch(
                "telegram_bot._find_existing",
                return_value=(sample_episode_dir, trans_dir, None),
            ):
                with patch("telegram_bot._send_translations_list", new_callable=AsyncMock):
                    await handle_message(mock_update, mock_context)

        assert Path(mock_context.user_data.get("last_episode_dir")).resolve() == sample_episode_dir.resolve()
        assert mock_context.user_data.get("last_series_name") == "Test Series"
        assert Path(mock_context.user_data.get("last_translations_dir")).resolve() == trans_dir.resolve()

    @pytest.mark.asyncio
    async def test_movie_high_confidence_runs_pipeline_without_confirmation(
        self, mock_update, mock_context
    ):
        """High-confidence movie resolution proceeds to pipeline without confirm keyboard."""
        from title_resolution import ResolvedTitle
        from telegram_bot import _handle_message_movie

        mock_update.message.text = "Inception 2010"
        high = ResolvedTitle(
            media_type="movie",
            canonical_title="Inception",
            year=2010,
            confidence="high",
            imdb_id="tt1375666",
        )
        with patch(
            "telegram_bot.resolve_input_async",
            new_callable=AsyncMock,
            return_value=high,
        ):
            with patch(
                "telegram_bot._run_movie_pipeline", new_callable=AsyncMock
            ) as m_pipe:
                with patch(
                    "telegram_bot._send_title_confirmation", new_callable=AsyncMock
                ) as m_confirm:
                    await _handle_message_movie(mock_update, mock_context, "Inception 2010")
        m_pipe.assert_called_once()
        m_confirm.assert_not_called()

    @pytest.mark.asyncio
    async def test_movie_low_confidence_asks_before_download(
        self, mock_update, mock_context
    ):
        """Low-confidence movie resolution shows confirmation, no pipeline yet."""
        from title_resolution import ResolvedTitle
        from telegram_bot import _handle_message_movie

        low = ResolvedTitle(
            media_type="movie",
            canonical_title="Inception",
            year=2010,
            confidence="low",
            issue="year_mismatch",
            user_parsed={"media_type": "movie", "movie_name": "Inception", "year": 2000},
        )
        with patch(
            "telegram_bot.resolve_input_async",
            new_callable=AsyncMock,
            return_value=low,
        ):
            with patch(
                "telegram_bot._run_movie_pipeline", new_callable=AsyncMock
            ) as m_pipe:
                with patch(
                    "telegram_bot._send_title_confirmation", new_callable=AsyncMock
                ) as m_confirm:
                    await _handle_message_movie(mock_update, mock_context, "Inception 2000")
        m_confirm.assert_called_once()
        m_pipe.assert_not_called()

    @pytest.mark.asyncio
    async def test_title_use_callback_runs_movie_pipeline(self, mock_update, mock_context):
        """title_use callback resumes movie pipeline with suggested identity."""
        import telegram_bot as tb
        from telegram_bot import _handle_title_callback
        from telegram import CallbackQuery

        pending = {
            "token": "abc123",
            "media_type": "movie",
            "raw": "Inception 2000",
            "user_parsed": {"media_type": "movie", "movie_name": "Inception", "year": 2000},
            "suggestion": {
                "media_type": "movie",
                "canonical_title": "Inception",
                "movie_name": "Inception",
                "year": 2010,
            },
            "alternatives": [],
            "latency": {"timings_ms": {}, "phase_timings_ms": {}},
            "req_started": 0.0,
        }
        mock_context.user_data["pending_title"] = pending

        query = Mock(spec=CallbackQuery)
        query.data = "title_use:abc123"
        query.answer = AsyncMock()
        query.message = mock_update.message

        wrapped = tb._wrap_callback_update(query)
        with patch("telegram_bot._run_movie_pipeline", new_callable=AsyncMock) as m_pipe:
            await _handle_title_callback(
                mock_update, mock_context, query, "title_use:abc123", wrapped
            )
        m_pipe.assert_called_once()
        assert mock_context.user_data.get("pending_title") is None
    
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
    
    @pytest.mark.skip(reason="send_tier_list_results was removed from telegram_bot")
    @pytest.mark.asyncio
    async def test_file_not_found_tier_list(self, mock_update, mock_context, temp_dir):
        """Test file not found errors - missing tier list files."""
    
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
        """OpenAI failures in normalization return None (bot falls back to parsed title)."""
        import telegram_bot as tb

        with patch.object(tb, "resolve_openai_api_key", return_value="sk-test"):
            with patch("openai.OpenAI") as m_oa:
                m_oa.return_value.chat.completions.create.side_effect = RuntimeError("API Error")
                result = await tb._normalize_with_chatgpt("some show s1 e1")
        assert result is None
    
    @pytest.mark.skip(reason="send_tier_list_results was removed from telegram_bot")
    @pytest.mark.asyncio
    async def test_invalid_data_corrupted_csv(self, mock_update, mock_context, temp_dir):
        """Test invalid data - corrupted CSV files."""
    
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
    
    @pytest.mark.skip(reason="send_tier_list_results was removed from telegram_bot")
    @pytest.mark.asyncio
    async def test_empty_tier_list(self, mock_update, mock_context, temp_dir):
        """Test invalid data - empty tier lists."""


class TestWordListExamples:
    """Word tier lists show subtitle examples like phrasal verbs."""

    def test_format_word_list_includes_example(self):
        from telegram_bot import _format_word_list

        text = _format_word_list(
            "Test Show",
            1,
            1,
            [("beating", "избиение", "Stop the beating right now.")],
        )
        assert "beating" in text
        assert "избиение" in text
        assert "Stop the beating" in text
        assert "personal dictionary" in text

    def test_format_word_list_omits_dictionary_hint_when_empty(self):
        from telegram_bot import _format_word_list

        text = _format_word_list("Test Show", 1, 1, [])
        assert "personal dictionary" not in text

    def test_load_translation_pairs_reads_example_en(self, temp_dir):
        from telegram_bot import _load_translation_pairs_csv

        p = temp_dir / "tier_1_translations.csv"
        with open(p, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["word", "translation_ru", "example_en"])
            w.writerow(["maid", "служанка", "The maid left early."])
        rows = _load_translation_pairs_csv(p)
        assert rows == [("maid", "служанка", "The maid left early.")]

    def test_fill_missing_word_examples_from_srt(self, temp_dir):
        from telegram_bot import _attach_subtitle_examples

        srt = temp_dir / "ep.srt"
        srt.write_text(
            "1\n00:00:00,000 --> 00:00:01,000\nThe maid left early.\n\n",
            encoding="utf-8",
        )
        rows = _attach_subtitle_examples([("maid", "служанка", "")], srt)
        assert rows[0][2] == "The maid left early."

    def test_attach_subtitle_examples_prefers_srt_over_stale_csv(self, temp_dir):
        from telegram_bot import _attach_subtitle_examples

        srt = temp_dir / "ep.srt"
        srt.write_text(
            "1\n00:00:00,000 --> 00:00:01,000\nThe maid left early.\n\n",
            encoding="utf-8",
        )
        rows = _attach_subtitle_examples(
            [("maid", "служанка", "old csv line")], srt
        )
        assert rows[0][2] == "The maid left early."

    def test_format_word_entry_line_shows_dictionary_icon_when_saved(self):
        from telegram_bot import _format_word_entry_line

        line = _format_word_entry_line(1, "maid", "служанка", "", is_saved=True)
        assert "maid 📚" in line

    def test_format_word_entry_line_makes_clickable_link(self):
        from telegram_bot import _format_word_entry_line

        line = _format_word_entry_line(
            1,
            "legion",
            "Легион",
            "",
            word_link="https://t.me/mybot?start=dw_abc123",
        )
        assert "[legion](https://t.me/mybot?start=dw_abc123)" in line


class TestMyWordsFeature:
    def test_show_my_words_text_trigger_ru(self):
        from telegram_bot import _is_show_my_words_text

        assert _is_show_my_words_text("показать мои слова")
        assert _is_show_my_words_text("мои слова")
        assert not _is_show_my_words_text("Fallout")

    @pytest.mark.asyncio
    async def test_show_my_words_empty_dictionary_message(self, mock_update, mock_context):
        import telegram_bot as tb

        with patch.object(tb, "_safe_user_id", return_value=12345):
            with patch.object(tb, "_get_user_dictionary", return_value={}):
                await tb.show_my_words(mock_update, mock_context)
        assert mock_update.message.reply_text.called
        text = mock_update.message.reply_text.call_args[0][0]
        assert "Личный словарь пока пуст" in text

    def test_deep_link_for_word_token(self):
        from telegram_bot import _deep_link_for_word_token

        link = _deep_link_for_word_token("mybot", "abc123")
        assert link == "https://t.me/mybot?start=dw_abc123"

    def test_format_my_words_list_includes_clickable_links(self):
        from telegram_bot import _format_my_words_list

        text = _format_my_words_list(
            [("legion", "a large military unit", "The legion marched.")],
            saved_keys={"legion::a large military unit"},
            word_tokens={"legion::a large military unit": "tok1"},
            bot_username="mybot",
        )
        assert "[legion 📚](https://t.me/mybot?start=dw_tok1)" in text
        assert "personal dictionary" in text

    def test_render_my_words_view_drops_removed_entries(self):
        from telegram_bot import _render_word_view_text

        view = {
            "kind": "my_words",
            "rows": [
                ("alpha", "first", ""),
                ("beta", "second", ""),
            ],
        }
        text = _render_word_view_text(
            view,
            saved_keys={"alpha::first"},
            bot_username="mybot",
        )
        assert "alpha" in text
        assert "beta" not in text
        assert "Saved words: 1" in text

    @pytest.mark.asyncio
    async def test_dictionary_deep_link_refreshes_my_words_anchor(
        self, mock_update, mock_context
    ):
        import telegram_bot as tb

        mock_context.user_data["word_list_anchor"] = {
            "chat_id": 1,
            "message_id": 99,
            "view": {
                "kind": "my_words",
                "rows": [("legion", "a large military unit", "")],
            },
        }
        mock_context.bot = Mock()
        mock_context.bot.edit_message_text = AsyncMock()
        mock_context.bot.username = "mybot"
        mock_update.message.delete = AsyncMock()

        with patch.object(tb, "_safe_user_id", return_value=12345):
            with patch.object(
                tb,
                "_toggle_dictionary_word_by_token",
                return_value=True,
            ) as m_toggle:
                with patch.object(
                    tb,
                    "_get_user_dictionary",
                    return_value={},
                ):
                    await tb._handle_dictionary_deep_link(
                        mock_update, mock_context, "tok1"
                    )
        m_toggle.assert_called_once_with(12345, "tok1")
        mock_context.bot.edit_message_text.assert_called_once()
        edited = mock_context.bot.edit_message_text.call_args.kwargs["text"]
        assert "empty" in edited.lower()


class TestEpisodeDirResolution:
    def test_resolve_episode_dir_from_translation_info(self, temp_dir, monkeypatch):
        import json
        import telegram_bot as tb

        monkeypatch.setattr(tb, "BASE_DIR", temp_dir)
        monkeypatch.setattr(tb, "TIERLIST_BASE", temp_dir / "Tier_lists")
        monkeypatch.setattr(tb, "TRANSLATIONS_BASE", temp_dir / "translations")

        tier_dir = temp_dir / "Tier_lists" / "Euphoria" / "Season 1" / "6"
        tier_dir.mkdir(parents=True)
        (tier_dir / "tier_1_hard_usable_words.csv").write_text(
            "word,series_frequency,english_frequency,vocabulary_level\nx,1,2,C1\n",
            encoding="utf-8",
        )
        (tier_dir / "episode_info.json").write_text(
            json.dumps(
                {
                    "series": "Euphoria",
                    "season_number": 1,
                    "episode_number": 6,
                    "subtitle_file": "euphoria_s1_e6.srt",
                }
            ),
            encoding="utf-8",
        )

        trans_dir = temp_dir / "translations" / "Euphoria S1 E6" / "Season 1" / "1"
        trans_dir.mkdir(parents=True)
        (trans_dir / "translation_info.json").write_text(
            json.dumps(
                {
                    "series": "Euphoria S1 E6",
                    "season_number": 1,
                    "episode_number": 1,
                    "source_subtitle": "euphoria_s1_e6.srt",
                }
            ),
            encoding="utf-8",
        )

        ctx = Mock()
        ctx.user_data = {}
        resolved = tb._resolve_episode_dir(trans_dir, ctx)
        assert resolved == tier_dir.resolve()

    @pytest.mark.asyncio
    async def test_reply_bot_message_falls_back_without_markdown(self, mock_update):
        from telegram.error import BadRequest
        import telegram_bot as tb

        mock_update.message.reply_text = AsyncMock(
            side_effect=[BadRequest("parse error"), None]
        )
        await tb._reply_bot_message(mock_update, text="*bold* word", parse_mode="Markdown")
        assert mock_update.message.reply_text.call_count == 2
        assert mock_update.message.reply_text.call_args_list[1][1]["parse_mode"] is None


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
