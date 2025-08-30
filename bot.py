import os
import requests
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters
from datetime import datetime, timedelta
import random
import logging
import pytz
try:
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
except ImportError as e:
    logging.error(f"Ошибка импорта urllib3: {e}")
    raise

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

JETTON_ADDRESS = "EQBE_gBrU3mPI9hHjlJoR_kYyrhQgyCFD6EUWfa42W8T7EBP"
POOL_ADDRESS = "EQBp8y9u4gYmVLCiG4CVZw9Ir3IDV5a9xoAxG3Du7xrwFFmP"  # Сохранен для справки
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
    if not os.getenv('TONAPI_KEY'):
        logging.error("TONAPI_KEY не установлен")
        return "Error: TONAPI_KEY not set"
    url = f"https://tonapi.io/v2/rates?tokens={JETTON_ADDRESS}&currencies=ton,usd"
    headers = {"Authorization": f"Bearer {os.getenv('TONAPI_KEY')}"}
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
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
    except Exception as e:
        logging.error(f"Ошибка в get_tac_price: {e}")
        return "Error: Unable to fetch price"

def get_ton_usd_price():
    if not os.getenv('TONAPI_KEY'):
        logging.error("TONAPI_KEY не установлен")
        return None
    url = "https://tonapi.io/v2/rates?tokens=ton&currencies=usd"
    headers = {"Authorization": f"Bearer {os.getenv('TONAPI_KEY')}"}
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        return float(data['rates']['TON']['prices']['USD'])
    except Exception as e:
        logging.error(f"Ошибка в get_ton_usd_price: {e}")
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
        logging.info(f"Запрос к STON.fi API: {url} with params {payload}")
        response = session.get(url, params=payload, timeout=15)
        response.raise_for_status()
        data = response.json()
        logging.info(f"Ответ API: {data}")
        stats = data.get('stats', [])
        for jetton in stats:
            # Логируем каждый пул для отладки
            logging.info(f"Проверяемый пул: {jetton}")
            if (jetton.get('base_address') == JETTON_ADDRESS or 
                jetton.get('quote_address') == JETTON_ADDRESS or 
                ('url' in jetton and JETTON_ADDRESS in jetton['url'])) and jetton.get('quote_symbol') == 'TON':
                volume_ton = float(jetton['quote_volume'])
                ton_usd = get_ton_usd_price()
                if ton_usd is not None:
                    volume_usd = volume_ton * ton_usd
                    logging.info(f"Объем за 24 часа: ${volume_usd:,.2f}")
                    return volume_usd
                else:
                    logging.warning("Не удалось получить цену TON/USD для конвертации объема")
                    return None
        logging.warning("Пул для $TAC не найден в ответе API")
        return None
    except requests.exceptions.RequestException as e:
        logging.error(f"Ошибка при запросе к STON.fi API: {e}")
        return None
    except ValueError as e:
        logging.error(f"Ошибка при разборе JSON: {e}")
        return None
    except Exception as e:
        logging.error(f"Неизвестная ошибка в get_tac_volume: {e}")
        return None

async def delete_webhook(token: str):
    try:
        response = requests.get(f"https://api.telegram.org/bot{token}/deleteWebhook")
        data = response.json()
        if data.get("ok"):
            logging.info("Webhook успешно удален")
        else:
            logging.error(f"Не удалось удалить webhook: {data}")
    except Exception as e:
        logging.error(f"Ошибка при удалении webhook: {e}")

async def collect_price_data(context: ContextTypes.DEFAULT_TYPE) -> None:
    global price_history
    price_data = get_tac_price()
    if isinstance(price_data, dict) and price_data['usd'] is not None:
        price_history.append({'timestamp': get_msk_time(), 'usd': price_data['usd']})
        logging.info(f"Добавлена цена: ${price_data['usd']:.4f}, price_history size: {len(price_history)}")
        price_history = [entry for entry in price_history if entry['timestamp'] > get_msk_time() - timedelta(hours=4)]
    else:
        logging.warning(f"Не удалось добавить цену: {price_data}")

