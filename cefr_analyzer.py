#!/usr/bin/env python3
"""
CEFR-based word analysis and tier categorization.
Labels words by CEFR level and creates hard words lists based on user's level.
"""

import csv
import pandas as pd
from pathlib import Path
from collections import Counter
from typing import Dict, List, Set, Optional, Tuple
import re
from collections import Counter


CEFR_LEVELS = ['A1', 'A2', 'B1', 'B2', 'C1', 'C2']
CEFR_ORDER = {level: idx for idx, level in enumerate(CEFR_LEVELS)}


def load_cefr_levels(cefr_file: Path) -> Dict[str, str]:
    """Load CEFR levels from Excel file.
    
    Args:
        cefr_file: Path to complete English vocabulary Excel file
        
    Returns:
        Dictionary mapping word (lowercase) to CEFR level (A1, A2, B1, B2, C1, C2)
    """
    word_levels = {}
    
    if not cefr_file.exists():
        print(f"Warning: CEFR file not found: {cefr_file}")
        return word_levels
    
    try:
        # Read Excel file
        df = pd.read_excel(cefr_file)
        
        # Check if required columns exist
        if 'word' not in df.columns or 'level' not in df.columns:
            print(f"Warning: Required columns not found. Columns: {df.columns.tolist()}")
            return word_levels
        
        # Create mapping: word -> level
        for _, row in df.iterrows():
            word = str(row['word']).lower().strip()
            level = str(row['level']).strip().upper()
            
            # Validate level
            if level in CEFR_LEVELS:
                # If word already exists, keep the higher level (more advanced)
                if word not in word_levels:
                    word_levels[word] = level
                else:
                    current_level = word_levels[word]
                    if CEFR_ORDER[level] > CEFR_ORDER[current_level]:
                        word_levels[word] = level
        
        print(f"Loaded {len(word_levels)} words with CEFR levels")
        return word_levels
        
    except Exception as e:
        print(f"Error loading CEFR levels: {e}")
        import traceback
        traceback.print_exc()
        return word_levels


def to_singular(word: str) -> str:
    """Convert a word to its singular form (simple version).
    
    Args:
        word: Word to singularize
        
    Returns:
        Singular form of the word
    """
    word_lower = word.lower()
    
    # Common plural rules
    if word_lower.endswith('ies'):
        return word_lower[:-3] + 'y'
    elif word_lower.endswith('ves'):
        return word_lower[:-3] + 'f'
    elif word_lower.endswith('es') and len(word_lower) > 3:
        # Check if it's a word that ends in 'es' (like 'boxes')
        if word_lower[-3] in 'sxz' or word_lower[-3:-1] in ['ch', 'sh']:
            return word_lower[:-2]
    elif word_lower.endswith('s') and len(word_lower) > 1:
        return word_lower[:-1]
    
    return word_lower


def label_words_by_cefr(words: List[str], cefr_levels: Dict[str, str]) -> Dict[str, str]:
    """Label words by their CEFR level.
    
    Args:
        words: List of words to label
        cefr_levels: Dictionary mapping words to CEFR levels
        
    Returns:
        Dictionary mapping word to CEFR level (or 'UNKNOWN' if not found)
    """
    labeled = {}
    
    for word in words:
        word_lower = word.lower()
        
        # Try exact match
        if word_lower in cefr_levels:
            labeled[word] = cefr_levels[word_lower]
        else:
            # Try singular form
            singular = to_singular(word_lower)
            if singular in cefr_levels:
                labeled[word] = cefr_levels[singular]
            else:
                labeled[word] = 'UNKNOWN'
    
    return labeled


