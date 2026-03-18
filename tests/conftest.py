#!/usr/bin/env python3
"""
Pytest fixtures and test utilities for SerialTranslate test suite.
"""

import pytest
import tempfile
import shutil
import csv
import json
from pathlib import Path
from unittest.mock import Mock, AsyncMock, MagicMock
from typing import Dict, List
from collections import Counter

# Import bot modules
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from telegram import Update, Message, User, Chat, Document, CallbackQuery
from telegram.ext import ContextTypes
from openai import OpenAI, AsyncOpenAI


# ============================================================================
# FIXTURES - Test Data
# ============================================================================

@pytest.fixture
def temp_dir():
    """Create a temporary directory for tests."""
    temp_path = Path(tempfile.mkdtemp())
    yield temp_path
    shutil.rmtree(temp_path, ignore_errors=True)


@pytest.fixture
def sample_subtitle_file(temp_dir):
    """Create a sample subtitle file (SRT format)."""
    subtitle_file = temp_dir / "test_series.srt"
    subtitle_content = """1
00:00:01,000 --> 00:00:03,000
This is a test subtitle with example words.

2
00:00:04,000 --> 00:00:06,000
Another line of dialogue for testing.

3
00:00:07,000 --> 00:00:09,000
Here is a sample phrase with more words.
"""
    subtitle_file.write_text(subtitle_content, encoding='utf-8')
    return subtitle_file


