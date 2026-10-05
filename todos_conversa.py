"""
O "cérebro" do chatbot.

Este código recebe: telefone do cliente, texto que o cliente mandou e devolve o texto da resposta. Isso permite testar tudo no terminal
(teste_simulador.py) antes de ligar no WhatsApp (teste_app.py / producao_app.py).

A conversa funciona como uma MÁQUINA DE ESTADOS: cada cliente está numa
"etapa" (menu, esperando a origem, esperando o peso). A mensagem que
chega é tratada de acordo com a etapa em que o cliente está.

    inicio -> menu -> origem -> destino -> peso -> medidas -> pos_cotacao -> faq -> com_atendente (bot só lembra o protocolo)

Para a cotação o bot precisa de 3 informações: ORIGEM, DESTINO, PESO e, se o cliente souber, as MEDIDAS. 
O cliente pode mandar tudo numa mensagem só ("Goiânia para Palmas, 50 kg") ou uma de cada vez.
O bot sempre pede de novo SÓ o que ainda está faltando.
"""
import random
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import todos_config as config
import todos_faq as faq
from todos_alerta import enviar_alerta
from todos_distancia import (achar_cidade_no_texto, distancia_km, nome_completo,
                       normalizar, resolver_cidade)
from todos_registro import registrar
from todos_tabela import calcular_preco, formatar_reais

# Guarda a etapa e os dados de cada cliente, usando o telefone como chave.
# (Fica na memória: se o programa reiniciar, as conversas em andamento recomeçam.)
sessoes = {}

TEXTO_HORARIO = f"🕗 Atendimento: das {config.HORA_ABRE}h às {config.HORA_FECHA}h."

# O que o bot pergunta em cada etapa da cotação
PERGUNTAS = {
    "origem": "📍 Qual a *Cidade de Origem* da carga?\n\nEx.: Goiânia - GO",
    "destino": "📍 Qual a *Cidade de Destino*?\n\nEx.: Palmas - TO",
    "peso": "⚖️ Qual o *Peso Total* da carga, em kg?\n\nEx.: 150",
    "medidas": ("📐 Você sabe as *Medidas* da carga? Elas ajudam a deixar a cotação mais precisa.\n\n"
                "Envie comprimento x largura x altura, *apenas em centímetros* (só os números).\n\n"
                "Ex.: 50x40x30\n\n"
                "Se forem vários volumes iguais: 3 caixas de 50x40x30\n\n"
                "Se não souber, digite *PULAR*."),
}

# Como o bot se refere a cada informação quando ela está faltando
NOMES = {
    "origem": "a *cidade de origem*",
    "destino": "a *cidade de destino*",
    "peso": "o *peso* da carga (em kg)",
    "medidas": "as *medidas* da carga em centímetros (ou digite PULAR)",
}

# Etapas em que o bot está esperando alguma informação da cotação
ETAPAS_COLETA = {"origem", "destino", "peso", "medidas", "escolher_origem", "escolher_destino"}


# =================================================================
# Funções auxiliares
# =================================================================
def agora_brasilia():
    return datetime.now(ZoneInfo(config.FUSO))


def esta_aberto(momento):
    """True se o momento estiver dentro do horário de atendimento."""
    return (momento.weekday() in config.DIAS_FUNCIONAMENTO
            and config.HORA_ABRE <= momento.hour < config.HORA_FECHA)


def formatar_numero(valor):
    """30.0 -> '30' ; 30.5 -> '30,5' ; 1000 -> '1.000'"""
    texto = f"{valor:,.2f}".rstrip("0").rstrip(".")      # '1,000' ou '30.5'
    return texto.replace(",", "X").replace(".", ",").replace("X", ".")


def _para_numero(texto):
    """'1.000' -> 1000 ; '30,5' -> 30.5 ; '30.5' -> 30.5"""
    if re.fullmatch(r"\d{1,3}(\.\d{3})+(,\d+)?", texto):   # ponto de milhar
        texto = texto.replace(".", "")
    return float(texto.replace(",", "."))


def ler_peso(texto):
    """Entende '30', '30kg', '30,5 kg', '1.000' e devolve um número (ou None)."""
    t = texto.lower()
    for palavra in ("kg", "quilos", "quilo", "kilos"):
        t = t.replace(palavra, "")
    t = t.replace(" ", "")
    try:
        peso = _para_numero(t)
    except ValueError:
        return None
    return peso if peso > 0 else None


