#!/usr/bin/env python3
"""Migrate data from CouchDB to Qdrant vector database."""

import argparse
import json
import sys
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import requests
from requests.auth import HTTPBasicAuth

# CouchDB configuration
COUCHDB_URL = "http://localhost:5984"
COUCHDB_USER = "admin"
COUCHDB_PASSWORD = "password"

# Qdrant configuration  
QDRANT_HOST = "localhost"
QDRANT_PORT = 6333
QDRANT_URL = f"http://{QDRANT_HOST}:{QDRANT_PORT}"

# Embedding dimension (Mistral embeddings are 1024-dimensional)
EMBEDDING_DIM = 1024


def get_couchdb_auth() -> HTTPBasicAuth:
    """Get CouchDB authentication."""
    return HTTPBasicAuth(COUCHDB_USER, COUCHDB_PASSWORD)


def get_couchdb_documents(database: str, batch_size: int = 1000) -> List[Dict[str, Any]]:
    """Fetch all documents from CouchDB database in batches."""
    auth = get_couchdb_auth()
    all_docs = []
    skip = 0
    
    # First get total count
    count_url = f"{COUCHDB_URL}/{database}"
    try:
        count_response = requests.get(count_url, auth=auth, timeout=30)
        count_response.raise_for_status()
        total_docs = count_response.json().get("doc_count", 0)
        print(f"  Total documents in database: {total_docs}")
    except:
        total_docs = None
    
    while True:
        url = f"{COUCHDB_URL}/{database}/_all_docs?include_docs=true&limit={batch_size}&skip={skip}"
        
        try:
            response = requests.get(url, auth=auth, timeout=60)
            response.raise_for_status()
            data = response.json()
            
            rows = data.get("rows", [])
            if not rows:
                break
            
            # Extract documents, skipping design docs
            batch_docs = []
            for row in rows:
                if "doc" in row:
                    doc = row["doc"]
                    # Skip design documents and deleted docs
                    if not doc.get("_id", "").startswith("_design/") and not doc.get("_deleted"):
                        batch_docs.append(doc)
            
            all_docs.extend(batch_docs)
            skip += len(rows)
            
            print(f"  Fetched {len(all_docs)} documents so far (processed {skip} rows)...")
            
            # Check if we've fetched all documents
            if len(rows) < batch_size:
                break
            
        except requests.exceptions.RequestException as e:
            print(f"Error fetching documents: {e}")
            if hasattr(e, 'response') and e.response:
                print(f"Response: {e.response.text}")
            raise
            
    return all_docs


def prepare_qdrant_point(doc: Dict[str, Any], point_id: int) -> Optional[Dict[str, Any]]:
    """Convert a CouchDB document to a Qdrant point."""
    # Skip documents without embeddings
    if "embedding" not in doc or not isinstance(doc.get("embedding"), list):
        return None
    
    # Extract embedding
    embedding = doc["embedding"]
    
    # Verify embedding dimension
    if len(embedding) != EMBEDDING_DIM:
        print(f"Warning: Issue {doc.get('number')} has embedding of dimension {len(embedding)}, expected {EMBEDDING_DIM}")
        return None
    
    # Prepare payload (all non-embedding fields)
    payload = {}
    for key, value in doc.items():
        # Skip CouchDB internal fields and embedding
        if key not in ["_id", "_rev", "embedding", "embeddings"]:
            # Handle special cases
            if key == "labels" and isinstance(value, list):
                # Store label names as a list
                payload["label_names"] = [label["name"] for label in value if isinstance(label, dict) and "name" in label]
                payload["labels"] = value
            elif key == "author" and isinstance(value, dict):
                # Flatten author info
                payload["author_login"] = value.get("login")
                payload["author"] = value
            elif key == "assignees" and isinstance(value, list):
                # Store assignee logins
                payload["assignee_logins"] = [assignee.get("login") for assignee in value if isinstance(assignee, dict)]
                payload["assignees"] = value
            elif key == "cross_references" and isinstance(value, list):
                # Store cross-reference numbers
                payload["cross_reference_numbers"] = [ref.get("number") for ref in value if isinstance(ref, dict) and "number" in ref]
                payload["cross_references"] = value
            elif key == "recommendations" and isinstance(value, list):
                # Store recommendations
                payload["recommendations"] = value
                payload["has_recommendations"] = len(value) > 0
                if value:
                    # Extract recommendation types
                    rec_types = []
                    for rec in value:
                        if isinstance(rec, dict) and "recommendation" in rec:
                            rec_types.append(rec["recommendation"])
                    payload["recommendation_types"] = list(set(rec_types))
            else:
                payload[key] = value
    
    # Add issue identifier
    if "number" in payload:
        payload["issue_number"] = payload["number"]
    
    return {
        "id": point_id,
        "vector": embedding,
        "payload": payload
    }


