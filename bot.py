import os
import requests
import asyncio
import random
from threading import Thread
from wsgiref.simple_server import make_server
from telegram.ext import Application, ContextTypes
from datetime import datetime, timedelta
import pytz
try:
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
except ImportError:
    raise

# Минимальное логирование
import logging
logging.basicConfig(format='%(levelname)s: %(message)s', level=logging.WARNING)
logger = logging.getLogger(__name__)

# WSGI для Render и UptimeRobot
def simple_wsgi_app(environ, start_response):
    status = '200 OK'
    headers = [('Content-type', 'text/plain; charset=utf-8')]
    start_response(status, headers)
    return [b"Bot is running"]

# Конфигурация
JETTON_ADDRESS = "EQBE_gBrU3mPI9hHjlJoR_kYyrhQgyCFD6EUWfa42W8T7EBP"
CHAT_ID = "-1002954606074"
ADMIN_CHAT_ID = "YOUR_ADMIN_CHAT_ID"  # Замените на ваш chat_id
message_counters = {}
price_history = []
MAX_HISTORY_SIZE = 16
GIF_URLS = [
    "https://media.giphy.com/media/83JLhFcYedwQBR0oW5/giphy.mp4",
    "https://media.giphy.com/media/nZW5fIzaIJVXddVla7/giphy.mp4",
    "https://media.giphy.com/media/KNeeNrAQQqt0v8jvf9/giphy.mp4"
]

def get_msk_time():
    return datetime.now(pytz.timezone('Europe/Moscow'))

def get_tac_price():
    url = f"https://tonapi.io/v2/rates?tokens={JETTON_ADDRESS}&currencies=ton,usd"
    headers = {"Authorization": f"Bearer {os.getenv('TONAPI_KEY')}"}
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if 'rates' not in data or JETTON_ADDRESS not in data['rates']:
                return "Error: Invalid TonAPI response"
            rates = data['rates'][JETTON_ADDRESS]['prices']
            usd_price = rates.get('USD', 'N/A')
            ton_price = rates.get('TON', 'N/A')
            usd_str = f"{float(usd_price):.4f}" if usd_price != 'N/A' else 'N/A'
            ton_str = f"{float(ton_price):.4f}" if ton_price != 'N/A' else 'N/A'
            return {
                'usd': float(usd_price) if usd_price != 'N/A' else None,
                'ton': float(ton_price) if ton_price != 'N/A' else None,
                'usd_str': usd_str,
                'ton_str': ton_str,
                'message': (
                    f"<b>🟣 $TAC Price:</b>\n"
                    f"<b>🟢 USD: ${usd_str}</b>\n"
                    f"<b>🔵 TON: {ton_str} TON</b>"
                )
            }
        return f"Error: TonAPI returned {response.status_code}"
    except Exception:
        return "Error: Failed to fetch price"

def get_ton_usd_price():
    headers = {"Authorization": f"Bearer {os.getenv('TONAPI_KEY')}"}
    try:
        response = requests.get("https://tonapi.io/v2/rates?tokens=ton&currencies=usd", headers=headers, timeout=10)
        response.raise_for_status()
        return float(response.json()['rates']['TON']['prices']['USD'])
    except Exception:
        return None

def get_tac_volume():
    session = requests.Session()
    retries = Retry(total=2, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
    session.mount('https://', HTTPAdapter(max_retries=retries))
    
    # Попробовать STON.fi
    try:
        since = (datetime.utcnow() - timedelta(days=1)).isoformat(timespec='seconds')
        until = datetime.utcnow().isoformat(timespec='seconds')
        response = session.get("https://api.ston.fi/v1/stats/pool", params={'since': since, 'until': until}, timeout=10)
        response.raise_for_status()
        stats = response.json().get('stats', [])
        for jetton in stats:
            if (jetton.get('base_address') == JETTON_ADDRESS or 
                jetton.get('quote_address') == JETTON_ADDRESS) and jetton.get('quote_symbol') == 'TON':
                volume_ton = float(jetton.get('quote_volume', 0))
                ton_usd = get_ton_usd_price()
                if ton_usd:
                    return volume_ton * ton_usd
                return None
    except Exception:
        pass
    
    # Попробовать DeDust
    try:
        response = session.get("https://api.dedust.io/v2/pools", timeout=10)
        response.raise_for_status()
        data = response.json()
        for pool in data:
            if (pool.get('address') == JETTON_ADDRESS or 
                pool.get('assets', [{}])[0].get('address') == JETTON_ADDRESS) and pool.get('quote_asset') == 'TON':
                return float(pool.get('volume_24h', 0))
        return None
    except Exception:
        return None

async def collect_price_data(context: ContextTypes.DEFAULT_TYPE):
    price_data = get_tac_price()
    if isinstance(price_data, dict) and price_data['usd'] is not None:
        price_history.append({'timestamp': datetime.now(), 'usd': price_data['usd']})
        if len(price_history) > MAX_HISTORY_SIZE:
            price_history.pop(0)

async def send_price_update(context: ContextTypes.DEFAULT_TYPE):
    price_data = get_tac_price()
    try:
        await context.bot.send_message(chat_id=CHAT_ID, text=price_data['message'] if isinstance(price_data, dict) else price_data, parse_mode="HTML")
        if isinstance(price_data, dict):
            message_counters[CHAT_ID] = message_counters.get(CHAT_ID, 0) + 1
            if message_counters[CHAT_ID] >= 10:
                await context.bot.send_animation(chat_id=CHAT_ID, animation=random.choice(GIF_URLS))
                message_counters[CHAT_ID] = 0
    except Exception:
        pass

async def send_volume_update(context: ContextTypes.DEFAULT_TYPE):
    volume = get_tac_volume()
    message = f"<b>🟣 Volume (24h): ${volume:,.2f}</b> (MSK: {get_msk_time().strftime('%H:%M')})" if volume else f"<b>🟣 Volume (24h): N/A</b> (MSK: {get_msk_time().strftime('%H:%M')})"
    try:
        await context.bot.send_message(chat_id=CHAT_ID, text=message, parse_mode="HTML")
        message_counters[CHAT_ID] = message_counters.get(CHAT_ID, 0) + 1
        if message_counters[CHAT_ID] >= 10:
            await context.bot.send_animation(chat_id=CHAT_ID, animation=random.choice(GIF_URLS))
            message_counters[CHAT_ID] = 0
        if not volume:
            await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text="Error: Failed to fetch volume", parse_mode="HTML")
    except Exception:
        pass

