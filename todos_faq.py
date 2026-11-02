"""
Dúvidas frequentes dos clientes e as respostas.

As respostas não foram inventadas: elas seguem o que o atendimento da empresa
já responde hoje no WhatsApp, lido a partir de 99 conversas reais exportadas
do CRM (prazo contado a partir da coleta, 72 horas para coletar no fracionado,
porta a porta com seguro, impostos e rastreamento, boleto depois do CT-e).

Cada dúvida tem:
  - "pergunta": o texto que aparece na lista para o cliente;
  - "palavras": palavras-chave FORTES. Elas só aparecem quando o assunto é
                mesmo aquele ("fracionado", "cte", "cubagem", "boleto"). Uma
                delas já basta para o bot responder, em qualquer frase;
  - "genericas": palavras-chave FRACAS. São palavras que grudam em qualquer
                assunto ("entrega", "hora", "caixa", "quanto tempo", "limite").
                Uma delas só responde quando a frase INTEIRA é daquele assunto,
                ou seja, quando não sobra na mensagem nenhuma palavra que a
                dúvida não conheça (explicado em buscar_por_texto);
  - "resposta": o que o bot manda;
  - "confirmar": True = regra da empresa que PRECISA ser confirmada com o
                 dono antes de colocar no ar.

Por que existem palavras fracas:
  Uma palavra-chave pode ser o ASSUNTO da pergunta ou só um detalhe dela.
  "Em quanto tempo vocês entregam?" é sobre prazo de entrega. Já "O certificado
  de origem é emitido em quanto tempo?" tem o mesmo "quanto tempo", mas o
  assunto é outro, que o bot não conhece. Responder o prazo de entrega aí seria
  dar uma resposta errada com toda a confiança, e pior: o bot acharia que soube
  responder, então a pergunta nem iria para a base de conhecimento.
  Por isso as palavras que grudam em qualquer assunto ficam em "genericas" e
  precisam de companhia: "quanto tempo" + "entregam" responde; "quanto tempo"
  sozinho, com um assunto estranho na frase, vira pergunta nova para uma pessoa
  responder (veja o todos_aprendizado.py). O bot prefere admitir que não sabe
  a chutar.

Para mudar uma resposta, é só editar o texto aqui. Não precisa mexer em
mais nada do código.

Além das dúvidas escritas aqui, o bot também usa as respostas APROVADAS na
planilha "base_conhecimento" (veja o todos_aprendizado.py). Elas vêm primeiro,
porque são mais específicas: só existem porque um dia o bot não soube responder
e uma pessoa escreveu a resposta certa.

Atenção: alguns assuntos NÃO são respondidos aqui, porque o bot chama um
atendente direto (está no todos_conversa.py): frete dedicado, pedido de
desconto e problema com uma carga já enviada.
"""
import todos_aprendizado as aprendizado
import todos_config as config
from todos_distancia import normalizar

HORARIO = f"{config.HORA_ABRE}h às {config.HORA_FECHA}h"

