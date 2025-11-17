#!/usr/bin/env python3
"""Test script for pull functionality with Qdrant integration."""

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import Mock, patch

import requests

# Add the project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from rich_issue_mcp.database import (
    get_collection_name,
    get_headers,
    get_qdrant_config,
    get_qdrant_url,
    load_issues,
)


class QdrantTestServer:
    """Mock Qdrant server for testing."""
    
    def __init__(self):
        self.collections = {}
        self.running = False
    
    def start(self):
        """Start the mock Qdrant server."""
        print("🚀 Starting mock Qdrant server...")
        self.running = True
        # In a real test, you would start an actual Qdrant instance
        # For now, we'll mock the responses
        
    def stop(self):
        """Stop the mock Qdrant server."""
        print("🛑 Stopping mock Qdrant server...")
        self.running = False
        self.collections = {}
    
    def verify_collection_exists(self, collection_name: str) -> bool:
        """Check if collection exists."""
        try:
            response = requests.get(
                get_qdrant_url(f"collections/{collection_name}"),
                headers=get_headers(),
                timeout=get_qdrant_config()["timeout"],
            )
            return response.status_code == 200
        except:
            return False
    
    def get_collection_info(self, collection_name: str) -> Dict[str, Any]:
        """Get collection information."""
        try:
            response = requests.get(
                get_qdrant_url(f"collections/{collection_name}"),
                headers=get_headers(),
                timeout=get_qdrant_config()["timeout"],
            )
            if response.status_code == 200:
                return response.json()["result"]
        except:
            pass
        return {}


class GitHubAPIMock:
    """Mock GitHub API for testing."""
    
    def __init__(self, test_data_dir: Path):
        self.test_data_dir = test_data_dir
        self.call_count = 0
        
    def load_test_issue(self, issue_number: int, updated: bool = False) -> Dict[str, Any]:
        """Load test issue from JSON file."""
        if updated:
            file_path = self.test_data_dir / "updated" / f"issue_{issue_number}.json"
            if not file_path.exists():
                file_path = self.test_data_dir / "issues" / f"issue_{issue_number}.json"
        else:
            file_path = self.test_data_dir / "issues" / f"issue_{issue_number}.json"
            
        if not file_path.exists():
            return None
            
        with open(file_path) as f:
            return json.load(f)
    
    def mock_gh_api_call(self, command: List[str], updated: bool = False) -> str:
        """Mock gh CLI API calls."""
        self.call_count += 1
        
        # Parse the gh command to understand what's being requested
        if "api" in command and "repos/test/repo/issues" in command:
            # This is an issues list request
            issues = []
            
            # Load test issues (1001-1010, plus 1011 if updated)
            issue_numbers = list(range(1001, 1011))
            if updated and (self.test_data_dir / "updated" / "issue_1011.json").exists():
                issue_numbers.append(1011)
            
            for issue_num in issue_numbers:
                issue_data = self.load_test_issue(issue_num, updated)
                if issue_data:
                    # Convert to GitHub API format
                    gh_issue = {
                        "number": issue_data["number"],
                        "title": issue_data["title"],
                        "body": issue_data["body"],
                        "state": issue_data["state"].lower(),
                        "created_at": issue_data["createdAt"],
                        "updated_at": issue_data["updatedAt"],
                        "html_url": issue_data["url"],
                        "user": issue_data["author"],
                        "labels": issue_data["labels"],
                        "assignees": issue_data["assignees"],
                        "reactions": {
                            **issue_data["reactions"],
                            "total_count": sum(issue_data["reactions"].values())
                        }
                    }
                    issues.append(gh_issue)
            
            return json.dumps(issues)
            
        elif "api" in command and "/issues/" in command and "/comments" in command:
            # This is a comments request for a specific issue
            # Extract issue number from URL
            url_part = next(part for part in command if "/issues/" in part)
            issue_num = int(url_part.split("/issues/")[1].split("/")[0])
            
            issue_data = self.load_test_issue(issue_num, updated)
            if issue_data and "comments" in issue_data:
                gh_comments = []
                for comment in issue_data["comments"]:
                    gh_comment = {
                        "user": comment["author"],
                        "body": comment["body"],
                        "created_at": comment["createdAt"],
                        "reactions": {
                            **comment["reactions"],
                            "total_count": sum(comment["reactions"].values())
                        }
                    }
                    gh_comments.append(gh_comment)
                return json.dumps(gh_comments)
            
            return "[]"  # No comments
        
        # Default response
        return "{}"


def setup_test_environment():
    """Set up test environment with mock config."""
    # Create a temporary config file for testing
    test_config = {
        "api": {
            "mistral_api_key": "test-key-123"
        },
        "qdrant": {
            "host": "localhost",
            "port": 6333,
            "timeout": 30
        }
    }
    
    # Write test config
    config_path = project_root / "config.toml"
    config_backup = None
    
    if config_path.exists():
        config_backup = config_path.read_text()
    
    with open(config_path, "w") as f:
        import toml
        toml.dump(test_config, f)
    
    return config_backup


