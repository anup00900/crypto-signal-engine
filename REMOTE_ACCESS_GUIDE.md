# 🌐 Remote Database Access Guide

Access the Deribit data from anywhere in the world (India, US, Europe, etc.)

---

## 📊 Access Credentials

### pgAdmin (Web Interface)
| Field | Value |
|-------|-------|
| URL | `http://YOUR_IP:5050` |
| Email | `admin@example.com` |
| Password | `(set in .env)` |

### PostgreSQL Direct Connection
| Field | Value |
|-------|-------|
| Host | `YOUR_IP` |
| Port | `5433` |
| Database | `deribit_data` |
| Username | `admin` |
| Password | `(set in .env)` |

### Read-Only User (for analysts)
| Field | Value |
|-------|-------|
| Username | `analyst` |
| Password | `(set in .env)` |

### Collector User (for data ingestion)
| Field | Value |
|-------|-------|
| Username | `collector` |
| Password | `(set in .env)` |

---

## 🖥️ Method 1: pgAdmin Web Interface (Easiest)

1. Open browser: `http://YOUR_HOST_IP:5050`
2. Login:
   - Email: `admin@example.com`
   - Password: `(set in .env)`
3. Connect to server "Deribit Data" (pre-configured)
4. Enter password when prompted: `(set in .env)`

**Browse tables:**
- `instruments` - All BTC/ETH options and futures
- `ohlcv` - Price candles (1m, 5m, 15m, 1h, 1d)
- `options_market_data` - IV, Greeks, OI
- `funding_rates` - Perpetual funding history
- `basis` - Futures vs spot spread
- `order_book_snapshots` - Market depth
- `volatility_index` - DVOL history

---

## 🐍 Method 2: Python Connection

```python
import psycopg2
import pandas as pd

# Connection settings
conn = psycopg2.connect(
    host="YOUR_HOST_IP",
    port=5433,
    database="deribit_data",
    user="analyst",  # read-only user
    password="(set in .env)"
)

# Query examples
df = pd.read_sql("""
    SELECT * FROM ohlcv 
    WHERE timeframe = '1h'
    ORDER BY time DESC 
    LIMIT 1000
""", conn)

# Get options surface
options = pd.read_sql("""
    SELECT * FROM v_options_chain 
    WHERE base_currency = 'BTC'
    AND dte BETWEEN 7 AND 30
""", conn)

# Get funding rates
funding = pd.read_sql("""
    SELECT * FROM v_current_funding
""", conn)

conn.close()
```

---

## 📊 Method 3: DBeaver / DataGrip

**Connection String:**
```
jdbc:postgresql://YOUR_HOST_IP:5433/deribit_data
```

**Settings:**
- Driver: PostgreSQL
- Host: YOUR_HOST_IP
- Port: 5433
- Database: deribit_data
- User: analyst
- Password: (set in .env)

---

## 🔧 Method 4: Command Line (psql)

```bash
# Connect directly
psql -h YOUR_HOST_IP -p 5433 -U analyst -d deribit_data

# Run query
psql -h YOUR_HOST_IP -p 5433 -U analyst -d deribit_data -c "SELECT * FROM instruments LIMIT 10"
```

---

## 🌍 Remote Access Setup (For Host Machine)

### Option A: Port Forwarding (Simple)

On your router:
1. Forward port `5050` (pgAdmin) to your machine
2. Forward port `5433` (PostgreSQL) to your machine
3. Share your public IP with remote users

### Option B: ngrok (No Router Access Needed)

```bash
# Install ngrok
brew install ngrok  # macOS

# Expose pgAdmin
ngrok http 5050

# Expose PostgreSQL  
ngrok tcp 5433
```

Share the ngrok URLs with remote users.

### Option C: SSH Tunnel (Most Secure)

Remote user runs:
```bash
# Create tunnel from their machine
ssh -L 5050:localhost:5050 -L 5433:localhost:5433 user@YOUR_HOST_IP

# Now they can access:
# pgAdmin: http://localhost:5050
# PostgreSQL: localhost:5433
```

### Option D: Tailscale (Best for Teams)

1. Install Tailscale on host and all client machines
2. Share Tailscale IP instead of public IP
3. No port forwarding needed, encrypted connection

---

## 📋 Available Views (Pre-built Queries)

```sql
-- Latest prices for all instruments
SELECT * FROM v_latest_prices;

-- Full options chain with Greeks
SELECT * FROM v_options_chain 
WHERE dte BETWEEN 0 AND 30
ORDER BY expiration_date, strike;

-- Current funding rates
SELECT * FROM v_current_funding;
```

---

## 📈 Database Tables

| Table | Description | Data |
|-------|-------------|------|
| `instruments` | All tradeable instruments | Options, Futures, Perpetuals |
| `ohlcv` | Price candles | Open, High, Low, Close, Volume |
| `options_market_data` | Options analytics | IV, Delta, Gamma, Theta, Vega, OI |
| `options_surface` | IV surface snapshots | Term structure, Skew |
| `funding_rates` | Perpetual funding | 8h rates, Premium |
| `basis` | Futures basis | Annualized carry |
| `open_interest` | Position sizes | By instrument |
| `order_book_snapshots` | Market depth | Top 20 levels |
| `volatility_index` | DVOL | Implied vol index |
| `trades` | Trade history | Tick data |
| `index_prices` | Spot prices | BTC, ETH, SOL |

---

## 🔐 Security Notes

1. **Change default passwords** before exposing to internet
2. Use `analyst` role for read-only access (safer)
3. Use SSH tunnels or VPN for sensitive data
4. Enable firewall rules to whitelist IPs

---

## ❓ Troubleshooting

**Can't connect remotely?**
- Check firewall allows ports 5050 and 5433
- Verify Docker containers are running: `docker ps`
- Check host machine IP: `curl ifconfig.me`

**Connection refused?**
- Ensure PostgreSQL is listening on all interfaces
- Check `docker logs deribit-postgres`

**Slow queries?**
- Add indexes for frequently filtered columns
- Use LIMIT for large result sets
- Use pre-built views for common queries

---

## 🚀 Quick Start for Remote Users

1. Get host IP from admin
2. Open `http://HOST_IP:5050` in browser
3. Login: `admin@example.com` / `(set in .env)`
4. Click "Deribit Data" server
5. Enter password: `(set in .env)`
6. Start querying!

**Need help?** Check the Query Tool in pgAdmin for easy SQL execution.

