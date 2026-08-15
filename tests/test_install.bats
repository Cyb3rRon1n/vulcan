#!/usr/bin/env bats
#
# Unit tests for the ./install bootstrap's venv-readiness check. The
# bootstrap is gated on the venv being genuinely able to import
# installer.cli, not just on the .venv directory existing - an
# interrupted/failed first run leaves .venv/ present but with no deps
# installed, and the old `[ ! -d "$VENV_DIR" ]` gate silently skipped
# setup forever after, exec'ing a venv python that crashed with
# "No module named 'typer'" (a real, reproduced bug).
# Each test runs a copy of the real `install` script against a stub
# venv whose bin/python simulates either a healthy or a broken install.

setup() {
    REPO="$BATS_TEST_DIRNAME/.."
    INSTALL_DIR="$BATS_TMPDIR/vulcan-install-$$"
    rm -rf "$INSTALL_DIR"
    mkdir -p "$INSTALL_DIR/.venv/bin" "$INSTALL_DIR/bin"
    cp "$REPO/install" "$INSTALL_DIR/install"
    chmod +x "$INSTALL_DIR/install"
}

teardown() {
    rm -rf "$INSTALL_DIR"
}

@test "a broken venv (import fails) triggers the full re-bootstrap" {

    # bin/python fails the readiness import - simulates a .venv/ left
    # behind by an interrupted first run, present but dep-less. Fails
    # only the bootstrap's own `-c "import installer.cli"` check; the
    # final `exec ... -m installer` below must still exit 0.
    cat > "$INSTALL_DIR/.venv/bin/python" <<'EOF'
#!/usr/bin/env bash
if [ "$1" = "-c" ]; then
    exit 1
fi
exit 0
EOF
    chmod +x "$INSTALL_DIR/.venv/bin/python"

    # pip is invoked via its absolute path inside the venv, so the stub
    # must live at .venv/bin/pip; it records what it was asked to do.
    cat > "$INSTALL_DIR/.venv/bin/pip" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$PIP_LOG"
exit 0
EOF
    chmod +x "$INSTALL_DIR/.venv/bin/pip"

    # python3 (on PATH) must pass the version check and "create" the
    # venv; the version check is the one `-c` invocation that needs a
    # real version string back.
    cat > "$INSTALL_DIR/bin/python3" <<'EOF'
#!/usr/bin/env bash
if [ "$1" = "-c" ]; then
    printf '3.11\n'
fi
exit 0
EOF
    chmod +x "$INSTALL_DIR/bin/python3"

    PIP_LOG="$INSTALL_DIR/pip.log"
    run env PATH="$INSTALL_DIR/bin:$PATH" PIP_LOG="$PIP_LOG" bash "$INSTALL_DIR/install" --plain version

    [ "$status" -eq 0 ]
    [[ "$output" == *"Setting up Vulcan (first run)..."* ]]
    [[ "$(cat "$PIP_LOG")" == *"-e $INSTALL_DIR"* ]]
}

@test "a healthy venv (import succeeds) skips the re-bootstrap" {

    cat > "$INSTALL_DIR/.venv/bin/python" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
    chmod +x "$INSTALL_DIR/.venv/bin/python"

    # Same python3 stub as above - a healthy run never reaches it, but
    # the script's own version check runs before the venv gate either way.
    cat > "$INSTALL_DIR/bin/python3" <<'EOF'
#!/usr/bin/env bash
if [ "$1" = "-c" ]; then
    printf '3.11\n'
fi
exit 0
EOF
    chmod +x "$INSTALL_DIR/bin/python3"

    # If the setup block is (wrongly) entered, pip writing to the log
    # would fail loudly - and the test below would see the log exists.
    cat > "$INSTALL_DIR/.venv/bin/pip" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$PIP_LOG"
exit 0
EOF
    chmod +x "$INSTALL_DIR/.venv/bin/pip"

    PIP_LOG="$INSTALL_DIR/pip.log"
    run env PATH="$INSTALL_DIR/bin:$PATH" PIP_LOG="$PIP_LOG" bash "$INSTALL_DIR/install" --plain version

    [ "$status" -eq 0 ]
    [[ "$output" != *"Setting up Vulcan (first run)..."* ]]
    [ ! -e "$PIP_LOG" ]
}
