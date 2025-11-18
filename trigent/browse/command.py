"""Browse command implementation."""

from trigent.browse.tui import main as tui_main


def browse_repository(repo: str, config: dict) -> None:
    """Browse repository issues interactively."""
    tui_main(repo, config)
