import os
import time
import requests
import json
import smtplib
import threading
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import pandas as pd
import numpy as np
import yfinance as yf
from nselib import capital_market

from reportlab.lib.pagesizes import letter, landscape
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

# --- TIMEZONE CONFIGURATION ---
IST = ZoneInfo("Asia/Kolkata")
start_now = datetime.now(IST)

# --- NEW TELEGRAM CONFIGURATION (SAS TRADING LAB) ---
TELEGRAM_BOT_TOKEN = "8941192045:AAEBwZ8O4Q7-K-ktSx7kAewUy4QIXsLWEhs"

# നിങ്ങളുടെ കൃത്യമായ ചാനൽ ഐഡിയും അഡ്മിൻ ഐഡികളും
TELEGRAM_CHAT_IDS = [
    "-1004417570442",     # SAS TRADING LAB (Channel ID)
    "6789591588"          # Admin Personal ID
]

tele_session = requests.Session()
STRATEGY_DISPLAY_NAME = "MOMENTUM SPIKE"

# --- NEW EMAIL CONFIGURATION ---
SENDER_EMAIL = "shinos99@gmail.com"
SENDER_APP_PASSWORD = "nouiwuzkyjbzsgix"
RECEIVER_EMAILS = ["shinos99@gmail.com"]

# --- WELCOME MESSAGE ---
WELCOME_MESSAGE = (
    "👋 Welcome to SAS TRADING LAB!\n\n"
    "📈 Automated Algo Tracking exclusively for NIFTY 50.\n"
    f"⚡ Live Signals & Precision Levels ({STRATEGY_DISPLAY_NAME}).\n"
    "📊 Real-Time Strikes for Option Buyers & Sellers.\n"
    "🎯 Accurate Expiry Day Setups.\n\n"
    "📌 Please check the PINNED message for important Legal Disclaimers.\n"
    "(Educational & Analysis purpose only | Not SEBI Registered)"
)

