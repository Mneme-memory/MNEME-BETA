"""
Conversation Manager Module for Mneme Memory System

Orchestrates the complete conversation flow:
1. Receive user input
2. Check for @commands
3. Store message in database
4. Generate embedding (immediate)
5. Add to tagging queue (batch later)
6. Retrieve relevant memories
7. Assemble context (70k recent + 15k memories)
8. Call AI model
9. Store AI response
10. Return to user

SPEC ALIGNMENT:
Lines 384-389: Phase 3 conversation interface
Line 68: "All messages auto-stored"
Line 71: "Embeddings generated in background"
Lines 358-360: Backend service architecture

USAGE:
    manager = ConversationManager(db, embedder, config)
    response = manager.process_message("Tell me about the crows")
"""

from typing import Dict, Optional, List
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import re
import sys


from .context import ContextAssembler
from .background import BackgroundQueue
from .commands import CommandHandler
from .prompt_cache import PromptCacheManager
from .prompt_builder import PromptBuilder
from .tier_manager import TierManager
from .instance_executor import InstanceExecutor
from .ai_client import AIClient, AIClientError
from .provenance import ProvenanceLogger
from .error_handling import (
    retry_with_backoff,
    handle_anthropic_error,
    get_user_friendly_message,
    MnemeAPIError
)


class ConversationError(Exception):
    """Custom exception for conversation errors."""
    pass


