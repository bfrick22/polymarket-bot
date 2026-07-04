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

# Ultra-short crypto scanner (Phase 3) — Binance latency arb + spread floor
CRYPTO_5M_ENABLED = os.getenv("CRYPTO_5M_ENABLED", "true").lower() in ("1", "true", "yes")
CRYPTO_5M_POLL_INTERVAL_SEC = int(os.getenv("CRYPTO_5M_POLL_INTERVAL_SEC", "5"))
_raw_assets = os.getenv("CRYPTO_5M_ASSETS", "BTC,XRP")
CRYPTO_5M_ASSETS = [a.strip().upper() for a in _raw_assets.split(",") if a.strip()]
CRYPTO_5M_MAX_TRADE_USD = float(os.getenv("CRYPTO_5M_MAX_TRADE_USD", "1.0"))
# Signal A — Binance impulse
# 10 bps default (was 3): only fire when Binance moves significantly, not on
# every microtick. 3 bps was firing constantly and paying 90c+ asks that
# resolved to $0 on any reversal.
CRYPTO_5M_IMPULSE_BPS = float(os.getenv("CRYPTO_5M_IMPULSE_BPS", "10.0"))
CRYPTO_5M_IMPULSE_WINDOW_SEC = float(os.getenv("CRYPTO_5M_IMPULSE_WINDOW_SEC", "5"))
# Tighter neutral band (was 0.10 → 0.05): if Polymarket mid has already moved
# past 0.55, the edge is gone and we'd be chasing.
CRYPTO_5M_NEUTRAL_BAND = float(os.getenv("CRYPTO_5M_NEUTRAL_BAND", "0.05"))
# Hard ceiling on Signal A entry price. Refuses to pay more than this per share
# for a directional bet. At $0.60 the risk/reward is $0.60 to make $0.40 vs
# $0.99 to make $0.01 under the old settings.
CRYPTO_5M_MAX_ENTRY_PRICE = float(os.getenv("CRYPTO_5M_MAX_ENTRY_PRICE", "0.60"))
# Signal B — spread floor
CRYPTO_5M_SPREAD_THRESHOLD = float(os.getenv("CRYPTO_5M_SPREAD_THRESHOLD", "0.97"))
# Don't fire if the market resolves in less than this many seconds (avoid stale fills)
CRYPTO_5M_MIN_SECONDS_LEFT = float(os.getenv("CRYPTO_5M_MIN_SECONDS_LEFT", "60"))

# Chain
CHAIN_ID = 137  # Polygon mainnet
