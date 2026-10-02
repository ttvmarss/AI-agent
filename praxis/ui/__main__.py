"""python -m praxis.ui [folder]   open the PRAXIS interface (what `praxis` / the desktop shortcut runs)
   --no-window                    start the engine and the local server only, and print the address
   --qt                           the older Qt window instead (needs PySide6)"""
import os
import sys


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--qt" in argv:
        from ..desktop.__main__ import main as qt_main
        return qt_main([a for a in argv if a != "--qt"])
    show = "--no-window" not in argv
    argv = [a for a in argv if a != "--no-window"]
    from . import app
    existing = app.running_instance() if show else None
    if existing:                                    # PRAXIS is already running for this user: just open another window on it
        from . import window
        window.open_window(existing)
        return 0
    from ..desktop.controller import Controller
    from ..desktop.settings import Settings
    ws = argv[0] if argv else (Settings().last_workspace or os.path.join(os.path.expanduser("~"), "PRAXIS", "workspace"))
    os.makedirs(ws, exist_ok=True)
    ctl = Controller(ws)
    ctl.start()
    return app.run(ctl, show=show)


if __name__ == "__main__":
    sys.exit(main())