async def send_price_update(context: ContextTypes.DEFAULT_TYPE) -> None:
    logging.info("Запуск send_price_update")
    chat_id = "-1002954606074"
    price_data = get_tac_price()
    message = price_data['message'] if isinstance(price_data, dict) else price_data
    await context.bot.send_message(chat_id=chat_id, text=message, parse_mode="HTML")
    message_counters[chat_id] = message_counters.get(chat_id, 0) + 1
    if message_counters[chat_id] >= 10:
        await context.bot.send_animation(chat_id=chat_id, animation=random.choice(GIF_URLS))
        message_counters[chat_id] = 0

async def send_volume_update(context: ContextTypes.DEFAULT_TYPE) -> None:
    logging.info("Запуск send_volume_update")
    chat_id = "-1002954606074"
    volume = get_tac_volume()
    if volume is not None:
        volume_str = f"{volume:,.2f}"
        message = f"<b>Volume (24h): ${volume_str}</b> (MSK: {get_msk_time().strftime('%H:%M')})"
    else:
        message = f"<b>Volume (24h): N/A (failed to fetch data)</b> (MSK: {get_msk_time().strftime('%H:%M')})"
        logging.warning("Не удалось получить данные об объеме")
        admin_chat_id = "YOUR_ADMIN_CHAT_ID"  # Замените на ваш chat_id
        await context.bot.send_message(
            chat_id=admin_chat_id,
            text=f"Ошибка: Не удалось получить данные об объеме от STON.fi",
            parse_mode="HTML"
        )
    await context.bot.send_message(chat_id=chat_id, text=message, parse_mode="HTML")
    message_counters[chat_id] = message_counters.get(chat_id, 0) + 1
    if message_counters[chat_id] >= 10:
        await context.bot.send_animation(chat_id=chat_id, animation=random.choice(GIF_URLS))
        message_counters[chat_id] = 0

async def send_four_hour_report(context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = "-1002954606074"
    price_data = get_tac_price()
    if not isinstance(price_data, dict) or price_data['usd'] is None:
        await context.bot.send_message(chat_id=chat_id, text="Error: Unable to fetch data for report", parse_mode="HTML")
        return

    past_prices = [entry['usd'] for entry in price_history if entry['timestamp'] > get_msk_time() - timedelta(hours=4)]
    logging.info(f"past_prices: {past_prices}, price_history size: {len(price_history)}")
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

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.message.chat_id
    message_counters[chat_id] = message_counters.get(chat_id, 0) + 1
    if message_counters[chat_id] >= 10:
        await context.bot.send_animation(chat_id=chat_id, animation=random.choice(GIF_URLS))
        message_counters[chat_id] = 0

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    keyboard = [
        [InlineKeyboardButton("Get Price", callback_data="price")],
        [InlineKeyboardButton("Help", callback_data="help")]
    ]
    await update.message.reply_text(
        "Hello! I'm a $TAC price bot. Click below:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    price_data = get_tac_price()
    message = price_data['message'] if isinstance(price_data, dict) else price_data
    keyboard = [[InlineKeyboardButton("Refresh Price", callback_data="price")]]
    await update.message.reply_text(message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

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

async def main():
    try:
        token = "7376596629:AAEWq1wQY03ColQcciuXxa7FmCkxQ4MUs7E"
        await delete_webhook(token)
        application = Application.builder().token(token).build()
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("price", price))
        application.add_handler(CallbackQueryHandler(button))
        application.add_handler(MessageHandler(filters.ALL, handle_message))

        logging.info("Добавление задач в планировщик...")
        application.job_queue.run_repeating(collect_price_data, interval=900, first=10)
        application.job_queue.run_repeating(send_price_update, interval=300, first=10)  # Каждые 5 минут
        application.job_queue.run_repeating(send_four_hour_report, interval=14400, first=10)
        application.job_queue.run_repeating(send_volume_update, interval=3600, first=10)
        logging.info("Задачи добавлены в планировщик")

        await application.initialize()
        await application.start()
        await application.updater.start_polling(allowed_updates=Update.ALL_TYPES)
        await asyncio.Event().wait()
    except Exception as e:
        logging.error(f"Критическая ошибка в main: {e}", exc_info=True)
        raise

if __name__ == "__main__":
    try:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(main())
    except Exception as e:
        logging.error(f"Ошибка при запуске приложения: {e}", exc_info=True)
        raise