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
ANGEL_API_KEY = "Qm1mu8xU[span_2](start_span)"[span_2](end_span)
ANGEL_TOTP_KEY = "XXWTRAQWY6B4XGDBHD2YAJRVJE[span_3](start_span)"[span_3](end_span)
ANGEL_CLIENT_CODE = os.getenv("ANGEL_CLIENT_CODE", "AACM196001")[span_4](start_span)[span_4](end_span)
ANGEL_PIN = os.getenv("ANGEL_PIN", "4099")[span_5](start_span)[span_5](end_span)

BOT_TOKEN = "8804327561:AAECrvtU0MCYB80L0ZchoKy_YDpwJ52zQA8[span_6](start_span)"[span_6](end_span)
ADMIN_CHAT_ID = "6789591588[span_7](start_span)"[span_7](end_span)
CHANNEL_CHAT_ID = "-100XXXXXXXXXX[span_8](start_span)"[span_8](end_span)

ADMIN_EMAIL = "shinos99@gmail.com[span_9](start_span)"[span_9](end_span)
GMAIL_APP_PASS = "wgms etgl eklv cdja[span_10](start_span)"[span_10](end_span)

STATE_FILE = "sas_bot_state.json[span_11](start_span)"[span_11](end_span)
HISTORY_FILE = "sas_expiry_cycle_trades.json[span_12](start_span)"[span_12](end_span)
IST = pytz.timezone("Asia/Kolkata")[span_13](start_span)[span_13](end_span)

# NSE Trading Holidays with Reason
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
    last_day = calendar.monthrange(year, month)[1][span_14](start_span)[span_14](end_span)
    d = date(year, month, last_day)[span_15](start_span)[span_15](end_span)

    target_weekday = 3  # Thursday[span_16](start_span)[span_16](end_span)
    while d.weekday() != target_weekday:[span_17](start_span)[span_17](end_span)
        d -= timedelta(days=1)[span_18](start_span)[span_18](end_span)

    while d.strftime("%Y-%m-%d") in NSE_HOLIDAYS_2026 or d.weekday() >= 5:
        d -= timedelta(days=1)[span_19](start_span)[span_19](end_span)

    return d[span_20](start_span)[span_20](end_span)

def is_today_monthly_expiry():
    today = datetime.now(IST).date()[span_21](start_span)[span_21](end_span)
    expiry_date = get_monthly_expiry_date(today.year, today.month)[span_22](start_span)[span_22](end_span)
    return today == expiry_date[span_23](start_span)[span_23](end_span)

# ================= 3. ANGEL ONE SMART API =================
def init_angel_session():
    global smart_api
    try:
        smart_api = SmartConnect(api_key=ANGEL_API_KEY)[span_24](start_span)[span_24](end_span)
        totp = pyotp.TOTP(ANGEL_TOTP_KEY).now()[span_25](start_span)[span_25](end_span)
        data = smart_api.generateSession(ANGEL_CLIENT_CODE, ANGEL_PIN, totp)[span_26](start_span)[span_26](end_span)
        if data and data.get("status"):[span_27](start_span)[span_27](end_span)
            print("Angel One Session Authenticated Successfully.")[span_28](start_span)[span_28](end_span)
            return True[span_29](start_span)[span_29](end_span)
        else:
            err_msg = data.get("message") if data else "Unknown[span_30](start_span)"[span_30](end_span)
            print(f"Angel One Login Failed: {err_msg}")[span_31](start_span)[span_31](end_span)
            return False[span_32](start_span)[span_32](end_span)
    except Exception as e:
        print(f"Error during Angel One login: {e}")[span_33](start_span)[span_33](end_span)
        return False[span_34](start_span)[span_34](end_span)

def get_angel_nifty_candle_data():
    global smart_api
    try:
        now_dt = datetime.now(IST)[span_35](start_span)[span_35](end_span)
        from_date = (now_dt - pd.Timedelta(days=5)).strftime("%Y-%m-%d 09:15")[span_36](start_span)[span_36](end_span)
        to_date = now_dt.strftime("%Y-%m-%d %H:%M")[span_37](start_span)[span_37](end_span)

        historic_param = {
            "exchange": "NSE",
            "symboltoken": "99926000",
            "interval": "FIVE_MINUTE",
            "fromdate": from_date,
            "todate": to_date
        }[span_38](start_span)[span_38](end_span)
        res = smart_api.getCandleData(historic_param)[span_39](start_span)[span_39](end_span)
        if res and res.get("status") and res.get("data"):[span_40](start_span)[span_40](end_span)
            cols = ["Timestamp", "Open", "High", "Low", "Close", "Volume"][span_41](start_span)[span_41](end_span)
            df = pd.DataFrame(res["data"], columns=cols)[span_42](start_span)[span_42](end_span)
            df["Timestamp"] = pd.to_datetime(df["Timestamp"])[span_43](start_span)[span_43](end_span)
            df.set_index("Timestamp", inplace=True)[span_44](start_span)[span_44](end_span)
            return df[span_45](start_span)[span_45](end_span)
        else:
            init_angel_session()[span_46](start_span)[span_46](end_span)
            return None[span_47](start_span)[span_47](end_span)
    except Exception as e:
        print(f"Data Fetch Exception: {e}")[span_48](start_span)[span_48](end_span)
        return None[span_49](start_span)[span_49](end_span)

