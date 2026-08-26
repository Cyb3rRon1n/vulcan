import getpass
import os
import subprocess
import sys
from pathlib import Path

import typer
from rich.console import Console

from installer import __version__
from installer.auth import hash_authelia_password
from installer.detect import (
    SystemInfo,
    describe_media_redundancy,
    detect_disk,
    detect_docker,
    detect_host_ip,
    detect_media_disk_path,
    detect_media_redundancy,
    detect_storage_mount,
    detect_system,
)
from installer.docker_setup import (
    add_user_to_docker_group,
    check_docker_ready,
    ensure_compose_v2,
    install_docker,
    install_plan_for,
    prune_docker_artifacts,
    run_docker_command,
    start_docker_service,
)
from installer.generate import (
    STACK_DIR,
    WALKTHROUGH_URL,
    GenerationConfig,
    default_puid_pgid,
    default_timezone,
    enabled_service_keys,
    find_next_available_port,
    load_previous_state,
    render_setup_order,
    render_stack_summary,
    resolve_ports,
    write_stack,
)
from installer.post_install import (
    backup_stack,
    export_images,
    import_images,
    latest_backup,
    latest_export,
    pull_stack,
    remove_orphaned_containers,
    restore_stack,
    stack_containers_exist,
    uninstall_stack,
    update_stack,
    verify_stack_running,
)
from installer.preflight import (
    check_network_conflicts,
    check_ports_available,
    format_network_conflicts,
    format_port_conflicts,
)
from installer.panel import RunPanel, _NoOpPanel, progress_panel
from installer.self_update import update_vulcan_self
from installer.storage import (
    _raid_level_options,
    apply_storage_layout,
    apply_storage_teardown,
    describe_raid_option,
    describe_storage_plan,
    describe_storage_teardown,
    device_tree_text,
    identify_protected_devices,
    list_blank_unprotected_devices,
    list_block_devices,
    plan_storage_layout,
    plan_storage_teardown,
)
from installer.tiers import ALL_SERVICES, TIERS, recommend_tier, tier_description


app = typer.Typer(
    name="vulcan",
    help="An intelligent media stack forge - inspects your system and builds a tailored, self-hosted media homelab."
)

# A real sub-app, not a flat vulcan-storage-report command - storage
# provisioning is a deliberately separate, more advanced namespace from
# every other lifecycle command above (report/plan/apply, and their
# teardown counterpart, all more heavily-gated than the rest of the CLI).
storage_app = typer.Typer(
    help="Detect, provision, and tear down real storage on this machine."
)
app.add_typer(storage_app, name="storage")

console = Console()

MENU_SH_PATH = Path(__file__).parent / "menu.sh"


def _launch_menu() -> int:
    """
    Launches the whiptail Main Menu (installer/menu.sh) as a real
    subprocess, not an import - it's bash, not Python. Every choice it
    gathers is handed back to this same `vulcan` binary as a
    --non-interactive --yes invocation (see menu.sh itself), so this
    function owns no interactive logic of its own, only the handoff.
    Returns the script's real exit code so `main()` can propagate it.

    VULCAN_BIN is exported explicitly rather than left to menu.sh's own
    PATH lookup: ./install (the real entry point) execs this venv's
    python directly without activating the venv, so .venv/bin - where
    the `vulcan` console script lives - is not on PATH and a bare
    `vulcan` call would fail. sys.executable is this venv's python, so
    the console script always sits right next to it.
    """

    menu_env = os.environ.copy()
    menu_env["VULCAN_BIN"] = str(Path(sys.executable).parent / "vulcan")

    result = subprocess.run(["bash", str(MENU_SH_PATH)], env=menu_env)
    return result.returncode


@app.command()
def version():
    """
    Display the Vulcan version.
    """

    console.print(
        f"[bold red]Vulcan[/bold red] version {__version__}"
    )


def _shell_quote(value: str) -> str:
    """Single-quoted, safe to eval - escapes any embedded single quotes."""

    return "'" + value.replace("'", "'\\''") + "'"


@app.command(name="detect")
def detect_shell():
    """
    Print real detected system state as KEY=VALUE lines, eval-able from
    bash (`eval "$(vulcan detect)"`). Exists so installer/menu.sh (the
    whiptail front end) can show real specs and a real tier
    recommendation before asking the user anything, the same way the
    old Textual TUI's WelcomeScreen/ConfigScreen did - without
    duplicating any detection logic here. Plain KEY=VALUE rather than
    JSON deliberately - this project has never needed jq before, and
    eval-ing a flat block is pure bash with zero new dependencies.
    """

    previous = load_previous_state(STACK_DIR)

    info = detect_system(
        disk_path=detect_media_disk_path(previous["media_path"] if previous else None)
    )
    recommendation = recommend_tier(info)

    compose_path = STACK_DIR / "docker-compose.yml"
    stack_exists = compose_path.exists() or stack_containers_exist(STACK_DIR.name)
    has_backups = latest_backup() is not None

    default_puid, default_pgid = default_puid_pgid()
    default_tz = default_timezone()

    fields = {
        "CPU_CORES_LOGICAL": info.cpu_cores_logical or 0,
        "CPU_MODEL": info.cpu_model or "unknown",
        "RAM_TOTAL_GB": info.ram_total_gb,
        "DISK_FREE_GB": info.disk_free_gb,
        "GPU_VENDOR": info.gpu_vendor or "",
        "DOCKER_INSTALLED": "true" if info.docker_installed else "false",
        "DOCKER_RUNNING": "true" if info.docker_running else "false",
        "DOCKER_COMPOSE_V2": "true" if info.docker_compose_v2 else "false",
        "OS_ID": info.os_id or "unknown",
        "OS_PRETTY_NAME": info.os_pretty_name or "unknown",
        "OS_IS_ATOMIC": "true" if info.os_is_atomic else "false",
        "RECOMMENDED_TIER": recommendation.tier.name,
        "RECOMMENDED_TIER_MEETS_MINIMUM": "true" if recommendation.meets_minimum else "false",
        "RECOMMENDED_TIER_EXPLANATION": recommendation.explanation,
        # Comma-separated blank, unprotected devices available to be
        # provisioned as media storage - installer/menu.sh's "Media
        # Storage Setup" item builds its whiptail checklist from this.
        "BLANK_STORAGE_DEVICES": ",".join(
            d["path"] for d in list_blank_unprotected_devices()
        ),
        # The provisioned media-storage mount point (default /mnt/media)
        # when one is actually mounted - installer/menu.sh defaults its
        # Guided Setup Media Library path to this on a fresh install.
        "STORAGE_MOUNT": detect_storage_mount() or "",
        "STACK_EXISTS": "true" if stack_exists else "false",
        "HAS_BACKUPS": "true" if has_backups else "false",
        "DEFAULT_PUID": default_puid,
        "DEFAULT_PGID": default_pgid,
        "DEFAULT_TIMEZONE": default_tz,
        # Everything below is blank when there's no previous state -
        # installer/menu.sh uses blank-ness itself as the "is this a
        # rerun?" signal, same role `self.app.previous_state is None`
        # played for the old TierConfigScreen/ServiceSelectionScreen.
        "PREVIOUS_TIER": previous["tier"] if previous else "",
        "PREVIOUS_MEDIA_PATH": previous["media_path"] if previous else "",
        "PREVIOUS_PUID": previous["puid"] if previous else "",
        "PREVIOUS_PGID": previous["pgid"] if previous else "",
        "PREVIOUS_TIMEZONE": previous["timezone"] if previous else "",
        "PREVIOUS_ENABLED_OPTIONAL": ",".join(previous["enabled_optional"]) if previous else "",
        "PREVIOUS_GPU_VENDOR": (previous.get("gpu_vendor") or "") if previous else "",
        "PREVIOUS_DOMAIN": (previous.get("domain") or "") if previous else "",
        "PREVIOUS_CLOUDFLARE_DNS": "true" if (previous and previous.get("cloudflare_dns")) else "false",
        "PREVIOUS_CLOUDFLARE_EMAIL": (previous.get("cloudflare_email") or "") if previous else "",
        "PREVIOUS_HOMEPAGE_PRIVATE": (
            "true" if (previous is None or previous.get("homepage_private", True)) else "false"
        ),
        "PREVIOUS_DASHY_PRIVATE": (
            "true" if (previous is None or previous.get("dashy_private", True)) else "false"
        ),
        "PREVIOUS_GENERATED_AT": (previous.get("generated_at") or "") if previous else "",
    }

    # Plain print(), not console.print() - Rich word-wraps long lines
    # to the terminal width by default, which would corrupt a value
    # like RECOMMENDED_TIER_EXPLANATION mid-eval. This output is meant
    # to be piped/eval-ed, not read as formatted terminal output.
    for key, value in fields.items():
        print(f"{key}={_shell_quote(str(value))}")


def _config_from_previous_state(previous: dict) -> GenerationConfig:
    """
    Rebuilds a real GenerationConfig from saved state - the shared
    piece behind `urls`/`install-summary`, both of which need to
    re-derive real, current stack detail after the fact rather than
    keeping a second, drifting copy of what a real install already
    computed once.
    """

    return GenerationConfig(
        tier=TIERS[previous["tier"]],
        media_path=previous["media_path"],
        puid=previous["puid"],
        pgid=previous["pgid"],
        timezone=previous["timezone"],
        enabled_optional=set(previous["enabled_optional"]),
        gpu_vendor=previous.get("gpu_vendor"),
        custom_services=(
            set(previous["custom_services"]) if previous.get("custom_services") is not None else None
        ),
        domain=previous.get("domain"),
        cloudflare_dns=previous.get("cloudflare_dns", False),
        cloudflare_email=previous.get("cloudflare_email"),
        port_overrides=previous.get("port_overrides", {}),
        homepage_private=previous.get("homepage_private", True),
        dashy_private=previous.get("dashy_private", True),
    )


