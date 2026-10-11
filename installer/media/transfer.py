"""
`vulcan media import`: carry out a plan. Each video is rsync'd to
<dest>.vulcan-partial (resumable), verified, then renamed into place, so the
library never holds a half-written file. Existing library files are never
overwritten; --move deletes a source only after its copy verified.
"""

import hashlib
import shutil
import subprocess
from pathlib import Path

CHUNK = 8 * 1024 * 1024


def _digest(path, full):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        if full:
            for block in iter(lambda: f.read(1024 * 1024), b""):
                h.update(block)
        else:
            h.update(f.read(CHUNK))
            size = Path(path).stat().st_size
            if size > CHUNK:
                f.seek(max(CHUNK, size - CHUNK))
                h.update(f.read(CHUNK))
    return h.hexdigest()


def verify_copy(src, dst, mode="quick"):
    src, dst = Path(src), Path(dst)
    if not dst.exists() or src.stat().st_size != dst.stat().st_size:
        return False
    return _digest(src, mode == "full") == _digest(dst, mode == "full")


def _free(path):
    path = Path(path)
    while not path.exists():
        path = path.parent
    return shutil.disk_usage(path).free


def import_plan(plan, *, move=False, verify="quick", include_review=False, save=None, on_row=None, run=subprocess.run):
    result = {"imported": [], "failed": [], "skipped": [], "stopped": None}
    wanted = {"import", "review"} if include_review else {"import"}

    for row in plan["rows"]:
        if row.get("action") not in wanted or row.get("done") or not row.get("destination"):
            continue
        src, dest = Path(row["source"]), Path(row["destination"])

        if dest.exists():
            row["result"] = "skip:conflict"
            result["skipped"].append(row)
        elif not src.exists():
            row["result"] = "failed: source missing"
            result["failed"].append(row)
        elif _free(dest.parent) < row["size"]:
            result["stopped"] = f"destination full before {src.name}"
            break
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            partial = dest.with_name(dest.name + ".vulcan-partial")
            copied = run(["rsync", "--partial", "--append-verify", "--preallocate", str(src), str(partial)],
                         capture_output=True, text=True)
            if copied.returncode != 0:
                row["result"] = f"failed: rsync exit {copied.returncode}: {(copied.stderr or '').strip()[:120]}"
                result["failed"].append(row)
            elif not verify_copy(src, partial, verify):
                partial.unlink(missing_ok=True)
                row["result"] = "failed: copy did not verify"
                result["failed"].append(row)
            else:
                partial.rename(dest)
                for sidecar in row.get("sidecars", []):
                    target = dest.parent / Path(sidecar).name
                    if Path(sidecar).exists() and not target.exists():
                        shutil.copy2(sidecar, target)
                if move:
                    src.unlink()
                    for sidecar in row.get("sidecars", []):
                        Path(sidecar).unlink(missing_ok=True)
                row["done"], row["result"] = True, "imported"
                result["imported"].append(row)

        if save:
            save(plan)
        if on_row:
            on_row(row)

    return result
