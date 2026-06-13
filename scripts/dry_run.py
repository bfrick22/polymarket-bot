"""
Dry-run: for every trader in src/traders.json, fetch their most recent trade
and show what the bot WOULD copy. No orders placed.

Usage:
    python scripts/dry_run.py
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from watcher import TraderWatcher
from config import (
    TRADERS,
    COPY_RATIO,
    COPY_RATIO_SMALL,
    MAX_TRADE_USD,
    MIN_SHARES,
    MIN_POSITION_USD,
    MAX_EXPOSURE_PER_MARKET_USD,
    MARKET_KEYWORDS,
    MIRROR_SELLS,
)


def scale_size(target_shares: float, price: float) -> float:
    usd_value = target_shares * price
    ratio = COPY_RATIO_SMALL if usd_value <= MAX_TRADE_USD else COPY_RATIO
    our_usd = min(usd_value * ratio, MAX_TRADE_USD)
    return our_usd / price if price > 0 else 0


def describe(trade: dict, name: str) -> None:
    title = trade.get("title", "")
    side = (trade.get("side") or "").upper()
    price = float(trade.get("price", 0) or 0)
    shares = float(trade.get("size", 0) or 0)
    target_usd = shares * price

    print(f"  Market : {title[:80]}")
    print(f"  Side   : {side}")
    print(f"  Price  : ${price:.3f}")
    print(f"  Target : {shares:.2f} shares (${target_usd:.2f})")

    # Keyword filter
    if MARKET_KEYWORDS:
        if not any(kw in title.lower() for kw in MARKET_KEYWORDS):
            print(f"  → SKIP: title doesn't match any of MARKET_KEYWORDS")
            return

    if side == "SELL":
        if not MIRROR_SELLS:
            print("  → SKIP: MIRROR_SELLS=false (BUY-only mode)")
            return
        print("  → Would mirror SELL proportional to current held position")
        print("    (live bot queries your /positions to compute the right share count)")
        return

    our_shares = scale_size(shares, price)
    our_usd = our_shares * price
    print(f"  Scaled : {our_shares:.2f} shares (${our_usd:.2f}) "
          f"@ ratio {'COPY_RATIO_SMALL' if target_usd <= MAX_TRADE_USD else 'COPY_RATIO'}")

    if our_shares < MIN_SHARES:
        print(f"  → SKIP: {our_shares:.2f} sh < MIN_SHARES={MIN_SHARES}")
        return
    if our_usd < MIN_POSITION_USD:
        print(f"  → SKIP: ${our_usd:.3f} < MIN_POSITION_USD=${MIN_POSITION_USD}")
        return
    print(f"  → WOULD BUY (subject to per-market exposure cap ${MAX_EXPOSURE_PER_MARKET_USD})")


def main() -> None:
    if not TRADERS:
        print("No traders configured in src/traders.json")
        sys.exit(1)

    print(f"=== DRY RUN against {len(TRADERS)} trader(s) ===")
    print(f"  MARKET_KEYWORDS    : {MARKET_KEYWORDS or '(empty — all markets)'}")
    print(f"  COPY_RATIO         : {COPY_RATIO}  (large trades)")
    print(f"  COPY_RATIO_SMALL   : {COPY_RATIO_SMALL}  (small trades)")
    print(f"  MAX_TRADE_USD      : ${MAX_TRADE_USD}")
    print(f"  MIN_SHARES         : {MIN_SHARES}")
    print(f"  MAX_EXPOSURE/MARKET: ${MAX_EXPOSURE_PER_MARKET_USD}")
    print(f"  MIRROR_SELLS       : {MIRROR_SELLS}")
    print()

    for t in TRADERS:
        name = t["name"]
        addr = t["address"]
        print(f"--- {name} ({addr[:10]}...) ---")
        watcher = TraderWatcher(addr)
        trades = watcher.get_recent_trades(limit=1)
        if not trades:
            print("  No recent trades found.")
            continue
        describe(trades[0], name)
        print()


if __name__ == "__main__":
    main()
