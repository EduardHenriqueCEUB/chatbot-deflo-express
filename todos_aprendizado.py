"""
O caderno de aprendizado do bot.

Para que serve?
  Toda vez que o bot não consegue responder uma pergunta, ele chama o atendente
  (isso já acontecia) e, agora, também ANOTA a pergunta numa planilha do Drive
  chamada "base_conhecimento".

  Depois, com calma, uma pessoa abre essa planilha, escreve a resposta e muda o
  status para "aprovada". A partir daí o bot passa a responder aquilo sozinho.

Por que anotar em vez de aprender sozinho?
  Porque a resposta de um atendente costuma valer só para aquele cliente
  ("para essa carga fica R$ 1.850 e coletamos quinta"). Se isso virasse resposta
  oficial, o bot passaria a dizer isso para todo mundo. Além disso, o atendente
  pode errar e corrigir depois. Por isso existe o passo da aprovação: quem
  decide o que o bot vai dizer é uma pessoa.

Por que agrupar perguntas parecidas?
  Se cinco clientes perguntam a mesma coisa com palavras diferentes, não adianta
  virar cinco linhas. Vira UMA linha, com a contagem (coluna "vezes") e os outros
  jeitos de perguntar guardados ao lado. Assim:
    - quem for responder começa pelo que mais apareceu, e não pelo mais recente;
    - os "outros jeitos" viram, de graça, as palavras-chave da resposta nova.

O que o bot NUNCA faz aqui:
  Não apaga linha, não muda resposta que uma pessoa escreveu e não muda status.
  Ele só acrescenta linhas novas e atualiza a contagem e as datas.

Você pode apagar linhas à mão:
  Antes de anotar qualquer pergunta, o bot relê a planilha. Então, se você apagar
  uma linha, ele trata aquela pergunta como nova da próxima vez. Isso também
  evita que ele escreva no número de uma linha que mudou de lugar depois de uma
  exclusão, o que estragaria a linha de outra pergunta.
  (Para RESPONDER, o bot usa a cópia guardada na memória, que é relida a cada
  CONHECIMENTO_ATUALIZAR_MIN minutos. Então uma linha aprovada que você apagar
  pode continuar sendo respondida por até esse tempo.)

O que NÃO vira linha (senão a planilha vira lixo e ninguém abre):
  1. Mensagem com dado pessoal: e-mail, telefone, CPF, CNPJ, CEP ou link.
     Essa é a regra mais importante. A base de conhecimento é um FAQ, e não um
     depósito de dado de cliente (LGPD).
  2. Agradecimento, confirmação e despedida: "ok", "valeu", "perfeito", "tchau".
  3. Mensagem sem palavra nenhuma: só emoji, só pontuação, só risada.
  4. Só data, hora, peso ou unidade: "quinta-feira", "amanhã", "22 toneladas".
  5. Nome de cidade solto, mesmo com interrogação: "goiania?".
  6. Mensagem comprida demais (acima de 25 palavras): é descrição de demanda ou
     endereço colado, não pergunta reaproveitável.
  7. Comando e número do menu, e erro de digitação de cidade.
  Além disso, a MESMA pergunta na MESMA conversa conta uma vez só (quem cuida
  dessa parte é o todos_conversa.py). Assim a coluna "vezes" quer dizer
  "quantas conversas diferentes perguntaram isso".

Colunas da planilha "base_conhecimento" (nesta ordem, A até H):
  pergunta       -> a frase do cliente, do jeito que ele escreveu na primeira vez
  outros_jeitos  -> outras formas de perguntar a mesma coisa, separadas por " | "
  vezes          -> quantas vezes a pergunta apareceu
  primeira_vez   -> data e hora da primeira vez (AAAA-MM-DD HH:MM)
  ultima_vez     -> data e hora da última vez
  etapa          -> onde o cliente estava na conversa (menu, faq, pos_cotacao...)
  resposta       -> VOCÊ escreve aqui o que o bot deve responder
  status         -> pendente / aprovada / ignorada
                    O bot só usa a resposta quando o status é "aprovada".
                    "pendente" aparece no resumo semanal; "ignorada" some do resumo.

Depois que a resposta é aprovada:
  O bot passa a responder aquilo sozinho, sem publicar código novo. Ele relê a
  planilha a cada CONHECIMENTO_ATUALIZAR_MIN minutos (o padrão é 5).
  Isso vale só para as perguntas NOVAS que chegarem. O bot nunca volta numa
  conversa antiga para mandar uma resposta atrasada: ele só fala quando
  recebe uma mensagem.

O resumo semanal:
  Uma vez por semana o bot manda UMA mensagem no Telegram com as perguntas que
  estão esperando resposta, da mais perguntada para a menos. Assim o atendente
  não precisa parar o que está fazendo para ensinar o bot no meio do expediente,
  e o canal de alertas não vira bagunça.

Para testar a ligação: python todos_aprendizado.py
"""
import difflib
import re
import threading
import unicodedata
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import asyncio

