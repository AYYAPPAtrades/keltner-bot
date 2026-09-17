"""
MOMENTUM SPIKE BOT V4 - Professional Research/Alert Engine
===========================================================
- Secure Telegram configuration via environment variables
- Email PDF daily + NIFTY monthly-expiry report
- 09:00–15:40 runtime guard + weekend/holiday reason alerts
- Resilient outer-loop retry on transient runtime exceptions
- Robust HTTP/NSE/yfinance retry handling
- Timestamp/staleness validation
- 5-minute OHLC engine using timestamp buckets
- EMA5 + candle-quality + breakout confirmation
- Duplicate protection and daily/consecutive-loss limits
- T1 -> breakeven
- Persistent trade/event audit log
- Realistic-ish index-level backtest with costs/slippage
- IMPORTANT: This is an alert/research system, not an order execution system.
- IMPORTANT: BUY/SELL below refer to the INDEX direction. It does not select CE/PE contracts.
"""

from __future__ import annotations

import csv
import json
import os
import time
import uuid
import smtplib
import tempfile
import threading
import queue
from dataclasses import dataclass
from datetime import datetime, timedelta, time as dtime
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests
import yfinance as yf
from nselib import capital_market

try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    REPORTLAB_OK = True
except Exception:
    REPORTLAB_OK = False


VERSION = "V4.4"

# =========================
# CONFIG
# =========================

IST = ZoneInfo("Asia/Kolkata")

INDEX_WATCHLIST = ["NIFTY 50", "NIFTY BANK"]
YF_TICKERS = {"NIFTY 50": "^NSEI", "NIFTY BANK": "^NSEBANK"}

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "6789591588").strip()

EMAIL_SMTP_HOST = os.getenv("EMAIL_SMTP_HOST", "smtp.gmail.com").strip()
EMAIL_SMTP_PORT = int(os.getenv("EMAIL_SMTP_PORT", "465"))
REPORT_EMAIL_SENDER = os.getenv("REPORT_EMAIL_SENDER", "shinos99@gmail.com").strip()
REPORT_EMAIL_PASSWORD = os.getenv("REPORT_EMAIL_PASSWORD", "").strip()
REPORT_EMAIL_RECIPIENT = os.getenv("REPORT_EMAIL_RECIPIENT", "shinos99@gmail.com").strip()

DATA_DIR = Path(os.getenv("BOT_DATA_DIR", "."))
REPORT_DIR = DATA_DIR / "reports"
TRADE_FILE = DATA_DIR / "active_trades_v4.json"
EVENT_LOG_FILE = DATA_DIR / "trade_events_v4.csv"
BACKTEST_LOG_FILE = DATA_DIR / "backtest_results_v4.csv"

REQUEST_TIMEOUT = 3
LOOP_SECONDS = 5
TELEGRAM_QUEUE_MAX = 200
TELEGRAM_SHUTDOWN_WAIT_SECONDS = 4
MAX_DATA_AGE_SECONDS = 45
MAX_CONSECUTIVE_DATA_ERRORS = 6

# NSE trading-holiday guard. Keep this list configurable/updateable.
# The bot stays alive outside market hours, but on a listed holiday it will
# send one reason alert and will not enter the market-processing loop.
# NSE trading holidays (2026). Additional dates can be supplied via
# NSE_HOLIDAYS_EXTRA=YYYY-MM-DD,YYYY-MM-DD,... without changing the code.
NSE_HOLIDAYS = {
    # Republic Day
    datetime(2026, 1, 26, tzinfo=IST).date(),
    # Mahashivratri
    datetime(2026, 2, 15, tzinfo=IST).date(),
    # Holi
    datetime(2026, 3, 4, tzinfo=IST).date(),
    # Ram Navami
    datetime(2026, 3, 26, tzinfo=IST).date(),
    # Mahavir Jayanti
    datetime(2026, 3, 31, tzinfo=IST).date(),
    # Good Friday
    datetime(2026, 4, 3, tzinfo=IST).date(),
    # Dr. Ambedkar Jayanti
    datetime(2026, 4, 14, tzinfo=IST).date(),
    # Maharashtra Day
    datetime(2026, 5, 1, tzinfo=IST).date(),
    # Bakri Id
    datetime(2026, 5, 27, tzinfo=IST).date(),
    # Muharram
    datetime(2026, 6, 26, tzinfo=IST).date(),
    # Independence Day (Saturday, included for completeness)
    datetime(2026, 8, 15, tzinfo=IST).date(),
    # Ganesh Chaturthi
    datetime(2026, 9, 14, tzinfo=IST).date(),
    # Mahatma Gandhi Jayanti
    datetime(2026, 10, 2, tzinfo=IST).date(),
    # Dussehra
    datetime(2026, 10, 20, tzinfo=IST).date(),
    # Diwali Laxmi Pujan
    datetime(2026, 11, 9, tzinfo=IST).date(),
    # Diwali Balipratipada
    datetime(2026, 11, 10, tzinfo=IST).date(),
    # Guru Nanak Jayanti
    datetime(2026, 11, 24, tzinfo=IST).date(),
    # Christmas
    datetime(2026, 12, 25, tzinfo=IST).date(),
}
_extra_holidays = os.getenv("NSE_HOLIDAYS_EXTRA", "")
for _item in _extra_holidays.split(","):
    _item = _item.strip()
    if _item:
        try:
            NSE_HOLIDAYS.add(datetime.fromisoformat(_item).date())
        except ValueError:
            print(f"Ignoring invalid NSE_HOLIDAYS_EXTRA date: {_item}")
HOLIDAY_ALERT_ONCE = True
BOT_WATCHDOG_SECONDS = 30

BOT_START = dtime(9, 0)
TRADE_START = dtime(9, 30)
TRADE_END = dtime(15, 20)
FORCE_EXIT = dtime(15, 20)
SHUTDOWN = dtime(15, 40)

