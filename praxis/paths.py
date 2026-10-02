"""Where PRAXIS keeps user-level state (settings, keys, config). Override with PRAXIS_HOME."""
import os


def home():
    return os.environ.get("PRAXIS_HOME") or os.path.join(os.path.expanduser("~"), ".praxis")
