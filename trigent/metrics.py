"""Shared metrics calculation functions."""


def calculate_priority_score(
    severity: str,
    frequency: str,
    prevalence: str,
    solution_complexity: str,
    solution_risk: str,
) -> int:
    """
    Calculate priority score for a recommendation.

    Higher severity, frequency, and prevalence increase priority.
    Higher complexity and risk decrease priority (inverted).

    Returns a score from 5-15 based on simple addition.
    """
    # Map text values to numeric scores
    severity_map = {"low": 1, "medium": 2, "high": 3}
    frequency_map = {"low": 1, "medium": 2, "high": 3}
    prevalence_map = {"low": 1, "medium": 2, "high": 3}
    complexity_map = {"low": 3, "medium": 2, "high": 1}  # Inverted
    risk_map = {"low": 3, "medium": 2, "high": 1}  # Inverted

    # Get scores with defaults
    severity_score = severity_map.get(severity.lower(), 2)
    frequency_score = frequency_map.get(frequency.lower(), 2)
    prevalence_score = prevalence_map.get(prevalence.lower(), 2)
    complexity_score = complexity_map.get(solution_complexity.lower(), 2)
    risk_score = risk_map.get(solution_risk.lower(), 2)

    # Simple sum of all scores (range 5-15)
    return (
        severity_score
        + frequency_score
        + prevalence_score
        + complexity_score
        + risk_score
    )


def get_recommendation_priority_score(recommendation: dict) -> int:
    """
    Get priority score from a recommendation, calculating if needed.

    Args:
        recommendation: Dictionary containing recommendation data

    Returns:
        Priority score (5-15)
    """
    # Return existing score if present
    if "priority_score" in recommendation:
        return recommendation["priority_score"]

    # Otherwise calculate from analysis fields
    analysis = recommendation.get("analysis", {})

    return calculate_priority_score(
        analysis.get("severity", "medium"),
        analysis.get("frequency", "medium"),
        analysis.get("prevalence", "medium"),
        analysis.get("solution_complexity", "medium"),
        analysis.get("solution_risk", "medium"),
    )
