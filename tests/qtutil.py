"""Deterministic clean-up of Qt widgets in tests.

A widget (and its QTimer) that is only garbage collected can be finalised by the collector running on a WORKER thread (a voice or
executor thread that happens to allocate), and Qt then aborts with "Timers cannot be stopped from another thread" and a segfault.
Found when the whole suite ran together. Every test widget is stopped, closed and deleted on the main thread."""
import gc


def dispose(w):
    try:
        from PySide6.QtCore import QEvent
        from PySide6.QtWidgets import QApplication
        from praxis.desktop.qt.core import CoreView
        cores = ([w] if isinstance(w, CoreView) else []) + w.findChildren(CoreView)
        for c in cores:
            c.timer.stop()
        if hasattr(w, "timer"):
            w.timer.stop()
        w.close()
        w.deleteLater()
        app = QApplication.instance()
        if app is not None:
            app.sendPostedEvents(None, QEvent.DeferredDelete)
    finally:
        gc.collect()
