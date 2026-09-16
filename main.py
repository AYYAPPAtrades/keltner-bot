import pandas as pd
import numpy as np
import time
import requests
import json
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from datetime import datetime
from zoneinfo import ZoneInfo
import yfinance as yf
from nselib import capital_market

from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

# --- TIMEZONE CONFIGURATION ---
IST = ZoneInfo("Asia/Kolkata")

# --- TELEGRAM CONFIGURATION ---
TELEGRAM_BOT_TOKEN = "8941192045:AAEBwZ8O4Q7-K-ktSx7kAewUy4QIXsLWEhs"
TELEGRAM_CHAT_IDS = ["8996427731", "6789591588"]
tele_session = requests.Session()

def send_telegram_alert(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    for chat_id in TELEGRAM_CHAT_IDS:
        try:
            payload = {"chat_id": chat_id, "text": message, "disable_web_page_preview": True}
            tele_session.post(url, json=payload, timeout=4)
        except Exception as e:
            print(f"Telegram Error ({chat_id}): {e}")

def send_telegram_document(file_path, caption=""):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendDocument"
    for chat_id in TELEGRAM_CHAT_IDS:
        try:
            with open(file_path, 'rb') as doc:
                files = {'document': doc}
                data = {'chat_id': chat_id, 'caption': caption}
                requests.post(url, data=data, files=files, timeout=15)
        except Exception as e:
            print(f"Telegram Doc Error ({chat_id}): {e}")

# --- EMAIL DISPATCH (TO SHINOS99@GMAIL.COM) ---
SENDER_EMAIL = "shinosanthagopi@gmail.com"
SENDER_APP_PASSWORD = "nouiwuzkyjbzsgix"
RECEIVER_EMAILS = ["shinos99@gmail.com"]

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
        part.add_header("Content-Disposition", f"attachment; filename= {os.path.basename(file_path)}")
        msg.attach(part)

        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(SENDER_EMAIL, SENDER_APP_PASSWORD)
        server.sendmail(SENDER_EMAIL, RECEIVER_EMAILS, msg.as_string())
        server.quit()
        print("PDF emailed to shinos99@gmail.com successfully.")
    except Exception as e:
        print(f"Email Dispatch Warning: {e}")

# --- 1. WEEKEND CHECK ---
today_weekday = datetime.now(IST).weekday()
if today_weekday in [5, 6]:
    day_name = "Saturday" if today_weekday == 5 else "Sunday"
    send_telegram_alert(
        f"🏖️ WEEKEND MARKET HOLIDAY ({day_name})!\n\n"
        f"• Status: Market is Closed.\n"
        f"• Scanner will remain inactive today.\n"
        f"• Resumes Monday at 09:00 AM IST."
    )
    exit(0)

# --- 2. MARKET HOLIDAY CHECK ---
try:
    holidays_df = capital_market.holiday_trading()
    today_str = datetime.now(IST).strftime('%d-%b-%Y')
    if holidays_df is not None and not holidays_df.empty:
        if 'tradingDate' in holidays_df.columns and today_str in holidays_df['tradingDate'].values:
            reason = holidays_df[holidays_df['tradingDate'] == today_str]['description'].values[0]
            send_telegram_alert(
                f"🏖️ MARKET HOLIDAY TODAY!\n"
                f"Reason: {reason}\n"
                f"Strategy: MOMENTUM SPIKE will not run today."
            )
            print(f"Market Holiday: {reason}. Exiting.")
            exit(0)
except Exception as e:
    print(f"Holiday check skipped: {e}")

INDEX_WATCHLIST = ["NIFTY 50", "NIFTY BANK"]
YF_TICKERS = {"NIFTY 50": "^NSEI", "NIFTY BANK": "^NSEBANK"}
TRADE_FILE = "active_trades_momentum.json"
MONTHLY_LEDGER_FILE = "monthly_trades_ledger.json"
STRATEGY_DISPLAY_NAME = "MOMENTUM SPIKE"

trade_stats = {"total_signals": 0, "target_hits": 0, "sl_hits": 0}
trade_logs = []
levels_sent_today = False
hero_zero_sent = False
last_heartbeat_hour = -1

triggered_levels = {idx: set() for idx in INDEX_WATCHLIST}
last_prices = {}

# --- TRADE PERSISTENCE ---
def load_trades():
    default_structure = {idx: None for idx in INDEX_WATCHLIST}
    if os.path.exists(TRADE_FILE):
        try:
            with open(TRADE_FILE, 'r') as f:
                return json.load(f)
        except Exception:
            pass
    return default_structure

def save_trades(trades):
    try:
        with open(TRADE_FILE, 'w') as f:
            json.dump(trades, f, indent=4)
    except Exception as e:
        print(f"Trade save error: {e}")

def record_to_monthly_ledger(log_entry):
    records = []
    if os.path.exists(MONTHLY_LEDGER_FILE):
        try:
            with open(MONTHLY_LEDGER_FILE, 'r') as f:
                records = json.load(f)
        except Exception:
            records = []
    records.append(log_entry)
    try:
        with open(MONTHLY_LEDGER_FILE, 'w') as f:
            json.dump(records, f, indent=4)
    except Exception as e:
        print(f"Monthly ledger error: {e}")

# --- HISTORICAL DATA & PREVIOUS DAY LEVELS ---
prev_close_dict = {}
previous_day_levels = {}

def get_historical_candles(index_name):
    global prev_close_dict, previous_day_levels
    try:
        ticker = YF_TICKERS.get(index_name)
        df_hist = yf.download(ticker, period="5d", interval="5m", progress=False)
        if not df_hist.empty:
            if isinstance(df_hist.columns, pd.MultiIndex):
                df_hist.columns = df_hist.columns.get_level_values(0)
            candles = []
            for _, row in df_hist.tail(60).iterrows():
                candles.append({
                    'Open': float(row['Open']),
                    'High': float(row['High']),
                    'Low': float(row['Low']),
                    'Close': float(row['Close'])
                })
            
            # Previous Day High, Low, Close Calculation
            df_d = yf.download(ticker, period="3d", interval="1d", progress=False)
            if not df_d.empty:
                if isinstance(df_d.columns, pd.MultiIndex):
                    df_d.columns = df_d.columns.get_level_values(0)
                prev_day = df_d.iloc[-2] if len(df_d) >= 2 else df_d.iloc[-1]
                pdh = float(prev_day['High'])
                pdl = float(prev_day['Low'])
                pdc = float(prev_day['Close'])
                mid_point = (pdh + pdl) / 2.0
                
                prev_close_dict[index_name] = pdc
                previous_day_levels[index_name] = {
                    "PDH": round(pdh, 2),
                    "PDL": round(pdl, 2),
                    "PDC": round(pdc, 2),
                    "MID": round(mid_point, 2)
                }
            return candles
    except Exception as e:
        print(f"History fetch error {index_name}: {e}")
    return []

candle_history = {idx: get_historical_candles(idx) for idx in INDEX_WATCHLIST}
active_trades = load_trades()
current_candles = {idx: {"open": None, "high": -1, "low": 9999999, "close": None, "start_min": None} for idx in INDEX_WATCHLIST}
alert_candles = {idx: {"sell_alert": None, "buy_alert": None} for idx in INDEX_WATCHLIST}

# --- PDF REPORT GENERATOR ---
def generate_pdf_report(filename, title_text, date_str, logs_to_print):
    doc = SimpleDocTemplate(filename, pagesize=letter, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
    styles = getSampleStyleSheet()
    elements = []

    title_style = ParagraphStyle(
        'RepTitle', parent=styles['Heading1'], fontSize=16, leading=20,
        textColor=colors.HexColor("#1A365D"), alignment=1
    )
    elements.append(Paragraph(f"{title_text} ({STRATEGY_DISPLAY_NAME})", title_style))
    elements.append(Paragraph(f"Date: {date_str} | Target: shinos99@gmail.com", styles['Normal']))
    elements.append(Spacer(1, 15))

    tot_sig = len(logs_to_print)
    target_count = sum(1 for l in logs_to_print if 'Target' in l.get('status', ''))
    sl_count = sum(1 for l in logs_to_print if 'SL Hit' in l.get('status', ''))

    sum_data = [
        ["Total Signals", "Targets Hit", "Stop Losses Hit"],
        [str(tot_sig), str(target_count), str(sl_count)]
    ]
    t_sum = Table(sum_data, colWidths=[170, 170, 170])
    t_sum.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#2B6CB0")),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('GRID', (0, 0), (-1, -1), 1, colors.HexColor("#CBD5E0")),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    elements.append(t_sum)
    elements.append(Spacer(1, 15))

    if logs_to_print:
        log_data = [["Time", "Index", "Type", "Entry", "Exit", "PnL", "Status"]]
        for log in logs_to_print:
            log_data.append([
                log.get('time', ''), log['index'], log['type'],
                f"{log['entry']:.2f}", f"{log['exit']:.2f}",
                f"{log['pnl']:+.2f}", log['status']
            ])
        t_log = Table(log_data, colWidths=[70, 85, 50, 75, 75, 75, 120])
        t_log.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#4A5568")),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
        ]))
        elements.append(t_log)
    else:
        elements.append(Paragraph("<i>No trades closed today.</i>", styles['Normal']))

    doc.build(elements)

