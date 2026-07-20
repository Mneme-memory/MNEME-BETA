"""
Daily Summaries Module for Mneme Memory System (Phase 9)

Provides short-term timeline awareness through daily conversation summaries.
Generates outcomes-focused summaries of each day's conversations using Haiku,
and maintains a 7-day rolling window for temporal context.

DESIGN:
- Summaries stored permanently (for historical reference)
- Only last 7 days injected into prompt (~2400-2800 tokens)
- Generation happens in background (non-blocking)
- Uses first-person perspective for AI continuity

USAGE:
    manager = DailySummaryManager(config, database)

    # Check and generate missing summaries
    missing = manager.get_missing_days(days=7)
    for date in missing:
        manager.generate_summary(date)

    # Get formatted context for prompt
    timeline_context = manager.get_seven_day_block()
"""

from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
import json


class DailySummaryError(Exception):
    """Custom exception for daily summary errors."""
    pass


class DailySummaryManager:
    """
    Manages daily conversation summaries for timeline awareness.

    This class handles:
    - Generating summaries for individual days using Haiku
    - Detecting which days need summaries
    - Formatting the 7-day rolling window for prompt injection
    - Handling day rollover and cold starts
    """

    def __init__(self, config: Dict, database, ai_client=None):
        """
        Initialize daily summary manager.

        Args:
            config: Configuration dictionary
            database: Database instance
            ai_client: Optional AIClient instance (created if not provided)
        """
        self.config = config
        self.db = database
        self.ai_client = ai_client

        # Timeline configuration
        timeline_config = config.get("features", {}).get("timeline", {})
        self.enabled = timeline_config.get("enabled", False)
        self.days_to_show = timeline_config.get("days_to_show", 7)
        self.max_tokens_per_day = timeline_config.get("max_tokens_per_day", 400)
        self.summary_model = timeline_config.get("summary_model", "claude-haiku-4-5")
        self.temperature = timeline_config.get("temperature", 0.3)
        self.user_name = config.get("identity", {}).get("user_name", "") or "Human"

        # Token counting (lazy import)
        self._encoding = None

    def _get_encoding(self):
        """Lazy-load tiktoken encoding."""
        if self._encoding is None:
            try:
                import tiktoken
                self._encoding = tiktoken.get_encoding("cl100k_base")
            except ImportError:
                self._encoding = None
        return self._encoding

    def _count_tokens(self, text: str) -> int:
        """Count tokens in text."""
        if not text:
            return 0
        encoding = self._get_encoding()
        if encoding:
            return len(encoding.encode(text))
        return len(text) // 4  # Rough estimate

    def _get_ai_client(self):
        """Get or create AI client for Haiku calls."""
        if self.ai_client is not None:
            return self.ai_client

        # Create a new client for Haiku
        from .ai_client import AIClient
        anthropic_key = self.config.get("api_keys", {}).get("anthropic")
        if not anthropic_key or anthropic_key == "YOUR_ANTHROPIC_API_KEY_HERE":
            raise DailySummaryError("Anthropic API key not configured")

        self.ai_client = AIClient(
            api_key=anthropic_key,
            model=self.summary_model,
            temperature=self.temperature,
            max_tokens=max(800, self.max_tokens_per_day * 2)
        )
        return self.ai_client

    def get_missing_days(self, days: int = 7) -> List[str]:
        """
        Get list of dates that have messages but no summary.

        Args:
            days: Number of days to check (default 7)

        Returns:
            List of date strings (YYYY-MM-DD) needing summaries
        """
        if not self.enabled:
            return []

        # Calculate date range
        today = datetime.now(timezone.utc).date()
        start_date = today - timedelta(days=days)

        # Get dates with messages
        dates_with_messages = self.db.get_dates_with_messages(
            start_date.isoformat(),
            today.isoformat()
        )

        # Get dates with summaries
        existing_summaries = self.db.get_summaries_for_range(
            start_date.isoformat(),
            today.isoformat()
        )
        dates_with_summaries = {s["date"] for s in existing_summaries}

        # Find missing (exclude today - day not complete yet)
        today_str = today.isoformat()
        missing = [
            d for d in dates_with_messages
            if d not in dates_with_summaries and d != today_str
        ]

        return missing

    def generate_summary(self, date: str, show_progress: bool = True) -> Optional[Dict]:
        """
        Generate a summary for a specific date.

        Args:
            date: Date string in YYYY-MM-DD format
            show_progress: Whether to print progress messages

        Returns:
            Summary dict if successful, None if no messages or error

        COST: ~$0.04-0.06 per day (Haiku input + output)
        """
        if not self.enabled:
            return None

        # Get messages for this date
        messages = self.db.get_messages_for_date(date)

        if not messages:
            # No messages - save placeholder
            self.db.save_daily_summary(
                date=date,
                summary_text="No activity",
                token_count=2,
                message_count=0
            )
            return {"date": date, "summary": "No activity", "message_count": 0}

        if show_progress:
            print(f"  -> Generating summary for {date} ({len(messages)} messages)...")

        # Build prompt for Haiku
        prompt = self._build_summary_prompt(date, messages)

        try:
            # Call Haiku API
            client = self._get_ai_client()

            # Temporarily switch to summary model (try/finally ensures restore)
            # Note: not thread-safe if another thread uses the same ai_client concurrently
            original_model = client.model
            if client.model != self.summary_model:
                client.model = self.summary_model

            try:
                summary_text, usage, _ = client.call(
                    messages=[{"role": "user", "content": prompt}],
                    system=(
                        "You are a daily conversation summarizer. Your output must be ONLY bullet points — nothing else.\n\n"
                        "STRICT OUTPUT FORMAT:\n"
                        "- [past-tense fact or event]\n"
                        "- [past-tense fact or event]\n\n"
                        "DO NOT write: introductions, closing remarks, offers to help, role-play responses, "
                        "prose paragraphs, section headers, or any text outside the bullet points.\n"
                        "DO NOT respond as if you are the AI in the conversation.\n"
                        "START your response with '- ' immediately. Nothing before the first bullet."
                    )
                )
            finally:
                client.model = original_model

            # Count tokens in generated summary
            token_count = self._count_tokens(summary_text)

            # Save to database
            self.db.save_daily_summary(
                date=date,
                summary_text=summary_text.strip(),
                token_count=token_count,
                message_count=len(messages)
            )

            if show_progress:
                print(f"  -> Summary generated ({token_count} tokens)")

            return {
                "date": date,
                "summary": summary_text.strip(),
                "message_count": len(messages),
                "token_count": token_count
            }

        except Exception as e:
            print(f"  -> Summary generation failed for {date}: {e}")
            return None

    def _build_summary_prompt(self, date: str, messages: List[Dict]) -> str:
        """
        Build the prompt for Haiku to generate a daily summary.

        Args:
            date: Date being summarized
            messages: List of message dictionaries

        Returns:
            Formatted prompt string
        """
        # Format messages
        formatted_messages = []
        for msg in messages:
            sender = msg["sender"]
            content = msg["content"]
            timestamp = msg.get("timestamp", "")[:16]  # YYYY-MM-DDTHH:MM

            # Truncate very long messages (same limit as embeddings: 15K chars)
            if len(content) > 15000:
                content = content[:14997] + "..."

            formatted_messages.append(f"[{timestamp}] {sender}: {content}")

        messages_text = "\n\n".join(formatted_messages)

        target_tokens = self.max_tokens_per_day // 2

        prompt = f"""Summarize this day's conversation focusing on OUTCOMES and EVENTS.

Voice and perspective:
- Use first person ("I") for things the AI said/did/suggested
- Use "{self.user_name}" for things they said/did
- Example: "I helped {self.user_name} debug the auth issue. We decided on JWT."

Include:
- Decisions made
- Events that happened
- Topics discussed
- Open threads/unfinished work
- Key information shared by either party

Do NOT include:
- Conversational pleasantries
- Redundant details
- Meta-discussion about the conversation itself

Format: 2-5 bullet points, past tense, target ~{target_tokens} tokens total.
Output ONLY the bullet points. No preamble, no closing remarks, no offers to help.

Date: {date}
User's name: {self.user_name}

Messages:
{messages_text}

Start with "- " immediately."""

        return prompt

    def get_seven_day_block(self) -> str:
        """
        Get formatted summary block for prompt injection.

        Shows the N most recent days that have real summaries (not "No activity"),
        plus a today marker. For sparse users this reaches further back to fill
        slots with meaningful content instead of wasting tokens on empty days.

        Returns:
            Formatted string for the timeline section, or empty string if disabled

        FORMAT:
        === RECENT ACTIVITY ===
        Mar 12 (Wed): Worked on the auth refactor. Decided on JWT approach.
        Mar 15 (Sat): Fixed login validation bug. Mikael mentioned deadline.
        Mar 18 (Tue): Resumed auth work. Reviewed PR and suggested improvements.
        Mar 21 (Fri): [Today - current session]
        """
        if not self.enabled:
            return ""

        today = datetime.now(timezone.utc).date()

        # Fetch the N most recent real summaries (skip "No activity" placeholders)
        summaries = self.db.execute_query(
            "SELECT date, summary_text FROM daily_summaries "
            "WHERE summary_text != 'No activity' AND date < ? "
            "ORDER BY date DESC LIMIT ?",
            (today.isoformat(), self.days_to_show)
        )

        # Format oldest-first
        lines = []
        for s in reversed(summaries):
            d = datetime.strptime(s["date"], "%Y-%m-%d").date()
            lines.append(f"{d.strftime('%b %d')} ({d.strftime('%a')}): {s['summary_text']}")

        # Today marker
        lines.append(f"{today.strftime('%b %d')} ({today.strftime('%a')}): [Today - current session]")

        if len(lines) <= 1:
            # Only today marker, no summaries yet
            return ""

        header = "=== RECENT ACTIVITY ==="
        return f"{header}\n" + "\n".join(lines) + "\n"

    def check_and_generate_missing(self, show_progress: bool = True) -> int:
        """
        Check for and generate any missing summaries.

        This is the main entry point for cold start and startup checks.

        Args:
            show_progress: Whether to print progress messages

        Returns:
            Number of summaries generated
        """
        if not self.enabled:
            return 0

        missing = self.get_missing_days(self.days_to_show)

        if not missing:
            return 0

        if show_progress:
            print(f"Generating {len(missing)} missing daily summaries...")

        generated = 0
        for date in missing:
            result = self.generate_summary(date, show_progress=show_progress)
            if result:
                generated += 1

        return generated

    def check_day_rollover(self) -> bool:
        """
        Generate daily summaries for past days that have left active context.

        Skips days whose messages are still in active tier (AI sees them verbatim),
        days with no messages, and days that already have summaries.
        Walks back up to days_to_show days from yesterday.

        Returns:
            True if any summaries were generated
        """
        if not self.enabled:
            return False

        today = datetime.now(timezone.utc).date()
        generated_any = False

        for days_ago in range(1, self.days_to_show + 1):
            date_str = (today - timedelta(days=days_ago)).isoformat()

            # Already summarized — skip this day but keep checking older days
            if self.db.get_daily_summary(date_str):
                continue

            # No messages that day — skip (don't create "No activity" placeholders)
            messages = self.db.get_messages_for_date(date_str)
            if not messages:
                continue

            # Any messages still in active tier — AI sees them verbatim, skip
            active_count = self.db.execute_query(
                "SELECT COUNT(*) as n FROM messages WHERE timestamp LIKE ? AND tier = 'active'",
                (f"{date_str}%",)
            )
            if active_count and active_count[0]["n"] > 0:
                continue

            self.generate_summary(date_str, show_progress=True)
            generated_any = True

        return generated_any

    def get_last_message_date(self) -> Optional[str]:
        """
        Get the date of the most recent message.

        Returns:
            Date string (YYYY-MM-DD) or None if no messages
        """
        result = self.db.execute_query("""
            SELECT MAX(SUBSTR(timestamp, 1, 10)) as last_date
            FROM messages
            WHERE (metadata IS NULL OR json_extract(metadata, '$.temporary') IS NULL)
        """)
        if result and result[0]["last_date"]:
            return result[0]["last_date"]
        return None


if __name__ == "__main__":
    """
    Test the daily summaries module.
    """
    print("Daily Summaries module loaded successfully!")
    print("\nFeatures:")
    print("  - 7-day rolling window of daily summaries")
    print("  - Outcomes-focused, first-person perspective")
    print("  - Background generation (non-blocking)")
    print("  - ~$0.04-0.06 per day generation cost")
    print("  - ~2400-2800 tokens in prompt")
    print("\nTo use:")
    print("  from daily_summaries import DailySummaryManager")
    print("  manager = DailySummaryManager(config, database)")
    print("  manager.check_and_generate_missing()")