def send_telegram_alert(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    for chat_id in TELEGRAM_CHAT_IDS:
        try:
            payload = {"chat_id": chat_id, "text": msg}
            tele_session.post(url, json=payload, timeout=6)
        except Exception as e:
            print(f"Telegram Alert Error ({chat_id}): {e}")

def send_telegram_document(file_path, caption=""):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendDocument"
    for chat_id in TELEGRAM_CHAT_IDS:
        try:
            with open(file_path, 'rb') as doc:
                files = {'document': doc}
                data = {'chat_id': chat_id, 'caption': caption}
                requests.post(url, data=data, files=files, timeout=25)
        except Exception as e:
            print(f"Telegram Doc Delivery Error ({chat_id}): {e}")

def send_email_with_pdf(file_path, subject, body):
    try:
        msg = MIMEMultipart()
        msg['From'] = SENDER_EMAIL
        msg['To'] = ", ".join(RECEIVER_EMAILS)
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain'))

        with open(file_path, "rb") as attachment:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(attachment.read())
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", f"attachment; filename={os.path.basename(file_path)}")
        msg.attach(part)

        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(SENDER_EMAIL, SENDER_APP_PASSWORD)
        server.sendmail(SENDER_EMAIL, RECEIVER_EMAILS, msg.as_string())
        server.quit()
        print("PDF report successfully emailed.")
    except Exception as e:
        print(f"Email Dispatch Warning: {e}")

# 1. IMMEDIATE STARTUP NOTIFICATION
send_telegram_alert(
    "🟢 ALGO SCANNER RUNNING!\n\n"
    "🚀 SAS TRADING LAB Engine Connected Successfully.\n"
    f"⚡ Strategy: {STRATEGY_DISPLAY_NAME}\n"
    f"🕒 Time: {start_now.strftime('%I:%M:%S %p')} IST\n"
    "📡 Signals & Reports directly delivering to this channel."
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

# --- WEEKEND & HOLIDAY PROTECTION ---
today_weekday = datetime.now(IST).weekday()
if today_weekday in [5, 6]:
    day_name = "Saturday" if today_weekday == 5 else "Sunday"
    send_telegram_alert(f"🏖️ WEEKEND MARKET HOLIDAY ({day_name})!\n\n• Market Closed.\n• Resumes Monday at 09:00 AM IST.")
    exit(0)

try:
    holidays_df = capital_market.holiday_trading()
    today_str = datetime.now(IST).strftime('%d-%b-%Y')
    if holidays_df is not None and not holidays_df.empty:
        if 'tradingDate' in holidays_df.columns and today_str in holidays_df['tradingDate'].values:
            reason = holidays_df[holidays_df['tradingDate'] == today_str]['description'].values[0]
            send_telegram_alert(f"🏖️ MARKET HOLIDAY TODAY!\n\n• Reason: {reason}\n• Bot shutting down cleanly.")
            exit(0)
except Exception as e:
    print(f"Holiday check bypassed: {e}")

# FOCUS: NIFTY 50 ONLY
INDEX_NAME = "NIFTY 50"
BACKUP_FILE = "active_trades_sas_lab.json"
MONTHLY_LEDGER_FILE = "monthly_trades_ledger_sas.json"

trade_stats = {"total_signals": 0, "target_hits": 0, "sl_hits": 0, "early_cuts": 0}
prev_close = None
algo_levels = None
pivots_alert_sent = False
hero_zero_sent = False
last_heartbeat_hour = -1

# --- JSON BACKUP & PERSISTENCE ---
def load_backup_state():
    default_state = {"NIFTY 50": None}
    if os.path.exists(BACKUP_FILE):
        try:
            with open(BACKUP_FILE, 'r') as f:
                data = json.load(f)
                if "NIFTY 50" in data:
                    return data
        except Exception as err:
            print(f"Backup Load Error: {err}")
    return default_state

def save_backup_state(state):
    try:
        with open(BACKUP_FILE, 'w') as f:
            json.dump(state, f, indent=4)
    except Exception as err:
        print(f"Backup Save Error: {err}")

def load_monthly_ledger():
    if os.path.exists(MONTHLY_LEDGER_FILE):
        try:
            with open(MONTHLY_LEDGER_FILE, 'r') as f:
                return json.load(f)
        except Exception:
            return []
    return []

def record_to_monthly_ledger(trade_entry):
    records = load_monthly_ledger()
    records.append(trade_entry)
    try:
        with open(MONTHLY_LEDGER_FILE, 'w') as f:
            json.dump(records, f, indent=4)
    except Exception as e:
        print(f"Ledger save warning: {e}")

# --- INTERNAL LEVEL CALCULATION ---
def calculate_algo_levels():
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
                "Buy_Trigger": round(close + (diff * 1.1 / 2.0), 2),
                "Key_Res": round(close + (diff * 1.1 / 4.0), 2),
                "Key_Sup": round(close - (diff * 1.1 / 4.0), 2),
                "Sell_Trigger": round(close - (diff * 1.1 / 2.0), 2),
                "Prev_Close": round(close, 2)
            }
    except Exception as e:
        print(f"Internal Level Calc Warning: {e}")
    return None

algo_levels = calculate_algo_levels()
active_trades = load_backup_state()

# --- ACCURATE NSE EXPIRY ENGINE ---
def check_actual_nse_expiry():
    try:
        chain_df = capital_market.live_index_option_chain("NIFTY")
        if chain_df is not None and not chain_df.empty:
            exp_date_str = str(chain_df['expiryDate'].iloc[0])
            exp_dt = datetime.strptime(exp_date_str, "%d-%b-%Y").date()
            today_dt = datetime.now(IST).date()

            is_today_expiry = (today_dt == exp_dt)
            next_possible_exp = exp_dt + timedelta(days=7)
            is_monthly_expiry = (next_possible_exp.month != exp_dt.month)

            return is_today_expiry, is_monthly_expiry, exp_date_str
    except Exception as e:
        print(f"NSE Expiry Check Warning: {e}")
    return False, False, ""

is_today_expiry, is_monthly_expiry, current_expiry_str = check_actual_nse_expiry()

# --- OPTION STRIKE ENGINE ---
def get_option_recommendations(spot_price, signal_direction, spot_risk):
    step = 50
    atm_strike = int(round(spot_price / step) * step)
    delta = 0.50
    base_atm_price = 110.0
    otm_seller_price = 65.0

    buyer_entry = base_atm_price
    buyer_sl = max(10.0, round(buyer_entry - (spot_risk * delta), 1))
    buyer_t1 = round(buyer_entry + (spot_risk * 1.0 * delta), 1)
    buyer_t2 = round(buyer_entry + (spot_risk * 1.5 * delta), 1)
    buyer_t3 = round(buyer_entry + (spot_risk * 2.5 * delta), 1)

    seller_entry = base_atm_price
    seller_sl = round(seller_entry + (spot_risk * delta), 1)
    seller_target = max(5.0, round(seller_entry - (spot_risk * 1.2 * delta), 1))

    if signal_direction == "BUY":
        buyer_strike = f"{atm_strike} CE"
        seller_strike = f"{atm_strike} PE"
        safe_seller_strike = f"{atm_strike - step} PE"
    else:
        buyer_strike = f"{atm_strike} PE"
        seller_strike = f"{atm_strike} CE"
        safe_seller_strike = f"{atm_strike + step} CE"

    return {
        "buyer_strike": buyer_strike, "buyer_entry": buyer_entry, "buyer_sl": buyer_sl,
        "buyer_t1": buyer_t1, "buyer_t2": buyer_t2, "buyer_t3": buyer_t3,
        "seller_strike": seller_strike, "seller_entry": seller_entry, "seller_sl": seller_sl,
        "seller_target": seller_target, "safe_seller_strike": safe_seller_strike, "safe_seller_entry": otm_seller_price
    }

# --- PDF REPORT ENGINE WITH DETAILED TIMESTAMPS & LEDGER TABLE ---
def generate_detailed_pdf_report(filename, title_text, subtitle_text, logs_to_print):
    doc = SimpleDocTemplate(filename, pagesize=landscape(letter), rightMargin=15, leftMargin=15, topMargin=20, bottomMargin=20)
    styles = getSampleStyleSheet()
    elements = []

    title_style = ParagraphStyle(
        'RepTitle', parent=styles['Heading1'], fontSize=15, leading=18,
        textColor=colors.HexColor("#1A365D"), alignment=1
    )
    elements.append(Paragraph(f"SAS TRADING LAB - {title_text}", title_style))
    elements.append(Paragraph(f"Strategy: {STRATEGY_DISPLAY_NAME} | Timeline: {subtitle_text} | Total Trades: {len(logs_to_print)}", styles['Normal']))
    elements.append(Spacer(1, 10))

    headers = [
        "SL\nNO", "Date", "Index & Type", "Entry Price\n- Time",
        "Target 1\n- Time", "Target 2\n- Time", "Target 3\n- Time",
        "Stop Loss\n- Time", "P/L Points\n(+ / -)", "Final Status"
    ]

    table_rows = [headers]
    for idx, log in enumerate(logs_to_print, start=1):
        t1_val = f"{log.get('t1', '-')}\n({log.get('t1_time', '-')})" if log.get('t1_hit') else "-"
        t2_val = f"{log.get('t2', '-')}\n({log.get('t2_time', '-')})" if log.get('t2_hit') else "-"
        t3_val = f"{log.get('t3', '-')}\n({log.get('t3_time', '-')})" if log.get('t3_hit') else "-"
        sl_val = f"{log.get('sl', '-')}\n({log.get('sl_time', '-')})" if log.get('sl_hit') else f"{log.get('sl', '-')}"

        pnl_val = f"{log.get('pnl', 0.0):+.2f}"

        table_rows.append([
            str(idx),
            log.get('date', '-'),
            f"{log.get('index', '')}\n({log.get('type', '')})",
            f"{log.get('entry', 0.0):.2f}\n({log.get('entry_time', '')})",
            t1_val,
            t2_val,
            t3_val,
            sl_val,
            pnl_val,
            log.get('status', '-')
        ])

    col_widths = [25, 65, 80, 80, 80, 80, 80, 80, 65, 110]
    trade_table = Table(table_rows, colWidths=col_widths)
    trade_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#2B6CB0")),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E0")),
        ('FONTSIZE', (0, 0), (-1, -1), 7.5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
    ]))
    elements.append(trade_table)
    doc.build(elements)

