"""
dashboard.py — NSE Money Printer v6 Dashboard
Port: 9090 — started manually via start.sh, NOT via launchd
"""

from flask import Flask, jsonify, request, render_template_string
import sqlite3, json, glob, subprocess, os
from datetime import datetime, date, timedelta
from config import JOURNAL_DB, CAPITAL, DASHBOARD_PORT, DASHBOARD_HOST
from config import MAX_TRADES_PER_DAY, MAX_DAILY_LOSS_PCT, MARKET_OPEN_TIME, MARKET_CLOSE_TIME

app = Flask(__name__)
_broker = None

def _get_broker():
    global _broker
    if _broker is None:
        try:
            from broker import Broker
            _broker = Broker()
        except Exception:
            pass
    return _broker

def _q(sql, params=()):
    conn = sqlite3.connect(JOURNAL_DB)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    except Exception:
        return []
    finally:
        conn.close()

def _one(sql, params=()):
    rows = _q(sql, params)
    return rows[0] if rows else {}

def _live_equity():
    rows = _q(
        "SELECT pnl, close_time FROM trades "
        "WHERE close_time IS NOT NULL AND pnl IS NOT NULL "
        "ORDER BY close_time ASC"
    )
    # Group by date to reduce noise
    by_date = {}
    cum = CAPITAL
    for r in rows:
        cum += r["pnl"]
        d = r["close_time"][:10]
        by_date[d] = {"time": d, "equity": round(cum, 2), "pnl": round(r["pnl"], 2)}
    return list(by_date.values())

