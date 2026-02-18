# Crypto Data Access Guide

This guide explains how to retrieve cryptocurrency market data from our AWS S3 bucket.

---

## Data Overview

| Data Type | Format | Update Frequency | Description |
|-----------|--------|------------------|-------------|
| OHLCV | CSV | Every 15 min | Price candles (Open, High, Low, Close, Volume) |
| Funding Rates | CSV | Every 15 min | Perpetual futures funding rates |
| Options Greeks | Parquet | Every 15 min | Delta, Gamma, Theta, Vega for all options |
| Order Book | Parquet | Every 15 min | Best bid/ask, spread, depth snapshots |
| Open Interest | Parquet | Every 15 min | Futures and options open interest |

---

## S3 Bucket Details

- Bucket Name: `crypto-collector-prod-data-720428162886`
- Region: `eu-north-1`
- Access: Requires AWS credentials with S3 read permissions

---

## File Structure

```
s3://crypto-collector-prod-data-720428162886/data/

CSV Files (Time-series, append mode):
------------------------------------
funding_BTC.csv                    BTC perpetual funding rate history
funding_ETH.csv                    ETH perpetual funding rate history

ohlcv_BTC_5.csv                    BTC 5-minute candles
ohlcv_BTC_60.csv                   BTC 1-hour candles
ohlcv_BTC_240.csv                  BTC 4-hour candles (using 3h from Deribit)

ohlcv_ETH_5.csv                    ETH 5-minute candles
ohlcv_ETH_60.csv                   ETH 1-hour candles
ohlcv_ETH_240.csv                  ETH 4-hour candles (using 3h from Deribit)


Parquet Files (Snapshots, daily partitions, append mode):
---------------------------------------------------------
options_greeks/
    BTC/
        2026-01-27.parquet         BTC options with Greeks for Jan 27
        2026-01-28.parquet         BTC options with Greeks for Jan 28
        ...
    ETH/
        2026-01-27.parquet         ETH options with Greeks for Jan 27
        2026-01-28.parquet         ETH options with Greeks for Jan 28
        ...

orderbook/
    2026-01-27.parquet             Order book snapshots for Jan 27
    2026-01-28.parquet             Order book snapshots for Jan 28
    ...

open_interest/
    2026-01-27.parquet             Open interest snapshots for Jan 27
    2026-01-28.parquet             Open interest snapshots for Jan 28
    ...
```

---

## Data Update Behavior

| Data Type | Storage | Behavior |
|-----------|---------|----------|
| OHLCV | CSV | New candles appended, duplicates removed |
| Funding | CSV | New rates appended, duplicates removed |
| Options Greeks | Parquet | Each 15-min snapshot appended to daily file |
| Order Book | Parquet | Each 15-min snapshot appended to daily file |
| Open Interest | Parquet | Each 15-min snapshot appended to daily file |

Parquet files contain approximately 96 snapshots per day (4 per hour x 24 hours).

---

## Python Access

### Prerequisites

```bash
pip install boto3 pandas pyarrow
```

### Configure AWS Credentials

```bash
aws configure
```

Enter the following when prompted:
- AWS Access Key ID
- AWS Secret Access Key
- Default region: eu-north-1
- Default output format: json

### Read CSV Files (OHLCV, Funding)

```python
import boto3
import pandas as pd
from io import BytesIO

s3 = boto3.client('s3', region_name='eu-north-1')
BUCKET = 'crypto-collector-prod-data-720428162886'

def read_csv_from_s3(key):
    """Read CSV file from S3 and return DataFrame"""
    response = s3.get_object(Bucket=BUCKET, Key=key)
    return pd.read_csv(BytesIO(response['Body'].read()))

# Example: Get BTC 1-hour OHLCV data
btc_ohlcv = read_csv_from_s3('data/ohlcv_BTC_60.csv')
print(btc_ohlcv.head())

# Example: Get BTC funding rates
btc_funding = read_csv_from_s3('data/funding_BTC.csv')
print(btc_funding.tail())
```

### Read Parquet Files (Options Greeks, Order Book, Open Interest)

