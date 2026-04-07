import requests
import logging
from config import DATA_HOST

logger = logging.getLogger(__name__)


class TraderWatcher:
    """
    Polls the Data API to detect new trades by a target trader.
    Uses the /trades endpoint which requires no authentication.
    """

    def __init__(self, trader_address: str):
        self.trader_address = trader_address
        self.seen_trade_ids = set()

    def get_recent_trades(self, limit: int = 20) -> list:
        """
        Fetch recent trades for the target trader.
        No auth needed — this is a public endpoint.
        Rate limit: 200 req/10s — we're polling every 10s so we're safe.
        """
        url = f"{DATA_HOST}/trades"
        params = {
            "maker": self.trader_address,
            "limit": limit,
            # Can also add: "taker", "market", "before", "after"
        }

        try:
            resp = requests.get(url, params=params, timeout=10)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            logger.error(f"Failed to fetch trades for {self.trader_address}: {e}")
            return []

    def get_new_trades(self) -> list:
        """
        Returns only trades we haven't seen before.
        Call this in a loop — it acts as a change detector.
        """
        trades = self.get_recent_trades()
        new_trades = []

        for trade in trades:
            trade_id = trade.get("id")
            if trade_id and trade_id not in self.seen_trade_ids:
                self.seen_trade_ids.add(trade_id)
                new_trades.append(trade)
                logger.info(f"New trade detected: {trade_id}")

        return new_trades

    def get_positions(self) -> list:
        """
        Get current open positions for the target trader.
        Useful for initial sync when the bot starts.
        Rate limit: 150 req/10s
        """
        url = f"{DATA_HOST}/positions"
        params = {"user": self.trader_address}

        try:
            resp = requests.get(url, params=params, timeout=10)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            logger.error(f"Failed to fetch positions: {e}")
            return []
