import os
import sys
import json
import time
import smtplib
import calendar
import requests
import pyotp
import numpy as np
import pandas as pd
from datetime import datetime, date, timedelta, time as dtime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
import pytz

# SmartAPI (Angel One)
from SmartApi import SmartConnect

# ReportLab for PDF generation
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

# ================= 1. CREDENTIALS & CONSTANTS =================
ANGEL_API_KEY = "Qm1mu8xU"
ANGEL_TOTP_KEY = "XXWTRAQWY6B4XGDBHD2YAJRVJE"
ANGEL_CLIENT_CODE = os.getenv("ANGEL_CLIENT_CODE", "AACM196001")
ANGEL_PIN = os.getenv("ANGEL_PIN", "4099")

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

smart_api = None

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

# ================= 3. ANGEL ONE SMART API =================
def init_angel_session():
    global smart_api
    try:
        smart_api = SmartConnect(api_key=ANGEL_API_KEY)
        totp = pyotp.TOTP(ANGEL_TOTP_KEY).now()
        data = smart_api.generateSession(ANGEL_CLIENT_CODE, ANGEL_PIN, totp)
        if data and data.get("status"):
            print("Angel One Session Authenticated Successfully.")
            return True
        else:
            err_msg = data.get("message") if data else "Unknown"
            print(f"Angel One Login Failed: {err_msg}")
            return False
    except Exception as e:
        print(f"Error during Angel One login: {e}")
        return False

def get_angel_nifty_candle_data():
    global smart_api
    try:
        now_dt = datetime.now(IST)
        from_date = (now_dt - pd.Timedelta(days=5)).strftime("%Y-%m-%d 09:15")
        to_date = now_dt.strftime("%Y-%m-%d %H:%M")

        historic_param = {
            "exchange": "NSE",
            "symboltoken": "99926000",
            "interval": "THREE_MINUTE",
            "fromdate": from_date,
            "todate": to_date
        }
        res = smart_api.getCandleData(historic_param)
        if res and res.get("status") and res.get("data"):
            cols = ["Timestamp", "Open", "High", "Low", "Close", "Volume"]
            df = pd.DataFrame(res["data"], columns=cols)
            df["Timestamp"] = pd.to_datetime(df["Timestamp"])
            df.set_index("Timestamp", inplace=True)
            return df
        else:
            init_angel_session()
            return None
    except Exception as e:
        print(f"Data Fetch Exception: {e}")
        return None

# ================= 4. TELEGRAM UTILS =================
def send_telegram(text: str, target="admin"):
    header = "📢 *SAS LEVEL TRACKER*\n"
    full_text = f"{header}\n{text}"
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    
    # 1. Send to Admin
    try:
        res = requests.post(
            url, 
            json={"chat_id": ADMIN_CHAT_ID, "text": full_text, "parse_mode": "Markdown"}, 
            timeout=10
        )
        data = res.json()
        if not data.get("ok"):
            print(f"Telegram Admin Error [{res.status_code}]: {data.get('description')}")
        else:
            print("Telegram Alert Dispatched to Admin Successfully!")
    except Exception as e:
        print(f"Telegram Admin Connection Error: {e}")

    # 2. Send to Channel / Subscribers
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
                f"Rs.{t['entry']}",
                f"Rs.{t['exit']}",
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

    summary_text = f"<b>Net Cumulative P&L (Strict Entry to Exit):</b> {'+' if total_points > 0 else ''}{round(total_points, 2)} Points"
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

# ================= 7. TECHNICAL CALCULATIONS =================
def calculate_camarilla_levels(df_daily):
    prev = df_daily.iloc[-2]
    h, l, c = float(prev["High"]), float(prev["Low"]), float(prev["Close"])
    diff = h - l
    return {
        "H4": round(c + (diff * 1.1 / 2.0), 2),
        "H3": round(c + (diff * 1.1 / 4.0), 2),
        "L3": round(c - (diff * 1.1 / 4.0), 2),
        "L4": round(c - (diff * 1.1 / 2.0), 2),
        "PP": round((h + l + c) / 3.0, 2)
    }

