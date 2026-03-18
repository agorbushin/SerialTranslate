# 1. Bot Description: Structure of Messages and Inputs

This document describes the Telegram bot layer: its responsibilities, the structure of messages and user inputs at different levels, and the inputs the bot requires from the translation system.

---

## 1.1 Bot Role

The **bot** (`telegram_bot.py`) is the user-facing layer. It:

- Receives and parses user messages and document uploads
- Handles commands (`/start`, `/next`, `/full`, `/phrasal`)
- Handles inline button callbacks (Full List, Phrasal Verbs, Rare in Series Hard Words, Hard Words Frequent in Series, New Series)
- Orchestrates: series name standardization, subtitle download, word-tier analysis, and translation
- Sends status updates and result messages with a consistent structure
- Persists session context (`last_episode_dir`, `last_series_name`, `last_tier_type`) for navigation

The bot **does not** perform word extraction, tier categorization, or translation logic itself; it invokes the word-tier system (subtitle_analyzer) and the translation system (translate_words) and consumes their outputs.

---

## 1.2 Levels of Interaction

### Level 1: User → Bot (inputs the bot receives)

| Input type | Source | Description | Examples | Context required to route |
|------------|--------|-------------|----------|---------------------------|
| **Text message** | User | Series name and/or season/episode | `"Fallout"`, `"game of thrones s2 e3"`, `"Severance episode 4"`, `"Marvelous Ms Maiszel Ep 1"` | None. The message itself must contain (or imply) series name; season/episode are optional. |
| **Command** | User | Slash command | `/start`, `/next`, `/full`, `/phrasal` | `/start`, `/next`: none. `/full`, `/phrasal`: `last_episode_dir` (and for Full List, `last_tier_type`). You cannot send full list or phrasal verbs until a series/episode has been chosen and results were shown. |
| **Callback query** | Inline button | Button identifier | `full_list`, `rare_hard_words`, `hard_words_frequent`, `phrasal_verbs`, `next_series` | `full_list`, `rare_hard_words`, `hard_words_frequent`, `phrasal_verbs`: `last_episode_dir` (and `last_tier_type` for full_list). `next_series`: none. |
| **Document** | User | Uploaded file | `.srt` or `.zip` subtitle file | None. The file is the input; series/season/episode may be inferred from filename or requested later. |

### Level 2: Bot → User (messages the bot sends)

| Message type | When | Structure |
|--------------|------|-----------|
| **Welcome** | `/start` | Title, short instruction (“type series name”), list of commands, bot version |
| **Prompt for series** | `/next` or callback `next_series` | Short prompt to type series name (with examples) |
| **Status (editable)** | During processing | “Processing request for: *{user_message}*” + stage text (e.g. “Normalizing series name…”, “Downloading subtitle…”, “Translating words…”, “Getting hard words list…”) |
| **Result – Hard Words (Tier 1)** | After tier list ready (from cache or new analysis) | Header: “📺 {series} - S{ss}, E{ee}”, “📊 Hard Usable Words: {count}”, “Top 10 Words to Learn:” list (word → translation), “… and N more”, then inline keyboard |
| **Result – Rare in Series Hard Words (Tier 2)** | Callback `rare_hard_words` | Same structure as above but “📊 Rare in Series Hard Words”, tier_2 data, different button (“Hard Words Frequent in Series” instead of “Rare in Series Hard Words”) |
| **Result – Full List** | Callback `full_list` | Same structure but full list (no “Top 10”), split into messages if long; keyboard unchanged |
| **Result – Phrasal Verbs** | Callback `phrasal_verbs` | Header with series/episode, phrasal verb count, list (phrasal → translation), inline keyboard |
| **Error / guidance** | On failure or ambiguity | Clear error text (e.g. “Could not download subtitle”, “Could not identify the series”) + possible causes + “Use /next to search for another series” or billing link |

### Level 3: Internal flow (bot → other systems)

| Bot action | Target system | Inputs passed |
|------------|---------------|---------------|
| Standardize + download | OpenAI, OpenSubtitles | `user_message`, `season`, `episode` (derived), `status_update_callback` |
| Find existing tier lists | Local filesystem | `series_name`; filter by `S{season}E{episode}` if specified |
| Analyze subtitle | Word-tier system (subtitle_analyzer) | `subtitle_path`, `user_level` (fixed `'C'`) |
| Translate tier list | Translation system | `episode_dir`, `subtitle_path` |
| Translate specific tier file | Translation system | `tier_file` (path), `subtitle_path` |
| Send results | — | `episode_dir`, `update`, `context`; reads tier CSV + `episode_info.json` |

