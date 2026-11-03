"""Channel resolution + video discovery via yt-dlp (metadata only). Records WHY each video is included."""
import re
from datetime import datetime

from . import config, db

# Evidence keywords. A match is recorded as the reason; no match => not auto-included.
STRONG = [r"unstable\s*(smp|universe)", r"\bunstable\b.*\b(episode|ep\b|day|season)", r"farlands", r"\bnull\b.*\b(smp|totem)",
          r"saparata", r"\bLAW\b.*(smp|unstable)", r"clownpierce"]
COUNTRY_HINTS = ["flamefrags", "wemmbu", "parrot", "spoke"]


def parse_channel_url(url: str):
    url = url.strip()
    m = re.match(r"^https?://(www\.|m\.)?youtube\.com/(@[\w.\-]+|channel/[\w\-]+|c/[\w.\-]+|user/[\w.\-]+)", url)
    if not m:
        raise ValueError("Not a recognised YouTube channel URL (expected /@handle, /channel/ID, /c/name or /user/name)")
    return f"https://www.youtube.com/{m.group(2)}"


def classify(title: str, description: str, tags, published: str):
    """Return (relevance, reason, era). relevance: relevant|maybe|irrelevant."""
    text = f"{title}\n{description or ''}\n{' '.join(tags or [])}"
    hits = [p for p in STRONG if re.search(p, text, re.I)]
    era = "current" if published and published >= config.CURRENT_FROM else "historical"
    if hits:
        return "relevant", f"matched {len(hits)} Unstable-SMP keyword pattern(s): {', '.join(hits[:3])}", era
    if re.search(r"\bunstable\b", text, re.I):
        return "maybe", "mentions 'unstable' but no SMP/universe context; needs review", era
    return "irrelevant", "no Unstable SMP indicators in title/description/tags", era


def _fmt_date(d):
    return f"{d[:4]}-{d[4:6]}-{d[6:8]}" if d and len(d) == 8 else None


def discover(channel_id: str, limit: int = 200):
    from yt_dlp import YoutubeDL
    ch = db.q1("SELECT * FROM channels WHERE id=?", (channel_id,))
    base = dict(quiet=True, no_warnings=True, skip_download=True)
    with YoutubeDL({**base, "extract_flat": True, "playlistend": limit}) as y:
        info = y.extract_info(ch["url"] + "/videos", download=False)
    entries = [e for e in (info.get("entries") or []) if e and e.get("id")]
    db.run("UPDATE channels SET name=?, yt_channel_id=? WHERE id=?",
           (info.get("channel") or info.get("title"), info.get("channel_id"), channel_id))
    added = 0
    with YoutubeDL({**base}) as y:
        for e in entries:
            if db.q1("SELECT 1 x FROM videos WHERE yt_id=?", (e["id"],)):
                continue
            try:
                v = y.extract_info(f"https://www.youtube.com/watch?v={e['id']}", download=False)
            except Exception as ex:  # private/age-restricted/etc: record the limitation
                db.run("INSERT INTO videos(id,channel_id,yt_id,title,url,status,error,created) VALUES(?,?,?,?,?,?,?,?)",
                       (db.uid("vid_"), channel_id, e["id"], e.get("title"), e.get("url"), "restricted",
                        f"metadata unavailable: {str(ex)[:300]}", db.now()))
                continue
            pub = _fmt_date(v.get("upload_date"))
            rel, reason, era = classify(v.get("title", ""), v.get("description", ""), v.get("tags"), pub)
            status = "discovered" if rel != "irrelevant" else "skipped"
            db.run("INSERT INTO videos(id,channel_id,yt_id,title,url,published,duration,relevance,relevance_reason,era,status,created)"
                   " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                   (db.uid("vid_"), channel_id, v["id"], v.get("title"), v.get("webpage_url"), pub,
                    v.get("duration"), rel, reason, era, status, db.now()))
            added += 1
    db.run("UPDATE channels SET status='discovered', last_discovered=?, error=NULL WHERE id=?", (db.now(), channel_id))
    return added
