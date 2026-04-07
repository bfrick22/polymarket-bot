import time
import logging
import sys
from auth import get_authenticated_client, check_geoblock
from watcher import TraderWatcher
from trader import CopyTrader
from config import TARGET_TRADER, POLL_INTERVAL_SEC

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# Run scripts/lookup_trader.py to find this address, then set TARGET_TRADER in .env
COLDMATH_ADDRESS = TARGET_TRADER  # set TARGET_TRADER=0x... in your .env file


def main():
    logger.info("=== Polymarket Copy Trading Bot Starting ===")

    # 1. Geoblock check — MUST pass before trading
    logger.info("Checking geoblock status...")
    if not check_geoblock():
        logger.error("Bot running from blocked region! Orders will fail. Deploy to eu-west-1.")
        # In production: sys.exit(1)
        # For now, continue for development/testing of read-only features

    # 2. Set up the watcher (no auth needed)
    watcher = TraderWatcher(COLDMATH_ADDRESS)
    logger.info(f"Watching trader: {COLDMATH_ADDRESS}")

    # 3. Set up authenticated trading client
    logger.info("Authenticating with Polymarket CLOB...")
    client = get_authenticated_client()
    copy_trader = CopyTrader(client)

    # 4. Initial sync — see where they stand right now
    logger.info("Fetching current positions for initial sync...")
    positions = watcher.get_positions()
    logger.info(f"Target has {len(positions)} open positions")

    # 5. Main polling loop
    logger.info(f"Starting polling loop (every {POLL_INTERVAL_SEC}s)...")
    while True:
        try:
            new_trades = watcher.get_new_trades()

            if new_trades:
                logger.info(f"Found {len(new_trades)} new trade(s)!")
                for trade in new_trades:
                    copy_trader.copy_trade(trade)
            else:
                logger.debug("No new trades.")

        except KeyboardInterrupt:
            logger.info("Bot stopped by user.")
            break
        except Exception as e:
            logger.error(f"Unexpected error in main loop: {e}", exc_info=True)
            # Don't crash — log and continue

        time.sleep(POLL_INTERVAL_SEC)


if __name__ == "__main__":
    main()
