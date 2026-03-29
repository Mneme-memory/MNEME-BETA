"""
Regenerate specific entity summaries that were botched by Haiku refusals.

Usage:
    # Regenerate October 2025 monthly + all-time for "Anthropic" (entity 1633):
    python scripts/regenerate_entity_summaries.py --entity-id 1633 --months 2025-10

    # Regenerate all-time only (keeps monthly summaries):
    python scripts/regenerate_entity_summaries.py --entity-id 1633 --alltime-only

    # Regenerate everything for an entity (all months + all-time):
    python scripts/regenerate_entity_summaries.py --entity-id 1633 --all

    # Dry run — show what would be regenerated without doing it:
    python scripts/regenerate_entity_summaries.py --entity-id 1633 --months 2025-10 --dry-run

    # Scan all summaries for refusal patterns:
    python scripts/regenerate_entity_summaries.py --scan
"""

import sys
import os
import json
import argparse
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.backend.entity_summaries import EntitySummaryManager, _is_refusal


def load_config():
    from src.backend.config import load_config as _load_config
    return _load_config()


def get_db_and_graph(config):
    from src.backend.database import Database
    from src.backend.graph_database import GraphDatabase

    db_path = config["storage"]["database_path"]
    db = Database(db_path)
    graph_db = GraphDatabase(config)
    return db, graph_db


def scan_for_refusals(db):
    """Scan all entity summaries for refusal patterns."""
    rows = db.execute_query("""
        SELECT es.id, es.entity_id, e.name, es.period_type, es.period_start, es.summary
        FROM entity_summaries es
        JOIN entities e ON e.id = es.entity_id
        ORDER BY e.name, es.period_type, es.period_start
    """)

    found = 0
    for row in rows:
        summary_id, entity_id, entity_name, period_type, period_start, summary = (
            row["id"], row["entity_id"], row["name"], row["period_type"],
            row["period_start"], row["summary"]
        )
        if summary and _is_refusal(summary):
            found += 1
            period_label = period_start if period_type == "month" else "all_time"
            print(f"\n{'='*60}")
            print(f"REFUSAL DETECTED: {entity_name} (id={entity_id}) [{period_label}]")
            print(f"Summary ID: {summary_id}")
            print(f"Preview: {summary[:200]}...")
            print(f"{'='*60}")

    if found == 0:
        print("No refusals detected in any entity summaries.")
    else:
        print(f"\nFound {found} refusal(s) total.")
    return found


def regenerate_months(manager, db, entity_id, entity_name, months, dry_run=False):
    """Regenerate specific monthly summaries."""
    for month in months:
        # Check existing
        existing = db.get_entity_summary(entity_id, "month", month)
        if existing:
            is_refused = _is_refusal(existing.get("summary", ""))
            print(f"\n  Month {month}: exists (frozen={existing.get('is_frozen')}, refusal={is_refused})")
            print(f"    Preview: {existing.get('summary', '')[:150]}...")
        else:
            print(f"\n  Month {month}: no existing summary")

        if dry_run:
            print(f"    [DRY RUN] Would regenerate {month}")
            continue

        # Delete existing summary for this month
        if existing:
            print(f"    Deleting old summary...")
            db.delete_entity_summary(entity_id, "month", month)

        # Regenerate
        print(f"    Regenerating {month}...", end=" ", flush=True)
        messages = db.get_messages_for_entity_by_month(entity_id, month)
        if not messages:
            print(f"no messages found!")
            continue

        formatted = manager._format_messages_for_prompt(messages)
        month_display = manager._format_month(month)

        from src.backend.entity_summaries import MONTHLY_SUMMARY_PROMPT
        prompt = MONTHLY_SUMMARY_PROMPT.format(
            entity_name=entity_name,
            month_year=month_display,
            messages=formatted
        )

        try:
            summary_text = manager._call_haiku(prompt)

            current_month = manager._get_current_month()
            is_frozen = month != current_month

            db.save_entity_summary(
                entity_id=entity_id,
                period_type="month",
                summary=summary_text,
                message_count=len(messages),
                token_count=manager.count_tokens(summary_text),
                last_message_id=messages[-1].get("id"),
                is_frozen=is_frozen,
                period_start=month
            )
            print(f"done ({len(summary_text)} chars)")
            print(f"    Preview: {summary_text[:150]}...")

        except Exception as e:
            print(f"FAILED: {e}")


def regenerate_alltime(manager, entity_id, dry_run=False):
    """Regenerate all-time summary from existing monthlies."""
    if dry_run:
        print(f"\n  [DRY RUN] Would regenerate all-time summary")
        return

    print(f"\n  Regenerating all-time summary...", end=" ", flush=True)

    # Delete existing all-time
    manager.db.delete_entity_summary(entity_id, "all_time")

    result = manager.regenerate_alltime(entity_id)
    if result.get("success"):
        print(f"done (from {result.get('monthly_count', '?')} months)")
        # Read it back
        alltime = manager.db.get_entity_summary(entity_id, "all_time")
        if alltime:
            print(f"    Preview: {alltime.get('summary', '')[:200]}...")
    else:
        print(f"FAILED: {result.get('error', 'unknown')}")


def main():
    parser = argparse.ArgumentParser(description="Regenerate entity summaries")
    parser.add_argument("--entity-id", type=int, help="Entity ID to regenerate")
    parser.add_argument("--months", nargs="+", help="Specific months to regenerate (YYYY-MM)")
    parser.add_argument("--alltime-only", action="store_true", help="Only regenerate all-time summary")
    parser.add_argument("--all", action="store_true", help="Regenerate all months + all-time")
    parser.add_argument("--scan", action="store_true", help="Scan all summaries for refusal patterns")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without doing it")
    args = parser.parse_args()

    config = load_config()
    db, graph_db = get_db_and_graph(config)

    if args.scan:
        scan_for_refusals(db)
        return

    if not args.entity_id:
        parser.error("--entity-id is required (unless using --scan)")

    entity = graph_db.get_entity_by_id(args.entity_id)
    if not entity:
        print(f"Entity {args.entity_id} not found!")
        return

    entity_name = entity.get("name", f"Entity {args.entity_id}")
    print(f"Entity: {entity_name} (id={args.entity_id})")

    manager = EntitySummaryManager(config, db, graph_db)

    if args.all:
        # Get all months for this entity
        all_data = db.get_all_summaries_for_entity(args.entity_id)
        months = [s.get("period_start") for s in all_data.get("monthly", []) if s.get("period_start")]
        if not months:
            months = db.get_entity_months(args.entity_id)
        print(f"Regenerating ALL months: {months}")
        regenerate_months(manager, db, args.entity_id, entity_name, months, args.dry_run)
        regenerate_alltime(manager, args.entity_id, args.dry_run)

    elif args.alltime_only:
        regenerate_alltime(manager, args.entity_id, args.dry_run)

    elif args.months:
        regenerate_months(manager, db, args.entity_id, entity_name, args.months, args.dry_run)
        # Always regenerate all-time after fixing months
        regenerate_alltime(manager, args.entity_id, args.dry_run)

    else:
        parser.error("Specify --months, --alltime-only, --all, or --scan")

    print(f"\nAPI stats: {manager.stats}")


if __name__ == "__main__":
    main()
