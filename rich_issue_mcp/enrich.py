#!/usr/bin/env python3
"""Main enrichment module for processing raw GitHub issues."""

import hashlib
import json
import re
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd
import requests
from sklearn.neighbors import NearestNeighbors

from rich_issue_mcp.config import get_cache


def _get_cache_key(content: str, model: str) -> str:
    """Generate cache key from content and model hash."""
    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return f"{model}:{content_hash}"


def _sanitize_content(content: str) -> str:
    """Sanitize content for API requests using built-in methods."""
    # Remove null bytes and other problematic characters
    content = content.replace("\x00", "").replace("\ufeff", "")

    # Replace control characters (except common whitespace) with spaces
    sanitized = "".join(c if c in "\t\n\r" or ord(c) >= 32 else " " for c in content)

    # Clean up whitespace
    sanitized = " ".join(sanitized.split())

    # Truncate if too long
    if len(sanitized) > 50000:
        sanitized = sanitized[:50000] + "..."

    return sanitized


def get_mistral_embedding(
    content: str, api_key: str, model: str = "mistral-embed"
) -> list[float] | None:
    """Get embedding from Mistral API with caching."""
    if not content.strip():
        return None

    # Sanitize content for API
    sanitized_content = _sanitize_content(content)
    if not sanitized_content.strip():
        return None

    # Check cache first (use original content for cache key to avoid duplicates)
    cache_key = _get_cache_key(content, model)
    cache = get_cache()
    cached_embedding = cache.get(cache_key)
    if cached_embedding is not None:
        print("📦 Cache hit for embedding")
        return cached_embedding

    try:
        payload = {"model": model, "input": [sanitized_content]}

        response = requests.post(
            "https://api.mistral.ai/v1/embeddings",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=30,
        )
        response.raise_for_status()
        embedding = response.json()["data"][0]["embedding"]

        # Cache the result
        cache.set(cache_key, embedding)
        print("💾 Cached embedding for content")

        return embedding
    except Exception as e:
        print(f"❌ API call failed for content length {len(sanitized_content)}: {e}")
        # Try with just title if content is too long
        if len(sanitized_content) > 20000:
            print("🔄 Retrying with title only...")
            try:
                title_only = _sanitize_content(content.split("\n")[0])
                if title_only and len(title_only) < 1000:
                    payload = {"model": model, "input": [title_only]}
                    response = requests.post(
                        "https://api.mistral.ai/v1/embeddings",
                        headers={
                            "Authorization": f"Bearer {api_key}",
                            "Content-Type": "application/json",
                        },
                        json=payload,
                        timeout=30,
                    )
                    response.raise_for_status()
                    embedding = response.json()["data"][0]["embedding"]
                    cache.set(cache_key, embedding)
                    print("💾 Cached title-only embedding")
                    return embedding
            except Exception as retry_e:
                print(f"❌ Title-only retry also failed: {retry_e}")
        return None


def get_mistral_completion(
    prompt: str, api_key: str, model: str = "mistral-small"
) -> str | None:
    """Get completion from Mistral API with caching."""
    if not prompt.strip():
        return None

    # Check cache first
    cache_key = _get_cache_key(prompt, model)
    cache = get_cache()
    cached_completion = cache.get(cache_key)
    if cached_completion is not None:
        print("📦 Cache hit for completion")
        return cached_completion

    try:
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 500,
            "temperature": 0.1,
        }

        response = requests.post(
            "https://api.mistral.ai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=30,
        )
        response.raise_for_status()
        completion = response.json()["choices"][0]["message"]["content"]

        # Cache the result
        cache.set(cache_key, completion)
        print("💾 Cached completion")

        return completion
    except Exception as e:
        print(f"❌ API call failed: {e}")
        return None


def get_issue_embedding(
    issue: dict[str, Any], api_key: str | None, model: str
) -> list[float] | None:
    """Get embedding for issue content."""
    if not api_key:
        return None

    # Truncate body and comments to fit within API limits
    title = issue.get("title", "")
    body = issue.get("body", "") or ""
    if len(body) > 15000:  # Reduced from 30000
        body = body[:15000] + "... [truncated]"

    # Limit comments to prevent excessive length
    comments = issue.get("comments", [])
    comment_texts = []
    total_comment_length = 0
    for comment in comments:
        comment_body = comment.get("body", "") or ""
        if total_comment_length + len(comment_body) > 8000:  # Reduced from 15000
            comment_texts.append("[... more comments truncated]")
            break
        comment_texts.append(comment_body)
        total_comment_length += len(comment_body)

    content_parts = [
        title,
        body,
        "\n".join(comment_texts),
    ]

    content = "\n".join(content_parts).strip()

    if not content:
        return None

    return get_mistral_embedding(content, api_key, model)


