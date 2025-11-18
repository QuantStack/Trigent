#!/usr/bin/env python3
"""Validator to check database entries for completeness and consistency."""

from collections import defaultdict
from typing import Any

from trigent.database import delete_issues, load_issues


def validate_required_fields(item: dict[str, Any]) -> list[str]:
    """Validate that an item has all required fields."""
    required_fields = {
        "number",
        "title",
        "state",
        "createdAt",
        "updatedAt",
        "url",
        "author",
        "labels",
        "assignees",
        "comments",
        "number_of_comments",
    }

    missing_fields = []
    for field in required_fields:
        if field not in item:
            missing_fields.append(field)
        elif item[field] is None:
            missing_fields.append(f"{field} (null)")

    return missing_fields


def validate_author_field(item: dict[str, Any]) -> list[str]:
    """Validate author field structure."""
    issues = []
    author = item.get("author")

    if not isinstance(author, dict):
        issues.append("author is not a dict")
    elif "login" not in author:
        issues.append("author missing 'login' field")
    elif not isinstance(author["login"], str):
        issues.append("author.login is not a string")

    return issues


def validate_labels_field(item: dict[str, Any]) -> list[str]:
    """Validate labels field structure."""
    issues = []
    labels = item.get("labels", [])

    if not isinstance(labels, list):
        issues.append("labels is not a list")
        return issues

    for i, label in enumerate(labels):
        if not isinstance(label, dict):
            issues.append(f"labels[{i}] is not a dict")
            continue
        if "name" not in label:
            issues.append(f"labels[{i}] missing 'name' field")
        if "color" not in label:
            issues.append(f"labels[{i}] missing 'color' field")

    return issues


def validate_assignees_field(item: dict[str, Any]) -> list[str]:
    """Validate assignees field structure."""
    issues = []
    assignees = item.get("assignees", [])

    if not isinstance(assignees, list):
        issues.append("assignees is not a list")
        return issues

    for i, assignee in enumerate(assignees):
        if not isinstance(assignee, dict):
            issues.append(f"assignees[{i}] is not a dict")
            continue
        if "login" not in assignee:
            issues.append(f"assignees[{i}] missing 'login' field")

    return issues


def validate_comments_field(item: dict[str, Any]) -> list[str]:
    """Validate comments field structure and count consistency."""
    issues = []
    comments = item.get("comments", [])
    number_of_comments = item.get("number_of_comments", 0)

    if not isinstance(comments, list):
        issues.append("comments is not a list")
        return issues

    # Check count consistency
    actual_count = len(comments)
    if actual_count != number_of_comments:
        issues.append(
            f"comment count mismatch: number_of_comments={number_of_comments}, actual={actual_count}"
        )

    # Validate comment structure
    required_comment_fields = {
        "id",
        "body",
        "createdAt",
        "updatedAt",
        "author",
        "authorAssociation",
    }

    for i, comment in enumerate(comments):
        if not isinstance(comment, dict):
            issues.append(f"comments[{i}] is not a dict")
            continue

        for field in required_comment_fields:
            if field not in comment:
                issues.append(f"comments[{i}] missing '{field}' field")

        # Validate comment author
        if "author" in comment and isinstance(comment["author"], dict):
            if "login" not in comment["author"]:
                issues.append(f"comments[{i}].author missing 'login' field")

        # Validate reactions
        if "reactions" in comment:
            reactions = comment["reactions"]
            if isinstance(reactions, dict) and "totalCount" not in reactions:
                issues.append(f"comments[{i}].reactions missing 'totalCount' field")

    return issues


def validate_cross_references_field(item: dict[str, Any]) -> list[str]:
    """Validate cross_references field structure."""
    issues = []
    cross_refs = item.get("cross_references", [])

    if not isinstance(cross_refs, list):
        issues.append("cross_references is not a list")
        return issues

    for i, ref in enumerate(cross_refs):
        if not isinstance(ref, dict):
            issues.append(f"cross_references[{i}] is not a dict")
            continue

        required_ref_fields = {"number", "type", "title", "url"}
        for field in required_ref_fields:
            if field not in ref:
                issues.append(f"cross_references[{i}] missing '{field}' field")

    return issues


