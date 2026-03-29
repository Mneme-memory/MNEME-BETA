"""
Terminal Chat Interface for Mneme Memory System

Simple chat interface for quick testing of the backend.

USAGE:
    python scripts/chat.py                  # Use default model from config
    python scripts/chat.py --production     # Use Sonnet (production model)
    python scripts/chat.py --stats          # Show statistics at end

FEATURES:
- Chat with AI using stored memories
- Try @commands (@remember, @recall, etc.)
- See token usage and context info
- Model switching (Haiku/Sonnet)

Type 'exit' or 'quit' to end conversation.
Type '@help' to see available commands.
"""

import sys
from pathlib import Path
import argparse

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.backend.database import Database
from src.backend.config import load_config, ConfigError
from src.backend.embeddings import EmbeddingGenerator
from src.backend.conversation import ConversationManager


def print_separator():
    """Print visual separator."""
    print("-" * 70)


def print_header():
    """Print chat interface header."""
    print("\n" + "=" * 70)
    print("  MNEME CHAT INTERFACE")
    print("=" * 70)


def print_context_info(context_info: dict):
    """Print context information."""
    if not context_info:
        return

    print(f"\n[Context: {context_info.get('recent_messages', '?')} recent msgs, "
          f"{context_info.get('memories_retrieved', '?')} memories, "
          f"{context_info.get('tokens_used', 0):,}/{context_info.get('tokens_budget', 0):,} tokens]")


def main():
    """Run chat interface."""
    # Parse arguments
    parser = argparse.ArgumentParser(description="Mneme Chat Interface")
    parser.add_argument("--production", action="store_true",
                       help="Use production model (Sonnet) instead of testing model (Haiku)")
    parser.add_argument("--stats", action="store_true",
                       help="Show statistics when exiting")
    args = parser.parse_args()

    print_header()

    # Load configuration
    print("\n[1/3] Loading configuration...")
    try:
        config = load_config()
        db_path = config["storage"]["database_path"]
        openai_key = config["api_keys"]["openai"]
        anthropic_key = config["api_keys"]["anthropic"]

        # Check keys
        if openai_key == "YOUR_OPENAI_API_KEY_HERE":
            print("  x OpenAI API key not configured in config.json")
            return 1
        if anthropic_key == "YOUR_ANTHROPIC_API_KEY_HERE":
            print("  x Anthropic API key not configured in config.json")
            return 1

        print("      ok Configuration loaded")

    except ConfigError as e:
        print(f"\n  x Configuration error:\n{e}\n")
        return 1

    # Initialize components
    print("\n[2/3] Initializing memory system...")
    try:
        db = Database(db_path)
        embedder = EmbeddingGenerator(openai_key, model="text-embedding-3-small")

        print("      ok Database connected")
        print("      ok Embeddings ready (OpenAI)")

    except Exception as e:
        print(f"\n  x Initialization error:\n{e}\n")
        return 1

    # Check for existing messages
    message_count = db.get_message_count()
    print(f"      ok Found {message_count} existing messages")

    if message_count == 0:
        print("\n  Note: No messages in database yet.")
        print("   Start chatting - new messages will be stored.")

    # Initialize conversation manager
    print("\n[3/3] Starting conversation manager...")
    try:
        # Override config for model selection
        if args.production:
            config.setdefault("model", {})["use_testing"] = False

        manager = ConversationManager(db, embedder, config)

        model_name = "Production" if args.production else "Testing"
        print(f"      ok Model: {model_name} ({manager.model})")
        print(f"      ok Temperature: {manager.temperature}")
        print(f"      ok Context budget: {config.get('context', {}).get('recent_messages_tokens', 70000):,} tokens")

    except Exception as e:
        print(f"\n  x Failed to start conversation manager:\n{e}\n")
        return 1

    # Start chat loop
    print_separator()
    print("\n  Ready to chat!")
    print("\nAvailable commands:")
    print("  @remember [text] - Mark as high-importance")
    print("  @recall [topic] - Retrieve memories")
    print("  @help - Show all commands")
    print("  exit or quit - End conversation")
    print_separator()

    message_count_start = message_count

    try:
        while True:
            # Get user input
            try:
                user_input = input("\nYou: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n\nEnding conversation...")
                break

            if not user_input:
                continue

            # Check for exit
            if user_input.lower() in ["exit", "quit", "bye"]:
                print("\nEnding conversation...")
                break

            # Process message
            try:
                result = manager.process_message(user_input)

                # Show response
                print(f"\nAssistant: {result['response']}")

                # Show context info (if not a command)
                if not result.get("is_command"):
                    print_context_info(result.get("context_info", {}))

            except Exception as e:
                print(f"\n  x Error processing message: {e}")
                continue

    finally:
        # Force process any remaining messages
        print("\n\nProcessing remaining messages...")
        manager.force_process_queue()

        # Show statistics if requested
        if args.stats:
            print_separator()
            print("\nCONVERSATION STATISTICS:")
            stats = manager.get_statistics()

            print(f"\nMessages:")
            print(f"  Received: {stats.get('conversation', {}).get('messages_received', 0)}")
            print(f"  Sent: {stats.get('conversation', {}).get('messages_sent', 0)}")
            print(f"  Commands: {stats.get('conversation', {}).get('commands_executed', 0)}")

            print(f"\nCosts:")
            print(f"  Total: ${stats.get('conversation', {}).get('total_cost', 0):.4f}")

        # Final message count
        message_count_end = db.get_message_count()
        messages_added = message_count_end - message_count_start

        print(f"\n{messages_added} new messages stored in database.")
        print("Database:", db_path)

        print_separator()

    return 0


if __name__ == "__main__":
    sys.exit(main())
