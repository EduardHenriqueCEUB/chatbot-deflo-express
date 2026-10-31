"""
Ligação do bot com a pasta de dados no Google Drive.

Por que os dados ficam no Drive e não no GitHub?
  O GitHub guarda só o CÓDIGO. A tabela de preços é informação comercial
  da empresa e o registro de cotações tem telefones de clientes (LGPD).
  Por isso, os dados ficam numa pasta privada do Google Drive
  ("Chatbot Deflo - Dados"), e o bot busca de lá.

Como o bot entra no Drive?
  Usando uma "conta de serviço" (a conta robô bot-deflo@...gserviceaccount.com).
  Ela é como um crachá: só enxerga a pasta que foi compartilhada com ela,
  e só faz o que foi permitido (ler a pasta e escrever nas planilhas de registro).
  A chave dessa conta é um arquivo .json, tratado como senha:
    - no teste: fica numa pasta segura do computador, e o .env diz onde;
    - na produção: fica em "Secret Files" no painel do Render.

O que tem na pasta do Drive:
  TabelaCotacao.xlsx      -> tabela de preços (o bot só LÊ)
  municipios.csv          -> cidades do Brasil com coordenadas (só LÊ)
  estados.csv             -> estados e siglas (só LÊ)
  cotacoes_registradas    -> planilha Google onde o bot ACRESCENTA uma linha por cotação
  emails_registrados      -> planilha Google onde o bot ACRESCENTA uma linha por e-mail recebido
  base_conhecimento       -> planilha Google onde o bot ANOTA o que não soube responder

Funções principais:
  baixar_arquivo(nome)                      -> devolve o conteúdo de um arquivo da pasta (bytes)
  acrescentar_linha(nome, valores)          -> escreve uma linha nova no fim de uma planilha Google
                                               e devolve o número da linha onde ela ficou
  atualizar_celulas(nome, celulas)          -> troca o valor de algumas células (ex.: C5 e P5)
  ler_planilha(nome)                        -> devolve todas as linhas de uma planilha Google
  link_da_planilha(nome)                    -> endereço para abrir a planilha no navegador
"""
import re

import todos_config as config

# Permissões que o bot pede ao Google (o mínimo necessário):
#   drive.readonly -> ler arquivos que foram compartilhados com a conta robô
#   spreadsheets   -> escrever nas planilhas que foram compartilhadas como Editor
PERMISSOES = [
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/spreadsheets",
]

URL_DRIVE = "https://www.googleapis.com/drive/v3/files"
URL_PLANILHAS = "https://sheets.googleapis.com/v4/spreadsheets"
TEMPO_LIMITE = 30   # segundos esperando o Google responder

_sessao = None      # conexão com o Google, criada uma vez só
_ids = {}           # guarda o ID de cada arquivo já encontrado (para não procurar de novo)


def _conectar():
    """Faz o login da conta robô no Google (uma vez só) e devolve a conexão."""
    global _sessao
    if _sessao is not None:
        return _sessao

    if not config.GOOGLE_CREDENCIAIS_ARQUIVO or not config.DRIVE_PASTA_ID:
        raise RuntimeError("Faltam GOOGLE_CREDENCIAIS_ARQUIVO e/ou DRIVE_PASTA_ID "
                           "(no .env, para o teste, ou no Render, para a produção).")

    # A biblioteca do Google só é carregada aqui, na hora de conectar.
    from google.auth.transport.requests import AuthorizedSession
    from google.oauth2 import service_account

    credenciais = service_account.Credentials.from_service_account_file(
        config.GOOGLE_CREDENCIAIS_ARQUIVO, scopes=PERMISSOES)
    _sessao = AuthorizedSession(credenciais)
    return _sessao


