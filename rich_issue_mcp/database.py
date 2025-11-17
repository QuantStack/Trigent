#!/usr/bin/env python3
"""Database operations using CouchDB for the Rich Issue MCP system."""

import json
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests
from requests.auth import HTTPBasicAuth


class CouchDBError(Exception):
    """Base exception for CouchDB operations."""

    pass


class CouchDBConnectionError(CouchDBError):
    """Exception for CouchDB connection issues."""

    pass


class CouchDBDocumentConflict(CouchDBError):
    """Exception for CouchDB document conflicts (409)."""

    pass


from rich_issue_mcp.config import get_couchdb_config


def get_database_name(repo: str) -> str:
    """Get the CouchDB database name for a repository."""
    # CouchDB database names must be lowercase and contain only a-z, 0-9, _, $, (, ), +, -, /
    return f"issues-{repo.replace('/', '-').lower()}"


def get_couchdb_url(repo: str) -> str:
    """Get the CouchDB database URL for a repository."""
    config = get_couchdb_config()
    db_name = get_database_name(repo)
    return f"{config['server_url']}/{db_name}"


def get_auth() -> HTTPBasicAuth | None:
    """Get CouchDB authentication if configured."""
    config = get_couchdb_config()
    if config.get("username") and config.get("password"):
        return HTTPBasicAuth(config["username"], config["password"])
    return None


def ensure_database_exists(repo: str) -> None:
    """Create CouchDB database if it doesn't exist."""
    url = get_couchdb_url(repo)
    auth = get_auth()

    try:
        response = requests.put(url, auth=auth, timeout=30)
        if response.status_code == 201:
            # Database created successfully
            pass
        elif response.status_code == 412:
            # Database already exists
            pass
        else:
            response.raise_for_status()
    except requests.exceptions.RequestException as e:
        raise CouchDBConnectionError(f"Failed to create/access database {repo}: {e}")


def load_design_documents(repo: str) -> None:
    """Load and update design documents from view files."""
    views_dir = Path(__file__).parent / "views"
    design_doc_path = views_dir / "design_doc.json"

    if not design_doc_path.exists():
        print("Warning: No design document template found")
        return

    # Load the design document template
    with open(design_doc_path) as f:
        design_doc = json.load(f)

    # Replace placeholders with actual view functions
    for view_name, view_def in design_doc["views"].items():
        map_function_file = views_dir / f"{view_name}.js"
        if map_function_file.exists():
            with open(map_function_file) as f:
                map_function = f.read().strip()
            view_def["map"] = map_function
        else:
            print(f"Warning: View file {map_function_file} not found")

    # Update the design document in CouchDB
    auth = get_auth()
    base_url = get_couchdb_url(repo)
    design_url = f"{base_url}/_design/queries"

    try:
        # Check if design doc exists to get current revision
        response = requests.get(design_url, auth=auth, timeout=30)
        if response.status_code == 200:
            existing_doc = response.json()
            design_doc["_rev"] = existing_doc["_rev"]

        # Update the design document
        response = requests.put(design_url, json=design_doc, auth=auth, timeout=30)
        if response.status_code in [200, 201]:
            print(f"✓ Design document updated with {len(design_doc['views'])} views")
        else:
            print(f"Warning: Failed to update design document: {response.status_code}")
    except requests.exceptions.RequestException as e:
        print(f"Warning: Failed to update design document: {e}")


