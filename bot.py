import sys
import os
import requests
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

JETTON_ADDRESS = "EQBE_gBrU3mPI9hHjlJoR_kYyrhQgyCFD6EUWfa42W8T7EBP"

def get_tac_price():
    url = f"https://tonapi.io/v2/rates?tokens={JETTON_ADDRESS}&currencies=ton,usd"
    headers = {}
    if os.getenv("TONAPI_KEY"):
        headers["Authorization"] = f"Bearer {os.getenv('TONAPI_KEY')}"
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            data = response.json()
            rates = data['rates'][JETTON_ADDRESS]['prices']
            usd_price = rates.get('USD', 'N/A')
            ton_price = rates.get('TON', 'N/A')
            return f"$TAC Price:\nUSD: ${usd_price}\nTON: {ton_price} TON"
        else:
            return f"Ошибка: Не удалось получить цену. Код: {response.status_code}"
    except Exception as e:
        return f"Ошибка: {str(e)}"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(f"Привет! Я бот цены $TAC. Отправляю обновления каждую минуту.\nТвой chat_id: {update.message.chat_id}")

async def price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    price_message = get_tac_price()
    await update.message.reply_text(price_message)

async def send_price_update(context: ContextTypes.DEFAULT_TYPE) -> None:
    price_message = get_tac_price()
    chat_id = "@tacprice"
    await context.bot.send_message(chat_id=int(chat_id), text=price_message)

def main() -> None:
    print(f"Starting bot with Python {sys.version} and python-telegram-bot 21.4")
    application = Application.builder().token("7376596629:AAEWq1wQY03ColQcciuXxa7FmCkxQ4MUs7E").build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("price", price))
    application.job_queue.run_repeating(send_price_update, interval=60, first=0)
    application.run_polling()

if __name__ == "__main__":
    main()