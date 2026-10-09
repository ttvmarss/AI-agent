"""Download a small public-domain corpus (Project Gutenberg) and build deterministic splits.

Rights note: these works are public domain in the US; Gutenberg's trademark/boilerplate is
stripped. This is a PIPELINE-PROOF corpus, not the production training corpus (see
rights/SOURCE_RIGHTS_REGISTER.md). Re-check jurisdiction before any redistribution.

Splits (leak-free by construction):
  train = first 95% of each TRAIN book; val = last 5% of each TRAIN book;
  test  = whole held-out book(s), never used for training or model selection.
"""
import hashlib, json, re, sys, urllib.request
from pathlib import Path

BOOKS = {  # id: (title, role)
    1342: ("Pride and Prejudice", "train"),
    84: ("Frankenstein", "train"),
    1661: ("The Adventures of Sherlock Holmes", "train"),
    11: ("Alice's Adventures in Wonderland", "test"),
}

def fetch(book_id: int) -> str:
    url = f"https://www.gutenberg.org/cache/epub/{book_id}/pg{book_id}.txt"
    with urllib.request.urlopen(url, timeout=60) as r:
        return r.read().decode("utf-8-sig")

def strip(text: str) -> str:
    text = text.replace("\r\n", "\n")
    s = re.search(r"\*\*\* ?START OF (THE|THIS) PROJECT GUTENBERG EBOOK.*?\*\*\*", text)
    e = re.search(r"\*\*\* ?END OF (THE|THIS) PROJECT GUTENBERG EBOOK", text)
    if s and e:
        text = text[s.end():e.start()]
    return re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"

def main(out: Path):
    out.mkdir(parents=True, exist_ok=True)
    splits = {"train": [], "val": [], "test": []}
    manifest = {"books": [], "source": "gutenberg.org", "license": "Public domain (US); boilerplate stripped"}
    for bid, (title, role) in BOOKS.items():
        raw = fetch(bid)
        text = strip(raw)
        entry = {"id": bid, "title": title, "role": role, "raw_sha256": hashlib.sha256(raw.encode()).hexdigest(),
                 "clean_sha256": hashlib.sha256(text.encode()).hexdigest(), "chars": len(text)}
        manifest["books"].append(entry)
        if role == "train":
            cut = int(len(text) * 0.95)
            splits["train"].append(text[:cut]); splits["val"].append(text[cut:])
        else:
            splits["test"].append(text)
    for name, parts in splits.items():
        body = "\n".join(parts)
        (out / f"{name}.txt").write_text(body, encoding="utf-8")
        manifest[f"{name}_chars"] = len(body)
        manifest[f"{name}_sha256"] = hashlib.sha256(body.encode()).hexdigest()
    (out / "corpus_manifest.json").write_text(json.dumps(manifest, indent=2))
    print(json.dumps({k: v for k, v in manifest.items() if k != "books"}, indent=2))

if __name__ == "__main__":
    main(Path(sys.argv[1]))
