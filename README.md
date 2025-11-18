# Trigent—A Rich Issue MCP for GitHub Triaging at Scale

An MCP server that provides enriched GitHub issue data with semantic embeddings, metrics, and analysis to help AI agents effectively triage and manage large issue repositories.

## Quick Start

```bash
# Install the package
pip install -e .

# Configure API key (copy and edit config file)
cp config.toml.example config.toml

# 1. Initial repository setup (pulls data and enriches it)
trigent pull jupyterlab/jupyterlab --start-date 2025-01-01

# 2. Keep repository up to date (incremental updates)
trigent update jupyterlab/jupyterlab

# 3. Start MCP server for AI agent access
trigent serve jupyterlab/jupyterlab

# 4. Browse issues interactively
trigent browse jupyterlab/jupyterlab

# 5. Export data for analysis
trigent export jupyterlab/jupyterlab --csv --viz
```

## Architecture

### 1. Data Pulling (`trigent/pull/`)
- Python module that pulls raw issues from GitHub repositories using intelligent paging
- Uses `gh` CLI for GitHub API access with weekly chunking based on `updatedAt` timestamps
- Implements incremental updates to avoid refetching unchanged issues
- Maintains state tracking in `data/state-{repo}.json` for last fetch timestamps
- Merges new/updated issues with existing data while preserving all information
- Saves raw data as gzipped JSON in /data folder

### 2. Data Enrichment (`trigent/enrich/`)
- Python module that processes raw issue data
- Adds embeddings for semantic search (via Mistral API)
- Computes metrics: reactions, comments, age, activity scores
- Assigns quartiles for all metrics using pandas `qcut()`
- Saves enriched data as gzipped JSON in /data folder

### 3. MCP Server (`trigent/mcp/`)
- FastMCP server providing database access tools
- Serves enriched issue data to AI agents
- Tools: get_issue, find_similar_issues, find_cross_referenced_issues, get_issue_metrics, get_top_issues

### 4. CLI Orchestration (`trigent/cli.py`)
- Python CLI for coordinating all components
- Unified `trigent` command with subcommands
- Orchestrates the entire workflow from pull to triaging

## Key Features

- **Intelligent Paging**: Weekly chunking with incremental updates based on `updatedAt` timestamps
- **State Management**: Tracks last fetch to enable efficient incremental updates
- **Smart Merging**: Updates existing issues while preserving data integrity
- **Semantic Similarity**: Mistral API embeddings of title + body + comments
- **Reaction Metrics**: Positive/negative reaction counts across issue and comments
- **Engagement Heuristics**: Comment frequency, age, activity scores
- **Link Detection**: Extract referenced issue numbers (#1234)
- **Quartile Analysis**: Statistical distribution of all metrics
- **K-NN Analysis**: K-4 nearest neighbor distance computation for clustering
- **AI Summaries**: Optional LLM-generated issue summaries
- **Persistent Cache**: Disk-based caching for API responses
- **Top Issues API**: Query top N issues sorted by any metric

## Files

- `trigent/cli/cli.py` - Main CLI entry point with all subcommands
- `trigent/pull/pull.py` - Python module for fetching raw issues from GitHub
- `trigent/enrich/enrich.py` - Python enrichment pipeline with embeddings/metrics
- `trigent/mcp/mcp_server.py` - FastMCP server for database access
- `trigent/config.py` - Configuration management
- `config.toml` - Configuration file for API keys and settings
- `pyproject.toml` - Project configuration

## Dependencies

- **Python 3.12+** - Core language with modern type hints
- **pandas, numpy** - Data processing and quartile calculations
- **requests** - HTTP client for Mistral API
- **FastMCP** - Minimal server for database access
- **scikit-learn** - Machine learning utilities for k-nearest neighbors
- **diskcache** - Persistent caching for API responses
- **toml** - Configuration file parsing
- **ipython, ipdb** - Interactive development and debugging
- **gh CLI** - GitHub issue fetching (external dependency)

Designed for large-scale issue management with minimal dependencies and maximum efficiency.

## CLI Commands

### `trigent pull <repo>` - Initial Repository Setup
Sets up a new repository by fetching issues and enriching them with embeddings and metrics.

```bash
trigent pull jupyterlab/jupyterlab --limit 100 --start-date 2025-01-01
```

Options:
- `--exclude-closed`: Only fetch open issues
- `--limit, -l`: Limit number of issues to fetch
- `--start-date`: Start date for fetching issues (default: 2025-01-01)
- `--item-types`: What to fetch: 'issues', 'prs', or 'both' (default: both)
- `--prefix`: Collection prefix for isolating data (useful for testing)

### `trigent update <repo>` - Incremental Updates
Updates an existing repository with new and modified issues since last fetch.

```bash
trigent update jupyterlab/jupyterlab
```

Options:
- `--prefix`: Collection prefix for isolating data

### `trigent serve <repo>` - Start MCP Server
Starts the MCP server to provide issue data to AI agents.

```bash
trigent serve jupyterlab/jupyterlab --port 8000
```

Options:
- `--host`: Host to bind to (default: localhost)
- `--port`: Port to bind to (default: 8000)
- `--prefix`: Collection prefix for isolating data

### `trigent browse <repo>` - Interactive Browser
Opens an interactive TUI to browse and search issues.

```bash
trigent browse jupyterlab/jupyterlab
```

Options:
- `--prefix`: Collection prefix for isolating data

### `trigent export <repo>` - Export Data
Exports issue data to CSV or creates visualizations.

```bash
# Export to CSV
trigent export jupyterlab/jupyterlab --csv

# Create visualizations
trigent export jupyterlab/jupyterlab --viz

# Both (default if no flags specified)
trigent export jupyterlab/jupyterlab
```

Options:
- `--csv`: Export to CSV format
- `--viz`: Export visualizations
- `--output, -o`: Output file/directory path
- `--scale`: Scale factor for visualizations (default: 1.0)
- `--prefix`: Collection prefix for isolating data

### `trigent clean [repo]` - Clean Data
Removes repository data from the database.

```bash
# Clean specific repository
trigent clean jupyterlab/jupyterlab

# Clean all repositories (with confirmation)
trigent clean
```

Options:
- `--yes, -y`: Skip confirmation prompt
- `--prefix`: Collection prefix for isolating data

### `trigent validate <repo>` - Validate Data
Validates repository data integrity.

```bash
trigent validate jupyterlab/jupyterlab
```

Options:
- `--delete-invalid`: Delete invalid entries
- `--prefix`: Collection prefix for isolating data
