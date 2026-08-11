import getpass
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
    detect_media_redundancy,
    detect_system,
)
from installer.docker_setup import (
    add_user_to_docker_group,
    check_docker_ready,
    ensure_compose_v2,
    install_docker,
    install_plan_for,
    run_docker_command,
    start_docker_service,
)
from installer.generate import (
    STACK_DIR,
    WALKTHROUGH_URL,
    GenerationConfig,
    default_puid_pgid,
    default_timezone,
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
)
from installer.preflight import check_ports_available, format_port_conflicts
from installer.tiers import ALL_SERVICES, TIERS, recommend_tier, tier_description


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
def pull():
    """
    Pull images for the generated stack without starting it - useful to prepare
    a stack for an offline environment ahead of time.
    """

    compose_path = STACK_DIR / "docker-compose.yml"

    if not compose_path.exists():
        console.print("[red]No stack found - run `vulcan` first to generate one.[/red]")
        raise typer.Exit(code=1)

    result = pull_stack(str(compose_path), str(STACK_DIR / ".env"))

    if not result["success"]:
        console.print(f"[red]{result['error']}[/red]")
        raise typer.Exit(code=1)

    console.print(
        "[green]Images pulled.[/green] Run this whenever you're ready - no network "
        f"access needed at that point:\n  docker compose -f {compose_path} --env-file "
        f"{STACK_DIR / '.env'} up -d"
    )


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


@app.command()
def uninstall(
    non_interactive: bool = typer.Option(False, "--non-interactive"),
    yes: bool = typer.Option(False, "--yes"),
    purge_artifacts: bool = typer.Option(
        False, "--purge-artifacts", help="Also delete backups/ and exports/"
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
    )

    if not yes and not typer.confirm("Continue?"):
        console.print("Aborted.")
        raise typer.Exit(code=0)

    result = uninstall_stack(
        str(STACK_DIR / "docker-compose.yml"),
        str(STACK_DIR / ".env"),
        purge_artifacts=purge_artifacts
    )

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
    start: bool | None = typer.Option(None, "--start/--no-start"),
    gpu: bool | None = typer.Option(None, "--gpu/--no-gpu"),
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
    plain: bool = typer.Option(False, "--plain", help="Use the plain CLI prompts instead of the TUI"),
    offline: bool = typer.Option(
        False, "--offline",
        help="No internet access on this machine - skip automatic Docker install if it's missing"
    )
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
        homepage=homepage,
        homepage_private=homepage_private,
        metube=metube,
        downtify=downtify,
        netdata=netdata,
        vaultwarden=vaultwarden,
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
        offline=offline
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
    offline: bool = False
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

    info, group_just_added = _ensure_docker_ready(info, non_interactive, yes, offline)

    if not (info.docker_installed and info.docker_running and info.docker_compose_v2):
        console.print("[red]Docker isn't ready - can't continue.[/red]")
        raise typer.Exit(code=1)

    config = _gather_generation_config(
        info, tier, media_path, vpn, sabnzbd, recyclarr, homepage, homepage_private, metube,
        downtify, netdata, vaultwarden, gpu, puid, pgid, timezone,
        non_interactive, previous, custom_services_from_flag, domain, cloudflare_dns,
        cloudflare_email, auth_username, auth_password
    )

    _generate_and_maybe_start(config, non_interactive, yes, start, group_just_added)


def _ensure_docker_ready(
    info: SystemInfo,
    non_interactive: bool,
    yes: bool,
    offline: bool = False
) -> tuple[SystemInfo, bool]:

    group_just_added = False

    if info.docker_installed and info.docker_running and info.docker_compose_v2:

        console.print("[green]Docker is ready.[/green]")
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
    auth_password: str | None = None
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

    redundancy = detect_media_redundancy(media_path)
    description = describe_media_redundancy(redundancy)

    if description is not None:

        console.print(f"Media storage: {description}")

        if redundancy["redundant"] is False:
            console.print(
                "[yellow]! No drive-level redundancy - a single drive failure "
                "would mean data loss.[/yellow]"
            )

    recommendation = recommend_tier(info)

    console.print(
        f"Recommended tier: [bold]{recommendation.tier.display_name}[/bold] - "
        f"{recommendation.explanation}"
    )

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
                "Enable MeTube (YouTube downloader)?",
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
        port_overrides=dict(previous["port_overrides"]) if previous and previous.get("port_overrides") else {},
        homepage_private=homepage_private_value
    )


