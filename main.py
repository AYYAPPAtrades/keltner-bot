
import os
import time
import requests
import json
import smtplib
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

# --- TELEGRAM CONFIGURATION (SINGLE CHAT) ---
TELEGRAM_BOT_TOKEN = "8921879577:AAHR_GPiDLyTtsrtMZx12CJ2nCM-YAUh3N0"
TELEGRAM_CHAT_ID = "6789591588"
tele_session = requests.Session()

def send_telegram_alert(message):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "disable_web_page_preview": True}
        tele_session.post(url, json=payload, timeout=4)
    except Exception as e:
        print(f"Telegram Error: {e}")

def send_telegram_document(file_path, caption=""):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendDocument"
        with open(file_path, 'rb') as doc:
            files = {'document': doc}
            data = {'chat_id': TELEGRAM_CHAT_ID, 'caption': caption}
            requests.post(url, data=data, files=files, timeout=20)
    except Exception as e:
        print(f"Telegram Doc Error: {e}")

# --- EMAIL CONFIGURATION (NEW GMAIL & APP PASSWORD) ---
SENDER_EMAIL = "shinos99@gmail.com"
SENDER_APP_PASSWORD = "xufefwfphwsomnsnu"
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
        print("PDF report emailed successfully.")
    except Exception as e:
        print(f"Email Dispatch Warning: {e}")

# --- 1. WEEKEND PROTECTION ---
today_weekday = datetime.now(IST).weekday()
if today_weekday in [5, 6]:
    day_name = "Saturday" if today_weekday == 5 else "Sunday"
    send_telegram_alert(
        f"🏖️ WEEKEND MARKET HOLIDAY ({day_name})!\n\n"
        "• Status: Market is Closed.\n"
        "• Scanner will remain inactive today.\n"
        "• Resumes Monday at 09:00 AM IST."
    )
    exit(0)

# --- 2. NSE OFFICIAL HOLIDAY CHECK ---
try:
    holidays_df = capital_market.holiday_trading()
    today_str = datetime.now(IST).strftime('%d-%b-%Y')
    if holidays_df is not None and not holidays_df.empty:
        if 'tradingDate' in holidays_df.columns and today_str in holidays_df['tradingDate'].values:
            reason = holidays_df[holidays_df['tradingDate'] == today_str]['description'].values[0]
            send_telegram_alert(
                f"🏖️ MARKET HOLIDAY TODAY!\n"
                f"Reason: {reason}\n"
                f"Strategy: MOMENTUM SPIKE will not run today."
            )
            exit(0)
except Exception as e:
    print(f"Holiday check skipped: {e}")

INDEX_WATCHLIST = ["NIFTY 50", "NIFTY BANK"]
YF_TICKERS = {"NIFTY 50": "^NSEI", "NIFTY BANK": "^NSEBANK"}
TRADE_FILE = "active_trades_momentum.json"
MONTHLY_LEDGER_FILE = "monthly_trades_ledger.json"
STRATEGY_DISPLAY_NAME = "MOMENTUM SPIKE"

trade_stats = {"total_signals": 0, "target_hits": 0, "sl_hits": 0}
levels_sent_today = False
hero_zero_sent = False
last_heartbeat_hour = -1
prev_close_dict = {}

# --- AUTOMATIC EXPIRY DETECTION (WEEKLY & MONTHLY) ---
def check_nifty_expiry_today():
    today_date = datetime.now(IST).date()
    today_str = today_date.strftime('%d-%b-%Y').upper()
    try:
        chain_df = capital_market.live_index_option_chain("NIFTY")
        if chain_df is not None and not chain_df.empty:
            all_expiries = sorted(list(set(chain_df['expiryDate'].dropna().tolist())))
            if all_expiries:
                current_expiry_str = all_expiries[0].upper()
                is_expiry_today = (current_expiry_str == today_str)

                curr_month = today_date.strftime('%b').upper()
                curr_year = today_date.strftime('%Y')
                month_expiries = [e for e in all_expiries if curr_month in e.upper() and curr_year in e]
                is_monthly_expiry = (month_expiries and current_expiry_str == month_expiries[-1].upper() and is_expiry_today)

                return is_expiry_today, is_monthly_expiry, current_expiry_str
    except Exception as e:
        print(f"Expiry fetch error: {e}")

    # Default weekly Tuesday (weekday == 1)
    is_tuesday = (today_date.weekday() == 1)
    return is_tuesday, False, today_str

