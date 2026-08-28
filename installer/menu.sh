#!/usr/bin/env bash
#
# Vulcan's whiptail-driven installer front end - a real bash+whiptail
# Main Menu, DockSTARTer-style, replacing the old Python/Textual TUI
# (see CLAUDE.md/ROADMAP.md for why). Every choice gathered here is
# handed to the `vulcan` CLI, which already has a full
# --non-interactive --yes flag surface for every command - no
# detection, generation, or validation logic is duplicated here, only
# dialog plumbing and argv-building.
#
# Entry point: `vulcan` with no flags (installer/cli.py's main()
# execs this script instead of importing installer.tui). Can also be
# run directly for development: ./installer/menu.sh

set -uo pipefail

VULCAN_BIN="${VULCAN_BIN:-vulcan}"
BACKTITLE="Vulcan - Media Stack Forge"

# --- Theme ---------------------------------------------------------
#
# whiptail/newt only supports a fixed set of named colors (no
# arbitrary hex). Vulcan brand: red window background, black-on-red
# border, white text on black for labels/entries/listboxes, yellow
# for focused states.
export NEWT_COLORS='
root=white,black
border=black,red
window=white,red
shadow=black,black
title=yellow,red
button=white,red
actbutton=black,yellow
checkbox=black,red
actcheckbox=black,yellow
entry=black,red
label=black,red
listbox=black,red
actlistbox=black,yellow
sellistbox=black,red
actsellistbox=black,yellow
textbox=black,red
acttextbox=black,red
helpline=white,black
roottext=white,black
emptyscale=,black
fullscale=,red
disabledentry=gray,red
compactbutton=white,red
'

# whiptail defaults to "compact" Yes/No/OK/Cancel buttons - plain
# "<Yes>"/"<No>" text with no focused-state color of their own (there's
# no actcompactbutton in newt's colorset list, only actbutton/actcheckbox/
# actlistbox/etc. for other widgets) - so no matter what button/actbutton
# above are set to, Tab/arrow-key focus between Yes and No was never
# visible. --fullbuttons renders real boxed buttons that DO use
# button/actbutton, restoring a visible focus indicator.
#
# Only define this if nothing already has - tests/test_menu.bats
# exports its own `whiptail` mock function (real dialogs can't run
# without a terminal) to intercept every call in this script; an
# unconditional definition here would silently override that mock
# with the real binary instead, and every test relying on the mock's
# recorded output would break. Confirmed live: it did, until this
# guard was added.
if ! declare -F whiptail >/dev/null; then
    whiptail() {
        command whiptail --fullbuttons "$@"
    }
fi

# --- Auto-sizing helpers ---------------------------------------------
#
# Every dialog uses terminal-relative dimensions instead of hardcoded
# values, so the UI fills the available screen space at any terminal
# size. _dlg_rows / _dlg_cols return the usable dialog height/width
# (80% of terminal, clamped to sane minimums). _dlg_menu_items returns
# the visible-items count for --menu/--checklist/--radiolist (60% of
# terminal rows, minimum 5).

_dlg_rows() {
    local total
    total=$(tput lines 2>/dev/null || echo 24)
    local rows=$(( total * 60 / 100 ))
    [ "$rows" -lt 10 ] && rows=10
    echo "$rows"
}

_dlg_cols() {
    local total
    total=$(tput cols 2>/dev/null || echo 80)
    local cols=$(( total * 60 / 100 ))
    [ "$cols" -lt 60 ] && cols=60
    echo "$cols"
}

_dlg_menu_items() {
    local total
    total=$(tput lines 2>/dev/null || echo 24)
    local items=$(( total * 45 / 100 ))
    [ "$items" -lt 5 ] && items=5
    echo "$items"
}

# Compute once at startup, use everywhere
DLG_ROWS=$(_dlg_rows)
DLG_COLS=$(_dlg_cols)
DLG_ITEMS=$(_dlg_menu_items)

# --- Structured logging (Security Onion pattern) --------------------
#
# Every setup step is logged to $SETUP_LOG with timestamps and levels.
# In interactive mode the log is silent; on failure it's shown to the user.

SETUP_LOG="${SETUP_LOG:-/tmp/vulcan-setup.log}"

log() {
    local msg="$1" level="${2:-INFO}"
    local now
    now=$(date +"%Y-%m-%dT%H:%M:%S%z")
    echo "$now | $level | $msg" >> "$SETUP_LOG" 2>&1
}

log_info()  { log "$1" "INFO"; }
log_error() { log "$1" "ERROR"; }

# Writes a section header to the log (visible in the log file, not on screen).
log_title() {
    echo -e "\n-----------------------------\n $1\n-----------------------------\n" >> "$SETUP_LOG" 2>&1
}

# --- Small helpers ---------------------------------------------------

# Reads real detected state into the current shell as plain vars
# (CPU_CORES_LOGICAL, RECOMMENDED_TIER, PREVIOUS_TIER, ...) - see
# `vulcan detect --help` / installer/cli.py's detect_shell() for the
# full field list. Called fresh every time the Main Menu redraws, so
# it always reflects real current state (e.g. right after a stack was
# just generated or torn down).
refresh_detect() {
    eval "$("$VULCAN_BIN" detect)"
}

# whiptail --yesno confirm, then run the given command with real,
# live terminal output (not captured into a msgbox - a `docker pull`
# or full stack generation can be long and verbose, and truncating or
# buffering it would hide real progress/errors). Returns the command's
# own exit status; returns 130 if the user declined the confirm.
confirm_and_run() {
    local title="$1" confirm_text="$2"
    shift 2

    if ! whiptail --backtitle "$BACKTITLE" --title "$title" \
        --yesno "$confirm_text" "$DLG_ROWS" "$DLG_COLS"; then
        return 130
    fi

    clear
    echo "=== $title ==="
    echo

    # `local status` must be declared *before* running "$@", not after
    # - `local` is itself a real command with its own exit status, so
    # a bare `local status` (no assignment) run right after "$@" would
    # overwrite $? with `local`'s own exit code before `status=$?` ever
    # sees the real one. Found live, the hard way: CI's bats suite
    # caught this exact regression from an earlier, well-intentioned
    # but wrong shellcheck-SC2155 fix (splitting `local status=$?`
    # this way without also reordering it) - status silently read 0
    # for every failed command, "Done." printed even on real failures.
    local status
    # VULCAN_PROGRESS=1 turns on the CLI's Rich live progress panel
    # (installer/panel.py) - every menu action keeps its real, live
    # install/docker output on screen inside a progress panel instead
    # of dumping raw subprocess spew. Only set for this one command,
    # not exported into the menu loop itself.
    VULCAN_PROGRESS=1 "$@"
    status=$?

    echo
    if [ "$status" -eq 0 ]; then
        echo "✓ Done."
    else
        echo "✗ Failed (exit $status) - see output above."
        echo "  Tip: Check 'docker compose -f stack/docker-compose.yml logs <service>' for details."
    fi

    # Guided Setup's own success path flows straight into the Setup
    # Complete screen (see guided_setup) rather than pausing here first -
    # every other menu action still waits for a real keypress before the
    # screen clears.
    if [ "$status" -ne 0 ] || [ -z "${SKIP_RETURN_PROMPT:-}" ]; then
        read -rp "Press Enter to return to the menu..." _dummy
    fi

    return "$status"
}

# --- Main Menu -------------------------------------------------------
#
# Every item is always shown, DockSTARTer-style, rather than hidden or
# disabled when not yet applicable (e.g. no stack exists yet) - the
# underlying `vulcan` command already has its own real "no stack
# found" check and error message (installer/cli.py's update()/pull()/
# uninstall()/etc.), so re-implementing that gate here would just
# duplicate logic that already exists and is already tested. Selecting
# an inapplicable item still gives the user a clear, real answer -
# arguably more informative than a silently disabled button.
# --- Sub-menus -----------------------------------------------------------

menu_install() {
    while true; do
        refresh_detect
        local choice
        choice=$(whiptail --backtitle "$BACKTITLE" --title "Install" \
            --menu "Choose install type:" "$DLG_ROWS" "$DLG_COLS" "$DLG_ITEMS" \
            "complete"      "Complete Setup (recommended) → storage → guided → configure → start" \
            "guided"        "Guided Setup → detect hardware, generate stack (no start)" \
            "storage"       "Media Storage Setup → provision blank drives as RAID/media volume" \
            "back"          "Back to main menu" \
            3>&1 1>&2 2>&3) || return
        case "$choice" in
            complete) complete_setup_flow ;;
            guided)   guided_setup ;;
            storage)  storage_setup_flow ;;
            back)     return ;;
        esac
    done
}

menu_configure() {
    while true; do
        refresh_detect
        local choice
        choice=$(whiptail --backtitle "$BACKTITLE" --title "Configure" \
            --menu "Configure services:" "$DLG_ROWS" "$DLG_COLS" "$DLG_ITEMS" \
            "services"    "Configure Services → VPN, Tailscale, Cloudflare, Traefik, Authelia, etc." \
            "storage"     "Reconfigure Media Storage → change RAID, mount point, drives" \
            "back"        "Back to main menu" \
            3>&1 1>&2 2>&3) || return
        case "$choice" in
            services) configure_services_flow ;;
            storage)  storage_setup_flow ;;
            back)     return ;;
        esac
    done
}

menu_stack() {
    while true; do
        refresh_detect
        local choice
        choice=$(whiptail --backtitle "$BACKTITLE" --title "Stack" \
            --menu "Stack operations:" "$DLG_ROWS" "$DLG_COLS" "$DLG_ITEMS" \
            "start"       "Start Stack → start an already-generated stack" \
            "status"      "Stack Status → show running/healthy/failed containers" \
            "update"      "Update Stack → pull latest images, recreate containers" \
            "pull"        "Pull Images → prep for offline start later" \
            "backup"      "Backup Stack → archive config/compose/env to backups/" \
            "restore"     "Restore Stack → from most recent backup" \
            "back"        "Back to main menu" \
            3>&1 1>&2 2>&3) || return
        case "$choice" in
            start)   confirm_and_run "Start Stack" "This will start stack/docker-compose.yml, reassigning any port already in use." "$VULCAN_BIN" start ;;
            status)  stack_status_flow ;;
            update)  confirm_and_run "Update Stack" "This will pull the latest images and recreate containers for stack/docker-compose.yml." "$VULCAN_BIN" update --non-interactive --yes ;;
            pull)    confirm_and_run "Pull Images" "This will pull images for stack/docker-compose.yml without starting anything." "$VULCAN_BIN" pull ;;
            backup)  confirm_and_run "Backup Stack" "This will archive stack/config/ and the compose/env files to backups/." "$VULCAN_BIN" backup ;;
            restore) restore_stack_flow ;;
            back)    return ;;
        esac
    done
}

