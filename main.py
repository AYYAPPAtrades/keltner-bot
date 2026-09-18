import os
import time
import requests
from requests.adapters import HTTPAdapter
import json
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import pandas as pd
import numpy as np
import yfinance as yf
from nselib import capital_market

from reportlab.lib.pagesizes import letter, landscape
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

# --- TIMEZONE CONFIGURATION ---
IST = ZoneInfo("Asia/Kolkata")
start_now = datetime.now(IST)

# --- TELEGRAM CONFIGURATION (CHANNEL ONLY) ---
TELEGRAM_BOT_TOKEN = "8999213661:AAEfHcQzRZ2-ZI4bbfq8UcuGA48ihzQKchA"
TELEGRAM_CHAT_IDS = ["@sastradinglab", "6789591588"]

STRATEGY_DISPLAY_NAME = "MOMENTUM SPIKE"

# --- HIGH-SPEED TELEGRAM SESSION (ZERO DELAY) ---
tele_session = requests.Session()
adapter = HTTPAdapter(pool_connections=10, pool_maxsize=10)
tele_session.mount('https://', adapter)

# --- EMAIL CONFIGURATION ---
SENDER_EMAIL = "shinos99@gmail.com"
SENDER_APP_PASSWORD = "nouiwuzkyjbzsgix"
RECEIVER_EMAILS = ["shinos99@gmail.com"]

# --- FAST TELEGRAM DISPATCH ENGINES ---
def send_telegram_alert(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHANNEL_CHAT_ID,
        "text": msg,
        "disable_web_page_preview": True
    }
    try:
        tele_session.post(url, json=payload, timeout=3)
    except Exception as e:
        print(f"Telegram Fast Alert Error: {e}")

def send_telegram_document(file_path, caption=""):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendDocument"
    try:
        with open(file_path, 'rb') as doc:
            requests.post(url, data={'chat_id': CHANNEL_CHAT_ID, 'caption': caption}, files={'document': doc}, timeout=30)
    except Exception as e:
        print(f"Telegram Document Error: {e}")

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
        print("Report successfully emailed.")
    except Exception as e:
        print(f"Email Dispatch Warning: {e}")

# 1. IMMEDIATE CHANNEL STARTUP NOTIFICATION
send_telegram_alert(
    "🟢 SAS TRADING LAB Engine RUNNING!\n\n"
    f"⚡ Strategy: {STRATEGY_DISPLAY_NAME}\n"
    f"🕒 Time: {start_now.strftime('%I:%M:%S %p')} IST\n"
    f"📅 Date: {start_now.strftime('%d-%b-%Y')}\n"
    "📡 Precision Option Strikes & Zero-Delay Signals Armed."
)

# --- MARKET HOLIDAY CHECK ---
today_weekday = datetime.now(IST).weekday()
if today_weekday in [5, 6]:
    day_name = "Saturday" if today_weekday == 5 else "Sunday"
    send_telegram_alert(f"🏖️ WEEKEND MARKET HOLIDAY ({day_name})!\n\n• Market closed today.\n• Scanner resumes on Monday at 09:00 AM IST.")
    exit(0)

try:
    holidays_df = capital_market.holiday_trading()
    today_str = datetime.now(IST).strftime('%d-%b-%Y')
    if holidays_df is not None and not holidays_df.empty:
        if 'tradingDate' in holidays_df.columns and today_str in holidays_df['tradingDate'].values:
            reason = holidays_df[holidays_df['tradingDate'] == today_str]['description'].values[0]
            send_telegram_alert(f"🏖️ MARKET HOLIDAY TODAY!\n\n• Reason: {reason}\n• Scanner safely shut down.")
            exit(0)
except Exception as e:
    print(f"Holiday check bypassed: {e}")

INDEX_WATCHLIST = ["NIFTY 50", "NIFTY BANK"]
YF_TICKERS = {"NIFTY 50": "^NSEI", "NIFTY BANK": "^NSEBANK"}
TRADE_FILE = "active_trades_sas_momentum.json"
EXPIRY_LEDGER_FILE = "expiry_trades_ledger_sas.json"

