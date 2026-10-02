#!/bin/sh
# Start the PRAXIS desktop app on Linux/macOS. Full UI: pip install PySide6-Essentials. Fallback window: sudo apt install python3-tk
cd "$(dirname "$0")" || exit 1
exec python3 -m praxis.desktop "$@"
