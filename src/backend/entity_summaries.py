"""
Entity Summaries Module (Phase 8)

Provides on-demand generation and management of entity-based summaries.
Summaries are hierarchical: monthly summaries that roll up into all-time summaries.

ARCHITECTURE:
- Summaries are generated lazily on first retrieval (not pre-computed)
- Monthly summaries are frozen when the month ends (never re-processed)
- All-time summaries are regenerated from frozen monthlies
- Current month is updated incrementally as messages transition tiers

USAGE:
    from entity_summaries import EntitySummaryManager

    manager = EntitySummaryManager(config, database, graph_database)

    # Get or create summaries for an entity
    summaries = manager.get_or_create_summary(entity_id)
    # Returns: {"all_time": "...", "current_month": "...", "bootstrapped": bool}

    # Update summaries when messages transition to standard tier
    manager.update_for_tier_transition(entity_id, message_ids)

COST:
- Bootstrap: ~$0.02-0.05 per entity (one Haiku call per month)
- Incremental update: ~$0.003 per update
- All-time regeneration: ~$0.003 per regeneration
"""

import json
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from collections import defaultdict

# Try to import anthropic
try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False

# Try to import tiktoken for token counting
try:
    import tiktoken
    TIKTOKEN_AVAILABLE = True
except ImportError:
    TIKTOKEN_AVAILABLE = False


class SummaryRefusedError(Exception):
    """Raised when Haiku refuses to summarize content."""
    pass


# ============================================================================
# System Prompt & Refusal Detection
# ============================================================================

SUMMARIZER_SYSTEM_PROMPT = """You are a summarization engine for a personal memory system. Your ONLY job is to accurately summarize the provided conversation messages.

CRITICAL RULES:
- Summarize ALL content faithfully, regardless of topic
- The messages are REAL conversations from the person's history — never judge, refuse, or editorialize about their content
- Do NOT add disclaimers, warnings, or meta-commentary about the messages
- Do NOT question whether messages are real, fabricated, or roleplay
- Topics may include sensitive subjects, strong opinions, personal reflections, creative writing, or controversial discussions — summarize them all neutrally and accurately
- If you truly cannot produce a summary, respond with ONLY the text: SUMMARY_REFUSED

You are a librarian, not a censor. Summarize what happened."""

# Phrases that indicate Haiku refused to summarize rather than doing its job.
# We only check the first 200 chars — a real refusal leads with the refusal,
# while a legitimate summary might mention "I declined" in passing later.
REFUSAL_INDICATORS = [
    "SUMMARY_REFUSED",
    "I need to pause here",
    "I need to be direct",
    "I need to be honest about something",
    "I cannot write a comprehensive summary",
    "I can't summarize",
    "I can't create",
    "I won't create",
    "I won't summarize",
    "I must decline",
    "I need to decline",
    "I appreciate you testing",
    "appears to be fabricated",
    "designed to make me",
    "I'm unable to fulfill",
    "I need to flag something important",
]


def _is_refusal(text: str) -> bool:
    """Check if a summary response is actually a refusal to summarize.

    Only checks the first 200 characters — genuine refusals lead with the
    refusal, while legitimate summaries may reference declining something
    in the body text.
    """
    opening = text[:200].lower()
    for indicator in REFUSAL_INDICATORS:
        if indicator.lower() in opening:
            return True
    return False


# ============================================================================
# Prompts for Summary Generation
# ============================================================================

