"""
Entity Management Script

Interactive CLI tool for viewing and editing entity descriptions and aliases.
Useful for quality control of the knowledge graph.

USAGE:
    python scripts/manage_entities.py [command] [args]

COMMANDS:
    list [--search QUERY] [--min-mentions N] [--limit N]
        List entities, optionally filtered

    view <entity_name_or_id>
        View entity details including description, aliases, and summaries

    edit <entity_name_or_id>
        Interactive edit of entity description and aliases

    describe <entity_name_or_id> "<description>"
        Set entity description directly

    alias <entity_name_or_id> add|remove|set <alias>
        Manage entity aliases

EXAMPLES:
    python scripts/manage_entities.py list --min-mentions 10
    python scripts/manage_entities.py view River_dog
    python scripts/manage_entities.py edit 18
    python scripts/manage_entities.py describe River_dog "User's beloved dog, a golden retriever"
    python scripts/manage_entities.py alias River_dog add "River"
"""

import sys
import json
import argparse
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.backend.config import load_config
from src.backend.database import Database
from src.backend.graph_database import GraphDatabase


def get_entity(graph_db, identifier):
    """Get entity by name or ID."""
    # Try as ID first
    try:
        entity_id = int(identifier)
        entity = graph_db.get_entity_by_id(entity_id)
        if entity:
            return entity
    except ValueError:
        pass

    # Try as name
    entity = graph_db.get_entity_by_name(identifier)
    if entity:
        return entity

    # Try as alias
    entity = graph_db.get_entity_by_alias(identifier)
    return entity


def cmd_list(args, db, graph_db):
    """List entities with optional filtering."""
    min_links = args.min_mentions or 1
    limit = args.limit or 50

    # Get entity link counts from message_entities table (more accurate than mention_count)
    query = """
        SELECT e.id, e.name, e.description, e.aliases,
               COUNT(me.id) as link_count
        FROM entities e
        LEFT JOIN message_entities me ON e.id = me.entity_id
        GROUP BY e.id
        HAVING link_count >= ?
        ORDER BY link_count DESC
        LIMIT ?
    """
    results = db.execute_query(query, (min_links, limit * 2))  # Get extra for filtering
    entities = [dict(row) for row in results]

    # Filter by search query if provided
    if args.search:
        search_lower = args.search.lower()
        entities = [
            e for e in entities
            if search_lower in e["name"].lower() or
               (e.get("description") and search_lower in e["description"].lower())
        ]

    # Limit results
    entities = entities[:limit]

    if not entities:
        print("No entities found matching criteria.")
        return

    # Display
    print(f"\n{'ID':>5} | {'Name':<30} | {'Links':>8} | Description")
    print("-" * 80)

    for e in entities:
        name = e["name"][:30]
        desc = (e.get("description") or "")[:40]
        if len(e.get("description") or "") > 40:
            desc += "..."
        print(f"{e['id']:>5} | {name:<30} | {e.get('link_count', 0):>8} | {desc}")

    print(f"\nShowing {len(entities)} entities (min {min_links} message links)")


