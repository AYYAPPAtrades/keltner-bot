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

# ================= CONFIGURATION =================
ANGEL_API_KEY = "Qm1mu8xU[span_5](start_span)"[span_5](end_span)
ANGEL_TOTP_KEY = "XXWTRAQWY6B4XGDBHD2YAJRVJE[span_6](start_span)"[span_6](end_span)
ANGEL_CLIENT_CODE = os.getenv("ANGEL_CLIENT_CODE", "YOUR_CLIENT_ID")
ANGEL_PIN = os.getenv("ANGEL_PIN", "YOUR_4_DIGIT_PIN")

BOT_TOKEN = "8804327561:AAECrvtUOMCYB80L0ZchoKy_YDpwJ52zQA8[span_7](start_span)"[span_7](end_span)
ADMIN_CHAT_ID = "6789591588[span_8](start_span)"[span_8](end_span)
CHANNEL_CHAT_ID = "-100XXXXXXXXXX"     # ടെലിഗ്രാം ചാനൽ ID ഇവിടെ നൽകുക

ADMIN_EMAIL = "shinos99@gmail.com"
GMAIL_APP_PASS = "wgms etgl eklv cdja[span_9](start_span)"[span_9](end_span)

STATE_FILE = "sas_bot_state.json"
HISTORY_FILE = "sas_expiry_cycle_trades.json"
IST = pytz.timezone("Asia/Kolkata")

# NSE ട്രേഡിംഗ് ഹോളിഡേ ലിസ്റ്റ് (അവധി ദിവസങ്ങളിൽ എക്സ്പയറി തൊട്ടുമുമ്പത്തെ ട്രേഡിംഗ് ദിനമാകും)
NSE_HOLIDAYS_2026 = [
    "2026-01-26", "2026-03-03", "2026-03-26", "2026-04-03", 
    "2026-04-14", "2026-05-01", "2026-08-15", "2026-10-02", 
    "2026-10-20", "2026-11-08", "2026-12-25"
]

smart_api = None

# ================= MONTHLY EXPIRY CALCULATOR =================
def get_monthly_expiry_date(year, month):
    last_day = calendar.monthrange(year, month)[1]
    d = date(year, month, last_day)

    # മാസത്തിലെ അവസാന വ്യാഴാഴ്ച (Thursday = 3)
    target_weekday = 3 
    while d.weekday() != target_weekday:
        d -= timedelta(days=1)

    # അവധി ദിവസമാണെങ്കിൽ തൊട്ടുമുമ്പത്തെ ട്രേഡിംഗ് ദിനം എടുക്കുന്നു
    while d.strftime("%Y-%m-%d") in NSE_HOLIDAYS_2026 or d.weekday() >= 5:
        d -= timedelta(days=1)

    return d

def is_today_monthly_expiry():
    today = datetime.now(IST).date()
    expiry_date = get_monthly_expiry_date(today.year, today.month)
    return today == expiry_date

# ================= ANGEL ONE API =================
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
            print("Angel One Login Failed.")
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
            "interval": "FIVE_MINUTE",
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

# ================= TELEGRAM UTILS =================
def send_telegram(text: str, target="admin"):
    header = "📢 *SAS LEVEL TRACKER*\n[span_10](start_span)"[span_10](end_span)
    full_text = f"{header}\n{text}"
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage[span_11](start_span)"[span_11](end_span)
    
    # 1. അഡ്മിന് മാത്രം അയക്കുന്നു
    try:
        requests.post(url, json={"chat_id": ADMIN_CHAT_ID, "text": full_text, "parse_mode": "Markdown"}, timeout=10)[span_12](start_span)[span_12](end_span)
    except Exception as e:
        print(f"Telegram Admin Error: {e}")

    # 2. ചാനൽ ജോയിൻ ചെയ്തവർക്ക് അയക്കുന്നു
    if target == "all" and CHANNEL_CHAT_ID and not CHANNEL_CHAT_ID.startswith("-100XX"):
        try:
            requests.post(url, json={"chat_id": CHANNEL_CHAT_ID, "text": full_text, "parse_mode": "Markdown"}, timeout=10)
        except Exception as e:
            print(f"Telegram Channel Error: {e}")

# ================= STATE & TRADE BACKUP =================
def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "active_trade": None,
        "support_sent_today": False,[span_13](start_span)[span_13](end_span)
        "daily_report_sent_today": False,[span_14](start_span)[span_14](end_span)
        "monthly_report_sent_today": False,[span_15](start_span)[span_15](end_span)
        "startup_alert_sent": False[span_16](start_span)[span_16](end_span)
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