def get_issue_summary(
    issue: dict[str, Any], api_key: str | None, model: str = "mistral-small"
) -> str | None:
    """Generate a summary for the issue including metrics analysis."""
    if not api_key:
        return None

    # Create a compact, LLM-friendly representation of the issue
    compact_issue = {
        "number": issue.get("number"),
        "url": issue.get("url"),
        "title": issue.get("title"),
        "conversation": issue.get("conversation"),
        "author": issue.get("author", {}).get("login"),
        "updatedAt": issue.get("updatedAt"),
        "labels": [label.get("name") for label in issue.get("labels", [])],
        "state": issue.get("state"),
        "age_days": issue.get("age_days"),
        "age_days_quartile": issue.get("age_days_quartile"),
        "comment_count": issue.get("comment_count"),
        "comment_count_quartile": issue.get("comment_count_quartile"),
        "engagements": issue.get("engagements"),
        "engagements_quartile": issue.get("engagements_quartile"),
        "engagements_per_day": issue.get("engagements_per_day"),
        "engagements_per_day_quartile": issue.get("engagements_per_day_quartile"),
        "body_emojis": issue.get("body_emojis"),
        "body_emojis_quartile": issue.get("body_emojis_quartile"),
        "comment_emojis": issue.get("comment_emojis"),
        "comment_emojis_quartile": issue.get("comment_emojis_quartile"),
        "total_emojis": issue.get("total_emojis"),
        "total_emojis_quartile": issue.get("total_emojis_quartile"),
    }

    issue_json = json.dumps(
        compact_issue, indent=None, separators=(",", ":"), default=str
    )

    prompt = f"""Analyze this GitHub issue and write a concise 3 sentence summary:
- The main problem or request, NOT restating issue number or url.
- Key discussion points and current status (open, fixed & closed, not fixed & closed, etc)
- Community engagement using engagement, age, comment and emoji metrics and their associated quartiles fields.

Issue:
{issue_json}
"""

    return get_mistral_completion(prompt, api_key, model)


def calc_comment_count(issue: dict[str, Any]) -> int:
    """Calculate number of comments on issue."""
    return len(issue.get("comments", []))


def calc_reaction_totals(reaction_groups: list[dict[str, Any]]) -> int:
    """Calculate total reactions from reaction groups."""
    return sum(r.get("users", {}).get("totalCount", 0) for r in reaction_groups)


def format_emoji_counts(reaction_groups: list[dict[str, Any]]) -> str:
    """Format emoji reaction counts for conversation column."""
    if not reaction_groups:
        return ""

    # Map GitHub reaction content to actual emoji symbols
    emoji_map = {
        "THUMBS_UP": "👍",
        "THUMBS_DOWN": "👎",
        "LAUGH": "😄",
        "HOORAY": "🎉",
        "CONFUSED": "😕",
        "HEART": "❤️",
        "ROCKET": "🚀",
        "EYES": "👀"
    }

    emoji_counts = []
    for reaction in reaction_groups:
        content = reaction.get("content", "")
        count = reaction.get("users", {}).get("totalCount", 0)
        if count > 0:
            emoji = emoji_map.get(content, content)
            emoji_counts.append(f"{emoji} {count}")

    return f" [{', '.join(emoji_counts)}]" if emoji_counts else ""


def format_date(date_str: str | None) -> str:
    """Format a date string to YYYY-MM-DD format."""
    if not date_str:
        return ""
    try:
        date_obj = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        return date_obj.strftime("%Y-%m-%d")
    except (ValueError, AttributeError):
        return ""