def _resolve_port_conflicts(config: GenerationConfig, result: dict, non_interactive: bool) -> dict:
    """
    Step two of the port-conflict work: check_ports_available() already
    diagnosed a real cause (see preflight.py), but the only thing this
    project ever did with that diagnosis was print it and refuse. This
    turns "here's what's wrong" into "let's fix it and retry" for the
    two real cases the diagnosis already distinguishes - your own
    orphaned containers (safe to clean up automatically) and an
    unrelated service (needs a different port, not a cleanup). A third,
    genuinely unresolvable case (a non-Docker/native service holding
    the port, or a service - Traefik, FlareSolverr - deliberately out
    of remap scope) still ends in the same clean refusal this always
    had; this only replaces the *dead end*, not the boundary.

    Loops rather than handling one pass, since fixing one conflict can
    surface another (e.g. a typed-in port that happens to collide with
    a second still-conflicting service) - each pass regenerates via
    write_stack() (same re-run-safe path every other regenerate uses)
    and re-checks for real before declaring victory or asking again.
    """

    while True:

        port_check = check_ports_available(result["compose_path"])

        if port_check["available"]:
            return result

        console.print("[red]Can't start - port(s) already in use:[/red]")
        console.print(format_port_conflicts(port_check))

        if non_interactive:
            console.print(
                "[red]Free them, then run this when you're ready:\n"
                f"  docker compose -f {result['compose_path']} --env-file "
                f"{result['env_path']} up -d[/red]"
            )
            raise typer.Exit(code=1)

        remappable = resolve_ports(config)
        resolved_any = False

        # remove_orphaned_containers() tears down the whole orphaned
        # project in one call - real testing against actual orphaned
        # containers surfaced that asking once per conflicting port
        # (own_orphan is often true for several ports at once, since
        # they're all the same leftover stack) meant every port after
        # the first just re-asked to clean up containers that were
        # already gone. One confirm covers every own-orphan port in
        # this pass.
        own_orphan_cleaned = False

        for port in port_check["conflicts"]:

            service_key = port_check["port_services"].get(port)

            if port_check["own_orphan"].get(port):

                if own_orphan_cleaned:
                    resolved_any = True
                    continue

                if typer.confirm(
                    f"Port {port} (and any other ports below from the same stack) is "
                    "held by your own orphaned containers from a previous stack. Stop "
                    "and remove them now?",
                    default=True
                ):

                    cleanup = remove_orphaned_containers(Path(result["compose_path"]).parent.name)

                    if cleanup["success"]:
                        resolved_any = True
                        own_orphan_cleaned = True
                    else:
                        console.print(f"[red]{cleanup['error']}[/red]")

                continue

            if service_key is None or service_key not in remappable:

                console.print(
                    f"[yellow]Port {port} can't be remapped automatically - free it "
                    "manually and retry.[/yellow]"
                )
                continue

            new_port_str = typer.prompt(
                f"Enter a new host port for {service_key} (currently {port}), or "
                "press Enter to leave it and resolve manually",
                default="",
                show_default=False
            )

            if not new_port_str:
                continue

            try:
                new_port = int(new_port_str)
            except ValueError:
                console.print("[red]Not a valid port number - skipped.[/red]")
                continue

            if new_port in remappable.values():
                console.print(
                    f"[red]Port {new_port} is already used by another service in "
                    "this stack - skipped.[/red]"
                )
                continue

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
    console.print(f"  MeTube: {'enabled' if 'metube' in config.enabled_optional else 'disabled'}")
    console.print(f"  Downtify: {'enabled' if 'downtify' in config.enabled_optional else 'disabled'}")
    console.print(f"  Netdata: {'enabled' if 'netdata' in config.enabled_optional else 'disabled'}")
    console.print(f"  Vaultwarden: {'enabled' if 'vaultwarden' in config.enabled_optional else 'disabled'}")
    if config.homepage_private:
        console.print("  Homepage: private (not publicly routed)")
    console.print(f"  Homepage: {'enabled' if 'homepage' in config.enabled_optional else 'disabled'}")
    console.print(f"  GPU passthrough: {config.gpu_vendor or 'disabled'}")

    if config.custom_services is not None:
        console.print(f"  Services: {', '.join(sorted(config.custom_services))}")

    if config.domain:
        console.print(f"  Domain: {config.domain}")

    if config.cloudflare_dns:
        console.print(f"  Cloudflare DNS (real Let's Encrypt certs): enabled ({config.cloudflare_email})")

    if config.auth_username:
        console.print(f"  Authelia admin username: {config.auth_username}")

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

        result = _resolve_port_conflicts(config, result, non_interactive)

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

            console.print("[green]Stack is up:[/green]")

            summary = render_stack_summary(config, detect_host_ip())

            if summary:
                console.print(summary)

            setup_order = render_setup_order(config, detect_host_ip())

            if setup_order:
                console.print(f"\n{setup_order}")

        else:
            console.print("[red]Failed to start the stack - check `docker compose logs`.[/red]")
            raise typer.Exit(code=1)

    else:

        console.print(
            "Run this when you're ready:\n"
            f"  docker compose -f {result['compose_path']} --env-file {result['env_path']} up -d\n\n"
            f"Once it's up, a suggested setup order for every service you enabled is here: "
            f"{WALKTHROUGH_URL}"
        )

    return result


if __name__ == "__main__":
    app()