# ================= PDF & EMAIL REPORT GENERATION =================
def generate_pdf_report(filename, title, subtitle, trades):
    doc = SimpleDocTemplate(filename, pagesize=letter, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
    styles = getSampleStyleSheet()
    elements = []

    title_style = ParagraphStyle("TitleStyle", parent=styles["Heading1"], fontSize=16, textColor=colors.HexColor("#1A365D"), spaceAfter=10)
    elements.append(Paragraph(title, title_style))
    elements.append(Paragraph(subtitle, styles["Normal"]))
    elements.append(Spacer(1, 15))

    # Strict Entry to Exit Table
    table_data = [["Date", "Signal", "Entry Price", "Exit Price", "P&L (Points)", "Reason", "Time"]][span_17](start_span)[span_17](end_span)
    total_points = 0.0

    if not trades:
        table_data.append(["-", "No Trades", "-", "-", "-", "-", "-"])
    else:
        for t in trades:
            pts = round(t["pnl_points"], 2)[span_18](start_span)[span_18](end_span)
            total_points += pts
            table_data.append([
                t.get("date", "-"),
                t["action"],
                f"₹{t['entry']}",[span_19](start_span)[span_19](end_span)
                f"₹{t['exit']}",[span_20](start_span)[span_20](end_span)
                f"{'+' if pts > 0 else ''}{pts}",[span_21](start_span)[span_21](end_span)
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

    summary_text = f"<b>Net Cumulative P&L (Strict Entry to Exit):</b> {'+' if total_points > 0 else ''}{round(total_points, 2)} Points[span_22](start_span)"[span_22](end_span)
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
        server.login(ADMIN_EMAIL, GMAIL_APP_PASS.replace(" ", ""))[span_23](start_span)[span_23](end_span)
        server.sendmail(ADMIN_EMAIL, ADMIN_EMAIL, msg.as_string())
        server.quit()
        print(f"Email sent successfully: {subject}")
    except Exception as e:
        print(f"Failed to send email: {e}")

# ================= TECHNICAL CALCULATIONS =================
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

# ================= ENGINE CYCLE =================
def process_market_cycle(state):
    now_ist = datetime.now(IST)
    curr_time = now_ist.time()
    today_str = now_ist.strftime("%Y-%m-%d")

    # 1. 09:00 AM - Bot Auto-run Alert (Admin Only)
    if dtime(9, 0) <= curr_time < dtime(9, 5):
        if not state.get("startup_alert_sent"):
            send_telegram("🚀 *SYSTEM LIVE:* Angel One API Active.\nZero-delay continuous scan started at 9:00 AM.", target="admin")[span_24](start_span)[span_24](end_span)
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
                f"📊 *NIFTY INTRADAY LEVELS (Angel One Live)*\n\n"
                f"• *Resistance 2 (Breakout H4):* ₹{levels['H4']}\n"
                f"• *Resistance 1 (Cam H3):* ₹{levels['H3']}\n"
                f"• *Pivot Point (PP):* ₹{levels['PP']}\n"
                f"• *Support 1 (Cam L3):* ₹{levels['L3']}\n"
                f"• *Support 2 (Breakdown L4):* ₹{levels['L4']}"
            )
            send_telegram(msg, target="all")[span_25](start_span)[span_25](end_span)
            state["support_sent_today"] = True
            save_state(state)

    # 3. 09:15 AM to 03:00 PM - Signal Processing
    if dtime(9, 15) <= curr_time <= dtime(15, 0):[span_26](start_span)[span_26](end_span)
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
        active = state.get("active_trade")[span_27](start_span)[span_27](end_span)

        # നിലവിലുള്ള ട്രേഡ് പരിശോധിക്കുന്നു
        if active is not None:
            # T1 Achieved
            if not active["t1_hit"]:[span_28](start_span)[span_28](end_span)
                if (active["action"] == "BUY" and c_high >= active["t1"]) or (active["action"] == "SELL" and c_low <= active["t1"]):[span_29](start_span)[span_29](end_span)
                    active["t1_hit"] = True[span_30](start_span)[span_30](end_span)
                    active["sl_active"] = False  # T1 അടിച്ച ശേഷം SL പൂർണ്ണമായി ഒഴിവാക്കുന്നു[span_31](start_span)[span_31](end_span)
                    msg = (
                        f"🎯 *TARGET 1 (T1) ACHIEVED! [₹{active['t1']}]*\n\n[span_32](start_span)"[span_32](end_span)
                        f"• Trade secured: **Stop Loss Removed Completely**.\n[span_33](start_span)"[span_33](end_span)
                        f"• Now trailing for Target 2 (₹{active['t2']}) & Target 3 (₹{active['t3']}).[span_34](start_span)"[span_34](end_span)
                    )
                    send_telegram(msg, target="all")[span_35](start_span)[span_35](end_span)
                    save_state(state)

            # T2 Achieved
            if active["t1_hit"] and not active["t2_hit"]:[span_36](start_span)[span_36](end_span)
                if (active["action"] == "BUY" and c_high >= active["t2"]) or (active["action"] == "SELL" and c_low <= active["t2"]):[span_37](start_span)[span_37](end_span)
                    active["t2_hit"] = True[span_38](start_span)[span_38](end_span)
                    send_telegram(f"🚀 *TARGET 2 (T2) ACHIEVED! [₹{active['t2']}]*\nTrail stops to lock profit.", target="all")[span_39](start_span)[span_39](end_span)
                    save_state(state)

            # T3 Hit (Complete Exit)
            if active["t2_hit"] and not active["t3_hit"]:[span_40](start_span)[span_40](end_span)
                if (active["action"] == "BUY" and c_high >= active["t3"]) or (active["action"] == "SELL" and c_low <= active["t3"]):[span_41](start_span)[span_41](end_span)
                    active["t3_hit"] = True[span_42](start_span)[span_42](end_span)
                    exit_price = active["t3"]
                    pnl = (exit_price - active["entry"]) if active["action"] == "BUY" else (active["entry"] - exit_price)[span_43](start_span)[span_43](end_span)
                    send_telegram(f"🏆 *FINAL TARGET 3 (T3) HIT! [₹{exit_price}]*\nExit full position.", target="all")[span_44](start_span)[span_44](end_span)
                    
                    log_trade({
                        "date": today_str, "action": active["action"],
                        "entry": active["entry"], "exit": exit_price,[span_45](start_span)[span_45](end_span)
                        "pnl_points": pnl, "reason": "Target 3 Achieved",[span_46](start_span)[span_46](end_span)
                        "exit_time": now_ist.strftime("%H:%M")[span_47](start_span)[span_47](end_span)
                    })
                    state["active_trade"] = None[span_48](start_span)[span_48](end_span)
                    save_state(state)
                    return

            # SL Check (T1-ന് മുൻപ് മാത്രം)
            if active["sl_active"]:[span_49](start_span)[span_49](end_span)
                sl_hit = (active["action"] == "BUY" and c_low <= active["sl"]) or (active["action"] == "SELL" and c_high >= active["sl"])[span_50](start_span)[span_50](end_span)
                if sl_hit:[span_51](start_span)[span_51](end_span)
                    exit_price = active["sl"]
                    pnl = (exit_price - active["entry"]) if active["action"] == "BUY" else (active["entry"] - exit_price)[span_52](start_span)[span_52](end_span)
                    send_telegram(f"🛑 *STOP LOSS HIT! [₹{exit_price}]*\nExit trade.", target="all")[span_53](start_span)[span_53](end_span)
                    log_trade({
                        "date": today_str, "action": active["action"],
                        "entry": active["entry"], "exit": exit_price,[span_54](start_span)[span_54](end_span)
                        "pnl_points": pnl, "reason": "Stop Loss Hit",[span_55](start_span)[span_55](end_span)
                        "exit_time": now_ist.strftime("%H:%M")[span_56](start_span)[span_56](end_span)
                    })
                    state["active_trade"] = None[span_57](start_span)[span_57](end_span)
                    save_state(state)
                    return

        # പുതിയ സിഗ്നൽ സ്കാനിംഗ്
        new_signal = None
        if float(prior["Close"]) <= levels["H4"] and c_close > levels["H4"] and c_ema9 > c_ema21:
            new_signal = "BUY"
        elif float(prior["Close"]) >= levels["L4"] and c_close < levels["L4"] and c_ema9 < c_ema21:
            new_signal = "SELL"

        if new_signal:
            if state["active_trade"] is None:[span_58](start_span)[span_58](end_span)
                trigger_entry(new_signal, c_close, c_atr, now_ist, state)[span_59](start_span)[span_59](end_span)
            elif state["active_trade"]["t1_hit"]:[span_60](start_span)[span_60](end_span)
                # T1 അടിച്ച ശേഷം പുതിയ സിഗ്നൽ വന്നാൽ Exit Previous Trade Alert നൽകുന്നു
                prev_action = state["active_trade"]["action"]
                prev_entry = state["active_trade"]["entry"][span_61](start_span)[span_61](end_span)
                exit_price = round(c_close, 2)
                pnl = (exit_price - prev_entry) if prev_action == "BUY" else (prev_entry - exit_price)[span_62](start_span)[span_62](end_span)
                
                send_telegram(
                    f"⚠️ *EXIT PREVIOUS TRADE ALERT*\n\n[span_63](start_span)"[span_63](end_span)
                    f"New market momentum formed.\n[span_64](start_span)"[span_64](end_span)
                    f"• *Exit Current Trade At:* ₹{exit_price}\n[span_65](start_span)"[span_65](end_span)
                    f"• *Strict Gain Locked:* {'+' if pnl > 0 else ''}{round(pnl, 2)} Pts",[span_66](start_span)[span_66](end_span)
                    target="all[span_67](start_span)"[span_67](end_span)
                )
                log_trade({
                    "date": today_str, "action": prev_action,
                    "entry": prev_entry, "exit": exit_price,[span_68](start_span)[span_68](end_span)
                    "pnl_points": pnl, "reason": "Replaced by New Signal",[span_69](start_span)[span_69](end_span)
                    "exit_time": now_ist.strftime("%H:%M")[span_70](start_span)[span_70](end_span)
                })
                trigger_entry(new_signal, c_close, c_atr, now_ist, state)[span_71](start_span)[span_71](end_span)

    # 4. 03:20 PM - ഇൻട്രാഡേ സ്ക്വയർ-ഓഫ്
    if dtime(15, 20) <= curr_time < dtime(15, 30):
        if state.get("active_trade") is not None:[span_72](start_span)[span_72](end_span)
            active = state["active_trade"][span_73](start_span)[span_73](end_span)
            exit_price = round(float(df.iloc[-1]["Close"]), 2)
            pnl = (exit_price - active["entry"]) if active["action"] == "BUY" else (active["entry"] - exit_price)[span_74](start_span)[span_74](end_span)
            send_telegram(f"⏰ *INTRADAY AUTO SQUARE-OFF (3:20 PM)*\nExiting at ₹{exit_price}.", target="all")
            log_trade({
                "date": today_str, "action": active["action"],
                "entry": active["entry"], "exit": exit_price,[span_75](start_span)[span_75](end_span)
                "pnl_points": pnl, "reason": "Intraday Close (3:20 PM)",[span_76](start_span)[span_76](end_span)
                "exit_time": now_ist.strftime("%H:%M")[span_77](start_span)[span_77](end_span)
            })
            state["active_trade"] = None[span_78](start_span)[span_78](end_span)
            save_state(state)

    # 5. 03:45 PM - എല്ലാ ദിവസവും ഡെയ്‌ലി റിപ്പോർട്ട് (Daily Report)
    if dtime(15, 45) <= curr_time < dtime(15, 55):
        if not state.get("daily_report_sent_today"):[span_79](start_span)[span_79](end_span)
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
                f"SAS LEVEL TRACKER - DAILY REPORT",[span_80](start_span)[span_80](end_span)
                f"<b>Date:</b> {today_str} | <b>Calculation:</b> Strict Entry to Exit",[span_81](start_span)[span_81](end_span)
                today_trades
            )
            send_email_with_attachment(
                pdf_filename,
                f"SAS LEVEL TRACKER: Daily P&L Report ({today_str})",[span_82](start_span)[span_82](end_span)
                f"Hello Admin,\n\nPlease find attached the Daily P&L Report for {today_str}.[span_83](start_span)"[span_83](end_span)
            )
            net_pts = sum(t["pnl_points"] for t in today_trades)
            send_telegram(
                f"📄 *DAILY P&L REPORT (3:45 PM)*\n\n"
                f"• *Date:* {today_str}\n"
                f"• *Trades Executed:* {len(today_trades)}\n"
                f"• *Strict Net P&L:* {'+' if net_pts > 0 else ''}{round(net_pts, 2)} Pts\n"
                f"Verified PDF sent to Admin email ({ADMIN_EMAIL}).",[span_84](start_span)[span_84](end_span)
                target="all[span_85](start_span)"[span_85](end_span)
            )
            state["daily_report_sent_today"] = True[span_86](start_span)[span_86](end_span)
            save_state(state)

    # 6. 03:45 PM - MONTHLY EXPIRY DAY ആയാൽ മാത്രം പ്രത്യേക MONTHLY REPORT
    if dtime(15, 45) <= curr_time < dtime(15, 55):
        if is_today_monthly_expiry() and not state.get("monthly_report_sent_today"):[span_87](start_span)[span_87](end_span)
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
                f"SAS LEVEL TRACKER - MONTHLY EXPIRY DETAILED REPORT",[span_88](start_span)[span_88](end_span)
                f"<b>Expiry Date:</b> {today_str} | <b>Cycle:</b> Expiry to Expiry Detailed P&L",[span_89](start_span)[span_89](end_span)
                all_cycle_trades
            )
            send_email_with_attachment(
                monthly_pdf,
                f"SAS LEVEL TRACKER: Monthly Expiry-to-Expiry Report ({month_str})",[span_90](start_span)[span_90](end_span)
                f"Hello Admin,\n\nToday is Monthly Expiry Day. Attached is the complete Expiry-to-Expiry performance log.[span_91](start_span)"[span_91](end_span)
            )
            total_cycle_pts = sum(t["pnl_points"] for t in all_cycle_trades)
            send_telegram(
                f"🏆 *MONTHLY EXPIRY-TO-EXPIRY REPORT (3:45 PM)*\n\n[span_92](start_span)"[span_92](end_span)
                f"Today marks the Monthly Expiry Day!\n[span_93](start_span)"[span_93](end_span)
                f"• *Total Cycle Trades:* {len(all_cycle_trades)}\n"
                f"• *Total Cycle Net P&L:* {'+' if total_cycle_pts > 0 else ''}{round(total_cycle_pts, 2)} Pts\n"
                f"Detailed Monthly P&L statement dispatched to Admin email.",[span_94](start_span)[span_94](end_span)
                target="all[span_95](start_span)"[span_95](end_span)
            )
            clear_expiry_cycle_trades()
            state["monthly_report_sent_today"] = True[span_96](start_span)[span_96](end_span)
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
        f"⚡ *NEW INTRADAY SIGNAL (ANGEL ONE)*\n\n"
        f"• *Instrument:* NIFTY 50 (`{strike}`)\n"
        f"• *Action:* *{action}*\n"
        f"• *Entry Price:* ₹{entry}\n[span_97](start_span)"[span_97](end_span)
        f"• *Target 1 (T1):* ₹{t1}\n[span_98](start_span)"[span_98](end_span)
        f"• *Target 2 (T2):* ₹{t2}\n[span_99](start_span)"[span_99](end_span)
        f"• *Target 3 (T3):* ₹{t3}\n[span_100](start_span)"[span_100](end_span)
        f"• *Stop Loss (SL):* ₹{sl}\n[span_101](start_span)"[span_101](end_span)
        f"• *Time:* {now_ist.strftime('%H:%M:%S')} IST"
    )
    send_telegram(msg, target="all")[span_102](start_span)[span_102](end_span)

    state["active_trade"] = {
        "action": action, "entry": entry,[span_103](start_span)[span_103](end_span)
        "t1": t1, "t2": t2, "t3": t3, "sl": sl,[span_104](start_span)[span_104](end_span)
        "t1_hit": False, "t2_hit": False, "t3_hit": False,[span_105](start_span)[span_105](end_span)
        "sl_active": True, "entry_time": now_ist.strftime("%H:%M")[span_106](start_span)[span_106](end_span)
    }
    save_state(state)

