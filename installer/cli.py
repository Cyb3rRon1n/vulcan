import getpass
from pathlib import Path

import typer
from rich.console import Console

from installer import __version__
from installer.detect import SystemInfo, detect_disk, detect_docker, detect_system
from installer.docker_setup import (
    add_user_to_docker_group,
    ensure_compose_v2,
    install_docker,
    install_plan_for,
    run_docker_command,
    start_docker_service,
)
from installer.generate import (
    STACK_DIR,
    GenerationConfig,
    default_puid_pgid,
    default_timezone,
    load_previous_state,
    write_stack,
)
from installer.post_install import backup_stack, latest_backup, restore_stack, update_stack
from installer.tiers import ALL_SERVICES, TIERS, recommend_tier


app = typer.Typer(
    name="vulcan",
    help="An intelligent media stack forge - inspects your system and builds a tailored Jellyfin + *arr homelab."
)

console = Console()


@app.command()
def version():
    """
    Display the Vulcan version.
    """

    console.print(
        f"[bold red]Vulcan[/bold red] version {__version__}"
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

    result = update_stack(str(compose_path), str(STACK_DIR / ".env"))

    if not result["success"]:
        console.print(f"[red]{result['error']}[/red]")
        raise typer.Exit(code=1)

    console.print("[green]Stack updated.[/green]")


@app.command()
def backup():
    """
    Archive the generated stack's config directories and compose files.
    """

    result = backup_stack()

    if not result["success"]:
        console.print(f"[red]{result['error']}[/red]")
        raise typer.Exit(code=1)

    console.print(f"[green]Backup written to {result['backup_path']}[/green]")

    for warning in result["warnings"]:
        console.print(f"[yellow]! {warning}[/yellow]")


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

    result = restore_stack(chosen, str(compose_path), str(env_path))

    if not result["success"]:
        console.print(f"[red]{result['error']}[/red]")
        raise typer.Exit(code=1)

    console.print("[green]Stack restored.[/green]")

    if start is None:
        do_start = False if non_interactive else typer.confirm("Start the restored stack now?", default=True)
    else:
        do_start = start

    if do_start:

        proc = run_docker_command(
            ["docker", "compose", "-f", str(compose_path), "--env-file", str(env_path), "up", "-d"]
        )

        if proc.returncode == 0:
            console.print("[green]Stack is up.[/green]")
        else:
            console.print("[red]Failed to start the stack - check `docker compose logs`.[/red]")
            raise typer.Exit(code=1)


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
    start: bool | None = typer.Option(None, "--start/--no-start"),
    gpu: bool | None = typer.Option(None, "--gpu/--no-gpu"),
    puid: int | None = typer.Option(None, "--puid"),
    pgid: int | None = typer.Option(None, "--pgid"),
    timezone: str | None = typer.Option(None, "--timezone"),
    services: str | None = typer.Option(
        None, "--services",
        help="Comma-separated service keys for a custom selection, overriding the tier's default set"
    ),
    plain: bool = typer.Option(False, "--plain", help="Use the plain CLI prompts instead of the TUI")
):
    if ctx.invoked_subcommand is not None:
        return

    if not non_interactive and not plain:

        from installer.tui import run_tui

        run_tui()
        return

    run_install(
        tier=tier,
        media_path=media_path,
        non_interactive=non_interactive,
        yes=yes,
        vpn=vpn,
        sabnzbd=sabnzbd,
        recyclarr=recyclarr,
        start=start,
        gpu=gpu,
        puid=puid,
        pgid=pgid,
        timezone=timezone,
        services=services
    )


