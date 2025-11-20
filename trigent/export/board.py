"""Export issues to GitHub Project Board."""

import os
from typing import Any

import requests

from trigent.database import load_issues
from trigent.metrics import get_recommendation_priority_score


def _get_github_token(config: dict[str, Any]) -> str:
    """Get GitHub token from config or environment."""
    # Try config first
    if config:
        # Try both locations for token
        token = config.get("github", {}).get("token") or config.get("token")
        if token:
            return str(token)

    # Fall back to environment variable
    token = os.getenv("GITHUB_TOKEN")
    if token:
        return token

    raise ValueError(
        "No GitHub token found. Set token in config.toml, use 'gh auth login', or set GITHUB_TOKEN"
    )


def _graphql_request(
    query: str, config: dict[str, Any], variables: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Make a GraphQL request to GitHub API."""
    token = _get_github_token(config)

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    payload: dict[str, Any] = {"query": query}
    if variables:
        payload["variables"] = variables

    response = requests.post(
        "https://api.github.com/graphql", headers=headers, json=payload, timeout=30
    )

    if response.status_code != 200:
        raise RuntimeError(
            f"GraphQL request failed: {response.status_code} {response.text}"
        )

    data = response.json()
    if "errors" in data:
        raise RuntimeError(f"GraphQL errors: {data['errors']}")

    return data


def export_board(
    repo: str, config: dict[str, Any], project_override: str | None = None
) -> None:
    """
    Export issues to a GitHub Project Board with custom fields.

    Creates or updates a GitHub project board with:
    - One entry per issue, linking to the original
    - Recommendation as board-level select field
    - Severity, frequency, prevalence, solution complexity, solution risk as select fields
    - Priority score as a number column
    """
    # Get board configuration - either from override or config
    if project_override:
        # Parse project override format: "org/project_num", "user/project_num", "owner/repo/project_num"
        # or "org/", "user/", "owner/repo/" to create new board
        try:
            parts = project_override.split("/")
            if len(parts) == 2:
                # Organization or user project: "org/1" or "user/1" or "org/" for new
                org_or_user, project_num_str = parts
                if project_num_str == "":
                    # Create new board
                    project_number = None
                    repository = None
                else:
                    project_number = int(project_num_str)
                    repository = None
            elif len(parts) == 3:
                # Repository project: "owner/repo/1" or "owner/repo/" for new
                owner, repo_name, project_num_str = parts
                repository = f"{owner}/{repo_name}"
                org_or_user = None
                if project_num_str == "":
                    # Create new board
                    project_number = None
                else:
                    project_number = int(project_num_str)
            else:
                raise ValueError("Invalid format")
        except (ValueError, TypeError) as e:
            raise ValueError(
                "Invalid --project format. Use 'org/project_num', 'user/project_num', 'owner/repo/project_num' "
                "or 'org/', 'user/', 'owner/repo/' to create new board (e.g., 'myorg/1' or 'myorg/' for new)"
            ) from e
    else:
        # Use config
        board_config = config.get("board", {})
        org_or_user = board_config.get("org_or_user")
        repository = board_config.get("repository")  # New repository option
        project_number = board_config.get("project_number")

        if (not org_or_user and not repository) or not project_number:
            raise ValueError(
                "Board export requires ('org_or_user' or 'repository') and 'project_number' in [board] config section, "
                "or use --project flag to override (e.g., --project myorg/1)"
            )

    if repository:
        print(
            f"📋 Exporting to Repository Project Board: {repository}/projects/{project_number}"
        )
    else:
        print(
            f"📋 Exporting to GitHub Project Board: {org_or_user}/projects/{project_number}"
        )

    # Load enriched issues
    issues = load_issues(repo, config)
    if not issues:
        print("❌ No issues found in database")
        return

    # Filter to only open issues
    open_issues = [
        issue for issue in issues if issue.get("state", "").lower() == "open"
    ]

    if not open_issues:
        print("❌ No open issues found")
        return

    print(f"📝 Found {len(open_issues)} open issues")

    # Count how many have recommendations
    issues_with_recs = [
        issue
        for issue in open_issues
        if issue.get("recommendations") and len(issue.get("recommendations", [])) > 0
    ]
    print(f"📝 {len(issues_with_recs)} issues have recommendations")

    # Get unique recommendations for the select field
    recommendations = set()
    for issue in issues_with_recs:
        for rec in issue.get("recommendations", []):
            if rec_type := rec.get("recommendation"):
                recommendations.add(rec_type)

    # Get or create project
    if project_number is None:
        # Create new project
        print("📋 Creating new project board...")
        project_title = f"{repo.replace('/', '-')} Issues"
        project_id = _create_project_board(
            org_or_user, repository, project_title, config
        )
        if not project_id:
            print("❌ Failed to create project board")
            return
    else:
        # Get existing project
        project_id = _get_project_id(org_or_user, project_number, repository, config)
        if not project_id:
            if repository:
                print(f"❌ Project {repository}/projects/{project_number} not found")
            else:
                print(f"❌ Project {org_or_user}/projects/{project_number} not found")
            return

    # Ensure custom fields exist
    field_ids = _ensure_custom_fields(project_id, list(recommendations), config)

    # Process each issue
    added_count = 0
    updated_count = 0

    for issue in open_issues:
        # Skip if no number
        if "number" not in issue:
            continue

        # Use the last recommendation (most recent) if available, otherwise None
        recommendations_list = issue.get("recommendations", [])
        last_rec = recommendations_list[-1] if recommendations_list else None

        # Get priority score (will calculate if recommendation exists, otherwise None)
        if last_rec:
            priority_score = get_recommendation_priority_score(last_rec)
        else:
            # No recommendation = no priority score
            priority_score = None

        # Add or update the issue in the project
        is_new = _add_or_update_project_item(
            project_id, repo, issue, last_rec, field_ids, priority_score, config
        )

        if is_new:
            added_count += 1
        else:
            updated_count += 1

    print(f"✅ Board updated: {added_count} new items, {updated_count} updated items")


def _get_project_id(
    org_or_user: str | None,
    project_number: int,
    repository: str | None = None,
    config: dict[str, Any] | None = None,
) -> str | None:
    """Get the GraphQL ID of a project."""
    if config is None:
        return None

    project_data = None

    if repository:
        # Repository project
        owner, repo_name = repository.split("/", 1)
        query = """
        query($owner: String!, $repo: String!, $number: Int!) {
          repository(owner: $owner, name: $repo) {
            projectV2(number: $number) {
              id
              title
            }
          }
        }
        """
        variables = {"owner": owner, "repo": repo_name, "number": project_number}

        try:
            data = _graphql_request(query, config, variables)
            project_data = data.get("data", {}).get("repository", {}).get("projectV2")
        except RuntimeError:
            pass

    else:
        # Organization or user project - try both
        if org_or_user is None:
            return None
        login = org_or_user.split("/")[-1] if "/" in org_or_user else org_or_user

        # Try organization first
        org_query = """
        query($login: String!, $number: Int!) {
          organization(login: $login) {
            projectV2(number: $number) {
              id
              title
            }
          }
        }
        """
        variables = {"login": login, "number": project_number}

        try:
            data = _graphql_request(org_query, config, variables)
            project_data = data.get("data", {}).get("organization", {}).get("projectV2")
        except RuntimeError:
            pass

        # If not found as organization, try as user
        if not project_data:
            user_query = """
            query($login: String!, $number: Int!) {
              user(login: $login) {
                projectV2(number: $number) {
                  id
                  title
                }
              }
            }
            """

            try:
                data = _graphql_request(user_query, config, variables)
                project_data = data.get("data", {}).get("user", {}).get("projectV2")
            except RuntimeError:
                pass

    if project_data:
        print(f"📋 Found project: {project_data['title']}")
        return project_data["id"]

    return None


def _create_project_board(
    org_or_user: str | None, repository: str | None, title: str, config: dict[str, Any]
) -> str | None:
    """Create a new project board and return its ID."""
    if repository:
        # Repository project
        owner, repo_name = repository.split("/", 1)

        # First get repository ID
        repo_query = """
        query($owner: String!, $repo: String!) {
          repository(owner: $owner, name: $repo) {
            id
          }
        }
        """
        variables = {"owner": owner, "repo": repo_name}

        try:
            data = _graphql_request(repo_query, config, variables)
            repo_id = data.get("data", {}).get("repository", {}).get("id")

            if not repo_id:
                print(f"❌ Repository {repository} not found")
                return None
        except RuntimeError as e:
            print(f"❌ Failed to get repository ID: {e}")
            return None

        # Create project mutation
        mutation = """
        mutation($repositoryId: ID!, $title: String!) {
          createProjectV2(input: {
            repositoryId: $repositoryId
            title: $title
          }) {
            projectV2 {
              id
              number
            }
          }
        }
        """
        mutation_variables = {"repositoryId": repo_id, "title": title}

    else:
        # Organization or user project
        if org_or_user is None:
            return None
        login = org_or_user.split("/")[-1] if "/" in org_or_user else org_or_user

        # Try organization first
        org_query = """
        query($login: String!) {
          organization(login: $login) {
            id
          }
        }
        """
        org_variables: dict[str, Any] = {"login": login}

        owner_id = None
        try:
            data = _graphql_request(org_query, config, org_variables)
            owner_id = data.get("data", {}).get("organization", {}).get("id")
        except RuntimeError:
            pass

        # If not found as organization, try as user
        if not owner_id:
            user_query = """
            query($login: String!) {
              user(login: $login) {
                id
              }
            }
            """
            user_variables: dict[str, Any] = {"login": login}

            try:
                data = _graphql_request(user_query, config, user_variables)
                owner_id = data.get("data", {}).get("user", {}).get("id")
            except RuntimeError:
                pass

        if not owner_id:
            print(f"❌ Neither organization nor user '{login}' found")
            return None

        # Create project mutation
        mutation = """
        mutation($ownerId: ID!, $title: String!) {
          createProjectV2(input: {
            ownerId: $ownerId
            title: $title
          }) {
            projectV2 {
              id
              number
            }
          }
        }
        """
        mutation_variables = {"ownerId": owner_id, "title": title}

    # Create the project
    try:
        data = _graphql_request(mutation, config, mutation_variables)
        project_data = data.get("data", {}).get("createProjectV2", {}).get("projectV2")

        if project_data:
            project_id = project_data["id"]
            project_number = project_data["number"]

            if repository:
                print(
                    f"✅ Created repository project board: {repository}/projects/{project_number}"
                )
            else:
                print(
                    f"✅ Created project board: {org_or_user}/projects/{project_number}"
                )

            return project_id

    except RuntimeError as e:
        print(f"❌ Failed to create project: {e}")
        return None

    return None


def _ensure_custom_fields(
    project_id: str, recommendations: list[str], config: dict[str, Any]
) -> dict[str, str]:
    """Ensure all required custom fields exist and return their IDs."""
    field_ids = {}

    # Define fields we need
    select_fields = {
        "Recommendation": recommendations,
        "Severity": ["Low", "Medium", "High"],
        "Frequency": ["Low", "Medium", "High"],
        "Prevalence": ["Low", "Medium", "High"],
        "Solution Complexity": ["Low", "Medium", "High"],
        "Solution Risk": ["Low", "Medium", "High"],
    }

    # Get existing fields
    existing_fields = _get_project_fields(project_id, config)

    # Create missing fields
    for field_name, options in select_fields.items():
        if field_name in existing_fields:
            field_ids[field_name] = existing_fields[field_name]["id"]
            print(f"✓ Found existing field: {field_name}")
        else:
            field_id = _create_select_field(project_id, field_name, options, config)
            if field_id:
                field_ids[field_name] = field_id

    # Handle priority score (number field)
    if "Priority Score" in existing_fields:
        field_ids["Priority Score"] = existing_fields["Priority Score"]["id"]
        print("✓ Found existing field: Priority Score")
    else:
        field_id = _create_number_field(project_id, "Priority Score", config)
        if field_id:
            field_ids["Priority Score"] = field_id

    return field_ids


def _get_project_fields(
    project_id: str, config: dict[str, Any] | None = None
) -> dict[str, dict[str, Any]]:
    """Get all custom fields for a project."""
    if config is None:
        return {}

    query = """
    query($projectId: ID!) {
      node(id: $projectId) {
        ... on ProjectV2 {
          fields(first: 100) {
            nodes {
              ... on ProjectV2Field {
                id
                name
                dataType
              }
              ... on ProjectV2SingleSelectField {
                id
                name
                dataType
                options {
                  id
                  name
                }
              }
            }
          }
        }
      }
    }
    """
    variables = {"projectId": project_id}

    try:
        data = _graphql_request(query, config, variables)
        fields = {}

        for field in (
            data.get("data", {}).get("node", {}).get("fields", {}).get("nodes", [])
        ):
            if field.get("name"):
                fields[field["name"]] = field

        return fields

    except RuntimeError as e:
        print(f"❌ Failed to get fields: {e}")
        return {}


def _create_select_field(
    project_id: str, name: str, options: list[str], config: dict[str, Any]
) -> str | None:
    """Create a single select field with options."""
    mutation = """
    mutation($projectId: ID!, $name: String!, $options: [ProjectV2SingleSelectFieldOptionInput!]!) {
      createProjectV2Field(input: {
        projectId: $projectId
        dataType: SINGLE_SELECT
        name: $name
        singleSelectOptions: $options
      }) {
        projectV2Field {
          ... on ProjectV2SingleSelectField {
            id
          }
        }
      }
    }
    """

    # Format options for GraphQL - GitHub requires color and description fields
    color_map = {"Low": "GRAY", "Medium": "YELLOW", "High": "RED"}

    options_list = [
        {
            "name": opt,
            "color": color_map.get(opt, "GRAY"),
            "description": f"{opt} priority level",
        }
        for opt in options
    ]
    variables = {"projectId": project_id, "name": name, "options": options_list}

    try:
        data = _graphql_request(mutation, config, variables)
        field_id = (
            data.get("data", {})
            .get("createProjectV2Field", {})
            .get("projectV2Field", {})
            .get("id")
        )

        if field_id:
            print(f"✅ Created field '{name}'")

        return field_id

    except RuntimeError as e:
        print(f"❌ Failed to create field '{name}': {e}")
        return None


def _create_number_field(
    project_id: str, name: str, config: dict[str, Any]
) -> str | None:
    """Create a number field."""
    mutation = """
    mutation($projectId: ID!, $name: String!) {
      createProjectV2Field(input: {
        projectId: $projectId
        dataType: NUMBER
        name: $name
      }) {
        projectV2Field {
          ... on ProjectV2Field {
            id
          }
        }
      }
    }
    """

    variables = {"projectId": project_id, "name": name}

    try:
        data = _graphql_request(mutation, config, variables)
        field_id = (
            data.get("data", {})
            .get("createProjectV2Field", {})
            .get("projectV2Field", {})
            .get("id")
        )

        if field_id:
            print(f"✅ Created field '{name}'")

        return field_id

    except RuntimeError as e:
        print(f"❌ Failed to create field '{name}': {e}")
        return None


def _add_or_update_project_item(
    project_id: str,
    repo: str,
    issue: dict[str, Any],
    recommendation: dict[str, Any] | None,
    field_ids: dict[str, str],
    priority_score: int | None,
    config: dict[str, Any],
) -> bool:
    """Add or update an issue in the project. Returns True if newly added."""
    # First check if issue already exists in project
    issue_url = f"https://github.com/{repo}/issues/{issue['number']}"
    existing_item_id = _find_project_item(project_id, issue_url, config)

    if existing_item_id:
        # Update existing item
        _update_project_item_fields(
            project_id,
            existing_item_id,
            recommendation,
            field_ids,
            priority_score,
            config,
        )
        return False
    else:
        # Add new item
        item_id = _add_issue_to_project(project_id, repo, issue["number"], config)
        if item_id:
            _update_project_item_fields(
                project_id, item_id, recommendation, field_ids, priority_score, config
            )
            return True
        return False


def _find_project_item(
    project_id: str, issue_url: str, config: dict[str, Any]
) -> str | None:
    """Find if an issue already exists in the project."""
    query = """
    query($projectId: ID!) {
      node(id: $projectId) {
        ... on ProjectV2 {
          items(first: 100) {
            nodes {
              id
              content {
                ... on Issue {
                  url
                }
              }
            }
          }
        }
      }
    }
    """
    variables = {"projectId": project_id}

    try:
        data = _graphql_request(query, config, variables)
        items = data.get("data", {}).get("node", {}).get("items", {}).get("nodes", [])

        for item in items:
            if item.get("content", {}).get("url") == issue_url:
                return item["id"]

    except RuntimeError:
        pass

    return None


def _add_issue_to_project(
    project_id: str, repo: str, issue_number: int, config: dict[str, Any]
) -> str | None:
    """Add an issue to the project."""
    # First get the issue's node ID
    owner, repo_name = repo.split("/", 1)
    issue_query = """
    query($owner: String!, $repo: String!, $number: Int!) {
      repository(owner: $owner, name: $repo) {
        issue(number: $number) {
          id
        }
      }
    }
    """
    variables = {"owner": owner, "repo": repo_name, "number": issue_number}

    try:
        data = _graphql_request(issue_query, config, variables)
        issue_id = data.get("data", {}).get("repository", {}).get("issue", {}).get("id")

        if not issue_id:
            print(f"❌ Issue #{issue_number} not found")
            return None

    except RuntimeError as e:
        print(f"❌ Failed to get issue #{issue_number}: {e}")
        return None

    # Add to project
    mutation = """
    mutation($projectId: ID!, $contentId: ID!) {
      addProjectV2ItemById(input: {
        projectId: $projectId
        contentId: $contentId
      }) {
        item {
          id
        }
      }
    }
    """
    variables = {"projectId": project_id, "contentId": issue_id}

    try:
        data = _graphql_request(mutation, config, variables)
        return (
            data.get("data", {})
            .get("addProjectV2ItemById", {})
            .get("item", {})
            .get("id")
        )

    except RuntimeError as e:
        print(f"❌ Failed to add issue #{issue_number}: {e}")
        return None


def _update_project_item_fields(
    project_id: str,
    item_id: str,
    recommendation: dict[str, Any] | None,
    field_ids: dict[str, str],
    priority_score: int | None,
    config: dict[str, Any],
) -> None:
    """Update the custom fields for a project item."""
    # Get field values with option IDs
    fields_data = _get_project_fields(project_id, config)

    # Get analysis data (empty if no recommendation)
    analysis = recommendation.get("analysis", {}) if recommendation else {}

    # Update each field (will be None/empty for issues without recommendations)
    field_updates = {
        "Recommendation": recommendation.get("recommendation")
        if recommendation
        else None,
        "Severity": analysis.get("severity"),
        "Frequency": analysis.get("frequency"),
        "Prevalence": analysis.get("prevalence"),
        "Solution Complexity": analysis.get("solution_complexity"),
        "Solution Risk": analysis.get("solution_risk"),
    }

    for field_name, value in field_updates.items():
        if value and field_name in field_ids:
            field_id = field_ids[field_name]
            field_info = fields_data.get(field_name, {})

            # Find option ID for select fields
            option_id = None
            for option in field_info.get("options", []):
                if option["name"].lower() == str(value).lower():
                    option_id = option["id"]
                    break

            if option_id:
                _update_select_field(project_id, item_id, field_id, option_id, config)

    # Update priority score (only if there's a value)
    if "Priority Score" in field_ids and priority_score is not None:
        _update_number_field(
            project_id, item_id, field_ids["Priority Score"], priority_score, config
        )


def _update_select_field(
    project_id: str, item_id: str, field_id: str, option_id: str, config: dict[str, Any]
) -> None:
    """Update a single select field value."""
    mutation = """
    mutation($projectId: ID!, $itemId: ID!, $fieldId: ID!, $optionId: String!) {
      updateProjectV2ItemFieldValue(input: {
        projectId: $projectId
        itemId: $itemId
        fieldId: $fieldId
        value: {
          singleSelectOptionId: $optionId
        }
      }) {
        projectV2Item {
          id
        }
      }
    }
    """
    variables = {
        "projectId": project_id,
        "itemId": item_id,
        "fieldId": field_id,
        "optionId": option_id,
    }

    try:
        _graphql_request(mutation, config, variables)
    except RuntimeError:
        pass  # Ignore update errors


def _update_number_field(
    project_id: str, item_id: str, field_id: str, value: float, config: dict[str, Any]
) -> None:
    """Update a number field value."""
    mutation = """
    mutation($projectId: ID!, $itemId: ID!, $fieldId: ID!, $value: Float!) {
      updateProjectV2ItemFieldValue(input: {
        projectId: $projectId
        itemId: $itemId
        fieldId: $fieldId
        value: {
          number: $value
        }
      }) {
        projectV2Item {
          id
        }
      }
    }
    """
    variables = {
        "projectId": project_id,
        "itemId": item_id,
        "fieldId": field_id,
        "value": value,
    }

    try:
        _graphql_request(mutation, config, variables)
    except RuntimeError:
        pass  # Ignore update errors
