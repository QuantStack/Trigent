"""Clean command implementation."""

import requests

from trigent.database import (
    get_collection_name,
    get_headers,
    get_qdrant_config,
    get_qdrant_url,
)


def clean_repository(repo: str | None, skip_confirmation: bool, config: dict) -> None:
    """Execute clean command to remove Qdrant collections."""
    headers = get_headers()
    timeout = get_qdrant_config()["timeout"]

    if repo:
        # Clean specific repository
        collections_to_delete = [get_collection_name(repo, config)]
        print(f"🗑️  Collection to delete for {repo}:")
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
                col["name"]
                for col in all_collections
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

    # Ask for confirmation unless skip_confirmation flag is used
    if not skip_confirmation:
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

    if repo:
        print(f"✅ Cleaned Qdrant collection for {repo}")
    else:
        print(f"✅ Deleted {deleted_count} collections from Qdrant")