def check_banknifty_expiry_today():
    today_date = datetime.now(IST).date()
    # Bank Nifty weekly Wednesday (weekday == 2)
    return (today_date.weekday() == 2)

# --- TRADE PERSISTENCE ---
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

# --- HISTORICAL CANDLES & CAMARILLA LEVELS ---
def get_historical_candles(index_name):
    global prev_close_dict
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
            df_d = yf.download(ticker, period="2d", interval="1d", progress=False)
            if not df_d.empty:
                if isinstance(df_d.columns, pd.MultiIndex):
                    df_d.columns = df_d.columns.get_level_values(0)
                prev_close_dict[index_name] = float(df_d.iloc[-2]['Close']) if len(df_d) >= 2 else float(df_d.iloc[-1]['Close'])
            return candles
    except Exception as e:
        print(f"History fetch error {index_name}: {e}")
    return []

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
            s3 = c - (rng * 1.1 / 4)
            return {"R3": round(r3, 2), "R2": round(r2, 2), "R1": round(r1, 2), 
                    "S1": round(s1, 2), "S2": round(s2, 2), "S3": round(s3, 2)}
    except Exception as e:
        print(f"Level calc error {index_name}: {e}")
    return None

# --- PDF REPORT GENERATOR ---
def generate_detailed_pdf_report(filename, title_text, subtitle_text, logs_to_print):
    doc = SimpleDocTemplate(filename, pagesize=landscape(letter), rightMargin=15, leftMargin=15, topMargin=20, bottomMargin=20)
    styles = getSampleStyleSheet()
    elements = []

    title_style = ParagraphStyle(
        'RepTitle', parent=styles['Heading1'], fontSize=14, leading=17,
        textColor=colors.HexColor("#1A365D"), alignment=1
    )
    elements.append(Paragraph(f"{title_text} - {STRATEGY_DISPLAY_NAME}", title_style))
    elements.append(Paragraph(f"Timeline: {subtitle_text} | Total Trades Logged: {len(logs_to_print)}", styles['Normal']))
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
            t1_val, t2_val, t3_val, sl_val, pnl_val,
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

candle_history = {idx: get_historical_candles(idx) for idx in INDEX_WATCHLIST}
active_trades = load_trades()
current_candles = {idx: {"open": None, "high": -1, "low": 9999999, "close": None, "start_min": None} for idx in INDEX_WATCHLIST}
alert_candles = {idx: {"sell_alert": None, "buy_alert": None} for idx in INDEX_WATCHLIST}

send_telegram_alert(
    "⚡ MOMENTUM SPIKE BOT ACTIVE\n"
    "⏰ Time: " + datetime.now(IST).strftime('%H:%M:%S IST') + "\n"
    "• System initialized with single chat alert & direct mail.\n"
    "• Monitoring NIFTY 50 & NIFTY BANK."
)

def get_live_index_data():
    try:
        return capital_market.market_watch_all_indices()
    except Exception as e:
        print(f"NSE Fetch Error: {e}")
        return None