# ================= 4. TELEGRAM UTILS =================
def send_telegram(text: str, target="admin"):
    header = "📢 *SAS LEVEL TRACKER*\n[span_50](start_span)"[span_50](end_span)
    full_text = f"{header}\n{text}[span_51](start_span)"[span_51](end_span)
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage[span_52](start_span)"[span_52](end_span)
    
    # 1. Send to Admin
    try:
        res = requests.post(
            url, 
            json={"chat_id": ADMIN_CHAT_ID, "text": full_text, "parse_mode": "Markdown"}, 
            timeout=10
        )[span_53](start_span)[span_53](end_span)
        data = res.json()[span_54](start_span)[span_54](end_span)
        if not data.get("ok"):[span_55](start_span)[span_55](end_span)
            print(f"Telegram Admin Error [{res.status_code}]: {data.get('description')}")[span_56](start_span)[span_56](end_span)
        else:
            print("Telegram Alert Dispatched to Admin Successfully!")[span_57](start_span)[span_57](end_span)
    except Exception as e:
        print(f"Telegram Admin Connection Error: {e}")[span_58](start_span)[span_58](end_span)

    # 2. Send to Channel / Subscribers
    if target == "all" and CHANNEL_CHAT_ID and not CHANNEL_CHAT_ID.startswith("-100XX"):[span_59](start_span)[span_59](end_span)
        try:
            requests.post(
                url, 
                json={"chat_id": CHANNEL_CHAT_ID, "text": full_text, "parse_mode": "Markdown"}, 
                timeout=10
            )[span_60](start_span)[span_60](end_span)
        except Exception as e:
            print(f"Telegram Channel Error: {e}")[span_61](start_span)[span_61](end_span)

# ================= 5. STATE & CRASH BACKUP =================
def load_state():
    if os.path.exists(STATE_FILE):[span_62](start_span)[span_62](end_span)
        try:
            with open(STATE_FILE, "r") as f:[span_63](start_span)[span_63](end_span)
                return json.load(f)[span_64](start_span)[span_64](end_span)
        except Exception:
            pass
    return {
        "active_trade": None,[span_65](start_span)[span_65](end_span)
        "support_sent_today": False,[span_66](start_span)[span_66](end_span)
        "daily_report_sent_today": False,[span_67](start_span)[span_67](end_span)
        "monthly_report_sent_today": False,[span_68](start_span)[span_68](end_span)
        "startup_alert_sent": False,[span_69](start_span)[span_69](end_span)
        "last_hourly_alert_hour": None
    }

def save_state(state):
    with open(STATE_FILE, "w") as f:[span_70](start_span)[span_70](end_span)
        json.dump(state, f, indent=4)[span_71](start_span)[span_71](end_span)

def log_trade(trade_record):
    trades = [][span_72](start_span)[span_72](end_span)
    if os.path.exists(HISTORY_FILE):[span_73](start_span)[span_73](end_span)
        try:
            with open(HISTORY_FILE, "r") as f:[span_74](start_span)[span_74](end_span)
                trades = json.load(f)[span_75](start_span)[span_75](end_span)
        except Exception:
            trades = [][span_76](start_span)[span_76](end_span)
    trades.append(trade_record)[span_77](start_span)[span_77](end_span)
    with open(HISTORY_FILE, "w") as f:[span_78](start_span)[span_78](end_span)
        json.dump(trades, f, indent=4)[span_79](start_span)[span_79](end_span)

def clear_expiry_cycle_trades():
    if os.path.exists(HISTORY_FILE):[span_80](start_span)[span_80](end_span)
        with open(HISTORY_FILE, "w") as f:[span_81](start_span)[span_81](end_span)
            json.dump([], f)[span_82](start_span)[span_82](end_span)

