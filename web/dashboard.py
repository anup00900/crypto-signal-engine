"""
Crypto Signal Engine — Web Dashboard

Single-file Flask app that reads signal data from S3
(same backend as the MCP server) and renders a dark
trading-terminal UI with Chart.js charts.

Usage:
    python3 web/dashboard.py
    # Opens at http://localhost:8080
"""

import io
import json
import os
from datetime import datetime, timezone
from typing import Optional

import boto3
import pandas as pd
from botocore.exceptions import ClientError
from flask import Flask, jsonify, request

# ── Config ──────────────────────────────────────────────────
S3_BUCKET = os.environ.get("S3_BUCKET", "crypto-collector-prod-data-720428162886")
AWS_REGION = os.environ.get("AWS_REGION", "eu-north-1")
S3_PREFIX = "signals"

s3 = boto3.client("s3", region_name=AWS_REGION)
app = Flask(__name__)


# ── S3 helpers ──────────────────────────────────────────────

def _read_json(key: str) -> dict:
    try:
        resp = s3.get_object(Bucket=S3_BUCKET, Key=key)
        return json.loads(resp["Body"].read().decode())
    except ClientError as e:
        if e.response["Error"]["Code"] in ("NoSuchKey", "404"):
            return {"error": f"Not found: {key}"}
        raise


def _read_parquet(key: str, tail: int = 0) -> Optional[pd.DataFrame]:
    try:
        resp = s3.get_object(Bucket=S3_BUCKET, Key=key)
        df = pd.read_parquet(io.BytesIO(resp["Body"].read()))
        if tail:
            df = df.tail(tail)
        return df
    except ClientError as e:
        if e.response["Error"]["Code"] in ("NoSuchKey", "404"):
            return None
        raise


def _df_to_records(df: pd.DataFrame, symbol: str = "") -> list:
    if df is None or df.empty:
        return []
    if symbol:
        symbol = symbol.upper()
        if "symbol" in df.columns:
            df = df[df["symbol"] == symbol]
    for col in df.select_dtypes(include=["datetime64", "datetimetz"]).columns:
        df = df.copy()
        df[col] = df[col].astype(str)
    return json.loads(df.to_json(orient="records", default_handler=str))


# ── API routes ──────────────────────────────────────────────

@app.route("/api/signals")
def api_signals():
    data = _read_json(f"{S3_PREFIX}/signals_latest.json")
    return jsonify(data)


@app.route("/api/candles")
def api_candles():
    symbol = request.args.get("symbol", "BTCUSDT").upper()
    count = min(int(request.args.get("count", 60)), 500)
    df = _read_parquet(f"{S3_PREFIX}/candles_1m_rolling.parquet")
    rows = _df_to_records(df, symbol)
    return jsonify(rows[-count:])


@app.route("/api/volume_profile")
def api_volume_profile():
    data = _read_json(f"{S3_PREFIX}/volume_profile.json")
    return jsonify(data)


@app.route("/api/derivatives")
def api_derivatives():
    symbol = request.args.get("symbol", "").upper()
    df = _read_parquet(f"{S3_PREFIX}/derivatives_rolling.parquet")
    rows = _df_to_records(df, symbol)
    return jsonify(rows[-60:])


@app.route("/api/positioning")
def api_positioning():
    symbol = request.args.get("symbol", "").upper()
    df = _read_parquet(f"{S3_PREFIX}/liquidations_rolling.parquet")
    rows = _df_to_records(df, symbol)
    return jsonify(rows[-60:])


@app.route("/api/trades")
def api_trades():
    data = _read_json(f"{S3_PREFIX}/trades_executed.json")
    if isinstance(data, dict) and "trades" in data:
        return jsonify(data["trades"])
    if isinstance(data, list):
        return jsonify(data)
    return jsonify([])


@app.route("/api/status")
def api_status():
    info = {"bucket": S3_BUCKET, "region": AWS_REGION, "ts": datetime.now(timezone.utc).isoformat()}
    # buffer sizes
    for name, key in [
        ("candles", f"{S3_PREFIX}/candles_1m_rolling.parquet"),
        ("derivatives", f"{S3_PREFIX}/derivatives_rolling.parquet"),
        ("positioning", f"{S3_PREFIX}/liquidations_rolling.parquet"),
    ]:
        try:
            meta = s3.head_object(Bucket=S3_BUCKET, Key=key)
            info[name] = {
                "size_kb": round(meta["ContentLength"] / 1024, 1),
                "last_modified": meta["LastModified"].isoformat(),
            }
        except ClientError:
            info[name] = {"size_kb": 0, "last_modified": None}
    return jsonify(info)


# ── Dashboard HTML ──────────────────────────────────────────

DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Crypto Signal Engine</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js"></script>
<style>
*{margin:0;padding:0;box-sizing:border-box}
:root{
  --bg:#0d1117;--bg2:#161b22;--bg3:#1c2333;
  --border:#30363d;--text:#c9d1d9;--dim:#8b949e;
  --green:#3fb950;--red:#f85149;--yellow:#d29922;
  --blue:#58a6ff;--purple:#bc8cff;--cyan:#39d2c0;
}
body{background:var(--bg);color:var(--text);font-family:'JetBrains Mono','SF Mono','Fira Code',monospace;font-size:13px;line-height:1.5}
a{color:var(--blue);text-decoration:none}

/* Header */
.header{display:flex;align-items:center;justify-content:space-between;padding:12px 20px;background:var(--bg2);border-bottom:1px solid var(--border)}
.header h1{font-size:16px;font-weight:600;letter-spacing:1px}
.header .status{display:flex;align-items:center;gap:8px;font-size:12px;color:var(--dim)}
.header .dot{width:8px;height:8px;border-radius:50%;background:var(--green);display:inline-block}
.header .dot.stale{background:var(--yellow)}
.header .dot.dead{background:var(--red)}

/* Symbol tabs */
.tabs{display:flex;gap:2px;padding:8px 20px;background:var(--bg2);border-bottom:1px solid var(--border)}
.tab{padding:6px 16px;border-radius:6px 6px 0 0;cursor:pointer;color:var(--dim);font-size:12px;font-weight:600;letter-spacing:.5px;transition:all .15s}
.tab:hover{color:var(--text);background:var(--bg3)}
.tab.active{color:var(--text);background:var(--bg);border:1px solid var(--border);border-bottom-color:var(--bg)}

/* Grid */
.grid{display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;padding:16px 20px}
.grid .wide{grid-column:span 2}
.grid .full{grid-column:span 3}
@media(max-width:1200px){.grid{grid-template-columns:1fr 1fr}.grid .wide,.grid .full{grid-column:span 2}}
@media(max-width:768px){.grid{grid-template-columns:1fr}.grid .wide,.grid .full{grid-column:span 1}}

/* Card */
.card{background:var(--bg2);border:1px solid var(--border);border-radius:8px;overflow:hidden}
.card-head{padding:10px 14px;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:1px;color:var(--dim);border-bottom:1px solid var(--border);display:flex;justify-content:space-between;align-items:center}
.card-body{padding:14px}

/* TDS Gauge */
.gauge-row{display:flex;gap:16px;flex-wrap:wrap;justify-content:center}
.gauge{text-align:center;min-width:100px}
.gauge-val{font-size:36px;font-weight:700;line-height:1}
.gauge-label{font-size:11px;color:var(--dim);margin-top:4px;text-transform:uppercase;letter-spacing:.5px}
.gauge-bar{height:4px;border-radius:2px;margin-top:6px;background:var(--border)}
.gauge-bar-fill{height:100%;border-radius:2px;transition:width .5s}

/* KV rows */
.kv{display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px solid var(--border)}
.kv:last-child{border-bottom:none}
.kv-key{color:var(--dim);font-size:12px}
.kv-val{font-weight:600;font-size:12px}

/* Entry badge */
.badge{display:inline-block;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:700;letter-spacing:.5px}
.badge-long{background:rgba(63,185,80,.15);color:var(--green);border:1px solid rgba(63,185,80,.3)}
.badge-short{background:rgba(248,81,73,.15);color:var(--red);border:1px solid rgba(248,81,73,.3)}
.badge-neutral{background:rgba(139,148,158,.15);color:var(--dim);border:1px solid rgba(139,148,158,.3)}
.badge-entry{background:rgba(63,185,80,.2);color:var(--green);border:1px solid var(--green)}
.badge-no{background:rgba(248,81,73,.1);color:var(--dim);border:1px solid var(--border)}

/* Table */
.tbl{width:100%;border-collapse:collapse;font-size:12px}
.tbl th{text-align:left;padding:6px 8px;color:var(--dim);font-weight:600;border-bottom:1px solid var(--border);font-size:11px;text-transform:uppercase;letter-spacing:.5px;position:sticky;top:0;background:var(--bg2)}
.tbl td{padding:5px 8px;border-bottom:1px solid var(--border)}
.tbl tbody tr:hover{background:var(--bg3)}
.scroll-y{max-height:300px;overflow-y:auto}

/* Chart container */
.chart-wrap{position:relative;height:220px}

/* Colors */
.c-green{color:var(--green)}.c-red{color:var(--red)}.c-yellow{color:var(--yellow)}.c-blue{color:var(--blue)}.c-dim{color:var(--dim)}

/* Footer */
.footer{padding:12px 20px;text-align:center;font-size:11px;color:var(--dim);border-top:1px solid var(--border);margin-top:8px}

/* Loading skeleton */
.loading{color:var(--dim);font-size:12px;padding:20px;text-align:center}
</style>
</head>
<body>

