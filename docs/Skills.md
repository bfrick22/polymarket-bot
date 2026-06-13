# Bot Skills

Capabilities of the Polymarket bot and the modules that implement them.

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
- Emits both BUY and SELL trades (the copy module decides handling)
- Can also fetch the target's current open positions

**Rate limit:** 200 req/10s (well within the 10s poll interval)

---

## Position Sizing (`src/trader.py → scale_size`)

Converts the target's trade into a proportional position using a tiered ratio system:

- **Small trades** (target USD ≤ `MAX_TRADE_USD`): use `COPY_RATIO_SMALL` for a meaningful copy position
- **Large trades** (target USD > `MAX_TRADE_USD`): use `COPY_RATIO`, always capped at `MAX_TRADE_USD`

Converts between USD and shares using the trade price.

---

## BUY Mirroring (`src/trader.py → _mirror_buy`)

Takes a BUY trade from the watcher and places a scaled BUY on the CLOB:

1. Scales size via `scale_size`
2. Skips if below `MIN_SHARES` or below `MIN_POSITION_USD`
3. Queries our current position on the token; if we're already at `MAX_EXPOSURE_PER_MARKET_USD`, the BUY is skipped. If there's partial room, the BUY is trimmed to fit
4. Submits the order via `create_and_post_order`
5. Logs every decision (skip reasons included); errors are caught and the bot continues

---

## SELL Mirroring (`src/trader.py → _mirror_sell`)

Takes a SELL trade from the watcher and places a proportional SELL on the CLOB:

1. Returns immediately if `MIRROR_SELLS=false`
2. Queries our current position on the token; skips if none held
3. Computes proportional close: if target sold fraction *f* of their initial position, we sell *f* × our holdings
4. Enforces `MIN_SHARES` (rounds up to min if we have enough; otherwise skips)
5. Submits SELL order via `create_and_post_order`

Without this, the bot accumulated positions indefinitely and held losers to resolution.

---

## Ultra-Short Crypto Scanner (`src/crypto_5m.py`) — Phase 3

Scans Polymarket's rolling 5-minute BTC/XRP up-or-down markets and fires on two independent inefficiency signals:

- **Binance latency (Signal A):** spot moves > `CRYPTO_5M_IMPULSE_BPS` over the trailing `CRYPTO_5M_IMPULSE_WINDOW_SEC` AND the Polymarket Up mid is still within the neutral band. Fires the direction Binance moved.
- **Spread floor (Signal B):** `up_ask + down_ask < CRYPTO_5M_SPREAD_THRESHOLD`. Fires BOTH YES legs — guaranteed profit at resolution since the outcomes are mutually exclusive.

Subcomponents:

- `PriceFeed` — bounded ring buffer per asset; `delta_bps(window)` returns trailing change in basis points.
- `BinanceStream` — daemon thread per asset, subscribes to Binance's public `<symbol>@aggTrade` WebSocket. No Binance account / API key required (public market data is open). Auto-reconnects on disconnect.
- `Crypto5mScanner` — discovers active 5m markets via Gamma `/markets?order=createdAt`, refreshes every 30s, evaluates both signals per market on each tick.

Sizing: `max(CRYPTO_5M_MAX_TRADE_USD / price, MIN_SHARES)`. Floor enforces Polymarket's 5-share exchange minimum.

Each filled market's slug is tracked in `fired_slugs` to prevent double-fire; the set self-cleans as markets expire.

This is uncorrelated with Phase 2: Phase 2 needs 3+ outcomes & `negRisk=True`, while the up/down markets are 2-outcome binaries (`negRisk=False` on the event) so Phase 2 never touches them.

---

## Multi-Outcome Arbitrage Scanner (`src/arbitrage.py`)

Scans the Gamma `/events` endpoint for events with mutually-exclusive YES outcomes. When the sum of YES prices across a basket is below `ARB_THRESHOLD`, the scanner buys equal-share quantities of every YES leg — a mechanical guaranteed profit at resolution because exactly one outcome resolves YES.

