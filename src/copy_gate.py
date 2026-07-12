"""
Phase 4B — copy-trade sanity gate (Claude Haiku 4.5).

Before mirroring a coldmath/Hans323 trade, ask Claude:
    "Given this trader's recent pattern, does this new trade look normal?
     Or does it smell out-of-pattern (fat-finger, hacked account, one-off
     political bet that doesn't match their strategy)?"

Design constraints:
  - Latency budget ~2s per copy trade. Haiku 4.5 fits.
  - Fail-open by default: if Claude times out or errors, the trade fires
    (matches pre-Phase-4 behavior). Set COPY_GATE_FAIL_MODE=skip to fail-closed.
  - Prompt caching: the rules + trader's 10 recent trades are cached with a
    5-min TTL. Only the new trade under review changes per call → cache hit
    on every subsequent call within the window.
"""
import json
import logging
import time
from typing import Literal

import requests
from pydantic import BaseModel, Field

from claude_client import get_client
from config import (
    COPY_GATE_ENABLED,
    COPY_GATE_MODEL,
    COPY_GATE_TIMEOUT_SEC,
    COPY_GATE_FAIL_MODE,
    DATA_HOST,
)

logger = logging.getLogger(__name__)


class GateDecision(BaseModel):
    decision: Literal["allow", "skip"] = Field(
        description="Allow the copy trade or skip it."
    )
    reason: str = Field(description="Short (< 30 words) rationale for the decision.")


_SYSTEM_RULES = """You are a copy-trading sanity gate. A bot mirrors trades from a specific target trader.
Your job: given the target's recent trading pattern and one new trade, decide whether the new trade
looks like a normal continuation of their pattern (allow) or looks anomalous (skip).

SKIP if the new trade:
  - Is in a market category the trader has never touched (e.g. political when they're a weather trader)
  - Has an entry price that's an outlier (e.g. paying $0.99 when they usually enter at 1-15c)
  - Looks like a fat-finger (size 100x larger than usual)
  - Is on a market that resolves months out when the trader specializes in same-day markets

ALLOW if the trade fits the pattern. Default to ALLOW unless something is clearly off — the
trader has an edge, we don't want to over-filter.

Respond with a JSON object matching the schema."""


# Simple per-trader cache: trader_address -> (history_string, expires_at_ts)
_HISTORY_CACHE: dict[str, tuple[str, float]] = {}
_HISTORY_TTL_SEC = 600  # 10 min


def _get_trader_history(trader_address: str) -> str:
    """
    Fetch the target trader's recent 10 trades, formatted for the LLM.
    Cached for 10 min per trader — their pattern changes slowly.
    """
    now = time.time()
    cached = _HISTORY_CACHE.get(trader_address)
    if cached and cached[1] > now:
        return cached[0]

    try:
        resp = requests.get(
            f"{DATA_HOST}/trades",
            params={"user": trader_address, "limit": 10},
            timeout=5,
        )
        resp.raise_for_status()
        trades = resp.json()
    except (requests.RequestException, ValueError) as e:
        logger.warning(f"copy_gate: couldn't fetch history for {trader_address[:10]}: {e}")
        return "(no history available)"

    if not trades:
        return "(no recent trades)"

    lines = []
    for t in trades:
        try:
            side = (t.get("side") or "").upper()
            size = float(t.get("size", 0) or 0)
            price = float(t.get("price", 0) or 0)
            title = (t.get("title") or "")[:80]
            lines.append(f"  {side} {size:.1f}sh @ ${price:.3f}  {title}")
        except (TypeError, ValueError):
            continue

    formatted = "\n".join(lines) if lines else "(no trades)"
    _HISTORY_CACHE[trader_address] = (formatted, now + _HISTORY_TTL_SEC)
    return formatted


def evaluate_trade(trade: dict, trader_name: str, trader_address: str) -> tuple[str, str]:
    """
    Returns (decision, reason). decision is "allow" or "skip".
    Never raises — on any error returns COPY_GATE_FAIL_MODE + explanation.
    """
    if not COPY_GATE_ENABLED:
        return "allow", "gate disabled"

    client = get_client()
    if client is None:
        return "allow", "no Claude client (Phase 4 off)"

    history = _get_trader_history(trader_address)

    trade_summary = {
        "side": (trade.get("side") or "").upper(),
        "shares": float(trade.get("size", 0) or 0),
        "price": float(trade.get("price", 0) or 0),
        "title": trade.get("title", ""),
    }

    try:
        # Cache the rules + trader history together — those are stable across
        # calls. The new trade is volatile, so it goes after the cache
        # breakpoint in a plain user message.
        response = client.with_options(timeout=COPY_GATE_TIMEOUT_SEC).messages.create(
            model=COPY_GATE_MODEL,
            max_tokens=200,
            system=[
                {
                    "type": "text",
                    "text": (
                        f"{_SYSTEM_RULES}\n\n"
                        f"Target trader: {trader_name}\n"
                        f"Recent 10 trades:\n{history}"
                    ),
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[
                {
                    "role": "user",
                    "content": (
                        "New trade to evaluate:\n"
                        f"{json.dumps(trade_summary, indent=2)}\n\n"
                        "Return JSON with decision and reason."
                    ),
                }
            ],
            output_config={
                "format": {
                    "type": "json_schema",
                    "schema": GateDecision.model_json_schema(),
                }
            },
        )
    except Exception as e:
        logger.warning(f"copy_gate: Claude call failed ({type(e).__name__}: {e}) — fail-mode={COPY_GATE_FAIL_MODE}")
        return COPY_GATE_FAIL_MODE, f"api_error: {type(e).__name__}"

    # output_config.format guarantees the first text block is valid JSON.
    try:
        text = next(b.text for b in response.content if getattr(b, "type", "") == "text")
        parsed = GateDecision(**json.loads(text))
    except (StopIteration, json.JSONDecodeError, ValueError) as e:
        logger.warning(f"copy_gate: couldn't parse response ({e}) — fail-mode={COPY_GATE_FAIL_MODE}")
        return COPY_GATE_FAIL_MODE, f"parse_error: {type(e).__name__}"

    # Verify cache is working — only log occasionally to avoid noise
    if response.usage.cache_read_input_tokens == 0 and response.usage.cache_creation_input_tokens > 0:
        logger.debug(
            f"copy_gate: cache write ({response.usage.cache_creation_input_tokens} tokens); "
            "future calls this window will read"
        )

    return parsed.decision, parsed.reason
