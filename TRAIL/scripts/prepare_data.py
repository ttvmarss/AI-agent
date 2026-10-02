"""Thin wrapper: same as `trail data prepare` (extra arguments are passed through)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from trail.cli import main

if __name__ == "__main__":
    sys.exit(main("data prepare".split() + sys.argv[1:]))
