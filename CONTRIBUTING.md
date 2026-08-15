# Contributing to Vulcan

Thank you for your interest in contributing!

Vulcan inspects a machine's real hardware and generates a Docker Compose media stack genuinely sized to what it can handle — deterministically, not by guessing or by asking an AI to decide.

Before proposing a feature, ask yourself:

> **Does this help Vulcan generate a more correct, better-fitted stack for the hardware it's given?**

If the answer is "yes," it likely aligns with the project's goals.

## Ways to Contribute

### Documentation

* Improve the README or `CLAUDE.md`
* Fix typos or unclear explanations
* Add real examples of generated stacks
* Document a service or tier decision that isn't explained well

### Code

* Fix bugs or add services (see [ROADMAP.md](ROADMAP.md) for what's shipped vs. open)
* Add hardware detection for a new distro or GPU vendor
* Improve tier scoring or resource limit formulas
* Add or refine port-conflict resolution

### Testing

* Run the test suite and report failures
* Test on a new distro and report results
* Help verify real-infrastructure checks (real Docker containers, real compose files)

### Security

* Report security issues via [SECURITY.md](SECURITY.md) — do not publicly disclose through GitHub Issues or Discussions

### Not a contribution

* Opinionated feature requests that don't help Vulcan generate a more correct stack for the given hardware
* Work that duplicates already-shipped functionality (see [ROADMAP.md](ROADMAP.md))

---

Thank you for helping make Vulcan better!
