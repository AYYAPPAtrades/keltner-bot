import pandas as pd
import numpy as np
import time
import requests
import json
import os
from datetime import datetime
from nselib import capital_market

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

send_telegram_alert("🚀 DUAL SCANNER ACTIVATED (SEPARATE ALERTS)!\n• Strategy 1: Keltner Channel Breakout\n• Strategy 2: Ichimoku Cloud Breakout\n• Trading Window: 09:30 AM - 03:20 PM\n• T1 (1:1.5) | T2 (1:2.0) | T3 (1:3.0)")

print("======================================================")
print("   SEPARATE KELTNER & ICHIMOKU SCANNER (T1, T2, T3)   ")
print("======================================================\n")

INDEX_WATCHLIST = ["NIFTY 50", "NIFTY BANK"]
STRATEGIES = ["KELTNER", "ICHIMOKU"]
TRADE_FILE = "active_trades.json"
CANDLE_BACKUP_FILE = "candle_history.json"

# --- PERSISTENCE ---
def load_trades():
    default_structure = {
        idx: {"KELTNER": None, "ICHIMOKU": None} for idx in INDEX_WATCHLIST
    }
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

def load_candle_history():
    if os.path.exists(CANDLE_BACKUP_FILE):
        try:
            with open(CANDLE_BACKUP_FILE, 'r') as f:
                data = json.load(f)
                print(">>> Candle history restored from backup successfully!")
                return data
        except Exception as e:
            print(f"Failed to load candle backup: {e}")
    return {idx: [] for idx in INDEX_WATCHLIST}

def save_candle_history(history):
    try:
        with open(CANDLE_BACKUP_FILE, 'w') as f:
            json.dump(history, f, indent=4)
    except Exception as e:
        print(f"Failed to save candle backup: {e}")

active_trades = load_trades()
candle_history = load_candle_history()

current_candles = {
    idx: {"open": None, "high": -1, "low": 9999999, "close": None, "start_min": None}
    for idx in INDEX_WATCHLIST
}

last_signals = {
    idx: {"KELTNER": None, "ICHIMOKU": None} for idx in INDEX_WATCHLIST
}