# ================= 6. PDF & EMAIL REPORT =================
def generate_pdf_report(filename, title, subtitle, trades):
    doc = SimpleDocTemplate(filename, pagesize=letter, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)[span_83](start_span)[span_83](end_span)
    styles = getSampleStyleSheet()[span_84](start_span)[span_84](end_span)
    elements = [][span_85](start_span)[span_85](end_span)

    title_style = ParagraphStyle("TitleStyle", parent=styles["Heading1"], fontSize=16, textColor=colors.HexColor("#1A365D"), spaceAfter=10)[span_86](start_span)[span_86](end_span)
    elements.append(Paragraph(title, title_style))[span_87](start_span)[span_87](end_span)
    elements.append(Paragraph(subtitle, styles["Normal"]))[span_88](start_span)[span_88](end_span)
    elements.append(Spacer(1, 15))[span_89](start_span)[span_89](end_span)

    table_data = [["Date", "Signal", "Entry Price", "Exit Price", "P&L (Points)", "Reason", "Time"]][span_90](start_span)[span_90](end_span)
    total_points = 0.0[span_91](start_span)[span_91](end_span)

    if not trades:[span_92](start_span)[span_92](end_span)
        table_data.append(["-", "No Trades", "-", "-", "-", "-", "-"])[span_93](start_span)[span_93](end_span)
    else:
        for t in trades:[span_94](start_span)[span_94](end_span)
            pts = round(t["pnl_points"], 2)[span_95](start_span)[span_95](end_span)
            total_points += pts[span_96](start_span)[span_96](end_span)
            table_data.append([
                t.get("date", "-"),[span_97](start_span)[span_97](end_span)
                t["action"],[span_98](start_span)[span_98](end_span)
                f"Rs.{t['entry']}",[span_99](start_span)[span_99](end_span)
                f"Rs.{t['exit']}",[span_100](start_span)[span_100](end_span)
                f"{'+' if pts > 0 else ''}{pts}",[span_101](start_span)[span_101](end_span)
                t["reason"],[span_102](start_span)[span_102](end_span)
                t["exit_time"][span_103](start_span)[span_103](end_span)
            ])[span_104](start_span)[span_104](end_span)

    t = Table(table_data, colWidths=[70, 60, 80, 80, 85, 120, 60])[span_105](start_span)[span_105](end_span)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#2B6CB0")),[span_106](start_span)[span_106](end_span)
        ("TEXTCOLOR", (0,0), (-1,0), colors.whitesmoke),[span_107](start_span)[span_107](end_span)
        ("ALIGN", (0,0), (-1,-1), "CENTER"),[span_108](start_span)[span_108](end_span)
        ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),[span_109](start_span)[span_109](end_span)
        ("GRID", (0,0), (-1,-1), 1, colors.HexColor("#CBD5E0")),[span_110](start_span)[span_110](end_span)
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#F7FAFC")]),[span_111](start_span)[span_111](end_span)
    ]))[span_112](start_span)[span_112](end_span)
    elements.append(t)[span_113](start_span)[span_113](end_span)
    elements.append(Spacer(1, 20))[span_114](start_span)[span_114](end_span)

    summary_text = f"<b>Net Cumulative P&L (Strict Entry to Exit):</b> {'+' if total_points > 0 else ''}{round(total_points, 2)} Points[span_115](start_span)"[span_115](end_span)
    elements.append(Paragraph(summary_text, styles["Heading2"]))[span_116](start_span)[span_116](end_span)
    doc.build(elements)[span_117](start_span)[span_117](end_span)
    return filename[span_118](start_span)[span_118](end_span)

def send_email_with_attachment(pdf_path, subject, body_text):
    try:
        msg = MIMEMultipart()[span_119](start_span)[span_119](end_span)
        msg["From"] = ADMIN_EMAIL[span_120](start_span)[span_120](end_span)
        msg["To"] = ADMIN_EMAIL[span_121](start_span)[span_121](end_span)
        msg["Subject"] = subject[span_122](start_span)[span_122](end_span)
        msg.attach(MIMEText(body_text, "plain"))[span_123](start_span)[span_123](end_span)

        with open(pdf_path, "rb") as attachment:[span_124](start_span)[span_124](end_span)
            p = MIMEBase("application", "octet-stream")[span_125](start_span)[span_125](end_span)
            p.set_payload(attachment.read())[span_126](start_span)[span_126](end_span)
            encoders.encode_base64(p)[span_127](start_span)[span_127](end_span)
            p.add_header("Content-Disposition", f"attachment; filename= {os.path.basename(pdf_path)}")[span_128](start_span)[span_128](end_span)
            msg.attach(p)[span_129](start_span)[span_129](end_span)

        server = smtplib.SMTP("smtp.gmail.com", 587)[span_130](start_span)[span_130](end_span)
        server.starttls()[span_131](start_span)[span_131](end_span)
        server.login(ADMIN_EMAIL, GMAIL_APP_PASS.replace(" ", ""))[span_132](start_span)[span_132](end_span)
        server.sendmail(ADMIN_EMAIL, ADMIN_EMAIL, msg.as_string())[span_133](start_span)[span_133](end_span)
        server.quit()[span_134](start_span)[span_134](end_span)
        print(f"Email sent successfully: {subject}")[span_135](start_span)[span_135](end_span)
    except Exception as e:
        print(f"Failed to send email: {e}")[span_136](start_span)[span_136](end_span)

