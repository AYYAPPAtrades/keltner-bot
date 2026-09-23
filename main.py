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

# Watchlist & Tickers (NIFTY 50 Only)
INDEX_WATCHLIST = ["NIFTY 50"]
YF_TICKERS = {"NIFTY 50": "^NSEI"}

# State Files
DAILY_STATE_FILE = "daily_active_trades.json"
EXPIRY_LEDGER_FILE = "expiry_trades_ledger.json"

telegram_session = requests.Session()
executor = ThreadPoolExecutor(max_workers=4)

# ==========================================
# 2. DISPATCH FUNCTIONS (MESSAGES, PDF & EMAIL)
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
# 3. NSE HOLIDAY & WEEKEND DETECTION
# ==========================================
def get_nse_holidays():
    try:
        holidays_df = capital_market.holiday_trading()
        if holidays_df is not None and not holidays_df.empty and 'tradingDate' in holidays_df.columns:
            return [datetime.strptime(d, '%d-%b-%Y').date() for d in holidays_df['tradingDate'].values]
    except Exception as e:
        logger.error(f"Error fetching NSE holidays: {e}")
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
                    logger.info("Daily state restored successfully.")
                    return data.get("active_trade")
        except Exception as e:
            logger.error(f"Error loading daily state: {e}")
    return None

