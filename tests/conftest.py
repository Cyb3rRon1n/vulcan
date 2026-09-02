"""Test isolation for the Vulcan suite.

The CLI and several engine functions resolve ``stack/``, ``backups/``,
``exports/`` and ``stack/.vulcan-state.json`` relative to the *current
working directory*. Running ``pytest`` from a checkout that happens to
contain a real generated ``stack/`` - a dev box, or a homelab actually
running Vulcan - made a dozen-odd mocked CLI tests see a bogus "re-run
against an existing stack" state and fail (wrong prompt sequence, wrong
exit code). Found the hard way on two separate machines.

Fixing it per-test is whack-a-mole; the whole suite should be
independent of what's sitting in the checkout. So: every test runs from
a fresh empty directory.
"""

import pytest


@pytest.fixture(autouse=True)
def _isolate_cwd(tmp_path, monkeypatch):
    # monkeypatch.chdir restores the original cwd at teardown. Templates
    # and other package data are resolved via the installer package path,
    # not cwd, so nothing that should work breaks.
    monkeypatch.chdir(tmp_path)
