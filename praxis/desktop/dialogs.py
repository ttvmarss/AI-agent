"""Approval dialog: shows the EXACT action the Guard is asking about (never a model-written summary)."""
import tkinter as tk
import tkinter.ttk as ttk

from .theme import COL

from .approvals import LEGEND, describe  # noqa: F401


class ApprovalDialog(tk.Toplevel):
    def __init__(self, app, req, on_answer):
        super().__init__(app.root)
        self.req, self.on_answer, self.answered = req, on_answer, False
        title, tone, meaning = LEGEND.get(req.cls, (f"CLASS {req.cls}", "warn", ""))
        self.title("PRAXIS needs your approval")
        self.configure(bg=COL["bg0"])
        self.transient(app.root)
        self.resizable(False, False)
        head = tk.Frame(self, bg=COL[tone], height=6)
        head.pack(fill="x")
        body = ttk.Frame(self, padding=22)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text=f"Class {req.cls}  -  {title}", font=app.fonts["title"]).pack(anchor="w")
        ttk.Label(body, text=meaning, style="Muted.TLabel", wraplength=560, justify="left").pack(anchor="w", pady=(2, 12))
        box = tk.Text(body, width=72, height=8, bg=COL["bg2"], fg=COL["text"], relief="flat", wrap="word",
                      font=app.fonts["mono"], padx=12, pady=10, highlightthickness=0)
        box.insert("1.0", describe(req))
        box.configure(state="disabled")
        box.pack(fill="x")
        ttk.Label(body, text=f"Why you are being asked: {req.reason}", style="Muted.TLabel", wraplength=560,
                  justify="left").pack(anchor="w", pady=(10, 14))
        row = ttk.Frame(body)
        row.pack(fill="x")
        self.deny_btn = ttk.Button(row, text="Deny   (Esc)", style="Danger.TButton", command=lambda: self._answer(False))
        self.deny_btn.pack(side="right")
        self.ok_btn = ttk.Button(row, text="Approve", style="Accent.TButton", command=lambda: self._answer(True))
        self.ok_btn.pack(side="right", padx=(0, 10))
        self.bind("<Escape>", lambda e: self._answer(False))
        self.protocol("WM_DELETE_WINDOW", lambda: self._answer(False))  # closing the window is a refusal
        self.update_idletasks()
        x = app.root.winfo_rootx() + (app.root.winfo_width() - self.winfo_width()) // 2
        y = app.root.winfo_rooty() + (app.root.winfo_height() - self.winfo_height()) // 3
        self.geometry(f"+{max(0, x)}+{max(0, y)}")
        self.deny_btn.focus_set()  # the safe choice has the keyboard focus
        try:
            self.grab_set()
        except tk.TclError:
            pass

    def _answer(self, ok):
        if self.answered:
            return
        self.answered = True
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.on_answer(self.req, ok)
        self.destroy()
