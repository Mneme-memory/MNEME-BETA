"""
Import an existing conversation into Mneme.

Reads a JSON export from Claude.ai or ChatGPT and imports messages into the
active profile's database, then runs the full enrichment pipeline: embeddings,
entity assignment (with importance scoring and descriptions), entity summaries,
and daily summaries.

USAGE:
    python scripts/import_conversation.py export.json
    python scripts/import_conversation.py export.json --dry-run
    python scripts/import_conversation.py export.json --skip-enrichment
    python scripts/import_conversation.py export.json --resume

EXPORT FORMAT:
    The script auto-detects the format. Supported:

    1. Claude.ai JSON (via browser extension export):
       [{"role": "human", "content": "...", "timestamp": "..."}, ...]
       or {"chat_messages": [{"sender": "human", "text": "...", ...}], ...}

    2. ChatGPT JSON export:
       {"mapping": {"id": {"message": {"role": "user", "content": {...}}}}}

    3. Simple format (array of messages):
       [{"role": "user|assistant", "content": "...", "timestamp": "..."}, ...]

COST WARNING:
    Enrichment (steps 3-5) uses API calls. Rough estimates for 1000 messages:
    - Embeddings: ~$0.01 (OpenAI)
    - Entity assignment + importance + descriptions: ~$0.30 (Haiku)
    - Entity summaries: ~$0.50-2.00 depending on entity count (Haiku)
    - Daily summaries: ~$0.15-0.50 depending on date range (Haiku)

    The script shows a cost estimate and asks for confirmation before proceeding.
"""

import sys
import os
import json
import time
import argparse
from pathlib import Path
from datetime import datetime, timezone

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.backend.config import load_config
from src.backend.database import Database
from src.backend.graph_database import GraphDatabase
from src.backend.embeddings import EmbeddingGenerator
from src.backend.entity_assignment import EntityAssigner
from src.backend.entity_summaries import EntitySummaryManager
from src.backend.daily_summaries import DailySummaryManager

try:
    import anthropic
except ImportError:
    print("Error: anthropic package not installed. Run: pip install anthropic")
    sys.exit(1)


# ============================================================================
# FORMAT DETECTION AND PARSING
# ============================================================================

def detect_and_parse(file_path: str) -> list:
    """
    Auto-detect export format and parse into a flat list of messages.

    Returns:
        List of dicts: [{"sender": "user"|"assistant", "content": str, "timestamp": str}, ...]
        Sorted by timestamp ascending.
    """
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    messages = []

    if isinstance(data, list):
        messages = _parse_message_array(data)
    elif isinstance(data, dict):
        if "chat_messages" in data:
            messages = _parse_claude_chat_messages(data)
        elif "mapping" in data:
            messages = _parse_chatgpt_mapping(data)
        elif "messages" in data and isinstance(data["messages"], list):
            messages = _parse_message_array(data["messages"])
        else:
            # Try to find any array of messages in the dict
            for key, value in data.items():
                if isinstance(value, list) and len(value) > 0:
                    if isinstance(value[0], dict) and any(
                        k in value[0] for k in ("role", "sender", "author")
                    ):
                        messages = _parse_message_array(value)
                        break

    if not messages:
        print("Error: Could not detect message format in the JSON file.")
        print("Expected: an array of messages with role/sender and content fields,")
        print("or a Claude.ai/ChatGPT export format.")
        sys.exit(1)

    # Sort by timestamp
    messages.sort(key=lambda m: m["timestamp"])

    return messages


def _normalize_role(role: str) -> str:
    """Map various role names to 'user' or 'assistant'."""
    role = role.lower().strip()
    if role in ("user", "human"):
        return "user"
    if role in ("assistant", "ai", "bot", "system"):
        return "assistant"
    return role


def _extract_timestamp(msg: dict) -> str:
    """Extract and normalize timestamp from a message dict."""
    for key in ("timestamp", "created_at", "create_time", "date", "time"):
        val = msg.get(key)
        if val:
            if isinstance(val, (int, float)):
                # Unix timestamp
                return datetime.fromtimestamp(val, tz=timezone.utc).isoformat()
            return str(val)

    # Fallback: use current time (messages will be ordered by array position)
    return datetime.now(timezone.utc).isoformat()


