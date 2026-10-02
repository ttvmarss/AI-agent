# TRAIL Data Foundry

`trail data prepare --config configs/trail_micro.yaml` runs:

raw files -> format detection (binary/unreadable dropped) -> normalisation (NFC, LF, control chars) -> quality filter (length, alpha ratio, repetition,
minified, encoding) -> safety filter (documents with credentials are dropped; e-mail addresses redacted) -> deduplication (exact hash + MinHash/LSH
near-duplicates) -> category/script/language tags -> tokenizer -> per-category train/val `uint16` shards + `manifest.json`.

* Category = first directory under the source root (explicit), else file type. Categories not in `data.mixture` are dropped *and counted*.
* Split is by document hash (a document is never in both train and val); every category with >= 5 documents gets at least one validation document.
* `manifest.json` holds tokenizer digest, config digest, per-file provenance (url, licence), token counts and shard hashes. Everything dropped is counted by reason in `clean/clean_report.json`.
* The mixer samples windows by category weights; batch `step` is a pure function of `(seed, step)`. The curriculum (`curriculum:` in the config) changes the weights with progress.
* Local data only. `scripts/fetch_corpus.py` assembles the V1 corpus (public-domain books, IETF RFCs, the Python standard library, structured files that ship with Python) and records licences; nothing private is read.
