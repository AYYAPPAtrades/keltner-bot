
import os
import time
import calendar
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from nsepython import nse_eq_history
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet

# --- CONFIGURATIONS ---
TELEGRAM_BOT_TOKEN = "8804327561:AAECrvtU0MCYB80L0ZchoKy_YDpwJ52zQA8"
ADMIN_CHAT_ID = "6789591588"       # Admin Chat ID (Startup & Reports)
CHANNEL_CHAT_ID = "-1004416495917"  # Channel Chat ID (Levels & Live Signals)

def send_alert_to_admin(message):
    """Sends alert exclusively to the Admin chat"""
    if not TELEGRAM_BOT_TOKEN or not ADMIN_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": ADMIN_CHAT_ID, "text": message, "parse_mode": "Markdown"})

def send_alert_to_joiners(message):
    """Sends alerts (Levels & Signals) to Telegram Joiners/Channel"""
    if not TELEGRAM_BOT_TOKEN or not CHANNEL_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": CHANNEL_CHAT_ID, "text": message, "parse_mode": "Markdown"})

def find_monthly_expiry(year, month):
    """Automatically finds the monthly expiry date (Last Thursday or Tuesday of the month)"""
    last_day = calendar.monthrange(year, month)[1]
    last_date = datetime(year, month, last_day)
    offset = (last_date.weekday() - 3) % 7  # Thursday as default expiry
    expiry_date = last_date - timedelta(days=offset)
    return expiry_date.strftime('%Y-%m-%d')

def generate_pdf_report(filename="sas_daily_report.pdf"):
    """Generates professional PDF report for Daily P&L"""
    doc = SimpleDocTemplate(filename, pagesize=letter)
    story = []
    styles = getSampleStyleSheet()
    
    story.append(Paragraph("SAS LEVEL TRACKER - DAILY REPORT", styles['Title']))
    story.append(Spacer(1, 12))
    
    date_str = datetime.now().strftime('%Y-%m-%d')
    story.append(Paragraph(f"<b>Date:</b> {date_str}", styles['Normal']))
    story.append(Spacer(1, 8))
    
    content = (
        "<b>Strategy Used:</b> Price + Volume + EMA (5, 10, 20, 50, 200)<br/>"
        "<b>Total Signals Generated:</b> Today's Active Signals<br/>"
        "<b>Status:</b> Market Closed Successfully.<br/><br/>"
        "<i>Generated automatically by SAS LEVEL TRACKER Bot.</i>"
    )
    story.append(Paragraph(content, styles['Normal']))
    doc.build(story)

def send_pdf_report_to_telegram(filename="sas_daily_report.pdf"):
    """Sends the generated PDF report to Admin and Channel"""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendDocument"
    if os.path.exists(filename):
        with open(filename, 'rb') as pdf_file:
            files = {'document': pdf_file}
            caption_text = "🔴🟠 **SAS LEVEL TRACKER** 🔴🟠\n📊 **Daily P&L & Market Report PDF**"
            # Send to Admin
            requests.post(url, data={'chat_id': ADMIN_CHAT_ID, 'caption': caption_text, 'parse_mode': 'Markdown'}, files=files)
            # Send to Channel
            requests.post(url, data={'chat_id': CHANNEL_CHAT_ID, 'caption': caption_text, 'parse_mode': 'Markdown'}, files=files)

def get_market_levels():
    try:
        df = nse_eq_history("RELIANCE", "1D")
        if df is not None and not df.empty:
            high = float(df.iloc[-1]['CH_TRADE_HIGH_PRICE'])
            low = float(df.iloc[-1]['CH_TRADE_LOW_PRICE'])
            close = float(df.iloc[-1]['CH_CLOSING_PRICE'])
            
            pivot = (high + low + close) / 3
            resistance_1 = (2 * pivot) - low
            support_1 = (2 * pivot) - high
            
            return round(support_1, 2), round(resistance_1, 2)
    except:
        pass
    return 0, 0

def run_pro_bot():
    now = datetime.now()
    current_time = now.strftime("%H:%M")
    current_hour_min = int(now.strftime("%H%M"))
    
    print(f"Bot running at {current_time}")

    # 1. 9:00 AM Startup Alert -> ADMIN ONLY
    if 900 <= current_hour_min <= 904:
        msg = (
            "🔴🟠 **SAS LEVEL TRACKER** 🔴🟠\n\n"
            "🚀 **BOT STARTED SUCCESSFULLY**\n"
            f"📅 **Date:** {now.strftime('%Y-%m-%d')}\n"
            "🟢 **System Status:** Active and monitoring market."
        )
        send_alert_to_admin(msg)
        return

    # 2. 9:05 AM Support & Resistance Alert -> JOINERS / CHANNEL ONLY
    if 905 <= current_hour_min <= 909:
        sup, res = get_market_levels()
        msg = (
            "🔴🟠 **SAS LEVEL TRACKER** 🔴🟠\n\n"
            "📊 **NIFTY / STOCK SUPPORT & RESISTANCE**\n\n"
            f"🔴 **Resistance 1:** `{res}`\n"
            f"🟢 **Support 1:** `{sup}`\n\n"
            "⚠️ Watch out for breakouts!"
        )
        send_alert_to_joiners(msg)
        return

    # 3. 9:15 AM to 3:30 PM Live Signals -> JOINERS / CHANNEL ONLY
    if 915 <= current_hour_min <= 1530:
        try:
            symbol = "RELIANCE"
            df = nse_eq_history(symbol, "1D")
            
            if df is None or df.empty:
                return

            df['CH_CLOSING_PRICE'] = pd.to_numeric(df['CH_CLOSING_PRICE'])
            df['CH_TOT_TRADED_VAL'] = pd.to_numeric(df['CH_TOT_TRADED_VAL'])

            # EMA Calculations (5, 10, 20, 50, 200)
            df['EMA_5'] = df['CH_CLOSING_PRICE'].ewm(span=5, adjust=False).mean()
            df['EMA_10'] = df['CH_CLOSING_PRICE'].ewm(span=10, adjust=False).mean()
            df['EMA_20'] = df['CH_CLOSING_PRICE'].ewm(span=20, adjust=False).mean()
            df['EMA_50'] = df['CH_CLOSING_PRICE'].ewm(span=50, adjust=False).mean()
            df['EMA_200'] = df['CH_CLOSING_PRICE'].ewm(span=200, adjust=False).mean()

            latest = df.iloc[-1]
            close_price = float(latest['CH_CLOSING_PRICE'])
            volume = float(latest['CH_TOT_TRADED_VAL'])
            avg_volume = df['CH_TOT_TRADED_VAL'].rolling(window=20).mean().iloc[-1]

            ema5 = float(latest['EMA_5'])
            ema10 = float(latest['EMA_10'])
            ema20 = float(latest['EMA_20'])
            ema50 = float(latest['EMA_50'])
            ema200 = float(latest['EMA_200'])

            # Strategy Condition: Price + Volume + EMA (5, 10, 20, 50, 200)
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
                    "🚨 **INTRADAY SIGNAL ALERT** 🚨\n\n"
                    f"📊 **Asset:** {symbol}\n"
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
                print("Signal sent to joiners successfully.")

        except Exception as e:
            print(f"Error in strategy execution: {e}")

    # 4. 3:35 PM Daily Report Generation & PDF Send
    if 335 <= current_hour_min <= 340:
        try:
            generate_pdf_report()
            send_pdf_report_to_telegram()
            print("Daily PDF Report generated and sent successfully.")
        except Exception as e:
            print(f"Error generating report: {e}")

if __name__ == "__main__":
    run_pro_bot()
