# Bot Output Tester

This tool validates bot output using ChatGPT to ensure that the vocabulary lists sent to users don't contain:
- **Names** (character names, person names, proper nouns)
- **Fictional entities** (made-up words, fantasy-specific terms)
- **Swear words** (profanity, inappropriate language)
- **Simple/common words** (basic vocabulary that learners already know)

## Usage

### Test a single episode:
```bash
python3 test_bot_output.py --episode-dir "tierlist/The Boys/S04E08"
```

### Test all episodes for a specific series:
```bash
python3 test_bot_output.py --series "The Boys"
```

### Test all episodes:
```bash
python3 test_bot_output.py --all
```

### Custom API key:
```bash
python3 test_bot_output.py --episode-dir "tierlist/Friends/S01E01" --api-key "your-api-key"
```

## Output

The tester provides:
1. **Console output** with validation results for each episode
2. **JSON file** (`test_results.json`) with detailed validation data

### Validation Results Include:
- **is_valid**: Boolean indicating if the output passes validation
- **score**: Quality score (0-100, where 100 is perfect)
- **issues**: List of problems found, categorized by type:
  - `name`: Character names or proper nouns
  - `fictional_entity`: Made-up words or fantasy entities
  - `swear_word`: Profanity or inappropriate words
  - `simple_word`: Too common or basic vocabulary
- **summary**: Overall assessment from ChatGPT

## Example Output

```
Testing: The Boys - S04E08
============================================================

======================================================================
VALIDATION RESULTS SUMMARY
======================================================================

Total tests: 1
✅ Valid: 0
❌ Invalid: 1

❌ The Boys - S04E08 (Score: 40/100)
   Issues found: 8
   - [name] neuman: Neuman is a character name...
   - [name] annie: Annie is a character name...
   - [name] hughie: Hughie is a character name...
   ...
```

## How It Works

1. **Loads tier list CSV** from the episode directory
2. **Formats it** like the bot's output message
3. **Sends to ChatGPT** with a validation prompt
4. **Checks filters** (swear words, common words) locally
5. **Combines results** from ChatGPT and local filters
6. **Generates report** with issues and quality score

## Integration with Two-Stage Filtering

This tester validates the **final output** that users see. It works in conjunction with the two-stage filtering system:

- **Stage 1** (in `translate_words.py`): Filters names BEFORE translation
- **Stage 2**: Translates remaining words
- **This tester**: Validates the final output to catch any names that slipped through

## Continuous Testing

You can run this tester:
- After creating new tier lists
- Before deploying bot updates
- As part of CI/CD pipeline
- To verify fixes after addressing issues

## Improving Results

If the tester finds issues:
1. Check if the two-stage filtering in `translate_words.py` is working correctly
2. Verify that `filter_names_and_fantasy_entities()` in `telegram_bot.py` is catching names
3. Review the capital letter detection logic
4. Check if swear words or common words need to be added to filter CSVs
