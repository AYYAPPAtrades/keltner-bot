import os
import sys
import json
import time
import pytz
import logging
import requests
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from datetime import datetime, timedelta, time as dtime
from concurrent.futures import ThreadPoolExecutor
import pandas as pd
import yfinance as yf
from nselib import capital_market

from reportlab.lib.pagesizes import letter, landscape
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

# ==========================================
# 1. LOGGING & BASIC CONFIGURATION
# ==========================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("SAS_TRACKER")

IST = pytz.timezone("Asia/Kolkata")

# Credentials & Bot Tokens
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8804327561:AAECrvtU0MCYB80L0ZchoKy_YDpwJ52zQA8")
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID", "-1004416495917")
TELEGRAM_ADMIN_CHAT_ID = os.getenv("TELEGRAM_ADMIN_CHAT_ID", "6789591588")
PUBLIC_ALERT_IDS = [TELEGRAM_CHANNEL_ID, TELEGRAM_ADMIN_CHAT_ID]

# Email Credentials
SENDER_EMAIL = "shinos99@gmail.com"
SENDER_APP_PASSWORD = "xufefwfphwsomsnu"
RECEIVER_EMAILS = ["shinos99@gmail.com"]

# Strategy Name
STRATEGY_DISPLAY_NAME = "SAS LEVEL PULSE"

# Watchlist & Tickers (NIFTY 50 Only)
INDEX_WATCHLIST = ["NIFTY 50"]
YF_TICKERS = {"NIFTY 50": "^NSEI"}

DAILY_STATE_FILE = "daily_active_trades.json"
EXPIRY_LEDGER_FILE = "expiry_trades_ledger.json"

telegram_session = requests.Session()
executor = ThreadPoolExecutor(max_workers=4)

# ==========================================
# 2. DISPATCH FUNCTIONS
# ==========================================
def _send_single_telegram(cid, message, parse_mode):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": cid, "text": message, "parse_mode": parse_mode}
    try:
        telegram_session.post(url, json=payload, timeout=10)
    except Exception as e:
        logger.error(f"[TELEGRAM ERROR] {cid}: {e}")

def send_telegram_alert(message, parse_mode="HTML", chat_id=None):
    if not TELEGRAM_BOT_TOKEN:
        return
    targets = [chat_id] if chat_id else PUBLIC_ALERT_IDS
    for cid in targets:
        if cid:
            executor.submit(_send_single_telegram, cid, message, parse_mode)

def send_telegram_document(file_path, caption=""):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendDocument"
    for chat_id in PUBLIC_ALERT_IDS:
        try:
            with open(file_path, 'rb') as doc:
                telegram_session.post(url, data={'chat_id': chat_id, 'caption': caption}, files={'document': doc}, timeout=25)
        except Exception as e:
            logger.error(f"Telegram Doc Error ({chat_id}): {e}")

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
        logger.info("PDF Report emailed successfully.")
    except Exception as e:
        logger.error(f"Email Dispatch Warning: {e}")

# ==========================================
# 3. NSE HOLIDAY CHECK
# ==========================================
def get_nse_holidays():
    try:
        holidays_df = capital_market.holiday_trading()
        if holidays_df is not None and not holidays_df.empty and 'tradingDate' in holidays_df.columns:
            return [datetime.strptime(d, '%d-%b-%Y').date() for d in holidays_df['tradingDate'].values]
    except Exception:
        pass
    return []

holiday_dates = get_nse_holidays()
today_dt = datetime.now(IST)
today_date = today_dt.date()
today_str_display = today_dt.strftime('%d-%b-%Y')

if today_dt.weekday() in [5, 6]:
    day_name = "Saturday" if today_dt.weekday() == 5 else "Sunday"
    send_telegram_alert(f"🏖️ <b>WEEKEND MARKET HOLIDAY ({day_name})</b>\n• Market is closed today.")
    sys.exit(0)

if today_date in holiday_dates:
    send_telegram_alert(f"🏖️ <b>NSE MARKET HOLIDAY TODAY ({today_str_display})</b>\n• Market is closed.")
    sys.exit(0)

def is_today_monthly_tuesday_expiry():
    today = datetime.now(IST).date()
    next_month = today.replace(day=28) + timedelta(days=4)
    last_day_of_month = next_month - timedelta(days=next_month.day)
    cur_day = last_day_of_month
    while cur_day.weekday() != 1:
        cur_day -= timedelta(days=1)
    while cur_day in holiday_dates or cur_day.weekday() in [5, 6]:
        cur_day -= timedelta(days=1)
    return today == cur_day

