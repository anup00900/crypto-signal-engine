# 🔴 pgAdmin COMPLETE STEP-BY-STEP GUIDE

## STEP 0: Make Sure Everything is Running

Open Terminal and run:
```bash
cd "/Users/anup/Downloads/Crypto Data Collector/crypto-data-collector"
docker ps
```

You should see:
```
deribit-postgres   Up   0.0.0.0:5433->5432
deribit-pgadmin    Up   0.0.0.0:5050->80
```

If NOT running, start with:
```bash
docker-compose up -d
```

---

## STEP 1: Open pgAdmin

1. Open your browser (Chrome/Firefox/Safari)
2. Go to: **http://localhost:5050**
3. Wait for page to fully load (may take 10-15 seconds first time)

---

## STEP 2: Add Server Connection

### Option A: Right-Click Method
1. Look at the LEFT panel
2. Find **"Servers"** (with a database icon)
3. **RIGHT-CLICK** on "Servers"
4. Click **"Register" → "Server..."**

### Option B: Menu Method
1. Click **"Object"** menu at the top
2. Click **"Register" → "Server..."**

---

## STEP 3: Fill in Server Details

A popup window will appear with tabs: **General | Connection | SSL | SSH Tunnel | Advanced**

### TAB 1: General
| Field | What to Enter |
|-------|--------------|
| **Name** | `Deribit Data` |

### TAB 2: Connection (CLICK THIS TAB!)
| Field | What to Enter |
|-------|--------------|
| **Host name/address** | `deribit-postgres` |
| **Port** | `5432` |
| **Maintenance database** | `deribit_data` |
| **Username** | `admin` |
| **Password** | `(set in .env)` |
| **Save password?** | ✅ YES (toggle ON) |

### TAB 3, 4, 5: SSL, SSH Tunnel, Advanced
**DON'T TOUCH THESE - Leave default**

---

## STEP 4: Click SAVE

Click the blue **"Save"** button at bottom right

---

## STEP 5: Success!

You should now see:
```
▼ Servers
   ▼ Deribit Data
      ▼ Databases
         ▼ deribit_data
            ▼ Schemas
               ▼ public
                  ▼ Tables
                     → instruments
                     → ohlcv
                     → options_market_data
                     → funding_rates
                     → basis
                     → order_book_snapshots
                     → etc...
```

---

## STEP 6: View Your Data

1. Expand **deribit_data** → **Schemas** → **public** → **Tables**
2. **RIGHT-CLICK** on any table (e.g., `ohlcv`)
3. Click **"View/Edit Data" → "All Rows"**

Your data will appear in a grid!

---

## STEP 7: Run SQL Queries

1. Click on **deribit_data** database
2. Click **"Tools"** menu → **"Query Tool"**
3. Type your SQL:
```sql
-- Get latest BTC prices
SELECT * FROM ohlcv 
WHERE instrument_id = 1 
ORDER BY time DESC 
LIMIT 100;
```
4. Press **F5** or click **▶ Execute** button

---

## 🔴 TROUBLESHOOTING

### "Connection Refused" Error
The host should be `deribit-postgres` (the Docker container name), NOT `localhost`

### "Authentication Failed" Error
Password is exactly: `(set in .env)`

### "Server Not Found" Error
Check Docker is running:
```bash
docker ps
```

### pgAdmin Won't Load
Wait 30 seconds. It's slow on first load. If still nothing:
```bash
docker-compose restart pgadmin
```

---

## 📋 QUICK COPY-PASTE VALUES

```
Name:        Deribit Data
Host:        deribit-postgres
Port:        5432
Database:    deribit_data
Username:    admin
Password:    (set in .env)
```

---

## 🌐 FOR REMOTE USERS (India/US/etc)

If accessing from ANOTHER COMPUTER:

| Field | Value |
|-------|-------|
| **Host** | `YOUR_IP_ADDRESS` (not deribit-postgres) |
| **Port** | `5433` (note: 5433, not 5432) |
| **Database** | `deribit_data` |
| **Username** | `analyst` |
| **Password** | `(set in .env)` |

Get your IP:
```bash
curl ifconfig.me
```

