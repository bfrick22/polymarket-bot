"""
Sell shares on a Polymarket CLOB token at the current best bid.

Defaults to a dry run — shows the order that WOULD be placed. Pass --live to
actually submit. Pass --price <float> to set a specific limit price instead
of taking best-bid.

Usage:
    # Dry run (see what it would do)
    python scripts/sell_position.py \\
        --token 39343707438379131883527162296681742264187661695159387350978687807542512925353 \\
        --shares 134.97

    # Live (actually submits the order)
    python scripts/sell_position.py \\
        --token 39343707438379131883527162296681742264187661695159387350978687807542512925353 \\
        --shares 134.97 \\
        --live

    # Custom limit price (e.g. wait for a slight premium)
    python scripts/sell_position.py \\
        --token ... --shares 134.97 --price 0.97 --live
"""
import argparse
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import requests
from py_clob_client_v2.clob_types import OrderArgs
from auth import get_authenticated_client
from config import CLOB_HOST


def get_best_bid(token_id: str) -> tuple[float, float] | tuple[None, None]:
    """Returns (best_bid_price, best_bid_size). None,None if no bids."""
    resp = requests.get(f"{CLOB_HOST}/book", params={"token_id": token_id}, timeout=10)
    resp.raise_for_status()
    book = resp.json()
    if "error" in book:
        raise RuntimeError(f"Orderbook error: {book['error']}")
    bids = book.get("bids") or []
    if not bids:
        return None, None
    # Bids are ascending — best (highest) bid is the LAST entry
    best = bids[-1]
    return float(best["price"]), float(best["size"])


def main() -> None:
    parser = argparse.ArgumentParser(description="Sell shares at best bid on Polymarket.")
    parser.add_argument("--token", required=True, help="CLOB token_id of the outcome to sell")
    parser.add_argument("--shares", required=True, type=float, help="Share count to sell")
    parser.add_argument(
        "--price",
        type=float,
        default=None,
        help="Optional limit price. Defaults to current best bid.",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Actually submit the order. Default is dry run.",
    )
    args = parser.parse_args()

    if args.shares < 5:
        print(f"ERROR: {args.shares} < 5 shares — below Polymarket's exchange minimum.")
        sys.exit(1)

    print("=== Orderbook check ===")
    best_bid, best_bid_size = get_best_bid(args.token)
    if best_bid is None:
        print("ERROR: no bids on the book. Nothing to sell against.")
        sys.exit(1)
    print(f"  best bid price: ${best_bid:.4f}")
    print(f"  best bid size : {best_bid_size:.2f} shares")

    price = args.price if args.price is not None else best_bid
    if args.price is not None and args.price > best_bid:
        print(
            f"\n  NOTE: your limit ${args.price:.4f} is above best bid ${best_bid:.4f}. "
            f"Order will REST on the book until someone matches it."
        )

    proceeds = args.shares * price
    print(f"\n=== Order that will be posted ===")
    print(f"  side  : SELL")
    print(f"  token : {args.token[:16]}...")
    print(f"  size  : {args.shares}")
    print(f"  price : ${price:.4f}")
    print(f"  gross : ${proceeds:.2f}")

    if not args.live:
        print("\n(dry run — pass --live to actually submit)")
        return

    print("\n=== Authenticating ===")
    client = get_authenticated_client()

    print("=== Submitting order ===")
    order = client.create_and_post_order(
        OrderArgs(
            token_id=args.token,
            price=price,
            size=args.shares,
            side="SELL",
        )
    )
    print(f"\nOrder response:\n{order}")


if __name__ == "__main__":
    main()