@app.command(name="urls")
def urls_shell():
    """
    Print real per-service access URLs for the currently-generated
    stack, plain text (one per line) - not eval-able KEY=VALUE like
    `detect`, since installer/menu.sh only needs to display these in a
    whiptail msgbox, not read them into shell variables. Reuses
    render_stack_summary() against a GenerationConfig rebuilt from the
    same saved state `detect`'s PREVIOUS_* fields already read, so the
    URL list is never a second, drifting implementation of what the
    live console output already prints during a real install.
    """

    previous = load_previous_state(STACK_DIR)

    if previous is None:
        return

    config = _config_from_previous_state(previous)

    print(render_stack_summary(config, detect_host_ip()))


@app.command(name="install-summary")
def install_summary_shell():
    """
    Plain-text install detail for the currently-generated stack -
    detected hardware, the chosen tier and what it includes, any
    warnings from the last real `write_stack()` (persisted into
    stack/.vulcan-state.json specifically for this), and the numbered
    setup order. Not eval-able like `detect`; menu.sh's Guided Setup
    prints this into its "Setup Complete" screen instead of the same
    detail scrolling by live under a whiptail progress panel (see
    installer.panel.RunPanel.note()) - moved, not deleted.
    """

    previous = load_previous_state(STACK_DIR)

    if previous is None:
        return

    info = detect_system()
    config = _config_from_previous_state(previous)

    print(
        f"Detected: {info.cpu_cores_logical} logical cores, {info.ram_total_gb}GB RAM, "
        f"GPU: {info.gpu_vendor or 'none detected'}, "
        f"{info.os_pretty_name or info.os_id or 'unknown OS'}"
    )
    print(f"Tier: {config.tier.display_name} - {tier_description(config.tier)}")

    for warning in previous.get("warnings", []):
        print(f"! {warning}")

    setup_order = render_setup_order(config, detect_host_ip())

    if setup_order:
        print()
        print(setup_order)


@storage_app.command(name="report")
def storage_report():
    """
    List real block devices on this machine and which ones are protected
    (currently backing / or /boot) - read-only, never plans or executes anything.
    """

    devices = list_block_devices()

    if not devices:
        console.print("[yellow]No block devices found (or `lsblk` isn't available).[/yellow]")
        raise typer.Exit(code=1)

    protected = identify_protected_devices()

    for disk in devices:

        model = f" ({disk['model']})" if disk.get("model") else ""
        tag = " [red](protected - backs / or /boot)[/red]" if disk["path"] in protected else ""

        console.print(f"{disk['path']}  {disk['size']}{model}{tag}")

        for child in disk.get("children", []) or []:

            fstype = child.get("fstype") or "no filesystem"
            mountpoint = f" -> {child['mountpoint']}" if child.get("mountpoint") else ""
            console.print(f"    {child['path']}  {child['size']}  {fstype}{mountpoint}")


@storage_app.command(name="plan")
def storage_plan(
    devices: str = typer.Option(
        ..., "--devices",
        help="Comma-separated device paths to plan against, e.g. /dev/sdb,/dev/sdc"
    ),
    mount_point: str = typer.Option("/mnt/media", "--mount-point"),
    filesystem: str = typer.Option("ext4", "--filesystem"),
    raid_level: str | None = typer.Option(
        None, "--raid-level", help="mdadm RAID level (1/5/6/10) - only used with 2+ devices"
    )
):
    """
    Show the exact commands that would provision the given device(s) into a
    single mounted volume - mdadm RAID first if 2+ devices, then format and
    mount. Never executes anything; nothing on this machine is touched.
    """

    device_paths = [d.strip() for d in devices.split(",") if d.strip()]

    if not device_paths:
        console.print("[red]--devices requires at least one device path.[/red]")
        raise typer.Exit(code=1)

    plan = plan_storage_layout(device_paths, mount_point, filesystem, raid_level)

    console.print(describe_storage_plan(plan))

    if plan["error"]:
        raise typer.Exit(code=1)


@storage_app.command(name="apply")
def storage_apply(
    devices: str = typer.Option(
        ..., "--devices",
        help="Comma-separated device paths to provision, e.g. /dev/sdb,/dev/sdc"
    ),
    mount_point: str = typer.Option("/mnt/media", "--mount-point"),
    filesystem: str = typer.Option("ext4", "--filesystem"),
    raid_level: str | None = typer.Option(
        None, "--raid-level", help="mdadm RAID level (1/5/6/10) - only used with 2+ devices"
    ),
    non_interactive: bool = typer.Option(False, "--non-interactive"),
    yes: bool = typer.Option(False, "--yes"),
    confirm_wipe: bool = typer.Option(
        False, "--confirm-wipe",
        help="Deliberately destroy data already on the target device(s) - required in "
        "non-interactive mode for devices that have a filesystem or partition table."
    )
):
    """
    Actually provision the given device(s) into a single mounted volume -
    the real mdadm/mkfs/mount run that `vulcan storage plan` only prints.
    Every step is re-checked against live state first, so a re-run on an
    already-provisioned mount is a no-op and a re-run against an existing
    array/filed system resumes instead of re-creating anything.
    """

    device_paths = [d.strip() for d in devices.split(",") if d.strip()]

    if not device_paths:
        console.print("[red]--devices requires at least one device path.[/red]")
        raise typer.Exit(code=1)

    if not non_interactive and raid_level is None and len(device_paths) > 1:

        picked = _choose_raid_level(len(device_paths))

        if picked is None:
            console.print("[red]No valid RAID level chosen - nothing was executed.[/red]")
            raise typer.Exit(code=1)

        raid_level = picked

    plan = plan_storage_layout(device_paths, mount_point, filesystem, raid_level)

    console.print(describe_storage_plan(plan))

    if plan["error"]:
        raise typer.Exit(code=1)

    already_has_data = plan.get("already_has_data", {})
    non_blank = [
        path for path in device_paths if already_has_data.get(path) is True
    ]

    if non_interactive:

        if not yes:
            console.print(
                "[red]--yes is required alongside --non-interactive.[/red]"
            )
            raise typer.Exit(code=1)

        if non_blank and not confirm_wipe:

            console.print(
                f"[red]Refusing: {', '.join(non_blank)} already has a filesystem "
                "or partition table. Re-run with --confirm-wipe to destroy it.[/red]"
            )
            raise typer.Exit(code=1)

    else:

        if non_blank:
            console.print(
                f"[yellow]! {', '.join(non_blank)} already has a filesystem or "
                "partition table - this will destroy it. Type the full device "
                "list to confirm.[/yellow]"
            )

        typed = typer.prompt(
            f"Type the exact device list to confirm ({', '.join(device_paths)})",
            hide_input=False,
        )

        if {p.strip() for p in typed.split(",") if p.strip()} != set(device_paths):

            console.print("[red]Confirmation didn't match - nothing was executed.[/red]")
            raise typer.Exit(code=1)

        confirm_wipe = bool(non_blank)

    result = None

    with progress_panel(
        "Media Storage Setup", ["Provision storage"], console=console
    ) as panel:
        result = apply_storage_layout(plan, confirm_wipe=confirm_wipe)
        panel.advance()

    for command in result.get("ran", []):
        console.print(f"[green]ran:[/green] {command}")

    for note in result.get("skipped", []):
        console.print(f"[cyan]skipped:[/cyan] {note}")

    if not result["success"]:
        console.print(f"[red]{result['error']}[/red]")
        raise typer.Exit(code=1)

    if result.get("already_provisioned"):
        console.print(
            f"[green]{mount_point} is already provisioned from "
            f"{plan['target_device']} - nothing to do.[/green]"
        )
        raise typer.Exit(code=0)

    console.print(
        f"[green]Storage provisioned: {', '.join(device_paths)} is now mounted "
        f"at {mount_point}. Use it as your media path.[/green]"
    )

    tree = device_tree_text(plan["target_device"])

    if tree:
        console.print(tree)


@storage_app.command(name="teardown")
def storage_teardown(
    mount_point: str = typer.Option("/mnt/media", "--mount-point"),
    non_interactive: bool = typer.Option(False, "--non-interactive"),
    yes: bool = typer.Option(False, "--yes"),
    confirm_wipe: bool = typer.Option(
        False, "--confirm-wipe",
        help="Deliberately erase the storage mounted at --mount-point and its "
        "member device(s) - required in non-interactive mode. Unlike `storage "
        "apply`'s --confirm-wipe (only needed when a target device already has "
        "data), this is always required: a teardown is destructive by definition."
    )
):
    """
    Reverse whatever `vulcan storage apply` provisioned at --mount-point:
    unmount, stop the RAID array and zero every member's superblock (if
    it's a RAID array), wipe the array/device and each member, and remove
    the /etc/fstab line - so the member device(s) show up as blank again
    for a future `vulcan storage apply`. There is no undo.
    """

    plan = plan_storage_teardown(mount_point)

    console.print(describe_storage_teardown(plan))

    if plan["error"]:
        raise typer.Exit(code=1)

    if non_interactive:

        if not yes:
            console.print("[red]--yes is required alongside --non-interactive.[/red]")
            raise typer.Exit(code=1)

        if not confirm_wipe:
            console.print(
                "[red]--confirm-wipe is required - a teardown is always "
                "destructive.[/red]"
            )
            raise typer.Exit(code=1)

    else:

        typed = typer.prompt(
            f"Type the mount point to confirm ({mount_point})",
            hide_input=False,
        )

        if typed.strip() != mount_point:
            console.print("[red]Confirmation didn't match - nothing was executed.[/red]")
            raise typer.Exit(code=1)

        confirm_wipe = True

    result = None

    with progress_panel(
        "Media Storage Teardown", ["Tear down storage"], console=console
    ) as panel:
        result = apply_storage_teardown(plan, confirm_wipe=confirm_wipe)
        panel.advance()

    for command in result.get("ran", []):
        console.print(f"[green]ran:[/green] {command}")

    for note in result.get("skipped", []):
        console.print(f"[cyan]skipped:[/cyan] {note}")

    if not result["success"]:
        console.print(f"[red]{result['error']}[/red]")
        raise typer.Exit(code=1)

    console.print(
        f"[green]Storage torn down: {mount_point} is no longer provisioned. "
        "The underlying device(s) are blank again.[/green]"
    )