def cmd_view(args, db, graph_db):
    """View detailed entity information."""
    entity = get_entity(graph_db, args.entity)

    if not entity:
        print(f"Entity not found: {args.entity}")
        return

    print("\n" + "=" * 60)
    print(f"ENTITY: {entity['name']}")
    print("=" * 60)

    print(f"\nID: {entity['id']}")
    print(f"Mention Count: {entity.get('mention_count', 0)}")
    print(f"First Mentioned: {entity.get('first_mentioned', 'N/A')[:10] if entity.get('first_mentioned') else 'N/A'}")
    print(f"Last Mentioned: {entity.get('last_mentioned', 'N/A')[:10] if entity.get('last_mentioned') else 'N/A'}")

    # Description
    print(f"\nDescription:")
    if entity.get("description"):
        print(f"  {entity['description']}")
    else:
        print("  (none)")

    # Aliases
    aliases = json.loads(entity["aliases"]) if entity.get("aliases") else []
    print(f"\nAliases: {', '.join(aliases) if aliases else '(none)'}")

    # Check for entity summaries
    summaries = db.get_all_summaries_for_entity(entity["id"])
    if summaries.get("all_time") or summaries.get("monthly"):
        print(f"\n--- Entity Summaries ---")
        if summaries.get("all_time"):
            alltime = summaries["all_time"]
            print(f"All-Time ({alltime.get('message_count', 0)} messages, {alltime.get('token_count', 0)} tokens):")
            # Show full summary
            summary_text = alltime.get("summary", "")
            # Indent each line for readability
            for line in summary_text.split('\n'):
                print(f"  {line}")

        if summaries.get("monthly"):
            print(f"\nMonthly Summaries: {len(summaries['monthly'])}")
            for m in summaries["monthly"][-3:]:  # Show last 3
                status = "current" if not m.get("is_frozen") else "frozen"
                print(f"  - {m.get('period_start')}: {m.get('message_count', 0)} msgs [{status}]")

    print()


def cmd_edit(args, db, graph_db):
    """Interactive edit of entity."""
    entity = get_entity(graph_db, args.entity)

    if not entity:
        print(f"Entity not found: {args.entity}")
        return

    print(f"\nEditing: {entity['name']} (ID: {entity['id']})")
    print("-" * 40)

    # Current values
    current_desc = entity.get("description") or ""
    current_aliases = json.loads(entity["aliases"]) if entity.get("aliases") else []

    print(f"Current description: {current_desc or '(none)'}")
    print(f"Current aliases: {', '.join(current_aliases) if current_aliases else '(none)'}")
    print()

    # Edit description
    print("Enter new description (or press Enter to keep current, 'clear' to remove):")
    new_desc = input("> ").strip()

    if new_desc.lower() == "clear":
        new_desc = ""
    elif new_desc == "":
        new_desc = None  # Keep current

    # Edit aliases
    print("\nEdit aliases? (y/n)")
    if input("> ").strip().lower() == "y":
        print(f"Current aliases: {current_aliases}")
        print("Enter new aliases (comma-separated, or press Enter to keep current):")
        alias_input = input("> ").strip()

        if alias_input:
            new_aliases = [a.strip() for a in alias_input.split(",") if a.strip()]
        else:
            new_aliases = None  # Keep current
    else:
        new_aliases = None

    # Apply changes
    if new_desc is not None or new_aliases is not None:
        graph_db.update_entity(
            entity["id"],
            description=new_desc,
            aliases=new_aliases
        )
        print("\n✓ Entity updated successfully!")

        # Show updated entity
        updated = graph_db.get_entity_by_id(entity["id"])
        print(f"  Description: {updated.get('description') or '(none)'}")
        updated_aliases = json.loads(updated["aliases"]) if updated.get("aliases") else []
        print(f"  Aliases: {', '.join(updated_aliases) if updated_aliases else '(none)'}")
    else:
        print("\nNo changes made.")


def cmd_describe(args, db, graph_db):
    """Set entity description directly."""
    entity = get_entity(graph_db, args.entity)

    if not entity:
        print(f"Entity not found: {args.entity}")
        return

    graph_db.update_entity(entity["id"], description=args.description)
    print(f"✓ Updated description for '{entity['name']}'")


