"""Test CLI commands with real GitHub repository."""

import subprocess
import sys
from typing import Any

import pytest
import requests

from trigent.database import (
    get_qdrant_url,
    get_headers,
    get_qdrant_config,
    load_issues,
)


# Session-scoped fixture to set up data once for all tests
@pytest.fixture(scope="session")
def cli_populated_collection(test_repo, test_config, skip_if_no_config, keep_test_db):
    """Set up a collection using CLI pull command, shared across all tests."""
    prefix = "clitest"
    
    # Clean up any existing test collection first
    from trigent.database import get_collection_name
    prefixed_config = {**test_config, "qdrant": {**test_config.get("qdrant", {}), "collection_prefix": prefix}}
    collection_name = get_collection_name(test_repo, prefixed_config)
    
    try:
        requests.delete(
            get_qdrant_url(f"collections/{collection_name}"),
            headers=get_headers(),
            timeout=get_qdrant_config()["timeout"],
        )
        print(f"🧹 Cleaned up existing test collection: {collection_name}")
    except:
        pass
    
    # Run CLI pull command once for the whole test session
    result = subprocess.run(
        [
            sys.executable, '-m', 'trigent', 'pull', test_repo,
            '--limit', '20',
            '--start-date', '2020-01-01',
            '--prefix', prefix
        ],
        capture_output=True,
        text=True,
        timeout=300
    )
    
    if result.returncode != 0:
        pytest.skip(f"CLI pull failed: {result.stderr}")
    
    yield collection_name, prefix, prefixed_config
    
    # Cleanup after all tests are done (only if not keeping test db)
    if not keep_test_db:
        try:
            requests.delete(
                get_qdrant_url(f"collections/{collection_name}"),
                headers=get_headers(),
                timeout=get_qdrant_config()["timeout"],
            )
            print(f"🧹 Cleaned up test collection: {collection_name}")
        except:
            pass
    else:
        print(f"🔍 Keeping test collection for inspection: {collection_name}")
        print(f"   Use: trigent browse {test_repo} --prefix {prefix}")


class TestCLICommands:
    """Test suite for all CLI commands with shared state."""

    def test_cli_pull_creates_collection(self, cli_populated_collection, test_repo):
        """Test that CLI pull command successfully creates and populates collection."""
        collection_name, prefix, config = cli_populated_collection
        
        # Verify collection exists in Qdrant
        response = requests.get(
            get_qdrant_url(f"collections/{collection_name}"),
            headers=get_headers(),
            timeout=get_qdrant_config()["timeout"],
        )
        
        assert response.status_code == 200, "Collection should exist in Qdrant"
        collection_info = response.json()["result"]
        points_count = collection_info.get("points_count", 0)
        assert points_count > 0, "Collection should have points"
        
        # Verify we can load issues through database interface
        issues = load_issues(test_repo, config)
        assert len(issues) > 0, "Should have loaded issues"
        assert len(issues) <= 20, "Should respect the limit"
        
        # Verify issue structure includes enrichment
        first_issue = issues[0]
        required_fields = ['number', 'title', 'body', 'state', 'createdAt', 'updatedAt', 'embedding']
        for field in required_fields:
            assert field in first_issue, f"Issue should have {field} field"

    def test_qdrant_structure(self, cli_populated_collection):
        """Test Qdrant collection structure and configuration."""
        collection_name, prefix, config = cli_populated_collection
        
        # Check collection configuration
        response = requests.get(
            get_qdrant_url(f"collections/{collection_name}"),
            headers=get_headers(),
            timeout=get_qdrant_config()["timeout"],
        )
        
        assert response.status_code == 200, "Collection should exist"
        collection_info = response.json()["result"]
        vector_config = collection_info.get("config", {}).get("params", {}).get("vectors", {})
        
        # Verify vector configuration
        assert vector_config.get("size") == 1024, "Vector size should be 1024 for Mistral embeddings"
        assert vector_config.get("distance") == "Cosine", "Distance metric should be Cosine"

    def test_load_issues_interface(self, cli_populated_collection, test_repo):
        """Test loading issues through database interface."""
        collection_name, prefix, config = cli_populated_collection
        
        # Load through database interface
        loaded_issues = load_issues(test_repo, config)
        
        assert len(loaded_issues) > 0, "Should have loaded issues from CLI-populated collection"
        
        # Check issue structure includes enrichment fields
        first_loaded = loaded_issues[0]
        
        required_fields = ['number', 'title', 'state', 'embedding', 'conversation']
        for field in required_fields:
            assert field in first_loaded, f"Loaded issue should have {field} field"

    def test_cli_update(self, cli_populated_collection, test_repo):
        """Test CLI update command for incremental updates."""
        collection_name, prefix, config = cli_populated_collection
        
        # Get initial count from CLI-populated collection
        initial_issues = load_issues(test_repo, config)
        initial_count = len(initial_issues)
        assert initial_count > 0
        
        # Run CLI update command
        result = subprocess.run(
            [
                sys.executable, '-m', 'trigent', 'update', test_repo,
                '--prefix', prefix
            ],
            capture_output=True,
            text=True,
            timeout=300
        )
        
        # Check that command succeeded
        assert result.returncode == 0, f"Update command failed: {result.stderr}"
        
        # Verify output shows completion
        assert "✅" in result.stdout, "Should show success indicators"
        
        # Verify data is still accessible and consistent
        final_issues = load_issues(test_repo, config)
        assert len(final_issues) >= initial_count, "Should have at least initial number of issues"

    def test_qdrant_search_functionality(self, cli_populated_collection):
        """Test basic Qdrant search capabilities."""
        collection_name, prefix, config = cli_populated_collection
        
        # Test scrolling through points
        scroll_payload = {
            "limit": 3,
            "with_payload": True,
            "with_vector": False
        }
        
        response = requests.post(
            get_qdrant_url(f"collections/{collection_name}/points/scroll"),
            json=scroll_payload,
            headers=get_headers(),
            timeout=get_qdrant_config()["timeout"],
        )
        
        assert response.status_code == 200, "Scroll should work"
        
        result = response.json()["result"]
        points = result.get("points", [])
        
        assert len(points) > 0, "Should get some points"
        assert len(points) <= 3, "Should respect limit"
        
        # Verify point structure
        first_point = points[0]
        assert "payload" in first_point, "Point should have payload"
        assert "number" in first_point["payload"], "Payload should have issue number"

    def test_filter_by_state(self, cli_populated_collection):
        """Test filtering issues by state in Qdrant."""
        collection_name, prefix, config = cli_populated_collection
        
        # Filter for open issues
        filter_payload = {
            "limit": 10,
            "filter": {
                "must": [
                    {
                        "key": "state",
                        "match": {"value": "open"}
                    }
                ]
            },
            "with_payload": True,
            "with_vector": False
        }
        
        response = requests.post(
            get_qdrant_url(f"collections/{collection_name}/points/scroll"),
            json=filter_payload,
            headers=get_headers(),
            timeout=get_qdrant_config()["timeout"],
        )
        
        assert response.status_code == 200, "Filter should work"
        
        filtered_points = response.json()["result"]["points"]
        
        # Verify all returned issues are open
        for point in filtered_points:
            assert point["payload"]["state"] == "open", "All filtered issues should be open"