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

@test "storage setup asks for a RAID level at 4+ devices and passes --raid-level" {

    vulcan_stub() {
        if [ "$1" = "detect" ]; then
            echo "BLANK_STORAGE_DEVICES='/dev/sdb,/dev/sdc,/dev/sdd,/dev/sde'"
        else
            echo "vulcan $*"
        fi
    }
    export -f vulcan_stub

    whiptail() {
        case "$*" in
            *"Select which blank device"*) echo -n '"/dev/sdb" "/dev/sdc" "/dev/sdd" "/dev/sde"' >&3; return 0 ;;
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

@test "storage setup does not show the RAID picker at 3 devices (RAID5 is the only choice)" {

    vulcan_stub() {
        if [ "$1" = "detect" ]; then
            echo "BLANK_STORAGE_DEVICES='/dev/sdb,/dev/sdc,/dev/sdd'"
        else
            echo "vulcan $*"
        fi
    }
    export -f vulcan_stub

    whiptail() {
        case "$*" in
            *"Select which blank device"*) echo -n '"/dev/sdb" "/dev/sdc" "/dev/sdd"' >&3; return 0 ;;
            *"Mount point for the media storage volume"*) echo -n "/mnt/media" >&3; return 0 ;;
            # The confirm text is a whiptail --yesno arg, not stdout -
            # echo it so the test can assert the level summary it carries.
            *"--yesno"*) echo "$*" >&1; return 0 ;;
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
    [[ "$output" != *"--raid-level"* ]]
}

@test "storage setup at 2 devices passes no --raid-level (engine defaults to RAID1)" {

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
            *"--yesno"*) echo "$*" >&1; return 0 ;;
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
    [[ "$output" != *"--raid-level"* ]]
}

@test "main_menu is numbered with install-path items first" {

    whiptail() {
        # `echo >&1` (not >&2): main_menu swaps fds via 3>&1 1>&2 2>&3,
        # so inside the command substitution fd1 is the *original*
        # stderr, and fd2 has been redirected to the captured output -
        # a `>&2` here would leak into CHOICE and never match "exit".
        echo "$*" >&1
        echo -n "exit" >&3
        return 0
    }
    export -f whiptail

    run bash -c "source '$MENU_SH'; main_menu"

    [ "$status" -eq 0 ]
    # Full rendered menu text (dialog args joined with spaces), asserting
    # order: Guided Setup and Storage Setup (the new-install path) come
    # before the maintenance items, and every item is numbered.
    [[ "$output" == *"1. Guided Setup"* ]]
    [[ "$output" == *"2. Media Storage Setup"* ]]
    [[ "$output" == *"3. Update Stack"* ]]
    [[ "$output" == *"4. Pull Images"* ]]
    [[ "$output" == *"5. Backup Stack"* ]]
    [[ "$output" == *"6. Restore Stack"* ]]
    [[ "$output" == *"7. Uninstall Stack"* ]]
    [[ "$output" == *"8. Update Vulcan"* ]]
    [[ "$output" == *"0. Exit"* ]]

    first_guided=$(echo "$output" | grep -b -o "1. Guided Setup" | cut -d: -f1)
    first_storage=$(echo "$output" | grep -b -o "2. Media Storage Setup" | cut -d: -f1)
    first_update=$(echo "$output" | grep -b -o "3. Update Stack" | cut -d: -f1)
    [ "$first_guided" -lt "$first_storage" ]
    [ "$first_storage" -lt "$first_update" ]
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
                echo "STORAGE_MOUNT='/mnt/media'"
                echo "PREVIOUS_TIER=''"
                echo "PREVIOUS_ENABLED_OPTIONAL=''"
                echo "RECOMMENDED_TIER='medium'"
                echo "CPU_CORES_LOGICAL='8'"
                echo "RAM_TOTAL_GB='32.0'"
                echo "DISK_FREE_GB='900.0'"
                echo "RECOMMENDED_TIER_EXPLANATION='test'"
                echo "DEFAULT_PUID='1000'"
                echo "DEFAULT_PGID='1000'"
                echo "DEFAULT_TIMEZONE='UTC'"
                echo "DOCKER_INSTALLED='true'"
                echo "DOCKER_RUNNING='true'"
                echo "DOCKER_COMPOSE_V2='true'"
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
                echo "STORAGE_MOUNT=''"
                echo "PREVIOUS_TIER=''"
                echo "PREVIOUS_ENABLED_OPTIONAL=''"
                echo "RECOMMENDED_TIER='medium'"
                echo "CPU_CORES_LOGICAL='8'"
                echo "RAM_TOTAL_GB='32.0'"
                echo "DISK_FREE_GB='900.0'"
                echo "RECOMMENDED_TIER_EXPLANATION='test'"
                echo "DEFAULT_PUID='1000'"
                echo "DEFAULT_PGID='1000'"
                echo "DEFAULT_TIMEZONE='UTC'"
                echo "DOCKER_INSTALLED='true'"
                echo "DOCKER_RUNNING='true'"
                echo "DOCKER_COMPOSE_V2='true'"
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
                echo "STORAGE_MOUNT='/mnt/media'"
                echo "PREVIOUS_TIER='medium'"
                echo "PREVIOUS_MEDIA_PATH='/mnt/old-media'"
                echo "PREVIOUS_PUID='1000'"
                echo "PREVIOUS_PGID='1000'"
                echo "PREVIOUS_TIMEZONE='UTC'"
                echo "PREVIOUS_ENABLED_OPTIONAL=''"
                echo "RECOMMENDED_TIER='medium'"
                echo "CPU_CORES_LOGICAL='8'"
                echo "RAM_TOTAL_GB='32.0'"
                echo "DISK_FREE_GB='900.0'"
                echo "RECOMMENDED_TIER_EXPLANATION='test'"
                echo "DEFAULT_PUID='1000'"
                echo "DEFAULT_PGID='1000'"
                echo "DEFAULT_TIMEZONE='UTC'"
                echo "DOCKER_INSTALLED='true'"
                echo "DOCKER_RUNNING='true'"
                echo "DOCKER_COMPOSE_V2='true'"
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
