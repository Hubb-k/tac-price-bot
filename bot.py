import os
import requests
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters
from datetime import datetime, timedelta
import random

# Адрес Jetton-контракта $TAC и пула на DexScreener
JETTON_ADDRESS = "EQBE_gBrU3mPI9hHjlJoR_kYyrhQgyCFD6EUWfa42W8T7EBP"
POOL_ADDRESS = "EQBp8y9u4gYmVLCiG4CVZw9Ir3IDV5a9xoAxG3Du7xrwFFmP"

# Счетчик сообщений для GIF
message_counters = {}

# Хранилище для истории цен
price_history = []

# Список URL-адресов GIF
GIF_URLS = [
    "https://media.giphy.com/media/83JLhFcYedwQBR0oW5/giphy.mp4",
    "https://media.giphy.com/media/nZW5fIzaIJVXddVla7/giphy.mp4",
    "https://media.giphy.com/media/KNeeNrAQQqt0v8jvf9/giphy.mp4"
]

# Получение цены из TonAPI
def get_tac_price():
    url = f"https://tonapi.io/v2/rates?tokens={JETTON_ADDRESS}&currencies=ton,usd"
    headers = {"Authorization": f"Bearer {os.getenv('TONAPI_KEY')}"}
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            data = response.json()
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
        return "Error: Unable to fetch price"
    except:
        return "Error: Unable to fetch price"

# Получение объема из DexScreener
def get_tac_volume():
    try:
        url = f"https://api.dexscreener.com/latest/dex/pairs/ton/{POOL_ADDRESS}"
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            return float(data['pair']['volume']['h24'])
        return None
    except:
        return None

# Удаление webhook перед запуском
async def delete_webhook(token: str):
    try:
        response = requests.get(f"https://api.telegram.org/bot{token}/deleteWebhook")
        data = response.json()
        if data.get("ok"):
            print("Webhook deleted successfully")
        else:
            print(f"Failed to delete webhook: {data}")
    except Exception as e:
        print(f"Error deleting webhook: {str(e)}")

# Сбор цен каждые 15 минут
async def collect_price_data(context: ContextTypes.DEFAULT_TYPE) -> None:
    global price_history
    price_data = get_tac_price()
    if isinstance(price_data, dict) and price_data['usd'] is not None:
        price_history.append({'timestamp': datetime.now(), 'usd': price_data['usd']})
        price_history = [entry for entry in price_history if entry['timestamp'] > datetime.now() - timedelta(hours=4)]

# Отправка цен каждые 5 минут
async def send_price_update(context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = "-1002954606074"
    price_data = get_tac_price()
    message = price_data['message'] if isinstance(price_data, dict) else price_data
    await context.bot.send_message(chat_id=chat_id, text=message, parse_mode="HTML")
    message_counters[chat_id] = message_counters.get(chat_id, 0) + 1
    if message_counters[chat_id] >= 10:
        await context.bot.send_animation(chat_id=chat_id, animation=random.choice(GIF_URLS))
        message_counters[chat_id] = 0

# Отправка объема каждый час
async def send_volume_update(context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = "-1002954606074"
    volume = get_tac_volume()
    volume_str = f"{volume:,.2f}" if volume is not None else "N/A"
    message = f"<b>Volume (24h): ${volume_str}</b>"
    await context.bot.send_message(chat_id=chat_id, text=message, parse_mode="HTML")
    message_counters[chat_id] = message_counters.get(chat_id, 0) + 1
    if message_counters[chat_id] >= 10:
        await context.bot.send_animation(chat_id=chat_id, animation=random.choice(GIF_URLS))
        message_counters[chat_id] = 0

# 4-часовой отчет
async def send_four_hour_report(context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = "-1002954606074"
    price_data = get_tac_price()
    if not isinstance(price_data, dict) or price_data['usd'] is None:
        await context.bot.send_message(chat_id=chat_id, text="Error: Unable to fetch data for report", parse_mode="HTML")
        return

    past_prices = [entry['usd'] for entry in price_history if entry['timestamp'] > datetime.now() - timedelta(hours=4)]
    if past_prices and len(past_prices) > 1:
        oldest_price = past_prices[0]
        current_price = price_data['usd']
        price_change_str = f"{((current_price - oldest_price) / oldest_price * 100):+.2f}%" if oldest_price != 0 else "N/A"
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
    await context.bot.send_message(chat_id=chat_id, text=report_message, parse_mode="HTML")
    message_counters[chat_id] = message_counters.get(chat_id, 0) + 1
    if message_counters[chat_id] >= 10:
        await context.bot.send_animation(chat_id=chat_id, animation=random.choice(GIF_URLS))
        message_counters[chat_id] = 0

# Обработчик сообщений для GIF
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.message.chat_id
    message_counters[chat_id] = message_counters.get(chat_id, 0) + 1
    if message_counters[chat_id] >= 10:
        await context.bot.send_animation(chat_id=chat_id, animation=random.choice(GIF_URLS))
        message_counters[chat_id] = 0

# Команда /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    keyboard = [
        [InlineKeyboardButton("Get Price", callback_data="price")],
        [InlineKeyboardButton("Help", callback_data="help")]
    ]
    await update.message.reply_text(
        "Hello! I'm a $TAC price bot. Click below:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# Команда /price
async def price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    price_data = get_tac_price()
    message = price_data['message'] if isinstance(price_data, dict) else price_data
    keyboard = [[InlineKeyboardButton("Refresh Price", callback_data="price")]]
    await update.message.reply_text(message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

# Обработчик кнопок
async def button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if query.data == "price":
        price_data = get_tac_price()
        message = price_data['message'] if isinstance(price_data, dict) else price_data
        keyboard = [[InlineKeyboardButton("Refresh Price", callback_data="price")]]
        await query.message.reply_text(message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
    elif query.data == "help":
        await query.message.reply_text("Use /price or 'Get Price' to check $TAC price.")

# Основная функция
async def main():
    token = "7376596629:AAEWq1wQY03ColQcciuXxa7FmCkxQ4MUs7E"
    # Удаляем webhook перед запуском
    await delete_webhook(token)
    application = Application.builder().token(token).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("price", price))
    application.add_handler(CallbackQueryHandler(button))
    application.add_handler(MessageHandler(filters.ALL, handle_message))

    # Расписание задач
    application.job_queue.run_repeating(collect_price_data, interval=900, first=0)  # Сбор цен каждые 15 минут
    application.job_queue.run_repeating(send_price_update, interval=300, first=0)  # Цены каждые 5 минут
    application.job_queue.run_repeating(
        send_four_hour_report,
        interval=14400,
        first=(datetime.now().replace(minute=0, second=0, microsecond=0) + timedelta(hours=4 - (datetime.now().hour % 4))).timestamp() - datetime.now().timestamp()
    )  # Отчет каждые 4 часа MSK
    application.job_queue.run_repeating(
        send_volume_update,
        interval=3600,
        first=(datetime.now().replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)).timestamp() - datetime.now().timestamp()
    )  # Объем каждый час MSK

    # Запуск в существующем цикле событий
    await application.initialize()
    await application.start()
    await application.updater.start_polling(allowed_updates=Update.ALL_TYPES)
    await asyncio.Event().wait()  # Держим приложение активным

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())