"""
Servidor de TESTE: roda no seu computador, com o ngrok.

Para que serve:
  Testar o bot no WhatsApp de verdade ANTES de mandar qualquer mudança
  para a produção (producao_app.py). Toda alteração no código passa
  primeiro por aqui.

Como rodar:
  Terminal 1:  python -m uvicorn teste_app:app --port 8000
  Terminal 2:  ngrok http 8000 --url https://SEU-ENDERECO.ngrok-free.dev
  Terminal 3:  python todos_assinar_webhook.py ID_DA_CONTA https://SEU-ENDERECO.ngrok-free.dev/webhook
  (o passo do Terminal 3 faz a Meta mandar as mensagens para o teste)

As senhas vêm do arquivo .env do seu computador.

Diferenças em relação à produção (producao_app.py):
  - a conferência de assinatura da Meta é opcional (facilita os primeiros testes);
  - a página de documentação automática (/docs) fica ligada, para estudo.

A lógica do WhatsApp fica em todos_whatsapp.py, compartilhada com a produção.
"""
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse

import todos_whatsapp as whatsapp


@asynccontextmanager
async def ciclo_de_vida(app):
    tarefa = asyncio.create_task(whatsapp.verificar_lembretes_sempre())   # liga junto com o servidor
    yield
    tarefa.cancel()                                                        # desliga quando o servidor para


app = FastAPI(title="Chatbot Deflo Express - TESTE", lifespan=ciclo_de_vida)


@app.get("/")
def status():
    return {"status": "chatbot da Deflo Express no ar", "modo": "teste"}


# A Meta chama este GET uma vez, quando você cadastra o webhook.
@app.get("/webhook", response_class=PlainTextResponse)
def verificar_webhook(request: Request):
    return whatsapp.verificar_webhook(request.query_params)


# A Meta chama este POST toda vez que chega mensagem.
@app.post("/webhook")
async def receber_mensagem(request: Request):
    corpo = await request.body()
    whatsapp.conferir_assinatura(corpo, request.headers.get("X-Hub-Signature-256", ""), obrigatoria=False)
    whatsapp.processar_webhook(await request.json())
    return {"ok": True}
