"""Visual language of the PRAXIS command center. Colors carry meaning; nothing here is ornament."""
from PySide6.QtGui import QColor, QFont, QFontDatabase

C = dict(bg0="#050911", bg1="#0a111b", panel="#0f1823", panel2="#142131", line="#1c2b3d", line2="#27405a",
         text="#dce8f6", muted="#7a8da6", dim="#4b5d74",
         accent="#3fd7ff", accent_dim="#2a8aa6", violet="#9b8cff", ok="#3de3a1", warn="#ffb84a", bad="#ff5d73",
         select="#12354a")

STATE_COLOR = {"IDLE": "accent_dim", "STARTING": "muted", "PLANNING": "accent", "RUNNING": "accent",
               "WAITING FOR YOU": "warn", "VERIFIED": "ok", "UNVERIFIED": "warn", "FAILED": "bad",
               "CANCELLED": "warn", "STOPPING": "warn", "ERROR": "bad", "SETUP NEEDED": "warn"}
STEP_COLOR = {"pending": "dim", "running": "accent", "waiting": "warn", "ran": "info_", "verified": "ok", "denied": "bad",
              "failed": "bad", "rolled back": "warn"}
COST_COLOR = {0: "ok", 1: "accent", 2: "violet"}          # local / free cloud / subscription
COST_NAME = {0: "LOCAL", 1: "FREE", 2: "SUBSCRIPTION"}
PRIVACY_NAME = {"local": "LOCAL", "cloud": "TRUSTED", "open": "OPEN"}


def qc(key, alpha=255):
    c = QColor(C.get(key, key))
    c.setAlpha(alpha)
    return c


def pick(candidates, default):
    have = set(QFontDatabase.families())
    return next((f for f in candidates if f in have), default)


def fonts():
    ui = pick(["Segoe UI Variable Display", "Segoe UI", "Inter", "SF Pro Display", "Roboto", "Ubuntu", "Liberation Sans", "DejaVu Sans"], "Sans Serif")
    mono = pick(["Cascadia Mono", "Consolas", "JetBrains Mono", "SF Mono", "Liberation Mono", "DejaVu Sans Mono"], "Monospace")
    return ui, mono


def qss(ui, mono):
    return f"""
* {{ font-family: "{ui}"; color: {C['text']}; }}
QMainWindow, QDialog {{ background: {C['bg0']}; }}
QToolTip {{ background: {C['panel2']}; color: {C['text']}; border: 1px solid {C['line2']}; padding: 6px; }}
QFrame#card {{ background: rgba(18,30,45,0.80); border: 1px solid rgba(70,115,160,0.30); border-radius: 14px; }}
QFrame#cardflat {{ background: rgba(14,24,36,0.65); border: 1px solid rgba(60,100,140,0.22); border-radius: 12px; }}
QLabel {{ background: transparent; }}
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QLabel#h1 {{ font-size: 22px; font-weight: 600; }}
QLabel#h2 {{ font-size: 13px; font-weight: 600; letter-spacing: 1px; color: {C['muted']}; }}
QLabel#muted {{ color: {C['muted']}; }}
QLabel#chip {{ border-radius: 9px; padding: 2px 9px; font-size: 10px; font-weight: 700; letter-spacing: 1px; }}
QPushButton {{ background: {C['panel2']}; border: 1px solid {C['line2']}; border-radius: 9px; padding: 8px 16px; font-weight: 600; }}
QPushButton:hover {{ background: #1b2d42; border-color: {C['accent_dim']}; }}
QPushButton:disabled {{ color: {C['dim']}; background: {C['panel']}; border-color: {C['line']}; }}
QPushButton#primary {{ background: {C['accent']}; color: #03202a; border: none; }}
QPushButton#primary:hover {{ background: #7ee6ff; }}
QPushButton#primary:disabled {{ background: #1a4655; color: #5c8896; }}
QPushButton#danger {{ background: {C['bad']}; color: #2a0510; border: none; }}
QPushButton#danger:hover {{ background: #ff8b9c; }}
QPushButton#danger:disabled {{ background: #3a1f29; color: #7d4a57; }}
QPushButton#ghost {{ background: transparent; border: 1px solid {C['line']}; color: {C['muted']}; }}
QPushButton#ghost:hover {{ color: {C['text']}; border-color: {C['accent_dim']}; }}
QPlainTextEdit, QTextEdit, QLineEdit {{ background: rgba(8,14,22,0.85); border: 1px solid {C['line']}; border-radius: 10px;
    padding: 8px 10px; selection-background-color: {C['select']}; }}
QPlainTextEdit:focus, QTextEdit:focus, QLineEdit:focus {{ border-color: {C['accent_dim']}; }}
QPlainTextEdit#mono, QTextEdit#mono {{ font-family: "{mono}"; font-size: 12px; }}
QTreeWidget, QTableWidget {{ background: rgba(8,14,22,0.70); border: 1px solid {C['line']}; border-radius: 10px;
    alternate-background-color: rgba(20,32,48,0.5); outline: 0; gridline-color: transparent; }}
QTreeWidget::item, QTableWidget::item {{ padding: 5px 6px; border: none; }}
QTreeWidget::item:selected, QTableWidget::item:selected {{ background: {C['select']}; color: {C['text']}; }}
QHeaderView::section {{ background: {C['panel2']}; color: {C['muted']}; border: none; padding: 7px 8px; font-size: 11px;
    font-weight: 600; letter-spacing: 1px; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {C['line2']}; border-radius: 4px; min-height: 28px; }}
QScrollBar::handle:vertical:hover {{ background: {C['accent_dim']}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar:horizontal {{ height: 10px; background: transparent; }}
QScrollBar::handle:horizontal {{ background: {C['line2']}; border-radius: 4px; }}
QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 5px; border: 1px solid {C['line2']}; background: {C['bg1']}; }}
QCheckBox::indicator:checked {{ background: {C['accent']}; border-color: {C['accent']}; }}
QSplitter::handle {{ background: transparent; }}
QProgressBar {{ background: {C['panel']}; border: none; border-radius: 4px; height: 8px; text-align: center; color: transparent; }}
QProgressBar::chunk {{ background: {C['accent']}; border-radius: 4px; }}
"""
