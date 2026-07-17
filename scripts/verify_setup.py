"""
Setup Verification Script for Mneme Memory System

Tests that everything is installed and configured correctly.

USAGE:
    python scripts/verify_setup.py
"""

import sys
import os
from pathlib import Path

# Add project root to path so we can import our modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.backend.config import load_config, ConfigError
from src.backend.database import Database, DatabaseError
from src.backend.schema import verify_schema


class TestResult:
    """Container for test results."""

    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.tests = []

    def add_pass(self, name: str, message: str = ""):
        self.passed += 1
        self.tests.append(("[PASS]", name, message, True))

    def add_fail(self, name: str, message: str = ""):
        self.failed += 1
        self.tests.append(("[FAIL]", name, message, False))

    def print_summary(self):
        print("\n" + "=" * 70)
        print("  TEST RESULTS")
        print("=" * 70)
        print()

        for symbol, name, message, passed in self.tests:
            print(f"{symbol} {name}")
            if message:
                print(f"  {message}")
            print()

        print("=" * 70)
        print(f"  Total: {self.passed + self.failed} tests")
        print(f"  Passed: {self.passed}")
        print(f"  Failed: {self.failed}")
        print("=" * 70)

        if self.failed == 0:
            print("\n[OK] All tests passed! Your Mneme setup is ready to use.\n")
            return True
        else:
            print(f"\n[!!] {self.failed} test(s) failed. Please fix the issues above.\n")
            return False


def verify_dependencies(results: TestResult):
    """Verify all required Python packages are installed."""
    required = {
        "flask": "flask",
        "flask_cors": "flask-cors",
        "openai": "openai",
        "anthropic": "anthropic",
        "numpy": "numpy",
        "tiktoken": "tiktoken",
        "PIL": "Pillow",
        "pdfplumber": "pdfplumber",
        "elevenlabs": "elevenlabs",
        "onnxruntime": "onnxruntime",
        "tokenizers": "tokenizers",
    }
    missing = []
    for module, package in required.items():
        try:
            __import__(module)
        except ImportError:
            missing.append(package)

    if missing:
        results.add_fail(
            "Python dependencies",
            f"Missing packages: {', '.join(missing)}. Run: pip install -r requirements.txt"
        )
        return False
    else:
        results.add_pass("Python dependencies", f"All {len(required)} required packages installed")
        return True


def verify_python_version(results: TestResult):
    """Verify Python version is 3.9 or higher."""
    version = sys.version_info

    if version.major >= 3 and version.minor >= 9:
        results.add_pass(
            "Python version",
            f"Python {version.major}.{version.minor}.{version.micro}"
        )
        return True
    else:
        results.add_fail(
            "Python version",
            f"Python {version.major}.{version.minor}.{version.micro} is too old. "
            f"Mneme requires Python 3.9 or higher."
        )
        return False


def verify_configuration(results: TestResult):
    """Verify configuration file exists and is valid."""
    try:
        config = load_config()
        results.add_pass(
            "Configuration file",
            "config.json loaded successfully"
        )
        return config
    except ConfigError as e:
        results.add_fail("Configuration file", str(e))
        return None
    except Exception as e:
        results.add_fail("Configuration file", f"Unexpected error: {e}")
        return None


def verify_database_exists(config, results: TestResult):
    """Verify database file exists."""
    if not config:
        results.add_fail("Database file", "Skipped (configuration not loaded)")
        return None

    db_path = config["storage"]["database_path"]

    if os.path.exists(db_path):
        results.add_pass("Database file", f"Found at {db_path}")
        return db_path
    else:
        results.add_fail(
            "Database file",
            f"Not found at {db_path}. Run: python scripts/init_db.py"
        )
        return None


def verify_database_schema(db_path, results: TestResult):
    """Verify all database tables exist."""
    if not db_path:
        results.add_fail("Database schema", "Skipped (database not found)")
        return False

    try:
        verification = verify_schema(db_path)

        if "error" in verification:
            results.add_fail("Database schema", f"Error: {verification['error']}")
            return False

        if verification["all_tables_exist"]:
            results.add_pass(
                "Database schema",
                f"All {len(verification['tables'])} tables present. "
                f"Schema version: {verification['schema_version']}"
            )
            return True
        else:
            results.add_fail(
                "Database schema",
                f"Missing tables. Expected: {verification['expected_tables']}, "
                f"Found: {verification['tables']}"
            )
            return False

    except Exception as e:
        results.add_fail("Database schema", f"Verification error: {e}")
        return False


