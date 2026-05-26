"""Translation style profiles for tier word glosses.

The bot defaults to English dictionary-style definitions. Russian glosses are
preserved for CLI/scripts via ``russian`` mode or ``TRANSLATION_MODE=russian``.
"""

from __future__ import annotations

import os
from typing import Literal, Tuple

TranslationMode = Literal["english_dictionary", "russian"]

DEFAULT_TRANSLATION_MODE: TranslationMode = "english_dictionary"
LEGACY_TRANSLATION_MODE: TranslationMode = "russian"


def normalize_translation_mode(value: str | None) -> TranslationMode:
    """Map env/CLI values to a supported mode (default: english_dictionary)."""
    raw = (value or "").strip().lower().replace("-", "_")
    if raw in ("russian", "ru", "rus"):
        return "russian"
    if raw in (
        "english_dictionary",
        "english",
        "en",
        "dictionary",
        "dict",
        "english_dict",
    ):
        return "english_dictionary"
    return DEFAULT_TRANSLATION_MODE


def get_translation_mode_from_env() -> TranslationMode:
    return normalize_translation_mode(os.environ.get("TRANSLATION_MODE"))


def build_translate_batch_prompt(
    *,
    mode: TranslationMode,
    series_name: str,
    words_list: str,
    examples_block: str,
    context: str,
) -> Tuple[str, str]:
    """Return (user_prompt, system_message) for one translate_batch API call."""
    if mode == "russian":
        return _build_russian_prompt(
            series_name=series_name,
            words_list=words_list,
            examples_block=examples_block,
            context=context,
        )
    return _build_english_dictionary_prompt(
        series_name=series_name,
        words_list=words_list,
        examples_block=examples_block,
        context=context,
    )


def _build_russian_prompt(
    *,
    series_name: str,
    words_list: str,
    examples_block: str,
    context: str,
) -> Tuple[str, str]:
    target_language = "Russian"
    prompt = f"""Series: {series_name}. Use the meaning that fits this show's setting (e.g. medieval/fantasy: maid = handmaid/servant = служанка; crow can be the bird or to crow; choose based on the example lines below).

You are a dictionary translator. Translate the following English words into {target_language}.

EXAMPLE LINES FROM THE EPISODE (use these to choose the correct sense):
{examples_block}

SUBTITLE CONTEXT (fallback when a word has no example above):
{context}

WORDS TO TRANSLATE: {words_list}

RULES:
- Translation must be short and dictionary-like: maximum 4-5 words.
- Prefer the meaning that appears in the EXAMPLE LINES above; if there are no examples for a word, use the subtitle context and the series setting.
- For period/fantasy series, prefer setting-appropriate terms (e.g. maid as servant = служанка; appropriate register for nobility/war).
- Avoid generic or default dictionary sense when the context clearly suggests a more specific sense (e.g. beating in a fight context; raped as in the dialogue).
- NEVER phonetically transcribe English sounds into Russian. Always use a real Russian dictionary word.
  Wrong: "cockroach" → "Кокроча"   Right: "cockroach" → "таракан"
  Wrong: "erm" → "эм"              Right: "erm" → "э-э (звук колебания)"
  If a word has no clean Russian equivalent, use the closest semantic meaning — never a phonetic copy.
- IMPORTANT NAME RULE: if the EXAMPLE LINES show that this token is used as a character/person name in the episode,
  output this exact pattern:
  "<русская передача имени> (имя в сериале), словарный перевод — <обычный перевод слова>"
  Example: "destiny" when used as a name → "Дестини (имя в сериале), словарный перевод — судьба"
- The "maximum 4-5 words" rule does NOT apply to this special NAME RULE format.
- If you are genuinely unsure of a word's meaning in context, leave its value as an empty string "".
- Output ONLY a JSON object with the exact English word as key and the {target_language} translation as value. No explanation.
- Example format: {{"word1": "translation1", "word2": "translation2"}}

Respond with a single JSON object only."""
    system = (
        "You are a precise Russian dictionary translator. You respond only with valid JSON. "
        "No markdown, no extra text. Never phonetically transcribe — always use real Russian words."
    )
    return prompt, system


def _build_english_dictionary_prompt(
    *,
    series_name: str,
    words_list: str,
    examples_block: str,
    context: str,
) -> Tuple[str, str]:
    prompt = f"""Series: {series_name}. You are writing learner-friendly English dictionary glosses for hard words from this episode.

EXAMPLE LINES FROM THE EPISODE (use these to choose the correct sense):
{examples_block}

SUBTITLE CONTEXT (fallback when a word has no example above):
{context}

WORDS TO GLOSS: {words_list}

RULES:
- Write each gloss in English, like a concise learner's dictionary entry for the sense used in this episode.
- Prefer a short definition phrase (about 3–12 words), not a full sentence unless needed for clarity.
- Optional part-of-speech tag at the start is OK, e.g. "(v.) to reduce in amount" or "(n.) a large country house".
- Use the EXAMPLE LINES to pick the right sense; avoid unrelated dictionary senses.
- For period/fantasy settings, use definitions that match the world (e.g. maid = female servant, not office assistant).
- Do NOT translate into another language — glosses must be English only.
- Do NOT repeat the headword alone; explain the meaning (e.g. "abate" → "to become less intense", not "abate").
- IMPORTANT NAME RULE: if the EXAMPLE LINES show the token is a character/person name,
  use: "<Name> (character name); dictionary sense — <normal English gloss of the word>"
  Example: "destiny" as a name → "Destiny (character name); dictionary sense — fate, predetermined outcome"
- If you are genuinely unsure of a word's meaning in context, leave its value as an empty string "".
- Output ONLY a JSON object with the exact English word as key and the English gloss as value. No explanation.
- Example format: {{"word1": "gloss1", "word2": "gloss2"}}

Respond with a single JSON object only."""
    system = (
        "You are a precise English dictionary lexicographer for TV vocabulary learners. "
        "You respond only with valid JSON. No markdown, no extra text. Glosses are English definitions only."
    )
    return prompt, system
