#!/usr/bin/env python3
"""Main CLI entry point for Trigent."""

import argparse

from trigent.clean import clean_repository
from trigent.config import get_config
from trigent.enrich import enrich_issues
from trigent.export.command import export_repository
from trigent.pull import fetch_issues
from trigent.serve.command import serve_repository
from trigent.stats import show_collection_statistics
from trigent.update import update_repository


def cmd_pull(args, config) -> None:
    """Execute pull command: Initial data pull (create mode) + enrichment."""
    # Apply prefix to config if provided
    if hasattr(args, "prefix") and args.prefix:
        config.setdefault("qdrant", {})["collection_prefix"] = args.prefix

    print(f"🚀 Setting up repository: {args.repo}")
    print("📥 Phase 1: Pulling initial issue data...")

    # Pull issues in create mode with smart defaults
    raw_issues = fetch_issues(
        repo=args.repo,
        include_closed=not getattr(args, "exclude_closed", False),
        limit=getattr(args, "limit", None),
        start_date=getattr(args, "start_date", "2025-01-01"),
        refetch=False,  # Always False for initial pull
        mode="create",  # Always create mode for pull command
        issue_numbers=None,
        item_types=getattr(args, "item_types", "both"),
        config=config,
    )

    print(f"📥 Retrieved {len(raw_issues)} issues")

    # Automatically enrich the pulled data
    print("\n📥 Phase 2: Enriching issue data...")
    enrich_issues(args.repo, config)

    print(f"\n✅ Repository {args.repo} is ready!")
    print("💡 Next steps:")
    print(f"   trigent serve {args.repo}  # Start MCP server")
    print(f"   trigent browse {args.repo} # Browse issues interactively")


def cmd_update(args, config) -> None:
    """Execute update command: Incremental update (update mode) + enrichment."""
    # Apply prefix to config if provided
    if hasattr(args, "prefix") and args.prefix:
        config.setdefault("qdrant", {})["collection_prefix"] = args.prefix

    update_repository(args.repo, config)


def cmd_serve(args, config) -> None:
    """Start MCP server for a repository."""
    # Apply prefix to config if provided
    if hasattr(args, "prefix") and args.prefix:
        config.setdefault("qdrant", {})["collection_prefix"] = args.prefix

    serve_repository(args.repo, args.host, args.port, config)


def cmd_export(args, config) -> None:
    """Export repository data to various formats."""
    # Apply prefix to config if provided
    if hasattr(args, "prefix") and args.prefix:
        config.setdefault("qdrant", {})["collection_prefix"] = args.prefix

    export_repository(
        args.repo,
        getattr(args, "output", None),
        getattr(args, "csv", False),
        getattr(args, "viz", False),
        getattr(args, "scale", 1.0),
        config,
    )


def cmd_clean(args, config) -> None:
    """Execute clean command to remove Qdrant collections."""
    # Apply prefix to config if provided
    if hasattr(args, "prefix") and args.prefix:
        config.setdefault("qdrant", {})["collection_prefix"] = args.prefix

    clean_repository(getattr(args, "repo", None), getattr(args, "yes", False), config)


def cmd_stats(args, config) -> None:
    """Show statistics for collections."""
    # Apply prefix to config if provided
    if hasattr(args, "prefix") and args.prefix:
        config.setdefault("qdrant", {})["collection_prefix"] = args.prefix

    show_collection_statistics(getattr(args, "repo", None), config)


def main() -> None:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Trigent - A Rich Issue MCP for GitHub Triaging at Scale"
    )

    # Global config flag available for all commands
    parser.add_argument(
        "--config",
        "-c",
        help="Path to config.toml file (default: ./config.toml, then project root/config.toml)",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Pull command (initial setup)
    pull_parser = subparsers.add_parser(
        "pull", help="Initial repository setup: pull issues + enrich data"
    )
    pull_parser.add_argument("repo", help="Repository to set up (e.g., 'owner/repo')")
    pull_parser.add_argument(
        "--exclude-closed",
        action="store_true",
        help="Exclude closed issues (default: include all)",
    )
    pull_parser.add_argument("--limit", "-l", type=int, help="Limit number of issues")
    pull_parser.add_argument(
        "--start-date",
        default="2025-01-01",
        help="Start date for fetching issues (YYYY-MM-DD)",
    )
    pull_parser.add_argument(
        "--item-types",
        choices=["issues", "prs", "both"],
        default="both",
        help="What to fetch: 'issues' only, 'prs' only, or 'both' (default: both)",
    )
    pull_parser.add_argument(
        "--prefix", help="Collection prefix for isolating data (useful for testing)"
    )
    pull_parser.set_defaults(func=cmd_pull)

    # Update command (incremental updates)
    update_parser = subparsers.add_parser(
        "update", help="Update existing repository: fetch new/updated issues + enrich"
    )
    update_parser.add_argument("repo", help="Repository to update (e.g., 'owner/repo')")
    update_parser.add_argument(
        "--prefix", help="Collection prefix for isolating data (useful for testing)"
    )
    update_parser.set_defaults(func=cmd_update)

    # Serve command (MCP server)
    serve_parser = subparsers.add_parser(
        "serve", help="Start MCP server for a repository"
    )
    serve_parser.add_argument("repo", help="Repository to serve (e.g., 'owner/repo')")
    serve_parser.add_argument("--host", default="localhost", help="Host to bind to")
    serve_parser.add_argument("--port", type=int, default=8000, help="Port to bind to")
    serve_parser.add_argument(
        "--prefix", help="Collection prefix for isolating data (useful for testing)"
    )
    serve_parser.set_defaults(func=cmd_serve)

    # Export command
    export_parser = subparsers.add_parser(
        "export", help="Export repository data to various formats"
    )
    export_parser.add_argument("repo", help="Repository to export (e.g., 'owner/repo')")
    export_parser.add_argument(
        "--csv", action="store_true", help="Export to CSV format"
    )
    export_parser.add_argument(
        "--viz", action="store_true", help="Export visualizations"
    )
    export_parser.add_argument("--output", "-o", help="Output file/directory path")
    export_parser.add_argument(
        "--scale", type=float, default=1.0, help="Scale factor for visualizations"
    )
    export_parser.add_argument(
        "--prefix", help="Collection prefix for isolating data (useful for testing)"
    )
    export_parser.set_defaults(func=cmd_export)

    # Clean command
    clean_parser = subparsers.add_parser("clean", help="Clean repository data")
    clean_parser.add_argument(
        "repo", nargs="?", help="Repository to clean (all repos if not specified)"
    )
    clean_parser.add_argument(
        "--yes", "-y", action="store_true", help="Skip confirmation"
    )
    clean_parser.add_argument(
        "--prefix", help="Collection prefix for isolating data (useful for testing)"
    )
    clean_parser.set_defaults(func=cmd_clean)

    # Stats command
    stats_parser = subparsers.add_parser(
        "stats", help="Show statistics for collections"
    )
    stats_parser.add_argument(
        "repo", nargs="?", help="Repository to show stats for (all if not specified)"
    )
    stats_parser.add_argument(
        "--prefix", help="Collection prefix for isolating data (useful for testing)"
    )
    stats_parser.set_defaults(func=cmd_stats)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    # Read config once and pass to all commands
    try:
        config = get_config(getattr(args, "config", None))
    except FileNotFoundError as e:
        print(f"❌ {e}")
        return
    except ValueError as e:
        print(f"❌ {e}")
        return

    args.func(args, config)


if __name__ == "__main__":
    main()