def format_telegram_card(trade):
    t1_txt = f"{trade.get('t1', '-')} [{trade.get('t1_time', '-')}] ✅" if trade.get('t1_hit') else "-"
    t2_txt = f"{trade.get('t2', '-')} [{trade.get('t2_time', '-')}] ✅" if trade.get('t2_hit') else "-"
    t3_txt = f"{trade.get('t3', '-')} [{trade.get('t3_time', '-')}] ✅" if trade.get('t3_hit') else "-"
    sl_txt = f"{trade.get('sl', '-')} [{trade.get('sl_time', '-')}] ❌" if trade.get('sl_hit') else f"{trade.get('sl', '-')}"

    pnl = trade.get('pnl', 0.0)
    pnl_str = f"+{pnl:.2f} Pts" if pnl >= 0 else f"{pnl:.2f} Pts"

    return (
        "📊 TRADE PERFORMANCE SUMMARY\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"📅 Date: {trade.get('date', '-')}\n"
        f"🔹 Index: {trade['index']} ({trade['type']})\n"
        f"⚡ Strategy: {STRATEGY_DISPLAY_NAME}\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"▫️ Entry Price : {trade['entry']:.2f} [{trade.get('entry_time', '-')}]\n"
        f"🎯 Target 1    : {t1_txt}\n"
        f"🎯 Target 2    : {t2_txt}\n"
        f"🎯 Target 3    : {t3_txt}\n"
        f"🛑 Stop Loss   : {sl_txt}\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"📈 P/L Points  : {pnl_str}\n"
        f"🏁 Final Status: {trade.get('status', 'Completed')}\n"
        "━━━━━━━━━━━━━━━━━━━━━"
    )

