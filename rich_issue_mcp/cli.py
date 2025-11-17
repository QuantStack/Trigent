#!/usr/bin/env python3
"""Main CLI entry point for Rich Issue MCP."""

import argparse

from rich_issue_mcp.config import get_config
from rich_issue_mcp.database import clear_all_recommendations, load_issues
from rich_issue_mcp.enrich import (
    add_k4_distances,
    add_quartile_columns,
    print_stats,
)
from rich_issue_mcp.mcp_server import run_mcp_server
from rich_issue_mcp.pull import fetch_issues
from rich_issue_mcp.validate import validate_database
from rich_issue_mcp.visualize import visualize_issues


def cmd_pull(args, config) -> None:
    """Execute pull command."""
    print(f"🔍 Fetching issues from {args.repo}...")

    raw_issues = fetch_issues(
        repo=args.repo,
        include_closed=not args.exclude_closed,  # Invert the flag
        limit=args.limit,
        start_date=getattr(args, "start_date", "2025-01-01"),
        refetch=getattr(args, "refetch", False),
        mode=getattr(args, "mode", "update"),
        issue_numbers=getattr(args, "issue_numbers", None),
        item_types=getattr(args, "item_types", "both"),
        config=config,
    )
    print(f"📥 Retrieved {len(raw_issues)} issues")
    print("✅ Issues saved to database during fetch process")


def cmd_enrich(args, config) -> None:
    """Execute enrich command for post-processing (quartiles and k4 distances)."""
    print(f"🔍 Loading issues from {args.repo}...")
    issues = load_issues(args.repo, config)
    print(f"📥 Retrieved {len(issues)} issues")

    print("🔧 Computing quartile assignments...")
    enriched = add_quartile_columns(issues)

    print("🔧 Computing k-4 nearest neighbor distances...")
    enriched = add_k4_distances(enriched)

    # Apply post-processing using individual upserts to preserve existing data
    print("💾 Saving post-processed issues using individual upserts...")
    from rich_issue_mcp.database import upsert_issues

    for i, issue in enumerate(enriched):
        if (i + 1) % 100 == 0:
            print(f"  Saved {i + 1}/{len(enriched)} post-processed issues")
        upsert_issues(args.repo, [issue])

    print("✅ Post-processed issue database saved using individual upserts")
    print_stats(enriched)


def cmd_mcp(args, config) -> None:
    """Execute MCP server."""
    run_mcp_server(host=args.host, port=args.port, repo=args.repo, config=config)


def cmd_visualize(args, config) -> None:
    """Execute visualize command."""
    print(f"📊 Visualizing repository: {args.repo}")

    visualize_issues(args.repo, args.output, scale=args.scale, config=config)


