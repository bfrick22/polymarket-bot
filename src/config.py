import os
from dotenv import load_dotenv

load_dotenv()

# Wallet credentials
PRIVATE_KEY = os.getenv("PRIVATE_KEY")           # your Polygon wallet private key
POLY_ADDRESS = os.getenv("POLY_ADDRESS")          # your proxy wallet address (from polymarket.com/settings)

# Polymarket API endpoints
CLOB_HOST = "https://clob.polymarket.com"
GAMMA_HOST = "https://gamma-api.polymarket.com"
DATA_HOST = "https://data-api.polymarket.com"

# Trader to copy
TARGET_TRADER = os.getenv("TARGET_TRADER", "coldmath")  # the address, not username

# Copy trading settings
COPY_RATIO = float(os.getenv("COPY_RATIO", "0.1"))              # % of target's trade when target > MAX_TRADE_USD
COPY_RATIO_SMALL = float(os.getenv("COPY_RATIO_SMALL", "0.35")) # % of target's trade when target <= MAX_TRADE_USD
MAX_TRADE_USD = float(os.getenv("MAX_TRADE_USD", "50"))         # never copy more than $50/trade
POLL_INTERVAL_SEC = int(os.getenv("POLL_INTERVAL_SEC", "10"))  # check every 10 seconds

# Chain
CHAIN_ID = 137  # Polygon mainnet
