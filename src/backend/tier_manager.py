"""
Tier Manager Module for Mneme Memory System

Handles memory tier transitions and rebalancing:
- Active tier: Messages within token budget (rolling window)
- Standard tier: Messages outside budget (retrievable)
- Deep archive: Messages older than 6 months (--deep flag only)

TIER FLOW:
- New messages start as "active" (in 75k rolling window)
- When they age out of 75k → "standard" (now retrievable)
- After 6 months → "deep_archive" (only with --deep flag)

SPEC ALIGNMENT:
- Line 29: "Rolling window: 50-100k tokens active"
- Line 32: "Memory lifecycle: load → use → unload when topic shifts"

USAGE:
    tier_mgr = TierManager(database, context_assembler, config, graph_db)
    tier_mgr.rebalance_on_startup()
    tier_mgr.transition_tiers()
"""

from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, List
import sys


class TierError(Exception):
    """Custom exception for tier management errors."""
    pass


class TierManager:
    """
    Manages memory tier transitions and rebalancing.

    This class handles:
    - Transitioning messages between active/standard/deep_archive tiers
    - Cleaning up temporary/retrieved messages that aged out
    - Rebalancing tiers on startup based on config changes
    """

    def __init__(self, database, context_assembler, config: Dict, graph_db=None):
        """
        Initialize tier manager.

        Args:
            database: Database instance
            context_assembler: ContextAssembler instance (for token counting)
            config: Configuration dictionary
            graph_db: GraphDatabase instance (optional, for entity summaries)
        """
        self.db = database
        self.context_assembler = context_assembler
        self.config = config
        self.graph_db = graph_db

        # Track last tier transition time
        self.last_transition_time = datetime.now(timezone.utc)

        # Deep archive threshold
        self.deep_archive_days = config.get("retrieval", {}).get("deep_archive_age_days", 180)

        # Entity summary manager (lazy-initialized)
        self.entity_summary_manager = None
        summaries_config = config.get("features", {}).get("entity_summaries", {})
        self.summaries_enabled = summaries_config.get("enabled", False) and graph_db is not None

    def transition_tiers(self, background_summaries: bool = False) -> Dict:
        """
        Update memory tiers based on position in active window.
        Also cleanup temporary/retrieved messages that aged out.

        Returns:
            dict: Summary of changes made

        TIER FLOW:
        - New messages start as "active" (in 75k rolling window)
        - When they age out of 75k → "standard" (now retrievable)
        - After 6 months → "deep_archive" (only with --deep flag)

        CLEANUP:
        - Retrieved memories outside 75k → DELETE (duplicates of originals)
        - Temporary system messages outside 75k → DELETE (status messages)

        This runs:
        - On startup (clean stale data)
        - On cold starts (gap > 60min)
        - Every N messages (batched for efficiency)
        """
        import json

        changes = {
            "deleted_temporary": 0,
            "promoted_to_active": 0,
            "transitioned_to_standard": 0,
            "archived_to_deep": 0
        }

        try:
            # Step 1: Calculate active window boundary (token budget)
            # CRITICAL: Process ALL database messages (not just conversation_history!)
            # This ensures ALL messages get proper tier assignment.

            # Load ALL messages from database (no limit!)
            message_count = self.db.get_message_count()
            if message_count > 50000:
                print(f"  WARNING: Large database ({message_count:,} messages) - tier transitions may be slow", file=sys.stderr, flush=True)
            if message_count > 100000:
                print(f"  CRITICAL: Database exceeds 100k messages - consider archiving old data", file=sys.stderr, flush=True)

            all_msgs = self.db.get_recent_messages(limit=100000)  # Huge limit = get everything

            # Count tokens backwards from newest to find active window boundary
            # Active = within budget, Standard = outside budget
            active_ids = []
            total_tokens = 0
            budget = self.context_assembler.recent_budget

            for msg in all_msgs:  # Already in reverse chronological order
                content = msg.get("content", "")
                tokens = self.context_assembler.count_tokens(content)

                if total_tokens + tokens <= budget:
                    # Within budget → stays in "active" tier
                    active_ids.append(msg["id"])
                    total_tokens += tokens
                else:
                    # Outside budget → will be transitioned to "standard"
                    # Keep processing to count all messages (for deep archive check)
                    pass

            if not active_ids:
                return changes  # No messages in active window, nothing to do

            # Build SQL placeholder string for active message IDs
            placeholders = ','.join('?' * len(active_ids))

            # Step 2: Delete temporary system messages outside active window
            # Status messages, errors, etc. that are no longer relevant
            deleted_temp = self.db.execute_write(f"""
                DELETE FROM messages
                WHERE json_extract(metadata, '$.temporary') = 1
                AND sender = 'system'
                AND id NOT IN ({placeholders})
            """, tuple(active_ids))
            changes["deleted_temporary"] = deleted_temp or 0

            # Step 3: Promote messages INTO active tier (standard → active)
            # This is critical for rebalancing after config changes or importing databases!
            promoted = self.db.execute_write(f"""
                UPDATE messages
                SET tier = 'active'
                WHERE id IN ({placeholders})
                AND tier != 'active'
                AND (metadata IS NULL OR json_extract(metadata, '$.retrieved') IS NULL)
                AND (metadata IS NULL OR json_extract(metadata, '$.temporary') IS NULL)
            """, tuple(active_ids))
            changes["promoted_to_active"] = promoted or 0

            # Step 4: Transition real messages from active → standard (aged out of window)
            # First, query for IDs that will be transitioned (for entity summary updates)
            transitioning_ids = []
            if self.summaries_enabled:
                result = self.db.execute_query(f"""
                    SELECT id FROM messages
                    WHERE tier = 'active'
                    AND id NOT IN ({placeholders})
                    AND (metadata IS NULL OR json_extract(metadata, '$.retrieved') IS NULL)
                    AND (metadata IS NULL OR json_extract(metadata, '$.temporary') IS NULL)
                """, tuple(active_ids))
                transitioning_ids = [row["id"] for row in result]

            # Only transition messages that aren't retrieved or temporary
            transitioned = self.db.execute_write(f"""
                UPDATE messages
                SET tier = 'standard'
                WHERE tier = 'active'
                AND id NOT IN ({placeholders})
                AND (metadata IS NULL OR json_extract(metadata, '$.retrieved') IS NULL)
                AND (metadata IS NULL OR json_extract(metadata, '$.temporary') IS NULL)
            """, tuple(active_ids))
            changes["transitioned_to_standard"] = transitioned or 0
            changes["transitioned_ids"] = transitioning_ids

            # Step 4.5: Strip @run output from transitioned messages
            # Output persists in active context for multi-turn discussion,
            # but is dead weight once the message leaves the active window.
            if transitioning_ids:
                changes["run_output_stripped"] = self._strip_run_output(transitioning_ids)

            # Step 5: Archive old messages (6+ months) from standard → deep_archive
            cutoff = (datetime.now(timezone.utc) - timedelta(days=self.deep_archive_days)).isoformat() + "Z"
            archived = self.db.execute_write("""
                UPDATE messages
                SET tier = 'deep_archive'
                WHERE tier = 'standard'
                AND timestamp < ?
            """, (cutoff,))
            changes["archived_to_deep"] = archived or 0

            # Update last transition time
            self.last_transition_time = datetime.now(timezone.utc)

            # Log transitions (only if something changed)
            self._log_changes(changes)

            # Phase 8: Update entity summaries for transitioned messages
            if self.summaries_enabled and transitioning_ids:
                if background_summaries:
                    import threading
                    threading.Thread(
                        target=self._update_entity_summaries,
                        args=(transitioning_ids,),
                        daemon=True
                    ).start()
                else:
                    self._update_entity_summaries(transitioning_ids)

            return changes

        except Exception as e:
            # Don't crash on tier transition errors, just log
            print(f"Warning: Tier transition failed: {e}")
            return changes

    def _update_entity_summaries(self, transitioned_ids: List[int]):
        """
        Update entity summaries for messages that transitioned to standard tier.

        Args:
            transitioned_ids: List of message IDs that just transitioned

        This is called after tier transitions to keep entity summaries fresh.
        Uses lazy initialization of the EntitySummaryManager.
        """
        if not transitioned_ids:
            return

        try:
            # Lazy-initialize entity summary manager
            if self.entity_summary_manager is None:
                from src.backend.entity_summaries import EntitySummaryManager
                self.entity_summary_manager = EntitySummaryManager(
                    self.config, self.db, self.graph_db
                )

            # Update summaries for affected entities
            result = self.entity_summary_manager.update_for_tier_transition(transitioned_ids)

            if result.get("entities_updated", 0) > 0:
                print(f"  Updated entity summaries for {result['entities_updated']} entities")

        except Exception as e:
            # Don't crash on entity summary errors
            print(f"Warning: Entity summary update failed: {e}")

    def rebalance_on_startup(self) -> bool:
        """
        Run automatic tier reallocation on startup.

        Returns:
            bool: True if rebalancing was successful

        This ensures database tiers match current config settings after:
        - Config changes (budget adjustments)
        - Server restarts
        - Manual database modifications

        NOTE: Uses transition_tiers() which does proper token counting!
        """
        auto_rebalance = self.config.get("caching", {}).get("auto_rebalance_on_startup", True)

        if not auto_rebalance:
            return False

        try:
            print("Running automatic tier rebalancing...")
            changes = self.transition_tiers(background_summaries=True)

            if any(v > 0 for v in changes.values() if isinstance(v, (int, float))):
                print("   Tiers rebalanced based on current config")
            else:
                print("   Tiers already balanced")

            return True

        except Exception as e:
            print(f"   Rebalancing failed: {e}")
            print("   (Continuing with existing tiers)")
            return False

    def get_tier_statistics(self) -> Dict:
        """
        Get current tier statistics.

        Returns:
            dict: Tier counts and info
        """
        tier_counts = self.db.execute_query("""
            SELECT tier, COUNT(*) as count
            FROM messages
            GROUP BY tier
        """)

        tier_map = {"active": "Active", "standard": "Standard", "deep_archive": "Deep Archive"}

        # Build count dict from query results
        tier_count_dict = {}
        total = 0
        for tier_row in tier_counts:
            tier_count_dict[tier_row["tier"]] = tier_row["count"]
            total += tier_row["count"]

        return {
            "active": tier_count_dict.get("active", 0),
            "standard": tier_count_dict.get("standard", 0),
            "deep_archive": tier_count_dict.get("deep_archive", 0),
            "total": total,
            "last_transition": self.last_transition_time.isoformat()
        }

    def _log_changes(self, changes: Dict):
        """
        Log tier transition changes.

        Args:
            changes: Dict of change counts
        """
        messages = []
        if changes["deleted_temporary"] > 0:
            messages.append(f"  {changes['deleted_temporary']} temporary messages deleted")
        if changes["promoted_to_active"] > 0:
            messages.append(f"  {changes['promoted_to_active']} promoted to active tier")
        if changes["transitioned_to_standard"] > 0:
            messages.append(f"  {changes['transitioned_to_standard']} moved to standard tier")
        if changes["archived_to_deep"] > 0:
            messages.append(f"  {changes['archived_to_deep']} archived to deep storage")

        if messages:
            print("Tier transition:")
            for msg in messages:
                print(msg)

    def _strip_run_output(self, message_ids: List[int]) -> int:
        """
        Strip [run output]...[/run output] blocks from messages leaving active tier.

        Returns:
            Number of messages stripped.
        """
        import re

        stripped = 0
        for msg_id in message_ids:
            msg = self.db.get_message(msg_id)
            if not msg or msg["sender"] != "assistant":
                continue
            content = msg["content"]
            if "[run output]" not in content:
                continue

            new_content = re.sub(
                r'\n*\[run output\]\n[\s\S]*?\[/run output\]',
                '',
                content
            )

            if new_content != content:
                self.db.update_message_content(msg_id, new_content)
                stripped += 1

        if stripped:
            print(f"  Stripped @run output from {stripped} messages")
        return stripped