def _extract_content(msg: dict) -> str:
    """Extract text content from a message dict."""
    # Direct string content
    for key in ("content", "text", "body", "message"):
        val = msg.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()

    # ChatGPT nested content format: {"content": {"parts": ["text"]}}
    content = msg.get("content")
    if isinstance(content, dict):
        parts = content.get("parts", [])
        text_parts = [p for p in parts if isinstance(p, str)]
        if text_parts:
            return "\n".join(text_parts).strip()

    return ""


def _parse_message_array(messages: list) -> list:
    """Parse a flat array of message objects."""
    result = []
    for msg in messages:
        if not isinstance(msg, dict):
            continue

        role_raw = msg.get("role") or msg.get("sender") or msg.get("author") or ""
        sender = _normalize_role(role_raw)

        if sender not in ("user", "assistant"):
            continue

        content = _extract_content(msg)
        if not content:
            continue

        timestamp = _extract_timestamp(msg)

        result.append({
            "sender": sender,
            "content": content,
            "timestamp": timestamp,
        })

    return result


def _parse_claude_chat_messages(data: dict) -> list:
    """Parse Claude.ai's chat_messages format."""
    result = []
    for msg in data.get("chat_messages", []):
        if not isinstance(msg, dict):
            continue

        sender_raw = msg.get("sender") or msg.get("role") or ""
        sender = _normalize_role(sender_raw)

        if sender not in ("user", "assistant"):
            continue

        content = _extract_content(msg)
        if not content:
            continue

        timestamp = _extract_timestamp(msg)

        result.append({
            "sender": sender,
            "content": content,
            "timestamp": timestamp,
        })

    return result


def _parse_chatgpt_mapping(data: dict) -> list:
    """Parse ChatGPT's mapping format (nested tree of messages)."""
    result = []
    mapping = data.get("mapping", {})

    for node_id, node in mapping.items():
        msg = node.get("message")
        if not msg or not isinstance(msg, dict):
            continue

        author = msg.get("author", {})
        role_raw = author.get("role", "") if isinstance(author, dict) else str(author)
        sender = _normalize_role(role_raw)

        if sender not in ("user", "assistant"):
            continue

        content = _extract_content(msg)
        if not content:
            continue

        timestamp = _extract_timestamp(msg)

        result.append({
            "sender": sender,
            "content": content,
            "timestamp": timestamp,
        })

    return result


# ============================================================================
# STEP 1: INSERT MESSAGES
# ============================================================================

def insert_messages(db: Database, messages: list, config: dict) -> list:
    """
    Insert parsed messages into the database with correct tier assignment.

    Returns list of (message_id, message) tuples for further processing.
    """
    print(f"\n{'='*60}")
    print("STEP 1: Inserting messages")
    print(f"{'='*60}")

    # Calculate tiers: recent messages go to active, older ones to standard
    active_budget = config.get("context", {}).get("recent_context_tokens", 75000)

    # Count backwards to find the active/standard boundary
    token_count = 0
    active_start = len(messages)
    for i in range(len(messages) - 1, -1, -1):
        msg_tokens = len(messages[i]["content"]) // 4  # rough estimate
        token_count += msg_tokens
        if token_count <= active_budget:
            active_start = i
        else:
            break

    active_count = len(messages) - active_start
    standard_count = active_start

    print(f"  Total messages: {len(messages)}")
    print(f"  Active tier (recent): {active_count} messages")
    print(f"  Standard tier (older): {standard_count} messages")

    inserted = []
    skipped = 0

    for i, msg in enumerate(messages):
        tier = "active" if i >= active_start else "standard"

        try:
            message_id = db.add_message(
                sender=msg["sender"],
                content=msg["content"],
                timestamp=msg["timestamp"],
                importance_score=3.0,
                tier=tier,
                metadata={
                    "imported": True,
                    "import_date": datetime.now(timezone.utc).isoformat()
                }
            )
            inserted.append((message_id, msg))
        except Exception as e:
            print(f"  Warning: Failed to insert message {i}: {e}")
            skipped += 1

        if (i + 1) % 100 == 0:
            print(f"  Inserted {i + 1}/{len(messages)}...")

    print(f"\n  Inserted: {len(inserted)} messages")
    if skipped:
        print(f"  Skipped: {skipped}")

    return inserted


