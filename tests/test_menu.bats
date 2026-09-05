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

# A complete `vulcan detect` block. menu.sh runs under `set -u`, so a
# stub that only echoes the two or three vars a given test cares about
# makes refresh_detect blow up on the first unstubbed reference. Tests
# pass "KEY='value'" args to override/extend; later lines win the eval.
_detect() {
    cat <<'DETECT'
CPU_CORES_LOGICAL='12'
CPU_MODEL='Test CPU'
RAM_TOTAL_GB='32.0'
DISK_FREE_GB='900.0'
GPU_VENDOR='intel'
DOCKER_INSTALLED='true'
DOCKER_RUNNING='true'
DOCKER_COMPOSE_V2='true'
OS_ID='fedora'
OS_PRETTY_NAME='Test Linux'
OS_IS_ATOMIC='false'
RECOMMENDED_TIER='medium'
RECOMMENDED_TIER_MEETS_MINIMUM='true'
RECOMMENDED_TIER_EXPLANATION='test'
BLANK_STORAGE_DEVICES=''
ALL_UNPROTECTED_DEVICES=''
STORAGE_MOUNT=''
STACK_EXISTS='false'
HAS_BACKUPS='false'
DEFAULT_PUID='1000'
DEFAULT_PGID='1000'
DEFAULT_TIMEZONE='UTC'
PREVIOUS_TIER=''
PREVIOUS_MEDIA_PATH=''
PREVIOUS_PUID=''
PREVIOUS_PGID=''
PREVIOUS_TIMEZONE=''
PREVIOUS_ENABLED_OPTIONAL=''
PREVIOUS_GPU_VENDOR=''
PREVIOUS_DOMAIN=''
PREVIOUS_CLOUDFLARE_DNS='false'
PREVIOUS_CLOUDFLARE_EMAIL=''
PREVIOUS_HOMEPAGE_PRIVATE='true'
PREVIOUS_DASHY_PRIVATE='true'
PREVIOUS_GENERATED_AT=''
DETECT
    printf '%s\n' "$@"
}
export -f _detect

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

@test "confirm_and_run exports VULCAN_PROGRESS=1 to the command" {

    whiptail() { return 0; }
    export -f whiptail

    run bash -c "source '$MENU_SH'; confirm_and_run 'Test' 'confirm text' env <<< ''"

    [ "$status" -eq 0 ]
    [[ "$output" == *"VULCAN_PROGRESS=1"* ]]
}

@test "VULCAN_PROGRESS is not exported into the menu loop itself" {

    whiptail() { return 0; }
    export -f whiptail

    run bash -c "source '$MENU_SH'; if [ -n \"\${VULCAN_PROGRESS:-}\" ]; then echo 'unexpectedly set'; else echo 'not set'; fi"

    [ "$status" -eq 0 ]
    [[ "$output" == *"not set"* ]]
}

@test "quick guided-setup select-all enables every optional service without showing the checklist" {

    whiptail() {
        case "$*" in
            *"Select All"*) return 0 ;;
            *"Optional Services"*"checklist"*) echo "CHECKLIST_SHOWN" >&2; return 0 ;;
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
    [[ "$output" != *"CHECKLIST_SHOWN"* ]]
    [[ "$output" == *"--vpn"* ]]
    [[ "$output" == *"--sabnzbd"* ]]
    [[ "$output" == *"--recyclarr"* ]]
    [[ "$output" == *"--homepage"* ]]
    [[ "$output" == *"--metube"* ]]
    [[ "$output" == *"--downtify"* ]]
    [[ "$output" == *"--netdata"* ]]
    [[ "$output" == *"--vaultwarden"* ]]
    [[ "$output" == *"--dashy"* ]]
}

@test "quick guided-setup toggles map checked services to their real CLI flags" {

    whiptail() {
        case "$*" in
            *"Select All"*) return 1 ;;
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
            *"Select All"*) return 1 ;;
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

