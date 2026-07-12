import time
import logging
import sys
from auth import get_authenticated_client, check_geoblock
from watcher import TraderWatcher
from trader import CopyTrader
from arbitrage import ArbitrageScanner
from crypto_5m import Crypto5mScanner
from news_scanner import NewsScanner
from daily_review import DailyReview
from claude_client import is_available as claude_available
from config import (
    TRADERS,
    POLL_INTERVAL_SEC,
    ARB_ENABLED,
    ARB_POLL_INTERVAL_SEC,
    CRYPTO_5M_ENABLED,
    CRYPTO_5M_POLL_INTERVAL_SEC,
    NEWS_SCAN_ENABLED,
    NEWS_SCAN_INTERVAL_MIN,
    DAILY_REVIEW_ENABLED,
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

    # Phase 4 modules — gated on ANTHROPIC_API_KEY presence
    news_scanner = NewsScanner(client) if (NEWS_SCAN_ENABLED and claude_available()) else None
    if news_scanner:
        logger.info(
            f"News scanner enabled — scanning every {NEWS_SCAN_INTERVAL_MIN} min (Sonnet 4.6)"
        )
    last_news_scan = 0.0
    news_interval_sec = NEWS_SCAN_INTERVAL_MIN * 60

    daily_review = DailyReview() if (DAILY_REVIEW_ENABLED and claude_available()) else None
    if daily_review:
        logger.info("Daily review enabled (Sonnet 4.6)")

    if not claude_available():
        logger.info(
            "Phase 4 disabled: ANTHROPIC_API_KEY not set. "
            "Add it to .secrets.env to enable news scanner, copy gate, and daily review."
        )

    logger.info(f"Watching {len(watchers)} trader(s), polling every {POLL_INTERVAL_SEC}s...")
    while True:
        try:
            for entry in watchers:
                new_trades = entry["watcher"].get_new_trades()
                if new_trades:
                    logger.info(f"[{entry['name']}] Found {len(new_trades)} new trade(s)!")
                    for trade in new_trades:
                        copy_trader.copy_trade(
                            trade,
                            trader_name=entry["name"],
                            trader_address=entry["watcher"].trader_address,
                        )

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

            if news_scanner and (time.time() - last_news_scan) >= news_interval_sec:
                last_news_scan = time.time()
                try:
                    news_scanner.scan_and_execute()
                except Exception as e:
                    logger.error(f"news_scanner error: {e}", exc_info=True)

            if daily_review:
                try:
                    daily_review.maybe_run()
                except Exception as e:
                    logger.error(f"daily_review error: {e}", exc_info=True)

        except KeyboardInterrupt:
            logger.info("Bot stopped by user.")
            break
        except Exception as e:
            logger.error(f"Unexpected error in main loop: {e}", exc_info=True)

        time.sleep(POLL_INTERVAL_SEC)


if __name__ == "__main__":
    main()