# ================= 7. TECHNICAL CALCULATIONS =================
def calculate_camarilla_levels(df_daily):
    prev = df_daily.iloc[-2][span_137](start_span)[span_137](end_span)
    h, l, c = float(prev["High"]), float(prev["Low"]), float(prev["Close"])[span_138](start_span)[span_138](end_span)
    diff = h - l[span_139](start_span)[span_139](end_span)
    return {
        "H4": round(c + (diff * 1.1 / 2.0), 2),[span_140](start_span)[span_140](end_span)
        "H3": round(c + (diff * 1.1 / 4.0), 2),[span_141](start_span)[span_141](end_span)
        "L3": round(c - (diff * 1.1 / 4.0), 2),[span_142](start_span)[span_142](end_span)
        "L4": round(c - (diff * 1.1 / 2.0), 2),[span_143](start_span)[span_143](end_span)
        "PP": round((h + l + c) / 3.0, 2)[span_144](start_span)[span_144](end_span)
    }

# ================= 8. INTRADAY SCANNER & TARGET RULES =================
def process_market_cycle(state):
    now_ist = datetime.now(IST)[span_145](start_span)[span_145](end_span)
    curr_time = now_ist.time()[span_146](start_span)[span_146](end_span)
    today_str = now_ist.strftime("%Y-%m-%d")[span_147](start_span)[span_147](end_span)

    # 1. 09:00 AM - Market Session Start Alert (Admin Only)
    if dtime(9, 0) <= curr_time < dtime(9, 5):[span_148](start_span)[span_148](end_span)
        if not state.get("startup_alert_sent"):[span_149](start_span)[span_149](end_span)
            send_telegram("🚀 *MARKET SESSION START (9:00 AM):*\nIntraday continuous cycle active.", target="admin")[span_150](start_span)[span_150](end_span)
            state["startup_alert_sent"] = True[span_151](start_span)[span_151](end_span)
            save_state(state)[span_152](start_span)[span_152](end_span)

    df = get_angel_nifty_candle_data()[span_153](start_span)[span_153](end_span)
    if df is None or len(df) < 20:[span_154](start_span)[span_154](end_span)
        return[span_155](start_span)[span_155](end_span)

    # 2. 09:05 AM - Nifty Resistance and Support Levels
    if dtime(9, 5) <= curr_time < dtime(9, 15):[span_156](start_span)[span_156](end_span)
        if not state.get("support_sent_today"):[span_157](start_span)[span_157](end_span)
            df_daily = df.resample("D").agg({"Open": "first", "High": "max", "Low": "min", "Close": "last"}).dropna()[span_158](start_span)[span_158](end_span)
            levels = calculate_camarilla_levels(df_daily)[span_159](start_span)[span_159](end_span)
            msg = (
                f"📊 *NIFTY INTRADAY LEVELS (Live Feed)*\n\n"
                f"• *Resistance 2 (Breakout H4):* Rs.{levels['H4']}\n"
                f"• *Resistance 1 (Cam H3):* Rs.{levels['H3']}\n"
                f"• *Pivot Point (PP):* Rs.{levels['PP']}\n"
                f"• *Support 1 (Cam L3):* Rs.{levels['L3']}\n"
                f"• *Support 2 (Breakdown L4):* Rs.{levels['L4']}"
            )[span_160](start_span)[span_160](end_span)
            send_telegram(msg, target="all")[span_161](start_span)[span_161](end_span)
            state["support_sent_today"] = True[span_162](start_span)[span_162](end_span)
            save_state(state)[span_163](start_span)[span_163](end_span)

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
                f"🟢 *Bot Health:* Active & Monitoring\n"
                f"📈 *Nifty Current Spot:* Rs.{c_spot}\n"
                f"📊 *Session High / Low:* Rs.{c_high_day} / Rs.{c_low_day}\n\n"
                f"🔄 *Active Trade:* {trade_info}\n"
                f"📑 *Today's Trades Closed:* {trades_cnt}\n"
                f"🎯 *Key Levels:* H4: Rs.{cam_levels['H4']} | L4: Rs.{cam_levels['L4']}"
            )
            send_telegram(hourly_msg, target="admin")
            state["last_hourly_alert_hour"] = now_ist.hour
            save_state(state)

    # 4. 09:15 AM to 03:00 PM - Signal Processing
    if dtime(9, 15) <= curr_time <= dtime(15, 0):[span_164](start_span)[span_164](end_span)
        high_low = df["High"] - df["Low"][span_165](start_span)[span_165](end_span)
        high_close = np.abs(df["High"] - df["Close"].shift())[span_166](start_span)[span_166](end_span)
        low_close = np.abs(df["Low"] - df["Close"].shift())[span_167](start_span)[span_167](end_span)
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)[span_168](start_span)[span_168](end_span)
        df["ATR"] = tr.rolling(14).mean()[span_169](start_span)[span_169](end_span)
        df["EMA9"] = df["Close"].ewm(span=9, adjust=False).mean()[span_170](start_span)[span_170](end_span)
        df["EMA21"] = df["Close"].ewm(span=21, adjust=False).mean()[span_171](start_span)[span_171](end_span)

        candle = df.iloc[-1][span_172](start_span)[span_172](end_span)
        prior = df.iloc[-2][span_173](start_span)[span_173](end_span)
        c_close = float(candle["Close"])[span_174](start_span)[span_174](end_span)
        c_high = float(candle["High"])[span_175](start_span)[span_175](end_span)
        c_low = float(candle["Low"])[span_176](start_span)[span_176](end_span)
        c_atr = float(candle["ATR"])[span_177](start_span)[span_177](end_span)
        c_ema9 = float(candle["EMA9"])[span_178](start_span)[span_178](end_span)
        c_ema21 = float(candle["EMA21"])[span_179](start_span)[span_179](end_span)

        df_daily = df.resample("D").agg({"Open": "first", "High": "max", "Low": "min", "Close": "last"}).dropna()[span_180](start_span)[span_180](end_span)
        levels = calculate_camarilla_levels(df_daily)[span_181](start_span)[span_181](end_span)
        active = state.get("active_trade")[span_182](start_span)[span_182](end_span)

        # Active Trade Management
        if active is not None:[span_183](start_span)[span_183](end_span)
            # T1 Achieved
            if not active["t1_hit"]:[span_184](start_span)[span_184](end_span)
                if (active["action"] == "BUY" and c_high >= active["t1"]) or (active["action"] == "SELL" and c_low <= active["t1"]):[span_185](start_span)[span_185](end_span)
                    active["t1_hit"] = True[span_186](start_span)[span_186](end_span)
                    active["sl_active"] = False[span_187](start_span)[span_187](end_span)
                    msg = (
                        f"🎯 *TARGET 1 (T1) ACHIEVED! [Rs.{active['t1']}]*\n\n"
                        f"• Trade Secured: **Stop Loss Removed Completely**.\n"
                        f"• Trailing for Target 2 (Rs.{active['t2']}) & Target 3 (Rs.{active['t3']})."
                    )[span_188](start_span)[span_188](end_span)
                    send_telegram(msg, target="all")[span_189](start_span)[span_189](end_span)
                    save_state(state)[span_190](start_span)[span_190](end_span)

            # T2 Achieved
            if active["t1_hit"] and not active["t2_hit"]:[span_191](start_span)[span_191](end_span)
                if (active["action"] == "BUY" and c_high >= active["t2"]) or (active["action"] == "SELL" and c_low <= active["t2"]):[span_192](start_span)[span_192](end_span)
                    active["t2_hit"] = True[span_193](start_span)[span_193](end_span)
                    send_telegram(f"🚀 *TARGET 2 (T2) ACHIEVED! [Rs.{active['t2']}]*\nTrail stops to lock profit.", target="all")[span_194](start_span)[span_194](end_span)
                    save_state(state)[span_195](start_span)[span_195](end_span)

            # T3 Hit (Complete Exit)
            if active["t2_hit"] and not active["t3_hit"]:[span_196](start_span)[span_196](end_span)
                if (active["action"] == "BUY" and c_high >= active["t3"]) or (active["action"] == "SELL" and c_low <= active["t3"]):[span_197](start_span)[span_197](end_span)
                    active["t3_hit"] = True[span_198](start_span)[span_198](end_span)
                    exit_price = active["t3"][span_199](start_span)[span_199](end_span)
                    pnl = (exit_price - active["entry"]) if active["action"] == "BUY" else (active["entry"] - exit_price)[span_200](start_span)[span_200](end_span)
                    send_telegram(f"🏆 *FINAL TARGET 3 (T3) HIT! [Rs.{exit_price}]*\nExit full position.", target="all")[span_201](start_span)[span_201](end_span)
                    
                    log_trade({
                        "date": today_str, "action": active["action"],
                        "entry": active["entry"], "exit": exit_price,
                        "pnl_points": pnl, "reason": "Target 3 Achieved",
                        "exit_time": now_ist.strftime("%H:%M")
                    })[span_202](start_span)[span_202](end_span)
                    state["active_trade"] = None[span_203](start_span)[span_203](end_span)
                    save_state(state)[span_204](start_span)[span_204](end_span)
                    return

            # SL Check (Only prior to T1)
            if active["sl_active"]:[span_205](start_span)[span_205](end_span)
                sl_hit = (active["action"] == "BUY" and c_low <= active["sl"]) or (active["action"] == "SELL" and c_high >= active["sl"])[span_206](start_span)[span_206](end_span)
                if sl_hit:[span_207](start_span)[span_207](end_span)
                    exit_price = active["sl"][span_208](start_span)[span_208](end_span)
                    pnl = (exit_price - active["entry"]) if active["action"] == "BUY" else (active["entry"] - exit_price)[span_209](start_span)[span_209](end_span)
                    send_telegram(f"🛑 *STOP LOSS HIT! [Rs.{exit_price}]*\nExit trade.", target="all")[span_210](start_span)[span_210](end_span)
                    log_trade({
                        "date": today_str, "action": active["action"],
                        "entry": active["entry"], "exit": exit_price,
                        "pnl_points": pnl, "reason": "Stop Loss Hit",
                        "exit_time": now_ist.strftime("%H:%M")
                    })[span_211](start_span)[span_211](end_span)
                    state["active_trade"] = None[span_212](start_span)[span_212](end_span)
                    save_state(state)[span_213](start_span)[span_213](end_span)
                    return

        # New Signal Scan
        new_signal = None[span_214](start_span)[span_214](end_span)
        if float(prior["Close"]) <= levels["H4"] and c_close > levels["H4"] and c_ema9 > c_ema21:[span_215](start_span)[span_215](end_span)
            new_signal = "BUY[span_216](start_span)"[span_216](end_span)
        elif float(prior["Close"]) >= levels["L4"] and c_close < levels["L4"] and c_ema9 < c_ema21:[span_217](start_span)[span_217](end_span)
            new_signal = "SELL[span_218](start_span)"[span_218](end_span)

        if new_signal:[span_219](start_span)[span_219](end_span)
            if state["active_trade"] is None:[span_220](start_span)[span_220](end_span)
                trigger_entry(new_signal, c_close, c_atr, now_ist, state)[span_221](start_span)[span_221](end_span)
            elif state["active_trade"]["t1_hit"]:[span_222](start_span)[span_222](end_span)
                prev_action = state["active_trade"]["action"][span_223](start_span)[span_223](end_span)
                prev_entry = state["active_trade"]["entry"][span_224](start_span)[span_224](end_span)
                exit_price = round(c_close, 2)[span_225](start_span)[span_225](end_span)
                pnl = (exit_price - prev_entry) if prev_action == "BUY" else (prev_entry - exit_price)[span_226](start_span)[span_226](end_span)
                
                send_telegram(
                    f"⚠️ *EXIT PREVIOUS TRADE ALERT*\n\n"
                    f"New market momentum formed.\n"
                    f"• *Exit Current Trade At:* Rs.{exit_price}\n"
                    f"• *Strict Gain Locked:* {'+' if pnl > 0 else ''}{round(pnl, 2)} Pts",
                    target="all"
                )[span_227](start_span)[span_227](end_span)
                log_trade({
                    "date": today_str, "action": prev_action,
                    "entry": prev_entry, "exit": exit_price,
                    "pnl_points": pnl, "reason": "Replaced by New Signal",
                    "exit_time": now_ist.strftime("%H:%M")
                })[span_228](start_span)[span_228](end_span)
                trigger_entry(new_signal, c_close, c_atr, now_ist, state)[span_229](start_span)[span_229](end_span)

    # 5. 03:20 PM - Intraday Auto Square-Off
    if dtime(15, 20) <= curr_time < dtime(15, 30):[span_230](start_span)[span_230](end_span)
        if state.get("active_trade") is not None:[span_231](start_span)[span_231](end_span)
            active = state["active_trade"][span_232](start_span)[span_232](end_span)
            exit_price = round(float(df.iloc[-1]["Close"]), 2)[span_233](start_span)[span_233](end_span)
            pnl = (exit_price - active["entry"]) if active["action"] == "BUY" else (active["entry"] - exit_price)[span_234](start_span)[span_234](end_span)
            send_telegram(f"⏰ *INTRADAY AUTO SQUARE-OFF (3:20 PM)*\nExiting at Rs.{exit_price}.", target="all")[span_235](start_span)[span_235](end_span)
            log_trade({
                "date": today_str, "action": active["action"],
                "entry": active["entry"], "exit": exit_price,
                "pnl_points": pnl, "reason": "Intraday Close (3:20 PM)",
                "exit_time": now_ist.strftime("%H:%M")
            })[span_236](start_span)[span_236](end_span)
            state["active_trade"] = None[span_237](start_span)[span_237](end_span)
            save_state(state)[span_238](start_span)[span_238](end_span)

    # 6. 03:45 PM - Daily Report
    if dtime(15, 45) <= curr_time < dtime(15, 55):[span_239](start_span)[span_239](end_span)
        if not state.get("daily_report_sent_today"):[span_240](start_span)[span_240](end_span)
            all_trades = [][span_241](start_span)[span_241](end_span)
            if os.path.exists(HISTORY_FILE):[span_242](start_span)[span_242](end_span)
                try:
                    with open(HISTORY_FILE, "r") as f:[span_243](start_span)[span_243](end_span)
                        all_trades = json.load(f)[span_244](start_span)[span_244](end_span)
                except Exception:
                    pass
            today_trades = [t for t in all_trades if t.get("date") == today_str][span_245](start_span)[span_245](end_span)

            pdf_filename = f"SAS_Daily_Report_{today_str}.pdf[span_246](start_span)"[span_246](end_span)
            generate_pdf_report(
                pdf_filename,
                f"SAS LEVEL TRACKER - DAILY REPORT",
                f"<b>Date:</b> {today_str} | <b>Calculation:</b> Strict Entry to Exit",
                today_trades
            )[span_247](start_span)[span_247](end_span)
            send_email_with_attachment(
                pdf_filename,
                f"SAS LEVEL TRACKER: Daily P&L Report ({today_str})",
                f"Hello Admin,\n\nPlease find attached the Daily P&L Report for {today_str}."
            )[span_248](start_span)[span_248](end_span)
            net_pts = sum(t["pnl_points"] for t in today_trades)[span_249](start_span)[span_249](end_span)
            send_telegram(
                f"📄 *DAILY P&L REPORT (3:45 PM)*\n\n"
                f"• *Date:* {today_str}\n"
                f"• *Trades Executed:* {len(today_trades)}\n"
                f"• *Strict Net P&L:* {'+' if net_pts > 0 else ''}{round(net_pts, 2)} Pts\n"
                f"Verified PDF sent to Admin email ({ADMIN_EMAIL}).",
                target="all"
            )[span_250](start_span)[span_250](end_span)
            state["daily_report_sent_today"] = True[span_251](start_span)[span_251](end_span)
            save_state(state)[span_252](start_span)[span_252](end_span)

    # 7. 03:45 PM - Monthly Expiry Report
    if dtime(15, 45) <= curr_time < dtime(15, 55):[span_253](start_span)[span_253](end_span)
        if is_today_monthly_expiry() and not state.get("monthly_report_sent_today"):[span_254](start_span)[span_254](end_span)
            all_cycle_trades = [][span_255](start_span)[span_255](end_span)
            if os.path.exists(HISTORY_FILE):[span_256](start_span)[span_256](end_span)
                try:
                    with open(HISTORY_FILE, "r") as f:[span_257](start_span)[span_257](end_span)
                        all_cycle_trades = json.load(f)[span_258](start_span)[span_258](end_span)
                except Exception:
                    pass

            month_str = now_ist.strftime("%B_%Y")[span_259](start_span)[span_259](end_span)
            monthly_pdf = f"SAS_Monthly_Expiry_Report_{month_str}.pdf[span_260](start_span)"[span_260](end_span)
            generate_pdf_report(
                monthly_pdf,
                f"SAS LEVEL TRACKER - MONTHLY EXPIRY DETAILED REPORT",
                f"<b>Expiry Date:</b> {today_str} | <b>Cycle:</b> Expiry to Expiry Detailed P&L",
                all_cycle_trades
            )[span_261](start_span)[span_261](end_span)
            send_email_with_attachment(
                monthly_pdf,
                f"SAS LEVEL TRACKER: Monthly Expiry-to-Expiry Report ({month_str})",
                f"Hello Admin,\n\nToday is Monthly Expiry Day. Attached is the complete Expiry-to-Expiry performance log."
            )[span_262](start_span)[span_262](end_span)
            total_cycle_pts = sum(t["pnl_points"] for t in all_cycle_trades)[span_263](start_span)[span_263](end_span)
            send_telegram(
                f"🏆 *MONTHLY EXPIRY-TO-EXPIRY REPORT (3:45 PM)*\n\n"
                f"Today marks the Monthly Expiry Day!\n"
                f"• *Total Cycle Trades:* {len(all_cycle_trades)}\n"
                f"• *Total Cycle Net P&L:* {'+' if total_cycle_pts > 0 else ''}{round(total_cycle_pts, 2)} Pts\n"
                f"Detailed Monthly P&L statement dispatched to Admin email.",
                target="all"
            )[span_264](start_span)[span_264](end_span)
            clear_expiry_cycle_trades()[span_265](start_span)[span_265](end_span)
            state["monthly_report_sent_today"] = True[span_266](start_span)[span_266](end_span)
            save_state(state)[span_267](start_span)[span_267](end_span)

