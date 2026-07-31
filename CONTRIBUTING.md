# Contributing to Vulcan

First off, thank you for your interest in contributing to Vulcan!

Whether you're fixing a typo, testing on a distro nobody's tried yet, adding a service, or helping shape the roadmap, your contributions are appreciated.

Vulcan exists so that spinning up a Jellyfin + *arr homelab doesn't mean either guessing at what your hardware can handle or copy-pasting a one-size-fits-all `docker-compose.yml` off a forum post. Every contribution that helps Vulcan understand a machine better, or generate a more correct stack for it, moves that forward.

---

# Our Mission

Vulcan inspects a machine's real hardware and generates a Docker Compose stack genuinely sized to what it can handle - deterministically, not by guessing or by asking an AI to decide.

Before proposing a feature, ask yourself:

> **Does this help Vulcan generate a more correct, better-fitted stack for the hardware it's given?**

If the answer is "yes," it likely aligns with the project's goals.

---

# Ways to Contribute

## Documentation

* Improve the README or `CLAUDE.md`
* Fix typos or unclear explanations
* Add real examples of generated stacks
* Document a service or tier decision that isn't explained well

---

## Development

* Add a new service to a tier (or to custom mode's picker)
* Improve tier scoring or resource-limit accuracy
* Fix bugs
* Improve the TUI
* Refactor for readability

See `CLAUDE.md`'s "Known, real, not-yet-addressed gaps" section for concrete, already-identified starting points - Recyclarr integration, real Traefik routing, a `vulcan restore` command, and aarch64 verification are all real, scoped gaps as of this writing, not hypothetical ideas.

---

## Testing

Vulcan's automatic Docker install currently targets Ubuntu, Debian, Raspbian, Fedora (via `get.docker.com`), and Arch (via `pacman`) - help test on distros beyond whichever one a given change was verified against. Real-hardware testing matters even more here: different GPU vendors (only AMD has been verified against real hardware in this project's history; Intel and NVIDIA are implemented per documented convention but unverified), aarch64/ARM (a stated design goal, never actually run), and different filesystem layouts all genuinely affect whether a generated stack works.

---

## Ideas

Suggestions are always welcome. Examples:

* Additional services or a different default set for a tier
* Better resource-limit tuning based on real-world usage
* CLI or TUI ergonomics improvements
* New post-install operations alongside `vulcan update`/`vulcan backup`

---

# Before You Start

Please check existing issues, pull requests, and `CLAUDE.md`'s architecture notes first - a lot of "why does it work this way" questions are already answered there, and checking avoids duplicate work.

---

# Development Philosophy

## Deterministic, Not AI-Driven

Tier recommendations come from fixed rules over detected CPU/RAM/disk/GPU - there is no LLM anywhere in the decision path, and there shouldn't be. A user should be able to read `tiers.py` top to bottom and know exactly why their machine got the recommendation it did.

---

## Observe, Then Act

Vulcan shows what it detected and what it's about to generate before doing anything. Nothing is silently overwritten - re-running against an existing stack makes the overwrite explicit rather than assuming it's fine.

---

## Re-Run Safe

Running Vulcan again against an existing stack should offer to upgrade or reconfigure, never clobber. Concretely: it must never reset a real secret (a Gluetun VPN key someone has already filled in) back to a placeholder just because the stack was regenerated.

---

## Never Invent a Secret

When something needs a credential Vulcan can't know (a VPN provider's private key), it generates an honest, clearly-labeled placeholder and says so - never a fake-looking value that could be mistaken for real.

---

## Verify Against Real Infrastructure

A mocked test suite passing is necessary but not sufficient. Changes touching Docker, the filesystem, or GPU passthrough should be checked against a real machine wherever practical - a real container started, a real generated compose file validated with `docker compose config`, a real archive inspected. This has been true of nearly every piece of this project so far, and it's expected to stay true.

---

# Development Setup

Clone the repository:

```bash
git clone https://github.com/<your-username>/vulcan.git
cd vulcan
```

Create a virtual environment and install in editable mode with the dev extras:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Run the test suite:

```bash
python -m pytest tests/ --cov=installer --cov-report=term-missing
```

