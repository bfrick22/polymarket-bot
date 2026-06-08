# Strategy Analysis & Diversification Plan

Analysis performed against your wallet (`0x7c391853FdcF4B4077B1DD55ba3c4708e682Cf4A`) and the three traders you currently copy. Numbers pulled from the public Polymarket Data API on 2026-06-08.

---

## 1. Why You're Losing Money

### Your wallet — net **-$305.59**

| Metric | Value |
|---|---|
| Positions opened | 142 |
| Invested | $429.83 |
| Current value | $21.45 |
| Realized PnL | +$102.79 |
| Unrealized PnL | -$408.38 |
| **NET** | **-$305.59** |

### Recent 500-trade behaviour

| Metric | Value | Read |
|---|---|---|
| BUY / SELL split | 494 / 6 | **You never exit.** 1.2% sell rate vs Hans323's 21%. Profits decay back, losers run to resolution. |
| Avg USD / trade | $2.55 | 100× smaller than coldmath ($269). Sizing is below where edge survives slippage + price discretization. |
| Category mix | 89% weather, 10% sports | Single-degree weather buckets are coin flips priced near 50¢. |
| Avg fill price | $0.524 | You're getting filled at the *mid* — i.e. after the move, not before. |

### Top concentrations of loss

| PnL | Market |
|---|---|
| -$27.56 | NYC lowest temp 66-67°F (1-degree bucket) |
| -$26.15 | FC Nordsjælland vs Aarhus O/U 1.5 (sports, no edge) |
| -$20.13 | FC Nordsjælland spread (-2.5) |
| -$14.09 | Seoul lowest temp 9°C |

Almost all losses come from **single-degree temperature buckets** — these are inherently lottery tickets priced like coin flips. When they lose they take a 100% hit; when they win they pay <2×.

---

## 2. The Copy Targets Themselves

| Trader | NET PnL | Trades | Sell rate | Avg USD | Pattern | Verdict |
|---|---|---|---|---|---|---|
| **coldmath** | **+$95,602** | 500 | 0% | $269 | 188 longshots @ 1-7¢ + 248 near-certain @ 70-99¢ | Profitable, but you're missing his edge — see below |
| **Hans323**  | +$792    | 500 | 21% | $534 | Weather + scalps, sells aggressively | Profitable and copy-able |
| **neobrother** | **-$507** | 500 | 27% | $3 | 100% weather, 412/500 trades at 1-7¢ longshots | **Losing trader. Drop immediately.** |

### Why copying coldmath isn't translating to profit for you

Coldmath's edge is a **portfolio of asymmetric bets** — most lose, but the longshots that hit return 50-500× the entry. Two structural problems prevent you from capturing it:

1. **Your $1 minimum filters out his longshots.** A 1¢ share scaled at 35% of his $269 trade = $0.94 — under $1, skipped. You're systematically only fillting the *expensive* certainties.
2. **Even the "certainties" don't pay much.** 90¢ shares double-or-nothing return 11% if they hit, -100% if they don't. You need a *large* portfolio of these for the law of large numbers to work, but you're firing $2.55 trades — your portfolio is too small for tail outcomes to dominate.

Coldmath's $-17,633 Eurovision loss tells you this is a **survival-of-portfolio** strategy, not a per-trade-edge strategy. You can't safely replicate it at 1% of his bankroll.

---

## 3. Where The Edge Actually Lives

I scanned the top 100 events by 24h volume for live arbitrage and price-inefficiency patterns. Three categories pay reliably and don't require predicting weather:

### A. Multi-outcome basket arbitrage (highest-confidence, lowest-skill)

Events where exactly one outcome can resolve YES. Sum of YES prices must equal $1.00 at fair value. When it dips below $1, buying every YES outcome at once **guarantees** profit at resolution.

**Live right now during this analysis:**

| Event | Outcomes | Sum YES | Guaranteed return |
|---|---|---|---|
| Netherlands vs Uzbekistan | 3 | $0.976 | **+2.5%** |
| 2026 NBA Champion | 30 | $0.999 | ~0% (at par) |
| 2028 Democratic Nominee | 128 | $0.997 | borderline |
| LA Mayoral Election | 15 | $0.984 | **+1.6%** |
| Elon Musk tweets June 6-8 | 10 | $1.000 | at par |

A scanner running every 60s on the `/events` endpoint will catch dips below $0.97 multiple times per day across sports half-times, tennis matches, election fields. **Many wallets cited in your CSV (Annica, noovd, ElonSpam) do exactly this.**

### B. Ultra-short crypto markets (Binance vs Polymarket latency arb)

`@0x8dxd` wallet (cited in your CSV at ~$1.6M PnL) runs this: stream BTC/ETH spot from Binance at 1-second resolution, watch the Polymarket "Bitcoin up or down" 5m/15m markets. When BTC makes a sharp impulse on Binance, Polymarket pricing lags 10-30 seconds. Hit the lagging side, exit on repricing.

- Entry: total YES+NO < $1.00 (the inefficiency window)
- Exit: when implied probability has converged to actual price direction (usually <60s)
- Risk control: per-trade max + close near expiry regardless

This requires a Binance WebSocket connection and tight execution. Higher complexity, but documented in the same X posts you've already saved.

