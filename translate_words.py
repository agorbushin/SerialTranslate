#!/usr/bin/env python3
"""
Translate words from tier lists using ChatGPT API.
Uses subtitle context to provide series-specific translations and examples.
"""

import csv
import json
import os
import re
from pathlib import Path
from typing import List, Dict, Optional, Set
import argparse
import time
from openai import OpenAI, AsyncOpenAI
import asyncio


def filter_names_sync(words: List[str], subtitle_text: str, series_name: str, api_key: str) -> Set[str]:
    """Synchronous wrapper for filter_names_and_fantasy_entities.
    
    Args:
        words: List of words to check
        subtitle_text: Subtitle text for context
        series_name: Name of the series
        api_key: OpenAI API key
        
    Returns:
        Set of words that are names or fantasy entities
    """
    try:
        # Import the async function
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).parent))
        from telegram_bot import filter_names_and_fantasy_entities
        from openai import OpenAI
        
        # Create OpenAI client
        openai_client = OpenAI(api_key=api_key)
        
        # Run async function in event loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(
                filter_names_and_fantasy_entities(words, subtitle_text, series_name, openai_client)
            )
            return result
        finally:
            loop.close()
    except Exception as e:
        print(f"Error in ChatGPT name filtering: {e}")
        return set()


def filter_names_sync_with_reasons(words: List[str], subtitle_text: str, series_name: str, api_key: str) -> tuple[Set[str], Dict[str, str]]:
    """Synchronous wrapper for filter_names_and_fantasy_entities_with_reasons.
    
    Args:
        words: List of words to check
        subtitle_text: Subtitle text for context
        series_name: Name of the series
        api_key: OpenAI API key
        
    Returns:
        Tuple of (set of words that are names/fantasy entities, dict of word -> reason)
    """
    try:
        # Import the async function
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).parent))
        from telegram_bot import filter_names_and_fantasy_entities_with_reasons
        from openai import OpenAI
        
        # Create OpenAI client
        openai_client = OpenAI(api_key=api_key)
        
        # Run async function in event loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(
                filter_names_and_fantasy_entities_with_reasons(words, subtitle_text, series_name, openai_client)
            )
            return result
        finally:
            loop.close()
    except Exception as e:
        print(f"Error in ChatGPT name filtering: {e}")
        return set(), {}


def extract_examples_from_subtitle(subtitle_path: Path, words: Set[str], max_examples_per_word: int = 3) -> Dict[str, List[str]]:
    """Extract example sentences from subtitle file for given words.
    
    Args:
        subtitle_path: Path to subtitle file
        words: Set of words to find examples for
        max_examples_per_word: Maximum number of examples per word
        
    Returns:
        Dictionary mapping words to lists of example sentences
    """
    examples = {word: [] for word in words}
    
    if not subtitle_path.exists():
        return examples
    
    try:
        with open(subtitle_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        
        # Parse SRT format: extract subtitle text (lines that aren't numbers or timestamps)
        # Pattern: number, timestamp, text lines, blank line
        subtitle_blocks = re.split(r'\n\s*\n', content)
        
        for block in subtitle_blocks:
            lines = [line.strip() for line in block.split('\n') if line.strip()]
            if len(lines) < 3:
                continue
            
            # Skip number and timestamp lines, get text
            text_lines = []
            for line in lines:
                # Skip if it's a number or timestamp
                if re.match(r'^\d+$', line):
                    continue
                if re.match(r'\d{2}:\d{2}:\d{2}[,.]\d{3}\s*-->\s*\d{2}:\d{2}:\d{2}[,.]\d{3}', line):
                    continue
                text_lines.append(line)
            
            if not text_lines:
                continue
            
            # Combine text lines into sentences
            subtitle_text = ' '.join(text_lines)
            
            # Remove HTML tags and brackets
            subtitle_text = re.sub(r'<[^>]+>', '', subtitle_text)
            subtitle_text = re.sub(r'\[.*?\]', '', subtitle_text)
            
            # Remove subtitle metadata/watermarks
            subtitle_text = re.sub(r'(?i)downloaded\s+from\s+www\.[^\s]+', '', subtitle_text)
            subtitle_text = re.sub(r'(?i)www\.[^\s]+', '', subtitle_text)
            subtitle_text = re.sub(r'(?i)http[s]?://[^\s]+', '', subtitle_text)
            subtitle_text = re.sub(r'(?i)subtitle[s]?\s+by\s+[^\n]+', '', subtitle_text)
            subtitle_text = re.sub(r'(?i)sync[ed]?\s+by\s+[^\n]+', '', subtitle_text)
            
            # Skip if this subtitle block is just metadata
            if re.search(r'(?i)(downloaded|www\.|http|subtitle\s+by|sync)', subtitle_text):
                continue
            
            # Check if any of our words appear in this subtitle
            subtitle_lower = subtitle_text.lower()
            for word in words:
                # Use word boundaries to match whole words only
                if len(examples[word]) >= max_examples_per_word:
                    continue
                
                word_pattern = r'\b' + re.escape(word) + r'\b'
                if re.search(word_pattern, subtitle_lower):
                    # Clean up the sentence
                    clean_sentence = ' '.join(subtitle_text.split())
                    if clean_sentence and len(clean_sentence) > 10:
                        examples[word].append(clean_sentence)
    
    except Exception as e:
        print(f"Warning: Could not extract examples from subtitle: {e}")
    
    return examples


async def translate_words_with_context_async(client: AsyncOpenAI, words: List[str], subtitle_text: str,
                                             examples: Dict[str, List[str]], target_language: str = "Russian") -> Dict[str, Dict[str, str]]:
    """Async version: Translate multiple words using ChatGPT API with subtitle context (PARALLEL PROCESSING).
    
    Args:
        client: AsyncOpenAI client instance
        words: List of words to translate
        subtitle_text: Full subtitle text for context
        examples: Dictionary of word -> example sentences from subtitles
        target_language: Target language for translation
        
    Returns:
        Dictionary mapping words to translation results
    """
    # Prepare examples text
    examples_text = ""
    for word in words:
        word_examples = examples.get(word, [])
        if word_examples:
            examples_text += f"\n- '{word}': {word_examples[0]}\n"
    
    # Limit subtitle text to avoid token limits
    subtitle_context = subtitle_text[:8000] if len(subtitle_text) > 8000 else subtitle_text
    
    # Build words list for prompt
    words_list = ", ".join([f'"{w}"' for w in words])
    
    # Build example structure for prompt
    example_word = words[0] if words else 'word1'
    example_structure = f'    "{example_word}": {{\n        "translation": "actual translation in {target_language}",\n        "example_en": "example sentence in English",\n        "example_translated": "translated example sentence"\n    }}'
    if len(words) > 1:
        example_structure += f',\n    "{words[1]}": {{...}}'
    
    na_warning = "NEVER use N/A"
    transliteration_example = "don't translate cookie as Куки, translate it as печенье"
    
    prompt = f"""You are a professional dictionary translator. Translate words from a TV series using dictionary-style translations that are precise and concise, while considering the specific meaning used in the series context.

SUBTITLE TEXT (for context - use this to determine which meaning/usage applies):
{subtitle_context}

WORDS TO TRANSLATE: {words_list}

EXAMPLES FROM THE SERIES:
{examples_text if examples_text else "No examples available"}

For each word, provide a CONTEXTUAL translation:
1. **Translation** (to {target_language}): 
   - Provide the translation that matches the meaning used in the series context
   - Use up to 5 words when needed for accuracy (especially if a single word doesn't capture the meaning well)
   - If the word has multiple meanings, choose the one that fits the series context and use a phrase if needed
   - Format: word or short phrase (e.g., "узел" for simple cases, "связующее звено" if more context is needed)
   - {na_warning} or empty string - always provide a valid translation
2. **Example sentence** from the series (use the example provided above if available, otherwise create one that matches the series context)
3. **Translated example** - the {target_language} translation of the example sentence

TRANSLATION GUIDELINES:
- Use the series context to determine the exact meaning
- Prefer concise translations (1 word) when accurate
- Use longer phrases (up to 5 words) when a single word doesn't accurately convey the meaning
- Choose the meaning that matches how the word is used in the series
- If a word can be a noun or verb, choose based on how it's used in the series
- Be precise: use the exact translation that fits the context, even if it requires 2-5 words

Format as JSON with this structure (use EXACT word spelling as keys):
{{
{example_structure}
}}

CRITICAL REQUIREMENTS:
- Use the EXACT word spelling as the JSON key (case-sensitive)
- Provide contextual translations (1-5 words, use more words when needed for accuracy)
- Use the series context to select the correct meaning and provide the most accurate translation
- If a single word doesn't accurately translate the meaning, use a phrase (up to 5 words)
- {na_warning} or empty string for translation - always provide a real translation
- NEVER use transliteration (e.g., {transliteration_example})
- Always provide the actual meaning/translation in {target_language}, not a phonetic copy
- If a word is a name, it should have been filtered out already - translate the actual word meaning
- If you cannot translate a word, use a placeholder like [untranslatable] but never N/A"""

    try:
        response = await asyncio.wait_for(
            client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": "You are a helpful translator specializing in TV series translations. Always respond with valid JSON."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                response_format={"type": "json_object"},
                timeout=60.0
            ),
            timeout=60.0
        )
        
        if not response or not response.choices or not response.choices[0].message:
            print(f"⚠️  Empty response from API")
            return {}
        
        result_content = response.choices[0].message.content
        if not result_content:
            print(f"⚠️  Empty content in API response")
            return {}
        
        try:
            result = json.loads(result_content)
        except json.JSONDecodeError as e:
            print(f"⚠️  JSON decode error: {e}")
            print(f"Response content (first 500 chars): {result_content[:500]}")
            return {}
        
        # Debug: Print first few keys to see what ChatGPT returned
        if result:
            keys = list(result.keys())[:5]
            print(f"    Debug: ChatGPT returned {len(result)} keys. First keys: {keys}")
        else:
            print(f"    ⚠️  ChatGPT returned empty result")
        
        # Return result as-is - we'll do case-insensitive matching when processing
        return result
    except asyncio.TimeoutError:
        print(f"⚠️  API call timed out after 60 seconds")
        return {}
    except Exception as e:
        print(f"Error translating words: {e}")
        import traceback
        traceback.print_exc()
        return {}


