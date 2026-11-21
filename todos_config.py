"""
Todas as configurações do chatbot em um só lugar.

Por que um arquivo só para isso? Se amanhã o horário mudar, ou o peso
máximo mudar, você altera AQUI e o resto do código continua igual.

Senhas e tokens NÃO ficam escritos no código: eles são lidos do arquivo
.env (veja o .env_exemplo). Assim você pode mostrar o código para o
professor sem expor as chaves da empresa.
"""
import os

# Tenta carregar o arquivo .env (se a biblioteca python-dotenv estiver instalada)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ---------------------------------------------------------------
# Dados no Google Drive
# ---------------------------------------------------------------
# Os dados NÃO ficam no GitHub: ficam na pasta privada "Chatbot Deflo - Dados"
# do Google Drive, e o bot busca de lá (veja todos_drive.py).
# O ID da pasta e o caminho da chave da conta robô vêm do .env / Render.
DRIVE_PASTA_ID = os.getenv("DRIVE_PASTA_ID", "")
GOOGLE_CREDENCIAIS_ARQUIVO = os.getenv("GOOGLE_CREDENCIAIS_ARQUIVO", "")

# Nomes dos arquivos dentro da pasta do Drive (têm que ser exatamente estes)
NOME_TABELA = "TabelaCotacao.xlsx"            # tabela de preços (peso x distância)
ABA_TABELA = "TabelaCotação"                  # nome da aba dentro do Excel
NOME_MUNICIPIOS = "municipios.csv"            # cidades do Brasil com latitude/longitude
NOME_ESTADOS = "estados.csv"
NOME_PLANILHA_REGISTRO = "cotacoes_registradas"   # planilha Google com o histórico das cotações
NOME_PLANILHA_EMAILS = "emails_registrados"       # planilha Google com o histórico dos e-mails
NOME_PLANILHA_CONHECIMENTO = "base_conhecimento"  # planilha Google onde o bot anota o que não soube responder

# De quantos em quantos minutos o bot busca a tabela de preços de novo no Drive.
# Assim, se o dono atualizar os preços, o bot passa a usar a tabela nova sozinho.
TABELA_ATUALIZAR_MIN = 10
# O mesmo para a base de conhecimento: depois de aprovar uma resposta na planilha,
# o bot passa a usar ela dentro desse tempo, sem precisar publicar código novo.
CONHECIMENTO_ATUALIZAR_MIN = 5

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
# E-mail novo também recebe protocolo, com outro começo (M de e-mail), ex.: ATM-04102026-1432-K7.
# Assim, um e-mail e uma mensagem de WhatsApp no mesmo minuto nunca têm o mesmo número.
PREFIXO_PROTOCOLO_EMAIL = "ATM"
# O atendente responde o cliente pelo WhatsApp OFICIAL da empresa (não pelo número do bot).
# Se preencher o número abaixo (ex.: "(61) 90000-0000"), ele aparece na mensagem ao cliente.
# Deixe vazio ("") para mostrar só "WhatsApp oficial da empresa".
WHATSAPP_OFICIAL_EMPRESA = ""

# ---------------------------------------------------------------
# CNPJ do cliente
# ---------------------------------------------------------------
# A empresa transporta só para outras empresas, então a conversa começa pedindo
# o CNPJ. O bot confere os dígitos verificadores (conta do módulo 11), sem
# consultar nada na internet: assim ele nunca barra uma empresa recém-aberta.
# A conferência cadastral (existe? é dessa empresa?) é feita pelo atendente.
# Para desligar a exigência, troque para False.
EXIGIR_CNPJ = True
# O bot pede os 14 caracteres sem ponto, barra ou traço, para todo mundo responder
# igual. Na planilha e no Telegram a máscara é colocada de volta pelo código.
# Com False, o bot também aceita o CNPJ digitado com máscara.
CNPJ_SO_NUMEROS = True
# Quantas vezes o cliente pode errar o CNPJ antes de o bot chamar um atendente.
CNPJ_TENTATIVAS = 3
# Depois do CNPJ, o bot pergunta o primeiro nome do cliente e usa durante a
# conversa. O nome é cortesia, e NÃO exigência: se o cliente não quiser dizer,
# a conversa segue normalmente. Com False, o bot não pergunta.
PERGUNTAR_NOME = True

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
# O bot é uma ferramenta rápida de cotação. Por isso ele NUNCA fica bloqueado
# esperando um atendente: depois de encaminhar, a próxima mensagem do cliente já
# é uma cotação nova, com CNPJ e protocolo novos.
TEMPO_SESSAO_MIN = 15           # sem mensagens por 15 min -> conversa recomeça (e o CNPJ é pedido de novo)
LEMBRETE_MIN = 10               # cliente parou no meio da cotação por 10 min -> bot lembra o que falta
# Quantas vezes seguidas o bot tenta antes de chamar o atendente.
# Com 2: na 3ª vez que o bot não entende (ou que o cliente repete a mesma pergunta),
# ele para de insistir e passa o cliente para o atendente.
INSISTENCIA_MAXIMA = 2

