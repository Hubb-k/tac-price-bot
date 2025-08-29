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

# Настройка логирования
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Простой WSGI-эндпоинт для Render
def simple_wsgi_app(environ, start_response):
    status = '200 OK'
    headers = [('Content-type', 'text/plain; charset=utf-8')]
    start_response(status, headers)
    return [b"Bot is running"]

# Адрес Jetton-контракта $TAC
JETTON_ADDRESS = "EQBE_gBrU3mPI9hHjlJoR_kYyrhQgyCFD6EUWfa42W8T7EBP"

# Счетчик сообщений для каждого чата
message_counters = {}

# Хранилище для истории цен (в USD)
price_history = []

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
    if tonapi_key:
        headers["Authorization"] = f"Bearer {tonapi_key}"
        logger.info(f"Using TONAPI_KEY: {tonapi_key[:5]}...")
    else:
        logger.error("TONAPI_KEY not set")
    try:
        response = requests.get(url, headers=headers)
        logger.info(f"TonAPI response status: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            logger.info(f"TonAPI response: {data}")
            rates = data['rates'][JETTON_ADDRESS]['prices']
            usd_price = rates.get('USD', 'N/A')
            ton_price = rates.get('TON', 'N/A')
            usd_str = f"{float(usd_price):.4f}" if usd_price != 'N/A' else 'N/A'
            ton_str = f"{float(ton_price):.4f}" if ton_price != 'N/A' else 'N/A'
            return {
                'usd': float(usd_price) if usd_price != 'N/A' else None,
                'ton': float(ton_price) if ton_price != 'N/A' else None,
                'usd_str': usd_str,
                'ton_str': ton_str
            }
        else:
            error_msg = f"TonAPI Error: Code {response.status_code}"
            logger.error(error_msg)
            return error_msg
    except Exception as e:
        error_msg = f"Error in get_tac_price: {str(e)}"
        logger.error(error_msg)
        return error_msg

# Функция для сбора цен каждые 10 минут
async def collect_price_data(context: ContextTypes.DEFAULT_TYPE) -> None:
    global price_history  # Переносим global в начало функции
    price_data = get_tac_price()
    if isinstance(price_data, dict) and price_data['usd'] is not None:
        timestamp = datetime.now()
        price_history.append({'timestamp': timestamp, 'usd': price_data['usd']})
        # Удаляем данные старше 4 часов
        four_hours_ago = timestamp - timedelta(hours=4)
        price_history = [entry for entry in price_history if entry['timestamp'] > four_hours_ago]
        logger.info(f"Collected price: ${price_data['usd']:.4f}, history size: {len(price_history)}")
    else:
        logger.error("Failed to collect price data")

# Функция для создания отчета каждые 4 часа
async def send_four_hour_report(context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = "-1002954606074"
    price_data = get_tac_price()
    if not isinstance(price_data, dict) or price_data['usd'] is None:
        logger.error("Failed to fetch current price for report")
        await context.bot.send_message(chat_id=int(chat_id), text="Error: Unable to fetch data for report", parse_mode="HTML")
        return

    # Volume (заглушка, так как TonAPI не дает объем)
    volume = "N/A"

    # Price Change in %
    four_hours_ago = datetime.now() - timedelta(hours=4)
    past_prices = [entry['usd'] for entry in price_history if entry['timestamp'] > four_hours_ago]
    if past_prices and len(past_prices) > 1:
        oldest_price = past_prices[0]
        current_price = price_data['usd']
        price_change_percent = ((current_price - oldest_price) / oldest_price * 100) if oldest_price != 0 else 0
        price_change_str = f"{price_change_percent:+.2f}%"
    else:
        price_change_str = "N/A (insufficient data)"

    # Maximum and Minimum Price
    max_price = max(past_prices) if past_prices else price_data['usd']
    min_price = min(past_prices) if past_prices else price_data['usd']
    max_price_str = f"${max_price:.4f}" if max_price is not None else "N/A"
    min_price_str = f"${min_price:.4f}" if min_price is not None else "N/A"

    # Формируем сообщение на английском
    report_message = (
        f"<b>📊 4-Hour Report:</b>\n"
        f"<b>📈 Volume:</b> {volume}\n"
        f"<b>📉 Price Change:</b> {price_change_str}\n"
        f"<b>🔺 Maximum Price:</b> {max_price_str}\n"
        f"<b>🔻 Minimum Price:</b> {min_price_str}"
    )

    # Отправляем сообщение
    try:
        await context.bot.send_message(chat_id=int(chat_id), text=report_message, parse_mode="HTML")
        logger.info(f"Sent 4-hour report to {chat_id}: {report_message}")
        
        # Увеличиваем счетчик сообщений
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
    price_message = get_tac_price()
    if isinstance(price_message, str):
        logger.info(f"Sending price to {update.message.chat_id}: {price_message}")
        keyboard = [[InlineKeyboardButton("Refresh Price", callback_data="price")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(price_message, reply_markup=reply_markup, parse_mode="HTML")
    else:
        error_msg = "Error: Unable to fetch price"
        logger.error(f"Sending error to {update.message.chat_id}: {error_msg}")
        await update.message.reply_text(error_msg, parse_mode="HTML")

# Обработчик кнопок
async def button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if query.data == "price":
        price_message = get_tac_price()
        if isinstance(price_message, str):
            logger.info(f"Sending price to {query.message.chat_id}: {price_message}")
            keyboard = [[InlineKeyboardButton("Refresh Price", callback_data="price")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.message.reply_text(price_message, reply_markup=reply_markup, parse_mode="HTML")
        else:
            error_msg = "Error: Unable to fetch price"
            logger.error(f"Sending error to {query.message.chat_id}: {error_msg}")
            await query.message.reply_text(error_msg, parse_mode="HTML")
    elif query.data == "help":
        await query.message.reply_text("I'm a bot for tracking $TAC price. Use /price or the 'Get Price' button.")

# Автоматическое обновление цены
async def send_price_update(context: ContextTypes.DEFAULT_TYPE) -> None:
    price_message = get_tac_price()
    chat_id = "-1002954606074"
    if isinstance(price_message, str):
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
        error_msg = "Error: Unable to fetch price"
        logger.error(f"Sending error to {chat_id}: {error_msg}")
        try:
            await context.bot.send_message(chat_id=int(chat_id), text=error_msg, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Error sending error message to {chat_id}: {str(e)}")

def run_wsgi():
    port = int(os.getenv("PORT", 8080))
    logger.info(f"Starting WSGI server on port {port}")
    server = make_server('0.0.0.0', port, simple_wsgi_app)
    server.serve_forever()

async def main():
    logger.info(f"Starting bot with Python {sys.version} and python-telegram-bot 21.4")
    application = Application.builder().token("7376596629:AAEWq1wQY03ColQcciuXxa7FmCkxQ4MUs7E").build()
    await application.initialize()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("price", price))
    application.add_handler(CallbackQueryHandler(button))
    application.add_handler(MessageHandler(filters.ALL, handle_message))
    if application.job_queue is None:
        logger.error("Error: job_queue is None")
        return
    application.job_queue.run_repeating(collect_price_data, interval=600, first=0)  # Сбор цен каждые 10 минут
    application.job_queue.run_repeating(send_price_update, interval=180, first=0)  # Цены каждые 3 минуты
    application.job_queue.run_repeating(send_four_hour_report, interval=14400, first=0)  # Отчет каждые 4 часа
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