# ============================================================================
# STEP 2: GENERATE EMBEDDINGS
# ============================================================================

def generate_embeddings(db: Database, inserted: list, config: dict):
    """Generate OpenAI embeddings for all inserted messages."""
    print(f"\n{'='*60}")
    print("STEP 2: Generating embeddings")
    print(f"{'='*60}")

    api_key = config["api_keys"].get("openai")
    if not api_key:
        print("  Skipping: No OpenAI API key configured")
        return

    embedder = EmbeddingGenerator(api_key=api_key)
    success = 0
    failed = 0

    for i, (msg_id, msg) in enumerate(inserted):
        try:
            embedding = embedder.generate_embedding(msg["content"])
            embedding_id = db.add_embedding(
                vector=embedding,
                model=embedder.model,
                cost=0.0
            )
            db.update_message_embedding(msg_id, embedding_id)
            success += 1
        except Exception as e:
            failed += 1
            if failed <= 3:
                print(f"  Warning: Embedding failed for message {msg_id}: {e}")
            elif failed == 4:
                print(f"  (suppressing further embedding warnings)")

        if (i + 1) % 50 == 0:
            print(f"  Embedded {i + 1}/{len(inserted)}...")

    print(f"\n  Embedded: {success}/{len(inserted)} messages")
    if failed:
        print(f"  Failed: {failed}")


# ============================================================================
# STEP 3: ENTITY ASSIGNMENT (includes importance + descriptions)
# ============================================================================