@test "customize-services SERVICE_LIST covers every key in ALL_SERVICES" {

    # Drift guard: the bash-native service picker hardcodes its list;
    # ALL_SERVICES (tiers.py) is the real registry. Every key there must
    # be selectable in the TUI or that service is CLI-only by accident.
    keys=$(cd "$BATS_TEST_DIRNAME/.." && python -c "
from installer.tiers import ALL_SERVICES
print(' '.join(s.key for s in ALL_SERVICES))
")
    list=$(sed -n 's/^ *"\([a-z-]*\):.*/\1/p' "$MENU_SH" | tr '\n' ' ')

    for k in $keys; do
        [[ " $list " == *" $k "* ]] || { echo "missing from menu.sh SERVICE_LIST: $k"; false; }
    done
}

@test "customize-services shows a single checklist with every service labeled by category and pre-checked from the seed" {

    # Single-screen picker (replaces the old pick-a-category-first flow):
    # one whiptail --checklist call, every item's tag prefixed with its
    # tiers.py category, pre-checked from the core seed on a fresh run.
    export capture="$BATS_TEST_TMPDIR/checklist_args"
    whiptail() {
        case "$*" in
            *"Customize Services"*)
                printf '%s\n' "$@" > "$capture"
                echo -n '"jellyfin" "radarr" "sonarr" "prowlarr" "qbittorrent"' >&3
                return 0 ;;
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
    [[ "$output" == *"SERVICES:--services "* ]]
    for svc in jellyfin radarr sonarr prowlarr qbittorrent; do
        [[ "$output" == *"$svc"* ]]
    done
    [[ "$output" == *"DOMAIN:"* ]]
    [[ "$output" != *"--domain"* ]]

    # Exactly one checklist screen was shown (no category submenu), every
    # service is tagged with its category, and the core seed is the only
    # thing pre-checked ON. whiptail's argv is captured one word per
    # line (printf '%s\n' "$@") - join with "|" so each item's
    # tag/label/status triple can be matched as one substring.
    [ -f "$capture" ]
    joined=$(tr '\n' '|' < "$capture")
    [[ "$joined" == *'jellyfin|[Media Server] Jellyfin (media server)|ON|'* ]]
    [[ "$joined" == *'radarr|[Media Management] Radarr (movies)|ON|'* ]]
    [[ "$joined" == *'navidrome|[Media Server] Navidrome (music streaming)|OFF|'* ]]
    [[ "$joined" == *'seerr|[Media Server] Seerr (media requests)|OFF|'* ]]
    [[ "$joined" == *'traefik|[Infrastructure] Traefik (reverse proxy)|OFF|'* ]]
}

@test "customize-services builds --services from whatever the single checklist returns" {

    # --services list order is not deterministic (SELECTED_MAP is an
    # associative array), so assert membership, not a fixed order.
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
    [[ "$output" == *"SERVICES:--services "* ]]
    for svc in jellyfin radarr sonarr prowlarr qbittorrent; do
        [[ "$output" == *"$svc"* ]]
    done
    [[ "$output" == *"DOMAIN:"* ]]
    [[ "$output" != *"--domain"* ]]
}

@test "customize-services cancelling the checklist aborts without building a services list" {

    whiptail() {
        case "$*" in
            *"Customize Services"*) return 1 ;;   # Cancel/ESC
            *) return 0 ;;
        esac
    }
    export -f whiptail

    run bash -c "
        source '$MENU_SH'
        PREVIOUS_TIER=''
        PREVIOUS_ENABLED_OPTIONAL=''
        SERVICES_FLAG=()
        DOMAIN_FLAGS=()
        _guided_setup_customize_services
        echo \"STATUS:\$?\"
    "

    [[ "$output" == *"STATUS:1"* ]]
}

@test "customize-services asks for a domain and Cloudflare/Authelia details when traefik+authelia are chosen" {

    # One checklist call returns both traefik and authelia checked; the
    # domain / Cloudflare-DNS / Authelia follow-up prompts fire because
    # both are in the final list.
    whiptail() {
        case "$*" in
            *"Customize Services"*) echo -n '"traefik" "authelia"' >&3; return 0 ;;
            *"Base domain"*)      echo -n "media.example.com" >&3; return 0 ;;
            *"Contact email"*)    echo -n "me@example.com" >&3; return 0 ;;
            *"Cloudflare DNS"*)   return 0 ;;   # yesno: yes
            *"admin username"*)   echo -n "admin" >&3; return 0 ;;
            *"admin password"*)   echo -n "hunter2" >&3; return 0 ;;
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
    [[ "$output" == *"traefik"* ]]
    [[ "$output" == *"authelia"* ]]
    [[ "$output" == *"--domain media.example.com"* ]]
    [[ "$output" == *"--cloudflare-dns"* ]]
    [[ "$output" == *"--cloudflare-email me@example.com"* ]]
    [[ "$output" == *"--auth-username admin"* ]]
    [[ "$output" == *"--auth-password hunter2"* ]]
}

