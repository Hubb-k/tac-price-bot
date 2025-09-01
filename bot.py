import os
import asyncio
import random
from threading import Thread
from wsgiref.simple_server import make_server
from telegram.ext import Application, ContextTypes
from datetime import datetime, timedelta
import pytz
import logging
from config import CHAT_ID, ADMIN_CHAT_ID, GIF_URLS, message_counters, MAX_HISTORY_SIZE
from data_fetcher import get_token_data

# Логирование для отладки
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
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
        logger.info("Collected price data: USD=%s", price_data['usd'])

async def send_price_update(context: ContextTypes.DEFAULT_TYPE):
    price_data = get_token_data()
    try:
        await context.bot.send_message(chat_id=CHAT_ID, text=price_data['message'] if isinstance(price_data, dict) else price_data, parse_mode="HTML")
        if isinstance(price_data, dict):
            message_counters[CHAT_ID] = message_counters.get(CHAT_ID, 0) + 1
            if message_counters[CHAT_ID] >= 10:
                await context.bot.send_animation(chat_id=CHAT_ID, animation=random.choice(GIF_URLS))
                message_counters[CHAT_ID] = 0
            logger.info("Sent price update to %s", CHAT_ID)
    except Exception as e:
        logger.error("Failed to send price update: %s", e)

async def send_four_hour_report(context: ContextTypes.DEFAULT_TYPE):
    price_data = get_token_data()
    if not isinstance(price_data, dict) or price_data['usd'] is None:
        try:
            await context.bot.send_message(chat_id=CHAT_ID, text="Error: Unable to fetch data for report", parse_mode="HTML")
            logger.error("Failed to fetch data for 4-hour report")
        except Exception as e:
            logger.error("Failed to send error report: %s", e)
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
        logger.info("Sent 4-hour report to %s", CHAT_ID)
    except Exception as e:
        logger.error("Failed to send 4-hour report: %s", e)

async def check_and_delete_webhook(token: str):
    import requests
    try:
        response = requests.get(f"https://api.telegram.org/bot{token}/getWebhookInfo", timeout=5)
        webhook_info = response.json()
        if webhook_info.get("result", {}).get("url"):
            logger.info("Webhook found, deleting...")
            requests.get(f"https://api.telegram.org/bot{token}/deleteWebhook", timeout=5)
            logger.info("Webhook deleted")
        return True
    except Exception as e:
        logger.error("Failed to check/delete webhook: %s", e)
        return True

def run_wsgi():
    port = int(os.getenv("PORT", 8080))
    server = make_server('0.0.0.0', port, simple_wsgi_app)
    logger.info("Starting WSGI server on port %s", port)
    server.serve_forever()

async def main():
    from dotenv import load_dotenv
    load_dotenv()
    token = os.getenv("BOT_TOKEN")
    if not token:
        try:
            import requests
            requests.get(f"https://api.telegram.org/bot737