import todos_config as config
import todos_distancia as distancia
import todos_drive as drive
from todos_alerta import enviar_alerta

COLUNAS = ["pergunta", "outros_jeitos", "vezes", "primeira_vez", "ultima_vez",
           "etapa", "resposta", "status"]

# Palavras comuns demais para dizer do que a pergunta trata.
# Elas são ignoradas na hora de comparar duas perguntas.
PALAVRAS_SEM_PESO = {
    "A", "AO", "AOS", "AS", "DA", "DAS", "DE", "DO", "DOS", "E", "EM", "NA", "NAS", "NO", "NOS",
    "O", "OS", "OU", "PARA", "PRA", "PELO", "PELA", "POR", "UM", "UMA", "UNS", "UMAS", "COM",
    "SEM", "QUE", "QUAL", "QUAIS", "COMO", "QUANDO", "ONDE", "QUEM", "SE", "JA", "SO", "AI",
    "EU", "ME", "MEU", "MINHA", "VOCE", "VOCES", "VCS", "VC", "TEM", "TEMOS", "TENHO", "E",
    "SER", "SAO", "ESTA", "ESTAO", "FOI", "VAI", "VOU", "PODE", "POSSO", "QUERO", "QUERIA",
    "PRECISO", "GOSTARIA", "FAZ", "FAZER", "DAR", "DA", "OI", "OLA", "BOM", "BOA", "DIA",
    "TARDE", "NOITE", "OBRIGADO", "OBRIGADA", "FAVOR", "POR FAVOR", "ISSO", "ESSE", "ESSA",
    "AQUI", "LA", "MAIS", "MENOS", "MUITO", "BEM", "TUDO", "NAO", "SIM",
}

# Nessas etapas o bot está esperando um dado (cidade, peso, medidas).
# Ali, uma mensagem só vira pergunta anotada se tiver ponto de interrogação,
# senão todo erro de digitação de cidade viraria uma linha na planilha.
ETAPAS_QUE_ESPERAM_DADO = {"origem", "destino", "peso", "medidas",
                           "escolher_origem", "escolher_destino"}

# Mensagens que nunca são pergunta: comando, número do menu, agradecimento,
# confirmação, despedida e risada. Saíram das conversas reais da empresa.
MENSAGENS_SEM_PERGUNTA = {
    # comandos
    "MENU", "INICIO", "VOLTAR", "PULAR", "PULA",
    # confirmação
    "SIM", "NAO", "S", "N", "OK", "OKAY", "OKEY", "ISSO", "ISSO MESMO", "EXATO", "CERTO",
    "PERFEITO", "ENTENDI", "ENTENDIDO", "FECHADO", "COMBINADO", "AGUARDO", "TA BOM",
    "TA BEM", "TUDO BEM", "PODE SER", "PODE SIM", "CLARO", "SHOW", "TRANQUILO", "BELEZA",
    "BLZ", "TA", "TA CERTO", "SEM PROBLEMA", "SEM PROBLEMAS",
    # agradecimento e despedida
    "OBRIGADO", "OBRIGADA", "OBG", "VALEU", "VLW", "DE NADA", "POR NADA", "ATE MAIS",
    "ATE LOGO", "TCHAU", "ABRACO", "ABRACOS", "BOM FINAL DE SEMANA", "BOA SEMANA",
    "BOM TRABALHO", "FICO NO AGUARDO", "AGUARDO RETORNO",
    # saudação
    "OI", "OLA", "ALO", "BOM DIA", "BOA TARDE", "BOA NOITE", "E AI", "OPA",
    # risada
    "KKK", "KKKK", "KKKKK", "RS", "RSRS", "RSRSRS", "HAHA", "HAHAHA", "HEHE",
}