<div class="header">
  <h1>CRYPTO SIGNAL ENGINE</h1>
  <div class="status">
    <span class="dot" id="statusDot"></span>
    <span id="statusText">Connecting...</span>
    <span style="margin-left:12px" id="clockText"></span>
  </div>
</div>

<div class="tabs" id="symbolTabs"></div>

<div class="grid" id="dashboard">
  <div class="loading">Loading signal data...</div>
</div>

<div class="footer">
  Signal Engine Dashboard &mdash; S3: <span id="footerBucket"></span> &mdash; Auto-refresh 60s
</div>

<script>
// ── State ──
let CURRENT_SYMBOL = 'BTCUSDT';
let SIGNALS = {};
let radarChart = null;
let volProfileChart = null;
let posChart = null;

// ── Helpers ──
const $ = s => document.querySelector(s);
const $$ = s => document.querySelectorAll(s);

function fmt(n, d=2) {
  if (n == null || isNaN(n)) return '—';
  return Number(n).toFixed(d);
}
function fmtPrice(n) {
  if (n == null || isNaN(n)) return '—';
  n = Number(n);
  if (n > 1000) return n.toLocaleString('en-US', {minimumFractionDigits:2, maximumFractionDigits:2});
  return n.toFixed(4);
}
function scoreColor(v) {
  if (v == null) return 'var(--dim)';
  if (v >= 70) return 'var(--green)';
  if (v >= 45) return 'var(--yellow)';
  return 'var(--red)';
}
function dirBadge(dir, entry) {
  if (entry) {
    if (dir === 1) return '<span class="badge badge-long">LONG</span>';
    if (dir === -1) return '<span class="badge badge-short">SHORT</span>';
  }
  if (dir === 1) return '<span class="badge badge-neutral">LONG</span>';
  if (dir === -1) return '<span class="badge badge-neutral">SHORT</span>';
  return '<span class="badge badge-neutral">—</span>';
}
function entryBadge(ok) {
  return ok
    ? '<span class="badge badge-entry">ENTRY OK</span>'
    : '<span class="badge badge-no">NO ENTRY</span>';
}
function deltaColor(v) {
  if (v == null) return '';
  return Number(v) >= 0 ? 'c-green' : 'c-red';
}
function timeAgo(ts) {
  if (!ts) return '—';
  const diff = (Date.now() - new Date(ts).getTime()) / 1000;
  if (diff < 60) return Math.floor(diff) + 's ago';
  if (diff < 3600) return Math.floor(diff/60) + 'm ago';
  return Math.floor(diff/3600) + 'h ago';
}

// ── API fetch ──
async function api(path) {
  try {
    const r = await fetch(path);
    if (!r.ok) return null;
    return await r.json();
  } catch { return null; }
}

// ── Render tabs ──
function renderTabs(symbols) {
  const el = $('#symbolTabs');
  el.innerHTML = symbols.map(s =>
    `<div class="tab${s===CURRENT_SYMBOL?' active':''}" onclick="switchSymbol('${s}')">${s.replace('USDT','')}/USDT</div>`
  ).join('') + '<div class="tab" onclick="switchSymbol(\'ALL\')">ALL</div>';
}
const KNOWN_SYMBOLS = ['BTCUSDT','ETHUSDT'];

function switchSymbol(s) {
  CURRENT_SYMBOL = s;
  const hasSignals = Object.keys(SIGNALS).length > 0;
  if (hasSignals) {
    renderAll();
  } else {
    renderWaiting();
  }
}

// ── Render dashboard ──
function renderAll() {
  const syms = Object.keys(SIGNALS).length > 0 ? Object.keys(SIGNALS) : KNOWN_SYMBOLS;
  renderTabs(syms);
  if (CURRENT_SYMBOL === 'ALL') {
    renderAllSymbols();
  } else {
    renderSymbol(CURRENT_SYMBOL);
  }
}

function renderAllSymbols() {
  const grid = $('#dashboard');
  let html = '';
  const syms = Object.keys(SIGNALS).length > 0 ? Object.keys(SIGNALS) : KNOWN_SYMBOLS;
  // If no signals, render waiting panels for each symbol
  if (Object.keys(SIGNALS).length === 0) {
    renderWaitingAll();
    return;
  }
  for (const sym of syms) {
    const sig = SIGNALS[sym];
    html += renderSignalCard(sym, sig);
  }
  grid.innerHTML = html;
  // No charts in ALL mode – keep it simple
}

