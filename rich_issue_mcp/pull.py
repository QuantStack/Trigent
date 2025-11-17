#!/usr/bin/env python3
"""Pull GitHub issues using Issues REST API with intelligent page-based caching."""

import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import requests
import toml

from rich_issue_mcp.database import load_issues
from rich_issue_mcp.enrich import enrich_issue
from rich_issue_mcp.config import get_config


def get_last_updated_date(repo: str, config: dict[str, Any] | None = None) -> datetime | None:
    """Get the most recent updated date from existing issues in database."""
    from rich_issue_mcp.database import get_latest_updated_date_from_view, load_issues
    
    # Try the efficient view-based approach first
    try:
        latest_updated_str = get_latest_updated_date_from_view(repo)
        if latest_updated_str:
            return datetime.fromisoformat(latest_updated_str.replace("Z", "+00:00"))
    except Exception as e:
        print(f"⚠️  View-based query failed: {e}")
    
    # Fallback to loading all issues (slower but reliable)
    try:
        existing_issues = load_issues(repo)
        if not existing_issues:
            return None

        updated_dates = [
            datetime.fromisoformat(issue["updatedAt"].replace("Z", "+00:00"))
            for issue in existing_issues
            if "updatedAt" in issue
        ]

        if not updated_dates:
            return None

        return max(updated_dates)
    except Exception as e:
        print(f"⚠️  Could not get last updated date: {e}")
        return None


def get_existing_issue_numbers(repo: str, config: dict[str, Any] | None = None) -> set[int]:
    """Get set of existing issue numbers in database to avoid re-pulling."""
    try:
        existing_issues = load_issues(repo, config)
        return {issue["number"] for issue in existing_issues if "number" in issue}
    except Exception:
        return set()


def get_database_coverage(
    repo: str, mode: str = "update", config: dict[str, Any] | None = None
) -> tuple[datetime, datetime] | None:
    """Get the date range covered by existing database issues.

    Args:
        repo: GitHub repository in owner/repo format
        mode: Either 'create' or 'update' - determines which timestamp field to use
    """
    try:
        existing_issues = load_issues(repo, config)
        if not existing_issues:
            return None

        # Use different timestamp field based on mode
        date_field = "createdAt" if mode == "create" else "updatedAt"
        dates = [
            datetime.fromisoformat(issue[date_field].replace("Z", "+00:00"))
            for issue in existing_issues
            if date_field in issue
        ]

        if not dates:
            return None

        return (min(dates), max(dates))
    except Exception as e:
        print(f"⚠️  Could not analyze database coverage: {e}")
        return None


def get_github_token() -> str:
    """Get GitHub token from config or environment."""
    # Try config file first
    config_path = Path("config.toml")
    if config_path.exists():
        try:
            config = toml.load(config_path)
            # Try both locations for token
            token = config.get("github", {}).get("token") or config.get("token")
            if token:
                return str(token)
        except Exception:
            pass

    raise ValueError(
        "No GitHub token found. Set token in config.toml, use 'gh auth login', or set GITHUB_TOKEN"
    )


