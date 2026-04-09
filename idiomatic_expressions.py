#!/usr/bin/env python3
"""
Extract repeated multiword idiomatic expressions from subtitles (standalone).

Pipeline: token n-grams (default 3–6) with min occurrence count → deterministic
filters → LLM verification → translation + idiomaticity score → CSV.

Does not depend on phrasal_verbs.py (no OpenAI import at module level from there).
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from openai import OpenAI

from env_config import resolve_openai_api_key
from subtitle_text_utils import get_subtitle_text

VERIFY_MODEL = "gpt-4o-mini"
TRANSLATE_MODEL = "gpt-4o-mini"

# Translation-time quality gate (like phrasality score in phrasal_verbs.py).
# Lower than this => expression is dropped from final CSV.
MIN_IDIOMATICITY_SCORE = 5

_DEFAULT_MIN_N = 3
_DEFAULT_MAX_N = 6
_DEFAULT_MIN_OCCURRENCES = 2
_DEFAULT_MAX_CANDIDATES = 220

_EN_STOP = frozenset(
    """
    a an the and or but if so as at by for from in into of on onto to too
    up down out off over with without about above after again against all
    almost also always am any are around as be been being both can could
    did do does doing done each else ever every few for get got had has have
    having he her here hers him his how i if in is it its just least like
    ll me more most much my no nor not now of off on once only or other our
    ours out re s same she should so some such than that the their them
    then there these they this those through to too under until ve very was
    we were what when where which while who whom why will with would yet
    you your yours
    """.split()
)

# High-frequency compositional chunks (not worth LLM tokens).
_BORING_NGRAMS = frozenset(
    {
        "one of the",
        "some of the",
        "any of the",
        "most of the",
        "many of the",
        "much of the",
        "none of the",
        "part of the",
        "end of the",
        "out of the",
        "top of the",
        "rest of the",
        "middle of the",
        "bottom of the",
        "front of the",
        "back of the",
        "side of the",
        "lot of the",
        "kind of the",
        "sort of the",
        "couple of the",
        "number of the",
        "bit of the",
        "piece of the",
        "i don t know",
        "i do not know",
        "you know what",
        "what do you",
        "what are you",
        "what is your",
        "what s your",
        "i want to",
        "i need to",
        "i have to",
        "i got to",
        "going to be",
        "have to be",
        "has to be",
        "had to be",
        "there is a",
        "there are a",
        "this is the",
        "that is the",
        "it s a",
        "it is a",
        "the first time",
        "for the first time",
        "a civil war",
        "the civil war",
        "a hundred percent",
        "one hundred percent",
        "it is a big deal",
        "this is a big deal",
        "i m gonna",
        "i am gonna",
        "this wasn t",
        "this was not",
        "ruin my life",
        "having the best time",
        "the quiet room",
        "ride the carousel",
        "lot of shit",
    }
)

# Leading tokens often produced by SRT tokenizer splitting contractions.
_FRAGMENT_HEADS = frozenset({"s", "m", "re", "ve", "ll", "d", "t"})

# Trailing function words often indicate a cut-off title or subtitle break.
_TRAILING_JUNK = frozenset({"and", "or", "the", "a", "an", "to", "of", "in", "on", "for"})


def tokenize_words(text: str) -> List[str]:
    return re.findall(r"\b\w+\b", text.lower())


def extract_repeated_ngrams(
    tokens: List[str],
    *,
    min_n: int,
    max_n: int,
    min_occurrences: int,
) -> Counter:
    """Count space-separated n-grams that appear at least min_occurrences times."""
    out: Counter = Counter()
    if not tokens or min_n < 1 or max_n < min_n:
        return out
    L = len(tokens)
    for n in range(min_n, max_n + 1):
        if L < n:
            continue
        for i in range(L - n + 1):
            chunk = tokens[i : i + n]
            phrase = " ".join(chunk)
            out[phrase] += 1
    return Counter({k: v for k, v in out.items() if v >= min_occurrences})


def _stopword_ratio(phrase: str) -> float:
    parts = phrase.split()
    if not parts:
        return 1.0
    sw = sum(1 for p in parts if p in _EN_STOP)
    return sw / len(parts)


def filter_ngram_candidates(
    counter: Counter,
    *,
    max_stopword_ratio: float = 0.65,
    boring: Optional[Set[str]] = None,
) -> Counter:
    """Drop stopword-heavy spans, tokenizer fragments, and known compositional boilerplate."""
    boring = boring or _BORING_NGRAMS
    out: Counter = Counter()
    for phrase, count in counter.items():
        parts = phrase.split()
        if len(parts) < 2:
            continue
        if phrase in boring:
            continue
        if parts[0] in _FRAGMENT_HEADS:
            continue
        if len(parts) >= 4 and parts[-1] in _TRAILING_JUNK:
            continue
        if all(p in _EN_STOP for p in parts):
            continue
        if _stopword_ratio(phrase) > max_stopword_ratio:
            continue
        out[phrase] = count
    return out


def _phrase_boundary_pattern(phrase: str) -> re.Pattern[str]:
    parts = phrase.lower().split()
    if not parts:
        return re.compile(r"^$")
    inner = r"\s+".join(re.escape(p) for p in parts)
    return re.compile(rf"\b{inner}\b", re.IGNORECASE)


def _is_consecutive_subsequence(short_tokens: List[str], long_tokens: List[str]) -> bool:
    if not short_tokens or len(short_tokens) > len(long_tokens):
        return False
    m, n = len(short_tokens), len(long_tokens)
    for i in range(n - m + 1):
        if long_tokens[i : i + m] == short_tokens:
            return True
    return False


def dedupe_subsumed_phrases(
    phrases_with_counts: List[Tuple[str, int]],
    approved: Set[str],
) -> Set[str]:
    """Drop shorter phrases that are a consecutive token subsequence of a longer kept phrase."""
    items = [(p, c) for p, c in phrases_with_counts if p in approved]
    items.sort(key=lambda pc: (-len(pc[0].split()), -pc[1], pc[0]))
    kept: List[str] = []
    for p, _ in items:
        pt = p.split()
        if any(_is_consecutive_subsequence(pt, k.split()) for k in kept):
            continue
        kept[:] = [k for k in kept if not _is_consecutive_subsequence(k.split(), pt)]
        kept.append(p)
    return set(kept)


def extract_examples_for_phrases(
    subtitle_text: str,
    phrases: List[str],
    max_examples: int = 2,
) -> Dict[str, List[str]]:
    examples: Dict[str, List[str]] = {}
    sentences = re.split(r"[.!?]+", subtitle_text)
    cleaned: List[str] = []
    for sentence in sentences:
        sent = sentence.strip()
        if len(sent) > 10 and len(sent) < 260:
            cleaned.append(sent)

    for ph in phrases:
        ph_examples: List[str] = []
        pat = _phrase_boundary_pattern(ph)
        for sent in cleaned:
            if pat.search(sent) and sent not in ph_examples:
                ph_examples.append(sent)
                if len(ph_examples) >= max_examples:
                    break
        if len(ph_examples) < max_examples:
            ph_lower = ph.lower()
            for sent in cleaned:
                if ph_lower in sent.lower() and sent not in ph_examples:
                    ph_examples.append(sent)
                    if len(ph_examples) >= max_examples:
                        break
        examples[ph] = ph_examples[:max_examples]
    return examples


def verify_idioms_with_llm(
    candidates: List[str],
    subtitle_text: str,
    series_name: str,
    api_key: str,
    batch_size: int = 22,
    model: str = VERIFY_MODEL,
) -> Set[str]:
    if not candidates:
        return set()
    client = OpenAI(api_key=api_key)
    approved: Set[str] = set()
    ctx_snip = subtitle_text[:2800]

    for batch_start in range(0, len(candidates), batch_size):
        batch = candidates[batch_start : batch_start + batch_size]
        numbered = "\n".join(f"{i + 1}. {p}" for i, p in enumerate(batch))

        prompt = f"""You are a linguist judging English multiword expressions for the TV series "{series_name}".

