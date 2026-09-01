"""
RunPanel - the live progress panel the CLI wraps its long-running
operations in (Guided Setup, storage apply, update, restore, ...).

Activated by the VULCAN_PROGRESS=1 env var, which installer/menu.sh's
confirm_and_run() exports for every menu action. When that var is unset
(a bare `vulcan update` on a terminal, a piped run, the test suite) the
panel is inert - a no-op context manager with the same method surface -
so CLI output stays byte-identical to before this module existed.

The panel's log pane is fed by the shell stream sink (installer/shell.py):
setting the sink on enter means every run_privileged()/run_docker_command()
call made while the panel is open tees its real output line-by-line into
the scrolling log instead of the terminal, with no per-command wiring.
The progress bar only ever advances on real step completion - phases are
advanced by the CLI itself at genuine boundaries (detection done, Docker
ready, stack written, containers started), never on a timer or a guess.

Live is created with transient=False (the default) so the final
Done./Failed. frame stays on screen after the command exits, right where
menu.sh's `read -rp "Press Enter..."` expects to find it.
"""

import os
from collections import deque

from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.progress_bar import ProgressBar
from rich.text import Text

from installer.shell import clear_stream_sink, set_stream_sink

_LOG_LINES = 12


class RunPanel:
    """
    A Rich Live panel: title header, a phase-based progress bar, a
    scrolling log pane (last _LOG_LINES lines), and a final Done./Failed.
    state with an optional summary line. Context manager - entering sets
    the shell stream sink (all subprocess output for the duration lands
    in the log pane), leaving clears it and stops Live.
    """

    def __init__(self, title: str, phases: list[str], console: Console | None = None):

        self._title = title
        self._phases = list(phases)
        self._console = console or Console()
        self._log = deque(maxlen=_LOG_LINES)
        self._index = 0
        self._done = False
        self._success: bool | None = None
        self._summary: str | None = None

        self._live = Live(
            self._render(),
            console=self._console,
            refresh_per_second=8,
            transient=False
        )

    def __enter__(self) -> "RunPanel":

        set_stream_sink(self._on_line)
        self._live.start()
        return self

    def __exit__(self, exc_type, exc, tb):

        # If the body raised without an explicit finish(), show the
        # failure state rather than leaving a stale "running" frame on
        # screen - every raise path (restore failing, guided setup
        # aborting, _generate_and_maybe_start's start failure) lands
        # here automatically.
        if exc_type is not None and not self._done:
            self.finish(False)

        clear_stream_sink()
        self._live.stop()

        # Leave the terminal in a known-good state for whatever draws
        # next (the whiptail menu, over SSH). Live.stop() with
        # transient=False keeps the last frame but can leave the cursor
        # hidden or a paint unflushed.
        self._console.show_cursor(True)
        try:
            self._console.file.flush()
        except (OSError, ValueError):
            pass

        return False

    def _on_line(self, line: str) -> None:

        self._log.append(line.rstrip())
        self._live.update(self._render())

    def advance(self, label: str | None = None) -> None:
        """
        Advance to the next phase. Called by the CLI at real step
        boundaries - never automatically, so the bar only moves on
        genuine completion. The label (used by on_phase hooks like
        update_stack's) is ignored - phases advance in the order the
        panel was given them, which the call sites already match.
        """

        self._index = min(self._index + 1, len(self._phases))
        self._live.update(self._render())

    def note(self, text: str) -> None:
        """
        Detail that's only worth showing when there's no live panel to
        clutter - detected hardware, "Docker is ready.", a Review
        block, etc. A no-op here on purpose: that detail is real and
        genuinely useful (see this module's own docstring on why the
        panel exists at all), but whiptail's Guided Setup already has
        its own screens for confirming these same choices, and this
        panel's log pane is reserved for real subprocess output, not a
        second copy of console prose scrolling above it. The call sites
        that use this route the same detail into "Setup Complete"
        instead (installer/cli.py's install-summary command) - moved,
        not deleted.
        """

    def finish(self, success: bool, summary: str | None = None) -> None:
        """Set the final Done./Failed. state and (optionally) a summary line."""

        self._done = True
        self._success = success
        self._summary = summary
        self._live.update(self._render())

    def _render(self) -> Panel:

        if self._done:
            body = self._done_render()
        else:
            body = self._running_render()

        return Panel(
            body,
            title=f" {self._title} ",
            border_style="cyan",
            expand=False
        )

    def _running_render(self) -> Group:

        current = self._phases[self._index] if self._index < len(self._phases) else self._phases[-1]

        total = len(self._phases)
        percent = int(100 * self._index / total) if total else 100

        return Group(
            Text(f"{current}   {self._index}/{total} phases", style="bold cyan"),
            ProgressBar(total=total, completed=self._index, width=48),
            Text(f"  {percent}%", style="cyan"),
            Text("─" * 50, style="dim"),
            *[Text(line, style="dim") for line in self._log],
        )

    def _done_render(self) -> Group:

        status = (
            Text("Done.", style="bold green")
            if self._success
            else Text("Failed.", style="bold red")
        )

        summary = [Text(f"  {self._summary}", style="green")] if self._summary else []

        return Group(
            status,
            *summary,
            Text("─" * 50, style="dim"),
            *[Text(line, style="dim") for line in self._log],
        )


class _NoOpPanel:
    """
    Inert stand-in when VULCAN_PROGRESS is unset - byte-identical output.
    note() is the one method that isn't a no-op: with no real panel to
    suppress detail into, it prints immediately via the stored console -
    exactly what a bare console.print() call would have done, so a
    call site can use panel.note(...) unconditionally without caring
    whether a real panel is active.
    """

    def __init__(self, console: Console | None = None):
        self._console = console

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def advance(self, label: str | None = None) -> None:
        pass

    def note(self, text: str) -> None:
        if self._console is not None:
            self._console.print(text)

    def finish(self, success: bool, summary: str | None = None) -> None:
        pass


def progress_panel(title: str, phases: list[str], console: Console | None = None) -> RunPanel | _NoOpPanel:
    """
    Returns a real RunPanel when VULCAN_PROGRESS=1 (and stdout is a
    terminal - a piped/progress-captured run stays plain), otherwise the
    no-op panel. Call sites are identical either way. The panel must use
    the CLI's own console instance (the same one its console.print calls
    go through), not a fresh one, so interleaved messages render above
    the live region rather than fighting it.
    """

    if os.environ.get("VULCAN_PROGRESS") == "1" and os.isatty(1):
        return RunPanel(title, phases, console=console)

    return _NoOpPanel(console)
