"""Plumbing tests. The fake vision client below is TEST-ONLY; its output is never usable outside this temp DB."""
import json, os, subprocess, importlib, hashlib
import pytest

@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path)); monkeypatch.setenv("ADMIN_TOKEN", "t0k")
    import app.config as c; importlib.reload(c)
    import app.db as d; importlib.reload(d)
    for m in ("queue", "merge", "frames", "vision", "export", "worker", "youtube"):
        importlib.reload(importlib.import_module("app." + m))
    d.init()
    return tmp_path

def make_video(path):
    subprocess.run(["ffmpeg","-y","-loglevel","error","-f","lavfi","-i","testsrc=duration=30:size=640x360:rate=10","-pix_fmt","yuv420p",str(path)],check=True)

class FakeClient:
    class messages:
        @staticmethod
        def create(model, max_tokens, system, messages):
            txt = [b["text"] for b in messages[0]["content"] if b["type"]=="text" and b["text"].startswith("frame_index")]
            frames = []
            for t in txt:
                i = int(t.split("=")[1].split()[0])
                obs = [{"kind":"building","name":"Test Keep","civilization":"TESTCIV","dimension":"overworld","is_interior":i%2==0,
                        "description":"stone keep","materials":["stone_bricks"],"est_dimensions":None,"evidence":"sign reads Test Keep",
                        "confidence":0.4 if i==0 else 0.9,"ambiguous":i==0}]
                frames.append({"frame_index":i,"in_game":True,"observations":obs})
            class R: content=[type("B",(),{"text":json.dumps({"frames":frames})})]
            return R()

def test_queue_lease_and_pause(env):
    from app import queue, db
    j = queue.enqueue("process_video","x"); assert queue.enqueue("process_video","x")==j
    c = queue.claim(); assert c["id"]==j and queue.claim() is None
    queue.pause(j); assert queue.heartbeat(j)=="paused"
    queue.resume(j); assert queue.claim()["id"]==j
    db.run("UPDATE jobs SET lease_until=0 WHERE id=?",(j,))   # simulated worker crash
    assert queue.claim()["id"]==j

def test_pipeline_and_export(env):
    from app import db, queue, worker, export
    p = env/"v.mp4"; make_video(p)
    db.run("INSERT INTO videos(id,yt_id,title,url,published,source,relevance,era,status,local_path,created) VALUES('v1','u1','T','upload://v1','2026-05-01','upload','relevant','current','queued',?,0)",(str(p),))
    jid = queue.enqueue("process_video","v1"); job = queue.claim()
    worker.process_video(job, client=FakeClient)
    v = db.q1("SELECT * FROM videos WHERE id='v1'")
    assert v["status"]=="analyzed" and v["frames_done"]==v["frames_total"]>=3 and v["pass2_total"]>=1 and v["pass2_done"]==v["pass2_total"]
    ents = db.q("SELECT * FROM entities"); assert len(ents)==1 and ents[0]["name"]=="Test Keep"   # dedup across frames
    assert len(db.q("SELECT * FROM entity_sources"))>=3
    r = export.build("https://example.test")
    root = env/"exports"/r["token"]; m = json.loads((root/"manifest.json").read_text())
    for f in m["files"]:
        b = (root/f["path"]).read_bytes(); assert hashlib.sha256(b).hexdigest()==f["sha256"]
    assert m["coverage"]["complete_world_claimed"] is False
    assert any(f["path"].startswith("evidence/frames/") for f in m["files"])

def test_no_key_fails_loudly(env, monkeypatch):
    from app import db, queue, worker
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    p = env/"v.mp4"; make_video(p)
    db.run("INSERT INTO videos(id,yt_id,title,url,published,source,relevance,era,status,local_path,created) VALUES('v1','u1','T','x','2026-05-01','upload','relevant','current','queued',?,0)",(str(p),))
    queue.enqueue("process_video","v1"); worker.process_video(queue.claim())
    v = db.q1("SELECT * FROM videos WHERE id='v1'"); assert v["status"]=="failed" and "ANTHROPIC_API_KEY" in v["error"]
    assert db.q("SELECT * FROM entities")==[]

def test_classify_and_url(env):
    from app import youtube
    assert youtube.classify("Unstable SMP Day 5","",[], "2026-03-01")[0]=="relevant"
    assert youtube.classify("Minecraft hardcore","",[], "2026-03-01")[0]=="irrelevant"
    assert youtube.classify("Unstable SMP","",[], "2025-03-01")[2]=="historical"
    assert youtube.parse_channel_url("https://www.youtube.com/@Wemmbu/videos").endswith("@Wemmbu")
    with pytest.raises(ValueError): youtube.parse_channel_url("https://evil.com/@x")
