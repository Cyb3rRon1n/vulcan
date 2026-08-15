# Security Policy

Vulcan inspects your hardware, installs and operates Docker (including privileged operations - installing packages, managing the `docker` group, running `docker compose`), and generates real credentials (Authelia, Vaultwarden, CrowdSec, and VPN configuration) into files on your disk. Because it touches system-level operations and real secrets, security and responsible handling of that data are core considerations, not an afterthought.

## Supported Versions

Vulcan is early, single-maintainer, pre-1.0 software (currently `0.1.0-alpha`). There is no release-branch or LTS structure yet.

| Version | Supported |
| ------- | --------: |
| `main` (latest) | ✅ |

## Reporting a Security Vulnerability

Please do not publicly disclose security vulnerabilities through:
* GitHub Issues
* Discussions
* Pull Requests

Instead, report them responsibly — see the section below.

## Reporting

Security vulnerabilities will be investigated and, if confirmed, a fix will be released as quickly as possible. While a fix is in development, a temporary mitigation may be documented.

All security-related code changes will be tracked in the `main` branch, and a release will be cut once the fix is verified.
