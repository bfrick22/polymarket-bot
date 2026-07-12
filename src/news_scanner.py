"""
Phase 4A — news-driven market discovery (Claude Sonnet 4.6).

Every NEWS_SCAN_INTERVAL_MIN minutes:
  1. Pull the current short-horizon Polymarket catalog (markets resolving within
     MAX_RESOLUTION_HOURS) from Gamma.
  2. Ask Sonnet 4.6 — with the web_search server tool — which markets look
     mispriced given recent news.
  3. Claude returns structured candidates: {slug, side, size_usd, rationale, confidence}.
  4. If NEWS_SCAN_AUTO_TRADE=true, executor places BUY orders subject to
     NEWS_SCAN_MAX_TRADE_USD cap and dedup on filled_slugs. Otherwise advisory
     logging only.

Prompt caching:
  - Catalog + rules are cached with 1-hour TTL. At 15-min cadence that's 4
    reads per cache write — 2.3x cost vs 4x uncached.
  - Question is a small user message after the cache breakpoint.
"""
import json
import logging
import time
from datetime import datetime, timezone
from typing import Literal

import requests
from pydantic import BaseModel, Field

from claude_client import get_client
from config import (
    NEWS_SCAN_ENABLED,
    NEWS_SCAN_MODEL,
    NEWS_SCAN_AUTO_TRADE,
    NEWS_SCAN_MAX_TRADE_USD,
    NEWS_SCAN_MAX_TRADES_PER_CYCLE,
    MAX_RESOLUTION_HOURS,
    MIN_SHARES,
    GAMMA_HOST,
    CLOB_HOST,
)

logger = logging.getLogger(__name__)


class Candidate(BaseModel):
    slug: str = Field(description="Exact market slug from the provided catalog.")
    side: Literal["YES", "NO"] = Field(description="Which outcome to buy.")
    confidence: float = Field(ge=0.0, le=1.0, description="0-1 confidence this is mispriced.")
    size_usd: float = Field(gt=0.0, description="Suggested USD to enter.")
    rationale: str = Field(description="One-sentence 'why' tied to specific news.")


class ScannerOutput(BaseModel):
    candidates: list[Candidate] = Field(
        description="0-5 markets that look mispriced given current news. Empty is fine."
    )
    summary: str = Field(description="One-line summary of what you looked at.")


_SYSTEM_PROMPT = """You are a prediction-market analyst. Given (a) a catalog of short-horizon
Polymarket markets and (b) the ability to search the web, your job is to find markets whose
current YES price does NOT reflect recent news.

Method:
  1. Use web_search to look up news from the last few hours on topics relevant to the catalog.
     Focus on breaking news that would move a specific market's probability.
  2. For any market where you have a clear thesis (news + entry direction + reasoning),
     add it to `candidates`. Size each between $1 and the max provided.
  3. Prefer high-confidence picks. It's fine to return 0 candidates if nothing stands out.

Rules:
  - Only reference markets that exist in the provided catalog (match slug exactly).
  - Do NOT pick markets where the current YES is already extreme (< $0.05 or > $0.95) —
    the news is priced in.
  - Do NOT trade on rumors, tweets from non-primary sources, or unverified claims.
  - Confidence < 0.6 → don't include the candidate.

Respond with a JSON object matching the schema."""