# Palavras que não mudam o assunto de uma pergunta: artigos, preposições,
# pronomes, cumprimentos, educação e as palavras do dia a dia da transportadora
# ("frete", "carga", "mercadoria"), que aparecem em pergunta de qualquer assunto.
# Elas são ignoradas quando o bot confere se sobrou um assunto estranho na frase.
PALAVRAS_SEM_ASSUNTO = {
    # perguntar
    "QUAL", "QUAIS", "QUE", "QUEM", "QUANDO", "ONDE", "QUANTO", "QUANTA",
    "QUANTOS", "QUANTAS", "SERA", "COMO",
    # ligar as palavras
    "O", "A", "OS", "AS", "UM", "UMA", "UNS", "UMAS", "DE", "DO", "DA", "DOS",
    "DAS", "EM", "NO", "NA", "NOS", "NAS", "AO", "AOS", "E", "OU", "COM", "SEM",
    "POR", "PARA", "PRA", "PRO", "SOBRE", "SE", "MAIS", "MENOS", "MUITO", "JA",
    "SO", "AI", "NE", "ENTAO", "TAMBEM", "AINDA", "TEM", "TEMOS", "TENHO",
    "SAO", "ESTA", "ESTAO", "FOI", "VAI", "VAO", "POSSO", "PODE", "PODEM",
    "FAZ", "FAZEM", "FICA", "FICAM", "SER", "VEM", "DAR", "DA", "DEIXA",
    # quem fala com quem
    "VOCE", "VOCES", "VC", "VCS", "EU", "ME", "MEU", "MINHA", "MEUS", "MINHAS",
    "SEU", "SUA", "SEUS", "SUAS", "GENTE", "LA", "AQUI",
    # cumprimento e educação
    "OI", "OLA", "BOM", "BOA", "DIA", "TARDE", "NOITE", "TUDO", "BEM", "FAVOR",
    "OBRIGADO", "OBRIGADA", "POIS", "DESCULPA", "DESCULPE", "AMIGO", "PESSOAL",
    # jeitos de abrir uma pergunta e de amaciar a pergunta
    "QUERIA", "QUERO", "GOSTARIA", "PRECISO", "PRECISAVA", "SABER", "DUVIDA",
    "PERGUNTA", "INFORMACAO", "INFORMACOES", "AJUDA", "DIZER", "FALAR",
    "MEDIA", "APROXIMADAMENTE", "NORMALMENTE", "GERALMENTE", "COSTUMA",
    "COSTUMAM", "EXATO", "EXATAMENTE", "CERTO", "MESMO", "REALMENTE",
    # o dia a dia da transportadora: aparecem em pergunta de qualquer assunto
    "FRETE", "FRETES", "CARGA", "CARGAS", "MERCADORIA", "MERCADORIAS",
    "TRANSPORTE", "ENVIO", "ENVIAR", "MANDAR", "PEDIDO", "MATERIAL",
    "PRODUTO", "PRODUTOS", "EMPRESA", "CLIENTE", "SERVICO",
}

