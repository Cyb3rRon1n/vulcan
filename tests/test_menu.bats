#!/usr/bin/env bats
#
# Unit tests for installer/menu.sh's testable logic - argv-building
# functions and confirm_and_run's two outcomes. Real interactive
# whiptail dialog rendering/navigation isn't automatable (no
# Pilot-equivalent tool exists for whiptail) - see CLAUDE.md/
# ROADMAP.md for the real-terminal verification this is bounded by.
# Each test replaces the `whiptail` binary with a shell function
# (bats' `run` executes in a subshell, so `export -f` makes it visible
# there) returning fixed, scripted answers - the bash equivalent of
# mocking a widget's return value in the old Textual test suite.

setup() {
    MENU_SH="$BATS_TEST_DIRNAME/../installer/menu.sh"
}

@test "confirm_and_run executes the command and reports success when confirmed" {

    whiptail() { return 0; }
    export -f whiptail

    run bash -c "source '$MENU_SH'; confirm_and_run 'Test' 'confirm text' echo 'hello world' <<< ''"

    [ "$status" -eq 0 ]
    [[ "$output" == *"hello world"* ]]
    [[ "$output" == *"Done."* ]]
}

@test "confirm_and_run does not run the command when declined" {

    whiptail() { return 1; }
    export -f whiptail

    run bash -c "source '$MENU_SH'; confirm_and_run 'Test' 'confirm text' echo 'should not run'"

    [ "$status" -eq 130 ]
    [[ "$output" != *"should not run"* ]]
}

@test "confirm_and_run reports failure and propagates a non-zero exit code" {

    whiptail() { return 0; }
    export -f whiptail

    run bash -c "source '$MENU_SH'; confirm_and_run 'Test' 'confirm text' bash -c 'exit 3' <<< ''"

    [ "$status" -eq 3 ]
    [[ "$output" == *"Failed (exit 3)"* ]]
}

@test "quick guided-setup toggles map checked services to their real CLI flags" {

    whiptail() {
        case "$*" in
            *"Optional Services"*) echo -n '"gluetun" "homepage" "netdata"' >&3; return 0 ;;
            *) return 0 ;;
        esac
    }
    export -f whiptail

    run bash -c "
        source '$MENU_SH'
        PREVIOUS_TIER=''
        PREVIOUS_ENABLED_OPTIONAL=''
        TIER='medium'
        GPU_VENDOR=''
        TOGGLE_FLAGS=()
        _guided_setup_quick_toggles
        echo \"\${TOGGLE_FLAGS[*]}\"
    "

    [ "$status" -eq 0 ]
    [[ "$output" == *"--vpn"* ]]
    [[ "$output" == *"--homepage"* ]]
    [[ "$output" == *"--netdata"* ]]
    [[ "$output" == *"--no-sabnzbd"* ]]
    [[ "$output" == *"--no-recyclarr"* ]]
    [[ "$output" == *"--no-metube"* ]]
    [[ "$output" == *"--no-downtify"* ]]
    [[ "$output" == *"--no-vaultwarden"* ]]
    [[ "$output" == *"--no-dashy"* ]]
}

@test "quick guided-setup asks about GPU passthrough only at heavy tier with a detected GPU" {

    whiptail() {
        case "$*" in
            *"Optional Services"*) echo -n '' >&3; return 0 ;;
            *"GPU Passthrough"*) echo "GPU_PROMPT_SHOWN" >&2; return 0 ;;
            *) return 0 ;;
        esac
    }
    export -f whiptail

    run bash -c "
        source '$MENU_SH'
        PREVIOUS_TIER=''
        PREVIOUS_ENABLED_OPTIONAL=''
        TIER='medium'
        GPU_VENDOR='nvidia'
        TOGGLE_FLAGS=()
        _guided_setup_quick_toggles
    "

    [[ "$output" != *"GPU_PROMPT_SHOWN"* ]]

    run bash -c "
        source '$MENU_SH'
        PREVIOUS_TIER=''
        PREVIOUS_ENABLED_OPTIONAL=''
        TIER='heavy'
        GPU_VENDOR='nvidia'
        TOGGLE_FLAGS=()
        _guided_setup_quick_toggles
        echo \"\${TOGGLE_FLAGS[*]}\"
    "

    [[ "$output" == *"--gpu"* ]]
}

