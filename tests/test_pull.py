"""Test pull functionality with real GitHub repository."""

from typing import Any

import pytest
import requests

from rich_issue_mcp.database import (
    get_qdrant_url,
    get_headers,
    get_qdrant_config,
    load_issues,
)
from rich_issue_mcp.pull import fetch_issues


class TestPullFunctionality:
    """Test suite for pull functionality."""

    def test_pull_initial_data(self, test_repo, test_config, clean_collection, skip_if_no_config):
        """Test initial pull of issues from real repository."""
        # Pull issues with reasonable limits
        issues = fetch_issues(
            repo=test_repo,
            include_closed=True,
            limit=20,
            start_date="2020-01-01",
            refetch=True,
            mode="create",
            config=test_config
        )
        
        # Verify we got some issues
        assert len(issues) > 0, "Should fetch at least one issue"
        assert len(issues) <= 20, "Should respect the limit"
        
        # Verify issue structure
        first_issue = issues[0]
        required_fields = ['number', 'title', 'body', 'state', 'createdAt', 'updatedAt']
        for field in required_fields:
            assert field in first_issue, f"Issue should have {field} field"

    def test_qdrant_collection_created(self, test_repo, populated_collection, skip_if_no_config):
        """Test that Qdrant collection is created and populated."""
        # Collection should already be populated by fixture
        
        # Check collection exists in Qdrant
        response = requests.get(
            get_qdrant_url(f"collections/{populated_collection}"),
            headers=get_headers(),
            timeout=get_qdrant_config()["timeout"],
        )
        
        assert response.status_code == 200, "Collection should exist in Qdrant"
        
        collection_info = response.json()["result"]
        points_count = collection_info.get("points_count", 0)
        
        assert points_count > 0, "Collection should have points"

    def test_qdrant_structure(self, test_repo, populated_collection, skip_if_no_config):
        """Test Qdrant collection structure and configuration."""
        # Check collection configuration (data already populated by fixture)
        response = requests.get(
            get_qdrant_url(f"collections/{populated_collection}"),
            headers=get_headers(),
            timeout=get_qdrant_config()["timeout"],
        )
        
        collection_info = response.json()["result"]
        vector_config = collection_info.get("config", {}).get("params", {}).get("vectors", {})
        
        # Verify vector configuration
        assert vector_config.get("size") == 1024, "Vector size should be 1024 for Mistral embeddings"
        assert vector_config.get("distance") == "Cosine", "Distance metric should be Cosine"

    def test_load_issues_interface(self, test_repo, test_config, populated_collection, skip_if_no_config):
        """Test loading issues through database interface."""
        # Load through database interface (data already populated by fixture)
        loaded_issues = load_issues(test_repo, test_config)
        
        assert len(loaded_issues) > 0, "Should have loaded issues from populated collection"
        
        # Check a specific issue structure
        first_loaded = loaded_issues[0]
        
        required_fields = ['number', 'title', 'state', 'embedding', 'conversation']
        for field in required_fields:
            assert field in first_loaded, f"Loaded issue should have {field} field"

    def test_update_mode(self, test_repo, test_config, populated_collection, skip_if_no_config):
        """Test update mode functionality."""
        # Get initial count from populated collection
        initial_issues = load_issues(test_repo, test_config)
        initial_count = len(initial_issues)
        assert initial_count > 0
        
        # Update pull (should be faster and may process fewer issues)
        fetch_issues(
            repo=test_repo,
            include_closed=True,
            limit=5,
            mode="update",
            config=test_config
        )
        
        # Verify data is still accessible
        final_issues = load_issues(test_repo, test_config)
        assert len(final_issues) >= initial_count, "Should have at least initial number of issues"

    def test_qdrant_search_functionality(self, test_repo, populated_collection, skip_if_no_config):
        """Test basic Qdrant search capabilities."""
        # Test scrolling through points (data already populated by fixture)
        scroll_payload = {
            "limit": 3,
            "with_payload": True,
            "with_vector": False
        }
        
        response = requests.post(
            get_qdrant_url(f"collections/{populated_collection}/points/scroll"),
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

    def test_filter_by_state(self, test_repo, populated_collection, skip_if_no_config):
        """Test filtering issues by state in Qdrant."""
        # Filter for open issues (data already populated by fixture)
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
            get_qdrant_url(f"collections/{populated_collection}/points/scroll"),
            json=filter_payload,
            headers=get_headers(),
            timeout=get_qdrant_config()["timeout"],
        )
        
        assert response.status_code == 200, "Filter should work"
        
        filtered_points = response.json()["result"]["points"]
        
        # Verify all returned issues are open
        for point in filtered_points:
            assert point["payload"]["state"] == "open", "All filtered issues should be open"