import subprocess
import os

def _get_app_version():
    try:
        with open(os.path.join(os.path.dirname(__file__), "..", "VERSION"), "r") as f:
            hc = f.read().strip()
    except Exception:
        hc = "0.1"

    releases_count = "0"
    commits_count = "0"

    try:
        releases = subprocess.check_output(["gh", "release", "list"], stderr=subprocess.DEVNULL).decode().strip().split("\n")
        count = len([r for r in releases if r.strip()])
        releases_count = str(count)
    except Exception:
        pass

    try:
        commits_count = subprocess.check_output(["git", "rev-list", "--count", "HEAD"], stderr=subprocess.DEVNULL).decode().strip()
    except Exception:
        pass

    return f"v{hc}.{releases_count}.{commits_count}"

print(_get_app_version())
