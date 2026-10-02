"""Desktop control: the policy, the Guard classes, the per-goal grant, the verifiers, the PNG encoder and a whole goal driven end to end against a fake backend.
The Windows backend itself could not be run where this was built (no Windows); everything around it is tested here."""
import json
import struct
import tempfile
import unittest
import zlib
from unittest import mock

from praxis import control, reflex
from praxis.control import ControlError, Controller, encode_png, parse_keys
from praxis.events import EventLog
from praxis.executive import Executive, FAILED, VERIFIED
from praxis.guard import ALLOW, DENY, ESCALATE, Guard
from praxis.opener import Opener
from praxis.router import Router, ScriptedProvider
from praxis.tools import ToolError, ToolRuntime, Workspace
from praxis.verifiers import verify


class FakeBackend(control.Backend):
    name = "fake"

    def __init__(self, front="Untitled - Notepad", cursor=(500, 400)):
        self.wins = [front, "Google Chrome"]
        self.front, self.pos, self.clip = front, cursor, ""
        self.calls = []

    def windows(self): return [{"title": t, "active": t == self.front} for t in self.wins]
    def foreground(self): return self.front
    def focus(self, title):
        hit = next((t for t in self.wins if title.lower() in t.lower()), None)
        if hit is None:
            raise ControlError(f"no open window has {title!r} in its title")
        self.front = hit; self.calls.append(("focus", hit)); return hit
    def close(self, title): self.calls.append(("close", title)); return title
    def type_text(self, text): self.calls.append(("type", text))
    def key(self, mods, key): self.calls.append(("key", tuple(mods), key))
    def click(self, x, y, button="left", double=False): self.calls.append(("click", x, y, button, double))
    def scroll(self, amount): self.calls.append(("scroll", amount))
    def clipboard_get(self): return self.clip
    def clipboard_set(self, text): self.clip = text
    def screenshot(self): return 4, 2, bytearray(bytes([10, 20, 30, 255]) * 8)
    def cursor(self): return self.pos
    def screen_size(self): return 1920, 1080


def ctl(**kw):
    ws = Workspace(tempfile.mkdtemp())
    return Controller(FakeBackend(**kw), ws, sleep=lambda s: None), ws


class Keys(unittest.TestCase):
    def test_chords_are_normalised(self):
        self.assertEqual(parse_keys("Control + S"), (["ctrl"], "s"))
        self.assertEqual(control.chord("shift+ctrl+t"), "ctrl+shift+t")
        self.assertEqual(parse_keys("Return"), ([], "enter"))

    def test_nonsense_is_refused(self):
        for bad in ("", None, "ctrl+", "foo+s", "ctrl", "a+b+c+d+e"):
            with self.assertRaises(ControlError, msg=repr(bad)):
                parse_keys(bad)


