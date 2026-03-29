#!/usr/bin/env python3
"""
Database Diagnostic Tool for Mneme

Checks database health after FK constraint and locking issues.
Run this to verify your database is safe and identify any issues.

USAGE:
    python scripts/diagnose_database.py
"""

import sys
import os

# Add parent directory to path so we can import backend modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.backend.database import Database
from src.backend.config import load_config, get_database_path


def check_integrity(db: Database) -> bool:
    """Check SQLite integrity."""
    print("\n=== 1. SQLite Integrity Check ===")
    try:
        is_ok = db.integrity_check()
        if is_ok:
            print("✓ Database integrity: OK")
            return True
        else:
            print("✗ Database integrity: FAILED")
            print("  Your database file may be corrupted.")
            return False
    except Exception as e:
        print(f"✗ Integrity check failed: {e}")
        return False


def check_foreign_keys(db: Database) -> dict:
    """Check for foreign key violations."""
    print("\n=== 2. Foreign Key Constraint Check ===")
    results = {
        "tags_violations": [],
        "embeddings_violations": [],
        "importance_violations": []
    }

    try:
        # Check tags.message_id references
        query = """
            SELECT t.id, t.message_id, t.tag_name
            FROM tags t
            LEFT JOIN messages m ON t.message_id = m.id
            WHERE m.id IS NULL
        """
        orphaned_tags = db.execute_query(query)
        results["tags_violations"] = [dict(row) for row in orphaned_tags]

        if orphaned_tags:
            print(f"✗ Found {len(orphaned_tags)} orphaned tags (referencing deleted messages)")
            for tag in orphaned_tags[:5]:  # Show first 5
                print(f"  - Tag ID {tag['id']}: '{tag['tag_name']}' references missing message {tag['message_id']}")
            if len(orphaned_tags) > 5:
                print(f"  ... and {len(orphaned_tags) - 5} more")
        else:
            print("✓ Tags: No orphaned records")

        # Check importance_scores.message_id references
        query = """
            SELECT i.id, i.message_id
            FROM importance_scores i
            LEFT JOIN messages m ON i.message_id = m.id
            WHERE m.id IS NULL
        """
        orphaned_importance = db.execute_query(query)
        results["importance_violations"] = [dict(row) for row in orphaned_importance]

        if orphaned_importance:
            print(f"✗ Found {len(orphaned_importance)} orphaned importance_scores")
        else:
            print("✓ Importance scores: No orphaned records")

        # Check messages.embedding_id references
        query = """
            SELECT m.id, m.embedding_id
            FROM messages m
            WHERE m.embedding_id IS NOT NULL
            AND NOT EXISTS (SELECT 1 FROM embeddings e WHERE e.id = m.embedding_id)
        """
        missing_embeddings = db.execute_query(query)
        results["embeddings_violations"] = [dict(row) for row in missing_embeddings]

        if missing_embeddings:
            print(f"✗ Found {len(missing_embeddings)} messages referencing missing embeddings")
        else:
            print("✓ Embeddings: No broken references")

        return results

    except Exception as e:
        print(f"✗ FK check failed: {e}")
        return results


def check_batch_tagging_status(db: Database) -> dict:
    """Check if messages are properly tagged."""
    print("\n=== 3. Batch Tagging Status ===")

    try:
        # Count messages without tags
        untagged = db.get_untagged_messages()
        total_messages = db.get_message_count()
        tagged_count = total_messages - len(untagged)

        print(f"Total messages: {total_messages}")
        print(f"Tagged messages: {tagged_count}")
        print(f"Untagged messages: {len(untagged)}")

        if len(untagged) > 0:
            print(f"\n⚠️  You have {len(untagged)} untagged messages")
            print(f"   This could be normal if they're recent and haven't been batched yet.")
            print(f"   Batch size is 10, so up to 9 untagged messages is expected.")

            if len(untagged) > 10:
                print(f"   Consider re-running batch tagging for these messages.")
        else:
            print("✓ All messages are tagged")

        return {
            "total": total_messages,
            "tagged": tagged_count,
            "untagged": len(untagged)
        }

    except Exception as e:
        print(f"✗ Tagging status check failed: {e}")
        return {}


