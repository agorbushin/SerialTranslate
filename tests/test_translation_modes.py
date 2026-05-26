"""Tests for translation mode selection and prompts."""

from translation_modes import (
    DEFAULT_TRANSLATION_MODE,
    build_translate_batch_prompt,
    get_translation_mode_from_env,
    normalize_translation_mode,
)


def test_normalize_translation_mode_defaults_to_english_dictionary():
    assert normalize_translation_mode(None) == "english_dictionary"
    assert normalize_translation_mode("") == "english_dictionary"
    assert normalize_translation_mode("english") == "english_dictionary"
    assert normalize_translation_mode("dictionary") == "english_dictionary"


def test_normalize_translation_mode_russian_aliases():
    assert normalize_translation_mode("russian") == "russian"
    assert normalize_translation_mode("ru") == "russian"


def test_default_mode_is_english_dictionary():
    assert DEFAULT_TRANSLATION_MODE == "english_dictionary"


def test_russian_prompt_mentions_russian():
    prompt, system = build_translate_batch_prompt(
        mode="russian",
        series_name="Test",
        words_list='"abate"',
        examples_block='  "abate": "it began to abate"',
        context="context",
    )
    assert "Russian" in prompt
    assert "Russian" in system


def test_english_dictionary_prompt_is_english_only():
    prompt, system = build_translate_batch_prompt(
        mode="english_dictionary",
        series_name="Test",
        words_list='"abate"',
        examples_block='  "abate": "it began to abate"',
        context="context",
    )
    assert "English dictionary" in prompt or "dictionary glosses" in prompt
    assert "Glosses are English" in system
    assert "Russian" not in prompt


def test_get_translation_mode_from_env(monkeypatch):
    monkeypatch.delenv("TRANSLATION_MODE", raising=False)
    assert get_translation_mode_from_env() == "english_dictionary"
    monkeypatch.setenv("TRANSLATION_MODE", "russian")
    assert get_translation_mode_from_env() == "russian"