def make_rest_request(
    url: str, params: dict[str, Any] | None = None, max_retries: int = 5
) -> requests.Response:
    """Make a REST API request to GitHub with rate limit handling."""
    import requests.exceptions

    token = get_github_token()
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "RichIssueMCP/1.0",
    }

    for attempt in range(max_retries):
        try:
            response = requests.get(url, headers=headers, params=params, timeout=30)
        except (requests.exceptions.ConnectTimeout, requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            print(f"⚠️  Network error on attempt {attempt + 1}/{max_retries}: {e}")
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt  # Exponential backoff: 1, 2, 4, 8 seconds
                print(f"🔄 Retrying in {wait_time} seconds...")
                time.sleep(wait_time)
                continue
            else:
                print(f"❌ Failed after {max_retries} attempts, skipping this request")
                raise
        except requests.exceptions.RequestException as e:
            print(f"⚠️  Request error on attempt {attempt + 1}/{max_retries}: {e}")
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt
                print(f"🔄 Retrying in {wait_time} seconds...")
                time.sleep(wait_time)
                continue
            else:
                print(f"❌ Failed after {max_retries} attempts, skipping this request")
                raise

        # If successful, return immediately
        if response.status_code == 200:
            return response

        # Handle rate limit errors
        if response.status_code == 403:
            try:
                error_data = response.json()
                if "rate limit" in error_data.get("message", "").lower():
                    # Check if we have rate limit reset info in headers
                    rate_limit_reset = response.headers.get("X-RateLimit-Reset")
                    remaining = response.headers.get("X-RateLimit-Remaining", "0")

                    if rate_limit_reset:
                        reset_time = int(rate_limit_reset)
                        current_time = int(time.time())
                        time_until_reset = (
                            reset_time - current_time + 10
                        )  # Add 10 second buffer

                        # Wait until rate limit resets
                        wait_time = max(time_until_reset, 60)  # Minimum 60 seconds

                        reset_datetime = datetime.fromtimestamp(reset_time)
                        print(
                            f"⚠️  Rate limit exceeded (remaining: {remaining}). "
                            f"Waiting {wait_time} seconds until reset at {reset_datetime.strftime('%H:%M:%S')}..."
                        )
                    else:
                        # Fallback: exponential backoff
                        wait_time = 60 * (2**attempt)
                        print(
                            f"⚠️  Rate limit hit (attempt {attempt + 1}/{max_retries}). "
                            f"Waiting {wait_time} seconds..."
                        )

                    time.sleep(wait_time)
                    continue
            except (ValueError, KeyError):
                # Not a JSON response or missing fields, treat as non-rate-limit 403
                pass

        # For non-rate-limit errors or final attempt, return the response
        if attempt == max_retries - 1 or response.status_code != 403:
            return response

        # For other 403 errors, wait a short time before retry
        print(
            f"⚠️  Request failed with 403 (attempt {attempt + 1}/{max_retries}). Waiting 30 seconds..."
        )
        time.sleep(30)

    return response


def make_graphql_request(
    query: str, variables: dict[str, Any] | None = None, max_retries: int = 5
) -> requests.Response:
    """Make a GraphQL API request to GitHub with rate limit handling."""
    token = get_github_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "User-Agent": "RichIssueMCP/1.0",
    }

    payload = {"query": query}
    if variables:
        payload["variables"] = variables

    for attempt in range(max_retries):
        response = requests.post(
            "https://api.github.com/graphql", headers=headers, json=payload
        )

        # If successful, return immediately
        if response.status_code == 200:
            return response

        # Handle rate limit errors
        if response.status_code == 403:
            try:
                error_data = response.json()
                if "rate limit" in error_data.get("message", "").lower():
                    # Check if we have rate limit reset info in headers
                    rate_limit_reset = response.headers.get("X-RateLimit-Reset")
                    remaining = response.headers.get("X-RateLimit-Remaining", "0")

                    if rate_limit_reset:
                        reset_time = int(rate_limit_reset)
                        current_time = int(time.time())
                        time_until_reset = (
                            reset_time - current_time + 10
                        )  # Add 10 second buffer

                        # Wait until rate limit resets
                        wait_time = max(time_until_reset, 60)  # Minimum 60 seconds

                        reset_datetime = datetime.fromtimestamp(reset_time)
                        print(
                            f"⚠️  GraphQL Rate limit exceeded (remaining: {remaining}). "
                            f"Waiting {wait_time} seconds until reset at {reset_datetime.strftime('%H:%M:%S')}..."
                        )
                    else:
                        # Fallback: exponential backoff
                        wait_time = 60 * (2**attempt)
                        print(
                            f"⚠️  GraphQL Rate limit hit (attempt {attempt + 1}/{max_retries}). "
                            f"Waiting {wait_time} seconds..."
                        )

                    time.sleep(wait_time)
                    continue
            except (ValueError, KeyError):
                # Not a JSON response or missing fields, treat as non-rate-limit 403
                pass

        # For non-rate-limit errors or final attempt, return the response
        if attempt == max_retries - 1 or response.status_code != 403:
            return response

        # For other 403 errors, wait a short time before retry
        print(
            f"⚠️  GraphQL Request failed with 403 (attempt {attempt + 1}/{max_retries}). Waiting 30 seconds..."
        )
        time.sleep(30)

    return response


