import os
import sys
import json
import time
import smtplib
import calendar
import requests
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime, date, timedelta, time as dtime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
import pytz

# ReportLab for PDF generation
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

# ================= 1. CREDENTIALS & CONSTANTS =================
BOT_TOKEN = "8804327561:AAECrvtU0MCYB80L0ZchoKy_YDpwJ52zQA8"
ADMIN_CHAT_ID = "6789591588"
CHANNEL_CHAT_ID = "-1004416495917"

ADMIN_EMAIL = "shinos99@gmail.com"
GMAIL_APP_PASS = "wgms etgl eklv cdja"

STATE_FILE = "sas_bot_state.json"
HISTORY_FILE = "sas_expiry_cycle_trades.json"
IST = pytz.timezone("Asia/Kolkata")

# NSE Holidays with Reason
NSE_HOLIDAYS_2026 = {
    "2026-01-26": "Republic Day",
    "2026-03-03": "Holi",
    "2026-03-26": "Ram Navami",
    "2026-04-03": "Good Friday",
    "2026-04-14": "Dr. Baba Saheb Ambedkar Jayanti",
    "2026-05-01": "Maharashtra Day / Labour Day",
    "2026-08-15": "Independence Day",
    "2026-10-02": "Mahatma Gandhi Jayanti",
    "2026-10-20": "Dussehra",
    "2026-11-08": "Diwali Balipratipada",
    "2026-12-25": "Christmas"
}

# ================= 2. MONTHLY EXPIRY CALCULATOR =================
def get_monthly_expiry_date(year, month):
    last_day = calendar.monthrange(year, month)[1]
    d = date(year, month, last_day)

    target_weekday = 3  # Thursday
    while d.weekday() != target_weekday:
        d -= timedelta(days=1)

    while d.strftime("%Y-%m-%d") in NSE_HOLIDAYS_2026 or d.weekday() >= 5:
        d -= timedelta(days=1)

    return d

def is_today_monthly_expiry():
    today = datetime.now(IST).date()
    expiry_date = get_monthly_expiry_date(today.year, today.month)
    return today == expiry_date

# ================= 3. DATA FETCH (YAHOO FINANCE - 1 MIN SCALPING) =================
def get_nifty_candle_data():
    try:
        ticker = yf.Ticker("^NSEI")
        df = ticker.history(period="5d", interval="1m")
        if df is not None and not df.empty:
            df = df.reset_index()
            time_col = "Datetime" if "Datetime" in df.columns else "Date"
            df = df.rename(columns={time_col: "Timestamp", "Open": "Open", "High": "High", "Low": "Low", "Close": "Close", "Volume": "Volume"})
            df["Timestamp"] = pd.to_datetime(df["Timestamp"])
            if df["Timestamp"].dt.tz is not None:
                df["Timestamp"] = df["Timestamp"].dt.tz_convert(IST)
            else:
                df["Timestamp"] = df["Timestamp"].dt.tz_localize("UTC").dt.tz_convert(IST)
            
            df.set_index("Timestamp", inplace=True)
            df.index = df.index.tz_localize(None)
            return df[['Open', 'High', 'Low', 'Close', 'Volume']]
        return None
    except Exception as e:
        print(f"Data Fetch Exception: {e}")
        return None

# ================= 4. TELEGRAM UTILS =================
def send_telegram(text: str, target="admin"):
    header = "📢 *SAS LEVEL TRACKER*\n"
    full_text = f"{header}\n{text}"
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    
    try:
        res = requests.post(
            url, 
            json={"chat_id": ADMIN_CHAT_ID, "text": full_text, "parse_mode": "Markdown"}, 
            timeout=10
        )
        data = res.json()
        if not data.get("ok"):
            print(f"Telegram Admin Error [{res.status_code}]: {data.get('description')}")
    except Exception as e:
        print(f"Telegram Admin Connection Error: {e}")

    if target == "all" and CHANNEL_CHAT_ID and not CHANNEL_CHAT_ID.startswith("-100XX"):
        try:
            requests.post(
                url, 
                json={"chat_id": CHANNEL_CHAT_ID, "text": full_text, "parse_mode": "Markdown"}, 
                timeout=10
            )
        except Exception as e:
            print(f"Telegram Channel Error: {e}")

# ================= 5. STATE & CRASH BACKUP =================
def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "active_trade": None,
        "support_sent_today": False,
        "daily_report_sent_today": False,
        "monthly_report_sent_today": False,
        "startup_alert_sent": False,
        "last_hourly_alert_hour": None
    }

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=4)

def log_trade(trade_record):
    trades = []
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r") as f:
                trades = json.load(f)
        except Exception:
            trades = []
    trades.append(trade_record)
    with open(HISTORY_FILE, "w") as f:
        json.dump(trades, f, indent=4)

def clear_expiry_cycle_trades():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "w") as f:
            json.dump([], f)

