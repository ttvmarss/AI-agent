"""TRAIL DATA FOUNDRY pipeline.

  clean():  RAW -> format detection -> normalisation -> quality filter -> safety filter -> deduplication -> tagging -> clean/docs.jsonl
  shard():  clean docs -> TRAIL tokenizer -> per-category train/val token shards (uint16) -> manifest.json (provenance, counts, hashes)
Everything dropped is counted by reason; nothing is silently discarded.
"""
import hashlib
import json
import os
import time
from collections import Counter

import numpy as np

from .. import __version__
from ..tokenizer.bpe import EOS, Tokenizer
from ..utilities.files import sha256_text, write_json_atomic
from ..utilities.log import get_logger
from . import dedup, ingest, normalize, quality, safety, tagging

log = get_logger("foundry")
FOUNDRY_VERSION = "foundry-v1"
SHARD_TOKENS = 4_000_000


def clean(sources, out_dir, base=".", min_chars=200, max_chars=2_000_000, allowed_categories=None, allow_unknown=False):
    os.makedirs(out_dir, exist_ok=True)
    dd = dedup.Deduper()
    drops, kept_by_cat, chars_by_cat, redactions, n_in = Counter(), Counter(), Counter(), 0, 0
    source_files = []
    t0 = time.time()
    path = os.path.join(out_dir, "docs.jsonl")
    with open(path + ".tmp", "w", encoding="utf-8") as out:
        for doc in ingest.iter_raw(sources, base):
            n_in += 1
            rec = {"rel": doc.rel, "format": doc.fmt}
            if doc.fmt != "text":
                drops["not_text"] += 1
                source_files.append({**rec, "status": "dropped:not_text"})
                continue
            cat = tagging.category_of(doc.rel, doc.declared_category)
            if allowed_categories is not None and cat not in allowed_categories and not allow_unknown:
                drops["category_not_in_mixture"] += 1
                source_files.append({**rec, "category": cat, "status": "dropped:category_not_in_mixture"})
                continue
            text = normalize.normalize(doc.text)
            why = quality.check(text, cat, min_chars, max_chars, doc.bad_decode)
            if why:
                drops[why] += 1
                source_files.append({**rec, "category": cat, "status": f"dropped:{why}"})
                continue
            why, text, nred = safety.scan(text)
            if why:
                drops[why] += 1
                source_files.append({**rec, "category": cat, "status": f"dropped:{why}"})
                continue
            redactions += nred
            doc_id = sha256_text(doc.rel + "\n" + text)[:16]
            dup = dd.check(doc_id, text)
            if dup:
                drops["duplicate"] += 1
                source_files.append({**rec, "category": cat, "status": f"dropped:duplicate_of:{dup}"})
                continue
            out.write(json.dumps({"id": doc_id, "category": cat, "script": tagging.script_of(text), "lang": tagging.programming_language(doc.rel),
                                  "rel": doc.rel, "provenance": doc.provenance, "text": text}, ensure_ascii=False) + "\n")
            kept_by_cat[cat] += 1
            chars_by_cat[cat] += len(text)
            source_files.append({**rec, "category": cat, "status": "kept", "id": doc_id, "chars": len(text)})
    os.replace(path + ".tmp", path)
    report = {"foundry": FOUNDRY_VERSION, "files_seen": n_in, "kept_docs": dict(kept_by_cat), "kept_chars": dict(chars_by_cat), "dropped": dict(drops),
              "email_redactions": redactions, "seconds": round(time.time() - t0, 1), "sources": source_files}
    write_json_atomic(os.path.join(out_dir, "clean_report.json"), report)
    log.info("clean: %d files -> kept %s ; dropped %s", n_in, dict(kept_by_cat), dict(drops))
    return report


def split_of(doc_id, val_fraction):
    return "val" if int(hashlib.sha256(doc_id.encode()).hexdigest()[:8], 16) / 2**32 < val_fraction else "train"


def shard(clean_dir, tokenizer: Tokenizer, out_dir, val_fraction=0.02, config_digest="", shard_tokens=SHARD_TOKENS):
    if tokenizer.vocab_size > 65536:
        raise ValueError("uint16 shards need vocab_size <= 65536")
    os.makedirs(out_dir, exist_ok=True)
    docs = [json.loads(line) for line in open(os.path.join(clean_dir, "docs.jsonl"), "r", encoding="utf-8")]
    if not docs:
        raise ValueError("no clean documents to shard")
    by_cat = {}
    for d in docs:
        by_cat.setdefault(d["category"], []).append(d)
    for cat, ds in by_cat.items():                       # hash split, but guarantee a validation document wherever there are enough documents
        for d in ds:
            d["split"] = split_of(d["id"], val_fraction)
        if len(ds) >= 5 and not any(d["split"] == "val" for d in ds):
            min(ds, key=lambda d: hashlib.sha256(d["id"].encode()).hexdigest())["split"] = "val"
    manifest = {"foundry": FOUNDRY_VERSION, "trail_version": __version__, "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "tokenizer": {"version": tokenizer.meta.get("version", "trail-tokenizer-v1"), "vocab_size": tokenizer.vocab_size,
                              "digest": hashlib.sha256(json.dumps(tokenizer.merges).encode()).hexdigest()[:16]},
                "config_digest": config_digest, "val_fraction": val_fraction, "categories": {}, "documents": []}
    for cat, ds in sorted(by_cat.items()):
        for split in ("train", "val"):
            sel = [d for d in sorted(ds, key=lambda d: d["id"]) if d["split"] == split]
            if not sel:
                continue
            buf, files, n_tok, shard_i = [], [], 0, 0

            def flush():
                nonlocal buf, shard_i
                if not buf:
                    return
                arr = np.asarray(buf, dtype=np.uint16)
                rel = os.path.join(cat, f"{split}_{shard_i:05d}.bin")
                os.makedirs(os.path.join(out_dir, cat), exist_ok=True)
                arr.tofile(os.path.join(out_dir, rel))
                files.append({"file": rel.replace("\\", "/"), "tokens": int(arr.size), "sha256": hashlib.sha256(arr.tobytes()).hexdigest()})
                shard_i += 1
                buf = []
            for d in sel:
                ids = tokenizer.encode(d["text"]) + [EOS]
                buf.extend(ids)
                n_tok += len(ids)
                manifest["documents"].append({"id": d["id"], "rel": d["rel"], "category": cat, "split": split, "tokens": len(ids), "provenance": d["provenance"]})
                if len(buf) >= shard_tokens:
                    flush()
            flush()
            manifest["categories"].setdefault(cat, {})[split] = {"docs": len(sel), "tokens": n_tok, "shards": files}
    write_json_atomic(os.path.join(out_dir, "manifest.json"), manifest)
    tot = {s: sum(c.get(s, {}).get("tokens", 0) for c in manifest["categories"].values()) for s in ("train", "val")}
    log.info("shard: %s tokens (train) %s (val) in %d categories", f"{tot['train']:,}", f"{tot['val']:,}", len(by_cat))
    manifest["totals"] = tot
    write_json_atomic(os.path.join(out_dir, "manifest.json"), manifest)
    return manifest
