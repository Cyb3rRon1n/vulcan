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



### Local Development

1. Install dependencies: `pip install -e ".[dev]"`
2. Run tests: `pytest tests/ --deselect tests/test_cli.py::test_detect_shell_output_is_eval_able_key_value --deselect tests/test_cli.py::test_non_interactive_homepage_private_defaults_true_on_fresh_install --deselect tests/test_cli.py::test_interactive_full_run_with_prompts`
3. Lint: `ruff check .`
4. Install: `sudo ./install` (runs guided setup)
5. For quick CLI tests: `python -m installer --help` or `python -m installer --version`

### Pull Request Process

1. Fork the repository and create a new branch from `main`
2. Make your changes following the project's code style (deliberate vertical spacing, pyflakes-only linting)
3. Add or update tests as appropriate - all 600 tests should pass when 3 env-state tests are deselected
4. Commit with a clear description of the change
5. Push to your fork and open a Pull Request against `main`
6. Address any review feedback - maintainers may request changes before merging

### Development Notes

* The codebase uses `typer` for CLI, `rich` for console output
* Linting is pyflakes-only (`select = ["F"]`) - real bugs, not style debates
* Test environment state persistence between runs can cause 3 tests to fail in isolation - deselect them when running the full suite
* Generated stack output (docker-compose.yml, .env, etc.) is gitignored - produced on the end user's machine

### Not a contribution

* Opinionated feature requests that don't help Vulcan generate a more correct stack for the given hardware
* Work that duplicates already-shipped functionality (see [ROADMAP.md](ROADMAP.md))

---

Thank you for helping make Vulcan better!
