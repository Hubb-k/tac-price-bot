import sys
import os
import requests
import asyncio
import logging
import random
from threading import Thread
from wsgiref.simple_server import make_server
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters
from datetime import datetime, timedelta
from time import sleep

# Настройка логирования
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Простой WSGI-эндпоинт для Render
def simple_wsgi_app(environ, start_response):
    status = '200 OK'
    headers = [('Content-type', 'text/plain; charset=utf-8')]
    start_response(status, headers)
    return [b"Bot is running"]

# Адрес Jetton-контракта $TAC и пула на STON.fi
JETTON_ADDRESS = "EQBE_gBrU3mPI9hHjlJoR_kYyrhQgyCFD6EUWfa42W8T7EBP"
POOL_ADDRESS = "EQBp8y9u4gYmVLCiG4CVZw9Ir3IDV5a9xoAxG3Du7xrwFFmP"

# Счетчик сообщений для каждого чата
message_counters = {}

# Хранилище для истории цен (в USD)
price_history = []

# Кэш последнего успешного объема
last_known_volume = None

# Список рабочих URL-адресов GIF
GIF_URLS = [
    "https://media.giphy.com/media/83JLhFcYedwQBR0oW5/giphy.mp4",  # Moon
    "https://media.giphy.com/media/nZW5fIzaIJVXddVla7/giphy.mp4",  # Dancing Cat
    "https://media.giphy.com/media/KNeeNrAQQqt0v8jvf9/giphy.mp4",  # Clown
]

# Функция для получения цены из TonAPI
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

# Функция для получения 24-часового объема торгов из STON.fi
def get_tac_volume():
    global last_known_volume
    for attempt in range(3):
        try:
            url = f"https://api.ston.fi/v1/pools/{POOL_ADDRESS}"
            response = requests.get(url, timeout=10)
            logger.info(f"STON.fi response status (attempt {attempt + 1}): {response.status_code}")
            logger.info(f"STON.fi response: {response.text}")
            if response.status_code == 200:
                data = response.json()
                volume_usd = float(data.get('volume_24h', 0))  # 24h объем в USD
                last_known_volume = volume_usd
                logger.info(f"Got volume from STON.fi: ${volume_usd:,.2f}")
                return volume_usd
            elif response.status_code == 429:
                logger.warning(f"STON.fi rate limit exceeded, retrying in {2 ** attempt} seconds")
                sleep(2 ** attempt)  # Экспоненциальная задержка
                continue
            else:
                logger.error(f"STON.fi error: Code {response.status_code}, Response: {response.text}")
                break
        except Exception as e:
            logger.error(f"Error in get_tac_volume (STON.fi, attempt {attempt + 1}): {str(e)}")
            sleep(2 ** attempt)
    
    logger.info(f"Returning last known volume: ${last_known_volume:,.2f if last_known_volume else 'None'}")
    return last_known_volume