@test "main_menu exits cleanly (status 0) when Exit is chosen" {

    # main_menu() now calls refresh_detect on every redraw (see the
    # "Reset Media Storage" conditional item) - a bare $VULCAN_BIN
    # detect needs *something* real to run against here.
    fake_vulcan() {
        if [ "$1" = "detect" ]; then
            _detect "BLANK_STORAGE_DEVICES=''" "STORAGE_MOUNT=''"
        fi
    }
    export -f fake_vulcan

    whiptail() { echo -n "exit" >&3; return 0; }
    export -f whiptail

    run bash -c "VULCAN_BIN=fake_vulcan; export VULCAN_BIN; source '$MENU_SH'; main_menu"

    [ "$status" -eq 0 ]
}

@test "main_menu exits cleanly (status 0) on Cancel/ESC" {

    fake_vulcan() {
        if [ "$1" = "detect" ]; then
            _detect "BLANK_STORAGE_DEVICES=''" "STORAGE_MOUNT=''"
        fi
    }
    export -f fake_vulcan

    whiptail() { return 1; }
    export -f whiptail

    run bash -c "VULCAN_BIN=fake_vulcan; export VULCAN_BIN; source '$MENU_SH'; main_menu"

    [ "$status" -eq 0 ]
}

@test "menu.sh is valid bash syntax" {
    run bash -n "$MENU_SH"
    [ "$status" -eq 0 ]
}

@test "entry point runs Guided Setup directly, no Main Menu, when no stack exists" {

    fake_vulcan() {
        case "$*" in
            detect) _detect "STACK_EXISTS='false'" ;;
            *) return 0 ;;
        esac
    }
    export -f fake_vulcan

    whiptail() {
        echo "WHIPTAIL_CALL:$*" >&2
        # Decline immediately - just need to see which flow got entered.
        return 1
    }
    export -f whiptail

    run bash -c "VULCAN_BIN=fake_vulcan '$MENU_SH'"

    [[ "$output" == *"WHIPTAIL_CALL:"*"Welcome"* ]]
    [[ "$output" != *"WHIPTAIL_CALL:"*"Choose an action"* ]]
}

@test "entry point runs Main Menu, not Guided Setup, when a stack already exists" {

    fake_vulcan() {
        case "$*" in
            detect)
                _detect "STACK_EXISTS='true'" "BLANK_STORAGE_DEVICES=''" "STORAGE_MOUNT=''"
                ;;
            *) return 0 ;;
        esac
    }
    export -f fake_vulcan

    whiptail() {
        echo "WHIPTAIL_CALL:$*" >&2
        return 1
    }
    export -f whiptail

    run bash -c "VULCAN_BIN=fake_vulcan '$MENU_SH'"

    [ "$status" -eq 0 ]
    [[ "$output" != *"WHIPTAIL_CALL:"*"Welcome"* ]]
}

@test "storage setup shells out to 'vulcan storage apply' for the chosen blank devices" {

    vulcan_stub() {
        if [ "$1" = "detect" ]; then
            _detect "BLANK_STORAGE_DEVICES='/dev/sdb,/dev/sdc'" "ALL_UNPROTECTED_DEVICES='/dev/sdb,/dev/sdc'"
        else
            echo "vulcan $*"
        fi
    }
    export -f vulcan_stub

    whiptail() {
        case "$*" in
            *"Select drive"*) echo -n '"/dev/sdb" "/dev/sdc"' >&3; return 0 ;;
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
            _detect 
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
            _detect "BLANK_STORAGE_DEVICES='/dev/sdb,/dev/sdc'" "ALL_UNPROTECTED_DEVICES='/dev/sdb,/dev/sdc'"
        else
            echo "vulcan $*"
        fi
    }
    export -f vulcan_stub

    whiptail() {
        case "$*" in
            *"Select drive"*) echo -n '' >&3; return 0 ;;
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

