"""Versioned, immutable, checksummed project snapshots served at an unguessable public HTTPS path (/x/<token>/)."""
import hashlib
import json
import re
import secrets
import shutil
import zipfile

from . import config, db

SCHEMA_VERSION = "1.0"
ENTITY_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema", "title": "UnstableEntity",
    "type": "object", "required": ["id", "kind", "name", "status", "confidence", "sources", "missing_information"],
    "properties": {
        "id": {"type": "string", "pattern": "^[A-Z]{3}-[0-9]{6}$"}, "kind": {"enum": ["building", "civilization", "weapon", "item", "enchantment", "mechanic", "event"]},
        "name": {"type": "string"}, "civilization": {"type": ["string", "null"]}, "dimension": {"type": "string"},
        "status": {"enum": ["observed", "needs_review", "destroyed", "historical"]}, "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "current_state": {"type": "object"}, "history": {"type": "array"},
        "sources": {"type": "array", "items": {"type": "object", "required": ["video_url", "timestamp_s", "published", "era"]}},
        "screenshots": {"type": "array", "items": {"type": "string"}}, "missing_information": {"type": "array", "items": {"type": "string"}},
        "conflicts": {"type": "array"}}}
MANIFEST_SCHEMA = {"$schema": "https://json-schema.org/draft/2020-12/schema", "title": "ExportManifest", "type": "object",
                   "required": ["schema_version", "version", "created", "files", "counts", "coverage", "disclaimers"]}
FOLDERS = {"building": "buildings", "civilization": "civilizations_entities", "weapon": "weapons", "item": "items",
           "enchantment": "enchantments", "mechanic": "mechanics", "event": "events"}


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", (s or "unaffiliated").lower()).strip("-") or "unaffiliated"


def _sha(b: bytes):
    return hashlib.sha256(b).hexdigest()