def run_install(
    tier: str | None,
    media_path: str | None,
    non_interactive: bool,
    yes: bool,
    vpn: bool | None,
    sabnzbd: bool | None,
    recyclarr: bool | None,
    start: bool | None,
    gpu: bool | None,
    puid: int | None,
    pgid: int | None,
    timezone: str | None,
    services: str | None
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

    console.print("[bold]Detecting your system...[/bold]")
    info = detect_system()

    console.print(
        f"  CPU: {info.cpu_cores_logical} logical cores ({info.cpu_model or 'unknown'})\n"
        f"  RAM: {info.ram_total_gb}GB total\n"
        f"  GPU: {info.gpu_vendor or 'none detected'}\n"
        f"  OS: {info.os_pretty_name or info.os_id or 'unknown'} ({info.architecture})"
    )

    info, group_just_added = _ensure_docker_ready(info, non_interactive, yes)

    if not (info.docker_installed and info.docker_running and info.docker_compose_v2):
        console.print("[red]Docker isn't ready - can't continue.[/red]")
        raise typer.Exit(code=1)

    config = _gather_generation_config(
        info, tier, media_path, vpn, sabnzbd, recyclarr, gpu, puid, pgid, timezone,
        non_interactive, previous, custom_services_from_flag
    )

    _generate_and_maybe_start(config, non_interactive, yes, start, group_just_added)


def _ensure_docker_ready(
    info: SystemInfo,
    non_interactive: bool,
    yes: bool
) -> tuple[SystemInfo, bool]:

    group_just_added = False

    if info.docker_installed and info.docker_running and info.docker_compose_v2:

        console.print("[green]Docker is ready.[/green]")
        return info, group_just_added

    if not info.docker_installed:

        plan = install_plan_for(info.os_id)

        if plan is None:

            console.print(
                f"[red]No known automatic install method for '{info.os_id}'. "
                "Install Docker manually: https://docs.docker.com/engine/install/[/red]"
            )

            return info, group_just_added

        console.print(f"Docker will be installed via: {plan['description']}")

        if yes or typer.confirm("Install Docker now?"):

            install_docker(info.os_id)
            start_docker_service()
            add_user_to_docker_group(getpass.getuser())
            ensure_compose_v2(info.os_id)
            group_just_added = True

    elif not info.docker_running:

        console.print("Docker is installed but not running.")

        if yes or typer.confirm("Start the Docker service now?"):
            start_docker_service()

    elif not info.docker_compose_v2:

        console.print("Docker Compose v2 isn't available.")

        if yes or typer.confirm("Attempt to install Docker Compose v2 now?"):
            ensure_compose_v2(info.os_id)

    docker_state = detect_docker()
    info.docker_installed = docker_state["docker_installed"]
    info.docker_running = docker_state["docker_running"]
    info.docker_compose_v2 = docker_state["docker_compose_v2"]

    return info, group_just_added


def _gather_generation_config(
    info: SystemInfo,
    tier: str | None,
    media_path: str | None,
    vpn: bool | None,
    sabnzbd: bool | None,
    recyclarr: bool | None,
    gpu: bool | None,
    puid: int | None,
    pgid: int | None,
    timezone: str | None,
    non_interactive: bool,
    previous: dict | None,
    custom_services_from_flag: set[str] | None
) -> GenerationConfig:

    if previous is not None:

        console.print(
            f"Found an existing [bold]{previous['tier']}[/bold] stack, generated "
            f"{previous['generated_at']}. Using it as defaults - pass flags to override."
        )

    if media_path is None:

        default_media_path = previous["media_path"] if previous else str(Path.home() / "media")

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

    recommendation = recommend_tier(info)

    console.print(
        f"Recommended tier: [bold]{recommendation.tier.display_name}[/bold] - "
        f"{recommendation.explanation}"
    )

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

                custom_services_selected = requested
                break

        else:
            custom_services_selected = None

    enabled_optional = set()

    if custom_services_selected is None and chosen_tier_name == "medium":

        vpn_default = "gluetun" in previous["enabled_optional"] if previous else False

        if vpn is None:

            enable_vpn = vpn_default if non_interactive else typer.confirm(
                "Enable Gluetun VPN for qBittorrent? "
                "(you'll need to add real VPN credentials afterward)",
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

    return GenerationConfig(
        tier=chosen_tier,
        media_path=media_path,
        puid=final_puid,
        pgid=final_pgid,
        timezone=final_tz,
        enabled_optional=enabled_optional,
        gpu_vendor=gpu_vendor_to_use,
        custom_services=custom_services_selected
    )


def _generate_and_maybe_start(
    config: GenerationConfig,
    non_interactive: bool,
    yes: bool,
    start: bool | None,
    group_just_added: bool
) -> dict:

    console.print("\n[bold]Review[/bold]")
    console.print(f"  Tier: {config.tier.display_name}")
    console.print(f"  Media path: {config.media_path}")
    console.print(f"  PUID/PGID: {config.puid}/{config.pgid}")
    console.print(f"  Timezone: {config.timezone}")
    console.print(f"  Gluetun VPN: {'enabled' if 'gluetun' in config.enabled_optional else 'disabled'}")
    console.print(f"  SABnzbd: {'enabled' if 'sabnzbd' in config.enabled_optional else 'disabled'}")
    console.print(f"  Recyclarr: {'enabled' if 'recyclarr' in config.enabled_optional else 'disabled'}")
    console.print(f"  GPU passthrough: {config.gpu_vendor or 'disabled'}")

    if config.custom_services is not None:
        console.print(f"  Services: {', '.join(sorted(config.custom_services))}")

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

    console.print(f"[green]Stack written to {result['compose_path']}[/green]")

    for warning in result["warnings"]:
        console.print(f"[yellow]! {warning}[/yellow]")

    if start is None:
        do_start = False if non_interactive else typer.confirm("Start the stack now?", default=True)
    else:
        do_start = start

    if do_start:

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
            console.print("[green]Stack is up.[/green]")
        else:
            console.print("[red]Failed to start the stack - check `docker compose logs`.[/red]")
            raise typer.Exit(code=1)

    else:

        console.print(
            "Run this when you're ready:\n"
            f"  docker compose -f {result['compose_path']} --env-file {result['env_path']} up -d"
        )

    return result


if __name__ == "__main__":
    app()
