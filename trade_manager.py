"""
trade_manager.py — Trade lifecycle management for NSE Money Printer v6
Handles entries, exits, trailing stops, partial targets
"""

import uuid
from datetime import datetime
from logger import get_logger

def _get_ltp(broker, symbol: str, fallback: float) -> float:
    """Get LTP from broker, fallback to yfinance, then entry price."""
    try:
        ltp = broker.get_ltp(symbol)
        if ltp and ltp > 0:
            return ltp
    except Exception:
        pass
    # Fallback to yfinance
    try:
        import yfinance as yf
        hist = yf.Ticker(f"{symbol}.NS").history(period="1d", interval="1m")
        if not hist.empty:
            return float(hist["Close"].iloc[-1])
    except Exception:
        pass
    return fallback
from config import (
    TARGET_RR_RATIO, MIN_RR_RATIO, TRAIL_ACTIVATION_R,
    TRAIL_OFFSET_PCT, CAPITAL, RISK_PER_TRADE_PCT
)
import journal
import risk

log = get_logger("trade_manager")


def open_trade(broker, symbol: str, side: str, entry: float,
               stop: float, zone_id: int, zone_type: str,
               score: float, pattern: str = "", htf_aligned: bool = False) -> dict:
    """Open a new trade after all checks pass."""

    # Risk gate
    ok, reason = risk.can_trade(symbol)
    if not ok:
        log.info(f"Trade blocked for {symbol}: {reason}")
        return {"ok": False, "reason": reason}

    # Stop distance check (penny stock protection)
    ok, reason = risk.check_stop_distance(entry, stop)
    if not ok:
        log.warning(f"Stop distance rejected for {symbol}: {reason}")
        return {"ok": False, "reason": reason}

    # Position size
    pos = risk.size_position(entry, stop)
    if pos["qty"] <= 0:
        log.warning(f"Position sizing failed for {symbol}: {pos['reason']}")
        return {"ok": False, "reason": pos["reason"]}

    qty = pos["qty"]
    stop_dist = abs(entry - stop)
    target = entry + (stop_dist * TARGET_RR_RATIO) if side == "BUY" else entry - (stop_dist * TARGET_RR_RATIO)
    partial_target = entry + (stop_dist * 1.0) if side == "BUY" else entry - (stop_dist * 1.0)

    # Check RR
    rr = abs(target - entry) / abs(stop - entry) if abs(stop - entry) > 0 else 0
    if rr < MIN_RR_RATIO:
        return {"ok": False, "reason": f"RR too low: {rr:.2f}"}

    # Place order
    result = broker.place_order(symbol, side, qty, entry)
    if not result.get("ok"):
        log.error(f"Order failed for {symbol}: {result.get('error')}")
        return {"ok": False, "reason": result.get("error", "Order failed")}

    fill_price = result.get("fill_price", entry)
    order_id = result.get("order_id", f"PAPER-{uuid.uuid4().hex[:12]}")
    now = datetime.now().isoformat()

    trade_id = journal.execute(
        "INSERT INTO trades (symbol, side, direction, qty, entry, stop_loss, target, "
        "partial_target, peak_price, score, risk_pct, pattern, zone_id, zone_type, "
        "htf_aligned, trail_stop, order_id, status, open_time, rr) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (symbol, side, side, qty, fill_price, stop, round(target, 2),
         round(partial_target, 2), fill_price, score,
         RISK_PER_TRADE_PCT / 100.0, pattern, zone_id, zone_type,
         1 if htf_aligned else 0, stop, order_id, "OPEN", now, round(rr, 2))
    )

    # Update session
    today = datetime.now().date().isoformat()
    journal.execute(
        "UPDATE sessions SET trades_taken = trades_taken + 1 WHERE session_date=?",
        (today,)
    )
    journal.execute(
        "UPDATE discipline SET trades_taken = trades_taken + 1 WHERE session_date=?",
        (today,)
    )

    log.info(
        f"TRADE OPENED: {side} {qty}x{symbol} @ {fill_price:.2f} "
        f"SL={stop:.2f} TP={target:.2f} RR={rr:.1f} [{order_id}]"
    )

    return {
        "ok": True, "trade_id": trade_id, "order_id": order_id,
        "qty": qty, "entry": fill_price, "stop": stop,
        "target": round(target, 2), "rr": round(rr, 2)
    }


def manage_open_trades(broker) -> None:
    """Check all open trades — update stops, check exits."""
    open_trades = journal.query("SELECT * FROM trades WHERE status='OPEN'")
    if not open_trades:
        return

    for t in open_trades:
        try:
            _manage_trade(broker, t)
        except Exception as e:
            log.error(f"Error managing trade {t['id']} {t['symbol']}: {e}")


