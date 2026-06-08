import logging
import requests
from py_clob_client_v2.client import ClobClient
from py_clob_client_v2.clob_types import OrderArgs
from config import (
    COPY_RATIO,
    COPY_RATIO_SMALL,
    MAX_TRADE_USD,
    MARKET_KEYWORDS,
    MIN_SHARES,
    MIN_POSITION_USD,
    MAX_EXPOSURE_PER_MARKET_USD,
    MIRROR_SELLS,
    DATA_HOST,
    POLY_ADDRESS,
)

logger = logging.getLogger(__name__)


class CopyTrader:
    """
    Takes detected trades from TraderWatcher and mirrors them
    at a scaled-down size using the authenticated CLOB client.
    """

    def __init__(self, client: ClobClient):
        self.client = client

    def scale_size(self, shares: float, price: float) -> float:
        """
        Convert target's share count to a USD value, apply ratio,
        then convert back to shares at the same price.

        Small trades (target USD <= MAX_TRADE_USD) use COPY_RATIO_SMALL (35%)
        for a more meaningful position. Large trades use COPY_RATIO, capped at MAX_TRADE_USD.
        """
        usd_value = shares * price
        ratio = COPY_RATIO_SMALL if usd_value <= MAX_TRADE_USD else COPY_RATIO
        our_usd = min(usd_value * ratio, MAX_TRADE_USD)
        our_shares = our_usd / price if price > 0 else 0
        return our_shares

    def _get_our_position(self, token_id: str) -> dict | None:
        """
        Query our current position on a single token. Returns None if no position held.
        Used by SELL mirroring (can't sell what we don't have) and exposure capping.
        """
        try:
            resp = requests.get(
                f"{DATA_HOST}/positions",
                params={"user": POLY_ADDRESS, "asset": token_id},
                timeout=10,
            )
            resp.raise_for_status()
            positions = resp.json()
            if not positions:
                return None
            return positions[0]
        except requests.RequestException as e:
            logger.warning(f"Could not fetch our position for {token_id[:16]}...: {e}")
            return None

    def copy_trade(self, trade: dict, trader_name: str = "") -> dict | None:
        """
        Mirror a single detected trade. Handles BUY and SELL.

        Trade object from Data API:
        {
            "asset": "token_id...",
            "side": "BUY" | "SELL",
            "price": 0.65,
            "size": 1000.0,   # target's shares, not USD
            "title": "...",
            ...
        }
        """
        try:
            token_id = trade.get("asset")
            side = trade.get("side", "BUY").upper()
            price = float(trade.get("price", 0))
            shares = float(trade.get("size", 0))

            if not token_id or not price or not shares:
                logger.warning(f"Incomplete trade data: {trade}")
                return None

            if MARKET_KEYWORDS:
                title = (trade.get("title", "") or "").lower()
                if not any(kw in title for kw in MARKET_KEYWORDS):
                    logger.info(f"Skipping non-matching market: {trade.get('title', 'unknown')}")
                    return None

            label = f"[{trader_name}] " if trader_name else ""

            if side == "SELL":
                return self._mirror_sell(token_id, price, shares, trade, label)
            return self._mirror_buy(token_id, price, shares, trade, label)

        except Exception as e:
            logger.error(f"Failed to copy trade: {e}", exc_info=True)
            return None

    def _mirror_buy(self, token_id: str, price: float, target_shares: float,
                    trade: dict, label: str) -> dict | None:
        """Mirror a BUY with sizing rules + per-market exposure cap."""
        our_shares = self.scale_size(target_shares, price)
        our_usd = our_shares * price

        if our_shares < MIN_SHARES:
            logger.info(
                f"{label}BUY too small: {our_shares:.2f} shares < {MIN_SHARES} min "
                f"({trade.get('title', '')[:50]}) — skipping"
            )
            return None
        if our_usd < MIN_POSITION_USD:
            logger.info(
                f"{label}BUY USD too small: ${our_usd:.3f} < ${MIN_POSITION_USD} — skipping"
            )
            return None

        # Per-market exposure cap — refuse to add if we already hold the cap.
        existing = self._get_our_position(token_id)
        existing_usd = float(existing.get("currentValue", 0)) if existing else 0.0
        if existing_usd >= MAX_EXPOSURE_PER_MARKET_USD:
            logger.info(
                f"{label}BUY blocked by per-market cap: already ${existing_usd:.2f} "
                f">= ${MAX_EXPOSURE_PER_MARKET_USD} on {trade.get('title', '')[:50]}"
            )
            return None
        room_usd = MAX_EXPOSURE_PER_MARKET_USD - existing_usd
        if our_usd > room_usd:
            our_usd = room_usd
            our_shares = our_usd / price
            if our_shares < MIN_SHARES:
                logger.info(
                    f"{label}BUY capped below min after exposure trim — skipping"
                )
                return None

        logger.info(
            f"{label}BUY {token_id[:16]}... @ {price} "
            f"shares={our_shares:.2f} (${our_usd:.2f}) "
            f"[target: {target_shares:.2f} shares (${target_shares * price:.2f})] "
            f"{trade.get('title', '')[:60]}"
        )

        order_args = OrderArgs(
            token_id=token_id,
            price=price,
            size=our_shares,
            side="BUY",
        )
        order = self.client.create_and_post_order(order_args)
        logger.info(f"Order placed: {order}")
        return order

    def _mirror_sell(self, token_id: str, price: float, target_shares: float,
                     trade: dict, label: str) -> dict | None:
        """
        Mirror a SELL proportionally. If target sells X% of their holdings,
        we sell X% of our holdings on the same token.
        """
        if not MIRROR_SELLS:
            logger.info(f"{label}SELL ignored (MIRROR_SELLS=false)")
            return None

        # Need our current position to compute proportional close.
        our_pos = self._get_our_position(token_id)
        if not our_pos:
            logger.info(
                f"{label}SELL skipped: no position held on {token_id[:16]}..."
            )
            return None

        our_shares_held = float(our_pos.get("size", 0))
        if our_shares_held < MIN_SHARES:
            logger.info(
                f"{label}SELL skipped: holding {our_shares_held:.2f} < {MIN_SHARES} min"
            )
            return None

        # Estimate the fraction of target's position they're selling.
        # If we can't determine it, default to selling the same scaled proportion.
        target_initial = float(our_pos.get("initialQuantity", 0))  # may not exist
        fraction = 1.0
        if target_initial > 0 and target_shares <= target_initial:
            fraction = target_shares / target_initial

        our_sell_shares = min(our_shares_held * fraction, our_shares_held)
        if our_sell_shares < MIN_SHARES:
            # Round up to MIN_SHARES if we can; otherwise dump the whole thing if close.
            if our_shares_held >= MIN_SHARES:
                our_sell_shares = min(our_shares_held, MIN_SHARES)
            else:
                logger.info(f"{label}SELL too small: {our_sell_shares:.2f} shares — skipping")
                return None

        logger.info(
            f"{label}SELL {token_id[:16]}... @ {price} "
            f"shares={our_sell_shares:.2f} of {our_shares_held:.2f} held "
            f"[target sold: {target_shares:.2f}] "
            f"{trade.get('title', '')[:60]}"
        )

        order_args = OrderArgs(
            token_id=token_id,
            price=price,
            size=our_sell_shares,
            side="SELL",
        )
        order = self.client.create_and_post_order(order_args)
        logger.info(f"Order placed: {order}")
        return order
