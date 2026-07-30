"""
The Textual TUI: a second interface onto the same detect.py/
docker_setup.py/tiers.py/generate.py engine cli.py already wraps -
same manager functions, driven by screens instead of prompts.
"""

from installer.tui.app import VulcanApp


def run_tui() -> None:

    VulcanApp().run()
