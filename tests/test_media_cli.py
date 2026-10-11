import json
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from installer.cli import app

runner = CliRunner()


def fake_plan(tmp_path, fits=True):
    return {"version": 1, "source": str(tmp_path), "media_path": str(tmp_path / "lib"), "rows": [],
            "summary": {"files": 0, "actions": {}, "import_bytes": 0, "free_bytes": 1, "fits": fits,
                        "rule_breaks": 0, "may_convert": 0, "review": 0}}


class NullProber:
    def __init__(self, *a, **k): pass
    def __enter__(self): return self
    def __exit__(self, *a): return False


def test_scan_needs_a_stack_or_media_path(tmp_path):
    result = runner.invoke(app, ["media", "scan", str(tmp_path)])
    assert result.exit_code == 1 and "--media-path" in result.output


def test_scan_writes_plan_and_fails_when_it_does_not_fit(tmp_path):
    out = tmp_path / "p.json"
    with patch("installer.cli.MediaProber", NullProber), \
         patch("installer.cli.media_scan_engine", return_value=fake_plan(tmp_path, fits=False)):
        result = runner.invoke(app, ["media", "scan", str(tmp_path), "--media-path", str(tmp_path / "lib"),
                                     "--offline", "--plan", str(out)])
    assert result.exit_code == 1 and out.exists() and "won't fit" in result.output.lower()


def test_import_requires_rsync(tmp_path):
    plan = tmp_path / "p.json"
    plan.write_text(json.dumps(fake_plan(tmp_path)))
    with patch("installer.cli.shutil.which", return_value=None):
        result = runner.invoke(app, ["media", "import", str(plan)])
    assert result.exit_code == 1 and "rsync" in result.output


def test_import_offline_queues_imported_rows_for_registration(tmp_path):
    plan = tmp_path / "p.json"
    plan.write_text(json.dumps(fake_plan(tmp_path)))
    imported = [{"destination": "/lib/a.mkv", "identity": {}}]
    pending = []
    with patch("installer.cli.shutil.which", return_value="/usr/bin/rsync"), \
         patch("installer.cli.import_plan", return_value={"imported": imported, "failed": [], "skipped": [], "stopped": None}), \
         patch("installer.cli.add_pending", side_effect=lambda rows, *a: pending.extend(rows)):
        result = runner.invoke(app, ["media", "import", str(plan), "--offline"])
    assert result.exit_code == 0, result.output
    assert pending and pending[0]["reason"] == "stack offline" and "vulcan media register" in result.output


def test_register_without_reachable_arrs_exits_1(tmp_path):
    result = runner.invoke(app, ["media", "register"])
    assert result.exit_code == 1 and "Sonarr/Radarr" in result.output
