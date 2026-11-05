"""
Avisa no Telegram quando chega um e-mail novo na caixa da empresa
e guarda cada e-mail na planilha "emails_registrados", no Google Drive.

Para que serve:
  Muitos clientes ainda pedem cotação por e-mail. Com este aviso, o atendente
  fica sabendo na hora, pelo mesmo Telegram onde já recebe os atendimentos
  do WhatsApp, sem precisar ficar abrindo o e-mail. E a planilha vira o
  histórico dos contatos por e-mail, para análise de dados.

Como funciona:
  1. A cada EMAIL_VERIFICAR_SEG segundos (todos_config.py), o bot entra na
     caixa de entrada pelo IMAP (o "idioma" que os programas de e-mail usam
     para ler mensagens).
  2. Para cada e-mail novo, ele:
       - cria um protocolo, ex.: ATM-25102026-0914-K7 (M de e-mail; no WhatsApp é ATD);
       - manda o aviso para o Telegram;
       - grava uma linha na planilha emails_registrados.

Mesma conversa = mesmo protocolo:
  Se o cliente responder a conversa de e-mail que ele já tinha começado, a mensagem
  nova ganha OUTRA linha na planilha (com o horário dela), mas com o
  MESMO protocolo da primeira. O bot reconhece a conversa pelo código que o Gmail dá
  para cada conversa (o mesmo que vai no link). O aviso no Telegram diz que é uma
  mensagem nova numa conversa que já existe.

Prévia só com o texto novo:
  Numa resposta, o e-mail traz embaixo o texto antigo ("Em sáb., ... escreveu:").
  O bot corta essa parte, para a prévia mostrar o que o cliente escreveu agora.

O bot só LÊ:
  A caixa é aberta em modo "somente leitura": o e-mail continua como NÃO LIDO,
  nada é apagado e nada é respondido. O dono vê tudo normalmente.
  Por isso o cliente não recebe o protocolo: ele serve para a equipe se organizar.

E-mails automáticos (Google, Render, UptimeRobot, Meta, "não responda"...):
  São ignorados: não geram protocolo, nem aviso no Telegram, nem linha na planilha.
  Assim, o celular do atendente e a planilha ficam só com e-mails de clientes.

Senha:
  O bot NÃO usa a senha normal do e-mail. Ele usa uma "senha de app": uma senha
  especial, criada na conta Google só para ele, que pode ser cancelada a
  qualquer momento sem mexer na senha principal. Ela fica no .env (teste)
  e no painel do Render (produção), como as outras senhas.

Onde roda:
  Só na PRODUÇÃO (producao_app.py). Se o teste também verificasse, o atendente
  receberia cada aviso duas vezes enquanto o teste estivesse ligado.
  Para testar no computador:  python todos_email.py
  (ele faz o caminho completo com o e-mail mais recente da caixa: aviso no
  Telegram marcado como TESTE e uma linha na planilha, que depois pode ser apagada)

Como o bot sabe o que é novo:
  Cada e-mail da caixa tem um número (UID) que só cresce. Quando o servidor liga,
  o bot anota o maior número que já existe e, dali em diante, cuida só dos maiores.
  Por isso, e-mails que já estavam na caixa não geram aviso.

Planilha emails_registrados (a primeira linha tem estes títulos, nesta ordem):
  data_hora  -> quando o bot viu o e-mail (AAAA-MM-DD HH:MM)
  email      -> endereço de quem mandou
  protocolo  -> ex.: ATM-25102026-0914-K7
  link       -> abre a conversa direto no Gmail (o mesmo link para todas as mensagens da conversa)

Atenção (LGPD): o e-mail do cliente é dado pessoal. A planilha fica na pasta
privada do Drive, compartilhada só com a conta robô do bot.
"""
import asyncio
import email
import imaplib
import re
from email import policy
from email.utils import parseaddr
from urllib.parse import quote

import todos_config as config
import todos_drive as drive
import todos_alerta as alerta
from todos_alerta import enviar_alerta
from todos_conversa import agora_brasilia, gerar_protocolo
from todos_distancia import normalizar

