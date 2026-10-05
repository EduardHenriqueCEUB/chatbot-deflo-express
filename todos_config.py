"""
Todas as configurações do chatbot em um só lugar.

Por que um arquivo só para isso? Se amanhã o horário mudar, ou o peso
máximo mudar, você altera AQUI e o resto do código continua igual.

Senhas e tokens NÃO ficam escritos no código: eles são lidos do arquivo
.env (veja o .env_exemplo). Assim você pode mostrar o código para o
professor sem expor as chaves da empresa.
"""
import os
from pathlib import Path

# Tenta carregar o arquivo .env (se a biblioteca python-dotenv estiver instalada)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ---------------------------------------------------------------
# Arquivos
# ---------------------------------------------------------------
PASTA = Path(__file__).parent
ARQ_TABELA = PASTA / "dados" / "TabelaCotacao.xlsx"       # tabela de preços (peso x distância)
ABA_TABELA = "TabelaCotação"                              # nome da aba dentro do Excel
ARQ_MUNICIPIOS = PASTA / "dados" / "municipios.csv"       # cidades do Brasil com latitude/longitude
ARQ_ESTADOS = PASTA / "dados" / "estados.csv"
ARQ_REGISTRO = PASTA / "dados" / "cotacoes_registradas.csv"  # histórico das cotações feitas pelo bot

# ---------------------------------------------------------------
# Empresa
# ---------------------------------------------------------------
NOME_EMPRESA = "Deflo Express"
FUSO = "America/Sao_Paulo"      # horário de Brasília
HORA_ABRE = 8                   # abre às 8h
HORA_FECHA = 20                 # fecha às 20h
# Dias de funcionamento: 0 = segunda ... 6 = domingo.
# ⚠️ CONFIRMAR com a empresa. Por enquanto: todos os dias.
DIAS_FUNCIONAMENTO = {0, 1, 2, 3, 4, 5, 6}

# ---------------------------------------------------------------
# Atendimento humano
# ---------------------------------------------------------------
# Todo chamado de atendente recebe um protocolo, ex.: ATD-04102026-1432-K7
# (dia/mês/ano - hora:minuto - código sorteado). Aparece no Telegram e para o cliente.
PREFIXO_PROTOCOLO = "ATD"
# O atendente responde o cliente pelo WhatsApp OFICIAL da empresa (não pelo número do bot).
# Se preencher o número abaixo (ex.: "(61) 90000-0000"), ele aparece na mensagem ao cliente.
# Deixe vazio ("") para mostrar só "WhatsApp oficial da empresa".
WHATSAPP_OFICIAL_EMPRESA = ""

# ---------------------------------------------------------------
# Regras da cotação
# ---------------------------------------------------------------
# Limite do frete fracionado. Vale para o peso real e também para o peso
# considerado (o maior entre o real e o cubado): acima disso, o bot não cota.
PESO_MAXIMO_KG = 1000
# Distância pela estrada ≈ distância em linha reta × 1,28.
# Esse fator foi medido nas viagens da própria planilha da Deflo.
FATOR_ESTRADA = 1.28
# Multiplicador aplicado sobre o valor da tabela (1.0 = usa a tabela exatamente como está).
FATOR_AJUSTE_PRECO = 1.0
# Fator de cubagem: quantos kg "vale" 1 m³ de carga.
# 300 kg/m³ é o padrão usado no transporte rodoviário. ⚠️ CONFIRMAR com a empresa.
FATOR_CUBAGEM = 300

# ---------------------------------------------------------------
# Comportamento da conversa
# ---------------------------------------------------------------
TEMPO_SESSAO_MIN = 30           # sem mensagens por 30 min -> conversa recomeça
LEMBRETE_MIN = 10               # cliente parou no meio da cotação por 10 min -> bot lembra o que falta
PAUSA_ATENDENTE_HORAS = 12      # depois de chamar atendente, por 12h o bot só lembra o protocolo (MENU volta ao bot)

# ---------------------------------------------------------------
# Alerta para o celular do atendente (Telegram)
# ---------------------------------------------------------------
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# ---------------------------------------------------------------
# WhatsApp (API oficial da Meta — WhatsApp Cloud API)
# ---------------------------------------------------------------
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN", "")
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
WHATSAPP_VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "")
WHATSAPP_APP_SECRET = os.getenv("WHATSAPP_APP_SECRET", "")
GRAPH_API_VERSION = os.getenv("GRAPH_API_VERSION", "v23.0")