MIN_RISK_POINTS = 8.0
BREAKOUT_BUFFER_POINTS = 1.0
MIN_CANDLE_BODY_RATIO = 0.35

# Early-exit protection: require two completed 5-minute candles to confirm
# a reversal against the open position.
REVERSAL_CONFIRM_CANDLES = 2
EARLY_EXIT_ENABLED = True

MAX_DAILY_SIGNALS = 5
MAX_DAILY_LOSSES = 3
MAX_CONSECUTIVE_LOSSES = 2

TARGET_R = (1.5, 2.0, 3.0)

# Research/backtest costs. These are index-point assumptions, not brokerage advice.
BACKTEST_SLIPPAGE_POINTS = 0.50
BACKTEST_COST_POINTS = 0.50

REPORT_DIR.mkdir(parents=True, exist_ok=True)
DATA_DIR.mkdir(parents=True, exist_ok=True)


# =========================
# RUNTIME GUARD / HOLIDAY HELPERS
# =========================

_last_main_loop_heartbeat = time.monotonic()
_last_holiday_alert_date = None


def is_weekend_or_holiday(d) -> tuple[bool, str]:
    if d.weekday() >= 5:
        return True, "Weekend / NSE market closed"
    if d in NSE_HOLIDAYS:
        return True, "NSE trading holiday"
    return False, ""


def send_market_closed_alert_once(day: datetime) -> None:
    global _last_holiday_alert_date
    closed, reason = is_weekend_or_holiday(day.date())
    if not closed:
        return
    key = f"{day.date().isoformat()}:{reason}"
    if HOLIDAY_ALERT_ONCE and _last_holiday_alert_date == key:
        return
    _last_holiday_alert_date = key
    send_telegram_alert(
        f"🛑 BOT NOT RUNNING — MARKET CLOSED\\n"
        f"Date: {day.strftime('%d-%b-%Y')}\\n"
        f"Reason: {reason}\\n"
        f"Runtime window: 09:00–15:40 IST"
    )


def watchdog_touch() -> None:
    global _last_main_loop_heartbeat
    _last_main_loop_heartbeat = time.monotonic()


# =========================
# RUNTIME STATE
# =========================

trade_stats = {
    "date": None,
    "total_signals": 0,
    "completed_trades": 0,
    "target_hits": 0,
    "sl_hits": 0,
    "daily_losses": 0,
    "consecutive_losses": 0,
    "points": 0.0,
}

prev_close_dict: Dict[str, float] = {}
last_price_time: Dict[str, datetime] = {}
last_heartbeat_hour = -1
last_data_error_count = 0
levels_sent_today = False
last_report_date = None

active_trades: Dict[str, Optional[dict]] = {
    idx: None for idx in INDEX_WATCHLIST
}

candle_history: Dict[str, List[dict]] = {idx: [] for idx in INDEX_WATCHLIST}
current_candles: Dict[str, dict] = {
    idx: {
        "open": None,
        "high": None,
        "low": None,
        "close": None,
        "bucket": None,
    }
    for idx in INDEX_WATCHLIST
}

alert_candles: Dict[str, dict] = {
    idx: {"sell_alert": None, "buy_alert": None} for idx in INDEX_WATCHLIST
}


# =========================
# UTILITIES
# =========================

def now_ist() -> datetime:
    return datetime.now(IST)


