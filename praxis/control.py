"""Desktop control: windows, keyboard, mouse, clipboard and screenshots, behind the same Guard, approval, checkpoint and verification as every other tool.

Three layers, so the dangerous part is small and the rest is testable anywhere:

* `Controller`: platform-neutral. Owns the safety policy (what may never be typed where, which keys are refused, the mouse-corner failsafe, the Stop
  signal, pacing) and turns a tool call into backend calls. Tested with a fake backend.
* `Backend`: the few primitives an operating system provides. `WindowsBackend` is ctypes over user32/gdi32 (no dependency). Elsewhere there is no
  backend and every tool says so plainly (never a pretend success).
* `encode_png`: pure Python, so screenshots need no imaging library and the encoder is unit-tested.

Safety rules that hold whatever a plan says (each one is a test):
1. Never type or send keys into a terminal, a Run dialog, or a UAC / credential / password-manager window: a typed command there would bypass the
   Guard's shell classification. Commands go through shell.run, which is classified.
2. Win+R, Win+X, Ctrl+Alt+Del, Ctrl+Shift+Esc and Win+L are refused.
3. Failsafe: the mouse in the top-left screen corner halts desktop control (and so does Stop). Clicks aimed at that corner are refused.
4. Every action is logged by the executive before it runs (step.intent), checkpointed, and verifiable with window_exists / window_active / clipboard_contains.
"""
import ctypes
import os
import re
import struct
import sys
import time
import zlib

IS_WINDOWS = sys.platform == "win32"


class ControlError(Exception):
    """A desktop action was refused or failed. The message is shown to the user and the planner."""


# -- policy --------------------------------------------------------------------------------------------------------------------------------------
TERMINAL_TITLE = re.compile(r"(command prompt|powershell|windows terminal|cmd\.exe|\bterminal\b|\bbash\b|\bwsl\b|git bash|\bconsole\b|^run$|^praxis\b)", re.I)
SENSITIVE_TITLE = re.compile(r"(user account control|windows security|credential|password|keepass|bitwarden|1password|lastpass|authenticator|sign in to|log in to)", re.I)
BLOCKED_KEYS = {"win+r", "win+x", "win+l", "ctrl+alt+delete", "ctrl+alt+del", "ctrl+shift+esc", "ctrl+esc"}
MAX_TYPE = 4000
CHUNK = 40
MODS = ("ctrl", "shift", "alt", "win")
ALIASES = {"control": "ctrl", "cmd": "win", "windows": "win", "super": "win", "meta": "win", "return": "enter", "escape": "esc", "del": "delete",
           "pgup": "pageup", "pgdn": "pagedown", "pagedn": "pagedown", "backspace": "backspace", "spacebar": "space", "option": "alt"}


def parse_keys(spec):
    """'ctrl+shift+t' -> (['ctrl','shift'], 't'). Raises ControlError for anything that is not a plain chord."""
    if not isinstance(spec, str) or not spec.strip():
        raise ControlError("desktop.key needs keys such as 'ctrl+c' or 'enter'")
    parts = [ALIASES.get(p.strip().lower(), p.strip().lower()) for p in spec.replace(" + ", "+").split("+")]
    if any(not p for p in parts) or len(parts) > 4:
        raise ControlError(f"cannot read the key combination {spec!r}")
    key, mods = parts[-1], parts[:-1]
    if any(m not in MODS for m in mods):
        raise ControlError(f"{spec!r}: only ctrl, shift, alt and win can be held")
    if key in MODS and not mods:
        raise ControlError(f"{spec!r}: a modifier alone does nothing")
    return mods, key


def chord(spec):
    mods, key = parse_keys(spec)
    return "+".join(sorted(mods, key=MODS.index) + [key])


