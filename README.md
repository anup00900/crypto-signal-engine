# Crypto Signal Engine

Real-time BTC/ETH signal computation running on AWS Lambda, with an MCP server exposing 53 tools for Claude Code and other MCP-compatible clients.

## What It Does

- **Collects** Binance Futures data every minute (candles, funding, OI, long/short ratios)
- **Computes** 7 proprietary signals weighted into a Trade Decision Score (TDS)
- **Stores** rolling buffers + daily archives in S3 (Parquet + JSON)
- **Exposes** everything through 53 MCP tools for AI-assisted trading analysis

## Architecture

```
Binance Futures API
        |
   [EventBridge: 1 min]
        |
   [Signal Engine Lambda]
        |
   [S3 Bucket: eu-north-1]
        |
   [MCP Server (stdio)]
        |
   Claude Code / Claude Desktop / Cursor / Any MCP Client
```

## Signal Engine

7 signals are computed every minute and combined into a weighted **TDS (Trade Decision Score)**:

| Signal | Weight | Description |
|--------|--------|-------------|
| VEP | 15% | Volume Expansion Percentile — volume vs rolling 120-bar baseline |
| SCI | 15% | Spread Compression Index — volatility squeeze detection |
| LCS | 15% | Liquidation Cascade Score — funding + OI stress |
| FLOW | 20% | Order Flow Imbalance — delta + taker aggression |
| DPS | 10% | Delta-Price Skew — price vs delta divergence |
| GRAV | 10% | Volume Gravity — distance from volume profile POC |
| CAP | 15% | Cross-Asset Pressure — BTC/ETH correlation signal |

**Entry logic:** TDS >= 75, FLOW >= 50, CAP >= 45

## Quick Start (For You)

### 1. Clone

```bash
git clone https://github.com/anup00900/crypto-signal-engine.git
cd crypto-signal-engine
```

### 2. Install Dependencies

```bash
pip install mcp boto3 pandas pyarrow loguru
```

### 3. Configure AWS

```bash
aws configure
# AWS Access Key ID: <your key>
# AWS Secret Access Key: <your secret>
# Default region: eu-north-1
# Output format: json
```

### 4. Add MCP Server to Claude Code

Create `.mcp.json` in the project root:

```json
{
  "mcpServers": {
    "crypto-signals": {
      "command": "python3",
      "args": ["mcp_server/signal_server.py"],
      "cwd": "/path/to/crypto-signal-engine",
      "env": {
        "S3_BUCKET": "crypto-collector-prod-data-720428162886",
        "AWS_REGION": "eu-north-1"
      }
    }
  }
}
```

### 5. Use It

Open Claude Code in the project directory and ask:

```
"Get me the latest crypto signals"
"Show BTC volume profile"
"What's the current positioning summary?"
"Show me the last 20 candles for ETHUSDT"
```

---

## Setup for Other Users (Any Country)

Since the data lives on AWS S3, anyone worldwide can connect. Here's how to give someone access.

### Step 1: Create IAM Credentials (Admin Does This)

```bash
# Create a read-only user
aws iam create-user --user-name signal-reader-<name>

# Attach read-only policy for signals
aws iam put-user-policy --user-name signal-reader-<name> \
  --policy-name S3SignalReadOnly \
  --policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:ListBucket"],
      "Resource": [
        "arn:aws:s3:::crypto-collector-prod-data-720428162886",
        "arn:aws:s3:::crypto-collector-prod-data-720428162886/signals/*",
        "arn:aws:s3:::crypto-collector-prod-data-720428162886/data/*"
      ]
    }]
  }'

# Generate access keys
aws iam create-access-key --user-name signal-reader-<name>
```

Send them the `AccessKeyId` and `SecretAccessKey`.

### Step 2: User Setup (They Do This)

```bash
# 1. Clone the repo
git clone https://github.com/anup00900/crypto-signal-engine.git
cd crypto-signal-engine

# 2. Install Python dependencies
pip install mcp boto3 pandas pyarrow loguru

# 3. Configure AWS credentials
aws configure
# AWS Access Key ID: <key from admin>
# AWS Secret Access Key: <secret from admin>
# Default region: eu-north-1
# Output format: json
```