# Um número seguido de kg/quilos. Ex.: "50kg", "30,5 kg", "1.000 quilos"
REGEX_PESO = re.compile(r"(\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:[.,]\d+)?)\s*(?:kg|quilos?|kilos?)\b",
                        re.IGNORECASE)


def extrair_peso(texto):
    """Procura um peso COM unidade dentro de uma frase. Devolve (peso, frase_sem_o_peso)."""
    achado = REGEX_PESO.search(texto)
    if not achado:
        return None, texto
    resto = texto[:achado.start()] + " " + texto[achado.end():]
    return _para_numero(achado.group(1)), resto


# Palavras que separam origem e destino: "Goiânia PARA Palmas", "Goiânia X Palmas"
REGEX_SEPARADOR = re.compile(r" (?:PARA|PRA|ATE|X|DESTINO) ")

# Medidas: "50x40x30" ou, com quantidade na frente, "3x50x40x30"
_NUM = r"(\d+(?:[.,]\d+)?)"
_X = r"\s*[xX×*]\s*"
REGEX_4_NUMEROS = re.compile(_NUM + _X + _NUM + _X + _NUM + _X + _NUM)
REGEX_3_NUMEROS = re.compile(_NUM + _X + _NUM + _X + _NUM)
REGEX_QUANTIDADE = re.compile(
    r"(\d+)\s*(?:volumes?|caixas?|pacotes?|pallets?|paletes?|unidades?|pe[çc]as?|fardos?|sacos?)",
    re.IGNORECASE)


# Unidade diferente de centímetros escrita pelo cliente: "1x1x1 m", "2 metros", "500 mm"
# (o (?<![^\W\d_]) exige que antes não haja uma letra: assim o "m" de "cm" ou de
#  "também" não é confundido com metro)
REGEX_OUTRA_UNIDADE = re.compile(r"(?<![^\W\d_])(m|mt|mts|metros?|mm|mil[ií]metros?|pol|polegadas?)\b",
                                 re.IGNORECASE)

MEDIDA_MAXIMA_CM = 1500   # 15 metros: nenhum volume do fracionado passa disso


def usou_outra_unidade(texto):
    """True se o cliente escreveu as medidas em metros, milímetros ou polegadas."""
    return bool(REGEX_OUTRA_UNIDADE.search(texto))


def ler_medidas(texto):
    """
    Entende as medidas da carga, SEMPRE em centímetros.
    Devolve (quantidade, [comprimento, largura, altura] em cm) ou None se não entender.
      '50x40x30'             -> (1, [50, 40, 30])
      '50 x 40 x 30 cm'      -> (1, [50, 40, 30])
      '3 caixas de 50x40x30' -> (3, [50, 40, 30])
      '3x50x40x30'           -> (3, [50, 40, 30])
    """
    quantidade = 1
    achado4 = REGEX_4_NUMEROS.search(texto)
    if achado4:
        quantidade = int(_para_numero(achado4.group(1)))
        numeros = achado4.groups()[1:]
    else:
        achado3 = REGEX_3_NUMEROS.search(texto)
        if not achado3:
            return None
        numeros = achado3.groups()
        qtd = REGEX_QUANTIDADE.search(texto)
        if qtd:
            quantidade = int(qtd.group(1))

    medidas_cm = [_para_numero(n) for n in numeros]
    if quantidade < 1 or any(m <= 0 or m > MEDIDA_MAXIMA_CM for m in medidas_cm):
        return None
    return quantidade, medidas_cm


def calcular_peso_cubado(quantidade, medidas_cm):
    """
    Peso cubado = volume em m³ × fator de cubagem.
    As medidas chegam em centímetros; dividimos cada uma por 100 para virar metros.
      Ex.: 3 caixas de 50x40x30 cm -> 0,5 × 0,4 × 0,3 × 3 = 0,18 m³ × 300 = 54 kg
    """
    comprimento, largura, altura = (m / 100 for m in medidas_cm)
    metros_cubicos = comprimento * largura * altura * quantidade
    return round(metros_cubicos * config.FATOR_CUBAGEM, 1)


def quer_cotacao(comando):
    """Detecta frases como 'quero uma cotação' ou 'quanto custa o frete'."""
    palavras = comando.split()
    return any(p in palavras for p in ("COTACAO", "COTAR", "ORCAMENTO", "QUANTO", "CUSTA", "PRECO"))


