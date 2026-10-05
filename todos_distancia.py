"""
Encontra a cidade que o cliente digitou e calcula a distância.

Como funciona:
  1. Temos um arquivo com as 5.570 cidades do Brasil e a latitude/longitude
     de cada uma (dados/municipios.csv).
  2. O cliente digita algo como "goiania - go", "Goiânia/GO" ou só "goiania".
     A gente "normaliza" o texto (tira acento, deixa maiúsculo) e procura.
  3. Com as coordenadas das duas cidades, calculamos a distância em linha
     reta (fórmula de Haversine) e multiplicamos por 1,28 para estimar
     a distância pela estrada. Esse 1,28 foi medido nas viagens da Deflo.

Funções principais:
  resolver_cidade(texto)        -> quando o cliente responde SÓ com uma cidade (trata nomes repetidos e sugere nomes parecidos)
  achar_cidade_no_texto(texto)  -> acha uma cidade no meio de uma frase ("quero cotar de rio de janeiro rj")
  distancia_km(origem, destino) -> distância aproximada pela estrada
"""
import csv
import difflib
import math
import re
import unicodedata

import todos_config as config


def normalizar(texto):
    """'Goiânia/GO?' -> 'GOIANIA GO'  (sem acento, maiúsculo, sem pontuação)."""
    sem_acento = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode()
    so_letras = re.sub(r"[^A-Z0-9 ]", " ", sem_acento.upper())   # troca pontuação por espaço
    return " ".join(so_letras.split())                           # tira espaços repetidos


def _carregar_cidades():
    """Monta um dicionário: nome normalizado -> lista de cidades com esse nome."""
    siglas = {}
    with open(config.ARQ_ESTADOS, encoding="utf-8-sig") as f:
        for linha in csv.DictReader(f):
            siglas[linha["codigo_uf"]] = linha["uf"]

    cidades = {}
    with open(config.ARQ_MUNICIPIOS, encoding="utf-8-sig") as f:
        for linha in csv.DictReader(f):
            cidade = {
                "nome": linha["nome"],
                "uf": siglas[linha["codigo_uf"]],
                "lat": float(linha["latitude"]),
                "lon": float(linha["longitude"]),
            }
            # Várias cidades têm o mesmo nome (ex.: "Bom Jesus" existe em 5 estados)
            cidades.setdefault(normalizar(linha["nome"]), []).append(cidade)
    return cidades, set(siglas.values())


CIDADES, UFS = _carregar_cidades()


def resolver_cidade(texto):
    """
    Tenta descobrir qual cidade o cliente quis dizer.
    Devolve uma tupla (situacao, resultado):
      ("ok", cidade)              -> achou exatamente uma
      ("ambigua", [cidades])      -> existe em mais de um estado; precisa perguntar
      ("nao_encontrada", [nomes]) -> não achou; devolve sugestões parecidas
    """
    partes = normalizar(texto).split()
    if not partes:
        return "nao_encontrada", []

    # Se a última palavra for uma sigla de estado (GO, SP...), separamos ela.
    uf = None
    if len(partes) > 1 and partes[-1] in UFS:
        uf = partes[-1]
        partes = partes[:-1]
    nome = " ".join(partes)

    candidatas = CIDADES.get(nome, [])
    if uf:
        candidatas = [c for c in candidatas if c["uf"] == uf]

    if len(candidatas) == 1:
        return "ok", candidatas[0]
    if len(candidatas) > 1:
        return "ambigua", candidatas

    # Não achou: procura nomes parecidos (erros de digitação)
    parecidos = difflib.get_close_matches(nome, CIDADES.keys(), n=3, cutoff=0.8)
    sugestoes = []
    for p in parecidos:
        for c in CIDADES[p]:
            if uf is None or c["uf"] == uf:
                sugestoes.append(f'{c["nome"]} - {c["uf"]}')
    return "nao_encontrada", sugestoes[:3]


def achar_cidade_no_texto(texto):
    """
    Procura UMA cidade dentro de uma frase maior, sem sugestões.
    Ex.: 'quero cotar de rio de janeiro rj'  ->  Rio de Janeiro - RJ

    Como funciona: testa pedaços da frase, começando pelos mais à esquerda
    e mais longos, até achar um pedaço que seja exatamente uma cidade.
    Devolve a cidade, ou None se não achar (ou se o nome existir em vários
    estados e o cliente não disse qual).
    """
    palavras = normalizar(texto).split()
    for inicio in range(len(palavras)):
        for fim in range(len(palavras), inicio, -1):
            pedaco = palavras[inicio:fim]
            uf = None
            if len(pedaco) > 1 and pedaco[-1] in UFS:
                uf, pedaco = pedaco[-1], pedaco[:-1]
            candidatas = CIDADES.get(" ".join(pedaco), [])
            if uf:
                candidatas = [c for c in candidatas if c["uf"] == uf]
            if len(candidatas) == 1:
                return candidatas[0]
    return None


def distancia_km(origem, destino):
    """Distância aproximada pela estrada, em km (Haversine × fator da estrada)."""
    raio_terra = 6371  # km
    lat1, lon1 = math.radians(origem["lat"]), math.radians(origem["lon"])
    lat2, lon2 = math.radians(destino["lat"]), math.radians(destino["lon"])
    a = (math.sin((lat2 - lat1) / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2)
    linha_reta = 2 * raio_terra * math.asin(math.sqrt(a))
    return round(linha_reta * config.FATOR_ESTRADA)


def nome_completo(cidade):
    return f'{cidade["nome"]} - {cidade["uf"]}'


if __name__ == "__main__":
    # Teste rápido: python todos_distancia.py
    _, goiania = resolver_cidade("goiania go")
    _, palmas = resolver_cidade("Palmas - TO")
    print(nome_completo(goiania), "->", nome_completo(palmas), distancia_km(goiania, palmas), "km")
    print(resolver_cidade("goiaina"))