def _fetch_short_horizon_catalog(max_markets: int = 40) -> list[dict]:
    """
    Pull the current active-market catalog, filter to markets resolving inside
    MAX_RESOLUTION_HOURS. Return compact records the LLM can reason over.
    """
    try:
        r = requests.get(
            f"{GAMMA_HOST}/markets",
            params={
                "active": "true",
                "closed": "false",
                "limit": 200,
                "order": "volume24hr",
                "ascending": "false",
            },
            timeout=10,
        )
        r.raise_for_status()
        markets = r.json()
    except (requests.RequestException, ValueError) as e:
        logger.error(f"news_scanner: catalog fetch failed: {e}")
        return []

    now = datetime.now(timezone.utc).timestamp()
    filtered = []
    for m in markets:
        end_s = m.get("endDate") or ""
        if not end_s:
            continue
        try:
            end_ts = datetime.fromisoformat(end_s.replace("Z", "+00:00")).timestamp()
        except ValueError:
            continue
        hours_left = (end_ts - now) / 3600.0
        if not (0 < hours_left <= MAX_RESOLUTION_HOURS):
            continue
        # Skip ultra-short crypto 5m markets — Phase 3 already covers those
        slug = (m.get("slug") or "").lower()
        if "updown-5m" in slug:
            continue
        # Parse the YES price
        op = m.get("outcomePrices", "[]")
        try:
            prices = json.loads(op) if isinstance(op, str) else op
            yes_price = float(prices[0]) if prices else None
        except (json.JSONDecodeError, TypeError, ValueError):
            yes_price = None
        if yes_price is None:
            continue
        filtered.append({
            "slug": slug,
            "question": (m.get("question") or "")[:140],
            "yes_price": round(yes_price, 3),
            "hours_left": round(hours_left, 1),
            "volume_24h": round(float(m.get("volume24hr", 0) or 0), 0),
        })
        if len(filtered) >= max_markets:
            break

    return filtered


def _resolve_market_by_slug(slug: str) -> dict | None:
    """Look up a market by slug to get its token IDs and current price."""
    try:
        r = requests.get(f"{GAMMA_HOST}/markets", params={"slug": slug}, timeout=8)
        r.raise_for_status()
        data = r.json()
        if isinstance(data, list) and data:
            return data[0]
    except (requests.RequestException, ValueError):
        pass
    return None


