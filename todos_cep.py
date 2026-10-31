"""
CEP: reconhece o CEP na mensagem do cliente e descobre a cidade.

Por que isso existe:
  Nas conversas reais da empresa, muito cliente pede cotação pelo CEP, e não
  pelo nome da cidade. Um pedido de verdade, lido do CRM, chega assim:

      4) CEP de origem 74486-225
      5) CEP de destino 39948-000

  Sem entender CEP, o bot ficava pedindo "qual a cidade de origem?" para alguém
  que já tinha dito de onde a carga sai. Isso irrita e faz o cliente desistir.

Como funciona:
  1. O bot acha os CEPs na mensagem (veja achar_no_texto).
  2. Para cada um, descobre a cidade consultando o ViaCEP, que é um serviço
     público e gratuito, sem cadastro e sem chave.
  3. Com a cidade na mão, o resto da cotação segue igual: o bot calcula a
     distância e o preço do mesmo jeito.

Quando a consulta não funciona:
  Se a internet falhar, se o ViaCEP estiver fora do ar ou se o CEP não existir,
  o bot NÃO trava e NÃO inventa cidade: ele volta a pedir a cidade por extenso.
  O cliente nunca fica preso por causa de um serviço de terceiro.

Por que aqui pode consultar um serviço externo, e no CNPJ não:
  É a diferença entre uma consulta que AJUDA e uma que BARRA. No CNPJ, depender
  de uma base externa significaria recusar uma empresa recém-aberta que ainda
  não apareceu na base. Aqui, no pior caso o bot só pede a cidade escrita, que
  é exatamente o que ele já fazia antes.

Cache:
  A resposta de cada CEP fica guardada na memória enquanto o bot roda. Cliente
  que repete a mesma rota não gera consulta nova, e o bot responde na hora.

Funções:
  limpar(texto)         -> deixa só os 8 dígitos: '74486-225' -> '74486225'
  valido(texto)         -> True se são 8 dígitos e não são todos iguais
  formatar(cep)         -> '74486225' -> '74486-225'
  parece_cep(texto)     -> True se a mensagem inteira é um CEP
  achar_no_texto(texto) -> lista dos CEPs achados, na ordem em que aparecem
  achar_com_rotulo(texto) -> ({'origem': '74486-225'}, ['39948-000'])
  remover_do_texto(texto) -> a frase sem os CEPs
  cidade(cep)           -> {'nome': 'Goiânia', 'uf': 'GO'} ou None
"""
import re

import requests

TAMANHO = 8
ENDERECO_VIACEP = "https://viacep.com.br/ws/{cep}/json/"
SEGUNDOS_DE_ESPERA = 6          # o cliente está esperando no WhatsApp: não dá para demorar

# O que já foi consultado nesta execução: {'74486225': {'nome': ..., 'uf': ...}}
# O None também é guardado, para o bot não bater no ViaCEP de novo por um CEP que não existe.
_cache = {}

# Um CEP escrito com hífen (74486-225) ou oito dígitos seguidos (74486225).
# O \b nas pontas impede pegar um pedaço de número maior: num CNPJ de 14 dígitos
# não existe oito dígitos com fronteira de palavra dos dois lados.
REGEX_CEP = re.compile(r"\b(\d{5})-(\d{3})\b|\b(\d{8})\b")

# A palavra CEP antes do número. Serve para aceitar os oito dígitos sem hífen
# só quando o cliente disse que aquilo é um CEP.
REGEX_COM_PALAVRA = re.compile(r"\bcep\b[^0-9]{0,30}(\d{5}-?\d{3})\b", re.IGNORECASE)

# "CEP de origem 74486-225", "CEP de destino 39948-000", "coleta no cep ...".
PALAVRAS_DE_ORIGEM = ("origem", "coleta", "remetente", "sai de", "saida", "partida")
PALAVRAS_DE_DESTINO = ("destino", "entrega", "destinatario", "chega", "chegada")


def limpar(texto):
    """Deixa só os números. '74.486-225' -> '74486225'"""
    return re.sub(r"\D", "", str(texto))


def valido(texto):
    """
    True quando são 8 dígitos e não são todos iguais.
    Isso não garante que o CEP existe: quem diz isso é a consulta.
      '74486-225'  -> True
      '74486225'   -> True
      '00000000'   -> False
      '123'        -> False
    """
    limpo = limpar(texto)
    return len(limpo) == TAMANHO and limpo != limpo[0] * TAMANHO


def formatar(texto):
    """'74486225' -> '74486-225'. Devolve o texto original se não der."""
    limpo = limpar(texto)
    if len(limpo) != TAMANHO:
        return str(texto).strip()
    return f"{limpo[:5]}-{limpo[5:]}"


def parece_cep(texto):
    """True quando a mensagem INTEIRA é um CEP ('74486-225', 'cep 74486225')."""
    sem_palavra = re.sub(r"\bcep\b", " ", str(texto), flags=re.IGNORECASE)
    return valido(sem_palavra) and len(limpar(sem_palavra)) == TAMANHO


