"""
O "cérebro" do chatbot.

Este código recebe: telefone do cliente, texto que o cliente mandou e devolve o texto da resposta. Isso permite testar tudo no terminal
(teste_simulador.py) antes de ligar no WhatsApp (teste_app.py / producao_app.py).

A conversa funciona como uma MÁQUINA DE ESTADOS: cada cliente está numa
"etapa" (menu, esperando a origem, esperando o peso). A mensagem que
chega é tratada de acordo com a etapa em que o cliente está.

    inicio -> cnpj -> menu -> origem -> destino -> peso -> medidas -> pos_cotacao -> faq

A empresa transporta só para outras empresas, então o bot se apresenta e já pede o
CNPJ. Sem um CNPJ bem formado a cotação não começa (veja todos_cnpj.py). O cliente
digita só os 14 caracteres, sem ponto, barra ou traço: a máscara é colocada depois
pelo código, na planilha e no alerta do Telegram. Dúvidas gerais o bot responde
mesmo antes do CNPJ, porque isso é informação pública. Quem disser que é pessoa
física vai direto para o atendente.

O CNPJ e o NOME valem para UMA conversa, e não para sempre. Os dois são pedidos
de novo quando:
  - o cliente fica TEMPO_SESSAO_MIN minutos sem escrever e volta depois;
  - o cliente é passado para um atendente. A conversa com o bot termina ali.
A ideia é que toda cotação nova tenha o CNPJ e o nome confirmados na hora. O
WhatsApp pode ser o número de uma empresa, e não de uma pessoa: quem escrever na
próxima conversa pode ser outro funcionário.

O bot NUNCA fica bloqueado esperando o atendente. Ele não tem como saber se o
cliente está sendo atendido, porque o atendente responde por outro número. Então
depois de encaminhar, a próxima mensagem já é uma cotação nova, com protocolo
novo. Assim quem precisa de várias cotações no mesmo dia nunca fica esperando.

Para a cotação o bot precisa de 3 informações: ORIGEM, DESTINO, PESO e, se o cliente souber, as MEDIDAS. 
O cliente pode mandar tudo numa mensagem só ("Goiânia para Palmas, 50 kg") ou uma de cada vez.
O bot sempre pede de novo SÓ o que ainda está faltando.

Quando o bot não sabe responder uma pergunta de verdade, ele ADMITE que não sabe
e oferece um atendente, em vez de fingir que entendeu e mostrar o menu.
A pergunta também é anotada na planilha "base_conhecimento"
(veja o todos_aprendizado.py), para virar resposta nova depois.

Quando o bot chama um atendente sozinho (sem o cliente escolher a opção do menu):
  - o cliente fala de FRETE DEDICADO (um veículo só para a carga dele), com a palavra
    "dedicado", "carga fechada", "lotação" ou com o nome do caminhão ("carreta", "bitruck");
    o bot só cota frete FRACIONADO;
  - o cliente pede para falar com uma pessoa, mesmo com outras palavras
    ("posso falar com o dono?", "quero contatar o seu superior");
    se ele mandar só a palavra ("dono", "gerente"), o bot pergunta antes se ele quer um atendente;
  - o cliente relata um problema com uma carga já enviada (avaria, extravio, reclamação);
  - o cliente pede desconto ou acha o valor alto: quem negocia preço é o atendente;
  - o cliente mostra que está em dúvida ("não estou entendendo", "como assim?", "?");
  - o bot não consegue ajudar 3 vezes seguidas: não entende a mensagem, ou o
    cliente repete a mesma pergunta (o número fica em INSISTENCIA_MAXIMA, no todos_config.py).
"""
import random
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import todos_aprendizado as aprendizado
import todos_cep as cep
import todos_cnpj as cnpj
import todos_config as config
import todos_faq as faq
import todos_alerta as alerta
from todos_alerta import enviar_alerta
from todos_distancia import (achar_cidade_no_texto, achar_todas_as_cidades,
                       achar_ultima_cidade_no_texto, distancia_km, nome_completo,
                       normalizar, resolver_cidade)
from todos_registro import registrar
from todos_tabela import calcular_preco, formatar_reais

# Guarda a etapa e os dados de cada cliente, usando o telefone como chave.
# (Fica na memória: se o programa reiniciar, as conversas em andamento recomeçam.)
sessoes = {}

TEXTO_HORARIO = f"Atendimento das {config.HORA_ABRE}h às {config.HORA_FECHA}h."

# O que o bot pergunta em cada etapa da cotação.
# Os emojis saíram de propósito: ficam só os números das opções, que servem para
# o cliente saber o que digitar. Emoji de enfeite deixa a conversa com cara de
# robô, e quem escreve no WhatsApp da empresa é uma pessoa.
PERGUNTAS = {
    "origem": "Qual a *cidade de origem* da carga?\n\nEx.: Goiânia - GO",
    "destino": "E qual a *cidade de destino*?\n\nEx.: Palmas - TO",
    "peso": "Qual o *peso total* da carga, em kg?\n\nEx.: 150",
    "medidas": ("Você sabe as *medidas* da carga? Elas deixam a cotação mais precisa.\n\n"
                "Me envie comprimento x largura x altura, em *centímetros*.\n\n"
                "Ex.: 50x40x30\n\n"
                "Se forem vários volumes iguais: 3 caixas de 50x40x30\n\n"
                "Se os volumes tiverem tamanhos diferentes, me mande um por linha:\n"
                "2 caixas de 50x40x30\n"
                "3 caixas de 80x60x40\n\n"
                "Se preferir escrever em metros, pode escrever, é só colocar o *m*: 1x1x1,5 m\n\n"
                "Se você não souber, digite *PULAR*."),
}

# As mesmas duas perguntas, para quem começou a rota pelo CEP. O bot pergunta
# sempre pela CIDADE, que é o jeito mais simples de entender. Só depois que o
# cliente escolhe o CEP é que ele passa a pedir CEP, para a rota não misturar os
# dois formatos.
PERGUNTAS_CEP = {
    "origem": "Qual o *CEP de origem* da carga?\n\nEx.: 74486-225",
    "destino": "E qual o *CEP de destino*?\n\nEx.: 39948-000",
}

# Como o bot se refere a cada informação quando ela está faltando
NOMES = {
    "origem": "a *cidade de origem*",
    "destino": "a *cidade de destino*",
    "peso": "o *peso* da carga (em kg)",
    "medidas": "as *medidas* da carga, em centímetros (ou digite PULAR)",
}

# Etapas em que o bot está esperando alguma informação da cotação
NOMES_CEP = {
    "origem": "o *CEP de origem*",
    "destino": "o *CEP de destino*",
}

# Expressões em que o cliente diz, com todas as letras, de onde a carga SAI e
# para onde ela VAI. Elas são usadas só para preencher a ponta da rota que ficou
# faltando depois da leitura normal ("de X para Y").
#
# Repare que nenhuma delas fala do CLIENTE. "sou de", "moro em" e "tem sede em"
# ficam de fora de propósito: elas dizem onde a PESSOA está, e não de onde a
# carga sai, e o bot não pode confundir uma coisa com a outra.
MARCAS_DE_ORIGEM = ("sai de", "sai da", "saem de", "saindo de", "saindo da",
                    "parte de", "partindo de", "origem", "remetente em",
                    "coleta em", "coleta no", "coleta na", "coletar em",
                    "retirada em", "retirar em", "buscar em", "busca em",
                    "carga esta em", "mercadoria esta em", "material esta em")
MARCAS_DE_DESTINO = ("entrega em", "entrega no", "entrega na", "entregar em",
                     "entregue em", "entregar no", "destino", "destinatario em",
                     "chega em", "vai para", "seguir para", "segue para")

# Jeitos de dizer, dentro de uma mensagem maior, que não vai mandar as medidas.
# Sem isso o bot perguntaria as medidas para quem acabou de escrever que não sabe.
SEM_MEDIDAS = ("NAO SEI AS MEDIDAS", "NAO SEI AS MEDIDA", "NAO SEI A MEDIDA",
               "NAO SEI AS DIMENSOES", "NAO TENHO AS MEDIDAS", "NAO TENHO AS MEDIDA",
               "NAO TENHO A MEDIDA", "NAO TENHO AS DIMENSOES", "SEM AS MEDIDAS",
               "SEM MEDIDAS", "NAO SEI AS MEDIDAS DA CARGA", "MEDIDAS EU NAO SEI",
               "AS MEDIDAS EU NAO SEI", "NAO INFORMAR AS MEDIDAS", "PULAR AS MEDIDAS",
               "PULA AS MEDIDAS", "PULAR MEDIDAS", "SEM INFORMAR AS MEDIDAS",
               "NAO SEI INFORMAR AS MEDIDAS", "DESCONHECO AS MEDIDAS")

ETAPAS_COLETA = {"origem", "destino", "peso", "medidas", "escolher_origem", "escolher_destino"}

# Pedido para falar com uma pessoa (sempre comparado sem acento e em maiúsculas).
# Palavras que só podem ser uma pessoa da empresa:
PESSOAS_CLARAS = {"ATENDENTE", "ATENDENTES", "HUMANO", "HUMANA", "GERENTE", "SUPERVISOR",
                  "SUPERVISORA", "RESPONSAVEL", "ALGUEM", "FUNCIONARIO", "FUNCIONARIA", "VENDEDOR",
                  "VENDEDORA", "CONSULTOR", "CONSULTORA", "OPERADOR", "OPERADORA", "CHEFE"}
# Palavras que podem ter outro sentido ("peso superior a 100 kg", "sou o dono da carga",
# "pessoa jurídica"). Numa frase, só contam junto com um verbo de contato.
PESSOAS_DUVIDOSAS = {"SUPERIOR", "DONO", "DONA", "PROPRIETARIO", "PROPRIETARIA", "PESSOA"}
# Começo dos verbos de contato: "FALA" pega falar e fala; "CONTAT" pega contatar e contato...
VERBOS_CONTATO = ("FALA", "FALO", "CONVERS", "CONTAT", "CONTACT", "CHAMA", "LIGA", "PASSA",
                  "TRANSFER", "ATEND", "COMUNIC")
# Palavras de pedido: junto com uma pessoa clara, viram pedido ("quero um atendente")
PALAVRAS_PEDIDO = {"QUERO", "QUERIA", "PRECISO", "GOSTARIA", "DESEJO", "POSSO", "PODE", "PODERIA"}
# Palavras que não mudam o sentido quando o cliente manda só "o dono", "um atendente por favor"
PALAVRAS_SOLTAS = {"O", "A", "OS", "AS", "UM", "UMA", "SEU", "SUA", "SEUS", "SUAS", "DE", "DO", "DA",
                   "E", "OU", "POR", "FAVOR", "PF", "PFV", "PFVR", "OI", "OLA", "AI", "CADE"}

TEXTO_CONFIRMAR_ATENDENTE = "Você quer falar com um atendente?\n\n1️⃣ Sim\n2️⃣ Não"

# As opções que aparecem depois da cotação (também usadas quando o cliente volta
# para essa etapa). Ficam num lugar só para as duas listas nunca ficarem diferentes.
OPCOES_POS_COTACAO = ("1️⃣ Negociar com um atendente\n"
                      "2️⃣ Fazer uma nova cotação\n"
                      "3️⃣ Ver o menu")

# Primeira mensagem: o bot se apresenta e pede o CNPJ.
# O cliente digita só os 14 caracteres. A máscara com pontos e barra é colocada
# depois, pelo código, na planilha e no alerta do Telegram.
#
# ATENÇÃO: nenhuma destas mensagens pode conter um CNPJ VÁLIDO como exemplo.
# Se contivesse, bastaria o cliente copiar o exemplo para passar pela porta de
# entrada. Por isso aqui se explica o FORMATO, e não se mostra um número.
# O teste_automatico.py confere isso a cada rodada.
TEXTO_PEDIR_CNPJ = (
    f"Olá! Aqui é o assistente virtual da *{config.NOME_EMPRESA}*.\n"
    "Eu posso te passar uma cotação de frete fracionado na hora.\n\n"
    "O nosso transporte é feito para empresas, então, antes de começar, eu preciso do "
    "*CNPJ* da sua empresa.\n\n"
    "Me envie os *14 caracteres seguidos*, sem pontos, barra ou traço.")

TEXTO_CNPJ_INVALIDO = ("Esse CNPJ não parece válido.\n"
                       "Confere os 14 caracteres e me envia de novo, por favor, "
                       "sem pontos, barra ou traço.")

TEXTO_CNPJ_COM_MASCARA = ("Quase lá! Me envia o CNPJ *só com os caracteres*, "
                          "sem pontos, barra ou traço.")

TEXTO_CNPJ_VARIOS = "Achei mais de um CNPJ na sua mensagem."

# O nome é pedido na hora de chamar um atendente, e não no começo da conversa.
TEXTO_PEDIR_NOME_ATENDENTE = "Para um melhor atendimento, por favor informe o seu nome."

# O cliente travou na mesma informação. O bot não chama o atendente de cara:
# primeiro ele oferece, e só insiste se o cliente travar de novo.
TEXTO_DIFICULDADE = ("Percebi que você está tendo dificuldade para preencher as "
                     "informações.\n\n")
TEXTO_VOU_CHAMAR = ("Percebi que você está tendo dificuldades. Vou chamar um atendente "
                    "para te ajudar.\n")

# Na conversa tranquila, o bot pergunta o nome depois do CNPJ. Ele pede só o
# PRIMEIRO nome: é o que basta para conversar, e nome completo é mais dado
# pessoal do que o necessário.
#
# Quem chega com o pedido pronto NÃO é perguntado: aí o nome só aparece na hora
# de chamar um atendente (veja _falta_nome e _modo_rapido).
TEXTO_PEDIR_NOME = "E com quem eu falo? Me diga só o seu primeiro nome."

# Palavras que aparecem ANTES do nome e não fazem parte dele.
PALAVRAS_ANTES_DO_NOME = {"MEU", "NOME", "E", "ME", "CHAMO", "EU", "SOU", "O", "A",
                          "AQUI", "QUEM", "FALA", "DAQUI", "DA", "DO", "SR", "SRA",
                          "SENHOR", "SENHORA", "OI", "OLA", "BOM", "BOA", "DIA",
                          "TARDE", "NOITE", "TUDO", "BEM", "PODE", "CHAMAR", "DE"}
