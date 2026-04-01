#!/usr/bin/env python3
"""
Extract and translate phrasal verbs from subtitles.
Phrasal verbs are verb + particle combinations (e.g., "give up", "look for").
"""

import re
import csv
import json
from pathlib import Path
from collections import Counter
from typing import Dict, List, Tuple, Optional, Set
from openai import OpenAI
import argparse

# Common phrasal verb particles
PHRASAL_PARTICLES = [
    'up', 'down', 'out', 'in', 'on', 'off', 'away', 'back', 'over', 'through',
    'around', 'about', 'along', 'across', 'by', 'for', 'with', 'to', 'into',
    'onto', 'upon', 'after', 'before', 'ahead', 'aside', 'apart', 'together'
]

# Common phrasal verb patterns (verb + particle)
# This is a basic list - we'll detect more from context
COMMON_PHRASAL_VERBS = [
    'give up', 'look for', 'turn on', 'turn off', 'put on', 'take off',
    'get up', 'sit down', 'come in', 'go out', 'come back', 'go back',
    'look up', 'look down', 'look out', 'look after', 'look into',
    'find out', 'figure out', 'work out', 'point out', 'turn out',
    'break down', 'break up', 'break in', 'break out', 'break through',
    'bring up', 'bring in', 'bring out', 'bring back', 'bring about',
    'call off', 'call up', 'call on', 'call for', 'call back',
    'come up', 'come down', 'come out', 'come in', 'come across',
    'go on', 'go off', 'go through', 'go over', 'go along',
    'pick up', 'pick out', 'pick on', 'put down', 'put off',
    'put up', 'put out', 'put together', 'take on', 'take in',
    'take over', 'take up', 'turn around', 'turn down', 'turn up',
    'wake up', 'wake up', 'stand up', 'stand by', 'stand for',
    'set up', 'set out', 'set off', 'set about', 'show up',
    'show off', 'shut down', 'shut up', 'shut off', 'shut in',
    'run into', 'run out', 'run over', 'run away', 'run across',
    'make up', 'make out', 'make for', 'make off', 'make over',
    'get on', 'get off', 'get in', 'get out', 'get back',
    'get up', 'get down', 'get over', 'get through', 'get along',
    'keep up', 'keep on', 'keep off', 'keep out', 'keep away',
    'hold on', 'hold up', 'hold back', 'hold out', 'hold off',
    'move on', 'move in', 'move out', 'move over', 'move along',
    'carry on', 'carry out', 'carry over', 'carry off', 'carry away',
    'check in', 'check out', 'check up', 'check on', 'check off',
    'fill in', 'fill out', 'fill up', 'end up', 'wind up',
    'catch up', 'catch on', 'catch out',
    'deal with', 'do with', 'do without', 'go with', 'go without',
    'come up with', 'put up with', 'keep up with',
    'give in', 'give out', 'give away', 'give back', 'give off',
    'let in', 'let out', 'let down', 'let up', 'let go',
    'pass away', 'pass out', 'pass on', 'pass by', 'pass through',
    'pull off', 'pull out', 'pull over', 'pull through', 'pull together',
    'push on', 'push through', 'push ahead', 'push forward', 'push back',
    'send off', 'send out', 'send away', 'send back', 'send in',
    'throw away', 'throw out', 'throw off', 'throw up', 'throw in',
    'try on', 'try out', 'try for', 'try back', 'wear out',
    'write down', 'write up', 'write out', 'write off', 'write back'
]

# First-token artifacts from splitting contractions with \\b\\w+\\b (e.g. what's -> s + next).
CONTRACTION_FRAGMENTS = frozenset({'s', 't', 'm', 're', 've', 'll', 'd'})

_COMMON_PHRASAL_SET = frozenset(COMMON_PHRASAL_VERBS)


