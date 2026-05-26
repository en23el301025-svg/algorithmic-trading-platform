"""
config.py — NSE Money Printer v6
All critical v5 fixes baked in from day one.
"""

import os

BASE_DIR = os.path.expanduser("~/trading_bot")

# ── BROKER ───────────────────────────────────────────────────────────
BROKER_NAME        = "dhan"
DHAN_CLIENT_ID     = "1107875240"
DHAN_ACCESS_TOKEN  = ""           # fill when going live
PAPER_TRADE        = True         # ← do NOT change until 10 profitable sessions

# ── CAPITAL ──────────────────────────────────────────────────────────
CAPITAL            = 20000

# ── RISK MANAGEMENT — Recovery profile ───────────────────────────────
RISK_PER_TRADE_PCT      = 0.5     # 0.5% per trade during recovery
MAX_TRADES_PER_DAY      = 2
MAX_OPEN_TRADES         = 1       # CRITICAL: was 28, caused ₹1.4L loss
MAX_DAILY_LOSS_PCT      = 1.0     # 1% = ₹200 max daily loss
MAX_CONSECUTIVE_LOSSES  = 2
PAUSE_AFTER_LOSS_MINS   = 60
MIN_SCORE_AFTER_LOSS    = 0.65

# ── ZONE SCORING ─────────────────────────────────────────────────────
BASE_SCORE_THRESHOLD    = 0.62    # below this = net negative in backtest
MIN_SCORE_THRESHOLD     = 0.45
ZONE_PROXIMITY_PCT      = 0.6
ALERT_PROXIMITY_PCT     = 2.0

# ── TRADE EXECUTION ──────────────────────────────────────────────────
TARGET_RR_RATIO         = 2.2     # was 1.2, now 2.2
MIN_RR_RATIO            = 1.8
TRAIL_ACTIVATION_R      = 1.0
TRAIL_OFFSET_PCT        = 0.25
MIN_STOP_DISTANCE_PCT   = 0.3     # CRITICAL: prevents penny stock 100k qty bug

# ── PATTERNS ─────────────────────────────────────────────────────────
ALLOWED_PATTERNS        = ["RBR", "DBD", "DBR", "RBD"]

# ── MARKET HOURS ─────────────────────────────────────────────────────
MARKET_OPEN_TIME        = "09:15"
MARKET_CLOSE_TIME       = "15:30"
SQUAREOFF_TIME          = "15:15"

# ── FILES ────────────────────────────────────────────────────────────
JOURNAL_DB              = os.path.join(BASE_DIR, "journal.db")
UNIVERSE_FILE           = os.path.join(BASE_DIR, "universe.csv")
LOG_DIR                 = os.path.join(BASE_DIR, "logs")
REPORTS_DIR             = os.path.join(BASE_DIR, "reports")
MEMORY_FILE             = os.path.join(BASE_DIR, "bittu_trading_memory.json")

# ── DASHBOARD ────────────────────────────────────────────────────────
DASHBOARD_PORT          = 9090
DASHBOARD_HOST          = "0.0.0.0"

# ── DISCORD ──────────────────────────────────────────────────────────
DISCORD_WEBHOOK_SIGNALS = ""
DISCORD_WEBHOOK_TRADES  = ""
DISCORD_WEBHOOK_ERRORS  = ""
DISCORD_WEBHOOK_REPORT  = ""

# ── SCANNING ─────────────────────────────────────────────────────────
SCAN_INTERVAL_SECS      = 60
ZONE_LOOKBACK_BARS      = 250
MIN_IMPULSE_RATIO       = 1.5
MIN_ZONE_TOUCHES        = 1
HTF_TIMEFRAME           = "1d"
LTF_TIMEFRAME           = "15m"
