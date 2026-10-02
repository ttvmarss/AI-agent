"""Assemble the V1 local training corpus into datasets/raw/<category>/ with a provenance record for every file.

Only material that may be redistributed/used is taken:
  language / science / mathematics : public-domain books from Project Gutenberg (headers and licence boilerplate stripped)
  technical                        : IETF RFCs (the IETF Trust permits copying and reuse)
  code                             : the Python standard library on this machine (PSF licence)
  structured_data                  : JSON / YAML / TOML / XML / CSV files that ship with the local Python installation
Nothing private is read. Re-running is idempotent. Usage: python scripts/fetch_corpus.py [--code-mb 12] [--offline]
"""
import argparse
import json
import os
import re
import sys
import sysconfig
import time
import urllib.request

ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "datasets", "raw")
BOOKS = {  # gutenberg id: (category, slug)
    1342: ("language", "pride_and_prejudice"), 11: ("language", "alice_in_wonderland"), 84: ("language", "frankenstein"), 2701: ("language", "moby_dick"),
    1661: ("language", "sherlock_holmes"), 345: ("language", "dracula"), 1400: ("language", "great_expectations"), 98: ("language", "tale_of_two_cities"),
    174: ("language", "dorian_gray"), 76: ("language", "huckleberry_finn"), 1260: ("language", "jane_eyre"), 2554: ("language", "crime_and_punishment"),
    1228: ("science", "origin_of_species"), 5001: ("science", "einstein_relativity"), 14725: ("science", "darwin_voyage_beagle_part"),
    21076: ("mathematics", "euclid_elements"), 13700: ("mathematics", "mathematical_recreations"),
}
RFCS = [8259, 3986, 9110, 793, 791, 1035, 5321, 9112, 7230, 6455, 4180, 2616, 3339, 5322, 6749, 7519]
STRUCT_EXT = (".json", ".yaml", ".yml", ".toml", ".xml", ".csv", ".ini", ".cfg")


def fetch(url, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "trail-corpus/0.1"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read().decode("utf-8", errors="replace")
        except Exception as e:
            err = e
            time.sleep(1 + i)
    print(f"  could not fetch {url}: {err}", file=sys.stderr)
    return None


def strip_gutenberg(t):
    a = re.search(r"\*\*\* ?START OF (?:THE|THIS) PROJECT GUTENBERG EBOOK.*?\*\*\*", t, re.S)
    b = re.search(r"\*\*\* ?END OF (?:THE|THIS) PROJECT GUTENBERG EBOOK", t)
    if a:
        t = t[a.end():]
    if b and b.start() > a.end() if a and b else False:
        t = t[:re.search(r"\*\*\* ?END OF (?:THE|THIS) PROJECT GUTENBERG EBOOK", t).start()]
    return t.strip()


def write(cat, name, text, prov, rec):
    d = os.path.join(ROOT, cat)
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, name)
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    rec.append({"file": f"{cat}/{name}", **prov})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--code-mb", type=float, default=12.0)
    ap.add_argument("--struct-mb", type=float, default=3.0)
    ap.add_argument("--offline", action="store_true", help="skip network downloads (code and structured data only)")
    a = ap.parse_args()
    rec = []
    if not a.offline:
        for gid, (cat, slug) in BOOKS.items():
            url = f"https://www.gutenberg.org/cache/epub/{gid}/pg{gid}.txt"
            t = fetch(url)
            if t:
                t = strip_gutenberg(t)
                write(cat, f"{slug}.txt", t, {"url": url, "license": "public domain (US), Project Gutenberg text with licence header removed"}, rec)
                print(f"book {slug}: {len(t) / 1e6:.2f} MB")
        for n in RFCS:
            url = f"https://www.rfc-editor.org/rfc/rfc{n}.txt"
            t = fetch(url)
            if t:
                write("technical", f"rfc{n}.txt", t, {"url": url, "license": "IETF Trust: copying and reuse of RFCs permitted"}, rec)
                print(f"rfc{n}: {len(t) / 1e3:.0f} KB")
    stdlib = sysconfig.get_paths()["stdlib"]
    files = []
    for base, dirs, fs in os.walk(stdlib):
        dirs[:] = sorted(d for d in dirs if d not in ("site-packages", "dist-packages", "__pycache__", "idlelib", "lib2to3"))
        files += [os.path.join(base, f) for f in sorted(fs) if f.endswith(".py") and 1_000 < os.path.getsize(os.path.join(base, f)) < 150_000]
    stride = max(1, int(sum(os.path.getsize(f) for f in files) / (a.code_mb * 1e6)))
    got = 0
    for i, f in enumerate(files):
        if i % stride:
            continue
        rel = os.path.relpath(f, stdlib).replace(os.sep, "__")
        with open(f, "r", encoding="utf-8", errors="replace") as fh:
            t = fh.read()
        write("code", rel, t, {"url": "file:" + f, "license": "PSF License (Python standard library)"}, rec)
        got += len(t)
    print(f"code: {got / 1e6:.1f} MB from {stdlib}")
    cands = []
    for root in {stdlib, sysconfig.get_paths()["purelib"], "/usr/lib/python3/dist-packages", "/usr/local/lib/python3.11/dist-packages"}:
        for base, dirs, fs in os.walk(root):
            dirs[:] = sorted(dirs)
            cands += [os.path.join(base, f) for f in sorted(fs) if f.lower().endswith(STRUCT_EXT) and 300 < os.path.getsize(os.path.join(base, f)) < 300_000]
    stride = max(1, int(sum(os.path.getsize(f) for f in cands) / (a.struct_mb * 1e6))) if cands else 1
    got = 0
    for i, f in enumerate(cands):
        if i % stride:
            continue
        with open(f, "r", encoding="utf-8", errors="replace") as fh:
            t = fh.read()
        write("structured_data", f"{i:05d}_{os.path.basename(f)}", t, {"url": "file:" + f, "license": "ships with locally installed Python packages (their own licences)"}, rec)
        got += len(t)
    print(f"structured: {got / 1e6:.1f} MB")
    os.makedirs(ROOT, exist_ok=True)
    with open(os.path.join(ROOT, "PROVENANCE.jsonl"), "w", encoding="utf-8") as f:
        for r in rec:
            f.write(json.dumps(r) + "\n")
    print(f"{len(rec)} files recorded in PROVENANCE.jsonl")


if __name__ == "__main__":
    main()
