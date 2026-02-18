-- =====================================================
-- DERIBIT COMPREHENSIVE DATA SCHEMA
-- =====================================================
-- Data Types:
--   1. OHLCV (all timeframes)
--   2. Order Book Snapshots
--   3. Options Surface (IV, Skew, Term Structure)
--   4. Greeks (Delta, Gamma, Theta, Vega, Rho)
--   5. Open Interest
--   6. Funding Rates
--   7. Basis (Futures vs Spot)
-- =====================================================

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- =====================================================
-- 1. INSTRUMENTS TABLE (Base for all data)
-- =====================================================
CREATE TABLE IF NOT EXISTS instruments (
    id SERIAL PRIMARY KEY,
    instrument_name VARCHAR(100) NOT NULL UNIQUE,
    kind VARCHAR(20) NOT NULL, -- 'future', 'option', 'spot'
    base_currency VARCHAR(10) NOT NULL, -- 'BTC', 'ETH', 'SOL'
    quote_currency VARCHAR(10) DEFAULT 'USD',
    settlement_currency VARCHAR(10),
    
    -- Option specific fields
    strike DECIMAL(20, 2),
    option_type VARCHAR(4), -- 'call', 'put'
    
    -- Expiration
    expiration_timestamp BIGINT,
    expiration_date DATE,
    
    -- Contract specs
    tick_size DECIMAL(20, 10),
    min_trade_amount DECIMAL(20, 10),
    contract_size DECIMAL(20, 10),
    
    -- Status
    is_active BOOLEAN DEFAULT TRUE,
    creation_timestamp BIGINT,
    
    -- Metadata
    raw_data JSONB,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_instruments_kind ON instruments(kind);
CREATE INDEX idx_instruments_base ON instruments(base_currency);
CREATE INDEX idx_instruments_expiration ON instruments(expiration_date);
CREATE INDEX idx_instruments_option ON instruments(option_type, strike) WHERE kind = 'option';

-- =====================================================
-- 2. OHLCV DATA (Multiple timeframes)
-- =====================================================
CREATE TABLE IF NOT EXISTS ohlcv (
    time TIMESTAMPTZ NOT NULL,
    instrument_id INTEGER NOT NULL REFERENCES instruments(id),
    timeframe VARCHAR(10) NOT NULL, -- '1s', '1m', '5m', '15m', '1h', '4h', '1d'
    open DECIMAL(20, 8) NOT NULL,
    high DECIMAL(20, 8) NOT NULL,
    low DECIMAL(20, 8) NOT NULL,
    close DECIMAL(20, 8) NOT NULL,
    volume DECIMAL(30, 8) NOT NULL,
    trades_count INTEGER,
    PRIMARY KEY (time, instrument_id, timeframe)
);

-- Convert to TimescaleDB hypertable
SELECT create_hypertable('ohlcv', 'time', if_not_exists => TRUE);

CREATE INDEX idx_ohlcv_instrument ON ohlcv(instrument_id, time DESC);
CREATE INDEX idx_ohlcv_timeframe ON ohlcv(timeframe, time DESC);

-- =====================================================
-- 3. ORDER BOOK SNAPSHOTS
-- =====================================================
CREATE TABLE IF NOT EXISTS order_book_snapshots (
    time TIMESTAMPTZ NOT NULL,
    instrument_id INTEGER NOT NULL REFERENCES instruments(id),
    
    -- Best bid/ask
    best_bid_price DECIMAL(20, 8),
    best_bid_amount DECIMAL(20, 8),
    best_ask_price DECIMAL(20, 8),
    best_ask_amount DECIMAL(20, 8),
    
    -- Spread
    spread DECIMAL(20, 8),
    spread_percent DECIMAL(10, 6),
    mid_price DECIMAL(20, 8),
    
    -- Depth (aggregated)
    bid_depth_5 DECIMAL(30, 8), -- Total bid volume within 5 levels
    ask_depth_5 DECIMAL(30, 8),
    bid_depth_10 DECIMAL(30, 8),
    ask_depth_10 DECIMAL(30, 8),
    bid_depth_20 DECIMAL(30, 8),
    ask_depth_20 DECIMAL(30, 8),
    
    -- Full order book as JSONB (top 20 levels)
    bids JSONB, -- [[price, amount], ...]
    asks JSONB,
    
    -- Imbalance
    imbalance_ratio DECIMAL(10, 6), -- (bid_depth - ask_depth) / (bid_depth + ask_depth)
    
    PRIMARY KEY (time, instrument_id)
);

SELECT create_hypertable('order_book_snapshots', 'time', if_not_exists => TRUE);

CREATE INDEX idx_orderbook_instrument ON order_book_snapshots(instrument_id, time DESC);

-- =====================================================
-- 4. OPTIONS MARKET DATA (IV, Greeks)
-- =====================================================
CREATE TABLE IF NOT EXISTS options_market_data (
    time TIMESTAMPTZ NOT NULL,
    instrument_id INTEGER NOT NULL REFERENCES instruments(id),
    
    -- Price data
    mark_price DECIMAL(20, 10),
    underlying_price DECIMAL(20, 8),
    underlying_index VARCHAR(20), -- 'BTC-USD', 'ETH-USD'
    
    -- Implied Volatility
    mark_iv DECIMAL(10, 4), -- Mark IV as decimal (e.g., 0.65 = 65%)
    bid_iv DECIMAL(10, 4),
    ask_iv DECIMAL(10, 4),
    
    -- Greeks
    delta DECIMAL(12, 8),
    gamma DECIMAL(12, 8),
    theta DECIMAL(12, 8),
    vega DECIMAL(12, 8),
    rho DECIMAL(12, 8),
    
    -- Additional metrics
    interest_rate DECIMAL(10, 6),
    
    -- Open Interest & Volume
    open_interest DECIMAL(30, 8),
    volume_24h DECIMAL(30, 8),
    
    PRIMARY KEY (time, instrument_id)
);

SELECT create_hypertable('options_market_data', 'time', if_not_exists => TRUE);

CREATE INDEX idx_options_market_instrument ON options_market_data(instrument_id, time DESC);

-- =====================================================
-- 5. OPTIONS SURFACE SNAPSHOTS (IV Surface)
-- =====================================================
CREATE TABLE IF NOT EXISTS options_surface (
    time TIMESTAMPTZ NOT NULL,
    base_currency VARCHAR(10) NOT NULL, -- 'BTC', 'ETH'
    
    -- Underlying
    underlying_price DECIMAL(20, 8) NOT NULL,
    
    -- Surface data as JSONB
    -- Structure: {expiry: {strike: {call_iv, put_iv, call_delta, put_delta, ...}}}
    surface_data JSONB NOT NULL,
    
    -- Computed metrics
    atm_iv JSONB, -- {expiry: atm_iv} for each expiration
    skew_25d JSONB, -- {expiry: skew} 25-delta put IV - 25-delta call IV
    skew_10d JSONB, -- 10-delta skew
    
    -- Term structure
    term_structure JSONB, -- [{dte: X, atm_iv: Y}, ...]
    
    -- Volatility regime
    vol_of_vol DECIMAL(10, 4), -- Realized vol of IV
    
    PRIMARY KEY (time, base_currency)
);

SELECT create_hypertable('options_surface', 'time', if_not_exists => TRUE);

CREATE INDEX idx_surface_currency ON options_surface(base_currency, time DESC);

-- =====================================================
-- 6. OPEN INTEREST
-- =====================================================
CREATE TABLE IF NOT EXISTS open_interest (
    time TIMESTAMPTZ NOT NULL,
    instrument_id INTEGER NOT NULL REFERENCES instruments(id),
    
    open_interest DECIMAL(30, 8) NOT NULL,
    open_interest_usd DECIMAL(30, 2),
    
    -- Changes
    oi_change_24h DECIMAL(30, 8),
    oi_change_percent_24h DECIMAL(10, 4),
    
    PRIMARY KEY (time, instrument_id)
);

SELECT create_hypertable('open_interest', 'time', if_not_exists => TRUE);

CREATE INDEX idx_oi_instrument ON open_interest(instrument_id, time DESC);

-- Aggregated OI by currency
CREATE TABLE IF NOT EXISTS open_interest_aggregate (
    time TIMESTAMPTZ NOT NULL,
    base_currency VARCHAR(10) NOT NULL,
    kind VARCHAR(20) NOT NULL, -- 'future', 'option', 'perpetual'
    
    total_oi DECIMAL(30, 8),
    total_oi_usd DECIMAL(30, 2),
    
    -- Options breakdown
    calls_oi DECIMAL(30, 8),
    puts_oi DECIMAL(30, 8),
    put_call_ratio DECIMAL(10, 4),
    
    PRIMARY KEY (time, base_currency, kind)
);

SELECT create_hypertable('open_interest_aggregate', 'time', if_not_exists => TRUE);

-- =====================================================
-- 7. FUNDING RATES (Perpetuals)
-- =====================================================
CREATE TABLE IF NOT EXISTS funding_rates (
    time TIMESTAMPTZ NOT NULL,
    instrument_id INTEGER NOT NULL REFERENCES instruments(id),
    
    funding_rate DECIMAL(20, 10) NOT NULL, -- 8-hour funding rate
    funding_rate_8h DECIMAL(20, 10), -- Same as above
    funding_rate_annualized DECIMAL(20, 10), -- Annualized
    
    -- Index prices
    index_price DECIMAL(20, 8),
    mark_price DECIMAL(20, 8),
    
    -- Premium
    premium DECIMAL(20, 10),
    premium_percent DECIMAL(10, 6),
    
    PRIMARY KEY (time, instrument_id)
);

SELECT create_hypertable('funding_rates', 'time', if_not_exists => TRUE);

CREATE INDEX idx_funding_instrument ON funding_rates(instrument_id, time DESC);

-- =====================================================
-- 8. BASIS (Futures vs Spot)
-- =====================================================
CREATE TABLE IF NOT EXISTS basis (
    time TIMESTAMPTZ NOT NULL,
    base_currency VARCHAR(10) NOT NULL,
    future_instrument_id INTEGER REFERENCES instruments(id),
    
    -- Prices
    spot_price DECIMAL(20, 8) NOT NULL,
    future_price DECIMAL(20, 8) NOT NULL,
    
    -- Basis calculations
    basis DECIMAL(20, 8), -- future_price - spot_price
    basis_percent DECIMAL(10, 6), -- (future - spot) / spot * 100
    basis_annualized DECIMAL(10, 4), -- Annualized basis rate
    
    -- DTE for futures
    days_to_expiry INTEGER,
    
    PRIMARY KEY (time, base_currency, future_instrument_id)
);

SELECT create_hypertable('basis', 'time', if_not_exists => TRUE);

CREATE INDEX idx_basis_currency ON basis(base_currency, time DESC);

-- =====================================================
-- 9. TRADES (Tick Data)
-- =====================================================
CREATE TABLE IF NOT EXISTS trades (
    time TIMESTAMPTZ NOT NULL,
    instrument_id INTEGER NOT NULL REFERENCES instruments(id),
    trade_id VARCHAR(50),
    
    price DECIMAL(20, 8) NOT NULL,
    amount DECIMAL(20, 8) NOT NULL,
    direction VARCHAR(4), -- 'buy', 'sell'
    
    -- Trade details
    tick_direction INTEGER, -- 0-3
    liquidation BOOLEAN DEFAULT FALSE,
    
    -- Index price at trade time
    index_price DECIMAL(20, 8),
    
    PRIMARY KEY (time, instrument_id, trade_id)
);

SELECT create_hypertable('trades', 'time', if_not_exists => TRUE);

CREATE INDEX idx_trades_instrument ON trades(instrument_id, time DESC);

-- =====================================================
-- 10. VOLATILITY INDEX (DVOL)
-- =====================================================
CREATE TABLE IF NOT EXISTS volatility_index (
    time TIMESTAMPTZ NOT NULL,
    base_currency VARCHAR(10) NOT NULL, -- 'BTC', 'ETH'
    
    dvol DECIMAL(10, 4) NOT NULL, -- Deribit Volatility Index
    
    -- Historical vol comparison
    rv_7d DECIMAL(10, 4), -- 7-day realized vol
    rv_30d DECIMAL(10, 4), -- 30-day realized vol
    rv_90d DECIMAL(10, 4), -- 90-day realized vol
    
    -- Vol premium
    vol_premium DECIMAL(10, 4), -- DVOL - RV30
    
    PRIMARY KEY (time, base_currency)
);

SELECT create_hypertable('volatility_index', 'time', if_not_exists => TRUE);

-- =====================================================
-- 11. INDEX PRICES
-- =====================================================
CREATE TABLE IF NOT EXISTS index_prices (
    time TIMESTAMPTZ NOT NULL,
    index_name VARCHAR(20) NOT NULL, -- 'btc_usd', 'eth_usd', 'sol_usd'
    
    price DECIMAL(20, 8) NOT NULL,
    
    PRIMARY KEY (time, index_name)
);

SELECT create_hypertable('index_prices', 'time', if_not_exists => TRUE);

-- =====================================================
-- 12. DATA COLLECTION LOG
-- =====================================================
CREATE TABLE IF NOT EXISTS collection_log (
    id SERIAL PRIMARY KEY,
    collection_type VARCHAR(50) NOT NULL,
    instrument_name VARCHAR(100),
    base_currency VARCHAR(10),
    
    start_time TIMESTAMPTZ,
    end_time TIMESTAMPTZ,
    
    records_collected INTEGER,
    status VARCHAR(20), -- 'success', 'partial', 'failed'
    error_message TEXT,
    
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_collection_log_type ON collection_log(collection_type, created_at DESC);

-- =====================================================
-- 13. USERS TABLE (For multi-user access)
-- =====================================================
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    email VARCHAR(100) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    
    -- Access control
    role VARCHAR(20) DEFAULT 'viewer', -- 'admin', 'analyst', 'viewer'
    is_active BOOLEAN DEFAULT TRUE,
    
    -- Location/preferences
    timezone VARCHAR(50) DEFAULT 'UTC',
    country VARCHAR(50),
    
    created_at TIMESTAMP DEFAULT NOW(),
    last_login TIMESTAMP
);

-- =====================================================
-- VIEWS FOR COMMON QUERIES
-- =====================================================

-- Current Options Surface View
CREATE OR REPLACE VIEW v_current_options AS
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
JOIN LATERAL (
    SELECT * FROM options_market_data 
    WHERE instrument_id = i.id 
    ORDER BY time DESC LIMIT 1
) o ON TRUE
WHERE i.kind = 'option' AND i.is_active = TRUE;

-- Current Funding Rates View
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
JOIN LATERAL (
    SELECT * FROM funding_rates 
    WHERE instrument_id = i.id 
    ORDER BY time DESC LIMIT 1
) f ON TRUE
WHERE i.kind = 'future' AND i.instrument_name LIKE '%-PERPETUAL';

-- Current Basis View
CREATE OR REPLACE VIEW v_current_basis AS
SELECT 
    base_currency,
    days_to_expiry,
    spot_price,
    future_price,
    basis,
    basis_percent,
    basis_annualized,
    time as last_update
FROM basis
WHERE time > NOW() - INTERVAL '1 hour'
ORDER BY base_currency, days_to_expiry;

-- =====================================================
-- CONTINUOUS AGGREGATES (TimescaleDB)
-- =====================================================

-- Hourly OHLCV aggregation
CREATE MATERIALIZED VIEW IF NOT EXISTS ohlcv_hourly
WITH (timescaledb.continuous) AS
SELECT 
    time_bucket('1 hour', time) AS bucket,
    instrument_id,
    first(open, time) AS open,
    max(high) AS high,
    min(low) AS low,
    last(close, time) AS close,
    sum(volume) AS volume,
    sum(trades_count) AS trades_count
FROM ohlcv
WHERE timeframe = '1m'
GROUP BY bucket, instrument_id
WITH NO DATA;

-- Daily aggregation
CREATE MATERIALIZED VIEW IF NOT EXISTS ohlcv_daily
WITH (timescaledb.continuous) AS
SELECT 
    time_bucket('1 day', time) AS bucket,
    instrument_id,
    first(open, time) AS open,
    max(high) AS high,
    min(low) AS low,
    last(close, time) AS close,
    sum(volume) AS volume,
    sum(trades_count) AS trades_count
FROM ohlcv
WHERE timeframe = '1h'
GROUP BY bucket, instrument_id
WITH NO DATA;

-- =====================================================
-- RETENTION POLICIES
-- =====================================================
-- Keep tick data for 90 days
SELECT add_retention_policy('trades', INTERVAL '90 days', if_not_exists => TRUE);

-- Keep order book snapshots for 180 days  
SELECT add_retention_policy('order_book_snapshots', INTERVAL '180 days', if_not_exists => TRUE);

-- Keep everything else for 3 years
SELECT add_retention_policy('ohlcv', INTERVAL '3 years', if_not_exists => TRUE);
SELECT add_retention_policy('options_market_data', INTERVAL '3 years', if_not_exists => TRUE);
SELECT add_retention_policy('funding_rates', INTERVAL '3 years', if_not_exists => TRUE);

-- =====================================================
-- GRANT PERMISSIONS
-- =====================================================
-- Analyst role (read-only)
GRANT SELECT ON ALL TABLES IN SCHEMA public TO crypto_analyst;
GRANT SELECT ON ALL SEQUENCES IN SCHEMA public TO crypto_analyst;

-- Collector role (read-write for data)
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO crypto_collector;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO crypto_collector;

-- Admin role (full access)
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO crypto_admin;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO crypto_admin;

