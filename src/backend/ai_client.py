"""
AI Client Module for Mneme Memory System

Handles all Anthropic API interactions:
- Non-streaming API calls
- Streaming API calls with chunk handling
- Response parsing (handling multiple content blocks)
- Usage/cost tracking

This module isolates API interaction from prompt building and caching logic.

USAGE:
    client = AIClient(anthropic_key, model, temperature, max_tokens)
    response = client.call(messages, system=system_text)
    # Or with streaming:
    for chunk in client.call_stream(messages, system=system_text):
        print(chunk, end="")
"""

import sys
from typing import Dict, List, Optional, Generator, Any, Tuple
from dataclasses import dataclass


# Cost per million tokens
# Full model names for exact matching
MODEL_COSTS = {
    "claude-opus-4-6": {"input": 15.0, "output": 75.0},
    "claude-sonnet-4-6": {"input": 3.0, "output": 15.0},
    "claude-opus-4-5": {"input": 15.0, "output": 75.0},
    "claude-sonnet-4-5": {"input": 3.0, "output": 15.0},
    "claude-haiku-4-5": {"input": 0.80, "output": 4.0},
}

# Fallback patterns for partial matching (checked in order)
MODEL_COST_FALLBACKS = [
    ("opus", {"input": 15.0, "output": 75.0}),
    ("haiku", {"input": 0.80, "output": 4.0}),
    ("sonnet", {"input": 3.0, "output": 15.0}),
]

# Default if nothing matches
DEFAULT_MODEL_COST = {"input": 3.0, "output": 15.0}  # Sonnet pricing


@dataclass
class APIUsage:
    """Tracks API usage for a single call."""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    cost: float = 0.0

    def calculate_cost(self, model: str) -> float:
        """Calculate cost based on model pricing."""
        model_lower = model.lower()

        # 1. Try exact match first
        costs = MODEL_COSTS.get(model)

        # 2. Try fallback patterns (in defined order)
        if costs is None:
            for pattern, pricing in MODEL_COST_FALLBACKS:
                if pattern in model_lower:
                    costs = pricing
                    break

        # 3. Use default if nothing matched
        if costs is None:
            costs = DEFAULT_MODEL_COST

        self.cost = (
            (self.input_tokens / 1_000_000 * costs["input"]) +
            (self.output_tokens / 1_000_000 * costs["output"]) +
            (self.cache_creation_tokens / 1_000_000 * costs["input"] * 1.25) +
            (self.cache_read_tokens / 1_000_000 * costs["input"] * 0.1)
        )
        return self.cost


class AIClientError(Exception):
    """Custom exception for AI client errors."""
    pass


