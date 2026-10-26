import os
import time
import calendar
import requests
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet

# --- CONFIGURATIONS ---
TELEGRAM_BOT_TOKEN = "8804327561:AAECrvtU0MCYB80L0ZchoKy_YDpwJ52zQA8"
ADMIN_CHAT_ID = "6789591588"       # Admin Chat ID
CHANNEL_CHAT_ID = "-1004416495917"  # Channel Chat ID

def send_alert_to_admin(message):
    """Sends alert exclusively to the Admin chat"""
    if not TELEGRAM_BOT_TOKEN or not ADMIN_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": ADMIN_CHAT_ID, "text": message, "parse_mode": "Markdown"})
    except Exception as e:
        print(f"Error sending admin alert: {e}")

def send_alert_to_joiners(message):
    """Sends alerts (Levels, Signals & Square-off) to Telegram Joiners/Channel"""
    if not TELEGRAM_BOT_TOKEN or not CHANNEL_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": CHANNEL_CHAT_ID, "text": message, "parse_mode": "Markdown"})
    except Exception as e:
        print(f"Error sending joiners alert: {e}")

def generate_pdf_report(filename="sas_daily_report.pdf"):
    """Generates professional PDF report for Daily P&L"""
    try:
        doc = SimpleDocTemplate(filename, pagesize=letter)
        story = []
        styles = getSampleStyleSheet()
        
        story.append(Paragraph("SAS LEVEL TRACKER - DAILY REPORT", styles['Title']))
        story.append(Spacer(1, 12))
        
        date_str = datetime.now().strftime('%Y-%m-%d')
        story.append(Paragraph(f"<b>Date:</b> {date_str}", styles['Normal']))
        story.append(Spacer(1, 8))
        
        content = (
            "<b>Strategy Used:</b> Price + Volume + EMA (5, 10, 20, 50, 200) [3-Min Candle]<br/>"
            "<b>Total Signals Generated:</b> Today's Active Signals<br/>"
            "<b>Status:</b> Market Closed & All Positions Square-off Completed.<br/><br/>"
            "<i>Generated automatically by SAS LEVEL TRACKER Bot.</i>"
        )
        story.append(Paragraph(content, styles['Normal']))
        doc.build(story)
    except Exception as e:
        print(f"Error generating PDF: {e}")

def send_pdf_report_to_telegram(filename="sas_daily_report.pdf"):
    """Sends the generated PDF report to Admin and Channel"""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendDocument"
    if os.path.exists(filename):
        try:
            with open(filename, 'rb') as pdf_file:
                files = {'document': pdf_file}
                caption_text = "🔴🟠 **SAS LEVEL TRACKER** 🔴🟠\n📊 **Daily P&L & Market Report PDF**"
                requests.post(url, data={'chat_id': ADMIN_CHAT_ID, 'caption': caption_text, 'parse_mode': 'Markdown'}, files=files)
                requests.post(url, data={'chat_id': CHANNEL_CHAT_ID, 'caption': caption_text, 'parse_mode': 'Markdown'}, files=files)
        except Exception as e:
            print(f"Error sending PDF to Telegram: {e}")

def get_market_levels():
    try:
        df = yf.download("^NSEI", period="2d", interval="1d", progress=False)
        if df is not None and not df.empty:
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.droplevel(1)
            high = float(df.iloc[-1]['High'])
            low = float(df.iloc[-1]['Low'])
            close = float(df.iloc[-1]['Close'])
            
            pivot = (high + low + close) / 3
            resistance_1 = (2 * pivot) - low
            support_1 = (2 * pivot) - high
            
            return round(support_1, 2), round(resistance_1, 2)
    except Exception as e:
        print(f"Error getting market levels: {e}")
    return 0, 0