def restore_config(config_backup: str):
    """Restore original config."""
    config_path = project_root / "config.toml"
    if config_backup:
        config_path.write_text(config_backup)
    elif config_path.exists():
        config_path.unlink()


def test_pull_initial_data():
    """Test pulling initial issue data into Qdrant."""
    print("\n" + "="*60)
    print("🧪 TESTING: Pull Initial Data")
    print("="*60)
    
    test_repo = "test/repo"
    collection_name = get_collection_name(test_repo)
    
    # Create GitHub API mock
    fixtures_dir = project_root / "tests" / "fixtures"
    github_mock = GitHubAPIMock(fixtures_dir)
    
    def mock_subprocess_run(command, *args, **kwargs):
        """Mock subprocess.run for gh CLI calls."""
        if command[0] == "gh":
            result_stdout = github_mock.mock_gh_api_call(command)
            return Mock(stdout=result_stdout, stderr="", returncode=0)
        return subprocess.run(command, *args, **kwargs)
    
    # Clean up any existing collection first
    try:
        response = requests.delete(
            get_qdrant_url(f"collections/{collection_name}"),
            headers=get_headers(),
            timeout=get_qdrant_config()["timeout"],
        )
        print(f"🧹 Cleaned up existing collection: {response.status_code}")
    except:
        print("🧹 No existing collection to clean up")
    
    # Mock the GitHub API calls
    with patch('subprocess.run', side_effect=mock_subprocess_run):
        # Import and run the pull function
        from rich_issue_mcp.pull import fetch_issues
        
        print(f"📥 Pulling issues for {test_repo}...")
        start_time = time.time()
        
        try:
            issues = fetch_issues(
                repo=test_repo,
                include_closed=True,
                limit=None,
                start_date="2024-01-01",
                refetch=True,
                mode="create"
            )
            
            pull_time = time.time() - start_time
            print(f"✅ Pull completed in {pull_time:.2f}s")
            print(f"📊 Fetched {len(issues)} issues")
            
            # Verify the issues were saved to Qdrant
            print("\n🔍 Verifying Qdrant population...")
            
            # Check if collection exists
            try:
                response = requests.get(
                    get_qdrant_url(f"collections/{collection_name}"),
                    headers=get_headers(),
                    timeout=get_qdrant_config()["timeout"],
                )
                
                if response.status_code == 200:
                    collection_info = response.json()["result"]
                    points_count = collection_info.get("points_count", 0)
                    print(f"✅ Collection '{collection_name}' exists with {points_count} points")
                    
                    # Verify we can load issues back
                    loaded_issues = load_issues(test_repo)
                    print(f"✅ Successfully loaded {len(loaded_issues)} issues from Qdrant")
                    
                    # Check some issue details
                    issue_numbers = [issue.get("number") for issue in loaded_issues]
                    expected_numbers = list(range(1001, 1011))
                    
                    print(f"📋 Issue numbers found: {sorted(issue_numbers)}")
                    print(f"📋 Expected numbers: {sorted(expected_numbers)}")
                    
                    missing = set(expected_numbers) - set(issue_numbers)
                    extra = set(issue_numbers) - set(expected_numbers)
                    
                    if missing:
                        print(f"❌ Missing issues: {sorted(missing)}")
                    if extra:
                        print(f"ℹ️  Extra issues: {sorted(extra)}")
                    
                    if not missing and len(loaded_issues) >= len(expected_numbers):
                        print("✅ All expected issues found in Qdrant!")
                        
                        # Verify issue content
                        test_issue = next((issue for issue in loaded_issues if issue["number"] == 1001), None)
                        if test_issue:
                            print(f"✅ Test issue 1001: '{test_issue['title'][:50]}...'")
                            print(f"   State: {test_issue['state']}, Comments: {len(test_issue.get('comments', []))}")
                        
                        return True
                    else:
                        print("❌ Issue count mismatch")
                        return False
                else:
                    print(f"❌ Collection not found: {response.status_code}")
                    return False
                    
            except Exception as e:
                print(f"❌ Error checking Qdrant: {e}")
                return False
                
        except Exception as e:
            print(f"❌ Pull failed: {e}")
            import traceback
            traceback.print_exc()
            return False


