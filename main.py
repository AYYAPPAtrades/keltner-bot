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

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8804327561:AAECrvtU0MCYB80L0ZchoKy_YDpwJ52zQA8")
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID", "-1004416495917")
TELEGRAM_ADMIN_CHAT_ID = os.getenv("TELEGRAM_ADMIN_CHAT_ID", "6789591588")

PUBLIC_ALERT_IDS = [TELEGRAM_CHANNEL_ID, TELEGRAM_ADMIN_CHAT_ID]

SENDER_EMAIL = "shinos99@gmail.com"
SENDER_APP_PASSWORD = "xufefwfphwsomsnu"
RECEIVER_EMAILS = ["shinos99@gmail.com"]

STRATEGY_DISPLAY_NAME = "SAS LEVEL PULSE"
DAILY_STATE_FILE = "daily_active_trades.json"
WEEKLY_LEDGER_FILE = "weekly_trades_ledger.json"
EXPIRY_LEDGER_FILE = "expiry_trades_ledger.json"

telegram_session = requests.Session()
executor = ThreadPoolExecutor(max_workers=4)

# ==========================================
# 2. ULTRA-FAST NSE LIVE FEED (WITH HIGH & LOW)
# ==========================================
class FastNSELive:
    def __init__(self):
        self.session = requests.Session()
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9"
        }
        self.last_cookie_time = 0
        self.refresh_cookies()

    def refresh_cookies(self):
        try:
            self.session.get("https://www.nseindia.com", headers=self.headers, timeout=5)
            self.last_cookie_time = time.time()
        except Exception:
            pass

    def get_nifty_data(self):
        if time.time() - self.last_cookie_time > 300:
            self.refresh_cookies()
        try:
            url = "https://www.nseindia.com/api/allIndices"
            resp = self.session.get(url, headers=self.headers, timeout=3)
            if resp.status_code == 200:
                data = resp.json()
                for item in data.get("data", []):
                    if item.get("index") == "NIFTY 50":
                        last_price = float(str(item.get("last")).replace(",", ""))
                        day_high = float(str(item.get("high", last_price)).replace(",", ""))
                        day_low = float(str(item.get("low", last_price)).replace(",", ""))
                        return last_price, day_high, day_low
            elif resp.status_code in [401, 403]:
                self.refresh_cookies()
        except Exception:
            pass
        return None, None, None

nse_live = FastNSELive()

# ==========================================
# 3. ZERO-DELAY TELEGRAM & EMAIL DISPATCH
# ==========================================
def _send_single_telegram(cid, message, parse_mode):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": cid, "text": message, "parse_mode": parse_mode}
    try:
        telegram_session.post(url, json=payload, timeout=5)
    except Exception as e:
        logger.error(f"[TELEGRAM ERROR] {cid}: {e}")

def send_telegram_alert(message, parse_mode="HTML"):
    if not TELEGRAM_BOT_TOKEN:
        return
    for cid in PUBLIC_ALERT_IDS:
        if cid:
            executor.submit(_send_single_telegram, cid, message, parse_mode)

def send_admin_alert(message, parse_mode="HTML"):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_ADMIN_CHAT_ID:
        return
    executor.submit(_send_single_telegram, TELEGRAM_ADMIN_CHAT_ID, message, parse_mode)

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
        logger.info("PDF emailed successfully.")
    except Exception as e:
        logger.error(f"Email Dispatch Warning: {e}")