# Respostas que NÃO são um nome. Se o cliente mandar uma destas, o bot não
# insiste: ele segue a conversa sem o nome.
NAO_E_NOME = {"NAO", "NAO QUERO", "NAO VOU DIZER", "PREFIRO NAO DIZER", "PREFIRO NAO",
              "TANTO FAZ", "SEM NOME", "ANONIMO", "NAO IMPORTA", "DEIXA", "PULAR",
              "PULA", "MENU", "SIM", "OK", "CERTO", "CLIENTE", "EMPRESA", "CNPJ",
              "COTACAO", "FRETE", "CARGA", "PESSOA", "FISICA", "JURIDICA",
              "ATENDENTE", "HUMANO", "ROBO", "BOT", "TESTE",
              # Verbos e palavras de pergunta. Sem isso, "tem seguro" viraria o
              # nome "Tem", porque a primeira palavra tem cara de nome.
              "TEM", "TEMOS", "TENHO", "QUERO", "QUERIA", "PRECISO", "PRECISA",
              "GOSTARIA", "PODE", "PODEM", "POSSO", "FAZ", "FAZEM", "VAI", "VAO",
              "QUANTO", "QUANTOS", "QUANTAS", "COMO", "QUANDO", "ONDE", "PORQUE",
              "ACEITA", "ACEITAM", "ENTREGA", "ENTREGAM", "COLETA", "COLETAM",
              "TRANSPORTA", "TRANSPORTAM", "ATENDE", "ATENDEM", "CUSTA", "CHEGA",
              "DEMORA", "EXISTE", "SERVE", "MANDA", "ENVIA", "VALOR", "PRECO",
              "PRAZO", "SEGURO", "BOLETO", "NOTA", "PESO", "MEDIDA", "MEDIDAS"}
# Letras que um nome pode ter (com acento, apóstrofo e hífen: D'Ávila, Ana-Maria).
REGEX_NOME = re.compile(r"^[A-ZÁÂÃÀÄÉÊËÈÍÏÎÌÓÔÕÖÒÚÜÛÙÇÑ][A-ZÁÂÃÀÄÉÊËÈÍÏÎÌÓÔÕÖÒÚÜÛÙÇÑ'’-]+$",
                        re.IGNORECASE)

# Jeitos de dizer que não tem CNPJ. Nesse caso a conversa vai para o atendente.
SEM_CNPJ = ("NAO TENHO CNPJ", "NAO TEMOS CNPJ", "SEM CNPJ", "NAO POSSUO CNPJ",
            "PESSOA FISICA", "NAO SOU EMPRESA", "NAO TENHO EMPRESA", "NAO TENHO FIRMA",
            "SO TENHO CPF", "TENHO CPF", "MEU CPF", "E CPF", "CPF")
# Quando o cliente faz uma pergunta de verdade e o bot não tem a resposta.
TEXTO_NAO_SEI = "Essa eu não sei te responder.\n\n"

# Peso impreciso: o cliente deu um LIMITE em vez do peso ("mais de 100 kg",
# "entre 100 e 200 kg"). Como o frete é cobrado por faixa de peso, usar o limite
# daria um valor errado, então o bot pede o número exato.
REGEX_PESO_IMPRECISO = re.compile(
    r"\b(MAIS DE|ACIMA DE|SUPERIOR A|A PARTIR DE|NO MINIMO|PELO MENOS"
    r"|MENOS DE|ABAIXO DE|INFERIOR A|NO MAXIMO|ENTRE)\b")

# Pedido de desconto. Nas conversas reais a empresa NUNCA dá desconto na hora:
# ela leva para dentro ("vou verificar com o nosso financeiro"). O bot faz igual
# e passa para o atendente, porque quem fecha preço é uma pessoa.
# Palavras que, sozinhas, já são pedido de desconto:
PALAVRAS_DESCONTO = {"DESCONTO", "DESCONTOS", "DESCONTINHO", "ABATIMENTO", "PROMOCAO",
                     "PRECINHO", "NEGOCIAR", "NEGOCIACAO", "NEGOCIAVEL", "CARO", "CARISSIMO"}
# Expressões inteiras, agrupadas pelo jeito que o cliente fala:
FRASES_DESCONTO = (
    # achou o valor alto
    "ACHEI CARO", "FICOU CARO", "VALOR ALTO", "PRECO ALTO", "MUITO ALTO", "BEM ALTO",
    "ACHEI ALTO", "FICOU ALTO", "FICOU SALGADO", "TA SALGADO", "MUITO SALGADO",
    "FICOU PUXADO", "TA PUXADO", "PESOU NO BOLSO",
    "ACIMA DO ORCAMENTO", "FORA DO ORCAMENTO", "PASSOU DO ORCAMENTO",
    "ESTOUROU O ORCAMENTO", "NAO CABE NO ORCAMENTO",
    # pedindo para baixar
    "CONSEGUE MELHORAR", "DA PARA MELHORAR", "DA PRA MELHORAR", "TEM COMO MELHORAR",
    "PODE MELHORAR", "MELHORA ESSE", "MELHOR PRECO", "MELHOR VALOR", "MELHOR CONDICAO",
    "MELHOR OFERTA", "VALOR MELHOR", "PRECO MELHOR", "CONDICAO MELHOR",
    "FAZ POR MENOS", "FAZER POR MENOS", "SAI POR MENOS", "FICAR MAIS BARATO",
    "FAZER MAIS BARATO", "SAI MAIS BARATO", "MAIS EM CONTA",
    "BAIXAR O VALOR", "BAIXAR O PRECO", "ABAIXAR O VALOR", "ABAIXAR O PRECO",
    "REDUZIR O VALOR", "DIMINUIR O VALOR", "TEM COMO BAIXAR", "DA PARA BAIXAR",
    "DA PRA BAIXAR", "ULTIMO VALOR", "ULTIMO PRECO", "MELHOR QUE CONSEGUE",
    "DA UM JEITINHO", "DA UM JEITO NESSE", "QUEBRA UM GALHO", "DA UMA FORCA",
    "MARGEM DE NEGOCIACAO", "TEM FLEXIBILIDADE",
    # comparando com a concorrência
    "COBRIR A CONCORRENCIA", "COBRE A CONCORRENCIA", "CONSEGUI MAIS BARATO",
    "ACHEI MAIS BARATO", "A CONCORRENCIA", "OUTRA TRANSPORTADORA", "OUTRO TRANSPORTADOR")

# Problema com uma carga JÁ ENVIADA. Aqui o bot não tenta resolver nada:
# chama uma pessoa na hora. São expressões inteiras, e não palavras soltas,
# para "tem seguro contra avaria?" continuar sendo uma dúvida normal.
FRASES_OCORRENCIA = ("CARGA AVARIADA", "CHEGOU AVARIADA", "VEIO AVARIADA", "MERCADORIA AVARIADA",
                     "CHEGOU QUEBRADA", "VEIO QUEBRADA", "CHEGOU DANIFICADA", "VEIO DANIFICADA",
                     "CARGA EXTRAVIADA", "EXTRAVIO", "EXTRAVIARAM", "QUERO RECLAMAR",
                     "FAZER UMA RECLAMACAO", "RECLAMACAO")

# Frete dedicado: o bot NÃO cota. Qualquer menção vai direto para o atendente,
# porque essa operação exige análise da equipe (veículo, rota e hora parada).
# Palavras que dizem "quero um veículo só para a minha carga":
PALAVRAS_DEDICADO = {"DEDICADO", "DEDICADA", "DEDICADOS", "DEDICADAS", "LOTACAO",
                     "EXCLUSIVO", "EXCLUSIVA"}
# Nomes de veículo. Nas conversas reais da empresa o cliente quase nunca escreve
# "dedicado": ele pede pelo caminhão ("cota pra mim um bitruck", "sim carreta").
VEICULOS_DEDICADO = {"TOCO", "TRUCK", "BITRUCK", "BITREM", "RODOTREM", "CARRETA", "CARRETAS",
                     "CARRETINHA", "CARRETINHAS", "VUC", "MUNCK", "CEGONHA"}
# Expressões de mais de uma palavra (procuradas na frase inteira):
FRASES_DEDICADO = ("CARGA FECHADA", "CARGA COMPLETA", "CAMINHAO FECHADO", "VEICULO FECHADO",
                   "CAMINHAO EXCLUSIVO", "VEICULO EXCLUSIVO", "CAMINHAO SO", "VEICULO SO",
                   "FRETE CHEIO")
# "3/4" é o nome de um caminhão. A normalização troca a barra por espaço, por isso ele
# é procurado no texto original, do jeito que o cliente escreveu.
REGEX_TRES_QUARTOS = re.compile(r"\b3\s*/\s*4\b")

TEXTO_FRETE_DEDICADO = (
    "Pelo que entendi, você está falando de *frete dedicado*.\n\n"
    "No *fracionado*, que é o que eu coto aqui na hora, a sua carga divide o veículo com "
    "a de outros clientes.\n"
    "No *dedicado*, o veículo sai só com a sua mercadoria, e o modelo de caminhão é "
    "escolhido para a carga. Essa operação é montada por um atendente.\n\n")

# Sinais de que o cliente está em dúvida ou perdido na conversa.
FRASES_DUVIDA = ("NAO ENTENDI", "NAO ENTENDO", "NAO ESTOU ENTENDENDO", "NAO TO ENTENDENDO",
                 "NAO TOU ENTENDENDO", "NAO COMPREENDI", "NAO COMPREENDO", "NAO SEI COMO",
                 "NAO SEI O QUE", "NAO SEI OQ", "NAO SEI FAZER", "NAO FAZ SENTIDO", "COMO ASSIM",
                 "CONFUSO", "CONFUSA", "ESTOU PERDIDO", "ESTOU PERDIDA", "TO PERDIDO", "TO PERDIDA")
# Mensagens curtas que, com ponto de interrogação, também mostram dúvida ("hã?", "que?")
CURTAS_DUVIDA = {"HA", "HAN", "HEIN", "HEM", "QUE", "O QUE", "OQ", "OQUE", "COMO"}


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

# Medidas: "50x40x30", "3x50x40x30" (quantidade na frente) e "4,86 por 30x30".
# O "por" entrou porque é assim que muito cliente escreve de verdade.
_NUM = r"(\d+(?:[.,]\d+)?)"
_X = r"\s*(?:[xX×*]|\bpor\b)\s*"
# Um grupo de medidas no meio do texto: três números, com um quarto opcional na
# frente, que é a quantidade. O finditer acha TODOS os grupos da mensagem, e é
# isso que permite ler uma carga com vários volumes de tamanhos diferentes.
REGEX_MEDIDAS_NO_TEXTO = re.compile(
    r"(?:" + _NUM + _X + r")?" + _NUM + _X + _NUM + _X + _NUM, re.IGNORECASE)
REGEX_4_NUMEROS = re.compile(_NUM + _X + _NUM + _X + _NUM + _X + _NUM, re.IGNORECASE)
REGEX_3_NUMEROS = re.compile(_NUM + _X + _NUM + _X + _NUM, re.IGNORECASE)
# "3 caixas", "2- volumes", "1) volume": o traço e o parêntese aparecem muito
# quando o cliente manda a carga em lista.
REGEX_QUANTIDADE = re.compile(
    r"(\d+)\s*[-–.)]?\s*(?:volumes?|caixas?|pacotes?|pallets?|paletes?|unidades?|pe[çc]as?|fardos?|sacos?)",
    re.IGNORECASE)
# Quantidade escrita só como número antes das medidas: "1 50x40x30", "3 de 50x40x30"
# (pega o último número inteiro que aparece ANTES das medidas)
REGEX_QTD_ANTES = re.compile(r"(?<![\d.,])(\d+)(?![\d.,])\D*$")


# A unidade que o cliente escreveu junto das medidas: "50x40x30 cm", "1x1x1 m".
# O (?<![^\W\d_]) exige que antes não haja uma letra, para o "m" de "também" não
# ser confundido com metro.
REGEX_UNIDADE = re.compile(
    r"(?<![^\W\d_])(cm|cent[ií]metros?|mm|mil[ií]metros?|m|mt|mts|metros?)\b", re.IGNORECASE)
# Polegada continua sendo recusada: a conversão daria número quebrado e o cliente
# brasileiro quase nunca mede carga assim.
REGEX_POLEGADA = re.compile(r"(?<![^\W\d_])(pol|polegadas?)\b", re.IGNORECASE)

# Quanto vale 1 de cada unidade, em centímetros.
VALOR_EM_CM = {"cm": 1, "centimetro": 1, "centimetros": 1,
               "mm": 0.1, "milimetro": 0.1, "milimetros": 0.1,
               "m": 100, "mt": 100, "mts": 100, "metro": 100, "metros": 100}

MEDIDA_MAXIMA_CM = 1500   # 15 metros: nenhum volume do fracionado passa disso
# Abaixo de 5 cm não existe volume de frete: uma medida assim está em metros,
# mesmo que o cliente não tenha escrito a unidade. É o caso de "4,86 por 30x30",
# que é 4,86 metros por 30 por 30 centímetros.
MEDIDA_MINIMA_CM = 5


def usou_polegadas(texto):
    """True se o cliente escreveu as medidas em polegadas."""
    return bool(REGEX_POLEGADA.search(texto))


def _unidade_do_trecho(trecho):
    """Devolve quantos centímetros vale 1 unidade escrita no trecho, ou None."""
    achado = REGEX_UNIDADE.search(trecho)
    if not achado:
        return None
    return VALOR_EM_CM.get(normalizar(achado.group(1)).lower())


