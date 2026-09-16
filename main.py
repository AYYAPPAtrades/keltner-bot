import pandas as pd
import numpy as np
import time
import requests
import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo
import yfinance as yf
from nselib import capital_market

# --- TIMEZONE CONFIGURATION ---
IST = ZoneInfo("Asia/Kolkata")

# --- TELEGRAM CONFIGURATION ---
TELEGRAM_BOT_TOKEN = "8921879577:AAHR_GPiDLyTtsrtMZx12CJ2nCM-YAUh3N0"
TELEGRAM_CHAT_ID = "6789591588"

def send_telegram_alert(message):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "disable_web_page_preview": True}
        requests.post(url, json=payload, timeout=3)
    except Exception as e:
        print(f"Telegram Error: {e}")

# --- MARKET HOLIDAY CHECK ---
try:
    holidays_df = capital_market.holiday_trading()
    today_str = datetime.now(IST).strftime('%d-%b-%Y')
    if holidays_df is not None and not holidays_df.empty:
        if 'tradingDate' in holidays_df.columns and today_str in holidays_df['tradingDate'].values:
            reason = holidays_df[holidays_df['tradingDate'] == today_str]['description'].values[0]
            send_telegram_alert(
                f"🏖️ MARKET HOLIDAY TODAY!\n"
                f"Reason: {reason}\n"
                f"Strategy: MOMENTUM SPIKE will not run today."
            )
            print(f"Market Holiday: {reason}. Exiting.")
            exit(0)
except Exception as e:
    print(f"Holiday check skipped: {e}")

INDEX_WATCHLIST = ["NIFTY 50", "NIFTY BANK"]
YF_TICKERS = {"NIFTY 50": "^NSEI", "NIFTY BANK": "^NSEBANK"}
TRADE_FILE = "active_trades_momentum.json"

trade_stats = {"total_signals": 0, "target_hits": 0, "sl_hits": 0}
levels_sent_today = False
last_heartbeat_hour = -1

# --- TRADE PERSISTENCE ---
def load_trades():
    default_structure = {idx: None for idx in INDEX_WATCHLIST}
    if os.path.exists(TRADE_FILE):
        try:
            with open(TRADE_FILE, 'r') as f:
                return json.load(f)
        except Exception:
            pass
    return default_structure

def save_trades(trades):
    with open(TRADE_FILE, 'w') as f:
        json.dump(trades, f, indent=4)

# --- HISTORICAL DATA & PREVIOUS CLOSE ---
prev_close_dict = {}

def get_historical_candles(index_name):
    global prev_close_dict
    try:
        ticker = YF_TICKERS.get(index_name)
        df_hist = yf.download(ticker, period="5d", interval="5m", progress=False)
        if not df_hist.empty:
            if isinstance(df_hist.columns, pd.MultiIndex):
                df_hist.columns = df_hist.columns.get_level_values(0)
            candles = []
            for _, row in df_hist.tail(60).iterrows():
                candles.append({
                    'Open': float(row['Open']),
                    'High': float(row['High']),
                    'Low': float(row['Low']),
                    'Close': float(row['Close'])
                })
            # Get previous day close for change calculation
            df_d = yf.download(ticker, period="2d", interval="1d", progress=False)
            if not df_d.empty:
                if isinstance(df_d.columns, pd.MultiIndex):
                    df_d.columns = df_d.columns.get_level_values(0)
                prev_close_dict[index_name] = float(df_d.iloc[-2]['Close']) if len(df_d) >= 2 else float(df_d.iloc[-1]['Close'])
            return candles
    except Exception as e:
        print(f"History fetch error {index_name}: {e}")
    return []

# --- 09:05 AM CAMARILLA LEVELS ---
def calculate_camarilla_levels(index_name):
    try:
        ticker = YF_TICKERS.get(index_name)
        df_d = yf.download(ticker, period="2d", interval="1d", progress=False)
        if not df_d.empty:
            if isinstance(df_d.columns, pd.MultiIndex):
                df_d.columns = df_d.columns.get_level_values(0)
            prev_day = df_d.iloc[-2] if len(df_d) >= 2 else df_d.iloc[-1]
            h, l, c = float(prev_day['High']), float(prev_day['Low']), float(prev_day['Close'])
            rng = h - l
            
            r3 = c + (rng * 1.1 / 4)
            r2 = c + (rng * 1.1 / 6)
            r1 = c + (rng * 1.1 / 12)
            s1 = c - (rng * 1.1 / 12)
            s2 = c - (rng * 1.1 / 6)
            s3 = c - (rng * 1.1 / 4)
            return {"R3": round(r3, 2), "R2": round(r2, 2), "R1": round(r1, 2), 
                    "S1": round(s1, 2), "S2": round(s2, 2), "S3": round(s3, 2)}
    except Exception as e:
        print(f"Level calc error {index_name}: {e}")
    return None

