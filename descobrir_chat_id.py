"""
Descobre o CHAT_ID do Telegram do atendente.

Passo a passo:
  1. Coloque o TELEGRAM_TOKEN no arquivo .env
  2. No celular do atendente, abra o seu bot no Telegram e mande "oi"
  3. Rode:  python descobrir_chat_id.py
  4. Copie o número que aparecer para TELEGRAM_CHAT_ID no .env
"""
import requests

import todos_config as config

if not config.TELEGRAM_TOKEN:
    raise SystemExit("Coloque o TELEGRAM_TOKEN no arquivo .env primeiro.")

dados = requests.get(f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}/getUpdates", timeout=10).json()
conversas = {m["message"]["chat"]["id"]: m["message"]["chat"].get("first_name", "")
             for m in dados.get("result", []) if "message" in m}

if not conversas:
    print("Nenhuma mensagem encontrada. Mande um 'oi' para o bot pelo celular e rode de novo.")
for chat_id, nome in conversas.items():
    print(f"CHAT_ID = {chat_id}   ({nome})")
