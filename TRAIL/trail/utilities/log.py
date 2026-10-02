"""One logger setup for the whole project (stderr, timestamps, no silent errors)."""
import logging
import sys

_DONE = False


def get_logger(name="trail"):
    global _DONE
    if not _DONE:
        h = logging.StreamHandler(sys.stderr)
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s", "%H:%M:%S"))
        root = logging.getLogger("trail")
        root.addHandler(h)
        root.setLevel(logging.INFO)
        root.propagate = False
        _DONE = True
    return logging.getLogger(name if name.startswith("trail") else f"trail.{name}")