def _id_do_arquivo(nome):
    """Procura o arquivo pelo NOME dentro da pasta de dados e devolve o ID dele."""
    if nome in _ids:
        return _ids[nome]

    busca = f"'{config.DRIVE_PASTA_ID}' in parents and name = '{nome}' and trashed = false"
    resposta = _conectar().get(URL_DRIVE, params={"q": busca, "fields": "files(id, name)"},
                               timeout=TEMPO_LIMITE)
    resposta.raise_for_status()
    arquivos = resposta.json().get("files", [])
    if not arquivos:
        raise FileNotFoundError(f"'{nome}' não foi encontrado na pasta de dados do Drive. "
                                "Confira o nome do arquivo e se a pasta foi compartilhada "
                                "com a conta robô.")
    _ids[nome] = arquivos[0]["id"]
    return _ids[nome]


def baixar_arquivo(nome):
    """Devolve o conteúdo de um arquivo da pasta de dados (em bytes)."""
    resposta = _conectar().get(f"{URL_DRIVE}/{_id_do_arquivo(nome)}",
                               params={"alt": "media"}, timeout=TEMPO_LIMITE)
    resposta.raise_for_status()
    return resposta.content


def acrescentar_linha(nome_planilha, valores):
    """
    Escreve UMA linha nova no fim da planilha Google (primeira aba).
    valores: lista com o valor de cada coluna, na ordem das colunas.
    Devolve o número da linha onde ela ficou (ex.: 5), para o bot poder
    voltar nela depois (quando a conversa vai para um atendente).
    O bot nunca apaga linhas.
    """
    id_planilha = _id_do_arquivo(nome_planilha)
    resposta = _conectar().post(
        f"{URL_PLANILHAS}/{id_planilha}/values/A1:append",
        params={"valueInputOption": "RAW", "insertDataOption": "INSERT_ROWS"},
        json={"values": [valores]},
        timeout=TEMPO_LIMITE,
    )
    resposta.raise_for_status()
    # O Google responde onde gravou, ex.: "Página1!A5:P5" -> linha 5
    intervalo = resposta.json()["updates"]["updatedRange"]
    return int(re.search(r"![A-Z]+(\d+)", intervalo).group(1))


def atualizar_celulas(nome_planilha, celulas):
    """
    Troca o valor de algumas células da planilha (primeira aba), tudo de uma vez.
    celulas: dicionário {célula: valor}
    Ex.: atualizar_celulas("cotacoes_registradas", {"C5": "ATD-...", "O5": "atendimento"})
    """
    id_planilha = _id_do_arquivo(nome_planilha)
    resposta = _conectar().post(
        f"{URL_PLANILHAS}/{id_planilha}/values:batchUpdate",
        json={"valueInputOption": "RAW",
              "data": [{"range": celula, "values": [[valor]]} for celula, valor in celulas.items()]},
        timeout=TEMPO_LIMITE,
    )
    resposta.raise_for_status()


def link_da_planilha(nome_planilha):
    """Devolve o endereço para abrir a planilha no navegador."""
    return f"https://docs.google.com/spreadsheets/d/{_id_do_arquivo(nome_planilha)}"


def ler_planilha(nome_planilha):
    """
    Devolve todas as linhas da planilha Google (primeira aba), como uma lista de listas.
    Ex.: [["data_hora", "email", ...], ["2026-10-25 09:14", "fulano@empresa.com", ...]]
    """
    id_planilha = _id_do_arquivo(nome_planilha)
    resposta = _conectar().get(f"{URL_PLANILHAS}/{id_planilha}/values/A:Z", timeout=TEMPO_LIMITE)
    resposta.raise_for_status()
    return resposta.json().get("values", [])


if __name__ == "__main__":
    # Teste rápido da ligação com o Drive: python todos_drive.py
    for arquivo in (config.NOME_TABELA, config.NOME_MUNICIPIOS, config.NOME_ESTADOS):
        print(f"{arquivo}: {len(baixar_arquivo(arquivo)):,} bytes baixados".replace(",", "."))
    for planilha in (config.NOME_PLANILHA_REGISTRO, config.NOME_PLANILHA_EMAILS,
                     config.NOME_PLANILHA_CONHECIMENTO):
        print(f"{planilha}: encontrada (ID {_id_do_arquivo(planilha)[:6]}...)")
    print("Ligação com o Google Drive funcionando.")