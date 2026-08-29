"""
Build and consume a self-contained offline bundle of Vulcan's own Python
dependencies - the piece a fresh, disconnected box can't get from PyPI.

`vulcan export-bundle` (run on a machine with network, for the target
machine's arch) resolves Vulcan's exact runtime dependency tree from
pyproject.toml with `pip download` and writes it to a tarball; a bundle
install (the `vulcan install-bundle` command, or the same call wired into
the `install` bootstrap) untars it on the offline box and `pip install
--no-index --find-links` from it, so the venv is built with zero network.

This deliberately mirrors the existing export_images/import_images image-
transfer pattern (build on a connected box, carry the artifact across,
consume offline) - but for Vulcan's own Python deps, not container
images. It does NOT bundle host packages (python3/whiptail/mdadm/curl) or
Docker itself; those stay the concern of deps.py / docker_setup.py.

# ponytail: the bundle only carries Vulcan's Python deps today. Bundling
# the docker-ce .debs for the target arch (the other half of a truly
# offline first boot) is deliberately deferred - resolving Docker's
# per-arch .deb set from download.docker.com is arch+fragile and needs a
# network to even test. Add a debs/ section to build_bundle() when that
# becomes a real need.
"""

import subprocess
import sys
import tarfile
import tomllib
from datetime import datetime, timezone as dt_timezone
from pathlib import Path


def runtime_dependencies(project_root: Path = Path(".")) -> list[str]:
    """Vulcan's runtime dependency names from [project].dependencies in
    pyproject.toml - the source of truth, not a hardcoded copy, so a dep
    bump there is picked up automatically. Returns [] if pyproject is
    missing or unparseable."""

    pyproject = Path(project_root) / "pyproject.toml"

    if not pyproject.exists():
        return []

    try:

        with open(pyproject, "rb") as f:
            data = tomllib.load(f)

    except (tomllib.TOMLDecodeError, OSError):
        return []

    return list(data.get("project", {}).get("dependencies", []) or [])


def _pip_download_args(
    deps: list[str], wheel_dir: Path, platform: str | None, py_abi: str
) -> list[str]:
    """Build the `pip download` argv. platform=None means "current machine"
    (build for the box you're on); an explicit platform tag cross-builds
    for a different arch (e.g. manylinux2014_aarch64) from this one."""

    args = [
        sys.executable, "-m", "pip", "download",
        "--only-binary=:all:",  # vulcan's deps are all wheels; no sdists to compile
        "--dest", str(wheel_dir),
    ]

    if platform is not None:
        args += [
            "--platform", platform,
            "--python-version", py_abi.replace("cp", ""),  # "cp311" -> "311"
            "--implementation", "cp",
            "--abi", py_abi,
        ]

    args += deps
    return args


def _venv_pip(venv_dir: Path) -> list[str]:
    """The pip binary inside a venv, or system pip if venv_dir is empty."""

    if venv_dir is not None and (venv_dir / "bin" / "pip").exists():
        return [str(venv_dir / "bin" / "python"), "-m", "pip"]

    return [sys.executable, "-m", "pip"]