def fetch_issues_page_graphql(
    repo: str,
    cursor: str | None = None,
    include_closed: bool = True,
    since: str | None = None,
    mode: str = "update",
    item_type: str = "issues",
) -> tuple[list[dict[str, Any]], str | None, bool]:
    """Fetch a single page of issues or PRs using GraphQL API with cursor-based pagination.

    Args:
        repo: GitHub repository in owner/repo format
        cursor: Cursor for pagination (after this cursor)
        include_closed: Whether to include closed items
        since: ISO timestamp to fetch items since
        mode: Either 'create' (sort by created) or 'update' (sort by updated)
        item_type: Either 'issues' or 'pull_requests'

    Returns:
        Tuple of (items_list, next_cursor, has_next_page)
    """
    owner, name = repo.split("/")

    # Set sort parameters based on mode
    order_by = "CREATED_AT" if mode == "create" else "UPDATED_AT"

    # Build states filter - for PRs, include MERGED state as well
    if item_type == "pull_requests":
        states = ["OPEN", "CLOSED", "MERGED"] if include_closed else ["OPEN"]
    else:
        states = ["OPEN", "CLOSED"] if include_closed else ["OPEN"]
    states_filter = ", ".join(states)

    # Build GraphQL query based on item type (create mode - sort by CREATED_AT)
    if item_type == "issues":
        query = f"""
        query($owner: String!, $name: String!, $cursor: String) {{
            repository(owner: $owner, name: $name) {{
                issues(first: 100, after: $cursor, orderBy: {{field: {order_by}, direction: ASC}}, states: [{states_filter}]) {{
                    pageInfo {{
                        hasNextPage
                        endCursor
                    }}
                    nodes {{
                        number
                        title
                        body
                        state
                        createdAt
                        updatedAt
                        url
                        author {{
                            login
                        }}
                        labels(first: 50) {{
                            nodes {{
                                name
                                color
                            }}
                        }}
                        assignees(first: 10) {{
                            nodes {{
                                login
                            }}
                        }}
                        reactionGroups {{
                            content
                            users {{
                                totalCount
                            }}
                        }}
                    }}
                }}
            }}
            rateLimit {{
                remaining
                resetAt
            }}
        }}
        """
    else:  # pull_requests
        query = f"""
        query($owner: String!, $name: String!, $cursor: String) {{
            repository(owner: $owner, name: $name) {{
                pullRequests(first: 100, after: $cursor, orderBy: {{field: {order_by}, direction: ASC}}, states: [{states_filter}]) {{
                    pageInfo {{
                        hasNextPage
                        endCursor
                    }}
                    nodes {{
                        number
                        title
                        body
                        state
                        createdAt
                        updatedAt
                        url
                        author {{
                            login
                        }}
                        labels(first: 50) {{
                            nodes {{
                                name
                                color
                            }}
                        }}
                        assignees(first: 10) {{
                            nodes {{
                                login
                            }}
                        }}
                        reactionGroups {{
                            content
                            users {{
                                totalCount
                            }}
                        }}
                        mergeable
                        merged
                        mergedAt
                        baseRefName
                        headRefName
                    }}
                }}
            }}
            rateLimit {{
                remaining
                resetAt
            }}
        }}
        """

    variables = {"owner": owner, "name": name, "cursor": cursor}

    response = make_graphql_request(query, variables)

    if response.status_code != 200:
        raise Exception(f"GraphQL API failed: {response.status_code} - {response.text}")

    data = response.json()

    if "errors" in data:
        raise Exception(f"GraphQL errors: {data['errors']}")

    repository = data["data"]["repository"]
    rate_limit = data["data"]["rateLimit"]

    # Get the appropriate data based on item type
    if item_type == "issues":
        items_data = repository["issues"]
        type_name = "issue"
    else:  # pull_requests
        items_data = repository["pullRequests"]
        type_name = "pull_request"

    # Convert GraphQL format to REST API format for compatibility
    items = []
    for node in items_data["nodes"]:
        item = {
            "number": node["number"],
            "title": node["title"],
            "body": node["body"],
            "state": node["state"].lower(),
            "created_at": node["createdAt"],
            "updated_at": node["updatedAt"],
            "html_url": node["url"],
            "user": {"login": node["author"]["login"] if node["author"] else "ghost"},
            "labels": [
                {"name": label["name"], "color": label["color"]}
                for label in node["labels"]["nodes"]
            ],
            "assignees": [
                {"login": assignee["login"]} for assignee in node["assignees"]["nodes"]
            ],
            "reactionGroups": node.get("reactionGroups", []),
            "item_type": type_name,
            "pulled_date": datetime.now().isoformat(),
        }

        # Add PR-specific fields
        if item_type == "pull_requests":
            item.update(
                {
                    "mergeable": node.get("mergeable"),
                    "merged": node.get("merged", False),
                    "merged_at": node.get("mergedAt"),
                    "base_ref": node.get("baseRefName"),
                    "head_ref": node.get("headRefName"),
                }
            )

        items.append(item)

    page_info = items_data["pageInfo"]
    next_cursor = page_info["endCursor"] if page_info["hasNextPage"] else None
    has_next_page = page_info["hasNextPage"]

    # Print rate limit info
    remaining = rate_limit["remaining"]
    reset_at = rate_limit["resetAt"]
    reset_time = datetime.fromisoformat(reset_at.replace("Z", "+00:00"))

    cursor_info = f"cursor={cursor[:10]}..." if cursor else "first page"
    item_name = "issues" if item_type == "issues" else "PRs"
    print(
        f"📄 GraphQL fetched {cursor_info}: {len(items)} {item_name}, "
        f"Rate limit: {remaining} remaining (resets at {reset_time.strftime('%H:%M:%S')}), "
        f"Has next: {has_next_page}"
    )

    # Debug: show first and last issue numbers on this page
    if items:
        first_num = items[0]["number"]
        last_num = items[-1]["number"]
        print(f"  🔢 Issue range on this page: #{first_num} to #{last_num}")

        # Look for missing PR 2525
        if first_num <= 2525 <= last_num:
            print("  🎯 This page should contain PR #2525!")
            has_2525 = any(item["number"] == 2525 for item in items)
            print(f"  🎯 PR #2525 actually present: {has_2525}")
            if has_2525:
                print("  ✅ Found PR #2525! Fix successful.")
    else:
        print("  🔢 No items returned from GraphQL")

    return items, next_cursor, has_next_page


def filter_new_issues_for_create_mode(
    page_issues: list[dict[str, Any]], existing_numbers: set[int]
) -> list[dict[str, Any]]:
    """Filter out issues that already exist in database for create mode."""
    return [issue for issue in page_issues if issue["number"] not in existing_numbers]


