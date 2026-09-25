import os
import sys
import json
import time
import pytz
import logging
import requests
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta, time as dtime
from concurrent.futures import ThreadPoolExecutor

# ==========================================
# 1. LOGGING & BASIC CONFIGURATION
# ==========================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("SAS_TRACKER")

IST = pytz.timezone("Asia/Kolkata")

# Credentials & Bot Tokens
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8804327561:AAECrvtU0MCYB80L0ZchoKy_YDpwJ52zQA8")
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID", "-1004416495917")
TELEGRAM_ADMIN_CHAT_ID = os.getenv("TELEGRAM_ADMIN_CHAT_ID", "6789591588")

# State Files
DAILY_STATE_FILE = "daily_active_trades.json"
EXPIRY_LEDGER_FILE = "expiry_trades_ledger.json"

telegram_session = requests.Session()
executor = ThreadPoolExecutor(max_workers=4)

# ==========================================
# 2. FAST TELEGRAM DISPATCH
# ==========================================
def _send_single_telegram(cid, message, parse_mode):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": cid, "text": message, "parse_mode": parse_mode}
    try:
        telegram_session.post(url, json=payload, timeout=10)
    except Exception as e:
        logger.error(f"[TELEGRAM ERROR] {cid}: {e}")

def send_telegram_alert(message, parse_mode="HTML", chat_id=None):
    if not TELEGRAM_BOT_TOKEN:
        return
    targets = [chat_id] if chat_id else [TELEGRAM_CHANNEL_ID, TELEGRAM_ADMIN_CHAT_ID]
    for cid in targets:
        if cid:
            executor.submit(_send_single_telegram, cid, message, parse_mode)

# ==========================================
# 3. HIGH SPEED RESILIENT PRICE ENGINE
# ==========================================
def get_live_tick():
    # 1. Google Finance Fast Feed (ബ്ലോക്ക് ആവില്ല)
    try:
        url = "https://www.google.com/finance/quote/NIFTY_50:INDEXNSE"
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(url, headers=headers, timeout=3)
        if r.status_code == 200 and 'data-last-price="' in r.text:
            price_str = r.text.split('data-last-price="')[1].split('"')[0]
            val = float(price_str.replace(",", ""))
            if val > 10000:
                return val
    except Exception:
        pass

    # 2. Yahoo Finance Secondary Feed
    try:
        data = yf.download(tickers="^NSEI", period="1d", interval="1m", progress=False)
        if not data.empty:
            if isinstance(data.columns, pd.MultiIndex):
                data.columns = data.columns.get_level_values(0)
            return float(data['Close'].iloc[-1])
    except Exception:
        pass

    return None

# ==========================================
# 4. STATE & LEDGER MANAGEMENT
# ==========================================
def load_backup_state():
    today_str = datetime.now(IST).strftime("%Y-%m-%d")
    if os.path.exists(DAILY_STATE_FILE):
        try:
            with open(DAILY_STATE_FILE, "r") as f:
                data = json.load(f)
                if data.get("date") == today_str:
                    return data.get("active_trade")
        except Exception:
            pass
    return None

def save_daily_state(active_trade):
    today_str = datetime.now(IST).strftime("%Y-%m-%d")
    try:
        with open(DAILY_STATE_FILE, "w") as f:
            json.dump({"date": today_str, "active_trade": active_trade}, f, indent=4)
    except Exception:
        pass

