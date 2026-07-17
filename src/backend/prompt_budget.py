"""
Prompt budget estimation for model-aware context trimming.

Anthropic enforces the full request payload, not just Mneme's recent-message
budget. These helpers estimate that full payload locally every turn and reserve
space for output/thinking before deciding whether to trim.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from .model_capabilities import get_model_capabilities


EXACT_COUNT_MARGIN = 30_000
WARNING_MARGIN_STANDARD = 20_000
WARNING_MARGIN_EXTENDED = 50_000


@dataclass(frozen=True)
class PromptBudget:
    model: str
    context_window_tokens: int
    usable_input_tokens: int
    response_reserve_tokens: int
    thinking_reserve_tokens: int
    safety_margin_tokens: int
    warning_at_tokens: int
    exact_count_at_tokens: int
    supports_1m_context: bool


@dataclass(frozen=True)
class PromptSize:
    estimated_tokens: int
    exact_tokens: Optional[int] = None
    used_exact_count: bool = False

    @property
    def input_tokens(self) -> int:
        return self.exact_tokens if self.exact_tokens is not None else self.estimated_tokens


def build_prompt_budget(
    model: str,
    max_tokens: int,
    thinking_enabled: bool,
    thinking_budget: int,
) -> PromptBudget:
    """Compute an input budget after reserving room for output and thinking."""
    caps = get_model_capabilities(model)
    context_window = caps.context_window_tokens

    response_reserve = max(10_000, int(max_tokens or 0))
    response_reserve = min(response_reserve, 25_000 if caps.supports_1m_context else 15_000)

    if thinking_enabled:
        # Adaptive-thinking models do not expose a fixed budget. Keep a modest
        # reserve so "maximum" windows still leave room for hidden reasoning.
        thinking_reserve = max(10_000, int(thinking_budget or 0))
    else:
        thinking_reserve = 0
    thinking_reserve = min(thinking_reserve, 30_000 if caps.supports_1m_context else 15_000)

    safety_margin = 25_000 if caps.supports_1m_context else 10_000
    usable = max(10_000, context_window - response_reserve - thinking_reserve - safety_margin)
    warning_margin = WARNING_MARGIN_EXTENDED if caps.supports_1m_context else WARNING_MARGIN_STANDARD

    return PromptBudget(
        model=model,
        context_window_tokens=context_window,
        usable_input_tokens=usable,
        response_reserve_tokens=response_reserve,
        thinking_reserve_tokens=thinking_reserve,
        safety_margin_tokens=safety_margin,
        warning_at_tokens=max(10_000, usable - warning_margin),
        exact_count_at_tokens=max(10_000, usable - EXACT_COUNT_MARGIN),
        supports_1m_context=caps.supports_1m_context,
    )


def estimate_request_tokens(request: Dict[str, Any]) -> int:
    """
    Rough local estimate for an Anthropic Messages payload.

    Text uses the same simple char/4 heuristic already used elsewhere in Mneme;
    non-text blocks receive conservative overhead because images and documents
    are opaque to the local estimator.
    """
    return _estimate_value(request) + 256


def is_context_length_error(error: BaseException | str) -> bool:
    """Detect Anthropic context-window/prompt-too-long failures."""
    text = str(error).lower()
    markers = (
        "prompt is too long",
        "maximum context",
        "context length",
        "input is too long",
        "too many input tokens",
        "exceeds the context",
        "exceed context",
        "tokens exceed",
    )
    return any(marker in text for marker in markers)


def _estimate_value(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, str):
        return max(1, len(value) // 4)
    if isinstance(value, (int, float, bool)):
        return 1
    if isinstance(value, list):
        return 4 + sum(_estimate_value(item) for item in value)
    if isinstance(value, dict):
        block_type = value.get("type")
        overhead = 6
        if block_type == "image":
            overhead += 1_500
        elif block_type in ("document", "file"):
            overhead += 2_500
        elif block_type and block_type != "text":
            overhead += 400
        return overhead + sum(_estimate_value(v) for k, v in value.items() if k != "cache_control")
    return max(1, len(str(value)) // 4)