def page_needs_processing(
    page_issues: list[dict[str, Any]],
    coverage: tuple[datetime, datetime] | None,
    mode: str = "update",
) -> bool:
    """Check if any issue in the page needs processing (outside existing coverage).

    Uses a one-day margin to handle cases where many issues have the same timestamp,
    which can cause skipped pages when some issues with identical timestamps are missing.

    Args:
        page_issues: List of issues from the current page
        coverage: Database coverage range (min_date, max_date) or None
        mode: Either 'create' or 'update' - determines which timestamp field to check
    """
    if not coverage or not page_issues:
        return True

    earliest_db, latest_db = coverage

    # Add one-day margin to coverage range to avoid skipping issues with identical timestamps
    earliest_with_margin = earliest_db - timedelta(days=1)
    latest_with_margin = latest_db + timedelta(days=1)

    # Use different timestamp field based on mode
    timestamp_field = "created_at" if mode == "create" else "updated_at"

    # Check if any issue in this page is outside the database coverage (with margin)
    for issue in page_issues:
        issue_timestamp = datetime.fromisoformat(
            issue[timestamp_field].replace("Z", "+00:00")
        )
        if (
            issue_timestamp < earliest_with_margin
            or issue_timestamp > latest_with_margin
        ):
            return True

    return False


def fetch_all_comments(repo: str, issue_number: int) -> list[dict[str, Any]] | None:
    """Fetch all comments for an issue with pagination.

    Returns:
        List of comments if successful, None if failed to fetch
    """
    import requests.exceptions

    all_comments = []
    page = 1

    while True:
        comments_url = (
            f"https://api.github.com/repos/{repo}/issues/{issue_number}/comments"
        )

        try:
            response = make_rest_request(comments_url, {"per_page": 100, "page": page})
        except KeyboardInterrupt:
            print(f"🛑 Interrupted while fetching comments for issue #{issue_number}")
            raise
        except (requests.exceptions.ConnectTimeout, requests.exceptions.ConnectionError,
                requests.exceptions.Timeout, requests.exceptions.RequestException) as e:
            print(f"❌ Network error fetching comments for issue #{issue_number}: {e}")
            print(f"⚠️  Skipping issue #{issue_number} - refusing incomplete data")
            return None  # Return None to indicate failure - issue will be skipped

        if response.status_code != 200:
            print(
                f"⚠️  Failed to get comments for issue #{issue_number}: {response.status_code}"
            )
            return None

        comments = response.json()
        if not comments:
            break

        all_comments.extend(comments)
        page += 1

    return [
        {
            "id": str(comment["id"]),
            "body": comment["body"],
            "createdAt": comment["created_at"],
            "updatedAt": comment["updated_at"],
            "author": {"login": comment["user"]["login"]},
            "authorAssociation": comment.get("author_association", "NONE"),
            "reactions": {
                "totalCount": comment.get("reactions", {}).get("total_count", 0)
            },
        }
        for comment in all_comments
    ]


def fetch_all_timeline_cross_references(
    repo: str, issue_number: int
) -> list[dict[str, Any]] | None:
    """Fetch all cross-references from timeline with pagination.

    Returns:
        List of cross-references if successful, None if failed to fetch
    """
    import requests.exceptions

    all_cross_references = []
    page = 1

    while True:
        timeline_url = (
            f"https://api.github.com/repos/{repo}/issues/{issue_number}/timeline"
        )

        try:
            response = make_rest_request(timeline_url, {"per_page": 100, "page": page})
        except KeyboardInterrupt:
            print(f"🛑 Interrupted while fetching timeline for issue #{issue_number}")
            raise
        except (requests.exceptions.ConnectTimeout, requests.exceptions.ConnectionError,
                requests.exceptions.Timeout, requests.exceptions.RequestException) as e:
            print(f"❌ Network error fetching timeline for issue #{issue_number}: {e}")
            print(f"⚠️  Skipping issue #{issue_number} - refusing incomplete data")
            return None  # Return None to indicate failure - issue will be skipped

        if response.status_code != 200:
            print(
                f"⚠️  Failed to get timeline for issue #{issue_number}: {response.status_code}"
            )
            return None

        timeline_events = response.json()
        if not timeline_events:
            break

        # Filter cross-referenced events
        for event in timeline_events:
            if event.get("event") == "cross-referenced" and event.get("source"):
                source = event["source"]

                if "issue" in source:
                    item = source["issue"]
                    item_type = "issue"
                elif "pull_request" in source:
                    item = source["pull_request"]
                    item_type = "pr"
                else:
                    continue

                cross_ref = {
                    "number": item.get("number"),
                    "type": item_type,
                    "title": item.get("title"),
                    "url": item.get("html_url"),
                    "author": item.get("user", {}).get("login"),
                }
                all_cross_references.append(cross_ref)

        page += 1

    return all_cross_references


