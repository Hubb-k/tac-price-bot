import os
import requests
import asyncio
import logging
import random
from threading import Thread
from wsgiref.simple_server import make_server
from telegram.ext import Application, ContextTypes
from datetime import datetime, timedelta
import pytz
try:
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
except ImportError as e:
    logging.error(f"Ошибка импорта urllib3: {e}")
    raise

# Настройка логирования
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Простой WSGI-эндпоинт для Render и UptimeRobot
def simple_wsgi_app(environ, start_response):
    status = '200 OK'
    headers = [('Content-type', 'text/plain; charset=utf-8')]
    start_response(status, headers)
    return [b"Bot is running"]

# Адрес Jetton-контракта $TAC
JETTON_ADDRESS = "EQBE_gBrU3mPI9hHjlJoR_kYyrhQgyCFD6EUWfa42W8T7EBP"
CHAT_ID = "-1002954606074"
ADMIN_CHAT_ID = "224780379"  # Замените на ваш chat_id
message_counters = {}
price_history = []
GIF_URLS = [
    "https://media.giphy.com/media/83JLhFcYedwQBR0oW5/giphy.mp4",
    "https://media.giphy.com/media/nZW5fIzaIJVXddVla7/giphy.mp4",
    "https://media.giphy.com/media/KNeeNrAQQqt0v8jvf9/giphy.mp4"
]

def get_msk_time():
    return datetime.now(pytz.timezone('Europe/Moscow'))

