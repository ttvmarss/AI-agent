import os
from pathlib import Path

DATA_DIR = Path(os.environ.get("DATA_DIR", "./data")).resolve()
DB_PATH = Path(os.environ.get("DB_PATH", DATA_DIR / "analyzer.db"))
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
VISION_MODEL = os.environ.get("VISION_MODEL", "claude-sonnet-5-5")
WORKER_CONCURRENCY = int(os.environ.get("WORKER_CONCURRENCY", "2"))
FRAME_MIN_INTERVAL_S = float(os.environ.get("FRAME_MIN_INTERVAL_S", "8"))
SCENE_THRESHOLD = float(os.environ.get("SCENE_THRESHOLD", "0.30"))
FRAMES_PER_REQUEST = int(os.environ.get("FRAMES_PER_REQUEST", "4"))
MAX_FRAMES_PER_VIDEO = int(os.environ.get("MAX_FRAMES_PER_VIDEO", "4000"))
LEASE_SECONDS = int(os.environ.get("LEASE_SECONDS", "300"))
# Videos published on/after this date are "current"; earlier ones are historical-only.
CURRENT_FROM = os.environ.get("CURRENT_FROM", "2026-01-01")

for sub in ("videos", "frames", "exports", "uploads"):
    (DATA_DIR / sub).mkdir(parents=True, exist_ok=True)
