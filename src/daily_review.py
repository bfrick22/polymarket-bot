"""
Phase 4C — nightly post-trade review (Claude Sonnet 4.6).

Once per day at DAILY_REVIEW_HOUR_UTC, gather the last 24 hours of activity
and ask Claude to write a short performance report:
  - what strategies made or lost money
  - notable outliers
  - concrete config-tweak suggestions

The report is emitted to logs. It does NOT touch orders.
"""
import logging
import time
from datetime import datetime, timezone

import requests

from claude_client import get_client
from config import (
    DAILY_REVIEW_ENABLED,
    DAILY_REVIEW_MODEL,
    DAILY_REVIEW_HOUR_UTC,
    DATA_HOST,
    POLY_ADDRESS,
)

logger = logging.getLogger(__name__)


_SYSTEM_PROMPT = """You are a trading operations analyst. You are given 24 hours of activity
from a Polymarket bot that runs several strategies concurrently:

  Phase 1: mirror-copy trades from specific target traders (mostly weather markets)
  Phase 2: multi-outcome arbitrage baskets (short-fuse events)
  Phase 3: ultra-short 5-minute BTC/XRP up/down markets (Binance latency + spread arb)
  Phase 4A: news-driven market discovery (advisory or auto-trade)

Write a short daily report (max ~400 words) that includes:
  1. A one-line P&L summary and cash-vs-locked breakdown
  2. Per-strategy assessment: what worked, what didn't. Reference specific markets.
  3. Two or three concrete, actionable config suggestions (name the env var if you can).
  4. Any anomalies worth flagging (unexpected fills, out-of-pattern trades, big losses).

Be direct and terse. Use bullet points. Don't hedge — pick a lane on each recommendation.
Assume the reader knows the strategy design and doesn't need it re-explained."""


def _should_run_now(last_run_date: str | None) -> bool:
    """
    True if the current UTC hour matches DAILY_REVIEW_HOUR_UTC and we haven't
    already run today. This is polled from the main loop so we naturally fire
    once per day inside a small window.
    """
    now = datetime.now(timezone.utc)
    if now.hour != DAILY_REVIEW_HOUR_UTC:
        return False
    today = now.strftime("%Y-%m-%d")
    return last_run_date != today


def _gather_activity_snapshot() -> dict:
    """
    Pull the last 24h of trades + current position snapshot into a JSON blob
    the LLM can chew on. Timestamps in trades let Claude do temporal reasoning.
    """
    snapshot: dict = {"trades_24h": [], "positions": [], "totals": {}}
    now = time.time()
    cutoff = now - 24 * 3600

    # Trades
    try:
        r = requests.get(
            f"{DATA_HOST}/trades",
            params={"user": POLY_ADDRESS, "limit": 500},
            timeout=15,
        )
        r.raise_for_status()
        trades = r.json()
    except (requests.RequestException, ValueError) as e:
        logger.warning(f"daily_review: trades fetch failed: {e}")
        trades = []

    recent = [t for t in trades if int(t.get("timestamp", 0) or 0) >= cutoff]
    for t in recent[:200]:  # cap to keep prompt bounded
        snapshot["trades_24h"].append({
            "ts": datetime.fromtimestamp(int(t.get("timestamp", 0)), tz=timezone.utc).isoformat(),
            "side": (t.get("side") or "").upper(),
            "shares": float(t.get("size", 0) or 0),
            "price": float(t.get("price", 0) or 0),
            "title": (t.get("title") or "")[:100],
        })

    # Positions
    try:
        r = requests.get(
            f"{DATA_HOST}/positions",
            params={"user": POLY_ADDRESS, "limit": 500},
            timeout=15,
        )
        r.raise_for_status()
        positions = r.json()
    except (requests.RequestException, ValueError) as e:
        logger.warning(f"daily_review: positions fetch failed: {e}")
        positions = []

    for p in positions:
        cv = float(p.get("currentValue", 0) or 0)
        if cv < 0.10:
            continue  # skip pennies + resolved-to-zero positions
        snapshot["positions"].append({
            "shares": float(p.get("size", 0) or 0),
            "avg_price": float(p.get("avgPrice", 0) or 0),
            "current_value": cv,
            "cash_pnl": float(p.get("cashPnl", 0) or 0),
            "realized_pnl": float(p.get("realizedPnl", 0) or 0),
            "title": (p.get("title") or "")[:100],
        })

    # Rollups
    total_invested = sum(float(p.get("initialValue", 0) or 0) for p in positions)
    total_current = sum(float(p.get("currentValue", 0) or 0) for p in positions)
    total_realized = sum(float(p.get("realizedPnl", 0) or 0) for p in positions)
    total_unrealized = sum(float(p.get("cashPnl", 0) or 0) for p in positions)
    snapshot["totals"] = {
        "position_count": len(positions),
        "worth_over_10c": len(snapshot["positions"]),
        "total_invested": round(total_invested, 2),
        "total_current_value": round(total_current, 2),
        "total_realized_pnl": round(total_realized, 2),
        "total_unrealized_pnl": round(total_unrealized, 2),
        "trades_last_24h": len(snapshot["trades_24h"]),
    }
    return snapshot


class DailyReview:
    def __init__(self):
        self.last_run_date: str | None = None

    def maybe_run(self) -> str | None:
        """
        Called from the main loop. Runs the review at most once per calendar
        day (UTC) at hour DAILY_REVIEW_HOUR_UTC. Returns the report text if
        it ran, else None.
        """
        if not DAILY_REVIEW_ENABLED:
            return None
        if not _should_run_now(self.last_run_date):
            return None

        client = get_client()
        if client is None:
            return None

        logger.info("daily_review: kicking off nightly report")
        snapshot = _gather_activity_snapshot()

        try:
            response = client.messages.create(
                model=DAILY_REVIEW_MODEL,
                max_tokens=2000,
                thinking={"type": "adaptive"},
                system=_SYSTEM_PROMPT,
                messages=[
                    {
                        "role": "user",
                        "content": (
                            "Here's the last 24 hours of activity. "
                            "Write the daily report per your instructions.\n\n"
                            f"{snapshot}"
                        ),
                    }
                ],
            )
        except Exception as e:
            logger.error(f"daily_review: Claude call failed: {type(e).__name__}: {e}")
            return None

        try:
            report = next(b.text for b in response.content if getattr(b, "type", "") == "text")
        except StopIteration:
            logger.error("daily_review: response had no text block")
            return None

        # Mark done for the day and dump the report to logs
        self.last_run_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        logger.info("=" * 60)
        logger.info("DAILY REVIEW")
        logger.info("=" * 60)
        for line in report.splitlines():
            logger.info(line)
        logger.info("=" * 60)
        return report
