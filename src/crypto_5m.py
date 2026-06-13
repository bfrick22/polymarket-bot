"""
Phase 3 — ultra-short crypto market scanner.

Two independent fire signals on Polymarket's 5m up/down crypto markets:

  Signal A (Binance latency):
      Spot on Binance moves > CRYPTO_5M_IMPULSE_BPS in CRYPTO_5M_IMPULSE_WINDOW_SEC
      AND the Polymarket Up market mid is still near 0.50 (hasn't repriced).
      → Buy whichever direction Binance moved.

  Signal B (spread floor / mini-arbitrage):
      YES_Up_ask + YES_Down_ask < CRYPTO_5M_SPREAD_THRESHOLD.
      The two outcomes are mutually exclusive, so the sum should be ~1.00.
      → Buy YES on both sides for locked-in profit.

Binance public WebSocket needs no account or API key. We only read the price.
"""
import json
import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import re
import requests
from websocket import WebSocketApp

from py_clob_client_v2.client import ClobClient
from py_clob_client_v2.clob_types import OrderArgs

from config import (
    GAMMA_HOST,
    CLOB_HOST,
    CRYPTO_5M_ASSETS,
    CRYPTO_5M_MAX_TRADE_USD,
    CRYPTO_5M_IMPULSE_BPS,
    CRYPTO_5M_IMPULSE_WINDOW_SEC,
    CRYPTO_5M_NEUTRAL_BAND,
    CRYPTO_5M_SPREAD_THRESHOLD,
    CRYPTO_5M_MIN_SECONDS_LEFT,
    MIN_SHARES,
)

logger = logging.getLogger(__name__)

BINANCE_WS_BASE = "wss://stream.binance.com:9443/ws"
SYMBOL_MAP = {
    "BTC": "btcusdt",
    "ETH": "ethusdt",
    "XRP": "xrpusdt",
    "SOL": "solusdt",
}

# 5-minute markets trade for exactly 300 seconds starting at the slug-suffix
# epoch. Polymarket's `endDate` field is the 24h settlement-deadline, not the
# trading close, so we cannot trust it as the cutoff.
TRADING_WINDOW_SEC = 300
SLUG_EPOCH_RE = re.compile(r"-(\d{10})$")


@dataclass
class PriceFeed:
    """Bounded ring buffer of (timestamp_sec, price) tuples for one asset."""
    asset: str
    prices: deque = field(default_factory=lambda: deque(maxlen=2000))

    def add(self, price: float, ts_sec: float) -> None:
        self.prices.append((ts_sec, price))

    def latest(self) -> Optional[float]:
        return self.prices[-1][1] if self.prices else None

    def delta_bps(self, window_sec: float) -> Optional[float]:
        """Basis-point change between most-recent price and oldest within window."""
        if len(self.prices) < 2:
            return None
        now_ts = self.prices[-1][0]
        target = now_ts - window_sec
        # deque is ordered oldest-first; find the first entry inside the window
        old_price = None
        for ts, p in self.prices:
            if ts >= target:
                old_price = p
                break
        if old_price is None or old_price == 0:
            return None
        return (self.prices[-1][1] - old_price) / old_price * 10000.0


class BinanceStream(threading.Thread):
    """
    Background thread that maintains a live spot-price feed for one asset
    via Binance's public aggTrade WebSocket. Auto-reconnects on disconnect.
    """

    def __init__(self, asset: str, feed: PriceFeed):
        super().__init__(name=f"binance-{asset}", daemon=True)
        self.asset = asset.upper()
        self.feed = feed
        self.symbol = SYMBOL_MAP[self.asset]

    def run(self) -> None:
        url = f"{BINANCE_WS_BASE}/{self.symbol}@aggTrade"
        while True:
            try:
                logger.info(f"crypto5m: connecting Binance feed for {self.asset}")
                ws = WebSocketApp(
                    url,
                    on_message=self._on_msg,
                    on_error=self._on_err,
                    on_close=self._on_close,
                )
                ws.run_forever(ping_interval=20, ping_timeout=10)
            except Exception as e:
                logger.error(f"crypto5m: Binance {self.asset} stream crashed: {e}")
            time.sleep(5)

    def _on_msg(self, _ws, raw: str) -> None:
        try:
            msg = json.loads(raw)
            self.feed.add(float(msg["p"]), msg["T"] / 1000.0)
        except (KeyError, ValueError, json.JSONDecodeError):
            pass

    def _on_err(self, _ws, err) -> None:
        logger.error(f"crypto5m: Binance {self.asset} WS error: {err}")

    def _on_close(self, _ws, code, _reason) -> None:
        logger.info(f"crypto5m: Binance {self.asset} WS closed (code={code}), reconnecting...")