@app.command()
def update(
    non_interactive: bool = typer.Option(False, "--non-interactive"),
    yes: bool = typer.Option(False, "--yes")
):
    """
    Pull the latest images for the generated stack and recreate containers.
    """

    compose_path = STACK_DIR / "docker-compose.yml"

    if not compose_path.exists():
        console.print("[red]No stack found - run `vulcan` first to generate one.[/red]")
        raise typer.Exit(code=1)

    if non_interactive and not yes:
        console.print("[red]--yes is required alongside --non-interactive.[/red]")
        raise typer.Exit(code=1)

    console.print(f"This will pull the latest images and recreate containers for {compose_path}.")

    if not yes and not typer.confirm("Continue?"):
        console.print("Aborted.")
        raise typer.Exit(code=0)

    result = None

    with progress_panel(
        "Update Stack", ["Pull images", "Recreate containers"], console=console
    ) as panel:
        result = update_stack(
            str(compose_path), str(STACK_DIR / ".env"),
            on_phase=panel.advance
        )
        panel.finish(result["success"])

    if not result["success"]:
        console.print(f"[red]{result['error']}[/red]")
        raise typer.Exit(code=1)

    console.print("[green]Stack updated.[/green]")


@app.command(name="update-self")
def update_self(
    non_interactive: bool = typer.Option(False, "--non-interactive"),
    yes: bool = typer.Option(False, "--yes")
):
    """
    Update Vulcan itself (this checkout) to the latest version on origin/main -
    a plain fast-forward git pull, never a force/reset. Does not touch any
    generated stack.
    """

    if non_interactive and not yes:
        console.print("[red]--yes is required alongside --non-interactive.[/red]")
        raise typer.Exit(code=1)

    console.print("This will fast-forward this Vulcan checkout to the latest origin/main.")

    if not yes and not typer.confirm("Continue?"):
        console.print("Aborted.")
        raise typer.Exit(code=0)

    result = None

    with progress_panel(
        "Update Vulcan", ["Update Vulcan"], console=console
    ) as _panel:
        result = update_vulcan_self()
        _panel.finish(result["success"])

    if not result["success"]:
        console.print(f"[red]{result['error']}[/red]")
        raise typer.Exit(code=1)

    if not result["updated"]:
        console.print(f"[green]Already up to date[/green] ({result['commit']}).")
        return

    console.print(
        f"[green]Updated {result['old_commit']} -> {result['new_commit']}.[/green] "
        "Restart Vulcan to use the new version."
    )


@app.command()
def pull():
    """
    Pull images for the generated stack without starting it - useful to prepare
    a stack for an offline environment ahead of time.
    """

    compose_path = STACK_DIR / "docker-compose.yml"

    if not compose_path.exists():
        console.print("[red]No stack found - run `vulcan` first to generate one.[/red]")
        raise typer.Exit(code=1)

    result = None

    with progress_panel(
        "Pull Images", ["Pull images"], console=console
    ) as _panel:
        result = pull_stack(str(compose_path), str(STACK_DIR / ".env"))
        _panel.finish(result["success"])

    if not result["success"]:
        console.print(f"[red]{result['error']}[/red]")
        raise typer.Exit(code=1)

    console.print(
        "[green]Images pulled.[/green] Run this whenever you're ready - no network "
        f"access needed at that point:\n  docker compose -f {compose_path} --env-file "
        f"{STACK_DIR / '.env'} up -d"
    )


@app.command()
def start():
    """
    Start an already-generated stack, auto-resolving any port
    conflicts against what's actually running on the host first - the
    same check Guided Setup already runs before its own first start,
    available here for restarting a stack later without regenerating
    it by hand (e.g. after a sibling stack's own ports shifted).
    """

    compose_path = STACK_DIR / "docker-compose.yml"

    if not compose_path.exists():
        console.print("[red]No stack found - run `vulcan` first to generate one.[/red]")
        raise typer.Exit(code=1)

    previous = load_previous_state(STACK_DIR)

    if previous is None:
        console.print(
            "[red]No usable state file - run `vulcan` again to regenerate the stack.[/red]"
        )
        raise typer.Exit(code=1)

    info = detect_system()

    config = _gather_generation_config(
        info=info,
        tier=None,
        media_path=None,
        vpn=None,
        sabnzbd=None,
        recyclarr=None,
        homepage=None,
        homepage_private=None,
        metube=None,
        downtify=None,
        netdata=None,
        vaultwarden=None,
        dashy=None,
        dashy_private=None,
        pihole=None,
        gpu=None,
        puid=None,
        pgid=None,
        timezone=None,
        non_interactive=True,
        previous=previous,
        custom_services_from_flag=None,
        domain=None
    )

    result = write_stack(config)

    for warning in result["warnings"]:
        console.print(f"[yellow]! {warning}[/yellow]")

    result = _resolve_port_conflicts(config, result)

    net_check = check_network_conflicts(result["compose_path"])

    if not net_check["ok"]:
        console.print("[red]Network configuration errors (Docker would reject these):[/red]")
        console.print(format_network_conflicts(net_check))
        raise typer.Exit(code=1)

    proc = run_docker_command(
        [
            "docker", "compose",
            "-f", result["compose_path"],
            "--env-file", result["env_path"],
            "up", "-d"
        ]
    )

    if proc.returncode != 0:
        raise typer.Exit(code=proc.returncode)

    verification = verify_stack_running(result["compose_path"])

    if not verification["all_running"]:

        console.print("[red]Stack started but isn't actually running:[/red]")

        if verification["error"]:
            console.print(f"[red]{verification['error']}[/red]")

        for entry in verification["not_running"]:
            console.print(
                f"[red]  {entry['service']}: {entry['state']} ({entry['status']})[/red]"
            )

        console.print("[red]Check `docker compose logs` for the failing service(s).[/red]")
        raise typer.Exit(code=1)

    console.print("[green]Stack is up.[/green]")

    summary = render_stack_summary(config, detect_host_ip())

    if summary:
        console.print(summary)


@app.command()
def backup():
    """
    Archive the generated stack's config directories and compose files.
    """

    result = None

    with progress_panel(
        "Backup Stack", ["Backup stack"], console=console
    ) as _panel:
        result = backup_stack()
        _panel.finish(result["success"])

    if not result["success"]:
        console.print(f"[red]{result['error']}[/red]")
        raise typer.Exit(code=1)

    console.print(f"[green]Backup written to {result['backup_path']}[/green]")

    for warning in result["warnings"]:
        console.print(f"[yellow]! {warning}[/yellow]")


@app.command(name="export")
def export_command(
    output: str | None = typer.Option(
        None, "--output", help="Path for the image tarball; defaults into exports/"
    )
):
    """
    Save the generated stack's already-pulled images to a tarball, to move to a
    machine with no internet access. Run `vulcan pull` first if you haven't already.
    """

    compose_path = STACK_DIR / "docker-compose.yml"
    env_path = STACK_DIR / ".env"

    result = export_images(
        str(compose_path), str(env_path),
        output_path=Path(output) if output is not None else None
    )

    if not result["success"]:
        console.print(f"[red]{result['error']}[/red]")
        raise typer.Exit(code=1)

    console.print(f"[green]Images exported to {result['export_path']}[/green]")


@app.command(name="import")
def import_command(
    tar_file: str = typer.Argument(
        None, help="Path to an image tarball; defaults to the most recent file in exports/"
    )
):
    """
    Load images from a tarball produced by `vulcan export` - works with no
    internet access, doesn't require a generated stack on this machine.
    """

    chosen = Path(tar_file) if tar_file is not None else latest_export()

    if chosen is None:
        console.print("[red]No image archives found in exports/ - pass a path explicitly.[/red]")
        raise typer.Exit(code=1)

    result = import_images(str(chosen))

    if not result["success"]:
        console.print(f"[red]{result['error']}[/red]")
        raise typer.Exit(code=1)

    console.print(f"[green]Images loaded from {chosen}.[/green]")


@app.command()
def restore(
    backup_file: str = typer.Argument(
        None, help="Path to a backup archive; defaults to the most recent file in backups/"
    ),
    non_interactive: bool = typer.Option(False, "--non-interactive"),
    yes: bool = typer.Option(False, "--yes"),
    start: bool | None = typer.Option(None, "--start/--no-start")
):
    """
    Restore stack/config, docker-compose.yml, and .env from a backup archive,
    stopping the current stack first if one is running.
    """

    chosen = Path(backup_file) if backup_file is not None else latest_backup()

    if chosen is None:
        console.print("[red]No backup archives found in backups/ - pass a path explicitly.[/red]")
        raise typer.Exit(code=1)

    if not chosen.exists():
        console.print(f"[red]Backup file not found: {chosen}[/red]")
        raise typer.Exit(code=1)

    if non_interactive and not yes:
        console.print("[red]--yes is required alongside --non-interactive.[/red]")
        raise typer.Exit(code=1)

    compose_path = STACK_DIR / "docker-compose.yml"
    env_path = STACK_DIR / ".env"
    stack_exists = compose_path.exists()

    console.print(
        f"This will restore config/, docker-compose.yml, and .env in {STACK_DIR} from "
        f"[bold]{chosen}[/bold], overwriting what's there now"
        + (", and stop the currently running stack first." if stack_exists else ".")
    )

    if not yes and not typer.confirm("Continue?"):
        console.print("Aborted.")
        raise typer.Exit(code=0)

    # `start` is always explicit in the menu path (--start/--no-start),
    # so the panel's "Start stack" phase is only shown when it will
    # actually run. When start is None the panel is inert anyway (the
    # env var that activates it is only ever set by menu.sh).
    phases = ["Restore stack"]
    if start is True:
        phases.append("Start stack")

    result = None

    with progress_panel("Restore Stack", phases, console=console) as panel:
        result = restore_stack(chosen, str(compose_path), str(env_path))

        if not result["success"]:
            panel.finish(False)
            console.print(f"[red]{result['error']}[/red]")
            raise typer.Exit(code=1)

        console.print("[green]Stack restored.[/green]")

        if start is True:

            proc = run_docker_command(
                ["docker", "compose", "-f", str(compose_path), "--env-file", str(env_path), "up", "-d"]
            )

            if proc.returncode == 0:
                panel.advance()
                console.print("[green]Stack is up.[/green]")
            else:
                panel.finish(False)
                console.print("[red]Failed to start the stack - check `docker compose logs`.[/red]")
                raise typer.Exit(code=1)

    if start is None:
        do_start = False if non_interactive else typer.confirm("Start the restored stack now?", default=True)
    else:
        do_start = start

    if do_start and start is not True:

        proc = run_docker_command(
            ["docker", "compose", "-f", str(compose_path), "--env-file", str(env_path), "up", "-d"]
        )

        if proc.returncode == 0:
            console.print("[green]Stack is up.[/green]")
        else:
            console.print("[red]Failed to start the stack - check `docker compose logs`.[/red]")
            raise typer.Exit(code=1)


