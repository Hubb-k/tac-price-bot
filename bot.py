import os
import requests
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters
from datetime import datetime, timedelta
import random
import logging
import pytz

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

JETTON_ADDRESS = "EQBE_gBrU3mPI9hHjlJoR_kYyrhQgyCFD6EUWfa42W8T7EBP"
POOL_ADDRESS = "EQBp8y9u4gYmVLCiG4CVZw9Ir3IDV5a9xoAxG3Du7xrwFFmP"  # Не используется напрямую, но сохранен для справки
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
    from datetime import datetime, timedelta
    try:
        since = (datetime.utcnow() - timedelta(days=1)).isoformat(timespec='seconds')
        until = datetime.utcnow().isoformat(timespec='seconds')
        payload = {'since': since, 'until': until}
        url = "https://api.ston.fi/v1/stats/pool"
        logging.info(f"Запрос к STON.fi API: {url} with params {payload}")
        response = requests.get(url, params=payload, timeout=15)
        response.raise_for_status()
        data = response.json()
        logging.info(f"Ответ API: {data}")
        stats = data.get('stats', [])
        for jetton in stats:
            # Фильтр по JETTON_ADDRESS в 'url' или 'base_address' (если есть); предполагаем 'url' содержит JETTON_ADDRESS
            if 'url' in jetton and JETTON_ADDRESS in jetton['url'] and jetton.get('quote_symbol') == 'TON':
                volume_ton = float(jetton['quote_volume'])
                ton_usd = get_ton_usd_price()
                if ton_usd is not None:
                    volume_usd = volume_ton * ton_usd
                    logging.info(f"Объем за 24 часа: ${volume_usd:,.2f}")
                    return volume_usd
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

# Остальной код остается без изменений (delete_webhook, collect_price_data, send_price_update, send_volume_update и т.д.)
# ...

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
    await context.bot.send_message(chat_id=chat_id, text=message, parse_mode="HTML")
    message_counters[chat_id] = message_counters.get(chat_id, 0) + 1
    if message_counters[chat_id] >= 10:
        await context.bot.send_animation(chat_id=chat_id, animation=random.choice(GIF_URLS))
        message_counters[chat_id] = 0

# ... (остальной код main и другие функции без изменений)