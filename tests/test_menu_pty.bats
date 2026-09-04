#!/usr/bin/env bats
#
# Real-terminal rendering/navigation tests for installer/menu.sh.
#
# tests/test_menu.bats mocks the `whiptail` binary with a shell
# function returning scripted answers - it exercises the argv-building
# logic but never the real newt widget painting a real screen or
# real keystrokes moving a real selection. This file closes that gap
# (the "no Pilot-equivalent for whiptail" item in ROADMAP.md's Next
# list): it runs the unmodified menu.sh with the real whiptail binary
# inside a real pty (tmux), sends real keys, and asserts on the frame
# tmux captures back.
#
# Anchors are the boxed window titles (`┤ Vulcan ├`, `┤ Install ├`, ...)
# and the visible menu-item descriptions - newt does NOT reliably paint
# the `--menu` prompt-text argument into a capturable cell, so tests
# never key off that.
#
# VULCAN_BIN is stubbed to a function that shells out to the real
# `vulcan detect` (read-only) and force-sets STACK_EXISTS, so no real
# stack / Docker / privileged operation is ever touched - only the
# dialog layer is under test.

setup() {
    command -v tmux >/dev/null || skip "tmux not installed"
    command -v whiptail >/dev/null || skip "whiptail not installed"

    REPO="$(cd "$BATS_TEST_DIRNAME/.." && pwd)"
    VULCAN="$REPO/.venv/bin/vulcan"
    [ -x "$VULCAN" ] || VULCAN="$(command -v vulcan)" || skip "vulcan CLI not found (run ./install or pip install -e .)"

    # Per-test named socket + session so parallel/re-run bats never collide.
    SOCK="vpty_${BATS_SUITE_TEST_NUMBER:-$$}"
    LAUNCHER="$BATS_TEST_TMPDIR/launch.sh"
}

teardown() {
    [ -n "${SOCK:-}" ] && tmux -L "$SOCK" kill-server 2>/dev/null || true
}

# Write the menu.sh launcher. $1 = value to force STACK_EXISTS to
# ("true" -> Main Menu, "false" -> first-run Guided Setup).
make_launcher() {
    cat > "$LAUNCHER" <<EOF
#!/usr/bin/env bash
export TERM=xterm-256color
vulcan_stub() {
    case "\$1" in
        detect) "$VULCAN" detect; echo "STACK_EXISTS='$1'" ;;
        *) : ;;
    esac
}
export -f vulcan_stub
export VULCAN_BIN=vulcan_stub
cd "$REPO"
exec bash "$REPO/installer/menu.sh"
EOF
    chmod +x "$LAUNCHER"
}

# Launch menu.sh in a detached 200x50 pty. After the script exits the
# pane prints MENU_EXIT_<rc> and idles, so a test can assert on the
# exit status too.
start_menu() {
    make_launcher "${1:-true}"
    tmux -L "$SOCK" new-session -d -s m -x 200 -y 50 \
        "bash '$LAUNCHER'; printf 'MENU_EXIT_%s' \$?; exec sleep 300"
}

pane() { tmux -L "$SOCK" capture-pane -pt m 2>/dev/null; }
keys() { tmux -L "$SOCK" send-keys -t m "$@"; }

# Busy-poll the captured frame until $1 appears, or $2 (default 15) seconds pass.
# ponytail: busy-wait, no sleep dependency; fine for a handful of short tests.
wait_for() {
    local pat="$1" deadline=$(( SECONDS + ${2:-15} ))
    while (( SECONDS < deadline )); do
        pane | grep -qF "$pat" && return 0
    done
    echo "TIMEOUT waiting for: $pat" >&2
    pane >&2
    return 1
}

@test "Main Menu renders in a real pty with the real whiptail binary" {
    start_menu true
    wait_for "┤ Vulcan ├"

    run pane
    [[ "$output" == *"Vulcan - Media Stack Forge"* ]]          # backtitle
    [[ "$output" == *"Install → Complete, Guided, Storage"* ]]
    [[ "$output" == *"Stack → Start, Status, Update, Pull, Backup, Restore"* ]]
    [[ "$output" == *"exit"*"Exit"* ]]
    [[ "$output" == *"Cancel"* ]]                              # --fullbuttons boxed button
}

@test "arrow-key navigation + Enter moves Main Menu -> Configure submenu" {
    start_menu true
    wait_for "┤ Vulcan ├"

    keys Down Enter
    wait_for "┤ Configure ├"

    run pane
    [[ "$output" == *"Configure Credentials → VPN, domain, tunnel token, passwords"* ]]
}

@test "first-letter jump + Enter opens the Install submenu" {
    start_menu true
    wait_for "┤ Vulcan ├"

    keys i Enter
    wait_for "┤ Install ├"

    run pane
    [[ "$output" == *"Complete Setup (recommended)"* ]]
    [[ "$output" == *"Guided Setup → detect hardware"* ]]
}

@test "the Back item returns from a submenu to the Main Menu" {
    start_menu true
    wait_for "┤ Vulcan ├"
    keys i Enter
    wait_for "┤ Install ├"

    keys b Enter
    wait_for "┤ Vulcan ├"

    run pane
    [[ "$output" == *"Install → Complete, Guided, Storage"* ]]  # back on the Main Menu
    [[ "$output" != *"┤ Install ├"* ]]
}

# ESC-key cancel returning exit 0 is covered by tests/test_menu.bats's
# mocked "main_menu exits cleanly ... on Cancel/ESC" - a lone ESC into
# real newt is timer/terminal-sensitive (SLang escape-sequence
# disambiguation) and not a menu.sh behaviour, so it's not re-tested here.

@test "the Exit item terminates the menu with status 0" {
    start_menu true
    wait_for "┤ Vulcan ├"

    keys e Enter
    wait_for "MENU_EXIT_0"
}

@test "first run (no stack) drops straight into the Welcome / Guided screen" {
    start_menu false
    wait_for "┤ Welcome ├"

    run pane
    [[ "$output" == *"Welcome to the Vulcan Setup!"* ]]
    [[ "$output" == *"Arrow keys to move around"* ]]
    [[ "$output" != *"┤ Vulcan ├"* ]]     # Main Menu is skipped on first run
}