```python
def read_parquet_from_s3(key):
    """Read Parquet file from S3 and return DataFrame"""
    response = s3.get_object(Bucket=BUCKET, Key=key)
    return pd.read_parquet(BytesIO(response['Body'].read()))

# Example: Get BTC options Greeks for specific date
btc_greeks = read_parquet_from_s3('data/options_greeks/BTC/2026-01-27.parquet')
print(btc_greeks.head())

# Example: Get order book snapshots for specific date
orderbook = read_parquet_from_s3('data/orderbook/2026-01-27.parquet')
print(orderbook.head())

# Example: Get open interest for specific date
oi = read_parquet_from_s3('data/open_interest/2026-01-27.parquet')
print(oi.head())
```

### List Available Files

```python
def list_files(prefix='data/'):
    """List all files in bucket with given prefix"""
    response = s3.list_objects_v2(Bucket=BUCKET, Prefix=prefix)
    files = []
    for obj in response.get('Contents', []):
        files.append({
            'key': obj['Key'],
            'size_mb': round(obj['Size'] / (1024 * 1024), 2),
            'last_modified': obj['LastModified']
        })
    return pd.DataFrame(files)

# List all files
all_files = list_files()
print(all_files)

# List only options Greeks files
greeks_files = list_files('data/options_greeks/')
print(greeks_files)
```

### Read Multiple Days of Parquet Data

```python
from datetime import datetime, timedelta

def read_date_range(data_type, currency, start_date, end_date):
    """
    Read Parquet files for a date range and combine into single DataFrame
    
    Parameters:
        data_type: 'options_greeks', 'orderbook', or 'open_interest'
        currency: 'BTC' or 'ETH' (only required for options_greeks)
        start_date: 'YYYY-MM-DD' format
        end_date: 'YYYY-MM-DD' format
    
    Returns:
        Combined DataFrame with all data in date range
    """
    all_data = []
    
    start = datetime.strptime(start_date, '%Y-%m-%d')
    end = datetime.strptime(end_date, '%Y-%m-%d')
    
    current = start
    while current <= end:
        date_str = current.strftime('%Y-%m-%d')
        
        if data_type == 'options_greeks':
            key = f'data/{data_type}/{currency}/{date_str}.parquet'
        else:
            key = f'data/{data_type}/{date_str}.parquet'
        
        try:
            df = read_parquet_from_s3(key)
            all_data.append(df)
            print(f'Loaded {key} ({len(df)} rows)')
        except Exception as e:
            print(f'Missing {key}')
        
        current += timedelta(days=1)
    
    if all_data:
        return pd.concat(all_data, ignore_index=True)
    return pd.DataFrame()

# Example: Get 7 days of BTC options Greeks
btc_greeks_week = read_date_range(
    data_type='options_greeks',
    currency='BTC',
    start_date='2026-01-20',
    end_date='2026-01-27'
)
print(f'Total rows: {len(btc_greeks_week)}')
```

---

## AWS CLI Access

### List Files

```bash
# List all data files
aws s3 ls s3://crypto-collector-prod-data-720428162886/data/ --recursive

# List only options Greeks files
aws s3 ls s3://crypto-collector-prod-data-720428162886/data/options_greeks/ --recursive

# List only orderbook files
aws s3 ls s3://crypto-collector-prod-data-720428162886/data/orderbook/ --recursive
```

### Download Files

```bash
# Download single CSV file
aws s3 cp s3://crypto-collector-prod-data-720428162886/data/ohlcv_BTC_60.csv ./

# Download single Parquet file
aws s3 cp s3://crypto-collector-prod-data-720428162886/data/options_greeks/BTC/2026-01-27.parquet ./

# Download all OHLCV files
aws s3 cp s3://crypto-collector-prod-data-720428162886/data/ ./ --recursive --exclude "*" --include "ohlcv_*.csv"

# Download entire options_greeks folder
aws s3 cp s3://crypto-collector-prod-data-720428162886/data/options_greeks/ ./options_greeks/ --recursive

# Download entire data folder
aws s3 cp s3://crypto-collector-prod-data-720428162886/data/ ./data/ --recursive

# Sync (only download new or changed files)
aws s3 sync s3://crypto-collector-prod-data-720428162886/data/ ./local_data/
```