def translate_words_with_context(client: OpenAI, words: List[str], subtitle_text: str,
                                 examples: Dict[str, List[str]], target_language: str = "Russian") -> Dict[str, Dict[str, str]]:
    """Translate multiple words using ChatGPT API with subtitle context.
    
    Args:
        client: OpenAI client instance
        words: List of words to translate
        subtitle_text: Full subtitle text for context
        examples: Dictionary of word -> example sentences from subtitles
        target_language: Target language for translation
        
    Returns:
        Dictionary mapping words to translation results
    """
    # Prepare examples text
    examples_text = ""
    for word in words:
        word_examples = examples.get(word, [])
        if word_examples:
            examples_text += f"\n- '{word}': {word_examples[0]}\n"
    
    # Limit subtitle text to avoid token limits
    subtitle_context = subtitle_text[:8000] if len(subtitle_text) > 8000 else subtitle_text
    
    # Build words list for prompt
    words_list = ", ".join([f'"{w}"' for w in words])
    
    # Build example structure for prompt
    example_word = words[0] if words else 'word1'
    example_structure = f'    "{example_word}": {{\n        "translation": "actual translation in {target_language}",\n        "example_en": "example sentence in English",\n        "example_translated": "translated example sentence"\n    }}'
    if len(words) > 1:
        example_structure += f',\n    "{words[1]}": {{...}}'
    
    na_warning = "NEVER use N/A"
    transliteration_example = "don't translate cookie as Куки, translate it as печенье"
    
    prompt = f"""You are a professional dictionary translator. Translate words from a TV series using dictionary-style translations that are precise and concise, while considering the specific meaning used in the series context.

SUBTITLE TEXT (for context - use this to determine which meaning/usage applies):
{subtitle_context}

WORDS TO TRANSLATE: {words_list}

EXAMPLES FROM THE SERIES:
{examples_text if examples_text else "No examples available"}

For each word, provide a CONTEXTUAL translation:
1. **Translation** (to {target_language}): 
   - Provide the translation that matches the meaning used in the series context
   - Use up to 5 words when needed for accuracy (especially if a single word doesn't capture the meaning well)
   - If a single word accurately translates the meaning, use just that word
   - If the word has multiple meanings, choose the one that fits the series context and use a phrase if needed
   - Format: word or short phrase (e.g., "узел" for simple cases, "связующее звено" if more context is needed)
   - {na_warning} or empty string - always provide a valid translation
2. **Example sentence** from the series (use the example provided above if available, otherwise create one that matches the series context)
3. **Translated example** - the {target_language} translation of the example sentence

TRANSLATION GUIDELINES:
- Use the series context to determine the exact meaning
- Prefer concise translations (1 word) when accurate
- Use longer phrases (up to 5 words) when a single word doesn't accurately convey the meaning
- Choose the meaning that matches how the word is used in the series
- If a word can be a noun or verb, choose based on how it's used in the series
- Be precise: use the exact translation that fits the context, even if it requires 2-5 words

Format as JSON with this structure (use EXACT word spelling as keys):
{{
{example_structure}
}}

CRITICAL REQUIREMENTS:
- Use the EXACT word spelling as the JSON key (case-sensitive)
- Provide contextual translations (1-5 words, use more words when needed for accuracy)
- Use the series context to select the correct meaning and provide the most accurate translation
- If a single word doesn't accurately translate the meaning, use a phrase (up to 5 words)
- {na_warning} or empty string for translation - always provide a real translation
- NEVER use transliteration (e.g., {transliteration_example})
- Always provide the actual meaning/translation in {target_language}, not a phonetic copy
- If a word is a name, it should have been filtered out already - translate the actual word meaning
- If you cannot translate a word, use a placeholder like [untranslatable] but never N/A"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are a helpful translator specializing in TV series translations. Always respond with valid JSON."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
            response_format={"type": "json_object"},
            timeout=60.0
        )
        
        if not response or not response.choices or not response.choices[0].message:
            print(f"⚠️  Empty response from API")
            return {}
        
        result_content = response.choices[0].message.content
        if not result_content:
            print(f"⚠️  Empty content in API response")
            return {}
        
        try:
            result = json.loads(result_content)
        except json.JSONDecodeError as e:
            print(f"⚠️  JSON decode error: {e}")
            print(f"Response content (first 500 chars): {result_content[:500]}")
            return {}
        
        # Debug: Print first few keys to see what ChatGPT returned
        if result:
            keys = list(result.keys())[:5]
            print(f"    Debug: ChatGPT returned {len(result)} keys. First keys: {keys}")
        else:
            print(f"    ⚠️  ChatGPT returned empty result")
        
        # Return result as-is - we'll do case-insensitive matching when processing
        return result
    except asyncio.TimeoutError:
        print(f"⚠️  API call timed out after 60 seconds")
        return {}
    except Exception as e:
        print(f"Error translating words: {e}")
        import traceback
        traceback.print_exc()
        return {}


def get_subtitle_text(subtitle_path: Path) -> str:
    """Extract clean text from subtitle file.
    
    Args:
        subtitle_path: Path to subtitle file
        
    Returns:
        Cleaned subtitle text
    """
    if not subtitle_path.exists():
        return ""
    
    try:
        with open(subtitle_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        
        # Remove SRT timing lines
        content = re.sub(r'\d{2}:\d{2}:\d{2}[,.]\d{3}\s*-->\s*\d{2}:\d{2}:\d{2}[,.]\d{3}', '', content)
        # Remove subtitle numbers
        content = re.sub(r'^\d+$', '', content, flags=re.MULTILINE)
        # Remove HTML tags
        content = re.sub(r'<[^>]+>', '', content)
        # Remove sound effects and speaker labels
        content = re.sub(r'\[.*?\]', '', content)
        # Clean up whitespace
        content = ' '.join(content.split())
        
        return content
    except Exception as e:
        print(f"Warning: Could not read subtitle file: {e}")
        return ""


def translate_tier_file(tier_file: Path, subtitle_path: Optional[Path], api_key: str, 
                        target_language: str = "Russian", delay: float = 0.5, 
                        overwrite: bool = False) -> bool:
    """Translate words in a tier CSV file using subtitle context.
    
    Args:
        tier_file: Path to tier CSV file
        subtitle_path: Path to subtitle file (for context and examples)
        api_key: OpenAI API key
        target_language: Target language for translation
        delay: Delay between API calls (seconds)
        
    Returns:
        True if successful, False otherwise
    """
    if not tier_file.exists():
        print(f"File not found: {tier_file}")
        return False
    
    # Read existing CSV
    words_data = []
    with open(tier_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            words_data.append(row)
    
    if not words_data:
        print("No words to translate")
        return False
    
    # Check if translations already exist and identify words that need retry
    # Only check if translation column exists in the data
    has_translation_column = 'translation' in words_data[0] if words_data else False
    
    # Identify words that need translation (no translation, N/A, or [Translation failed])
    words_needing_translation = []
    words_with_valid_translation = []
    
    if has_translation_column:
        for row in words_data:
            translation = row.get('translation', '').strip()
            # Check if translation is missing, N/A, or failed
            if not translation or translation.upper() == 'N/A' or translation == '[Translation failed]':
                words_needing_translation.append(row['word'])
            else:
                words_with_valid_translation.append(row['word'])
        
        if words_with_valid_translation and not overwrite:
            print(f"Found {len(words_with_valid_translation)} words with existing translations")
            print(f"Found {len(words_needing_translation)} words needing translation (N/A, [Translation failed], or missing)")
            
            # In non-interactive mode (when called from bot), always retry failed translations
            import sys
            if sys.stdin.isatty():  # Only prompt if running interactively
                if words_needing_translation:
                    print(f"Will retry {len(words_needing_translation)} words with failed/missing translations")
                    response = input("Proceed with retry? (y/n): ")
                    if response.lower() != 'y':
                        return False
                else:
                    # All words have valid translations
                    response = input("Overwrite existing translations? (y/n): ")
                    if response.lower() != 'y':
                        return False
            else:
                # Non-interactive mode: always retry failed translations
                if words_needing_translation:
                    print(f"Non-interactive mode: Will retry {len(words_needing_translation)} words with failed/missing translations")
                else:
                    # All words have valid translations
                    if overwrite:
                        print("Non-interactive mode: --overwrite flag set, will retranslate all words")
                    else:
                        print("Non-interactive mode: All words have valid translations. Nothing to do.")
                        print("Use --overwrite flag to force retranslation of all words.")
                        return True  # All words already translated, nothing to do
    
    # Get subtitle context
    subtitle_text = ""
    if subtitle_path and subtitle_path.exists():
        print(f"Loading subtitle context from {subtitle_path.name}...")
        subtitle_text = get_subtitle_text(subtitle_path)
        print(f"Loaded {len(subtitle_text)} characters of subtitle text")
    else:
        print("Warning: No subtitle file provided. Translations will be generic.")
    
    # Load name filters BEFORE using them (needed for STAGE 1)
    name_filters = set()
    filters_dir = Path(__file__).parent / "filters"
    name_files = ['names_male.csv', 'names_female.csv', 'names_last.csv', 'names_characters.csv']
    for name_file in name_files:
        name_file_path = filters_dir / name_file
        if name_file_path.exists():
            try:
                with open(name_file_path, 'r', encoding='utf-8') as f:
                    reader = csv.reader(f)
                    next(reader, None)  # Skip header
                    for row in reader:
                        if row:
                            name_filters.add(row[0].lower().strip())
            except:
                pass
    if name_filters:
        print(f"Loaded {len(name_filters)} names from name filters")
    
    # STAGE 1: Check for names and fantasy entities (save as column, don't filter out)
    print("\n" + "="*60)
    print("STAGE 1: Checking for names and fantasy entities...")
    print("="*60)
    
    # Extract words to check
    words_to_check = [row['word'] for row in words_data]
    
    # Use ChatGPT to identify names and fantasy entities
    names_from_chatgpt = set()
    chatgpt_reasons = {}  # Store reasons for each word
    if subtitle_text and api_key:
        try:
            # Get series name from episode info if available
            series_name = "Unknown"
            episode_info_file = tier_file.parent / "episode_info.json"
            if episode_info_file.exists():
                try:
                    with open(episode_info_file, 'r', encoding='utf-8') as f:
                        info = json.load(f)
                        series_name = info.get('series', 'Unknown')
                except:
                    pass
            
            # Get ChatGPT filtering results with reasons (now includes "normal word" tags)
            names_from_chatgpt, chatgpt_reasons = filter_names_sync_with_reasons(
                words_to_check, subtitle_text, series_name, api_key
            )
            print(f"ChatGPT flagged {len(names_from_chatgpt)} words as names/fantasy entities")
            print(f"ChatGPT tagged {len([r for r in chatgpt_reasons.values() if 'normal word' in r.lower()])} words as normal words")
        except Exception as e:
            print(f"Warning: Could not use ChatGPT filtering: {e}")
            chatgpt_reasons = {}
    
    # Add filtering results as a column to each word
    # First check name filters, then ChatGPT, then zero-frequency check
    for row in words_data:
        word = row['word']
        word_lower = word.lower()
        
        # Check 1: Name filters (pre-filter before ChatGPT)
        if word_lower in name_filters:
            row['is_name_or_fantasy'] = f"name/fantasy entity (name filter: {row['word']})"
            continue
        
        # Check 1.5: Zero English frequency = likely made-up word or name
        english_freq = int(row.get('english_frequency', 0) or 0)
        if english_freq == 0:
            # Zero frequency usually means it's not a real English word
            # Could be a name, fantasy entity, or made-up word
            # Only tag as name if ChatGPT didn't already tag it as "normal word"
            # (We'll check ChatGPT tag below)
            pass  # Will check after ChatGPT tag
        
        # Check 2: ChatGPT results
        # ChatGPT now returns tags for ALL words (including "normal word")
        chatgpt_tag = chatgpt_reasons.get(word, chatgpt_reasons.get(word.lower(), ''))
        
        if chatgpt_tag:
            if 'name/fantasy entity' in chatgpt_tag.lower():
                row['is_name_or_fantasy'] = f"name/fantasy entity (ChatGPT: {chatgpt_tag})"
            elif 'normal word' in chatgpt_tag.lower():
                # ChatGPT tagged as "normal word", but check if it has zero frequency
                # Zero frequency + "normal word" tag = likely ChatGPT made a mistake, it's probably a name
                if english_freq == 0:
                    print(f"    ⚠️  Word '{word}' has zero English frequency but ChatGPT tagged as 'normal word' - likely a name, overriding")
                    row['is_name_or_fantasy'] = f"name/fantasy entity (zero frequency - likely proper noun)"
                else:
                    row['is_name_or_fantasy'] = 'normal word'
            else:
                # Unknown tag format, treat as name/fantasy if word is in excluded set
                is_name_chatgpt = word_lower in {w.lower() for w in names_from_chatgpt}
                if is_name_chatgpt:
                    row['is_name_or_fantasy'] = f"name/fantasy entity (ChatGPT: {chatgpt_tag})"
                else:
                    row['is_name_or_fantasy'] = 'normal word'
        else:
            # No tag from ChatGPT - check if word is in excluded set (fallback)
            is_name_chatgpt = word_lower in {w.lower() for w in names_from_chatgpt}
            if is_name_chatgpt:
                row['is_name_or_fantasy'] = 'name/fantasy entity (ChatGPT: no tag provided)'
            elif english_freq == 0:
                # No ChatGPT tag but zero frequency = likely a name
                print(f"    ⚠️  Word '{word}' has zero English frequency and no ChatGPT tag - likely a name")
                row['is_name_or_fantasy'] = 'name/fantasy entity (zero frequency - likely proper noun)'
            else:
                # No tag - will be handled by simple word detection or default to empty
                row['is_name_or_fantasy'] = ''  # Empty if not flagged
    
    # STAGE 1.5: Check for simple words based on vocabulary_level and other criteria
    print("\n" + "="*60)
    print("STAGE 1.5: Checking for simple words...")
    print("="*60)
    
    simple_word_count = 0
    
    # Load easy words filter
    easy_words_filter = set()
    easy_words_file = Path(__file__).parent / "filters" / "easy_words.csv"
    if easy_words_file.exists():
        try:
            with open(easy_words_file, 'r', encoding='utf-8') as f:
                reader = csv.reader(f)
                next(reader, None)  # Skip header
                for row in reader:
                    if row:
                        easy_words_filter.add(row[0].lower().strip())
            print(f"Loaded {len(easy_words_filter)} words from easy_words.csv filter")
        except Exception as e:
            print(f"Warning: Could not load easy_words.csv: {e}")
    
    # Name filters already loaded above (before STAGE 1)
    
    for row in words_data:
        # If word is already flagged as name/fantasy or tagged as normal word, don't override
        existing_tag = row.get('is_name_or_fantasy', '').strip()
        if existing_tag and 'normal word' not in existing_tag.lower():
            continue  # Skip if already tagged as name/fantasy or simple word
        
        word = row.get('word', '').lower()
        vocab_level = row.get('vocabulary_level', 'N/A').upper()
        english_freq = int(row.get('english_frequency', 0) or 0)
        
        # Check 1: Vocabulary level A1 or A2
        if vocab_level in ['A1', 'A2']:
            row['is_name_or_fantasy'] = f'simple word (vocabulary level: {vocab_level})'
            simple_word_count += 1
            continue
        
        # Check 2: Word in easy_words filter
        if word in easy_words_filter:
            row['is_name_or_fantasy'] = 'simple word (easy_words filter)'
            simple_word_count += 1
            continue
        
        # Check 3: Very high English frequency (> 2M, doubled from 1M to make filter 2x weaker) and not in vocabulary list (likely simple/common)
        if vocab_level == 'N/A' and english_freq > 2_000_000:
            row['is_name_or_fantasy'] = f'simple word (high frequency: {english_freq:,}, not in vocabulary list)'
            simple_word_count += 1
            continue
        
        # Check 4: Informal/non-standard words (repeated letters, unusual patterns)
        # Pattern: 3+ repeated letters (e.g., "wassuuuup", "whasuuuup")
        if re.search(r'(.)\1{2,}', word):
            row['is_name_or_fantasy'] = 'simple word (informal/non-standard spelling)'
            simple_word_count += 1
            continue
        
        # Check 5: Very short words with high frequency (likely simple) - threshold doubled from 1M to 2M
        if len(word) <= 4 and english_freq > 2_000_000:
            row['is_name_or_fantasy'] = f'simple word (short word with high frequency: {english_freq:,})'
            simple_word_count += 1
            continue
        
        # If no simple word flags and ChatGPT tagged as "normal word", keep it
        if existing_tag and 'normal word' in existing_tag.lower():
            continue  # Keep the "normal word" tag from ChatGPT
    
    print(f"Flagged {simple_word_count} words as simple words")
    
    # Ensure all words that ChatGPT tagged as "normal word" keep that tag
    for row in words_data:
        word = row['word']
        chatgpt_tag = chatgpt_reasons.get(word, chatgpt_reasons.get(word.lower(), ''))
        current_tag = row.get('is_name_or_fantasy', '').strip()
        
        # If ChatGPT tagged as "normal word" and current tag is empty or doesn't override it
        if chatgpt_tag and 'normal word' in chatgpt_tag.lower():
            if not current_tag or current_tag == '':
                row['is_name_or_fantasy'] = 'normal word'
    
    flagged_count = sum(1 for row in words_data if row.get('is_name_or_fantasy', '') and 'normal word' not in row.get('is_name_or_fantasy', '').lower())
    normal_word_count = sum(1 for row in words_data if 'normal word' in row.get('is_name_or_fantasy', '').lower())
    print(f"Total flagged: {flagged_count} words (names/fantasy entities + simple words)")
    print(f"Total tagged as normal word: {normal_word_count} words")
    print(f"Total words to translate: {len(words_data)}")
    print("="*60 + "\n")
    
    if not words_data:
        print("No words to translate.")
        return False
    
    # STAGE 2: Extract words to translate (after filtering)
    # If we have words needing translation, only translate those (unless overwrite is True)
    # Otherwise, translate all words (if overwrite is True or no translations exist)
    if has_translation_column and words_needing_translation and not overwrite:
        # Only translate words that need retry (have "[Translation failed]", "N/A", or missing translation)
        words_to_translate = words_needing_translation
        print(f"Retrying translation for {len(words_to_translate)} words with failed/missing translations")
        print(f"  Words with valid translations ({len(words_with_valid_translation)}) will be preserved")
    elif overwrite:
        # Overwrite flag set: translate all words
        words_to_translate = [row['word'] for row in words_data]
        print(f"Overwrite mode: Will retranslate all {len(words_to_translate)} words")
    else:
        # No translations exist yet, translate all words
        words_to_translate = [row['word'] for row in words_data]
        print(f"Translating all {len(words_to_translate)} words (no existing translations)")
    
    words_set = set(words_to_translate)
    
    # Extract examples from subtitles
    examples = {}
    if subtitle_path and subtitle_path.exists():
        print("Extracting example sentences from subtitles...")
        examples = extract_examples_from_subtitle(subtitle_path, words_set, max_examples_per_word=2)
        found_examples = sum(1 for ex_list in examples.values() if ex_list)
        print(f"Found examples for {found_examples}/{len(words_to_translate)} words")
    
    # STAGE 2: Translate remaining words (non-names) - PARALLEL PROCESSING
    print("\n" + "="*60)
    print("STAGE 2: Translating remaining words (PARALLEL)...")
    print("="*60)
    
    # Use async parallel processing for translations
    async def translate_all_batches_parallel():
        """Translate all batches in parallel using async processing."""
        async_client = AsyncOpenAI(api_key=api_key)
        batch_size = 10  # Translate 10 words at a time to include full context
        max_concurrent = 5  # Process 5 batches at once for GPT-4o (more powerful but rate-limited)
        semaphore = asyncio.Semaphore(max_concurrent)
        
        # Create batches
        batches = []
        for batch_start in range(0, len(words_to_translate), batch_size):
            batch_words = words_to_translate[batch_start:batch_start + batch_size]
            batch_examples = {word: examples.get(word, []) for word in batch_words}
            batch_num = batch_start//batch_size + 1
            batches.append((batch_words, batch_examples, batch_num))
        
        async def translate_batch(batch_words: List[str], batch_examples: Dict[str, List[str]], batch_num: int) -> tuple[List[str], Dict[str, Dict[str, str]]]:
            """Translate a single batch of words."""
            async with semaphore:
                print(f"Translating batch {batch_num} ({len(batch_words)} words)...")
                try:
                    translations = await translate_words_with_context_async(
                        async_client, batch_words, subtitle_text, batch_examples, target_language
                    )
                    if not translations:
                        print(f"⚠️  Batch {batch_num} returned empty translations")
                    return batch_words, translations
                except Exception as e:
                    error_msg = str(e)
                    error_type = type(e).__name__
                    print(f"⚠️  Error translating batch {batch_num}: {error_type}: {error_msg}")
                    # Check for specific API errors
                    if "401" in error_msg or "authentication" in error_msg.lower() or "api key" in error_msg.lower() or "invalid_api_key" in error_msg.lower():
                        print(f"❌ API authentication error - check API key")
                    elif "429" in error_msg or "rate limit" in error_msg.lower() or "insufficient_quota" in error_msg.lower() or "RateLimitError" in error_type:
                        print(f"❌ API quota/rate limit exceeded - check billing and quota")
                        print(f"   This may cause all translations to fail. Please check OpenAI account billing.")
                    elif "500" in error_msg or "503" in error_msg or "InternalServerError" in error_type:
                        print(f"❌ API server error - OpenAI service may be down")
                    import traceback
                    traceback.print_exc()
                    return batch_words, {}
        
        # Process all batches concurrently with timeout and error handling
        print(f"Translating {len(words_to_translate)} words in {len(batches)} batches (parallel)...")
        try:
            batch_results = await asyncio.wait_for(
                asyncio.gather(*[
                    translate_batch(batch_words, batch_examples, batch_num)
                    for batch_words, batch_examples, batch_num in batches
                ], return_exceptions=True),
                timeout=300.0  # 5 minutes total timeout
            )
        except asyncio.TimeoutError:
            print("⚠️  Translation timed out after 5 minutes. Processing partial results...")
            # Get partial results if any batches completed
            batch_results = []
            for batch_words, batch_examples, batch_num in batches:
                batch_results.append((batch_words, {}))  # Empty translations for timed out batches
        
        # Update word data with translations
        successful_batches = 0
        failed_batches = 0
        translated_words_count = 0
        for i, result in enumerate(batch_results):
            if isinstance(result, Exception):
                print(f"⚠️  Batch {i+1}/{len(batches)} failed with exception: {result}")
                import traceback
                traceback.print_exc()
                failed_batches += 1
                # Mark words in this batch for retry
                batch_words, batch_examples, batch_num = batches[i]
                for word_data in words_data:
                    if word_data['word'] in batch_words:
                        word_data['_needs_retry'] = True
                continue
            
            batch_words, translations = result
            successful_batches += 1
            batch_translated = 0
            for word_data in words_data:
                word = word_data['word']
                # Only process words that are in this batch
                if word in batch_words:
                    # Skip if word already has a valid translation and we're not overwriting
                    # (This is a safety check - words_to_translate should already be filtered)
                    if has_translation_column and not overwrite:
                        existing_translation = word_data.get('translation', '').strip()
                        if existing_translation and existing_translation.upper() != 'N/A' and existing_translation != '[Translation failed]':
                            # Word already has valid translation, skip (shouldn't happen if words_to_translate is correct)
                            print(f"    ⚠️  Skipping '{word}' - already has valid translation (this shouldn't happen)")
                            continue
                    # Try exact match first, then case-insensitive match
                    word_key = None
                    if word in translations:
                        word_key = word
                    elif word.lower() in translations:
                        word_key = word.lower()
                    else:
                        # Try to find any key that matches (case-insensitive)
                        for key in translations.keys():
                            if key.lower() == word.lower():
                                word_key = key
                                break
                    
                    if word_key and word_key in translations:
                        trans_data = translations[word_key]
                        # Handle both dict and string formats
                        if isinstance(trans_data, dict):
                            translation = trans_data.get('translation', '').strip()
                        elif isinstance(trans_data, str):
                            translation = trans_data.strip()
                        else:
                            translation = str(trans_data).strip()
                        
                        # Validate translation - must not be empty or "N/A"
                        if translation and translation.upper() != 'N/A' and translation != '[Translation failed]':
                            word_data['translation'] = translation
                            # Use example from subtitle if available, otherwise use from translation
                            batch_examples = {w: examples.get(w, []) for w in batch_words}
                            if batch_examples.get(word):
                                word_data['example_en'] = batch_examples[word][0]
                            elif isinstance(trans_data, dict):
                                word_data['example_en'] = trans_data.get('example_en', '').strip()
                                word_data['example_translated'] = trans_data.get('example_translated', '').strip()
                            batch_translated += 1
                            translated_words_count += 1
                        else:
                            # Translation is empty or "N/A" - mark for retry
                            print(f"⚠️  Word '{word}' has invalid translation '{translation}', will retry")
                            word_data['_needs_retry'] = True
                    else:
                        # Word not in translation response - debug and retry
                        print(f"⚠️  Word '{word}' not in translation response. Available keys: {list(translations.keys())[:10]}")
                        # Mark for retry
                        word_data['_needs_retry'] = True
            
            print(f"✓ Batch {i+1}/{len(batches)} completed: {batch_translated}/{len(batch_words)} words translated ({successful_batches} successful batches, {failed_batches} failed batches, {translated_words_count} total words translated)")
        
        print(f"\n📊 Translation progress: {translated_words_count}/{len(words_to_translate)} words translated ({successful_batches}/{len(batches)} batches successful)")
        
        # Check if we had API quota errors
        if translated_words_count == 0 and len(words_to_translate) > 0:
            print(f"\n⚠️  WARNING: No words were translated. This may indicate:")
            print(f"   - API quota exceeded (check OpenAI billing)")
            print(f"   - API authentication error (check API key)")
            print(f"   - Network/connectivity issues")
            print(f"   - All words are names/fantasy entities (should be filtered)")
        
        await async_client.close()
    
    # Run async translation
    # Since this function is called from run_in_executor (separate thread), asyncio.run() will work
    print(f"Translating {len(words_to_translate)} words with series context (parallel processing)...")
    asyncio.run(translate_all_batches_parallel())
    
    # Retry words that didn't get translations (PARALLEL)
    words_needing_retry = [row for row in words_data if row.get('_needs_retry') and not row.get('translation', '').strip()]
    if words_needing_retry:
        print(f"\nRetrying {len(words_needing_retry)} words that didn't get translations (parallel)...")
        
        async def retry_words_parallel():
            """Retry failed words in parallel."""
            async_client = AsyncOpenAI(api_key=api_key)
            max_concurrent = 5  # Lower concurrency for retries (using GPT-4o)
            semaphore = asyncio.Semaphore(max_concurrent)
            
            async def retry_single_word(word_data: Dict) -> Dict:
                """Retry translation for a single word."""
                async with semaphore:
                    word = word_data['word']
                    print(f"  Retrying '{word}'...")
                    
                    # Get example if available
                    word_example = examples.get(word, [])
                    example_text = word_example[0] if word_example else ""
                    
                    try:
                        # Contextual translation prompt for retry
                        example_placeholder = example_text if example_text else "example sentence"
                        retry_prompt = f"""Translate the English word "{word}" to {target_language} using contextual translation.

