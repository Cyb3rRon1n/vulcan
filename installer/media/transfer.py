"""
`vulcan media import`: carry out a plan. Each video is rsync'd to
<dest>.vulcan-partial (resumable), verified, then renamed into place, so the
library never holds a half-written file. Existing library files are never
overwritten; --move deletes a source only after its copy verified.
"""

import errno
import hashlib
import os
import shutil
import subprocess
from pathlib import Path

CHUNK = 8 * 1024 * 1024

# Filesystems with no hard-link support (exFAT, FAT, many CIFS/SMB mounts)
# raise one of these from os.link(); fall back to a plain rename instead.
_NO_HARDLINK_ERRNOS = {errno.EPERM, errno.EOPNOTSUPP, errno.ENOTSUP, errno.EXDEV, errno.EMLINK}


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
        if row.get("action") not in wanted or row.get("done"):
            continue

        if not row.get("destination"):
            row["result"] = "skip: no destination - set one in the plan"
            result["skipped"].append(row)
            if save:
                save(plan)
            if on_row:
                on_row(row)
            continue

        src, dest = Path(row["source"]), Path(row["destination"])

        try:
            if dest.exists():
                row["result"] = "skip:conflict"
                result["skipped"].append(row)
            elif not src.exists():
                row["result"] = "failed: source missing"
                result["failed"].append(row)
            else:
                dest.parent.mkdir(parents=True, exist_ok=True)
                partial = dest.with_name(dest.name + ".vulcan-partial")
                space_needed = row["size"] - (partial.stat().st_size if partial.exists() else 0)
                if _free(dest.parent) < space_needed:
                    result["stopped"] = f"destination full before {src.name}"
                    break

                copied = run(["rsync", "--partial", "--append-verify", "--preallocate", str(src), str(partial)],
                             capture_output=True, text=True)
                if copied.returncode != 0:
                    # Keep partial for resumability on next run via --append-verify
                    row["result"] = f"failed: rsync exit {copied.returncode}: {(copied.stderr or '').strip()[:120]}"
                    result["failed"].append(row)
                elif not verify_copy(src, partial, verify):
                    partial.unlink(missing_ok=True)
                    row["result"] = "failed: copy did not verify"
                    result["failed"].append(row)
                else:
                    def _finish():
                        partial.unlink(missing_ok=True)
                        copied_sidecars = []
                        for sidecar in row.get("sidecars", []):
                            target = dest.parent / Path(sidecar).name
                            if Path(sidecar).exists() and not target.exists():
                                shutil.copyfile(sidecar, target)
                                copied_sidecars.append(sidecar)
                        if move:
                            src.unlink()
                            for sidecar in copied_sidecars:
                                Path(sidecar).unlink(missing_ok=True)
                        row["done"], row["result"] = True, "imported"
                        result["imported"].append(row)

                    # Atomic no-overwrite placement: hard link then remove
                    # partial, falling back to a rename on filesystems with
                    # no hard links (exFAT/FAT/CIFS).
                    try:
                        os.link(str(partial), str(dest))
                    except FileExistsError:
                        partial.unlink(missing_ok=True)
                        row["result"] = "skip:conflict"
                        result["skipped"].append(row)
                    except OSError as error:
                        if error.errno not in _NO_HARDLINK_ERRNOS:
                            raise
                        # ponytail: exists-check then rename is a tiny race
                        # (another import could create dest in between) -
                        # acceptable since it only runs where hard links
                        # aren't available; worst case is a spurious
                        # skip:conflict, never an overwrite or lost data.
                        if dest.exists():
                            partial.unlink(missing_ok=True)
                            row["result"] = "skip:conflict"
                            result["skipped"].append(row)
                        else:
                            os.rename(partial, dest)
                            _finish()
                    else:
                        _finish()
        except OSError as error:
            row["result"] = f"failed: {error}"
            result["failed"].append(row)

        if save:
            save(plan)
        if on_row:
            on_row(row)

    return result
