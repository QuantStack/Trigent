"""FastMCP server for accessing Rich Issues database."""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
from fastmcp import FastMCP

from trigent.database import (
    get_collection_name,
    get_headers,
    get_qdrant_config,
    get_qdrant_url,
    load_issues,
    upsert_issues,
)
from trigent.enrich import get_mistral_embedding
from trigent.metrics import calculate_priority_score

mcp = FastMCP("Rich Issues Server")

# Global config for MCP tools
_mcp_config: dict[str, Any] | None = None


def _get_repo_name(repo: str | None = None) -> str:
    """Get repository name, defaulting to jupyterlab/jupyterlab."""
    return repo or "jupyterlab/jupyterlab"


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Calculate cosine similarity between two embedding vectors."""
    dot_product = sum(x * y for x, y in zip(a, b, strict=False))
    magnitude_a = sum(x * x for x in a) ** 0.5
    magnitude_b = sum(x * x for x in b) ** 0.5
    return (
        dot_product / (magnitude_a * magnitude_b) if magnitude_a and magnitude_b else 0
    )


def _search_similar_in_qdrant(
    repo: str,
    query_vector: list[float],
    threshold: float = 0.8,
    limit: int = 10,
    status: str | None = None,
    config: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Search for similar issues in Qdrant using native vector search."""
    collection_name = get_collection_name(repo, config)
    headers = get_headers()
    timeout = get_qdrant_config()["timeout"]

    # Build filter conditions
    filter_conditions = {"must": []}
    if status:
        filter_conditions["must"].append(
            {"key": "state", "match": {"value": status.upper()}}
        )

    # Prepare search payload
    search_payload = {
        "vector": query_vector,
        "limit": limit,
        "score_threshold": threshold,
        "with_payload": True,
    }

    if filter_conditions["must"]:
        search_payload["filter"] = filter_conditions

    try:
        response = requests.post(
            get_qdrant_url(f"collections/{collection_name}/points/search"),
            json=search_payload,
            headers=headers,
            timeout=timeout,
        )

        if response.status_code == 404:
            return []  # Collection doesn't exist

        response.raise_for_status()
        results = response.json()["result"]

        # Transform results to expected format
        similar = []
        for hit in results:
            payload = hit["payload"]
            similar.append(
                {
                    "number": payload["number"],
                    "title": payload.get("title"),
                    "summary": payload.get("summary"),
                    "url": payload.get("url"),
                    "similarity": hit["score"],
                    "state": payload.get("state"),
                }
            )

        return similar

    except requests.exceptions.RequestException:
        # Fallback to in-memory search
        return None


@mcp.tool()
def get_issue(
    issue_number: int, repo: str | None = None, status: str | None = None
) -> dict[str, Any] | None:
    """Get specific issue summary and number. Optionally filter by status (open/closed)."""
    repo = _get_repo_name(repo)
    config = _mcp_config
    issues = load_issues(repo, config)
    issue = next((i for i in issues if i["number"] == issue_number), None)
    if not issue:
        return None

    # Filter by status if specified
    if status:
        issue_state = issue.get("state", "").lower()
        if status.lower() == "open" and issue_state != "open":
            return None
        elif status.lower() == "closed" and issue_state != "closed":
            return None

    return {
        "number": issue["number"],
        "summary": issue.get("summary"),
        "conversation": issue.get("conversation"),
        "recommendations": issue.get("recommendations", []),
        "state": issue.get("state"),
    }


