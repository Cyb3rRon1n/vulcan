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
    GenerationConfig,
    default_puid_pgid,
    default_timezone,
    write_stack,
)
from installer.tiers import TIERS, recommend_tier


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


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    tier: str | None = typer.Option(None, "--tier", help="light, medium, or heavy"),
    media_path: str | None = typer.Option(None, "--media-path"),
    non_interactive: bool = typer.Option(False, "--non-interactive"),
    yes: bool = typer.Option(False, "--yes"),
    vpn: bool | None = typer.Option(None, "--vpn/--no-vpn"),
    start: bool | None = typer.Option(None, "--start/--no-start"),
    gpu: bool | None = typer.Option(None, "--gpu/--no-gpu"),
    puid: int | None = typer.Option(None, "--puid"),
    pgid: int | None = typer.Option(None, "--pgid"),
    timezone: str | None = typer.Option(None, "--timezone")
):
    if ctx.invoked_subcommand is not None:
        return

    run_install(
        tier=tier,
        media_path=media_path,
        non_interactive=non_interactive,
        yes=yes,
        vpn=vpn,
        start=start,
        gpu=gpu,
        puid=puid,
        pgid=pgid,
        timezone=timezone
    )


def run_install(
    tier: str | None,
    media_path: str | None,
    non_interactive: bool,
    yes: bool,
    vpn: bool | None,
    start: bool | None,
    gpu: bool | None,
    puid: int | None,
    pgid: int | None,
    timezone: str | None
):

    if non_interactive and not yes:
        console.print("[red]--yes is required alongside --non-interactive.[/red]")
        raise typer.Exit(code=1)

    if non_interactive and (tier is None or media_path is None):
        console.print("[red]--tier and --media-path are required in --non-interactive mode.[/red]")
        raise typer.Exit(code=1)

    if tier is not None and tier not in ("light", "medium", "heavy"):
        console.print(f"[red]--tier '{tier}' must be 'light', 'medium', or 'heavy'.[/red]")
        raise typer.Exit(code=1)

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
        info, tier, media_path, vpn, gpu, puid, pgid, timezone, non_interactive
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
    gpu: bool | None,
    puid: int | None,
    pgid: int | None,
    timezone: str | None,
    non_interactive: bool
) -> GenerationConfig:

    if media_path is None:
        media_path = typer.prompt("Media library path", default=str(Path.home() / "media"))

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

    else:

        default_choice = recommendation.tier.name

        chosen_tier_name = typer.prompt("Which tier? (light/medium/heavy)", default=default_choice)

        while chosen_tier_name not in ("light", "medium", "heavy"):
            chosen_tier_name = typer.prompt(
                "Please enter 'light', 'medium', or 'heavy'", default=default_choice
            )

    chosen_tier = TIERS[chosen_tier_name]

    enabled_optional = set()

    if chosen_tier_name == "medium":

        if vpn is None:

            enable_vpn = False if non_interactive else typer.confirm(
                "Enable Gluetun VPN for qBittorrent? "
                "(you'll need to add real VPN credentials afterward)",
                default=False
            )

        else:
            enable_vpn = vpn

        if enable_vpn:
            enabled_optional.add("gluetun")

    gpu_vendor_to_use = None

    if chosen_tier_name == "heavy" and info.gpu_vendor:

        if gpu is None:

            enable_gpu = True if non_interactive else typer.confirm(
                f"Enable hardware transcoding using the detected {info.gpu_vendor} GPU?",
                default=True
            )

        else:
            enable_gpu = gpu

        if enable_gpu:
            gpu_vendor_to_use = info.gpu_vendor

    default_puid, default_pgid = default_puid_pgid()
    default_tz = default_timezone()

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
        gpu_vendor=gpu_vendor_to_use
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
    console.print(f"  GPU passthrough: {config.gpu_vendor or 'disabled'}")

    if not yes and not typer.confirm("\nGenerate the stack with these settings?"):
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
