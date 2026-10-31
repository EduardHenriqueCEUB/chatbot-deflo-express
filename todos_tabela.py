"""
Lê a tabela de preços do frete fracionado e calcula o valor.

A tabela fica na pasta de dados do Google Drive (arquivo TabelaCotacao.xlsx,
aba "TabelaCotação"), neste formato:

    Peso \\ Distância (km) | 0-100 | 100-200 | 200-300 | ...
    0-10kg                 |  295  |   310   |   335   | ...
    10-20kg                |  335  |   355   |   370   | ...

Para achar o preço:
  1. descobrimos em qual LINHA o peso se encaixa (faixa de peso);
  2. descobrimos em qual COLUNA a distância se encaixa (faixa de km);
  3. o preço é o valor da célula no cruzamento.

Brasil inteiro, sem limite de distância:
  A tabela vai até 6.000 km (a rota mais longa do Brasil tem cerca de 5.800 km).
  As colunas de 3.200 a 6.000 km (em laranja na planilha) são preços estimados:
  cada faixa de peso continua subindo no mesmo ritmo do fim da tabela.
  Se um dia aparecer uma distância maior que a última coluna, o bot faz a
  mesma conta sozinho (veja _preco_alem_da_tabela), e o cliente sempre recebe
  a cotação.

Atenção: o peso usado aqui é o PESO CONSIDERADO, ou seja, o maior entre
o peso real e o peso cubado (quem calcula isso é o todos_conversa.py).

Atualização automática: a cada TABELA_ATUALIZAR_MIN minutos (todos_config.py),
o bot busca a tabela de novo no Drive. Se o dono mudar os preços lá, o bot
passa a usar os preços novos sozinho, sem mexer no código. Se o Drive falhar
nessa hora, o bot continua com a tabela que já tinha.
"""
import io
import math
import re
import time

import openpyxl

import todos_config as config
import todos_drive as drive


def _limite_superior(rotulo):
    """
    Recebe o texto de uma faixa, como '100-150kg' ou '401–450 kg',
    e devolve o maior número dela (150, 450).
    Usamos expressão regular (re) para pegar todos os números do texto.
    """
    numeros = re.findall(r"\d+", str(rotulo))
    return float(numeros[-1]) if numeros else None


def carregar_tabela(conteudo, aba=config.ABA_TABELA):
    """
    Lê a aba 'TabelaCotação' do Excel e devolve um dicionário com as faixas e os preços.
    conteudo: o arquivo .xlsx em bytes (baixado do Drive).
    """
    arquivo = openpyxl.load_workbook(io.BytesIO(conteudo), data_only=True)
    if aba not in arquivo.sheetnames:
        raise ValueError(f"A aba '{aba}' não foi encontrada em {config.NOME_TABELA}. "
                         f"Abas existentes: {arquivo.sheetnames}")
    planilha = arquivo[aba]

    # Linhas: as que têm uma faixa de peso na coluna A (ex.: "0-10kg").
    # Um texto sem número na coluna A é ignorado.
    linhas = [l for l in range(2, planilha.max_row + 1)
              if _limite_superior(planilha.cell(l, 1).value) is not None]
    # Colunas: as que têm uma faixa de km no título e preço na primeira linha de peso.
    # A legenda que fica embaixo da tabela não entra, porque não está numa linha de peso.
    colunas = [c for c in range(2, planilha.max_column + 1)
               if _limite_superior(planilha.cell(1, c).value) is not None
               and planilha.cell(linhas[0], c).value is not None]

    limites_km = [_limite_superior(planilha.cell(1, c).value) for c in colunas]
    limites_kg = [_limite_superior(planilha.cell(l, 1).value) for l in linhas]
    precos = [[planilha.cell(l, c).value for c in colunas] for l in linhas]

    # Conferência: toda célula da tabela precisa ter um número.
    # Se o dono apagar um preço sem querer, o bot avisa no log e segue com a tabela anterior,
    # em vez de passar um valor errado para o cliente.
    for i, l in enumerate(linhas):
        for j, c in enumerate(colunas):
            if not isinstance(precos[i][j], (int, float)):
                celula = planilha.cell(l, c).coordinate
                raise ValueError(f"A célula {celula} da tabela de preços está vazia ou não é um número.")

    return {"limites_km": limites_km, "limites_kg": limites_kg, "precos": precos}


def _baixar_tabela():
    return carregar_tabela(drive.baixar_arquivo(config.NOME_TABELA))


# A tabela é baixada do Drive quando o programa inicia...
TABELA = _baixar_tabela()
_ultima_atualizacao = time.monotonic()


def _atualizar_se_preciso():
    """...e baixada de novo a cada TABELA_ATUALIZAR_MIN minutos."""
    global TABELA, _ultima_atualizacao
    if time.monotonic() - _ultima_atualizacao < config.TABELA_ATUALIZAR_MIN * 60:
        return
    _ultima_atualizacao = time.monotonic()      # mesmo se falhar, só tenta de novo no próximo intervalo
    try:
        TABELA = _baixar_tabela()
    except Exception as erro:                   # Drive fora do ar: segue com a tabela antiga
        print(f"[TABELA] Não consegui atualizar a tabela do Drive ({erro}). Usando a anterior.")


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


def _preco_alem_da_tabela(precos_da_linha, limites_km, distancia_km):
    """
    Distância maior que a última coluna: continua subindo no mesmo ritmo do fim da tabela.
    Ex.: últimas colunas 1845 e 1870 (sobe 25 a cada 100 km), última faixa até 6000 km.
         6150 km está 2 faixas além (6000-6100 e 6100-6200) -> 1870 + 2 x 25 = 1920
    """
    aumento = precos_da_linha[-1] - precos_da_linha[-2]        # quanto sobe a cada faixa
    largura = limites_km[-1] - limites_km[-2]                  # tamanho de cada faixa (100 km)
    faixas_a_mais = math.ceil((distancia_km - limites_km[-1]) / largura)
    return precos_da_linha[-1] + aumento * faixas_a_mais


def calcular_preco(peso_kg, distancia_km):
    """
    peso_kg: peso considerado (maior entre o real e o cubado).
    Devolve o valor do frete em reais, para qualquer distância.
    O peso acima da tabela não chega aqui: o todos_conversa.py manda essa carga
    (carga volumosa) direto para o atendente.
    """
    _atualizar_se_preciso()
    linha = _indice_da_faixa(peso_kg, TABELA["limites_kg"])
    if linha is None:
        raise ValueError(f"Peso de {peso_kg} kg acima da tabela (deveria ter ido para o atendente).")
    precos_da_linha = TABELA["precos"][linha]
    coluna = _indice_da_faixa(distancia_km, TABELA["limites_km"])
    if coluna is None:
        preco = _preco_alem_da_tabela(precos_da_linha, TABELA["limites_km"], distancia_km)
    else:
        preco = precos_da_linha[coluna]
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
    print("30 kg, 5700 km ->", formatar_reais(calcular_preco(30, 5700)))
    print("30 kg, 6150 km (além da tabela) ->", formatar_reais(calcular_preco(30, 6150)))