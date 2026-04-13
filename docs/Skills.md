# Bot Skills

Capabilities of the Polymarket copy-trading bot and the modules that implement them.

> **Maintenance rule:** Whenever code changes are made to this bot — bug fixes, new features, config additions, or logic changes — Claude must review and update this file and `Rules.md` to reflect the current behavior before the work is considered complete.

---

## Authentication (`src/auth.py`)

Derives L2 API credentials from a Polygon private key using Polymarket's CLOB client. The same private key always produces the same API key (deterministic derivation via nonce), so credentials do not need to be stored separately.

- Supports `signature_type=1` (POLY_PROXY) for Google/email login accounts
- Supports `signature_type=2` (GNOSIS_SAFE) for wallet-based login accounts
- Validates geoblock status before allowing any trading activity

**Required config:** `PRIVATE_KEY`, `POLY_ADDRESS`

---

## Trade Watching (`src/watcher.py`)

Polls the Polymarket Data API for new trades by a target wallet address. No authentication required — the trades endpoint is public.

- Fetches the last N trades on each poll cycle
- Deduplicates by `transactionHash` so each trade is processed once
- Seeds seen trades on startup to avoid replaying history
- Can also fetch the target's current open positions

**Rate limit:** 200 req/10s (well within the 10s poll interval)

---

## Position Sizing (`src/trader.py → scale_size`)

Converts the target's trade into a proportional position using a tiered ratio system:

- **Small trades** (target USD ≤ MAX_TRADE_USD): use `COPY_RATIO_SMALL` for a more meaningful copy position
- **Large trades** (target USD > MAX_TRADE_USD): use `COPY_RATIO`, always capped at `MAX_TRADE_USD`

Converts between USD and shares using the trade price.

---

## Trade Copying (`src/trader.py → copy_trade`)

Takes a raw trade object from the watcher and places a mirrored order on the CLOB:

1. Extracts token ID, side (BUY/SELL), price, and share count
2. Scales the position via the sizing rules above
3. Skips trades that fall below Polymarket's 5-share minimum
4. Submits the order via `create_and_post_order`
5. Logs the outcome; errors are caught and skipped without crashing

---

## Main Loop (`src/main.py`)

Orchestrates all skills in sequence:

1. Geoblock check (exit if blocked)
2. Initialize watcher for the target trader
3. Authenticate and create trading client
4. Fetch current positions for initial sync
5. Seed seen trades
6. Poll indefinitely, copying any new trades found

Recovers from unexpected errors without crashing — logs and continues.
