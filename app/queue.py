"""Durable DB-backed job queue with leases (crash-safe), pause/resume/retry."""
from . import config, db


def enqueue(type_, ref_id):
    ex = db.q1("SELECT * FROM jobs WHERE type=? AND ref_id=? AND status IN ('queued','running','paused')", (type_, ref_id))
    if ex:
        return ex["id"]
    jid = db.uid("job_")
    db.run("INSERT INTO jobs(id,type,ref_id,status,created,updated) VALUES(?,?,?,?,?,?)",
           (jid, type_, ref_id, "queued", db.now(), db.now()))
    return jid


def claim():
    """Atomically claim the oldest runnable job. Expired leases are reclaimed (worker crash recovery)."""
    with db.tx() as c:
        t = db.now()
        r = c.execute(
            "SELECT id FROM jobs WHERE status='queued' OR (status='running' AND lease_until<?) "
            "ORDER BY created LIMIT 1", (t,)).fetchone()
        if not r:
            return None
        c.execute("UPDATE jobs SET status='running', attempts=attempts+1, lease_until=?, updated=? WHERE id=?",
                  (t + config.LEASE_SECONDS, t, r["id"]))
        return dict(c.execute("SELECT * FROM jobs WHERE id=?", (r["id"],)).fetchone())


def heartbeat(job_id, stage=None):
    """Extend lease. Returns the current status so workers can notice pause requests."""
    t = db.now()
    st = db.q1("SELECT status FROM jobs WHERE id=?", (job_id,))["status"]
    if st == "running":
        db.run("UPDATE jobs SET lease_until=?, updated=?, stage=COALESCE(?,stage) WHERE id=?",
               (t + config.LEASE_SECONDS, t, stage, job_id))
    return st


def finish(job_id, ok, error=None):
    st = db.q1("SELECT status FROM jobs WHERE id=?", (job_id,))["status"]
    if st == "paused" and ok is None:
        return
    db.run("UPDATE jobs SET status=?, error=?, lease_until=NULL, updated=? WHERE id=?",
           ("done" if ok else "failed", error, db.now(), job_id))


def pause(job_id):
    db.run("UPDATE jobs SET status='paused', lease_until=NULL, updated=? WHERE id=? AND status IN ('queued','running')",
           (db.now(), job_id))


def resume(job_id):
    db.run("UPDATE jobs SET status='queued', updated=? WHERE id=? AND status='paused'", (db.now(), job_id))


def retry(job_id):
    db.run("UPDATE jobs SET status='queued', error=NULL, updated=? WHERE id=? AND status IN ('failed','paused')",
           (db.now(), job_id))