# ==========================================
# 4. STATE & LEDGER MANAGEMENT
# ==========================================
def load_backup_state():
    today_str = datetime.now(IST).strftime("%Y-%m-%d")
    if os.path.exists(DAILY_STATE_FILE):
        try:
            with open(DAILY_STATE_FILE, "r") as f:
                data = json.load(f)
                if data.get("date") == today_str:
                    return data.get("active_trade")
        except Exception:
            pass
    return None

def save_daily_state(active_trade):
    today_str = datetime.now(IST).strftime("%Y-%m-%d")
    try:
        with open(DAILY_STATE_FILE, "w") as f:
            json.dump({"date": today_str, "active_trade": active_trade}, f, indent=4)
    except Exception:
        pass

def load_expiry_ledger():
    if os.path.exists(EXPIRY_LEDGER_FILE):
        try:
            with open(EXPIRY_LEDGER_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def record_trade_to_ledger(trade_record):
    ledger = load_expiry_ledger()
    ledger.append(trade_record)
    try:
        with open(EXPIRY_LEDGER_FILE, "w") as f:
            json.dump(ledger, f, indent=4)
    except Exception as e:
        pass

def clear_expiry_ledger():
    try:
        if os.path.exists(EXPIRY_LEDGER_FILE):
            os.remove(EXPIRY_LEDGER_FILE)
    except Exception:
        pass

# ==========================================
# 5. PDF REPORT GENERATOR
# ==========================================
def generate_pdf_report(filename, title_text, date_text, logs, total_pnl):
    doc = SimpleDocTemplate(filename, pagesize=landscape(letter), rightMargin=15, leftMargin=15, topMargin=20, bottomMargin=20)
    styles = getSampleStyleSheet()
    elements = []

    title_style = ParagraphStyle('RepTitle', parent=styles['Heading1'], fontSize=14, leading=17, textColor=colors.HexColor("#1A365D"), alignment=1)
    elements.append(Paragraph(f"{STRATEGY_DISPLAY_NAME} - {title_text}", title_style))
    pnl_status_text = f"NET POINTS: +{total_pnl:.2f} Pts" if total_pnl >= 0 else f"NET POINTS: {total_pnl:.2f} Pts"
    elements.append(Paragraph(f"Strategy: {STRATEGY_DISPLAY_NAME} | Timeline: {date_text} | Total Events: {len(logs)} | <b>{pnl_status_text}</b>", styles['Normal']))
    elements.append(Spacer(1, 10))

    headers = ["SL", "Date", "Index & Type", "Entry & Time", "Target 1", "Target 2", "Target 3", "Stop Loss", "Points", "Status"]
    table_rows = [headers]

    for i, l in enumerate(logs, 1):
        table_rows.append([
            str(i), l.get('date', '-'), f"{l.get('index', 'NIFTY 50')}\n({l.get('side', '-')})",
            f"{l.get('entry', 0.0):.2f}\n({l.get('time', '-')})",
            f"{l.get('t1', 0.0):.2f}" if l.get('highest_target', 0) >= 1 else "-",
            f"{l.get('t2', 0.0):.2f}" if l.get('highest_target', 0) >= 2 else "-",
            f"{l.get('t3', 0.0):.2f}" if l.get('highest_target', 0) >= 3 else "-",
            f"{l.get('sl', 0.0):.2f}",
            f"{l.get('pnl', 0.0):+.2f}",
            l.get('status', '-')
        ])

    table_rows.append([
        "TOTAL", "-", "-", "-", "-", "-", "-", "TOTAL POINTS", f"{total_pnl:+.2f}", "CYCLE FINISHED"
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
        ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor("#EDF2F7")),
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
    ]))
    elements.append(trade_table)
    doc.build(elements)

# ==========================================
# 6. FAST LIVE MARKET DATA
# ==========================================
def fetch_recent_data():
    try:
        df = yf.download(tickers=YF_TICKERS["NIFTY 50"], period="1d", interval="1m", progress=False)
        if not df.empty:
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            return df
    except Exception as e:
        logger.error(f"Data fetch error: {e}")
    return None

def get_live_nifty_price():
    try:
        all_indices = capital_market.market_watch_all_indices()
        if all_indices is not None and not all_indices.empty:
            nifty_row = all_indices[all_indices['index'] == 'NIFTY 50']
            if not nifty_row.empty:
                return float(str(nifty_row['last'].values[0]).replace(',', ''))
    except Exception:
        pass
    return None

