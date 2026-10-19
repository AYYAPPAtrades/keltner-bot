import os
import sys
import json
import time
import smtplib
import calendar
import requests
import subprocess
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

# ================= 3. TELEGRAM UTILS =================
def send_telegram(text: str, target="admin"):
    header = "📢 *SAS LEVEL TRACKER*\n"
    full_text = f"{header}\n{text}"
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    
    try:
        requests.post(url, json={"chat_id": ADMIN_CHAT_ID, "text": full_text, "parse_mode": "Markdown"}, timeout=10)
    except Exception as e:
        print(f"Telegram Admin Error: {e}")

    if target == "all" and CHANNEL_CHAT_ID and not CHANNEL_CHAT_ID.startswith("-100XX"):
        try:
            requests.post(url, json={"chat_id": CHANNEL_CHAT_ID, "text": full_text, "parse_mode": "Markdown"}, timeout=10)
        except Exception as e:
            print(f"Telegram Channel Error: {e}")

def send_telegram_document_to_all(pdf_path, caption_text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"
    chat_ids = [ADMIN_CHAT_ID]
    if CHANNEL_CHAT_ID and not CHANNEL_CHAT_ID.startswith("-100XX"):
        chat_ids.append(CHANNEL_CHAT_ID)

    for chat_id in chat_ids:
        try:
            with open(pdf_path, "rb") as doc:
                requests.post(
                    url,
                    data={"chat_id": chat_id, "caption": caption_text, "parse_mode": "Markdown"},
                    files={"document": doc},
                    timeout=30
                )
        except Exception as e:
            print(f"Telegram PDF Document Error for {chat_id}: {e}")

# ================= 4. PDF & EMAIL REPORT =================
def generate_pdf_report(filename, title, subtitle, trades):
    doc = SimpleDocTemplate(filename, pagesize=letter, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
    styles = getSampleStyleSheet()
    elements = []

    title_style = ParagraphStyle("TitleStyle", parent=styles["Heading1"], fontSize=16, textColor=colors.HexColor("#1A365D"), spaceAfter=10)
    elements.append(Paragraph(title, title_style))
    elements.append(Paragraph(subtitle, styles["Normal"]))
    elements.append(Spacer(1, 15))

    table_data = [["Date", "Signal", "Strike", "Spot Entry", "Spot Exit", "Spot P&L", "Reason", "Time"]]
    total_spot_pts = 0.0

    if not trades:
        table_data.append(["-", "No Trades Recorded", "-", "-", "-", "-", "-", "-"])
    else:
        for t in trades:
            s_pts = round(t.get("spot_pnl", t.get("pnl_points", 0.0)), 2)
            total_spot_pts += s_pts
            table_data.append([
                t.get("date", "-"),
                t["action"],
                t.get("strike", "-"),
                f"Rs.{t['entry']}",
                f"Rs.{t['exit']}",
                f"{'+' if s_pts > 0 else ''}{s_pts}",
                t["reason"],
                t["exit_time"]
            ])

    t = Table(table_data, colWidths=[70, 50, 75, 75, 75, 75, 100, 55])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#2B6CB0")),
        ("TEXTCOLOR", (0,0), (-1,0), colors.whitesmoke),
        ("ALIGN", (0,0), (-1,-1), "CENTER"),
        ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
        ("FONTSIZE", (0,0), (-1,-1), 8),
        ("GRID", (0,0), (-1,-1), 1, colors.HexColor("#CBD5E0")),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#F7FAFC")]),
    ]))
    elements.append(t)
    elements.append(Spacer(1, 15))

    summary_text = f"<b>Spot Net Cumulative P&L:</b> {'+' if total_spot_pts > 0 else ''}{round(total_spot_pts, 2)} Points"
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

# ================= 5. MAIN EXECUTION (FORCED MANUAL REPORT) =================
def main():
    now_ist = datetime.now(IST)
    today_str = now_ist.strftime("%Y-%m-%d")
    
    print(f"Generating Manual / On-Demand Report for {today_str}...")

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
        f"SAS LEVEL TRACKER - DAILY SCALPING REPORT",
        f"<b>Date:</b> {today_str} | <b>Calculation:</b> T1 Secured / Entry to Exit",
        today_trades
    )

    send_email_with_attachment(
        pdf_filename,
        f"SAS LEVEL TRACKER: Daily P&L Report ({today_str})",
        f"Hello Admin,\n\nPlease find attached the Daily Scalping P&L Report for {today_str}. Total Trades: {len(today_trades)}."
    )

    net_pts = sum(t.get("spot_pnl", t.get("pnl_points", 0.0)) for t in today_trades)
    send_telegram_document_to_all(
        pdf_filename, 
        f"📄 *SAS ALERT: DAILY P&L REPORT ({today_str})*\n\n"
        f"• *Trades Executed:* {len(today_trades)}\n"
        f"• *Net P&L:* {'+' if net_pts > 0 else ''}{round(net_pts, 2)} Pts"
    )
    print("Report successfully generated and dispatched!")

if __name__ == "__main__":
    main()