# Dado pessoal: e-mail, CNPJ, CPF, CEP, telefone e link.
# Mensagem com qualquer um deles é descartada, sem exceção (LGPD).
REGEX_DADO_PESSOAL = re.compile(
    r"[\w.+-]+@[\w.-]+\.\w{2,}"                             # e-mail
    r"|\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}"                 # CNPJ
    r"|\d{3}\.?\d{3}\.?\d{3}-\d{2}"                         # CPF
    r"|\b\d{5}-?\d{3}\b"                                    # CEP
    r"|(?:\+?55\s?)?\(?\d{2}\)?[\s.-]?9?\d{4}[\s.-]?\d{4}\b"  # telefone
    r"|https?://|www\.|wa\.me|maps\.app|goo\.gl",             # link
    re.IGNORECASE)

# Palavras que sozinhas não dizem do que a pergunta trata: tempo, peso e unidade.
# Se sobrar só isso, a mensagem é resposta a uma pergunta do atendente, não dúvida.
PALAVRAS_DE_CONTEXTO = {
    "SEGUNDA", "TERCA", "QUARTA", "QUINTA", "SEXTA", "SABADO", "DOMINGO", "FEIRA",
    "HOJE", "AMANHA", "ONTEM", "AGORA", "CEDO", "MANHA", "TARDE", "NOITE", "DIA", "DIAS",
    "HORA", "HORAS", "SEMANA", "SEMANAS", "MES", "MESES", "ANO", "ANOS", "MINUTOS",
    "KG", "KGS", "QUILO", "QUILOS", "TONELADA", "TONELADAS", "TON", "GRAMAS",
    "PALETE", "PALETES", "PALLET", "PALLETS", "CAIXA", "CAIXAS", "VOLUME", "VOLUMES",
    "METRO", "METROS", "CM", "CENTIMETROS", "UNIDADE", "UNIDADES", "REAIS",
}

TAMANHO_MAXIMO = 200        # corta perguntas enormes antes de gravar
MAXIMO_PALAVRAS = 25        # acima disso é descrição de demanda, não pergunta
MAXIMO_OUTROS_JEITOS = 5    # guarda no máximo 5 formas diferentes de perguntar
PARECIDAS_JACCARD = 0.5     # metade das palavras importantes em comum
PARECIDAS_LETRAS = 0.80     # ou 80% de semelhança letra a letra

_cache = {"quando": None, "linhas": []}
_tranca = threading.Lock()      # duas mensagens ao mesmo tempo não podem criar duas linhas iguais


# =================================================================
# Texto
# =================================================================
def _normalizar(texto):
    """'Tem seguro?' -> 'TEM SEGURO' (sem acento, maiúsculo, sem pontuação)."""
    sem_acento = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode()
    so_letras = re.sub(r"[^A-Z0-9 ]", " ", sem_acento.upper())
    return " ".join(so_letras.split())


def _importantes(texto):
    """Devolve só as palavras que dizem do que a pergunta trata."""
    return {p for p in _normalizar(texto).split()
            if len(p) > 2 and p not in PALAVRAS_SEM_PESO and not p.isdigit()}


def sao_a_mesma_pergunta(uma, outra):
    """
    True quando duas perguntas tratam do mesmo assunto.
      'tem seguro?' e 'a carga tem seguro'            -> True
      'o seguro cobre avaria?' e 'tem seguro?'        -> True
      'qual o prazo?' e 'tem seguro?'                 -> False
    Duas contas: palavras importantes em comum, e semelhança letra a letra.
    Basta uma das duas passar.
    """
    palavras_uma, palavras_outra = _importantes(uma), _importantes(outra)
    if palavras_uma and palavras_outra:
        comuns = palavras_uma & palavras_outra
        todas = palavras_uma | palavras_outra
        if len(comuns) / len(todas) >= PARECIDAS_JACCARD:
            return True
    semelhanca = difflib.SequenceMatcher(None, _normalizar(uma), _normalizar(outra)).ratio()
    return semelhanca >= PARECIDAS_LETRAS