@test "customize-services builds --services and skips domain flags without traefik" {

    whiptail() {
        case "$*" in
            *"Customize Services"*) echo -n '"jellyfin" "radarr" "sonarr" "prowlarr" "qbittorrent"' >&3; return 0 ;;
            *) return 0 ;;
        esac
    }
    export -f whiptail

    run bash -c "
        source '$MENU_SH'
        PREVIOUS_TIER=''
        PREVIOUS_ENABLED_OPTIONAL=''
        PREVIOUS_DOMAIN=''
        PREVIOUS_CLOUDFLARE_EMAIL=''
        SERVICES_FLAG=()
        DOMAIN_FLAGS=()
        _guided_setup_customize_services
        echo \"SERVICES:\${SERVICES_FLAG[*]}\"
        echo \"DOMAIN:\${DOMAIN_FLAGS[*]}\"
    "

    [ "$status" -eq 0 ]
    [[ "$output" == *"SERVICES:--services jellyfin,radarr,sonarr,prowlarr,qbittorrent"* ]]
    [[ "$output" == *"DOMAIN:"* ]]
    [[ "$output" != *"--domain"* ]]
}

@test "customize-services asks for a domain and Cloudflare/Authelia details when traefik+authelia are chosen" {

    whiptail() {
        # More specific patterns first - the Cloudflare email inputbox's
        # own --title also contains "Cloudflare", so a bare *"Cloudflare"*
        # pattern would wrongly intercept it before reaching
        # *"Contact email"* if it came first (found live while writing
        # this test - a real ordering trap, not hypothetical).
        case "$*" in
            *"Customize Services"*)
                echo -n '"jellyfin" "traefik" "authelia"' >&3; return 0 ;;
            *"Base domain"*)
                echo -n "media.example.com" >&3; return 0 ;;
            *"Contact email"*)
                echo -n "me@example.com" >&3; return 0 ;;
            *"Cloudflare"*)
                return 0 ;;
            *"admin username"*)
                echo -n "admin" >&3; return 0 ;;
            *"admin password"*)
                echo -n "hunter2" >&3; return 0 ;;
            *) return 0 ;;
        esac
    }
    export -f whiptail

    run bash -c "
        source '$MENU_SH'
        PREVIOUS_TIER=''
        PREVIOUS_ENABLED_OPTIONAL=''
        PREVIOUS_DOMAIN=''
        PREVIOUS_CLOUDFLARE_EMAIL=''
        SERVICES_FLAG=()
        DOMAIN_FLAGS=()
        _guided_setup_customize_services
        echo \"SERVICES:\${SERVICES_FLAG[*]}\"
        echo \"DOMAIN:\${DOMAIN_FLAGS[*]}\"
    "

    [ "$status" -eq 0 ]
    [[ "$output" == *"--services jellyfin,traefik,authelia"* ]]
    [[ "$output" == *"--domain media.example.com"* ]]
    [[ "$output" == *"--cloudflare-dns"* ]]
    [[ "$output" == *"--cloudflare-email me@example.com"* ]]
    [[ "$output" == *"--auth-username admin"* ]]
    [[ "$output" == *"--auth-password hunter2"* ]]
}

@test "main_menu exits cleanly (status 0) when Exit is chosen" {

    whiptail() { echo -n "exit" >&3; return 0; }
    export -f whiptail

    run bash -c "source '$MENU_SH'; main_menu"

    [ "$status" -eq 0 ]
}