# --- PERSISTENCE: RESTART & RECOVERY BACKUP ---
def load_backup_state():
    default_data = {
        "trades": {idx: None for idx in INDEX_WATCHLIST},
        "stats": {"total_signals": 0, "t1_hits": 0, "t2_hits": 0, "t3_hits": 0, "sl_hits": 0},
        "date": datetime.now(IST).strftime('%d-%b-%Y')
    }
    if os.path.exists(TRADE_FILE):
        try:
            with open(TRADE_FILE, 'r') as f:
                data = json.load(f)
                if data.get("date") == default_data["date"]:
                    return data.get("trades", default_data["trades"]), data.get("stats", default_data["stats"])
        except Exception as e:
            print(f"Backup Load Warning: {e}")
    return default_data["trades"], default_data["stats"]

def save_backup_state(trades, stats):
    try:
        data = {"trades": trades, "stats": stats, "date": datetime.now(IST).strftime('%d-%b-%Y')}
        with open(TRADE_FILE, 'w') as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        print(f"Backup Save Warning: {e}")

def load_expiry_ledger():
    if os.path.exists(EXPIRY_LEDGER_FILE):
        try:
            with open(EXPIRY_LEDGER_FILE, 'r') as f:
                return json.load(f)
        except Exception:
            return []
    return []

def record_to_expiry_ledger(trade_entry):
    records = load_expiry_ledger()
    records.append(trade_entry)
    try:
        with open(EXPIRY_LEDGER_FILE, 'w') as f:
            json.dump(records, f, indent=4)
    except Exception as e:
        print(f"Ledger save warning: {e}")

def clear_expiry_ledger():
    try:
        if os.path.exists(EXPIRY_LEDGER_FILE):
            os.remove(EXPIRY_LEDGER_FILE)
    except Exception:
        pass

active_trades, trade_stats = load_backup_state()

# --- ACCURATE EXPIRY DETECTION ---
def is_today_expiry(ticker="^NSEI"):
    try:
        t = yf.Ticker(ticker)
        expiries = t.options
        if expiries:
            today_str = datetime.now(IST).strftime('%Y-%m-%d')
            return expiries[0] == today_str
    except Exception as e:
        print(f"Expiry fetch note: {e}")
    return datetime.now(IST).weekday() == 1

def is_monthly_expiry_check():
    today = datetime.now(IST).date()
    next_week = today + timedelta(days=7)
    return today.month != next_week.month