function renderSymbol(sym) {
  const sig = SIGNALS[sym];
  if (!sig) {
    $('#dashboard').innerHTML = '<div class="loading">No data for ' + sym + '</div>';
    return;
  }
  const grid = $('#dashboard');
  grid.innerHTML = `
    ${renderSignalCard(sym, sig)}
    <div class="card" id="radarCard">
      <div class="card-head">Score Radar</div>
      <div class="card-body"><div class="chart-wrap"><canvas id="radarCanvas"></canvas></div></div>
    </div>
    <div class="card" id="derivCard">
      <div class="card-head">Derivatives <span class="c-dim" id="derivTs"></span></div>
      <div class="card-body" id="derivBody"><div class="loading">Loading...</div></div>
    </div>
    <div class="card" id="tpCard">
      <div class="card-head">TP / Invalidation</div>
      <div class="card-body">${renderTPCard(sig)}</div>
    </div>
    <div class="card" id="vpCard">
      <div class="card-head">Volume Profile</div>
      <div class="card-body"><div class="chart-wrap"><canvas id="vpCanvas"></canvas></div></div>
    </div>
    <div class="card" id="posCard">
      <div class="card-head">Positioning</div>
      <div class="card-body"><div class="chart-wrap"><canvas id="posCanvas"></canvas></div></div>
    </div>
    <div class="card wide" id="candleCard">
      <div class="card-head">Recent Candles (1m) <span class="c-dim">Last 20</span></div>
      <div class="card-body scroll-y" id="candleBody"><div class="loading">Loading...</div></div>
    </div>
    <div class="card" id="tradeCard">
      <div class="card-head">Trade Journal</div>
      <div class="card-body scroll-y" id="tradeBody"><div class="loading">Loading...</div></div>
    </div>
    <div class="card" id="reasonCard">
      <div class="card-head">Diagnostics</div>
      <div class="card-body">${renderReason(sig)}</div>
    </div>
  `;
  // Async panel loads
  loadRadar(sig);
  loadDerivatives(sym);
  loadVolumeProfile(sym);
  loadPositioning(sym);
  loadCandles(sym);
  loadTrades();
}

// ── Signal card ──
function renderSignalCard(sym, sig) {
  const tds = sig.tds != null ? sig.tds : 0;
  const scores = [
    {k:'VEP',v:sig.vep,w:.22},{k:'SCI',v:sig.sci,w:.20},{k:'LCS',v:sig.lcs,w:.18},
    {k:'FLOW',v:sig.flow,w:.12},{k:'DPS',v:sig.dps,w:.10},{k:'GRAV',v:sig.grav,w:.10},{k:'CAP',v:sig.cap,w:.08}
  ];
  return `
  <div class="card">
    <div class="card-head">${sym} ${entryBadge(sig.entry_ok)} ${dirBadge(sig.direction, sig.entry_ok)}</div>
    <div class="card-body">
      <div class="gauge-row">
        <div class="gauge">
          <div class="gauge-val" style="color:${scoreColor(tds)}">${fmt(tds,1)}</div>
          <div class="gauge-label">TDS</div>
          <div class="gauge-bar"><div class="gauge-bar-fill" style="width:${Math.min(tds,100)}%;background:${scoreColor(tds)}"></div></div>
        </div>
      </div>
      <div style="margin-top:12px">
        ${scores.map(s => `
        <div class="kv">
          <span class="kv-key">${s.k} <span class="c-dim">(${(s.w*100).toFixed(0)}%)</span></span>
          <span class="kv-val" style="color:${scoreColor(s.v)}">${fmt(s.v,1)}</span>
        </div>`).join('')}
      </div>
      <div style="margin-top:8px;text-align:center;font-size:12px;color:var(--dim)">
        Price: <span style="color:var(--text);font-weight:600">${fmtPrice(sig.price)}</span>
        &nbsp;|&nbsp; ${timeAgo(sig.ts)}
      </div>
    </div>
  </div>`;
}

// ── TP card ──
function renderTPCard(sig) {
  return `
    <div class="kv"><span class="kv-key">TP1</span><span class="kv-val c-green">${fmtPrice(sig.tp1)}</span></div>
    <div class="kv"><span class="kv-key">TP2</span><span class="kv-val c-green">${fmtPrice(sig.tp2)}</span></div>
    <div class="kv"><span class="kv-key">TP3</span><span class="kv-val c-green">${fmtPrice(sig.tp3)}</span></div>
    <div class="kv"><span class="kv-key">Invalidation</span><span class="kv-val c-red">${fmtPrice(sig.inval)}</span></div>
    <div class="kv"><span class="kv-key">SCI Dir</span><span class="kv-val">${sig.sci_dir === 1 ? '<span class="c-green">Bullish</span>' : sig.sci_dir === -1 ? '<span class="c-red">Bearish</span>' : '<span class="c-dim">None</span>'}</span></div>
  `;
}

// ── Diagnostics ──
function renderReason(sig) {
  const r = sig.reason || {};
  return `
    <div class="kv"><span class="kv-key">Compression</span><span class="kv-val">${fmt(r.compression,3)}</span></div>
    <div class="kv"><span class="kv-key">Activity</span><span class="kv-val">${fmt(r.activity,3)}</span></div>
    <div class="kv"><span class="kv-key">Noise</span><span class="kv-val">${fmt(r.noise,6)}</span></div>
    <div class="kv"><span class="kv-key">SCI Dir</span><span class="kv-val">${r.sci_dir || '—'}</span></div>
  `;
}

