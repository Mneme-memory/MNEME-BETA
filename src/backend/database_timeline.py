"""
Timeline (daily summaries) and notes database operations — mixin for the Database class.
"""

from datetime import datetime, timezone
from typing import List, Dict, Optional


class DatabaseTimelineMixin:

    # =========================================================================
    # DAILY SUMMARY OPERATIONS (Phase 9)
    # =========================================================================

    def get_daily_summary(self, date: str) -> Optional[Dict]:
        """
        Get a daily summary by date.

        Args:
            date: Date string in YYYY-MM-DD format

        Returns:
            Summary dictionary or None if not found
        """
        results = self.execute_query(
            "SELECT * FROM daily_summaries WHERE date = ?",
            (date,)
        )
        return dict(results[0]) if results else None

    def save_daily_summary(
        self,
        date: str,
        summary_text: str,
        token_count: int = 0,
        message_count: int = 0
    ) -> bool:
        """
        Save or update a daily summary.

        Args:
            date: Date string in YYYY-MM-DD format
            summary_text: The summary text
            token_count: Approximate token count
            message_count: Number of messages summarized

        Returns:
            True if successful
        """
        timestamp = datetime.now(timezone.utc).isoformat() + "Z"

        query = """
            INSERT OR REPLACE INTO daily_summaries
            (date, summary_text, token_count, message_count, generated_at)
            VALUES (?, ?, ?, ?, ?)
        """
        self.execute_write(query, (date, summary_text, token_count, message_count, timestamp))
        return True

    def get_summaries_for_range(self, start_date: str, end_date: str) -> List[Dict]:
        """
        Get all summaries for a date range.

        Args:
            start_date: Start date in YYYY-MM-DD format
            end_date: End date in YYYY-MM-DD format

        Returns:
            List of summary dictionaries, ordered by date ascending
        """
        query = """
            SELECT * FROM daily_summaries
            WHERE date >= ? AND date <= ?
            ORDER BY date ASC
        """
        results = self.execute_query(query, (start_date, end_date))
        return [dict(row) for row in results]

    def get_messages_for_date(self, date: str) -> List[Dict]:
        """
        Get all messages for a specific date.

        Args:
            date: Date string in YYYY-MM-DD format

        Returns:
            List of message dictionaries, ordered by timestamp ascending
        """
        # Match timestamps that start with the date (YYYY-MM-DD)
        query = """
            SELECT id, sender, content, timestamp, importance_score, tier
            FROM messages
            WHERE timestamp LIKE ?
              AND (metadata IS NULL OR json_extract(metadata, '$.temporary') IS NULL)
            ORDER BY timestamp ASC
        """
        results = self.execute_query(query, (f"{date}%",))
        return [dict(row) for row in results]

    def get_dates_with_messages(self, start_date: str, end_date: str) -> List[str]:
        """
        Get list of dates that have messages within a range.

        Args:
            start_date: Start date in YYYY-MM-DD format
            end_date: End date in YYYY-MM-DD format

        Returns:
            List of dates in YYYY-MM-DD format that have messages
        """
        query = """
            SELECT DISTINCT SUBSTR(timestamp, 1, 10) as date
            FROM messages
            WHERE SUBSTR(timestamp, 1, 10) >= ?
              AND SUBSTR(timestamp, 1, 10) <= ?
              AND (metadata IS NULL OR json_extract(metadata, '$.temporary') IS NULL)
            ORDER BY date ASC
        """
        results = self.execute_query(query, (start_date, end_date))
        return [row["date"] for row in results]

    def delete_daily_summary(self, date: str) -> bool:
        """
        Delete a daily summary.

        Args:
            date: Date string in YYYY-MM-DD format

        Returns:
            True if deleted
        """
        self.execute_write(
            "DELETE FROM daily_summaries WHERE date = ?",
            (date,)
        )
        return True

    # =========================================================================
    # NOTES OPERATIONS (Phase 11)
    # =========================================================================

    def get_all_notes(self) -> List[Dict]:
        """
        Get all notes, ordered by creation time.

        Returns:
            List[dict]: All note sections
        """
        results = self.execute_query(
            "SELECT * FROM notes ORDER BY created_at ASC"
        )
        return [dict(row) for row in results]

    def get_note(self, section: str) -> Optional[Dict]:
        """
        Get a note by section name.

        Args:
            section: Section name

        Returns:
            dict: Note data, or None if not found
        """
        results = self.execute_query(
            "SELECT * FROM notes WHERE section = ?",
            (section,)
        )
        return dict(results[0]) if results else None

    def set_note(self, section: str, content: str) -> int:
        """
        Create or replace a note section.

        Args:
            section: Section name
            content: Section content

        Returns:
            int: ID of the note
        """
        timestamp = datetime.now(timezone.utc).isoformat() + "Z"

        return self.execute_write(
            """INSERT OR REPLACE INTO notes (section, content, created_at, updated_at)
            VALUES (?,
                    ?,
                    COALESCE((SELECT created_at FROM notes WHERE section = ?), ?),
                    ?)""",
            (section, content, section, timestamp, timestamp)
        )

    def remove_note(self, section: str) -> bool:
        """
        Remove a note section.

        Args:
            section: Section name

        Returns:
            bool: True if removed, False if not found
        """
        rows_affected = self.execute_write(
            "DELETE FROM notes WHERE section = ?",
            (section,)
        )
        return rows_affected > 0

    def clear_notes(self) -> int:
        """
        Clear all notes.

        Returns:
            int: Number of notes removed
        """
        return self.execute_write("DELETE FROM notes")