def verify_crud_operations(db_path, results: TestResult):
    """Verify basic database operations work."""
    if not db_path:
        results.add_fail("Database operations", "Skipped (database not found)")
        return False

    message_id = None
    try:
        db = Database(db_path)

        # Test: Add a message
        message_id = db.add_message(
            sender="user",
            content="Test message for verification",
            importance_score=5.0
        )

        if not message_id:
            results.add_fail("Database operations", "Failed to add message")
            return False

        # Test: Retrieve the message
        message = db.get_message(message_id)
        if not message or message["content"] != "Test message for verification":
            results.add_fail("Database operations", "Failed to retrieve message")
            return False

        # Test: Update importance
        db.update_message_importance(message_id, 7.0, "test")
        updated = db.get_message(message_id)
        if updated["importance_score"] != 7.0:
            results.add_fail("Database operations", "Failed to update importance score")
            return False

        # Test: Update tier
        db.update_message_tier(message_id, "active")
        updated = db.get_message(message_id)
        if updated["tier"] != "active":
            results.add_fail("Database operations", "Failed to update tier")
            return False

        results.add_pass(
            "Database operations (CRUD)",
            "Create, Read, Update operations working"
        )
        return True

    except DatabaseError as e:
        results.add_fail("Database operations", f"Database error: {e}")
        return False
    except Exception as e:
        results.add_fail("Database operations", f"Unexpected error: {e}")
        return False
    finally:
        if message_id:
            try:
                db.delete_message(message_id)
            except Exception:
                pass


def verify_search_functionality(db_path, results: TestResult):
    """Verify search operations work."""
    if not db_path:
        results.add_fail("Search functionality", "Skipped (database not found)")
        return False

    message_id = None
    try:
        db = Database(db_path)

        # Add a test message with unique keyword
        test_keyword = "VERIFICATION_TEST_UNIQUE_KEYWORD"
        message_id = db.add_message(
            sender="assistant",
            content=f"This message contains {test_keyword} for testing"
        )

        # Search for it
        results_list = db.search_messages_keyword(test_keyword)

        if not results_list or len(results_list) == 0:
            results.add_fail(
                "Search functionality",
                "Failed to find test message with keyword search"
            )
            return False

        # Verify we found the right message
        found = any(msg["id"] == message_id for msg in results_list)
        if not found:
            results.add_fail(
                "Search functionality",
                "Keyword search returned results but not the expected message"
            )
            return False

        results.add_pass("Search functionality", "Keyword search working correctly")
        return True

    except DatabaseError as e:
        results.add_fail("Search functionality", f"Database error: {e}")
        return False
    except Exception as e:
        results.add_fail("Search functionality", f"Unexpected error: {e}")
        return False
    finally:
        if message_id:
            try:
                db.delete_message(message_id)
            except Exception:
                pass


def verify_statistics(db_path, results: TestResult):
    """Verify statistics functions work."""
    if not db_path:
        results.add_fail("Statistics", "Skipped (database not found)")
        return False

    try:
        db = Database(db_path)

        # Get message count
        count = db.get_message_count()
        if count < 0:
            results.add_fail("Statistics", "Message count returned invalid value")
            return False

        # Get tier counts
        tier_counts = db.get_message_count_by_tier()
        if not isinstance(tier_counts, dict):
            results.add_fail("Statistics", "Tier counts returned invalid type")
            return False

        results.add_pass(
            "Statistics",
            f"All statistics functions working ({count} total messages)"
        )
        return True

    except DatabaseError as e:
        results.add_fail("Statistics", f"Database error: {e}")
        return False
    except Exception as e:
        results.add_fail("Statistics", f"Unexpected error: {e}")
        return False


def main():
    """Run all verification tests."""
    print("=" * 70)
    print("  MNEME SETUP VERIFICATION")
    print("=" * 70)
    print("\nRunning tests...\n")

    results = TestResult()

    # Run all tests
    verify_python_version(results)
    verify_dependencies(results)
    config = verify_configuration(results)
    db_path = verify_database_exists(config, results)
    verify_database_schema(db_path, results)
    verify_crud_operations(db_path, results)
    verify_search_functionality(db_path, results)
    verify_statistics(db_path, results)

    # Print results
    all_passed = results.print_summary()

    if all_passed:
        print("Next steps:\n")
        print("  1. Start the web server:")
        print("     python src/backend/server.py\n")
        print("  2. Open http://localhost:8080\n")
        return 0
    else:
        print("Troubleshooting:\n")
        print("  1. Make sure you ran: python scripts/init_db.py")
        print("  2. Check that config.json exists and has your API key")
        print("  3. Read the setup instructions in README.md\n")
        return 1


if __name__ == "__main__":
    try:
        exit_code = main()
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n\nVerification cancelled by user.")
        sys.exit(1)
    except Exception as e:
        print(f"\n[!!] Unexpected error during verification: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