@app.command()
def uninstall(
    non_interactive: bool = typer.Option(False, "--non-interactive"),
    yes: bool = typer.Option(False, "--yes"),
    purge_artifacts: bool = typer.Option(
        False, "--purge-artifacts", help="Also delete backups/ and exports/"
    ),
    prune_docker: bool = typer.Option(
        False, "--prune-docker",
        help="Also run `docker system prune -a` after teardown - reclaims disk space "
        "but affects the whole Docker host, not just vulcan's own containers"
    )
):
    """
    Stop the generated stack and permanently delete stack/ (containers,
    network, and all app config/data) - for testing a fresh install, or
    tearing one down for good. Never touches your media library. Also
    finds and stops containers left orphaned by stack/ being deleted
    through some means other than a real `vulcan uninstall` run.
    """

    if not STACK_DIR.exists() and not stack_containers_exist(STACK_DIR.name):
        console.print("[red]No stack found - nothing to uninstall.[/red]")
        raise typer.Exit(code=1)

    if non_interactive and not yes:
        console.print("[red]--yes is required alongside --non-interactive.[/red]")
        raise typer.Exit(code=1)

    console.print(
        f"This will stop the running stack (if any) and permanently delete {STACK_DIR}/ "
        "(containers, network, and all app config/data)."
        + (
            " backups/ and exports/ will also be deleted."
            if purge_artifacts
            else " Your media library, backups/, and exports/ are left untouched."
        )
        + (
            " Afterward, `docker system prune -a` will also run - removing stopped "
            "containers, unused networks, dangling images, and build cache for the "
            "whole Docker host, not just vulcan's stack."
            if prune_docker
            else ""
        )
    )

    if not yes and not typer.confirm("Continue?"):
        console.print("Aborted.")
        raise typer.Exit(code=0)

    result = None

    phases = ["Uninstall stack"]
    if prune_docker:
        phases.append("Prune Docker artifacts")

    with progress_panel("Uninstall Stack", phases, console=console) as _panel:

        result = uninstall_stack(
            str(STACK_DIR / "docker-compose.yml"),
            str(STACK_DIR / ".env"),
            purge_artifacts=purge_artifacts
        )

        if not result["success"] or not prune_docker:
            _panel.finish(result["success"])
        else:
            _panel.advance()
            result = prune_docker_artifacts()
            _panel.finish(result["success"])

    if not result["success"]:
        console.print(f"[red]{result['error']}[/red]")
        raise typer.Exit(code=1)

    console.print("[green]Stack removed.[/green] Run `./install` again for a fresh setup.")


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    tier: str | None = typer.Option(None, "--tier", help="light, medium, or heavy"),
    media_path: str | None = typer.Option(None, "--media-path"),
    non_interactive: bool = typer.Option(False, "--non-interactive"),
    yes: bool = typer.Option(False, "--yes"),
    vpn: bool | None = typer.Option(None, "--vpn/--no-vpn"),
    sabnzbd: bool | None = typer.Option(None, "--sabnzbd/--no-sabnzbd"),
    recyclarr: bool | None = typer.Option(None, "--recyclarr/--no-recyclarr"),
    homepage: bool | None = typer.Option(None, "--homepage/--no-homepage"),
    homepage_private: bool | None = typer.Option(
        None, "--homepage-private/--homepage-public",
        help="Keep Homepage off the public Traefik-routed domain - only used if homepage and "
        "traefik+domain are all enabled"
    ),
    metube: bool | None = typer.Option(None, "--metube/--no-metube"),
    downtify: bool | None = typer.Option(None, "--downtify/--no-downtify"),
    netdata: bool | None = typer.Option(
        None, "--netdata/--no-netdata",
        help="System resource monitoring - real, deeper host access than every other "
        "service here (SYS_PTRACE/SYS_ADMIN, read-only host filesystem, docker.sock)"
    ),
    vaultwarden: bool | None = typer.Option(
        None, "--vaultwarden/--no-vaultwarden",
        help="Self-hosted password manager (Bitwarden-compatible) - deliberately not "
        "routed through Authelia, same as Jellyfin"
    ),
    dashy: bool | None = typer.Option(
        None, "--dashy/--no-dashy",
        help="A second, more visually customizable dashboard alongside Homepage"
    ),
    dashy_private: bool | None = typer.Option(
        None, "--dashy-private/--dashy-public",
        help="Keep Dashy off the public Traefik-routed domain - only used if dashy and "
        "traefik+domain are all enabled"
    ),
    pihole: bool | None = typer.Option(
        None, "--pihole/--no-pihole",
        help="DNS-level ad blocker with recursive DNS resolver (Unbound)"
    ),
    start: bool | None = typer.Option(None, "--start/--no-start"),
    version: bool | None = typer.Option(
        None, "--version/--no-version",
        help="Show vulcan version and exit"
    ),    gpu: bool | None = typer.Option(None, "--gpu/--no-gpu"),
    puid: int | None = typer.Option(None, "--puid"),
    pgid: int | None = typer.Option(None, "--pgid"),
    timezone: str | None = typer.Option(None, "--timezone"),
    services: str | None = typer.Option(
        None, "--services",
        help="Comma-separated service keys for a custom selection, overriding the tier's default set"
    ),
    domain: str | None = typer.Option(
        None, "--domain",
        help="Base domain for Traefik routing (e.g. media.example.com) - only used if traefik is enabled"
    ),
    cloudflare_dns: bool = typer.Option(
        False, "--cloudflare-dns",
        help="Use Cloudflare DNS-01 for real Let's Encrypt certificates instead of Traefik's "
        "self-signed default - only used if traefik is enabled with a domain"
    ),
    cloudflare_email: str | None = typer.Option(
        None, "--cloudflare-email",
        help="Contact email for Let's Encrypt - only used with --cloudflare-dns"
    ),
    auth_username: str | None = typer.Option(
        None, "--auth-username",
        help="Authelia admin username - only used if authelia is enabled and not already configured"
    ),
    auth_password: str | None = typer.Option(
        None, "--auth-password",
        help="Authelia admin password - only used if authelia is enabled and not already configured"
    ),
    auth_users: str | None = typer.Option(
        None, "--auth-users",
        help="Additional Authelia users as comma-separated username:password:group entries "
        "(e.g. 'friend:pass123:media,guest:pass456:media') - only used if authelia is enabled"
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run",
        help="Generate the stack without starting it and print a full walkthrough - "
        "implies --no-start --non-interactive --yes"
    ),
    plain: bool = typer.Option(False, "--plain", help="Use the plain CLI prompts instead of the TUI"),
    offline: bool = typer.Option(
        False, "--offline",
        help="No internet access on this machine - skip automatic Docker install if it's missing"
    )
):
    if ctx.invoked_subcommand is not None:
        return

    if dry_run:
        non_interactive = True
        yes = True
        start = False

    if not non_interactive and not plain:

        raise typer.Exit(code=_launch_menu())

    run_install(
        tier=tier,
        media_path=media_path,
        non_interactive=non_interactive,
        yes=yes,
        vpn=vpn,
        sabnzbd=sabnzbd,
        recyclarr=recyclarr,
        homepage=homepage,
        homepage_private=homepage_private,
        metube=metube,
        downtify=downtify,
        netdata=netdata,
        vaultwarden=vaultwarden,
        dashy=dashy,
        dashy_private=dashy_private,
        pihole=pihole,
        start=start,
        gpu=gpu,
        puid=puid,
        pgid=pgid,
        timezone=timezone,
        services=services,
        domain=domain,
        cloudflare_dns=cloudflare_dns,
        cloudflare_email=cloudflare_email,
        auth_username=auth_username,
        auth_password=auth_password,
        auth_users_raw=auth_users,
        offline=offline,
        dry_run=dry_run
    )