def get_tac_price():
    url = f"https://tonapi.io/v2/rates?tokens={JETTON_ADDRESS}&currencies=ton,usd"
    headers = {}
    tonapi_key = os.getenv("TONAPI_KEY")
    if not tonapi_key:
        logger.error("TONAPI_KEY is not set in environment variables")
        return "Error: TONAPI_KEY is not configured"
    headers["Authorization"] = f"Bearer {tonapi_key}"
    logger.info(f"Using TONAPI_KEY: {tonapi_key[:5]}...")
    try:
        response = requests.get(url, headers=headers, timeout=10)
        logger.info(f"TonAPI response status: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            logger.info(f"TonAPI response: {data}")
            if 'rates' not in data or JETTON_ADDRESS not in data['rates']:
                logger.error(f"Invalid response format: {data}")
                return "Error: Invalid response from TonAPI"
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
        elif response.status_code == 429:
            logger.error(f"TonAPI rate limit exceeded (429): {response.text}")
            return "Error: TonAPI rate limit exceeded"
        else:
            error_msg = f"TonAPI Error: Code {response.status_code}, Response: {response.text}"
            logger.error(error_msg)
            return error_msg
    except requests.exceptions.RequestException as e:
        error_msg = f"Network error in get_tac_price: {str(e)}"
        logger.error(error_msg)
        return error_msg
    except Exception as e:
        error_msg = f"Unexpected error in get_tac_price: {str(e)}"
        logger.error(error_msg)
        return error_msg

def get_ton_usd_price():
    tonapi_key = os.getenv("TONAPI_KEY")
    if not tonapi_key:
        logger.error("TONAPI_KEY не установлен")
        return None
    url = "https://tonapi.io/v2/rates?tokens=ton&currencies=usd"
    headers = {"Authorization": f"Bearer {tonapi_key}"}
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        logger.info(f"Ответ TonAPI (TON/USD): {data}")
        return float(data['rates']['TON']['prices']['USD'])
    except Exception as e:
        logger.error(f"Ошибка в get_ton_usd_price: {e}")
        return None

def get_tac_volume():
    session = requests.Session()
    retries = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
    session.mount('https://', HTTPAdapter(max_retries=retries))
    try:
        since = (datetime.utcnow() - timedelta(days=1)).isoformat(timespec='seconds')
        until = datetime.utcnow().isoformat(timespec='seconds')
        payload = {'since': since, 'until': until}
        url = "https://api.ston.fi/v1/stats/pool"
        logger.info(f"Запрос к STON.fi API: {url} with params {payload}")
        response = session.get(url, params=payload, timeout=15)
        response.raise_for_status()
        data = response.json()
        logger.info(f"Полный ответ STON.fi API: {data}")
        stats = data.get('stats', [])
        for jetton in stats:
            logger.info(f"Пул: base_address={jetton.get('base_address')}, quote_address={jetton.get('quote_address')}, quote_symbol={jetton.get('quote_symbol')}")
            if (jetton.get('base_address') == JETTON_ADDRESS or 
                jetton.get('quote_address') == JETTON_ADDRESS) and jetton.get('quote_symbol') == 'TON':
                volume_ton = float(jetton.get('quote_volume', 0))
                ton_usd = get_ton_usd_price()
                if ton_usd is not None:
                    volume_usd = volume_ton * ton_usd
                    logger.info(f"Объем за 24 часа: ${volume_usd:,.2f}")
                    return volume_usd
                else:
                    logger.warning("Не удалось получить цену TON/USD")
                    return None
        logger.warning(f"Пул для $TAC ({JETTON_ADDRESS}) не найден")
        return None
    except Exception as e:
        logger.error(f"Ошибка в get_tac_volume: {e}")
        return None

async def collect_price_data(context: ContextTypes.DEFAULT_TYPE):
    price_data = get_tac_price()
    if isinstance(price_data, dict) and price_data['usd'] is not None:
        timestamp = datetime.now()
        price_history.append({'timestamp': timestamp, 'usd': price_data['usd']})
        four_hours_ago = timestamp - timedelta(hours=4)
        price_history = [entry for entry in price_history if entry['timestamp'] > four_hours_ago]
        logger.info(f"Collected price: ${price_data['usd']:.4f}, history size: {len(price_history)}")
    else:
        logger.error(f"Failed to collect price data: {price_data}")

async def send_price_update(context: ContextTypes.DEFAULT_TYPE):
    price_data = get_tac_price()
    if isinstance(price_data, dict):
        price_message = price_data['message']
        logger.info(f"Sending auto-update to {CHAT_ID}: {price_message}")
        try:
            await context.bot.send_message(chat_id=CHAT_ID, text=price_message, parse_mode="HTML")
            message_counters[CHAT_ID] = message_counters.get(CHAT_ID, 0) + 1
            if message_counters[CHAT_ID] >= 10:
                gif_url = random.choice(GIF_URLS)
                try:
                    await context.bot.send_animation(chat_id=CHAT_ID, animation=gif_url)
                    logger.info(f"Sent GIF to channel {CHAT_ID}: {gif_url}")
                    message_counters[CHAT_ID] = 0
                except Exception as e:
                    logger.error(f"Error sending GIF to channel {CHAT_ID}: {str(e)}")
        except Exception as e:
            logger.error(f"Error in send_price_update: {str(e)}")
    else:
        error_msg = price_data
        logger.error(f"Sending error to {CHAT_ID}: {error_msg}")
        try:
            await context.bot.send_message(chat_id=CHAT_ID, text=error_msg, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Error sending error message to {CHAT_ID}: {str(e)}")

async def send_volume_update(context: ContextTypes.DEFAULT_TYPE):
    logger.info("Запуск send_volume_update")
    volume = get_tac_volume()
    if volume is not None:
        volume_str = f"{volume:,.2f}"
        message = f"<b>Volume (24h): ${volume_str}</b> (MSK: {get_msk_time().strftime('%H:%M')})"
    else:
        message = f"<b>Volume (24h): N/A (failed to fetch data)</b> (MSK: {get_msk_time().strftime('%H:%M')})"
        logger.warning("Не удалось получить данные об объеме")
        try:
            await context.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=f"Ошибка: Не удалось получить данные об объеме от STON.fi",
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Ошибка при отправке уведомления админу: {e}")
    try:
        await context.bot.send_message(chat_id=CHAT_ID, text=message, parse_mode="HTML")
        message_counters[CHAT_ID] = message_counters.get(CHAT_ID, 0) + 1
        if message_counters[CHAT_ID] >= 10:
            gif_url = random.choice(GIF_URLS)
            try:
                await context.bot.send_animation(chat_id=CHAT_ID, animation=gif_url)
                logger.info(f"Sent GIF to channel {CHAT_ID}: {gif_url}")
                message_counters[CHAT_ID] = 0
            except Exception as e:
                logger.error(f"Error sending GIF to channel {CHAT_ID}: {str(e)}")
    except Exception as e:
        logger.error(f"Ошибка при отправке объема: {e}")

async def send_four_hour_report(context: ContextTypes.DEFAULT_TYPE):
    price_data = get_tac_price()
    volume = get_tac_volume()
    if not isinstance(price_data, dict) or price_data['usd'] is None:
        logger.error(f"Failed to fetch current price for report: {price_data}")
        await context.bot.send_message(chat_id=CHAT_ID, text="Error: Unable to fetch data for report", parse_mode="HTML")
        return

    volume_str = f"${volume:,.2f}" if volume is not None else "N/A"
    four_hours_ago = datetime.now() - timedelta(hours=4)
    past_prices = [entry['usd'] for entry in price_history if entry['timestamp'] > four_hours_ago]
    if past_prices and len(past_prices) > 1:
        oldest_price = past_prices[0]
        current_price = price_data['usd']
        price_change_percent = ((current_price - oldest_price) / oldest_price * 100) if oldest_price != 0 else 0
        price_change_str = f"{price_change_percent:+.2f}%"
    else:
        price_change_str = "N/A (insufficient data)"

    max_price = max(past_prices) if past_prices else price_data['usd']
    min_price = min(past_prices) if past_prices else price_data['usd']
    max_price_str = f"${max_price:.4f}" if max_price is not None else "N/A"
    min_price_str = f"${min_price:.4f}" if min_price is not None else "N/A"

    report_message = (
        f"<b>🟣 4-Hour Report:</b>\n"
        f"<b>🟢 Volume:</b> {volume_str}\n"
        f"<b>🔵 Price Change:</b> {price_change_str}\n"
        f"<b>Maximum Price:</b> {max_price_str}\n"
        f"<b>Minimum Price:</b> {min_price_str}"
    )

    try:
        await context.bot.send_message(chat_id=CHAT_ID, text=report_message, parse_mode="HTML")
        logger.info(f"Sent 4-hour report to {CHAT_ID}: {report_message}")
        message_counters[CHAT_ID] = message_counters.get(CHAT_ID, 0) + 1
        if message_counters[CHAT_ID] >= 10:
            gif_url = random.choice(GIF_URLS)
            try:
                await context.bot.send_animation(chat_id=CHAT_ID, animation=gif_url)
                logger.info(f"Sent GIF to channel {CHAT_ID}: {gif_url}")
                message_counters[CHAT_ID] = 0
            except Exception as e:
                logger.error(f"Error sending GIF to channel {CHAT_ID}: {str(e)}")
    except Exception as e:
        logger.error(f"Error sending report to {CHAT_ID}: {str(e)}")

async def check_and_delete_webhook(token: str):
    try:
        response = requests.get(f"https://api.telegram.org/bot{token}/getWebhookInfo")
        data = response.json()
        logger.info(f"Webhook info: {data}")
        if data.get("result", {}).get("url"):
            logger.info("Webhook detected, attempting to delete")
            response = requests.get(f"https://api.telegram.org/bot{token}/deleteWebhook")
            if response.json().get("ok"):
                logger.info("Webhook successfully deleted")
            else:
                logger.error(f"Failed to delete webhook: {response.json()}")
        else:
            logger.info("No webhook set, proceeding with polling")
    except Exception as e:
        logger.error(f"Error checking/deleting webhook: {str(e)}")

def run_wsgi():
    port = int(os.getenv("PORT", 8080))
    logger.info(f"Starting WSGI server on port {port}")
    server = make_server('0.0.0.0', port, simple_wsgi_app)
    server.serve_forever()

async def main():
    logger.info("Starting bot")
    token = "7376596629:AAEWq1wQY03ColQcciuXxa7FmCkxQ4MUs7E"
    tonapi_key = os.getenv("TONAPI_KEY")
    if not tonapi_key:
        logger.error("TONAPI_KEY is not set. Bot may fail to fetch prices.")
    
    # Проверяем и удаляем webhook
    await check_and_delete_webhook(token)
    
    application = Application.builder().token(token).build()
    if application.job_queue is None:
        logger.error("Error: job_queue is None")
        return
    application.job_queue.run_repeating(collect_price_data, interval=900, first=0)  # Сбор цен каждые 15 минут
    application.job_queue.run_repeating(send_price_update, interval=300, first=0)  # Цены каждые 5 минут
    application.job_queue.run_repeating(send_volume_update, interval=3600, first=0)  # Объём каждый час
    application.job_queue.run_repeating(send_four_hour_report, interval=14400, first=0)  # Отчет каждые 4 часа
    
    wsgi_thread = Thread(target=run_wsgi, daemon=True)
    wsgi_thread.start()
    
    try:
        await application.initialize()
        await application.start()
        await application.updater.start_polling(allowed_updates=Update.ALL_TYPES)
        logger.info("Bot started successfully")
        await asyncio.Event().wait()
    except Exception as e:
        logger.error(f"Error in main: {str(e)}", exc_info=True)
        raise
    finally:
        await application.updater.stop()
        await application.stop()
        await application.shutdown()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        logger.error(f"Error in main: {str(e)}", exc_info=True)