# --- LIVE OPTION CHAIN RECOMMENDATIONS ---
def get_option_recommendations(index_name, spot_price, signal_direction, spot_risk):
    step = 50 if index_name == "NIFTY 50" else 100
    atm_strike = int(round(spot_price / step) * step)
    delta = 0.50

    buyer_strike_type = "CE" if signal_direction == "BUY" else "PE"
    seller_strike_type = "PE" if signal_direction == "BUY" else "CE"
    safe_seller_strike_val = (atm_strike - step) if signal_direction == "BUY" else (atm_strike + step)

    buyer_entry = None
    seller_entry = None
    safe_seller_entry = None

    try:
        symbol = "NIFTY" if index_name == "NIFTY 50" else "BANKNIFTY"
        chain_df = capital_market.live_index_option_chain(symbol)
        if chain_df is not None and not chain_df.empty:
            col_buyer = f"{buyer_strike_type}_lastPrice" if f"{buyer_strike_type}_lastPrice" in chain_df.columns else f"{buyer_strike_type}_LTP"
            col_seller = f"{seller_strike_type}_lastPrice" if f"{seller_strike_type}_lastPrice" in chain_df.columns else f"{seller_strike_type}_LTP"

            if col_buyer in chain_df.columns:
                val = chain_df[chain_df['strikePrice'] == atm_strike][col_buyer].values
                if len(val) > 0 and float(str(val[0]).replace(',', '')) > 0:
                    buyer_entry = float(str(val[0]).replace(',', ''))

            if col_seller in chain_df.columns:
                val_s = chain_df[chain_df['strikePrice'] == atm_strike][col_seller].values
                if len(val_s) > 0 and float(str(val_s[0]).replace(',', '')) > 0:
                    seller_entry = float(str(val_s[0]).replace(',', ''))

                val_safe = chain_df[chain_df['strikePrice'] == safe_seller_strike_val][col_seller].values
                if len(val_safe) > 0 and float(str(val_safe[0]).replace(',', '')) > 0:
                    safe_seller_entry = float(str(val_safe[0]).replace(',', ''))
    except Exception as e:
        print(f"Live option LTP fetch note: {e}")

    # Fallbacks
    if not buyer_entry:
        buyer_entry = 110.0 if index_name == "NIFTY 50" else 260.0
    if not seller_entry:
        seller_entry = buyer_entry
    if not safe_seller_entry:
        safe_seller_entry = round(seller_entry * 0.65, 1)

    buyer_sl = max(5.0, round(buyer_entry - (spot_risk * delta), 1))
    buyer_t1 = round(buyer_entry + (spot_risk * 1.0 * delta), 1)
    buyer_t2 = round(buyer_entry + (spot_risk * 1.5 * delta), 1)
    buyer_t3 = round(buyer_entry + (spot_risk * 2.5 * delta), 1)

    seller_sl = round(seller_entry + (spot_risk * delta), 1)
    seller_target = max(2.0, round(seller_entry - (spot_risk * 1.0 * delta), 1))

    return {
        "buyer_strike": f"{atm_strike} {buyer_strike_type}",
        "buyer_entry": buyer_entry,
        "buyer_sl": buyer_sl,
        "buyer_t1": buyer_t1,
        "buyer_t2": buyer_t2,
        "buyer_t3": buyer_t3,
        "seller_strike": f"{atm_strike} {seller_strike_type}",
        "seller_entry": seller_entry,
        "seller_sl": seller_sl,
        "seller_target": seller_target,
        "safe_seller_strike": f"{safe_seller_strike_val} {seller_strike_type}",
        "safe_seller_entry": safe_seller_entry
    }

# --- PDF REPORT GENERATION ---
def generate_pdf_report(filename, title_text, subtitle_text, logs):
    doc = SimpleDocTemplate(filename, pagesize=landscape(letter), rightMargin=15, leftMargin=15, topMargin=20, bottomMargin=20)
    styles = getSampleStyleSheet()
    elements = []

    title_style = ParagraphStyle('RepTitle', parent=styles['Heading1'], fontSize=15, leading=18, textColor=colors.HexColor("#1A365D"), alignment=1)
    elements.append(Paragraph(f"SAS TRADING LAB - {title_text}", title_style))
    elements.append(Paragraph(f"Strategy: {STRATEGY_DISPLAY_NAME} | Timeline: {subtitle_text} | Total Trades: {len(logs)}", styles['Normal']))
    elements.append(Spacer(1, 10))

    headers = ["SL", "Date", "Index & Type", "Entry & Time", "Target 1", "Target 2", "Target 3", "Stop Loss", "P/L Pts", "Status"]
    table_rows = [headers]

    for idx, log in enumerate(logs, start=1):
        t1_val = f"{log.get('t1', '-')}\n({log.get('t1_time', '-')})" if log.get('t1_hit') else "-"
        t2_val = f"{log.get('t2', '-')}\n({log.get('t2_time', '-')})" if log.get('t2_hit') else "-"
        t3_val = f"{log.get('t3', '-')}\n({log.get('t3_time', '-')})" if log.get('t3_hit') else "-"
        sl_val = f"{log.get('sl', '-')}"
        pnl_val = f"{log.get('pnl', 0.0):+.2f}"

        table_rows.append([
            str(idx), log.get('date', '-'), f"{log.get('index', '')}\n({log.get('type', '')})",
            f"{log.get('entry', 0.0):.2f}\n({log.get('entry_time', '')})",
            t1_val, t2_val, t3_val, sl_val, pnl_val, log.get('status', '-')
        ])

    col_widths = [25, 65, 80, 85, 80, 80, 80, 75, 65, 100]
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

# --- 5-DAY HISTORICAL DATA ---
def get_historical_5m_candles(index_name):
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
            return candles
    except Exception as e:
        print(f"History Fetch Error ({index_name}): {e}")
    return []

