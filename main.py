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
from datetime import datetime, time as dtime
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
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8804327561:AAHYL_srWzPSWCZR5aJe_tM0fD24HblsL_Q")
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID", "@niftylivevetrade")
TELEGRAM_ADMIN_CHAT_ID = os.getenv("TELEGRAM_ADMIN_CHAT_ID", "6677937397")

# Watchlist & Tickers (NIFTY 50 Only)
INDEX_WATCHLIST = ["NIFTY 50"]
YF_TICKERS = {"NIFTY 50": "^NSEI"}

# State Files
DAILY_STATE_FILE = "daily_active_trades.json"
EXPIRY_LEDGER_FILE = "expiry_trades_ledger.json"

telegram_session = requests.Session()

# ==========================================
# 2. TELEGRAM UTILITY FUNCTIONS
# ==========================================
def send_telegram_alert(message, parse_mode="HTML", chat_id=None):
    if not TELEGRAM_BOT_TOKEN:
        return
    targets = [chat_id] if chat_id else [TELEGRAM_CHANNEL_ID, TELEGRAM_ADMIN_CHAT_ID]
    for cid in targets:
        if not cid:
            continue
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {"chat_id": cid, "text": message, "parse_mode": parse_mode}
        try:
            telegram_session.post(url, json=payload, timeout=4)
        except Exception as e:
            logger.error(f"Telegram alert delivery error to {cid}: {e}")

# ==========================================
# 3. STATE & LEDGER MANAGEMENT
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

def record_trade_to_ledger(trade_record):
    ledger = []
    if os.path.exists(EXPIRY_LEDGER_FILE):
        try:
            with open(EXPIRY_LEDGER_FILE, "r") as f:
                ledger = json.load(f)
        except Exception:
            ledger = []
    ledger.append(trade_record)
    try:
        with open(EXPIRY_LEDGER_FILE, "w") as f:
            json.dump(ledger, f, indent=4)
    except Exception as e:
        logger.error(f"Error saving ledger: {e}")

# ==========================================
# 4. MARKET DATA & CALCULATIONS (ZERO-DELAY NSE ENGINE)
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
        "L5": close - (1.1 * diff)
    }
    return levels

# Zero-delay live NSE data fetcher
def get_live_tick():
    try:
        data = capital_market.market_watch_all_indices()
        if data is not None and not data.empty:
            row = data[data['index'] == "NIFTY 50"]
            if not row.empty:
                val = str(row['last'].values[0]).replace(',', '')
                return float(val)
    except Exception:
        pass
    # Yahoo Finance fallback
    try:
        ticker = yf.Ticker(YF_TICKERS["NIFTY 50"])
        df = ticker.history(period="1d", interval="1m")
        if not df.empty:
            return float(df['Close'].iloc[-1])
    except Exception as e:
        logger.error(f"Error fetching live tick: {e}")
    return None

def fetch_atm_options(spot_price):
    try:
        chain = capital_market.live_index_option_chain("NIFTY")
        df = pd.DataFrame(chain)
        df['strike'] = pd.to_numeric(df['strikePrice'], errors='coerce')
        closest_strike = df.iloc[(df['strike'] - spot_price).abs().argsort()[:1]]['strike'].values[0]
        return closest_strike
    except Exception:
        strike = round(spot_price / 50) * 50
        return strike