class ConversationManager:
    """
    Manages the complete conversation flow with memory integration.

    This class:
    - Handles user input and AI responses
    - Manages context assembly
    - Processes @commands
    - Handles background embedding
    - Calls AI model (Claude)
    - Tracks conversation statistics
    """

    def __init__(self, database, embedder, config, graph_db=None, file_processor=None, artifact_storage=None):
        """
        Initialize conversation manager.

        Args:
            database: Database instance
            embedder: EmbeddingGenerator instance
            config: Configuration dictionary
            graph_db: GraphDatabase instance (optional, for Phase 5)
            file_processor: FileProcessor instance (optional, for Phase 7)
            artifact_storage: ArtifactStorage instance (optional)

        Raises:
            ConversationError: If required components unavailable
        """
        self.db = database
        self.embedder = embedder
        self.config = config
        self.graph_db = graph_db
        self.file_processor = file_processor
        self.artifact_storage = artifact_storage

        # Get model config
        model_config = config.get("model", {})
        self.use_testing_model = model_config.get("use_testing", True)

        if self.use_testing_model:
            self.model = model_config.get("testing", "claude-haiku-4-5")
        else:
            self.model = model_config.get("default", "claude-sonnet-4-6")

        self.temperature = model_config.get("temperature", 1.0)
        self.max_tokens = model_config.get("max_tokens", 4096)
        self.max_instance_iterations = config.get("commands", {}).get("max_iterations", 6)

        # Initialize AI client (handles all Anthropic API interactions)
        anthropic_key = config.get("api_keys", {}).get("anthropic")
        if not anthropic_key or anthropic_key == "YOUR_ANTHROPIC_API_KEY_HERE":
            raise ConversationError("Anthropic API key not configured")

        self.ai_client = AIClient(
            api_key=anthropic_key,
            model=self.model,
            temperature=self.temperature,
            max_tokens=self.max_tokens
        )

        # Initialize components
        self.provenance = ProvenanceLogger(database)
        self.context_assembler = ContextAssembler(database, embedder, config, graph_db=graph_db, provenance=self.provenance)
        self.background_queue = BackgroundQueue(database, embedder, config, graph_db=graph_db)
        self.command_handler = CommandHandler(
            database, embedder, config, self.background_queue, self.context_assembler,
            graph_db=graph_db, file_processor=file_processor, artifact_storage=artifact_storage
        )
        self.cache_manager = PromptCacheManager(config)
        self.prompt_builder = PromptBuilder(config, database, self.cache_manager)
        self.instance_executor = InstanceExecutor(self.command_handler, database, config)

        # Conversation history (for context)
        # Load recent messages from database on startup
        self.conversation_history = self._load_recent_context()

        # Track temporary command results (cleaned up after AI response)
        self.temporary_message_ids = []

        # Pending notifications from background/internal operations (drained by streaming pipeline)
        self._pending_notifications = []

        # Initialize tier manager (handles memory tier transitions)
        # Pass graph_db for Phase 8 entity summary updates on tier transitions
        self.tier_manager = TierManager(database, self.context_assembler, config, graph_db)

        # Run automatic tier reallocation on startup (respects config changes)
        self.tier_manager.rebalance_on_startup()

        # Statistics
        self.stats = {
            "messages_sent": 0,
            "messages_received": 0,
            "commands_executed": 0,
            "api_calls": 0,
            "total_cost": 0.0
        }

        # Cache overflow tracking — updated after each API call, checked before the next
        self.last_total_prompt_tokens = 0

        # Concept auto-extraction tracking (Phase 6)
        # Messages counter is kept here (stateful), settings are in PromptBuilder
        total_messages = database.get_message_count()
        _concept_freq = self.prompt_builder.concept_extract_frequency
        self.messages_since_concept_check = total_messages % _concept_freq if _concept_freq > 0 else 0

        # Notes cleanup tracking
        notes_config = config.get("features", {}).get("notes", {})
        self.notes_cleanup_interval = notes_config.get("cleanup_interval_messages", 50)
        self.messages_since_notes_check = total_messages % self.notes_cleanup_interval if self.notes_cleanup_interval > 0 else 0

        # Extended thinking config
        thinking_config = config.get("thinking", {})
        self.thinking_enabled = thinking_config.get("enabled", False)
        self.thinking_budget = thinking_config.get("budget_tokens", 10000)
        self.show_thinking = thinking_config.get("show_in_ui", True)

        # Daily summaries manager (lazy-initialized)
        timeline_config = config.get("features", {}).get("timeline", {})
        self.timeline_enabled = timeline_config.get("enabled", False)
        self.daily_summary_manager = None
        self._last_message_date = None  # For day rollover detection
        self.instance_name = (
            config.get("identity", {}).get("instance_name", "")
            or config.get("storage", {}).get("active_profile", "")
            or "Claude"
        )

        self._startup_notifications = []  # Drained on first message

        # Print startup statistics (after all attributes initialized)
        self._print_startup_stats()

        # Startup background tasks: importance decay + daily summaries (Phase 9)
        import threading
        self._startup_bg_thread = threading.Thread(
            target=self._check_daily_summaries_on_startup,
            daemon=True
        )
        self._startup_bg_thread.start()

    def _status(self, id: str, pill: str, summary: str, detail: dict = None) -> dict:
        """Build a structured status notification for the frontend."""
        data = {"id": id, "pill": pill, "summary": summary}
        if detail:
            data["detail"] = detail
        return {"type": "notification", "data": data}

    def _get_daily_summary_manager(self):
        """Lazy-initialize the daily summary manager."""
        if self.daily_summary_manager is None and self.timeline_enabled:
            from .daily_summaries import DailySummaryManager
            self.daily_summary_manager = DailySummaryManager(
                self.config, self.db, self.ai_client
            )
        return self.daily_summary_manager

    def _check_daily_summaries_on_startup(self):
        """Check for and generate missing daily summaries on startup (Phase 9).

        Runs in a background thread to avoid blocking server startup.
        Uses its own AIClient to avoid race conditions with the main client.
        """
        # Always run importance decay on startup (independent of timeline config)
        self._apply_importance_decay()
        self._startup_notifications.append(
            self._status("importance_decay", "decay applied", "Applied daily importance decay to older messages")
        )

        if not self.timeline_enabled:
            return

        try:
            # Create a dedicated DailySummaryManager with its own AIClient
            # to avoid race conditions with the main conversation client
            from .daily_summaries import DailySummaryManager
            bg_manager = DailySummaryManager(self.config, self.db, ai_client=None)
            generated = bg_manager.check_and_generate_missing(show_progress=True)
            if generated > 0:
                print(f"✓ Generated {generated} daily summaries in background")
                self._startup_notifications.append(
                    self._status("backfill_summary", "backfill done", f"Generated {generated} missing daily summaries")
                )
        except Exception as e:
            print(f"Daily summary check failed on startup: {e}")

    def _check_day_rollover(self) -> bool:
        """
        Check if we've crossed into a new day and need to generate yesterday's summary.

        Called on each message to detect day transitions.

        Returns:
            bool: True if day rollover was detected and summary generation started
        """
        if not self.timeline_enabled:
            return False

        today = datetime.now(timezone.utc).date().isoformat()

        # First message after startup — seed from DB to detect day boundary across restarts
        if self._last_message_date is None:
            result = self.db.execute_query(
                "SELECT MAX(SUBSTR(timestamp, 1, 10)) as last_date FROM messages "
                "WHERE metadata IS NULL OR json_extract(metadata, '$.temporary') IS NULL"
            )
            self._last_message_date = (result[0]["last_date"] if result and result[0]["last_date"] else today)
            if self._last_message_date == today:
                return False
            # Fall through to rollover detection below

        # Same day - no rollover
        if self._last_message_date == today:
            return False

        # Day changed! Generate yesterday's summary and apply importance decay
        print(f"Day rollover detected ({self._last_message_date} -> {today})")
        self._last_message_date = today

        import threading
        def _day_rollover_tasks():
            try:
                self._apply_importance_decay()
            except Exception as e:
                print(f"Day rollover importance decay failed: {e}")
            try:
                manager = self._get_daily_summary_manager()
                if manager:
                    manager.check_day_rollover()
            except Exception as e:
                print(f"Day rollover summary generation failed: {e}")

        threading.Thread(target=_day_rollover_tasks, daemon=True).start()
        return True

    def _apply_importance_decay(self):
        """
        Apply daily importance decay to all messages above the floor.

        Uses exponential decay toward a floor value:
            new = floor + (current - floor) × rate^days_elapsed

        This runs once per calendar day (tracked via metadata table).
        Catches up on missed days by using the actual elapsed days.

        DESIGN:
        - Floor: 3.0 (default new-message importance)
        - Rate: 0.995/day
        - A message at 10.0, never retrieved: ~4.1 after 1 year
        - A message at 10.0, retrieved monthly: ~9.0 after 1 year
          (retrieval boosts counteract decay for useful memories)
        """
        DECAY_FLOOR = 3.0
        DECAY_RATE = 0.995

        try:
            today = datetime.now(timezone.utc).date().isoformat()

            # Check when decay last ran
            result = self.db.execute_query(
                "SELECT value FROM metadata WHERE key = 'last_importance_decay'",
                ()
            )
            if result:
                last_decay = json.loads(result[0]["value"])
                if last_decay == today:
                    return  # Already ran today

                # Calculate days since last decay
                from datetime import date
                last_date = date.fromisoformat(last_decay)
                today_date = date.fromisoformat(today)
                days_elapsed = (today_date - last_date).days

                if days_elapsed <= 0:
                    return
            else:
                # First run ever — apply 1 day of decay
                days_elapsed = 1

            # Apply decay: new = floor + (current - floor) * rate^days
            # Only update messages above the floor (no point decaying 3.0)
            multiplier = DECAY_RATE ** days_elapsed

            affected = self.db.execute_write(
                """UPDATE messages
                   SET importance_score = ? + (importance_score - ?) * ?
                   WHERE importance_score > ?""",
                (DECAY_FLOOR, DECAY_FLOOR, multiplier, DECAY_FLOOR)
            )

            # Record that decay ran today
            self.db.execute_write(
                """INSERT OR REPLACE INTO metadata (key, value, updated_at)
                   VALUES ('last_importance_decay', ?, ?)""",
                (json.dumps(today), datetime.now(timezone.utc).isoformat())
            )

            if affected and affected > 0:
                print(f"  Importance decay applied: {affected} messages, {days_elapsed}d elapsed (×{multiplier:.4f})")

        except Exception as e:
            print(f"Warning: Importance decay failed: {e}")

    def _load_recent_context(self) -> List[Dict]:
        """
        Load recent conversation history from database on startup.

        Uses ContextAssembler's token counting (with formatting) to ensure
        consistency with what actually goes to the API.

        Returns:
            List[Dict]: Recent messages from database (within token budget)
        """
        # Load ALL recent messages from database (returns newest first)
        message_count = self.db.get_message_count()
        if message_count > 50000:
            print(f"⚠️ WARNING: Large database ({message_count:,} messages) - performance may degrade", file=sys.stderr, flush=True)
        all_recent = self.db.get_recent_messages(limit=10000)

        # Count tokens using ContextAssembler's method (includes formatting)
        # Process newest first, stop when budget exceeded
        context_msgs = []
        total_tokens = 0
        budget = self.context_assembler.recent_budget

        for i, msg in enumerate(all_recent):  # Already newest first
            # Count tokens with formatting (matches what goes to API)
            msg_text = f"{msg['sender']}: {msg['content']}"
            msg_tokens = self.context_assembler.count_tokens(msg_text)

            if total_tokens + msg_tokens > budget:
                break  # Hit budget, stop loading

            # Load attachment UUIDs for this message (Phase 7)
            attachment_uuids = []
            attachments = self.db.get_attachments_for_message(msg["id"])
            if attachments:
                attachment_uuids = [a["uuid"] for a in attachments]

            # Add to context
            context_msgs.append({
                "id": msg["id"],
                "sender": msg["sender"],
                "content": msg["content"],
                "timestamp": msg["timestamp"],
                "attachment_uuids": attachment_uuids
            })
            total_tokens += msg_tokens

        # Reverse to chronological order (oldest first) for conversation flow
        context_msgs.reverse()

        return context_msgs

    # =========================================================================
    # Helper methods to reduce duplication between streaming/non-streaming
    # =========================================================================

    def _get_utc_timestamp(self) -> str:
        """Get consistent UTC timestamp for conversation history."""
        return datetime.now(timezone.utc).replace(microsecond=0).strftime('%Y-%m-%dT%H:%M:%S') + 'Z'

    def _add_to_history(self, msg_id: int, sender: str, content: str, attachment_uuids: list = None):
        """Add message to conversation history with consistent timestamp."""
        self.conversation_history.append({
            "id": msg_id,
            "sender": sender,
            "content": content,
            "timestamp": self._get_utc_timestamp(),
            "attachment_uuids": attachment_uuids or []
        })

    def _finalize_response(self, ai_response: str, ai_msg_id: int, context: Dict) -> Dict:
        """
        Finalize response: queue for background processing.

        Args:
            ai_response: The AI's response text
            ai_msg_id: The AI message ID
            context: The context dict (for retrieved memories)

        Returns:
            dict: Processing info for AI message
        """
        # Generate embedding for AI response
        try:
            ai_processing_info = self.background_queue.add_message(
                ai_msg_id,
                ai_response,
                "assistant"
            )
        except Exception as e:
            print(f"Background processing failed (non-critical): {e}")
            ai_processing_info = {
                "embedding_generated": False,
                "queued_for_entity_assignment": False,
                "entity_batch_processed": False,
                "error": str(e)
            }

        return ai_processing_info

    def _build_result(self, ai_response: str, context: Dict, user_processing: Dict, ai_processing: Dict) -> Dict:
        """Build standard result dict for conversation response."""
        return {
            "response": ai_response,
            "is_command": False,
            "context_info": {
                "recent_messages": context["metadata"]["recent_messages_included"],
                "memories_retrieved": context["metadata"]["memories_included"],
                "memories_skipped_duplicate": context["metadata"]["memories_skipped_duplicate"],
                "tokens_used": context["token_counts"]["total"],
                "tokens_budget": context["token_counts"]["budget"],
                "tokens_remaining": context["token_counts"]["remaining"]
            },
            "processing_info": {
                "user_message": user_processing,
                "ai_message": ai_processing,
                "tagging_queue_size": self.background_queue.get_queue_status()["entity_queue_size"]
            }
        }

    def _load_attachment_blocks(self, attachment_uuids: list) -> list:
        """
        Load attachment content blocks for AI request (Phase 7).

        Args:
            attachment_uuids: List of attachment UUIDs

        Returns:
            List of content blocks (images, text) for Anthropic API
        """
        if not attachment_uuids or not self.file_processor:
            return []

        blocks = []
        for uuid in attachment_uuids:
            try:
                # Get attachment record from database
                attachment = self.db.get_attachment_by_uuid(uuid)
                if not attachment:
                    print(f"⚠️ Attachment not found: {uuid[:8]}...", flush=True)
                    continue

                # Load content using file_processor
                content_block = self.file_processor.load_for_context(attachment)

                # Add filename label with UUID before content
                # UUID is needed for AI to use @describe command
                uuid_short = attachment['uuid'][:8]
                blocks.append({
                    "type": "text",
                    "text": f"📎 File [{uuid_short}]: {attachment['filename']}"
                })

                # Add content block(s) - could be single or list for PDFs
                if isinstance(content_block, list):
                    blocks.extend(content_block)
                else:
                    blocks.append(content_block)

                print(f"📎 Loaded attachment: {attachment['filename']}", flush=True)

            except Exception as e:
                print(f"⚠️ Failed to load attachment {uuid[:8]}: {str(e)}", flush=True)

        return blocks

    def _load_history_attachment_blocks(self, conversation_history: list) -> dict:
        """
        Pre-load attachment blocks for all messages in conversation history (Phase 7).

        Args:
            conversation_history: List of message dicts with attachment_uuids

        Returns:
            Dict mapping message_id -> list of attachment content blocks
        """
        if not self.file_processor:
            return {}

        history_attachments = {}

        for msg in conversation_history:
            msg_id = msg.get("id")
            attachment_uuids = msg.get("attachment_uuids", [])

            if not attachment_uuids:
                continue

            blocks = []
            for uuid in attachment_uuids:
                try:
                    attachment = self.db.get_attachment_by_uuid(uuid)
                    if not attachment:
                        continue

                    # Load content
                    content_block = self.file_processor.load_for_context(attachment)

                    # Add filename label with UUID
                    uuid_short = attachment['uuid'][:8]
                    blocks.append({
                        "type": "text",
                        "text": f"📎 File [{uuid_short}]: {attachment['filename']}"
                    })

                    # Add content block(s)
                    if isinstance(content_block, list):
                        blocks.extend(content_block)
                    else:
                        blocks.append(content_block)

                except Exception as e:
                    print(f"⚠️ Failed to load historical attachment {uuid[:8]}: {str(e)}", flush=True)

            if blocks:
                history_attachments[msg_id] = blocks

        return history_attachments

    # =========================================================================
    # End helper methods
    # =========================================================================

    def process_message(self, user_input: str, sender: str = "user", attachment_uuids: list = None) -> Dict:
        """
        Process user message and generate response.

        Args:
            user_input: User's message
            sender: Who sent it ("user" or other identifier)
            attachment_uuids: List of attachment UUIDs to include in AI request (Phase 7)

        Returns:
            dict: {
                "response": str,  # AI response text
                "is_command": bool,  # Was this a @command?
                "command_result": dict (if command),
                "context_info": dict,  # Token counts, memories used
                "processing_info": dict  # Embedding/tagging status
            }

        PROCESS:
        1. Check for @command
        2. Store user message
        3. Generate embedding + queue for tagging
        4. Retrieve memories (if not command)
        5. Assemble context
        6. Call AI
        7. Store AI response
        8. Return response
        """
        user_input = user_input.strip()
        attachment_uuids = attachment_uuids or []

        if not user_input and not attachment_uuids:
            return {
                "response": "",
                "is_command": False,
                "error": "Empty input"
            }

        # Check for cold start - run tier transition before cache rebuild
        # When gap > 60min, cache has expired. Context may have grown during
        # previous active session (70k → 130k). Trim back to budget BEFORE
        # creating new cache to prevent expensive cache write on bloated context.
        use_caching, reason = self.cache_manager.should_use_caching()
        if "cold_start" in reason:
            print(f"Cold start detected ({reason}) - rebalancing tiers before cache rebuild", flush=True)
            self.tier_manager.transition_tiers(background_summaries=True)

            # CRITICAL: Reload conversation_history from database after tier changes!
            # Tier transition updates DB but doesn't touch in-memory conversation_history.
            # Cache is built from conversation_history, so we MUST reload it to respect
            # the new tier boundaries. Otherwise cache will include messages that were
            # just moved to "standard" tier.
            print(f"   ↳ Reloading conversation history from database...", flush=True)
            self.conversation_history = self._load_recent_context()
            print(f"   ↳ Loaded {len(self.conversation_history)} messages within budget", flush=True)

        # Check for @command
        if self.command_handler.is_command(user_input):
            return self._process_command(user_input, sender)

        # Process as normal conversation
        return self._process_conversation(user_input, sender, attachment_uuids)

    def process_message_stream(self, user_input: str, sender: str = "user", attachment_uuids: list = None):
        """
        Process user message and stream AI response in real-time (Phase 4.3).

        Args:
            user_input: User's message
            sender: Who sent it ("user" or other identifier)
            attachment_uuids: List of attachment UUIDs to include in AI request (Phase 7)

        Yields:
            dict: Stream events with types:
                - {"type": "notification", "data": "🤖 Processing..."}
                - {"type": "chunk", "data": "partial response text"}
                - {"type": "done", "data": {...complete result...}}

        STREAMING BEHAVIOR:
        - Commands return immediately (no streaming)
        - Notifications sent during processing
        - AI response streamed chunk-by-chunk
        - Final metadata sent at end
        """
        user_input = user_input.strip()
        attachment_uuids = attachment_uuids or []

        if not user_input and not attachment_uuids:
            yield {"type": "error", "data": "Empty input"}
            return

        # Check for cold start
        use_caching, reason = self.cache_manager.should_use_caching()
        if "cold_start" in reason:
            yield self._status("cold_start", "cold start", "First message after a break — rebalancing tiers")
            changes = self.tier_manager.transition_tiers(background_summaries=True)
            self.conversation_history = self._load_recent_context()
            yield self._status("history_loaded", "history loaded", f"Loaded {len(self.conversation_history)} messages from recent conversation")

            # Notify about background tasks kicked off by tier transition
            transitioned = changes.get("transitioned_to_standard", 0)
            if transitioned > 0 and self.tier_manager.summaries_enabled:
                yield self._status("entity_summaries_updating", "summaries updating", f"Updating entity summaries for {transitioned} transitioned messages")

        # Check for @command (commands don't stream - return immediately)
        if self.command_handler.is_command(user_input):
            result = self._process_command(user_input, sender)
            # Yield the response text as a chunk so it displays in the frontend
            if result.get("response"):
                yield {"type": "chunk", "data": result["response"]}
            yield {"type": "done", "data": result}
            return

        # Stream normal conversation
        yield from self._process_conversation_stream(user_input, sender, attachment_uuids)

    def _process_command(self, command_input: str, sender: str) -> Dict:
        """
        Process @command.

        Args:
            command_input: Command string
            sender: Who issued command

        Returns:
            dict: Command result with formatted response
        """
        self.stats["commands_executed"] += 1

        # Store command input as user message (marked temporary for cleanup)
        command_msg_id = self.db.add_message(
            sender=sender,
            content=command_input,
            importance_score=3.0,
            metadata={"temporary": True, "is_command": True}  # Prevent cache pollution
        )

        # Add to conversation history with temporary flag
        self.conversation_history.append({
            "id": command_msg_id,
            "sender": sender,
            "content": command_input,
            "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
            "temporary": True  # Filtered from cache structure
        })

        # Track for cleanup after next AI response
        self.temporary_message_ids.append(command_msg_id)

        try:
            result = self.command_handler.handle_command(command_input, marked_by=sender)

            # Format response
            if result["success"]:
                response_text = f"✓ {result['message']}"

                # Add data if present
                if "data" in result and result["data"]:
                    data = result["data"]

                    # Format based on command
                    if result["command"] == "recall":
                        response_text += f"\n\nFound {len(data.get('results', []))} memories:\n"
                        for i, mem in enumerate(data.get("results", [])[:10], 1):  # Show top 10
                            response_text += f"\n[{i}] ({mem['importance']:.1f}/10) {mem['timestamp'][:10]}\n"
                            response_text += f"  {mem['content']}\n"
                            if mem.get("tags"):
                                response_text += f"  Tags: {', '.join(mem['tags'])}\n"

                    elif result["command"] == "review":
                        response_text += f"\n\n{len(data.get('results', []))} memories:\n"
                        for i, mem in enumerate(data.get("results", [])[:20], 1):
                            response_text += f"\n[{i}] ({mem['importance']:.1f}/10) {mem['sender']}\n"
                            response_text += f"  {mem['content']}\n"

                    elif result["command"] == "config":
                        if not data.get("parameter"):  # Showing current config
                            response_text += "\n\nCurrent settings:\n"
                            for key, value in data.items():
                                response_text += f"  {key}: {value}\n"
            else:
                response_text = f"✗ {result['message']}"

            # Store command result as assistant message
            result_msg_id = self.db.add_message(
                sender="system",
                content=response_text,
                importance_score=3.0,
                metadata={"temporary": True, "command_type": result["command"]}
            )

            # Add to conversation history with temporary flag
            # This flag will be checked when building cache structure
            self.conversation_history.append({
                "id": result_msg_id,
                "sender": "system",
                "content": response_text,
                "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
                "temporary": True  # Mark as temporary for cache filtering
            })

            # Track as temporary for cleanup
            self.temporary_message_ids.append(result_msg_id)

            return {
                "response": response_text,
                "is_command": True,
                "command_result": result,
                "context_info": {},
                "processing_info": {}
            }

        except Exception as e:
            self.stats["commands_executed"] -= 1  # Don't count failed commands

            # Store error as system message
            error_msg_id = self.db.add_message(
                sender="system",
                content=f"✗ Command failed: {str(e)}",
                importance_score=3.0,
                metadata={"temporary": True, "command_type": "error"}
            )
    
            self.conversation_history.append({
                "id": error_msg_id,
                "sender": "system",
                "content": f"✗ Command failed: {str(e)}",
                "timestamp": datetime.now(timezone.utc).isoformat() + "Z"
            })

            # Track as temporary for cleanup
            self.temporary_message_ids.append(error_msg_id)

            return {
                "response": f"✗ Command failed: {str(e)}",
                "is_command": True,
                "error": str(e)
            }

    def _process_conversation(self, user_input: str, sender: str, attachment_uuids: list = None) -> Dict:
        """
        Non-streaming conversation — wraps the streaming pipeline and collects output.
        Kept for compatibility when streaming is disabled in config (streaming_enabled: false).

        The streaming path is canonical; this wrapper automatically inherits all its
        improvements (early save on disconnect, usage tracking, thinking support, etc.).
        """
        result = {}
        thinking_parts = []

        for event in self._process_conversation_stream(user_input, sender, attachment_uuids):
            if event["type"] == "thinking":
                thinking_parts.append(event["data"])
            elif event["type"] == "done":
                result = event["data"]
            elif event["type"] == "error":
                return {
                    "response": event["data"],
                    "is_command": False,
                    "error": event["data"]
                }

        if thinking_parts:
            result["thinking"] = "".join(thinking_parts)

        return result

    def _process_conversation_stream(self, user_input: str, sender: str, attachment_uuids: list = None):
        """
        Process normal conversation message with streaming (Phase 4.3).

        Args:
            user_input: User's message
            sender: Who sent it
            attachment_uuids: List of attachment UUIDs to include in AI request (Phase 7)

        Yields:
            dict: Stream events (type: notification/chunk/done)
        """
        attachment_uuids = attachment_uuids or []
        self.stats["messages_received"] += 1
        self.messages_since_concept_check += 1  # Track messages for concept extraction (Phase 6)
        self.messages_since_notes_check += 1  # Track messages for notes cleanup (Phase 11)

        # Sync conversation_history with DB if out of sync (e.g. after interruption)
        # Interruption saves messages to DB but never calls _add_to_history,
        # so the in-memory history can be stale. Append only missing messages
        # to preserve existing list objects and cache prefix.
        last_history_id = self.conversation_history[-1]["id"] if self.conversation_history else 0
        last_db_msg = self.db.get_recent_messages(limit=1)
        last_db_id = last_db_msg[0]["id"] if last_db_msg else 0
        if last_db_id > last_history_id:
            missing = self.db.execute_query(
                """SELECT id, sender, content, timestamp FROM messages
                   WHERE id > ? AND content != ''
                   AND (metadata IS NULL OR json_extract(metadata, '$.temporary') IS NULL)
                   ORDER BY id ASC""",
                (last_history_id,)
            )
            for msg in missing:
                attachments = self.db.get_attachments_for_message(msg["id"])
                self.conversation_history.append({
                    "id": msg["id"],
                    "sender": msg["sender"],
                    "content": msg["content"],
                    "timestamp": msg["timestamp"],
                    "attachment_uuids": [a["uuid"] for a in attachments] if attachments else []
                })

        # Phase 9: Check for day rollover (generates yesterday's summary if needed)
        if self._check_day_rollover():
            yield self._status("day_rollover", "new day", "Day changed — generating yesterday's summary in background")

        # Drain startup notifications (importance decay, backfill, etc.)
        while self._startup_notifications:
            yield self._startup_notifications.pop(0)

        # Step 1: Store user message
        user_msg_id = self.db.add_message(
            sender=sender,
            content=user_input,
            importance_score=3.0
        )

        # Step 1.5: Link attachments to user message (Phase 7)
        for uuid in attachment_uuids:
            self.db.link_attachment_to_message(uuid, user_msg_id)

        # Step 2: Generate embedding + queue for tagging
        yield self._status("processing", "processing", "Processing your message...")
        processing_info = self.background_queue.add_message(
            user_msg_id,
            user_input,
            sender
        )

        # Notify embedding status
        if processing_info.get("embedding_generated"):
            yield self._status("embedding", "embedded", "Generated search embedding for your message")
        elif len(user_input) > 15000:
            yield self._status("embedding_skipped", "too large", f"Message too large for embedding ({len(user_input)} chars — skipped)")

        # Notify entity assignment results
        entity_details = processing_info.get("entity_batch_details")
        if entity_details and entity_details.get("success"):
            if entity_details.get("new_entity_names"):
                names = ", ".join(entity_details["new_entity_names"])
                new_details = entity_details.get("new_entity_details", [])
                if new_details:
                    detail_items = [
                        {"label": e["name"], "content": f"aliases: {', '.join(e['aliases'])}" if e.get("aliases") else "(no aliases)"}
                        for e in new_details
                    ]
                else:
                    detail_items = [{"label": n, "content": n} for n in entity_details["new_entity_names"]]
                yield self._status(
                    "new_entities", "new entities", f"Auto-created entities: {names}",
                    detail={
                        "explanation": "New topics were identified and added as named entities. Each entity can accumulate a summary of relevant context over time.",
                        "items": detail_items
                    }
                )
            links = entity_details.get("links_created", 0)
            msgs = entity_details.get("messages_processed", 0)
            if links > 0:
                yield self._status("entity_links", "entities linked", f"Linked {links} entities across {msgs} messages")

        # Step 3: Assemble context
        yield self._status("context_assembly", "assembling", "Assembling context from memory...")

        # Check if query is too large for semantic search
        if len(user_input) > 15000:
            yield self._status("semantic_skip", "search skipped", f"Message too large for semantic search ({len(user_input)} chars)")

        context = self.context_assembler.assemble_context(
            recent_messages=self._get_recent_messages(),
            current_query=user_input
        )
        context["user_msg_id"] = user_msg_id

        # Step 3.1: Add timeline context (Phase 9)
        if self.timeline_enabled:
            timeline_context, timeline_tokens = self.context_assembler.get_timeline_context()
            context["timeline_context"] = timeline_context
            context["token_counts"]["timeline"] = timeline_tokens
            context["token_counts"]["total"] += timeline_tokens

        # Notify context assembly results
        tc = context["token_counts"]
        md = context["metadata"]

        memories_count = md["memories_included"]
        if memories_count > 0:
            # Build description list from memory metadata
            descriptions = []
            for mem in context.get("retrieved_memories", []):
                meta = mem.get("metadata")
                if isinstance(meta, str):
                    import json as _json
                    try:
                        meta = _json.loads(meta)
                    except Exception:
                        meta = {}
                desc = (meta or {}).get("description", "")
                if desc:
                    descriptions.append(desc)

            dupes = md["memories_skipped_duplicate"]
            dupe_note = f" ({dupes} duplicates skipped)" if dupes > 0 else ""

            if descriptions:
                if len(descriptions) == 1:
                    desc_str = descriptions[0]
                elif len(descriptions) == 2:
                    desc_str = f"{descriptions[0]} and {descriptions[1]}"
                else:
                    desc_str = ", ".join(descriptions[:-1]) + f", and {descriptions[-1]}"
                summary = f"Retrieved messages about {desc_str}{dupe_note}"
            else:
                summary = f"Retrieved {memories_count} relevant {'message' if memories_count == 1 else 'messages'}{dupe_note}"

            # Build detail items from retrieved memories
            detail_items = []
            for mem in context.get("retrieved_memories", []):
                meta = mem.get("metadata")
                if isinstance(meta, str):
                    try:
                        import json as _json
                        meta = _json.loads(meta)
                    except Exception:
                        meta = {}
                desc = (meta or {}).get("description", "")
                sender = mem.get("sender", "user")
                content = mem.get("content", "")
                timestamp = mem.get("timestamp", "")
                label = desc if desc else f"{sender} message"
                detail_items.append({
                    "label": label,
                    "sender": sender,
                    "content": f"{sender}: {content}",
                    "timestamp": timestamp
                })

            yield self._status(
                "memories_found", "memories found", summary,
                detail={
                    "explanation": f"Semantic search finds past messages most relevant to your current message. These are injected into {self.instance_name}'s context so it can reference them naturally.",
                    "items": detail_items
                }
            )
        else:
            yield self._status("no_memories", "no matches", "No relevant memories found for this message")

        if tc.get("entity_summaries", 0) > 0:
            bootstrapped = md.get("entities_bootstrapped", [])
            for name in bootstrapped:
                yield self._status("entity_bootstrapped", "entity created", f"Generated first summary for {name}")

            # Get entity names from metadata
            entity_names = md.get("entity_names_loaded", [])
            if entity_names:
                if len(entity_names) == 1:
                    names_str = entity_names[0]
                elif len(entity_names) == 2:
                    names_str = f"{entity_names[0]} and {entity_names[1]}"
                else:
                    names_str = ", ".join(entity_names[:-1]) + f", and {entity_names[-1]}"
                summary = f"Loaded context for {names_str}"
            else:
                summary = f"Loaded entity context ({tc['entity_summaries']} tokens)"

            entity_detail = md.get("entity_summaries_detail", [])
            detail_items = [
                {"label": e["name"], "content": e["summary"]}
                for e in entity_detail
            ] if entity_detail else [{"label": name, "content": name} for name in entity_names]

            yield self._status(
                "entity_summaries", "entities loaded", summary,
                detail={
                    "explanation": f"Entity summaries are AI-generated profiles of recurring topics, people, and themes. They give {self.instance_name} long-term context about who and what you talk about most.",
                    "items": detail_items
                }
            )

        if tc.get("notes", 0) > 0:
            notes_text = context.get("notes_context", "")
            yield self._status(
                "notes_loaded", "notes loaded", "Persistent notes active",
                detail={
                    "explanation": f"AI notes are sections of persistent memory that {self.instance_name} manages itself — updated automatically to track ongoing projects, preferences, and important context that should always be available.",
                    "items": [{"label": "notes", "content": notes_text}] if notes_text else []
                }
            )
            if context.get("notes_cleanup_needed"):
                yield self._status("notes_warning", "notes full", "Notes approaching capacity — cleanup may trigger this turn")

        if tc.get("concepts", 0) > 0:
            concept_matches = context.get("metadata", {}).get("concept_matches", [])
            concept_names = context.get("metadata", {}).get("concept_names", [])
            concept_summary = f"Loaded concepts: {', '.join(n.replace('_', ' ') for n in concept_names)}" if concept_names else "Narrative concept context loaded"

            # Build per-concept detail items
            concept_items = []
            for m in concept_matches:
                name = m.get("name", "").replace("_", " ")
                keywords = ", ".join(m.get("matched_keywords", [])[:5])
                content = m.get("definition", "")
                if keywords:
                    content += f"\nTriggered by: {keywords}"
                concept_items.append({"label": name, "content": content})

            yield self._status(
                "concepts_loaded", "concepts loaded", concept_summary,
                detail={
                    "explanation": "Narrative concepts are manually-defined knowledge entries that trigger based on keywords in your conversation. They inject curated context about recurring themes and topics.",
                    "items": concept_items
                }
            )

        if tc.get("files", 0) > 0:
            files_text = context.get("files_context", "")
            yield self._status(
                "files_loaded", "files loaded", f"Loaded {len(attachment_uuids) if attachment_uuids else 'file'} attachment(s)",
                detail={
                    "explanation": f"File attachments are images, PDFs, or text files you shared in this conversation. Their content is injected directly into {self.instance_name}'s context.",
                    "items": [{"label": "file context", "content": files_text}] if files_text else []
                }
            )

        if tc.get("timeline", 0) > 0:
            timeline_text = context.get("timeline_context", "")
            yield self._status(
                "timeline_loaded", "timeline loaded", "Daily timeline context loaded",
                detail={
                    "explanation": f"Timeline context is a 7-day rolling summary of your recent conversations — one paragraph per day. It gives {self.instance_name} awareness of what you've been doing and discussing this week.",
                    "items": [{"label": "timeline", "content": timeline_text}] if timeline_text else []
                }
            )

        dynamic_total = tc['total'] - tc.get('recent', 0)
        yield self._status(
            "token_budget", "context ready", "Context assembled and ready",
            detail={
                "explanation": "Each turn, dynamic context (memories, summaries, notes, etc.) is injected fresh into the prompt. The conversation history is cached separately and not counted here.",
                "items": [{"label": "token breakdown", "content": (
                    f"dynamic (this turn): {dynamic_total:,}\n"
                    f"  memories: {tc.get('memories', 0):,}\n"
                    f"  entity summaries: {tc.get('entity_summaries', 0):,}\n"
                    f"  notes: {tc.get('notes', 0):,}\n"
                    f"  concepts: {tc.get('concepts', 0):,}\n"
                    f"  timeline: {tc.get('timeline', 0):,}\n\n"
                    f"conversation history: {tc.get('recent', 0):,}\n"
                    f"total: {tc['total']:,} / {tc['budget']:,}"
                )}]
            }
        )

        sections = self.prompt_builder.build_sections(context, user_input)

        # Step 3.5: Load attachment content blocks (Phase 7)
        attachment_blocks = self._load_attachment_blocks(attachment_uuids)
        if attachment_blocks:
            yield self._status("attachments", "attachments", f"Loaded {len(attachment_uuids)} file attachment(s)")

        # Cache overflow protection — check last turn's total before this turn's API call
        if self.last_total_prompt_tokens >= 195_000:
            yield self._status("cache_overflow", "trimming", f"Context near limit ({self.last_total_prompt_tokens:,} tokens) — forcing tier transition")
            self.tier_manager.transition_tiers(background_summaries=True)
            self.conversation_history = self._load_recent_context()
            yield self._status("context_trimmed", "trimmed", f"Conversation trimmed to {len(self.conversation_history)} messages")
        elif self.last_total_prompt_tokens >= 185_000:
            yield self._status("cache_warning", "context full", f"Approaching token limit ({self.last_total_prompt_tokens:,}/200k) — consider starting a new session soon")

        # Step 4: Call AI model with streaming
        use_caching, cache_reason = self.cache_manager.should_use_caching()
        if use_caching:
            cache_desc = "cache active"
        elif cache_reason == "cold_start_first":
            cache_desc = "first message — cache starting"
        elif cache_reason and cache_reason.startswith("cold_start_gap_"):
            mins = cache_reason.replace("cold_start_gap_", "").replace("min", "")
            cache_desc = f"{mins}-minute gap — cache restarting"
        else:
            cache_desc = "cache paused"
        yield self._status(
            "calling_api", "calling API", f"Sending to {self.instance_name} ({cache_desc})",
            detail={"explanation": "Cache saves API credits by keeping the conversation context active on Anthropic's servers. When active, responses are faster and cheaper."}
        )

        # Pre-allocate AI message ID before the API call so the AI sees its own ID in context
        ai_msg_id = self.db.add_message(sender="assistant", content="", importance_score=3.0)
        context["ai_msg_id"] = ai_msg_id

        try:
            # Call AI with stream=True - returns AIClient stream generator
            stream = self._call_ai(context=context, current_input=user_input, stream=True, attachment_blocks=attachment_blocks)

            # Accumulate full response while streaming chunks
            full_response = ""
            accumulated_thinking = ""
            usage_data = None

            # Stream chunks from AIClient (abstracted format)
            for event in stream:
                if event["type"] == "start":
                    # Stream started
                    pass
                elif event["type"] == "thinking_start":
                    # Extended thinking block started (Phase 10)
                    if self.show_thinking:
                        yield {"type": "thinking_start", "data": None}
                elif event["type"] == "thinking":
                    # Extended thinking chunk (Phase 10)
                    accumulated_thinking += event["data"]
                    if self.show_thinking:
                        yield {"type": "thinking", "data": event["data"]}
                elif event["type"] == "chunk":
                    chunk = event["data"]
                    full_response += chunk
                    yield {"type": "chunk", "data": chunk}
                elif event["type"] == "end":
                    # Stream ended - extract usage from APIUsage object
                    end_data = event["data"]
                    usage_obj = end_data["usage"]
                    usage_data = {
                        "input_tokens": usage_obj.input_tokens,
                        "output_tokens": usage_obj.output_tokens,
                        "cache_creation_input_tokens": usage_obj.cache_creation_tokens,
                        "cache_read_input_tokens": usage_obj.cache_read_tokens
                    }
                    # Capture thinking from end event if we missed accumulating it
                    if not accumulated_thinking and end_data.get("thinking"):
                        accumulated_thinking = end_data["thinking"]

            ai_response = full_response

            # Update timestamp for gap detection (Phase 4.1 - CRITICAL for caching)
            # Without this, streaming mode treats every message as cold start!
            self.cache_manager.update_message_time()

            # Generate and send cache notification (Phase 4.3 - FIX for missing cache details)
            # This was missing in streaming mode, causing notifications to show no token details
            if usage_data:
                use_caching = usage_data["cache_creation_input_tokens"] > 0 or usage_data["cache_read_input_tokens"] > 0

                # Still record for internal metrics (but don't use the returned string for display)
                self.cache_manager.record_message(
                    cached=use_caching,
                    usage=usage_data,
                    model=self.model
                )

                dynamic = usage_data["input_tokens"]
                cache_read = usage_data["cache_read_input_tokens"]
                cache_write = usage_data["cache_creation_input_tokens"]
                total = dynamic + cache_read + cache_write

                if cache_read > 0:
                    pill = "cache active"
                    summary = f"{self.instance_name} received {total // 1000}k tokens — {cache_read // 1000}k from cache"
                elif cache_write > 0:
                    pill = "cache written"
                    summary = f"Cache written ({cache_write // 1000}k tokens) — next turn will be faster"
                else:
                    pill = "no cache"
                    summary = f"Sent {total // 1000}k tokens (no cache this turn)"

                yield self._status(
                    "cache_result", pill, summary,
                    detail={
                        "explanation": f"Prompt caching tells Anthropic's servers to keep the conversation context active between your messages. When the cache is hit, {self.instance_name} receives previous context without you paying full input token cost — saves credits and speeds up responses.",
                        "items": [{"label": "token breakdown", "content": (
                            f"dynamic (new): {dynamic:,}\n"
                            f"cached (read): {cache_read:,}\n"
                            f"cached (written): {cache_write:,}\n"
                            f"total: {total:,}"
                        )}]
                    }
                )

                self.last_total_prompt_tokens = total

            # Drain any pending notifications from _call_ai (concept/notes reminders etc.)
            for notif in self._pending_notifications:
                yield {"type": "notification", "data": notif}
            self._pending_notifications.clear()

        except Exception as e:
            self._pending_notifications.clear()
            self.db.delete_message(ai_msg_id)
            self.db.delete_message(user_msg_id)
            yield {"type": "error", "data": f"Error calling AI: {str(e)}"}
            return

        # Step 5: Add user message to conversation history (with attachments)
        # NOTE: Only save user input, NOT retrieved memories (prevents cache growth)
        self._add_to_history(user_msg_id, sender, user_input, attachment_uuids)

        # Step 5.5: Save initial AI response to the pre-allocated message record
        initial_response = ai_response
        self.db.update_message_content(ai_msg_id, ai_response)

        # Step 5.55: Save thinking to metadata if present (Phase 10)
        if accumulated_thinking:
            self.db.update_message_metadata(ai_msg_id, {"thinking": accumulated_thinking}, merge=True)

        # Step 5.6: Check for instance commands with streaming notifications
        def ai_caller(ctx, current_input, stream):
            blocks = ctx.pop("_continuation_content_blocks", None)
            return self._call_ai(context=ctx, current_input=current_input, stream=stream, attachment_blocks=blocks)

        ai_response, _ = yield from self.instance_executor.execute_loop_stream(
            ai_response, context, ai_caller
        )

        # Step 5.7: Strip @run code blocks from stored response (save tokens in cache)
        # The AI already has the output via continuation; the source code is dead weight.
        ai_response = re.sub(
            r'^@run\s*\n[\s\S]*?^@endrun\s*$',
            '[ran python]',
            ai_response,
            flags=re.MULTILINE
        )

        # Step 6: Update AI response if it changed (due to command execution)
        if ai_response != initial_response:
            self.db.update_message_content(ai_msg_id, ai_response)

        self._add_to_history(ai_msg_id, "assistant", ai_response)

        # Cleanup temporary messages
        cleanup_notifications = self._cleanup_temporary_messages(ai_response)
        for note in cleanup_notifications:
            yield {"type": "notification", "data": {"id": "cleanup", "pill": "cleanup", "summary": note}}

        # Step 7: Finalize (background processing)
        yield self._status("finalizing", "finalizing", "Saving response and updating indexes...")
        ai_processing_info = self._finalize_response(ai_response, ai_msg_id, context)

        # Notify finalization results
        if ai_processing_info.get("embedding_generated"):
            yield self._status("response_embedding", "indexed", f"Generated search embedding for {self.instance_name}'s response")
        if ai_processing_info.get("queued_for_entity_assignment") or ai_processing_info.get("queued_for_tagging"):
            queue_status = self.background_queue.get_queue_status()
            yield self._status("entity_queued", "entities queued", f"Queued for entity assignment ({queue_status['entity_queue_size']}/{self.background_queue.entity_batch_size} in batch)")
        if ai_processing_info.get("entity_batch_processed"):
            bg_stats = self.background_queue.get_statistics()
            yield self._status("entity_batch", "entities assigned", f"Entity assignment batch complete ({bg_stats['entity_links_created']} total links created)")

        self.stats["messages_sent"] += 1

        # Send final metadata
        yield {"type": "done", "data": self._build_result(ai_response, context, processing_info, ai_processing_info)}

    def continue_message_stream(self, interrupted_message_id: int):
        """
        Continue a previously interrupted AI response.

        Loads the partial message from DB, asks the AI to continue seamlessly
        from where it left off, streams the continuation, then merges the result
        back into the original DB message (removing the [message interrupted] suffix).

        Args:
            interrupted_message_id: DB id of the interrupted assistant message

        Yields:
            SSE-style event dicts: notification, chunk, done, error
        """
        # Load the interrupted message
        interrupted_msg = self.db.get_message(interrupted_message_id)
        if not interrupted_msg:
            yield {"type": "error", "data": f"Message {interrupted_message_id} not found"}
            return

        raw_content = interrupted_msg['content']
        suffix = '\n\n[message interrupted]'
        if raw_content.endswith(suffix):
            partial_clean = raw_content[:-len(suffix)].rstrip()
        else:
            partial_clean = raw_content

        # Build ephemeral continuation prompt (not stored to DB)
        continuation_prompt = (
            "[Your previous response was cut off. Here is what you had written so far:\n\n"
            f"{partial_clean}\n\n"
            "Please continue your response seamlessly from exactly where it was cut off. "
            "Do not restate anything already written — continue the content directly.]"
        )

        # Assemble context (uses conversation history which already includes the user message)
        yield self._status("continuing", "continuing", "Continuing previous response...")
        context = self.context_assembler.assemble_context(
            recent_messages=self._get_recent_messages(),
            current_query=partial_clean
        )

        if self.timeline_enabled:
            timeline_context, timeline_tokens = self.context_assembler.get_timeline_context()
            context["timeline_context"] = timeline_context
            context["token_counts"]["timeline"] = timeline_tokens
            context["token_counts"]["total"] += timeline_tokens

        use_caching, cache_reason = self.cache_manager.should_use_caching()
        if use_caching:
            cache_desc = "cache active"
        elif cache_reason == "cold_start_first":
            cache_desc = "first message — cache starting"
        elif cache_reason and cache_reason.startswith("cold_start_gap_"):
            mins = cache_reason.replace("cold_start_gap_", "").replace("min", "")
            cache_desc = f"{mins}-minute gap — cache restarting"
        else:
            cache_desc = "cache paused"
        yield self._status(
            "calling_api", "calling API", f"Sending to {self.instance_name} ({cache_desc})",
            detail={"explanation": "Cache saves API credits by keeping the conversation context active on Anthropic's servers. When active, responses are faster and cheaper."}
        )

        try:
            stream = self._call_ai(context=context, current_input=continuation_prompt, stream=True)

            continuation_text = ""
            usage_data = None

            for event in stream:
                if event["type"] == "start":
                    pass
                elif event["type"] == "chunk":
                    chunk = event["data"]
                    continuation_text += chunk
                    yield {"type": "chunk", "data": chunk}
                elif event["type"] == "end":
                    end_data = event["data"]
                    usage_obj = end_data["usage"]
                    usage_data = {
                        "input_tokens": usage_obj.input_tokens,
                        "output_tokens": usage_obj.output_tokens,
                        "cache_creation_input_tokens": usage_obj.cache_creation_tokens,
                        "cache_read_input_tokens": usage_obj.cache_read_tokens
                    }

            self.cache_manager.update_message_time()

            if usage_data:
                use_caching = (usage_data["cache_creation_input_tokens"] > 0 or
                               usage_data["cache_read_input_tokens"] > 0)

                # Still record for internal metrics (but don't use the returned string for display)
                self.cache_manager.record_message(
                    cached=use_caching, usage=usage_data, model=self.model
                )

                dynamic = usage_data["input_tokens"]
                cache_read = usage_data["cache_read_input_tokens"]
                cache_write = usage_data["cache_creation_input_tokens"]
                total = dynamic + cache_read + cache_write

                if cache_read > 0:
                    pill = "cache active"
                    summary = f"{self.instance_name} received {total // 1000}k tokens — {cache_read // 1000}k from cache"
                elif cache_write > 0:
                    pill = "cache written"
                    summary = f"Cache written ({cache_write // 1000}k tokens) — next turn will be faster"
                else:
                    pill = "no cache"
                    summary = f"Sent {total // 1000}k tokens (no cache this turn)"

                yield self._status(
                    "cache_result", pill, summary,
                    detail={
                        "explanation": f"Prompt caching tells Anthropic's servers to keep the conversation context active between your messages. When the cache is hit, {self.instance_name} receives previous context without you paying full input token cost — saves credits and speeds up responses.",
                        "items": [{"label": "token breakdown", "content": (
                            f"dynamic (new): {dynamic:,}\n"
                            f"cached (read): {cache_read:,}\n"
                            f"cached (written): {cache_write:,}\n"
                            f"total: {total:,}"
                        )}]
                    }
                )

                self.last_total_prompt_tokens = total

            for notif in self._pending_notifications:
                yield {"type": "notification", "data": notif}
            self._pending_notifications.clear()

        except Exception as e:
            self._pending_notifications.clear()
            yield {"type": "error", "data": f"Error continuing response: {str(e)}"}
            return

        # Merge: replace DB content with clean partial + continuation (no interrupted suffix)
        merged_content = partial_clean + continuation_text
        self.db.update_message_content(interrupted_message_id, merged_content)

        # Update the existing history entry (or add if somehow missing)
        updated = False
        for msg in self.conversation_history:
            if msg.get("id") == interrupted_message_id:
                msg["content"] = merged_content
                updated = True
                break
        if not updated:
            self._add_to_history(interrupted_message_id, "assistant", merged_content)

        # Background processing (embeddings, entity assignment)
        self._finalize_response(merged_content, interrupted_message_id, context)

        yield {"type": "done", "data": {"merged_message_id": interrupted_message_id}}

    def _cleanup_temporary_messages(self, ai_response: str) -> List[str]:
        """
        Clean up temporary command results after AI response.

        Keeps messages if AI referenced them, deletes if not.

        Args:
            ai_response: The AI's response text

        Returns:
            List[str]: Notification messages about cleanup actions
        """
        notifications = []

        if not self.temporary_message_ids:
            return notifications  # Nothing to clean

        messages_to_keep = []
        messages_to_delete = []

        # Check each temporary message
        for msg_id in self.temporary_message_ids:
            # Find the message in conversation history
            temp_msg = None
            for msg in self.conversation_history:
                if msg["id"] == msg_id:
                    temp_msg = msg
                    break

            if not temp_msg:
                continue  # Already gone somehow

            # Check if AI referenced this content
            # Require multiple keyword matches to avoid false positives from common words
            content_keywords = [w for w in temp_msg["content"].lower().split()[:15] if len(w) > 5]
            ai_response_lower = ai_response.lower()

            match_count = sum(1 for kw in content_keywords if kw in ai_response_lower)
            referenced = match_count >= 2 or (len(content_keywords) == 1 and match_count == 1)

            if referenced:
                messages_to_keep.append(msg_id)
                # Update metadata in database to mark as keeper
                self.db.execute_write(
                    "UPDATE messages SET metadata = ? WHERE id = ?",
                    (json.dumps({"temporary": False, "kept_by_ai": True}), msg_id)
                )
                # Update temporary flag in conversation_history
                for msg in self.conversation_history:
                    if msg["id"] == msg_id:
                        msg["temporary"] = False
                        break
            else:
                messages_to_delete.append(msg_id)
                # Remove from conversation history
                self.conversation_history = [
                    msg for msg in self.conversation_history if msg["id"] != msg_id
                ]
                # Delete from database
                self.db.execute_write("DELETE FROM messages WHERE id = ?", (msg_id,))

        # Clear the temporary tracking list
        self.temporary_message_ids.clear()

        # Return notifications about what happened
        if messages_to_delete:
            notifications.append(f"🗑️  Cleaned up {len(messages_to_delete)} unused command results")
        if messages_to_keep:
            notifications.append(f"📌 Kept {len(messages_to_keep)} referenced command results")

        return notifications

    # NOTE: Instance command execution moved to instance_executor.py
    # Methods removed: _parse_instance_commands, _execute_instance_command_loop_stream,
    #                  _execute_instance_command_loop, _apply_remember_to_message

    def _print_startup_stats(self):
        """
        Print startup statistics showing current configuration.

        Shows:
        - Active model
        - Context windows
        - Cache settings
        - Memory tier budgets
        """
        print("\n" + "="*60)
        print("📊 MNEME STARTUP CONFIGURATION")
        print("="*60)

        # Model info
        model_id = self.model
        print(f"\n🤖 Model: {model_id}")
        print(f"   Temperature: {self.temperature}")
        print(f"   Max tokens: {self.max_tokens:,}")

        # Context windows
        print(f"\n💭 Context Windows:")
        print(f"   Recent messages: {self.context_assembler.recent_budget:,} tokens")
        print(f"   Retrieved memories: max {self.context_assembler.memory_limit} results")

        # Cache settings
        cache_enabled = self.cache_manager.enabled
        cache_ttl = "1 hour" if self.cache_manager.use_extended_ttl else "5 minutes"
        print(f"\n💾 Prompt Caching:")
        print(f"   Status: {'✅ Enabled' if cache_enabled else '❌ Disabled'}")
        if cache_enabled:
            print(f"   TTL: {cache_ttl} (refreshes on each use)")
            print(f"   Tier transitions: On cold starts (gap > {self.cache_manager.adaptive_threshold_minutes} min)")
            print(f"   Cold start threshold: {self.cache_manager.adaptive_threshold_minutes} minutes")

        # Memory tiers (use tier manager)
        tier_stats = self.tier_manager.get_tier_statistics()

        print(f"\n Memory Tiers:")
        print(f"   Active: {tier_stats['active']:,} messages")
        print(f"   Standard: {tier_stats['standard']:,} messages")
        print(f"   Deep Archive: {tier_stats['deep_archive']:,} messages")
        print(f"   Total: {tier_stats['total']:,} messages")

        # Conversation history
        hist_size = len(self.conversation_history)
        print(f"\n📝 Conversation History:")
        print(f"   Loaded: {hist_size} messages")

        # AI Notes (Phase 11)
        notes_enabled = self.context_assembler.notes_enabled
        print(f"\n📝 AI Notes (Phase 11):")
        print(f"   Status: {'✅ Enabled' if notes_enabled else '❌ Disabled'}")
        if notes_enabled:
            notes = self.db.get_all_notes()
            print(f"   Sections: {len(notes)}")
            print(f"   Token budget: {self.context_assembler.notes_max_tokens:,}")
            print(f"   Cleanup threshold: {int(self.context_assembler.notes_cleanup_threshold * 100)}%")

        # Concept auto-extraction (Phase 6)
        if self.prompt_builder.concept_auto_extract_enabled:
            messages_until_trigger = self.prompt_builder.concept_extract_frequency - self.messages_since_concept_check
            print(f"\n🔔 Concept Auto-Extraction (Phase 6):")
            print(f"   Status: ✅ Enabled")
            print(f"   Progress: {self.messages_since_concept_check}/{self.prompt_builder.concept_extract_frequency} messages")
            print(f"   Next reminder: in {messages_until_trigger} message{'s' if messages_until_trigger != 1 else ''}")
        else:
            print(f"\n🔔 Concept Auto-Extraction (Phase 6):")
            print(f"   Status: ❌ Disabled")

        # Extended thinking (Phase 10)
        if self.thinking_enabled:
            print(f"\n🧠 Extended Thinking (Phase 10):")
            print(f"   Status: ✅ Enabled")
            print(f"   Budget: {self.thinking_budget:,} tokens")
            print(f"   Show in UI: {'Yes' if self.show_thinking else 'No'}")
        else:
            print(f"\n🧠 Extended Thinking (Phase 10):")
            print(f"   Status: ❌ Disabled")

        # Timeline awareness
        timeline_config = self.config.get("features", {}).get("timeline", {})
        if timeline_config.get("enabled", False):
            days_to_show = timeline_config.get("days_to_show", 7)
            user_name = self.config.get("identity", {}).get("user_name", "") or "Human"
            print(f"\n📅 Timeline Awareness:")
            print(f"   Status: ✅ Enabled")
            print(f"   Window: {days_to_show} days")
            print(f"   User name: {user_name}")
            print(f"   Cost: ~$0.04-0.06 per day (Haiku)")
        else:
            print(f"\n📅 Timeline Awareness:")
            print(f"   Status: ❌ Disabled")

        print("\n" + "="*60 + "\n")

    def _get_recent_messages(self, limit: int = None) -> List[Dict]:
        """
        Get recent messages for context.

        Args:
            limit: Maximum messages to return (None = all messages)

        Returns:
            List[Dict]: Recent messages

        Uses in-memory conversation_history first, falls back to database.
        Token budget in ContextAssembler will naturally limit what fits.
        """
        if self.conversation_history:
            if limit:
                return self.conversation_history[-limit:]
            else:
                # Return ALL messages - let token budget handle limiting
                return self.conversation_history
        else:
            # First message - get from database
            # Use large limit since token budget will naturally limit what fits
            if limit is None:
                limit = 10000  # Large number = get everything, let token budget handle it
            return self.db.get_recent_messages(limit=limit)

    # NOTE: Prompt building methods moved to prompt_builder.py (Phase 2 refactor):
    # - _should_trigger_concept_check()
    # - _generate_concept_reminder()
    # - _build_prompt_sections()
    # - _build_prompt()
    # - _get_system_instructions()

    @retry_with_backoff(max_retries=3, initial_delay=2.0)
    def _call_ai(self, prompt: str = None, context: Dict = None, current_input: str = None, stream: bool = False, attachment_blocks: list = None):
        """
        Call AI model with adaptive caching support.

        Args:
            prompt: Complete prompt (for non-cached fallback or when context not provided)
            context: Context dict with sections (for caching)
            current_input: Current user message (for caching)
            stream: If True, return streaming response (Phase 4.3)
            attachment_blocks: List of content blocks for attachments (Phase 7)

        Returns:
            str: AI response (or stream generator if stream=True)

        Raises:
            ConversationError: If API call fails after retries

        ADAPTIVE CACHING:
        - Checks if caching should be used (gap detection)
        - If yes: Uses structured message format with cache_control markers
        - If no: Uses regular prompt format (cold start, avoids write penalty)

        ERROR HANDLING (Phase 4.4):
        - Automatic retry with exponential backoff (2s, 4s, 8s)
        - Rate limit handling (60s delay on 429 errors)
        - User-friendly error messages
        - 60-second timeout per request
        """
        self.stats["api_calls"] += 1
        attachment_blocks = attachment_blocks or []

        # Decide if caching should be used
        use_caching, cache_reason = self.cache_manager.should_use_caching()

        try:
            # Build messages based on caching decision
            if use_caching and context is not None and current_input is not None:
                # Build sections using PromptBuilder
                sections = self.prompt_builder.build_sections(context, current_input)

                # Check if we should trigger concept extraction reminder (Phase 6)
                concept_reminder = None
                if self.prompt_builder.should_trigger_concept_check(self.messages_since_concept_check):
                    concept_reminder = self.prompt_builder.generate_concept_reminder(self.messages_since_concept_check)
                    self.messages_since_concept_check = 0  # Reset counter
                    print(f"🔔 Concept extraction reminder triggered ({self.prompt_builder.concept_extract_frequency} messages)", flush=True)
                    self._pending_notifications.append("🔔 Concept extraction injection activated")

                # Check if we should trigger notes cleanup reminder (Phase 11)
                notes_reminder = None
                if self.prompt_builder.should_trigger_notes_cleanup(self.messages_since_notes_check):
                    notes_reminder = self.prompt_builder.generate_notes_cleanup_reminder(self.messages_since_notes_check)
                    self.messages_since_notes_check = 0  # Reset counter
                    print(f"📝 Notes cleanup reminder triggered ({self.notes_cleanup_interval} messages)", flush=True)
                    self._pending_notifications.append("📝 Notes cleanup reminder injected")

                # Check if we should prompt for file descriptions (Phase 7)
                describe_reminder = None
                if attachment_blocks and self.prompt_builder.should_trigger_describe_check():
                    describe_reminder = self.prompt_builder.generate_describe_reminder()
                    if describe_reminder:
                        print(f"📎 File description reminder triggered", flush=True)

                # Pre-load attachment blocks for historical messages (Phase 7)
                history_attachments = self._load_history_attachment_blocks(self.conversation_history)

                # Combine concept + notes reminders into single reminder block
                combined_reminder = concept_reminder or ""
                if notes_reminder:
                    combined_reminder = (combined_reminder + "\n\n" + notes_reminder).strip() if combined_reminder else notes_reminder

                # Build proper multi-turn message structure with caching
                cache_structure = self.prompt_builder.build_cached_structure(
                    sections=sections,
                    conversation_history=self.conversation_history,
                    current_input=current_input,
                    concept_reminder=combined_reminder or None,
                    attachment_blocks=attachment_blocks,
                    describe_reminder=describe_reminder,
                    history_attachments=history_attachments
                )

                # Extract components
                tools_param = cache_structure["tools"]
                system_param = cache_structure["system"]
                messages = cache_structure["messages"]

                # Get cache headers
                extra_headers = self.cache_manager.get_api_headers()

                # Print to both stdout (for frontend) and stderr (for console debugging)
                cache_msg = f"💾 Cache: Enabled ({cache_reason})"
                print(cache_msg, flush=True)
                print(cache_msg, file=sys.stderr, flush=True)

            else:
                # Cold start - use regular format
                if prompt is None:
                    if context is not None and current_input is not None:
                        sections = self.prompt_builder.build_sections(context, current_input)
                        # For cold start, use simple string format
                        # Include timeline in system param (Phase 9)
                        system_param = sections["system"]
                        if sections.get("timeline"):
                            system_param = system_param + "\n\n" + sections["timeline"]

                        # Check if we should trigger concept extraction reminder (Phase 6)
                        concept_reminder_text = ""
                        if self.prompt_builder.should_trigger_concept_check(self.messages_since_concept_check):
                            concept_reminder_text = "\n\n" + self.prompt_builder.generate_concept_reminder(self.messages_since_concept_check) + "\n\n"
                            self.messages_since_concept_check = 0  # Reset counter
                            print(f"🔔 Concept extraction reminder triggered ({self.prompt_builder.concept_extract_frequency} messages)", flush=True)
                            self._pending_notifications.append("🔔 Concept extraction injection activated")

                        # Check if we should trigger notes cleanup reminder (Phase 11)
                        notes_reminder_text = ""
                        if self.prompt_builder.should_trigger_notes_cleanup(self.messages_since_notes_check):
                            notes_reminder_text = "\n\n" + self.prompt_builder.generate_notes_cleanup_reminder(self.messages_since_notes_check) + "\n\n"
                            self.messages_since_notes_check = 0  # Reset counter
                            print(f"📝 Notes cleanup reminder triggered ({self.notes_cleanup_interval} messages)", flush=True)
                            self._pending_notifications.append("📝 Notes cleanup reminder injected")

                        # Check if we should prompt for file descriptions (Phase 7)
                        describe_reminder_text = ""
                        if attachment_blocks and self.prompt_builder.should_trigger_describe_check():
                            describe_reminder_text = "\n\n" + self.prompt_builder.generate_describe_reminder() + "\n\n"
                            if describe_reminder_text.strip():
                                print(f"📎 File description reminder triggered", flush=True)

                        # Build cold start prompt with all context sections
                        prompt_parts = []
                        if sections.get("recent"):
                            prompt_parts.append(sections["recent"])
                        if sections.get("notes"):
                            prompt_parts.append(sections["notes"])
                        if sections.get("graph"):
                            prompt_parts.append(sections["graph"])
                        if sections.get("retrieved"):
                            prompt_parts.append(sections["retrieved"])
                        if sections.get("concept"):
                            prompt_parts.append(sections["concept"])
                        if concept_reminder_text:
                            prompt_parts.append(concept_reminder_text)
                        if notes_reminder_text:
                            prompt_parts.append(notes_reminder_text)
                        if sections.get("files"):
                            prompt_parts.append(sections["files"])
                        if describe_reminder_text:
                            prompt_parts.append(describe_reminder_text)
                        if sections.get("entity_summaries"):
                            prompt_parts.append(sections["entity_summaries"])
                        if sections.get("datetime"):
                            prompt_parts.append(sections["datetime"])
                        prompt_parts.append(sections["current"])
                        prompt = "".join(prompt_parts)
                    else:
                        raise ConversationError("Neither prompt nor context+current_input provided")
                else:
                    # Legacy prompt-only path (for backwards compatibility)
                    system_param = None
                    prompt = prompt

                if attachment_blocks:
                    user_content = list(attachment_blocks)
                    user_content.append({"type": "text", "text": prompt})
                    messages = [{"role": "user", "content": user_content}]
                else:
                    messages = [{"role": "user", "content": prompt}]
                extra_headers = {}

                # Print to both stdout (for frontend) and stderr (for console debugging)
                cache_msg = f"💾 Cache: Disabled ({cache_reason})"
                print(cache_msg, flush=True)
                print(cache_msg, file=sys.stderr, flush=True)

            # Build thinking param if enabled
            thinking_param = None
            if self.thinking_enabled:
                thinking_param = {"type": "enabled", "budget_tokens": self.thinking_budget}

            # Check if streaming is requested (Phase 4.3)
            if stream:
                # Return AIClient stream generator - yields {"type": "start/chunk/end", ...}
                return self.ai_client.call_stream(
                    messages=messages,
                    system=system_param if 'system_param' in locals() else None,
                    tools=tools_param if 'tools_param' in locals() and tools_param else None,
                    extra_headers=extra_headers,
                    thinking=thinking_param
                )

            # Non-streaming: Use AIClient which handles text extraction and usage tracking
            ai_text, usage_obj, thinking_text = self.ai_client.call(
                messages=messages,
                system=system_param if 'system_param' in locals() else None,
                tools=tools_param if 'tools_param' in locals() and tools_param else None,
                extra_headers=extra_headers,
                thinking=thinking_param
            )

            # Convert APIUsage object to dict for cache_manager compatibility
            usage = {
                "input_tokens": usage_obj.input_tokens,
                "output_tokens": usage_obj.output_tokens,
                "cache_creation_input_tokens": usage_obj.cache_creation_tokens,
                "cache_read_input_tokens": usage_obj.cache_read_tokens
            }

            # Record message for cache metrics and get summary
            cache_summary = self.cache_manager.record_message(
                cached=use_caching,
                usage=usage,
                model=self.model
            )

            # Print summary to both stdout (for frontend) and stderr (for console)
            if cache_summary:
                print(cache_summary, flush=True)
                print(cache_summary, file=sys.stderr, flush=True)

            # Update timestamp for gap detection
            self.cache_manager.update_message_time()

            # Store thinking text for non-streaming path (Phase 10)
            self._last_thinking_text = thinking_text if thinking_text else ""

            # Cost is tracked by ai_client.stats — no duplicate tracking needed

            return ai_text

        except Exception as e:
            # Convert to user-friendly error (Phase 4.4)
            friendly_error = handle_anthropic_error(e)
            error_msg = get_user_friendly_message(friendly_error)
            raise ConversationError(error_msg) from e

    def get_statistics(self) -> Dict:
        """
        Get conversation statistics.

        Returns:
            dict: Statistics including message counts, costs, and cache performance
        """
        bg_stats = self.background_queue.get_statistics()
        cache_stats = self.cache_manager.get_statistics()

        # Use ai_client's cost tracking (includes cache token pricing)
        stats = dict(self.stats)
        stats["total_cost"] = self.ai_client.stats.get("total_cost", 0.0)

        return {
            "conversation": stats,
            "background_processing": bg_stats,
            "cache_performance": cache_stats,
            "model": self.model,
            "temperature": self.temperature
        }

    def switch_model(self, use_production: bool):
        """
        Switch between testing (Haiku) and production (Sonnet) model.

        Args:
            use_production: True for Sonnet, False for Haiku

        USAGE:
        manager.switch_model(True)  # Switch to Sonnet
        manager.switch_model(False)  # Switch to Haiku
        """
        self.use_testing_model = not use_production

        model_config = self.config.get("model", {})

        if use_production:
            self.model = model_config.get("default", "claude-sonnet-4-6")
        else:
            self.model = model_config.get("testing", "claude-haiku-4-5")

        # Update AIClient model too
        self.ai_client.update_model(self.model)

    def clear_conversation_history(self):
        """
        Clear in-memory conversation history.

        Call this when:
        - Starting new conversation session
        - Topic shifts significantly
        - User explicitly requests

        NOTE: Messages remain in database, just clears in-memory cache.
        """
        self.conversation_history.clear()
        self.context_assembler.clear_loaded_memories()

    def force_process_queue(self):
        """
        Force process tagging queue immediately.

        Call this:
        - Before ending conversation session
        - When user wants up-to-date stats
        - Before important @recall or @review
        """
        return self.background_queue.force_process()


if __name__ == "__main__":
    """
    Test the conversation manager.
    """
    print("Conversation Manager module loaded successfully!")
    print("\nFeatures:")
    print("  ✓ Full conversation loop with memory integration")
    print("  ✓ Token-based context (70k recent + 15k memories)")
    print("  ✓ @command system (all 7 commands)")
    print("  ✓ Background processing (immediate embeddings)")
    print("  ✓ Model switching (Haiku/Sonnet)")
    print("  ✓ Cost tracking")
    print("\nTo use:")
    print("  from conversation import ConversationManager")
    print("  manager = ConversationManager(db, embedder, config)")
    print("  result = manager.process_message('Tell me about the crows')")
