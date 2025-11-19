# Trigent—RAG for Triaging GH Issues at Scale

Trigent enables **Retrieval-Augmented Generation (RAG) over GitHub issues at scale**. It fetches issues, enriches them with semantic embeddings, and provides an MCP server so AI agents can intelligently search, analyze, and triage large issue repositories.

## What it does

- **Fetches** GitHub issues and pull requests from any repository
- **Enriches** them with semantic embeddings (using Mistral API) 
- **Provides** an MCP server with tools for semantic search, similarity matching, and analytics
- **Enables** AI agents to perform intelligent issue triaging at scale

## Quick Start

```bash
# Install and configure
pip install -e .
cp config.toml.example config.toml  # Add your Mistral API key

# Start Qdrant vector database
docker run -p 6333:6333 qdrant/qdrant
# or with Nix: services.qdrant.enable = true; (in configuration.nix)

# Setup a repository (fetches and enriches data)
trigent pull jupyterlab/jupyterlab

# Start MCP server for AI agent access  
trigent serve jupyterlab/jupyterlab

# Keep data updated
trigent update jupyterlab/jupyterlab
```

## MCP Tools Available

The MCP server provides these tools for AI agents:

- `get_issue(number)` - Get specific issue details
- `find_similar_issues(number)` - Find semantically similar issues using embeddings
- `find_similar_issues_by_text(text)` - Find issues similar to given text
- `find_cross_referenced_issues(number)` - Get linked/referenced issues
- `get_top_issues(sort_column)` - Get top issues by any metric
- `add_recommendation(issue_number, ...)` - Add AI recommendations to issues

## Other Commands

```bash
trigent export <repo>     # Export to CSV or visualizations  
trigent clean <repo>      # Remove repository data
trigent stats [<repo>]    # Show collection statistics
```

## Configuration

Add your Mistral API key to `config.toml`:

```toml
[api]
mistral_api_key = "your_key_here"
```

## Requirements

- Python 3.12+
- GitHub CLI (`gh`) for fetching issues
- Mistral API key for embeddings
- Qdrant vector database (runs locally by default)
