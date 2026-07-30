"""
Jinja2 rendering: takes the chosen tier + configuration answers and
renders templates/docker-compose.yml.j2 and templates/env.j2 into a
real stack/docker-compose.yml and stack/.env for the user's machine.
Pure-ish: write_stack() does real file I/O but never prompts or
confirms - that's the CLI layer's job (Phase 1 slice 5), the same
split Atlas keeps between config/writer.py and the atlas init command.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from installer.services import resource_limits_for
from installer.tiers import TierDefinition


TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"


@dataclass
class GenerationConfig:

    tier: TierDefinition
    media_path: str
    puid: int
    pgid: int
    timezone: str
    enabled_optional: set[str] = field(default_factory=set)


def default_puid_pgid() -> tuple[int, int]:

    return os.getuid(), os.getgid()


def default_timezone() -> str:

    try:
        return Path("/etc/timezone").read_text().strip()
    except OSError:
        pass

    try:
        target = Path("/etc/localtime").resolve()
        return str(target).split("zoneinfo/", 1)[1]
    except (OSError, IndexError):
        return "UTC"


def enabled_service_keys(config: GenerationConfig) -> set[str]:

    return {
        service.key for service in config.tier.services
        if not service.optional or service.key in config.enabled_optional
    }


def _jinja_env() -> Environment:

    return Environment(
        loader=FileSystemLoader(TEMPLATES_DIR),
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
        autoescape=False
    )


def render_compose(config: GenerationConfig) -> str:

    template = _jinja_env().get_template("docker-compose.yml.j2")

    return template.render(
        enabled=enabled_service_keys(config),
        limits=resource_limits_for(config.tier.name)
    )


def render_env(config: GenerationConfig) -> str:

    template = _jinja_env().get_template("env.j2")

    return template.render(
        media_path=config.media_path,
        puid=config.puid,
        pgid=config.pgid,
        timezone=config.timezone,
        gluetun_enabled="gluetun" in config.enabled_optional
    )


def write_stack(config: GenerationConfig, output_dir: Path = Path("stack")) -> dict:

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    compose_path = output_dir / "docker-compose.yml"
    env_path = output_dir / ".env"

    compose_path.write_text(render_compose(config))
    env_path.write_text(render_env(config))

    for key in enabled_service_keys(config):
        (output_dir / "config" / key).mkdir(parents=True, exist_ok=True)

    media_path = Path(config.media_path)
    (media_path / "downloads").mkdir(parents=True, exist_ok=True)
    (media_path / "media" / "movies").mkdir(parents=True, exist_ok=True)
    (media_path / "media" / "tv").mkdir(parents=True, exist_ok=True)

    warnings = []

    if "gluetun" in config.enabled_optional:

        warnings.append(
            "Gluetun requires real VPN provider credentials in stack/.env "
            "before it will connect - see the TODO comments there."
        )

    return {
        "success": True,
        "compose_path": str(compose_path),
        "env_path": str(env_path),
        "warnings": warnings
    }
