import os
import asyncio
import random
from threading import Thread
from wsgiref.simple_server import make_server
from telegram.ext import Application, ContextTypes
from datetime import datetime, timedelta
import pytz
from config import CHAT_ID, ADMIN_CHAT_ID, GIF_URLS, message_counters, MAX_HISTORY_SIZE
from data_fetcher import get_token_data

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

# История цен
price_history = []

def get_msk_time():
    return datetime.now(pytz.timezone('Europe/Moscow'))

async def collect_price_data(context: ContextTypes.DEFAULT_TYPE):
    price_data = get_token_data()
    if isinstance(price_data, dict) and price_data['usd'] is not None:
        price_history.append({'timestamp': datetime.now(), 'usd': price_data['usd']})
        if len(price_history) > MAX_HISTORY_SIZE:
            price_history.pop(0)

async def send_price_update(context: ContextTypes.DEFAULT_TYPE):
    price_data = get_token_data()
    try:
        await context.bot.send_message(chat_id=CHAT_ID, text=price_data['message'] if isinstance(price_data, dict) else price_data, parse_mode="HTML")
        if isinstance(price_data, dict):
            message_counters[CHAT_ID] = message_counters.get(CHAT_ID, 0) + 1
            if message_counters[CHAT_ID] >= 10:
                await context.bot.send_animation(chat_id=CHAT_ID, animation=random.choice(GIF_URLS))
                message_counters[CHAT_ID] = 0
    except Exception:
        pass

async def send_four_hour_report(context: ContextTypes.DEFAULT_TYPE):
    price_data = get_token_data()
    if not isinstance(price_data, dict) or price_data['usd'] is None:
        try:
            await context.bot.send_message(chat_id=CHAT_ID, text="Error: Unable to fetch data for report", parse_mode="HTML")
        except Exception:
            pass
        return

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
        f"<b>🟢 Price Change:</b> {price_change_str}\n"
        f"<b>🔵 Maximum Price:</b> {max_price_str}\n"
        f"<b>🔵 Minimum Price:</b> {min_price_str}"
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
    from dotenv import load_dotenv
    load_dotenv()
    token = os.getenv("BOT_TOKEN")
    if not token:
        try:
            requests.get(f"https://api.telegram.org/bot7376596629:AAEWq1wQY03ColQcciuXxa7FmCkxQ4MUs7E/sendMessage?chat_id={ADMIN_CHAT_ID}&text=Error:%20BOT_TOKEN%20not%20set")
        except Exception:
            pass
        return
    if not os.getenv("TONAPI_KEY"):
        try:
            requests.get(f"https://api.telegram.org/bot{token}/sendMessage?chat_id={ADMIN_CHAT_ID}&text=Error:%20TONAPI_KEY%20not%20set")
        except Exception:
            pass
        return
    
    if not await check_and_delete_webhook(token):
        return
    
    application = Application.builder().token(token).build()
    if application.job_queue:
        application.job_queue.run_repeating(collect_price_data, interval=1800, first=10)  # 30 минут
        application.job_queue.run_repeating(send_price_update, interval=300, first=10)  # 5 минут
        application.job_queue.run_repeating(send_four_hour_report, interval=14400, first=10)  # 4 часа
    
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