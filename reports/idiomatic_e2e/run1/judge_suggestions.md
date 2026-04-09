# Judge improvement_suggestions (run1)

- [game_of_thrones_s1e1] Add a filtering step that excludes proper nouns, title fragments, and compositional noun phrases unless they function as repeated discourse formulas.
- [game_of_thrones_s1e1] Require each candidate to be validated against a definition of idiomaticity or formulaicity, not just frequency in the episode transcript.
- [euphoria_s1e4] Filter candidates with a stricter idiom/formula test: keep only expressions that are opaque, strongly conventionalized, or clearly discourse-formulaic, and exclude plain grammar frames and literal phrases.
- [euphoria_s1e4] Require context-sensitive Russian glosses that preserve register and force, especially for profanity and emphasis (e.g. 'whatever the fuck', 'no fucking way').
- [euphoria_s1e4] Normalize subtitle fragments before evaluation so entries include missing auxiliaries/articles and can be translated as full natural Russian utterances.
- [fallout_s2e3] Add a validation step that filters out truncated subtitle fragments and requires a complete clause or a recognized multiword formula before labeling an item as an idiom.
- [fallout_s2e3] Use a whitelist/blacklist heuristic: keep opaque or conventionalized expressions, but exclude transparent noun phrases like "a civil war" and generic time phrases like "the first time" unless there is clear idiomatic evidence.
