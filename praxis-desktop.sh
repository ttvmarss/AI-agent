#!/bin/sh
# Start the PRAXIS desktop app on Linux/macOS (needs Python 3.11+ with Tk: sudo apt install python3-tk)
cd "$(dirname "$0")" || exit 1
exec python3 -m praxis.desktop "$@"