def parse_srt_file(srt_path: Path) -> str:
    """Parse SRT subtitle file and return clean text.
    
    Args:
        srt_path: Path to SRT file
        
    Returns:
        Clean text content
    """
    try:
        with open(srt_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        
        # Remove subtitle timestamps and formatting
        # Remove timestamps (e.g., "00:00:01,234 --> 00:00:03,456")
        content = re.sub(r'\d{2}:\d{2}:\d{2}[,.]\d{3}\s*-->\s*\d{2}:\d{2}:\d{2}[,.]\d{3}', '', content)
        
        # Remove subtitle numbers
        content = re.sub(r'^\d+$', '', content, flags=re.MULTILINE)
        
        # Remove HTML tags
        content = re.sub(r'<[^>]+>', '', content)
        
        # Remove formatting tags like {\an8}
        content = re.sub(r'\{[^}]+\}', '', content)
        
        # Remove subtitle metadata/watermarks
        content = re.sub(r'Downloaded\s+From\s+www\.[^\s]+', '', content, flags=re.IGNORECASE)
        content = re.sub(r'www\.[^\s]+', '', content, flags=re.IGNORECASE)
        content = re.sub(r'http[s]?://[^\s]+', '', content)
        content = re.sub(r'Subtitles?\s+by\s+[^\n]+', '', content, flags=re.IGNORECASE)
        content = re.sub(r'Synced\s+by\s+[^\n]+', '', content, flags=re.IGNORECASE)
        
        # Clean up whitespace
        content = ' '.join(content.split())
        
        return content
    except Exception as e:
        print(f"Error parsing SRT file: {e}")
        return ""


def _to_token_filter_drop(phrase: str) -> bool:
    """True if phrase should be dropped due to project 'to' heuristics."""
    return (
        ' to ' in phrase
        or phrase.endswith(' to')
        or phrase.startswith('to ')
    )


def extract_phrasal_verbs(text: str) -> Tuple[Counter, Set[str]]:
    """Extract phrasal verbs from text.

    Tokenization uses ``\\b\\w+\\b`` (contraction-safe parsing deferred); dynamic
    hits are tagged separately for deterministic filtering.

    Returns:
        (counter, from_dictionary): counts after merging dict + dynamic passes,
        and the set of phrases that matched COMMON_PHRASAL_VERBS (not dynamic-only).
    """
    dict_counter: Counter = Counter()
    dynamic_counter: Counter = Counter()
    text_lower = text.lower()

    words = re.findall(r'\b\w+\b', text_lower)

    for pv in COMMON_PHRASAL_VERBS:
        if _to_token_filter_drop(pv):
            continue
        pattern = r'\b' + re.escape(pv) + r'\b'
        matches = len(re.findall(pattern, text_lower))
        if matches > 0:
            dict_counter[pv] += matches

    for i in range(len(words) - 1):
        word = words[i]
        next_word = words[i + 1] if i + 1 < len(words) else None

        if next_word and next_word in PHRASAL_PARTICLES and next_word != 'to':
            phrasal_verb = f"{word} {next_word}"
            if phrasal_verb not in _COMMON_PHRASAL_SET and not _to_token_filter_drop(
                phrasal_verb
            ):
                dynamic_counter[phrasal_verb] += 1

        if i + 2 < len(words):
            word_after = words[i + 2]
            if next_word in PHRASAL_PARTICLES and word_after in [
                'with',
                'for',
                'on',
                'in',
                'at',
                'by',
            ]:
                phrasal_verb = f"{word} {next_word} {word_after}"
                if phrasal_verb not in _COMMON_PHRASAL_SET:
                    dynamic_counter[phrasal_verb] += 1

    merged = dict_counter + dynamic_counter
    filtered = Counter()
    for pv, count in merged.items():
        if _to_token_filter_drop(pv):
            continue
        filtered[pv] = count

    from_dictionary = set(dict_counter.keys()) & set(filtered.keys())
    return filtered, from_dictionary


def filter_phrasal_candidates(counter: Counter, from_dictionary: Set[str]) -> Counter:
    """Drop tokenizer junk and weak dynamic heads; never weaken dictionary matches."""
    out = Counter()
    for phrase, count in counter.items():
        if phrase in from_dictionary:
            out[phrase] = count
            continue
        parts = phrase.split()
        if not parts:
            continue
        head = parts[0]
        if head in CONTRACTION_FRAGMENTS:
            continue
        if len(head) < 2:
            continue
        out[phrase] = count
    return out


def verify_phrasal_verbs_with_chatgpt(
    candidates: List[str],
    subtitle_text: str,
    series_name: str,
    api_key: str,
    batch_size: int = 25,
) -> Set[str]:
    """Ask the model which strings are real phrasal / verb-particle idioms.

    Returns a subset of ``candidates`` (exact string match). Invalid adjacency
    and non-idiomatic pairs should be excluded by the model.
    """
    if not candidates:
        return set()

    client = OpenAI(api_key=api_key)
    approved: Set[str] = set()
    context = subtitle_text[:3000] if len(subtitle_text) > 3000 else subtitle_text
    ctx_snip = context[:2000]

    for batch_start in range(0, len(candidates), batch_size):
        batch = candidates[batch_start : batch_start + batch_size]
        numbered = "\n".join(f"{i + 1}. {p}" for i, p in enumerate(batch))

        prompt = f"""You are a linguist judging English multiword units for the TV series "{series_name}".

Below is a numbered list of candidate PHRASES (2–3 words) taken from subtitles. Many are NOT real phrasal verbs: they may be random adjacency (e.g. "you in", "man in"), tokenizer garbage (e.g. "s up" from contractions), or ordinary grammar — not lexical phrasal verbs / idiomatic verb–particle combinations.

Keep ONLY phrases that are genuine phrasal verbs or established verb–particle / verb–preposition idioms in English (e.g. "give up", "come on", "look for", "put up with").

CANDIDATES:
{numbered}

SUBTITLE EXCERPT (for context only):
{ctx_snip}

Return ONLY a JSON object with this exact shape:
{{"valid": ["phrase1", "phrase2", ...]}}

Rules:
- Each string in "valid" MUST be copied EXACTLY from the candidate list above (same spelling, same spacing).
- If none qualify, return {{"valid": []}}.
"""

        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": "You judge phrasal verbs. Respond only with valid JSON: an object with key 'valid' whose value is an array of strings.",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                response_format={"type": "json_object"},
            )
            raw = response.choices[0].message.content
            result = json.loads(raw) if raw else {}
            valid_list = result.get("valid") or []
            batch_set = set(batch)
            for s in valid_list:
                if isinstance(s, str) and s in batch_set:
                    approved.add(s)
            print(
                f"Verified batch {batch_start // batch_size + 1}: "
                f"{len([x for x in valid_list if isinstance(x, str) and x in batch_set])}/"
                f"{len(batch)} kept"
            )
        except Exception as e:
            print(f"Error verifying batch {batch_start // batch_size + 1}: {e}")

    return approved