@test "storage setup asks for a RAID level at 4+ devices and passes --raid-level" {

    vulcan_stub() {
        if [ "$1" = "detect" ]; then
            _detect "BLANK_STORAGE_DEVICES='/dev/sdb,/dev/sdc,/dev/sdd,/dev/sde'" "ALL_UNPROTECTED_DEVICES='/dev/sdb,/dev/sdc,/dev/sdd,/dev/sde'"
        else
            echo "vulcan $*"
        fi
    }
    export -f vulcan_stub

    whiptail() {
        case "$*" in
            *"Select drive"*) echo -n '"/dev/sdb" "/dev/sdc" "/dev/sdd" "/dev/sde"' >&3; return 0 ;;
            *"Mount point for the media storage volume"*) echo -n "/mnt/media" >&3; return 0 ;;
            *"Choose a RAID level"*) echo -n "6" >&3; return 0 ;;
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
    [[ "$output" == *"vulcan storage apply --devices /dev/sdb,/dev/sdc,/dev/sdd,/dev/sde --mount-point /mnt/media --non-interactive --yes --raid-level 6"* ]]
}

@test "storage setup offers a RAID0/RAID5 picker at 3 devices and passes the chosen level" {

    vulcan_stub() {
        if [ "$1" = "detect" ]; then
            _detect "BLANK_STORAGE_DEVICES='/dev/sdb,/dev/sdc,/dev/sdd'" "ALL_UNPROTECTED_DEVICES='/dev/sdb,/dev/sdc,/dev/sdd'"
        else
            echo "vulcan $*"
        fi
    }
    export -f vulcan_stub

    whiptail() {
        case "$*" in
            *"Select drive"*) echo -n '"/dev/sdb" "/dev/sdc" "/dev/sdd"' >&3; return 0 ;;
            *"Mount point for the media storage volume"*) echo -n "/mnt/media" >&3; return 0 ;;
            *"Choose a RAID level"*) echo "$*" >&1; echo -n "5" >&3; return 0 ;;
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
    [[ "$output" == *"RAID5"* ]]
    [[ "$output" == *"--raid-level 5"* ]]
    [[ "$output" != *"RAID6"* ]]   # 3 devices: no RAID6/RAID10 option
}

@test "storage setup offers a RAID0/RAID1 picker at 2 devices and passes the chosen level" {

    vulcan_stub() {
        if [ "$1" = "detect" ]; then
            _detect "BLANK_STORAGE_DEVICES='/dev/sdb,/dev/sdc'" "ALL_UNPROTECTED_DEVICES='/dev/sdb,/dev/sdc'"
        else
            echo "vulcan $*"
        fi
    }
    export -f vulcan_stub

    whiptail() {
        case "$*" in
            *"Select drive"*) echo -n '"/dev/sdb" "/dev/sdc"' >&3; return 0 ;;
            *"Mount point for the media storage volume"*) echo -n "/mnt/media" >&3; return 0 ;;
            *"Choose a RAID level"*) echo "$*" >&1; echo -n "1" >&3; return 0 ;;
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
    [[ "$output" == *"RAID1"* ]]
    [[ "$output" == *"--raid-level 1"* ]]
}

@test "storage teardown reports nothing to do when nothing is provisioned" {

    vulcan_stub() {
        if [ "$1" = "detect" ]; then
            _detect "STORAGE_MOUNT=''"
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
        storage_teardown_flow <<< ''
    "

    [ "$status" -eq 0 ]
    [[ "$output" != *"storage teardown"* ]]
}

@test "storage teardown mismatched typed confirmation runs nothing" {

    vulcan_stub() {
        if [ "$1" = "detect" ]; then
            _detect "STORAGE_MOUNT='/mnt/media'"
        else
            echo "vulcan $*"
        fi
    }
    export -f vulcan_stub

    whiptail() {
        case "$*" in
            *"Type the mount point to confirm"*) echo -n "/mnt/wrong" >&3; return 0 ;;
            *) return 0 ;;
        esac
    }
    export -f whiptail

    run bash -c "
        source '$MENU_SH'
        VULCAN_BIN='vulcan_stub'
        storage_teardown_flow <<< ''
    "

    [ "$status" -eq 0 ]
    [[ "$output" != *"storage teardown"* ]]
}

