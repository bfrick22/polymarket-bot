# Polymarket Copy Trading Bot

Automatically mirrors trades from one or more Polymarket traders at a scaled-down size. Polls the public Polymarket Data API for new trades every 10 seconds and places proportional orders through the CLOB using your authenticated wallet.

---

## How It Works

### 1. Geoblock Gate

On startup the bot calls `https://polymarket.com/api/geoblock` to verify trading is allowed from the current IP. If the check fails (US IPs are blocked), the bot exits immediately — no trades are ever placed from a restricted region. **This is why the bot must run from an Ireland IP, either via AWS eu-west-1 or a VPN.**

### 2. Authentication

`src/auth.py` derives L2 API credentials from your Polygon wallet private key using the Polymarket CLOB client. The derivation is deterministic — the same private key always produces the same API key, so credentials don't need to be stored separately. Two clients are built:

- **L1 client** — creates or derives the API credentials using your private key
- **L2 client** — the trading-capable client, used for all order placement

> **Signature type:** The bot uses `signature_type=1` (POLY_PROXY), which is correct for accounts created via email or Google login on polymarket.com. If you created your account by connecting a wallet directly, change this to `signature_type=2` (GNOSIS_SAFE) in `src/auth.py`.

### 3. Trade Watching

`src/watcher.py` polls `https://data-api.polymarket.com/trades?user=<address>` for each configured trader. The endpoint is public — no authentication required. On startup it seeds a `seen_trade_ids` set from the current recent trade history so historical trades are never replayed. On each poll cycle, only trades with a new `transactionHash` are returned as actionable.

### 4. Market Keyword Filter

Before copying, the trade's market title is checked against `MARKET_KEYWORDS`. Only markets whose title contains at least one keyword are copied. This lets you focus on specific market categories (e.g. weather events) and ignore everything else. Set `MARKET_KEYWORDS=""` to copy all markets.

Default keywords: `weather, temperature, rain, snow, hurricane, tornado, precipitation, degrees, wind, flood, frost, hail, blizzard, drought`

### 5. Position Sizing

`src/trader.py` uses a tiered ratio to scale the target's trade into your position:

| Target trade size | Ratio used | Cap |
|---|---|---|
| ≤ `MAX_TRADE_USD` (small) | `COPY_RATIO_SMALL` (default 35%) | `MAX_TRADE_USD` |
| > `MAX_TRADE_USD` (large) | `COPY_RATIO` (default 10%) | `MAX_TRADE_USD` |

Small trades get a higher ratio so your copy position stays meaningful. Large trades are capped at `MAX_TRADE_USD` regardless of ratio.

**Example:**
- Target buys $8 worth → small → you buy $2.80 (35%)
- Target buys $300 worth → large → you buy $20 (capped at MAX_TRADE_USD)

Trades where the scaled position is under $1 USD are skipped — that's Polymarket's effective minimum.

### 6. Trade Copying

For each new trade that passes the keyword filter and sizing minimum, an `OrderArgs` object is built and submitted via `client.create_and_post_order()`. Errors are caught, logged, and skipped — the bot never crashes on a failed order and continues polling.

### 7. Multi-Trader Support

`src/traders.json` lists all traders to watch. The bot creates one `TraderWatcher` per entry and processes new trades from all of them on each poll cycle. Edit this file to add, remove, or swap traders.

```json
[
  { "name": "coldmath",   "address": "0x594edb9112f526fa6a80b8f858a6379c8a2c1c11" },
  { "name": "Hans323",    "address": "0x0f37cb80dee49d55b5f6d9e595d52591d6371410" },
  { "name": "neobrother", "address": "0x6297b93ea37ff92a57fd636410f3b71ebf74517e" }
]
```

---

## Configuration Reference

All settings are read from environment variables (or `.env` for local runs).

| Variable | Default | Description |
|---|---|---|
| `PRIVATE_KEY` | — | Your Polygon wallet private key (`0x...`) |
| `POLY_ADDRESS` | — | Your proxy wallet address from polymarket.com/settings |
| `COPY_RATIO` | `0.10` | Copy ratio for large trades (target > MAX_TRADE_USD) |
| `COPY_RATIO_SMALL` | `0.35` | Copy ratio for small trades (target ≤ MAX_TRADE_USD) |
| `MAX_TRADE_USD` | `50` | Hard cap per copied trade in USD |
| `POLL_INTERVAL_SEC` | `10` | Seconds between trade checks |
| `RECENT_TRADES_LIMIT` | `40` | Trades fetched per poll cycle |
| `MARKET_KEYWORDS` | *(weather terms)* | Comma-separated market title keywords to copy; empty = all |

---

## Local Development

### Prerequisites

- Python 3.12+
- A Polymarket account with a funded proxy wallet
- Polygon wallet private key

### Setup

```bash
# Install dependencies
pip install -r requirements.txt

# Copy and fill in the env file
cp .env.example .env
# Edit .env with your PRIVATE_KEY, POLY_ADDRESS, and wallet address
```

### Find a Trader to Copy

```bash
# Look up a trader's wallet address by username
python scripts/lookup_trader.py coldmath
```

Edit `src/traders.json` to configure which traders the bot watches.

### Dry Run

Preview what the bot would copy from the most recent trade without placing any orders:

```bash
python scripts/dry_run.py
```

### Run

```bash
python src/main.py
```

---

## Running with Docker Locally

### Region Requirement

Polymarket blocks trading from US IPs. The geoblock check runs on startup and will exit the bot if your IP is blocked. **When running Docker locally from the US, you must connect to a VPN with a non-blocked exit node before starting the container.**

Recommended VPN exit locations: Ireland, UK, Germany, Netherlands, or any EU country.

