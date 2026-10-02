"""Approval and key dialogs. The approval dialog shows the EXACT action and defaults to Deny."""
import webbrowser

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QVBoxLayout)

from ..approvals import LEGEND, describe
from .theme import C, fonts


class ApprovalDialog(QDialog):
    def __init__(self, parent, req):
        super().__init__(parent)
        self.req, self.answer = req, False
        title, tone, meaning = LEGEND.get(req.cls, (f"CLASS {req.cls}", "warn", ""))
        self.setWindowTitle("PRAXIS needs your approval")
        self.setModal(True)
        self.setMinimumWidth(640)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 22)
        bar = QFrame(); bar.setFixedHeight(6); bar.setStyleSheet(f"background: {C[tone]}; border: none;")
        lay.addWidget(bar)
        body = QVBoxLayout(); body.setContentsMargins(26, 18, 26, 0); body.setSpacing(10)
        lay.addLayout(body)
        h = QLabel(f"Class {req.cls}   -   {title}"); h.setObjectName("h1"); body.addWidget(h)
        m = QLabel(meaning); m.setObjectName("muted"); m.setWordWrap(True); body.addWidget(m)
        box = QPlainTextEdit(describe(req)); box.setObjectName("mono"); box.setReadOnly(True); box.setFixedHeight(190)
        body.addWidget(box)
        why = QLabel(f"Why you are being asked: {req.reason}"); why.setObjectName("muted"); why.setWordWrap(True)
        body.addWidget(why)
        row = QHBoxLayout(); row.addStretch()
        self.deny_btn = QPushButton("Deny   (Esc)"); self.deny_btn.setObjectName("danger")
        self.ok_btn = QPushButton("Approve"); self.ok_btn.setObjectName("primary")
        row.addWidget(self.deny_btn); row.addWidget(self.ok_btn); body.addLayout(row)
        self.deny_btn.clicked.connect(self.reject)
        self.ok_btn.clicked.connect(self._approve)
        self.deny_btn.setDefault(True); self.deny_btn.setFocus()      # the safe choice holds the keyboard focus

    def _approve(self):
        self.answer = True
        self.accept()

    def reject(self):   # Esc, the title-bar X, Alt+F4: all refusals
        self.answer = False
        super().reject()


class KeyDialog(QDialog):
    def __init__(self, parent, preset, existing=False):
        super().__init__(parent)
        self.preset, self.value = preset, ""
        self.setWindowTitle(f"{preset.label}: API key")
        self.setModal(True)
        self.setMinimumWidth(560)
        lay = QVBoxLayout(self); lay.setContentsMargins(26, 22, 26, 22); lay.setSpacing(10)
        h = QLabel(preset.label); h.setObjectName("h1"); lay.addWidget(h)
        trust = ("TRUSTED: its documented terms say your API data is not used for training."
                 if preset.privacy == "cloud" else
                 "OPEN: the free tier may log, train on, or have humans read prompts. PRAXIS only uses it for goals you mark "
                 "Open, and never when a credential is detected in the prompt.")
        t = QLabel(trust); t.setWordWrap(True); t.setStyleSheet(f"color: {C['ok'] if preset.privacy == 'cloud' else C['warn']};")
        lay.addWidget(t)
        c = QLabel(preset.caveat); c.setObjectName("muted"); c.setWordWrap(True); lay.addWidget(c)
        self.edit = QLineEdit(); self.edit.setEchoMode(QLineEdit.Password)
        self.edit.setPlaceholderText("paste the key here (stored only in your private key file)")
        lay.addWidget(self.edit)
        row = QHBoxLayout()
        get = QPushButton("Get a free key"); get.setObjectName("ghost")
        get.clicked.connect(lambda: webbrowser.open(preset.signup_url))
        row.addWidget(get); row.addStretch()
        cancel = QPushButton("Cancel"); cancel.setObjectName("ghost"); cancel.clicked.connect(self.reject)
        save = QPushButton("Save key"); save.setObjectName("primary"); save.clicked.connect(self._save)
        row.addWidget(cancel); row.addWidget(save); lay.addLayout(row)

    def _save(self):
        v = self.edit.text().strip()
        if len(v) >= 8:
            self.value = v
            self.accept()