@test "main_menu exits cleanly (status 0) on Cancel/ESC" {

    whiptail() { return 1; }
    export -f whiptail

    run bash -c "source '$MENU_SH'; main_menu"

    [ "$status" -eq 0 ]
}

@test "menu.sh is valid bash syntax" {
    run bash -n "$MENU_SH"
    [ "$status" -eq 0 ]
}

@test "storage setup shells out to 'vulcan storage apply' for the chosen blank devices" {

    vulcan_stub() {
        if [ "$1" = "detect" ]; then
            echo "BLANK_STORAGE_DEVICES='/dev/sdb,/dev/sdc'"
        else
            echo "vulcan $*"
        fi
    }
    export -f vulcan_stub

    whiptail() {
        case "$*" in
            *"Select which blank device"*) echo -n '"/dev/sdb" "/dev/sdc"' >&3; return 0 ;;
            *"Mount point for the media storage volume"*) echo -n "/mnt/media" >&3; return 0 ;;
            *) return 0 ;;
        esac
    }
    export -f whiptail

    run bash -c "
        source '$MENU_SH'
        VULCAN_BIN='vulcan_stub'
        storage_setup_flow <<< ''
    "

    [ "$status" -eq 0 ]
    [[ "$output" == *"vulcan storage apply --devices /dev/sdb,/dev/sdc --mount-point /mnt/media --non-interactive --yes"* ]]
}

@test "storage setup reports when no blank devices exist and runs nothing" {

    vulcan_stub() {
        if [ "$1" = "detect" ]; then
            echo "BLANK_STORAGE_DEVICES=''"
        else
            echo "vulcan $*"
        fi
    }
    export -f vulcan_stub

    whiptail() { return 0; }
    export -f whiptail

    run bash -c "
        source '$MENU_SH'
        VULCAN_BIN='vulcan_stub'
        storage_setup_flow <<< ''
    "

    [ "$status" -eq 0 ]
    [[ "$output" != *"storage apply"* ]]
}

@test "storage setup does not run apply when no devices are selected" {

    vulcan_stub() {
        if [ "$1" = "detect" ]; then
            echo "BLANK_STORAGE_DEVICES='/dev/sdb,/dev/sdc'"
        else
            echo "vulcan $*"
        fi
    }
    export -f vulcan_stub

    whiptail() {
        case "$*" in
            *"Select storage devices"*) echo -n '' >&3; return 0 ;;
            *) return 0 ;;
        esac
    }
    export -f whiptail

    run bash -c "
        source '$MENU_SH'
        VULCAN_BIN='vulcan_stub'
        storage_setup_flow <<< ''
    "

    [ "$status" -eq 0 ]
    [[ "$output" != *"storage apply"* ]]
}

@test "every field menu.sh references from 'vulcan detect' is actually emitted by it" {

    cli_py="$BATS_TEST_DIRNAME/../installer/cli.py"

    # Every $UPPER_CASE var menu.sh reads that looks like a detect
    # field (by convention: no local lowercase vars share this naming
    # shape) must appear as a dict key in detect_shell()'s fields{}.
    for var in DOCKER_INSTALLED DOCKER_RUNNING DOCKER_COMPOSE_V2 \
        RECOMMENDED_TIER RECOMMENDED_TIER_EXPLANATION PREVIOUS_TIER \
        PREVIOUS_MEDIA_PATH PREVIOUS_PUID PREVIOUS_PGID PREVIOUS_TIMEZONE \
        PREVIOUS_ENABLED_OPTIONAL PREVIOUS_DOMAIN PREVIOUS_CLOUDFLARE_EMAIL \
        DEFAULT_PUID DEFAULT_PGID DEFAULT_TIMEZONE CPU_CORES_LOGICAL \
        RAM_TOTAL_GB DISK_FREE_GB GPU_VENDOR; do

        grep -q "\"$var\":" "$cli_py" || {
            echo "menu.sh references \$$var but detect_shell() never emits it" >&2
            return 1
        }
    done
}
