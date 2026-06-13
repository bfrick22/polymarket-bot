# Copy Trading Rules

Rules governing when and how the bot copies trades and runs the arbitrage scanner.

> **Maintenance rule:** Whenever code changes are made to this bot — bug fixes, new features, config additions, or logic changes — Claude must review and update this file and `Skills.md` to reflect the current behavior before the work is considered complete.

---

## 1. Geoblock Gate

The bot checks Polymarket's geoblock API at startup. If the current IP is in a blocked region (US included), the bot exits immediately. No trades are placed.

---

## 2. Startup Seeding

On launch the bot fetches recent trades from each target trader and marks them as already seen. This prevents replaying historical trades — only trades that occur **after** the bot starts are copied.

---

## 3. Trade Detection

The bot polls each target trader's trade history every `POLL_INTERVAL_SEC` seconds (default: 10s). Each trade is uniquely identified by its `transactionHash`. A trade is copied exactly once.

Both BUY and SELL trades are emitted by the watcher — the copy logic decides what to do with each side.

---

## 4. Position Sizing (BUY)

Trade size is determined by the target's USD value (`shares × price`) and which tier it falls into:

| Target Trade Size | Ratio Applied | Cap |
|---|---|---|
| ≤ `MAX_TRADE_USD` (small) | `COPY_RATIO_SMALL` (default 35%) | `MAX_TRADE_USD` |
| > `MAX_TRADE_USD` (large) | `COPY_RATIO` (default 10%) | `MAX_TRADE_USD` |

**Rationale:** Small trades from the target would result in near-zero positions at a flat ratio. A higher ratio on small trades keeps your copy position meaningful.

**Example:**
- Target buys $0.42 worth → small trade → you put in $0.15 (35%)
- Target buys $200 worth → large trade → you put in $20 (capped at `MAX_TRADE_USD`)

---

## 5. Minimum Trade Size

After scaling, a BUY is skipped if:

