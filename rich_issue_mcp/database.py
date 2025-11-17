#!/usr/bin/env python3
"""Database operations using Qdrant vector database for the Rich Issue MCP system."""

import json
import math
import time
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote

import numpy as np
import requests

from rich_issue_mcp.config import get_config

# Embedding dimension for Mistral embeddings
EMBEDDING_DIM = 1024


class QdrantError(Exception):
    """Base exception for Qdrant operations."""

    pass


class QdrantConnectionError(QdrantError):
    """Exception for Qdrant connection issues."""

    pass


class QdrantDocumentConflict(QdrantError):
    """Exception for Qdrant document conflicts."""

    pass


# Legacy aliases for backward compatibility
CouchDBError = QdrantError
CouchDBConnectionError = QdrantConnectionError
CouchDBDocumentConflict = QdrantDocumentConflict


def get_qdrant_config() -> dict[str, Any]:
    """
    Get Qdrant configuration from config.toml.

    Returns:
        Dictionary containing Qdrant configuration with defaults:
        - host: Qdrant server host (default: localhost)
        - port: Qdrant server port (default: 6333)
        - api_key: Optional API key for authentication
        - timeout: Request timeout in seconds (default: 30)
    """
    try:
        config = get_config()
        qdrant_config = config.get("qdrant", {})

        # Apply defaults
        defaults = {
            "host": "localhost",
            "port": 6333,
            "api_key": None,
            "timeout": 30,
        }

        # Merge with configured values
        result = defaults.copy()
        result.update(qdrant_config)

        return result

    except (FileNotFoundError, ValueError):
        # Return defaults if config not available
        return {
            "host": "localhost",
            "port": 6333,
            "api_key": None,
            "timeout": 30,
        }


def get_collection_name(repo: str, config: dict[str, Any] | None = None) -> str:
    """Get the Qdrant collection name for a repository."""
    if config is None:
        from rich_issue_mcp.config import get_config
        config = get_config()
    
    # Get prefix from config, default to empty string
    prefix = config.get("qdrant", {}).get("collection_prefix", "")
    
    # Clean repo name for Qdrant collection names (letters, numbers, underscores)
    clean_repo = repo.replace('/', '_').replace('-', '_').lower()
    
    # Return with or without prefix
    if prefix:
        return f"{prefix}_{clean_repo}"
    else:
        return clean_repo


def get_qdrant_url(endpoint: str = "") -> str:
    """Get the Qdrant API URL."""
    config = get_qdrant_config()
    base_url = f"http://{config['host']}:{config['port']}"
    return f"{base_url}/{endpoint}" if endpoint else base_url


def get_headers() -> dict[str, str]:
    """Get headers for Qdrant API requests."""
    headers = {"Content-Type": "application/json"}
    config = get_qdrant_config()
    if config.get("api_key"):
        headers["api-key"] = config["api_key"]
    return headers


def ensure_collection_exists(repo: str, config: dict[str, Any] | None = None) -> None:
    """Create Qdrant collection if it doesn't exist."""
    collection_name = get_collection_name(repo, config)
    headers = get_headers()
    timeout = get_qdrant_config()["timeout"]

    # Check if collection exists
    try:
        response = requests.get(
            get_qdrant_url(f"collections/{collection_name}"),
            headers=headers,
            timeout=timeout,
        )
        if response.status_code == 200:
            # Collection exists
            return
    except requests.exceptions.RequestException:
        pass

    # Create collection
    create_payload = {
        "vectors": {
            "size": EMBEDDING_DIM,
            "distance": "Cosine"  # Using cosine similarity for normalized embeddings
        }
    }

    try:
        response = requests.put(
            get_qdrant_url(f"collections/{collection_name}"),
            json=create_payload,
            headers=headers,
            timeout=timeout,
        )
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        raise QdrantConnectionError(f"Failed to create collection {collection_name}: {e}")