def _para_centimetros(trecho, medidas):
    """
    Deixa as medidas em centímetros.

    1. Se o cliente escreveu a unidade ("50x40x30 cm", "1x1x1 m"), usa ela.
    2. Se não escreveu, são centímetros, que é como o bot pede.
    3. A exceção é a medida pequena demais para ser centímetro: menos de
       MEDIDA_MINIMA_CM. Não existe volume de frete com 4 cm de comprimento,
       então aquilo é metro. É assim que "4,86 por 30x30" vira 486 x 30 x 30 cm.

    Repare que a regra do item 3 vale medida por medida, porque o cliente mistura
    mesmo: ele escreve o comprimento em metros e a seção em centímetros, na mesma
    linha. Essa é a forma de ler que não perde dinheiro: se o bot lesse 4,86 como
    centímetros, o peso cubado sairia 100 vezes menor do que o real.
    """
    fator = _unidade_do_trecho(trecho)
    if fator:
        return [round(m * fator, 2) for m in medidas]
    return [round(m * 100, 2) if m < MEDIDA_MINIMA_CM else m for m in medidas]


def _quantidade_no_trecho(trecho):
    """Quantos volumes o cliente disse no pedaço de texto antes das medidas."""
    achado = REGEX_QUANTIDADE.search(trecho)
    if achado:
        return int(achado.group(1))
    antes = REGEX_QTD_ANTES.search(trecho)
    if antes:
        return int(antes.group(1))
    return None


def ler_medidas(texto):
    """
    Entende as medidas da carga e devolve uma LISTA de volumes, sempre em
    centímetros, ou None quando não entendeu nada.

    Cada item da lista é (quantidade, [comprimento, largura, altura]).

      '50x40x30'             -> [(1, [50, 40, 30])]
      '3 caixas de 50x40x30' -> [(3, [50, 40, 30])]
      '3x50x40x30'           -> [(3, [50, 40, 30])]
      '1x1x1 m'              -> [(1, [100, 100, 100])]

    E, principalmente, uma carga com volumes de tamanhos diferentes, que é como
    chegam os pedidos de verdade:

      2- volume de 4,86 por 30x30
      2- volume de 3,60 por 30x30
      1- volume de 0,80 por 30x30
          -> [(2, [486, 30, 30]), (2, [360, 30, 30]), (1, [80, 30, 30])]

    Como funciona: o bot acha TODOS os grupos de três números da mensagem. Para
    cada grupo, procura a quantidade no pedaço de texto que vem antes, e a
    unidade no pedaço que vem logo depois.
    """
    texto = str(texto)
    volumes = []
    fim_anterior = 0
    for achado in REGEX_MEDIDAS_NO_TEXTO.finditer(texto):
        antes = texto[fim_anterior:achado.start()]
        depois = texto[achado.start():achado.end() + 15]
        fim_anterior = achado.end()

        numeros = [n for n in achado.groups() if n is not None]
        if len(numeros) == 4:                  # a quantidade veio colada: "3x50x40x30"
            quantidade = int(_para_numero(numeros[0]))
            dimensoes = numeros[1:]
        else:
            quantidade = _quantidade_no_trecho(antes)
            dimensoes = numeros

        medidas_cm = _para_centimetros(depois, [_para_numero(n) for n in dimensoes])
        if quantidade is None:
            quantidade = 1              # o cliente não disse: o bot calcula como 1 volume
        if quantidade < 1 or any(m <= 0 or m > MEDIDA_MAXIMA_CM for m in medidas_cm):
            return None
        volumes.append((quantidade, medidas_cm))

    return volumes or None


def quantidade_de_todos_informada(texto):
    """
    True quando o CLIENTE disse quantos volumes são em TODOS os grupos de medidas.

    Se algum grupo veio sem quantidade, o bot supôs 1 volume ali, e suposição do
    bot não pode virar informação do cliente na planilha.
    """
    texto = str(texto)
    achou_algum = False
    fim_anterior = 0
    for achado in REGEX_MEDIDAS_NO_TEXTO.finditer(texto):
        achou_algum = True
        antes = texto[fim_anterior:achado.start()]
        fim_anterior = achado.end()
        numeros = [n for n in achado.groups() if n is not None]
        if len(numeros) == 4:
            continue                            # a quantidade veio colada
        if _quantidade_no_trecho(antes) is None:
            return False
    return achou_algum


def calcular_peso_cubado(volumes):
    """
    Peso cubado = volume total em m³ × fator de cubagem.

    Recebe a LISTA de volumes que o ler_medidas devolve. O bot calcula o volume
    de cada linha separadamente, soma tudo e só então multiplica pelo fator. É
    assim que a logística calcula carga mista, e é a única conta certa quando os
    volumes têm tamanhos diferentes.

    Exemplo simples:
      3 caixas de 50x40x30 cm -> 0,5 × 0,4 × 0,3 × 3 = 0,18 m³ × 300 = 54 kg

    Exemplo de carga mista (um pedido real da empresa):
      2 de 486x30x30 cm -> 4,86 × 0,30 × 0,30 × 2 = 0,8748 m³
      2 de 360x30x30 cm -> 3,60 × 0,30 × 0,30 × 2 = 0,6480 m³
      2 de 250x30x30 cm -> 2,50 × 0,30 × 0,30 × 2 = 0,4500 m³
      2 de  40x30x30 cm -> 0,40 × 0,30 × 0,30 × 2 = 0,0720 m³
      1 de  80x30x30 cm -> 0,80 × 0,30 × 0,30 × 1 = 0,0720 m³
                                          total = 2,1168 m³ × 300 = 635,0 kg
    O peso real era 240 kg, então a cotação usa 635 kg, que é o maior dos dois.
    """
    metros_cubicos = 0.0
    for quantidade, medidas_cm in volumes:
        comprimento, largura, altura = (m / 100 for m in medidas_cm)
        metros_cubicos += comprimento * largura * altura * quantidade
    return round(metros_cubicos * config.FATOR_CUBAGEM, 1)


def peso_impreciso(texto):
    """
    True quando o cliente deu um limite, e não o peso.
      'mais de 100 kg' / 'acima de 100 kg' / 'entre 100 e 200 kg' -> True
      '100 kg' / 'aproximadamente 100 kg'                         -> False
    """
    return bool(REGEX_PESO_IMPRECISO.search(normalizar(texto)))


def pede_desconto(comando):
    """True se o cliente pediu desconto ou achou o valor alto."""
    if any(p in PALAVRAS_DESCONTO for p in comando.split()):
        return True
    frase = f" {comando} "
    return any(f" {expressao} " in frase for expressao in FRASES_DESCONTO)


def relata_ocorrencia(comando):
    """True se o cliente relatou um problema com uma carga já enviada."""
    frase = f" {comando} "
    return any(f" {expressao} " in frase for expressao in FRASES_OCORRENCIA)


def pede_frete_dedicado(texto, comando):
    """
    True se o cliente está falando de frete dedicado, ou seja, um veículo só para a
    carga dele. O bot cota apenas o frete fracionado.
      'quero frete dedicado'        -> True
      'cota pra mim um bitruck'     -> True  (o cliente pede pelo nome do caminhão)
      'preciso de uma carreta'      -> True
      'é carga fechada'             -> True
      'tem como ser 3/4?'           -> True
      'goiania para palmas 50kg'    -> False
    """
    palavras = comando.split()
    if any(p in PALAVRAS_DEDICADO or p in VEICULOS_DEDICADO for p in palavras):
        return True
    frase = f" {comando} "
    if any(f" {expressao} " in frase for expressao in FRASES_DEDICADO):
        return True
    return bool(REGEX_TRES_QUARTOS.search(texto))


def pedido_de_pessoa(comando):
    """
    Descobre se o cliente quer falar com uma pessoa.
    Devolve:
      "claro"  -> pediu com uma frase clara: o bot chama o atendente na hora
                  'posso falar com o dono?', 'quero contactar o seu superior', 'quero um atendente'
      "talvez" -> mandou só a palavra: o bot pergunta se ele quer um atendente
                  'dono', 'gerente', 'atendente', 'o superior?'
      None     -> não é pedido de atendente
                  'peso superior a 100 kg', 'sou o dono da carga'
    """
    palavras = comando.split()
    claras = [p for p in palavras if p in PESSOAS_CLARAS]
    duvidosas = [p for p in palavras if p in PESSOAS_DUVIDOSAS]
    if not claras and not duvidosas:
        return None

    # (a própria palavra "atendente" começa com "ATEND", por isso as pessoas ficam de fora aqui)
    tem_contato = any(p.startswith(VERBOS_CONTATO) for p in palavras
                      if p not in PESSOAS_CLARAS and p not in PESSOAS_DUVIDOSAS)
    tem_pedido = any(p in PALAVRAS_PEDIDO for p in palavras)
    if tem_contato or (claras and tem_pedido):
        return "claro"

    # Só a palavra (com, no máximo, "o", "um", "por favor"...): pergunta antes
    outras = [p for p in palavras
              if p not in PESSOAS_CLARAS and p not in PESSOAS_DUVIDOSAS and p not in PALAVRAS_SOLTAS]
    if not outras:
        return "talvez"
    return None


def parece_em_duvida(texto, comando):
    """
    True se a mensagem mostra que o cliente está em dúvida.
      '?' ou '???'                 -> True
      'hã?' / 'que?'               -> True
      'não estou entendendo'       -> True
      'tem seguro?'                -> False (é uma pergunta normal: quem responde é o FAQ)
      'não sei' (nas medidas)      -> False (é o mesmo que PULAR)
    """
    if texto and not texto.replace("?", "").strip():          # só pontos de interrogação
        return True
    if "?" in texto and comando in CURTAS_DUVIDA:
        return True
    frase = f" {comando} "
    return any(f" {duvida} " in frase for duvida in FRASES_DUVIDA)


# Expressões de preço que começam com "quanto". A palavra "quanto" sozinha não serve,
# porque "em quanto tempo vocês coletam?" é uma dúvida, e não um pedido de cotação.
QUANTO_DE_PRECO = ("QUANTO CUSTA", "QUANTO FICA", "QUANTO FICARIA", "QUANTO SAI", "QUANTO E",
                   "QUANTO SERIA", "QUANTO DA", "QUANTO VAI CUSTAR", "QUANTO VOCES COBRAM",
                   "QUANTO COBRAM", "QUANTO PAGO", "QUANTO VOU PAGAR")


def quer_cotacao(comando):
    """Detecta frases como 'quero uma cotação' ou 'quanto custa o frete'."""
    palavras = comando.split()
    if any(p in palavras for p in ("COTACAO", "COTAR", "ORCAMENTO", "CUSTA", "PRECO")):
        return True
    frase = f" {comando} "
    return any(f" {expressao} " in frase for expressao in QUANTO_DE_PRECO)


def _saudacao_inicial():
    """A apresentação do bot, usada na primeira mensagem da conversa."""
    return f"Olá! Aqui é o assistente virtual da *{config.NOME_EMPRESA}*.\n\n"


def ler_nome(texto):
    """
    Tira o primeiro nome da resposta do cliente, ou devolve None.

      'Eduardo'              -> 'Eduardo'
      'meu nome é eduardo'   -> 'Eduardo'
      'sou o Eduardo Santos' -> 'Eduardo'   (só o primeiro nome)
      'EDUARDO'              -> 'Eduardo'   (a escrita é padronizada)
      'prefiro não dizer'    -> None
      '11222333000181'       -> None
      'quanto custa?'        -> None
    """
    if "?" in str(texto):                            # pergunta nunca é um nome
        return None
    palavras = [p.strip(".,;:!?()\"'") for p in str(texto).split()]
    palavras = [p for p in palavras if p]
    if not palavras or len(palavras) > 6:            # frase comprida não é um nome
        return None
    if normalizar(texto) in NAO_E_NOME:
        return None

    for palavra in palavras:
        if normalizar(palavra) in PALAVRAS_ANTES_DO_NOME:
            continue                                  # 'meu', 'nome', 'sou'...
        if not (2 <= len(palavra) <= 20):
            return None
        if not REGEX_NOME.match(palavra):             # tem número ou símbolo
            return None
        if normalizar(palavra) in NAO_E_NOME:
            return None
        return palavra.capitalize()
    return None


def recusou_o_nome(texto):
    """
    True quando o cliente disse, com essas palavras, que não vai dar o nome
    ("prefiro não dizer", "tanto faz", "pular"). Isso não é uma pergunta nova:
    é só o cliente passando da gentileza, e a conversa segue sem o nome.
    """
    return normalizar(texto) in NAO_E_NOME


def _prazer(sessao):
    """'Prazer, Eduardo! ' quando o cliente disse o nome, ou '' quando não disse."""
    nome = sessao.get("nome")
    return f"Prazer, {nome}! " if nome else ""


def texto_convite(sessao):
    """
    A abertura da conversa, depois do CNPJ e do nome.

    Aqui o bot NÃO joga o menu numerado. Ele convida o cliente a escrever com as
    próprias palavras, que é como as pessoas conversam no WhatsApp, e deixa o
    menu como apoio para quem preferir escolher por número. O menu continua
    aparecendo sozinho quando o bot não entende a mensagem.
    """
    return (_prazer(sessao)
            + "Me conta o que você precisa.\n\n"
              "Se for uma cotação, me envie a cidade de origem, a cidade de destino e o "
              "peso da carga. Pode mandar tudo numa mensagem só, se preferir.\n"
              "Se for uma dúvida, pergunte com as suas palavras mesmo.\n\n"
              "_Se você preferir escolher por número, digite MENU._")


def texto_menu():
    """
    O menu numerado. Ele deixou de ser a abertura da conversa e virou apoio:
    aparece quando o cliente digita MENU, quando o bot não entende a mensagem e
    quando a conversa precisa voltar para um lugar conhecido.
    """
    return "\n".join(["Escolha uma opção:",
                       "1️⃣ Fazer uma cotação de frete",
                       "2️⃣ Dúvidas frequentes",
                       "3️⃣ Falar com um atendente",
                       "",
                       "_A qualquer momento, digite MENU para voltar aqui._"])


