"""
Command Line Interface for Mneme Memory System

Simple text-based interface for inspecting and testing the database directly.
For actual conversations, use the web UI.

AVAILABLE COMMANDS:
- add: Add a new message
- search: Search for messages
- list: Show recent messages
- get: Show a specific message
- importance: Update importance score
- stats: Show database statistics
- help: Show available commands
- exit: Quit the CLI

USAGE:
    python src/backend/cli.py
"""

import sys
import os
from pathlib import Path

# Add parent directory to path so we can import our modules
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.backend.database import Database, DatabaseError
from src.backend.config import load_config, ConfigError
from datetime import datetime


class MemoryCLI:
    """
    Command-line interface for the Mneme memory system.

    This provides an interactive shell for testing database operations.
    """

    def __init__(self, db_path: str):
        """
        Initialize the CLI with a database connection.

        Args:
            db_path (str): Path to the database file
        """
        self.db = Database(db_path)
        self.running = True

    def print_header(self):
        """
        Display the CLI welcome message.
        """
        print("\n" + "=" * 60)
        print("  MNEME - Memory System for AI Continuity")
        print("  Database Inspector")
        print("=" * 60)
        print("\nType 'help' for available commands or 'exit' to quit\n")

    def print_help(self):
        """
        Display available commands and their usage.
        """
        help_text = """
AVAILABLE COMMANDS:

  add <sender> <content>
      Add a new message to the database
      sender: 'user' or 'assistant'
      Example: add user Hello, how are you?

  search <keyword>
      Search for messages containing the keyword
      Example: search crow

  list [limit]
      Show recent messages (default: 10)
      Example: list 20

  get <message_id>
      Show details for a specific message
      Example: get 5

  importance <message_id> <score>
      Update importance score for a message (1-10)
      Example: importance 5 8.5

  stats
      Show database statistics

  help
      Show this help message

  exit
      Quit the CLI

"""
        print(help_text)

    def cmd_add(self, args: list):
        """
        Add a new message to the database.

        Args:
            args: [sender, content...]

        EXAMPLE:
            add user Hello, this is a test message
        """
        if len(args) < 2:
            print("Error: Usage: add <sender> <content>")
            print("Example: add user Hello, how are you?")
            return

        sender = args[0]
        if sender not in ["user", "assistant"]:
            print(f"Error: sender must be 'user' or 'assistant', got: {sender}")
            return

        content = " ".join(args[1:])

        try:
            message_id = self.db.add_message(sender=sender, content=content)
            print(f"✓ Message added successfully (ID: {message_id})")
        except DatabaseError as e:
            print(f"✗ Error adding message: {e}")

    def cmd_search(self, args: list):
        """
        Search for messages containing a keyword.

        Args:
            args: [keyword]
        """
        if len(args) < 1:
            print("Error: Usage: search <keyword>")
            return

        keyword = " ".join(args)

        try:
            results = self.db.search_messages_keyword(keyword, limit=10)

            if not results:
                print(f"No messages found containing '{keyword}'")
                return

            print(f"\nFound {len(results)} message(s) containing '{keyword}':\n")
            for msg in results:
                print(f"ID: {msg['id']} | {msg['sender']} | {msg['timestamp']}")
                print(f"Content: {msg['content'][:100]}...")
                print(f"Importance: {msg['importance_score']} | Tier: {msg['tier']}")
                print("-" * 60)

        except DatabaseError as e:
            print(f"✗ Error searching: {e}")

    def cmd_list(self, args: list):
        """
        List recent messages.

        Args:
            args: [limit] (optional)
        """
        limit = 10
        if args:
            try:
                limit = int(args[0])
            except ValueError:
                print(f"Error: limit must be a number, got: {args[0]}")
                return

        try:
            messages = self.db.get_recent_messages(limit=limit)

            if not messages:
                print("No messages in database yet.")
                return

            print(f"\nShowing {len(messages)} most recent message(s):\n")
            for msg in messages:
                print(f"ID: {msg['id']} | {msg['sender']} | {msg['timestamp']}")
                print(f"Content: {msg['content'][:100]}{'...' if len(msg['content']) > 100 else ''}")
                print(f"Importance: {msg['importance_score']} | Tier: {msg['tier']}")
                print("-" * 60)

        except DatabaseError as e:
            print(f"✗ Error listing messages: {e}")

    def cmd_get(self, args: list):
        """
        Show details for a specific message.

        Args:
            args: [message_id]
        """
        if len(args) < 1:
            print("Error: Usage: get <message_id>")
            return

        try:
            message_id = int(args[0])
            message = self.db.get_message(message_id)

            if not message:
                print(f"Message {message_id} not found")
                return

            print(f"\nMessage ID: {message['id']}")
            print(f"Timestamp: {message['timestamp']}")
            print(f"Sender: {message['sender']}")
            print(f"Importance: {message['importance_score']}")
            print(f"Tier: {message['tier']}")
            print(f"\nContent:\n{message['content']}\n")

        except ValueError:
            print(f"Error: message_id must be a number, got: {args[0]}")
        except DatabaseError as e:
            print(f"✗ Error retrieving message: {e}")

    def cmd_importance(self, args: list):
        """
        Update importance score for a message.

        Args:
            args: [message_id, score]
        """
        if len(args) < 2:
            print("Error: Usage: importance <message_id> <score>")
            print("Example: importance 5 8.5")
            return

        try:
            message_id = int(args[0])
            score = float(args[1])

            if score < 1.0 or score > 10.0:
                print("Error: score must be between 1.0 and 10.0")
                return

            self.db.update_message_importance(
                message_id,
                score,
                reason="manual_cli_update",
                details={"updated_via": "cli"}
            )
            print(f"✓ Updated importance score for message {message_id} to {score}")

        except ValueError as e:
            print(f"Error: Invalid input - {e}")
        except DatabaseError as e:
            print(f"✗ Error updating importance: {e}")

    def cmd_stats(self, args: list):
        """
        Show database statistics.
        """
        try:
            total = self.db.get_message_count()
            tier_counts = self.db.get_message_count_by_tier()

            print("\n" + "=" * 60)
            print("DATABASE STATISTICS")
            print("=" * 60)

            print(f"\nTotal Messages: {total}")

            print("\nMessages by Tier:")
            for tier, count in tier_counts.items():
                print(f"  {tier}: {count}")

            print()

        except DatabaseError as e:
            print(f"✗ Error retrieving statistics: {e}")

    def cmd_exit(self, args: list):
        """
        Exit the CLI.
        """
        print("\nGoodbye!")
        self.running = False

    def process_command(self, command_line: str):
        """
        Parse and execute a command.

        Args:
            command_line (str): The full command line input
        """
        parts = command_line.strip().split()
        if not parts:
            return

        command = parts[0].lower()
        args = parts[1:]

        # Map commands to their handler functions
        commands = {
            "add": self.cmd_add,
            "search": self.cmd_search,
            "list": self.cmd_list,
            "get": self.cmd_get,
            "importance": self.cmd_importance,
            "stats": self.cmd_stats,
            "help": lambda args: self.print_help(),
            "exit": self.cmd_exit,
            "quit": self.cmd_exit,
        }

        if command in commands:
            commands[command](args)
        else:
            print(f"Unknown command: {command}")
            print("Type 'help' for available commands")

    def run(self):
        """
        Main loop for the CLI.

        This keeps running until the user types 'exit' or presses Ctrl+C.
        """
        self.print_header()

        while self.running:
            try:
                command_line = input("mneme> ")
                self.process_command(command_line)
            except KeyboardInterrupt:
                print("\n\nInterrupted. Type 'exit' to quit.")
            except EOFError:
                print("\nGoodbye!")
                break
            except Exception as e:
                print(f"✗ Unexpected error: {e}")


def main():
    """
    Entry point for the CLI.
    """
    try:
        # Try to load config to get database path
        config = load_config()
        db_path = config["storage"]["database_path"]
    except ConfigError as e:
        print(f"Configuration error: {e}")
        print("\nPlease set up config.json before using the CLI.")
        return 1
    except Exception as e:
        print(f"Error loading configuration: {e}")
        return 1

    # Check if database exists
    if not os.path.exists(db_path):
        print(f"Database not found at: {db_path}")
        print("\nPlease run: python scripts/init_db.py")
        return 1

    # Start the CLI
    try:
        cli = MemoryCLI(db_path)
        cli.run()
        return 0
    except Exception as e:
        print(f"Fatal error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
