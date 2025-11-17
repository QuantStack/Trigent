#!/usr/bin/env python3
"""Script to populate the test repository with test issues using gh CLI."""

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, Any

# Add the project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def run_gh_command(command: list[str]) -> subprocess.CompletedProcess:
    """Run a gh CLI command and return the result."""
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=True)
        return result
    except subprocess.CalledProcessError as e:
        print(f"Error running gh command: {' '.join(command)}")
        print(f"Error: {e.stderr}")
        raise


def create_issue_from_data(repo: str, issue_data: Dict[str, Any]) -> int:
    """Create a GitHub issue from our test data."""
    title = issue_data["title"]
    body = issue_data["body"]
    
    # Build labels list
    labels = [label["name"] for label in issue_data.get("labels", [])]
    
    # Build assignees list
    assignees = [assignee["login"] for assignee in issue_data.get("assignees", [])]
    
    print(f"Creating issue #{issue_data['number']}: {title[:50]}...")
    
    # Create the issue
    command = ["gh", "issue", "create", "--repo", repo, "--title", title, "--body", body]
    
    if labels:
        command.extend(["--label", ",".join(labels)])
    
    if assignees:
        command.extend(["--assignee", ",".join(assignees)])
    
    result = run_gh_command(command)
    
    # Extract issue number from output (format: "https://github.com/user/repo/issues/123")
    issue_url = result.stdout.strip()
    actual_issue_number = int(issue_url.split("/")[-1])
    
    print(f"  ✅ Created as issue #{actual_issue_number}")
    
    # Add comments if any
    comments = issue_data.get("comments", [])
    if comments:
        print(f"  📝 Adding {len(comments)} comments...")
        for i, comment in enumerate(comments):
            comment_body = f"**Comment by @{comment['author']['login']}:**\n\n{comment['body']}"
            
            comment_command = ["gh", "issue", "comment", str(actual_issue_number), "--repo", repo, "--body", comment_body]
            run_gh_command(comment_command)
            print(f"    ✅ Added comment {i+1}/{len(comments)}")
            
            # Small delay to avoid rate limiting
            time.sleep(0.5)
    
    return actual_issue_number


def close_issue_if_needed(repo: str, issue_number: int, state: str):
    """Close an issue if it should be closed."""
    if state.upper() == "CLOSED":
        print(f"  🔒 Closing issue #{issue_number}...")
        command = ["gh", "issue", "close", str(issue_number), "--repo", repo]
        run_gh_command(command)


def populate_initial_issues(repo: str):
    """Populate the repository with initial test issues."""
    print(f"🚀 Populating {repo} with initial test issues...")
    
    fixtures_dir = project_root / "tests" / "fixtures" / "issues"
    created_issues = {}
    
    # Load and create all issues (1001-1010)
    for issue_num in range(1001, 1011):
        issue_file = fixtures_dir / f"issue_{issue_num}.json"
        
        if not issue_file.exists():
            print(f"❌ Issue file not found: {issue_file}")
            continue
        
        with open(issue_file) as f:
            issue_data = json.load(f)
        
        try:
            actual_number = create_issue_from_data(repo, issue_data)
            created_issues[issue_num] = actual_number
            
            # Close if needed
            close_issue_if_needed(repo, actual_number, issue_data["state"])
            
            # Small delay to avoid rate limiting
            time.sleep(1)
            
        except Exception as e:
            print(f"❌ Failed to create issue {issue_num}: {e}")
            continue
    
    print(f"✅ Created {len(created_issues)} issues")
    
    # Create mapping file for reference
    mapping_file = project_root / "tests" / "issue_mapping.json"
    with open(mapping_file, "w") as f:
        json.dump(created_issues, f, indent=2)
    
    print(f"📋 Issue number mapping saved to {mapping_file}")
    return created_issues


