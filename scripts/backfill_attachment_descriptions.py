"""
Backfill ai_description into attachment metadata.json files.

Previously, descriptions were only stored in SQLite. This syncs them
to the on-disk metadata.json so @run scripts can find files by description.

Usage:
    python scripts/backfill_attachment_descriptions.py
    python scripts/backfill_attachment_descriptions.py --dry-run
"""

import sys
import json
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def load_config():
    from src.backend.config import load_config as _load_config
    return _load_config()


def main():
    dry_run = "--dry-run" in sys.argv

    config = load_config()

    from src.backend.database import Database
    db = Database(config["storage"]["database_path"])

    # Get all attachments that have descriptions
    rows = db.execute_query("""
        SELECT uuid, filename, ai_description
        FROM attachments
        WHERE ai_description IS NOT NULL
    """)

    if not rows:
        print("No attachments with descriptions found.")
        return

    profile = config.get("storage", {}).get("active_profile", "main")
    attachments_dir = Path("data") / profile / "attachments"

    updated = 0
    skipped = 0
    missing = 0

    for row in rows:
        file_uuid = row["uuid"]
        description = row["ai_description"]
        filename = row["filename"]
        metadata_path = attachments_dir / file_uuid / "metadata.json"

        if not metadata_path.exists():
            print(f"  MISSING  {filename} ({file_uuid[:8]}) — no metadata.json")
            missing += 1
            continue

        with open(metadata_path, "r", encoding="utf-8") as f:
            metadata = json.load(f)

        if metadata.get("ai_description") == description:
            skipped += 1
            continue

        if dry_run:
            print(f"  WOULD UPDATE  {filename} ({file_uuid[:8]})")
            print(f"    → {description[:80]}{'...' if len(description) > 80 else ''}")
            updated += 1
            continue

        metadata["ai_description"] = description
        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2)

        print(f"  UPDATED  {filename} ({file_uuid[:8]})")
        updated += 1

    print(f"\nDone{' (dry run)' if dry_run else ''}. Updated: {updated}, Already current: {skipped}, Missing metadata: {missing}")


if __name__ == "__main__":
    main()
