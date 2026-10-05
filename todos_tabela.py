"""
Lê a tabela de preços do frete fracionado e calcula o valor.

A tabela fica no arquivo dados/TabelaCotacao.xlsx, na aba "TabelaCotação",
neste formato:

    Peso \\ Distância (km) | 0-100 | 100-200 | 200-300 | ...
    0-10kg                 |  295  |   310   |   335   | ...
    10-20kg                |  335  |   355   |   370   | ...

Para achar o preço:
  1. descobrimos em qual LINHA o peso se encaixa (faixa de peso);
  2. descobrimos em qual COLUNA a distância se encaixa (faixa de km);
  3. o preço é o valor da célula no cruzamento.

Atenção: o peso usado aqui é o PESO CONSIDERADO, ou seja, o maior entre
o peso real e o peso cubado (quem calcula isso é o todos_conversa.py).
"""
import re
import openpyxl

import todos_config as config


def _limite_superior(rotulo):
    """
    Recebe o texto de uma faixa, como '100-150kg' ou '401–450 kg',
    e devolve o maior número dela (150, 450).
    Usamos expressão regular (re) para pegar todos os números do texto.
    """
    numeros = re.findall(r"\d+", str(rotulo))
    return float(numeros[-1]) if numeros else None


def carregar_tabela(caminho=config.ARQ_TABELA, aba=config.ABA_TABELA):
    """Lê a aba 'TabelaCotação' do Excel e devolve um dicionário com as faixas e os preços."""
    arquivo = openpyxl.load_workbook(caminho, data_only=True)
    if aba not in arquivo.sheetnames:
        raise ValueError(f"A aba '{aba}' não foi encontrada em {caminho.name}. "
                         f"Abas existentes: {arquivo.sheetnames}")
    planilha = arquivo[aba]

    # Colunas: só usamos as que têm preço preenchido (linha 2).
    colunas = [c for c in range(2, planilha.max_column + 1)
               if planilha.cell(2, c).value is not None]
    # Linhas: todas que têm um rótulo de peso na coluna A.
    linhas = [l for l in range(2, planilha.max_row + 1)
              if planilha.cell(l, 1).value is not None]

    limites_km = [_limite_superior(planilha.cell(1, c).value) for c in colunas]
    limites_kg = [_limite_superior(planilha.cell(l, 1).value) for l in linhas]
    precos = [[planilha.cell(l, c).value for c in colunas] for l in linhas]

    return {"limites_km": limites_km, "limites_kg": limites_kg, "precos": precos}


# Carregamos a tabela UMA vez, quando o programa inicia.
TABELA = carregar_tabela()
DISTANCIA_MAXIMA_KM = TABELA["limites_km"][-1]


def _indice_da_faixa(valor, limites):
    """
    Devolve a posição da primeira faixa cujo limite é >= valor.
    Ex.: limites [100, 200, 300] e valor 150 -> posição 1 (faixa 100-200).
    Se o valor passar de todas as faixas, devolve None.
    """
    for posicao, limite in enumerate(limites):
        if valor <= limite:
            return posicao
    return None


def calcular_preco(peso_kg, distancia_km):
    """
    peso_kg: peso considerado (maior entre o real e o cubado).
    Devolve o valor do frete em reais, ou None se a combinação
    estiver fora da tabela (ex.: distância maior que a última faixa).
    """
    linha = _indice_da_faixa(peso_kg, TABELA["limites_kg"])
    coluna = _indice_da_faixa(distancia_km, TABELA["limites_km"])
    if linha is None or coluna is None:
        return None
    preco = TABELA["precos"][linha][coluna]
    if preco is None:
        return None
    return round(float(preco) * config.FATOR_AJUSTE_PRECO, 2)


def formatar_reais(valor):
    """1450.5 -> 'R$ 1.450,50' (padrão brasileiro)."""
    texto = f"{valor:,.2f}"                     # '1,450.50' (padrão americano)
    texto = texto.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {texto}"


if __name__ == "__main__":
    # Teste rápido: python todos_tabela.py
    print("Faixas de km:", TABELA["limites_km"])
    print("Faixas de kg:", TABELA["limites_kg"])
    print("30 kg, 933 km ->", formatar_reais(calcular_preco(30, 933)))
