"""
S3-backed rolling buffer for candles and derivatives

Uses the existing S3Storage class from aws.s3_storage for all I/O.
Manages parquet rolling buffers, JSON profiles, and daily archives.
"""

import json
from datetime import datetime, timezone
from typing import Any, Dict, List

import pandas as pd
from botocore.exceptions import ClientError


class CandleStore:
    """
    Manages S3 rolling buffers for signal engine data.

    Files managed:
      {prefix}/candles_1m_rolling.parquet
      {prefix}/derivatives_rolling.parquet
      {prefix}/volume_profile.json
      {prefix}/signals_latest.json
      {prefix}/archive/{data_type}/YYYY-MM-DD.parquet
    """

    def __init__(self, s3_storage, s3_prefix: str = "signals"):
        """
        Args:
            s3_storage: An aws.s3_storage.S3Storage instance
            s3_prefix: S3 key prefix for all signal files
        """
        self.storage = s3_storage
        self.prefix = s3_prefix

    def _key(self, name: str) -> str:
        return f"{self.prefix}/{name}"

    # ----------------------------------------------------------
    # Rolling candles (parquet)
    # ----------------------------------------------------------

    def load_rolling_candles(self) -> pd.DataFrame:
        """Read signals/candles_1m_rolling.parquet from S3."""
        key = self._key("candles_1m_rolling.parquet")
        df = self.storage.download_dataframe(key, file_format="parquet")
        if df is None:
            return pd.DataFrame()
        if "ts" in df.columns:
            df["ts"] = pd.to_datetime(df["ts"], utc=True)
        return df

    def save_rolling_candles(self, df: pd.DataFrame) -> None:
        """Overwrite the rolling candles parquet."""
        key = self._key("candles_1m_rolling.parquet")
        self.storage.upload_dataframe(df, key, file_format="parquet")

    # ----------------------------------------------------------
    # Rolling derivatives (parquet)
    # ----------------------------------------------------------

    def load_rolling_derivatives(self) -> pd.DataFrame:
        """Read signals/derivatives_rolling.parquet from S3."""
        key = self._key("derivatives_rolling.parquet")
        df = self.storage.download_dataframe(key, file_format="parquet")
        if df is None:
            return pd.DataFrame()
        if "ts" in df.columns:
            df["ts"] = pd.to_datetime(df["ts"], utc=True)
        return df

    def save_rolling_derivatives(self, df: pd.DataFrame) -> None:
        """Overwrite the rolling derivatives parquet."""
        key = self._key("derivatives_rolling.parquet")
        self.storage.upload_dataframe(df, key, file_format="parquet")

    # ----------------------------------------------------------
    # Rolling liquidations (parquet)
    # ----------------------------------------------------------

    def load_rolling_liquidations(self) -> pd.DataFrame:
        """Read signals/liquidations_rolling.parquet from S3."""
        key = self._key("liquidations_rolling.parquet")
        df = self.storage.download_dataframe(key, file_format="parquet")
        if df is None:
            return pd.DataFrame()
        if "time" in df.columns:
            df["time"] = pd.to_datetime(df["time"], utc=True)
        return df

    def save_rolling_liquidations(self, df: pd.DataFrame) -> None:
        """Overwrite the rolling liquidations parquet."""
        key = self._key("liquidations_rolling.parquet")
        self.storage.upload_dataframe(df, key, file_format="parquet")

    # ----------------------------------------------------------
    # Volume profile (JSON)
    # ----------------------------------------------------------

    def load_volume_profile(self) -> Dict[str, Any]:
        """Read signals/volume_profile.json from S3."""
        key = self._key("volume_profile.json")
        try:
            resp = self.storage.s3_client.get_object(
                Bucket=self.storage.bucket_name, Key=key
            )
            return json.loads(resp["Body"].read().decode("utf-8"))
        except ClientError:
            return {}

    def save_volume_profile(self, profile: Dict[str, Any]) -> None:
        """Write volume_profile.json to S3."""
        key = self._key("volume_profile.json")
        self.storage.upload_json(profile, key)

    # ----------------------------------------------------------
    # Signals latest (JSON)
    # ----------------------------------------------------------

    def load_signals_latest(self) -> Dict[str, Any]:
        """Read signals/signals_latest.json from S3."""
        key = self._key("signals_latest.json")
        try:
            resp = self.storage.s3_client.get_object(
                Bucket=self.storage.bucket_name, Key=key
            )
            return json.loads(resp["Body"].read().decode("utf-8"))
        except ClientError:
            return {}

    def save_signals_latest(self, signals: Dict[str, Any]) -> None:
        """Write signals_latest.json to S3."""
        key = self._key("signals_latest.json")
        self.storage.upload_json(signals, key)

    # ----------------------------------------------------------
    # Buffer management
    # ----------------------------------------------------------

    @staticmethod
    def append_candles(
        existing_df: pd.DataFrame,
        new_rows: List[Dict],
        limit: int = 1500,
    ) -> pd.DataFrame:
        """
        Append new candle rows to existing DataFrame.
        Deduplicates on (ts, symbol), sorts by ts, trims to limit per symbol.
        """
        if not new_rows:
            return existing_df

        new_df = pd.DataFrame(new_rows)
        if "ts" in new_df.columns:
            new_df["ts"] = pd.to_datetime(new_df["ts"], utc=True)

        if existing_df.empty:
            combined = new_df
        else:
            combined = pd.concat([existing_df, new_df], ignore_index=True)

        # Deduplicate
        if "ts" in combined.columns and "symbol" in combined.columns:
            combined = combined.drop_duplicates(
                subset=["ts", "symbol"], keep="last"
            )
            combined = combined.sort_values("ts").reset_index(drop=True)

        # Trim per symbol
        if "symbol" in combined.columns:
            parts = []
            for sym in combined["symbol"].unique():
                part = combined[combined["symbol"] == sym].tail(limit)
                parts.append(part)
            combined = pd.concat(parts, ignore_index=True)
        else:
            combined = combined.tail(limit)

        return combined

    # ----------------------------------------------------------
    # Daily archive
    # ----------------------------------------------------------

    def append_to_daily_archive(
        self, df: pd.DataFrame, data_type: str
    ) -> None:
        """
        Append rows to signals/archive/{data_type}/YYYY-MM-DD.parquet.

        Reads existing daily file (if any), concats, deduplicates, and writes back.
        Deduplication prevents duplicate rows from Lambda retries.
        """
        if df.empty:
            return

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        key = self._key(f"archive/{data_type}/{today}.parquet")

        existing = self.storage.download_dataframe(key, file_format="parquet")
        if existing is not None and not existing.empty:
            combined = pd.concat([existing, df], ignore_index=True)
            # Dedup on (ts, symbol) if both columns exist
            if "ts" in combined.columns and "symbol" in combined.columns:
                combined = combined.drop_duplicates(
                    subset=["ts", "symbol"], keep="last"
                )
            combined = combined.sort_values("ts").reset_index(drop=True) if "ts" in combined.columns else combined
        else:
            combined = df

        self.storage.upload_dataframe(combined, key, file_format="parquet")
