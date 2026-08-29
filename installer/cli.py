import os
import subprocess
import sys
from pathlib import Path

import typer
from rich.console import Console

from installer import __version__
from installer.auth import hash_authelia_password
from installer.configure import configure_pending
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
    # install_docker / start_docker_service: Phase 0 (installer/phase0.py)
    # owns Docker install/start/group now - kept in this namespace only so
    # tests can patch them and assert run_install never installs Docker.
    install_docker,  # noqa: F401
    prune_docker_artifacts,
    run_docker_command,
    start_docker_service,  # noqa: F401
)
from installer.generate import (
    STACK_DIR,
    STATE_FILENAME,
    GenerationConfig,
    default_puid_pgid,
    default_timezone,
    enabled_service_keys,
    export_plan,
    find_next_available_port,
    load_plan,
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
from installer.deps import ensure_system_deps
from installer.offline import (
    bundle_dependencies,
    extract_bundle,
    install_from_wheelhouse,
    package_bundle,
    runtime_dependencies,
)
from installer.preflight import (
    check_network_conflicts,
    check_ports_available,
    format_network_conflicts,
    format_port_conflicts,
)
from installer.phase0 import ensure_system_ready
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
    list_unprotected_devices,
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

# A stack plan is the portable subset of saved state (tier, services,
# domain, PUID/PGID/timezone - never secrets, those stay in .env) -
# `export` writes it, `build --from-plan` reads it back in as this
# run's "previous state" seed, same machinery a same-machine rebuild
# already uses.
plan_app = typer.Typer(
    help="Export the current stack's shape (tier, services, settings - no secrets) to a shareable file."
)
app.add_typer(plan_app, name="plan")

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


def _ensure_system_deps(non_interactive: bool) -> None:
    """
    Ensure whiptail (the TUI) and mdadm (RAID provisioning) exist before
    the flow needs them - a fresh OS ships neither. Auto-installs via the
    distro package manager with consent in interactive mode; in
    non-interactive mode it installs unconditionally (scripted runs imply
    consent) and only warns if anything remains missing. python3 is
    handled by the bash `install` bootstrap before this ever runs, so
    it's expected to already be present here.
    """

    plan = ensure_system_deps(dry_run=True)

    if not plan["packages"]:
        return

    if not non_interactive:
        console.print(
            "[bold]Missing system packages:[/bold] "
            + ", ".join(plan["packages"])
        )
        if not typer.confirm("Install them now?"):
            console.print("[yellow]Skipping - some features (TUI/RAID) may not work.[/yellow]")
            return

    result = ensure_system_deps()

    for tool in result["installed"]:
        console.print(f"[green]Installed:[/green] {tool}")

    if result["missing_after"]:
        console.print(
            f"[red]Still missing after install: {', '.join(result['missing_after'])}[/red]"
        )
        if result["error"]:
            console.print(f"[red]{result['error']}[/red]")
    elif result["needs_reboot"]:
        console.print("[yellow]Installed as a layered package - reboot to take effect.[/yellow]")

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
        "ALL_UNPROTECTED_DEVICES": ",".join(
            d["path"] for d in list_unprotected_devices()
        ),
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


@app.command()
def preflight(
    fix: bool = typer.Option(False, "--fix", help="Install what's missing (needs root for Docker/packages)."),
    offline: bool = typer.Option(
        False, "--offline",
        help="No network path to package mirrors - report-only (implies no --fix), with "
        "per-tool remediation for what to bring onto this machine instead."
    ),
):
    """Phase 0: check (or with --fix, install) the system packages and
    Docker setup a first run needs. Idempotent - safe to re-run."""

    report = ensure_system_ready(fix=fix, offline=offline)

    if report["offline_rows"] is not None:

        console.print(
            "[yellow]Offline mode - nothing will be fetched from the network. "
            "Here's what this machine still needs:[/yellow]"
        )

        present = [row["name"] for row in report["offline_rows"] if row["present"]]
        missing = [row for row in report["offline_rows"] if not row["present"]]

        if present:
            console.print(f"[green]Already present:[/green] {', '.join(present)}")

        if missing:
            console.print("[red]Missing:[/red]")
            for row in missing:
                console.print(f"  [red]- {row['name']}[/red]  {row['remediation']}")
            console.print(
                "\nBring these onto this machine (or install them on a connected box "
                "first), or re-run without --offline once a connection exists."
            )
        else:
            console.print("[green]Everything needed is already present.[/green]")

        raise typer.Exit(code=0 if not missing else 1)

    for step in report["did"]:
        console.print(f"[green]✓[/green] {step}")

    if report["needs_reboot"]:
        console.print(
            "\n[yellow]Docker was layered via rpm-ostree (atomic OS). Reboot, "
            "then run ./install again - it will pick up from here.[/yellow]\n"
            "  sudo systemctl reboot"
        )
        raise typer.Exit(code=0)

    if report["needs_root"]:
        console.print(
            "\n[red]Phase 0 needs root to install Docker / system packages.[/red]\n"
            "  sudo ./install"
        )
        raise typer.Exit(code=1)

    if report["ready"]:
        console.print("[green]System is ready.[/green]")
        raise typer.Exit(code=0)

    console.print("\n[red]Still missing:[/red] " + ", ".join(report["missing"]))
    console.print("Run  ./install  (or  sudo vulcan preflight --fix ) to install these.")
    raise typer.Exit(code=1)


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


@app.command()
def configure():
    """
    Fill in credentials for services in the already-built stack (VPN
    provider + key, Cloudflare tunnel token, Tailscale auth key, Pi-hole
    admin password). Run after `vulcan build` / a Guided Setup that
    generated the stack but left credentials blank.
    """

    previous = load_previous_state(STACK_DIR)

    if previous is None:
        console.print("[red]No stack found. Run `vulcan build` first.[/red]")
        raise typer.Exit(code=1)

    config = _config_from_previous_state(previous)

    from installer.configure import pending_credentials, configured_credentials

    already = configured_credentials(config)
    pending = [item["service"] for item in pending_credentials(config)]

    if already:
        console.print(f"[green]Already configured:[/green] {', '.join(already)}")
    if not pending:
        console.print("[green]Nothing left to configure.[/green]")
        return

    console.print(f"[bold]Needs credentials:[/bold] {', '.join(pending)}")
    result = configure_pending(config, non_interactive=False)

    if result["written"]:
        console.print(f"[green]Wrote:[/green] {', '.join(result['written'])}")

    if result["still_blank"]:
        console.print(f"[yellow]Still blank:[/yellow] {', '.join(result['still_blank'])}")

    if not result["written"] and not result["still_blank"]:
        console.print("[green]All enabled services already have their credentials.[/green]")


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

    plan = plan_storage_layout(device_paths, mount_point, filesystem, raid_level, confirm_wipe)

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
        cloudflared=None,
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
        sportarr=None,
        tracearr=None,
        threadfin=None,
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
def build(
    tier: str | None = typer.Option(None, "--tier", help="light, medium, or heavy"),
    media_path: str | None = typer.Option(None, "--media-path"),
    non_interactive: bool = typer.Option(False, "--non-interactive"),
    yes: bool = typer.Option(False, "--yes"),
    vpn: bool | None = typer.Option(None, "--vpn/--no-vpn"),
    cloudflared: bool | None = typer.Option(None, "--cloudflared/--no-cloudflared"),
    sabnzbd: bool | None = typer.Option(None, "--sabnzbd/--no-sabnzbd"),
    recyclarr: bool | None = typer.Option(None, "--recyclarr/--no-recyclarr"),
    homepage: bool | None = typer.Option(None, "--homepage/--no-homepage"),
    homepage_private: bool | None = typer.Option(
        None, "--homepage-private/--homepage-public"
    ),
    metube: bool | None = typer.Option(None, "--metube/--no-metube"),
    downtify: bool | None = typer.Option(None, "--downtify/--no-downtify"),
    netdata: bool | None = typer.Option(None, "--netdata/--no-netdata"),
    vaultwarden: bool | None = typer.Option(None, "--vaultwarden/--no-vaultwarden"),
    dashy: bool | None = typer.Option(None, "--dashy/--no-dashy"),
    dashy_private: bool | None = typer.Option(None, "--dashy-private/--dashy-public"),
    pihole: bool | None = typer.Option(None, "--pihole/--no-pihole"),
    sportarr: bool | None = typer.Option(None, "--sportarr/--no-sportarr"),
    tracearr: bool | None = typer.Option(None, "--tracearr/--no-tracearr"),
    threadfin: bool | None = typer.Option(None, "--threadfin/--no-threadfin"),
    gpu: bool | None = typer.Option(None, "--gpu/--no-gpu"),
    puid: int | None = typer.Option(None, "--puid"),
    pgid: int | None = typer.Option(None, "--pgid"),
    timezone: str | None = typer.Option(None, "--timezone"),
    services: str | None = typer.Option(None, "--services"),
    domain: str | None = typer.Option(None, "--domain"),
    cloudflare_dns: bool = typer.Option(False, "--cloudflare-dns"),
    cloudflare_email: str | None = typer.Option(None, "--cloudflare-email"),
    auth_username: str | None = typer.Option(None, "--auth-username"),
    auth_password: str | None = typer.Option(None, "--auth-password"),
    auth_users: str | None = typer.Option(None, "--auth-users"),
    from_plan: str | None = typer.Option(
        None, "--from-plan",
        help="Seed tier/services/settings from a file written by `vulcan plan export` "
        "instead of this machine's own saved state - every other flag here still "
        "overrides the plan's value for that one field."
    ),
):
    """
    Generate stack/docker-compose.yml + .env from your choices and stop -
    never starts anything, never needs Docker. Run `vulcan start` once
    Docker is ready. Mirrors every option of the top-level guided run
    (`vulcan --help`) bar the start-related ones.
    """

    run_install(
        tier=tier,
        media_path=media_path,
        non_interactive=non_interactive,
        yes=yes,
        vpn=vpn,
        cloudflared=cloudflared,
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
        sportarr=sportarr,
        tracearr=tracearr,
        threadfin=threadfin,
        start=False,
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
        plan_path=from_plan,
    )


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


@plan_app.command(name="export")
def plan_export(
    file: str = typer.Argument("vulcan-plan.json", help="Where to write the plan"),
):
    """
    Write the currently-generated stack's shape to a JSON file: tier,
    enabled services, domain/routing settings, PUID/PGID/timezone.
    No credentials - those live only in stack/.env. Reuse it with
    `vulcan build --from-plan <file>` on this machine or another one.
    """

    state = load_previous_state(STACK_DIR)

    if state is None:
        console.print(
            f"[red]No generated stack found ({STACK_DIR / STATE_FILENAME} is missing or "
            "invalid) - run `vulcan build` first.[/red]"
        )
        raise typer.Exit(code=1)

    export_plan(state, Path(file))
    console.print(f"[green]Plan written to {file}[/green]")


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


@app.command(name="export-bundle")
def export_bundle_command(
    output: str | None = typer.Option(
        None, "--output", help="Directory for the offline bundle; defaults into exports/"
    ),
    platform: str | None = typer.Option(
        None,
        "--platform",
        help="Target platform tag (e.g. manylinux2014_aarch64) to cross-build for another arch. "
        "Omit to build for this machine.",
    ),
):
    """
    Build a self-contained offline bundle of Vulcan's own Python deps with
    `pip download`, for a machine with no internet access. Run this on a
    connected box (or for the exact target arch with --platform), carry the
    tarball across, then `vulcan install-bundle <file>` on the offline box.
    """

    dest = Path(output) if output is not None else Path("exports")
    dest.mkdir(parents=True, exist_ok=True)

    result = bundle_dependencies(dest, platform=platform)

    if not result["success"]:
        console.print(f"[red]{result['error']}[/red]")
        raise typer.Exit(code=1)

    version = __version__
    arch_label = platform or "current"
    packaged = package_bundle(dest, arch_label, version, runtime_dependencies())

    if not packaged["success"]:
        console.print(f"[red]{packaged['error']}[/red]")
        raise typer.Exit(code=1)

    console.print(f"[green]Offline bundle written to {packaged['bundle_path']}[/green]")
    console.print("[yellow]Carry this tarball to the offline machine and run "
                  "`vulcan install-bundle <file>`[/yellow]")


@app.command(name="install-bundle")
def install_bundle_command(
    bundle_file: str = typer.Argument(..., help="Path to the tarball from `vulcan export-bundle`"),
):
    """
    Untar an offline bundle and `pip install --no-index --find-links` from it
    into the current environment - works with no internet access.
    """

    dest = Path("exports") / "installed"
    extracted = extract_bundle(bundle_file, dest)

    if not extracted["success"]:
        console.print(f"[red]{extracted['error']}[/red]")
        raise typer.Exit(code=1)

    installed = install_from_wheelhouse(
        Path(extracted["wheel_dir"]), runtime_dependencies()
    )

    if not installed["success"]:
        console.print(f"[red]{installed['error']}[/red]")
        raise typer.Exit(code=1)

    console.print("[green]Wheels installed from the offline bundle.[/green]")


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
    cloudflared: bool | None = typer.Option(
        None, "--cloudflared/--no-cloudflared",
        help="Cloudflare Tunnel for secure remote access - requires Cloudflare account and tunnel token"
    ),
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
    sportarr: bool | None = typer.Option(
        None, "--sportarr/--no-sportarr",
        help="Sports PVR - monitors leagues, downloads events"
    ),
    tracearr: bool | None = typer.Option(
        None, "--tracearr/--no-tracearr",
        help="Real-time stream analytics (Tautulli/Jellystat replacement)"
    ),
    threadfin: bool | None = typer.Option(
        None, "--threadfin/--no-threadfin",
        help="M3U/IPTV proxy for Jellyfin/Plex/Emby live TV"
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
    from_plan: str | None = typer.Option(
        None, "--from-plan",
        help="Seed tier/services/settings from a file written by `vulcan plan export` "
        "instead of this machine's own saved state - every other flag here still "
        "overrides the plan's value for that one field."
    ),
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
        cloudflared=cloudflared,
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
        sportarr=sportarr,
        tracearr=tracearr,
        threadfin=threadfin,
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
        dry_run=dry_run,
        plan_path=from_plan,
    )


def run_install(
    tier: str | None,
    media_path: str | None,
    non_interactive: bool,
    yes: bool,
    vpn: bool | None,
    cloudflared: bool | None,
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
    sportarr: bool | None,
    tracearr: bool | None,
    threadfin: bool | None,
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
    dry_run: bool = False,
    plan_path: str | None = None
):

    if non_interactive and not yes:
        console.print("[red]--yes is required alongside --non-interactive.[/red]")
        raise typer.Exit(code=1)

    if plan_path is not None:

        previous = load_plan(Path(plan_path))

        if previous is None:
            console.print(
                f"[red]Could not read a valid plan from {plan_path} (missing, invalid "
                "JSON, or an unknown tier name).[/red]"
            )
            raise typer.Exit(code=1)

    else:
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
    phases = ["Detect system", "Storage setup", "Configure stack", "Generate stack", "Configure services"]
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

        # Phase: Storage setup - offer to provision blank drives before Docker/tier
        if previous is None and media_path is None:
            available_devices = list_unprotected_devices()
            if available_devices:
                device_list = ", ".join(
                    f"{d['path']} ({d['size']}){' [blank]' if not d.get('fstype') and not d.get('children') else ''}"
                    for d in available_devices
                )
                console.print(f"[bold]Available drives for media storage:[/bold] {device_list}")
                console.print("[dim]Drives marked [blank] have no filesystem/partitions. Others will be wiped if selected.[/dim]")
                if not non_interactive:
                    if typer.confirm("Set up one or more drives as a media storage volume (mdadm RAID if 2+)?") :
                        default_mount = "/mnt/media"
                        mount_point = typer.prompt("Mount point for the media volume", default=default_mount)
                        console.print("\nSelect drives to use (comma-separated, e.g. /dev/sdb,/dev/sdc):")
                        for i, d in enumerate(available_devices):
                            status = "blank" if not d.get('fstype') and not d.get('children') else f"has {d.get('fstype', 'partition')}"
                            console.print(f"  {i+1}. {d['path']} ({d['size']}) - {status}")
                        chosen = typer.prompt("Drives to use").strip()
                        device_paths = [p.strip() for p in chosen.split(",") if p.strip()]
                        valid_paths = {d["path"] for d in available_devices}
                        if device_paths and set(device_paths).issubset(valid_paths):
                            raid_level = _choose_raid_level(len(device_paths))
                            if raid_level is not None or len(device_paths) <= 1:
                                plan = plan_storage_layout(device_paths, mount_point, raid_level=raid_level)
                                console.print(describe_storage_plan(plan))
                                if not plan["error"]:
                                    typed = typer.prompt(
                                        f"Type the exact device list to confirm ({', '.join(device_paths)})",
                                        hide_input=False,
                                    )
                                    if {p.strip() for p in typed.split(",") if p.strip()} == set(device_paths):
                                        result = apply_storage_layout(plan)
                                        for cmd in result.get("ran", []):
                                            console.print(f"[green]ran:[/green] {cmd}")
                                        for note in result.get("skipped", []):
                                            console.print(f"[cyan]skipped:[/cyan] {note}")
                                        if result["success"]:
                                            media_path = mount_point
                                            panel.note(f"[green]Storage provisioned at {mount_point}[/green]")
        panel.advance()

        # Phase 0 adds the user to the docker group in a separate (root)
        # process; this process's group list is still stale, but
        # `./install`'s final `exec` goes through `runuser -u $SUDO_USER`,
        # which builds a fresh group list from the DB - so by the time
        # this code runs, the docker group is already effective. (A
        # non-root `./install` where Phase 0 had nothing to do added no
        # group, so nothing is stale either.) Kept for _start's
        # use_group_workaround signature.
        group_just_added = False

        config = _gather_generation_config(
            info, tier, media_path, vpn, cloudflared, sabnzbd, recyclarr, homepage,
            homepage_private, metube, downtify, netdata, vaultwarden, dashy,
            dashy_private, pihole, sportarr, tracearr, threadfin, gpu,
            puid, pgid, timezone, non_interactive, previous,
            custom_services_from_flag, domain, cloudflare_dns,
            cloudflare_email, auth_username, auth_password, auth_users_raw, panel
        )
        panel.advance()

        build_result = _build(
            config, non_interactive, yes,
            on_phase=panel.advance, panel=panel
        )

        # Phase 6 - Configure: fill in the credentials enabled services
        # need but don't have yet (VPN key, tunnel token, ...). Env vars
        # (set by the menu or exported by the user) + --domain seed the
        # answers; anything still blank gets prompted interactively, or
        # left for `vulcan configure` on a non-interactive run.
        vpn_answers = {
            "VPN_SERVICE_PROVIDER": os.environ.get("VPN_SERVICE_PROVIDER", ""),
            "VPN_TYPE": os.environ.get("VPN_TYPE", ""),
            "WIREGUARD_PRIVATE_KEY": os.environ.get("WIREGUARD_PRIVATE_KEY", ""),
            "WIREGUARD_ADDRESSES": os.environ.get("WIREGUARD_ADDRESSES", ""),
            # OpenVPN has no env.j2 keys yet - see follow-up
            "DOMAIN": config.domain or "",
        }

        configure_pending(
            config, non_interactive,
            answers={k: v for k, v in vpn_answers.items() if v}
        )
        panel.advance()

        if start is None:
            start = False if non_interactive else typer.confirm(
                "Start the stack now?", default=True
            )

        if start is not False:
            _start(
                config, build_result, group_just_added,
                on_phase=panel.advance, panel=panel
            )
        else:
            _report_stack_generated(config, build_result, panel=panel)

        panel.finish(True)


def _assert_docker_ready(info: SystemInfo) -> SystemInfo:
    """Phase 0 (`./install` / `vulcan preflight --fix`) is responsible for
    getting Docker ready. By the time run_install runs it either is, or we
    stop here and point the user back at ./install."""

    state = detect_docker()
    info.docker_installed = state["docker_installed"]
    info.docker_running = state["docker_running"]
    info.docker_accessible = state.get("docker_accessible", True)
    info.docker_compose_v2 = state["docker_compose_v2"]

    if not (info.docker_installed and info.docker_running
            and info.docker_accessible and info.docker_compose_v2):
        console.print(
            "[red]Docker isn't ready.[/red] Run  ./install  again "
            "(or  vulcan preflight --fix ) to install/start it and add your "
            "user to the docker group, then retry."
        )
        raise typer.Exit(code=1)

    return info


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

    default = next(
        (o["level"] for o in options if o["recommended"]),
        options[0]["level"] if options else None,
    )

    while True:

        raw = typer.prompt(
            "RAID level (number or RAID#)",
            default=default,
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


# (required_both, required_neither, message) - an error fires if a stack
# contains all of `required_both`, or all of `required_neither`.
#
# gluetun + tailscale used to live here as mutually exclusive. They're
# not: gluetun is container-scoped (only whatever opts into
# `network_mode: service:gluetun` - qbittorrent - routes through it, the
# host routing table is never touched), and tailscale runs
# `network_mode: host` for inbound mesh access to the management UIs.
# The common split - gluetun for download egress, tailscale for admin
# ingress - is a real, supported layout. The one interaction is
# TS_ACCEPT_DNS, handled in the compose template (off when pihole/
# adguardhome is also enabled so tailscale doesn't take the host
# resolver from them).
_SERVICE_CONFLICTS: list[tuple[set[str], set[str], str]] = []


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


def _resolve_service_deps(services: set[str]) -> set[str]:
    """Auto-add required dependencies from _SERVICE_DEPS to the service set."""
    result = set(services)
    changed = True
    while changed:
        changed = False
        for service, dependency, _ in _SERVICE_DEPS:
            if service in result and dependency not in result:
                result.add(dependency)
                changed = True
    return result


def _gather_generation_config(
    info: SystemInfo,
    tier: str | None,
    media_path: str | None,
    vpn: bool | None,
    cloudflared: bool | None,
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
    sportarr: bool | None,
    tracearr: bool | None,
    threadfin: bool | None,
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

    # Read VPN env vars unconditionally - GenerationConfig consumes them
    # on every path (below), so leaving them unbound when Gluetun is off
    # (incl. custom --services mode, which skips the prompt sections)
    # crashes with UnboundLocalError instead of passing None.
    vpn_service_provider = os.environ.get("VPN_SERVICE_PROVIDER")
    vpn_type = os.environ.get("VPN_TYPE")
    wireguard_private_key = os.environ.get("WIREGUARD_PRIVATE_KEY")
    wireguard_addresses = os.environ.get("WIREGUARD_ADDRESSES")
    openvpn_user = os.environ.get("OPENVPN_USER")
    openvpn_password = os.environ.get("OPENVPN_PASSWORD")

    if previous is not None:

        # A plan loaded via --from-plan has no generated_at (deliberately
        # stripped on export - see export_plan()) and isn't necessarily
        # "an existing stack" at all, just a previous choice to seed
        # defaults from - previous['generated_at'] would KeyError there.
        generated_note = f", generated {previous['generated_at']}" if previous.get("generated_at") else ""

        panel.note(
            f"Found an existing [bold]{previous['tier']}[/bold] configuration{generated_note}. "
            "Using it as defaults - pass flags to override."
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
    # Show all services per tier before the recommendation - but only when
    # the tier is still being chosen. A non-interactive run (every whiptail
    # Guided Setup) has already decided, so this is just the wall of text
    # the comment above is about.
    if not non_interactive:
        console.print("\n[bold]Services included in each tier:[/bold]")
        for tier_name in ("light", "medium", "heavy"):
            tier_obj = TIERS[tier_name]
            core = [s for s in tier_obj.services if not s.optional]
            opt = [s for s in tier_obj.services if s.optional]
            rec_marker = " ← recommended" if tier_obj.name == recommendation.tier.name else ""
            console.print(f"\n  {tier_obj.display_name}{rec_marker}:")
            console.print(f"    Core ({len(core)}): {', '.join(s.display_name for s in core)}")
            console.print(f"    Optional ({len(opt)}): {', '.join(s.display_name for s in opt)}")

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

            # Build categories from service definitions
            category_map: dict[str, list[tuple[str, str]]] = {}
            for svc in ALL_SERVICES:
                if svc.key in valid_keys:
                    category_map.setdefault(svc.category, []).append((svc.key, svc.display_name))

            console.print("[bold]Available services by category:[/bold]")
            for cat in sorted(category_map.keys()):
                svcs = category_map[cat]
                console.print(f"  {cat}: {', '.join(f'{k} ({n})' for k, n in svcs)}")
            console.print()

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

    # Bound here, before any branch, so every path into GenerationConfig
    # below has them - they used to be assigned only inside the
    # `if enable_vpn:` block, which meant a VPN-off run (the default in
    # --non-interactive, and every --no-vpn menu path) raised
    # UnboundLocalError building the config.
    vpn_service_provider = os.environ.get("VPN_SERVICE_PROVIDER")
    vpn_type = os.environ.get("VPN_TYPE")
    wireguard_private_key = os.environ.get("WIREGUARD_PRIVATE_KEY")
    wireguard_addresses = os.environ.get("WIREGUARD_ADDRESSES")
    openvpn_user = os.environ.get("OPENVPN_USER")
    openvpn_password = os.environ.get("OPENVPN_PASSWORD")

    if custom_services_selected is None:

        console.print("\n[bold]Downloads & Network[/bold]")        # Defaults to True (opt-out, not opt-in) on a fresh install -
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
        vpn_default = "gluetun" in previous["enabled_optional"] if previous else False

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

            # Credentials (provider, key, ...) are no longer gathered here -
            # Phase 6 (`configure_pending`) fills them in after the stack is
            # built, from env vars or an interactive walkthrough. The
            # os.environ reads above still seed GenerationConfig so
            # write_stack can put real values / placeholders in .env.
            enabled_optional.add("gluetun")

    if custom_services_selected is None:

        console.print("\n[bold]Infrastructure[/bold]")

        cloudflared_default = "cloudflared" in previous["enabled_optional"] if previous else False

        if cloudflared is None:

            enable_cloudflared = cloudflared_default if non_interactive else typer.confirm(
                "Enable Cloudflare Tunnel? Requires a Cloudflare account and tunnel token. "
                "See https://github.com/cloudflare/cloudflared for setup.",
                default=cloudflared_default
            )

        else:
            enable_cloudflared = cloudflared

        if enable_cloudflared:
            enabled_optional.add("cloudflared")

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

        console.print("\n[bold]Media Management[/bold]")

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

        console.print("\n[bold]Dashboards[/bold]")

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

        console.print("\n[bold]Downloads[/bold]")

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

        console.print("\n[bold]Monitoring[/bold]")

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

        console.print("\n[bold]System[/bold]")

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

    sportarr_default = "sportarr" in previous["enabled_optional"] if previous else False

    if sportarr is not None:
        enable_sportarr = sportarr
    elif non_interactive:
        enable_sportarr = sportarr_default
    else:
        enable_sportarr = False

    if enable_sportarr:
        enabled_optional.add("sportarr")

    tracearr_default = "tracearr" in previous["enabled_optional"] if previous else False

    if tracearr is not None:
        enable_tracearr = tracearr
    elif non_interactive:
        enable_tracearr = tracearr_default
    else:
        enable_tracearr = False

    if enable_tracearr:
        enabled_optional.add("tracearr")

    threadfin_default = "threadfin" in previous["enabled_optional"] if previous else False

    if threadfin is not None:
        enable_threadfin = threadfin
    elif non_interactive:
        enable_threadfin = threadfin_default
    else:
        enable_threadfin = False

    if enable_threadfin:
        enabled_optional.add("threadfin")

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
    final_services = _resolve_service_deps(final_services)
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
        dashy_private=dashy_private_value,
        vpn_service_provider=vpn_service_provider,
        vpn_type=vpn_type,
        wireguard_private_key=wireguard_private_key,
        wireguard_addresses=wireguard_addresses,
        openvpn_user=openvpn_user,
        openvpn_password=openvpn_password
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


def _build(
    config: GenerationConfig,
    non_interactive: bool,
    yes: bool,
    on_phase=None,
    panel: RunPanel | _NoOpPanel | None = None
) -> dict:
    """
    Generate stack/docker-compose.yml + .env from the gathered config -
    review, confirm, write_stack, surface warnings. Never touches Docker,
    so a first run can generate a stack before Docker is installed/started
    (Phase 0 / `vulcan start` handle that). Returns the write_stack result.
    """

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
    panel.note(f"  Sportarr: {'enabled' if 'sportarr' in config.enabled_optional else 'disabled'}")
    panel.note(f"  Tracearr: {'enabled' if 'tracearr' in config.enabled_optional else 'disabled'}")
    panel.note(f"  Threadfin: {'enabled' if 'threadfin' in config.enabled_optional else 'disabled'}")
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

    return result


def _start(
    config: GenerationConfig,
    build_result: dict,
    group_just_added: bool,
    on_phase=None,
    panel: RunPanel | _NoOpPanel | None = None
) -> None:
    """
    Bring an already-generated stack up: assert Docker is ready (Phase 0's
    job, not ours - bail to ./install if not), resolve port/network
    conflicts, `docker compose up -d`, then verify the containers actually
    stayed up and print the access summary. Raises typer.Exit on any failure.
    """

    panel = panel if panel is not None else _NoOpPanel(console)

    # Phase 0 (./install / vulcan preflight --fix) owns getting Docker
    # ready. Starting the stack is the first step that actually needs it -
    # assert here and bail to ./install rather than install anything.
    _assert_docker_ready(detect_system())

    result = _resolve_port_conflicts(config, build_result)

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

    if proc.returncode != 0:
        console.print("[red]Failed to start the stack - check `docker compose logs`.[/red]")
        raise typer.Exit(code=1)

    if on_phase is not None:
        on_phase("Start stack")

    # `up -d` only waits for containers to start, not for the process
    # inside to actually stay up - a real check here catches a
    # crash-loop `up -d` alone would silently report as success.
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


def _report_stack_generated(
    config: GenerationConfig,
    build_result: dict,
    panel: RunPanel | _NoOpPanel | None = None
) -> None:
    """The "generated but not started" summary - what `_start` would have
    printed, plus the manual `up -d` line and any service-specific
    follow-ups (Cloudflare Tunnel token, extra Authelia users)."""

    panel = panel if panel is not None else _NoOpPanel(console)

    panel.note("[bold]Stack generated (not started):[/bold]")

    summary = render_stack_summary(config, detect_host_ip())

    if summary:
        panel.note(summary)

    setup_order = render_setup_order(config, detect_host_ip())

    if setup_order:
        panel.note(f"\n{setup_order}")

    panel.note(
        "\nRun this when you're ready:\n"
        f"  docker compose -f {build_result['compose_path']} "
        f"--env-file {build_result['env_path']} up -d"
    )

    if config.auth_users:
        panel.note(
            f"\nAuthelia users configured: admin ('{config.auth_username}') + "
            f"{len(config.auth_users)} additional user(s). Admin has full access; "
            "additional users can only reach Jellyfin and Seerr."
        )

    if "cloudflared" in enabled_service_keys(config):
        panel.note(
            "\nCloudflare Tunnel: fill in TUNNEL_TOKEN in "
            f"{build_result['env_path']} before starting. Create a tunnel at "
            "Zero Trust dashboard > Networks > Tunnels > Create a tunnel > "
            "Docker tab, then add a Public Hostname pointing at "
            "http://traefik:8081."
        )


if __name__ == "__main__":
    app()
