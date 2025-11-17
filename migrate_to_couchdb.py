#!/usr/bin/env python3
"""Migration script to transfer data from TinyDB backup to CouchDB."""

import json
import sys
from pathlib import Path
from typing import List, Dict, Any

from tinydb import TinyDB
from BetterJSONStorage import BetterJSONStorage

# Import our new CouchDB database functions
from rich_issue_mcp.database import save_issues, load_issues, convert_numpy_types


def load_tinydb_backup(backup_path: Path) -> List[Dict[str, Any]]:
    """Load issues from TinyDB backup file."""
    print(f"Loading TinyDB backup from: {backup_path}")
    
    if not backup_path.exists():
        raise FileNotFoundError(f"Backup file not found: {backup_path}")
    
    try:
        # Open with BetterJSONStorage (the same format as the backup)
        db = TinyDB(backup_path, storage=BetterJSONStorage)
        issues = db.all()
        db.close()
        
        print(f"Loaded {len(issues)} issues from TinyDB backup")
        return issues
        
    except Exception as e:
        print(f"Error loading TinyDB backup: {e}")
        raise


def validate_issue_data(issues: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Validate and clean issue data before migration."""
    print("Validating issue data...")
    
    valid_issues = []
    issues_with_problems = 0
    
    for issue in issues:
        # Check required fields
        if 'number' not in issue:
            issues_with_problems += 1
            continue
            
        # Convert numpy types to ensure JSON serialization
        cleaned_issue = convert_numpy_types(issue)
        valid_issues.append(cleaned_issue)
    
    print(f"Validation complete: {len(valid_issues)} valid issues, {issues_with_problems} issues with problems")
    return valid_issues


def migrate_to_couchdb(repo: str, issues: List[Dict[str, Any]], batch_size: int = 1000) -> None:
    """Migrate issues to CouchDB in batches."""
    print(f"Starting migration to CouchDB for repository: {repo}")
    print(f"Total issues to migrate: {len(issues)}")
    print(f"Batch size: {batch_size}")
    
    # Process in batches to avoid memory issues and provide progress updates
    total_batches = (len(issues) + batch_size - 1) // batch_size
    
    for batch_num in range(total_batches):
        start_idx = batch_num * batch_size
        end_idx = min(start_idx + batch_size, len(issues))
        batch = issues[start_idx:end_idx]
        
        print(f"Processing batch {batch_num + 1}/{total_batches} ({len(batch)} issues)...")
        
        if batch_num == 0:
            # First batch: use save_issues to clear any existing data
            save_issues(repo, batch)
        else:
            # Subsequent batches: use upsert to add to existing data
            from rich_issue_mcp.database import upsert_issues
            upsert_issues(repo, batch)
        
        print(f"  ✓ Batch {batch_num + 1} completed")
    
    print(f"Migration completed successfully!")


def verify_migration(repo: str, expected_count: int) -> bool:
    """Verify the migration was successful."""
    print("Verifying migration...")
    
    try:
        migrated_issues = load_issues(repo)
        migrated_count = len(migrated_issues)
        
        print(f"Expected issues: {expected_count}")
        print(f"Migrated issues: {migrated_count}")
        
        if migrated_count == expected_count:
            print("✅ Migration verification successful!")
            
            # Check a few sample issues
            if migrated_issues:
                sample_issue = migrated_issues[0]
                required_fields = ['number', 'title', 'state']
                enriched_fields = ['recommendations', 'embedding', 'engagements_quartile']
                
                print(f"Sample issue #{sample_issue.get('number', 'unknown')}:")
                print(f"  Title: {sample_issue.get('title', 'N/A')[:50]}...")
                print(f"  Has required fields: {all(field in sample_issue for field in required_fields)}")
                print(f"  Has enriched fields: {all(field in sample_issue for field in enriched_fields)}")
            
            return True
        else:
            print(f"❌ Migration verification failed: count mismatch")
            return False
            
    except Exception as e:
        print(f"❌ Migration verification failed: {e}")
        return False


def main():
    """Main migration function."""
    print("🔄 Starting TinyDB to CouchDB migration")
    print("=" * 50)
    
    # Configuration
    repo = "jupyterlab/jupyterlab"
    backup_path = Path("/home/generic/RichIssueMCP/data/issues-jupyterlab-jupyterlab-bak.db")
    batch_size = 1000
    
    try:
        # Step 1: Load TinyDB backup
        print("\n📂 Step 1: Loading TinyDB backup...")
        issues = load_tinydb_backup(backup_path)
        
        # Step 2: Validate data
        print("\n✅ Step 2: Validating data...")
        valid_issues = validate_issue_data(issues)
        
        # Step 3: Migrate to CouchDB
        print("\n🚀 Step 3: Migrating to CouchDB...")
        migrate_to_couchdb(repo, valid_issues, batch_size)
        
        # Step 4: Verify migration
        print("\n🔍 Step 4: Verifying migration...")
        success = verify_migration(repo, len(valid_issues))
        
        if success:
            print("\n🎉 Migration completed successfully!")
            print(f"Repository '{repo}' data is now available in CouchDB")
        else:
            print("\n❌ Migration completed with errors")
            sys.exit(1)
            
    except Exception as e:
        print(f"\n💥 Migration failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()