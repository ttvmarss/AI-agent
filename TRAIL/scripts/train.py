"""Thin wrapper: same as `trail train` (extra arguments are passed through)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from trail.cli import main

if __name__ == "__main__":
    sys.exit(main("train".split() + sys.argv[1:]))
