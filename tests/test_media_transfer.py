import shutil
import subprocess
from pathlib import Path

from installer.media.transfer import import_plan, verify_copy


def fake_rsync(cmd, **kw):
    """Stand-in for `rsync ... SRC DST`: plain copy (tests don't depend on rsync being installed)."""
    shutil.copyfile(cmd[-2], cmd[-1])
    return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")


def row(src, dest, action="import", sidecars=()):
    return {"source": str(src), "size": src.stat().st_size, "sidecars": [str(s) for s in sidecars],
            "destination": str(dest), "action": action}


def setup(tmp_path, data=b"video-bytes"):
    src = tmp_path / "drive" / "Heat.1995.mkv"
    src.parent.mkdir(parents=True)
    src.write_bytes(data)
    sub = tmp_path / "drive" / "Heat.1995.en.srt"
    sub.write_text("subs")
    dest = tmp_path / "lib" / "media" / "movies" / "Heat (1995)" / "Heat.1995.mkv"
    return src, sub, dest


def test_verify_copy_quick_and_full(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.write_bytes(b"x" * (20 * 1024 * 1024))
    b.write_bytes(b"x" * (20 * 1024 * 1024))
    assert verify_copy(a, b) and verify_copy(a, b, "full")
    b.write_bytes(b"x" * (10 * 1024 * 1024) + b"y" + b"x" * (10 * 1024 * 1024 - 1))   # middle differs
    assert verify_copy(a, b, "quick") and not verify_copy(a, b, "full")
    b.write_bytes(b"short")
    assert not verify_copy(a, b)


def test_import_copies_video_and_sidecar_and_keeps_source(tmp_path):
    src, sub, dest = setup(tmp_path)
    plan = {"rows": [row(src, dest, sidecars=[sub])]}
    saved = []
    result = import_plan(plan, run=fake_rsync, save=lambda p: saved.append(True))
    assert dest.read_bytes() == b"video-bytes" and (dest.parent / "Heat.1995.en.srt").read_text() == "subs"
    assert src.exists() and not list(dest.parent.glob("*.vulcan-partial"))
    assert plan["rows"][0]["done"] and plan["rows"][0]["result"] == "imported"
    assert len(result["imported"]) == 1 and saved


def test_import_skips_non_import_rows_unless_review_included(tmp_path):
    src, _, dest = setup(tmp_path)
    plan = {"rows": [row(src, dest, action="review")]}
    assert import_plan(plan, run=fake_rsync)["imported"] == []
    assert len(import_plan(plan, run=fake_rsync, include_review=True)["imported"]) == 1


def test_import_never_overwrites_existing(tmp_path):
    src, _, dest = setup(tmp_path)
    dest.parent.mkdir(parents=True)
    dest.write_bytes(b"keep me")
    plan = {"rows": [row(src, dest)]}
    result = import_plan(plan, run=fake_rsync)
    assert dest.read_bytes() == b"keep me" and plan["rows"][0]["result"] == "skip:conflict" and result["skipped"]


def test_move_deletes_source_only_after_verify(tmp_path):
    src, sub, dest = setup(tmp_path)

    def corrupting_rsync(cmd, **kw):
        Path(cmd[-1]).write_bytes(b"corrupt")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    plan = {"rows": [row(src, dest, sidecars=[sub])]}
    result = import_plan(plan, move=True, run=corrupting_rsync)
    assert src.exists() and not dest.exists() and result["failed"]
    assert not list(dest.parent.glob("*.vulcan-partial"))
    plan = {"rows": [row(src, dest, sidecars=[sub])]}
    import_plan(plan, move=True, run=fake_rsync)
    assert dest.exists() and not src.exists() and not sub.exists()


def test_resume_skips_done_rows_and_missing_source_fails_softly(tmp_path):
    src, _, dest = setup(tmp_path)
    gone = row(src, tmp_path / "lib" / "x.mkv")
    gone["source"] = str(tmp_path / "drive" / "vanished.mkv")
    plan = {"rows": [dict(row(src, dest), done=True, result="imported"), gone]}
    result = import_plan(plan, run=fake_rsync)
    assert not dest.exists()                                         # done row not redone
    assert plan["rows"][1]["result"].startswith("failed: source missing") and result["failed"]


def test_rsync_failure_is_a_failed_row(tmp_path):
    src, _, dest = setup(tmp_path)
    plan = {"rows": [row(src, dest)]}
    bad = lambda cmd, **kw: subprocess.CompletedProcess(cmd, 23, stdout="", stderr="rsync error")
    result = import_plan(plan, run=bad)
    assert plan["rows"][0]["result"].startswith("failed: rsync") and result["failed"] and not dest.exists()
