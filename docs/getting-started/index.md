# Getting Started

## Requirements

- Linux (Ubuntu, Debian, Raspbian, Fedora, and Arch all have an automatic Docker install path; other distros need Docker installed manually first)
- Python 3.11+
- Docker — installed and started automatically on supported distros if it isn't already there

## Quick Start

```bash
git clone https://github.com/Cyb3rRon1n/vulcan.git
cd vulcan
./install
```

`./install` bootstraps a local virtual environment on first run, then opens on a persistent **Main Menu** — Guided Setup, plus Update/Pull/Backup/Restore/Uninstall for a stack you've already generated. Every item is always listed, DockSTARTer-style; picking a maintenance command before a stack exists gives you the same real "no stack found" message the CLI itself would. Picking **Guided Setup** walks you through:

1. Detects your system
2. Gets Docker ready if it isn't already
3. Recommends a tier
4. Asks only the questions that matter (media path, optional VPN/SABnzbd/Recyclarr/Homepage, PUID/PGID/timezone)
5. Generates a ready-to-run stack, with the option to start it immediately

Before actually starting, Vulcan checks that every port your stack needs is genuinely free and refuses cleanly (naming the conflicting port) rather than letting Docker fail partway through. Once it's up, Vulcan prints the real URL for every service you enabled, so you're not left guessing ports.

## Non-interactive / scripted use

```bash
./install --tier medium --media-path /mnt/media --non-interactive --yes --start
```

`--non-interactive` requires both `--yes` and an explicit `--tier`/`--media-path` — nothing is inferred silently in scripted mode. `--start` is likewise opt-in on every path: generating a stack never launches it without being asked (interactively) or told to (`--start`).

Prefer the original plain-prompt flow over the guided `whiptail` menu (e.g. on a limited terminal, or `whiptail` isn't installed)? Add `--plain`.

!!! note "`--offline` is currently CLI-only"
    `--offline` skips the automatic Docker install attempt when there's no connection. The guided menu doesn't yet ask about it — a real, open gap, tracked in the [Roadmap](../roadmap.md). Use `--plain --offline` or `--non-interactive --offline` on a machine with no internet access.

## Next

- Not sure which tier or services you need? See [Tiers & Custom Mode](../tiers.md).
- Want domain routing, real TLS, a login wall, or intrusion protection? See [Optional Integrations](../integrations.md).
- Setting up on a machine with fresh, unformatted drives? See [Storage Planning](../storage.md).
