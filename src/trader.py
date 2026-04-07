import logging
from py_clob_client.client import ClobClient
from config import COPY_RATIO, MAX_TRADE_USD

logger = logging.getLogger(__name__)


class CopyTrader:
    """
    Takes detected trades from TraderWatcher and mirrors them
    at a scaled-down size using the authenticated CLOB client.
    """

    def __init__(self, client: ClobClient):
        self.client = client

    def scale_size(self, original_size: float) -> float:
        """
        Scale the target's trade size down to our size.
        E.g. if they buy $1000 and COPY_RATIO=0.1, we buy $100.
        Capped at MAX_TRADE_USD for risk management.
        """
        scaled = original_size * COPY_RATIO
        return min(scaled, MAX_TRADE_USD)

    def copy_trade(self, trade: dict) -> dict | None:
        """
        Mirror a single detected trade.

        A trade object from the Data API looks like:
        {
            "id": "abc123",
            "market": "token_id_here",
            "outcome": "Yes",
            "side": "BUY",
            "price": 0.65,
            "size": 500.0,
            ...
        }
        """
        try:
            token_id = trade.get("asset_id") or trade.get("market")
            side = trade.get("side", "BUY").upper()
            price = float(trade.get("price", 0))
            original_size = float(trade.get("size", 0))

            if not token_id or not price or not original_size:
                logger.warning(f"Incomplete trade data: {trade}")
                return None

            our_size = self.scale_size(original_size)

            if our_size < 1.0:  # Polymarket minimum
                logger.info(f"Trade too small after scaling: ${our_size:.2f}, skipping")
                return None

            logger.info(
                f"Copying trade: {side} {token_id} @ {price} "
                f"size={our_size:.2f} (original: {original_size:.2f})"
            )

            # Place the order via CLOB API
            # This requires L2 auth + the order is signed with your private key
            order = self.client.create_and_post_order({
                "token_id": token_id,
                "price": price,
                "size": our_size,
                "side": side,
            })

            logger.info(f"Order placed: {order}")
            return order

        except Exception as e:
            logger.error(f"Failed to copy trade: {e}")
            return None