def process_and_save_issue(repo: str, issue: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Process a single issue by fetching comments and cross-references, enriching, then save to database.

    Returns:
        Processed issue if successful, None if comments or cross-references could not be fetched
    """
    from rich_issue_mcp.database import upsert_issues

    issue_number = issue["number"]

    # Fetch all comments with pagination
    comments_list = fetch_all_comments(repo, issue_number)
    if comments_list is None:
        print(f"  ✗ Issue #{issue_number}: Failed to fetch comments - skipping save")
        return None

    # Fetch all cross-references with pagination
    cross_references = fetch_all_timeline_cross_references(repo, issue_number)
    if cross_references is None:
        print(
            f"  ✗ Issue #{issue_number}: Failed to fetch cross-references - skipping save"
        )
        return None

    # Transform to expected format (without pulled_date for comparison)
    processed_issue = {
        "number": issue["number"],
        "title": issue["title"],
        "body": issue["body"],
        "state": issue["state"],
        "createdAt": issue["created_at"],
        "updatedAt": issue["updated_at"],
        "url": issue["html_url"],
        "author": {"login": issue["user"]["login"]},
        "labels": [
            {"name": label["name"], "color": label["color"]}
            for label in issue.get("labels", [])
        ],
        "assignees": [
            {"login": assignee["login"]} for assignee in issue.get("assignees", [])
        ],
        "comments": comments_list,
        "number_of_comments": len(comments_list),
        "reactionGroups": issue.get("reactionGroups", []),
        "cross_references": cross_references,
    }

    # Enrich with embeddings and summaries inline
    try:
        if config is None:
            raise ValueError("Config must be provided to process_and_save_issue")
            
        api_key = config.get("api", {}).get("mistral_api_key")
        model = "mistral-embed"
        
        if api_key:
            print(f"  🧠 Enriching issue #{issue_number} with embeddings...")
            enriched_issue = enrich_issue(processed_issue, api_key, model)
        else:
            print(f"  ⚠️  No Mistral API key found, skipping enrichment for issue #{issue_number}")
            enriched_issue = processed_issue
            enriched_issue["embedding"] = None
            enriched_issue["summary"] = None
    except Exception as e:
        print(f"  ❌ Error enriching issue #{issue_number}: {e}")
        enriched_issue = processed_issue
        enriched_issue["embedding"] = None
        enriched_issue["summary"] = None

    # Save immediately to database (upsert_issues will handle the pulled_date and messaging)
    upsert_issues(repo, [enriched_issue], config)

    return enriched_issue


def process_page_issues(
    repo: str, page_issues: list[dict[str, Any]], config: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    """Process a page of issues by fetching comments and cross-references with pagination."""
    processed_issues = []

    for issue in page_issues:
        processed_issue = process_and_save_issue(repo, issue, config)
        if processed_issue is not None:
            processed_issues.append(processed_issue)

    return processed_issues


def fetch_specific_issue(repo: str, issue_number: int) -> dict[str, Any] | None:
    """Fetch a specific issue by number using Issues API."""
    issue_url = f"https://api.github.com/repos/{repo}/issues/{issue_number}"

    response = make_rest_request(issue_url)

    if response.status_code == 404:
        print(f"⚠️  Issue #{issue_number} not found")
        return None
    elif response.status_code != 200:
        print(
            f"⚠️  Failed to fetch issue #{issue_number}: {response.status_code} - {response.text}"
        )
        return None

    return response.json()


def fetch_specific_issues(repo: str, issue_numbers: list[int], config: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Fetch specific issues by number and process them."""
    print(
        f"🎯 Fetching {len(issue_numbers)} specific issues: {', '.join(map(str, issue_numbers))}"
    )

    processed_issues = []

    for issue_number in issue_numbers:
        print(f"\n🔍 Fetching issue #{issue_number}...")

        # Fetch the issue
        issue = fetch_specific_issue(repo, issue_number)
        if issue is None:
            continue

        # Process and save the issue
        processed_issue = process_and_save_issue(repo, issue, config)
        if processed_issue is not None:
            processed_issues.append(processed_issue)

    return processed_issues


def fetch_items_with_rest_since(
    repo: str,
    item_type: str,
    include_closed: bool,
    since: datetime,
    config: dict[str, Any] | None = None,
) -> tuple[int, int, int]:
    """Fetch items using REST API with since parameter for efficient updates.
    
    Args:
        repo: GitHub repository in owner/repo format
        item_type: Either 'issues' or 'pull_requests'
        include_closed: Whether to include closed items
        since: Datetime to fetch items updated since
        
    Returns:
        Tuple of (processed_count, comments_count, cross_refs_count)
    """
    if item_type == "pull_requests":
        api_url = f"https://api.github.com/repos/{repo}/pulls"
        type_name = "PRs"
    else:
        api_url = f"https://api.github.com/repos/{repo}/issues"
        type_name = "issues"

    # Convert since datetime to ISO string format required by GitHub API
    since_str = since.isoformat().replace("+00:00", "Z")
    print(f"🕐 Fetching {type_name} updated since: {since.strftime('%Y-%m-%d %H:%M:%S UTC')}")

    state = "all" if include_closed else "open"
    page = 1
    total_processed = 0
    total_comments = 0
    total_cross_refs = 0

    while True:
        print(f"\n🔍 Fetching {type_name} page {page} (REST API with since)...")

        params = {
            "state": state,
            "sort": "updated",
            "direction": "asc",
            "since": since_str,
            "per_page": 100,
            "page": page
        }

        try:
            response = make_rest_request(api_url, params)
        except Exception as e:
            print(f"❌ Failed to fetch {type_name} page {page}: {e}")
            break

        if response.status_code != 200:
            print(f"❌ REST API failed: {response.status_code} - {response.text}")
            break

        items = response.json()

        if not items:
            print(f"✅ No more {type_name} found - fetch complete")
            break

        # GitHub Issues API returns both issues and PRs - process both
        # Separate them by checking for pull_request field
        issues_from_api = [item for item in items if "pull_request" not in item]
        prs_from_api = [item for item in items if "pull_request" in item]

        # Convert both issues and PRs to same schema as GraphQL for compatibility
        page_items = []

        # Process issues
        for item in issues_from_api:
            converted_item = {
                "number": item["number"],
                "title": item["title"],
                "body": item["body"],
                "state": item["state"],  # REST API already lowercase
                "created_at": item["created_at"],
                "updated_at": item["updated_at"],
                "html_url": item["html_url"],
                "user": {"login": item["user"]["login"] if item["user"] else "ghost"},
                "labels": [
                    {"name": label["name"], "color": label["color"]}
                    for label in item.get("labels", [])
                ],
                "assignees": [
                    {"login": assignee["login"]} for assignee in item.get("assignees", [])
                ],
                "reactionGroups": [],  # Not available in REST API
                "item_type": "issue",
                "pulled_date": datetime.now().isoformat(),
            }
            page_items.append(converted_item)

        # Process PRs
        for item in prs_from_api:
            converted_item = {
                "number": item["number"],
                "title": item["title"],
                "body": item["body"],
                "state": item["state"],  # REST API already lowercase
                "created_at": item["created_at"],
                "updated_at": item["updated_at"],
                "html_url": item["html_url"],
                "user": {"login": item["user"]["login"] if item["user"] else "ghost"},
                "labels": [
                    {"name": label["name"], "color": label["color"]}
                    for label in item.get("labels", [])
                ],
                "assignees": [
                    {"login": assignee["login"]} for assignee in item.get("assignees", [])
                ],
                "reactionGroups": [],  # Not available in REST API
                "item_type": "pull_request",
                # Add PR-specific fields
                "mergeable": item.get("mergeable"),
                "merged": item.get("merged", False),
                "merged_at": item.get("merged_at"),  # REST uses snake_case
                "base_ref": item.get("base", {}).get("ref"),
                "head_ref": item.get("head", {}).get("ref"),
                "pulled_date": datetime.now().isoformat(),
            }
            page_items.append(converted_item)

        if not page_items:
            print(f"✅ No {type_name} remaining after filtering - fetch complete")
            break

        issues_count = len(issues_from_api)
        prs_count = len(prs_from_api)
        print(f"📄 REST API fetched page {page}: {issues_count} issues, {prs_count} PRs ({len(page_items)} total)")

        if page_items:
            first_num = page_items[0]["number"]
            last_num = page_items[-1]["number"]
            print(f"  🔢 Item range on this page: #{first_num} to #{last_num}")

        # Process the items (fetch comments and cross-references)
        print(f"🔧 Processing page {page} ({len(page_items)} items: {issues_count} issues, {prs_count} PRs)...")
        processed_items = process_page_issues(repo, page_items, config)

        # Count stats
        page_comments = sum(len(item["comments"]) for item in processed_items)
        page_cross_refs = sum(len(item["cross_references"]) for item in processed_items)

        total_processed += len(processed_items)
        total_comments += page_comments
        total_cross_refs += page_cross_refs

        print(f"  📊 Page stats: {page_comments} comments, {page_cross_refs} cross-refs")

        # Check if there are more pages by looking at the Link header
        link_header = response.headers.get("Link", "")
        if 'rel="next"' not in link_header:
            print(f"✅ No more {type_name} pages - fetch complete")
            break

        page += 1

    return total_processed, total_comments, total_cross_refs


def fetch_items_with_pagination(
    repo: str,
    item_type: str,
    include_closed: bool,
    existing_numbers: set[int],
    coverage: tuple[datetime, datetime] | None,
    mode: str,
    config: dict[str, Any] | None = None,
) -> tuple[int, int, int]:
    """Fetch all items (issues or PRs) with pagination.

    Returns:
        Tuple of (processed_count, comments_count, cross_refs_count)
    """
    cursor = None
    page_num = 1
    total_processed = 0
    total_comments = 0
    total_cross_refs = 0

    while True:
        print(f"\n🔍 Fetching {item_type} page {page_num}...")
        page_items, next_cursor, has_next_page = fetch_issues_page_graphql(
            repo, cursor, include_closed, None, mode, item_type
        )

        if not page_items:
            print(f"✅ No more {item_type} found - fetch complete")
            break

        # Filter out existing items in create mode
        if mode == "create" and existing_numbers:
            original_count = len(page_items)

            # Debug: Check first few items in this page
            if page_items:
                sample_numbers = [item["number"] for item in page_items[:5]]
                sample_in_db = [
                    num for num in sample_numbers if num in existing_numbers
                ]
                print(
                    f"  🐛 Debug: Page has {original_count} items, sample numbers: {sample_numbers}"
                )
                print(f"  🐛 Debug: Sample numbers in existing_numbers: {sample_in_db}")
                print(f"  🐛 Debug: existing_numbers size: {len(existing_numbers)}")

            page_items = filter_new_issues_for_create_mode(page_items, existing_numbers)
            filtered_count = original_count - len(page_items)
            if filtered_count > 0:
                print(
                    f"  ⏭️  Filtered out {filtered_count} existing {item_type} ({len(page_items)} new)"
                )

        if not page_items:
            print(f"  ⏭️  All {item_type} in page already exist - skipping")
            # Stop if no more pages (check before updating cursor)
            if not has_next_page:
                print(f"✅ No more {item_type} pages - fetch complete")
                break
            cursor = next_cursor
            page_num += 1
            continue

        # Check if this page needs processing (for update mode with coverage)
        needs_processing = True
        if mode == "update":
            needs_processing = page_needs_processing(page_items, coverage, mode)

        if needs_processing:
            print(
                f"🔧 Processing {item_type} page {page_num} ({len(page_items)} items)..."
            )
            processed_items = process_page_issues(repo, page_items, config)

            # Count stats
            page_comments = sum(len(item["comments"]) for item in processed_items)
            page_cross_refs = sum(
                len(item["cross_references"]) for item in processed_items
            )

            total_processed += len(processed_items)
            total_comments += page_comments
            total_cross_refs += page_cross_refs

            print(
                f"  📊 Page stats: {page_comments} comments, {page_cross_refs} cross-refs"
            )

        else:
            print(
                f"⏭️  Skipping {item_type} page {page_num} - all items already in database"
            )

        # Stop if no more pages
        if not has_next_page:
            print(f"✅ No more {item_type} pages - fetch complete")
            break

        # Move to next page (always update cursor regardless of processing)
        cursor = next_cursor
        page_num += 1

    return total_processed, total_comments, total_cross_refs


def fetch_issues(
    repo: str,
    include_closed: bool = True,
    limit: int | None = None,
    start_date: str | None = None,
    refetch: bool = False,
    mode: str = "update",
    issue_numbers: list[int] | None = None,
    item_types: str = "both",
    config: dict[str, Any] | None = None,
    **kwargs: Any,  # Backward compatibility for unused params
) -> list[dict[str, Any]]:
    """Fetch issues from GitHub using Issues API with intelligent page-based processing.

    Args:
        repo: GitHub repository in owner/repo format
        include_closed: Whether to include closed issues
        limit: Maximum number of issues to process (for testing)
        start_date: Start date in YYYY-MM-DD format
        refetch: Whether to refetch all issues from start date
        mode: Either 'create' or 'update'
            - 'create': Sort by created date, use start_date as since, avoid re-pulling existing issues
            - 'update': Pull from last updated date in database
        issue_numbers: Specific issue numbers to refetch (always refetches even if they exist)
        item_types: What to fetch - 'issues', 'prs', or 'both' (default)
    """

    # Handle specific issue numbers if provided
    if issue_numbers:
        print(f"🚀 Starting specific issue fetch for {repo}")
        specific_issues = fetch_specific_issues(repo, issue_numbers, config)

        # Load and return all issues in database
        try:
            final_issues = load_issues(repo, config)
            print("\n📋 Specific issue fetch complete:")
            print(f"  🎯 Fetched {len(specific_issues)} specific issues")
            print(f"  📁 Total issues in database: {len(final_issues)}")
            return final_issues
        except Exception as e:
            print(f"⚠️  Could not load final results: {e}")
            return specific_issues

    print(f"🚀 Starting Issues API fetch for {repo} in '{mode}' mode")

    # Parse start_date if provided
    start_datetime = None
    if start_date:
        try:
            start_datetime = datetime.fromisoformat(start_date + "T00:00:00+00:00")
        except ValueError as e:
            raise ValueError(
                f"Invalid start_date format: {start_date}. Expected YYYY-MM-DD"
            ) from e

    # Get existing issue numbers for create mode filtering
    existing_numbers = set() if refetch else get_existing_issue_numbers(repo, config)

    # Analyze existing database coverage
    coverage = None if refetch else get_database_coverage(repo, mode, config)

    if mode == "create":
        # CREATE MODE: Use start_date as since, avoid re-pulling existing issues
        if start_datetime:
            print(f"📅 CREATE mode: Using start_date as since: {start_datetime.date()}")
            if existing_numbers:
                print(f"📊 Will skip {len(existing_numbers)} existing issues")
        else:
            if coverage:
                earliest, latest = coverage
                print(
                    f"📊 Existing database covers: {earliest.date()} to {latest.date()}"
                )
                print(
                    f"📅 CREATE mode: Using earliest created date as since: {earliest.date()}"
                )
            else:
                print("📊 CREATE mode: No existing database - will fetch all issues")
    else:
        # UPDATE MODE: Pull from last updated date in database
        if refetch and start_datetime:
            # If refetch with start_date, use start_date
            print(
                f"📅 UPDATE mode (refetch): Using start_date as since: {start_datetime.date()}"
            )
        else:
            # Use last updated date from database
            last_updated = get_last_updated_date(repo, config)
            if last_updated:
                print(
                    f"📅 UPDATE mode: Using last updated date as since: {last_updated.date()}"
                )
            elif start_datetime:
                print(
                    f"📅 UPDATE mode: No existing database, using start_date as since: {start_datetime.date()}"
                )
            else:
                print(
                    "📊 UPDATE mode: No existing database or start_date - will fetch all issues"
                )

    if coverage:
        earliest, latest = coverage
        print(f"📊 Existing database coverage: {earliest.date()} to {latest.date()}")

    # Initialize counters
    total_processed = 0
    total_comments = 0
    total_cross_refs = 0

    # Determine which API to use based on mode
    if mode == "update":
        # UPDATE MODE: Use REST API with since parameter for efficiency
        if refetch and start_datetime:
            since_date = start_datetime
        else:
            since_date = get_last_updated_date(repo, config)
            # Add 1-week overlap before last updatedAt to ensure coverage
            if since_date:
                since_date = since_date - timedelta(weeks=1)
                print("📅 Added 1-week overlap before last updated date for comprehensive coverage")

        if since_date:
            print("🚀 UPDATE mode: Using REST API with since parameter")

            # GitHub Issues API returns both issues and PRs, so fetch once
            print("\n🔍 Fetching issues and pull requests together (Issues API returns both)...")
            items_processed = fetch_items_with_rest_since(
                repo, "issues", include_closed, since_date, config
            )
            total_processed += items_processed[0]
            total_comments += items_processed[1]
            total_cross_refs += items_processed[2]
        else:
            print("⚠️  UPDATE mode: No since date available, falling back to GraphQL (fetch all)")
            # Fall back to GraphQL pagination without existing_numbers filtering for update mode
            if item_types in ("issues", "both"):
                print("\n🔍 Fetching issues...")
                issues_processed = fetch_items_with_pagination(
                    repo, "issues", include_closed, set(), coverage, mode, config
                )
                total_processed += issues_processed[0]
                total_comments += issues_processed[1]
                total_cross_refs += issues_processed[2]
            else:
                print(f"\n⏭️  Skipping issues (item_types={item_types})")

            if item_types in ("prs", "both"):
                print("\n🔍 Fetching pull requests...")
                prs_processed = fetch_items_with_pagination(
                    repo, "pull_requests", include_closed, set(), coverage, mode, config
                )
                total_processed += prs_processed[0]
                total_comments += prs_processed[1]
                total_cross_refs += prs_processed[2]
            else:
                print(f"\n⏭️  Skipping pull requests (item_types={item_types})")
    else:
        # CREATE/REFETCH MODE: Use GraphQL pagination (fetch all issues)
        print(f"🚀 {mode.upper()} mode: Using GraphQL pagination")

        # For create mode, filter existing issues; for refetch mode, don't filter
        filter_existing = existing_numbers if mode == "create" else set()

        # Fetch issues if requested
        if item_types in ("issues", "both"):
            print("\n🔍 Fetching issues...")
            issues_processed = fetch_items_with_pagination(
                repo, "issues", include_closed, filter_existing, coverage, mode, config
            )
            total_processed += issues_processed[0]
            total_comments += issues_processed[1]
            total_cross_refs += issues_processed[2]
        else:
            print(f"\n⏭️  Skipping issues (item_types={item_types})")

        # Fetch PRs if requested
        if item_types in ("prs", "both"):
            print("\n🔍 Fetching pull requests...")
            prs_processed = fetch_items_with_pagination(
                repo, "pull_requests", include_closed, filter_existing, coverage, mode, config
            )
            total_processed += prs_processed[0]
            total_comments += prs_processed[1]
            total_cross_refs += prs_processed[2]
        else:
            print(f"\n⏭️  Skipping pull requests (item_types={item_types})")

    # Load final results
    try:
        final_issues = load_issues(repo, config)
        print("\n📋 Final results:")
        print(f"  📁 Total items in database: {len(final_issues)}")
        print(f"  ✅ Processed this run: {total_processed}")
        print(f"  💬 Comments fetched: {total_comments}")
        print(f"  🔗 Cross-references fetched: {total_cross_refs}")
        print("  💾 Each item saved to database immediately after processing")

        return final_issues
    except Exception as e:
        print(f"⚠️  Could not load final results: {e}")
        return []