class Crypto5mScanner:
    """
    Discovers active 5m crypto up/down markets on Polymarket, monitors them
    against a live Binance price feed, fires on either of the two signals
    above. Single-leg BUYs sized to the Polymarket exchange minimum.
    """

    def __init__(self, client: ClobClient):
        self.client = client
        self.feeds: dict[str, PriceFeed] = {}
        self.market_cache: dict[str, dict] = {}  # slug -> {asset, up_token, down_token, open_ts, end_ts}
        self.fired_slugs: set[str] = set()
        self.last_window_start: int = 0

        for asset in CRYPTO_5M_ASSETS:
            if asset.upper() not in SYMBOL_MAP:
                logger.warning(f"crypto5m: asset {asset} not in SYMBOL_MAP, skipping")
                continue
            feed = PriceFeed(asset=asset.upper())
            self.feeds[asset.upper()] = feed
            stream = BinanceStream(asset, feed)
            stream.start()

    def _fetch_market_by_slug(self, slug: str) -> Optional[dict]:
        try:
            r = requests.get(
                f"{GAMMA_HOST}/markets",
                params={"slug": slug},
                timeout=10,
            )
            r.raise_for_status()
            data = r.json()
            if isinstance(data, list) and data:
                return data[0]
        except requests.RequestException as e:
            logger.warning(f"crypto5m: fetch by slug {slug} failed: {e}")
        return None

    def discover_markets(self) -> None:
        """
        Build/refresh the cache of currently-tradable markets.

        Polymarket pre-creates the next ~24h of 5m markets, so paginated listings
        return future-dated windows. To find the *currently* trading market, we
        derive the slug directly: `<asset>-updown-5m-<floor(now/300)*300>`.
        Each tradable window's slug is queried once and cached until the window
        rolls over.
        """
        now_ts = time.time()
        window_start = int(now_ts // TRADING_WINDOW_SEC) * TRADING_WINDOW_SEC
        window_close = window_start + TRADING_WINDOW_SEC

        # If the wall-clock 5m window hasn't changed and we already populated
        # this window's slugs, nothing to do.
        if window_start == self.last_window_start and self.market_cache:
            return

        self.last_window_start = window_start
        new_cache: dict[str, dict] = {}
        for asset in CRYPTO_5M_ASSETS:
            asset_u = asset.upper()
            if asset_u not in SYMBOL_MAP:
                continue
            slug = f"{asset.lower()}-updown-5m-{window_start}"
            seconds_left = window_close - now_ts
            if seconds_left <= CRYPTO_5M_MIN_SECONDS_LEFT:
                continue
            market = self._fetch_market_by_slug(slug)
            if not market:
                continue
            if market.get("closed") or not market.get("active"):
                continue
            ids_raw = market.get("clobTokenIds", "[]")
            try:
                tokens = json.loads(ids_raw) if isinstance(ids_raw, str) else ids_raw
            except (json.JSONDecodeError, TypeError):
                continue
            if not tokens or len(tokens) < 2:
                continue
            new_cache[slug] = {
                "asset": asset_u,
                "up_token": tokens[0],
                "down_token": tokens[1],
                "open_ts": window_start,
                "end_ts": window_close,
            }

        # Replace the cache; old slugs (previous window) drop out and their
        # fired_slugs entries are pruned below.
        self.market_cache = new_cache
        active_slugs = set(new_cache.keys())
        self.fired_slugs = {s for s in self.fired_slugs if s in active_slugs}
        logger.info(
            f"crypto5m: window {window_start}–{window_close}, "
            f"{len(new_cache)} market(s) in cache"
        )

    def fetch_top_of_book(self, token_id: str) -> tuple[Optional[float], Optional[float]]:
        """Returns (best_bid_price, best_ask_price) for a YES token."""
        try:
            r = requests.get(
                f"{CLOB_HOST}/book",
                params={"token_id": token_id},
                timeout=5,
            )
            r.raise_for_status()
            book = r.json()
        except requests.RequestException:
            return None, None
        if "error" in book:
            return None, None
        bids = book.get("bids") or []
        asks = book.get("asks") or []
        # bids are ascending — best (highest) bid is the LAST entry
        best_bid = float(bids[-1]["price"]) if bids else None
        # asks are ascending — best (lowest) ask is the FIRST entry
        best_ask = float(asks[0]["price"]) if asks else None
        return best_bid, best_ask

    def _expire_stale(self) -> None:
        """Drop markets that have already ended."""
        now_ts = time.time()
        expired = [s for s, m in self.market_cache.items() if m["end_ts"] <= now_ts]
        for s in expired:
            self.market_cache.pop(s, None)
            self.fired_slugs.discard(s)
        # If we expired everything, the window rolled — force a re-discovery
        # next tick by zeroing the cached window_start.
        if not self.market_cache:
            self.last_window_start = 0

    def _check_signal_b(self, slug: str, mkt: dict, up_ask: float, down_ask: float) -> bool:
        """Spread-floor mini-arbitrage. Both legs must fill to lock the edge."""
        spread = up_ask + down_ask
        if spread >= CRYPTO_5M_SPREAD_THRESHOLD:
            return False
        edge_pct = (1.0 / spread - 1.0) * 100 if spread > 0 else 0
        logger.info(
            f"crypto5m SIGNAL_B [{slug}] spread=${spread:.4f} "
            f"(up_ask=${up_ask:.3f} + down_ask=${down_ask:.3f}) edge={edge_pct:.2f}%"
        )
        up_ok = self._fire(mkt["up_token"], up_ask, slug, "spread_floor_up")
        down_ok = self._fire(mkt["down_token"], down_ask, slug, "spread_floor_down")
        return up_ok and down_ok

    def _check_signal_a(
        self, slug: str, mkt: dict, up_bid: Optional[float], up_ask: float, down_ask: float
    ) -> bool:
        """Binance impulse vs Polymarket mid lag."""
        feed = self.feeds[mkt["asset"]]
        delta = feed.delta_bps(CRYPTO_5M_IMPULSE_WINDOW_SEC)
        if delta is None or abs(delta) < CRYPTO_5M_IMPULSE_BPS:
            return False

        up_mid = ((up_bid + up_ask) / 2) if up_bid is not None else up_ask
        if abs(up_mid - 0.5) > CRYPTO_5M_NEUTRAL_BAND:
            # Polymarket already repriced — edge gone
            return False

        if delta > 0:
            logger.info(
                f"crypto5m SIGNAL_A [{slug}] BTC↑ {delta:+.1f}bps in "
                f"{CRYPTO_5M_IMPULSE_WINDOW_SEC}s, pm_up_mid={up_mid:.3f} → buy UP"
            )
            return self._fire(mkt["up_token"], up_ask, slug, "impulse_up")
        logger.info(
            f"crypto5m SIGNAL_A [{slug}] {mkt['asset']}↓ {delta:+.1f}bps in "
            f"{CRYPTO_5M_IMPULSE_WINDOW_SEC}s, pm_up_mid={up_mid:.3f} → buy DOWN"
        )
        return self._fire(mkt["down_token"], down_ask, slug, "impulse_down")

    def _fire(self, token_id: str, price: float, slug: str, signal: str) -> bool:
        """
        Place a BUY at the displayed ask price. Sizing: target CRYPTO_5M_MAX_TRADE_USD
        but never below MIN_SHARES (Polymarket's exchange floor).
        """
        if price <= 0:
            return False
        target_shares = max(CRYPTO_5M_MAX_TRADE_USD / price, MIN_SHARES)
        cost = target_shares * price
        try:
            order = self.client.create_and_post_order(
                OrderArgs(token_id=token_id, price=price, size=target_shares, side="BUY")
            )
            logger.info(
                f"crypto5m FIRE [{signal}] {slug}: {target_shares:.1f}sh @ "
                f"${price:.3f} = ${cost:.2f} | order={order}"
            )
            return True
        except Exception as e:
            logger.error(f"crypto5m FIRE FAILED [{signal}] {slug}: {e}")
            return False

    def scan_and_fire(self) -> int:
        """One tick: refresh discovery if window rolled, expire stale, check every market."""
        self.discover_markets()
        self._expire_stale()

        fires = 0
        for slug, mkt in list(self.market_cache.items()):
            if slug in self.fired_slugs:
                continue
            up_bid, up_ask = self.fetch_top_of_book(mkt["up_token"])
            down_bid, down_ask = self.fetch_top_of_book(mkt["down_token"])
            if up_ask is None or down_ask is None:
                continue
            if self._check_signal_b(slug, mkt, up_ask, down_ask):
                self.fired_slugs.add(slug)
                fires += 1
                continue
            if self._check_signal_a(slug, mkt, up_bid, up_ask, down_ask):
                self.fired_slugs.add(slug)
                fires += 1
        return fires
