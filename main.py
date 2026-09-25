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
from nselib import capital_market

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
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID", "@niftyfivtybanknifty")
TELEGRAM_ADMIN_CHAT_ID = os.getenv("TELEGRAM_ADMIN_CHAT_ID", "6789591588")

# Watchlist & Tickers (NIFTY 50 Only)
INDEX_WATCHLIST = ["NIFTY 50"]
YF_TICKERS = {"NIFTY 50": "^NSEI"}

# State Files
DAILY_STATE_FILE = "daily_active_trades.json"
EXPIRY_LEDGER_FILE = "expiry_trades_ledger.json"

telegram_session = requests.Session()
executor = ThreadPoolExecutor(max_workers=4)

# ==========================================
# 2. FAST TELEGRAM DISPATCH (PARALLEL & NO TIMEOUT ERROR)
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
# 3. NSE HOLIDAY & WEEKEND DETECTION
# ==========================================
def get_nse_holidays():
    try:
        holidays_df = capital_market.holiday_trading()
        if holidays_df is not None and not holidays_df.empty and 'tradingDate' in holidays_df.columns:
            return [datetime.strptime(d, '%d-%b-%Y').date() for d in holidays_df['tradingDate'].values]
    except Exception as e:
        logger.error(f"Error fetching NSE holidays: {e}")
    return []

holiday_dates = get_nse_holidays()
today_dt = datetime.now(IST)
today_date = today_dt.date()
today_str_display = today_dt.strftime('%d-%b-%Y')

# Weekend Check
if today_dt.weekday() in [5, 6]:
    day_name = "Saturday" if today_dt.weekday() == 5 else "Sunday"
    send_telegram_alert(f"🏖️ <b>WEEKEND MARKET HOLIDAY ({day_name})</b>\n• Market is closed today.")
    sys.exit(0)

# Holiday Check
if today_date in holiday_dates:
    send_telegram_alert(f"🏖️ <b>NSE MARKET HOLIDAY TODAY ({today_str_display})</b>\n• Market is closed.")
    sys.exit(0)

# Monthly Tuesday Expiry Detection
def is_today_monthly_tuesday_expiry():
    today = datetime.now(IST).date()
    next_month = today.replace(day=28) + timedelta(days=4)
    last_day_of_month = next_month - timedelta(days=next_month.day)
    
    cur_day = last_day_of_month
    while cur_day.weekday() != 1:
        cur_day -= timedelta(days=1)
        
    while cur_day in holiday_dates or cur_day.weekday() in [5, 6]:
        cur_day -= timedelta(days=1)
        
    return today == cur_day

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
                    logger.info("Daily state restored successfully.")
                    return data.get("active_trade")
        except Exception as e:
            logger.error(f"Error loading daily state: {e}")
    return None

def save_daily_state(active_trade):
    today_str = datetime.now(IST).strftime("%Y-%m-%d")
    data = {"date": today_str, "active_trade": active_trade}
    try:
        with open(DAILY_STATE_FILE, "w") as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        logger.error(f"Error saving daily state: {e}")

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
    except Exception as e:
        logger.error(f"Error saving ledger: {e}")

def clear_expiry_ledger():
    try:
        if os.path.exists(EXPIRY_LEDGER_FILE):
            os.remove(EXPIRY_LEDGER_FILE)
    except Exception:
        pass

# ==========================================
# 5. CAMARILLA MARKET DATA & 30 PT RISK
# ==========================================
def fetch_previous_ohlc():
    try:
        ticker = yf.Ticker(YF_TICKERS["NIFTY 50"])
        df = ticker.history(period="5d", interval="1d")
        if len(df) >= 2:
            prev_day = df.iloc[-2]
            return float(prev_day['High']), float(prev_day['Low']), float(prev_day['Close'])
    except Exception as e:
        logger.error(f"Error fetching OHLC: {e}")
    return None, None, None