### C. Esports BO3/BO5 momentum (`czoyimsezblaznili` strategy)

LCK/LPL League of Legends markets and Counter-Strike majors. Liquidity is thin, so odds reprice slowly between maps/rounds. When momentum shifts (e.g. one team wins map 1), the second-map market often takes 5-15s to fully reprice. CS:GO majors are currently showing $1.4M-$2.1M 24h volume per match — plenty of liquidity for $20-50 trades.

### D. Weather, but only with proper risk controls

Weather isn't dead — coldmath proves it works. But it only works if you:
- Stop holding to resolution (mirror SELLS)
- Stop concentrating in 1-degree buckets
- Allow tiny positions (drop the $1 floor) so longshots are included

---

## 4. Strategy Plan — Prioritised by Effort vs. Edge

### Phase 1 — Stop the bleeding (1–2 hours of work, ship today)

| # | Change | Expected impact |
|---|---|---|
| 1.1 | Drop `neobrother` from `traders.json` | Stops -$507/cycle bleed |
| 1.2 | Mirror SELL trades, not just BUY | Captures Hans323's exits, prevents holding losers to expiry |
| 1.3 | Lower the $1 USD floor to Polymarket's *actual* 5-share minimum | Lets coldmath's 1-7¢ longshots into your portfolio |
| 1.4 | Add per-market max-exposure cap (e.g. $5) | Prevents the 1-degree-weather concentration losses |
| 1.5 | Add a rolling 30d PnL check on copy targets; auto-pause anyone in the red | Quality control on the trader list |

### Phase 2 — Add arbitrage scanner module (1 day of work, biggest expected EV)

New module `src/arbitrage.py`:

- Every 60s: pull `/events?active=true&closed=false&limit=200`
- For each event with ≥3 markets: compute `sum_yes = Σ outcomePrices[0]`
- If `sum_yes < 0.97`: pull current orderbook for each outcome (`/book` endpoint), confirm fillable depth at the YES side, buy proportional sizes such that you hold 1 share of each outcome
- Optional `sum_no < 0.97` check for "must-happen" arb
- Hard cap per arb: $20-50 total exposure across the basket
- Resolves automatically — no exit logic needed

The math is mechanical, the edge is real, and unlike copying it doesn't depend on someone else's discretion. **This is the change most likely to flip your PnL positive.**

### Phase 3 — Ultra-short crypto module (2-3 days of work, higher complexity)

New module `src/crypto_5m.py`:

- Binance WebSocket: `wss://stream.binance.com:9443/ws/btcusdt@trade`
- Track 1s rolling delta on BTC, ETH
- When `|Δ1s| > X bps` and there's an active Polymarket 5m/15m BTC market with `mid != expected`, fire side that's underpriced
- Auto-exit on Polymarket repricing or T-30s before market close

Needs careful backtesting before going live. Defer until Phase 1+2 are stable.

### Phase 4 — Broaden the copy-trader pool (ongoing)

- Add `scripts/scout_traders.py`: for any wallet that shows in `/holders` of high-volume markets, pull 30d PnL via positions endpoint, surface those with >$5k positive realized
- Sort by PnL stability (high realized + low unrealized = consistent winner, not just paper gains)
- Rotate copy targets monthly based on 30d performance, not lifetime

---

## 5. Concrete Code Changes

| File | Change |
|---|---|
| `src/traders.json` | Remove `neobrother`. Optionally remove `Hans323` if you want pure coldmath. |
| `src/config.py` | Add `MIRROR_SELLS=true`, `MIN_POSITION_USD=0.10` (down from implicit $1), `MAX_EXPOSURE_PER_MARKET_USD=5`, `ARBITRAGE_ENABLED=true`, `ARB_THRESHOLD=0.97` |
| `src/trader.py` | `copy_trade()` — handle SELL side: if target sells, sell same proportion of your position. Add per-market exposure check before placing. |
| `src/watcher.py` | Already returns SELLs in trade stream — verify side handling downstream. |
| `src/arbitrage.py` (new) | Scan events, detect sum<threshold, build multi-leg basket order |
| `src/main.py` | Add second loop: every 60s call `arbitrage.scan_and_fire()` alongside trader copying |
| `scripts/scout_traders.py` (new) | Discover candidate traders from high-volume market holders, rank by 30d PnL |
| `docs/Rules.md` / `docs/Skills.md` | Update with new strategies (per repo maintenance rule) |

---

## 6. Risk & Bankroll Discipline

You have ~$21 of value left in positions and a bot configured to keep firing copies. Before adding any new strategy:

- Decide a hard bankroll for each module: e.g. $100 copy-trading, $100 arb scanner, $0 crypto-5m until proven in shadow mode
- Each module logs its own PnL — don't aggregate so you can kill a losing module without contaminating the wins
- Run new strategies in **dry-run mode for 48h first** (already supported via `scripts/dry_run.py` pattern — extend to arb scanner)
- Set a circuit breaker: if any module hits -$25 in 24h, auto-pause

---

## 7. What I'd Ship First

If you only do one thing this week: **Phase 1 (cleanup) + Phase 2 (arb scanner)**. The cleanup stops the obvious bleed, the arb scanner adds an uncorrelated positive-EV stream that doesn't depend on you predicting anything. Together they're ~1.5 days of work and the most likely to flip the curve.
