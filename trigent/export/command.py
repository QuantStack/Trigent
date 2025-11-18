"""Export command implementation."""

from trigent.export.csv import export_csv
from trigent.export.visualize import visualize_issues


def export_repository(
    repo: str,
    output_path: str,
    export_csv_flag: bool,
    export_viz_flag: bool,
    scale: float,
    config: dict,
) -> None:
    """Export repository data to various formats."""
    print(f"📊 Exporting data for {repo}")

    # Default to both formats if none specified
    do_csv = export_csv_flag or not any([export_csv_flag, export_viz_flag])
    do_viz = export_viz_flag or not any([export_csv_flag, export_viz_flag])

    if do_csv:
        print("📄 Exporting to CSV...")
        export_csv(repo, output_path, config)

    if do_viz:
        print("📊 Creating visualizations...")
        visualize_issues(repo, output_path, scale=scale, config=config)
