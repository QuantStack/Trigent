"""Pytest configuration and shared fixtures for Rich Issue MCP tests."""

import time
from pathlib import Path
from typing import Any, Generator

import pytest
import requests

from trigent.database import (
    get_collection_name,
    get_headers,
    get_qdrant_config,
    get_qdrant_url,
)


def pytest_addoption(parser):
    """Add custom command line options for pytest."""
    parser.addoption(
        "--keep-test-db",
        action="store_true",
        default=False,
        help="Keep test database collections after tests complete (useful for debugging)"
    )


@pytest.fixture(scope="session")
def project_root() -> Path:
    """Get the project root directory."""
    return Path(__file__).parent.parent


@pytest.fixture(scope="session")
def test_repo() -> str:
    """Test repository to use for all tests."""
    return "jupyter/echo_kernel"


@pytest.fixture(scope="session")
def qdrant_available() -> bool:
    """Check if Qdrant is available for testing."""
    try:
        response = requests.get(
            get_qdrant_url("collections"),
            headers=get_headers(),
            timeout=5,
        )
        return response.status_code == 200
    except:
        return False


@pytest.fixture(scope="session")
def skip_if_no_qdrant(qdrant_available):
    """Skip tests if Qdrant is not available."""
    if not qdrant_available:
        pytest.skip("Qdrant not available")


@pytest.fixture(scope="session")
def keep_test_db(request):
    """Get the --keep-test-db flag value."""
    return request.config.getoption("--keep-test-db")


@pytest.fixture(scope="session")
def config_available(project_root: Path) -> bool:
    """Check if config.toml exists."""
    return (project_root / "config.toml").exists()


@pytest.fixture(scope="session")
def skip_if_no_config(config_available):
    """Skip tests if config.toml is not available."""
    if not config_available:
        pytest.skip("config.toml not found - copy config.toml.example to config.toml")


@pytest.fixture(scope="session")
def test_config(test_repo: str) -> dict[str, Any]:
    """Create test configuration with test collection prefix."""
    from trigent.config import get_config
    
    config = get_config()
    # Override collection prefix for testing
    config.setdefault("qdrant", {})["collection_prefix"] = "__test"
    return config


@pytest.fixture(scope="session")
def clean_collection(test_repo: str, test_config: dict[str, Any], skip_if_no_qdrant, keep_test_db) -> Generator[str, None, None]:
    """Provide a clean Qdrant collection for testing (session-scoped)."""
    collection_name = get_collection_name(test_repo, test_config)
    
    # Clean up before session
    try:
        requests.delete(
            get_qdrant_url(f"collections/{collection_name}"),
            headers=get_headers(),
            timeout=get_qdrant_config()["timeout"],
        )
        time.sleep(0.5)  # Allow deletion to complete
        print(f"🧹 Cleaned collection {collection_name} for test session")
    except:
        pass  # Collection might not exist
    
    yield collection_name
    
    # Clean up after session (only if not keeping test db)
    if not keep_test_db:
        try:
            requests.delete(
                get_qdrant_url(f"collections/{collection_name}"),
                headers=get_headers(),
                timeout=get_qdrant_config()["timeout"],
            )
            print(f"🧹 Cleaned up collection {collection_name} after test session")
        except:
            pass
    else:
        print(f"🔍 Keeping test collection: {collection_name}")
        print(f"   Use: trigent browse {test_repo} --prefix test")


@pytest.fixture(scope="session")
def populated_collection(test_repo: str, test_config: dict[str, Any], clean_collection: str, skip_if_no_config) -> str:
    """Populate the test collection with data (session-scoped)."""
    from trigent.pull import fetch_issues
    
    print(f"📊 Populating collection {clean_collection} with test data...")
    
    # Fetch limited data once for the entire test session
    # Pass test config to use test collection prefix
    issues = fetch_issues(
        repo=test_repo,
        include_closed=True,
        limit=20,
        start_date="2020-01-01",
        refetch=True,
        mode="create",
        config=test_config
    )
    
    print(f"✅ Populated collection with {len(issues)} issues for testing")
    return clean_collection