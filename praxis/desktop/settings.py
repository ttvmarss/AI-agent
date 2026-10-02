"""Tiny persisted UI settings (recent workspaces, window geometry). Corrupt files never crash the app."""
import json
import os


def default_home():
    return os.environ.get("PRAXIS_HOME") or os.path.join(os.path.expanduser("~"), ".praxis")


class Settings:
    MAX_RECENT = 8

    def __init__(self, home=None):
        self.home = home or default_home()
        self.path = os.path.join(self.home, "desktop.json")
        self.recent, self.geometry = [], ""
        try:
            with open(self.path) as f:
                d = json.load(f)
            self.recent = [x for x in d.get("recent", []) if isinstance(x, str)][:self.MAX_RECENT]
            self.geometry = d.get("geometry", "") if isinstance(d.get("geometry"), str) else ""
        except (OSError, ValueError, AttributeError):
            pass

    def add_recent(self, path):
        self.recent = ([path] + [p for p in self.recent if p != path])[:self.MAX_RECENT]

    @property
    def last_workspace(self):
        return self.recent[0] if self.recent else None

    def save(self):
        try:
            os.makedirs(self.home, exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w") as f:
                json.dump({"recent": self.recent, "geometry": self.geometry}, f)
            os.replace(tmp, self.path)
        except OSError:
            pass
