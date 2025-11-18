#!/usr/bin/env python3
"""Main CLI entry point for Trigent."""

import argparse

from trigent.config import get_config
from trigent.database import load_issues
from trigent.enrich import (
    add_k4_distances,
    add_quartile_columns,
    print_stats,
)
from trigent.mcp_server import run_mcp_server
from trigent.pull import fetch_issues
from trigent.validate import validate_database
from trigent.visualize import visualize_issues


def _enrich_issues(repo: str, config) -> None:
    """Internal function to enrich issues with embeddings and metrics."""
    print(f"🧠 Enriching issues for {repo}...")
    issues = load_issues(repo, config)
    
    if not issues:
        print("⚠️  No issues found to enrich")
        return
    
    print(f"📥 Retrieved {len(issues)} issues")

    print("🔧 Computing quartile assignments...")
    enriched = add_quartile_columns(issues)

    print("🔧 Computing k-4 nearest neighbor distances...")
    enriched = add_k4_distances(enriched)

    # Apply post-processing using individual upserts to preserve existing data
    print("💾 Saving enriched issues...")
    from trigent.database import upsert_issues

    for i, issue in enumerate(enriched):
        if (i + 1) % 100 == 0:
            print(f"  Saved {i + 1}/{len(enriched)} enriched issues")
        upsert_issues(repo, [issue], config)

    print("✅ Issue enrichment complete")
    print_stats(enriched)


def cmd_pull(args, config) -> None:
    """Execute pull command: Initial data pull (create mode) + enrichment."""
    # Apply prefix to config if provided
    if hasattr(args, 'prefix') and args.prefix:
        config.setdefault('qdrant', {})['collection_prefix'] = args.prefix
    
    print(f"🚀 Setting up repository: {args.repo}")
    print("📥 Phase 1: Pulling initial issue data...")

    # Pull issues in create mode with smart defaults
    raw_issues = fetch_issues(
        repo=args.repo,
        include_closed=not getattr(args, 'exclude_closed', False),
        limit=getattr(args, 'limit', None),
        start_date=getattr(args, 'start_date', '2025-01-01'),
        refetch=False,  # Always False for initial pull
        mode='create',  # Always create mode for pull command
        issue_numbers=None,
        item_types=getattr(args, 'item_types', 'both'),
        config=config,
    )
    
    print(f"📥 Retrieved {len(raw_issues)} issues")
    
    # Automatically enrich the pulled data
    print("\n📥 Phase 2: Enriching issue data...")
    _enrich_issues(args.repo, config)
    
    print(f"\n✅ Repository {args.repo} is ready!")
    print("💡 Next steps:")
    print(f"   trigent serve {args.repo}  # Start MCP server")
    print(f"   trigent browse {args.repo} # Browse issues interactively")


def cmd_update(args, config) -> None:
    """Execute update command: Incremental update (update mode) + enrichment."""
    # Apply prefix to config if provided
    if hasattr(args, 'prefix') and args.prefix:
        config.setdefault('qdrant', {})['collection_prefix'] = args.prefix
    
    print(f"🔄 Updating repository: {args.repo}")
    print("📥 Phase 1: Fetching updated issues...")

    # Pull issues in update mode
    raw_issues = fetch_issues(
        repo=args.repo,
        include_closed=True,  # Always include all for updates
        limit=None,           # No limit for updates
        start_date=None,      # Let update mode determine date
        refetch=False,
        mode='update',        # Always update mode
        issue_numbers=None,
        item_types='both',
        config=config,
    )
    
    print(f"📥 Retrieved {len(raw_issues)} updated issues")
    
    if raw_issues:
        # Enrich the updated data
        print("\n📥 Phase 2: Enriching updated data...")
        _enrich_issues(args.repo, config)
    else:
        print("✅ No new issues to update")
    
    print(f"\n✅ Repository {args.repo} is up to date!")


def cmd_serve(args, config) -> None:
    """Start MCP server for a repository."""
    # Apply prefix to config if provided
    if hasattr(args, 'prefix') and args.prefix:
        config.setdefault('qdrant', {})['collection_prefix'] = args.prefix
    
    print(f"🚀 Starting MCP server for {args.repo}")
    run_mcp_server(host=args.host, port=args.port, repo=args.repo, config=config)


def cmd_browse(args, config) -> None:
    """Browse repository issues interactively."""
    # Apply prefix to config if provided
    if hasattr(args, 'prefix') and args.prefix:
        config.setdefault('qdrant', {})['collection_prefix'] = args.prefix
    
    from trigent.tui import main as tui_main
    tui_main(args.repo, config)