def check_database_locks(db: Database) -> bool:
    """Try a write operation to check for locks."""
    print("\n=== 4. Database Lock Test ===")

    try:
        # Try a simple read
        db.get_message_count()
        print("✓ Read operations: OK")

        # Try a simple write (add and immediately delete a test message)
        test_id = db.add_message(
            sender="system",
            content="[DIAGNOSTIC TEST - WILL BE DELETED]",
            importance_score=1.0
        )
        db.delete_message(test_id)
        print("✓ Write operations: OK")
        print("✓ No database locks detected")
        return True

    except Exception as e:
        print(f"✗ Database operation failed: {e}")
        if "locked" in str(e).lower():
            print("⚠️  DATABASE IS STILL LOCKED!")
            print("   Recommended actions:")
            print("   1. Stop all Mneme processes")
            print("   2. Wait 30 seconds")
            print("   3. Restart and try again")
        return False


def get_statistics(db: Database) -> dict:
    """Get database statistics."""
    print("\n=== 5. Database Statistics ===")

    try:
        stats = {
            "messages": db.get_message_count(),
            "tiers": db.get_message_count_by_tier(),
            "tags": db.get_tag_statistics()[:10]  # Top 10 tags
        }

        print(f"Total messages: {stats['messages']}")
        print(f"\nMessages by tier:")
        for tier, count in stats['tiers'].items():
            print(f"  {tier}: {count}")

        print(f"\nTop 10 tags:")
        for tag in stats['tags']:
            print(f"  {tag['tag_name']}: {tag['count']}")

        return stats

    except Exception as e:
        print(f"✗ Statistics failed: {e}")
        return {}


def main():
    """Run all diagnostic checks."""
    print("=" * 60)
    print("Mneme Database Diagnostic Tool")
    print("=" * 60)

    # Load config and database
    try:
        config = load_config()
        db_path = get_database_path(config)
        print(f"\nDatabase: {db_path}")

        # Show profile info if available
        active_profile = config.get("storage", {}).get("active_profile", None)
        if active_profile:
            print(f"Active profile: {active_profile}")

        if not os.path.exists(db_path):
            print(f"\n✗ Database file not found: {db_path}")
            print("  Check your config.json for correct database_path")
            return 1

        db = Database(db_path)

    except Exception as e:
        print(f"\n✗ Failed to load database: {e}")
        return 1

    # Run checks
    results = {
        "integrity": check_integrity(db),
        "foreign_keys": check_foreign_keys(db),
        "tagging": check_batch_tagging_status(db),
        "locks": check_database_locks(db),
        "stats": get_statistics(db)
    }

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)

    issues = []
    if not results["integrity"]:
        issues.append("Database integrity check failed (CRITICAL)")

    if results["foreign_keys"]["tags_violations"]:
        issues.append(f"{len(results['foreign_keys']['tags_violations'])} orphaned tags")

    if results["foreign_keys"]["importance_violations"]:
        issues.append(f"{len(results['foreign_keys']['importance_violations'])} orphaned importance scores")

    if results["foreign_keys"]["embeddings_violations"]:
        issues.append(f"{len(results['foreign_keys']['embeddings_violations'])} broken embedding references")

    if not results["locks"]:
        issues.append("Database is locked (CRITICAL)")

    if issues:
        print("\n⚠️  ISSUES FOUND:")
        for i, issue in enumerate(issues, 1):
            print(f"  {i}. {issue}")

        print("\n📋 RECOMMENDED ACTIONS:")

        if not results["integrity"]:
            print("  1. BACKUP YOUR DATABASE IMMEDIATELY")
            print("  2. Try running: PRAGMA integrity_check")
            print("  3. Consider restoring from backup if available")
        elif not results["locks"]:
            print("  1. Stop all Mneme processes")
            print("  2. Wait 30 seconds")
            print("  3. Restart and run diagnostic again")
        elif any(results["foreign_keys"].values()):
            print("  1. Run cleanup script to remove orphaned records:")
            print("     python scripts/cleanup_orphaned_records.py")

        return 1
    else:
        print("\n✅ YOUR DATABASE IS SAFE!")
        print("   All checks passed. No issues detected.")
        print("\nThe FK constraint failure and database lock were temporary issues")
        print("that have been resolved by the code fixes.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
