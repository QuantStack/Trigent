"""Visualization module for Rich Issue MCP."""

import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.manifold import TSNE
from sklearn.neighbors import NearestNeighbors

from rich_issue_mcp.database import load_issues


def load_enriched_issues(repo: str) -> list[dict[str, Any]]:
    """Load enriched issues from database."""
    return load_issues(repo)


def extract_embeddings(issues: list[dict[str, Any]]) -> tuple[np.ndarray, list[str]]:
    """Extract embeddings and issue IDs from enriched issues."""
    embeddings = []
    issue_ids = []

    for issue in issues:
        if "embedding" in issue and issue["embedding"]:
            embeddings.append(issue["embedding"])
            issue_ids.append(str(issue["number"]))

    return np.array(embeddings), issue_ids


def compute_tsne(embeddings: np.ndarray, random_state: int = 42) -> np.ndarray:
    """Compute T-SNE projection of embeddings to 2D."""
    tsne = TSNE(
        n_components=2,
        random_state=random_state,
        perplexity=min(30, len(embeddings) - 1),
    )
    return tsne.fit_transform(embeddings)


def find_nearest_neighbors(embeddings: np.ndarray, k: int = 4) -> list[list[int]]:
    """Find k nearest neighbors for each embedding."""
    nbrs = NearestNeighbors(n_neighbors=k + 1, algorithm="auto").fit(embeddings)
    distances, indices = nbrs.kneighbors(embeddings)

    # Remove self (first neighbor) and return indices
    return [list(neighbors[1:]) for neighbors in indices]


def extract_cross_references(issues: list[dict[str, Any]]) -> dict[str, set[str]]:
    """Extract cross-reference relationships between issues."""
    cross_refs = {}
    issue_numbers = {str(issue["number"]) for issue in issues}

    for issue in issues:
        issue_id = str(issue["number"])
        cross_refs[issue_id] = set()

        # Check cross_references field
        if "cross_references" in issue and issue["cross_references"]:
            for ref in issue["cross_references"]:
                if ref.get("type") == "issue" and "number" in ref:
                    ref_id = str(ref["number"])
                    if ref_id in issue_numbers:
                        cross_refs[issue_id].add(ref_id)

    return cross_refs


def write_graphml(
    issue_ids: list[str],
    tsne_coords: np.ndarray,
    nearest_neighbors: list[list[int]],
    cross_references: dict[str, set[str]],
    output_path: Path,
    issues: list[dict[str, Any]],
    scale: float = 1.0,
) -> None:
    """Write GraphML file with issue network."""
    # Create root element
    root = ET.Element("graphml")
    root.set("xmlns", "http://graphml.graphdrawing.org/xmlns")
    root.set("xmlns:xsi", "http://www.w3.org/2001/XMLSchema-instance")
    root.set(
        "xsi:schemaLocation",
        "http://graphml.graphdrawing.org/xmlns http://graphml.graphdrawing.org/xmlns/1.0/graphml.xsd",
    )

    # Define node attributes
    node_attrs = [
        ("d0", "x", "double"),
        ("d1", "y", "double"),
        ("d2", "label", "string"),
        ("d3", "title", "string"),
        ("d4", "state", "string"),
        ("d5", "reactions", "int"),
        ("d6", "comments", "int"),
        ("d7", "url", "string"),
        ("d8", "status", "string"),
        ("d9", "num_comments", "int"),
        ("d10", "num_emojis", "int"),
        ("d11", "total_engagements", "int"),
    ]

    for attr_id, attr_name, attr_type in node_attrs:
        key = ET.SubElement(root, "key")
        key.set("id", attr_id)
        key.set("for", "node")
        key.set("attr.name", attr_name)
        key.set("attr.type", attr_type)

    # Define edge attributes
    edge_attrs = [
        ("d12", "edge_type", "string"),
    ]

    for attr_id, attr_name, attr_type in edge_attrs:
        key = ET.SubElement(root, "key")
        key.set("id", attr_id)
        key.set("for", "edge")
        key.set("attr.name", attr_name)
        key.set("attr.type", attr_type)

    # Create graph
    graph = ET.SubElement(root, "graph")
    graph.set("id", "IssueNetwork")
    graph.set("edgedefault", "undirected")

    # Create issue lookup
    issue_lookup = {str(issue["number"]): issue for issue in issues}

    # Add nodes
    for i, issue_id in enumerate(issue_ids):
        node = ET.SubElement(graph, "node")
        node.set("id", issue_id)

        # Add coordinates (scaled)
        x_data = ET.SubElement(node, "data")
        x_data.set("key", "d0")
        x_data.text = str(tsne_coords[i, 0] * scale)

        y_data = ET.SubElement(node, "data")
        y_data.set("key", "d1")
        y_data.text = str(tsne_coords[i, 1] * scale)

        # Add issue metadata
        issue = issue_lookup.get(issue_id, {})

        label_data = ET.SubElement(node, "data")
        label_data.set("key", "d2")
        label_data.text = f"{issue_id}: {issue.get('title', '')}"

        title_data = ET.SubElement(node, "data")
        title_data.set("key", "d3")
        title_data.text = issue.get("title", "")

        state_data = ET.SubElement(node, "data")
        state_data.set("key", "d4")
        state_data.text = issue.get("state", "unknown")

        reactions_data = ET.SubElement(node, "data")
        reactions_data.set("key", "d5")
        reactions_data.text = str(issue.get("reactions", {}).get("total_count", 0))

        comments_data = ET.SubElement(node, "data")
        comments_data.set("key", "d6")
        comments_data.text = str(issue.get("number_of_comments", 0))

        # URL field
        url_data = ET.SubElement(node, "data")
        url_data.set("key", "d7")
        url_data.text = issue.get("html_url", "")

        # Status field (duplicate of state for clarity)
        status_data = ET.SubElement(node, "data")
        status_data.set("key", "d8")
        status_data.text = issue.get("state", "unknown")

        # Number of comments field
        num_comments_data = ET.SubElement(node, "data")
        num_comments_data.set("key", "d9")
        num_comments_data.text = str(issue.get("number_of_comments", 0))

        # Count emojis in body and comments
        emoji_count = 0
        # Count emojis in reactions
        reactions = issue.get("reactions", {})
        if isinstance(reactions, dict):
            for key, value in reactions.items():
                if key != "total_count" and isinstance(value, int):
                    emoji_count += value

        # Count emojis from comments (if available)
        comments = issue.get("comments_data", [])
        if isinstance(comments, list):
            for comment in comments:
                if isinstance(comment, dict) and "reactions" in comment:
                    comment_reactions = comment["reactions"]
                    if isinstance(comment_reactions, dict):
                        for key, value in comment_reactions.items():
                            if key != "total_count" and isinstance(value, int):
                                emoji_count += value

        num_emojis_data = ET.SubElement(node, "data")
        num_emojis_data.set("key", "d10")
        num_emojis_data.text = str(emoji_count)

        # Calculate total engagements: comments + emojis + linked issues
        num_comments = issue.get("number_of_comments", 0)
        num_linked = len(cross_references.get(issue_id, set()))
        total_engagements = num_comments + emoji_count + num_linked

        total_engagements_data = ET.SubElement(node, "data")
        total_engagements_data.set("key", "d11")
        total_engagements_data.text = str(total_engagements)

    # Add nearest neighbor edges
    edge_id = 0
    for i, neighbors in enumerate(nearest_neighbors):
        source_id = issue_ids[i]
        for neighbor_idx in neighbors:
            target_id = issue_ids[neighbor_idx]

            edge = ET.SubElement(graph, "edge")
            edge.set("id", f"e{edge_id}")
            edge.set("source", source_id)
            edge.set("target", target_id)

            type_data = ET.SubElement(edge, "data")
            type_data.set("key", "d12")
            type_data.text = "nearest_neighbor"

            edge_id += 1

    # Add cross-reference edges
    for source_id, refs in cross_references.items():
        if source_id in issue_ids:
            for target_id in refs:
                if target_id in issue_ids:
                    edge = ET.SubElement(graph, "edge")
                    edge.set("id", f"e{edge_id}")
                    edge.set("source", source_id)
                    edge.set("target", target_id)

                    type_data = ET.SubElement(edge, "data")
                    type_data.set("key", "d12")
                    type_data.text = "cross_reference"

                    edge_id += 1

    # Write to file
    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    tree.write(output_path, encoding="utf-8", xml_declaration=True)