@test "storage teardown matched typed confirmation shells out to 'vulcan storage teardown'" {

    vulcan_stub() {
        if [ "$1" = "detect" ]; then
            _detect "STORAGE_MOUNT='/mnt/media'"
        else
            echo "vulcan $*"
        fi
    }
    export -f vulcan_stub

    whiptail() {
        case "$*" in
            *"Type the mount point to confirm"*) echo -n "/mnt/media" >&3; return 0 ;;
            *) return 0 ;;
        esac
    }
    export -f whiptail

    run bash -c "
        source '$MENU_SH'
        VULCAN_BIN='vulcan_stub'
        storage_teardown_flow <<< ''
    "

    [ "$status" -eq 0 ]
    [[ "$output" == *"vulcan storage teardown --mount-point /mnt/media --non-interactive --yes --confirm-wipe"* ]]
}

@test "main_menu renders the grouped top-level items in order" {

    fake_vulcan() {
        if [ "$1" = "detect" ]; then
            _detect
        fi
    }
    export -f fake_vulcan

    whiptail() {
        # `echo >&1` (not >&2): main_menu swaps fds via 3>&1 1>&2 2>&3,
        # so inside the command substitution fd1 is the *original*
        # stderr, and fd2 has been redirected to the captured output.
        echo "$*" >&1
        echo -n "exit" >&3
        return 0
    }
    export -f whiptail

    run bash -c "VULCAN_BIN=fake_vulcan; export VULCAN_BIN; source '$MENU_SH'; main_menu"

    [ "$status" -eq 0 ]
    [[ "$output" == *"Install → Complete, Guided, Storage"* ]]
    [[ "$output" == *"Configure → Services, Storage"* ]]
    [[ "$output" == *"Stack → Start, Status, Update, Pull, Backup, Restore"* ]]
    [[ "$output" == *"System → Update, Uninstall"* ]]

    first_install=$(echo "$output" | grep -b -o "Install → Complete" | head -1 | cut -d: -f1)
    first_stack=$(echo "$output" | grep -b -o "Stack → Start" | head -1 | cut -d: -f1)
    first_system=$(echo "$output" | grep -b -o "System → Update" | head -1 | cut -d: -f1)
    [ "$first_install" -lt "$first_stack" ]
    [ "$first_stack" -lt "$first_system" ]
}

@test "menu_configure lists Reset Media Storage and routes it to storage_teardown_flow" {

    FLAG="$BATS_TEST_TMPDIR/picked"

    fake_vulcan() { [ "$1" = "detect" ] && _detect "STORAGE_MOUNT='/mnt/media'"; }
    export -f fake_vulcan

    # First render: pick reset-storage. Every render after: cancel (return
    # 1) so menu_configure's `choice=$(...) || return` breaks the loop.
    # menu.sh's fd swap (3>&1 1>&2 2>&3) puts the rendered args on the
    # original stderr here - echo >&1.
    whiptail() {
        echo "MENU_ARGS:$*" >&1
        [ -f "$FLAG" ] && return 1
        touch "$FLAG"
        echo -n "reset-storage" >&3
        return 0
    }
    export -f whiptail
    export FLAG

    run bash -c "
        source '$MENU_SH'
        VULCAN_BIN=fake_vulcan
        storage_teardown_flow() { echo 'TEARDOWN_FLOW_CALLED'; }
        menu_configure
    "

    [ "$status" -eq 0 ]
    [[ "$output" == *"reset-storage"*"Reset Media Storage"* ]]
    [[ "$output" == *"TEARDOWN_FLOW_CALLED"* ]]
}

@test "guided-setup Setup Complete screen includes 'vulcan install-summary' output" {

    fake_vulcan() {
        case "$*" in
            detect)
                _detect "STORAGE_MOUNT=''" "PREVIOUS_TIER=''" "PREVIOUS_ENABLED_OPTIONAL=''" "RECOMMENDED_TIER='medium'" "CPU_CORES_LOGICAL='8'" "RAM_TOTAL_GB='32.0'" "DISK_FREE_GB='900.0'" "RECOMMENDED_TIER_EXPLANATION='test'" "DEFAULT_PUID='1000'" "DEFAULT_PGID='1000'" "DEFAULT_TIMEZONE='UTC'" "DOCKER_INSTALLED='true'" "DOCKER_RUNNING='true'"
            ;;
            install-summary)
                echo "EXAMPLE_INSTALL_SUMMARY_LINE"
                ;;
            *)
                return 0
                ;;
        esac
    }
    export -f fake_vulcan

    whiptail() {
        case "$*" in
            *"Media Library"*) echo -n "${@: -1}" >&3; return 0 ;;
            *"Customize the full service list"*) return 1 ;;
            *) echo "$*" >&1; return 0 ;;
        esac
    }
    export -f whiptail

    run bash -c "
        source '$MENU_SH'
        VULCAN_BIN=fake_vulcan
        guided_setup
    "

    [ "$status" -eq 0 ]
    [[ "$output" == *"EXAMPLE_INSTALL_SUMMARY_LINE"* ]]
}