def create_conversation_column(issue: dict[str, Any]) -> str:
    """Create a conversation column that combines title, body, and comments with emoji counts."""
    parts = []

    # Add title
    title = issue.get("title", "").strip()
    if title:
        parts.append(title)

    # Add body with author login (truncate if too long)
    body = issue.get("body", "")
    author_login = issue.get("author", {}).get("login", "unknown")
    issue_date = format_date(issue.get("createdAt"))
    if body and body.strip():
        # Truncate body for conversation column
        if len(body) > 20000:
            body = body[:20000] + "... [truncated]"
        # Include date in the body display
        if issue_date:
            body_part = f"{author_login} ({issue_date}): {body.strip()}"
        else:
            body_part = f"{author_login}: {body.strip()}"
        # Add issue-level emoji counts
        emoji_counts = format_emoji_counts(issue.get("reactionGroups", []))
        body_part += emoji_counts
        parts.append(body_part)

    # Add comments with author login and emoji counts (truncate individually)
    comments = issue.get("comments", [])
    total_comment_chars = 0
    for comment in comments:
        comment_body = comment.get("body", "")
        comment_author = comment.get("author", {}).get("login", "unknown")
        comment_date = format_date(comment.get("createdAt"))
        if comment_body and comment_body.strip():
            # Truncate individual comments if too long
            if len(comment_body) > 5000:
                comment_body = comment_body[:5000] + "... [truncated]"

            # Stop adding comments if total gets too long
            if total_comment_chars + len(comment_body) > 25000:
                parts.append("[... more comments truncated for conversation]")
                break

            # Include date in the comment display
            if comment_date:
                comment_part = f"{comment_author} ({comment_date}): {comment_body.strip()}"
            else:
                comment_part = f"{comment_author}: {comment_body.strip()}"
            # Add comment-level emoji counts
            if comment.get("reactionGroups"):
                # Use GraphQL format with detailed emoji breakdown
                emoji_counts = format_emoji_counts(comment.get("reactionGroups", []))
                comment_part += emoji_counts
            else:
                # Fallback to REST API format (total count only)
                reaction_count = comment.get("reactions", {}).get("totalCount", 0)
                if reaction_count > 0:
                    comment_part += f" [👍 {reaction_count}]"
            parts.append(comment_part)
            total_comment_chars += len(comment_body)

    return "\n\n".join(parts)


def calc_reaction_metrics(issue: dict[str, Any]) -> dict[str, int]:
    """Calculate reaction metrics for issue and comments separately."""
    # Handle both GraphQL format (reactionGroups) and REST format (reactions.totalCount)
    issue_reactions = calc_reaction_totals(issue.get("reactionGroups", []))

    # If no reactionGroups (REST API), try to get total from reactions field
    if issue_reactions == 0 and "reactions" in issue:
        issue_reactions = issue.get("reactions", {}).get("totalCount", 0)

    # Calculate comment reactions separately
    comment_reactions_total = 0

    for comment in issue.get("comments", []):
        # Try GraphQL format first
        comment_reactions = calc_reaction_totals(comment.get("reactionGroups", []))

        # If no reactionGroups (REST API), use reactions.totalCount
        if comment_reactions == 0 and "reactions" in comment:
            comment_total = comment.get("reactions", {}).get("totalCount", 0)
            comment_reactions_total += comment_total
        else:
            comment_reactions_total += comment_reactions

    return {
        "body_emojis": issue_reactions,
        "comment_emojis": comment_reactions_total,
        "total_emojis": issue_reactions + comment_reactions_total,
    }


def calc_age_days(issue: dict[str, Any]) -> int:
    """Calculate age in days between creation and last update."""
    created = datetime.fromisoformat(issue["createdAt"].replace("Z", "+00:00"))
    updated = datetime.fromisoformat(issue["updatedAt"].replace("Z", "+00:00"))
    return int((updated - created).days)


def calc_engagements(comment_count: int, total_emojis: int) -> int:
    """Calculate total engagements (comments + reactions)."""
    return comment_count + total_emojis


def calc_engagements_per_day(engagements: int, age_days: int) -> float:
    """Calculate engagements per day from total engagements and age."""
    return engagements / age_days if age_days > 0 else 0.0


def enrich_issue(
    issue: dict[str, Any], api_key: str | None, model: str
) -> dict[str, Any]:
    """Enrich a single issue with additional metrics and embeddings."""
    enriched = issue.copy()

    # Debug: Check issue structure and handle missing keys
    try:
        issue_number = issue['number']
        issue_title = issue.get('title', 'No title')[:50]
        print(f"🔧 Enriching issue #{issue_number}: {issue_title}...")
    except KeyError as e:
        print(f"❌ KeyError in issue data: {e}")
        print(f"📋 Issue keys available: {list(issue.keys())}")
        print(f"📄 Issue document (first 500 chars): {str(issue)[:500]}...")
        raise

    # Initialize recommendations field as empty list if not present
    if "recommendations" not in enriched:
        enriched["recommendations"] = []

    # Add conversation column
    enriched["conversation"] = create_conversation_column(issue)

    # Add embeddings
    enriched["embedding"] = get_issue_embedding(issue, api_key, model)

    # Add metrics
    enriched["comment_count"] = calc_comment_count(issue)

    reactions = calc_reaction_metrics(issue)
    enriched.update(reactions)

    enriched["age_days"] = calc_age_days(issue)
    enriched["engagements"] = calc_engagements(
        enriched["comment_count"], enriched["total_emojis"]
    )
    enriched["engagements_per_day"] = calc_engagements_per_day(
        enriched["engagements"], enriched["age_days"]
    )

    return enriched


