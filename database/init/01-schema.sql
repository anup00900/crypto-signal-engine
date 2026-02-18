-- =====================================================
-- DERIBIT DATA DATABASE SCHEMA
-- =====================================================
-- Initialized automatically when PostgreSQL starts
-- =====================================================

-- Enable TimescaleDB
CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;

-- =====================================================
-- 1. INSTRUMENTS
-- =====================================================
CREATE TABLE IF NOT EXISTS instruments (
    id SERIAL PRIMARY KEY,
    instrument_name VARCHAR(100) NOT NULL UNIQUE,
    kind VARCHAR(20) NOT NULL,
    base_currency VARCHAR(10) NOT NULL,
    quote_currency VARCHAR(10) DEFAULT 'USD',
    strike DECIMAL(20, 2),
    option_type VARCHAR(4),
    expiration_timestamp BIGINT,
    expiration_date DATE,
    tick_size DECIMAL(20, 10),
    min_trade_amount DECIMAL(20, 10),
    contract_size DECIMAL(20, 10),
    is_active BOOLEAN DEFAULT TRUE,
    raw_data JSONB,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_instruments_kind ON instruments(kind);
CREATE INDEX IF NOT EXISTS idx_instruments_base ON instruments(base_currency);
CREATE INDEX IF NOT EXISTS idx_instruments_expiration ON instruments(expiration_date);

-- =====================================================
-- 2. OHLCV DATA
-- =====================================================
CREATE TABLE IF NOT EXISTS ohlcv (
    time TIMESTAMPTZ NOT NULL,
    instrument_id INTEGER NOT NULL,
    timeframe VARCHAR(10) NOT NULL,
    open DECIMAL(20, 8) NOT NULL,
    high DECIMAL(20, 8) NOT NULL,
    low DECIMAL(20, 8) NOT NULL,
    close DECIMAL(20, 8) NOT NULL,
    volume DECIMAL(30, 8) NOT NULL,
    trades_count INTEGER,
    PRIMARY KEY (time, instrument_id, timeframe)
);

SELECT create_hypertable('ohlcv', 'time', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_ohlcv_instrument ON ohlcv(instrument_id, time DESC);

-- =====================================================
-- 3. ORDER BOOK SNAPSHOTS
-- =====================================================
CREATE TABLE IF NOT EXISTS order_book_snapshots (
    time TIMESTAMPTZ NOT NULL,
    instrument_id INTEGER NOT NULL,
    best_bid_price DECIMAL(20, 8),
    best_bid_amount DECIMAL(20, 8),
    best_ask_price DECIMAL(20, 8),
    best_ask_amount DECIMAL(20, 8),
    spread DECIMAL(20, 8),
    spread_percent DECIMAL(10, 6),
    mid_price DECIMAL(20, 8),
    bid_depth_5 DECIMAL(30, 8),
    ask_depth_5 DECIMAL(30, 8),
    bid_depth_10 DECIMAL(30, 8),
    ask_depth_10 DECIMAL(30, 8),
    bid_depth_20 DECIMAL(30, 8),
    ask_depth_20 DECIMAL(30, 8),
    bids JSONB,
    asks JSONB,
    imbalance_ratio DECIMAL(10, 6),
    PRIMARY KEY (time, instrument_id)
);

SELECT create_hypertable('order_book_snapshots', 'time', if_not_exists => TRUE);

-- =====================================================
-- 4. OPTIONS MARKET DATA (IV, Greeks)
-- =====================================================
CREATE TABLE IF NOT EXISTS options_market_data (
    time TIMESTAMPTZ NOT NULL,
    instrument_id INTEGER NOT NULL,
    mark_price DECIMAL(20, 10),
    underlying_price DECIMAL(20, 8),
    underlying_index VARCHAR(20),
    mark_iv DECIMAL(10, 4),
    bid_iv DECIMAL(10, 4),
    ask_iv DECIMAL(10, 4),
    delta DECIMAL(12, 8),
    gamma DECIMAL(12, 8),
    theta DECIMAL(12, 8),
    vega DECIMAL(12, 8),
    rho DECIMAL(12, 8),
    open_interest DECIMAL(30, 8),
    volume_24h DECIMAL(30, 8),
    PRIMARY KEY (time, instrument_id)
);

SELECT create_hypertable('options_market_data', 'time', if_not_exists => TRUE);

-- =====================================================
-- 5. OPTIONS SURFACE SNAPSHOTS
-- =====================================================
CREATE TABLE IF NOT EXISTS options_surface (
    time TIMESTAMPTZ NOT NULL,
    base_currency VARCHAR(10) NOT NULL,
    underlying_price DECIMAL(20, 8) NOT NULL,
    surface_data JSONB NOT NULL,
    atm_iv JSONB,
    skew_25d JSONB,
    skew_10d JSONB,
    term_structure JSONB,
    PRIMARY KEY (time, base_currency)
);

SELECT create_hypertable('options_surface', 'time', if_not_exists => TRUE);

-- =====================================================
-- 6. OPEN INTEREST
-- =====================================================
CREATE TABLE IF NOT EXISTS open_interest (
    time TIMESTAMPTZ NOT NULL,
    instrument_id INTEGER NOT NULL,
    open_interest DECIMAL(30, 8) NOT NULL,
    open_interest_usd DECIMAL(30, 2),
    oi_change_24h DECIMAL(30, 8),
    oi_change_percent_24h DECIMAL(10, 4),
    PRIMARY KEY (time, instrument_id)
);

SELECT create_hypertable('open_interest', 'time', if_not_exists => TRUE);

-- Aggregated OI
CREATE TABLE IF NOT EXISTS open_interest_aggregate (
    time TIMESTAMPTZ NOT NULL,
    base_currency VARCHAR(10) NOT NULL,
    kind VARCHAR(20) NOT NULL,
    total_oi DECIMAL(30, 8),
    total_oi_usd DECIMAL(30, 2),
    calls_oi DECIMAL(30, 8),
    puts_oi DECIMAL(30, 8),
    put_call_ratio DECIMAL(10, 4),
    PRIMARY KEY (time, base_currency, kind)
);

SELECT create_hypertable('open_interest_aggregate', 'time', if_not_exists => TRUE);

-- =====================================================
-- 7. FUNDING RATES
-- =====================================================
CREATE TABLE IF NOT EXISTS funding_rates (
    time TIMESTAMPTZ NOT NULL,
    instrument_id INTEGER NOT NULL,
    funding_rate DECIMAL(20, 10) NOT NULL,
    funding_rate_8h DECIMAL(20, 10),
    funding_rate_annualized DECIMAL(20, 10),
    index_price DECIMAL(20, 8),
    mark_price DECIMAL(20, 8),
    premium DECIMAL(20, 10),
    premium_percent DECIMAL(10, 6),
    PRIMARY KEY (time, instrument_id)
);

SELECT create_hypertable('funding_rates', 'time', if_not_exists => TRUE);

-- =====================================================
-- 8. BASIS
-- =====================================================
CREATE TABLE IF NOT EXISTS basis (
    time TIMESTAMPTZ NOT NULL,
    base_currency VARCHAR(10) NOT NULL,
    future_instrument_id INTEGER,
    spot_price DECIMAL(20, 8) NOT NULL,
    future_price DECIMAL(20, 8) NOT NULL,
    basis DECIMAL(20, 8),
    basis_percent DECIMAL(10, 6),
    basis_annualized DECIMAL(10, 4),
    days_to_expiry INTEGER,
    PRIMARY KEY (time, base_currency, future_instrument_id)
);

SELECT create_hypertable('basis', 'time', if_not_exists => TRUE);

-- =====================================================
-- 9. TRADES
-- =====================================================
CREATE TABLE IF NOT EXISTS trades (
    time TIMESTAMPTZ NOT NULL,
    instrument_id INTEGER NOT NULL,
    trade_id VARCHAR(50),
    price DECIMAL(20, 8) NOT NULL,
    amount DECIMAL(20, 8) NOT NULL,
    direction VARCHAR(4),
    tick_direction INTEGER,
    liquidation BOOLEAN DEFAULT FALSE,
    index_price DECIMAL(20, 8),
    PRIMARY KEY (time, instrument_id, trade_id)
);

SELECT create_hypertable('trades', 'time', if_not_exists => TRUE);

-- =====================================================
-- 10. VOLATILITY INDEX (DVOL)
-- =====================================================
CREATE TABLE IF NOT EXISTS volatility_index (
    time TIMESTAMPTZ NOT NULL,
    base_currency VARCHAR(10) NOT NULL,
    dvol DECIMAL(10, 4) NOT NULL,
    rv_7d DECIMAL(10, 4),
    rv_30d DECIMAL(10, 4),
    rv_90d DECIMAL(10, 4),
    vol_premium DECIMAL(10, 4),
    PRIMARY KEY (time, base_currency)
);

SELECT create_hypertable('volatility_index', 'time', if_not_exists => TRUE);

-- =====================================================
-- 11. INDEX PRICES
-- =====================================================
CREATE TABLE IF NOT EXISTS index_prices (
    time TIMESTAMPTZ NOT NULL,
    index_name VARCHAR(20) NOT NULL,
    price DECIMAL(20, 8) NOT NULL,
    PRIMARY KEY (time, index_name)
);

SELECT create_hypertable('index_prices', 'time', if_not_exists => TRUE);

-- =====================================================
-- 12. COLLECTION LOG
-- =====================================================
CREATE TABLE IF NOT EXISTS collection_log (
    id SERIAL PRIMARY KEY,
    collection_type VARCHAR(50) NOT NULL,
    instrument_name VARCHAR(100),
    base_currency VARCHAR(10),
    start_time TIMESTAMPTZ,
    end_time TIMESTAMPTZ,
    records_collected INTEGER,
    status VARCHAR(20),
    error_message TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

-- =====================================================
-- 13. USERS (for multi-user access)
-- =====================================================
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    email VARCHAR(100) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    role VARCHAR(20) DEFAULT 'viewer',
    is_active BOOLEAN DEFAULT TRUE,
    timezone VARCHAR(50) DEFAULT 'UTC',
    country VARCHAR(50),
    created_at TIMESTAMP DEFAULT NOW(),
    last_login TIMESTAMP
);

-- =====================================================
-- CREATE ROLES FOR MULTI-USER ACCESS
-- =====================================================

-- Read-only user (for analysts)
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'analyst') THEN
        CREATE ROLE analyst WITH LOGIN PASSWORD 'CHANGE_ME_IN_PRODUCTION';
    END IF;
END
$$;

GRANT CONNECT ON DATABASE deribit_data TO analyst;
GRANT USAGE ON SCHEMA public TO analyst;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO analyst;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO analyst;

-- Collector user (read-write for data collection)
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'collector') THEN
        CREATE ROLE collector WITH LOGIN PASSWORD 'CHANGE_ME_IN_PRODUCTION';
    END IF;
