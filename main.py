import os
import time
import json
import smtplib
from datetime import datetime
from zoneinfo import ZoneInfo
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

import pandas as pd
import numpy as np
import requests
import yfinance as yf
from nselib import capital_market

from reportlab.lib.pagesizes import letter, landscape
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
            tele_session.post(url, json=payload, timeout=6)
        except Exception as e:
            print(f"Telegram Alert Error ({chat_id}): {e}")

def send_telegram_document(file_path, caption=""):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendDocument"
    for chat_id in TELEGRAM_CHAT_IDS:
        try:
            with open(file_path, 'rb') as doc:
                files = {'document': doc}
                data = {'chat_id': chat_id, 'caption': caption}
                requests.post(url, data=data, files=files, timeout=20)
        except Exception as e:
            print(f"Telegram Document Error ({chat_id}): {e}")

# --- EMAIL DISPATCH ---
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
        part.add_header("Content-Disposition", f"attachment; filename={os.path.basename(file_path)}")
        msg.attach(part)

        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(SENDER_EMAIL, SENDER_APP_PASSWORD)
        server.sendmail(SENDER_EMAIL, RECEIVER_EMAILS, msg.as_string())
        server.quit()
        print("PDF Emailed Successfully.")
    except Exception as e:
        print(f"Email Dispatch Warning: {e}")

# --- WEEKEND & HOLIDAY CHECKS ---
today_weekday = datetime.now(IST).weekday()
if today_weekday in [5, 6]:
    day_name = "Saturday" if today_weekday == 5 else "Sunday"
    send_telegram_alert(
        f"🏖️ WEEKEND MARKET HOLIDAY ({day_name})\n\n"
        "• Market is closed today.\n"
        "• Scanner resumes Monday at 09:00 AM IST."
    )
    exit(0)

try:
    holidays_df = capital_market.holiday_trading()
    today_str = datetime.now(IST).strftime('%d-%b-%Y')
    if holidays_df is not None and not holidays_df.empty:
        if 'tradingDate' in holidays_df.columns and today_str in holidays_df['tradingDate'].values:
            reason = holidays_df[holidays_df['tradingDate'] == today_str]['description'].values[0]
            send_telegram_alert(f"🏖️ MARKET HOLIDAY TODAY!\nReason: {reason}")
            exit(0)
except Exception as e:
    print(f"Holiday API skipped: {e}")

INDEX_WATCHLIST = ["NIFTY 50", "NIFTY BANK"]
YF_TICKERS = {"NIFTY 50": "^NSEI", "NIFTY BANK": "^NSEBANK"}
TRADE_FILE = "active_trades_momentum.json"
MONTHLY_LEDGER_FILE = "monthly_trades_ledger.json"
STRATEGY_DISPLAY_NAME = "MOMENTUM SPIKE"

levels_sent_today = False
hero_zero_sent = False
last_heartbeat_hour = -1

# --- JSON PERSISTENCE SYSTEM ---
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

def load_monthly_ledger():
    if os.path.exists(MONTHLY_LEDGER_FILE):
        try:
            with open(MONTHLY_LEDGER_FILE, 'r') as f:
                return json.load(f)
        except Exception:
            return []
    return []

def record_to_monthly_ledger(trade):
    records = load_monthly_ledger()
    records.append(trade)
    try:
        with open(MONTHLY_LEDGER_FILE, 'w') as f:
            json.dump(records, f, indent=4)
    except Exception as e:
        print(f"Monthly ledger save error: {e}")

# --- PREVIOUS DAY LEVELS CALCULATION ---
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
        print(f"Historical Candles Fetch Error ({index_name}): {e}")
    return []

candle_history = {idx: get_historical_candles(idx) for idx in INDEX_WATCHLIST}
active_trades = load_trades()
current_candles = {idx: {"open": None, "high": -1, "low": 9999999, "close": None, "start_min": None} for idx in INDEX_WATCHLIST}
alert_candles = {idx: {"sell_alert": None, "buy_alert": None} for idx in INDEX_WATCHLIST}