---

## 1.3 Message Structure (detailed)

### Status message (single editable message)

- **Line 1:** “🔍 Processing request for: *{user_message}*”
- **Line 2+:** Stage-dependent, e.g.  
  “⏳ Normalizing series name…”  
  “✅ Identified as: *{series_name}*”  
  “📺 Season {season}, Episode {episode}”  
  “⏳ Downloading subtitle…”  
  “⏳ Analyzing subtitle and creating tier list…”  
  “⏳ Translating words…”  
  “📊 Getting hard words list…”

### Result message (Hard Words / Rare in Series / Full List)

- **Header:** “📺 {series_name} - S{ss}, E{ee}”
- **Count line:** “📊 Hard Usable Words: {n}” or “📊 Rare in Series Hard Words: {n}”
- **Subheader (if top 10):** “Top 10 Words to Learn:” or “Top 10 Rare in Series Hard Words:”
- **List lines:** “1. word → translation” … “10. word → translation”
- **Footer:** “… and N more words.” (or full list in Full List view)
- **Inline keyboard:** 2 rows of buttons (Full List, Phrasal Verbs; Rare in Series Hard Words or Hard Words Frequent in Series; New Series)

### Phrasal verbs message

- **Header:** “📺 {series} - S{ss}, E{ee}”, “🔤 Phrasal Verbs: {count}”
- **List:** “1. phrasal_verb → translation” …
- **Inline keyboard:** Same pattern as above

---

## 1.4 Inputs the Bot Needs from the Translation System

The bot **calls** the translation system (e.g. `translate_tier_list(episode_dir, subtitle_path)` or `translate_specific_tier_file(tier_file, subtitle_path)`) and then **reads from the filesystem** the outputs that the translation system has written. So “inputs from the translation system” here means **the data the bot expects to be present after translation has run**.

| Input | Location / format | Used by bot for |
|-------|-------------------|------------------|
| **Translation success/failure** | Return value of `translate_tier_list()` / `translate_specific_tier_file()` (`True`/`False`) | Decide whether to show “Translation complete” or “Translation failed / timed out” and whether to show words with “N/A” or retry message |
| **Tier CSV with translation column** | `episode_dir / tier_1_hard_usable_words.csv` (and tier_2, tier_4 when relevant) | Display “word → translation” in Hard Words, Rare in Series Hard Words, and Full List messages |
| **Translation column content** | CSV column `translation`: string per row (or empty / `N/A` / `[Translation failed]`) | Show translation next to each word; treat empty/N/A/failed as “N/A” in the message |
| **Name/fantasy tagging column** | CSV column `is_name_or_fantasy` (if present) | Filter or label words when building the displayed list (hide or de-emphasize names/fantasy entities) |
| **Optional example columns** | e.g. `example_en`, `example_translated` in CSV | Not currently used in the bot message body; could be used later for richer display |

### Contract (what the bot assumes after translation)

- **Paths:** Tier files live under `episode_dir`:  
  `tier_1_hard_usable_words.csv`, `tier_2_random_words.csv`, `tier_4_rare_in_series.csv`.
- **CSV format:** Headers include `word` and, after translation, `translation`. Optional: `is_name_or_fantasy`, `vocabulary_level`.
- **In-place update:** The translation system **overwrites or appends columns** in the same CSV files; the bot re-reads those files after calling the translation system.
- **No direct return payload:** The bot does not receive a structured in-memory “result” from the translation system; it only gets a boolean success and then reads from disk.

---

## 1.5 Session Context (user_data)

The bot keeps the following in `context.user_data` so that callbacks and “Full List” know which episode and which list type to show:

| Key | Type | Meaning |
|-----|------|---------|
| `last_episode_dir` | str (path) | Path to `tierlist/SeriesName/S02E03/` |
| `last_series_name` | str | Normalized series name |
| `last_tier_type` | str | `'tier_1'`, `'tier_2'`, or `'tier_4'` for Full List |

---

See **SYSTEM_AND_PIPELINE.md** for the full pipeline and **2_TRANSLATION_SYSTEM.md** for the translation system’s inputs and behavior.
