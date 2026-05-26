"""
scanner.py — Multi-Timeframe Supply/Demand Zone Scanner v6
NSE Money Printer — Full MTF Confluence System

Timeframe Stack:
  Yearly  → Strongest zones, score boost +0.35
  6Month  → Institutional zones, score boost +0.25
  Monthly → Swing zones, score boost +0.20
  Weekly  → HTF trend zones, score boost +0.15
  Daily   → Trade setup zones, base score
  15Min   → Entry confirmation only

Confluence Rule:
  Daily zone overlaps Weekly  → score += 0.15
  Daily zone overlaps Monthly → score += 0.20
  Daily zone overlaps 6Month  → score += 0.25
  Daily zone overlaps Yearly  → score += 0.35
  Max score = 1.0
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from logger import get_logger
from config import BASE_SCORE_THRESHOLD, MIN_IMPULSE_RATIO, ZONE_LOOKBACK_BARS, ALLOWED_PATTERNS
import journal

log = get_logger("scanner")

TIMEFRAMES = {
    "yearly":  {"period": "5y",  "interval": "1mo", "boost": 0.35},
    "6month":  {"period": "3y",  "interval": "1wk", "boost": 0.25},
    "monthly": {"period": "2y",  "interval": "1wk", "boost": 0.20},
    "weekly":  {"period": "1y",  "interval": "1d",  "boost": 0.15},
    "daily":   {"period": "6mo", "interval": "1d",  "boost": 0.00},
}


def fetch_ohlcv(symbol, period="6mo", interval="1d"):
    try:
        import yfinance as yf
        df = yf.Ticker(f"{symbol}.NS").history(period=period, interval=interval)
        if df.empty:
            return pd.DataFrame()
        df = df[["Open","High","Low","Close","Volume"]].copy()
        df.columns = ["open","high","low","close","volume"]
        df.dropna(inplace=True)
        return df
    except Exception as e:
        log.debug(f"Fetch failed {symbol} {interval}: {e}")
        return pd.DataFrame()


def _base_score(impulse, vol_ratio, age):
    s = 0.0
    s += min(impulse / 5.0, 1.0) * 0.40
    s += min(vol_ratio / 5.0, 1.0) * 0.30
    s += max(0, 1.0 - age / 100) * 0.30
    return round(min(s, 0.65), 4)


def detect_raw_zones(df, symbol, timeframe):
    if df is None or len(df) < 10:
        return []
    zones = []
    df = df.tail(ZONE_LOOKBACK_BARS).reset_index(drop=True)
    n = len(df)
    for i in range(2, n - 2):
        c = df.iloc[i]; pr = df.iloc[i-1]; nx = df.iloc[i+1]
        base_size = max(c["high"] - c["low"], 0.001)
        avg_vol = df["volume"].iloc[max(0,i-20):i].mean()
        vol_ratio = nx["volume"] / max(avg_vol, 1)

        # DEMAND
        if (pr["close"] < pr["open"] and
            abs(c["close"] - c["open"]) < base_size * 0.6 and
            nx["close"] > nx["open"] and
            (nx["close"] - nx["open"]) > base_size * 0.4):
            imp = (nx["close"] - nx["open"]) / base_size
            if imp >= MIN_IMPULSE_RATIO * 0.8:
                pat = "RBR" if pr["close"] < pr["open"] else "DBR"
                if pat in ALLOWED_PATTERNS:
                    zones.append({"symbol":symbol,"type":"DEMAND",
                        "high":round(c["high"],2),"low":round(c["low"],2),
                        "impulse_ratio":round(imp,2),"volume_ratio":round(vol_ratio,2),
                        "age_bars":n-i,"formed_at_bar":i,"notes":pat,
                        "timeframe":timeframe,"raw_score":_base_score(imp,vol_ratio,n-i)})

        # SUPPLY
        if (pr["close"] > pr["open"] and
            abs(c["close"] - c["open"]) < base_size * 0.6 and
            nx["close"] < nx["open"] and
            (nx["open"] - nx["close"]) > base_size * 0.4):
            imp = (nx["open"] - nx["close"]) / base_size
            if imp >= MIN_IMPULSE_RATIO * 0.8:
                pat = "RBD" if pr["close"] > pr["open"] else "DBD"
                if pat in ALLOWED_PATTERNS:
                    zones.append({"symbol":symbol,"type":"SUPPLY",
                        "high":round(c["high"],2),"low":round(c["low"],2),
                        "impulse_ratio":round(imp,2),"volume_ratio":round(vol_ratio,2),
                        "age_bars":n-i,"formed_at_bar":i,"notes":pat,
                        "timeframe":timeframe,"raw_score":_base_score(imp,vol_ratio,n-i)})
    return zones


def _overlaps(z1, z2):
    return (z1["symbol"]==z2["symbol"] and z1["type"]==z2["type"] and
            z1["low"] < z2["high"] and z1["high"] > z2["low"])


def _overlap_pct(z1, z2):
    if not _overlaps(z1, z2): return 0.0
    overlap = min(z1["high"],z2["high"]) - max(z1["low"],z2["low"])
    smaller = min(z1["high"]-z1["low"], z2["high"]-z2["low"])
    return overlap / max(smaller, 0.001)


def detect_zones_mtf(symbol):
    """Full MTF zone detection with confluence scoring."""
    all_tf = {}
    for tf_name, cfg in TIMEFRAMES.items():
        df = fetch_ohlcv(symbol, cfg["period"], cfg["interval"])
        all_tf[tf_name] = detect_raw_zones(df, symbol, tf_name)

    daily = all_tf.get("daily", [])
    if not daily:
        return []

    htf_order = ["weekly","monthly","6month","yearly"]
    final = []

    for dz in daily:
        score = dz["raw_score"]
        htf_aligned = []

        for htf in htf_order:
            boost = TIMEFRAMES[htf]["boost"]
            for hz in all_tf.get(htf, []):
                if _overlaps(dz, hz) and _overlap_pct(dz, hz) > 0.3:
                    score += boost
                    htf_aligned.append(htf)
                    # Tighten zone to confluence region
                    dz["high"] = min(dz["high"], hz["high"])
                    dz["low"]  = max(dz["low"],  hz["low"])
                    break

        score = round(min(score, 1.0), 4)
        if score >= BASE_SCORE_THRESHOLD * 0.8:
            dz["score"] = score
            dz["htf_aligned"] = 1 if htf_aligned else 0
            dz["confluence_count"] = len(htf_aligned)
            dz["confluence_tfs"] = ",".join(htf_aligned) if htf_aligned else "daily"
            dz["status"] = "ACTIVE"
            final.append(dz)

    # Add standalone HTF zones (no daily overlap) — these are walls
    for htf in ["monthly","6month","yearly"]:
        boost = TIMEFRAMES[htf]["boost"]
        for hz in all_tf.get(htf, []):
            if not any(_overlaps(hz, dz) for dz in daily):
                hz["score"] = round(min(0.55 + boost * 2, 1.0), 4)
                hz["htf_aligned"] = 1
                hz["confluence_count"] = 0
                hz["confluence_tfs"] = htf
                hz["status"] = "ACTIVE"
                final.append(hz)

    final = _deduplicate(final)
    log.info(f"{symbol}: {len(final)} zones | {len([z for z in final if z.get('confluence_count',0)>0])} confluent")
    return final


# Keep backward compat — engine calls detect_zones()
def detect_zones(symbol):
    return detect_zones_mtf(symbol)


def _deduplicate(zones):
    zones.sort(key=lambda z: z["score"], reverse=True)
    kept = []
    for z in zones:
        if not any(k["symbol"]==z["symbol"] and k["type"]==z["type"] and
                   z["low"]<k["high"] and z["high"]>k["low"] for k in kept):
            kept.append(z)
    return kept


def save_zones(zones):
    saved = 0
    now = datetime.now().isoformat()
    for z in zones:
        existing = journal.query(
            "SELECT id FROM zones WHERE symbol=? AND type=? AND status='ACTIVE' "
            "AND ABS(high-?)<3 AND ABS(low-?)<3",
            (z["symbol"],z["type"],z["high"],z["low"])
        )
        if existing:
            journal.execute(
                "UPDATE zones SET score=?,htf_aligned=?,last_updated=?,notes=? WHERE id=?",
                (z["score"],z.get("htf_aligned",0),now,
                 z.get("confluence_tfs",z.get("notes","")),existing[0]["id"])
            )
            continue
        journal.execute(
            "INSERT INTO zones (symbol,type,high,low,score,impulse_ratio,"
            "volume_ratio,htf_aligned,age_bars,formed_at_bar,notes,status,"
            "detected_on,last_updated) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (z["symbol"],z["type"],z["high"],z["low"],z["score"],
             z.get("impulse_ratio",1.0),z.get("volume_ratio",1.0),
             z.get("htf_aligned",0),z.get("age_bars",0),z.get("formed_at_bar",0),
             z.get("confluence_tfs",z.get("notes","")),
             "ACTIVE",now,now)
        )
        saved += 1
    return saved


def set_alerts(symbol, ltp, zones):
    from config import ALERT_PROXIMITY_PCT
    fired = 0
    now = datetime.now().isoformat()
    expires = (datetime.now() + timedelta(days=14)).isoformat()
    for z in zones:
        if z.get("symbol") != symbol:
            continue
        alert_price = z["high"]*1.02 if z["type"]=="DEMAND" else z["low"]*0.98
        proximity = abs(ltp-(z["high"]+z["low"])/2)/ltp*100
        if proximity <= ALERT_PROXIMITY_PCT*3:
            existing = journal.query(
                "SELECT id FROM alerts WHERE symbol=? AND zone_id=? AND status='ACTIVE'",
                (symbol, z.get("id",0))
            )
            if not existing:
                journal.execute(
                    "INSERT INTO alerts (zone_id,symbol,alert_price,direction,"
                    "status,created_on,expires_on) VALUES (?,?,?,?,?,?,?)",
                    (z.get("id",0),symbol,round(alert_price,4),
                     "APPROACHING_FROM_ABOVE" if z["type"]=="DEMAND" else "APPROACHING_FROM_BELOW",
                     "ACTIVE",now,expires)
                )
                fired += 1
    return fired
