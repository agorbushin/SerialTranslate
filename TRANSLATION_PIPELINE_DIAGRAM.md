# Translation Pipeline - Complete Flow Diagram

## Overview

The translation pipeline has 4 main stages:
1. **Subtitle Analysis** → Creates tier lists
2. **Name/Fantasy Entity Filtering** → Flags names and simple words
3. **Translation** → Translates words with context
4. **Display** → Shows results to user

## Complete Pipeline Flow

```mermaid
flowchart TD
    A[User Request: 'Game of Thrones S03E04'] --> B[handle_message]
    B --> C{Existing Tier Lists?}
    C -->|Yes| D[Use Existing]
    C -->|No| E[Download/Analyze Subtitle]
    E --> F[subtitle_analyzer.py]
    F --> G[Create 5 Tier Files]
    G --> H[tier_1_hard_usable_words.csv]
    G --> I[tier_2_random_words.csv]
    G --> J[tier_3_common_words.csv]
    G --> K[tier_4_rare_in_series.csv]
    G --> L[tier_5_filtered_words.csv]
    
    D --> M[Check Translation Status]
    M --> N{Translation Needed?}
    N -->|Yes| O[translate_tier_list]
    N -->|No| P[Display Results]
    
    O --> Q[translate_episode]
    Q --> R{Which Tiers?}
    R -->|Default| S[Translate tier_1 ✅]
    R -->|Default| T[Translate tier_2 ✅]
    R -->|Default| U[tier_4 ❌ NOT TRANSLATED]
    
    S --> V[translate_tier_file]
    T --> V
    V --> W[STAGE 1: Name Filtering]
    W --> X[STAGE 1.5: Simple Word Detection]
    X --> Y[STAGE 2: Translation]
    Y --> Z[Save Translations to CSV]
    
    Z --> P
    P --> AA[User Clicks 'Full List']
    AA --> AB[send_full_list]
    AB --> AC{Which Tier?}
    AC -->|tier_4| AD[Read tier_4_rare_in_series.csv]
    AC -->|tier_1| AE[Read tier_1_hard_usable_words.csv]
    AC -->|tier_2| AF[Read tier_2_random_words.csv]
    
    AD --> AG{Has Translation Column?}
    AG -->|No| AH[Show N/A for all words ❌]
    AG -->|Yes| AI[Display Translations]
    
    AE --> AI
    AF --> AI
```

## Translation Pipeline Details

### Stage 1: Subtitle Analysis
**Location:** `subtitle_analyzer.py`

**Input:** Subtitle file (.srt)
**Output:** 5 tier CSV files

**Process:**
1. Parse subtitle → Extract words
2. Count frequencies (series + English)
3. Load vocabulary levels (A1-C2)
4. Categorize into tiers:
   - **Tier 1**: Low English freq, High series freq (best for learning)
   - **Tier 2**: Low English freq, Low series freq (rare words)
   - **Tier 3**: High English freq, High series freq (common words)
   - **Tier 4**: High English freq, Low series freq (common but rare in series) ⚠️
   - **Tier 5**: Filtered words (Oxford 3000, simple words)

### Stage 2: Translation Process

**Location:** `translate_words.py` → `translate_episode()`

**Current Behavior:**
- ✅ Translates `tier_1_hard_usable_words.csv`
- ✅ Translates `tier_2_random_words.csv`
- ❌ **Does NOT translate `tier_4_rare_in_series.csv`**
- ❌ Does NOT translate tier_3 or tier_5

**Translation Steps (for tier_1 and tier_2):**

```mermaid
flowchart LR
    A[translate_tier_file] --> B[STAGE 1: Name Filtering]
    B --> C[Load Name Databases]
    B --> D[ChatGPT Filtering GPT-4o]
    B --> E[Add is_name_or_fantasy column]
    
    E --> F[STAGE 1.5: Simple Words]
    F --> G[Check Vocabulary Level]
    F --> H[Check Easy Words Filter]
    F --> I[Check High Frequency]
    
    I --> J[STAGE 2: Translation]
    J --> K[Extract Examples from Subtitles]
    J --> L[Translate in Batches 10 words]
    J --> M[GPT-4o-mini with Context]
    J --> N[Validate Translations]
    J --> O[Retry Failed Translations]
    
    O --> P[Save to CSV]
```

### Stage 3: Display Results

**Functions:**
- `send_tier_list_results()` → Shows tier_1 (with translation check ✅)
- `send_rare_hard_words()` → Shows tier_2 (with translation check ✅)
- `send_full_list()` → Shows tier_1/tier_2/tier_4 (❌ NO translation check for tier_4)

## Problem: tier_4 Translation Failure

### Root Cause

**tier_4_rare_in_series.csv is never translated:**

1. **Default Translation Pipeline:**
   - `translate_episode()` only translates tier_1 and tier_2
   - tier_4 is completely skipped

2. **Display Function:**
   - `send_full_list()` can display tier_4
   - But has NO translation check/trigger
   - Just reads the file and shows "N/A" if no translations

3. **Result:**
   - tier_4 files have no `translation` column
   - All words show "N/A" when displayed

### Code Evidence

**translate_episode() - lines 1220-1248:**
```python
# Translate both tier 1 and tier 2
tier_1_file = episode_dir / "tier_1_hard_usable_words.csv"
tier_2_file = episode_dir / "tier_2_random_words.csv"
# ❌ tier_4 is NOT included
```

**send_full_list() - lines 3067-3089:**
```python
# Read tier list
words_data = []
with open(tier_file, 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for row in reader:
        words_data.append(row)
# ❌ NO translation check before reading
# ❌ NO translation trigger
```

## Solution

Add translation check and trigger to `send_full_list()` for tier_4, matching the logic in `send_tier_list_results()` and `send_rare_hard_words()`.

This will:
1. Detect when tier_4 needs translation
2. Automatically trigger translation
3. Show "⏳ Translating words..." message
4. Retry failed translations