def cmd_clean(args, config) -> None:
    """Execute clean command to remove Qdrant collections."""
    from rich_issue_mcp.database import (
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
        collections_to_delete = [get_collection_name(args.repo)]
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
    """Execute validate command to check database integrity."""
    success = validate_database(
        args.repo, delete_invalid=getattr(args, "delete_invalid", False), config=config
    )
    if not success:
        exit(1)


def cmd_tui(args, config) -> None:
    """Execute TUI command to browse database interactively."""
    from rich_issue_mcp.tui import run_tui

    try:
        run_tui(args.repo)
    except KeyboardInterrupt:
        print("\nTUI exited by user")
    except Exception as e:
        print(f"Error running TUI: {e}")


def cmd_update_views(args, config) -> None:
    """Execute update-views command (no-op for Qdrant)."""
    print(
        f"ℹ️  Qdrant handles indexing automatically - "
        f"no manual view updates needed for {args.repo}"
    )
    print("✅ Collection indexes are managed automatically by Qdrant")


def cmd_clear_recommendations(args, config) -> None:
    """Execute clear-recommendations command."""
    # Ask for confirmation unless --yes flag is used
    if not args.yes:
        response = (
            input(f"\n❓ Clear all recommendations from {args.repo}? (y/N): ")
            .strip()
            .lower()
        )
        if response not in ("y", "yes"):
            print("❌ Clear recommendations operation cancelled")
            return

    try:
        cleared_count = clear_all_recommendations(args.repo, config)
        if cleared_count > 0:
            print(
                f"✅ Successfully cleared recommendations from {cleared_count} issues"
            )
        else:
            print("ℹ️  No issues had recommendations to clear")
    except Exception as e:
        print(f"❌ Failed to clear recommendations: {e}")


def cmd_export_csv(args, config) -> None:
    """Export issues with recommendations to CSV."""
    import csv
    from pathlib import Path
    
    print(f"📊 Loading issues from {args.repo}...")
    issues = load_issues(args.repo, config)
    
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
        # Get the first (most recent) recommendation
        first_rec = issue["recommendations"][0]
        
        # Create flattened row
        row = {
            # Issue fields
            "number": issue.get("number"),
            "title": issue.get("title"),
            "url": issue.get("url"),
            "state": issue.get("state"),
            "created_at": issue.get("createdAt"),
            "updated_at": issue.get("updatedAt"),
            "labels": ", ".join([label.get("name", "") for label in issue.get("labels", [])]),
            "author": issue.get("author", {}).get("login", ""),
            "issue_summary": issue.get("summary"),
            
            # Metrics
            "comments_count": issue.get("comments_count", 0),
            "issue_total_emojis": issue.get("issue_total_emojis", 0),
            "conversation_total_emojis": issue.get("conversation_total_emojis", 0),
            "age_days": issue.get("age_days", 0),
            "activity_score": issue.get("activity_score", 0),
            
            # First recommendation fields
            "recommendation": first_rec.get("recommendation"),
            "confidence": first_rec.get("confidence"),
            "rec_summary": first_rec.get("summary"),
            "rationale": first_rec.get("rationale"),
            "report": first_rec.get("report"),
            
            # Analysis fields
            "severity": first_rec.get("analysis", {}).get("severity"),
            "frequency": first_rec.get("analysis", {}).get("frequency"),
            "prevalence": first_rec.get("analysis", {}).get("prevalence"),
            "solution_complexity": first_rec.get("analysis", {}).get("solution_complexity"),
            "solution_risk": first_rec.get("analysis", {}).get("solution_risk"),
            
            # Context fields
            "affected_packages": ", ".join(first_rec.get("context", {}).get("affected_packages", [])),
            "affected_paths": ", ".join(first_rec.get("context", {}).get("affected_paths", [])),
            "affected_components": ", ".join(first_rec.get("context", {}).get("affected_components", [])),
            "merge_with": ", ".join([str(n) for n in first_rec.get("context", {}).get("merge_with", [])]),
            "relevant_issues_count": len(first_rec.get("context", {}).get("relevant_issues", [])),
            
            # Meta fields
            "reviewer": first_rec.get("meta", {}).get("reviewer"),
            "review_timestamp": first_rec.get("meta", {}).get("timestamp"),
            "model_version": first_rec.get("meta", {}).get("model_version"),
            "total_recommendations": len(issue.get("recommendations", []))
        }
        
        # Calculate priority score
        level_map = {"low": 1, "medium": 2, "high": 3}
        analysis = first_rec.get("analysis", {})
        
        severity = level_map.get(analysis.get("severity", "").lower(), 1)
        frequency = level_map.get(analysis.get("frequency", "").lower(), 1)
        prevalence = level_map.get(analysis.get("prevalence", "").lower(), 1)
        complexity = level_map.get(analysis.get("solution_complexity", "").lower(), 1)
        risk = level_map.get(analysis.get("solution_risk", "").lower(), 1)
        
        # Calculate priority score: (severity × frequency × prevalence) / (complexity × risk)
        # Avoid division by zero
        if complexity * risk > 0:
            priority_score = (severity * frequency * prevalence) / (complexity * risk)
        else:
            priority_score = 0
        
        row["priority_score"] = round(priority_score, 2)
        
        csv_rows.append(row)
    
    # Determine output path
    output_path = Path(args.output if args.output else f"{args.repo.replace('/', '_')}_recommendations.csv")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Write CSV file
    if csv_rows:
        fieldnames = list(csv_rows[0].keys())
        
        with open(output_path, "w", newline="", encoding="utf-8") as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(csv_rows)
        
        print(f"✅ Exported {len(csv_rows)} issues to {output_path}")
    else:
        print("❌ No data to export")


def main() -> None:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Rich Issue MCP - Enhanced repo information for AI triaging"
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Pull command
    pull_parser = subparsers.add_parser("pull", help="Pull raw issues from GitHub")
    pull_parser.add_argument("repo", help="Repository to analyze (e.g., 'owner/repo')")
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
        "--refetch", action="store_true", help="Refetch all issues from start date"
    )
    pull_parser.add_argument(
        "--mode",
        choices=["create", "update"],
        default="update",
        help=(
            "Pull mode: 'create' sorts by created date and avoids re-pulling existing issues, "
            "'update' pulls from last updated date in database (default: update)"
        ),
    )
    pull_parser.add_argument(
        "--issue-numbers",
        nargs="+",
        type=int,
        help="Specific issue numbers to refetch (always refetches even if they exist)",
    )
    pull_parser.add_argument(
        "--item-types",
        choices=["issues", "prs", "both"],
        default="both",
        help="What to fetch: 'issues' only, 'prs' only, or 'both' (default: both)",
    )
    pull_parser.set_defaults(func=cmd_pull)

    # Enrich command
    enrich_parser = subparsers.add_parser(
        "enrich", help="Enrich raw issues with embeddings and metrics"
    )
    enrich_parser.add_argument(
        "repo", help="GitHub repository (e.g., 'jupyterlab/jupyterlab')"
    )
    enrich_parser.add_argument("--model", default="mistral-embed", help="Mistral model")
    enrich_parser.add_argument(
        "--skip-summaries",
        action="store_true",
        help="Skip LLM summarization to save time",
    )
    enrich_parser.set_defaults(func=cmd_enrich)

    # MCP command
    mcp_parser = subparsers.add_parser("mcp", help="Start MCP server")
    mcp_parser.add_argument("repo", help="Repository to serve (e.g., 'owner/repo')")
    mcp_parser.add_argument("--host", default="localhost", help="Host to bind to")
    mcp_parser.add_argument("--port", type=int, default=8000, help="Port to bind to")
    mcp_parser.set_defaults(func=cmd_mcp)

    # Visualize command
    visualize_parser = subparsers.add_parser(
        "visualize",
        help="Create T-SNE visualization and GraphML network from enriched issues in TinyDB",
    )
    visualize_parser.add_argument(
        "repo", help="Repository to visualize (e.g., 'owner/repo')"
    )
    visualize_parser.add_argument(
        "--output",
        help="Output file path (.graphml) or directory (default: owner_repo_issues.graphml in current directory)",
    )
    visualize_parser.add_argument(
        "--scale",
        type=float,
        default=1.0,
        help="Scale factor for embedding coordinates (default: 1.0)",
    )
    visualize_parser.set_defaults(func=cmd_visualize)

    # Clean command
    clean_parser = subparsers.add_parser("clean", help="Clean downloaded data files")
    clean_parser.add_argument(
        "repo", nargs="?", help="Repository to clean (if not specified, cleans all)"
    )
    clean_parser.add_argument(
        "--yes", "-y", action="store_true", help="Skip confirmation prompt"
    )
    clean_parser.set_defaults(func=cmd_clean)

    # Validate command
    validate_parser = subparsers.add_parser(
        "validate", help="Validate database integrity and completeness"
    )
    validate_parser.add_argument(
        "repo", help="Repository to validate (e.g., 'owner/repo')"
    )
    validate_parser.add_argument(
        "--delete-invalid",
        action="store_true",
        help="Delete invalid entries from database after confirmation",
    )
    validate_parser.set_defaults(func=cmd_validate)

    # TUI command
    tui_parser = subparsers.add_parser(
        "tui", help="Browse database interactively with Terminal UI"
    )
    tui_parser.add_argument("repo", help="Repository to browse (e.g., 'owner/repo')")
    tui_parser.set_defaults(func=cmd_tui)

    # Update views command
    views_parser = subparsers.add_parser(
        "update-views", help="Update database views and indexes (no-op for Qdrant)"
    )
    views_parser.add_argument(
        "repo", help="Repository to update views for (e.g., 'owner/repo')"
    )
    views_parser.set_defaults(func=cmd_update_views)

    # Clear recommendations command
    clear_recs_parser = subparsers.add_parser(
        "clear-recommendations",
        help="Clear all recommendations from all issues in the repository",
    )
    clear_recs_parser.add_argument(
        "repo", help="Repository to clear recommendations from (e.g., 'owner/repo')"
    )
    clear_recs_parser.add_argument(
        "--yes", "-y", action="store_true", help="Skip confirmation prompt"
    )
    clear_recs_parser.set_defaults(func=cmd_clear_recommendations)

    # Export CSV command
    export_csv_parser = subparsers.add_parser(
        "export-csv",
        help="Export issues with recommendations to CSV (flattens first recommendation)",
    )
    export_csv_parser.add_argument(
        "repo", help="Repository to export (e.g., 'owner/repo')"
    )
    export_csv_parser.add_argument(
        "--output", "-o",
        help="Output CSV file path (default: repo_recommendations.csv)",
    )
    export_csv_parser.set_defaults(func=cmd_export_csv)

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
