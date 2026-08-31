from unittest.mock import patch

from installer.deps import _family_for, ensure_system_deps


def test_family_for_known_distros():

    assert _family_for("ubuntu") == "debian"
    assert _family_for("debian") == "debian"
    assert _family_for("fedora") == "fedora"
    assert _family_for("rocky") == "fedora"
    assert _family_for("arch") == "arch"


def test_family_for_unknown_distro():

    assert _family_for("gentoo") is None
    assert _family_for(None) is None


def test_ensure_system_deps_dry_run_lists_missing_packages():

    with patch("installer.deps.detect_os",
               return_value={"os_id": "ubuntu", "os_is_atomic": False}), \
         patch("installer.deps.shutil.which",
               side_effect=lambda b: None if b in ("python3", "whiptail") else "/usr/bin/x"):

        plan = ensure_system_deps(dry_run=True)

    assert "python3-venv" in plan["packages"]
    assert "whiptail" in plan["packages"]
    assert plan["installed"] == []
    assert plan["missing_after"] == []


def test_ensure_system_deps_all_present_short_circuits():

    with patch("installer.deps.detect_os",
               return_value={"os_id": "fedora", "os_is_atomic": False}), \
         patch("installer.deps.shutil.which", return_value="/usr/bin/x"):

        plan = ensure_system_deps()

    assert plan["packages"] == []
    assert plan["success"] is True
    assert plan["missing_after"] == []
    assert plan["already_present"] == ["python3", "whiptail", "mdadm", "git"]


def test_ensure_system_deps_installs_missing_and_rechecks():

    present = {"python3": True, "whiptail": True, "mdadm": False, "git": True}

    def fake_which(binary):
        return "/usr/bin/x" if present.get(binary) else None

    def fake_run(cmd, **kwargs):
        present["mdadm"] = True
        return {"success": True, "error": None}

    with patch("installer.deps.detect_os",
               return_value={"os_id": "arch", "os_is_atomic": False}), \
         patch("installer.deps.shutil.which", side_effect=fake_which), \
         patch("installer.deps.run_privileged", side_effect=fake_run) as mock_run:

        plan = ensure_system_deps()

    mock_run.assert_called_once_with(["pacman", "-Sy", "--noconfirm", "mdadm"])

    assert plan["success"] is True
    assert plan["missing_after"] == []
    assert plan["installed"] == ["mdadm"]


def test_ensure_system_deps_unknown_distro_reports_missing():

    with patch("installer.deps.detect_os",
               return_value={"os_id": "gentoo", "os_is_atomic": False}), \
         patch("installer.deps.shutil.which", return_value=None):

        plan = ensure_system_deps()

    assert plan["success"] is False
    assert plan["missing_after"] == ["python3", "whiptail", "mdadm", "git"]


def test_git_is_in_the_debian_install_plan_when_missing(monkeypatch):
    from installer import deps

    monkeypatch.setattr(deps, "detect_os", lambda: {"os_id": "ubuntu", "os_is_atomic": False})
    monkeypatch.setattr(deps, "_tool_present", lambda tool: tool != "git")

    plan = deps.ensure_system_deps(dry_run=True)

    assert "git" in plan["packages"]