def _sessao_expirou(sessao, momento):
    """Passou TEMPO_SESSAO_MIN sem o cliente escrever: a conversa recomeça do zero."""
    return momento - sessao["ultima"] > timedelta(minutes=config.TEMPO_SESSAO_MIN)


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

    # A mensagem do cliente diz a pressa dele, e o bot se adapta a ela:
    #   mandou a rota ou o peso já escritos -> ele quer a cotação rápido, então
    #   o bot não para para perguntar o nome e vai direto ao que interessa;
    #   só "oi" ou "vim do site" -> ele está tranquilo e vai responder passo a
    #   passo, então o bot se apresenta e pergunta o nome.
    # Vale para QUALQUER mensagem, e não só para a primeira: quem começa com
    # "oi" e na mensagem seguinte manda o pedido inteiro também tem pressa.
    # O nome não se perde nos dois casos: no caminho rápido ele é pedido na hora
    # de chamar um atendente, que é quando ele realmente faz falta.
    if _tem_dados_de_cotacao(texto):
        sessao["modo_rapido"] = True
    sessao.setdefault("modo_rapido", False)

    # --- Comandos que funcionam em qualquer etapa ---
    if comando in ("MENU", "INICIO", "VOLTAR"):
        sessao["etapa"], sessao["dados"] = "menu", {}
        _zerar_insistencia(sessao)
        if _falta_cnpj(sessao):             # voltou ao início sem CNPJ: pede de novo
            return _pedir_cnpj(sessao)
        return texto_menu()

    # Falou de frete dedicado: o bot não cota essa operação, vai direto para o atendente
    if pede_frete_dedicado(texto, comando):
        return _encaminhar(
            telefone, sessao, momento, evento="frete_dedicado", texto=texto,
            motivo=f'Cliente falou de FRETE DEDICADO: "{texto[:100]}"',
            inicio=TEXTO_FRETE_DEDICADO)

    # Problema com uma carga já enviada: isso é sempre com uma pessoa
    if relata_ocorrencia(comando):
        return _encaminhar(
            telefone, sessao, momento, evento="ocorrencia", texto=texto,
            motivo=f'Cliente relatou PROBLEMA COM A CARGA: "{texto[:100]}"',
            inicio=("Sinto muito pelo transtorno. Vou chamar um atendente agora "
                    "para resolver isso com você.\n"))

    # Pediu desconto ou achou o valor alto: quem fecha preço é o atendente
    if pede_desconto(comando):
        return _encaminhar(
            telefone, sessao, momento, texto=texto,
            motivo=f'Cliente pediu DESCONTO / negociação: "{texto[:100]}"',
            inicio=("Entendi. Quem fecha valor aqui é o atendente, então eu vou chamar "
                    "um para falar com você.\n"))

    # Pediu para falar com uma pessoa
    pedido = pedido_de_pessoa(comando)
    if pedido == "claro":                       # frase clara: chama o atendente na hora
        return _encaminhar(telefone, sessao, momento,
                                "Cliente pediu para falar com um atendente", texto=texto)
    if pedido == "talvez":                      # só a palavra ("dono"): pergunta antes
        return _perguntar_se_quer_atendente(sessao)

    # Mostrou que está em dúvida ("não estou entendendo", "?"): chama o atendente na hora
    if parece_em_duvida(texto, comando):
        return _encaminhar(
            telefone, sessao, momento, evento="duvida", texto=texto,
            motivo=f'Cliente demonstrou dúvida: "{texto[:100]}"',
            inicio="Sem problemas. Vou chamar alguém da nossa equipe para te ajudar.\n")

    # --- Porta de entrada: sem CNPJ, a conversa não anda ---
    # Fica aqui, e não só na primeira mensagem, para cobrir também quem volta
    # depois de falar com um atendente ou depois de um tempo sem escrever.
    # As etapas abaixo são perguntas que o próprio bot acabou de fazer. A porta do
    # CNPJ não pode atropelar a resposta do cliente, senão a conversa anda em
    # círculo: o bot pergunta se ele quer um atendente e, quando ele diz que sim,
    # a pergunta se perde.
    if sessao["etapa"] not in ("cnpj", "confirmar_atendente", "nome_atendente") \
            and _falta_cnpj(sessao):
        # A mensagem já traz o CNPJ: não faz sentido pedir uma coisa que o
        # cliente acabou de mandar. Quem cuida do resto é a etapa do CNPJ.
        if cnpj.valido(texto) or cnpj.achar_no_texto(texto):
            sessao["etapa"] = "cnpj"
            return etapa_cnpj(telefone, sessao, texto, momento)
        return _pedir_cnpj(sessao, texto, momento)

    # --- Encaminha para a função da etapa atual ---
    etapa_antes = sessao["etapa"]
    dados_antes = dict(sessao["dados"])
    sessao["nao_entendeu"] = False          # a função da etapa marca True se não entender
    funcao_da_etapa = ETAPAS[sessao["etapa"]]
    resposta = funcao_da_etapa(telefone, sessao, texto, momento)
    return _conferir_insistencia(telefone, sessao, momento, comando, etapa_antes, dados_antes, resposta)


def _perguntar_se_quer_atendente(sessao, inicio=None):
    """
    Pergunta se o cliente quer um atendente, guardando a etapa para voltar depois.
    Usada em dois casos: o cliente mandou só 'dono'/'gerente', ou o bot não soube
    responder uma pergunta de verdade.
    """
    saudacao = inicio or ""
    if inicio is None and sessao["etapa"] == "inicio":
        saudacao = _saudacao_inicial()
    if sessao["etapa"] == "inicio":
        sessao["etapa"] = "menu"
    if sessao["etapa"] != "confirmar_atendente":
        sessao["etapa_anterior"] = sessao["etapa"]      # para voltar se ele disser que não
    sessao["etapa"] = "confirmar_atendente"
    return saudacao + TEXTO_CONFIRMAR_ATENDENTE


def _encaminhar(telefone, sessao, momento, motivo, inicio="", evento=None, texto="",
                pedir_cnpj=True):
    """
    Caminho único para chamar um atendente.

    Antes de encaminhar, o bot junta o que o atendente vai precisar:
      1. o CNPJ, se ainda não tiver;
      2. o primeiro nome, se ainda não souber.
    Só então ele passa a conversa adiante.

    pedir_cnpj=False é usado justamente quando o problema É o CNPJ: cliente que
    disse ser pessoa física, ou que errou o número várias vezes. Pedir de novo
    ali seria prender a pessoa num beco sem saída.

    O pedido fica guardado em "atendente_pendente" enquanto isso, para o motivo
    e o evento continuarem os mesmos quando o encaminhamento acontecer de verdade.
    """
    falta_cnpj = pedir_cnpj and _falta_cnpj(sessao)
    if falta_cnpj or _sem_nome(sessao):
        sessao["atendente_pendente"] = {"motivo": motivo, "evento": evento, "texto": texto,
                                        "pedir_cnpj": pedir_cnpj}
        return inicio + _pedir_o_que_falta_para_o_atendente(sessao)
    return chamar_atendente(telefone, sessao, momento, motivo, inicio, evento, texto)


def _pedir_o_que_falta_para_o_atendente(sessao):
    """Pede o CNPJ, ou o nome, antes de encaminhar. O CNPJ vem primeiro."""
    pendente = sessao.get("atendente_pendente", {}) or {}
    if pendente.get("pedir_cnpj", True) and _falta_cnpj(sessao):
        sessao["etapa"] = "cnpj"
        return TEXTO_PEDIR_CNPJ
    sessao["etapa"] = "nome_atendente"
    return TEXTO_PEDIR_NOME_ATENDENTE


def _encaminhar_pendente(telefone, sessao, momento):
    """
    Já temos CNPJ e nome: encaminha de verdade o pedido que estava guardado.
    Se ainda faltar alguma coisa, pede a próxima.
    """
    pendente = sessao.get("atendente_pendente", {}) or {}
    if (pendente.get("pedir_cnpj", True) and _falta_cnpj(sessao)) or _sem_nome(sessao):
        return _pedir_o_que_falta_para_o_atendente(sessao)
    pendente = sessao.pop("atendente_pendente", {}) or {}
    return chamar_atendente(telefone, sessao, momento,
                            motivo=pendente.get("motivo", "Cliente pediu para falar com um atendente"),
                            evento=pendente.get("evento"),
                            texto=pendente.get("texto", ""))


def etapa_nome_atendente(telefone, sessao, texto, momento):
    """
    O bot pediu o nome porque vai chamar um atendente.
    O nome continua sendo cortesia: quem não quiser dizer não fica preso, o
    encaminhamento acontece do mesmo jeito, só sem o nome no alerta.
    """
    nome = ler_nome(texto)
    if nome:
        sessao["nome"] = nome
    elif not recusou_o_nome(texto):
        resposta_faq = faq.buscar_por_texto(texto)
        if resposta_faq:
            return f"{resposta_faq}\n\n{TEXTO_PEDIR_NOME_ATENDENTE}"
    pendente = sessao.pop("atendente_pendente", {}) or {}
    return chamar_atendente(telefone, sessao, momento,
                            motivo=pendente.get("motivo", "Cliente pediu para falar com um atendente"),
                            evento=pendente.get("evento"),
                            texto=pendente.get("texto", ""))


def etapa_confirmar_atendente(telefone, sessao, texto, momento):
    """Resposta à pergunta 'Gostaria de contactar um dos nossos atendentes?'"""
    comando = normalizar(texto)
    anterior = sessao.pop("etapa_anterior", "menu")
    if comando in ("1", "SIM", "S", "ISSO", "QUERO", "CLARO", "POR FAVOR", "SIM POR FAVOR", "PODE SER", "PODE"):
        return _encaminhar(telefone, sessao, momento, "Cliente pediu para falar com um atendente")

    sessao["etapa"] = anterior
    if comando in ("2", "NAO", "N", "NAO OBRIGADO", "NAO OBRIGADA", "AGORA NAO"):
        return "Tudo bem, vamos continuar então.\n\n" + _texto_para_continuar(sessao)
    # Mandou outra coisa (ex.: a cidade): segue a conversa de onde parou
    return ETAPAS[anterior](telefone, sessao, texto, momento)


def _texto_para_continuar(sessao):
    """O que o bot estava pedindo antes da pergunta sobre o atendente."""
    etapa = sessao["etapa"]
    if etapa == "cnpj":
        return TEXTO_PEDIR_CNPJ
    if etapa in ETAPAS_COLETA:
        return _pedido_da_etapa(sessao)
    if etapa == "nome":
        return TEXTO_PEDIR_NOME
    if etapa == "nome_atendente":
        return TEXTO_PEDIR_NOME_ATENDENTE
    if etapa == "pos_cotacao":
        return f"O que você quer fazer agora?\n{OPCOES_POS_COTACAO}"
    if etapa == "faq":
        return faq.texto_lista()
    sessao["etapa"] = "menu"
    return texto_menu()


# Começos de frase que indicam uma pergunta mesmo sem o ponto de interrogação.
COMECOS_DE_PERGUNTA = ("QUAL", "QUAIS", "QUANTO", "QUANTOS", "QUANTAS", "COMO",
                       "QUANDO", "ONDE", "QUEM", "PORQUE", "POR QUE", "TEM",
                       "TEEM", "FAZEM", "FAZ", "ACEITAM", "ACEITA", "POSSO",
                       "PODE", "PODEM", "DA PARA", "E POSSIVEL", "EXISTE",
                       "PRECISA", "PRECISO", "VOCES", "VC", "VCS")


def parece_pergunta(texto):
    """
    True quando a mensagem é mesmo uma pergunta: tem ponto de interrogação, ou
    começa com uma palavra de pergunta.

    Serve para separar "tem seguro" de "vim do site". As duas são frases curtas
    sem interrogação, mas só a primeira espera uma resposta. Sem isso, o bot
    responderia "essa eu não sei te responder" para quem só está se apresentando.
    """
    if "?" in str(texto):
        return True
    comando = normalizar(texto)
    return any(comando == comeco or comando.startswith(comeco + " ")
               for comeco in COMECOS_DE_PERGUNTA)


def _e_pergunta_de_verdade(sessao, texto):
    """
    True quando a mensagem é mesmo uma pergunta, e não comando, agradecimento,
    número solto ou erro de digitação. Usa o mesmo filtro da base de conhecimento,
    para o bot só oferecer atendente quando faz sentido.
    """
    try:
        return aprendizado.vale_anotar(texto, sessao["etapa"])
    except Exception:
        return False


def _nao_sei_responder(sessao, texto, momento=None, inicio=""):
    """
    O bot não soube responder uma pergunta de verdade.
    Em vez de fingir que não entendeu e jogar o menu, ele admite, anota para
    aprender depois e oferece um atendente. Quem decide é o cliente.
    """
    _anotar_pergunta(sessao, texto, momento)
    return _perguntar_se_quer_atendente(sessao, inicio=inicio + TEXTO_NAO_SEI)


def _anotar_pergunta(sessao, texto, momento=None):
    """
    O bot não soube responder: anota a pergunta na base de conhecimento.
    Quem decide se aquilo vira mesmo uma linha na planilha é o todos_aprendizado.py
    (ele descarta dado pessoal, comando, agradecimento, cidade solta e por aí vai).

    Aqui tem uma regra a mais: a MESMA pergunta, na MESMA conversa, conta uma vez só.
    Se o cliente repete a frase porque o bot não entendeu, isso é um cliente, e não
    três. Assim a coluna "vezes" da planilha quer dizer "quantas conversas diferentes
    perguntaram isso", que é o número certo para decidir o que responder primeiro.
    """
    ja_anotadas = sessao.setdefault("perguntas_anotadas", set())
    chave = normalizar(texto)
    if chave in ja_anotadas:
        return
    ja_anotadas.add(chave)
    try:
        aprendizado.registrar_pergunta(texto, sessao["etapa"], momento or agora_brasilia())
    except Exception as erro:
        print(f"[APRENDIZADO] não consegui anotar a pergunta ({erro})")


def _zerar_insistencia(sessao):
    sessao["falhas"] = 0
    sessao["repeticoes"] = 0
    sessao.pop("ultima_mensagem", None)


