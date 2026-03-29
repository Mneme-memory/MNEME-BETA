#!/usr/bin/env python3
"""
Manage Entity Aliases in Knowledge Graph

This script allows you to view, add, remove, and split aliases.

USAGE:
    # View all entities with aliases
    python scripts/manage_aliases.py [database_path] --list

    # View specific entity's aliases
    python scripts/manage_aliases.py [database_path] --entity "API_costs"

    # Remove an alias from an entity
    python scripts/manage_aliases.py [database_path] --entity "API_costs" --remove-alias "API_cost_concerns"

    # Split alias into separate entity (undoes a merge)
    python scripts/manage_aliases.py [database_path] --entity "API_costs" --split-alias "API_cost_concerns"

    # Add an alias to an entity
    python scripts/manage_aliases.py [database_path] --entity "API_costs" --add-alias "api costs"
"""

import sys
import sqlite3
from pathlib import Path
import argparse
import json
from typing import List, Dict, Optional

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
from src.backend.config import load_config, get_database_path


def list_entities_with_aliases(db_path: str):
    """List all entities that have aliases."""

    if not Path(db_path).exists():
        print(f"Error: Database not found at {db_path}")
        sys.exit(1)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, name, aliases, mention_count
        FROM entities
        WHERE aliases IS NOT NULL AND aliases != '[]'
        ORDER BY mention_count DESC
    """)

    entities_with_aliases = cursor.fetchall()

    if not entities_with_aliases:
        print("No entities have aliases.")
        conn.close()
        return

    print(f"{'='*80}")
    print(f"ENTITIES WITH ALIASES ({len(entities_with_aliases)} total)")
    print(f"{'='*80}\n")

    for entity in entities_with_aliases:
        aliases = json.loads(entity['aliases']) if entity['aliases'] else []
        print(f"• {entity['name']} ({entity['mention_count']} mentions)")
        for alias in aliases:
            print(f"  └─ {alias}")
        print()

    conn.close()


def view_entity(db_path: str, entity_name: str):
    """View details of a specific entity including all aliases."""

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("SELECT id, name, aliases, mention_count FROM entities WHERE name = ?", (entity_name,))
    entity = cursor.fetchone()

    if not entity:
        print(f"Entity '{entity_name}' not found.")
        conn.close()
        return

    aliases = json.loads(entity['aliases']) if entity['aliases'] else []

    print(f"\n{'='*80}")
    print(f"ENTITY: {entity['name']}")
    print(f"{'='*80}")
    print(f"ID: {entity['id']}")
    print(f"Mentions: {entity['mention_count']}")
    print(f"Aliases: {len(aliases)}")

    if aliases:
        print(f"\nAlias list:")
        for i, alias in enumerate(aliases, 1):
            print(f"  {i}. {alias}")
    else:
        print("\nNo aliases.")

    # Show relationships
    cursor.execute("""
        SELECT COUNT(*) as count
        FROM relations
        WHERE source_id = ? OR target_id = ?
    """, (entity['id'], entity['id']))

    rel_count = cursor.fetchone()['count']
    print(f"\nRelationships: {rel_count}")

    conn.close()


def remove_alias(db_path: str, entity_name: str, alias_to_remove: str, dry_run: bool = False):
    """Remove an alias from an entity."""

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Get entity
    cursor.execute("SELECT id, name, aliases FROM entities WHERE name = ?", (entity_name,))
    entity = cursor.fetchone()

    if not entity:
        print(f"Entity '{entity_name}' not found.")
        conn.close()
        return

    aliases = json.loads(entity['aliases']) if entity['aliases'] else []

    if alias_to_remove not in aliases:
        print(f"Alias '{alias_to_remove}' not found in entity '{entity_name}'.")
        print(f"Current aliases: {aliases}")
        conn.close()
        return

    # Remove the alias
    new_aliases = [a for a in aliases if a != alias_to_remove]

    print(f"\n{'='*80}")
    print(f"REMOVE ALIAS")
    print(f"{'='*80}")
    print(f"Entity: {entity_name}")
    print(f"Remove: {alias_to_remove}")
    print(f"Before: {aliases}")
    print(f"After:  {new_aliases}")
    print(f"{'='*80}\n")

    if dry_run:
        print("[DRY RUN] No changes made.")
        conn.close()
        return

    # Confirm
    response = input("Proceed? (yes/no): ")
    if response.lower() != 'yes':
        print("Cancelled.")
        conn.close()
        return

    # Update database
    cursor.execute(
        "UPDATE entities SET aliases = ? WHERE id = ?",
        (json.dumps(new_aliases), entity['id'])
    )
    conn.commit()

    print(f"✓ Removed alias '{alias_to_remove}' from '{entity_name}'")
    conn.close()


def split_alias(db_path: str, entity_name: str, alias_to_split: str, dry_run: bool = False):
    """
    Split an alias into a separate entity (undo a merge).

    This creates a new entity with the alias name and moves relationships back.
    WARNING: This doesn't restore the original relationships - all relationships
    will remain on the canonical entity. Use this only to separate entities that
    shouldn't have been merged.
    """

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Get entity
    cursor.execute("SELECT id, name, aliases FROM entities WHERE name = ?", (entity_name,))
    entity = cursor.fetchone()

    if not entity:
        print(f"Entity '{entity_name}' not found.")
        conn.close()
        return

    aliases = json.loads(entity['aliases']) if entity['aliases'] else []

    if alias_to_split not in aliases:
        print(f"Alias '{alias_to_split}' not found in entity '{entity_name}'.")
        conn.close()
        return

    print(f"\n{'='*80}")
    print(f"SPLIT ALIAS INTO SEPARATE ENTITY")
    print(f"{'='*80}")
    print(f"Current entity: {entity_name}")
    print(f"Will create new entity: {alias_to_split}")
    print(f"\n⚠️  WARNING: All existing relationships will remain on '{entity_name}'")
    print(f"   The new entity '{alias_to_split}' will have NO relationships.")
    print(f"   Use this only to fix wrongly merged entities.")
    print(f"{'='*80}\n")

    if dry_run:
        print("[DRY RUN] No changes made.")
        conn.close()
        return

    # Confirm
    response = input("Proceed? (yes/no): ")
    if response.lower() != 'yes':
        print("Cancelled.")
        conn.close()
        return

    try:
        # Remove alias from current entity
        new_aliases = [a for a in aliases if a != alias_to_split]
        cursor.execute(
            "UPDATE entities SET aliases = ? WHERE id = ?",
            (json.dumps(new_aliases), entity['id'])
        )

        # Create new entity with alias name
        cursor.execute("""
            INSERT INTO entities (name, aliases, mention_count, first_mentioned, last_mentioned, metadata)
            VALUES (?, ?, ?, datetime('now'), datetime('now'), ?)
        """, (alias_to_split, json.dumps([]), 0, json.dumps({"split_from": entity_name})))

        conn.commit()

        print(f"✓ Split '{alias_to_split}' from '{entity_name}'")
        print(f"✓ Created new entity: '{alias_to_split}'")

    except Exception as e:
        conn.rollback()
        print(f"✗ Error: {e}")
    finally:
        conn.close()


def add_alias(db_path: str, entity_name: str, alias_to_add: str, dry_run: bool = False):
    """Add an alias to an entity."""

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Get entity
    cursor.execute("SELECT id, name, aliases FROM entities WHERE name = ?", (entity_name,))
    entity = cursor.fetchone()

    if not entity:
        print(f"Entity '{entity_name}' not found.")
        conn.close()
        return

    aliases = json.loads(entity['aliases']) if entity['aliases'] else []

    if alias_to_add in aliases:
        print(f"Alias '{alias_to_add}' already exists in entity '{entity_name}'.")
        conn.close()
        return

    # Check if alias exists as another entity
    cursor.execute("SELECT name FROM entities WHERE name = ?", (alias_to_add,))
    existing = cursor.fetchone()

    if existing:
        print(f"⚠️  WARNING: '{alias_to_add}' exists as a separate entity!")
        print(f"   Consider using --split-alias instead, or delete that entity first.")
        conn.close()
        return

    # Add the alias
    new_aliases = aliases + [alias_to_add]

    print(f"\n{'='*80}")
    print(f"ADD ALIAS")
    print(f"{'='*80}")
    print(f"Entity: {entity_name}")
    print(f"Add:    {alias_to_add}")
    print(f"Before: {aliases}")
    print(f"After:  {new_aliases}")
    print(f"{'='*80}\n")

    if dry_run:
        print("[DRY RUN] No changes made.")
        conn.close()
        return

    # Confirm
    response = input("Proceed? (yes/no): ")
    if response.lower() != 'yes':
        print("Cancelled.")
        conn.close()
        return

    # Update database
    cursor.execute(
        "UPDATE entities SET aliases = ? WHERE id = ?",
        (json.dumps(new_aliases), entity['id'])
    )
    conn.commit()

    print(f"✓ Added alias '{alias_to_add}' to '{entity_name}'")
    conn.close()


def main():
    parser = argparse.ArgumentParser(description="Manage entity aliases in knowledge graph")
    parser.add_argument('database', nargs='?', default=None, help='Path to database (default: from config.json)')
    parser.add_argument('--list', action='store_true', help='List all entities with aliases')
    parser.add_argument('--entity', type=str, help='Entity name to work with')
    parser.add_argument('--remove-alias', type=str, help='Remove this alias from the entity')
    parser.add_argument('--split-alias', type=str, help='Split this alias into a separate entity')
    parser.add_argument('--add-alias', type=str, help='Add this alias to the entity')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be done without doing it')

    args = parser.parse_args()

    # Get database path from args or config
    if args.database:
        db_path = args.database
    else:
        config = load_config()
        db_path = get_database_path(config)

    if not Path(db_path).exists():
        print(f"Error: Database not found at {db_path}")
        sys.exit(1)

    if args.list:
        list_entities_with_aliases(db_path)
    elif args.entity:
        if args.remove_alias:
            remove_alias(db_path, args.entity, args.remove_alias, args.dry_run)
        elif args.split_alias:
            split_alias(db_path, args.entity, args.split_alias, args.dry_run)
        elif args.add_alias:
            add_alias(db_path, args.entity, args.add_alias, args.dry_run)
        else:
            # Just view the entity
            view_entity(db_path, args.entity)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
