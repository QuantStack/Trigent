"""Export command implementation."""

from trigent.export.board import export_board
from trigent.export.csv import export_csv
from trigent.export.visualize import visualize_issues


def export_repository(
    repo: str,
    output_path: str,
    export_csv_flag: bool,
    export_viz_flag: bool,
    export_board_flag: bool,
    project_override: str | None,
    scale: float,
    config: dict,
) -> None:
    """Export repository data to various formats."""
    print(f"📊 Exporting data for {repo}")

    # Default to CSV and viz if none specified (but not board)
    any_flag_specified = any([export_csv_flag, export_viz_flag, export_board_flag])
    do_csv = export_csv_flag or (not any_flag_specified)
    do_viz = export_viz_flag or (not any_flag_specified)
    do_board = export_board_flag

    if do_csv:
        print("📄 Exporting to CSV...")
        export_csv(repo, output_path, config)

    if do_viz:
        print("📊 Creating visualizations...")
        visualize_issues(repo, output_path, scale=scale, config=config)

    if do_board:
        print("📋 Exporting to GitHub Project Board...")
        export_board(repo, config, project_override)