# ================= MASTER LOOP =================
def main():
    print("Starting SAS LEVEL TRACKER Service...")
    init_angel_session()
    state = load_state()

    # എപ്പോൾ ബോട്ട് റീസ്റ്റാർട്ട് ആയാലും അഡ്മിന് മാത്രം അറിയിപ്പ് അയക്കുന്നു
    send_telegram("🔄 *SYSTEM RESTART:* Angel One Bot successfully recovered all trade states from local backup.", target="admin")[span_107](start_span)[span_107](end_span)

    while True:
        try:
            now_ist = datetime.now(IST)
            curr_time = now_ist.time()
            weekday = now_ist.weekday()

            if weekday >= 5:
                time.sleep(3600)
                continue

            if curr_time < dtime(8, 55):
                state["support_sent_today"] = False[span_108](start_span)[span_108](end_span)
                state["daily_report_sent_today"] = False[span_109](start_span)[span_109](end_span)
                state["monthly_report_sent_today"] = False[span_110](start_span)[span_110](end_span)
                state["startup_alert_sent"] = False[span_111](start_span)[span_111](end_span)
                save_state(state)
                time.sleep(60)
                continue

            # 9:00 AM മുതൽ 3:55 PM വരെ റൺ ചെയ്യുന്നു
            if dtime(9, 0) <= curr_time <= dtime(15, 55):
                process_market_cycle(state)
                time.sleep(5)  # 5 സെക്കൻഡ് ഇടവിട്ടുള്ള കൃത്യമായ ലൈവ് ചെക്കിംഗ്
            else:
                time.sleep(60)

        except Exception as e:
            print(f"Engine Loop Error: {e}")
            time.sleep(10)

if __name__ == "__main__":
    main()
