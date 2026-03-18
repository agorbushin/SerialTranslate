# SerialTranslate Test Suite

This directory contains comprehensive tests for the SerialTranslate system as specified in the QA Test Plan.

## Test Structure

### Test Files

1. **`conftest.py`** - Pytest fixtures and test utilities
   - Mock Telegram Update/Context objects
   - Mock OpenAI clients
   - Sample data fixtures (subtitles, tier files, episode directories)
   - Utility functions for creating test data

2. **`test_telegram_bot.py`** - Tests for Telegram bot functionality
   - Command handlers (`/start`, `/next`, `/full`, `/phrasal`)
   - Message handling (series name input, response formatting, context management)
   - Error handling (file not found, API errors, invalid data)

3. **`test_translation.py`** - Tests for translation functionality
   - Translation functions (`translate_words_with_context`, `translate_tier_file`, `translate_episode`)
   - Translation quality (validation, retry logic, parallel processing)
   - Name/fantasy entity filtering (STAGE 1 and STAGE 1.5)
   - Edge cases (empty inputs, special characters, API limits)

4. **`test_tierlist_creation.py`** - Tests for tier list creation
   - Categorization logic (`categorize_words` function)
   - File generation (`save_tierlist_results` function)
   - Data integrity (word frequency mapping, word coverage, sorting)
   - Edge cases (empty subtitles, special characters, large files)

5. **`test_integration.py`** - End-to-end integration tests
   - Full workflow tests (Subtitle → Tier list → Translation → Bot response)
   - Error propagation tests
   - Workflow integration scenarios

### Test Data

- **`test_data/sample_subtitle.srt`** - Sample subtitle file for testing

## Running Tests

### Prerequisites

```bash
pip install pytest pytest-asyncio
```

### Run All Tests

```bash
pytest tests/ -v
```

### Run Specific Test File

```bash
pytest tests/test_telegram_bot.py -v
pytest tests/test_translation.py -v
pytest tests/test_tierlist_creation.py -v
pytest tests/test_integration.py -v
```

### Run Specific Test Class

```bash
pytest tests/test_telegram_bot.py::TestCommandHandlers -v
```

### Run Specific Test

```bash
pytest tests/test_telegram_bot.py::TestCommandHandlers::test_start_command -v
```

## Test Coverage

### Block 1: Telegram Bot Answers
- ✅ Command handlers (`/start`, `/next`, `/full`, `/phrasal`)
- ✅ Message handling (series name input, response formatting, context management)
- ✅ Error handling (file not found, API errors, invalid data)

### Block 2: Translation
- ✅ Translation functions (`translate_words_with_context`, `translate_tier_file`, `translate_episode`)
- ✅ Translation quality (validation, retry logic)
- ✅ Name/fantasy entity filtering (STAGE 1 and STAGE 1.5)
- ✅ Edge cases (empty inputs, special characters, API limits)

### Block 3: Tier List Creation
- ✅ Categorization logic (all 5 tiers)
- ✅ File generation (CSV files, episode_info.json, README.md)
- ✅ Data integrity (word frequency mapping, word coverage, sorting)
- ✅ Edge cases (empty subtitles, special characters)

### Integration Tests
- ✅ Full workflow tests
- ✅ Error propagation tests
- ✅ Workflow integration scenarios

## Notes

- Tests use mocks for external dependencies (OpenAI API, Telegram API)
- Tests use temporary directories for file operations
- All tests are designed to be independent and can run in any order
- Some tests may require network access if not properly mocked (integration tests)

## Troubleshooting

If you encounter issues with pytest plugins (e.g., pytest-recording), you can disable them:

```bash
pytest tests/ -v -p no:pytest-recording
```

Or create a `pytest.ini` file:

```ini
[pytest]
addopts = -p no:pytest-recording
```