def assign_entities(db: Database, graph_db: GraphDatabase, config: dict):
    """
    Run entity assignment on all unprocessed messages.
    This also assigns importance scores and generates descriptions.
    """
    print(f"\n{'='*60}")
    print("STEP 3: Entity assignment + importance scoring + descriptions")
    print(f"{'='*60}")

    api_key = config["api_keys"].get("anthropic")
    if not api_key:
        print("  Skipping: No Anthropic API key configured")
        return

    # Get canonical entities
    entity_stats = graph_db.get_entity_stats(min_mentions=0)
    canonical_entities = [e["name"] for e in entity_stats]
    print(f"  Existing entities: {len(canonical_entities)}")

    # Get unprocessed messages
    unlinked = db.execute_query("""
        SELECT m.id, m.sender, m.content, m.timestamp
        FROM messages m
        LEFT JOIN message_entities me ON m.id = me.message_id
        WHERE me.id IS NULL
          AND m.content != ''
          AND (m.metadata IS NULL OR json_extract(m.metadata, '$.temporary') IS NOT 1)
        ORDER BY m.timestamp ASC
    """)
    unlinked_messages = [dict(row) for row in unlinked]

    if not unlinked_messages:
        print("  All messages already processed")
        return

    print(f"  Messages to process: {len(unlinked_messages)}")

    batch_size = 30
    total_batches = (len(unlinked_messages) + batch_size - 1) // batch_size

    client = anthropic.Anthropic(api_key=api_key)
    assigner = EntityAssigner(client)

    total_links = 0
    total_new = 0
    errors = 0
    consecutive_errors = 0

    print(f"  Processing in {total_batches} batches of {batch_size}...\n")

    for i in range(0, len(unlinked_messages), batch_size):
        batch = unlinked_messages[i:i + batch_size]
        batch_num = i // batch_size + 1

        print(f"  Batch {batch_num}/{total_batches}...", end=" ", flush=True)

        try:
            (assignments, new_entities, importance_scores,
             alias_updates, descriptions, corrected_ids) = assigner.assign_and_discover_batch(
                batch, canonical_entities
            )

            # Store importance scores
            for msg in batch:
                msg_id = str(msg["id"])
                score = importance_scores.get(msg_id)
                if score and score != 3:
                    try:
                        db.update_message_importance(
                            msg["id"], score, "import_entity_assignment"
                        )
                    except Exception:
                        pass

            # Store descriptions in message metadata
            if descriptions:
                for msg in batch:
                    desc = descriptions.get(msg["id"])
                    if desc:
                        try:
                            db.update_message_metadata(msg["id"], {"description": desc})
                        except Exception:
                            pass

            # Create new entities
            batch_new = 0
            for new_ent in new_entities:
                existing = graph_db.get_entity_by_name(new_ent["name"])
                if not existing:
                    graph_db.add_entity(new_ent["name"])
                    canonical_entities.append(new_ent["name"])
                    batch_new += 1

            # Store entity links
            batch_links = 0
            for msg in batch:
                msg_id = str(msg["id"])
                for entity_info in assignments.get(msg_id, []):
                    entity = graph_db.get_entity_by_name(entity_info["entity"])
                    if entity:
                        try:
                            db.add_message_entity(
                                message_id=msg["id"],
                                entity_id=entity["id"],
                                confidence=entity_info["confidence"],
                                source="haiku"
                            )
                            batch_links += 1
                        except Exception:
                            pass

            # Store links for new entities
            for new_ent in new_entities:
                entity = graph_db.get_entity_by_name(new_ent["name"])
                if not entity:
                    continue
                for assignment in new_ent.get("assignments", []):
                    try:
                        db.add_message_entity(
                            message_id=int(assignment["message_id"]),
                            entity_id=entity["id"],
                            confidence=assignment["confidence"],
                            source="haiku"
                        )
                        batch_links += 1
                    except Exception:
                        pass

            total_links += batch_links
            total_new += batch_new
            consecutive_errors = 0

            new_note = f", +{batch_new} new entities" if batch_new else ""
            print(f"ok ({batch_links} links{new_note})")

            if i + batch_size < len(unlinked_messages):
                time.sleep(0.5)

        except Exception as e:
            errors += 1
            consecutive_errors += 1
            print(f"error: {type(e).__name__}: {str(e)[:80]}")

            if consecutive_errors >= 3:
                print("\n  Stopping: 3 consecutive errors")
                break

    print(f"\n  Entity links created: {total_links}")
    print(f"  New entities discovered: {total_new}")
    print(f"  Errors: {errors}")
    print(f"  Estimated cost: ${assigner.get_cost():.4f}")


# ============================================================================
# STEP 4: ENTITY SUMMARIES
# ============================================================================

def generate_entity_summaries(db: Database, graph_db: GraphDatabase, config: dict):
    """Generate summaries for all entities that have message links."""
    print(f"\n{'='*60}")
    print("STEP 4: Generating entity summaries")
    print(f"{'='*60}")

    api_key = config["api_keys"].get("anthropic")
    if not api_key:
        print("  Skipping: No Anthropic API key configured")
        return

    manager = EntitySummaryManager(config, db, graph_db)

    # Get entities that have message links but no summaries
    entities_with_links = db.execute_query("""
        SELECT DISTINCT e.id, e.name, COUNT(me.id) as link_count
        FROM entities e
        JOIN message_entities me ON e.id = me.entity_id
        LEFT JOIN entity_summaries es ON e.id = es.entity_id
        WHERE es.id IS NULL
        GROUP BY e.id
        HAVING link_count >= 3
        ORDER BY link_count DESC
    """)

    entities = [dict(row) for row in entities_with_links]

    if not entities:
        print("  All entities already have summaries (or none qualify)")
        return

    print(f"  Entities to summarize: {len(entities)}")
    print(f"  (Only entities with 3+ message links)")

    success = 0
    failed = 0

    for i, entity in enumerate(entities):
        print(f"  [{i+1}/{len(entities)}] {entity['name']} ({entity['link_count']} links)...", end=" ", flush=True)

        try:
            result = manager.bootstrap_entity_summaries(entity["id"], entity["name"])
            if result.get("success"):
                months = result.get("months_created", 0)
                print(f"ok ({months} months)")
                success += 1
            else:
                print(f"skipped: {result.get('message', 'unknown')}")
        except Exception as e:
            print(f"error: {str(e)[:60]}")
            failed += 1

        # Rate limit
        time.sleep(0.3)

    print(f"\n  Summaries created: {success}")
    if failed:
        print(f"  Failed: {failed}")