Below is a numbered list of candidate PHRASES taken from subtitles. Each appeared multiple times in this episode.
Many are NOT useful idioms: they may be ordinary grammar, high-frequency compositional chunks, random collocations, or dialogue fragments.

Keep ONLY phrases that are **idiomatic or formulaic** in English — fixed or semi-fixed expressions a learner would study as a unit, including:
- figurative idioms ("bend the rules", "read between the lines")
- discourse / conversational formulas ("for what it s worth", "if you ask me")
- strong opaque collocations that are not plain compositional ("fair enough" style — but multiword only)

REJECT:
- Plain syntax or transparent combinations ("in the room", "on the table", "going to the")
- Verb + particle **phrasal verbs** as the main entry (e.g. "give up", "look for") — those belong in a separate phrasal-verb list
- Fragments that are not a coherent expression — especially **subtitle tokenizer breaks** (leading "s ", "m ", "re ", "i m " fragments, or lines ending mid-title with "and", "of", "the")
- **Proper names, place names, fictional titles, house names, lore terms** (e.g. "king s landing", "of house targaryen", "the first men")
- **Full independent clauses** that are ordinary sentences, not conventional formulas (e.g. "i don t fight in tournaments")
- Generic time/quantity phrases ("the first time", "a civil war" as literal NP), meta lines ("thank you in dothraki")
- Named-entity or plot-specific strings that are not general English idioms

