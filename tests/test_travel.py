import socket
import subprocess

from installer.travel import apply_steps, avahi_steps, doctor_checks, host_setup

DEBIAN = {"os_id": "debian", "os_is_atomic": False, "architecture": "x86_64"}


def fake_runner(fail_on=None):

    calls = []

    def run(argv):
        calls.append(argv)
        ok = argv != fail_on
        return {"success": ok, "error": None if ok else "exit code 1"}

    return calls, run


def fake_write(written):

    def write(path, content, run):
        written[path] = content
        return {"success": True, "error": None}

    return write


def test_avahi_steps_per_family():

    assert avahi_steps("ubuntu", False, "trip") == [
        ["apt-get", "install", "-y", "avahi-daemon", "libnss-mdns"],
        ["hostnamectl", "set-hostname", "trip"],
        ["systemctl", "enable", "--now", "avahi-daemon"],
    ]
    assert avahi_steps("fedora", False, "trip")[0] == ["dnf", "install", "-y", "avahi", "nss-mdns"]
    assert avahi_steps("fedora", True, "trip") == [
        ["hostnamectl", "set-hostname", "trip"],
        ["systemctl", "enable", "--now", "avahi-daemon"],
    ]
    assert avahi_steps("gentoo", False, "trip") is None


def test_apply_steps_stops_at_the_first_failure():

    calls, run = fake_runner(fail_on=["b"])
    result = apply_steps([["a"], ["b"], ["c"]], run)

    assert result == {"ok": False, "error": "b: exit code 1"}
    assert calls == [["a"], ["b"]]


def test_host_setup_runs_avahi():

    calls, run = fake_runner()
    results = host_setup({"jellyfin"}, "trip", False, DEBIAN, run=run, write=fake_write({}), exists=lambda p: False)

    assert results[0] == {"step": "avahi (trip.local)", "ok": True, "error": None, "skipped": False}
    assert ["hostnamectl", "set-hostname", "trip"] in calls


def test_host_setup_reports_an_unsupported_distro():

    calls, run = fake_runner()
    results = host_setup({"jellyfin"}, "trip", False, {"os_id": "gentoo", "os_is_atomic": False},
                         run=run, write=fake_write({}), exists=lambda p: False)

    assert results[0]["ok"] is False and "avahi" in results[0]["error"]
    assert calls == []


def test_doctor_checks_pass():

    def active(argv, **kw):
        return subprocess.CompletedProcess(argv, 0, "active\n", "")

    checks = doctor_checks("trip", run_capture=active, resolve=lambda host, port: [("ok",)])

    assert [c["ok"] for c in checks] == [True, True]


def test_doctor_checks_fail_with_plain_fixes():

    def inactive(argv, **kw):
        return subprocess.CompletedProcess(argv, 3, "inactive\n", "")

    def no_resolve(host, port):
        raise socket.gaierror("Name or service not known")

    checks = doctor_checks("trip", run_capture=inactive, resolve=no_resolve)

    assert [c["ok"] for c in checks] == [False, False]
    assert "systemctl enable --now avahi-daemon" in checks[0]["fix"]
    assert "trip.local" in checks[1]["name"]
    assert "libnss-mdns" in checks[1]["fix"]


def test_host_setup_rejects_a_bad_hostname_before_running_anything():

    calls, run = fake_runner()
    written = {}

    for bad in ("Bad Name", "-x", "a.b", ""):
        results = host_setup({"jellyfin"}, bad, False, DEBIAN, run=run, write=fake_write(written), exists=lambda p: False)

        assert results[0]["ok"] is False and "not a valid hostname" in results[0]["error"]

    assert calls == [] and written == {}


def _hosts_for(text):

    written = {}
    calls, run = fake_runner()
    rows = host_setup({"jellyfin"}, "trip", False, DEBIAN, run=run, write=fake_write(written),
                      exists=lambda p: False, read_hosts=lambda: text)

    return rows, written


def test_hosts_replaces_the_old_127_0_1_1_line_only():

    rows, written = _hosts_for("127.0.0.1 localhost\n127.0.1.1 oldname oldname.lan\n::1 ip6-localhost\n")

    assert written["/etc/hosts"] == "127.0.0.1 localhost\n127.0.1.1 trip\n::1 ip6-localhost\n"
    assert rows[1]["ok"] is True


def test_hosts_adds_the_line_when_missing():

    _, written = _hosts_for("127.0.0.1 localhost\n")

    assert written["/etc/hosts"] == "127.0.0.1 localhost\n127.0.1.1 trip\n"


def test_hosts_is_untouched_when_already_correct():

    rows, written = _hosts_for("127.0.0.1 localhost\n127.0.1.1 trip\n")

    assert written == {}
    assert rows[1]["skipped"] is True


def test_atomic_failure_and_unknown_distro_mention_rpm_ostree():

    calls, run = fake_runner(fail_on=["systemctl", "enable", "--now", "avahi-daemon"])
    atomic = {"os_id": "fedora", "os_is_atomic": True}
    rows = host_setup({"jellyfin"}, "trip", False, atomic, run=run, write=fake_write({}), exists=lambda p: False)

    assert "rpm-ostree install avahi nss-mdns" in rows[0]["error"] and "reboot" in rows[0]["error"]

    rows = host_setup({"jellyfin"}, "trip", False, {"os_id": "gentoo"}, run=run, write=fake_write({}), exists=lambda p: False)

    assert "rpm-ostree install avahi nss-mdns" in rows[0]["error"]


def test_doctor_fix_covers_arch_and_atomic():

    def no_resolve(host, port):
        raise socket.gaierror("x")

    fix = doctor_checks("trip", run_capture=lambda *a, **k: subprocess.CompletedProcess(a, 0, "active\n", ""),
                        resolve=no_resolve)[1]["fix"]

    assert "pacman -S avahi nss-mdns" in fix and "rpm-ostree install avahi nss-mdns" in fix


def test_hosts_write_is_followed_by_restorecon_only_when_installed():

    for present in (True, False):
        calls, run = fake_runner()

        def write(path, content, run):
            calls.append(["write", path])
            return {"success": True, "error": None}

        host_setup({"jellyfin"}, "trip", False, DEBIAN, run=run, write=write, exists=lambda p: False,
                   read_hosts=lambda: "127.0.0.1 localhost\n",
                   which=lambda name: "/usr/sbin/restorecon" if present else None)

        assert (["restorecon", "/etc/hosts"] in calls) is present
        if present:
            assert calls.index(["restorecon", "/etc/hosts"]) == calls.index(["write", "/etc/hosts"]) + 1
