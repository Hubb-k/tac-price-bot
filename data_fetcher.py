import os
import requests
from config import JETTON_ADDRESS, ADMIN_CHAT_ID

def get_token_data():
    url = f"https://tonapi.io/v2/rates?tokens={JETTON_ADDRESS}&currencies=ton,usd"
    headers = {"Authorization": f"Bearer {os.getenv('TONAPI_KEY')}"}
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if 'rates' not in data or JETTON_ADDRESS not in data['rates']:
                return "Error: Invalid TonAPI response"
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
        return f"Error: TonAPI returned {response.status_code}"
    except Exception:
        try:
            requests.get(f"https://api.telegram.org/bot7376596629:AAEWq1wQY03ColQcciuXxa7FmCkxQ4MUs7E/sendMessage?chat_id={ADMIN_CHAT_ID}&text=Error:%20Failed%20to%20fetch%20price")
        except Exception:
            pass
        return "Error: Failed to fetch price"