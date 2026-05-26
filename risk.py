"""
risk.py — Position sizing & risk management for NSE Money Printer v6
CRITICAL FIX: MIN_STOP_DISTANCE_PCT prevents penny stock 100k qty disaster
"""

from config import (
    CAPITAL, RISK_PER_TRADE_PCT, MAX_OPEN_TRADES,
    MAX_DAILY_LOSS_PCT, MAX_CONSECUTIVE_LOSSES,
    MIN_STOP_DISTANCE_PCT, MIN_SCORE_AFTER_LOSS,
    BASE_SCORE_THRESHOLD
)
from logger import get_logger
import journal

log = get_logger("risk")


def check_stop_distance(entry: float, stop: float) -> tuple[bool, str]:
    """CRITICAL: Reject trades where stop is too close — prevents huge qty."""
    if entry <= 0:
        return False, "Invalid entry price"
    dist_pct = abs(entry - stop) / entry * 100
    if dist_pct < MIN_STOP_DISTANCE_PCT:
        return False, f"Stop too close: {dist_pct:.2f}% < {MIN_STOP_DISTANCE_PCT}% min"
    return True, "ok"


def size_position(entry: float, stop: float, capital: float = CAPITAL,
                  risk_pct: float = RISK_PER_TRADE_PCT) -> dict:
    """Calculate position size. Returns qty=0 if stop too close."""
    ok, reason = check_stop_distance(entry, stop)
    if not ok:
        log.warning(f"Position rejected: {reason}")
        return {"qty": 0, "risk_amount": 0, "stop_distance": 0, "reason": reason}

    risk_amount = capital * risk_pct / 100.0
    stop_distance = abs(entry - stop)
    qty = int(risk_amount / stop_distance)

    if qty <= 0:
        return {"qty": 0, "risk_amount": 0, "stop_distance": stop_distance,
                "reason": "Qty too small"}

    actual_risk = qty * stop_distance
    log.info(f"Position sized: qty={qty}, risk=₹{actual_risk:.0f} "
             f"({risk_pct}% of ₹{capital:.0f}), stop_dist=₹{stop_distance:.2f}")

    return {
        "qty": qty,
        "risk_amount": round(actual_risk, 2),
        "stop_distance": round(stop_distance, 2),
        "reason": "ok"
    }


def can_trade(symbol: str = None) -> tuple[bool, str]:
    """Check all risk gates before allowing a new trade."""
    from datetime import date, datetime
    today = date.today().isoformat()

    # Check open trades count
    open_trades = journal.query(
        "SELECT COUNT(*) as c FROM trades WHERE status='OPEN'"
    )
    open_count = open_trades[0]["c"] if open_trades else 0
    if open_count >= MAX_OPEN_TRADES:
        return False, f"Max open trades reached ({open_count}/{MAX_OPEN_TRADES})"

    # Check discipline
    disc = journal.one(
        "SELECT * FROM discipline WHERE session_date=?", (today,)
    )
    if not disc:
        journal.ensure_session()
        disc = journal.one(
            "SELECT * FROM discipline WHERE session_date=?", (today,)
        )

    # Check if paused
    if disc.get("is_paused"):
        pause_until = disc.get("pause_until")
        if pause_until:
            try:
                pu = datetime.fromisoformat(pause_until)
                if datetime.now() < pu:
                    return False, f"Trading paused until {pu.strftime('%H:%M')}"
                else:
                    # Unpause
                    journal.execute(
                        "UPDATE discipline SET is_paused=0, pause_until=NULL WHERE session_date=?",
                        (today,)
                    )
            except Exception:
                pass

    # Check daily loss
    daily_loss = disc.get("daily_loss", 0)
    max_loss = CAPITAL * MAX_DAILY_LOSS_PCT / 100.0
    if daily_loss >= max_loss:
        return False, f"Daily loss limit hit: ₹{daily_loss:.0f} >= ₹{max_loss:.0f}"

    # Check consecutive losses
    consec = disc.get("consecutive_losses", 0)
    if consec >= MAX_CONSECUTIVE_LOSSES:
        return False, f"Max consecutive losses: {consec}"

    return True, "ok"


def record_trade_result(pnl: float):
    """Update discipline after a trade closes."""
    from datetime import date, datetime, timedelta
    from config import PAUSE_AFTER_LOSS_MINS
    today = date.today().isoformat()

    disc = journal.one("SELECT * FROM discipline WHERE session_date=?", (today,))
    if not disc:
        journal.ensure_session()
        disc = journal.one("SELECT * FROM discipline WHERE session_date=?", (today,))

    consec = disc.get("consecutive_losses", 0)
    daily_loss = disc.get("daily_loss", 0)
    daily_pnl = disc.get("daily_pnl", 0)

    if pnl < 0:
        consec += 1
        daily_loss += abs(pnl)
        should_pause = consec >= MAX_CONSECUTIVE_LOSSES
        pause_until = None
        if should_pause:
            pause_until = (datetime.now() + timedelta(minutes=PAUSE_AFTER_LOSS_MINS)).isoformat()
            log.warning(f"Pausing trading for {PAUSE_AFTER_LOSS_MINS} mins after {consec} losses")
        journal.execute(
            "UPDATE discipline SET consecutive_losses=?, daily_loss=?, daily_pnl=?, "
            "is_paused=?, pause_until=? WHERE session_date=?",
            (consec, daily_loss, daily_pnl + pnl,
             1 if should_pause else 0, pause_until, today)
        )
    else:
        journal.execute(
            "UPDATE discipline SET consecutive_losses=0, daily_pnl=? WHERE session_date=?",
            (daily_pnl + pnl, today)
        )