TAMANHO_PREVIA = 300            # quantas letras do texto aparecem no aviso
BYTES_LIDOS = 60_000            # lê só o começo de cada e-mail (anexos grandes ficam de fora)

COLUNAS_EMAIL = ["data_hora", "email", "protocolo", "link"]

# Remetentes de e-mails automáticos (avisos de sistemas, não de clientes)
REMETENTES_AUTOMATICOS = ("NOREPLY", "NO REPLY", "NAO RESPONDA", "NAORESPONDA", "DONOTREPLY",
                          "DO NOT REPLY", "MAILER DAEMON", "POSTMASTER", "NOTIFICATION")
DOMINIOS_AUTOMATICOS = ("google.com", "accounts.google.com", "render.com", "uptimerobot.com",
                        "facebookmail.com", "meta.com", "github.com", "telegram.org")

_ultimo_uid = None              # maior número de e-mail já visto
_validade = None                # "versão" da caixa; se mudar, os números recomeçam
_protocolos = None              # {link da conversa: protocolo}, lido da planilha na primeira vez


# =================================================================
# Ler a caixa de entrada
# =================================================================
def _conectar():
    """Entra na caixa de entrada em modo somente leitura."""
    caixa = imaplib.IMAP4_SSL(config.EMAIL_IMAP_SERVIDOR)
    caixa.login(config.EMAIL_ENDERECO, config.EMAIL_SENHA_APP)
    caixa.select("INBOX", readonly=True)      # readonly: não marca nada como lido
    return caixa


def _uids_e_validade(caixa):
    """Devolve a lista de números (UID) dos e-mails da caixa e a validade desses números."""
    _, dados = caixa.response("UIDVALIDITY")
    validade = dados[0].decode() if dados and dados[0] else None
    _, resultado = caixa.uid("search", None, "ALL")
    uids = [int(u) for u in resultado[0].split()] if resultado and resultado[0] else []
    return uids, validade


def _baixar(caixa, uid):
    """
    Baixa o começo de um e-mail SEM marcar como lido (BODY.PEEK) e o código da conversa
    no Gmail (X-GM-THRID), usado para montar o link que abre a conversa direto.
    """
    _, dados = caixa.uid("fetch", str(uid), f"(X-GM-THRID BODY.PEEK[]<0.{BYTES_LIDOS}>)")
    for parte in dados:
        if isinstance(parte, tuple):
            achado = re.search(rb"X-GM-THRID (\d+)", parte[0])
            conversa = int(achado.group(1)) if achado else None
            return email.message_from_bytes(parte[1], policy=policy.default), conversa
    return email.message_from_bytes(b"", policy=policy.default), None


# =================================================================
# Entender o e-mail
# =================================================================
def _texto_simples(html):
    """Tira as etiquetas de um e-mail em HTML, deixando só o texto (e sem a parte citada)."""
    html = re.split(r'(?i)<div[^>]*class="[^"]*gmail_quote|<blockquote', html)[0]
    sem_estilo = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
    com_quebras = re.sub(r"(?i)<br\s*/?>|</p>|</div>", "\n", sem_estilo)
    return re.sub(r"<[^>]+>", " ", com_quebras)


# Onde começa o texto antigo numa resposta de e-mail
_CABECALHO_RESPOSTA = re.compile(
    r"(?im)^[ \t]*(?:Em|On)\s[^\n]{0,300}(?:\n[^\n]{0,300}){0,2}?(?:escreveu|wrote)\s*:"
    r"|^[ \t]*-{2,}\s*(?:Mensagem original|Original Message|Mensagem encaminhada|Forwarded message)"
    r"|^[ \t]*(?:De|From):\s[^\n]+\n[ \t]*(?:Enviad[ao] em|Enviad[ao]|Sent|Data|Date):")


def _so_texto_novo(texto):
    """
    Numa resposta, tira o texto antigo que vem embaixo ("Em sáb., 25 de out., Fulano escreveu:"
    e as linhas que começam com ">"), deixando só o que o cliente escreveu agora.
    """
    corte = _CABECALHO_RESPOSTA.search(texto)
    if corte:
        texto = texto[:corte.start()]
    linhas = [linha for linha in texto.splitlines() if not linha.lstrip().startswith(">")]
    return " ".join(" ".join(linhas).split())


