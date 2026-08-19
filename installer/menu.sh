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
# arbitrary hex) - "red" is the closest named match to Vulcan's real
# brand accent, "ember" (#ff5f1f in docs/images/logo.svg and the
# website), so the installer now reads as the same project as its own
# README/site instead of an arbitrary whiptail-safe cyan.
# button/checkbox/listbox all used black,red for BOTH their focused and
# unfocused state - identical to window's own black,red background, so an
# unfocused Yes/No button (or an unselected list row) was visually
# indistinguishable from empty dialog space, and red-on-white for the
# focused state renders too close to that same background on some terminal
# color profiles (reported: couldn't tell which of Yes/No was highlighted,
# even with Tab/arrow keys). Every interactive element below now has its
# own visible box (red,black) at rest and a yellow background - the one
# color that reliably shows up against black, red, and window alike -
# when focused.
export NEWT_COLORS='
root=white,black
border=red,black
window=black,red
shadow=black,black
title=black,red
button=red,black
actbutton=black,yellow
checkbox=red,black
actcheckbox=black,yellow
entry=black,red
label=white,black
listbox=red,black
actlistbox=black,yellow
sellistbox=red,black
actsellistbox=black,yellow
textbox=black,red
acttextbox=black,red
helpline=white,black
roottext=white,black
emptyscale=,black
fullscale=,red
disabledentry=gray,red
compactbutton=red,black
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
        --yesno "$confirm_text" 14 76; then
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
        echo "Done."
    else
        echo "Failed (exit $status) - see output above."
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
main_menu() {
    while true; do

        CHOICE=$(whiptail --backtitle "$BACKTITLE" --title "Vulcan" \
            --menu "Choose an action:" 21 76 10 \
            "guided-setup"    "1. Guided Setup - detect hardware, generate a stack (new install)" \
            "storage-setup"   "2. Media Storage Setup - provision blank drives as media storage (new install)" \
            "start-stack"     "3. Start Stack - start an already-generated stack" \
            "update-stack"    "4. Update Stack - pull latest images, recreate containers" \
            "pull-images"     "5. Pull Images - prep for an offline start later" \
            "backup-stack"    "6. Backup Stack - archive config/compose/env to backups/" \
            "restore-stack"   "7. Restore Stack - from the most recent backup" \
            "uninstall-stack" "8. Uninstall Stack - stop and delete stack/ entirely" \
            "update-self"     "9. Update Vulcan - fast-forward this checkout" \
            "exit"            "0. Exit" \
            3>&1 1>&2 2>&3)
        status=$?

        if [ "$status" -ne 0 ] || [ "$CHOICE" = "exit" ]; then
            clear
            exit 0
        fi

        case "$CHOICE" in
            guided-setup)
                guided_setup
                ;;
            storage-setup)
                storage_setup_flow
                ;;
            start-stack)
                confirm_and_run "Start Stack" \
                    "This will start stack/docker-compose.yml, reassigning any port already in use." \
                    "$VULCAN_BIN" start
                ;;
            update-stack)
                confirm_and_run "Update Stack" \
                    "This will pull the latest images and recreate containers for stack/docker-compose.yml." \
                    "$VULCAN_BIN" update --non-interactive --yes
                ;;
            pull-images)
                confirm_and_run "Pull Images" \
                    "This will pull images for stack/docker-compose.yml without starting anything." \
                    "$VULCAN_BIN" pull
                ;;
            backup-stack)
                confirm_and_run "Backup Stack" \
                    "This will archive stack/config/ and the compose/env files to backups/." \
                    "$VULCAN_BIN" backup
                ;;
            restore-stack)
                restore_stack_flow
                ;;
            uninstall-stack)
                uninstall_flow
                ;;
            update-self)
                confirm_and_run "Update Vulcan" \
                    "This will fast-forward this Vulcan checkout to the latest origin/main." \
                    "$VULCAN_BIN" update-self --non-interactive --yes
                ;;
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

    if [ -z "$BLANK_STORAGE_DEVICES" ]; then
        whiptail --backtitle "$BACKTITLE" --title "Media Storage Setup" \
            --msgbox "No blank, unprotected storage devices found. A blank device is one with no filesystem and no partition table, and not backing / or /boot." 12 76
        return 0
    fi

    local default_mount_point="/mnt/media"

    MEDIA_MOUNT_POINT=$(whiptail --backtitle "$BACKTITLE" --title "Media Storage Setup" \
        --inputbox "Mount point for the media storage volume" 10 70 "$default_mount_point" \
        3>&1 1>&2 2>&3) || return 0
    [ -z "$MEDIA_MOUNT_POINT" ] && return 0

    # BLANK_STORAGE_DEVICES is a comma-separated list (e.g.
    # /dev/sdb,/dev/sdc) - turn it into a real bash array, then build a
    # whiptail --checklist with every blank device pre-selected (they're
    # blank, so there's nothing to wipe - selecting them by default
    # matches the "identify available blank storage" intent, and the
    # user can still deselect any they want to keep spare).
    local -a blank_devices
    IFS=',' read -r -a blank_devices <<< "$BLANK_STORAGE_DEVICES"

    local -a checklist_args=()
    local device
    for device in "${blank_devices[@]:-}"; do
        checklist_args+=( "$device" "blank storage device" "ON" )
    done

    CHOSEN_DEVICES=$(whiptail --backtitle "$BACKTITLE" --title "Media Storage Setup" \
        --checklist "Select which blank device(s) to provision as media storage:" 16 76 6 \
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

    # The CLI offers the RAID picker only in interactive mode; from the
    # menu it runs --non-interactive, so the choice is gathered here and
    # passed through as --raid-level. Mirrors the engine's own option
    # table (_raid_level_options in installer/storage.py): a real
    # radiolist only when there's more than one valid option (4+
    # devices); 3 devices has RAID5 as the only choice, and 1-2 devices
    # have no picker at all (single ext4 / RAID1 by the engine's own
    # default), so those cases just state what will happen.
    if [ "$device_count" -ge 4 ]; then

        RAID_LEVEL=$(whiptail --backtitle "$BACKTITLE" --title "Media Storage Setup" \
            --radiolist "Choose a RAID level for these $device_count devices:" 14 76 3 \
            "5"  "RAID5 - ~$((device_count - 1)) of $device_count drives usable, survives 1 drive failure (recommended)" "ON" \
            "6"  "RAID6 - ~$((device_count - 2)) of $device_count drives usable, survives 2 drive failures" "OFF" \
            "10" "RAID10 - ~$((device_count / 2)) of $device_count drives usable, survives 1 drive per pair" "OFF" \
            3>&1 1>&2 2>&3) || return 0

        raid_level="$RAID_LEVEL"
        level_summary="mdadm RAID$RAID_LEVEL"
    elif [ "$device_count" -eq 3 ]; then
        level_summary="mdadm RAID5"
    elif [ "$device_count" -eq 2 ]; then
        level_summary="mdadm RAID1"
    else
        level_summary="a single ext4 volume"
    fi

    local raid_flag=()
    [ -n "$raid_level" ] && raid_flag=(--raid-level "$raid_level")

    confirm_and_run "Media Storage Setup" \
        "This will provision $devices_csv into a single volume mounted at $MEDIA_MOUNT_POINT as $level_summary. Continue?" \
        "$VULCAN_BIN" storage apply --devices "$devices_csv" --mount-point "$MEDIA_MOUNT_POINT" --non-interactive --yes "${raid_flag[@]}"
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
        --yesno "Start the restored stack immediately after restoring?" 10 70; then
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
        --yesno "Also delete backups/ and exports/? (default: No - leave your backup archives in place)" 10 70 --defaultno; then
        purge_flags=(--purge-artifacts)
    fi

    if whiptail --backtitle "$BACKTITLE" --title "Uninstall Stack" \
        --yesno "Also run 'docker system prune -a' afterward? Reclaims disk space, but affects the whole Docker host, not just vulcan's containers. (default: No)" 10 70 --defaultno; then
        prune_flags=(--prune-docker)
    fi

    confirm_and_run "Uninstall Stack" \
        "This will stop the running stack (if any) and permanently delete stack/ (containers, network, and all app config/data). Your media library is always left untouched." \
        "$VULCAN_BIN" uninstall --non-interactive --yes "${purge_flags[@]}" "${prune_flags[@]}"
}

