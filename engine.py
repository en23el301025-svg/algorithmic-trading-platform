"""
engine.py — Main trading loop for NSE Money Printer v6
Supply/Demand zone strategy with strict risk controls
"""

import time
import signal
import sys
from datetime import datetime, date
from logger import get_logger
from config import (
    SCAN_INTERVAL_SECS, MARKET_OPEN_TIME, MARKET_CLOSE_TIME,
    SQUAREOFF_TIME, BASE_SCORE_THRESHOLD, ZONE_PROXIMITY_PCT,
    ALERT_PROXIMITY_PCT, MAX_OPEN_TRADES, PAPER_TRADE
)
import journal
import scanner
import trade_manager
import risk
from broker import Broker
from universe import load_universe

log = get_logger("engine")
_running = True


def _signal_handler(sig, frame):
    global _running
    log.info("Shutdown signal received")
    _running = False


signal.signal(signal.SIGTERM, _signal_handler)
signal.signal(signal.SIGINT, _signal_handler)


def is_market_open() -> bool:
    now = datetime.now().strftime("%H:%M")
    return MARKET_OPEN_TIME <= now <= MARKET_CLOSE_TIME


def is_squareoff_time() -> bool:
    now = datetime.now().strftime("%H:%M")
    return now >= SQUAREOFF_TIME


def get_ltp_batch(symbols: list, broker) -> dict:
    """Get LTP for multiple symbols. Falls back to yfinance if broker fails."""
    ltps = {}
    for sym in symbols:
        try:
            ltp = broker.get_ltp(sym)
            if ltp and ltp > 0:
                ltps[sym] = ltp
            else:
                raise ValueError("No LTP from broker")
        except Exception:
            try:
                import yfinance as yf
                t = yf.Ticker(f"{sym}.NS")
                hist = t.history(period="1d", interval="1m")
                if not hist.empty:
                    ltps[sym] = float(hist["Close"].iloc[-1])
            except Exception:
                pass
    return ltps


def scan_and_alert(symbols: list, broker) -> int:
    """Scan universe for zones and set alerts."""
    total_zones = 0
    total_alerts = 0
    today = date.today().isoformat()

    log.info(f"Scanning {len(symbols)} symbols...")

    for sym in symbols:
        try:
            zones = scanner.detect_zones(sym)
            if zones:
                saved = scanner.save_zones(zones)
                total_zones += saved

            # Get LTP and set alerts
            db_zones = journal.query(
                "SELECT * FROM zones WHERE symbol=? AND status='ACTIVE' ORDER BY score DESC LIMIT 5",
                (sym,)
            )
            if db_zones:
                ltp = None
                try:
                    ltp = broker.get_ltp(sym)
                    if not ltp:
                        import yfinance as yf
                        hist = yf.Ticker(f"{sym}.NS").history(period="1d", interval="1m")
                        if not hist.empty:
                            ltp = float(hist["Close"].iloc[-1])
                except Exception:
                    pass

                if ltp:
                    fired = scanner.set_alerts(sym, ltp, db_zones)
                    total_alerts += fired

        except Exception as e:
            log.debug(f"Scan error {sym}: {e}")

    # Update session
    journal.execute(
        "UPDATE sessions SET scan_count=scan_count+1, zones_detected=zones_detected+? "
        "WHERE session_date=?", (total_zones, today)
    )

    log.info(f"Scan complete: {total_zones} new zones, {total_alerts} new alerts")
    return total_zones


def check_entries(symbols: list, broker) -> None:
    """Check if any symbol is near a zone and enter a trade."""
    # Hard gate: max open trades
    open_count = journal.query("SELECT COUNT(*) as c FROM trades WHERE status='OPEN'")[0]["c"]
    if open_count >= MAX_OPEN_TRADES:
        return

    # Check discipline
    ok, reason = risk.can_trade()
    if not ok:
        log.debug(f"Entry blocked: {reason}")
        return

    # Get score threshold (may be elevated after losses)
    today = date.today().isoformat()
    disc = journal.one("SELECT * FROM discipline WHERE session_date=?", (today,))
    score_threshold = disc.get("score_threshold", BASE_SCORE_THRESHOLD) if disc else BASE_SCORE_THRESHOLD

    # Check trades taken today
    trades_today = journal.query(
        "SELECT COUNT(*) as c FROM trades WHERE open_time LIKE ?",
        (today + "%",)
    )[0]["c"]
    from config import MAX_TRADES_PER_DAY
    if trades_today >= MAX_TRADES_PER_DAY:
        return

    # Get active zones near current price
    active_zones = journal.query(
        "SELECT * FROM zones WHERE status='ACTIVE' AND score >= ? "
        "ORDER BY score DESC LIMIT 100",
        (score_threshold,)
    )

    if not active_zones:
        return

    # Get LTPs for relevant symbols
    zone_symbols = list(set(z["symbol"] for z in active_zones))
    ltps = get_ltp_batch(zone_symbols[:20], broker)  # limit API calls

    for zone in active_zones:
        sym = zone["symbol"]
        ltp = ltps.get(sym)
        if not ltp:
            continue

        # Check proximity
        zone_high = zone["high"]
        zone_low = zone["low"]
        zone_mid = (zone_high + zone_low) / 2

        proximity_pct = abs(ltp - zone_mid) / zone_mid * 100

        if zone["type"] == "DEMAND":
            # Price should be near or just above demand zone
            if not (zone_low * 0.99 <= ltp <= zone_high * 1.005):
                continue

            # Entry at zone.high * 1.001, stop at zone.low * 0.994
            entry = zone_high * 1.001
            stop = zone_low * 0.994

            # Trend check: price should be above 20-day MA
            if not _trend_ok(sym, "BUY"):
                log.debug(f"Trend filter: {sym} BUY blocked (downtrend)")
                continue

            # Confirmation: need 2+ signals
            if not _has_confirmation(sym, "BUY", ltp):
                continue

            result = trade_manager.open_trade(
                broker, sym, "BUY", entry, stop,
                zone["id"], zone["type"],
                zone["score"], zone.get("notes", ""),
                bool(zone["htf_aligned"])
            )
            if result["ok"]:
                log.info(f"ENTRY: BUY {sym} zone={zone_low:.2f}-{zone_high:.2f} score={zone['score']:.2f}")
                _mark_zone_touched(zone["id"])
                return  # One trade at a time

        elif zone["type"] == "SUPPLY":
            # Price should be near or just below supply zone
            if not (zone_low * 0.995 <= ltp <= zone_high * 1.01):
                continue

            entry = zone_low * 0.999
            stop = zone_high * 1.006

            # Trend check
            if not _trend_ok(sym, "SELL"):
                log.debug(f"Trend filter: {sym} SELL blocked (uptrend)")
                continue

            if not _has_confirmation(sym, "SELL", ltp):
                continue

            result = trade_manager.open_trade(
                broker, sym, "SELL", entry, stop,
                zone["id"], zone["type"],
                zone["score"], zone.get("notes", ""),
                bool(zone["htf_aligned"])
            )
            if result["ok"]:
                log.info(f"ENTRY: SELL {sym} zone={zone_low:.2f}-{zone_high:.2f} score={zone['score']:.2f}")
                _mark_zone_touched(zone["id"])
                return