@mcp.tool()
def find_similar_issues(
    issue_number: int,
    threshold: float = 0.8,
    limit: int = 10,
    repo: str | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    """Find issues similar to target issue using embeddings. Optionally filter by status (open/closed)."""
    repo = _get_repo_name(repo)
    config = _mcp_config

    # First, get the target issue to get its embedding
    issues = load_issues(repo, config)
    target = next((i for i in issues if i["number"] == issue_number), None)

    if not target or not target.get("embedding"):
        return []

    # Try Qdrant native search first
    config = _mcp_config
    qdrant_results = _search_similar_in_qdrant(
        repo,
        target["embedding"],
        threshold,
        limit + 1,
        status,
        config,  # +1 to exclude self
    )

    if qdrant_results is not None:
        # Filter out the target issue itself
        return [r for r in qdrant_results if r["number"] != issue_number][:limit]

    # Fallback to in-memory search
    issues = load_issues(repo, config)
    similar = []
    for issue in issues:
        if issue["number"] == issue_number or not issue.get("embedding"):
            continue

        # Filter by status if specified
        if status:
            issue_state = issue.get("state", "").lower()
            if status.lower() == "open" and issue_state != "open":
                continue
            elif status.lower() == "closed" and issue_state != "closed":
                continue

        similarity = _cosine_similarity(target["embedding"], issue["embedding"])
        if similarity >= threshold:
            result = {
                "number": issue["number"],
                "title": issue.get("title"),
                "summary": issue.get("summary"),
                "url": issue.get("url"),
                "similarity": similarity,
                "state": issue.get("state"),
            }
            similar.append(result)

    return sorted(similar, key=lambda x: x["similarity"], reverse=True)[:limit]


@mcp.tool()
def find_similar_issues_by_text(
    text: str,
    threshold: float = 0.8,
    limit: int = 10,
    repo: str | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    """Find issues similar to given text using embeddings. Optionally filter by status (open/closed)."""
    repo = _get_repo_name(repo)

    # Get Mistral API key from config
    config = _mcp_config
    if not config:
        return []
    api_key = config.get("api", {}).get("mistral_api_key")
    if not api_key:
        return []

    # Generate embedding for the input text
    text_embedding = get_mistral_embedding(text, api_key)
    if not text_embedding:
        return []

    # Try Qdrant native search first
    qdrant_results = _search_similar_in_qdrant(
        repo, text_embedding, threshold, limit, status, config
    )

    if qdrant_results is not None:
        return qdrant_results

    # Fallback to in-memory search
    issues = load_issues(repo, config)
    similar = []
    for issue in issues:
        if not issue.get("embedding"):
            continue

        # Filter by status if specified
        if status:
            issue_state = issue.get("state", "").lower()
            if status.lower() == "open" and issue_state != "open":
                continue
            elif status.lower() == "closed" and issue_state != "closed":
                continue

        similarity = _cosine_similarity(text_embedding, issue["embedding"])
        if similarity >= threshold:
            result = {
                "number": issue["number"],
                "title": issue.get("title"),
                "summary": issue.get("summary"),
                "url": issue.get("url"),
                "similarity": similarity,
                "state": issue.get("state"),
            }
            similar.append(result)

    return sorted(similar, key=lambda x: x["similarity"], reverse=True)[:limit]


@mcp.tool()
def find_cross_referenced_issues(
    issue_number: int, repo: str | None = None, status: str | None = None
) -> list[dict[str, Any]]:
    """Find cross-referenced issues from the target issue. Optionally filter by status (open/closed)."""
    repo = _get_repo_name(repo)
    config = _mcp_config
    issues = load_issues(repo, config)
    target = next((i for i in issues if i["number"] == issue_number), None)

    if not target:
        return []

    cross_refs = target.get("cross_references", [])

    # Filter by status if specified
    if status:
        # Create lookup for issue states
        issue_states = {
            issue["number"]: issue.get("state", "").lower() for issue in issues
        }

        filtered_refs = []
        for ref in cross_refs:
            ref_number = ref.get("number")
            if ref_number and ref_number in issue_states:
                ref_state = issue_states[ref_number]
                if status.lower() == "open" and ref_state == "open":
                    filtered_refs.append(ref)
                elif status.lower() == "closed" and ref_state == "closed":
                    filtered_refs.append(ref)

        return filtered_refs

    return cross_refs


@mcp.tool()
def get_available_sort_columns(repo: str | None = None) -> list[str]:
    """Get list of available columns that can be used for sorting issues."""
    repo = _get_repo_name(repo)
    config = _mcp_config
    issues = load_issues(repo, config)

    if not issues:
        return []

    # Get all available columns from the first issue
    all_columns = list(issues[0].keys())

    # Filter to columns that are likely useful for sorting (numeric, string, not complex objects)
    sortable_columns = []
    sample_issue = issues[0]

    for column in all_columns:
        value = sample_issue.get(column)
        # Include columns with numeric, string, or None values
        # Exclude lists, dicts, and other complex types unless they're specific known ones
        if value is None or isinstance(value, int | float | str | bool):
            sortable_columns.append(column)
        elif column in ["k4_distances"]:  # Skip complex columns we know aren't sortable
            continue
        else:
            # For other types, check if they're consistently comparable across a few samples
            sample_values = [
                issue.get(column)
                for issue in issues[:5]
                if issue.get(column) is not None
            ]
            if sample_values and all(
                isinstance(v, type(sample_values[0])) for v in sample_values
            ):
                try:
                    # Test if values are sortable
                    sorted(sample_values)
                    sortable_columns.append(column)
                except (TypeError, ValueError):
                    continue

    return sorted(sortable_columns)


@mcp.tool()
def get_top_issues(
    sort_column: str,
    limit: int = 10,
    descending: bool = True,
    repo: str | None = None,
) -> list[dict[str, Any]]:
    """Get top n issues sorted by a specific column from the enriched database."""
    repo = _get_repo_name(repo)
    config = _mcp_config
    issues = load_issues(repo, config)

    if not issues:
        return []

    # Validate that the sort column exists
    available_columns = set(issues[0].keys()) if issues else set()
    if sort_column not in available_columns:
        raise ValueError(
            f"Column '{sort_column}' not found. Available columns: {sorted(available_columns)}"
        )

    # Filter out issues that don't have the sort column or have None values
    valid_issues = [issue for issue in issues if issue.get(sort_column) is not None]

    # Sort issues by the specified column
    try:
        sorted_issues = sorted(
            valid_issues, key=lambda x: x[sort_column], reverse=descending
        )
    except TypeError:
        # Handle case where values might not be comparable (mixed types)
        sorted_issues = sorted(
            valid_issues, key=lambda x: str(x[sort_column]), reverse=descending
        )

    return [
        {
            "number": issue["number"],
            "title": issue.get("title"),
            "summary": issue.get("summary"),
            "url": issue.get("url"),
        }
        for issue in sorted_issues[:limit]
    ]


@mcp.tool()
def export_all_open_issues(
    output_path: str,
    repo: str | None = None,
) -> dict[str, Any]:
    """Export all open issues to a JSON file with name, title, url, and summary."""
    repo = _get_repo_name(repo)
    config = _mcp_config
    issues = load_issues(repo, config)

    if not issues:
        return {"status": "error", "message": "No issues found in database"}

    # Filter for open issues (state == "OPEN")
    open_issues = [issue for issue in issues if issue.get("state") == "OPEN"]

    # Create the output data structure
    export_data = []
    for issue in open_issues:
        export_data.append(
            {
                "name": f"#{issue['number']}",
                "title": issue.get("title", ""),
                "url": issue.get("url", ""),
                "summary": issue.get("summary", ""),
            }
        )

    # Write to JSON file
    try:
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)

        with open(output_file, "w") as f:
            json.dump(export_data, f, indent=2)

        return {
            "status": "success",
            "message": f"Exported {len(export_data)} open issues to {output_path}",
            "count": len(export_data),
            "file_path": str(output_file.absolute()),
        }
    except Exception as e:
        return {"status": "error", "message": f"Failed to write file: {e}"}


@mcp.tool()
def add_recommendation(
    issue_number: int,
    recommendation: str,
    confidence: str,
    summary: str,
    rationale: str,
    report: str,
    severity: str,
    frequency: str,
    prevalence: str,
    solution_complexity: str,
    solution_risk: str,
    affected_packages: list[str],
    affected_paths: list[str],
    affected_components: list[str],
    merge_with: list[int],
    relevant_issues: list[dict[str, Any]] | None = None,
    reviewer: str = "ai",
    model_version: str | None = None,
    repo: str | None = None,
) -> dict[str, Any]:
    """Add a recommendation to an issue in the database using the new enhanced schema."""

    # Validate input parameters
    valid_levels = {"low", "medium", "high"}
    valid_recommendations = {
        "close_completed",
        "close_merge",
        "close_not_planned",
        "close_invalid",
        "almost_done",
        "priority_high",
        "priority_medium",
        "priority_low",
        "needs_more_info",
    }

    errors = []
    if recommendation not in valid_recommendations:
        errors.append(
            f"recommendation must be one of: {', '.join(sorted(valid_recommendations))}"
        )
    if confidence not in valid_levels:
        errors.append(f"confidence must be one of: {', '.join(sorted(valid_levels))}")
    if severity not in valid_levels:
        errors.append(f"severity must be one of: {', '.join(sorted(valid_levels))}")
    if frequency not in valid_levels:
        errors.append(f"frequency must be one of: {', '.join(sorted(valid_levels))}")
    if prevalence not in valid_levels:
        errors.append(f"prevalence must be one of: {', '.join(sorted(valid_levels))}")
    if solution_complexity not in valid_levels:
        errors.append(
            f"solution_complexity must be one of: {', '.join(sorted(valid_levels))}"
        )
    if solution_risk not in valid_levels:
        errors.append(
            f"solution_risk must be one of: {', '.join(sorted(valid_levels))}"
        )

    if not isinstance(summary, str) or not summary.strip():
        errors.append("summary must be a non-empty string")
    if not isinstance(rationale, str) or not rationale.strip():
        errors.append("rationale must be a non-empty string")
    if not isinstance(report, str) or not report.strip():
        errors.append("report must be a non-empty string")
    if not isinstance(issue_number, int):
        errors.append("issue_number must be an integer")
    if not isinstance(affected_packages, list):
        errors.append("affected_packages must be a list")
    elif not all(isinstance(pkg, str) for pkg in affected_packages):
        errors.append("affected_packages must be a list of strings")
    if not isinstance(affected_paths, list):
        errors.append("affected_paths must be a list")
    elif not all(isinstance(path, str) for path in affected_paths):
        errors.append("affected_paths must be a list of strings")
    if not isinstance(affected_components, list):
        errors.append("affected_components must be a list")
    elif not all(isinstance(comp, str) for comp in affected_components):
        errors.append("affected_components must be a list of strings")
    if not isinstance(merge_with, list):
        errors.append("merge_with must be a list")
    elif not all(isinstance(issue_id, int) for issue_id in merge_with):
        errors.append("merge_with must be a list of integers")
    if relevant_issues is not None:
        if not isinstance(relevant_issues, list):
            errors.append("relevant_issues must be a list")
        elif not all(
            isinstance(item, dict)
            and "number" in item
            and "title" in item
            and "url" in item
            for item in relevant_issues
        ):
            errors.append(
                "relevant_issues must be a list of dictionaries with keys: number, title, url"
            )

    if errors:
        return {"status": "error", "message": "Validation failed", "errors": errors}

    repo = _get_repo_name(repo)

    try:
        config = _mcp_config
        issues = load_issues(repo, config)
    except Exception as e:
        return {"status": "error", "message": f"Failed to load database: {e}"}

    # Find the issue
    issue = next((i for i in issues if i["number"] == issue_number), None)
    if not issue:
        return {"status": "error", "message": f"Issue #{issue_number} not found"}

    # Ensure recommendations field exists
    if "recommendations" not in issue:
        issue["recommendations"] = []

    # Generate review ID
    import uuid

    review_id = str(uuid.uuid4())

    # Calculate priority score
    priority_score = calculate_priority_score(
        severity, frequency, prevalence, solution_complexity, solution_risk
    )

    # Create new recommendation with enhanced schema
    new_recommendation = {
        "recommendation": recommendation,
        "confidence": confidence,
        "summary": summary.strip(),
        "rationale": rationale.strip(),
        "report": report.strip(),
        "analysis": {
            "severity": severity,
            "frequency": frequency,
            "prevalence": prevalence,
            "solution_complexity": solution_complexity,
            "solution_risk": solution_risk,
        },
        "priority_score": priority_score,
        "context": {
            "affected_packages": affected_packages,
            "affected_paths": affected_paths,
            "affected_components": affected_components,
            "merge_with": merge_with,
            "relevant_issues": relevant_issues or [],
        },
        "meta": {
            "reviewer": reviewer,
            "timestamp": datetime.now().isoformat(),
            "model_version": model_version,
            "review_id": review_id,
        },
    }

    # Add recommendation
    issue["recommendations"].append(new_recommendation)
    recommendation_count = len(issue["recommendations"])

    # Save updated issue using individual upsert to preserve other data
    try:
        upsert_issues(repo, [issue], config)

        # Generate ordinal number text
        ordinals = {1: "first", 2: "second", 3: "third", 4: "fourth", 5: "fifth"}
        ordinal_text = ordinals.get(recommendation_count, f"{recommendation_count}th")

        return {
            "status": "success",
            "message": f"Added {ordinal_text} recommendation for issue #{issue_number}",
            "issue_number": issue_number,
            "recommendation_count": recommendation_count,
            "recommendation": new_recommendation,
        }

    except Exception as e:
        return {"status": "error", "message": f"Failed to save database: {e}"}


@mcp.tool()
def get_recommendation_schema() -> dict[str, Any]:
    """Get the complete schema for issue recommendations."""
    return {
        "schema_version": "1.0",
        "description": "Enhanced schema for issue recommendations with structured analysis",
        "fields": {
            "recommendation": {
                "type": "string",
                "required": True,
                "description": "The recommended action to take on the issue",
                "enum": [
                    "close_completed",
                    "close_merge",
                    "close_not_planned",
                    "close_invalid",
                    "almost_done",
                    "priority_high",
                    "priority_medium",
                    "priority_low",
                    "needs_more_info",
                ],
                "enum_descriptions": {
                    "close_completed": "Issue has been completed/fixed",
                    "close_merge": "Issue should be merged with another issue",
                    "close_not_planned": "Valid issue but not aligned with roadmap",
                    "close_invalid": "Invalid issue (spam, off-topic, etc.)",
                    "almost_done": "Issue is nearly complete, needs minor work",
                    "priority_high": "Critical issue needing immediate attention",
                    "priority_medium": "Important issue for next sprint/release",
                    "priority_low": "Valid issue but lower priority",
                    "needs_more_info": "Requires additional details from reporter",
                },
            },
            "confidence": {
                "type": "string",
                "required": True,
                "description": "Confidence level in the recommendation",
                "enum": ["low", "medium", "high"],
            },
            "summary": {
                "type": "string",
                "required": True,
                "description": "Brief one-line summary of the recommendation",
                "example": "Close as duplicate of #123",
            },
            "rationale": {
                "type": "string",
                "required": True,
                "description": "Short explanation for why this action is recommended",
                "example": "Same root cause as #123, already has detailed discussion",
            },
            "report": {
                "type": "string",
                "required": True,
                "description": "Full markdown report with detailed analysis",
                "example": "## Analysis\\n\\nThis issue appears to be...",
            },
            "analysis": {
                "type": "object",
                "required": True,
                "description": "Structured analysis of the issue",
                "properties": {
                    "severity": {
                        "type": "string",
                        "required": True,
                        "description": "Impact on users/system",
                        "enum": ["low", "medium", "high"],
                    },
                    "frequency": {
                        "type": "string",
                        "required": True,
                        "description": "How often the issue occurs",
                        "enum": ["low", "medium", "high"],
                    },
                    "prevalence": {
                        "type": "string",
                        "required": True,
                        "description": "How many users are affected",
                        "enum": ["low", "medium", "high"],
                    },
                    "solution_complexity": {
                        "type": "string",
                        "required": True,
                        "description": "Estimated development effort required",
                        "enum": ["low", "medium", "high"],
                    },
                    "solution_risk": {
                        "type": "string",
                        "required": True,
                        "description": "Risk of implementing solution (breaking changes, etc.)",
                        "enum": ["low", "medium", "high"],
                    },
                },
            },
            "context": {
                "type": "object",
                "required": True,
                "description": "Contextual information about the issue",
                "properties": {
                    "affected_packages": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Code packages/modules affected",
                        "example": ["@jupyterlab/notebook", "@jupyterlab/cells"],
                    },
                    "affected_paths": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Paths affected (files/directories), optionally with line numbers using GitHub syntax (path:line or path:start-end)",
                        "example": [
                            "packages/notebook/src/widget.ts:42",
                            "packages/cells/src/model.ts:123-145",
                            "src/main.ts",
                            "packages/notebook/",
                        ],
                    },
                    "affected_components": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "UI/system components affected",
                        "example": ["NotebookPanel", "CodeCell"],
                    },
                    "merge_with": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "Issue numbers to merge with (for close_merge action)",
                        "example": [456],
                    },
                    "relevant_issues": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "number": {"type": "integer"},
                                "title": {"type": "string"},
                                "url": {"type": "string"},
                            },
                            "required": ["number", "title", "url"],
                        },
                        "description": "Relevant issues identified via cross-references and similar issues",
                        "example": [
                            {
                                "number": 789,
                                "title": "Related keyboard issue",
                                "url": "https://github.com/owner/repo/issues/789",
                            }
                        ],
                    },
                },
            },
            "meta": {
                "type": "object",
                "required": True,
                "description": "Metadata about the recommendation",
                "properties": {
                    "reviewer": {
                        "type": "string",
                        "description": "Who made the recommendation",
                        "default": "ai",
                        "example": "claude-3.5",
                    },
                    "timestamp": {
                        "type": "string",
                        "description": "ISO timestamp when recommendation was made",
                        "format": "iso8601",
                    },
                    "model_version": {
                        "type": "string",
                        "description": "Model version used for analysis",
                        "example": "claude-3.5-sonnet-20241022",
                    },
                    "review_id": {
                        "type": "string",
                        "description": "Unique identifier for this review",
                        "format": "uuid",
                    },
                },
            },
        },
        "example": {
            "recommendation": "close_merge",
            "confidence": "high",
            "summary": "Merge with #123 - same keyboard shortcut issue",
            "rationale": "Both issues describe identical keyboard shortcut conflicts in notebook interface",
            "report": "## Analysis\\n\\nBoth issues #456 and #123 report the same keyboard shortcut conflict...",
            "analysis": {
                "severity": "medium",
                "frequency": "high",
                "prevalence": "low",
                "solution_complexity": "low",
                "solution_risk": "low",
            },
            "context": {
                "affected_packages": ["@jupyterlab/notebook"],
                "affected_paths": [
                    "packages/notebook/src/widget.ts:142-156",
                    "packages/notebook/src/panel.ts:89",
                ],
                "affected_components": ["NotebookPanel"],
                "merge_with": [123],
                "relevant_issues": [
                    {
                        "number": 789,
                        "title": "Related keyboard issue",
                        "url": "https://github.com/jupyterlab/jupyterlab/issues/789",
                    }
                ],
            },
            "meta": {
                "reviewer": "ai",
                "timestamp": "2024-01-15T10:30:00Z",
                "model_version": "claude-3.5-sonnet",
                "review_id": "550e8400-e29b-41d4-a716-446655440000",
            },
        },
    }