### Step 3: Connect to an MCP Client

#### Claude Code (CLI)

Create `.mcp.json` in the project root:

```json
{
  "mcpServers": {
    "crypto-signals": {
      "command": "python3",
      "args": ["mcp_server/signal_server.py"],
      "cwd": "/absolute/path/to/crypto-signal-engine",
      "env": {
        "S3_BUCKET": "crypto-collector-prod-data-720428162886",
        "AWS_REGION": "eu-north-1"
      }
    }
  }
}
```

#### Claude Desktop

Go to **Settings > Developer > MCP Servers** and add:

```json
{
  "crypto-signals": {
    "command": "python3",
    "args": ["/absolute/path/to/crypto-signal-engine/mcp_server/signal_server.py"],
    "env": {
      "S3_BUCKET": "crypto-collector-prod-data-720428162886",
      "AWS_REGION": "eu-north-1"
    }
  }
}
```

#### Cursor / Windsurf / Continue.dev

Add to your editor's MCP configuration:

```json
{
  "command": "python3",
  "args": ["/absolute/path/to/crypto-signal-engine/mcp_server/signal_server.py"],
  "transport": "stdio",
  "env": {
    "S3_BUCKET": "crypto-collector-prod-data-720428162886",
    "AWS_REGION": "eu-north-1"
  }
}
```

### Step 4: Verify

Ask your MCP client:

```
"Get the latest crypto signals for BTC"
```

If you get signal data back, you're connected.

---

## MCP Tools Reference (53 Tools)

| Category | Tools | Description |
|----------|-------|-------------|
| **Signals** | `get_crypto_signals`, `get_crypto_signal` | Latest TDS, entry/exit, direction, TP/invalidation |
| **All Scores** | `get_all_scores`, `get_score_history` | All 7 signal scores at once, historical tracking |
| **VEP** | `get_vep`, `get_vep_detail` | Volume Expansion Percentile |
| **SCI** | `get_sci`, `get_sci_detail` | Spread Compression + direction |
| **LCS** | `get_lcs`, `get_lcs_detail` | Liquidation Cascade Score |
| **FLOW** | `get_flow`, `get_flow_detail` | Order Flow Imbalance |
| **DPS** | `get_dps`, `get_dps_detail` | Delta-Price Skew |
| **GRAV** | `get_grav`, `get_grav_detail` | Volume Gravity |
| **CAP** | `get_cap`, `get_cap_detail` | Cross-Asset Pressure |
| **Volume Profile** | `get_volume_profile`, `get_multi_timeframe_profile` | POC, HVN, LVN, VAH, VAL |
| **Candles** | `get_latest_candles`, `get_candle_history`, `list_archive_dates` | OHLCV + delta + VWAP |
| **Derivatives** | `get_funding_rate`, `get_open_interest`, `get_mark_index_spread`, `get_derivatives_snapshot`, `get_derivatives_history`, `list_derivatives_archive_dates` | Funding, OI, mark/index prices |
| **Derived Features** | `get_derived_features` | range_5m, vol_5m, delta_5m, velocity, body_efficiency |
| **Positioning** | `get_long_short_ratio`, `get_positioning_summary` | Crowd + whale + taker positioning |
| **Deribit** | `get_options_surface`, `get_orderbook_snapshot`, `get_deribit_open_interest`, `list_deribit_data` | Options IV surface, orderbook depth |
| **Trade Journal** | `log_trade`, `close_trade`, `get_trades`, `get_trade_performance` | Track trades with signal state + PnL |
| **System** | `get_signal_config`, `get_system_status`, `get_entry_logic`, `get_signal_weights` | Configuration and health |

## AWS Infrastructure

