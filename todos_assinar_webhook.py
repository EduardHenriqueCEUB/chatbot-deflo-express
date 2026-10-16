"""
Diz à Meta para qual servidor mandar as mensagens do WhatsApp.

É a "chave" entre TESTE e PRODUÇÃO:
  A Meta entrega as mensagens do número do bot em UM endereço só.
  - Para testar uma mudança no seu computador, aponte para o ngrok (teste_app.py).
  - Depois de aprovada, aponte de volta para a nuvem (producao_app.py).
  Enquanto estiver apontado para o teste, a produção não recebe mensagens.

Como usar (rode no seu computador, na pasta do projeto):
  Teste:     python todos_assinar_webhook.py ID_DA_CONTA https://SEU-ENDERECO.ngrok-free.dev/webhook
  Produção:  python todos_assinar_webhook.py ID_DA_CONTA https://SEU-SERVICO.onrender.com/webhook

  O ID_DA_CONTA é o "ID da conta do WhatsApp Business", na Etapa 2 do painel
  da Meta. O servidor do endereço precisa estar ligado na hora: a Meta faz um
  "GET /webhook" nele para conferir a senha antes de aceitar.
  Deve aparecer "Assinatura feita com sucesso" e o endereço escolhido.

A senha usada na verificação é a do WHATSAPP_VERIFY_TOKEN do arquivo .env
(e precisa ser a mesma cadastrada no Render).
"""
import sys

import requests

import todos_config as config

if len(sys.argv) != 3:
    raise SystemExit("Uso: python todos_assinar_webhook.py ID_DA_CONTA https://SEU-ENDERECO.ngrok-free.dev/webhook")
if not config.WHATSAPP_TOKEN:
    raise SystemExit("Preencha o WHATSAPP_TOKEN no arquivo .env primeiro.")
if not config.WHATSAPP_VERIFY_TOKEN:
    raise SystemExit("Preencha o WHATSAPP_VERIFY_TOKEN no arquivo .env primeiro.")

waba_id = sys.argv[1].strip()
endereco_bot = sys.argv[2].strip()
if not endereco_bot.startswith("https://") or not endereco_bot.endswith("/webhook"):
    raise SystemExit("O endereço precisa começar com https:// e terminar com /webhook")

url = f"https://graph.facebook.com/{config.GRAPH_API_VERSION}/{waba_id}/subscribed_apps"
cabecalho = {"Authorization": f"Bearer {config.WHATSAPP_TOKEN}"}

# 1) Assina a conta do WhatsApp Business no app, apontando para o endereço do bot.
#    A Meta vai fazer um "GET /webhook" no bot para conferir a senha antes de aceitar.
resposta = requests.post(url, headers=cabecalho, timeout=30, data={
    "override_callback_uri": endereco_bot,
    "verify_token": config.WHATSAPP_VERIFY_TOKEN,
})
if resposta.ok:
    print("Assinatura feita com sucesso.")
else:
    print(f"A Meta recusou a assinatura: {resposta.status_code} {resposta.text}")
    raise SystemExit(1)

# 2) Mostra quais apps estão assinados e para onde a Meta vai mandar as mensagens
lista = requests.get(url, headers=cabecalho, timeout=15).json()
for item in lista.get("data", []):
    app = item.get("whatsapp_business_api_data", {})
    destino = item.get("override_callback_uri", "endereço padrão do app")
    print(f"App assinado: {app.get('name', '?')}  ->  mensagens vão para: {destino}")