# Функция для отправки объема каждый час в 00 минут
async def send_volume_update(context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = "-1002954606074"
    volume = get_tac_volume()
    volume_str = f"{volume:,.2f}" if volume is not None else "N/A"
    message = f"<b>Volume (24h): ${volume_str}</b>"
    try:
        await context.bot.send_message(chat_id=int(chat_id), text=message, parse_mode="HTML")
        logger.info(f"Sent volume update to {chat_id}: {message}")
        
        global message_counters
        message_counters[chat_id] = message_counters.get(chat_id, 0) + 1
        if message_counters[chat_id] >= 10:
            gif_url = random.choice(GIF_URLS)
            try:
                await context.bot.send_animation(chat_id=int(chat_id), animation=gif_url)
                logger.info(f"Sent GIF to channel {chat_id}: {gif_url}")
                message_counters[chat_id] = 0
            except Exception as e:
                logger.error(f"Error sending GIF to channel {chat_id}: {str(e)}")
    except Exception as e:
        logger.error(f"Error sending volume update to {chat_id}: {str(e)}")

# Функция для сбора цен каждые 15 минут
async def collect_price_data(context: ContextTypes.DEFAULT_TYPE) -> None:
    global price_history
    price_data = get_tac_price()
    if isinstance(price_data, dict) and price_data['usd'] is not None:
        timestamp = datetime.now()
        price_history.append({'timestamp': timestamp, 'usd': price_data['usd']})
        four_hours_ago = timestamp - timedelta(hours=4)
        price_history = [entry for entry in price_history if entry['timestamp'] > four_hours_ago]
        logger.info(f"Collected price: ${price_data['usd']:.4f}, history size: {len(price_history)}")
    else:
        logger.error(f"Failed to collect price data: {price_data}")
        await asyncio.sleep(10)

# Функция для создания отчета каждые 4 часа
async def send_four_hour_report(context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = "-1002954606074"
    price_data = get_tac_price()
    if not isinstance(price_data, dict) or price_data['usd'] is None:
        logger.error(f"Failed to fetch current price for report: {price_data}")
        await context.bot.send_message(chat_id=int(chat_id), text="Error: Unable to fetch data for report", parse_mode="HTML")
        return

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
        f"<b>4-Hour Report:</b>\n"
        f"<b>Price Change: {price_change_str}</b>\n"
        f"<b>Maximum Price: {max_price_str}</b>\n"
        f"<b>Minimum Price: {min_price_str}</b>"
    )

    try:
        await context.bot.send_message(chat_id=int(chat_id), text=report_message, parse_mode="HTML")
        logger.info(f"Sent 4-hour report to {chat_id}: {report_message}")
        
        global message_counters
        message_counters[chat_id] = message_counters.get(chat_id, 0) + 1
        if message_counters[chat_id] >= 10:
            gif_url = random.choice(GIF_URLS)
            try:
                await context.bot.send_animation(chat_id=int(chat_id), animation=gif_url)
                logger.info(f"Sent GIF to channel {chat_id}: {gif_url}")
                message_counters[chat_id] = 0
            except Exception as e:
                logger.error(f"Error sending GIF to channel {chat_id}: {str(e)}")
    except Exception as e:
        logger.error(f"Error sending report to {chat_id}: {str(e)}")

# Обработчик всех сообщений для подсчета и отправки GIF
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.message.chat_id
    message_counters[chat_id] = message_counters.get(chat_id, 0) + 1
    logger.info(f"Message count for chat {chat_id}: {message_counters[chat_id]}")
    
    if message_counters[chat_id] >= 10:
        gif_url = random.choice(GIF_URLS)
        try:
            await context.bot.send_animation(chat_id=chat_id, animation=gif_url)
            logger.info(f"Sent GIF to chat {chat_id}: {gif_url}")
            message_counters[chat_id] = 0
        except Exception as e:
            logger.error(f"Error sending GIF to chat {chat_id}: {str(e)}")

# Команда /start с кнопками
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    keyboard = [
        [InlineKeyboardButton("Get Price", callback_data="price")],
        [InlineKeyboardButton("Help", callback_data="help")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        f"Hello! I'm a $TAC price bot. Click the button below:\nYour chat_id: {update.message.chat_id}",
        reply_markup=reply_markup
    )

# Команда /price
async def price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    price_data = get_tac_price()
    if isinstance(price_data, dict):
        price_message = price_data['message']
        logger.info(f"Sending price to {update.message.chat_id}: {price_message}")
        keyboard = [[InlineKeyboardButton("Refresh Price", callback_data="price")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(price_message, reply_markup=reply_markup, parse_mode="HTML")
    else:
        error_msg = price_data
        logger.error(f"Sending error to {update.message.chat_id}: {error_msg}")
        await update.message.reply_text(error_msg, parse_mode="HTML")

# Обработчик кнопок
async def button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if query.data == "price":
        price_data = get_tac_price()
        if isinstance(price_data, dict):
            price_message = price_data['message']
            logger.info(f"Sending price to {query.message.chat_id}: {price_message}")
            keyboard = [[InlineKeyboardButton("Refresh Price", callback_data="price")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.message.reply_text(price_message, reply_markup=reply_markup, parse_mode="HTML")
        else:
            error_msg = price_data
            logger.error(f"Sending error to {query.message.chat_id}: {error_msg}")
            await query.message.reply_text(error_msg, parse_mode="HTML")
    elif query.data == "help":
        await query.message.reply_text("I'm a bot for tracking $TAC price. Use /price or the 'Get Price' button.")

# Автоматическое обновление цены
async def send_price_update(context: ContextTypes.DEFAULT_TYPE) -> None:
    price_data = get_tac_price()
    chat_id = "-1002954606074"
    if isinstance(price_data, dict):
        price_message = price_data['message']
        logger.info(f"Sending auto-update to {chat_id}: {price_message}")
        try:
            await context.bot.send_message(chat_id=int(chat_id), text=price_message, parse_mode="HTML")
            message_counters[chat_id] = message_counters.get(chat_id, 0) + 1
            if message_counters[chat_id] >= 10:
                gif_url = random.choice(GIF_URLS)
                try:
                    await context.bot.send_animation(chat_id=int(chat_id), animation=gif_url)
                    logger.info(f"Sent GIF to channel {chat_id}: {gif_url}")
                    message_counters[chat_id] = 0
                except Exception as e:
                    logger.error(f"Error sending GIF to channel {chat_id}: {str(e)}")
        except Exception as e:
            logger.error(f"Error in send_price_update: {str(e)}")
    else:
        error_msg = price_data
        logger.error(f"Sending error to {chat_id}: {error_msg}")
        try:
            await context.bot.send_message(chat_id=int(chat_id), text=error_msg, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Error sending error message to {chat_id}: {str(e)}")

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

# Функция для вычисления времени первого запуска (в MSK)
def calculate_first_run_time(interval_hours, timezone_offset_hours):
    now = datetime.now()
    utc_now = now - timedelta(hours=timezone_offset_hours)  # MSK = UTC+3
    next_run = utc_now.replace(minute=0, second=0, microsecond=0)
    while next_run <= utc_now:
        next_run += timedelta(hours=interval_hours)
    return (next_run - utc_now).total_seconds()

async def main():
    logger.info(f"Starting bot with Python {sys.version} and python-telegram-bot 21.4")
    token = "7376596629:AAEWq1wQY03ColQcciuXxa7FmCkxQ4MUs7E"
    tonapi_key = os.getenv("TONAPI_KEY")
    if not tonapi_key:
        logger.error("TONAPI_KEY is not set. Bot may fail to fetch prices.")
    
    # Проверяем и удаляем webhook перед началом polling
    await check_and_delete_webhook(token)
    
    application = Application.builder().token(token).build()
    await application.initialize()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("price", price))
    application.add_handler(CallbackQueryHandler(button))
    application.add_handler(MessageHandler(filters.ALL, handle_message))
    if application.job_queue is None:
        logger.error("Error: job_queue is None")
        return
    
    # Сбор цен каждые 15 минут
    application.job_queue.run_repeating(collect_price_data, interval=900, first=0)
    # Цены каждые 5 минут
    application.job_queue.run_repeating(send_price_update, interval=300, first=0)
    # Отчет каждые 4 часа (00:00, 04:00, 08:00, 12:00, 16:00, 20:00 MSK)
    application.job_queue.run_repeating(
        send_four_hour_report,
        interval=14400,
        first=calculate_first_run_time(4, 3)  # MSK = UTC+3
    )
    # Объем каждый час в 00 минут
    application.job_queue.run_repeating(
        send_volume_update,
        interval=3600,
        first=calculate_first_run_time(1, 3)  # MSK = UTC+3
    )
    
    wsgi_thread = Thread(target=run_wsgi, daemon=True)
    wsgi_thread.start()
    try:
        await application.start()
        await application.updater.start_polling(allowed_updates=Update.ALL_TYPES)
        await asyncio.Event().wait()
    except Exception as e:
        logger.error(f"Error in run_polling: {str(e)}")
        raise
    finally:
        await application.updater.stop()
        await application.stop()
        await application.shutdown()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        logger.error(f"Error in main: {str(e)}")