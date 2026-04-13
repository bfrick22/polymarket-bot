# Copy Trading Rules

Rules governing when and how the bot copies trades from the target trader.

> **Maintenance rule:** Whenever code changes are made to this bot — bug fixes, new features, config additions, or logic changes — Claude must review and update this file and `Skills.md` to reflect the current behavior before the work is considered complete.

---

## 1. Geoblock Gate

The bot checks Polymarket's geoblock API at startup. If the current IP is in a blocked region (US included), the bot exits immediately. No trades are placed.

---

## 2. Startup Seeding

On launch the bot fetches recent trades from the target and marks them as already seen. This prevents replaying historical trades — only trades that occur **after** the bot starts are copied.

---

## 3. Trade Detection

The bot polls the target trader's trade history every `POLL_INTERVAL_SEC` seconds (default: 10s). Each trade is uniquely identified by its `transactionHash`. A trade is copied exactly once.

---

## 4. Position Sizing

Trade size is determined by the target's USD value (`shares × price`) and which tier it falls into:

| Target Trade Size | Ratio Applied | Cap |
|---|---|---|
| ≤ `MAX_TRADE_USD` (small) | `COPY_RATIO_SMALL` (default 35%) | `MAX_TRADE_USD` |
| > `MAX_TRADE_USD` (large) | `COPY_RATIO` (default 15%) | `MAX_TRADE_USD` |

**Rationale:** Small trades from the target would result in near-zero positions at a flat ratio. A higher ratio on small trades keeps your copy position meaningful.

**Example:**
- Target buys $0.42 worth → small trade → you put in $0.15 (35%)
- Target buys $200 worth → large trade → you put in $20 (capped at MAX_TRADE_USD)

---

## 5. Minimum Share Filter

After scaling, if the resulting position is fewer than **5 shares**, the trade is skipped. This is Polymarket's minimum order size. The skip is logged.

---

## 6. Error Handling

A failed trade (API error, 401, timeout) is logged and skipped. The bot does **not** crash or retry — it continues to the next poll cycle.

---

## Configuration Reference

All rules are tunable via `.env` without code changes:

| Variable | Default | Description |
|---|---|---|
| `COPY_RATIO` | `0.15` | Copy ratio for large trades (target > MAX_TRADE_USD) |
| `COPY_RATIO_SMALL` | `0.35` | Copy ratio for small trades (target ≤ MAX_TRADE_USD) |
| `MAX_TRADE_USD` | `20` | Hard cap per copied trade in USD |
| `POLL_INTERVAL_SEC` | `10` | Seconds between trade checks |
| `TARGET_TRADER` | — | Wallet address of the trader to copy |