def run_install(
    tier: str | None,
    media_path: str | None,
    non_interactive: bool,
    yes: bool,
    vpn: bool | None,
    sabnzbd: bool | None,
    recyclarr: bool | None,
    homepage: bool | None,
    homepage_private: bool | None,
    metube: bool | None,
    downtify: bool | None,
    netdata: bool | None,
    vaultwarden: bool | None,
    dashy: bool | None,
    dashy_private: bool | None,
    pihole: bool | None,
    start: bool | None,
    gpu: bool | None,
    puid: int | None,
    pgid: int | None,
    timezone: str | None,
    services: str | None,
    domain: str | None,
    cloudflare_dns: bool = False,
    cloudflare_email: str | None = None,
    auth_username: str | None = None,
    auth_password: str | None = None,
    auth_users_raw: str | None = None,
    offline: bool = False,
    dry_run: bool = False
):

    if non_interactive and not yes:
        console.print("[red]--yes is required alongside --non-interactive.[/red]")
        raise typer.Exit(code=1)

    previous = load_previous_state(STACK_DIR)

    if non_interactive and previous is None and (tier is None or media_path is None):
        console.print(
            "[red]--tier and --media-path are required in --non-interactive mode "
            "(no existing stack was found to fall back on).[/red]"
        )
        raise typer.Exit(code=1)

    if tier is not None and tier not in ("light", "medium", "heavy"):
        console.print(f"[red]--tier '{tier}' must be 'light', 'medium', or 'heavy'.[/red]")
        raise typer.Exit(code=1)

    custom_services_from_flag = None

    if services is not None:

        requested = {key.strip() for key in services.split(",") if key.strip()}
        valid_keys = {service.key for service in ALL_SERVICES}
        unknown = requested - valid_keys

        if unknown:

            console.print(
                f"[red]Unknown service(s) in --services: {', '.join(sorted(unknown))}. "
                f"Valid keys: {', '.join(sorted(valid_keys))}[/red]"
            )
            raise typer.Exit(code=1)

        custom_services_from_flag = requested

    # start is always explicit (--start/--no-start) in the menu path,
    # which is the only path that activates the panel - so the "Start
    # stack" phase only exists when it will actually run.
    phases = ["Detect system", "Docker ready", "Configure stack", "Generate stack"]
    if start is not False:
        phases.append("Start stack")

    with progress_panel("Guided Setup", phases, console=console) as panel:
        console.print("[bold]Detecting your system...[/bold]")
        info = detect_system()

        console.print(
            f"  CPU: {info.cpu_cores_logical} logical cores ({info.cpu_model or 'unknown'})\n"
            f"  RAM: {info.ram_total_gb}GB total\n"
            f"  GPU: {info.gpu_vendor or 'none detected'}\n"
            f"  OS: {info.os_pretty_name or info.os_id or 'unknown'} ({info.architecture})"
        )
        panel.advance()

        info, group_just_added = _ensure_docker_ready(info, non_interactive, yes, offline, panel)

        if not (info.docker_installed and info.docker_running and info.docker_compose_v2):
            panel.finish(False)
            console.print("[red]Docker isn't ready - can't continue.[/red]")
            raise typer.Exit(code=1)

        panel.advance()

        config = _gather_generation_config(
            info, tier, media_path, vpn, sabnzbd, recyclarr, homepage, homepage_private, metube,
            downtify, netdata, vaultwarden, dashy, dashy_private, pihole, gpu, puid, pgid, timezone,
            non_interactive, previous, custom_services_from_flag, domain, cloudflare_dns,
            cloudflare_email, auth_username, auth_password, auth_users_raw, panel
        )
        panel.advance()

        _generate_and_maybe_start(
            config, non_interactive, yes, start, group_just_added,
            on_phase=panel.advance, panel=panel
        )
        panel.finish(True)


def _ensure_docker_ready(
    info: SystemInfo,
    non_interactive: bool,
    yes: bool,
    offline: bool = False,
    panel: RunPanel | _NoOpPanel | None = None
) -> tuple[SystemInfo, bool]:

    group_just_added = False
    panel = panel if panel is not None else _NoOpPanel(console)

    if info.docker_installed and info.docker_running and info.docker_compose_v2:

        panel.note("[green]Docker is ready.[/green]")
        return info, group_just_added

    if not info.docker_installed:

        if offline:

            console.print(
                "[red]No internet access - Docker must already be installed on this "
                "machine, or install it from a machine that does have a connection: "
                "https://docs.docker.com/engine/install/[/red]"
            )

            return info, group_just_added

        plan = install_plan_for(info.os_id, info.os_is_atomic)

        if plan is None:

            console.print(
                f"[red]No known automatic install method for '{info.os_id}'. "
                "Install Docker manually: https://docs.docker.com/engine/install/[/red]"
            )

            return info, group_just_added

        console.print(f"Docker will be installed via: {plan['description']}")

        if yes or typer.confirm("Install Docker now?"):

            result = install_docker(info.os_id, info.os_is_atomic)

            if not result["success"]:

                console.print(f"[red]Docker install failed: {result['error']}[/red]")
                return info, group_just_added

            if result["needs_reboot"]:

                console.print(
                    "[yellow]Docker was layered onto this system via rpm-ostree (this is "
                    "an atomic/immutable OS - Bazzite, Silverblue, Kinoite, or similar). "
                    "That only takes effect after a reboot.[/yellow]\n\n"
                    "Reboot this machine now, then re-run this installer - it will detect "
                    "Docker is installed and pick up from there (starting the service, "
                    "adding your user to the docker group):\n"
                    "  sudo systemctl reboot"
                )
                return info, group_just_added

            start_docker_service()

            group_result = add_user_to_docker_group(getpass.getuser())

            if not group_result["success"]:
                console.print(f"[red]Failed to add your user to the docker group: {group_result['error']}[/red]")
                return info, group_just_added

            ensure_compose_v2(info.os_id)
            group_just_added = True

    elif not info.docker_running:

        console.print("Docker is installed but not running.")

        if yes or typer.confirm("Start the Docker service now?"):

            start_docker_service()

            # Real gap found live (sibling Anvil project) against a
            # real Bazzite host: Docker installed by a *previous* run
            # (the atomic-OS reboot-split case) never got its user
            # added to the docker group, since that only happened
            # alongside a fresh install above. The daemon starting
            # cleanly doesn't mean this user can reach it -
            # /var/run/docker.sock is root:docker.
            group_result = add_user_to_docker_group(getpass.getuser())

            if not group_result["success"]:
                console.print(f"[red]Failed to add your user to the docker group: {group_result['error']}[/red]")
                return info, group_just_added

            group_just_added = True

    elif not info.docker_compose_v2:

        console.print("Docker Compose v2 isn't available.")

        if yes or typer.confirm("Attempt to install Docker Compose v2 now?"):
            ensure_compose_v2(info.os_id)

    docker_state = detect_docker()
    info.docker_installed = docker_state["docker_installed"]
    info.docker_running = docker_state["docker_running"]
    info.docker_compose_v2 = docker_state["docker_compose_v2"]

    if group_just_added:

        # A plain detect_docker() re-check right after adding this
        # process's own user to the docker group would still see the
        # stale group list inherited at this session's login - see
        # check_docker_ready()'s own docstring for the real failure
        # this fixes, confirmed live rather than assumed.
        readiness = check_docker_ready(use_group_workaround=True)
        info.docker_running = readiness["docker_running"]
        info.docker_compose_v2 = readiness["docker_compose_v2"]

    return info, group_just_added


def _choose_raid_level(device_count: int) -> str | None:
    """
    The interactive RAID picker, shared by `vulcan storage apply` and the
    install-flow offer so the exact same choices/descriptors appear in
    both. Shows the real valid options for this device count (each with
    honest tradeoffs via describe_raid_option()), prompts for one, and
    returns the chosen level - re-prompting on invalid input, never
    guessing. Returns None only when there's nothing to choose (1
    device: no RAID); otherwise always returns a valid level.
    """

    options = _raid_level_options(device_count)

    if len(options) <= 1:
        return options[0]["level"] if options else None

    console.print("Choose a RAID level for these devices:")

    for index, option in enumerate(options, start=1):
        console.print(f"  {index}. {describe_raid_option(option)}")

    while True:

        raw = typer.prompt(
            "RAID level (number or RAID#)",
            default="5",
        ).strip()

        for index, option in enumerate(options, start=1):

            if raw in (str(index), option["level"], f"RAID{option['level']}"):
                return option["level"]

        console.print(f"[red]'{raw}' isn't a valid choice - try again.[/red]")


def _offer_storage_setup(non_interactive: bool) -> str | None:
    """
    The plain-CLI install flow's optional storage step: when the machine
    has genuinely spare (blank, unprotected) disks, offer to provision
    them as a single media volume before the media-path prompt - a fresh
    nanorack with four empty drives should be asked "want this set up as
    your media storage?" instead of silently pointing MEDIA_PATH at the
    boot disk. Returns the mount point when storage was provisioned,
    None when there was nothing to offer or the user declined/failed.
    Reuses the exact same engine + gates as `vulcan storage apply`
    (typed-device confirmation included), never a separate path.
    """

    if non_interactive:
        return None

    blank_devices = list_blank_unprotected_devices()

    if not blank_devices:
        return None

    total = ", ".join(
        f"{d['path']} ({d['size']})" for d in blank_devices
    )

    console.print(
        f"[bold]Detected spare storage:[/bold] {total} - blank, "
        "not backing the system disk."
    )

    if not typer.confirm(
        "Set these up as a single media storage volume "
        "(mdadm RAID if 2+ devices)?"
    ):
        return None

    default_mount = "/mnt/media"

    mount_point = typer.prompt("Mount point for the media volume", default=default_mount)

    device_paths = [d["path"] for d in blank_devices]

    raid_level = _choose_raid_level(len(device_paths))

    if raid_level is None and len(device_paths) > 1:
        console.print("[red]No valid RAID level chosen - skipping storage setup.[/red]")
        return None

    plan = plan_storage_layout(device_paths, mount_point, raid_level=raid_level)

    console.print(describe_storage_plan(plan))

    if plan["error"]:
        console.print(f"[red]Can't plan this storage: {plan['error']}[/red]")
        return None

    typed = typer.prompt(
        f"Type the exact device list to confirm ({', '.join(device_paths)})",
        hide_input=False,
    )

    if {p.strip() for p in typed.split(",") if p.strip()} != set(device_paths):

        console.print("[red]Confirmation didn't match - skipping storage setup.[/red]")
        return None

    result = apply_storage_layout(plan)

    for command in result.get("ran", []):
        console.print(f"[green]ran:[/green] {command}")

    for note in result.get("skipped", []):
        console.print(f"[cyan]skipped:[/cyan] {note}")

    if not result["success"]:
        console.print(f"[red]{result['error']}[/red]")
        return None

    if result.get("already_provisioned"):
        console.print(
            f"[green]{mount_point} was already provisioned - using it.[/green]"
        )
        return mount_point

    console.print(
        f"[green]Media storage provisioned and mounted at {mount_point}.[/green]"
    )

    tree = device_tree_text(plan["target_device"])

    if tree:
        console.print(tree)

    return mount_point


_SERVICE_CONFLICTS: list[tuple[set[str], set[str], str]] = [
    (
        {"gluetun", "tailscale"}, set(),
        "Gluetun (container VPN) and Tailscale (host VPN) both manage network "
        "routing and cannot run together. Pick one.",
    ),
]


_SERVICE_DEPS: list[tuple[str, str, str]] = [
    ("cloudflared", "traefik", "Cloudflare Tunnel requires Traefik as the reverse proxy."),
    ("authelia", "traefik", "Authelia requires Traefik for forward-auth middleware."),
    ("crowdsec", "traefik", "CrowdSec requires Traefik for its bouncer middleware."),
]