def add_quartile_columns(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Add quartile columns for key metrics using pandas qcut."""
    metrics = [
        "comment_count",
        "age_days",
        "engagements",
        "engagements_per_day",
        "body_emojis",
        "comment_emojis",
        "total_emojis",
    ]

    df = pd.DataFrame(issues)

    # Use pandas qcut for clean quartile assignment
    for metric in metrics:
        if metric in df.columns:
            try:
                quartile_col = f"{metric}_quartile"
                df[quartile_col] = pd.qcut(
                    df[metric],
                    q=4,
                    labels=["Bottom25%", "Bottom50%", "Top50%", "Top25%"],
                    duplicates="raise",
                )
            except ValueError:
                # Handle case where all values are the same
                df[f"{metric}_quartile"] = "Top25%"

    return df.to_dict("records")


def add_summaries(
    issues: list[dict[str, Any]], api_key: str | None, model: str = "mistral-small"
) -> list[dict[str, Any]]:
    """Add AI-generated summaries to issues (must run after quartiles are added)."""
    if not api_key:
        print("⚠️  No API key provided, skipping summaries")
        for issue in issues:
            issue["summary"] = None
        return issues

    print(f"📝 Generating summaries for {len(issues)} issues...")

    for issue in issues:
        print(f"🔧 Generating summary for issue #{issue['number']}")
        issue["summary"] = get_issue_summary(issue, api_key, model)

    return issues


def add_k4_distances(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Add k-4 nearest neighbor distances using embeddings."""
    # Filter issues with embeddings
    issues_with_embeddings = [
        issue for issue in issues if issue.get("embedding") is not None
    ]

    if len(issues_with_embeddings) < 5:  # Need at least 5 for k=4 neighbors
        # Add empty k4_distances for all issues
        for issue in issues:
            issue["k4_distances"] = []
        return issues

    # Extract embeddings, issue numbers, and titles
    embeddings = np.array([issue["embedding"] for issue in issues_with_embeddings])
    issue_numbers = [issue["number"] for issue in issues_with_embeddings]
    issue_titles = [issue.get("title", "") for issue in issues_with_embeddings]

    # Create mapping from issue number to title for quick lookup
    issue_title_map = dict(zip(issue_numbers, issue_titles, strict=False))

    # Fit k-nearest neighbors (k=5 to get 4 neighbors excluding self)
    nn = NearestNeighbors(n_neighbors=5, metric="cosine")
    nn.fit(embeddings)

    # Find distances and indices
    distances, indices = nn.kneighbors(embeddings)

    # Create mapping from issue number to k4_distances
    k4_distances_map = {}

    for i, issue_num in enumerate(issue_numbers):
        # Skip first neighbor (self at distance 0) and take next 4
        neighbor_distances = distances[i][1:5]
        neighbor_indices = indices[i][1:5]

        k4_distances = []
        for dist, idx in zip(neighbor_distances, neighbor_indices, strict=False):
            neighbor_issue_num = issue_numbers[idx]
            neighbor_title = issue_title_map[neighbor_issue_num]
            k4_distances.append(
                {
                    "issue_number": neighbor_issue_num,
                    "title": neighbor_title,
                    "distance": float(dist),
                }
            )

        k4_distances_map[issue_num] = k4_distances

    # Add k4_distances to all issues
    for issue in issues:
        issue_num = issue["number"]
        issue["k4_distances"] = k4_distances_map.get(issue_num, [])

    return issues


def print_stats(enriched: list[dict[str, Any]]) -> None:
    """Print statistics about enriched issues."""
    total = len(enriched)
    with_embeddings = sum(1 for issue in enriched if issue.get("embedding") is not None)
    with_summaries = sum(1 for issue in enriched if issue.get("summary") is not None)

    print("📊 Statistics:")
    print(f"  Total issues: {total}")
    print(f"  With embeddings: {with_embeddings}")
    print(f"  With summaries: {with_summaries}")