"""
S3 Storage Adapter for Crypto Data

Handles uploading DataFrames and files to AWS S3
with proper organization and partitioning.
"""

import io
import json
import os
from datetime import datetime
from typing import Optional, Dict, Any, List

import boto3
import pandas as pd
from botocore.exceptions import ClientError
from loguru import logger


class S3Storage:
    """
    S3 Storage handler for crypto data
    
    Organizes data in S3 with the following structure:
    
    s3://bucket-name/
    ├── latest/                          # Latest snapshots (overwritten each run)
    │   ├── options_surface_BTC.csv
    │   ├── options_surface_ETH.csv
    │   ├── orderbook.csv
    │   ├── funding_rates.csv
    │   ├── open_interest.csv
    │   └── basis.csv
    ├── options_surface/                 # Historical partitioned data
    │   └── YYYY/MM/DD/
    │       └── options_surface_HHMM.csv
    ├── orderbook/
    │   └── YYYY/MM/DD/
    │       └── orderbook_HHMM.csv
    ├── funding_rates/
    │   └── YYYY/MM/DD/
    │       └── funding_rates_HHMM.csv
    ├── open_interest/
    │   └── YYYY/MM/DD/
    │       └── open_interest_HHMM.csv
    ├── basis/
    │   └── YYYY/MM/DD/
    │       └── basis_HHMM.csv
    └── ohlcv/
        └── {instrument}/
            └── {timeframe}/
                └── YYYY/MM/DD/
                    └── ohlcv_HHMM.csv
    """
    
    def __init__(
        self,
        bucket_name: str,
        region: Optional[str] = None,
        aws_access_key_id: Optional[str] = None,
        aws_secret_access_key: Optional[str] = None
    ):
        """
        Initialize S3 storage
        
        Args:
            bucket_name: S3 bucket name
            region: AWS region (default: from env or eu-north-1)
            aws_access_key_id: Optional AWS credentials
            aws_secret_access_key: Optional AWS credentials
        """
        self.bucket_name = bucket_name
        self.region = region or os.environ.get("AWS_REGION", "eu-north-1")
        
        # Initialize S3 client
        session_kwargs = {}
        if aws_access_key_id and aws_secret_access_key:
            session_kwargs["aws_access_key_id"] = aws_access_key_id
            session_kwargs["aws_secret_access_key"] = aws_secret_access_key
            
        self.s3_client = boto3.client("s3", region_name=self.region, **session_kwargs)
        self.s3_resource = boto3.resource("s3", region_name=self.region, **session_kwargs)
        
    def upload_dataframe(
        self,
        df: pd.DataFrame,
        s3_key: str,
        file_format: str = "csv"
    ) -> bool:
        """
        Upload a DataFrame to S3
        
        Args:
            df: Pandas DataFrame to upload
            s3_key: S3 object key (path within bucket)
            file_format: 'csv' or 'parquet'
            
        Returns:
            True if successful
        """
        try:
            buffer = io.BytesIO()
            
            if file_format == "parquet":
                df.to_parquet(buffer, index=False, engine="pyarrow")
                content_type = "application/octet-stream"
            else:
                # CSV format
                csv_data = df.to_csv(index=False)
                buffer.write(csv_data.encode("utf-8"))
                content_type = "text/csv"
                
            buffer.seek(0)
            
            self.s3_client.upload_fileobj(
                buffer,
                self.bucket_name,
                s3_key,
                ExtraArgs={"ContentType": content_type}
            )
            
            logger.debug(f"Uploaded {s3_key} ({len(df)} rows)")
            return True
            
        except ClientError as e:
            logger.error(f"Failed to upload {s3_key}: {e}")
            return False
            
    def upload_json(self, data: Dict[str, Any], s3_key: str) -> bool:
        """
        Upload JSON data to S3
        """
        try:
            json_data = json.dumps(data, indent=2, default=str)
            
            self.s3_client.put_object(
                Bucket=self.bucket_name,
                Key=s3_key,
                Body=json_data.encode("utf-8"),
                ContentType="application/json"
            )
            
            return True
            
        except ClientError as e:
            logger.error(f"Failed to upload {s3_key}: {e}")
            return False
            
    def download_dataframe(
        self,
        s3_key: str,
        file_format: str = "csv"
    ) -> Optional[pd.DataFrame]:
        """
        Download a DataFrame from S3
        """
        try:
            response = self.s3_client.get_object(Bucket=self.bucket_name, Key=s3_key)
            
            if file_format == "parquet":
                return pd.read_parquet(io.BytesIO(response["Body"].read()))
            else:
                return pd.read_csv(io.BytesIO(response["Body"].read()))
                
        except ClientError as e:
            logger.error(f"Failed to download {s3_key}: {e}")
            return None
            
    def list_files(
        self,
        prefix: str = "",
        max_keys: int = 1000
    ) -> List[Dict[str, Any]]:
        """
        List files in S3 bucket with given prefix
        """
        try:
            response = self.s3_client.list_objects_v2(
                Bucket=self.bucket_name,
                Prefix=prefix,
                MaxKeys=max_keys
            )
            
            files = []
            for obj in response.get("Contents", []):
                files.append({
                    "key": obj["Key"],
                    "size": obj["Size"],
                    "last_modified": obj["LastModified"]
                })
                
            return files
            
        except ClientError as e:
            logger.error(f"Failed to list files: {e}")
            return []
            
    def get_latest(self, data_type: str) -> Optional[pd.DataFrame]:
        """
        Get the latest version of a data type
        
        Args:
            data_type: e.g., 'options_surface_BTC', 'orderbook', 'funding_rates'
        """
        s3_key = f"latest/{data_type}.csv"
        return self.download_dataframe(s3_key)
        
    def get_historical_range(
        self,
        data_type: str,
        start_date: datetime,
        end_date: datetime
    ) -> pd.DataFrame:
        """
        Get historical data for a date range
        
        Combines multiple daily files into a single DataFrame
        """
        all_data = []
        
        current_date = start_date
        while current_date <= end_date:
            prefix = f"{data_type}/{current_date.strftime('%Y/%m/%d')}/"
            files = self.list_files(prefix)
            
            for file_info in files:
                df = self.download_dataframe(file_info["key"])
                if df is not None:
                    all_data.append(df)
                    
            current_date += pd.Timedelta(days=1)
            
        if all_data:
            return pd.concat(all_data, ignore_index=True)
        return pd.DataFrame()
        
    def ensure_bucket_exists(self) -> bool:
        """
        Create the S3 bucket if it doesn't exist
        """
        try:
            self.s3_client.head_bucket(Bucket=self.bucket_name)
            logger.info(f"Bucket {self.bucket_name} exists")
            return True
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "")
            
            if error_code == "404":
                # Bucket doesn't exist, create it
                try:
                    if self.region == "us-east-1":
                        self.s3_client.create_bucket(Bucket=self.bucket_name)
                    else:
                        self.s3_client.create_bucket(
                            Bucket=self.bucket_name,
                            CreateBucketConfiguration={
                                "LocationConstraint": self.region
                            }
                        )
                    logger.info(f"Created bucket {self.bucket_name}")
                    return True
                except ClientError as create_error:
                    logger.error(f"Failed to create bucket: {create_error}")
                    return False
            else:
                logger.error(f"Error checking bucket: {e}")
                return False