# --- Guided Setup ------------------------------------------------------
#
# The bash-native version of WelcomeScreen -> TierConfigScreen ->
# ReviewScreen (quick path) and, optionally, -> ServiceSelectionScreen
# (customize path). Ends by handing a single fully-formed
# `vulcan --non-interactive --yes ...` invocation to confirm_and_run -
# no generation logic lives here, only gathering the same choices the
# old TUI screens gathered.
guided_setup() {

    # --- Welcome screen (Security Onion pattern) ---
    if ! whiptail --backtitle "$BACKTITLE" --title "Welcome" --yesno \
        "Welcome to the Vulcan Setup!\n\nVulcan will detect your hardware and recommend the best\nconfiguration for a self-hosted media stack.\n\nSetup uses keyboard navigation:\n  Arrow keys to move around\n  Enter to select\n  Tab to switch between buttons\n\nWould you like to continue?" 20 76; then
        return 0
    fi
    log_title "Starting Guided Setup"
    log_info "User entered guided setup"

    log_title "Phase 1: System Detection"
    refresh_detect
    log_info "CPU: ${CPU_CORES_LOGICAL:-0} logical cores, RAM: ${RAM_TOTAL_GB:-0}GB, Disk free: ${DISK_FREE_GB:-0}GB"
    log_info "Docker: installed=$DOCKER_INSTALLED running=$DOCKER_RUNNING compose=$DOCKER_COMPOSE_V2"
    log_info "Recommended tier: ${RECOMMENDED_TIER:-none}"

    if [ "$DOCKER_INSTALLED" != "true" ] || [ "$DOCKER_RUNNING" != "true" ] || [ "$DOCKER_COMPOSE_V2" != "true" ]; then
        log_info "Docker not fully ready, showing warning"
        whiptail --backtitle "$BACKTITLE" --title "Docker" --msgbox \
            "Docker isn't fully ready yet (installed=$DOCKER_INSTALLED running=$DOCKER_RUNNING compose-v2=$DOCKER_COMPOSE_V2). Continuing will let Vulcan try to install/start it for you (--yes is implied)." 12 76
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
        --inputbox "Where should your media library live?" 10 70 "$default_media_path" \
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
        18 76 3 \
        "light"  "Light - low-resource baseline" "$light_on" \
        "medium" "Medium - the common case" "$medium_on" \
        "heavy"  "Heavy - full stack, GPU transcoding, more services" "$heavy_on" \
        3>&1 1>&2 2>&3) || return

    local customize=false

    if whiptail --backtitle "$BACKTITLE" --title "Services" \
        --yesno "Customize the full service list? (adds Traefik/Authelia domain routing, CrowdSec, Tailscale, Decluttarr, Maintainerr, and more)\n\nChoose No for the common case - just the tier's usual services plus the toggles on the next screen." \
        14 76 --defaultno; then
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
        --inputbox "PUID - user ID the containers run as (matters for file ownership on your media library)" 10 70 "$default_puid_value" \
        3>&1 1>&2 2>&3) || return

    PGID=$(whiptail --backtitle "$BACKTITLE" --title "User/Group" \
        --inputbox "PGID - group ID the containers run as" 10 70 "$default_pgid_value" \
        3>&1 1>&2 2>&3) || return

    TIMEZONE=$(whiptail --backtitle "$BACKTITLE" --title "Timezone" \
        --inputbox "IANA timezone name (e.g. America/New_York)" 10 70 "$default_tz_value" \
        3>&1 1>&2 2>&3) || return

    START_FLAG="--no-start"
    if whiptail --backtitle "$BACKTITLE" --title "Start Now" \
        --yesno "Start the stack now, right after generating it?" 10 70; then
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
        --yesno "$summary" 20 76 --scrolltext; then
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

        # --- Setup Complete (Security Onion pattern) ---
        if [ "$START_FLAG" = "--start" ]; then

            local urls
            urls=$("$VULCAN_BIN" urls 2>/dev/null)

            local complete_msg="Vulcan setup is complete!\n\nYour stack is running."
            [ -n "$urls" ] && complete_msg+="\n\nService URLs:\n$urls"
            complete_msg+="\n\nTo manage your stack:\n  docker compose -f stack/docker-compose.yml ps\n  docker compose -f stack/docker-compose.yml down"

            local landing_note="Not sure where to start? "
            if echo "$urls" | grep -q "Homepage"; then
                landing_note+="Open Homepage above - it links out to everything you enabled."
            elif echo "$urls" | grep -q "Dashy"; then
                landing_note+="Open Dashy above - it links out to everything you enabled."
            else
                landing_note+="Jump straight to a service above, or the full walkthrough for setup order and details."
            fi
            complete_msg+="\n\n${landing_note}\nFull walkthrough: https://github.com/Cyb3rRon1n/vulcan/blob/main/docs/walkthrough.md"

            whiptail --backtitle "$BACKTITLE" --title "Setup Complete" \
                --msgbox "$complete_msg" 26 76 --scrolltext
        else
            whiptail --backtitle "$BACKTITLE" --title "Setup Complete" --msgbox \
                "Vulcan setup is complete!\n\nStack written to stack/docker-compose.yml (not started yet).\n\nStart it when ready:\n  docker compose -f stack/docker-compose.yml up -d" 14 76
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

    local -a all_optional_keys=(gluetun sabnzbd recyclarr homepage metube downtify netdata vaultwarden dashy)

    if whiptail --backtitle "$BACKTITLE" --title "Optional Services - Select All?" \
        --yesno "Enable ALL optional services? (Gluetun, SABnzbd, Recyclarr, Homepage, MeTube, Downtify, Netdata, Vaultwarden, Dashy)\n\nChoose No to pick individually instead." \
        12 76 --defaultno; then

        SELECTED=("${all_optional_keys[@]}")
    else

        CHOSEN=$(whiptail --backtitle "$BACKTITLE" --title "Optional Services" \
            --checklist "Choose optional services to enable:" 20 78 9 \
            "gluetun"     "VPN for torrent traffic (recommended)"  "$(_default_on gluetun on)" \
            "sabnzbd"     "SABnzbd - Usenet downloader"            "$(_default_on sabnzbd off)" \
            "recyclarr"   "Recyclarr - TRaSH Guides sync"          "$(_default_on recyclarr off)" \
            "homepage"    "Homepage dashboard"                     "$(_default_on homepage on)" \
            "metube"      "MeTube - video downloader"               "$(_default_on metube off)" \
            "downtify"    "Downtify - Spotify downloader"           "$(_default_on downtify off)" \
            "netdata"     "Netdata - system monitoring"             "$(_default_on netdata off)" \
            "vaultwarden" "Vaultwarden - password manager"          "$(_default_on vaultwarden off)" \
            "dashy"       "Dashy - second dashboard"                "$(_default_on dashy off)" \
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

    if [ "$TIER" = "heavy" ] && [ -n "$GPU_VENDOR" ]; then
        if whiptail --backtitle "$BACKTITLE" --title "GPU Passthrough" \
            --yesno "Enable GPU passthrough for Jellyfin hardware transcoding? Detected: $GPU_VENDOR" 10 70; then
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

    CHOSEN=$(whiptail --backtitle "$BACKTITLE" --title "Customize Services" \
        --checklist "Choose exactly which services to include:" 22 78 14 \
        "jellyfin"    "Jellyfin (media server)"                     "$(_svc_on jellyfin)" \
        "radarr"      "Radarr (movies)"                             "$(_svc_on radarr)" \
        "sonarr"      "Sonarr (TV)"                                 "$(_svc_on sonarr)" \
        "prowlarr"    "Prowlarr (indexers)"                         "$(_svc_on prowlarr)" \
        "qbittorrent" "qBittorrent"                                 "$(_svc_on qbittorrent)" \
        "jellyseerr"  "Jellyseerr (requests)"                       "$(_svc_on jellyseerr)" \
        "bazarr"      "Bazarr (subtitles)"                          "$(_svc_on bazarr)" \
        "flaresolverr" "FlareSolverr"                                "$(_svc_on flaresolverr)" \
        "lidarr"      "Lidarr (music)"                              "$(_svc_on lidarr)" \
        "readarr"     "Readarr (books)"                             "$(_svc_on readarr)" \
        "gluetun"     "Gluetun (VPN)"                                "$(_svc_on gluetun)" \
        "sabnzbd"     "SABnzbd"                                      "$(_svc_on sabnzbd)" \
        "recyclarr"   "Recyclarr"                                    "$(_svc_on recyclarr)" \
        "decluttarr"  "Decluttarr (download queue cleanup)"          "$(_svc_on decluttarr)" \
        "maintainerr" "Maintainerr (library cleanup)"                "$(_svc_on maintainerr)" \
        "homepage"    "Homepage/Homarr dashboard"                    "$(_svc_on homepage)" \
        "dashy"       "Dashy dashboard"                              "$(_svc_on dashy)" \
        "metube"      "MeTube (video downloader)"                    "$(_svc_on metube)" \
        "downtify"    "Downtify (Spotify downloader)"                "$(_svc_on downtify)" \
        "netdata"     "Netdata (system monitoring)"                  "$(_svc_on netdata)" \
        "vaultwarden" "Vaultwarden (password manager)"                "$(_svc_on vaultwarden)" \
        "traefik"     "Reverse proxy (Traefik)"                       "$(_svc_on traefik)" \
        "authelia"    "Authentication (Authelia)"                     "$(_svc_on authelia)" \
        "crowdsec"    "Intrusion protection (CrowdSec)"                "$(_svc_on crowdsec)" \
        "tailscale"   "Tailscale (private remote access)"              "$(_svc_on tailscale)" \
        "uptime-kuma" "Uptime Kuma"                                    "$(_svc_on uptime-kuma)" \
        "watchtower"  "Watchtower"                                     "$(_svc_on watchtower)" \
        3>&1 1>&2 2>&3) || CHOSEN=""

    # whiptail's own --checklist output is a properly double-quoted,
    # space-separated tag list (e.g. `"gluetun" "homepage"`) - eval is
    # the standard, safe idiom for turning that into a real bash array,
    # since the quoting is whiptail's own, not unsanitized user input.
    # Static analysis can't trace an eval'd assignment, hence the disables below:
    # shellcheck disable=SC2034,SC2154
    eval "SELECTED=($CHOSEN)"

    local joined=""
    local item
    for item in "${SELECTED[@]:-}"; do
        [ -z "$item" ] && continue
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
            10 76 "$PREVIOUS_DOMAIN" \
            3>&1 1>&2 2>&3) || DOMAIN=""

        if [ -n "$DOMAIN" ]; then

            DOMAIN_FLAGS+=(--domain "$DOMAIN")

            if whiptail --backtitle "$BACKTITLE" --title "Cloudflare DNS" \
                --yesno "Is this domain's DNS managed by Cloudflare? (real Let's Encrypt certs via DNS-01, instead of Traefik's self-signed default)" 10 76; then

                CF_EMAIL=$(whiptail --backtitle "$BACKTITLE" --title "Cloudflare DNS" \
                    --inputbox "Contact email for Let's Encrypt" 10 70 "$PREVIOUS_CLOUDFLARE_EMAIL" \
                    3>&1 1>&2 2>&3) || CF_EMAIL=""

                DOMAIN_FLAGS+=(--cloudflare-dns --cloudflare-email "$CF_EMAIL")
            fi
        fi
    fi

    if [[ ",$joined," == *",authelia,"* ]]; then

        AUTH_USER=$(whiptail --backtitle "$BACKTITLE" --title "Authelia" \
            --inputbox "Authelia admin username" 10 60 "admin" \
            3>&1 1>&2 2>&3) || AUTH_USER=""

        if [ -n "$AUTH_USER" ]; then

            AUTH_PASS=$(whiptail --backtitle "$BACKTITLE" --title "Authelia" \
                --passwordbox "Authelia admin password (won't be shown again)" 10 60 \
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
    trap 'log_error "Unhandled error on line $LINENO"; whiptail --backtitle "$BACKTITLE" --title "Error" --msgbox "Unexpected error. Check log:\n$SETUP_LOG" 10 76 2>/dev/null; exit 1' ERR

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
