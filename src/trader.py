import logging
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs
from config import COPY_RATIO, COPY_RATIO_SMALL, MAX_TRADE_USD, MARKET_KEYWORDS

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

    def copy_trade(self, trade: dict) -> dict | None:
        """
        Mirror a single detected trade.

        Trade object from Data API:
        {
            "asset": "token_id...",
            "side": "BUY",
            "price": 0.65,
            "size": 1000.0,   # shares, not USD
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

            # Market keyword filter
            if MARKET_KEYWORDS:
                title = trade.get("title", "").lower()
                if not any(kw in title for kw in MARKET_KEYWORDS):
                    logger.info(f"Skipping non-weather market: {trade.get('title', 'unknown')}")
                    return None

            our_shares = self.scale_size(shares, price)
            our_usd = our_shares * price

            if our_usd < 1.0:  # Polymarket minimum ~$1 USD
                logger.info(f"Trade too small after scaling: {our_shares:.2f} shares (${our_usd:.2f}), skipping")
                return None

            logger.info(
                f"Copying trade: {side} {token_id[:16]}... @ {price} "
                f"shares={our_shares:.2f} (${our_usd:.2f}) "
                f"[target: {shares:.2f} shares (${shares * price:.2f})]"
            )

            order_args = OrderArgs(
                token_id=token_id,
                price=price,
                size=our_shares,
                side=side,
            )

            order = self.client.create_and_post_order(order_args)
            logger.info(f"Order placed: {order}")
            return order

        except Exception as e:
            logger.error(f"Failed to copy trade: {e}")
            return None