# --- MAIN TRADING LOOP ---
while True:
    try:
        now = datetime.now(IST)
        current_time_str = now.strftime('%H:%M:%S IST')
        today_date_str = now.strftime('%d-%b-%Y')
        
        start_trade_time = datetime.strptime("09:30", "%H:%M").time()
        hero_zero_time = datetime.strptime("13:15", "%H:%M").time()
        end_trade_time = datetime.strptime("15:20", "%H:%M").time()
        market_shutdown_time = datetime.strptime("15:40", "%H:%M").time()

        can_take_trades = (start_trade_time <= now.time() < end_trade_time)
        is_market_closing = (now.time() >= end_trade_time)

        # 1. 09:05 AM LEVELS ALERT
        if not levels_sent_today and now.hour == 9 and now.minute >= 5:
            levels_msg = "📊 DAILY SUPPORT & RESISTANCE (9:05 AM)\n⚡ Strategy: MOMENTUM SPIKE\n"
            for idx in INDEX_WATCHLIST:
                lvl = calculate_camarilla_levels(idx)
                if lvl:
                    levels_msg += (
                        f"\n🔹 {idx}:\n"
                        f"  R3: {lvl['R3']:.2f} | R2: {lvl['R2']:.2f} | R1: {lvl['R1']:.2f}\n"
                        f"  S1: {lvl['S1']:.2f} | S2: {lvl['S2']:.2f} | S3: {lvl['S3']:.2f}\n"
                    )
            send_telegram_alert(levels_msg)
            levels_sent_today = True

        # 2. 03:40 PM DAILY & MONTHLY REPORT + PDF & EMAIL
        if now.time() >= market_shutdown_time:
            all_ledger_records = load_monthly_ledger()
            today_records = [l for l in all_ledger_records if l.get('date') == today_date_str]

            summary = (
                f"📋 DAILY PERFORMANCE REPORT\n"
                f"⚡ Strategy: {STRATEGY_DISPLAY_NAME}\n"
                f"📅 Date: {today_date_str}\n"
                f"• Total Signals: {trade_stats['total_signals']}\n"
                f"• Targets Hit: {trade_stats['target_hits']}\n"
                f"• Stop Loss Hit: {trade_stats['sl_hits']}\n\n"
                f"Bot safely completed today's session."
            )
            send_telegram_alert(summary)

            # Daily PDF Dispatch
            pdf_daily = f"Daily_Report_{today_date_str}.pdf"
            generate_detailed_pdf_report(pdf_daily, "DAILY TRADE PERFORMANCE", today_date_str, today_records)
            send_telegram_document(pdf_daily, caption=f"📄 Daily Detailed Report ({today_date_str})")
            send_email_with_pdf(pdf_daily, f"Daily Trading Report - {today_date_str}", summary)

            # Monthly Expiry PDF Dispatch
            is_nifty_expiry, is_monthly_expiry, _ = check_nifty_expiry_today()
            if is_monthly_expiry and os.path.exists(MONTHLY_LEDGER_FILE):
                try:
                    month_name = now.strftime('%B %Y')
                    pdf_monthly = f"Monthly_Expiry_Report_{now.strftime('%b_%Y')}.pdf"
                    generate_detailed_pdf_report(
                        pdf_monthly, 
                        f"MONTHLY EXPIRY PERFORMANCE REPORT ({month_name})", 
                        f"Full Expiry Cycle up to {today_date_str}", 
                        all_ledger_records
                    )
                    send_telegram_document(pdf_monthly, caption=f"📚 Monthly Expiry Detailed Report - {month_name}")
                    send_email_with_pdf(
                        pdf_monthly, 
                        f"Monthly Expiry Trading Report - {month_name}", 
                        f"Attached complete monthly trading summary and ledger for the expiry cycle ending {today_date_str}."
                    )
                except Exception as ex:
                    print(f"Monthly PDF dispatch error: {ex}")

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

                    # 3. HERO-ZERO EXPIRY SETUP (01:15 PM)
                    if not hero_zero_sent and now.time() >= hero_zero_time:
                        is_nifty_exp, is_monthly_exp, exp_date_str = check_nifty_expiry_today()
                        is_bn_exp = check_banknifty_expiry_today()

                        target_indices = []
                        if is_nifty_exp and index_name == "NIFTY 50":
                            target_indices.append("NIFTY 50")
                        if is_bn_exp and index_name == "NIFTY BANK":
                            target_indices.append("NIFTY BANK")

                        if index_name in target_indices:
                            step = 50 if index_name == "NIFTY 50" else 100
                            atm_k = int(round(current_price / step) * step)
                            exp_type = "MONTHLY EXPIRY" if is_monthly_exp else "WEEKLY EXPIRY"
                            
                            hz_msg = (
                                f"🔥 HERO-ZERO {exp_type} SETUP (01:15 PM IST)\n\n"
                                f"📍 Index: {index_name} (Spot: {current_price:.2f})\n"
                                f"🎯 Focus Strikes (₹15 - ₹35 Low Premium):\n"
                                f"• Call Option: {atm_k + step} CE\n"
                                f"• Put Option: {atm_k - step} PE\n\n"
                                f"⚡ Strategy: Target MOMENTUM SPIKE breakout!"
                            )
                            send_telegram_alert(hz_msg)
                            hero_zero_sent = True

                    # 4. POSITION TRACKING & EXITS
                    if trade is not None:
                        # 03:20 PM Auto Exit
                        if is_market_closing:
                            pnl = current_price - trade['entry'] if trade['type'] == 'BUY' else trade['entry'] - current_price
                            trade['exit_price'] = current_price
                            trade['exit_time'] = current_time_str
                            trade['pnl'] = pnl
                            trade['status'] = 'Auto-Exit (03:20 PM)'
                            record_to_monthly_ledger(trade)

                            send_telegram_alert(
                                f"⏰ AUTO EXIT (03:20 PM)\n"
                                f"⚡ Strategy: MOMENTUM SPIKE\n"
                                f"Index: {index_name}\n"
                                f"💵 Exit Price: {current_price:.2f}\n"
                                f"📈 Points: {pnl:+.2f}"
                            )
                            active_trades[index_name] = None
                            save_trades(active_trades)
                            continue

                        # BUY ORDERS
                        if trade['type'] == 'BUY':
                            if not trade.get('t1_hit') and current_price >= trade['t1']:
                                trade['t1_hit'] = True
                                trade['t1_time'] = current_time_str
                                trade_stats['target_hits'] += 1
                                save_trades(active_trades)
                                send_telegram_alert(
                                    f"🎯 TARGET 1 HIT!\n"
                                    f"⚡ Strategy: MOMENTUM SPIKE\n"
                                    f"Index: {index_name} (CALL)\n"
                                    f"💵 Target Price: {trade['t1']:.2f}\n"
                                    f"Current: {current_price:.2f}"
                                )

                            if not trade.get('t2_hit') and current_price >= trade['t2']:
                                trade['t2_hit'] = True
                                trade['t2_time'] = current_time_str
                                trade_stats['target_hits'] += 1
                                save_trades(active_trades)
                                send_telegram_alert(
                                    f"🎯 TARGET 2 HIT!\n"
                                    f"⚡ Strategy: MOMENTUM SPIKE\n"
                                    f"Index: {index_name} (CALL)\n"
                                    f"💵 Target Price: {trade['t2']:.2f}\n"
                                    f"Current: {current_price:.2f}"
                                )

                            if current_price >= trade['t3']:
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
                                    f"🏆 TARGET 3 ACHIEVED!\n"
                                    f"⚡ Strategy: MOMENTUM SPIKE\n"
                                    f"Index: {index_name} (CALL)\n"
                                    f"💵 Final Target: {trade['t3']:.2f}\n"
                                    f"Trade Completed."
                                )
                                active_trades[index_name] = None
                                save_trades(active_trades)

                            elif current_price <= trade['sl']:
                                trade_stats['sl_hits'] += 1
                                pnl = current_price - trade['entry']
                                trade['sl_hit'] = True
                                trade['sl_time'] = current_time_str
                                trade['exit_price'] = current_price
                                trade['exit_time'] = current_time_str
                                trade['pnl'] = pnl
                                trade['status'] = 'Target 1 & Exit' if trade.get('t1_hit') else 'SL Hit'
                                record_to_monthly_ledger(trade)

                                active_trades[index_name] = None
                                save_trades(active_trades)
                                
                                if not trade.get('t1_hit', False):
                                    send_telegram_alert(
                                        f"🛑 STOP LOSS HIT!\n"
                                        f"⚡ Strategy: MOMENTUM SPIKE\n"
                                        f"Index: {index_name} (CALL)\n"
                                        f"🛑 SL Price: {trade['sl']:.2f}"
                                    )

                        # SELL ORDERS
                        elif trade['type'] == 'SELL':
                            if not trade.get('t1_hit') and current_price <= trade['t1']:
                                trade['t1_hit'] = True
                                trade['t1_time'] = current_time_str
                                trade_stats['target_hits'] += 1
                                save_trades(active_trades)
                                send_telegram_alert(
                                    f"🎯 TARGET 1 HIT!\n"
                                    f"⚡ Strategy: MOMENTUM SPIKE\n"
                                    f"Index: {index_name} (PUT)\n"
                                    f"💵 Target Price: {trade['t1']:.2f}\n"
                                    f"Current: {current_price:.2f}"
                                )

                            if not trade.get('t2_hit') and current_price <= trade['t2']:
                                trade['t2_hit'] = True
                                trade['t2_time'] = current_time_str
                                trade_stats['target_hits'] += 1
                                save_trades(active_trades)
                                send_telegram_alert(
                                    f"🎯 TARGET 2 HIT!\n"
                                    f"⚡ Strategy: MOMENTUM SPIKE\n"
                                    f"Index: {index_name} (PUT)\n"
                                    f"💵 Target Price: {trade['t2']:.2f}\n"
                                    f"Current: {current_price:.2f}"
                                )

                            if current_price <= trade['t3']:
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
                                    f"🏆 TARGET 3 ACHIEVED!\n"
                                    f"⚡ Strategy: MOMENTUM SPIKE\n"
                                    f"Index: {index_name} (PUT)\n"
                                    f"💵 Final Target: {trade['t3']:.2f}\n"
                                    f"Trade Completed."
                                )
                                active_trades[index_name] = None
                                save_trades(active_trades)

                            elif current_price >= trade['sl']:
                                trade_stats['sl_hits'] += 1
                                pnl = trade['entry'] - current_price
                                trade['sl_hit'] = True
                                trade['sl_time'] = current_time_str
                                trade['exit_price'] = current_price
                                trade['exit_time'] = current_time_str
                                trade['pnl'] = pnl
                                trade['status'] = 'Target 1 & Exit' if trade.get('t1_hit') else 'SL Hit'
                                record_to_monthly_ledger(trade)

                                active_trades[index_name] = None
                                save_trades(active_trades)
                                
                                if not trade.get('t1_hit', False):
                                    send_telegram_alert(
                                        f"🛑 STOP LOSS HIT!\n"
                                        f"⚡ Strategy: MOMENTUM SPIKE\n"
                                        f"Index: {index_name} (PUT)\n"
                                        f"🛑 SL Price: {trade['sl']:.2f}"
                                    )

                    # 5. CANDLE AGGREGATION & 5 EMA SETUP
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

                            # Sell Alert: Candle totally above 5 EMA
                            if last_c['Low'] > last_c['EMA5']:
                                alert_candles[index_name]["sell_alert"] = {'high': last_c['High'], 'low': last_c['Low']}
                            else:
                                alert_candles[index_name]["sell_alert"] = None

                            # Buy Alert: Candle totally below 5 EMA
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

                    # 6. INSTANT SIGNAL GENERATION
                    if can_take_trades and active_trades[index_name] is None:
                        # SELL BREAKOUT
                        s_alert = alert_candles[index_name]["sell_alert"]
                        if s_alert and current_price < s_alert['low']:
                            risk = round(s_alert['high'] - s_alert['low'], 2)
                            if risk >= 8.0:
                                trade_stats['total_signals'] += 1
                                sl = round(s_alert['high'], 2)
                                t1 = round(current_price - (risk * 1.5), 2)
                                t2 = round(current_price - (risk * 2.0), 2)
                                t3 = round(current_price - (risk * 3.0), 2)
                                active_trades[index_name] = {
                                    'date': today_date_str, 'index': index_name,
                                    'type': 'SELL', 'entry': current_price, 'entry_time': current_time_str,
                                    'sl': sl, 'sl_hit': False, 'sl_time': None,
                                    't1': t1, 't1_hit': False, 't1_time': None,
                                    't2': t2, 't2_hit': False, 't2_time': None,
                                    't3': t3, 't3_hit': False, 't3_time': None
                                }
                                save_trades(active_trades)
                                alert_candles[index_name]["sell_alert"] = None

                                send_telegram_alert(
                                    f"🔴 {index_name} SELL SIGNAL\n\n"
                                    f"⚡ Strategy: MOMENTUM SPIKE\n"
                                    f"⏰ Time: {current_time_str}\n"
                                    f"💵 Entry: {current_price:.2f}\n"
                                    f"🛑 Stop Loss: {sl:.2f}\n\n"
                                    f"🎯 Target 1: {t1:.2f}\n"
                                    f"🎯 Target 2: {t2:.2f}\n"
                                    f"🎯 Target 3: {t3:.2f}"
                                )

                        # BUY BREAKOUT
                        b_alert = alert_candles[index_name]["buy_alert"]
                        if b_alert and current_price > b_alert['high']:
                            risk = round(b_alert['high'] - b_alert['low'], 2)
                            if risk >= 8.0:
                                trade_stats['total_signals'] += 1
                                sl = round(b_alert['low'], 2)
                                t1 = round(current_price + (risk * 1.5), 2)
                                t2 = round(current_price + (risk * 2.0), 2)
                                t3 = round(current_price + (risk * 3.0), 2)
                                active_trades[index_name] = {
                                    'date': today_date_str, 'index': index_name,
                                    'type': 'BUY', 'entry': current_price, 'entry_time': current_time_str,
                                    'sl': sl, 'sl_hit': False, 'sl_time': None,
                                    't1': t1, 't1_hit': False, 't1_time': None,
                                    't2': t2, 't2_hit': False, 't2_time': None,
                                    't3': t3, 't3_hit': False, 't3_time': None
                                }
                                save_trades(active_trades)
                                alert_candles[index_name]["buy_alert"] = None

                                send_telegram_alert(
                                    f"🟢 {index_name} BUY SIGNAL\n\n"
                                    f"⚡ Strategy: MOMENTUM SPIKE\n"
                                    f"⏰ Time: {current_time_str}\n"
                                    f"💵 Entry: {current_price:.2f}\n"
                                    f"🛑 Stop Loss: {sl:.2f}\n\n"
                                    f"🎯 Target 1: {t1:.2f}\n"
                                    f"🎯 Target 2: {t2:.2f}\n"
                                    f"🎯 Target 3: {t3:.2f}"
                                )

            # 7. HOURLY STATUS ALERT (Every Hour with +/- Points & %)
            if now.minute == 0 and now.hour != last_heartbeat_hour and (9 <= now.hour <= 15):
                last_heartbeat_hour = now.hour
                hb_msg = f"💓 HOURLY STATUS ALERT\n⏰ Time: {current_time_str}\n\n"
                for idx, prc in prices_dict.items():
                    prev_c = prev_close_dict.get(idx, prc)
                    diff = prc - prev_c
                    pct = (diff / prev_c) * 100 if prev_c else 0
                    sign = "+" if diff >= 0 else ""
                    hb_msg += f"• {idx}: {prc:.2f} ({sign}{diff:.2f} | {sign}{pct:.2f}%)\n"
                send_telegram_alert(hb_msg)

        time.sleep(5)
    except Exception as e:
        print(f"Loop Exception: {e}")
        time.sleep(5)
