"""
Command System Module for Mneme Memory System

Implements all @commands for manual memory management:
- @remember: Mark moments as high-importance
- @recall: Retrieve memories by topic
- @forget: Archive and reduce importance
- @modify: Modify memory importance
- @view: View message by ID with full metadata
- @config: Adjust system settings
- @help: Show available commands

SPEC ALIGNMENT:
Line 58-60: @remember sets importance to 10.0 directly
Line 62: Referenced +2 importance
Lines 91-96: Instance autonomy for certain settings

USAGE:
    handler = CommandHandler(db, embedder, config, background_queue)
    result = handler.handle_command(user_input)
"""

from typing import Dict, Optional, List
from datetime import datetime, timedelta
from pathlib import Path
import re
import json
from .sandbox_runner import AppContainerBackend, SandboxUnavailable


class CommandError(Exception):
    """Custom exception for command execution errors."""
    pass


class CommandHandler:
    """
    Handles all @commands for memory management and system configuration.

    This class implements:
    - Memory marking (@remember)
    - Memory retrieval (@recall)
    - Memory archiving (@forget)
    - Memory modification (@modify)
    - Configuration changes (@config)
    - Help system (@help)
    - File attachments (@file, @describe) - Phase 7
    """

    def __init__(self, database, embedder, config, background_queue, context_assembler=None, graph_db=None, file_processor=None, artifact_storage=None):
        """
        Initialize command handler.

        Args:
            database: Database instance
            embedder: EmbeddingGenerator instance
            config: Configuration dictionary
            background_queue: BackgroundQueue instance
            context_assembler: ContextAssembler instance
            graph_db: GraphDatabase instance (for entity commands; @graph kept for compatibility)
            file_processor: FileProcessor instance (for @file/@describe commands, Phase 7)
            artifact_storage: ArtifactStorage instance (for @artifact command)
        """
        self.db = database
        self.embedder = embedder
        self.config = config
        self.background_queue = background_queue
        self.context_assembler = context_assembler
        self.graph_db = graph_db
        self.file_processor = file_processor
        self.artifact_storage = artifact_storage

        # Instance autonomy settings (what instance can modify without approval)
        commands_config = config.get("commands", {})
        self.instance_autonomy = commands_config.get("instance_autonomy", [
            "similarity_threshold",
            "semantic_weight",
            "importance_weight",
            "recency_weight",
            "recent_messages_tokens",
            "temperature"
        ])

    def _ok(self, cmd: str, msg: str, data: dict = None) -> Dict:
        r = {"success": True, "command": cmd, "message": msg}
        if data is not None:
            r["data"] = data
        return r

    def _err(self, cmd: str, msg: str, data: dict = None) -> Dict:
        r = {"success": False, "command": cmd, "message": msg}
        if data is not None:
            r["data"] = data
        return r

    def is_command(self, message: str) -> bool:
        """
        Check if message is a command.

        Args:
            message: User input

        Returns:
            bool: True if starts with @, False otherwise
        """
        return message.strip().startswith("@")

    def handle_command(self, message: str, marked_by: str = "user") -> Dict:
        """
        Parse and execute command.

        Args:
            message: Command string (e.g., "@remember This is important")
            marked_by: Who issued command ("user" or "instance")

        Returns:
            dict: Command result {
                "success": bool,
                "command": str,
                "message": str,
                "data": dict (optional)
            }

        Raises:
            CommandError: If command invalid or execution fails
        """
        message = message.strip()

        if not self.is_command(message):
            raise CommandError("Not a command (must start with @)")

        # Parse command
        parts = message[1:].split(None, 1)  # Remove @ and split
        command = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        # Route to appropriate handler
        if command == "remember":
            return self.cmd_remember(args, marked_by)
        elif command == "recall":
            return self.cmd_recall(args)
        elif command == "forget":
            return self.cmd_forget(args)
        elif command == "note":
            return self.cmd_note(args)
        elif command == "modify":
            return self.cmd_modify(args, marked_by)
        elif command == "view":
            return self.cmd_view(args)
        elif command == "config":
            return self.cmd_config(args, marked_by)
        elif command == "graph":
            return self.cmd_graph(args)
        elif command == "concept":
            return self.cmd_concept(args, marked_by)
        elif command == "file":
            return self.cmd_file(args)
        elif command == "describe":
            return self.cmd_describe(args)
        elif command == "artifact":
            return self.cmd_artifact(args)
        elif command == "run":
            return self.cmd_run(args)
        elif command == "entity":
            return self.cmd_entity(args, marked_by)
        elif command == "help":
            return self.cmd_help(args)
        else:
            return self._err(command, f"Unknown command: @{command}. Type @help for available commands.")

    # =========================================================================
    # SPEC LINE 74: @remember [text] - Mark as high-importance
    # =========================================================================

    def cmd_remember(self, text: str, marked_by: str = "user") -> Dict:
        """
        Mark a message as high-importance by its ID.

        Args:
            text: Message ID (integer shown as [ID:N] in context)
            marked_by: Who marked it ("user" or "instance")

        Returns:
            dict: Result with marked message info

        Explicitly marked messages go straight to max importance (10.0).
        The multiplier system was too subtle — ×2 on baseline 3.0 = 6.0,
        which later gets overridden by tier transitions to something lower.
        """
        try:
            msg_id = int(text.strip())
        except (ValueError, TypeError):
            return self._err("remember", "Usage: @remember {id} — use the [ID:N] shown next to messages in context")

        message = self.db.get_message(msg_id)
        if not message:
            return self._err("remember", f"Message ID {msg_id} not found")

        msg_id = message["id"]
        current_importance = message["importance_score"]

        # Check if already marked (handle None metadata safely)
        metadata_str = message.get("metadata")
        metadata = json.loads(metadata_str) if metadata_str else {}
        already_marked_by = metadata.get("marked_by", [])

        # Determine new marking status
        if marked_by in already_marked_by:
            return self._err("remember", f"Already marked by {marked_by}")

        # Update marking list
        already_marked_by.append(marked_by)
        metadata["marked_by"] = already_marked_by

        # Set to max importance directly — explicit marking = max priority
        new_importance = 10.0

        # Update database
        self.db.update_message_importance(
            msg_id,
            new_importance,
            reason=f"marked_by_{marked_by}",
            details={
                "previous_importance": current_importance,
                "marked_by": already_marked_by
            }
        )

        # Update metadata
        self.db.execute_write(
            "UPDATE messages SET metadata = ? WHERE id = ?",
            (json.dumps(metadata), msg_id)
        )

        return self._ok("remember", f"Marked as high-importance (set to {new_importance:.0f})", {
            "message_id": msg_id,
            "content_preview": message["content"][:100],
            "previous_importance": current_importance,
            "new_importance": new_importance,
            "marked_by": already_marked_by
        })

    # =========================================================================
    # SPEC LINE 75-76: @recall [topic] - Retrieve memories
    # =========================================================================

    def cmd_recall(self, query: str) -> Dict:
        """
        Retrieve memories about topic.

        Args:
            query: Search query (e.g., "crows" or "--deep vulnerability")

        Returns:
            dict: Results with retrieved memories

        SPEC LINE 62: Mark as referenced (+2 importance)

        USAGE:
        @recall crows → Search standard pool
        @recall --deep crows → Search deep archive
        """
        if not query.strip():
            return self._err("recall", "Please specify what to recall. Usage: @recall [topic]")

        # Check for --deep flag
        deep = False
        if query.startswith("--deep "):
            deep = True
            query = query[7:]  # Remove "--deep "

        # Perform semantic search
        from .retrieval import MemoryRetriever
        threshold = self.config.get("retrieval", {}).get("similarity_threshold", 0.25)
        max_results = self.config.get("retrieval", {}).get("max_results", 20)
        entity_match_weight = self.config.get("retrieval", {}).get("entity_match_weight", 0.15)
        retriever = MemoryRetriever(self.db, self.embedder, similarity_threshold=threshold,
                                    entity_match_weight=entity_match_weight, graph_db=self.graph_db)

        if deep:
            # Search deep archive (all tiers)
            results = retriever.semantic_search(
                query,
                limit=max_results,
                tier=None,  # All tiers
                months_back=None  # No time limit
            )
        else:
            # Standard search: explicit recall must never miss a memory just
            # because it's recent — the prompt's recent-message window is
            # smaller than the active tier, and the AI may not have the
            # target message in context. Search both active and standard
            # tiers (unlike automatic per-turn retrieval, which is
            # standard-only — see context.py::_retrieve_memories).
            results = retriever.semantic_search(
                query,
                limit=max_results,
                tier=["active", "standard"],
                months_back=6
            )

        if not results:
            return self._ok("recall", f"No memories found for: {query}" + (" (deep search)" if deep else ""), {"results": []})

        # Format results
        formatted = []
        for r in results:
            formatted.append({
                "id": r["id"],
                "content": r["content"],  # Full content, no truncation
                "timestamp": r["timestamp"],
                "importance": r["importance"],
                "tags": r.get("tags", []),
                "similarity": r["semantic_similarity"],
                "final_score": r["final_score"]
            })

        # Note: Memories are automatically marked as referenced in ContextAssembler
        # when they're retrieved, which adds +2 to importance (spec line 62)

        return self._ok("recall", f"Found {len(results)} memories for: {query}" + (" (deep search)" if deep else ""), {"results": formatted, "deep_search": deep})

    # =========================================================================
    # SPEC LINE 77: @forget [topic] - Two-step archive with preview
    # =========================================================================

    def cmd_forget(self, topic: str) -> Dict:
        """
        Two-step memory archival: preview then confirm.

        Step 1: @forget {topic} — shows matching memories with IDs and haiku summaries
        Step 2: @forget confirm {id1} {id2} ... — archives the selected messages
                @forget confirm all — archives all previewed messages

        Uses keyword pre-filter + semantic scoring to find relevant matches.
        Higher similarity threshold (1.5x normal) to avoid irrelevant results.
        """
        if not topic.strip():
            return self._err("forget", "Usage: @forget {topic} → preview, then @forget confirm {id1} {id2} ...")

        # Step 2: Handle confirmation
        if topic.startswith("confirm"):
            return self._forget_confirm(topic[len("confirm"):].strip())

        # Step 1: Preview — find matching memories
        return self._forget_preview(topic)

    def _forget_preview(self, topic: str) -> Dict:
        """Find memories matching topic and return preview list."""
        from .retrieval import MemoryRetriever
        import json

        base_threshold = self.config.get("retrieval", {}).get("similarity_threshold", 0.25)
        # Higher threshold to avoid irrelevant matches
        forget_threshold = min(base_threshold * 1.5, 0.6)
        retriever = MemoryRetriever(self.db, self.embedder, similarity_threshold=forget_threshold)

        # Keyword pre-filter: find messages containing topic words
        keyword_matches = self.db.search_messages_keyword(topic, limit=100)
        keyword_ids = {msg["id"] for msg in keyword_matches}

        # Semantic search
        semantic_results = retriever.semantic_search(topic, limit=30)

        # Merge: prioritize messages that match both keyword AND semantic
        # Then include semantic-only matches above a stricter threshold
        previews = []
        seen_ids = set()

        for result in semantic_results:
            msg_id = result["id"]
            if msg_id in seen_ids:
                continue
            seen_ids.add(msg_id)

            metadata = result.get("metadata", {})
            description = metadata.get("description", "")
            similarity = result.get("semantic_similarity", 0)
            in_keyword = msg_id in keyword_ids

            # Include if: keyword match + semantic, or very high semantic alone
            if in_keyword or similarity >= forget_threshold * 1.2:
                previews.append({
                    "id": msg_id,
                    "description": description or result["content"][:60].replace("\n", " "),
                    "sender": result["sender"],
                    "timestamp": result["timestamp"][:10],
                    "similarity": round(similarity, 2),
                    "keyword_match": in_keyword,
                    "importance": result["importance"],
                })

        if not previews:
            return self._ok("forget", f"No memories found matching: {topic}", {"archived_count": 0})

        # Cap at 20 previews
        previews = previews[:20]

        # Store pending list for confirm step
        self._pending_forget = {p["id"]: p for p in previews}
        self._pending_forget_topic = topic

        # Build preview message
        lines = [f"Found {len(previews)} memories matching \"{topic}\":\n"]
        for p in previews:
            marker = "K+S" if p["keyword_match"] else "S"
            lines.append(f"  [ID:{p['id']}] {p['description']} ({p['timestamp']}, imp:{p['importance']:.1f}, {marker})")

        lines.append(f"\nTo archive, use: @forget confirm <id1> <id2> ... (or 'all')")
        lines.append(f"K+S = keyword + semantic match, S = semantic only")

        return self._ok("forget", "\n".join(lines), {
            "is_retrieval": True,
            "previews": previews,
            "topic": topic,
        })

    def _forget_confirm(self, args: str) -> Dict:
        """Archive confirmed message IDs."""
        if not args:
            return self._err("forget", "Usage: @forget confirm {id1} {id2} ... (or 'all')")

        pending = getattr(self, "_pending_forget", {})
        topic = getattr(self, "_pending_forget_topic", "unknown")

        # The preview IS the safety mechanism: confirm only ever archives
        # what a preceding @forget <topic> actually showed.
        if not pending:
            return self._err("forget", "Nothing to confirm. Run @forget <topic> first to preview.")

        if args.strip().lower() == "all":
            ids_to_archive = list(pending.keys())
        else:
            # Parse IDs from args, rejecting anything the preview didn't show
            ids_to_archive = []
            rejected = []
            for token in args.split():
                try:
                    msg_id = int(token)
                except ValueError:
                    continue
                if msg_id in pending:
                    ids_to_archive.append(msg_id)
                else:
                    rejected.append(msg_id)
            if rejected:
                rejected_list = ", ".join(str(r) for r in rejected)
                return self._err(
                    "forget",
                    f"ID(s) not in the current preview: {rejected_list}. "
                    f"Nothing was archived. Run @forget <topic> again to refresh the preview."
                )

        if not ids_to_archive:
            return self._err("forget", "No valid IDs provided. Use @forget confirm {id1} {id2} ... or 'all'")

        # Archive each confirmed message
        archived_count = 0
        for msg_id in ids_to_archive:
            msg = self.db.get_message(msg_id)
            if not msg:
                continue

            # Move to deep archive
            self.db.update_message_tier(msg_id, "deep_archive")

            # Halve importance (proportional reduction)
            current_importance = msg.get("importance_score", 5.0)
            new_importance = max(current_importance * 0.5, 1.0)
            self.db.update_message_importance(
                msg_id,
                new_importance,
                reason="forgotten_by_user",
                details={"topic": topic}
            )

            archived_count += 1

        # Clear pending state
        self._pending_forget = {}
        self._pending_forget_topic = ""

        return self._ok("forget", f"Archived {archived_count} memories about: {topic}", {"archived_count": archived_count, "topic": topic})

    # =========================================================================
    # PHASE 11: @note - AI-managed persistent notes
    # =========================================================================

    def cmd_note(self, args: str) -> Dict:
        """
        Manage AI persistent notes organized in named sections.

        Args:
            args: Subcommand and arguments:
                  - "remove {section}" - Remove a section
                  - "clear" - Clear all notes
                  - "{section_name}\\ncontent...\\n@endnote" - Create/replace section
                    (multi-line parsed by instance_executor pre-pass)

        Returns:
            dict: Command result (non-retrieval, no continuation)

        USAGE (AI only, instance command):
        @note Preferences
        - Dark themes, minimal UI
        - Direct communication style
        @endnote

        @note remove Preferences

        @note clear
        """
        if not args.strip():
            return self._err("note", "Usage: @note <section_name>\\n<content>\\n@endnote, @note remove <section>, or @note clear")

        args_stripped = args.strip()

        # Handle @note clear
        if args_stripped.lower() == "clear":
            count = self.db.clear_notes()
            return self._ok("note", f"Cleared all notes ({count} sections removed)")

        # Handle @note remove {section}
        if args_stripped.lower().startswith("remove "):
            section_name = args_stripped[7:].strip()
            if not section_name:
                return self._err("note", "Usage: @note remove <section_name>")
            removed = self.db.remove_note(section_name)
            if removed:
                return self._ok("note", f"Removed note section: {section_name}")
            else:
                return self._err("note", f"Note section not found: {section_name}")

        # Handle @note {section_name}\ncontent\n@endnote
        # The multi-line block is already parsed by instance_executor pre-pass
        # args will contain: "section_name\ncontent..." (with @endnote stripped)
        lines = args_stripped.split("\n", 1)
        section_name = lines[0].strip()

        if len(lines) < 2 or not lines[1].strip():
            return self._err("note", f"No content provided for section '{section_name}'. Use multi-line format with @endnote.")

        content = lines[1].strip()

        # Strip trailing @endnote if present (safety, should already be stripped)
        if content.endswith("@endnote"):
            content = content[:-len("@endnote")].strip()

        if not content:
            return self._err("note", f"No content provided for section '{section_name}'.")

        self.db.set_note(section_name, content)
        return self._ok("note", f"Updated note section: {section_name}")

    # =========================================================================
    # @modify - Modify memory importance
    # =========================================================================

    def cmd_modify(self, args: str, marked_by: str = "user") -> Dict:
        """
        Modify memory importance score.

        Args:
            args: "{msg_id} importance {score}" format
            marked_by: Who is modifying ("user" or "instance")

        Returns:
            dict: Result with modification details

        USAGE:
        @modify 123 importance 7.5 - Set importance to 7.5/10
        """
        if not args.strip():
            return self._err("modify", "Usage: @modify {msg_id} importance {score}")

        parts = args.split(None, 2)
        if len(parts) < 3:
            return self._err("modify", "Usage: @modify {msg_id} importance {score}")

        # Parse message ID
        try:
            msg_id = int(parts[0])
        except ValueError:
            return self._err("modify", f"Invalid message ID: {parts[0]} (must be a number)")

        # Check if message exists
        message = self.db.get_message(msg_id)
        if not message:
            return self._err("modify", f"Message {msg_id} not found")

        action = parts[1].lower()

        # Handle importance modification
        if action == "importance":
            try:
                new_importance = float(parts[2])
            except ValueError:
                return self._err("modify", f"Invalid importance score: {parts[2]} (must be a number between 1.0 and 10.0)")

            # Validate range
            if new_importance < 1.0 or new_importance > 10.0:
                return self._err("modify", f"Importance score must be between 1.0 and 10.0 (got {new_importance})")

            old_importance = message.get("importance_score", 3.0)

            # Update importance
            self.db.update_message_importance(
                msg_id,
                new_importance,
                reason=f"manual_modification_by_{marked_by}",
                details={
                    "old_importance": old_importance,
                    "new_importance": new_importance,
                    "modified_by": marked_by
                }
            )

            return self._ok("modify", f"Updated importance: {old_importance:.1f} → {new_importance:.1f}", {
                "message_id": msg_id,
                "old_importance": old_importance,
                "new_importance": new_importance,
                "content_preview": message["content"][:100]
            })

        else:
            return self._err("modify", f"Invalid action: {action} (must be 'importance')")

    # =========================================================================
    # @view - View a specific message by ID with all metadata
    # =========================================================================

    def cmd_view(self, args: str) -> Dict:
        """
        View a specific message by ID with all metadata.

        Args:
            args: Message ID to view

        Returns:
            dict: Message with full metadata (triggers continuation)

        USAGE:
        @view 123 - View message ID 123 with all details
        """
        if not args.strip():
            return self._err("view", "Usage: @view {msg_id}")

        # Parse message ID
        try:
            msg_id = int(args.strip())
        except ValueError:
            return self._err("view", f"Invalid message ID: {args} (must be a number)")

        # Get message
        message = self.db.get_message(msg_id)
        if not message:
            return self._err("view", f"Message {msg_id} not found")

        # Format detailed view
        details = []
        details.append(f"\n{'='*70}")
        details.append(f"MESSAGE ID: {message['id']}")
        details.append(f"{'='*70}")
        details.append(f"Timestamp: {message['timestamp']}")
        details.append(f"Sender: {message['sender']}")
        details.append(f"Importance: {message.get('importance_score', 3.0):.1f}/10")
        details.append(f"Tier: {message.get('tier', 'unknown')}")
        details.append(f"\nContent:\n{message['content']}")
        details.append(f"{'='*70}\n")

        formatted_details = "\n".join(details)

        return self._ok("view", formatted_details, {"content": formatted_details})

    # =========================================================================
    # SPEC LINE 80: @config [parameter] [value] - Adjust settings
    # =========================================================================

    def cmd_config(self, args: str, requester: str = "user") -> Dict:
        """
        Adjust system configuration.

        Args:
            args: "[parameter] [value]" format
            requester: Who requested change ("user" or "instance")

        Returns:
            dict: Result with updated config

        SPEC LINES 91-96: Instance autonomy
        Instance can modify certain parameters without approval.
        Others require mutual consent.

        USAGE:
        @config temperature 1.2
        @config recent_messages_tokens 80000
        @config similarity_threshold 0.3
        """
        parts = args.split(None, 1)
        if len(parts) < 2:
            # Show current config
            return self._ok("config", "Current configuration", self._get_current_config())

        parameter = parts[0]
        value = parts[1]

        # Check autonomy
        if requester == "instance" and parameter not in self.instance_autonomy:
            return self._err("config", f"Instance cannot modify '{parameter}' (requires user approval)", {"requires_approval": True})

        # Apply change
        success, message = self._apply_config_change(parameter, value)

        return {
            "success": success,
            "command": "config",
            "message": message,
            "data": {"parameter": parameter, "new_value": value if success else None}
        }

    def _get_current_config(self) -> Dict:
        """Get current configuration values."""
        return {
            "temperature": self.config.get("model", {}).get("temperature", 1.0),
            "recent_messages_tokens": self.config.get("context", {}).get("recent_messages_tokens", 50000),
            "similarity_threshold": self.config.get("retrieval", {}).get("similarity_threshold", 0.25),
            "semantic_weight": self.config.get("retrieval", {}).get("semantic_weight", 0.4),
            "importance_weight": self.config.get("retrieval", {}).get("importance_weight", 0.4),
            "recency_weight": self.config.get("retrieval", {}).get("recency_weight", 0.2)
        }

    def _apply_config_change(self, parameter: str, value: str) -> tuple:
        """
        Apply configuration change.

        Args:
            parameter: Config parameter name
            value: New value (as string)

        Returns:
            tuple: (success: bool, message: str)
        """
        try:
            # Parse value
            if parameter in ["temperature", "similarity_threshold", "semantic_weight", "importance_weight", "recency_weight"]:
                new_value = float(value)
            elif parameter in ["recent_messages_tokens"]:
                new_value = int(value)
            else:
                return False, f"Unknown parameter: {parameter}"

            # Validate ranges
            if parameter == "temperature":
                if not 0.0 <= new_value <= 2.0:
                    return False, "Temperature must be between 0.0 and 2.0"
                self.config["model"]["temperature"] = new_value

            elif parameter == "similarity_threshold":
                if not 0.0 <= new_value <= 1.0:
                    return False, "Retrieval threshold must be between 0.0 and 1.0"
                self.config["retrieval"]["similarity_threshold"] = new_value

            elif parameter == "recent_messages_tokens":
                if new_value < 1000:
                    return False, "Recent context must be at least 1000 tokens"
                self.config["context"]["recent_messages_tokens"] = new_value

            elif parameter in ["semantic_weight", "importance_weight", "recency_weight"]:
                if not 0.0 <= new_value <= 1.0:
                    return False, f"{parameter} must be between 0.0 and 1.0"
                self.config["retrieval"][parameter] = new_value

            return True, f"Updated {parameter} to {new_value}"

        except ValueError:
            return False, f"Invalid value for {parameter}: {value}"

    # =========================================================================
    # @graph - Deprecated compatibility wrapper for entity overview/detail
    # =========================================================================

    def cmd_graph(self, args: str) -> Dict:
        """
        Query the entity system for overview or details on a specific entity.

        Args:
            args: Optional entity name to focus on

        Returns:
            dict: Command result

        USAGE:
        @graph                 Compatibility alias for entity overview
        @graph consciousness   Compatibility alias for entity details
        """
        if not self.graph_db:
            return self._err("graph", "Entity system not enabled. Set features.entity_summaries.enabled=true in config.")

        try:
            if not args.strip():
                entity_stats = self.graph_db.get_entity_stats(min_mentions=1)

                if not entity_stats:
                    return self._ok("graph", "No entities yet — they are discovered automatically during conversation.", {"empty": True})

                top_entities = entity_stats[:15]

                response = f"📊 ENTITY OVERVIEW\n\n"
                response += f"Total entities: {len(entity_stats)}\n\n"
                response += "Top entities by mentions:\n"
                for i, entity in enumerate(top_entities, 1):
                    aliases = ""
                    if entity.get("aliases"):
                        alias_list = json.loads(entity["aliases"]) if isinstance(entity["aliases"], str) else entity["aliases"]
                        if alias_list:
                            aliases = f" (aka {', '.join(alias_list[:3])})"
                    response += f"  {i}. {entity['name']}{aliases} — {entity['mention_count']} mentions\n"

                return self._ok("graph", response.strip())

            else:
                entity_name = args.strip()
                entity = self.graph_db.get_entity_by_name_or_alias(entity_name)

                if not entity:
                    return self._err("graph", f"Entity not found: {entity_name}\n\nTry @entity list to see available entities.")

                canonical_name = entity["name"]

                response = f"📊 ENTITY: {canonical_name.upper()}\n\n"
                response += f"Mentions: {entity['mention_count']}\n"
                response += f"Type: {entity.get('entity_type', 'unknown')}\n"

                if entity.get("aliases"):
                    aliases = json.loads(entity["aliases"]) if isinstance(entity["aliases"], str) else entity["aliases"]
                    if aliases:
                        response += f"Aliases: {', '.join(aliases)}\n"

                return self._ok("graph", response.strip())

        except Exception as e:
            return self._err("graph", f"Entity query failed: {e}")

    # =========================================================================
    # @concept - Narrative concept management (Phase 6)
    # =========================================================================

    def cmd_concept(self, args: str, requester: str = "user") -> Dict:
        """
        Manage narrative concepts for contextual interpretation.

        Args:
            args: Sub-command and arguments
            requester: Who requested ("user" or "instance")

        Returns:
            dict: Command result

        USAGE:
        @concept list                                     List all concepts
        @concept view [name]                              View specific concept
        @concept create [name] | [keywords] | [definition]
        @concept edit [name] | [keywords] | [definition]
        @concept delete [name]

        PHASE 6: Narrative concepts bridge memories and graph relationships
        """
        if not args.strip():
            # Show usage
            return self._err("concept",
                            "Usage:\n"
                            "@concept list\n"
                            "@concept view [name]\n"
                            "@concept create [name] | [keywords] | [definition]\n"
                            "@concept edit [name] | [keywords] | [definition]\n"
                            "@concept delete [name]")

        # Parse sub-command
        parts = args.split(None, 1)
        sub_command = parts[0].lower()
        sub_args = parts[1] if len(parts) > 1 else ""

        if sub_command == "list":
            # List all concepts
            concepts = self.db.get_all_concepts()

            if not concepts:
                return self._ok("concept", "No concepts defined yet. Use @concept create to add one.", {"concepts": []})

            # Format list
            response = f"📚 {len(concepts)} CONCEPTS:\n\n"
            for concept in concepts:
                keywords = ", ".join(concept["trigger_keywords"][:3])
                if len(concept["trigger_keywords"]) > 3:
                    keywords += f", +{len(concept['trigger_keywords']) - 3} more"
                response += f"**{concept['name']}**\n"
                response += f"  Keywords: {keywords}\n"
                response += f"  {concept['definition'][:100]}{'...' if len(concept['definition']) > 100 else ''}\n\n"

            return self._ok("concept", response.strip(), {"concepts": concepts})

        elif sub_command == "view":
            # View specific concept
            if not sub_args:
                return self._err("concept", "Usage: @concept view [name]")

            concept = self.db.get_concept_by_name(sub_args.strip())

            if not concept:
                return self._err("concept", f"Concept not found: {sub_args}")

            # Format full concept
            response = f"📖 CONCEPT: {concept['name'].upper()}\n\n"
            response += f"Definition:\n{concept['definition']}\n\n"
            response += f"Trigger Keywords:\n"
            for keyword in concept["trigger_keywords"]:
                response += f"  - {keyword}\n"
            response += f"\nCreated by: {concept['created_by']}\n"
            response += f"Created: {concept['created_at']}\n"
            response += f"Updated: {concept['updated_at']}"

            return self._ok("concept", response, {"concept": concept})

        elif sub_command == "create":
            # Create new concept
            # Format: @concept create [name] | [keywords] | [definition]
            if not sub_args or sub_args.count("|") < 2:
                return self._err("concept", "Usage: @concept create [name] | [keyword1, keyword2] | [definition]")

            parts = sub_args.split("|")
            name = parts[0].strip()
            keywords_str = parts[1].strip()
            definition = parts[2].strip()

            # Parse keywords
            keywords = [k.strip() for k in keywords_str.split(",") if k.strip()]

            if not name or not keywords or not definition:
                return self._err("concept", "Name, keywords, and definition are all required")

            # Check if exists
            existing = self.db.get_concept_by_name(name)
            if existing:
                return self._err("concept", f"Concept '{name}' already exists. Use @concept edit to modify.")

            # Create concept
            try:
                concept_id = self.db.create_concept(
                    name=name,
                    definition=definition,
                    trigger_keywords=keywords,
                    created_by=requester
                )

                return self._ok("concept", f"✓ Created concept '{name}' with {len(keywords)} keywords")
            except Exception as e:
                return self._err("concept", f"Failed to create concept: {e}")

        elif sub_command == "edit":
            # Edit existing concept
            # Format: @concept edit [name] | [keywords] | [definition]
            if not sub_args or sub_args.count("|") < 2:
                return self._err("concept", "Usage: @concept edit [name] | [keyword1, keyword2] | [definition]")

            parts = sub_args.split("|")
            name = parts[0].strip()
            keywords_str = parts[1].strip()
            definition = parts[2].strip()

            # Parse keywords
            keywords = [k.strip() for k in keywords_str.split(",") if k.strip()]

            if not name:
                return self._err("concept", "Concept name is required")

            # Check if exists
            existing = self.db.get_concept_by_name(name)
            if not existing:
                return self._err("concept", f"Concept '{name}' not found. Use @concept create to add it.")

            # Update concept
            try:
                success = self.db.update_concept(
                    concept_id=existing["id"],
                    definition=definition if definition else None,
                    trigger_keywords=keywords if keywords else None
                )

                if success:
                    return self._ok("concept", f"✓ Updated concept '{name}'")
                else:
                    return self._err("concept", f"Failed to update concept '{name}'")
            except Exception as e:
                return self._err("concept", f"Failed to update concept: {e}")

        elif sub_command == "delete":
            # Delete concept
            if not sub_args:
                return self._err("concept", "Usage: @concept delete [name]")

            name = sub_args.strip()

            # Check if exists
            existing = self.db.get_concept_by_name(name)
            if not existing:
                return self._err("concept", f"Concept '{name}' not found")

            # Delete
            try:
                success = self.db.delete_concept(existing["id"])

                if success:
                    return self._ok("concept", f"✓ Deleted concept '{name}'")
                else:
                    return self._err("concept", f"Failed to delete concept '{name}'")
            except Exception as e:
                return self._err("concept", f"Failed to delete concept: {e}")

        else:
            return self._err("concept", f"Unknown sub-command: {sub_command}. Use @concept without arguments for usage.")

    # =========================================================================
    # @entity - Force-include an entity summary on the next retrieval
    # =========================================================================

    def cmd_entity(self, args: str, marked_by: str = "user") -> Dict:
        """
        Manage entity summaries and force-include entities in retrieval.

        Usage:
            @entity list             List all entities (name, type, alias count)
            @entity view {name}      Show entity's current summary text
            @entity merge {a} | {b}  Merge two or more entities into one
            @entity {name}           Force-include entity in next retrieval

        Looks up the entity by name, alias, or partial FTS match.
        """
        if not self.graph_db:
            return self._err("entity", "Entity system not available.")

        name = args.strip()
        if not name:
            return self._err("entity", "Usage: @entity <name> — e.g. @entity Sanni\nOr: @entity list / @entity view <name>")

        # Dispatch sub-commands
        parts = name.split(None, 1)
        sub_command = parts[0].lower()
        sub_args = parts[1] if len(parts) > 1 else ""

        if sub_command == "list":
            entities = self.graph_db.get_entity_stats(min_mentions=1)

            if not entities:
                return self._ok("entity", "No entities tracked yet.", {"entities": []})

            response = f"🗂️ {len(entities)} ENTITIES:\n\n"
            for e in entities:
                aliases = e.get("aliases") or []
                alias_count = len(aliases) if isinstance(aliases, list) else 0
                entity_type = e.get("description", "")[:40] if e.get("description") else ""
                alias_str = f"  ({alias_count} aliases)" if alias_count else ""
                response += f"**{e['name']}**{alias_str}\n"
                if entity_type:
                    response += f"  {entity_type}\n"

            return self._ok("entity", response.strip(), {"entities": entities})

        elif sub_command == "view":
            if not sub_args:
                return self._err("entity", "Usage: @entity view <name>")

            entity = self.graph_db.get_entity_by_name_or_alias(sub_args.strip())
            if not entity:
                results = self.graph_db.search_entities(sub_args.strip(), limit=1)
                entity = results[0] if results else None

            if not entity:
                return self._err("entity", f"No entity found matching '{sub_args}'.")

            entity_id = entity["id"]
            entity_name = entity["name"]

            # All-time preferred; fall back to the newest monthly summary —
            # roughly a third of entities only ever get monthly ones.
            summary = self.db.get_entity_summary(entity_id, "all_time")
            if not (summary and summary.get("summary")):
                summary = self.db.get_latest_monthly_summary(entity_id)

            response = f"📋 ENTITY: {entity_name.upper()}\n\n"
            if entity.get("description"):
                response += f"Description: {entity['description']}\n\n"
            if summary and summary.get("summary"):
                label = "Summary" if summary.get("period_type") == "all_time" \
                    else f"Summary ({summary.get('period_start', 'recent month')})"
                response += f"{label}:\n{summary['summary']}"
            else:
                response += ("No summary yet — one builds automatically "
                             "the next time this topic comes up.")

            return self._ok("entity", response, {"entity": entity, "summary": summary})

        elif sub_command == "merge":
            # Destructive and judgment-heavy — humans only. AI-proposed merges
            # belong to the planned consolidation suggestion flow, not here.
            if marked_by == "instance":
                return self._err("entity", "@entity merge is human-only.")
            return self._entity_merge(sub_args)

        else:
            # Original behavior: force-include entity in next retrieval
            if not self.context_assembler:
                return self._err("entity", "Context assembler not available.")

            entity = self.graph_db.get_entity_by_name_or_alias(name)
            if not entity:
                results = self.graph_db.search_entities(name, limit=1)
                entity = results[0] if results else None

            if not entity:
                return self._err("entity", f"No entity found matching '{name}'. Check @entity list for entity names.")

            entity_id = entity["id"]
            entity_name = entity["name"]

            self.context_assembler.forced_entity_ids.append(entity_id)

            return self._ok("entity", f"'{entity_name}' will be included in the next retrieval.")

    def _entity_merge(self, sub_args: str) -> Dict:
        """
        Merge two or more entities into one: @entity merge A | B | C

        Haiku picks the surviving canonical name (from the input names only)
        and writes a merged description. Then:
        - message_entities links repoint to the survivor (deduped)
        - all summaries for every involved entity are deleted — the lazy
          summary pipeline rebuilds the merged history on next retrieval
        - losers' names + aliases become aliases of the survivor, so future
          entity assignment redirects instead of recreating the dead names

        No side effects happen unless every input name resolves.
        """
        names = [n.strip() for n in sub_args.split("|") if n.strip()]
        if len(names) < 2:
            return self._err("entity", "Usage: @entity merge <name1> | <name2> [| <name3> ...]")

        # Resolve every name first — abort cleanly on any miss
        entities = []
        seen_ids = set()
        for name in names:
            entity = self.graph_db.get_entity_by_name_or_alias(name)
            if not entity:
                return self._err("entity", f"No entity found matching '{name}'. Nothing was merged.")
            if entity["id"] in seen_ids:
                return self._err("entity", f"'{name}' resolves to an already-listed entity. Nothing was merged.")
            seen_ids.add(entity["id"])
            entities.append(entity)

        # Haiku chooses the survivor + merged description (no side effects yet).
        # Fallback if the API is unavailable: most-mentioned entity wins.
        canonical_name, merged_description = self._merge_arbiter(entities)
        target = next(e for e in entities if e["name"] == canonical_name)
        sources = [e for e in entities if e["id"] != target["id"]]
        source_ids = [e["id"] for e in sources]

        # Main DB: repoint links, drop stale summaries (lazy rebuild)
        link_count = self.db.merge_entity_links(target["id"], source_ids)
        self.db.delete_all_entity_summaries([target["id"], *source_ids])

        # Graph DB: absorb names/aliases, delete sources. This is a separate
        # SQLite file — the main-DB writes above are already committed, so a
        # failure here leaves a split state. Every step is idempotent, so
        # re-running the same merge completes it; surface that instead of
        # letting the raw exception hide what happened.
        try:
            merged = self.graph_db.merge_entities(
                target["id"], source_ids, new_description=merged_description
            )
        except Exception as e:
            return self._err(
                "entity",
                f"Merge partially completed: message links now point at "
                f"'{target['name']}', but combining the entity records failed "
                f"({e}). Run the same @entity merge again to finish it."
            )

        # Rebuild the survivor's summary now, in the background — the merge
        # deleted every summary (monthly + all-time), and "No summary
        # generated yet" right after a merge reads as a bug even though the
        # lazy pipeline would rebuild it on next retrieval.
        def _rebuild_summary(entity_id=target["id"]):
            try:
                from src.backend.entity_summaries import EntitySummaryManager
                manager = EntitySummaryManager(self.config, self.db, self.graph_db)
                manager.get_or_create_summary(entity_id, show_progress=False)
            except Exception as e:
                print(f"⚠️ Post-merge summary rebuild failed (lazy rebuild will retry): {e}")

        import threading
        threading.Thread(target=_rebuild_summary, daemon=True,
                         name="merge-summary-rebuild").start()

        absorbed = ", ".join(e["name"] for e in sources)
        return self._ok(
            "entity",
            f"Merged {absorbed} into '{merged['name']}' ({link_count} linked messages). "
            f"Its combined summary is rebuilding in the background — give it a moment.",
            {"merged_entity": merged, "absorbed": [e["name"] for e in sources], "link_count": link_count}
        )

    def _merge_arbiter(self, entities: List[Dict]) -> tuple:
        """
        Ask Haiku which entity name should survive a merge, and for a merged
        description. Returns (canonical_name, description). Deterministic
        fallback (most mentions wins, descriptions joined) on any failure.
        """
        fallback = max(entities, key=lambda e: e.get("mention_count") or 0)
        fallback_desc = "; ".join(
            d for d in dict.fromkeys((e.get("description") or "").strip() for e in entities) if d
        )

        try:
            import anthropic
            api_key = self.config.get("api_keys", {}).get("anthropic")
            if not api_key:
                raise RuntimeError("no key")
            client = anthropic.Anthropic(api_key=api_key)

            lines = []
            for e in entities:
                aliases = json.loads(e["aliases"]) if e.get("aliases") else []
                lines.append(
                    f"- name: {e['name']} | mentions: {e.get('mention_count') or 0}"
                    f" | aliases: {', '.join(aliases) if aliases else '(none)'}"
                    f" | description: {(e.get('description') or '(none)').strip()}"
                )
            prompt = (
                "These topic entities in a personal memory system are being merged into one.\n\n"
                + "\n".join(lines) +
                "\n\nPick which existing name should be the canonical name for the merged entity "
                "(prefer the most general, human-recognizable one) and write one merged description "
                "covering what the combined topic is — as much detail as the combined "
                "topics need, typically 1-3 sentences.\n\n"
                "Respond with ONLY a JSON object, no other text:\n"
                '{"canonical": "<one of the names above, exactly as written>", "description": "<merged description>"}'
            )
            response = client.messages.create(
                model="claude-haiku-4-5",
                max_tokens=300,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text.strip()
            # Tolerate accidental fencing
            if text.startswith("```"):
                text = text.strip("`")
                text = text[text.find("{"):text.rfind("}") + 1]
            parsed = json.loads(text[text.find("{"):text.rfind("}") + 1])
            canonical = parsed.get("canonical", "")
            valid_names = {e["name"] for e in entities}
            if canonical not in valid_names:
                # Case-insensitive rescue
                by_lower = {n.lower(): n for n in valid_names}
                canonical = by_lower.get(canonical.lower(), fallback["name"])
            description = (parsed.get("description") or fallback_desc).strip()
            return canonical, description
        except Exception as e:
            print(f"  [entity merge] Haiku arbiter unavailable ({e}) — most-mentioned entity wins")
            return fallback["name"], fallback_desc

    # =========================================================================
    # @help - Show available commands
    # =========================================================================

    def cmd_help(self, args: str) -> Dict:
        """
        Show available commands and usage.

        Args:
            args: Optional specific command to get help for

        Returns:
            dict: Help information
        """
        if args.strip():
            # Help for specific command
            command = args.strip().lower()
            help_text = self._get_command_help(command)
        else:
            # General help
            # Build dynamic help with current config values and system state
            retrieval_cfg = self.config.get("retrieval", {})
            context_cfg = self.config.get("context", {})
            model_cfg = self.config.get("model", {})
            entity_cfg = self.config.get("features", {}).get("entity_summaries", {})
            notes_cfg = self.config.get("features", {}).get("notes", {})

            # Count entities and concepts
            entity_count = 0
            if self.graph_db:
                try:
                    entity_count = len(self.graph_db.get_entity_stats(min_mentions=0))
                except Exception:
                    pass
            concept_count = len(self.db.get_all_concepts()) if hasattr(self.db, 'get_all_concepts') else 0
            note_count = len(self.db.get_all_notes()) if hasattr(self.db, 'get_all_notes') else 0
            message_count = self.db.get_message_count() if hasattr(self.db, 'get_message_count') else 0

            help_text = f"""
SYSTEM STATUS:
  Messages stored: {message_count}
  Entities: {entity_count}
  Concepts: {concept_count}
  Note sections: {note_count}

CURRENT CONFIGURATION (@config to change):
  temperature: {model_cfg.get('temperature', 1.0)}
  recent_messages_tokens: {context_cfg.get('recent_messages_tokens', 50000)}
  similarity_threshold: {retrieval_cfg.get('similarity_threshold', 0.25)}
  semantic_weight: {retrieval_cfg.get('semantic_weight', 0.4)}
  importance_weight: {retrieval_cfg.get('importance_weight', 0.4)}
  recency_weight: {retrieval_cfg.get('recency_weight', 0.2)}

TIPS & EDGE CASES:
  - @remember sets importance to 10.0 directly (max score)
  - @forget is two-step: preview first, then @forget confirm with IDs
  - @recall --deep searches messages older than {retrieval_cfg.get('deep_archive_age_months', 6)} months
  - @concept create/edit and @artifact use | as delimiter — no pipes in field values
  - @entity merge combines duplicate topics (human-only; see @help entity)
  - @run auto-imports os; DB_PATH, REPO_PATH, ARTIFACTS_PATH, SRC_PATH available via os.environ
  - @run is OS-sandboxed: read-only inputs, no network/children, disposable SCRATCH_PATH only
  - Use @artifact, not @run, for creative/technical work that should be saved
  - Entity summaries: {'enabled' if entity_cfg.get('enabled', False) else 'disabled'}
  - Notes budget: ~{notes_cfg.get('max_tokens', 5000)} tokens

Type @help [command] for detailed usage of a specific command.
"""

        return self._ok("help", help_text.strip(), {"content": help_text.strip()})

    def _get_command_help(self, command: str) -> str:
        """Get detailed help for specific command."""
        help_texts = {
            "remember": """
@remember [text]

Mark a message as high-importance (sets importance to 10.0).

USAGE MODES:
1. @remember              Mark YOUR last message (no args)
2. @remember [keyword]    Search for message with keyword and mark it
3. @remember self         (AI only) Mark AI's own response

Examples:
  @remember                              Mark your last message
  @remember important decision about crows   Find and mark that message
  @remember self                         (AI only) Mark own response
""",
            "recall": """
@recall [topic]
@recall --deep [topic]

Retrieve memories about a topic using semantic search.

Standard search looks in active/standard tiers (last 6 months).
Deep search includes deep archive (all time).

Automatically boosts importance of recalled memories (+2 points).

Examples:
  @recall crows
  @recall vulnerability moments
  @recall --deep our first conversation
""",
            "forget": """
@forget [topic]
@forget confirm [id1 id2 ...] or @forget confirm all

Two-step memory archival with preview.

Step 1: @forget [topic] — searches for matching memories using keyword + semantic
        scoring. Returns a numbered list with message IDs and short descriptions.
        Triggers continuation so you can review the list.

Step 2: @forget confirm [id1 id2 ...] — archives the selected messages.
        Or @forget confirm all to archive everything from the preview.

Archived memories move to deep_archive tier with halved importance.
Still retrievable with @recall --deep.

Examples:
  @forget outdated project details
  (review list, then)
  @forget confirm 234 456 789
  @forget confirm all
""",
            "entity": """
@entity [name]
@entity list
@entity view [name]
@entity merge [name1] | [name2] [| name3 ...]

Topic/person summaries the system tracks across conversations.

USAGE MODES:
1. @entity [name]            Force-include an entity in the next retrieval
2. @entity list              Show all known entities
3. @entity view [name]       Show a specific entity's summary
4. @entity merge a | b | c   Merge near-duplicate entities into one
                             (human-only; also available as tap-to-select
                             merge mode in the commands drawer)

MERGE BEHAVIOR:
Haiku picks the surviving canonical name from the given names and writes a
merged description. Message links repoint to the survivor, old summaries are
deleted (they rebuild automatically from the combined history on next
retrieval), and the absorbed names become aliases of the survivor so future
entity assignment redirects to it.

Examples:
  @entity River
  @entity view Sanni
  @entity merge grass_blockage | River_Health
""",
            "graph": """
@graph
@graph [entity]

Deprecated compatibility command. Use @entity list for overview and
@entity view [name] for details.

USAGE MODES:
1. @entity list              Show known entities
2. @entity view [entity]     Show a specific entity summary

Entities are people, topics, places, and recurring themes that the system
tracks across conversations. Each entity accumulates a summary over time.

SETUP:
Set features.entity_summaries.enabled=true in config. Entities are
discovered automatically during conversation.

Examples:
  @entity list
  @entity view consciousness
""",
            "note": """
@note <section_name>
<content>
@endnote

@note remove <section_name>
@note clear

INSTANCE-ONLY COMMAND (AI use only)

Manage persistent notes organized in named sections.
Notes persist across turns and conversations (stored in database).

Commands:
  @note <name>     Create/replace a note section (multi-line, ends with @endnote)
  @note remove <name>  Remove a section
  @note clear      Clear all notes

Examples:
  @note Preferences
  - Dark themes, minimal UI
  - Direct communication style
  @endnote

  @note remove Old Projects
  @note clear
""",
            "modify": """
@modify [msg_id] importance [score]

Modify memory importance score for retrieved memories.

USE CASES:
- Retrieved memory has inflated/inaccurate importance score
- Need to adjust importance based on new context

MESSAGE IDs:
Message IDs are shown in retrieved memories:
  [Memory ID: 123 | From: 2025-01-15T14:30:00Z]
  [Importance: 7.5/10]

Examples:
  @modify 123 importance 5.0          Set importance to 5.0/10
  @modify 456 importance 8.0          Boost importance to 8.0/10
""",
            "view": """
@view [msg_id]

View a specific message by ID with full metadata.

Shows complete message details:
- Timestamp and sender
- Importance score (X.X/10)
- Tier (active/standard/deep_archive)
- Full message content

USE CASES:
- Check if message stats were modified correctly
- Inspect retrieved memory details before modifying
- Verify importance after changes

MESSAGE IDs:
Message IDs are shown in retrieved memories section:
  [Memory ID: 123 | From: 2025-01-15T14:30:00Z]

Examples:
  @view 123     View complete details for message 123
  @view 456     Check current importance for message 456
""",
            "artifact": """
@artifact {category}/{slug} | title | tag1, tag2 | summary
<content in markdown>
@endartifact

INSTANCE-ONLY COMMAND (AI use only)

Save creative or technical work as a verified markdown file under the
profile's artifacts directory. Mneme verifies the written file and reports
the final path and byte size.

Use @artifact for files your human should keep. Do not use @run to create
artifact files.

Examples:
  @artifact technical/mneme-notes | Mneme Notes | mneme, notes | Working notes
  # Mneme Notes
  ...
  @endartifact
""",
            "run": """
@run
<python code>
@endrun

INSTANCE-ONLY COMMAND (AI use only)

Run short Python scripts for inspection: query the SQLite database, browse
artifacts/attachments, or inspect source files. Results are returned in a
continuation turn.

Use @run for querying only. It is not a file-creation/export tool; use
@artifact or a dedicated app export feature when your human needs a saved file.
Scripts time out after 10 seconds.
""",
            "config": """
@config [parameter] [value]

Adjust system settings.

Without arguments, shows current configuration.
With arguments, updates the specified parameter.

Instance can modify: temperature, retrieval weights, context tokens.
Other parameters require user approval.

Examples:
  @config
  @config temperature 1.2
  @config recent_messages_tokens 80000
  @config similarity_threshold 0.3
"""
        }

        return help_texts.get(command, f"No detailed help available for @{command}")

    # =========================================================================
    # @file - File attachment operations (Phase 7)
    # =========================================================================

    def cmd_file(self, args: str) -> Dict:
        """
        File attachment operations.

        Args:
            args: Sub-command and arguments

        Returns:
            dict: Command result

        USAGE:
        @file list                    List recent files with descriptions
        @file view [uuid]             View file content (RETRIEVAL - triggers continuation)
        @file search [query]          Search files by description/filename

        PHASE 7: File attachments with AI descriptions
        """
        files_config = self.config.get("features", {}).get("attachments", {})
        if not files_config.get("enabled", False):
            return self._err("file", "File attachments not enabled. Set features.attachments.enabled=true after running migration.")

        if not args.strip():
            return self._err("file", "Usage:\n@file list\n@file view [uuid]\n@file search [query]")

        # Parse sub-command
        parts = args.split(None, 1)
        sub_command = parts[0].lower()
        sub_args = parts[1] if len(parts) > 1 else ""

        if sub_command == "list":
            return self._file_list()
        elif sub_command == "view":
            return self._file_view(sub_args)
        elif sub_command == "search":
            return self._file_search(sub_args)
        else:
            return self._err("file", f"Unknown sub-command: {sub_command}. Use @file without arguments for usage.")

    def _file_list(self) -> Dict:
        """List recent files with descriptions."""
        attachments = self.db.get_recent_attachments(limit=20, with_description=False)

        if not attachments:
            return self._ok("file", "No files have been uploaded yet.", {"sub_command": "list", "content": "No files have been uploaded yet."})

        # Format list
        response = f"📁 {len(attachments)} FILE(S):\n\n"
        for att in attachments:
            uuid_short = att["uuid"][:8]
            filename = att["filename"]
            description = att.get("ai_description", "(no description)")
            if description and len(description) > 60:
                description = description[:57] + "..."
            status = "✓" if att.get("ai_description") else "⏳"
            response += f"{status} [{uuid_short}] {filename}\n"
            if description and description != "(no description)":
                response += f"   {description}\n"
            response += "\n"

        response += "Use @file view [uuid] to view a file in detail."

        return self._ok("file", response.strip(), {"sub_command": "list", "content": response.strip()})

    def _file_view(self, uuid_or_query: str) -> Dict:
        """
        View file content - RETRIEVAL COMMAND.

        This triggers a continuation call with the file content,
        allowing the AI to see and respond to the file.
        """
        if not uuid_or_query.strip():
            return self._err("file", "Usage: @file view [uuid]")

        # Try to find by UUID prefix
        uuid_prefix = uuid_or_query.strip()
        attachment = self.db.get_attachment_by_uuid(uuid_prefix)

        # If not found by exact match, try prefix search
        if not attachment:
            attachments = self.db.get_recent_attachments(limit=100, with_description=False)
            for att in attachments:
                if att["uuid"].startswith(uuid_prefix):
                    attachment = att
                    break

        if not attachment:
            return self._err("file", f"File not found: {uuid_prefix}")

        # Load file content for AI context
        if not self.file_processor:
            return self._err("file", "File processor not initialized")

        try:
            content_block = self.file_processor.load_for_context(attachment)

            # Format result for continuation
            return self._ok("file", f"📎 Loaded file: {attachment['filename']}", {
                "file_uuid": attachment["uuid"],
                "filename": attachment["filename"],
                "mime_type": attachment["mime_type"],
                "content_block": content_block,  # For multimodal message building
                "description": attachment.get("ai_description", ""),
                "is_retrieval": True  # Mark as retrieval command
            })

        except Exception as e:
            return self._err("file", f"Error loading file: {e}")

    def _file_search(self, query: str) -> Dict:
        """Search files by description or filename."""
        if not query.strip():
            return self._err("file", "Usage: @file search [query]")

        results = self.db.search_attachments_by_description(query.strip(), limit=10)

        if not results:
            return self._ok("file", f"No files found matching: {query}", {"sub_command": "search", "content": f"No files found matching: {query}"})

        # Format results
        response = f"🔍 Found {len(results)} file(s) matching '{query}':\n\n"
        for att in results:
            uuid_short = att["uuid"][:8]
            filename = att["filename"]
            description = att.get("ai_description", "(no description)")
            if description and len(description) > 60:
                description = description[:57] + "..."
            response += f"[{uuid_short}] {filename}\n"
            if description and description != "(no description)":
                response += f"   {description}\n"
            response += "\n"

        response += "Use @file view [uuid] to view a file."

        return self._ok("file", response.strip(), {"sub_command": "search", "content": response.strip()})

    def _sync_description_to_metadata(self, file_uuid: str, description: str):
        """Write ai_description into the attachment's metadata.json so @run scripts can see it."""
        if not self.file_processor:
            return
        metadata_path = Path(self.file_processor.attachments_dir) / file_uuid / "metadata.json"
        if not metadata_path.exists():
            return
        try:
            with open(metadata_path, "r", encoding="utf-8") as f:
                metadata = json.load(f)
            metadata["ai_description"] = description
            with open(metadata_path, "w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=2)
        except Exception:
            pass  # Non-critical — DB is the source of truth

    # =========================================================================
    # @describe - Create AI description for file (Phase 7)
    # =========================================================================

    def cmd_describe(self, args: str) -> Dict:
        """
        View a file and create/update its AI description.

        Args:
            args: UUID of file to describe, and optionally description text

        Returns:
            dict: Command result with file content for viewing
                  If description text provided, saves it directly

        USAGE:
        @describe [uuid]                      View file to create description
        @describe [uuid] | [description]      Set description directly

        PHASE 7: Instance-driven file descriptions
        """
        files_config = self.config.get("features", {}).get("attachments", {})
        if not files_config.get("enabled", False):
            return self._err("describe", "File attachments not enabled.")

        if not args.strip():
            # Show files needing descriptions
            undescribed = self.db.get_attachments_without_descriptions(limit=10)

            if not undescribed:
                return self._ok("describe", "All files have descriptions! Use @file list to see files.", {"empty": True})

            response = f"📎 {len(undescribed)} file(s) need descriptions:\n\n"
            for att in undescribed:
                uuid_short = att["uuid"][:8]
                response += f"  [{uuid_short}] {att['filename']}\n"

            response += "\nUse @describe [uuid] to view and describe a file."

            return self._ok("describe", response.strip())

        # Parse: @describe [uuid] [optional description]
        # UUID is first word, everything after is the description
        # Supports both space-separated and pipe-separated formats:
        #   @describe abc12345 Golden sunset over calm water
        #   @describe abc12345 | Golden sunset over calm water
        parts = args.strip().split(None, 1)  # Split on first whitespace
        uuid_prefix = parts[0].strip() if parts else ""
        description = parts[1].strip() if len(parts) > 1 else None

        # Also support pipe delimiter for backwards compatibility
        if description and description.startswith("|"):
            description = description[1:].strip()

        # Find attachment
        attachment = self.db.get_attachment_by_uuid(uuid_prefix)
        if not attachment:
            attachments = self.db.get_recent_attachments(limit=100, with_description=False)
            for att in attachments:
                if att["uuid"].startswith(uuid_prefix):
                    attachment = att
                    break

        if not attachment:
            return self._err("describe", f"File not found: {uuid_prefix}")

        # If description provided, save it directly
        if description:
            success = self.db.update_attachment(
                attachment_id=attachment["id"],
                ai_description=description
            )

            if success:
                # Sync description to metadata.json so @run scripts can find it
                self._sync_description_to_metadata(attachment["uuid"], description)
                return self._ok("describe", f"✓ Updated description for {attachment['filename']}")
            else:
                return self._err("describe", f"Failed to update description")

        # Otherwise, load file for viewing (retrieval command)
        if not self.file_processor:
            return self._err("describe", "File processor not initialized")

        try:
            content_block = self.file_processor.load_for_context(attachment)

            return self._ok("describe", f"📎 Viewing file for description: {attachment['filename']}", {
                "file_uuid": attachment["uuid"],
                "filename": attachment["filename"],
                "mime_type": attachment["mime_type"],
                "content_block": content_block,
                "current_description": attachment.get("ai_description", ""),
                "needs_description": True,
                "is_retrieval": True
            })

        except Exception as e:
            return self._err("describe", f"Error loading file: {e}")


    def cmd_artifact(self, args: str) -> Dict:
        """
        Save a creative or technical artifact to the filesystem.

        Called with the full block body already extracted by instance_executor's
        pre-pass (analogous to @note/@endnote).

        Args format (first line is header, rest is content):
            {category}/{slug} | title | tag1, tag2 | summary
            [artifact body in markdown]

        Example:
            @artifact poetry/2026-03-06_recipe-caramel | Caramel (Recipe as Poem) | recipe, constraint-poetry | Recipe as poem
            # Caramel
            ...
            @endartifact

        Returns:
            dict: Command result
        """
        if not self.artifact_storage:
            return self._err("artifact", "Artifact storage not initialized.")

        if not args.strip():
            return self._err("artifact",
                             "Usage:\n"
                             "@artifact {category}/{slug} | title | tag1, tag2 | summary\n"
                             "<content>\n"
                             "@endartifact")

        # Split header line from content body
        lines = args.split("\n", 1)
        header_line = lines[0].strip()
        content = lines[1].strip() if len(lines) > 1 else ""

        # Parse header: {category}/{slug} | title | tags | summary
        header_parts = [p.strip() for p in header_line.split("|")]
        if len(header_parts) < 4:
            return self._err("artifact",
                             "Header must have 4 pipe-separated parts: "
                             "{category}/{slug} | title | tags | summary")

        path_part = header_parts[0]
        title = header_parts[1]
        tags_raw = header_parts[2]
        summary = header_parts[3]

        # Parse category/slug
        if "/" not in path_part:
            return self._err("artifact", "Path must be {category}/{slug} (e.g. poetry/2026-03-06_recipe-caramel)")
        category, slug = path_part.split("/", 1)
        category = category.strip()
        slug = slug.strip()

        if not category or not slug:
            return self._err("artifact", "Both category and slug must be non-empty.")

        # Parse tags
        tags = [t.strip() for t in tags_raw.split(",") if t.strip()]

        try:
            saved_path = self.artifact_storage.save(
                category=category,
                slug=slug,
                title=title,
                summary=summary,
                tags=tags,
                content=content,
            )
        except Exception as e:
            return self._err("artifact", f"Failed to save artifact: {e}")

        try:
            saved_file = Path(saved_path)
            stat = saved_file.stat()
            size_bytes = stat.st_size
        except Exception as e:
            return self._err("artifact", f"Artifact write could not be verified: {e}")

        relative_path = f"{category}/{slug}/ARTIFACT.md"
        return self._ok("artifact", f"Artifact saved and verified: {relative_path} ({size_bytes} bytes)", {
            "path": saved_path,
            "relative_path": relative_path,
            "category": category,
            "slug": slug,
            "title": title,
            "verified": True,
            "size_bytes": size_bytes,
        })

    # =========================================================================
    # @run — Execute read-only Python code
    # =========================================================================

    def cmd_run(self, args: str) -> Dict:
        """
        Execute Python in a fail-closed Windows AppContainer for inspection.

        The repository, database snapshot, attachments, and artifacts are
        readable. Only disposable scratch storage is writable; network and
        child-process access are denied by the OS sandbox.

        Args:
            args: Python code body (extracted by instance_executor pre-pass)

        Returns:
            dict: Command result with stdout/stderr as retrieval data
        """
        if not args.strip():
            return self._err("run", "No code provided. Use @run\\n<python code>\\n@endrun")

        code = args.strip()
        if "import os" not in code:
            code = "import os\n" + code

        artifacts_dir = getattr(self.artifact_storage, "artifacts_dir", None)
        attachments_dir = getattr(self.file_processor, "attachments_dir", None)
        backend = AppContainerBackend(
            db_path=self.db.db_path,
            config=self.config,
            artifacts_path=artifacts_dir,
            attachments_path=attachments_dir,
        )

        try:
            result = backend.execute(code, timeout_seconds=10, memory_mb=256)
            if result.timed_out:
                return self._ok("run", "Script timed out after 10 seconds.", {
                    "is_retrieval": True,
                    "output": "",
                    "errors": "Script timed out after 10 seconds.",
                    "return_code": -1,
                })
            output = result.stdout
            errors = result.stderr

            # Truncate very long output
            max_len = 4000
            if len(output) > max_len:
                output = output[:max_len] + "\n[Output truncated...]"
            if len(errors) > max_len:
                errors = errors[:max_len] + "\n[Stderr truncated...]"

            combined = ""
            if output:
                combined += output
            if errors:
                combined += f"\n[stderr]\n{errors}"
            if not combined.strip():
                combined = "(no output)"

            return self._ok("run", combined.strip(), {
                "is_retrieval": True,
                "output": output,
                "errors": errors,
                "return_code": result.return_code,
            })

        except SandboxUnavailable as e:
            return self._ok("run", str(e), {
                "is_retrieval": True,
                "output": "",
                "errors": str(e),
                "return_code": -1,
            })
        except Exception as e:
            # Fail closed: never retry with an ordinary Python subprocess.
            message = f"Sandbox execution failed safely: {e}"
            return self._ok("run", message, {
                "is_retrieval": True,
                "output": "",
                "errors": message,
                "return_code": -1,
            })

if __name__ == "__main__":
    """
    Test the command handler.
    """
    print("Command System module loaded successfully!")
    print("\nImplemented commands:")
    print("  ✓ @remember - Mark high-importance (set to 10.0)")
    print("  ✓ @recall - Retrieve memories (+2 importance)")
    print("  ✓ @forget - Archive and reduce importance")
    print("  ✓ @modify - Modify memory importance")
    print("  ✓ @view - View message by ID")
    print("  ✓ @config - Adjust settings (instance autonomy)")
    print("  ✓ @entity - Entity summaries")
    print("  ✓ @concept - Manage concepts")
    print("  ✓ @file - File attachments")
    print("  ✓ @help - Show command help")
    print("\nTo use:")
    print("  from commands import CommandHandler")
    print("  handler = CommandHandler(db, embedder, config, background_queue)")
    print("  result = handler.handle_command('@remember important moment')")
