#!/usr/bin/env python3
"""
Lemmatization module for word normalization.

This module provides lemmatization functionality using spaCy.
It can be easily disabled by setting USE_LEMMATIZATION = False.

To disable lemmatization:
1. Set USE_LEMMATIZATION = False in this file
2. The code will fall back to simple singularization

To modify lemmatization:
- Change the spaCy model (currently 'en_core_web_sm')
- Adjust the lemmatization logic in lemmatize_word()
"""

import os
from typing import Optional

# Configuration: Set to False to disable lemmatization and use simple singularization
USE_LEMMATIZATION = True

# spaCy model name (lightweight model for speed)
SPACY_MODEL = 'en_core_web_sm'

# Global spaCy nlp object (lazy loaded)
_nlp = None
_warning_printed = False


def _get_nlp():
    """Lazy load spaCy model."""
    global _nlp, _warning_printed
    if _nlp is None:
        if not USE_LEMMATIZATION:
            return None
        try:
            import spacy
            _nlp = spacy.load(SPACY_MODEL, disable=['parser', 'ner'])
        except OSError:
            # Model not found - only print warning once
            if not _warning_printed:
                print(f"Info: spaCy model '{SPACY_MODEL}' not found.")
                print(f"  Install with: python -m spacy download {SPACY_MODEL}")
                print(f"  Using simple singularization instead.")
                _warning_printed = True
            return None
        except ImportError:
            # spaCy not installed - only print warning once
            if not _warning_printed:
                print(f"Info: spaCy not installed.")
                print(f"  Install with: pip install spacy")
                print(f"  Using simple singularization instead.")
                _warning_printed = True
            return None
        except Exception as e:
            # Other errors - only print warning once
            if not _warning_printed:
                print(f"Info: Could not load spaCy model: {e}")
                print(f"  Using simple singularization instead.")
                _warning_printed = True
            return None
    return _nlp


def lemmatize_word(word: str) -> str:
    """
    Lemmatize a word using spaCy.
    
    This converts words to their base form:
    - "thinking" -> "think"
    - "thought" -> "think"
    - "thinks" -> "think"
    - "cities" -> "city"
    - "went" -> "go"
    
    Args:
        word: Word to lemmatize
        
    Returns:
        Lemmatized word (base form)
    """
    if not USE_LEMMATIZATION:
        # Fall back to simple singularization
        from subtitle_analyzer import to_singular
        return to_singular(word)
    
    nlp = _get_nlp()
    if nlp is None:
        # Fall back to simple singularization if spaCy not available
        from subtitle_analyzer import to_singular
        return to_singular(word)
    
    # Use spaCy for lemmatization
    doc = nlp(word)
    if doc:
        lemma = doc[0].lemma_.lower()
        return lemma
    
    # Fallback if lemmatization fails
    return word.lower()


def lemmatize_words(words: list) -> list:
    """
    Lemmatize a list of words.
    
    Args:
        words: List of words to lemmatize
        
    Returns:
        List of lemmatized words
    """
    if not USE_LEMMATIZATION:
        # Fall back to simple singularization
        from subtitle_analyzer import to_singular
        return [to_singular(w) for w in words]
    
    nlp = _get_nlp()
    if nlp is None:
        # Fall back to simple singularization if spaCy not available
        from subtitle_analyzer import to_singular
        return [to_singular(w) for w in words]
    
    # Batch process for efficiency
    lemmatized = []
    try:
        # Process in batches for better performance
        batch_size = 1000
        for i in range(0, len(words), batch_size):
            batch = words[i:i+batch_size]
            # Join with spaces, process, then extract lemmas
            text = ' '.join(batch)
            doc = nlp(text)
            # Extract lemmas in order (matching input order)
            batch_lemmas = [token.lemma_.lower() for token in doc if not token.is_space]
            lemmatized.extend(batch_lemmas)
    except Exception as e:
        # Fall back to word-by-word if batch processing fails
        from subtitle_analyzer import to_singular
        return [to_singular(w) for w in words]
    
    # Ensure we have the same number of words
    if len(lemmatized) != len(words):
        # Fallback if counts don't match
        from subtitle_analyzer import to_singular
        return [to_singular(w) for w in words]
    
    return lemmatized


def is_lemmatization_enabled() -> bool:
    """Check if lemmatization is enabled."""
    return USE_LEMMATIZATION and _get_nlp() is not None


if __name__ == "__main__":
    # Test lemmatization
    test_words = ["thinking", "thought", "thinks", "cities", "went", "goes", "went"]
    
    print("Testing lemmatization:")
    print(f"USE_LEMMATIZATION = {USE_LEMMATIZATION}")
    print(f"spaCy available = {_get_nlp() is not None}")
    print()
    
    for word in test_words:
        lemma = lemmatize_word(word)
        print(f"  {word} -> {lemma}")
