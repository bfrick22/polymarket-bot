import os
import json
from dotenv import load_dotenv

load_dotenv()

# Wallet credentials
PRIVATE_KEY = os.getenv("PRIVATE_KEY")           # your Polygon wallet private key
POLY_ADDRESS = os.getenv("POLY_ADDRESS")          # your proxy wallet address (from polymarket.com/settings)

# Polymarket API endpoints
CLOB_HOST = "https://clob.polymarket.com"
GAMMA_HOST = "https://gamma-api.polymarket.com"
DATA_HOST = "https://data-api.polymarket.com"

# Traders to copy
_traders_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'traders.json')
with open(_traders_file) as _f:
    TRADERS = json.load(_f)

# Copy trading settings
COPY_RATIO = float(os.getenv("COPY_RATIO", "0.1"))              # % of target's trade when target > MAX_TRADE_USD
COPY_RATIO_SMALL = float(os.getenv("COPY_RATIO_SMALL", "0.35")) # % of target's trade when target <= MAX_TRADE_USD
MAX_TRADE_USD = float(os.getenv("MAX_TRADE_USD", "50"))         # never copy more than $50/trade
POLL_INTERVAL_SEC = int(os.getenv("POLL_INTERVAL_SEC", "10"))  # check every 10 seconds

# Polymarket order floor is 5 shares (not $1 USD). Setting the USD floor lower
# unlocks coldmath-style 1-7c longshot entries that were being filtered out.
MIN_SHARES = float(os.getenv("MIN_SHARES", "5"))
MIN_POSITION_USD = float(os.getenv("MIN_POSITION_USD", "0.10"))

# Per-market exposure cap (USD) — prevents concentration losses on single-degree
# weather buckets where one bad outcome can wipe out gains.
MAX_EXPOSURE_PER_MARKET_USD = float(os.getenv("MAX_EXPOSURE_PER_MARKET_USD", "5"))

# Mirror the target's SELL trades, not just BUYs. Without this, we hold every
# position to resolution and never harvest profit or cut losers.
MIRROR_SELLS = os.getenv("MIRROR_SELLS", "true").lower() in ("1", "true", "yes")

# Market filter — only copy trades whose title contains one of these keywords (case-insensitive)
# Set to empty string to copy all markets
_raw = os.getenv("MARKET_KEYWORDS", "weather,temperature,rain,snow,hurricane,tornado,precipitation,degrees,wind,flood,frost,hail,blizzard,drought")
MARKET_KEYWORDS = [kw.strip().lower() for kw in _raw.split(",") if kw.strip()]

# Multi-outcome arbitrage scanner (Phase 2)
ARB_ENABLED = os.getenv("ARB_ENABLED", "true").lower() in ("1", "true", "yes")
ARB_POLL_INTERVAL_SEC = int(os.getenv("ARB_POLL_INTERVAL_SEC", "60"))
ARB_THRESHOLD = float(os.getenv("ARB_THRESHOLD", "0.97"))       # sum_YES must be < this to qualify
ARB_MIN_EDGE = float(os.getenv("ARB_MIN_EDGE", "0.015"))         # min 1.5% guaranteed return after rounding
ARB_MAX_BASKET_USD = float(os.getenv("ARB_MAX_BASKET_USD", "20"))  # max total $ across a single arb basket
ARB_MIN_OUTCOMES = int(os.getenv("ARB_MIN_OUTCOMES", "3"))       # need at least this many YES outcomes
ARB_MAX_OUTCOMES = int(os.getenv("ARB_MAX_OUTCOMES", "30"))      # skip baskets so wide each leg is < min size

# Chain
CHAIN_ID = 137  # Polygon mainnet
