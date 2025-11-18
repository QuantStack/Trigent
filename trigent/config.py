"""Configuration management for Rich Issue MCP."""

from pathlib import Path
from typing import Any

import diskcache as dc
import toml

# Global cache instance
_cache_instance = None


def get_cache() -> dc.Cache:
    """Get the global cache instance."""
    global _cache_instance
    if _cache_instance is None:
        # Default cache directory in project root
        project_root = Path(__file__).parent.parent
        cache_dir = project_root / "dcache"

        # Try to get cache settings from config
        try:
            config = get_config()
            cache_config = config.get("cache", {})
            cache_dir = Path(cache_config.get("directory", cache_dir))
            size_limit = cache_config.get("size_limit_mb", 500) * 1024 * 1024
        except (FileNotFoundError, ValueError):
            # Use defaults if config not available
            size_limit = 500 * 1024 * 1024  # 500MB default

        _cache_instance = dc.Cache(str(cache_dir), size_limit=size_limit)

    return _cache_instance


def get_config(config_path: str | None = None) -> dict[str, Any]:
    """
    Get configuration from config.toml file.

    Args:
        config_path: Optional path to config file. If None, looks for config.toml
                    in current directory, then project root.

    Returns:
        Dictionary containing configuration values

    Raises:
        FileNotFoundError: If config file cannot be found
        ValueError: If config file is invalid TOML
    """
    # Determine config file path
    if config_path:
        config_file = Path(config_path)
    else:
        # Look for config.toml in current directory first
        config_file = Path("config.toml")
        if not config_file.exists():
            # Look in project root (where this module is located)
            project_root = Path(__file__).parent.parent
            config_file = project_root / "config.toml"

    if not config_file.exists():
        raise FileNotFoundError(
            f"Configuration file not found at {config_file}. "
            f"Copy config.toml.example to config.toml and configure your settings."
        )

    try:
        with open(config_file) as f:
            return toml.load(f)
    except toml.TomlDecodeError as e:
        raise ValueError(f"Invalid TOML in config file {config_file}: {e}") from e


def get_data_directory() -> Path:
    """
    Get the configured data directory as an absolute path.

    Returns:
        Absolute Path to the data directory

    Raises:
        ValueError: If configured path is not absolute or not configured
        FileNotFoundError: If config file cannot be found
    """
    config = get_config()
    data_config = config.get("data", {})
    data_dir = data_config.get("directory")

    if data_dir is None:
        raise ValueError(
            "Data directory must be configured in config.toml [data] section"
        )

    # Convert to Path and validate it's absolute
    path = Path(data_dir)
    if not path.is_absolute():
        raise ValueError(f"Data directory must be an absolute path, got: {data_dir}")

    return path


def get_data_file_path(filename: str) -> Path:
    """
    Get an absolute path to a file in the data directory.

    Args:
        filename: Name of the file

    Returns:
        Absolute path to the file in the data directory
    """
    return get_data_directory() / filename


def get_alignment_date() -> str:
    """
    Get the date alignment anchor from configuration.

    This date is used to align date ranges to improve cache hits.
    All date ranges will be aligned such that they end/begin on
    boundaries that are multiples of chunk_days from this anchor.

    Returns:
        ISO date string (YYYY-MM-DD) for alignment anchor
        Defaults to "2024-01-01" if not configured
    """
    try:
        config = get_config()
        pull_config = config.get("pull", {})
        return pull_config.get("alignment_date", "2024-01-01")
    except (FileNotFoundError, ValueError):
        # Use default if config not available
        return "2024-01-01"


def get_couchdb_config() -> dict[str, Any]:
    """
    Get CouchDB configuration from config.toml.

    Returns:
        Dictionary containing CouchDB configuration with defaults:
        - server_url: CouchDB server URL (default: http://localhost:5984)
        - username: Optional username for authentication
        - password: Optional password for authentication
        - timeout: Request timeout in seconds (default: 30)

    Raises:
        FileNotFoundError: If config file cannot be found
        ValueError: If config file is invalid TOML
    """
    try:
        config = get_config()
        couchdb_config = config.get("couchdb", {})

        # Apply defaults
        defaults = {
            "server_url": "http://localhost:5984",
            "username": None,
            "password": None,
            "timeout": 30,
        }

        # Merge with configured values
        result = defaults.copy()
        result.update(couchdb_config)

        # Validate server_url
        server_url = result["server_url"]
        if not server_url.startswith(("http://", "https://")):
            raise ValueError(
                f"CouchDB server_url must start with http:// or https://, got: {server_url}"
            )

        # Remove trailing slash
        result["server_url"] = server_url.rstrip("/")

        return result

    except (FileNotFoundError, ValueError):
        # Return defaults if config not available
        return {
            "server_url": "http://localhost:5984",
            "username": None,
            "password": None,
            "timeout": 30,
        }
