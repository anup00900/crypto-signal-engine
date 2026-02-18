"""
AWS Lambda Handler for Crypto Data Collection
Runs every 15 minutes via EventBridge

Collects:
- Options Surface (IV, Greeks)
- Order Book Snapshots
- Funding Rates (current)
- Open Interest
- Basis
- OHLCV (latest candles)
"""

import asyncio
import json
import os
import sys
import glob
from datetime import datetime, timedelta
from typing import Dict, Any

# Add parent directory for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import boto3
import pandas as pd
from loguru import logger

# Configure logging for Lambda
logger.remove()
logger.add(sys.stderr, level="INFO", 
           format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}")


def get_secrets() -> Dict[str, str]:
    """
    Retrieve API credentials from AWS Secrets Manager
    """
    secret_name = os.environ.get("SECRETS_NAME", "crypto-collector/deribit")
    region = os.environ.get("AWS_REGION", "eu-north-1")
    
    client = boto3.client("secretsmanager", region_name=region)
    
    try:
        response = client.get_secret_value(SecretId=secret_name)
        return json.loads(response["SecretString"])
    except Exception as e:
        logger.warning(f"Could not retrieve secrets: {e}")
        # Fall back to environment variables
        return {
            "DERIBIT_CLIENT_ID": os.environ.get("DERIBIT_CLIENT_ID", ""),
            "DERIBIT_CLIENT_SECRET": os.environ.get("DERIBIT_CLIENT_SECRET", "")
        }


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Main Lambda entry point
    
    Triggered by EventBridge every 15 minutes
    """
    logger.info("=" * 60)
    logger.info("CRYPTO DATA COLLECTION - LAMBDA EXECUTION")
    logger.info(f"Timestamp: {datetime.utcnow().isoformat()}")
    logger.info("=" * 60)
    
    # Get configuration
    bucket_name = os.environ.get("S3_BUCKET", "ailerlabs-crypto-data")
    currencies = os.environ.get("CURRENCIES", "BTC,ETH").split(",")
    
    # Load secrets
    secrets = get_secrets()
    os.environ["DERIBIT_CLIENT_ID"] = secrets.get("DERIBIT_CLIENT_ID", "")
    os.environ["DERIBIT_CLIENT_SECRET"] = secrets.get("DERIBIT_CLIENT_SECRET", "")
    
    try:
        # Run the async collector
        result = asyncio.run(
            run_collection(bucket_name, currencies)
        )
        
        logger.info("=" * 60)
        logger.info("COLLECTION COMPLETE")
        logger.info(f"Files uploaded: {result.get('files_uploaded', 0)}")
        logger.info("=" * 60)
        
        return {
            "statusCode": 200,
            "body": json.dumps({
                "message": "Data collection successful",
                "timestamp": datetime.utcnow().isoformat(),
                "files_uploaded": result.get("files_uploaded", 0),
                "currencies": currencies
            })
        }
        
    except Exception as e:
        logger.error(f"Collection failed: {e}")
        
        # Send alert (optional - if SNS topic configured)
        send_alert(f"Crypto data collection failed: {str(e)}")
        
        return {
            "statusCode": 500,
            "body": json.dumps({
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat()
            })
        }


async def run_collection(bucket_name: str, currencies: list) -> Dict[str, Any]:
    """
    Run the data collection and upload to S3
    
    - CSV files: OHLCV, Funding (append mode)
    - Parquet files: Options Greeks, Order Book, Open Interest (daily partitions, append)
    """
    from aws.collector import CryptoCollector, Config
    from aws.s3_storage import S3Storage
    
    # Initialize storage
    storage = S3Storage(bucket_name)
    
    # Configure collector - output to temp directory
    config = Config(
        cryptos=currencies,
        output_dir="/tmp/data"
    )
    
    # Create temp output directories
    os.makedirs("/tmp/data", exist_ok=True)
    os.makedirs("/tmp/data/options_greeks", exist_ok=True)
    os.makedirs("/tmp/data/orderbook", exist_ok=True)
    os.makedirs("/tmp/data/open_interest", exist_ok=True)
    
    files_uploaded = 0
    
    try:
        # Download existing CSV files from S3 to append to
        existing_csv = storage.list_files(prefix="data/")
        for file_info in existing_csv:
            if file_info['key'].endswith('.csv'):
                local_path = f"/tmp/{file_info['key']}"
                os.makedirs(os.path.dirname(local_path), exist_ok=True)
                try:
                    df = storage.download_dataframe(file_info['key'], file_format='csv')
                    if df is not None:
                        df.to_csv(local_path, index=False)
                except:
                    pass
        
        # Download existing Parquet files (today's daily files only)
        today = datetime.utcnow().strftime("%Y-%m-%d")
        for data_type in ['options_greeks', 'orderbook', 'open_interest']:
            # For options_greeks with currency subdirs
            if data_type == 'options_greeks':
                for currency in currencies:
                    if currency in ['BTC', 'ETH']:
                        s3_key = f"data/{data_type}/{currency}/{today}.parquet"
                        local_path = f"/tmp/data/{data_type}/{currency}/{today}.parquet"
                        os.makedirs(os.path.dirname(local_path), exist_ok=True)
                        try:
                            df = storage.download_dataframe(s3_key, file_format='parquet')
                            if df is not None:
                                df.to_parquet(local_path, index=False)
                        except:
                            pass
            else:
                s3_key = f"data/{data_type}/{today}.parquet"
                local_path = f"/tmp/data/{data_type}/{today}.parquet"
                os.makedirs(os.path.dirname(local_path), exist_ok=True)
                try:
                    df = storage.download_dataframe(s3_key, file_format='parquet')
                    if df is not None:
                        df.to_parquet(local_path, index=False)
                except:
                    pass
        
        # Run collection (appends to existing files)
        async with CryptoCollector(config) as collector:
            await collector.collect_update()
        
        # Upload all CSV files back to S3
        for filepath in glob.glob("/tmp/data/*.csv"):
            filename = os.path.basename(filepath)
            s3_key = f"data/{filename}"
            
            df = pd.read_csv(filepath)
            storage.upload_dataframe(df, s3_key, file_format='csv')
            files_uploaded += 1
            logger.info(f"Uploaded CSV: {s3_key} ({len(df)} rows)")
        
        # Upload all Parquet files back to S3
        for data_type in ['options_greeks', 'orderbook', 'open_interest']:
            pattern = f"/tmp/data/{data_type}/**/*.parquet"
            for filepath in glob.glob(pattern, recursive=True):
                # Build S3 key from local path
                rel_path = filepath.replace("/tmp/data/", "")
                s3_key = f"data/{rel_path}"
                
                df = pd.read_parquet(filepath)
                storage.upload_dataframe(df, s3_key, file_format='parquet')
                files_uploaded += 1
                logger.info(f"Uploaded Parquet: {s3_key} ({len(df)} rows)")
                
    except Exception as e:
        logger.error(f"Collection error: {e}")
        raise
        
    return {"files_uploaded": files_uploaded}


def send_alert(message: str):
    """
    Send alert via SNS (optional)
    """
    topic_arn = os.environ.get("ALERT_SNS_TOPIC")
    
    if not topic_arn:
        return
        
    try:
        sns = boto3.client("sns")
        sns.publish(
            TopicArn=topic_arn,
            Subject="Crypto Data Collector Alert",
            Message=message
        )
    except Exception as e:
        logger.error(f"Failed to send alert: {e}")


# For local testing
if __name__ == "__main__":
    # Test the handler locally
    test_event = {"source": "local-test"}
    result = lambda_handler(test_event, None)
    print(json.dumps(result, indent=2))

