"""Persistent background worker. Run: python -m app.worker  (any number of replicas; DB leases coordinate)."""
import logging
import shutil
import threading
import time
import traceback

from . import config, db, frames as fr, merge, queue, vision, youtube

log = logging.getLogger("worker")


class Paused(Exception):
    pass


def _check(job):
    st = queue.heartbeat(job["id"])
    if st != "running":
        raise Paused()


def download(video):
    from yt_dlp import YoutubeDL
    out = config.DATA_DIR / "videos" / video["id"]
    out.mkdir(parents=True, exist_ok=True)
    opts = dict(quiet=True, no_warnings=True, outtmpl=str(out / "src.%(ext)s"), format="bv*[height<=720]+ba/b[height<=720]/b",
                merge_output_format="mp4", retries=5, fragment_retries=5)
    with YoutubeDL(opts) as y:
        y.download([video["url"]])
    files = list(out.glob("src.*"))
    if not files:
        raise RuntimeError("download produced no file")
    return str(files[0])


def process_video(job, client=None):
    v = db.q1("SELECT * FROM videos WHERE id=?", (job["ref_id"],))
    db.run("UPDATE videos SET status='processing', error=NULL WHERE id=?", (v["id"],))
    try:
        # stage 1: acquire
        if not v["local_path"] or not __import__("os").path.exists(v["local_path"]):
            queue.heartbeat(job["id"], "download")
            path = download(v) if v["source"] == "youtube" else None
            if not path:
                raise RuntimeError("no local file for uploaded video")
            db.run("UPDATE videos SET local_path=? WHERE id=?", (path, v["id"]))
            v["local_path"] = path
        # stage 2: frames (skipped if already extracted -> resumable)
        if v["frames_total"] == 0 or not db.q1("SELECT 1 x FROM frames WHERE video_id=?", (v["id"],)):
            queue.heartbeat(job["id"], "frames")
            fr.extract(v["id"], v["local_path"])
        # stage 3: pass 1 over every frame, resumable per batch
        queue.heartbeat(job["id"], "analyze_pass1")
        v = db.q1("SELECT * FROM videos WHERE id=?", (v["id"],))
        while True:
            _check(job)
            batch = db.q("SELECT * FROM frames WHERE video_id=? AND pass1=0 ORDER BY idx LIMIT ?", (v["id"], config.FRAMES_PER_REQUEST))
            if not batch:
                break
            results = vision.analyze_frames(batch, v["title"], client=client)
            by_idx = {r.get("frame_index"): r for r in results}
            for f in batch:
                r = by_idx.get(f["idx"])
                if r is None:
                    raise RuntimeError(f"model returned no result for frame {f['idx']}; not marking analyzed")
                weak = False
                for o in (r.get("observations") or []) if r.get("in_game", True) else []:
                    merge.ingest(v, f, o, 1)
                    weak |= bool(o.get("ambiguous")) or float(o.get("confidence") or 0) < 0.5
                db.run("UPDATE frames SET pass1=1, needs_pass2=? WHERE id=?", (int(weak), f["id"]))
            db.run("UPDATE videos SET frames_done=(SELECT COUNT(*) FROM frames WHERE video_id=? AND pass1=1) WHERE id=?", (v["id"], v["id"]))
        # stage 4: pass 2 — revisit ambiguous/low-confidence frames with neighbouring context
        queue.heartbeat(job["id"], "analyze_pass2")
        db.run("UPDATE videos SET pass2_total=(SELECT COUNT(*) FROM frames WHERE video_id=? AND needs_pass2=1) WHERE id=?", (v["id"], v["id"]))
        while True:
            _check(job)
            f = db.q1("SELECT * FROM frames WHERE video_id=? AND needs_pass2=1 AND pass2=0 ORDER BY idx LIMIT 1", (v["id"],))
            if not f:
                break
            ctx = db.q("SELECT * FROM frames WHERE video_id=? AND idx BETWEEN ? AND ? ORDER BY idx", (v["id"], f["idx"] - 1, f["idx"] + 1))
            results = vision.analyze_frames(ctx, v["title"], hint="re-examine frame_index=%d; earlier pass was ambiguous or low confidence. "
                                            "Use neighbouring frames for context; keep null where still unknown." % f["idx"], client=client)
            for r in results:
                if r.get("frame_index") == f["idx"] and r.get("in_game", True):
                    for o in r.get("observations") or []:
                        merge.ingest(v, f, o, 2)
            db.run("UPDATE frames SET pass2=1 WHERE id=?", (f["id"],))
            db.run("UPDATE videos SET pass2_done=(SELECT COUNT(*) FROM frames WHERE video_id=? AND pass2=1) WHERE id=?", (v["id"], v["id"]))
        # complete ONLY when every frame had pass 1 and every flagged frame had pass 2
        left = db.q1("SELECT (SELECT COUNT(*) FROM frames WHERE video_id=? AND pass1=0) a,"
                     "(SELECT COUNT(*) FROM frames WHERE video_id=? AND needs_pass2=1 AND pass2=0) b", (v["id"], v["id"]))
        if left["a"] or left["b"]:
            raise RuntimeError("incomplete processing; not marking analyzed")
        db.run("UPDATE videos SET status='analyzed', analyzed_at=? WHERE id=?", (db.now(), v["id"]))
        queue.finish(job["id"], True)
    except Paused:
        db.run("UPDATE videos SET status='queued' WHERE id=?", (v["id"],))
    except Exception as e:
        db.run("UPDATE videos SET status='failed', error=? WHERE id=?", (f"{type(e).__name__}: {e}"[:500], v["id"]))
        queue.finish(job["id"], False, f"{type(e).__name__}: {e}"[:500])
        log.error("job %s failed: %s", job["id"], traceback.format_exc())


def discover_channel(job):
    try:
        n = youtube.discover(job["ref_id"])
        queue.finish(job["id"], True)
        log.info("discovered %d videos", n)
    except Exception as e:
        db.run("UPDATE channels SET status='error', error=? WHERE id=?", (str(e)[:500], job["ref_id"]))
        queue.finish(job["id"], False, str(e)[:500])


def run_job(job, client=None):
    if job["type"] == "process_video":
        process_video(job, client)
    elif job["type"] == "discover_channel":
        discover_channel(job)


def loop(stop=None):
    db.init()
    sem = threading.Semaphore(config.WORKER_CONCURRENCY)

    def go(job):
        try:
            run_job(job)
        finally:
            sem.release()

    while not (stop and stop.is_set()):
        sem.acquire()
        job = queue.claim()
        if not job:
            sem.release()
            time.sleep(3)
            continue
        threading.Thread(target=go, args=(job,), daemon=True).start()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    loop()
