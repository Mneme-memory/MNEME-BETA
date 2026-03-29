#!/usr/bin/env python3
"""
List all entities in the knowledge graph.

Usage:
    python scripts/list_entities.py [database_path]

If no path provided, uses the database path from config.json
"""

import sys
import sqlite3
from pathlib import Path

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
from src.backend.config import load_config, get_database_path

def list_entities(db_path: str):
    """List all entities with their mention counts and aliases."""

    if not Path(db_path).exists():
        print(f"Error: Database not found at {db_path}")
        sys.exit(1)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Get all entities sorted by actual message link count
    cursor.execute("""
        SELECT e.name, e.aliases, e.mention_count, e.first_mentioned, e.last_mentioned,
               COUNT(me.message_id) as link_count
        FROM entities e
        LEFT JOIN message_entities me ON e.id = me.entity_id
        GROUP BY e.id
        ORDER BY link_count DESC
    """)

    entities = cursor.fetchall()

    print(f"Total entities: {len(entities)}\n")

    # Show top 50
    print("="*80)
    print("TOP 50 ENTITIES (by mention count)")
    print("="*80)
    for i, entity in enumerate(entities[:50], 1):
        try:
            aliases = eval(entity['aliases']) if entity['aliases'] else []
            alias_str = f" (aliases: {', '.join(aliases[:3])})" if aliases else ''
            # Handle encoding issues in entity names
            name = entity['name'].encode('utf-8', errors='replace').decode('utf-8', errors='replace')
            print(f"{i:3}. {name:40} - {entity['link_count']:4} messages{alias_str}")
        except Exception as e:
            print(f"{i:3}. [CORRUPTED ENTITY] - {entity['link_count']:4} messages")

    print(f"\n... and {len(entities) - 50} more entities\n")

    # Show bottom 30 (likely noise)
    print("="*80)
    print("BOTTOM 30 ENTITIES (likely noise to clean up)")
    print("="*80)
    for i, entity in enumerate(entities[-30:], 1):
        try:
            aliases = eval(entity['aliases']) if entity['aliases'] else []
            alias_str = f" (aliases: {', '.join(aliases[:3])})" if aliases else ''
            # Handle encoding issues in entity names
            name = entity['name'].encode('utf-8', errors='replace').decode('utf-8', errors='replace')
            print(f"{i:3}. {name:40} - {entity['link_count']:4} messages{alias_str}")
        except Exception as e:
            print(f"{i:3}. [CORRUPTED ENTITY] - {entity['link_count']:4} messages")

    # Statistics by mention count
    print("\n" + "="*80)
    print("DISTRIBUTION BY MENTION COUNT")
    print("="*80)

    mention_ranges = {
        "0 messages": 0,
        "1-5 messages": 0,
        "6-20 messages": 0,
        "21-50 messages": 0,
        "51-200 messages": 0,
        "201+ messages": 0
    }

    for entity in entities:
        count = entity['link_count']
        if count == 0:
            mention_ranges["0 messages"] += 1
        elif count <= 5:
            mention_ranges["1-5 messages"] += 1
        elif count <= 20:
            mention_ranges["6-20 messages"] += 1
        elif count <= 50:
            mention_ranges["21-50 messages"] += 1
        elif count <= 200:
            mention_ranges["51-200 messages"] += 1
        else:
            mention_ranges["201+ messages"] += 1

    for range_name, count in mention_ranges.items():
        print(f"{range_name:20}: {count:4} entities")

    # Export full list
    export_path = Path(__file__).parent.parent / "entity_list.txt"
    with open(export_path, 'w', encoding='utf-8', errors='replace') as f:
        f.write(f"Full Entity List ({len(entities)} total)\n")
        f.write("="*80 + "\n\n")
        for i, entity in enumerate(entities, 1):
            try:
                aliases = eval(entity['aliases']) if entity['aliases'] else []
                alias_str = f" | Aliases: {', '.join(aliases)}" if aliases else ''
                # Encode/decode to handle surrogates
                name = entity['name'].encode('utf-8', errors='replace').decode('utf-8', errors='replace')
                f.write(f"{i}. {name} ({entity['link_count']} messages){alias_str}\n")
            except Exception as e:
                # Skip corrupted entries
                f.write(f"{i}. [CORRUPTED ENTITY - skipped]\n")

    print(f"\n✓ Full list exported to: {export_path}")

    conn.close()

if __name__ == "__main__":
    if len(sys.argv) > 1:
        db_path = sys.argv[1]
    else:
        config = load_config()
        db_path = get_database_path(config)
    list_entities(db_path)