def _conferir_insistencia(telefone, sessao, momento, comando, etapa_antes, dados_antes, resposta):
    """
    Conta quantas vezes SEGUIDAS a conversa ficou parada:
      falhas     -> o bot não entendeu a mensagem (cidade que não existe, peso sem número...)
      repeticoes -> o cliente mandou a mesma mensagem de novo (insistiu na mesma pergunta)
    Se a conversa andou (mudou de etapa ou o bot guardou alguma informação), tudo zera.

    Passando de INSISTENCIA_MAXIMA, o bot NÃO chama o atendente de cara:
      1ª vez que trava -> ele pergunta se o cliente quer ajuda de um atendente.
                          Se o cliente disser que não, a conversa continua de onde parou.
      2ª vez que trava -> aí ele avisa que vai chamar e encaminha.
    Ou seja, o cliente tem duas rodadas inteiras de tentativas antes de ser passado
    adiante. Quem só precisava de mais uma chance não é empurrado para uma fila.
    """
    if sessao["etapa"] == "inicio":          # a conversa foi encaminhada e recomeçou
        _zerar_insistencia(sessao)
        return resposta

    andou = sessao["etapa"] != etapa_antes or sessao["dados"] != dados_antes
    if andou:
        sessao["falhas"] = 0
        sessao["repeticoes"] = 1
    else:
        sessao["falhas"] = sessao.get("falhas", 0) + 1 if sessao["nao_entendeu"] else 0
        if comando == sessao.get("ultima_mensagem"):
            sessao["repeticoes"] = sessao.get("repeticoes", 1) + 1
        else:
            sessao["repeticoes"] = 1
    sessao["ultima_mensagem"] = comando

    limite = config.INSISTENCIA_MAXIMA
    if sessao["falhas"] <= limite and sessao["repeticoes"] <= limite:
        return resposta

    # O cliente travou na mesma informação. Na PRIMEIRA vez o bot não encaminha:
    # ele pergunta se o cliente quer ajuda, porque muita gente só precisa de mais
    # uma tentativa. Travando de novo, aí sim ele chama alguém.
    _zerar_insistencia(sessao)
    sessao["vezes_que_travou"] = sessao.get("vezes_que_travou", 0) + 1
    tentativas = limite + 1
    if sessao["vezes_que_travou"] == 1:
        return _perguntar_se_quer_atendente(sessao, inicio=TEXTO_DIFICULDADE)
    return _encaminhar(
        telefone, sessao, momento, evento="insistencia",
        motivo=f"Cliente travou {tentativas} vezes, duas vezes seguidas, e o bot não conseguiu ajudar",
        inicio=TEXTO_VOU_CHAMAR)


# =================================================================
# Início e menu
# =================================================================
def _tem_dados_de_cotacao(texto):
    """True se a frase já traz peso ou 'cidade PARA cidade' (ex.: 'Goiânia para Palmas 50kg')."""
    teste = {"dados": {}}
    _absorver(teste, texto)
    # Medidas sozinhas não abrem cotação: "50x40x30" solto no menu não quer
    # dizer que o cliente está pedindo um frete.
    return any(campo in teste["dados"] for campo in ("peso", "origem", "destino"))


def etapa_inicio(telefone, sessao, texto, momento):
    """Primeira mensagem do cliente."""
    comando = normalizar(texto)
    if comando in ("1", "2", "3"):          # já escolheu uma opção do menu
        sessao["etapa"] = "menu"
        return etapa_menu(telefone, sessao, texto, momento)
    if quer_cotacao(comando) or _tem_dados_de_cotacao(texto):
        return _saudacao_inicial() + iniciar_cotacao(telefone, sessao, momento, texto)

    sessao["etapa"] = "menu"
    resposta_faq = faq.buscar_por_texto(texto)
    if resposta_faq:
        return f"{_saudacao_inicial()}{resposta_faq}\n\n" + texto_menu()
    if _e_pergunta_de_verdade(sessao, texto):     # já chegou perguntando algo que o bot não sabe
        return _nao_sei_responder(sessao, texto, momento, inicio=_saudacao_inicial())
    if _falta_nome(sessao):                       # sem CNPJ exigido, o nome é pedido aqui
        return _pedir_nome(sessao, texto)
    return _saudacao_inicial() + texto_convite(sessao)


def _falta_cnpj(sessao):
    """True quando a conversa ainda não tem um CNPJ confirmado."""
    return config.EXIGIR_CNPJ and not sessao.get("cnpj")


def _pedir_cnpj(sessao, texto="", momento=None):
    """
    Leva a conversa para a porta de entrada. O que o cliente escreveu fica
    guardado e é retomado assim que ele informar o CNPJ.

    Com uma exceção: quem chega PERGUNTANDO é respondido antes. Informação sobre
    o serviço é pública, e exigir CNPJ para dizer se a carga tem seguro afastaria
    o cliente logo na primeira mensagem. O CNPJ é exigido para COTAR, e para
    falar com um atendente, não para tirar uma dúvida.
    """
    resposta_faq = faq.buscar_por_texto(texto) if texto else None
    if resposta_faq:
        sessao["etapa"] = "cnpj"
        sessao.pop("primeira_mensagem", None)
        return f"{_saudacao_inicial()}{resposta_faq}\n\n{TEXTO_PEDIR_CNPJ}"

    # Pergunta de verdade que o bot não sabe responder: ele admite e oferece o
    # atendente. Se o cliente aceitar, aí sim o CNPJ e o nome são pedidos.
    # Pedido de cotação não entra aqui, mesmo escrito em forma de pergunta: para
    # cotar, o CNPJ é obrigatório, e é isso que o bot vai pedir logo abaixo.
    pedido_de_cotacao = quer_cotacao(normalizar(texto)) or _tem_dados_de_cotacao(texto)
    if (texto and not pedido_de_cotacao and parece_pergunta(texto)
            and _e_pergunta_de_verdade(sessao, texto)):
        return _nao_sei_responder(sessao, texto, momento, inicio=_saudacao_inicial())

    sessao["primeira_mensagem"] = texto
    sessao["etapa"] = "cnpj"
    return TEXTO_PEDIR_CNPJ


def etapa_cnpj(telefone, sessao, texto, momento):
    """
    O bot está esperando o CNPJ. Sem ele, a cotação não começa.
    Três caminhos:
      - CNPJ bem formado, sozinho ou no meio de uma mensagem maior: guarda e
        retoma o que o cliente queria;
      - cliente diz que é pessoa física: vai para o atendente;
      - número errado, ou digitado com máscara: pede de novo, e passando de
        CNPJ_TENTATIVAS chama o atendente, para o cliente nunca ficar preso.
    Dúvida geral continua sendo respondida, porque isso é informação pública.
    """
    comando = normalizar(texto)

    # O bot listou os CNPJs que achou e o cliente respondeu com o número
    listados = sessao.get("cnpjs_achados")
    if listados and comando.isdigit() and 1 <= int(comando) <= len(listados):
        escolhido = listados[int(comando) - 1]
        sessao.pop("cnpjs_achados", None)
        return _aceitar_cnpj(telefone, sessao, momento, escolhido)

    frase = f" {comando} "
    if any(f" {expressao} " in frase for expressao in SEM_CNPJ):
        return _encaminhar(
            telefone, sessao, momento, evento="cnpj", pedir_cnpj=False,
            motivo="Cliente informou que não tem CNPJ (pessoa física)",
            inicio=("Entendi. O nosso transporte é feito para empresas, então eu vou "
                    "chamar alguém da nossa equipe para falar com você.\n"))

    # Veio certo, mas com a máscara: o bot pede do jeito combinado
    if cnpj.valido(texto) and config.CNPJ_SO_NUMEROS and not cnpj.sem_pontuacao(texto):
        return _errou_o_cnpj(telefone, sessao, momento, texto, TEXTO_CNPJ_COM_MASCARA)

    if cnpj.valido(texto):
        return _aceitar_cnpj(telefone, sessao, momento, texto)

    # O CNPJ veio no meio de uma mensagem maior. Muito cliente manda o pedido
    # inteiro de uma vez, com o CNPJ numa lista numerada no meio do texto.
    achados = cnpj.achar_no_texto(texto)
    distintos = cnpj.distintos_no_texto(texto)
    if len(distintos) == 1:
        # Pode ter aparecido duas vezes (pagador e destinatário iguais): é um só.
        return _aceitar_cnpj(telefone, sessao, momento, achados[0], mensagem_inteira=texto)
    if len(distintos) > 1:
        # Pedido com CNPJ do pagador, do remetente e do destinatário: o bot não
        # escolhe por conta própria qual deles responde pelo frete. Ele lista os
        # que achou e o cliente responde com o número, sem ter que digitar de novo.
        sessao["cnpjs_achados"] = achados
        if _tem_dados_de_cotacao(texto):
            sessao["primeira_mensagem"] = texto
        lista = "\n".join(f"{numero}. {achado}" for numero, achado in enumerate(achados, 1))
        return (f"{TEXTO_CNPJ_VARIOS}\n\n{lista}\n\n"
                "Digite o *número* do CNPJ da sua empresa, o que vai responder pelo frete.")

    # Ainda não é um CNPJ: se for dúvida conhecida, responde e pede de novo
    resposta_faq = faq.buscar_por_texto(texto)
    if resposta_faq:
        return f"{resposta_faq}\n\n" + TEXTO_PEDIR_CNPJ

    return _errou_o_cnpj(telefone, sessao, momento, texto, TEXTO_CNPJ_INVALIDO)


def _aceitar_cnpj(telefone, sessao, momento, texto_cnpj, mensagem_inteira=""):
    """
    Guarda o CNPJ e segue a conversa.

    mensagem_inteira vem preenchida quando o CNPJ estava no meio de uma mensagem
    maior. Se essa mensagem também trouxer a rota ou o peso, é ela que o bot
    retoma depois, e não a que ficou guardada antes: o cliente acabou de mandar
    o pedido completo, e seria estranho o bot responder a mensagem antiga.
    """
    sessao["cnpj"] = cnpj.formatar(texto_cnpj)
    sessao.pop("tentativas_cnpj", None)
    sessao.pop("cnpjs_achados", None)
    if mensagem_inteira and _tem_dados_de_cotacao(mensagem_inteira):
        sessao["primeira_mensagem"] = mensagem_inteira
    abertura = f"Obrigado! Registrei o CNPJ *{sessao['cnpj']}*.\n\n"

    # O CNPJ estava sendo pedido para encaminhar a conversa: segue para lá
    if sessao.get("atendente_pendente"):
        return abertura + _encaminhar_pendente(telefone, sessao, momento)

    # Agora o bot pergunta o nome. Como o nome é apagado junto com o CNPJ
    # a cada encaminhamento e a cada conversa que expira, na prática ele é
    # perguntado uma vez por protocolo.
    if _falta_nome(sessao):
        sessao["etapa"] = "nome"
        return abertura + TEXTO_PEDIR_NOME
    return abertura + _seguir_depois_do_nome(telefone, sessao, momento)


def _errou_o_cnpj(telefone, sessao, momento, texto, mensagem):
    """
    O cliente mandou algo que não serve como CNPJ. O bot conta a tentativa e
    pede de novo. Passando de CNPJ_TENTATIVAS, chama um atendente, para ninguém
    ficar preso repetindo a mesma coisa.
    """
    sessao["tentativas_cnpj"] = sessao.get("tentativas_cnpj", 0) + 1
    if sessao["tentativas_cnpj"] > config.CNPJ_TENTATIVAS:
        return _encaminhar(
            telefone, sessao, momento, evento="cnpj", pedir_cnpj=False,
            motivo=f'Cliente não informou um CNPJ válido: "{texto[:60]}"',
            inicio=("Não consegui confirmar o CNPJ. Vou chamar alguém da nossa "
                    "equipe para te ajudar.\n"))
    return mensagem


# =================================================================
# O nome do cliente
# =================================================================
def _sem_nome(sessao):
    """True quando o bot ainda não sabe o nome do cliente."""
    return config.PERGUNTAR_NOME and not sessao.get("nome")


def _falta_nome(sessao):
    """
    True quando o bot deve PARAR a conversa para perguntar o nome.

    Só na conversa tranquila. Quem chegou com o pedido pronto não é interrompido:
    o nome dele é pedido depois, na hora de chamar um atendente.
    """
    return _sem_nome(sessao) and not sessao.get("modo_rapido")


def _pedir_nome(sessao, texto=""):
    """Leva a conversa para a pergunta do nome, guardando o que o cliente queria."""
    if texto:
        sessao["primeira_mensagem"] = texto
    sessao["etapa"] = "nome"
    return _saudacao_inicial() + TEXTO_PEDIR_NOME


def etapa_nome(telefone, sessao, texto, momento):
    """
    O bot perguntou o nome do cliente.

    Diferente do CNPJ, o nome NÃO é uma exigência: ele é cortesia. Por isso o bot
    pergunta uma vez e nunca insiste. Se o cliente não quiser dizer, mandar um
    número ou já emendar outro assunto, a conversa segue na mesma hora, só sem o
    nome. Prender a conversa por causa de uma gentileza seria o contrário de
    atender bem.
    """
    nome = ler_nome(texto)
    if nome:
        sessao["nome"] = nome
        return _seguir_depois_do_nome(telefone, sessao, momento)

    # Disse que não quer dar o nome: a conversa segue, e isso NÃO é tratado como
    # uma pergunta nova (senão o bot responderia "essa eu não sei te responder").
    if recusou_o_nome(texto):
        return _seguir_depois_do_nome(telefone, sessao, momento)

    # Não era um nome. Se era uma dúvida conhecida, o bot responde antes de seguir.
    resposta_faq = faq.buscar_por_texto(texto)
    if resposta_faq:
        return f"{resposta_faq}\n\n" + _seguir_depois_do_nome(telefone, sessao, momento)

    # Qualquer outra coisa é tratada como o próximo assunto da conversa.
    return _seguir_depois_do_nome(telefone, sessao, momento, texto)