DUVIDAS = [
    {
        "pergunta": "Como funciona o frete fracionado?",
        "palavras": ["fracionado"],
        # "como funciona" combina com quase qualquer pergunta.
        "genericas": ["como funciona", "funciona"],
        "resposta": ("No frete fracionado, sua carga divide o espaço do veículo com cargas "
                     "de outros clientes. Assim você paga só pelo espaço que usa, o que deixa "
                     "o frete mais barato para cargas pequenas e médias."),
        "confirmar": False,
    },
    {
        # Esta dúvida quase sempre é vista pelo número, na lista. Quando o cliente
        # ESCREVE sobre dedicado, o todos_conversa.py já explica e chama o atendente.
        "pergunta": "Qual a diferença entre frete fracionado e frete dedicado?",
        "palavras": ["dedicado", "carga fechada", "lotacao", "exclusivo",
                     "carreta", "truck", "bitruck", "toco", "vuc"],
        # "diferenca" gruda em qualquer assunto ("qual a diferença de prazo?").
        "genericas": ["diferenca", "diferencas"],
        "resposta": ("No *fracionado*, a sua carga divide o veículo com a de outros clientes. "
                     "É esse que eu coto aqui na hora.\n"
                     "No *dedicado*, o veículo sai só com a sua mercadoria, com o modelo de "
                     "caminhão escolhido para a carga (toco, 3/4, truck, bitruck, carreta).\n"
                     "O dedicado exige uma análise mais detalhada, então ele é sempre montado "
                     "por um atendente."),
        "confirmar": False,
    },
    {
        "pergunta": "O que está incluso no valor do frete?",
        "palavras": ["incluso", "inclui", "incluido", "porta a porta", "taxas",
                     "imposto", "impostos", "icms"],
        "resposta": ("Nossa operação é de *porta a porta*: a gente coleta e segue direto para a "
                     "entrega no destino final.\n"
                     "Estão inclusos o seguro da mercadoria, os impostos e o rastreamento "
                     "24 horas."),
        "confirmar": True,
    },
    {
        "pergunta": "Em quanto tempo vocês coletam a carga?",
        "palavras": ["coleta", "coletar", "coletam", "buscar", "buscam", "retirar",
                     "retiram", "retirada"],
        "resposta": ("No frete fracionado, nosso prazo é de *até 72 horas* para coletar o "
                     "material.\n"
                     "Para marcar uma data e um horário, um atendente acerta com você. "
                     "Para alinhar a coleta precisamos do endereço, de um contato no local "
                     "e da nota fiscal."),
        "confirmar": True,
    },
    {
        "pergunta": "Qual o prazo de entrega?",
        # Só estas expressões dizem o assunto inteiro, sem precisar de companhia.
        "palavras": ["prazo de entrega", "prazo da entrega", "prazo para entrega",
                     "prazo de entregar", "prazo para entregar"],
        # Todo o resto gruda em qualquer assunto: "quanto tempo" serve para
        # perguntar o prazo de uma entrega, de uma emissão de documento, de um
        # cadastro... e "entrega" sozinha serve para "entrega em condomínio?".
        # Por isso aqui precisa de duas: "quanto tempo" + "entregam", por exemplo.
        "genericas": ["prazo", "demora", "demoram", "demorar", "quantos dias",
                      "quanto tempo", "quando chega", "chega quando", "chega",
                      "chegar", "chegada", "entrega", "entregar", "entregam", "entregue"],
        "resposta": ("O prazo de entrega é contado *a partir da coleta*, não do fechamento.\n"
                     "Em rotas mais curtas fica em torno de 3 dias após a coleta. Em rotas "
                     "longas pode chegar a 8 dias.\n"
                     "O prazo exato da sua rota é confirmado por um atendente."),
        "confirmar": True,
    },
    {
        "pergunta": "Qual o peso máximo que vocês transportam?",
        "palavras": ["peso maximo", "limite de peso", "peso limite", "quantos quilos",
                     "quantas toneladas"],
        # "limite" e "maximo" grudam em qualquer assunto ("limite de crédito",
        # "valor máximo da nota"), então sozinhos não respondem.
        "genericas": ["limite", "maximo", "peso", "quilos", "toneladas", "kg"],
        "resposta": (f"Trabalhamos com cargas de até {config.PESO_MAXIMO_KG:,} kg. ".replace(",", ".")
                     + "Esse limite vale para o peso real e também para o peso cubado "
                       "(calculado pelas medidas da carga).\n"
                       "Acima disso, a cotação é feita por um atendente."),
        "confirmar": False,
    },
    {
        "pergunta": "O que é peso cubado? Por que pedem as medidas?",
        "palavras": ["valor muda", "cubagem", "cubado", "medidas"],
        # "tamanho" e "volume" grudam em qualquer assunto ("tamanho do caminhão").
        "genericas": ["mudar", "tamanho", "volume", "volumes", "medida"],
        "resposta": ("Uma carga leve, mas grande, ocupa muito espaço no caminhão. Por isso, além "
                     "do peso real, calculamos o *peso cubado* a partir das medidas da carga. "
                     "O frete é cobrado pelo MAIOR dos dois.\n"
                     "Na cotação, envie as medidas em *centímetros*: "
                     "comprimento x largura x altura. Ex.: 50x40x30\n"
                     "Se os volumes tiverem tamanhos diferentes, mande um por linha. "
                     "O bot soma o volume de cada linha e cobra pelo total.\n"
                     "Ex.: uma caixa de 100x100x100 cm pesando 20 kg tem peso cubado de "
                     f"{config.FATOR_CUBAGEM} kg, e a cotação usa {config.FATOR_CUBAGEM} kg.\n"
                     "Se a carga já estiver paletizada, envie a medida com o palete, que é "
                     "assim que ela vai viajar.\n"
                     "Se você não informar as medidas, a cotação é feita só pelo peso e pode "
                     "ser revisada pelo atendente."),
        "confirmar": True,
    },
    {
        "pergunta": "Para quais regiões vocês transportam?",
        "palavras": ["regiao", "regioes", "cidades", "estados", "todo o brasil",
                     "brasil todo"],
        # "atendem", "transportam" e "levam" grudam em qualquer assunto
        # ("vocês atendem sábado?", "vocês transportam geladeira?").
        "genericas": ["atendem", "atende", "transportam", "transporta", "levam",
                      "leva", "brasil", "estado", "cidade"],
        "resposta": ("Atendemos rotas em todo o Brasil. Me diga a cidade de origem e a de "
                     "destino que eu calculo o frete fracionado na hora."),
        "confirmar": True,
    },
    {
        "pergunta": "Quais as formas de pagamento?",
        "palavras": ["pagamento", "pix", "boleto", "deposito", "transferencia",
                     "faturar", "faturado", "a prazo"],
        "genericas": ["pagar", "paga", "pago"],
        "resposta": ("O pagamento é em boleto. A política da empresa é boleto em *até 10 dias* "
                     "após a emissão do CT-e.\n"
                     "Prazo maior, ou faturamento, depende de aprovação do nosso financeiro. "
                     "Para tratar disso, um atendente fala com você."),
        "confirmar": True,
    },
    {
        "pergunta": "O que é o CT-e?",
        "palavras": ["cte", "ct e", "conhecimento de transporte"],
        "resposta": ("O CT-e é o documento fiscal do transporte, ou seja, é a nota fiscal do "
                     "frete, emitida pela transportadora.\n"
                     "A nota fiscal da mercadoria continua sendo a sua."),
        "confirmar": False,
    },
    {
        "pergunta": "Quais documentos são necessários?",
        "palavras": ["documento", "documentos", "nota fiscal", "declaracao de conteudo",
                     "declaracao"],
        "genericas": ["nota", "cadastro"],
        "resposta": ("A carga precisa ir com a nota fiscal. Se você for pessoa física e não "
                     "tiver nota, é possível enviar com declaração de conteúdo. "
                     "Todo transporte é feito com emissão de CT-e.\n"
                     "Cadastro de fornecedor, envio dos documentos da empresa e proposta em "
                     "PDF são feitos por um atendente."),
        "confirmar": True,
    },
    {
        "pergunta": "A carga tem seguro?",
        # Vale para as várias formas de perguntar a mesma coisa: "tem seguro?",
        # "o seguro já está incluso?", "e se a carga quebrar?", "tem cobertura?".
        # Relato de problema com carga JÁ ENVIADA não cai aqui: o todos_conversa.py
        # chama um atendente antes.
        "palavras": ["seguro", "segurada", "segurado", "cobertura",
                     "coberta", "coberto", "sinistro", "quebrar", "danificar",
                     "estragar", "se acontecer algo", "se acontecer alguma coisa",
                     "der problema", "quem paga"],
        "genericas": ["garantia", "garantido"],
        "resposta": ("Sim. Todas as nossas operações seguem com seguro da mercadoria, "
                     "do começo ao fim da viagem.\n"
                     "Para mercadorias de valor alto, informe o valor da nota ao atendente."),
        "confirmar": True,
    },
    {
        "pergunta": "Como acompanho a minha carga?",
        "palavras": ["rastrear", "rastreio", "rastreamento", "acompanhar", "acompanho",
                     "acompanhamento", "onde esta", "previsao de entrega"],
        "genericas": ["status", "localizacao", "posicao"],
        "resposta": ("Nossa operação tem rastreamento 24 horas.\n"
                     "Para ver a posição da sua carga, um atendente consulta no sistema da "
                     "operação e te passa o andamento pelo WhatsApp oficial da empresa."),
        "confirmar": True,
    },
    {
        "pergunta": "Como devo embalar a carga?",
        "palavras": ["embalagem", "embalar", "embalada", "pallet", "palete", "paletizada"],
        "genericas": ["caixa", "caixas"],
        "resposta": ("A carga deve estar bem embalada, protegida e identificada com o nome e o "
                     "endereço do destinatário. A embalagem é responsabilidade de quem envia.\n"
                     "Se a carga for paletizada, me envie a medida já com o palete."),
        "confirmar": True,
    },
    {
        "pergunta": "Que tipo de carga vocês não transportam?",
        "palavras": ["nao transporta", "nao transportam", "proibida", "proibido",
                     "perigosa", "perigoso", "tipo de carga", "animais", "animal vivo",
                     "dinheiro", "valores", "inflamavel", "inflamaveis", "quimico",
                     "quimicos", "bateria", "baterias"],
        "genericas": ["aceitam", "aceita", "ilegal", "ilegais"],
        "resposta": ("Não transportamos cargas ilegais, animais vivos, dinheiro ou valores, "
                     "nem produtos perigosos sem a documentação exigida. Em caso de dúvida, "
                     "fale com um atendente."),
        "confirmar": True,
    },
    {
        "pergunta": "Qual o horário de atendimento?",
        "palavras": ["horario", "que horas", "funcionamento", "expediente"],
        "genericas": ["hora", "horas", "abre", "abrem", "fecha", "fecham"],
        "resposta": f"Nosso atendimento funciona das {HORARIO}.",
        "confirmar": False,
    },
]


