
import os
import json
import smtplib
import requests
from datetime import datetime
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

BOT_TOKEN = "8804327561:AAECrvtU0MCYB80L0ZchoKy_YDpwJ52zQA8"
ADMIN_CHAT_ID = "6789591588"
CHANNEL_CHAT_ID = "-1004416495917"
ADMIN_EMAIL = "shinos99@gmail.com"
GMAIL_APP_PASS = "wgms etgl eklv cdja"

HISTORY_FILE = "sas_expiry_cycle_trades.json"
IST = pytz.timezone("Asia/Kolkata")

def send_telegram(text: str):
    header = "📢 *SAS LEVEL TRACKER - MANUAL REPORT*\n"
    full_text = f"{header}\n{text}"
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": ADMIN_CHAT_ID, "text": full_text, "parse_mode": "Markdown"}, timeout=10)
        requests.post(url, json={"chat_id": CHANNEL_CHAT_ID, "text": full_text, "parse_mode": "Markdown"}, timeout=10)
    except Exception as e:
        print(f"Telegram Error: {e}")

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
        table_data.append(["-", "No Trades Today", "-", "-", "-", "-", "-"])
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
        print("Email sent successfully.")
    except Exception as e:
        print(f"Email Failed: {e}")

if __name__ == "__main__":
    today_str = datetime.now(IST).strftime("%Y-%m-%d")
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
        f"<b>Date:</b> {today_str} | <b>Calculation:</b> Entry to Exit Price",
        today_trades
    )
    
    send_email_with_attachment(
        pdf_filename,
        f"SAS LEVEL TRACKER: Daily P&L Report ({today_str})",
        f"Hello Admin,\n\nAttached is today's manual Daily Scalping P&L Report for {today_str}."
    )
    
    net_pts = sum(t["pnl_points"] for t in today_trades)
    send_telegram(
        f"📄 *DAILY P&L REPORT (MANUAL)*\n\n"
        f"• *Date:* {today_str}\n"
        f"• *Trades Executed:* {len(today_trades)}\n"
        f"• *Net P&L:* {'+' if net_pts > 0 else ''}{round(net_pts, 2)} Pts\n"
        f"PDF report dispatched to Admin email."
    )
    print("Manual report process completed.")
