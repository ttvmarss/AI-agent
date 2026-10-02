"""Launch the desktop app:  python -m praxis.desktop [workspace]"""
import os
import sys


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    try:
        import tkinter  # noqa: F401
    except ImportError:
        print("PRAXIS needs Tk. On Windows/macOS install Python from python.org (Tk is included); "
              "on Linux: sudo apt install python3-tk")
        return 1
    from .app import App
    from .controller import Controller
    from .settings import Settings
    from .telemetry import Telemetry
    ws = argv[0] if argv else (Settings().last_workspace or os.path.join(os.path.expanduser("~"), "PRAXIS", "workspace"))
    os.makedirs(ws, exist_ok=True)
    ctl = Controller(ws)
    ctl.start()
    app = App(ctl, Telemetry())
    app.root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