# -- screenshots: PNG with the standard library ---------------------------------------------------------------------------------------------------
def encode_png(width, height, bgra):
    """32-bit BGRA rows (top-down) -> PNG bytes."""
    if width <= 0 or height <= 0 or len(bgra) < width * height * 4:
        raise ValueError("bad image size")
    rgb = bytearray(width * height * 3)
    rgb[0::3], rgb[1::3], rgb[2::3] = bgra[2:width * height * 4:4], bgra[1:width * height * 4:4], bgra[0:width * height * 4:4]
    stride = width * 3
    raw = b"".join(b"\x00" + bytes(rgb[y * stride:(y + 1) * stride]) for y in range(height))

    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw, 3)) + chunk(b"IEND", b"")


# -- backends ------------------------------------------------------------------------------------------------------------------------------------
class Backend:
    """What an operating system must provide. Titles are matched case-insensitively by substring."""
    name = "none"

    def windows(self): raise NotImplementedError          # -> [{"title": str, "active": bool}] visible top-level windows, front first
    def foreground(self): raise NotImplementedError       # -> title of the active window ("" when none)
    def focus(self, title): raise NotImplementedError     # -> the title now active; raises ControlError
    def close(self, title): raise NotImplementedError     # politely asks the window to close (WM_CLOSE); never kills a process
    def type_text(self, text): raise NotImplementedError
    def key(self, mods, key): raise NotImplementedError
    def click(self, x, y, button="left", double=False): raise NotImplementedError
    def scroll(self, amount): raise NotImplementedError  # positive = up
    def clipboard_get(self): raise NotImplementedError
    def clipboard_set(self, text): raise NotImplementedError
    def screenshot(self): raise NotImplementedError       # -> (width, height, BGRA bytes)
    def cursor(self): raise NotImplementedError           # -> (x, y)
    def screen_size(self): raise NotImplementedError      # -> (w, h)


