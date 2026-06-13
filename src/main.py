import time
import logging
import sys
from auth import get_authenticated_client, check_geoblock
from watcher import TraderWatcher
from trader import CopyTrader
from arbitrage import ArbitrageScanner
from crypto_5m import Crypto5mScanner
from config import (
    TRADERS,
    POLL_INTERVAL_SEC,
    ARB_ENABLED,
    ARB_POLL_INTERVAL_SEC,
    CRYPTO_5M_ENABLED,
    CRYPTO_5M_POLL_INTERVAL_SEC,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)


def main():
    logger.info("=== Polymarket Copy Trading Bot Starting ===")

    if not check_geoblock():
        logger.error("Bot running from blocked region! Exiting.")
        sys.exit(1)

    logger.info("Authenticating with Polymarket CLOB...")
    client = get_authenticated_client()
    copy_trader = CopyTrader(client)

    watchers = []
    for t in TRADERS:
        logger.info(f"Setting up watcher for {t['name']} ({t['address'][:10]}...)")
        watcher = TraderWatcher(t["address"])
        watcher.seed_seen_trades()
        watchers.append({"name": t["name"], "watcher": watcher})

    arb_scanner = ArbitrageScanner(client) if ARB_ENABLED else None
    if arb_scanner:
        logger.info(
            f"Arb scanner enabled — scanning every {ARB_POLL_INTERVAL_SEC}s"
        )
    last_arb_scan = 0.0

    crypto_5m = Crypto5mScanner(client) if CRYPTO_5M_ENABLED else None
    if crypto_5m:
        logger.info(
            f"Crypto 5m scanner enabled — ticking every {CRYPTO_5M_POLL_INTERVAL_SEC}s"
        )
    last_crypto_scan = 0.0

    logger.info(f"Watching {len(watchers)} trader(s), polling every {POLL_INTERVAL_SEC}s...")
    while True:
        try:
            for entry in watchers:
                new_trades = entry["watcher"].get_new_trades()
                if new_trades:
                    logger.info(f"[{entry['name']}] Found {len(new_trades)} new trade(s)!")
                    for trade in new_trades:
                        copy_trader.copy_trade(trade, trader_name=entry["name"])

            if arb_scanner and (time.time() - last_arb_scan) >= ARB_POLL_INTERVAL_SEC:
                last_arb_scan = time.time()
                try:
                    arb_scanner.scan_and_fire()
                except Exception as e:
                    logger.error(f"Arb scan error: {e}", exc_info=True)

            if crypto_5m and (time.time() - last_crypto_scan) >= CRYPTO_5M_POLL_INTERVAL_SEC:
                last_crypto_scan = time.time()
                try:
                    crypto_5m.scan_and_fire()
                except Exception as e:
                    logger.error(f"crypto5m scan error: {e}", exc_info=True)

        except KeyboardInterrupt:
            logger.info("Bot stopped by user.")
            break
        except Exception as e:
            logger.error(f"Unexpected error in main loop: {e}", exc_info=True)

        time.sleep(POLL_INTERVAL_SEC)


if __name__ == "__main__":
    main()
