"""CSV export functionality."""

import csv
from pathlib import Path

from trigent.database import load_issues
from trigent.metrics import get_recommendation_priority_score


def export_csv(repo: str, output_path: str | None, config: dict) -> None:
    """Export issues with recommendations to CSV."""
    issues = load_issues(repo, config)

    # Filter issues that have at least one recommendation
    issues_with_recs = [
        issue
        for issue in issues
        if issue.get("recommendations") and len(issue.get("recommendations", [])) > 0
    ]

    if not issues_with_recs:
        print("❌ No issues with recommendations found")
        return

    print(f"📝 Found {len(issues_with_recs)} issues with recommendations")

    # Prepare CSV data with flattened first recommendation
    csv_rows = []
    for issue in issues_with_recs:
        first_rec = issue["recommendations"][0]
        analysis = first_rec.get("analysis", {})

        # Create flattened row with key fields
        row = {
            "number": issue.get("number"),
            "title": issue.get("title"),
            "url": issue.get("url"),
            "state": issue.get("state"),
            "author": issue.get("author", {}).get("login", ""),
            "labels": ", ".join(
                [label.get("name", "") for label in issue.get("labels", [])]
            ),
            "comments_count": issue.get("comment_count", 0),
            "recommendation": first_rec.get("recommendation"),
            "confidence": first_rec.get("confidence"),
            "rationale": first_rec.get("rationale"),
            "severity": analysis.get("severity", ""),
            "frequency": analysis.get("frequency", ""),
            "prevalence": analysis.get("prevalence", ""),
            "solution_complexity": analysis.get("solution_complexity", ""),
            "solution_risk": analysis.get("solution_risk", ""),
            "priority_score": get_recommendation_priority_score(first_rec),
        }
        csv_rows.append(row)

    # Write CSV file
    output_file = (
        Path(output_path)
        if output_path
        else Path(f"{repo.replace('/', '_')}_recommendations.csv")
    )
    output_file.parent.mkdir(parents=True, exist_ok=True)

    with open(output_file, "w", newline="", encoding="utf-8") as csvfile:
        if csv_rows:
            writer = csv.DictWriter(csvfile, fieldnames=list(csv_rows[0].keys()))
            writer.writeheader()
            writer.writerows(csv_rows)

    print(f"✅ Exported {len(csv_rows)} issues to {output_file}")