# ================= 6. PDF & EMAIL REPORT =================
def generate_pdf_report(filename, title, subtitle, trades):
    doc = SimpleDocTemplate(filename, pagesize=letter, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
    styles = getSampleStyleSheet()
    elements = []

    title_style = ParagraphStyle("TitleStyle", parent=styles["Heading1"], fontSize=16, textColor=colors.HexColor("#1A365D"), spaceAfter=10)
    elements.append(Paragraph(title, title_style))
    elements.append(Paragraph(subtitle, styles["Normal"]))
    elements.append(Spacer(1, 15))

    table_data = [["Date", "Signal", "Entry Price", "Exit Price", "P&L (Points)", "Reason", "Time"]]
    total_points = 0.0

    if not trades:
        table_data.append(["-", "No Trades", "-", "-", "-", "-", "-"])
    else:
        for t in trades:
            pts = round(t["pnl_points"], 2)
            total_points += pts
            table_data.append([
                t.get("date", "-"),
                t["action"],
                f"{t['entry']}",
                f"{t['exit']}",
                f"{'+' if pts > 0 else ''}{pts}",
                t["reason"],
                t["exit_time"]
            ])

    t = Table(table_data, colWidths=[70, 60, 80, 80, 85, 120, 60])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#2B6CB0")),
        ("TEXTCOLOR", (0,0), (-1,0), colors.whitesmoke),
        ("ALIGN", (0,0), (-1,-1), "CENTER"),
        ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
        ("GRID", (0,0), (-1,-1), 1, colors.HexColor("#CBD5E0")),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#F7FAFC")]),
    ]))
    elements.append(t)
    elements.append(Spacer(1, 20))

    summary_text = f"<b>Net Cumulative P&L:</b> {'+' if total_points > 0 else ''}{round(total_points, 2)} Points"
    elements.append(Paragraph(summary_text, styles["Heading2"]))
    doc.build(elements)
    return filename

def send_email_with_attachment(pdf_path, subject, body_text):
    try:
        msg = MIMEMultipart()
        msg["From"] = ADMIN_EMAIL
        msg["To"] = ADMIN_EMAIL
        msg["Subject"] = subject
        msg.attach(MIMEText(body_text, "plain"))

        with open(pdf_path, "rb") as attachment:
            p = MIMEBase("application", "octet-stream")
            p.set_payload(attachment.read())
            encoders.encode_base64(p)
            p.add_header("Content-Disposition", f"attachment; filename= {os.path.basename(pdf_path)}")
            msg.attach(p)

        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(ADMIN_EMAIL, GMAIL_APP_PASS.replace(" ", ""))
        server.sendmail(ADMIN_EMAIL, ADMIN_EMAIL, msg.as_string())
        server.quit()
        print(f"Email sent successfully: {subject}")
    except Exception as e:
        print(f"Failed to send email: {e}")

# ================= 7. SCALPING INDICATORS (EMA 5, 10, 20, 50, 200 + Volume) =================
def calculate_indicators(df):
    df["EMA5"] = df["Close"].ewm(span=5, adjust=False).mean()
    df["EMA10"] = df["Close"].ewm(span=10, adjust=False).mean()
    df["EMA20"] = df["Close"].ewm(span=20, adjust=False).mean()
    df["EMA50"] = df["Close"].ewm(span=50, adjust=False).mean()
    df["EMA200"] = df["Close"].ewm(span=200, adjust=False).mean()
    
    df["VolMA20"] = df["Volume"].rolling(window=20).mean()
    return df

