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
EXPIRY_LEDGER_FILE = "expiry_trades_ledger.json"

telegram_session = requests.Session()
executor = ThreadPoolExecutor(max_workers=4)

# ==========================================
# 2. ULTRA-FAST NSE LIVE SESSION
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

    def get_nifty_price(self):
        if time.time() - self.last_cookie_time > 300:
            self.refresh_cookies()
        try:
            url = "https://www.nseindia.com/api/allIndices"
            resp = self.session.get(url, headers=self.headers, timeout=3)
            if resp.status_code == 200:
                data = resp.json()
                for item in data.get("data", []):
                    if item.get("index") == "NIFTY 50":
                        return float(str(item.get("last")).replace(",", ""))
            elif resp.status_code in [401, 403]:
                self.refresh_cookies()
        except Exception:
            pass
        return None

nse_live = FastNSELive()

# ==========================================
# 3. DISPATCH & TELEGRAM SYNC FUNCTIONS
# ==========================================
def _send_single_telegram(cid, message, parse_mode):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": cid, "text": message, "parse_mode": parse_mode}
    try:
        telegram_session.post(url, json=payload, timeout=5)
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
        logger.info("PDF emailed successfully.")
    except Exception as e:
        logger.error(f"Email Dispatch Warning: {e}")

# സെർവർ റീസ്റ്റാർട്ട് ആയാലും ടെലിഗ്രാമിൽ നിന്ന് ആക്റ്റീവ് ട്രേഡ് വീണ്ടെടുക്കുന്നു
def sync_active_trade_from_telegram():
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHANNEL_ID:
        return None
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates?offset=-10"
        resp = requests.get(url, timeout=5).json()
        if resp.get("ok") and resp.get("result"):
            messages = resp.get("result")
            last_signal = None
            has_closed = False

            for item in reversed(messages):
                msg = item.get("channel_post") or item.get("message")
                if not msg or "text" not in msg:
                    continue
                text = msg["text"]

                if "TARGET 1 HIT" in text or "STOP LOSS HIT" in text or "TRAILING STOP" in text or "MARKET CLOSING" in text:
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
# 4. HOLIDAYS & EXPIRY DETECTION
# ==========================================
def is_today_monthly_expiry():
    today = datetime.now(IST).date()
    next_month = today.replace(day=28) + timedelta(days=4)
    last_day_of_month = next_month - timedelta(days=next_month.day)
    target_day = last_day_of_month
    while target_day.weekday() != 1:
        target_day -= timedelta(days=1)
    return today == target_day

# ==========================================
# 5. STATE & LEDGER BACKUP
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
    # ഫയൽ ലഭ്യമല്ലെങ്കിൽ ടെലിഗ്രാമിൽ നിന്ന് പരിശോധിക്കുന്നു
    return sync_active_trade_from_telegram()

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
    except Exception:
        pass

def clear_expiry_ledger():
    try:
        if os.path.exists(EXPIRY_LEDGER_FILE):
            os.remove(EXPIRY_LEDGER_FILE)
    except Exception:
        pass

