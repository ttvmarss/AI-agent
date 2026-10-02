"""Windows decodes/encodes with the locale code page (cp1252), not UTF-8. We reproduce that on Linux by forcing an ASCII
locale in a child interpreter, then require every text path that touches model output or user files to be explicit UTF-8."""
import os, subprocess, sys, tempfile, textwrap, unittest

CHILD = textwrap.dedent('''
    import os, sys, json, tempfile, stat
    sys.path.insert(0, {repo!r})
    import locale
    assert locale.getpreferredencoding(False).upper() in ("ANSI_X3.4-1968", "US-ASCII", "ASCII"), locale.getpreferredencoding(False)
    TEXT = "check \\u2713 arrow \\u2192 emoji \\U0001F680 caf\\u00e9"

    from praxis.tools import Workspace
    ws = Workspace(tempfile.mkdtemp())
    ws.fs_write("u.txt", TEXT)
    assert ws.fs_read("u.txt") == TEXT, "fs round trip"
    r = ws.shell_run("python3 -c pass")  # must not choke on decoding
    assert r["returncode"] == 0

    from praxis import proc
    d = tempfile.mkdtemp(); p = os.path.join(d, "ucli")
    open(p, "w", encoding="utf-8").write("#!/usr/bin/env python3\\nimport sys\\nsys.stdout.buffer.write(sys.stdin.buffer.read() + 'ok \\u2713'.encode('utf-8'))\\n")
    os.chmod(p, 0o755)
    out, _ = proc.run_cli([p], TEXT, (), 20)
    assert TEXT in out and out.endswith("ok \\u2713"), repr(out)

    from praxis.desktop.settings import Settings
    s = Settings(tempfile.mkdtemp()); s.add_recent("/tmp/caf\\u00e9-\\u2713"); s.save()
    assert Settings(s.home).recent == ["/tmp/caf\\u00e9-\\u2713"]

    from praxis.events import EventLog
    log = EventLog(os.path.join(tempfile.mkdtemp(), "l.db")); i = log.append("g", "a", "t", {{"x": TEXT}})
    assert log.get(i).payload["x"] == TEXT and log.verify_chain()[0]

    from praxis import __main__ as cli
    import io, contextlib
    buf = io.TextIOWrapper(io.BytesIO(), encoding="ascii", errors="strict")
    sys.stdout = buf
    cli._safe_streams()
    cli._print_report(type("R", (), {{"status": "FAILED", "goal_id": "g", "checkpoint": "c", "reason": TEXT,
                                     "evidence": [{{"claim": TEXT, "passed": False}}]}})())
    print("OK")
''')


class AsciiLocale(unittest.TestCase):
    def test_everything_survives_a_non_utf8_locale(self):
        repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        env = {k: v for k, v in os.environ.items() if k not in ("PYTHONUTF8", "PYTHONIOENCODING")}
        env.update(LC_ALL="C", LANG="C", PYTHONUTF8="0", PYTHONCOERCECLOCALE="0")
        p = subprocess.run([sys.executable, "-c", CHILD.format(repo=repo)], env=env, capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr[-1500:])


if __name__ == "__main__":
    unittest.main()