def _texto_do_email(mensagem):
    """O texto NOVO do e-mail (sem a parte citada de mensagens anteriores), em uma linha só."""
    try:
        corpo = mensagem.get_body(preferencelist=("plain", "html"))
        texto = corpo.get_content() if corpo else ""
        if corpo is not None and corpo.get_content_type() == "text/html":
            texto = _texto_simples(texto)
    except Exception:                          # e-mail fora do padrão: segue sem o texto
        texto = ""
    return _so_texto_novo(texto)


def _previa(texto):
    if len(texto) > TAMANHO_PREVIA:
        texto = texto[:TAMANHO_PREVIA].rstrip() + "..."
    return texto or "(sem texto)"


def eh_automatico(nome, endereco):
    """True se o e-mail veio de um sistema (Google, Render, 'não responda'...), e não de um cliente."""
    quem = normalizar(f"{nome} {endereco.replace('-', ' ').replace('_', ' ')}")
    dominio = endereco.lower().rsplit("@", 1)[-1]
    return (any(palavra in quem for palavra in REMETENTES_AUTOMATICOS)
            or any(dominio == d or dominio.endswith("." + d) for d in DOMINIOS_AUTOMATICOS))


def link_gmail(conversa, mensagem):
    """
    Link que abre a conversa direto no Gmail da empresa.
    Se o Gmail não informar o código da conversa, o link procura o e-mail pelo código dele.
    """
    base = f"https://mail.google.com/mail/?authuser={config.EMAIL_ENDERECO}"
    if conversa:
        return f"{base}#all/{conversa:x}"
    codigo = str(mensagem.get("Message-ID", "")).strip("<> ")
    return f"{base}#search/{quote('rfc822msgid:' + codigo)}" if codigo else base


# =================================================================
# Cuidar de um e-mail novo: protocolo, aviso no Telegram e planilha
# =================================================================
def _protocolo_da_conversa(link):
    """
    Se o cliente já escreveu antes nesta MESMA conversa, devolve o protocolo dela.
    Na primeira vez, o bot lê a planilha inteira e guarda {link: protocolo} na memória,
    assim o protocolo continua o mesmo mesmo depois de o servidor reiniciar.
    """
    global _protocolos
    if _protocolos is None:
        try:
            linhas = drive.ler_planilha(config.NOME_PLANILHA_EMAILS)[1:]     # [1:] pula os títulos
            col_link, col_protocolo = COLUNAS_EMAIL.index("link"), COLUNAS_EMAIL.index("protocolo")
            _protocolos = {linha[col_link]: linha[col_protocolo]
                           for linha in linhas if len(linha) > col_link}
        except Exception as erro:
            print(f"[E-MAIL] Não consegui ler a planilha {config.NOME_PLANILHA_EMAILS} ({erro}).")
            return None                        # tenta de novo no próximo e-mail
    return _protocolos.get(link)


def _registrar(valores):
    """Grava a linha na planilha. Se o Drive falhar, o aviso no Telegram já foi e o erro vai para o log."""
    try:
        drive.acrescentar_linha(config.NOME_PLANILHA_EMAILS, valores)
    except Exception as erro:
        print(f"[E-MAIL] Não consegui gravar na planilha {config.NOME_PLANILHA_EMAILS} ({erro}): {valores}")