# ============================================================================
# STEP 5: DAILY SUMMARIES
# ============================================================================

def generate_daily_summaries(db: Database, config: dict):
    """Generate daily summaries for all dates with messages."""
    print(f"\n{'='*60}")
    print("STEP 5: Generating daily summaries")
    print(f"{'='*60}")

    api_key = config["api_keys"].get("anthropic")
    if not api_key:
        print("  Skipping: No Anthropic API key configured")
        return

    manager = DailySummaryManager(config, db)

    # Force enable for generation even if config has it disabled
    manager.enabled = True

    # Get all dates with messages
    dates = db.execute_query("""
        SELECT DISTINCT DATE(timestamp) as date
        FROM messages
        WHERE content != ''
        ORDER BY date ASC
    """)

    all_dates = [row["date"] for row in dates if row["date"]]

    # Filter out dates that already have summaries
    existing = db.execute_query("SELECT date FROM daily_summaries")
    existing_dates = {row["date"] for row in existing}

    dates_needed = [d for d in all_dates if d not in existing_dates]

    # Don't generate for today (it's still in progress)
    today = datetime.now().strftime("%Y-%m-%d")
    dates_needed = [d for d in dates_needed if d != today]

    if not dates_needed:
        print("  All dates already have summaries")
        return

    print(f"  Total dates with messages: {len(all_dates)}")
    print(f"  Already summarized: {len(existing_dates)}")
    print(f"  Dates to generate: {len(dates_needed)}")

    success = 0
    failed = 0

    for i, date in enumerate(dates_needed):
        print(f"  [{i+1}/{len(dates_needed)}] {date}...", end=" ", flush=True)

        try:
            result = manager.generate_summary(date, show_progress=False)
            if result:
                print("ok")
                success += 1
            else:
                print("skipped (no messages or error)")
        except Exception as e:
            print(f"error: {str(e)[:60]}")
            failed += 1

        time.sleep(0.3)

    print(f"\n  Summaries generated: {success}")
    if failed:
        print(f"  Failed: {failed}")


# ============================================================================
# COST ESTIMATION
# ============================================================================

