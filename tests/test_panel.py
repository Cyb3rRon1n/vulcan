import io
import os
from unittest.mock import patch

from rich.console import Console

from installer.panel import RunPanel, _NoOpPanel, progress_panel
from installer.shell import get_stream_sink


def _recording_console() -> Console:

    return Console(file=io.StringIO(), width=80, legacy_windows=False, force_terminal=False)


def test_progress_panel_is_noop_without_env_var():

    with patch.dict(os.environ, {}, clear=True):

        panel = progress_panel("Test", ["Phase one"])

    assert isinstance(panel, _NoOpPanel)


def test_progress_panel_is_noop_when_not_a_terminal():

    with patch.dict(os.environ, {"VULCAN_PROGRESS": "1"}, clear=True), patch(
        "installer.panel.os.isatty", return_value=False
    ):

        panel = progress_panel("Test", ["Phase one"])

    assert isinstance(panel, _NoOpPanel)


def test_progress_panel_returns_runpanel_when_active():

    with patch.dict(os.environ, {"VULCAN_PROGRESS": "1"}, clear=True), patch(
        "installer.panel.os.isatty", return_value=True
    ):

        panel = progress_panel("Test", ["Phase one"])

    assert isinstance(panel, RunPanel)
    panel._live.stop()


def test_noop_panel_is_inert():

    with patch.dict(os.environ, {}, clear=True):

        panel = progress_panel("Test", ["Phase one"])

        with panel:
            panel.advance()
            panel.finish(True)

    assert get_stream_sink() is None


def test_runpanel_sets_and_clears_stream_sink():

    panel = RunPanel("Test", ["Phase one"])

    assert get_stream_sink() is None

    with panel:
        assert get_stream_sink() is not None
        assert get_stream_sink() == panel._on_line

    assert get_stream_sink() is None


def test_advance_moves_index_forward():

    panel = RunPanel("Test", ["Phase one", "Phase two"])

    assert panel._index == 0

    panel.advance()

    assert panel._index == 1

    panel.advance()

    assert panel._index == 2

    panel.advance()

    assert panel._index == 2

    panel._live.stop()


def test_finish_sets_done_state():

    panel = RunPanel("Test", ["Phase one"])
    panel.finish(True, summary="All good")

    assert panel._done is True
    assert panel._success is True
    assert panel._summary == "All good"

    panel._live.stop()


def test_running_render_shows_phase_and_percent():

    console = _recording_console()
    panel = RunPanel("Test", ["Phase one", "Phase two"], console=console)

    with panel:
        panel._live.update(panel._render())
        panel._live.stop()
        text = console.file.getvalue()

    assert "Test" in text
    assert "Phase one" in text
    assert "0/2 phases" in text
    assert "0%" in text

    panel._live.start()
    panel.advance()
    panel._live.update(panel._render())
    panel._live.stop()
    text = console.file.getvalue()

    assert "Phase two" in text
    assert "1/2 phases" in text
    assert "50%" in text


def test_finish_render_shows_done_and_summary():

    console = _recording_console()
    panel = RunPanel("Test", ["Phase one"], console=console)

    with panel:
        panel.advance()
        panel.finish(True, summary="Stack updated")

    text = console.file.getvalue()

    assert "Done." in text
    assert "Stack updated" in text


def test_finish_render_shows_failed():

    console = _recording_console()
    panel = RunPanel("Test", ["Phase one"], console=console)

    with panel:
        panel.finish(False)

    text = console.file.getvalue()

    assert "Failed." in text


def test_log_lines_appear_in_render():

    console = _recording_console()
    panel = RunPanel("Test", ["Phase one"], console=console)

    with panel:
        panel._on_line("pulling image")
        panel._on_line("container started")

    text = console.file.getvalue()

    assert "pulling image" in text
    assert "container started" in text


def test_log_keeps_last_twelve_lines():

    panel = RunPanel("Test", ["Phase one"])

    for i in range(20):
        panel._on_line(f"line {i}")

    assert len(panel._log) == 12
    assert panel._log[-1] == "line 19"
    assert "line 0" not in panel._log

    panel._live.stop()


def test_runpanel_note_is_a_no_op():

    console = _recording_console()
    panel = RunPanel("Test", ["Phase one"], console=console)

    with panel:
        panel.note("[bold]Review[/bold]")
        panel.note("  Tier: Heavy")

    text = console.file.getvalue()

    assert "Review" not in text
    assert "Tier: Heavy" not in text


def test_noop_panel_note_prints_via_its_stored_console():

    console = _recording_console()
    panel = _NoOpPanel(console)

    panel.note("[bold]Review[/bold]")

    text = console.file.getvalue()

    assert "Review" in text


def test_noop_panel_note_is_safe_with_no_console():

    panel = _NoOpPanel()

    panel.note("this must not raise")


def test_exit_with_raised_body_shows_failed():

    console = _recording_console()
    panel = RunPanel("Test", ["Phase one"], console=console)

    try:
        with panel:
            panel._on_line("some output")
            raise RuntimeError("boom")
    except RuntimeError:
        pass

    text = console.file.getvalue()

    assert "Failed." in text