---

## Data Schemas

### OHLCV (CSV)

| Column | Type | Description |
|--------|------|-------------|
| timestamp | string | Candle timestamp in ISO 8601 format |
| instrument | string | Instrument name (e.g., BTC-PERPETUAL) |
| timeframe | string | Timeframe in minutes (5, 60, 240) |
| open | float | Opening price in USD |
| high | float | Highest price in USD |
| low | float | Lowest price in USD |
| close | float | Closing price in USD |
| volume | float | Trading volume |

Example row:
```
timestamp,instrument,timeframe,open,high,low,close,volume
2026-01-27T12:00:00,BTC-PERPETUAL,60,101250.5,101500.0,101100.0,101350.0,1250.5
```

### Funding Rates (CSV)

| Column | Type | Description |
|--------|------|-------------|
| timestamp | string | Funding timestamp in ISO 8601 format |
| instrument | string | Instrument name (e.g., BTC-PERPETUAL) |
| funding_8h | float | 8-hour funding rate (decimal, e.g., 0.0001 = 0.01%) |
| index_price | float | Index price at funding time |

Example row:
```
timestamp,instrument,funding_8h,index_price
2026-01-27T08:00:00,BTC-PERPETUAL,0.0001,101250.5
```

### Options Greeks (Parquet)

| Column | Type | Description |
|--------|------|-------------|
| timestamp | string | Snapshot timestamp in ISO 8601 format |
| currency | string | Base currency (BTC or ETH) |
| instrument | string | Option instrument name |
| expiry | string | Expiration date code (e.g., 27JAN26) |
| strike | float | Strike price in USD |
| type | string | Option type (call or put) |
| underlying | float | Current underlying price in USD |
| mark_price | float | Mark price in base currency (BTC or ETH) |
| mark_iv | float | Mark implied volatility (percentage) |
| bid | float | Best bid price in base currency |
| ask | float | Best ask price in base currency |
| open_interest | float | Open interest in contracts |
| volume_24h | float | 24-hour trading volume |
| delta | float | Delta Greek (-1 to 1) |
| gamma | float | Gamma Greek |
| theta | float | Theta Greek (daily decay) |
| vega | float | Vega Greek |

Example row:
```
timestamp: 2026-01-27T12:15:00
currency: BTC
instrument: BTC-31JAN26-100000-C
expiry: 31JAN26
strike: 100000.0
type: call
underlying: 101250.5
mark_price: 0.0523
mark_iv: 45.5
bid: 0.0520
ask: 0.0526
open_interest: 1250.0
volume_24h: 85.5
delta: 0.55
gamma: 0.00002
theta: -125.5
vega: 185.2
```

### Order Book (Parquet)

| Column | Type | Description |
|--------|------|-------------|
| timestamp | string | Snapshot timestamp in ISO 8601 format |
| instrument | string | Instrument name (e.g., BTC-PERPETUAL) |
| best_bid | float | Best bid price in USD |
| best_ask | float | Best ask price in USD |
| mid_price | float | Mid price in USD |
| spread | float | Bid-ask spread in USD |
| bid_depth | float | Total bid depth (sum of bid sizes) |
| ask_depth | float | Total ask depth (sum of ask sizes) |

Example row:
```
timestamp: 2026-01-27T12:15:00
instrument: BTC-PERPETUAL
best_bid: 101248.5
best_ask: 101251.5
mid_price: 101250.0
spread: 3.0
bid_depth: 125.5
ask_depth: 118.2
```

### Open Interest (Parquet)

| Column | Type | Description |
|--------|------|-------------|
| timestamp | string | Snapshot timestamp in ISO 8601 format |
| currency | string | Base currency (BTC or ETH) |
| perpetual_oi | float | Perpetual futures open interest |
| futures_oi | float | Total futures open interest (all expirations) |
| options_oi | float | Total options open interest |

Example row:
```
timestamp: 2026-01-27T12:15:00
currency: BTC
perpetual_oi: 45250.5
futures_oi: 52180.2
options_oi: 125500.0
```