def estimate_costs(message_count: int, db: Database = None, graph_db: GraphDatabase = None):
    """Print cost estimates for the enrichment pipeline."""
    batches = (message_count + 29) // 30

    embed_cost = message_count * 0.00001  # ~$0.01 per 1000 messages
    entity_cost = batches * 0.008  # ~$0.008 per batch of 30
    # Entity summaries: rough estimate based on expected entity count
    estimated_entities = min(message_count // 20, 200)  # ~1 entity per 20 messages
    summary_cost = estimated_entities * 0.015  # ~$0.015 per entity

    # Daily summaries: estimate unique days
    estimated_days = min(message_count // 5, 365)
    daily_cost = estimated_days * 0.005  # ~$0.005 per day

    total = embed_cost + entity_cost + summary_cost + daily_cost

    print(f"\n  Estimated costs:")
    print(f"    Embeddings (OpenAI):              ${embed_cost:.2f}")
    print(f"    Entity assignment (Haiku):         ${entity_cost:.2f}")
    print(f"    Entity summaries (~{estimated_entities} entities):  ${summary_cost:.2f}")
    print(f"    Daily summaries (~{estimated_days} days):     ${daily_cost:.2f}")
    print(f"    ─────────────────────────────────")
    print(f"    Estimated total:                   ${total:.2f}")
    print()
    print(f"  Time estimate: {message_count // 30 + estimated_entities + estimated_days} API calls")
    print(f"  (with rate limiting, roughly {(message_count // 30 + estimated_entities + estimated_days) // 60 + 1} minutes)")

    return total


# ============================================================================
# MAIN
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Import a conversation export into Mneme"
    )
    parser.add_argument(
        "file",
        help="Path to JSON export file"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and show stats without importing"
    )
    parser.add_argument(
        "--skip-enrichment",
        action="store_true",
        help="Only insert messages (skip embeddings, entities, summaries)"
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Skip message insertion, run enrichment on existing unprocessed messages"
    )
    parser.add_argument(
        "--profile",
        type=str,
        default=None,
        help="Import into a specific profile (default: active profile)"
    )

    args = parser.parse_args()

    if not Path(args.file).exists():
        print(f"Error: File not found: {args.file}")
        sys.exit(1)

    # Load config
    config = load_config()

    if args.profile:
        from src.backend.config import update_active_profile
        config = update_active_profile(config, args.profile)

    # Parse the export
    print(f"Parsing {args.file}...")
    messages = detect_and_parse(args.file)
    print(f"Found {len(messages)} messages")

    if len(messages) == 0:
        print("No messages found. Check the file format.")
        sys.exit(1)

    # Show summary
    first_ts = messages[0]["timestamp"][:10]
    last_ts = messages[-1]["timestamp"][:10]
    user_count = sum(1 for m in messages if m["sender"] == "user")
    assistant_count = sum(1 for m in messages if m["sender"] == "assistant")

    print(f"\n  Date range: {first_ts} to {last_ts}")
    print(f"  User messages: {user_count}")
    print(f"  Assistant messages: {assistant_count}")

    if args.dry_run:
        print("\n  DRY RUN — no changes made")
        estimate_costs(len(messages))
        sys.exit(0)

    # Initialize database
    db_path = config["storage"]["database_path"]
    db = Database(db_path)
    graph_db = GraphDatabase(config)

    if not args.resume:
        # Step 1: Insert messages
        inserted = insert_messages(db, messages, config)

        if not inserted:
            print("No messages were inserted.")
            sys.exit(1)
    else:
        print("\n  --resume: Skipping message insertion, running enrichment only")
        inserted = None  # enrichment steps query the DB directly

    if args.skip_enrichment:
        print(f"\n{'='*60}")
        print("IMPORT COMPLETE (enrichment skipped)")
        print(f"{'='*60}")
        print("\nTo run enrichment later:")
        print("  python scripts/import_conversation.py export.json --resume")
        sys.exit(0)

    # Cost estimate and confirmation
    msg_count = len(messages) if not args.resume else db.execute_query(
        "SELECT COUNT(*) as c FROM messages"
    )[0]["c"]

    estimate_costs(msg_count)

    print("  Enrichment uses Anthropic (Haiku) and OpenAI API calls.")
    print("  You can interrupt at any time and --resume later.\n")

    confirm = input("  Proceed with enrichment? [y/N] ").strip().lower()
    if confirm not in ("y", "yes"):
        print("\n  Enrichment skipped. Messages are imported.")
        print("  Run with --resume later to enrich.")
        sys.exit(0)

    # Step 2: Embeddings
    if inserted:
        generate_embeddings(db, inserted, config)
    else:
        # Resume mode: find messages without embeddings
        no_embed = db.execute_query("""
            SELECT m.id, m.sender, m.content, m.timestamp
            FROM messages m
            WHERE m.embedding_id IS NULL AND m.content != ''
            ORDER BY m.timestamp ASC
        """)
        embed_list = [(row["id"], dict(row)) for row in no_embed]
        if embed_list:
            generate_embeddings(db, embed_list, config)
        else:
            print("\n  Embeddings: all messages already embedded")

    # Step 3: Entity assignment
    assign_entities(db, graph_db, config)

    # Step 4: Entity summaries
    generate_entity_summaries(db, graph_db, config)

    # Step 5: Daily summaries
    generate_daily_summaries(db, config)

    # Done
    print(f"\n{'='*60}")
    print("IMPORT COMPLETE")
    print(f"{'='*60}")
    print(f"\nYour conversation has been imported into profile '{config['storage']['active_profile']}'.")
    print(f"Start Mneme and the AI will have full context of your history.")
    print(f"\nNote: Narrative concepts (@concept) are not backfilled —")
    print(f"the AI will create them organically as you continue chatting.")


if __name__ == "__main__":
    main()