# ================= 8. INTRADAY SCANNER & TARGET RULES =================
def process_market_cycle(state):
    now_ist = datetime.now(IST)
    curr_time = now_ist.time()
    today_str = now_ist.strftime("%Y-%m-%d")

    # 1. 09:00 AM - Market Session Start Alert (Admin Only)
    if dtime(9, 0) <= curr_time < dtime(9, 5):
        if not state.get("startup_alert_sent"):
            send_telegram("🚀 *MARKET SESSION START (9:00 AM):*\nIntraday continuous cycle active (3-Min Frame).", target="admin")
            state["startup_alert_sent"] = True
            save_state(state)

    df = get_angel_nifty_candle_data()
    if df is None or len(df) < 20:
        return

    # 2. 09:05 AM - Nifty Resistance and Support Levels
    if dtime(9, 5) <= curr_time < dtime(9, 15):
        if not state.get("support_sent_today"):
            df_daily = df.resample("D").agg({"Open": "first", "High": "max", "Low": "min", "Close": "last"}).dropna()
            levels = calculate_camarilla_levels(df_daily)
            msg = (
                f"📊 *NIFTY INTRADAY LEVELS (Live Feed)*\n\n"
                f"• *Resistance 2 (H4):* Rs.{levels['H4']}\n"
                f"• *Resistance 1 (H3):* Rs.{levels['H3']}\n"
                f"• *Pivot Point (PP):* Rs.{levels['PP']}\n"
                f"• *Support 1 (L3):* Rs.{levels['L3']}\n"
                f"• *Support 2 (L4):* Rs.{levels['L4']}"
            )
            send_telegram(msg, target="all")
            state["support_sent_today"] = True
            save_state(state)

    # 3. HOURLY STATUS ALERT (ADMIN ONLY)
    if 10 <= now_ist.hour <= 15:
        if state.get("last_hourly_alert_hour") != now_ist.hour:
            c_spot = round(float(df.iloc[-1]["Close"]), 2)
            c_high_day = round(float(df["High"].max()), 2)
            c_low_day = round(float(df["Low"].min()), 2)

            active = state.get("active_trade")
            if active:
                trade_info = f"`{active['action']}` (Entry: Rs.{active['entry']} | {'T1 Secured 🎯' if active['t1_hit'] else 'Active SL: Rs.' + str(active['sl'])})"
            else:
                trade_info = "None (Waiting for Setup)"

            trades_cnt = 0
            if os.path.exists(HISTORY_FILE):
                try:
                    with open(HISTORY_FILE, "r") as f:
                        h_trades = json.load(f)
                        trades_cnt = len([t for t in h_trades if t.get("date") == today_str])
                except Exception:
                    pass

            df_daily = df.resample("D").agg({"Open": "first", "High": "max", "Low": "min", "Close": "last"}).dropna()
            cam_levels = calculate_camarilla_levels(df_daily)

            hourly_msg = (
                f"⏱️ *HOURLY SYSTEM & MARKET UPDATE ({now_ist.strftime('%I:00 %p')})*\n\n"
                f"🟢 *Bot Health:* Active (3-Min Frame)\n"
                f"📈 *Nifty Current Spot:* Rs.{c_spot}\n"
                f"📊 *Session High / Low:* Rs.{c_high_day} / Rs.{c_low_day}\n\n"
                f"🔄 *Active Trade:* {trade_info}\n"
                f"📑 *Today's Trades Closed:* {trades_cnt}\n"
                f"🎯 *Key Levels:* H3: Rs.{cam_levels['H3']} | L3: Rs.{cam_levels['L3']}"
            )
            send_telegram(hourly_msg, target="admin")
            state["last_hourly_alert_hour"] = now_ist.hour
            save_state(state)

    # 4. 09:30 AM to 03:00 PM - Signal Processing
    if dtime(9, 30) <= curr_time <= dtime(15, 0):
        high_low = df["High"] - df["Low"]
        high_close = np.abs(df["High"] - df["Close"].shift())
        low_close = np.abs(df["Low"] - df["Close"].shift())
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        df["ATR"] = tr.rolling(14).mean()
        df["EMA9"] = df["Close"].ewm(span=9, adjust=False).mean()
        df["EMA21"] = df["Close"].ewm(span=21, adjust=False).mean()

        candle = df.iloc[-1]
        prior = df.iloc[-2]
        c_close = float(candle["Close"])
        c_high = float(candle["High"])
        c_low = float(candle["Low"])
        c_atr = float(candle["ATR"])
        c_ema9 = float(candle["EMA9"])
        c_ema21 = float(candle["EMA21"])

        df_daily = df.resample("D").agg({"Open": "first", "High": "max", "Low": "min", "Close": "last"}).dropna()
        levels = calculate_camarilla_levels(df_daily)
        active = state.get("active_trade")

        # Active Trade Management
        if active is not None:
            # T1 Achieved
            if not active["t1_hit"]:
                if (active["action"] == "BUY" and c_high >= active["t1"]) or (active["action"] == "SELL" and c_low <= active["t1"]):
                    active["t1_hit"] = True
                    active["sl_active"] = False
                    msg = (
                        f"🎯 *TARGET 1 (T1) ACHIEVED! [Rs.{active['t1']}]*\n\n"
                        f"• Trade Secured: **Stop Loss Removed Completely**.\n"
                        f"• Trailing for Target 2 (Rs.{active['t2']}) & Target 3 (Rs.{active['t3']})."
                    )
                    send_telegram(msg, target="all")
                    save_state(state)

            # T2 Achieved
            if active["t1_hit"] and not active["t2_hit"]:
                if (active["action"] == "BUY" and c_high >= active["t2"]) or (active["action"] == "SELL" and c_low <= active["t2"]):
                    active["t2_hit"] = True
                    send_telegram(f"🚀 *TARGET 2 (T2) ACHIEVED! [Rs.{active['t2']}]*\nTrail stops to lock profit.", target="all")
                    save_state(state)

            # T3 Hit (Complete Exit)
            if active["t2_hit"] and not active["t3_hit"]:
                if (active["action"] == "BUY" and c_high >= active["t3"]) or (active["action"] == "SELL" and c_low <= active["t3"]):
                    active["t3_hit"] = True
                    exit_price = active["t3"]
                    pnl = (exit_price - active["entry"]) if active["action"] == "BUY" else (active["entry"] - exit_price)
                    send_telegram(f"🏆 *FINAL TARGET 3 (T3) HIT! [Rs.{exit_price}]*\nExit full position.", target="all")
                    
                    log_trade({
                        "date": today_str, "action": active["action"],
                        "entry": active["entry"], "exit": exit_price,
                        "pnl_points": pnl, "reason": "Target 3 Achieved",
                        "exit_time": now_ist.strftime("%H:%M")
                    })
                    state["active_trade"] = None
                    save_state(state)
                    return

            # SL Check (Only prior to T1)
            if active["sl_active"]:
                sl_hit = (active["action"] == "BUY" and c_low <= active["sl"]) or (active["action"] == "SELL" and c_high >= active["sl"])
                if sl_hit:
                    exit_price = active["sl"]
                    pnl = (exit_price - active["entry"]) if active["action"] == "BUY" else (active["entry"] - exit_price)
                    send_telegram(f"🛑 *STOP LOSS HIT! [Rs.{exit_price}]*\nExit trade.", target="all")
                    log_trade({
                        "date": today_str, "action": active["action"],
                        "entry": active["entry"], "exit": exit_price,
                        "pnl_points": pnl, "reason": "Stop Loss Hit",
                        "exit_time": now_ist.strftime("%H:%M")
                    })
                    state["active_trade"] = None
                    save_state(state)
                    return

        # New Signal Scan: Using H3 and L3 levels for early momentum signals with EMA filter
        new_signal = None
        if float(prior["Close"]) <= levels["H3"] and c_close > levels["H3"] and c_ema9 > c_ema21:
            new_signal = "BUY"
        elif float(prior["Close"]) >= levels["L3"] and c_close < levels["L3"] and c_ema9 < c_ema21:
            new_signal = "SELL"

        if new_signal and state["active_trade"] is None:
            trigger_entry(new_signal, c_close, c_atr, now_ist, state)

    # 5. 03:20 PM - Intraday Auto Square-Off
    if dtime(15, 20) <= curr_time < dtime(15, 30):
        if state.get("active_trade") is not None:
            active = state["active_trade"]
            exit_price = round(float(df.iloc[-1]["Close"]), 2)
            pnl = (exit_price - active["entry"]) if active["action"] == "BUY" else (active["entry"] - exit_price)
            
            if active.get("t2_hit"):
                status_str = "Target 1 & Target 2 Achieved (Pending T3 Closed)"
            elif active.get("t1_hit"):
                status_str = "Target 1 Achieved (Pending T2/T3 Closed)"
            else:
                status_str = "Running (No Targets Hit)"

            pnl_str = f"{'+' if pnl > 0 else ''}{round(pnl, 2)} pts"
            sq_msg = (
                f"⏰ *INTRADAY AUTO-SQUARE OFF (3:20 PM)*\n\n"
                f"• *Position:* {active['action']} NIFTY\n"
                f"• *Status:* {status_str}\n"
                f"• *Entry Price:* Rs.{active['entry']}\n"
                f"• *Exit Price:* Rs.{exit_price}\n"
                f"• *PnL:* {pnl_str}"
            )
            send_telegram(sq_msg, target="all")
            
            log_trade({
                "date": today_str, "action": active["action"],
                "entry": active["entry"], "exit": exit_price,
                "pnl_points": pnl, "reason": f"Intraday Close ({status_str})",
                "exit_time": now_ist.strftime("%H:%M")
            })
            state["active_trade"] = None
            save_state(state)

    # 6. 03:45 PM - Daily Report
    if dtime(15, 45) <= curr_time < dtime(15, 55):
        if not state.get("daily_report_sent_today"):
            all_trades = []
            if os.path.exists(HISTORY_FILE):
                try:
                    with open(HISTORY_FILE, "r") as f:
                        all_trades = json.load(f)
                except Exception:
                    pass
            today_trades = [t for t in all_trades if t.get("date") == today_str]

            pdf_filename = f"SAS_Daily_Report_{today_str}.pdf"
            generate_pdf_report(
                pdf_filename,
                f"SAS LEVEL TRACKER - DAILY REPORT",
                f"<b>Date:</b> {today_str} | <b>Calculation:</b> Strict Entry to Exit",
                today_trades
            )
            send_email_with_attachment(
                pdf_filename,
                f"SAS LEVEL TRACKER: Daily P&L Report ({today_str})",
                f"Hello Admin,\n\nPlease find attached the Daily P&L Report for {today_str}."
            )
            net_pts = sum(t["pnl_points"] for t in today_trades)
            send_telegram(
                f"📄 *DAILY P&L REPORT (3:45 PM)*\n\n"
                f"• *Date:* {today_str}\n"
                f"• *Trades Executed:* {len(today_trades)}\n"
                f"• *Strict Net P&L:* {'+' if net_pts > 0 else ''}{round(net_pts, 2)} Pts\n"
                f"Verified PDF sent to Admin email ({ADMIN_EMAIL}).",
                target="all"
            )
            state["daily_report_sent_today"] = True
            save_state(state)

    # 7. 03:45 PM - Monthly Expiry Report
    if dtime(15, 45) <= curr_time < dtime(15, 55):
        if is_today_monthly_expiry() and not state.get("monthly_report_sent_today"):
            all_cycle_trades = []
            if os.path.exists(HISTORY_FILE):
                try:
                    with open(HISTORY_FILE, "r") as f:
                        all_cycle_trades = json.load(f)
                except Exception:
                    pass

            month_str = now_ist.strftime("%B_%Y")
            monthly_pdf = f"SAS_Monthly_Expiry_Report_{month_str}.pdf"
            generate_pdf_report(
                monthly_pdf,
                f"SAS LEVEL TRACKER - MONTHLY EXPIRY DETAILED REPORT",
                f"<b>Expiry Date:</b> {today_str} | <b>Cycle:</b> Expiry to Expiry Detailed P&L",
                all_cycle_trades
            )
            send_email_with_attachment(
                monthly_pdf,
                f"SAS LEVEL TRACKER: Monthly Expiry-to-Expiry Report ({month_str})",
                f"Hello Admin,\n\nToday is Monthly Expiry Day. Attached is the complete Expiry-to-Expiry performance log."
            )
            total_cycle_pts = sum(t["pnl_points"] for t in all_cycle_trades)
            send_telegram(
                f"🏆 *MONTHLY EXPIRY-TO-EXPIRY REPORT (3:45 PM)*\n\n"
                f"Today marks the Monthly Expiry Day!\n"
                f"• *Total Cycle Trades:* {len(all_cycle_trades)}\n"
                f"• *Total Cycle Net P&L:* {'+' if total_cycle_pts > 0 else ''}{round(total_cycle_pts, 2)} Pts\n"
                f"Detailed Monthly P&L statement dispatched to Admin email.",
                target="all"
            )
            clear_expiry_cycle_trades()
            state["monthly_report_sent_today"] = True
            save_state(state)