// ── Radar chart ──
function loadRadar(sig) {
  const ctx = document.getElementById('radarCanvas');
  if (!ctx) return;
  if (radarChart) radarChart.destroy();
  const labels = ['VEP','SCI','LCS','FLOW','DPS','GRAV','CAP'];
  const values = [sig.vep,sig.sci,sig.lcs,sig.flow,sig.dps,sig.grav,sig.cap].map(v=>v||0);
  radarChart = new Chart(ctx, {
    type: 'radar',
    data: {
      labels,
      datasets: [{
        label: 'Score',
        data: values,
        backgroundColor: 'rgba(88,166,255,0.15)',
        borderColor: 'rgba(88,166,255,0.8)',
        borderWidth: 2,
        pointBackgroundColor: values.map(v=>scoreColor(v)),
        pointRadius: 4,
      }]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      scales: {
        r: {
          min: 0, max: 100,
          ticks: { stepSize:25, color:'#8b949e', backdropColor:'transparent', font:{size:10} },
          grid: { color:'#30363d' },
          pointLabels: { color:'#c9d1d9', font:{size:11,weight:'bold'} },
          angleLines: { color:'#30363d' }
        }
      },
      plugins: { legend: { display:false } }
    }
  });
}

// ── Derivatives ──
async function loadDerivatives(sym) {
  const rows = await api('/api/derivatives?symbol=' + sym);
  const el = $('#derivBody');
  if (!rows || !rows.length) { el.innerHTML = '<span class="c-dim">No data</span>'; return; }
  const last = rows[rows.length - 1];
  $('#derivTs').textContent = timeAgo(last.ts);
  el.innerHTML = `
    <div class="kv"><span class="kv-key">Mark Price</span><span class="kv-val">${fmtPrice(last.mark_price)}</span></div>
    <div class="kv"><span class="kv-key">Index Price</span><span class="kv-val">${fmtPrice(last.index_price)}</span></div>
    <div class="kv"><span class="kv-key">Funding Rate</span><span class="kv-val ${Number(last.funding_rate)>=0?'c-green':'c-red'}">${fmt(Number(last.funding_rate)*100,4)}%</span></div>
    <div class="kv"><span class="kv-key">Open Interest</span><span class="kv-val">${Number(last.open_interest).toLocaleString()}</span></div>
    <div class="kv"><span class="kv-key">Basis</span><span class="kv-val">${fmtPrice(Number(last.mark_price)-Number(last.index_price))}</span></div>
  `;
}

// ── Volume Profile chart ──
async function loadVolumeProfile(sym) {
  const data = await api('/api/volume_profile');
  const ctx = document.getElementById('vpCanvas');
  if (!ctx) return;
  if (volProfileChart) volProfileChart.destroy();
  const profile = data ? data[sym] : null;
  if (!profile || !profile.hvn) {
    ctx.parentElement.innerHTML = '<span class="c-dim">No profile data</span>';
    return;
  }
  // Build bars: POC, HVNs, VAH, VAL, LVNs
  const levels = [];
  if (profile.poc) levels.push({price:profile.poc, type:'POC', color:'rgba(88,166,255,0.9)'});
  if (profile.vah) levels.push({price:profile.vah, type:'VAH', color:'rgba(188,140,255,0.7)'});
  if (profile.val) levels.push({price:profile.val, type:'VAL', color:'rgba(188,140,255,0.7)'});
  (profile.hvn||[]).forEach(p => levels.push({price:p, type:'HVN', color:'rgba(63,185,80,0.6)'}));
  (profile.lvn||[]).forEach(p => levels.push({price:p, type:'LVN', color:'rgba(248,81,73,0.4)'}));
  levels.sort((a,b) => a.price - b.price);

  volProfileChart = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: levels.map(l => fmtPrice(l.price)),
      datasets: [{
        label: 'Level',
        data: levels.map(l => l.type==='POC'?100 : l.type==='HVN'?70 : l.type.startsWith('VA')?50 : 25),
        backgroundColor: levels.map(l=>l.color),
        borderRadius: 3,
      }]
    },
    options: {
      indexAxis: 'y', responsive:true, maintainAspectRatio:false,
      scales: {
        x: { display:false },
        y: { ticks:{color:'#c9d1d9',font:{size:10}}, grid:{color:'#30363d'} }
      },
      plugins: {
        legend:{display:false},
        tooltip:{callbacks:{label: ctx => levels[ctx.dataIndex].type + ': ' + fmtPrice(levels[ctx.dataIndex].price)}}
      }
    }
  });
}