def create_qdrant_collection(collection_name: str):
    """Create a Qdrant collection with appropriate configuration."""
    try:
        # Check if collection exists
        response = requests.get(f"{QDRANT_URL}/collections")
        response.raise_for_status()
        collections = response.json()["result"]["collections"]
        
        if any(c["name"] == collection_name for c in collections):
            print(f"Collection '{collection_name}' already exists. Delete it first if you want to recreate.")
            user_response = input("Delete existing collection? (y/N): ")
            if user_response.lower() == 'y':
                delete_response = requests.delete(f"{QDRANT_URL}/collections/{collection_name}")
                delete_response.raise_for_status()
                print(f"Deleted collection '{collection_name}'")
            else:
                return
        
        # Create collection with cosine distance (typical for normalized embeddings)
        create_payload = {
            "vectors": {
                "size": EMBEDDING_DIM,
                "distance": "Cosine"
            }
        }
        
        create_response = requests.put(
            f"{QDRANT_URL}/collections/{collection_name}",
            json=create_payload
        )
        create_response.raise_for_status()
        print(f"Created collection '{collection_name}' with {EMBEDDING_DIM}-dimensional vectors")
        
    except Exception as e:
        print(f"Error creating collection: {e}")
        raise


def migrate_database(database_name: str, collection_name: Optional[str] = None):
    """Migrate a CouchDB database to Qdrant collection."""
    if collection_name is None:
        # Use database name as collection name, replacing invalid characters
        collection_name = database_name.replace("/", "_").replace("-", "_")
    
    print(f"\nMigrating CouchDB database '{database_name}' to Qdrant collection '{collection_name}'")
    
    # Test connection to Qdrant
    try:
        test_response = requests.get(f"{QDRANT_URL}/collections")
        test_response.raise_for_status()
        print(f"✓ Connected to Qdrant at {QDRANT_HOST}:{QDRANT_PORT}")
    except Exception as e:
        print(f"✗ Failed to connect to Qdrant: {e}")
        print(f"Make sure Qdrant is running at {QDRANT_HOST}:{QDRANT_PORT}")
        return
    
    # Create collection
    create_qdrant_collection(collection_name)
    
    # Fetch documents from CouchDB
    print(f"\nFetching documents from CouchDB database '{database_name}'...")
    documents = get_couchdb_documents(database_name)
    print(f"✓ Fetched {len(documents)} documents")
    
    # Convert to Qdrant points
    print("\nConverting documents to Qdrant points...")
    points = []
    skipped = 0
    
    for idx, doc in enumerate(documents):
        point = prepare_qdrant_point(doc, idx)
        if point:
            points.append(point)
        else:
            skipped += 1
    
    print(f"✓ Converted {len(points)} documents (skipped {skipped} without embeddings)")
    
    if not points:
        print("No documents with embeddings found. Nothing to migrate.")
        return
    
    # Upload to Qdrant in batches
    print(f"\nUploading {len(points)} points to Qdrant...")
    batch_size = 100
    
    for i in range(0, len(points), batch_size):
        batch = points[i:i+batch_size]
        try:
            # Upload batch using Qdrant's REST API
            upload_payload = {"points": batch}
            upload_response = requests.put(
                f"{QDRANT_URL}/collections/{collection_name}/points",
                json=upload_payload
            )
            upload_response.raise_for_status()
            print(f"  ✓ Uploaded batch {i//batch_size + 1}/{(len(points) + batch_size - 1)//batch_size}")
        except Exception as e:
            print(f"  ✗ Error uploading batch: {e}")
            if hasattr(e, 'response') and e.response:
                print(f"Response: {e.response.text}")
            raise
    
    # Verify upload
    try:
        info_response = requests.get(f"{QDRANT_URL}/collections/{collection_name}")
        info_response.raise_for_status()
        collection_info = info_response.json()["result"]
        point_count = collection_info.get("points_count", 0)
        print(f"\n✓ Migration complete! Collection '{collection_name}' has {point_count} points")
    except Exception as e:
        print(f"\n✗ Error verifying collection: {e}")


