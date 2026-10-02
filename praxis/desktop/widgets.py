"""Small custom widgets. Each one maps to real system state; nothing here is decoration."""
import math
import tkinter as tk
import tkinter.ttk as ttk

from .theme import COL


class Reactor(tk.Canvas):
    """Status ring: rotates ONLY while PRAXIS is working, amber when it needs you, red on error."""
    COLORS = {"idle": "accent_dim", "starting": "muted", "working": "accent", "stopping": "warn",
              "waiting": "warn", "error": "bad", "ok": "ok"}

    def __init__(self, parent, size=44):
        super().__init__(parent, width=size, height=size, bg=COL["bg0"], highlightthickness=0)
        self.size, self.mode, self.angle = size, "starting", 0
        self.draw()

    def set_mode(self, mode):
        if mode != self.mode:
            self.mode = mode
            self.draw()

    def tick(self):
        if self.mode in ("working", "stopping", "starting"):
            self.angle = (self.angle + 14) % 360
            self.draw()
        elif self.mode == "waiting":
            self.angle = (self.angle + 6) % 360
            self.draw()

    def draw(self):
        self.delete("all")
        c, r = self.size / 2, self.size / 2 - 4
        col = COL[self.COLORS.get(self.mode, "accent_dim")]
        self.create_oval(c - r, c - r, c + r, c + r, outline=COL["line"], width=2)
        if self.mode in ("working", "stopping", "starting", "waiting"):
            self.create_arc(c - r, c - r, c + r, c + r, start=self.angle, extent=110, style="arc", outline=col, width=3)
            self.create_arc(c - r, c - r, c + r, c + r, start=self.angle + 180, extent=60, style="arc", outline=col, width=3)
        else:
            self.create_oval(c - r, c - r, c + r, c + r, outline=col, width=3)
        k = r * 0.38
        pulse = 0.9 + 0.1 * math.sin(math.radians(self.angle * 2)) if self.mode == "waiting" else 1.0
        self.create_oval(c - k * pulse, c - k * pulse, c + k * pulse, c + k * pulse, fill=col, outline="")


class Bar(tk.Canvas):
    """Labelled usage bar (CPU, RAM, GPU, VRAM)."""

    def __init__(self, parent, label, width=190, height=30):
        super().__init__(parent, width=width, height=height, bg=COL["bg1"], highlightthickness=0)
        self.label, self.w, self.h = label, width, height
        self.set(0, "-")

    def set(self, pct, text):
        self.text, self.pct = text, pct
        self.delete("all")
        pct = max(0.0, min(100.0, pct))
        self.create_text(0, 8, text=self.label, anchor="w", fill=COL["muted"], font=("TkDefaultFont", 8))
        self.create_text(self.w, 8, text=text, anchor="e", fill=COL["text"], font=("TkDefaultFont", 8))
        self.create_rectangle(0, 18, self.w, 25, fill=COL["bg2"], outline="")
        color = COL["bad"] if pct > 90 else COL["warn"] if pct > 75 else COL["accent"]
        if pct > 0:
            self.create_rectangle(0, 18, self.w * pct / 100.0, 25, fill=color, outline="")


class NavItem(tk.Label):
    def __init__(self, parent, text, command, fonts):
        super().__init__(parent, text=text, anchor="w", padx=16, pady=9, bg=COL["bg1"], fg=COL["muted"],
                         font=fonts["ui_b"], cursor="hand2")
        self.command, self.active = command, False
        self.bind("<Button-1>", lambda e: command())
        self.bind("<Enter>", lambda e: self._paint(True))
        self.bind("<Leave>", lambda e: self._paint(False))

    def set_active(self, on):
        self.active = on
        self._paint(False)

    def _paint(self, hover):
        if self.active:
            self.configure(bg=COL["select"], fg=COL["accent"])
        else:
            self.configure(bg=COL["bg2"] if hover else COL["bg1"], fg=COL["text"] if hover else COL["muted"])


class LogText(tk.Text):
    """Read-only coloured text (activity feed, reports)."""

    def __init__(self, parent, fonts, **kw):
        super().__init__(parent, bg=COL["bg2"], fg=COL["text"], insertbackground=COL["text"], relief="flat",
                         wrap="word", font=fonts["mono_s"], padx=10, pady=8, borderwidth=0, state="disabled",
                         highlightthickness=0, **kw)
        for tag, key in (("ok", "ok"), ("warn", "warn"), ("bad", "bad"), ("info", "info"), ("muted", "muted")):
            self.tag_configure(tag, foreground=COL[key])
        self.tag_configure("bold", font=fonts["mono_s"] + ("bold",))

    def append(self, text, tag="info"):
        self.configure(state="normal")
        self.insert("end", text + "\n", tag)
        self.configure(state="disabled")
        self.see("end")

    def replace(self, text, tag="info"):
        self.configure(state="normal")
        self.delete("1.0", "end")
        self.insert("end", text, tag)
        self.configure(state="disabled")
