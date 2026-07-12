"""
Shared Anthropic client setup for Phase 4 (news scanner, copy gate, daily review).

Loading order for the API key (config.py already merges .env + .secrets.env):
  1. .env   — bot config (private key, wallet, tuning knobs)
  2. .secrets.env — third-party API keys (ANTHROPIC_API_KEY)

If ANTHROPIC_API_KEY is not set, Phase 4 is disabled at import time and the
individual modules early-return without ever calling the API.
"""
import logging
import anthropic
from config import ANTHROPIC_API_KEY, PHASE4_ENABLED

logger = logging.getLogger(__name__)

# One process-wide client. The SDK is thread-safe for the read paths we use,
# and instances hold pooled HTTP connections — creating one per call is wasteful.
_client: anthropic.Anthropic | None = None


def get_client() -> anthropic.Anthropic | None:
    """
    Returns a shared Anthropic client, or None if Phase 4 is disabled.
    Modules should check for None and gracefully skip work when it's absent.
    """
    global _client
    if not PHASE4_ENABLED:
        return None
    if _client is None:
        _client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        logger.info("Anthropic client initialised (Phase 4 enabled)")
    return _client


def is_available() -> bool:
    """True if we have an API key and Phase 4 is on."""
    return PHASE4_ENABLED