menu_system() {
    while true; do
        refresh_detect
        local choice
        choice=$(whiptail --backtitle "$BACKTITLE" --title "System" \
            --menu "System operations:" "$DLG_ROWS" "$DLG_COLS" "$DLG_ITEMS" \
            "update"      "Update Vulcan → fast-forward this checkout" \
            "uninstall"   "Uninstall Stack → stop and delete stack/ entirely" \
            "back"        "Back to main menu" \
            3>&1 1>&2 2>&3) || return
        case "$choice" in
            update)     confirm_and_run "Update Vulcan" "This will fast-forward this Vulcan checkout to the latest origin/main." "$VULCAN_BIN" update-self --non-interactive --yes ;;
            uninstall)  uninstall_flow ;;
            back)       return ;;
        esac
    done
}

# --- Main Menu -----------------------------------------------------------

main_menu() {
    while true; do
        refresh_detect

        local choice
        choice=$(whiptail --backtitle "$BACKTITLE" --title "Vulcan" \
            --menu "Main Menu:" "$DLG_ROWS" "$DLG_COLS" "$DLG_ITEMS" \
            "install"     "Install → Complete, Guided, Storage" \
            "configure"   "Configure → Services, Storage" \
            "stack"       "Stack → Start, Status, Update, Pull, Backup, Restore" \
            "system"      "System → Update, Uninstall" \
            "exit"        "Exit" \
            3>&1 1>&2 2>&3) || return

        case "$choice" in
            install)    menu_install ;;
            configure)  menu_configure ;;
            stack)      menu_stack ;;
            system)     menu_system ;;
            exit)       clear; exit 0 ;;
        esac
    done
}

# --- Media Storage Setup ------------------------------------------------
#
# The whiptail front end for `vulcan storage apply`: detects the real
# blank, unprotected devices (`vulcan detect`'s BLANK_STORAGE_DEVICES,
# computed by installer/storage.py's list_blank_unprotected_devices()),
# lets the user pick which ones to provision, and hands the resulting
# argv to the exact same `vulcan storage apply --non-interactive --yes`
# command the CLI's own plain path would build - all the real safety
# gates (plan errors, non-blank refusal without --confirm-wipe, etc.)
# live in the CLI/engine, not re-implemented in bash.
storage_setup_flow() {

    refresh_detect

    if [ -z "$ALL_UNPROTECTED_DEVICES" ]; then
        whiptail --backtitle "$BACKTITLE" --title "Media Storage Setup" \
            --msgbox "No unprotected storage devices found. All drives appear to be in use by the system (/ or /boot)." "$DLG_ROWS" "$DLG_COLS"
        return 0
    fi

    local default_mount_point="/mnt/media"

    MEDIA_MOUNT_POINT=$(whiptail --backtitle "$BACKTITLE" --title "Media Storage Setup" \
        --inputbox "Mount point for the media storage volume" "$DLG_ROWS" "$DLG_COLS" "$default_mount_point" \
        3>&1 1>&2 2>&3) || return 0
    [ -z "$MEDIA_MOUNT_POINT" ] && return 0

# Get detailed info for all unprotected devices using lsblk
    local -a device_paths
    IFS=',' read -r -a device_paths <<< "$ALL_UNPROTECTED_DEVICES"

    # Build lsblk query for these specific devices to get size, fstype, mountpoint, model, serial
    local lsblk_paths
    lsblk_paths=$(IFS=,; echo "${device_paths[*]}")

    local lsblk_output
    lsblk_output=$(lsblk -J -o "NAME,PATH,SIZE,FSTYPE,MOUNTPOINT,MODEL,SERIAL" "$lsblk_paths" 2>/dev/null || echo '{"blockdevices":[]}')

    # Parse JSON to build checklist with device info
    local -a checklist_args=()
    local -a blank_devices=()
    local device
    for device in "${device_paths[@]}"; do
        # Extract info from lsblk JSON using grep/sed
        local size fstype mountpoint model serial
        size=$(echo "$lsblk_output" | grep -o "\"path\":\"$device\"[^}]*\"size\":\"[^\"]*" | sed 's/.*"size":"\([^"]*\)".*/\1/')
        fstype=$(echo "$lsblk_output" | grep -o "\"path\":\"$device\"[^}]*\"fstype\":\"[^\"]*" | sed 's/.*"fstype":"\([^"]*\)".*/\1/')
        mountpoint=$(echo "$lsblk_output" | grep -o "\"path\":\"$device\"[^}]*\"mountpoint\":\"[^\"]*" | sed 's/.*"mountpoint":"\([^"]*\)".*/\1/')
        model=$(echo "$lsblk_output" | grep -o "\"path\":\"$device\"[^}]*\"model\":\"[^\"]*" | sed 's/.*"model":"\([^"]*\)".*/\1/')
        serial=$(echo "$lsblk_output" | grep -o "\"path\":\"$device\"[^}]*\"serial\":\"[^\"]*" | sed 's/.*"serial":"\([^"]*\)".*/\1/')

        local desc
        if [ -z "$fstype" ] && [ -z "$mountpoint" ]; then
            desc="blank - $size"
        elif [ -n "$mountpoint" ]; then
            desc="mounted at $mountpoint ($fstype) - $size"
        else
            desc="$fstype - $size"
        fi

        if [ -n "$model" ] && [ "$model" != "null" ]; then
            desc="$desc - $model"
        fi
        if [ -n "$serial" ] && [ "$serial" != "null" ]; then
            desc="$desc (SN: $serial)"
        fi

        # Track blank devices (pre-selected) vs drives with data (not pre-selected)
        if [ -z "$fstype" ] && [ -z "$mountpoint" ]; then
            blank_devices+=("$device")
            default_on="ON"
        else
            default_on="OFF"
        fi

        checklist_args+=( "$device" "$desc" "$default_on" )
    done

    CHOSEN_DEVICES=$(whiptail --backtitle "$BACKTITLE" --title "Media Storage Setup" \
        --checklist "Select drive(s) to provision as media storage (blank drives pre-selected; selecting others will WIPE them):" "$DLG_ROWS" "$DLG_COLS" "$DLG_ITEMS" \
        "${checklist_args[@]}" \
        3>&1 1>&2 2>&3) || return 0

    # Same safe-eval idiom as the Optional Services checklist above:
    # whiptail's own --checklist output is properly double-quoted
    # space-separated tags, so eval is the standard idiom here too.
    # shellcheck disable=SC2034,SC2154
    eval "CHOSEN_DEVICE_LIST=($CHOSEN_DEVICES)"

    if [ "${#CHOSEN_DEVICE_LIST[@]}" -eq 0 ]; then
        return 0
    fi

    local devices_csv
    devices_csv=$(IFS=,; echo "${CHOSEN_DEVICE_LIST[*]}")

    local device_count="${#CHOSEN_DEVICE_LIST[@]}"
    local raid_level=""
    local level_summary=""

    # Determine if --confirm-wipe is needed: any chosen device NOT in blank_devices list
    local need_confirm_wipe=false
    local blank_set=" ${blank_devices[*]} "
    for device in "${CHOSEN_DEVICE_LIST[@]}"; do
        if [[ "$blank_set" != *" $device "* ]]; then
            need_confirm_wipe=true
            break
        fi
    done

    if [ "$device_count" -ge 4 ]; then

        RAID_LEVEL=$(whiptail --backtitle "$BACKTITLE" --title "Media Storage Setup" \
            --radiolist "Choose a RAID level for these $device_count devices:" "$DLG_ROWS" "$DLG_COLS" "$DLG_ITEMS" \
            "0"  "RAID0 - striping, $device_count of $device_count drives usable, NO redundancy (max capacity, any drive fails = data loss)" "OFF" \
            "5"  "RAID5 - ~$((device_count - 1)) of $device_count drives usable, survives 1 drive failure (recommended)" "ON" \
            "6"  "RAID6 - ~$((device_count - 2)) of $device_count drives usable, survives 2 drive failures" "OFF" \
            "10" "RAID10 - ~$((device_count / 2)) of $device_count drives usable, survives 1 drive per pair" "OFF" \
            3>&1 1>&2 2>&3) || return 0

        raid_level="$RAID_LEVEL"
        level_summary="mdadm RAID$RAID_LEVEL"
    elif [ "$device_count" -eq 3 ]; then

        RAID_LEVEL=$(whiptail --backtitle "$BACKTITLE" --title "Media Storage Setup" \
            --radiolist "Choose a RAID level for these $device_count devices:" "$DLG_ROWS" "$DLG_COLS" "$DLG_ITEMS" \
            "0"  "RAID0 - striping, 3 of 3 drives usable, NO redundancy (max capacity, any drive fails = data loss)" "OFF" \
            "5"  "RAID5 - ~2 of 3 drives usable, survives 1 drive failure (recommended)" "ON" \
            3>&1 1>&2 2>&3) || return 0

        raid_level="$RAID_LEVEL"
        level_summary="mdadm RAID$RAID_LEVEL"
    elif [ "$device_count" -eq 2 ]; then

        RAID_LEVEL=$(whiptail --backtitle "$BACKTITLE" --title "Media Storage Setup" \
            --radiolist "Choose a RAID level for these $device_count devices:" "$DLG_ROWS" "$DLG_COLS" "$DLG_ITEMS" \
            "0"  "RAID0 - striping, 2 of 2 drives usable, NO redundancy (max capacity, any drive fails = data loss)" "OFF" \
            "1"  "RAID1 - mirror, 1 of 2 drives usable, survives 1 drive failure (recommended)" "ON" \
            3>&1 1>&2 2>&3) || return 0

        raid_level="$RAID_LEVEL"
        level_summary="mdadm RAID$RAID_LEVEL"
    else
        level_summary="a single ext4 volume"
    fi

    local raid_flag=()
    [ -n "$raid_level" ] && raid_flag=(--raid-level "$raid_level")

    # Check if any selected drive has existing filesystem/partition (needs --confirm-wipe)
    local need_confirm_wipe=false
    for device in "${CHOSEN_DEVICE_LIST[@]}"; do
        local fstype mountpoint
        fstype=$(echo "$lsblk_output" | grep -o "\"path\":\"$device\"[^}]*\"fstype\":\"[^\"]*" | sed 's/.*"fstype":"\([^"]*\)".*/\1/')
        mountpoint=$(echo "$lsblk_output" | grep -o "\"path\":\"$device\"[^}]*\"mountpoint\":\"[^\"]*" | sed 's/.*"mountpoint":"\([^"]*\)".*/\1/')
        if [ -n "$fstype" ] || [ -n "$mountpoint" ]; then
            need_confirm_wipe=true
            break
        fi
    done

    local wipe_flag=()
    [ "$need_confirm_wipe" = true ] && wipe_flag=(--confirm-wipe)

    confirm_and_run "Media Storage Setup" \
        "This will provision $devices_csv into a single volume mounted at $MEDIA_MOUNT_POINT as $level_summary. Continue?" \
        "$VULCAN_BIN" storage apply --devices "$devices_csv" --mount-point "$MEDIA_MOUNT_POINT" --non-interactive --yes "${raid_flag[@]}" "${wipe_flag[@]}"
}