# ---------------------------------------------------------------
# Resumo da base de conhecimento (Telegram)
# ---------------------------------------------------------------
# Uma vez por semana, o bot manda UMA mensagem com as perguntas que ele não
# soube responder, para alguém escrever as respostas na planilha com calma.
# Uma mensagem por semana não atrapalha o canal de alertas. Para desligar,
# troque para False.
RESUMO_LIGADO = True
RESUMO_DIA = 6                  # 0 = segunda ... 6 = domingo
RESUMO_HORA = 9                 # hora cheia em que o resumo é enviado
RESUMO_MAXIMO_PERGUNTAS = 10    # quantas perguntas aparecem na mensagem
RESUMO_VERIFICAR_SEG = 600      # de quanto em quanto tempo o bot olha se é a hora

# ---------------------------------------------------------------
# IA do Google (Gemini) (todos_ia.py)
# ---------------------------------------------------------------
# A IA só entra onde as regras do bot não entendem: uma pergunta que o FAQ e a
# base de conhecimento não respondem, ou um pedido de cotação escrito de um
# jeito que as regras não conseguem ler. Ela NUNCA dá preço: o valor do frete
# continua sendo calculado pelo código, pela tabela.
# Um interruptor só: True liga a IA no teste e na produção, False desliga nos
# dois. Desligada, o bot funciona exatamente como funcionava antes da IA.
# Antes de ligar, preencha a GEMINI_API_KEY no .env e no painel do Render.
IA_LIGADA = True
# Chave da API do Gemini, criada no Google AI Studio. É senha: fica no .env
# (teste) e no painel do Render (produção), nunca no código.
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
# Modelo usado. Os "flash-lite" são os mais rápidos e têm uso gratuito.
# Se um dia o Google aposentar este modelo, troque o nome aqui por um dos que
# aparecem na lista de modelos do Google AI Studio.
IA_MODELO = "gemini-3.1-flash-lite"
# Modelo reserva: usado UMA vez quando o principal está sobrecarregado (erro 503),
# lento demais ou sem limite gratuito. Cada modelo tem a sua própria capacidade,
# então quando um está cheio o outro costuma responder. Deixe "" para não usar.
IA_MODELO_RESERVA = "gemini-2.5-flash-lite"

# ---------------------------------------------------------------
# Alerta para o celular do atendente (Telegram)
# ---------------------------------------------------------------
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
# Senha do webhook do Telegram. O Telegram devolve ela em todo aviso de botão
# tocado, e o servidor recusa o que vier sem ela. Invente uma frase qualquer.
TELEGRAM_SEGREDO = os.getenv("TELEGRAM_SEGREDO", "")

# ---------------------------------------------------------------
# Aviso de e-mail novo no Telegram (todos_email.py)
# ---------------------------------------------------------------
EMAIL_ENDERECO = os.getenv("EMAIL_ENDERECO", "")
EMAIL_SENHA_APP = os.getenv("EMAIL_SENHA_APP", "")     # senha de app do Google, NÃO a senha normal
EMAIL_IMAP_SERVIDOR = "imap.gmail.com"
EMAIL_VERIFICAR_SEG = 60                               # olha a caixa de entrada a cada 1 minuto

# ---------------------------------------------------------------
# WhatsApp (API oficial da Meta — WhatsApp Cloud API)
# ---------------------------------------------------------------
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN", "")
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
WHATSAPP_VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "")
WHATSAPP_APP_SECRET = os.getenv("WHATSAPP_APP_SECRET", "")
GRAPH_API_VERSION = os.getenv("GRAPH_API_VERSION", "v23.0")