def texto_menu(saudacao=False):
    linhas = []
    if saudacao:
        linhas += [f"Olá! 👋 Bem-vindo(a) à *{config.NOME_EMPRESA}*.",
                   "Sou o assistente virtual e posso te passar uma cotação de frete fracionado na hora.",
                   ""]
    linhas += ["Escolha uma opção:",
               "1️⃣ Fazer uma cotação de frete",
               "2️⃣ Dúvidas frequentes",
               "3️⃣ Falar com um atendente",
               "",
               "_A qualquer momento, digite MENU para voltar aqui._"]
    return "\n".join(linhas)


def _sessao_expirou(sessao, momento):
    if sessao["etapa"] == "com_atendente":
        limite = timedelta(hours=config.PAUSA_ATENDENTE_HORAS)
    else:
        limite = timedelta(minutes=config.TEMPO_SESSAO_MIN)
    return momento - sessao["ultima"] > limite


def _campo_da_etapa(etapa):
    """'escolher_origem' -> 'origem' ; 'peso' -> 'peso'"""
    return etapa.replace("escolher_", "")


# =================================================================
# Função principal: recebe a mensagem e devolve a resposta
# =================================================================
def responder(telefone, texto, momento=None):
    """
    Devolve o texto de resposta, ou None quando o bot não precisa responder
    (o cliente já foi passado para um atendente e o protocolo foi lembrado há pouco).
    """
    momento = momento or agora_brasilia()

    sessao = sessoes.get(telefone)
    if sessao is None or _sessao_expirou(sessao, momento):
        sessao = {"etapa": "inicio", "dados": {}, "ultima": momento}
        sessoes[telefone] = sessao
    sessao["ultima"] = momento
    sessao["lembrete_enviado"] = False     # o cliente respondeu: pode lembrar de novo no futuro

    texto = (texto or "").strip()
    comando = normalizar(texto)

    # --- Comandos que funcionam em qualquer etapa ---
    if comando in ("MENU", "INICIO", "VOLTAR"):
        sessao["etapa"], sessao["dados"] = "menu", {}
        return texto_menu()

    if sessao["etapa"] == "com_atendente":
        # O atendente fala com o cliente pelo WhatsApp oficial da empresa.
        # Se o cliente escrever de novo aqui, o bot lembra o protocolo (no máximo
        # uma vez a cada TEMPO_SESSAO_MIN minutos, para não ficar repetindo).
        return _lembrar_protocolo(sessao, momento)

    if "ATENDENTE" in comando.split() or comando in ("HUMANO", "FALAR COM ALGUEM"):
        return chamar_atendente(telefone, sessao, momento, "Cliente pediu para falar com um atendente")

    # --- Encaminha para a função da etapa atual ---
    funcao_da_etapa = ETAPAS[sessao["etapa"]]
    return funcao_da_etapa(telefone, sessao, texto, momento)


# =================================================================
# Início e menu
# =================================================================
def _tem_dados_de_cotacao(texto):
    """True se a frase já traz peso ou 'cidade PARA cidade' (ex.: 'Goiânia para Palmas 50kg')."""
    teste = {"dados": {}}
    confirmados, _ = _absorver(teste, texto)
    return bool(confirmados)


def etapa_inicio(telefone, sessao, texto, momento):
    """Primeira mensagem do cliente."""
    comando = normalizar(texto)
    if comando in ("1", "2", "3"):          # já escolheu uma opção do menu
        sessao["etapa"] = "menu"
        return etapa_menu(telefone, sessao, texto, momento)
    if quer_cotacao(comando) or _tem_dados_de_cotacao(texto):
        return (f"Olá! 👋 Bem-vindo(a) à *{config.NOME_EMPRESA}*.\n\n"
                + iniciar_cotacao(telefone, sessao, momento, texto))

    sessao["etapa"] = "menu"
    resposta_faq = faq.buscar_por_texto(texto)
    if resposta_faq:
        return f"Olá! 👋 Bem-vindo(a) à *{config.NOME_EMPRESA}*.\n\n{resposta_faq}\n\n" + texto_menu()
    return texto_menu(saudacao=True)