def bundle_dependencies(
    dest_dir: Path,
    project_root: Path = Path("."),
    platform: str | None = None,
    py_abi: str = "cp311",
) -> dict:
    """
    Resolve Vulcan's runtime deps into dest_dir/wheels/ via `pip download`
    (the full transitive tree, so the venv can be built with
    --no-index). platform=None builds for the current machine; pass an
    explicit platform tag to cross-build for another arch.

    Returns the project's result-dict convention:
    {"success", "error", "wheel_dir"}.
    """

    deps = runtime_dependencies(project_root)

    if not deps:
        return {"success": False, "error": "no runtime dependencies found in pyproject.toml", "wheel_dir": None}

    wheel_dir = dest_dir / "wheels"
    wheel_dir.mkdir(parents=True, exist_ok=True)

    result = subprocess.run(
        _pip_download_args(deps, wheel_dir, platform, py_abi),
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        return {
            "success": False,
            "error": f"pip download failed: {result.stderr.strip() or result.stdout.strip()}",
            "wheel_dir": str(wheel_dir),
        }

    return {"success": True, "error": None, "wheel_dir": str(wheel_dir)}


def package_bundle(dest_dir: Path, arch_label: str, version: str, deps: list[str]) -> dict:
    """Tar dest_dir/wheels/ plus a requirements.txt (the resolved dep names)
    into a single carryable artifact named vulcan-offline-<arch>-<version>-<ts>.tar.gz
    in dest_dir. The requirements.txt lets a consumer `pip install --no-index
    --find-links wheels -r requirements.txt` without any local copy of
    pyproject.toml. Returns {"success", "error", "bundle_path"}."""

    wheel_dir = dest_dir / "wheels"

    if not wheel_dir.is_dir() or not any(wheel_dir.iterdir()):
        return {"success": False, "error": "no wheels to package - run bundle_dependencies first", "bundle_path": None}

    req_file = dest_dir / "requirements.txt"

    if deps:
        req_file.write_text("\n".join(deps) + "\n")

    ts = datetime.now(dt_timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    bundle_path = dest_dir / f"vulcan-offline-{arch_label}-{version}-{ts}.tar.gz"

    try:

        with tarfile.open(bundle_path, "w:gz") as tar:
            tar.add(wheel_dir, arcname="wheels")
            if req_file.exists():
                tar.add(req_file, arcname="requirements.txt")

    except (OSError, tarfile.TarError) as error:
        return {"success": False, "error": str(error), "bundle_path": str(bundle_path)}

    return {"success": True, "error": None, "bundle_path": str(bundle_path)}


def extract_bundle(bundle_path: str | Path, dest_dir: Path) -> dict:
    """Untar a bundle produced by package_bundle() into dest_dir/wheels/
    (arms-length paths only - never writes outside dest_dir). Returns
    {"success", "error", "wheel_dir"}."""

    bundle_path = Path(bundle_path)

    if not bundle_path.exists():
        return {"success": False, "error": f"bundle not found: {bundle_path}", "wheel_dir": None}

    dest_dir.mkdir(parents=True, exist_ok=True)

    try:

        with tarfile.open(bundle_path, "r:gz") as tar:
            for member in tar.getmembers():
                target = (dest_dir / member.name).resolve()
                if not str(target).startswith(str(dest_dir.resolve())):
                    return {"success": False, "error": "bundle contains a path outside dest", "wheel_dir": None}
            tar.extractall(dest_dir)

    except (OSError, tarfile.TarError) as error:
        return {"success": False, "error": str(error), "wheel_dir": None}

    wheel_dir = dest_dir / "wheels"
    return {"success": True, "error": None, "wheel_dir": str(wheel_dir)}


def install_from_wheelhouse(
    wheel_dir: Path, deps: list[str], venv_dir: Path | None = None
) -> dict:
    """
    pip install --no-index --find-links wheel_dir <deps...> into the venv -
    the offline half of the bundle, no network touched. Each dep resolves
    from the wheelhouse (the full transitive tree is bundled), so
    --no-index + --find-links never reach PyPI. Returns the result dict."""

    if not wheel_dir.is_dir() or not any(wheel_dir.iterdir()):
        return {"success": False, "error": f"no wheels found in {wheel_dir}"}

    if not deps:
        return {"success": False, "error": "no dependencies to install - run export-bundle produced an empty wheelhouse?"}

    args = [*_venv_pip(venv_dir), "install", "--no-index", "--find-links", str(wheel_dir), *deps]

    result = subprocess.run(args, capture_output=True, text=True)

    if result.returncode != 0:
        return {
            "success": False,
            "error": f"pip install failed: {result.stderr.strip() or result.stdout.strip()}",
        }

    return {"success": True, "error": None}
