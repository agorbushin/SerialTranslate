#!/usr/bin/env python3
"""
Extract and gloss phrasal verbs from subtitles.
Phrasal verbs are verb + particle combinations (e.g., "give up", "look for").
Default gloss style is learner-friendly English dictionary definitions.
"""

import re
import csv
import json
from pathlib import Path
from collections import Counter
from typing import Dict, List, Tuple, Optional, Set
from openai import OpenAI
import argparse

# Dual-score gate after translation (see _translate_phrasal_batch rubric).
# Keep only if idiomaticity is high AND literal word-for-word mapping is low.
MIN_IDIOMATICITY_SCORE = 6
MAX_LITERARITY_SCORE = 3  # literality 1 = transparent; must be <= this to keep


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
                bigram = f"{word} {next_word}"
                # Avoid spurious 3-grams like "find out in" when "find out" is already lexicalized.
                if bigram in _COMMON_PHRASAL_SET:
                    pass
                else:
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

Below is a numbered list of candidate PHRASES (2–3 words) taken from subtitles. Many are NOT real phrasal verbs: they may be random adjacency (e.g. "you in", "man in"), tokenizer garbage (e.g. "s up" from contractions), accidental merges across two constructions (e.g. "find out" + "in" as one unit), or ordinary grammar — not lexical phrasal verbs / idiomatic verb–particle combinations.

Keep ONLY phrases that are genuine phrasal verbs or established verb–particle / verb–preposition idioms in English (e.g. "give up", "come on", "look for", "put up with").

REJECT in particular:
- Fragments that are not standard idioms (e.g. two idioms jammed with an extra preposition).
- Readings where the first word is a NOUN, not a verb (e.g. animal "bear" + "in" in "a bear in a trap").
- Candidates whose first word is an inflected/auxiliary form where the list should use the base lemma instead — exclude past-tense-only heads like "jumped off" unless you are certain it is a fixed lexical entry in that form (prefer to reject marginal cases).
- Strings that are not a coherent phrasal-verb entry a learner would study (participial scraps, preposition piles).

Prefer candidates whose first word is a verb in base/infinitive-lemma form when matching subtitle usage.

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


def _phrase_boundary_pattern(phrase: str):
    """Regex for whole phrase as tokens (substring-safe)."""
    parts = phrase.lower().split()
    if not parts:
        return re.compile(r"^$")
    inner = r"\s+".join(re.escape(p) for p in parts)
    return re.compile(rf"\b{inner}\b", re.IGNORECASE)


def _format_phrasal_lines_for_prompt(
    pv_list: List[str],
    examples: Optional[Dict[str, List[str]]],
) -> str:
    lines = []
    ex = examples or {}
    for pv in pv_list:
        xs = ex.get(pv) or []
        if xs:
            for i, line in enumerate(xs[:2], start=1):
                lines.append(f'  - "{pv}" (example {i}): {line[:400]}')
        else:
            lines.append(f'  - "{pv}" (no matched subtitle line)')
    return "\n".join(lines)


def _coerce_phrasality_score(raw: object) -> Optional[int]:
    """Return integer 1–10 or None."""
    if raw is None:
        return None
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw if 1 <= raw <= 10 else None
    if isinstance(raw, float) and raw.is_integer():
        n = int(raw)
        return n if 1 <= n <= 10 else None
    if isinstance(raw, str):
        s = raw.strip()
        if s.isdigit():
            n = int(s)
            return n if 1 <= n <= 10 else None
    return None