class Safety(unittest.TestCase):
    def test_never_types_into_a_terminal_or_run_dialog_or_a_password_prompt(self):
        for title in ("Windows PowerShell", "Command Prompt", "Windows Terminal", "Run", "PRAXIS", "User Account Control", "Bitwarden - Vault", "Sign in to your account"):
            c, _ = ctl(front=title)
            with self.assertRaises(ControlError, msg=title):
                c.type_text("rm -rf /")
            with self.assertRaises(ControlError, msg=title):
                c.key("enter")
            self.assertEqual(c.backend.calls, [], title)

    def test_focus_moving_to_a_terminal_midway_stops_typing(self):
        c, _ = ctl()
        original = c.backend.type_text
        def spy(text):
            original(text); c.backend.front = "Windows PowerShell"
        c.backend.type_text = spy
        with self.assertRaises(ControlError):
            c.type_text("x" * (control.CHUNK * 3))
        self.assertEqual(len(c.backend.calls), 1)               # only the first chunk went out

    def test_dangerous_chords_are_refused_in_any_spelling(self):
        for k in ("win+r", "Windows+R", "super + r", "ctrl+alt+delete", "ctrl+shift+esc", "win+l", "win+x"):
            c, _ = ctl()
            with self.assertRaises(ControlError, msg=k):
                c.key(k)
        c, _ = ctl()
        self.assertEqual(c.key("ctrl+s")["pressed"], "ctrl+s")

    def test_the_corner_failsafe_halts_everything_until_the_next_goal(self):
        c, _ = ctl(cursor=(0, 0))
        with self.assertRaises(ControlError) as cm:
            c.click(100, 100)
        self.assertIn("failsafe", str(cm.exception))
        c.backend.pos = (300, 300)
        with self.assertRaises(ControlError):
            c.key("enter")                                      # still halted
        c.reset()
        c.key("enter")

    def test_stop_interrupts_typing_and_waiting(self):
        c, _ = ctl()
        c.should_stop = lambda: True
        with self.assertRaises(ControlError):
            c.type_text("hello")
        with self.assertRaises(ControlError):
            c.wait(5)

    def test_clicks_off_screen_or_in_the_corner_are_refused(self):
        c, _ = ctl()
        for xy in ((-1, 5), (1920, 5), (5, 1080), (1, 1), ("a", 3)):
            with self.assertRaises(ControlError, msg=str(xy)):
                c.click(*xy)
        self.assertEqual(c.click(10, 10, "right", True)["button"], "right")
        with self.assertRaises(ControlError):
            c.click(10, 10, "laser")

    def test_will_not_close_a_terminal_and_limits_text_size(self):
        c, _ = ctl()
        with self.assertRaises(ControlError):
            c.close("PowerShell")
        with self.assertRaises(ControlError):
            c.type_text("x" * (control.MAX_TYPE + 1))

    def test_without_a_backend_every_tool_says_so_instead_of_pretending(self):
        c = Controller(None, Workspace(tempfile.mkdtemp()))
        for f in (c.windows, lambda: c.key("enter"), lambda: c.type_text("a"), lambda: c.click(5, 5), lambda: c.screenshot()):
            with self.assertRaises(ControlError):
                f()
        self.assertIn("NOT available", c.describe())


class Tools(unittest.TestCase):
    def test_screenshot_is_a_real_png_inside_the_workspace_only(self):
        c, ws = ctl()
        r = c.screenshot("shots/a")
        self.assertEqual(r["saved"], "shots/a.png")
        with open(ws.resolve("shots/a.png"), "rb") as f:
            data = f.read()
        self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
        with self.assertRaises(Exception):
            c.screenshot("../../outside.png")

    def test_png_encoder_round_trips_pixels_and_checks_crc(self):
        bgra = bytearray()
        for y in range(2):
            for x in range(3):
                bgra += bytes([x * 50, y * 100, 7, 255])        # B, G, R, A
        png = encode_png(3, 2, bgra)
        pos, chunks = 8, {}
        while pos < len(png):
            n, = struct.unpack(">I", png[pos:pos + 4]); tag = png[pos + 4:pos + 8]; body = png[pos + 8:pos + 8 + n]
            self.assertEqual(struct.unpack(">I", png[pos + 8 + n:pos + 12 + n])[0], zlib.crc32(tag + body) & 0xFFFFFFFF)
            chunks[tag] = body; pos += 12 + n
        self.assertEqual(struct.unpack(">IIBBBBB", chunks[b"IHDR"]), (3, 2, 8, 2, 0, 0, 0))
        raw = zlib.decompress(chunks[b"IDAT"])
        self.assertEqual(raw[0:1], b"\x00"); self.assertEqual(raw[1:4], bytes([7, 0, 0]))          # R, G, B of pixel (0,0)
        self.assertEqual(raw[10:11], b"\x00"); self.assertEqual(raw[11:14], bytes([7, 100, 0])); self.assertEqual(raw[14:17], bytes([7, 100, 50]))   # row 1: pixels (0,1) and (1,1)
        with self.assertRaises(ValueError):
            encode_png(3, 2, bytearray(4))

    def test_clipboard_round_trip_and_windows_listing(self):
        c, _ = ctl()
        c.clipboard("set", "héllo"); self.assertEqual(c.clipboard("get")["text"], "héllo")
        self.assertTrue(any(w["active"] for w in c.windows()))
        with self.assertRaises(ControlError):
            c.clipboard("burn")

    def test_toolruntime_turns_control_errors_into_tool_errors(self):
        c, ws = ctl(front="Windows PowerShell")
        rt = ToolRuntime(ws, control=c)
        with self.assertRaises(ToolError):
            rt.run("desktop.type", {"text": "dir"})
        c.backend.front = "Notepad"
        self.assertEqual(rt.run("desktop.type", {"text": "hi"})["typed"], 2)