def etapa_menu(telefone, sessao, texto, momento):
    comando = normalizar(texto)
    if comando == "1":
        return iniciar_cotacao(telefone, sessao, momento)
    if quer_cotacao(comando) or _tem_dados_de_cotacao(texto):
        return iniciar_cotacao(telefone, sessao, momento, texto)
    if comando == "2":
        sessao["etapa"] = "faq"
        return faq.texto_lista()
    if comando == "3":
        return chamar_atendente(telefone, sessao, momento, "Cliente pediu para falar com um atendente")

    resposta_faq = faq.buscar_por_texto(texto)
    if resposta_faq:
        return f"{resposta_faq}\n\n" + texto_menu()
    return "Desculpe, não entendi. 🤔\n\n" + texto_menu()


# =================================================================
# Cotação: coleta de origem, destino e peso
# =================================================================
def iniciar_cotacao(telefone, sessao, momento, texto=""):
    """Começa uma cotação. Se a mensagem já trouxer dados, aproveita."""
    sessao["dados"] = {}
    confirmados, _ = _absorver(sessao, texto) if texto else ([], "")
    if not confirmados:
        confirmados = ["📦 Vamos lá! Para a cotação, preciso da origem, do destino e do peso da carga."]
    return _continuar(telefone, sessao, momento, confirmados)


def _absorver(sessao, texto):
    """
    Tenta tirar da mensagem as informações que ainda faltam:
      - peso com unidade ("50kg");
      - origem e destino no formato "cidade PARA cidade".
    Devolve (lista de confirmações, resto do texto que não foi usado).
    """
    dados = sessao["dados"]
    confirmados = []

    peso, resto = extrair_peso(texto)
    if peso and "peso" not in dados:
        dados["peso"] = peso
        confirmados.append(f"✅ Peso: {formatar_numero(peso)} kg")

    partes = REGEX_SEPARADOR.split(f" {normalizar(resto)} ", maxsplit=1)
    if len(partes) == 2:
        origem = achar_cidade_no_texto(partes[0])
        destino = achar_cidade_no_texto(partes[1])
        if origem and "origem" not in dados:
            dados["origem"] = origem
            confirmados.insert(0, f"✅ Origem: {nome_completo(origem)}")
        if destino and "destino" not in dados:
            dados["destino"] = destino
            confirmados.insert(1 if origem else 0, f"✅ Destino: {nome_completo(destino)}")
        if origem or destino:
            resto = ""
    return confirmados, resto


def _continuar(telefone, sessao, momento, confirmados):
    """
    Olha o que já temos e pede a PRÓXIMA informação que falta.
    Quando origem, destino e peso estiverem completos, pede as medidas.
    """
    prefixo = "\n".join(confirmados) + "\n\n" if confirmados else ""
    dados = sessao["dados"]

    if dados.get("peso", 0) > config.PESO_MAXIMO_KG:
        sessao["etapa"], sessao["dados"] = "menu", {}
        return (f"No momento trabalhamos com cargas de até {formatar_numero(config.PESO_MAXIMO_KG)} kg. "
                "Se tiver outra carga dentro desse limite, é só fazer uma nova cotação. 🙂\n\n"
                + texto_menu())

    for campo in ("origem", "destino", "peso"):
        if campo not in dados:
            sessao["etapa"] = campo
            return prefixo + PERGUNTAS[campo]

    sessao["etapa"] = "medidas"
    return prefixo + PERGUNTAS["medidas"]


def _pedir_de_novo(campo, motivo, texto_cliente=""):
    """
    Monta a mensagem pedindo de novo a informação que faltou.
    Se o cliente fez uma pergunta no meio (ex.: 'tem seguro?'), responde antes.
    """
    resposta_faq = faq.buscar_por_texto(texto_cliente) if texto_cliente else None
    if resposta_faq:
        return (f"{resposta_faq}\n\n"
                f"Para continuar a cotação, me envie {NOMES[campo]}.\n\n{PERGUNTAS[campo]}")
    return f"⚠️ {motivo}\nPor favor, envie novamente {NOMES[campo]}.\n\n{PERGUNTAS[campo]}"


