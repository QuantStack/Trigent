"""Update command implementation."""

from trigent.pull import fetch_issues


def update_repository(repo: str, config: dict) -> None:
    """Execute update command: Incremental update (update mode) + enrichment."""
    print(f"🔄 Updating repository: {repo}")
    print("📥 Phase 1: Fetching updated issues...")

    # Pull issues in update mode
    raw_issues = fetch_issues(
        repo=repo,
        include_closed=True,  # Always include all for updates
        limit=None,  # No limit for updates
        start_date=None,  # Let update mode determine date
        refetch=False,
        mode="update",  # Always update mode
        issue_numbers=None,
        item_types="both",
        config=config,
    )

    print(f"📥 Retrieved {len(raw_issues)} updated issues")

    if raw_issues:
        # Enrich the updated data
        print("\n📥 Phase 2: Enriching updated data...")
        from trigent.enrich import enrich_issues

        enrich_issues(repo, config)
    else:
        print("✅ No new issues to update")

    print(f"\n✅ Repository {repo} is up to date!")
