# Trigent—A Rich Issue MCP for GitHub Triaging at Scale

An MCP server that provides enriched GitHub issue data with semantic embeddings, metrics, and analysis to help AI agents effectively triage and manage large issue repositories.

## Quick Start

```bash
# Install the package
pip install -e .

# Configure API key (copy and edit config file)
cp config.toml.example config.toml

# 1. Pull raw issue data (intelligent paging from 2025-01-01)
trigent pull jupyterlab/jupyterlab --start-date 2025-01-01

# 1a. Incremental update (only new/updated issues since last fetch)
trigent pull jupyterlab/jupyterlab

# 1b. Force full refetch from start date
trigent pull jupyterlab/jupyterlab --refetch

# 2. Enrich data with embeddings and metrics
trigent enrich jupyterlab/jupyterlab

# 3. Start MCP server for database access
trigent mcp &

# 4. Clean data files when needed
trigent clean
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

### 4. CLI Orchestration (`trigent/cli/`)
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