def add_updated_issues(repo: str, issue_mapping: Dict[int, int]):
    """Add updates to existing issues and create new ones."""
    print(f"📝 Adding updates to {repo}...")
    
    updated_dir = project_root / "tests" / "fixtures" / "updated"
    
    # Update issue 1001 (add comment and close)
    if 1001 in issue_mapping:
        print("Updating issue 1001 with resolution comment...")
        actual_number = issue_mapping[1001]
        
        resolution_comment = """**Resolution by @issue_resolver:**

Fixed by implementing better kernel state management. Variable scope is now properly maintained.

This resolves the random NameError issues by:
- Improving kernel state persistence
- Better variable scope tracking
- Enhanced error handling for undefined variables"""

        comment_command = ["gh", "issue", "comment", str(actual_number), "--repo", repo, "--body", resolution_comment]
        run_gh_command(comment_command)
        
        # Close the issue
        close_command = ["gh", "issue", "close", str(actual_number), "--repo", repo, "--comment", "Issue resolved with kernel state management improvements."]
        run_gh_command(close_command)
        
        print("  ✅ Added resolution comment and closed issue 1001")
    
    # Update issue 1005 (add progress comment)
    if 1005 in issue_mapping:
        print("Updating issue 1005 with progress comment...")
        actual_number = issue_mapping[1005]
        
        progress_comment = """**Progress Update by @kernel_team:**

Working on a fix that implements async kernel communication. Should resolve the GIL blocking issue.

Current progress:
- ✅ Identified GIL as root cause
- ✅ Designed async communication protocol  
- 🔄 Implementing kernel message queue
- ⏳ Testing with long-running operations

Expected completion: Next sprint."""

        comment_command = ["gh", "issue", "comment", str(actual_number), "--repo", repo, "--body", progress_comment]
        run_gh_command(comment_command)
        
        print("  ✅ Added progress comment to issue 1005")
    
    # Create new issue 1011 if it exists
    issue_1011_file = updated_dir / "issue_1011.json"
    if issue_1011_file.exists():
        print("Creating new issue 1011...")
        
        with open(issue_1011_file) as f:
            issue_data = json.load(f)
        
        try:
            actual_number = create_issue_from_data(repo, issue_data)
            print(f"  ✅ Created new issue #{actual_number} (was 1011 in test data)")
            
            # Update mapping
            issue_mapping[1011] = actual_number
            
        except Exception as e:
            print(f"❌ Failed to create issue 1011: {e}")
    
    # Update mapping file
    mapping_file = project_root / "tests" / "issue_mapping.json"
    with open(mapping_file, "w") as f:
        json.dump(issue_mapping, f, indent=2)
    
    print("✅ Updates completed")


def verify_repo_population(repo: str):
    """Verify that the repository has been populated correctly."""
    print(f"🔍 Verifying {repo} population...")
    
    try:
        # List all issues
        command = ["gh", "issue", "list", "--repo", repo, "--state", "all", "--limit", "50"]
        result = run_gh_command(command)
        
        lines = result.stdout.strip().split('\n')
        issue_count = len([line for line in lines if line.strip()])
        
        print(f"✅ Found {issue_count} issues in repository")
        
        # Show first few issues
        if lines:
            print("📋 Recent issues:")
            for line in lines[:5]:
                if line.strip():
                    print(f"  {line}")
        
        return issue_count >= 10  # We expect at least 10 issues
        
    except Exception as e:
        print(f"❌ Error verifying repo: {e}")
        return False


def main():
    """Main function to populate the test repository."""
    repo = "mmesch/trigent-test-repo"
    
    print("🚀 Rich Issue MCP Test Repository Setup")
    print(f"Repository: {repo}")
    print("="*60)
    
    try:
        # Check gh CLI authentication
        try:
            run_gh_command(["gh", "auth", "status"])
            print("✅ GitHub CLI authenticated")
        except:
            print("❌ GitHub CLI not authenticated. Please run 'gh auth login'")
            return 1
        
        # Populate initial issues
        issue_mapping = populate_initial_issues(repo)
        
        if not issue_mapping:
            print("❌ No issues were created")
            return 1
        
        # Wait a bit before adding updates
        print("⏳ Waiting before adding updates...")
        time.sleep(2)
        
        # Add updates
        add_updated_issues(repo, issue_mapping)
        
        # Verify population
        if verify_repo_population(repo):
            print(f"\n✅ Repository {repo} successfully populated!")
            print(f"🔗 View at: https://github.com/{repo}/issues")
            
            # Show summary
            print(f"\n📊 Summary:")
            print(f"  - Created {len(issue_mapping)} test issues")
            print(f"  - Added comments and cross-references")
            print(f"  - Included open and closed issues")
            print(f"  - Issue mapping saved to tests/issue_mapping.json")
            
            return 0
        else:
            print("❌ Repository verification failed")
            return 1
            
    except KeyboardInterrupt:
        print("\n❌ Interrupted by user")
        return 1
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())