def apply_verified_phrasals(counter: Counter, approved: Set[str]) -> Counter:
    """Keep only keys present in ``approved``, preserving counts."""
    return Counter({k: counter[k] for k in counter if k in approved})


def translate_phrasal_verbs(phrasal_verbs: List[Tuple[str, int]], 
                                   subtitle_text: str,
                                   series_name: str,
                                   api_key: str,
                                   target_language: str = "Russian") -> Dict[str, str]:
    """Translate phrasal verbs using ChatGPT with series context.
    
    Args:
        phrasal_verbs: List of (phrasal_verb, frequency) tuples
        subtitle_text: Subtitle text for context
        series_name: Name of the series
        api_key: OpenAI API key
        target_language: Target language for translation
        
    Returns:
        Dictionary mapping phrasal verb to translation
    """
    if not phrasal_verbs:
        return {}
    
    translations = {}
    client = OpenAI(api_key=api_key)
    
    # Process in batches
    batch_size = 20
    for batch_start in range(0, len(phrasal_verbs), batch_size):
        batch = phrasal_verbs[batch_start:batch_start + batch_size]
        pv_list = [pv for pv, _ in batch]
        
        # Get context from subtitles
        context = subtitle_text[:3000] if len(subtitle_text) > 3000 else subtitle_text
        
        prompt = f"""You are translating phrasal verbs from the TV series "{series_name}".

PHASAL VERBS TO TRANSLATE:
{', '.join(pv_list)}

SUBTITLE CONTEXT:
{context[:2000]}

For each phrasal verb, provide a translation in {target_language} that:
1. Is accurate and natural in {target_language}
2. Reflects the meaning used in this series context
3. Can be 1-3 words if needed for accuracy

Return ONLY a JSON object with this structure:
{{
    "translations": {{
        "give up": "сдаваться",
        "look for": "искать",
        ...
    }}
}}

Return the JSON:"""

        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": f"You are a translator specializing in phrasal verbs. Always respond with valid JSON in {target_language}."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                response_format={"type": "json_object"}
            )
            
            result = json.loads(response.choices[0].message.content)
            batch_translations = result.get("translations", {})
            translations.update(batch_translations)
            
            print(f"Translated batch {batch_start//batch_size + 1}: {len(batch_translations)} phrasal verbs")
            
        except Exception as e:
            print(f"Error translating batch {batch_start//batch_size + 1}: {e}")
            # Continue with next batch
    
    return translations


