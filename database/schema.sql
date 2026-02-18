-- ===========================================
-- CRYPTO DATA COLLECTOR - DATABASE SCHEMA
-- ===========================================
-- Run this script as the postgres superuser to set up
-- the database with multi-user access

-- Create database
CREATE DATABASE crypto_data;

-- Connect to the database
\c crypto_data;

-- ===========================================
-- CREATE ROLES AND USERS
-- ===========================================

-- Admin role - full access
CREATE ROLE crypto_admin WITH LOGIN PASSWORD 'CHANGE_ME_IN_PRODUCTION';
GRANT ALL PRIVILEGES ON DATABASE crypto_data TO crypto_admin;

-- Collector role - insert/update data
CREATE ROLE crypto_collector WITH LOGIN PASSWORD 'CHANGE_ME_IN_PRODUCTION';
GRANT CONNECT ON DATABASE crypto_data TO crypto_collector;

-- Analyst role - read-only for analysis
CREATE ROLE crypto_analyst WITH LOGIN PASSWORD 'CHANGE_ME_IN_PRODUCTION';
GRANT CONNECT ON DATABASE crypto_data TO crypto_analyst;

-- API role - read-only for external applications
CREATE ROLE crypto_api WITH LOGIN PASSWORD 'CHANGE_ME_IN_PRODUCTION';
GRANT CONNECT ON DATABASE crypto_data TO crypto_api;

-- ===========================================
-- CREATE SCHEMA
-- ===========================================

-- Create schema owned by admin
CREATE SCHEMA IF NOT EXISTS crypto AUTHORIZATION crypto_admin;

-- Set default schema
SET search_path TO crypto, public;

-- ===========================================
-- INSTRUMENTS TABLE (Reference Data)
-- ===========================================