class GuardClasses(unittest.TestCase):
    def setUp(self):
        self.ws = tempfile.mkdtemp()

    def cls(self, tool, args=None, granted=False, tainted=False):
        g = Guard(self.ws); g.desktop_granted = granted
        return g.decide(tool, args or {}, tainted=tainted)

    def test_observing_is_cheap_input_needs_a_human_until_granted(self):
        self.assertEqual(self.cls("desktop.windows").verdict, ALLOW)
        self.assertEqual(self.cls("desktop.wait", {"seconds": 1}).cls, 0)
        for t, a in (("desktop.type", {"text": "x"}), ("desktop.key", {"keys": "a"}), ("desktop.click", {"x": 5, "y": 5}), ("desktop.focus", {"title": "x"})):
            self.assertEqual(self.cls(t, a).verdict, ESCALATE, t)
            self.assertEqual(self.cls(t, a, granted=True).verdict, ALLOW, t)

    def test_closing_and_reading_the_clipboard_always_ask(self):
        self.assertEqual(self.cls("desktop.close", {"title": "x"}, granted=True).verdict, ESCALATE)
        self.assertEqual(self.cls("desktop.clipboard", {"op": "get"}, granted=True).verdict, ESCALATE)
        self.assertEqual(self.cls("desktop.clipboard", {"op": "set", "text": "a"}).verdict, ALLOW)

    def test_screenshot_outside_the_workspace_is_not_auto(self):
        self.assertEqual(self.cls("desktop.screenshot", {"name": "a.png"}).verdict, ALLOW)
        self.assertEqual(self.cls("desktop.screenshot", {"name": "/etc/x.png"}).verdict, ESCALATE)

    def test_a_tainted_plan_can_never_drive_the_desktop_even_with_a_grant(self):
        for t, a in (("desktop.type", {"text": "x"}), ("desktop.click", {"x": 5, "y": 5}), ("desktop.key", {"keys": "enter"}), ("desktop.screenshot", {})):
            self.assertEqual(self.cls(t, a, granted=True, tainted=True).verdict, DENY, t)

    def test_unknown_desktop_tool_fails_closed(self):
        self.assertEqual(self.cls("desktop.format_c").verdict, ESCALATE)


class Verifiers(unittest.TestCase):
    def test_window_and_clipboard_checks_use_the_real_screen_state(self):
        c, ws = ctl()
        self.assertTrue(verify({"type": "window_exists", "title": "chrome", "wait": 0}, ws, desktop=c).passed)
        self.assertFalse(verify({"type": "window_exists", "title": "nonexistent", "wait": 0}, ws, desktop=c).passed)
        self.assertTrue(verify({"type": "window_active", "title": "notepad"}, ws, desktop=c).passed)
        self.assertFalse(verify({"type": "window_active", "title": "chrome", "wait": 0}, ws, desktop=c).passed)
        c.backend.clip = "copied text"
        self.assertTrue(verify({"type": "clipboard_contains", "text": "copied"}, ws, desktop=c).passed)
        self.assertFalse(verify({"type": "clipboard_contains", "text": "other"}, ws, desktop=c).passed)

    def test_without_desktop_control_the_check_fails_not_passes(self):
        self.assertFalse(verify({"type": "window_exists", "title": "x"}, Workspace(tempfile.mkdtemp()), desktop=None).passed)


