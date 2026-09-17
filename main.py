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
from datetime import datetime
from zoneinfo import ZoneInfo
import pandas as pd
import yfinance as yf
from nselib import capital_market

from reportlab.lib.pagesizes import letter, landscape
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

# --- TIMEZONE CONFIGURATION ---
IST = ZoneInfo("Asia/Kolkata")

# --- TELEGRAM CONFIGURATION ---
TELEGRAM_BOT_TOKEN = "8999213661:AAHEZnM2kpGuxZknoUDsh91fNqafsNHo5RI"

# ചാനൽ ഐഡിയും നിങ്ങളുടെ വ്യക്തിഗത ഐഡിയും ഒരുമിച്ച് (രണ്ടിലേക്കും അലേർട്ടുകൾ എത്തും)
TELEGRAM_CHAT_IDS = ["-1004417570442", "6789591588"]

tele_session = requests.Session()

def send_telegram_alert(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    for chat_id in TELEGRAM_CHAT_IDS:
        try:
            payload = {"chat_id": chat_id, "text": msg}
            res = tele_session.post(url, json=payload, timeout=8).json()
            if not res.get("ok"):
                print(f"⚠️ Telegram Alert Delivery Error ({chat_id}): {res.get('description')}")
            else:
                print(f"✅ Alert sent successfully to {chat_id}")
        except Exception as e:
            print(f"Telegram Network Error ({chat_id}): {e}")

def send_telegram_document(file_path, caption=""):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendDocument"
    for chat_id in TELEGRAM_CHAT_IDS:
        try:
            with open(file_path, 'rb') as doc:
                files = {'document': doc}
                data = {'chat_id': chat_id, 'caption': caption}
                res = requests.post(url, data=data, files=files, timeout=25).json()
                if not res.get("ok"):
                    print(f"⚠️ PDF Error ({chat_id}): {res.get('description')}")
        except Exception as e:
            print(f"Telegram Doc Error ({chat_id}): {e}")

# --- IMMEDIATE WORKFLOW RUN ALERT ---
start_now = datetime.now(IST)
send_telegram_alert(
    "🟢 GITHUB WORKFLOW TRIGGERED!\n\n"
    "🚀 SAS Capital Market Algo Engine is RUNNING.\n"
    f"🕒 Time: {start_now.strftime('%I:%M:%S %p')} IST\n"
    f"📅 Date: {start_now.strftime('%d-%b-%Y')}\n"
    "📡 Channel & Admin Connection: Verified & Active ✅"
)

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

# --- WELCOME MESSAGE LISTENER ---
WELCOME_MESSAGE = (
    "👋 Welcome to SAS CAPITAL MARKET!\n\n"
    "📈 Automated Algo Tracking for Nifty & Bank Nifty.\n"
    "⚡ Live Momentum Spikes & Key Breakout Levels.\n"
    "📊 Daily Real-Time Performance Reports.\n\n"
    "📌 Please check the PINNED message for important Legal Disclaimers.\n"
    "(Educational & Analysis purpose only | Not SEBI Registered)"
)

def poll_telegram_events():
    last_update_id = 0
    while True:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
            params = {
                "offset": last_update_id + 1,
                "timeout": 15,
                "allowed_updates": ["chat_member", "chat_join_request"]
            }
            res = tele_session.get(url, params=params, timeout=20).json()
            if res.get("ok"):
                for update in res.get("result", []):
                    last_update_id = update["update_id"]

                    if "chat_join_request" in update:
                        cjr = update["chat_join_request"]
                        user_id = cjr.get("from", {}).get("id")
                        chat_id = cjr.get("chat", {}).get("id")
                        if user_id and chat_id:
                            tele_session.post(
                                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/approveChatJoinRequest",
                                json={"chat_id": chat_id, "user_id": user_id},
                                timeout=6
                            )
                            # ഉപയോക്താവിന്റെ DM-ലേക്കും നിങ്ങൾക്കും വെൽക്കം മെസ്സേജ് അയക്കുന്നു
                            tele_session.post(
                                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                                json={"chat_id": user_id, "text": WELCOME_MESSAGE},
                                timeout=6
                            )
                            tele_session.post(
                                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                                json={"chat_id": "6789591588", "text": f"👤 New Member Joined!\nUser ID: {user_id}\n\n{WELCOME_MESSAGE}"},
                                timeout=6
                            )
        except Exception:
            time.sleep(3)
        time.sleep(2)

threading.Thread(target=poll_telegram_events, daemon=True).start()

# --- WEEKEND PROTECTION ---
today_weekday = datetime.now(IST).weekday()
if today_weekday in [5, 6]:
    day_name = "Saturday" if today_weekday == 5 else "Sunday"
    send_telegram_alert(
        f"🏖️ WEEKEND MARKET HOLIDAY ({day_name})!\n\n"
        "• Status: Market is Closed.\n"
        "• Resumes Monday at 09:00 AM IST."
    )
    exit(0)

INDEX_WATCHLIST = ["NIFTY 50", "NIFTY BANK"]
YF_TICKERS = {"NIFTY 50": "^NSEI", "NIFTY BANK": "^NSEBANK"}
BACKUP_FILE = "active_trades_momentum.json"
MONTHLY_LEDGER_FILE = "monthly_trades_ledger.json"
STRATEGY_DISPLAY_NAME = "MOMENTUM SPIKE"

trade_stats = {"total_signals": 0, "target_hits": 0, "sl_hits": 0, "early_cuts": 0}
prev_close_dict = {}
camarilla_levels = {}
pivots_alert_sent = False
hero_zero_sent = False
last_heartbeat_hour = -1

# --- PERSISTENCE HELPERS ---
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
            s3 = close - (diff * 1.1 / 4.0)
            s4 = close - (diff * 1.1 / 2.0)

            return {
                "R4": round(r4, 2), "R3": round(r3, 2),
                "S3": round(s3, 2), "S4": round(s4, 2),
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
    buyer_entry = base_atm_price
    buyer_sl = max(10.0, round(buyer_entry - (spot_risk * delta), 1))
    buyer_t1 = round(buyer_entry + (spot_risk * 1.0 * delta), 1)
    buyer_t2 = round(buyer_entry + (spot_risk * 1.5 * delta), 1)
    buyer_t3 = round(buyer_entry + (spot_risk * 2.5 * delta), 1)
    buyer_strike = f"{atm_strike} CE" if signal_direction == "BUY" else f"{atm_strike} PE"

    return {
        "buyer_strike": buyer_strike, "buyer_entry": buyer_entry, "buyer_sl": buyer_sl,
        "buyer_t1": buyer_t1, "buyer_t2": buyer_t2, "buyer_t3": buyer_t3
    }

# --- PDF ENGINE ---
def generate_detailed_pdf_report(filename, title_text, subtitle_text, logs_to_print):
    doc = SimpleDocTemplate(filename, pagesize=landscape(letter), rightMargin=15, leftMargin=15, topMargin=20, bottomMargin=20)
    styles = getSampleStyleSheet()
    elements = []

    title_style = ParagraphStyle('RepTitle', parent=styles['Heading1'], fontSize=14, leading=17, textColor=colors.HexColor("#1A365D"), alignment=1)
    elements.append(Paragraph(f"{title_text} - {STRATEGY_DISPLAY_NAME}", title_style))
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
        print(f"NSE Live Fetch Note: {e}")
        return None

# --- SCANNING LOOP ---
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

        # 1. PIVOTS ALERT (09:05 AM)
        if not pivots_alert_sent and current_time >= pivot_alert_time:
            pivots_alert_sent = True
            p_msg = f"📐 DAILY CAMARILLA PIVOT LEVELS (09:05 AM IST)\n📅 Date: {today_date_str}\n⚡ Strategy: {STRATEGY_DISPLAY_NAME}\n\n"
            for idx in INDEX_WATCHLIST:
                lvl = camarilla_levels.get(idx)
                if lvl:
                    p_msg += (
                        f"🔹 {idx} (Prev Close: {lvl['Prev_Close']})\n"
                        f"• R4 (Breakout Buy): {lvl['R4']:.2f} | R3: {lvl['R3']:.2f}\n"
                        f"• S3: {lvl['S3']:.2f} | S4 (Breakdown Sell): {lvl['S4']:.2f}\n\n"
                    )
            send_telegram_alert(p_msg)

        can_take_trades = (start_trade_time <= current_time < end_trade_time)
        is_market_closing = (current_time >= end_trade_time)

        # 2. MARKET CLOSE & SUMMARY (03:40 PM)
        if current_time >= shutdown_time:
            all_ledger_records = load_monthly_ledger()
            today_records = [l for l in all_ledger_records if l.get('date') == today_date_str]

            total = trade_stats['total_signals']
            wins = trade_stats['target_hits']
            win_rate = (wins / total * 100) if total > 0 else 0.0

            summary = (
                f"📊 MARKET CLOSED (DAILY REPORT)\n\n"
                f"⚡ Strategy: {STRATEGY_DISPLAY_NAME}\n"
                f"📅 Date: {today_date_str}\n\n"
                f"• Today's Signals Closed: {len(today_records)}\n"
                f"• Targets Hit: {wins}\n"
                f"• Stop Losses Hit: {trade_stats['sl_hits']}\n"
                f"• Early Cuts: {trade_stats['early_cuts']}\n"
                f"🏆 Win Rate: {win_rate:.1f}%\n"
                f"📚 Total Trades Logged: {len(all_ledger_records)}"
            )
            send_telegram_alert(summary)

            pdf_daily = f"Daily_Report_{today_date_str}.pdf"
            generate_detailed_pdf_report(pdf_daily, "DAILY TRADE PERFORMANCE", today_date_str, today_records)
            send_telegram_document(pdf_daily, caption=f"📄 Daily Detailed Performance Sheet ({today_date_str})")
            send_email_with_pdf(pdf_daily, f"Daily Trading Report - {today_date_str}", summary)
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

                    # HERO-ZERO NOTIFICATION (01:15 PM)
                    if not hero_zero_sent and current_time >= hero_zero_time:
                        step = 50 if index_name == "NIFTY 50" else 100
                        atm_k = int(round(current_price / step) * step)
                        hz_msg = (
                            f"🔥 HERO-ZERO SETUP ALERT (01:15 PM IST)\n\n"
                            f"📍 Index: {index_name} (Spot: {current_price:.2f})\n"
                            f"🎯 Focus Strikes (Low Premium):\n"
                            f"• Call Option: {atm_k + step} CE\n"
                            f"• Put Option: {atm_k - step} PE\n\n"
                            f"⚡ Strategy: {STRATEGY_DISPLAY_NAME} Camarilla Breakout!"
                        )
                        send_telegram_alert(hz_msg)
                        hero_zero_sent = True

                    # ACTIVE POSITION TRACKING
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

                        if trade['type'] == 'BUY':
                            if not trade.get('t1_hit') and current_price < trade['cut_level']:
                                trade_stats['early_cuts'] += 1
                                trade['exit_price'] = current_price
                                trade['exit_time'] = current_time_str
                                trade['pnl'] = current_price - trade['entry']
                                trade['status'] = 'Early Cut (R3)'
                                record_to_monthly_ledger(trade)
                                send_telegram_alert(format_telegram_card(trade))
                                active_trades[index_name] = None
                                save_backup_state(active_trades)
                                continue

                            if current_price <= trade['sl']:
                                trade_stats['sl_hits'] += 1
                                trade['sl_hit'] = True
                                trade['sl_time'] = current_time_str
                                trade['exit_price'] = current_price
                                trade['exit_time'] = current_time_str
                                trade['pnl'] = current_price - trade['entry']
                                trade['status'] = 'Target 1 & Exit' if trade.get('t1_hit') else 'SL Hit'
                                record_to_monthly_ledger(trade)
                                if not trade.get('t1_hit'):
                                    send_telegram_alert(format_telegram_card(trade))
                                active_trades[index_name] = None
                                save_backup_state(active_trades)
                                continue

                            if not trade.get('t1_hit') and current_price >= trade['t1']:
                                trade['t1_hit'] = True
                                trade['t1_time'] = current_time_str
                                trade['sl'] = trade['entry']
                                trade_stats['target_hits'] += 1
                                save_backup_state(active_trades)
                                send_telegram_alert(f"🎯 TARGET 1 ACHIEVED!\n📍 Index: {index_name} (BUY)\n💵 Spot: {current_price:.2f}\n⏰ Time: {current_time_str}\n🛡️ Action: SL moved to Entry ({trade['entry']:.2f})!")

                            if trade.get('t1_hit') and not trade.get('t2_hit') and current_price >= trade['t2']:
                                trade['t2_hit'] = True
                                trade['t2_time'] = current_time_str
                                trade['sl'] = trade['t1']
                                trade_stats['target_hits'] += 1
                                save_backup_state(active_trades)
                                send_telegram_alert(f"🎯🎯 TARGET 2 ACHIEVED!\n📍 Index: {index_name} (BUY)\n💵 Spot: {current_price:.2f}\n⏰ Time: {current_time_str}\n🛡️ Action: SL trailed to T1 ({trade['t1']:.2f})!")

                            if trade.get('t2_hit') and current_price >= trade['t3']:
                                trade['t3_hit'] = True
                                trade['t3_time'] = current_time_str
                                trade_stats['target_hits'] += 1
                                trade['exit_price'] = current_price
                                trade['exit_time'] = current_time_str
                                trade['pnl'] = current_price - trade['entry']
                                trade['status'] = 'Target 3 Achieved'
                                record_to_monthly_ledger(trade)
                                send_telegram_alert(format_telegram_card(trade))
                                active_trades[index_name] = None
                                save_backup_state(active_trades)
                                continue

                        elif trade['type'] == 'SELL':
                            if not trade.get('t1_hit') and current_price > trade['cut_level']:
                                trade_stats['early_cuts'] += 1
                                trade['exit_price'] = current_price
                                trade['exit_time'] = current_time_str
                                trade['pnl'] = trade['entry'] - current_price
                                trade['status'] = 'Early Cut (S3)'
                                record_to_monthly_ledger(trade)
                                send_telegram_alert(format_telegram_card(trade))
                                active_trades[index_name] = None
                                save_backup_state(active_trades)
                                continue

                            if current_price >= trade['sl']:
                                trade_stats['sl_hits'] += 1
                                trade['sl_hit'] = True
                                trade['sl_time'] = current_time_str
                                trade['exit_price'] = current_price
                                trade['exit_time'] = current_time_str
                                trade['pnl'] = trade['entry'] - current_price
                                trade['status'] = 'Target 1 & Exit' if trade.get('t1_hit') else 'SL Hit'
                                record_to_monthly_ledger(trade)
                                if not trade.get('t1_hit'):
                                    send_telegram_alert(format_telegram_card(trade))
                                active_trades[index_name] = None
                                save_backup_state(active_trades)
                                continue

                            if not trade.get('t1_hit') and current_price <= trade['t1']:
                                trade['t1_hit'] = True
                                trade['t1_time'] = current_time_str
                                trade['sl'] = trade['entry']
                                trade_stats['target_hits'] += 1
                                save_backup_state(active_trades)
                                send_telegram_alert(f"🎯 TARGET 1 ACHIEVED!\n📍 Index: {index_name} (SELL)\n💵 Spot: {current_price:.2f}\n⏰ Time: {current_time_str}\n🛡️ Action: SL moved to Entry ({trade['entry']:.2f})!")

                            if trade.get('t1_hit') and not trade.get('t2_hit') and current_price <= trade['t2']:
                                trade['t2_hit'] = True
                                trade['t2_time'] = current_time_str
                                trade['sl'] = trade['t1']
                                trade_stats['target_hits'] += 1
                                save_backup_state(active_trades)
                                send_telegram_alert(f"🎯🎯 TARGET 2 ACHIEVED!\n📍 Index: {index_name} (SELL)\n💵 Spot: {current_price:.2f}\n⏰ Time: {current_time_str}\n🛡️ Action: SL trailed to T1 ({trade['t1']:.2f})!")

                            if trade.get('t2_hit') and current_price <= trade['t3']:
                                trade['t3_hit'] = True
                                trade['t3_time'] = current_time_str
                                trade_stats['target_hits'] += 1
                                trade['exit_price'] = current_price
                                trade['exit_time'] = current_time_str
                                trade['pnl'] = trade['entry'] - current_price
                                trade['status'] = 'Target 3 Achieved'
                                record_to_monthly_ledger(trade)
                                send_telegram_alert(format_telegram_card(trade))
                                active_trades[index_name] = None
                                save_backup_state(active_trades)
                                continue

                    # BREAKOUT ENTRY TRIGGER
                    pivots = camarilla_levels.get(index_name)
                    if can_take_trades and active_trades[index_name] is None and pivots is not None:
                        r4, s4, r3, s3 = pivots['R4'], pivots['S4'], pivots['R3'], pivots['S3']

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

                            send_telegram_alert(
                                f"🟢 {index_name} BUY SIGNAL\n⚡ Strategy: {STRATEGY_DISPLAY_NAME}\n"
                                f"⏰ Time: {current_time_str} IST\n💵 Spot Entry: {current_price:.2f} | SL: {sl:.2f}\n\n"
                                f"🛒 OPTION BUYERS (CALL):\n• Strike: {opt['buyer_strike']}\n• Entry Approx: ₹{opt['buyer_entry']:.1f}\n"
                                f"• Targets: T1: ₹{opt['buyer_t1']:.1f} | T2: ₹{opt['buyer_t2']:.1f} | T3: ₹{opt['buyer_t3']:.1f}\n\n"
                                f"🎯 Spot Targets: T1: {t1:.2f} | T2: {t2:.2f} | T3: {t3:.2f}"
                            )

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

                            send_telegram_alert(
                                f"🔴 {index_name} SELL SIGNAL\n⚡ Strategy: {STRATEGY_DISPLAY_NAME}\n"
                                f"⏰ Time: {current_time_str} IST\n💵 Spot Entry: {current_price:.2f} | SL: {sl:.2f}\n\n"
                                f"🛒 OPTION BUYERS (PUT):\n• Strike: {opt['buyer_strike']}\n• Entry Approx: ₹{opt['buyer_entry']:.1f}\n"
                                f"• Targets: T1: ₹{opt['buyer_t1']:.1f} | T2: ₹{opt['buyer_t2']:.1f} | T3: ₹{opt['buyer_t3']:.1f}\n\n"
                                f"🎯 Spot Targets: T1: {t1:.2f} | T2: {t2:.2f} | T3: {t3:.2f}"
                            )

            # 3. HOURLY STATUS ALERT
            if now.minute == 0 and now.hour != last_heartbeat_hour and (9 <= now.hour <= 15):
                last_heartbeat_hour = now.hour
                hb_msg = f"💓 HOURLY STATUS ALERT\n⏰ Time: {current_time_str} IST\n⚡ Strategy: {STRATEGY_DISPLAY_NAME}\n\n"
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