// ── Positioning chart ──
async function loadPositioning(sym) {
  const rows = await api('/api/positioning?symbol=' + sym);
  const ctx = document.getElementById('posCanvas');
  if (!ctx) return;
  if (posChart) posChart.destroy();
  if (!rows || !rows.length) {
    ctx.parentElement.innerHTML = '<span class="c-dim">No positioning data</span>';
    return;
  }
  const last20 = rows.slice(-20);
  const labels = last20.map((r,i)=> {
    const t = r.time || r.ts || '';
    if (t) { const d = new Date(t); return d.getUTCHours()+':'+String(d.getUTCMinutes()).padStart(2,'0'); }
    return i;
  });
  posChart = new Chart(ctx, {
    type: 'bar',
    data: {
      labels,
      datasets: [
        {label:'Taker Buy',data:last20.map(r=>r.taker_buy_vol||0),backgroundColor:'rgba(63,185,80,0.6)',stack:'s'},
        {label:'Taker Sell',data:last20.map(r=>r.taker_sell_vol||0),backgroundColor:'rgba(248,81,73,0.6)',stack:'s'},
      ]
    },
    options: {
      responsive:true,maintainAspectRatio:false,
      scales:{
        x:{ticks:{color:'#8b949e',font:{size:9}},grid:{display:false}},
        y:{ticks:{color:'#8b949e'},grid:{color:'#30363d'},stacked:true}
      },
      plugins:{legend:{labels:{color:'#c9d1d9',font:{size:10}}}}
    }
  });
}

// ── Candles table ──
async function loadCandles(sym) {
  const rows = await api('/api/candles?symbol='+sym+'&count=20');
  const el = $('#candleBody');
  if (!rows || !rows.length) { el.innerHTML = '<span class="c-dim">No candle data</span>'; return; }
  const reversed = [...rows].reverse();
  el.innerHTML = `<table class="tbl"><thead><tr>
    <th>Time</th><th>Open</th><th>High</th><th>Low</th><th>Close</th><th>Volume</th><th>Delta</th><th>VWAP</th>
  </tr></thead><tbody>
  ${reversed.map(r => {
    const cls = Number(r.close)>=Number(r.open) ? 'c-green' : 'c-red';
    return `<tr>
      <td class="c-dim">${(r.ts||'').replace(/T/,' ').slice(0,19)}</td>
      <td>${fmtPrice(r.open)}</td><td>${fmtPrice(r.high)}</td>
      <td>${fmtPrice(r.low)}</td><td class="${cls}">${fmtPrice(r.close)}</td>
      <td>${fmt(r.volume,0)}</td>
      <td class="${deltaColor(r.delta)}">${fmt(r.delta,2)}</td>
      <td>${fmtPrice(r.vwap)}</td>
    </tr>`;
  }).join('')}
  </tbody></table>`;
}

// ── Trade journal ──
async function loadTrades() {
  const trades = await api('/api/trades');
  const el = $('#tradeBody');
  if (!trades || !trades.length) { el.innerHTML = '<span class="c-dim">No trades logged</span>'; return; }
  el.innerHTML = `<table class="tbl"><thead><tr>
    <th>#</th><th>Symbol</th><th>Dir</th><th>Entry</th><th>Exit</th><th>PnL</th><th>Status</th>
  </tr></thead><tbody>
  ${trades.map(t => `<tr>
    <td>${t.id||''}</td>
    <td>${t.symbol||''}</td>
    <td>${t.direction==='LONG'?'<span class="c-green">LONG</span>':'<span class="c-red">SHORT</span>'}</td>
    <td>${fmtPrice(t.entry_price)}</td>
    <td>${t.exit_price ? fmtPrice(t.exit_price) : '—'}</td>
    <td class="${t.pnl>0?'c-green':t.pnl<0?'c-red':'c-dim'}">${t.pnl!=null?fmt(t.pnl,4):'—'}</td>
    <td>${t.status==='OPEN'?'<span class="c-yellow">OPEN</span>':'<span class="c-dim">CLOSED</span>'}</td>
  </tr>`).join('')}
  </tbody></table>`;
}

// ── Status / clock ──
async function updateStatus() {
  const data = await api('/api/status');
  if (!data) {
    $('#statusDot').className = 'dot dead';
    $('#statusText').textContent = 'Disconnected';
    return;
  }
  $('#footerBucket').textContent = data.bucket || '';
  // Check candle freshness
  const candleMod = data.candles?.last_modified;
  if (candleMod) {
    const age = (Date.now() - new Date(candleMod).getTime())/1000;
    if (age < 120) {
      $('#statusDot').className = 'dot';
      $('#statusText').textContent = 'Live — ' + timeAgo(candleMod);
    } else if (age < 600) {
      $('#statusDot').className = 'dot stale';
      $('#statusText').textContent = 'Stale — ' + timeAgo(candleMod);
    } else {
      $('#statusDot').className = 'dot dead';
      $('#statusText').textContent = 'Offline — ' + timeAgo(candleMod);
    }
  }
}

function updateClock() {
  const now = new Date();
  $('#clockText').textContent = now.toISOString().slice(0,19).replace('T',' ') + ' UTC';
}

