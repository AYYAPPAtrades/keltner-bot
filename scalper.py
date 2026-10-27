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
import ta
import yfinance as yf
from datetime import datetime, date, timedelta, time as dtime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
import pytz

# ================= 1. CREDENTIALS & CONSTANTS =================
BOT_TOKEN = "8830008372:AAGaq16u0STxZR1Z9q3qO5Lr1MQD288_9pc"

ADMIN_CHAT_ID = "6789591588"
TELEGRAM_CHAT_IDS = [
    "8996427731",
    "6789591588",
    "-1004399032148"
]

ADMIN_EMAIL = "Shinos99@gmail.com"
GMAIL_EMAIL_PASS = "Qm1mu8xU"

STATE_FILE = "trade_state.json"
DATA_LOG_FILE = "trade_history.json"
IST = pytz.timezone('Asia/Kolkata')

TARGET_PTS = 30.0
SL_PTS = 30.0

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

# ================= 3. TELEGRAM & EMAIL UTILS (WITH DEBUG) =================
def send_telegram(message, admin_only=False):
    target_chats = [ADMIN_CHAT_ID] if admin_only else TELEGRAM_CHAT_IDS
    formatted_msg = f"⚡ *SAS LEVEL TRACKER* ⚡\n\n{message}"
    
    for cid in target_chats:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        payload = {"chat_id": cid, "text": formatted_msg, "parse_mode": "Markdown"}
        try:
            res = requests.post(url, json=payload, timeout=10)
            print(f"DEBUG - Telegram to {cid}: Status {res.status_code}, Response: {res.text}")
        except Exception as e:
            print(f"DEBUG - Telegram Connection Error for {cid}: {e}")

def send_telegram_file(file_path, caption):
    caption_text = f"📊 *SAS LEVEL TRACKER*\n{caption}"
    for cid in TELEGRAM_CHAT_IDS:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"
        post_data = {"chat_id": cid, "caption": caption_text, "parse_mode": "Markdown"}
        try:
            with open(file_path, 'rb') as f:
                res = requests.post(url, data=post_data, files={'document': f}, timeout=25)
                print(f"DEBUG - File Send to {cid}: Status {res.status_code}, Response: {res.text}")
        except Exception as e:
            print(f"Telegram File Send Error: {e}")

def send_email_with_pdf(file_path, subject):
    try:
        msg = MIMEMultipart()
        msg['From'] = ADMIN_EMAIL
        msg['To'] = ADMIN_EMAIL
        msg['Subject'] = f"SAS LEVEL TRACKER - {subject}"
        msg.attach(MIMEText("Please find attached the trading performance report.", 'plain'))
        
        with open(file_path, 'rb') as attachment:
            part = MIMEBase('application', 'octet-stream')
            part.set_payload(attachment.read())
            encoders.encode_base64(part)
            part.add_header('Content-Disposition', f'attachment; filename="{os.path.basename(file_path)}"')
            msg.attach(part)
            
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(ADMIN_EMAIL, GMAIL_EMAIL_PASS.replace(" ", ""))
        server.sendmail(ADMIN_EMAIL, ADMIN_EMAIL, msg.as_string())
        server.quit()
        print("Email sent successfully.")
    except Exception as e:
        print(f"Email Dispatch Error: {e}")

# ================= 4. STATE & GITHUB BACKUP =================
def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                return