candle_history = {idx: get_historical_5m_candles(idx) for idx in INDEX_WATCHLIST}
current_candles = {idx: {"open": None, "high": -1, "low": 9999999, "close": None, "start_min": None} for idx in INDEX_WATCHLIST}
alert_candles = {idx: {"sell_alert": None, "buy_alert": None} for idx in INDEX_WATCHLIST}

def get_live_index_data():
    try:
        return capital_market.market_watch_all_indices()
    except Exception as e:
        return None

last_heartbeat_hour = -1

# --- SCANNER RUNTIME LOOP (ZERO DELAY) ---
while True:
    try:
        now = datetime.now(IST)
        current_time = now.time()
        current_time_str = now.strftime('%I:%M:%S %p')
        today_date_str = now.strftime('%d-%b-%Y')

        start_trade_time = datetime.strptime("09:30", "%H:%M").time()
        end_trade_time = datetime.strptime("15:20", "%H:%M").time()
        shutdown_time = datetime.strptime("15:40", "%H:%M").time()

        can_take_trades = (start_trade_time <= current_time < end_trade_time)
        is_market_closing = (current_time >= end_trade_time)

        # 03:40 PM SHUTDOWN & EXPIRY REPORT DELIVERY
        if current_time >= shutdown_time:
            today_is_exp = is_today_expiry()
            monthly_exp = is_monthly_expiry_check()

            if today_is_exp:
                records = load_expiry_ledger()
                exp_type = "MONTHLY EXPIRY" if monthly_exp else "WEEKLY EXPIRY"
                summary = (
                    f"📊 {exp_type} PERFORMANCE REPORT\n\n"
                    f"⚡ Strategy: {STRATEGY_DISPLAY_NAME}\n"
                    f"📅 Expiry Date: {today_date_str}\n\n"
                    f"• Total Trades This Expiry Cycle: {len(records)}\n"
                    f"• Target 1 Hits: {trade_stats['t1_hits']}\n"
                    f"• Target 2 Hits: {trade_stats['t2_hits']}\n"
                    f"• Target 3 Hits: {trade_stats['t3_hits']}\n"
                    f"• Stop Losses Hit: {trade_stats['sl_hits']}\n\n"
                    "📄 Comprehensive PDF generated and delivered via Email & Channel."
                )
                send_telegram_alert(summary)

                pdf_file = f"SAS_Lab_Expiry_Report_{today_date_str}.pdf"
                generate_pdf_report(pdf_file, f"{exp_type} REPORT", today_date_str, records)
                send_telegram_document(pdf_file, caption=f"📄 SAS TRADING LAB {exp_type} Report")
                send_email_with_pdf(pdf_file, f"SAS TRADING LAB {exp_type} Report - {today_date_str}", summary)

                clear_expiry_ledger()
            else:
                send_telegram_alert(
                    f"📊 MARKET CLOSED (DAILY SESSION)\n\n"
                    f"⚡ Strategy: {STRATEGY_DISPLAY_NAME}\n"
                    f"📅 Date: {today_date_str}\n\n"
                    f"• Trades Today: {trade_stats['total_signals']}\n"
                    f"• T1 Hits: {trade_stats['t1_hits']} | T2 Hits: {trade_stats['t2_hits']} | T3 Hits: {trade_stats['t3_hits']}\n"
                    f"• Stop Losses: {trade_stats['sl_hits']}\n\n"
                    "📌 Note: Detailed PDF reports are generated on Expiry Days.\n"
                    "SAS TRADING LAB Engine safely shut down. Resumes tomorrow at 09:00 AM IST."
                )
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

                    # 1. ACTIVE POSITION MONITORING
                    if trade is not None:
                        # 03:20 PM Auto Square-off
                        if is_market_closing:
                            pnl = current_price - trade['entry'] if trade['type'] == 'BUY' else trade['entry'] - current_price
                            trade['exit_price'] = current_price
                            trade['exit_time'] = current_time_str
                            trade['pnl'] = pnl
                            trade['status'] = 'Auto-Exit (03:20 PM)'
                            record_to_expiry_ledger(trade)

                            send_telegram_alert(
                                f"⏰ AUTO EXIT (03:20 PM CLOSE)\n\n"
                                f"⚡ Strategy: {STRATEGY_DISPLAY_NAME}\n"
                                f"Index: {index_name} ({trade['type']})\n"
                                f"Exit Spot: {current_price:.2f} | PnL: {pnl:+.2f} pts\n"
                                "Position Cleared for the Day."
                            )
                            active_trades[index_name] = None
                            save_backup_state(active_trades, trade_stats)
                            continue

                        # BUY TRADES MONITORING
                        if trade['type'] == 'BUY':
                            if not trade.get('t1_hit') and current_price >= trade['t1']:
                                trade['t1_hit'] = True
                                trade['t1_time'] = current_time_str
                                trade['sl'] = trade['entry']
                                trade_stats['t1_hits'] += 1
                                save_backup_state(active_trades, trade_stats)

                                send_telegram_alert(
                                    f"🎯 TARGET 1 HIT!\n\n"
                                    f"⚡ Strategy: {STRATEGY_DISPLAY_NAME}\n"
                                    f"Index: {index_name} (BUY)\n"
                                    f"Spot Price: {current_price:.2f} | T1: {trade['t1']:.2f}\n"
                                    f"⏰ Time: {current_time_str}\n"
                                    f"🛡️ Action: SL Moved to Cost ({trade['entry']:.2f}). Zero Risk Active!\n"
                                    f"🎯 T2 ({trade['t2']:.2f}) & T3 ({trade['t3']:.2f}) are LIVE."
                                )

                            if trade.get('t1_hit') and not trade.get('t2_hit') and current_price >= trade['t2']:
                                trade['t2_hit'] = True
                                trade['t2_time'] = current_time_str
                                trade_stats['t2_hits'] += 1
                                save_backup_state(active_trades, trade_stats)

                                send_telegram_alert(
                                    f"🎯🎯 TARGET 2 HIT!\n\n"
                                    f"⚡ Strategy: {STRATEGY_DISPLAY_NAME}\n"
                                    f"Index: {index_name} (BUY)\n"
                                    f"Spot Price: {current_price:.2f} | T2: {trade['t2']:.2f}\n"
                                    f"⏰ Time: {current_time_str}\n"
                                    f"Status: Major profits locked. Trailing to T3 ({trade['t3']:.2f})!"
                                )

                            if trade.get('t2_hit') and current_price >= trade['t3']:
                                trade['t3_hit'] = True
                                trade['t3_time'] = current_time_str
                                trade_stats['t3_hits'] += 1
                                pnl = current_price - trade['entry']
                                trade['exit_price'] = current_price
                                trade['exit_time'] = current_time_str
                                trade['pnl'] = pnl
                                trade['status'] = 'All Targets Hit (T3)'
                                record_to_expiry_ledger(trade)

                                send_telegram_alert(
                                    f"🏆 ALL TARGETS HIT (T3)!\n\n"
                                    f"⚡ Strategy: {STRATEGY_DISPLAY_NAME}\n"
                                    f"Index: {index_name} (BUY)\n"
                                    f"Exit Spot: {current_price:.2f} | PnL: +{pnl:.2f} pts\n"
                                    "Status: Full Targets Achieved. Trade Closed!"
                                )
                                active_trades[index_name] = None
                                save_backup_state(active_trades, trade_stats)
                                continue

                            if not trade.get('t1_hit') and current_price <= trade['sl']:
                                trade_stats['sl_hits'] += 1
                                pnl = current_price - trade['entry']
                                trade['exit_price'] = current_price
                                trade['exit_time'] = current_time_str
                                trade['pnl'] = pnl
                                trade['status'] = 'Stop Loss Hit'
                                record_to_expiry_ledger(trade)

                                send_telegram_alert(
                                    f"🛑 STOP LOSS HIT!\n\n"
                                    f"⚡ Strategy: {STRATEGY_DISPLAY_NAME}\n"
                                    f"Index: {index_name} (BUY)\n"
                                    f"Exit Spot: {current_price:.2f} | SL: {trade['sl']:.2f}\n"
                                    "Status: Position Cleared."
                                )
                                active_trades[index_name] = None
                                save_backup_state(active_trades, trade_stats)
                                continue

                            elif trade.get('t1_hit') and current_price <= trade['sl']:
                                pnl = current_price - trade['entry']
                                trade['exit_price'] = current_price
                                trade['exit_time'] = current_time_str
                                trade['pnl'] = pnl
                                trade['status'] = 'T1 Achieved & Cost Exit'
                                record_to_expiry_ledger(trade)

                                send_telegram_alert(
                                    f"🛡️ COST EXIT (ZERO LOSS)\n\n"
                                    f"⚡ Strategy: {STRATEGY_DISPLAY_NAME}\n"
                                    f"Index: {index_name} (BUY)\n"
                                    f"Spot Price returned to Entry: {current_price:.2f}\n"
                                    "Trade safely exited with profit locked at T1!"
                                )
                                active_trades[index_name] = None
                                save_backup_state(active_trades, trade_stats)
                                continue

                        # SELL TRADES MONITORING
                        elif trade['type'] == 'SELL':
                            if not trade.get('t1_hit') and current_price <= trade['t1']:
                                trade['t1_hit'] = True
                                trade['t1_time'] = current_time_str
                                trade['sl'] = trade['entry']
                                trade_stats['t1_hits'] += 1
                                save_backup_state(active_trades, trade_stats)

                                send_telegram_alert(
                                    f"🎯 TARGET 1 HIT!\n\n"
                                    f"⚡ Strategy: {STRATEGY_DISPLAY_NAME}\n"
                                    f"Index: {index_name} (SELL)\n"
                                    f"Spot Price: {current_price:.2f} | T1: {trade['t1']:.2f}\n"
                                    f"⏰ Time: {current_time_str}\n"
                                    f"🛡️ Action: SL Moved to Cost ({trade['entry']:.2f}). Zero Risk Active!\n"
                                    f"🎯 T2 ({trade['t2']:.2f}) & T3 ({trade['t3']:.2f}) are LIVE."
                                )

                            if trade.get('t1_hit') and not trade.get('t2_hit') and current_price <= trade['t2']:
                                trade['t2_hit'] = True
                                trade['t2_time'] = current_time_str
                                trade_stats['t2_hits'] += 1
                                save_backup_state(active_trades, trade_stats)

                                send_telegram_alert(
                                    f"🎯🎯 TARGET 2 HIT!\n\n"
                                    f"⚡ Strategy: {STRATEGY_DISPLAY_NAME}\n"
                                    f"Index: {index_name} (SELL)\n"
                                    f"Spot Price: {current_price:.2f} | T2: {trade['t2']:.2f}\n"
                                    f"⏰ Time: {current_time_str}\n"
                                    f"Status: Major profits locked. Trailing to T3 ({trade['t3']:.2f})!"
                                )

                            if trade.get('t2_hit') and current_price <= trade['t3']:
                                trade['t3_hit'] = True
                                trade['t3_time'] = current_time_str
                                trade_stats['t3_hits'] += 1
                                pnl = trade['entry'] - current_price
                                trade['exit_price'] = current_price
                                trade['exit_time'] = current_time_str
                                trade['pnl'] = pnl
                                trade['status'] = 'All Targets Hit (T3)'
                                record_to_expiry_ledger(trade)

                                send_telegram_alert(
                                    f"🏆 ALL TARGETS HIT (T3)!\n\n"
                                    f"⚡ Strategy: {STRATEGY_DISPLAY_NAME}\n"
                                    f"Index: {index_name} (SELL)\n"
                                    f"Exit Spot: {current_price:.2f} | PnL: +{pnl:.2f} pts\n"
                                    "Status: Full Targets Achieved. Trade Closed!"
                                )
                                active_trades[index_name] = None
                                save_backup_state(active_trades, trade_stats)
                                continue

                            if not trade.get('t1_hit') and current_price >= trade['sl']:
                                trade_stats['sl_hits'] += 1
                                pnl = trade['entry'] - current_price
                                trade['exit_price'] = current_price
                                trade['exit_time'] = current_time_str
                                trade['pnl'] = pnl
                                trade['status'] = 'Stop Loss Hit'
                                record_to_expiry_ledger(trade)

                                send_telegram_alert(
                                    f"🛑 STOP LOSS HIT!\n\n"
                                    f"⚡ Strategy: {STRATEGY_DISPLAY_NAME}\n"
                                    f"Index: {index_name} (SELL)\n"
                                    f"Exit Spot: {current_price:.2f} | SL: {trade['sl']:.2f}\n"
                                    "Status: Position Cleared."
                                )
                                active_trades[index_name] = None
                                save_backup_state(active_trades, trade_stats)
                                continue

                            elif trade.get('t1_hit') and current_price >= trade['sl']:
                                pnl = trade['entry'] - current_price
                                trade['exit_price'] = current_price
                                trade['exit_time'] = current_time_str
                                trade['pnl'] = pnl
                                trade['status'] = 'T1 Achieved & Cost Exit'
                                record_to_expiry_ledger(trade)

                                send_telegram_alert(
                                    f"🛡️ COST EXIT (ZERO LOSS)\n\n"
                                    f"⚡ Strategy: {STRATEGY_DISPLAY_NAME}\n"
                                    f"Index: {index_name} (SELL)\n"
                                    f"Spot Price returned to Entry: {current_price:.2f}\n"
                                    "Trade safely exited with profit locked at T1!"
                                )
                                active_trades[index_name] = None
                                save_backup_state(active_trades, trade_stats)
                                continue

                    # 2. 5-MINUTE CANDLE AGGREGATION & MOMENTUM SETUP
                    c_bucket = current_candles[index_name]
                    current_min_slot = (now.minute // 5) * 5
                    if c_bucket["start_min"] is None or c_bucket["start_min"] != current_min_slot:
                        if c_bucket["start_min"] is not None and c_bucket["open"] is not None:
                            completed_candle = {
                                'Open': c_bucket["open"], 'High': c_bucket["high"],
                                'Low': c_bucket["low"], 'Close': c_bucket["close"]
                            }
                            candle_history[index_name].append(completed_candle)
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

                    # 3. REAL-TIME SIGNAL TRIGGER WITH LIVE OPTION CHAIN
                    if can_take_trades and active_trades[index_name] is None:
                        # SELL TRIGGER
                        s_alert = alert_candles[index_name]["sell_alert"]
                        if s_alert and current_price < s_alert['low']:
                            risk = round(s_alert['high'] - s_alert['low'], 2)
                            min_risk = 10.0 if index_name == "NIFTY 50" else 25.0

                            if risk >= min_risk:
                                sl = round(s_alert['high'], 2)
                                t1 = round(current_price - (risk * 1.5), 2)
                                t2 = round(current_price - (risk * 2.0), 2)
                                t3 = round(current_price - (risk * 3.0), 2)

                                opt = get_option_recommendations(index_name, current_price, "SELL", risk)

                                active_trades[index_name] = {
                                    'date': today_date_str, 'index': index_name, 'type': 'SELL',
                                    'entry': current_price, 'entry_time': current_time_str,
                                    'sl': sl, 't1': t1, 't2': t2, 't3': t3,
                                    't1_hit': False, 't2_hit': False, 't3_hit': False
                                }
                                trade_stats['total_signals'] += 1
                                save_backup_state(active_trades, trade_stats)
                                alert_candles[index_name]["sell_alert"] = None

                                send_telegram_alert(
                                    f"🔴 {index_name} SELL SIGNAL (BUY PUT)\n\n"
                                    f"⚡ Strategy: {STRATEGY_DISPLAY_NAME}\n"
                                    f"📅 Date: {today_date_str}\n"
                                    f"⏰ Time: {current_time_str} IST\n"
                                    f"💵 Spot Entry: {current_price:.2f} | SL: {sl:.2f}\n\n"
                                    f"🛒 OPTION BUYERS (PUT):\n"
                                    f"• Strike: {opt['buyer_strike']} @ ₹{opt['buyer_entry']:.1f}\n"
                                    f"• Option SL: ₹{opt['buyer_sl']:.1f}\n"
                                    f"• Target 1: ₹{opt['buyer_t1']:.1f} | Target 2: ₹{opt['buyer_t2']:.1f} | Target 3: ₹{opt['buyer_t3']:.1f}\n\n"
                                    f"🛡️ OPTION SELLERS (CE):\n"
                                    f"• Sell ATM: {opt['seller_strike']} @ ₹{opt['seller_entry']:.1f}\n"
                                    f"• Safe OTM: {opt['safe_seller_strike']} @ ₹{opt['safe_seller_entry']:.1f}\n"
                                    f"• SL: ₹{opt['seller_sl']:.1f} | Target: ₹{opt['seller_target']:.1f}\n\n"
                                    f"🎯 Spot Targets: T1: {t1:.2f} | T2: {t2:.2f} | T3: {t3:.2f}"
                                )

                        # BUY TRIGGER
                        b_alert = alert_candles[index_name]["buy_alert"]
                        if b_alert and current_price > b_alert['high']:
                            risk = round(b_alert['high'] - b_alert['low'], 2)
                            min_risk = 10.0 if index_name == "NIFTY 50" else 25.0

                            if risk >= min_risk:
                                sl = round(b_alert['low'], 2)
                                t1 = round(current_price + (risk * 1.5), 2)
                                t2 = round(current_price + (risk * 2.0), 2)
                                t3 = round(current_price + (risk * 3.0), 2)

                                opt = get_option_recommendations(index_name, current_price, "BUY", risk)

                                active_trades[index_name] = {
                                    'date': today_date_str, 'index': index_name, 'type': 'BUY',
                                    'entry': current_price, 'entry_time': current_time_str,
                                    'sl': sl, 't1': t1, 't2': t2, 't3': t3,
                                    't1_hit': False, 't2_hit': False, 't3_hit': False
                                }
                                trade_stats['total_signals'] += 1
                                save_backup_state(active_trades, trade_stats)
                                alert_candles[index_name]["buy_alert"] = None

                                send_telegram_alert(
                                    f"🟢 {index_name} BUY SIGNAL (BUY CALL)\n\n"
                                    f"⚡ Strategy: {STRATEGY_DISPLAY_NAME}\n"
                                    f"📅 Date: {today_date_str}\n"
                                    f"⏰ Time: {current_time_str} IST\n"
                                    f"💵 Spot Entry: {current_price:.2f} | SL: {sl:.2f}\n\n"
                                    f"🛒 OPTION BUYERS (CALL):\n"
                                    f"• Strike: {opt['buyer_strike']} @ ₹{opt['buyer_entry']:.1f}\n"
                                    f"• Option SL: ₹{opt['buyer_sl']:.1f}\n"
                                    f"• Target 1: ₹{opt['buyer_t1']:.1f} | Target 2: ₹{opt['buyer_t2']:.1f} | Target 3: ₹{opt['buyer_t3']:.1f}\n\n"
                                    f"🛡️ OPTION SELLERS (PE):\n"
                                    f"• Sell ATM: {opt['seller_strike']} @ ₹{opt['seller_entry']:.1f}\n"
                                    f"• Safe OTM: {opt['safe_seller_strike']} @ ₹{opt['safe_seller_entry']:.1f}\n"
                                    f"• SL: ₹{opt['seller_sl']:.1f} | Target: ₹{opt['seller_target']:.1f}\n\n"
                                    f"🎯 Spot Targets: T1: {t1:.2f} | T2: {t2:.2f} | T3: {t3:.2f}"
                                )

            # 4. HOURLY STATUS ALERT (CHANNEL ONLY)
            if now.minute == 0 and now.hour != last_heartbeat_hour and (9 <= now.hour <= 15):
                last_heartbeat_hour = now.hour
                hb_msg = f"💓 SAS TRADING LAB: HOURLY STATUS\n⚡ Strategy: {STRATEGY_DISPLAY_NAME}\n⏰ Time: {current_time_str} IST\n\n"
                for idx, prc in prices_dict.items():
                    hb_msg += f"• {idx}: {prc:.2f}\n"
                send_telegram_alert(hb_msg)

        # Ultra-low 0.5s loop delay for instant execution
        time.sleep(0.5)

    except Exception as e:
        print(f"Loop Exception: {e}")
        time.sleep(1)
