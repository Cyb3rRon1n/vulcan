"""
Travel tier: the pieces that live on the box itself, outside the Docker
stack. Pure checks and plan builders; nothing here prompts or prints.
"""

import ipaddress
import re

_HOSTNAME = re.compile(r"[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?")


def valid_hostname(name: str) -> bool:
    """One DNS label (RFC 1123): what Avahi can publish as <name>.local."""

    return bool(_HOSTNAME.fullmatch(name))


def valid_ip(value: str) -> bool:

    try:
        ipaddress.ip_address(value)
    except ValueError:
        return False

    return True