def achar_no_texto(texto):
    """
    Devolve os CEPs achados na mensagem, já formatados e sem repetir, na ordem
    em que aparecem.

    Oito dígitos seguidos só contam quando a palavra CEP aparece antes deles.
    Sem essa exigência, qualquer número comprido na mensagem viraria CEP.
    """
    texto = str(texto)
    achados = []

    def guardar(bruto):
        if valido(bruto):
            bonito = formatar(bruto)
            if bonito not in achados:
                achados.append(bonito)

    for achado in REGEX_CEP.finditer(texto):
        com_hifen = achado.group(1) and achado.group(2)
        if com_hifen:
            guardar(achado.group(1) + achado.group(2))
    for achado in REGEX_COM_PALAVRA.finditer(texto):
        guardar(achado.group(1))

    # Mantém a ordem em que aparecem no texto, e não a ordem em que foram achados
    achados.sort(key=lambda cep: texto.find(cep[:5]))
    return achados


def _rotulo_do_trecho(trecho):
    """Olha o pedaço de texto ANTES do CEP e diz se ele fala de origem ou destino."""
    trecho = trecho.lower()
    posicao_origem = max((trecho.rfind(p) for p in PALAVRAS_DE_ORIGEM), default=-1)
    posicao_destino = max((trecho.rfind(p) for p in PALAVRAS_DE_DESTINO), default=-1)
    if posicao_origem == posicao_destino == -1:
        return None
    return "origem" if posicao_origem > posicao_destino else "destino"


def achar_com_rotulo(texto):
    """
    Separa os CEPs em dois grupos. Devolve (rotulados, sem_rotulo):

      'CEP de origem 74486-225 ... CEP de destino 39948-000'
          -> ({'origem': '74486-225', 'destino': '39948-000'}, [])
      'de 74486-225 para 39948-000'
          -> ({}, ['74486-225', '39948-000'])

    O bot procura a palavra (origem, coleta, destino, entrega) logo antes de
    cada CEP. O que não tem palavra volta na segunda lista, SEM palpite, porque
    quem decide onde ele encaixa é o todos_conversa.py: lá se sabe se a cidade
    de origem ou a de destino já foi informada por extenso. Chutar aqui faria o
    CEP de "de Goiânia para o cep 39948-000" virar origem, que é o oposto.
    """
    texto = str(texto)
    encontrados = achar_no_texto(texto)
    if not encontrados:
        return {}, []

    rotulados = {}
    sem_rotulo = []
    for achado in encontrados:
        posicao = texto.find(achado[:5])
        rotulo = _rotulo_do_trecho(texto[max(0, posicao - 60):posicao])
        if rotulo and rotulo not in rotulados:
            rotulados[rotulo] = achado
        else:
            sem_rotulo.append(achado)
    return rotulados, sem_rotulo


def remover_do_texto(texto):
    """
    Tira os CEPs da frase. Serve para o resto do código não confundir os números
    do CEP com outra coisa: sem isso, o "000" de um CEP terminado em -000 podia
    virar a quantidade de volumes da carga.
    """
    limpo = REGEX_COM_PALAVRA.sub(" ", str(texto))
    return re.sub(r"\b\d{5}-\d{3}\b", " ", limpo)


def cidade(cep, _consulta=None):
    """
    Descobre a cidade do CEP. Devolve {'nome': 'Goiânia', 'uf': 'GO'} ou None.

    None quer dizer "não consegui": CEP inexistente, serviço fora do ar ou sem
    internet. Quem chama trata os três do mesmo jeito, pedindo a cidade escrita.

    O _consulta existe só para o teste automático poder rodar sem internet.
    """
    limpo = limpar(cep)
    if not valido(limpo):
        return None
    if limpo in _cache:
        return _cache[limpo]

    resposta = None
    try:
        buscar = _consulta or _consultar_viacep
        dados = buscar(limpo)
        if dados and not dados.get("erro") and dados.get("localidade") and dados.get("uf"):
            resposta = {"nome": dados["localidade"], "uf": dados["uf"].upper()}
    except Exception as erro:
        print(f"[CEP] não consegui consultar o CEP {limpo} ({erro})")
        return None            # falha de rede não vira cache: na próxima tenta de novo

    _cache[limpo] = resposta
    return resposta


def _consultar_viacep(cep):
    """Consulta de verdade. Separada para o teste poder trocar por uma de mentira."""
    resposta = requests.get(ENDERECO_VIACEP.format(cep=cep), timeout=SEGUNDOS_DE_ESPERA)
    resposta.raise_for_status()
    return resposta.json()


def limpar_cache():
    """Esquece o que já foi consultado. Usado pelo teste automático."""
    _cache.clear()


if __name__ == "__main__":
    # Teste rápido: python todos_cep.py   (este precisa de internet)
    exemplos = ["74486-225", "39948000", "cep 01001000", "00000000", "123"]
    for exemplo in exemplos:
        if valido(exemplo):
            achada = cidade(exemplo)
            print(f"{exemplo:14} -> {formatar(exemplo)} -> "
                  + (f"{achada['nome']} - {achada['uf']}" if achada else "não encontrei"))
        else:
            print(f"{exemplo:14} -> não é um CEP")