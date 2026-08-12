# Security Policy

## Overview

Vulcan inspects your hardware, installs and operates Docker (including privileged operations - installing packages, managing the `docker` group, running `docker compose`), and generates real credentials (Authelia, Vaultwarden, CrowdSec, and VPN configuration) into files on your disk. Because it touches system-level operations and real secrets, security and responsible handling of that data are core considerations, not an afterthought.

We appreciate the security community and contributors who help identify and improve potential vulnerabilities.

---

# Supported Versions

Vulcan is early, single-maintainer, pre-1.0 software (currently `0.1.0-alpha`). There is no release-branch or LTS structure yet.

| Version            | Supported      |
| ------------------ | -------------- |
| `main` (latest)     | ✅              |
| Older commits       | ⚠️ Best effort |

This policy will be revisited once Vulcan has real tagged releases.

---

# Reporting a Security Vulnerability

Please do not publicly disclose security vulnerabilities through:

* GitHub Issues
* Discussions
* Pull Requests

before the maintainer has had an opportunity to investigate and address the issue. Open a private report instead (GitHub's "Report a vulnerability" under the Security tab, once enabled) or contact the maintainer directly.

---

## What to Include

When reporting a security concern, please include:

* Description of the vulnerability
* Potential impact
* Steps to reproduce
* Affected component (e.g. `installer/docker_setup.py`, a specific generated service block, `vulcan update-self`)
* Relevant logs or screenshots (if safe to share)
* Suggested mitigation (if known)

Please avoid including:

* Real credentials from a generated `stack/.env` (VPN keys, Authelia/CrowdSec secrets, Vaultwarden admin tokens)
* A full `stack/` or `backups/` archive - these can contain real service data and credentials
* Personal information (your real domain, real media library paths, etc. - redact before sharing)

---

# Response Process

After receiving a report:

1. Confirm receipt
2. Investigate and reproduce
3. Determine severity and impact
4. Develop a fix, verified against real infrastructure where practical (this project's own existing standard - see `CLAUDE.md`)
5. Coordinate disclosure timing with the reporter
6. Publish relevant information after remediation, credited to the reporter unless they prefer otherwise

---

# Security Principles

Vulcan's existing design principles (see `README.md`) are themselves security-relevant, not just architectural preferences:

## Deterministic, Not AI-Driven

Tier recommendations and every generated file come from fixed rules over detected hardware - no LLM in the decision path, no non-deterministic behavior to reason about from a security standpoint.

## Observe, Then Act

The installer shows what it detected and what it's about to generate before doing anything; nothing is silently overwritten. Every mutating action (Docker install, container start/stop, `vulcan update`/`restore`/`uninstall`/`update-self`) sits behind an explicit confirmation, with no bypass beyond an intentional `--yes`/`--non-interactive` flag pair.

## Never Invent a Secret

When something needs a credential Vulcan can't know (a VPN provider's private key, a Cloudflare API token), it generates an honest, clearly-labeled placeholder and says so. When Vulcan *can* generate a real secret itself (Authelia's `JWT_SECRET`, Vaultwarden's `ADMIN_TOKEN`, CrowdSec's bouncer key), it uses `secrets.token_hex(32)` - a real, unpredictable value, not a hardcoded or weak default - and preserves it across a regenerate rather than resetting it.

## Secrets Stay Out of Git

Generated `.env` files, the `stack/` directory, `backups/`, and `exports/` are all gitignored. `vulcan backup`'s own output warns explicitly that the archive contains `stack/.env` and may hold real credentials.

## Never a Force, Never a Reset

`vulcan update-self` is a plain `git pull --ff-only` against `origin/main` - if the local checkout has diverged, it refuses cleanly rather than discarding anything. The same discipline applies to every other mutating command in this codebase.

---

# Real, Named Risk Areas

Rather than a generic checklist, these are the parts of Vulcan that actually warrant a security-conscious look before relying on them:

* **Privileged Docker operations.** `installer/docker_setup.py` runs `sudo`-prefixed commands to install Docker and manage group membership. Review what a given release actually runs before trusting it on a machine you care about, the same way you would for any installer script.
* **`vulcan update-self`** performs a real `git pull` and `pip install -e .` against whatever `origin` your clone is configured with - it only ever operates on the remote you already trust (the one you cloned from), never fetches from an arbitrary source.
* **Generated secrets live in plaintext on disk** (`stack/.env`, `stack/config/*/secrets/`), by necessity - Docker Compose and the services themselves need to read them. File permissions on `stack/` follow your host's normal umask; there's no additional encryption-at-rest layer.
* **CrowdSec/Traefik/Authelia are themselves security features** - a bug in how Vulcan wires them together (a missing middleware label, a misconfigured forward-auth address) could leave a service *less* protected than intended without an obvious symptom. See `ROADMAP.md` for what's been verified against real infrastructure versus what's honestly still open (e.g. the CrowdSec plugin-catalog verification gap).

---

# Thank You

Security is a community effort. Every report, suggestion, and improvement helps make Vulcan safer for the homelabs relying on it.
