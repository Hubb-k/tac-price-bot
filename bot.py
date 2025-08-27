import requests
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# Адрес Jetton-контракта $TAC
JETTON_ADDRESS = "EQBE_gBrU3mPI9hHjlJoR_kYyrhQgyCFD6EUWfa42W8T7EBP"

# Функция для получения цены из TonAPI
def get_tac_price():
    url = f"https://tonapi.io/v2/rates?tokens={JETTON_ADDRESS}&currencies=ton,usd"
    try:
        response = requests.get(url)
        if response.status_code == 200:
            data = response.json()
            rates = data['rates'][JETTON_ADDRESS]['prices']
            usd_price = rates.get('USD', 'N/A')
            ton_price = rates.get('TON', 'N/A')
            return f"$TAC Price:\nUSD: ${usd_price}\nTON: {ton_price} TON"
        else:
            return "Ошибка: Не удалось получить цену."
    except Exception as e:
        return f"Ошибка: {str(e)}"

# Команда /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Привет! Я бот цены $TAC. Отправляю обновления каждую минуту.\nТвой chat_id: " + str(update.message.chat_id))

# Команда /price
async def price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    price_message = get_tac_price()
    await update.message.reply_text(price_message)

# Автоматическое обновление цены
async def send_price_update(context: ContextTypes.DEFAULT_TYPE) -> None:
    price_message = get_tac_price()
    chat_id = "YOUR_CHAT_ID"  # Вставь сюда chat_id
    await context.bot.send_message(chat_id=chat_id, text=price_message)

def main() -> None:
    # Вставь свой токен бота
    application = Application.builder().token(7376596629:AAEWq1wQY03ColQcciuXxa7FmCkxQ4MUs7E).build()

    # Обработчики команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("price", price))

    # Обновление каждые 60 секунд
    application.job_queue.run_repeating(send_price_update, interval=60, first=0)

    # Запуск бота
    application.run_polling()

if __name__ == "__main__":
    main()
