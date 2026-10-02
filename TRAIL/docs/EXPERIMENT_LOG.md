# Experiment log

Format per entry: what changed / why / expected / actual / metrics / likely cause / keep or revert.

## E-001 tokenizer pre-tokenisation dropped `_` (FAILED, fixed)
* **Changed:** first byte-level BPE pre-tokenisation regex (`[^\W\d_]+` for letters, `[^\s\w]+` for punctuation).
* **Why:** keep letters, punctuation and whitespace in separate pre-tokens.
* **Expected:** exact round-trip on all corpus documents.
* **Actual:** `decode(encode(x)) != x` for 41 of 619 documents (every Python file using `_`).
* **Cause:** `_` is a word character (`\w`) but excluded from the letter class and also from the punctuation class, so no alternative matched it and it was silently dropped.
* **Resolution (kept):** punctuation alternative is now `(?:[^\s\w]|_)+`; a test enumerates every Unicode code point through the pre-tokeniser (0 uncovered) and the corpus round-trip is 619/619 exact. The round-trip check in `trail tokenizer train` is what caught it.

## E-002 tokenizer could not reach the requested vocabulary on a tiny corpus (FAILED, fixed)
* **Actual:** requested 400, got 375 (merges ran out of pairs above `min_frequency`) -> model/tokenizer size mismatch.
* **Resolution (kept):** ids beyond the learned merges are reserved and never produced, so the table size always equals the config.

## E-003 test bugs found while writing the suite (no product defect)
* a test class attribute named `run` shadowed `TestCase.run`; sampling tests passed the generator in the repetition-penalty slot (so "seeded" tests did not test seeding until fixed). Both were test errors; the fixed tests pass and now actually exercise seeding.