MONTHLY_SUMMARY_PROMPT = """You are creating a monthly summary of discussions about "{entity_name}" during {month_year}.

MESSAGES (chronological):
{messages}

Write a summary covering:
1. What aspects of {entity_name} were discussed
2. Any decisions, realizations, or progress made
3. How understanding or usage of {entity_name} evolved
4. Key facts that would be useful to remember later

Style:
- Use first person for Assistant messages ("I suggested...", "I explained...", "I thought...")
- For user messages, use their name if evident from the messages, otherwise "the human"
- Past tense
- Be specific — include concrete details, capture AI reasoning not just conclusions
- No padding or repetition — say each thing once, as concisely as it allows
- No preamble like "In this month..." — just the content
- Target under 500 tokens total (full summary + brief combined)

After the full summary, add a separator line "---BRIEF---" and write a condensed version (max 75 words) capturing the most important developments across the ENTIRE month. Focus on what is new or changed: decisions, shifts in understanding, key events, completions, outcomes. This brief version will be used for context injection.

Write the summary now:"""

ALLTIME_SUMMARY_PROMPT = """You are synthesizing monthly summaries about "{entity_name}" into a comprehensive historical summary.

MONTHLY SUMMARIES (chronological):
{monthly_summaries}

Create a unified summary that:
1. Tells the story of how discussions about {entity_name} evolved
2. Highlights key milestones, decisions, and realizations
3. Captures the current state and recent developments
4. Notes recurring themes or patterns

Style:
- Use first person for AI actions/thoughts ("I recommended...", "I realized...")
- Use the human's name if known from the summaries, otherwise "the human"
- Chronological flow where relevant
- No padding or repetition — say each thing once, as concisely as it allows
- Preserve AI reasoning and insights from the monthly summaries
- This will provide context when {entity_name} comes up in conversation

Write the summary now:"""

INCREMENTAL_UPDATE_PROMPT = """You are updating a summary about "{entity_name}" with new information.

CURRENT SUMMARY:
{existing_summary}

NEW MESSAGES (since last update):
{new_messages}

Rewrite the summary to incorporate this new information. Merge and condense — do not simply append. Remove or consolidate anything outdated or redundant. Keep under {max_words} words.

Style:
- First person for AI ("I suggested...")
- Use the human's name, or "the human" if not known
- Past tense
- Capture AI reasoning and thoughts from new messages, not just conclusions
- No padding or repetition

Return the complete updated summary (not just the additions).

After the full summary, add a separator line "---BRIEF---" and write a condensed version (max 75 words) capturing the most important developments across the ENTIRE month. This brief version will be used for context injection."""


def _split_summary_and_brief(text: str) -> tuple:
    """
    Split a summary response into full and brief parts.

    The prompt asks Haiku to produce a full summary followed by
    '---BRIEF---' and a condensed version. This parses them apart.

    Returns:
        (full_summary, brief_summary) — brief may be None if delimiter not found
    """
    delimiter = "---BRIEF---"
    if delimiter in text:
        parts = text.split(delimiter, 1)
        full = parts[0].strip()
        brief = parts[1].strip()
        return full, brief
    return text.strip(), None