def etapa_coleta(telefone, sessao, texto, momento):
    """Usada nas etapas 'origem', 'destino' e 'peso'."""
    campo = sessao["etapa"]
    confirmados, resto = _absorver(sessao, texto)

    # A mensagem já trouxe a informação desta etapa (ou um peso acima do limite)
    if campo in sessao["dados"] or sessao["dados"].get("peso", 0) > config.PESO_MAXIMO_KG:
        return _continuar(telefone, sessao, momento, confirmados)

    prefixo = "\n".join(confirmados) + "\n\n" if confirmados else ""
    resto = resto.strip()

    # Mandou só outra informação (ex.: o peso quando pedimos a origem): pede de novo esta
    if confirmados and not resto:
        return prefixo + f"Agora só falta {NOMES[campo]}.\n\n{PERGUNTAS[campo]}"

    if not resto:
        return prefixo + _pedir_de_novo(campo, "Não recebi essa informação.")

    if campo == "peso":
        peso = ler_peso(resto)
        if peso is None:
            return prefixo + _pedir_de_novo("peso", "Não consegui identificar o peso.", resto)
        sessao["dados"]["peso"] = peso
        return _continuar(telefone, sessao, momento,
                          confirmados + [f"✅ Peso: {formatar_numero(peso)} kg"])

    return prefixo + _receber_cidade(telefone, sessao, momento, resto, campo)


def _receber_cidade(telefone, sessao, momento, texto, campo):
    """Resposta com UMA cidade (origem ou destino)."""
    situacao, resultado = resolver_cidade(texto)
    if situacao != "ok":
        # talvez a cidade esteja no meio de uma frase ("é de goiania go")
        cidade = achar_cidade_no_texto(texto)
        if cidade:
            situacao, resultado = "ok", cidade

    if situacao == "ok":
        return _cidade_confirmada(telefone, sessao, momento, campo, resultado)

    if situacao == "ambigua":
        sessao["opcoes"] = resultado
        sessao["etapa"] = f"escolher_{campo}"
        lista = "\n".join(f"{i}. {nome_completo(c)}" for i, c in enumerate(resultado, start=1))
        return f"Encontrei mais de uma cidade com esse nome. Digite o número da correta:\n{lista}"

    motivo = "Não encontrei essa cidade."
    if resultado:
        motivo += "\nVocê quis dizer: " + ", ".join(resultado) + "?"
    return _pedir_de_novo(campo, motivo, texto)


def _escolher_cidade(telefone, sessao, texto, momento):
    """Cliente escolhe, pelo número, uma das cidades com nome repetido."""
    campo = _campo_da_etapa(sessao["etapa"])
    opcoes = sessao.get("opcoes", [])
    if texto.isdigit() and 1 <= int(texto) <= len(opcoes):
        return _cidade_confirmada(telefone, sessao, momento, campo, opcoes[int(texto) - 1])
    if not texto.strip() or texto.isdigit():     # vazio ou número que não está na lista
        lista = "\n".join(f"{i}. {nome_completo(c)}" for i, c in enumerate(opcoes, start=1))
        return f"⚠️ Por favor, digite o número da cidade correta:\n{lista}"
    return _receber_cidade(telefone, sessao, momento, texto, campo)   # talvez tenha digitado o nome de novo


def _cidade_confirmada(telefone, sessao, momento, campo, cidade):
    sessao["dados"][campo] = cidade
    sessao.pop("opcoes", None)
    rotulo = "Origem" if campo == "origem" else "Destino"
    return _continuar(telefone, sessao, momento, [f"✅ {rotulo}: {nome_completo(cidade)}"])


# =================================================================
# Cotação: medidas (peso cubado) e cálculo final
# =================================================================
def etapa_medidas(telefone, sessao, texto, momento):
    comando = normalizar(texto)
    if comando in ("PULAR", "PULA", "NAO SEI", "NAO", "N", "SEM MEDIDAS") or comando.startswith("NAO SEI"):
        return _finalizar_cotacao(telefone, sessao, momento, None)

    # Padrão da empresa: medidas sempre em centímetros
    if usou_outra_unidade(texto):
        return _pedir_de_novo("medidas", "As medidas precisam estar *apenas em centímetros* "
                                         "(1 metro = 100 cm). Ex.: 1x1x1,5 m vira 100x100x150.")

    medidas = ler_medidas(texto)
    if medidas is None:
        return _pedir_de_novo("medidas", "Não consegui entender as medidas.", texto)
    return _finalizar_cotacao(telefone, sessao, momento, medidas)


