"""
Prompt Builder Module for Mneme Memory System

Handles all prompt construction for AI API calls:
- System instructions loading from file
- Prompt section assembly (datetime, memories, concepts, graph, cache status)
- Cached message structure building (proper Anthropic format)
- Concept extraction reminder generation

DESIGN:
- Separates prompt construction from caching decisions (handled by PromptCacheManager)
- Separates prompt construction from API calls (handled by AIClient)
- Single responsibility: build prompts in the correct format

USAGE:
    builder = PromptBuilder(config, database, cache_manager)
    sections = builder.build_sections(context, current_input)
    cached_structure = builder.build_cached_structure(sections, conversation_history, current_input)
"""

from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any


class PromptBuilderError(Exception):
    """Custom exception for prompt builder errors."""
    pass


class PromptBuilder:
    """
    Builds prompts for AI API calls.

    This class handles:
    - Loading system instructions from file
    - Building individual prompt sections (datetime, memories, etc.)
    - Assembling cached message structures for Anthropic API
    - Generating concept extraction reminders (Phase 6)
    """

    def __init__(self, config: Dict, database=None, cache_manager=None):
        """
        Initialize prompt builder.

        Args:
            config: Configuration dictionary
            database: Database instance (for concept queries)
            cache_manager: PromptCacheManager instance (for cache status display)
        """
        self.config = config
        self.db = database
        self.cache_manager = cache_manager

        # Template variables for system instructions
        self.max_instance_iterations = config.get("commands", {}).get("max_iterations", 6)
        self.instance_name = (
            config.get("identity", {}).get("instance_name", "")
            or config.get("storage", {}).get("active_profile", "")
            or "Claude"
        )

        # Concept extraction settings
        concepts_config = config.get("features", {}).get("concepts", {})
        self.concept_auto_extract_enabled = concepts_config.get("auto_extract", True)
        self.concept_extract_frequency = concepts_config.get("auto_extract_frequency", 40)
        self.concept_min_words = concepts_config.get("auto_extract_min_words", 100)
        self.concept_max_words = concepts_config.get("auto_extract_max_words", 500)

        # File description settings
        files_config = config.get("features", {}).get("attachments", {})
        self.files_enabled = files_config.get("enabled", False)
        self.describe_reminder_enabled = files_config.get("describe_reminder", True)

        # Notes cleanup settings
        notes_config = config.get("features", {}).get("notes", {})
        self.notes_enabled = notes_config.get("enabled", True)
        self.notes_cleanup_interval = notes_config.get("cleanup_interval_messages", 50)

        # Timeline settings
        timeline_config = config.get("features", {}).get("timeline", {})
        self.timeline_enabled = timeline_config.get("enabled", False)

        # System instructions: check per-profile first, fall back to global
        db_dir = Path(config["storage"]["database_path"]).parent
        profile_instructions = db_dir / "system_instructions.txt"
        if profile_instructions.exists():
            self.instructions_path = profile_instructions
        else:
            self.instructions_path = Path(__file__).parent.parent.parent / "system_instructions.txt"

    # =========================================================================
    # Main API
    # =========================================================================

    def build_sections(self, context: Dict, current_input: str) -> Dict:
        """
        Build individual prompt sections for caching.

        Args:
            context: Assembled context from ContextAssembler
            current_input: Current user message

        Returns:
            dict: {
                "system": str,      # System instructions
                "timeline": str,    # Timeline (7-day summaries) - Phase 9
                "recent": str,      # Recent conversation
                "datetime": str,    # Current date/time/weekday
                "retrieved": str,   # Retrieved memories
                "notes": str,       # AI notes (Phase 11)
                "concept": str,     # Concept context (Phase 6)
                "graph": str,       # Graph context (Phase 5)
                "cache": str,       # Cache status from previous message
                "current": str,     # Current message
                "full_prompt": str  # Combined (for non-cached fallback)
            }
        """
        sections = {}

        # System instructions (Layer 1 - cacheable)
        sections["system"] = self.get_system_instructions()

        # Timeline (7-day summaries) - Phase 9 (cacheable, changes once per day)
        sections["timeline"] = context.get("timeline_context", "") or ""

        # Recent conversation (Layer 2 - cacheable)
        sections["recent"] = self._build_recent_section(context)

        # Current datetime (uncached)
        sections["datetime"] = self._build_datetime_section()

        # Retrieved memories (uncached)
        sections["retrieved"] = self._build_retrieved_section(context)

        # AI Notes (uncached) - Phase 11
        sections["notes"] = self._build_notes_section(context)

        # Concept context (uncached) - Phase 6
        sections["concept"] = context.get("concept_context", "") or ""

        # Files context (uncached) - Phase 7
        sections["files"] = context.get("files_context", "") or ""

        # Entity summaries (uncached) - Phase 8
        sections["entity_summaries"] = context.get("entity_summaries_context", "") or ""

        # Cache status (uncached)
        sections["cache"] = self._build_cache_status_section()

        # Current message (uncached)
        user_msg_id = context.get("user_msg_id", "")
        ai_msg_id = context.get("ai_msg_id", "")
        user_id_prefix = f"[ID:{user_msg_id}] " if user_msg_id else ""
        ai_id_note = f"\n[Your response will be stored as message ID: {ai_msg_id}]" if ai_msg_id else ""
        sections["current"] = f"\n\n=== CURRENT MESSAGE ===\n{user_id_prefix}user: {current_input}{ai_id_note}"

        # Full prompt for non-cached fallback
        sections["full_prompt"] = self._build_full_prompt(sections)

        return sections

    def build_cached_structure(
        self,
        sections: Dict,
        conversation_history: List[Dict],
        current_input: str,
        concept_reminder: Optional[str] = None,
        attachment_blocks: Optional[List[Dict]] = None,
        describe_reminder: Optional[str] = None,
        history_attachments: Optional[Dict[int, List[Dict]]] = None
    ) -> Dict:
        """
        Build proper multi-turn message structure with caching.

        Args:
            sections: Sections from build_sections()
            conversation_history: List of {"sender": "user/assistant", "content": "..."}
            current_input: Current user message
            concept_reminder: Optional concept extraction reminder (Phase 6)
            attachment_blocks: Optional list of content blocks for file attachments (Phase 7)
            describe_reminder: Optional file description reminder (Phase 7)
            history_attachments: Optional dict of msg_id -> attachment blocks for history (Phase 7)

        Returns:
            dict: {
                "tools": [],        # Empty for now, ready for MCP (Phase 2)
                "system": [...],    # System blocks
                "messages": [...]   # Multi-turn conversation with cache_control
            }

        PROPER FORMAT (per Anthropic docs):
        tools=[],
        system=[{"type": "text", "text": "..."}],
        messages=[
            {"role": "user", "content": "..."},
            {"role": "assistant", "content": "..."},
            {"role": "user", "content": [
                {"type": "text", "text": "...", "cache_control": {"type": "ephemeral"}}
            ]}  # Cache on LAST user turn
        ]

        CACHING STRATEGY (Nov 2025):
        - Cache breakpoint: Last USER message (not last assistant)
        - Retrieval blocks appear in assistant's "working memory" section
        - Last assistant response (~500-1000 tokens) becomes uncached
        - Benefit: Retrieval blocks appear as "AI's internal notes" not "user instructions"
        """
        attachment_blocks = attachment_blocks or []
        history_attachments = history_attachments or {}

        # System blocks with optional timeline (Phase 9)
        # Timeline merged into system text (separate cache_control blocks cause API issues)
        system_text = sections["system"]
        if sections.get("timeline"):
            system_text = system_text + "\n\n" + sections["timeline"]

        system_blocks = [{
            "type": "text",
            "text": system_text
        }]

        # Build messages array from conversation history
        messages = []

        # Filter out temporary command results
        filtered_messages = [
            msg for msg in conversation_history
            if not msg.get("temporary", False)
        ]

        # Separate last assistant response from history (will be used in uncached section)
        last_assistant_response = None
        if len(filtered_messages) > 0 and filtered_messages[-1]["sender"] == "assistant":
            last_assistant_response = filtered_messages[-1]["content"]
            messages_to_cache = filtered_messages[:-1]
        else:
            messages_to_cache = filtered_messages

        # Find the last user message for cache_control placement
        last_user_idx = -1
        for i in range(len(messages_to_cache) - 1, -1, -1):
            if messages_to_cache[i]["sender"] == "user":
                last_user_idx = i
                break

        # Build cached historical messages
        for i, msg in enumerate(messages_to_cache):
            # Map sender to valid Anthropic API role
            role = "assistant" if msg["sender"] == "system" else msg["sender"]

            # Check if this message has attachments (Phase 7)
            # Only include attachments for user messages — the Anthropic API
            # rejects image blocks inside assistant turns.
            msg_id = msg.get("id")
            msg_attachments = history_attachments.get(msg_id, []) if msg_id and role == "user" else []

            # For last user message, add cache_control
            if i == last_user_idx:
                # Build content blocks
                content_blocks = []
                # Add attachments first (images before text)
                if msg_attachments:
                    content_blocks.extend(msg_attachments)
                # Add text with cache_control on last block
                content_blocks.append({
                    "type": "text",
                    "text": msg["content"],
                    "cache_control": {"type": "ephemeral", "ttl": "1h"}
                })
                messages.append({
                    "role": role,
                    "content": content_blocks
                })
            elif msg_attachments:
                # Message with attachments - need content blocks
                content_blocks = list(msg_attachments)  # Copy to avoid mutation
                content_blocks.append({
                    "type": "text",
                    "text": msg["content"]
                })
                messages.append({
                    "role": role,
                    "content": content_blocks
                })
            else:
                # Regular message without attachments (no cache_control)
                messages.append({
                    "role": role,
                    "content": msg["content"]
                })

        # Build UNCACHED assistant message with retrieval blocks
        assistant_blocks = self._build_assistant_working_memory_blocks(
            last_assistant_response,
            sections
        )

        # Add assistant message with all blocks (only if there's content)
        if assistant_blocks:
            messages.append({
                "role": "assistant",
                "content": assistant_blocks
            })

        # Add current user message (with optional concept reminder and attachments)
        user_blocks = []
        if concept_reminder:
            user_blocks.append({
                "type": "text",
                "text": concept_reminder
            })

        # Add attachment content blocks (Phase 7) - images/files go before text
        if attachment_blocks:
            user_blocks.extend(attachment_blocks)

        # Add user's text message
        if current_input:
            user_blocks.append({
                "type": "text",
                "text": current_input
            })

        # Add file description reminder (Phase 7) - after user message
        if describe_reminder:
            user_blocks.append({
                "type": "text",
                "text": describe_reminder
            })

        messages.append({
            "role": "user",
            "content": user_blocks
        })

        return {
            "tools": [],  # Empty for now, ready for MCP
            "system": system_blocks,
            "messages": messages
        }

    def build_full_prompt(self, context: Dict, current_input: str) -> str:
        """
        Build complete prompt for AI including context.

        Args:
            context: Assembled context from ContextAssembler
            current_input: Current user message

        Returns:
            str: Complete prompt

        NOTE: For cached calls, use build_sections() + build_cached_structure() instead.
        """
        sections = self.build_sections(context, current_input)
        return sections["full_prompt"]

    # =========================================================================
    # System Instructions
    # =========================================================================

    def get_system_instructions(self) -> str:
        """
        Get system instructions for AI from external file.

        Returns:
            str: System prompt with variables replaced

        Loads from system_instructions.txt in project root and replaces:
        - {max_iterations} with actual configured value
        - {instance_name} with the AI's configured name
        """
        try:
            instructions = self.instructions_path.read_text(encoding='utf-8')
            # Replace template variables
            instructions = instructions.replace("{max_iterations}", str(self.max_instance_iterations))
            instructions = instructions.replace("{instance_name}", self.instance_name)
            return instructions
        except FileNotFoundError:
            # Fallback to basic instructions if file missing
            return self._get_fallback_instructions()

    def _get_fallback_instructions(self) -> str:
        """Get fallback system instructions if system_instructions.txt is missing.

        This should not normally be reached — copy system_instructions.example.txt
        to system_instructions.txt in the project root.
        """
        return """You are an AI assistant with access to a persistent memory system.

Available commands:
- @recall [query] - Search memories
- @remember {id} - Mark a message as high-importance
- @forget [topic] - Archive memories about a topic
- @note {section}\\n{content}\\n@endnote - Create or update a persistent note section
- @graph [entity] - Query knowledge graph
- @concept list - List narrative concepts
- @concept [action] - Manage narrative concepts

Respond naturally and use commands when helpful."""

    # =========================================================================
    # Concept Extraction (Phase 6)
    # =========================================================================

    def should_trigger_concept_check(self, messages_since_check: int) -> bool:
        """
        Determine if we should prompt for concept extraction.

        Args:
            messages_since_check: Messages since last concept check

        Returns:
            bool: True if it's time to check for new concepts
        """
        if not self.concept_auto_extract_enabled or self.concept_extract_frequency <= 0:
            return False
        return messages_since_check >= self.concept_extract_frequency

    def generate_concept_reminder(self, messages_since_check: int) -> str:
        """
        Generate ephemeral reminder message for concept extraction.

        This message is injected into the API call but NOT saved to database.

        Args:
            messages_since_check: Messages since last concept check

        Returns:
            str: Formatted reminder message
        """
        # Get existing concepts
        if self.db:
            concepts = self.db.get_all_concepts()
            concept_names = [c["name"] for c in concepts] if concepts else []
        else:
            concept_names = []

        # Format concept list
        if concept_names:
            concept_list = "\n".join(f"  - {name}" for name in sorted(concept_names))
            existing_note = f"Existing concepts in database:\n{concept_list}\n\n"
        else:
            existing_note = "No concepts have been created yet.\n\n"

        # Build reminder message
        reminder = f"""🔔 AUTOMATED CONCEPT EXTRACTION REMINDER

This is your periodic reminder ({messages_since_check} messages since last check) to identify any new narrative concepts that have emerged in recent conversation.

{existing_note}INSTRUCTIONS:
1. Review the last {self.concept_extract_frequency} messages for recurring themes, patterns, or significant topics
2. Identify concepts that:
   - Represent important narrative themes or experiential patterns
   - Would help you understand similar situations in future conversations
   - Are not already covered by existing concepts
3. For each new concept, use the @concept create command with this format:
   @concept create [concept_name] | [keyword1, keyword2, keyword3] | [definition]

REQUIREMENTS:
- Definitions should be {self.concept_min_words}-{self.concept_max_words} words
- Include 3-7 trigger keywords for detection
- Focus on interpretive understanding, not just facts
- Only create concepts if they genuinely emerged; it's fine if none did

IMPORTANT: This reminder is for your awareness only. Respond normally to the user's message, and create concepts using @concept create if appropriate. The concepts will persist across conversations to help you recognize similar patterns."""

        return reminder

    # =========================================================================
    # Notes Cleanup Reminder (Phase 11)
    # =========================================================================

    def should_trigger_notes_cleanup(self, messages_since_check: int) -> bool:
        """
        Determine if we should inject a periodic notes cleanup reminder.

        Args:
            messages_since_check: Messages since last notes cleanup check

        Returns:
            bool: True if it's time to remind about notes maintenance
        """
        if not self.notes_enabled or self.notes_cleanup_interval <= 0:
            return False
        return messages_since_check >= self.notes_cleanup_interval

    def generate_notes_cleanup_reminder(self, messages_since_check: int) -> str:
        """
        Generate periodic reminder for notes maintenance.

        Injected into the API call but NOT saved to database.

        Args:
            messages_since_check: Messages since last check

        Returns:
            str: Formatted reminder message
        """
        return f"""📝 PERIODIC NOTES MAINTENANCE REMINDER

This is your periodic reminder ({messages_since_check} messages since last check) to review and maintain your notes.

INSTRUCTIONS:
1. Review your current notes in the AI NOTES section above
2. Remove sections that are no longer relevant with @note remove <section>
3. Condense verbose sections by rewriting them with @note <section>...@endnote
4. Add any new persistent information you've learned recently

IMPORTANT: This reminder is for your awareness only. Respond normally to the user's message first. Notes maintenance is secondary."""

    # =========================================================================
    # File Description Reminder (Phase 7)
    # =========================================================================

    def should_trigger_describe_check(self) -> bool:
        """
        Determine if we should prompt for file description.

        Returns:
            bool: True if there are files needing descriptions
        """
        if not self.files_enabled or not self.describe_reminder_enabled:
            return False

        if not self.db:
            return False

        # Check if there are files without descriptions
        undescribed = self.db.get_attachments_without_descriptions(limit=1)
        return len(undescribed) > 0

    def generate_describe_reminder(self) -> str:
        """
        Generate ephemeral reminder message for file description.

        This message is injected into the API call but NOT saved to database.

        Returns:
            str: Formatted reminder message, or empty string if no files need descriptions
        """
        if not self.db:
            return ""

        # Get files without descriptions
        undescribed = self.db.get_attachments_without_descriptions(limit=5)
        if not undescribed:
            return ""

        # Build file list
        file_list = []
        for attachment in undescribed:
            uuid_short = attachment["uuid"][:8]
            filename = attachment["filename"]
            mime_type = attachment["mime_type"]
            file_list.append(f"  - [{uuid_short}] {filename} ({mime_type})")

        # Build reminder message
        reminder = f"""📎 FILE DESCRIPTION REMINDER

You have {len(undescribed)} file(s) that need descriptions for future retrieval:

{chr(10).join(file_list)}

INSTRUCTIONS:
1. Use @describe [uuid] to view each file and create a description
2. Descriptions should be 1-3 sentences capturing what the file contains
3. Focus on content that would help you find this file later
4. For images: describe what's visible, including objects, people, setting, mood
5. For text/documents: summarize the main topic and key information

IMPORTANT: This reminder is for your awareness. If the current conversation relates to any of these files, consider describing them now. Otherwise, you can describe them when relevant."""

        return reminder

    # =========================================================================
    # Section Builders (Private)
    # =========================================================================

    def _build_recent_section(self, context: Dict) -> str:
        """Build recent conversation section."""
        if not context.get("recent_context"):
            return ""

        parts = ["\n\n=== RECENT CONVERSATION ==="]
        for msg in context["recent_context"]:
            msg_id = msg.get("id", "")
            id_prefix = f"[ID:{msg_id}] " if msg_id else ""
            parts.append(f"\n{id_prefix}{msg['sender']}: {msg['content']}")
        return "\n".join(parts)

    def _build_datetime_section(self) -> str:
        """Build current date/time/weekday section."""
        now = datetime.now()
        parts = [
            "\n\n" + "=" * 70,
            "📅 CURRENT DATE AND TIME",
            "=" * 70,
            f"\nDate: {now.strftime('%Y-%m-%d')}",
            f"Time: {now.strftime('%H:%M:%S')}",
            f"Weekday: {now.strftime('%A')}",
            "=" * 70 + "\n"
        ]
        return "\n".join(parts)

    def _build_retrieved_section(self, context: Dict) -> str:
        """Build retrieved memories section."""
        if context.get("retrieved_memories"):
            parts = [
                "\n\n" + "=" * 70,
                "📚 RETRIEVED MEMORIES",
                "=" * 70,
                "\nMemories from past conversations that might be relevant:\n"
            ]

            for memory in context["retrieved_memories"]:
                parts.append(f"\n[Memory ID: {memory['id']} | From: {memory['timestamp']}]")
                parts.append(f"{memory['sender']}: {memory['content']}")
                if memory.get("importance") is not None:
                    parts.append(f"[Importance: {memory['importance']:.1f}/10]")

            parts.extend([
                "\n" + "=" * 70,
                "END OF RETRIEVED MEMORIES",
                "=" * 70 + "\n"
            ])
        else:
            parts = [
                "\n\n" + "=" * 70,
                "📚 NO MEMORIES RETRIEVED",
                "=" * 70,
                "\nNo relevant memories found for this query.",
                "=" * 70 + "\n"
            ]

        return "\n".join(parts)

    def _build_notes_section(self, context: Dict) -> str:
        """Build AI notes section (Phase 11)."""
        if not context.get("notes_context"):
            return ""

        parts = [
            "\n\n" + "=" * 70,
            context["notes_context"],
            "=" * 70 + "\n"
        ]

        return "\n".join(parts)

    def _build_cache_status_section(self) -> str:
        """Build cache status section (from previous message)."""
        if not self.cache_manager:
            return ""

        cache_stats = self.cache_manager.get_statistics()
        last_msg_cache = self.cache_manager.last_message_cache

        # Only show if we have data (at least one message processed)
        if cache_stats.get("total_messages", 0) == 0:
            return ""

        parts = [
            "\n\n" + "=" * 70,
            "💾 CACHE STATUS (FROM PREVIOUS MESSAGE)",
            "=" * 70,
            "\nNOTE: This shows caching performance from the PREVIOUS message.",
            "Current message's cache status will be available next turn.\n"
        ]

        # Last message specific status
        status = last_msg_cache.get("status", "unknown")
        if status == "not_active":
            parts.append("Previous message: Cache NOT ACTIVE (cold start)")
        elif status == "cold_start":
            parts.append("Previous message: Cache COLD START (wrote cache)")
            parts.append(f"  ↳ Wrote: {last_msg_cache.get('cache_write_tokens', 0):,} tokens")
        elif status == "active":
            parts.append("Previous message: Cache ACTIVE (hit)")
            parts.append(f"  ↳ Read: {last_msg_cache.get('cache_read_tokens', 0):,} tokens")
            if last_msg_cache.get('cache_write_tokens', 0) > 0:
                parts.append(f"  ↳ Wrote: {last_msg_cache.get('cache_write_tokens', 0):,} tokens")
        else:
            parts.append(f"Previous message: Status {status}")

        parts.append("")  # Blank line

        # Overall session statistics
        parts.extend([
            f"Session cache hit rate: {cache_stats.get('cache_hit_rate', 0):.1%}",
            f"Session totals: {cache_stats.get('cache_hits', 0)} hits | {cache_stats.get('cache_writes', 0)} writes | {cache_stats.get('cold_starts', 0)} cold starts",
            f"Total messages: {cache_stats.get('total_messages', 0)}",
            f"Cost savings: ${cache_stats.get('savings', 0):.4f} ({cache_stats.get('savings_percent', 0):.1f}% saved)",
            "=" * 70 + "\n"
        ])

        return "\n".join(parts)

    def _build_full_prompt(self, sections: Dict) -> str:
        """Build full prompt from sections (for non-cached fallback)."""
        full_parts = [sections["system"]]

        # Timeline (Phase 9) - comes right after system instructions
        if sections.get("timeline"):
            full_parts.append(sections["timeline"])
        if sections.get("recent"):
            full_parts.append(sections["recent"])
        if sections.get("notes"):
            full_parts.append(sections["notes"])
        if sections.get("retrieved"):
            full_parts.append(sections["retrieved"])
        if sections.get("concept"):
            full_parts.append(sections["concept"])
        if sections.get("files"):
            full_parts.append(sections["files"])
        if sections.get("entity_summaries"):
            full_parts.append(sections["entity_summaries"])
        if sections.get("cache"):
            full_parts.append(sections["cache"])
        full_parts.append(sections["current"])

        return "\n".join(full_parts)

    def _build_assistant_working_memory_blocks(
        self,
        last_assistant_response: Optional[str],
        sections: Dict
    ) -> List[Dict]:
        """
        Build assistant's working memory blocks for uncached section.

        Args:
            last_assistant_response: Last assistant response (if any)
            sections: Prompt sections dict

        Returns:
            List of content blocks for assistant message
        """
        blocks = []

        # Start with last assistant response (if exists)
        if last_assistant_response:
            blocks.append({
                "type": "text",
                "text": last_assistant_response
            })

        # Check if we have any working memory content
        has_working_memory = any([
            sections.get("datetime"),
            sections.get("notes"),
            sections.get("retrieved"),
            sections.get("concept"),
            sections.get("files"),
            sections.get("graph"),
            sections.get("entity_summaries"),
            sections.get("cache")
        ])

        # Add separator between response and working memory
        if last_assistant_response and has_working_memory:
            blocks.append({
                "type": "text",
                "text": "\n\n--- AI's Internal Working Memory for This Turn ---\n(The following are not part of my response to you, but rather context I've retrieved for processing your message)\n"
            })

        # Add working memory sections
        for key in ["datetime", "notes", "retrieved", "concept", "files", "graph", "entity_summaries", "cache"]:
            if sections.get(key):
                blocks.append({
                    "type": "text",
                    "text": sections[key]
                })

        # End of working memory section
        if last_assistant_response and has_working_memory:
            blocks.append({
                "type": "text",
                "text": "\n--- End of Internal Working Memory ---\n"
            })

        return blocks


if __name__ == "__main__":
    """
    Test the prompt builder.
    """
    print("Prompt Builder loaded successfully!")
    print("\nFeatures:")
    print("  ✓ System instructions loading from file")
    print("  ✓ Prompt section building (datetime, memories, concepts, graph)")
    print("  ✓ Cached message structure (proper Anthropic format)")
    print("  ✓ Concept extraction reminders (Phase 6)")
    print("  ✓ Cache status display")
    print("\nTo use:")
    print("  from prompt_builder import PromptBuilder")
    print("  builder = PromptBuilder(config, database, cache_manager)")
    print("  sections = builder.build_sections(context, user_input)")