There's no `requirements.txt` lockfile to keep in sync - `pyproject.toml` is the single source of truth for dependencies.

---

# Branch Naming

Please work on a feature branch rather than directly on `main`.

Examples:

```text
feature/sabnzbd-support

feature/recyclarr

fix/gpu-passthrough-intel

docs/update-tiers-table

refactor/generate-templates
```

---

# Commit Messages

Vulcan follows the Conventional Commits specification.

Examples:

```text
feat: add SABnzbd as an alternative downloader

fix: correct resource limit for lidarr under custom mode

docs: document the restore command

test: add real GPU passthrough verification for intel

refactor: extract shared service-selection logic

ci: add GitHub Actions workflow
```

Commit messages in this project tend to explain *why*, not just *what* - a decision's reasoning (and what was actually verified, if anything touched real infrastructure) belongs in the commit body. Future readers - including you, months later - benefit far more from "why" than from a restatement of the diff.

---

# Pull Requests

Good pull requests typically:

* Focus on one logical change
* Include a clear description of what changed and why
* Update `CLAUDE.md` if the change affects architecture, and the README if it affects user-facing behavior
* Include or update tests - both the mocked unit tests and, for anything touching real Docker/filesystem/GPU behavior, a description of what was verified against real infrastructure and how
* Keep changes as small and reviewable as practical

If your change affects generated output (a new service, a changed volume mount, a different resource limit), say so explicitly and show a real generated example if you can.

---

# Coding Standards

* Favor readability over cleverness.
* Keep functions focused; the engine layer (`detect.py`, `docker_setup.py`, `tiers.py`, `services.py`, `generate.py`, `post_install.py`) stays pure/near-pure and never prompts or confirms - that belongs in the CLI/TUI layer only. See `CLAUDE.md` for the full split.
* Match the file you're editing: heavy vertical spacing (blank line after `def ...():`, one argument per line in multi-arg calls) is the established convention here, not an accident.
* Don't add a docstring that just restates the function name - a comment or module docstring earns its place by explaining a non-obvious *why*.
* Remove unused code before submitting; don't leave commented-out blocks or dead branches "just in case."

---

# Documentation Standards

Documentation is a core feature of Vulcan, not an afterthought. Whenever appropriate, include:

* What the feature does and why it exists
* Any real hardware/OS/GPU requirements or limitations
* What's been verified against real infrastructure, and what hasn't (be honest about the difference - `CLAUDE.md` deliberately says "not hardware-verified" for the NVIDIA GPU passthrough path, for exactly this reason)
* Examples of real generated output where relevant

---

# Reporting Bugs

When reporting an issue, please include:

* Distro and architecture (`x86_64`/`aarch64`)
* GPU vendor, if relevant (`amd`/`intel`/`nvidia`/none)
* Vulcan version (`vulcan version`)
* Python version
* The tier and any custom service selection involved
* Steps to reproduce, expected behavior, actual behavior
* Relevant output - Vulcan's own console output is usually enough; Docker logs (`docker compose logs`) if the issue is with a running container rather than generation itself

---

# Suggesting Features

Feature requests should explain:

* The problem being solved
* Why it matters for a real homelab setup
* A proposed approach, if you have one
* Whether it changes what gets generated, how it's detected, or just how it's presented

Discussion is encouraged before implementation for anything that touches the tier model, the resource-limit matrix, or the volume layout - those are foundational enough that getting them right matters more than getting them fast.

---

# Code of Conduct

Be respectful, constructive, and welcoming to others. Vulcan is intended to be a friendly and inclusive project to contribute to.

---

# Recognition

Every contribution matters - whether it's fixing a typo, testing on a distro nobody's verified yet, or adding a whole new service. Thank you for contributing.

---

# Our Philosophy

Vulcan is guided by a few simple ideas:

**Size it to the real machine.**

No guessing, no LLM in the decision path - fixed rules over real detected hardware.

**Show your work.**

What was detected, what's about to be generated, and why - always visible before anything happens.

**Never assume it's fine to overwrite.**

A re-run should make things better, never lose what was already there.

If your contribution supports those ideas, you're helping move Vulcan in the right direction.

Welcome aboard!