class NewsScanner:
    """
    Periodically ask Claude which markets are mispriced given the news.
    Places trades via the same CLOB client the copy trader uses (BUY only).
    """

    def __init__(self, clob_client):
        self.clob_client = clob_client
        self.last_scan: float = 0.0
        self.fired_slugs: set[str] = set()

    def _build_catalog_text(self, catalog: list[dict]) -> str:
        lines = ["Slug | Question | YES price | Hours to resolution | 24h volume"]
        lines.append("-" * 80)
        for m in catalog:
            lines.append(
                f"{m['slug']} | {m['question']} | ${m['yes_price']:.3f} | "
                f"{m['hours_left']:.1f}h | ${m['volume_24h']:,.0f}"
            )
        return "\n".join(lines)

    def scan(self) -> ScannerOutput | None:
        """Run one Claude scan. Returns parsed output or None on failure."""
        client = get_client()
        if client is None:
            return None

        catalog = _fetch_short_horizon_catalog()
        if not catalog:
            logger.info("news_scanner: no short-horizon markets in catalog")
            return None

        catalog_text = self._build_catalog_text(catalog)
        logger.info(f"news_scanner: asking Sonnet 4.6 to review {len(catalog)} markets")

        try:
            response = client.messages.create(
                model=NEWS_SCAN_MODEL,
                max_tokens=4000,
                thinking={"type": "adaptive"},
                system=[
                    {
                        "type": "text",
                        "text": _SYSTEM_PROMPT,
                        "cache_control": {"type": "ephemeral"},
                    },
                    {
                        "type": "text",
                        "text": (
                            f"Current Polymarket catalog (short-horizon, max "
                            f"{MAX_RESOLUTION_HOURS}h to resolution):\n\n{catalog_text}"
                        ),
                        # 1-hour TTL: catalog is stable enough over ~4 scans
                        # to amortize the 2x write cost vs 4x uncached.
                        "cache_control": {"type": "ephemeral", "ttl": "1h"},
                    },
                ],
                tools=[
                    {"type": "web_search_20260209", "name": "web_search"},
                ],
                messages=[
                    {
                        "role": "user",
                        "content": (
                            f"Search for news from the last 2-3 hours that could move any "
                            f"of these markets. Then return up to "
                            f"{NEWS_SCAN_MAX_TRADES_PER_CYCLE} high-confidence candidates. "
                            f"Cap each size at ${NEWS_SCAN_MAX_TRADE_USD}. Use the schema."
                        ),
                    }
                ],
                output_config={
                    "format": {
                        "type": "json_schema",
                        "schema": ScannerOutput.model_json_schema(),
                    }
                },
            )
        except Exception as e:
            logger.error(f"news_scanner: Claude call failed: {type(e).__name__}: {e}")
            return None

        # Log cache stats — helps verify the caching setup
        u = response.usage
        logger.info(
            f"news_scanner: usage input={u.input_tokens} "
            f"cache_read={u.cache_read_input_tokens} "
            f"cache_write={u.cache_creation_input_tokens} "
            f"output={u.output_tokens}"
        )

        try:
            text = next(b.text for b in response.content if getattr(b, "type", "") == "text")
            parsed = ScannerOutput(**json.loads(text))
        except (StopIteration, json.JSONDecodeError, ValueError) as e:
            logger.error(f"news_scanner: couldn't parse response ({e})")
            return None

        return parsed

    def execute_candidates(self, output: ScannerOutput) -> int:
        """
        If auto-trade is enabled, place BUYs on the candidates. Returns count fired.
        Otherwise logs candidates as advisory only.
        """
        if not output.candidates:
            logger.info(f"news_scanner: no candidates. Summary: {output.summary}")
            return 0

        logger.info(f"news_scanner: {len(output.candidates)} candidate(s). Summary: {output.summary}")
        for c in output.candidates:
            logger.info(
                f"  candidate: {c.slug}  side={c.side}  "
                f"conf={c.confidence:.2f}  size=${c.size_usd:.2f}  reason={c.rationale}"
            )

        if not NEWS_SCAN_AUTO_TRADE:
            logger.info("news_scanner: NEWS_SCAN_AUTO_TRADE=false — advisory only")
            return 0

        # Import locally to avoid a circular dep and to allow this module to
        # be imported by the daily review without a CLOB dependency.
        from py_clob_client_v2.clob_types import OrderArgs

        fires = 0
        for c in output.candidates:
            if c.slug in self.fired_slugs:
                continue
            if fires >= NEWS_SCAN_MAX_TRADES_PER_CYCLE:
                break

            market = _resolve_market_by_slug(c.slug)
            if not market:
                logger.warning(f"news_scanner: couldn't resolve slug {c.slug}, skip")
                continue

            ids_raw = market.get("clobTokenIds", "[]")
            try:
                tokens = json.loads(ids_raw) if isinstance(ids_raw, str) else ids_raw
            except (json.JSONDecodeError, TypeError):
                continue
            if not tokens or len(tokens) < 2:
                continue
            token_id = tokens[0] if c.side == "YES" else tokens[1]

            # Get the current best ask so we know what we're paying
            try:
                r = requests.get(f"{CLOB_HOST}/book", params={"token_id": token_id}, timeout=5)
                r.raise_for_status()
                book = r.json()
                asks = book.get("asks") or []
                price = float(asks[0]["price"]) if asks else None
            except (requests.RequestException, ValueError, KeyError):
                price = None
            if not price or price <= 0:
                logger.warning(f"news_scanner: no ask for {c.slug}, skip")
                continue

            # Size respecting the cap and the 5-share minimum
            size_usd = min(c.size_usd, NEWS_SCAN_MAX_TRADE_USD)
            shares = max(size_usd / price, MIN_SHARES)
            cost = shares * price
            try:
                order = self.clob_client.create_and_post_order(
                    OrderArgs(token_id=token_id, price=price, size=shares, side="BUY")
                )
                logger.info(
                    f"news_scanner FIRE: {c.side} {c.slug} {shares:.1f}sh @ "
                    f"${price:.3f} = ${cost:.2f} | order={order}"
                )
                self.fired_slugs.add(c.slug)
                fires += 1
            except Exception as e:
                logger.error(f"news_scanner FIRE FAILED [{c.slug}]: {e}")

        return fires

    def scan_and_execute(self) -> int:
        """One tick. Returns number of orders fired (0 if advisory or no candidates)."""
        output = self.scan()
        if output is None:
            return 0
        return self.execute_candidates(output)
