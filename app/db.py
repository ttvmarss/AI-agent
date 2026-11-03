"""SQLite (WAL) persistence. One file on a persistent volume; safe for API + worker processes."""
import json
import sqlite3
import time
import uuid
from contextlib import contextmanager

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS channels(
  id TEXT PRIMARY KEY, url TEXT UNIQUE, name TEXT, yt_channel_id TEXT,
  status TEXT DEFAULT 'new', last_discovered REAL, error TEXT, created REAL);
CREATE TABLE IF NOT EXISTS videos(
  id TEXT PRIMARY KEY, channel_id TEXT, yt_id TEXT UNIQUE, title TEXT, url TEXT,
  published TEXT, duration REAL, source TEXT DEFAULT 'youtube',
  relevance TEXT, relevance_reason TEXT, era TEXT,            -- era: current|historical
  status TEXT DEFAULT 'discovered',  -- discovered|queued|processing|analyzed|failed|skipped|restricted
  frames_total INTEGER DEFAULT 0, frames_done INTEGER DEFAULT 0,
  pass2_total INTEGER DEFAULT 0, pass2_done INTEGER DEFAULT 0,
  local_path TEXT, error TEXT, created REAL, analyzed_at REAL);
CREATE TABLE IF NOT EXISTS jobs(
  id TEXT PRIMARY KEY, type TEXT, ref_id TEXT, status TEXT DEFAULT 'queued', -- queued|running|paused|failed|done
  stage TEXT, attempts INTEGER DEFAULT 0, error TEXT, lease_until REAL,
  created REAL, updated REAL);
CREATE TABLE IF NOT EXISTS frames(
  id TEXT PRIMARY KEY, video_id TEXT, idx INTEGER, t REAL, path TEXT,
  pass1 INTEGER DEFAULT 0, pass2 INTEGER DEFAULT 0, needs_pass2 INTEGER DEFAULT 0,
  UNIQUE(video_id, idx));
CREATE TABLE IF NOT EXISTS observations(
  id TEXT PRIMARY KEY, video_id TEXT, frame_id TEXT, t REAL, pass INTEGER,
  kind TEXT, name TEXT, data TEXT, confidence REAL, entity_id TEXT, created REAL);
CREATE TABLE IF NOT EXISTS entities(
  id TEXT PRIMARY KEY, kind TEXT, name TEXT, norm_name TEXT, civilization TEXT, dimension TEXT,
  status TEXT DEFAULT 'observed',   -- observed|needs_review|destroyed|historical
  confidence REAL, data TEXT, missing TEXT, created REAL, updated REAL);
CREATE TABLE IF NOT EXISTS entity_sources(
  entity_id TEXT, video_id TEXT, frame_id TEXT, t REAL, era TEXT, published TEXT, note TEXT,
  confidence REAL, observation_id TEXT, UNIQUE(entity_id, observation_id));
CREATE TABLE IF NOT EXISTS merge_candidates(
  a TEXT, b TEXT, score REAL, reason TEXT, UNIQUE(a,b));
CREATE TABLE IF NOT EXISTS questions(
  id TEXT PRIMARY KEY, text TEXT, entity_id TEXT, video_id TEXT, created REAL, resolved INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS exports(
  id TEXT PRIMARY KEY, version TEXT, token TEXT UNIQUE, created REAL, counts TEXT, manifest_sha256 TEXT, note TEXT);
CREATE INDEX IF NOT EXISTS ix_obs_video ON observations(video_id);
CREATE INDEX IF NOT EXISTS ix_frames_video ON frames(video_id);
CREATE INDEX IF NOT EXISTS ix_ent_kind ON entities(kind);
"""


def connect():
    c = sqlite3.connect(config.DB_PATH, timeout=30, isolation_level=None)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA foreign_keys=ON")
    return c


@contextmanager
def tx():
    c = connect()
    try:
        c.execute("BEGIN IMMEDIATE")
        yield c
        c.execute("COMMIT")
    except Exception:
        c.execute("ROLLBACK")
        raise
    finally:
        c.close()


def init():
    c = connect()
    c.executescript(SCHEMA)
    c.close()


def q(sql, args=()):
    c = connect()
    try:
        return [dict(r) for r in c.execute(sql, args).fetchall()]
    finally:
        c.close()


def q1(sql, args=()):
    r = q(sql, args)
    return r[0] if r else None


def run(sql, args=()):
    c = connect()
    try:
        c.execute(sql, args)
    finally:
        c.close()


def uid(prefix=""):
    return prefix + uuid.uuid4().hex[:12]


def now():
    return time.time()


def jdump(o):
    return json.dumps(o, ensure_ascii=False, sort_keys=True)


def jload(s, default=None):
    try:
        return json.loads(s) if s else default
    except Exception:
        return default
