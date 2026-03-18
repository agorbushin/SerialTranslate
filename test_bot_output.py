#!/usr/bin/env python3
"""
Test bot output using ChatGPT to validate that responses don't contain:
- Names
- Fictional entities
- Swear words
- Simple/common words
"""

import json
import os
import csv
from pathlib import Path
from typing import Dict, List, Optional
from openai import OpenAI
import argparse


def load_swear_words() -> set:
    """Load swear words from filter."""
    swear_words_file = Path(__file__).parent / "filters" / "swear_words.csv"
    swear_words = set()
    if swear_words_file.exists():
        try:
            with open(swear_words_file, 'r', encoding='utf-8') as f:
                reader = csv.reader(f)
                for row in reader:
                    if row:
                        swear_words.add(row[0].lower().strip())
        except Exception as e:
            print(f"Warning: Could not load swear words: {e}")
    return swear_words


def load_common_words() -> set:
    """Load common/easy words from filters."""
    common_words = set()
    
    # Load easy_words.csv
    easy_words_file = Path(__file__).parent / "filters" / "easy_words.csv"
    if easy_words_file.exists():
        try:
            with open(easy_words_file, 'r', encoding='utf-8') as f:
                reader = csv.reader(f)
                for row in reader:
                    if row:
                        common_words.add(row[0].lower().strip())
        except Exception as e:
            print(f"Warning: Could not load easy words: {e}")
    
    # Load oxford_3000.csv
    oxford_file = Path(__file__).parent / "filters" / "oxford_3000.csv"
    if oxford_file.exists():
        try:
            with open(oxford_file, 'r', encoding='utf-8') as f:
                reader = csv.reader(f)
                for row in reader:
                    if row:
                        common_words.add(row[0].lower().strip())
        except Exception as e:
            print(f"Warning: Could not load Oxford words: {e}")
    
    return common_words