def _check_service_conflicts(services: set[str]) -> str | None:
    """Return an error message if *services* contains an incompatible combination, else None."""

    for required_both, required_neither, message in _SERVICE_CONFLICTS:
        if required_both.issubset(services):
            return message
        if required_neither and required_neither.issubset(services):
            return message

    for service, dependency, message in _SERVICE_DEPS:
        if service in services and dependency not in services:
            return message

    return None


def _gather_generation_config(
    info: SystemInfo,
    tier: str | None,
    media_path: str | None,
    vpn: bool | None,
    sabnzbd: bool | None,
    recyclarr: bool | None,
    homepage: bool | None,
    homepage_private: bool | None,
    metube: bool | None,
    downtify: bool | None,
    netdata: bool | None,
    vaultwarden: bool | None,
    dashy: bool | None,
    dashy_private: bool | None,
    pihole: bool | None,
    gpu: bool | None,
    puid: int | None,
    pgid: int | None,
    timezone: str | None,
    non_interactive: bool,
    previous: dict | None,
    custom_services_from_flag: set[str] | None,
    domain: str | None,
    cloudflare_dns: bool = False,
    cloudflare_email: str | None = None,
    auth_username: str | None = None,
    auth_password: str | None = None,
    auth_users_raw: str | None = None,
    panel: RunPanel | _NoOpPanel | None = None
) -> GenerationConfig:

    panel = panel if panel is not None else _NoOpPanel(console)

    if previous is not None:

        panel.note(
            f"Found an existing [bold]{previous['tier']}[/bold] stack, generated "
            f"{previous['generated_at']}. Using it as defaults - pass flags to override."
        )

    if media_path is None:

        default_media_path = previous["media_path"] if previous else str(Path.home() / "media")

        if not non_interactive and previous is None:

            storage_mount = _offer_storage_setup(non_interactive)

            if storage_mount is not None:
                default_media_path = storage_mount

        media_path = default_media_path if non_interactive else typer.prompt(
            "Media library path", default=default_media_path
        )

    media_path = str(Path(media_path).expanduser().resolve())

    # detect_disk() needs a path that actually exists on the target
    # filesystem - a brand-new media directory doesn't yet, so create it
    # now rather than reporting a false 0.0GB free (write_stack() would
    # create it anyway, just later).
    try:
        Path(media_path).mkdir(parents=True, exist_ok=True)
    except OSError as error:
        console.print(f"[red]Can't create media path '{media_path}': {error}[/red]")
        raise typer.Exit(code=1)

    disk_info = detect_disk(media_path)
    info.disk_free_gb = disk_info["disk_free_gb"]
    info.disk_path_checked = disk_info["disk_path_checked"]

    redundancy = detect_media_redundancy(media_path)
    description = describe_media_redundancy(redundancy)

    if description is not None:

        panel.note(f"Media storage: {description}")

        if redundancy["redundant"] is False:
            panel.note(
                "[yellow]! No drive-level redundancy - a single drive failure "
                "would mean data loss.[/yellow]"
            )

    recommendation = recommend_tier(info)

    # The full 3-tier comparison only helps someone still choosing - a
    # real, avoidable wall of text when --tier already decided it (every
    # non-interactive run, which is what the whiptail menu always uses).
    # The one-line recommendation stays either way; it's short and still
    # useful context even when the choice is already made.
    console.print(
        f"Recommended tier: [bold]{recommendation.tier.display_name}[/bold] - "
        f"{recommendation.explanation}"
    )

    if not non_interactive:
        for tier_name in ("light", "medium", "heavy"):
            console.print(f"  {TIERS[tier_name].display_name}: {tier_description(TIERS[tier_name])}")

    if tier is not None:

        chosen_tier_name = tier

    elif non_interactive:

        chosen_tier_name = previous["tier"]

    else:

        default_choice = previous["tier"] if previous else recommendation.tier.name

        chosen_tier_name = typer.prompt("Which tier? (light/medium/heavy)", default=default_choice)

        while chosen_tier_name not in ("light", "medium", "heavy"):
            chosen_tier_name = typer.prompt(
                "Please enter 'light', 'medium', or 'heavy'", default=default_choice
            )

    chosen_tier = TIERS[chosen_tier_name]

    previous_custom = previous.get("custom_services") if previous else None

    if custom_services_from_flag is not None:

        conflict = _check_service_conflicts(custom_services_from_flag)

        if conflict:
            console.print(f"[red]{conflict}[/red]")
            raise typer.Exit(code=1)

        custom_services_selected = custom_services_from_flag

    elif non_interactive:

        custom_services_selected = set(previous_custom) if previous_custom is not None else None

    else:

        wants_custom = typer.confirm(
            "Customize which services are included?",
            default=previous_custom is not None
        )

        if wants_custom:

            starting_set = (
                set(previous_custom) if previous_custom is not None
                else {service.key for service in chosen_tier.services if not service.optional}
            )
            valid_keys = {service.key for service in ALL_SERVICES}

            console.print(f"Available services: {', '.join(sorted(valid_keys))}")

            while True:

                raw = typer.prompt(
                    "Services to include (comma-separated)",
                    default=",".join(sorted(starting_set))
                )
                requested = {key.strip() for key in raw.split(",") if key.strip()}
                unknown = requested - valid_keys

                if unknown:
                    console.print(f"[red]Unknown service(s): {', '.join(sorted(unknown))}[/red]")
                    continue

                conflict = _check_service_conflicts(requested)

                if conflict:
                    console.print(f"[red]{conflict}[/red]")
                    continue

                custom_services_selected = requested
                break

        else:
            custom_services_selected = None

    domain_value = None

    if custom_services_selected is not None and "traefik" in custom_services_selected:

        previous_domain = previous.get("domain") if previous else None

        if domain is not None:
            domain_value = domain
        elif non_interactive:
            domain_value = previous_domain
        else:

            console.print(
                "You'll need to own this domain and point its subdomains at this host "
                "yourself - Vulcan doesn't create DNS records for you. By default it uses "
                "Traefik's self-signed certificate; if your domain's DNS is on Cloudflare, "
                "you can opt into real Let's Encrypt certificates instead (next question)."
            )

            domain_value = typer.prompt(
                "Base domain for Traefik routing, e.g. media.example.com (leave blank to skip)",
                default=previous_domain or ""
            ) or None

    cloudflare_dns_value = False
    cloudflare_email_value = None

    if domain_value:

        previous_cloudflare_dns = previous.get("cloudflare_dns") if previous else False
        previous_cloudflare_email = previous.get("cloudflare_email") if previous else None

        if cloudflare_dns:
            cloudflare_dns_value = True
        elif non_interactive:
            cloudflare_dns_value = bool(previous_cloudflare_dns)
        else:
            cloudflare_dns_value = typer.confirm(
                "Is this domain's DNS managed by Cloudflare? If so, Vulcan can get you real "
                "Let's Encrypt certificates instead of Traefik's self-signed one.",
                default=previous_cloudflare_dns
            )

        if cloudflare_dns_value:

            if cloudflare_email is not None:
                cloudflare_email_value = cloudflare_email
            elif non_interactive:
                cloudflare_email_value = previous_cloudflare_email
            else:

                console.print(
                    "You'll need a scoped Cloudflare API token (Zone:DNS:Edit on this "
                    "domain's zone) in stack/.env before this actually works - Vulcan will "
                    "remind you after generating."
                )

                cloudflare_email_value = typer.prompt(
                    "Contact email for Let's Encrypt",
                    default=previous_cloudflare_email or ""
                ) or None

    auth_username_value = None
    auth_password_hash_value = None
    auth_users_value = []

    if custom_services_selected is not None and "authelia" in custom_services_selected:

        users_database_path = STACK_DIR / "config" / "authelia" / "users_database.yml"

        if not users_database_path.exists():

            if auth_username is not None and auth_password is not None:
                chosen_username = auth_username
                chosen_password = auth_password
            elif non_interactive:
                console.print(
                    "[red]--auth-username and --auth-password are required when enabling "
                    "authelia in --non-interactive mode.[/red]"
                )
                raise typer.Exit(code=1)
            else:

                console.print(
                    "Authelia puts a real login in front of every Traefik-routed service. "
                    "This creates that login - remember the password, it won't be shown again."
                )

                chosen_username = auth_username or typer.prompt("Authelia admin username", default="admin")
                chosen_password = auth_password or typer.prompt(
                    "Authelia admin password", hide_input=True, confirmation_prompt=True
                )

            hash_result = hash_authelia_password(chosen_password)

            if not hash_result["success"]:
                console.print(f"[red]{hash_result['error']}[/red]")
                raise typer.Exit(code=1)

            auth_username_value = chosen_username
            auth_password_hash_value = hash_result["hash"]

            if auth_users_raw:

                for entry in auth_users_raw.split(","):
                    entry = entry.strip()
                    if not entry:
                        continue

                    parts = entry.split(":")
                    if len(parts) != 3:
                        console.print(
                            f"[red]Invalid --auth-users entry '{entry}': "
                            "expected username:password:group[/red]"
                        )
                        raise typer.Exit(code=1)

                    user_username, user_password, user_group = parts

                    if user_group not in ("admin", "media"):
                        console.print(
                            f"[red]Invalid group '{user_group}' for user "
                            f"'{user_username}': must be 'admin' or 'media'[/red]"
                        )
                        raise typer.Exit(code=1)

                    user_hash_result = hash_authelia_password(user_password)

                    if not user_hash_result["success"]:
                        console.print(
                            f"[red]Failed to hash password for user "
                            f"'{user_username}': {user_hash_result['error']}[/red]"
                        )
                        raise typer.Exit(code=1)

                    auth_users_value.append({
                        "username": user_username,
                        "password_hash": user_hash_result["hash"],
                        "groups": [user_group]
                    })

    enabled_optional = set()

    if custom_services_selected is None:

        # Defaults to True (opt-out, not opt-in) on a fresh install -
        # qBittorrent is present at every tier, and Gluetun is what
        # actually keeps its torrent traffic from exposing a real IP
        # to the swarm. A real, deliberate behavior change: previously
        # defaulted off and was only ever asked about at Medium tier
        # specifically (Heavy-tier users on the default flow could
        # never reach this question at all outside custom mode) -
        # both gaps meant it was realistic to end up torrenting fully
        # exposed without ever being asked. A regenerate still respects
        # whatever was explicitly chosen last time, same as every other
        # optional service here.
        vpn_default = "gluetun" in previous["enabled_optional"] if previous else True

        if vpn is None:

            enable_vpn = vpn_default if non_interactive else typer.confirm(
                "Enable Gluetun VPN for qBittorrent? Recommended - without it, torrent "
                "traffic exposes your real IP to the swarm. You'll need your VPN "
                "provider's credentials afterward - setup guide per provider: "
                "https://github.com/qdm12/gluetun-wiki/tree/main/setup/providers",
                default=vpn_default
            )

        else:
            enable_vpn = vpn

        if enable_vpn:
            enabled_optional.add("gluetun")

    if custom_services_selected is None:

        sabnzbd_default = "sabnzbd" in previous["enabled_optional"] if previous else False

        if sabnzbd is None:

            enable_sabnzbd = sabnzbd_default if non_interactive else typer.confirm(
                "Enable SABnzbd (Usenet downloader) alongside qBittorrent?",
                default=sabnzbd_default
            )

        else:
            enable_sabnzbd = sabnzbd

        if enable_sabnzbd:
            enabled_optional.add("sabnzbd")

    if custom_services_selected is None:

        recyclarr_default = "recyclarr" in previous["enabled_optional"] if previous else False

        if recyclarr is None:

            enable_recyclarr = recyclarr_default if non_interactive else typer.confirm(
                "Enable Recyclarr (TRaSH Guides config sync for Radarr/Sonarr)?",
                default=recyclarr_default
            )

        else:
            enable_recyclarr = recyclarr

        if enable_recyclarr:
            enabled_optional.add("recyclarr")

    if custom_services_selected is None:

        homepage_default = (
            ("homepage" in previous["enabled_optional"]) or (previous.get("tier") == "heavy")
            if previous else True
        )

        if homepage is None:

            enable_homepage = homepage_default if non_interactive else typer.confirm(
                "Enable Homepage dashboard?",
                default=homepage_default
            )

        else:
            enable_homepage = homepage

        if enable_homepage:
            enabled_optional.add("homepage")

    homepage_enabled = (
        "homepage" in enabled_optional if custom_services_selected is None
        else "homepage" in custom_services_selected
    )

    # Only meaningful once there's something to be "private" from - a
    # real public routed domain. Defaults True (the point of asking at
    # all is that most people who set up a public domain don't want a
    # dashboard of every other service handed to a stranger who reaches
    # it) but stays a real, declinable question, same as every other
    # default-on optional flag here.
    homepage_private_value = False

    if homepage_enabled and domain_value:

        homepage_private_default = (
            bool(previous.get("homepage_private", True)) if previous else True
        )

        if homepage_private is None:

            homepage_private_value = homepage_private_default if non_interactive else typer.confirm(
                "Keep Homepage off the public domain? Recommended - Jellyfin (and anything "
                "else you route) still gets its own subdomain either way; this only affects "
                "whether a stranger who reaches your domain can also find Homepage.",
                default=homepage_private_default
            )

        else:
            homepage_private_value = homepage_private

    if custom_services_selected is None:

        metube_default = "metube" in previous["enabled_optional"] if previous else False

        if metube is None:

            enable_metube = metube_default if non_interactive else typer.confirm(
                "Enable MeTube (video downloader - YouTube, Facebook, and hundreds of other sites)?",
                default=metube_default
            )

        else:
            enable_metube = metube

        if enable_metube:
            enabled_optional.add("metube")

    if custom_services_selected is None:

        downtify_default = "downtify" in previous["enabled_optional"] if previous else False

        if downtify is None:

            enable_downtify = downtify_default if non_interactive else typer.confirm(
                "Enable Downtify (Spotify downloader - no account or API key needed)?",
                default=downtify_default
            )

        else:
            enable_downtify = downtify

        if enable_downtify:
            enabled_optional.add("downtify")

    if custom_services_selected is None:

        # Deliberately no opt-out-style default like Gluetun's - real,
        # meaningfully deeper host access than every other service
        # here (SYS_PTRACE/SYS_ADMIN, read-only host filesystem,
        # docker.sock), named explicitly in the prompt itself, not
        # just the post-generate warning.
        netdata_default = "netdata" in previous["enabled_optional"] if previous else False

        if netdata is None:

            enable_netdata = netdata_default if non_interactive else typer.confirm(
                "Enable Netdata (system resource monitoring)? Real-time CPU/RAM/disk/"
                "network/temperature dashboards - needs real, deeper host access than "
                "anything else here (SYS_PTRACE/SYS_ADMIN, read-only host filesystem, "
                "the Docker socket) to see all of that.",
                default=netdata_default
            )

        else:
            enable_netdata = netdata

        if enable_netdata:
            enabled_optional.add("netdata")

    if custom_services_selected is None:

        vaultwarden_default = "vaultwarden" in previous["enabled_optional"] if previous else False

        if vaultwarden is None:

            enable_vaultwarden = vaultwarden_default if non_interactive else typer.confirm(
                "Enable Vaultwarden (self-hosted, Bitwarden-compatible password manager)? "
                "Not routed through Authelia even if enabled - same reason as Jellyfin, its "
                "own apps can't complete a browser SSO redirect.",
                default=vaultwarden_default
            )

        else:
            enable_vaultwarden = vaultwarden

        if enable_vaultwarden:
            enabled_optional.add("vaultwarden")

    if custom_services_selected is None:

        dashy_default = "dashy" in previous["enabled_optional"] if previous else False

        if dashy is None:

            enable_dashy = dashy_default if non_interactive else typer.confirm(
                "Enable Dashy (a second, more visually customizable dashboard alongside "
                "Homepage)?",
                default=dashy_default
            )

        else:
            enable_dashy = dashy

        if enable_dashy:
            enabled_optional.add("dashy")

    dashy_enabled = (
        "dashy" in enabled_optional if custom_services_selected is None
        else "dashy" in custom_services_selected
    )

    pihole_default = "pihole" in previous["enabled_optional"] if previous else False

    if pihole is not None:
        enable_pihole = pihole
    elif non_interactive:
        enable_pihole = pihole_default
    else:
        enable_pihole = False

    if enable_pihole:
        enabled_optional.add("pihole")

    pihole_enabled = (
        "pihole" in enabled_optional if custom_services_selected is None
        else "pihole" in custom_services_selected
    )

    # Same reasoning and same opt-out-by-default question as Homepage's
    # own homepage_private above, asked independently - enabling both
    # dashboards doesn't mean they share one privacy decision.
    dashy_private_value = False

    if dashy_enabled and domain_value:

        dashy_private_default = (
            bool(previous.get("dashy_private", True)) if previous else True
        )

        if dashy_private is None:

            dashy_private_value = dashy_private_default if non_interactive else typer.confirm(
                "Keep Dashy off the public domain? Recommended - Jellyfin (and anything "
                "else you route) still gets its own subdomain either way; this only affects "
                "whether a stranger who reaches your domain can also find Dashy.",
                default=dashy_private_default
            )

        else:
            dashy_private_value = dashy_private

    gpu_vendor_to_use = None

    jellyfin_included = "jellyfin" in (
        custom_services_selected if custom_services_selected is not None
        else {service.key for service in chosen_tier.services}
    )

    show_gpu_question = (
        jellyfin_included and info.gpu_vendor and
        (chosen_tier_name == "heavy" or custom_services_selected is not None)
    )

    if show_gpu_question:

        gpu_default = bool(previous.get("gpu_vendor")) if previous else True

        if gpu is None:

            enable_gpu = gpu_default if non_interactive else typer.confirm(
                f"Enable hardware transcoding using the detected {info.gpu_vendor} GPU?",
                default=gpu_default
            )

        else:
            enable_gpu = gpu

        if enable_gpu:
            gpu_vendor_to_use = info.gpu_vendor

    default_puid, default_pgid = default_puid_pgid()
    default_tz = default_timezone()

    if previous:
        default_puid = previous["puid"]
        default_pgid = previous["pgid"]
        default_tz = previous["timezone"]

    if not non_interactive and (puid is None or pgid is None):

        console.print(
            "PUID/PGID set which user/group ID the containers run as - matters for file "
            "ownership on your media library. The defaults below are your own user; "
            "accept them unless you specifically need something else."
        )

    if puid is None:
        final_puid = default_puid if non_interactive else typer.prompt("PUID", default=default_puid, type=int)
    else:
        final_puid = puid

    if pgid is None:
        final_pgid = default_pgid if non_interactive else typer.prompt("PGID", default=default_pgid, type=int)
    else:
        final_pgid = pgid

    if timezone is None:
        final_tz = default_tz if non_interactive else typer.prompt("Timezone", default=default_tz)
    else:
        final_tz = timezone

    final_services = (
        custom_services_selected if custom_services_selected is not None
        else enabled_optional | {s.key for s in chosen_tier.services if not s.optional}
    )
    conflict = _check_service_conflicts(final_services)

    if conflict:
        console.print(f"[red]{conflict}[/red]")
        raise typer.Exit(code=1)

    return GenerationConfig(
        tier=chosen_tier,
        media_path=media_path,
        puid=final_puid,
        pgid=final_pgid,
        timezone=final_tz,
        enabled_optional=enabled_optional,
        gpu_vendor=gpu_vendor_to_use,
        custom_services=custom_services_selected,
        domain=domain_value,
        cloudflare_dns=cloudflare_dns_value,
        cloudflare_email=cloudflare_email_value,
        auth_username=auth_username_value,
        auth_password_hash=auth_password_hash_value,
        auth_users=auth_users_value,
        port_overrides=dict(previous["port_overrides"]) if previous and previous.get("port_overrides") else {},
        homepage_private=homepage_private_value,
        dashy_private=dashy_private_value
    )