def load_expiry_ledger():
    if os.path.exists(EXPIRY_LEDGER_FILE):
        try:
            with open(EXPIRY_LEDGER_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def record_trade_to_ledger(trade_record):
    ledger = load_expiry_ledger()
    ledger.append(trade_record)
    try:
        with open(EXPIRY_LEDGER_FILE, "w") as f:
            json.dump(ledger, f, indent=4)
    except Exception:
        pass

# ==========================================
# 5. CORE SCALPING ENGINE (FIXED 30 PT SL & TARGET)
# ==========================================
def main():
    logger.info("Initializing SAS 30-Pt Scalper Bot...")

    active_trade = load_backup_state()
    today_date_str = datetime.now(IST).strftime("%Y-%m-%d")
    today_str_display = datetime.now(IST).strftime('%d-%b-%Y')
    startup_alert_sent = False
    last_heartbeat_hour = -1

    # Scalping Micro-Range Engine
    price_history = []
    FIXED_RISK = 30.0  # കൃത്യം 30 പോയിന്റ് ഫിക്സഡ് SL & T1

    while True:
        now = datetime.now(IST)
        current_time = now.time()

        # 09:00 AM Engine Alert
        if current_time >= dtime(9, 0) and not startup_alert_sent:
            msg = (
                f"🚀 <b>SAS SCALPER LIVE (09:00 AM)</b>\n\n"
                f"⚡ <b>Strategy:</b> 30-PT MOMENTUM SCALPING\n"
                f"📊 <b>Index:</b> NIFTY 50\n"
                f"🛑 <b>Fixed Stop Loss:</b> 30.0 Pts\n"
                f"🎯 <b>Fixed Target 1:</b> 30.0 Pts\n"
                f"🛡️ <b>Engine Status:</b> Fast Real-Time Scalper Active."
            )
            send_telegram_alert(msg)
            startup_alert_sent = True

        # Active Scalping Window (09:15 AM - 03:25 PM)
        if dtime(9, 15) <= current_time <= dtime(15, 25):
            current_tick = get_live_tick()
            if current_tick:
                price_history.append(current_tick)
                if len(price_history) > 60:
                    price_history.pop(0)

                # -----------------------------------------------
                # SCENARIO A: MONITOR ACTIVE TRADE (30 PT RULE)
                # -----------------------------------------------
                if active_trade is not None:
                    side = active_trade["side"]
                    entry = active_trade["entry"]
                    t1 = active_trade["t1"]
                    t2 = active_trade["t2"]
                    t3 = active_trade["t3"]
                    sl = active_trade["sl"]

                    if side == "BUY":
                        # Target 3 (90 Pts)
                        if current_tick >= t3:
                            pnl = t3 - entry
                            active_trade["status"] = "Target 3 Achieved"
                            active_trade["exit_price"] = t3
                            active_trade["pnl"] = pnl
                            record_trade_to_ledger(active_trade)
                            send_telegram_alert(f"🎯 <b>TARGET 3 ACHIEVED! [BUY]</b>\nPrice: {current_tick:.2f}\nPoints: +{pnl:.2f} Pts\nTrade closed in full profit.")
                            active_trade = None
                            save_daily_state(None)

                        # Target 2 (60 Pts)
                        elif current_tick >= t2 and active_trade.get("highest_target", 0) < 2:
                            active_trade["highest_target"] = 2
                            active_trade["sl"] = t1
                            send_telegram_alert(f"🎯 <b>TARGET 2 ACHIEVED! [BUY]</b>\nPrice: {current_tick:.2f}\nPoints: +60.0 Pts\nSL trailed to Target 1 ({t1:.2f}).")
                            save_daily_state(active_trade)

                        # Target 1 (Quick 30 Pts Scalp -> Book & Ready for Next)
                        elif current_tick >= t1 and active_trade.get("highest_target", 0) < 1:
                            pnl = t1 - entry
                            active_trade["status"] = "Target 1 Achieved"
                            active_trade["exit_price"] = t1
                            active_trade["pnl"] = pnl
                            record_trade_to_ledger(active_trade)
                            send_telegram_alert(f"🎯 <b>TARGET 1 ACHIEVED! [BUY]</b>\nPrice: {current_tick:.2f}\nPoints: +{pnl:.2f} Pts\nTarget 1 safely booked. Ready for next scalping opportunity!")
                            active_trade = None
                            save_daily_state(None)

                        # Stop Loss Hit (30 Pts)
                        elif current_tick <= sl:
                            pnl = sl - entry
                            active_trade["exit_price"] = sl
                            active_trade["pnl"] = pnl
                            active_trade["status"] = "Stop Loss Hit"
                            record_trade_to_ledger(active_trade)
                            send_telegram_alert(f"🛑 <b>STOP LOSS HIT [BUY]</b>\nPrice: {current_tick:.2f}\nPoints: {pnl:.2f} Pts\nExited position.")
                            active_trade = None
                            save_daily_state(None)

                    elif side == "SELL":
                        # Target 3 (90 Pts)
                        if current_tick <= t3:
                            pnl = entry - t3
                            active_trade["status"] = "Target 3 Achieved"
                            active_trade["exit_price"] = t3
                            active_trade["pnl"] = pnl
                            record_trade_to_ledger(active_trade)
                            send_telegram_alert(f"🎯 <b>TARGET 3 ACHIEVED! [SELL]</b>\nPrice: {current_tick:.2f}\nPoints: +{pnl:.2f} Pts\nTrade closed in full profit.")
                            active_trade = None
                            save_daily_state(None)

                        # Target 2 (60 Pts)
                        elif current_tick <= t2 and active_trade.get("highest_target", 0) < 2:
                            active_trade["highest_target"] = 2
                            active_trade["sl"] = t1
                            send_telegram_alert(f"🎯 <b>TARGET 2 ACHIEVED! [SELL]</b>\nPrice: {current_tick:.2f}\nPoints: +60.0 Pts\nSL trailed to Target 1 ({t1:.2f}).")
                            save_daily_state(active_trade)

                        # Target 1 (Quick 30 Pts Scalp -> Book & Ready for Next)
                        elif current_tick <= t1 and active_trade.get("highest_target", 0) < 1:
                            pnl = entry - t1
                            active_trade["status"] = "Target 1 Achieved"
                            active_trade["exit_price"] = t1
                            active_trade["pnl"] = pnl
                            record_trade_to_ledger(active_trade)
                            send_telegram_alert(f"🎯 <b>TARGET 1 ACHIEVED! [SELL]</b>\nPrice: {current_tick:.2f}\nPoints: +{pnl:.2f} Pts\nTarget 1 safely booked. Ready for next scalping opportunity!")
                            active_trade = None
                            save_daily_state(None)

                        # Stop Loss Hit (30 Pts)
                        elif current_tick >= sl:
                            pnl = entry - sl
                            active_trade["exit_price"] = sl
                            active_trade["pnl"] = pnl
                            active_trade["status"] = "Stop Loss Hit"
                            record_trade_to_ledger(active_trade)
                            send_telegram_alert(f"🛑 <b>STOP LOSS HIT [SELL]</b>\nPrice: {current_tick:.2f}\nPoints: {pnl:.2f} Pts\nExited position.")
                            active_trade = None
                            save_daily_state(None)

                # -----------------------------------------------
                # SCENARIO B: SCAN FOR FAST MOMENTUM SCALP SIGNALS
                # -----------------------------------------------
                else:
                    if len(price_history) >= 15:
                        recent_max = max(price_history[:-1])
                        recent_min = min(price_history[:-1])
                        trigger = None

                        # Fast Scalp Breakout
                        if current_tick > recent_max + 1.0:
                            trigger = "BUY"
                        elif current_tick < recent_min - 1.0:
                            trigger = "SELL"

                        if trigger:
                            entry = current_tick
                            entry_time_display = now.strftime('%I:%M:%S %p')

                            if trigger == "BUY":
                                sl = round(entry - FIXED_RISK, 2)
                                t1 = round(entry + FIXED_RISK, 2)
                                t2 = round(entry + (FIXED_RISK * 2), 2)
                                t3 = round(entry + (FIXED_RISK * 3), 2)
                            else:
                                sl = round(entry + FIXED_RISK, 2)
                                t1 = round(entry - FIXED_RISK, 2)
                                t2 = round(entry - (FIXED_RISK * 2), 2)
                                t3 = round(entry - (FIXED_RISK * 3), 2)

                            active_trade = {
                                "date": today_date_str,
                                "index": "NIFTY 50",
                                "side": trigger,
                                "entry": entry,
                                "sl": sl,
                                "t1": t1,
                                "t2": t2,
                                "t3": t3,
                                "highest_target": 0,
                                "time": entry_time_display
                            }
                            save_daily_state(active_trade)

                            msg = (
                                f"⚡ <b>SAS SCALPER SIGNAL</b>\n"
                                f"━━━━━━━━━━━━━━━━━━━━\n"
                                f"📊 <b>Index:</b> NIFTY 50\n"
                                f"🎯 <b>Action:</b> {trigger}\n"
                                f"⏰ <b>Entry Time:</b> {entry_time_display} IST\n"
                                f"🔹 <b>Entry:</b> {entry:.2f}\n"
                                f"🛑 <b>Stop Loss:</b> {sl:.2f} (30.0 Pts)\n"
                                f"🎯 <b>Target 1:</b> {t1:.2f} (30.0 Pts)\n"
                                f"🎯 <b>Target 2:</b> {t2:.2f} (60.0 Pts)\n"
                                f"🎯 <b>Target 3:</b> {t3:.2f} (90.0 Pts)\n"
                                f"━━━━━━━━━━━━━━━━━━━━"
                            )
                            send_telegram_alert(msg)
                            price_history = []  # Clear buffer for next breakout

                # Hourly Status
                if now.minute == 0 and now.hour != last_heartbeat_hour and (9 <= now.hour <= 15):
                    last_heartbeat_hour = now.hour
                    send_telegram_alert(f"💓 <b>HOURLY STATUS:</b> NIFTY 50 Spot at {current_tick:.2f} ({now.strftime('%I:%M %p')})")

        # 03:25 PM Auto Square Off
        if current_time >= dtime(15, 25) and active_trade is not None:
            entry = active_trade["entry"]
            last_prc = current_tick if 'current_tick' in locals() and current_tick else entry
            pnl = (last_prc - entry) if active_trade["side"] == "BUY" else (entry - last_prc)
            active_trade["status"] = "EOD Auto-Exit"
            active_trade["exit_price"] = last_prc
            active_trade["pnl"] = pnl
            record_trade_to_ledger(active_trade)
            active_trade = None
            save_daily_state(None)
            send_telegram_alert(f"🔔 <b>MARKET CLOSING (03:25 PM):</b> Open position closed ({pnl:+.2f} Pts).")

        # 03:40 PM Daily Performance Summary
        if current_time >= dtime(15, 40):
            ledger = load_expiry_ledger()
            today_trades = [t for t in ledger if t.get("date") == today_date_str]
            today_pnl = sum(t.get("pnl", 0.0) for t in today_trades)

            daily_summary = (
                f"📊 <b>DAILY PERFORMANCE SUMMARY (03:40 PM)</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"📅 <b>Date:</b> {today_str_display}\n"
                f"⚡ <b>Strategy:</b> 30-PT MOMENTUM SCALPING\n"
                f"• Today Trades: {len(today_trades)}\n"
                f"📈 <b>Day Net Points:</b> {today_pnl:+.2f} Pts\n"
                f"━━━━━━━━━━━━━━━━━━━━"
            )
            send_telegram_alert(daily_summary)
            send_telegram_alert("🛑 <b>MARKET CLOSED (03:40 PM):</b> SAS Scalper shutting down safely.")
            break

        time.sleep(2)

if __name__ == "__main__":
    main()