def run_continuous_bot():
    print("🚀 SAS Level Tracker Continuous Bot Started...")
    
    # Flags to ensure actions happen only once per day
    startup_sent_date = ""
    levels_sent_date = ""
    square_off_sent_date = ""
    report_sent_date = ""

    while True:
        try:
            now = datetime.now()
            current_date = now.strftime("%Y-%m-%d")
            current_hour_min = int(now.strftime("%H%M"))
            current_weekday = now.weekday() # 0-4 = Monday to Friday

            # Skip weekends (Saturday=5, Sunday=6)
            if current_weekday >= 5:
                print("Weekend today. Sleeping for 1 hour...")
                time.sleep(3600)
                continue

            # 1. 9:00 AM Startup Alert -> ADMIN ONLY (Once a day)
            if 900 <= current_hour_min <= 904 and startup_sent_date != current_date:
                test_msg = (
                    "🔴🟠 **SAS LEVEL TRACKER** 🔴🟠\n\n"
                    "🚀 **BOT RUN SUCCESSFULLY (LIVE)**\n"
                    f"📅 **Date:** {now.strftime('%Y-%m-%d %H:%M:%S')}\n"
                    "🟢 **System Status:** Connected and monitoring market continuously."
                )
                send_alert_to_admin(test_msg)
                startup_sent_date = current_date
                print("Startup message sent to admin.")

            # 2. 9:05 AM Support & Resistance Alert -> CHANNEL ONLY (Once a day)
            if 905 <= current_hour_min <= 909 and levels_sent_date != current_date:
                sup, res = get_market_levels()
                msg = (
                    "🔴🟠 **SAS LEVEL TRACKER** 🔴🟠\n\n"
                    "📊 **NIFTY / STOCK SUPPORT & RESISTANCE**\n\n"
                    f"🔴 **Resistance 1:** `{res}`\n"
                    f"🟢 **Support 1:** `{sup}`\n\n"
                    "⚠️ Watch out for breakouts!"
                )
                send_alert_to_joiners(msg)
                levels_sent_date = current_date
                print("Support & Resistance levels sent to channel.")

            # 3. 9:15 AM to 3:19 PM Live Signals (3-Min Interval check)
            if 915 <= current_hour_min <= 1519:
                ticker = "^NSEI" # Nifty 50
                df = yf.download(ticker, period="5d", interval="3m", progress=False)
                
                if df is not None and not df.empty:
                    if isinstance(df.columns, pd.MultiIndex):
                        df.columns = df.columns.droplevel(1)

                    df['EMA_5'] = df['Close'].ewm(span=5, adjust=False).mean()
                    df['EMA_10'] = df['Close'].ewm(span=10, adjust=False).mean()
                    df['EMA_20'] = df['Close'].ewm(span=20, adjust=False).mean()
                    df['EMA_50'] = df['Close'].ewm(span=50, adjust=False).mean()
                    df['EMA_200'] = df['Close'].ewm(span=200, adjust=False).mean()

                    latest = df.iloc[-1]
                    close_price = float(latest['Close'])
                    volume = float(latest['Volume'])
                    avg_volume = df['Volume'].rolling(window=20).mean().iloc[-1]

                    ema5 = float(latest['EMA_5'])
                    ema10 = float(latest['EMA_10'])
                    ema20 = float(latest['EMA_20'])
                    ema50 = float(latest['EMA_50'])
                    ema200 = float(latest['EMA_200'])

                    is_uptrend = (close_price > ema200) and (ema5 > ema10) and (ema10 > ema20) and (ema20 > ema50)
                    is_volume_spike = volume > (avg_volume * 1.2)

                    if is_uptrend and is_volume_spike:
                        entry_price = close_price
                        stop_loss = round(ema20 - (entry_price * 0.001), 2)
                        risk = entry_price - stop_loss
                        
                        t1 = round(entry_price + (risk * 1), 2)
                        t2 = round(entry_price + (risk * 2), 2)
                        t3 = round(entry_price + (risk * 3), 2)

                        signal_msg = (
                            "🔴🟠 **SAS LEVEL TRACKER** 🔴🟠\n\n"
                            "🚨 **INTRADAY SIGNAL ALERT (3-Min)** 🚨\n\n"
                            "📊 **Asset:** NIFTY 50\n"
                            "🟢 **Action:** BUY (LONG)\n"
                            f"💰 **Entry Price:** `{entry_price}`\n\n"
                            f"🛑 **Stop Loss (SL):** `{stop_loss}`\n"
                            f"🎯 **Target 1 (T1):** `{t1}`\n"
                            f"🎯 **Target 2 (T2):** `{t2}`\n"
                            f"🎯 **Target 3 (T3):** `{t3}`\n\n"
                            "📈 **Status:** Active Signal\n"
                            f"⏰ **Time:** {now.strftime('%H:%M:%S')}"
                        )
                        send_alert_to_joiners(signal_msg)
                        print("3-Min Signal sent to joiners successfully.")

            # 4. 3:20 PM Auto Square-off Warning -> CHANNEL ONLY (Once a day)
            if 1520 <= current_hour_min <= 1524 and square_off_sent_date != current_date:
                square_off_msg = (
                    "🔴🟠 **SAS LEVEL TRACKER** 🔴🟠\n\n"
                    "⚠️ **AUTO SQUARE-OFF WARNING (3:20 PM)** ⚠️\n\n"
                    "🔔 All active intraday positions should be closed or manual square-off recommended!\n"
                    "🚪 Exit previous signals now to avoid broker auto-square off charges.\n\n"
                    f"⏰ **Time:** {now.strftime('%H:%M:%S')}"
                )
                send_alert_to_joiners(square_off_msg)
                square_off_sent_date = current_date
                print("Auto square-off warning sent to joiners.")

            # 5. 3:35 PM Daily Report Generation & PDF Send -> ADMIN & CHANNEL (Once a day)
            if 1535 <= current_hour_min <= 1540 and report_sent_date != current_date:
                try:
                    generate_pdf_report()
                    send_pdf_report_to_telegram()
                    report_sent_date = current_date
                    print("Daily PDF Report generated and sent successfully.")
                except Exception as e:
                    print(f"Error generating report: {e}")

            # Wait for 3 minutes (180 seconds) before checking the market again
            time.sleep(180)

        except Exception as e:
            print(f"Error in continuous loop: {e}")
            time.sleep(60)

if __name__ == "__main__":
    run_continuous_bot()
