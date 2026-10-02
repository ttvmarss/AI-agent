"""Launch the desktop app:  python -m praxis.desktop [workspace]   (--tk forces the simple Tk shell)"""
import os
import sys


def _qt_available():
    try:
        import PySide6.QtWidgets  # noqa: F401
        return True
    except ImportError:
        return False


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    force_tk = "--tk" in argv
    argv = [a for a in argv if a != "--tk"]
    use_qt = not force_tk and _qt_available()
    if not use_qt:
        try:
            import tkinter  # noqa: F401
        except ImportError:
            print("PRAXIS needs a GUI toolkit. Run:  pip install PySide6-Essentials   (recommended)\n"
                  "or on Linux:  sudo apt install python3-tk")
            return 1
        if not force_tk:
            print("Using the basic Tk window. For the full command center:  pip install PySide6-Essentials")
    from .controller import Controller
    from .settings import Settings
    from .telemetry import Telemetry
    ws = argv[0] if argv else (Settings().last_workspace or os.path.join(os.path.expanduser("~"), "PRAXIS", "workspace"))
    os.makedirs(ws, exist_ok=True)
    ctl = Controller(ws)
    ctl.start()
    if use_qt:
        from .qt.app import run
        return run(ctl, Telemetry())
    from .app import App
    app = App(ctl, Telemetry())
    app.root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
