#!/usr/bin/env python3
"""
Diagnose Context Loading Issues

Checks what's actually in conversation_history and how it's being processed.

USAGE:
    python scripts/diagnose_context.py
"""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.backend.database import Database
from src.backend.config import load_config, get_database_path
from src.backend.context import ContextAssembler
from src.backend.embeddings import EmbeddingGenerator


def analyze_messages(db: Database):
    """Analyze message distribution and characteristics."""

    # Get tier counts
    print("\n=== MESSAGE TIER DISTRIBUTION ===")
    tier_counts = db.execute_query("""
        SELECT tier, COUNT(*) as count
        FROM messages
        GROUP BY tier
    """)
    for row in tier_counts:
        print(f"{row['tier']}: {row['count']} messages")

    # Get total
    total = db.get_message_count()
    print(f"Total: {total} messages")

    # Check for temporary messages
    print("\n=== TEMPORARY MESSAGE ANALYSIS ===")
    temp_in_active = db.execute_query("""
        SELECT COUNT(*) as count
        FROM messages
        WHERE tier = 'active'
        AND json_extract(metadata, '$.temporary') = 1
    """)
    print(f"Temporary messages in active tier: {temp_in_active[0]['count']}")

    # Check for command messages
    print("\n=== COMMAND MESSAGE ANALYSIS ===")
    command_msgs = db.execute_query("""
        SELECT COUNT(*) as count
        FROM messages
        WHERE sender = 'user'
        AND content LIKE '@%'
        AND tier = 'active'
    """)
    print(f"Command messages in active tier: {command_msgs[0]['count']}")

    # Get recent 150 messages with details
    print("\n=== RECENT MESSAGE SAMPLE ===")
    recent = db.execute_query("""
        SELECT id, sender,
               SUBSTR(content, 1, 60) as content_preview,
               length(content) as content_length,
               tier,
               metadata
        FROM messages
        WHERE tier = 'active'
        ORDER BY timestamp DESC
        LIMIT 20
    """)

    for i, msg in enumerate(recent, 1):
        temp_flag = ""
        if msg['metadata']:
            import json
            try:
                meta = json.loads(msg['metadata'])
                if meta.get('temporary'):
                    temp_flag = " [TEMP]"
            except:
                pass

        print(f"{i}. ID={msg['id']}, {msg['sender']}, len={msg['content_length']}{temp_flag}")
        print(f"   \"{msg['content_preview']}...\"")


def simulate_context_loading(db: Database, config: dict):
    """Simulate what ConversationManager does on startup."""

    print("\n=== SIMULATING CONTEXT LOADING ===")

    # Create context assembler
    embedder = EmbeddingGenerator(config)
    context_assembler = ContextAssembler(db, embedder, config)

    recent_budget = config.get("context", {}).get("recent_messages_tokens", 70000)
    print(f"Recent context budget: {recent_budget:,} tokens")

    # Load recent messages (simulating _load_recent_context)
    all_recent = db.get_recent_messages(limit=10000)
    print(f"Retrieved from DB: {len(all_recent)} messages")

    # Count tokens backwards
    context_msgs = []
    total_tokens = 0

    for msg in all_recent:
        msg_text = msg["content"]
        msg_tokens = context_assembler.count_tokens(msg_text)

        if total_tokens + msg_tokens > recent_budget:
            break

        context_msgs.append(msg)
        total_tokens += msg_tokens

    context_msgs.reverse()  # Chronological order

    print(f"Loaded into conversation_history: {len(context_msgs)} messages")
    print(f"Total tokens: {total_tokens:,} / {recent_budget:,}")

    # Check for temporary messages in loaded context
    temp_count = 0
    command_count = 0
    for msg in context_msgs:
        if msg.get('metadata'):
            import json
            try:
                meta = json.loads(msg['metadata'])
                if meta.get('temporary'):
                    temp_count += 1
            except:
                pass

        if msg['sender'] == 'user' and msg['content'].startswith('@'):
            command_count += 1

    print(f"Temporary messages in loaded context: {temp_count}")
    print(f"Command messages in loaded context: {command_count}")

    # Simulate filtering (what cache structure does)
    import json
    filtered = []
    for msg in context_msgs:
        # Check if temporary flag is set
        is_temp = False
        if msg.get('metadata'):
            try:
                if isinstance(msg['metadata'], str):
                    meta = json.loads(msg['metadata'])
                else:
                    meta = msg['metadata']
                is_temp = meta.get('temporary', False)
            except:
                pass

        if not is_temp:
            filtered.append(msg)

    print(f"\nAfter filtering temporary messages: {len(filtered)} messages would go to API")

    return context_msgs, filtered


def main():
    print("=" * 60)
    print("Mneme Context Diagnostic Tool")
    print("=" * 60)

    try:
        config = load_config()
        db_path = get_database_path(config)
        print(f"\nDatabase: {db_path}")

        active_profile = config.get("storage", {}).get("active_profile", None)
        if active_profile:
            print(f"Active profile: {active_profile}")

        if not os.path.exists(db_path):
            print(f"\n✗ Database file not found: {db_path}")
            return 1

        db = Database(db_path)

        # Run analyses
        analyze_messages(db)
        loaded, filtered = simulate_context_loading(db, config)

        # Summary
        print("\n" + "=" * 60)
        print("DIAGNOSIS SUMMARY")
        print("=" * 60)

        print(f"\nMessages loaded: {len(loaded)}")
        print(f"Messages after filtering: {len(filtered)}")
        print(f"Difference: {len(loaded) - len(filtered)} messages filtered out")

        if len(filtered) < 50:
            print("\n⚠️  WARNING: Very few messages would be visible to AI!")
            print("   This could be due to:")
            print("   - Many temporary command messages")
            print("   - Token budget too small")
            print("   - Messages too large")

        return 0

    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