def trigger_entry(action, price, atr, now_ist, state):
    sl_dist = max(round(1.2 * atr, 1), 22.0)
    t1_dist = round(sl_dist * 1.0, 1)
    t2_dist = round(sl_dist * 1.8, 1)
    t3_dist = round(sl_dist * 2.8, 1)

    entry = round(price, 2)
    if action == "BUY":
        sl = round(entry - sl_dist, 2)
        t1 = round(entry + t1_dist, 2)
        t2 = round(entry + t2_dist, 2)
        t3 = round(entry + t3_dist, 2)
        strike = f"{round(entry / 50.0) * 50} CE"
    else:
        sl = round(entry + sl_dist, 2)
        t1 = round(entry - t1_dist, 2)
        t2 = round(entry - t2_dist, 2)
        t3 = round(entry - t3_dist, 2)
        strike = f"{round(entry / 50.0) * 50} PE"

    msg = (
        f"⚡ *NEW INTRADAY SIGNAL (3-Min)*\n\n"
        f"• *Instrument:* NIFTY 50 (`{strike}`)\n"
        f"• *Action:* *{action}*\n"
        f"• *Entry Price:* Rs.{entry}\n"
        f"• *Target 1 (T1):* Rs.{t1}\n"
        f"• *Target 2 (T2):* Rs.{t2}\n"
        f"• *Target 3 (T3):* Rs.{t3}\n"
        f"• *Stop Loss (SL):* Rs.{sl}\n"
        f"• *Time:* {now_ist.strftime('%H:%M:%S')} IST"
    )
    send_telegram(msg, target="all")

    state["active_trade"] = {
        "action": action, "entry": entry,
        "t1": t1, "t2": t2, "t3": t3, "sl": sl,
        "t1_hit": False, "t2_hit": False, "t3_hit": False,
        "sl_active": True, "entry_time": now_ist.strftime("%H:%M")
    }
    save_state(state)

