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
        # Instant delivery with low timeout
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
            send_telegram_alert(f"MOMENTUM SPIKE\nMARKET HOLIDAY TODAY!\nReason: {reason}\nScanner will not run today.")
            print(f"Market Holiday: {reason}. Exiting.")
            exit(0)
except Exception as e:
    print(f"Holiday check skipped: {e}")

INDEX_WATCHLIST = ["NIFTY 50", "NIFTY BANK"]
YF_TICKERS = {"NIFTY 50": "^NSEI", "NIFTY BANK": "^NSEBANK"}
TRADE_FILE = "momentum_spike_trades.json"

trade_stats = {"total_signals": 0, "target_hits": 0, "sl_hits": 0}
levels_sent_today = False
last_heartbeat_hour = -1

# --- PERSISTENCE ---
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

# --- 5-DAY HISTORICAL DATA ---
def get_historical_candles(index_name):
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
            return candles
    except Exception as e:
        print(f"History Error {index_name}: {e}")
    return []

# --- CAMARILLA PIVOT CALCULATOR FOR 9:05 AM LEVELS ---
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
            s3 = c - (rng * 1.1 / 1.149) # Camarilla standard S3
            return {"R3": round(r3, 2), "R2": round(r2, 2), "R1": round(r1, 2), 
                    "S1": round(s1, 2), "S2": round(s2, 2), "S3": round(s3, 2)}
    except Exception as e:
        print(f"Level Calc Error {index_name}: {e}")
    return None

candle_history = {idx: get_historical_candles(idx) for idx in INDEX_WATCHLIST}
active_trades = load_trades()
current_candles = {idx: {"open": None, "high": -1, "low": 9999999, "close": None, "start_min": None} for idx in INDEX_WATCHLIST}
alert_candles = {idx: {"sell_alert": None, "buy_alert": None} for idx in INDEX_WATCHLIST}

send_telegram_alert(
    "MOMENTUM SPIKE\n"
    "SCANNER ACTIVATED & ARMED!\n"
    "• Strategy: 5 EMA Reversal + Pivot Breakout\n"
    "• Window: 09:00 AM - 03:40 PM IST\n"
    "• Auto-Recovery & Backup Enabled"
)

def get_live_index_data():
    try:
        return capital_market.market_watch_all_indices()
    except Exception as e:
        print(f"NSE Fetch Error: {e}")
        return None