def _finalizar_cotacao(telefone, sessao, momento, medidas):
    """Calcula peso considerado, distância e preço, e mostra a cotação."""
    dados = sessao["dados"]
    dados["peso_cubado"] = None
    dados["medidas"] = medidas
    if medidas:
        quantidade, dimensoes = medidas
        dados["peso_cubado"] = calcular_peso_cubado(quantidade, dimensoes)

    # No fracionado, cobra-se pelo MAIOR entre o peso real e o peso cubado
    dados["peso_considerado"] = max(dados["peso"], dados["peso_cubado"] or 0)
    dados["km"] = distancia_km(dados["origem"], dados["destino"])

    if dados["peso_considerado"] > config.PESO_MAXIMO_KG:
        return chamar_atendente(
            telefone, sessao, momento, evento="carga_volumosa",
            motivo=f"Carga volumosa — peso cubado de {formatar_numero(dados['peso_cubado'])} kg",
            inicio=(f"Pelas medidas, sua carga é bem volumosa (peso cubado de "
                    f"{formatar_numero(dados['peso_cubado'])} kg). A cotação dela é feita "
                    "pela nossa equipe. 🚚\n"))

    dados["valor"] = calcular_preco(dados["peso_considerado"], dados["km"])
    if dados["valor"] is None:
        return chamar_atendente(
            telefone, sessao, momento, evento="fora_da_tabela",
            motivo="Rota fora da tabela automática — calcular cotação manualmente",
            inicio="Para essa rota, a cotação precisa ser feita pela nossa equipe. 🚚\n")

    _registrar_evento(telefone, dados, momento, "cotacao")
    sessao["etapa"] = "pos_cotacao"
    return texto_cotacao(dados)


def _texto_medidas(medidas):
    """(3, [50, 40, 30]) -> '3 volumes de 50x40x30 cm'"""
    quantidade, dimensoes_cm = medidas
    cm = "x".join(formatar_numero(m) for m in dimensoes_cm)
    return f"{quantidade} volume{'s' if quantidade > 1 else ''} de {cm} cm"


def texto_cotacao(dados):
    linhas = [
        "📦 *Cotação de frete fracionado*",
        "",
        f"Origem: {nome_completo(dados['origem'])}",
        f"Destino: {nome_completo(dados['destino'])}",
        f"Distância aproximada: {dados['km']} km",
    ]
    if dados["peso_cubado"] is not None:
        linhas += [
            f"Peso real: {formatar_numero(dados['peso'])} kg",
            f"Peso cubado: {formatar_numero(dados['peso_cubado'])} kg ({_texto_medidas(dados['medidas'])})",
            f"Peso considerado: {formatar_numero(dados['peso_considerado'])} kg",
            "_No frete fracionado, vale o maior entre o peso real e o peso cubado._",
        ]
    else:
        linhas += [
            f"Peso: {formatar_numero(dados['peso'])} kg",
            "_Cotação feita só pelo peso. Se a carga for volumosa, o valor pode mudar._",
        ]
    linhas += [
        "",
        f"💰 *Valor estimado: {formatar_reais(dados['valor'])}*",
        "_Valor negociável. O valor final é confirmado pelo atendente._",
        "",
        TEXTO_HORARIO,
        "",
        "O que deseja fazer?",
        "1️⃣ Negociar com um atendente",
        "2️⃣ Fazer nova cotação",
        "3️⃣ Voltar ao menu",
    ]
    return "\n".join(linhas)


def etapa_pos_cotacao(telefone, sessao, texto, momento):
    comando = normalizar(texto)
    if comando == "1" or "NEGOCIAR" in comando.split():
        return chamar_atendente(telefone, sessao, momento, "Cliente quer NEGOCIAR a cotação",
                                evento="pediu_negociacao")
    if comando == "2":
        return iniciar_cotacao(telefone, sessao, momento)
    if comando == "3":
        sessao["etapa"] = "menu"
        return texto_menu()

    resposta_faq = faq.buscar_por_texto(texto)
    opcoes = "1️⃣ Negociar com um atendente\n2️⃣ Fazer nova cotação\n3️⃣ Voltar ao menu"
    if resposta_faq:
        return f"{resposta_faq}\n\n{opcoes}"
    return f"Digite o número de uma opção:\n{opcoes}"


def etapa_faq(telefone, sessao, texto, momento):
    if texto.isdigit():
        resposta = faq.resposta_por_numero(int(texto))
        if resposta:
            return f"{resposta}\n\nDigite outro número para ver mais dúvidas, ou *MENU* para voltar."
    resposta = faq.buscar_por_texto(texto)
    if resposta:
        return f"{resposta}\n\nDigite outro número para ver mais dúvidas, ou *MENU* para voltar."
    return faq.texto_lista()