# ==========================================
# 4. STRICT TELEGRAM STATE RESTORATION
# ==========================================
def sync_active_trade_from_telegram():
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHANNEL_ID:
        return None
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates?offset=-10"
        resp = requests.get(url, timeout=5).json()
        if resp.get("ok") and resp.get("result"):
            messages = resp.get("result")
            has_closed = False

            for item in reversed(messages):
                msg = item.get("channel_post") or item.get("message")
                if not msg or "text" not in msg:
                    continue
                text = msg["text"]

                if any(x in text for x in ["TARGET 1 HIT", "STOP LOSS HIT", "TRAILING STOP", "MARKET CLOSING", "EXIT PREVIOUS POSITION"]):
                    has_closed = True
                    break

                if ("BUY SIGNAL" in text or "SELL SIGNAL" in text) and not has_closed:
                    lines = text.split("\n")
                    side = "BUY" if "BUY SIGNAL" in text else "SELL"
                    entry, sl, t1, t2, t3 = 0, 0, 0, 0, 0
                    for line in lines:
                        if "Entry:" in line:
                            entry = float(line.split(":")[-1].strip())
                        elif "Stop Loss:" in line:
                            sl = float(line.split(":")[-1].strip())
                        elif "T1:" in line:
                            t1 = float(line.split(":")[-1].strip())
                        elif "T2:" in line:
                            t2 = float(line.split(":")[-1].strip())
                        elif "T3:" in line:
                            t3 = float(line.split(":")[-1].strip())

                    if entry > 0:
                        return {
                            "date": datetime.now(IST).strftime("%Y-%m-%d"),
                            "index": "NIFTY 50",
                            "side": side,
                            "entry": entry,
                            "sl": sl,
                            "t1": t1,
                            "t2": t2,
                            "t3": t3,
                            "highest_target": 0,
                            "time": "Synced"
                        }
    except Exception as e:
        logger.error(f"Telegram sync error: {e}")
    return None

# ==========================================
# 5. HOLIDAY & TUESDAY EXPIRY ENGINE
# ==========================================
NSE_HOLIDAYS_2026 = [
    "2026-01-26", "2026-03-03", "2026-03-26", "2026-04-02", "2026-04-14",
    "2026-05-01", "2026-05-28", "2026-06-26", "2026-08-15", "2026-10-02",
    "2026-10-20", "2026-11-09", "2026-11-24", "2026-12-25"
]

def is_trading_holiday(dt):
    return dt.weekday() in [5, 6] or dt.strftime("%Y-%m-%d") in NSE_HOLIDAYS_2026

def get_actual_expiry_day(target_date):
    curr = target_date
    while is_trading_holiday(curr):
        curr -= timedelta(days=1)
    return curr

def is_today_weekly_expiry():
    today = datetime.now(IST).date()
    days_until_tuesday = (1 - today.weekday()) % 7
    target_tuesday = today + timedelta(days=days_until_tuesday)
    return today == get_actual_expiry_day(target_tuesday)

def is_today_monthly_expiry():
    today = datetime.now(IST).date()
    next_month = today.replace(day=28) + timedelta(days=4)
    last_day_of_month = next_month - timedelta(days=next_month.day)
    target_tuesday = last_day_of_month
    while target_tuesday.weekday() != 1:
        target_tuesday -= timedelta(days=1)
    return today == get_actual_expiry_day(target_tuesday)

# ==========================================
# 6. STATE & MULTI-CYCLE LEDGER MANAGEMENT
# ==========================================
def load_backup_state():
    today_str = datetime.now(IST).strftime("%Y-%m-%d")
    if os.path.exists(DAILY_STATE_FILE):
        try:
            with open(DAILY_STATE_FILE, "r") as f:
                data = json.load(f)
                if data.get("date") == today_str and data.get("active_trade"):
                    return data.get("active_trade")
        except Exception:
            pass
    return sync_active_trade_from_telegram()

def save_daily_state(active_trade):
    today_str = datetime.now(IST).strftime("%Y-%m-%d")
    try:
        with open(DAILY_STATE_FILE, "w") as f:
            json.dump({"date": today_str, "active_trade": active_trade}, f, indent=4)
    except Exception:
        pass

def append_to_file(filepath, record):
    ledger = []
    if os.path.exists(filepath):
        try:
            with open(filepath, "r") as f:
                ledger = json.load(f)
        except Exception:
            ledger = []
    ledger.append(record)
    try:
        with open(filepath, "w") as f:
            json.dump(ledger, f, indent=4)
    except Exception:
        pass

def record_trade_to_ledger(trade_record):
    append_to_file(WEEKLY_LEDGER_FILE, trade_record)
    append_to_file(EXPIRY_LEDGER_FILE, trade_record)

def load_ledger(filepath):
    if os.path.exists(filepath):
        try:
            with open(filepath, "r") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def clear_ledger(filepath):
    try:
        if os.path.exists(filepath):
            os.remove(filepath)
    except Exception:
        pass