def texto_lista():
    """Monta a lista numerada de dúvidas para mostrar ao cliente."""
    linhas = ["*Dúvidas frequentes*", "Digite o número da dúvida:", ""]
    for numero, d in enumerate(DUVIDAS, start=1):
        linhas.append(f"{numero}. {d['pergunta']}")
    linhas += ["", "Ou digite *MENU* para voltar."]
    return "\n".join(linhas)


def _frase_toda_do_assunto(duvida, frase):
    """
    True quando NADA na frase fala de outro assunto.

    O bot junta todas as palavras-chave da dúvida (fortes e fracas) e confere o
    que sobrou na frase do cliente, ignorando as palavras de enfeite. Se sobrar
    alguma palavra que a dúvida não conhece, é sinal de que o cliente está
    perguntando de outra coisa:
      "qual o prazo?"                    -> sobra nada          -> é do assunto
      "vocês transportam geladeira?"     -> sobra "GELADEIRA"    -> NÃO é
      "o certificado de origem é emitido
       em quanto tempo?"                 -> sobra "CERTIFICADO",
                                             "ORIGEM", "EMITIDO" -> NÃO é
    """
    vocabulario = set()
    for chave in list(duvida["palavras"]) + list(duvida.get("genericas", ())):
        vocabulario.update(normalizar(chave).split())
    for palavra in frase.split():
        if palavra not in PALAVRAS_SEM_ASSUNTO and palavra not in vocabulario:
            return False
    return True