class Goals(unittest.TestCase):
    def setUp(self):
        self.ws = tempfile.mkdtemp()
        self.log = EventLog()

    def executive(self, plan, approver, **bk):
        c = Controller(FakeBackend(**bk), Workspace(self.ws), sleep=lambda s: None)
        prov = ScriptedProvider([json.dumps(plan)])
        return Executive(self.ws, self.log, Router([prov]), approver=approver, control=c, critic=False), c, prov

    PLAN = {"steps": [{"id": "f", "tool": "desktop.focus", "args": {"title": "notepad"}, "verify": {"type": "window_active", "title": "notepad"}},
                      {"id": "t", "tool": "desktop.type", "args": {"text": "hello"}, "verify": {"type": "none"}},
                      {"id": "k", "tool": "desktop.key", "args": {"keys": "ctrl+s"}, "verify": {"type": "none"}}],
            "success": [{"type": "window_active", "title": "notepad"}]}

    def test_one_approval_covers_the_goal_and_everything_is_logged(self):
        asked = []
        ex, c, _ = self.executive(self.PLAN, lambda d: asked.append(d) or True)
        r = ex.run("I would like you to write hello in the notepad window and save it")
        self.assertEqual(r.status, VERIFIED, r.reason)
        self.assertEqual(len(asked), 1)                                          # asked once (focus), then granted for the goal
        self.assertEqual([x[0] for x in c.backend.calls], ["focus", "type", "key"])
        self.assertEqual(sum(1 for e in self.log.all() if e.type == "step.intent"), 3)
        self.assertTrue(self.log.verify_chain())

    def test_a_denied_approval_touches_nothing(self):
        ex, c, _ = self.executive(self.PLAN, lambda d: False)
        r = ex.run("I would like you to write hello in the notepad window and save it")
        self.assertEqual(r.status, FAILED); self.assertEqual(c.backend.calls, [])

    def test_the_grant_does_not_leak_into_the_next_goal(self):
        ex, c, prov = self.executive(self.PLAN, lambda d: True)
        ex.run("I would like you to write hello in the notepad window and save it")
        self.assertTrue(ex.guard.desktop_granted)
        with mock.patch.object(ex, "_run", side_effect=lambda g: None):
            ex.run("anything")
        self.assertFalse(ex.guard.desktop_granted)

    def test_typing_into_a_terminal_fails_the_goal_even_after_approval(self):
        plan = dict(self.PLAN); plan["steps"] = [{"id": "t", "tool": "desktop.type", "args": {"text": "del *"}, "verify": {"type": "none"}}]
        ex2, c2, _ = self.executive(plan, lambda d: True, front="Windows PowerShell")
        r = ex2.run("I would like you to type a command into the console please")
        self.assertEqual(r.status, FAILED); self.assertIn("terminal", r.reason); self.assertEqual(c2.backend.calls, [])

    def test_the_planner_is_told_about_desktop_control(self):
        ex, _, _ = self.executive(self.PLAN, None)
        s = ex._system()
        self.assertIn("desktop.focus{title}", s); self.assertIn("window_active{title}", s)


class ScreenshotReflex(unittest.TestCase):
    def test_a_screenshot_is_instant_free_and_verified(self):
        ws = tempfile.mkdtemp(); log = EventLog()
        c = Controller(FakeBackend(), Workspace(ws), sleep=lambda s: None)
        prov = ScriptedProvider([])
        ex = Executive(ws, log, Router([prov]), control=c, critic=False)
        for phrase in ("take a screenshot", "Can you please grab a screenshot of my screen."):
            r = ex.run(phrase)
            self.assertEqual(r.status, VERIFIED, (phrase, r.reason))
        self.assertNotIn("model.try", [e.type for e in log.all()])
        self.assertIsNone(reflex.match("take a screenshot", Opener(ws), Controller(None, None)))      # no backend: the planner explains instead


if __name__ == "__main__":
    unittest.main()