def format_tier_list_for_testing(tier_file: Path, approach: str = "frequency", 
                                 user_level: Optional[str] = None) -> str:
    """Format tier list CSV as a bot message for testing.
    
    This mimics the exact format that send_tier_list_results() sends to users.
    
    Args:
        tier_file: Path to tier CSV file
        approach: "frequency" or "cefr"
        user_level: User level (A, B, C) for frequency approach, or CEFR level for cefr approach
    """
    if not tier_file.exists():
        return ""
    
    words_data = []
    try:
        with open(tier_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                words_data.append(row)
    except Exception as e:
        print(f"Error reading tier file: {e}")
        return ""
    
    if not words_data:
        return ""
    
    # Filter out names and fantasy entities (matching bot behavior)
    words_data = [row for row in words_data if not row.get('is_name_or_fantasy', '').strip()]
    
    # Filter by vocabulary_level based on user_level (matching bot behavior)
    # Level C (Advanced): Show only C1, C2, and N/A words
    # Level B (Intermediate): Show B1, B2, C1, C2, and N/A words
    # Level A (Beginner): Show all words
    if approach == "frequency" and user_level:
        original_count = len(words_data)
        if user_level.upper() == 'C':
            # Advanced: Only C1, C2, and N/A
            allowed_levels = {'C1', 'C2', 'N/A', ''}
            words_data = [row for row in words_data if row.get('vocabulary_level', 'N/A').upper() in allowed_levels]
        elif user_level.upper() == 'B':
            # Intermediate: B1, B2, C1, C2, and N/A (hide A1, A2)
            allowed_levels = {'B1', 'B2', 'C1', 'C2', 'N/A', ''}
            words_data = [row for row in words_data if row.get('vocabulary_level', 'N/A').upper() in allowed_levels]
        # Level A: Show all words (no filtering)
    
    if not words_data:
        return ""
    
    # Format like bot output (matching send_tier_list_results format)
    if approach == "cefr" and user_level:
        response = "📊 Hard Words (Level {}+): {}\n\n".format(user_level, len(words_data))
    else:
        level_names = {'A': 'Beginner', 'B': 'Intermediate', 'C': 'Advanced'}
        level_name = level_names.get(user_level.upper() if user_level else 'B', 'Unknown')
        response = f"📊 Hard Usable Words (Level {user_level or 'B'} - {level_name}): {len(words_data)}\n\n"
    response += "Top 10 Words to Learn:\n\n"
    
    for i, word_data in enumerate(words_data[:10], 1):
        word = word_data.get('word', '')
        translation = word_data.get('translation', 'N/A')
        example = word_data.get('example_en', '')
        
        response += f"{i}. {word} → {translation}\n"
        if example and example.strip():
            # Truncate long examples (matching bot behavior)
            example_short = example[:60] + "..." if len(example) > 60 else example
            response += f'   "{example_short}"\n'
        response += "\n"
    
    if len(words_data) > 10:
        response += f"\n... and {len(words_data) - 10} more words.\n"
        response += f"\nUse /full to get the complete list.\n"
    
    return response


def validate_bot_output_with_chatgpt(
    bot_output: str,
    series_name: str,
    openai_client: OpenAI,
    swear_words: set,
    common_words: set
) -> Dict:
    """Use ChatGPT to validate bot output.
    
    Args:
        bot_output: The formatted bot message
        series_name: Name of the series
        openai_client: OpenAI client
        swear_words: Set of swear words to check
        common_words: Set of common words to check
        
    Returns:
        Dictionary with validation results
    """
    
    # Extract words from bot output
    words_in_output = []
    lines = bot_output.split('\n')
    for line in lines:
        # Look for lines like "1. word → translation"
        if '→' in line and '.' in line:
            try:
                word_part = line.split('→')[0].strip()
                # Extract word (after number and dot)
                if '.' in word_part:
                    word = word_part.split('.', 1)[1].strip()
                    words_in_output.append(word)
            except:
                pass
    
    words_text = ", ".join(words_in_output[:20])  # Limit to first 20 for prompt
    
    prompt = f"""You are validating a bot output for a TV series vocabulary learning system.

SERIES: {series_name}

BOT OUTPUT:
{bot_output}

WORDS IN OUTPUT:
{words_text}

Please analyze this bot output and check for the following issues:

1. **NAMES**: Are there any character names, person names, or proper nouns that should NOT be in a vocabulary learning list?
   - Character names (e.g., "Barry", "Chachi", "Joey", "Monica", "Sage", "Zoe", "Vicky")
   - Person names (first names, last names)
   - Any word that is primarily used as a name in this series

2. **FICTIONAL ENTITIES**: Are there any made-up words or fantasy-specific entities?
   - Series-specific made-up words (e.g., "doraki" in Game of Thrones)
   - Fantasy creatures or entities that don't exist in real English
   - Words that are not learnable English vocabulary

3. **SWEAR WORDS**: Are there any profanity or inappropriate words?
   - Check against common swear words
   - Words that are inappropriate for educational content

4. **SIMPLE/COMMON WORDS**: Are there any words that are too simple or common?
   - Basic vocabulary that most English learners already know
   - Very common words that shouldn't be in an "advanced" word list
   - Words from basic English word lists (Oxford 3000, easy words)

Return a JSON object with this structure:
{{
    "is_valid": true/false,
    "issues": [
        {{
            "type": "name" | "fictional_entity" | "swear_word" | "simple_word",
            "word": "the problematic word",
            "reason": "explanation of why this is an issue"
        }}
    ],
    "summary": "Overall assessment of the bot output quality",
    "score": 0-100  // Quality score (100 = perfect, 0 = many issues)
}}

Be strict but fair. Only flag genuine issues. Real English words that are learnable vocabulary should NOT be flagged, even if they appear frequently in the series."""

    try:
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a strict validator for educational vocabulary content. Always respond with valid JSON."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
            response_format={"type": "json_object"}
        )
        
        result = json.loads(response.choices[0].message.content)
        
        # Also do a quick check for swear words and common words
        additional_issues = []
        for word in words_in_output:
            word_lower = word.lower()
            if word_lower in swear_words:
                additional_issues.append({
                    "type": "swear_word",
                    "word": word,
                    "reason": "Swear word detected in filter list"
                })
            if word_lower in common_words:
                additional_issues.append({
                    "type": "simple_word",
                    "word": word,
                    "reason": "Common/easy word detected in filter list"
                })
        
        # Merge additional issues
        if additional_issues:
            if "issues" not in result:
                result["issues"] = []
            result["issues"].extend(additional_issues)
            # Update validity if issues found
            if result.get("is_valid", True) and additional_issues:
                result["is_valid"] = False
        
        return result
        
    except Exception as e:
        print(f"Error validating with ChatGPT: {e}")
        import traceback
        traceback.print_exc()
        return {
            "is_valid": False,
            "issues": [{"type": "error", "word": "", "reason": str(e)}],
            "summary": "Error during validation",
            "score": 0
        }


