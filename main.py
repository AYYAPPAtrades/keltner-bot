import os
import time
import requests
import json
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import pandas as pd
import yfinance as yf
from nselib import capital_market

from reportlab.lib.pagesizes import letter, landscape
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

# --- TIMEZONE CONFIGURATION ---
IST = ZoneInfo("Asia/Kolkata")
start_now = datetime.now(IST)

# --- TELEGRAM CONFIGURATION ---

TELEGRAM_BOT_TOKEN = "8804327561:"AAHYL_srWzPSWCZR5aJe_tMOfD24HblsL_Q"

ADMIN_CHAT_ID = "6789591588"
CHANNEL_CHAT_ID = "@sastradinglab"
PUBLIC_ALERT_IDS = [CHANNEL_CHAT_ID, ADMIN_CHAT_ID]

tele_session = requests.Session()
STRATEGY_DISPLAY_NAME = "MOMENTUM SPIKE"
CHANNEL_NAME = "SAS TRADING LAB"

# --- EMAIL CONFIGURATION ---
SENDER_EMAIL = "shinos99@gmail.com"
SENDER_APP_PASSWORD = "xufefwfphwsomsnu"
RECEIVER_EMAILS = ["shinos99@gmail.com"]

def send_admin_alert(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        res = tele_session.post(url, json={"chat_id": ADMIN_CHAT_ID, "text": msg}, timeout=10)
        print(f"Admin alert status: {res.status_code}")
    except Exception as e:
        print(f"Admin Alert Error: {e}")

def send_telegram_alert(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    for chat_id in PUBLIC_ALERT_IDS:
        try:
            res = tele_session.post(url, json={"chat_id": chat_id, "text": msg}, timeout=10)
            print(f"Telegram alert ({chat_id}): {res.status_code}")
        except Exception as e:
            print(f"Telegram Alert Error ({chat_id}): {e}")

def send_telegram_document(file_path, caption=""):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendDocument"
    for chat_id in PUBLIC_ALERT_IDS:
        try:
            with open(file_path, 'rb') as doc:
                res = requests.post(url, data={'chat_id': chat_id, 'caption': caption}, files={'document': doc}, timeout=25)
                print(f"Telegram doc ({chat_id}): {res.status_code}")
        except Exception as e:
            print(f"Telegram Doc Error ({chat_id}): {e}")

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
    except Exception as e:
        print(f"Email Dispatch Warning: {e}")

# --- BOT INSTANT STARTUP ALERT ---
startup_message = (
    f"🚀 ALGO SCANNER LIVE\n\n"
    f"📍 Channel: {CHANNEL_NAME}\n"
    f"⚡ Strategy: {STRATEGY_DISPLAY_NAME}\n"
    f"🕒 Time: {start_now.strftime('%I:%M:%S %p')} IST\n"
    f"🛡️ Status: Engine Running & Connected Successfully!"
)
send_telegram_alert(startup_message)

INDEX_WATCHLIST = ["NIFTY 50", "NIFTY BANK"]
YF_TICKERS = {"NIFTY 50": "^NSEI", "NIFTY BANK": "^NSEBANK"}
BACKUP_FILE = "daily_active_trades.json"
EXPIRY_LEDGER_FILE = "expiry_trades_ledger.json"

trade_stats = {"total_signals": 0, "target_hits": 0, "sl_hits": 0}
prev_close_dict = {}
last_tick_prices = {}
camarilla_levels = {}

# ANTI-REPEAT FLAGS
open_alert_sent = start_now.time() >= datetime.strptime("09:15", "%H:%M").time()
pivots_alert_sent = start_now.time() >= datetime.strptime("09:15", "%H:%M").time()
eod_alert_sent = False
last_heartbeat_hour = -1

# --- PERSISTENT STATE MANAGEMENT ---
def load_backup_state():
    default_state = {idx: None for idx in INDEX_WATCHLIST}
    today_str = datetime.now(IST).strftime('%d-%b-%Y')
    if os.path.exists(BACKUP_FILE):
        try:
            with open(BACKUP_FILE, 'r') as f:
                data = json.load(f)
                for idx in INDEX_WATCHLIST:
                    if idx in data and data[idx] and data[idx].get('date') != today_str:
                        data[idx] = None
                    elif idx not in data:
                        data[idx] = None
                return data
        except Exception:
            return default_state
    return default_state

def save_state(state):
    try:
        with open(BACKUP_FILE, 'w') as f:
            json.dump(state, f, indent=4)
    except Exception:
        pass

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
    except Exception:
        pass

def clear_expiry_ledger():
    try:
        if os.path.exists(EXPIRY_LEDGER_FILE):
            os.remove(EXPIRY_LEDGER_FILE)
    except Exception:
        pass

active_trades = load_backup_state()
restored_trades = [f"{k} ({v['type']} @ {v['entry']})" for k, v in active_trades.items() if v is not None]

if restored_trades:
    send_admin_alert(
        f"♻️ BOT RESUMED & STATE RESTORED\n\n"
        f"⚡ Active Retained Trades:\n• " + "\n• ".join(restored_trades) + "\n\n"
        f"🎯 Retaining active SL & Targets without repeated alerts."
    )

def is_today_nifty_expiry():
    try:
        t = yf.Ticker("^NSEI")
        expiries = t.options
        if expiries:
            today_str = datetime.now(IST).strftime('%Y-%m-%d')
            return expiries[0] == today_str
    except Exception:
        pass
    return datetime.now(IST).weekday() == 1

def is_monthly_expiry_check():
    today = datetime.now(IST).date()
    next_week = today + timedelta(days=7)
    return today.month != next_week.month

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
        print(f"Option LTP fetch note: {e}")

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

def calculate_camarilla_pivots(index_name):
    try:
        ticker = YF_TICKERS.get(index_name)
        df_daily = yf.download(ticker, period="5d", interval="1d", progress=False)
        if not df_daily.empty:
            if isinstance(df_daily.columns, pd.MultiIndex):
                df_daily.columns = df_daily.columns.get_level_values(0)
            prev_day = df_daily.iloc[-2]
            high = float(prev_day['High'])
            low = float(prev_day['Low'])
            close = float(prev_day['Close'])
            diff = high - low
            pivot = (high + low + close) / 3.0

            return {
                "Pivot": round(pivot, 2),
                "R4": round(close + (diff * 1.1 / 2.0), 2),
                "R3": round(close + (diff * 1.1 / 4.0), 2),
                "S3": round(close - (diff * 1.1 / 4.0), 2),
                "S4": round(close - (diff * 1.1 / 2.0), 2),
                "Prev_Close": round(close, 2)
            }
    except Exception as e:
        print(f"Camarilla error ({index_name}): {e}")
    return None

for idx in INDEX_WATCHLIST:
    camarilla_levels[idx] = calculate_camarilla_pivots(idx)

def generate_pdf_report(filename, title_text, date_text, logs):
    doc = SimpleDocTemplate(filename, pagesize=landscape(letter), rightMargin=15, leftMargin=15, topMargin=20, bottomMargin=20)
    styles = getSampleStyleSheet()
    elements = []

    title_style = ParagraphStyle('RepTitle', parent=styles['Heading1'], fontSize=14, leading=17, textColor=colors.HexColor("#1A365D"), alignment=1)
    elements.append(Paragraph(f"{CHANNEL_NAME} - {title_text}", title_style))
    elements.append(Paragraph(f"Strategy: {STRATEGY_DISPLAY_NAME} | Timeline: {date_text} | Total Trades: {len(logs)}", styles['Normal']))
    elements.append(Spacer(1, 10))

    headers = ["SL", "Date", "Index & Type", "Entry & Time", "Target 1", "Target 2", "Target 3", "Stop Loss", "P/L Pts", "Status"]
    table_rows = [headers]

    for i, l in enumerate(logs, 1):
        table_rows.append([
            str(i), l.get('date', '-'), f"{l.get('index')}\n({l.get('type')})",
            f"{l.get('entry'):.2f}\n({l.get('entry_time')})",
            f"{l.get('t1'):.2f}" if l.get('t1_hit') else "-",
            f"{l.get('t2'):.2f}" if l.get('t2_hit') else "-",
            f"{l.get('t3'):.2f}" if l.get('t3_hit') else "-",
            f"{l.get('sl'):.2f}",
            f"{l.get('pnl', 0.0):+.2f}",
            l.get('status', '-')
        ])

    trade_table = Table(table_rows, colWidths=[25, 65, 80, 80, 80, 80, 80, 80, 65, 110])
    trade_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#2B6CB0")),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E0")),
        ('FONTSIZE', (0, 0), (-1, -1), 7.5),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]))
    elements.append(trade_table)
    doc.build(elements)