# =================================================================
# Quando o cliente some ou manda áudio/foto no meio da cotação
# =================================================================
def _pedido_da_etapa(sessao):
    """Texto pedindo a informação que o bot está esperando agora."""
    etapa = sessao["etapa"]
    if etapa.startswith("escolher_"):
        lista = "\n".join(f"{i}. {nome_completo(c)}" for i, c in enumerate(sessao.get("opcoes", []), 1))
        return f"Digite o número da cidade correta:\n{lista}"
    return f"Falta só {NOMES[etapa]}.\n\n{PERGUNTAS[etapa]}"


def verificar_lembretes(momento=None):
    """
    Procura clientes que pararam no meio da cotação há LEMBRETE_MIN minutos
    e devolve uma lista de (telefone, mensagem de lembrete).
    Cada cliente recebe no máximo UM lembrete até responder de novo.
    O todos_whatsapp.py chama esta função a cada minuto.
    """
    momento = momento or agora_brasilia()
    lembretes = []
    for telefone, sessao in sessoes.items():
        parado = momento - sessao["ultima"]
        if (sessao["etapa"] in ETAPAS_COLETA
                and not sessao.get("lembrete_enviado")
                and parado >= timedelta(minutes=config.LEMBRETE_MIN)
                and not _sessao_expirou(sessao, momento)):
            sessao["lembrete_enviado"] = True
            lembretes.append((telefone, "Oi! Ainda está aí? 🙂 Para terminar a sua cotação, "
                                        + _pedido_da_etapa(sessao)[0].lower()
                                        + _pedido_da_etapa(sessao)[1:]))
    return lembretes


def responder_nao_texto(telefone, momento=None):
    """Resposta para áudio, foto, figurinha etc."""
    momento = momento or agora_brasilia()
    sessao = sessoes.get(telefone)
    if sessao and sessao["etapa"] == "com_atendente":
        return _lembrar_protocolo(sessao, momento)
    aviso = "Por aqui eu consigo entender só mensagens escritas. 🙏"
    if sessao and sessao["etapa"] in ETAPAS_COLETA and not _sessao_expirou(sessao, momento):
        sessao["ultima"] = momento
        return f"{aviso}\n{_pedido_da_etapa(sessao)}"
    return f"{aviso}\nDigite MENU para ver as opções."


# =================================================================
# Chamar um atendente (envia o alerta para o celular)
# =================================================================
# Letras e números fáceis de ler (sem 0/O, 1/I/L), para o código do protocolo
_CARACTERES_PROTOCOLO = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"


def gerar_protocolo(momento):
    """
    Cria o número do atendimento, ex.: ATD-04102026-1432-K7
    (dia/mês/ano - hora:minuto - código sorteado).
    Não usa contagem (001, 002...) porque o servidor grátis pode reiniciar e
    a contagem voltaria do zero, repetindo números. Data com ano + hora + código
    sorteado não se repete, mesmo depois de um reinício ou de muitos anos.
    """
    codigo = "".join(random.choice(_CARACTERES_PROTOCOLO) for _ in range(2))
    return f"{config.PREFIXO_PROTOCOLO}-{momento.strftime('%d%m%Y-%H%M')}-{codigo}"


def _link_whatsapp(telefone):
    """
    Link que abre a conversa com o cliente no WhatsApp com um toque.
    Celulares do Brasil às vezes chegam sem o 9 extra: aqui ele é colocado de volta.
    """
    if telefone.startswith("55") and len(telefone) == 12 and telefone[4] in "6789":
        telefone = telefone[:4] + "9" + telefone[4:]
    return f"https://wa.me/{telefone}"


def _texto_whatsapp_oficial():
    """'WhatsApp oficial da empresa' ou, se configurado, com o número."""
    if config.WHATSAPP_OFICIAL_EMPRESA:
        return f"WhatsApp oficial da {config.NOME_EMPRESA}: {config.WHATSAPP_OFICIAL_EMPRESA}"
    return f"WhatsApp oficial da {config.NOME_EMPRESA}"