# --- PDF GENERATOR (WITH DATE COLUMN) ---
def generate_detailed_pdf_report(filename, title_text, subtitle_text, logs_to_print):
    doc = SimpleDocTemplate(filename, pagesize=landscape(letter), rightMargin=15, leftMargin=15, topMargin=20, bottomMargin=20)
    styles = getSampleStyleSheet()
    elements = []

    title_style = ParagraphStyle(
        'RepTitle', parent=styles['Heading1'], fontSize=14, leading=17,
        textColor=colors.HexColor("#1A365D"), alignment=1
    )
    elements.append(Paragraph(f"{title_text} - {STRATEGY_DISPLAY_NAME}", title_style))
    elements.append(Paragraph(f"Timeline: {subtitle_text} | Total Trades: {len(logs_to_print)}", styles['Normal']))
    elements.append(Spacer(1, 10))

    headers = [
        "SL\nNO", "Date", "Index & Type", "Entry Price\n& Time",
        "Target 1\n& Time", "Target 2\n& Time", "Target 3\n& Time",
        "Stop Loss\n& Time", "P / L\nPoints", "Final Status"
    ]

    table_rows = [headers]
    for idx, log in enumerate(logs_to_print, start=1):
        t1_val = f"{log.get('t1', '-')}\n({log.get('t1_time', '-')})" if log.get('t1_hit') else "-"
        t2_val = f"{log.get('t2', '-')}\n({log.get('t2_time', '-')})" if log.get('t2_hit') else "-"
        t3_val = f"{log.get('t3', '-')}\n({log.get('t3_time', '-')})" if log.get('t3_hit') else "-"
        sl_val = f"{log.get('sl', '-')}\n({log.get('sl_time', '-')})" if log.get('sl_hit') else f"{log.get('sl', '-')}"

        pnl_val = f"{log.get('pnl', 0.0):+.2f}"

        table_rows.append([
            str(idx),
            log.get('date', '-'),
            f"{log.get('index', '')}\n({log.get('type', '')})",
            f"{log.get('entry', 0.0):.2f}\n{log.get('entry_time', '')}",
            t1_val,
            t2_val,
            t3_val,
            sl_val,
            pnl_val,
            log.get('status', '-')
        ])

    col_widths = [25, 65, 80, 80, 80, 80, 80, 80, 65, 110]
    trade_table = Table(table_rows, colWidths=col_widths)
    trade_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#2B6CB0")),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E0")),
        ('FONTSIZE', (0, 0), (-1, -1), 7.5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
    ]))
    elements.append(trade_table)
    doc.build(elements)

def format_telegram_trade_card(trade):
    t1_txt = f"{trade.get('t1', '-')} [{trade.get('t1_time', '-')}] ✅" if trade.get('t1_hit') else "-"
    t2_txt = f"{trade.get('t2', '-')} [{trade.get('t2_time', '-')}] ✅" if trade.get('t2_hit') else "-"
    t3_txt = f"{trade.get('t3', '-')} [{trade.get('t3_time', '-')}] ✅" if trade.get('t3_hit') else "-"
    sl_txt = f"{trade.get('sl', '-')} [{trade.get('sl_time', '-')}] ❌" if trade.get('sl_hit') else f"{trade.get('sl', '-')}"

    pnl = trade.get('pnl', 0.0)
    pnl_str = f"+{pnl:.2f} Pts" if pnl >= 0 else f"{pnl:.2f} Pts"

    return (
        "📊 TRADE PERFORMANCE SUMMARY\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"📅 Date: {trade.get('date', '-')}\n"
        f"🔹 Index: {trade['index']} ({trade['type']})\n"
        f"⚡ Strategy: {STRATEGY_DISPLAY_NAME}\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"▫️ Entry Price : {trade['entry']:.2f} [{trade.get('entry_time', '-')}]\n"
        f"🎯 Target 1    : {t1_txt}\n"
        f"🎯 Target 2    : {t2_txt}\n"
        f"🎯 Target 3    : {t3_txt}\n"
        f"🛑 Stop Loss   : {sl_txt}\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"📈 P/L Points  : {pnl_str}\n"
        f"🏁 Final Status: {trade.get('status', 'Completed')}\n"
        "━━━━━━━━━━━━━━━━━━━━━"
    )

# --- STARTUP ALERT ---
send_telegram_alert(
    "🚀 MOMENTUM SPIKE SCANNER ONLINE\n\n"
    "• Strategy: 5 EMA + Previous Day Levels\n"
    "• Tracking: Entry, Targets (T1-T3), SL with Timestamps & Date\n"
    "• Persistence: Ledger active and preserved across restarts"
)

def get_live_index_data():
    try:
        return capital_market.market_watch_all_indices()
    except Exception as e:
        print(f"NSE Fetch Error: {e}")
        return None

