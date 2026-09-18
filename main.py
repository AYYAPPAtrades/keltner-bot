import os
import time
import requests
import json
import smtplib
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
start_now = datetime.now(IST)

# --- TELEGRAM CONFIGURATION ---
TELEGRAM_BOT_TOKEN = "8999213661:AAEfHcQzRZ2-ZI4bbfq8UcuGA48ihzQKchA"

# ചാനലും പേഴ്സണൽ ചാറ്റും വേർതിരിക്കുന്നു
ADMIN_CHAT_ID = "6789591588"
CHANNEL_CHAT_ID = "@sastradinglab"
PUBLIC_ALERT_IDS = [CHANNEL_CHAT_ID, ADMIN_CHAT_ID]

tele_session = requests.Session()
STRATEGY_DISPLAY_NAME = "MOMENTUM SPIKE"

# --- EMAIL CONFIGURATION ---
SENDER_EMAIL = "shinos99@gmail.com"
SENDER_APP_PASSWORD = "xufefwfphwsomsnu"
RECEIVER_EMAILS = ["shinos99@gmail.com"]

# 1. അഡ്മിന് മാത്രമുള്ള സിസ്റ്റം അപ്‌ഡേറ്റുകൾ
def send_admin_alert(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        payload = {"chat_id": ADMIN_CHAT_ID, "text": msg}
        tele_session.post(url, json=payload, timeout=4)
    except Exception as e:
        print(f"Admin Alert Error: {e}")

# 2. ചാനലിലുള്ള എല്ലാവർക്കും നിങ്ങൾക്കും ലഭിക്കുന്ന സിഗ്നലുകളും അലേർട്ടുകളും
def send_telegram_alert(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    for chat_id in PUBLIC_ALERT_IDS:
        try:
            payload = {"chat_id": chat_id, "text": msg}
            tele_session.post(url, json=payload, timeout=4)
        except Exception as e:
            print(f"Telegram Post Error ({chat_id}): {e}")

def send_telegram_document(file_path, caption=""):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendDocument"
    for chat_id in PUBLIC_ALERT_IDS:
        try:
            with open(file_path, 'rb') as doc:
                files = {'document': doc}
                data = {'chat_id': chat_id, 'caption': caption}
                requests.post(url, data=data, files=files, timeout=20)
        except Exception as e:
            print(f"Telegram Doc Error ({chat_id}): {e}")

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
    except Exception as e:
        print(f"Email Dispatch Warning: {e}")

# --- WEEKEND & HOLIDAY PROTECTION (ADMIN ALERT ONLY) ---
today_weekday = datetime.now(IST).weekday()
if today_weekday in [5, 6]:
    day_name = "Saturday" if today_weekday == 5 else "Sunday"
    send_admin_alert(f"🏖️ WEEKEND MARKET HOLIDAY ({day_name})!\n\n• Market is closed today.\n• Resumes Monday at 09:00 AM IST.")
    exit(0)

try:
    holidays_df = capital_market.holiday_trading()
    today_str = datetime.now(IST).strftime('%d-%b-%Y')
    if holidays_df is not None and not holidays_df.empty:
        if 'tradingDate' in holidays_df.columns and today_str in holidays_df['tradingDate'].values:
            reason = holidays_df[holidays_df['tradingDate'] == today_str]['description'].values[0]
            send_admin_alert(f"🏖️ NSE MARKET HOLIDAY TODAY!\n\n• Reason: {reason}\n• Scanner resting safely.")
            exit(0)
except Exception as e:
    print(f"Holiday check note: {e}")

INDEX_WATCHLIST = ["NIFTY 50", "NIFTY BANK"]
YF_TICKERS = {"NIFTY 50": "^NSEI", "NIFTY BANK": "^NSEBANK"}
BACKUP_FILE = "daily_active_trades.json"
MONTHLY_LEDGER_FILE = "monthly_trades_ledger.json"

trade_stats = {"total_signals": 0, "target_hits": 0, "sl_hits": 0}
prev_close_dict = {}
camarilla_levels = {}
pivots_alert_sent = False
eod_alert_sent = False
last_heartbeat_hour = -1

def init_clean_daily_state():
    state = {idx: None for idx in INDEX_WATCHLIST}
    try:
        with open(BACKUP_FILE, 'w') as f:
            json.dump(state, f, indent=4)
    except Exception as e:
        print(f"Init state note: {e}")
    return state

def save_state(state):
    try:
        with open(BACKUP_FILE, 'w') as f:
            json.dump(state, f, indent=4)
    except Exception:
        pass

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
    except Exception:
        pass

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

            return {
                "R4": round(close + (diff * 1.1 / 2.0), 2),
                "R3": round(close + (diff * 1.1 / 4.0), 2),
                "S3": round(close - (diff * 1.1 / 4.0), 2),
                "S4": round(close - (diff * 1.1 / 2.0), 2),
                "Prev_Close": round(close, 2)
            }
    except Exception as e:
        print(f"Camarilla error ({index_name}): {e}")
    return None

for idx in INDEX_WATCHLIST:
    camarilla_levels[idx] = calculate_camarilla_pivots(idx)

active_trades = init_clean_daily_state()

def generate_pdf_report(filename, title_text, date_text, logs):
    doc = SimpleDocTemplate(filename, pagesize=landscape(letter), rightMargin=15, leftMargin=15, topMargin=20, bottomMargin=20)
    styles = getSampleStyleSheet()
    elements = []

    title_style = ParagraphStyle('RepTitle', parent=styles['Heading1'], fontSize=14, leading=17, textColor=colors.HexColor("#1A365D"), alignment=1)
    elements.append(Paragraph(f"{title_text} - {STRATEGY_DISPLAY_NAME}", title_style))
    elements.append(Paragraph(f"Timeline: {date_text} | Total Trades: {len(logs)}", styles['Normal']))
    elements.append(Spacer(1, 10))

    headers = ["SL", "Date", "Index & Type", "Entry & Time", "Target 1", "Target 2", "Target 3", "Stop Loss", "P/L Pts", "Status"]
    table_rows = [headers]

    for i, l in enumerate(logs, 1):
        table_rows.append([
            str(i), l.get('date', '-'), f"{l.get('index')}\n({l.get('type')})",
            f"{l.get('entry'):.2f}\n({l.get('entry_time')})",
            f"{l.get('t1'):.2f}" if l.get('t1_hit') else "-",
            f"{l.get('t2'):.2f}" if l.get('t2_hit') else "-",
            f"{l.get('t3'):.2f}" if l.get('t3_hit') else "-",
            f"{l.get('sl'):.2f}",
            f"{l.get('pnl', 0.0):+.2f}",
            l.get('status', '-')
        ])

    trade_table = Table(table_rows, colWidths=[25, 65, 80, 80, 80, 80, 80, 80, 65, 110])
    trade_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#2B6CB0")),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E0")),
        ('FONTSIZE', (0, 0), (-1, -1), 7.5),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]))
    elements.append(trade_table)
    doc.build(elements)