---

## Example Analysis Scripts

### Calculate Average Daily Funding Rate

```python
funding = read_csv_from_s3('data/funding_BTC.csv')
funding['timestamp'] = pd.to_datetime(funding['timestamp'])
funding['date'] = funding['timestamp'].dt.date

daily_funding = funding.groupby('date')['funding_8h'].mean()
print('Average daily funding rate (last 7 days):')
print(daily_funding.tail(7))

# Annualized funding rate
annual_rate = daily_funding * 3 * 365  # 3 funding periods per day
print('\nAnnualized funding rate:')
print(annual_rate.tail(7))
```

### Track Delta Changes for Specific Strike

```python
greeks = read_date_range('options_greeks', 'BTC', '2026-01-20', '2026-01-27')
greeks['timestamp'] = pd.to_datetime(greeks['timestamp'])

# Filter for 100k strike calls
calls_100k = greeks[(greeks['strike'] == 100000) & (greeks['type'] == 'call')]

# Group by timestamp and get average delta
delta_over_time = calls_100k.groupby('timestamp')['delta'].mean()
print('Delta for 100k calls over time:')
print(delta_over_time.head(20))
```

### Monitor Open Interest Changes

```python
oi = read_date_range('open_interest', None, '2026-01-20', '2026-01-27')
oi['timestamp'] = pd.to_datetime(oi['timestamp'])

btc_oi = oi[oi['currency'] == 'BTC'].copy()
btc_oi = btc_oi.sort_values('timestamp')

# Calculate OI change
btc_oi['perp_oi_change'] = btc_oi['perpetual_oi'].diff()
btc_oi['options_oi_change'] = btc_oi['options_oi'].diff()

print('BTC Open Interest changes:')
print(btc_oi[['timestamp', 'perpetual_oi', 'perp_oi_change', 'options_oi', 'options_oi_change']].tail(20))
```

### Calculate Implied Volatility Surface

```python
greeks = read_parquet_from_s3('data/options_greeks/BTC/2026-01-27.parquet')

# Get latest snapshot
latest_time = greeks['timestamp'].max()
latest = greeks[greeks['timestamp'] == latest_time]

# Pivot to create IV surface
calls = latest[latest['type'] == 'call']
iv_surface = calls.pivot_table(
    values='mark_iv',
    index='strike',
    columns='expiry',
    aggfunc='mean'
)

print('Implied Volatility Surface (Calls):')
print(iv_surface)
```

---

## Access Permissions

To access this data, you need AWS credentials with the following IAM policy:

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "s3:GetObject",
                "s3:ListBucket"
            ],
            "Resource": [
                "arn:aws:s3:::crypto-collector-prod-data-720428162886",
                "arn:aws:s3:::crypto-collector-prod-data-720428162886/*"
            ]
        }
    ]
}
```

Contact the data administrator to request read-only credentials.

---

## Technical Details

- Data Source: Deribit Exchange (public API)
- Collection Frequency: Every 15 minutes
- Lambda Function: crypto-collector-prod
- AWS Region: eu-north-1
- Data Retention: Standard storage for 30 days, then moved to Infrequent Access, then Glacier after 90 days
- Supported Cryptocurrencies: BTC, ETH

---

## Troubleshooting

### Access Denied Error

Ensure your AWS credentials are configured correctly:
```bash
aws configure list
```

Verify you have the correct permissions by testing:
```bash
aws s3 ls s3://crypto-collector-prod-data-720428162886/data/ --region eu-north-1
```

### File Not Found

Check if the file exists:
```bash
aws s3 ls s3://crypto-collector-prod-data-720428162886/data/options_greeks/BTC/
```

Parquet files are created daily. If requesting today's data, ensure at least one 15-minute collection cycle has completed.

### Slow Downloads

For large files, consider using the AWS CLI sync command which supports parallel transfers:
```bash
aws s3 sync s3://crypto-collector-prod-data-720428162886/data/ ./local_data/ --region eu-north-1
```

---

## Contact

For access requests or technical issues, contact the data administrator.