{f'Context from series: "{example_text}"' if example_text else 'No context available'}

Provide a CONTEXTUAL translation:
- Use up to 5 words when needed for accuracy (especially if a single word doesn't capture the meaning well)
- If a single word accurately translates the meaning, use just that word
- Choose the meaning that matches the series context
- Be precise: use the exact translation that fits the context

Return JSON:
{{
    "translation": "contextual translation in {target_language} (1-5 words, use more when needed for accuracy)",
    "example_en": "{example_placeholder}",
    "example_translated": "translated example sentence"
}}

CRITICAL: NEVER return "N/A" or empty string for translation. Always provide a real, accurate translation that matches the series context."""
                        
                        retry_response = await asyncio.wait_for(
                            async_client.chat.completions.create(
                                model="gpt-4o",
                                messages=[
                                    {"role": "system", "content": "You are a helpful translator. Always respond with valid JSON."},
                                    {"role": "user", "content": retry_prompt}
                                ],
                                temperature=0.0,
                                response_format={"type": "json_object"},
                                timeout=60.0
                            ),
                            timeout=60.0
                        )
                        
                        retry_result = json.loads(retry_response.choices[0].message.content)
                        
                        # Handle different response formats
                        translation = None
                        example_en = None
                        example_translated = None
                        
                        # Check if response has the word as a key
                        if word in retry_result:
                            trans_data = retry_result[word]
                            translation = trans_data.get('translation', '').strip()
                            example_en = trans_data.get('example_en', '').strip()
                            example_translated = trans_data.get('example_translated', '').strip()
                        # Check if response has 'translation' at root level
                        elif 'translation' in retry_result:
                            translation = retry_result.get('translation', '').strip()
                            example_en = retry_result.get('example_en', '').strip()
                            example_translated = retry_result.get('example_translated', '').strip()
                        # Try case-insensitive match
                        else:
                            for key in retry_result.keys():
                                if key.lower() == word.lower():
                                    trans_data = retry_result[key]
                                    translation = trans_data.get('translation', '').strip()
                                    example_en = trans_data.get('example_en', '').strip()
                                    example_translated = trans_data.get('example_translated', '').strip()
                                    break
                        
                        # Validate translation
                        if translation and translation.upper() != 'N/A':
                            word_data['translation'] = translation
                            if not word_data.get('example_en') and example_en and example_en.upper() != 'N/A':
                                word_data['example_en'] = example_en
                            if example_translated and example_translated.upper() != 'N/A':
                                word_data['example_translated'] = example_translated
                            word_data.pop('_needs_retry', None)
                            return word_data
                        else:
                            print(f"    ⚠️  Retry failed for '{word}': translation = '{translation}'")
                            word_data['translation'] = '[Translation failed]'
                            word_data.pop('_needs_retry', None)
                            return word_data
                    except asyncio.TimeoutError:
                        print(f"    ⚠️  Timeout retrying '{word}': API call exceeded 60 seconds")
                        word_data['translation'] = '[Translation failed]'
                        word_data.pop('_needs_retry', None)
                        return word_data
                    except Exception as e:
                        print(f"    Error retrying '{word}': {e}")
                        import traceback
                        traceback.print_exc()
                        word_data['translation'] = '[Translation failed]'
                        word_data.pop('_needs_retry', None)
                        return word_data
            
            # Process all retries concurrently with timeout
            print(f"Retrying {len(words_needing_retry)} words in parallel...")
            try:
                await asyncio.wait_for(
                    asyncio.gather(*[retry_single_word(word_data) for word_data in words_needing_retry], return_exceptions=True),
                    timeout=120.0  # 2 minutes for retries
                )
            except asyncio.TimeoutError:
                print("⚠️  Retry operation timed out after 2 minutes. Some words may not be translated.")
            except Exception as e:
                print(f"⚠️  Error during retry operation: {e}")
                import traceback
                traceback.print_exc()
            await async_client.close()
        
        asyncio.run(retry_words_parallel())
    
    # Remove retry markers
    for word_data in words_data:
        word_data.pop('_needs_retry', None)
    
    # Final validation: Check for any words with empty or N/A translations
    # Also check for words with "[Translation failed]" - these are likely names that should be filtered
    words_without_translation = []
    words_with_failed_translation = []
    for word_data in words_data:
        translation = word_data.get('translation', '').strip()
        word = word_data.get('word', '')
        is_name_tag = word_data.get('is_name_or_fantasy', '').strip().lower()
        
        if not translation or translation.upper() == 'N/A':
            words_without_translation.append(word)
        elif translation == '[Translation failed]':
            words_with_failed_translation.append(word)
            # Only re-tag as name/fantasy if word ALSO has zero English frequency
            # Translation can fail for many reasons (API quota, network, etc.), not just names
            english_freq = int(word_data.get('english_frequency', 0) or 0)
            if 'normal word' in is_name_tag and english_freq == 0:
                # Zero frequency + failed translation = likely a name
                print(f"    ⚠️  Word '{word}' failed translation, has zero frequency, and was tagged as 'normal word' - likely a name, re-tagging")
                word_data['is_name_or_fantasy'] = f"name/fantasy entity (translation failed - zero frequency, likely proper noun)"
            elif 'normal word' in is_name_tag and english_freq > 0:
                # Real English word with failed translation - keep as "normal word", translation failure is likely API issue
                print(f"    ℹ️  Word '{word}' failed translation but has English frequency {english_freq:,} - keeping as 'normal word' (likely API issue, not a name)")
                # Don't change the tag - keep it as "normal word"
    
    if words_without_translation:
        print(f"\n⚠️  WARNING: {len(words_without_translation)} words still have no valid translation:")
        for word in words_without_translation[:10]:  # Show first 10
            print(f"    - {word}")
        if len(words_without_translation) > 10:
            print(f"    ... and {len(words_without_translation) - 10} more")
    
    if words_with_failed_translation:
        print(f"\n⚠️  WARNING: {len(words_with_failed_translation)} words failed translation (likely names/fantasy entities):")
        for word in words_with_failed_translation[:10]:  # Show first 10
            print(f"    - {word}")
        if len(words_with_failed_translation) > 10:
            print(f"    ... and {len(words_with_failed_translation) - 10} more")
    
    # Write back to CSV
    fieldnames = list(words_data[0].keys())
    with open(tier_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(words_data)
    
    # Count flagged words for summary
    flagged_count = sum(1 for row in words_data if row.get('is_name_or_fantasy', '') and 'normal word' not in row.get('is_name_or_fantasy', '').lower())
    translated_count = sum(1 for row in words_data if row.get('translation', '').strip() and row.get('translation', '').strip().upper() != 'N/A' and row.get('translation', '').strip() != '[Translation failed]')
    failed_count = sum(1 for row in words_data if row.get('translation', '').strip() == '[Translation failed]')
    
    print(f"\n✓ Translations saved to {tier_file}")
    print(f"✓ Total words: {len(words_data)}")
    print(f"✓ Words with valid translations: {translated_count}")
    print(f"✓ Words flagged as names/fantasy entities: {flagged_count} (saved in 'is_name_or_fantasy' column)")
    
    if words_without_translation:
        print(f"⚠️  Words without translations: {len(words_without_translation)}")
    
    if failed_count > 0:
        print(f"⚠️  Words with failed translations: {failed_count}")
        if failed_count == len(words_data):
            print(f"❌ ALL translations failed - likely API quota/authentication issue")
            print(f"   Check OpenAI billing: https://platform.openai.com/account/billing")
    
    return True


def find_subtitle_file(episode_dir: Path) -> Optional[Path]:
    """Try to find subtitle file for this episode.
    
    Looks for subtitle files in common locations based on episode info.
    """
    # Check episode_info.json for subtitle filename
    episode_info = episode_dir / "episode_info.json"
    if episode_info.exists():
        try:
            with open(episode_info, 'r', encoding='utf-8') as f:
                info = json.load(f)
                subtitle_filename = info.get('subtitle_file', '')
                if subtitle_filename:
                    # Try to find in Subtitles directory
                    base_dir = episode_dir.parent.parent.parent
                    subtitle_path = base_dir / "Subtitles" / subtitle_filename
                    if subtitle_path.exists():
                        return subtitle_path
        except:
            pass
    
    # Try to find any .srt file in Subtitles directory
    base_dir = episode_dir.parent.parent.parent
    subtitles_dir = base_dir / "Subtitles"
    if subtitles_dir.exists():
        # Try to match by episode info
        episode_info = episode_dir / "episode_info.json"
        if episode_info.exists():
            try:
                with open(episode_info, 'r', encoding='utf-8') as f:
                    info = json.load(f)
                    season = info.get('season', '')
                    episode = info.get('episode', '')
                    series = info.get('series', '')
                    
                    # Search for matching subtitle files
                    for srt_file in subtitles_dir.glob("*.srt"):
                        if season and season in srt_file.name:
                            if episode and episode in srt_file.name:
                                return srt_file
            except:
                pass
    
    return None


def translate_episode(episode_dir: Path, subtitle_path: Optional[Path], api_key: str, 
                     target_language: str = "Russian", delay: float = 0.5, 
                     overwrite: bool = False) -> bool:
    """Translate all tier files in an episode directory using subtitle context.
    
    Args:
        episode_dir: Path to episode directory
        subtitle_path: Path to subtitle file (if None, will try to find automatically)
        api_key: OpenAI API key
        target_language: Target language for translation
        delay: Delay between API calls (seconds)
        
    Returns:
        True if successful, False otherwise
    """
    # Check if this is a CEFR-based episode
    episode_info_file = episode_dir / "episode_info.json"
    tier_file = None
    
    if episode_info_file.exists():
        try:
            import json
            with open(episode_info_file, 'r', encoding='utf-8') as f:
                info = json.load(f)
                if info.get('approach') == 'cefr':
                    user_level = info.get('user_level')
                    if user_level:
                        tier_file = episode_dir / f"hard_words_for_{user_level}.csv"
        except:
            pass
    
    # Fall back to standard tier files if not CEFR
    if tier_file is None:
        # Translate both tier 1 and tier 2
        tier_1_file = episode_dir / "tier_1_hard_usable_words.csv"
        tier_2_file = episode_dir / "tier_2_random_words.csv"
        
        # Try to find subtitle file if not provided
        if subtitle_path is None:
            subtitle_path = find_subtitle_file(episode_dir)
            if subtitle_path:
                print(f"Found subtitle file: {subtitle_path.name}")
            else:
                print("Warning: Could not find subtitle file. Please provide with --subtitle option.")
        
        # Translate tier 1
        success_1 = True
        if tier_1_file.exists():
            print(f"\nTranslating Tier 1 (Hard Usable Words)...")
            success_1 = translate_tier_file(tier_1_file, subtitle_path, api_key, target_language, delay, overwrite)
        else:
            print(f"Tier 1 file not found: {tier_1_file}")
        
        # Translate tier 2
        success_2 = True
        if tier_2_file.exists():
            print(f"\nTranslating Tier 2 (Rare in Series Hard Words)...")
            success_2 = translate_tier_file(tier_2_file, subtitle_path, api_key, target_language, delay, overwrite)
        else:
            print(f"Tier 2 file not found: {tier_2_file}")
        
        return success_1 and success_2
    else:
        # CEFR-based episode - translate only the specified tier file
        if not tier_file.exists():
            print(f"Tier file not found in {episode_dir}: {tier_file}")
            return False
        
        # Try to find subtitle file if not provided
        if subtitle_path is None:
            subtitle_path = find_subtitle_file(episode_dir)
            if subtitle_path:
                print(f"Found subtitle file: {subtitle_path.name}")
            else:
                print("Warning: Could not find subtitle file. Please provide with --subtitle option.")
        
        return translate_tier_file(tier_file, subtitle_path, api_key, target_language, delay, overwrite)


def main():
    parser = argparse.ArgumentParser(description='Translate words in tier lists using ChatGPT API with subtitle context')
    parser.add_argument('--tier-file', '-f', type=str,
                       help='Path to tier CSV file to translate')
    parser.add_argument('--episode-dir', '-e', type=str,
                       help='Path to episode directory (translates tier_1_hard_usable_words.csv)')
    parser.add_argument('--subtitle', '-s', type=str,
                       help='Path to subtitle file (SRT). If not provided, will try to find automatically for episode.')
    parser.add_argument('--api-key', type=str,
                       default=os.environ.get("OPENAI_API_KEY", ""),
                       help='OpenAI API key (default: OPENAI_API_KEY env)')
    parser.add_argument('--language', '-l', type=str, default='Russian',
                       help='Target language for translation (default: Russian)')
    parser.add_argument('--delay', type=float, default=0.5,
                       help='Delay between API calls in seconds (default: 0.5)')
    parser.add_argument('--overwrite', action='store_true',
                       help='Overwrite existing translations without prompting')
    
    args = parser.parse_args()
    
    base_dir = Path(__file__).parent
    
    subtitle_path = None
    if args.subtitle:
        subtitle_path = base_dir / args.subtitle
    
    if args.tier_file:
        tier_file = base_dir / args.tier_file
        success = translate_tier_file(tier_file, subtitle_path, args.api_key, args.language, args.delay, args.overwrite)
        if not success:
            print("ERROR: Translation failed")
            exit(1)
    elif args.episode_dir:
        episode_dir = base_dir / args.episode_dir
        success = translate_episode(episode_dir, subtitle_path, args.api_key, args.language, args.delay, args.overwrite)
        if not success:
            print("ERROR: Translation failed")
            exit(1)
    else:
        parser.print_help()
        print("\nExample usage:")
        print("  python3 translate_words.py --episode-dir tierlist/Fallout/S02E01")
        print("  python3 translate_words.py --episode-dir tierlist/Fallout/S02E01 --subtitle Subtitles/Fallout.S02E01.srt")
        print("  python3 translate_words.py --tier-file tierlist/Fallout/S02E01/tier_1_hard_usable_words.csv --subtitle Subtitles/Fallout.S02E01.srt")
        exit(1)


if __name__ == '__main__':
    main()