# --- Complete Setup (Linear Flow) --------------------------------------
#
# One-click linear flow for new users: storage → guided → configure → start.
# Runs the full setup sequence automatically with sensible defaults,
# pausing only for required user input (media path, tier, VPN/domain decisions).
complete_setup_flow() {

    log_title "Complete Setup"
    log_info "Starting complete linear setup flow"

    # Phase 0: Storage setup (if blank devices available)
    refresh_detect
    if [ -n "$ALL_UNPROTECTED_DEVICES" ]; then
        if whiptail --backtitle "$BACKTITLE" --title "Media Storage Setup" --yesno \
            "Vulcan detected unprotected drives that can be provisioned as a media storage volume (RAID if 2+ drives).\n\nSet up media storage now? This will:\n  - Let you choose which drives to use\n  - Configure RAID level (RAID0/1/5/6/10)\n  - Create filesystem and mount at /mnt/media\n\nChoose No to skip and use an existing path instead." "$DLG_ROWS" "$DLG_COLS"; then
            log_title "Phase 0: Media Storage Setup"
            storage_setup_flow
        else
            log_info "User skipped media storage setup"
        fi
    fi

    # Phase 1: System detection + Docker
    log_title "Phase 1: System Detection & Docker"
    refresh_detect
    log_info "CPU: ${CPU_CORES_LOGICAL:-0} logical cores, RAM: ${RAM_TOTAL_GB:-0}GB, Disk free: ${DISK_FREE_GB:-0}GB"
    log_info "Docker: installed=$DOCKER_INSTALLED running=$DOCKER_RUNNING compose=$DOCKER_COMPOSE_V2"
    log_info "Recommended tier: ${RECOMMENDED_TIER:-none}"

    if [ "$DOCKER_INSTALLED" != "true" ] || [ "$DOCKER_RUNNING" != "true" ] || [ "$DOCKER_COMPOSE_V2" != "true" ]; then
        log_info "Docker not fully ready"
        whiptail --backtitle "$BACKTITLE" --title "Docker" --msgbox \
            "Docker isn't fully ready yet (installed=$DOCKER_INSTALLED running=$DOCKER_RUNNING compose-v2=$DOCKER_COMPOSE_V2). Continuing will let Vulcan try to install/start it for you (--yes is implied)." "$DLG_ROWS" "$DLG_COLS"
    fi

    # Phase 2: Guided Setup (but don't start stack yet)
    log_title "Phase 2: Guided Stack Configuration"
    # Run guided setup but with --no-start equivalent
    guided_setup_no_start
    local guided_rc=$?

    if [ $guided_rc -ne 0 ]; then
        log_error "Guided setup failed or was cancelled (exit $guided_rc)"
        if whiptail --backtitle "$BACKTITLE" --title "Setup Incomplete" --yesno \
            "Guided setup was cancelled or failed. Storage may have been provisioned.\n\nReturn to main menu to retry or clean up?" "$DLG_ROWS" "$DLG_COLS"; then
            return 1
        fi
        return 1
    fi

    # Phase 3: Configure Services (if any need config)
    log_title "Phase 3: Service Configuration"
    refresh_detect
    if [ -f "stack/docker-compose.yml" ]; then
        # Check if any configurable services are enabled but not configured
        local needs_config=false
        if grep -q "gluetun" stack/docker-compose.yml && [ -z "${VPN_SERVICE_PROVIDER:-}${VPN_TYPE:-}" ]; then
            needs_config=true
        elif grep -q "cloudflared" stack/docker-compose.yml && [ -z "${CLOUDFLARE_TUNNEL_TOKEN:-}" ]; then
            needs_config=true
        elif grep -q "tailscale" stack/docker-compose.yml && [ -z "${TAILSCALE_AUTHKEY:-}" ]; then
            needs_config=true
        elif grep -q "traefik" stack/docker-compose.yml && [ -z "${DOMAIN:-}" ]; then
            needs_config=true
        elif grep -q "pihole" stack/docker-compose.yml && [ -z "${PIHOLE_PASSWORD:-}" ]; then
            needs_config=true
        fi

        if [ "$needs_config" = true ]; then
            if whiptail --backtitle "$BACKTITLE" --title "Configure Services" --yesno \
                "Some services need additional configuration (VPN credentials, domain, tunnel tokens, etc.).\n\nOpen Configure Services menu now to set them up?" "$DLG_ROWS" "$DLG_COLS"; then
                configure_services_flow
            fi
        fi
    fi

    # Phase 4: Start Stack
    log_title "Phase 4: Starting Stack"
    if whiptail --backtitle "$BACKTITLE" --title "Start Stack" --yesno \
        "Stack is configured. Start it now?\n\nThis will pull images and start all enabled services." "$DLG_ROWS" "$DLG_COLS"; then
        confirm_and_run "Start Stack" \
            "This will start stack/docker-compose.yml, reassigning any port already in use." \
            "$VULCAN_BIN" start
    fi

    log_info "Complete Setup finished"
}