| Resource | Details |
|----------|---------|
| **Signal Lambda** | `crypto-collector-prod-signal-engine`, 256MB, 30s timeout, Python 3.11 |
| **Trigger** | EventBridge rule, every 1 minute |
| **S3 Bucket** | `crypto-collector-prod-data-720428162886` (eu-north-1) |
| **Logs** | CloudWatch `/aws/lambda/crypto-collector-prod-signal-engine` |
| **Alarm** | CloudWatch alarm on Lambda errors |

### S3 Data Structure

```
signals/
  signals_latest.json          # Current signals (updated every minute)
  volume_profile.json          # POC/HVN/LVN (updated every 5 min)
  candles_1m_rolling.parquet   # Rolling 1500-candle buffer per symbol
  derivatives_rolling.parquet  # Rolling derivatives buffer
  liquidations_rolling.parquet # Rolling long/short ratio buffer
  archive/
    candles_1m/2026-02-18.parquet       # Daily candle archive
    derivatives_1m/2026-02-18.parquet   # Daily derivatives archive
    signals_1m/2026-02-18.parquet       # Daily signal archive
```

### Estimated Costs

| Component | Monthly Cost |
|-----------|-------------|
| Signal Lambda (1/min) | ~$2-4 |
| S3 Storage | ~$0.50 |
| CloudWatch Logs | ~$1-2 |
| Data Transfer | ~$0.50 |
| **Total** | **$4-7/month** |

## Binance API Endpoints Used

All public endpoints, no API key required:

| Endpoint | Data | Frequency |
|----------|------|-----------|
| `GET /fapi/v1/klines` | 1m candles (OHLCV + delta + VWAP) | Every 1 min |
| `GET /fapi/v1/premiumIndex` | Mark price, index price, funding rate | Every 1 min |
| `GET /fapi/v1/openInterest` | Open interest | Every 1 min |
| `GET /futures/data/takerlongshortRatio` | Taker buy/sell ratio | Every 1 min |
| `GET /futures/data/globalLongShortAccountRatio` | Crowd positioning | Every 1 min |
| `GET /futures/data/topLongShortPositionRatio` | Whale positioning | Every 1 min |

## Local Development

### Data Collection (PostgreSQL)

```bash
# Start PostgreSQL
cd docker && docker-compose up -d

# Setup database
python scripts/setup_database.py

# Run initial data load
python scripts/initial_load.py --instruments BTC-PERPETUAL --timeframes 1d,1h

# Validate data
python scripts/validate_data.py
```

### Deploy Lambda

```bash
cd aws
bash deploy.sh    # Packages code + runs terraform apply
```

### Test Signal Engine Locally

```bash
python -c "
from aws.signal_lambda.handler import lambda_handler
import json
result = lambda_handler({'source': 'local-test'}, None)
print(json.dumps(json.loads(result['body']), indent=2))
"
```

## Project Structure

```
crypto-signal-engine/
├── aws/
│   ├── signal_lambda/         # Signal engine (runs every 1 min)
│   │   ├── handler.py         # Lambda entry point
│   │   ├── signal_engine.py   # 7 signals + TDS computation
│   │   ├── binance_fetcher.py # Binance Futures REST API
│   │   ├── candle_store.py    # S3 rolling buffer management
│   │   └── config.py          # Signal weights, thresholds
│   ├── terraform/             # Infrastructure as code
│   │   ├── main.tf            # Deribit collector Lambda
│   │   └── signal_lambda.tf   # Signal engine Lambda + EventBridge
│   ├── collector.py           # Deribit data collector
│   ├── s3_storage.py          # S3 read/write utilities
│   ├── lambda_handler.py      # Deribit Lambda entry point
│   └── deploy.sh              # Build + deploy script
├── mcp_server/
│   └── signal_server.py       # MCP stdio server (53 tools)
├── collectors/                # Exchange API clients
│   ├── binance/
│   ├── deribit/
│   └── coingecko/
├── config/                    # Configuration
├── database/                  # PostgreSQL schema + models
├── processors/                # Data validation + aggregation
├── storage/                   # Local data storage handlers
├── scripts/                   # Utility scripts
├── tests/                     # Unit tests
└── docker/                    # Docker configuration
```

## License

MIT