# ==========================================
# 7. CORE EXECUTION ENGINE (30 PTS FIXED RISK)
# ==========================================
def main():
    logger.info("Initializing SAS Level Pulse (30 Pts Momentum Spike Engine)...")

    startup_alert_sent = False
    active_trade = load_backup_state()
    last_heartbeat_hour = -1
    today_date_str = datetime.now(IST).strftime("%Y-%m-%d")

    while True:
        now = datetime.now(IST)
        current_time = now.time()

        # 09:00 AM Engine Alert
        if current_time >= dtime(9, 0) and not startup_alert_sent:
            startup_msg = (
                f"🚀 <b>SAS LEVEL PULSE LIVE</b>\n"
                f"⏰ Time: {now.strftime('%I:%M:%S %p')} IST\n"
                f"📊 Index: NIFTY 50\n"
                f"⚡ Strategy: 30 Pts Fast Momentum Spike Scanner Active"
            )
            send_telegram_alert(startup_msg)
            startup_alert_sent = True

        # Active Scanning Window (09:15 AM - 03:25 PM)
        if dtime(9, 15) <= current_time <= dtime(15, 25):
            df = fetch_recent_data()
            live_price = get_live_nifty_price()

            if df is not None and len(df) >= 12:
                current_price = live_price if live_price else float(df['Close'].iloc[-1])
                
                # Fast Momentum Breakout Metrics
                ema5 = df['Close'].ewm(span=5, adjust=False).mean().iloc[-1]
                ema13 = df['Close'].ewm(span=13, adjust=False).mean().iloc[-1]
                high10 = df['High'].rolling(10).max().iloc[-2]
                low10 = df['Low'].rolling(10).min().iloc[-2]

                # SCENARIO A: MONITOR ACTIVE TRADE
                if active_trade is not None:
                    side = active_trade["side"]
                    entry = active_trade["entry"]
                    t1 = active_trade["t1"]
                    t2 = active_trade["t2"]
                    t3 = active_trade["t3"]
                    sl = active_trade["sl"]

                    if side == "BUY":
                        if current_price >= t3:
                            pnl = t3 - entry
                            active_trade["highest_target"] = 3
                            active_trade["status"] = "Target 3 Achieved"
                            active_trade["exit_price"] = t3
                            active_trade["pnl"] = pnl
                            record_trade_to_ledger(active_trade)
                            send_telegram_alert(f"🎯 <b>TARGET 3 HIT!</b>\nSpot: {current_price:.2f}\nPoints: +{pnl:.2f} Pts")
                            active_trade = None
                            save_daily_state(None)

                        elif current_price >= t2 and active_trade.get("highest_target", 0) < 2:
                            pnl = t2 - entry
                            active_trade["highest_target"] = 2
                            active_trade["sl"] = t1
                            active_trade["locked_pnl"] = pnl
                            send_telegram_alert(f"🎯 <b>TARGET 2 HIT!</b>\nSpot: {current_price:.2f}\nPoints: +{pnl:.2f} Pts")
                            save_daily_state(active_trade)

                        elif current_price >= t1 and active_trade.get("highest_target", 0) < 1:
                            pnl = t1 - entry
                            active_trade["highest_target"] = 1
                            active_trade["sl"] = entry  # Trailing SL to Cost
                            active_trade["locked_pnl"] = pnl
                            send_telegram_alert(f"🎯 <b>TARGET 1 HIT!</b>\nSpot: {current_price:.2f}\nPoints: +{pnl:.2f} Pts\nTrailing SL moved to Cost.")
                            save_daily_state(active_trade)

                        elif current_price <= sl:
                            if active_trade.get("highest_target", 0) >= 1:
                                target_num = active_trade["highest_target"]
                                booked_pnl = active_trade.get("locked_pnl", 0.0)
                                active_trade["status"] = f"Target {target_num} Achieved"
                                active_trade["exit_price"] = active_trade[f"t{target_num}"]
                                active_trade["pnl"] = booked_pnl
                                send_telegram_alert(f"🏁 <b>TRAILING STOP TRIGGERED [BUY]</b>\nSpot: {current_price:.2f}\nPoints: +{booked_pnl:.2f} Pts")
                            else:
                                pnl = sl - entry
                                active_trade["exit_price"] = sl
                                active_trade["pnl"] = pnl
                                active_trade["status"] = "Stop Loss Hit"
                                send_telegram_alert(f"🛑 <b>STOP LOSS HIT!</b>\nSpot: {current_price:.2f}\nPoints: {pnl:.2f} Pts")

                            record_trade_to_ledger(active_trade)
                            active_trade = None
                            save_daily_state(None)

                    elif side == "SELL":
                        if current_price <= t3:
                            pnl = entry - t3
                            active_trade["highest_target"] = 3
                            active_trade["status"] = "Target 3 Achieved"
                            active_trade["exit_price"] = t3
                            active_trade["pnl"] = pnl
                            record_trade_to_ledger(active_trade)
                            send_telegram_alert(f"🎯 <b>TARGET 3 HIT!</b>\nSpot: {current_price:.2f}\nPoints: +{pnl:.2f} Pts")
                            active_trade = None
                            save_daily_state(None)

                        elif current_price <= t2 and active_trade.get("highest_target", 0) < 2:
                            pnl = entry - t2
                            active_trade["highest_target"] = 2
                            active_trade["sl"] = t1
                            active_trade["locked_pnl"] = pnl
                            send_telegram_alert(f"🎯 <b>TARGET 2 HIT!</b>\nSpot: {current_price:.2f}\nPoints: +{pnl:.2f} Pts")
                            save_daily_state(active_trade)

                        elif current_price <= t1 and active_trade.get("highest_target", 0) < 1:
                            pnl = entry - t1
                            active_trade["highest_target"] = 1
                            active_trade["sl"] = entry  # Trailing SL to Cost
                            active_trade["locked_pnl"] = pnl
                            send_telegram_alert(f"🎯 <b>TARGET 1 HIT!</b>\nSpot: {current_price:.2f}\nPoints: +{pnl:.2f} Pts\nTrailing SL moved to Cost.")
                            save_daily_state(active_trade)

                        elif current_price >= sl:
                            if active_trade.get("highest_target", 0) >= 1:
                                target_num = active_trade["highest_target"]
                                booked_pnl = active_trade.get("locked_pnl", 0.0)
                                active_trade["status"] = f"Target {target_num} Achieved"
                                active_trade["exit_price"] = active_trade[f"t{target_num}"]
                                active_trade["pnl"] = booked_pnl
                                send_telegram_alert(f"🏁 <b>TRAILING STOP TRIGGERED [SELL]</b>\nSpot: {current_price:.2f}\nPoints: +{booked_pnl:.2f} Pts")
                            else:
                                pnl = entry - sl
                                active_trade["exit_price"] = sl
                                active_trade["pnl"] = pnl
                                active_trade["status"] = "Stop Loss Hit"
                                send_telegram_alert(f"🛑 <b>STOP LOSS HIT!</b>\nSpot: {current_price:.2f}\nPoints: {pnl:.2f} Pts")

                            record_trade_to_ledger(active_trade)
                            active_trade = None
                            save_daily_state(None)

                # SCENARIO B: SCAN FOR MOMENTUM BREAKOUT
                trigger = None
                if current_price > high10 and ema5 > ema13:
                    trigger = "BUY"
                elif current_price < low10 and ema5 < ema13:
                    trigger = "SELL"

                # Opposite Signal Reversal Exit
                if trigger and active_trade is not None and active_trade["side"] != trigger:
                    rev_pnl = (current_price - active_trade["entry"]) if active_trade["side"] == "BUY" else (active_trade["entry"] - current_price)
                    active_trade["status"] = "Closed due to Reversal"
                    active_trade["exit_price"] = current_price
                    active_trade["pnl"] = rev_pnl
                    record_trade_to_ledger(active_trade)
                    send_telegram_alert(f"🔄 <b>REVERSAL EXIT:</b> Closed previous trade ({rev_pnl:+.2f} Pts). Switching to {trigger}!")
                    active_trade = None
                    save_daily_state(None)

                # New Entry Trigger (30 PTS EXACT RISK & TARGETS)
                if trigger and active_trade is None:
                    entry = current_price
                    entry_time_display = now.strftime('%I:%M:%S %p')
                    
                    risk_pts = 30.0  # 30 Points Stop Loss & 1:1, 1:2, 1:3 Targets

                    if trigger == "BUY":
                        sl = round(entry - risk_pts, 2)
                        t1 = round(entry + risk_pts, 2)
                        t2 = round(entry + (risk_pts * 2.0), 2)
                        t3 = round(entry + (risk_pts * 3.0), 2)
                    else:
                        sl = round(entry + risk_pts, 2)
                        t1 = round(entry - risk_pts, 2)
                        t2 = round(entry - (risk_pts * 2.0), 2)
                        t3 = round(entry - (risk_pts * 3.0), 2)

                    active_trade = {
                        "date": today_date_str,
                        "index": "NIFTY 50",
                        "side": trigger,
                        "entry": entry,
                        "sl": sl,
                        "t1": t1,
                        "t2": t2,
                        "t3": t3,
                        "highest_target": 0,
                        "locked_pnl": 0.0,
                        "time": entry_time_display
                    }
                    save_daily_state(active_trade)

                    # കൃത്യമായി ചോദിച്ച സിമ്പിൾ അലേർട്ട്
                    msg = (
                        f"⚡ <b>{trigger} SIGNAL</b>\n\n"
                        f"• <b>Entry:</b> {entry:.2f}\n"
                        f"• <b>Entry Time:</b> {entry_time_display} IST\n"
                        f"• <b>Spot:</b> {current_price:.2f}\n"
                        f"• <b>Stop Loss:</b> {sl:.2f}\n"
                        f"• <b>T1:</b> {t1:.2f}\n"
                        f"• <b>T2:</b> {t2:.2f}\n"
                        f"• <b>T3:</b> {t3:.2f}"
                    )
                    send_telegram_alert(msg)

                # Hourly Status
                if now.minute == 0 and now.hour != last_heartbeat_hour and (9 <= now.hour <= 15):
                    last_heartbeat_hour = now.hour
                    hb_msg = f"💓 <b>HOURLY UPDATE</b>\n⏰ Time: {now.strftime('%I:%M:00 %p')} IST\n• NIFTY 50: {current_price:.2f}"
                    send_telegram_alert(hb_msg)

        # 03:25 PM Auto Square Off
        if current_time >= dtime(15, 25) and active_trade is not None:
            entry = active_trade["entry"]
            last_prc = current_price if 'current_price' in locals() else entry
            pnl = (last_prc - entry) if active_trade["side"] == "BUY" else (entry - last_prc)
            active_trade["status"] = "EOD Auto-Exit"
            active_trade["exit_price"] = last_prc
            active_trade["pnl"] = pnl
            record_trade_to_ledger(active_trade)
            active_trade = None
            save_daily_state(None)
            send_telegram_alert(f"🔔 <b>MARKET CLOSING (03:25 PM):</b> Position squared off ({pnl:+.2f} Pts).")

        # 03:40 PM Reports
        if current_time >= dtime(15, 40):
            ledger = load_expiry_ledger()
            today_trades = [t for t in ledger if t.get("date") == today_date_str]
            today_pnl = sum(t.get("pnl", 0.0) for t in today_trades)
            
            daily_summary = (
                f"📊 <b>DAILY PERFORMANCE SUMMARY (03:40 PM)</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"📅 Date: {today_str_display}\n"
                f"⚡ Strategy: {STRATEGY_DISPLAY_NAME}\n"
                f"• Today Trades: {len(today_trades)}\n"
                f"📈 Day Net Points: {today_pnl:+.2f} Pts\n"
                f"━━━━━━━━━━━━━━━━━━━━"
            )
            send_telegram_alert(daily_summary)

            daily_pdf = f"Daily_Report_{today_str_display}.pdf"
            try:
                generate_pdf_report(daily_pdf, "DAILY PERFORMANCE REPORT", today_str_display, today_trades, today_pnl)
                send_telegram_document(daily_pdf, caption=f"📄 Daily Report ({today_str_display}) | Net: {today_pnl:+.2f} Pts")
                send_email_with_pdf(daily_pdf, f"Daily Report - {today_str_display}", daily_summary)
            except Exception as e:
                logger.error(f"Daily PDF Error: {e}")

            if is_today_monthly_tuesday_expiry():
                total_cycle_pnl = sum(t.get("pnl", 0.0) for t in ledger)
                expiry_pdf = f"Monthly_Expiry_Report_{today_str_display}.pdf"
                try:
                    generate_pdf_report(expiry_pdf, "MONTHLY EXPIRY CYCLE REPORT", today_str_display, ledger, total_cycle_pnl)
                    send_telegram_document(expiry_pdf, caption=f"📄 Monthly Expiry Report | Net: {total_cycle_pnl:+.2f} Pts")
                    send_email_with_pdf(expiry_pdf, f"Monthly Expiry Report - {today_str_display}", daily_summary)
                    clear_expiry_ledger()
                except Exception as e:
                    logger.error(f"Expiry PDF Error: {e}")

            send_telegram_alert("🛑 <b>MARKET CLOSED:</b> Engine stopped.")
            break

        time.sleep(1)

if __name__ == "__main__":
    main()