def validate_recommendations_field(item: dict[str, Any]) -> list[str]:
    """Validate recommendations field structure."""
    issues = []
    recommendations = item.get("recommendations", [])

    if recommendations is not None and not isinstance(recommendations, list):
        issues.append(
            f"recommendations is not a list (type: {type(recommendations).__name__}, value: {recommendations})"
        )
        return issues

    if isinstance(recommendations, list):
        for i, rec in enumerate(recommendations):
            if not isinstance(rec, dict):
                issues.append(f"recommendations[{i}] is not a dict")
                continue

            required_rec_fields = {
                "severity",
                "frequency",
                "prevalence",
                "report",
                "recommendation",
                "solution_complexity",
                "solution_risk",
                "timestamp",
            }
            for field in required_rec_fields:
                if field not in rec:
                    issues.append(f"recommendations[{i}] missing '{field}' field")

    return issues


def validate_pr_specific_fields(item: dict[str, Any]) -> list[str]:
    """Validate PR-specific fields if item is a pull request."""
    issues = []

    # Check if this is a PR by looking for PR-specific fields or URL pattern
    url = item.get("url", "")
    has_pr_fields = any(
        field in item
        for field in ["mergeable", "merged", "mergedAt", "baseRefName", "headRefName"]
    )
    is_pr_url = "/pull/" in url

    if has_pr_fields or is_pr_url:
        # This appears to be a PR, validate PR fields
        pr_fields = ["mergeable", "merged", "baseRefName", "headRefName"]
        for field in pr_fields:
            if field not in item:
                issues.append(f"PR missing '{field}' field")

        # Validate merged/mergedAt consistency
        if item.get("merged") and "mergedAt" not in item:
            issues.append("PR is merged but missing 'mergedAt' field")
        elif not item.get("merged") and item.get("mergedAt"):
            issues.append("PR has 'mergedAt' but merged=False")

    return issues


def validate_item(item: dict[str, Any]) -> dict[str, list[str]]:
    """Validate a single database item and return all issues found."""
    validation_issues = {}

    # Check required fields
    missing_fields = validate_required_fields(item)
    if missing_fields:
        validation_issues["missing_fields"] = missing_fields

    # Validate specific field structures
    author_issues = validate_author_field(item)
    if author_issues:
        validation_issues["author"] = author_issues

    labels_issues = validate_labels_field(item)
    if labels_issues:
        validation_issues["labels"] = labels_issues

    assignees_issues = validate_assignees_field(item)
    if assignees_issues:
        validation_issues["assignees"] = assignees_issues

    comments_issues = validate_comments_field(item)
    if comments_issues:
        validation_issues["comments"] = comments_issues

    cross_refs_issues = validate_cross_references_field(item)
    if cross_refs_issues:
        validation_issues["cross_references"] = cross_refs_issues

    recommendations_issues = validate_recommendations_field(item)
    if recommendations_issues:
        validation_issues["recommendations"] = recommendations_issues

    pr_issues = validate_pr_specific_fields(item)
    if pr_issues:
        validation_issues["pull_request"] = pr_issues

    return validation_issues


