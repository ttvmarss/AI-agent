"""ffmpeg frame extraction: scene-change frames plus a minimum sampling interval, with true timestamps."""
import re
import subprocess
from pathlib import Path

from . import config, db


def extract(video_id: str, path: str):
    out = config.DATA_DIR / "frames" / video_id
    out.mkdir(parents=True, exist_ok=True)
    for f in out.glob("*.jpg"):
        f.unlink()
    n, thr = config.FRAME_MIN_INTERVAL_S, config.SCENE_THRESHOLD
    sel = f"select='gt(scene,{thr})+isnan(prev_selected_t)+gte(t-prev_selected_t,{n})',showinfo,scale=960:-2"
    p = subprocess.run(["ffmpeg", "-hide_banner", "-nostdin", "-i", path, "-vf", sel, "-vsync", "vfr",
                        "-q:v", "4", str(out / "%06d.jpg")], capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {p.stderr[-500:]}")
    times = [float(x) for x in re.findall(r"pts_time:([\d.]+)", p.stderr)]
    files = sorted(out.glob("*.jpg"))
    if not files:
        raise RuntimeError("ffmpeg produced no frames (is the file a valid video?)")
    if len(files) > config.MAX_FRAMES_PER_VIDEO:
        raise RuntimeError(f"{len(files)} frames exceeds MAX_FRAMES_PER_VIDEO; raise the limit or the interval")
    if len(times) != len(files):
        raise RuntimeError("frame/timestamp count mismatch")
    db.run("DELETE FROM frames WHERE video_id=?", (video_id,))
    c = db.connect()
    try:
        c.execute("BEGIN")
        for i, (f, t) in enumerate(zip(files, times)):
            c.execute("INSERT INTO frames(id,video_id,idx,t,path) VALUES(?,?,?,?,?)",
                      (f"{video_id}_{i:06d}", video_id, i, t, str(f.relative_to(config.DATA_DIR))))
        c.execute("COMMIT")
    finally:
        c.close()
    db.run("UPDATE videos SET frames_total=?, frames_done=0, pass2_total=0, pass2_done=0 WHERE id=?", (len(files), video_id))
    return len(files)


def probe_duration(path: str):
    p = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                       capture_output=True, text=True)
    return float(p.stdout.strip()) if p.returncode == 0 and p.stdout.strip() else None
