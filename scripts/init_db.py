"""
Database Initialization Script for Mneme Memory System

This script creates the database and sets up all tables for the first time.

WHAT THIS DOES:
1. Loads configuration to find database location
2. Creates necessary directories (respects active_profile setting)
3. Creates database with all tables and indexes
4. Verifies the setup was successful
5. Shows helpful next steps

WHEN TO RUN THIS:
- First time setting up Mneme
- After deleting the database
- When starting fresh with a clean database
- When initializing a NEW PROFILE (see PROFILES_GUIDE.md)

USAGE:
    python scripts/init_db.py

PROFILE SUPPORT:
    The script automatically uses the 'active_profile' from config.json.

    To initialize a test database:
    1. Set "active_profile": "testing" in config.json
    2. Run: python scripts/init_db.py
    3. Creates: data/testing/memory.db

    Your main profile remains untouched!

SAFETY:
- Won't overwrite existing database (asks for confirmation first)
- Creates backup of existing database before replacing
"""

import sys
import os
from pathlib import Path
from datetime import datetime
import shutil

# Add project root to path so we can import our modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.backend.schema import create_database_schema, verify_schema
from src.backend.config import load_config, ConfigError


def backup_existing_database(db_path: str, backup_dir: str) -> str:
    """
    Create a backup of existing database before replacing it.

    Args:
        db_path (str): Path to the database file
        backup_dir (str): Directory to store backup

    Returns:
        str: Path to the backup file

    SAFETY:
    This ensures you never lose data when reinitializing the database.
    """
    if not os.path.exists(db_path):
        return None

    # Create backup directory if needed
    os.makedirs(backup_dir, exist_ok=True)

    # Generate backup filename with timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    db_name = os.path.basename(db_path)
    backup_name = f"{db_name}.backup_{timestamp}"
    backup_path = os.path.join(backup_dir, backup_name)

    # Copy database to backup location
    shutil.copy2(db_path, backup_path)

    return backup_path


def init_database():
    """
    Initialize the Mneme database.

    STEPS:
    1. Load configuration
    2. Check if database already exists
    3. Create backup if needed
    4. Create new database
    5. Verify setup
    6. Show results
    """

    print("=" * 70)
    print("  MNEME DATABASE INITIALIZATION")
    print("=" * 70)
    print()

    # =========================================================================
    # STEP 1: Load Configuration
    # =========================================================================

    print("[1/5] Loading configuration...")

    try:
        config = load_config()
        db_path = config["storage"]["database_path"]
        backup_path = config["storage"]["backup_path"]

        # Show active profile (if using profiles)
        active_profile = config.get("storage", {}).get("active_profile", "")
        if active_profile:
            print(f"      Active profile: '{active_profile}'")
            print(f"      Database path: {db_path}")
            print(f"      (Profile creates isolated database in data/{active_profile}/)")
        else:
            print(f"      Database path: {db_path}")
            print(f"      (No profile set - using flat structure)")

    except ConfigError as e:
        print(f"\n✗ Configuration error:\n{e}\n")
        return 1
    except Exception as e:
        print(f"\n✗ Error loading configuration: {e}\n")
        return 1

    # =========================================================================
    # STEP 2: Check for Existing Database
    # =========================================================================

    print("\n[2/5] Checking for existing database...")

    if os.path.exists(db_path):
        print(f"      ⚠ Database already exists at: {db_path}")
        print("\n      WARNING: Reinitializing will create a fresh database.")
        print("      All existing data will be backed up but no longer active.\n")

        response = input("      Continue with initialization? (yes/no): ")
        if response.lower() not in ["yes", "y"]:
            print("\n      Initialization cancelled.")
            return 0

        # Create backup
        print("\n      Creating backup of existing database...")
        backup_file = backup_existing_database(db_path, backup_path)
        if backup_file:
            print(f"      ✓ Backup created: {backup_file}")
        else:
            print("      ✗ Could not create backup")
            return 1

        # Remove old database
        os.remove(db_path)
        print("      ✓ Old database removed")
    else:
        print("      ✓ No existing database found (this is a fresh install)")

    # =========================================================================
    # STEP 3: Create Database Directories
    # =========================================================================

    print("\n[3/5] Creating directories...")

    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
        print(f"      ✓ Created: {db_dir}")

    os.makedirs(backup_path, exist_ok=True)
    print(f"      ✓ Created: {backup_path}")

    # =========================================================================
    # STEP 4: Create Database Schema
    # =========================================================================

    print("\n[4/5] Creating database schema...")

    try:
        success = create_database_schema(db_path)
        if not success:
            print("      ✗ Failed to create database schema")
            return 1
        print("      ✓ Database schema created successfully")
    except Exception as e:
        print(f"      ✗ Error creating schema: {e}")
        return 1

    # =========================================================================
    # STEP 5: Verify Setup
    # =========================================================================

    print("\n[5/5] Verifying database setup...")

    try:
        verification = verify_schema(db_path)

        if "error" in verification:
            print(f"      ✗ Verification failed: {verification['error']}")
            return 1

        if not verification["all_tables_exist"]:
            print("      ✗ Some tables are missing")
            print(f"      Expected: {verification['expected_tables']}")
            print(f"      Found: {verification['tables']}")
            return 1

        print("      ✓ All tables created successfully")
        print(f"      ✓ Schema version: {verification['schema_version']}")
        print(f"      ✓ Tables: {', '.join(verification['tables'])}")
        print(f"      ✓ Indexes: {len(verification['indexes'])} created")

    except Exception as e:
        print(f"      ✗ Verification error: {e}")
        return 1

    # =========================================================================
    # SUCCESS!
    # =========================================================================

    print("\n" + "=" * 70)
    print("  ✓ DATABASE INITIALIZATION COMPLETE")
    print("=" * 70)

    # Show profile-specific success message
    active_profile = config.get("storage", {}).get("active_profile", "")
    if active_profile:
        print(f"\n✓ Profile '{active_profile}' database initialized successfully!")
        print(f"  Location: {db_path}")
        print("\nTo switch profiles:")
        print("  1. Open config.json")
        print("  2. Change 'active_profile' to a different name")
        print("  3. Run this script again to initialize the new profile")
        print("  4. See docs/user/SETUP_AND_USAGE.md for more details")

    print("\nNext steps:\n")
    print("  1. Test the database:")
    print("     python src/backend/cli.py\n")
    print("  2. Verify everything works:")
    print("     python scripts/verify_setup.py\n")
    print("  3. Start using the system!")
    print()

    return 0


if __name__ == "__main__":
    """
    Entry point when script is run directly.
    """
    try:
        exit_code = init_database()
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n\nInitialization cancelled by user.")
        sys.exit(1)
    except Exception as e:
        print(f"\n✗ Unexpected error: {e}")
        sys.exit(1)
