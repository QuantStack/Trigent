"""Statistics command for showing collection information."""

from collections import Counter, defaultdict
from datetime import datetime
from typing import Any

import requests

from trigent.database import (
    get_collection_name,
    get_headers,
    get_qdrant_config,
    get_qdrant_url,
)


def get_all_collections(config: dict[str, Any] | None = None) -> list[str]:
    """Get all collection names from Qdrant."""
    headers = get_headers()
    timeout = get_qdrant_config()["timeout"]
    
    try:
        response = requests.get(
            get_qdrant_url("collections"),
            headers=headers,
            timeout=timeout,
        )
        response.raise_for_status()
        
        collections = response.json()["result"]["collections"]
        # Extract just the collection names
        return [col["name"] for col in collections]
    except Exception as e:
        print(f"❌ Error fetching collections: {e}")
        return []


def get_collection_stats(collection_name: str, config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Get statistics for a single collection."""
    headers = get_headers()
    timeout = get_qdrant_config()["timeout"]
    
    stats = {
        "name": collection_name,
        "total_items": 0,
        "issues": 0,
        "prs": 0,
        "state_stats": {},
        "recommendation_histogram": Counter(),
        "last_updated": None,
    }
    
    try:
        # Get collection info
        info_response = requests.get(
            get_qdrant_url(f"collections/{collection_name}"),
            headers=headers,
            timeout=timeout,
        )
        
        if info_response.status_code == 404:
            return stats
            
        info_response.raise_for_status()
        collection_info = info_response.json()["result"]
        
        # Get point count from collection info
        stats["total_items"] = collection_info.get("points_count", 0)
        
        if stats["total_items"] == 0:
            return stats
        
        # Fetch all points to analyze (we need the payloads for detailed stats)
        # Using scroll to get all points
        all_points = []
        offset = None
        limit = 100
        
        while True:
            scroll_payload = {
                "limit": limit,
                "with_payload": True,
            }
            if offset:
                scroll_payload["offset"] = offset
                
            response = requests.post(
                get_qdrant_url(f"collections/{collection_name}/points/scroll"),
                json=scroll_payload,
                headers=headers,
                timeout=timeout,
            )
            response.raise_for_status()
            
            result = response.json()["result"]
            points = result.get("points", [])
            all_points.extend(points)
            
            # Check if there are more points
            next_offset = result.get("next_page_offset")
            if not next_offset or len(points) < limit:
                break
            offset = next_offset
        
        # Analyze points
        state_counts = defaultdict(int)
        latest_update = None
        
        for point in all_points:
            payload = point.get("payload", {})
            
            # Count issues vs PRs
            url = payload.get("url", "")
            if "/pull/" in url:
                stats["prs"] += 1
            else:
                stats["issues"] += 1
            
            # Count states
            state = payload.get("state", "unknown").lower()
            state_counts[state] += 1
            
            # Count recommendations
            recommendations = payload.get("recommendations", [])
            if isinstance(recommendations, list):
                stats["recommendation_histogram"][len(recommendations)] += 1
            
            # Track latest update
            updated_at = payload.get("updatedAt")
            if updated_at:
                try:
                    update_time = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
                    if latest_update is None or update_time > latest_update:
                        latest_update = update_time
                except:
                    pass
        
        # Calculate state percentages
        total = sum(state_counts.values())
        if total > 0:
            stats["state_stats"] = {
                state: {
                    "count": count,
                    "percentage": round(count / total * 100, 1)
                }
                for state, count in state_counts.items()
            }
        
        # Set last updated
        if latest_update:
            stats["last_updated"] = latest_update.isoformat()
        
        return stats
        
    except Exception as e:
        print(f"❌ Error getting stats for {collection_name}: {e}")
        return stats


def show_collection_statistics(repo: str | None = None, config: dict[str, Any] | None = None) -> None:
    """Show statistics for all collections or a specific repository."""
    print("📊 Fetching collection statistics...\n")
    
    # Get all collections
    all_collections = get_all_collections(config)
    
    if not all_collections:
        print("❌ No collections found in Qdrant")
        return
    
    # Filter by repo if specified
    if repo:
        # Get the collection name for this repo
        target_collection = get_collection_name(repo, config)
        if target_collection not in all_collections:
            print(f"❌ Collection for {repo} not found")
            print(f"   Available collections: {', '.join(all_collections)}")
            return
        collections_to_show = [target_collection]
    else:
        collections_to_show = all_collections
    
    # Get stats for each collection
    total_issues = 0
    total_prs = 0
    
    for collection in sorted(collections_to_show):
        stats = get_collection_stats(collection, config)
        
        print(f"📦 Collection: {collection}")
        print(f"   Total items: {stats['total_items']:,}")
        
        if stats['total_items'] > 0:
            print(f"   - Issues: {stats['issues']:,}")
            print(f"   - Pull Requests: {stats['prs']:,}")
            
            # State statistics
            if stats['state_stats']:
                print("   State distribution:")
                for state, info in sorted(stats['state_stats'].items()):
                    print(f"     - {state}: {info['count']:,} ({info['percentage']}%)")
            
            # Recommendation histogram
            if stats['recommendation_histogram']:
                print("   Recommendations:")
                for rec_count in sorted(stats['recommendation_histogram'].keys()):
                    count = stats['recommendation_histogram'][rec_count]
                    print(f"     - {rec_count} recommendations: {count:,} items")
            else:
                print("   Recommendations: No items have recommendations")
            
            # Last updated
            if stats['last_updated']:
                last_update = datetime.fromisoformat(stats['last_updated'])
                days_ago = (datetime.now(last_update.tzinfo) - last_update).days
                print(f"   Last updated: {last_update.strftime('%Y-%m-%d %H:%M')} ({days_ago} days ago)")
            else:
                print("   Last updated: Unknown")
                
            total_issues += stats['issues']
            total_prs += stats['prs']
        else:
            print("   (Empty collection)")
        
        print()  # Blank line between collections
    
    # Summary if showing multiple collections
    if len(collections_to_show) > 1:
        print("📈 Summary across all collections:")
        print(f"   Total collections: {len(collections_to_show)}")
        print(f"   Total issues: {total_issues:,}")
        print(f"   Total pull requests: {total_prs:,}")
        print(f"   Total items: {total_issues + total_prs:,}")