def _export_csv(repo: str, output_path: str, config) -> None:
    """Export issues with recommendations to CSV."""
    import csv
    from pathlib import Path
    
    issues = load_issues(repo, config)
    
    # Filter issues that have at least one recommendation
    issues_with_recs = [
        issue for issue in issues 
        if issue.get("recommendations") and len(issue.get("recommendations", [])) > 0
    ]
    
    if not issues_with_recs:
        print("❌ No issues with recommendations found")
        return
    
    print(f"📝 Found {len(issues_with_recs)} issues with recommendations")
    
    # Prepare CSV data with flattened first recommendation
    csv_rows = []
    for issue in issues_with_recs:
        first_rec = issue["recommendations"][0]
        
        # Create flattened row with key fields
        row = {
            "number": issue.get("number"),
            "title": issue.get("title"),
            "url": issue.get("url"),
            "state": issue.get("state"),
            "author": issue.get("author", {}).get("login", ""),
            "labels": ", ".join([label.get("name", "") for label in issue.get("labels", [])]),
            "comments_count": issue.get("comments_count", 0),
            "recommendation": first_rec.get("recommendation"),
            "confidence": first_rec.get("confidence"),
            "rationale": first_rec.get("rationale"),
        }
        csv_rows.append(row)
    
    # Write CSV file
    output_file = Path(output_path) if output_path else Path(f"{repo.replace('/', '_')}_recommendations.csv")
    output_file.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_file, "w", newline="", encoding="utf-8") as csvfile:
        if csv_rows:
            writer = csv.DictWriter(csvfile, fieldnames=list(csv_rows[0].keys()))
            writer.writeheader()
            writer.writerows(csv_rows)
    
    print(f"✅ Exported {len(csv_rows)} issues to {output_file}")


def cmd_export(args, config) -> None:
    """Export repository data to various formats."""
    # Apply prefix to config if provided
    if hasattr(args, 'prefix') and args.prefix:
        config.setdefault('qdrant', {})['collection_prefix'] = args.prefix
    
    print(f"📊 Exporting data for {args.repo}")
    
    # Default to both formats if none specified
    export_csv = getattr(args, 'csv', False) or not any([getattr(args, 'csv', False), getattr(args, 'viz', False)])
    export_viz = getattr(args, 'viz', False) or not any([getattr(args, 'csv', False), getattr(args, 'viz', False)])
    
    if export_csv:
        print("📄 Exporting to CSV...")
        _export_csv(args.repo, getattr(args, 'output', None), config)
    
    if export_viz:
        print("📊 Creating visualizations...")
        output_path = getattr(args, 'output', None)
        visualize_issues(args.repo, output_path, scale=getattr(args, 'scale', 1.0), config=config)


def cmd_clean(args, config) -> None:
    """Execute clean command to remove Qdrant collections."""
    # Apply prefix to config if provided
    if hasattr(args, 'prefix') and args.prefix:
        config.setdefault('qdrant', {})['collection_prefix'] = args.prefix
    
    from trigent.database import (
        get_collection_name,
        get_headers,
        get_qdrant_config,
        get_qdrant_url,
    )
    import requests

    headers = get_headers()
    timeout = get_qdrant_config()["timeout"]

    if hasattr(args, "repo") and args.repo:
        # Clean specific repository
        collections_to_delete = [get_collection_name(args.repo, config)]
        print(f"🗑️  Collection to delete for {args.repo}:")
    else:
        # List all collections and filter for issue collections
        try:
            response = requests.get(
                get_qdrant_url("collections"),
                headers=headers,
                timeout=timeout,
            )
            response.raise_for_status()
            all_collections = response.json()["result"]["collections"]
            
            # Filter for issue collections (starting with "issues_")
            collections_to_delete = [
                col["name"] for col in all_collections 
                if col["name"].startswith("issues_")
            ]
            
            if not collections_to_delete:
                print("📁 No issue collections found in Qdrant")
                return
                
            print("🗑️  Collections to be deleted:")
        except requests.exceptions.RequestException as e:
            print(f"❌ Failed to list Qdrant collections: {e}")
            return

    # Show collections that would be deleted with point counts
    for collection_name in sorted(collections_to_delete):
        try:
            response = requests.get(
                get_qdrant_url(f"collections/{collection_name}"),
                headers=headers,
                timeout=timeout,
            )
            if response.status_code == 200:
                info = response.json()["result"]
                points_count = info.get("points_count", 0)
                print(f"  - {collection_name} ({points_count} issues)")
            else:
                print(f"  - {collection_name} (unknown size)")
        except requests.exceptions.RequestException:
            print(f"  - {collection_name} (unknown size)")

    # Ask for confirmation unless --yes flag is used
    if not args.yes:
        response = input("\n❓ Delete these collections? (y/N): ").strip().lower()
        if response not in ("y", "yes"):
            print("❌ Clean operation cancelled")
            return

    # Delete the collections
    deleted_count = 0
    for collection_name in collections_to_delete:
        try:
            response = requests.delete(
                get_qdrant_url(f"collections/{collection_name}"),
                headers=headers,
                timeout=timeout,
            )
            response.raise_for_status()
            deleted_count += 1
            print(f"🗑️  Deleted collection {collection_name}")
        except requests.exceptions.RequestException as e:
            print(f"❌ Failed to delete collection {collection_name}: {e}")

    if hasattr(args, "repo") and args.repo:
        print(f"✅ Cleaned Qdrant collection for {args.repo}")
    else:
        print(f"✅ Deleted {deleted_count} collections from Qdrant")


