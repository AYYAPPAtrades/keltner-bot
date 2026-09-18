import os
import time
import requests
import json
import threading
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import pandas as pd
import numpy as np
import yfinance as yf
from nselib import capital_market

# --- TIMEZONE CONFIGURATION ---
IST = ZoneInfo("Asia/Kolkata")
start_now = datetime.now(IST)

# --- NEW TELEGRAM CONFIGURATION (SAS TRADING LAB) ---
TELEGRAM_BOT_TOKEN = "8941192045:AAEBwZ8O4Q7-K-ktSx7kAewUy4QIXsLWEhs"

# പുതിയ ചാനൽ യൂസർനെയിമും അഡ്മിൻ ഐഡികളും
TELEGRAM_CHAT_IDS = [
    "@sas_trading_lab",   # പുതിയ ചാനൽ
    "8996427731",         # Admin 1
    "6789591588"          # Admin 2
]

tele_session = requests.Session()
STRATEGY_DISPLAY_NAME = "MOMENTUM SPIKE"

# --- FAST ALERT ENGINE ---
def send_telegram_alert(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    for chat_id in TELEGRAM_CHAT_IDS:
        try:
            payload = {"chat_id": chat_id, "text": msg}
            tele_session.post(url, json=payload, timeout=5)
        except Exception as e:
            print(f"Telegram Alert Error ({chat_id}): {e}")

# 1. IMMEDIATE WORKFLOW ALERT (SAS TRADING LAB)
send_telegram_alert(
    "🟢 GITHUB WORKFLOW TRIGGERED!\n\n"
    "🚀 SAS TRADING LAB Algo Engine is RUNNING.\n"
    f"🕒 Time: {start_now.strftime('%I:%M:%S %p')} IST\n"
    f"📅 Date: {start_now.strftime('%d-%b-%Y')}\n"
    "📡 Channel & Admin Connection: Verified & Active ✅"
)

# 2. WELCOME MESSAGE FOR NEW MEMBERS
WELCOME_MESSAGE = (
    "👋 Welcome to SAS TRADING LAB!\n\n"
    "📈 Automated Algo Tracking for NIFTY 50.\n"
    "⚡ Live Momentum Spikes & Key Breakout Levels (H1-H4).\n"
    "📊 Daily Real-Time Performance & Expiry Tracking.\n\n"
    "📌 Please check the PINNED message for important Legal Disclaimers.\n"
    "(Educational & Research purpose only | Not SEBI Registered)"
)

# --- BACKGROUND MEMBER JOIN LISTENER ---
def poll_new_channel_members():
    last_update_id = 0
    while True:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
            params = {"offset": last_update_id + 1, "timeout": 20, "allowed_updates": ["chat_member"]}
            res = tele_session.get(url, params=params, timeout=25).json()
            if res.get("ok"):
                for update in res.get("result", []):
                    last_update_id = update["update_id"]
                    if "chat_member" in update:
                        cm = update["chat_member"]
                        if cm.get("new_chat_member", {}).get("status") == "member":
                            target_chat_id = cm["chat"]["id"]
                            send_telegram_alert(WELCOME_MESSAGE)
        except Exception:
            time.sleep(5)
        time.sleep(2)

threading.Thread(target=poll_new_channel_members, daemon=True).start()

# --- HOLIDAY & WEEKEND CHECK ---
today_weekday = datetime.now(IST).weekday()
if today_weekday in [5, 6]:
    day_name = "Saturday" if today_weekday == 5 else "Sunday"
    send_telegram_alert(f"🏖️ WEEKEND MARKET HOLIDAY ({day_name})!\n\n• Market closed today.\n• Resumes Monday 09:00 AM IST.")
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
    print(f"Holiday check bypassed: {e}")

# FOCUS: NIFTY 50 ONLY
INDEX_NAME = "NIFTY 50"
BACKUP_FILE = "active_trades_sas_lab.json"

# --- JSON PERSISTENCE (STATE & BACKUP) ---
def load_backup():
    default_data = {
        "trade": None,
        "stats": {"total_signals": 0, "targets_achieved": 0, "sl_hits": 0, "reversal_profits": 0, "early_sl_cuts": 0},
        "date": datetime.now(IST).strftime('%d-%b-%Y')
    }
    if os.path.exists(BACKUP_FILE):
        try:
            with open(BACKUP_FILE, 'r') as f:
                data = json.load(f)
                if data.get("date") == default_data["date"]:
                    return data.get("trade"), data.get("stats", default_data["stats"])
        except Exception:
            pass
    return default_data["trade"], default_data["stats"]

def save_backup(trade, stats):
    try:
        data = {"trade": trade, "stats": stats, "date": datetime.now(IST).strftime('%d-%b-%Y')}
        with open(BACKUP_FILE, 'w') as f:
            json.dump(data, f, indent=4)
    except Exception as err:
        print(f"Backup Save Error: {err}")

active_trade, trade_stats = load_backup()

# --- CAMARILLA H1-H4 LEVELS ---
def calculate_h_l_levels():
    try:
        df_daily = yf.download("^NSEI", period="5d", interval="1d", progress=False)
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
        print(f"Levels Calculation Error: {e}")
    return None

pivots = calculate_h_l_levels()

# --- OPTION DATA ENGINE ---
def get_detailed_options(spot_price, signal_type):
    step = 50
    atm_strike = int(round(spot_price / step) * step)
    buyer_type = "CE" if signal_type == "BUY" else "PE"
    seller_type = "PE" if signal_type == "BUY" else "CE"
    safe_seller_strike = (atm_strike - step) if signal_type == "BUY" else (atm_strike + step)

    buyer_ltp = None
    seller_ltp = None
    safe_seller_ltp = None
    exp_date = ""

    try:
        chain_df = capital_market.live_index_option_chain("NIFTY")
        if chain_df is not None and not chain_df.empty:
            exp_date = chain_df['expiryDate'].iloc[0]
            curr_exp = chain_df[chain_df['expiryDate'] == exp_date]

            b_row = curr_exp[curr_exp['strikePrice'] == atm_strike]
            if not b_row.empty and f"{buyer_type}_LTP" in b_row.columns:
                buyer_ltp = float(str(b_row[f"{buyer_type}_LTP"].values[0]).replace(',', ''))

            s_row = curr_exp[curr_exp['strikePrice'] == atm_strike]
            if not s_row.empty and f"{seller_type}_LTP" in s_row.columns:
                seller_ltp = float(str(s_row[f"{seller_type}_LTP"].values[0]).replace(',', ''))

            safe_row = curr_exp[curr_exp['strikePrice'] == safe_seller_strike]
            if not safe_row.empty and f"{seller_type}_LTP" in safe_row.columns:
                safe_seller_ltp = float(str(safe_row[f"{seller_type}_LTP"].values[0]).replace(',', ''))
    except Exception as e:
        print(f"Option Chain Warning: {e}")

    b_sl = f"₹{max(buyer_ltp * 0.70, 5.0):.1f}" if buyer_ltp else "15-20% SL"
    b_t1 = f"₹{buyer_ltp * 1.25:.1f}" if buyer_ltp else "+25% Gain"
    b_t2 = f"₹{buyer_ltp * 1.50:.1f}" if buyer_ltp else "+50% Gain"

    s_sl = f"₹{seller_ltp * 1.35:.1f}" if seller_ltp else "+35% Premium"
    s_tgt = f"₹{seller_ltp * 0.40:.1f}" if seller_ltp else "60% Decay"

    return {
        "exp": exp_date,
        "buyer_strike": f"{atm_strike} {buyer_type}",
        "buyer_ltp": f"₹{buyer_ltp:.2f}" if buyer_ltp else "Live Terminal",
        "buyer_sl": b_sl,
        "buyer_t1": b_t1,
        "buyer_t2": b_t2,
        "seller_strike": f"{atm_strike} {seller_type}",
        "seller_ltp": f"₹{seller_ltp:.2f}" if seller_ltp else "Live Terminal",
        "seller_sl": s_sl,
        "seller_tgt": s_tgt,
        "safe_seller_strike": f"{safe_seller_strike} {seller_type}",
        "safe_seller_ltp": f"₹{safe_seller_ltp:.2f}" if safe_seller_ltp else "Live Terminal",
    }

def get_live_index_data():
    try:
        return capital_market.market_watch_all_indices()
    except Exception as e:
        return None

last_heartbeat_hour = -1
levels_sent = False

# --- ZERO-DELAY SCANNER ENGINE ---
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

        # 09:10 AM MORNING LEVELS
        if now.hour == 9 and now.minute >= 10 and not levels_sent:
            if pivots:
                send_telegram_alert(
                    f"📊 KEY PIVOT LEVELS (NIFTY 50)\n⏰ Time: 09:10 AM IST\nStrategy: {STRATEGY_DISPLAY_NAME}\n\n"
                    f"• H4 (Breakout Buy): {pivots['H4']:.2f}\n"
                    f"• H3 (Sell Reversal Zone): {pivots['H3']:.2f}\n"
                    f"• H2: {pivots['H2']:.2f} | H1: {pivots['H1']:.2f}\n"
                    f"• L1: {pivots['L1']:.2f} | L2: {pivots['L2']:.2f}\n"
                    f"• L3 (Buy Reversal Zone): {pivots['L3']:.2f}\n"
                    f"• L4 (Breakdown Sell): {pivots['L4']:.2f}\n"
                )
            levels_sent = True

        # 03:40 PM DAILY CLOSING SUMMARY
        if current_time >= shutdown_time:
            total_sigs = trade_stats['total_signals']
            targets = trade_stats['targets_achieved']
            sls = trade_stats['sl_hits']
            revs = trade_stats['reversal_profits']
            early_cuts = trade_stats.get('early_sl_cuts', 0)
            total_res = targets + sls + revs + early_cuts
            win_rate = ((targets + revs) / total_res * 100) if total_res > 0 else 0.0

            send_telegram_alert(
                f"📊 MARKET CLOSED (DAILY REPORT)\n\n"
                f"⚡ Strategy: {STRATEGY_DISPLAY_NAME}\n"
                f"📅 Date: {now.strftime('%d-%b-%Y')}\n\n"
                f"• Total Signals: {total_sigs}\n"
                f"• Targets Achieved: {targets}\n"
                f"• Reversal Exits in Profit: {revs}\n"
                f"• Early Risk Cuts: {early_cuts}\n"
                f"• Stop Losses Hit: {sls}\n"
                f"• Win Rate: {win_rate:.1f}%\n\n"
                f"SAS TRADING LAB Engine safely shut down."
            )
            break

        raw = get_live_index_data()
        if raw is not None and not raw.empty:
            row = raw[raw['index'] == INDEX_NAME]
            if not row.empty:
                current_price = float(str(row['last'].values[0]).replace(',', ''))

                # --- 1. ACTIVE POSITION TRACKING ---
                if active_trade is not None:
                    # 03:20 PM AUTO-EXIT
                    if is_market_closing:
                        pnl = current_price - active_trade['entry'] if active_trade['type'] == 'BUY' else active_trade['entry'] - current_price
                        send_telegram_alert(
                            f"⏰ AUTO EXIT (03:20 PM CLOSE)\n\n"
                            f"Index: NIFTY 50\n"
                            f"Exit Spot: {current_price:.2f} | Spot PnL: {pnl:+.2f}\n"
                            f"Status: Position Cleared."
                        )
                        active_trade = None
                        save_backup(active_trade, trade_stats)
                        continue

                    # BUY TRADE MONITORING
                    if active_trade['type'] == 'BUY':
                        if 'best_price' not in active_trade: active_trade['best_price'] = active_trade['entry']
                        active_trade['best_price'] = max(active_trade['best_price'], current_price)
                        peak = active_trade['best_price'] - active_trade['entry']
                        adverse = active_trade['entry'] - current_price

                        # Early Cut below L4
                        if not active_trade.get('t1_hit') and adverse >= 45 and (pivots and current_price < pivots['L4']):
                            trade_stats['early_sl_cuts'] = trade_stats.get('early_sl_cuts', 0) + 1
                            send_telegram_alert(
                                f"⚠️ MOMENTUM FAILED: EARLY EXIT!\n\n"
                                f"Index: NIFTY 50 (BUY)\n"
                                f"Reason: Breakdown Below Support L4\n"
                                f"Exit Spot: {current_price:.2f} (Cut at -{adverse:.2f} pts)\n"
                                f"Status: Position cut to protect capital."
                            )
                            active_trade = None
                            save_backup(active_trade, trade_stats)
                            continue

                        # Profit Reversal Lock (30+ pts peak, 40% retrace)
                        if not active_trade.get('t1_hit') and peak >= 30:
                            if (active_trade['best_price'] - current_price) >= (peak * 0.40):
                                locked = current_price - active_trade['entry']
                                send_telegram_alert(
                                    f"⚡ MOMENTUM REVERSAL: BOOK PROFIT!\n\n"
                                    f"Index: NIFTY 50 (BUY)\n"
                                    f"Peak Spot: {active_trade['best_price']:.2f}\n"
                                    f"Book Profit @ {current_price:.2f} (+{locked:.2f} pts)\n"
                                    f"Status: Trade Closed in profit before SL."
                                )
                                trade_stats['reversal_profits'] += 1
                                active_trade = None
                                save_backup(active_trade, trade_stats)
                                continue

                        # Stop Loss
                        if not active_trade.get('t1_hit') and current_price <= active_trade['sl']:
                            trade_stats['sl_hits'] += 1
                            send_telegram_alert(
                                f"❌ STOP LOSS HIT!\n\n"
                                f"Index: NIFTY 50 (BUY)\n"
                                f"Exit Spot: {current_price:.2f} | SL: {active_trade['sl']:.2f}\n"
                                f"Status: Trade Closed."
                            )
                            active_trade = None
                            save_backup(active_trade, trade_stats)
                            continue

                        # Target 1 Achieved
                        if not active_trade.get('t1_hit') and current_price >= active_trade['t1']:
                            active_trade['t1_hit'] = True
                            active_trade['sl'] = active_trade['entry']
                            trade_stats['targets_achieved'] += 1
                            send_telegram_alert(
                                f"🎯 TARGET 1 ACHIEVED!\n\n"
                                f"Index: NIFTY 50 (BUY)\n"
                                f"Spot: {current_price:.2f} | T1: {active_trade['t1']:.2f}\n"
                                f"🛡️ SL Trailed to Cost: {active_trade['entry']:.2f} (Zero Risk Active)"
                            )
                            save_backup(active_trade, trade_stats)

                        # Target 2 Achieved
                        if active_trade.get('t1_hit') and not active_trade.get('t2_hit') and current_price >= active_trade['t2']:
                            active_trade['t2_hit'] = True
                            send_telegram_alert(
                                f"🎯🎯 TARGET 2 ACHIEVED!\n\n"
                                f"Index: NIFTY 50 (BUY)\n"
                                f"Spot: {current_price:.2f} | T2: {active_trade['t2']:.2f}\n"
                                f"Status: Profits locked. Trailing to T3."
                            )
                            save_backup(active_trade, trade_stats)

                        # Target 3 Achieved
                        if active_trade.get('t2_hit') and current_price >= active_trade['t3']:
                            send_telegram_alert(
                                f"🎯🎯🎯 FINAL TARGET 3 HIT!\n\n"
                                f"Index: NIFTY 50 (BUY)\n"
                                f"Exit Spot: {current_price:.2f} | T3: {active_trade['t3']:.2f}\n"
                                f"Status: Full Targets Achieved. Trade Closed!"
                            )
                            active_trade = None
                            save_backup(active_trade, trade_stats)
                            continue

                    # SELL TRADE MONITORING
                    elif active_trade['type'] == 'SELL':
                        if 'best_price' not in active_trade: active_trade['best_price'] = active_trade['entry']
                        active_trade['best_price'] = min(active_trade['best_price'], current_price)
                        peak = active_trade['entry'] - active_trade['best_price']
                        adverse = current_price - active_trade['entry']

                        # Early Cut above H4
                        if not active_trade.get('t1_hit') and adverse >= 45 and (pivots and current_price > pivots['H4']):
                            trade_stats['early_sl_cuts'] = trade_stats.get('early_sl_cuts', 0) + 1
                            send_telegram_alert(
                                f"⚠️ MOMENTUM FAILED: EARLY EXIT!\n\n"
                                f"Index: NIFTY 50 (SELL)\n"
                                f"Reason: Breakout Above Resistance H4\n"
                                f"Exit Spot: {current_price:.2f} (Cut at -{adverse:.2f} pts)\n"
                                f"Status: Position cut to protect capital."
                            )
                            active_trade = None
                            save_backup(active_trade, trade_stats)
                            continue

                        # Profit Reversal Lock
                        if not active_trade.get('t1_hit') and peak >= 30:
                            if (current_price - active_trade['best_price']) >= (peak * 0.40):
                                locked = active_trade['entry'] - current_price
                                send_telegram_alert(
                                    f"⚡ MOMENTUM REVERSAL: BOOK PROFIT!\n\n"
                                    f"Index: NIFTY 50 (SELL)\n"
                                    f"Lowest Dip: {active_trade['best_price']:.2f}\n"
                                    f"Book Profit @ {current_price:.2f} (+{locked:.2f} pts)\n"
                                    f"Status: Trade Closed in profit before SL."
                                )
                                trade_stats['reversal_profits'] += 1
                                active_trade = None
                                save_backup(active_trade, trade_stats)
                                continue

                        # Stop Loss
                        if not active_trade.get('t1_hit') and current_price >= active_trade['sl']:
                            trade_stats['sl_hits'] += 1
                            send_telegram_alert(
                                f"❌ STOP LOSS HIT!\n\n"
                                f"Index: NIFTY 50 (SELL)\n"
                                f"Exit Spot: {current_price:.2f} | SL: {active_trade['sl']:.2f}\n"
                                f"Status: Trade Closed."
                            )
                            active_trade = None
                            save_backup(active_trade, trade_stats)
                            continue

                        # Target 1 Achieved
                        if not active_trade.get('t1_hit') and current_price <= active_trade['t1']:
                            active_trade['t1_hit'] = True
                            active_trade['sl'] = active_trade['entry']
                            trade_stats['targets_achieved'] += 1
                            send_telegram_alert(
                                f"🎯 TARGET 1 ACHIEVED!\n\n"
                                f"Index: NIFTY 50 (SELL)\n"
                                f"Spot: {current_price:.2f} | T1: {active_trade['t1']:.2f}\n"
                                f"🛡️ SL Trailed to Cost: {active_trade['entry']:.2f} (Zero Risk Active)"
                            )
                            save_backup(active_trade, trade_stats)

                        # Target 2 Achieved
                        if active_trade.get('t1_hit') and not active_trade.get('t2_hit') and current_price <= active_trade['t2']:
                            active_trade['t2_hit'] = True
                            send_telegram_alert(
                                f"🎯🎯 TARGET 2 ACHIEVED!\n\n"
                                f"Index: NIFTY 50 (SELL)\n"
                                f"Spot: {current_price:.2f} | T2: {active_trade['t2']:.2f}\n"
                                f"Status: Profits locked. Trailing to T3."
                            )
                            save_backup(active_trade, trade_stats)

                        # Target 3 Achieved
                        if active_trade.get('t2_hit') and current_price <= active_trade['t3']:
                            send_telegram_alert(
                                f"🎯🎯🎯 FINAL TARGET 3 HIT!\n\n"
                                f"Index: NIFTY 50 (SELL)\n"
                                f"Exit Spot: {current_price:.2f} | T3: {active_trade['t3']:.2f}\n"
                                f"Status: Full Targets Achieved. Trade Closed!"
                            )
                            active_trade = None
                            save_backup(active_trade, trade_stats)
                            continue

                # --- 2. ZERO-DELAY ENTRY DETECTOR ---
                if can_take_trades and active_trade is None and pivots is not None:
                    h4, h3, h2, h1 = pivots['H4'], pivots['H3'], pivots['H2'], pivots['H1']
                    l1, l2, l3, l4 = pivots['L1'], pivots['L2'], pivots['L3'], pivots['L4']

                    sig_found = False
                    sig_type = ""
                    setup_name = ""
                    sl = 0.0
                    t1, t2, t3 = 0.0, 0.0, 0.0

                    # H4 BREAKOUT (BUY)
                    if current_price > h4:
                        sig_found = True
                        sig_type = "BUY"
                        setup_name = "H4 BREAKOUT"
                        sl = round(h3, 2)
                        risk = current_price - sl
                        if risk < 15: sl = round(current_price - 25.0, 2); risk = 25.0
                        t1 = round(current_price + (risk * 1.0), 2)
                        t2 = round(current_price + (risk * 1.5), 2)
                        t3 = round(current_price + (risk * 2.5), 2)

                    # L4 BREAKDOWN (SELL)
                    elif current_price < l4:
                        sig_found = True
                        sig_type = "SELL"
                        setup_name = "L4 BREAKDOWN"
                        sl = round(l3, 2)
                        risk = sl - current_price
                        if risk < 15: sl = round(current_price + 25.0, 2); risk = 25.0
                        t1 = round(current_price - (risk * 1.0), 2)
                        t2 = round(current_price - (risk * 1.5), 2)
                        t3 = round(current_price - (risk * 2.5), 2)

                    # L3 REVERSAL (BOUNCE BUY)
                    elif current_price >= l3 and current_price <= (l3 + 12):
                        sig_found = True
                        sig_type = "BUY"
                        setup_name = "L3 REVERSAL"
                        sl = round(l4, 2)
                        t1, t2, t3 = round(l1, 2), round(h1, 2), round(h3, 2)

                    # H3 REVERSAL (REJECTION SELL)
                    elif current_price <= h3 and current_price >= (h3 - 12):
                        sig_found = True
                        sig_type = "SELL"
                        setup_name = "H3 REVERSAL"
                        sl = round(h4, 2)
                        t1, t2, t3 = round(h1, 2), round(l1, 2), round(l3, 2)

                    if sig_found:
                        opt = get_detailed_options(current_price, sig_type)
                        exp_txt = f"({opt['exp']})" if opt['exp'] else ""

                        active_trade = {
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
                        save_backup(active_trade, trade_stats)

                        icon = "🟢" if sig_type == "BUY" else "🔴"
                        send_telegram_alert(
                            f"{icon} NIFTY 50 {setup_name} ({sig_type})\n\n"
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

        # 1-second delay for instant signal dispatch
        time.sleep(1)

    except Exception as loop_err:
        print(f"Loop error: {loop_err}")
        time.sleep(2)