@test "guided-setup defaults Media Library path to the provisioned storage mount" {

    # Full guided_setup run: VULCAN_BIN is stubbed with a fake detect
    # that reports a provisioned storage mount, and whiptail answers
    # the Media Library inputbox with whatever default it was offered
    # (so the captured MEDIA_PATH is exactly the default the flow
    # computed). The customize path is declined so the quick path runs,
    # and the final `--media-path` handed to the vulcan invocation is
    # what we assert on.
    fake_vulcan() {
        case "$*" in
            detect)
                _detect "STORAGE_MOUNT='/mnt/media'" "PREVIOUS_TIER=''" "PREVIOUS_ENABLED_OPTIONAL=''" "RECOMMENDED_TIER='medium'" "CPU_CORES_LOGICAL='8'" "RAM_TOTAL_GB='32.0'" "DISK_FREE_GB='900.0'" "RECOMMENDED_TIER_EXPLANATION='test'" "DEFAULT_PUID='1000'" "DEFAULT_PGID='1000'" "DEFAULT_TIMEZONE='UTC'" "DOCKER_INSTALLED='true'" "DOCKER_RUNNING='true'"
            ;;
            *)
                echo "VULCAN_INVOKED:$*"
                return 0
                ;;
        esac
    }
    export -f fake_vulcan

    whiptail() {
        case "$*" in
            *"Media Library"*)
                echo -n "${@: -1}" >&3
                return 0
                ;;
            *"Customize the full service list"*) return 1 ;;
            *) return 0 ;;
        esac
    }
    export -f whiptail

    run bash -c "
        source '$MENU_SH'
        VULCAN_BIN=fake_vulcan
        guided_setup
    "

    [ "$status" -eq 0 ]
    [[ "$output" == *"VULCAN_INVOKED:"* ]]
    [[ "$output" == *"--media-path /mnt/media"* ]]
}

@test "guided-setup falls back to HOME/media when no storage mount is provisioned" {

    fake_vulcan() {
        case "$*" in
            detect)
                _detect "STORAGE_MOUNT=''" "PREVIOUS_TIER=''" "PREVIOUS_ENABLED_OPTIONAL=''" "RECOMMENDED_TIER='medium'" "CPU_CORES_LOGICAL='8'" "RAM_TOTAL_GB='32.0'" "DISK_FREE_GB='900.0'" "RECOMMENDED_TIER_EXPLANATION='test'" "DEFAULT_PUID='1000'" "DEFAULT_PGID='1000'" "DEFAULT_TIMEZONE='UTC'" "DOCKER_INSTALLED='true'" "DOCKER_RUNNING='true'"
            ;;
            *)
                echo "VULCAN_INVOKED:$*"
                return 0
                ;;
        esac
    }
    export -f fake_vulcan

    whiptail() {
        case "$*" in
            *"Media Library"*)
                echo -n "${@: -1}" >&3
                return 0
                ;;
            *"Customize the full service list"*) return 1 ;;
            *) return 0 ;;
        esac
    }
    export -f whiptail

    run bash -c "
        source '$MENU_SH'
        VULCAN_BIN=fake_vulcan
        HOME=/home/testuser
        guided_setup
    "

    [ "$status" -eq 0 ]
    [[ "$output" == *"--media-path /home/testuser/media"* ]]
}

