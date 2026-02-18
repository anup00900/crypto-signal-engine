"""
Deribit Data Dashboard - Web UI
Multi-user access from anywhere (India, US, etc.)
"""

from flask import Flask, render_template, jsonify, request, send_file, Response
from flask_cors import CORS
import pandas as pd
import json
import os
import sys
from datetime import datetime, timedelta
from functools import wraps
import asyncio

# Add parent to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

app = Flask(__name__, 
            static_folder='static',
            template_folder='templates')
CORS(app)

# Configuration
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data_exports")
CURRENCIES = ["BTC", "ETH", "SOL"]

# =========================================================
# HELPER FUNCTIONS
# =========================================================

def load_csv(filename: str) -> pd.DataFrame:
    """Load CSV file from data directory"""
    filepath = os.path.join(DATA_DIR, filename)
    if os.path.exists(filepath):
        return pd.read_csv(filepath)
    return pd.DataFrame()


def get_available_files() -> dict:
    """List all available data files"""
    files = {}
    if os.path.exists(DATA_DIR):
        for f in os.listdir(DATA_DIR):
            if f.endswith('.csv'):
                filepath = os.path.join(DATA_DIR, f)
                size = os.path.getsize(filepath)
                mtime = datetime.fromtimestamp(os.path.getmtime(filepath))
                files[f] = {
                    "size_mb": round(size / 1024 / 1024, 2),
                    "modified": mtime.isoformat(),
                    "rows": len(pd.read_csv(filepath)) if size < 100_000_000 else "Large file"
                }
    return files


# =========================================================
# API ROUTES
# =========================================================

@app.route('/api/status')
def api_status():
    """Get system status"""
    files = get_available_files()
    return jsonify({
        "status": "online",
        "timestamp": datetime.utcnow().isoformat(),
        "data_directory": DATA_DIR,
        "files_count": len(files),
        "files": files
    })


@app.route('/api/instruments/<currency>')
def api_instruments(currency):
    """Get instruments for a currency"""
    df = load_csv(f"instruments_{currency}.csv")
    if df.empty:
        return jsonify({"error": "No data found"}), 404
    return jsonify(df.to_dict(orient='records'))


@app.route('/api/ohlcv/<instrument>/<timeframe>')
def api_ohlcv(instrument, timeframe):
    """Get OHLCV data"""
    # Try different filename patterns
    patterns = [
        f"ohlcv_{instrument}_{timeframe}.csv",
        f"ohlcv_{instrument.replace('-', '_')}_{timeframe}.csv"
    ]
    
    for pattern in patterns:
        df = load_csv(pattern)
        if not df.empty:
            # Limit to last N records for API
            limit = request.args.get('limit', 1000, type=int)
            df = df.tail(limit)
            return jsonify({
                "instrument": instrument,
                "timeframe": timeframe,
                "count": len(df),
                "data": df.to_dict(orient='records')
            })
            
    return jsonify({"error": "No data found"}), 404


@app.route('/api/options/surface/<currency>')
def api_options_surface(currency):
    """Get options surface data"""
    df = load_csv(f"options_surface_{currency}.csv")
    if df.empty:
        return jsonify({"error": "No data found"}), 404
        
    # Group by expiry for easier visualization
    result = {
        "currency": currency,
        "timestamp": df["timestamp"].iloc[0] if "timestamp" in df.columns else None,
        "underlying_price": df["underlying_price"].iloc[0] if "underlying_price" in df.columns else None,
        "expirations": {}
    }
    
    for expiry, group in df.groupby("expiry"):
        result["expirations"][expiry] = {
            "calls": group[group["option_type"] == "call"].to_dict(orient='records'),
            "puts": group[group["option_type"] == "put"].to_dict(orient='records')
        }
        
    return jsonify(result)


@app.route('/api/funding/<instrument>')
def api_funding(instrument):
    """Get funding rate history"""
    df = load_csv(f"funding_{instrument}.csv")
    if df.empty:
        return jsonify({"error": "No data found"}), 404
        
    limit = request.args.get('limit', 500, type=int)
    df = df.tail(limit)
    
    return jsonify({
        "instrument": instrument,
        "count": len(df),
        "data": df.to_dict(orient='records')
    })


@app.route('/api/open_interest')
def api_open_interest():
    """Get open interest data"""
    df = load_csv("open_interest.csv")
    if df.empty:
        return jsonify({"error": "No data found"}), 404
    return jsonify(df.to_dict(orient='records'))


@app.route('/api/basis')
def api_basis():
    """Get basis data"""
    df = load_csv("basis.csv")
    if df.empty:
        return jsonify({"error": "No data found"}), 404
    return jsonify(df.to_dict(orient='records'))


@app.route('/api/orderbook')
def api_orderbook():
    """Get orderbook snapshots"""
    df = load_csv("orderbook_snapshots.csv")
    if df.empty:
        return jsonify({"error": "No data found"}), 404
    return jsonify(df.to_dict(orient='records'))


@app.route('/api/dvol/<currency>')
def api_dvol(currency):
    """Get DVOL history"""
    df = load_csv(f"dvol_{currency}.csv")
    if df.empty:
        return jsonify({"error": "No data found"}), 404
        
    limit = request.args.get('limit', 500, type=int)
    df = df.tail(limit)
    
    return jsonify({
        "currency": currency,
        "count": len(df),
        "data": df.to_dict(orient='records')
    })


@app.route('/api/download/<filename>')
def api_download(filename):
    """Download a CSV file"""
    filepath = os.path.join(DATA_DIR, filename)
    if os.path.exists(filepath) and filename.endswith('.csv'):
        return send_file(filepath, as_attachment=True)
    return jsonify({"error": "File not found"}), 404


# =========================================================
# PAGE ROUTES
# =========================================================

@app.route('/')
def index():
    """Main dashboard"""
    return render_template('index.html')


@app.route('/options')
def options_page():
    """Options surface page"""
    return render_template('options.html')


@app.route('/funding')
def funding_page():
    """Funding rates page"""
    return render_template('funding.html')


@app.route('/data')
def data_page():
    """Data explorer page"""
    return render_template('data.html')


# =========================================================
# ERROR HANDLERS
# =========================================================

@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Not found"}), 404


@app.errorhandler(500)
def server_error(e):
    return jsonify({"error": "Server error"}), 500


# =========================================================
# MAIN
# =========================================================

if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='0.0.0.0', help='Host to bind to')
    parser.add_argument('--port', type=int, default=5000, help='Port to bind to')
    parser.add_argument('--debug', action='store_true', help='Debug mode')
    
    args = parser.parse_args()
    
    print(f"""
╔══════════════════════════════════════════════════════════════╗
║           DERIBIT DATA DASHBOARD                             ║
╠══════════════════════════════════════════════════════════════╣
║  Local:    http://localhost:{args.port}                           ║
║  Network:  http://<your-ip>:{args.port}                           ║
║                                                              ║
║  For remote access, share your public IP or use ngrok/ssh    ║
╚══════════════════════════════════════════════════════════════╝
    """)
    
    app.run(host=args.host, port=args.port, debug=args.debug)