def atomic_json_save(path: Path, payload: Any) -> None:
    """Atomic state save to reduce corruption risk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.remove(tmp_name)


def load_trades() -> Dict[str, Optional[dict]]:
    default = {idx: None for idx in INDEX_WATCHLIST}
    if not TRADE_FILE.exists():
        return default
    try:
        with open(TRADE_FILE, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        for idx in INDEX_WATCHLIST:
            default[idx] = loaded.get(idx)
        return default
    except Exception as e:
        print(f"Trade-state load error: {e}")
        return default


def save_trades(trades: Dict[str, Optional[dict]]) -> None:
    atomic_json_save(TRADE_FILE, trades)


def ensure_event_log() -> None:
    if EVENT_LOG_FILE.exists():
        return
    with open(EVENT_LOG_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "event_id", "timestamp", "date", "index", "event",
            "side", "entry", "exit", "sl", "t1", "t2", "t3",
            "points", "r_multiple", "note"
        ])


def log_event(
    event: str,
    index_name: str,
    trade: Optional[dict] = None,
    exit_price: Optional[float] = None,
    points: Optional[float] = None,
    r_multiple: Optional[float] = None,
    note: str = "",
) -> None:
    ensure_event_log()
    trade = trade or {}
    ts = now_ist()
    with open(EVENT_LOG_FILE, "a", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow([
            uuid.uuid4().hex[:12],
            ts.isoformat(),
            ts.date().isoformat(),
            index_name,
            event,
            trade.get("type", ""),
            trade.get("entry", ""),
            exit_price if exit_price is not None else "",
            trade.get("sl", ""),
            trade.get("t1", ""),
            trade.get("t2", ""),
            trade.get("t3", ""),
            "" if points is None else round(points, 2),
            "" if r_multiple is None else round(r_multiple, 3),
            note,
        ])


# Telegram is sent from a dedicated worker so a slow Telegram HTTP request
# never blocks market-data polling / signal generation.
telegram_queue: "queue.PriorityQueue[tuple[int, int, str]]" = queue.PriorityQueue(maxsize=TELEGRAM_QUEUE_MAX)
telegram_stop = threading.Event()
telegram_worker_thread: Optional[threading.Thread] = None
telegram_seq = 0
telegram_session: Optional[requests.Session] = None


def _telegram_priority(message: str) -> int:
    urgent = (
        "SIGNAL", "EARLY EXIT", "SL", "BREAKEVEN", "T1 HIT", "T2 HIT",
        "T3 HIT", "TARGET3", "AUTO EXIT", "DATA WARNING"
    )
    return 0 if any(tag in message for tag in urgent) else 10


def _telegram_worker() -> None:
    global telegram_session
    telegram_session = requests.Session()
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    while not telegram_stop.is_set() or not telegram_queue.empty():
        try:
            _, _, message = telegram_queue.get(timeout=0.25)
        except queue.Empty:
            continue
        try:
            telegram_session.post(
                url,
                json={
                    "chat_id": TELEGRAM_CHAT_ID,
                    "text": message,
                    "disable_web_page_preview": True,
                },
                timeout=REQUEST_TIMEOUT,
            ).raise_for_status()
        except Exception as e:
            print(f"Telegram Error: {e}")
        finally:
            telegram_queue.task_done()

    if telegram_session is not None:
        telegram_session.close()
        telegram_session = None


def start_telegram_worker() -> None:
    global telegram_worker_thread
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram credentials not configured.")
        return
    if telegram_worker_thread and telegram_worker_thread.is_alive():
        return
    telegram_stop.clear()
    telegram_worker_thread = threading.Thread(
        target=_telegram_worker,
        name="telegram-alert-worker",
        daemon=True,
    )
    telegram_worker_thread.start()


def stop_telegram_worker() -> None:
    if not telegram_worker_thread:
        return
    telegram_stop.set()
    telegram_worker_thread.join(timeout=TELEGRAM_SHUTDOWN_WAIT_SECONDS)


def send_telegram_alert(message: str) -> bool:
    global telegram_seq
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram credentials not configured.")
        return False

    start_telegram_worker()
    telegram_seq += 1
    item = (_telegram_priority(message), telegram_seq, message)
    try:
        telegram_queue.put_nowait(item)
        return True
    except queue.Full:
        try:
            telegram_queue.get_nowait()
            telegram_queue.task_done()
            telegram_queue.put_nowait(item)
            print("Telegram queue full; dropped one queued alert to keep loop non-blocking.")
            return True
        except queue.Empty:
            print("Telegram queue full; alert dropped.")
            return False


def email_pdf(pdf_path: Path, subject: str, body: str) -> bool:
    required = [
        REPORT_EMAIL_SENDER,
        REPORT_EMAIL_PASSWORD,
        REPORT_EMAIL_RECIPIENT,
    ]
    if not all(required):
        print("Email report skipped: email environment variables are not configured.")
        return False

    try:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = REPORT_EMAIL_SENDER
        msg["To"] = REPORT_EMAIL_RECIPIENT
        msg.set_content(body)

        with open(pdf_path, "rb") as f:
            msg.add_attachment(
                f.read(),
                maintype="application",
                subtype="pdf",
                filename=pdf_path.name,
            )

        with smtplib.SMTP_SSL(EMAIL_SMTP_HOST, EMAIL_SMTP_PORT, timeout=20) as server:
            server.login(REPORT_EMAIL_SENDER, REPORT_EMAIL_PASSWORD)
            server.send_message(msg)
        return True
    except Exception as e:
        print(f"Email Error: {e}")
        return False


# =========================
# MARKET DATA
# =========================

def normalize_yf_columns(df: pd.DataFrame) -> pd.DataFrame:
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df


def get_historical_candles(index_name: str) -> List[dict]:
    ticker = YF_TICKERS[index_name]
    try:
        df = yf.download(
            ticker,
            period="10d",
            interval="5m",
            progress=False,
            auto_adjust=False,
            threads=False,
        )
        df = normalize_yf_columns(df)
        if df.empty:
            return []

        needed = ["Open", "High", "Low", "Close"]
        if not all(c in df.columns for c in needed):
            return []

        df = df.dropna(subset=needed).tail(120)
        candles = []
        for _, row in df.iterrows():
            candles.append({
                "Open": float(row["Open"]),
                "High": float(row["High"]),
                "Low": float(row["Low"]),
                "Close": float(row["Close"]),
            })

        # Previous daily close
        daily = yf.download(
            ticker,
            period="7d",
            interval="1d",
            progress=False,
            auto_adjust=False,
            threads=False,
        )
        daily = normalize_yf_columns(daily)
        if not daily.empty and "Close" in daily.columns:
            daily = daily.dropna(subset=["Close"])
            if len(daily) >= 2:
                prev_close_dict[index_name] = float(daily.iloc[-2]["Close"])
            elif len(daily) == 1:
                prev_close_dict[index_name] = float(daily.iloc[-1]["Close"])

        return candles
    except Exception as e:
        print(f"History fetch error {index_name}: {e}")
        return []


def get_live_index_data() -> Optional[pd.DataFrame]:
    global last_data_error_count
    try:
        df = capital_market.market_watch_all_indices()
        if df is None or df.empty:
            raise ValueError("NSE returned empty data")
        if "index" not in df.columns or "last" not in df.columns:
            raise ValueError("NSE response missing index/last columns")
        last_data_error_count = 0
        return df
    except Exception as e:
        last_data_error_count += 1
        print(f"NSE Fetch Error #{last_data_error_count}: {e}")
        if last_data_error_count in (1, MAX_CONSECUTIVE_DATA_ERRORS):
            send_telegram_alert(
                f"⚠️ DATA WARNING\n"
                f"Consecutive NSE data errors: {last_data_error_count}\n"
                f"Bot is pausing new signals until data recovers."
            )
        return None


def parse_price(value: Any) -> Optional[float]:
    try:
        text = str(value).replace(",", "").strip()
        price = float(text)
        if not np.isfinite(price) or price <= 0:
            return None
        return price
    except Exception:
        return None


def data_is_fresh(index_name: str) -> bool:
    ts = last_price_time.get(index_name)
    if ts is None:
        return False
    return (now_ist() - ts).total_seconds() <= MAX_DATA_AGE_SECONDS


# =========================
# LEVELS
# =========================

def calculate_camarilla_levels(index_name: str) -> Optional[dict]:
    ticker = YF_TICKERS[index_name]
    try:
        df = yf.download(
            ticker,
            period="7d",
            interval="1d",
            progress=False,
            auto_adjust=False,
            threads=False,
        )
        df = normalize_yf_columns(df)
        if df.empty:
            return None
        df = df.dropna(subset=["High", "Low", "Close"])
        if df.empty:
            return None

        prev_day = df.iloc[-2] if len(df) >= 2 else df.iloc[-1]
        h, l, c = float(prev_day["High"]), float(prev_day["Low"]), float(prev_day["Close"])
        rng = h - l
        if rng <= 0:
            return None

        return {
            "R3": round(c + rng * 1.1 / 4, 2),
            "R2": round(c + rng * 1.1 / 6, 2),
            "R1": round(c + rng * 1.1 / 12, 2),
            "S1": round(c - rng * 1.1 / 12, 2),
            "S2": round(c - rng * 1.1 / 6, 2),
            "S3": round(c - rng * 1.1 / 4, 2),
        }
    except Exception as e:
        print(f"Level calc error {index_name}: {e}")
        return None


# =========================
# SIGNAL / RISK ENGINE
# =========================

def candle_quality(c: dict) -> bool:
    rng = float(c["High"]) - float(c["Low"])
    body = abs(float(c["Close"]) - float(c["Open"]))
    return rng > 0 and (body / rng) >= MIN_CANDLE_BODY_RATIO


def risk_allows_new_signal() -> bool:
    return (
        trade_stats["total_signals"] < MAX_DAILY_SIGNALS
        and trade_stats["daily_losses"] < MAX_DAILY_LOSSES
        and trade_stats["consecutive_losses"] < MAX_CONSECUTIVE_LOSSES
        and last_data_error_count < MAX_CONSECUTIVE_DATA_ERRORS
    )


def reset_daily_state_if_needed() -> None:
    global levels_sent_today, last_heartbeat_hour, last_report_date
    today = now_ist().date().isoformat()
    if trade_stats["date"] != today:
        trade_stats.update({
            "date": today,
            "total_signals": 0,
            "completed_trades": 0,
            "target_hits": 0,
            "sl_hits": 0,
            "daily_losses": 0,
            "consecutive_losses": 0,
            "points": 0.0,
        })
        levels_sent_today = False
        last_heartbeat_hour = -1
        last_report_date = None



def option_contract_info(direction: str, spot: float, expiry: str = "") -> dict:
    """Informational option metadata only; no strike/strategy recommendation."""
    try:
        atm = round(float(spot) / 50.0) * 50
    except Exception:
        atm = None
    return {
        "option_type": "CE" if direction.upper() == "BUY" else "PE",
        "atm_reference": atm,
        "expiry": expiry or "NEAR_EXPIRY",
    }

def register_trade(
    index_name: str,
    side: str,
    entry: float,
    sl: float,
    risk: float,
) -> dict:
    sign = 1 if side == "BUY" else -1
    return {
        "id": uuid.uuid4().hex[:12],
        "created_at": now_ist().isoformat(),
        "type": side,
        "entry": round(entry, 2),
        "sl": round(sl, 2),
        "original_sl": round(sl, 2),
        "risk": round(risk, 2),
        "t1": round(entry + sign * risk * TARGET_R[0], 2),
        "t2": round(entry + sign * risk * TARGET_R[1], 2),
        "t3": round(entry + sign * risk * TARGET_R[2], 2),
        "t1_hit": False,
        "t2_hit": False,
        "t3_hit": False,
        "breakeven_moved": False,
    }


def close_trade(index_name: str, trade: dict, exit_price: float, reason: str) -> None:
    side = trade["type"]
    points = (
        exit_price - trade["entry"]
        if side == "BUY"
        else trade["entry"] - exit_price
    )
    r = points / trade["risk"] if trade.get("risk") else 0.0

    trade_stats["completed_trades"] += 1
    trade_stats["points"] += points

    if reason == "SL":
        trade_stats["sl_hits"] += 1
        if not trade.get("t1_hit"):
            trade_stats["daily_losses"] += 1
            trade_stats["consecutive_losses"] += 1
    elif reason == "EARLY_REVERSAL":
        if points < 0:
            trade_stats["daily_losses"] += 1
            trade_stats["consecutive_losses"] += 1
        else:
            trade_stats["consecutive_losses"] = 0
    elif reason == "TARGET3":
        trade_stats["target_hits"] += 1
        trade_stats["consecutive_losses"] = 0
    elif reason == "BREAKEVEN":
        trade_stats["target_hits"] += 1
        trade_stats["consecutive_losses"] = 0

    log_event(
        reason,
        index_name,
        trade,
        exit_price=exit_price,
        points=points,
        r_multiple=r,
    )


def reversal_confirmed(index_name: str, side: str) -> bool:
    """Confirm a short-term trend reversal using completed 5-minute candles."""
    if not EARLY_EXIT_ENABLED:
        return False

    history = candle_history.get(index_name, [])
    if len(history) < REVERSAL_CONFIRM_CANDLES:
        return False

    df = pd.DataFrame(history)
    required = {"Open", "High", "Low", "Close"}
    if not required.issubset(df.columns):
        return False

    df["EMA5"] = df["Close"].ewm(span=5, adjust=False).mean()
    recent = df.tail(REVERSAL_CONFIRM_CANDLES)

    if side == "BUY":
        return bool((recent["Close"] < recent["EMA5"]).all())
    return bool((recent["Close"] > recent["EMA5"]).all())


def manage_trade(index_name: str, current_price: float) -> None:
    trade = active_trades[index_name]
    if trade is None:
        return

    side = trade["type"]

    # Force exit before market shutdown.
    if now_ist().time() >= FORCE_EXIT:
        close_trade(index_name, trade, current_price, "AUTO_EXIT")
        send_telegram_alert(
            f"⏰ AUTO EXIT\n"
            f"⚡ MOMENTUM SPIKE V4\n"
            f"Index: {index_name}\n"
            f"Side: {side}\n"
            f"Exit: {current_price:.2f}"
        )
        active_trades[index_name] = None
        save_trades(active_trades)
        return

    # Early exit when a confirmed 5-minute EMA5 reversal appears.
    if reversal_confirmed(index_name, side):
        close_trade(index_name, trade, current_price, "EARLY_REVERSAL")
        send_telegram_alert(
            f"🔄 EARLY EXIT — TREND REVERSAL\\n"
            f"{index_name} {side}\\n"
            f"Exit: {current_price:.2f}\\n"
            f"Confirmed by {REVERSAL_CONFIRM_CANDLES} completed 5m candles."
        )
        active_trades[index_name] = None
        save_trades(active_trades)
        return

    if side == "BUY":
        if not trade["t1_hit"] and current_price >= trade["t1"]:
            trade["t1_hit"] = True
            trade["breakeven_moved"] = True
            trade["sl"] = trade["entry"]
            send_telegram_alert(
                f"🎯 T1 HIT + BREAKEVEN\n"
                f"{index_name} BUY\n"
                f"T1: {trade['t1']:.2f}\n"
                f"New SL: {trade['entry']:.2f}"
            )
            log_event("T1_HIT", index_name, trade, exit_price=current_price)
            save_trades(active_trades)

        if not trade["t2_hit"] and current_price >= trade["t2"]:
            trade["t2_hit"] = True
            send_telegram_alert(
                f"🎯 T2 HIT\n{index_name} BUY\nTarget: {trade['t2']:.2f}"
            )
            log_event("T2_HIT", index_name, trade, exit_price=current_price)
            save_trades(active_trades)

        if not trade["t3_hit"] and current_price >= trade["t3"]:
            trade["t3_hit"] = True
            close_trade(index_name, trade, current_price, "TARGET3")
            send_telegram_alert(
                f"🏆 T3 HIT — TRADE COMPLETE\n"
                f"{index_name} BUY\n"
                f"Exit: {current_price:.2f}"
            )
            active_trades[index_name] = None
            save_trades(active_trades)
            return

        if current_price <= trade["sl"]:
            reason = "BREAKEVEN" if trade["breakeven_moved"] else "SL"
            close_trade(index_name, trade, current_price, reason)
            send_telegram_alert(
                f"🛑 {reason}\n"
                f"{index_name} BUY\n"
                f"Exit: {current_price:.2f}"
            )
            active_trades[index_name] = None
            save_trades(active_trades)

    else:
        if not trade["t1_hit"] and current_price <= trade["t1"]:
            trade["t1_hit"] = True
            trade["breakeven_moved"] = True
            trade["sl"] = trade["entry"]
            send_telegram_alert(
                f"🎯 T1 HIT + BREAKEVEN\n"
                f"{index_name} SELL\n"
                f"T1: {trade['t1']:.2f}\n"
                f"New SL: {trade['entry']:.2f}"
            )
            log_event("T1_HIT", index_name, trade, exit_price=current_price)
            save_trades(active_trades)

        if not trade["t2_hit"] and current_price <= trade["t2"]:
            trade["t2_hit"] = True
            send_telegram_alert(
                f"🎯 T2 HIT\n{index_name} SELL\nTarget: {trade['t2']:.2f}"
            )
            log_event("T2_HIT", index_name, trade, exit_price=current_price)
            save_trades(active_trades)

        if not trade["t3_hit"] and current_price <= trade["t3"]:
            trade["t3_hit"] = True
            close_trade(index_name, trade, current_price, "TARGET3")
            send_telegram_alert(
                f"🏆 T3 HIT — TRADE COMPLETE\n"
                f"{index_name} SELL\n"
                f"Exit: {current_price:.2f}"
            )
            active_trades[index_name] = None
            save_trades(active_trades)
            return

        if current_price >= trade["sl"]:
            reason = "BREAKEVEN" if trade["breakeven_moved"] else "SL"
            close_trade(index_name, trade, current_price, reason)
            send_telegram_alert(
                f"🛑 {reason}\n"
                f"{index_name} SELL\n"
                f"Exit: {current_price:.2f}"
            )
            active_trades[index_name] = None
            save_trades(active_trades)


# =========================
# REPORTS
# =========================

def read_events() -> pd.DataFrame:
    if not EVENT_LOG_FILE.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(EVENT_LOG_FILE)
    except Exception:
        return pd.DataFrame()


def make_report_pdf(kind: str, date_value: datetime) -> Optional[Path]:
    if not REPORTLAB_OK:
        print("reportlab is not installed; PDF skipped.")
        return None

    df = read_events()
    if kind == "daily":
        date_key = date_value.date().isoformat()
        subset = df[df["date"].astype(str) == date_key] if not df.empty and "date" in df.columns else pd.DataFrame()
        filename = REPORT_DIR / f"daily_report_{date_value.strftime('%Y%m%d')}.pdf"
        title = f"MOMENTUM SPIKE V4 — Daily Report — {date_value.strftime('%d-%b-%Y')}"
    else:
        month_key = date_value.strftime("%Y-%m")
        subset = df[df["date"].astype(str).str.startswith(month_key)] if not df.empty and "date" in df.columns else pd.DataFrame()
        filename = REPORT_DIR / f"monthly_report_{date_value.strftime('%Y_%m')}.pdf"
        title = f"MOMENTUM SPIKE V4 — Monthly Report — {date_value.strftime('%B %Y')}"

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="CenterTitleV4", parent=styles["Title"], alignment=TA_CENTER))
    doc = SimpleDocTemplate(str(filename), pagesize=A4, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)

    story = [Paragraph(title, styles["CenterTitleV4"]), Spacer(1, 16)]

    total_events = len(subset)
    target_events = int(subset["event"].astype(str).isin(["TARGET3", "BREAKEVEN"]).sum()) if not subset.empty else 0
    sl_events = int(subset["event"].astype(str).eq("SL").sum()) if not subset.empty else 0

    points = 0.0
    if not subset.empty and "points" in subset.columns:
        points = pd.to_numeric(subset["points"], errors="coerce").fillna(0).sum()

    summary_data = [
        ["Metric", "Value"],
        ["Event rows", str(total_events)],
        ["Completed target/breakeven exits", str(target_events)],
        ["SL exits", str(sl_events)],
        ["Logged points", f"{points:.2f}"],
    ]
    table = Table(summary_data, colWidths=[260, 180])
    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
    ]))
    story.append(table)
    story.append(Spacer(1, 18))

    if not subset.empty:
        display_cols = [c for c in ["timestamp", "index", "event", "side", "entry", "exit", "points", "r_multiple"] if c in subset.columns]
        rows = [display_cols]
        for _, r in subset.tail(40).iterrows():
            rows.append([str(r.get(c, ""))[:24] for c in display_cols])
        event_table = Table(rows, repeatRows=1)
        event_table.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
            ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
            ("FONTSIZE", (0, 0), (-1, -1), 7),
        ]))
        story.append(event_table)
    else:
        story.append(Paragraph("No trade events were logged for this period.", styles["BodyText"]))

    doc.build(story)
    return filename


def send_daily_report_if_needed(day: datetime) -> None:
    global last_report_date
    if last_report_date == day.date().isoformat():
        return

    pdf = make_report_pdf("daily", day)
    if pdf:
        email_pdf(
            pdf,
            f"MOMENTUM SPIKE V4 Daily Report — {day.strftime('%d-%b-%Y')}",
            "Attached is the daily trading-alert audit report.",
        )
    send_telegram_alert(
        f"📋 DAILY REPORT READY\n"
        f"Date: {day.strftime('%d-%b-%Y')}\n"
        f"Signals: {trade_stats['total_signals']}\n"
        f"Completed: {trade_stats['completed_trades']}\n"
        f"Points: {trade_stats['points']:+.2f}"
    )
    last_report_date = day.date().isoformat()


def is_weekday(d) -> bool:
    return d.weekday() < 5


def last_tuesday(year: int, month: int):
    if month == 12:
        first_next = datetime(year + 1, 1, 1, tzinfo=IST)
    else:
        first_next = datetime(year, month + 1, 1, tzinfo=IST)
    last_day = first_next - timedelta(days=1)
    delta = (last_day.weekday() - 1) % 7  # Tuesday = 1
    return (last_day - timedelta(days=delta)).date()


def is_nifty_monthly_expiry_day(d) -> bool:
    # Kept configurable because exchange expiry rules can change.
    # Default assumption for this strategy's report scheduler: last Tuesday.
    expiry = last_tuesday(d.year, d.month)
    return d == expiry


def send_monthly_report_if_expiry(day: datetime) -> None:
    if not is_nifty_monthly_expiry_day(day.date()):
        return

    marker = REPORT_DIR / f"monthly_sent_{day.strftime('%Y_%m')}.marker"
    if marker.exists():
        return

    pdf = make_report_pdf("monthly", day)
    if pdf:
        email_pdf(
            pdf,
            f"MOMENTUM SPIKE V4 Monthly Expiry Report — {day.strftime('%B %Y')}",
            (
                "Attached is the monthly trading-alert audit PDF covering the period "
                f"{day.replace(day=1).strftime('%d-%b-%Y')} through {day.strftime('%d-%b-%Y')} "
                "(month start through the configured NIFTY monthly expiry day)."
            ),
        )
        marker.write_text(now_ist().isoformat(), encoding="utf-8")

    send_telegram_alert(
        f"📊 MONTHLY REPORT\n"
        f"Month: {day.strftime('%B %Y')}\n"
        f"Expiry-report day: {day.strftime('%d-%b-%Y')}\n"
        f"PDF: {'created' if pdf else 'not created'}"
    )


# =========================
# BACKTEST
# =========================

def backtest_dataframe(
    df: pd.DataFrame,
    min_risk: float = MIN_RISK_POINTS,
    slippage: float = BACKTEST_SLIPPAGE_POINTS,
    costs: float = BACKTEST_COST_POINTS,
) -> pd.DataFrame:
    """
    Index-level research backtest for the same core idea:
    - completed candle entirely above EMA5 -> watch downside breakout
    - completed candle entirely below EMA5 -> watch upside breakout
    - candle range >= min_risk
    - entry at breakout + slippage
    - target3/SL are evaluated from subsequent OHLC candles
    """
    required = {"Open", "High", "Low", "Close"}
    if not required.issubset(df.columns):
        raise ValueError(f"DataFrame must contain {required}")

    x = df.copy().dropna(subset=list(required)).reset_index(drop=True)
    x["EMA5"] = x["Close"].ewm(span=5, adjust=False).mean()

    results = []
    watch = None
    i = 0

    while i < len(x):
        row = x.iloc[i]

        if watch is None:
            rng = float(row["High"] - row["Low"])
            if rng >= min_risk and candle_quality({
                "Open": row["Open"], "High": row["High"],
                "Low": row["Low"], "Close": row["Close"]
            }):
                if row["Low"] > row["EMA5"]:
                    watch = {
                        "side": "SELL",
                        "high": float(row["High"]),
                        "low": float(row["Low"]),
                        "risk": rng,
                        "signal_i": i,
                    }
                elif row["High"] < row["EMA5"]:
                    watch = {
                        "side": "BUY",
                        "high": float(row["High"]),
                        "low": float(row["Low"]),
                        "risk": rng,
                        "signal_i": i,
                    }
            i += 1
            continue

        side = watch["side"]
        risk = watch["risk"]

        if side == "BUY" and row["High"] > watch["high"] + BREAKOUT_BUFFER_POINTS:
            entry = watch["high"] + BREAKOUT_BUFFER_POINTS + slippage
            sl = watch["low"]
            t1 = entry + risk * 1.5
            t2 = entry + risk * 2.0
            t3 = entry + risk * 3.0
        elif side == "SELL" and row["Low"] < watch["low"] - BREAKOUT_BUFFER_POINTS:
            entry = watch["low"] - BREAKOUT_BUFFER_POINTS - slippage
            sl = watch["high"]
            t1 = entry - risk * 1.5
            t2 = entry - risk * 2.0
            t3 = entry - risk * 3.0
        else:
            i += 1
            continue

        exit_price = None
        reason = None
        t1_hit = False
        t2_hit = False
        be = False

        # Start from the breakout candle; conservative rule when SL and target
        # are both touched in the same candle: count SL first.
        for j in range(i, len(x)):
            r = x.iloc[j]
            hi, lo = float(r["High"]), float(r["Low"])

            if side == "BUY":
                if lo <= sl:
                    exit_price = sl - costs
                    reason = "BREAKEVEN" if be else "SL"
                    break
                if not t1_hit and hi >= t1:
                    t1_hit = True
                    be = True
                    sl = entry
                if not t2_hit and hi >= t2:
                    t2_hit = True
                if hi >= t3:
                    exit_price = t3 - costs
                    reason = "TARGET3"
                    break
            else:
                if hi >= sl:
                    exit_price = sl + costs
                    reason = "BREAKEVEN" if be else "SL"
                    break
                if not t1_hit and lo <= t1:
                    t1_hit = True
                    be = True
                    sl = entry
                if not t2_hit and lo <= t2:
                    t2_hit = True
                if lo <= t3:
                    exit_price = t3 + costs
                    reason = "TARGET3"
                    break

        if exit_price is None:
            last_close = float(x.iloc[-1]["Close"])
            exit_price = last_close
            reason = "EOD"

        points = exit_price - entry if side == "BUY" else entry - exit_price
        results.append({
            "signal_i": watch["signal_i"],
            "entry_i": i,
            "side": side,
            "entry": round(entry, 2),
            "sl_initial": round(watch["high"] if side == "SELL" else watch["low"], 2),
            "exit": round(exit_price, 2),
            "reason": reason,
            "t1_hit": t1_hit,
            "t2_hit": t2_hit,
            "points": round(points, 2),
            "R": round(points / risk, 3),
        })

        watch = None
        i += 1

    return pd.DataFrame(results)


# =========================
# STARTUP / LOOP
# =========================

def startup() -> None:
    global active_trades, candle_history
    start_telegram_worker()
    ensure_event_log()
    active_trades = load_trades()
    for idx in INDEX_WATCHLIST:
        candle_history[idx] = get_historical_candles(idx)

    if not TELEGRAM_BOT_TOKEN:
        print("WARNING: TELEGRAM_BOT_TOKEN is not configured.")
    if not TELEGRAM_CHAT_ID:
        print("WARNING: TELEGRAM_CHAT_ID is not configured.")
    if not REPORT_EMAIL_PASSWORD:
        print("WARNING: Email credentials are not configured.")

    send_telegram_alert(
        "⚡ MOMENTUM SPIKE V4 ACTIVE\n"
        "Professional research/alert engine initialized.\n"
        "Monitoring NIFTY 50 & NIFTY BANK.\n"
        "Index-level signals only; no automatic order execution."
    )


def main() -> None:
    startup()

    global levels_sent_today, last_heartbeat_hour

    while True:
        try:
            watchdog_touch()
            now = now_ist()
            reset_daily_state_if_needed()

            # Do not process market data before 09:00 or after 15:40.
            # On weekends/NSE holidays, remain safely idle and send one reason alert.
            if now.time() < BOT_START:
                time.sleep(min(LOOP_SECONDS, max(1, int((datetime.combine(now.date(), BOT_START, tzinfo=IST) - now).total_seconds()))))
                continue

            if now.time() >= SHUTDOWN:
                send_daily_report_if_needed(now)
                send_monthly_report_if_expiry(now)
                telegram_queue.join()
                stop_telegram_worker()
                break

            # 09:05 levels
            if not levels_sent_today and now.hour == 9 and now.minute >= 5:
                msg = "📊 DAILY CAMARILLA LEVELS\n⚡ MOMENTUM SPIKE V4\n"
                for idx in INDEX_WATCHLIST:
                    lvl = calculate_camarilla_levels(idx)
                    if lvl:
                        msg += (
                            f"\n🔹 {idx}\n"
                            f"R3 {lvl['R3']:.2f} | R2 {lvl['R2']:.2f} | R1 {lvl['R1']:.2f}\n"
                            f"S1 {lvl['S1']:.2f} | S2 {lvl['S2']:.2f} | S3 {lvl['S3']:.2f}\n"
                        )
                send_telegram_alert(msg)
                levels_sent_today = True

            raw_data = get_live_index_data()

            if raw_data is not None:
                prices_dict = {}

                for index_name in INDEX_WATCHLIST:
                    row = raw_data[raw_data["index"] == index_name]
                    if row.empty:
                        continue

                    price = parse_price(row["last"].values[0])
                    if price is None:
                        continue

                    prices_dict[index_name] = price
                    last_price_time[index_name] = now

                    manage_trade(index_name, price)

                    # Build 5-minute candle
                    bucket = now.replace(
                        minute=(now.minute // 5) * 5,
                        second=0,
                        microsecond=0,
                    )

                    c = current_candles[index_name]
                    if c["bucket"] != bucket:
                        if c["open"] is not None:
                            completed = {
                                "Open": c["open"],
                                "High": c["high"],
                                "Low": c["low"],
                                "Close": c["close"],
                            }
                            candle_history[index_name].append(completed)
                            candle_history[index_name] = candle_history[index_name][-120:]

                            df = pd.DataFrame(candle_history[index_name])
                            df["EMA5"] = df["Close"].ewm(span=5, adjust=False).mean()
                            last_c = df.iloc[-1]

                            if candle_quality(last_c):
                                if last_c["Low"] > last_c["EMA5"]:
                                    alert_candles[index_name]["sell_alert"] = {
                                        "high": float(last_c["High"]),
                                        "low": float(last_c["Low"]),
                                    }
                                else:
                                    alert_candles[index_name]["sell_alert"] = None

                                if last_c["High"] < last_c["EMA5"]:
                                    alert_candles[index_name]["buy_alert"] = {
                                        "high": float(last_c["High"]),
                                        "low": float(last_c["Low"]),
                                    }
                                else:
                                    alert_candles[index_name]["buy_alert"] = None

                        current_candles[index_name] = {
                            "open": price,
                            "high": price,
                            "low": price,
                            "close": price,
                            "bucket": bucket,
                        }
                    else:
                        c["high"] = max(c["high"], price)
                        c["low"] = min(c["low"], price)
                        c["close"] = price

                    # New signals
                    can_trade = (
                        TRADE_START <= now.time() < TRADE_END
                        and active_trades[index_name] is None
                        and risk_allows_new_signal()
                        and data_is_fresh(index_name)
                    )

                    if can_trade:
                        s = alert_candles[index_name]["sell_alert"]
                        if s and price < s["low"] - BREAKOUT_BUFFER_POINTS:
                            risk = round(s["high"] - s["low"], 2)
                            if risk >= MIN_RISK_POINTS:
                                trade = register_trade(
                                    index_name, "SELL", price, s["high"], risk
                                )
                                active_trades[index_name] = trade
                                trade_stats["total_signals"] += 1
                                alert_candles[index_name]["sell_alert"] = None
                                save_trades(active_trades)
                                log_event("SIGNAL", index_name, trade)
                                send_telegram_alert(
                                    f"🔴 {index_name} SELL SIGNAL\n\n"
                                    f"⚡ MOMENTUM SPIKE V4\n"
                                    f"⏰ {now.strftime('%H:%M:%S IST')}\n"
                                    f"Entry: {trade['entry']:.2f}\n"
                                    f"SL: {trade['sl']:.2f}\n"
                                    f"T1: {trade['t1']:.2f}\n"
                                    f"T2: {trade['t2']:.2f}\n"
                                    f"T3: {trade['t3']:.2f}"
                                )

                        b = alert_candles[index_name]["buy_alert"]
                        if active_trades[index_name] is None and b and price > b["high"] + BREAKOUT_BUFFER_POINTS:
                            risk = round(b["high"] - b["low"], 2)
                            if risk >= MIN_RISK_POINTS:
                                trade = register_trade(
                                    index_name, "BUY", price, b["low"], risk
                                )
                                active_trades[index_name] = trade
                                trade_stats["total_signals"] += 1
                                alert_candles[index_name]["buy_alert"] = None
                                save_trades(active_trades)
                                log_event("SIGNAL", index_name, trade)
                                send_telegram_alert(
                                    f"🟢 {index_name} BUY SIGNAL\n\n"
                                    f"⚡ MOMENTUM SPIKE V4\n"
                                    f"⏰ {now.strftime('%H:%M:%S IST')}\n"
                                    f"Entry: {trade['entry']:.2f}\n"
                                    f"SL: {trade['sl']:.2f}\n"
                                    f"T1: {trade['t1']:.2f}\n"
                                    f"T2: {trade['t2']:.2f}\n"
                                    f"T3: {trade['t3']:.2f}"
                                )

                # Hourly status
                if now.minute == 0 and now.hour != last_heartbeat_hour and 9 <= now.hour <= 15:
                    last_heartbeat_hour = now.hour
                    hb = f"💓 V4 STATUS — {now.strftime('%H:%M IST')}\n"
                    for idx, price in prices_dict.items():
                        prev = prev_close_dict.get(idx, price)
                        diff = price - prev
                        pct = diff / prev * 100 if prev else 0
                        hb += f"• {idx}: {price:.2f} ({diff:+.2f} | {pct:+.2f}%)\n"
                    hb += (
                        f"\nSignals: {trade_stats['total_signals']}"
                        f"\nLosses: {trade_stats['daily_losses']}"
                        f"\nPoints: {trade_stats['points']:+.2f}"
                    )
                    send_telegram_alert(hb)

            time.sleep(LOOP_SECONDS)

        except Exception as exc:
            # Keep the outer loop alive on transient runtime failures.
            # The next iteration retries after the normal loop delay.
            send_telegram_alert(f"⚠️ BOT LOOP ERROR — auto-retrying\\n{type(exc).__name__}: {exc}")
            time.sleep(LOOP_SECONDS)

        except KeyboardInterrupt:
            send_telegram_alert("🛑 MOMENTUM SPIKE V4 stopped manually.")
            telegram_queue.join()
            stop_telegram_worker()
            break
        except Exception as e:
            print(f"Main loop exception: {e}")
            time.sleep(LOOP_SECONDS)


if __name__ == "__main__":
    main()