def cuidar_do_email(caixa, uid, teste=False):
    """Lê um e-mail novo, avisa no Telegram e grava na planilha. Devolve o aviso (ou None)."""
    mensagem, conversa = _baixar(caixa, uid)
    nome, endereco = parseaddr(str(mensagem.get("From", "")))
    if endereco.lower() == config.EMAIL_ENDERECO.lower():
        return None                            # e-mail enviado pela própria empresa: ignora
    if eh_automatico(nome, endereco):
        return None                            # aviso de sistema (Google, Render...): ignora

    momento = agora_brasilia()
    titulo = str(mensagem.get("Subject", "")).strip()
    texto = _texto_do_email(mensagem)
    link = link_gmail(conversa, mensagem)
    # Mesma conversa de e-mail: mesmo protocolo (nova linha, com o horário desta mensagem)
    protocolo = _protocolo_da_conversa(link) if conversa else None
    continuacao = protocolo is not None
    if not continuacao:
        protocolo = gerar_protocolo(momento, config.PREFIXO_PROTOCOLO_EMAIL)
    _registrar([momento.strftime("%Y-%m-%d %H:%M"), endereco.lower(), protocolo, link])
    if _protocolos is not None:
        _protocolos[link] = protocolo

    remetente = f"{nome} <{endereco}>" if nome else endereco
    titulo_aviso = "NOVA MENSAGEM NA MESMA CONVERSA" if continuacao else "NOVO E-MAIL"
    # O ❌ diz que ninguém atendeu ainda; o botão "Já atendi" troca por ✅.
    aviso = (f"{alerta.MARCA_PENDENTE} {titulo_aviso} — Protocolo {protocolo}\n"
             f"De: {remetente}\n"
             f"Assunto: {titulo or '(sem assunto)'}\n"
             f"Prévia: {_previa(texto)}")
    enviar_alerta(("(TESTE) " if teste else "") + aviso,
                  link=link, rotulo_do_link="Abrir e-mail")
    return aviso


def email_configurado():
    return bool(config.EMAIL_ENDERECO and config.EMAIL_SENHA_APP)


def verificar_emails_novos():
    """
    Cuida dos e-mails que chegaram desde a última verificação.
    Na primeira vez, só anota onde a caixa está (não mexe nos e-mails antigos).
    Devolve quantos e-mails novos foram encontrados.
    """
    global _ultimo_uid, _validade
    caixa = _conectar()
    try:
        uids, validade = _uids_e_validade(caixa)
        maior = max(uids, default=0)

        if _ultimo_uid is None or validade != _validade:
            _ultimo_uid, _validade = maior, validade
            return 0

        novos = sorted(u for u in uids if u > _ultimo_uid)
        for uid in novos:
            try:
                cuidar_do_email(caixa, uid)
            except Exception as erro:          # um e-mail com problema não trava os outros
                print(f"[E-MAIL] Não consegui ler o e-mail {uid} ({erro}).")
            _ultimo_uid = uid
        return len(novos)
    finally:
        caixa.logout()


async def verificar_emails_sempre():
    """
    Roda em segundo plano enquanto o servidor de produção estiver ligado.
    Se a caixa de e-mail falhar (internet, senha), o erro aparece no log
    e o bot tenta de novo na próxima volta. O WhatsApp nunca é afetado.
    """
    if not email_configurado():
        print("[E-MAIL] EMAIL_ENDERECO ou EMAIL_SENHA_APP vazios: aviso de e-mail desligado.")
        return
    while True:
        try:
            await asyncio.to_thread(verificar_emails_novos)
        except Exception as erro:
            print(f"[E-MAIL] Não consegui verificar a caixa de entrada ({erro}).")
        await asyncio.sleep(config.EMAIL_VERIFICAR_SEG)


if __name__ == "__main__":
    # Teste no computador: python todos_email.py
    if not email_configurado():
        raise SystemExit("Preencha EMAIL_ENDERECO e EMAIL_SENHA_APP no .env.")
    caixa = _conectar()
    try:
        uids, _ = _uids_e_validade(caixa)
        print(f"Ligação com o e-mail funcionando: {len(uids)} e-mails na caixa de entrada.")
        if uids:
            # Mostra qual e-mail está sendo analisado (o mais recente da caixa)
            mensagem, _ = _baixar(caixa, max(uids))
            print("\nAnalisando o e-mail MAIS RECENTE da caixa:")
            print(f"  De:     {mensagem.get('From', '')}")
            print(f"  Título: {mensagem.get('Subject', '')}")
            print(f"  Texto novo (sem a parte citada): {_previa(_texto_do_email(mensagem))}\n")
            aviso = cuidar_do_email(caixa, max(uids), teste=True)
            if aviso:
                print("Aviso mandado para o Telegram e linha gravada na planilha:\n")
                print(aviso)
            else:
                print("O e-mail mais recente é automático (Google, Render...) ou da própria empresa, "
                      "e por isso foi ignorado. Mande um e-mail do seu e-mail pessoal e rode de novo.")
    finally:
        caixa.logout()