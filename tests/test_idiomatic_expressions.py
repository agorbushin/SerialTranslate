"""Unit tests for idiomatic_expressions (no live API)."""

from collections import Counter

import pytest

from idiomatic_expressions import (
    _extract_idiomacy_scores,
    _is_consecutive_subsequence,
    dedupe_subsumed_phrases,
    extract_repeated_ngrams,
    filter_ngram_candidates,
    tokenize_words,
)


def test_tokenize_words_lowercase():
    assert tokenize_words("Hello, World!") == ["hello", "world"]


def test_extract_repeated_ngrams_min_occurrences():
    tokens = tokenize_words("a b c a b c a b c")
    c = extract_repeated_ngrams(tokens, min_n=2, max_n=2, min_occurrences=2)
    assert c["a b"] >= 2
    assert c["b c"] >= 2


def test_extract_repeated_ngrams_filters_single_occurrence():
    tokens = tokenize_words("once upon a time once upon a time")
    c = extract_repeated_ngrams(tokens, min_n=4, max_n=4, min_occurrences=2)
    assert c["once upon a time"] == 2


def test_filter_drops_all_stopwords():
    raw = Counter({"in the and": 3})
    out = filter_ngram_candidates(raw)
    assert "in the and" not in out


def test_filter_keeps_idiom_like_span():
    raw = Counter({"bend the rules": 2, "one of the": 5})
    out = filter_ngram_candidates(raw)
    assert "bend the rules" in out
    assert "one of the" not in out


def test_filter_drops_fragment_head():
    raw = Counter({"s just going straight": 2, "fair enough": 2})
    out = filter_ngram_candidates(raw)
    assert "s just going straight" not in out
    assert "fair enough" in out


def test_filter_drops_trailing_title_junk():
    raw = Counter({"king of the andals and": 2, "winter is coming": 2})
    out = filter_ngram_candidates(raw)
    assert "king of the andals and" not in out
    assert "winter is coming" in out


def test_is_consecutive_subsequence():
    assert _is_consecutive_subsequence(["the", "end"], ["at", "the", "end", "of"])
    assert not _is_consecutive_subsequence(["the", "of"], ["at", "the", "end", "of"])


def test_dedupe_subsumed_phrases():
    items = [
        ("at the end of the day", 3),
        ("the end of the", 3),
        ("fair enough", 2),
    ]
    approved = {"at the end of the day", "the end of the", "fair enough"}
    kept = dedupe_subsumed_phrases(items, approved)
    assert "fair enough" in kept
    assert "at the end of the day" in kept
    assert "the end of the" not in kept


def test_extract_idiomacy_scores_accepts_new_key():
    payload = {"idiomacy_ratings": {"the quiet room": 2, "fair enough": "8"}}
    out = _extract_idiomacy_scores(payload)
    assert out["the quiet room"] == 2
    assert out["fair enough"] == 8


def test_extract_idiomacy_scores_fallback_legacy_key():
    payload = {"idiomaticity_scores": {"winter is coming": 7}}
    out = _extract_idiomacy_scores(payload)
    assert out["winter is coming"] == 7
