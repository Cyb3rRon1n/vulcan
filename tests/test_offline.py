import tarfile

from unittest.mock import patch

from installer.offline import (
    build_requires,
    bundle_dependencies,
    extract_bundle,
    install_from_wheelhouse,
    package_bundle,
    runtime_dependencies,
)


def test_runtime_dependencies_parses_pyproject(tmp_path):

    (tmp_path / "pyproject.toml").write_text(
        '[project]\ndependencies = ["typer>=0.12", "rich", "psutil"]\n'
    )

    assert runtime_dependencies(tmp_path) == ["typer>=0.12", "rich", "psutil"]


def test_runtime_dependencies_missing_pyproject_is_empty(tmp_path):

    assert runtime_dependencies(tmp_path) == []


def test_runtime_dependencies_bad_pyproject_is_empty(tmp_path):

    (tmp_path / "pyproject.toml").write_text("not [valid TOML ==")

    assert runtime_dependencies(tmp_path) == []


def test_bundle_dependencies_success(tmp_path):

    with patch("installer.offline.runtime_dependencies",
               return_value=["typer", "rich"]), \
         patch("installer.offline.build_requires", return_value=["hatchling"]), \
         patch("installer.offline.subprocess.run") as mock_run:

        mock_run.return_value.returncode = 0

        result = bundle_dependencies(tmp_path)

    assert result["success"] is True
    assert result["error"] is None
    assert result["wheel_dir"].endswith("wheels")
    # build backend + editable-hook extra downloaded into the same
    # wheelhouse, so the offline box's own `pip install -e .` (build
    # isolation) can resolve them.
    argv = mock_run.call_args.args[0]
    assert "hatchling" in argv
    assert "editables" in argv


def test_build_requires_parses_pyproject(tmp_path):

    (tmp_path / "pyproject.toml").write_text(
        "[build-system]\nrequires = [\"hatchling\"]\n"
    )

    assert build_requires(tmp_path) == ["hatchling"]


def test_build_requires_missing_pyproject_is_empty(tmp_path):

    assert build_requires(tmp_path) == []


def test_bundle_dependencies_subprocess_failure(tmp_path):

    with patch("installer.offline.runtime_dependencies",
               return_value=["typer"]), \
         patch("installer.offline.subprocess.run") as mock_run:

        mock_run.return_value.returncode = 1
        mock_run.return_value.stderr = "no such platform"

        result = bundle_dependencies(tmp_path)

    assert result["success"] is False
    assert "no such platform" in result["error"]


def test_package_and_extract_bundle_roundtrip(tmp_path):

    wheels = tmp_path / "wheels"
    wheels.mkdir()
    (wheels / "typer-0.12.0-py3-none-any.whl").write_text("x")

    packaged = package_bundle(tmp_path, "testarch", "1.0.0", ["typer", "rich"])
    assert packaged["success"] is True

    dest = tmp_path / "out"
    extracted = extract_bundle(packaged["bundle_path"], dest)
    assert extracted["success"] is True
    assert (dest / "wheels" / "typer-0.12.0-py3-none-any.whl").exists()
    assert (dest / "requirements.txt").read_text().splitlines() == ["typer", "rich"]


def test_extract_bundle_missing_file(tmp_path):

    assert extract_bundle(tmp_path / "nope.tar.gz", tmp_path)["success"] is False


def test_extract_bundle_rejects_path_escape(tmp_path):

    malicious = tmp_path / "evil.tar.gz"
    with tarfile.open(malicious, "w:gz") as tar:
        info = tarfile.TarInfo("../../escape.txt")
        info.size = 0
        tar.addfile(info)

    assert extract_bundle(malicious, tmp_path)["success"] is False


def test_install_from_wheelhouse_success(tmp_path):

    wheels = tmp_path / "wheels"
    wheels.mkdir()
    (wheels / "typer-0.12.0-py3-none-any.whl").write_text("x")

    with patch("installer.offline._venv_pip", return_value=["pip"]), \
         patch("installer.offline.subprocess.run") as mock_run:

        mock_run.return_value.returncode = 0

        result = install_from_wheelhouse(wheels, ["typer", "rich"])

    assert result["success"] is True
    args = mock_run.call_args.args[0]
    assert "--no-index" in args
    assert "--find-links" in args
    assert str(wheels) in args
    assert "typer" in args


def test_install_from_wheelhouse_empty_dir(tmp_path):

    wheels = tmp_path / "wheels"
    wheels.mkdir()

    assert install_from_wheelhouse(wheels, ["typer"])["success"] is False


def test_install_from_wheelhouse_subprocess_failure(tmp_path):

    wheels = tmp_path / "wheels"
    wheels.mkdir()
    (wheels / "typer-0.12.0-py3-none-any.whl").write_text("x")

    with patch("installer.offline._venv_pip", return_value=["pip"]), \
         patch("installer.offline.subprocess.run") as mock_run:

        mock_run.return_value.returncode = 1
        mock_run.return_value.stderr = "could not find a version"

        result = install_from_wheelhouse(wheels, ["typer"])

    assert result["success"] is False
    assert "could not find a version" in result["error"]