def extract_examples_for_phrasal_verbs(subtitle_text: str, 
                                       phrasal_verbs: List[str],
                                       max_examples: int = 2) -> Dict[str, List[str]]:
    """Extract example sentences containing phrasal verbs.
    
    Args:
        subtitle_text: Subtitle text
        phrasal_verbs: List of phrasal verbs to find examples for
        max_examples: Maximum examples per phrasal verb
        
    Returns:
        Dictionary mapping phrasal verb to list of example sentences
    """
    examples = {}
    
    # Split text into sentences (rough approximation)
    sentences = re.split(r'[.!?]+', subtitle_text)
    
    for pv in phrasal_verbs:
        pv_examples = []
        pv_lower = pv.lower()
        
        for sentence in sentences:
            if pv_lower in sentence.lower():
                # Clean up sentence
                sentence = sentence.strip()
                if len(sentence) > 10 and len(sentence) < 200:  # Reasonable length
                    pv_examples.append(sentence)
                    if len(pv_examples) >= max_examples:
                        break
        
        examples[pv] = pv_examples[:max_examples]
    
    return examples


def save_phrasal_verbs(phrasal_verbs: Counter,
                       translations: Dict[str, str],
                       examples: Dict[str, List[str]],
                       episode_dir: Path):
    """Save phrasal verbs to CSV file.
    
    Args:
        phrasal_verbs: Counter of phrasal verbs with frequencies
        translations: Dictionary of phrasal verb -> translation
        examples: Dictionary of phrasal verb -> list of example sentences
        episode_dir: Directory to save the CSV file
    """
    episode_dir.mkdir(parents=True, exist_ok=True)
    csv_file = episode_dir / "phrasal_verbs.csv"
    
    # Sort by frequency (descending)
    sorted_pvs = sorted(phrasal_verbs.items(), key=lambda x: x[1], reverse=True)
    
    with open(csv_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['phrasal_verb', 'frequency', 'translation', 'example'])
        
        for pv, freq in sorted_pvs:
            translation = translations.get(pv, 'N/A')
            pv_examples = examples.get(pv, [])
            example = pv_examples[0] if pv_examples else 'N/A'
            
            writer.writerow([pv, freq, translation, example])
    
    print(f"Saved {len(sorted_pvs)} phrasal verbs to {csv_file}")