def convert_numpy_types(obj: Any) -> Any:
    """Recursively convert NumPy types to Python native types for JSON serialization."""
    import numpy as np

    if isinstance(obj, np.integer):
        return int(obj)
    elif isinstance(obj, np.floating):
        value = float(obj)
        # Convert NaN and infinity to None for JSON compatibility
        if math.isnan(value) or math.isinf(value):
            return None
        return value
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    elif isinstance(obj, (float, int)):
        # Handle Python native float/int that might be NaN or infinity
        if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
            return None
        return obj
    elif isinstance(obj, dict):
        return {key: convert_numpy_types(value) for key, value in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return [convert_numpy_types(item) for item in obj]
    else:
        return obj


def issue_to_point(issue: dict[str, Any], point_id: int) -> dict[str, Any]:
    """Convert an issue to a Qdrant point."""
    # Extract embedding
    embedding = issue.get("embedding")
    if not embedding or not isinstance(embedding, list):
        raise ValueError(f"Issue {issue.get('number')} has no valid embedding")

    if len(embedding) != EMBEDDING_DIM:
        raise ValueError(
            f"Issue {issue.get('number')} has embedding of dimension {len(embedding)}, "
            f"expected {EMBEDDING_DIM}"
        )

    # Prepare payload (all fields except embedding)
    payload = convert_numpy_types(issue.copy())
    payload.pop("embedding", None)  # Remove embedding from payload
    
    # Add special fields for filtering
    if "labels" in payload and isinstance(payload["labels"], list):
        # Store label names for filtering
        payload["label_names"] = [
            label["name"] for label in payload["labels"] 
            if isinstance(label, dict) and "name" in label
        ]
    
    if "author" in payload and isinstance(payload["author"], dict):
        payload["author_login"] = payload["author"].get("login")
    
    if "assignees" in payload and isinstance(payload["assignees"], list):
        payload["assignee_logins"] = [
            assignee.get("login") for assignee in payload["assignees"] 
            if isinstance(assignee, dict)
        ]

    return {
        "id": point_id,
        "vector": embedding,
        "payload": payload,
    }


def save_issues(repo: str, issues: list[dict[str, Any]], config: dict[str, Any] | None = None) -> None:
    """Save issues to Qdrant collection, replacing all existing data."""
    # Validate repo parameter
    if (
        ".db" in repo
        or ".json" in repo
        or ".gz" in repo
        or "issues-" in repo
        or "enriched-" in repo
    ):
        raise ValueError(
            f"Invalid repo name '{repo}': should be 'owner/repo', not a file path"
        )

    collection_name = get_collection_name(repo, config)
    headers = get_headers()
    timeout = get_qdrant_config()["timeout"]

    # Delete and recreate collection
    try:
        # Delete collection if it exists
        response = requests.delete(
            get_qdrant_url(f"collections/{collection_name}"),
            headers=headers,
            timeout=timeout,
        )
        # Ignore 404 (collection doesn't exist)
        if response.status_code not in [200, 404]:
            response.raise_for_status()

        # Wait a bit for deletion to complete
        time.sleep(0.5)

    except requests.exceptions.RequestException as e:
        raise QdrantConnectionError(f"Failed to delete collection {collection_name}: {e}")

    # Create collection
    ensure_collection_exists(repo)

    if not issues:
        return  # Nothing to save

    # Convert issues to points
    points = []
    for idx, issue in enumerate(issues):
        try:
            point = issue_to_point(issue, idx)
            points.append(point)
        except ValueError as e:
            print(f"Warning: Skipping issue: {e}")
            continue

    if not points:
        return

    # Upload points in batches
    batch_size = 100
    for i in range(0, len(points), batch_size):
        batch = points[i : i + batch_size]
        upload_payload = {"points": batch}

        try:
            response = requests.put(
                get_qdrant_url(f"collections/{collection_name}/points"),
                json=upload_payload,
                headers=headers,
                timeout=timeout * 2,  # Double timeout for uploads
            )
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            raise QdrantConnectionError(
                f"Failed to upload batch {i // batch_size + 1}: {e}"
            )


def load_issues(repo: str, config: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Load all issues from Qdrant collection."""
    # Validate repo parameter
    if (
        ".db" in repo
        or ".json" in repo
        or ".gz" in repo
        or "issues-" in repo
        or "enriched-" in repo
    ):
        raise ValueError(
            f"Invalid repo name '{repo}': should be 'owner/repo', not a file path"
        )

    collection_name = get_collection_name(repo, config)
    headers = get_headers()
    timeout = get_qdrant_config()["timeout"]

    try:
        # First, get collection info to know total points
        info_response = requests.get(
            get_qdrant_url(f"collections/{collection_name}"),
            headers=headers,
            timeout=timeout,
        )
        if info_response.status_code == 404:
            # Collection doesn't exist
            return []
        info_response.raise_for_status()
        
        collection_info = info_response.json()["result"]
        total_points = collection_info.get("points_count", 0)
        
        if total_points == 0:
            return []

        # Scroll through all points
        issues = []
        offset = None
        limit = 100
        
        while True:
            scroll_payload = {
                "limit": limit,
                "with_payload": True,
                "with_vector": True,
            }
            if offset is not None:
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
            
            if not points:
                break
                
            for point in points:
                # Reconstruct issue from point
                issue = point["payload"].copy()
                issue["embedding"] = point["vector"]
                issues.append(issue)
            
            # Check if there's a next page
            next_offset = result.get("next_page_offset")
            if next_offset is None:
                break
            offset = next_offset

        return issues

    except requests.exceptions.RequestException as e:
        if hasattr(e, "response") and e.response and e.response.status_code == 404:
            # Collection doesn't exist yet
            return []
        raise QdrantConnectionError(f"Failed to load issues from {repo}: {e}")


def upsert_issues(repo: str, issues: list[dict[str, Any]], config: dict[str, Any] | None = None) -> None:
    """Upsert issues to Qdrant collection (update existing, insert new)."""
    # Validate repo parameter
    if (
        ".db" in repo
        or ".json" in repo
        or ".gz" in repo
        or "issues-" in repo
        or "enriched-" in repo
    ):
        raise ValueError(
            f"Invalid repo name '{repo}': should be 'owner/repo', not a file path"
        )

    if not issues:
        return

    collection_name = get_collection_name(repo, config)
    headers = get_headers()
    timeout = get_qdrant_config()["timeout"]

    # Ensure collection exists
    ensure_collection_exists(repo, config)

    # Get existing issues to determine point IDs
    existing_issues = load_issues(repo, config)
    issue_number_to_id = {}
    max_id = -1
    
    for idx, issue in enumerate(existing_issues):
        issue_num = issue.get("number")
        if issue_num:
            issue_number_to_id[issue_num] = idx
            max_id = max(max_id, idx)

    # Process each issue
    points_to_upsert = []
    
    for issue in issues:
        issue_num = issue.get("number")
        if not issue_num:
            print(f"Warning: Issue without number, skipping")
            continue

        # Determine point ID
        if issue_num in issue_number_to_id:
            point_id = issue_number_to_id[issue_num]
            action = "update"
        else:
            max_id += 1
            point_id = max_id
            action = "create"

        try:
            point = issue_to_point(issue, point_id)
            points_to_upsert.append(point)
            
            # Log action
            comments_count = len(issue.get("comments", []))
            cross_refs_count = len(issue.get("cross_references", []))
            updated_at = issue.get("updatedAt", "unknown")
            print(
                f"  ✓ Issue #{issue_num} (updated: {updated_at}): "
                f"{comments_count} comments, {cross_refs_count} cross-refs - {action} in database"
            )
        except ValueError as e:
            print(f"Warning: Skipping issue #{issue_num}: {e}")
            continue

    if not points_to_upsert:
        return

    # Upsert points in batches
    batch_size = 100
    for i in range(0, len(points_to_upsert), batch_size):
        batch = points_to_upsert[i : i + batch_size]
        upsert_payload = {"points": batch}

        try:
            response = requests.put(
                get_qdrant_url(f"collections/{collection_name}/points"),
                json=upsert_payload,
                headers=headers,
                timeout=timeout * 2,  # Double timeout for uploads
            )
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            raise QdrantConnectionError(
                f"Failed to upsert batch {i // batch_size + 1}: {e}"
            )


def delete_issue(repo: str, issue_number: int, config: dict[str, Any] | None = None) -> bool:
    """Delete a specific issue from the collection by issue number."""
    collection_name = get_collection_name(repo, config)
    headers = get_headers()
    timeout = get_qdrant_config()["timeout"]

    try:
        # Find the point with this issue number
        search_payload = {
            "filter": {
                "must": [
                    {
                        "key": "number",
                        "match": {"value": issue_number}
                    }
                ]
            },
            "limit": 1,
            "with_payload": False,
        }

        response = requests.post(
            get_qdrant_url(f"collections/{collection_name}/points/scroll"),
            json=search_payload,
            headers=headers,
            timeout=timeout,
        )
        
        if response.status_code == 404:
            return False  # Collection doesn't exist
        
        response.raise_for_status()
        points = response.json()["result"]["points"]
        
        if not points:
            return False  # Issue not found
        
        point_id = points[0]["id"]

        # Delete the point
        delete_payload = {"points": [point_id]}
        delete_response = requests.post(
            get_qdrant_url(f"collections/{collection_name}/points/delete"),
            json=delete_payload,
            headers=headers,
            timeout=timeout,
        )
        delete_response.raise_for_status()
        
        return True

    except requests.exceptions.RequestException as e:
        raise QdrantConnectionError(f"Failed to delete issue {issue_number}: {e}")


def delete_issues(repo: str, issue_numbers: list[int], config: dict[str, Any] | None = None) -> tuple[int, int]:
    """Delete multiple issues from the collection.

    Returns:
        Tuple of (successful_deletions, failed_deletions)
    """
    successful = 0
    failed = 0

    for issue_number in issue_numbers:
        try:
            if delete_issue(repo, issue_number):
                successful += 1
                print(f"  ✓ Deleted issue #{issue_number}")
            else:
                failed += 1
                print(f"  ✗ Issue #{issue_number} not found")
        except Exception as e:
            failed += 1
            print(f"  ✗ Failed to delete issue #{issue_number}: {e}")

    return successful, failed


def get_latest_updated_date_from_view(repo: str, config: dict[str, Any] | None = None) -> str | None:
    """Get the most recent updatedAt timestamp from the collection."""
    collection_name = get_collection_name(repo, config)
    headers = get_headers()
    timeout = get_qdrant_config()["timeout"]

    try:
        # Get all issues and find the latest updatedAt
        issues = load_issues(repo, config)
        if not issues:
            return None
        
        latest_date = None
        for issue in issues:
            updated_at = issue.get("updatedAt")
            if updated_at and (latest_date is None or updated_at > latest_date):
                latest_date = updated_at
        
        return latest_date

    except QdrantConnectionError:
        return None


def clear_all_recommendations(repo: str, config: dict[str, Any] | None = None) -> int:
    """Clear all recommendations from all issues in the repository.

    Returns the number of issues that had recommendations cleared.
    """
    print(f"🧹 Clearing all recommendations from {repo}...")

    # Load all issues
    try:
        issues = load_issues(repo)
    except QdrantConnectionError as e:
        if "404" in str(e):
            print("📁 No collection found")
            return 0
        raise

    if not issues:
        print("📁 No issues found in collection")
        return 0

    # Count and update issues with recommendations
    cleared_count = 0
    updated_issues = []

    for issue in issues:
        if issue.get("recommendations") and len(issue["recommendations"]) > 0:
            # Clear recommendations
            issue["recommendations"] = []
            updated_issues.append(issue)
            cleared_count += 1

    if updated_issues:
        # Upsert the updated issues
        upsert_issues(repo, updated_issues)

    print(f"✅ Cleared recommendations from {cleared_count} issues")
    return cleared_count


# Keep these functions for backward compatibility during migration
def load_design_documents(repo: str, config: dict[str, Any] | None = None) -> None:
    """No-op for Qdrant - no design documents needed."""
    pass


def ensure_indexes(repo: str, config: dict[str, Any] | None = None) -> None:
    """No-op for Qdrant - indexes are handled automatically."""
    pass


def documents_are_equal(doc1: dict[str, Any], doc2: dict[str, Any]) -> bool:
    """Compare two documents for equality, ignoring internal fields."""
    # Create copies without internal fields and pulled_date (which always changes)
    clean_doc1 = {
        k: v for k, v in doc1.items() if k != "pulled_date"
    }
    clean_doc2 = {
        k: v for k, v in doc2.items() if k != "pulled_date"
    }

    return clean_doc1 == clean_doc2


def get_database_name(repo: str, config: dict[str, Any] | None = None) -> str:
    """Get the database/collection name for a repository (backward compatibility)."""
    return get_collection_name(repo, config)


# Additional legacy alias
get_couchdb_config = get_qdrant_config