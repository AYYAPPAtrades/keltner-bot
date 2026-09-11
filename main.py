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
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message}
        res = requests.post(url, json=payload, timeout=8)
        print(f"Telegram status: {res.status_code}")
    except Exception as e:
        print(f"Telegram Connection Error: {e}")

# --- MARKET HOLIDAY CHECK ---
try:
    holidays_df = capital_market.holiday_trading()
    today_str = datetime.now(IST).strftime('%d-%b-%Y')
    if holidays_df is not None and not holidays_df.empty:
        if 'tradingDate' in holidays_df.columns and today_str in holidays_df['tradingDate'].values:
            reason = holidays_df[holidays_df['tradingDate'] == today_str]['description'].values[0]
            send_telegram_alert(f"MARKET HOLIDAY TODAY!\nReason: {reason}\nScanner will not run today. Enjoy your holiday!")
            print(f"Market Holiday: {reason}. Exiting cleanly.")
            exit(0)
except Exception as e:
    print(f"Holiday check skipped: {e}")

INDEX_WATCHLIST = ["NIFTY 50", "NIFTY BANK"]
YF_TICKERS = {"NIFTY 50": "^NSEI", "NIFTY BANK": "^NSEBANK"}
STRATEGIES = ["KELTNER", "ICHIMOKU"]
TRADE_FILE = "active_trades.json"

trade_stats = {"total_signals": 0, "target_hits": 0, "sl_hits": 0}
last_heartbeat_hour = -1

# --- PERSISTENCE ---
def load_trades():
    default_structure = {idx: {"KELTNER": None, "ICHIMOKU": None} for idx in INDEX_WATCHLIST}
    if os.path.exists(TRADE_FILE):
        try:
            with open(TRADE_FILE, 'r') as f:
                data = json.load(f)
                for idx in INDEX_WATCHLIST:
                    if idx not in data or not isinstance(data[idx], dict):
                        data[idx] = {"KELTNER": None, "ICHIMOKU": None}
                return data
        except Exception:
            pass
    return default_structure

def save_trades(trades):
    with open(TRADE_FILE, 'w') as f:
        json.dump(trades, f, indent=4)

# --- INITIAL HISTORICAL CANDLES FETCH ---
def get_historical_5m_candles(index_name):
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
            print(f"Loaded {len(candles)} historical 5m candles for {index_name}")
            return candles
    except Exception as e:
        print(f"History Fetch Error for {index_name}: {e}")
    return []

candle_history = {idx: get_historical_5m_candles(idx) for idx in INDEX_WATCHLIST}
active_trades = load_trades()
current_candles = {idx: {"open": None, "high": -1, "low": 9999999, "close": None, "start_min": None} for idx in INDEX_WATCHLIST}
last_signals = {idx: {"KELTNER": None, "ICHIMOKU": None} for idx in INDEX_WATCHLIST}

send_telegram_alert("DUAL SCANNER ACTIVATED!\n• Strategy 1: Keltner Channel Breakout\n• Strategy 2: Ichimoku Cloud Breakout\n• Trading Window: 09:30 AM - 03:20 PM IST\n• Operating Session: 09:00 AM - 03:40 PM IST\n• Historical Data Pre-loaded & Timezone Locked to IST")

def calculate_indicators(df):
    high, low, close = df['High'], df['Low'], df['Close']
    
    tr = pd.concat([high - low, (high - close.shift(1)).abs(), (low - close.shift(1)).abs()], axis=1).max(axis=1)
    atr = tr.ewm(span=10, adjust=False).mean()
    df['ATR'] = atr
    
    df['KC_Middle'] = close.ewm(span=20, adjust=False).mean()
    df['KC_Upper'] = df['KC_Middle'] + (1.5 * atr)
    df['KC_Lower'] = df['KC_Middle'] - (1.5 * atr)
    
    tenkan = (high.rolling(window=9, min_periods=1).max() + low.rolling(window=9, min_periods=1).min()) / 2
    kijun = (high.rolling(window=26, min_periods=1).max() + low.rolling(window=26, min_periods=1).min()) / 2
    senkou_a = (tenkan + kijun) / 2
    senkou_b = (high.rolling(window=52, min_periods=1).max() + low.rolling(window=52, min_periods=1).min()) / 2
    
    df['Cloud_Top'] = np.maximum(senkou_a, senkou_b)
    df['Cloud_Bottom'] = np.minimum(senkou_a, senkou_b)
    return df