class S3DataManager:
    """
    High-level data management for crypto data on S3
    """
    
    def __init__(self, bucket_name: str):
        self.storage = S3Storage(bucket_name)
        
    def save_snapshot(
        self,
        data_type: str,
        df: pd.DataFrame,
        timestamp: Optional[datetime] = None
    ):
        """
        Save a data snapshot with proper partitioning
        
        Saves both:
        - Historical version (partitioned by date/time)
        - Latest version (for quick access)
        """
        timestamp = timestamp or datetime.utcnow()
        
        # Historical path
        date_prefix = timestamp.strftime("%Y/%m/%d")
        time_suffix = timestamp.strftime("%H%M")
        historical_key = f"{data_type}/{date_prefix}/{data_type}_{time_suffix}.csv"
        
        # Latest path
        latest_key = f"latest/{data_type}.csv"
        
        # Upload both
        self.storage.upload_dataframe(df, historical_key)
        self.storage.upload_dataframe(df, latest_key)
        
        logger.info(f"Saved {data_type}: {len(df)} rows")
        
    def get_data_summary(self) -> Dict[str, Any]:
        """
        Get summary of all data in the bucket
        """
        data_types = [
            "options_surface",
            "orderbook", 
            "funding_rates",
            "open_interest",
            "basis",
            "ohlcv"
        ]
        
        summary = {}
        
        for data_type in data_types:
            files = self.storage.list_files(prefix=f"{data_type}/")
            
            if files:
                summary[data_type] = {
                    "file_count": len(files),
                    "total_size_mb": sum(f["size"] for f in files) / (1024 * 1024),
                    "latest_file": max(files, key=lambda x: x["last_modified"])["key"]
                }
            else:
                summary[data_type] = {"file_count": 0}
                
        return summary