# ================= 9. MASTER BOT LOOP =================
def main():
    print("Starting SAS LEVEL TRACKER Service...")
    
    now_ist = datetime.now(IST)
    today_str = now_ist.strftime("%Y-%m-%d")
    weekday = now_ist.weekday()

    if weekday >= 5:
        day_name = "Saturday" if weekday == 5 else "Sunday"
        send_telegram(
            f"🏖️ *WEEKEND PAUSE ({day_name})*\n\n"
            f"Market is closed today. Live scanner is inactive.\n"
            f"Workflow stopped immediately to save minutes.",
            target="admin"
        )
        print("Weekend detected. Workflow exited.")
        sys.exit(0)

    if today_str in NSE_HOLIDAYS_2026:
        reason = NSE_HOLIDAYS_2026[today_str]
        holiday_msg = (
            f"🏖️ *MARKET HOLIDAY ALERT (NSE/BSE)*\n\n"
            f"• *Date:* {today_str}\n"
            f"• *Occasion:* *{reason}*\n"
            f"• *Status:* Market is officially closed today.\n"
            f"Live scanner and alerts are paused."
        )
        send_telegram(holiday_msg, target="all")
        print(f"Holiday today: {reason}. Exiting.")
        sys.exit(0)

    send_telegram("🚀 *BOT RUNNING:* 3-Minute Scanner Active.", target="admin")

    state = load_state()
    init_angel_session()

    while True:
        try:
            now_ist = datetime.now(IST)
            curr_time = now_ist.time()

            if curr_time > dtime(15, 50):
                print("Market closed & Daily reports sent. Shutting down bot.")
                send_telegram("🛑 *SYSTEM SHUTDOWN (3:50 PM):* Daily session completed.", target="admin")
                break

            if dtime(8, 58) <= curr_time <= dtime(15, 50):
                process_market_cycle(state)
                time.sleep(5)
            else:
                time.sleep(30)

        except Exception as e:
            print(f"Engine Loop Error: {e}")
            time.sleep(10)

    print("Workflow completed successfully.")
    sys.exit(0)

if __name__ == "__main__":
    main()
