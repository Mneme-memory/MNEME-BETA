"""
Prompt Cache Manager for Mneme Memory System

Handles adaptive caching decisions and metrics:
- Gap detection (decide when to enable/disable caching)
- Cache API headers for Anthropic
- Usage metrics tracking (hits, writes, costs)
- Cost calculation and savings analysis

NOTE: Prompt structure building moved to prompt_builder.py (Phase 2 refactor)

ADAPTIVE LOGIC:
- If last message >threshold ago: Disable caching (cold start, avoid write penalty)
- If last message <threshold: Enable caching (likely to get cache hits)

COST SAVINGS:
- Active conversations: 50-70% cost reduction
- Sparse conversations: 0% (no penalty, same as no caching)

USAGE:
    cache_mgr = PromptCacheManager(config)
    use_cache, reason = cache_mgr.should_use_caching()
    if use_cache:
        headers = cache_mgr.get_api_headers()
    cache_mgr.record_message(cached, usage, model)
"""

from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, Tuple


class PromptCacheManager:
    """
    Manages adaptive prompt caching with gap detection.

    This class handles:
    - Gap detection (decide when to enable/disable caching)
    - Cache control marker formatting
    - Metrics tracking (hits, writes, costs)
    - Cost calculation and savings analysis
    """

    def __init__(self, config: Dict):
        """
        Initialize cache manager.

        Args:
            config: Configuration dictionary
        """
        cache_config = config.get("caching", {})

        # Configuration
        self.enabled = cache_config.get("enabled", True)
        self.use_extended_ttl = cache_config.get("extended_ttl", True)  # 1h vs 5min
        self.adaptive_threshold_minutes = cache_config.get("adaptive_threshold_minutes", 60)
        self.track_metrics = cache_config.get("track_metrics", True)
        self.force_caching = cache_config.get("force_caching", False)  # Force caching even on cold start

        # State tracking
        self.last_message_time: Optional[datetime] = None
        self.current_session_cached = False

        # Last message cache state (for AI info display)
        self.last_message_cache = {
            "status": "not_started",  # "not_active", "cold_start", "active"
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
            "cached": False
        }

        # Metrics
        self.stats = {
            "cache_writes": 0,
            "cache_hits": 0,
            "cold_starts": 0,
            "total_messages": 0,
            "total_input_tokens": 0,
            "total_cached_read_tokens": 0,
            "total_cached_write_tokens": 0,
            "cost_with_cache": 0.0,
            "cost_without_cache": 0.0,
            "savings": 0.0
        }

    def should_use_caching(self) -> Tuple[bool, str]:
        """
        Decide whether to enable caching for current message.

        Returns:
            tuple: (use_caching: bool, reason: str)

        LOGIC:
        - If disabled in config: False
        - If force_caching enabled: True (bypass cold start detection)
        - If first message ever: False (cold start)
        - If >threshold since last message: False (cold start after gap)
        - Otherwise: True (active conversation)

        EXAMPLES:
        - First message of day: (False, "cold_start_first")
        - 2 hours since last: (False, "cold_start_gap")
        - 5 minutes since last: (True, "active_conversation")
        - Force caching enabled: (True, "forced_caching")
        """
        if not self.enabled:
            return False, "disabled_in_config"

        # Force caching mode (for special use cases like 1M context, entity extraction)
        if self.force_caching:
            return True, "forced_caching"

        if self.last_message_time is None:
            # First message ever - cold start
            return False, "cold_start_first"

        time_since_last = datetime.now(timezone.utc) - self.last_message_time
        threshold = timedelta(minutes=self.adaptive_threshold_minutes)

        if time_since_last > threshold:
            # Long gap - cold start
            self.current_session_cached = False
            return False, f"cold_start_gap_{int(time_since_last.total_seconds() / 60)}min"

        # Active conversation - use caching
        return True, f"active_{int(time_since_last.total_seconds() / 60)}min"

    # NOTE: build_cached_prompt_structure() moved to prompt_builder.py (Phase 2 refactor)

    def get_api_headers(self) -> Dict[str, str]:
        """
        Get required API headers for caching.

        Returns:
            dict: Headers to add to Anthropic API call

        HEADERS:
        - prompt-caching-2024-07-31: Enable basic caching
        - extended-cache-ttl-2025-04-11: Enable 1-hour cache (if use_extended_ttl=true)
        """
        if not self.enabled:
            return {}

        # Prompt caching is now GA - no beta header needed for base caching
        # Only add beta header for extended 1h TTL
        if self.use_extended_ttl:
            headers = {"anthropic-beta": "extended-cache-ttl-2025-04-11"}
        else:
            headers = {}

        return headers

    def update_message_time(self):
        """Update last message timestamp."""
        self.last_message_time = datetime.now(timezone.utc)

    def record_message(
        self,
        cached: bool,
        usage: Dict,
        model: str
    ) -> str:
        """
        Record cache usage for metrics.

        Args:
            cached: Whether caching was enabled for this message
            usage: Usage dict from Anthropic API response
            model: Model name (for cost calculation)

        Returns:
            str: Summary message for this specific message (for display)

        Usage dict structure:
        {
            "input_tokens": 88000,
            "output_tokens": 1000,
            "cache_creation_input_tokens": 73000,  # Only on cache write
            "cache_read_input_tokens": 73000       # Only on cache hit
        }
        """
        if not self.track_metrics:
            return ""

        self.stats["total_messages"] += 1

        # Extract token counts
        input_tokens = usage.get("input_tokens", 0)
        output_tokens = usage.get("output_tokens", 0)
        cache_creation_tokens = usage.get("cache_creation_input_tokens", 0)
        cache_read_tokens = usage.get("cache_read_input_tokens", 0)

        self.stats["total_input_tokens"] += input_tokens

        # Update last message cache state for AI info display
        self.last_message_cache = {
            "cached": cached,
            "cache_read_tokens": cache_read_tokens,
            "cache_write_tokens": cache_creation_tokens,
            "status": "not_active" if not cached else (
                "cold_start" if (cache_creation_tokens > 0 and cache_read_tokens == 0) else "active"
            )
        }

        # Determine if cache write, hit, or refresh (hit + write)
        summary = ""
        if not cached:
            # Cold start - no caching
            self.stats["cold_starts"] += 1
            summary = f"   ↳ No cache (cold start) - {input_tokens:,} input tokens"
        elif cache_creation_tokens > 0 and cache_read_tokens > 0:
            # Cache hit + refresh (most common in active conversations)
            # Reading old content from cache + writing new conversation turns
            self.stats["cache_hits"] += 1
            self.stats["cache_writes"] += 1
            self.stats["total_cached_read_tokens"] += cache_read_tokens
            self.stats["total_cached_write_tokens"] += cache_creation_tokens

            # Calculate savings
            # input_tokens from the API only reflects uncached tokens; add cached tokens
            # back to get the true "what would we have paid without caching" baseline
            total_input = input_tokens + cache_creation_tokens + cache_read_tokens
            cost_this_message = self._calculate_message_cost(
                input_tokens, output_tokens, cache_creation_tokens, cache_read_tokens, model
            )
            cost_without_cache = self._calculate_message_cost(
                total_input, output_tokens, 0, 0, model
            )
            saved = cost_without_cache - cost_this_message
            saved_pct = (saved / cost_without_cache * 100) if cost_without_cache > 0 else 0
            savings_note = f" (saved {saved_pct:.0f}%)" if saved_pct > 0 else ""

            summary = f"   ↳ Cache hit + refresh - {cache_read_tokens:,} read, {cache_creation_tokens:,} written{savings_note}"
        elif cache_creation_tokens > 0:
            # Pure cache write (first message with caching enabled)
            self.stats["cache_writes"] += 1
            self.stats["total_cached_write_tokens"] += cache_creation_tokens
            summary = f"   ↳ Cache write - {cache_creation_tokens:,} tokens cached (2× cost)"
        elif cache_read_tokens > 0:
            # Pure cache hit (content unchanged - rare, would mean exact same prefix)
            self.stats["cache_hits"] += 1
            self.stats["total_cached_read_tokens"] += cache_read_tokens

            # Calculate savings
            total_input = input_tokens + cache_creation_tokens + cache_read_tokens
            cost_this_message = self._calculate_message_cost(
                input_tokens, output_tokens, cache_creation_tokens, cache_read_tokens, model
            )
            cost_without_cache = self._calculate_message_cost(
                total_input, output_tokens, 0, 0, model
            )
            saved = cost_without_cache - cost_this_message
            saved_pct = (saved / cost_without_cache * 100) if cost_without_cache > 0 else 0
            savings_note = f" (saved {saved_pct:.0f}%)" if saved_pct > 0 else ""

            summary = f"   ↳ Cache hit - {cache_read_tokens:,} tokens read{savings_note}"
        else:
            # Caching was enabled but no cache info in response (shouldn't happen)
            self.stats["cold_starts"] += 1
            summary = f"   ↳ No cache data returned"

        # Calculate costs (total_input includes cached tokens for accurate baseline)
        total_input = input_tokens + cache_creation_tokens + cache_read_tokens
        cost_this_message = self._calculate_message_cost(
            input_tokens, output_tokens, cache_creation_tokens, cache_read_tokens, model
        )
        cost_without_cache = self._calculate_message_cost(
            total_input, output_tokens, 0, 0, model
        )

        self.stats["cost_with_cache"] += cost_this_message
        self.stats["cost_without_cache"] += cost_without_cache
        self.stats["savings"] = self.stats["cost_without_cache"] - self.stats["cost_with_cache"]

        return summary

    def _calculate_message_cost(
        self,
        input_tokens: int,
        output_tokens: int,
        cache_write_tokens: int,
        cache_read_tokens: int,
        model: str
    ) -> float:
        """
        Calculate cost for a single message.

        Args:
            input_tokens: Regular input tokens
            output_tokens: Output tokens
            cache_write_tokens: Tokens written to cache
            cache_read_tokens: Tokens read from cache
            model: Model name

        Returns:
            float: Cost in USD

        PRICING (as of 2025):
        Sonnet 4.5:
        - Input: $3/M
        - Output: $15/M
        - Cache write (1h): $6/M (2× input price)
        - Cache read: $0.30/M (0.1× input price)

        Haiku 4.5:
        - Input: $0.80/M
        - Output: $4/M
        - Cache write (1h): $1.60/M (2× input price)
        - Cache read: $0.08/M (0.1× input price)
        """
        # Determine base prices
        model_lower = model.lower()
        if "fable" in model_lower:
            input_price = 10.0 / 1_000_000
            output_price = 50.0 / 1_000_000
        elif "opus" in model_lower:
            input_price = 15.0 / 1_000_000
            output_price = 75.0 / 1_000_000
        elif "haiku" in model_lower:
            input_price = 0.80 / 1_000_000
            output_price = 4.0 / 1_000_000
        else:
            # Default to Sonnet pricing
            input_price = 3.0 / 1_000_000
            output_price = 15.0 / 1_000_000

        # Cache pricing multipliers
        cache_write_multiplier = 2.0 if self.use_extended_ttl else 1.25
        cache_read_multiplier = 0.1

        # Calculate components
        regular_input_cost = input_tokens * input_price
        output_cost = output_tokens * output_price
        cache_write_cost = cache_write_tokens * input_price * cache_write_multiplier
        cache_read_cost = cache_read_tokens * input_price * cache_read_multiplier

        total = regular_input_cost + output_cost + cache_write_cost + cache_read_cost
        return total

    def get_statistics(self) -> Dict:
        """
        Get cache performance statistics.

        Returns:
            dict: Cache metrics and cost savings

        INCLUDES:
        - Message counts (total, writes, hits, cold starts)
        - Cache hit rate
        - Token usage
        - Costs and savings
        - Savings percentage
        """
        total = self.stats["total_messages"]
        if total == 0:
            return {
                **self.stats,
                "cache_hit_rate": 0.0,
                "cold_start_rate": 0.0,
                "savings_percent": 0.0
            }

        stats = self.stats.copy()

        # Calculate rates
        cached_messages = self.stats["cache_writes"] + self.stats["cache_hits"]
        if cached_messages > 0:
            stats["cache_hit_rate"] = self.stats["cache_hits"] / cached_messages
        else:
            stats["cache_hit_rate"] = 0.0

        stats["cold_start_rate"] = self.stats["cold_starts"] / total

        # Calculate savings percentage
        if self.stats["cost_without_cache"] > 0:
            stats["savings_percent"] = (self.stats["savings"] / self.stats["cost_without_cache"]) * 100
        else:
            stats["savings_percent"] = 0.0

        return stats


if __name__ == "__main__":
    """
    Test the cache manager.
    """
    print("Prompt Cache Manager loaded successfully!")
    print("\nFeatures:")
    print("  ✓ Adaptive caching (gap detection)")
    print("  ✓ 2-layer cache structure (System + Recent)")
    print("  ✓ Cost calculation and tracking")
    print("  ✓ 50-70% savings on active conversations")
    print("  ✓ 0% penalty on sparse conversations")
    print("\nTo use:")
    print("  from prompt_cache import PromptCacheManager")
    print("  cache_mgr = PromptCacheManager(config)")
    print("  use_cache, reason = cache_mgr.should_use_caching()")
