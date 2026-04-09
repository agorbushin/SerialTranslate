# Judge improvement_suggestions (run2)

- [game_of_thrones_s1e1] Filter out transparent title fragments and proper-noun coordinations unless they function as fixed episode formulas.
- [game_of_thrones_s1e1] Require each Russian gloss to be a direct, context-matched translation of the exact subtitle line, not a paraphrase or unrelated sentence.
- [game_of_thrones_s1e1] Add an idiom-vs-title-vs-literal-phrase classifier before translation evaluation to reduce false positives.
- [euphoria_s1e4] Filter out plain grammatical fragments and transparent collocations unless they recur as fixed discourse formulas with clear pragmatic value.
- [euphoria_s1e4] Require each Russian gloss to be a complete, natural learner-facing equivalent in the episode context, not a literal word-for-word fragment.
- [euphoria_s1e4] Add an automatic check for idiom-likeness: keep exclamations, discourse markers, and opaque slang formulas; reject routine syntax patterns like "I hadn't" or "please don't".
- [fallout_s2e3] Tighten extraction rules to exclude transparent grammatical chunks and ordinary time phrases unless they recur as episode-specific catchphrases.
- [fallout_s2e3] Add a filter that prioritizes opaque or semi-opaque collocations and discourse formulas, and down-ranks contracted obligation patterns like 'gotta be ready'.