def _translate_phrasal_batch(
    client: OpenAI,
    pv_list: List[str],
    subtitle_text: str,
    series_name: str,
    target_language: str,
    examples: Optional[Dict[str, List[str]]],
) -> Tuple[Dict[str, str], Dict[str, int], Dict[str, int], Dict[str, str]]:
    """Returns translations, idiomaticity_scores, literality_scores, score_rationale."""
    context = subtitle_text[:3000] if len(subtitle_text) > 3000 else subtitle_text
    per_phrase = _format_phrasal_lines_for_prompt(pv_list, examples)
    prompt = f"""You are glossing multiword verb units from the TV series "{series_name}" for a **learner list of opaque phrasal / idiomatic verbs only**.

PHRASES (with episode lines where each appears — use these to choose the correct sense):
{per_phrase}

GENERAL SUBTITLE CONTEXT (same episode):
{context[:2000]}

For EACH phrase listed above you must output:

1. **translation** in {target_language}: dictionary-style learner gloss for the sense used here.
   - Keep it concise: usually 3-10 words.
   - Prefer infinitive/base-definition style when natural (e.g., "to stop trying", "to discover").
   - Do NOT output Russian or any other language.

2. **idiomaticity_score** (integer 1-10): How **fixed / non-literal / idiomatic** the English unit is **in this context** as a verb construction worth memorizing as a chunk.
   - **1-3:** Transparent grammar + preposition/particle (e.g. "believe in", "look at", "think about", "wait for", "depend on", "listen to") — the meaning follows from verb + preposition even if colloquial.
   - **4-5:** Somewhat colloquial but still largely compositional.
   - **6-8:** Clearly lexicalized or meaning not obvious from parts alone in this use.
   - **9-10:** Strong opaque phrasal / particle verb (e.g. "give up" = surrender, "make up" = invent/reconcile, "keep up" = not fall behind).

3. **literality_score** (integer 1-10): How **directly** the {target_language} gloss maps **word-for-word** to the English pieces (verb + particle/preposition).
   - **1-3:** Clearly **not** word-for-word; translation is idiomatic or rephrased (good for this list).
   - **4-6:** Partially compositional.
   - **7-10:** Near transparent composition: you can derive the meaning directly from verb + particle/preposition (e.g. "believe in" ≈ "to have faith in"). **These must get high literality** even if the phrase appears in textbooks.

**HARD RULE:** If the pair is essentially **verb + common preposition** and the gloss is a transparent compositional reading (like "believe in" → "to have faith in"), set **idiomaticity_score 1-3** and **literality_score 8-10**. Such items must NOT be recommended for an opaque-phrasal learner list.

4. **score_rationale** (one short English phrase per key, max ~15 words): why you chose those two scores.

Return ONLY JSON with this shape (exact keys for every phrase in the list, exact English spelling):
{{
    "translations": {{ "give up": "to stop trying", "believe in": "to have faith in" }},
    "idiomaticity_scores": {{ "give up": 9, "believe in": 2 }},
    "literality_scores": {{ "give up": 2, "believe in": 9 }},
    "score_rationale": {{ "give up": "opaque particle sense", "believe in": "verb+prep calque" }}
}}"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": (
                    "You write concise English dictionary-style glosses for verb phrases and output strict JSON with keys: "
                    "translations, idiomaticity_scores, literality_scores, score_rationale. "
                    "All score values are integers 1-10. Rationale values are short English strings."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0.3,
        response_format={"type": "json_object"},
    )
    raw = response.choices[0].message.content
    result = json.loads(raw) if raw else {}
    trans_raw = result.get("translations") or {}
    idiom_raw = result.get("idiomaticity_scores") or {}
    lit_raw = result.get("literality_scores") or {}
    rat_raw = result.get("score_rationale") or {}

    translations: Dict[str, str] = {}
    idiomaticity: Dict[str, int] = {}
    literality: Dict[str, int] = {}
    rationale: Dict[str, str] = {}
    expected = set(pv_list)
    for k in expected:
        if k in trans_raw and trans_raw[k] is not None:
            translations[str(k)] = str(trans_raw[k]).strip()
        idi = _coerce_phrasality_score(idiom_raw.get(k))
        if idi is not None:
            idiomaticity[str(k)] = idi
        lit = _coerce_phrasality_score(lit_raw.get(k))
        if lit is not None:
            literality[str(k)] = lit
        r = rat_raw.get(k)
        if isinstance(r, str) and r.strip():
            rationale[str(k)] = r.strip()[:240]
    return translations, idiomaticity, literality, rationale


def translate_phrasal_verbs(
    phrasal_verbs: List[Tuple[str, int]],
    subtitle_text: str,
    series_name: str,
    api_key: str,
    target_language: str = "English",
    examples: Optional[Dict[str, List[str]]] = None,
) -> Tuple[Dict[str, str], Dict[str, int], Dict[str, int], Dict[str, str]]:
    """Translate and score each phrase (idiomaticity + literality + short rationale).

    Caller keeps rows where idiomaticity >= MIN_IDIOMATICITY_SCORE and
    literality <= MAX_LITERARITY_SCORE.
    """
    if not phrasal_verbs:
        return {}, {}, {}, {}

    translations: Dict[str, str] = {}
    idiomaticity_scores: Dict[str, int] = {}
    literality_scores: Dict[str, int] = {}
    rationales: Dict[str, str] = {}
    client = OpenAI(api_key=api_key)
    batch_size = 20

    for batch_start in range(0, len(phrasal_verbs), batch_size):
        batch = phrasal_verbs[batch_start : batch_start + batch_size]
        pv_list = [pv for pv, _ in batch]
        try:
            bt, bi, bl, br = _translate_phrasal_batch(
                client, pv_list, subtitle_text, series_name, target_language, examples
            )
            translations.update(bt)
            idiomaticity_scores.update(bi)
            literality_scores.update(bl)
            rationales.update(br)
            print(
                f"Translated batch {batch_start // batch_size + 1}: "
                f"{len(bt)} phrases, {len(bi)} idiom / {len(bl)} lit scores"
            )
        except Exception as e:
            print(f"Error translating batch {batch_start // batch_size + 1}: {e}")

    def _is_bad(val: str) -> bool:
        t = (val or "").strip()
        if not t:
            return True
        return t.upper() == "N/A" or t.lower() in ("none", "null")

    expected = [pv for pv, _ in phrasal_verbs]
    missing = [
        pv
        for pv in expected
        if _is_bad(translations.get(pv, ""))
        or pv not in idiomaticity_scores
        or pv not in literality_scores
    ]
    if missing:
        try:
            rt, ri, rl, rr = _translate_phrasal_batch(
                client,
                missing,
                subtitle_text,
                series_name,
                target_language,
                examples,
            )
            for k, v in rt.items():
                if not _is_bad(str(v)):
                    translations[k] = str(v).strip()
            idiomaticity_scores.update(ri)
            literality_scores.update(rl)
            rationales.update(rr)
            ok_t = len([p for p in missing if not _is_bad(translations.get(p, ""))])
            ok_i = len([p for p in missing if p in idiomaticity_scores])
            ok_l = len([p for p in missing if p in literality_scores])
            print(
                f"Translation retry: {ok_t}/{len(missing)} glosses, "
                f"{ok_i}/{len(missing)} idiom, {ok_l}/{len(missing)} literality"
            )
        except Exception as e:
            print(f"Translation retry failed: {e}")

    return translations, idiomaticity_scores, literality_scores, rationales


def extract_examples_for_phrasal_verbs(
    subtitle_text: str,
    phrasal_verbs: List[str],
    max_examples: int = 2,
) -> Dict[str, List[str]]:
    """Extract example sentences containing phrasal verbs.

    Prefers token-boundary matches so substrings like \"drop into\" inside
    \"100-foot drop into the water\" are not treated as the phrasal verb.

    Args:
        subtitle_text: Subtitle text
        phrasal_verbs: List of phrasal verbs to find examples for
        max_examples: Maximum examples per phrasal verb

    Returns:
        Dictionary mapping phrasal verb to list of example sentences
    """
    examples: Dict[str, List[str]] = {}
    sentences = re.split(r'[.!?]+', subtitle_text)
    cleaned = []
    for sentence in sentences:
        sent = sentence.strip()
        if len(sent) > 10 and len(sent) < 200:
            cleaned.append(sent)

    for pv in phrasal_verbs:
        pv_examples: List[str] = []
        pv_lower = pv.lower()
        pat = _phrase_boundary_pattern(pv)

        for sent in cleaned:
            if pat.search(sent):
                if sent not in pv_examples:
                    pv_examples.append(sent)
                if len(pv_examples) >= max_examples:
                    break

        if len(pv_examples) < max_examples:
            for sent in cleaned:
                if pv_lower in sent.lower() and sent not in pv_examples:
                    pv_examples.append(sent)
                if len(pv_examples) >= max_examples:
                    break

        examples[pv] = pv_examples[:max_examples]

    return examples


def save_phrasal_verbs(
    phrasal_verbs: Counter,
    translations: Dict[str, str],
    examples: Dict[str, List[str]],
    episode_dir: Path,
    *,
    idiomaticity_scores: Optional[Dict[str, int]] = None,
    literality_scores: Optional[Dict[str, int]] = None,
    score_rationales: Optional[Dict[str, str]] = None,
):
    """Save phrasal verbs CSV with idiomaticity, literality, and rationale columns."""
    episode_dir.mkdir(parents=True, exist_ok=True)
    csv_file = episode_dir / "phrasal_verbs.csv"

    sorted_pvs = sorted(phrasal_verbs.items(), key=lambda x: x[1], reverse=True)
    idiom = idiomaticity_scores or {}
    lit = literality_scores or {}
    rat = score_rationales or {}

    with open(csv_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "phrasal_verb",
                "frequency",
                "translation",
                "idiomaticity_score",
                "literality_score",
                "score_rationale",
                "example",
            ]
        )

        for pv, freq in sorted_pvs:
            translation = translations.get(pv, "N/A")
            pv_examples = examples.get(pv, [])
            example = pv_examples[0] if pv_examples else "N/A"
            writer.writerow(
                [
                    pv,
                    freq,
                    translation,
                    idiom.get(pv, ""),
                    lit.get(pv, ""),
                    rat.get(pv, ""),
                    example,
                ]
            )

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
    translations, idiomaticity_scores, literality_scores, score_rationales = (
        translate_phrasal_verbs(
            sorted_pvs,
            subtitle_text,
            series_name,
            api_key,
            examples=examples,
        )
    )

    def _passes_dual_gate(k: str) -> bool:
        idi = idiomaticity_scores.get(k)
        lit = literality_scores.get(k)
        if idi is None or lit is None:
            return False
        return idi >= MIN_IDIOMATICITY_SCORE and lit <= MAX_LITERARITY_SCORE

    kept_keys = {k for k in verified if _passes_dual_gate(k)}
    missing_idi = [k for k in verified if k not in idiomaticity_scores]
    missing_lit = [k for k in verified if k not in literality_scores]
    fail_idi = [
        k
        for k in verified
        if k in idiomaticity_scores
        and idiomaticity_scores[k] < MIN_IDIOMATICITY_SCORE
    ]
    fail_lit = [
        k
        for k in verified
        if k in literality_scores and literality_scores[k] > MAX_LITERARITY_SCORE
    ]
    dropped = len(verified) - len(kept_keys)
    print(
        f"Dual-score filter (idiomaticity>={MIN_IDIOMATICITY_SCORE}, "
        f"literality<={MAX_LITERARITY_SCORE}): "
        f"kept {len(kept_keys)}, dropped {dropped} "
        f"(missing idiom: {len(missing_idi)}, missing lit: {len(missing_lit)}, "
        f"low idiom: {len(fail_idi)}, high lit: {len(fail_lit)})"
    )

    if not kept_keys:
        print("No phrasal verbs left after dual-score filter")
        return False

    final_counter = Counter({k: verified[k] for k in kept_keys})
    final_translations = {k: translations.get(k, "N/A") for k in kept_keys}
    final_examples = {k: examples.get(k, []) for k in kept_keys}
    final_idiom = {k: idiomaticity_scores[k] for k in kept_keys}
    final_lit = {k: literality_scores[k] for k in kept_keys}
    final_rat = {k: score_rationales.get(k, "") for k in kept_keys}

    print("\nSaving results...")
    save_phrasal_verbs(
        final_counter,
        final_translations,
        final_examples,
        episode_dir,
        idiomaticity_scores=final_idiom,
        literality_scores=final_lit,
        score_rationales=final_rat,
    )
    
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
