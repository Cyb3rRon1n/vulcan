"""
Updates Vulcan itself (this checked-out repo), not a generated stack -
a real, previously-missing Main Menu item found while researching
DockSTARTer's own persistent-hub behavior (its "Update DockSTARTer"
item has no Vulcan equivalent before this). A plain `git pull
--ff-only`, never a force/reset - if the local checkout has diverged
or has uncommitted changes conflicting with upstream, this refuses
cleanly and reports why, the same "never invent history, only
fast-forward" discipline this project already applies to every other
destructive-adjacent action.
"""

import subprocess
import sys
from pathlib import Path


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess:

    return subprocess.run(args, cwd=cwd, capture_output=True, text=True)


def update_vulcan_self(repo_dir: Path = Path(".")) -> dict:

    is_repo = _run(["git", "rev-parse", "--is-inside-work-tree"], repo_dir)

    if is_repo.returncode != 0:
        return {
            "success": False,
            "error": "This doesn't look like a git checkout of Vulcan - can't self-update.",
            "updated": False
        }

    fetch = _run(["git", "fetch", "origin", "main"], repo_dir)

    if fetch.returncode != 0:
        return {
            "success": False,
            "error": f"Failed to check for updates: {fetch.stderr.strip()}",
            "updated": False
        }

    old_commit = _run(["git", "rev-parse", "--short", "HEAD"], repo_dir).stdout.strip()

    behind = _run(["git", "rev-list", "HEAD..origin/main", "--count"], repo_dir)

    if behind.stdout.strip() == "0":
        return {"success": True, "error": None, "updated": False, "commit": old_commit}

    pull = _run(["git", "pull", "--ff-only", "origin", "main"], repo_dir)

    if pull.returncode != 0:

        return {
            "success": False,
            "error": (
                "Failed to update - your local checkout may have diverged from origin/main "
                f"(uncommitted changes or local commits). Resolve manually: {pull.stderr.strip()}"
            ),
            "updated": False
        }

    # Matches ./install's own real bootstrap command exactly (plain
    # `pip install -e .`, no [dev] extras) - this runs for real end
    # users, not developers, so it shouldn't pull in test-only deps
    # the bootstrap itself never installs.
    pip_install = subprocess.run(
        [sys.executable, "-m", "pip", "install", "--quiet", "-e", str(repo_dir)],
        capture_output=True, text=True
    )

    if pip_install.returncode != 0:

        return {
            "success": False,
            "error": (
                "Code updated, but reinstalling dependencies failed - run `pip install -e .` "
                f"manually: {pip_install.stderr.strip()[-500:]}"
            ),
            "updated": False
        }

    new_commit = _run(["git", "rev-parse", "--short", "HEAD"], repo_dir).stdout.strip()

    return {
        "success": True,
        "error": None,
        "updated": True,
        "old_commit": old_commit,
        "new_commit": new_commit
    }