def get_live_index_data():
    try:
        return capital_market.market_watch_all_indices()
    except Exception as e:
        return None

# --- SCANNER RUNTIME LOOP ---
while True:
    try:
        now = datetime.now(IST)
        current_time = now.time()
        current_time_str = now.strftime('%I:%M %p')
        today_date_str = now.strftime('%d-%b-%Y')

        pivot_alert_time = datetime.strptime("09:05", "%H:%M").time()
        start_trade_time = datetime.strptime("09:30", "%H:%M").time()
        hero_zero_time = datetime.strptime("13:15", "%H:%M").time()
        end_trade_time = datetime.strptime("15:20", "%H:%M").time()
        shutdown_time = datetime.strptime("15:40", "%H:%M").time()

        # 1. 09:05 AM KEY LEVELS DISPATCH
        if not pivots_alert_sent and current_time >= pivot_alert_time:
            pivots_alert_sent = True
            if algo_levels:
                send_telegram_alert(
                    f"📐 DAILY KEY LEVELS (09:05 AM IST)\n"
                    f"📅 Date: {today_date_str} | Strategy: {STRATEGY_DISPLAY_NAME}\n\n"
                    f"🔹 NIFTY 50 (Prev Close: {algo_levels['Prev_Close']})\n"
                    f"• Bullish Breakout Zone: Above {algo_levels['Buy_Trigger']:.2f}\n"
                    f"• Major Resistance: {algo_levels['Key_Res']:.2f}\n"
                    f"• Major Support: {algo_levels['Key_Sup']:.2f}\n"
                    f"• Bearish Breakdown Zone: Below {algo_levels['Sell_Trigger']:.2f}\n"
                )

        can_take_trades = (start_trade_time <= current_time < end_trade_time)
        is_market_closing = (current_time >= end_trade_time)

        # 2. 03:40 PM MARKET CLOSE (PDF & EMAIL)
        if current_time >= shutdown_time:
            all_ledger_records = load_monthly_ledger()
            today_records = [l for l in all_ledger_records if l.get('date') == today_date_str]

            total = trade_stats['total_signals']
            wins = trade_stats['target_hits']
            win_rate = (wins / total * 100) if total > 0 else 0.0

            title_badge = "MONTHLY EXPIRY REPORT" if is_monthly_expiry else "DAILY PERFORMANCE REPORT"

            summary = (
                f"📊 MARKET CLOSED ({title_badge})\n\n"
                f"⚡ Strategy: {STRATEGY_DISPLAY_NAME}\n"
                f"📅 Date: {today_date_str}\n\n"
                f"• Signals Closed Today: {len(today_records)}\n"
                f"• Targets / Locks Achieved: {wins}\n"
                f"• Stop Losses Hit: {trade_stats['sl_hits']}\n"
                f"• Early Cuts: {trade_stats['early_cuts']}\n"
                f"🏆 Win Rate: {win_rate:.1f}%\n"
                f"📚 Total Monthly Trades: {len(all_ledger_records)}\n\n"
                f"Generating & Dispatching Comprehensive PDFs..."
            )
            send_telegram_alert(summary)

            pdf_daily = f"Nifty_Daily_Report_{today_date_str}.pdf"
            generate_detailed_pdf_report(pdf_daily, "DAILY PERFORMANCE REPORT", today_date_str, today_records)
            send_telegram_document(pdf_daily, caption=f"📄 NIFTY 50 Daily Report ({today_date_str})")
            send_email_with_pdf(pdf_daily, f"NIFTY 50 Daily Report - {today_date_str}", summary)

            if is_monthly_expiry:
                month_str = now.strftime('%B %Y')
                pdf_monthly = f"Nifty_Monthly_Cumulative_{now.strftime('%b_%Y')}.pdf"
                generate_detailed_pdf_report(pdf_monthly, "MONTHLY EXPIRY CUMULATIVE REPORT", month_str, all_ledger_records)
                send_telegram_document(pdf_monthly, caption=f"📚 Monthly Cumulative Ledger ({month_str})")
                send_email_with_pdf(pdf_monthly, f"NIFTY 50 Monthly Expiry Ledger - {month_str}", f"Attached full trade records up to {today_date_str}.")

            print("Market session completed safely.")
            break

        raw = get_live_index_data()
        if raw is not None and not raw.empty:
            row = raw[raw['index'] == INDEX_NAME]
            if not row.empty:
                current_price = float(str(row['last'].values[0]).replace(',', ''))
                if prev_close is None and 'previousClose' in row.columns:
                    prev_close = float(str(row['previousClose'].values[0]).replace(',', ''))

                # --- 🎯 01:15 PM HERO-ZERO SETUP ---
                if is_today_expiry and not hero_zero_sent and current_time >= hero_zero_time:
                    step = 50
                    atm = int(round(current_price / step) * step)
                    hz_type = "MONTHLY EXPIRY" if is_monthly_expiry else "WEEKLY EXPIRY"

                    send_telegram_alert(
                        f"🔥 *HERO-ZERO {hz_type} SETUP (01:15 PM)*\n\n"
                        f"📍 Index: *NIFTY 50* (Spot: {current_price:.2f})\n"
                        f"⚡ Strategy: {STRATEGY_DISPLAY_NAME}\n"
                        f"📅 Expiry Date: *{current_expiry_str}*\n\n"
                        f"🎯 *CALL OPTION (On Upside Spike):*\n"
                        f"• Buy Strike: *{atm + step} CE* (Expected: ₹15 - ₹35)\n"
                        f"• Strict SL: ₹6.00 | T1: ₹50.00 | T2: ₹80.00+\n\n"
                        f"🎯 *PUT OPTION (On Downside Spike):*\n"
                        f"• Buy Strike: *{atm - step} PE* (Expected: ₹15 - ₹35)\n"
                        f"• Strict SL: ₹6.00 | T1: ₹50.00 | T2: ₹80.00+\n\n"
                        f"⚡ *Rule:* 02:00 PM-ന് ശേഷമുള്ള അതിവേഗ സ്പൈക്കുകളിൽ മാത്രം ട്രേഡ് ചെയ്യുക. T1-ൽ ക്യാപിറ്റൽ എടുത്തു ട്രേഡ് റിസ്ക്-ഫ്രീ ആക്കുക!"
                    )
                    hero_zero_sent = True

                # --- ACTIVE POSITION TRACKING ---
                trade = active_trades["NIFTY 50"]
                if trade is not None:
                    # 03:20 PM AUTO-EXIT
                    if is_market_closing:
                        pnl = current_price - trade['entry'] if trade['type'] == 'BUY' else trade['entry'] - current_price
                        trade['exit_price'] = current_price
                        trade['exit_time'] = current_time_str
                        trade['pnl'] = pnl
                        trade['status'] = 'Auto-Exit (03:20 PM)'
                        record_to_monthly_ledger(trade)

                        send_telegram_alert(format_telegram_card(trade))
                        active_trades["NIFTY 50"] = None
                        save_backup_state(active_trades)
                        continue

                    # BUY POSITION MONITORING
                    if trade['type'] == 'BUY':
                        gain = current_price - trade['entry']
                        if gain > trade.get('max_gain', 0): trade['max_gain'] = gain

                        # Early Cut
                        if not trade.get('t1_hit') and current_price < trade['cut_level']:
                            trade_stats['early_cuts'] += 1
                            pnl = current_price - trade['entry']
                            trade['exit_price'] = current_price
                            trade['exit_time'] = current_time_str
                            trade['pnl'] = pnl
                            trade['status'] = 'Early Cut'
                            record_to_monthly_ledger(trade)

                            send_telegram_alert(format_telegram_card(trade))
                            active_trades["NIFTY 50"] = None
                            save_backup_state(active_trades)
                            continue

                        # Reversal Profit Lock
                        if trade.get('max_gain', 0) >= 30 and gain <= 10:
                            trade_stats['target_hits'] += 1
                            pnl = current_price - trade['entry']
                            trade['exit_price'] = current_price
                            trade['exit_time'] = current_time_str
                            trade['pnl'] = pnl
                            trade['status'] = 'Reversal Profit Lock'
                            record_to_monthly_ledger(trade)

                            send_telegram_alert(format_telegram_card(trade))
                            active_trades["NIFTY 50"] = None
                            save_backup_state(active_trades)
                            continue

                        # SL Hit
                        if current_price <= trade['sl']:
                            trade_stats['sl_hits'] += 1
                            pnl = current_price - trade['entry']
                            trade['sl_hit'] = True
                            trade['sl_time'] = current_time_str
                            trade['exit_price'] = current_price
                            trade['exit_time'] = current_time_str
                            trade['pnl'] = pnl
                            trade['status'] = 'Target 1 & Exit' if trade.get('t1_hit') else 'SL Hit'
                            record_to_monthly_ledger(trade)

                            if not trade.get('t1_hit'):
                                send_telegram_alert(format_telegram_card(trade))

                            active_trades["NIFTY 50"] = None
                            save_backup_state(active_trades)
                            continue

                        # T1 Hit
                        if not trade.get('t1_hit') and current_price >= trade['t1']:
                            trade['t1_hit'] = True
                            trade['t1_time'] = current_time_str
                            trade['sl'] = trade['entry']
                            trade_stats['target_hits'] += 1
                            save_backup_state(active_trades)
                            send_telegram_alert(
                                f"🎯 TARGET 1 ACHIEVED!\n\n"
                                f"⚡ Strategy: {STRATEGY_DISPLAY_NAME}\n"
                                f"📅 Date: {today_date_str}\n"
                                f"📍 Index: NIFTY 50 (BUY)\n"
                                f"💵 Spot: {current_price:.2f} | T1: {trade['t1']:.2f}\n"
                                f"⏰ Time: {current_time_str}\n"
                                f"🛡️ Action: Move SL to Entry ({trade['entry']:.2f}) - Zero Risk Active!"
                            )

                        # T2 Hit
                        if trade.get('t1_hit') and not trade.get('t2_hit') and current_price >= trade['t2']:
                            trade['t2_hit'] = True
                            trade['t2_time'] = current_time_str
                            trade['sl'] = trade['t1']
                            trade_stats['target_hits'] += 1
                            save_backup_state(active_trades)
                            send_telegram_alert(
                                f"🎯🎯 TARGET 2 ACHIEVED!\n\n"
                                f"⚡ Strategy: {STRATEGY_DISPLAY_NAME}\n"
                                f"📅 Date: {today_date_str}\n"
                                f"📍 Index: NIFTY 50 (BUY)\n"
                                f"💵 Spot: {current_price:.2f} | T2: {trade['t2']:.2f}\n"
                                f"⏰ Time: {current_time_str}\n"
                                f"🛡️ Action: Trail SL to Target 1 ({trade['t1']:.2f})!"
                            )

                        # T3 Hit
                        if trade.get('t2_hit') and current_price >= trade['t3']:
                            trade['t3_hit'] = True
                            trade['t3_time'] = current_time_str
                            trade_stats['target_hits'] += 1
                            pnl = current_price - trade['entry']
                            trade['exit_price'] = current_price
                            trade['exit_time'] = current_time_str
                            trade['pnl'] = pnl
                            trade['status'] = 'Target 3 Achieved'
                            record_to_monthly_ledger(trade)

                            send_telegram_alert(format_telegram_card(trade))
                            active_trades["NIFTY 50"] = None
                            save_backup_state(active_trades)
                            continue

                    # SELL POSITION MONITORING
                    elif trade['type'] == 'SELL':
                        gain = trade['entry'] - current_price
                        if gain > trade.get('max_gain', 0): trade['max_gain'] = gain

                        # Early Cut
                        if not trade.get('t1_hit') and current_price > trade['cut_level']:
                            trade_stats['early_cuts'] += 1
                            pnl = trade['entry'] - current_price
                            trade['exit_price'] = current_price
                            trade['exit_time'] = current_time_str
                            trade['pnl'] = pnl
                            trade['status'] = 'Early Cut'
                            record_to_monthly_ledger(trade)

                            send_telegram_alert(format_telegram_card(trade))
                            active_trades["NIFTY 50"] = None
                            save_backup_state(active_trades)
                            continue

                        # Reversal Profit Lock
                        if trade.get('max_gain', 0) >= 30 and gain <= 10:
                            trade_stats['target_hits'] += 1
                            pnl = trade['entry'] - current_price
                            trade['exit_price'] = current_price
                            trade['exit_time'] = current_time_str
                            trade['pnl'] = pnl
                            trade['status'] = 'Reversal Profit Lock'
                            record_to_monthly_ledger(trade)

                            send_telegram_alert(format_telegram_card(trade))
                            active_trades["NIFTY 50"] = None
                            save_backup_state(active_trades)
                            continue

                        # SL Hit
                        if current_price >= trade['sl']:
                            trade_stats['sl_hits'] += 1
                            pnl = trade['entry'] - current_price
                            trade['sl_hit'] = True
                            trade['sl_time'] = current_time_str
                            trade['exit_price'] = current_price
                            trade['exit_time'] = current_time_str
                            trade['pnl'] = pnl
                            trade['status'] = 'Target 1 & Exit' if trade.get('t1_hit') else 'SL Hit'
                            record_to_monthly_ledger(trade)

                            if not trade.get('t1_hit'):
                                send_telegram_alert(format_telegram_card(trade))

                            active_trades["NIFTY 50"] = None
                            save_backup_state(active_trades)
                            continue

                        # T1 Hit
                        if not trade.get('t1_hit') and current_price <= trade['t1']:
                            trade['t1_hit'] = True
                            trade['t1_time'] = current_time_str
                            trade['sl'] = trade['entry']
                            trade_stats['target_hits'] += 1
                            save_backup_state(active_trades)
                            send_telegram_alert(
                                f"🎯 TARGET 1 ACHIEVED!\n\n"
                                f"⚡ Strategy: {STRATEGY_DISPLAY_NAME}\n"
                                f"📅 Date: {today_date_str}\n"
                                f"📍 Index: NIFTY 50 (SELL)\n"
                                f"💵 Spot: {current_price:.2f} | T1: {trade['t1']:.2f}\n"
                                f"⏰ Time: {current_time_str}\n"
                                f"🛡️ Action: Move SL to Entry ({trade['entry']:.2f}) - Zero Risk Active!"
                            )

                        # T2 Hit
                        if trade.get('t1_hit') and not trade.get('t2_hit') and current_price <= trade['t2']:
                            trade['t2_hit'] = True
                            trade['t2_time'] = current_time_str
                            trade['sl'] = trade['t1']
                            trade_stats['target_hits'] += 1
                            save_backup_state(active_trades)
                            send_telegram_alert(
                                f"🎯🎯 TARGET 2 ACHIEVED!\n\n"
                                f"⚡ Strategy: {STRATEGY_DISPLAY_NAME}\n"
                                f"📅 Date: {today_date_str}\n"
                                f"📍 Index: NIFTY 50 (SELL)\n"
                                f"💵 Spot: {current_price:.2f} | T2: {trade['t2']:.2f}\n"
                                f"⏰ Time: {current_time_str}\n"
                                f"🛡️ Action: Trail SL to Target 1 ({trade['t1']:.2f})!"
                            )

                        # T3 Hit
                        if trade.get('t2_hit') and current_price <= trade['t3']:
                            trade['t3_hit'] = True
                            trade['t3_time'] = current_time_str
                            trade_stats['target_hits'] += 1
                            pnl = trade['entry'] - current_price
                            trade['exit_price'] = current_price
                            trade['exit_time'] = current_time_str
                            trade['pnl'] = pnl
                            trade['status'] = 'Target 3 Achieved'
                            record_to_monthly_ledger(trade)

                            send_telegram_alert(format_telegram_card(trade))
                            active_trades["NIFTY 50"] = None
                            save_backup_state(active_trades)
                            continue

                # --- ZERO-DELAY ENTRY DETECTOR ---
                if can_take_trades and active_trades["NIFTY 50"] is None and algo_levels is not None:
                    buy_trigger = algo_levels['Buy_Trigger']
                    sell_trigger = algo_levels['Sell_Trigger']
                    key_res = algo_levels['Key_Res']
                    key_sup = algo_levels['Key_Sup']

                    # BUY SIGNAL
                    if current_price > buy_trigger:
                        sl = round(key_res, 2)
                        risk = round(current_price - sl, 2)
                        if risk < 15: risk = 25.0; sl = round(current_price - 25.0, 2)

                        t1 = round(current_price + (risk * 1.0), 2)
                        t2 = round(current_price + (risk * 1.5), 2)
                        t3 = round(current_price + (risk * 2.5), 2)

                        active_trades["NIFTY 50"] = {
                            'date': today_date_str,
                            'index': "NIFTY 50",
                            'type': 'BUY',
                            'entry': current_price,
                            'entry_time': current_time_str,
                            'sl': sl,
                            'sl_hit': False,
                            'sl_time': None,
                            't1': t1,
                            't1_hit': False,
                            't1_time': None,
                            't2': t2,
                            't2_hit': False,
                            't2_time': None,
                            't3': t3,
                            't3_hit': False,
                            't3_time': None,
                            'cut_level': key_res,
                            'max_gain': 0.0
                        }
                        save_backup_state(active_trades)
                        trade_stats['total_signals'] += 1

                        opt = get_option_recommendations(current_price, "BUY", risk)
                        send_telegram_alert(
                            f"🟢 NIFTY 50 BUY SIGNAL\n\n"
                            f"⚡ Strategy: {STRATEGY_DISPLAY_NAME}\n"
                            f"📅 Date: {today_date_str}\n"
                            f"⏰ Time: {current_time_str} IST\n"
                            f"💵 Spot Entry: {current_price:.2f} | SL: {sl:.2f}\n\n"
                            f"🛒 OPTION BUYERS (CALL):\n"
                            f"• Strike: {opt['buyer_strike']}\n"
                            f"• Entry Approx: ₹{opt['buyer_entry']:.1f}\n"
                            f"• Targets: T1: ₹{opt['buyer_t1']:.1f} | T2: ₹{opt['buyer_t2']:.1f} | T3: ₹{opt['buyer_t3']:.1f}\n\n"
                            f"🛡️ OPTION SELLERS (PE):\n"
                            f"• Sell ATM: {opt['seller_strike']} @ ₹{opt['seller_entry']:.1f}\n"
                            f"• Safe OTM: {opt['safe_seller_strike']} @ ₹{opt['safe_seller_entry']:.1f}\n\n"
                            f"🎯 Spot Targets: T1: {t1:.2f} | T2: {t2:.2f} | T3: {t3:.2f}"
                        )

                    # SELL SIGNAL
                    elif current_price < sell_trigger:
                        sl = round(key_sup, 2)
                        risk = round(sl - current_price, 2)
                        if risk < 15: risk = 25.0; sl = round(current_price + 25.0, 2)

                        t1 = round(current_price - (risk * 1.0), 2)
                        t2 = round(current_price - (risk * 1.5), 2)
                        t3 = round(current_price - (risk * 2.5), 2)

                        active_trades["NIFTY 50"] = {
                            'date': today_date_str,
                            'index': "NIFTY 50",
                            'type': 'SELL',
                            'entry': current_price,
                            'entry_time': current_time_str,
                            'sl': sl,
                            'sl_hit': False,
                            'sl_time': None,
                            't1': t1,
                            't1_hit': False,
                            't1_time': None,
                            't2': t2,
                            't2_hit': False,
                            't2_time': None,
                            't3': t3,
                            't3_hit': False,
                            't3_time': None,
                            'cut_level': key_sup,
                            'max_gain': 0.0
                        }
                        save_backup_state(active_trades)
                        trade_stats['total_signals'] += 1

                        opt = get_option_recommendations(current_price, "SELL", risk)
                        send_telegram_alert(
                            f"🔴 NIFTY 50 SELL SIGNAL\n\n"
                            f"⚡ Strategy: {STRATEGY_DISPLAY_NAME}\n"
                            f"📅 Date: {today_date_str}\n"
                            f"⏰ Time: {current_time_str} IST\n"
                            f"💵 Spot Entry: {current_price:.2f} | SL: {sl:.2f}\n\n"
                            f"🛒 OPTION BUYERS (PUT):\n"
                            f"• Strike: {opt['buyer_strike']}\n"
                            f"• Entry Approx: ₹{opt['buyer_entry']:.1f}\n"
                            f"• Targets: T1: ₹{opt['buyer_t1']:.1f} | T2: ₹{opt['buyer_t2']:.1f} | T3: ₹{opt['buyer_t3']:.1f}\n\n"
                            f"🛡️ OPTION SELLERS (CE):\n"
                            f"• Sell ATM: {opt['seller_strike']} @ ₹{opt['seller_entry']:.1f}\n"
                            f"• Safe OTM: {opt['safe_seller_strike']} @ ₹{opt['safe_seller_entry']:.1f}\n\n"
                            f"🎯 Spot Targets: T1: {t1:.2f} | T2: {t2:.2f} | T3: {t3:.2f}"
                        )

                # --- HOURLY PULSE ---
                if now.minute == 0 and now.hour != last_heartbeat_hour and (9 <= now.hour <= 15):
                    last_heartbeat_hour = now.hour
                    prc = current_price
                    prv = prev_close if prev_close else prc
                    diff = prc - prv
                    pct = (diff / prv) * 100 if prv != 0 else 0.0
                    send_telegram_alert(f"💓 HOURLY STATUS ALERT\n⏰ Time: {current_time_str} IST\n\n• NIFTY 50: {prc:.2f} ({diff:+.2f} | {pct:+.2f}%)\n")

        # 1-second interval for instant zero-delay triggers
        time.sleep(1)

    except Exception as loop_err:
        print(f"Engine Warning: {loop_err}")
        time.sleep(2)
