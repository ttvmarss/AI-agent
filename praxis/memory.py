"""Episodic + failure + procedural memory, DERIVED from the event log (rebuildable, provenance = goal ids).

Relevance-based retrieval (BM25, stdlib only). Nothing is stored that is not already an event, so memory
can never drift from the truth and can always be rebuilt or purged by editing/replaying the log.
"""
import math
import re

_STOP = set("the a an and or to of in on for with from into this that is are be it as at by do does please".split())


def _tok(text):
    return [w for w in re.findall(r"[a-z0-9_.]+", text.lower()) if w not in _STOP and len(w) > 1]


class Memory:
    def __init__(self, log):
        self.log = log

    def episodes(self):
        intents, reports = {}, {}
        for e in self.log.all():
            if e.type == "goal.intent":
                intents[e.goal_id] = e.payload.get("text", "")
            elif e.type == "goal.report":
                reports[e.goal_id] = e.payload
        out = []
        for g, text in intents.items():
            if g in reports:  # only finished goals are memories
                r = reports[g]
                out.append({"goal_id": g, "text": text, "status": r.get("status", ""), "reason": r.get("reason", "")})
        return out

    def search(self, query, k=3, exclude=()):
        docs = [(ep, _tok(ep["text"] + " " + ep["reason"])) for ep in self.episodes() if ep["goal_id"] not in exclude]
        q = _tok(query)
        if not docs or not q:
            return []
        n = len(docs)
        avg = sum(len(d) for _, d in docs) / n or 1.0
        df = {t: sum(t in d for _, d in docs) for t in set(q)}
        scored = []
        for ep, d in docs:
            s = 0.0
            for t in set(q):
                f = d.count(t)
                if f:
                    idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
                    s += idf * f * 2.5 / (f + 1.5 * (0.25 + 0.75 * len(d) / avg))
            if s > 0:
                scored.append((s, ep))
        scored.sort(key=lambda x: -x[0])
        return [dict(ep, score=round(s, 3)) for s, ep in scored[:k]]

    @staticmethod
    def render(hits):
        lines = []
        for h in hits:
            if h["status"] == "VERIFIED":
                lines.append(f"- earlier goal [{h['goal_id']}] succeeded: {h['text']!r}")
            else:
                lines.append(f"- PAST FAILURE [{h['goal_id']}] {h['status']}: {h['text']!r} | reason: {h['reason'][:300]}")
        return "\n".join(lines)
