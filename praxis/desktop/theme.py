"""Dark theme + fonts for the desktop app (ttk 'clam' base, stdlib only)."""
import sys
import tkinter as tk
import tkinter.font as tkfont
import tkinter.ttk as ttk

COL = dict(bg0="#0a0e13", bg1="#10161d", bg2="#18212b", bg3="#212c38", line="#263446",
           text="#d8e3f0", muted="#7f93aa", accent="#38d1f2", accent_dim="#1b6a7c",
           ok="#37d998", warn="#f4b53c", bad="#ff5c6c", info="#8fa8cc", select="#16384a")

STATE_COLOR = {"IDLE": "muted", "STARTING": "muted", "PLANNING": "accent", "RUNNING": "accent",
               "WAITING FOR YOU": "warn", "VERIFIED": "ok", "UNVERIFIED": "warn", "FAILED": "bad",
               "CANCELLED": "warn", "STOPPING": "warn", "ERROR": "bad"}


def pick_font(root, candidates, default):
    have = set(tkfont.families(root))
    return next((c for c in candidates if c in have), default)


def setup(root):
    """Configure ttk styles; returns the font names to use."""
    ui = pick_font(root, ["Segoe UI", "SF Pro Text", "Inter", "Ubuntu", "DejaVu Sans"], "TkDefaultFont")
    mono = pick_font(root, ["Cascadia Mono", "Consolas", "SF Mono", "Menlo", "DejaVu Sans Mono"], "TkFixedFont")
    fonts = {"ui": (ui, 10), "ui_b": (ui, 10, "bold"), "small": (ui, 9), "title": (ui, 15, "bold"),
             "big": (ui, 20, "bold"), "mono": (mono, 10), "mono_s": (mono, 9)}
    root.configure(bg=COL["bg0"])
    st = ttk.Style(root)
    st.theme_use("clam")
    st.configure(".", background=COL["bg1"], foreground=COL["text"], fieldbackground=COL["bg2"],
                 bordercolor=COL["line"], lightcolor=COL["line"], darkcolor=COL["line"],
                 troughcolor=COL["bg2"], font=fonts["ui"], focuscolor=COL["accent_dim"])
    st.configure("TFrame", background=COL["bg1"])
    st.configure("Card.TFrame", background=COL["bg2"])
    st.configure("TLabel", background=COL["bg1"], foreground=COL["text"])
    st.configure("Muted.TLabel", foreground=COL["muted"])
    st.configure("Card.TLabel", background=COL["bg2"])
    st.configure("Title.TLabel", font=fonts["title"])
    st.configure("TCheckbutton", background=COL["bg1"], foreground=COL["text"], indicatorcolor=COL["bg3"])
    st.map("TCheckbutton", indicatorcolor=[("selected", COL["accent"])], background=[("active", COL["bg1"])])
    st.configure("TEntry", fieldbackground=COL["bg2"], foreground=COL["text"], insertcolor=COL["text"])
    for name, bg, fg, active in (("TButton", COL["bg3"], COL["text"], COL["line"]),
                                 ("Accent.TButton", COL["accent"], "#04222b", "#6fe3fa"),
                                 ("Danger.TButton", COL["bad"], "#2a0509", "#ff8c97"),
                                 ("Ghost.TButton", COL["bg1"], COL["muted"], COL["bg3"])):
        st.configure(name, background=bg, foreground=fg, borderwidth=0, padding=(14, 7), font=fonts["ui_b"], relief="flat")
        st.map(name, background=[("active", active), ("disabled", COL["bg2"])],
               foreground=[("disabled", COL["muted"])])
    st.configure("Treeview", background=COL["bg2"], fieldbackground=COL["bg2"], foreground=COL["text"],
                 rowheight=26, borderwidth=0, font=fonts["ui"])
    st.map("Treeview", background=[("selected", COL["select"])], foreground=[("selected", COL["text"])])
    st.configure("Treeview.Heading", background=COL["bg3"], foreground=COL["muted"], relief="flat",
                 font=fonts["small"], padding=(8, 6))
    st.map("Treeview.Heading", background=[("active", COL["line"])])
    st.configure("Vertical.TScrollbar", background=COL["bg3"], troughcolor=COL["bg1"], arrowcolor=COL["muted"],
                 borderwidth=0)
    st.configure("TPanedwindow", background=COL["bg0"])
    st.configure("Horizontal.TProgressbar", background=COL["accent"], troughcolor=COL["bg2"], borderwidth=0)
    return fonts


def dpi_awareness():
    """Crisp text on Windows high-DPI displays (must run before the first Tk window)."""
    if sys.platform.startswith("win"):
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