def list_couchdb_databases():
    """List all available CouchDB databases."""
    auth = get_couchdb_auth()
    url = f"{COUCHDB_URL}/_all_dbs"
    
    try:
        response = requests.get(url, auth=auth, timeout=30)
        response.raise_for_status()
        databases = response.json()
        
        # Filter out system databases
        user_databases = [db for db in databases if not db.startswith("_")]
        
        return user_databases
    except requests.exceptions.RequestException as e:
        print(f"Error listing databases: {e}")
        return []


def main():
    """Main migration script."""
    print("CouchDB to Qdrant Migration Tool")
    print("=" * 40)
    
    # List available databases
    print("\nFetching CouchDB databases...")
    databases = list_couchdb_databases()
    
    if not databases:
        print("No user databases found in CouchDB")
        return
    
    print(f"\nFound {len(databases)} database(s):")
    for i, db in enumerate(databases, 1):
        print(f"  {i}. {db}")
    
    # Ask user which database to migrate
    if len(sys.argv) > 1:
        # Database specified as command line argument
        db_name = sys.argv[1]
        if db_name not in databases:
            print(f"\nError: Database '{db_name}' not found")
            return
    else:
        # Interactive selection
        print("\nWhich database would you like to migrate?")
        print("Enter database name or number (or 'all' to migrate all databases): ", end="")
        choice = input().strip()
        
        if choice.lower() == 'all':
            for db in databases:
                migrate_database(db)
            return
        elif choice.isdigit() and 1 <= int(choice) <= len(databases):
            db_name = databases[int(choice) - 1]
        elif choice in databases:
            db_name = choice
        else:
            print(f"Invalid choice: {choice}")
            return
    
    # Get custom collection name if desired
    print(f"\nMigrating database: {db_name}")
    default_collection = db_name.replace("/", "_").replace("-", "_").lower()
    print(f"Enter Qdrant collection name (default: {default_collection}): ", end="")
    collection_name = input().strip()
    
    if not collection_name:
        collection_name = None
    
    # Perform migration
    migrate_database(db_name, collection_name)
    
    print("\n✓ Migration complete!")
    
    # Show sample query  
    print("\nSample Qdrant query to find similar issues:")
    print(f"""
import requests

# Search for similar issues
search_payload = {{
    "vector": embedding,  # Your query embedding (1024-dimensional)
    "limit": 5,
    "filter": {{
        "must": [
            {{
                "key": "state",
                "match": {{
                    "value": "open"
                }}
            }}
        ]
    }}
}}

response = requests.post(
    "http://{QDRANT_HOST}:{QDRANT_PORT}/collections/COLLECTION_NAME/points/search",
    json=search_payload
)
results = response.json()["result"]
    """)


if __name__ == "__main__":
    main()