def _seguir_depois_do_nome(telefone, sessao, momento, texto=""):
    """
    A conversa segue depois da pergunta do nome.
    Se o cliente já tinha dito o que queria antes (por exemplo, pediu uma cotação
    e só então o bot pediu o CNPJ), é isso que é retomado. Senão, o bot faz o
    convite aberto, sem jogar o menu numerado na cara de ninguém.
    """
    sessao["etapa"] = "menu"
    # Se o cliente escreveu outra coisa no lugar do nome, é ISSO que ele quer agora.
    # A mensagem guardada antes do CNPJ só volta quando ele respondeu o nome.
    if texto:
        guardada = texto
        sessao.pop("primeira_mensagem", None)
    else:
        guardada = sessao.pop("primeira_mensagem", "")
    abertura = _prazer(sessao)
    if abertura:
        abertura = abertura.strip() + "\n\n"

    if guardada:
        if normalizar(guardada) in ("1", "2", "3") or quer_cotacao(normalizar(guardada)) \
                or _tem_dados_de_cotacao(guardada):
            return abertura + etapa_menu(telefone, sessao, guardada, momento)
        resposta_faq = faq.buscar_por_texto(guardada)
        if resposta_faq:
            return f"{abertura}{resposta_faq}\n\n" + texto_menu()
        if _e_pergunta_de_verdade(sessao, guardada):
            return _nao_sei_responder(sessao, guardada, momento, inicio=abertura)
    return texto_convite(sessao)


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
        return _encaminhar(telefone, sessao, momento, "Cliente pediu para falar com um atendente")

    resposta_faq = faq.buscar_por_texto(texto)
    if resposta_faq:
        return f"{resposta_faq}\n\n" + texto_menu()
    if _e_pergunta_de_verdade(sessao, texto):
        return _nao_sei_responder(sessao, texto, momento)
    sessao["nao_entendeu"] = True
    return "Desculpe, eu não entendi.\n\n" + texto_menu()


# =================================================================
# Cotação: coleta de origem, destino e peso
# =================================================================
def iniciar_cotacao(telefone, sessao, momento, texto=""):
    """Começa uma cotação. Se a mensagem já trouxer dados, aproveita."""
    sessao["dados"] = {}
    sessao.pop("registro", None)     # nova cotação: a linha da cotação anterior não é mais atualizada
    confirmados, _ = _absorver(sessao, texto) if texto else ([], "")
    if not confirmados:
        confirmados = ["Vamos lá! Para a cotação eu preciso da origem, do destino e do "
                       "peso da carga."]
    return _continuar(telefone, sessao, momento, confirmados)


def _cidade_do_cep(texto_cep):
    """
    Descobre a cidade do CEP e devolve a cidade da lista do bot, com latitude e
    longitude, que é o que o cálculo da distância usa. None quando não deu.
    """
    achada = cep.cidade(texto_cep)
    if not achada:
        return None
    situacao, resultado = resolver_cidade(f"{achada['nome']} {achada['uf']}")
    if situacao == "ok":
        return resultado
    if situacao == "ambigua" and resultado:
        return resultado[0]        # com a UF junto, a lista já vem de um estado só
    return None


def _guardar_cep(sessao, campo, texto_cep):
    """
    Guarda o CEP que o cliente informou e, se der, já resolve a cidade.
    campo é "origem" ou "destino". Devolve a cidade achada, ou None.

    O CEP fica guardado mesmo quando a consulta falha: ele vai para a planilha e
    para o alerta do Telegram de qualquer jeito, porque foi o cliente que o
    informou. O que muda é que aí o bot pede a cidade por extenso.
    """
    dados = sessao["dados"]
    dados[f"cep_{campo}"] = cep.formatar(texto_cep)
    cidade_achada = _cidade_do_cep(texto_cep)
    if cidade_achada and campo not in dados:
        dados[campo] = cidade_achada
        return cidade_achada
    return None


def _modo_da_rota(dados):
    """
    Diz se a rota desta cotação está sendo informada por CIDADE ou por CEP.
    Devolve "cidade", "cep", ou None quando o cliente ainda não informou nenhum
    dos dois lados.

    Regra da empresa: a rota é toda por cidade ou toda por CEP, nunca metade de
    cada. Misturar deixa a planilha confusa (metade da rota numa coluna, metade
    em outra) e, na conversa, faz o cliente se perder no que o bot está pedindo.
    """
    if dados.get("cidade_origem_dita") or dados.get("cidade_destino_dita"):
        return "cidade"
    if dados.get("cep_origem") or dados.get("cep_destino"):
        return "cep"
    return None


def _combina_com_a_rota(dados, por_cep):
    """True quando esse formato combina com o que já foi usado nesta rota."""
    modo = _modo_da_rota(dados)
    if modo is None:
        return True              # primeiro lado informado: ele é quem decide o formato
    return (modo == "cep") == por_cep


def _pergunta_da_rota(sessao, campo):
    """A pergunta de origem ou destino, no formato que o cliente já escolheu."""
    if campo in PERGUNTAS_CEP and _modo_da_rota(sessao["dados"]) == "cep":
        return PERGUNTAS_CEP[campo]
    return PERGUNTAS[campo]


def _nome_da_rota(sessao, campo):
    """Como o bot chama a informação que falta, no formato que o cliente escolheu."""
    if campo in NOMES_CEP and _modo_da_rota(sessao["dados"]) == "cep":
        return NOMES_CEP[campo]
    return NOMES[campo]


def _cidade_depois_da_marca(frase, marcas, outras_marcas):
    """
    Procura uma cidade logo DEPOIS de uma expressão como "sai de" ou "entrega em".
    A busca para no próximo marcador, para a origem não invadir o destino.
    Devolve a cidade, ou None.
    """
    for marca in marcas:
        texto_marca = f" {normalizar(marca)} "
        posicao = frase.find(texto_marca)
        if posicao < 0:
            continue
        trecho = frase[posicao + len(texto_marca):][:40]
        for outra in outras_marcas:
            corte = trecho.find(f" {normalizar(outra)} ")
            if corte >= 0:
                trecho = trecho[:corte]
        achada = achar_cidade_no_texto(trecho)
        if achada:
            return achada
    return None


def _absorver_cidades_marcadas(sessao, texto):
    """
    Preenche a ponta da rota que ainda falta, usando o que o cliente marcou com
    todas as letras: "cotação para manaus, a carga sai de goiania".

    Só roda para a ponta que está faltando. Se a rota já foi lida inteira pelo
    "de X para Y", esta função não mexe em nada.

    A exigência da expressão é o que torna isso seguro. Sem ela, qualquer cidade
    citada de passagem viraria rota: em "para manaus, mas o transporte não é para
    mim, eu sou de Brasília", Brasília não tem marcador nenhum e fica de fora.
    """
    dados = sessao["dados"]
    frase = f" {normalizar(texto)} "
    confirmados = []
    for campo, marcas, outras in (("origem", MARCAS_DE_ORIGEM, MARCAS_DE_DESTINO),
                                  ("destino", MARCAS_DE_DESTINO, MARCAS_DE_ORIGEM)):
        if campo in dados or not _combina_com_a_rota(dados, por_cep=False):
            continue
        achada = _cidade_depois_da_marca(frase, marcas, outras)
        if achada:
            dados[campo] = achada
            dados[f"cidade_{campo}_dita"] = True
            rotulo = "Origem" if campo == "origem" else "Destino"
            confirmados.append(f"{rotulo}: {nome_completo(achada)}")
    return confirmados


def _guardar_ponta(dados, campo, cidade):
    """Guarda uma ponta da rota e devolve a confirmação para o cliente."""
    dados[campo] = cidade
    dados[f"cidade_{campo}_dita"] = True
    rotulo = "Origem" if campo == "origem" else "Destino"
    return f"{rotulo}: {nome_completo(cidade)}"


def _completar_a_rota_pelas_cidades(sessao, texto):
    """
    Última regra da fila: quem cita duas cidades num pedido de frete está dizendo
    a rota. A dúvida é só qual é a origem e qual é o destino.

    Dois casos, nesta ordem:

    1. Falta UMA ponta e sobrou UMA cidade. A cidade é essa ponta. Aqui não tem
       dúvida nenhuma, porque a outra ponta já foi identificada antes:
         "cotação para manaus, eu moro em brasilia"
             -> o destino veio do "para"; sobrou Brasília, então ela é a origem.

    2. Faltam AS DUAS pontas e sobraram exatamente DUAS cidades. Aí vale a ordem
       em que elas aparecem: a primeira é a origem, a segunda é o destino. É como
       se fala e como se escreve um frete, de onde sai para onde vai:
         "quero cotar brasilia manaus"  ->  de Brasília para Manaus.

    O caso 2 é um palpite, e é o único do bot. Ele só é dado quando não existe
    mais nada na frase para decidir: nem o "para", nem expressão marcada, nem
    uma ponta já conhecida. E o bot devolve a rota que entendeu antes de pedir
    as medidas, e de novo na cotação, para o cliente ver e corrigir.

    Fora desses dois casos, ele não escolhe:
      - sobrando mais de duas cidades, não dá para saber quais são a rota;
      - sobrando uma cidade só e faltando as duas pontas, não dá para saber se
        ela é a origem ou o destino.
    """
    dados = sessao["dados"]
    faltando = [campo for campo in ("origem", "destino") if campo not in dados]
    if not faltando or not _combina_com_a_rota(dados, por_cep=False):
        return []

    ja_usadas = [dados[campo] for campo in ("origem", "destino") if campo in dados]
    sobrando = [cidade for cidade in achar_todas_as_cidades(texto) if cidade not in ja_usadas]

    if len(faltando) == 1 and len(sobrando) == 1:
        return [_guardar_ponta(dados, faltando[0], sobrando[0])]

    if len(faltando) == 2 and len(sobrando) == 2:
        # A ordem da frase decide: a primeira cidade é de onde sai, a segunda é para onde vai.
        return [_guardar_ponta(dados, "origem", sobrando[0]),
                _guardar_ponta(dados, "destino", sobrando[1])]
    return []


def avisou_que_nao_tem_medidas(texto):
    """True quando a mensagem já diz que o cliente não vai informar as medidas."""
    frase = f" {normalizar(texto)} "
    return any(f" {aviso} " in frase for aviso in SEM_MEDIDAS)


def _absorver_ceps(sessao, texto):
    """
    Aproveita os CEPs escritos na mensagem ("CEP de origem 74486-225").
    Devolve a lista de confirmações para mostrar ao cliente.

    Esta função roda DEPOIS da leitura das cidades, de propósito, para o CEP solto
    cair na ponta que a cidade ainda não tomou.

    O CEP só entra se a rota ainda não tiver começado por cidade. A rota é toda
    por cidade ou toda por CEP (veja _modo_da_rota). O que não combina é só
    ignorado, e o bot pergunta de novo no formato certo.
    """
    dados = sessao["dados"]
    rotulados, sem_rotulo = cep.achar_com_rotulo(texto)
    pendentes = list(sem_rotulo)
    confirmacoes = []

    for campo in ("origem", "destino"):
        if campo in dados:
            continue
        texto_cep = rotulados.get(campo)
        if texto_cep is None and pendentes:
            texto_cep = pendentes.pop(0)       # CEP sem palavra vai para a ponta que falta
        if texto_cep is None:
            continue
        # A rota já começou por cidade: o CEP não entra
        if not _combina_com_a_rota(dados, por_cep=True):
            continue
        cidade_achada = _guardar_cep(sessao, campo, texto_cep)
        if cidade_achada:
            rotulo = "Origem" if campo == "origem" else "Destino"
            confirmacoes.append(f"{rotulo}: {nome_completo(cidade_achada)} "
                                f"(CEP {dados[f'cep_{campo}']})")
    return confirmacoes


def _melhor_corte_da_rota(frase):
    """
    Decide ONDE cortar a frase para separar origem e destino.

    A frase pode ter mais de um "para". Em "realiza essa cotação PRA mim por
    favor, quero cotar de manaus PARA camboriu", o primeiro é conversa e o
    segundo é a rota. Cortar sempre no primeiro faria o bot ler a rota errada.

    Então o bot experimenta TODOS os cortes e fica com o que achar mais pontas
    da rota. Empatando, fica com o primeiro, que é o mais comum.

    Devolve (origem, destino), cada um podendo ser None.
    """
    melhor = (None, None)
    melhor_pontos = 0
    for achado in REGEX_SEPARADOR.finditer(frase):
        origem = achar_ultima_cidade_no_texto(frase[:achado.start()])
        destino = achar_cidade_no_texto(frase[achado.end():])
        pontos = (1 if origem else 0) + (1 if destino else 0)
        if pontos > melhor_pontos:
            melhor, melhor_pontos = (origem, destino), pontos
    return melhor


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
    if peso and peso_impreciso(texto):
        peso = None                 # 'mais de 100 kg': o bot vai pedir o peso exato
    if peso and "peso" not in dados:
        dados["peso"] = peso
        confirmados.append(f"Peso: {formatar_numero(peso)} kg")

    # O texto sem o peso e sem os CEPs é o que vale para ler as medidas. Sem essa
    # limpeza, o "450" de "450kg" viraria 450 volumes, e o "000" de um CEP
    # terminado em -000 viraria quantidade zero.
    texto_das_medidas = cep.remover_do_texto(resto)

    # Quem decide o formato da rota é o que o cliente MARCOU. Um CEP com a palavra
    # junto ("CEP de origem 74486-225") vale mais do que uma cidade solta na mesma
    # frase, porque ali o cliente disse com todas as letras como quer informar.
    # Sem isso, em "cep de origem 74486-225, destino palmas to" o bot leria Palmas
    # primeiro, entraria no modo cidade e recusaria justo o CEP que foi marcado.
    rotulados, _ = cep.achar_com_rotulo(resto)
    if rotulados and _modo_da_rota(dados) is None:
        confirmados.extend(_absorver_ceps(sessao, texto))

    # Antes do "para", vale a ÚLTIMA cidade: é a que está colada no "para", e é
    # ali que o cliente diz de onde a carga sai. Depois do "para", vale a
    # PRIMEIRA, pelo mesmo motivo, só que do outro lado.
    origem, destino = _melhor_corte_da_rota(f" {normalizar(resto)} ")
    if origem or destino:
        # A rota já começou por CEP: a cidade não entra
        if origem and "origem" not in dados:
            if _combina_com_a_rota(dados, por_cep=False):
                dados["origem"] = origem
                dados["cidade_origem_dita"] = True
                confirmados.insert(0, f"Origem: {nome_completo(origem)}")
            else:
                origem = None
        if destino and "destino" not in dados:
            if _combina_com_a_rota(dados, por_cep=False):
                dados["destino"] = destino
                dados["cidade_destino_dita"] = True
                confirmados.insert(1 if origem else 0, f"Destino: {nome_completo(destino)}")
            else:
                destino = None
        if origem or destino:
            resto = ""

    # A ponta que faltou pode estar marcada com todas as letras na mensagem
    # ("a carga sai de goiania", "entrega em palmas").
    confirmados.extend(_absorver_cidades_marcadas(sessao, texto))

    # Última regra: duas cidades na mensagem são a rota.
    confirmados.extend(_completar_a_rota_pelas_cidades(sessao, texto))

    # CEP escrito na mensagem vale como cidade, depois de descobrir qual é. Vem
    # depois das cidades para o CEP cair na ponta que ainda está faltando.
    confirmados.extend(_absorver_ceps(sessao, texto))

    # Medidas escritas na mesma mensagem. O convite do bot diz "pode mandar tudo
    # numa mensagem só", então ele tem que aproveitar as medidas também.
    if "medidas" not in dados and not dados.get("pulou_medidas"):
        volumes = ler_medidas(texto_das_medidas)
        if volumes:
            dados["medidas"] = volumes
            dados["qtd_informada"] = quantidade_de_todos_informada(texto_das_medidas)
            confirmados.append("Medidas: " + _resumo_das_medidas(volumes))
        elif avisou_que_nao_tem_medidas(texto):
            # O cliente já disse que não sabe. Perguntar de novo seria não ter lido.
            dados["pulou_medidas"] = True
            dados["qtd_informada"] = False
    return confirmados, resto


