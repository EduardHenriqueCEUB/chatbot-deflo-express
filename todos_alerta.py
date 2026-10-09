"""
Avisa o celular do atendente quando um cliente quer falar com alguém.

Como o alerta chega no celular?
  Usamos um bot do TELEGRAM. É gratuito, e o Telegram mostra uma notificação
  no celular como qualquer mensagem. Basta:
    1. criar um bot no Telegram (conversando com o @BotFather) -> ele te dá um TOKEN;
    2. mandar um "oi" para o seu bot pelo celular do atendente;
    3. rodar  python descobrir_chat_id.py  para descobrir o CHAT_ID;
    4. colocar TOKEN e CHAT_ID no arquivo .env.

  Enviar a mensagem é só uma requisição HTTP para a API do Telegram.

Se o Telegram ainda não estiver configurado, o alerta aparece no terminal (útil para testar no simulador).
"""
import requests

import todos_config as config


def enviar_alerta(texto):
    """Envia o alerta. Nunca derruba o chatbot: se der erro, só registra no terminal."""
    if not config.TELEGRAM_TOKEN or not config.TELEGRAM_CHAT_ID:
        print("\n🔔 [ALERTA SIMULADO — Telegram não configurado]\n" + texto + "\n")
        return False

    url = f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}/sendMessage"
    try:
        resposta = requests.post(url, data={"chat_id": config.TELEGRAM_CHAT_ID, "text": texto}, timeout=10)
        resposta.raise_for_status()
        return True
    except requests.RequestException as erro:
        print(f"[ERRO] Não consegui enviar o alerta pelo Telegram: {erro}")
        return False