@mcp.tool()
def get_first_issue_without_recommendation(
    repo: str | None = None,
    status: str | None = "open",
) -> dict[str, Any] | None:
    """Get the first issue without any recommendations. Defaults to open issues, optionally filter by status (open/closed)."""
    repo = _get_repo_name(repo)
    config = _mcp_config
    issues = load_issues(repo, config)

    if not issues:
        return None

    # Find first issue without recommendations
    for issue in issues:
        # Filter by status if specified
        if status:
            issue_state = issue.get("state", "").lower()
            if status.lower() == "open" and issue_state != "open":
                continue
            elif status.lower() == "closed" and issue_state != "closed":
                continue

        recommendations = issue.get("recommendations", [])
        if not recommendations or len(recommendations) == 0:
            return {
                "number": issue["number"],
                "title": issue.get("title"),
                "summary": issue.get("summary"),
                "url": issue.get("url"),
                "state": issue.get("state"),
                "cross_references": issue.get("cross_references", []),
                "recommendations": recommendations,
            }

    return None


@mcp.tool()
def get_issue_by_difficulty(
    difficulty: str,
    repo: str | None = None,
) -> dict[str, Any] | None:
    """Get an issue by difficulty level based on solution complexity and risk.

    Easy: low solution_complexity AND low solution_risk
    Medium: medium solution_complexity OR medium solution_risk (but not both high)
    Hard: high solution_complexity OR high solution_risk

    Returns the issue with highest engagement (total emojis) for the given difficulty.
    """
    valid_difficulties = {"easy", "medium", "hard"}
    if difficulty not in valid_difficulties:
        return {
            "status": "error",
            "message": f"difficulty must be one of: {', '.join(sorted(valid_difficulties))}",
        }

    repo = _get_repo_name(repo)
    config = _mcp_config
    issues = load_issues(repo, config)

    if not issues:
        return None

    # Filter issues that have recommendations
    issues_with_recommendations = [
        issue
        for issue in issues
        if issue.get("recommendations") and len(issue.get("recommendations", [])) > 0
    ]

    if not issues_with_recommendations:
        return None

    # Categorize issues by difficulty based on their recommendations
    categorized_issues = []

    for issue in issues_with_recommendations:
        recommendations = issue.get("recommendations", [])

        # Get the latest recommendation's complexity and risk
        latest_rec = recommendations[-1]  # Most recent recommendation
        analysis = latest_rec.get("analysis", {})
        complexity = analysis.get("solution_complexity", "").lower()
        risk = analysis.get("solution_risk", "").lower()

        # Categorize based on complexity and risk
        issue_difficulty = None

        if complexity == "low" and risk == "low":
            issue_difficulty = "easy"
        elif complexity == "high" or risk == "high":
            issue_difficulty = "hard"
        else:  # medium complexity/risk or mixed low/medium
            issue_difficulty = "medium"

        if issue_difficulty == difficulty:
            # Calculate engagement score (total emojis)
            engagement_score = issue.get("issue_total_emojis", 0) + issue.get(
                "conversation_total_emojis", 0
            )

            categorized_issues.append(
                {
                    "issue": issue,
                    "engagement_score": engagement_score,
                    "latest_recommendation": latest_rec,
                }
            )

    if not categorized_issues:
        return None

    # Return the issue with highest engagement score
    best_issue_data = max(categorized_issues, key=lambda x: x["engagement_score"])
    issue = best_issue_data["issue"]

    return {
        "number": issue["number"],
        "title": issue.get("title"),
        "summary": issue.get("summary"),
        "url": issue.get("url"),
        "state": issue.get("state"),
        "difficulty": difficulty,
        "engagement_score": best_issue_data["engagement_score"],
        "issue_emojis": issue.get("issue_total_emojis", 0),
        "conversation_emojis": issue.get("conversation_total_emojis", 0),
        "solution_complexity": best_issue_data["latest_recommendation"]
        .get("analysis", {})
        .get("solution_complexity"),
        "solution_risk": best_issue_data["latest_recommendation"]
        .get("analysis", {})
        .get("solution_risk"),
        "recommendation": best_issue_data["latest_recommendation"].get(
            "recommendation"
        ),
        "cross_references": issue.get("cross_references", []),
        "recommendations_count": len(issue.get("recommendations", [])),
    }


def run_mcp_server(
    host: str = "localhost",
    port: int = 8000,
    repo: str | None = None,
    config: dict[str, Any] | None = None,
) -> None:
    """Run the MCP server with specified configuration."""
    repo = _get_repo_name(repo)

    # Store config globally for MCP tools to use
    global _mcp_config
    _mcp_config = config

    print("🚀 Starting MCP server")
    print(f"📂 Using repository: {repo}")

    # Use HTTP transport (SSE) if port is not default 8000
    # Otherwise use stdio transport (default for MCP)
    if port != 8000:
        print(f"🌐 Starting HTTP server on {host}:{port}")
        try:
            mcp.run(transport="sse", host=host, port=port)
        except Exception as e:
            print(f"❌ Failed to start HTTP server: {e}")
            raise
    else:
        print("📡 Using STDIO transport")
        mcp.run()


def main():
    """Main entry point for MCP server."""
    import argparse

    parser = argparse.ArgumentParser(
        description="FastMCP server for accessing Rich Issues database"
    )
    parser.add_argument("--host", default="localhost", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind to")
    parser.add_argument("--repo", help="Repository name")

    args = parser.parse_args()
    run_mcp_server(args.host, args.port, args.repo)


if __name__ == "__main__":
    main()