def build(base_url: str, note: str = ""):
    n = (db.q1("SELECT COUNT(*) n FROM exports")["n"]) + 1
    version, token = f"v{n:04d}", secrets.token_urlsafe(16)
    root = config.DATA_DIR / "exports" / token
    root.mkdir(parents=True)
    files = {}

    def put(rel, content):
        b = content if isinstance(content, bytes) else (json.dumps(content, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode() if not isinstance(content, str) else content.encode()
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b)
        files[rel] = b

    ents = db.q("SELECT * FROM entities ORDER BY id")
    srcs = db.q("SELECT s.*, v.url video_url, v.title video_title, v.channel_id, c.name channel FROM entity_sources s "
                "JOIN videos v ON v.id=s.video_id LEFT JOIN channels c ON c.id=v.channel_id ORDER BY s.published DESC, s.t")
    frames_used = set()
    by_ent = {}
    for s in srcs:
        by_ent.setdefault(s["entity_id"], []).append(s)
    records = []
    for e in ents:
        d = db.jload(e["data"], {})
        ss = by_ent.get(e["id"], [])
        shots = []
        for s in ss:
            fr = db.q1("SELECT path FROM frames WHERE id=?", (s["frame_id"],))
            if fr and (config.DATA_DIR / fr["path"]).exists():
                rel = f"evidence/frames/{s['frame_id']}.jpg"
                if rel not in files:
                    put(rel, (config.DATA_DIR / fr["path"]).read_bytes())
                shots.append(f"{base_url}/x/{token}/{rel}")
                frames_used.add(s["frame_id"])
        sources = [{"video_id": s["video_id"], "video_url": s["video_url"] + (f"&t={int(s['t'])}s" if s["video_url"] and "?" in s["video_url"] else ""),
                    "video_title": s["video_title"], "channel": s["channel"], "timestamp_s": s["t"], "published": s["published"],
                    "era": s["era"], "note": s["note"], "confidence": s["confidence"]} for s in ss]
        versions = d.get("versions", [])
        rec = {"id": e["id"], "kind": e["kind"], "name": e["name"], "civilization": e["civilization"], "dimension": e["dimension"],
               "status": e["status"], "confidence": round(e["confidence"] or 0, 3),
               "current_state": {k: d.get(k) for k in ("current_description", "materials", "est_dimensions", "mechanic", "item",
                                                       "current_state_from", "has_interior", "has_exterior", "geometry_note")},
               "history": [v for v in versions if v["era"] == "historical"], "all_versions": versions,
               "sources": sources, "screenshots": shots, "missing_information": db.jload(e["missing"], []),
               "conflicts": d.get("conflicts", [])}
        records.append(rec)
        put(f"{FOLDERS[e['kind']]}/{e['id']}.json", rec)
    by_kind = {}
    for r in records:
        by_kind.setdefault(r["kind"], []).append(r)
    for kind, folder in FOLDERS.items():
        put(f"registries/{folder}.json", {"kind": kind, "count": len(by_kind.get(kind, [])),
            "items": [{"id": r["id"], "name": r["name"], "civilization": r["civilization"], "dimension": r["dimension"],
                       "confidence": r["confidence"], "status": r["status"], "url": f"{base_url}/x/{token}/{folder}/{r['id']}.json"}
                      for r in by_kind.get(kind, [])]})
    # per-building construction notes: NEVER exact geometry; plans only when evidence exists
    for r in by_kind.get("building", []):
        cs = r["current_state"]
        put(f"plans/{r['id']}.json", {"building_id": r["id"], "geometry": "estimated" if cs.get("est_dimensions") else "unknown",
            "est_dimensions": cs.get("est_dimensions"), "block_palette_observed": cs.get("materials"),
            "schematic_available": False, "schematic_note": "No .schem generated: footage-derived data is insufficient for exact block coordinates.",
            "missing_information": r["missing_information"]})
    civs = sorted({r["civilization"] for r in records if r["civilization"]} | {r["name"] for r in by_kind.get("civilization", [])})
    for civ in civs:
        sub = [r for r in records if slug(r["civilization"]) == slug(civ) or (r["kind"] == "civilization" and slug(r["name"]) == slug(civ))]
        put(f"by_civilization/{slug(civ)}.json", {"civilization": civ, "count": len(sub), "records": sub})
    vids = db.q("SELECT v.id,v.title,v.url,v.published,v.era,v.status,v.relevance,v.relevance_reason,v.frames_total,v.frames_done,"
                "v.pass2_total,v.pass2_done,v.error,c.name channel FROM videos v LEFT JOIN channels c ON c.id=v.channel_id ORDER BY v.published DESC")
    put("evidence/index.json", {"videos": vids, "evidence_frames": sorted(frames_used)})
    put("world_index.json", {"civilizations": civs, "dimensions": sorted({r["dimension"] for r in records}),
        "records_by_kind": {k: len(v) for k, v in by_kind.items()}, "registries": {k: f"{base_url}/x/{token}/registries/{f}.json" for k, f in FOLDERS.items()}})
    qs = db.q("SELECT * FROM questions WHERE resolved=0")
    mc = db.q("SELECT * FROM merge_candidates")
    put("research_questions.json", {"open_questions": qs, "possible_duplicate_entities_unmerged": mc})
    analyzed = [v for v in vids if v["status"] == "analyzed"]
    progress = {"videos_total": len(vids), "videos_fully_analyzed": len(analyzed),
                "videos_by_status": {s: sum(1 for v in vids if v["status"] == s) for s in {v["status"] for v in vids}},
                "needs_review_entities": sum(1 for r in records if r["status"] == "needs_review")}
    put("progress/report.json", progress)
    put("schemas/entity.schema.json", ENTITY_SCHEMA)
    put("schemas/manifest.schema.json", MANIFEST_SCHEMA)
    readme = f"""# Unstable Universe Analyzer export {version}

Machine-readable entry point: `manifest.json` (lists every file with URL, size and SHA-256).

## How to read this
1. Fetch `{base_url}/x/{token}/manifest.json`.
2. `world_index.json` -> registries (`registries/*.json`) -> per-record files (`buildings/BLD-000001.json`, ...).
3. Each record has `sources[]` with video URL + timestamp, `screenshots[]` (real extracted frames), `confidence`, `missing_information[]`.
4. `by_civilization/<slug>.json` = smaller per-civilization exports. `complete.zip` = everything.

## Rules for consumers
- `est_dimensions` are visual estimates, never exact. No schematics exist unless `schematic_available` is true.
- `history[]` = footage before {config.CURRENT_FROM}; `current_state` is derived from newest footage.
- Weapons/machines must NOT be prebuilt on the server; `mechanics`/`weapons` records describe construction + activation only.
- `status: needs_review` and the `possible_duplicate_entities_unmerged` list mean unresolved identity. Absence of a record is NOT evidence it does not exist.

## Counts
{json.dumps({k: len(v) for k, v in by_kind.items()}, indent=2)}
Videos fully analyzed: {progress['videos_fully_analyzed']} / {progress['videos_total']}
"""
    put("README.md", readme)
    # zip of everything so far
    zp = root / "complete.zip"
    with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
        for rel, b in files.items():
            z.writestr(rel, b)
    zb = zp.read_bytes()
    listing = [{"path": rel, "url": f"{base_url}/x/{token}/{rel}", "bytes": len(b), "sha256": _sha(b)} for rel, b in sorted(files.items())]
    listing.append({"path": "complete.zip", "url": f"{base_url}/x/{token}/complete.zip", "bytes": len(zb), "sha256": _sha(zb)})
    counts = {k: len(v) for k, v in by_kind.items()}
    manifest = {"schema_version": SCHEMA_VERSION, "version": version, "snapshot_id": token, "created": db.now(), "note": note,
                "base_url": f"{base_url}/x/{token}/", "counts": counts,
                "coverage": {**progress, "complete_world_claimed": False},
                "disclaimers": ["Coverage is limited to videos listed in evidence/index.json with status 'analyzed'.",
                                "Estimates are not exact reconstructions.", "No credentials are contained in this export."],
                "files": listing}
    mb = (json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode()
    (root / "manifest.json").write_bytes(mb)
    eid = db.uid("exp_")
    db.run("INSERT INTO exports(id,version,token,created,counts,manifest_sha256,note) VALUES(?,?,?,?,?,?,?)",
           (eid, version, token, db.now(), db.jdump(counts), _sha(mb), note))
    return {"id": eid, "version": version, "token": token, "manifest_url": f"{base_url}/x/{token}/manifest.json",
            "index_url": f"{base_url}/x/{token}/", "zip_url": f"{base_url}/x/{token}/complete.zip", "counts": counts,
            "manifest_sha256": _sha(mb)}