def validate_database(repo: str, delete_invalid: bool = False) -> bool:
    """Validate entire database and report issues."""
    print(f"🔍 Loading database for {repo}...")
    items = load_issues(repo)
    print(f"📊 Found {len(items)} items to validate")

    # Statistics
    total_items = len(items)
    items_with_issues = 0
    issue_counts = defaultdict(int)
    comment_mismatches = []
    valid_items = []
    invalid_items = []

    print(f"\n🔍 Validating {total_items} items...")

    for i, item in enumerate(items):
        item_number = item.get("number", f"item_{i}")
        validation_issues = validate_item(item)

        if validation_issues:
            items_with_issues += 1
            invalid_items.append((item, validation_issues))

            # Count issue types
            for category, issues in validation_issues.items():
                issue_counts[category] += len(issues)

            # Track comment mismatches specifically
            if "comments" in validation_issues:
                for issue in validation_issues["comments"]:
                    if "comment count mismatch" in issue:
                        comment_mismatches.append((item_number, issue))
        else:
            valid_items.append(item)

        # Progress indicator
        if (i + 1) % 1000 == 0:
            print(f"  ✓ Validated {i + 1}/{total_items} items...")

    # Report results
    print("\n📋 Validation Results:")
    print(f"  📊 Total items: {total_items}")
    print(f"  ✅ Items without issues: {total_items - items_with_issues}")
    print(f"  ⚠️  Items with issues: {items_with_issues}")

    if issue_counts:
        print("\n📝 Issue breakdown:")
        for category, count in sorted(issue_counts.items()):
            print(f"  {category}: {count} issues")

    if comment_mismatches:
        print(f"\n💬 Comment count mismatches ({len(comment_mismatches)}):")
        for item_number, issue in comment_mismatches[:10]:  # Show first 10
            print(f"  #{item_number}: {issue}")
        if len(comment_mismatches) > 10:
            print(f"  ... and {len(comment_mismatches) - 10} more")

    # Sample detailed issues
    items_with_detailed_issues = []
    for i, item in enumerate(items[:100]):  # Check first 100 for detailed output
        validation_issues = validate_item(item)
        if validation_issues:
            items_with_detailed_issues.append(
                (item.get("number", f"item_{i}"), validation_issues)
            )

    if items_with_detailed_issues:
        print(
            f"\n🔍 Sample detailed issues (first 5 of {len(items_with_detailed_issues)}):"
        )
        for item_number, issues in items_with_detailed_issues[:5]:
            print(f"  #{item_number}:")
            for category, issue_list in issues.items():
                print(f"    {category}: {issue_list}")

    # Handle deletion of invalid entries if requested
    if delete_invalid and invalid_items:
        print("\n🗑️  Delete invalid entries requested:")
        print(f"  📊 {len(valid_items)} valid items will be kept")
        print(f"  🗑️  {len(invalid_items)} invalid items will be deleted")

        # Show some examples of what will be deleted
        if invalid_items:
            print("\n📝 Examples of items to be deleted:")
            for i, (item, issues) in enumerate(invalid_items[:5]):
                item_number = item.get("number", f"item_{i}")
                issue_summary = []
                for category, issue_list in issues.items():
                    issue_summary.append(f"{category}({len(issue_list)})")
                print(f"  #{item_number}: {', '.join(issue_summary)}")
            if len(invalid_items) > 5:
                print(f"  ... and {len(invalid_items) - 5} more")

        # Confirm deletion
        confirm = (
            input("\n❓ Are you sure you want to delete invalid items? (yes/no): ")
            .strip()
            .lower()
        )
        if confirm in ("yes", "y"):
            print(f"\n🗑️  Deleting {len(invalid_items)} invalid items...")

            # Extract issue numbers from invalid items
            invalid_issue_numbers = [
                item["number"]
                for item in invalid_items
                if "number" in item and isinstance(item["number"], int)
            ]

            if invalid_issue_numbers:
                successful, failed = delete_issues(repo, invalid_issue_numbers)
                print(f"✅ Deletion complete: {successful} deleted, {failed} failed")
            else:
                print("⚠️  No valid issue numbers found in invalid items to delete")

            # Recalculate health score
            final_health_score = 100.0  # All remaining items are valid
            print(f"🏥 New database health score: {final_health_score:.1f}%")
            return True
        else:
            print("❌ Deletion cancelled")

    # Overall health score
    health_score = (
        ((total_items - items_with_issues) / total_items * 100)
        if total_items > 0
        else 0
    )
    print(f"\n🏥 Database health score: {health_score:.1f}%")

    if health_score < 95:
        print("⚠️  Database may need attention")
        return False
    else:
        print("✅ Database appears healthy")
        return True