def _aproveitar_dados(sessao, texto):
    """
    O cliente está sendo encaminhado para um atendente, e a mensagem dele pode já
    trazer rota e peso ("quero um bitruck de ubatuba para sao paulo, uns 500kg").

    Sem isso, a linha da planilha sairia com origem e destino como nao_informado e
    o peso vazio, e o atendente teria que perguntar de novo o que o cliente já
    tinha dito. Então o bot aproveita o que dá para aproveitar da própria frase,
    e calcula a distância quando as duas cidades aparecem.

    O valor continua vazio, e está certo: quem dá preço de frete dedicado, de
    ocorrência ou de negociação é o atendente, nunca o bot.

    Só vale quando NÃO há cotação em andamento. Se já houver, o que o cliente
    informou passo a passo vale mais do que uma frase solta.
    """
    if not texto or sessao.get("dados"):
        return
    try:
        _absorver(sessao, texto)
        dados = sessao["dados"]
        if dados.get("origem") and dados.get("destino") and dados.get("km") is None:
            dados["km"] = distancia_km(dados["origem"], dados["destino"])
    except Exception as erro:
        print(f"[ATENDENTE] não consegui aproveitar os dados da mensagem ({erro})")


def _continuar(telefone, sessao, momento, confirmados):
    """
    Olha o que já temos e pede a PRÓXIMA informação que falta.
    Quando origem, destino e peso estiverem completos, pede as medidas.
    """
    prefixo = "\n".join(confirmados) + "\n\n" if confirmados else ""
    dados = sessao["dados"]

    if dados.get("peso", 0) > config.PESO_MAXIMO_KG:
        sessao["etapa"], sessao["dados"] = "menu", {}
        return (f"No momento nós trabalhamos com cargas de até "
                f"{formatar_numero(config.PESO_MAXIMO_KG)} kg. "
                "Se você tiver outra carga dentro desse limite, é só fazer uma nova cotação.\n\n"
                + texto_menu())

    for campo in ("origem", "destino", "peso"):
        if campo not in dados:
            sessao["etapa"] = campo
            return prefixo + _pergunta_da_rota(sessao, campo)

    # As medidas já vieram na mesma mensagem, ou o cliente já disse que não as
    # tem: não há o que perguntar. A cotação sai direto, e SEM repetir a lista
    # do que foi entendido: ela aparece inteira dentro da própria cotação.
    if dados.get("medidas") or dados.get("pulou_medidas"):
        return _finalizar_cotacao(telefone, sessao, momento, dados.get("medidas"))

    sessao["etapa"] = "medidas"
    return prefixo + PERGUNTAS["medidas"]


def _recusar_mistura(sessao, campo):
    """
    O cliente mandou a outra ponta da rota num formato diferente do que ele mesmo
    começou. O bot simplesmente não aceita e repete a pergunta, no formato certo.

    Sem sermão: explicar a regra em cada tentativa soa como bronca, e o cliente
    entende sozinho pela pergunta, que já diz se é cidade ou CEP.

    Conta como "não entendi" de propósito: se o cliente insistir três vezes, a
    regra da insistência chama um atendente, e ninguém fica preso.
    """
    sessao["nao_entendeu"] = True
    return _pergunta_da_rota(sessao, campo)


def _pedir_de_novo(sessao, campo, motivo, texto_cliente=""):
    """
    Monta a mensagem pedindo de novo a informação que faltou.
    Se o cliente fez uma pergunta no meio (ex.: 'tem seguro?'), responde antes.
    Se não for pergunta, o bot não entendeu a mensagem (conta para a insistência).
    """
    nome = _nome_da_rota(sessao, campo)
    pergunta = _pergunta_da_rota(sessao, campo)
    resposta_faq = faq.buscar_por_texto(texto_cliente) if texto_cliente else None
    sessao["nao_entendeu"] = resposta_faq is None
    if resposta_faq:
        return (f"{resposta_faq}\n\n"
                f"Para continuar a cotação, me envie {nome}.\n\n{pergunta}")

    # Era uma pergunta de verdade, e o bot não tem a resposta: admite, anota e
    # mostra o caminho para uma pessoa, sem largar a cotação pela metade.
    if texto_cliente and _e_pergunta_de_verdade(sessao, texto_cliente):
        _anotar_pergunta(sessao, texto_cliente)
        return ("Essa eu não sei te responder. Um atendente consegue: "
                "é só digitar *ATENDENTE* a qualquer momento.\n\n"
                f"Para continuar a cotação, me envie {nome}.\n\n{pergunta}")
    return f"{motivo}\nPode me enviar de novo {nome}?\n\n{pergunta}"


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
        return prefixo + _pedir_de_novo(sessao, campo, "Não recebi essa informação.")

    if campo == "peso":
        if peso_impreciso(texto):
            return prefixo + _pedir_de_novo(
                sessao, "peso",
                "Preciso do peso exato da carga, porque o frete é cobrado por faixa de peso.")
        peso = ler_peso(resto)
        if peso is None:
            return prefixo + _pedir_de_novo(sessao, "peso", "Não consegui identificar o peso.", resto)
        sessao["dados"]["peso"] = peso
        return _continuar(telefone, sessao, momento,
                          confirmados + [f"✅ Peso: {formatar_numero(peso)} kg"])

    return prefixo + _receber_cidade(telefone, sessao, momento, resto, campo)


def _receber_cidade(telefone, sessao, momento, texto, campo):
    """
    Resposta com UMA ponta da rota (origem ou destino), por nome de cidade ou
    por CEP. Os dois lados precisam vir do MESMO jeito: quem começou pela cidade
    continua pela cidade, e quem começou pelo CEP continua pelo CEP.
    """
    dados = sessao["dados"]

    # O cliente respondeu com um CEP em vez do nome da cidade
    if cep.parece_cep(texto):
        if not _combina_com_a_rota(dados, por_cep=True):
            return _recusar_mistura(sessao, campo)
        cidade_achada = _guardar_cep(sessao, campo, texto)
        if cidade_achada:
            return _cidade_confirmada(telefone, sessao, momento, campo, cidade_achada,
                                      cep_usado=sessao["dados"][f"cep_{campo}"])
        return _pedir_de_novo(
            sessao, campo,
            f"Não consegui descobrir a cidade do CEP {cep.formatar(texto)} agora.")

    situacao, resultado = resolver_cidade(texto)
    if situacao != "ok":
        # talvez a cidade esteja no meio de uma frase ("é de goiania go")
        cidade = achar_cidade_no_texto(texto)
        if cidade:
            situacao, resultado = "ok", cidade

    if situacao == "ok":
        # A rota começou pelo CEP: a cidade não entra, para não misturar
        if not _combina_com_a_rota(dados, por_cep=False):
            return _recusar_mistura(sessao, campo)
        return _cidade_confirmada(telefone, sessao, momento, campo, resultado)

    if situacao == "ambigua":
        sessao["opcoes"] = resultado
        sessao["etapa"] = f"escolher_{campo}"
        lista = "\n".join(f"{i}. {nome_completo(c)}" for i, c in enumerate(resultado, start=1))
        return f"Encontrei mais de uma cidade com esse nome. Digite o número da correta:\n{lista}"

    motivo = "Não encontrei essa cidade."
    if resultado:
        motivo += "\nVocê quis dizer: " + ", ".join(resultado) + "?"
    return _pedir_de_novo(sessao, campo, motivo, texto)


def _escolher_cidade(telefone, sessao, texto, momento):
    """Cliente escolhe, pelo número, uma das cidades com nome repetido."""
    campo = _campo_da_etapa(sessao["etapa"])
    opcoes = sessao.get("opcoes", [])
    if texto.isdigit() and 1 <= int(texto) <= len(opcoes):
        return _cidade_confirmada(telefone, sessao, momento, campo, opcoes[int(texto) - 1])
    if not texto.strip() or texto.isdigit():     # vazio ou número que não está na lista
        lista = "\n".join(f"{i}. {nome_completo(c)}" for i, c in enumerate(opcoes, start=1))
        sessao["nao_entendeu"] = True
        return f"Digite o número da cidade correta, por favor:\n{lista}"
    return _receber_cidade(telefone, sessao, momento, texto, campo)   # talvez tenha digitado o nome de novo


def _cidade_confirmada(telefone, sessao, momento, campo, cidade, cep_usado=None):
    sessao["dados"][campo] = cidade
    # Marca que foi o CLIENTE quem escreveu o nome da cidade. Quando a cidade veio
    # de um CEP, essa marca fica de fora, e a planilha guarda o CEP, e não a cidade.
    if not cep_usado:
        sessao["dados"][f"cidade_{campo}_dita"] = True
    sessao.pop("opcoes", None)
    rotulo = "Origem" if campo == "origem" else "Destino"
    confirmacao = f"{rotulo}: {nome_completo(cidade)}"
    if cep_usado:
        confirmacao += f" (CEP {cep_usado})"
    return _continuar(telefone, sessao, momento, [confirmacao])


# =================================================================
# Cotação: medidas (peso cubado) e cálculo final
# =================================================================
def etapa_medidas(telefone, sessao, texto, momento):
    comando = normalizar(texto)
    if comando in ("PULAR", "PULA", "NAO SEI", "NAO", "N", "SEM MEDIDAS") or comando.startswith("NAO SEI"):
        sessao["dados"]["qtd_informada"] = False
        return _finalizar_cotacao(telefone, sessao, momento, None)

    # Polegada o bot não converte: daria número quebrado e quase ninguém mede
    # carga assim no Brasil. Metro e milímetro ele converte sozinho.
    if usou_polegadas(texto):
        return _pedir_de_novo(sessao, "medidas", "As medidas precisam estar em *centímetros* "
                                         "ou em *metros*. Ex.: 50x40x30 cm, ou 1x1x1,5 m.")

    medidas = ler_medidas(texto)
    if medidas is None:
        return _pedir_de_novo(sessao, "medidas", "Não consegui entender as medidas.", texto)
    # Guarda se a quantidade foi dita pelo cliente em todos os volumes, ou suposta
    # pelo bot (1 volume) em algum deles
    sessao["dados"]["qtd_informada"] = quantidade_de_todos_informada(texto)
    return _finalizar_cotacao(telefone, sessao, momento, medidas)


def _finalizar_cotacao(telefone, sessao, momento, medidas):
    """Calcula peso considerado, distância e preço, e mostra a cotação."""
    dados = sessao["dados"]
    dados["peso_cubado"] = None
    dados["medidas"] = medidas
    if medidas:
        dados["peso_cubado"] = calcular_peso_cubado(medidas)

    # No fracionado, cobra-se pelo MAIOR entre o peso real e o peso cubado
    dados["peso_considerado"] = max(dados["peso"], dados["peso_cubado"] or 0)
    dados["km"] = distancia_km(dados["origem"], dados["destino"])

    if dados["peso_considerado"] > config.PESO_MAXIMO_KG:
        return _encaminhar(
            telefone, sessao, momento, evento="carga_volumosa",
            motivo=f"Carga volumosa — peso cubado de {formatar_numero(dados['peso_cubado'])} kg",
            inicio=(f"Pelas medidas, a sua carga é bem volumosa (peso cubado de "
                    f"{formatar_numero(dados['peso_cubado'])} kg). A cotação dela é feita "
                    "pela nossa equipe.\n"))

    # Qualquer distância tem preço (a tabela cobre o Brasil inteiro)
    dados["valor"] = calcular_preco(dados["peso_considerado"], dados["km"])

    # Cria a linha da cotação na planilha e guarda, para atualizar o evento depois
    # (se a conversa mudar de rumo, a MESMA linha é atualizada)
    sessao["registro"] = _registrar_linha(telefone, dados, momento, evento="cotacao",
                                          protocolo="nao_se_aplica",
                                          documento=sessao.get("cnpj"))
    sessao["etapa"] = "pos_cotacao"
    return texto_cotacao(dados, sessao)


def _um_volume(volume):
    """(3, [50, 40, 30]) -> '3 volumes de 50x40x30 cm'"""
    quantidade, dimensoes_cm = volume
    cm = "x".join(formatar_numero(m) for m in dimensoes_cm)
    return f"{quantidade} volume{'s' if quantidade > 1 else ''} de {cm} cm"


def _texto_medidas(volumes):
    """A lista de volumes escrita numa linha só (para o Telegram e a confirmação)."""
    return " + ".join(_um_volume(v) for v in volumes)


def _resumo_das_medidas(volumes):
    """
    Versão curta, para confirmar ao cliente sem encher a tela.
      um tamanho só  -> '1 volume de 50x40x30 cm'
      vários         -> '9 volumes, em 5 tamanhos'
    """
    if len(volumes) == 1:
        return _um_volume(volumes[0])
    total = _total_de_volumes(volumes)
    return f"{total} volumes, em {len(volumes)} tamanhos"