@pytest.fixture
def sample_tier_1_file(temp_dir):
    """Create a sample tier_1 CSV file."""
    tier_file = temp_dir / "tier_1_hard_usable_words.csv"
    words_data = [
        {
            'word': 'example',
            'series_frequency': '5',
            'english_frequency': '1000000',
            'vocabulary_level': 'B1',
            'translation': '',
            'example_en': '',
            'example_translated': '',
            'is_name_or_fantasy': ''
        },
        {
            'word': 'test',
            'series_frequency': '3',
            'english_frequency': '2000000',
            'vocabulary_level': 'A2',
            'translation': '',
            'example_en': '',
            'example_translated': '',
            'is_name_or_fantasy': ''
        },
        {
            'word': 'sample',
            'series_frequency': '2',
            'english_frequency': '500000',
            'vocabulary_level': 'B2',
            'translation': 'пример',
            'example_en': 'This is a sample',
            'example_translated': 'Это пример',
            'is_name_or_fantasy': ''
        }
    ]
    
    fieldnames = ['word', 'series_frequency', 'english_frequency', 'vocabulary_level',
                  'translation', 'example_en', 'example_translated', 'is_name_or_fantasy']
    
    with open(tier_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(words_data)
    
    return tier_file


@pytest.fixture
def sample_episode_dir(temp_dir, sample_tier_1_file):
    """Create a sample episode directory with tier list and metadata."""
    episode_dir = temp_dir / "S01E01"
    episode_dir.mkdir(parents=True, exist_ok=True)
    
    # Copy tier file
    shutil.copy(sample_tier_1_file, episode_dir / "tier_1_hard_usable_words.csv")
    
    # Create episode_info.json
    episode_info = {
        'series': 'Test Series',
        'season': 'Season 1',
        'episode': 'Episode 01',
        'subtitle_file': 'test_series.srt',
        'analysis_date': '2025-01-18T23:30:00',
        'thresholds': {
            'series_threshold': 2,
            'english_threshold': 5000000,
            'max_english_freq': 5000000
        },
        'word_counts': {
            'tier_1_hard_usable': 3,
            'tier_2_random': 0,
            'tier_3_common': 0,
            'tier_4_rare_in_series': 0,
            'tier_5_filtered': 0
        }
    }
    (episode_dir / "episode_info.json").write_text(
        json.dumps(episode_info, indent=2, ensure_ascii=False),
        encoding='utf-8'
    )
    
    return episode_dir


@pytest.fixture
def sample_english_freq_data():
    """Sample English frequency data."""
    return {
        'example': 1000000,
        'test': 2000000,
        'sample': 500000,
        'common': 10000000,
        'rare': 100000,
        'the': 50000000,
        'is': 40000000,
        'a': 45000000
    }


@pytest.fixture
def sample_series_freq_data():
    """Sample series frequency data."""
    return Counter({
        'example': 5,
        'test': 3,
        'sample': 2,
        'common': 10,
        'rare': 1
    })


@pytest.fixture
def sample_vocabulary_levels():
    """Sample vocabulary level data."""
    return {
        'example': 'B1',
        'test': 'A2',
        'sample': 'B2',
        'common': 'A1',
        'rare': 'C1'
    }


# ============================================================================
# FIXTURES - Telegram Bot Mocks
# ============================================================================

@pytest.fixture
def mock_update():
    """Create a mock Telegram Update object."""
    update = Mock(spec=Update)
    update.message = Mock(spec=Message)
    update.message.text = "Test Series"
    update.message.from_user = Mock(spec=User)
    update.message.from_user.id = 12345
    update.message.from_user.username = "test_user"
    update.message.reply_text = AsyncMock()
    update.message.reply_document = AsyncMock()
    update.message.reply_markdown = AsyncMock()
    update.effective_user = update.message.from_user
    update.effective_chat = Mock(spec=Chat)
    update.effective_chat.id = 12345
    return update


@pytest.fixture
def mock_context():
    """Create a mock Context object."""
    context = Mock(spec=ContextTypes.DEFAULT_TYPE)
    context.user_data = {}
    context.bot = Mock()
    context.bot.get_file = AsyncMock()
    return context


@pytest.fixture
def mock_callback_query(mock_update):
    """Create a mock CallbackQuery object."""
    query = Mock(spec=CallbackQuery)
    query.data = "full_list"
    query.answer = AsyncMock()
    query.message = mock_update.message
    query.edit_message_text = AsyncMock()
    query.from_user = mock_update.message.from_user
    return query


# ============================================================================
# FIXTURES - OpenAI Mocks
# ============================================================================

@pytest.fixture
def mock_openai_client():
    """Create a mock OpenAI client."""
    client = Mock(spec=OpenAI)
    client.chat = Mock()
    client.chat.completions = Mock()
    client.chat.completions.create = Mock()
    return client


@pytest.fixture
def mock_openai_response():
    """Create a mock OpenAI API response."""
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message = MagicMock()
    response.choices[0].message.content = json.dumps({
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
    return response


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def create_tier_file(directory: Path, tier_name: str, words: List[Dict]) -> Path:
    """Create a tier CSV file with given words."""
    tier_file = directory / f"{tier_name}.csv"
    
    if not words:
        # Create empty file with headers
        fieldnames = ['word', 'series_frequency', 'english_frequency', 'vocabulary_level']
        with open(tier_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
        return tier_file
    
    fieldnames = list(words[0].keys())
    with open(tier_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(words)
    
    return tier_file


def create_episode_info(directory: Path, series: str, season: str = None, 
                        episode: str = None) -> Path:
    """Create an episode_info.json file."""
    info = {
        'series': series,
        'season': season,
        'episode': episode,
        'subtitle_file': 'test.srt',
        'analysis_date': '2025-01-18T23:30:00',
        'thresholds': {
            'series_threshold': 2,
            'english_threshold': 5000000,
            'max_english_freq': 5000000
        },
        'word_counts': {
            'tier_1_hard_usable': 0,
            'tier_2_random': 0,
            'tier_3_common': 0,
            'tier_4_rare_in_series': 0,
            'tier_5_filtered': 0
        }
    }
    
    info_file = directory / "episode_info.json"
    info_file.write_text(
        json.dumps(info, indent=2, ensure_ascii=False),
        encoding='utf-8'
    )
    return info_file


def create_subtitle_file(directory: Path, filename: str, content: str = None) -> Path:
    """Create a subtitle file."""
    if content is None:
        content = """1
00:00:01,000 --> 00:00:03,000
This is a test subtitle.

2
00:00:04,000 --> 00:00:06,000
Another line of dialogue.
"""
    subtitle_file = directory / filename
    subtitle_file.write_text(content, encoding='utf-8')
    return subtitle_file
