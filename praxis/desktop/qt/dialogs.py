"""Approval and key dialogs. The approval dialog shows the EXACT action and defaults to Deny."""
from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QVBoxLayout)

from ..approvals import LEGEND, describe
from .theme import C, fonts


class ApprovalDialog(QDialog):
    def __init__(self, parent, req):
        super().__init__(parent)
        self.req, self.answer, self.answered_elsewhere = req, False, False
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

    def watch(self, is_pending):
        """Close this dialog by itself if the request is answered somewhere else (by voice): it must never sit on screen
        asking a question that was already answered."""
        self.answered_elsewhere = False
        t = QTimer(self); t.timeout.connect(lambda: self._check(is_pending)); t.start(120)
        self._watch = t

    def _check(self, is_pending):
        if not is_pending(self.req.id):
            self.answered_elsewhere = True
            self._watch.stop()
            super().reject()

    def _approve(self):
        self.answer = True
        self.accept()

    def reject(self):   # Esc, the title-bar X, Alt+F4: all refusals
        self.answer = False
        super().reject()
