"""
Avisa o celular do atendente quando um cliente quer falar com alguém,
e deixa ele marcar no próprio alerta quem já foi atendido.

Como o alerta chega no celular?
  Usamos um bot do TELEGRAM. É gratuito, e o Telegram mostra uma notificação
  no celular como qualquer mensagem. Basta:
    1. criar um bot no Telegram (conversando com o @BotFather) -> ele te dá um TOKEN;
    2. mandar um "oi" para o seu bot pelo celular do atendente;
    3. rodar  python descobrir_chat_id.py  para descobrir o CHAT_ID;
    4. colocar TOKEN e CHAT_ID no arquivo .env.

  Enviar a mensagem é só uma requisição HTTP para a API do Telegram.

O ❌ e o ✅ da primeira linha:
  Todo alerta chega marcado com ❌, que quer dizer "ninguém atendeu ainda".
  Embaixo da mensagem vêm dois botões:

      [ Abrir conversa ]   [ ✅ Já atendi ]

  O primeiro abre o WhatsApp (ou o Gmail) direto na conversa do cliente.
  O segundo troca o ❌ da primeira linha por ✅, NA MESMA MENSAGEM.

  Assim o atendente rola o Telegram e vê de relance o que já foi atendido e o
  que ainda está esperando. A marca fica no histórico, e não some.

Por que precisa de dois toques:
  O Telegram NÃO avisa o bot quando alguém clica num link comum. Quando o
  atendente toca no link do WhatsApp, o celular dele abre o aplicativo e pronto,
  nada disso passa pelo bot. O que o Telegram avisa é o toque num BOTÃO que o
  próprio bot colocou. Por isso o "Já atendi" é um botão separado.

Como o bot fica sabendo do toque:
  O Telegram manda um aviso para um endereço do nosso servidor (o webhook), do
  mesmo jeito que a Meta faz com as mensagens do WhatsApp. Esse endereço é
  cadastrado uma vez só, com:

      python todos_alerta.py https://SEU-SERVICO.onrender.com/telegram

  Nada precisa ser guardado: quando o atendente toca no botão, o Telegram manda
  de volta o texto inteiro da mensagem, então o bot só troca o ❌ pelo ✅ e devolve.

  Se o botão não estiver funcionando, rode:

      python todos_alerta.py --conferir

  Ele mostra o endereço cadastrado e o último erro que o Telegram teve ao tentar
  entregar um toque, que é o que costuma explicar o problema.

Segurança:
  O endereço do webhook é público, então qualquer um poderia tentar mandar
  cliques falsos para ele. Para impedir isso, o cadastro leva um segredo
  (TELEGRAM_SEGREDO, no .env). O Telegram devolve esse segredo em todo aviso,
  e o nosso servidor recusa o que vier sem ele.

Se o Telegram ainda não estiver configurado, o alerta aparece no terminal
(útil para testar no simulador).
"""
import re

import requests

import todos_config as config

MARCA_PENDENTE = "❌"
MARCA_ATENDIDO = "✅"
TEXTO_DO_BOTAO = f"{MARCA_ATENDIDO} Já atendi"
DADO_DO_BOTAO = "atendido"          # o que o Telegram devolve quando o botão é tocado
SEGUNDOS_DE_ESPERA = 10


def _api(metodo):
    return f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}/{metodo}"


def _chamar(metodo, dados):
    """
    Chama a API do Telegram. Nunca derruba o chatbot: erro só vai para o terminal.

    Quando o Telegram recusa, ele manda junto uma explicação em "description".
    O erro mostra essa explicação, e NÃO a URL: a URL carrega o token do bot,
    que é senha e não pode aparecer no terminal nem em print de tela.
    """
    try:
        resposta = requests.post(_api(metodo), json=dados, timeout=SEGUNDOS_DE_ESPERA)
        if resposta.ok:
            return True
        try:
            explicacao = resposta.json().get("description", "")
        except ValueError:
            explicacao = ""
        print(f"[ERRO] Telegram recusou o {metodo} ({resposta.status_code}): "
              f"{explicacao or 'sem explicação'}")
        return False
    except requests.RequestException as erro:
        print(f"[ERRO] Não consegui falar com o Telegram no {metodo}: {type(erro).__name__}")
        return False


def _botoes(link, rotulo_do_link):
    """
    Monta os botões que vão embaixo do alerta.
    O botão de link é opcional: o resumo semanal, por exemplo, não tem link.
    """
    linha = []
    if link:
        linha.append({"text": rotulo_do_link, "url": link})
    linha.append({"text": TEXTO_DO_BOTAO, "callback_data": DADO_DO_BOTAO})
    return {"inline_keyboard": [linha]}


def enviar_alerta(texto, link=None, rotulo_do_link="Abrir conversa", com_botoes=True):
    """
    Envia o alerta para o Telegram do atendente.

    link           -> endereço que o botão abre (a conversa no WhatsApp, o e-mail no Gmail)
    com_botoes     -> False para avisos que não são atendimento (o resumo semanal)
    """
    if not config.TELEGRAM_TOKEN or not config.TELEGRAM_CHAT_ID:
        print("\n🔔 [ALERTA SIMULADO — Telegram não configurado]\n" + texto + "\n")
        return False

    dados = {"chat_id": config.TELEGRAM_CHAT_ID, "text": texto}
    if com_botoes:
        dados["reply_markup"] = _botoes(link, rotulo_do_link)
    return _chamar("sendMessage", dados)


