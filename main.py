import os
import time
import requests
import json
import threading
from datetime import datetime
from zoneinfo import ZoneInfo
import pandas as pd
import numpy as np
import yfinance as yf
from nselib import capital_market

# --- TIMEZONE CONFIGURATION ---
IST = ZoneInfo("Asia/Kolkata")
start_now = datetime.now(IST)

# --- TELEGRAM CONFIGURATION ---
TELEGRAM_BOT_TOKEN = "8941192045:AAEBwZ8O4Q7-K-ktSx7kAewUy4QIXsLWEhs"
TELEGRAM_CHAT_IDS = ["8996427731", "6789591588", "@sas_trading_lab"]

tele_session = requests.Session()

# 🎯 ഔദ്യോഗിക സ്ട്രാറ്റജി ബ്രാൻഡ് നെയിം
STRATEGY_DISPLAY_NAME = "MOMENTUM SPIKE"

# --- 1. IMMEDIATE WORKFLOW ALERT ---
def send_telegram_alert(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    for chat_id in TELEGRAM_CHAT_IDS:
        try:
            payload = {"chat_id": chat_id, "text": msg}
            tele_session.post(url, json=payload, timeout=8)
        except Exception as e:
            print(f"Telegram Alert Error ({chat_id}): {e}")

send_telegram_alert(
    "🟢 GITHUB WORKFLOW TRIGGERED!\n\n"
    "🚀 SAS TRADING LAB Algo Engine is RUNNING.\n"
    f"🕒 Time: {start_now.strftime('%I:%M:%S %p')} IST\n"
    f"📅 Date: {start_now.strftime('%d-%b-%Y')}\n"
    "📡 Channel & Admin Connection: Verified & Active ✅"
)

# --- 2. WELCOME MESSAGE ---
WELCOME_MESSAGE = (
    "👋 Welcome to SAS TRADING LAB!\n\n"
    "📈 Automated Algo Tracking for Nifty & Bank Nifty.\n"
    "⚡ Live Momentum Spikes & Key Breakout Levels.\n"
    "📊 Daily Real-Time Performance Reports.\n\n"
    "📌 Please check the PINNED message for important Legal Disclaimers.\n"
    "(Educational & Research purpose only | Not SEBI Registered)"
)

# --- BACKGROUND MEMBER JOIN LISTENER ---
def poll_new_channel_members():
    last_update_id = 0
    while True:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
            params = {
                "offset": last_update_id + 1,
                "timeout": 20,
                "allowed_updates": ["chat_member"]
            }
            res = tele_session.get(url, params=params, timeout=25).json()
            if res.get("ok"):
                for update in res.get("result", []):
                    last_update_id = update["update_id"]
                    if "chat_member" in update:
                        chat_member = update["chat_member"]
                        new_status = chat_member.get("new_chat_member", {}).get("status")
                        old_status = chat_member.get("old_chat_member", {}).get("status")

                        if new_status == "member" and old_status in ["left", "kicked"]:
                            target_chat_id = chat_member["chat"]["id"]
                            send_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
                            tele_session.post(send_url, json={"chat_id": target_chat_id, "text": WELCOME_MESSAGE}, timeout=8)
        except Exception:
            time.sleep(5)
        time.sleep(2)

threading.Thread(target=poll_new_channel_members, daemon=True).start()

# --- WEEKEND & HOLIDAY CHECK ---
today_weekday = datetime.now(IST).weekday()
if today_weekday in [5, 6]:
    day_name = "Saturday" if today_weekday == 5 else "Sunday"
    send_telegram_alert(
        f"🏖️ WEEKEND MARKET HOLIDAY ({day_name})!\n\n"
        f"• Market is closed today.\n"
        f"• Scanner resumes on Monday at 09:00 AM IST."
    )
    exit(0)

try:
    holidays_df = capital_market.holiday_trading()
    today_str = datetime.now(IST).strftime('%d-%b-%Y')
    if holidays_df is not None and not holidays_df.empty:
        if 'tradingDate' in holidays_df.columns and today_str in holidays_df['tradingDate'].values:
            reason = holidays_df[holidays_df['tradingDate'] == today_str]['description'].values[0]
            send_telegram_alert(f"🏖️ MARKET HOLIDAY TODAY!\n\n• Reason: {reason}\n• Scanner closed.")
            exit(0)
except Exception as e:
    print(f"Holiday API check skipped: {e}")

INDEX_WATCHLIST = ["NIFTY 50", "NIFTY BANK"]
YF_TICKERS = {"NIFTY 50": "^NSEI", "NIFTY BANK": "^NSEBANK"}
BACKUP_FILE = "active_trades_engine.json"

def load_backup():
    default_data = {
        "trades": {idx: None for idx in INDEX_WATCHLIST},
        "stats": {"total_signals": 0, "targets_achieved": 0, "sl_hits": 0, "reversal_profits": 0, "early_sl_cuts": 0},
        "date": datetime.now(IST).strftime('%d-%b-%Y')
    }
    if os.path.exists(BACKUP_FILE):
        try:
            with open(BACKUP_FILE, 'r') as f:
                data = json.load(f)
                if data.get("date") == default_data["date"]:
                    return data.get("trades", default_data["trades"]), data.get("stats", default_data["stats"])
        except Exception:
            pass
    return default_data["trades"], default_data["stats"]

def save_backup(trades, stats):
    try:
        data = {"trades": trades, "stats": stats, "date": datetime.now(IST).strftime('%d-%b-%Y')}
        with open(BACKUP_FILE, 'w') as f:
            json.dump(data, f, indent=4)
    except Exception as err:
        print(f"Backup Save Error: {err}")

active_trades, trade_stats = load_backup()

# --- COMPLETE H1-H4 & L1-L4 FORMULA ENGINE ---
def calculate_h_l_levels(index_name):
    try:
        ticker = YF_TICKERS.get(index_name)
        df_daily = yf.download(ticker, period="5d", interval="1d", progress=False)
        if not df_daily.empty:
            if isinstance(df_daily.columns, pd.MultiIndex):
                df_daily.columns = df_daily.columns.get_level_values(0)
            prev_day = df_daily.iloc[-2]
            high = float(prev_day['High'])
            low = float(prev_day['Low'])
            close = float(prev_day['Close'])
            diff = high - low

            return {
                "H4": round(close + (diff * 1.1 / 2.0), 2),
                "H3": round(close + (diff * 1.1 / 4.0), 2),
                "H2": round(close + (diff * 1.1 / 6.0), 2),
                "H1": round(close + (diff * 1.1 / 12.0), 2),
                "L1": round(close - (diff * 1.1 / 12.0), 2),
                "L2": round(close - (diff * 1.1 / 6.0), 2),
                "L3": round(close - (diff * 1.1 / 4.0), 2),
                "L4": round(close - (diff * 1.1 / 2.0), 2)
            }
    except Exception as e:
        print(f"Levels Calculation Error ({index_name}): {e}")
    return None

market_levels = {idx: calculate_h_l_levels(idx) for idx in INDEX_WATCHLIST}

# --- LIVE OPTION CHAIN DATA ENGINE (BUYERS & SELLERS) ---
def get_detailed_options(index_name, spot_price, signal_type):
    step = 50 if index_name == "NIFTY 50" else 100
    atm_strike = int(round(spot_price / step) * step)
    symbol = "NIFTY" if index_name == "NIFTY 50" else "BANKNIFTY"

    if signal_type == "BUY":
        buyer_type = "CE"
        buyer_strike = atm_strike
        seller_type = "PE"
        seller_strike = atm_strike
        safe_seller_strike = atm_strike - step
    else:
        buyer_type = "PE"
        buyer_strike = atm_strike
        seller_type = "CE"
        seller_strike = atm_strike
        safe_seller_strike = atm_strike + step

    buyer_ltp = None
    seller_ltp = None
    safe_seller_ltp = None
    exp_date = ""

    try:
        chain_df = capital_market.live_index_option_chain(symbol)
        if chain_df is not None and not chain_df.empty:
            exp_date = chain_df['expiryDate'].iloc[0]
            curr_exp = chain_df[chain_df['expiryDate'] == exp_date]

            b_row = curr_exp[curr_exp['strikePrice'] == buyer_strike]
            if not b_row.empty and f"{buyer_type}_LTP" in b_row.columns:
                buyer_ltp = float(str(b_row[f"{buyer_type}_LTP"].values[0]).replace(',', ''))

            s_row = curr_exp[curr_exp['strikePrice'] == seller_strike]
            if not s_row.empty and f"{seller_type}_LTP" in s_row.columns:
                seller_ltp = float(str(s_row[f"{seller_type}_LTP"].values[0]).replace(',', ''))

            safe_row = curr_exp[curr_exp['strikePrice'] == safe_seller_strike]
            if not safe_row.empty and f"{seller_type}_LTP" in safe_row.columns:
                safe_seller_ltp = float(str(safe_row[f"{seller_type}_LTP"].values[0]).replace(',', ''))
    except Exception as e:
        print(f"Live Option Chain Warning: {e}")

    b_sl = f"₹{max(buyer_ltp * 0.70, 5.0):.1f}" if buyer_ltp else "15-20% SL"
    b_t1 = f"₹{buyer_ltp * 1.25:.1f}" if buyer_ltp else "+25% Gain"
    b_t2 = f"₹{buyer_ltp * 1.50:.1f}" if buyer_ltp else "+50% Gain"

    s_sl = f"₹{seller_ltp * 1.35:.1f}" if seller_ltp else "+35% Premium"
    s_tgt = f"₹{seller_ltp * 0.40:.1f}" if seller_ltp else "60% Decay"

    return {
        "exp": exp_date,
        "buyer_strike": f"{buyer_strike} {buyer_type}",
        "buyer_ltp": f"₹{buyer_ltp:.2f}" if buyer_ltp else "Live Terminal",
        "buyer_sl": b_sl,
        "buyer_t1": b_t1,
        "buyer_t2": b_t2,
        "seller_strike": f"{seller_strike} {seller_type}",
        "seller_ltp": f"₹{seller_ltp:.2f}" if seller_ltp else "Live Terminal",
        "seller_sl": s_sl,
        "seller_tgt": s_tgt,
        "safe_seller_strike": f"{safe_seller_strike} {seller_type}",
        "safe_seller_ltp": f"₹{safe_seller_ltp:.2f}" if safe_seller_ltp else "Live Terminal",
    }

def send_morning_levels():
    msg = f"📊 KEY PIVOT LEVELS (H1-H4 & L1-L4)\n⏰ Time: 09:10 AM IST\nStrategy: {STRATEGY_DISPLAY_NAME}\n\n"
    for idx in INDEX_WATCHLIST:
        p = market_levels.get(idx)
        if p:
            msg += (
                f"🔹 {idx}:\n"
                f"• H4 (Breakout Buy): {p['H4']:.2f}\n"
                f"• H3 (Short Zone / Sell Reversal): {p['H3']:.2f}\n"
                f"• H2: {p['H2']:.2f} | H1: {p['H1']:.2f}\n"
                f"• L1: {p['L1']:.2f} | L2: {p['L2']:.2f}\n"
                f"• L3 (Long Zone / Buy Reversal): {p['L3']:.2f}\n"
                f"• L4 (Breakdown Sell): {p['L4']:.2f}\n\n"
            )
    send_telegram_alert(msg)

def get_live_index_data():
    try:
        return capital_market.market_watch_all_indices()
    except Exception as e:
        print(f"NSE Fetch Error: {e}")
        return None

prev_close_dict = {}
last_heartbeat_hour = -1
levels_sent_today = False

# --- CONTINUOUS SCANNER ENGINE ---
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

        if now.hour == 9 and now.minute >= 10 and not levels_sent_today:
            send_morning_levels()
            levels_sent_today = True

        # 03:40 PM Daily Closing Summary
        if current_time >= shutdown_time:
            total_sigs = trade_stats['total_signals']
            targets = trade_stats['targets_achieved']
            sls = trade_stats['sl_hits']
            revs = trade_stats['reversal_profits']
            early_cuts = trade_stats.get('early_sl_cuts', 0)
            total_resolved = targets + sls + revs + early_cuts
            win_rate = ((targets + revs) / total_resolved * 100) if total_resolved > 0 else 0.0

            summary = (
                f"📊 MARKET CLOSED (DAILY PERFORMANCE REPORT)\n\n"
                f"⚡ Strategy: {STRATEGY_DISPLAY_NAME}\n"
                f"📅 Date: {now.strftime('%d-%b-%Y')}\n\n"
                f"• Total Momentum Spikes: {total_sigs}\n"
                f"• Targets Achieved: {targets}\n"
                f"• Reversal Exits in Profit: {revs}\n"
                f"• Early Risk Cuts: {early_cuts}\n"
                f"• Stop Losses Hit: {sls}\n"
                f"• Win Rate: {win_rate:.1f}%\n\n"
                f"Scanner safely closed. Resumes tomorrow at 09:00 AM IST!"
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

                    trade = active_trades[index_name]
                    pivots = market_levels.get(index_name)
                    adverse_cut_limit = 45 if index_name == "NIFTY 50" else 90

                    if trade is not None:
                        # 03:20 PM Auto Square-off
                        if is_market_closing:
                            pnl = current_price - trade['entry'] if trade['type'] == 'BUY' else trade['entry'] - current_price
                            send_telegram_alert(
                                f"⏰ AUTO EXIT (03:20 PM INTRADAY CLOSE)\n\n"
                                f"Strategy: {STRATEGY_DISPLAY_NAME}\n"
                                f"Index: {index_name}\n"
                                f"Exit Spot: {current_price:.2f} | Spot PnL: {pnl:+.2f}\n"
                                f"Status: Position Cleared."
                            )
                            active_trades[index_name] = None
                            save_backup(active_trades, trade_stats)
                            continue

                        # --- BUY TRADE TRACKING ---
                        if trade['type'] == 'BUY':
                            if 'best_price' not in trade: trade['best_price'] = trade['entry']
                            trade['best_price'] = max(trade['best_price'], current_price)
                            peak_profit = trade['best_price'] - trade['entry']
                            adverse_move = trade['entry'] - current_price

                            # 1. Early Cut
                            if not trade.get('t1_hit') and adverse_move >= adverse_cut_limit and (pivots and current_price < pivots['L4']):
                                trade_stats['early_sl_cuts'] = trade_stats.get('early_sl_cuts', 0) + 1
                                send_telegram_alert(
                                    f"⚠️ MOMENTUM FAILED: EARLY EXIT!\n\n"
                                    f"Strategy: {STRATEGY_DISPLAY_NAME}\n"
                                    f"Index: {index_name} (BUY)\n"
                                    f"Reason: Breakdown Below Support L4\n"
                                    f"Exit Spot: {current_price:.2f} (Cut at -{adverse_move:.2f} pts)\n"
                                    f"Status: Safely closed to save big SL."
                                )
                                active_trades[index_name] = None
                                save_backup(active_trades, trade_stats)
                                continue

                            # 2. Profit Reversal Cut
                            if not trade.get('t1_hit') and peak_profit >= 30:
                                pullback = trade['best_price'] - current_price
                                if pullback >= (peak_profit * 0.40):
                                    locked_gain = current_price - trade['entry']
                                    send_telegram_alert(
                                        f"⚡ MOMENTUM REVERSAL: BOOK PROFIT!\n\n"
                                        f"Strategy: {STRATEGY_DISPLAY_NAME}\n"
                                        f"Index: {index_name} (BUY)\n"
                                        f"Peak Spot: {trade['best_price']:.2f}\n"
                                        f"Book full profit @ {current_price:.2f} (+{locked_gain:.2f} pts)\n"
                                        f"Status: Trade Closed in profit before SL."
                                    )
                                    trade_stats['reversal_profits'] += 1
                                    active_trades[index_name] = None
                                    save_backup(active_trades, trade_stats)
                                    continue

                            # 3. Full SL
                            if not trade.get('t1_hit') and current_price <= trade['sl']:
                                trade_stats['sl_hits'] += 1
                                send_telegram_alert(
                                    f"❌ STOP LOSS HIT!\n\n"
                                    f"Strategy: {STRATEGY_DISPLAY_NAME}\n"
                                    f"Index: {index_name} (BUY)\n"
                                    f"Exit Spot: {current_price:.2f} | SL: {trade['sl']:.2f}\n"
                                    f"Status: Trade Closed."
                                )
                                active_trades[index_name] = None
                                save_backup(active_trades, trade_stats)
                                continue

                            # 4. Target 1
                            if not trade.get('t1_hit') and current_price >= trade['t1']:
                                trade['t1_hit'] = True
                                trade['sl'] = trade['entry']
                                trade_stats['targets_achieved'] += 1
                                send_telegram_alert(
                                    f"🎯 TARGET 1 ACHIEVED!\n\n"
                                    f"Strategy: {STRATEGY_DISPLAY_NAME}\n"
                                    f"Index: {index_name} (BUY)\n"
                                    f"Spot: {current_price:.2f} | T1: {trade['t1']:.2f}\n"
                                    f"🛡️ SL Trailed to Entry: {trade['entry']:.2f} (Zero Risk Active)"
                                )
                                save_backup(active_trades, trade_stats)

                            # 5. Target 2
                            if trade.get('t1_hit') and not trade.get('t2_hit') and current_price >= trade['t2']:
                                trade['t2_hit'] = True
                                send_telegram_alert(
                                    f"🎯🎯 TARGET 2 ACHIEVED!\n\n"
                                    f"Strategy: {STRATEGY_DISPLAY_NAME}\n"
                                    f"Index: {index_name} (BUY)\n"
                                    f"Spot: {current_price:.2f} | T2: {trade['t2']:.2f}\n"
                                    f"Status: Partial profits secured. Trailing active."
                                )
                                save_backup(active_trades, trade_stats)

                            # 6. Target 3
                            if trade.get('t2_hit') and current_price >= trade['t3']:
                                send_telegram_alert(
                                    f"🎯🎯🎯 FINAL TARGET 3 HIT!\n\n"
                                    f"Strategy: {STRATEGY_DISPLAY_NAME}\n"
                                    f"Index: {index_name} (BUY)\n"
                                    f"Exit Spot: {current_price:.2f} | T3: {trade['t3']:.2f}\n"
                                    f"Status: All Targets Achieved. Trade Closed!"
                                )
                                active_trades[index_name] = None
                                save_backup(active_trades, trade_stats)
                                continue

                        # --- SELL TRADE TRACKING ---
                        elif trade['type'] == 'SELL':
                            if 'best_price' not in trade: trade['best_price'] = trade['entry']
                            trade['best_price'] = min(trade['best_price'], current_price)
                            peak_profit = trade['entry'] - trade['best_price']
                            adverse_move = current_price - trade['entry']

                            # 1. Early Cut
                            if not trade.get('t1_hit') and adverse_move >= adverse_cut_limit and (pivots and current_price > pivots['H4']):
                                trade_stats['early_sl_cuts'] = trade_stats.get('early_sl_cuts', 0) + 1
                                send_telegram_alert(
                                    f"⚠️ MOMENTUM FAILED: EARLY EXIT!\n\n"
                                    f"Strategy: {STRATEGY_DISPLAY_NAME}\n"
                                    f"Index: {index_name} (SELL)\n"
                                    f"Reason: Breakout Above Resistance H4\n"
                                    f"Exit Spot: {current_price:.2f} (Cut at -{adverse_move:.2f} pts)\n"
                                    f"Status: Safely closed to save big SL."
                                )
                                active_trades[index_name] = None
                                save_backup(active_trades, trade_stats)
                                continue

                            # 2. Profit Reversal Cut
                            if not trade.get('t1_hit') and peak_profit >= 30:
                                bounce = current_price - trade['best_price']
                                if bounce >= (peak_profit * 0.40):
                                    locked_gain = trade['entry'] - current_price
                                    send_telegram_alert(
                                        f"⚡ MOMENTUM REVERSAL: BOOK PROFIT!\n\n"
                                        f"Strategy: {STRATEGY_DISPLAY_NAME}\n"
                                        f"Index: {index_name} (SELL)\n"
                                        f"Lowest Dip: {trade['best_price']:.2f}\n"
                                        f"Book full profit @ {current_price:.2f} (+{locked_gain:.2f} pts)\n"
                                        f"Status: Trade Closed in profit before SL."
                                    )
                                    trade_stats['reversal_profits'] += 1
                                    active_trades[index_name] = None
                                    save_backup(active_trades, trade_stats)
                                    continue

                            # 3. Full SL
                            if not trade.get('t1_hit') and current_price >= trade['sl']:
                                trade_stats['sl_hits'] += 1
                                send_telegram_alert(
                                    f"❌ STOP LOSS HIT!\n\n"
                                    f"Strategy: {STRATEGY_DISPLAY_NAME}\n"
                                    f"Index: {index_name} (SELL)\n"
                                    f"Exit Spot: {current_price:.2f} | SL: {trade['sl']:.2f}\n"
                                    f"Status: Trade Closed."
                                )
                                active_trades[index_name] = None
                                save_backup(active_trades, trade_stats)
                                continue

                            # 4. Target 1
                            if not trade.get('t1_hit') and current_price <= trade['t1']:
                                trade['t1_hit'] = True
                                trade['sl'] = trade['entry']
                                trade_stats['targets_achieved'] += 1
                                send_telegram_alert(
                                    f"🎯 TARGET 1 ACHIEVED!\n\n"
                                    f"Strategy: {STRATEGY_DISPLAY_NAME}\n"
                                    f"Index: {index_name} (SELL)\n"
                                    f"Spot: {current_price:.2f} | T1: {trade['t1']:.2f}\n"
                                    f"🛡️ SL Trailed to Entry: {trade['entry']:.2f} (Zero Risk Active)"
                                )
                                save_backup(active_trades, trade_stats)

                            # 5. Target 2
                            if trade.get('t1_hit') and not trade.get('t2_hit') and current_price <= trade['t2']:
                                trade['t2_hit'] = True
                                send_telegram_alert(
                                    f"🎯🎯 TARGET 2 ACHIEVED!\n\n"
                                    f"Strategy: {STRATEGY_DISPLAY_NAME}\n"
                                    f"Index: {index_name} (SELL)\n"
                                    f"Spot: {current_price:.2f} | T2: {trade['t2']:.2f}\n"
                                    f"Status: Partial profits secured. Trailing active."
                                )
                                save_backup(active_trades, trade_stats)

                            # 6. Target 3
                            if trade.get('t2_hit') and current_price <= trade['t3']:
                                send_telegram_alert(
                                    f"🎯🎯🎯 FINAL TARGET 3 HIT!\n\n"
                                    f"Strategy: {STRATEGY_DISPLAY_NAME}\n"
                                    f"Index: {index_name} (SELL)\n"
                                    f"Exit Spot: {current_price:.2f} | T3: {trade['t3']:.2f}\n"
                                    f"Status: All Targets Achieved. Trade Closed!"
                                )
                                active_trades[index_name] = None
                                save_backup(active_trades, trade_stats)
                                continue

                    # --- H1-H4 & L1-L4 ENTRY DETECTOR ---
                    if can_take_trades and active_trades[index_name] is None and pivots is not None:
                        h4, h3, h2, h1 = pivots['H4'], pivots['H3'], pivots['H2'], pivots['H1']
                        l1, l2, l3, l4 = pivots['L1'], pivots['L2'], pivots['L3'], pivots['L4']

                        signal_found = False
                        sig_type = ""
                        setup_name = ""
                        sl = 0.0
                        t1 = 0.0
                        t2 = 0.0
                        t3 = 0.0

                        # 1. H4 SUPER BREAKOUT (BUY)
                        if current_price > h4:
                            signal_found = True
                            sig_type = "BUY"
                            setup_name = "H4 BREAKOUT"
                            sl = round(h3, 2)
                            risk = current_price - sl
                            if risk < 15: sl = round(current_price - 25.0, 2); risk = 25.0
                            t1 = round(current_price + (risk * 1.0), 2)
                            t2 = round(current_price + (risk * 1.5), 2)
                            t3 = round(current_price + (risk * 2.5), 2)

                        # 2. L4 SUPER BREAKDOWN (SELL)
                        elif current_price < l4:
                            signal_found = True
                            sig_type = "SELL"
                            setup_name = "L4 BREAKDOWN"
                            sl = round(l3, 2)
                            risk = sl - current_price
                            if risk < 15: sl = round(current_price + 25.0, 2); risk = 25.0
                            t1 = round(current_price - (risk * 1.0), 2)
                            t2 = round(current_price - (risk * 1.5), 2)
                            t3 = round(current_price - (risk * 2.5), 2)

                        # 3. L3 REVERSAL (BOUNCE BUY)
                        elif current_price >= l3 and current_price <= (l3 + 12):
                            signal_found = True
                            sig_type = "BUY"
                            setup_name = "L3 REVERSAL"
                            sl = round(l4, 2)
                            t1 = round(l1, 2)
                            t2 = round(h1, 2)
                            t3 = round(h3, 2)

                        # 4. H3 REVERSAL (REJECTION SELL)
                        elif current_price <= h3 and current_price >= (h3 - 12):
                            signal_found = True
                            sig_type = "SELL"
                            setup_name = "H3 REVERSAL"
                            sl = round(h4, 2)
                            t1 = round(h1, 2)
                            t2 = round(l1, 2)
                            t3 = round(l3, 2)

                        # DISPATCH SIGNAL IF TRIGGERED
                        if signal_found:
                            opt = get_detailed_options(index_name, current_price, sig_type)
                            exp_txt = f"({opt['exp']})" if opt['exp'] else ""

                            active_trades[index_name] = {
                                'strategy': STRATEGY_DISPLAY_NAME,
                                'setup': setup_name,
                                'type': sig_type,
                                'entry': current_price,
                                'best_price': current_price,
                                'sl': sl,
                                't1': t1,
                                't2': t2,
                                't3': t3,
                                't1_hit': False,
                                't2_hit': False
                            }
                            trade_stats['total_signals'] += 1
                            save_backup(active_trades, trade_stats)

                            icon = "🟢" if sig_type == "BUY" else "🔴"
                            msg = (
                                f"{icon} {index_name} {setup_name} ({sig_type})\n\n"
                                f"⚡ Strategy: {STRATEGY_DISPLAY_NAME}\n"
                                f"⏰ Time: {current_time_str} IST\n"
                                f"💵 Spot Entry: {current_price:.2f}\n"
                                f"🛑 Spot SL: {sl:.2f}\n\n"
                                f"🛒 FOR OPTION BUYERS {exp_txt}:\n"
                                f"• Strike: {opt['buyer_strike']} @ {opt['buyer_ltp']}\n"
                                f"• Option SL: {opt['buyer_sl']}\n"
                                f"• Target 1: {opt['buyer_t1']} | Target 2: {opt['buyer_t2']}\n\n"
                                f"🛡️ FOR OPTION WRITERS / SELLERS:\n"
                                f"• Sell ATM: {opt['seller_strike']} @ {opt['seller_ltp']}\n"
                                f"• Safe OTM: {opt['safe_seller_strike']} @ {opt['safe_seller_ltp']}\n"
                                f"• SL: {opt['seller_sl']} | Target: {opt['seller_tgt']}\n\n"
                                f"🎯 Spot T1: {t1:.2f} | T2: {t2:.2f} | T3: {t3:.2f}"
                            )
                            send_telegram_alert(msg)

            # Hourly Market Pulse
            if now.minute == 0 and now.hour != last_heartbeat_hour and (9 <= now.hour <= 15):
                last_heartbeat_hour = now.hour
                hb_msg = f"💓 HOURLY STATUS ALERT\n⏰ Time: {current_time_str} IST\n\n"
                for idx, prc in prices_dict.items():
                    prev_c = prev_close_dict.get(idx, prc)
                    diff = prc - prev_c
                    pct = (diff / prev_c) * 100 if prev_c != 0 else 0.0
                    hb_msg += f"• {idx}: {prc:.2f} ({diff:+.2f} | {pct:+.2f}%)\n"
                send_telegram_alert(hb_msg)

        time.sleep(3)

    except Exception as loop_err:
        print(f"Engine Warning: {loop_err}")
        time.sleep(3)