def visualize_issues(
    repo: str, output_path: Path | str | None = None, scale: float = 1.0
) -> None:
    """Create T-SNE visualization and GraphML network from enriched issues.

    Args:
        repo: Repository name (e.g. 'owner/repo') to load from TinyDB
        output_path: Output GraphML file path, or directory path, or None for default naming
        scale: Scale factor for embedding coordinates
    """
    print(f"🔍 Loading enriched issues from repository {repo}...")

    issues = load_enriched_issues(repo)

    print(f"📊 Extracting embeddings from {len(issues)} issues...")
    embeddings, issue_ids = extract_embeddings(issues)

    if len(embeddings) == 0:
        raise ValueError("No embeddings found in input")

    print(f"🧮 Computing T-SNE projection for {len(embeddings)} embeddings...")
    tsne_coords = compute_tsne(embeddings)

    print("🔗 Finding 4 nearest neighbors for each issue...")
    nearest_neighbors = find_nearest_neighbors(embeddings, k=4)

    print("🔍 Extracting cross-reference relationships...")
    cross_references = extract_cross_references(issues)

    # Determine output path
    if output_path is None:
        # Default naming: owner_repo_issues.graphml
        default_name = repo.replace("/", "_") + "_issues.graphml"
        graphml_path = Path.cwd() / default_name
    else:
        output_path = Path(output_path)
        if output_path.is_dir():
            # It's a directory, use default filename in that directory
            default_name = repo.replace("/", "_") + "_issues.graphml"
            graphml_path = output_path / default_name
        else:
            # It's a file path
            graphml_path = output_path

    # Create output directory if needed
    graphml_path.parent.mkdir(parents=True, exist_ok=True)

    # Write GraphML file
    print(f"💾 Writing GraphML network to {graphml_path}...")
    write_graphml(
        issue_ids,
        tsne_coords,
        nearest_neighbors,
        cross_references,
        graphml_path,
        issues,
        scale,
    )

    # Write T-SNE coordinates as JSON in same directory
    tsne_path = graphml_path.parent / (graphml_path.stem + "_tsne_coordinates.json")
    print(f"💾 Writing T-SNE coordinates to {tsne_path}...")

    tsne_data = {
        "coordinates": [
            {"issue_id": issue_id, "x": float(coord[0]), "y": float(coord[1])}
            for issue_id, coord in zip(issue_ids, tsne_coords, strict=False)
        ]
    }

    with open(tsne_path, "w") as f:
        json.dump(tsne_data, f, indent=2)

    print("✅ Visualization complete!")
    print(f"   - GraphML network: {graphml_path}")
    print(f"   - T-SNE coordinates: {tsne_path}")
    print(f"   - Issues processed: {len(issue_ids)}")

    # Print edge statistics
    nn_edges = len(issue_ids) * 4  # Each issue has 4 nearest neighbors
    cr_edges = sum(len(refs) for refs in cross_references.values())
    print(f"   - Nearest neighbor edges: {nn_edges}")
    print(f"   - Cross-reference edges: {cr_edges}")