def trigger_entry(action, price, atr, now_ist, state):
    sl_dist = max(round(1.2 * atr, 1), 22.0)[span_268](start_span)[span_268](end_span)
    t1_dist = round(sl_dist * 1.0, 1)[span_269](start_span)[span_269](end_span)
    t2_dist = round(sl_dist * 1.8, 1)[span_270](start_span)[span_270](end_span)
    t3_dist = round(sl_dist * 2.8, 1)[span_271](start_span)[span_271](end_span)

    entry = round(price, 2)[span_272](start_span)[span_272](end_span)
    if action == "BUY":[span_273](start_span)[span_273](end_span)
        sl = round(entry - sl_dist, 2)[span_274](start_span)[span_274](end_span)
        t1 = round(entry + t1_dist, 2)[span_275](start_span)[span_275](end_span)
        t2 = round(entry + t2_dist, 2)[span_276](start_span)[span_276](end_span)
        t3 = round(entry + t3_dist, 2)[span_277](start_span)[span_277](end_span)
        strike = f"{round(entry / 50.0) * 50} CE[span_278](start_span)"[span_278](end_span)
    else:
        sl = round(entry + sl_dist, 2)[span_279](start_span)[span_279](end_span)
        t1 = round(entry - t1_dist, 2)[span_280](start_span)[span_280](end_span)
        t2 = round(entry - t2_dist, 2)[span_281](start_span)[span_281](end_span)
        t3 = round(entry - t3_dist, 2)[span_282](start_span)[span_282](end_span)
        strike = f"{round(entry / 50.0) * 50} PE[span_283](start_span)"[span_283](end_span)

    msg = (
        f"⚡ *NEW INTRADAY SIGNAL (ANGEL ONE)*\n\n"
        f"• *Instrument:* NIFTY 50 (`{strike}`)\n"
        f"• *Action:* *{action}*\n"
        f"• *Entry Price:* Rs.{entry}\n"
        f"• *Target 1 (T1):* Rs.{t1}\n"
        f"• *Target 2 (T2):* Rs.{t2}\n"
        f"• *Target 3 (T3):* Rs.{t3}\n"
        f"• *Stop Loss (SL):* Rs.{sl}\n"
        f"• *Time:* {now_ist.strftime('%H:%M:%S')} IST"
    )[span_284](start_span)[span_284](end_span)
    send_telegram(msg, target="all")[span_285](start_span)[span_285](end_span)

    state["active_trade"] = {
        "action": action, "entry": entry,
        "t1": t1, "t2": t2, "t3": t3, "sl": sl,
        "t1_hit": False, "t2_hit": False, "t3_hit": False,
        "sl_active": True, "entry_time": now_ist.strftime("%H:%M")
    }[span_286](start_span)[span_286](end_span)
    save_state(state)[span_287](start_span)[span_287](end_span)

