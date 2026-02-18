# 🚀 AWS Deployment Guide - Crypto Data Collector

This guide will walk you through deploying your crypto data collector to AWS for automated 24/7 data collection every 15 minutes.

---

## 📋 Table of Contents

1. [Prerequisites](#prerequisites)
2. [Quick Start (5 minutes)](#quick-start)
3. [Detailed Setup](#detailed-setup)
4. [Accessing Your Data](#accessing-your-data)
5. [Monitoring & Alerts](#monitoring--alerts)
6. [Cost Optimization](#cost-optimization)
7. [Troubleshooting](#troubleshooting)

---

## Prerequisites

### 1. Install AWS CLI

**macOS:**
```bash
brew install awscli
```

**Or download from:** https://aws.amazon.com/cli/

### 2. Install Terraform

**macOS:**
```bash
brew tap hashicorp/tap
brew install hashicorp/tap/terraform
```

**Or download from:** https://terraform.io/downloads

### 3. Configure AWS Credentials

You already have an AWS account (Ailerlabs - 7204-2816-2886). Now configure your local CLI:

```bash
aws configure
```

Enter:
- **AWS Access Key ID:** (from IAM user your-iam-user)
- **AWS Secret Access Key:** (from IAM user)
- **Default region:** `eu-north-1`
- **Default output format:** `json`

**To create access keys (if you don't have them):**

1. Go to AWS Console → IAM → Users → your-iam-user
2. Click "Security credentials" tab
3. Click "Create access key"
4. Select "Command Line Interface (CLI)"
5. Download and save the credentials

---

## Quick Start

If you want to deploy everything in one go:

```bash
cd /Users/anup/Downloads/Crypto\ Data\ Collector/crypto-data-collector/aws

# Make the script executable
chmod +x deploy.sh

# Run the deployment
./deploy.sh
```

This will:
1. ✅ Create the Lambda deployment package
2. ✅ Deploy all AWS infrastructure
3. ✅ Set up your API credentials
4. ✅ Start the 15-minute collection schedule

---

## Detailed Setup

### Step 1: Create Lambda Package

```bash
cd /Users/anup/Downloads/Crypto\ Data\ Collector/crypto-data-collector

# Create package directory
mkdir -p aws/package

# Create a virtual environment for packaging
python3 -m venv /tmp/lambda-build
source /tmp/lambda-build/bin/activate

# Install dependencies
pip install pandas numpy aiohttp websockets loguru boto3 pydantic pydantic-settings

# Copy to package directory
cd /tmp/lambda-build/lib/python3.*/site-packages
zip -r9 ~/Downloads/Crypto\ Data\ Collector/crypto-data-collector/aws/package/lambda.zip .

# Add project code
cd /Users/anup/Downloads/Crypto\ Data\ Collector/crypto-data-collector
zip -r aws/package/lambda.zip collectors config utils aws -x "*.pyc" -x "__pycache__/*" -x "venv/*"

deactivate
```

### Step 2: Deploy Infrastructure with Terraform

```bash
cd aws/terraform

# Initialize Terraform
terraform init

# Preview what will be created
terraform plan

# Deploy (type 'yes' when prompted)
terraform apply
```

**Resources Created:**
| Resource | Name | Purpose |
|----------|------|---------|
| S3 Bucket | `crypto-collector-prod-data-720428162886` | Store collected data |
| Lambda | `crypto-collector-prod` | Run data collection |
| EventBridge Rule | `crypto-collector-prod-schedule` | 15-min trigger |
| Secrets Manager | `crypto-collector-prod/deribit` | API credentials |
| CloudWatch Logs | `/aws/lambda/crypto-collector-prod` | Execution logs |
| SNS Topic | `crypto-collector-prod-alerts` | Error alerts |

### Step 3: Set Your Deribit API Credentials

```bash
aws secretsmanager put-secret-value \
  --secret-id crypto-collector-prod/deribit \
  --secret-string '{"DERIBIT_CLIENT_ID":"YOUR_CLIENT_ID","DERIBIT_CLIENT_SECRET":"YOUR_CLIENT_SECRET"}'
```

**Don't have Deribit API keys?**
1. Go to https://www.deribit.com/
2. Login → Account → API → Create new API key
3. Enable "read" permissions for market data

### Step 4: Test the Deployment

```bash
# Manually trigger the Lambda
aws lambda invoke \
  --function-name crypto-collector-prod \
  --payload '{}' \
  response.json

# Check the response
cat response.json

# View logs
aws logs tail /aws/lambda/crypto-collector-prod --follow
```

### Step 5: Verify Data Collection

```bash
# List collected data
aws s3 ls s3://crypto-collector-prod-data-720428162886/latest/

# Download a sample file
aws s3 cp s3://crypto-collector-prod-data-720428162886/latest/options_surface_BTC.csv .
```

---

## Accessing Your Data

### S3 Data Structure

```
s3://crypto-collector-prod-data-720428162886/
├── latest/                              # Most recent snapshots
│   ├── options_surface_BTC.csv          # BTC options with Greeks
│   ├── options_surface_ETH.csv          # ETH options with Greeks
│   ├── orderbook.csv                    # Order book snapshots
│   ├── funding_rates.csv                # Current funding rates
│   ├── open_interest.csv                # Open interest data
│   ├── basis.csv                        # Futures basis
│   └── ohlcv.csv                        # Latest OHLCV candles
│
├── options_surface_BTC/                 # Historical BTC options
│   └── 2026/01/25/
│       ├── options_surface_BTC_0000.csv
│       ├── options_surface_BTC_0015.csv
│       ├── options_surface_BTC_0030.csv
│       └── ...
│
├── options_surface_ETH/                 # Historical ETH options
│   └── ...
│
├── orderbook/                           # Historical orderbooks
│   └── ...
│
└── ...
```

### Download Commands

```bash
# Download latest options surface
aws s3 cp s3://crypto-collector-prod-data-720428162886/latest/options_surface_BTC.csv .

# Download all data for a specific day
aws s3 sync s3://crypto-collector-prod-data-720428162886/options_surface_BTC/2026/01/25/ ./data/

# Download entire bucket
aws s3 sync s3://crypto-collector-prod-data-720428162886/ ./all-data/
```

### Python Access

```python
import boto3
import pandas as pd
from io import StringIO

# Initialize S3 client
s3 = boto3.client('s3')
bucket = 'crypto-collector-prod-data-720428162886'

# Read latest options surface
response = s3.get_object(Bucket=bucket, Key='latest/options_surface_BTC.csv')
df = pd.read_csv(StringIO(response['Body'].read().decode('utf-8')))

print(df.head())
print(f"Options: {len(df)}")
print(f"Columns: {df.columns.tolist()}")
```

---

## Monitoring & Alerts

### View Logs

```bash
# Real-time log streaming
aws logs tail /aws/lambda/crypto-collector-prod --follow

# Last hour of logs
aws logs tail /aws/lambda/crypto-collector-prod --since 1h
```

### CloudWatch Dashboard

Go to: **AWS Console → CloudWatch → Dashboards**

Create a dashboard with:
- Lambda invocations
- Lambda errors
- Lambda duration
- S3 bucket size

### Email Alerts

To receive email alerts when collection fails:

1. Edit `aws/terraform/terraform.tfvars`:
```hcl
alert_email = "your-email@example.com"
```

2. Re-apply Terraform:
```bash
terraform apply
```

3. Confirm the subscription email from AWS SNS

---

## Cost Optimization

### Estimated Monthly Costs

| Service | Usage | Cost |
|---------|-------|------|
| Lambda | 96 invocations/day × 30 days | ~$5-10 |
| S3 | ~10GB storage | ~$2-3 |
| S3 Requests | ~3000 PUT/day | ~$1-2 |
| CloudWatch Logs | ~1GB/month | ~$0.50 |
| Secrets Manager | 1 secret | ~$0.40 |
| **Total** | | **~$10-15/month** |

### Cost-Saving Tips

1. **Reduce collection frequency** (30 min instead of 15 min):
   ```hcl
   schedule_rate = "rate(30 minutes)"
   ```

2. **Archive old data automatically** (already configured):
   - After 30 days → Standard-IA ($0.0125/GB)
   - After 90 days → Glacier ($0.004/GB)

3. **Reduce data retention**:
   Add to `main.tf`:
   ```hcl
   expiration {
     days = 365  # Delete after 1 year
   }
   ```

---

## Troubleshooting

### Common Issues

#### 1. "Access Denied" errors

```bash
# Check your IAM permissions
aws sts get-caller-identity

# Verify S3 bucket exists
aws s3 ls s3://crypto-collector-prod-data-720428162886/
```

#### 2. Lambda timeout

- Check CloudWatch logs for errors
- Increase Lambda memory (currently 1024MB)
- Reduce currencies or data types collected

#### 3. No data being collected

```bash
# Check if EventBridge rule is enabled
aws events describe-rule --name crypto-collector-prod-schedule

# Manually trigger collection
aws lambda invoke --function-name crypto-collector-prod response.json
cat response.json
```

#### 4. API credentials not working

```bash
# Verify secret exists
aws secretsmanager get-secret-value --secret-id crypto-collector-prod/deribit

# Update credentials
aws secretsmanager put-secret-value \
  --secret-id crypto-collector-prod/deribit \
  --secret-string '{"DERIBIT_CLIENT_ID":"new-id","DERIBIT_CLIENT_SECRET":"new-secret"}'
```

### Useful Commands

```bash
# Check Lambda status
aws lambda get-function --function-name crypto-collector-prod

# View recent invocations
aws lambda list-invocations --function-name crypto-collector-prod

# Check S3 bucket size
aws s3 ls s3://crypto-collector-prod-data-720428162886 --recursive --summarize | tail -2

# Disable collection temporarily
aws events disable-rule --name crypto-collector-prod-schedule

# Re-enable collection
aws events enable-rule --name crypto-collector-prod-schedule

# Destroy all resources (⚠️ DELETES EVERYTHING)
cd aws/terraform && terraform destroy
```

---

## Data Schema

### Options Surface (Greeks)

| Column | Type | Description |
|--------|------|-------------|
| timestamp | datetime | Collection time |
| currency | string | BTC or ETH |
| instrument_name | string | e.g., BTC-28MAR25-100000-C |
| expiry | string | Expiration date |
| strike | float | Strike price |
| option_type | string | call or put |
| underlying_price | float | Current spot price |
| mark_price | float | Mark price |
| mark_iv | float | Implied volatility |
| bid_price | float | Best bid |
| ask_price | float | Best ask |
| open_interest | float | Open interest |
| volume_24h | float | 24h volume |
| **delta** | float | Delta Greek |
| **gamma** | float | Gamma Greek |
| **theta** | float | Theta Greek |
| **vega** | float | Vega Greek |
| **rho** | float | Rho Greek |

### Funding Rates

| Column | Type | Description |
|--------|------|-------------|
| timestamp | datetime | Collection time |
| instrument_name | string | e.g., BTC-PERPETUAL |
| funding_8h | float | 8-hour funding rate |
| current_funding | float | Current funding rate |
| index_price | float | Index price |
| mark_price | float | Mark price |

### Open Interest

| Column | Type | Description |
|--------|------|-------------|
| timestamp | datetime | Collection time |
| currency | string | BTC or ETH |
| perpetual_oi | float | Perpetual OI |
| total_futures_oi | float | All futures OI |
| total_options_oi | float | All options OI |
| calls_oi | float | Calls OI |
| puts_oi | float | Puts OI |
| put_call_ratio | float | Put/Call ratio |

---

## Support

If you encounter issues:

1. Check CloudWatch logs for errors
2. Verify AWS credentials and permissions
3. Test the Lambda function manually
4. Check Deribit API status: https://status.deribit.com/

---

**🎉 Your pipeline is now running 24/7, collecting data every 15 minutes!**