def get_live_indices():
    try:
        return capital_market.market_watch_all_indices()
    except Exception:
        return None

# STARTUP NOTIFICATION (ADMIN ONLY)
send_admin_alert(
    "🚀 ALGO SCANNER LIVE\n\n"
    f"⚡ Strategy: {STRATEGY_DISPLAY_NAME}\n"
    f"🕒 Time: {start_now.strftime('%I:%M:%S %p')} IST\n"
    "🛡️ Engine Active: 09:00 AM - 03:40 PM"
)

# MAIN ENGINE LOOP
while True:
    try:
        now = datetime.now(IST)
        current_time = now.time()
        current_time_str = now.strftime('%I:%M:%S %p')
        today_date_str = now.strftime('%d-%b-%Y')

        pivot_alert_time = datetime.strptime("09:05", "%H:%M").time()
        start_trade_time = datetime.strptime("09:15", "%H:%M").time()
        exit_alert_time = datetime.strptime("15:25", "%H:%M").time()
        shutdown_time = datetime.strptime("15:40", "%H:%M").time()

        # 09:05 AM PIVOTS (PUBLIC ALERT - ചാനലിലേക്കും നിങ്ങൾക്കും)
        if not pivots_alert_sent and current_time >= pivot_alert_time:
            pivots_alert_sent = True
            p_msg = f"📐 DAILY CAMARILLA LEVELS (09:05 AM)\n📅 Date: {today_date_str}\n⚡ Strategy: {STRATEGY_DISPLAY_NAME}\n\n"
            for idx in INDEX_WATCHLIST:
                lvl = camarilla_levels.get(idx)
                if lvl:
                    p_msg += f"🔹 {idx}\n• R4: {lvl['R4']:.2f} | R3: {lvl['R3']:.2f}\n• S3: {lvl['S3']:.2f} | S4: {lvl['S4']:.2f}\n\n"
            send_telegram_alert(p_msg)

        # 03:25 PM EXIT ALERT (PUBLIC ALERT)
        if current_time >= exit_alert_time and not eod_alert_sent:
            eod_alert_sent = True
            send_telegram_alert("⚠️ INTRADAY AUTO-EXIT ALERT (03:25 PM)\n\n• Market closing soon.\n• Squaring off all active positions safely.")
            for idx in INDEX_WATCHLIST:
                trade = active_trades[idx]
                if trade is not None:
                    last_prc = prev_close_dict.get(idx, trade['entry'])
                    pnl = last_prc - trade['entry'] if trade['type'] == 'BUY' else trade['entry'] - last_prc
                    trade['exit_price'] = last_prc
                    trade['pnl'] = pnl
                    trade['status'] = 'Auto-Exit (03:25 PM)'
                    record_to_monthly_ledger(trade)
                    send_telegram_alert(f"🏁 POSITION SQUARED OFF ({idx})\n• P/L: {pnl:+.2f} Pts\n• Status: Intraday Auto-Exit")
                    active_trades[idx] = None
            save_state(active_trades)

        # 03:40 PM SHUTDOWN & PDF DISPATCH (PUBLIC ALERT)
        if current_time >= shutdown_time:
            records = load_monthly_ledger()
            today_recs = [r for r in records if r.get('date') == today_date_str]
            summary = (
                f"📊 MARKET CLOSED (DAILY REPORT)\n\n"
                f"📅 Date: {today_date_str}\n"
                f"⚡ Strategy: {STRATEGY_DISPLAY_NAME}\n"
                f"• Signals Executed: {len(today_recs)}\n"
                f"• Target Wins: {trade_stats['target_hits']}\n"
                f"• Stop Losses: {trade_stats['sl_hits']}\n\n"
                f"Dispatching PDF reports to Gmail & Telegram..."
            )
            send_telegram_alert(summary)

            pdf_file = f"Daily_Report_{today_date_str}.pdf"
            generate_pdf_report(pdf_file, "DAILY TRADE REPORT", today_date_str, today_recs)
            send_telegram_document(pdf_file, caption=f"📄 Performance Report ({today_date_str})")
            send_email_with_pdf(pdf_file, f"Market Report - {today_date_str}", summary)
            break

        # DATA STREAM & SIGNAL EXECUTION
        raw = get_live_indices()
        if raw is not None and not raw.empty:
            prices_dict = {}
            for idx in INDEX_WATCHLIST:
                row = raw[raw['index'] == idx]
                if not row.empty:
                    current_price = float(str(row['last'].values[0]).replace(',', ''))
                    prices_dict[idx] = current_price

                    if idx not in prev_close_dict and 'previousClose' in row.columns:
                        prev_close_dict[idx] = float(str(row['previousClose'].values[0]).replace(',', ''))

                    trade = active_trades[idx]

                    # 1. POSITION TRACKING (TARGETS & STOP LOSS - PUBLIC ALERTS)
                    if trade is not None:
                        # BUY TRADE
                        if trade['type'] == 'BUY':
                            if current_price <= trade['sl']:
                                trade_stats['sl_hits'] += 1
                                pnl = current_price - trade['entry']
                                trade['exit_price'] = current_price
                                trade['pnl'] = pnl
                                trade['status'] = 'Target 1 & Exit' if trade.get('t1_hit') else 'SL Hit'
                                record_to_monthly_ledger(trade)
                                send_telegram_alert(f"🛑 STOP LOSS HIT!\n📍 Index: {idx} (CALL)\n💵 Exit: {current_price:.2f}\n⏰ Time: {current_time_str}")
                                active_trades[idx] = None
                                save_state(active_trades)
                                continue

                            if not trade.get('t1_hit') and current_price >= trade['t1']:
                                trade['t1_hit'] = True
                                trade['sl'] = trade['entry']
                                trade_stats['target_hits'] += 1
                                save_state(active_trades)
                                send_telegram_alert(
                                    f"🎯 TARGET 1 HIT!\n"
                                    f"⚡ Strategy: {STRATEGY_DISPLAY_NAME}\n"
                                    f"Index: {idx} (CALL)\n"
                                    f"💵 Target Price: {trade['t1']:.2f}\n"
                                    f"Current: {current_price:.2f}"
                                )

                            if trade.get('t1_hit') and not trade.get('t2_hit') and current_price >= trade['t2']:
                                trade['t2_hit'] = True
                                trade['sl'] = trade['t1']
                                save_state(active_trades)
                                send_telegram_alert(
                                    f"🎯 TARGET 2 HIT!\n"
                                    f"⚡ Strategy: {STRATEGY_DISPLAY_NAME}\n"
                                    f"Index: {idx} (CALL)\n"
                                    f"💵 Target Price: {trade['t2']:.2f}\n"
                                    f"Current: {current_price:.2f}"
                                )

                            if trade.get('t2_hit') and current_price >= trade['t3']:
                                trade['t3_hit'] = True
                                pnl = current_price - trade['entry']
                                trade['exit_price'] = current_price
                                trade['pnl'] = pnl
                                trade['status'] = 'Target 3 Achieved'
                                record_to_monthly_ledger(trade)
                                send_telegram_alert(
                                    f"🎯 TARGET 3 HIT!\n"
                                    f"⚡ Strategy: {STRATEGY_DISPLAY_NAME}\n"
                                    f"Index: {idx} (CALL)\n"
                                    f"💵 Target Price: {trade['t3']:.2f}\n"
                                    f"Current: {current_price:.2f}"
                                )
                                active_trades[idx] = None
                                save_state(active_trades)
                                continue

                        # SELL TRADE
                        elif trade['type'] == 'SELL':
                            if current_price >= trade['sl']:
                                trade_stats['sl_hits'] += 1
                                pnl = trade['entry'] - current_price
                                trade['exit_price'] = current_price
                                trade['pnl'] = pnl
                                trade['status'] = 'Target 1 & Exit' if trade.get('t1_hit') else 'SL Hit'
                                record_to_monthly_ledger(trade)
                                send_telegram_alert(f"🛑 STOP LOSS HIT!\n📍 Index: {idx} (PUT)\n💵 Exit: {current_price:.2f}\n⏰ Time: {current_time_str}")
                                active_trades[idx] = None
                                save_state(active_trades)
                                continue

                            if not trade.get('t1_hit') and current_price <= trade['t1']:
                                trade['t1_hit'] = True
                                trade['sl'] = trade['entry']
                                trade_stats['target_hits'] += 1
                                save_state(active_trades)
                                send_telegram_alert(
                                    f"🎯 TARGET 1 HIT!\n"
                                    f"⚡ Strategy: {STRATEGY_DISPLAY_NAME}\n"
                                    f"Index: {idx} (PUT)\n"
                                    f"💵 Target Price: {trade['t1']:.2f}\n"
                                    f"Current: {current_price:.2f}"
                                )

                            if trade.get('t1_hit') and not trade.get('t2_hit') and current_price <= trade['t2']:
                                trade['t2_hit'] = True
                                trade['sl'] = trade['t1']
                                save_state(active_trades)
                                send_telegram_alert(
                                    f"🎯 TARGET 2 HIT!\n"
                                    f"⚡ Strategy: {STRATEGY_DISPLAY_NAME}\n"
                                    f"Index: {idx} (PUT)\n"
                                    f"💵 Target Price: {trade['t2']:.2f}\n"
                                    f"Current: {current_price:.2f}"
                                )

                            if trade.get('t2_hit') and current_price <= trade['t3']:
                                trade['t3_hit'] = True
                                pnl = trade['entry'] - current_price
                                trade['exit_price'] = current_price
                                trade['pnl'] = pnl
                                trade['status'] = 'Target 3 Achieved'
                                record_to_monthly_ledger(trade)
                                send_telegram_alert(
                                    f"🎯 TARGET 3 HIT!\n"
                                    f"⚡ Strategy: {STRATEGY_DISPLAY_NAME}\n"
                                    f"Index: {idx} (PUT)\n"
                                    f"💵 Target Price: {trade['t3']:.2f}\n"
                                    f"Current: {current_price:.2f}"
                                )
                                active_trades[idx] = None
                                save_state(active_trades)
                                continue

                    # 2. NEW SIGNAL TRIGGER (FIBONACCI RATIOS - PUBLIC ALERTS)
                    pivots = camarilla_levels.get(idx)
                    can_trade = (start_trade_time <= current_time < exit_alert_time)

                    if can_trade and active_trades[idx] is None and pivots is not None:
                        r4, s4, r3, s3 = pivots['R4'], pivots['S4'], pivots['R3'], pivots['S3']

                        # BUY SIGNAL (Above R4)
                        if current_price > r4:
                            sl = round(r3, 2)
                            risk = round(current_price - sl, 2)
                            if risk < 15: risk = 20.0; sl = round(current_price - 20.0, 2)

                            t1 = round(current_price + (risk * 1.437), 2)
                            t2 = round(current_price + (risk * 1.915), 2)
                            t3 = round(current_price + (risk * 2.873), 2)

                            active_trades[idx] = {
                                'date': today_date_str, 'index': idx, 'type': 'BUY',
                                'entry': current_price, 'entry_time': current_time_str,
                                'sl': sl, 't1': t1, 't2': t2, 't3': t3,
                                't1_hit': False, 't2_hit': False, 't3_hit': False
                            }
                            save_state(active_trades)
                            trade_stats['total_signals'] += 1

                            send_telegram_alert(
                                f"🟢 {idx} BUY SIGNAL\n\n"
                                f"⚡ Strategy: {STRATEGY_DISPLAY_NAME}\n"
                                f"⏰ Time: {current_time_str} IST\n"
                                f"💵 Entry: {current_price:.2f}\n"
                                f"🛑 Stop Loss: {sl:.2f}\n\n"
                                f"🎯 Target 1: {t1:.2f}\n"
                                f"🎯 Target 2: {t2:.2f}\n"
                                f"🎯 Target 3: {t3:.2f}"
                            )

                        # SELL SIGNAL (Below S4)
                        elif current_price < s4:
                            sl = round(s3, 2)
                            risk = round(sl - current_price, 2)
                            if risk < 15: risk = 20.0; sl = round(current_price + 20.0, 2)

                            t1 = round(current_price - (risk * 1.437), 2)
                            t2 = round(current_price - (risk * 1.915), 2)
                            t3 = round(current_price - (risk * 2.873), 2)

                            active_trades[idx] = {
                                'date': today_date_str, 'index': idx, 'type': 'SELL',
                                'entry': current_price, 'entry_time': current_time_str,
                                'sl': sl, 't1': t1, 't2': t2, 't3': t3,
                                't1_hit': False, 't2_hit': False, 't3_hit': False
                            }
                            save_state(active_trades)
                            trade_stats['total_signals'] += 1

                            send_telegram_alert(
                                f"🔴 {idx} SELL SIGNAL\n\n"
                                f"⚡ Strategy: {STRATEGY_DISPLAY_NAME}\n"
                                f"⏰ Time: {current_time_str} IST\n"
                                f"💵 Entry: {current_price:.2f}\n"
                                f"🛑 Stop Loss: {sl:.2f}\n\n"
                                f"🎯 Target 1: {t1:.2f}\n"
                                f"🎯 Target 2: {t2:.2f}\n"
                                f"🎯 Target 3: {t3:.2f}"
                            )

            # 3. HOURLY STATUS ALERT (ADMIN ONLY - ചാനലിൽ സ്പാം ഒഴിവാക്കാൻ)
            if now.minute == 0 and now.hour != last_heartbeat_hour and (9 <= now.hour <= 15):
                last_heartbeat_hour = now.hour
                hb_msg = f"💓 HOURLY STATUS ALERT\n⏰ Time: {current_time.strftime('%I:%M:00 %p')} IST\n\n"
                for idx, prc in prices_dict.items():
                    prev_c = prev_close_dict.get(idx, prc)
                    diff = prc - prev_c
                    pct = (diff / prev_c) * 100 if prev_c != 0 else 0.0
                    hb_msg += f"• {idx}: {prc:.2f} ({diff:+.2f} | {pct:+.2f}%)\n"
                send_admin_alert(hb_msg)

        time.sleep(1)

    except Exception as e:
        print(f"Engine Loop Warning: {e}")
        time.sleep(2)
