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

# Список рабочих URL-адресов GIF
GIF_URLS = [
    "https://media4.giphy.com/media/v1.Y2lkPTZjMDliOTUybWZuczh5b285dmhhYTNzZjZzZXVvb3M1NnYydW92MnJmMjZnaWN1cyZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/83JLhFcYedwQBR0oW5/giphy.gif",  # туземун
    "https://media1.giphy.com/media/v1.Y2lkPTZjMDliOTUyYTZodGp6YWQ0eHJpZWtnNjBkNW51b2FhaHE5d3Q1MHB3cGJuOHB6eSZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/nZW5fIzaIJVXddVla7/giphy.gif",  # Танцующий кот
    https://giphy.com/gifs/subpoprecords-breakfast-clowns-tv-priest-KNeeNrAQQqt0v8jvf9",  # Клоун
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
            return (
                f"<b>🌸 $TAC Price:</b>\n"  # Розовый (имитация эмодзи 🌸)
                f"<b>💚 USD: ${usd_str}</b>\n"  # Зеленый (имитация эмодзи 💚)
                f"<b>🔵 TON: {ton_str} TON</b>"  # Синий (имитация эмодзи 🔵)
            )
        else:
            error_msg = f"Ошибка TonAPI: Код {response.status_code}"
            logger.error(error_msg)
            return error_msg
    except Exception as e:
        error_msg = f"Ошибка в get_tac_price: {str(e)}"
        logger.error(error_msg)
        return error_msg

# Обработчик всех сообщений для подсчета и отправки GIF
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.message.chat_id
    # Увеличиваем счетчик сообщений для данного чата
    message_counters[chat_id] = message_counters.get(chat_id, 0) + 1
    logger.info(f"Message count for chat {chat_id}: {message_counters[chat_id]}")
    
    # Проверяем, достиг ли счетчик 10
    if message_counters[chat_id] >= 10:
        # Выбираем случайную GIF
        gif_url = random.choice(GIF_URLS)
        try:
            await context.bot.send_animation(chat_id=chat_id, animation=gif_url)
            logger.info(f"Sent GIF to chat {chat_id}: {gif_url}")
            # Сбрасываем счетчик
            message_counters[chat_id] = 0
        except Exception as e:
            logger.error(f"Ошибка при отправке GIF в чат {chat_id}: {str(e)}")

# Команда /start с кнопками
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    keyboard = [
        [InlineKeyboardButton("Получить цену", callback_data="price")],
        [InlineKeyboardButton("Помощь", callback_data="help")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        f"Привет! Я бот цены $TAC. Нажми кнопку ниже:\nТвой chat_id: {update.message.chat_id}",
        reply_markup=reply_markup
    )

# Команда /price
async def price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    price_message = get_tac_price()
    logger.info(f"Sending price to {update.message.chat_id}: {price_message}")
    keyboard = [[InlineKeyboardButton("Обновить цену", callback_data="price")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(price_message, reply_markup=reply_markup, parse_mode="HTML")

# Обработчик кнопок
async def button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if query.data == "price":
        price_message = get_tac_price()
        logger.info(f"Sending price to {query.message.chat_id}: {price_message}")
        keyboard = [[InlineKeyboardButton("Обновить цену", callback_data="price")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.reply_text(price_message, reply_markup=reply_markup, parse_mode="HTML")
    elif query.data == "help":
        await query.message.reply_text("Я бот для отслеживания цены $TAC. Используй /price или кнопку 'Получить цену'.")

# Автоматическое обновление цены
async def send_price_update(context: ContextTypes.DEFAULT_TYPE) -> None:
    price_message = get_tac_price()
    chat_id = "-1002954606074"  # Твой chat_id канала
    logger.info(f"Sending auto-update to {chat_id}: {price_message}")
    try:
        await context.bot.send_message(chat_id=int(chat_id), text=price_message, parse_mode="HTML")
        # Увеличиваем счетчик сообщений для канала
        message_counters[chat_id] = message_counters.get(chat_id, 0) + 1
        if message_counters[chat_id] >= 10:
            gif_url = random.choice(GIF_URLS)
            await context.bot.send_animation(chat_id=int(chat_id), animation=gif_url)
            logger.info(f"Sent GIF to channel {chat_id}: {gif_url}")
            message_counters[chat_id] = 0
    except Exception as e:
        logger.error(f"Ошибка в send_price_update: {str(e)}")

def run_wsgi():
    port = int(os.getenv("PORT", 8080))
    logger.info(f"Starting WSGI server on port {port}")
    server = make_server('0.0.0.0', port, simple_wsgi_app)
    server.serve_forever()

async def main():
    logger.info(f"Starting bot with Python {sys.version} and python-telegram-bot 21.4")
    application = Application.builder().token("7376596629:AAEWq1wQY03ColQcciuXxa7FmCkxQ4MUs7E").build()
    # Инициализируем приложение
    await application.initialize()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("price", price))
    application.add_handler(CallbackQueryHandler(button))
    application.add_handler(MessageHandler(filters.ALL, handle_message))  # Новый обработчик сообщений
    # Проверяем, что job_queue доступен
    if application.job_queue is None:
        logger.error("Error: job_queue is None")
        return
    application.job_queue.run_repeating(send_price_update, interval=180, first=0)
    # Запускаем WSGI в отдельном потоке
    wsgi_thread = Thread(target=run_wsgi, daemon=True)
    wsgi_thread.start()
    # Запускаем polling
    try:
        await application.start()
        await application.updater.start_polling(allowed_updates=Update.ALL_TYPES)
        # Держим приложение активным
        await asyncio.Event().wait()  # Бесконечное ожидание
    except Exception as e:
        logger.error(f"Error in run_polling: {str(e)}")
        raise
    finally:
        # Корректно завершаем приложение
        await application.updater.stop()
        await application.stop()
        await application.shutdown()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        logger.error(f"Error in main: {str(e)}")