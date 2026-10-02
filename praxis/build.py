"""Which build is this? Read straight from the git folder (no git program needed), so the window can say exactly what code it is running."""
import os


def info(root=None):
    """-> (short commit, branch) or ("", "") when this is not a git checkout."""
    root = root or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    try:
        gd = os.path.join(root, ".git")
        if os.path.isfile(gd):                                   # worktrees: ".git" is a file pointing at the real folder
            with open(gd, encoding="utf-8") as f:
                gd = os.path.join(root, f.read().split(":", 1)[1].strip())
        with open(os.path.join(gd, "HEAD"), encoding="utf-8") as f:
            head = f.read().strip()
        if not head.startswith("ref:"):
            return head[:7], "detached"
        ref = head.split(":", 1)[1].strip()
        branch = ref[len("refs/heads/"):] if ref.startswith("refs/heads/") else ref
        p = os.path.join(gd, *ref.split("/"))
        if os.path.isfile(p):
            with open(p, encoding="utf-8") as f:
                return f.read().strip()[:7], branch
        with open(os.path.join(gd, "packed-refs"), encoding="utf-8") as f:
            for line in f:
                if line.strip().endswith(" " + ref):
                    return line.split()[0][:7], branch
    except (OSError, IndexError):
        pass
    return "", ""


def label():
    c, b = info()
    return f"{c} ({b})" if c else "unknown build"