def calculate_indicators(df):
    high = df['High']
    low = df['Low']
    close = df['Close']
    
    # 1. ATR (10 Period)
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.ewm(span=10, adjust=False).mean()
    df['ATR'] = atr
    
    # 2. Keltner Channel (20 EMA, Multiplier 1.5)
    df['KC_Middle'] = close.ewm(span=20, adjust=False).mean()
    df['KC_Upper'] = df['KC_Middle'] + (1.5 * atr)
    df['KC_Lower'] = df['KC_Middle'] - (1.5 * atr)
    
    # 3. Ichimoku Cloud (9, 26, 52)
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
        now = datetime.now()
        current_time_str = now.strftime('%H:%M:%S')
        start_trade_time = datetime.strptime("09:30", "%H:%M").time()
        end_trade_time = datetime.strptime("15:20", "%H:%M").time()
        
        can_take_trades = (start_trade_time <= now.time() < end_trade_time)
        is_market_closing = (now.time() >= end_trade_time)

        raw_data = get_live_index_data()

        if raw_data is not None and not raw_data.empty:
            for index_name in INDEX_WATCHLIST:
                row = raw_data[raw_data['index'] == index_name]
                if not row.empty:
                    current_price = float(str(row['last'].values[0]).replace(',', ''))
                    
                    # 1. MONITOR ACTIVE TRADES
                    for strat in STRATEGIES:
                        trade = active_trades[index_name].get(strat)
                        if trade is not None:
                            # 03:20 PM Auto Exit
                            if is_market_closing:
                                pnl = current_price - trade['entry'] if trade['type'] == 'BUY' else trade['entry'] - current_price
                                alert = (
                                    f"⏰ AUTO EXIT (03:20 PM CLOSED)!\n"
                                    f"Strategy: {strat}\n"
                                    f"Index: {index_name}\n"
                                    f"Type: {trade['type']}\n"
                                    f"Exit Price: {current_price:.2f}\n"
                                    f"Points: {pnl:+.2f}\n"
                                    f"Position Cleared for the Day."
                                )
                                print("\n" + alert + "\n")
                                send_telegram_alert(alert)
                                active_trades[index_name][strat] = None
                                save_trades(active_trades)
                                continue

                            # BUY MONITORING
                            if trade['type'] == 'BUY':
                                if not trade.get('t1_hit') and current_price >= trade['t1']:
                                    trade['t1_hit'] = True
                                    alert = f"🎯 TARGET 1 HIT (1:1.5)!\nStrategy: {strat}\nIndex: {index_name}\nPrice: {current_price:.2f}\nT1: {trade['t1']:.2f}"
                                    print("\n" + alert + "\n")
                                    send_telegram_alert(alert)
                                    save_trades(active_trades)

                                if not trade.get('t2_hit') and current_price >= trade['t2']:
                                    trade['t2_hit'] = True
                                    alert = f"🎯 TARGET 2 HIT (1:2.0)!\nStrategy: {strat}\nIndex: {index_name}\nPrice: {current_price:.2f}\nT2: {trade['t2']:.2f}"
                                    print("\n" + alert + "\n")
                                    send_telegram_alert(alert)
                                    save_trades(active_trades)

                                if current_price >= trade['t3']:
                                    alert = f"🏆 TARGET 3 HIT (ALL TARGETS HIT)!\nStrategy: {strat}\nIndex: {index_name}\nExit Price: {current_price:.2f}\nT3: {trade['t3']:.2f}"
                                    print("\n" + alert + "\n")
                                    send_telegram_alert(alert)
                                    active_trades[index_name][strat] = None
                                    save_trades(active_trades)

                                elif current_price <= trade['sl']:
                                    alert = f"🛑 STOP LOSS HIT!\nStrategy: {strat}\nIndex: {index_name}\nPrice: {current_price:.2f}\nSL: {trade['sl']:.2f}"
                                    print("\n" + alert + "\n")
                                    send_telegram_alert(alert)
                                    active_trades[index_name][strat] = None
                                    save_trades(active_trades)

                            # SELL MONITORING
                            elif trade['type'] == 'SELL':
                                if not trade.get('t1_hit') and current_price <= trade['t1']:
                                    trade['t1_hit'] = True
                                    alert = f"🎯 TARGET 1 HIT (1:1.5)!\nStrategy: {strat}\nIndex: {index_name}\nPrice: {current_price:.2f}\nT1: {trade['t1']:.2f}"
                                    print("\n" + alert + "\n")
                                    send_telegram_alert(alert)
                                    save_trades(active_trades)

                                if not trade.get('t2_hit') and current_price <= trade['t2']:
                                    trade['t2_hit'] = True
                                    alert = f"🎯 TARGET 2 HIT (1:2.0)!\nStrategy: {strat}\nIndex: {index_name}\nPrice: {current_price:.2f}\nT2: {trade['t2']:.2f}"
                                    print("\n" + alert + "\n")
                                    send_telegram_alert(alert)
                                    save_trades(active_trades)

                                if current_price <= trade['t3']:
                                    alert = f"🏆 TARGET 3 HIT (ALL TARGETS HIT)!\nStrategy: {strat}\nIndex: {index_name}\nExit Price: {current_price:.2f}\nT3: {trade['t3']:.2f}"
                                    print("\n" + alert + "\n")
                                    send_telegram_alert(alert)
                                    active_trades[index_name][strat] = None
                                    save_trades(active_trades)

                                elif current_price >= trade['sl']:
                                    alert = f"🛑 STOP LOSS HIT!\nStrategy: {strat}\nIndex: {index_name}\nPrice: {current_price:.2f}\nSL: {trade['sl']:.2f}"
                                    print("\n" + alert + "\n")
                                    send_telegram_alert(alert)
                                    active_trades[index_name][strat] = None
                                    save_trades(active_trades)

                    # 2. CANDLE AGGREGATION (5-MINUTE)
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
                            
                            save_candle_history(candle_history)

                        c_bucket["open"] = current_price
                        c_bucket["high"] = current_price
                        c_bucket["low"] = current_price
                        c_bucket["close"] = current_price
                        c_bucket["start_min"] = current_min_slot
                    else:
                        c_bucket["high"] = max(c_bucket["high"], current_price)
                        c_bucket["low"] = min(c_bucket["low"], current_price)
                        c_bucket["close"] = current_price

                    # 3. INDEPENDENT STRATEGY CHECKS
                    df = pd.DataFrame(candle_history[index_name])
                    
                    if len(df) >= 30:
                        df = calculate_indicators(df)

                        latest = df.iloc[-1]
                        prev = df.iloc[-2]

                        close = latest['Close']
                        prev_close = prev['Close']
                        current_atr = latest['ATR']

                        kc_upper = latest['KC_Upper']
                        kc_lower = latest['KC_Lower']
                        prev_kc_upper = prev['KC_Upper']
                        prev_kc_lower = prev['KC_Lower']

                        cloud_top = latest['Cloud_Top']
                        cloud_bottom = latest['Cloud_Bottom']
                        prev_cloud_top = prev['Cloud_Top']
                        prev_cloud_bottom = prev['Cloud_Bottom']

                        print(f"[{current_time_str}] {index_name:10} | Close: {close:8.2f} | KC-Up: {kc_upper:8.2f} | Cloud-Top: {cloud_top:8.2f} | ATR: {current_atr:5.2f}")

                        if can_take_trades:
                            dynamic_risk = round(max(current_atr * 1.5, 20.0), 2)

                            # --- STRATEGY 1: KELTNER BREAKOUT ---
                            if active_trades[index_name]["KELTNER"] is None:
                                if (prev_close <= prev_kc_upper) and (close > kc_upper):
                                    if last_signals[index_name]["KELTNER"] != "BUY":
                                        last_signals[index_name]["KELTNER"] = "BUY"
                                        sl = round(close - dynamic_risk, 2)
                                        t1 = round(close + (dynamic_risk * 1.5), 2)
                                        t2 = round(close + (dynamic_risk * 2.0), 2)
                                        t3 = round(close + (dynamic_risk * 3.0), 2)

                                        active_trades[index_name]["KELTNER"] = {
                                            'type': 'BUY', 'entry': close, 'sl': sl,
                                            't1': t1, 't2': t2, 't3': t3, 't1_hit': False, 't2_hit': False
                                        }
                                        save_trades(active_trades)

                                        alert = (
                                            f"⚡ NEW SIGNAL: KELTNER BREAKOUT\n"
                                            f"Index: {index_name} (BUY / CALL)\n"
                                            f"Time: {current_time_str}\n"
                                            f"Entry: {close:.2f} | SL: {sl:.2f}\n"
                                            f"T1: {t1:.2f} | T2: {t2:.2f} | T3: {t3:.2f}"
                                        )
                                        print("\n" + alert + "\n")
                                        send_telegram_alert(alert)

                                elif (prev_close >= prev_kc_lower) and (close < kc_lower):
                                    if last_signals[index_name]["KELTNER"] != "SELL":
                                        last_signals[index_name]["KELTNER"] = "SELL"
                                        sl = round(close + dynamic_risk, 2)
                                        t1 = round(close - (dynamic_risk * 1.5), 2)
                                        t2 = round(close - (dynamic_risk * 2.0), 2)
                                        t3 = round(close - (dynamic_risk * 3.0), 2)

                                        active_trades[index_name]["KELTNER"] = {
                                            'type': 'SELL', 'entry': close, 'sl': sl,
                                            't1': t1, 't2': t2, 't3': t3, 't1_hit': False, 't2_hit': False
                                        }
                                        save_trades(active_trades)

                                        alert = (
                                            f"⚡ NEW SIGNAL: KELTNER BREAKOUT\n"
                                            f"Index: {index_name} (SELL / PUT)\n"
                                            f"Time: {current_time_str}\n"
                                            f"Entry: {close:.2f} | SL: {sl:.2f}\n"
                                            f"T1: {t1:.2f} | T2: {t2:.2f} | T3: {t3:.2f}"
                                        )
                                        print("\n" + alert + "\n")
                                        send_telegram_alert(alert)

                            # --- STRATEGY 2: ICHIMOKU CLOUD BREAKOUT ---
                            if active_trades[index_name]["ICHIMOKU"] is None:
                                if (prev_close <= prev_cloud_top) and (close > cloud_top):
                                    if last_signals[index_name]["ICHIMOKU"] != "BUY":
                                        last_signals[index_name]["ICHIMOKU"] = "BUY"
                                        sl = round(close - dynamic_risk, 2)
                                        t1 = round(close + (dynamic_risk * 1.5), 2)
                                        t2 = round(close + (dynamic_risk * 2.0), 2)
                                        t3 = round(close + (dynamic_risk * 3.0), 2)

                                        active_trades[index_name]["ICHIMOKU"] = {
                                            'type': 'BUY', 'entry': close, 'sl': sl,
                                            't1': t1, 't2': t2, 't3': t3, 't1_hit': False, 't2_hit': False
                                        }
                                        save_trades(active_trades)

                                        alert = (
                                            f"☁️ NEW SIGNAL: ICHIMOKU CLOUD BREAKOUT\n"
                                            f"Index: {index_name} (BUY / CALL)\n"
                                            f"Time: {current_time_str}\n"
                                            f"Entry: {close:.2f} | SL: {sl:.2f}\n"
                                            f"T1: {t1:.2f} | T2: {t2:.2f} | T3: {t3:.2f}"
                                        )
                                        print("\n" + alert + "\n")
                                        send_telegram_alert(alert)

                                elif (prev_close >= prev_cloud_bottom) and (close < cloud_bottom):
                                    if last_signals[index_name]["ICHIMOKU"] != "SELL":
                                        last_signals[index_name]["ICHIMOKU"] = "SELL"
                                        sl = round(close + dynamic_risk, 2)
                                        t1 = round(close - (dynamic_risk * 1.5), 2)
                                        t2 = round(close - (dynamic_risk * 2.0), 2)
                                        t3 = round(close - (dynamic_risk * 3.0), 2)

                                        active_trades[index_name]["ICHIMOKU"] = {
                                            'type': 'SELL', 'entry': close, 'sl': sl,
                                            't1': t1, 't2': t2, 't3': t3, 't1_hit': False, 't2_hit': False
                                        }
                                        save_trades(active_trades)

                                        alert = (
                                            f"☁️ NEW SIGNAL: ICHIMOKU CLOUD BREAKOUT\n"
                                            f"Index: {index_name} (SELL / PUT)\n"
                                            f"Time: {current_time_str}\n"
                                            f"Entry: {close:.2f} | SL: {sl:.2f}\n"
                                            f"T1: {t1:.2f} | T2: {t2:.2f} | T3: {t3:.2f}"
                                        )
                                        print("\n" + alert + "\n")
                                        send_telegram_alert(alert)
                    else:
                        print(f"[{current_time_str}] Building 5-min candles for {index_name}: {len(df)}/30...")

        print("-" * 65)
        time.sleep(15)
    except Exception as e:
        print(f"Scanner Loop Error: {e}")
        time.sleep(10)
