import os
import time
import requests
import json
import smtplib
import subprocess
import threading
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from datetime import datetime
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

# --- TELEGRAM CONFIGURATION (SAS TRADING LAB) ---
TELEGRAM_BOT_TOKEN = "8999213661:AAEfHcQzRZ2-ZI4bbfq8UcuGA48ihzQKchA"
TELEGRAM_CHAT_IDS = ["-1004417570442", "@sastradinglab"]

tele_session = requests.Session()

def send_telegram_alert(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    for chat_id in TELEGRAM_CHAT_IDS:
        try:
            payload = {"chat_id": chat_id, "text": msg}
            res = tele_session.post(url, json=payload, timeout=6).json()
            if res.get("ok"):
                break
        except Exception as e:
            print(f"Telegram Alert Error ({chat_id}): {e}")

def send_telegram_document(file_path, caption=""):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendDocument"
    for chat_id in TELEGRAM_CHAT_IDS:
        try:
            with open(file_path, 'rb') as doc:
                files = {'document': doc}
                data = {'chat_id': chat_id, 'caption': caption}
                res = requests.post(url, data=data, files=files, timeout=20).json()
                if res.get("ok"):
                    break
        except Exception as e:
            print(f"Telegram Doc Delivery Error ({chat_id}): {e}")

# --- GMAIL CONFIGURATION ---
SENDER_EMAIL = "shinos99@gmail.com"
SENDER_APP_PASSWORD = "xufefwfphwsomsnu"
RECEIVER_EMAILS = ["shinos99@gmail.com"]

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
        print("PDF successfully emailed to shinos99@gmail.com.")
    except Exception as e:
        print(f"Email Dispatch Warning: {e}")

# --- WELCOME MESSAGE LISTENER FOR CHANNEL ---
WELCOME_MESSAGE = (
    "👋 Welcome to SAS TRADING LAB!\n\n"
    "Get automated real-time algorithmic signals and daily target/stop-loss updates for NIFTY 50 & BANK NIFTY indices.\n\n"
    "🔹 Real-Time Breakout Signals (CE / PE)\n"
    "🔹 Option Buying & Selling Strike Guidance\n"
    "🔹 Strict Risk Management & Trailing SL\n"
    "🔹 Daily & Expiry PDF Performance Reports\n\n"
    "⚠️ LEGAL DISCLAIMER:\n"
    "All information shared in this channel is strictly for educational and analytical purposes only. We are not SEBI-registered financial advisors."
)

def poll_new_channel_members():
    last_update_id = 0
    while True:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
            params = {"offset": last_update_id + 1, "timeout": 20, "allowed_updates": ["chat_member", "chat_join_request"]}
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
                    elif "chat_join_request" in update:
                        cjr = update["chat_join_request"]
                        user_id = cjr.get("from", {}).get("id")
                        c_id = cjr.get("chat", {}).get("id")
                        if user_id and c_id:
                            tele_session.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/approveChatJoinRequest", json={"chat_id": c_id, "user_id": user_id}, timeout=6)
                            tele_session.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage", json={"chat_id": user_id, "text": WELCOME_MESSAGE}, timeout=6)
        except Exception:
            time.sleep(5)
        time.sleep(2)

threading.Thread(target=poll_new_channel_members, daemon=True).start()

# --- WEEKEND CHECK ---
today_weekday = datetime.now(IST).weekday()
if today_weekday in [5, 6]:
    day_name = "Saturday" if today_weekday == 5 else "Sunday"
    send_telegram_alert(
        f"🏖️ WEEKEND MARKET HOLIDAY ({day_name})!\n\n"
        "• Status: Market is Closed.\n"
        "• Scanner resumes Monday at 09:00 AM IST."
    )
    exit(0)

# --- GITHUB REPO AUTO-SYNC ---
BACKUP_FILE = "daily_active_trades.json"
MONTHLY_LEDGER_FILE = "monthly_trades_ledger.json"

def push_backup_to_github():
    try:
        subprocess.run(["git", "config", "--global", "user.name", "github-actions[bot]"], check=False)
        subprocess.run(["git", "config", "--global", "user.email", "github-actions[bot]@users.noreply.github.com"], check=False)
        subprocess.run(["git", "pull", "--rebase", "origin", "main"], check=False)
        subprocess.run(["git", "add", BACKUP_FILE, MONTHLY_LEDGER_FILE], check=False)
        subprocess.run(["git", "commit", "-m", "Auto-sync trades backup [skip ci]"], check=False)
        subprocess.run(["git", "push", "origin", "main"], check=False)
        print("Backup successfully synced to GitHub repository.")
    except Exception as e:
        print(f"Git auto-push note: {e}")

INDEX_WATCHLIST = ["NIFTY 50", "NIFTY BANK"]
YF_TICKERS = {"NIFTY 50": "^NSEI", "NIFTY BANK": "^NSEBANK"}
STRATEGY_DISPLAY_NAME = "MOMENTUM SPIKE"

trade_stats = {"total_signals": 0, "target_hits": 0, "sl_hits": 0, "early_cuts": 0}
prev_close_dict = {}
camarilla_levels = {}
pivots_alert_sent = False
hero_zero_sent = False
last_heartbeat_hour = -1

def load_backup_state():
    default_state = {idx: None for idx in INDEX_WATCHLIST}
    if os.path.exists(BACKUP_FILE):
        try:
            with open(BACKUP_FILE, 'r') as f:
                data = json.load(f)
                for idx in INDEX_WATCHLIST:
                    if idx not in data:
                        data[idx] = None
                return data
        except Exception as err:
            print(f"Backup Load Error: {err}")
    return default_state

def save_backup_state(state):
    try:
        with open(BACKUP_FILE, 'w') as f:
            json.dump(state, f, indent=4)
        push_backup_to_github()
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
        push_backup_to_github()
    except Exception as e:
        print(f"Ledger save warning: {e}")

# --- CAMARILLA PIVOT CALCULATION ---
def calculate_camarilla_pivots(index_name):
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

            r4 = close + (diff * 1.1 / 2.0)
            r3 = close + (diff * 1.1 / 4.0)
            r2 = close + (diff * 1.1 / 6.0)
            r1 = close + (diff * 1.1 / 12.0)

            s1 = close - (diff * 1.1 / 12.0)
            s2 = close - (diff * 1.1 / 6.0)
            s3 = close - (diff * 1.1 / 4.0)
            s4 = close - (diff * 1.1 / 2.0)

            return {
                "R4": round(r4, 2), "R3": round(r3, 2), "R2": round(r2, 2), "R1": round(r1, 2),
                "S1": round(s1, 2), "S2": round(s2, 2), "S3": round(s3, 2), "S4": round(s4, 2),
                "Prev_Close": round(close, 2)
            }
    except Exception as e:
        print(f"Pivot calc warning ({index_name}): {e}")
    return None

for idx in INDEX_WATCHLIST:
    camarilla_levels[idx] = calculate_camarilla_pivots(idx)

active_trades = load_backup_state()

def get_option_recommendations(index_name, spot_price, signal_direction, spot_risk):
    step = 50 if index_name == "NIFTY 50" else 100
    atm_strike = int(round(spot_price / step) * step)
    delta = 0.50

    base_atm_price = 110.0 if index_name == "NIFTY 50" else 260.0
    otm_seller_price = 70.0 if index_name == "NIFTY 50" else 170.0

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

# --- PDF ENGINE ---
def generate_detailed_pdf_report(filename, title_text, subtitle_text, logs_to_print):
    doc = SimpleDocTemplate(filename, pagesize=landscape(letter), rightMargin=15, leftMargin=15, topMargin=20, bottomMargin=20)
    styles = getSampleStyleSheet()
    elements = []

    title_style = ParagraphStyle('RepTitle', parent=styles['Heading1'], fontSize=14, leading=17, textColor=colors.HexColor("#1A365D"), alignment=1)
    elements.append(Paragraph(f"{title_text} - MOMENTUM SPIKE", title_style))
    elements.append(Paragraph(f"Timeline: {subtitle_text} | Total Trades: {len(logs_to_print)}", styles['Normal']))
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
            str(idx), log.get('date', '-'), f"{log.get('index', '')}\n({log.get('type', '')})",
            f"{log.get('entry', 0.0):.2f}\n({log.get('entry_time', '')})",
            t1_val, t2_val, t3_val, sl_val, pnl_val, log.get('status', '-')
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
        "⚡ MOMENTUM SPIKE\n"
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

# --- 09:00 AM STARTUP SCANNER ALERT ---
send_telegram_alert(
    "🚀 NIFTY & BANK NIFTY SCANNER ACTIVATED\n\n"
    "⚡ MOMENTUM SPIKE\n"
    "🕒 Trading Window: 09:30 AM - 03:20 PM IST\n"
    "🛡️ Protection: Strict SL + Early Cut + Reversal Lock\n"
    "🎯 Target Engine: T1 Achieved locks profit (No SL hit after T1)\n"
    "📑 Reports: Daily & Expiry-to-Expiry PDF Dispatched to Channel"
)

def get_live_index_data():
    try:
        return capital_market.market_watch_all_indices()
    except Exception as e:
        print(f"NSE Live Fetch Note: {e}")
        return None

# --- MAIN MONITORING ENGINE ---
while True:
    try:
        now = datetime.now(IST)
        current_time = now.time()
        current_time_str = now.strftime('%I:%M:%S %p')
        today_date_str = now.strftime('%d-%b-%Y')

        pivot_alert_time = datetime.strptime("09:05", "%H:%M").time()
        start_trade_time = datetime.strptime("09:30", "%H:%M").time()
        hero_zero_time = datetime.strptime("13:15", "%H:%M").time()
        end_trade_time = datetime.strptime("15:20", "%H:%M").time()
        shutdown_time = datetime.strptime("15:40", "%H:%M").time()

        # 1. 09:05 AM PIVOTS ALERT
        if not pivots_alert_sent and current_time >= pivot_alert_time:
            pivots_alert_sent = True
            p_msg = f"📐 DAILY CAMARILLA PIVOT LEVELS (09:05 AM IST)\n📅 Date: {today_date_str}\n⚡ MOMENTUM SPIKE\n\n"
            for idx in INDEX_WATCHLIST:
                lvl = camarilla_levels.get(idx)
                if lvl:
                    p_msg += (
                        f"🔹 {idx} (Prev Close: {lvl['Prev_Close']})\n"
                        f"• R4 (Breakout Buy): {lvl['R4']:.2f}\n"
                        f"• R3: {lvl['R3']:.2f} | R2: {lvl['R2']:.2f} | R1: {lvl['R1']:.2f}\n"
                        f"• S1: {lvl['S1']:.2f} | S2: {lvl['S2']:.2f} | S3: {lvl['S3']:.2f}\n"
                        f"• S4 (Breakdown Sell): {lvl['S4']:.2f}\n\n"
                    )
            send_telegram_alert(p_msg)

        can_take_trades = (start_trade_time <= current_time < end_trade_time)
        is_market_closing = (current_time >= end_trade_time)

        # 2. 03:40 PM DAILY DISPATCH
        if current_time >= shutdown_time:
            all_ledger_records = load_monthly_ledger()
            today_records = [l for l in all_ledger_records if l.get('date') == today_date_str]

            total = trade_stats['total_signals']
            wins = trade_stats['target_hits']
            win_rate = (wins / total * 100) if total > 0 else 0.0

            summary = (
                f"📊 MARKET CLOSED (DAILY REPORT)\n\n"
                "⚡ MOMENTUM SPIKE\n"
                f"📅 Date: {today_date_str}\n\n"
                f"• Today's Signals Closed: {len(today_records)}\n"
                f"• Targets / Locks: {wins}\n"
                f"• Stop Losses Hit: {trade_stats['sl_hits']}\n"
                f"• Early Cuts: {trade_stats['early_cuts']}\n"
                f"🏆 Win Rate: {win_rate:.1f}%\n"
                f"📚 Total Cycle Trades: {len(all_ledger_records)}\n\n"
                f"Dispatching reports to shinos99@gmail.com & Channel..."
            )
            send_telegram_alert(summary)

            pdf_daily = f"Daily_Report_{today_date_str}.pdf"
            generate_detailed_pdf_report(pdf_daily, "DAILY TRADE PERFORMANCE", today_date_str, today_records)
            send_telegram_document(pdf_daily, caption=f"📄 Daily Detailed Report ({today_date_str})")
            send_email_with_pdf(pdf_daily, f"Daily Trading Report - {today_date_str}", summary)

            print("Daily market session finished. Bot exiting safely.")
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

                    # 3. HERO-ZERO ALERT (01:15 PM)
                    if not hero_zero_sent and current_time >= hero_zero_time:
                        step = 50 if index_name == "NIFTY 50" else 100
                        atm_k = int(round(current_price / step) * step)
                        hz_msg = (
                            f"🔥 HERO-ZERO SETUP (01:15 PM IST)\n\n"
                            f"📍 Index: {index_name} (Spot: {current_price:.2f})\n"
                            f"🎯 Focus Strikes (Low Premium ₹15 - ₹35):\n"
                            f"• Call Option: {atm_k + step} CE\n"
                            f"• Put Option: {atm_k - step} PE\n\n"
                            "⚡ MOMENTUM SPIKE Breakout!"
                        )
                        send_telegram_alert(hz_msg)
                        hero_zero_sent = True

                    # 4. ACTIVE POSITION TRACKING
                    trade = active_trades[index_name]
                    if trade is not None:
                        if is_market_closing:
                            pnl = current_price - trade['entry'] if trade['type'] == 'BUY' else trade['entry'] - current_price
                            trade['exit_price'] = current_price
                            trade['exit_time'] = current_time_str
                            trade['pnl'] = pnl
                            trade['status'] = 'Auto-Exit (03:20 PM)'
                            record_to_monthly_ledger(trade)

                            send_telegram_alert(format_telegram_card(trade))
                            active_trades[index_name] = None
                            save_backup_state(active_trades)
                            continue

                        # BUY ORDER MANAGEMENT
                        if trade['type'] == 'BUY':
                            gain = current_price - trade['entry']
                            if gain > trade.get('max_gain', 0):
                                trade['max_gain'] = gain

                            if not trade.get('t1_hit') and current_price < trade['cut_level']:
                                trade_stats['early_cuts'] += 1
                                pnl = current_price - trade['entry']
                                trade['exit_price'] = current_price
                                trade['exit_time'] = current_time_str
                                trade['pnl'] = pnl
                                trade['status'] = 'Early Cut (R3)'
                                record_to_monthly_ledger(trade)

                                send_telegram_alert(format_telegram_card(trade))
                                active_trades[index_name] = None
                                save_backup_state(active_trades)
                                continue

                            if trade.get('max_gain', 0) >= 30 and gain <= 10:
                                trade_stats['target_hits'] += 1
                                pnl = current_price - trade['entry']
                                trade['exit_price'] = current_price
                                trade['exit_time'] = current_time_str
                                trade['pnl'] = pnl
                                trade['status'] = 'Reversal Profit Lock'
                                record_to_monthly_ledger(trade)

                                send_telegram_alert(format_telegram_card(trade))
                                active_trades[index_name] = None
                                save_backup_state(active_trades)
                                continue

                            if current_price <= trade['sl']:
                                pnl = current_price - trade['entry']
                                trade['exit_price'] = current_price
                                trade['exit_time'] = current_time_str
                                trade['pnl'] = pnl

                                if trade.get('t1_hit'):
                                    trade['status'] = 'T1 Achieved & Exit'
                                    record_to_monthly_ledger(trade)
                                else:
                                    trade_stats['sl_hits'] += 1
                                    trade['sl_hit'] = True
                                    trade['sl_time'] = current_time_str
                                    trade['status'] = 'SL Hit'
                                    record_to_monthly_ledger(trade)
                                    send_telegram_alert(
                                        f"🛑 STOP LOSS HIT!\n\n"
                                        "⚡ MOMENTUM SPIKE\n"
                                        f"📍 Index: {index_name} (BUY)\n"
                                        f"💵 Exit Price: {current_price:.2f}\n"
                                        f"⏰ Time: {current_time_str}"
                                    )

                                active_trades[index_name] = None
                                save_backup_state(active_trades)
                                continue

                            if not trade.get('t1_hit') and current_price >= trade['t1']:
                                trade['t1_hit'] = True
                                trade['t1_time'] = current_time_str
                                trade['sl'] = trade['entry']
                                trade_stats['target_hits'] += 1
                                save_backup_state(active_trades)
                                send_telegram_alert(
                                    f"🎯 TARGET 1 HIT!\n\n"
                                    "⚡ MOMENTUM SPIKE\n"
                                    f"📍 Index: {index_name} (BUY)\n"
                                    f"🎯 Target Price: {trade['t1']:.2f}\n"
                                    f"💵 Current Spot: {current_price:.2f}\n"
                                    f"⏰ Time: {current_time_str}\n"
                                    f"🛡️ Action: Move SL to Cost ({trade['entry']:.2f})!"
                                )

                            if trade.get('t1_hit') and not trade.get('t2_hit') and current_price >= trade['t2']:
                                trade['t2_hit'] = True
                                trade['t2_time'] = current_time_str
                                trade['sl'] = trade['t1']
                                trade_stats['target_hits'] += 1
                                save_backup_state(active_trades)
                                send_telegram_alert(
                                    f"🎯🎯 TARGET 2 HIT!\n\n"
                                    "⚡ MOMENTUM SPIKE\n"
                                    f"📍 Index: {index_name} (BUY)\n"
                                    f"🎯 Target Price: {trade['t2']:.2f}\n"
                                    f"💵 Current Spot: {current_price:.2f}\n"
                                    f"⏰ Time: {current_time_str}\n"
                                    f"🛡️ Action: Trail SL to Target 1 ({trade['t1']:.2f})!"
                                )

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

                                send_telegram_alert(
                                    f"🚀🚀🚀 TARGET 3 HIT (JACKPOT)!\n\n"
                                    "⚡ MOMENTUM SPIKE\n"
                                    f"📍 Index: {index_name} (BUY)\n"
                                    f"🎯 Target Price: {trade['t3']:.2f}\n"
                                    f"💵 Exit: {current_price:.2f} (+{pnl:.2f} Pts)\n"
                                    f"⏰ Time: {current_time_str}\n"
                                    f"🏁 Status: Trade Successfully Closed!"
                                )
                                active_trades[index_name] = None
                                save_backup_state(active_trades)
                                continue

                        # SELL ORDER MANAGEMENT
                        elif trade['type'] == 'SELL':
                            gain = trade['entry'] - current_price
                            if gain > trade.get('max_gain', 0):
                                trade['max_gain'] = gain

                            if not trade.get('t1_hit') and current_price > trade['cut_level']:
                                trade_stats['early_cuts'] += 1
                                pnl = trade['entry'] - current_price
                                trade['exit_price'] = current_price
                                trade['exit_time'] = current_time_str
                                trade['pnl'] = pnl
                                trade['status'] = 'Early Cut (S3)'
                                record_to_monthly_ledger(trade)

                                send_telegram_alert(format_telegram_card(trade))
                                active_trades[index_name] = None
                                save_backup_state(active_trades)
                                continue

                            if trade.get('max_gain', 0) >= 30 and gain <= 10:
                                trade_stats['target_hits'] += 1
                                pnl = trade['entry'] - current_price
                                trade['exit_price'] = current_price
                                trade['exit_time'] = current_time_str
                                trade['pnl'] = pnl
                                trade['status'] = 'Reversal Profit Lock'
                                record_to_monthly_ledger(trade)

                                send_telegram_alert(format_telegram_card(trade))
                                active_trades[index_name] = None
                                save_backup_state(active_trades)
                                continue

                            if current_price >= trade['sl']:
                                pnl = trade['entry'] - current_price
                                trade['exit_price'] = current_price
                                trade['exit_time'] = current_time_str
                                trade['pnl'] = pnl

                                if trade.get('t1_hit'):
                                    trade['status'] = 'T1 Achieved & Exit'
                                    record_to_monthly_ledger(trade)
                                else:
                                    trade_stats['sl_hits'] += 1
                                    trade['sl_hit'] = True
                                    trade['sl_time'] = current_time_str
                                    trade['status'] = 'SL Hit'
                                    record_to_monthly_ledger(trade)
                                    send_telegram_alert(
                                        f"🛑 STOP LOSS HIT!\n\n"
                                        "⚡ MOMENTUM SPIKE\n"
                                        f"📍 Index: {index_name} (SELL)\n"
                                        f"💵 Exit Price: {current_price:.2f}\n"
                                        f"⏰ Time: {current_time_str}"
                                    )

                                active_trades[index_name] = None
                                save_backup_state(active_trades)
                                continue

                            if not trade.get('t1_hit') and current_price <= trade['t1']:
                                trade['t1_hit'] = True
                                trade['t1_time'] = current_time_str
                                trade['sl'] = trade['entry']
                                trade_stats['target_hits'] += 1
                                save_backup_state(active_trades)
                                send_telegram_alert(
                                    f"🎯 TARGET 1 HIT!\n\n"
                                    "⚡ MOMENTUM SPIKE\n"
                                    f"📍 Index: {index_name} (SELL)\n"
                                    f"🎯 Target Price: {trade['t1']:.2f}\n"
                                    f"💵 Current Spot: {current_price:.2f}\n"
                                    f"⏰ Time: {current_time_str}\n"
                                    f"🛡️ Action: Move SL to Cost ({trade['entry']:.2f})!"
                                )

                            if trade.get('t1_hit') and not trade.get('t2_hit') and current_price <= trade['t2']:
                                trade['t2_hit'] = True
                                trade['t2_time'] = current_time_str
                                trade['sl'] = trade['t1']
                                trade_stats['target_hits'] += 1
                                save_backup_state(active_trades)
                                send_telegram_alert(
                                    f"🎯🎯 TARGET 2 HIT!\n\n"
                                    "⚡ MOMENTUM SPIKE\n"
                                    f"📍 Index: {index_name} (SELL)\n"
                                    f"🎯 Target Price: {trade['t2']:.2f}\n"
                                    f"💵 Current Spot: {current_price:.2f}\n"
                                    f"⏰ Time: {current_time_str}\n"
                                    f"🛡️ Action: Trail SL to Target 1 ({trade['t1']:.2f})!"
                                )

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

                                send_telegram_alert(
                                    f"🚀🚀🚀 TARGET 3 HIT (JACKPOT)!\n\n"
                                    "⚡ MOMENTUM SPIKE\n"
                                    f"📍 Index: {index_name} (SELL)\n"
                                    f"🎯 Target Price: {trade['t3']:.2f}\n"
                                    f"💵 Exit: {current_price:.2f} (+{pnl:.2f} Pts)\n"
                                    f"⏰ Time: {current_time_str}\n"
                                    f"🏁 Status: Trade Successfully Closed!"
                                )
                                active_trades[index_name] = None
                                save_backup_state(active_trades)
                                continue

                    # 5. ZERO-DELAY BREAKOUT DETECTION
                    pivots = camarilla_levels.get(index_name)
                    if can_take_trades and active_trades[index_name] is None and pivots is not None:
                        r4 = pivots['R4']
                        s4 = pivots['S4']
                        r3 = pivots['R3']
                        s3 = pivots['S3']

                        if current_price > r4:
                            sl = round(r3, 2)
                            risk = round(current_price - sl, 2)
                            if risk < 15: risk = 25.0; sl = round(current_price - 25.0, 2)

                            t1 = round(current_price + (risk * 1.0), 2)
                            t2 = round(current_price + (risk * 1.5), 2)
                            t3 = round(current_price + (risk * 2.5), 2)

                            active_trades[index_name] = {
                                'date': today_date_str, 'index': index_name, 'type': 'BUY',
                                'entry': current_price, 'entry_time': current_time_str,
                                'sl': sl, 'sl_hit': False, 'sl_time': None,
                                't1': t1, 't1_hit': False, 't1_time': None,
                                't2': t2, 't2_hit': False, 't2_time': None,
                                't3': t3, 't3_hit': False, 't3_time': None,
                                'cut_level': r3, 'max_gain': 0.0
                            }
                            save_backup_state(active_trades)
                            trade_stats['total_signals'] += 1

                            opt = get_option_recommendations(index_name, current_price, "BUY", risk)
                            msg = (
                                f"🟢 {index_name} BUY SIGNAL\n\n"
                                "⚡ MOMENTUM SPIKE\n"
                                f"⏰ Time: {current_time_str} IST\n"
                                f"💵 Spot Entry: {current_price:.2f}\n"
                                f"🛑 Stop Loss: {sl:.2f}\n"
                                f"🎯 Spot Targets: T1: {t1:.2f} | T2: {t2:.2f} | T3: {t3:.2f}\n"
                                "━━━━━━━━━━━━━━━━━━━━━\n"
                                "🛒 OPTION BUYERS:\n"
                                f"• Strike: {opt['buyer_strike']}\n"
                                f"• Entry Approx: ₹{opt['buyer_entry']:.1f}\n"
                                f"• SL Approx: ₹{opt['buyer_sl']:.1f}\n"
                                f"• Targets: T1: ₹{opt['buyer_t1']:.1f} | T2: ₹{opt['buyer_t2']:.1f} | T3: ₹{opt['buyer_t3']:.1f}\n"
                                "━━━━━━━━━━━━━━━━━━━━━\n"
                                "💼 OPTION SELLERS:\n"
                                f"• Strike: {opt['seller_strike']}\n"
                                f"• Entry Approx: ₹{opt['seller_entry']:.1f}\n"
                                f"• SL: ₹{opt['seller_sl']:.1f} | Target: ₹{opt['seller_target']:.1f}\n"
                                f"• Safe Strike: {opt['safe_seller_strike']} (Approx: ₹{opt['safe_seller_entry']:.1f})"
                            )
                            send_telegram_alert(msg)

                        elif current_price < s4:
                            sl = round(s3, 2)
                            risk = round(sl - current_price, 2)
                            if risk < 15: risk = 25.0; sl = round(current_price + 25.0, 2)

                            t1 = round(current_price - (risk * 1.0), 2)
                            t2 = round(current_price - (risk * 1.5), 2)
                            t3 = round(current_price - (risk * 2.5), 2)

                            active_trades[index_name] = {
                                'date': today_date_str, 'index': index_name, 'type': 'SELL',
                                'entry': current_price, 'entry_time': current_time_str,
                                'sl': sl, 'sl_hit': False, 'sl_time': None,
                                't1': t1, 't1_hit': False, 't1_time': None,
                                't2': t2, 't2_hit': False, 't2_time': None,
                                't3': t3, 't3_hit': False, 't3_time': None,
                                'cut_level': s3, 'max_gain': 0.0
                            }
                            save_backup_state(active_trades)
                            trade_stats['total_signals'] += 1

                            opt = get_option_recommendations(index_name, current_price, "SELL", risk)
                            msg = (
                                f"🔴 {index_name} SELL SIGNAL\n\n"
                                "⚡ MOMENTUM SPIKE\n"
                                f"⏰ Time: {current_time_str} IST\n"
                                f"💵 Spot Entry: {current_price:.2f}\n"
                                f"🛑 Stop Loss: {sl:.2f}\n"
                                f"🎯 Spot Targets: T1: {t1:.2f} | T2: {t2:.2f} | T3: {t3:.2f}\n"
                                "━━━━━━━━━━━━━━━━━━━━━\n"
                                "🛒 OPTION BUYERS:\n"
                                f"• Strike: {opt['buyer_strike']}\n"
                                f"• Entry Approx: ₹{opt['buyer_entry']:.1f}\n"
                                f"• SL Approx: ₹{opt['buyer_sl']:.1f}\n"
                                f"• Targets: T1: ₹{opt['buyer_t1']:.1f} | T2: ₹{opt['buyer_t2']:.1f} | T3: ₹{opt['buyer_t3']:.1f}\n"
                                "━━━━━━━━━━━━━━━━━━━━━\n"
                                "💼 OPTION SELLERS:\n"
                                f"• Strike: {opt['seller_strike']}\n"
                                f"• Entry Approx: ₹{opt['seller_entry']:.1f}\n"
                                f"• SL: ₹{opt['seller_sl']:.1f} | Target: ₹{opt['seller_target']:.1f}\n"
                                f"• Safe Strike: {opt['safe_seller_strike']} (Approx: ₹{opt['safe_seller_entry']:.1f})"
                            )
                            send_telegram_alert(msg)

            # 6. HOURLY STATUS ALERT
            if now.minute == 0 and now.hour != last_heartbeat_hour and (9 <= now.hour <= 15):
                last_heartbeat_hour = now.hour
                hb_msg = f"💓 HOURLY STATUS ALERT\n⏰ Time: {current_time_str} IST\n📅 Date: {today_date_str}\n⚡ MOMENTUM SPIKE\n\n"
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