def get_live_indices():
    try:
        return capital_market.market_watch_all_indices()
    except Exception:
        return None

# --- MAIN ENGINE LOOP ---
while True:
    try:
        now = datetime.now(IST)
        current_time = now.time()
        current_time_str = now.strftime('%I:%M:%S %p')
        today_date_str = now.strftime('%d-%b-%Y')

        market_open_notify_time = datetime.strptime("09:00", "%H:%M").time()
        pivot_alert_time = datetime.strptime("09:05", "%H:%M").time()
        start_trade_time = datetime.strptime("09:15", "%H:%M").time()
        exit_alert_time = datetime.strptime("15:25", "%H:%M").time()
        shutdown_time = datetime.strptime("15:40", "%H:%M").time()

        # 1. 09:00 AM MARKET OPENING ALERT
        if not open_alert_sent and (market_open_notify_time <= current_time < pivot_alert_time):
            open_alert_sent = True
            send_admin_alert(
                f"🔔 MARKET OPENING SESSION (09:00 AM)\n\n"
                f"📍 Channel: {CHANNEL_NAME}\n"
                f"⚡ Strategy: {STRATEGY_DISPLAY_NAME}\n"
                f"📅 Date: {today_date_str}\n"
                f"🛡️ Pre-market tracking online. Trading signals commence at 09:15 AM IST."
            )

        # 2. 09:05 AM CAMARILLA LEVELS
        if not pivots_alert_sent and (pivot_alert_time <= current_time < start_trade_time):
            pivots_alert_sent = True
            p_msg = f"📐 DAILY CAMARILLA SUPPORT & RESISTANCE (09:05 AM)\n📅 Date: {today_date_str}\n⚡ Strategy: {STRATEGY_DISPLAY_NAME}\n\n"
            for idx in INDEX_WATCHLIST:
                lvl = camarilla_levels.get(idx)
                if lvl:
                    p_msg += f"🔹 {idx}\n• Pivot: {lvl['Pivot']:.2f}\n• R4 (Breakout Buy): {lvl['R4']:.2f}\n• R3 (Resistance): {lvl['R3']:.2f}\n• S3 (Support): {lvl['S3']:.2f}\n• S4 (Breakdown Sell): {lvl['S4']:.2f}\n\n"
            send_telegram_alert(p_msg)

        # 3. 03:25 PM INTRADAY AUTO-EXIT
        if current_time >= exit_alert_time and not eod_alert_sent:
            eod_alert_sent = True
            send_telegram_alert(
                "⚠️ INTRADAY AUTO-EXIT ALERT (03:25 PM)\n\n"
                "• Market closing soon.\n"
                "• Squaring off all active intraday positions safely."
            )
            for idx in INDEX_WATCHLIST:
                trade = active_trades[idx]
                if trade is not None:
                    last_prc = prev_close_dict.get(idx, trade['entry'])
                    pnl = last_prc - trade['entry'] if trade['type'] == 'BUY' else trade['entry'] - last_prc
                    trade['exit_price'] = last_prc
                    trade['pnl'] = pnl
                    trade['status'] = 'Auto-Exit (03:25 PM)'
                    record_to_expiry_ledger(trade)
                    send_telegram_alert(f"🏁 POSITION SQUARED OFF ({idx})\n• P/L: {pnl:+.2f} Pts\n• Status: Intraday Auto-Exit")
                    active_trades[idx] = None
            save_state(active_trades)

        # 4. 03:40 PM SHUTDOWN, DAILY & EXPIRY PDF REPORT
        if current_time >= shutdown_time:
            today_is_exp = is_today_nifty_expiry()
            records = load_expiry_ledger()
            today_records = [r for r in records if r.get('date') == today_date_str]

            daily_summary = (
                f"📊 DAILY MARKET SUMMARY\n\n"
                f"📅 Date: {today_date_str}\n"
                f"⚡ Strategy: {STRATEGY_DISPLAY_NAME}\n"
                f"• Signals Executed: {len(today_records)}\n"
                f"• Target Wins: {trade_stats['target_hits']}\n"
                f"• Stop Losses: {trade_stats['sl_hits']}\n\n"
                f"Dispatching Daily PDF Performance Report..."
            )
            send_telegram_alert(daily_summary)

            daily_pdf_file = f"Daily_Report_{today_date_str}.pdf"
            generate_pdf_report(daily_pdf_file, "DAILY PERFORMANCE REPORT", today_date_str, today_records)
            send_telegram_document(daily_pdf_file, caption=f"📄 Daily Performance Report ({today_date_str})")
            send_email_with_pdf(daily_pdf_file, f"Daily Market Report - {today_date_str}", daily_summary)

            if today_is_exp:
                exp_type = "MONTHLY EXPIRY" if is_monthly_expiry_check() else "WEEKLY EXPIRY"
                exp_summary = (
                    f"📊 {exp_type} REPORT (EXPIRY TO EXPIRY)\n\n"
                    f"📅 Expiry Date: {today_date_str}\n"
                    f"⚡ Strategy: {STRATEGY_DISPLAY_NAME}\n"
                    f"• Cycle Trades: {len(records)}\n"
                    f"• Total Target Hits: {trade_stats['target_hits']}\n"
                    f"• Total Stop Losses: {trade_stats['sl_hits']}\n\n"
                    f"Dispatching Expiry PDF Report..."
                )
                send_telegram_alert(exp_summary)

                exp_pdf_file = f"Expiry_Report_{today_date_str}.pdf"
                generate_pdf_report(exp_pdf_file, f"{exp_type} PERFORMANCE REPORT", today_date_str, records)
                send_telegram_document(exp_pdf_file, caption=f"📄 {exp_type} Report ({today_date_str})")
                send_email_with_pdf(exp_pdf_file, f"{exp_type} Report - {today_date_str}", exp_summary)

                clear_expiry_ledger()
            break

        # DATA STREAM & SIGNAL ENGINE
        raw = get_live_indices()
        if raw is not None and not raw.empty:
            prices_dict = {}
            for idx in INDEX_WATCHLIST:
                row = raw[raw['index'] == idx]
                if not row.empty:
                    current_price = float(str(row['last'].values[0]).replace(',', ''))
                    prices_dict[idx] = current_price

                    if idx not in prev_close_dict and 'previousClose' in row.columns:
                        prev_close_dict[idx] = float(str(row['previousClose'].values[0]).replace(',', ''))

                    prev_tick = last_tick_prices.get(idx, current_price)
                    trade = active_trades[idx]

                    # 1. POSITION TRACKING (TARGETS & STOP LOSS)
                    if trade is not None:
                        # BUY TRADE
                        if trade['type'] == 'BUY':
                            if current_price <= trade['sl']:
                                trade_stats['sl_hits'] += 1
                                pnl = current_price - trade['entry']
                                trade['exit_price'] = current_price
                                trade['pnl'] = pnl
                                trade['status'] = 'Cost Exit' if trade.get('t1_hit') else 'SL Hit'
                                record_to_expiry_ledger(trade)
                                if not trade.get('t1_hit'):
                                    send_telegram_alert(f"🛑 STOP LOSS HIT!\n📍 Index: {idx} (CALL)\n💵 Exit Price: {current_price:.2f}\n⏰ Time: {current_time_str}")
                                else:
                                    send_telegram_alert(f"🛡️ COST EXIT (ZERO LOSS)\n📍 Index: {idx} (CALL)\n💵 Exit Price: {current_price:.2f}\n⏰ Time: {current_time_str}")
                                active_trades[idx] = None
                                save_state(active_trades)
                                continue

                            if not trade.get('t1_hit') and current_price >= trade['t1']:
                                trade['t1_hit'] = True
                                trade['sl'] = trade['entry']
                                trade_stats['target_hits'] += 1
                                save_state(active_trades)
                                send_telegram_alert(
                                    f"🎯 TARGET 1 HIT!\n⚡ Strategy: {STRATEGY_DISPLAY_NAME}\n"
                                    f"Index: {idx} (CALL)\n💵 Target Price: {trade['t1']:.2f}\n"
                                    f"Current Price: {current_price:.2f}\n🛡️ Stop Loss moved to Cost ({trade['entry']:.2f}). T2 & T3 LIVE!"
                                )

                            if trade.get('t1_hit') and not trade.get('t2_hit') and current_price >= trade['t2']:
                                trade['t2_hit'] = True
                                trade['sl'] = trade['t1']
                                save_state(active_trades)
                                send_telegram_alert(
                                    f"🎯 TARGET 2 HIT!\n⚡ Strategy: {STRATEGY_DISPLAY_NAME}\n"
                                    f"Index: {idx} (CALL)\n💵 Target Price: {trade['t2']:.2f}\n"
                                    f"Current Price: {current_price:.2f}"
                                )

                            if trade.get('t2_hit') and current_price >= trade['t3']:
                                trade['t3_hit'] = True
                                pnl = current_price - trade['entry']
                                trade['exit_price'] = current_price
                                trade['pnl'] = pnl
                                trade['status'] = 'Target 3 Achieved'
                                record_to_expiry_ledger(trade)
                                send_telegram_alert(
                                    f"🎯 TARGET 3 HIT!\n⚡ Strategy: {STRATEGY_DISPLAY_NAME}\n"
                                    f"Index: {idx} (CALL)\n💵 Target Price: {trade['t3']:.2f}\n"
                                    f"Current Price: {current_price:.2f}"
                                )
                                active_trades[idx] = None
                                save_state(active_trades)
                                continue

                        # SELL TRADE
                        elif trade['type'] == 'SELL':
                            if current_price >= trade['sl']:
                                trade_stats['sl_hits'] += 1
                                pnl = trade['entry'] - current_price
                                trade['exit_price'] = current_price
                                trade['pnl'] = pnl
                                trade['status'] = 'Cost Exit' if trade.get('t1_hit') else 'SL Hit'
                                record_to_expiry_ledger(trade)
                                if not trade.get('t1_hit'):
                                    send_telegram_alert(f"🛑 STOP LOSS HIT!\n📍 Index: {idx} (PUT)\n💵 Exit Price: {current_price:.2f}\n⏰ Time: {current_time_str}")
                                else:
                                    send_telegram_alert(f"🛡️ COST EXIT (ZERO LOSS)\n📍 Index: {idx} (PUT)\n💵 Exit Price: {current_price:.2f}\n⏰ Time: {current_time_str}")
                                active_trades[idx] = None
                                save_state(active_trades)
                                continue

                            if not trade.get('t1_hit') and current_price <= trade['t1']:
                                trade['t1_hit'] = True
                                trade['sl'] = trade['entry']
                                trade_stats['target_hits'] += 1
                                save_state(active_trades)
                                send_telegram_alert(
                                    f"🎯 TARGET 1 HIT!\n⚡ Strategy: {STRATEGY_DISPLAY_NAME}\n"
                                    f"Index: {idx} (PUT)\n💵 Target Price: {trade['t1']:.2f}\n"
                                    f"Current Price: {current_price:.2f}\n🛡️ Stop Loss moved to Cost ({trade['entry']:.2f}). T2 & T3 LIVE!"
                                )

                            if trade.get('t1_hit') and not trade.get('t2_hit') and current_price <= trade['t2']:
                                trade['t2_hit'] = True
                                trade['sl'] = trade['t1']
                                save_state(active_trades)
                                send_telegram_alert(
                                    f"🎯 TARGET 2 HIT!\n⚡ Strategy: {STRATEGY_DISPLAY_NAME}\n"
                                    f"Index: {idx} (PUT)\n💵 Target Price: {trade['t2']:.2f}\n"
                                    f"Current Price: {current_price:.2f}"
                                )

                            if trade.get('t2_hit') and current_price <= trade['t3']:
                                trade['t3_hit'] = True
                                pnl = trade['entry'] - current_price
                                trade['exit_price'] = current_price
                                trade['pnl'] = pnl
                                trade['status'] = 'Target 3 Achieved'
                                record_to_expiry_ledger(trade)
                                send_telegram_alert(
                                    f"🎯 TARGET 3 HIT!\n⚡ Strategy: {STRATEGY_DISPLAY_NAME}\n"
                                    f"Index: {idx} (PUT)\n💵 Target Price: {trade['t3']:.2f}\n"
                                    f"Current Price: {current_price:.2f}"
                                )
                                active_trades[idx] = None
                                save_state(active_trades)
                                continue

                    # 2. SIGNAL GENERATION (DYNAMIC RISK-REWARD ENGINE)
                    pivots = camarilla_levels.get(idx)
                    can_trade = (start_trade_time <= current_time < exit_alert_time)

                    if can_trade and active_trades[idx] is None and pivots is not None:
                        r4, s4, r3, s3, pp = pivots['R4'], pivots['S4'], pivots['R3'], pivots['S3'], pivots['Pivot']

                        trigger_signal = None
                        entry_type = None
                        calc_sl = None

                        if current_price <= pp and prev_tick > pp:
                            trigger_signal = "SELL"
                            entry_type = "MOMENTUM SPIKE"
                            calc_sl = round(r3 if current_price < r3 else pp, 2)
                        elif current_price >= pp and prev_tick < pp:
                            trigger_signal = "BUY"
                            entry_type = "MOMENTUM SPIKE"
                            calc_sl = round(s3 if current_price > s3 else pp, 2)
                        elif current_price > r4:
                            trigger_signal = "BUY"
                            entry_type = "CAMARILLA BREAKOUT"
                            calc_sl = round(r3, 2)
                        elif current_price < s4:
                            trigger_signal = "SELL"
                            entry_type = "CAMARILLA BREAKDOWN"
                            calc_sl = round(s3, 2)

                        if trigger_signal:
                            if trigger_signal == "BUY":
                                risk = round(current_price - calc_sl, 2)
                                min_limit = 15.0 if idx == "NIFTY 50" else 40.0
                                if risk < min_limit:
                                    risk = min_limit
                                    calc_sl = round(current_price - risk, 2)

                                t1 = round(current_price + (risk * 1.437), 2)
                                t2 = round(current_price + (risk * 1.915), 2)
                                t3 = round(current_price + (risk * 2.873), 2)
                                opt = get_option_recommendations(idx, current_price, "BUY", risk)

                                active_trades[idx] = {
                                    'date': today_date_str, 'index': idx, 'type': 'BUY',
                                    'entry': current_price, 'entry_time': current_time_str,
                                    'sl': calc_sl, 't1': t1, 't2': t2, 't3': t3,
                                    't1_hit': False, 't2_hit': False, 't3_hit': False
                                }
                                save_state(active_trades)
                                trade_stats['total_signals'] += 1

                                send_telegram_alert(
                                    f"🟢 {idx} BUY SIGNAL\n\n"
                                    f"⚡ Strategy: {STRATEGY_DISPLAY_NAME}\n"
                                    f"⏰ Time: {current_time_str} IST\n"
                                    f"💵 Entry Price: {current_price:.2f}\n"
                                    f"🛑 Stop Loss: {calc_sl:.2f}\n\n"
                                    f"🎯 Target 1: {t1:.2f}\n"
                                    f"🎯 Target 2: {t2:.2f}\n"
                                    f"🎯 Target 3: {t3:.2f}\n\n"
                                    f"🛒 OPTION BUYERS (CALL):\n"
                                    f"• Strike: {opt['buyer_strike']} @ ₹{opt['buyer_entry']:.1f}\n"
                                    f"• SL: ₹{opt['buyer_sl']:.1f} | T1: ₹{opt['buyer_t1']:.1f}\n\n"
                                    f"🛡️ OPTION SELLERS (PE):\n"
                                    f"• Strike: {opt['seller_strike']} @ ₹{opt['seller_entry']:.1f}\n"
                                    f"• SL: ₹{opt['seller_sl']:.1f} | Target: ₹{opt['seller_target']:.1f}"
                                )

                            elif trigger_signal == "SELL":
                                risk = round(calc_sl - current_price, 2)
                                min_limit = 15.0 if idx == "NIFTY 50" else 40.0
                                if risk < min_limit:
                                    risk = min_limit
                                    calc_sl = round(current_price + risk, 2)

                                t1 = round(current_price - (risk * 1.437), 2)
                                t2 = round(current_price - (risk * 1.915), 2)
                                t3 = round(current_price - (risk * 2.873), 2)
                                opt = get_option_recommendations(idx, current_price, "SELL", risk)

                                active_trades[idx] = {
                                    'date': today_date_str, 'index': idx, 'type': 'SELL',
                                    'entry': current_price, 'entry_time': current_time_str,
                                    'sl': calc_sl, 't1': t1, 't2': t2, 't3': t3,
                                    't1_hit': False, 't2_hit': False, 't3_hit': False
                                }
                                save_state(active_trades)
                                trade_stats['total_signals'] += 1

                                send_telegram_alert(
                                    f"🔴 {idx} SELL SIGNAL\n\n"
                                    f"⚡ Strategy: {STRATEGY_DISPLAY_NAME}\n"
                                    f"⏰ Time: {current_time_str} IST\n"
                                    f"💵 Entry Price: {current_price:.2f}\n"
                                    f"🛑 Stop Loss: {calc_sl:.2f}\n\n"
                                    f"🎯 Target 1: {t1:.2f}\n"
                                    f"🎯 Target 2: {t2:.2f}\n"
                                    f"🎯 Target 3: {t3:.2f}\n\n"
                                    f"🛒 OPTION BUYERS (PUT):\n"
                                    f"• Strike: {opt['buyer_strike']} @ ₹{opt['buyer_entry']:.1f}\n"
                                    f"• SL: ₹{opt['buyer_sl']:.1f} | T1: ₹{opt['buyer_t1']:.1f}\n\n"
                                    f"🛡️ OPTION SELLERS (CE):\n"
                                    f"• Strike: {opt['seller_strike']} @ ₹{opt['seller_entry']:.1f}\n"
                                    f"• SL: ₹{opt['seller_sl']:.1f} | Target: ₹{opt['seller_target']:.1f}"
                                )

                    last_tick_prices[idx] = current_price

            # 3. HOURLY STATUS ALERT (ADMIN ONLY)
            if now.minute == 0 and now.hour != last_heartbeat_hour and (9 <= now.hour <= 15):
                last_heartbeat_hour = now.hour
                hb_msg = f"💓 HOURLY STATUS ALERT\n⏰ Time: {current_time.strftime('%I:%M:00 %p')} IST\n\n"
                for idx, prc in prices_dict.items():
                    prev_c = prev_close_dict.get(idx, prc)
                    diff = prc - prev_c
                    pct = (diff / prev_c) * 100 if prev_c != 0 else 0.0
                    hb_msg += f"• {idx}: {prc:.2f} ({diff:+.2f} | {pct:+.2f}%)\n"
                send_admin_alert(hb_msg)

        time.sleep(1)

    except Exception as e:
        print(f"Engine Loop Warning: {e}")
        time.sleep(2)