# --- Stack Status -------------------------------------------------------
#
# Shows real-time container status with health checks.
stack_status_flow() {

    refresh_detect

    if [ ! -f "stack/docker-compose.yml" ]; then
        whiptail --backtitle "$BACKTITLE" --title "Stack Status" \
            --msgbox "No stack found. Run Guided Setup or Complete Setup first." "$DLG_ROWS" "$DLG_COLS"
        return 0
    fi

    local compose_file="stack/docker-compose.yml"

    # Get container status using docker compose ps --format json
    local status_output
    status_output=$(docker compose -f "$compose_file" ps --format json 2>/dev/null || echo "")

    if [ -z "$status_output" ]; then
        whiptail --backtitle "$BACKTITLE" --title "Stack Status" \
            --msgbox "No containers found for this stack. Run 'Start Stack' to begin." "$DLG_ROWS" "$DLG_COLS"
        return 0
    fi

    # Parse JSON output and build status table
    local -a status_lines=()
    while IFS= read -r line; do
        [ -z "$line" ] && continue
        local name image status health ports
        name=$(echo "$line" | jq -r '.Name // .Service // "unknown"')
        image=$(echo "$line" | jq -r '.Image // "unknown"')
        status=$(echo "$line" | jq -r '.State // "unknown"')
        health=$(echo "$line" | jq -r '.Health // "none"')
        ports=$(echo "$line" | jq -r '.Publishers // [] | map(.URL) | join(", ")')

        local status_icon
        case "$status" in
            running)
                if [ "$health" = "healthy" ]; then
                    status_icon="✓"
                elif [ "$health" = "unhealthy" ]; then
                    status_icon="✗"
                elif [ "$health" = "starting" ]; then
                    status_icon="⟳"
                else
                    status_icon="●"
                fi
                ;;
            exited|dead) status_icon="✗" ;;
            created) status_icon="○" ;;
            restarting) status_icon="⟳" ;;
            *) status_icon="?" ;;
        esac

        local health_display=""
        [ "$health" != "none" ] && [ "$health" != "null" ] && health_display=" ($health)"

        local port_display=""
        [ -n "$ports" ] && [ "$ports" != "null" ] && [ "$ports" != "[]" ] && port_display=" → $ports"

        status_lines+=("$status_icon $name$health_display$port_display")
    done <<< "$status_output"

    if [ ${#status_lines[@]} -eq 0 ]; then
        whiptail --backtitle "$BACKTITLE" --title "Stack Status" \
            --msgbox "No containers found." "$DLG_ROWS" "$DLG_COLS"
        return 0
    fi

    # Build scrollable msgbox content
    local msg="Stack Status (from docker compose ps):\n\n"
    for line in "${status_lines[@]}"; do
        msg+="$line\n"
    done
    msg+="\nLegend: ✓ healthy ● running ⟳ starting/restarting ✗ failed/unhealthy ○ created\n\n"
    msg+="Tip: Run 'docker compose -f stack/docker-compose.yml logs <service>' for details."

    whiptail --backtitle "$BACKTITLE" --title "Stack Status" \
        --msgbox "$msg" "$DLG_ROWS" "$DLG_COLS" --scrolltext
}

# --- Media Storage Teardown ------------------------------------------
#
# The whiptail front end for `vulcan storage teardown`: reverses
# whatever Media Storage Setup provisioned at $STORAGE_MOUNT. Two real
# confirmation steps, not one - a typed mount-point match (equal to
# Media Storage Setup's own typed-device-list bar) followed by a final
# yesno via confirm_and_run - deliberately a stronger bar than Media
# Storage Setup's single yesno, since a teardown is destructive by
# definition (Media Storage Setup's own bar only gets that strict when
# a target device already has data). All the real safety gates
# (protected-device refusal, etc.) live in the CLI/engine, not
# re-implemented here.
storage_teardown_flow() {

    refresh_detect

    if [ -z "$STORAGE_MOUNT" ]; then
        whiptail --backtitle "$BACKTITLE" --title "Reset Media Storage" \
            --msgbox "Nothing is currently provisioned - there's nothing to tear down." "$DLG_ROWS" "$DLG_COLS"
        return 0
    fi

    TYPED_MOUNT=$(whiptail --backtitle "$BACKTITLE" --title "Reset Media Storage" \
        --inputbox "This permanently unmounts and wipes every filesystem/RAID signature on the storage at $STORAGE_MOUNT - there is no undo.\n\nType the mount point to confirm:" \
        "$DLG_ROWS" "$DLG_COLS" \
        3>&1 1>&2 2>&3) || return 0

    if [ "$TYPED_MOUNT" != "$STORAGE_MOUNT" ]; then
        whiptail --backtitle "$BACKTITLE" --title "Reset Media Storage" \
            --msgbox "Confirmation didn't match - nothing was executed." "$DLG_ROWS" "$DLG_COLS"
        return 0
    fi

    confirm_and_run "Reset Media Storage" \
        "Final confirmation: tear down the storage mounted at $STORAGE_MOUNT?" \
        "$VULCAN_BIN" storage teardown --mount-point "$STORAGE_MOUNT" --non-interactive --yes --confirm-wipe
}

# --- Configure Services -----------------------------------------------
#
# Post-install walkthrough for services that need extra configuration
# (VPN credentials, tunnel tokens, domain setup, etc.). Runs after the
# stack is generated and started, so the user can fill in .env values
# and restart affected services.
configure_services_flow() {

    while true; do
        refresh_detect

        if [ ! -f "stack/docker-compose.yml" ]; then
            whiptail --backtitle "$BACKTITLE" --title "Configure Services" \
                --msgbox "No stack found. Run Guided Setup first." "$DLG_ROWS" "$DLG_COLS"
            return 0
        fi

        # Load current .env to see what's already set
        local env_file="stack/.env"
        if [ -f "$env_file" ]; then
            # shellcheck disable=SC1090
            source "$env_file"
        fi

        # Check which services needing config are enabled
        local -a config_items=()

        # gluetun - needs VPN credentials
        if grep -q "gluetun" stack/docker-compose.yml; then
            local status="NOT CONFIGURED"
            [ -n "${VPN_SERVICE_PROVIDER:-}" ] && [ -n "${VPN_TYPE:-}" ] && [ -n "${WIREGUARD_PRIVATE_KEY:-}${OPENVPN_USER:-}${OPENVPN_PASSWORD:-}" ] && status="CONFIGURED"
            config_items+=("gluetun" "Gluetun VPN - $status (needs VPN provider credentials)")
        fi

        # cloudflared - needs tunnel token
        if grep -q "cloudflared" stack/docker-compose.yml; then
            local status="NOT CONFIGURED"
            [ -n "${CLOUDFLARE_TUNNEL_TOKEN:-}" ] && status="CONFIGURED"
            config_items+=("cloudflared" "Cloudflare Tunnel - $status (needs tunnel token from Cloudflare Zero Trust)")
        fi

        # tailscale - needs auth key
        if grep -q "tailscale" stack/docker-compose.yml; then
            local status="NOT CONFIGURED"
            [ -n "${TAILSCALE_AUTHKEY:-}" ] && status="CONFIGURED"
            config_items+=("tailscale" "Tailscale - $status (needs auth key from Tailscale admin console)")
        fi

        # traefik - needs domain (handled in guided setup, but check DNS)
        if grep -q "traefik" stack/docker-compose.yml; then
            local status="NOT CONFIGURED"
            [ -n "${DOMAIN:-}" ] && status="DOMAIN SET"
            config_items+=("traefik" "Traefik - $status (needs domain + DNS A records pointing to this host)")
        fi

        # authelia - needs admin user (done in guided setup)
        if grep -q "authelia" stack/docker-compose.yml; then
            local status="CONFIGURED"
            [ ! -f "stack/config/authelia/users_database.yml" ] && status="NOT CONFIGURED"
            config_items+=("authelia" "Authelia SSO - $status (admin user created during setup)")
        fi

        # pihole - needs admin password
        if grep -q "pihole" stack/docker-compose.yml; then
            local status="NOT CONFIGURED"
            [ -n "${PIHOLE_PASSWORD:-}" ] && status="CONFIGURED"
            config_items+=("pihole" "Pi-hole - $status (needs admin password)")
        fi

        if [ ${#config_items[@]} -eq 0 ]; then
            whiptail --backtitle "$BACKTITLE" --title "Configure Services" \
                --msgbox "No configurable services found in the current stack." "$DLG_ROWS" "$DLG_COLS"
            return 0
        fi

        # Build menu
        local -a menu_items=()
        for ((i=0; i<${#config_items[@]}; i+=2)); do
            menu_items+=("${config_items[i]}" "${config_items[i+1]}")
        done
        menu_items+=("refresh" "⟳ Refresh Status - re-check all services")
        menu_items+=("done" "Done - return to main menu")

        local choice
        choice=$(whiptail --backtitle "$BACKTITLE" --title "Configure Services" \
            --menu "Select a service to configure (shows CONFIGURED/NOT CONFIGURED):" "$DLG_ROWS" "$DLG_COLS" "$DLG_ITEMS" \
            "${config_items[@]}" \
            3>&1 1>&2 2>&3) || return 0

        [ "$choice" = "done" ] && break

        if [ "$choice" = "refresh" ]; then
            continue  # Loop will re-run with fresh .env
        fi

        case "$choice" in
            gluetun)
                if ! prompt_edit_then_restart "gluetun" \
                    "Gluetun VPN Setup" \
                    $'Gluetun needs your VPN provider credentials in stack/.env:\n\n1. Edit stack/.env and set:\n   VPN_SERVICE_PROVIDER=<your_provider> (e.g. protonvpn, mullvad, nordvpn)\n   VPN_TYPE=wireguard (or openvpn)\n\nFor WireGuard:\n   WIREGUARD_PRIVATE_KEY=<from provider>\n   WIREGUARD_ADDRESSES=<from provider>\n\nFor OpenVPN:\n   OPENVPN_USER=<username>\n   OPENVPN_PASSWORD=<password>\n\nFull provider list: https://github.com/qdm12/gluetun-wiki/tree/main/setup/providers\n\nAfter editing .env: docker compose -f stack/docker-compose.yml up -d gluetun'; then
                    continue
                fi
                ;;
            cloudflared)
                if ! prompt_edit_then_restart "cloudflared" \
                    "Cloudflare Tunnel Setup" \
                    $'Cloudflare Tunnel needs a tunnel token from Cloudflare Zero Trust:\n\n1. Go to https://one.dash.cloudflare.com → Access → Tunnels\n2. Create a tunnel → Copy the token (starts with ey...)\n3. Edit stack/.env and set:\n   CLOUDFLARE_TUNNEL_TOKEN=<your_token>\n\nNote: Tunnel must have public hostnames configured for your services.'; then
                    continue
                fi
                ;;
            tailscale)
                if ! prompt_edit_then_restart "tailscale" \
                    "Tailscale Setup" \
                    $'Tailscale needs an auth key:\n\n1. Go to https://login.tailscale.com/admin/settings/keys\n2. Generate an auth key (reusable, ephemeral, pre-authorized)\n3. Edit stack/.env and set:\n   TAILSCALE_AUTHKEY=<your_auth_key>\n\nOptional: TAILSCALE_HOSTNAME=<custom_name>'; then
                    continue
                fi
                ;;
            traefik)
                if ! prompt_edit_then_restart "traefik" \
                    "Traefik Domain Setup" \
                    $'Traefik needs a domain with DNS pointing to this host:\n\n1. Own a domain (e.g. example.com)\n2. Create DNS A records pointing to this host\'s public IP:\n   *.example.com → YOUR_PUBLIC_IP\n3. Edit stack/.env and set:\n   DOMAIN=example.com\n\n3. For real Let\'s Encrypt certs (optional):\n   CLOUDFLARE_DNS=true\n   CLOUDFLARE_EMAIL=your@email.com\n   (requires Cloudflare DNS)'; then
                    continue
                fi
                ;;
            authelia)
                whiptail --backtitle "$BACKTITLE" --title "Authelia SSO Setup" --msgbox \
                    "Authelia was configured during Guided Setup:\n\
- Admin user: check stack/config/authelia/users_database.yml\n\
- Password was hashed during setup\n\n\
To add users: edit stack/config/authelia/users_database.yml\n\
and run: docker compose -f stack/docker-compose.yml restart authelia\n\n\
Access: https://authelia.${DOMAIN:-yourdomain.com}" \
                    "$DLG_ROWS" "$DLG_COLS"
                ;;
            pihole)
                if ! prompt_edit_then_restart "pihole" \
                    "Pi-hole Setup" \
                    "Pi-hole needs an admin password:\n\n\
1. Edit stack/.env and set:\n\
   PIHOLE_PASSWORD=<your_admin_password>\n\n\
Default login: admin / your_password"; then
                    continue
                fi
                ;;
        esac
    done
}

# Helper: Show instructions, then offer to restart service after user edits .env
prompt_edit_then_restart() {
    local service="$1"
    local title="$2"
    local instructions="$3"

    while true; do
        whiptail --backtitle "$BACKTITLE" --title "$title" --msgbox \
            $'$instructions\n\nAfter editing .env, choose an option below:' "$DLG_ROWS" "$DLG_COLS"

        local action
        action=$(whiptail --backtitle "$BACKTITLE" --title "$title" \
            --menu "What would you like to do?" "$DLG_ROWS" "$DLG_COLS" "$DLG_ITEMS" \
            "edit" "I've edited .env - restart $service now" \
            "recheck" "⟳ Re-check status (reload .env)" \
            "back" "Return to service menu" \
            3>&1 1>&2 2>&3) || return 1

        case "$action" in
            edit)
                # Reload .env and restart the service
                if [ -f "stack/.env" ]; then
                    # shellcheck disable=SC1090
                    source "stack/.env"
                fi
                if docker compose -f stack/docker-compose.yml up -d "$service" 2>/dev/null; then
                    whiptail --backtitle "$BACKTITLE" --title "$title" --msgbox \
                        $'$service restarted successfully.\n\nRe-checking status...' "$DLG_ROWS" "$DLG_COLS"
                else
                    whiptail --backtitle "$BACKTITLE" --title "$title - Error" --msgbox \
                        $'Failed to restart $service. Check logs:\n  docker compose -f stack/docker-compose.yml logs $service' "$DLG_ROWS" "$DLG_COLS"
                fi
                ;;
            recheck)
                continue  # Loop will re-check status
                ;;
            back)
                return 1
                ;;
        esac
    done

    return 0
}

# --- Restore --------------------------------------------------------
#
# The one maintenance item with a real second decision baked into the
# CLI itself (`vulcan restore --start/--no-start`) - mirrors
# RestoreScreen's own two-step shape, just via one extra yesno instead
# of a second screen.
restore_stack_flow() {

    local start_flag="--no-start"

    if whiptail --backtitle "$BACKTITLE" --title "Restore Stack" \
        --yesno "Start the restored stack immediately after restoring?" "$DLG_ROWS" "$DLG_COLS"; then
        start_flag="--start"
    fi

    confirm_and_run "Restore Stack" \
        "This will restore config/, docker-compose.yml, and .env in stack/ from the most recent backup, overwriting what's there now." \
        "$VULCAN_BIN" restore --non-interactive --yes "$start_flag"
}

# --- Uninstall -------------------------------------------------------

