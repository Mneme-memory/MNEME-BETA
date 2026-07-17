"""
Model capability helpers for Anthropic request budgeting.

Keep this conservative: unknown models should behave like 200k-context models
until explicitly identified.
"""

from dataclasses import dataclass


ONE_M_CONTEXT_TOKENS = 1_000_000
STANDARD_CONTEXT_TOKENS = 200_000


_ONE_M_CONTEXT_MARKERS = (
    "fable",
    "opus-4-8",
    "opus-4-7",
    "opus-4-6",
    "sonnet-5",
    "sonnet-4-6",
)


@dataclass(frozen=True)
class ModelCapabilities:
    model: str
    context_window_tokens: int
    supports_1m_context: bool


def get_model_capabilities(model: str) -> ModelCapabilities:
    """Return conservative context capabilities for a model id."""
    model_id = model or ""
    model_lower = model_id.lower()
    supports_1m = any(marker in model_lower for marker in _ONE_M_CONTEXT_MARKERS)

    return ModelCapabilities(
        model=model_id,
        context_window_tokens=ONE_M_CONTEXT_TOKENS if supports_1m else STANDARD_CONTEXT_TOKENS,
        supports_1m_context=supports_1m,
    )


def max_recent_window_for_model(model: str) -> int:
    """Largest user-selectable recent-history window for this model."""
    caps = get_model_capabilities(model)
    return 850_000 if caps.supports_1m_context else 125_000