@test "guided-setup still defaults Media Library path to the previous install's path on a rerun" {

    fake_vulcan() {
        case "$*" in
            detect)
                _detect "STORAGE_MOUNT='/mnt/media'" "PREVIOUS_TIER='medium'" "PREVIOUS_MEDIA_PATH='/mnt/old-media'" "PREVIOUS_PUID='1000'" "PREVIOUS_PGID='1000'" "PREVIOUS_TIMEZONE='UTC'" "PREVIOUS_ENABLED_OPTIONAL=''" "RECOMMENDED_TIER='medium'" "CPU_CORES_LOGICAL='8'" "RAM_TOTAL_GB='32.0'" "DISK_FREE_GB='900.0'" "RECOMMENDED_TIER_EXPLANATION='test'" "DEFAULT_PUID='1000'" "DEFAULT_PGID='1000'" "DEFAULT_TIMEZONE='UTC'" "DOCKER_INSTALLED='true'" "DOCKER_RUNNING='true'"
            ;;
            *)
                echo "VULCAN_INVOKED:$*"
                return 0
                ;;
        esac
    }
    export -f fake_vulcan

    whiptail() {
        case "$*" in
            *"Media Library"*)
                echo -n "${@: -1}" >&3
                return 0
                ;;
            *"Customize the full service list"*) return 1 ;;
            *) return 0 ;;
        esac
    }
    export -f whiptail

    run bash -c "
        source '$MENU_SH'
        VULCAN_BIN=fake_vulcan
        guided_setup
    "

    [ "$status" -eq 0 ]
    [[ "$output" == *"--media-path /mnt/old-media"* ]]
}

@test "guided_setup calls vulcan build then configure then start, no docker msgbox" {

    export VULCAN_CALLS="$BATS_TMPDIR/vcalls-$$"; : > "$VULCAN_CALLS"
    export SETUP_LOG="$BATS_TMPDIR/setup-$$.log"

    fake_vulcan() {
        case "$1" in
            detect)
                _detect "ALL_UNPROTECTED_DEVICES=''" "STORAGE_MOUNT=''" "PREVIOUS_TIER=''" "PREVIOUS_ENABLED_OPTIONAL=''" "RECOMMENDED_TIER='medium'" "CPU_CORES_LOGICAL='8'" "RAM_TOTAL_GB='32.0'" "DISK_FREE_GB='900.0'" "RECOMMENDED_TIER_EXPLANATION='test'" "DEFAULT_PUID='1000'" "DEFAULT_PGID='1000'" "DEFAULT_TIMEZONE='UTC'" "GPU_VENDOR=''" "DOCKER_INSTALLED='true'" "DOCKER_RUNNING='true'"
            ;;
            *) printf '%s\n' "$*" >> "$VULCAN_CALLS"; return 0 ;;
        esac
    }
    export -f fake_vulcan

    whiptail() {
        case "$*" in
            *"Docker isn't fully ready"*) echo "DOCKER MSGBOX SHOWN" >&2; return 0 ;;
            *"Media Library"*) echo -n "${@: -1}" >&3; return 0 ;;
            *"Customize the full service list"*) return 1 ;;
            *) return 0 ;;
        esac
    }
    export -f whiptail

    run bash -c "source '$MENU_SH'; VULCAN_BIN=fake_vulcan; guided_setup"

    [ "$status" -eq 0 ]
    grep -q '^build ' "$VULCAN_CALLS"
    grep -q '^configure' "$VULCAN_CALLS"
    grep -q '^start' "$VULCAN_CALLS"
    ! grep -q "DOCKER MSGBOX SHOWN" <<< "$output"
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
        RAM_TOTAL_GB DISK_FREE_GB GPU_VENDOR STORAGE_MOUNT; do

        grep -q "\"$var\":" "$cli_py" || {
            echo "menu.sh references \$$var but detect_shell() never emits it" >&2
            return 1
        }
    done
}

@test "_dlg_menu_items list-height leaves room for the box chrome (no title/border overflow)" {
    # Regression: _dlg_menu_items returned ~45% of the raw terminal
    # height while the box (_dlg_rows) is ~60% of it, so on any terminal
    # shorter than ~53 lines the list overflowed the top border - no
    # visible title, and a menu selection silently bounced back.
    source "$MENU_SH"

    for term in 20 24 30 40 50 80; do
        tput() { [ "$1" = "lines" ] && echo "$term" || echo 80; }
        export -f tput
        rows=$(_dlg_rows)
        items=$(_dlg_menu_items)
        # whiptail needs list-height <= box-height - 8 (title/border/msg/buttons)
        [ "$items" -le $(( rows - 8 )) ] || {
            echo "term=$term rows=$rows items=$items -> overflows box by $(( items - (rows - 8) ))"
            return 1
        }
        [ "$items" -ge 3 ]
    done
}