# ==========================================
# 7. PDF REPORT GENERATOR
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

    headers = ["SL", "Date", "Side", "Entry & Time", "Exit Price", "Target 1", "Target 2", "Target 3", "Points", "Status"]
    table_rows = [headers]

    for i, l in enumerate(logs, 1):
        table_rows.append([
            str(i), l.get('date', '-'), f"{l.get('index', 'NIFTY 50')}\n({l.get('side', '-')})",
            f"{l.get('entry', 0.0):.2f}\n({l.get('time', '-')})",
            f"{l.get('exit_price', 0.0):.2f}",
            f"{l.get('t1', 0.0):.2f}" if l.get('highest_target', 0) >= 1 else "-",
            f"{l.get('t2', 0.0):.2f}" if l.get('highest_target', 0) >= 2 else "-",
            f"{l.get('t3', 0.0):.2f}" if l.get('highest_target', 0) >= 3 else "-",
            f"{l.get('pnl', 0.0):+.2f}",
            l.get('status', '-')
        ])

    table_rows.append([
        "TOTAL", "-", "-", "-", "-", "-", "-", "NET POINTS", f"{total_pnl:+.2f}", "FINISHED"
    ])

    trade_table = Table(table_rows, colWidths=[25, 65, 80, 85, 75, 75, 75, 75, 65, 120])
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
# 8. CORE ENGINE (REAL-TIME SPIKE DETECTION)
# ==========================================
def main():
    logger.info("Starting SAS Level Pulse Engine...")

    active_trade = load_backup_state()
    today_date_str = datetime.now(IST).strftime("%Y-%m-%d")
    today_str_display = datetime.now(IST).strftime('%d-%b-%Y')

    if active_trade:
        send_admin_alert(
            f"♻️ <b>BOT RESTARTED (STATE RESTORED)</b>\n"
            f"• Position: {active_trade['side']} @ {active_trade['entry']:.2f}\n"
            f"• Stop Loss: {active_trade['sl']:.2f} | T1: {active_trade['t1']:.2f}\n"
            f"• Status: Strict Lock Active. No duplicate signals."
        )
    else:
        send_admin_alert(
            f"🚀 <b>{STRATEGY_DISPLAY_NAME} RUNNING</b>\n"
            f"• Status: Engine active for admin.\n"
            f"• Joiners will only receive Signals & Reports."
        )

    ref_high = None
    ref_low = None
    last_eval_time = 0
    last_heartbeat_hour = -1

    while True:
        now = datetime.now(IST)
        current_time = now.time()

        # Active Scanning Window (09:15 AM - 03:25 PM)
        if dtime(9, 15) <= current_time <= dtime(15, 25):
            current_price, high_price, low_price = nse_live.get_nifty_data()

            if current_price:
                # Fast Scalping: 1.5 Pt Sensitivity & 20s Update Window
                if ref_high is None or (time.time() - last_eval_time > 20):
                    ref_high = current_price + 1.5
                    ref_low = current_price - 1.5
                    last_eval_time = time.time()

                # Hourly Status Alert (Admin Only)
                if now.minute == 0 and now.hour != last_heartbeat_hour and (9 <= now.hour <= 15):
                    last_heartbeat_hour = now.hour
                    hb_msg = (
                        f"💓 <b>HOURLY STATUS ALERT (ADMIN)</b>\n"
                        f"⏰ <b>Time:</b> {now.strftime('%I:%M:00 %p')} IST\n"
                        f"📊 <b>NIFTY 50 Spot:</b> {current_price:.2f}"
                    )
                    send_admin_alert(hb_msg)

                # ----------------------------------------------------
                # SCENARIO A: ACTIVE TRADE MONITORING & AUTO-REVERSAL
                # ----------------------------------------------------
                if active_trade is not None:
                    side = active_trade["side"]
                    entry = active_trade["entry"]
                    t1 = active_trade["t1"]
                    t2 = active_trade["t2"]
                    t3 = active_trade["t3"]
                    sl = active_trade["sl"]

                    # സ്പൈക്ക് മിസ്സാവാതിരിക്കാൻ ഹൈയും ലോയും പരിഗണിക്കുന്നു
                    eval_high = max(current_price, high_price) if high_price else current_price
                    eval_low = min(current_price, low_price) if low_price else current_price

                    # 1. Reverse Momentum Trigger Check
                    reversal_direction = None
                    if side == "BUY" and current_price < ref_low:
                        reversal_direction = "SELL"
                    elif side == "SELL" and current_price > ref_high:
                        reversal_direction = "BUY"

                    if reversal_direction:
                        pnl = (current_price - entry) if side == "BUY" else (entry - current_price)
                        active_trade["status"] = f"Reversal Exit ({reversal_direction} Spike)"
                        active_trade["exit_price"] = current_price
                        active_trade["pnl"] = pnl
                        record_trade_to_ledger(active_trade)

                        exit_msg = (
                            f"⚠️ <b>EXIT PREVIOUS POSITION [{side}]</b>\n\n"
                            f"• <b>Exit Price:</b> {current_price:.2f}\n"
                            f"• <b>Points:</b> {pnl:+.2f} Pts\n"
                            f"• <b>Reason:</b> Reversal detected. Preparing new signal..."
                        )
                        send_telegram_alert(exit_msg)
                        time.sleep(1)

                        entry_time_display = now.strftime('%I:%M:%S %p')
                        fixed_risk = 30.0

                        if reversal_direction == "BUY":
                            new_sl = round(current_price - fixed_risk, 2)
                            new_t1 = round(current_price + fixed_risk, 2)
                            new_t2 = round(current_price + (fixed_risk * 2.0), 2)
                            new_t3 = round(current_price + (fixed_risk * 3.0), 2)
                        else:
                            new_sl = round(current_price + fixed_risk, 2)
                            new_t1 = round(current_price - fixed_risk, 2)
                            new_t2 = round(current_price - (fixed_risk * 2.0), 2)
                            new_t3 = round(current_price - (fixed_risk * 3.0), 2)

                        active_trade = {
                            "date": today_date_str,
                            "index": "NIFTY 50",
                            "side": reversal_direction,
                            "entry": current_price,
                            "sl": new_sl,
                            "t1": new_t1,
                            "t2": new_t2,
                            "t3": new_t3,
                            "highest_target": 0,
                            "time": entry_time_display
                        }
                        save_daily_state(active_trade)

                        rev_signal_msg = (
                            f"⚡ <b>{reversal_direction} SIGNAL (REVERSAL)</b>\n\n"
                            f"• <b>Entry:</b> {current_price:.2f}\n"
                            f"• <b>Entry Time:</b> {entry_time_display} IST\n"
                            f"• <b>Spot:</b> {current_price:.2f}\n"
                            f"• <b>Stop Loss:</b> {new_sl:.2f}\n"
                            f"• <b>T1:</b> {new_t1:.2f}\n"
                            f"• <b>T2:</b> {new_t2:.2f}\n"
                            f"• <b>T3:</b> {new_t3:.2f}"
                        )
                        send_telegram_alert(rev_signal_msg)
                        ref_high = current_price + 1.5
                        ref_low = current_price - 1.5
                        last_eval_time = time.time()
                        continue

                    # 2. Strict T1/T2/T3 & SL Monitoring
                    if side == "BUY":
                        if eval_high >= t3:
                            pnl = t3 - entry
                            active_trade["highest_target"] = 3
                            active_trade["status"] = "Target 3 Achieved"
                            active_trade["exit_price"] = t3
                            active_trade["pnl"] = pnl
                            record_trade_to_ledger(active_trade)
                            send_telegram_alert(f"🎯 <b>TARGET 3 HIT! [BUY]</b>\nSpot: {eval_high:.2f}\nPoints: +{pnl:.2f} Pts")
                            active_trade = None
                            save_daily_state(None)

                        elif eval_high >= t2 and active_trade.get("highest_target", 0) < 2:
                            active_trade["highest_target"] = 2
                            active_trade["sl"] = t1
                            send_telegram_alert(f"🎯 <b>TARGET 2 HIT! [BUY]</b>\nSpot: {eval_high:.2f}\nTrailing SL moved to Target 1 ({t1:.2f}).")
                            save_daily_state(active_trade)

                        elif eval_high >= t1 and active_trade.get("highest_target", 0) < 1:
                            active_trade["highest_target"] = 1
                            active_trade["sl"] = entry
                            send_telegram_alert(f"🎯 <b>TARGET 1 HIT! [BUY]</b>\nSpot: {eval_high:.2f}\nTrailing SL moved to Cost ({entry:.2f}).")
                            save_daily_state(active_trade)

                        elif eval_low <= sl:
                            pnl = sl - entry
                            active_trade["exit_price"] = sl
                            active_trade["pnl"] = pnl

                            if active_trade.get("highest_target", 0) >= 1:
                                active_trade["status"] = f"Target {active_trade['highest_target']} Achieved (Trail Exit)"
                                send_telegram_alert(f"🏁 <b>TRAILING STOP TRIGGERED [BUY]</b>\nSpot: {eval_low:.2f}\nClosed in Profit/Cost: {pnl:+.2f} Pts")
                            else:
                                active_trade["status"] = "Stop Loss Hit"
                                send_telegram_alert(f"🛑 <b>STOP LOSS HIT [BUY]</b>\nSpot: {eval_low:.2f}\nPoints: {pnl:.2f} Pts")

                            record_trade_to_ledger(active_trade)
                            active_trade = None
                            save_daily_state(None)

                    elif side == "SELL":
                        if eval_low <= t3:
                            pnl = entry - t3
                            active_trade["highest_target"] = 3
                            active_trade["status"] = "Target 3 Achieved"
                            active_trade["exit_price"] = t3
                            active_trade["pnl"] = pnl
                            record_trade_to_ledger(active_trade)
                            send_telegram_alert(f"🎯 <b>TARGET 3 HIT! [SELL]</b>\nSpot: {eval_low:.2f}\nPoints: +{pnl:.2f} Pts")
                            active_trade = None
                            save_daily_state(None)

                        elif eval_low <= t2 and active_trade.get("highest_target", 0) < 2:
                            active_trade["highest_target"] = 2
                            active_trade["sl"] = t1
                            send_telegram_alert(f"🎯 <b>TARGET 2 HIT! [SELL]</b>\nSpot: {eval_low:.2f}\nTrailing SL moved to Target 1 ({t1:.2f}).")
                            save_daily_state(active_trade)

                        elif eval_low <= t1 and active_trade.get("highest_target", 0) < 1:
                            active_trade["highest_target"] = 1
                            active_trade["sl"] = entry
                            send_telegram_alert(f"🎯 <b>TARGET 1 HIT! [SELL]</b>\nSpot: {eval_low:.2f}\nTrailing SL moved to Cost ({entry:.2f}).")
                            save_daily_state(active_trade)

                        elif eval_high >= sl:
                            pnl = entry - sl
                            active_trade["exit_price"] = sl
                            active_trade["pnl"] = pnl

                            if active_trade.get("highest_target", 0) >= 1:
                                active_trade["status"] = f"Target {active_trade['highest_target']} Achieved (Trail Exit)"
                                send_telegram_alert(f"🏁 <b>TRAILING STOP TRIGGERED [SELL]</b>\nSpot: {eval_high:.2f}\nClosed in Profit/Cost: {pnl:+.2f} Pts")
                            else:
                                active_trade["status"] = "Stop Loss Hit"
                                send_telegram_alert(f"🛑 <b>STOP LOSS HIT [SELL]</b>\nSpot: {eval_high:.2f}\nPoints: {pnl:.2f} Pts")

                            record_trade_to_ledger(active_trade)
                            active_trade = None
                            save_daily_state(None)

                # ----------------------------------------------------
                # SCENARIO B: SCAN FOR NEW TRADES (30-PT TARGET/SL)
                # ----------------------------------------------------
                else:
                    trigger = None
                    if current_price > ref_high:
                        trigger = "BUY"
                    elif current_price < ref_low:
                        trigger = "SELL"

                    if trigger:
                        entry = current_price
                        entry_time_display = now.strftime('%I:%M:%S %p')
                        fixed_risk = 30.0

                        if trigger == "BUY":
                            sl = round(entry - fixed_risk, 2)
                            t1 = round(entry + fixed_risk, 2)
                            t2 = round(entry + (fixed_risk * 2.0), 2)
                            t3 = round(entry + (fixed_risk * 3.0), 2)
                        else:
                            sl = round(entry + fixed_risk, 2)
                            t1 = round(entry - fixed_risk, 2)
                            t2 = round(entry - (fixed_risk * 2.0), 2)
                            t3 = round(entry - (fixed_risk * 3.0), 2)

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
                            "time": entry_time_display
                        }
                        save_daily_state(active_trade)

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

        # 03:25 PM Auto Square Off (Joiners & Admin)
        if current_time >= dtime(15, 25) and active_trade is not None:
            entry = active_trade["entry"]
            last_prc = current_price if 'current_price' in locals() and current_price else entry
            pnl = (last_prc - entry) if active_trade["side"] == "BUY" else (entry - last_prc)
            active_trade["status"] = "EOD Auto-Exit"
            active_trade["exit_price"] = last_prc
            active_trade["pnl"] = pnl
            record_trade_to_ledger(active_trade)
            active_trade = None
            save_daily_state(None)
            send_telegram_alert(f"🔔 <b>MARKET CLOSING (03:25 PM):</b> Open position closed ({pnl:+.2f} Pts).")

        # 03:40 PM Reports Dispatch
        if current_time >= dtime(15, 40):
            # 1. Daily Report
            weekly_ledger = load_ledger(WEEKLY_LEDGER_FILE)
            today_trades = [t for t in weekly_ledger if t.get("date") == today_date_str]
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

            # 2. Weekly Expiry Report (Every Tuesday / Holiday Rule)
            if is_today_weekly_expiry():
                total_weekly_pnl = sum(t.get("pnl", 0.0) for t in weekly_ledger)
                weekly_summary = (
                    f"🎯 <b>WEEKLY EXPIRY SUMMARY (03:40 PM)</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"📅 Expiry Date: {today_str_display}\n"
                    f"⚡ Strategy: {STRATEGY_DISPLAY_NAME}\n"
                    f"• Weekly Trades: {len(weekly_ledger)}\n"
                    f"📈 Weekly Net Points: {total_weekly_pnl:+.2f} Pts\n"
                    f"━━━━━━━━━━━━━━━━━━━━"
                )
                send_telegram_alert(weekly_summary)

                weekly_pdf = f"Weekly_Expiry_Report_{today_str_display}.pdf"
                try:
                    generate_pdf_report(weekly_pdf, "WEEKLY EXPIRY REPORT", today_str_display, weekly_ledger, total_weekly_pnl)
                    send_telegram_document(weekly_pdf, caption=f"📄 Weekly Expiry Report | Net: {total_weekly_pnl:+.2f} Pts")
                    send_email_with_pdf(weekly_pdf, f"Weekly Expiry Report - {today_str_display}", weekly_summary)
                    clear_ledger(WEEKLY_LEDGER_FILE)
                except Exception as e:
                    logger.error(f"Weekly PDF Error: {e}")

            # 3. Monthly Expiry Report (Last Tuesday / Holiday Rule)
            if is_today_monthly_expiry():
                monthly_ledger = load_ledger(EXPIRY_LEDGER_FILE)
                total_monthly_pnl = sum(t.get("pnl", 0.0) for t in monthly_ledger)
                monthly_summary = (
                    f"🏆 <b>MONTHLY EXPIRY CYCLE REPORT (03:40 PM)</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"📅 Expiry Date: {today_str_display}\n"
                    f"⚡ Strategy: {STRATEGY_DISPLAY_NAME}\n"
                    f"• Total Month Trades: {len(monthly_ledger)}\n"
                    f"📈 Month Net Points: {total_monthly_pnl:+.2f} Pts\n"
                    f"━━━━━━━━━━━━━━━━━━━━"
                )
                send_telegram_alert(monthly_summary)

                monthly_pdf = f"Monthly_Expiry_Report_{today_str_display}.pdf"
                try:
                    generate_pdf_report(monthly_pdf, "MONTHLY EXPIRY CYCLE REPORT", today_str_display, monthly_ledger, total_monthly_pnl)
                    send_telegram_document(monthly_pdf, caption=f"📄 Monthly Expiry Report | Net: {total_monthly_pnl:+.2f} Pts")
                    send_email_with_pdf(monthly_pdf, f"Monthly Expiry Report - {today_str_display}", monthly_summary)
                    clear_ledger(EXPIRY_LEDGER_FILE)
                except Exception as e:
                    logger.error(f"Monthly PDF Error: {e}")

            send_admin_alert("🛑 <b>MARKET CLOSED:</b> Engine stopped successfully.")
            break

        time.sleep(0.5)

if __name__ == "__main__":
    main()