def categorize_words_by_cefr(
    series_freqs: Counter,
    cefr_levels: Dict[str, str],
    user_level: str,
    excluded_words: Set[str],
    oxford_filter: Set[str],
    easy_words_filter: Set[str],
    english_freqs: Optional[Dict[str, int]] = None,
    max_english_freq: Optional[int] = None,
    min_level_gap: int = 1
) -> Dict[str, List[Tuple[str, int, str]]]:
    """Categorize words by CEFR level and filter based on user's level.
    
    Args:
        series_freqs: Word frequencies in the series
        cefr_levels: Dictionary mapping words to CEFR levels
        user_level: User's English level (A1, A2, B1, B2, C1, C2)
        excluded_words: Words to exclude (names, contractions, etc.)
        oxford_filter: Oxford 3000 words to exclude
        easy_words_filter: Easy words to exclude
        english_freqs: Optional English frequency dictionary for additional filtering
        max_english_freq: Optional maximum English frequency threshold
        min_level_gap: Minimum CEFR level gap (1 = next level, 2 = skip one level)
        
    Returns:
        Dictionary with 'hard_words' list (words above user's level)
    """
    if user_level not in CEFR_ORDER:
        raise ValueError(f"Invalid user level: {user_level}. Must be one of {CEFR_LEVELS}")
    
    user_level_idx = CEFR_ORDER[user_level]
    
    # Words above user's level
    hard_words = []
    
    # Label all words by CEFR level
    word_labels = label_words_by_cefr(list(series_freqs.keys()), cefr_levels)
    
    for word, series_count in series_freqs.items():
        word_lower = word.lower()
        
        # Skip excluded words
        if word_lower in excluded_words:
            continue
        
        # Skip Oxford words
        if word_lower in oxford_filter:
            continue
        
        # Skip easy words
        if word_lower in easy_words_filter:
            continue
        
        # Get CEFR level
        word_level = word_labels.get(word, 'UNKNOWN')
        
        # If word level is above user's level, check additional filters
        if word_level != 'UNKNOWN':
            word_level_idx_val = CEFR_ORDER.get(word_level, -1)
            level_gap = word_level_idx_val - user_level_idx
            
            # Only include words that are at least min_level_gap levels above
            if level_gap >= min_level_gap:
                # Additional filter: English frequency check
                if english_freqs and max_english_freq:
                    english_count = english_freqs.get(word_lower, 0)
                    # Also check singular form
                    if english_count == 0:
                        singular = to_singular(word_lower)
                        english_count = english_freqs.get(singular, 0)
                    
                    # Skip if too common in English
                    if english_count > max_english_freq:
                        continue
                
                hard_words.append((word, series_count, word_level))
        # If level is UNKNOWN, exclude it
    
    # Sort by series frequency (descending)
    hard_words.sort(key=lambda x: x[1], reverse=True)
    
    return {
        'hard_words': hard_words
    }


def save_cefr_tier_list(
    hard_words: List[Tuple[str, int, str]],
    episode_dir: Path,
    user_level: str
) -> Path:
    """Save CEFR-based hard words list to CSV.
    
    Args:
        hard_words: List of (word, series_freq, cefr_level) tuples
        episode_dir: Episode directory to save to
        user_level: User's English level
        
    Returns:
        Path to saved CSV file
    """
    episode_dir.mkdir(parents=True, exist_ok=True)
    
    # Create filename: hard_words_for_A1.csv, etc.
    filename = f"hard_words_for_{user_level}.csv"
    filepath = episode_dir / filename
    
    # Write CSV
    with open(filepath, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['word', 'series_frequency', 'cefr_level'])
        
        for word, series_freq, cefr_level in hard_words:
            writer.writerow([word, series_freq, cefr_level])
    
    print(f"Saved {len(hard_words)} hard words to {filepath}")
    return filepath


def analyze_subtitle_cefr(
    subtitle_path: Path,
    cefr_levels: Dict[str, str],
    user_level: str,
    excluded_words: Set[str],
    oxford_filter: Set[str],
    easy_words_filter: Set[str]
) -> Counter:
    """Analyze subtitle and extract words with frequencies for CEFR-based approach.
    
    Args:
        subtitle_path: Path to subtitle file
        cefr_levels: Dictionary mapping words to CEFR levels
        user_level: User's English level
        excluded_words: Words to exclude
        oxford_filter: Oxford words to exclude
        easy_words_filter: Easy words to exclude
        
    Returns:
        Counter of word frequencies in series
    """
    from subtitle_analyzer import parse_srt_file, extract_words_from_zip, to_singular
    
    # Extract words from subtitle
    if subtitle_path.suffix == '.zip':
        series_freqs = extract_words_from_zip(subtitle_path, excluded_words)
    else:
        words = parse_srt_file(subtitle_path, excluded_words)
        series_freqs = Counter(words)
    
    return series_freqs
