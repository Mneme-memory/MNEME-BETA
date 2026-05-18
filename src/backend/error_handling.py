"""
Error Handling & Retry Logic for Mneme Memory System

This module provides centralized error handling, retry logic, and graceful
degradation for API calls (OpenAI, Anthropic).

RETRY STRATEGY:
- Exponential backoff: 1s, 2s, 4s, 8s, 16s
- Max 5 retries by default
- Specific handling for rate limits, timeouts, API errors
- Graceful degradation when retries exhausted

USAGE:
    from error_handling import retry_with_backoff, handle_api_error

    @retry_with_backoff(max_retries=3)
    def my_api_call():
        return client.messages.create(...)
"""

import time
import functools
from typing import Callable, Any, Optional, Tuple
import sys


# ============================================================================
# Custom Exception Classes
# ============================================================================

class MnemeAPIError(Exception):
    """Base exception for all API-related errors."""
    pass


class RateLimitError(MnemeAPIError):
    """API rate limit exceeded."""
    pass


class APITimeoutError(MnemeAPIError):
    """API request timed out."""
    pass


class AuthenticationError(MnemeAPIError):
    """API authentication failed (invalid key)."""
    pass


class QuotaExceededError(MnemeAPIError):
    """API quota/credits exhausted."""
    pass


class ServiceUnavailableError(MnemeAPIError):
    """API service temporarily unavailable."""
    pass


# ============================================================================
# Retry Decorator with Exponential Backoff
# ============================================================================