def _contar_fracas(duvida, frase):
    """
    Conta quantas palavras FRACAS diferentes da dúvida aparecem na frase.

    Duas palavras fracas não contam duas vezes quando uma está dentro da outra:
    em "quando chega minha carga", "chega" e "quando chega" batem as duas, mas é
    o mesmo pedaço do texto, então vale uma só. Sem isso, "como funciona" e
    "funciona" daria dois pontos sozinhas, e a conta perderia a graça.
    """
    achadas = [normalizar(p) for p in duvida.get("genericas", ())
               if f" {normalizar(p)} " in frase]
    sozinhas = [a for a in achadas
                if not any(outra != a and f" {a} " in f" {outra} " for outra in achadas)]
    return len(sozinhas)


def buscar_por_texto(texto):
    """
    Procura a resposta para a frase do cliente, nesta ordem:
      1. as respostas aprovadas na planilha "base_conhecimento";
      2. as dúvidas escritas aqui, pelas palavras-chave FORTES;
      3. as dúvidas escritas aqui, pelas palavras-chave FRACAS.

    Nas palavras fortes, uma já basta e, se várias dúvidas combinarem, fica com
    a que tiver mais palavras encontradas.

    As palavras fracas são o último recurso, porque elas grudam em qualquer
    assunto. Elas só respondem quando a frase INTEIRA é daquele assunto, isto é,
    quando não sobra na mensagem nenhuma palavra que a dúvida não conheça:
      "em quanto tempo vocês entregam?"   -> responde o prazo de entrega
      "O certificado de origem é emitido
       em quanto tempo?"                  -> sobra "certificado de origem", que o
                                             bot não conhece, então ele não chuta:
                                             vira pergunta nova na base de
                                             conhecimento e o bot oferece um
                                             atendente.
    É esse cuidado que impede o bot de dar uma resposta errada com confiança e,
    pior, de achar que soube responder e nunca mandar a pergunta para ninguém.

    Devolve a resposta (texto) ou None.
    """
    # 1º: as respostas aprovadas na planilha. Vêm antes porque são específicas:
    # alguém escreveu aquela resposta justamente para aquela pergunta.
    aprendida = aprendizado.buscar_resposta(texto)
    if aprendida:
        return aprendida

    frase = f" {normalizar(texto)} "

    # 2º: palavras fortes. Uma já basta.
    melhor, melhor_pontos = None, 0
    for d in DUVIDAS:
        pontos = sum(1 for p in d["palavras"] if f" {normalizar(p)} " in frase)
        if pontos > melhor_pontos:
            melhor, melhor_pontos = d, pontos
    if melhor:
        return melhor["resposta"]

    # 3º: palavras fracas. Só valem se a frase inteira for daquele assunto.
    melhor, melhor_pontos = None, 0
    for d in DUVIDAS:
        pontos = _contar_fracas(d, frase)
        if pontos == 0:
            continue
        if not _frase_toda_do_assunto(d, frase):
            continue
        if pontos > melhor_pontos:
            melhor, melhor_pontos = d, pontos
    return melhor["resposta"] if melhor else None


def resposta_por_numero(numero):
    if 1 <= numero <= len(DUVIDAS):
        return DUVIDAS[numero - 1]["resposta"]
    return None