def _so_cidade(texto):
    """
    True se a mensagem é SÓ o nome de uma cidade.
      'goiania?' / 'palmas - to'          -> True
      'quanto tempo demora para goiania?' -> False (sobram outras palavras)
    """
    cidade = distancia.achar_cidade_no_texto(distancia.normalizar(texto))
    if cidade is None:
        return False
    palavras_da_cidade = _importantes(distancia.nome_completo(cidade))
    return not (_importantes(texto) - palavras_da_cidade)


def vale_anotar(texto, etapa):
    """
    True quando a mensagem é mesmo uma pergunta que merece virar linha na planilha.
    A lista completa do que é descartado está no comentário do topo do arquivo.
    """
    limpo = _normalizar(texto)

    # 1. Dado pessoal: nunca, de jeito nenhum
    if REGEX_DADO_PESSOAL.search(texto):
        return False

    # 2. Vazio, comando, agradecimento, confirmação, saudação, risada
    if not limpo or limpo in MENSAGENS_SEM_PERGUNTA:
        return False

    # 3. Número solto, medida solta
    if limpo.isdigit() or re.fullmatch(r"[\dX ,.]+", limpo):
        return False

    # 4. Comprida demais: é descrição de demanda, não pergunta reaproveitável
    if len(texto.split()) > MAXIMO_PALAVRAS:
        return False

    tem_pergunta = "?" in texto

    # 5. Onde o bot espera um dado (cidade, peso, medidas), só vale com interrogação.
    #    Sem isso, todo erro de digitação de cidade viraria uma linha.
    if etapa in ETAPAS_QUE_ESPERAM_DADO and not tem_pergunta:
        return False

    # 6. Precisa ter conteúdo: duas palavras importantes, ou uma com interrogação
    importantes = _importantes(texto)
    if not (len(importantes) >= 2 or (tem_pergunta and len(importantes) >= 1)):
        return False

    # 7. Sobrou só data, hora, peso ou unidade: é resposta ao atendente, não dúvida
    if not importantes - PALAVRAS_DE_CONTEXTO:
        return False

    # 8. É só o nome de uma cidade
    return not _so_cidade(texto)


# =================================================================
# Planilha
# =================================================================
def _ler_do_drive():
    """Lê a planilha e devolve uma lista de dicionários, com o número da linha."""
    linhas = drive.ler_planilha(config.NOME_PLANILHA_CONHECIMENTO)
    registros = []
    for numero, valores in enumerate(linhas[1:], start=2):      # linha 1 é o cabeçalho
        valores = list(valores) + [""] * (len(COLUNAS) - len(valores))
        registro = dict(zip(COLUNAS, valores))
        registro["linha"] = numero
        registros.append(registro)
    return registros


def carregar(forcar=False):
    """
    Devolve as linhas da planilha, relendo do Drive de tempos em tempos.
    Assim, uma resposta aprovada passa a valer sem precisar reiniciar o bot.
    """
    agora = datetime.now()
    velha = (_cache["quando"] is None
             or agora - _cache["quando"] > timedelta(minutes=config.CONHECIMENTO_ATUALIZAR_MIN))
    if forcar or velha:
        _cache["linhas"] = _ler_do_drive()
        _cache["quando"] = agora
    return _cache["linhas"]


def _letra(nome_coluna):
    """'vezes' -> 'C'"""
    return chr(ord("A") + COLUNAS.index(nome_coluna))