uninstall_flow() {

    local purge_flags=()
    local prune_flags=()

    if whiptail --backtitle "$BACKTITLE" --title "Uninstall Stack" \
        --yesno "Also delete backups/ and exports/? (default: No - leave your backup archives in place)" "$DLG_ROWS" "$DLG_COLS" --defaultno; then
        purge_flags=(--purge-artifacts)
    fi

    if whiptail --backtitle "$BACKTITLE" --title "Uninstall Stack" \
        --yesno "Also run 'docker system prune -a' afterward? Reclaims disk space, but affects the whole Docker host, not just vulcan's containers. (default: No)" "$DLG_ROWS" "$DLG_COLS" --defaultno; then
        prune_flags=(--prune-docker)
    fi

    confirm_and_run "Uninstall Stack" \
        "This will stop the running stack (if any) and permanently delete stack/ (containers, network, and all app config/data). Your media library is always left untouched." \
        "$VULCAN_BIN" uninstall --non-interactive --yes "${purge_flags[@]}" "${prune_flags[@]}"
}

# --- Guided Setup (No Start) ------------------------------------------
#
# Same as guided_setup but stops before starting the stack.
# Used by Complete Setup linear flow.
guided_setup_no_start() {

    # --- Welcome screen (Security Onion pattern) ---
    if ! whiptail --backtitle "$BACKTITLE" --title "Welcome" --yesno \
        "\n\n\n\nWelcome to the Vulcan Setup!\n\nVulcan will detect your hardware and recommend the best\nconfiguration for a self-hosted media stack.\n\nSetup uses keyboard navigation:\n  Arrow keys to move around\n  Enter to select\n  Tab to switch between buttons\n\nWould you like to continue?" "$DLG_ROWS" "$DLG_COLS"; then
        return 0
    fi
    log_title "Starting Guided Setup"
    log_info "User entered guided setup"

    # --- Phase 0: Media storage provisioning (optional) ---
    refresh_detect

    if [ -n "$ALL_UNPROTECTED_DEVICES" ]; then
        log_title "Phase 0: Media Storage Setup"
        storage_setup_flow
    fi

    log_title "Phase 1: System Detection"
    refresh_detect
    log_info "CPU: ${CPU_CORES_LOGICAL:-0} logical cores, RAM: ${RAM_TOTAL_GB:-0}GB, Disk free: ${DISK_FREE_GB:-0}GB"
    log_info "Docker: installed=$DOCKER_INSTALLED running=$DOCKER_RUNNING compose=$DOCKER_COMPOSE_V2"
    log_info "Recommended tier: ${RECOMMENDED_TIER:-none}"

    if [ "$DOCKER_INSTALLED" != "true" ] || [ "$DOCKER_RUNNING" != "true" ] || [ "$DOCKER_COMPOSE_V2" != "true" ]; then
        log_info "Docker not fully ready, showing warning"
        whiptail --backtitle "$BACKTITLE" --title "Docker" --msgbox \
            "Docker isn't fully ready yet (installed=$DOCKER_INSTALLED running=$DOCKER_RUNNING compose-v2=$DOCKER_COMPOSE_V2). Continuing will let Vulcan try to install/start it for you (--yes is implied)." "$DLG_ROWS" "$DLG_COLS"
    fi

    log_title "Phase 2: Configuration"

    local default_media_path default_tier default_puid_value default_pgid_value default_tz_value

    if [ -n "$PREVIOUS_TIER" ]; then
        default_media_path="$PREVIOUS_MEDIA_PATH"
        default_tier="$PREVIOUS_TIER"
        default_puid_value="$PREVIOUS_PUID"
        default_pgid_value="$PREVIOUS_PGID"
        default_tz_value="$PREVIOUS_TIMEZONE"
    else
        default_media_path="${STORAGE_MOUNT:-$HOME/media}"
        default_tier="$RECOMMENDED_TIER"
        default_puid_value="$DEFAULT_PUID"
        default_pgid_value="$DEFAULT_PGID"
        default_tz_value="$DEFAULT_TIMEZONE"
    fi

    MEDIA_PATH=$(whiptail --backtitle "$BACKTITLE" --title "Media Library" \
        --inputbox "Where should your media library live?" "$DLG_ROWS" "$DLG_COLS" "$default_media_path" \
        3>&1 1>&2 2>&3) || return
    [ -z "$MEDIA_PATH" ] && return

    local light_on medium_on heavy_on
    light_on="OFF"; medium_on="OFF"; heavy_on="OFF"
    case "$default_tier" in
        light) light_on="ON" ;;
        medium) medium_on="ON" ;;
        heavy) heavy_on="ON" ;;
    esac

    TIER=$(whiptail --backtitle "$BACKTITLE" --title "Choose a Tier" \
        --radiolist "Detected: $CPU_CORES_LOGICAL logical cores, ${RAM_TOTAL_GB}GB RAM, ${DISK_FREE_GB}GB free.\n${RECOMMENDED_TIER_EXPLANATION}" \
        "$DLG_ROWS" "$DLG_COLS" "$DLG_ITEMS" \
        "light"  "Light - low-resource baseline" "$light_on" \
        "medium" "Medium - the common case" "$medium_on" \
        "heavy"  "Heavy - full stack, GPU transcoding, more services" "$heavy_on" \
        3>&1 1>&2 2>&3) || return

    local customize=false

    if whiptail --backtitle "$BACKTITLE" --title "Services" \
        --yesno "Customize the full service list? (adds Traefik/Authelia domain routing, CrowdSec, Tailscale, Decluttarr, Maintainerr, and more)\n\nChoose No for the common case - just the tier's usual services plus the toggles on the next screen." \
        "$DLG_ROWS" "$DLG_COLS" --defaultno; then
        customize=true
    fi

    SERVICES_FLAG=()
    DOMAIN_FLAGS=()
    TOGGLE_FLAGS=()

    if [ "$customize" = true ]; then
        _guided_setup_customize_services
    else
        _guided_setup_quick_toggles
    fi

    # If gluetun (VPN) was selected, prompt for credentials now
    if [[ " ${TOGGLE_FLAGS[@]} " =~ " --vpn " ]]; then
        if [ -z "${VPN_SERVICE_PROVIDER:-}" ] || [ -z "${VPN_TYPE:-}" ]; then
            if whiptail --backtitle "$BACKTITLE" --title "Gluetun VPN Required" --yesno \
                $'Gluetun VPN was selected but no VPN credentials were provided.\n\nYou must provide VPN credentials for the stack to start successfully.\n\nWould you like to configure VPN credentials now?' "$DLG_ROWS" "$DLG_COLS"; then
                VPN_SERVICE_PROVIDER=$(whiptail --backtitle "$BACKTITLE" --title "VPN Provider" \
                    --inputbox "VPN Service Provider (e.g. protonvpn, mullvad, nordvpn)" "$DLG_ROWS" "$DLG_COLS" "" \
                    3>&1 1>&2 2>&3) || return
                VPN_TYPE=$(whiptail --backtitle "$BACKTITLE" --title "VPN Type" \
                    --radiolist "Select VPN type:" "$DLG_ROWS" "$DLG_COLS" "$DLG_ITEMS" \
                    "wireguard" "WireGuard (recommended)" "ON" \
                    "openvpn" "OpenVPN" "OFF" \
                    3>&1 1>&2 2>&3) || return
                
                if [ "$VPN_TYPE" = "wireguard" ]; then
                    WIREGUARD_PRIVATE_KEY=$(whiptail --backtitle "$BACKTITLE" --title "WireGuard Key" \
                        --passwordbox "WireGuard Private Key" "$DLG_ROWS" "$DLG_COLS" "" \
                        3>&1 1>&2 2>&3) || return
                    WIREGUARD_ADDRESSES=$(whiptail --backtitle "$BACKTITLE" --title "WireGuard Addresses" \
                        --inputbox "WireGuard Addresses (e.g. 10.0.0.2/24)" "$DLG_ROWS" "$DLG_COLS" "" \
                        3>&1 1>&2 2>&3) || return
                else
                    OPENVPN_USER=$(whiptail --backtitle "$BACKTITLE" --title "OpenVPN User" \
                        --inputbox "OpenVPN Username" "$DLG_ROWS" "$DLG_COLS" "" \
                        3>&1 1>&2 2>&3) || return
                    OPENVPN_PASSWORD=$(whiptail --backtitle "$BACKTITLE" --title "OpenVPN Password" \
                        --passwordbox "OpenVPN Password" "$DLG_ROWS" "$DLG_COLS" "" \
                        3>&1 1>&2 2>&3) || return
                fi
                
                export VPN_SERVICE_PROVIDER VPN_TYPE WIREGUARD_PRIVATE_KEY WIREGUARD_ADDRESSES OPENVPN_USER OPENVPN_PASSWORD
            else
                whiptail --backtitle "$BACKTITLE" --title "VPN Required" --msgbox \
                    $'Gluetun requires VPN credentials to function. Disabling VPN for this installation.' \
                    "$DLG_ROWS" "$DLG_COLS"
                TOGGLE_FLAGS=( "${TOGGLE_FLAGS[@]/--vpn/--no-vpn}" )
            fi
        fi
    fi


    PUID=$(whiptail --backtitle "$BACKTITLE" --title "User/Group" \
        --inputbox "PUID - user ID the containers run as (matters for file ownership on your media library)" "$DLG_ROWS" "$DLG_COLS" "$default_puid_value" \
        3>&1 1>&2 2>&3) || return

    PGID=$(whiptail --backtitle "$BACKTITLE" --title "User/Group" \
        --inputbox "PGID - group ID the containers run as" "$DLG_ROWS" "$DLG_COLS" "$default_pgid_value" \
        3>&1 1>&2 2>&3) || return

    TIMEZONE=$(whiptail --backtitle "$BACKTITLE" --title "Timezone" \
        --inputbox "Timezone (e.g. America/New_York, Europe/London)" "$DLG_ROWS" "$DLG_COLS" "$default_tz_value" \
        3>&1 1>&2 2>&3) || return

    # Build and run the vulcan command (without --start)
    local vulcan_cmd=("$VULCAN_BIN" --non-interactive --yes)

    vulcan_cmd+=(--tier "$TIER")
    vulcan_cmd+=(--media-path "$MEDIA_PATH")
    vulcan_cmd+=(--puid "$PUID")
    vulcan_cmd+=(--pgid "$PGID")
    vulcan_cmd+=(--timezone "$TIMEZONE")

    [ -n "$SERVICES_FLAG" ] && vulcan_cmd+=(--services "$SERVICES_FLAG")
    [ -n "$DOMAIN_FLAGS" ] && vulcan_cmd+=("${DOMAIN_FLAGS[@]}")
    [ -n "$TOGGLE_FLAGS" ] && vulcan_cmd+=("${TOGGLE_FLAGS[@]}")

    confirm_and_run "Generate Stack" \
        "This will generate stack/docker-compose.yml and .env with your choices. Stack will NOT be started." \
        "${vulcan_cmd[@]}"

