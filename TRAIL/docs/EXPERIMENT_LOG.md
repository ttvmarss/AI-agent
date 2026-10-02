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

## E-004 first real pretraining run (KEPT)
* **Changed:** trained `configs/trail_micro.yaml` from random initialisation: 3000 steps x 8,192 tokens = 24.6M tokens (~2.6 epochs of a 9.36M-token corpus), AdamW lr 3e-3 cosine, curriculum of 3 phases, CPU, ~64 min.
* **Expected:** loss falls well below ln(2048)=7.62; fluent-looking but not meaningful text; weak reasoning.
* **Actual:** train loss 7.1 -> 2.30; validation loss 2.67-2.73 (perplexity 14.4, 1.68 bits/byte). By category (val loss): structured data 1.67, code 2.05, language 3.20, technical 3.26. Generations are locally grammatical English, Python- and JSON-shaped text, with no factual content. Reasoning probe 3/12 (chance 3/12). Coding probe 8/10 (chance 2.5/10): consistent with 10 MB of Python standard library in the corpus, and the probe is tiny (10 items), so the margin is indicative only.
* **Likely cause of the gap between code and language:** code is 38% of the corpus with highly regular syntax; the language set is 12 novels (~9M chars), far too small for the model to learn meaning.
* **Decision:** keep. Next experiment: more and more varied language data before any architecture change; scale only after measuring data-limited vs capacity-limited behaviour (train/val gap is small at 2.30/2.7, so this run is data-limited, not overfit).

## E-005 instruct stage on templated identity data (KEPT with caveat)
* **Changed:** 300 steps on ~600 templated identity/simple-task examples (loss on answer tokens only) mixed with replay of pretraining windows.
* **Expected:** correct identity answers on training prompts; partial generalisation to held-out paraphrases; no capability collapse.
* **Actual:** instruct loss 0.002 (the templated set is memorised); replay loss ~2.6 (validation 2.71 vs base 2.67: little forgetting). Held-out paraphrases (6 prompts): 5/6 pass the lenient criterion "mentions TRAIL and names no other vendor", but reading the answers, only ~4/6 are actually correct ("Say your name." -> "Market."; "Which architecture do you use?" -> the origin sentence). Simple tasks on unseen inputs fail ("What is 3 plus 4?" -> "5"; "Write river in capital letters." -> "APPLE"). Asked "Are you ChatGPT?" it answered a different identity sentence rather than the denial.
* **Likely cause:** 5M parameters and a small templated set produce pattern matching to the nearest trained question, not understanding.
* **Decision:** keep as the V1 identity stage; do not present it as instruction following. The instruct set needs far more varied data.