# ================= 9. MASTER BOT LOOP =================
def main():
    print("Starting SAS LEVEL TRACKER Service...")[span_288](start_span)[span_288](end_span)
    
    now_ist = datetime.now(IST)
    today_str = now_ist.strftime("%Y-%m-%d")
    weekday = now_ist.weekday()

    # 1. Weekend Check (Saturday = 5, Sunday = 6)
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

    # 2. NSE Holiday Check (Morning 8:58 AM - 9:00 AM Alert with Reason)
    if today_str in NSE_HOLIDAYS_2026:
        reason = NSE_HOLIDAYS_2026[today_str]
        holiday_msg = (
            f"🏖️ *MARKET HOLIDAY ALERT (NSE/BSE)*\n\n"
            f"• *Date:* {today_str}\n"
            f"• *Occasion:* *{reason}*\n"
            f"• *Status:* Market is officially closed today.\n"
            f"Live scanner and alerts are paused. Workflow stopped to preserve free minutes."
        )
        send_telegram(holiday_msg, target="all")
        print(f"Holiday today: {reason}. Notification dispatched. Exiting.")
        sys.exit(0)

    # Active Trading Day
    send_telegram("🚀 *BOT RUNNING:* System triggered. Execution active.", target="admin")[span_289](start_span)[span_289](end_span)

    state = load_state()[span_290](start_span)[span_290](end_span)
    init_angel_session()[span_291](start_span)[span_291](end_span)

    while True:
        try:
            now_ist = datetime.now(IST)[span_292](start_span)[span_292](end_span)
            curr_time = now_ist.time()[span_293](start_span)[span_293](end_span)

            # 3:50 PM കഴിഞ്ഞാൽ റിപ്പോർട്ട് പൂർത്തിയാക്കി GitHub Actions തനിയെ ക്ലോസ് ആകുന്നു
            if curr_time > dtime(15, 50):
                print("Market closed & Daily reports sent. Shutting down bot.")
                send_telegram("🛑 *SYSTEM SHUTDOWN (3:50 PM):* Daily session completed. Bot stopped to save minutes.", target="admin")
                break

            # 8:58 AM - 3:50 PM Live Scanner Loop
            if dtime(8, 58) <= curr_time <= dtime(15, 50):
                process_market_cycle(state)
                time.sleep(5)
            else:
                time.sleep(30)

        except Exception as e:
            print(f"Engine Loop Error: {e}")[span_294](start_span)[span_294](end_span)
            time.sleep(10)

    print("Workflow completed successfully.")
    sys.exit(0)

if __name__ == "__main__":
    main()[span_295](start_span)[span_295](end_span)