def _total_de_volumes(volumes):
    """Quantos volumes a carga tem no total, somando todas as linhas."""
    return sum(quantidade for quantidade, _ in volumes)


def texto_cotacao(dados, sessao=None):
    nome = (sessao or {}).get("nome")
    abertura = f"Pronto, {nome}!" if nome else "Pronto!"
    linhas = [
        f"{abertura} Aqui está a sua *cotação de frete fracionado*.",
        "",
        f"Origem: {nome_completo(dados['origem'])}",
        f"Destino: {nome_completo(dados['destino'])}",
        f"Distância aproximada: {dados['km']} km",
    ]
    if dados["peso_cubado"] is not None:
        volumes = dados["medidas"]
        cubado = formatar_numero(dados["peso_cubado"])
        linhas.append(f"Peso real: {formatar_numero(dados['peso'])} kg")
        if len(volumes) == 1:
            linhas.append(f"Peso cubado: {cubado} kg ({_texto_medidas(volumes)})")
        else:
            # Carga com volumes de tamanhos diferentes: cada linha aparece
            # separada, para o cliente conferir o que o bot entendeu.
            linhas.append(f"Peso cubado: {cubado} kg, somando:")
            linhas += [f"  {_um_volume(volume)}" for volume in volumes]
        linhas += [
            f"Peso considerado: {formatar_numero(dados['peso_considerado'])} kg",
            "_No frete fracionado, vale o maior entre o peso real e o peso cubado._",
        ]
    else:
        linhas += [
            f"Peso: {formatar_numero(dados['peso'])} kg",
            "_A cotação foi feita só pelo peso. Se a carga for volumosa, o valor pode mudar._",
        ]
    linhas += [
        "",
        f"*Valor estimado: {formatar_reais(dados['valor'])}*",
        "_Esse valor é negociável, e o valor final é confirmado por um atendente._",
        "",
        TEXTO_HORARIO,
        "",
        "O que você quer fazer agora?",
        OPCOES_POS_COTACAO,
    ]
    return "\n".join(linhas)


def etapa_pos_cotacao(telefone, sessao, texto, momento):
    comando = normalizar(texto)
    if comando == "1" or "NEGOCIAR" in comando.split():
        return _encaminhar(telefone, sessao, momento, "Cliente quer NEGOCIAR a cotação")
    if comando == "2":
        return iniciar_cotacao(telefone, sessao, momento)
    if comando == "3":
        sessao["etapa"] = "menu"
        return texto_menu()

    resposta_faq = faq.buscar_por_texto(texto)
    if resposta_faq:
        return f"{resposta_faq}\n\n{OPCOES_POS_COTACAO}"
    if _e_pergunta_de_verdade(sessao, texto):
        return _nao_sei_responder(sessao, texto, momento)
    sessao["nao_entendeu"] = True
    return f"Digite o número de uma opção, por favor:\n{OPCOES_POS_COTACAO}"


def etapa_faq(telefone, sessao, texto, momento):
    if texto.isdigit():
        resposta = faq.resposta_por_numero(int(texto))
        if resposta:
            return f"{resposta}\n\nDigite outro número para ver outra dúvida, ou *MENU* para voltar."
    resposta = faq.buscar_por_texto(texto)
    if resposta:
        return f"{resposta}\n\nDigite outro número para ver outra dúvida, ou *MENU* para voltar."
    if _e_pergunta_de_verdade(sessao, texto):
        return _nao_sei_responder(sessao, texto, momento)
    sessao["nao_entendeu"] = True
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
    return f"falta só {_nome_da_rota(sessao, etapa)}.\n\n{_pergunta_da_rota(sessao, etapa)}"


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
            nome = sessao.get("nome")
            ola = f"{nome}, você ainda está aí?" if nome else "Oi! Você ainda está aí?"
            lembretes.append((telefone, f"{ola} Para terminar a sua cotação, "
                                        + _pedido_da_etapa(sessao)))
    return lembretes


def responder_nao_texto(telefone, momento=None):
    """Resposta para áudio, foto, figurinha etc."""
    momento = momento or agora_brasilia()
    sessao = sessoes.get(telefone)
    aviso = "Por aqui eu consigo ler só mensagens escritas."
    if sessao and sessao["etapa"] in ETAPAS_COLETA and not _sessao_expirou(sessao, momento):
        sessao["ultima"] = momento
        pedido = _pedido_da_etapa(sessao)
        return f"{aviso}\nPara terminar a sua cotação, {pedido}"
    return f"{aviso}\nSe quiser ver as opções, digite MENU."


# =================================================================
# Chamar um atendente (envia o alerta para o celular)
# =================================================================
# Letras e números fáceis de ler (sem 0/O, 1/I/L), para o código do protocolo
_CARACTERES_PROTOCOLO = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"


def gerar_protocolo(momento, prefixo=None):
    """
    Cria o número do atendimento, ex.: ATD-04102026-1432-K7
    (dia/mês/ano - hora:minuto - código sorteado).
    prefixo: ATD (WhatsApp, o padrão) ou ATM (e-mail, usado pelo todos_email.py).
    Não usa contagem (001, 002...) porque o servidor grátis pode reiniciar e
    a contagem voltaria do zero, repetindo números. Data com ano + hora + código
    sorteado não se repete, mesmo depois de um reinício ou de muitos anos.
    """
    codigo = "".join(random.choice(_CARACTERES_PROTOCOLO) for _ in range(2))
    prefixo = prefixo or config.PREFIXO_PROTOCOLO
    return f"{prefixo}-{momento.strftime('%d%m%Y-%H%M')}-{codigo}"


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


def chamar_atendente(telefone, sessao, momento, motivo, inicio="", evento=None, texto=""):
    """
    Passa o cliente para um atendente humano:
      1. gera o protocolo;
      2. registra na planilha de cotações, já com o protocolo;
      3. manda o alerta para o Telegram do atendente;
      4. avisa o cliente, mostrando o protocolo.

    evento: preenchido quando foi o BOT que decidiu chamar o atendente
            (frete_dedicado, ocorrencia, cnpj, carga_volumosa, insistencia ou duvida).
            Quando vem vazio, foi o CLIENTE que pediu, e o evento vira "atendimento".
            O pedido de desconto entra aqui: é um pedido do cliente.

    Na planilha:
      - o cliente já tinha recebido uma cotação e não começou outra:
        atualiza A MESMA linha, preenchendo o protocolo e TROCANDO o evento;
      - não havia cotação: cria uma linha nova com o evento.

    No fim, a conversa com o bot é encerrada e volta ao início: a próxima
    mensagem do cliente é uma cotação nova, com CNPJ e protocolo novos.

    Assim o evento guarda como a conversa TERMINOU. Para saber se houve cotação,
    basta olhar a coluna valor: preenchida quer dizer que o cliente viu um preço.
    """
    # A mensagem que levou o cliente até aqui pode trazer rota e peso. O bot
    # aproveita antes de registrar, para o atendente não perguntar de novo.
    _aproveitar_dados(sessao, texto)

    dados = sessao.get("dados", {})
    protocolo = gerar_protocolo(momento)
    sessao["protocolo"] = protocolo

    evento = evento or "atendimento"        # sem evento, foi o cliente que pediu
    if sessao.get("registro"):
        sessao.pop("registro").marcar_evento(protocolo, evento)
    else:
        _registrar_linha(telefone, dados, momento, evento=evento, protocolo=protocolo,
                         documento=sessao.get("cnpj"))

    # O ❌ diz que ninguém atendeu ainda. O atendente toca no botão "Já atendi"
    # e ele vira ✅, na mesma mensagem (veja o todos_alerta.py).
    linhas = [f"{alerta.MARCA_PENDENTE} NOVO ATENDIMENTO — Protocolo {protocolo}",
              f"Empresa: {config.NOME_EMPRESA}",
              f"Motivo: {motivo}",
              f"Cliente (WhatsApp): +{telefone}",
              f"Nome: {sessao.get('nome') or 'nao informado'}",
              f"CNPJ: {sessao.get('cnpj') or 'nao informado'}",
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
    enviar_alerta("\n".join(linhas), link=_link_whatsapp(telefone),
                  rotulo_do_link="Abrir conversa")

    # A conversa com o bot termina aqui. O bot não fica esperando o atendente,
    # porque ele não tem como saber se o cliente está sendo atendido: o atendente
    # responde por outro número. A próxima mensagem já é uma cotação nova, com
    # CNPJ e NOME confirmados de novo e protocolo novo.
    #
    # O nome sai junto com o CNPJ de propósito: o WhatsApp pode ser o número de
    # uma empresa, e não de uma pessoa. Quem escrever depois pode ser outro
    # funcionário, e chamar essa pessoa pelo nome de quem falou antes seria errado.
    # O nome ainda é usado na despedida, então ele é lido ANTES de ser apagado.
    nome = sessao.get("nome")
    sessao["etapa"] = "inicio"
    sessao["dados"] = {}
    for guardado in ("cnpj", "nome", "registro", "primeira_mensagem", "tentativas_cnpj",
                     "perguntas_anotadas", "opcoes", "etapa_anterior"):
        sessao.pop(guardado, None)
    _zerar_insistencia(sessao)

    if esta_aberto(momento):
        quando = "em instantes"
    else:
        quando = (f"assim que abrirmos (atendimento das {config.HORA_ABRE}h "
                  f"às {config.HORA_FECHA}h)")
    pronto = f"Pronto, {nome}!" if nome else "Pronto!"
    aviso = (f"{pronto} Já avisei a nossa equipe.\n"
             f"O seu número de protocolo é: *{protocolo}*\n\n"
             f"Um atendente vai falar com você pelo {_texto_whatsapp_oficial()} {quando}.")
    return f"{inicio}{aviso}\n\n_Precisa de outra cotação? É só me chamar aqui._"


def _medidas_planilha(volumes):
    """
    As medidas padronizadas para a planilha, sempre em centímetros.
      um volume só        -> '50x40x30 cm'
      carga com vários    -> '2x 486x30x30 cm | 2x 360x30x30 cm | 1x 80x30x30 cm'
    """
    if len(volumes) == 1:
        _, dimensoes_cm = volumes[0]
        return "x".join(formatar_numero(m) for m in dimensoes_cm) + " cm"
    partes = []
    for quantidade, dimensoes_cm in volumes:
        cm = "x".join(formatar_numero(m) for m in dimensoes_cm)
        partes.append(f"{quantidade}x {cm} cm")
    return " | ".join(partes)


def _cidade_para_planilha(dados, campo):
    """
    O nome da cidade para a planilha, mas SÓ quando foi o cliente que escreveu
    esse nome. Quando ele informou o CEP, a cidade fica como nao_informado e
    quem guarda a informação é a coluna do CEP.

    O motivo é registrar o que o CLIENTE disse, e não o que o bot descobriu. As
    duas colunas juntas contam a história inteira: dá para ver quantos clientes
    pedem por cidade e quantos pedem por CEP.
    """
    if dados.get(f"cidade_{campo}_dita") and dados.get(campo):
        return nome_completo(dados[campo])
    return "nao_informado"


def _registrar_linha(telefone, dados, momento, evento, protocolo, documento=None):
    """
    Cria uma linha na planilha do Drive (veja as regras de cada coluna em todos_registro.py).
    Texto obrigatório nunca fica vazio: o que o cliente não informou vira nao_informado.
    Número que não existe fica vazio (nunca 0).

    O CNPJ (documento) fica na sessão, e não nos dados da cotação, por isso ele
    entra por fora.

    O primeiro nome do cliente NÃO vai para esta planilha, de propósito. Ele serve
    para o bot conversar e para o atendente chamar o cliente pelo nome no Telegram.
    Para a análise das cotações ele não diz nada: quem é a empresa já está no CNPJ,
    e quem é a pessoa já está no telefone. Guardar o nome aqui seria juntar dado
    pessoal numa planilha que vira base de análise, sem ganho nenhum.
    """
    tem_medidas = bool(dados.get("medidas"))
    # A quantidade só vai para a planilha se o CLIENTE disse quantos volumes são.
    # Se ele mandou só "50x40x30", o bot calculou como 1 volume, mas não registra esse 1.
    tem_qtd = tem_medidas and dados.get("qtd_informada", False)
    return registrar({
        "data_hora": momento.strftime("%Y-%m-%d %H:%M"),
        "telefone": telefone,
        "cnpj": documento or "nao_informado",
        "protocolo": protocolo,
        "cidade_origem": _cidade_para_planilha(dados, "origem"),
        "cep_origem": dados.get("cep_origem") or "nao_informado",
        "cidade_destino": _cidade_para_planilha(dados, "destino"),
        "cep_destino": dados.get("cep_destino") or "nao_informado",
        "distancia_km": dados.get("km"),
        "peso_kg": dados.get("peso"),
        "qtd_transportada": _total_de_volumes(dados["medidas"]) if tem_qtd else None,
        "preenchimento_qtd_transportada": "informado" if tem_qtd else "nao_informado",
        "medidas": _medidas_planilha(dados["medidas"]) if tem_medidas else None,
        "peso_cubado_kg": dados.get("peso_cubado"),
        "preenchimento_medidas_cubado": "informado" if tem_medidas else "nao_informado",
        "peso_considerado_kg": dados.get("peso_considerado"),
        "valor": dados.get("valor"),
        "evento": evento,
    })


# Liga o nome de cada etapa à função que a trata.
ETAPAS = {
    "inicio": etapa_inicio,
    "cnpj": etapa_cnpj,
    "nome": etapa_nome,
    "nome_atendente": etapa_nome_atendente,
    "menu": etapa_menu,
    "origem": etapa_coleta,
    "destino": etapa_coleta,
    "peso": etapa_coleta,
    "escolher_origem": _escolher_cidade,
    "escolher_destino": _escolher_cidade,
    "medidas": etapa_medidas,
    "pos_cotacao": etapa_pos_cotacao,
    "faq": etapa_faq,
    "confirmar_atendente": etapa_confirmar_atendente,
}