# --- MAIN LOOP ---
while True:
    try:
        now = datetime.now(IST)
        current_time_str = now.strftime('%I:%M %p')
        today_date_str = now.strftime('%d-%b-%Y')

        start_trade_time = datetime.strptime("09:30", "%H:%M").time()
        hero_zero_time = datetime.strptime("13:15", "%H:%M").time()
        end_trade_time = datetime.strptime("15:20", "%H:%M").time()
        market_shutdown_time = datetime.strptime("15:40", "%H:%M").time()

        can_take_trades = (start_trade_time <= now.time() < end_trade_time)
        is_market_closing = (now.time() >= end_trade_time)

        # 09:05 AM PREVIOUS DAY KEY LEVELS ALERT
        if not levels_sent_today and now.hour == 9 and now.minute >= 5:
            levels_msg = f"📊 DAILY KEY LEVELS (PREVIOUS DAY RANGE - 09:05 AM)\n📅 Date: {today_date_str}\n"
            for idx in INDEX_WATCHLIST:
                lvl = previous_day_levels.get(idx)
                if lvl:
                    levels_msg += (
                        f"\n🔹 {idx}:\n"
                        f"  🔺 PDH: {lvl['PDH']:.2f}\n"
                        f"  ⚖️ Mid: {lvl['MID']:.2f}\n"
                        f"  🔻 PDL: {lvl['PDL']:.2f}\n"
                    )
            send_telegram_alert(levels_msg)
            levels_sent_today = True

        # 03:40 PM DAILY & MONTHLY PDF DISPATCH
        if now.time() >= market_shutdown_time:
            monthly_data = load_monthly_ledger()
            today_logs = [l for l in monthly_data if l.get('date') == today_date_str]

            summary_text = (
                f"📋 DAILY PERFORMANCE SUMMARY\n\n"
                f"📅 Date: {today_date_str}\n"
                f"• Today's Signals Closed: {len(today_logs)}\n"
                f"• Cumulative Monthly Trades Logged: {len(monthly_data)}\n\n"
                "Attaching Daily & Expiry-to-date Cumulative PDF reports."
            )
            send_telegram_alert(summary_text)

            # 1. Daily PDF
            daily_pdf = f"Daily_Report_{today_date_str}.pdf"
            generate_detailed_pdf_report(daily_pdf, "DAILY TRADE PERFORMANCE", today_date_str, today_logs)
            send_telegram_document(daily_pdf, caption=f"📄 Daily Detailed Report ({today_date_str})")
            send_email_with_pdf(daily_pdf, f"Daily Trading Report - {today_date_str}", summary_text)

            # 2. Cumulative Monthly PDF (Expiry Data Safe)
            monthly_pdf = f"Monthly_Cumulative_Ledger_{now.strftime('%b_%Y')}.pdf"
            generate_detailed_pdf_report(monthly_pdf, "MONTHLY EXPIRY CUMULATIVE REPORT", now.strftime('%B %Y'), monthly_data)
            send_telegram_document(monthly_pdf, caption=f"📚 Monthly Cumulative Ledger ({now.strftime('%B %Y')})")
            send_email_with_pdf(monthly_pdf, f"Monthly Cumulative Ledger - {now.strftime('%b %Y')}", summary_text)
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

                    # POSITION TRACKING
                    if trade is not None:
                        # Auto Exit at 03:20 PM
                        if is_market_closing:
                            pnl = current_price - trade['entry'] if trade['type'] == 'BUY' else trade['entry'] - current_price
                            trade['exit_price'] = current_price
                            trade['exit_time'] = current_time_str
                            trade['pnl'] = pnl
                            trade['status'] = 'Auto-Exit (03:20 PM)'
                            record_to_monthly_ledger(trade)

                            send_telegram_alert(format_telegram_trade_card(trade))
                            active_trades[index_name] = None
                            save_trades(active_trades)
                            continue

                        # BUY TRADES
                        if trade['type'] == 'BUY':
                            if not trade.get('t1_hit') and current_price >= trade['t1']:
                                trade['t1_hit'] = True
                                trade['t1_time'] = current_time_str
                                trade['sl'] = trade['entry']
                                save_trades(active_trades)
                                send_telegram_alert(
                                    f"🎯 TARGET 1 HIT!\n"
                                    f"📅 Date: {today_date_str}\n"
                                    f"Index: {index_name} (CALL)\n"
                                    f"T1: {trade['t1']:.2f} | Time: {current_time_str}\n"
                                    f"🛡️ SL Moved to Entry ({trade['entry']:.2f})"
                                )

                            if trade.get('t1_hit') and not trade.get('t2_hit') and current_price >= trade['t2']:
                                trade['t2_hit'] = True
                                trade['t2_time'] = current_time_str
                                trade['sl'] = trade['t1']
                                save_trades(active_trades)
                                send_telegram_alert(
                                    f"🎯 TARGET 2 HIT!\n"
                                    f"📅 Date: {today_date_str}\n"
                                    f"Index: {index_name} (CALL)\n"
                                    f"T2: {trade['t2']:.2f} | Time: {current_time_str}"
                                )

                            if trade.get('t2_hit') and current_price >= trade['t3']:
                                trade['t3_hit'] = True
                                trade['t3_time'] = current_time_str
                                trade['exit_price'] = current_price
                                trade['exit_time'] = current_time_str
                                trade['pnl'] = current_price - trade['entry']
                                trade['status'] = 'Target 3 Achieved'
                                record_to_monthly_ledger(trade)

                                send_telegram_alert(format_telegram_trade_card(trade))
                                active_trades[index_name] = None
                                save_trades(active_trades)
                                continue

                            elif current_price <= trade['sl']:
                                trade['sl_hit'] = True
                                trade['sl_time'] = current_time_str
                                trade['exit_price'] = current_price
                                trade['exit_time'] = current_time_str
                                trade['pnl'] = current_price - trade['entry']
                                trade['status'] = 'Target 1 & Exit' if trade.get('t1_hit') else 'SL Hit'
                                record_to_monthly_ledger(trade)

                                if not trade.get('t1_hit'):
                                    send_telegram_alert(format_telegram_trade_card(trade))

                                active_trades[index_name] = None
                                save_trades(active_trades)
                                continue

                        # SELL TRADES
                        elif trade['type'] == 'SELL':
                            if not trade.get('t1_hit') and current_price <= trade['t1']:
                                trade['t1_hit'] = True
                                trade['t1_time'] = current_time_str
                                trade['sl'] = trade['entry']
                                save_trades(active_trades)
                                send_telegram_alert(
                                    f"🎯 TARGET 1 HIT!\n"
                                    f"📅 Date: {today_date_str}\n"
                                    f"Index: {index_name} (PUT)\n"
                                    f"T1: {trade['t1']:.2f} | Time: {current_time_str}\n"
                                    f"🛡️ SL Moved to Entry ({trade['entry']:.2f})"
                                )

                            if trade.get('t1_hit') and not trade.get('t2_hit') and current_price <= trade['t2']:
                                trade['t2_hit'] = True
                                trade['t2_time'] = current_time_str
                                trade['sl'] = trade['t1']
                                save_trades(active_trades)
                                send_telegram_alert(
                                    f"🎯 TARGET 2 HIT!\n"
                                    f"📅 Date: {today_date_str}\n"
                                    f"Index: {index_name} (PUT)\n"
                                    f"T2: {trade['t2']:.2f} | Time: {current_time_str}"
                                )

                            if trade.get('t2_hit') and current_price <= trade['t3']:
                                trade['t3_hit'] = True
                                trade['t3_time'] = current_time_str
                                trade['exit_price'] = current_price
                                trade['exit_time'] = current_time_str
                                trade['pnl'] = trade['entry'] - current_price
                                trade['status'] = 'Target 3 Achieved'
                                record_to_monthly_ledger(trade)

                                send_telegram_alert(format_telegram_trade_card(trade))
                                active_trades[index_name] = None
                                save_trades(active_trades)
                                continue

                            elif current_price >= trade['sl']:
                                trade['sl_hit'] = True
                                trade['sl_time'] = current_time_str
                                trade['exit_price'] = current_price
                                trade['exit_time'] = current_time_str
                                trade['pnl'] = trade['entry'] - current_price
                                trade['status'] = 'Target 1 & Exit' if trade.get('t1_hit') else 'SL Hit'
                                record_to_monthly_ledger(trade)

                                if not trade.get('t1_hit'):
                                    send_telegram_alert(format_telegram_trade_card(trade))

                                active_trades[index_name] = None
                                save_trades(active_trades)
                                continue

                    # 5 EMA LOGIC & CANDLES
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

                            if last_c['Low'] > last_c['EMA5']:
                                alert_candles[index_name]["sell_alert"] = {'high': last_c['High'], 'low': last_c['Low']}
                            else:
                                alert_candles[index_name]["sell_alert"] = None

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

                    # SIGNALS TRIGGER
                    if can_take_trades and active_trades[index_name] is None:
                        s_alert = alert_candles[index_name]["sell_alert"]
                        if s_alert and current_price < s_alert['low']:
                            risk = round(s_alert['high'] - s_alert['low'], 2)
                            if risk >= 8.0:
                                sl = round(s_alert['high'], 2)
                                t1 = round(current_price - (risk * 1.5), 2)
                                t2 = round(current_price - (risk * 2.0), 2)
                                t3 = round(current_price - (risk * 3.0), 2)

                                active_trades[index_name] = {
                                    'date': today_date_str,
                                    'index': index_name,
                                    'type': 'SELL',
                                    'entry': current_price,
                                    'entry_time': current_time_str,
                                    'sl': sl,
                                    'sl_hit': False,
                                    'sl_time': None,
                                    't1': t1,
                                    't1_hit': False,
                                    't1_time': None,
                                    't2': t2,
                                    't2_hit': False,
                                    't2_time': None,
                                    't3': t3,
                                    't3_hit': False,
                                    't3_time': None
                                }
                                save_trades(active_trades)
                                alert_candles[index_name]["sell_alert"] = None

                                send_telegram_alert(
                                    f"🔴 {index_name} SELL SIGNAL\n\n"
                                    f"📅 Date: {today_date_str}\n"
                                    f"⚡ Strategy: {STRATEGY_DISPLAY_NAME}\n"
                                    f"⏰ Time: {current_time_str}\n"
                                    f"💵 Entry: {current_price:.2f}\n"
                                    f"🛑 Stop Loss: {sl:.2f}\n\n"
                                    f"🎯 Target 1: {t1:.2f}\n"
                                    f"🎯 Target 2: {t2:.2f}\n"
                                    f"🎯 Target 3: {t3:.2f}"
                                )

                        b_alert = alert_candles[index_name]["buy_alert"]
                        if b_alert and current_price > b_alert['high']:
                            risk = round(b_alert['high'] - b_alert['low'], 2)
                            if risk >= 8.0:
                                sl = round(b_alert['low'], 2)
                                t1 = round(current_price + (risk * 1.5), 2)
                                t2 = round(current_price + (risk * 2.0), 2)
                                t3 = round(current_price + (risk * 3.0), 2)

                                active_trades[index_name] = {
                                    'date': today_date_str,
                                    'index': index_name,
                                    'type': 'BUY',
                                    'entry': current_price,
                                    'entry_time': current_time_str,
                                    'sl': sl,
                                    'sl_hit': False,
                                    'sl_time': None,
                                    't1': t1,
                                    't1_hit': False,
                                    't1_time': None,
                                    't2': t2,
                                    't2_hit': False,
                                    't2_time': None,
                                    't3': t3,
                                    't3_hit': False,
                                    't3_time': None
                                }
                                save_trades(active_trades)
                                alert_candles[index_name]["buy_alert"] = None

                                send_telegram_alert(
                                    f"🟢 {index_name} BUY SIGNAL\n\n"
                                    f"📅 Date: {today_date_str}\n"
                                    f"⚡ Strategy: {STRATEGY_DISPLAY_NAME}\n"
                                    f"⏰ Time: {current_time_str}\n"
                                    f"💵 Entry: {current_price:.2f}\n"
                                    f"🛑 Stop Loss: {sl:.2f}\n\n"
                                    f"🎯 Target 1: {t1:.2f}\n"
                                    f"🎯 Target 2: {t2:.2f}\n"
                                    f"🎯 Target 3: {t3:.2f}"
                                )

            # HOURLY STATUS ALERT
            if now.minute == 0 and now.hour != last_heartbeat_hour and (9 <= now.hour <= 15):
                last_heartbeat_hour = now.hour
                hb_msg = f"💓 HOURLY STATUS ALERT\n⏰ Time: {current_time_str}\n📅 Date: {today_date_str}\n\n"
                for idx, prc in prices_dict.items():
                    prev_c = prev_close_dict.get(idx, prc)
                    diff = prc - prev_c
                    pct = (diff / prev_c) * 100 if prev_c else 0
                    sign = "+" if diff >= 0 else ""
                    hb_msg += f"• {idx}: {prc:.2f} ({sign}{diff:.2f} | {sign}{pct:.2f}%)\n"
                send_telegram_alert(hb_msg)

        time.sleep(3)
    except Exception as e:
        print(f"Main Loop Exception: {e}")
        time.sleep(3)