def _resolve_port_conflicts(config: GenerationConfig, result: dict) -> dict:
    """
    Step two of the port-conflict work: check_ports_available() already
    diagnosed a real cause (see preflight.py), but this used to just
    print it and refuse - and worse, the one case that could ask a
    human to fix it (typer.prompt) was dead code in practice, since
    neither real caller can prompt anyone: whiptail's Guided Setup
    always runs this CLI --non-interactive, and `vulcan start` is a
    maintenance command against an already-generated stack. This is now
    fully automatic for the two real recoverable cases the diagnosis
    already distinguishes - your own orphaned containers (safe to clean
    up) and a remappable service (bumped to the next free port) - and
    still ends in a clean refusal for the one genuinely unresolvable
    case (a non-Docker/native service, or a service - Traefik,
    FlareSolverr - deliberately out of remap scope).

    Loops rather than handling one pass, since fixing one conflict can
    surface another (e.g. a newly-picked port that happens to collide
    with a second still-conflicting service) - each pass regenerates
    via write_stack() (same re-run-safe path every other regenerate
    uses) and re-checks for real before declaring victory. Bounded to a
    generous attempt count so a genuinely pathological case (e.g.
    almost the entire port space already taken) fails loudly instead of
    spinning forever.
    """

    for _ in range(20):

        port_check = check_ports_available(result["compose_path"])

        if port_check["available"]:
            return result

        console.print("[yellow]Port(s) already in use - resolving automatically:[/yellow]")
        console.print(format_port_conflicts(port_check))

        remappable = resolve_ports(config)
        resolved_any = False

        # remove_orphaned_containers() tears down the whole orphaned
        # project in one call - real testing against actual orphaned
        # containers surfaced that own_orphan is often true for several
        # ports at once, since they're all the same leftover stack; one
        # cleanup covers every own-orphan port in this pass.
        own_orphan_cleaned = False

        for port in port_check["conflicts"]:

            service_key = port_check["port_services"].get(port)

            if port_check["own_orphan"].get(port):

                if own_orphan_cleaned:
                    resolved_any = True
                    continue

                cleanup = remove_orphaned_containers(Path(result["compose_path"]).parent.name)

                if cleanup["success"]:
                    console.print(
                        f"[yellow]Removed orphaned containers from a previous stack "
                        f"holding port {port}.[/yellow]"
                    )
                    resolved_any = True
                    own_orphan_cleaned = True
                else:
                    console.print(f"[red]{cleanup['error']}[/red]")

                continue

            if service_key is None or service_key not in remappable:

                owner = port_check["owners"].get(port)
                console.print(
                    f"[red]Port {port}{f' ({owner})' if owner else ''} can't be "
                    "remapped automatically - free it manually and retry.[/red]"
                )
                continue

            taken = set(remappable.values()) | set(port_check["conflicts"])
            new_port = find_next_available_port(port, taken)

            if new_port is None:
                console.print(f"[red]No free port found above {port} - free it manually.[/red]")
                continue

            console.print(
                f"[yellow]Port {port} ({service_key}) was in use - reassigned to "
                f"{new_port}.[/yellow]"
            )
            config.port_overrides[service_key] = new_port
            resolved_any = True

        if not resolved_any:
            console.print(
                "[red]Free the port(s) above, then run this when you're ready:\n"
                f"  docker compose -f {result['compose_path']} --env-file "
                f"{result['env_path']} up -d[/red]"
            )
            raise typer.Exit(code=1)

        result = write_stack(config)
        console.print(f"[green]Stack regenerated at {result['compose_path']}[/green]")

    console.print("[red]Couldn't resolve all port conflicts after repeated attempts.[/red]")
    raise typer.Exit(code=1)