- `our_shares < MIN_SHARES` (default 5 — Polymarket's exchange minimum), **OR**
- `our_usd < MIN_POSITION_USD` (default $0.10)

The previous $1 USD floor was filtering out coldmath-style 1¢-7¢ longshot entries; lowering it lets those into the portfolio.

---

## 6. Per-Market Exposure Cap

Before any BUY, the bot queries our current position on that token. If our existing exposure on that market is already ≥ `MAX_EXPOSURE_PER_MARKET_USD` (default $5), the BUY is skipped. If only partial room is available, the BUY is trimmed to fit.

**Rationale:** This prevents the kind of concentration loss that produced -$27.56 on a single 1-degree NYC temperature bucket.

---

## 7. SELL Mirroring

When `MIRROR_SELLS=true` (default), the bot mirrors target SELLs as well as BUYs:

- The bot queries our current position on the same token.
- If we hold none, the SELL is skipped.
- The bot computes a proportional close: if the target is selling a fraction *f* of their initial position, we sell *f* × our holdings (capped at our total holdings).
- If the proportional size would be below `MIN_SHARES` but we have ≥ `MIN_SHARES` total, we sell exactly `MIN_SHARES` (don't leave dust).

**Rationale:** The previous bot only placed BUYs (1.2% SELL rate on our wallet), so profits decayed back and losers ran to resolution. Mirroring SELLs harvests profit and cuts losing positions.

---

## 8. Market Keyword Filter

If `MARKET_KEYWORDS` is non-empty (default: weather-related terms), copy trades are only placed when the trade's market title matches at least one keyword. Set `MARKET_KEYWORDS=""` to copy all markets.

The keyword filter does **not** apply to the arbitrage scanner.

---

## 9. Multi-Outcome Arbitrage Scanner

When `ARB_ENABLED=true` (default), the bot scans the Gamma `/events` endpoint every `ARB_POLL_INTERVAL_SEC` seconds (default 60s) for events with mutually-exclusive YES outcomes whose price sum has fallen below the arb threshold.

A basket qualifies if **all** of these hold:

| Constraint | Default | Why |
|---|---|---|
| `event.negRisk == True` | — | Polymarket's flag for true mutual exclusion. Date-bucketed events ("by May X / by June X") and price-tier baskets ("Bitcoin hits $X") look like arbs but multiple YES can resolve, so the basket is **not** guaranteed profit. Without this gate, ~57% of high-volume events would be incorrectly eligible. |
| `n_outcomes ≥ ARB_MIN_OUTCOMES` | 3 | Pair markets aren't always mutually exclusive |
| `n_outcomes ≤ ARB_MAX_OUTCOMES` | 30 | Filters out paired-market events (e.g. NBA games with 100+ markets) and keeps per-leg size above minimum |
| `sum(YES) < ARB_THRESHOLD` | 0.97 | Edge after rounding |
| `(1/sum_yes − 1) ≥ ARB_MIN_EDGE` | 0.015 (1.5%) | Net edge required |
| `event_id not in filled set` | — | Don't re-buy a basket we already locked in |

For a qualifying basket the scanner buys *K* shares of every YES outcome at the displayed price, where `K = ARB_MAX_BASKET_USD / sum_yes`. Since exactly one YES resolves to $1.00, the basket pays exactly *K* dollars at resolution. Net profit = `K × (1 - sum_yes)`.

Partial fills are tolerated but logged as `ARB PARTIAL` — the missed legs degrade but rarely invert the guarantee.

The scanner does **not** sell legs — they're held to resolution.

---

## 10. Ultra-short Crypto Scanner (Phase 3)

When `CRYPTO_5M_ENABLED=true` (default), the bot scans Polymarket's rolling 5-minute up/down crypto markets every `CRYPTO_5M_POLL_INTERVAL_SEC` seconds (default 5s).

Active markets are discovered via `GET /markets?active=true&closed=false&order=createdAt&ascending=false`, filtered by slug prefix `<asset>-updown-5m-*`. Discovery is refreshed every 30 seconds.

For each active market the scanner reads the live top-of-book on both YES tokens (`/book?token_id=...`) and evaluates two independent signals:

**Signal A — Binance latency arbitrage.** Spot price on Binance (via public `aggTrade` WebSocket; no Binance account or API key needed) must move more than `CRYPTO_5M_IMPULSE_BPS` (default 3 bps = 0.03%) over the trailing `CRYPTO_5M_IMPULSE_WINDOW_SEC` (default 5s) window, AND the Polymarket Up market's mid must still be within `0.5 ± CRYPTO_5M_NEUTRAL_BAND` (default ±0.10, i.e. unrepriced). On hit, the scanner buys YES on the direction Binance moved.

**Signal B — spread floor.** Up_ask + Down_ask must be below `CRYPTO_5M_SPREAD_THRESHOLD` (default 0.97). Up/Down are mutually exclusive on these markets, so the basket pays exactly $1 at resolution regardless of which side wins. On hit, the scanner buys BOTH YES sides. Locked-in profit.

A market is also skipped if it expires sooner than `CRYPTO_5M_MIN_SECONDS_LEFT` (default 60s) — avoids stale fills that won't have time to resolve.

Each fire is sized to `max(CRYPTO_5M_MAX_TRADE_USD / price, MIN_SHARES)` — i.e. target $1, but never below the Polymarket 5-share exchange minimum. On a 50¢ entry this means $2.50 actual.

Once a market is filled (either signal), its slug is added to `fired_slugs` and won't be re-checked. The slug leaves the set when the market expires from the discovery cache.

Binance WebSocket runs in one daemon thread per asset; auto-reconnects on disconnect.

---

## 11. Error Handling

A failed trade or scanner cycle (API error, 401, timeout) is logged and skipped. The bot does **not** crash or retry — it continues to the next poll cycle.

---

## Configuration Reference

All rules are tunable via `.env` without code changes:

| Variable | Default | Description |
|---|---|---|
| `COPY_RATIO` | `0.10` | Copy ratio for large trades (target > `MAX_TRADE_USD`) |
| `COPY_RATIO_SMALL` | `0.35` | Copy ratio for small trades (target ≤ `MAX_TRADE_USD`) |
| `MAX_TRADE_USD` | `50` | Hard cap per copied trade in USD |
| `MIN_SHARES` | `5` | Polymarket exchange minimum order size |
| `MIN_POSITION_USD` | `0.10` | USD floor; below this the BUY is skipped |
| `MAX_EXPOSURE_PER_MARKET_USD` | `5` | Per-market exposure ceiling for BUYs |
| `MIRROR_SELLS` | `true` | If true, mirror target SELLs proportionally |
| `POLL_INTERVAL_SEC` | `10` | Seconds between trade-watcher polls |
| `MARKET_KEYWORDS` | weather terms | Comma-separated title filter; empty = all markets |
| `ARB_ENABLED` | `true` | Enable the multi-outcome arb scanner |
| `ARB_POLL_INTERVAL_SEC` | `60` | Seconds between arb scans |
| `ARB_THRESHOLD` | `0.97` | sum(YES) must be below this for a basket to qualify |
| `ARB_MIN_EDGE` | `0.015` | Minimum guaranteed return (1.5%) |
| `ARB_MAX_BASKET_USD` | `20` | Maximum total USD per arb basket |
| `ARB_MIN_OUTCOMES` | `3` | Minimum legs in a qualifying basket |
| `ARB_MAX_OUTCOMES` | `30` | Maximum legs in a qualifying basket |
| `CRYPTO_5M_ENABLED` | `true` | Enable the ultra-short crypto scanner |
| `CRYPTO_5M_POLL_INTERVAL_SEC` | `5` | Scanner tick cadence |
| `CRYPTO_5M_ASSETS` | `BTC,XRP` | Assets to scan; must map to a Binance pair in `SYMBOL_MAP` |
| `CRYPTO_5M_MAX_TRADE_USD` | `1.0` | Target USD per fire (rounds up to MIN_SHARES) |
| `CRYPTO_5M_IMPULSE_BPS` | `3.0` | Signal A trigger: Binance Δ over the window |
| `CRYPTO_5M_IMPULSE_WINDOW_SEC` | `5` | Signal A window |
| `CRYPTO_5M_NEUTRAL_BAND` | `0.10` | Signal A gate: Polymarket mid must be within 0.5 ± this |
| `CRYPTO_5M_SPREAD_THRESHOLD` | `0.97` | Signal B trigger: up_ask + down_ask below this |
| `CRYPTO_5M_MIN_SECONDS_LEFT` | `60` | Skip markets resolving sooner than this |