def _anotar_agora(texto, etapa, momento):
    """Faz o trabalho de verdade: procura uma linha parecida ou cria uma nova."""
    texto = texto.strip()[:TAMANHO_MAXIMO]
    quando = momento.strftime("%Y-%m-%d %H:%M")

    with _tranca:
        # Relê a planilha AGORA, e não a cópia guardada na memória.
        # Sem isso, uma linha apagada à mão continuaria "existindo" para o bot:
        # ele somaria 1 na contagem e escreveria no NÚMERO da linha antiga, que
        # depois de uma exclusão aponta para outra linha, ou para o vazio.
        # Como anotar pergunta é coisa rara, essa leitura a mais não pesa.
        linhas = carregar(forcar=True)
        achada = next((l for l in linhas
                       if sao_a_mesma_pergunta(texto, l["pergunta"])
                       or any(sao_a_mesma_pergunta(texto, j)
                              for j in l["outros_jeitos"].split(" | ") if j)), None)

        if achada is None:
            valores = [texto, "", 1, quando, quando, etapa, "", "pendente"]
            numero = drive.acrescentar_linha(config.NOME_PLANILHA_CONHECIMENTO, valores)
            nova = dict(zip(COLUNAS, valores))
            nova["linha"] = numero
            linhas.append(nova)
            return

        # Já existe: soma uma na contagem e guarda a data
        try:
            vezes = int(str(achada["vezes"]).strip() or 0) + 1
        except ValueError:
            vezes = 1
        achada["vezes"] = vezes
        achada["ultima_vez"] = quando
        celulas = {f"{_letra('vezes')}{achada['linha']}": vezes,
                   f"{_letra('ultima_vez')}{achada['linha']}": quando}

        # Guarda o jeito novo de perguntar, se for diferente e ainda couber
        jeitos = [j for j in achada["outros_jeitos"].split(" | ") if j]
        ja_conhecido = _normalizar(texto) in {_normalizar(achada["pergunta"])} | {
            _normalizar(j) for j in jeitos}
        if not ja_conhecido and len(jeitos) < MAXIMO_OUTROS_JEITOS:
            jeitos.append(texto)
            achada["outros_jeitos"] = " | ".join(jeitos)
            celulas[f"{_letra('outros_jeitos')}{achada['linha']}"] = achada["outros_jeitos"]

        drive.atualizar_celulas(config.NOME_PLANILHA_CONHECIMENTO, celulas)


def registrar_pergunta(texto, etapa, momento):
    """
    Anota a pergunta que o bot não soube responder.
    Roda em paralelo (thread): o cliente não espera o Google responder.
    Se o Drive falhar, o atendimento continua normalmente e o erro aparece no log.
    """
    if not vale_anotar(texto, etapa):
        return

    def tarefa():
        try:
            _anotar_agora(texto, etapa, momento)
        except Exception as erro:
            print(f"[APRENDIZADO] não consegui anotar a pergunta ({erro}): {texto[:60]}")

    threading.Thread(target=tarefa, daemon=False).start()


# =================================================================
# Consulta (usada pelo resumo e, depois, pelo FAQ)
# =================================================================
def pendentes():
    """Perguntas ainda sem resposta, das que mais apareceram para as que menos."""
    def contagem(linha):
        try:
            return int(str(linha["vezes"]).strip() or 0)
        except ValueError:
            return 0

    espera = [l for l in carregar(forcar=True)
              if str(l["status"]).strip().lower() == "pendente"]
    return sorted(espera, key=contagem, reverse=True)


def respostas_aprovadas():
    """As linhas que já têm resposta escrita e status aprovada."""
    try:
        linhas = carregar()
    except Exception as erro:
        # Se o Drive falhar, o bot segue com o FAQ escrito no código.
        print(f"[APRENDIZADO] não consegui ler a base de conhecimento ({erro}).")
        return []
    return [l for l in linhas
            if str(l["status"]).strip().lower() == "aprovada" and str(l["resposta"]).strip()]


def _serve_para(texto, linha):
    """
    True se a linha aprovada responde essa pergunta.

    A linha serve quando a pergunta do cliente é a MESMA da linha, ou a mesma de
    um dos "outros jeitos" já guardados nela (veja sao_a_mesma_pergunta).
    """
    if sao_a_mesma_pergunta(texto, linha["pergunta"]):
        return True
    return any(sao_a_mesma_pergunta(texto, jeito)
               for jeito in str(linha["outros_jeitos"]).split(" | ") if jeito)