CANDIDATES:
{numbered}

SUBTITLE EXCERPT (context only):
{ctx_snip}

Return ONLY JSON: {{"valid": ["phrase1", ...]}}
Each string in "valid" MUST match a candidate EXACTLY (same spelling and spacing)."""

        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You judge idiomatic multiword expressions. "
                            "Respond only with valid JSON: an object with key 'valid' (array of strings)."
                        ),
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
                f"Idiom verify batch {batch_start // batch_size + 1}: "
                f"{len([x for x in valid_list if isinstance(x, str) and x in batch_set])}/"
                f"{len(batch)} kept"
            )
        except Exception as e:
            print(f"Error verifying idiom batch {batch_start // batch_size + 1}: {e}")

    return approved


def apply_verified(counter: Counter, approved: Set[str]) -> Counter:
    return Counter({k: counter[k] for k in counter if k in approved})


def _coerce_score(raw: object) -> Optional[int]:
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw if 1 <= raw <= 10 else None
    if isinstance(raw, float) and raw.is_integer():
        n = int(raw)
        return n if 1 <= n <= 10 else None
    if isinstance(raw, str) and raw.strip().isdigit():
        n = int(raw.strip())
        return n if 1 <= n <= 10 else None
    return None


def _extract_idiomacy_scores(payload: Dict[str, object]) -> Dict[str, int]:
    """Accept both legacy and requested naming: idiomaticity_scores / idiomacy_ratings."""
    raw = payload.get("idiomacy_ratings")
    if not isinstance(raw, dict):
        raw = payload.get("idiomaticity_scores")
    if not isinstance(raw, dict):
        return {}
    out: Dict[str, int] = {}
    for k, v in raw.items():
        if not isinstance(k, str):
            continue
        score = _coerce_score(v)
        if score is not None:
            out[k] = score
    return out


def _format_phrase_lines(phrases: List[str], examples: Optional[Dict[str, List[str]]]) -> str:
    lines = []
    ex = examples or {}
    for ph in phrases:
        xs = ex.get(ph) or []
        if xs:
            for i, line in enumerate(xs[:2], start=1):
                lines.append(f'  - "{ph}" (example {i}): {line[:400]}')
        else:
            lines.append(f'  - "{ph}" (no example)')
    return "\n".join(lines)


def translate_idioms(
    phrases: List[Tuple[str, int]],
    subtitle_text: str,
    series_name: str,
    api_key: str,
    target_language: str = "Russian",
    examples: Optional[Dict[str, List[str]]] = None,
    model: str = TRANSLATE_MODEL,
    *,
    _retry_once: bool = True,
) -> Tuple[Dict[str, str], Dict[str, int]]:
    if not phrases:
        return {}, {}

    client = OpenAI(api_key=api_key)
    translations: Dict[str, str] = {}
    scores: Dict[str, int] = {}
    batch_size = 18
    ctx = subtitle_text[:2800]

    for batch_start in range(0, len(phrases), batch_size):
        batch = phrases[batch_start : batch_start + batch_size]
        ph_list = [p for p, _ in batch]
        per_phrase = _format_phrase_lines(ph_list, examples)
        prompt = f"""You translate idiomatic / formulaic English phrases from "{series_name}".