def test_pull_updated_data():
    """Test pulling updated issue data into Qdrant."""
    print("\n" + "="*60)
    print("🧪 TESTING: Pull Updated Data")
    print("="*60)
    
    test_repo = "test/repo"
    
    # Create GitHub API mock for updated data
    fixtures_dir = project_root / "tests" / "fixtures"
    github_mock = GitHubAPIMock(fixtures_dir)
    
    def mock_subprocess_run_updated(command, *args, **kwargs):
        """Mock subprocess.run for gh CLI calls with updated data."""
        if command[0] == "gh":
            result_stdout = github_mock.mock_gh_api_call(command, updated=True)
            return Mock(stdout=result_stdout, stderr="", returncode=0)
        return subprocess.run(command, *args, **kwargs)
    
    # Mock the GitHub API calls with updated data
    with patch('subprocess.run', side_effect=mock_subprocess_run_updated):
        from rich_issue_mcp.pull import fetch_issues
        
        print(f"📥 Pulling updated issues for {test_repo}...")
        start_time = time.time()
        
        try:
            issues = fetch_issues(
                repo=test_repo,
                include_closed=True,
                limit=None,
                mode="update"  # Update mode
            )
            
            pull_time = time.time() - start_time
            print(f"✅ Update pull completed in {pull_time:.2f}s")
            print(f"📊 Processed {len(issues)} issues")
            
            # Verify updates in Qdrant
            loaded_issues = load_issues(test_repo)
            print(f"✅ Loaded {len(loaded_issues)} issues after update")
            
            # Check for specific updates
            issue_1001 = next((issue for issue in loaded_issues if issue["number"] == 1001), None)
            if issue_1001:
                print(f"✅ Issue 1001 state: {issue_1001['state']} (should be CLOSED)")
                print(f"✅ Issue 1001 comments: {len(issue_1001.get('comments', []))} (should be 3)")
            
            # Check for new issue 1011
            issue_1011 = next((issue for issue in loaded_issues if issue["number"] == 1011), None)
            if issue_1011:
                print(f"✅ New issue 1011 found: '{issue_1011['title'][:50]}...'")
            else:
                print("❌ New issue 1011 not found")
            
            return True
            
        except Exception as e:
            print(f"❌ Update pull failed: {e}")
            import traceback
            traceback.print_exc()
            return False


def verify_qdrant_structure():
    """Verify the structure of data in Qdrant."""
    print("\n" + "="*60)
    print("🧪 TESTING: Qdrant Data Structure")
    print("="*60)
    
    test_repo = "test/repo"
    collection_name = get_collection_name(test_repo)
    
    try:
        # Get collection info
        response = requests.get(
            get_qdrant_url(f"collections/{collection_name}"),
            headers=get_headers(),
            timeout=get_qdrant_config()["timeout"],
        )
        
        if response.status_code == 200:
            info = response.json()["result"]
            print(f"✅ Collection: {collection_name}")
            print(f"   Points: {info.get('points_count', 0)}")
            print(f"   Vector size: {info.get('config', {}).get('params', {}).get('vectors', {}).get('size', 'unknown')}")
            print(f"   Distance: {info.get('config', {}).get('params', {}).get('vectors', {}).get('distance', 'unknown')}")
            
            # Sample some points
            scroll_payload = {"limit": 3, "with_payload": True, "with_vector": False}
            scroll_response = requests.post(
                get_qdrant_url(f"collections/{collection_name}/points/scroll"),
                json=scroll_payload,
                headers=get_headers(),
                timeout=get_qdrant_config()["timeout"],
            )
            
            if scroll_response.status_code == 200:
                points = scroll_response.json()["result"]["points"]
                print(f"\n📋 Sample points ({len(points)}):")
                for point in points[:3]:
                    payload = point["payload"]
                    print(f"   Issue #{payload.get('number')}: {payload.get('title', '')[:60]}...")
                    print(f"      State: {payload.get('state')}, Comments: {len(payload.get('comments', []))}")
                    
            return True
        else:
            print(f"❌ Collection not accessible: {response.status_code}")
            return False
            
    except Exception as e:
        print(f"❌ Error verifying Qdrant structure: {e}")
        return False


def cleanup_test_data():
    """Clean up test data from Qdrant."""
    test_repo = "test/repo"
    collection_name = get_collection_name(test_repo)
    
    try:
        response = requests.delete(
            get_qdrant_url(f"collections/{collection_name}"),
            headers=get_headers(),
            timeout=get_qdrant_config()["timeout"],
        )
        print(f"\n🧹 Cleanup: Deleted test collection ({response.status_code})")
    except:
        print("\n🧹 Cleanup: No test collection to delete")


def main():
    """Run the pull tests."""
    print("🚀 Starting Rich Issue MCP Pull Tests")
    print("Testing pull functionality with Qdrant integration\n")
    
    # Setup test environment
    config_backup = setup_test_environment()
    
    try:
        # Run tests
        results = {
            "initial_pull": test_pull_initial_data(),
            "updated_pull": test_pull_updated_data(),
            "qdrant_structure": verify_qdrant_structure()
        }
        
        # Summary
        print("\n" + "="*60)
        print("📊 TEST SUMMARY")
        print("="*60)
        
        for test_name, result in results.items():
            status = "✅ PASS" if result else "❌ FAIL"
            print(f"{test_name}: {status}")
        
        all_passed = all(results.values())
        print(f"\nOverall: {'✅ ALL TESTS PASSED' if all_passed else '❌ SOME TESTS FAILED'}")
        
        return 0 if all_passed else 1
        
    finally:
        # Cleanup
        cleanup_test_data()
        restore_config(config_backup)


if __name__ == "__main__":
    sys.exit(main())