- Pulls top 100 active events by 24h volume
- Filters by leg count (`ARB_MIN_OUTCOMES`…`ARB_MAX_OUTCOMES`) to keep baskets mutually exclusive and per-leg size above the share minimum
- Computes basket size `K = ARB_MAX_BASKET_USD / sum_yes`; required so the basket fits the cap while each leg meets `MIN_SHARES`
- Tracks `filled_event_ids` to avoid double-buying the same basket on subsequent scans
- Logs all opportunities (with edge %, leg count, cost, guaranteed payout)
- Partial fills are logged as `ARB PARTIAL` — degrades but rarely inverts guarantee

This is a category-agnostic positive-EV stream that does not require predicting any outcome.

---

## Main Loop (`src/main.py`)

Orchestrates all skills in sequence:

1. Geoblock check (exit if blocked)
2. Authenticate and create trading client
3. Initialise one `TraderWatcher` per entry in `traders.json` and seed seen trades
4. Initialise `ArbitrageScanner` if `ARB_ENABLED=true`
5. Initialise `Crypto5mScanner` if `CRYPTO_5M_ENABLED=true` (also starts one Binance WebSocket thread per asset)
6. Poll every `POLL_INTERVAL_SEC`:
   - For each watcher: fetch new trades, copy via `CopyTrader`
   - If `ARB_POLL_INTERVAL_SEC` has elapsed since last scan: run `arb_scanner.scan_and_fire()`
   - If `CRYPTO_5M_POLL_INTERVAL_SEC` has elapsed since last tick: run `crypto_5m.scan_and_fire()`

The three cadences are independent: trader copying default 10s, arb scanning 60s, crypto 5m scanner 5s.

Recovers from unexpected errors without crashing — logs and continues.

---

## Trader Roster (`src/traders.json`)

Current copy targets (rationale documented in `docs/Strategy.md`):

- `coldmath` — +$95k lifetime net; large average trade ($269); mix of cheap longshots and near-certain plays
- `Hans323` — modest +$792 net but **actively sells** (21% sell rate), which is exactly the behavior we now mirror

Removed: `neobrother` (was running negative -$507; pure weather longshots).

The roster should be re-evaluated periodically against 30d realized PnL. A scout script is planned for Phase 4 of the strategy plan.

---

## AWS Deployment (`terraform/`)

ECS Fargate service in `eu-west-1` managed by Terraform. Secrets are injected by the ECS agent at task launch — no application-side secret fetching needed.

### Secret Loading

All `.env` variables are stored as a single JSON object in AWS Secrets Manager (`polymarket-bot/config`). The ECS task definition maps each JSON key to a container environment variable using the native `secrets` injection mechanism. Secrets are available as normal `os.environ` values when `main.py` starts.

Populate the secret from your local `.env` file using the one-liner in the `deploy_commands` Terraform output. **Note:** when adding new config variables (e.g. arb scanner settings), include them in the JSON pushed to Secrets Manager and force a service redeploy.

### Infrastructure (`terraform/`)

| File | Purpose |
|---|---|
| `main.tf` | Provider, default VPC data sources |
| `variables.tf` | `aws_region`, `app_name`, `image_tag` |
| `ecr.tf` | ECR repository with lifecycle policy (keep last 3 images) |
| `secretsmanager.tf` | Secrets Manager secret for all `.env` variables |
| `iam.tf` | Execution role (ECR pull, CloudWatch, SM read) + Task role (no extra perms) |
| `cloudwatch.tf` | Log group with 7-day retention |
| `ecs.tf` | Cluster, task definition (256 CPU / 512 MB), service (1 task) |
| `outputs.tf` | ECR URL, SM ARN, deploy commands |

**Cost profile:** ~$10–13/mo (0.25 vCPU Fargate + ECR + CloudWatch). Uses default VPC with `assign_public_ip = true` to avoid NAT gateway costs.

### CLI User Policy (`iam/cli-policy.json`)

Least-privilege IAM policy for the human/CI user that runs `terraform apply` and deploys images. Scoped to `polymarket-bot-*` resources and `eu-west-1` only. Replace `ACCOUNT_ID` before attaching.

```bash
aws iam create-user --user-name polymarket-bot-deployer
aws iam put-user-policy --user-name polymarket-bot-deployer \
  --policy-name polymarket-bot-deploy \
  --policy-document file://iam/cli-policy.json
aws iam create-access-key --user-name polymarket-bot-deployer
```