END
$$;

GRANT CONNECT ON DATABASE deribit_data TO collector;
GRANT USAGE ON SCHEMA public TO collector;
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO collector;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO collector;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE ON TABLES TO collector;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE ON SEQUENCES TO collector;

-- =====================================================
-- USEFUL VIEWS
-- =====================================================

-- Latest prices view
CREATE OR REPLACE VIEW v_latest_prices AS
SELECT DISTINCT ON (instrument_id)
    i.instrument_name,
    i.base_currency,
    o.time,
    o.close as price,
    o.volume
FROM ohlcv o
JOIN instruments i ON i.id = o.instrument_id
WHERE o.timeframe = '1m'
ORDER BY instrument_id, o.time DESC;

-- Options chain view  
CREATE OR REPLACE VIEW v_options_chain AS
SELECT 
    i.instrument_name,
    i.base_currency,
    i.strike,
    i.option_type,
    i.expiration_date,
    (i.expiration_date - CURRENT_DATE) as dte,
    o.mark_price,
    o.mark_iv,
    o.delta,
    o.gamma,
    o.theta,
    o.vega,
    o.open_interest,
    o.underlying_price,
    o.time as last_update
FROM instruments i
LEFT JOIN LATERAL (
    SELECT * FROM options_market_data 
    WHERE instrument_id = i.id 
    ORDER BY time DESC LIMIT 1
) o ON TRUE
WHERE i.kind = 'option' AND i.is_active = TRUE;

-- Current funding view
CREATE OR REPLACE VIEW v_current_funding AS
SELECT 
    i.instrument_name,
    i.base_currency,
    f.funding_rate,
    f.funding_rate_annualized,
    f.index_price,
    f.mark_price,
    f.premium_percent,
    f.time as last_update
FROM instruments i
LEFT JOIN LATERAL (
    SELECT * FROM funding_rates 
    WHERE instrument_id = i.id 
    ORDER BY time DESC LIMIT 1
) f ON TRUE
WHERE i.instrument_name LIKE '%-PERPETUAL';

RAISE NOTICE 'Database schema initialized successfully!';