def cmd_alias(args, db, graph_db):
    """Manage entity aliases."""
    entity = get_entity(graph_db, args.entity)

    if not entity:
        print(f"Entity not found: {args.entity}")
        return

    current_aliases = json.loads(entity["aliases"]) if entity.get("aliases") else []

    if args.action == "add":
        if args.alias not in current_aliases:
            current_aliases.append(args.alias)
            graph_db.update_entity(entity["id"], aliases=current_aliases)
            print(f"✓ Added alias '{args.alias}' to '{entity['name']}'")
        else:
            print(f"Alias '{args.alias}' already exists")

    elif args.action == "remove":
        if args.alias in current_aliases:
            current_aliases.remove(args.alias)
            graph_db.update_entity(entity["id"], aliases=current_aliases)
            print(f"✓ Removed alias '{args.alias}' from '{entity['name']}'")
        else:
            print(f"Alias '{args.alias}' not found")

    elif args.action == "set":
        new_aliases = [a.strip() for a in args.alias.split(",") if a.strip()]
        graph_db.update_entity(entity["id"], aliases=new_aliases)
        print(f"✓ Set aliases for '{entity['name']}': {new_aliases}")

    # Show current state
    updated = graph_db.get_entity_by_id(entity["id"])
    updated_aliases = json.loads(updated["aliases"]) if updated.get("aliases") else []
    print(f"  Current aliases: {', '.join(updated_aliases) if updated_aliases else '(none)'}")


def cmd_no_description(args, db, graph_db):
    """List entities without descriptions."""
    min_links = args.min_mentions or 20
    limit = args.limit or 30

    # Get entities without descriptions, ordered by link count
    query = """
        SELECT e.id, e.name, e.description,
               COUNT(me.id) as link_count
        FROM entities e
        LEFT JOIN message_entities me ON e.id = me.entity_id
        WHERE e.description IS NULL OR e.description = ''
        GROUP BY e.id
        HAVING link_count >= ?
        ORDER BY link_count DESC
        LIMIT ?
    """
    results = db.execute_query(query, (min_links, limit))
    no_desc = [dict(row) for row in results]

    if not no_desc:
        print(f"All entities with {min_links}+ links have descriptions!")
        return

    print(f"\n{'ID':>5} | {'Name':<35} | {'Links':>8}")
    print("-" * 55)

    for e in no_desc:
        print(f"{e['id']:>5} | {e['name']:<35} | {e.get('link_count', 0):>8}")

    print(f"\nShowing {len(no_desc)} entities without descriptions (min {min_links} links)")
    print("Use: python scripts/manage_entities.py edit <name> to add descriptions")


def main():
    parser = argparse.ArgumentParser(
        description="Manage entity descriptions and aliases",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # list command
    list_parser = subparsers.add_parser("list", help="List entities")
    list_parser.add_argument("--search", "-s", help="Search query")
    list_parser.add_argument("--min-mentions", "-m", type=int, help="Minimum mention count")
    list_parser.add_argument("--limit", "-l", type=int, help="Maximum results")

    # view command
    view_parser = subparsers.add_parser("view", help="View entity details")
    view_parser.add_argument("entity", help="Entity name or ID")

    # edit command
    edit_parser = subparsers.add_parser("edit", help="Edit entity interactively")
    edit_parser.add_argument("entity", help="Entity name or ID")

    # describe command
    describe_parser = subparsers.add_parser("describe", help="Set entity description")
    describe_parser.add_argument("entity", help="Entity name or ID")
    describe_parser.add_argument("description", help="New description")

    # alias command
    alias_parser = subparsers.add_parser("alias", help="Manage aliases")
    alias_parser.add_argument("entity", help="Entity name or ID")
    alias_parser.add_argument("action", choices=["add", "remove", "set"], help="Action")
    alias_parser.add_argument("alias", help="Alias to add/remove, or comma-separated list for set")

    # no-description command
    nodesc_parser = subparsers.add_parser("no-description", help="List entities without descriptions")
    nodesc_parser.add_argument("--min-mentions", "-m", type=int, help="Minimum mention count (default: 5)")
    nodesc_parser.add_argument("--limit", "-l", type=int, help="Maximum results")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    # Load config and initialize
    try:
        config = load_config()
        db = Database(config["storage"]["database_path"])
        graph_db = GraphDatabase(config)
    except Exception as e:
        print(f"Error initializing: {e}")
        sys.exit(1)

    # Dispatch command
    commands = {
        "list": cmd_list,
        "view": cmd_view,
        "edit": cmd_edit,
        "describe": cmd_describe,
        "alias": cmd_alias,
        "no-description": cmd_no_description,
    }

    if args.command in commands:
        commands[args.command](args, db, graph_db)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