def _load_bt():
    try:
        files = sorted(glob.glob(os.path.expanduser("~/trading_bot/reports/backtest_2*.json")), reverse=True)
        return json.load(open(files[0])) if files else None
    except Exception:
        return None

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>NSE Money Printer v6</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&family=Sora:wght@300;400;600;700&display=swap');
:root{--bg:#080c14;--bg2:#0d1320;--bg3:#111827;--card:#0f1623;--border:rgba(255,255,255,0.07);--border2:rgba(255,255,255,0.13);--text:#e8eaf0;--muted:#6b7a99;--dim:#3d4a66;--green:#00d4a0;--red:#ff4d6a;--amber:#f5a623;--blue:#4d9fff;--purple:#a78bfa;--font:'Sora',sans-serif;--mono:'JetBrains Mono',monospace}
*{margin:0;padding:0;box-sizing:border-box}
body{background:var(--bg);color:var(--text);font-family:var(--font);font-size:13px;min-height:100vh}
.header{display:flex;align-items:center;justify-content:space-between;padding:12px 22px;border-bottom:1px solid var(--border);background:var(--bg2);position:sticky;top:0;z-index:100;gap:12px;flex-wrap:wrap}
.logo{display:flex;align-items:center;gap:10px;font-size:15px;font-weight:700}
.logo-icon{width:28px;height:28px;background:linear-gradient(135deg,var(--green),var(--blue));border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:14px}
.status-pill{display:flex;align-items:center;gap:6px;background:rgba(0,212,160,0.1);border:1px solid rgba(0,212,160,0.25);border-radius:20px;padding:4px 10px;font-size:11px;font-weight:600;color:var(--green)}
.status-pill.closed{background:rgba(255,77,106,0.1);border-color:rgba(255,77,106,0.25);color:var(--red)}
.pulse{width:6px;height:6px;border-radius:50%;background:var(--green);animation:pulse 2s ease infinite}
.pulse.off{background:var(--red);animation:none}
@keyframes pulse{0%,100%{opacity:1;transform:scale(1)}50%{opacity:.5;transform:scale(.8)}}
.header-right{display:flex;align-items:center;gap:10px}
.capital-badge{background:var(--bg3);border:1px solid var(--border2);border-radius:8px;padding:5px 11px;font-family:var(--mono);font-size:12px;font-weight:500;color:var(--amber)}
.time-display{font-family:var(--mono);font-size:11px;color:var(--muted)}
.broker-bar{display:flex;align-items:center;gap:16px;padding:7px 22px;background:var(--bg2);border-bottom:1px solid var(--border);font-size:11px;flex-wrap:wrap}
.bs{display:flex;align-items:center;gap:5px;color:var(--muted)}
.bs span{font-family:var(--mono);font-weight:600}
.bs.g span{color:var(--green)}.bs.r span{color:var(--red)}.bs.a span{color:var(--amber)}.bs.b span{color:var(--blue)}
.main{padding:16px 20px;max-width:1800px;margin:0 auto}
.session-strip{display:flex;gap:7px;margin-bottom:15px}
.sb{flex:1;background:var(--card);border:1px solid var(--border);border-radius:10px;padding:10px 12px}
.sb.go{border-color:rgba(0,212,160,.3);background:rgba(0,212,160,.04)}
.sb.warn{border-color:rgba(245,166,35,.3);background:rgba(245,166,35,.04)}
.sb.off{opacity:.4}
.sn{font-size:11px;font-weight:700;margin-bottom:2px}
.st{font-family:var(--mono);font-size:10px;color:var(--muted)}
.ss{font-size:10px;font-weight:600;margin-top:4px}
.ss.go{color:var(--green)}.ss.warn{color:var(--amber)}.ss.off{color:var(--muted)}
.metrics{display:grid;grid-template-columns:repeat(5,1fr);gap:11px;margin-bottom:15px}
.mc{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:14px;position:relative;overflow:hidden}
.mc::before{content:'';position:absolute;top:0;left:0;right:0;height:2px;border-radius:12px 12px 0 0}
.g::before{background:var(--green)}.r::before{background:var(--red)}.a::before{background:var(--amber)}.b::before{background:var(--blue)}.p::before{background:var(--purple)}
.ml{font-size:10px;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:1px;margin-bottom:6px}
.mv{font-family:var(--mono);font-size:24px;font-weight:700;line-height:1;margin-bottom:4px}
.mg{color:var(--green)}.mr{color:var(--red)}.ma{color:var(--amber)}.mb{color:var(--blue)}.mp{color:var(--purple)}
.ms{font-size:11px;color:var(--muted)}
.mt{background:var(--bg3);border-radius:2px;height:4px;overflow:hidden;margin:5px 0 3px}
.mf{height:100%;border-radius:2px;transition:width .8s}
.disc{display:grid;grid-template-columns:repeat(5,1fr);gap:11px;margin-bottom:15px;background:var(--card);border:1px solid var(--border);border-radius:12px;padding:13px 15px}
.di{text-align:center}
.dl{font-size:10px;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:.8px;margin-bottom:4px}
.dv{font-family:var(--mono);font-size:19px;font-weight:700}
.pb{background:rgba(245,166,35,.08);border:1px solid rgba(245,166,35,.3);border-radius:10px;padding:10px 15px;color:var(--amber);font-weight:600;font-size:12px;display:flex;align-items:center;gap:8px;margin-bottom:13px}
.panel{background:var(--card);border:1px solid var(--border);border-radius:13px;overflow:hidden;margin-bottom:13px}
.ph{display:flex;align-items:center;justify-content:space-between;padding:11px 14px;border-bottom:1px solid var(--border);background:rgba(255,255,255,.015)}
.pt{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:1.5px;color:var(--muted)}
.cb{background:rgba(77,159,255,.12);border:1px solid rgba(77,159,255,.2);color:var(--blue);border-radius:20px;padding:2px 8px;font-size:11px;font-weight:600;font-family:var(--mono)}
.g2{display:grid;grid-template-columns:1fr 1fr;gap:13px;margin-bottom:13px}
table{width:100%;border-collapse:collapse}
th{font-size:10px;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:.8px;padding:8px 13px;text-align:left;border-bottom:1px solid var(--border);background:rgba(255,255,255,.01);white-space:nowrap}
td{padding:9px 13px;font-size:12px;border-bottom:1px solid rgba(255,255,255,.035);vertical-align:middle}
tr:last-child td{border-bottom:none}
tbody tr{transition:background .12s}
tbody tr:hover td{background:rgba(255,255,255,.02)}
.tag{display:inline-block;padding:2px 7px;border-radius:4px;font-size:10px;font-weight:700;letter-spacing:.4px;text-transform:uppercase}
.t-supply{background:rgba(255,77,106,.14);color:#ff4d6a;border:1px solid rgba(255,77,106,.22)}
.t-demand{background:rgba(0,212,160,.14);color:#00d4a0;border:1px solid rgba(0,212,160,.22)}
.t-buy{background:rgba(0,212,160,.14);color:#00d4a0;border:1px solid rgba(0,212,160,.22)}
.t-sell{background:rgba(255,77,106,.14);color:#ff4d6a;border:1px solid rgba(255,77,106,.22)}
.t-win{background:rgba(0,212,160,.12);color:var(--green)}
.t-loss{background:rgba(255,77,106,.12);color:var(--red)}
.t-htf{background:rgba(0,212,160,.1);color:var(--green);border:1px solid rgba(0,212,160,.18)}
.t-pattern{background:rgba(77,159,255,.1);color:var(--blue);border:1px solid rgba(77,159,255,.18)}
.sc{display:flex;align-items:center;gap:7px}
.sk{width:44px;height:4px;background:var(--bg3);border-radius:2px;overflow:hidden}
.sf{height:100%;border-radius:2px}
.sv{font-family:var(--mono);font-size:11px;font-weight:600;min-width:28px}
.eq{background:var(--card);border:1px solid var(--border);border-radius:13px;padding:17px;margin-bottom:13px}
.eq-tabs{display:flex;gap:6px;margin-bottom:12px}
.eq-tab{padding:4px 14px;border-radius:6px;font-size:11px;font-weight:700;cursor:pointer;border:1px solid var(--border);background:transparent;color:var(--muted);font-family:var(--font);transition:all .15s}
.eq-tab.on{background:rgba(0,212,160,.12);color:var(--green);border-color:rgba(0,212,160,.3)}
.bittu-panel{background:linear-gradient(135deg,#0a0618,#060d1a);border:1px solid rgba(167,139,250,.35);border-radius:13px;padding:18px;margin-bottom:13px;position:relative;overflow:hidden}
.bittu-panel::before{content:'';position:absolute;top:0;left:0;right:0;height:2px;background:linear-gradient(90deg,#9d00ff,#00d4ff,#9d00ff)}
.bittu-head{display:flex;align-items:center;gap:12px;margin-bottom:14px}
.bittu-orb{width:38px;height:38px;border-radius:50%;background:radial-gradient(#9d00ff,#060010);border:1.5px solid #9d00ff;display:flex;align-items:center;justify-content:center;font-size:18px;animation:gorb 3s ease infinite}
@keyframes gorb{0%,100%{box-shadow:0 0 8px #9d00ff44}50%{box-shadow:0 0 22px #9d00ff99}}
.bittu-chat{background:rgba(0,0,0,.35);border:1px solid rgba(167,139,250,.15);border-radius:8px;padding:14px;min-height:70px;max-height:160px;overflow-y:auto;margin-bottom:12px;font-family:var(--mono);font-size:12px;color:#d0e8ff;line-height:1.6}
.bittu-row{display:flex;gap:8px;margin-bottom:10px}
.bittu-inp{flex:1;padding:9px 13px;background:rgba(0,0,0,.4);border:1px solid rgba(167,139,250,.3);border-radius:6px;color:#d0e8ff;font-family:var(--mono);font-size:12px;outline:none}
.bittu-inp:focus{border-color:#9d00ff}
.bittu-btn{padding:9px 18px;background:#9d00ff;color:#fff;border:none;border-radius:6px;cursor:pointer;font-weight:700;font-size:12px;transition:background .15s}
.bittu-btn:hover{background:#b300ff}
.bittu-quick{display:flex;gap:6px;flex-wrap:wrap}
.bq{padding:5px 11px;border:1px solid rgba(167,139,250,.25);border-radius:20px;background:transparent;color:var(--purple);font-size:11px;cursor:pointer;font-family:var(--font);transition:all .15s}
.bq:hover{background:rgba(167,139,250,.1)}
.bq.red{border-color:rgba(255,77,106,.4);color:var(--red)}
.bq.red:hover{background:rgba(255,77,106,.1)}
.le{display:flex;align-items:center;gap:10px;padding:8px 13px;border-bottom:1px solid rgba(255,255,255,.035);font-size:12px}
.ld{width:6px;height:6px;border-radius:50%;flex-shrink:0}
.lt{font-family:var(--mono);color:var(--muted);font-size:11px;min-width:55px}
.ls{font-weight:700;min-width:90px}
.lm{color:var(--muted);flex:1}
.la{font-family:var(--mono);font-size:11px;font-weight:600}
.es{padding:26px;text-align:center;color:var(--dim);font-size:12px}
.rb{position:fixed;bottom:0;left:0;right:0;height:2px;background:var(--border);z-index:200}
.rf{height:100%;background:linear-gradient(90deg,var(--green),var(--blue));animation:cd 10s linear infinite}
@keyframes cd{from{width:100%}to{width:0%}}
@media(max-width:1100px){.metrics,.disc{grid-template-columns:repeat(3,1fr)}.g2{grid-template-columns:1fr}.session-strip{flex-wrap:wrap}}
</style>
</head>
<body>

<div class="header">
  <div class="logo">
    <div class="logo-icon">⚡</div>
    NSE Money Printer v6
    <div class="status-pill" id="mkt-pill">
      <div class="pulse" id="mkt-pulse"></div>
      <span id="mkt-label">Loading...</span>
    </div>
  </div>
  <div class="header-right">
    <div class="time-display" id="clock">--:--:--</div>
    <div class="capital-badge">₹CAPITAL_VAL</div>
  </div>
</div>

<div class="broker-bar">
  <span id="mode-ind" style="font-weight:700;font-size:11px;padding:2px 8px;border-radius:4px;background:rgba(77,159,255,0.12);color:var(--blue)">PAPER MODE</span>
  <div class="bs g">Available: <span id="br-avail">—</span></div>
  <div class="bs r">Used: <span id="br-used">—</span></div>
  <div class="bs b">Total: <span id="br-total">—</span></div>
  <div class="bs a">Broker: <span id="br-name">Paper</span></div>
  <div class="bs" style="margin-left:auto" id="last-upd">—</div>
</div>

<div class="main">

<div class="session-strip">
  <div class="sb off"><div class="sn">Opening Chaos</div><div class="st">9:15–9:45</div><div class="ss off">Avoid</div></div>
  <div class="sb go" id="sg1"><div class="sn">🔥 Golden Window 1</div><div class="st">9:45–11:30</div><div class="ss go">Best entries</div></div>
  <div class="sb off"><div class="sn">Lunch Drift</div><div class="st">11:30–1:30</div><div class="ss off">Avoid</div></div>
  <div class="sb go" id="sg2"><div class="sn">🔥 Golden Window 2</div><div class="st">1:30–2:30</div><div class="ss go">Trend runs</div></div>
  <div class="sb warn"><div class="sn">No New Entries</div><div class="st">2:30–3:15</div><div class="ss warn">Manage only</div></div>
  <div class="sb off"><div class="sn">EOD Squareoff</div><div class="st">3:15–3:30</div><div class="ss off">Auto-exit</div></div>
</div>

<div class="metrics">
  <div class="mc g"><div class="ml">Today P&L</div><div class="mv mg" id="m-pnl">₹+0</div><div class="ms" id="m-pnl-s">Win rate: 0%</div></div>
  <div class="mc a"><div class="ml">Trades Today</div><div class="mv ma" id="m-trades">0</div><div class="ms" id="m-trades-s">0 open</div></div>
  <div class="mc r"><div class="ml">Daily Loss Used</div><div class="mv" id="m-loss" style="color:var(--text)">₹0</div><div class="mt"><div class="mf" id="m-loss-b" style="width:0%;background:var(--red)"></div></div><div class="ms" id="m-loss-s">Limit ₹200</div></div>
  <div class="mc b"><div class="ml">Zones / Alerts</div><div class="mv mb" id="m-zones">0</div><div class="ms" id="m-zones-s">0 alerts</div></div>
  <div class="mc p"><div class="ml">Total P&L (All Time)</div><div class="mv" id="m-total" style="color:var(--text)">₹0</div><div class="ms" id="m-total-s">0 trades</div></div>
</div>

<div class="pb" id="pb" style="display:none">⚠ Trading Paused — <span id="pr">—</span></div>

<div class="disc">
  <div class="di"><div class="dl">Consec. Losses</div><div class="dv" id="d-l" style="color:var(--text)">0</div></div>
  <div class="di"><div class="dl">Score Threshold</div><div class="dv ma" id="d-t">0.62</div></div>
  <div class="di"><div class="dl">Open Positions</div><div class="dv mb" id="d-op">0/1</div></div>
  <div class="di"><div class="dl">Alerts Fired</div><div class="dv ma" id="d-f">0</div></div>
  <div class="di"><div class="dl">Bot State</div><div class="dv mg" id="d-st">ACTIVE</div></div>
</div>

<!-- BITTU AI -->
<div class="bittu-panel">
  <div class="bittu-head">
    <div class="bittu-orb">🤖</div>
    <div>
      <div style="font-size:14px;font-weight:700;color:#a78bfa">BITTU AI — Trading Intelligence</div>
      <div style="font-size:10px;color:var(--muted);font-family:var(--mono)">phi4 · local · learns from every trade</div>
    </div>
    <div style="margin-left:auto;font-family:var(--mono);font-size:11px;color:#a78bfa" id="bst">● READY</div>
  </div>
  <div class="bittu-chat" id="bchat">BITTU: Neural link established. I monitor your trades and adapt strategy. Ask me anything.</div>
  <div class="bittu-row">
    <input class="bittu-inp" id="binp" type="text" placeholder="Ask BITTU anything about your trades..." onkeydown="if(event.key==='Enter')askBittu()">
    <button class="bittu-btn" onclick="askBittu()">ASK ›</button>
  </div>
  <div class="bittu-quick">
    <button class="bq" onclick="qask('Analyze my losses and tell me what to fix')">📈 Analyze Losses</button>
    <button class="bq" onclick="qask('Check my config and suggest improvements')">⚙ Fix Config</button>
    <button class="bq" onclick="qask('What is my trading status today?')">📊 Today Status</button>
    <button class="bq" onclick="qask('Which patterns and zones are working best?')">✅ What Works</button>
    <button class="bq red" onclick="emergClose()">🚨 Emergency Close All</button>
  </div>
</div>


<!-- MANUAL ORDER PANEL -->
<div class="panel" style="margin-bottom:13px">
  <div class="ph"><div class="pt">Manual Order</div><div style="font-size:11px;color:var(--muted)" id="mo-status"></div></div>
  <div style="padding:14px;display:grid;grid-template-columns:repeat(6,1fr);gap:10px;align-items:end">
    <div>
      <div style="font-size:10px;color:var(--muted);margin-bottom:5px">SYMBOL</div>
      <input id="mo-sym" type="text" placeholder="RELIANCE" style="width:100%;padding:8px;background:rgba(0,0,0,.3);border:1px solid rgba(255,255,255,.12);border-radius:6px;color:#e8eaf0;font-size:12px;font-family:var(--mono);outline:none">
    </div>
    <div>
      <div style="font-size:10px;color:var(--muted);margin-bottom:5px">SIDE</div>
      <select id="mo-side" style="width:100%;padding:8px;background:#0f1623;border:1px solid rgba(255,255,255,.12);border-radius:6px;color:#e8eaf0;font-size:12px;outline:none">
        <option value="BUY">BUY</option><option value="SELL">SELL</option>
      </select>
    </div>
    <div>
      <div style="font-size:10px;color:var(--muted);margin-bottom:5px">ENTRY</div>
      <input id="mo-entry" type="number" placeholder="0.00" style="width:100%;padding:8px;background:rgba(0,0,0,.3);border:1px solid rgba(255,255,255,.12);border-radius:6px;color:#e8eaf0;font-size:12px;font-family:var(--mono);outline:none">
    </div>
    <div>
      <div style="font-size:10px;color:var(--muted);margin-bottom:5px">STOP LOSS</div>
      <input id="mo-sl" type="number" placeholder="0.00" style="width:100%;padding:8px;background:rgba(0,0,0,.3);border:1px solid rgba(255,255,255,.12);border-radius:6px;color:#e8eaf0;font-size:12px;font-family:var(--mono);outline:none" oninput="calcSize()">
    </div>
    <div>
      <div style="font-size:10px;color:var(--muted);margin-bottom:5px">QTY (auto)</div>
      <input id="mo-qty" type="number" placeholder="0" style="width:100%;padding:8px;background:rgba(0,0,0,.3);border:1px solid rgba(255,255,255,.12);border-radius:6px;color:#00d4a0;font-size:12px;font-family:var(--mono);outline:none">
    </div>
    <div>
      <button onclick="placeManualOrder()" style="width:100%;padding:9px;background:linear-gradient(135deg,#00d4a0,#4d9fff);border:none;border-radius:6px;color:#000;font-weight:700;font-size:13px;cursor:pointer">PLACE ORDER</button>
    </div>
  </div>
  <div style="padding:0 14px 12px;font-size:11px;color:var(--muted)" id="mo-calc">Enter entry + stop loss to auto-calculate qty (0.5% risk)</div>
</div>

<!-- EQUITY CURVE -->
<div class="eq">
  <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px">
    <div style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:1.5px;color:var(--muted)">◢ Equity Curve</div>
    <div class="eq-tabs">
      <button class="eq-tab on" id="tab-live" onclick="switchEq('live')">Live Trades</button>
      <button class="eq-tab" id="tab-bt" onclick="switchEq('bt')">Backtest</button>
    </div>
  </div>
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
    <div style="font-family:var(--mono);font-size:22px;font-weight:700" id="eq-label">—</div>
    <div style="font-size:11px;color:var(--muted);display:flex;gap:16px" id="eq-stats"></div>
  </div>
  <div style="position:relative;height:160px;width:100%"><canvas id="ec"></canvas></div>
</div>

<div class="g2">
  <!-- Open Trades -->
  <div class="panel">
    <div class="ph"><div class="pt">🔴 Open Trades <span class="cb" id="ob">0</span></div></div>
    <div id="otb"><div class="es">No open trades</div></div>
  </div>
  <!-- Active Alerts -->
  <div class="panel">
    <div class="ph"><div class="pt">⚠ Active Alerts <span class="cb" id="ab">0</span></div></div>
    <div id="alb"><div class="es">No active alerts</div></div>
  </div>
</div>

<!-- Top Zones -->
<div class="panel">
  <div class="ph"><div class="pt">🎯 Top Zones <span class="cb" id="zb">0</span></div></div>
  <div id="znb"><div class="es">No zones yet</div></div>
</div>

<!-- Trade History -->
<div class="panel">
  <div class="ph"><div class="pt">📋 Trade History <span class="cb" id="hb">0</span></div></div>
  <div id="hst"><div class="es">No closed trades yet</div></div>
</div>

<!-- Signal Log -->
<div class="panel">
  <div class="ph"><div class="pt">📡 Live Signal Log</div><div style="font-size:11px;color:var(--muted)" id="lts">—</div></div>
  <div id="lc"></div>
</div>

</div>
<div class="rb"><div class="rf"></div></div>

<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.js"></script>
<script src="https://unpkg.com/lightweight-charts@4.1.3/dist/lightweight-charts.standalone.production.js"></script>
<script>
var CAP = CAPITAL_JS;
var prevPnl = null, prevAlerts = 0, eqChart = null, eqMode = 'live';
var liveEqData = [], btEqData = [];

function fmt(n, d) { d = d == null ? 2 : d; return n == null ? '--' : parseFloat(n).toFixed(d); }
function fmtRs(n) {
  if (n == null) return '--';
  var v = parseFloat(n), c = v >= 0 ? 'var(--green)' : 'var(--red)';
  return '<span style="color:' + c + '">₹' + (v >= 0 ? '+' : '') + Math.round(Math.abs(v)).toLocaleString('en-IN') + '</span>';
}
function ago(iso) {
  if (!iso) return '--';
  try {
    var d = (Date.now() - new Date(iso).getTime()) / 1000;
    if (d < 60) return Math.round(d) + 's ago';
    if (d < 3600) return Math.round(d / 60) + 'm ago';
    return Math.round(d / 3600) + 'h ago';
  } catch(e) { return '--'; }
}
function tag(t, c) { return '<span class="tag t-' + c + '">' + t + '</span>'; }
function sb(score) {
  var pct = Math.round(score * 100);
  var col = score >= 0.65 ? 'var(--green)' : score >= 0.55 ? 'var(--amber)' : 'var(--muted)';
  return '<div class="sc"><div class="sk"><div class="sf" style="width:' + pct + '%;background:' + col + '"></div></div><span class="sv" style="color:' + col + '">' + score.toFixed(2) + '</span></div>';
}

function tick() { document.getElementById('clock').textContent = new Date().toLocaleTimeString('en-IN', {hour: '2-digit', minute: '2-digit', second: '2-digit'}); }
tick(); setInterval(tick, 1000);

function updSess() {
  var m = new Date().getHours() * 60 + new Date().getMinutes();
  document.getElementById('sg1').className = 'sb ' + (m >= 585 && m < 690 ? 'go' : 'off');
  document.getElementById('sg2').className = 'sb ' + (m >= 810 && m < 870 ? 'go' : 'off');
}
updSess(); setInterval(updSess, 60000);

function addLog(dot, sym, msg, action, ac) {
  var t = new Date().toLocaleTimeString('en-IN', {hour: '2-digit', minute: '2-digit', second: '2-digit'});
  var c = document.getElementById('lc');
  var e = document.createElement('div');
  e.className = 'le';
  e.innerHTML = '<div class="ld" style="background:' + dot + '"></div><div class="lt">' + t + '</div><div class="ls">' + sym + '</div><div class="lm">' + msg + '</div><div class="la" style="color:' + ac + '">' + action + '</div>';
  c.insertBefore(e, c.firstChild);
  var all = c.querySelectorAll('.le');
  if (all.length > 15) all[all.length - 1].remove();
}

async function askBittu() {
  var inp = document.getElementById('binp');
  var chat = document.getElementById('bchat');
  var st = document.getElementById('bst');
  var q = inp.value.trim();
  if (!q) return;
  inp.value = '';
  chat.textContent += '\n\nYOU: ' + q + '\n\nBITTU: thinking...';
  chat.scrollTop = 9999;
  st.textContent = '● THINKING'; st.style.color = '#f5a623';
  try {
    var r = await fetch('/api/bittu', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({query: q})});
    var d = await r.json();
    var resp = (d.response || d.error || 'No response from phi4');
    chat.textContent = chat.textContent.replace('BITTU: thinking...', 'BITTU: ' + resp);
    chat.scrollTop = 9999;
    st.textContent = '● READY'; st.style.color = '#a78bfa';
  } catch(e) {
    chat.textContent += '\nError: ' + e;
    st.textContent = '● ERROR'; st.style.color = '#ff4d6a';
  }
}
function qask(q) { document.getElementById('binp').value = q; askBittu(); }

async function emergClose() {
  if (!confirm('EMERGENCY CLOSE ALL OPEN POSITIONS?')) return;
  var r = await fetch('/api/emergency_close', {method: 'POST'});
  var d = await r.json();
  addLog('var(--red)', 'EMERGENCY', 'Closed ' + (d.closed || 0) + ' positions', 'DONE', 'var(--red)');
  refresh();
}

function switchEq(m) {
  eqMode = m;
  document.getElementById('tab-live').className = 'eq-tab' + (m === 'live' ? ' on' : '');
  document.getElementById('tab-bt').className = 'eq-tab' + (m === 'bt' ? ' on' : '');
  if (m === 'live') drawEqChart(liveEqData, '#00d4a0', 'rgba(0,212,160,.08)');
  else drawEqChart(btEqData, '#4d9fff', 'rgba(77,159,255,.08)');
}

function drawEqChart(data, color, fill) {
  if (!data || !data.length) { document.getElementById('eq-label').textContent = 'No data yet'; return; }
  var vals = data.map(function(d) { return d.equity; });
  var labels = data.map(function(d, i) { return (d.time || '').substring(0,10) || ('T'+(i+1)); });
  var net = vals[vals.length - 1] - CAP;
  var mx = Math.max.apply(null, vals), mn = Math.min.apply(null, vals);
  document.getElementById('eq-label').textContent = (net >= 0 ? '+' : '') + '₹' + Math.round(net).toLocaleString('en-IN');
  document.getElementById('eq-label').style.color = net >= 0 ? 'var(--green)' : 'var(--red)';
  document.getElementById('eq-stats').innerHTML =
    '<span>Peak: <strong style="color:var(--green)">₹' + Math.round(mx).toLocaleString('en-IN') + '</strong></span>' +
    '<span>Trough: <strong style="color:var(--red)">₹' + Math.round(mn).toLocaleString('en-IN') + '</strong></span>' +
    '<span>Points: <strong>' + data.length + '</strong></span>';
  if (eqChart) eqChart.destroy();
  eqChart = new Chart(document.getElementById('ec'), {
    type: 'line',
    data: {labels: labels, datasets: [{data: vals, borderColor: color, backgroundColor: fill, borderWidth: 2, pointRadius: data.length > 30 ? 0 : 3, tension: 0.3, fill: true}]},
    options: {responsive: true, maintainAspectRatio: false, animation: false,
      plugins: {legend: {display: false}, tooltip: {callbacks: {label: function(c) { return '₹' + c.parsed.y.toLocaleString('en-IN'); }}}},
      scales: {
        x: {type:'category',grid: {color: 'rgba(255,255,255,.04)'}, ticks: {color: '#6b7a99', font: {size: 10}, maxTicksLimit: 10, maxRotation:0}},
        y: {grid: {color: 'rgba(255,255,255,.04)'}, ticks: {color: '#6b7a99', font: {size: 10}, callback: function(v) { return '₹' + (v / 1000).toFixed(0) + 'k'; }}}
      }
    }
  });
}


function calcSize() {
  var entry = parseFloat(document.getElementById('mo-entry').value) || 0;
  var sl = parseFloat(document.getElementById('mo-sl').value) || 0;
  if (entry > 0 && sl > 0 && Math.abs(entry-sl)/entry > 0.003) {
    var risk = 20000 * 0.005;
    var dist = Math.abs(entry - sl);
    var qty = Math.floor(risk / dist);
    document.getElementById('mo-qty').value = qty;
    var target = entry > sl ? entry + dist*2.2 : entry - dist*2.2;
    document.getElementById('mo-calc').textContent = 'Risk: Rs' + Math.round(risk) + ' | Stop dist: Rs' + dist.toFixed(2) + ' | Target: Rs' + target.toFixed(2) + ' | RR 1:2.2';
    document.getElementById('mo-calc').style.color = 'var(--green)';
  } else if (entry > 0 && sl > 0) {
    document.getElementById('mo-calc').textContent = 'Stop too close (< 0.3%) — rejected to prevent huge qty';
    document.getElementById('mo-calc').style.color = 'var(--red)';
  }
}

async function placeManualOrder() {
  var sym = document.getElementById('mo-sym').value.trim().toUpperCase();
  var side = document.getElementById('mo-side').value;
  var entry = parseFloat(document.getElementById('mo-entry').value);
  var sl = parseFloat(document.getElementById('mo-sl').value);
  var qty = parseInt(document.getElementById('mo-qty').value);
  var st = document.getElementById('mo-status');
  if (!sym || !entry || !sl || !qty) { st.textContent = 'Fill all fields'; st.style.color='var(--red)'; return; }
  if (Math.abs(entry-sl)/entry < 0.003) { st.textContent = 'Stop too close — rejected'; st.style.color='var(--red)'; return; }
  st.textContent = 'Placing...'; st.style.color='var(--amber)';
  try {
    var r = await fetch('/api/place_order', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({symbol:sym, side:side, entry:entry, stop:sl, qty:qty})});
    var d = await r.json();
    if (d.ok) {
      st.textContent = 'Order placed: ' + side + ' ' + qty + 'x' + sym + ' @ Rs' + entry;
      st.style.color = 'var(--green)';
      refresh();
    } else {
      st.textContent = 'Failed: ' + (d.reason || 'unknown');
      st.style.color = 'var(--red)';
    }
  } catch(e) { st.textContent = 'Error: ' + e; st.style.color='var(--red)'; }
}


function fillOrder(sym, side, entry, sl) {
  document.getElementById('mo-sym').value = sym;
  document.getElementById('mo-side').value = side;
  document.getElementById('mo-entry').value = entry;
  document.getElementById('mo-sl').value = sl;
  calcSize();
  // Scroll to manual order panel
  document.getElementById('mo-sym').closest('.panel').scrollIntoView({behavior:'smooth'});
  document.getElementById('mo-sym').style.borderColor = '#00d4a0';
  setTimeout(function(){ document.getElementById('mo-sym').style.borderColor = 'rgba(255,255,255,.12)'; }, 2000);
  document.getElementById('mo-status').textContent = sym + ' loaded — verify prices before placing';
  document.getElementById('mo-status').style.color = 'var(--amber)';
}

async function refresh() {
  try {
    var r = await fetch('/api/data');
    var d = await r.json();

    document.getElementById('mkt-label').textContent = d.market_open ? 'Market Open' : 'Market Closed';
    document.getElementById('mkt-pill').className = 'status-pill' + (d.market_open ? '' : ' closed');
    document.getElementById('mkt-pulse').className = 'pulse' + (d.market_open ? '' : ' off');
    document.getElementById('last-upd').textContent = 'Updated ' + new Date().toLocaleTimeString('en-IN');

    if (d.broker) {
      var b = d.broker;
      document.getElementById('br-avail').textContent = '₹' + Math.round(b.available || 0).toLocaleString('en-IN');
      document.getElementById('br-used').textContent = '₹' + Math.round(b.used || 0).toLocaleString('en-IN');
      document.getElementById('br-total').textContent = '₹' + Math.round(b.total || 0).toLocaleString('en-IN');
      document.getElementById('br-name').textContent = b.broker || 'Paper';
      document.getElementById('mode-ind').textContent = b.mode === 'paper' ? 'PAPER MODE' : 'LIVE MODE';
    }

    var s = d.stats;
    var pv = Math.round(s.daily_pnl || 0);
    var pe = document.getElementById('m-pnl');
    pe.textContent = '₹' + (pv >= 0 ? '+' : '') + pv.toLocaleString('en-IN');
    pe.className = 'mv ' + (pv >= 0 ? 'mg' : 'mr');
    document.getElementById('m-pnl-s').textContent = 'Win: ' + fmt(s.win_rate, 1) + '% | ' + s.trades_today + ' trades';
    document.getElementById('m-trades').textContent = s.trades_today + ' / ' + s.max_trades;
    document.getElementById('m-trades-s').textContent = s.open_trades + ' open | ' + s.winners + ' wins ' + s.losers + ' loss';
    var lp = s.max_loss > 0 ? Math.min(s.daily_loss / s.max_loss * 100, 100) : 0;
    document.getElementById('m-loss').textContent = '₹' + Math.round(s.daily_loss || 0).toLocaleString('en-IN');
    document.getElementById('m-loss-b').style.width = lp + '%';
    document.getElementById('m-loss-s').textContent = 'Limit ₹' + Math.round(s.max_loss || 0).toLocaleString('en-IN');
    document.getElementById('m-zones').textContent = s.active_zones;
    document.getElementById('m-zones-s').textContent = s.active_alerts + ' alerts | ' + (s.alerts_fired || 0) + ' fired';
    var tp = Math.round(s.total_pnl || 0);
    var te = document.getElementById('m-total');
    te.textContent = '₹' + (tp >= 0 ? '+' : '') + tp.toLocaleString('en-IN');
    te.style.color = tp >= 0 ? 'var(--green)' : 'var(--red)';
    document.getElementById('m-total-s').textContent = (s.total_trades || 0) + ' total trades';

    var disc = d.discipline || {};
    var ls = disc.consecutive_losses || 0;
    document.getElementById('d-l').textContent = ls;
    document.getElementById('d-l').style.color = ls >= 2 ? 'var(--red)' : 'var(--text)';
    document.getElementById('d-t').textContent = fmt(disc.score_threshold || 0.62, 2);
    document.getElementById('d-op').textContent = (d.open_trades ? d.open_trades.length : 0) + '/1';
    document.getElementById('d-f').textContent = (d.session || {}).alerts_fired || 0;
    var paused = disc.is_paused;
    document.getElementById('d-st').textContent = paused ? 'PAUSED' : 'ACTIVE';
    document.getElementById('d-st').style.color = paused ? 'var(--red)' : 'var(--green)';
    document.getElementById('pb').style.display = paused ? 'flex' : 'none';
    if (paused && disc.pause_until) {
      try { document.getElementById('pr').textContent = ls + ' losses. Resumes ' + new Date(disc.pause_until).toLocaleTimeString('en-IN'); } catch(e) {}
    }

    if (d.live_equity && d.live_equity.length) {
      liveEqData = d.live_equity;
      if (eqMode === 'live') drawEqChart(liveEqData, '#00d4a0', 'rgba(0,212,160,.08)');
    }

    // Open trades
    document.getElementById('ob').textContent = d.open_trades ? d.open_trades.length : 0;
    if (!d.open_trades || !d.open_trades.length) {
      document.getElementById('otb').innerHTML = '<div class="es">No open trades</div>';
    } else {
      var h = '<table><thead><tr><th>Symbol</th><th>Side</th><th>Qty</th><th>Entry</th><th>Stop</th><th>Target</th><th>Score</th><th>Since</th></tr></thead><tbody>';
      for (var i = 0; i < d.open_trades.length; i++) {
        var t = d.open_trades[i];
        h += '<tr><td><strong>' + (t.symbol || '') + '</strong></td><td>' + tag(t.side, t.side === 'BUY' ? 'buy' : 'sell') + '</td><td>' + t.qty + '</td><td style="font-family:var(--mono)">₹' + fmt(t.entry) + '</td><td style="font-family:var(--mono);color:var(--red)">₹' + fmt(t.stop_loss) + '</td><td style="font-family:var(--mono);color:var(--green)">₹' + fmt(t.target) + '</td><td>' + sb(t.score || 0) + '</td><td style="color:var(--muted)">' + ago(t.open_time) + '</td></tr>';
      }
      document.getElementById('otb').innerHTML = h + '</tbody></table>';
    }

    // Alerts
    document.getElementById('ab').textContent = d.alerts ? d.alerts.length : 0;
    if (!d.alerts || !d.alerts.length) {
      document.getElementById('alb').innerHTML = '<div class="es">No active alerts</div>';
    } else {
      var h = '<table><thead><tr><th>Symbol</th><th>Zone</th><th>Alert ₹</th><th>Score</th><th>Flags</th></tr></thead><tbody>';
      for (var i = 0; i < Math.min(d.alerts.length, 15); i++) {
        var a = d.alerts[i], zt = (a.zone_type || 'SUPPLY').toLowerCase();
        var aside = a.zone_type === 'DEMAND' ? 'BUY' : 'SELL';
        var asl = a.zone_type === 'DEMAND' ? (a.zone_low * 0.994).toFixed(2) : (a.zone_high * 1.006).toFixed(2);
        h += '<tr style="cursor:pointer" onclick="openChart(\''+a.symbol+'\');fillOrder(\''+a.symbol+'\',\''+aside+'\',\''+fmt(a.alert_price)+'\',\''+asl+'\')" title="Click to fill order form"><td><strong>' + (a.symbol || '') + '</strong></td><td>' + tag(a.zone_type || '--', zt) + '</td><td style="font-family:var(--mono)">₹' + fmt(a.alert_price) + '</td><td>' + sb(a.zone_score || 0) + '</td><td>' + (a.zone_htf ? tag('HTF', 'htf') : '') + '</td></tr>';
      }
      document.getElementById('alb').innerHTML = h + '</tbody></table>';
    }

    // Zones
    document.getElementById('zb').textContent = d.zones ? d.zones.length : 0;
    if (!d.zones || !d.zones.length) {
      document.getElementById('znb').innerHTML = '<div class="es">No zones yet</div>';
    } else {
      var h = '<table><thead><tr><th>Symbol</th><th>Type</th><th>Zone ₹</th><th>Score</th><th>Flags</th><th>Age</th></tr></thead><tbody>';
      for (var i = 0; i < Math.min(d.zones.length, 15); i++) {
        var z = d.zones[i];
        var zside = z.type === 'DEMAND' ? 'BUY' : 'SELL';
        var zentry = z.type === 'DEMAND' ? (z.high * 1.001).toFixed(2) : (z.low * 0.999).toFixed(2);
        var zsl = z.type === 'DEMAND' ? (z.low * 0.994).toFixed(2) : (z.high * 1.006).toFixed(2);
        h += '<tr style="cursor:pointer" onclick="openChart(\''+z.symbol+'\');fillOrder(\''+z.symbol+'\',\''+zside+'\',\''+zentry+'\',\''+zsl+'\')" title="Click to fill order form"><td><strong>' + (z.symbol || '') + '</strong></td><td>' + tag(z.type, z.type === 'DEMAND' ? 'demand' : 'supply') + '</td><td style="font-family:var(--mono);font-size:11px">₹' + fmt(z.low, 0) + ' – ₹' + fmt(z.high, 0) + '</td><td>' + sb(z.score || 0) + '</td><td>' + (z.htf_aligned ? tag('HTF', 'htf') : '') + '</td><td style="color:var(--muted)">' + (z.age_bars || 0) + 'd</td></tr>';
      }
      document.getElementById('znb').innerHTML = h + '</tbody></table>';
    }

    // History
    document.getElementById('hb').textContent = d.history ? d.history.length : 0;
    if (!d.history || !d.history.length) {
      document.getElementById('hst').innerHTML = '<div class="es">No closed trades yet</div>';
    } else {
      var h = '<table><thead><tr><th>Symbol</th><th>Side</th><th>Entry</th><th>Exit</th><th>P&L</th><th>RR</th><th>Reason</th><th>When</th></tr></thead><tbody>';
      for (var i = 0; i < d.history.length; i++) {
        var t = d.history[i], won = (t.pnl || 0) > 0;
        h += '<tr><td><strong>' + (t.symbol || '') + '</strong></td><td>' + tag(t.side || '--', t.side === 'BUY' ? 'buy' : 'sell') + '</td><td style="font-family:var(--mono)">₹' + fmt(t.entry) + '</td><td style="font-family:var(--mono)">₹' + fmt(t.exit_price) + '</td><td>' + fmtRs(t.pnl) + '</td><td style="color:var(--muted)">' + (t.rr ? '1:' + fmt(t.rr, 1) : '--') + '</td><td>' + tag(t.exit_reason || '--', won ? 'win' : 'loss') + '</td><td style="color:var(--muted)">' + ago(t.close_time) + '</td></tr>';
      }
      document.getElementById('hst').innerHTML = h + '</tbody></table>';
    }

    if (prevPnl !== null && Math.abs((s.daily_pnl || 0) - prevPnl) > 1) {
      var diff = (s.daily_pnl || 0) - prevPnl, won = diff > 0;
      addLog(won ? 'var(--green)' : 'var(--red)', 'CLOSED', 'P&L ' + (diff >= 0 ? '+' : '') + Math.round(diff).toLocaleString('en-IN'), won ? 'WIN' : 'LOSS', won ? 'var(--green)' : 'var(--red)');
    }
    prevPnl = s.daily_pnl || 0;

  } catch(e) {
    console.error('Refresh error:', e);
    document.getElementById('mkt-label').textContent = 'Error: ' + e.message;
  }
}

refresh();
setInterval(refresh, 10000);
addLog('var(--purple)', 'BITTU', 'AI trading assistant online', 'READY', 'var(--purple)');
addLog('var(--blue)', 'SYSTEM', 'Money Printer v6 dashboard loaded', 'OK', 'var(--blue)');
</script>

<!-- CHART MODAL -->
<div id="chart-modal" style="display:none;position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,.85);z-index:1000;align-items:center;justify-content:center">
  <div style="background:#0d1320;border:1px solid rgba(255,255,255,.12);border-radius:16px;width:90vw;max-width:1100px;height:82vh;display:flex;flex-direction:column;overflow:hidden">
    <div style="display:flex;align-items:center;justify-content:space-between;padding:14px 18px;border-bottom:1px solid rgba(255,255,255,.08)">
      <div>
        <span style="font-size:16px;font-weight:700" id="chart-title">Chart</span>
        <span style="font-size:11px;color:#6b7a99;margin-left:10px" id="chart-sub"></span>
      </div>
      <div style="display:flex;gap:8px;align-items:center">
        <button onclick="switchTf('1d')" id="tf-1d" class="tf-btn on">Daily</button>
        <button onclick="switchTf('1wk')" id="tf-1wk" class="tf-btn">Weekly</button>
        <button onclick="switchTf('1mo')" id="tf-1mo" class="tf-btn">Monthly</button>
        <button onclick="closeChart()" style="background:rgba(255,77,106,.15);border:1px solid rgba(255,77,106,.3);color:#ff4d6a;padding:6px 14px;border-radius:6px;cursor:pointer;font-size:12px;font-weight:600">✕ Close</button>
      </div>
    </div>
    <div style="padding:10px 18px;display:flex;gap:16px;flex-wrap:wrap;font-size:11px" id="chart-legend"></div>
    <div style="flex:1;padding:0 12px 12px;min-height:0;position:relative">
      <div id="chart-loading" style="position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);color:#6b7a99;font-size:13px;display:none">Loading chart...</div>
      <div id="chart-canvas" style="width:100%;height:100%;min-height:480px"></div>
    </div>
  </div>
</div>
<style>
.tf-btn{background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.1);color:#6b7a99;padding:5px 12px;border-radius:6px;cursor:pointer;font-size:11px;font-weight:600;font-family:var(--font)}
.tf-btn.on{background:rgba(0,212,160,.12);border-color:rgba(0,212,160,.3);color:#00d4a0}
</style>

<script>

// ── CHART ──────────────────────────────────────────────────────────
var chartInstance = null;
var chartSymbol = null;
var chartTf = '1d';

async function openChart(sym) {
  chartSymbol = sym;
  chartTf = '1d';
  document.getElementById('chart-modal').style.display = 'flex';
  document.getElementById('chart-title').textContent = sym;
  await loadChart(sym, '1d');
}

function closeChart() {
  document.getElementById('chart-modal').style.display = 'none';
  if (chartInstance) { try { chartInstance.remove(); } catch(e){} chartInstance = null; }
  document.getElementById('chart-canvas').innerHTML = '';
}

async function switchTf(tf) {
  chartTf = tf;
  ['1d','1wk','1mo'].forEach(t => {
    document.getElementById('tf-'+t).className = 'tf-btn' + (t===tf?' on':'');
  });
  await loadChart(chartSymbol, tf);
}

async function loadChart(sym, tf) {
  document.getElementById('chart-sub').textContent = 'Loading...';
  document.getElementById('chart-loading').style.display = 'block';
  document.getElementById('chart-canvas').innerHTML = '';
  if (chartInstance) { try{chartInstance.remove();}catch(e){} chartInstance=null; }
  try {
    var r = await fetch('/api/chart/' + sym + '?tf=' + tf);
    var d = await r.json();
    document.getElementById('chart-loading').style.display = 'none';
    if (d.error) { document.getElementById('chart-sub').textContent = d.error; return; }
    renderChart(d, sym);
  } catch(e) {
    document.getElementById('chart-loading').style.display = 'none';
    document.getElementById('chart-sub').textContent = 'Error: ' + e;
  }
}

function renderChart(d, sym) {
  var candles = d.candles || [];
  var zones   = d.zones  || [];
  var trades  = d.trades || [];
  if (!candles.length) { document.getElementById('chart-sub').textContent = 'No data'; return; }

  document.getElementById('chart-sub').textContent = candles.length + ' bars | ' + zones.length + ' zones';

  var container = document.getElementById('chart-canvas');
  container.innerHTML = '';

  var chart = LightweightCharts.createChart(container, {
    width:  container.offsetWidth  || 900,
    height: container.offsetHeight || 520,
    layout: { background:{color:'transparent'}, textColor:'#6b7a99' },
    grid:   { vertLines:{color:'rgba(255,255,255,.04)'}, horzLines:{color:'rgba(255,255,255,.04)'} },
    crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
    rightPriceScale: { borderColor:'rgba(255,255,255,.08)' },
    timeScale: { borderColor:'rgba(255,255,255,.08)', timeVisible:true },
  });
  chartInstance = chart;

  // Candlestick series
  var cs = chart.addCandlestickSeries({
    upColor:'#00d4a0', downColor:'#ff4d6a',
    borderUpColor:'#00d4a0', borderDownColor:'#ff4d6a',
    wickUpColor:'#00d4a0', wickDownColor:'#ff4d6a',
  });
  cs.setData(candles.map(function(c){
    return {time:c.time, open:c.open, high:c.high, low:c.low, close:c.close};
  }));

  // Zone price lines
  zones.forEach(function(z) {
    var isDemand = z.type === 'DEMAND';
    var col = isDemand ? '#00d4a0' : '#ff4d6a';
    var tfs = (z.notes||'daily').toUpperCase();
    // High line
    cs.createPriceLine({price:z.high, color:col, lineWidth:1, lineStyle:LightweightCharts.LineStyle.Dashed,
      axisLabelVisible:true, title:z.type+' '+z.high.toFixed(0)+' ['+tfs+']'});
    // Low line
    cs.createPriceLine({price:z.low, color:col, lineWidth:1, lineStyle:LightweightCharts.LineStyle.Dashed,
      axisLabelVisible:false, title:''});
  });

  // Trade lines
  trades.forEach(function(t) {
    cs.createPriceLine({price:t.entry,    color:'#fbbf24', lineWidth:1.5, lineStyle:LightweightCharts.LineStyle.Dotted, axisLabelVisible:true, title:'Entry'});
    cs.createPriceLine({price:t.stop_loss,color:'#ff4d6a', lineWidth:1.5, lineStyle:LightweightCharts.LineStyle.Dotted, axisLabelVisible:true, title:'Stop'});
    cs.createPriceLine({price:t.target,   color:'#00d4a0', lineWidth:1.5, lineStyle:LightweightCharts.LineStyle.Dotted, axisLabelVisible:true, title:'Target'});
  });

  chart.timeScale().fitContent();

  // Resize observer
  var ro = new ResizeObserver(function(){
    chart.applyOptions({width:container.offsetWidth, height:container.offsetHeight});
  });
  ro.observe(container);

  // Legend
  var last = candles[candles.length-1];
  var leg = '<span style="color:#6b7a99">LTP: <strong style="color:#e8eaf0">&#8377;'+last.close.toLocaleString('en-IN')+'</strong></span> ';
  zones.forEach(function(z){
    var c = z.type==='DEMAND'?'#00d4a0':'#ff4d6a';
    leg += '<span style="margin-left:12px;color:'+c+'">&#9646; '+z.type+' &#8377;'+z.low+'-'+z.high+' '+(z.score||0).toFixed(2)+'</span>';
  });
  document.getElementById('chart-legend').innerHTML = leg;
}

// Close modal on backdrop click
document.getElementById('chart-modal').addEventListener('click', function(e) {
  if (e.target === this) closeChart();
});


</script>
</body>
</html>"""


@app.route("/")
def index():
    html = HTML.replace("CAPITAL_VAL", "{:,.0f}".format(CAPITAL))
    html = html.replace("CAPITAL_JS", str(CAPITAL))
    return html


@app.route("/api/data")
def api_data():
    from journal import query as jq, one as jo, ensure_session
    today = date.today().isoformat()
    cutoff = (datetime.now() - timedelta(days=30)).isoformat()
    now_time = datetime.now().strftime("%H:%M")
    market_open = MARKET_OPEN_TIME <= now_time <= MARKET_CLOSE_TIME

    ensure_session()

    session = jo("SELECT * FROM sessions WHERE session_date=?", (today,)) or {}
    disc = jo("SELECT * FROM discipline WHERE session_date=?", (today,)) or {
        "consecutive_losses": 0, "is_paused": 0, "score_threshold": 0.62, "pause_until": None
    }
    open_trades = jq("SELECT * FROM trades WHERE status='OPEN' ORDER BY open_time DESC")
    ltps = {}
    b = _get_broker()
    for t in open_trades:
        try:
            ltp = b.get_ltp(t["symbol"]) if b else None
            ltps[t["symbol"]] = ltp if ltp and ltp > 0 else t.get("entry", 0)
        except Exception:
            ltps[t["symbol"]] = t.get("entry", 0)

    now_iso = datetime.now().isoformat()
    alerts = jq(
        "SELECT a.*, z.type as zone_type, z.score as zone_score,"
        " z.low as zone_low, z.high as zone_high,"
        " z.htf_aligned as zone_htf, z.impulse_ratio as zone_explosive"
        " FROM alerts a JOIN zones z ON a.zone_id=z.id"
        " WHERE a.status='ACTIVE' AND a.expires_on > ? AND z.status='ACTIVE'"
        " ORDER BY z.score DESC LIMIT 50", (now_iso,)
    )
    zones = jq("SELECT * FROM zones WHERE status='ACTIVE' ORDER BY score DESC LIMIT 50")
    history = jq(
        "SELECT * FROM trades WHERE close_time IS NOT NULL AND close_time >= ?"
        " ORDER BY close_time DESC LIMIT 50", (cutoff,)
    )
    today_trades = jq("SELECT * FROM trades WHERE open_time LIKE ?", (today + "%",))
    all_closed = jq("SELECT pnl FROM trades WHERE close_time IS NOT NULL AND pnl IS NOT NULL")

    closed = [t for t in today_trades if t.get("close_time")]
    pnls = [t["pnl"] for t in closed if t.get("pnl") is not None]
    winners = [p for p in pnls if p > 0]
    losers = [p for p in pnls if p < 0]
    all_pnls = [t["pnl"] for t in all_closed]

    stats = {
        "daily_pnl": round(sum(pnls), 2),
        "daily_loss": round(sum(abs(p) for p in losers), 2),
        "max_loss": round(CAPITAL * MAX_DAILY_LOSS_PCT / 100.0, 2),
        "trades_today": len(today_trades),
        "max_trades": MAX_TRADES_PER_DAY,
        "open_trades": len(open_trades),
        "winners": len(winners), "losers": len(losers),
        "win_rate": round(len(winners) / len(pnls) * 100, 1) if pnls else 0,
        "active_zones": len(zones), "active_alerts": len(alerts),
        "alerts_fired": session.get("alerts_fired", 0),
        "total_pnl": round(sum(all_pnls), 2),
        "total_trades": len(all_pnls),
    }

    broker_status = {"mode": "paper", "paper": True, "available": CAPITAL,
                     "used": 0.0, "total": CAPITAL, "broker": "Paper"}
    if b:
        try:
            broker_status = b.get_status()
        except Exception:
            pass

    return jsonify({
        "market_open": market_open, "stats": stats,
        "discipline": dict(disc), "session": dict(session),
        "open_trades": open_trades, "ltps": ltps,
        "alerts": alerts, "zones": zones, "history": history,
        "backtest": _load_bt(), "broker": broker_status,
        "live_equity": _live_equity(),
    })


@app.route("/api/bittu", methods=["POST"])
def bittu_query():
    data = request.get_json() or {}
    query = data.get("query", "")
    if not query:
        return jsonify({"error": "No query"}), 400

    # Smart model selection based on query type
    deep_keywords = ["analyze", "why", "losing", "loss", "pattern", "config", "improve", "adapt", "strategy"]
    use_deep = any(k in query.lower() for k in deep_keywords)
    model = "phi4" if use_deep else "mistral"

    from journal import query as jq
    trades = jq("SELECT * FROM trades WHERE close_time IS NOT NULL AND pnl IS NOT NULL ORDER BY close_time DESC LIMIT 50")
    losses = [t for t in trades if (t.get("pnl") or 0) < 0]
    wins = [t for t in trades if (t.get("pnl") or 0) > 0]
    total_pnl = sum(t.get("pnl", 0) for t in trades)
    wr = len(wins) / len(trades) * 100 if trades else 0
    ctx = (
        f"You are BITTU, expert NSE algo trading assistant. Be concise — max 3 sentences, no bullet points. "
        f"Stats: {len(trades)} trades | WR {wr:.1f}% | P&L Rs{total_pnl:+,.0f} | "
        f"{len(losses)} losses | Config: MAX_OPEN=1, score=0.62, RR=2.2, risk=0.5%. "
        f"Query: {query}"
    )
    try:
        r = subprocess.run(["ollama", "run", model, ctx],
                           capture_output=True, text=True, timeout=90)
        resp = r.stdout.strip() or f"No response from {model}. Is Ollama running?"
        return jsonify({"response": resp, "model": model})
    except Exception as e:
        return jsonify({"error": str(e)}), 500



@app.route("/api/place_order", methods=["POST"])
def place_order():
    from broker import Broker
    import uuid
    data = request.get_json() or {}
    sym = data.get("symbol","").upper()
    side = data.get("side","BUY")
    entry = float(data.get("entry",0))
    stop = float(data.get("stop",0))
    qty = int(data.get("qty",0))
    if not sym or not entry or not stop or not qty:
        return jsonify({"ok":False,"reason":"Missing fields"})
    # Validate symbol against universe
    try:
        from universe import load_universe
        valid_symbols = load_universe()
        if sym not in valid_symbols:
            return jsonify({"ok":False,"reason":f"{sym} not in NSE universe — check symbol name"})
    except Exception:
        pass  # If universe check fails, allow trade
    dist = abs(entry-stop)
    if dist/entry < 0.003:
        return jsonify({"ok":False,"reason":"Stop too close — min 0.3% required"})
    target = entry + dist*2.2 if side=="BUY" else entry - dist*2.2
    b = _get_broker()
    result = b.place_order(sym, side, qty, entry) if b else {"ok":True,"order_id":"PAPER-manual"}
    if result.get("ok"):
        now = datetime.now().isoformat()
        today = date.today().isoformat()
        from journal import execute as je, ensure_session
        ensure_session()
        je("INSERT INTO trades (symbol,side,direction,qty,entry,stop_loss,target,peak_price,score,risk_pct,pattern,zone_id,zone_type,trail_stop,order_id,status,open_time,rr) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
           (sym,side,side,qty,entry,stop,round(target,2),entry,0.7,0.005,"MANUAL",0,"MANUAL",stop,result.get("order_id",f"PAPER-{uuid.uuid4().hex[:8]}"),"OPEN",now,2.2))
        return jsonify({"ok":True,"order_id":result.get("order_id")})
    return jsonify({"ok":False,"reason":result.get("error","Order failed")})


@app.route("/api/chart/<symbol>")
def chart_data(symbol):
    import yfinance as yf
    from journal import query as jq
    tf = request.args.get("tf", "1d")
    # Map tf to yfinance params
    tf_map = {
        "1d":  {"period": "6mo",  "interval": "1d"},
        "1wk": {"period": "2y",   "interval": "1wk"},
        "1mo": {"period": "5y",   "interval": "1mo"},
    }
    cfg = tf_map.get(tf, tf_map["1d"])
    try:
        df = yf.Ticker(f"{symbol}.NS").history(period=cfg["period"], interval=cfg["interval"])
        if df.empty:
            return jsonify({"error": f"No data for {symbol}"})
        candles = []
        for idx, row in df.iterrows():
            # Strip timezone and format as YYYY-MM-DD — fixes Chart.js date parse error
            try:
                ts = str(idx)
                date_str = ts[:10]  # YYYY-MM-DD
                # Validate format
                if len(date_str) != 10 or date_str[4] != "-":
                    continue
            except Exception:
                continue
            candles.append({
                "time":  date_str,
                "open":  round(float(row["Open"]),2),
                "high":  round(float(row["High"]),2),
                "low":   round(float(row["Low"]),2),
                "close": round(float(row["Close"]),2),
                "volume":int(row["Volume"])
            })
        zones = jq(
            "SELECT * FROM zones WHERE symbol=? AND status=\'ACTIVE\' ORDER BY score DESC",
            (symbol,)
        )
        trades = jq(
            "SELECT * FROM trades WHERE symbol=? AND status=\'OPEN\'", (symbol,)
        )
        return jsonify({"candles": candles, "zones": zones, "trades": trades, "tf": tf})
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route("/api/emergency_close", methods=["POST"])
def emergency_close():
    from journal import query as jq, execute as je
    open_trades = jq("SELECT * FROM trades WHERE status='OPEN'")
    now = datetime.now().isoformat()
    for t in open_trades:
        je("UPDATE trades SET status='CLOSED', exit_reason='EMERGENCY_CLOSE', "
           "close_time=?, exit_price=entry, pnl=0 WHERE id=?", (now, t["id"]))
    return jsonify({"ok": True, "closed": len(open_trades)})


if __name__ == "__main__":
    os.makedirs(os.path.expanduser("~/trading_bot/logs"), exist_ok=True)
    print(f"\n  Money Printer v6 -> http://localhost:{DASHBOARD_PORT}\n")
    app.run(host=DASHBOARD_HOST, port=DASHBOARD_PORT, debug=False)