def ensure_indexes(repo: str) -> None:
    """Create necessary indexes for efficient querying."""
    url = f"{get_couchdb_url(repo)}/_index"
    auth = get_auth()

    # Index for recommendations count
    recommendations_index = {
        "index": {"fields": ["recommendations"]},
        "name": "recommendations-index",
        "type": "json",
    }

    # Index for issue number
    number_index = {
        "index": {"fields": ["number"]},
        "name": "number-index",
        "type": "json",
    }

    # Index for state and updated_at
    state_updated_index = {
        "index": {"fields": ["state", "updated_at"]},
        "name": "state-updated-index",
        "type": "json",
    }

    indexes = [recommendations_index, number_index, state_updated_index]

    for index_def in indexes:
        try:
            response = requests.post(url, json=index_def, auth=auth, timeout=30)
            if response.status_code not in [200, 409]:  # 409 = index already exists
                response.raise_for_status()
        except requests.exceptions.RequestException as e:
            # Log warning but don't fail - indexes are optimization
            print(f"Warning: Failed to create index {index_def['name']}: {e}")

    # Design documents are only updated via CLI command, not during normal operations


def convert_numpy_types(obj: Any) -> Any:
    """Recursively convert NumPy types to Python native types for JSON serialization."""
    import numpy as np
    import math

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


def documents_are_equal(doc1: dict[str, Any], doc2: dict[str, Any]) -> bool:
    """Compare two documents for equality, ignoring CouchDB internal fields."""
    # Create copies without internal fields and pulled_date (which always changes)
    clean_doc1 = {
        k: v for k, v in doc1.items() if not k.startswith("_") and k != "pulled_date"
    }
    clean_doc2 = {
        k: v for k, v in doc2.items() if not k.startswith("_") and k != "pulled_date"
    }

    return clean_doc1 == clean_doc2


def delete_issue(repo: str, issue_number: int) -> bool:
    """Delete a specific issue from the database by issue number."""
    auth = get_auth()
    base_url = get_couchdb_url(repo)
    doc_id = f"{repo}-{issue_number}"
    encoded_doc_id = quote(doc_id, safe="")

    try:
        # Get current document to get revision
        response = requests.get(f"{base_url}/{encoded_doc_id}", auth=auth, timeout=30)
        if response.status_code == 404:
            return False  # Document doesn't exist
        elif response.status_code != 200:
            raise CouchDBConnectionError(
                f"Failed to fetch document for deletion: {response.status_code}"
            )

        existing_doc = response.json()
        if "_rev" not in existing_doc:
            raise CouchDBConnectionError("Document missing _rev field for deletion")

        # Delete the document
        delete_response = requests.delete(
            f"{base_url}/{encoded_doc_id}?rev={existing_doc['_rev']}",
            auth=auth,
            timeout=30,
        )

        if delete_response.status_code == 200:
            return True
        else:
            raise CouchDBConnectionError(
                f"Failed to delete document: {delete_response.status_code}"
            )

    except requests.exceptions.RequestException as e:
        raise CouchDBConnectionError(f"Network error during deletion: {e}")