log_info "Guided Setup (no start) completed"
}

# --- Guided Setup ------------------------------------------------------
#
# The main guided setup that includes the option to start the stack.
# Calls guided_setup_no_start (which generates the stack) and then
# optionally starts it based on user choice.
guided_setup() {
    # --- Welcome screen (Security Onion pattern) ---
    if ! whiptail --backtitle "$BACKTITLE" --title "Welcome" --yesno \
        "\n\n\n\nWelcome to the Vulcan Setup!\n\nVulcan will detect your hardware and recommend the best\nconfiguration for a self-hosted media stack.\n\nSetup uses keyboard navigation:\n  Arrow keys to move around\n  Enter to select\n  Tab to switch between buttons\n\nWould you like to continue?" "$DLG_ROWS" "$DLG_COLS"; then
        return 0
    fi
    log_title "Starting Guided Setup"
    log_info "User entered guided setup"

    # --- Phase 0: Media storage provisioning (optional) ---
    # First ask if user wants to set up media storage
    refresh_detect

    if [ -n "$ALL_UNPROTECTED_DEVICES" ]; then
        if whiptail --backtitle "$BACKTITLE" --title "Media Storage Setup" --yesno \
            "Vulcan detected unprotected drives that can be provisioned as a media storage volume (RAID if 2+ drives).\n\nWould you like to set up media storage now?\n\nThis will:\n  - Detect all available drives\n  - Let you choose which to use\n  - Configure RAID level (RAID0/1/5/6/10)\n  - Create filesystem and mount at /mnt/media\n\nChoose No to skip and use an existing path instead." "$DLG_ROWS" "$DLG_COLS"; then
            log_title "Phase 0: Media Storage Setup"
            storage_setup_flow
        else
            log_info "User skipped media storage setup"
        fi
    fi

    log_title "Phase 1: System Detection"
    refresh_detect
    log_info "CPU: ${CPU_CORES_LOGICAL:-0} logical cores, RAM: ${RAM_TOTAL_GB:-0}GB, Disk free: ${DISK_FREE_GB:-0}GB"
    log_info "Docker: installed=$DOCKER_INSTALLED running=$DOCKER_RUNNING compose=$DOCKER_COMPOSE_V2"
    log_info "Recommended tier: ${RECOMMENDED_TIER:-none}"

    if [ "$DOCKER_INSTALLED" != "true" ] || [ "$DOCKER_RUNNING" != "true" ] || [ "$DOCKER_COMPOSE_V2" != "true" ]; then
        log_info "Docker not fully ready, showing warning"
        whiptail --backtitle "$BACKTITLE" --title "Docker" --msgbox \
            "Docker isn't fully ready yet (installed=$DOCKER_INSTALLED running=$DOCKER_RUNNING compose-v2=$DOCKER_COMPOSE_V2). Continuing will let Vulcan try to install/start it for you (--yes is implied)." "$DLG_ROWS" "$DLG_COLS"
    fi

    log_title "Phase 2: Configuration"

    local default_media_path default_tier default_puid_value default_pgid_value default_tz_value

    if [ -n "$PREVIOUS_TIER" ]; then
        default_media_path="$PREVIOUS_MEDIA_PATH"
        default_tier="$PREVIOUS_TIER"
        default_puid_value="$PREVIOUS_PUID"
        default_pgid_value="$PREVIOUS_PGID"
        default_tz_value="$PREVIOUS_TIMEZONE"
    else
        default_media_path="${STORAGE_MOUNT:-$HOME/media}"
        default_tier="$RECOMMENDED_TIER"
        default_puid_value="$DEFAULT_PUID"
        default_pgid_value="$DEFAULT_PGID"
        default_tz_value="$DEFAULT_TIMEZONE"
    fi

    MEDIA_PATH=$(whiptail --backtitle "$BACKTITLE" --title "Media Library" \
        --inputbox "Where should your media library live?" "$DLG_ROWS" "$DLG_COLS" "$default_media_path" \
        3>&1 1>&2 2>&3) || return
    [ -z "$MEDIA_PATH" ] && return

    local light_on medium_on heavy_on
    light_on="OFF"; medium_on="OFF"; heavy_on="OFF"
    case "$default_tier" in
        light) light_on="ON" ;;
        medium) medium_on="ON" ;;
        heavy) heavy_on="ON" ;;
    esac

    TIER=$(whiptail --backtitle "$BACKTITLE" --title "Choose a Tier" \
        --radiolist "Detected: $CPU_CORES_LOGICAL logical cores, ${RAM_TOTAL_GB}GB RAM, ${DISK_FREE_GB}GB free.\n${RECOMMENDED_TIER_EXPLANATION}" \
        "$DLG_ROWS" "$DLG_COLS" "$DLG_ITEMS" \
        "light"  "Light - low-resource baseline" "$light_on" \
        "medium" "Medium - the common case" "$medium_on" \
        "heavy"  "Heavy - full stack, GPU transcoding, more services" "$heavy_on" \
        3>&1 1>&2 2>&3) || return

    local customize=false

    if whiptail --backtitle "$BACKTITLE" --title "Services" \
        --yesno "Customize the full service list? (adds Traefik/Authelia domain routing, CrowdSec, Tailscale, Decluttarr, Maintainerr, and more)\n\nChoose No for the common case - just the tier's usual services plus the toggles on the next screen." \
        "$DLG_ROWS" "$DLG_COLS" --defaultno; then
        customize=true
    fi

    SERVICES_FLAG=()
    DOMAIN_FLAGS=()
    TOGGLE_FLAGS=()

    if [ "$customize" = true ]; then
        _guided_setup_customize_services
    else
        _guided_setup_quick_toggles
    fi

    PUID=$(whiptail --backtitle "$BACKTITLE" --title "User/Group" \
        --inputbox "PUID - user ID the containers run as (matters for file ownership on your media library)" "$DLG_ROWS" "$DLG_COLS" "$default_puid_value" \
        3>&1 1>&2 2>&3) || return

    PGID=$(whiptail --backtitle "$BACKTITLE" --title "User/Group" \
        --inputbox "PGID - group ID the containers run as" "$DLG_ROWS" "$DLG_COLS" "$default_pgid_value" \
        3>&1 1>&2 2>&3) || return

    TIMEZONE=$(whiptail --backtitle "$BACKTITLE" --title "Timezone" \
        --inputbox "IANA timezone name (e.g. America/New_York)" "$DLG_ROWS" "$DLG_COLS" "$default_tz_value" \
        3>&1 1>&2 2>&3) || return

    START_FLAG="--no-start"
    if whiptail --backtitle "$BACKTITLE" --title "Start Now" \
        --yesno "Start the stack now, right after generating it?" "$DLG_ROWS" "$DLG_COLS"; then
        START_FLAG="--start"
    fi

    local services_summary
    if [ "$customize" = true ]; then
        services_summary="${SERVICES_FLAG[1]:-none selected}"
    else
        services_summary="$TIER tier defaults"
        [ "${#TOGGLE_FLAGS[@]}" -gt 0 ] && services_summary+=" (${TOGGLE_FLAGS[*]})"
    fi

    # --- Phase 3: Review & Execute ---
    log_title "Phase 3: Review & Execute"
    log_info "Selected tier: $TIER"
    log_info "Media path: $MEDIA_PATH"
    log_info "PUID=$PUID PGID=$PGID TZ=$TIMEZONE"
    log_info "Services: $services_summary"
    log_info "Start: $START_FLAG"

    # Show a full settings summary before executing (Security Onion pattern).
    local summary=""
    summary+="Tier:        $TIER\n"
    summary+="Media Path:  $MEDIA_PATH\n"
    summary+="PUID/PGID:   $PUID / $PGID\n"
    summary+="Timezone:    $TIMEZONE\n"
    summary+="Services:    $services_summary\n"
    [ "${#DOMAIN_FLAGS[@]}" -gt 0 ] && summary+="Domain/Auth: configured\n"
    summary+="Auto-start:  $([ "$START_FLAG" = "--start" ] && echo "yes" || echo "no")\n"
    summary+="\nPress TAB to select yes or no."

    if ! whiptail --backtitle "$BACKTITLE" --title "Review Settings" \
        --yesno "$summary" "$DLG_ROWS" "$DLG_COLS" --scrolltext; then
        return 0
    fi

    SKIP_RETURN_PROMPT=true confirm_and_run "Guided Setup" \
        "About to generate a $TIER stack at $MEDIA_PATH (PUID=$PUID PGID=$PGID TZ=$TIMEZONE). Continue?" \
        "$VULCAN_BIN" --non-interactive --yes \
            --tier "$TIER" --media-path "$MEDIA_PATH" \
            --puid "$PUID" --pgid "$PGID" --timezone "$TIMEZONE" \
            "${SERVICES_FLAG[@]}" "${TOGGLE_FLAGS[@]}" "${DOMAIN_FLAGS[@]}" \
            "$START_FLAG"
    local rc=$?

    if [ "$rc" -eq 0 ]; then
        log_info "Guided setup completed successfully"

        # Real user feedback (2026-08-17): the live console output during
        # the run (detected hardware, itemized tier descriptions, per-
        # service warnings, the numbered setup order) scrolled by under
        # the live progress panel and was preferred less than this final
        # screen - so run_install() now suppresses that detail while the
        # panel is active (installer.panel.RunPanel.note()) and it's
        # surfaced here instead, via `vulcan install-summary` re-deriving
        # it from the just-written stack/.vulcan-state.json. Moved, not
        # dropped - see ROADMAP.md's "Guided Setup output redesign".
        local summary
        summary=$("$VULCAN_BIN" install-summary 2>/dev/null)

        # --- Setup Complete (Security Onion pattern) ---
        if [ "$START_FLAG" = "--start" ]; then

            local urls
            urls=$("$VULCAN_BIN" urls 2>/dev/null)

            local complete_msg="Vulcan setup is complete!\n\nYour stack is running."
            [ -n "$urls" ] && complete_msg+="\n\nService URLs:\n$urls"
            complete_msg+="\n\nTo manage your stack:\n  docker compose -f stack/docker-compose.yml ps\n  docker compose -f stack/docker-compose.yml down"
            [ -n "$summary" ] && complete_msg+="\n\n$summary"

            whiptail --backtitle "$BACKTITLE" --title "Setup Complete" \
                --msgbox "$complete_msg" "$DLG_ROWS" "$DLG_COLS" --scrolltext
        else
            local complete_msg="Vulcan setup is complete!\n\nStack written to stack/docker-compose.yml (not started yet).\n\nStart it when ready:\n  docker compose -f stack/docker-compose.yml up -d"
            [ -n "$summary" ] && complete_msg+="\n\n$summary"

            whiptail --backtitle "$BACKTITLE" --title "Setup Complete" \
                --msgbox "$complete_msg" "$DLG_ROWS" "$DLG_COLS" --scrolltext
        fi
    else
        log_error "Guided setup failed (exit $rc)"
    fi

    return "$rc"
}