def retry_with_backoff(
    max_retries: int = 5,
    initial_delay: float = 1.0,
    max_delay: float = 60.0,
    exponential_base: float = 2.0,
    retry_on: Optional[Tuple[type, ...]] = None
):
    """
    Decorator that retries a function with exponential backoff.

    Args:
        max_retries: Maximum number of retry attempts (default: 5)
        initial_delay: Initial delay in seconds (default: 1.0)
        max_delay: Maximum delay between retries (default: 60.0)
        exponential_base: Base for exponential backoff (default: 2.0)
        retry_on: Tuple of exception types to retry on (default: all exceptions)

    Returns:
        Decorator function

    RETRY DELAYS:
    - Attempt 1: 1s
    - Attempt 2: 2s
    - Attempt 3: 4s
    - Attempt 4: 8s
    - Attempt 5: 16s (or max_delay if lower)

    EXAMPLE:
        @retry_with_backoff(max_retries=3)
        def call_api():
            return client.messages.create(...)
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            last_exception = None

            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)

                except Exception as e:
                    last_exception = e

                    # Check if we should retry this exception
                    if retry_on and not isinstance(e, retry_on):
                        raise

                    # Check if this is the last attempt
                    if attempt == max_retries:
                        raise

                    # Calculate delay with exponential backoff
                    delay = min(
                        initial_delay * (exponential_base ** attempt),
                        max_delay
                    )

                    # Classify error and adjust delay if needed
                    error_type, suggested_delay = classify_error(e)
                    if error_type == "Authentication Failed":
                        raise  # Non-recoverable, don't waste time retrying
                    if suggested_delay:
                        delay = suggested_delay

                    # Log retry attempt
                    error_preview = str(e)[:500] if len(str(e)) > 500 else str(e)
                    print(
                        f"  ⚠️  {error_type}: {error_preview}",
                        file=sys.stderr,
                        flush=True
                    )
                    print(
                        f"  ↻ Retry {attempt + 1}/{max_retries} in {delay:.1f}s...",
                        file=sys.stderr,
                        flush=True
                    )

                    time.sleep(delay)

            # This should never be reached, but just in case
            raise last_exception

        return wrapper
    return decorator


# ============================================================================
# Error Classification
# ============================================================================

def classify_error(error: Exception) -> Tuple[str, Optional[float]]:
    """
    Classify an error and suggest retry delay.

    Args:
        error: The exception to classify

    Returns:
        Tuple of (error_type_string, suggested_delay_seconds)
        suggested_delay is None if default exponential backoff should be used

    CLASSIFICATIONS:
    - Rate Limit: Wait longer (60s recommended)
    - Timeout: Short retry (2s)
    - Authentication: Don't retry (immediate failure)
    - Service Unavailable: Medium retry (10s)
    - Unknown: Use default backoff
    """
    error_str = str(error).lower()
    error_type = type(error).__name__

    # Check for specific error patterns
    if "rate" in error_str and "limit" in error_str:
        return ("Rate Limit", 60.0)

    if "timeout" in error_str or "timed out" in error_str:
        return ("Timeout", 2.0)

    if "authentication" in error_str or "invalid api key" in error_str or "401" in error_str:
        return ("Authentication Failed", None)  # Don't retry

    if "quota" in error_str or "exceeded" in error_str or "429" in error_str:
        return ("Quota Exceeded", 60.0)

    if "503" in error_str or "service unavailable" in error_str or "502" in error_str:
        return ("Service Unavailable", 10.0)

    if "500" in error_str or "internal server error" in error_str:
        return ("Server Error", 5.0)

    if "connection" in error_str or "network" in error_str:
        return ("Network Error", 3.0)

    # Unknown error - use default backoff
    return (error_type, None)


# ============================================================================
# API-Specific Error Handlers
# ============================================================================

def handle_anthropic_error(error: Exception) -> MnemeAPIError:
    """
    Convert Anthropic-specific errors to Mneme error types.

    Args:
        error: The Anthropic API exception

    Returns:
        MnemeAPIError: Classified error

    ANTHROPIC ERROR TYPES:
    - RateLimitError: 429 status
    - AuthenticationError: 401 status
    - BadRequestError: 400 status
    - APIError: Other API errors
    """
    error_str = str(error).lower()

    if hasattr(error, 'status_code'):
        status = error.status_code

        if status == 429:
            return RateLimitError(f"Anthropic rate limit exceeded: {error}")
        elif status == 401:
            return AuthenticationError(f"Invalid Anthropic API key: {error}")
        elif status == 402:
            return QuotaExceededError(f"Anthropic quota exceeded: {error}")
        elif status == 503:
            return ServiceUnavailableError(f"Anthropic service unavailable: {error}")

    # Check error message for common patterns
    if "rate limit" in error_str:
        return RateLimitError(f"Anthropic rate limit: {error}")
    elif "authentication" in error_str or "api key" in error_str:
        return AuthenticationError(f"Anthropic auth failed: {error}")
    elif "timeout" in error_str:
        return APITimeoutError(f"Anthropic request timeout: {error}")

    # Generic API error
    return MnemeAPIError(f"Anthropic API error: {error}")


# ============================================================================
# User-Friendly Error Messages
# ============================================================================

def get_user_friendly_message(error: Exception) -> str:
    """
    Convert technical errors to user-friendly messages.

    Args:
        error: The exception

    Returns:
        str: User-friendly error message

    MESSAGES:
    - Rate Limit: "API rate limit reached. Please wait a moment."
    - Auth: "API key invalid. Please check your configuration."
    - Timeout: "Request timed out. Please try again."
    - Quota: "API quota exceeded. Please check your billing."
    - Generic: Brief technical error
    """
    if isinstance(error, RateLimitError):
        return "⏱️  API rate limit reached. Retrying with backoff..."

    elif isinstance(error, AuthenticationError):
        return "🔐 API authentication failed. Please check your API key in config.json"

    elif isinstance(error, QuotaExceededError):
        return "💳 API quota exceeded. Please check your billing at the provider's console."

    elif isinstance(error, APITimeoutError):
        error_details = f"{type(error).__name__}: {str(error)[:150]}"
        return f"⏱️  Timeout: {error_details}"

    elif isinstance(error, ServiceUnavailableError):
        return "🔧 API service temporarily unavailable. Retrying..."

    else:
        # Generic error - show full message (don't truncate - user needs details)
        error_msg = str(error)
        if len(error_msg) > 1000:
            error_msg = error_msg[:997] + "..."
        return f"⚠️  Error: {error_msg}"


# ============================================================================
# Graceful Degradation Utilities
# ============================================================================

def with_fallback(primary_func: Callable, fallback_func: Callable, fallback_on: Tuple[type, ...] = (Exception,)) -> Any:
    """
    Try primary function, fall back to secondary on error.

    Args:
        primary_func: Function to try first
        fallback_func: Function to try if primary fails
        fallback_on: Exceptions to trigger fallback (default: all)

    Returns:
        Result from primary or fallback function

    EXAMPLE:
        result = with_fallback(
            lambda: expensive_ai_tagging(msg),
            lambda: default_tags()
        )
    """
    try:
        return primary_func()
    except fallback_on as e:
        print(f"  ℹ️  Primary function failed, using fallback: {str(e)[:50]}", file=sys.stderr)
        return fallback_func()