CREATE TABLE crypto.instruments (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    name VARCHAR(100) NOT NULL,
    exchange VARCHAR(50) NOT NULL,
    instrument_name VARCHAR(100) NOT NULL UNIQUE,
    instrument_type VARCHAR(50) NOT NULL, -- perpetual, spot, future
    base_currency VARCHAR(20) NOT NULL,
    quote_currency VARCHAR(20) NOT NULL,
    contract_size DECIMAL(20, 8),
    tick_size DECIMAL(20, 10),
    min_trade_amount DECIMAL(20, 8),
    is_active BOOLEAN DEFAULT true,
    coingecko_id VARCHAR(100),
    metadata JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_instruments_symbol ON crypto.instruments(symbol);
CREATE INDEX idx_instruments_exchange ON crypto.instruments(exchange);
CREATE INDEX idx_instruments_name ON crypto.instruments(instrument_name);

-- ===========================================
-- OHLCV TABLES (One per timeframe for performance)
-- ===========================================

-- 1 Second OHLCV (aggregated from trades)
CREATE TABLE crypto.ohlcv_1s (
    id BIGSERIAL PRIMARY KEY,
    instrument_id INTEGER REFERENCES crypto.instruments(id),
    instrument VARCHAR(100) NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    open DECIMAL(20, 8) NOT NULL,
    high DECIMAL(20, 8) NOT NULL,
    low DECIMAL(20, 8) NOT NULL,
    close DECIMAL(20, 8) NOT NULL,
    volume DECIMAL(20, 8) NOT NULL,
    volume_usd DECIMAL(20, 2),
    trades_count INTEGER,
    source VARCHAR(50) DEFAULT 'deribit',
    collected_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(instrument, timestamp)
) PARTITION BY RANGE (timestamp);

-- Create monthly partitions for 1s data (very large)
CREATE TABLE crypto.ohlcv_1s_2024_01 PARTITION OF crypto.ohlcv_1s
    FOR VALUES FROM ('2024-01-01') TO ('2024-02-01');
CREATE TABLE crypto.ohlcv_1s_2024_02 PARTITION OF crypto.ohlcv_1s
    FOR VALUES FROM ('2024-02-01') TO ('2024-03-01');
CREATE TABLE crypto.ohlcv_1s_2024_03 PARTITION OF crypto.ohlcv_1s
    FOR VALUES FROM ('2024-03-01') TO ('2024-04-01');
CREATE TABLE crypto.ohlcv_1s_2024_04 PARTITION OF crypto.ohlcv_1s
    FOR VALUES FROM ('2024-04-01') TO ('2024-05-01');
CREATE TABLE crypto.ohlcv_1s_2024_05 PARTITION OF crypto.ohlcv_1s
    FOR VALUES FROM ('2024-05-01') TO ('2024-06-01');
CREATE TABLE crypto.ohlcv_1s_2024_06 PARTITION OF crypto.ohlcv_1s
    FOR VALUES FROM ('2024-06-01') TO ('2024-07-01');
CREATE TABLE crypto.ohlcv_1s_2024_07 PARTITION OF crypto.ohlcv_1s
    FOR VALUES FROM ('2024-07-01') TO ('2024-08-01');
CREATE TABLE crypto.ohlcv_1s_2024_08 PARTITION OF crypto.ohlcv_1s
    FOR VALUES FROM ('2024-08-01') TO ('2024-09-01');
CREATE TABLE crypto.ohlcv_1s_2024_09 PARTITION OF crypto.ohlcv_1s
    FOR VALUES FROM ('2024-09-01') TO ('2024-10-01');
CREATE TABLE crypto.ohlcv_1s_2024_10 PARTITION OF crypto.ohlcv_1s
    FOR VALUES FROM ('2024-10-01') TO ('2024-11-01');
CREATE TABLE crypto.ohlcv_1s_2024_11 PARTITION OF crypto.ohlcv_1s
    FOR VALUES FROM ('2024-11-01') TO ('2024-12-01');
CREATE TABLE crypto.ohlcv_1s_2024_12 PARTITION OF crypto.ohlcv_1s
    FOR VALUES FROM ('2024-12-01') TO ('2025-01-01');
CREATE TABLE crypto.ohlcv_1s_2025_01 PARTITION OF crypto.ohlcv_1s
    FOR VALUES FROM ('2025-01-01') TO ('2025-02-01');
CREATE TABLE crypto.ohlcv_1s_2025_02 PARTITION OF crypto.ohlcv_1s
    FOR VALUES FROM ('2025-02-01') TO ('2025-03-01');
CREATE TABLE crypto.ohlcv_1s_2025_03 PARTITION OF crypto.ohlcv_1s
    FOR VALUES FROM ('2025-03-01') TO ('2025-04-01');
CREATE TABLE crypto.ohlcv_1s_2025_04 PARTITION OF crypto.ohlcv_1s
    FOR VALUES FROM ('2025-04-01') TO ('2025-05-01');
CREATE TABLE crypto.ohlcv_1s_2025_05 PARTITION OF crypto.ohlcv_1s
    FOR VALUES FROM ('2025-05-01') TO ('2025-06-01');
CREATE TABLE crypto.ohlcv_1s_2025_06 PARTITION OF crypto.ohlcv_1s
    FOR VALUES FROM ('2025-06-01') TO ('2025-07-01');
CREATE TABLE crypto.ohlcv_1s_2025_07 PARTITION OF crypto.ohlcv_1s
    FOR VALUES FROM ('2025-07-01') TO ('2025-08-01');
CREATE TABLE crypto.ohlcv_1s_2025_08 PARTITION OF crypto.ohlcv_1s
    FOR VALUES FROM ('2025-08-01') TO ('2025-09-01');
CREATE TABLE crypto.ohlcv_1s_2025_09 PARTITION OF crypto.ohlcv_1s
    FOR VALUES FROM ('2025-09-01') TO ('2025-10-01');
CREATE TABLE crypto.ohlcv_1s_2025_10 PARTITION OF crypto.ohlcv_1s
    FOR VALUES FROM ('2025-10-01') TO ('2025-11-01');
CREATE TABLE crypto.ohlcv_1s_2025_11 PARTITION OF crypto.ohlcv_1s
    FOR VALUES FROM ('2025-11-01') TO ('2025-12-01');
CREATE TABLE crypto.ohlcv_1s_2025_12 PARTITION OF crypto.ohlcv_1s
    FOR VALUES FROM ('2025-12-01') TO ('2026-01-01');
CREATE TABLE crypto.ohlcv_1s_2026_01 PARTITION OF crypto.ohlcv_1s
    FOR VALUES FROM ('2026-01-01') TO ('2026-02-01');

CREATE INDEX idx_ohlcv_1s_instrument_ts ON crypto.ohlcv_1s(instrument, timestamp);
CREATE INDEX idx_ohlcv_1s_timestamp ON crypto.ohlcv_1s(timestamp);

-- 1 Minute OHLCV
CREATE TABLE crypto.ohlcv_1m (
    id BIGSERIAL PRIMARY KEY,
    instrument_id INTEGER REFERENCES crypto.instruments(id),
    instrument VARCHAR(100) NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    open DECIMAL(20, 8) NOT NULL,
    high DECIMAL(20, 8) NOT NULL,
    low DECIMAL(20, 8) NOT NULL,
    close DECIMAL(20, 8) NOT NULL,
    volume DECIMAL(20, 8) NOT NULL,
    volume_usd DECIMAL(20, 2),
    trades_count INTEGER,
    source VARCHAR(50) DEFAULT 'deribit',
    collected_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(instrument, timestamp)
);

CREATE INDEX idx_ohlcv_1m_instrument_ts ON crypto.ohlcv_1m(instrument, timestamp);
CREATE INDEX idx_ohlcv_1m_timestamp ON crypto.ohlcv_1m(timestamp);

-- 5 Minute OHLCV
CREATE TABLE crypto.ohlcv_5m (
    id BIGSERIAL PRIMARY KEY,
    instrument_id INTEGER REFERENCES crypto.instruments(id),
    instrument VARCHAR(100) NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    open DECIMAL(20, 8) NOT NULL,
    high DECIMAL(20, 8) NOT NULL,
    low DECIMAL(20, 8) NOT NULL,
    close DECIMAL(20, 8) NOT NULL,
    volume DECIMAL(20, 8) NOT NULL,
    volume_usd DECIMAL(20, 2),
    trades_count INTEGER,
    source VARCHAR(50) DEFAULT 'deribit',
    collected_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(instrument, timestamp)
);

CREATE INDEX idx_ohlcv_5m_instrument_ts ON crypto.ohlcv_5m(instrument, timestamp);
CREATE INDEX idx_ohlcv_5m_timestamp ON crypto.ohlcv_5m(timestamp);

-- 15 Minute OHLCV
CREATE TABLE crypto.ohlcv_15m (
    id BIGSERIAL PRIMARY KEY,
    instrument_id INTEGER REFERENCES crypto.instruments(id),
    instrument VARCHAR(100) NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    open DECIMAL(20, 8) NOT NULL,
    high DECIMAL(20, 8) NOT NULL,
    low DECIMAL(20, 8) NOT NULL,
    close DECIMAL(20, 8) NOT NULL,
    volume DECIMAL(20, 8) NOT NULL,
    volume_usd DECIMAL(20, 2),
    trades_count INTEGER,
    source VARCHAR(50) DEFAULT 'deribit',
    collected_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(instrument, timestamp)
);

CREATE INDEX idx_ohlcv_15m_instrument_ts ON crypto.ohlcv_15m(instrument, timestamp);
CREATE INDEX idx_ohlcv_15m_timestamp ON crypto.ohlcv_15m(timestamp);

-- 1 Hour OHLCV
CREATE TABLE crypto.ohlcv_1h (
    id BIGSERIAL PRIMARY KEY,
    instrument_id INTEGER REFERENCES crypto.instruments(id),
    instrument VARCHAR(100) NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    open DECIMAL(20, 8) NOT NULL,
    high DECIMAL(20, 8) NOT NULL,
    low DECIMAL(20, 8) NOT NULL,
    close DECIMAL(20, 8) NOT NULL,
    volume DECIMAL(20, 8) NOT NULL,
    volume_usd DECIMAL(20, 2),
    trades_count INTEGER,
    source VARCHAR(50) DEFAULT 'deribit',
    collected_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(instrument, timestamp)
);

CREATE INDEX idx_ohlcv_1h_instrument_ts ON crypto.ohlcv_1h(instrument, timestamp);
CREATE INDEX idx_ohlcv_1h_timestamp ON crypto.ohlcv_1h(timestamp);

-- 4 Hour OHLCV
CREATE TABLE crypto.ohlcv_4h (
    id BIGSERIAL PRIMARY KEY,
    instrument_id INTEGER REFERENCES crypto.instruments(id),
    instrument VARCHAR(100) NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    open DECIMAL(20, 8) NOT NULL,
    high DECIMAL(20, 8) NOT NULL,
    low DECIMAL(20, 8) NOT NULL,
    close DECIMAL(20, 8) NOT NULL,
    volume DECIMAL(20, 8) NOT NULL,
    volume_usd DECIMAL(20, 2),
    trades_count INTEGER,
    source VARCHAR(50) DEFAULT 'deribit',
    collected_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(instrument, timestamp)
);

CREATE INDEX idx_ohlcv_4h_instrument_ts ON crypto.ohlcv_4h(instrument, timestamp);
CREATE INDEX idx_ohlcv_4h_timestamp ON crypto.ohlcv_4h(timestamp);

-- 1 Day OHLCV
CREATE TABLE crypto.ohlcv_1d (
    id BIGSERIAL PRIMARY KEY,
    instrument_id INTEGER REFERENCES crypto.instruments(id),
    instrument VARCHAR(100) NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    open DECIMAL(20, 8) NOT NULL,
    high DECIMAL(20, 8) NOT NULL,
    low DECIMAL(20, 8) NOT NULL,
    close DECIMAL(20, 8) NOT NULL,
    volume DECIMAL(20, 8) NOT NULL,
    volume_usd DECIMAL(20, 2),
    trades_count INTEGER,
    source VARCHAR(50) DEFAULT 'deribit',
    collected_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(instrument, timestamp)
);

CREATE INDEX idx_ohlcv_1d_instrument_ts ON crypto.ohlcv_1d(instrument, timestamp);
CREATE INDEX idx_ohlcv_1d_timestamp ON crypto.ohlcv_1d(timestamp);

-- ===========================================
-- TRADES TABLE (Raw trade data for 1s aggregation)
-- ===========================================

CREATE TABLE crypto.trades (
    id BIGSERIAL PRIMARY KEY,
    instrument_id INTEGER REFERENCES crypto.instruments(id),
    instrument VARCHAR(100) NOT NULL,
    trade_id VARCHAR(100) NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    price DECIMAL(20, 8) NOT NULL,
    amount DECIMAL(20, 8) NOT NULL,
    direction VARCHAR(10), -- buy or sell
    tick_direction INTEGER, -- 0-3 for price movement
    liquidation BOOLEAN DEFAULT false,
    source VARCHAR(50) DEFAULT 'deribit',
    collected_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(instrument, trade_id)
) PARTITION BY RANGE (timestamp);

-- Create monthly partitions for trades
CREATE TABLE crypto.trades_2024_01 PARTITION OF crypto.trades
    FOR VALUES FROM ('2024-01-01') TO ('2024-02-01');
CREATE TABLE crypto.trades_2024_02 PARTITION OF crypto.trades
    FOR VALUES FROM ('2024-02-01') TO ('2024-03-01');
CREATE TABLE crypto.trades_2024_03 PARTITION OF crypto.trades
    FOR VALUES FROM ('2024-03-01') TO ('2024-04-01');
CREATE TABLE crypto.trades_2024_04 PARTITION OF crypto.trades
    FOR VALUES FROM ('2024-04-01') TO ('2024-05-01');
CREATE TABLE crypto.trades_2024_05 PARTITION OF crypto.trades
    FOR VALUES FROM ('2024-05-01') TO ('2024-06-01');
CREATE TABLE crypto.trades_2024_06 PARTITION OF crypto.trades
    FOR VALUES FROM ('2024-06-01') TO ('2024-07-01');
CREATE TABLE crypto.trades_2024_07 PARTITION OF crypto.trades
    FOR VALUES FROM ('2024-07-01') TO ('2024-08-01');
CREATE TABLE crypto.trades_2024_08 PARTITION OF crypto.trades
    FOR VALUES FROM ('2024-08-01') TO ('2024-09-01');
CREATE TABLE crypto.trades_2024_09 PARTITION OF crypto.trades
    FOR VALUES FROM ('2024-09-01') TO ('2024-10-01');
CREATE TABLE crypto.trades_2024_10 PARTITION OF crypto.trades
    FOR VALUES FROM ('2024-10-01') TO ('2024-11-01');
CREATE TABLE crypto.trades_2024_11 PARTITION OF crypto.trades
    FOR VALUES FROM ('2024-11-01') TO ('2024-12-01');
CREATE TABLE crypto.trades_2024_12 PARTITION OF crypto.trades
    FOR VALUES FROM ('2024-12-01') TO ('2025-01-01');
CREATE TABLE crypto.trades_2025_01 PARTITION OF crypto.trades
    FOR VALUES FROM ('2025-01-01') TO ('2025-02-01');
CREATE TABLE crypto.trades_2025_02 PARTITION OF crypto.trades
    FOR VALUES FROM ('2025-02-01') TO ('2025-03-01');
CREATE TABLE crypto.trades_2025_03 PARTITION OF crypto.trades
    FOR VALUES FROM ('2025-03-01') TO ('2025-04-01');
CREATE TABLE crypto.trades_2025_04 PARTITION OF crypto.trades
    FOR VALUES FROM ('2025-04-01') TO ('2025-05-01');
CREATE TABLE crypto.trades_2025_05 PARTITION OF crypto.trades
    FOR VALUES FROM ('2025-05-01') TO ('2025-06-01');
CREATE TABLE crypto.trades_2025_06 PARTITION OF crypto.trades
    FOR VALUES FROM ('2025-06-01') TO ('2025-07-01');
CREATE TABLE crypto.trades_2025_07 PARTITION OF crypto.trades
    FOR VALUES FROM ('2025-07-01') TO ('2025-08-01');
CREATE TABLE crypto.trades_2025_08 PARTITION OF crypto.trades
    FOR VALUES FROM ('2025-08-01') TO ('2025-09-01');
CREATE TABLE crypto.trades_2025_09 PARTITION OF crypto.trades
    FOR VALUES FROM ('2025-09-01') TO ('2025-10-01');
CREATE TABLE crypto.trades_2025_10 PARTITION OF crypto.trades
    FOR VALUES FROM ('2025-10-01') TO ('2025-11-01');
CREATE TABLE crypto.trades_2025_11 PARTITION OF crypto.trades
    FOR VALUES FROM ('2025-11-01') TO ('2025-12-01');
CREATE TABLE crypto.trades_2025_12 PARTITION OF crypto.trades
    FOR VALUES FROM ('2025-12-01') TO ('2026-01-01');
CREATE TABLE crypto.trades_2026_01 PARTITION OF crypto.trades
    FOR VALUES FROM ('2026-01-01') TO ('2026-02-01');

CREATE INDEX idx_trades_instrument_ts ON crypto.trades(instrument, timestamp);
CREATE INDEX idx_trades_timestamp ON crypto.trades(timestamp);

-- ===========================================
-- FUNDING RATES TABLE
-- ===========================================

CREATE TABLE crypto.funding_rates (
    id BIGSERIAL PRIMARY KEY,
    instrument_id INTEGER REFERENCES crypto.instruments(id),
    instrument VARCHAR(100) NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    funding_rate DECIMAL(20, 10) NOT NULL,
    mark_price DECIMAL(20, 8),
    index_price DECIMAL(20, 8),
    source VARCHAR(50) DEFAULT 'deribit',
    collected_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(instrument, timestamp)
);

CREATE INDEX idx_funding_instrument_ts ON crypto.funding_rates(instrument, timestamp);
CREATE INDEX idx_funding_timestamp ON crypto.funding_rates(timestamp);

-- ===========================================
-- COLLECTION LOG TABLE (Track collection progress)
-- ===========================================

CREATE TABLE crypto.collection_log (
    id SERIAL PRIMARY KEY,
    instrument VARCHAR(100) NOT NULL,
    data_type VARCHAR(50) NOT NULL, -- ohlcv_1s, ohlcv_1m, trades, funding
    source VARCHAR(50) NOT NULL,
    start_time TIMESTAMPTZ NOT NULL,
    end_time TIMESTAMPTZ NOT NULL,
    records_collected INTEGER NOT NULL,
    status VARCHAR(20) NOT NULL, -- success, failed, partial
    error_message TEXT,
    duration_seconds DECIMAL(10, 2),
    collected_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_collection_log_instrument ON crypto.collection_log(instrument);
CREATE INDEX idx_collection_log_type ON crypto.collection_log(data_type);
CREATE INDEX idx_collection_log_time ON crypto.collection_log(collected_at);

-- ===========================================
-- DATA GAPS TABLE (Track missing data)
-- ===========================================

CREATE TABLE crypto.data_gaps (
    id SERIAL PRIMARY KEY,
    instrument VARCHAR(100) NOT NULL,
    data_type VARCHAR(50) NOT NULL,
    gap_start TIMESTAMPTZ NOT NULL,
    gap_end TIMESTAMPTZ NOT NULL,
    expected_records INTEGER,
    detected_at TIMESTAMPTZ DEFAULT NOW(),
    filled_at TIMESTAMPTZ,
    status VARCHAR(20) DEFAULT 'detected' -- detected, filling, filled, unfillable
);

CREATE INDEX idx_data_gaps_instrument ON crypto.data_gaps(instrument);
CREATE INDEX idx_data_gaps_status ON crypto.data_gaps(status);

-- ===========================================
-- GRANT PERMISSIONS
-- ===========================================

-- Admin gets all permissions
GRANT ALL PRIVILEGES ON SCHEMA crypto TO crypto_admin;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA crypto TO crypto_admin;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA crypto TO crypto_admin;

-- Collector can insert, update, select
GRANT USAGE ON SCHEMA crypto TO crypto_collector;
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA crypto TO crypto_collector;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA crypto TO crypto_collector;

-- Analyst can only select
GRANT USAGE ON SCHEMA crypto TO crypto_analyst;
GRANT SELECT ON ALL TABLES IN SCHEMA crypto TO crypto_analyst;

-- API user can only select
GRANT USAGE ON SCHEMA crypto TO crypto_api;
GRANT SELECT ON ALL TABLES IN SCHEMA crypto TO crypto_api;

-- Set default privileges for future tables
ALTER DEFAULT PRIVILEGES IN SCHEMA crypto GRANT ALL ON TABLES TO crypto_admin;
ALTER DEFAULT PRIVILEGES IN SCHEMA crypto GRANT SELECT, INSERT, UPDATE ON TABLES TO crypto_collector;
ALTER DEFAULT PRIVILEGES IN SCHEMA crypto GRANT SELECT ON TABLES TO crypto_analyst;
ALTER DEFAULT PRIVILEGES IN SCHEMA crypto GRANT SELECT ON TABLES TO crypto_api;

ALTER DEFAULT PRIVILEGES IN SCHEMA crypto GRANT ALL ON SEQUENCES TO crypto_admin;
ALTER DEFAULT PRIVILEGES IN SCHEMA crypto GRANT USAGE, SELECT ON SEQUENCES TO crypto_collector;

-- ===========================================
-- USEFUL VIEWS
-- ===========================================

-- Latest prices view
CREATE OR REPLACE VIEW crypto.v_latest_prices AS
SELECT DISTINCT ON (instrument)
    instrument,
    timestamp,
    close as price,
    volume,
    source
FROM crypto.ohlcv_1m
ORDER BY instrument, timestamp DESC;

GRANT SELECT ON crypto.v_latest_prices TO crypto_analyst, crypto_api;

-- Data coverage summary view
CREATE OR REPLACE VIEW crypto.v_data_coverage AS
SELECT 
    instrument,
    data_type,
    MIN(timestamp) as earliest_data,
    MAX(timestamp) as latest_data,
    COUNT(*) as record_count,
    source
FROM (
    SELECT instrument, '1d' as data_type, timestamp, source FROM crypto.ohlcv_1d
    UNION ALL
    SELECT instrument, '1h' as data_type, timestamp, source FROM crypto.ohlcv_1h
    UNION ALL
    SELECT instrument, '15m' as data_type, timestamp, source FROM crypto.ohlcv_15m
    UNION ALL
    SELECT instrument, '5m' as data_type, timestamp, source FROM crypto.ohlcv_5m
    UNION ALL
    SELECT instrument, '1m' as data_type, timestamp, source FROM crypto.ohlcv_1m
) combined
GROUP BY instrument, data_type, source
ORDER BY instrument, data_type;

GRANT SELECT ON crypto.v_data_coverage TO crypto_analyst, crypto_api;

-- ===========================================
-- HELPER FUNCTIONS
-- ===========================================

-- Function to create new monthly partitions
CREATE OR REPLACE FUNCTION crypto.create_monthly_partition(
    table_name TEXT,
    partition_date DATE
)
RETURNS void AS $$
DECLARE
    partition_name TEXT;
    start_date DATE;
    end_date DATE;
BEGIN
    start_date := date_trunc('month', partition_date);
    end_date := start_date + interval '1 month';
    partition_name := table_name || '_' || to_char(partition_date, 'YYYY_MM');
    
    EXECUTE format(
        'CREATE TABLE IF NOT EXISTS crypto.%I PARTITION OF crypto.%I 
         FOR VALUES FROM (%L) TO (%L)',
        partition_name, table_name, start_date, end_date
    );
END;
$$ LANGUAGE plpgsql;

-- Function to upsert OHLCV data
CREATE OR REPLACE FUNCTION crypto.upsert_ohlcv(
    p_table TEXT,
    p_instrument TEXT,
    p_timestamp TIMESTAMPTZ,
    p_open DECIMAL,
    p_high DECIMAL,
    p_low DECIMAL,
    p_close DECIMAL,
    p_volume DECIMAL,
    p_volume_usd DECIMAL DEFAULT NULL,
    p_trades_count INTEGER DEFAULT NULL,
    p_source TEXT DEFAULT 'deribit'
)
RETURNS void AS $$
BEGIN
    EXECUTE format(
        'INSERT INTO crypto.%I (instrument, timestamp, open, high, low, close, volume, volume_usd, trades_count, source)
         VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
         ON CONFLICT (instrument, timestamp) 
         DO UPDATE SET 
            open = EXCLUDED.open,
            high = EXCLUDED.high,
            low = EXCLUDED.low,
            close = EXCLUDED.close,
            volume = EXCLUDED.volume,
            volume_usd = EXCLUDED.volume_usd,
            trades_count = EXCLUDED.trades_count,
            source = EXCLUDED.source,
            collected_at = NOW()',
        p_table
    ) USING p_instrument, p_timestamp, p_open, p_high, p_low, p_close, p_volume, p_volume_usd, p_trades_count, p_source;
END;
$$ LANGUAGE plpgsql;

GRANT EXECUTE ON FUNCTION crypto.create_monthly_partition TO crypto_admin;
GRANT EXECUTE ON FUNCTION crypto.upsert_ohlcv TO crypto_collector;

-- Done!
SELECT 'Database schema created successfully!' as message;