async def send_four_hour_report(context: ContextTypes.DEFAULT_TYPE):
    price_data = get_tac_price()
    volume = get_tac_volume()
    if not isinstance(price_data, dict) or price_data['usd'] is None:
        try:
            await context.bot.send_message(chat_id=CHAT_ID, text="Error: Unable to fetch data for report", parse_mode="HTML")
        except Exception:
            pass
        return

    volume_str = f"${volume:,.2f}" if volume else "N/A"
    four_hours_ago = datetime.now() - timedelta(hours=4)
    past_prices = [entry['usd'] for entry in price_history if entry['timestamp'] > four_hours_ago]
    price_change_str = "N/A"
    if past_prices and len(past_prices) > 1:
        oldest_price = past_prices[0]
        current_price = price_data['usd']
        if oldest_price != 0:
            price_change_str = f"{((current_price - oldest_price) / oldest_price * 100):+.2f}%"
    
    max_price_str = f"${max(past_prices):.4f}" if past_prices else price_data['usd_str']
    min_price_str = f"${min(past_prices):.4f}" if past_prices else price_data['usd_str']
    
    report_message = (
        f"<b>🟣 4-Hour Report:</b>\n"
        f"<b>🟢 Volume:</b> {volume_str}\n"
        f"<b>🔵 Price Change:</b> {price_change_str}\n"
        f"<b>Maximum Price:</b> {max_price_str}\n"
        f"<b>Minimum Price:</b> {min_price_str}"
    )
    
    try:
        await context.bot.send_message(chat_id=CHAT_ID, text=report_message, parse_mode="HTML")
        message_counters[CHAT_ID] = message_counters.get(CHAT_ID, 0) + 1
        if message_counters[CHAT_ID] >= 10:
            await context.bot.send_animation(chat_id=CHAT_ID, animation=random.choice(GIF_URLS))
            message_counters[CHAT_ID] = 0
    except Exception:
        pass

async def check_and_delete_webhook(token: str):
    try:
        response = requests.get(f"https://api.telegram.org/bot{token}/getWebhookInfo", timeout=5)
        if response.json().get("result", {}).get("url"):
            requests.get(f"https://api.telegram.org/bot{token}/deleteWebhook", timeout=5)
        return True
    except Exception:
        return True

def run_wsgi():
    port = int(os.getenv("PORT", 8080))
    server = make_server('0.0.0.0', port, simple_wsgi_app)
    server.serve_forever()

async def main():
    token = "7376596629:AAEWq1wQY03ColQcciuXxa7FmCkxQ4MUs7E"
    if not os.getenv("TONAPI_KEY"):
        return
    
    if not await check_and_delete_webhook(token):
        return
    
    application = Application.builder().token(token).build()
    if application.job_queue:
        application.job_queue.run_repeating(collect_price_data, interval=1800, first=10)  # 30 минут для экономии памяти
        application.job_queue.run_repeating(send_price_update, interval=300, first=10)
        application.job_queue.run_repeating(send_volume_update, interval=3600, first=10)
        application.job_queue.run_repeating(send_four_hour_report, interval=14400, first=10)
    
    wsgi_thread = Thread(target=run_wsgi, daemon=True)
    wsgi_thread.start()
    
    try:
        await application.initialize()
        await application.start()
        await application.updater.start_polling(allowed_updates=None, drop_pending_updates=True)
        await asyncio.Event().wait()
    except asyncio.CancelledError:
        pass
    except Exception:
        pass
    finally:
        await application.updater.stop()
        await application.stop()
        await application.shutdown()

if __name__ == "__main__":
    asyncio.run(main())