import os, tempfile, unittest
from praxis.guard import Guard, classify_call, ESCALATE, DENY, ALLOW
from praxis.tools import ToolRuntime, Workspace, ToolError
from praxis.router import ProviderError


class FakeAgent:
    can_delegate = True

    def __init__(self, edit=None, fail=None):
        self.edit, self.fail, self.calls = edit, fail, []

    def delegate(self, task, cwd):
        self.calls.append((task, cwd))
        if self.fail:
            raise ProviderError(self.fail)
        if self.edit:
            for name, text in self.edit.items():
                with open(os.path.join(cwd, name), "w") as f:
                    f.write(text)
        return "done"


class DelegateGuard(unittest.TestCase):
    def setUp(self):
        self.ws = tempfile.mkdtemp()

    def test_classes(self):
        for agent, cls in [("claude", 3), ("codex", 3), ("droid", 3), ("devin", 4), ("unknown", 4)]:
            self.assertEqual(classify_call("agent.delegate", {"agent": agent, "task": "x"}, self.ws), cls, agent)
        self.assertEqual(classify_call("agent.delegate", {"agent": "claude", "task": ""}, self.ws), 4)
        self.assertEqual(classify_call("agent.delegate", {"agent": "claude"}, self.ws), 4)

    def test_never_auto_allowed_and_tainted_denied(self):
        g = Guard(self.ws)
        d = g.decide("agent.delegate", {"agent": "claude", "task": "x"})
        self.assertEqual(d.verdict, ESCALATE)
        self.assertEqual(g.authorize(d, None), DENY)
        self.assertEqual(g.decide("agent.delegate", {"agent": "claude", "task": "x"}, tainted=True).verdict, DENY)


class DelegateRuntime(unittest.TestCase):
    def setUp(self):
        self.ws = Workspace(tempfile.mkdtemp())

    def test_reports_changed_files(self):
        with open(os.path.join(self.ws.root, "keep.txt"), "w") as f:
            f.write("same")
        agent = FakeAgent(edit={"new.py": "x=1", "keep.txt": "changed"})
        rt = ToolRuntime(self.ws, agents={"claude": agent})
        out = rt.run("agent.delegate", {"agent": "claude", "task": "do it"})
        self.assertEqual(out["changed"], ["keep.txt", "new.py"])
        self.assertEqual(agent.calls[0][1], self.ws.root)  # runs inside the workspace only

    def test_unknown_or_unconfigured_agent_rejected(self):
        rt = ToolRuntime(self.ws, agents={"claude": FakeAgent()})
        with self.assertRaises(ToolError):
            rt.run("agent.delegate", {"agent": "codex", "task": "x"})

    def test_agent_failure_is_tool_error(self):
        rt = ToolRuntime(self.ws, agents={"claude": FakeAgent(fail="boom")})
        with self.assertRaises(ToolError):
            rt.run("agent.delegate", {"agent": "claude", "task": "x"})


if __name__ == "__main__":
    unittest.main()
