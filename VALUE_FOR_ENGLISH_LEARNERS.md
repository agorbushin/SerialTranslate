# Why This Bot Helps English Learners

This document explains what the SerialTranslate bot does **for you** if you are learning English—especially if you already watch TV series in English and want vocabulary that actually appears in the shows you love.

---

## The problem it solves

- **Generic word lists** (apps, textbooks) rarely match what you hear in *your* show. You learn “abstract” words first, not the ones characters keep saying.
- **Subtitles alone** don’t tell you which words are worth studying: common fillers mix with rare, useful words.
- **Dictionaries** give many meanings; in an episode, only **one sense** usually matters (e.g. *maid* in a fantasy drama vs. in a modern office).

The bot focuses on **episode-specific, advanced-level vocabulary** and pairs each English word with a **short Russian translation** chosen with **context from that episode**.

---

## What you get

1. **Words from real dialogue**  
   Vocabulary is extracted from official-style subtitles for a **specific series, season, and episode**—so what you study matches what you watched.

2. **A “hard but useful” shortlist (Tier 1)**  
   The system ranks words by how often they appear **in that episode/series** vs. how common they are in **general English**.  
   The list you translate first is biased toward words that are **frequent in the show** but **not ultra-common** in everyday English—often the sweet spot for learners who already know basics.

3. **Sense-aware translations**  
   Translations use **lines from the episode** where possible, so the Russian gloss aims at the **meaning used in that scene**, not a random dictionary entry.

4. **Cleaner lists (fewer noise items)**  
   The pipeline tries to filter out things that are poor flashcard material—e.g. **names, places, and made-up fantasy terms**—so you spend time on **real English vocabulary**.

5. **Reusable study material**  
   Results are saved as structured data (word ↔ Russian translation). You can use the list in chat, export-style workflows, or future features (e.g. spaced repetition / Anki)—without re-typing subtitles by hand.

---

## Who benefits most

| You are… | Why it fits |
|----------|-------------|
| **B2+ moving toward C1/C2** | You want **precise, low-frequency, and idiomatic** words tied to stories you care about—not more “hello / table / beautiful.” |
| **Someone who learns from TV** | You turn **passive watching** into a **targeted word list** for one episode at a time. |
| **A Russian speaker** | Russian glosses make it faster to **anchor meaning** while you still engage with **English in context** (the show). |

If you are a **complete beginner**, a raw “hard words” list may feel heavy; the product is optimized for learners who already follow dialogue with subtitles.

---

## How to use it (conceptually)

1. Pick a show and episode you watched (or will watch).
2. Request that episode through the bot (series name + season/episode).
3. Get a **numbered list**: English word → Russian translation.
4. Review before/after the episode, or add words to your own flashcards.

**Tip:** One episode at a time keeps the list **memorable** and **context-rich**; binge-watching without a list is fun, but **one episode + one list** is easier to retain.

---

## Honest limitations (what the bot is *not*)

- It is **not** a full language course (no grammar curriculum, no speaking drills).
- **Translation quality** depends on models and prompts; rare words and tricky idioms may need a second look in a dictionary.
- **Subtitles** must be available for the episode; wrong metadata (wrong episode file) can hurt word–context alignment.
- Lists are **vocabulary-focused**; **phrasal verbs** and longer chunks may be expanded in future versions.

---

## One-line value proposition

> **Turn the episode you just watched into a short, context-aware list of advanced English words—with Russian meanings—so you study what the show actually taught you.**

---

## Related technical docs (for contributors)

- Pipeline overview: `test_runner.py` docstring (download → analyze tiers → translate → optional judge).
- Tier logic: `subtitle_analyzer.py`
- Translation step: `translate_tier_translations.py`
- Quality evaluation tooling: `translation_judge.py`

If you are **only** a learner, you can ignore those files—the bot’s value is: **less noise, more relevant English, faster to Russian meaning, tied to one episode.**