def test_episode(episode_dir: Path, api_key: str, series_name: Optional[str] = None, 
                approach: str = "frequency", user_level: Optional[str] = None) -> Dict:
    """Test a single episode's tier list output.
    
    Args:
        episode_dir: Path to episode directory
        api_key: OpenAI API key
        series_name: Optional series name (will try to get from episode_info.json)
        approach: "frequency" or "cefr"
        user_level: CEFR level if approach is "cefr" (A1, A2, B1, B2, C1, C2)
        
    Returns:
        Validation results dictionary
    """
    # Determine which tier file to use
    if approach == "cefr" and user_level:
        tier_file = episode_dir / f"hard_words_for_{user_level}.csv"
    else:
        tier_file = episode_dir / "tier_1_hard_usable_words.csv"
    
    if not tier_file.exists():
        return {
            "error": f"Tier file not found: {tier_file}",
            "is_valid": False,
            "approach": approach,
            "user_level": user_level
        }
    
    # Get series name and approach info from episode info
    episode_info_file = episode_dir / "episode_info.json"
    if episode_info_file.exists():
        try:
            with open(episode_info_file, 'r', encoding='utf-8') as f:
                info = json.load(f)
                if not series_name:
                    series_name = info.get('series', 'Unknown')
                # Override approach/user_level from episode info if available
                if info.get('approach') == 'cefr':
                    approach = 'cefr'
                    user_level = info.get('user_level', user_level)
        except:
            if not series_name:
                series_name = "Unknown"
    else:
        if not series_name:
            series_name = "Unknown"
    
    # Format bot output (update format for CEFR approach)
    bot_output = format_tier_list_for_testing(tier_file, approach=approach, user_level=user_level)
    
    if not bot_output:
        return {
            "error": "No words in tier list",
            "is_valid": False,
            "approach": approach,
            "user_level": user_level
        }
    
    # Load filters
    swear_words = load_swear_words()
    common_words = load_common_words()
    
    # Initialize OpenAI client
    openai_client = OpenAI(api_key=api_key)
    
    # Validate with ChatGPT
    print(f"Testing: {series_name} - {episode_dir.name}")
    print("="*60)
    validation_result = validate_bot_output_with_chatgpt(
        bot_output, series_name, openai_client, swear_words, common_words
    )
    
    return {
        "episode_dir": str(episode_dir),
        "series_name": series_name,
        "bot_output": bot_output,
        "validation": validation_result,
        "approach": approach,
        "user_level": user_level
    }