# ==========================================
# 6. PDF REPORT GENERATION
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
# 7. MAIN ENGINE (STRICT POSITION LOCK)
# ==========================================
def main():
    logger.info("Starting SAS Level Pulse Engine (Anti-Duplicate Cloud Safe)...")

    # റീസ്റ്റാർട്ട് ആയാലും ടെലിഗ്രാമിൽ നിന്നടക്കം പഴയ ട്രേഡ് പുനഃസ്ഥാപിക്കുന്നു
    active_trade = load_backup_state()
    if active_trade:
        logger.info(f"Active trade restored: {active_trade['side']} @ {active_trade['entry']}")

    startup_alert_sent = False
    last_heartbeat_hour = -1
    today_date_str = datetime.now(IST).strftime("%Y-%m-%d")
    today_str_display = datetime.now(IST).strftime('%d-%b-%Y')

    ref_high = None
    ref_low = None
    last_eval_time = 0

    while True:
        now = datetime.now(IST)
        current_time = now.time()

        # 09:00 AM Engine Alert (റീസ്റ്റാർട്ട് ആയാൽ വീണ്ടും ഇടയ്ക്ക് അയക്കില്ല)
        if current_time >= dtime(9, 0) and not startup_alert_sent and current_time < dtime(9, 15):
            startup_msg = (
                f"🚀 <b>{STRATEGY_DISPLAY_NAME} LIVE</b>\n"
                f"⏰ Time: {now.strftime('%I:%M:%S %p')} IST\n"
                f"📊 Index: NIFTY 50\n"
                f"⚡ Status: Scanner Active"
            )
            send_telegram_alert(startup_msg)
            startup_alert_sent = True

        # Active Scanning Window (09:15 AM - 03:25 PM)
        if dtime(9, 15) <= current_time <= dtime(15, 25):
            current_price = nse_live.get_nifty_price()

            if current_price:
                # ----------------------------------------------------
                # SCENARIO A: ആക്റ്റീവ് ട്രേഡ് ഉണ്ടെങ്കിൽ അത് മാത്രം മോണിറ്റർ ചെയ്യുക
                # ----------------------------------------------------
                if active_trade is not None:
                    side = active_trade["side"]
                    entry = active_trade["entry"]
                    t1 = active_trade["t1"]
                    t2 = active_trade["t2"]
                    t3 = active_trade["t3"]
                    sl = active_trade["sl"]

                    if side == "BUY":
                        # Hit Target 3
                        if current_price >= t3:
                            pnl = current_price - entry
                            active_trade["highest_target"] = 3
                            active_trade["status"] = "Target 3 Achieved"
                            active_trade["exit_price"] = current_price
                            active_trade["pnl"] = pnl
                            record_trade_to_ledger(active_trade)
                            send_telegram_alert(f"🎯 <b>TARGET 3 HIT! [BUY]</b>\nSpot: {current_price:.2f}\nPoints: +{pnl:.2f} Pts")
                            active_trade = None
                            save_daily_state(None)

                        # Hit Target 2
                        elif current_price >= t2 and active_trade.get("highest_target", 0) < 2:
                            active_trade["highest_target"] = 2
                            active_trade["sl"] = t1
                            send_telegram_alert(f"🎯 <b>TARGET 2 HIT! [BUY]</b>\nSpot: {current_price:.2f}\nTrailing SL moved to Target 1 ({t1:.2f}).")
                            save_daily_state(active_trade)

                        # Hit Target 1 (SL moved to Cost)
                        elif current_price >= t1 and active_trade.get("highest_target", 0) < 1:
                            active_trade["highest_target"] = 1
                            active_trade["sl"] = entry
                            send_telegram_alert(f"🎯 <b>TARGET 1 HIT! [BUY]</b>\nSpot: {current_price:.2f}\nTrailing SL moved to Cost ({entry:.2f}).")
                            save_daily_state(active_trade)

                        # Hit SL / Trailing SL
                        elif current_price <= sl:
                            pnl = current_price - entry
                            active_trade["exit_price"] = current_price
                            active_trade["pnl"] = pnl

                            if active_trade.get("highest_target", 0) >= 1:
                                active_trade["status"] = f"Target {active_trade['highest_target']} Achieved (Trail Exit)"
                                send_telegram_alert(f"🏁 <b>TRAILING STOP TRIGGERED [BUY]</b>\nSpot: {current_price:.2f}\nClosed in Profit/Cost: {pnl:+.2f} Pts")
                            else:
                                active_trade["status"] = "Stop Loss Hit"
                                send_telegram_alert(f"🛑 <b>STOP LOSS HIT [BUY]</b>\nSpot: {current_price:.2f}\nPoints: {pnl:.2f} Pts")

                            record_trade_to_ledger(active_trade)
                            active_trade = None
                            save_daily_state(None)

                    elif side == "SELL":
                        # Hit Target 3
                        if current_price <= t3:
                            pnl = entry - current_price
                            active_trade["highest_target"] = 3
                            active_trade["status"] = "Target 3 Achieved"
                            active_trade["exit_price"] = current_price
                            active_trade["pnl"] = pnl
                            record_trade_to_ledger(active_trade)
                            send_telegram_alert(f"🎯 <b>TARGET 3 HIT! [SELL]</b>\nSpot: {current_price:.2f}\nPoints: +{pnl:.2f} Pts")
                            active_trade = None
                            save_daily_state(None)

                        # Hit Target 2
                        elif current_price <= t2 and active_trade.get("highest_target", 0) < 2:
                            active_trade["highest_target"] = 2
                            active_trade["sl"] = t1
                            send_telegram_alert(f"🎯 <b>TARGET 2 HIT! [SELL]</b>\nSpot: {current_price:.2f}\nTrailing SL moved to Target 1 ({t1:.2f}).")
                            save_daily_state(active_trade)

                        # Hit Target 1 (SL moved to Cost)
                        elif current_price <= t1 and active_trade.get("highest_target", 0) < 1:
                            active_trade["highest_target"] = 1
                            active_trade["sl"] = entry
                            send_telegram_alert(f"🎯 <b>TARGET 1 HIT! [SELL]</b>\nSpot: {current_price:.2f}\nTrailing SL moved to Cost ({entry:.2f}).")
                            save_daily_state(active_trade)

                        # Hit SL / Trailing SL
                        elif current_price >= sl:
                            pnl = entry - current_price
                            active_trade["exit_price"] = current_price
                            active_trade["pnl"] = pnl

                            if active_trade.get("highest_target", 0) >= 1:
                                active_trade["status"] = f"Target {active_trade['highest_target']} Achieved (Trail Exit)"
                                send_telegram_alert(f"🏁 <b>TRAILING STOP TRIGGERED [SELL]</b>\nSpot: {current_price:.2f}\nClosed in Profit/Cost: {pnl:+.2f} Pts")
                            else:
                                active_trade["status"] = "Stop Loss Hit"
                                send_telegram_alert(f"🛑 <b>STOP LOSS HIT [SELL]</b>\nSpot: {current_price:.2f}\nPoints: {pnl:.2f} Pts")

                            record_trade_to_ledger(active_trade)
                            active_trade = None
                            save_daily_state(None)

                # ----------------------------------------------------
                # SCENARIO B: പുതിയ ട്രേഡ് സ്കാനിംഗ് (ആക്റ്റീവ് ട്രേഡ് ഇല്ലെങ്കിൽ മാത്രം)
                # ----------------------------------------------------
                else:
                    if ref_high is None or (time.time() - last_eval_time > 60):
                        ref_high = current_price + 3.0
                        ref_low = current_price - 3.0
                        last_eval_time = time.time()

                    trigger = None
                    if current_price > ref_high:
                        trigger = "BUY"
                    elif current_price < ref_low:
                        trigger = "SELL"

                    if trigger:
                        entry = current_price
                        entry_time_display = now.strftime('%I:%M:%S %p')
                        risk_pts = 30.0

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

                # Hourly Status
                if now.minute == 0 and now.hour != last_heartbeat_hour and (9 <= now.hour <= 15):
                    last_heartbeat_hour = now.hour
                    hb_msg = f"💓 <b>HOURLY UPDATE</b>\n⏰ Time: {now.strftime('%I:%M:00 %p')} IST\n• NIFTY 50: {current_price:.2f}"
                    send_telegram_alert(hb_msg)

        # 03:25 PM Auto Square Off
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

            if is_today_monthly_expiry():
                total_cycle_pnl = sum(t.get("pnl", 0.0) for t in ledger)
                expiry_summary = (
                    f"🏆 <b>MONTHLY EXPIRY CYCLE REPORT (03:40 PM)</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"📅 Expiry Date: {today_str_display}\n"
                    f"⚡ Strategy: {STRATEGY_DISPLAY_NAME}\n"
                    f"• Total Cycle Trades: {len(ledger)}\n"
                    f"📈 Net Cycle Points: {total_cycle_pnl:+.2f} Pts\n"
                    f"━━━━━━━━━━━━━━━━━━━━"
                )
                send_telegram_alert(expiry_summary)

                expiry_pdf = f"Monthly_Expiry_Report_{today_str_display}.pdf"
                try:
                    generate_pdf_report(expiry_pdf, "MONTHLY EXPIRY CYCLE REPORT", today_str_display, ledger, total_cycle_pnl)
                    send_telegram_document(expiry_pdf, caption=f"📄 Monthly Expiry Report | Net: {total_cycle_pnl:+.2f} Pts")
                    send_email_with_pdf(expiry_pdf, f"Monthly Expiry Report - {today_str_display}", expiry_summary)
                    clear_expiry_ledger()
                except Exception as e:
                    logger.error(f"Expiry PDF Error: {e}")

            send_telegram_alert("🛑 <b>MARKET CLOSED:</b> Engine stopped.")
            break

        time.sleep(0.5)

if __name__ == "__main__":
    main()