def _lembrar_protocolo(sessao, momento):
    """
    O cliente escreveu de novo depois de chamar o atendente.
    O bot lembra o protocolo, mas no máximo uma vez a cada TEMPO_SESSAO_MIN
    minutos, para não responder a cada mensagem.
    """
    ultimo = sessao.get("ultimo_aviso_protocolo")
    if ultimo and momento - ultimo < timedelta(minutes=config.TEMPO_SESSAO_MIN):
        return None
    sessao["ultimo_aviso_protocolo"] = momento
    return (f"Seu atendimento já foi encaminhado. 📋 Protocolo: *{sessao.get('protocolo', '-')}*\n\n"
            f"Um atendente vai te chamar pelo {_texto_whatsapp_oficial()}.\n\n"
            "_Se quiser voltar ao atendimento automático, digite MENU._")


def chamar_atendente(telefone, sessao, momento, motivo, inicio="", evento=None):
    """
    Passa o cliente para um atendente humano:
      1. gera o protocolo;
      2. registra a cotação no CSV (quando houver), já com o protocolo;
      3. manda o alerta para o Telegram do atendente;
      4. avisa o cliente, mostrando o protocolo.
    """
    dados = sessao.get("dados", {})
    protocolo = gerar_protocolo(momento)
    sessao["protocolo"] = protocolo
    sessao["ultimo_aviso_protocolo"] = momento

    if evento:
        _registrar_evento(telefone, dados, momento, evento, protocolo)

    linhas = [f"🔔 NOVO ATENDIMENTO — Protocolo {protocolo}",
              f"Empresa: {config.NOME_EMPRESA}",
              f"Motivo: {motivo}",
              f"Cliente (WhatsApp): +{telefone}",
              f"Abrir conversa: {_link_whatsapp(telefone)}",
              f"Horário: {momento.strftime('%d/%m %H:%M')}"]
    if "origem" in dados and "destino" in dados:
        linhas.append(f"Rota: {nome_completo(dados['origem'])} → {nome_completo(dados['destino'])}")
    if dados.get("km") is not None:
        linhas.append(f"Distância: {dados['km']} km")
    if "peso" in dados:
        linhas.append(f"Peso real: {formatar_numero(dados['peso'])} kg")
    if dados.get("medidas"):
        linhas.append(f"Medidas: {_texto_medidas(dados['medidas'])} | "
                      f"Peso cubado: {formatar_numero(dados['peso_cubado'])} kg")
    elif "peso_considerado" in dados:
        # Chegou a fazer a cotação, mas o cliente pulou as medidas
        linhas.append("⚠️ Cliente NÃO informou as medidas — confirmar antes de fechar o valor")
    if dados.get("valor"):
        linhas.append(f"Cotação do bot: {formatar_reais(dados['valor'])}")
    enviar_alerta("\n".join(linhas))

    sessao["etapa"] = "com_atendente"

    if esta_aberto(momento):
        quando = "em instantes"
    else:
        quando = (f"assim que abrirmos (atendimento das {config.HORA_ABRE}h "
                  f"às {config.HORA_FECHA}h)")
    aviso = ("✅ Pronto! Já avisei nossa equipe.\n"
             f"📋 Seu número de protocolo é: *{protocolo}*\n\n"
             f"Um atendente vai te chamar pelo {_texto_whatsapp_oficial()} {quando}.")
    return f"{inicio}{aviso}\n\n_Se quiser voltar ao atendimento automático, digite MENU._"


def _registrar_evento(telefone, dados, momento, evento, protocolo=""):
    registrar({
        "data_hora": momento.strftime("%Y-%m-%d %H:%M"),
        "protocolo": protocolo,
        "telefone": telefone,
        "origem": nome_completo(dados["origem"]),
        "destino": nome_completo(dados["destino"]),
        "distancia_km": dados.get("km"),
        "peso_kg": dados.get("peso"),
        "medidas": _texto_medidas(dados["medidas"]) if dados.get("medidas") else "",
        "peso_cubado_kg": dados.get("peso_cubado"),
        "peso_considerado_kg": dados.get("peso_considerado"),
        "valor": dados.get("valor"),
        "evento": evento,
    })


# Liga o nome de cada etapa à função que a trata.
ETAPAS = {
    "inicio": etapa_inicio,
    "menu": etapa_menu,
    "origem": etapa_coleta,
    "destino": etapa_coleta,
    "peso": etapa_coleta,
    "escolher_origem": _escolher_cidade,
    "escolher_destino": _escolher_cidade,
    "medidas": etapa_medidas,
    "pos_cotacao": etapa_pos_cotacao,
    "faq": etapa_faq,
}