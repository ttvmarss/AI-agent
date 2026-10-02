import os, tempfile, unittest
from praxis.guard import Guard, classify_shell, classify_call, ALLOW, DENY, ESCALATE


class ShellClassification(unittest.TestCase):
    def setUp(self):
        self.ws = tempfile.mkdtemp()

    def cls(self, cmd):
        return classify_shell(cmd, self.ws, sandboxed=True)

    def test_readonly_is_class0(self):
        for c in ["ls", "cat a.txt", "grep -n foo a.txt", "git status", "git diff", "git log"]:
            self.assertEqual(self.cls(c), 0, c)

    def test_test_runners_are_class2(self):
        for c in ["python3 -m unittest", "python3 -m pytest -q"]:
            self.assertEqual(self.cls(c), 2, c)

    def test_code_execution_needs_human_without_a_proven_sandbox(self):
        for c in ["python3 -m unittest", "python3 -m pytest -q", "pytest", "python3 run.py", "node app.js"]:
            self.assertEqual(classify_shell(c, self.ws, sandboxed=False), 4, c)
            self.assertEqual(classify_shell(c, self.ws, sandboxed=True), 2, c)

    def test_script_outside_workspace_never_trusted(self):
        for c in ["python3 /tmp/evil.py", "python3 ../x.py", "node /etc/x.js"]:
            self.assertGreaterEqual(classify_shell(c, self.ws, sandboxed=True), 4, c)

    def test_destructive_is_class5(self):
        for c in ["rm -rf .", "rm a.txt", "git push --force", "git reset --hard", "dd if=/dev/zero of=x",
                  "mkfs.ext4 /dev/sda", "git clean -fdx", "shred a"]:
            self.assertEqual(self.cls(c), 5, c)

    def test_network_is_class3_or_more(self):
        for c in ["curl http://evil.example", "wget x", "git push", "ssh host", "nc -l 1"]:
            self.assertGreaterEqual(self.cls(c), 3, c)

    def test_fail_closed_on_unknown_and_metachars(self):
        for c in ["frobnicate", "ls; rm -rf /", "cat a | sh", "ls && curl x", "echo `id`", "ls $(id)",
                  "cat a > b", "ls\nrm x", "", "'unterminated"]:
            self.assertGreaterEqual(self.cls(c), 4, repr(c))

    def test_path_escape_is_class4(self):
        for c in ["cat /etc/passwd", "cat ../../x", "ls /", "cat ~/.ssh/id_rsa"]:
            self.assertGreaterEqual(self.cls(c), 4, c)

    def test_interpreter_inline_code_is_not_trusted(self):
        for c in ["python3 -c 'import os; os.system(\"rm -rf /\")'", "bash -c ls", "sh x.sh", "env rm x",
                  "find . -delete", "find . -exec rm {} +", "xargs rm", "sed -i s/a/b/ f"]:
            self.assertGreaterEqual(self.cls(c), 4, c)


class FileClassification(unittest.TestCase):
    def setUp(self):
        self.ws = tempfile.mkdtemp()

    def test_fs(self):
        self.assertEqual(classify_call("fs.read", {"path": "a"}, self.ws), 0)
        self.assertEqual(classify_call("fs.write", {"path": "a", "content": ""}, self.ws), 2)
        self.assertGreaterEqual(classify_call("fs.write", {"path": "../a", "content": ""}, self.ws), 4)
        self.assertGreaterEqual(classify_call("fs.read", {"path": "/etc/passwd"}, self.ws), 4)

    def test_symlink_escape(self):
        os.symlink("/etc", os.path.join(self.ws, "link"))
        self.assertGreaterEqual(classify_call("fs.read", {"path": "link/passwd"}, self.ws), 4)

    def test_unknown_tool_fails_closed(self):
        self.assertEqual(classify_call("mystery.tool", {}, self.ws), 4)


class Decisions(unittest.TestCase):
    def setUp(self):
        self.ws = tempfile.mkdtemp()

    def test_unsandboxed_guard_escalates_code_execution(self):
        g = Guard(self.ws, max_auto_class=2, sandboxed=False)
        self.assertEqual(g.decide("shell.run", {"cmd": "python3 -m unittest"}).verdict, ESCALATE)

    def test_within_grant_allowed(self):
        g = Guard(self.ws, max_auto_class=2)
        self.assertEqual(g.decide("fs.write", {"path": "a", "content": "x"}).verdict, ALLOW)

    def test_above_grant_escalates_and_never_allows_without_approver(self):
        g = Guard(self.ws, max_auto_class=2)
        d = g.decide("shell.run", {"cmd": "curl http://x"})
        self.assertEqual(d.verdict, ESCALATE)
        self.assertEqual(g.authorize(d, approver=None), DENY)

    def test_approver_can_authorize_class3_and_4_but_5_needs_checkpoint(self):
        g = Guard(self.ws, max_auto_class=2)
        yes = lambda decision: True
        self.assertEqual(g.authorize(g.decide("shell.run", {"cmd": "curl http://x"}), yes), ALLOW)
        d5 = g.decide("shell.run", {"cmd": "rm a.txt"})
        self.assertEqual(d5.cls, 5)
        self.assertTrue(d5.requires_checkpoint)

    def test_taint_is_a_hard_cap_at_class2_that_no_approver_can_lift(self):
        g = Guard(self.ws, max_auto_class=2, sandboxed=True)
        self.assertEqual(g.decide("fs.read", {"path": "a"}, tainted=True).verdict, ALLOW)
        self.assertEqual(g.decide("fs.write", {"path": "a", "content": "x"}, tainted=True).verdict, ALLOW)  # reversible
        self.assertEqual(g.decide("shell.run", {"cmd": "python3 -m unittest"}, tainted=True).verdict, ALLOW)
        for tool, args in [("shell.run", {"cmd": "curl http://x"}), ("shell.run", {"cmd": "rm a"}),
                           ("shell.run", {"cmd": "touch x"}), ("agent.delegate", {"agent": "claude", "task": "t"})]:
            d = g.decide(tool, args, tainted=True)
            self.assertEqual(d.verdict, DENY, (tool, args))
            self.assertEqual(g.authorize(d, lambda x: True), DENY)  # even a human "yes" cannot launder it

    def test_grant_never_exceeds_cap(self):
        with self.assertRaises(ValueError):
            Guard(self.ws, max_auto_class=3)


if __name__ == "__main__":
    unittest.main()
