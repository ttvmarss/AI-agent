"""Launch the desktop app:  python -m praxis.desktop [workspace]
   (the web interface by default; --qt the older Qt window, --tk the simple Tk shell)"""
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
    if "--qt" not in argv and "--tk" not in argv:           # the interface is the web UI (TypeScript + WebGL) unless an older window is asked for by name
        from ..ui.__main__ import main as web_main
        return web_main([a for a in argv if a != "--web"])
    argv = [a for a in argv if a != "--qt"]
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
            msg = ("PRAXIS opened its BASIC window because the command-center UI (PySide6) is not installed for this Python.\n\n"
                   "To get the reactor screen, open a terminal and run:\n    py -3 -m pip install --user PySide6-Essentials\n\n"
                   "(or double-click windows\\Update-PRAXIS.bat, which does it for you).")
            print(msg)
            try:                                  # pyw hides the console, so a message box is the only way anyone sees this
                import tkinter
                from tkinter import messagebox
                r = tkinter.Tk(); r.withdraw(); messagebox.showwarning("PRAXIS: basic window", msg); r.destroy()
            except Exception:
                pass
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