def extract_phrasal_verbs_from_episode(subtitle_path: Path,
                                       episode_dir: Path,
                                       series_name: str,
                                       api_key: str) -> bool:
    """Extract and translate phrasal verbs from an episode.
    
    Args:
        subtitle_path: Path to subtitle file
        episode_dir: Directory to save results
        series_name: Name of the series
        api_key: OpenAI API key
        
    Returns:
        True if successful, False otherwise
    """
    print(f"\n{'='*60}")
    print("EXTRACTING PHRASAL VERBS")
    print(f"{'='*60}\n")
    
    # Parse subtitle file
    print(f"Parsing subtitle file: {subtitle_path.name}")
    subtitle_text = parse_srt_file(subtitle_path)
    
    if not subtitle_text:
        print("Error: Could not parse subtitle file")
        return False
    
    print(f"Extracted {len(subtitle_text)} characters of text")

    print("\nExtracting phrasal verbs...")
    phrasal_verbs, from_dictionary = extract_phrasal_verbs(subtitle_text)

    if not phrasal_verbs:
        print("No phrasal verbs found")
        return False

    print(
        f"After extract: {len(phrasal_verbs)} unique, "
        f"{sum(phrasal_verbs.values())} occurrences"
    )

    filtered = filter_phrasal_candidates(phrasal_verbs, from_dictionary)
    print(
        f"After deterministic filter: {len(filtered)} unique, "
        f"{sum(filtered.values())} occurrences"
    )
    if not filtered:
        print("No phrasal verbs left after deterministic filter")
        return False

    ordered_for_verify = sorted(filtered.items(), key=lambda x: x[1], reverse=True)
    candidate_strings = [p for p, _ in ordered_for_verify]

    print("\nVerifying phrasal verbs with ChatGPT...")
    approved = verify_phrasal_verbs_with_chatgpt(
        candidate_strings, subtitle_text, series_name, api_key
    )
    verified = apply_verified_phrasals(filtered, approved)
    print(
        f"After LLM verification: {len(verified)} unique, "
        f"{sum(verified.values())} occurrences"
    )
    if not verified:
        print("No phrasal verbs left after LLM verification")
        return False

    sorted_pvs = sorted(verified.items(), key=lambda x: x[1], reverse=True)

    print("\nExtracting example sentences...")
    pv_list = [pv for pv, _ in sorted_pvs]
    examples = extract_examples_for_phrasal_verbs(subtitle_text, pv_list)

    print("\nTranslating phrasal verbs...")
    translations = translate_phrasal_verbs(
        sorted_pvs, subtitle_text, series_name, api_key
    )

    print("\nSaving results...")
    save_phrasal_verbs(verified, translations, examples, episode_dir)
    
    print(f"\n{'='*60}")
    print("PHRASAL VERB EXTRACTION COMPLETE")
    print(f"{'='*60}\n")
    
    return True


def main():
    """Command-line interface for phrasal verb extraction."""
    parser = argparse.ArgumentParser(description='Extract phrasal verbs from subtitles')
    parser.add_argument('--subtitle', '-s', type=str, required=True,
                       help='Path to subtitle file')
    parser.add_argument('--output', '-o', type=str, required=True,
                       help='Output directory for CSV file')
    parser.add_argument('--series', type=str, required=True,
                       help='Series name')
    parser.add_argument('--api-key', type=str, required=True,
                       help='OpenAI API key')
    
    args = parser.parse_args()
    
    subtitle_path = Path(args.subtitle)
    output_dir = Path(args.output)
    
    if not subtitle_path.exists():
        print(f"Error: Subtitle file not found: {subtitle_path}")
        return
    
    extract_phrasal_verbs_from_episode(
        subtitle_path, output_dir, args.series, args.api_key
    )


if __name__ == '__main__':
    main()
