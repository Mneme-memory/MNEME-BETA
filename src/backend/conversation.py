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


from .context import ContextAssembler, DynamicContextBudget
from .background import BackgroundQueue
from .commands import CommandHandler
from .prompt_cache import PromptCacheManager
from .prompt_builder import PromptBuilder
from .tier_manager import TierManager
from .instance_executor import InstanceExecutor
from .ai_client import AIClient, AIClientError, build_thinking_param
from .prompt_budget import (
    build_prompt_budget,
    estimate_request_tokens,
    is_context_length_error,
)
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


CORE_CONTEXT_RESERVE_STANDARD = 12_000
CORE_CONTEXT_RESERVE_EXTENDED = 30_000


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
        # Cache-facing active window. It is trimmed only at explicit refresh
        # points, then grows append-only so Anthropic's prompt-cache prefix stays
        # stable between refreshes.
        self.active_prompt_history = list(self.conversation_history)

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

    def _status(self, id: str, pill: str, summary: str, detail: dict = None, no_log: bool = False) -> dict:
        """Build a structured status notification for the frontend."""
        data = {"id": id, "pill": pill, "summary": summary}
        if detail:
            data["detail"] = detail
        if no_log:
            data["noLog"] = True
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
            self._status("importance_decay", "decay applied", "Fading older memories", no_log=True)
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
                    self._status("backfill_summary", "backfill done", f"Caught up on {generated} missed days")
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

    def _strip_cache_control(self, value):
        """Return a copy of an Anthropic payload with cache_control fields removed."""
        if isinstance(value, dict):
            return {
                key: self._strip_cache_control(item)
                for key, item in value.items()
                if key != "cache_control"
            }
        if isinstance(value, list):
            return [self._strip_cache_control(item) for item in value]
        return value

    def _history_token_count(self, messages: List[Dict]) -> int:
        """Count recent-history tokens using the same formatting as ContextAssembler."""
        total = 0
        for msg in messages:
            total += self.context_assembler.count_tokens(f"{msg.get('sender', '')}: {msg.get('content', '')}")
        return total

    def _get_active_prompt_history(self) -> List[Dict]:
        """Return the anchored prompt-history window, initializing if needed."""
        if not hasattr(self, "active_prompt_history") or self.active_prompt_history is None:
            self.active_prompt_history = list(self.conversation_history)
        return self.active_prompt_history

    def _refresh_active_prompt_window(self, recent_budget: int = None) -> List[Dict]:
        """
        Recompute the anchored prompt-history window at an explicit refresh point.

        Between refreshes, this window grows append-only via _add_to_history().
        """
        budget = int(recent_budget or self.context_assembler.recent_budget)
        window, _tokens = self.context_assembler._get_recent_messages(
            self.conversation_history,
            max(1_000, budget)
        )
        self.active_prompt_history = list(window)
        return self.active_prompt_history

    def _reload_histories_after_tier_transition(
        self,
        exclude_message_ids: List[int] = None,
        recent_budget: int = None
    ) -> List[Dict]:
        """
        Reload prompt histories after TierManager mutates persisted messages.

        Mid-turn callers have already written the current user row and the
        preallocated empty assistant row. Exclude those volatile rows so the
        current input is not duplicated in prompt history.
        """
        excluded_ids = {
            int(msg_id)
            for msg_id in (exclude_message_ids or [])
            if msg_id is not None
        }
        original_budget = self.context_assembler.recent_budget
        if recent_budget is not None:
            self.context_assembler.recent_budget = max(1_000, int(recent_budget))

        try:
            reloaded = self._load_recent_context()
        finally:
            self.context_assembler.recent_budget = original_budget

        filtered = [
            msg for msg in reloaded
            if msg.get("id") not in excluded_ids
            and (msg.get("content") or "").strip()
        ]
        self.conversation_history = filtered
        self.active_prompt_history = list(filtered)
        return self.active_prompt_history

    def _append_history_entry(self, entry: Dict):
        """Append one history entry to both full and active prompt history."""
        self.conversation_history.append(entry)
        self._get_active_prompt_history().append(entry)

    def _remove_from_histories(self, msg_id: int):
        """Remove a message from both history lists."""
        self.conversation_history = [
            msg for msg in self.conversation_history if msg.get("id") != msg_id
        ]
        self.active_prompt_history = [
            msg for msg in self._get_active_prompt_history() if msg.get("id") != msg_id
        ]

    def _assemble_context_for_prompt(
        self,
        user_input: str,
        recent_budget: int = None,
        dynamic_payload_tokens: int = 0,
    ) -> Dict:
        """Assemble turn context from the anchored active prompt-history window."""
        prompt_history = (
            self._refresh_active_prompt_window(recent_budget)
            if recent_budget is not None
            else self._get_active_prompt_history()
        )
        dynamic_budget = self._dynamic_context_budget_for_turn(
            user_input,
            prompt_history,
            dynamic_payload_tokens=dynamic_payload_tokens,
        )
        original_budget = self.context_assembler.recent_budget
        active_tokens = self._history_token_count(prompt_history)
        # Avoid per-turn sliding trims: the active window may drift above the
        # configured refresh target between explicit refreshes. Preflight guards
        # the real model limit.
        self.context_assembler.recent_budget = max(original_budget, active_tokens + 1_000)
        try:
            context = self.context_assembler.assemble_context(
                recent_messages=prompt_history,
                current_query=user_input,
                dynamic_budget=dynamic_budget
            )
        finally:
            self.context_assembler.recent_budget = original_budget

        if self.timeline_enabled:
            timeline_context, timeline_tokens = self.context_assembler.get_timeline_context()
            context["timeline_context"] = timeline_context
            context["token_counts"]["timeline"] = timeline_tokens
            context["token_counts"]["total"] += timeline_tokens

        return context

    def _dynamic_context_budget_for_turn(
        self,
        user_input: str,
        prompt_history: List[Dict],
        dynamic_payload_tokens: int = 0,
    ) -> DynamicContextBudget:
        """
        Compute the volatile per-turn budget for uncached memories/entities.

        This deliberately does not trim or refresh prompt_history. Recent
        history is the cache anchor and only changes at explicit refresh events.
        """
        prompt_budget = self._current_prompt_budget()
        active_tokens = self._history_token_count(prompt_history)
        current_input_tokens = self.context_assembler.count_tokens(user_input or "")

        features = self.config.get("features", {})
        notes_cfg = features.get("notes", {})
        notes_reserve = (
            int(notes_cfg.get("max_tokens", 5000))
            if notes_cfg.get("enabled", True)
            else 0
        )

        timeline_cfg = features.get("timeline", {})
        timeline_reserve = 0
        if timeline_cfg.get("enabled", False):
            days = int(timeline_cfg.get("days_to_show", 7))
            per_day = int(timeline_cfg.get("max_tokens_per_day", 400))
            timeline_reserve = days * per_day + 500

        attachments_cfg = features.get("attachments", {})
        attachment_reserve = (
            int(attachments_cfg.get("max_tokens", 1500))
            if attachments_cfg.get("enabled", False)
            else 0
        )

        core_reserve = (
            CORE_CONTEXT_RESERVE_EXTENDED
            if prompt_budget.supports_1m_context
            else CORE_CONTEXT_RESERVE_STANDARD
        )

        available = (
            prompt_budget.usable_input_tokens
            - active_tokens
            - current_input_tokens
            - max(0, int(dynamic_payload_tokens or 0))
            - notes_reserve
            - timeline_reserve
            - attachment_reserve
            - core_reserve
        )
        return DynamicContextBudget(total_tokens=max(0, int(available)))

    def _attachment_blocks_token_estimate(self, attachment_blocks: list) -> int:
        """Conservative local estimate for non-text continuation blocks."""
        if not attachment_blocks:
            return 0
        return estimate_request_tokens({
            "messages": [{"role": "user", "content": attachment_blocks}]
        })

    def _forced_entity_status_events(self, context: Dict) -> List[Dict]:
        """Surface explicit @entity budget degradation in the user-visible status log."""
        metadata = context.get("metadata", {}) if context else {}
        events = []
        shortened = metadata.get("forced_entities_shortened") or []
        omitted = metadata.get("forced_entities_omitted") or []

        for name in shortened:
            events.append(self._status(
                "entity_summary_shortened",
                "topic shortened",
                f"Summary for {name} was shortened to fit this turn"
            ))
        for name in omitted:
            events.append(self._status(
                "entity_summary_omitted",
                "topic skipped",
                f"Summary for {name} could not fit this turn"
            ))
        return events

    def _prompt_history_for_context(self, context: Dict) -> List[Dict]:
        """
        Return the already-trimmed history for this prompt.

        This is deliberately not the full in-memory conversation history: the
        API sees the same recent window that ContextAssembler budgeted.
        """
        return context.get("recent_context") or []

    def _build_reminder_blocks(self, attachment_blocks: list, consume: bool = True) -> tuple:
        """Build ephemeral reminder blocks without mutating counters unless consumed."""
        concept_reminder = None
        notes_reminder = None
        describe_reminder = None

        if self.prompt_builder.should_trigger_concept_check(self.messages_since_concept_check):
            concept_reminder = self.prompt_builder.generate_concept_reminder(self.messages_since_concept_check)
            if consume:
                self.messages_since_concept_check = 0
                print(f"🔔 Concept extraction reminder triggered ({self.prompt_builder.concept_extract_frequency} messages)", flush=True)
                self._pending_notifications.append(f"Asking {self.instance_name} to note any new concepts")

        if self.prompt_builder.should_trigger_notes_cleanup(self.messages_since_notes_check):
            notes_reminder = self.prompt_builder.generate_notes_cleanup_reminder(self.messages_since_notes_check)
            if consume:
                self.messages_since_notes_check = 0
                print(f"📝 Notes cleanup reminder triggered ({self.notes_cleanup_interval} messages)", flush=True)
                self._pending_notifications.append(f"Reminding {self.instance_name} to tidy notes")

        if attachment_blocks and self.prompt_builder.should_trigger_describe_check():
            describe_reminder = self.prompt_builder.generate_describe_reminder()
            if consume and describe_reminder:
                print("📎 File description reminder triggered", flush=True)

        combined_reminder = concept_reminder or ""
        if notes_reminder:
            combined_reminder = (combined_reminder + "\n\n" + notes_reminder).strip() if combined_reminder else notes_reminder

        return combined_reminder or None, describe_reminder

    def _prepare_ai_request(
        self,
        prompt: str = None,
        context: Dict = None,
        current_input: str = None,
        attachment_blocks: list = None,
        consume_reminders: bool = True,
    ) -> Dict:
        """
        Build the exact Anthropic request pieces used for token counting and send.

        Side effects from periodic reminders are opt-in so preflight counting can
        inspect the payload without resetting reminder counters or emitting status.
        """
        attachment_blocks = attachment_blocks or []
        use_caching, cache_reason = self.cache_manager.should_use_caching()
        tools_param = []
        extra_headers = {}

        if prompt is None:
            if context is None or current_input is None:
                raise ConversationError("Neither prompt nor context+current_input provided")

            sections = self.prompt_builder.build_sections(context, current_input)
            concept_reminder, describe_reminder = self._build_reminder_blocks(
                attachment_blocks,
                consume=consume_reminders
            )
            prompt_history = self._prompt_history_for_context(context)
            history_attachments = self._load_history_attachment_blocks(prompt_history)

            structure = self.prompt_builder.build_cached_structure(
                sections=sections,
                conversation_history=prompt_history,
                current_input=current_input,
                concept_reminder=concept_reminder,
                attachment_blocks=attachment_blocks,
                describe_reminder=describe_reminder,
                history_attachments=history_attachments
            )

            tools_param = structure["tools"]
            if use_caching:
                system_param = structure["system"]
                messages = structure["messages"]
                extra_headers = self.cache_manager.get_api_headers()
            else:
                system_param = self._strip_cache_control(structure["system"])
                messages = self._strip_cache_control(structure["messages"])
                messages = self._merge_initial_assistant_context_into_user(messages)
        else:
            system_param = None
            messages = [{"role": "user", "content": prompt}]
            use_caching = False
            cache_reason = "legacy_prompt"

        thinking_param = build_thinking_param(
            self.model,
            self.thinking_enabled,
            self.thinking_budget
        )

        return {
            "messages": messages,
            "system": system_param,
            "tools": tools_param,
            "extra_headers": extra_headers,
            "thinking": thinking_param,
            "use_caching": use_caching,
            "cache_reason": cache_reason,
        }

    def _current_prompt_budget(self):
        """Current model-aware prompt budget for this manager."""
        return build_prompt_budget(
            self.model,
            self.max_tokens,
            self.thinking_enabled,
            self.thinking_budget,
        )

    def _measure_prompt_request(self, prepared: Dict, budget) -> Dict:
        """Estimate, and near the limit exactly count, an Anthropic request."""
        request_for_estimate = {
            "system": prepared.get("system"),
            "messages": prepared.get("messages"),
            "tools": prepared.get("tools"),
            "thinking": prepared.get("thinking"),
        }
        estimate = estimate_request_tokens(request_for_estimate)
        exact = None
        used_exact = False

        if estimate >= budget.exact_count_at_tokens:
            try:
                exact = self.ai_client.count_tokens(
                    messages=prepared["messages"],
                    system=prepared.get("system"),
                    tools=prepared.get("tools"),
                    thinking=prepared.get("thinking"),
                )
                used_exact = True
            except Exception as e:
                print(f"⚠️ Exact token count failed, using estimate: {e}", file=sys.stderr, flush=True)

        return {
            "estimated_tokens": estimate,
            "exact_tokens": exact,
            "used_exact_count": used_exact,
            "input_tokens": exact if exact is not None else estimate,
        }

    def _recent_trim_target(self, context: Dict, measured_tokens: int, budget) -> int:
        """Choose a lower recent-message budget after a prompt-size overage."""
        target_input = int(budget.usable_input_tokens * 0.78)
        recent_tokens = int(context.get("token_counts", {}).get("recent", 0) or 0)
        if recent_tokens <= 0:
            return 10_000

        over_target = max(0, measured_tokens - target_input)
        target_recent = recent_tokens - over_target
        if target_recent >= recent_tokens:
            target_recent = int(recent_tokens * 0.72)

        return max(10_000, min(target_recent, recent_tokens))

    def _copy_prompt_context_ids(self, source: Dict, target: Dict):
        """Preserve in-flight DB IDs across prompt-context rebuilds."""
        for key in ("user_msg_id", "ai_msg_id"):
            if key in source:
                target[key] = source[key]

    def _replace_prompt_context(self, context: Dict, replacement: Dict) -> Dict:
        """Mutate an existing context dict so continuation callers keep sharing it."""
        context.clear()
        context.update(replacement)
        return context

    def _truncate_current_input_for_budget(
        self,
        context: Dict,
        current_input: str,
        attachment_blocks: list,
        budget,
        measurement: Dict,
    ) -> tuple:
        """
        Trim an oversized continuation payload after normal context trimming.

        This is intentionally a last resort for huge command/file/run output.
        The marker stays inside the prompt so the AI knows information was
        omitted instead of silently hallucinating over a cut result.
        """
        if not current_input:
            return current_input, measurement, []

        status_events = []
        original_chars = len(current_input)
        marker = (
            "\n\n[Mneme truncated this command result because it was too large "
            "for the model context. Use the visible beginning/end and ask for a "
            "narrower follow-up if needed.]\n\n"
        )
        excess_tokens = max(0, measurement["input_tokens"] - budget.usable_input_tokens)
        max_chars = max(300, original_chars - ((excess_tokens + 5_000) * 4))

        def truncate_to(char_limit: int) -> str:
            if original_chars <= char_limit:
                return current_input
            available = max(80, char_limit - len(marker))
            head_chars = max(40, int(available * 0.72))
            tail_chars = max(0, available - head_chars)
            if tail_chars <= 0:
                return current_input[:available] + marker
            return current_input[:head_chars] + marker + current_input[-tail_chars:]

        truncated_input = current_input
        truncated_measurement = measurement
        for _attempt in range(6):
            truncated_input = truncate_to(max_chars)
            prepared = self._prepare_ai_request(
                context=context,
                current_input=truncated_input,
                attachment_blocks=attachment_blocks,
                consume_reminders=False,
            )
            truncated_measurement = self._measure_prompt_request(prepared, budget)
            if truncated_measurement["input_tokens"] <= budget.usable_input_tokens:
                break
            max_chars = max(200, int(max_chars * 0.55))

        if truncated_input != current_input:
            status_events.append(self._status(
                "context_result_truncated",
                "trimmed result",
                "A command result was too large, so Mneme kept the useful edges",
                detail=self._format_prompt_budget_detail(truncated_measurement, budget)
            ))

        return truncated_input, truncated_measurement, status_events

    def _preflight_prompt_request(
        self,
        context: Dict,
        current_input: str,
        attachment_blocks: list = None,
        exclude_message_ids: List[int] = None,
        context_query: str = None,
        allow_input_truncation: bool = False,
    ) -> tuple:
        """
        Run model-aware prompt preflight for initial sends and continuations.

        The measured request is built by _prepare_ai_request(), matching the
        exact structured payload shape that _call_ai() will send. This method
        only refreshes the anchored prompt history at explicit over-budget trim
        points, preserving cache-prefix stability during normal continuations.
        """
        attachment_blocks = attachment_blocks or []
        exclude_message_ids = exclude_message_ids or []
        status_events = []
        budget = self._current_prompt_budget()

        if allow_input_truncation:
            rebuilt_context = self._assemble_context_for_prompt(
                context_query if context_query is not None else current_input,
                dynamic_payload_tokens=self._attachment_blocks_token_estimate(attachment_blocks),
            )
            self._copy_prompt_context_ids(context, rebuilt_context)
            self._replace_prompt_context(context, rebuilt_context)
            status_events.extend(self._forced_entity_status_events(context))

        prepared = self._prepare_ai_request(
            context=context,
            current_input=current_input,
            attachment_blocks=attachment_blocks,
            consume_reminders=False,
        )
        measurement = self._measure_prompt_request(prepared, budget)

        if measurement["input_tokens"] >= budget.warning_at_tokens and measurement["input_tokens"] <= budget.usable_input_tokens:
            status_events.append(self._status(
                "context_warning",
                "nearly full",
                "This conversation is close to the model's context limit",
                detail=self._format_prompt_budget_detail(measurement, budget)
            ))

        if measurement["input_tokens"] > budget.usable_input_tokens:
            status_events.append(self._status(
                "cache_overflow",
                "trimming",
                "Refreshing context so this message fits",
                detail=self._format_prompt_budget_detail(measurement, budget)
            ))
            self.tier_manager.transition_tiers(background_summaries=True)

            target_recent_budget = self._recent_trim_target(context, measurement["input_tokens"], budget)
            self._reload_histories_after_tier_transition(
                exclude_message_ids=exclude_message_ids,
                recent_budget=target_recent_budget
            )
            rebuilt_context = self._assemble_context_for_prompt(
                context_query if context_query is not None else current_input,
                recent_budget=target_recent_budget,
                dynamic_payload_tokens=self._attachment_blocks_token_estimate(attachment_blocks),
            )
            self._copy_prompt_context_ids(context, rebuilt_context)
            self._replace_prompt_context(context, rebuilt_context)

            prepared = self._prepare_ai_request(
                context=context,
                current_input=current_input,
                attachment_blocks=attachment_blocks,
                consume_reminders=False,
            )
            measurement = self._measure_prompt_request(prepared, budget)
            status_events.append(self._status(
                "context_trimmed",
                "trimmed",
                f"Using {context['token_counts'].get('recent', 0):,} tokens of recent conversation",
                detail=self._format_prompt_budget_detail(measurement, budget)
            ))

        if allow_input_truncation and measurement["input_tokens"] > budget.usable_input_tokens:
            current_input, measurement, truncation_events = self._truncate_current_input_for_budget(
                context,
                current_input,
                attachment_blocks,
                budget,
                measurement,
            )
            status_events.extend(truncation_events)

        return context, current_input, measurement, budget, status_events

    def _retry_prompt_after_context_length_error(
        self,
        context: Dict,
        current_input: str,
        attachment_blocks: list = None,
        exclude_message_ids: List[int] = None,
        context_query: str = None,
        allow_input_truncation: bool = False,
    ) -> tuple:
        """Refresh harder after a model context-length rejection."""
        attachment_blocks = attachment_blocks or []
        status_events = [
            self._status(
                "context_retry",
                "retrying",
                "The model still said the prompt was too long, so Mneme is trimming harder"
            )
        ]
        retry_recent_budget = max(
            10_000,
            int(context.get("token_counts", {}).get("recent", 0) * 0.55)
        )
        self.tier_manager.transition_tiers(background_summaries=True)
        self._reload_histories_after_tier_transition(
            exclude_message_ids=exclude_message_ids or [],
            recent_budget=retry_recent_budget
        )
        rebuilt_context = self._assemble_context_for_prompt(
            context_query if context_query is not None else current_input,
            recent_budget=retry_recent_budget,
            dynamic_payload_tokens=self._attachment_blocks_token_estimate(attachment_blocks),
        )
        self._copy_prompt_context_ids(context, rebuilt_context)
        self._replace_prompt_context(context, rebuilt_context)

        context, current_input, _measurement, _budget, preflight_events = self._preflight_prompt_request(
            context=context,
            current_input=current_input,
            attachment_blocks=attachment_blocks,
            exclude_message_ids=exclude_message_ids,
            context_query=context_query,
            allow_input_truncation=allow_input_truncation,
        )
        status_events.extend(preflight_events)
        return context, current_input, status_events

    def _format_prompt_budget_detail(self, measurement: Dict, budget) -> Dict:
        """Human-readable prompt budget detail for status popovers."""
        count_kind = "exact" if measurement.get("used_exact_count") else "estimated"
        content = (
            f"input ({count_kind}): {measurement['input_tokens']:,}\n"
            f"usable input budget: {budget.usable_input_tokens:,}\n"
            f"context window: {budget.context_window_tokens:,}\n"
            f"reserved for reply: {budget.response_reserve_tokens:,}\n"
            f"reserved for thinking: {budget.thinking_reserve_tokens:,}\n"
            f"safety margin: {budget.safety_margin_tokens:,}"
        )
        return {
            "explanation": "Mneme checks the full request before sending, including history, memories, notes, files, and reply room.",
            "items": [{"label": "prompt budget", "content": content}]
        }

    def _merge_initial_assistant_context_into_user(self, messages: list) -> list:
        """
        Anthropic conversations should start with a user turn.

        Cached calls only reach structured mode after history exists, but cold
        starts can have dynamic context without prior turns. In that case,
        fold the synthetic assistant working-memory block into the first user
        turn as text context while preserving image/content blocks.
        """
        if not messages or messages[0].get("role") != "assistant":
            return messages

        if len(messages) < 2 or messages[1].get("role") != "user":
            return messages

        assistant_content = messages[0].get("content", [])
        if isinstance(assistant_content, str):
            context_text = assistant_content
        else:
            context_parts = [
                block.get("text", "")
                for block in assistant_content
                if isinstance(block, dict) and block.get("type") == "text" and block.get("text")
            ]
            context_text = "\n\n".join(context_parts)

        if not context_text:
            return messages[1:]

        user_message = dict(messages[1])
        user_content = user_message.get("content", [])
        if isinstance(user_content, str):
            user_content = [{"type": "text", "text": user_content}]
        else:
            user_content = list(user_content)

        context_block = {
            "type": "text",
            "text": f"=== CONTEXT ===\n{context_text}\n=== END CONTEXT ==="
        }
        user_message["content"] = [context_block] + user_content

        return [user_message] + messages[2:]

    def _get_utc_timestamp(self) -> str:
        """Get consistent UTC timestamp for conversation history."""
        return datetime.now(timezone.utc).replace(microsecond=0).strftime('%Y-%m-%dT%H:%M:%S') + 'Z'

    def _add_to_history(self, msg_id: int, sender: str, content: str, attachment_uuids: list = None):
        """Add message to conversation history with consistent timestamp."""
        self._append_history_entry({
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
            self.active_prompt_history = list(self.conversation_history)
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
            yield self._status("cold_start", "cold start", "First message after a break — tidying up")
            changes = self.tier_manager.transition_tiers(background_summaries=True)
            self.conversation_history = self._load_recent_context()
            self.active_prompt_history = list(self.conversation_history)
            yield self._status("history_loaded", "history loaded", f"Picked up where you left off ({len(self.conversation_history)} messages)")

            # Notify about background tasks kicked off by tier transition
            transitioned = changes.get("transitioned_to_standard", 0)
            if transitioned > 0 and self.tier_manager.summaries_enabled:
                yield self._status("entity_summaries_updating", "summaries updating", f"Updating memories for {transitioned} older messages")

        # Check for @command
        if self.command_handler.is_command(user_input):
            # Query commands typed by the user get AI commentary: the raw
            # result surfaces in the status log (glass), and the AI responds
            # with the substance plus its own take (Phase D).
            if sender == "user" and self._command_wants_commentary(user_input):
                yield from self._process_command_with_commentary(user_input, sender)
                return
            # Action/system commands stay instant (no streaming, no AI call)
            result = self._process_command(user_input, sender)
            # Yield the response text as a chunk so it displays in the frontend
            if result.get("response"):
                yield {"type": "chunk", "data": result["response"]}
            yield {"type": "done", "data": result}
            return

        # Stream normal conversation
        yield from self._process_conversation_stream(user_input, sender, attachment_uuids)

    def _format_command_response_text(self, result: Dict) -> str:
        """Format a command handler result into display text (shared by the
        instant command path and the AI-commentary path)."""
        if not result["success"]:
            return f"✗ {result['message']}"

        response_text = f"✓ {result['message']}"
        if "data" in result and result["data"]:
            data = result["data"]
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
        return response_text

    def _command_wants_commentary(self, user_input: str) -> bool:
        """
        Should this user-typed command get an AI commentary response?

        Query commands (read-only questions to the memory system) do — the AI
        relays the substance and adds its take. Action commands (@remember,
        @forget, @config, @concept create, ...) stay instant: their results
        are confirmations, not material for commentary.
        """
        # Only the first line must be a query command — any further lines are
        # the user's accompanying message, handled by the commentary path
        first_line = user_input.strip().splitlines()[0].strip()
        parts = first_line[1:].split(None, 2)
        if not parts:
            return False
        cmd = parts[0].lower()
        sub = parts[1].lower() if len(parts) > 1 else ""
        if cmd in ("recall", "review"):
            return True
        if cmd == "entity" and sub in ("list", "view"):
            return True
        if cmd == "concept" and sub in ("list", "view"):
            return True
        if cmd == "file" and sub in ("list", "search"):
            return True
        return False

    def _process_command_with_commentary(self, command_input: str, sender: str):
        """
        User-typed query command → AI commentary (Phase D).

        The command runs first; its raw output surfaces in the status log
        (the glass — machine speech, tap to expand). Then the turn proceeds
        as a normal conversation turn, with the result injected into the
        UNCACHED dynamic input section — the same cache-safe channel
        continuations use. Only the command (user message) and the AI's
        commentary (assistant message) persist; the raw dump lives nowhere
        and is regenerable by rerunning the command.
        """
        # First line is the command; any remaining lines are the user's own
        # message riding along with it ("@entity view River\nhow is she doing?")
        lines = command_input.strip().splitlines()
        command_line = lines[0].strip()
        user_prose = "\n".join(lines[1:]).strip()

        try:
            result = self.command_handler.handle_command(command_line, marked_by=sender)
        except Exception as e:
            yield {"type": "error", "data": f"Command failed: {str(e)}"}
            return

        formatted = self._format_command_response_text(result)

        if not result.get("success"):
            # Errors are instant — nothing worth commentary. Persist the
            # exchange the same way _process_command does (temporary rows),
            # or it exists only in SSE events and vanishes on reload.
            for msg_sender, content, meta in (
                (sender, command_input, {"temporary": True, "is_command": True}),
                ("system", formatted, {"temporary": True, "command_type": result.get("command", "unknown")}),
            ):
                msg_id = self.db.add_message(
                    sender=msg_sender, content=content,
                    importance_score=3.0, metadata=meta,
                )
                self._append_history_entry({
                    "id": msg_id, "sender": msg_sender, "content": content,
                    "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
                    "temporary": True,
                })
                self.temporary_message_ids.append(msg_id)

            yield {"type": "chunk", "data": formatted}
            yield {"type": "done", "data": {
                "response": formatted, "is_command": True,
                "command_result": result, "context_info": {}, "processing_info": {}
            }}
            return

        self.stats["commands_executed"] += 1
        yield self._status(
            "command_result", "command result",
            f"{command_line[:60]} — done",
            detail={
                "explanation": "Raw command output. The reply below is "
                               f"{self.instance_name}'s reading of this result.",
                "items": [{"label": "result", "content": formatted}],
            },
        )

        turn_user_name = self.config.get("identity", {}).get("user_name", "") or "your human"
        prose_note = (
            f" {turn_user_name} also wrote a message alongside the command — answer it using the result."
            if user_prose else ""
        )
        injected = (
            f"\n\n[SYSTEM NOTE: {turn_user_name} ran this command themselves. The raw result is below. "
            "They can expand it in the status log, but it is not part of the conversation — "
            "so weave the key substance into your reply naturally, then add your own thoughts, "
            f"connections, or observations.{prose_note} "
            "Do not use @commands in this reply unless genuinely needed.]\n\n"
            f"{formatted}"
        )
        yield from self._process_conversation_stream(command_input, sender, injected_context=injected)

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
        self._append_history_entry({
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
            response_text = self._format_command_response_text(result)

            # Store command result as assistant message
            result_msg_id = self.db.add_message(
                sender="system",
                content=response_text,
                importance_score=3.0,
                metadata={"temporary": True, "command_type": result["command"]}
            )

            # Add to conversation history with temporary flag
            # This flag will be checked when building cache structure
            self._append_history_entry({
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
    
            self._append_history_entry({
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

    def _process_conversation_stream(self, user_input: str, sender: str, attachment_uuids: list = None, injected_context: str = None):
        """
        Process normal conversation message with streaming (Phase 4.3).

        Args:
            user_input: User's message
            sender: Who sent it
            attachment_uuids: List of attachment UUIDs to include in AI request (Phase 7)
            injected_context: Optional block appended to the API-bound input only
                (Phase D command commentary). Storage, embedding, and retrieval
                all use the raw user_input; the injected block rides the uncached
                dynamic section exactly like continuation results, so the prompt
                cache and stored history stay consistent.

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
                self._append_history_entry({
                    "id": msg["id"],
                    "sender": msg["sender"],
                    "content": msg["content"],
                    "timestamp": msg["timestamp"],
                    "attachment_uuids": [a["uuid"] for a in attachments] if attachments else []
                })

        # Phase 9: Check for day rollover (generates yesterday's summary if needed)
        if self._check_day_rollover():
            yield self._status("day_rollover", "new day", "New day — summarizing yesterday")

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
        yield self._status("processing", "one sec", "one sec", no_log=True)
        processing_info = self.background_queue.add_message(
            user_msg_id,
            user_input,
            sender
        )

        # Notify embedding status
        if processing_info.get("embedding_generated"):
            yield self._status("embedding", "searching", "searching", no_log=True)
        elif len(user_input) > 15000:
            yield self._status("embedding_skipped", "too large", f"Message too long to search ({len(user_input)} chars)")

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
                    "new_entities", "new topics", f"Starting to track {names}",
                    detail={
                        "explanation": f"New topics {self.instance_name} noticed in your message. They'll build up context about these over time.",
                        "items": detail_items
                    }
                )
            links = entity_details.get("links_created", 0)
            msgs = entity_details.get("messages_processed", 0)
            if links > 0:
                yield self._status("entity_links", "memory updated", f"Connected {msgs} {'message' if msgs == 1 else 'messages'} to topics")

        # Step 3: Assemble context
        yield self._status("context_assembly", "loading", "pulling things together", no_log=True)

        # Check if query is too large for semantic search
        if len(user_input) > 15000:
            yield self._status("semantic_skip", "search skipped", f"Message too long for memory search ({len(user_input)} chars)")

        context = self._assemble_context_for_prompt(user_input)
        context["user_msg_id"] = user_msg_id

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
                summary = f"Found memories about {desc_str}"
            else:
                summary = f"Found {memories_count} {'memory' if memories_count == 1 else 'memories'}"

            summary += dupe_note

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
                "memories_found", f"{memories_count} {'memory' if memories_count == 1 else 'memories'}", summary,
                detail={
                    "explanation": f"Past messages {self.instance_name} found relevant to what you just said. They search your history by meaning and remember things that connect even if you didn't use the same words.",
                    "items": detail_items
                }
            )
        else:
            yield self._status("no_memories", "nothing", "no memories came up")

        if tc.get("entity_summaries", 0) > 0:
            bootstrapped = md.get("entities_bootstrapped", [])
            for name in bootstrapped:
                yield self._status("entity_bootstrapped", "new topic", f"Getting to know {name}")

            # Get entity names from metadata
            entity_names = md.get("entity_names_loaded", [])
            if entity_names:
                if len(entity_names) == 1:
                    names_str = entity_names[0]
                elif len(entity_names) == 2:
                    names_str = f"{entity_names[0]} and {entity_names[1]}"
                else:
                    names_str = ", ".join(entity_names[:-1]) + f", and {entity_names[-1]}"
                summary = f"Remembered your history with {names_str}"
            else:
                summary = "Loaded context"

            entity_detail = md.get("entity_summaries_detail", [])
            detail_items = [
                {"label": e["name"], "content": e["summary"]}
                for e in entity_detail
            ] if entity_detail else [{"label": name, "content": name} for name in entity_names]

            yield self._status(
                "entity_summaries", "people & topics", summary,
                detail={
                    "explanation": f"Ongoing summaries {self.instance_name} keeps about the people and topics that come up most in your life. They update over time as you talk about them more.",
                    "items": detail_items
                }
            )

        for event in self._forced_entity_status_events(context):
            yield event

        if tc.get("notes", 0) > 0:
            notes_text = context.get("notes_context", "")
            yield self._status(
                "notes_loaded", "notes", "Checked notes",
                detail={
                    "explanation": f"Things {self.instance_name} writes and keeps updated themself. Observations about you they want to hold onto over time.",
                    "items": [{"label": "notes", "content": notes_text}] if notes_text else []
                }
            )
            if context.get("notes_cleanup_needed"):
                yield self._status("notes_warning", "notes full", f"Notes almost full — {self.instance_name} may tidy up this turn")

        if tc.get("concepts", 0) > 0:
            concept_matches = context.get("metadata", {}).get("concept_matches", [])
            concept_names = context.get("metadata", {}).get("concept_names", [])
            concept_summary = f"Reminds {self.instance_name} of {', '.join(n.replace('_', ' ') for n in concept_names)}" if concept_names else "Recognized something familiar"

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
                "concepts_loaded", "concepts", concept_summary,
                detail={
                    "explanation": f"Concepts that {self.instance_name} remembered because certain words in your message matched them. They give them a richer understanding of specific themes that come up often in your conversations.",
                    "items": concept_items
                }
            )

        if tc.get("files", 0) > 0:
            files_text = context.get("files_context", "")
            _file_count = len(attachment_uuids) if attachment_uuids else 1
            yield self._status(
                "files_loaded", "attachments", f"Looking at {_file_count} attached {'file' if _file_count == 1 else 'files'}",
                detail={
                    "explanation": f"Files you shared in this conversation. {self.instance_name} can see their content directly.",
                    "items": [{"label": "file context", "content": files_text}] if files_text else []
                }
            )

        if tc.get("timeline", 0) > 0:
            timeline_text = context.get("timeline_context", "")
            yield self._status(
                "timeline_loaded", "timeline", "Checked your recent week",
                detail={
                    "explanation": f"A brief summary of your recent week, one paragraph per day. Gives {self.instance_name} a sense of what's been going on in your life even when it hasn't come up today.",
                    "items": [{"label": "timeline", "content": timeline_text}] if timeline_text else []
                }
            )

        dynamic_total = tc['total'] - tc.get('recent', 0)
        yield self._status(
            "token_budget", "ready", "ready",
            no_log=True,
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

        # Step 3.5: Load attachment content blocks (Phase 7)
        attachment_blocks = self._load_attachment_blocks(attachment_uuids)
        if attachment_blocks:
            _att_count = len(attachment_uuids)
            yield self._status("attachments", "attachments", f"Loaded {_att_count} {'file' if _att_count == 1 else 'files'}")

        # Phase D: append the command-result block for the API only — everything
        # above (DB storage, embedding, retrieval query) already used the raw
        # input, and raw_user_input keeps history/context-query raw below
        raw_user_input = user_input
        if injected_context:
            user_input = user_input + injected_context

        ai_msg_id = None
        try:
            # Pre-allocate AI message ID before the API call so the AI sees its own ID in context
            ai_msg_id = self.db.add_message(sender="assistant", content="", importance_score=3.0)
            context["ai_msg_id"] = ai_msg_id

            context, user_input, _measurement, _budget, preflight_events = self._preflight_prompt_request(
                context=context,
                current_input=user_input,
                attachment_blocks=attachment_blocks,
                exclude_message_ids=[user_msg_id, ai_msg_id],
                context_query=raw_user_input,
            )
            for event in preflight_events:
                yield event
        except Exception as e:
            self._pending_notifications.clear()
            if ai_msg_id is not None:
                self.db.delete_message(ai_msg_id)
            self.db.delete_message(user_msg_id)
            yield {"type": "error", "data": f"Error calling AI: {str(e)}"}
            return

        # Step 4: Call AI model with streaming
        yield self._status(
            "calling_api", "sending", "sending",
            no_log=True,
            detail={"explanation": f"When you send messages less than an hour apart, the whole conversation stays in {self.instance_name}'s mind — they don't need to re-read it from scratch. The longer you talk, the more it saves."}
        )

        full_response = ""
        accumulated_thinking = ""
        usage_data = None

        try:
            # Call AI with stream=True - returns AIClient stream generator
            stream = self._call_ai(context=context, current_input=user_input, stream=True, attachment_blocks=attachment_blocks)

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
                    pill = "all set"
                    summary = "Conversation still warm"
                elif cache_write > 0:
                    pill = "cache written"
                    summary = "Cache updated — next message will be faster"
                else:
                    pill = "no cache"
                    summary = "Sent without cache"

                yield self._status(
                    "cache_result", pill, summary,
                    detail={
                        "explanation": f"When you send messages less than an hour apart, the whole conversation stays in {self.instance_name}'s mind — they don't need to re-read it from scratch. The longer you talk, the more it saves.",
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
            if is_context_length_error(e) and not full_response:
                try:
                    context, user_input, retry_events = self._retry_prompt_after_context_length_error(
                        context=context,
                        current_input=user_input,
                        attachment_blocks=attachment_blocks,
                        exclude_message_ids=[user_msg_id, ai_msg_id],
                        context_query=raw_user_input,
                    )
                    for event in retry_events:
                        yield event

                    stream = self._call_ai(context=context, current_input=user_input, stream=True, attachment_blocks=attachment_blocks)
                    for event in stream:
                        if event["type"] == "start":
                            pass
                        elif event["type"] == "thinking_start":
                            if self.show_thinking:
                                yield {"type": "thinking_start", "data": None}
                        elif event["type"] == "thinking":
                            accumulated_thinking += event["data"]
                            if self.show_thinking:
                                yield {"type": "thinking", "data": event["data"]}
                        elif event["type"] == "chunk":
                            chunk = event["data"]
                            full_response += chunk
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
                            if not accumulated_thinking and end_data.get("thinking"):
                                accumulated_thinking = end_data["thinking"]

                    ai_response = full_response
                    self.cache_manager.update_message_time()

                    if usage_data:
                        use_caching = usage_data["cache_creation_input_tokens"] > 0 or usage_data["cache_read_input_tokens"] > 0
                        self.cache_manager.record_message(
                            cached=use_caching,
                            usage=usage_data,
                            model=self.model
                        )
                        dynamic = usage_data["input_tokens"]
                        cache_read = usage_data["cache_read_input_tokens"]
                        cache_write = usage_data["cache_creation_input_tokens"]
                        total = dynamic + cache_read + cache_write
                        self.last_total_prompt_tokens = total
                        yield self._status(
                            "cache_result", "sent", "Sent after refreshing context",
                            detail={
                                "explanation": f"{self.instance_name} got a smaller active window for this turn so the message could go through.",
                                "items": [{"label": "token breakdown", "content": (
                                    f"dynamic (new): {dynamic:,}\n"
                                    f"cached (read): {cache_read:,}\n"
                                    f"cached (written): {cache_write:,}\n"
                                    f"total: {total:,}"
                                )}]
                            }
                        )

                    for notif in self._pending_notifications:
                        yield {"type": "notification", "data": notif}
                    self._pending_notifications.clear()

                except Exception as retry_error:
                    self._pending_notifications.clear()
                    self.db.delete_message(ai_msg_id)
                    self.db.delete_message(user_msg_id)
                    yield {"type": "error", "data": f"Error calling AI: {str(retry_error)}"}
                    return
            else:
                self._pending_notifications.clear()
                self.db.delete_message(ai_msg_id)
                self.db.delete_message(user_msg_id)
                yield {"type": "error", "data": f"Error calling AI: {str(e)}"}
                return

        # Step 5: Add user message to conversation history (with attachments)
        # NOTE: Only save user input, NOT retrieved memories (prevents cache growth)
        self._add_to_history(user_msg_id, sender, raw_user_input, attachment_uuids)

        # Step 5.5: Save initial AI response to the pre-allocated message record
        initial_response = ai_response
        self.db.update_message_content(ai_msg_id, ai_response)

        # Step 5.55: Save thinking to metadata if present (Phase 10)
        if accumulated_thinking:
            self.db.update_message_metadata(ai_msg_id, {"thinking": accumulated_thinking}, merge=True)

        # Step 5.6: Check for instance commands with streaming notifications
        def ai_caller(ctx, current_input, stream):
            blocks = ctx.pop("_continuation_content_blocks", None)
            exclude_ids = [
                msg_id for msg_id in (ctx.get("user_msg_id"), ctx.get("ai_msg_id"))
                if msg_id is not None
            ]
            ctx, current_input, _measurement, _budget, preflight_events = self._preflight_prompt_request(
                context=ctx,
                current_input=current_input,
                attachment_blocks=blocks,
                exclude_message_ids=exclude_ids,
                context_query=current_input,
                allow_input_truncation=True,
            )

            if not stream:
                try:
                    return self._call_ai(
                        context=ctx,
                        current_input=current_input,
                        stream=False,
                        attachment_blocks=blocks
                    )
                except Exception as e:
                    if not is_context_length_error(e):
                        raise
                    ctx, current_input, _retry_events = self._retry_prompt_after_context_length_error(
                        context=ctx,
                        current_input=current_input,
                        attachment_blocks=blocks,
                        exclude_message_ids=exclude_ids,
                        context_query=current_input,
                        allow_input_truncation=True,
                    )
                    return self._call_ai(
                        context=ctx,
                        current_input=current_input,
                        stream=False,
                        attachment_blocks=blocks
                    )

            def _stream_with_preflight():
                for event in preflight_events:
                    yield event

                emitted_text = False
                try:
                    for event in self._call_ai(
                        context=ctx,
                        current_input=current_input,
                        stream=True,
                        attachment_blocks=blocks
                    ):
                        if event.get("type") in ("chunk", "thinking"):
                            emitted_text = True
                        yield event
                except Exception as e:
                    if not is_context_length_error(e) or emitted_text:
                        raise
                    retry_ctx, retry_input, retry_events = self._retry_prompt_after_context_length_error(
                        context=ctx,
                        current_input=current_input,
                        attachment_blocks=blocks,
                        exclude_message_ids=exclude_ids,
                        context_query=current_input,
                        allow_input_truncation=True,
                    )
                    for event in retry_events:
                        yield event
                    for event in self._call_ai(
                        context=retry_ctx,
                        current_input=retry_input,
                        stream=True,
                        attachment_blocks=blocks
                    ):
                        yield event

            return _stream_with_preflight()

        ai_response, _ = yield from self.instance_executor.execute_loop_stream(
            ai_response, context, ai_caller
        )

        # Step 5.7: Strip @run code blocks from stored response (save tokens in cache)
        # The AI already has the output via continuation; the source code is dead weight.
        ai_response = re.sub(
            r'^@run\s*\n[\s\S]*?^@endrun\s*$',
            '[looked it up]',
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
        yield self._status("finalizing", "saving", "saving", no_log=True)
        ai_processing_info = self._finalize_response(ai_response, ai_msg_id, context)

        # Notify finalization results
        if ai_processing_info.get("entity_batch_processed"):
            bg_stats = self.background_queue.get_statistics()
            yield self._status("entity_batch", "memory updated", f"Updated memory ({bg_stats['entity_links_created']} new connections)")

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
        yield self._status("continuing", "continuing", "Continuing where they left off")
        context = self._assemble_context_for_prompt(partial_clean)

        try:
            context, continuation_prompt, _measurement, _budget, preflight_events = self._preflight_prompt_request(
                context=context,
                current_input=continuation_prompt,
                exclude_message_ids=[interrupted_message_id],
                context_query=continuation_prompt,
                allow_input_truncation=True,
            )
            for event in preflight_events:
                yield event
        except Exception as e:
            self._pending_notifications.clear()
            yield {"type": "error", "data": f"Error continuing response: {str(e)}"}
            return

        yield self._status(
            "calling_api", "sending", "sending",
            no_log=True,
            detail={"explanation": f"When you send messages less than an hour apart, the whole conversation stays in {self.instance_name}'s mind — they don't need to re-read it from scratch. The longer you talk, the more it saves."}
        )

        try:
            continuation_text = ""
            usage_data = None

            stream = self._call_ai(context=context, current_input=continuation_prompt, stream=True)

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
                    pill = "all set"
                    summary = "Conversation still warm"
                elif cache_write > 0:
                    pill = "cache written"
                    summary = "Cache updated — next message will be faster"
                else:
                    pill = "no cache"
                    summary = "Sent without cache"

                yield self._status(
                    "cache_result", pill, summary,
                    detail={
                        "explanation": f"When you send messages less than an hour apart, the whole conversation stays in {self.instance_name}'s mind — they don't need to re-read it from scratch. The longer you talk, the more it saves.",
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
            if is_context_length_error(e) and not continuation_text:
                try:
                    context, continuation_prompt, retry_events = self._retry_prompt_after_context_length_error(
                        context=context,
                        current_input=continuation_prompt,
                        exclude_message_ids=[interrupted_message_id],
                        context_query=continuation_prompt,
                        allow_input_truncation=True,
                    )
                    for event in retry_events:
                        yield event

                    stream = self._call_ai(context=context, current_input=continuation_prompt, stream=True)
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

                        self.cache_manager.record_message(
                            cached=use_caching, usage=usage_data, model=self.model
                        )

                        dynamic = usage_data["input_tokens"]
                        cache_read = usage_data["cache_read_input_tokens"]
                        cache_write = usage_data["cache_creation_input_tokens"]
                        total = dynamic + cache_read + cache_write

                        if cache_read > 0:
                            pill = "all set"
                            summary = "Conversation still warm"
                        elif cache_write > 0:
                            pill = "cache written"
                            summary = "Cache updated — next message will be faster"
                        else:
                            pill = "no cache"
                            summary = "Sent without cache"

                        yield self._status(
                            "cache_result", pill, summary,
                            detail={
                                "explanation": f"When you send messages less than an hour apart, the whole conversation stays in {self.instance_name}'s mind — they don't need to re-read it from scratch. The longer you talk, the more it saves.",
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

                except Exception as retry_error:
                    self._pending_notifications.clear()
                    yield {"type": "error", "data": f"Error continuing response: {str(retry_error)}"}
                    return
            else:
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
        for msg in self._get_active_prompt_history():
            if msg.get("id") == interrupted_message_id:
                msg["content"] = merged_content
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
                for msg in self._get_active_prompt_history():
                    if msg["id"] == msg_id:
                        msg["temporary"] = False
                        break
            else:
                messages_to_delete.append(msg_id)
                # Remove from conversation history and active prompt window
                self._remove_from_histories(msg_id)
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

        try:
            prepared = self._prepare_ai_request(
                prompt=prompt,
                context=context,
                current_input=current_input,
                attachment_blocks=attachment_blocks,
                consume_reminders=True,
            )

            if prepared["use_caching"]:
                cache_msg = f"💾 Cache: Enabled ({prepared['cache_reason']})"
            else:
                cache_msg = f"💾 Cache: Disabled ({prepared['cache_reason']})"
            print(cache_msg, flush=True)
            print(cache_msg, file=sys.stderr, flush=True)

            # Check if streaming is requested (Phase 4.3)
            if stream:
                # Return AIClient stream generator - yields {"type": "start/chunk/end", ...}
                return self.ai_client.call_stream(
                    messages=prepared["messages"],
                    system=prepared["system"],
                    tools=prepared["tools"] if prepared["tools"] else None,
                    extra_headers=prepared["extra_headers"],
                    thinking=prepared["thinking"]
                )

            # Non-streaming: Use AIClient which handles text extraction and usage tracking
            ai_text, usage_obj, thinking_text = self.ai_client.call(
                messages=prepared["messages"],
                system=prepared["system"],
                tools=prepared["tools"] if prepared["tools"] else None,
                extra_headers=prepared["extra_headers"],
                thinking=prepared["thinking"]
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
                cached=prepared["use_caching"],
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
        self.active_prompt_history.clear()
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