def processar_callback(aviso):
    """
    O atendente tocou no botão "Já atendi".

    O Telegram manda de volta a mensagem inteira, então o bot troca o ❌ da
    primeira linha por ✅ e reescreve a MESMA mensagem. Os botões saem junto:
    depois de marcado, não há mais o que fazer ali.

    Devolve True quando a mensagem foi marcada.
    """
    toque = (aviso or {}).get("callback_query")
    if not toque or toque.get("data") != DADO_DO_BOTAO:
        return False

    mensagem = toque.get("message") or {}
    texto = mensagem.get("text") or ""
    chat = (mensagem.get("chat") or {}).get("id")
    numero = mensagem.get("message_id")

    # Sempre responde o toque, senão o botão fica girando no celular do atendente
    _chamar("answerCallbackQuery", {"callback_query_id": toque.get("id"),
                                    "text": "Marcado como atendido."})
    if not chat or not numero:
        return False

    if texto.startswith(MARCA_PENDENTE):
        texto = MARCA_ATENDIDO + texto[len(MARCA_PENDENTE):]
    elif not texto.startswith(MARCA_ATENDIDO):
        texto = f"{MARCA_ATENDIDO} {texto}"

    quem = (toque.get("from") or {}).get("first_name")
    if quem and "Atendido por" not in texto:
        texto += f"\n\nAtendido por {quem}."

    return _chamar("editMessageText", {"chat_id": chat, "message_id": numero, "text": texto})


# O Telegram só aceita letras, números, _ e - no segredo do webhook, até 256.
# Espaço, acento e pontuação fazem o cadastro ser recusado com 400.
REGEX_SEGREDO = re.compile(r"^[A-Za-z0-9_-]{1,256}$")


def segredo_valido(segredo):
    """True quando o segredo está no formato que o Telegram aceita."""
    return bool(REGEX_SEGREDO.match(str(segredo)))


def segredo_confere(recebido):
    """
    True quando o aviso veio mesmo do Telegram.

    Sem o TELEGRAM_SEGREDO preenchido no .env, o bot aceita qualquer aviso. Isso
    serve só para testar no computador: na produção, preencha o segredo.
    """
    if not config.TELEGRAM_SEGREDO:
        return True
    return recebido == config.TELEGRAM_SEGREDO


def conferir_webhook():
    """
    Mostra como está o cadastro do webhook, para descobrir por que o botão
    "Já atendi" não está funcionando. O Telegram guarda o último erro que deu
    ao tentar entregar um toque, e é isso que costuma explicar o problema.

    Não imprime o token em lugar nenhum.
    """
    try:
        resposta = requests.get(_api("getWebhookInfo"), timeout=SEGUNDOS_DE_ESPERA)
        dados = resposta.json().get("result", {})
    except Exception as erro:
        print(f"[ERRO] Não consegui perguntar ao Telegram: {type(erro).__name__}")
        return False

    endereco = dados.get("url") or "(nenhum)"
    print(f"Endereço cadastrado : {endereco}")
    print(f"Toques na fila      : {dados.get('pending_update_count', 0)}")
    print(f"Tipos que ele manda : {dados.get('allowed_updates') or '(todos)'}")
    ultimo = dados.get("last_error_message")
    if ultimo:
        print(f"ÚLTIMO ERRO         : {ultimo}")
        print()
        print("O que cada erro costuma querer dizer:")
        print("  401 ou 403  -> o TELEGRAM_SEGREDO do Render está diferente do que foi cadastrado aqui")
        print("  404         -> o deploy no Render ainda não tem a rota /telegram")
        print("  timeout     -> o Render estava dormindo; toque no botão de novo")
    else:
        print("Último erro         : nenhum")
        print()
        print("Sem erro e com o endereço certo, o toque está chegando no servidor.")
        print("Se mesmo assim o ❌ não vira ✅, o problema é dentro do servidor:")
        print("veja os Logs do Render logo depois de tocar no botão.")
    return True


def assinar_webhook(endereco):
    """Diz ao Telegram para onde mandar os toques nos botões."""
    dados = {"url": endereco, "allowed_updates": ["callback_query"]}
    if config.TELEGRAM_SEGREDO:
        dados["secret_token"] = config.TELEGRAM_SEGREDO
    return _chamar("setWebhook", dados)


if __name__ == "__main__":
    # Cadastra o endereço do webhook:
    #   python todos_alerta.py https://SEU-SERVICO.onrender.com/telegram
    import sys

    if len(sys.argv) == 2 and sys.argv[1] == "--conferir":
        if not config.TELEGRAM_TOKEN:
            raise SystemExit("Preencha o TELEGRAM_TOKEN no arquivo .env primeiro.")
        conferir_webhook()
        raise SystemExit(0)

    if len(sys.argv) != 2:
        raise SystemExit("Uso: python todos_alerta.py https://SEU-SERVICO.onrender.com/telegram\n"
                         "     python todos_alerta.py --conferir")
    if not config.TELEGRAM_TOKEN:
        raise SystemExit("Preencha o TELEGRAM_TOKEN no arquivo .env primeiro.")
    destino = sys.argv[1].strip()
    if not destino.startswith("https://") or not destino.endswith("/telegram"):
        raise SystemExit("O endereço precisa começar com https:// e terminar com /telegram")
    if not config.TELEGRAM_SEGREDO:
        print("Atenção: o TELEGRAM_SEGREDO está vazio. Na produção, preencha ele no .env e no Render.")
    elif not segredo_valido(config.TELEGRAM_SEGREDO):
        raise SystemExit(
            "O TELEGRAM_SEGREDO do .env tem caractere que o Telegram não aceita.\n"
            "Use só letras, números, _ e - (sem espaço, sem acento, sem pontuação).\n"
            "Ex.: TELEGRAM_SEGREDO=deflo-alertas-2026-k7m2")
    print("Assinatura feita com sucesso." if assinar_webhook(destino) else "Não consegui assinar.")
    print(f"Endereço: {destino}")