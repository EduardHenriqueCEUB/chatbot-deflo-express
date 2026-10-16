"""
Comunicação com o WhatsApp (API oficial da Meta: WhatsApp Cloud API).

Este arquivo é usado pelos DOIS servidores do projeto:
  - teste_app.py     -> TESTE, roda no seu computador com o ngrok
  - producao_app.py  -> PRODUÇÃO, roda 24h na nuvem (Render)

Por que um arquivo compartilhado?
  O teste só prova alguma coisa se a produção usar exatamente o mesmo código.
  Se cada servidor tivesse a sua cópia destas funções, uma correção feita no
  teste poderia não chegar na produção (ou o contrário). Aqui fica tudo num
  lugar só: o que muda entre teste e produção fica no teste_app.py e no producao_app.py.

Como funciona a comunicação:
  1. O cliente manda mensagem para o WhatsApp da Deflo.
  2. A Meta avisa o servidor fazendo um POST em /webhook (isso é o "webhook").
  3. processar_webhook() pega o texto, passa para conversa.responder() e recebe
     a resposta. Se for áudio, foto ou figurinha, usa conversa.responder_nao_texto(),
     que pede por escrito a informação que estiver faltando.
  4. enviar_whatsapp() manda a resposta de volta pela API da Meta.
"""
import asyncio
import hashlib
import hmac

import requests
from fastapi import HTTPException

import todos_config as config
import todos_conversa as conversa


# ------------------------------------------------------------------
# Verificação do webhook: a Meta chama uma vez, quando você cadastra
# o endereço, para confirmar que o servidor é seu.
# ------------------------------------------------------------------
def verificar_webhook(parametros):
    """Devolve o 'hub.challenge' se a senha bater; senão, recusa (403)."""
    if (parametros.get("hub.mode") == "subscribe"
            and parametros.get("hub.verify_token") == config.WHATSAPP_VERIFY_TOKEN):
        return parametros.get("hub.challenge", "")
    raise HTTPException(status_code=403, detail="Token de verificação inválido")


# ------------------------------------------------------------------
# Mensagens recebidas
# ------------------------------------------------------------------
def processar_webhook(dados):
    """Lê o aviso da Meta, gera a resposta de cada mensagem e envia."""
    for entrada in dados.get("entry", []):
        for mudanca in entrada.get("changes", []):
            for msg in mudanca.get("value", {}).get("messages", []):
                telefone = msg["from"]
                if msg.get("type") == "text":
                    resposta = conversa.responder(telefone, msg["text"]["body"])
                else:
                    # áudio, foto, figurinha etc.: pede por escrito o que estiver faltando
                    resposta = conversa.responder_nao_texto(telefone)
                if resposta:
                    enviar_whatsapp(telefone, resposta)


async def verificar_lembretes_sempre():
    """
    Roda em segundo plano enquanto o servidor estiver ligado.
    A cada 1 minuto, procura clientes que pararam no meio da cotação
    e manda um lembrete pedindo a informação que falta.
    """
    while True:
        await asyncio.sleep(60)
        for telefone, mensagem in conversa.verificar_lembretes():
            await asyncio.to_thread(enviar_whatsapp, telefone, mensagem)


# ------------------------------------------------------------------
# Envio de mensagens
# ------------------------------------------------------------------
def _com_nono_digito(telefone):
    """
    Celulares do Brasil: às vezes a Meta entrega o número SEM o 9 extra
    (ex.: 55 61 9999-8888 em vez de 55 61 9 9999-8888).
    Esta função devolve o número com o 9, ou None se não for esse caso.
    """
    if telefone.startswith("55") and len(telefone) == 12 and telefone[4] in "6789":
        return telefone[:4] + "9" + telefone[4:]
    return None


def enviar_whatsapp(telefone, texto):
    """Envia uma mensagem de texto pela WhatsApp Cloud API."""
    url = (f"https://graph.facebook.com/{config.GRAPH_API_VERSION}/"
           f"{config.WHATSAPP_PHONE_NUMBER_ID}/messages")
    cabecalho = {"Authorization": f"Bearer {config.WHATSAPP_TOKEN}"}

    tentativas = [telefone]
    if _com_nono_digito(telefone):
        tentativas.append(_com_nono_digito(telefone))

    for numero in tentativas:
        corpo = {
            "messaging_product": "whatsapp",
            "to": numero,
            "type": "text",
            "text": {"body": texto},
        }
        try:
            r = requests.post(url, headers=cabecalho, json=corpo, timeout=10)
        except requests.RequestException as erro:
            print(f"[ERRO] Sem conexão com a API do WhatsApp: {erro}")
            return
        if r.ok:
            return
        # Mostra o motivo exato que a Meta devolveu (ajuda muito a descobrir o problema)
        print(f"[ERRO] WhatsApp recusou o envio para {numero}: {r.status_code} {r.text}")
        # Erro 131030 = número não aceito. Pode ser só o 9 faltando: tenta de novo com ele.
        if "131030" not in r.text:
            return


# ------------------------------------------------------------------
# Segurança
# ------------------------------------------------------------------
def conferir_assinatura(corpo, assinatura, obrigatoria):
    """
    Confere se a mensagem veio mesmo da Meta.
    A Meta assina cada requisição com o App Secret (HMAC-SHA256).
    Se alguém tentar mandar mensagens falsas para o servidor,
    a assinatura não bate e a requisição é recusada.

    obrigatoria=False (teste):    sem WHATSAPP_APP_SECRET, a conferência é pulada.
    obrigatoria=True  (produção): sem WHATSAPP_APP_SECRET, tudo é recusado.
    """
    if not config.WHATSAPP_APP_SECRET:
        if obrigatoria:
            raise HTTPException(status_code=500, detail="WHATSAPP_APP_SECRET não configurado")
        return
    esperado = "sha256=" + hmac.new(config.WHATSAPP_APP_SECRET.encode(), corpo, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(esperado, assinatura):
        raise HTTPException(status_code=403, detail="Assinatura inválida")
