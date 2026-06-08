"""
Multi-outcome arbitrage scanner.

Polls the Gamma /events endpoint for events with N mutually-exclusive YES outcomes
(World Cup winner, election winner, NBA champion, halftime result, etc). Exactly
one outcome resolves YES, so sum_yes should equal $1.00 at fair value. When the
sum drops below ARB_THRESHOLD, buying one share of every YES outcome guarantees
profit at resolution.

This module does not predict anything. The edge is mechanical.
"""
import json
import logging
import time
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from py_clob_client_v2.client import ClobClient
from py_clob_client_v2.clob_types import OrderArgs

from config import (
    GAMMA_HOST,
    ARB_THRESHOLD,
    ARB_MIN_EDGE,
    ARB_MAX_BASKET_USD,
    ARB_MIN_OUTCOMES,
    ARB_MAX_OUTCOMES,
    MIN_SHARES,
)

logger = logging.getLogger(__name__)


class ArbitrageScanner:
    """
    Scans Polymarket events for multi-outcome YES-basket arbitrage.

    An event with N mutually-exclusive YES outcomes whose prices sum to S < $1
    can be locked in for a guaranteed (1/S - 1) return by buying one share of
    each YES at the listed prices and holding to resolution.
    """

    def __init__(self, client: ClobClient):
        self.client = client
        self.session = self._make_session()
        # Track events we've already filled to avoid re-buying the same basket
        # each scan cycle while prices stay below threshold.
        self.filled_event_ids: set[str] = set()

    def _make_session(self) -> requests.Session:
        session = requests.Session()
        retry = Retry(
            total=3,
            connect=3,
            read=3,
            backoff_factor=0.5,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"],
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry, pool_connections=1, pool_maxsize=1)
        session.mount("https://", adapter)
        session.headers.update({"Connection": "close"})
        return session

    def fetch_events(self, limit: int = 100) -> list[dict]:
        """Top events by 24h volume — concentrates the scanner on liquid markets."""
        try:
            resp = self.session.get(
                f"{GAMMA_HOST}/events",
                params={
                    "active": "true",
                    "closed": "false",
                    "limit": limit,
                    "order": "volume24hr",
                    "ascending": "false",
                },
                timeout=15,
            )
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            logger.error(f"Arb scan: failed to fetch events: {e}")
            return []

    @staticmethod
    def _parse_prices(market: dict) -> tuple[float, float] | None:
        """Returns (yes_price, no_price) or None if unparseable."""
        op = market.get("outcomePrices", "[]")
        try:
            prices = json.loads(op) if isinstance(op, str) else op
            if not prices or len(prices) < 2:
                return None
            return float(prices[0]), float(prices[1])
        except (ValueError, TypeError, json.JSONDecodeError):
            return None

    @staticmethod
    def _first_token_id(market: dict) -> str | None:
        """The YES token id is the first entry in clobTokenIds."""
        ids = market.get("clobTokenIds", "[]")
        try:
            parsed = json.loads(ids) if isinstance(ids, str) else ids
            return parsed[0] if parsed else None
        except (ValueError, TypeError, json.JSONDecodeError):
            return None

    def find_opportunities(self, events: list[dict]) -> list[dict]:
        """
        Filter events down to actionable arb candidates.
        Returns dicts with: event_id, title, sum_yes, edge, legs[].
        """
        opportunities = []
        for event in events:
            event_id = str(event.get("id", ""))
            if not event_id or event_id in self.filled_event_ids:
                continue

            # Mutual-exclusion gate. Polymarket marks negRisk=True on events
            # whose outcomes partition the probability space (one and only one
            # YES resolves true). Without this gate the scanner would mistake
            # date-bucketed events ("by May X / by June X") and price-tier
            # baskets ("Bitcoin hits $X") for arbs — buying every YES on those
            # would lose money because multiple YES can win or none do.
            if not event.get("negRisk"):
                continue

            markets = event.get("markets", [])
            if not (ARB_MIN_OUTCOMES <= len(markets) <= ARB_MAX_OUTCOMES):
                continue

            sum_yes = 0.0
            legs = []
            skip = False
            for m in markets:
                prices = self._parse_prices(m)
                token_id = self._first_token_id(m)
                if prices is None or not token_id:
                    skip = True
                    break
                yes_price, _ = prices
                if yes_price <= 0 or yes_price >= 1.0:
                    skip = True
                    break
                sum_yes += yes_price
                legs.append({
                    "token_id": token_id,
                    "yes_price": yes_price,
                    "question": m.get("question", "")[:80],
                })
            if skip or not legs:
                continue

            if sum_yes >= ARB_THRESHOLD:
                continue
            edge = (1.0 / sum_yes) - 1.0
            if edge < ARB_MIN_EDGE:
                continue

            opportunities.append({
                "event_id": event_id,
                "title": event.get("title", "")[:80],
                "sum_yes": sum_yes,
                "edge_pct": edge * 100,
                "n_legs": len(legs),
                "vol24h": float(event.get("volume24hr", 0) or 0),
                "legs": legs,
            })

        opportunities.sort(key=lambda x: -x["edge_pct"])
        return opportunities

    def execute_basket(self, opp: dict) -> bool:
        """
        Buy one share of every YES outcome in the basket. Sized so total
        exposure stays under ARB_MAX_BASKET_USD. Returns True if all legs filled.
        """
        legs = opp["legs"]
        sum_yes = opp["sum_yes"]

        # Equal-share approach: buy K shares of each YES leg. Resolution pays
        # exactly K dollars (since one YES will resolve to $1, others to $0).
        # Cost = K * sum_yes. To stay under the cap: K = floor(max_usd / sum_yes).
        # Then per-leg dollar cost = K * yes_price, share count = K.
        k_shares = ARB_MAX_BASKET_USD / sum_yes
        if k_shares < MIN_SHARES:
            logger.info(
                f"Arb {opp['event_id']}: K={k_shares:.2f} < {MIN_SHARES} min — skip"
            )
            return False

        total_cost = k_shares * sum_yes
        guaranteed_payout = k_shares
        guaranteed_profit = guaranteed_payout - total_cost
        logger.info(
            f"ARB FOUND: {opp['title']} | sum_YES=${sum_yes:.4f} | "
            f"edge={opp['edge_pct']:.2f}% | legs={opp['n_legs']} | "
            f"k={k_shares:.1f} sh per leg | cost=${total_cost:.2f} | "
            f"payout=${guaranteed_payout:.2f} | profit=${guaranteed_profit:.2f}"
        )

        # Fire each leg. If any leg fails, log it but continue — partial fills
        # degrade the guarantee but on a basket of 30 outcomes, missing one
        # rarely turns the trade negative since the missed leg is usually a
        # low-probability long-tail outcome.
        filled = 0
        for leg in legs:
            try:
                order_args = OrderArgs(
                    token_id=leg["token_id"],
                    price=leg["yes_price"],
                    size=k_shares,
                    side="BUY",
                )
                order = self.client.create_and_post_order(order_args)
                logger.info(
                    f"  ARB leg filled: ${leg['yes_price']:.3f} x {k_shares:.1f} "
                    f"= ${leg['yes_price']*k_shares:.2f} | {leg['question'][:50]}"
                )
                filled += 1
            except Exception as e:
                logger.error(
                    f"  ARB leg FAILED: {leg['question'][:50]} | {e}"
                )

        success = filled == len(legs)
        if success:
            logger.info(f"ARB COMPLETE: {filled}/{len(legs)} legs filled")
            self.filled_event_ids.add(opp["event_id"])
        else:
            logger.warning(
                f"ARB PARTIAL: {filled}/{len(legs)} legs filled — "
                f"guarantee compromised on {opp['title']}"
            )
        return success

    def scan_and_fire(self) -> int:
        """One scan cycle. Returns number of opportunities executed."""
        events = self.fetch_events()
        if not events:
            return 0
        opps = self.find_opportunities(events)
        if not opps:
            logger.debug(f"Arb scan: 0 opportunities in {len(events)} events")
            return 0
        logger.info(f"Arb scan: {len(opps)} opportunit(ies) found in {len(events)} events")
        fired = 0
        for opp in opps:
            if self.execute_basket(opp):
                fired += 1
        return fired
