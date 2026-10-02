"""Append-only, hash-chained event log (the root of the dependency graph)."""
import hashlib
import json
import sqlite3
import time
from dataclasses import dataclass, field

GENESIS = "0" * 64


@dataclass
class Event:
    id: int
    ts: float
    goal_id: str
    actor: str
    type: str
    payload: dict
    parent_ids: list
    prev_hash: str
    hash: str = field(default="")


def _digest(prev_hash, ts, goal_id, actor, type_, payload_json, parents_json):
    h = hashlib.sha256()
    for part in (prev_hash, repr(ts), goal_id, actor, type_, payload_json, parents_json):
        h.update(part.encode())
        h.update(b"\x00")
    return h.hexdigest()


class EventLog:
    def __init__(self, path=":memory:"):
        self.db = sqlite3.connect(path)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute(
            """CREATE TABLE IF NOT EXISTS events(
                 id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, goal_id TEXT,
                 actor TEXT, type TEXT, payload TEXT, parents TEXT,
                 prev_hash TEXT, hash TEXT)"""
        )
        self.db.commit()

    def _last_hash(self):
        row = self.db.execute("SELECT hash FROM events ORDER BY id DESC LIMIT 1").fetchone()
        return row[0] if row else GENESIS

    def append(self, goal_id, actor, type_, payload=None, parents=()):
        payload_json = json.dumps(payload or {}, sort_keys=True, default=str)
        parents_json = json.dumps(list(parents))
        ts = time.time()
        prev = self._last_hash()
        digest = _digest(prev, ts, goal_id, actor, type_, payload_json, parents_json)
        cur = self.db.execute(
            "INSERT INTO events(ts,goal_id,actor,type,payload,parents,prev_hash,hash) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (ts, goal_id, actor, type_, payload_json, parents_json, prev, digest),
        )
        self.db.commit()  # durable before the caller acts (write-ahead discipline)
        return cur.lastrowid

    @staticmethod
    def _row(r):
        return Event(r[0], r[1], r[2], r[3], r[4], json.loads(r[5]), json.loads(r[6]), r[7], r[8])

    def get(self, event_id):
        r = self.db.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
        return self._row(r) if r else None

    def all(self, goal_id=None, type_=None):
        q, args = "SELECT * FROM events", []
        conds = []
        if goal_id:
            conds.append("goal_id=?"); args.append(goal_id)
        if type_:
            conds.append("type=?"); args.append(type_)
        if conds:
            q += " WHERE " + " AND ".join(conds)
        return [self._row(r) for r in self.db.execute(q + " ORDER BY id", args)]

    def verify_chain(self):
        """Return (ok, first_bad_id). Detects edits, deletions and reordering."""
        prev = GENESIS
        for r in self.db.execute("SELECT * FROM events ORDER BY id"):
            e = self._row(r)
            expect = _digest(prev, e.ts, e.goal_id, e.actor, e.type,
                             json.dumps(e.payload, sort_keys=True, default=str),
                             json.dumps(e.parent_ids))
            if e.prev_hash != prev or e.hash != expect:
                return False, e.id
            prev = e.hash
        return True, None

    def ancestors(self, event_id):
        """Causal chain (event first, then its parents, transitively)."""
        seen, order, stack = set(), [], [event_id]
        while stack:
            i = stack.pop(0)
            if i in seen:
                continue
            seen.add(i)
            e = self.get(i)
            if e:
                order.append(e)
                stack.extend(e.parent_ids)
        return order