def main():
    parser = argparse.ArgumentParser(description="Test bot output using ChatGPT validation")
    parser.add_argument('--episode-dir', '-e', type=str,
                       help='Path to episode directory to test')
    parser.add_argument('--tierlist-dir', '-t', type=str,
                       default='tierlist',
                       help='Path to tierlist directory (default: tierlist)')
    parser.add_argument('--series', '-s', type=str,
                       help='Test all episodes for a specific series')
    parser.add_argument('--api-key', type=str,
                       default=os.environ.get("OPENAI_API_KEY", ""),
                       help='OpenAI API key (default: OPENAI_API_KEY env)')
    parser.add_argument('--all', action='store_true',
                       help='Test all episodes in tierlist directory')
    parser.add_argument('--approach', type=str, choices=['frequency', 'cefr'],
                       default='frequency',
                       help='Approach to test (frequency or cefr)')
    parser.add_argument('--level', type=str,
                       help='Level to test: A/B/C for frequency approach, or A1/A2/B1/B2/C1/C2 for cefr approach')
    parser.add_argument('--test-cefr', action='store_true',
                       help='Test all CEFR files found in tierlist directory')
    
    args = parser.parse_args()
    
    # Validate arguments
    if args.approach == 'cefr' and not args.level and not args.test_cefr:
        parser.error("--level is required when --approach is cefr (or use --test-cefr to test all)")
    
    base_dir = Path(__file__).parent
    
    results = []
    
    if args.test_cefr:
        # Test all CEFR files found
        tierlist_dir = base_dir / args.tierlist_dir
        if not tierlist_dir.exists():
            print(f"Error: Tierlist directory not found: {tierlist_dir}")
            return
        
        cefr_levels = ['A1', 'A2', 'B1', 'B2', 'C1', 'C2']
        for series_dir in sorted(tierlist_dir.iterdir()):
            if series_dir.is_dir():
                series_name = series_dir.name
                for episode_dir in sorted(series_dir.iterdir()):
                    if episode_dir.is_dir():
                        # Check for CEFR files
                        for level in cefr_levels:
                            cefr_file = episode_dir / f"hard_words_for_{level}.csv"
                            if cefr_file.exists():
                                result = test_episode(episode_dir, args.api_key, series_name, 
                                                     approach='cefr', user_level=level)
                                results.append(result)
    
    elif args.episode_dir:
        # Test single episode
        episode_dir = base_dir / args.episode_dir
        result = test_episode(episode_dir, args.api_key, approach=args.approach, 
                             user_level=args.level)
        results.append(result)
        
    elif args.series:
        # Test all episodes for a series
        tierlist_dir = base_dir / args.tierlist_dir
        series_dir = tierlist_dir / args.series
        
        if not series_dir.exists():
            print(f"Error: Series directory not found: {series_dir}")
            return
        
        for episode_dir in sorted(series_dir.iterdir()):
            if episode_dir.is_dir():
                result = test_episode(episode_dir, args.api_key, args.series, 
                                     approach=args.approach, user_level=args.level)
                results.append(result)
                
    elif args.all:
        # Test all episodes
        tierlist_dir = base_dir / args.tierlist_dir
        
        if not tierlist_dir.exists():
            print(f"Error: Tierlist directory not found: {tierlist_dir}")
            return
        
        for series_dir in sorted(tierlist_dir.iterdir()):
            if series_dir.is_dir():
                series_name = series_dir.name
                for episode_dir in sorted(series_dir.iterdir()):
                    if episode_dir.is_dir():
                        result = test_episode(episode_dir, args.api_key, series_name,
                                             approach=args.approach, user_level=args.level)
                        results.append(result)
    else:
        parser.print_help()
        return
    
    # Print results
    print("\n" + "="*70)
    print("VALIDATION RESULTS SUMMARY")
    print("="*70)
    
    total_tests = len(results)
    valid_count = sum(1 for r in results if r.get("validation", {}).get("is_valid", False))
    invalid_count = total_tests - valid_count
    
    print(f"\nTotal tests: {total_tests}")
    print(f"✅ Valid: {valid_count}")
    print(f"❌ Invalid: {invalid_count}")
    print()
    
    for result in results:
        episode_name = Path(result.get("episode_dir", "")).name
        series_name = result.get("series_name", "Unknown")
        validation = result.get("validation", {})
        
        is_valid = validation.get("is_valid", False)
        score = validation.get("score", 0)
        issues = validation.get("issues", [])
        
        status = "✅" if is_valid else "❌"
        approach = result.get("approach", "frequency")
        user_level = result.get("user_level", None)
        approach_str = f"CEFR-{user_level}" if approach == "cefr" and user_level else approach
        print(f"{status} {series_name} - {episode_name} [{approach_str}] (Score: {score}/100)")
        
        if issues:
            print(f"   Issues found: {len(issues)}")
            for issue in issues[:5]:  # Show first 5 issues
                print(f"   - [{issue.get('type', 'unknown')}] {issue.get('word', 'N/A')}: {issue.get('reason', '')}")
            if len(issues) > 5:
                print(f"   ... and {len(issues) - 5} more issues")
        print()
    
    # Save detailed results to JSON
    output_file = base_dir / "test_results.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    
    print(f"Detailed results saved to: {output_file}")


if __name__ == "__main__":
    main()