def save_daily_state(active_trade):
    today_str = datetime.now(IST).strftime("%Y-%m-%d")
    data = {"date": today_str, "active_trade": active_trade}
    try:
        with open(DAILY_STATE_FILE, "w") as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        logger.error(f"Error saving daily state: {e}")

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
        logger.error(f"Error saving ledger: {e}")

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
    elements.append(Paragraph(f"SAS LEVEL TRACKER - {title_text}", title_style))
    pnl_status_text = f"NET POINTS: +{total_pnl:.2f} Pts" if total_pnl >= 0 else f"NET POINTS: {total_pnl:.2f} Pts"
    elements.append(Paragraph(f"Strategy: SAS LEVEL TRACKER | Timeline: {date_text} | Total Events: {len(logs)} | <b>{pnl_status_text}</b>", styles['Normal']))
    elements.append(Spacer(1, 10))

    headers = ["SL", "Date", "Index & Type", "Entry & Time", "Level 1", "Level 2", "Level 3", "Threshold", "Points", "Status"]
    table_rows = [headers]

    for i, l in enumerate(logs, 1):
        table_rows.append([
            str(i), l.get('date', '-'), f"{l.get('index', 'NIFTY 50')}\n({l.get('side', l.get('type', '-'))})",
            f"{l.get('entry', 0.0):.2f}\n({l.get('time', l.get('entry_time', '-'))})",
            f"{l.get('t1', 0.0):.2f}" if l.get('highest_target', 0) >= 1 or l.get('t1_hit') else "-",
            f"{l.get('t2', 0.0):.2f}" if l.get('highest_target', 0) >= 2 or l.get('t2_hit') else "-",
            f"{l.get('t3', 0.0):.2f}" if l.get('highest_target', 0) >= 3 or l.get('t3_hit') else "-",
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
# 6. MARKET DATA & CALCULATIONS (30 PTS 50/50)
# ==========================================
def fetch_previous_ohlc():
    try:
        ticker = yf.Ticker(YF_TICKERS["NIFTY 50"])
        df = ticker.history(period="5d", interval="1d")
        if len(df) >= 2:
            prev_day = df.iloc[-2]
            return float(prev_day['High']), float(prev_day['Low']), float(prev_day['Close'])
    except Exception as e:
        logger.error(f"Error fetching OHLC: {e}")
    return None, None, None

def calculate_levels(high, low, close):
    diff = high - low
    levels = {
        "H5": close + (1.1 * diff),
        "H4": close + (diff * 1.1 / 2.0),
        "H3": close + (diff * 1.1 / 4.0),
        "L3": close - (diff * 1.1 / 4.0),
        "L4": close - (diff * 1.1 / 2.0),
        "L5": close - (1.1 * diff),
        "Dynamic_Risk": 30.0  # 30 Points Fixed Risk
    }
    return levels

def get_live_tick():
    try:
        data = yf.download(tickers=YF_TICKERS["NIFTY 50"], period="1d", interval="1m", progress=False)
        if not data.empty:
            if isinstance(data.columns, pd.MultiIndex):
                data.columns = data.columns.get_level_values(0)
            return float(data['Close'].iloc[-1])
    except Exception as e:
        logger.error(f"Error fetching live tick: {e}")
    return None

# ==========================================
# 7. CORE EXECUTION BOT
# ==========================================
def main():
    logger.info("Initializing SAS Level Tracker Bot...")

    high, low, close = fetch_previous_ohlc()
    if not high:
        logger.error("Failed to obtain previous session OHLC.")
        return

    levels = calculate_levels(high, low, close)
    dynamic_risk = levels["Dynamic_Risk"]
    logger.info(f"NIFTY Levels Loaded: R4={levels['H4']:.2f}, R3={levels['H3']:.2f}, S3={levels['L3']:.2f}, S4={levels['L4']:.2f}, Risk={dynamic_risk} Pts")

    startup_alert_sent = False
    levels_posted = False
    active_trade = load_backup_state()
    prev_tick = None
    last_heartbeat_hour = -1
    today_date_str = datetime.now(IST).strftime("%Y-%m-%d")

    sl_cooldown_until = None
    last_sl_side = None

    while True:
        now = datetime.now(IST)
        current_time = now.time()

        # 09:00 AM Engine Alert
        if current_time >= dtime(9, 0) and not startup_alert_sent:
            startup_msg = (
                f"🚀 <b>SAS LEVEL TRACKER LIVE (09:00 AM)</b>\n\n"
                f"⚡ <b>Strategy:</b> SAS LEVEL TRACKER\n"
                f"📊 <b>Index:</b> NIFTY 50\n"
                f"🕒 <b>Time:</b> {now.strftime('%I:%M:%S %p')} IST\n"
                f"🛡️ <b>Engine Status:</b> Fast Real-Time Scanner Active."
            )
            send_telegram_alert(startup_msg)
            startup_alert_sent = True

        # 09:05 AM - Levels Alert
        if current_time >= dtime(9, 5) and not levels_posted:
            msg = (
                f"<b>⚡ DAILY MOMENTUM SPIKE LEVELS (09:05 AM)</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"📊 <b>Index:</b> NIFTY 50\n"
                f"🔹 <b>Bullish Breakout (R4):</b> {levels['H4']:.2f}\n"
                f"🔹 <b>Resistance Reversal (R3):</b> {levels['H3']:.2f}\n"
                f"🔸 <b>Support Reversal (S3):</b> {levels['L3']:.2f}\n"
                f"🔸 <b>Bearish Breakdown (S4):</b> {levels['L4']:.2f}\n"
                f"🛡️ <b>Day Dynamic Risk:</b> {dynamic_risk:.2f} Pts\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"<i>Tracking live tick-by-tick momentum.</i>\n"
                f"⚠️ <i>Strictly for educational study only. Not SEBI registered.</i>"
            )
            send_telegram_alert(msg)
            levels_posted = True

        # Active Scanning Window (09:15 AM - 03:25 PM)
        if dtime(9, 15) <= current_time <= dtime(15, 25):
            current_tick = get_live_tick()
            if current_tick:
                if prev_tick is None:
                    prev_tick = current_tick
                    time.sleep(1)
                    continue

                # SCENARIO A: MONITOR ACTIVE TRADE
                if active_trade is not None:
                    side = active_trade["side"]
                    entry = active_trade["entry"]
                    t1 = active_trade["t1"]
                    t2 = active_trade["t2"]
                    t3 = active_trade["t3"]
                    sl = active_trade["sl"]

                    if side == "BUY":
                        if current_tick >= t3:
                            pnl = t3 - entry
                            active_trade["highest_target"] = 3
                            active_trade["status"] = "Target 3 Achieved"
                            active_trade["exit_price"] = t3
                            active_trade["pnl"] = pnl
                            record_trade_to_ledger(active_trade)
                            send_telegram_alert(f"🎯 <b>TARGET 3 ACHIEVED! [BUY]</b>\nPrice: {current_tick:.2f}\nPoints: +{pnl:.2f} Pts\nTrade closed in full profit.")
                            active_trade = None
                            save_daily_state(None)

                        elif current_tick >= t2 and active_trade.get("highest_target", 0) < 2:
                            pnl = t2 - entry
                            active_trade["highest_target"] = 2
                            active_trade["sl"] = t1
                            active_trade["locked_pnl"] = pnl
                            send_telegram_alert(f"🎯 <b>TARGET 2 ACHIEVED! [BUY]</b>\nPrice: {current_tick:.2f}\nPoints: +{pnl:.2f} Pts\nSL trailed to Target 1 ({t1:.2f}).")
                            save_daily_state(active_trade)

                        elif current_tick >= t1 and active_trade.get("highest_target", 0) < 1:
                            pnl = t1 - entry
                            active_trade["highest_target"] = 1
                            active_trade["sl"] = entry
                            active_trade["locked_pnl"] = pnl
                            send_telegram_alert(f"🎯 <b>TARGET 1 ACHIEVED! [BUY]</b>\nPrice: {current_tick:.2f}\nPoints: +{pnl:.2f} Pts\nSL trailed safely to Cost ({entry:.2f}). T2 & T3 Active!")
                            save_daily_state(active_trade)

                        elif current_tick <= sl:
                            if active_trade.get("highest_target", 0) >= 1:
                                target_num = active_trade["highest_target"]
                                booked_pnl = active_trade.get("locked_pnl", 0.0)
                                active_trade["status"] = f"Target {target_num} Achieved"
                                active_trade["exit_price"] = active_trade[f"t{target_num}"]
                                active_trade["pnl"] = booked_pnl
                                send_telegram_alert(f"🏁 <b>TRAILING STOP TRIGGERED [BUY]</b>\nPrice: {current_tick:.2f}\nExited with profit booked at Target {target_num} (+{booked_pnl:.2f} Pts).")
                            else:
                                pnl = sl - entry
                                active_trade["exit_price"] = sl
                                active_trade["pnl"] = pnl
                                active_trade["status"] = "Stop Loss Hit"
                                send_telegram_alert(f"🛑 <b>STOP LOSS HIT [BUY]</b>\nPrice: {current_tick:.2f}\nPoints: {pnl:.2f} Pts\nExited position.")
                                sl_cooldown_until = now + timedelta(minutes=3)
                                last_sl_side = "BUY"

                            record_trade_to_ledger(active_trade)
                            active_trade = None
                            save_daily_state(None)

                    elif side == "SELL":
                        if current_tick <= t3:
                            pnl = entry - t3
                            active_trade["highest_target"] = 3
                            active_trade["status"] = "Target 3 Achieved"
                            active_trade["exit_price"] = t3
                            active_trade["pnl"] = pnl
                            record_trade_to_ledger(active_trade)
                            send_telegram_alert(f"🎯 <b>TARGET 3 ACHIEVED! [SELL]</b>\nPrice: {current_tick:.2f}\nPoints: +{pnl:.2f} Pts\nTrade closed in full profit.")
                            active_trade = None
                            save_daily_state(None)

                        elif current_tick <= t2 and active_trade.get("highest_target", 0) < 2:
                            pnl = entry - t2
                            active_trade["highest_target"] = 2
                            active_trade["sl"] = t1
                            active_trade["locked_pnl"] = pnl
                            send_telegram_alert(f"🎯 <b>TARGET 2 ACHIEVED! [SELL]</b>\nPrice: {current_tick:.2f}\nPoints: +{pnl:.2f} Pts\nSL trailed to Target 1 ({t1:.2f}).")
                            save_daily_state(active_trade)

                        elif current_tick <= t1 and active_trade.get("highest_target", 0) < 1:
                            pnl = entry - t1
                            active_trade["highest_target"] = 1
                            active_trade["sl"] = entry
                            active_trade["locked_pnl"] = pnl
                            send_telegram_alert(f"🎯 <b>TARGET 1 ACHIEVED! [SELL]</b>\nPrice: {current_tick:.2f}\nPoints: +{pnl:.2f} Pts\nSL trailed safely to Cost ({entry:.2f}). T2 & T3 Active!")
                            save_daily_state(active_trade)

                        elif current_tick >= sl:
                            if active_trade.get("highest_target", 0) >= 1:
                                target_num = active_trade["highest_target"]
                                booked_pnl = active_trade.get("locked_pnl", 0.0)
                                active_trade["status"] = f"Target {target_num} Achieved"
                                active_trade["exit_price"] = active_trade[f"t{target_num}"]
                                active_trade["pnl"] = booked_pnl
                                send_telegram_alert(f"🏁 <b>TRAILING STOP TRIGGERED [SELL]</b>\nPrice: {current_tick:.2f}\nExited with profit booked at Target {target_num} (+{booked_pnl:.2f} Pts).")
                            else:
                                pnl = entry - sl
                                active_trade["exit_price"] = sl
                                active_trade["pnl"] = pnl
                                active_trade["status"] = "Stop Loss Hit"
                                send_telegram_alert(f"🛑 <b>STOP LOSS HIT [SELL]</b>\nPrice: {current_tick:.2f}\nPoints: {pnl:.2f} Pts\nExited position.")
                                sl_cooldown_until = now + timedelta(minutes=3)
                                last_sl_side = "SELL"

                            record_trade_to_ledger(active_trade)
                            active_trade = None
                            save_daily_state(None)

                # SCENARIO B: SCAN FOR NEW TRADES
                trigger = None
                trade_type = ""
                risk_pts = dynamic_risk

                if prev_tick < levels["H4"] and current_tick >= levels["H4"]:
                    trigger = "BUY"
                    trade_type = "Breakout Spike (Above R4)"
                elif prev_tick <= levels["L3"] and current_tick > levels["L3"]:
                    trigger = "BUY"
                    trade_type = "Support Bounce (Reversal from S3)"
                elif prev_tick > levels["L4"] and current_tick <= levels["L4"]:
                    trigger = "SELL"
                    trade_type = "Breakdown Spike (Below S4)"
                elif prev_tick >= levels["H3"] and current_tick < levels["H3"]:
                    trigger = "SELL"
                    trade_type = "Resistance Rejection (Reversal from R3)"

                if trigger and sl_cooldown_until and now < sl_cooldown_until and trigger == last_sl_side:
                    trigger = None

                if trigger and active_trade is not None:
                    if active_trade.get("highest_target", 0) >= 1 and active_trade["side"] != trigger:
                        target_num = active_trade["highest_target"]
                        booked_pnl = active_trade.get("locked_pnl", 0.0)
                        active_trade["status"] = f"Target {target_num} Achieved (Switched)"
                        active_trade["exit_price"] = active_trade[f"t{target_num}"]
                        active_trade["pnl"] = booked_pnl
                        record_trade_to_ledger(active_trade)
                        send_telegram_alert(
                            f"🔄 <b>POSITION SWITCHED TO {trigger}!</b>\n"
                            f"Old {active_trade['side']} position safely closed with Target {target_num} profit (+{booked_pnl:.2f} Pts)."
                        )
                        active_trade = None
                        save_daily_state(None)
                    else:
                        trigger = None

                if trigger and active_trade is None:
                    entry = current_tick
                    entry_time_display = now.strftime('%I:%M:%S %p')
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
                        "type": trade_type,
                        "entry": entry,
                        "sl": sl,
                        "initial_sl": sl,
                        "t1": t1,
                        "t2": t2,
                        "t3": t3,
                        "highest_target": 0,
                        "locked_pnl": 0.0,
                        "time": entry_time_display
                    }
                    save_daily_state(active_trade)

                    # Points text removed from SL & Targets
                    msg = (
                        f"⚡ <b>SAS LEVEL TRACKER SIGNAL</b>\n"
                        f"━━━━━━━━━━━━━━━━━━━━\n"
                        f"📊 <b>Index:</b> NIFTY 50\n"
                        f"🎯 <b>Action:</b> {trigger}\n"
                        f"⏰ <b>Entry Time:</b> {entry_time_display} IST\n"
                        f"🔹 <b>Entry:</b> {entry:.2f}\n"
                        f"🛑 <b>Stop Loss:</b> {sl:.2f}\n"
                        f"🎯 <b>Target 1:</b> {t1:.2f}\n"
                        f"🎯 <b>Target 2:</b> {t2:.2f}\n"
                        f"🎯 <b>Target 3:</b> {t3:.2f}\n"
                        f"━━━━━━━━━━━━━━━━━━━━"
                    )
                    send_telegram_alert(msg)

                if now.minute == 0 and now.hour != last_heartbeat_hour and (9 <= now.hour <= 15):
                    last_heartbeat_hour = now.hour
                    diff = current_tick - close
                    pct = (diff / close) * 100 if close != 0 else 0.0
                    hb_msg = (
                        f"💓 <b>HOURLY STATUS ALERT</b>\n"
                        f"⏰ Time: {now.strftime('%I:%M:00 %p')} IST\n\n"
                        f"• NIFTY 50: {current_tick:.2f} ({diff:+.2f} | {pct:+.2f}%)\n"
                    )
                    send_telegram_alert(hb_msg)

                prev_tick = current_tick

        # Auto Square Off at 03:25 PM
        if current_time >= dtime(15, 25) and active_trade is not None:
            entry = active_trade["entry"]
            last_prc = current_tick if current_tick else entry
            pnl = (last_prc - entry) if active_trade["side"] == "BUY" else (entry - last_prc)
            active_trade["status"] = "EOD Auto-Exit"
            active_trade["exit_price"] = last_prc
            active_trade["pnl"] = pnl
            record_trade_to_ledger(active_trade)
            active_trade = None
            save_daily_state(None)
            send_telegram_alert(f"🔔 <b>MARKET CLOSING (03:25 PM):</b> Open position closed ({pnl:+.2f} Pts).")

        # ==============================================================
        # 03:40 PM - DAILY PERFORMANCE & MONTHLY EXPIRY PDF DISPATCH
        # ==============================================================
        if current_time >= dtime(15, 40):
            ledger = load_expiry_ledger()
            today_trades = [t for t in ledger if t.get("date") == today_date_str]
            today_pnl = sum(t.get("pnl", 0.0) for t in today_trades)
            
            # 1. DAILY REPORT & PDF
            daily_summary = (
                f"📊 <b>DAILY PERFORMANCE SUMMARY (03:40 PM)</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"📅 <b>Date:</b> {today_str_display}\n"
                f"⚡ <b>Strategy:</b> SAS LEVEL TRACKER\n"
                f"• Today Trades: {len(today_trades)}\n"
                f"📈 <b>Day Net Points:</b> {today_pnl:+.2f} Pts\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"<i>Dispatching Daily Analytical PDF Report...</i>"
            )
            send_telegram_alert(daily_summary)

            daily_pdf = f"Daily_Report_{today_str_display}.pdf"
            try:
                generate_pdf_report(daily_pdf, "DAILY PERFORMANCE REPORT", today_str_display, today_trades, today_pnl)
                send_telegram_document(daily_pdf, caption=f"📄 Daily Performance Report ({today_str_display}) | Net: {today_pnl:+.2f} Pts")
                send_email_with_pdf(daily_pdf, f"Daily Performance Report - {today_str_display}", daily_summary)
            except Exception as e:
                logger.error(f"Daily PDF Generation Error: {e}")

            # 2. MONTHLY EXPIRY TO EXPIRY REPORT & PDF
            if is_today_monthly_tuesday_expiry():
                total_cycle_pnl = sum(t.get("pnl", 0.0) for t in ledger)
                monthly_summary = (
                    f"🏆 <b>MONTHLY EXPIRY CYCLE REPORT (03:40 PM)</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"📅 <b>Expiry Date:</b> {today_str_display}\n"
                    f"⚡ <b>Strategy:</b> SAS LEVEL TRACKER\n"
                    f"• Total Month Crossovers: {len(ledger)}\n"
                    f"📈 <b>Net Cycle Points:</b> {total_cycle_pnl:+.2f} Pts\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"<i>Dispatching Complete Expiry Ledger PDF...</i>"
                )
                send_telegram_alert(monthly_summary)

                expiry_pdf = f"Monthly_Expiry_Report_{today_str_display}.pdf"
                try:
                    generate_pdf_report(expiry_pdf, "MONTHLY EXPIRY CYCLE REPORT", today_str_display, ledger, total_cycle_pnl)
                    send_telegram_document(expiry_pdf, caption=f"📄 Monthly Expiry Report ({today_str_display}) | Final: {total_cycle_pnl:+.2f} Pts")
                    send_email_with_pdf(expiry_pdf, f"Monthly Expiry Report - {today_str_display}", monthly_summary)
                    clear_expiry_ledger()
                except Exception as e:
                    logger.error(f"Expiry PDF Generation Error: {e}")

            send_telegram_alert("🛑 <b>MARKET CLOSED (03:40 PM):</b> SAS Level Tracker shutting down safely.")
            break

        time.sleep(1)

if __name__ == "__main__":
    main()
