"""
Dry-run: shows what the bot would copy from coldmath's last trade.
No orders are placed.
"""
import sys
sys.path.insert(0, 'src')

from watcher import TraderWatcher
from config import TARGET_TRADER, COPY_RATIO, MAX_TRADE_USD
import os

addr = TARGET_TRADER
print(f"Fetching latest trade for {addr[:10]}...")

w = TraderWatcher(addr)
trades = w.get_recent_trades(limit=1)

if not trades:
    print("No trades found.")
    sys.exit(1)

trade = trades[0]
price = float(trade["price"])
shares = float(trade["size"])
usd = shares * price
our_usd = min(usd * COPY_RATIO, MAX_TRADE_USD)
our_shares = our_usd / price if price > 0 else 0

print(f"\nLatest trade:")
print(f"  Market : {trade['title']}")
print(f"  Side   : {trade['side']}")
print(f"  Price  : {price}")
print(f"  Target : {shares:.2f} shares (${usd:.2f})")
print(f"\nWe would place:")
print(f"  {our_shares:.2f} shares @ {price} = ${our_usd:.2f}")
print(f"  (COPY_RATIO={COPY_RATIO}, MAX_TRADE_USD={MAX_TRADE_USD})")
