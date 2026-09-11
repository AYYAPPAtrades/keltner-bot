import os
import time
import requests
import json
from datetime import datetime
from zoneinfo import ZoneInfo
import pandas as pd
import numpy as np
import yfinance as yf
from nselib import capital_market

# --- TIMEZONE CONFIGURATION ---
IST = ZoneInfo("Asia/Kolkata")

# --- TELEGRAM CONFIGURATION (DUAL CHANNELS) ---
TELEGRAM_BOT_TOKEN = "8941192045:AAEBwZ8O4Q7-K-ktSx7kAewUy4QIXsLWEhs"
TELEGRAM_CHAT_IDS = ["8996427731", "6789591588"]

def send_telegram_alert(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    for chat_id in TELEGRAM_CHAT_IDS:
        try:
            payload = {"chat_id": chat_id, "text": msg, "parse_mode": "Markdown"}
            requests.post(url, data=payload, timeout=8)
        except Exception as e:
            print(f"Telegram Delivery Error ({chat_id}): {e}")

# --- MARKET HOLIDAY CHECK ---
try:
    holidays_df = capital_market.holiday_trading()
    today_str = datetime.now(IST).strftime('%d-%b-%Y')
    if holidays_df is not None and not holidays_df.empty:
        if 'tradingDate' in holidays_df.columns and today_str in holidays_df['tradingDate'].values:
            reason = holidays_df[holidays_df['tradingDate'] == today_str]['description'].values[0]
            send_telegram_alert(f"🏖️ *MARKET HOLIDAY TODAY!*\nReason: {reason}\nScanner will not run today.")
            exit(0)
except Exception as e:
    print(f"Holiday check skipped: {e}")

INDEX_WATCHLIST = ["NIFTY 50", "NIFTY BANK"]
YF_TICKERS = {"NIFTY 50": "^NSEI", "NIFTY BANK": "^NSEBANK"}
TRADE_FILE = "active_trades_dual.json"

trade_stats = {"total_signals": 0, "target_hits": 0, "sl_hits": 0}
prev_close_dict = {}
last_heartbeat_hour = -1

# --- TRADE PERSISTENCE ---
def load_trades():
    default_data = {idx: None for idx in INDEX_WATCHLIST}
    if os.path.exists(TRADE_FILE):
        try:
            with open(TRADE_FILE, 'r') as f:
                data = json.load(f)
                for idx in INDEX_WATCHLIST:
                    if idx not in data:
                        data[idx] = None
                return data
        except Exception:
            pass
    return default_data

def save_trades(trades):
    with open(TRADE_FILE, 'w') as f:
        json.dump(trades, f, indent=4)

# --- HISTORICAL DATA PRE-LOAD (5M & 15M) ---
def get_historical_candles(index_name, interval, limit=80):
    try:
        ticker = YF_TICKERS.get(index_name)
        df_hist = yf.download(ticker, period="5d", interval=interval, progress=False)
        if not df_hist.empty:
            if isinstance(df_hist.columns, pd.MultiIndex):
                df_hist.columns = df_hist.columns.get_level_values(0)
            candles = []
            for _, row in df_hist.tail(limit).iterrows():
                candles.append({
                    'Open': float(row['Open']),
                    'High': float(row['High']),
                    'Low': float(row['Low']),
                    'Close': float(row['Close'])
                })
            return candles
    except Exception as e:
        print(f"History Fetch Error ({index_name}, {interval}): {e}")
    return []

# Separate history for 5m (Keltner) and 15m (Ichimoku)
history_5m = {idx: get_historical_candles(idx, "5m", 80) for idx in INDEX_WATCHLIST}
history_15m = {idx: get_historical_candles(idx, "15m", 80) for idx in INDEX_WATCHLIST}

current_candles_5m = {idx: {"open": None, "high": -1, "low": 9999999, "close": None, "slot": None} for idx in INDEX_WATCHLIST}
current_candles_15m = {idx: {"open": None, "high": -1, "low": 9999999, "close": None, "slot": None} for idx in INDEX_WATCHLIST}

active_trades = load_trades()

send_telegram_alert(
    "🚀 *NIFTY & BANK NIFTY SCANNER ACTIVATED*\n\n"
    "• *Strategies:* MOMENTUM SPIKE (5m) & TREND MASTER (15m)\n"
    "• *Target Tracking:* T1, T2, T3 Active\n"
    "• *Strict SL Exit:* Closes immediately upon hitting SL\n"
    "• *First-Come, First-Served:* Active trade blocks overlapping signals"
)

# --- INDICATOR CALCULATIONS ---
def calc_keltner(df):
    close = df['Close']
    high = df['High']
    low = df['Low']
    tr = pd.concat([high - low, (high - close.shift(1)).abs(), (low - close.shift(1)).abs()], axis=1).max(axis=1)
    df['ATR'] = tr.rolling(window=14).mean()
    df['KC_Middle'] = close.ewm(span=20, adjust=False).mean()
    df['KC_Upper'] = df['KC_Middle'] + (1.5 * df['ATR'])
    df['KC_Lower'] = df['KC_Middle'] - (1.5 * df['ATR'])
    return df

def calc_ichimoku(df):
    high = df['High']
    low = df['Low']
    close = df['Close']
    tr = pd.concat([high - low, (high - close.shift(1)).abs(), (low - close.shift(1)).abs()], axis=1).max(axis=1)
    df['ATR'] = tr.rolling(window=14).mean()

    tenkan = (high.rolling(window=9).max() + low.rolling(window=9).min()) / 2
    kijun = (high.rolling(window=26).max() + low.rolling(window=26).min()) / 2
    senkou_span_a = ((tenkan + kijun) / 2).shift(26)
    senkou_span_b = ((high.rolling(window=52).max() + low.rolling(window=52).min()) / 2).shift(26)

    df['Cloud_Top'] = pd.concat([senkou_span_a, senkou_span_b], axis=1).max(axis=1)
    df['Cloud_Bottom'] = pd.concat([senkou_span_a, senkou_span_b], axis=1).min(axis=1)
    return df

def get_live_index_data():
    try:
        return capital_market.market_watch_all_indices()
    except Exception as e:
        print(f"NSE Fetch Error: {e}")
        return None

# --- MAIN EXECUTION ENGINE ---
while True:
    try:
        now = datetime.now(IST)
        current_time = now.time()
        current_time_str = now.strftime('%H:%M:%S')

        start_trade_time = datetime.strptime("09:30", "%H:%M").time()
        end_trade_time = datetime.strptime("15:20", "%H:%M").time()
        shutdown_time = datetime.strptime("15:40", "%H:%M").time()

        can_take_trades = (start_trade_time <= current_time < end_trade_time)
        is_market_closing = (current_time >= end_trade_time)

        # 03:40 PM Daily Report & Shutdown
        if current_time >= shutdown_time:
            summary = (
                f"📊 *MARKET CLOSED (DAILY REPORT)*\n"
                f"Date: {now.strftime('%d-%b-%Y')}\n\n"
                f"• Total Signals: {trade_stats['total_signals']}\n"
                f"• Targets Achieved: {trade_stats['target_hits']}\n"
                f"• Stop Losses Hit: {trade_stats['sl_hits']}\n\n"
                f"Bot safely shut down. Resumes tomorrow at 09:00 AM IST!"
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

                    if index_name not in prev_close_dict and 'previousClose' in row.columns:
                        prev_close_dict[index_name] = float(str(row['previousClose'].values[0]).replace(',', ''))

                    # 1. TRADE MANAGEMENT (T1, T2, T3 & STRICT SL EXIT)
                    trade = active_trades[index_name]
                    if trade is not None:
                        # 03:20 PM Auto-Exit
                        if is_market_closing:
                            pnl = current_price - trade['entry'] if trade['type'] == 'BUY' else trade['entry'] - current_price
                            send_telegram_alert(
                                f"⏰ *AUTO EXIT (03:20 PM CLOSE)*\n\n"
                                f"Strategy: {trade['strategy']}\n"
                                f"Index: *{index_name}*\n"
                                f"Exit Price: {current_price:.2f} | PnL: {pnl:+.2f}\n"
                                f"Status: Position Cleared."
                            )
                            active_trades[index_name] = None
                            save_trades(active_trades)
                            continue

                        # BUY MANAGEMENT
                        if trade['type'] == 'BUY':
                            if current_price <= trade['sl']:
                                trade_stats['sl_hits'] += 1
                                send_telegram_alert(
                                    f"❌ *STOP LOSS HIT!*\n\n"
                                    f"Strategy: {trade['strategy']}\n"
                                    f"Index: *{index_name}* (BUY)\n"
                                    f"Exit Price: {current_price:.2f} | SL: {trade['sl']:.2f}\n"
                                    f"Status: Trade Closed. Signal ended."
                                )
                                active_trades[index_name] = None
                                save_trades(active_trades)
                                continue

                            if not trade.get('t1_hit') and current_price >= trade['t1']:
                                trade['t1_hit'] = True
                                trade_stats['target_hits'] += 1
                                send_telegram_alert(
                                    f"🎯 *TARGET 1 ACHIEVED!*\n\n"
                                    f"Strategy: {trade['strategy']}\n"
                                    f"Index: *{index_name}* (BUY)\n"
                                    f"Current Price: {current_price:.2f} | T1: {trade['t1']:.2f}\n"
                                    f"Status: Book partial profit!"
                                )
                                save_trades(active_trades)

                            if trade.get('t1_hit') and not trade.get('t2_hit') and current_price >= trade['t2']:
                                trade['t2_hit'] = True
                                trade_stats['target_hits'] += 1
                                send_telegram_alert(
                                    f"🎯🎯 *TARGET 2 ACHIEVED!*\n\n"
                                    f"Strategy: {trade['strategy']}\n"
                                    f"Index: *{index_name}* (BUY)\n"
                                    f"Current Price: {current_price:.2f} | T2: {trade['t2']:.2f}\n"
                                    f"Status: Move Stop Loss to Entry (Trail SL)!"
                                )
                                save_trades(active_trades)

                            if trade.get('t2_hit') and current_price >= trade['t3']:
                                trade_stats['target_hits'] += 1
                                send_telegram_alert(
                                    f"🎯🎯🎯 *FINAL TARGET 3 HIT!*\n\n"
                                    f"Strategy: {trade['strategy']}\n"
                                    f"Index: *{index_name}* (BUY)\n"
                                    f"Exit Price: {current_price:.2f} | T3: {trade['t3']:.2f}\n"
                                    f"Status: Full profits booked. Trade Closed!"
                                )
                                active_trades[index_name] = None
                                save_trades(active_trades)
                                continue

                        # SELL MANAGEMENT
                        elif trade['type'] == 'SELL':
                            if current_price >= trade['sl']:
                                trade_stats['sl_hits'] += 1
                                send_telegram_alert(
                                    f"❌ *STOP LOSS HIT!*\n\n"
                                    f"Strategy: {trade['strategy']}\n"
                                    f"Index: *{index_name}* (SELL)\n"
                                    f"Exit Price: {current_price:.2f} | SL: {trade['sl']:.2f}\n"
                                    f"Status: Trade Closed. Signal ended."
                                )
                                active_trades[index_name] = None
                                save_trades(active_trades)
                                continue

                            if not trade.get('t1_hit') and current_price <= trade['t1']:
                                trade['t1_hit'] = True
                                trade_stats['target_hits'] += 1
                                send_telegram_alert(
                                    f"🎯 *TARGET 1 ACHIEVED!*\n\n"
                                    f"Strategy: {trade['strategy']}\n"
                                    f"Index: *{index_name}* (SELL)\n"
                                    f"Current Price: {current_price:.2f} | T1: {trade['t1']:.2f}\n"
                                    f"Status: Book partial profit!"
                                )
                                save_trades(active_trades)

                            if trade.get('t1_hit') and not trade.get('t2_hit') and current_price <= trade['t2']:
                                trade['t2_hit'] = True
                                trade_stats['target_hits'] += 1
                                send_telegram_alert(
                                    f"🎯🎯 *TARGET 2 ACHIEVED!*\n\n"
                                    f"Strategy: {trade['strategy']}\n"
                                    f"Index: *{index_name}* (SELL)\n"
                                    f"Current Price: {current_price:.2f} | T2: {trade['t2']:.2f}\n"
                                    f"Status: Move Stop Loss to Entry (Trail SL)!"
                                )
                                save_trades(active_trades)

                            if trade.get('t2_hit') and current_price <= trade['t3']:
                                trade_stats['target_hits'] += 1
                                send_telegram_alert(
                                    f"🎯🎯🎯 *FINAL TARGET 3 HIT!*\n\n"
                                    f"Strategy: {trade['strategy']}\n"
                                    f"Index: *{index_name}* (SELL)\n"
                                    f"Exit Price: {current_price:.2f} | T3: {trade['t3']:.2f}\n"
                                    f"Status: Full profits booked. Trade Closed!"
                                )
                                active_trades[index_name] = None
                                save_trades(active_trades)
                                continue

                    # 2. CANDLE CONSTRUCTION (5-MIN FOR KELTNER & 15-MIN FOR ICHIMOKU)
                    slot_5m = (now.minute // 5) * 5
                    b5 = current_candles_5m[index_name]
                    if b5["slot"] is None or b5["slot"] != slot_5m:
                        if b5["slot"] is not None and b5["open"] is not None:
                            history_5m[index_name].append({'Open': b5["open"], 'High': b5["high"], 'Low': b5["low"], 'Close': b5["close"]})
                            if len(history_5m[index_name]) > 120: history_5m[index_name].pop(0)
                        b5["open"] = b5["high"] = b5["low"] = b5["close"] = current_price
                        b5["slot"] = slot_5m
                    else:
                        b5["high"] = max(b5["high"], current_price)
                        b5["low"] = min(b5["low"], current_price)
                        b5["close"] = current_price

                    slot_15m = (now.minute // 15) * 15
                    b15 = current_candles_15m[index_name]
                    if b15["slot"] is None or b15["slot"] != slot_15m:
                        if b15["slot"] is not None and b15["open"] is not None:
                            history_15m[index_name].append({'Open': b15["open"], 'High': b15["high"], 'Low': b15["low"], 'Close': b15["close"]})
                            if len(history_15m[index_name]) > 120: history_15m[index_name].pop(0)
                        b15["open"] = b15["high"] = b15["low"] = b15["close"] = current_price
                        b15["slot"] = slot_15m
                    else:
                        b15["high"] = max(b15["high"], current_price)
                        b15["low"] = min(b15["low"], current_price)
                        b15["close"] = current_price

                    # 3. SIGNAL GENERATION (FIRST-COME, FIRST-SERVED)
                    if can_take_trades and active_trades[index_name] is None:
                        triggered_strategy = None
                        signal_direction = None
                        trigger_close = 0.0
                        dynamic_risk = 25.0

                        # Check 1: MOMENTUM SPIKE (Keltner on 5m)
                        df5 = pd.DataFrame(history_5m[index_name])
                        if len(df5) >= 30:
                            df5 = calc_keltner(df5)
                            c5 = df5.iloc[-1]
                            p5 = df5.iloc[-2]
                            atr5 = c5['ATR'] if not np.isnan(c5['ATR']) else 25.0

                            if p5['Close'] <= p5['KC_Upper'] and c5['Close'] > c5['KC_Upper']:
                                triggered_strategy = "MOMENTUM SPIKE"
                                signal_direction = "BUY"
                                trigger_close = c5['Close']
                                dynamic_risk = round(max(atr5 * 1.5, 20.0), 2)
                            elif p5['Close'] >= p5['KC_Lower'] and c5['Close'] < c5['KC_Lower']:
                                triggered_strategy = "MOMENTUM SPIKE"
                                signal_direction = "SELL"
                                trigger_close = c5['Close']
                                dynamic_risk = round(max(atr5 * 1.5, 20.0), 2)

                        # Check 2: TREND MASTER (Ichimoku on 15m - Checked only if Keltner didn't fire)
                        if not triggered_strategy:
                            df15 = pd.DataFrame(history_15m[index_name])
                            if len(df15) >= 35:
                                df15 = calc_ichimoku(df15)
                                c15 = df15.iloc[-1]
                                p15 = df15.iloc[-2]
                                atr15 = c15['ATR'] if not np.isnan(c15['ATR']) else 30.0

                                if not np.isnan(c15['Cloud_Top']):
                                    if p15['Close'] <= p15['Cloud_Top'] and c15['Close'] > c15['Cloud_Top']:
                                        triggered_strategy = "TREND MASTER"
                                        signal_direction = "BUY"
                                        trigger_close = c15['Close']
                                        dynamic_risk = round(max(atr15 * 1.5, 25.0), 2)
                                    elif p15['Close'] >= p15['Cloud_Bottom'] and c15['Close'] < c15['Cloud_Bottom']:
                                        triggered_strategy = "TREND MASTER"
                                        signal_direction = "SELL"
                                        trigger_close = c15['Close']
                                        dynamic_risk = round(max(atr15 * 1.5, 25.0), 2)

                        # Execute Signal
                        if triggered_strategy:
                            if signal_direction == "BUY":
                                sl = round(trigger_close - dynamic_risk, 2)
                                t1 = round(trigger_close + (dynamic_risk * 1.5), 2)
                                t2 = round(trigger_close + (dynamic_risk * 2.0), 2)
                                t3 = round(trigger_close + (dynamic_risk * 3.0), 2)

                                active_trades[index_name] = {
                                    'strategy': triggered_strategy,
                                    'type': 'BUY',
                                    'entry': trigger_close,
                                    'sl': sl,
                                    't1': t1,
                                    't2': t2,
                                    't3': t3,
                                    't1_hit': False,
                                    't2_hit': False
                                }
                                save_trades(active_trades)
                                trade_stats['total_signals'] += 1

                                msg = (
                                    f"🟢 *{index_name} BUY SIGNAL*\n\n"
                                    f"⚡ Strategy: {triggered_strategy}\n"
                                    f"⏰ Time: {current_time_str} IST\n"
                                    f"💵 *Entry:* {trigger_close:.2f}\n"
                                    f"🛑 *Stop Loss:* {sl:.2f}\n\n"
                                    f"🎯 *Target 1:* {t1:.2f}\n"
                                    f"🎯 *Target 2:* {t2:.2f}\n"
                                    f"🎯 *Target 3:* {t3:.2f}"
                                )
                                send_telegram_alert(msg)

                            elif signal_direction == "SELL":
                                sl = round(trigger_close + dynamic_risk, 2)
                                t1 = round(trigger_close - (dynamic_risk * 1.5), 2)
                                t2 = round(trigger_close - (dynamic_risk * 2.0), 2)
                                t3 = round(trigger_close - (dynamic_risk * 3.0), 2)

                                active_trades[index_name] = {
                                    'strategy': triggered_strategy,
                                    'type': 'SELL',
                                    'entry': trigger_close,
                                    'sl': sl,
                                    't1': t1,
                                    't2': t2,
                                    't3': t3,
                                    't1_hit': False,
                                    't2_hit': False
                                }
                                save_trades(active_trades)
                                trade_stats['total_signals'] += 1

                                msg = (
                                    f"🔴 *{index_name} SELL SIGNAL*\n\n"
                                    f"⚡ Strategy: {triggered_strategy}\n"
                                    f"⏰ Time: {current_time_str} IST\n"
                                    f"💵 *Entry:* {trigger_close:.2f}\n"
                                    f"🛑 *Stop Loss:* {sl:.2f}\n\n"
                                    f"🎯 *Target 1:* {t1:.2f}\n"
                                    f"🎯 *Target 2:* {t2:.2f}\n"
                                    f"🎯 *Target 3:* {t3:.2f}"
                                )
                                send_telegram_alert(msg)

            # 4. HOURLY STATUS HEARTBEAT (+/- POINTS & %)
            if now.minute == 0 and now.hour != last_heartbeat_hour and (9 <= now.hour <= 15):
                last_heartbeat_hour = now.hour
                hb_msg = f"💓 *HOURLY STATUS ALERT*\n⏰ Time: {current_time_str} IST\n\n"
                for idx, prc in prices_dict.items():
                    prev_c = prev_close_dict.get(idx, prc)
                    diff = prc - prev_c
                    pct = (diff / prev_c) * 100 if prev_c != 0 else 0.0
                    hb_msg += f"• *{idx}:* {prc:.2f} ({diff:+.2f} | {pct:+.2f}%)\n"
                send_telegram_alert(hb_msg)

        time.sleep(15)

    except Exception as loop_err:
        print(f"Engine Warning: {loop_err}")
        time.sleep(10)
                                              
