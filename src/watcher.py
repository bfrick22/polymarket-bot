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

    def get_recent_trades(self, limit: int = None) -> list:
        import os
        if limit is None:
            limit = int(os.getenv("RECENT_TRADES_LIMIT", 40))
        """
        Fetch recent trades for the target trader.
        No auth needed — this is a public endpoint.
        Rate limit: 200 req/10s — we're polling every 10s so we're safe.
        """
        url = f"{DATA_HOST}/trades"
        params = {
            "user": self.trader_address,
            "limit": limit,
        }

        try:
            resp = requests.get(url, params=params, timeout=10)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            logger.error(f"Failed to fetch trades for {self.trader_address}: {e}")
            return []

    def seed_seen_trades(self) -> None:
        """
        Pre-populate seen_trade_ids with current recent trades so the bot
        doesn't copy historical trades on startup — only new ones going forward.
        """
        trades = self.get_recent_trades()
        for trade in trades:
            trade_id = trade.get("transactionHash")
            if trade_id:
                self.seen_trade_ids.add(trade_id)
        logger.info(f"Seeded {len(self.seen_trade_ids)} existing trades — watching for new ones")

    def get_new_trades(self) -> list:
        """
        Returns only trades we haven't seen before.
        Call this in a loop — it acts as a change detector.
        """
        trades = self.get_recent_trades()
        new_trades = []

        for trade in trades:
            trade_id = trade.get("transactionHash")
            if trade_id and trade_id not in self.seen_trade_ids:
                self.seen_trade_ids.add(trade_id)
                new_trades.append(trade)
                logger.info(f"New trade detected: {trade_id[:16]}...")

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