Verify your IP is unblocked before running:

```bash
curl -s https://polymarket.com/api/geoblock | python3 -m json.tool
# "blocked": false  ← required
```

### Build and Run

```bash
# Build the image
docker build -t polymarket-bot .

# Run with your .env file mounted
docker run --rm --env-file .env polymarket-bot
```

> **Apple Silicon:** Add `--platform linux/amd64` to the build command when targeting AWS deployment. For local-only runs the platform doesn't matter.

---

## AWS Deployment (Terraform)

The bot runs as an ECS Fargate service in `eu-west-1` (Ireland) — the AWS region itself satisfies the geoblock requirement, no VPN needed.

### Architecture

```
ECR Repository          → stores Docker image
Secrets Manager         → holds all .env vars as a JSON object
ECS Cluster (Fargate)   → runs 1 task, 256 CPU / 512 MB RAM
CloudWatch Logs         → 7-day retention, /ecs/polymarket-bot
IAM (execution role)    → pulls ECR image, reads Secrets Manager, writes logs
IAM (task role)         → no extra permissions (app makes only outbound API calls)
Default VPC             → public subnet + assign_public_ip avoids NAT gateway cost
```

**Estimated cost: ~$10–13/month** (Fargate + ECR storage + CloudWatch)

### Prerequisites

- [Terraform](https://developer.hashicorp.com/terraform/install) >= 1.6
- AWS CLI configured: `aws configure`
- Docker

### Step 1 — Create the Deployer IAM User

Create a least-privilege IAM user for Terraform and deployments. First replace the `ACCOUNT_ID` placeholder in the policy file:

```bash
# Find your account ID
aws sts get-caller-identity --query Account --output text

# Replace the placeholder (macOS)
sed -i '' 's/ACCOUNT_ID/YOUR_12_DIGIT_ACCOUNT_ID/g' iam/cli-policy.json

# Create the user and attach the policy
aws iam create-user --user-name polymarket-bot-deployer
aws iam put-user-policy \
  --user-name polymarket-bot-deployer \
  --policy-name polymarket-bot-deploy \
  --policy-document file://iam/cli-policy.json

# Create access keys and configure a named profile
aws iam create-access-key --user-name polymarket-bot-deployer
aws configure --profile polymarket-bot
```

Use the profile for all subsequent commands by prepending `AWS_PROFILE=polymarket-bot` or passing `--profile polymarket-bot`.

### Step 2 — Apply Terraform

```bash
cd terraform

terraform init
terraform plan
terraform apply
```

Terraform creates: ECR repo, Secrets Manager secret (empty shell), ECS cluster, task definition, service, IAM roles, CloudWatch log group, and security group.

After apply, note the outputs:

```bash
terraform output ecr_repository_url
terraform output secrets_manager_arn
```

### Step 3 — Populate Secrets

Upload your `.env` file to Secrets Manager as a JSON object. The one-liner in the Terraform output does this automatically:

```bash
terraform output -raw deploy_commands
# Copy and run the "Step 1" command shown — it reads .env and uploads to SM
```

Or manually:

```bash
aws secretsmanager put-secret-value \
  --secret-id polymarket-bot/config \
  --region eu-west-1 \
  --secret-string '{
    "PRIVATE_KEY":        "0xYOUR_KEY",
    "POLY_ADDRESS":       "0xYOUR_PROXY",
    "COPY_RATIO":         "0.10",
    "COPY_RATIO_SMALL":   "0.35",
    "MAX_TRADE_USD":      "50",
    "POLL_INTERVAL_SEC":  "10",
    "RECENT_TRADES_LIMIT":"40",
    "MARKET_KEYWORDS":    "weather,temperature,rain"
  }'
```

### Step 4 — Build and Push Docker Image

```bash
ECR_URL=$(terraform output -raw ecr_repository_url)

# Authenticate Docker to ECR
aws ecr get-login-password --region eu-west-1 | \
  docker login --username AWS --password-stdin "$ECR_URL"

# Build (--platform required on Apple Silicon)
docker build --platform linux/amd64 -t "$ECR_URL:latest" .
docker push "$ECR_URL:latest"
```

### Step 5 — Verify

The ECS service starts automatically after apply. Once the image is pushed, force a fresh task to pick up the latest image and secrets:

```bash
aws ecs update-service \
  --cluster polymarket-bot \
  --service polymarket-bot \
  --force-new-deployment \
  --region eu-west-1
```

**View logs:**

```bash
aws logs tail /ecs/polymarket-bot --follow --region eu-west-1
```

Expected startup output:
```
=== Polymarket Copy Trading Bot Starting ===
Geoblock check passed: IE/Leinster
Authenticating with Polymarket CLOB...
Got API key: xxxxxxxx...
Seeded 40 existing trades — watching for new ones
Watching 3 trader(s), polling every 10s...
```

### Updating the Bot

After code changes:

```bash
docker build --platform linux/amd64 -t "$ECR_URL:latest" .
docker push "$ECR_URL:latest"
aws ecs update-service --cluster polymarket-bot --service polymarket-bot \
  --force-new-deployment --region eu-west-1
```

To update config (e.g. change `MAX_TRADE_USD`), update the secret and force redeploy:

```bash
aws secretsmanager put-secret-value \
  --secret-id polymarket-bot/config \
  --region eu-west-1 \
  --secret-string '{ ...updated JSON... }'

aws ecs update-service --cluster polymarket-bot --service polymarket-bot \
  --force-new-deployment --region eu-west-1
```

### Teardown

```bash
cd terraform
terraform destroy
```

> **Note:** Secrets Manager has a 30-day recovery window by default. The Terraform config sets `recovery_window_in_days = 0` so the secret is deleted immediately on destroy.
