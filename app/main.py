import hmac
import shutil
import threading

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from . import config, db, export, frames as fr, queue, youtube

app = FastAPI(title="Unstable Universe Analyzer")
db.init()

if __import__("os").environ.get("RUN_WORKER_IN_API") == "1":
    from . import worker
    threading.Thread(target=worker.loop, daemon=True).start()


def auth(request: Request):
    if not config.ADMIN_TOKEN:
        raise HTTPException(503, "ADMIN_TOKEN is not configured on the server")
    tok = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    if not hmac.compare_digest(tok, config.ADMIN_TOKEN):
        raise HTTPException(401, "bad token")


def base(request: Request):
    return config.PUBLIC_BASE_URL or str(request.base_url).rstrip("/")


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/api/summary", dependencies=[Depends(auth)])
def summary():
    return {
        "channels": db.q1("SELECT COUNT(*) n FROM channels")["n"],
        "videos": db.q("SELECT status, COUNT(*) n FROM videos GROUP BY status"),
        "entities": db.q("SELECT kind, COUNT(*) n FROM entities GROUP BY kind"),
        "jobs": db.q("SELECT status, COUNT(*) n FROM jobs GROUP BY status"),
        "open_questions": db.q1("SELECT COUNT(*) n FROM questions WHERE resolved=0")["n"],
        "vision_configured": bool(__import__("os").environ.get("ANTHROPIC_API_KEY")),
    }


@app.post("/api/channels", dependencies=[Depends(auth)])
def add_channels(body: dict):
    """Body: {"urls": ["https://youtube.com/@x", ...]} — adds many; discovery runs concurrently via worker."""
    out = []
    for u in body.get("urls", []):
        try:
            url = youtube.parse_channel_url(u)
        except ValueError as e:
            out.append({"url": u, "error": str(e)})
            continue
        ex = db.q1("SELECT id FROM channels WHERE url=?", (url,))
        cid = ex["id"] if ex else db.uid("ch_")
        if not ex:
            db.run("INSERT INTO channels(id,url,created) VALUES(?,?,?)", (cid, url, db.now()))
        out.append({"url": url, "id": cid, "job": queue.enqueue("discover_channel", cid)})
    return out


@app.get("/api/channels", dependencies=[Depends(auth)])
def channels():
    return db.q("SELECT c.*, (SELECT COUNT(*) FROM videos v WHERE v.channel_id=c.id) videos FROM channels c ORDER BY created")


@app.post("/api/channels/{cid}/discover", dependencies=[Depends(auth)])
def rediscover(cid: str):
    return {"job": queue.enqueue("discover_channel", cid)}


@app.get("/api/videos", dependencies=[Depends(auth)])
def videos(status: str = "", era: str = ""):
    sql, a = "SELECT v.*, c.name channel FROM videos v LEFT JOIN channels c ON c.id=v.channel_id WHERE 1=1", []
    if status: sql += " AND v.status=?"; a.append(status)
    if era: sql += " AND v.era=?"; a.append(era)
    return db.q(sql + " ORDER BY v.published DESC LIMIT 500", a)


@app.post("/api/videos/{vid}/enqueue", dependencies=[Depends(auth)])
def enqueue_video(vid: str):
    if not db.q1("SELECT 1 x FROM videos WHERE id=?", (vid,)):
        raise HTTPException(404)
    db.run("UPDATE videos SET status='queued' WHERE id=? AND status IN ('discovered','failed','skipped','queued')", (vid,))
    return {"job": queue.enqueue("process_video", vid)}


@app.post("/api/videos/enqueue_current", dependencies=[Depends(auth)])
def enqueue_current():
    ids = [v["id"] for v in db.q("SELECT id FROM videos WHERE status='discovered' AND relevance='relevant' AND era='current'")]
    for i in ids:
        db.run("UPDATE videos SET status='queued' WHERE id=?", (i,))
        queue.enqueue("process_video", i)
    return {"queued": len(ids)}


@app.post("/api/uploads", dependencies=[Depends(auth)])
def upload(file: UploadFile = File(...), title: str = Form(...), published: str = Form(...), creator: str = Form("user-upload")):
    """Authorized user-provided MP4 (for restricted/inaccessible footage)."""
    vid = db.uid("vid_")
    dest = config.DATA_DIR / "uploads" / f"{vid}.mp4"
    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)
    dur = fr.probe_duration(str(dest))
    if dur is None:
        dest.unlink()
        raise HTTPException(400, "file is not a readable video")
    era = "current" if published >= config.CURRENT_FROM else "historical"
    db.run("INSERT INTO videos(id,yt_id,title,url,published,duration,source,relevance,relevance_reason,era,status,local_path,created) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
           (vid, f"upload:{vid}", title, f"upload://{vid}", published, dur, "upload", "relevant", f"user-provided upload by {creator}",
            era, "queued", str(dest), db.now()))
    return {"video": vid, "job": queue.enqueue("process_video", vid)}