_VK = {"enter": 0x0D, "tab": 0x09, "esc": 0x1B, "space": 0x20, "backspace": 0x08, "delete": 0x2E, "home": 0x24, "end": 0x23, "pageup": 0x21,
       "pagedown": 0x22, "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28, "insert": 0x2D, "ctrl": 0x11, "shift": 0x10, "alt": 0x12, "win": 0x5B}
_VK.update({f"f{i}": 0x70 + i - 1 for i in range(1, 13)})
_EXTENDED = {0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E, 0x5B}


def vk_for(key):
    if key in _VK:
        return _VK[key]
    if len(key) == 1 and key.isalnum() and key.isascii():
        return ord(key.upper())
    raise ControlError(f"unknown key {key!r}")


class WindowsBackend(Backend):
    """ctypes over user32/gdi32/kernel32. Written from the documented Win32 API; it could NOT be run where it was built (no Windows here), so the
    first run on a real PC is the first real test: `python -m praxis control selftest` exercises it safely (see __main__)."""
    name = "windows"

    def __init__(self):
        if not IS_WINDOWS:
            raise ControlError("the Windows backend only runs on Windows")
        from ctypes import wintypes
        self.w = wintypes
        self.u, self.g, self.k = ctypes.windll.user32, ctypes.windll.gdi32, ctypes.windll.kernel32
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)        # real pixels, not scaled ones, so coordinates match screenshots
        except Exception:
            try:
                self.u.SetProcessDPIAware()
            except Exception:
                pass
        w = wintypes
        self.u.GetForegroundWindow.restype = w.HWND
        self.u.GetWindowTextW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
        self.u.GetWindowTextLengthW.argtypes = [w.HWND]
        self.u.IsWindowVisible.argtypes = [w.HWND]
        self.u.IsIconic.argtypes = [w.HWND]
        self.u.ShowWindow.argtypes = [w.HWND, ctypes.c_int]
        self.u.SetForegroundWindow.argtypes = [w.HWND]
        self.u.PostMessageW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
        self.u.GetWindowLongW.argtypes = [w.HWND, ctypes.c_int]
        self.k.GlobalAlloc.restype = ctypes.c_void_p
        self.k.GlobalAlloc.argtypes = [w.UINT, ctypes.c_size_t]
        self.k.GlobalLock.restype = ctypes.c_void_p
        self.k.GlobalLock.argtypes = [ctypes.c_void_p]
        self.k.GlobalUnlock.argtypes = [ctypes.c_void_p]
        self.u.SetClipboardData.argtypes = [w.UINT, ctypes.c_void_p]
        self.u.SetClipboardData.restype = ctypes.c_void_p
        self.u.GetClipboardData.argtypes = [w.UINT]
        self.u.GetClipboardData.restype = ctypes.c_void_p

    # windows
    def _title(self, h):
        n = self.u.GetWindowTextLengthW(h)
        if n <= 0:
            return ""
        buf = ctypes.create_unicode_buffer(n + 1)
        self.u.GetWindowTextW(h, buf, n + 1)
        return buf.value

    def _enum(self):
        w, out = self.w, []
        EnumProc = ctypes.WINFUNCTYPE(ctypes.c_bool, w.HWND, w.LPARAM)
        fg = self.u.GetForegroundWindow()

        def cb(h, _):
            if self.u.IsWindowVisible(h):
                t = self._title(h)
                ex = self.u.GetWindowLongW(h, -20)                # GWL_EXSTYLE
                if t and t != "Program Manager" and not ex & 0x80:  # WS_EX_TOOLWINDOW
                    out.append((h, t, h == fg))
            return True
        self.u.EnumWindows(EnumProc(cb), 0)
        return out

    def windows(self):
        return [{"title": t, "active": a} for _, t, a in self._enum()]

    def foreground(self):
        return self._title(self.u.GetForegroundWindow())

    def _find(self, title):
        want = str(title).lower()
        hits = [(h, t) for h, t, _ in self._enum() if want in t.lower()]
        if not hits:
            raise ControlError(f"no open window has {title!r} in its title")
        return hits[0]

    def focus(self, title):
        h, t = self._find(title)
        if self.u.IsIconic(h):
            self.u.ShowWindow(h, 9)                                # SW_RESTORE
        self.u.keybd_event(0x12, 0, 0, 0)                          # a tap of Alt lets a background process take the foreground
        self.u.keybd_event(0x12, 0, 2, 0)
        self.u.SetForegroundWindow(h)
        time.sleep(0.15)
        return self.foreground() or t

    def close(self, title):
        h, t = self._find(title)
        self.u.PostMessageW(h, 0x0010, 0, 0)                       # WM_CLOSE: the program may ask to save; nothing is killed
        return t

    # input
    def _send(self, *inputs):
        arr = (_INPUT * len(inputs))(*inputs)
        if self.u.SendInput(len(inputs), arr, ctypes.sizeof(_INPUT)) != len(inputs):
            raise ControlError("Windows refused the input (a higher-privilege window may be in front)")

    def type_text(self, text):
        for line_no, line in enumerate(text.replace("\r\n", "\n").replace("\r", "\n").split("\n")):
            if line_no:
                self.key([], "enter")
            data = line.encode("utf-16-le")
            units = struct.unpack("<%dH" % (len(data) // 2), data) if data else ()
            for i in range(0, len(units), 16):                       # a handful of characters per SendInput call
                evs = []
                for c in units[i:i + 16]:
                    evs += [_kb(0, c, 0x0004), _kb(0, c, 0x0004 | 0x0002)]       # KEYEVENTF_UNICODE down, up
                self._send(*evs)
                time.sleep(0.004)

    def key(self, mods, key): raise NotImplementedError
    def click(self, x, y, button="left", double=False): raise NotImplementedError
    def scroll(self, amount): raise NotImplementedError  # positive = up
    def clipboard_get(self): raise NotImplementedError
    def clipboard_set(self, text): raise NotImplementedError
    def screenshot(self): raise NotImplementedError       # -> (width, height, BGRA bytes)
    def cursor(self): raise NotImplementedError           # -> (x, y)
    def screen_size(self): raise NotImplementedError      # -> (w, h)


_VK = {"enter": 0x0D, "tab": 0x09, "esc": 0x1B, "space": 0x20, "backspace": 0x08, "delete": 0x2E, "home": 0x24, "end": 0x23, "pageup": 0x21,
       "pagedown": 0x22, "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28, "insert": 0x2D, "ctrl": 0x11, "shift": 0x10, "alt": 0x12, "win": 0x5B}
_VK.update({f"f{i}": 0x70 + i - 1 for i in range(1, 13)})
_EXTENDED = {0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E, 0x5B}


def vk_for(key):
    if key in _VK:
        return _VK[key]
    if len(key) == 1 and key.isalnum() and key.isascii():
        return ord(key.upper())
    raise ControlError(f"unknown key {key!r}")


class WindowsBackend(Backend):
    """ctypes over user32/gdi32/kernel32. Written from the documented Win32 API; it could NOT be run where it was built (no Windows here), so the
    first run on a real PC is the first real test: `python -m praxis control selftest` exercises it safely (see __main__)."""
    name = "windows"

    def __init__(self):
        if not IS_WINDOWS:
            raise ControlError("the Windows backend only runs on Windows")
        from ctypes import wintypes
        self.w = wintypes
        self.u, self.g, self.k = ctypes.windll.user32, ctypes.windll.gdi32, ctypes.windll.kernel32
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)        # real pixels, not scaled ones, so coordinates match screenshots
        except Exception:
            try:
                self.u.SetProcessDPIAware()
            except Exception:
                pass
        w = wintypes
        self.u.GetForegroundWindow.restype = w.HWND
        self.u.GetWindowTextW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
        self.u.GetWindowTextLengthW.argtypes = [w.HWND]
        self.u.IsWindowVisible.argtypes = [w.HWND]
        self.u.IsIconic.argtypes = [w.HWND]
        self.u.ShowWindow.argtypes = [w.HWND, ctypes.c_int]
        self.u.SetForegroundWindow.argtypes = [w.HWND]
        self.u.PostMessageW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
        self.u.GetWindowLongW.argtypes = [w.HWND, ctypes.c_int]
        self.k.GlobalAlloc.restype = ctypes.c_void_p
        self.k.GlobalAlloc.argtypes = [w.UINT, ctypes.c_size_t]
        self.k.GlobalLock.restype = ctypes.c_void_p
        self.k.GlobalLock.argtypes = [ctypes.c_void_p]
        self.k.GlobalUnlock.argtypes = [ctypes.c_void_p]
        self.u.SetClipboardData.argtypes = [w.UINT, ctypes.c_void_p]
        self.u.SetClipboardData.restype = ctypes.c_void_p
        self.u.GetClipboardData.argtypes = [w.UINT]
        self.u.GetClipboardData.restype = ctypes.c_void_p

    # windows
    def _title(self, h):
        n = self.u.GetWindowTextLengthW(h)
        if n <= 0:
            return ""
        buf = ctypes.create_unicode_buffer(n + 1)
        self.u.GetWindowTextW(h, buf, n + 1)
        return buf.value

    def _enum(self):
        w, out = self.w, []
        EnumProc = ctypes.WINFUNCTYPE(ctypes.c_bool, w.HWND, w.LPARAM)
        fg = self.u.GetForegroundWindow()

        def cb(h, _):
            if self.u.IsWindowVisible(h):
                t = self._title(h)
                ex = self.u.GetWindowLongW(h, -20)                # GWL_EXSTYLE
                if t and t != "Program Manager" and not ex & 0x80:  # WS_EX_TOOLWINDOW
                    out.append((h, t, h == fg))
            return True
        self.u.EnumWindows(EnumProc(cb), 0)
        return out

    def windows(self):
        return [{"title": t, "active": a} for _, t, a in self._enum()]

    def foreground(self):
        return self._title(self.u.GetForegroundWindow())

    def _find(self, title):
        want = str(title).lower()
        hits = [(h, t) for h, t, _ in self._enum() if want in t.lower()]
        if not hits:
            raise ControlError(f"no open window has {title!r} in its title")
        return hits[0]

    def focus(self, title):
        h, t = self._find(title)
        if self.u.IsIconic(h):
            self.u.ShowWindow(h, 9)                                # SW_RESTORE
        self.u.keybd_event(0x12, 0, 0, 0)                          # a tap of Alt lets a background process take the foreground
        self.u.keybd_event(0x12, 0, 2, 0)
        self.u.SetForegroundWindow(h)
        time.sleep(0.15)
        return self.foreground() or t

    def close(self, title):
        h, t = self._find(title)
        self.u.PostMessageW(h, 0x0010, 0, 0)                       # WM_CLOSE: the program may ask to save; nothing is killed
        return t

    # input
    def _send(self, *inputs):
        arr = (_INPUT * len(inputs))(*inputs)
        if self.u.SendInput(len(inputs), arr, ctypes.sizeof(_INPUT)) != len(inputs):
            raise ControlError("Windows refused the input (a higher-privilege window may be in front)")

    def type_text(self, text):
        for unit in re.findall(r"[\ud800-\udbff][\udc00-\udfff]|.", text, re.S):
            if unit in "\r\n":
                if unit == "\n" or True:
                    self.key([], "enter") if unit == "\n" else None
                continue
            codes = [struct.unpack("<H", unit.encode("utf-16-le")[i:i + 2])[0] for i in range(0, len(unit.encode("utf-16-le")), 2)]
            evs = []
            for c in codes:
                evs += [_kb(0, c, 0x0004), _kb(0, c, 0x0004 | 0x0002)]
            self._send(*evs)
            time.sleep(0.004)

    def key(self, mods, key):
        vks = [vk_for(m) for m in mods]
        k = vk_for(key)
        evs = [_kb(v, 0, 1 if v in _EXTENDED else 0) for v in vks]
        evs += [_kb(k, 0, 1 if k in _EXTENDED else 0), _kb(k, 0, (1 if k in _EXTENDED else 0) | 2)]
        evs += [_kb(v, 0, (1 if v in _EXTENDED else 0) | 2) for v in reversed(vks)]
        self._send(*evs)

    def click(self, x, y, button="left", double=False):
        self.u.SetCursorPos(int(x), int(y))
        time.sleep(0.03)
        down, up = {"left": (0x0002, 0x0004), "right": (0x0008, 0x0010), "middle": (0x0020, 0x0040)}[button]
        for _ in range(2 if double else 1):
            self._send(_ms(down), _ms(up))
            time.sleep(0.04)

    def scroll(self, amount):
        self._send(_ms(0x0800, int(amount) * 120))

    # clipboard
    def clipboard_get(self):
        for _ in range(10):
            if self.u.OpenClipboard(None):
                break
            time.sleep(0.02)
        else:
            raise ControlError("the clipboard is busy")
        try:
            h = self.u.GetClipboardData(13)                        # CF_UNICODETEXT
            if not h:
                return ""
            p = self.k.GlobalLock(h)
            try:
                return ctypes.wstring_at(p)
            finally:
                self.k.GlobalUnlock(h)
        finally:
            self.u.CloseClipboard()

    def clipboard_set(self, text):
        data = (text + "\0").encode("utf-16-le")
        for _ in range(10):
            if self.u.OpenClipboard(None):
                break
            time.sleep(0.02)
        else:
            raise ControlError("the clipboard is busy")
        try:
            self.u.EmptyClipboard()
            h = self.k.GlobalAlloc(0x0002, len(data))              # GMEM_MOVEABLE
            p = self.k.GlobalLock(h)
            ctypes.memmove(p, data, len(data))
            self.k.GlobalUnlock(h)
            if not self.u.SetClipboardData(13, h):
                raise ControlError("could not set the clipboard")
        finally:
            self.u.CloseClipboard()

    # screen
    def cursor(self):
        pt = self.w.POINT()
        self.u.GetCursorPos(ctypes.byref(pt))
        return pt.x, pt.y

    def screen_size(self):
        return self.u.GetSystemMetrics(0), self.u.GetSystemMetrics(1)

    def screenshot(self):
        w, h = self.screen_size()
        hdc = self.u.GetDC(0)
        mem = self.g.CreateCompatibleDC(hdc)
        bmp = self.g.CreateCompatibleBitmap(hdc, w, h)
        old = self.g.SelectObject(mem, bmp)
        try:
            self.g.BitBlt(mem, 0, 0, w, h, hdc, 0, 0, 0x00CC0020 | 0x40000000)     # SRCCOPY | CAPTUREBLT
            bi = _BITMAPINFOHEADER(ctypes.sizeof(_BITMAPINFOHEADER), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
            buf = ctypes.create_string_buffer(w * h * 4)
            if not self.g.GetDIBits(mem, bmp, 0, h, buf, ctypes.byref(bi), 0):
                raise ControlError("could not read the screen")
            return w, h, bytearray(buf.raw)
        finally:
            self.g.SelectObject(mem, old)
            self.g.DeleteObject(bmp)
            self.g.DeleteDC(mem)
            self.u.ReleaseDC(0, hdc)


if IS_WINDOWS:
    from ctypes import wintypes as _wt

    class _MOUSEINPUT(ctypes.Structure):
        _fields_ = [("dx", _wt.LONG), ("dy", _wt.LONG), ("mouseData", _wt.DWORD), ("dwFlags", _wt.DWORD), ("time", _wt.DWORD), ("dwExtraInfo", ctypes.c_size_t)]

    class _KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", _wt.WORD), ("wScan", _wt.WORD), ("dwFlags", _wt.DWORD), ("time", _wt.DWORD), ("dwExtraInfo", ctypes.c_size_t)]

    class _HARDWAREINPUT(ctypes.Structure):
        _fields_ = [("uMsg", _wt.DWORD), ("wParamL", _wt.WORD), ("wParamH", _wt.WORD)]

    class _IU(ctypes.Union):
        _fields_ = [("mi", _MOUSEINPUT), ("ki", _KEYBDINPUT), ("hi", _HARDWAREINPUT)]

    class _INPUT(ctypes.Structure):
        _fields_ = [("type", _wt.DWORD), ("u", _IU)]

    class _BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", _wt.DWORD), ("biWidth", _wt.LONG), ("biHeight", _wt.LONG), ("biPlanes", _wt.WORD), ("biBitCount", _wt.WORD), ("biCompression", _wt.DWORD),
                    ("biSizeImage", _wt.DWORD), ("biXPelsPerMeter", _wt.LONG), ("biYPelsPerMeter", _wt.LONG), ("biClrUsed", _wt.DWORD), ("biClrImportant", _wt.DWORD)]

    def _kb(vk, scan, flags):
        return _INPUT(1, _IU(ki=_KEYBDINPUT(vk, scan, flags, 0, 0)))

    def _ms(flags, data=0):
        return _INPUT(0, _IU(mi=_MOUSEINPUT(0, 0, data & 0xFFFFFFFF, flags, 0, 0)))


def default_backend():
    """The real backend for this machine, or None where there is none (the tools then say so)."""
    if IS_WINDOWS:
        try:
            return WindowsBackend()
        except Exception:
            return None
    return None


# -- the controller -----------------------------------------------------------------------------------------------------------------------------
class Controller:
    def __init__(self, backend=None, workspace=None, should_stop=None, sleep=time.sleep, pace=0.05):
        self.backend = backend
        self.ws = workspace
        self.should_stop = should_stop or (lambda: False)
        self.sleep, self.pace = sleep, pace
        self.halted = False

    @property
    def available(self):
        return self.backend is not None

    def reset(self):
        self.halted = False

    # safety
    def _need(self):
        if self.backend is None:
            raise ControlError("desktop control is not available on this computer (it needs Windows)")

    def _failsafe(self):
        if self.halted:
            raise ControlError("desktop control was halted by the failsafe; start a new goal to continue")
        try:
            x, y = self.backend.cursor()
        except Exception:
            return
        if x <= 1 and y <= 1:
            self.halted = True
            raise ControlError("failsafe: the mouse is in the top-left corner, desktop control stopped")
        if self.should_stop():
            raise ControlError("stopped")

    def _front(self):
        try:
            return self.backend.foreground() or ""
        except Exception:
            return ""

    def _typing_target_ok(self):
        t = self._front()
        if TERMINAL_TITLE.search(t):
            raise ControlError(f"refused: the active window is a terminal or Run dialog ({t!r}). Typing there would bypass the command Guard; use shell.run")
        if SENSITIVE_TITLE.search(t):
            raise ControlError(f"refused: the active window looks like a password, credential or security prompt ({t!r})")
        return t

    def _act(self):
        self._need()
        self._failsafe()
        self.sleep(self.pace)

    # tools
    def windows(self):
        self._need()
        return [{"title": w["title"][:120], "active": bool(w["active"])} for w in self.backend.windows()][:40]

    def active(self):
        self._need()
        return self._front()

    def focus(self, title):
        self._act()
        title = self._text(title, "title", 200)
        got = self.backend.focus(title)
        return {"active": got}

    def close(self, title):
        self._act()
        title = self._text(title, "title", 200)
        if TERMINAL_TITLE.search(title) or SENSITIVE_TITLE.search(title):
            raise ControlError(f"refused: will not close {title!r}")
        return {"asked_to_close": self.backend.close(title)}

    def type_text(self, text):
        self._act()
        if not isinstance(text, str) or not text:
            raise ControlError("desktop.type needs text")
        if len(text) > MAX_TYPE:
            raise ControlError(f"too much text to type ({len(text)} > {MAX_TYPE}); put it on the clipboard and paste")
        target = self._typing_target_ok()
        for i in range(0, len(text), CHUNK):
            self._failsafe()
            self._typing_target_ok()                                # focus could have moved to a terminal mid-way
            self.backend.type_text(text[i:i + CHUNK])
        return {"typed": len(text), "into": target}

    def key(self, spec):
        self._act()
        c = chord(spec)
        if c in BLOCKED_KEYS:
            raise ControlError(f"refused: {c} (it opens a window that can run anything, bypassing the Guard)")
        target = self._typing_target_ok()
        mods, key = parse_keys(spec)
        self.backend.key(mods, key)
        return {"pressed": c, "into": target}

    def click(self, x, y, button="left", double=False):
        self._act()
        w, h = self.backend.screen_size()
        try:
            x, y = int(x), int(y)
        except (TypeError, ValueError):
            raise ControlError("desktop.click needs numeric x and y")
        if button not in ("left", "right", "middle"):
            raise ControlError("button must be left, right or middle")
        if not (0 <= x < w and 0 <= y < h):
            raise ControlError(f"({x}, {y}) is off the screen ({w}x{h})")
        if x <= 2 and y <= 2:
            raise ControlError("the top-left corner is the failsafe; click elsewhere")
        self.backend.click(x, y, button, bool(double))
        return {"clicked": [x, y], "button": button, "double": bool(double), "window": self._front()}

    def scroll(self, amount):
        self._act()
        try:
            n = max(-50, min(50, int(amount)))
        except (TypeError, ValueError):
            raise ControlError("desktop.scroll needs a whole number (positive = up)")
        self.backend.scroll(n)
        return {"scrolled": n}

    def clipboard(self, op, text=None):
        self._need()
        if op == "get":
            return {"text": self.backend.clipboard_get()[:2000]}
        if op == "set":
            if not isinstance(text, str) or len(text) > 100000:
                raise ControlError("clipboard set needs text (up to 100000 characters)")
            self.backend.clipboard_set(text)
            return {"set": len(text)}
        raise ControlError("clipboard op must be get or set")

    def screenshot(self, name="screenshot.png"):
        self._need()
        if self.ws is None:
            raise ControlError("no workspace to save the screenshot in")
        name = str(name or "screenshot.png")
        if not name.lower().endswith(".png"):
            name += ".png"
        path = self.ws.resolve(name)                                # raises when outside the workspace
        w, h, bgra = self.backend.screenshot()
        png = encode_png(w, h, bgra)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(png)
        return {"saved": name, "width": w, "height": h, "bytes": len(png)}

    def wait(self, seconds):
        try:
            s = max(0.0, min(10.0, float(seconds)))
        except (TypeError, ValueError):
            raise ControlError("desktop.wait needs a number of seconds")
        end = time.monotonic() + s
        while time.monotonic() < end:
            if self.should_stop():
                raise ControlError("stopped")
            self.sleep(min(0.1, max(0.0, end - time.monotonic())))
        return {"waited": s}

    @staticmethod
    def _text(v, what, limit):
        if not isinstance(v, str) or not v.strip():
            raise ControlError(f"{what} is required")
        return v.strip()[:limit]

    # checks used by verifiers
    def window_exists(self, title):
        self._need()
        want = str(title).lower()
        return any(want in w["title"].lower() for w in self.backend.windows())

    def window_active(self, title):
        self._need()
        return str(title).lower() in self._front().lower()

    def clipboard_text(self):
        self._need()
        return self.backend.clipboard_get()

    def describe(self):
        """The paragraph the planner is given."""
        if not self.available:
            return "Desktop control (windows, keyboard, mouse, clipboard, screenshots) is NOT available on this computer; do not plan desktop.* steps other than desktop.open."
        return (
            "You can control the desktop: desktop.windows{} (list open windows), desktop.focus{title} (bring a window to the front by part of its title), "
            "desktop.type{text}, desktop.key{keys} (e.g. 'ctrl+s', 'enter', 'alt+tab'), desktop.click{x,y,button?,double?}, desktop.scroll{amount}, "
            "desktop.clipboard{op:'get'|'set',text?}, desktop.screenshot{name?} (a PNG in the workspace), desktop.close{title} (asks politely), desktop.wait{seconds}. "
            "Open programs with desktop.open, then desktop.focus the window before typing or pressing keys. Prefer keyboard shortcuts to clicking at coordinates. "
            "Verify with window_exists{title}, window_active{title} or clipboard_contains{text}; a screenshot is not proof of anything. "
            "Typing into a terminal, the Run dialog or a password prompt is refused: use shell.run for commands. Win+R, Ctrl+Alt+Del and Win+L are refused. "
            "The user can stop at any time (Esc, or the mouse in the top-left corner).")


def selftest(workspace_root):
    """`python -m praxis control selftest`: a SAFE check of every primitive on this machine (it never types, clicks or presses a key).
    Lists windows, reads the cursor and screen size, round-trips the clipboard (and puts back what was there), and saves a screenshot."""
    from .tools import Workspace
    backend = default_backend()
    if backend is None:
        print("desktop control: NOT available here (it needs Windows).")
        return 1
    c = Controller(backend, Workspace(workspace_root))
    bad = 0

    def step(name, fn):
        nonlocal bad
        try:
            print(f"  ok    {name}: {fn()}")
        except Exception as e:
            bad += 1
            print(f"  FAIL  {name}: {type(e).__name__}: {e}")
    print("desktop control self-test (nothing is typed or clicked)")
    step("windows", lambda: f"{len(c.windows())} open, active = {c.active()!r}")
    step("screen + cursor", lambda: f"{backend.screen_size()} cursor {backend.cursor()}")

    def clip():
        old = backend.clipboard_get()
        try:
            backend.clipboard_set("praxis-selftest-\u00e9\u4e2d")
            ok = backend.clipboard_get() == "praxis-selftest-\u00e9\u4e2d"
        finally:
            backend.clipboard_set(old)
        if not ok:
            raise ControlError("clipboard did not round-trip")
        return "round-trip ok (your clipboard was restored)"
    step("clipboard", clip)
    step("screenshot", lambda: c.screenshot("praxis-selftest.png"))
    print("all primitives work" if not bad else f"{bad} check(s) failed: paste this output back so it can be fixed")
    return 1 if bad else 0
