import sys
import os
import requests
from flask import Flask
from threading import Thread
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

app = Flask(__name__)

# HTTP-эндпоинт для Render
@app.route('/health')
def health():
    return "Bot is running", 200

# Адрес Jetton-контракта $TAC
JETTON_ADDRESS = "EQBE_gBrU3mPI9hHjlJoR_kYyrhQgyCFD6EUWfa42W8T7EBP"

# Функция для получения цены из TonAPI
def get_tac_price():
    url = f"https://tonapi.io/v2/rates?tokens={JETTON_ADDRESS}&currencies=ton,usd"
    headers = {}
    tonapi_key = os.getenv("TONAPI_KEY")
    if tonapi_key:
        headers["Authorization"] = f"Bearer {tonapi_key}"
        print(f"Using TONAPI_KEY: {tonapi_key[:5]}...")
    else:
        print("TONAPI_KEY not set")
    try:
        response = requests.get(url, headers=headers)
        print(f"TonAPI response status: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            print(f"TonAPI response: {data}")
            rates = data['rates'][JETTON_ADDRESS]['prices']
            usd_price = rates.get('USD', 'N/A')
            ton_price = rates.get('TON', 'N/A')
            usd_str = f"{float(usd_price):.4f}" if usd_price != 'N/A' else 'N/A'
            ton_str = f"{float(ton_price):.4f}" if ton_price != 'N/A' else 'N/A'
            return f"$TAC Price:\nUSD: ${usd_str}\nTON: {ton_str} TON"
        else:
            error_msg = f"Ошибка TonAPI: Код {response.status_code}"
            print(error_msg)
            return error_msg
    except Exception as e:
        error_msg = f"Ошибка в get_tac_price: {str(e)}"
        print(error_msg)
        return error_msg

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
    print(f"Sending price to {update.message.chat_id}: {price_message}")
    keyboard = [[InlineKeyboardButton("Обновить цену", callback_data="price")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(price_message, reply_markup=reply_markup)

# Обработчик кнопок
async def button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if query.data == "price":
        price_message = get_tac_price()
        print(f"Sending price to {query.message.chat_id}: {price_message}")
        keyboard = [[InlineKeyboardButton("Обновить цену", callback_data="price")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.reply_text(price_message, reply_markup=reply_markup)
    elif query.data == "help":
        await query.message.reply_text("Я бот для отслеживания цены $TAC. Используй /price или кнопку 'Получить цену'.")

# Автоматическое обновление цены
async def send_price_update(context: ContextTypes.DEFAULT_TYPE) -> None:
    price_message = get_tac_price()
    chat_id = "-1002954606074"  # Замени на твой chat_id канала
    print(f"Sending auto-update to {chat_id}: {price_message}")
    try:
        await context.bot.send_message(chat_id=int(chat_id), text=price_message)
    except Exception as e:
        print(f"Ошибка в send_price_update: {str(e)}")

def run_flask():
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))

def main() -> None:
    print(f"Starting bot with Python {sys.version} and python-telegram-bot 21.4")
    application = Application.builder().token("7376596629:AAEWq1wQY03ColQcciuXxa7FmCkxQ4MUs7E").build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("price", price))
    application.add_handler(CallbackQueryHandler(button))
    application.job_queue.run_repeating(send_price_update, interval=60, first=0)
    # Запускаем Flask в отдельном потоке
    flask_thread = Thread(target=run_flask)
    flask_thread.start()
    application.run_polling()

if __name__ == "__main__":
    main()