# Quick path: tier's own default services, plus the same individual
# opt-in/opt-out toggles TierConfigScreen's "Continue" button offered
# (no --services override, no domain/Traefik/Authelia - those need
# the customize path below, matching the old TUI's own split between
# TierConfigScreen and ServiceSelectionScreen exactly).
_guided_setup_quick_toggles() {

    local prev_optional=",${PREVIOUS_ENABLED_OPTIONAL},"

    _default_on() {
        local svc="$1" fresh_default_on="$2"
        if [ -n "$PREVIOUS_TIER" ]; then
            [[ "$prev_optional" == *",$svc,"* ]] && echo ON || echo OFF
        else
            [ "$fresh_default_on" = "on" ] && echo ON || echo OFF
        fi
    }

    local -a all_optional_keys=(gluetun sabnzbd recyclarr homepage metube downtify netdata vaultwarden dashy pihole sportarr tracearr threadfin cloudflared)

    if whiptail --backtitle "$BACKTITLE" --title "Optional Services - Select All?" \
        --yesno "Enable ALL optional services? (Gluetun, SABnzbd, Recyclarr, Homepage, MeTube, Downtify, Netdata, Vaultwarden, Dashy, Pi-hole, Sportarr, Tracearr, Threadfin)\n\nChoose No to pick individually instead." \
        "$DLG_ROWS" "$DLG_COLS" --defaultno; then

        SELECTED=("${all_optional_keys[@]}")
    else

        CHOSEN=$(whiptail --backtitle "$BACKTITLE" --title "Optional Services" \
            --checklist "Choose optional services to enable:" "$DLG_ROWS" "$DLG_COLS" "$DLG_ITEMS" \
            "gluetun"     "VPN for torrent traffic (recommended)"  "$(_default_on gluetun off)" \
            "sabnzbd"     "SABnzbd - Usenet downloader"            "$(_default_on sabnzbd off)" \
            "recyclarr"   "Recyclarr - TRaSH Guides sync"          "$(_default_on recyclarr off)" \
            "homepage"    "Homepage dashboard"                     "$(_default_on homepage on)" \
            "metube"      "MeTube - video downloader"               "$(_default_on metube off)" \
            "downtify"    "Downtify - Spotify downloader"           "$(_default_on downtify off)" \
            "netdata"     "Netdata - system monitoring"             "$(_default_on netdata off)" \
            "vaultwarden" "Vaultwarden - password manager"          "$(_default_on vaultwarden off)" \
            "dashy"       "Dashy - second dashboard"                "$(_default_on dashy off)" \
            "pihole"      "Pi-hole + Unbound (DNS ad-blocker)"      "$(_default_on pihole off)" \
            "sportarr"    "Sportarr - sports PVR"                   "$(_default_on sportarr off)" \
            "tracearr"    "Tracearr - stream analytics"             "$(_default_on tracearr off)" \
            "threadfin"   "Threadfin - IPTV proxy for live TV"     "$(_default_on threadfin off)" \
            "cloudflared" "Cloudflare Tunnel (needs tunnel token)" "$(_default_on cloudflared off)" \
            3>&1 1>&2 2>&3) || CHOSEN=""

        # whiptail's own --checklist output is a properly double-quoted,
        # space-separated tag list (e.g. `"gluetun" "homepage"`) - eval is
        # the standard, safe idiom for turning that into a real bash array,
        # since the quoting is whiptail's own, not unsanitized user input.
        # Static analysis can't trace an eval'd assignment, hence the disables below:
        # shellcheck disable=SC2034,SC2154
        eval "SELECTED=($CHOSEN)"
    fi

    _has() {
        local needle="$1" item
        for item in "${SELECTED[@]:-}"; do
            [ "$item" = "$needle" ] && return 0
        done
        return 1
    }

    _has gluetun     && TOGGLE_FLAGS+=(--vpn)        || TOGGLE_FLAGS+=(--no-vpn)
    _has sabnzbd     && TOGGLE_FLAGS+=(--sabnzbd)    || TOGGLE_FLAGS+=(--no-sabnzbd)
    _has recyclarr   && TOGGLE_FLAGS+=(--recyclarr)  || TOGGLE_FLAGS+=(--no-recyclarr)
    _has homepage    && TOGGLE_FLAGS+=(--homepage)   || TOGGLE_FLAGS+=(--no-homepage)
    _has metube      && TOGGLE_FLAGS+=(--metube)     || TOGGLE_FLAGS+=(--no-metube)
    _has downtify    && TOGGLE_FLAGS+=(--downtify)   || TOGGLE_FLAGS+=(--no-downtify)
    _has netdata     && TOGGLE_FLAGS+=(--netdata)    || TOGGLE_FLAGS+=(--no-netdata)
    _has vaultwarden && TOGGLE_FLAGS+=(--vaultwarden) || TOGGLE_FLAGS+=(--no-vaultwarden)
    _has dashy       && TOGGLE_FLAGS+=(--dashy)      || TOGGLE_FLAGS+=(--no-dashy)
    _has pihole      && TOGGLE_FLAGS+=(--pihole)     || TOGGLE_FLAGS+=(--no-pihole)
    _has sportarr    && TOGGLE_FLAGS+=(--sportarr)   || TOGGLE_FLAGS+=(--no-sportarr)
    _has tracearr    && TOGGLE_FLAGS+=(--tracearr)   || TOGGLE_FLAGS+=(--no-tracearr)
    _has threadfin   && TOGGLE_FLAGS+=(--threadfin)  || TOGGLE_FLAGS+=(--no-threadfin)
    _has cloudflared && TOGGLE_FLAGS+=(--cloudflared) || TOGGLE_FLAGS+=(--no-cloudflared)

    if [ "$TIER" = "heavy" ] && [ -n "$GPU_VENDOR" ]; then
        if whiptail --backtitle "$BACKTITLE" --title "GPU Passthrough" \
            --yesno "Enable GPU passthrough for Jellyfin hardware transcoding? Detected: $GPU_VENDOR" "$DLG_ROWS" "$DLG_COLS"; then
            TOGGLE_FLAGS+=(--gpu)
        else
            TOGGLE_FLAGS+=(--no-gpu)
        fi
    fi
}