class AIClient:
    """
    Handles Anthropic API interactions.

    This class:
    - Makes API calls (streaming and non-streaming)
    - Parses responses (handling multiple content blocks)
    - Tracks usage and costs
    - Provides clean interface for conversation manager
    """

    def __init__(self, api_key: str, model: str, temperature: float = 1.0, max_tokens: int = 4096, timeout: float = 180.0):
        """
        Initialize AI client.

        Args:
            api_key: Anthropic API key
            model: Model ID (e.g., "claude-sonnet-4-5")
            temperature: Sampling temperature (0-2)
            max_tokens: Maximum response tokens
            timeout: Request timeout in seconds
        """
        try:
            import anthropic
            self.client = anthropic.Anthropic(api_key=api_key)
        except ImportError:
            raise AIClientError("anthropic package not installed")

        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout

        # Statistics
        self.stats = {
            "total_calls": 0,
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "total_cache_read_tokens": 0,
            "total_cache_write_tokens": 0,
            "total_cost": 0.0
        }

    def call(
        self,
        messages: List[Dict],
        system: Any = None,
        tools: List[Dict] = None,
        extra_headers: Dict = None,
        thinking: Optional[Dict] = None
    ) -> Tuple[str, APIUsage, str]:
        """
        Make a non-streaming API call.

        Args:
            messages: List of message dicts [{"role": "user/assistant", "content": "..."}]
            system: System prompt (string or list of blocks)
            tools: Optional tools list (for MCP)
            extra_headers: Additional headers (e.g., cache control)
            thinking: Optional thinking config {"type": "enabled", "budget_tokens": N}

        Returns:
            tuple: (response_text, usage, thinking_text)

        Raises:
            AIClientError: If API call fails
        """
        self.stats["total_calls"] += 1

        # Build API parameters
        params = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "messages": messages,
            "timeout": self.timeout
        }

        # When thinking is enabled, temperature must be 1 (or omitted)
        if thinking:
            params["thinking"] = thinking
        else:
            params["temperature"] = self.temperature

        if system is not None:
            params["system"] = system

        if tools:
            params["tools"] = tools

        if extra_headers:
            params["extra_headers"] = extra_headers

        try:
            response = self.client.messages.create(**params)

            # Parse response - handle multiple content blocks (including thinking)
            text, thinking_text = self._extract_response(response)

            # Track usage
            usage = self._extract_usage(response)
            usage.calculate_cost(self.model)
            self._update_stats(usage)

            return text, usage, thinking_text

        except Exception as e:
            raise AIClientError(f"API call failed: {str(e)}") from e

    def call_stream(
        self,
        messages: List[Dict],
        system: Any = None,
        tools: List[Dict] = None,
        extra_headers: Dict = None,
        thinking: Optional[Dict] = None
    ) -> Generator[Dict, None, Tuple[str, APIUsage]]:
        """
        Make a streaming API call.

        Args:
            messages: List of message dicts
            system: System prompt (string or list of blocks)
            tools: Optional tools list
            extra_headers: Additional headers
            thinking: Optional thinking config {"type": "enabled", "budget_tokens": N}

        Yields:
            dict: Stream events {"type": "chunk/start/end/thinking_start/thinking", "data": ...}

        Returns (via generator close):
            tuple: (full_response, usage)
        """
        self.stats["total_calls"] += 1

        # Build API parameters
        params = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "messages": messages,
            "timeout": self.timeout,
            "stream": True
        }

        # When thinking is enabled, temperature must be 1 (or omitted)
        if thinking:
            params["thinking"] = thinking
        else:
            params["temperature"] = self.temperature

        if system is not None:
            params["system"] = system

        if tools:
            params["tools"] = tools

        if extra_headers:
            params["extra_headers"] = extra_headers

        try:
            stream = self.client.messages.create(**params)

            full_response = ""
            full_thinking = ""
            usage = APIUsage()
            current_block_type = None  # Track whether we're in a "thinking" or "text" block

            for event in stream:
                if event.type == "message_start":
                    # Capture initial usage (contains cache metrics)
                    if hasattr(event, 'message') and hasattr(event.message, 'usage'):
                        usage.input_tokens = getattr(event.message.usage, 'input_tokens', 0)
                        usage.cache_creation_tokens = getattr(event.message.usage, 'cache_creation_input_tokens', 0)
                        usage.cache_read_tokens = getattr(event.message.usage, 'cache_read_input_tokens', 0)
                    yield {"type": "start", "data": None}

                elif event.type == "content_block_start":
                    block = event.content_block
                    block_type = getattr(block, 'type', None)
                    if block_type == "thinking":
                        current_block_type = "thinking"
                        yield {"type": "thinking_start", "data": None}
                    elif block_type == "text":
                        current_block_type = "text"

                elif event.type == "content_block_delta":
                    delta = event.delta
                    delta_type = getattr(delta, 'type', None)

                    if delta_type == "thinking_delta":
                        thinking_chunk = delta.thinking
                        full_thinking += thinking_chunk
                        yield {"type": "thinking", "data": thinking_chunk}
                    elif delta_type == "text_delta":
                        chunk = delta.text
                        full_response += chunk
                        yield {"type": "chunk", "data": chunk}

                elif event.type == "content_block_stop":
                    current_block_type = None

                elif event.type == "message_delta":
                    # Update output tokens
                    if hasattr(event, 'usage'):
                        usage.output_tokens = getattr(event.usage, 'output_tokens', 0)

            # Calculate cost and update stats
            usage.calculate_cost(self.model)
            self._update_stats(usage)

            yield {"type": "end", "data": {"response": full_response, "usage": usage, "thinking": full_thinking}}

        except Exception as e:
            raise AIClientError(f"Streaming API call failed: {str(e)}") from e

    def _extract_response(self, response) -> Tuple[str, str]:
        """
        Extract text and thinking from API response.

        Handles multiple content blocks including thinking blocks.

        Args:
            response: Anthropic API response

        Returns:
            tuple: (combined_text, thinking_text)
        """
        text_parts = []
        thinking_parts = []

        for block in response.content:
            block_type = getattr(block, 'type', None)

            if block_type == 'thinking' and hasattr(block, 'thinking'):
                thinking_parts.append(block.thinking)
            elif block_type == 'text' and hasattr(block, 'text'):
                text_parts.append(block.text)
            elif hasattr(block, 'text') and block_type is None:
                # Fallback for blocks without explicit type
                text_parts.append(block.text)

        text = '\n\n'.join(text_parts) if text_parts else ""
        thinking = '\n\n'.join(thinking_parts) if thinking_parts else ""
        return text, thinking

    def _extract_usage(self, response) -> APIUsage:
        """
        Extract usage statistics from API response.

        Args:
            response: Anthropic API response

        Returns:
            APIUsage: Usage statistics
        """
        return APIUsage(
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            cache_creation_tokens=getattr(response.usage, 'cache_creation_input_tokens', 0),
            cache_read_tokens=getattr(response.usage, 'cache_read_input_tokens', 0)
        )

    def _update_stats(self, usage: APIUsage):
        """Update cumulative statistics."""
        self.stats["total_input_tokens"] += usage.input_tokens
        self.stats["total_output_tokens"] += usage.output_tokens
        self.stats["total_cache_read_tokens"] += usage.cache_read_tokens
        self.stats["total_cache_write_tokens"] += usage.cache_creation_tokens
        self.stats["total_cost"] += usage.cost

    def get_statistics(self) -> Dict:
        """Get cumulative statistics."""
        return self.stats.copy()

    def update_model(self, model: str):
        """Update the model being used."""
        self.model = model

    def update_temperature(self, temperature: float):
        """Update the temperature setting."""
        self.temperature = temperature

    def update_max_tokens(self, max_tokens: int):
        """Update the max tokens setting."""
        self.max_tokens = max_tokens
