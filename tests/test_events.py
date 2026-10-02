import os, sqlite3, tempfile, unittest
from praxis.events import EventLog


class EventLogTests(unittest.TestCase):
    def test_chain_valid_and_causal_walk(self):
        log = EventLog()
        a = log.append("g", "user", "intent", {"x": 1})
        b = log.append("g", "executive", "plan", {}, parents=[a])
        c = log.append("g", "tool", "result", {}, parents=[b])
        self.assertEqual(log.verify_chain(), (True, None))
        self.assertEqual([e.id for e in log.ancestors(c)], [c, b, a])

    def test_tamper_detected(self):
        path = os.path.join(tempfile.mkdtemp(), "l.db")
        log = EventLog(path)
        for i in range(3):
            log.append("g", "a", "t", {"i": i})
        raw = sqlite3.connect(path)
        raw.execute("UPDATE events SET payload='{\"i\": 99}' WHERE id=2"); raw.commit()
        self.assertEqual(EventLog(path).verify_chain(), (False, 2))

    def test_deletion_detected(self):
        path = os.path.join(tempfile.mkdtemp(), "l.db")
        log = EventLog(path)
        for i in range(3):
            log.append("g", "a", "t", {"i": i})
        raw = sqlite3.connect(path)
        raw.execute("DELETE FROM events WHERE id=2"); raw.commit()
        ok, bad = EventLog(path).verify_chain()
        self.assertFalse(ok)

    def test_persists_across_reopen(self):
        path = os.path.join(tempfile.mkdtemp(), "l.db")
        EventLog(path).append("g", "a", "t", {"k": "v"})
        self.assertEqual(EventLog(path).all()[0].payload, {"k": "v"})


if __name__ == "__main__":
    unittest.main()


class ConcurrentOpen(unittest.TestCase):
    """Regression: two connections opening a NEW database at once used to raise 'database is locked'
    (journal_mode=WAL needs an exclusive lock and ignores the busy timeout)."""

    def test_many_threads_opening_a_fresh_db_and_writing(self):
        import threading
        for round_ in range(12):
            path = os.path.join(tempfile.mkdtemp(), "l.db")
            errors, barrier = [], threading.Barrier(8)

            def work(i):
                try:
                    barrier.wait()
                    log = EventLog(path)
                    for j in range(5):
                        log.append(f"g{i}", "a", "t", {"j": j})
                        log.since(0); log.last_goal_id()
                except Exception as e:
                    errors.append(repr(e))
            ts = [threading.Thread(target=work, args=(i,)) for i in range(8)]
            [t.start() for t in ts]; [t.join() for t in ts]
            self.assertEqual(errors, [], f"round {round_}")
            ok, bad = EventLog(path).verify_chain()
            self.assertTrue(ok, f"chain broken at {bad} in round {round_}")   # concurrent writers must not fork the chain
            self.assertEqual(len(EventLog(path).all()), 40)