def calculate_levels(high, low, close):
    diff = high - low
    levels = {
        "H5": close + (1.1 * diff),
        "H4": close + (diff * 1.1 / 2.0),
        "H3": close + (diff * 1.1 / 4.0),
        "L3": close - (diff * 1.1 / 4.0),
        "L4": close - (diff * 1.1 / 2.0),
        "L5": close - (1.1 * diff),
        "Dynamic_Risk": 30.0  # ഫിക്സഡ് 30 പോയിന്റ് SL & Quick Targets (50/50)
    }
    return levels

def get_live_tick():
    try:
        data = yf.download(tickers=YF_TICKERS["NIFTY 50"], period="1d", interval="1m", progress=False)
        if not data.empty:
            if isinstance(data.columns, pd.MultiIndex):
                data.columns = data.columns.get_level_values(0)
            return float(data['Close'].iloc[-1])
    except Exception as e:
        logger.error(f"Error fetching live tick: {e}")
    return None

# ==========================================
# 6. CORE EXECUTION BOT
# ==========================================
def main():
    logger.info("Initializing SAS Level Pulse Bot...")

    high, low, close = fetch_previous_ohlc()
    if not high:
        logger.error("Failed to obtain previous session OHLC.")
        return

    levels = calculate_levels(high, low, close)
    dynamic_risk = levels["Dynamic_Risk"]
    logger.info(f"NIFTY Camarilla Levels Loaded: R4={levels['H4']:.2f}, R3={levels['H3']:.2f}, S3={levels['L3']:.2f}, S4={levels['L4']:.2f}, Risk={dynamic_risk} Pts")

    startup_alert_sent = False
    levels_posted = False
    active_trade = load_backup_state()
    prev_tick = None
    last_heartbeat_hour = -1
    today_date_str = datetime.now(IST).strftime("%Y-%m-%d")

    sl_cooldown_until = None
    last_sl_side = None

    while True:
        now = datetime.now(IST)
        current_time = now.time()

        # 09:00 AM Engine Alert
        if current_time >= dtime(9, 0) and not startup_alert_sent:
            startup_msg = (
                f"🚀 <b>SAS LEVEL PULSE LIVE (09:00 AM)</b>\n\n"
                f"⚡ <b>Strategy:</b> SAS LEVEL PULSE (Camarilla Momentum)\n"
                f"📊 <b>Index:</b> NIFTY 50\n"
                f"🕒 <b>Time:</b> {now.strftime('%I:%M:%S %p')} IST\n"
                f"🛡️ <b>Engine Status:</b> Fast Real-Time Scanner Active."
            )
            send_telegram_alert(startup_msg)
            startup_alert_sent = True

        # 09:05 AM - Camarilla Levels Alert
        if current_time >= dtime(9, 5) and not levels_posted:
            msg = (
                f"<b>⚡ DAILY MOMENTUM SPIKE LEVELS (09:05 AM)</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"📊 <b>Index:</b> NIFTY 50\n"
                f"🔹 <b>Bullish Breakout (R4):</b> {levels['H4']:.2f}\n"
                f"🔹 <b>Resistance Reversal (R3):</b> {levels['H3']:.2f}\n"
                f"🔸 <b>Support Reversal (S3):</b> {levels['L3']:.2f}\n"
                f"🔸 <b>Bearish Breakdown (S4):</b> {levels['L4']:.2f}\n"
                f"🛡️ <b>Day Fixed Risk:</b> 30.0 Pts\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"<i>Tracking live tick-by-tick momentum.</i>\n"
                f"⚠️ <i>Strictly for educational study only. Not SEBI registered.</i>"
            )
            send_telegram_alert(msg)
            levels_posted = True

        # Active Scanning Window (09:15 AM - 03:25 PM)
        if dtime(9, 15) <= current_time <= dtime(15, 25):
            current_tick = get_live_tick()
            if current_tick:
                if prev_tick is None:
                    prev_tick = current_tick
                    time.sleep(1)
                    continue

                # -----------------------------------------------
                # SCENARIO A: MONITOR ACTIVE TRADE
                # -----------------------------------------------
                if active_trade is not None:
                    side = active_trade["side"]
                    entry = active_trade["entry"]
                    t1 = active_trade["t1"]
                    t2 = active_trade["t2"]
                    t3 = active_trade["t3"]
                    sl = active_trade["sl"]

                    if side == "BUY":
                        # Target 3 (Full Profit)
                        if current_tick >= t3:
                            pnl = t3 - entry
                            active_trade["highest_target"] = 3
                            active_trade["status"] = "Target 3 Achieved"
                            active_trade["exit_price"] = t3
                            active_trade["pnl"] = pnl
                            record_trade_to_ledger(active_trade)
                            send_telegram_alert(f"🎯 <b>TARGET 3 ACHIEVED! [BUY]</b>\nPrice: {current_tick:.2f}\nPoints: +{pnl:.2f} Pts\nTrade closed in full profit.")
                            active_trade = None
                            save_daily_state(None)

                        # Target 2
                        elif current_tick >= t2 and active_trade.get("highest_target", 0) < 2:
                            active_trade["highest_target"] = 2
                            active_trade["sl"] = t1
                            send_telegram_alert(f"🎯 <b>TARGET 2 ACHIEVED! [BUY]</b>\nPrice: {current_tick:.2f}\nPoints: +60.0 Pts\nSL trailed to Target 1 ({t1:.2f}).")
                            save_daily_state(active_trade)

                        # Target 1 (Quick 30 Pts -> Booked & Ready for Next)
                        elif current_tick >= t1 and active_trade.get("highest_target", 0) < 1:
                            active_trade["highest_target"] = 1
                            active_trade["status"] = "Target 1 Achieved"
                            active_trade["exit_price"] = t1
                            active_trade["pnl"] = t1 - entry
                            record_trade_to_ledger(active_trade)
                            send_telegram_alert(f"🎯 <b>TARGET 1 ACHIEVED! [BUY]</b>\nPrice: {current_tick:.2f}\nPoints: +{t1 - entry:.2f} Pts\nTarget 1 booked safely. Ready for next signal.")
                            active_trade = None
                            save_daily_state(None)

                        # Stop Loss Hit
                        elif current_tick <= sl:
                            pnl = sl - entry
                            active_trade["exit_price"] = sl
                            active_trade["pnl"] = pnl
                            active_trade["status"] = "Stop Loss Hit"
                            record_trade_to_ledger(active_trade)
                            send_telegram_alert(f"🛑 <b>STOP LOSS HIT [BUY]</b>\nPrice: {current_tick:.2f}\nPoints: {pnl:.2f} Pts\nExited position.")
                            sl_cooldown_until = now + timedelta(minutes=3)
                            last_sl_side = "BUY"
                            active_trade = None
                            save_daily_state(None)

                    elif side == "SELL":
                        # Target 3 (Full Profit)
                        if current_tick <= t3:
                            pnl = entry - t3
                            active_trade["highest_target"] = 3
                            active_trade["status"] = "Target 3 Achieved"
                            active_trade["exit_price"] = t3
                            active_trade["pnl"] = pnl
                            record_trade_to_ledger(active_trade)
                            send_telegram_alert(f"🎯 <b>TARGET 3 ACHIEVED! [SELL]</b>\nPrice: {current_tick:.2f}\nPoints: +{pnl:.2f} Pts\nTrade closed in full profit.")
                            active_trade = None
                            save_daily_state(None)

                        # Target 2
                        elif current_tick <= t2 and active_trade.get("highest_target", 0) < 2:
                            active_trade["highest_target"] = 2
                            active_trade["sl"] = t1
                            send_telegram_alert(f"🎯 <b>TARGET 2 ACHIEVED! [SELL]</b>\nPrice: {current_tick:.2f}\nPoints: +60.0 Pts\nSL trailed to Target 1 ({t1:.2f}).")
                            save_daily_state(active_trade)

                        # Target 1 (Quick 30 Pts -> Booked & Ready for Next)
                        elif current_tick <= t1 and active_trade.get("highest_target", 0) < 1:
                            active_trade["highest_target"] = 1
                            active_trade["status"] = "Target 1 Achieved"
                            active_trade["exit_price"] = t1
                            active_trade["pnl"] = entry - t1
                            record_trade_to_ledger(active_trade)
                            send_telegram_alert(f"🎯 <b>TARGET 1 ACHIEVED! [SELL]</b>\nPrice: {current_tick:.2f}\nPoints: +{entry - t1:.2f} Pts\nTarget 1 booked safely. Ready for next signal.")
                            active_trade = None
                            save_daily_state(None)

                        # Stop Loss Hit
                        elif current_tick >= sl:
                            pnl = entry - sl
                            active_trade["exit_price"] = sl
                            active_trade["pnl"] = pnl
                            active_trade["status"] = "Stop Loss Hit"
                            record_trade_to_ledger(active_trade)
                            send_telegram_alert(f"🛑 <b>STOP LOSS HIT [SELL]</b>\nPrice: {current_tick:.2f}\nPoints: {pnl:.2f} Pts\nExited position.")
                            sl_cooldown_until = now + timedelta(minutes=3)
                            last_sl_side = "SELL"
                            active_trade = None
                            save_daily_state(None)

                # -----------------------------------------------
                # SCENARIO B: SCAN FOR CAMARILLA BREAKOUT & REVERSAL SIGNALS
                # -----------------------------------------------
                else:
                    trigger = None
                    trade_type = ""
                    risk_pts = dynamic_risk  # കൃത്യം 30 Pts

                    # 1. Bullish Breakout (Above R4)
                    if prev_tick < levels["H4"] and current_tick >= levels["H4"]:
                        trigger = "BUY"
                        trade_type = "Breakout Spike (Above R4)"

                    # 2. Bullish Reversal (Bounce from S3)
                    elif prev_tick <= levels["L3"] and current_tick > levels["L3"]:
                        trigger = "BUY"
                        trade_type = "Support Bounce (Reversal from S3)"

                    # 3. Bearish Breakdown (Below S4)
                    elif prev_tick > levels["L4"] and current_tick <= levels["L4"]:
                        trigger = "SELL"
                        trade_type = "Breakdown Spike (Below S4)"

                    # 4. Bearish Reversal (Rejection from R3)
                    elif prev_tick >= levels["H3"] and current_tick < levels["H3"]:
                        trigger = "SELL"
                        trade_type = "Resistance Rejection (Reversal from R3)"

                    # SL Cooldown check
                    if trigger and sl_cooldown_until and now < sl_cooldown_until and trigger == last_sl_side:
                        trigger = None

                    # പുതിയ സിഗ്നൽ നൽകൽ (30 Pt SL & 30 Pt T1)
                    if trigger:
                        entry = current_tick
                        if trigger == "BUY":
                            sl = round(entry - risk_pts, 2)         # -30 Pts
                            t1 = round(entry + risk_pts, 2)         # +30 Pts
                            t2 = round(entry + (risk_pts * 2.0), 2) # +60 Pts
                            t3 = round(entry + (risk_pts * 3.0), 2) # +90 Pts
                        else:
                            sl = round(entry + risk_pts, 2)         # +30 Pts
                            t1 = round(entry - risk_pts, 2)         # -30 Pts
                            t2 = round(entry - (risk_pts * 2.0), 2) # -60 Pts
                            t3 = round(entry - (risk_pts * 3.0), 2) # -90 Pts

                        active_trade = {
                            "date": today_date_str,
                            "index": "NIFTY 50",
                            "side": trigger,
                            "type": trade_type,
                            "entry": entry,
                            "sl": sl,
                            "initial_sl": sl,
                            "t1": t1,
                            "t2": t2,
                            "t3": t3,
                            "highest_target": 0,
                            "time": now.strftime("%H:%M:%S")
                        }
                        save_daily_state(active_trade)

                        msg = (
                            f"⚡ <b>SAS LEVEL PULSE SIGNAL</b>\n"
                            f"━━━━━━━━━━━━━━━━━━━━\n"
                            f"📊 <b>Index:</b> NIFTY 50\n"
                            f"🎯 <b>Action:</b> {trigger}\n"
                            f"💡 <b>Pattern:</b> {trade_type}\n"
                            f"🔹 <b>Entry:</b> {entry:.2f}\n"
                            f"🛑 <b>Stop Loss:</b> {sl:.2f} (30.0 Pts)\n"
                            f"🎯 <b>Target 1:</b> {t1:.2f} (30.0 Pts)\n"
                            f"🎯 <b>Target 2:</b> {t2:.2f} (60.0 Pts)\n"
                            f"🎯 <b>Target 3:</b> {t3:.2f} (90.0 Pts)\n"
                            f"━━━━━━━━━━━━━━━━━━━━"
                        )
                        send_telegram_alert(msg)

                # Hourly heartbeat alert
                if now.minute == 0 and now.hour != last_heartbeat_hour and (9 <= now.hour <= 15):
                    last_heartbeat_hour = now.hour
                    diff = current_tick - close
                    pct = (diff / close) * 100 if close != 0 else 0.0
                    hb_msg = (
                        f"💓 <b>HOURLY STATUS ALERT</b>\n"
                        f"⏰ Time: {now.strftime('%I:%M:00 %p')} IST\n\n"
                        f"• NIFTY 50: {current_tick:.2f} ({diff:+.2f} | {pct:+.2f}%)\n"
                    )
                    send_telegram_alert(hb_msg)

                prev_tick = current_tick

        # Auto Square Off at 03:25 PM
        if current_time >= dtime(15, 25) and active_trade is not None:
            entry = active_trade["entry"]
            last_prc = current_tick if current_tick else entry
            pnl = (last_prc - entry) if active_trade["side"] == "BUY" else (entry - last_prc)
            active_trade["status"] = "EOD Auto-Exit"
            active_trade["exit_price"] = last_prc
            active_trade["pnl"] = pnl
            record_trade_to_ledger(active_trade)
            active_trade = None
            save_daily_state(None)
            send_telegram_alert(f"🔔 <b>MARKET CLOSING (03:25 PM):</b> Open position closed ({pnl:+.2f} Pts).")

        # 03:40 PM - Daily Summary & Monthly Tuesday Expiry Report
        if current_time >= dtime(15, 40):
            ledger = load_expiry_ledger()
            today_trades = [t for t in ledger if t.get("date") == today_date_str]
            today_pnl = sum(t.get("pnl", 0.0) for t in today_trades)
            
            # 1. Daily Report
            daily_summary = (
                f"📊 <b>DAILY PERFORMANCE SUMMARY (03:40 PM)</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"📅 <b>Date:</b> {today_str_display}\n"
                f"⚡ <b>Strategy:</b> SAS LEVEL PULSE\n"
                f"• Today Trades: {len(today_trades)}\n"
                f"📈 <b>Day Net Points:</b> {today_pnl:+.2f} Pts\n"
                f"━━━━━━━━━━━━━━━━━━━━"
            )
            send_telegram_alert(daily_summary)

            # 2. Monthly Tuesday Expiry Report
            if is_today_monthly_tuesday_expiry():
                total_cycle_pnl = sum(t.get("pnl", 0.0) for t in ledger)
                monthly_summary = (
                    f"🏆 <b>MONTHLY EXPIRY CYCLE REPORT (03:40 PM)</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"📅 <b>Expiry Date:</b> {today_str_display}\n"
                    f"⚡ <b>Strategy:</b> SAS LEVEL PULSE\n"
                    f"• Total Month Crossovers: {len(ledger)}\n"
                    f"📈 <b>Net Cycle Points:</b> {total_cycle_pnl:+.2f} Pts\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"<i>Monthly cycle completed. Ledger reset for next cycle.</i>"
                )
                send_telegram_alert(monthly_summary)
                clear_expiry_ledger()

            send_telegram_alert("🛑 <b>MARKET CLOSED (03:40 PM):</b> SAS Level Pulse shutting down safely.")
            break

        time.sleep(1)

if __name__ == "__main__":
    main()
