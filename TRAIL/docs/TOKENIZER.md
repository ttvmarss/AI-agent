# TRAIL Tokenizer V1

Byte-level BPE, trained by `trail tokenizer train` on the Data Foundry's cleaned documents (sampled round-robin across categories so code does not
decide the whole vocabulary).

* ids: 9 special tokens (`<PAD> <BOS> <EOS> <SYSTEM> <USER> <TRAIL> <TOOL> <MEMORY> <CODE>`), then 256 byte tokens, then learned merges.
* pre-tokenisation regex keeps words, single digits, punctuation runs and whitespace runs separate (indentation, JSON punctuation, paths and Markdown get their own merges).
* every Unicode code point (and arbitrary bytes) is representable: `decode(encode(x)) == x`, tested exhaustively over code points.
* user text is encoded without special-token parsing, so a user cannot type `<TRAIL>` and impersonate a role.
* if the corpus runs out of frequent pairs before `vocab_size`, the remaining ids are reserved (never produced), so the model table size is stable.
* `tokenizer.json` records version, regex, specials, merges and a corpus digest; loading refuses a mismatched file.
