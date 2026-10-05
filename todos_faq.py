"""
Dúvidas frequentes dos clientes e as respostas.

Cada dúvida tem:
  - "pergunta": o texto que aparece na lista para o cliente;
  - "palavras": palavras-chave. Se o cliente digitar uma frase com essas
                palavras (ex.: "vocês têm seguro?"), o bot responde sozinho;
  - "resposta": o que o bot manda;
  - "confirmar": True = regra da empresa que PRECISA ser confirmada com o
                 dono antes de colocar no ar.

Para mudar uma resposta, é só editar o texto aqui. Não precisa mexer em
mais nada do código.
"""
from todos_distancia import normalizar
import todos_config as config

HORARIO = f"{config.HORA_ABRE}h às {config.HORA_FECHA}h"

DUVIDAS = [
    {
        "pergunta": "Como funciona o frete fracionado?",
        "palavras": ["fracionado", "como funciona", "funciona"],
        "resposta": ("No frete fracionado, sua carga divide o espaço do veículo com cargas "
                     "de outros clientes. Assim você paga só pelo espaço que usa, o que deixa "
                     "o frete mais barato para cargas pequenas e médias."),
        "confirmar": False,
    },
    {
        "pergunta": "Qual o peso máximo que vocês transportam?",
        "palavras": ["peso maximo", "limite", "quantos quilos", "maximo"],
        "resposta": (f"Trabalhamos com cargas de até {config.PESO_MAXIMO_KG:,} kg. ".replace(",", ".")
                     + "Esse limite vale para o peso real e também para o peso cubado "
                       "(calculado pelas medidas da carga)."),
        "confirmar": False,
    },
    {
        "pergunta": "Qual o prazo de entrega?",
        "palavras": ["prazo", "demora", "quantos dias", "chega quando", "entrega"],
        "resposta": ("O prazo depende da rota e pode ser combinado com a nossa equipe. "
                     "Depois da cotação, escolha a opção de falar com um atendente para "
                     "acertar a data que for melhor para você."),
        "confirmar": False,
    },
    {
        "pergunta": "Para quais regiões vocês transportam?",
        "palavras": ["regiao", "regioes", "atendem", "cidades", "estados", "brasil"],
        "resposta": ("Atendemos rotas em todo o Brasil. Faça uma cotação com a cidade de "
                     "origem e de destino que calculamos na hora."),
        "confirmar": True,
    },
    {
        "pergunta": "Vocês fazem a coleta da carga?",
        "palavras": ["coleta", "coletar", "buscar", "retirar", "retirada"],
        "resposta": ("Sim, a coleta pode ser combinada com a nossa equipe. "
                     "Informe o endereço e o melhor horário para o atendente."),
        "confirmar": True,
    },
    {
        "pergunta": "Quais documentos são necessários?",
        "palavras": ["documento", "documentos", "nota fiscal", "nota", "declaracao"],
        "resposta": ("A carga precisa ir com a nota fiscal. Se você for pessoa física e não "
                     "tiver nota, é possível enviar com declaração de conteúdo. "
                     "Todo transporte é feito com emissão de CT-e."),
        "confirmar": True,
    },
    {
        "pergunta": "Quais as formas de pagamento?",
        "palavras": ["pagamento", "pagar", "pix", "boleto", "deposito", "transferencia"],
        "resposta": ("Aceitamos PIX, boleto e depósito/transferência bancária. "
                     "Boleto a prazo pode ser combinado com o atendente."),
        "confirmar": True,
    },
    {
        "pergunta": "A carga tem seguro?",
        "palavras": ["seguro", "segurada", "garantia", "avaria", "extravio", "danificada"],
        "resposta": ("Sim. As cargas são transportadas com seguro. Para mercadorias de valor "
                     "alto, informe o valor da nota ao atendente."),
        "confirmar": True,
    },
    {
        "pergunta": "Como acompanho a minha carga?",
        "palavras": ["rastrear", "rastreio", "rastreamento", "acompanhar", "onde esta", "status"],
        "resposta": ("Depois que a carga for coletada, nossa equipe informa o andamento "
                     "da viagem pelo WhatsApp oficial da empresa."),
        "confirmar": True,
    },
    {
        "pergunta": "O que é peso cubado? Por que pedem as medidas?",
        "palavras": ["valor muda", "mudar", "cubagem", "cubado", "volume", "tamanho", "medidas"],
        "resposta": ("Uma carga leve, mas grande, ocupa muito espaço no caminhão. Por isso, além "
                     "do peso real, calculamos o *peso cubado* a partir das medidas da carga. "
                     "O frete é cobrado pelo MAIOR dos dois.\n"
                     "Na cotação, envie as medidas *apenas em centímetros*: "
                     "comprimento x largura x altura. Ex.: 50x40x30\n"
                     "Ex.: uma caixa de 100x100x100 cm pesando 20 kg tem peso cubado de "
                     f"{config.FATOR_CUBAGEM} kg, e a cotação usa {config.FATOR_CUBAGEM} kg.\n"
                     "Se você não informar as medidas, a cotação é feita só pelo peso e pode "
                     "ser revisada pelo atendente."),
        "confirmar": True,
    },
    {
        "pergunta": "Que tipo de carga vocês não transportam?",
        "palavras": ["nao transporta", "proibida", "proibido", "perigosa", "tipo de carga", "aceitam"],
        "resposta": ("Não transportamos cargas ilegais, animais vivos, dinheiro ou valores, "
                     "nem produtos perigosos sem a documentação exigida. Em caso de dúvida, "
                     "fale com um atendente."),
        "confirmar": True,
    },
    {
        "pergunta": "Como devo embalar a carga?",
        "palavras": ["embalagem", "embalar", "embalada", "caixa", "pallet"],
        "resposta": ("A carga deve estar bem embalada, protegida e identificada com o nome e o "
                     "endereço do destinatário. A embalagem é responsabilidade de quem envia."),
        "confirmar": True,
    },
    {
        "pergunta": "Qual o horário de atendimento?",
        "palavras": ["horario", "hora", "abre", "fecha", "funcionamento", "expediente"],
        "resposta": f"Nosso atendimento funciona das {HORARIO}.",
        "confirmar": False,
    },
]


def texto_lista():
    """Monta a lista numerada de dúvidas para mostrar ao cliente."""
    linhas = ["❓ *Dúvidas frequentes*", "Digite o número da dúvida:", ""]
    for numero, d in enumerate(DUVIDAS, start=1):
        linhas.append(f"{numero}. {d['pergunta']}")
    linhas += ["", "Ou digite *MENU* para voltar."]
    return "\n".join(linhas)


def buscar_por_texto(texto):
    """
    Procura a dúvida cujas palavras-chave aparecem na frase do cliente.
    Se várias combinarem, fica com a que tiver mais palavras encontradas.
    Devolve a resposta (texto) ou None.
    """
    frase = f" {normalizar(texto)} "
    melhor, melhor_pontos = None, 0
    for d in DUVIDAS:
        pontos = sum(1 for p in d["palavras"] if f" {normalizar(p)} " in frase)
        if pontos > melhor_pontos:
            melhor, melhor_pontos = d, pontos
    return melhor["resposta"] if melhor else None


def resposta_por_numero(numero):
    if 1 <= numero <= len(DUVIDAS):
        return DUVIDAS[numero - 1]["resposta"]
    return None