"""Cross-channel reconstruction: resolve observations into unified entities, track conflicts and newest state."""
import re
from difflib import SequenceMatcher

from . import db

PREFIX = {"building": "BLD", "landmark": "BLD", "civilization": "CIV", "weapon": "WPN", "item": "ITM",
          "enchantment": "ENC", "mechanic": "MEC", "event": "EVT"}
AUTO_MERGE = 0.88   # same kind + near-identical name => same entity
REVIEW = 0.65       # in-between => recorded as merge candidate, NOT merged


def norm(s):
    return re.sub(r"[^a-z0-9 ]", "", (s or "").lower()).strip()


def canon_kind(k):
    return "building" if k == "landmark" else k


def _next_id(c, kind):
    p = PREFIX.get(kind, "ENT")
    row = c.execute("SELECT id FROM entities WHERE id LIKE ? ORDER BY id DESC LIMIT 1", (p + "-%",)).fetchone()
    n = int(row["id"].split("-")[1]) + 1 if row else 1
    return f"{p}-{n:06d}"


def _missing(kind, d):
    m = []
    if not d.get("materials"):
        m.append("block palette")
    if kind == "building":
        if not d.get("est_dimensions"):
            m.append("dimensions")
        if not d.get("has_interior"):
            m.append("interior footage")
        if not d.get("has_exterior"):
            m.append("exterior footage")
        m.append("coordinates (not derivable from footage unless F3 screen visible)")
    if kind in ("weapon", "mechanic") and not (d.get("mechanic") or {}).get("how_it_works"):
        m.append("operating principle")
    return m


def ingest(video, frame, obs, pass_no):
    """Add one model observation. Returns entity id or None. `video` has id,published,era."""
    kind = canon_kind(obs.get("kind") or "")
    if kind not in PREFIX:
        return None
    name = (obs.get("name") or "").strip() or None
    conf = float(obs.get("confidence") or 0)
    oid = db.uid("obs_")
    with db.tx() as c:
        civ = obs.get("civilization")
        dim = obs.get("dimension") or "unknown"
        eid = None
        cand = []
        if name:
            for e in c.execute("SELECT * FROM entities WHERE kind=?", (kind,)).fetchall():
                s = SequenceMatcher(None, norm(name), e["norm_name"] or "").ratio()
                if civ and e["civilization"] and norm(civ) != norm(e["civilization"]):
                    s -= 0.1
                if s >= AUTO_MERGE:
                    eid = e["id"]
                    break
                if s >= REVIEW:
                    cand.append((e["id"], s))
        if eid is None and not name:
            # unnamed: attach to an unnamed entity from the SAME video within 90 s, same dimension & interior flag
            for e in c.execute("SELECT e.* FROM entities e JOIN entity_sources s ON s.entity_id=e.id "
                               "WHERE e.kind=? AND e.status='needs_review' AND s.video_id=? AND ABS(s.t-?)<90 "
                               "AND e.dimension=? GROUP BY e.id", (kind, video["id"], frame["t"], dim)).fetchall():
                eid = e["id"]
                break
        created = False
        if eid is None:
            eid = _next_id(c, kind)
            display = name or f"Unidentified {kind} ({video['title'][:40]} @ {int(frame['t'])}s)"
            c.execute("INSERT INTO entities(id,kind,name,norm_name,civilization,dimension,status,confidence,data,missing,created,updated)"
                      " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                      (eid, kind, display, norm(name), civ, dim, "observed" if name else "needs_review", conf,
                       db.jdump({}), db.jdump([]), db.now(), db.now()))
            created = True
            for other, s in cand:
                c.execute("INSERT OR IGNORE INTO merge_candidates(a,b,score,reason) VALUES(?,?,?,?)",
                          (eid, other, s, "similar name, below auto-merge threshold"))
        e = c.execute("SELECT * FROM entities WHERE id=?", (eid,)).fetchone()
        d = db.jload(e["data"], {})
        versions = d.setdefault("versions", [])
        # newest published footage wins for 'current' fields; older kept in history
        ver = {"video_id": video["id"], "published": video["published"], "era": video["era"], "t": frame["t"],
               "description": obs.get("description"), "materials": obs.get("materials") or [],
               "est_dimensions": obs.get("est_dimensions"), "is_interior": bool(obs.get("is_interior")),
               "changes_from_previous": obs.get("changes_from_previous"), "confidence": conf,
               "mechanic": obs.get("mechanic"), "item": obs.get("item")}
        versions.append(ver)
        versions.sort(key=lambda v: (v["published"] or "", v["t"]))
        cur_pool = [v for v in versions if v["era"] == "current"] or versions
        newest = cur_pool[-1]
        mats = sorted({m for v in cur_pool for m in v["materials"]})
        dims = [v["est_dimensions"] for v in cur_pool if v["est_dimensions"]]
        d.update(materials=mats, est_dimensions=dims[-1] if dims else None, current_description=newest["description"],
                 mechanic=next((v["mechanic"] for v in reversed(cur_pool) if v["mechanic"]), None),
                 item=next((v["item"] for v in reversed(cur_pool) if v["item"]), None),
                 has_interior=any(v["is_interior"] for v in versions), has_exterior=any(not v["is_interior"] for v in versions),
                 current_state_from=newest["published"],
                 geometry_note="all dimensions are visual estimates, never exact measurements")
        # conflicting dimensions across sources -> flag
        if len({(round(x["w"]), round(x["d"]), round(x["h"])) for x in dims if all(k in x for k in "wdh")}) > 1:
            d["conflicts"] = ["sources disagree on estimated dimensions"]
        n_src = len({v["video_id"] for v in versions})
        total_conf = min(0.95, max(v["confidence"] for v in versions) * (0.7 + 0.1 * min(n_src, 3)))
        new_name = e["name"]
        if name and e["norm_name"] == "":
            new_name = name
        c.execute("UPDATE entities SET data=?, missing=?, confidence=?, updated=?, name=?, norm_name=?, "
                  "civilization=COALESCE(civilization,?), status=CASE WHEN ?<>'' THEN 'observed' ELSE status END WHERE id=?",
                  (db.jdump(d), db.jdump(_missing(kind, d)), total_conf, db.now(), new_name,
                   norm(new_name) if name else e["norm_name"], civ, name or "", eid))
        c.execute("INSERT INTO observations(id,video_id,frame_id,t,pass,kind,name,data,confidence,entity_id,created) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                  (oid, video["id"], frame["id"], frame["t"], pass_no, kind, name, db.jdump(obs), conf, eid, db.now()))
        c.execute("INSERT OR IGNORE INTO entity_sources(entity_id,video_id,frame_id,t,era,published,note,confidence,observation_id) VALUES(?,?,?,?,?,?,?,?,?)",
                  (eid, video["id"], frame["id"], frame["t"], video["era"], video["published"], obs.get("evidence"), conf, oid))
        if obs.get("ambiguous"):
            c.execute("INSERT INTO questions(id,text,entity_id,video_id,created) VALUES(?,?,?,?,?)",
                      (db.uid("q_"), f"Ambiguous scene at {int(frame['t'])}s: {obs.get('description','')[:160]} — confirm identity/location.",
                       eid, video["id"], db.now()))
        return eid