def cmd_validate(args, config) -> None:
    """Validate repository data integrity."""
    # Apply prefix to config if provided
    if hasattr(args, 'prefix') and args.prefix:
        config.setdefault('qdrant', {})['collection_prefix'] = args.prefix
    
    print(f"🔍 Validating repository: {args.repo}")
    success = validate_database(
        args.repo, delete_invalid=getattr(args, "delete_invalid", False), config=config
    )
    if not success:
        exit(1)


def main() -> None:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Trigent - A Rich Issue MCP for GitHub Triaging at Scale"
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Pull command (initial setup)
    pull_parser = subparsers.add_parser("pull", help="Initial repository setup: pull issues + enrich data")
    pull_parser.add_argument("repo", help="Repository to set up (e.g., 'owner/repo')")
    pull_parser.add_argument(
        "--exclude-closed",
        action="store_true", 
        help="Exclude closed issues (default: include all)"
    )
    pull_parser.add_argument("--limit", "-l", type=int, help="Limit number of issues")
    pull_parser.add_argument(
        "--start-date", 
        default="2025-01-01",
        help="Start date for fetching issues (YYYY-MM-DD)"
    )
    pull_parser.add_argument(
        "--item-types",
        choices=["issues", "prs", "both"],
        default="both",
        help="What to fetch: 'issues' only, 'prs' only, or 'both' (default: both)"
    )
    pull_parser.add_argument(
        "--prefix",
        help="Collection prefix for isolating data (useful for testing)"
    )
    pull_parser.set_defaults(func=cmd_pull)

    # Update command (incremental updates)
    update_parser = subparsers.add_parser("update", help="Update existing repository: fetch new/updated issues + enrich")
    update_parser.add_argument("repo", help="Repository to update (e.g., 'owner/repo')")
    update_parser.add_argument("--prefix", help="Collection prefix for isolating data (useful for testing)")
    update_parser.set_defaults(func=cmd_update)

    # Serve command (MCP server)
    serve_parser = subparsers.add_parser("serve", help="Start MCP server for a repository")
    serve_parser.add_argument("repo", help="Repository to serve (e.g., 'owner/repo')")
    serve_parser.add_argument("--host", default="localhost", help="Host to bind to")
    serve_parser.add_argument("--port", type=int, default=8000, help="Port to bind to")
    serve_parser.add_argument("--prefix", help="Collection prefix for isolating data (useful for testing)")
    serve_parser.set_defaults(func=cmd_serve)

    # Browse command (TUI)
    browse_parser = subparsers.add_parser("browse", help="Browse repository issues interactively")
    browse_parser.add_argument("repo", help="Repository to browse (e.g., 'owner/repo')")
    browse_parser.add_argument("--prefix", help="Collection prefix for isolating data (useful for testing)")
    browse_parser.set_defaults(func=cmd_browse)

    # Export command
    export_parser = subparsers.add_parser("export", help="Export repository data to various formats")
    export_parser.add_argument("repo", help="Repository to export (e.g., 'owner/repo')")
    export_parser.add_argument("--csv", action="store_true", help="Export to CSV format")
    export_parser.add_argument("--viz", action="store_true", help="Export visualizations")
    export_parser.add_argument("--output", "-o", help="Output file/directory path")
    export_parser.add_argument("--scale", type=float, default=1.0, help="Scale factor for visualizations")
    export_parser.add_argument("--prefix", help="Collection prefix for isolating data (useful for testing)")
    export_parser.set_defaults(func=cmd_export)

    # Clean command
    clean_parser = subparsers.add_parser("clean", help="Clean repository data")
    clean_parser.add_argument("repo", nargs="?", help="Repository to clean (all repos if not specified)")
    clean_parser.add_argument("--yes", "-y", action="store_true", help="Skip confirmation")
    clean_parser.add_argument("--prefix", help="Collection prefix for isolating data (useful for testing)")
    clean_parser.set_defaults(func=cmd_clean)

    # Validate command
    validate_parser = subparsers.add_parser("validate", help="Validate repository data integrity")
    validate_parser.add_argument("repo", help="Repository to validate (e.g., 'owner/repo')")
    validate_parser.add_argument("--delete-invalid", action="store_true", help="Delete invalid entries")
    validate_parser.add_argument("--prefix", help="Collection prefix for isolating data (useful for testing)")
    validate_parser.set_defaults(func=cmd_validate)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    # Read config once and pass to all commands
    try:
        config = get_config()
    except FileNotFoundError as e:
        print(f"❌ {e}")
        return
    except ValueError as e:
        print(f"❌ {e}")
        return

    args.func(args, config)


if __name__ == "__main__":
    main()