# Customize path: the full ALL_SERVICES list via --services=, the
# bash-native version of ServiceSelectionScreen - the only path that
# can reach Traefik/Authelia/CrowdSec/Tailscale/Decluttarr/
# Maintainerr/Lidarr/Readarr, matching the CLI's own real gating
# (_gather_generation_config() only asks about --domain at all when
# "traefik" is in an explicit --services list, confirmed by reading
# installer/cli.py directly).
#
# Default checkbox state is a real simplification, noted honestly:
# defaults to each service's previous on/off state on a rerun, or (on
# a fresh install) ON only for the five services required at every
# tier (jellyfin/radarr/sonarr/prowlarr/qbittorrent) - not a full
# per-tier-aware default the way ServiceSelectionScreen's Python-side
# `chosen_tier.services` computation was. Nothing about *validity* is
# weakened by this - `vulcan`'s own --services parsing still rejects
# any unknown key - only the starting checkbox convenience is
# simpler here.
_guided_setup_customize_services() {

    local prev_custom=",${PREVIOUS_ENABLED_OPTIONAL},"
    local core=",jellyfin,radarr,sonarr,prowlarr,qbittorrent,"

    _svc_on() {
        local svc="$1"
        if [ -n "$PREVIOUS_TIER" ]; then
            [[ "$prev_custom" == *",$svc,"* ]] && echo ON || echo OFF
        else
            [[ "$core" == *",$svc,"* ]] && echo ON || echo OFF
        fi
    }

    # Services grouped by category (matches tiers.py ServiceDefinition.category)
    # Format: key:display_name:category
    local -a SERVICE_LIST=(
        "jellyfin:Jellyfin (media server):Media Server"
        "seerr:Seerr (media requests):Media Server"
        "radarr:Radarr (movies):Media Management"
        "sonarr:Sonarr (TV):Media Management"
        "lidarr:Lidarr (music):Media Management"
        "readarr:Readarr (books):Media Management"
        "prowlarr:Prowlarr (indexers):Media Management"
        "bazarr:Bazarr (subtitles):Media Management"
        "flaresolverr:FlareSolverr:Media Management"
        "recyclarr:Recyclarr (TRaSH sync):Media Management"
        "decluttarr:Decluttarr (download queue cleanup):Media Management"
        "maintainerr:Maintainerr (library cleanup):Media Management"
        "sportarr:Sportarr (sports PVR):Media Management"
        "qbittorrent:qBittorrent:Downloaders"
        "sabnzbd:SABnzbd (Usenet):Downloaders"
        "metube:MeTube (video downloader):Downloaders"
        "downtify:Downtify (Spotify downloader):Downloaders"
        "uptime-kuma:Uptime Kuma (monitoring):Monitoring"
        "tracearr:Tracearr (stream analytics):Monitoring"
        "netdata:Netdata (system monitoring):Monitoring"
        "gluetun:Gluetun (VPN):Infrastructure"
        "pihole:Pi-hole + Unbound (DNS ad-blocker):Infrastructure"
        "traefik:Traefik (reverse proxy):Infrastructure"
        "cloudflared:Cloudflare Tunnel:Infrastructure"
        "tailscale:Tailscale (private remote access):Infrastructure"
        "authelia:Authelia (authentication):Security"
        "crowdsec:CrowdSec (intrusion protection):Security"
        "vaultwarden:Vaultwarden (password manager):Security"
        "homepage:Homepage/Homarr dashboard:Dashboards"
        "dashy:Dashy dashboard:Dashboards"
        "watchtower:Watchtower (auto-updates):Utilities"
        "filebrowser:FileBrowser (file manager):Utilities"
        "threadfin:Threadfin (IPTV proxy):Live TV"
    )

    # Build category -> services map
    declare -A CATEGORY_SERVICES
    local -a CATEGORIES=()
    local entry key display category
    for entry in "${SERVICE_LIST[@]}"; do
        IFS=':' read -r key display category <<< "$entry"
        if [[ -z "${CATEGORY_SERVICES[$category]:-}" ]]; then
            CATEGORIES+=("$category")
        fi
        CATEGORY_SERVICES["$category"]+="${CATEGORY_SERVICES[$category]:+,}$entry"
    done

    # Selected services accumulator
    declare -A SELECTED_MAP
    local joined="${PREVIOUS_ENABLED_OPTIONAL:-}"

    # Seed from previous or core
    if [ -n "$PREVIOUS_TIER" ]; then
        IFS=',' read -ra prev <<< "$PREVIOUS_ENABLED_OPTIONAL"
        for svc in "${prev[@]}"; do
            SELECTED_MAP["$svc"]=1
        done
    else
        IFS=',' read -ra core_svcs <<< "jellyfin,radarr,sonarr,prowlarr,qbittorrent"
        for svc in "${core_svcs[@]}"; do
            SELECTED_MAP["$svc"]=1
        done
    fi

    # Category selection loop - one screen per category
    while true; do
        # Count total selected across all categories
        local selected_total=0
        for svc in "${!SELECTED_MAP[@]}"; do
            ((selected_total++))
        done

        local -a cat_menu=()
        for cat in "${CATEGORIES[@]}"; do
            # Count selected in this category
            local selected_count=0
            IFS=',' read -ra cat_svcs <<< "${CATEGORY_SERVICES[$cat]}"
            for svc_entry in "${cat_svcs[@]}"; do
                IFS=':' read -r svc_key svc_display svc_cat <<< "$svc_entry"
                [[ -n "${SELECTED_MAP[$svc_key]:-}" ]] && ((selected_count++))
            done
            local total_count=${#cat_svcs[@]}
            cat_menu+=("$cat" "$cat ($selected_count/$total_count selected)")
        done
        cat_menu+=("done" "Done - Continue to next step")

        local cat_choice
        cat_choice=$(whiptail --backtitle "$BACKTITLE" --title "Customize Services - Select Category" \
            --menu "Choose a category to configure services. $selected_total of ${#SERVICE_LIST[@]} services selected.\n\n(Blank = not selected, ✓ = selected)" "$DLG_ROWS" "$DLG_COLS" "$DLG_ITEMS" \
            "${cat_menu[@]}" \
            3>&1 1>&2 2>&3) || return 1

        [ "$cat_choice" = "done" ] && break

        # Show checklist for this category
        local -a cat_checklist=()
        local -a cat_keys=()
        IFS=',' read -ra cat_svcs <<< "${CATEGORY_SERVICES[$cat_choice]}"
        for svc_entry in "${cat_svcs[@]}"; do
            IFS=':' read -r svc_key svc_display svc_cat <<< "$svc_entry"
            cat_checklist+=("$svc_key" "$svc_display" "$(_svc_on "$svc_key")")
            cat_keys+=("$svc_key")
        done

        # Add "Select All" / "Deselect All" pseudo-items at top
        cat_checklist=("__select_all__" "✓ Select ALL in this category" "OFF" "__deselect_all__" "✗ Deselect ALL in this category" "OFF" "${cat_checklist[@]}")

        local cat_chosen
        cat_chosen=$(whiptail --backtitle "$BACKTITLE" --title "Customize: $cat_choice" \
            --checklist "Select services in this category (use Select All / Deselect All):" "$DLG_ROWS" "$DLG_COLS" "$DLG_ITEMS" \
            "${cat_checklist[@]}" \
            3>&1 1>&2 2>&3) || cat_chosen=""

        # Update selection map for this category
        # First clear all in this category
        IFS=',' read -ra cat_svcs <<< "${CATEGORY_SERVICES[$cat_choice]}"
        for svc_entry in "${cat_svcs[@]}"; do
            IFS=':' read -r svc_key svc_display svc_cat <<< "$svc_entry"
            unset SELECTED_MAP["$svc_key"]
        done
        # Then set chosen ones (filter out pseudo-items)
        eval "local -a cat_selected=($cat_chosen)"
        for svc in "${cat_selected[@]}"; do
            if [[ "$svc" != "__select_all__" && "$svc" != "__deselect_all__" ]]; then
                SELECTED_MAP["$svc"]=1
            fi
        done
        # Handle Select All / Deselect All
        for svc in "${cat_selected[@]}"; do
            if [[ "$svc" == "__select_all__" ]]; then
                for key in "${cat_keys[@]}"; do
                    SELECTED_MAP["$key"]=1
                done
            elif [[ "$svc" == "__deselect_all__" ]]; then
                for key in "${cat_keys[@]}"; do
                    unset SELECTED_MAP["$key"]
                done
            fi
        done
    done

    # Build final joined list
    local joined=""
    local item

    # Auto-enable dependencies before building final list
    # cloudflared requires traefik
    if [[ -n "${SELECTED_MAP[cloudflared]:-}" ]] && [[ -z "${SELECTED_MAP[traefik]:-}" ]]; then
        SELECTED_MAP[traefik]=1
    fi
    # authelia requires traefik
    if [[ -n "${SELECTED_MAP[authelia]:-}" ]] && [[ -z "${SELECTED_MAP[traefik]:-}" ]]; then
        SELECTED_MAP[traefik]=1
    fi
    # crowdsec requires traefik
    if [[ -n "${SELECTED_MAP[crowdsec]:-}" ]] && [[ -z "${SELECTED_MAP[traefik]:-}" ]]; then
        SELECTED_MAP[traefik]=1
    fi

    for item in "${!SELECTED_MAP[@]}"; do
        joined="${joined:+$joined,}$item"
    done

    SERVICES_FLAG=(--services "$joined")

    local has_traefik=false
    for item in "${SELECTED[@]:-}"; do
        [ "$item" = "traefik" ] && has_traefik=true
    done

    if [ "$has_traefik" = true ]; then

        DOMAIN=$(whiptail --backtitle "$BACKTITLE" --title "Domain Routing" \
            --inputbox "Base domain for Traefik routing, e.g. media.example.com (leave blank to skip - Traefik uses a self-signed cert either way)" \
            "$DLG_ROWS" "$DLG_COLS" "$PREVIOUS_DOMAIN" \
            3>&1 1>&2 2>&3) || DOMAIN=""

        if [ -n "$DOMAIN" ]; then

            DOMAIN_FLAGS+=(--domain "$DOMAIN")

            if whiptail --backtitle "$BACKTITLE" --title "Cloudflare DNS" \
                --yesno "Is this domain's DNS managed by Cloudflare? (real Let's Encrypt certs via DNS-01, instead of Traefik's self-signed default)" "$DLG_ROWS" "$DLG_COLS"; then

                CF_EMAIL=$(whiptail --backtitle "$BACKTITLE" --title "Cloudflare DNS" \
                    --inputbox "Contact email for Let's Encrypt" "$DLG_ROWS" "$DLG_COLS" "$PREVIOUS_CLOUDFLARE_EMAIL" \
                    3>&1 1>&2 2>&3) || CF_EMAIL=""

                DOMAIN_FLAGS+=(--cloudflare-dns --cloudflare-email "$CF_EMAIL")
            fi
        fi
    fi

    if [[ ",$joined," == *",authelia,"* ]]; then

        AUTH_USER=$(whiptail --backtitle "$BACKTITLE" --title "Authelia" \
            --inputbox "Authelia admin username" "$DLG_ROWS" "$DLG_COLS" "admin" \
            3>&1 1>&2 2>&3) || AUTH_USER=""

        if [ -n "$AUTH_USER" ]; then

            AUTH_PASS=$(whiptail --backtitle "$BACKTITLE" --title "Authelia" \
                --passwordbox "Authelia admin password (won't be shown again)" "$DLG_ROWS" "$DLG_COLS" \
                3>&1 1>&2 2>&3) || AUTH_PASS=""

            if [ -n "$AUTH_PASS" ]; then
                DOMAIN_FLAGS+=(--auth-username "$AUTH_USER" --auth-password "$AUTH_PASS")
            fi
        fi
    fi
}

# --- Entry point -----------------------------------------------------
#
# Guarded so `tests/test_menu.bats` can `source` this file to unit
# test the argv-building functions (_guided_setup_quick_toggles,
# _guided_setup_customize_services, confirm_and_run) without
# triggering the whiptail-presence check or the interactive Main Menu
# loop - the same "keep logic out of the untestable shell" split this
# project's Python CLI/TUI code already follows.
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then

    # type -P, not command -v: this script defines its own `whiptail`
    # shell function a few dozen lines up (the --fullbuttons wrapper),
    # and `command -v` reports functions as a match too - it would
    # always "find" whiptail here even with the real binary missing.
    # -P forces a real PATH search, ignoring functions/aliases/builtins.
    if ! type -P whiptail >/dev/null 2>&1; then

        echo "whiptail not found - installing it (needed for this menu)..."
        SUDO=""
        [ "$EUID" -ne 0 ] && SUDO="sudo"

        if command -v apt-get >/dev/null 2>&1; then
            $SUDO apt-get update -qq && $SUDO apt-get install -y whiptail
        elif command -v dnf >/dev/null 2>&1; then
            $SUDO dnf install -y newt
        elif command -v pacman >/dev/null 2>&1; then
            $SUDO pacman -Sy --noconfirm libnewt
        elif command -v zypper >/dev/null 2>&1; then
            $SUDO zypper install -y newt
        elif command -v apk >/dev/null 2>&1; then
            $SUDO apk add --no-cache newt
        fi

        if ! type -P whiptail >/dev/null 2>&1; then
            echo "whiptail is required but could not be auto-installed. Install it manually (Debian/Ubuntu: whiptail, Fedora/RHEL: newt, Arch: libnewt, openSUSE: newt) and try again." >&2
            exit 1
        fi
    fi

    # Preserve old log on each run (Security Onion pattern).
    [ -f "$SETUP_LOG" ] && mv "$SETUP_LOG" "$SETUP_LOG.$(date +%Y%m%d%H%M%S)" 2>/dev/null

    # Trap unhandled errors - show the failed screen before exiting.
    trap 'log_error "Unhandled error on line $LINENO"; whiptail --backtitle "$BACKTITLE" --title "Error" --msgbox "Unexpected error. Check log:\n$SETUP_LOG" "$DLG_ROWS" "$DLG_COLS" 2>/dev/null; exit 1' ERR

    # First run (no stack yet) skips the Main Menu entirely and drops
    # straight into Guided Setup, matching Security Onion's so-setup -
    # a single linear wizard, not a menu to pick from. The Main Menu
    # only appears once a stack exists, for the real day-2 operations
    # (start/stop/status/update/backup) so-setup's own one-shot model
    # never needed.
    refresh_detect

    if [ "$STACK_EXISTS" = "true" ]; then
        main_menu
    else
        guided_setup
    fi
fi