candle_history = {idx: get_historical_candles(idx) for idx in INDEX_WATCHLIST}
active_trades = load_trades()
current_candles = {idx: {"open": None, "high": -1, "low": 9999999, "close": None, "start_min": None} for idx in INDEX_WATCHLIST}
alert_candles = {idx: {"sell_alert": None, "buy_alert": None} for idx in INDEX_WATCHLIST}

send_telegram_alert(
    "⚡ MOMENTUM SPIKE BOT ACTIVE\n"
    "⏰ Time: " + datetime.now(IST).strftime('%H:%M:%S IST') + "\n"
    "• System initialized with full historical backup.\n"
    "• Monitoring NIFTY 50 & NIFTY BANK."
)

def get_live_index_data():
    try:
        return capital_market.market_watch_all_indices()
    except Exception as e:
        print(f"NSE Fetch Error: {e}")
        return None

# --- MAIN TRADING LOOP ---
while True:
    try:
        now = datetime.now(IST)
        current_time_str = now.strftime('%H:%M:%S IST')
        start_trade_time = datetime.strptime("09:30", "%H:%M").time()
        end_trade_time = datetime.strptime("15:20", "%H:%M").time()
        market_shutdown_time = datetime.strptime("15:40", "%H:%M").time()

        can_take_trades = (start_trade_time <= now.time() < end_trade_time)
        is_market_closing = (now.time() >= end_trade_time)

        # 1. 09:05 AM LEVELS ALERT
        if not levels_sent_today and now.hour == 9 and now.minute >= 5:
            levels_msg = "📊 DAILY SUPPORT & RESISTANCE (9:05 AM)\n⚡ Strategy: MOMENTUM SPIKE\n"
            for idx in INDEX_WATCHLIST:
                lvl = calculate_camarilla_levels(idx)
                if lvl:
                    levels_msg += (
                        f"\n🔹 {idx}:\n"
                        f"  R3: {lvl['R3']:.2f} | R2: {lvl['R2']:.2f} | R1: {lvl['R1']:.2f}\n"
                        f"  S1: {lvl['S1']:.2f} | S2: {lvl['S2']:.2f} | S3: {lvl['S3']:.2f}\n"
                    )
            send_telegram_alert(levels_msg)
            levels_sent_today = True

        # 2. 03:40 PM DAILY REPORT
        if now.time() >= market_shutdown_time:
            summary = (
                f"📋 DAILY PERFORMANCE REPORT\n"
                f"⚡ Strategy: MOMENTUM SPIKE\n"
                f"📅 Date: {now.strftime('%d-%b-%Y')}\n"
                f"• Total Signals: {trade_stats['total_signals']}\n"
                f"• Targets Hit: {trade_stats['target_hits']}\n"
                f"• Stop Loss Hit: {trade_stats['sl_hits']}\n\n"
                f"Bot safely completed today's session."
            )
            send_telegram_alert(summary)
            break

        raw_data = get_live_index_data()

        if raw_data is not None and not raw_data.empty:
            prices_dict = {}
            for index_name in INDEX_WATCHLIST:
                row = raw_data[raw_data['index'] == index_name]
                if not row.empty:
                    current_price = float(str(row['last'].values[0]).replace(',', ''))
                    prices_dict[index_name] = current_price
                    trade = active_trades[index_name]

                    # 3. POSITION TRACKING & EXITS
                    if trade is not None:
                        # 3:20 PM Auto Exit
                        if is_market_closing:
                            pnl = current_price - trade['entry'] if trade['type'] == 'BUY' else trade['entry'] - current_price
                            send_telegram_alert(
                                f"⏰ AUTO EXIT (03:20 PM)\n"
                                f"⚡ Strategy: MOMENTUM SPIKE\n"
                                f"Index: {index_name}\n"
                                f"💵 Exit Price: {current_price:.2f}\n"
                                f"📈 Points: {pnl:+.2f}"
                            )
                            active_trades[index_name] = None
                            save_trades(active_trades)
                            continue

                        # BUY ORDERS
                        if trade['type'] == 'BUY':
                            if not trade.get('t1_hit') and current_price >= trade['t1']:
                                trade['t1_hit'] = True
                                trade_stats['target_hits'] += 1
                                send_telegram_alert(
                                    f"🎯 TARGET 1 HIT!\n"
                                    f"⚡ Strategy: MOMENTUM SPIKE\n"
                                    f"Index: {index_name} (CALL)\n"
                                    f"💵 Target Price: {trade['t1']:.2f}\n"
                                    f"Current: {current_price:.2f}"
                                )
                                save_trades(active_trades)

                            if not trade.get('t2_hit') and current_price >= trade['t2']:
                                trade['t2_hit'] = True
                                trade_stats['target_hits'] += 1
                                send_telegram_alert(
                                    f"🎯 TARGET 2 HIT!\n"
                                    f"⚡ Strategy: MOMENTUM SPIKE\n"
                                    f"Index: {index_name} (CALL)\n"
                                    f"💵 Target Price: {trade['t2']:.2f}\n"
                                    f"Current: {current_price:.2f}"
                                )
                                save_trades(active_trades)

                            if current_price >= trade['t3']:
                                trade_stats['target_hits'] += 1
                                send_telegram_alert(
                                    f"🏆 TARGET 3 ACHIEVED!\n"
                                    f"⚡ Strategy: MOMENTUM SPIKE\n"
                                    f"Index: {index_name} (CALL)\n"
                                    f"💵 Final Target: {trade['t3']:.2f}\n"
                                    f"Trade Completed."
                                )
                                active_trades[index_name] = None
                                save_trades(active_trades)

                            elif current_price <= trade['sl']:
                                trade_stats['sl_hits'] += 1
                                active_trades[index_name] = None
                                save_trades(active_trades)
                                # T1 അടിച്ചിട്ടുണ്ടെങ്കിൽ SL അടിച്ചാലും alert അയക്കില്ല
                                if not trade.get('t1_hit', False):
                                    send_telegram_alert(
                                        f"🛑 STOP LOSS HIT!\n"
                                        f"⚡ Strategy: MOMENTUM SPIKE\n"
                                        f"Index: {index_name} (CALL)\n"
                                        f"🛑 SL Price: {trade['sl']:.2f}"
                                    )

                        # SELL ORDERS
                        elif trade['type'] == 'SELL':
                            if not trade.get('t1_hit') and current_price <= trade['t1']:
                                trade['t1_hit'] = True
                                trade_stats['target_hits'] += 1
                                send_telegram_alert(
                                    f"🎯 TARGET 1 HIT!\n"
                                    f"⚡ Strategy: MOMENTUM SPIKE\n"
                                    f"Index: {index_name} (PUT)\n"
                                    f"💵 Target Price: {trade['t1']:.2f}\n"
                                    f"Current: {current_price:.2f}"
                                )
                                save_trades(active_trades)

                            if not trade.get('t2_hit') and current_price <= trade['t2']:
                                trade['t2_hit'] = True
                                trade_stats['target_hits'] += 1
                                send_telegram_alert(
                                    f"🎯 TARGET 2 HIT!\n"
                                    f"⚡ Strategy: MOMENTUM SPIKE\n"
                                    f"Index: {index_name} (PUT)\n"
                                    f"💵 Target Price: {trade['t2']:.2f}\n"
                                    f"Current: {current_price:.2f}"
                                )
                                save_trades(active_trades)

                            if current_price <= trade['t3']:
                                trade_stats['target_hits'] += 1
                                send_telegram_alert(
                                    f"🏆 TARGET 3 ACHIEVED!\n"
                                    f"⚡ Strategy: MOMENTUM SPIKE\n"
                                    f"Index: {index_name} (PUT)\n"
                                    f"💵 Final Target: {trade['t3']:.2f}\n"
                                    f"Trade Completed."
                                )
                                active_trades[index_name] = None
                                save_trades(active_trades)

                            elif current_price >= trade['sl']:
                                trade_stats['sl_hits'] += 1
                                active_trades[index_name] = None
                                save_trades(active_trades)
                                # T1 അടിച്ചിട്ടുണ്ടെങ്കിൽ SL alert ഇല്ല
                                if not trade.get('t1_hit', False):
                                    send_telegram_alert(
                                        f"🛑 STOP LOSS HIT!\n"
                                        f"⚡ Strategy: MOMENTUM SPIKE\n"
                                        f"Index: {index_name} (PUT)\n"
                                        f"🛑 SL Price: {trade['sl']:.2f}"
                                    )

                    # 4. CANDLE AGGREGATION & 5 EMA SETUP
                    c_bucket = current_candles[index_name]
                    current_min_slot = (now.minute // 5) * 5

                    if c_bucket["start_min"] is None or c_bucket["start_min"] != current_min_slot:
                        if c_bucket["start_min"] is not None and c_bucket["open"] is not None:
                            candle_history[index_name].append({
                                'Open': c_bucket["open"], 'High': c_bucket["high"],
                                'Low': c_bucket["low"], 'Close': c_bucket["close"]
                            })
                            if len(candle_history[index_name]) > 60:
                                candle_history[index_name].pop(0)

                            df = pd.DataFrame(candle_history[index_name])
                            df['EMA5'] = df['Close'].ewm(span=5, adjust=False).mean()
                            last_c = df.iloc[-1]

                            # Sell Alert: Candle totally above 5 EMA
                            if last_c['Low'] > last_c['EMA5']:
                                alert_candles[index_name]["sell_alert"] = {'high': last_c['High'], 'low': last_c['Low']}
                            else:
                                alert_candles[index_name]["sell_alert"] = None

                            # Buy Alert: Candle totally below 5 EMA
                            if last_c['High'] < last_c['EMA5']:
                                alert_candles[index_name]["buy_alert"] = {'high': last_c['High'], 'low': last_c['Low']}
                            else:
                                alert_candles[index_name]["buy_alert"] = None

                        c_bucket["open"] = current_price
                        c_bucket["high"] = current_price
                        c_bucket["low"] = current_price
                        c_bucket["close"] = current_price
                        c_bucket["start_min"] = current_min_slot
                    else:
                        c_bucket["high"] = max(c_bucket["high"], current_price)
                        c_bucket["low"] = min(c_bucket["low"], current_price)
                        c_bucket["close"] = current_price

                    # 5. INSTANT SIGNAL WITH EXACT ICONS
                    if can_take_trades and active_trades[index_name] is None:
                        # SELL BREAKOUT
                        s_alert = alert_candles[index_name]["sell_alert"]
                        if s_alert and current_price < s_alert['low']:
                            risk = round(s_alert['high'] - s_alert['low'], 2)
                            if risk >= 8.0:
                                trade_stats['total_signals'] += 1
                                sl = round(s_alert['high'], 2)
                                t1 = round(current_price - (risk * 1.5), 2)
                                t2 = round(current_price - (risk * 2.0), 2)
                                t3 = round(current_price - (risk * 3.0), 2)
                                active_trades[index_name] = {
                                    'type': 'SELL', 'entry': current_price, 'sl': sl, 
                                    't1': t1, 't2': t2, 't3': t3, 't1_hit': False, 't2_hit': False
                                }
                                save_trades(active_trades)
                                alert_candles[index_name]["sell_alert"] = None
                                
                                # Exact format as requested
                                send_telegram_alert(
                                    f"🔴 {index_name} SELL SIGNAL\n\n"
                                    f"⚡ Strategy: MOMENTUM SPIKE\n"
                                    f"⏰ Time: {current_time_str}\n"
                                    f"💵 Entry: {current_price:.2f}\n"
                                    f"🛑 Stop Loss: {sl:.2f}\n\n"
                                    f"🎯 Target 1: {t1:.2f}\n"
                                    f"🎯 Target 2: {t2:.2f}\n"
                                    f"🎯 Target 3: {t3:.2f}"
                                )

                        # BUY BREAKOUT
                        b_alert = alert_candles[index_name]["buy_alert"]
                        if b_alert and current_price > b_alert['high']:
                            risk = round(b_alert['high'] - b_alert['low'], 2)
                            if risk >= 8.0:
                                trade_stats['total_signals'] += 1
                                sl = round(b_alert['low'], 2)
                                t1 = round(current_price + (risk * 1.5), 2)
                                t2 = round(current_price + (risk * 2.0), 2)
                                t3 = round(current_price + (risk * 3.0), 2)
                                active_trades[index_name] = {
                                    'type': 'BUY', 'entry': current_price, 'sl': sl, 
                                    't1': t1, 't2': t2, 't3': t3, 't1_hit': False, 't2_hit': False
                                }
                                save_trades(active_trades)
                                alert_candles[index_name]["buy_alert"] = None
                                
                                # Exact format as requested
                                send_telegram_alert(
                                    f"🟢 {index_name} BUY SIGNAL\n\n"
                                    f"⚡ Strategy: MOMENTUM SPIKE\n"
                                    f"⏰ Time: {current_time_str}\n"
                                    f"💵 Entry: {current_price:.2f}\n"
                                    f"🛑 Stop Loss: {sl:.2f}\n\n"
                                    f"🎯 Target 1: {t1:.2f}\n"
                                    f"🎯 Target 2: {t2:.2f}\n"
                                    f"🎯 Target 3: {t3:.2f}"
                                )

            # 6. EXACT HOURLY STATUS ALERT (Every Hour)
            if now.minute == 0 and now.hour != last_heartbeat_hour and (9 <= now.hour <= 15):
                last_heartbeat_hour = now.hour
                hb_msg = (
                    f"💓 HOURLY STATUS ALERT\n"
                    f"⏰ Time: {current_time_str}\n\n"
                )
                for idx, prc in prices_dict.items():
                    prev_c = prev_close_dict.get(idx, prc)
                    diff = prc - prev_c
                    pct = (diff / prev_c) * 100 if prev_c else 0
                    sign = "+" if diff >= 0 else ""
                    hb_msg += f"• {idx}: {prc:.2f} ({sign}{diff:.2f} | {sign}{pct:.2f}%)\n"
                send_telegram_alert(hb_msg)

        time.sleep(5)  # Fast 5-second scanner loop
    except Exception as e:
        print(f"Loop Exception: {e}")
        time.sleep(5)
