"""
Guarda cada cotação feita pelo bot em um arquivo CSV (dados/cotacoes_registradas.csv).

Por quê? Com o tempo, esse arquivo vira uma base de dados valiosa:
quantas cotações foram feitas, para quais rotas, quantas viraram
negociação e com que frequência as cargas são volumosas.

Colunas:
  data_hora, protocolo, telefone, origem, destino, distancia_km,
  peso_kg             -> peso real informado pelo cliente
  medidas             -> ex.: "3 volumes de 50x40x30 cm" (vazio se o cliente pulou)
  peso_cubado_kg      -> calculado a partir das medidas (vazio se o cliente pulou)
  peso_considerado_kg -> o maior entre o peso real e o cubado (é o usado no preço)
  valor               -> valor da tabela (vazio quando não foi possível cotar)
  protocolo           -> número do atendimento (ex.: ATD-04102026-1432-K7), quando o cliente
                         foi passado para um atendente; vazio numa cotação comum
  evento              -> o que aconteceu:
        cotacao          = cotação mostrada ao cliente
        pediu_negociacao = cliente pediu para negociar com o atendente
        carga_volumosa   = peso considerado acima do limite -> foi para o atendente
        fora_da_tabela   = rota mais longa que a tabela -> foi para o atendente

Atenção (LGPD): o telefone do cliente é dado pessoal. Guarde o arquivo
em local seguro e não compartilhe.
"""
import csv

import todos_config as config

COLUNAS = ["data_hora", "protocolo", "telefone", "origem", "destino", "distancia_km",
           "peso_kg", "medidas", "peso_cubado_kg", "peso_considerado_kg", "valor", "evento"]


def _guardar_arquivo_antigo():
    """
    Se o CSV foi criado por uma versão antiga do bot (com outras colunas),
    renomeia para cotacoes_registradas_antigo.csv e deixa o bot começar um novo.
    Assim as colunas nunca ficam desalinhadas e nada se perde.
    """
    arquivo = config.ARQ_REGISTRO
    if not arquivo.exists():
        return
    with open(arquivo, encoding="utf-8") as f:
        cabecalho = f.readline().strip().split(",")
    if cabecalho == COLUNAS:
        return
    destino = arquivo.with_name(arquivo.stem + "_antigo.csv")
    numero = 2
    while destino.exists():
        destino = arquivo.with_name(f"{arquivo.stem}_antigo{numero}.csv")
        numero += 1
    arquivo.rename(destino)


def registrar(dados):
    """Adiciona uma linha ao CSV (cria o arquivo com cabeçalho se ainda não existir)."""
    _guardar_arquivo_antigo()
    novo = not config.ARQ_REGISTRO.exists()
    with open(config.ARQ_REGISTRO, "a", newline="", encoding="utf-8") as f:
        escritor = csv.DictWriter(f, fieldnames=COLUNAS, extrasaction="ignore")
        if novo:
            escritor.writeheader()
        escritor.writerow(dados)