PHRASES (with episode lines when available):
{per_phrase}

CONTEXT:
{ctx[:2000]}

For EACH phrase output:
1. A natural translation in {target_language} for how it is used here (short gloss OK). Preserve **register**: profanity, emphasis, and rudeness should match the English force (do not soften "fuck", "shit", etc. into neutral words unless the example line is clearly mild).
2. If the English is a subtitle fragment, infer the intended **whole formula** from the example line and translate that natural utterance (do not leave broken Russian).
3. Each gloss must match **only** that English phrase and its examples — never paste unrelated dialogue from elsewhere in the episode.
4. Provide an integer **idiomacy_rating** 1–10 for each phrase (same idea as phrasality score):
   - 1-3 = mostly literal/compositional phrase (drop candidates like "the quiet room")
   - 4-6 = mixed
   - 7-10 = strongly idiomatic/formulaic

Return ONLY JSON:
{{
  "translations": {{"phrase": "gloss"}},
  "idiomacy_ratings": {{"phrase": 8}}
}}
Include every phrase as a key in BOTH objects."""

        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You translate idioms and score idiomaticity. "
                            "Respond only with JSON: translations and idiomacy_ratings objects."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.25,
                response_format={"type": "json_object"},
            )
            raw = response.choices[0].message.content
            result = json.loads(raw) if raw else {}
            tr = result.get("translations") or {}
            sc = _extract_idiomacy_scores(result)
            for k in ph_list:
                if k in tr and tr[k] is not None:
                    translations[k] = str(tr[k]).strip()
                c = sc.get(k)
                if c is not None:
                    scores[k] = c
            print(
                f"Idiom translate batch {batch_start // batch_size + 1}: "
                f"{len([k for k in ph_list if k in translations])} glosses"
            )
        except Exception as e:
            print(f"Error translating idiom batch {batch_start // batch_size + 1}: {e}")

    def _bad_gloss(val: str) -> bool:
        t = (val or "").strip()
        if not t:
            return True
        return t.upper() == "N/A" or t.lower() in ("none", "null")

    expected = [p for p, _ in phrases]
    missing = [
        p
        for p in expected
        if _bad_gloss(translations.get(p, "")) or p not in scores
    ]
    if missing and _retry_once:
        freq_map = {p: c for p, c in phrases}
        miss_pairs = [(p, freq_map[p]) for p in missing if p in freq_map]
        try:
            retry_t, retry_s = translate_idioms(
                miss_pairs,
                subtitle_text,
                series_name,
                api_key,
                target_language=target_language,
                examples=examples,
                model=model,
                _retry_once=False,
            )
            for k, v in retry_t.items():
                if not _bad_gloss(str(v)):
                    translations[k] = str(v).strip()
            scores.update(retry_s)
            ok_t = len([p for p in missing if not _bad_gloss(translations.get(p, ""))])
            ok_s = len([p for p in missing if p in scores])
            print(
                f"Idiom translation retry: {ok_t}/{len(missing)} glosses, "
                f"{ok_s}/{len(missing)} scores"
            )
        except Exception as e:
            print(f"Idiom translation retry failed: {e}")

    return translations, scores


def save_idiomatic_expressions(
    counter: Counter,
    translations: Dict[str, str],
    examples: Dict[str, List[str]],
    episode_dir: Path,
    idiomaticity_scores: Optional[Dict[str, int]] = None,
    *,
    series_name: str = "",
    subtitle_path: Optional[Path] = None,
    season_number: int = 1,
    episode_number: int = 1,
) -> Path:
    episode_dir.mkdir(parents=True, exist_ok=True)
    csv_path = episode_dir / "idiomatic_expressions.csv"
    rows = sorted(counter.items(), key=lambda x: x[1], reverse=True)
    scores = idiomaticity_scores or {}

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            ["expression", "frequency", "translation", "idiomacy_rating", "example"]
        )
        for ph, freq in rows:
            exs = examples.get(ph) or []
            example = exs[0] if exs else "N/A"
            w.writerow(
                [
                    ph,
                    freq,
                    translations.get(ph, "N/A"),
                    scores.get(ph, ""),
                    example,
                ]
            )

    info: Dict[str, object] = {
        "series": series_name,
        "season_number": season_number,
        "episode_number": episode_number,
        "artifact": "idiomatic_expressions",
        "source_subtitle": subtitle_path.name if subtitle_path else "",
    }
    (episode_dir / "idiomatic_extraction_info.json").write_text(
        json.dumps(info, indent=2), encoding="utf-8"
    )
    print(f"Saved {len(rows)} idiomatic expressions to {csv_path}")
    return csv_path


def extract_idioms_from_episode(
    subtitle_path: Path,
    episode_dir: Path,
    series_name: str,
    api_key: str,
    *,
    min_n: int = _DEFAULT_MIN_N,
    max_n: int = _DEFAULT_MAX_N,
    min_occurrences: int = _DEFAULT_MIN_OCCURRENCES,
    max_candidates: int = _DEFAULT_MAX_CANDIDATES,
    target_language: str = "Russian",
    skip_translate: bool = False,
    season_number: int = 1,
    episode_number: int = 1,
    min_idiomacy_rating: int = MIN_IDIOMATICITY_SCORE,
) -> bool:
    print(f"\n{'='*60}\nIDIOMATIC EXPRESSIONS\n{'='*60}\n")
    text = get_subtitle_text(subtitle_path)
    if not text:
        print("Error: empty subtitle text")
        return False
    print(f"Loaded {len(text)} chars from {subtitle_path.name}")

    tokens = tokenize_words(text)
    raw = extract_repeated_ngrams(
        tokens, min_n=min_n, max_n=max_n, min_occurrences=min_occurrences
    )
    filtered = filter_ngram_candidates(raw)
    print(
        f"After n-gram filter: {len(filtered)} unique "
        f"({sum(filtered.values())} occurrences), min_n={min_n} max_n={max_n} min_occ≥{min_occurrences}"
    )
    if not filtered:
        print("No repeated n-grams passed filters")
        return False

    ordered = sorted(filtered.items(), key=lambda x: (-x[1], -len(x[0].split())))
    candidate_strings = [p for p, _ in ordered[:max_candidates]]

    print("\nVerifying with LLM...")
    approved = verify_idioms_with_llm(
        candidate_strings, text, series_name, api_key
    )
    verified = apply_verified(filtered, approved)
    print(f"After LLM verify: {len(verified)} phrases")

    if not verified:
        print("Nothing left after verification")
        return False

    ordered_vc = sorted(verified.items(), key=lambda x: (-x[1], -len(x[0].split())))
    deduped = dedupe_subsumed_phrases(ordered_vc, set(verified.keys()))
    verified = Counter({k: verified[k] for k in verified if k in deduped})
    print(f"After subsumption dedupe: {len(verified)} phrases")

    if not verified:
        return False

    sorted_phrases = sorted(verified.items(), key=lambda x: x[1], reverse=True)
    phrase_list = [p for p, _ in sorted_phrases]
    examples = extract_examples_for_phrases(text, phrase_list)

    translations: Dict[str, str] = {p: "N/A" for p in phrase_list}
    idiomaticity_scores: Dict[str, int] = {}

    if not skip_translate:
        print("\nTranslating...")
        translations, idiomaticity_scores = translate_idioms(
            sorted_phrases,
            text,
            series_name,
            api_key,
            target_language=target_language,
            examples=examples,
        )

    kept_keys = set(phrase_list)
    if not skip_translate:
        kept_keys = {
            k
            for k in verified
            if idiomaticity_scores.get(k) is not None
            and idiomaticity_scores[k] >= min_idiomacy_rating
        }
        low = [k for k in verified if k not in kept_keys]
        print(
            f"Idiomacy filter (min {min_idiomacy_rating}): kept {len(kept_keys)}, dropped {len(low)}"
        )

    if not kept_keys:
        print("No rows left after idiomaticity filter")
        return False

    final_counter = Counter({k: verified[k] for k in kept_keys})
    save_idiomatic_expressions(
        final_counter,
        translations,
        examples,
        episode_dir,
        idiomaticity_scores=idiomaticity_scores if not skip_translate else None,
        series_name=series_name,
        subtitle_path=subtitle_path,
        season_number=season_number,
        episode_number=episode_number,
    )
    print(f"\n{'='*60}\nIDIOMATIC EXTRACTION COMPLETE\n{'='*60}\n")
    return True


def main() -> None:
    p = argparse.ArgumentParser(description="Extract idiomatic expressions from subtitles")
    p.add_argument("--subtitle", "-s", type=str, required=True)
    p.add_argument("--output", "-o", type=str, required=True)
    p.add_argument("--series", type=str, required=True)
    p.add_argument("--api-key", type=str, default="", help="Or set OPENAI_API_KEY")
    p.add_argument("--min-n", type=int, default=_DEFAULT_MIN_N)
    p.add_argument("--max-n", type=int, default=_DEFAULT_MAX_N)
    p.add_argument("--min-occurrences", type=int, default=_DEFAULT_MIN_OCCURRENCES)
    p.add_argument("--max-candidates", type=int, default=_DEFAULT_MAX_CANDIDATES)
    p.add_argument("--target-language", type=str, default="Russian")
    p.add_argument("--skip-translate", action="store_true")
    p.add_argument(
        "--min-idiomacy-rating",
        type=int,
        default=MIN_IDIOMATICITY_SCORE,
        help="Minimum translation-time idiomacy rating (1-10) to keep rows",
    )
    p.add_argument("--season", type=int, default=1)
    p.add_argument("--episode", type=int, default=1)
    args = p.parse_args()

    key = resolve_openai_api_key(args.api_key or None)
    if not key:
        print("Error: set OPENAI_API_KEY or pass --api-key")
        return

    sp = Path(args.subtitle)
    if not sp.exists():
        print(f"Error: subtitle not found: {sp}")
        return

    extract_idioms_from_episode(
        sp,
        Path(args.output),
        args.series,
        key,
        min_n=args.min_n,
        max_n=args.max_n,
        min_occurrences=args.min_occurrences,
        max_candidates=args.max_candidates,
        target_language=args.target_language,
        skip_translate=args.skip_translate,
        season_number=args.season,
        episode_number=args.episode,
        min_idiomacy_rating=args.min_idiomacy_rating,
    )


if __name__ == "__main__":
    main()
