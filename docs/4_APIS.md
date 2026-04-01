# 4. APIs: List and Responsibilities

This document lists the external and internal “APIs” the system uses: HTTP APIs (OpenAI, OpenSubtitles), the API health-check module, and the role of each.

---

## 4.1 OpenAI (ChatGPT) API

**Purpose:** Language and translation tasks.

**Used by:** `telegram_bot.py`, `translate_words.py`, `phrasal_verbs.py`.

| Use case | Where | What it does |
|----------|--------|----------------|
| **Series name normalization** | `telegram_bot.normalize_series_name()` | Sends the user’s cleaned input (e.g. “got”, “Marvelous Ms Maiszel”) and asks for the official series name (e.g. “Game of Thrones”, “The Marvelous Mrs. Maisel”). Returns a single string. |
| **Alternative series name** | `telegram_bot.normalize_series_name_alternative()` | When download fails with the first name, asks for an alternative name the series might be known by (e.g. for search). |
| **Name / fantasy-entity tagging** | `translate_words.py` (Stage 1) | Sends the list of words from a tier CSV plus subtitle context; asks which words are proper nouns, fantasy/series-specific entities, or made-up words. Returns a set or list; written to column `is_name_or_fantasy`. |
| **Word translation with context** | `translate_words.translate_words_with_context_async()` (Stage 2) | Sends batches of words + subtitle context + example sentences; asks for translation (and optionally examples) in the target language. Returns a dict `word → { translation, example_en, example_translated }`. |
| **Phrasal verb verification** | `phrasal_verbs.verify_phrasal_verbs_with_chatgpt()` | After deterministic pre-filter (`filter_phrasal_candidates`), sends batches of candidates plus a subtitle excerpt; model returns JSON `valid` list of strings that are genuine phrasal / verb–particle idioms. Counts are preserved only for approved phrases; then translation runs. |
| **Phrasal verb translation** | `phrasal_verbs.translate_phrasal_verbs()` | Translates phrasal verbs into the target language. |

**Typical parameters:** Model (e.g. gpt-4o for name filtering, gpt-4o-mini for speed), API key, prompt text, JSON response format.

**Health checks:** `api_health_check.quick_openai_test()`, `APIHealthChecker.test_openai_api()` – used by the bot before running translation to detect quota, rate limit, or authentication issues and optionally show a message to the user.

---

## 4.2 OpenSubtitles API

**Purpose:** Search and download English subtitles for a given series and episode.

**Used by:** `telegram_bot.py` (via `download_subtitles.py`).

| Use case | Where | What it does |
|----------|--------|----------------|
| **Search subtitles** | `OpenSubtitlesDownloader.search_subtitles(query, languages, season_number, episode_number)` | GET request to OpenSubtitles API with query (series name), language (e.g. en), optional season/episode. Returns a list of subtitle results (file names, IDs, download counts, etc.). |
| **Download subtitle file** | `OpenSubtitlesDownloader.download_subtitle(subtitle_id, output_path)` | Uses the file ID from search to download the subtitle file (e.g. .srt) and save it to the given path. |
| **Best match selection** | `OpenSubtitlesDownloader.download_best_match(query, output_dir, season_number, episode_number)` | Calls search, then scores results (e.g. by name match and popularity), optionally checks season/episode pattern (including E00 for pilot). Downloads the best match and returns its path. |

**Typical parameters:** API key, query, languages, season_number, episode_number, output_dir.

**Health checks:** `api_health_check.quick_opensubtitles_test()`, `APIHealthChecker.test_opensubtitles_api()` – used by the bot before download to detect rate limit or authentication issues; bot may still attempt download and log the result.

---

## 4.3 API Health Check Module

**Purpose:** Lightweight checks to detect API problems before heavy use (translation, download).

**Used by:** `telegram_bot.py`.

| Function / class | What it does |
|------------------|--------------|
| **APIHealthChecker** | Holds API keys; provides `test_openai_api()`, `test_opensubtitles_api()` and error classification. |
| **check_openai_error(error)** | Classifies an OpenAI exception (quota, rate_limit, authentication, other). |
| **quick_openai_test(api_key)** | Short async check (e.g. minimal request) to see if OpenAI is reachable and valid. |
| **quick_opensubtitles_test(api_key)** | Short check that OpenSubtitles API responds (e.g. search or info). |

**Output:** Boolean success, error message string, and optional details (e.g. `is_api_issue`, `error_type`, `action_required` for the bot to show billing or retry guidance).

---

## 4.4 Summary Table

| API / module | Used by | Main role |
|--------------|---------|-----------|
| **OpenAI** | Bot, translate_words, phrasal_verbs | Series name normalization; alternative name; name/fantasy tagging; word translation; phrasal verb verification and translation. |
| **OpenSubtitles** | Bot (download_subtitles) | Search and download subtitles by series name and season/episode. |
| **api_health_check** | Bot | Test OpenAI and OpenSubtitles before translation/download; classify errors (quota, rate limit, auth). |

---

## 4.5 Who Does Not Use Which API

- **Word-tier system** (`subtitle_analyzer.py`): Does **not** call OpenAI or OpenSubtitles. It only reads the subtitle file (already on disk) and local data (frequency list, filters, vocabulary file).
- **Translation system** (`translate_words.py`): Uses **OpenAI** only (for tagging and translation). Does not call OpenSubtitles.
- **Bot** (`telegram_bot.py`): Uses **OpenAI** (normalization), **OpenSubtitles** (via download_subtitles), and **api_health_check** for both.

For end-to-end flow and how these APIs fit into the pipeline, see **SYSTEM_AND_PIPELINE.md**.