def delete_issues(repo: str, issue_numbers: list[int]) -> tuple[int, int]:
    """Delete multiple issues from the database.

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


def get_latest_updated_date_from_view(repo: str) -> str | None:
    """Get the most recent updatedAt using CouchDB view (much faster than loading all docs)."""
    auth = get_auth()
    base_url = get_couchdb_url(repo)

    # Query the by_updatedAt view with descending=true&limit=1 to get the latest
    view_url = f"{base_url}/_design/queries/_view/by_updatedAt"
    params = {"descending": "true", "limit": 1, "include_docs": "true"}

    try:
        response = requests.get(view_url, params=params, auth=auth, timeout=30)
        if response.status_code == 200:
            data = response.json()
            if data.get("rows"):
                # Get the first row (which is the latest due to descending=true)
                latest_row = data["rows"][0]
                if latest_row.get("doc") and latest_row["doc"].get("updatedAt"):
                    return latest_row["doc"]["updatedAt"]
        elif response.status_code == 404:
            # View doesn't exist yet, fallback to old method
            return None
        else:
            print(f"Warning: Failed to query view: {response.status_code}")
            return None
    except requests.exceptions.RequestException as e:
        print(f"Warning: Failed to query view: {e}")
        return None


def save_issues(repo: str, issues: list[dict[str, Any]]) -> None:
    """Save issues to CouchDB database, replacing all existing data."""
    # Validate repo parameter to prevent incorrect database naming
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

    # Convert NumPy types to Python native types for JSON serialization
    serializable_issues = [convert_numpy_types(issue) for issue in issues]

    # Ensure database exists
    ensure_database_exists(repo)

    auth = get_auth()
    base_url = get_couchdb_url(repo)

    # Delete the database and recreate it to clear all data
    try:
        # Delete database
        response = requests.delete(base_url, auth=auth, timeout=30)
        if response.status_code not in [200, 404]:  # 404 = database doesn't exist
            response.raise_for_status()

        # Recreate database
        ensure_database_exists(repo)
        ensure_indexes(repo)

    except requests.exceptions.RequestException as e:
        raise CouchDBConnectionError(f"Failed to clear database {repo}: {e}")

    if not serializable_issues:
        return  # Nothing to save

    # Prepare documents with CouchDB _id
    docs = []
    for issue in serializable_issues:
        doc = {"_id": f"{repo}-{issue['number']}", **issue}
        docs.append(doc)

    # Use _bulk_docs to save all issues
    url = f"{base_url}/_bulk_docs"

    try:
        response = requests.post(url, json={"docs": docs}, auth=auth, timeout=60)
        response.raise_for_status()

        # Check for any document-level errors
        result = response.json()
        if isinstance(result, list):
            errors = [doc for doc in result if doc.get("error")]
            if errors:
                print(f"Warning: {len(errors)} documents had errors during save:")
                for error in errors[:3]:  # Show first 3 errors
                    print(
                        f"  - {error.get('error', 'unknown')}: {error.get('reason', 'no reason')}"
                    )

    except requests.exceptions.RequestException as e:
        raise CouchDBConnectionError(f"Failed to save issues to {repo}: {e}")


def clear_all_recommendations(repo: str) -> int:
    """Clear all recommendations from all issues in the repository.

    Returns the number of issues that had recommendations cleared.
    """
    print(f"🧹 Clearing all recommendations from {repo}...")

    # Load all issues with CouchDB metadata intact
    url = f"{get_couchdb_url(repo)}/_all_docs?include_docs=true"
    auth = get_auth()
    
    try:
        response = requests.get(url, auth=auth, timeout=60)
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.RequestException as e:
        if hasattr(e, "response") and e.response.status_code == 404:
            print("📁 No database found")
            return 0
        raise CouchDBConnectionError(f"Failed to load issues from {repo}: {e}")

    # Extract documents and keep CouchDB metadata
    issues_with_metadata = []
    for row in data.get("rows", []):
        if "doc" in row:
            doc = row["doc"]
            # Skip design documents
            if doc.get("_id", "").startswith("_design/"):
                continue
            issues_with_metadata.append(doc)

    if not issues_with_metadata:
        print("📁 No issues found in database")
        return 0

    # Count and update issues with recommendations
    cleared_count = 0
    base_url = get_couchdb_url(repo)

    for issue in issues_with_metadata:
        if issue.get("recommendations") and len(issue["recommendations"]) > 0:
            # Clear recommendations
            issue["recommendations"] = []

            # Update in database with proper revision
            doc_id = issue["_id"]
            try:
                encoded_doc_id = quote(doc_id, safe="")
                response = requests.put(
                    f"{base_url}/{encoded_doc_id}", json=issue, auth=auth, timeout=30
                )
                if response.status_code in [200, 201]:
                    cleared_count += 1
                    print(f"  ✓ Cleared recommendations from issue #{issue['number']}")
                else:
                    print(
                        f"  ❌ Failed to clear recommendations from issue #{issue['number']}: {response.status_code}"
                    )
            except requests.exceptions.RequestException as e:
                print(
                    f"  ❌ Network error clearing recommendations from issue #{issue['number']}: {e}"
                )

    print(f"✅ Cleared recommendations from {cleared_count} issues")
    return cleared_count


def load_issues(repo: str) -> list[dict[str, Any]]:
    """Load all issues from CouchDB database."""
    # Validate repo parameter to prevent incorrect database naming
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

    url = f"{get_couchdb_url(repo)}/_all_docs?include_docs=true"
    auth = get_auth()

    try:
        response = requests.get(url, auth=auth, timeout=60)
        response.raise_for_status()

        data = response.json()

        # Extract documents and remove CouchDB metadata
        issues = []
        for row in data.get("rows", []):
            if "doc" in row:
                doc = row["doc"].copy()
                # Skip design documents
                if doc.get("_id", "").startswith("_design/"):
                    continue
                # Remove CouchDB internal fields
                doc.pop("_id", None)
                doc.pop("_rev", None)
                issues.append(doc)

        return issues

    except requests.exceptions.RequestException as e:
        if hasattr(e, "response") and e.response.status_code == 404:
            # Database doesn't exist yet, return empty list
            return []
        raise CouchDBConnectionError(f"Failed to load issues from {repo}: {e}")


def upsert_issues(repo: str, issues: list[dict[str, Any]]) -> None:
    """Upsert issues to CouchDB database (update existing, insert new)."""
    # Validate repo parameter to prevent incorrect database naming
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

    # Ensure database exists
    ensure_database_exists(repo)
    ensure_indexes(repo)

    auth = get_auth()
    base_url = get_couchdb_url(repo)

    # Process each issue individually to avoid conflicts
    for issue in issues:
        doc_id = f"{repo}-{issue['number']}"
        doc = convert_numpy_types(issue).copy()
        doc["_id"] = doc_id

        # Add pulled_date for tracking when data was last fetched
        from datetime import datetime

        doc["pulled_date"] = datetime.now().isoformat()

        # Get current revision if document exists and check if update is needed
        existing_doc = None
        try:
            encoded_doc_id = quote(doc_id, safe="")
            response = requests.get(
                f"{base_url}/{encoded_doc_id}", auth=auth, timeout=30
            )
            if response.status_code == 200:
                existing_doc = response.json()
                if "_rev" in existing_doc:
                    doc["_rev"] = existing_doc["_rev"]

                    # Check if documents are the same - skip update if no changes
                    if documents_are_equal(existing_doc, doc):
                        print(
                            f"  → Issue #{issue['number']}: No changes detected, skipping database update"
                        )
                        return  # No changes needed
        except requests.exceptions.RequestException:
            # Document doesn't exist, will be created
            pass

        # Save the document
        try:
            encoded_doc_id = quote(doc_id, safe="")
            response = requests.put(
                f"{base_url}/{encoded_doc_id}", json=doc, auth=auth, timeout=30
            )
            if response.status_code in [200, 201]:
                # Success - print appropriate message
                comments_count = len(doc.get("comments", []))
                cross_refs_count = len(doc.get("cross_references", []))
                updated_at = doc.get("updatedAt", "unknown")
                action = "updated" if existing_doc else "created"
                print(
                    f"  ✓ Issue #{issue['number']} (updated: {updated_at}): {comments_count} comments, {cross_refs_count} cross-refs - {action} in database"
                )
            elif response.status_code == 409:
                # Document conflict - merge with current version
                try:
                    print(f"Debug: Fetching URL: {base_url}/{encoded_doc_id}")
                    get_response = requests.get(
                        f"{base_url}/{encoded_doc_id}", auth=auth, timeout=30
                    )
                    print(f"Debug: Response status: {get_response.status_code}")
                    print(f"Debug: Response headers: {dict(get_response.headers)}")
                    if get_response.status_code == 200:
                        existing_doc = get_response.json()
                        if "_rev" not in existing_doc:
                            print(f"Debug: Document keys: {list(existing_doc.keys())}")
                            print(
                                f"Debug: Response text (first 300 chars): {get_response.text[:300]}"
                            )
                            raise CouchDBDocumentConflict(
                                f"Document for issue #{issue['number']} missing _rev field"
                            )
                        # Merge: existing doc gets updated with new issue data
                        merged_doc = existing_doc.copy()
                        merged_doc.update(convert_numpy_types(issue))
                        merged_doc["_id"] = doc_id  # Ensure _id is correct
                        # _rev is preserved from existing_doc by update()

                        # Check if the merged document is different from existing
                        if documents_are_equal(existing_doc, merged_doc):
                            print(
                                f"  → Issue #{issue['number']}: No changes after merge, skipping database update"
                            )
                            return  # No changes needed after merge

                        retry_response = requests.put(
                            f"{base_url}/{encoded_doc_id}",
                            json=merged_doc,
                            auth=auth,
                            timeout=30,
                        )
                        if retry_response.status_code in [200, 201]:
                            # Success after merge
                            comments_count = len(merged_doc.get("comments", []))
                            cross_refs_count = len(
                                merged_doc.get("cross_references", [])
                            )
                            updated_at = merged_doc.get("updatedAt", "unknown")
                            print(
                                f"  ✓ Issue #{issue['number']} (updated: {updated_at}): {comments_count} comments, {cross_refs_count} cross-refs - merged and updated in database"
                            )
                        else:
                            raise CouchDBDocumentConflict(
                                f"Failed to upsert issue #{issue['number']} after merge: {retry_response.status_code}"
                            )
                    else:
                        raise CouchDBDocumentConflict(
                            f"Failed to fetch current document for issue #{issue['number']}: {get_response.status_code}"
                        )
                except requests.exceptions.RequestException as e:
                    raise CouchDBConnectionError(
                        f"Network error during merge for issue #{issue['number']}: {e}"
                    )
            elif response.status_code not in [200, 201]:
                raise CouchDBConnectionError(
                    f"Failed to upsert issue #{issue['number']}: {response.status_code}"
                )
        except requests.exceptions.InvalidJSONError as e:
            # Debug JSON serialization issues
            import math
            print(f"\n❌ JSON serialization error for issue #{issue['number']}:")
            print(f"   Error: {e}")
            
            # Find and report NaN/Infinity values
            def find_invalid_values(obj, path=''):
                invalid_found = []
                if isinstance(obj, float):
                    if math.isnan(obj):
                        invalid_found.append(f"{path} = NaN")
                    elif math.isinf(obj):
                        invalid_found.append(f"{path} = Infinity")
                elif isinstance(obj, dict):
                    for k, v in obj.items():
                        invalid_found.extend(find_invalid_values(v, f'{path}.{k}' if path else k))
                elif isinstance(obj, list):
                    for i, v in enumerate(obj):
                        invalid_found.extend(find_invalid_values(v, f'{path}[{i}]'))
                return invalid_found
            
            invalid_values = find_invalid_values(doc)
            if invalid_values:
                print("   Invalid values found:")
                for invalid in invalid_values[:10]:  # Limit to first 10
                    print(f"     - {invalid}")
                if len(invalid_values) > 10:
                    print(f"     ... and {len(invalid_values) - 10} more")
            
            # Print summary of issue data
            print(f"\n   Issue #{issue['number']} summary:")
            print(f"     Title: {issue.get('title', 'N/A')[:80]}")
            print(f"     Created: {issue.get('createdAt', 'N/A')}")
            print(f"     Updated: {issue.get('updatedAt', 'N/A')}")
            print(f"     Age days: {issue.get('age_days', 'N/A')}")
            print(f"     Engagements: {issue.get('engagements', 'N/A')}")
            print(f"     Engagements/day: {issue.get('engagements_per_day', 'N/A')}")
            
            # Re-raise the original error
            raise CouchDBConnectionError(
                f"JSON serialization error for issue #{issue['number']}: {e}"
            )
        except requests.exceptions.RequestException as e:
            raise CouchDBConnectionError(
                f"Network error upserting issue #{issue['number']}: {e}"
            )