def _generate_and_maybe_start(
    config: GenerationConfig,
    non_interactive: bool,
    yes: bool,
    start: bool | None,
    group_just_added: bool,
    on_phase=None,
    panel: RunPanel | _NoOpPanel | None = None
) -> dict:

    panel = panel if panel is not None else _NoOpPanel(console)

    panel.note("\n[bold]Review[/bold]")
    panel.note(f"  Tier: {config.tier.display_name}")
    panel.note(f"  Media path: {config.media_path}")
    panel.note(f"  PUID/PGID: {config.puid}/{config.pgid}")
    panel.note(f"  Timezone: {config.timezone}")
    panel.note(f"  Gluetun VPN: {'enabled' if 'gluetun' in config.enabled_optional else 'disabled'}")
    panel.note(f"  SABnzbd: {'enabled' if 'sabnzbd' in config.enabled_optional else 'disabled'}")
    panel.note(f"  Recyclarr: {'enabled' if 'recyclarr' in config.enabled_optional else 'disabled'}")
    panel.note(f"  MeTube: {'enabled' if 'metube' in config.enabled_optional else 'disabled'}")
    panel.note(f"  Downtify: {'enabled' if 'downtify' in config.enabled_optional else 'disabled'}")
    panel.note(f"  Netdata: {'enabled' if 'netdata' in config.enabled_optional else 'disabled'}")
    panel.note(f"  Vaultwarden: {'enabled' if 'vaultwarden' in config.enabled_optional else 'disabled'}")
    if config.homepage_private:
        panel.note("  Homepage: private (not publicly routed)")
    panel.note(f"  Homepage: {'enabled' if 'homepage' in config.enabled_optional else 'disabled'}")
    if config.dashy_private:
        panel.note("  Dashy: private (not publicly routed)")
    panel.note(f"  Dashy: {'enabled' if 'dashy' in config.enabled_optional else 'disabled'}")
    panel.note(f"  Pi-hole: {'enabled' if 'pihole' in config.enabled_optional else 'disabled'}")
    panel.note(f"  GPU passthrough: {config.gpu_vendor or 'disabled'}")

    if config.custom_services is not None:
        panel.note(f"  Services: {', '.join(sorted(config.custom_services))}")

    if config.domain:
        panel.note(f"  Domain: {config.domain}")

    if config.cloudflare_dns:
        panel.note(f"  Cloudflare DNS (real Let's Encrypt certs): enabled ({config.cloudflare_email})")

    if config.auth_username:
        panel.note(f"  Authelia admin username: {config.auth_username}")

    if config.auth_users:
        for user in config.auth_users:
            panel.note(f"  Authelia user: {user['username']} (group: {', '.join(user['groups'])})")

    compose_exists = (STACK_DIR / "docker-compose.yml").exists()

    confirm_text = (
        "\nThis will overwrite the existing stack/docker-compose.yml. Continue?"
        if compose_exists else
        "\nGenerate the stack with these settings?"
    )

    if not yes and not typer.confirm(confirm_text):
        console.print("Aborted.")
        raise typer.Exit(code=0)

    try:
        result = write_stack(config)
    except OSError as error:
        console.print(f"[red]Failed to write the stack: {error}[/red]")
        raise typer.Exit(code=1)

    panel.note(f"[green]Stack written to {result['compose_path']}[/green]")

    if on_phase is not None:
        on_phase("Generate stack")

    # Real, actionable detail (a missing NVIDIA toolkit, a port that
    # got reassigned, ...) - not deleted, just moved: write_stack()
    # persists these into stack/.vulcan-state.json now specifically so
    # `vulcan install-summary` can surface them in "Setup Complete"
    # instead of them scrolling by here under a live panel.
    for warning in result["warnings"]:
        panel.note(f"[yellow]! {warning}[/yellow]")

    if start is None:
        do_start = False if non_interactive else typer.confirm("Start the stack now?", default=True)
    else:
        do_start = start

    if do_start:

        result = _resolve_port_conflicts(config, result)

        net_check = check_network_conflicts(result["compose_path"])

        if not net_check["ok"]:
            console.print("[red]Network configuration errors (Docker would reject these):[/red]")
            console.print(format_network_conflicts(net_check))
            raise typer.Exit(code=1)

        proc = run_docker_command(
            [
                "docker", "compose",
                "-f", result["compose_path"],
                "--env-file", result["env_path"],
                "up", "-d"
            ],
            use_group_workaround=group_just_added
        )

        if proc.returncode == 0:

            if on_phase is not None:
                on_phase("Start stack")

            # `up -d` only waits for containers to start, not for the
            # process inside to actually stay up - a real check here
            # catches a crash-loop `up -d` alone would silently report
            # as success.
            verification = verify_stack_running(result["compose_path"])

            if not verification["all_running"]:

                console.print("[red]Stack started but isn't actually running:[/red]")

                if verification["error"]:
                    console.print(f"[red]{verification['error']}[/red]")

                for entry in verification["not_running"]:
                    console.print(
                        f"[red]  {entry['service']}: {entry['state']} ({entry['status']})[/red]"
                    )

                console.print("[red]Check `docker compose logs` for the failing service(s).[/red]")
                raise typer.Exit(code=1)

            panel.note("[green]Stack is up:[/green]")

            summary = render_stack_summary(config, detect_host_ip())

            if summary:
                panel.note(summary)

            setup_order = render_setup_order(config, detect_host_ip())

            if setup_order:
                panel.note(f"\n{setup_order}")

        else:
            console.print("[red]Failed to start the stack - check `docker compose logs`.[/red]")
            raise typer.Exit(code=1)

    else:

        panel.note("[bold]Stack generated (not started):[/bold]")

        summary = render_stack_summary(config, detect_host_ip())

        if summary:
            panel.note(summary)

        setup_order = render_setup_order(config, detect_host_ip())

        if setup_order:
            panel.note(f"\n{setup_order}")

        panel.note(
            "\nRun this when you're ready:\n"
            f"  docker compose -f {result['compose_path']} --env-file {result['env_path']} up -d"
        )

        if config.auth_users:
            panel.note(
                f"\nAuthelia users configured: admin ('{config.auth_username}') + "
                f"{len(config.auth_users)} additional user(s). Admin has full access; "
                "additional users can only reach Jellyfin and Jellyseerr."
            )

        if "cloudflared" in enabled_service_keys(config):
            panel.note(
                "\nCloudflare Tunnel: fill in TUNNEL_TOKEN in "
                f"{result['env_path']} before starting. Create a tunnel at "
                "Zero Trust dashboard > Networks > Tunnels > Create a tunnel > "
                "Docker tab, then add a Public Hostname pointing at "
                "http://traefik:8081."
            )

    return result


if __name__ == "__main__":
    app()