// ── Empty-state: show data panels even without signals ──
function renderWaitingPanels(sym) {
  return `
    <div class="card">
      <div class="card-head">${sym} <span class="badge badge-no">AWAITING SIGNALS</span></div>
      <div class="card-body" style="text-align:center;padding:24px">
        <div style="font-size:14px;color:var(--yellow);margin-bottom:8px">Signal engine accumulating data...</div>
        <div class="c-dim" style="font-size:12px">TDS scores appear after ~120 minutes of candle collection.</div>
      </div>
    </div>
    <div class="card" id="derivCard_${sym}">
      <div class="card-head">${sym} Derivatives <span class="c-dim" id="derivTs_${sym}"></span></div>
      <div class="card-body" id="derivBody_${sym}"><div class="loading">Loading...</div></div>
    </div>
    <div class="card" id="vpCard_${sym}">
      <div class="card-head">${sym} Volume Profile</div>
      <div class="card-body"><div class="chart-wrap"><canvas id="vpCanvas_${sym}"></canvas></div></div>
    </div>
    <div class="card wide" id="candleCard_${sym}">
      <div class="card-head">${sym} Recent Candles (1m) <span class="c-dim">Last 20</span></div>
      <div class="card-body scroll-y" id="candleBody_${sym}"><div class="loading">Loading...</div></div>
    </div>
    <div class="card" id="posCard_${sym}">
      <div class="card-head">${sym} Positioning</div>
      <div class="card-body"><div class="chart-wrap"><canvas id="posCanvas_${sym}"></canvas></div></div>
    </div>
  `;
}

async function loadWaitingData(sym, suffix) {
  const sfx = suffix || '';
  // Derivatives
  const drows = await api('/api/derivatives?symbol=' + sym);
  const dEl = $(`#derivBody_${sym}${sfx}`);
  if (dEl && drows && drows.length) {
    const last = drows[drows.length - 1];
    const tsEl = $(`#derivTs_${sym}${sfx}`);
    if (tsEl) tsEl.textContent = timeAgo(last.ts);
    dEl.innerHTML = `
      <div class="kv"><span class="kv-key">Mark Price</span><span class="kv-val">${fmtPrice(last.mark_price)}</span></div>
      <div class="kv"><span class="kv-key">Index Price</span><span class="kv-val">${fmtPrice(last.index_price)}</span></div>
      <div class="kv"><span class="kv-key">Funding Rate</span><span class="kv-val ${Number(last.funding_rate)>=0?'c-green':'c-red'}">${fmt(Number(last.funding_rate)*100,4)}%</span></div>
      <div class="kv"><span class="kv-key">Open Interest</span><span class="kv-val">${Number(last.open_interest).toLocaleString()}</span></div>
      <div class="kv"><span class="kv-key">Basis</span><span class="kv-val">${fmtPrice(Number(last.mark_price)-Number(last.index_price))}</span></div>
    `;
  } else if (dEl) { dEl.innerHTML = '<span class="c-dim">No data</span>'; }

  // Volume Profile
  const vpData = await api('/api/volume_profile');
  const vpCtx = document.getElementById(`vpCanvas_${sym}${sfx}`);
  if (vpCtx && vpData && vpData[sym] && vpData[sym].hvn) {
    const profile = vpData[sym];
    const levels = [];
    if (profile.poc) levels.push({price:profile.poc, type:'POC', color:'rgba(88,166,255,0.9)'});
    if (profile.vah) levels.push({price:profile.vah, type:'VAH', color:'rgba(188,140,255,0.7)'});
    if (profile.val) levels.push({price:profile.val, type:'VAL', color:'rgba(188,140,255,0.7)'});
    (profile.hvn||[]).forEach(p => levels.push({price:p, type:'HVN', color:'rgba(63,185,80,0.6)'}));
    (profile.lvn||[]).forEach(p => levels.push({price:p, type:'LVN', color:'rgba(248,81,73,0.4)'}));
    levels.sort((a,b) => a.price - b.price);
    new Chart(vpCtx, {
      type:'bar', data:{labels:levels.map(l=>fmtPrice(l.price)),datasets:[{label:'Level',data:levels.map(l=>l.type==='POC'?100:l.type==='HVN'?70:l.type.startsWith('VA')?50:25),backgroundColor:levels.map(l=>l.color),borderRadius:3}]},
      options:{indexAxis:'y',responsive:true,maintainAspectRatio:false,scales:{x:{display:false},y:{ticks:{color:'#c9d1d9',font:{size:10}},grid:{color:'#30363d'}}},plugins:{legend:{display:false},tooltip:{callbacks:{label:ctx=>levels[ctx.dataIndex].type+': '+fmtPrice(levels[ctx.dataIndex].price)}}}}
    });
  } else if (vpCtx) { vpCtx.parentElement.innerHTML = '<span class="c-dim">No profile data</span>'; }

  // Candles
  const crows = await api('/api/candles?symbol='+sym+'&count=20');
  const cEl = $(`#candleBody_${sym}${sfx}`);
  if (cEl && crows && crows.length) {
    const reversed = [...crows].reverse();
    cEl.innerHTML = `<table class="tbl"><thead><tr><th>Time</th><th>Open</th><th>High</th><th>Low</th><th>Close</th><th>Vol</th><th>Delta</th><th>VWAP</th></tr></thead><tbody>
    ${reversed.map(r=>{const cls=Number(r.close)>=Number(r.open)?'c-green':'c-red';return `<tr><td class="c-dim">${(r.ts||'').replace(/T/,' ').slice(0,19)}</td><td>${fmtPrice(r.open)}</td><td>${fmtPrice(r.high)}</td><td>${fmtPrice(r.low)}</td><td class="${cls}">${fmtPrice(r.close)}</td><td>${fmt(r.volume,0)}</td><td class="${deltaColor(r.delta)}">${fmt(r.delta,2)}</td><td>${fmtPrice(r.vwap)}</td></tr>`;}).join('')}
    </tbody></table>`;
  } else if (cEl) { cEl.innerHTML = '<span class="c-dim">No candle data</span>'; }

  // Positioning
  const prows = await api('/api/positioning?symbol='+sym);
  const pCtx = document.getElementById(`posCanvas_${sym}${sfx}`);
  if (pCtx && prows && prows.length) {
    const last20 = prows.slice(-20);
    const labels = last20.map((r,i)=>{const t=r.time||r.ts||'';if(t){const d=new Date(t);return d.getUTCHours()+':'+String(d.getUTCMinutes()).padStart(2,'0');}return i;});
    new Chart(pCtx, {
      type:'bar', data:{labels,datasets:[{label:'Taker Buy',data:last20.map(r=>r.taker_buy_vol||0),backgroundColor:'rgba(63,185,80,0.6)',stack:'s'},{label:'Taker Sell',data:last20.map(r=>r.taker_sell_vol||0),backgroundColor:'rgba(248,81,73,0.6)',stack:'s'}]},
      options:{responsive:true,maintainAspectRatio:false,scales:{x:{ticks:{color:'#8b949e',font:{size:9}},grid:{display:false}},y:{ticks:{color:'#8b949e'},grid:{color:'#30363d'},stacked:true}},plugins:{legend:{labels:{color:'#c9d1d9',font:{size:10}}}}}
    });
  } else if (pCtx) { pCtx.parentElement.innerHTML = '<span class="c-dim">No positioning data</span>'; }
}

