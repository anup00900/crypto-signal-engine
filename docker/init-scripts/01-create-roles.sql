-- ===========================================
-- CREATE DATABASE ROLES AND USERS
-- ===========================================
-- This script runs automatically when the PostgreSQL container is first created

-- Create roles with different access levels
-- Note: Change these passwords in production!

-- Admin role - full access
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'crypto_admin') THEN
        CREATE ROLE crypto_admin WITH LOGIN PASSWORD 'CHANGE_ME_IN_PRODUCTION';
    END IF;
END
$$;

GRANT ALL PRIVILEGES ON DATABASE crypto_data TO crypto_admin;

-- Collector role - insert/update data
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'crypto_collector') THEN
        CREATE ROLE crypto_collector WITH LOGIN PASSWORD 'CHANGE_ME_IN_PRODUCTION';
    END IF;
END
$$;

GRANT CONNECT ON DATABASE crypto_data TO crypto_collector;

-- Analyst role - read-only for analysis
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'crypto_analyst') THEN
        CREATE ROLE crypto_analyst WITH LOGIN PASSWORD 'CHANGE_ME_IN_PRODUCTION';
    END IF;
END
$$;

GRANT CONNECT ON DATABASE crypto_data TO crypto_analyst;

-- API role - read-only for external applications  
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'crypto_api') THEN
        CREATE ROLE crypto_api WITH LOGIN PASSWORD 'CHANGE_ME_IN_PRODUCTION';
    END IF;
END
$$;

GRANT CONNECT ON DATABASE crypto_data TO crypto_api;

-- Create schema
CREATE SCHEMA IF NOT EXISTS crypto;

-- Grant schema permissions
GRANT ALL ON SCHEMA crypto TO crypto_admin;
GRANT USAGE ON SCHEMA crypto TO crypto_collector;
GRANT USAGE ON SCHEMA crypto TO crypto_analyst;
GRANT USAGE ON SCHEMA crypto TO crypto_api;

-- Set search path
ALTER DATABASE crypto_data SET search_path TO crypto, public;

SELECT 'Roles and schema created successfully!' as message;


