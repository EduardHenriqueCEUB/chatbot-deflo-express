"""
Servidor de PRODUÇÃO: roda 24h na nuvem (Render).

Para que serve:
  Deixar o bot no ar o tempo todo, sem depender do seu computador.
  Só recebe mudanças que já foram aprovadas no teste (teste_app.py).

Como roda (comando cadastrado no painel do Render, em "Start Command"):
  uvicorn producao_app:app --host 0.0.0.0 --port $PORT

As senhas NÃO ficam em arquivo: são cadastradas no painel do Render,
em "Environment". O todos_config.py lê do mesmo jeito que lê o .env.

Diferenças em relação ao teste (teste_app.py), todas por segurança:
  - se faltar alguma senha, o servidor nem liga e avisa qual falta;
  - a conferência de assinatura da Meta é obrigatória;
  - a página de documentação automática (/docs) fica desligada, para
    estranhos não verem como o servidor funciona;
  - a página de status aceita HEAD, usado pelo UptimeRobot, que visita
    o bot a cada 5 minutos para o servidor grátis não "dormir".

A lógica do WhatsApp fica em todos_whatsapp.py, compartilhada com o teste.
"""
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse

import todos_config as config
import todos_whatsapp as whatsapp

SENHAS_OBRIGATORIAS = {
    "WHATSAPP_TOKEN": config.WHATSAPP_TOKEN,
    "WHATSAPP_PHONE_NUMBER_ID": config.WHATSAPP_PHONE_NUMBER_ID,
    "WHATSAPP_VERIFY_TOKEN": config.WHATSAPP_VERIFY_TOKEN,
    "WHATSAPP_APP_SECRET": config.WHATSAPP_APP_SECRET,
    "TELEGRAM_TOKEN": config.TELEGRAM_TOKEN,
    "TELEGRAM_CHAT_ID": config.TELEGRAM_CHAT_ID,
}


def _conferir_senhas():
    """Na produção, não dá para funcionar pela metade: falta senha, não liga."""
    faltando = [nome for nome, valor in SENHAS_OBRIGATORIAS.items() if not valor]
    if faltando:
        raise RuntimeError("Cadastre no painel do Render (Environment): " + ", ".join(faltando))


@asynccontextmanager
async def ciclo_de_vida(app):
    _conferir_senhas()
    tarefa = asyncio.create_task(whatsapp.verificar_lembretes_sempre())   # liga junto com o servidor
    yield
    tarefa.cancel()                                                        # desliga quando o servidor para


app = FastAPI(title="Chatbot Deflo Express", lifespan=ciclo_de_vida,
              docs_url=None, redoc_url=None, openapi_url=None)


# GET = navegador; HEAD = UptimeRobot (só confere se o servidor responde)
@app.api_route("/", methods=["GET", "HEAD"])
def status():
    return {"status": "chatbot da Deflo Express no ar"}


# A Meta chama este GET uma vez, quando você cadastra o webhook.
@app.get("/webhook", response_class=PlainTextResponse)
def verificar_webhook(request: Request):
    return whatsapp.verificar_webhook(request.query_params)


# A Meta chama este POST toda vez que chega mensagem.
@app.post("/webhook")
async def receber_mensagem(request: Request):
    corpo = await request.body()
    whatsapp.conferir_assinatura(corpo, request.headers.get("X-Hub-Signature-256", ""), obrigatoria=True)
    whatsapp.processar_webhook(await request.json())
    # A Meta precisa receber 200 rápido, senão ela reenvia a mensagem.
    return {"ok": True}