def get_live_index_data():
    try:
        return capital_market.market_watch_all_indices()
    except Exception as e:
        print(f"NSE Fetch Error: {e}")
        return None

while True:
    try:
        now = datetime.now(IST)
        current_time_str = now.strftime('%H:%M:%S')
        start_trade_time = datetime.strptime("09:30", "%H:%M").time()
        end_trade_time = datetime.strptime("15:20", "%H:%M").time()
        market_shutdown_time = datetime.strptime("15:40", "%H:%M").time()
        
        can_take_trades = (start_trade_time <= now.time() < end_trade_time)
        is_market_closing = (now.time() >= end_trade_time)

        # 03:40 PM Clean Market Shutdown
        if now.time() >= market_shutdown_time:
            summary = (
                f"MARKET CLOSED (DAILY REPORT)\n"
                f"Date: {now.strftime('%d-%b-%Y')}\n"
                f"• Total Signals Generated: {trade_stats['total_signals']}\n"
                f"• Target Hits: {trade_stats['target_hits']}\n"
                f"• Stop Loss Hits: {trade_stats['sl_hits']}\n\n"
                f"Scanner shutting down cleanly. See you tomorrow at 09:00 AM IST!"
            )
            send_telegram_alert(summary)
            print(summary)
            break

        raw_data = get_live_index_data()

        if raw_data is not None and not raw_data.empty:
            prices_dict = {}
            for index_name in INDEX_WATCHLIST:
                row = raw_data[raw_data['index'] == index_name]
                if not row.empty:
                    current_price = float(str(row['last'].values[0]).replace(',', ''))
                    prices_dict[index_name] = current_price
                    
                    # 1. MONITOR ACTIVE TRADES
                    for strat in STRATEGIES:
                        trade = active_trades[index_name].get(strat)
                        if trade is not None:
                            if is_market_closing:
                                pnl = current_price - trade['entry'] if trade['type'] == 'BUY' else trade['entry'] - current_price
                                alert = (
                                    f"AUTO EXIT (03:20 PM CLOSED)!\n"
                                    f"Strategy: {strat}\n"
                                    f"Index: {index_name}\n"
                                    f"Exit Price: {current_price:.2f}\n"
                                    f"Points: {pnl:+.2f}\n"
                                    f"Position Cleared for the Day."
                                )
                                send_telegram_alert(alert)
                                active_trades[index_name][strat] = None
                                save_trades(active_trades)
                                continue

                            if trade['type'] == 'BUY':
                                if not trade.get('t1_hit') and current_price >= trade['t1']:
                                    trade['t1_hit'] = True
                                    trade_stats['target_hits'] += 1
                                    send_telegram_alert(f"TARGET 1 HIT (1:1.5)!\nStrategy: {strat}\nIndex: {index_name}\nPrice: {current_price:.2f}\nT1: {trade['t1']:.2f}")
                                    save_trades(active_trades)

                                if not trade.get('t2_hit') and current_price >= trade['t2']:
                                    trade['t2_hit'] = True
                                    trade_stats['target_hits'] += 1
                                    send_telegram_alert(f"TARGET 2 HIT (1:2.0)!\nStrategy: {strat}\nIndex: {index_name}\nPrice: {current_price:.2f}\nT2: {trade['t2']:.2f}")
                                    save_trades(active_trades)

                                if current_price >= trade['t3']:
                                    trade_stats['target_hits'] += 1
                                    send_telegram_alert(f"ALL TARGETS HIT (T3)!\nStrategy: {strat}\nIndex: {index_name}\nExit Price: {current_price:.2f}\nT3: {trade['t3']:.2f}")
                                    active_trades[index_name][strat] = None
                                    save_trades(active_trades)

                                elif current_price <= trade['sl']:
                                    trade_stats['sl_hits'] += 1
                                    send_telegram_alert(f"STOP LOSS HIT!\nStrategy: {strat}\nIndex: {index_name}\nPrice: {current_price:.2f}\nSL: {trade['sl']:.2f}")
                                    active_trades[index_name][strat] = None
                                    save_trades(active_trades)

                            elif trade['type'] == 'SELL':
                                if not trade.get('t1_hit') and current_price <= trade['t1']:
                                    trade['t1_hit'] = True
                                    trade_stats['target_hits'] += 1
                                    send_telegram_alert(f"TARGET 1 HIT (1:1.5)!\nStrategy: {strat}\nIndex: {index_name}\nPrice: {current_price:.2f}\nT1: {trade['t1']:.2f}")
                                    save_trades(active_trades)

                                if not trade.get('t2_hit') and current_price <= trade['t2']:
                                    trade['t2_hit'] = True
                                    trade_stats['target_hits'] += 1
                                    send_telegram_alert(f"TARGET 2 HIT (1:2.0)!\nStrategy: {strat}\nIndex: {index_name}\nPrice: {current_price:.2f}\nT2: {trade['t2']:.2f}")
                                    save_trades(active_trades)

                                if current_price <= trade['t3']:
                                    trade_stats['target_hits'] += 1
                                    send_telegram_alert(f"ALL TARGETS HIT (T3)!\nStrategy: {strat}\nIndex: {index_name}\nExit Price: {current_price:.2f}\nT3: {trade['t3']:.2f}")
                                    active_trades[index_name][strat] = None
                                    save_trades(active_trades)

                                elif current_price >= trade['sl']:
                                    trade_stats['sl_hits'] += 1
                                    send_telegram_alert(f"STOP LOSS HIT!\nStrategy: {strat}\nIndex: {index_name}\nPrice: {current_price:.2f}\nSL: {trade['sl']:.2f}")
                                    active_trades[index_name][strat] = None
                                    save_trades(active_trades)

                    # 2. CANDLE AGGREGATION
                    c_bucket = current_candles[index_name]
                    current_min_slot = (now.minute // 5) * 5

                    if c_bucket["start_min"] is None or c_bucket["start_min"] != current_min_slot:
                        if c_bucket["start_min"] is not None and c_bucket["open"] is not None:
                            candle_history[index_name].append({
                                'Open': c_bucket["open"],
                                'High': c_bucket["high"],
                                'Low': c_bucket["low"],
                                'Close': c_bucket["close"]
                            })
                            if len(candle_history[index_name]) > 120:
                                candle_history[index_name].pop(0)

                        c_bucket["open"] = current_price
                        c_bucket["high"] = current_price
                        c_bucket["low"] = current_price
                        c_bucket["close"] = current_price
                        c_bucket["start_min"] = current_min_slot
                    else:
                        c_bucket["high"] = max(c_bucket["high"], current_price)
                        c_bucket["low"] = min(c_bucket["low"], current_price)
                        c_bucket["close"] = current_price

                    # 3. STRATEGY CHECKS
                    df = pd.DataFrame(candle_history[index_name])
                    if len(df) >= 30:
                        df = calculate_indicators(df)
                        latest, prev = df.iloc[-1], df.iloc[-2]
                        close, prev_close, current_atr = latest['Close'], prev['Close'], latest['ATR']

                        print(f"[{current_time_str} IST] {index_name:10} | Close: {close:8.2f} | KC-Up: {latest['KC_Upper']:8.2f} | Cloud-Top: {latest['Cloud_Top']:8.2f} | ATR: {current_atr:5.2f}")

                        if can_take_trades:
                            dynamic_risk = round(max(current_atr * 1.5, 20.0), 2)

                            # Strategy 1: Keltner
                            if active_trades[index_name]["KELTNER"] is None:
                                if prev_close <= prev['KC_Upper'] and close > latest['KC_Upper']:
                                    if last_signals[index_name]["KELTNER"] != "BUY":
                                        last_signals[index_name]["KELTNER"] = "BUY"
                                        trade_stats['total_signals'] += 1
                                        sl = round(close - dynamic_risk, 2)
                                        t1 = round(close + (dynamic_risk * 1.5), 2)
                                        t2 = round(close + (dynamic_risk * 2.0), 2)
                                        t3 = round(close + (dynamic_risk * 3.0), 2)
                                        active_trades[index_name]["KELTNER"] = {'type': 'BUY', 'entry': close, 'sl': sl, 't1': t1, 't2': t2, 't3': t3, 't1_hit': False, 't2_hit': False}
                                        save_trades(active_trades)
                                        send_telegram_alert(f"NEW SIGNAL: KELTNER BREAKOUT\nIndex: {index_name} (BUY / CALL)\nTime: {current_time_str} IST\nEntry: {close:.2f} | SL: {sl:.2f}\nT1: {t1:.2f} | T2: {t2:.2f} | T3: {t3:.2f}")

                                elif prev_close >= prev['KC_Lower'] and close < latest['KC_Lower']:
                                    if last_signals[index_name]["KELTNER"] != "SELL":
                                        last_signals[index_name]["KELTNER"] = "SELL"
                                        trade_stats['total_signals'] += 1
                                        sl = round(close + dynamic_risk, 2)
                                        t1 = round(close - (dynamic_risk * 1.5), 2)
                                        t2 = round(close - (dynamic_risk * 2.0), 2)
                                        t3 = round(close - (dynamic_risk * 3.0), 2)
                                        active_trades[index_name]["KELTNER"] = {'type': 'SELL', 'entry': close, 'sl': sl, 't1': t1, 't2': t2, 't3': t3, 't1_hit': False, 't2_hit': False}
                                        save_trades(active_trades)
                                        send_telegram_alert(f"NEW SIGNAL: KELTNER BREAKOUT\nIndex: {index_name} (SELL / PUT)\nTime: {current_time_str} IST\nEntry: {close:.2f} | SL: {sl:.2f}\nT1: {t1:.2f} | T2: {t2:.2f} | T3: {t3:.2f}")

                            # Strategy 2: Ichimoku
                            if active_trades[index_name]["ICHIMOKU"] is None:
                                if prev_close <= prev['Cloud_Top'] and close > latest['Cloud_Top']:
                                    if last_signals[index_name]["ICHIMOKU"] != "BUY":
                                        last_signals[index_name]["ICHIMOKU"] = "BUY"
                                        trade_stats['total_signals'] += 1
                                        sl = round(close - dynamic_risk, 2)
                                        t1 = round(close + (dynamic_risk * 1.5), 2)
                                        t2 = round(close + (dynamic_risk * 2.0), 2)
                                        t3 = round(close + (dynamic_risk * 3.0), 2)
                                        active_trades[index_name]["ICHIMOKU"] = {'type': 'BUY', 'entry': close, 'sl': sl, 't1': t1, 't2': t2, 't3': t3, 't1_hit': False, 't2_hit': False}
                                        save_trades(active_trades)
                                        send_telegram_alert(f"NEW SIGNAL: ICHIMOKU CLOUD BREAKOUT\nIndex: {index_name} (BUY / CALL)\nTime: {current_time_str} IST\nEntry: {close:.2f} | SL: {sl:.2f}\nT1: {t1:.2f} | T2: {t2:.2f} | T3: {t3:.2f}")

                                elif prev_close >= prev['Cloud_Bottom'] and close < latest['Cloud_Bottom']:
                                    if last_signals[index_name]["ICHIMOKU"] != "SELL":
                                        last_signals[index_name]["ICHIMOKU"] = "SELL"
                                        trade_stats['total_signals'] += 1
                                        sl = round(close + dynamic_risk, 2)
                                        t1 = round(close - (dynamic_risk * 1.5), 2)
                                        t2 = round(close - (dynamic_risk * 2.0), 2)
                                        t3 = round(close - (dynamic_risk * 3.0), 2)
                                        active_trades[index_name]["ICHIMOKU"] = {'type': 'SELL', 'entry': close, 'sl': sl, 't1': t1, 't2': t2, 't3': t3, 't1_hit': False, 't2_hit': False}
                                        save_trades(active_trades)
                                        send_telegram_alert(f"NEW SIGNAL: ICHIMOKU CLOUD BREAKOUT\nIndex: {index_name} (SELL / PUT)\nTime: {current_time_str} IST\nEntry: {close:.2f} | SL: {sl:.2f}\nT1: {t1:.2f} | T2: {t2:.2f} | T3: {t3:.2f}")
                    else:
                        print(f"[{current_time_str} IST] Building 5-min candles for {index_name}: {len(df)}/30...")

            # 4. HOURLY HEARTBEAT CHECK
            if now.minute == 0 and now.hour != last_heartbeat_hour and (9 <= now.hour <= 15):
                last_heartbeat_hour = now.hour
                hb_msg = f"STATUS: Scanner Active & Healthy!\nTime: {current_time_str} IST\n"
                for idx, prc in prices_dict.items():
                    hb_msg += f"• {idx}: {prc:.2f}\n"
                send_telegram_alert(hb_msg)

        time.sleep(15)
    except Exception as e:
        print(f"Scanner Loop Error: {e}")
        time.sleep(10)
