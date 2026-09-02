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
# Phase 0 preflight (and any later `-m installer ...`) -> succeed
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

@test "under sudo, venv build and the CLI run as \$SUDO_USER, not root" {

    # A broken venv so the setup block runs.
    cat > "$INSTALL_DIR/.venv/bin/python" <<'EOF'
#!/usr/bin/env bash
if [ "$1" = "-c" ]; then exit 1; fi
# Phase 0 preflight (and any later `-m installer ...`) -> succeed
exit 0
EOF
    chmod +x "$INSTALL_DIR/.venv/bin/python"

    cat > "$INSTALL_DIR/.venv/bin/pip" <<'EOF'
#!/usr/bin/env bash
printf 'pip %s\n' "$*" >> "$RUNLOG"
exit 0
EOF
    chmod +x "$INSTALL_DIR/.venv/bin/pip"

    # Stubs: python3 passes the version check; `id -u` says root;
    # `runuser` records every command it was asked to run as the user.
    cat > "$INSTALL_DIR/bin/python3" <<'EOF'
#!/usr/bin/env bash
if [ "$1" = "-c" ]; then printf '3.11\n'; fi
exit 0
EOF
    cat > "$INSTALL_DIR/bin/id" <<'EOF'
#!/usr/bin/env bash
[ "$1" = "-u" ] && { echo 0; exit 0; }
exec /usr/bin/id "$@"
EOF
    cat > "$INSTALL_DIR/bin/runuser" <<'EOF'
#!/usr/bin/env bash
# runuser -u <user> -- <cmd...>
printf 'runuser %s\n' "$*" >> "$RUNLOG"
shift 3
exec "$@"
EOF
    chmod +x "$INSTALL_DIR/bin/python3" "$INSTALL_DIR/bin/id" "$INSTALL_DIR/bin/runuser"

    RUNLOG="$INSTALL_DIR/run.log"
    run env PATH="$INSTALL_DIR/bin:$PATH" RUNLOG="$RUNLOG" SUDO_USER=testuser \
        bash "$INSTALL_DIR/install" --plain version

    [ "$status" -eq 0 ]
    # venv creation, both pip installs, and the final exec all went via runuser -u testuser
    [[ "$(cat "$RUNLOG")" == *"runuser -u testuser -- "*"-m venv"* ]]
    [[ "$(cat "$RUNLOG")" == *"runuser -u testuser -- "*"pip"*"-e $INSTALL_DIR"* ]]
    [[ "$(cat "$RUNLOG")" == *"runuser -u testuser -- "*"-m installer"* ]]
}

@test "install runs preflight --fix, re-execs under sudo, and Phase 0 completes on the root pass" {

    # healthy venv so the bootstrap goes straight to preflight.
    # preflight only "needs root" on the first (unprivileged) pass -
    # SUDO_USER being set marks the re-exec'd root pass, where it
    # succeeds and the flow proceeds to the final `-m installer` run.
    cat > "$INSTALL_DIR/.venv/bin/python" <<'EOF'
#!/usr/bin/env bash
if [ "$1" = "-c" ]; then exit 0; fi          # import check passes
if [ "$2" = "installer" ] && [ "$3" = "preflight" ]; then
    if [ -z "${SUDO_USER:-}" ]; then
        echo "Phase 0 needs root"
        exit 1
    fi
    exit 0                                    # root pass -> preflight OK
fi
# the final `-m installer <args>` (the real app) -> succeed
exit 0
EOF
    chmod +x "$INSTALL_DIR/.venv/bin/python"

    cat > "$INSTALL_DIR/bin/python3" <<'EOF'
#!/usr/bin/env bash
if [ "$1" = "-c" ]; then printf '3.11\n'; fi
exit 0
EOF
    # root only on the re-exec'd pass (SUDO_USER set by the sudo stub)
    cat > "$INSTALL_DIR/bin/id" <<'EOF'
#!/usr/bin/env bash
if [ "$1" = "-u" ]; then
    [ -n "${SUDO_USER:-}" ] && echo 0 || echo 1000
    exit 0
fi
exec /usr/bin/id "$@"
EOF
    # sudo actually re-execs the script as "root": same PATH, RUNLOG,
    # and SUDO_USER set so the id/python stubs switch to their root behaviour.
    cat > "$INSTALL_DIR/bin/sudo" <<'EOF'
#!/usr/bin/env bash
printf 'sudo %s\n' "$*" >> "$RUNLOG"
exec env PATH="$PATH" RUNLOG="$RUNLOG" SUDO_USER=testuser bash "$@"
EOF
    cat > "$INSTALL_DIR/bin/runuser" <<'EOF'
#!/usr/bin/env bash
# runuser -u <user> -- <cmd...>
printf 'runuser %s\n' "$*" >> "$RUNLOG"
shift 3
exec "$@"
EOF
    chmod +x "$INSTALL_DIR/bin/python3" "$INSTALL_DIR/bin/id" \
        "$INSTALL_DIR/bin/sudo" "$INSTALL_DIR/bin/runuser"

    RUNLOG="$INSTALL_DIR/run.log"
    run env PATH="$INSTALL_DIR/bin:$PATH" RUNLOG="$RUNLOG" bash "$INSTALL_DIR/install" --plain version

    [ "$status" -eq 0 ]
    # the heads-up block printed exactly once (only the first pass needs root)
    [ "$(grep -c "Vulcan needs root once" <<< "$output")" -eq 1 ]
    [[ "$(cat "$RUNLOG")" == *"sudo "*"install"*"--plain version"* ]]
    # Phase 0 was allowed to complete on the root pass: the final
    # `-m installer version` ran (via runuser -u testuser).
    [[ "$(cat "$RUNLOG")" == *"runuser -u testuser -- "*"-m installer --plain version"* ]]
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