def buscar_resposta(texto):
    """
    Procura, entre as respostas aprovadas, uma que sirva para essa pergunta.
    É o que faz o bot "aprender": basta aprovar uma linha na planilha.
    Devolve o texto da resposta ou None.
    """
    for linha in respostas_aprovadas():
        if _serve_para(texto, linha):
            return str(linha["resposta"]).strip()
    return None


# =================================================================
# Resumo semanal no Telegram
# =================================================================
def texto_do_resumo():
    """Monta a mensagem do resumo, ou devolve None quando não há nada pendente."""
    espera = pendentes()
    if not espera:
        return None

    def contagem(linha):
        try:
            return int(str(linha["vezes"]).strip() or 0)
        except ValueError:
            return 0

    total_vezes = sum(contagem(l) for l in espera)
    linhas = ["📚 RESUMO DA BASE DE CONHECIMENTO", "",
              f"{len(espera)} pergunta(s) esperando resposta, "
              f"perguntadas {total_vezes} vez(es) ao todo.", "",
              "Mais perguntadas:"]
    for linha in espera[:config.RESUMO_MAXIMO_PERGUNTAS]:
        linhas.append(f"{contagem(linha)}x  {linha['pergunta']}")
    if len(espera) > config.RESUMO_MAXIMO_PERGUNTAS:
        linhas.append(f"...e mais {len(espera) - config.RESUMO_MAXIMO_PERGUNTAS}.")

    linhas += ["", "Escreva a resposta na planilha e mude o status para aprovada. "
                   f"O bot passa a responder em até {config.CONHECIMENTO_ATUALIZAR_MIN} minutos."]
    try:
        linhas.append(drive.link_da_planilha(config.NOME_PLANILHA_CONHECIMENTO))
    except Exception:
        pass        # sem o link, o resumo continua valendo
    return "\n".join(linhas)


def enviar_resumo():
    """Manda o resumo no Telegram. Devolve True se mandou."""
    texto = texto_do_resumo()
    if not texto:
        print("[APRENDIZADO] nada pendente: resumo não enviado.")
        return False
    # O resumo semanal não é um atendimento: não leva os botões de ❌ / ✅.
    enviar_alerta(texto, com_botoes=False)
    return True


_ultimo_resumo = None       # dia em que o resumo já foi enviado


async def enviar_resumo_sempre():
    """
    Roda em segundo plano na produção: olha de tempos em tempos se chegou o dia
    e a hora do resumo. Se o Drive falhar, o erro aparece no log e o bot tenta
    de novo na próxima volta. O atendimento nunca é afetado.
    """
    global _ultimo_resumo
    if not config.RESUMO_LIGADO:
        print("[APRENDIZADO] RESUMO_LIGADO está False: resumo semanal desligado.")
        return
    while True:
        try:
            agora = datetime.now(ZoneInfo(config.FUSO))
            if (agora.weekday() == config.RESUMO_DIA
                    and agora.hour == config.RESUMO_HORA
                    and _ultimo_resumo != agora.date()):
                _ultimo_resumo = agora.date()
                await asyncio.to_thread(enviar_resumo)
        except Exception as erro:
            print(f"[APRENDIZADO] não consegui enviar o resumo ({erro}).")
        await asyncio.sleep(config.RESUMO_VERIFICAR_SEG)


if __name__ == "__main__":
    # Teste rápido: python todos_aprendizado.py
    print(f"Planilha: {config.NOME_PLANILHA_CONHECIMENTO}")
    linhas = carregar(forcar=True)
    print(f"{len(linhas)} pergunta(s) anotadas até agora.")
    aprovadas = respostas_aprovadas()
    print(f"{len(aprovadas)} resposta(s) aprovada(s), que o bot já usa.")
    espera = pendentes()
    print(f"{len(espera)} aguardando resposta:\n")
    for linha in espera[:20]:
        print(f"  {linha['vezes']}x  {linha['pergunta']}")
        if linha["outros_jeitos"]:
            print(f"        também: {linha['outros_jeitos']}")
    print("\n--- Como o resumo do Telegram ficaria agora ---")
    print(texto_do_resumo() or "(nada pendente)")