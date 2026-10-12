import errno
import os
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


def test_move_preserves_preexisting_sidecar_at_destination(tmp_path):
    """Move with pre-existing same-named sidecar at destination: source sidecar must still exist."""
    src, sub, dest = setup(tmp_path)
    dest.parent.mkdir(parents=True)
    dest_sub = dest.parent / sub.name
    dest_sub.write_text("existing subs")
    plan = {"rows": [row(src, dest, sidecars=[sub])]}
    import_plan(plan, move=True, run=fake_rsync)
    assert dest.exists() and not src.exists()
    assert dest_sub.read_text() == "existing subs"  # unchanged
    assert sub.exists()  # source sidecar not deleted (target already existed)


def test_link_fallback_renames_into_place_when_hard_links_unsupported(tmp_path, monkeypatch):
    """exFAT/FAT/CIFS don't support hard links - os.link raising EPERM (or similarly) must fall
    back to a plain rename instead of failing the row."""
    src, sub, dest = setup(tmp_path)
    real_link = os.link

    def no_hardlinks(a, b):
        raise OSError(errno.EPERM, "operation not permitted")

    monkeypatch.setattr(os, "link", no_hardlinks)
    plan = {"rows": [row(src, dest, sidecars=[sub])]}
    result = import_plan(plan, run=fake_rsync)
    assert dest.read_bytes() == b"video-bytes" and plan["rows"][0]["result"] == "imported"
    assert result["imported"] and not list(dest.parent.glob("*.vulcan-partial"))
    monkeypatch.setattr(os, "link", real_link)


def test_link_fallback_skips_conflict_when_dest_exists(tmp_path, monkeypatch):
    """Without hard links, the fallback's own exists-check must still refuse to clobber a
    destination that appeared between the copy and placement (another import, a race)."""
    src, _, dest = setup(tmp_path)

    def no_hardlinks(a, b):
        raise OSError(errno.EPERM, "operation not permitted")

    monkeypatch.setattr(os, "link", no_hardlinks)

    def race_rsync(cmd, **kw):
        shutil.copyfile(cmd[-2], cmd[-1])
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"other writer")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    plan = {"rows": [row(src, dest)]}
    result = import_plan(plan, run=race_rsync)
    assert dest.read_bytes() == b"other writer" and plan["rows"][0]["result"] == "skip:conflict"
    assert result["skipped"] and not list(dest.parent.glob("*.vulcan-partial"))


def test_import_reports_missing_destination_instead_of_silently_skipping(tmp_path):
    src, _, _ = setup(tmp_path)
    bad_row = {"source": str(src), "size": src.stat().st_size, "sidecars": [], "destination": None,
               "action": "import"}
    plan = {"rows": [bad_row]}
    result = import_plan(plan, run=fake_rsync)
    assert bad_row["result"] == "skip: no destination - set one in the plan"
    assert result["skipped"] == [bad_row] and not result["imported"] and not result["failed"]


def test_dest_created_during_copy_results_in_skip_conflict(tmp_path):
    """Dest created between copy and placement: result skip:conflict, no partial left, source kept."""
    src, _, dest = setup(tmp_path)

    def race_rsync(cmd, **kw):
        """Copy succeeds but then someone creates the destination."""
        shutil.copyfile(cmd[-2], cmd[-1])
        # Simulate race: destination appears before we try to link it
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"other writer")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    plan = {"rows": [row(src, dest)]}
    import_plan(plan, move=True, run=race_rsync)
    assert dest.exists() and dest.read_bytes() == b"other writer"  # other writer's data
    assert src.exists()  # source kept (not deleted)
    assert plan["rows"][0]["result"] == "skip:conflict"
    assert not list(dest.parent.glob("*.vulcan-partial"))  # partial cleaned up


def test_resume_with_partial_accounts_for_partial_size(tmp_path, monkeypatch):
    """Pre-existing partial of size N-1; free space check should account for it."""
    src, _, dest = setup(tmp_path)
    dest.parent.mkdir(parents=True)
    partial = dest.with_name(dest.name + ".vulcan-partial")
    partial.write_bytes(b"x" * (len(b"video-bytes") - 1))  # partial is 10 bytes, src is 11 bytes

    import installer.media.transfer

    # Only 5 bytes free, but with the partial already there we need 11 - 10 = 1 byte, so it fits.
    monkeypatch.setattr(installer.media.transfer, "_free", lambda path: 5)

    plan = {"rows": [row(src, dest)]}
    result = import_plan(plan, run=fake_rsync)
    assert result["imported"]  # should succeed (5 free + 10 partial > 11 needed)


def test_oserror_during_sidecar_copy_fails_row_but_continues(tmp_path, monkeypatch):
    """OSError during sidecar copy: that row fails, next row in plan still imports."""
    src1, sub1, dest1 = setup(tmp_path, data=b"video1")
    src2, _, dest2 = setup(tmp_path / "second", data=b"video2")

    original_copyfile = shutil.copyfile
    call_count = [0]

    def failing_copyfile(src, dst):
        call_count[0] += 1
        if call_count[0] == 1:  # fail on first sidecar copy
            raise OSError("Sidecar copy failed")
        return original_copyfile(src, dst)

    monkeypatch.setattr(shutil, "copyfile", failing_copyfile)

    plan = {"rows": [row(src1, dest1, sidecars=[sub1]), row(src2, dest2)]}
    result = import_plan(plan, run=fake_rsync)
    # First row should fail (OSError during sidecar copy)
    assert len(result["failed"]) == 1 and "Sidecar copy failed" in plan["rows"][0]["result"]
    # Second row should still import
    assert len(result["imported"]) == 1 and dest2.exists()


def test_scan_write_load_import_round_trip(tmp_path):
    """End-to-end: scan a real drive, save the plan, reload it, import it - no mocking of the
    plan/transfer boundary itself, just the two things that would otherwise need real tools."""
    from installer.media.plan import load_plan, scan, write_plan

    class FakeProber:
        def probe(self, path):
            return {"width": 1920, "height": 1080, "vcodec": "h264", "bit_depth": 8, "duration": 1.0,
                    "audio": [{"lang": "eng", "codec": "aac"}], "subs": []}

    src = tmp_path / "drive" / "Heat.1995.mkv"
    src.parent.mkdir(parents=True)
    src.write_bytes(b"video-bytes")
    lib = tmp_path / "lib"

    plan = scan(src.parent, lib, FakeProber(), free_bytes=10**9)
    plan_path = tmp_path / "plans" / "scan.json"
    write_plan(plan, plan_path)

    reloaded = load_plan(plan_path)
    result = import_plan(reloaded, run=fake_rsync, save=lambda p: write_plan(p, plan_path))

    dest = lib / "media" / "movies" / "Heat (1995)" / "Heat.1995.mkv"
    assert result["imported"] and dest.read_bytes() == b"video-bytes"
    assert load_plan(plan_path)["rows"][0]["done"] is True