def _manage_trade(broker, t: dict) -> None:
    """Manage a single open trade."""
    symbol = t["symbol"]
    side = t["side"]
    entry = t["entry"]
    stop = t["stop_loss"]
    target = t["target"]
    trail_active = t["trail_active"]
    trail_stop = t["trail_stop"] or stop
    peak = t["peak_price"] or entry
    partial_done = t["partial_done"]

    # Get current price
    ltp = _get_ltp(broker, symbol, 0)
    if not ltp or ltp <= 0:
        return

    now = datetime.now().isoformat()
    stop_dist = abs(entry - stop)

    # Update peak price
    if side == "BUY":
        new_peak = max(peak, ltp)
    else:
        new_peak = min(peak, ltp)

    if new_peak != peak:
        journal.execute(
            "UPDATE trades SET peak_price=? WHERE id=?", (new_peak, t["id"])
        )

    # ── PARTIAL TARGET ────────────────────────────────────────────
    partial_target = t.get("partial_target")
    if partial_target and not partial_done:
        hit_partial = (side == "BUY" and ltp >= partial_target) or \
                      (side == "SELL" and ltp <= partial_target)
        if hit_partial:
            partial_qty = max(1, t["qty"] // 2)
            broker.place_order(symbol, "SELL" if side == "BUY" else "BUY",
                               partial_qty, ltp)
            log.info(f"PARTIAL EXIT: {symbol} {partial_qty}@{ltp:.2f}")
            journal.execute(
                "UPDATE trades SET partial_done=1 WHERE id=?", (t["id"],)
            )
            # Move stop to breakeven after partial
            new_stop = entry * (1.001 if side == "BUY" else 0.999)
            journal.execute(
                "UPDATE trades SET stop_loss=?, trail_stop=? WHERE id=?",
                (round(new_stop, 2), round(new_stop, 2), t["id"])
            )
            stop = new_stop
            trail_stop = new_stop

    # ── TRAIL STOP ACTIVATION ────────────────────────────────────
    r_multiple = (ltp - entry) / stop_dist if side == "BUY" else (entry - ltp) / stop_dist
    if r_multiple >= TRAIL_ACTIVATION_R and not trail_active:
        journal.execute(
            "UPDATE trades SET trail_active=1 WHERE id=?", (t["id"],)
        )
        trail_active = 1
        log.info(f"TRAIL ACTIVATED: {symbol} @ {ltp:.2f} ({r_multiple:.1f}R)")

    # ── UPDATE TRAIL STOP ─────────────────────────────────────────
    if trail_active:
        offset = ltp * TRAIL_OFFSET_PCT / 100.0
        if side == "BUY":
            new_trail = ltp - offset
            if new_trail > trail_stop:
                trail_stop = new_trail
                journal.execute(
                    "UPDATE trades SET trail_stop=?, stop_loss=? WHERE id=?",
                    (round(trail_stop, 2), round(trail_stop, 2), t["id"])
                )
        else:
            new_trail = ltp + offset
            if new_trail < trail_stop:
                trail_stop = new_trail
                journal.execute(
                    "UPDATE trades SET trail_stop=?, stop_loss=? WHERE id=?",
                    (round(trail_stop, 2), round(trail_stop, 2), t["id"])
                )

    # ── CHECK EXITS ───────────────────────────────────────────────
    exit_reason = None
    exit_price = ltp

    if side == "BUY":
        if ltp <= stop:
            exit_reason = "TRAIL_STOP" if trail_active else "STOP_HIT"
        elif ltp >= target:
            exit_reason = "TARGET_HIT"
    else:
        if ltp >= stop:
            exit_reason = "TRAIL_STOP" if trail_active else "STOP_HIT"
        elif ltp <= target:
            exit_reason = "TARGET_HIT"

    if exit_reason:
        _close_trade(broker, t, exit_price, exit_reason)


def _close_trade(broker, t: dict, exit_price: float, reason: str) -> None:
    """Close a trade and record P&L."""
    symbol = t["symbol"]
    side = t["side"]
    qty = t["qty"]
    entry = t["entry"]
    stop = t["stop_loss"]

    # Place exit order
    exit_side = "SELL" if side == "BUY" else "BUY"
    broker.place_order(symbol, exit_side, qty, exit_price)

    # Calculate P&L
    if side == "BUY":
        pnl = (exit_price - entry) * qty
    else:
        pnl = (entry - exit_price) * qty

    stop_dist = abs(entry - stop)
    rr = (exit_price - entry) / stop_dist if side == "BUY" else (entry - exit_price) / stop_dist
    now = datetime.now().isoformat()

    journal.execute(
        "UPDATE trades SET status='CLOSED', exit_price=?, exit_reason=?, "
        "pnl=?, rr=?, close_time=? WHERE id=?",
        (round(exit_price, 2), reason, round(pnl, 2), round(rr, 2), now, t["id"])
    )

    # Update session
    today = datetime.now().date().isoformat()
    won = pnl > 0
    journal.execute(
        f"UPDATE sessions SET {'winners' if won else 'losers'} = "
        f"{'winners' if won else 'losers'} + 1, net_pnl = net_pnl + ? "
        f"WHERE session_date=?", (pnl, today)
    )

    # Update risk discipline
    risk.record_trade_result(pnl)

    log.info(
        f"TRADE CLOSED: {symbol} {side} @ {exit_price:.2f} | "
        f"P&L: Rs{pnl:+.2f} | RR: {rr:.2f} | Reason: {reason}"
    )


def close_all_trades(broker) -> int:
    """Emergency close all open trades."""
    open_trades = journal.query("SELECT * FROM trades WHERE status='OPEN'")
    for t in open_trades:
        ltp = _get_ltp(broker, t["symbol"], t["entry"])
        _close_trade(broker, t, ltp, "EMERGENCY_CLOSE")
    log.warning(f"EMERGENCY CLOSE: {len(open_trades)} trades closed")
    return len(open_trades)


def eod_squareoff(broker) -> int:
    """Square off all positions at EOD."""
    open_trades = journal.query("SELECT * FROM trades WHERE status='OPEN'")
    for t in open_trades:
        ltp = _get_ltp(broker, t["symbol"], t["entry"])
        _close_trade(broker, t, ltp, "EOD_SQUAREOFF")
    log.info(f"EOD squareoff: {len(open_trades)} trades closed")
    return len(open_trades)