# ================= 8. INTRADAY SCALPING SCANNER =================
def process_market_cycle(state):
    now_ist = datetime.now(IST)
    curr_time = now_ist.time()
    today_str = now_ist.strftime("%Y-%m-%d")

    if dtime(9, 0) <= curr_time < dtime(9, 5):
        if not state.get("startup_alert_sent"):
            send_telegram("🚀 *MARKET SESSION START (9:00 AM):*\nNifty 1-Min Scalping Bot Active.", target="admin")
            state["startup_alert_sent"] = True
            save_state(state)

    df = get_nifty_candle_data()
    if df is None or len(df) < 210:
        return

    df = calculate_indicators(df)

    if dtime(9, 5) <= curr_time < dtime(9, 15):
        if not state.get("support_sent_today"):
            c_spot = round(float(df.iloc[-1]["Close"]), 2)
            msg = (
                f"📊 *NIFTY SCALPING LIVE FEED (9:05 AM)*\n\n"
                f"• *Current Nifty Spot:* {c_spot}\n"
                f"• *Strategy:* Price + Volume + EMA (5, 10, 20, 50, 200)"
            )
            send_telegram(msg, target="all")
            state["support_sent_today"] = True
            save_state(state)

    if 10 <= now_ist.hour <= 15:
        if state.get("last_hourly_alert_hour") != now_ist.hour:
            c_spot = round(float(df.iloc[-1]["Close"]), 2)
            active = state.get("active_trade")
            if active:
                trade_info = f"`{active['action']}` (Entry: {active['entry']} | {'T1 Secured 🎯' if active['t1_hit'] else 'Active SL: ' + str(active['spot_sl'])})"
            else:
                trade_info = "None (Scanning 1-Min Setup)"

            trades_cnt = 0
            if os.path.exists(HISTORY_FILE):
                try:
                    with open(HISTORY_FILE, "r") as f:
                        h_trades = json.load(f)
                        trades_cnt = len([t for t in h_trades if t.get("date") == today_str])
                except Exception:
                    pass

            hourly_msg = (
                f"⏱ *HOURLY SCALPING UPDATE ({now_ist.strftime('%I:00 %p')})*\n\n"
                f"🟢 *Bot Health:* Active (Nifty Spot Scalping)\n"
                f"📈 *Nifty Spot:* {c_spot}\n"
                f"🔄 *Active Trade:* {trade_info}\n"
                f"📑 *Today's Scalps Closed:* {trades_cnt}"
            )
            send_telegram(hourly_msg, target="admin")
            state["last_hourly_alert_hour"] = now_ist.hour
            save_state(state)

    if dtime(9, 15) <= curr_time <= dtime(15, 20):
        candle = df.iloc[-1]
        prev_candle = df.iloc[-2]
        
        c_close = float(candle["Close"])
        c_high = float(candle["High"])
        c_low = float(candle["Low"])
        c_vol = float(candle["Volume"])
        vol_ma = float(candle["VolMA20"]) if not np.isnan(candle["VolMA20"]) else c_vol

        ema5 = float(candle["EMA5"])
        ema10 = float(candle["EMA10"])
        ema20 = float(candle["EMA20"])
        ema50 = float(candle["EMA50"])
        ema200 = float(candle["EMA200"])
        
        prev_ema5 = float(prev_candle["EMA5"])
        prev_ema10 = float(prev_candle["EMA10"])

        active = state.get("active_trade")

        if active is not None:
            if not active["t1_hit"]:
                if (active["action"] == "BUY" and c_high >= active["spot_t1"]) or (active["action"] == "SELL" and c_low <= active["spot_t1"]):
                    active["t1_hit"] = True
                    active["sl_active"] = False
                    msg = (
                        f"🎯 *SAS ALERT: TARGET 1 (T1) ACHIEVED (+30 pts)*\n"
                        f"• Nifty Spot T1 Hit ({active['spot_t1']})\n"
                        f"• Trade Secured: **Stop Loss Removed**."
                    )
                    send_telegram(msg, target="all")
                    save_state(state)

            if active["t1_hit"] and not active["t2_hit"]:
                if (active["action"] == "BUY" and c_high >= active["spot_t2"]) or (active["action"] == "SELL" and c_low <= active["spot_t2"]):
                    active["t2_hit"] = True
                    send_telegram(f"🚀 *SAS ALERT: TARGET 2 (T2) ACHIEVED (+60 pts)*\n• Nifty Spot T2 Hit ({active['spot_t2']})", target="all")
                    save_state(state)

            if active["t2_hit"] and not active["t3_hit"]:
                if (active["action"] == "BUY" and c_high >= active["spot_t3"]) or (active["action"] == "SELL" and c_low <= active["spot_t3"]):
                    active["t3_hit"] = True
                    exit_price = active["spot_t3"]
                    pnl = (exit_price - active["entry"]) if active["action"] == "BUY" else (active["entry"] - exit_price)
                    send_telegram(f"🏆 *SAS ALERT: FINAL TARGET 3 (T3) HIT (+90 pts)*\n• Nifty Spot T3 Hit ({active['spot_t3']})", target="all")
                    
                    log_trade({
                        "date": today_str, "action": active["action"],
                        "entry": active["entry"], "exit": exit_price,
                        "pnl_points": pnl, "reason": "Target 3 Achieved (+90 pts)",
                        "exit_time": now_ist.strftime("%H:%M")
                    })
                    state["active_trade"] = None
                    save_state(state)
                    return

            if active["sl_active"]:
                sl_hit = (active["action"] == "BUY" and c_low <= active["spot_sl"]) or (active["action"] == "SELL" and c_high >= active["spot_sl"])
                if sl_hit:
                    exit_price = active["spot_sl"]
                    pnl = (exit_price - active["entry"]) if active["action"] == "BUY" else (active["entry"] - exit_price)
                    send_telegram(f"🛑 *SAS ALERT: STOP LOSS HIT (-30 pts)*\n• Nifty Spot SL Hit ({active['spot_sl']})", target="all")
                    log_trade({
                        "date": today_str, "action": active["action"],
                        "entry": active["entry"], "exit": exit_price,
                        "pnl_points": pnl, "reason": "Stop Loss Hit (-30 pts)",
                        "