def _trend_ok(symbol: str, side: str) -> bool:
    """Check if trend aligns with trade direction using 20-day MA."""
    try:
        import yfinance as yf
        df = yf.Ticker(f"{symbol}.NS").history(period="1mo", interval="1d")
        if df.empty or len(df) < 5:
            return True  # Default allow if can't check
        ma20 = df["Close"].tail(20).mean()
        ltp = df["Close"].iloc[-1]
        if side == "BUY":
            return ltp > ma20
        else:
            return ltp < ma20
    except Exception:
        return True


def _has_confirmation(symbol: str, side: str, ltp: float) -> bool:
    """Require 2+ confirmation signals before entry."""
    signals = 0
    try:
        import yfinance as yf
        df = yf.Ticker(f"{symbol}.NS").history(period="5d", interval="15m")
        if df.empty or len(df) < 10:
            return False

        # Signal 1: RSI
        close = df["Close"]
        delta = close.diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = (-delta.clip(upper=0)).rolling(14).mean()
        rs = gain / loss.replace(0, 0.001)
        rsi = 100 - (100 / (1 + rs))
        last_rsi = rsi.iloc[-1]
        if side == "BUY" and last_rsi < 50:
            signals += 1
        elif side == "SELL" and last_rsi > 50:
            signals += 1

        # Signal 2: Price momentum
        if len(df) >= 3:
            if side == "BUY" and df["Close"].iloc[-1] > df["Close"].iloc[-3]:
                signals += 1
            elif side == "SELL" and df["Close"].iloc[-1] < df["Close"].iloc[-3]:
                signals += 1

        # Signal 3: Volume confirmation
        avg_vol = df["Volume"].tail(20).mean()
        last_vol = df["Volume"].iloc[-1]
        if last_vol > avg_vol * 1.2:
            signals += 1

    except Exception as e:
        log.debug(f"Confirmation check error: {e}")
        return True  # Allow if can't check

    return signals >= 2


def _mark_zone_touched(zone_id: int) -> None:
    """Mark zone as recently touched."""
    journal.execute(
        "UPDATE zones SET last_updated=? WHERE id=?",
        (datetime.now().isoformat(), zone_id)
    )


def main():
    log.info("=" * 55)
    log.info("  NSE Money Printer v6 — Engine Starting")
    log.info(f"  Mode: {'PAPER' if PAPER_TRADE else 'LIVE'}")
    log.info("=" * 55)

    broker = Broker()
    symbols = load_universe()
    journal.ensure_session()

    log.info(f"Universe: {len(symbols)} symbols loaded")

    scan_counter = 0
    SCAN_EVERY_N_LOOPS = 30  # Scan zones every 30 minutes (30 loops × 60s)

    while _running:
        try:
            today = date.today().isoformat()
            journal.ensure_session()

            if is_market_open():
                # EOD squareoff
                if is_squareoff_time():
                    open_count = journal.query(
                        "SELECT COUNT(*) as c FROM trades WHERE status='OPEN'"
                    )[0]["c"]
                    if open_count > 0:
                        log.info("EOD: Squaring off all positions")
                        trade_manager.eod_squareoff(broker)

                # Manage open trades every loop
                trade_manager.manage_open_trades(broker)

                # Scan for zones periodically
                if scan_counter % SCAN_EVERY_N_LOOPS == 0:
                    scan_and_alert(symbols, broker)

                # Check for entries every loop
                check_entries(symbols, broker)

            else:
                # Pre-market zone scan
                if scan_counter % 60 == 0:  # Every hour
                    log.info("Pre/Post market: running zone scan")
                    scan_and_alert(symbols, broker)

            scan_counter += 1

        except Exception as e:
            log.error(f"Engine loop error: {e}", exc_info=True)

        time.sleep(SCAN_INTERVAL_SECS)

    log.info("Engine stopped cleanly")


if __name__ == "__main__":
    main()