# ==========================================
# 5. CORE EXECUTION BOT
# ==========================================
def main():
    logger.info("Initializing SAS Level Pulse Bot...")

    # --- BOT STARTUP ALERT (ADMIN ONLY) ---
    startup_msg = (
        f"🚀 <b>SAS LEVEL PULSE LIVE</b>\n\n"
        f"⚡ <b>Strategy:</b> SAS LEVEL PULSE\n"
        f"📊 <b>Index:</b> NIFTY 50\n"
        f"🕒 <b>Time:</b> {datetime.now(IST).strftime('%I:%M:%S %p')} IST\n"
        f"🛡️ <b>Engine Status:</b> Running & Monitoring Active (Zero-Delay NSE Feed)."
    )
    send_telegram_alert(startup_msg, chat_id=TELEGRAM_ADMIN_CHAT_ID)

    high, low, close = fetch_previous_ohlc()
    if not high:
        logger.error("Failed to obtain previous session OHLC. Retrying on next loop.")
        return

    levels = calculate_levels(high, low, close)
    logger.info(f"NIFTY Levels Loaded: R4={levels['H4']:.2f}, R3={levels['H3']:.2f}, S3={levels['L3']:.2f}, S4={levels['L4']:.2f}")

    levels_posted = False
    active_trade = load_backup_state()
    prev_tick = None
    last_heartbeat_hour = -1

    while True:
        now = datetime.now(IST)
        current_time = now.time()

        # 09:05 AM - Levels Alert (ADMIN ONLY)
        if current_time >= dtime(9, 5) and not levels_posted:
            msg = (
                f"<b>⚡ DAILY MOMENTUM SPIKE LEVELS (09:05 AM)</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"📊 <b>Index:</b> NIFTY 50\n"
                f"🔹 <b>Bullish Breakout (R4):</b> {levels['H4']:.2f}\n"
                f"🔹 <b>Resistance Reversal (R3):</b> {levels['H3']:.2f}\n"
                f"🔸 <b>Support Reversal (S3):</b> {levels['L3']:.2f}\n"
                f"🔸 <b>Bearish Breakdown (S4):</b> {levels['L4']:.2f}\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"<i>Tracking live tick-by-tick momentum.</i>\n"
                f"⚠️ <i>Strictly for educational study only. Not SEBI registered.</i>"
            )
            send_telegram_alert(msg, chat_id=TELEGRAM_ADMIN_CHAT_ID)
            levels_posted = True

        # 09:15 to 15:25 - Active Scanning & Monitoring
        if dtime(9, 15) <= current_time <= dtime(15, 25):
            current_tick = get_live_tick()
            if current_tick and prev_tick:
                # -----------------------------------------------
                # SCENARIO A: MONITOR ACTIVE TRADE (PUBLIC + ADMIN)
                # -----------------------------------------------
                if active_trade is not None:
                    side = active_trade["side"]
                    entry = active_trade["entry"]
                    t1 = active_trade["t1"]
                    t2 = active_trade["t2"]
                    t3 = active_trade["t3"]
                    sl = active_trade["sl"]

                    # LONG / CALL POSITION
                    if side == "BUY CE":
                        # Hit Target 3 -> Full Exit
                        if current_tick >= t3:
                            msg = f"🎯 <b>TARGET 3 ACHIEVED! [BUY CE]</b>\nPrice: {current_tick:.2f}\nTrade closed in full profit."
                            send_telegram_alert(msg)
                            active_trade["status"] = "Target 3 Achieved"
                            record_trade_to_ledger(active_trade)
                            active_trade = None
                            save_daily_state(None)

                        # Hit Target 2 -> Trail SL to T1
                        elif current_tick >= t2 and active_trade.get("highest_target", 0) < 2:
                            active_trade["highest_target"] = 2
                            active_trade["sl"] = t1
                            msg = f"🎯 <b>TARGET 2 ACHIEVED! [BUY CE]</b>\nPrice: {current_tick:.2f}\nSL trailed to Target 1 ({t1:.2f})."
                            send_telegram_alert(msg)
                            save_daily_state(active_trade)

                        # Hit Target 1 -> Trail SL to Cost
                        elif current_tick >= t1 and active_trade.get("highest_target", 0) < 1:
                            active_trade["highest_target"] = 1
                            active_trade["sl"] = entry
                            msg = f"🎯 <b>TARGET 1 ACHIEVED! [BUY CE]</b>\nPrice: {current_tick:.2f}\nSL trailed safely to Cost ({entry:.2f}). Ready for new opportunities."
                            send_telegram_alert(msg)
                            save_daily_state(active_trade)

                        # Stop Loss Hit
                        elif current_tick <= sl:
                            if active_trade.get("highest_target", 0) >= 1:
                                active_trade["status"] = f"Target {active_trade['highest_target']} Achieved (Trail Exit)"
                            else:
                                msg = f"🛑 <b>STOP LOSS HIT [BUY CE]</b>\nPrice: {current_tick:.2f}\nExited position."
                                send_telegram_alert(msg)
                                active_trade["status"] = "Stop Loss Hit"
                            record_trade_to_ledger(active_trade)
                            active_trade = None
                            save_daily_state(None)

                    # SHORT / PUT POSITION
                    elif side == "BUY PE":
                        # Hit Target 3 -> Full Exit
                        if current_tick <= t3:
                            msg = f"🎯 <b>TARGET 3 ACHIEVED! [BUY PE]</b>\nPrice: {current_tick:.2f}\nTrade closed in full profit."
                            send_telegram_alert(msg)
                            active_trade["status"] = "Target 3 Achieved"
                            record_trade_to_ledger(active_trade)
                            active_trade = None
                            save_daily_state(None)

                        # Hit Target 2 -> Trail SL to T1
                        elif current_tick >= t2 and active_trade.get("highest_target", 0) < 2:
                            active_trade["highest_target"] = 2
                            active_trade["sl"] = t1
                            msg = f"🎯 <b>TARGET 2 ACHIEVED! [BUY PE]</b>\nPrice: {current_tick:.2f}\nSL trailed to Target 1 ({t1:.2f})."
                            send_telegram_alert(msg)
                            save_daily_state(active_trade)

                        # Hit Target 1 -> Trail SL to Cost
                        elif current_tick >= t1 and active_trade.get("highest_target", 0) < 1:
                            active_trade["highest_target"] = 1
                            active_trade["sl"] = entry
                            msg = f"🎯 <b>TARGET 1 ACHIEVED! [BUY PE]</b>\nPrice: {current_tick:.2f}\nSL trailed safely to Cost ({entry:.2f}). Ready for new opportunities."
                            send_telegram_alert(msg)
                            save_daily_state(active_trade)

                        # Stop Loss Hit
                        elif current_tick >= sl:
                            if active_trade.get("highest_target", 0) >= 1:
                                active_trade["status"] = f"Target {active_trade['highest_target']} Achieved (Trail Exit)"
                            else:
                                msg = f"🛑 <b>STOP LOSS HIT [BUY PE]</b>\nPrice: {current_tick:.2f}\nExited position."
                                send_telegram_alert(msg)
                                active_trade["status"] = "Stop Loss Hit"
                            record_trade_to_ledger(active_trade)
                            active_trade = None
                            save_daily_state(None)

                # -----------------------------------------------
                # SCENARIO B: SCAN FOR NEW TRADES (PUBLIC + ADMIN)
                # -----------------------------------------------
                if active_trade is None:
                    trigger = None
                    trade_type = ""
                    risk_pts = 25.0

                    # 1. Bullish Breakout (Above H4)
                    if prev_tick < levels["H4"] and current_tick >= levels["H4"]:
                        trigger = "BUY CE"
                        trade_type = "Breakout Spike (Above R4)"
                        entry = current_tick
                        sl = entry - risk_pts
                        t1 = entry + (risk_pts * 1.417)
                        t2 = entry + (risk_pts * 1.889)
                        t3 = entry + (risk_pts * 2.834)

                    # 2. Bullish Reversal (Bounce from S3)
                    elif prev_tick <= levels["L3"] and current_tick > levels["L3"]:
                        trigger = "BUY CE"
                        trade_type = "Support Bounce (Reversal from S3)"
                        entry = current_tick
                        sl = entry - risk_pts
                        t1 = entry + (risk_pts * 1.417)
                        t2 = entry + (risk_pts * 1.889)
                        t3 = entry + (risk_pts * 2.834)

                    # 3. Bearish Breakdown (Below L4)
                    elif prev_tick > levels["L4"] and current_tick <= levels["L4"]:
                        trigger = "BUY PE"
                        trade_type = "Breakdown Spike (Below S4)"
                        entry = current_tick
                        sl = entry + risk_pts
                        t1 = entry - (risk_pts * 1.417)
                        t2 = entry - (risk_pts * 1.889)
                        t3 = entry - (risk_pts * 2.834)

                    # 4. Bearish Reversal (Rejection from R3)
                    elif prev_tick >= levels["H3"] and current_tick < levels["H3"]:
                        trigger = "BUY PE"
                        trade_type = "Resistance Rejection (Reversal from R3)"
                        entry = current_tick
                        sl = entry + risk_pts
                        t1 = entry - (risk_pts * 1.417)
                        t2 = entry - (risk_pts * 1.889)
                        t3 = entry - (risk_pts * 2.834)

                    if trigger:
                        strike = fetch_atm_options(entry)
                        active_trade = {
                            "index": "NIFTY 50",
                            "side": trigger,
                            "type": trade_type,
                            "strike": f"{int(strike)} {trigger.split()[-1]}",
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
                            f"🎯 <b>Action:</b> {trigger} ({active_trade['strike']})\n"
                            f"💡 <b>Pattern:</b> {trade_type}\n"
                            f"🔹 <b>Entry:</b> {entry:.2f}\n"
                            f"🛑 <b>Stop Loss:</b> {sl:.2f}\n"
                            f"🎯 <b>Target 1:</b> {t1:.2f}\n"
                            f"🎯 <b>Target 2:</b> {t2:.2f}\n"
                            f"🎯 <b>Target 3:</b> {t3:.2f}\n"
                            f"━━━━━━━━━━━━━━━━━━━━\n"
                            f"⚠️ <i>Strictly for educational study only. Not SEBI registered.</i>"
                        )
                        send_telegram_alert(msg)

                # --- HOURLY STATUS ALERT (ADMIN ONLY) ---
                if now.minute == 0 and now.hour != last_heartbeat_hour and (9 <= now.hour <= 15):
                    last_heartbeat_hour = now.hour
                    diff = current_tick - close
                    pct = (diff / close) * 100 if close != 0 else 0.0
                    hb_msg = (
                        f"💓 <b>HOURLY STATUS ALERT</b>\n"
                        f"⏰ Time: {now.strftime('%I:%M:00 %p')} IST\n\n"
                        f"• NIFTY 50: {current_tick:.2f} ({diff:+.2f} | {pct:+.2f}%)\n"
                    )
                    send_telegram_alert(hb_msg, chat_id=TELEGRAM_ADMIN_CHAT_ID)

            if current_tick:
                prev_tick = current_tick

        # 03:25 PM - Auto-Square Off (PUBLIC + ADMIN)
        if current_time >= dtime(15, 25) and active_trade is not None:
            active_trade["status"] = "EOD Auto-Exit"
            record_trade_to_ledger(active_trade)
            active_trade = None
            save_daily_state(None)
            send_telegram_alert("🔔 <b>MARKET CLOSING:</b> All open positions auto-squared off.")

        # 03:40 PM - Safe Shutdown (ADMIN ONLY)
        if current_time >= dtime(15, 40):
            send_telegram_alert("🛑 <b>MARKET CLOSED (03:40 PM):</b> SAS Level Pulse shutting down safely.", chat_id=TELEGRAM_ADMIN_CHAT_ID)
            break

        # 1-second interval fast live scanning
        time.sleep(1)

if __name__ == "__main__":
    main()