# --- MAIN LOOP ---
while True:
    try:
        now = datetime.now(IST)
        current_time_str = now.strftime('%H:%M:%S')
        start_trade_time = datetime.strptime("09:30", "%H:%M").time()
        end_trade_time = datetime.strptime("15:20", "%H:%M").time()
        market_shutdown_time = datetime.strptime("15:40", "%H:%M").time()

        can_take_trades = (start_trade_time <= now.time() < end_trade_time)
        is_market_closing = (now.time() >= end_trade_time)

        # 1. SEND 9:05 AM SUPPORT & RESISTANCE LEVELS
        if not levels_sent_today and now.hour == 9 and now.minute >= 5:
            levels_msg = "MOMENTUM SPIKE\n📊 DAILY SUPPORT & RESISTANCE (Camarilla):\n"
            for idx in INDEX_WATCHLIST:
                lvl = calculate_camarilla_levels(idx)
                if lvl:
                    levels_msg += f"\n• {idx}:\n  R3: {lvl['R3']} | R2: {lvl['R2']} | R1: {lvl['R1']}\n  S1: {lvl['S1']} | S2: {lvl['S2']} | S3: {lvl['S3']}\n"
            send_telegram_alert(levels_msg)
            levels_sent_today = True

        # 2. 03:40 PM CLEAN SHUTDOWN & DAILY REPORT
        if now.time() >= market_shutdown_time:
            summary = (
                f"MOMENTUM SPIKE\n"
                f"MARKET CLOSED (DAILY REPORT)\n"
                f"Date: {now.strftime('%d-%b-%Y')}\n"
                f"• Total Signals: {trade_stats['total_signals']}\n"
                f"• Target Hits: {trade_stats['target_hits']}\n"
                f"• SL Hits: {trade_stats['sl_hits']}\n\n"
                f"Bot shutting down safely."
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

                    # 3. LIVE TRADE MANAGEMENT & TARGETS
                    if trade is not None:
                        if is_market_closing:
                            pnl = current_price - trade['entry'] if trade['type'] == 'BUY' else trade['entry'] - current_price
                            send_telegram_alert(
                                f"MOMENTUM SPIKE\n⏰ AUTO EXIT (03:20 PM)!\n"
                                f"Index: {index_name}\nExit: {current_price:.2f}\nPnL: {pnl:+.2f}"
                            )
                            active_trades[index_name] = None
                            save_trades(active_trades)
                            continue

                        # BUY TRADES (CALL)
                        if trade['type'] == 'BUY':
                            if not trade.get('t1_hit') and current_price >= trade['t1']:
                                trade['t1_hit'] = True
                                trade_stats['target_hits'] += 1
                                send_telegram_alert(f"MOMENTUM SPIKE\n🎯 TARGET 1 HIT (1:1.5)!\nIndex: {index_name} (CALL)\nPrice: {current_price:.2f}\nT1: {trade['t1']}")
                                save_trades(active_trades)

                            if not trade.get('t2_hit') and current_price >= trade['t2']:
                                trade['t2_hit'] = True
                                trade_stats['target_hits'] += 1
                                send_telegram_alert(f"MOMENTUM SPIKE\n🎯 TARGET 2 HIT (1:2.0)!\nIndex: {index_name} (CALL)\nPrice: {current_price:.2f}\nT2: {trade['t2']}")
                                save_trades(active_trades)

                            if current_price >= trade['t3']:
                                trade_stats['target_hits'] += 1
                                send_telegram_alert(f"MOMENTUM SPIKE\n🏆 ALL TARGETS HIT (T3)!\nIndex: {index_name} (CALL)\nExit: {current_price:.2f}")
                                active_trades[index_name] = None
                                save_trades(active_trades)

                            elif current_price <= trade['sl']:
                                trade_stats['sl_hits'] += 1
                                active_trades[index_name] = None
                                save_trades(active_trades)
                                # T1 അടിച്ചശേഷമാണെങ്കിൽ SL അടിച്ചാൽ അലേർട്ട് അയക്കില്ല (Silent Close)
                                if not trade.get('t1_hit', False):
                                    send_telegram_alert(f"MOMENTUM SPIKE\n🛑 STOP LOSS HIT!\nIndex: {index_name} (CALL)\nPrice: {current_price:.2f}")

                        # SELL TRADES (PUT)
                        elif trade['type'] == 'SELL':
                            if not trade.get('t1_hit') and current_price <= trade['t1']:
                                trade['t1_hit'] = True
                                trade_stats['target_hits'] += 1
                                send_telegram_alert(f"MOMENTUM SPIKE\n🎯 TARGET 1 HIT (1:1.5)!\nIndex: {index_name} (PUT)\nPrice: {current_price:.2f}\nT1: {trade['t1']}")
                                save_trades(active_trades)

                            if not trade.get('t2_hit') and current_price <= trade['t2']:
                                trade['t2_hit'] = True
                                trade_stats['target_hits'] += 1
                                send_telegram_alert(f"MOMENTUM SPIKE\n🎯 TARGET 2 HIT (1:2.0)!\nIndex: {index_name} (PUT)\nPrice: {current_price:.2f}\nT2: {trade['t2']}")
                                save_trades(active_trades)

                            if current_price <= trade['t3']:
                                trade_stats['target_hits'] += 1
                                send_telegram_alert(f"MOMENTUM SPIKE\n🏆 ALL TARGETS HIT (T3)!\nIndex: {index_name} (PUT)\nExit: {current_price:.2f}")
                                active_trades[index_name] = None
                                save_trades(active_trades)

                            elif current_price >= trade['sl']:
                                trade_stats['sl_hits'] += 1
                                active_trades[index_name] = None
                                save_trades(active_trades)
                                # T1 അടിച്ചശേഷമാണെങ്കിൽ SL അടിച്ചാൽ അലേർട്ട് വേണ്ട
                                if not trade.get('t1_hit', False):
                                    send_telegram_alert(f"MOMENTUM SPIKE\n🛑 STOP LOSS HIT!\nIndex: {index_name} (PUT)\nPrice: {current_price:.2f}")

                    # 4. CANDLE AGGREGATION & 5 EMA CHECK
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

                            if last_c['Low'] > last_c['EMA5']:
                                alert_candles[index_name]["sell_alert"] = {'high': last_c['High'], 'low': last_c['Low']}
                            else:
                                alert_candles[index_name]["sell_alert"] = None

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

                    # 5. INSTANT SIGNAL EXECUTION
                    if can_take_trades and active_trades[index_name] is None:
                        s_alert = alert_candles[index_name]["sell_alert"]
                        if s_alert and current_price < s_alert['low']:
                            risk = round(s_alert['high'] - s_alert['low'], 2)
                            if risk >= 8.0:
                                trade_stats['total_signals'] += 1
                                sl = round(s_alert['high'], 2)
                                t1 = round(current_price - (risk * 1.5), 2)
                                t2 = round(current_price - (risk * 2.0), 2)
                                t3 = round(current_price - (risk * 3.0), 2)
                                active_trades[index_name] = {'type': 'SELL', 'entry': current_price, 'sl': sl, 't1': t1, 't2': t2, 't3': t3, 't1_hit': False, 't2_hit': False}
                                save_trades(active_trades)
                                alert_candles[index_name]["sell_alert"] = None
                                send_telegram_alert(
                                    f"MOMENTUM SPIKE\n🔴 SELL SIGNAL (BUY PUT)!\n"
                                    f"Index: {index_name} | Entry: {current_price:.2f}\n"
                                    f"SL: {sl} | T1: {t1} | T2: {t2} | T3: {t3}"
                                )

                        b_alert = alert_candles[index_name]["buy_alert"]
                        if b_alert and current_price > b_alert['high']:
                            risk = round(b_alert['high'] - b_alert['low'], 2)
                            if risk >= 8.0:
                                trade_stats['total_signals'] += 1
                                sl = round(b_alert['low'], 2)
                                t1 = round(current_price + (risk * 1.5), 2)
                                t2 = round(current_price + (risk * 2.0), 2)
                                t3 = round(current_price + (risk * 3.0), 2)
                                active_trades[index_name] = {'type': 'BUY', 'entry': current_price, 'sl': sl, 't1': t1, 't2': t2, 't3': t3, 't1_hit': False, 't2_hit': False}
                                save_trades(active_trades)
                                alert_candles[index_name]["buy_alert"] = None
                                send_telegram_alert(
                                    f"MOMENTUM SPIKE\n🟢 BUY SIGNAL (BUY CALL)!\n"
                                    f"Index: {index_name} | Entry: {current_price:.2f}\n"
                                    f"SL: {sl} | T1: {t1} | T2: {t2} | T3: {t3}"
                                )

        time.sleep(5) # Fast loop for zero delay
    except Exception as e:
        print(f"Loop Error: {e}")
        time.sleep(5)