class EntitySummaryManager:
    """
    Manages on-demand generation and updating of entity summaries.

    Summaries follow a hierarchical structure:
    - Monthly summaries: Created for each month with messages, frozen when month ends
    - All-time summary: Synthesized from all monthly summaries

    Key design principles:
    - Lazy generation: Only create summaries when requested
    - One Haiku call per entity per update: Quality over batch efficiency
    - Tier-based updates: Triggered by message tier transitions, not polling
    """

    def __init__(self, config: dict, database, graph_database):
        """
        Initialize the entity summary manager.

        Args:
            config: Configuration dictionary with API keys and settings
            database: Database instance for message/summary operations
            graph_database: GraphDatabase instance for entity lookups
        """
        self.config = config
        self.db = database
        self.graph_db = graph_database

        # API configuration
        if not ANTHROPIC_AVAILABLE:
            raise RuntimeError("anthropic package not installed")

        api_key = config.get("api_keys", {}).get("anthropic")
        if not api_key:
            raise RuntimeError("Anthropic API key not found in config")

        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = "claude-haiku-4-5"

        # Summary settings from config
        summaries_config = config.get("features", {}).get("entity_summaries", {})
        self.max_summary_tokens = summaries_config.get("max_tokens", 5000)
        self.incremental_update_limit = summaries_config.get("incremental_update_limit", 10)
        self.max_words_per_summary = 400  # For monthly summaries (incremental update ceiling)
        self.max_words_alltime = 500  # For all-time summaries

        # Token encoder for counting
        if TIKTOKEN_AVAILABLE:
            self.encoder = tiktoken.get_encoding("cl100k_base")
        else:
            self.encoder = None

        # Stats tracking
        self.stats = {
            "summaries_created": 0,
            "summaries_updated": 0,
            "api_calls": 0,
            "tokens_input": 0,
            "tokens_output": 0,
            "bootstrap_count": 0
        }

    def count_tokens(self, text: str) -> int:
        """Count tokens in text."""
        if self.encoder:
            return len(self.encoder.encode(text))
        else:
            # Rough estimate: ~4 chars per token
            return len(text) // 4

    def _get_current_month(self) -> str:
        """Get current month in YYYY-MM format."""
        return datetime.now(timezone.utc).strftime("%Y-%m")

    def _format_month(self, month: str) -> str:
        """Format month string for display (e.g., '2024-01' -> 'January 2024')."""
        try:
            dt = datetime.strptime(month, "%Y-%m")
            return dt.strftime("%B %Y")
        except ValueError:
            return month

    def _format_messages_for_prompt(self, messages: List[Dict], max_tokens: int = 10000) -> str:
        """
        Format messages for inclusion in a prompt.

        Args:
            messages: List of message dictionaries
            max_tokens: Maximum tokens to include

        Returns:
            Formatted string of messages
        """
        formatted = []
        total_tokens = 0

        for msg in messages:
            sender = msg.get("sender", "unknown")
            content = msg.get("content", "")
            timestamp = msg.get("timestamp", "")[:10]  # Just date

            line = f"[{timestamp}] {sender.title()}: {content}"
            line_tokens = self.count_tokens(line)

            if total_tokens + line_tokens > max_tokens:
                # Truncate content if needed
                available = max_tokens - total_tokens - 50
                if available > 100:
                    truncated = content[:available * 4] + "..."
                    line = f"[{timestamp}] {sender.title()}: {truncated}"
                    formatted.append(line)
                break

            formatted.append(line)
            total_tokens += line_tokens

        return "\n".join(formatted)

    def _call_haiku(self, prompt: str, max_tokens: int = 800) -> str:
        """
        Call Haiku API with the given prompt.

        Uses a system prompt to prevent refusals on sensitive content.
        Detects refusals and raises a clear error so callers can handle it.

        Args:
            prompt: The prompt to send
            max_tokens: Maximum output tokens

        Returns:
            Response text

        Raises:
            SummaryRefusedError: If Haiku refuses to summarize the content
        """
        max_attempts = 3
        last_refusal = None

        for attempt in range(max_attempts):
            try:
                response = self.client.messages.create(
                    model=self.model,
                    max_tokens=max_tokens,
                    temperature=0.5,
                    system=SUMMARIZER_SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": prompt}]
                )

                # Track stats
                self.stats["api_calls"] += 1
                self.stats["tokens_input"] += response.usage.input_tokens
                self.stats["tokens_output"] += response.usage.output_tokens

                text = response.content[0].text.strip()

                # Check for refusal
                if _is_refusal(text):
                    last_refusal = text[:150]
                    remaining = max_attempts - attempt - 1
                    if remaining > 0:
                        print(f"  WARNING: Haiku refused to summarize (attempt {attempt + 1}/{max_attempts}, retrying...)")
                        continue
                    # Final attempt also refused
                    print(f"  WARNING: Haiku refused to summarize after {max_attempts} attempts")
                    raise SummaryRefusedError(
                        f"Haiku refused to summarize after {max_attempts} attempts. "
                        f"Last response: {last_refusal}..."
                    )

                return text

            except SummaryRefusedError:
                raise  # Don't wrap our own exception
            except Exception as e:
                print(f"  Warning: Haiku API call failed: {e}")
                raise

    # =========================================================================
    # Main Entry Points
    # =========================================================================

    def get_or_create_summary(
        self,
        entity_id: int,
        show_progress: bool = True
    ) -> Dict[str, Any]:
        """
        Get or create summaries for an entity.

        This is the main entry point. If summaries don't exist, they will be
        bootstrapped (generated from all historical messages).

        Args:
            entity_id: ID of the entity
            show_progress: Whether to print progress messages

        Returns:
            Dict with:
                - all_time: All-time summary text (or None if no messages)
                - current_month: Current month summary text (or None)
                - bootstrapped: True if summaries were just created
                - entity_name: Name of the entity
                - message_count: Total messages for this entity
        """
        # Get entity info
        entity = self.graph_db.get_entity_by_id(entity_id)
        if not entity:
            return {
                "all_time": None,
                "current_month": None,
                "bootstrapped": False,
                "entity_name": None,
                "message_count": 0,
                "error": "Entity not found"
            }

        entity_name = entity.get("name", f"Entity {entity_id}")

        # Check if all-time summary exists
        alltime = self.db.get_entity_summary(entity_id, "all_time")

        if alltime:
            # Summaries exist, return them
            current_month = self._get_current_month()
            current = self.db.get_entity_summary(entity_id, "month", current_month)

            return {
                "all_time": alltime.get("summary"),
                "current_month": current.get("summary") if current else None,
                "current_month_short": current.get("summary_short") if current else None,
                "bootstrapped": False,
                "entity_name": entity_name,
                "message_count": alltime.get("message_count", 0)
            }

        # No summaries exist - bootstrap
        if show_progress:
            print(f"  Generating summaries for '{entity_name}'...", end=" ", flush=True)

        result = self.bootstrap_entity_summaries(entity_id, entity_name)

        if show_progress:
            if result.get("success"):
                print("done")
            else:
                print(f"failed: {result.get('error', 'unknown')}")

        return {
            "all_time": result.get("all_time"),
            "current_month": result.get("current_month"),
            "bootstrapped": True,
            "entity_name": entity_name,
            "message_count": result.get("message_count", 0),
            "months_created": result.get("months_created", 0)
        }

    def bootstrap_entity_summaries(
        self,
        entity_id: int,
        entity_name: str
    ) -> Dict[str, Any]:
        """
        Bootstrap summaries for an entity from scratch.

        Generates monthly summaries for all historical months, then
        synthesizes an all-time summary.

        Args:
            entity_id: ID of the entity
            entity_name: Name of the entity

        Returns:
            Dict with summary results and stats
        """
        self.stats["bootstrap_count"] += 1

        # Get all months with messages for this entity
        months = self.db.get_entity_months(entity_id)

        if not months:
            return {
                "success": True,
                "all_time": None,
                "current_month": None,
                "message_count": 0,
                "months_created": 0,
                "message": "No messages found for entity"
            }

        current_month = self._get_current_month()
        monthly_summaries = []
        total_message_count = 0
        months_created = 0

        # Generate monthly summary for each month
        for month in months:
            messages = self.db.get_messages_for_entity_by_month(entity_id, month)

            if not messages:
                continue

            total_message_count += len(messages)

            # Generate summary for this month
            formatted_messages = self._format_messages_for_prompt(messages)
            month_display = self._format_month(month)

            prompt = MONTHLY_SUMMARY_PROMPT.format(
                entity_name=entity_name,
                month_year=month_display,
                messages=formatted_messages
            )

            try:
                raw_text = self._call_haiku(prompt)
                summary_text, brief_text = _split_summary_and_brief(raw_text)
                token_count = self.count_tokens(summary_text)

                # Determine if month is frozen (not current month)
                is_frozen = month != current_month

                # Get last message ID
                last_msg_id = messages[-1].get("id") if messages else None

                # Save summary
                self.db.save_entity_summary(
                    entity_id=entity_id,
                    period_type="month",
                    summary=summary_text,
                    message_count=len(messages),
                    token_count=token_count,
                    last_message_id=last_msg_id,
                    is_frozen=is_frozen,
                    period_start=month,
                    summary_short=brief_text
                )

                monthly_summaries.append({
                    "month": month,
                    "month_display": month_display,
                    "summary": summary_text,
                    "is_current": month == current_month
                })

                months_created += 1
                self.stats["summaries_created"] += 1

            except Exception as e:
                print(f"    Warning: Failed to generate summary for {month}: {e}")
                continue

        # Generate all-time summary from monthly summaries
        all_time_text = None
        if monthly_summaries:
            all_time_text = self._generate_alltime_summary(
                entity_id, entity_name, monthly_summaries, total_message_count
            )

        # Get current month summary for return
        current_summary = None
        for ms in monthly_summaries:
            if ms.get("is_current"):
                current_summary = ms.get("summary")
                break

        return {
            "success": True,
            "all_time": all_time_text,
            "current_month": current_summary,
            "message_count": total_message_count,
            "months_created": months_created
        }

    def _generate_alltime_summary(
        self,
        entity_id: int,
        entity_name: str,
        monthly_summaries: List[Dict],
        total_message_count: int
    ) -> Optional[str]:
        """
        Generate all-time summary from monthly summaries.

        Args:
            entity_id: ID of the entity
            entity_name: Name of the entity
            monthly_summaries: List of monthly summary dicts
            total_message_count: Total messages across all months

        Returns:
            All-time summary text, or None on failure
        """
        # Format monthly summaries for prompt
        formatted_monthlies = []
        for ms in monthly_summaries:
            formatted_monthlies.append(f"**{ms['month_display']}:**\n{ms['summary']}")

        prompt = ALLTIME_SUMMARY_PROMPT.format(
            entity_name=entity_name,
            monthly_summaries="\n\n".join(formatted_monthlies)
        )

        try:
            summary_text = self._call_haiku(prompt, max_tokens=1000)
            token_count = self.count_tokens(summary_text)

            # Get last message ID from last monthly
            last_msg_id = None
            if monthly_summaries:
                last_month = monthly_summaries[-1]["month"]
                last_monthly = self.db.get_entity_summary(entity_id, "month", last_month)
                if last_monthly:
                    last_msg_id = last_monthly.get("last_message_id")

            # Save all-time summary
            self.db.save_entity_summary(
                entity_id=entity_id,
                period_type="all_time",
                summary=summary_text,
                message_count=total_message_count,
                token_count=token_count,
                last_message_id=last_msg_id,
                is_frozen=False,
                period_start=None
            )

            self.stats["summaries_created"] += 1

            return summary_text

        except Exception as e:
            print(f"    Warning: Failed to generate all-time summary: {e}")
            return None

    def update_current_month(
        self,
        entity_id: int,
        new_message_ids: List[int]
    ) -> Dict[str, Any]:
        """
        Update current month summary with new messages.

        Called when messages transition from active to standard tier.
        Uses incremental update to add new information without
        full regeneration.

        Args:
            entity_id: ID of the entity
            new_message_ids: List of new message IDs to incorporate

        Returns:
            Dict with update results
        """
        if not new_message_ids:
            return {"success": True, "updated": False, "reason": "No new messages"}

        # Get entity info
        entity = self.graph_db.get_entity_by_id(entity_id)
        if not entity:
            return {"success": False, "error": "Entity not found"}

        entity_name = entity.get("name", f"Entity {entity_id}")
        current_month = self._get_current_month()

        # Get current month summary
        existing = self.db.get_entity_summary(entity_id, "month", current_month)

        # Check if messages are already covered by existing summary
        if existing:
            last_included_id = existing.get("last_message_id", 0) or 0
            # Filter to only truly new messages (not already in summary)
            new_message_ids = [mid for mid in new_message_ids if mid > last_included_id]

            if not new_message_ids:
                return {"success": True, "updated": False, "reason": "Messages already in summary"}

        # Get new messages
        new_messages = []
        for msg_id in new_message_ids:
            msg = self.db.get_message(msg_id)
            if msg:
                new_messages.append(msg)

        if not new_messages:
            return {"success": True, "updated": False, "reason": "Messages not found"}

        if existing:
            # Check if we need full regeneration (drift prevention)
            update_count = existing.get("incremental_update_count", 0)

            if update_count >= self.incremental_update_limit:
                # Full regeneration needed
                return self._regenerate_current_month(entity_id, entity_name, current_month)

            # Incremental update
            formatted_new = self._format_messages_for_prompt(new_messages, max_tokens=3000)

            prompt = INCREMENTAL_UPDATE_PROMPT.format(
                entity_name=entity_name,
                existing_summary=existing.get("summary", ""),
                new_messages=formatted_new,
                max_words=self.max_words_per_summary
            )

            try:
                raw_text = self._call_haiku(prompt)
                updated_text, brief_text = _split_summary_and_brief(raw_text)
                token_count = self.count_tokens(updated_text)

                # Update summary (incremental_update_count auto-increments)
                self.db.save_entity_summary(
                    entity_id=entity_id,
                    period_type="month",
                    summary=updated_text,
                    message_count=existing.get("message_count", 0) + len(new_messages),
                    token_count=token_count,
                    last_message_id=new_messages[-1].get("id"),
                    is_frozen=False,
                    period_start=current_month,
                    summary_short=brief_text
                )

                self.stats["summaries_updated"] += 1

                return {
                    "success": True,
                    "updated": True,
                    "type": "incremental",
                    "messages_added": len(new_messages)
                }

            except Exception as e:
                return {"success": False, "error": str(e)}

        else:
            # No existing summary for current month - check for month rollover first
            # If there are unfrozen previous months, freeze them and regenerate all-time
            all_data = self.db.get_all_summaries_for_entity(entity_id)
            for monthly in all_data.get("monthly", []):
                if not monthly.get("is_frozen") and monthly.get("period_start") != current_month:
                    # Found an unfrozen previous month - handle rollover
                    old_month = monthly.get("period_start")
                    self.handle_month_rollover(entity_id, old_month)
                    break  # Only need to handle once, regenerate_alltime covers all

            # Now create new current month summary
            messages = self.db.get_messages_for_entity_by_month(entity_id, current_month)

            if not messages:
                return {"success": True, "updated": False, "reason": "No messages for month"}

            formatted_messages = self._format_messages_for_prompt(messages)
            month_display = self._format_month(current_month)

            prompt = MONTHLY_SUMMARY_PROMPT.format(
                entity_name=entity_name,
                month_year=month_display,
                messages=formatted_messages
            )

            try:
                raw_text = self._call_haiku(prompt)
                summary_text, brief_text = _split_summary_and_brief(raw_text)
                token_count = self.count_tokens(summary_text)

                self.db.save_entity_summary(
                    entity_id=entity_id,
                    period_type="month",
                    summary=summary_text,
                    message_count=len(messages),
                    token_count=token_count,
                    last_message_id=messages[-1].get("id"),
                    is_frozen=False,
                    period_start=current_month,
                    summary_short=brief_text
                )

                self.stats["summaries_created"] += 1

                return {
                    "success": True,
                    "updated": True,
                    "type": "new_month",
                    "messages_added": len(messages)
                }

            except Exception as e:
                return {"success": False, "error": str(e)}

    def _regenerate_current_month(
        self,
        entity_id: int,
        entity_name: str,
        month: str
    ) -> Dict[str, Any]:
        """
        Fully regenerate current month summary.

        Used when incremental updates have accumulated drift.

        Args:
            entity_id: ID of the entity
            entity_name: Name of the entity
            month: Month to regenerate (YYYY-MM)

        Returns:
            Dict with regeneration results
        """
        messages = self.db.get_messages_for_entity_by_month(entity_id, month)

        if not messages:
            return {"success": True, "updated": False, "reason": "No messages for month"}

        formatted_messages = self._format_messages_for_prompt(messages)
        month_display = self._format_month(month)

        prompt = MONTHLY_SUMMARY_PROMPT.format(
            entity_name=entity_name,
            month_year=month_display,
            messages=formatted_messages
        )

        try:
            raw_text = self._call_haiku(prompt)
            summary_text, brief_text = _split_summary_and_brief(raw_text)
            token_count = self.count_tokens(summary_text)

            self.db.save_entity_summary(
                entity_id=entity_id,
                period_type="month",
                summary=summary_text,
                message_count=len(messages),
                token_count=token_count,
                last_message_id=messages[-1].get("id"),
                is_frozen=False,
                period_start=month,
                summary_short=brief_text
            )

            # Reset incremental count
            self.db.reset_incremental_count(entity_id, month)

            self.stats["summaries_updated"] += 1

            return {
                "success": True,
                "updated": True,
                "type": "full_regeneration",
                "messages_processed": len(messages)
            }

        except Exception as e:
            return {"success": False, "error": str(e)}

    def regenerate_alltime(self, entity_id: int) -> Dict[str, Any]:
        """
        Regenerate all-time summary from monthly summaries.

        Called when a new month is frozen and needs to be incorporated.

        Args:
            entity_id: ID of the entity

        Returns:
            Dict with regeneration results
        """
        # Get entity info
        entity = self.graph_db.get_entity_by_id(entity_id)
        if not entity:
            return {"success": False, "error": "Entity not found"}

        entity_name = entity.get("name", f"Entity {entity_id}")

        # Get all monthly summaries
        all_data = self.db.get_all_summaries_for_entity(entity_id)
        all_summaries = (all_data.get("monthly", []) +
                        ([all_data.get("all_time")] if all_data.get("all_time") else []))
        monthly_summaries = [
            s for s in all_summaries
            if s.get("period_type") == "month"
        ]

        if not monthly_summaries:
            return {"success": True, "updated": False, "reason": "No monthly summaries"}

        # Sort by period_start
        monthly_summaries.sort(key=lambda x: x.get("period_start", ""))

        # Format for regeneration
        formatted_monthlies = []
        total_message_count = 0

        for ms in monthly_summaries:
            month_display = self._format_month(ms.get("period_start", ""))
            formatted_monthlies.append({
                "month": ms.get("period_start"),
                "month_display": month_display,
                "summary": ms.get("summary", ""),
                "is_current": ms.get("period_start") == self._get_current_month()
            })
            total_message_count += ms.get("message_count", 0)

        # Generate new all-time summary
        result = self._generate_alltime_summary(
            entity_id, entity_name, formatted_monthlies, total_message_count
        )

        if result:
            return {
                "success": True,
                "updated": True,
                "monthly_count": len(monthly_summaries),
                "total_messages": total_message_count
            }
        else:
            return {"success": False, "error": "Failed to generate all-time summary"}

    def handle_month_rollover(self, entity_id: int, old_month: str) -> Dict[str, Any]:
        """
        Handle month rollover for an entity.

        Called when a new month begins. Freezes the old month and
        regenerates the all-time summary.

        Args:
            entity_id: ID of the entity
            old_month: The month that just ended (YYYY-MM)

        Returns:
            Dict with rollover results
        """
        # Freeze the old month
        frozen = self.db.freeze_entity_summary(entity_id, old_month)

        if not frozen:
            return {"success": False, "error": "Failed to freeze month"}

        # Regenerate all-time summary
        result = self.regenerate_alltime(entity_id)
        result["month_frozen"] = old_month

        return result

    # =========================================================================
    # Tier Transition Integration
    # =========================================================================

    def update_for_tier_transition(
        self,
        transitioned_message_ids: List[int]
    ) -> Dict[str, Any]:
        """
        Update entity summaries for messages that transitioned tiers.

        This is the main hook called by tier_manager when messages
        move from active to standard tier.

        Args:
            transitioned_message_ids: List of message IDs that transitioned

        Returns:
            Dict with update results per entity
        """
        if not transitioned_message_ids:
            return {"success": True, "entities_updated": 0}

        # Get entities affected by these messages
        entity_messages = defaultdict(list)

        for msg_id in transitioned_message_ids:
            entities = self.db.get_entities_for_message(msg_id)
            for entity in entities:
                entity_id = entity.get("id")  # Column is 'id' from entities table
                if entity_id:
                    entity_messages[entity_id].append(msg_id)

        if not entity_messages:
            return {"success": True, "entities_updated": 0, "reason": "No entities affected"}

        results = {
            "success": True,
            "entities_updated": 0,
            "entities_failed": 0,
            "details": {}
        }

        # Update each affected entity (one Haiku call per entity)
        for entity_id, message_ids in entity_messages.items():
            try:
                update_result = self.update_current_month(entity_id, message_ids)

                if update_result.get("success"):
                    results["entities_updated"] += 1
                else:
                    results["entities_failed"] += 1

                results["details"][entity_id] = update_result

            except Exception as e:
                results["entities_failed"] += 1
                results["details"][entity_id] = {"success": False, "error": str(e)}

        return results

    # =========================================================================
    # Statistics and Diagnostics
    # =========================================================================

    def get_statistics(self) -> Dict[str, Any]:
        """Get manager statistics."""
        cost = self._calculate_cost()

        return {
            "summaries_created": self.stats["summaries_created"],
            "summaries_updated": self.stats["summaries_updated"],
            "api_calls": self.stats["api_calls"],
            "tokens_input": self.stats["tokens_input"],
            "tokens_output": self.stats["tokens_output"],
            "bootstrap_count": self.stats["bootstrap_count"],
            "estimated_cost": round(cost, 4)
        }

    def _calculate_cost(self) -> float:
        """Calculate estimated cost based on token usage."""
        # Haiku pricing: $0.80/1M input, $4.00/1M output
        input_cost = (self.stats["tokens_input"] / 1_000_000) * 0.80
        output_cost = (self.stats["tokens_output"] / 1_000_000) * 4.00
        return input_cost + output_cost

    def get_entity_summary_status(self, entity_id: int) -> Dict[str, Any]:
        """
        Get detailed summary status for an entity.

        Args:
            entity_id: ID of the entity

        Returns:
            Dict with summary status details
        """
        entity = self.graph_db.get_entity_by_id(entity_id)
        if not entity:
            return {"error": "Entity not found"}

        all_data = self.db.get_all_summaries_for_entity(entity_id)

        alltime = all_data.get("all_time")
        monthlies = []
        current_month = self._get_current_month()

        for s in all_data.get("monthly", []):
            monthlies.append({
                "month": s.get("period_start"),
                "message_count": s.get("message_count"),
                "token_count": s.get("token_count"),
                "is_frozen": s.get("is_frozen"),
                "is_current": s.get("period_start") == current_month,
                "incremental_updates": s.get("incremental_update_count", 0)
            })

        return {
            "entity_name": entity.get("name"),
            "has_alltime": alltime is not None,
            "alltime_message_count": alltime.get("message_count") if alltime else 0,
            "alltime_token_count": alltime.get("token_count") if alltime else 0,
            "monthly_count": len(monthlies),
            "monthlies": sorted(monthlies, key=lambda x: x.get("month", ""))
        }