@app.get("/api/jobs", dependencies=[Depends(auth)])
def jobs():
    return db.q("SELECT j.*, v.title, v.frames_total, v.frames_done, v.pass2_total, v.pass2_done FROM jobs j "
                "LEFT JOIN videos v ON v.id=j.ref_id ORDER BY j.updated DESC LIMIT 200")


@app.post("/api/jobs/{jid}/{action}", dependencies=[Depends(auth)])
def job_action(jid: str, action: str):
    fn = {"pause": queue.pause, "resume": queue.resume, "retry": queue.retry}.get(action)
    if not fn:
        raise HTTPException(400, "action must be pause|resume|retry")
    fn(jid)
    return db.q1("SELECT * FROM jobs WHERE id=?", (jid,))


@app.get("/api/entities", dependencies=[Depends(auth)])
def entities(kind: str = "", q: str = "", civ: str = ""):
    sql, a = "SELECT id,kind,name,civilization,dimension,status,confidence,missing FROM entities WHERE 1=1", []
    if kind: sql += " AND kind=?"; a.append(kind)
    if civ: sql += " AND civilization=?"; a.append(civ)
    if q: sql += " AND (name LIKE ? OR data LIKE ?)"; a += [f"%{q}%"] * 2
    return db.q(sql + " ORDER BY id LIMIT 500", a)


@app.get("/api/entities/{eid}", dependencies=[Depends(auth)])
def entity(eid: str):
    e = db.q1("SELECT * FROM entities WHERE id=?", (eid,))
    if not e:
        raise HTTPException(404)
    e["data"] = db.jload(e["data"], {}); e["missing"] = db.jload(e["missing"], [])
    e["sources"] = db.q("SELECT s.*, v.title, v.url FROM entity_sources s JOIN videos v ON v.id=s.video_id WHERE entity_id=? ORDER BY s.published DESC, s.t", (eid,))
    return e


@app.get("/api/frames/{fid}.jpg", dependencies=[Depends(auth)])
def frame(fid: str):
    f = db.q1("SELECT path FROM frames WHERE id=?", (fid,))
    if not f:
        raise HTTPException(404)
    return FileResponse(config.DATA_DIR / f["path"])


@app.get("/api/questions", dependencies=[Depends(auth)])
def questions():
    return db.q("SELECT * FROM questions WHERE resolved=0 ORDER BY created DESC LIMIT 300")


@app.post("/api/exports", dependencies=[Depends(auth)])
def make_export(request: Request, body: dict = None):
    return export.build(base(request), (body or {}).get("note", ""))


@app.get("/api/exports", dependencies=[Depends(auth)])
def exports(request: Request):
    return [{**e, "manifest_url": f"{base(request)}/x/{e['token']}/manifest.json"} for e in db.q("SELECT * FROM exports ORDER BY created DESC")]


# Public, read-only, capability-URL snapshots (no login): /x/<unguessable-token>/...
@app.get("/x/{token}/")
def export_index(token: str, request: Request):
    p = config.DATA_DIR / "exports" / token / "README.md"
    if not p.exists() or "/" in token or ".." in token:
        raise HTTPException(404)
    b = base(request)
    return HTMLResponse(f"<!doctype html><meta name=viewport content='width=device-width'><title>Export</title>"
                        f"<h1>Unstable export</h1><p><a href='{b}/x/{token}/manifest.json'>manifest.json</a> · "
                        f"<a href='{b}/x/{token}/README.md'>README.md</a> · <a href='{b}/x/{token}/complete.zip'>complete.zip</a></p>")


@app.get("/x/{token}/{path:path}")
def export_file(token: str, path: str):
    root = (config.DATA_DIR / "exports" / token).resolve()
    f = (root / path).resolve()
    if root.parent != (config.DATA_DIR / "exports").resolve() or root not in f.parents or not f.is_file():
        raise HTTPException(404)
    return FileResponse(f, headers={"Cache-Control": "public, max-age=31536000, immutable", "Access-Control-Allow-Origin": "*"})


app.mount("/", StaticFiles(directory="static", html=True), name="static")
