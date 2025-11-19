"""Test stats command functionality."""

import subprocess
import json
from pathlib import Path

import pytest


class TestStatsCommand:
    """Test suite for stats command."""

    def test_cli_stats_all_collections(self, test_repo, test_config, populated_collection, skip_if_no_config):
        """Test stats command shows all collections."""
        print("\n🔍 Testing stats command for all collections")
        
        # Run stats command without specifying repo (should show all)
        result = subprocess.run(
            ["python", "-m", "trigent", "stats", "--prefix", "__test"],
            capture_output=True,
            text=True,
        )
        
        assert result.returncode == 0, f"Stats command failed: {result.stderr}"
        output = result.stdout
        
        # Check for expected output elements
        assert "📊 Fetching collection statistics" in output
        assert "📦 Collection:" in output
        assert "Total items:" in output
        
        # Should show our test collection
        assert populated_collection in output or "__test_jupyter_echo_kernel" in output
        
        print("✅ Stats command successfully shows all collections")

    def test_cli_stats_specific_repo(self, test_repo, test_config, populated_collection, skip_if_no_config):
        """Test stats command for specific repository."""
        print(f"\n🔍 Testing stats command for specific repo: {test_repo}")
        
        # Run stats command for specific repo
        result = subprocess.run(
            ["python", "-m", "trigent", "stats", test_repo, "--prefix", "__test"],
            capture_output=True,
            text=True,
        )
        
        assert result.returncode == 0, f"Stats command failed: {result.stderr}"
        output = result.stdout
        
        # Check for expected output
        assert "📊 Fetching collection statistics" in output
        assert "Total items:" in output
        
        # Should show stats for issues and PRs
        assert "Issues:" in output or "Pull Requests:" in output or "(Empty collection)" in output
        
        # Should show state distribution if not empty
        if "(Empty collection)" not in output:
            assert "State distribution:" in output
            
        print("✅ Stats command successfully shows specific repo stats")

    def test_cli_stats_with_data(self, test_repo, test_config, populated_collection, skip_if_no_config):
        """Test stats command shows correct data for populated collection."""
        print(f"\n🔍 Testing stats command data accuracy")
        
        # First, let's ensure we have some data by running pull
        pull_result = subprocess.run(
            [
                "python", "-m", "trigent", "pull", test_repo,
                "--prefix", "__test",
                "--limit", "5",  # Just a few items for testing
            ],
            capture_output=True,
            text=True,
        )
        
        # Now run stats
        result = subprocess.run(
            ["python", "-m", "trigent", "stats", test_repo, "--prefix", "__test"],
            capture_output=True,
            text=True,
        )
        
        assert result.returncode == 0, f"Stats command failed: {result.stderr}"
        output = result.stdout
        
        # Parse the output to check data
        lines = output.split("\n")
        
        # Look for total items
        total_items_line = next((l for l in lines if "Total items:" in l), None)
        if total_items_line and "(Empty collection)" not in output:
            # Extract number from "Total items: X"
            total_str = total_items_line.split(":")[1].strip().replace(",", "")
            total_items = int(total_str)
            assert total_items > 0, "Should have some items"
            
            # Check state distribution percentages add up
            if "State distribution:" in output:
                state_section_start = lines.index(next(l for l in lines if "State distribution:" in l))
                # State lines follow the pattern "- state: count (X%)"
                percentages = []
                for i in range(state_section_start + 1, len(lines)):
                    line = lines[i].strip()
                    if line.startswith("- ") and "%" in line:
                        # Extract percentage
                        pct_str = line.split("(")[1].split("%")[0]
                        percentages.append(float(pct_str))
                    elif not line.startswith(" "):
                        break
                
                if percentages:
                    total_pct = sum(percentages)
                    assert 99.0 <= total_pct <= 101.0, f"Percentages should sum to ~100%, got {total_pct}%"
        
        print("✅ Stats command shows accurate data")

    def test_cli_stats_nonexistent_repo(self, test_config, skip_if_no_config):
        """Test stats command with non-existent repository."""
        print("\n🔍 Testing stats command with non-existent repo")
        
        # Use a unique prefix to ensure collection doesn't exist
        nonexistent_prefix = "__test_nonexistent_stats_"
        
        result = subprocess.run(
            ["python", "-m", "trigent", "stats", "fake/repo", "--prefix", nonexistent_prefix],
            capture_output=True,
            text=True,
        )
        
        # Should succeed but indicate collection not found
        assert result.returncode == 0, f"Stats command failed: {result.stderr}"
        output = result.stdout
        
        # Should indicate the collection wasn't found or show no collections
        assert "Collection for fake/repo not found" in output or "No collections found" in output
        
        print("✅ Stats command handles non-existent repo gracefully")

    def test_cli_stats_recommendation_histogram(self, test_repo, test_config, populated_collection, skip_if_no_config):
        """Test that stats command shows recommendation histogram."""
        print("\n🔍 Testing stats recommendation histogram")
        
        result = subprocess.run(
            ["python", "-m", "trigent", "stats", test_repo, "--prefix", "__test"],
            capture_output=True,
            text=True,
        )
        
        assert result.returncode == 0, f"Stats command failed: {result.stderr}"
        output = result.stdout
        
        if "(Empty collection)" not in output:
            # Should have recommendations section
            assert "Recommendations:" in output
            # Either shows histogram or indicates no recommendations
            assert "recommendations:" in output or "No items have recommendations" in output
        
        print("✅ Stats command shows recommendation information")

    def test_cli_stats_last_updated(self, test_repo, test_config, populated_collection, skip_if_no_config):
        """Test that stats command shows last updated information."""
        print("\n🔍 Testing stats last updated information")
        
        result = subprocess.run(
            ["python", "-m", "trigent", "stats", test_repo, "--prefix", "__test"],
            capture_output=True,
            text=True,
        )
        
        assert result.returncode == 0, f"Stats command failed: {result.stderr}"
        output = result.stdout
        
        if "(Empty collection)" not in output:
            # Should show last updated
            assert "Last updated:" in output
            # Should show days ago
            if "Last updated: Unknown" not in output:
                assert "days ago" in output
        
        print("✅ Stats command shows last updated information")