# --- STARTUP ALERT ---
send_telegram_alert(
    "🚀 MOMENTUM SPIKE\n"
    "SCANNER ACTIVATED & ARMED!\n"
    "• Strategy: 5 EMA Reversal + Previous Day Levels\n"
    "• Window: 09:00 AM - 03:40 PM IST\n"
    "• Support & Resistance: Previous Day High (PDH) & Low (PDL) Active"
)

def get_live_index_data():
    try:
        return capital_market.market_watch_all_indices()
    except Exception as e:
        print(f"NSE Fetch Error: {e}")
        return None

# --- MAIN TRADING LOOP ---
while True:
    try:
        now = datetime.now(IST)
        current_time_str = now.strftime('%H:%M:%S IST')
        start_trade_time = datetime.strptime("09:30", "%H:%M").time()
        hero_zero_time = datetime.strptime("13:15", "%H:%M").time()
        end_trade_time = datetime.strptime("15:20", "%H:%M").time()
        market_shutdown_time = datetime.strptime("15:40", "%H:%M").time()

        can_take_trades = (start_trade_time <= now.time() < end_trade_time)
        is_market_closing = (now.time() >= end_trade_time)

        # 1. 09:05 AM PREVIOUS DAY KEY LEVELS ALERT
        if not levels_sent_today and now.hour == 9 and now.minute >= 5:
            levels_msg = "📊 DAILY KEY LEVELS (PREVIOUS DAY RANGE - 09:05 AM)\n⚡ Strategy: MOMENTUM SPIKE\n"
            for idx in INDEX_WATCHLIST:
                lvl = previous_day_levels.get(idx)
                if lvl:
                    levels_msg += (
                        f"\n🔹 {idx}:\n"
                        f"  🔺 PDH (Resistance): {lvl['PDH']:.2f}\n"
                        f"  ⚖️ 50% Mid Range: {lvl['MID']:.2f}\n"
                        f"  🔻 PDL (Support): {lvl['PDL']:.2f}\n"
                        f"  🔹 Prev Close: {lvl['PDC']:.2f}\n"
                    )
            send_telegram_alert(levels_msg)
            levels_sent_today = True

        # 2. 03:40 PM DAILY REPORT + PDF EMAIL TO SHINOS99@GMAIL.COM
        if now.time() >= market_shutdown_time:
            date_str = now.strftime('%d-%b-%Y')
            summary = (
                f"📋 DAILY PERFORMANCE REPORT\n"
                f"⚡ Strategy: MOMENTUM SPIKE\n"
                f"📅 Date: {date_str}\n"
                f"• Total Signals: {trade_stats['total_signals']}\n"
                f"• Targets Hit: {trade_stats['target_hits']}\n"
                f"• Stop Loss Hit: {trade_stats['sl_hits']}\n\n"
                f"Bot safely completed today's session."
            )
            send_telegram_alert(summary)

            pdf_name = f"Daily_Report_{date_str}.pdf"
            generate_pdf_report(pdf_name, "DAILY PERFORMANCE REPORT", date_str, trade_logs)
            send_telegram_document(pdf_name, caption=f"📄 Performance Report - {date_str}")
            send_email_with_pdf(pdf_name, f"Trading Report - {date_str}", summary)
            break

        raw_data = get_live_index_data()

        if raw_data is not None and not raw_data.empty:
            prices_dict = {}
            for index_name in INDEX_WATCHLIST:
                row = raw_data[raw_data['index'] == index_name]
                if not row.empty:
                    current_price = float(str(row['last'].values[0]).replace(',', ''))
                    prices_dict[index_name] = current_price
                    trade = active_trades[index_name]

                    # --- LIVE PREVIOUS DAY LEVELS CROSS ALERTS ---
                    lvl = previous_day_levels.get(index_name)
                    if lvl and now.time() >= start_trade_time:
                        old_p = last_prices.get(index_name, current_price)

                        # PDH Breakout (Resistance Breakout)
                        if old_p <= lvl['PDH'] < current_price and "PDH_UP" not in triggered_levels[index_name]:
                            triggered_levels[index_name].add("PDH_UP")
                            send_telegram_alert(
                                f"🔺 {index_name} PREVIOUS DAY HIGH BREAKOUT!\n\n"
                                f"• Level: PDH ({lvl['PDH']:.2f})\n"
                                f"• Current Price: {current_price:.2f}\n"
                                f"⏰ Time: {current_time_str}\n"
                                f"⚡ Market sentiment is strongly Bullish!"
                            )

                        # PDL Breakdown (Support Breakdown)
                        elif old_p >= lvl['PDL'] > current_price and "PDL_DOWN" not in triggered_levels[index_name]:
                            triggered_levels[index_name].add("PDL_DOWN")
                            send_telegram_alert(
                                f"🔻 {index_name} PREVIOUS DAY LOW BREAKDOWN!\n\n"
                                f"• Level: PDL ({lvl['PDL']:.2f})\n"
                                f"• Current Price: {current_price:.2f}\n"
                                f"⏰ Time: {current_time_str}\n"
                                f"⚡ Market sentiment is strongly Bearish!"
                            )

                    last_prices[index_name] = current_price

                    # 3. HERO-ZERO SETUP ALERT (01:15 PM on Tue/Thu)
                    if not hero_zero_sent and now.time() >= hero_zero_time and today_weekday in [1, 3]:
                        step = 50 if index_name == "NIFTY 50" else 100
                        atm_k = int(round(current_price / step) * step)
                        send_telegram_alert(
                            f"🔥 HERO-ZERO EXPIRY SETUP (01:15 PM IST)\n\n"
                            f"📍 Index: {index_name} (Spot: {current_price:.2f})\n"
                            f"🎯 Focus Strikes:\n"
                            f"• Call Option: {atm_k + step} CE\n"
                            f"• Put Option: {atm_k - step} PE\n\n"
                            f"⚡ Strategy: Target low premium breakout!"
                        )
                        hero_zero_sent = True

                    # 4. POSITION TRACKING & EXITS
                    if trade is not None:
                        # 03:20 PM Auto Exit
                        if is_market_closing:
                            pnl = current_price - trade['entry'] if trade['type'] == 'BUY' else trade['entry'] - current_price
                            entry_log = {
                                'time': current_time_str, 'index': index_name, 'type': trade['type'],
                                'entry': trade['entry'], 'exit': current_price, 'pnl': pnl, 'status': 'Auto-Exit 03:20'
                            }
                            trade_logs.append(entry_log)
                            record_to_monthly_ledger(entry_log)

                            send_telegram_alert(
                                f"⏰ AUTO EXIT (03:20 PM)\n"
                                f"⚡ Strategy: MOMENTUM SPIKE\n"
                                f"Index: {index_name}\n"
                                f"💵 Exit Price: {current_price:.2f}\n"
                                f"📈 Points: {pnl:+.2f}"
                            )
                            active_trades[index_name] = None
                            save_trades(active_trades)
                            continue

                        # BUY ORDERS
                        if trade['type'] == 'BUY':
                            if not trade.get('t1_hit') and current_price >= trade['t1']:
                                trade['t1_hit'] = True
                                trade['sl'] = trade['entry']  # Trail to entry
                                trade_stats['target_hits'] += 1
                                send_telegram_alert(
                                    f"🎯 TARGET 1 HIT!\n"
                                    f"⚡ Strategy: MOMENTUM SPIKE\n"
                                    f"Index: {index_name} (CALL)\n"
                                    f"💵 Target Price: {trade['t1']:.2f}\n"
                                    f"Current: {current_price:.2f}\n"
                                    f"🛡️ Trailing SL: Moved to Entry ({trade['entry']:.2f})!"
                                )
                                save_trades(active_trades)

                            if not trade.get('t2_hit') and current_price >= trade['t2']:
                                trade['t2_hit'] = True
                                trade['sl'] = trade['t1']  # Trail to T1
                                trade_stats['target_hits'] += 1
                                send_telegram_alert(
                                    f"🎯 TARGET 2 HIT!\n"
                                    f"⚡ Strategy: MOMENTUM SPIKE\n"
                                    f"Index: {index_name} (CALL)\n"
                                    f"💵 Target Price: {trade['t2']:.2f}\n"
                                    f"Current: {current_price:.2f}\n"
                                    f"🛡️ Trailing SL: Moved to T1 ({trade['t1']:.2f})!"
                                )
                                save_trades(active_trades)

                            if current_price >= trade['t3']:
                                trade_stats['target_hits'] += 1
                                pnl = current_price - trade['entry']
                                entry_log = {
                                    'time': current_time_str, 'index': index_name, 'type': 'BUY',
                                    'entry': trade['entry'], 'exit': current_price, 'pnl': pnl, 'status': 'Target 3 Hit'
                                }
                                trade_logs.append(entry_log)
                                record_to_monthly_ledger(entry_log)

                                send_telegram_alert(
                                    f"🏆 TARGET 3 ACHIEVED!\n"
                                    f"⚡ Strategy: MOMENTUM SPIKE\n"
                                    f"Index: {index_name} (CALL)\n"
                                    f"💵 Final Target: {trade['t3']:.2f}\n"
                                    f"Trade Completed."
                                )
                                active_trades[index_name] = None
                                save_trades(active_trades)

                            elif current_price <= trade['sl']:
                                trade_stats['sl_hits'] += 1
                                pnl = current_price - trade['entry']
                                entry_log = {
                                    'time': current_time_str, 'index': index_name, 'type': 'BUY',
                                    'entry': trade['entry'], 'exit': current_price, 'pnl': pnl, 'status': 'SL Hit'
                                }
                                trade_logs.append(entry_log)
                                record_to_monthly_ledger(entry_log)

                                active_trades[index_name] = None
                                save_trades(active_trades)
                                if not trade.get('t1_hit', False):
                                    send_telegram_alert(
                                        f"🛑 STOP LOSS HIT!\n"
                                        f"⚡ Strategy: MOMENTUM SPIKE\n"
                                        f"Index: {index_name} (CALL)\n"
                                        f"🛑 SL Price: {trade['sl']:.2f}"
                                    )

                        # SELL ORDERS
                        elif trade['type'] == 'SELL':
                            if not trade.get('t1_hit') and current_price <= trade['t1']:
                                trade['t1_hit'] = True
                                trade['sl'] = trade['entry']  # Trail to entry
                                trade_stats['target_hits'] += 1
                                send_telegram_alert(
                                    f"🎯 TARGET 1 HIT!\n"
                                    f"⚡ Strategy: MOMENTUM SPIKE\n"
                                    f"Index: {index_name} (PUT)\n"
                                    f"💵 Target Price: {trade['t1']:.2f}\n"
                                    f"Current: {current_price:.2f}\n"
                                    f"🛡️ Trailing SL: Moved to Entry ({trade['entry']:.2f})!"
                                )
                                save_trades(active_trades)

                            if not trade.get('t2_hit') and current_price <= trade['t2']:
                                trade['t2_hit'] = True
                                trade['sl'] = trade['t1']  # Trail to T1
                                trade_stats['target_hits'] += 1
                                send_telegram_alert(
                                    f"🎯 TARGET 2 HIT!\n"
                                    f"⚡ Strategy: MOMENTUM SPIKE\n"
                                    f"Index: {index_name} (PUT)\n"
                                    f"💵 Target Price: {trade['t2']:.2f}\n"
                                    f"Current: {current_price:.2f}\n"
                                    f"🛡️ Trailing SL: Moved to T1 ({trade['t1']:.2f})!"
                                )
                                save_trades(active_trades)

                            if current_price <= trade['t3']:
                                trade_stats['target_hits'] += 1
                                pnl = trade['entry'] - current_price
                                entry_log = {
                                    'time': current_time_str, 'index': index_name, 'type': 'SELL',
                                    'entry': trade['entry'], 'exit': current_price, 'pnl': pnl, 'status': 'Target 3 Hit'
                                }
                                trade_logs.append(entry_log)
                                record_to_monthly_ledger(entry_log)

                                send_telegram_alert(
                                    f"🏆 TARGET 3 ACHIEVED!\n"
                                    f"⚡ Strategy: MOMENTUM SPIKE\n"
                                    f"Index: {index_name} (PUT)\n"
                                    f"💵 Final Target: {trade['t3']:.2f}\n"
                                    f"Trade Completed."
                                )
                                active_trades[index_name] = None
                                save_trades(active_trades)

                            elif current_price >= trade['sl']:
                                trade_stats['sl_hits'] += 1
                                pnl = trade['entry'] - current_price
                                entry_log = {
                                    'time': current_time_str, 'index': index_name, 'type': 'SELL',
                                    'entry': trade['entry'], 'exit': current_price, 'pnl': pnl, 'status': 'SL Hit'
                                }
                                trade_logs.append(entry_log)
                                record_to_monthly_ledger(entry_log)

                                active_trades[index_name] = None
                                save_trades(active_trades)
                                if not trade.get('t1_hit', False):
                                    send_telegram_alert(
                                        f"🛑 STOP LOSS HIT!\n"
                                        f"⚡ Strategy: MOMENTUM SPIKE\n"
                                        f"Index: {index_name} (PUT)\n"
                                        f"🛑 SL Price: {trade['sl']:.2f}"
                                    )

                    # 5. CANDLE AGGREGATION & 5 EMA SETUP
                    c_bucket = current_candles[index_name]
                    current_min_slot = (now.minute // 5) * 5

                    if c_bucket["start_min"] is None or c_bucket["start_min"] != current_min_slot:
                        if c_bucket["start_min"] is not None and c_bucket["open"] is not None:
                            candle_history[index_name].append({
                                'Open': c_bucket["open"], 'High': c_bucket["high"],
                                'Low': c_bucket["low"], 'Close': c_bucket["close"]
                            })
                            if len(candle_history[index_name]) > 60:
                                candle_history[index_name].pop(0)

                            df = pd.DataFrame(candle_history[index_name])
                            df['EMA5'] = df['Close'].ewm(span=5, adjust=False).mean()
                            last_c = df.iloc[-1]

                            # Sell Alert: Candle totally above 5 EMA
                            if last_c['Low'] > last_c['EMA5']:
                                alert_candles[index_name]["sell_alert"] = {'high': last_c['High'], 'low': last_c['Low']}
                            else:
                                alert_candles[index_name]["sell_alert"] = None

                            # Buy Alert: Candle totally below 5 EMA
                            if last_c['High'] < last_c['EMA5']:
                                alert_candles[index_name]["buy_alert"] = {'high': last_c['High'], 'low': last_c['Low']}
                            else:
                                alert_candles[index_name]["buy_alert"] = None

                        c_bucket["open"] = current_price
                        c_bucket["high"] = current_price
                        c_bucket["low"] = current_price
                        c_bucket["close"] = current_price
                        c_bucket["start_min"] = current_min_slot
                    else:
                        c_bucket["high"] = max(c_bucket["high"], current_price)
                        c_bucket["low"] = min(c_bucket["low"], current_price)
                        c_bucket["close"] = current_price

                    # 6. INSTANT 5 EMA BREAKOUT SIGNALS
                    if can_take_trades and active_trades[index_name] is None:
                        # SELL BREAKOUT
                        s_alert = alert_candles[index_name]["sell_alert"]
                        if s_alert and current_price < s_alert['low']:
                            risk = round(s_alert['high'] - s_alert['low'], 2)
                            if risk >= 8.0:
                                trade_stats['total_signals'] += 1
                                sl = round(s_alert['high'], 2)
                                t1 = round(current_price - (risk * 1.5), 2)
                                t2 = round(current_price - (risk * 2.0), 2)
                                t3 = round(current_price - (risk * 3.0), 2)
                                active_trades[index_name] = {
                                    'type': 'SELL', 'entry': current_price, 'sl': sl, 
                                    't1': t1, 't2': t2, 't3': t3, 't1_hit': False, 't2_hit': False
                                }
                                save_trades(active_trades)
                                alert_candles[index_name]["sell_alert"] = None
                                
                                send_telegram_alert(
                                    f"🔴 {index_name} SELL SIGNAL\n\n"
                                    f"⚡ Strategy: MOMENTUM SPIKE\n"
                                    f"⏰ Time: {current_time_str}\n"
                                    f"💵 Entry: {current_price:.2f}\n"
                                    f"🛑 Stop Loss: {sl:.2f}\n\n"
                                    f"🎯 Target 1: {t1:.2f}\n"
                                    f"🎯 Target 2: {t2:.2f}\n"
                                    f"🎯 Target 3: {t3:.2f}"
                                )

                        # BUY BREAKOUT
                        b_alert = alert_candles[index_name]["buy_alert"]
                        if b_alert and current_price > b_alert['high']:
                            risk = round(b_alert['high'] - b_alert['low'], 2)
                            if risk >= 8.0:
                                trade_stats['total_signals'] += 1
                                sl = round(b_alert['low'], 2)
                                t1 = round(current_price + (risk * 1.5), 2)
                                t2 = round(current_price + (risk * 2.0), 2)
                                t3 = round(current_price + (risk * 3.0), 2)
                                active_trades[index_name] = {
                                    'type': 'BUY', 'entry': current_price, 'sl': sl, 
                                    't1': t1, 't2': t2, 't3': t3, 't1_hit': False, 't2_hit': False
                                }
                                save_trades(active_trades)
                                alert_candles[index_name]["buy_alert"] = None
                                
                                send_telegram_alert(
                                    f"🟢 {index_name} BUY SIGNAL\n\n"
                                    f"⚡ Strategy: MOMENTUM SPIKE\n"
                                    f"⏰ Time: {current_time_str}\n"
                                    f"💵 Entry: {current_price:.2f}\n"
                                    f"🛑 Stop Loss: {sl:.2f}\n\n"
                                    f"🎯 Target 1: {t1:.2f}\n"
                                    f"🎯 Target 2: {t2:.2f}\n"
                                    f"🎯 Target 3: {t3:.2f}"
                                )

            # 7. HOURLY STATUS ALERT
            if now.minute == 0 and now.hour != last_heartbeat_hour and (9 <= now.hour <= 15):
                last_heartbeat_hour = now.hour
                hb_msg = f"💓 HOURLY STATUS ALERT\n⏰ Time: {current_time_str}\n\n"
                for idx, prc in prices_dict.items():
                    prev_c = prev_close_dict.get(idx, prc)
                    diff = prc - prev_c
                    pct = (diff / prev_c) * 100 if prev_c else 0
                    sign = "+" if diff >= 0 else ""
                    hb_msg += f"• {idx}: {prc:.2f} ({sign}{diff:.2f} | {sign}{pct:.2f}%)\n"
                send_telegram_alert(hb_msg)

        time.sleep(3)
    except Exception as e:
        print(f"Loop Exception: {e}")
        time.sleep(3)
