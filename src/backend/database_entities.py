"""
Entity and entity summary database operations — mixin for the Database class.
"""

from datetime import datetime, timezone
from typing import List, Dict, Optional


class DatabaseEntitiesMixin:

    # =========================================================================
    # MESSAGE-ENTITY OPERATIONS (Phase 8)
    # =========================================================================

    def add_message_entity(
        self,
        message_id: int,
        entity_id: int,
        confidence: float = 1.0,
        source: str = "haiku"
    ) -> Optional[int]:
        """
        Link a message to an entity.

        Args:
            message_id: ID of the message
            entity_id: ID of the entity
            confidence: Confidence of the assignment (0.0-1.0)
            source: How the assignment was made ('haiku', 'string_match', 'manual')

        Returns:
            int: ID of the new link, or None if already exists

        NOTE: Uses INSERT OR IGNORE to handle duplicate gracefully.
        """
        timestamp = datetime.now(timezone.utc).isoformat() + "Z"

        query = """
            INSERT OR IGNORE INTO message_entities
            (message_id, entity_id, confidence, source, created_at)
            VALUES (?, ?, ?, ?, ?)
        """
        params = (message_id, entity_id, confidence, source, timestamp)

        try:
            result = self.execute_write(query, params)
            return result if result else None
        except Exception:
            # Likely duplicate, which is fine
            return None

    def add_message_entities_batch(
        self,
        links: List[Dict]
    ) -> int:
        """
        Add multiple message-entity links in a batch.

        Args:
            links: List of dicts with keys: message_id, entity_id, confidence, source

        Returns:
            int: Number of links added

        EXAMPLE:
            links = [
                {"message_id": 1, "entity_id": 5, "confidence": 0.9, "source": "haiku"},
                {"message_id": 1, "entity_id": 8, "confidence": 0.7, "source": "haiku"}
            ]
            count = db.add_message_entities_batch(links)
        """
        timestamp = datetime.now(timezone.utc).isoformat() + "Z"

        query = """
            INSERT OR IGNORE INTO message_entities
            (message_id, entity_id, confidence, source, created_at)
            VALUES (?, ?, ?, ?, ?)
        """

        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            added = 0

            for link in links:
                try:
                    cursor.execute(query, (
                        link["message_id"],
                        link["entity_id"],
                        link.get("confidence", 1.0),
                        link.get("source", "haiku"),
                        timestamp
                    ))
                    if cursor.rowcount > 0:
                        added += 1
                except Exception as e:
                    print(f"  Warning: failed to add entity link: {e}")
                    continue

            conn.commit()
            return added
        finally:
            conn.close()

    def get_entities_for_message(self, message_id: int) -> List[Dict]:
        """
        Get all entities linked to a message.

        Args:
            message_id: ID of the message

        Returns:
            List of entity dictionaries with confidence and link info
        """
        query = """
            SELECT
                e.id, e.name, e.aliases, e.mention_count,
                e.first_mentioned, e.last_mentioned,
                me.confidence, me.source, me.created_at as linked_at
            FROM message_entities me
            JOIN entities e ON me.entity_id = e.id
            WHERE me.message_id = ?
            ORDER BY me.confidence DESC
        """
        results = self.execute_query(query, (message_id,))
        return [dict(row) for row in results]

    def get_messages_for_entity(
        self,
        entity_id: int,
        limit: int = 100,
        min_confidence: float = 0.0
    ) -> List[Dict]:
        """
        Get all messages that discuss an entity.

        Args:
            entity_id: ID of the entity
            limit: Maximum messages to return
            min_confidence: Minimum confidence threshold

        Returns:
            List of message dictionaries ordered by timestamp
        """
        query = """
            SELECT
                m.id, m.sender, m.content, m.timestamp,
                m.importance_score, m.tier,
                me.confidence
            FROM message_entities me
            JOIN messages m ON me.message_id = m.id
            WHERE me.entity_id = ?
              AND me.confidence >= ?
            ORDER BY m.timestamp DESC
            LIMIT ?
        """
        results = self.execute_query(query, (entity_id, min_confidence, limit))
        return [dict(row) for row in results]

    def get_messages_for_entity_by_month(
        self,
        entity_id: int,
        month: str,
        min_confidence: float = 0.0
    ) -> List[Dict]:
        """
        Get messages discussing an entity for a specific month.

        Args:
            entity_id: ID of the entity
            month: Month in format 'YYYY-MM' (e.g., '2024-01')
            min_confidence: Minimum confidence threshold

        Returns:
            List of message dictionaries ordered by timestamp
        """
        # Match timestamps that start with the month
        query = """
            SELECT
                m.id, m.sender, m.content, m.timestamp,
                m.importance_score, m.tier,
                me.confidence
            FROM message_entities me
            JOIN messages m ON me.message_id = m.id
            WHERE me.entity_id = ?
              AND me.confidence >= ?
              AND m.timestamp LIKE ?
            ORDER BY m.timestamp ASC
        """
        results = self.execute_query(query, (entity_id, min_confidence, f"{month}%"))
        return [dict(row) for row in results]

    def get_entity_months(self, entity_id: int) -> List[str]:
        """
        Get list of months that have messages for an entity.

        Args:
            entity_id: ID of the entity

        Returns:
            List of months in 'YYYY-MM' format, sorted chronologically
        """
        query = """
            SELECT DISTINCT SUBSTR(m.timestamp, 1, 7) as month
            FROM message_entities me
            JOIN messages m ON me.message_id = m.id
            WHERE me.entity_id = ?
            ORDER BY month ASC
        """
        results = self.execute_query(query, (entity_id,))
        return [row["month"] for row in results]

    def get_unlinked_messages(self, limit: int = 100) -> List[Dict]:
        """
        Get messages that haven't been linked to any entities.

        Args:
            limit: Maximum messages to return

        Returns:
            List of message dictionaries
        """
        query = """
            SELECT m.*
            FROM messages m
            LEFT JOIN message_entities me ON m.id = me.message_id
            WHERE me.id IS NULL
            ORDER BY m.timestamp DESC
            LIMIT ?
        """
        results = self.execute_query(query, (limit,))
        return [dict(row) for row in results]

    def get_message_entity_stats(self) -> Dict:
        """
        Get statistics about message-entity links.

        Returns:
            Dict with statistics
        """
        total_links = self.execute_query(
            "SELECT COUNT(*) as count FROM message_entities"
        )[0]["count"]

        linked_messages = self.execute_query(
            "SELECT COUNT(DISTINCT message_id) as count FROM message_entities"
        )[0]["count"]

        total_messages = self.execute_query(
            "SELECT COUNT(*) as count FROM messages"
        )[0]["count"]

        by_source = self.execute_query("""
            SELECT source, COUNT(*) as count
            FROM message_entities
            GROUP BY source
        """)

        avg_entities_per_message = self.execute_query("""
            SELECT AVG(entity_count) as avg FROM (
                SELECT message_id, COUNT(*) as entity_count
                FROM message_entities
                GROUP BY message_id
            )
        """)[0]["avg"]

        return {
            "total_links": total_links,
            "linked_messages": linked_messages,
            "total_messages": total_messages,
            "unlinked_messages": total_messages - linked_messages,
            "coverage_percent": round(linked_messages / total_messages * 100, 1) if total_messages > 0 else 0,
            "by_source": {row["source"]: row["count"] for row in by_source},
            "avg_entities_per_message": round(avg_entities_per_message or 0, 2)
        }

    # =========================================================================
    # ENTITY SUMMARY OPERATIONS (Phase 8)
    # =========================================================================

    def get_entity_summary(
        self,
        entity_id: int,
        period_type: str,
        period_start: Optional[str] = None
    ) -> Optional[Dict]:
        """
        Get a specific entity summary.

        Args:
            entity_id: ID of the entity
            period_type: 'month' or 'all_time'
            period_start: Month string (e.g., '2024-01') for monthly, None for all_time

        Returns:
            Summary dictionary or None if not found
        """
        if period_type == "all_time":
            query = """
                SELECT * FROM entity_summaries
                WHERE entity_id = ? AND period_type = 'all_time'
            """
            results = self.execute_query(query, (entity_id,))
        else:
            query = """
                SELECT * FROM entity_summaries
                WHERE entity_id = ? AND period_type = ? AND period_start = ?
            """
            results = self.execute_query(query, (entity_id, period_type, period_start))

        return dict(results[0]) if results else None

    def get_all_summaries_for_entity(self, entity_id: int) -> Dict:
        """
        Get all summaries for an entity.

        Args:
            entity_id: ID of the entity

        Returns:
            Dict with 'all_time' and 'monthly' keys
        """
        query = """
            SELECT * FROM entity_summaries
            WHERE entity_id = ?
            ORDER BY period_type, period_start
        """
        results = self.execute_query(query, (entity_id,))

        all_time = None
        monthly = []

        for row in results:
            row_dict = dict(row)
            if row_dict["period_type"] == "all_time":
                all_time = row_dict
            else:
                monthly.append(row_dict)

        return {
            "all_time": all_time,
            "monthly": monthly
        }

    def save_entity_summary(
        self,
        entity_id: int,
        period_type: str,
        summary: str,
        message_count: int = 0,
        token_count: int = 0,
        last_message_id: Optional[int] = None,
        is_frozen: bool = False,
        period_start: Optional[str] = None,
        summary_short: Optional[str] = None
    ) -> int:
        """
        Save or update an entity summary.

        Args:
            entity_id: ID of the entity
            period_type: 'month' or 'all_time'
            summary: The full summary text
            message_count: Number of messages that contributed
            token_count: Approximate token count
            last_message_id: Last message ID included
            is_frozen: Whether this summary is frozen
            period_start: Month string for monthly summaries
            summary_short: Condensed version (~100 words) for context injection

        Returns:
            ID of the summary record
        """
        timestamp = datetime.now(timezone.utc).isoformat() + "Z"

        # Check if summary exists
        existing = self.get_entity_summary(entity_id, period_type, period_start)

        if existing:
            # Update existing summary
            query = """
                UPDATE entity_summaries
                SET summary = ?,
                    summary_short = ?,
                    message_count = ?,
                    token_count = ?,
                    last_message_id = ?,
                    is_frozen = ?,
                    incremental_update_count = incremental_update_count + 1,
                    updated_at = ?
                WHERE id = ?
            """
            self.execute_write(query, (
                summary, summary_short, message_count, token_count,
                last_message_id, 1 if is_frozen else 0,
                timestamp, existing["id"]
            ))
            return existing["id"]
        else:
            # Create new summary
            query = """
                INSERT INTO entity_summaries
                (entity_id, period_type, period_start, summary, summary_short, message_count,
                 token_count, last_message_id, is_frozen, incremental_update_count,
                 created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
            """
            return self.execute_write(query, (
                entity_id, period_type, period_start, summary, summary_short, message_count,
                token_count, last_message_id, 1 if is_frozen else 0,
                timestamp, timestamp
            ))

    def freeze_entity_summary(self, entity_id: int, period_start: str) -> bool:
        """
        Mark a monthly summary as frozen.

        Args:
            entity_id: ID of the entity
            period_start: Month to freeze (e.g., '2024-01')

        Returns:
            True if frozen successfully
        """
        timestamp = datetime.now(timezone.utc).isoformat() + "Z"

        query = """
            UPDATE entity_summaries
            SET is_frozen = 1, updated_at = ?
            WHERE entity_id = ? AND period_type = 'month' AND period_start = ?
        """
        self.execute_write(query, (timestamp, entity_id, period_start))
        return True

    def reset_incremental_count(self, entity_id: int, period_start: str) -> bool:
        """
        Reset the incremental update count after a full regeneration.

        Args:
            entity_id: ID of the entity
            period_start: Month to reset (e.g., '2024-01')

        Returns:
            True if reset successfully
        """
        timestamp = datetime.now(timezone.utc).isoformat() + "Z"

        query = """
            UPDATE entity_summaries
            SET incremental_update_count = 0, updated_at = ?
            WHERE entity_id = ? AND period_type = 'month' AND period_start = ?
        """
        self.execute_write(query, (timestamp, entity_id, period_start))
        return True

    def get_unfrozen_summaries(self) -> List[Dict]:
        """
        Get all unfrozen monthly summaries.

        Returns:
            List of summary dictionaries that need potential freezing
        """
        query = """
            SELECT * FROM entity_summaries
            WHERE period_type = 'month' AND is_frozen = 0
            ORDER BY period_start
        """
        results = self.execute_query(query)
        return [dict(row) for row in results]

    def get_stale_summaries(self, incremental_limit: int = 10) -> List[Dict]:
        """
        Get summaries that have exceeded the incremental update limit.

        Args:
            incremental_limit: Threshold for incremental updates

        Returns:
            List of summary dictionaries needing full regeneration
        """
        query = """
            SELECT * FROM entity_summaries
            WHERE period_type = 'month'
              AND is_frozen = 0
              AND incremental_update_count >= ?
            ORDER BY period_start
        """
        results = self.execute_query(query, (incremental_limit,))
        return [dict(row) for row in results]

    def delete_entity_summary(
        self,
        entity_id: int,
        period_type: str,
        period_start: Optional[str] = None
    ) -> bool:
        """
        Delete an entity summary.

        Args:
            entity_id: ID of the entity
            period_type: 'month' or 'all_time'
            period_start: Month string for monthly summaries

        Returns:
            True if deleted
        """
        if period_type == "all_time":
            query = """
                DELETE FROM entity_summaries
                WHERE entity_id = ? AND period_type = 'all_time'
            """
            self.execute_write(query, (entity_id,))
        else:
            query = """
                DELETE FROM entity_summaries
                WHERE entity_id = ? AND period_type = ? AND period_start = ?
            """
            self.execute_write(query, (entity_id, period_type, period_start))
        return True

    def get_entity_summary_stats(self) -> Dict:
        """
        Get statistics about entity summaries.

        Returns:
            Dict with statistics
        """
        total = self.execute_query(
            "SELECT COUNT(*) as count FROM entity_summaries"
        )[0]["count"]

        by_type = self.execute_query("""
            SELECT period_type, COUNT(*) as count
            FROM entity_summaries
            GROUP BY period_type
        """)

        frozen_count = self.execute_query(
            "SELECT COUNT(*) as count FROM entity_summaries WHERE is_frozen = 1"
        )[0]["count"]

        entities_with_summaries = self.execute_query(
            "SELECT COUNT(DISTINCT entity_id) as count FROM entity_summaries"
        )[0]["count"]

        return {
            "total_summaries": total,
            "by_type": {row["period_type"]: row["count"] for row in by_type},
            "frozen_count": frozen_count,
            "entities_with_summaries": entities_with_summaries
        }