function renderWaiting() {
  renderTabs(KNOWN_SYMBOLS);
  const sym = CURRENT_SYMBOL === 'ALL' ? 'BTCUSDT' : CURRENT_SYMBOL;
  const grid = $('#dashboard');
  grid.innerHTML = renderWaitingPanels(sym) + `
    <div class="card" id="tradeCard">
      <div class="card-head">Trade Journal</div>
      <div class="card-body scroll-y" id="tradeBody"><div class="loading">Loading...</div></div>
    </div>
  `;
  loadWaitingData(sym);
  loadTrades();
}

function renderWaitingAll() {
  renderTabs(KNOWN_SYMBOLS);
  const grid = $('#dashboard');
  grid.innerHTML = KNOWN_SYMBOLS.map(sym => renderWaitingPanels(sym)).join('') + `
    <div class="card" id="tradeCard">
      <div class="card-head">Trade Journal</div>
      <div class="card-body scroll-y" id="tradeBody"><div class="loading">Loading...</div></div>
    </div>
  `;
  KNOWN_SYMBOLS.forEach(sym => loadWaitingData(sym));
  loadTrades();
}

// ── Main loop ──
async function refresh() {
  const data = await api('/api/signals');
  if (data && !data.error && Object.keys(data).length > 0) {
    SIGNALS = data;
    if (!SIGNALS[CURRENT_SYMBOL] && CURRENT_SYMBOL !== 'ALL') {
      CURRENT_SYMBOL = Object.keys(SIGNALS)[0] || 'BTCUSDT';
    }
    renderAll();
  } else {
    renderWaiting();
  }
  updateStatus();
}

// Boot
refresh();
setInterval(refresh, 60000);
setInterval(updateClock, 1000);
updateClock();
</script>
</body>
</html>"""


@app.route("/")
def index():
    return DASHBOARD_HTML


# ── Main ────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Crypto Signal Engine Dashboard")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    print(f"""
╔══════════════════════════════════════════════════════════╗
║         CRYPTO SIGNAL ENGINE DASHBOARD                  ║
╠══════════════════════════════════════════════════════════╣
║  Local:   http://localhost:{args.port}                        ║
║  S3:      {S3_BUCKET}     ║
║  Region:  {AWS_REGION}                                     ║
╚══════════════════════════════════════════════════════════╝
    """)

    app.run(host=args.host, port=args.port, debug=args.debug)
