"""
Teste automático do chatbot: roda uma lista de conversas e confere as respostas.

Para que serve?
  O teste_simulador.py é para você conversar com o bot na mão. É ótimo para
  explorar, mas lento e cansativo: para conferir tudo são dezenas de mensagens
  digitadas, e é fácil esquecer um caso.
  Este programa faz isso sozinho, em segundos, sempre com os mesmos casos.
  Assim, toda vez que o código mudar, dá para saber na hora se alguma coisa
  que já funcionava parou de funcionar.

O que ele NÃO faz:
  Não manda nada para o Telegram e não escreve nada na planilha do Drive.
  Essas duas partes são trocadas por versões de mentira, que só guardam o que
  teria sido enviado. Assim o teste pode rodar quantas vezes você quiser, sem
  sujar a planilha nem apitar o celular do atendente.
  A lista de cidades e a tabela de preços continuam sendo lidas do Drive, igual
  ao bot de verdade, então é preciso internet e o .env configurado.

Como usar:
    python teste_automatico.py              -> roda tudo e mostra o resultado
    python teste_automatico.py --detalhe    -> mostra também a resposta de cada caso
    python teste_automatico.py --csv        -> salva resultado_dos_testes.csv

Como ler o resultado:
  Cada caso vira uma linha: OK quando passou, FALHOU quando a resposta não bateu.
  No fim aparece a contagem e a porcentagem de acerto.

Como criar um caso novo:
  É só acrescentar um dicionário na lista CASOS, lá embaixo. Os campos são:
    nome       -> o que está sendo testado (aparece no resultado)
    mensagens  -> o que o cliente digita, na ordem. "/esperar 20" finge que passaram
                  20 minutos sem o cliente escrever, e "/audio" finge um áudio.
    espera     -> pedaços de texto que PRECISAM aparecer na última resposta
    nao_espera -> pedaços de texto que NÃO podem aparecer na última resposta
    evento     -> o evento gravado na planilha ("cotacao", "frete_dedicado"...),
                  ou None quando o caso não deve gravar nada
    valor_preenchido -> True/False: se a coluna valor devia estar preenchida
                        (é assim que se sabe que houve cotação, mesmo quando o
                         evento mudou para atendimento)
    anotou     -> True/False: se a pergunta devia ou não ir para a base de conhecimento
    anotou_quantas -> quantas perguntas deviam ter sido anotadas na conversa inteira
    alerta     -> pedaços de texto que precisam aparecer no alerta do Telegram
    alerta_link -> o endereço que o botão do alerta deve abrir
    coluna     -> (nome da coluna, valor esperado) na linha gravada na planilha.
                  Valor None quer dizer que essa coluna NÃO deve existir na planilha.
    aprovadas  -> respostas que já estariam aprovadas na planilha {pergunta: resposta}
    com_cnpj   -> por padrão True: o caso começa como se o cliente já tivesse informado
                  o CNPJ, para o teste ir direto ao que ele quer medir. Use False nos
                  casos que testam justamente o pedido de CNPJ.
    com_nome   -> por padrão True: o caso começa como se o cliente já tivesse dito o
                  primeiro nome. Use False nos casos que testam a pergunta do nome.
  Os textos são comparados sem diferenciar maiúscula de minúscula e sem acento.
"""
import argparse
import csv
import re
import sys
import unicodedata
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import todos_aprendizado as aprendizado
import todos_cep as cep
import todos_cnpj as cnpj
import todos_config as config
import todos_conversa as conversa
import todos_faq as faq

# CNPJ bem formado, usado para o teste começar depois da porta de entrada.
CNPJ_DE_TESTE = "11.222.333/0001-81"   # já no formato guardado, com máscara
NOME_DE_TESTE = "Eduardo"              # o nome que o cliente já teria dito

# Segunda-feira, 10h: dentro do horário de atendimento, para a resposta ser sempre igual
MOMENTO = datetime(2026, 10, 26, 10, 0, tzinfo=ZoneInfo(config.FUSO))


# =================================================================
# Peças de mentira: Telegram e planilha
# =================================================================
class PlanilhaDeMentira:
    """Finge ser uma linha da planilha, mas só guarda o que foi gravado."""

    ultima = None        # a última linha "gravada", para o teste conferir

    def __init__(self, dados):
        self.dados = dict(dados)
        PlanilhaDeMentira.ultima = self.dados

    def marcar_evento(self, protocolo, evento):
        self.dados["protocolo"] = protocolo
        self.dados["evento"] = evento
        PlanilhaDeMentira.ultima = self.dados


def registrar_de_mentira(dados):
    return PlanilhaDeMentira(dados)


class Telegram:
    ultima = None
    ultimo_link = None


def alerta_de_mentira(texto, link=None, rotulo_do_link="", com_botoes=True):
    Telegram.ultima = texto
    Telegram.ultimo_link = link


class AprendizadoDeMentira:
    """
    Finge ser o caderno de aprendizado: guarda o que teria sido anotado, sem
    escrever nada no Drive.
    O filtro de verdade (vale_anotar) continua sendo usado, porque é justamente
    ele que os testes de lixo precisam conferir.
    """

    anotadas = []
    aprovadas = {}      # pergunta -> resposta, como se estivessem aprovadas na planilha

    @staticmethod
    def registrar_pergunta(texto, etapa, momento):
        if aprendizado.vale_anotar(texto, etapa):
            AprendizadoDeMentira.anotadas.append((texto, etapa))

    @staticmethod
    def vale_anotar(texto, etapa):
        return aprendizado.vale_anotar(texto, etapa)

    @staticmethod
    def buscar_resposta(texto):
        for pergunta, resposta in AprendizadoDeMentira.aprovadas.items():
            if aprendizado.sao_a_mesma_pergunta(texto, pergunta):
                return resposta
        return None


# O todos_conversa.py importou essas funções para dentro dele,
# então é ali que elas precisam ser trocadas.
conversa.registrar = registrar_de_mentira
conversa.enviar_alerta = alerta_de_mentira
conversa.aprendizado = AprendizadoDeMentira
faq.aprendizado = AprendizadoDeMentira


# Consulta de CEP de mentira: o teste não pode depender de internet nem bater
# num serviço de terceiro a cada rodada. O formato da resposta é o mesmo do ViaCEP.
CEPS_DE_MENTIRA = {
    "74486225": {"localidade": "Goiânia", "uf": "GO"},
    "39948000": {"localidade": "Padre Paraíso", "uf": "MG"},
    "77001002": {"localidade": "Palmas", "uf": "TO"},
}


def consulta_de_cep_de_mentira(cep_limpo):
    return CEPS_DE_MENTIRA.get(cep_limpo, {"erro": True})


cep._consultar_viacep = consulta_de_cep_de_mentira


# =================================================================
# Comparação de texto
# =================================================================
def simplificar(texto):
    """Deixa o texto comparável: sem acento e tudo em minúsculo."""
    sem_acento = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode()
    return sem_acento.lower()


# =================================================================
# Os casos de teste
# =================================================================
CASOS = [
    # ---------- Porta de entrada: CNPJ ----------
    {"nome": "CNPJ: a conversa começa pedindo o CNPJ",
     "mensagens": ["oi"],
     "espera": ["assistente virtual", "CNPJ"],
     "nao_espera": ["Escolha uma opção"],
     "evento": None, "com_cnpj": False, "com_nome": False},

    {"nome": "CNPJ: número inválido pede de novo",
     "mensagens": ["oi", "12345678901234"],
     "espera": ["não parece válido"],
     "evento": None, "com_cnpj": False},

    {"nome": "CNPJ: todos os dígitos iguais é recusado",
     "mensagens": ["oi", "00.000.000/0000-00"],
     "espera": ["não parece válido"],
     "evento": None, "com_cnpj": False},

    {"nome": "CNPJ: válido e sem máscara libera a conversa",
     "mensagens": ["oi", "11222333000181"],
     "espera": ["Registrei o CNPJ *11.222.333/0001-81*", "Me conta o que você precisa"],
     "nao_espera": ["Escolha uma opção"],
     "evento": None, "com_cnpj": False},

    {"nome": "CNPJ: digitado com máscara pede sem a máscara",
     "mensagens": ["oi", "11.222.333/0001-81"],
     "espera": ["só com os caracteres"],
     "nao_espera": ["Registrei o CNPJ"],
     "evento": None, "com_cnpj": False},

    {"nome": "CNPJ: depois do aviso da máscara, o certo é aceito",
     "mensagens": ["oi", "11.222.333/0001-81", "11222333000181"],
     "espera": ["Registrei o CNPJ"],
     "evento": None, "com_cnpj": False},

    {"nome": "CNPJ: formato novo com letras é aceito",
     "mensagens": ["oi", "12ABC34501DE35"],
     "espera": ["Registrei o CNPJ *12.ABC.345/01DE-35*"],
     "evento": None, "com_cnpj": False},

    {"nome": "CNPJ: o que o cliente queria é retomado depois",
     "mensagens": ["quero cotar de goiania go para palmas to 450kg", "11222333000181"],
     "espera": ["Registrei o CNPJ", "Medidas"],
     "evento": None, "com_cnpj": False},

    # Pedido real do WhatsApp: o cliente manda tudo numa mensagem só, com o CNPJ
    # no meio de uma lista numerada.
    {"nome": "CNPJ: no meio de uma mensagem maior, é aceito",
     "mensagens": ["oi", "Realiza essa cotação pra mim por favor, sou de brasilia, "
                         "mas quero cotar de manaus para camboriu\n\n"
                         "1) CNPJ do pagador do frete\n45053805000131\n"
                         "5) Peso total dos volumes 300kg"],
     "espera": ["Registrei o CNPJ *45.053.805/0001-31*"],
     "evento": None, "com_cnpj": False, "com_nome": False},

    # Quem manda o pedido pronto não é interrompido para dizer o nome: o bot
    # registra o CNPJ e já segue com a cotação.
    {"nome": "CNPJ: o pedido da mesma mensagem é aproveitado na hora",
     "mensagens": ["oi", "Realiza essa cotação pra mim por favor, sou de brasilia, "
                         "mas quero cotar de manaus para camboriu\n\n"
                         "1) CNPJ do pagador do frete\n45053805000131\n"
                         "5) Peso total dos volumes 300kg"],
     "espera": ["Origem: Manaus - AM", "Destino: Camboriú - SC", "300 kg"],
     "nao_espera": ["Brasília", "primeiro nome"],
     "evento": None, "com_cnpj": False, "com_nome": False},

    {"nome": "CNPJ: com mais de um na mensagem, o bot pergunta qual é",
     "mensagens": ["oi", "pagador 45053805000131, remetente 11222333000181"],
     "espera": ["mais de um CNPJ"],
     "nao_espera": ["Registrei o CNPJ"],
     "evento": None, "com_cnpj": False, "com_nome": False},

    {"nome": "CNPJ: dúvida é respondida mesmo antes do CNPJ",
     "mensagens": ["oi", "tem seguro?"],
     "espera": ["seguro da mercadoria", "CNPJ"],
     "nao_espera": ["protocolo"],
     "evento": None, "com_cnpj": False},

    {"nome": "CNPJ: pessoa física vai para o atendente",
     "mensagens": ["oi", "sou pessoa física"],
     "espera": ["protocolo"],
     "evento": "cnpj", "com_cnpj": False},

    {"nome": "CNPJ: três erros ainda pedem de novo",
     "mensagens": ["oi", "111", "222", "333"],
     "espera": ["não parece válido"],
     "nao_espera": ["protocolo"],
     "evento": None, "com_cnpj": False},

    {"nome": "CNPJ: do quarto erro em diante chama o atendente",
     "mensagens": ["oi", "111", "222", "333", "444"],
     "espera": ["protocolo"],
     "evento": "cnpj", "com_cnpj": False},

    {"nome": "CNPJ vai para a planilha na linha da cotação",
     "mensagens": ["1", "goiania go", "palmas to", "450", "pular"],
     "evento": "cotacao", "coluna": ("cnpj", "11.222.333/0001-81")},

    {"nome": "CNPJ: depois do atendente, a próxima mensagem já pede de novo",
     "mensagens": ["quero falar com alguém", "oi"],
     "espera": ["preciso do *CNPJ*"],
     "nao_espera": ["Escolha uma opção"],
     "evento": "atendimento"},

    {"nome": "Atendente: o bot não fica bloqueado esperando",
     "mensagens": ["quero falar com alguém", "oi", "11222333000181", "1"],
     "espera": ["Cidade de Origem"],
     "nao_espera": ["já foi encaminhado"],
     "evento": "atendimento"},

    # O alerta chega marcado com ❌ e com o botão que abre a conversa. O atendente
    # toca em "Já atendi" e o ❌ vira ✅, na mesma mensagem.
    {"nome": "Alerta: chega marcado como não atendido",
     "mensagens": ["quero falar com alguém"],
     "alerta": ["❌ NOVO ATENDIMENTO"],
     "evento": "atendimento"},

    {"nome": "Alerta: o botão abre a conversa do cliente no WhatsApp",
     "mensagens": ["quero falar com alguém"],
     "alerta_link": "https://wa.me/5561900000020",
     "evento": "atendimento"},

    {"nome": "Atendente: cada encaminhamento gera um protocolo novo",
     "mensagens": ["quero falar com alguém", "oi", "11222333000181", "Eduardo",
                   "quero falar com alguém"],
     "espera": ["protocolo"],
     "evento": "atendimento"},

    {"nome": "CNPJ: MENU sem CNPJ não libera o menu",
     "mensagens": ["oi", "menu"],
     "espera": ["preciso do *CNPJ*"],
     "nao_espera": ["Escolha uma opção"],
     "evento": None, "com_cnpj": False},

    {"nome": "CNPJ: parado por mais de 15 minutos, pede de novo",
     "mensagens": ["oi", "11222333000181", "/esperar 20", "oi"],
     "espera": ["preciso do *CNPJ*"],
     "evento": None, "com_cnpj": False},

    {"nome": "CNPJ: parado por menos de 15 minutos, segue a conversa",
     "mensagens": ["oi", "11222333000181", "/esperar 5", "1"],
     "espera": ["Cidade de Origem"],
     "nao_espera": ["preciso do *CNPJ*"],
     "evento": None, "com_cnpj": False},

    # ---------- O nome do cliente ----------
    {"nome": "Nome: depois do CNPJ, o bot pergunta o primeiro nome",
     "mensagens": ["oi", "11222333000181"],
     "espera": ["Registrei o CNPJ", "primeiro nome"],
     "evento": None, "com_cnpj": False, "com_nome": False},

    {"nome": "Nome: o bot cumprimenta pelo nome e abre a conversa",
     "mensagens": ["oi", "11222333000181", "Eduardo"],
     "espera": ["Prazer, Eduardo", "Me conta o que você precisa"],
     "evento": None, "com_cnpj": False, "com_nome": False},

    {"nome": "Nome: numa frase (meu nome é...) o bot tira só o primeiro nome",
     "mensagens": ["oi", "11222333000181", "meu nome é eduardo santos"],
     "espera": ["Prazer, Eduardo"],
     "nao_espera": ["Santos"],
     "evento": None, "com_cnpj": False, "com_nome": False},

    {"nome": "Nome: quem não quer dizer segue a conversa sem o nome",
     "mensagens": ["oi", "11222333000181", "prefiro não dizer"],
     "espera": ["Me conta o que você precisa"],
     "nao_espera": ["Prazer", "primeiro nome"],
     "evento": None, "com_cnpj": False, "com_nome": False},

    {"nome": "Nome: o bot NÃO insiste e nunca pergunta duas vezes",
     "mensagens": ["oi", "11222333000181", "450"],
     "nao_espera": ["primeiro nome"],
     "evento": None, "com_cnpj": False, "com_nome": False},

    {"nome": "Nome: no lugar do nome, o cliente já pede a cotação",
     "mensagens": ["oi", "11222333000181", "de goiania go para palmas to 450kg"],
     "espera": ["Medidas"],
     "nao_espera": ["primeiro nome"],
     "evento": None, "com_cnpj": False, "com_nome": False},

    {"nome": "Nome: no lugar do nome, o cliente faz uma dúvida",
     "mensagens": ["oi", "11222333000181", "tem seguro?"],
     "espera": ["seguro da mercadoria"],
     "evento": None, "com_cnpj": False, "com_nome": False},

    # O WhatsApp pode ser o número de uma empresa: quem escreve na conversa
    # seguinte pode ser outro funcionário. Por isso o nome é pedido de novo.
    {"nome": "Nome: depois do atendente, o CNPJ E o nome são pedidos de novo",
     "mensagens": ["quero falar com alguém", "oi", "11222333000181"],
     "espera": ["Registrei o CNPJ", "primeiro nome"],
     "nao_espera": ["Prazer, Eduardo"],
     "evento": "atendimento"},

    {"nome": "Nome: depois do atendente, o bot usa o nome NOVO, não o antigo",
     "mensagens": ["quero falar com alguém", "oi", "11222333000181", "Mariana"],
     "espera": ["Prazer, Mariana"],
     "nao_espera": ["Eduardo"],
     "evento": "atendimento"},

    {"nome": "Nome: passados 15 minutos, o nome também é pedido de novo",
     "mensagens": ["oi", "/esperar 20", "oi", "11222333000181"],
     "espera": ["primeiro nome"],
     "evento": None},

    # Decisão de projeto: o nome serve para conversar e para o atendente, e NÃO
    # entra na planilha de cotações. Este caso existe para ninguém colocar de volta.
    {"nome": "Nome: NÃO vai para a planilha de cotações",
     "mensagens": ["1", "goiania go", "palmas to", "450", "pular"],
     "evento": "cotacao", "coluna": ("nome", None)},

    {"nome": "Nome: o bot usa o nome ao entregar a cotação",
     "mensagens": ["1", "goiania go", "palmas to", "450", "pular"],
     "espera": ["Pronto, Eduardo!"],
     "evento": "cotacao", "valor_preenchido": True},

    {"nome": "Nome: o bot usa o nome ao encaminhar para o atendente",
     "mensagens": ["quero falar com alguém"],
     "espera": ["Pronto, Eduardo!", "protocolo"],
     "evento": "atendimento"},

    {"nome": "Nome: sem o nome, o bot fala igual, só sem cumprimentar",
     "mensagens": ["1", "goiania go", "palmas to", "450", "pular"],
     "espera": ["Pronto!", "Valor estimado"],
     "nao_espera": ["Prazer"],
     "evento": "cotacao", "com_nome": False},

    # ---------- CEP no lugar da cidade ----------
    # Pedido real, lido do CRM: o cliente manda os dados numerados e usa CEP.
    {"nome": "CEP: pedido estruturado com CEP de origem e de destino",
     "mensagens": ["""Realiza essa cotação pra mim por favor

1) CNPJ do pagador do frete 45053805000131
2) CNPJ do Remetente 309781170001/05
3) CNPJ do destinatário 45053805000131
4) CEP de origem 74486-225
5) CEP de destino 39948-000
6) Tipo de material Tenda Piramidal
7) Valor da nota fiscal
R$ 6.200,00
8) Quantidade de volumes: 9
9) Peso total dos volumes 240kg"""],
     "espera": ["Goiânia - GO", "Padre Paraíso - MG", "240 kg", "Medidas"],
     "nao_espera": ["cidade de origem"],
     "evento": None},

    {"nome": "CEP: o CNPJ da mensagem não é confundido com CEP",
     "mensagens": ["cotação do cep 74486-225 para o cep 39948-000, cnpj 45053805000131, 100kg"],
     "espera": ["Goiânia - GO", "Padre Paraíso - MG"],
     "evento": None},

    {"nome": "CEP: respondendo a pergunta da cidade com um CEP",
     "mensagens": ["1", "74486-225"],
     "espera": ["Goiânia - GO", "CEP de destino"],
     "evento": None},

    {"nome": "CEP: sem hífen também vale quando é a resposta inteira",
     "mensagens": ["1", "74486225"],
     "espera": ["Goiânia - GO"],
     "evento": None},

    {"nome": "CEP: inexistente faz o bot pedir a cidade, sem travar",
     "mensagens": ["1", "99999-999"],
     "espera": ["cidade de origem"],
     "nao_espera": ["protocolo"],
     "evento": None},

    {"nome": "CEP nos dois lados fecha a cotação",
     "mensagens": ["1", "74486-225", "39948-000", "450", "pular"],
     "espera": ["Padre Paraíso - MG", "Valor estimado"],
     "evento": "cotacao", "valor_preenchido": True},

    {"nome": "CEP: a planilha guarda o CEP de origem",
     "mensagens": ["1", "74486-225", "39948-000", "450", "pular"],
     "evento": "cotacao", "coluna": ("cep_origem", "74486-225")},

    {"nome": "CEP: quem pede por CEP deixa a cidade como nao_informado",
     "mensagens": ["1", "74486-225", "39948-000", "450", "pular"],
     "evento": "cotacao", "coluna": ("cidade_origem", "nao_informado")},

    {"nome": "CEP: quem pede por cidade deixa o CEP como nao_informado",
     "mensagens": ["1", "goiania go", "palmas to", "450", "pular"],
     "evento": "cotacao", "coluna": ("cep_origem", "nao_informado")},

    # ---------- Cidade com cidade, CEP com CEP: a rota não mistura ----------
    # O bot não aceita o formato diferente, e também não dá sermão: ele só
    # repete a pergunta, que já diz se é cidade ou CEP.
    {"nome": "Mistura: começou por cidade, mandou CEP, o bot repete a pergunta",
     "mensagens": ["1", "goiania go", "39948-000"],
     "espera": ["cidade de destino"],
     "nao_espera": ["Padre Paraíso", "bagunçada", "você começou"],
     "evento": None},

    {"nome": "Mistura: começou por CEP, mandou cidade, o bot repete a pergunta",
     "mensagens": ["1", "74486-225", "palmas to"],
     "espera": ["CEP de destino"],
     "nao_espera": ["Destino: Palmas", "bagunçada", "você começou"],
     "evento": None},

    {"nome": "Mistura: depois da recusa, o cliente corrige e a cotação sai",
     "mensagens": ["1", "goiania go", "39948-000", "palmas to", "450", "pular"],
     "espera": ["Destino: Palmas - TO", "Valor estimado"],
     "evento": "cotacao", "valor_preenchido": True},

    {"nome": "Mistura: depois da recusa pelo CEP, o cliente corrige e segue",
     "mensagens": ["1", "74486-225", "palmas to", "39948-000"],
     "espera": ["Padre Paraíso - MG", "peso total"],
     "nao_espera": ["bagunçada"],
     "evento": None},

    {"nome": "Mistura numa mensagem só: cidade na origem e CEP no destino",
     "mensagens": ["cotacao de goiania go para o cep 39948-000, 450kg"],
     "espera": ["Origem: Goiânia - GO", "cidade de destino"],
     "nao_espera": ["Padre Paraíso", "bagunçada"],
     "evento": None},

    {"nome": "Mistura numa mensagem só: CEP na origem e cidade no destino",
     "mensagens": ["cep de origem 74486-225, destino palmas to, 450kg"],
     "espera": ["CEP de destino"],
     "nao_espera": ["Valor estimado", "bagunçada"],
     "evento": None},

    {"nome": "Rota toda por CEP numa mensagem só continua funcionando",
     "mensagens": ["de 74486-225 para 39948-000, 450kg, 50x40x30"],
     "espera": ["Valor estimado"],
     "evento": "cotacao", "valor_preenchido": True},

    {"nome": "CEP: o peso da frase não vira quantidade de volumes",
     "mensagens": ["de 74486-225 para 39948-000, 450kg, 50x40x30"],
     "espera": ["1 volume de 50x40x30 cm"],
     "nao_espera": ["450 volumes"],
     "evento": "cotacao", "valor_preenchido": True},

    {"nome": "CEP: a distância é calculada mesmo vindo de CEP",
     "mensagens": ["1", "74486-225", "77001-002", "450", "pular"],
     "espera": ["Distância aproximada"],
     "evento": "cotacao", "valor_preenchido": True},

    # ---------- Caminho rápido x caminho tranquilo ----------
    # Quem chega com o pedido pronto quer velocidade: o bot não para para
    # perguntar o nome, vai direto à cotação.
    {"nome": "Rápido: pedido completo com CNPJ vira cotação sem perguntar o nome",
     "mensagens": ["quero cotar de goiania go para palmas to, 450kg, 50x40x30, "
                   "cnpj 11222333000181"],
     "espera": ["Registrei o CNPJ", "Valor estimado"],
     "nao_espera": ["primeiro nome"],
     "evento": "cotacao", "valor_preenchido": True, "com_cnpj": False, "com_nome": False},

    {"nome": "Rápido: o nome só é pedido ao chamar o atendente",
     "mensagens": ["quero cotar de goiania go para palmas to, 450kg, 50x40x30, "
                   "cnpj 11222333000181", "1"],
     "espera": ["Para um melhor atendimento"],
     "evento": "cotacao", "com_cnpj": False, "com_nome": False},

    {"nome": "Rápido: depois do nome, o protocolo sai",
     "mensagens": ["quero cotar de goiania go para palmas to, 450kg, 50x40x30, "
                   "cnpj 11222333000181", "1", "Eduardo"],
     "espera": ["Pronto, Eduardo!", "protocolo"],
     "evento": "atendimento", "valor_preenchido": True,
     "com_cnpj": False, "com_nome": False},

    # Quem chega com "oi" está tranquilo: o bot se apresenta e pergunta o nome.
    {"nome": "Tranquilo: quem chega com oi é perguntado o nome depois do CNPJ",
     "mensagens": ["oi", "11222333000181"],
     "espera": ["primeiro nome"],
     "evento": None, "com_cnpj": False, "com_nome": False},

    {"nome": "Tranquilo: 'vim do site' não vira pergunta sem resposta",
     "mensagens": ["vim do site"],
     "espera": ["preciso do *CNPJ*"],
     "nao_espera": ["não sei te responder"],
     "evento": None, "com_cnpj": False, "com_nome": False},

    # ---------- Pergunta logo na chegada, antes do CNPJ ----------
    {"nome": "Pergunta na chegada: o bot responde sem exigir o CNPJ antes",
     "mensagens": ["tem seguro?"],
     "espera": ["seguro da mercadoria", "CNPJ"],
     "evento": None, "com_cnpj": False, "com_nome": False},

    {"nome": "Pergunta na chegada sem resposta: o bot oferece o atendente",
     "mensagens": ["vocês emitem certificado de origem?"],
     "espera": ["não sei te responder", "falar com um atendente"],
     "nao_espera": ["preciso do *CNPJ*"],
     "evento": None, "com_cnpj": False, "com_nome": False, "anotou": True},

    {"nome": "Pergunta na chegada: aceitando o atendente, pede CNPJ e nome",
     "mensagens": ["vocês emitem certificado de origem?", "1", "11222333000181", "Eduardo"],
     "espera": ["Pronto, Eduardo!", "protocolo"],
     "evento": "atendimento", "coluna": ("cnpj", "11.222.333/0001-81"),
     "com_cnpj": False, "com_nome": False},

    # ---------- Vários CNPJs na mesma mensagem ----------
    # O cliente já disse na mensagem que não tem as medidas: perguntar de novo
    # seria não ter lido o que ele escreveu.
    {"nome": "Medidas: 'não sei as medidas' na mensagem fecha a cotação direto",
     "mensagens": ["cotação de goiania go para palmas to, 450kg, cnpj 11222333000181, "
                   "não sei as medidas"],
     "espera": ["Valor estimado"],
     "nao_espera": ["Você sabe as *medidas*"],
     "evento": "cotacao", "valor_preenchido": True,
     "com_cnpj": False, "com_nome": False},

    {"nome": "Medidas: 'sem medidas' também é entendido",
     "mensagens": ["cotação de goiania go para palmas to, 450kg, sem medidas"],
     "espera": ["Valor estimado"],
     "nao_espera": ["Você sabe as *medidas*"],
     "evento": "cotacao", "valor_preenchido": True},

    {"nome": "Medidas: quem não diz nada continua sendo perguntado",
     "mensagens": ["cotação de goiania go para palmas to, 450kg"],
     "espera": ["Você sabe as *medidas*"],
     "evento": None},

    # Três CNPJs, sendo dois iguais: a lista mostra como o cliente escreveu.
    {"nome": "CNPJ: a lista sai do jeito que o cliente escreveu",
     "mensagens": ["1) CNPJ do pagador 45053805000131\n"
                   "2) CNPJ do Remetente 309781170001/05\n"
                   "3) CNPJ do destinatário 45053805000131\n"
                   "de goiania go para palmas to 450kg"],
     "espera": ["1. 45053805000131", "2. 309781170001/05", "3. 45053805000131"],
     "evento": None, "com_cnpj": False, "com_nome": False},

    {"nome": "CNPJ: o mesmo repetido não vira pergunta",
     "mensagens": ["pagador 45053805000131 e destinatário 45053805000131, "
                   "de goiania go para palmas to 450kg, sem medidas"],
     "espera": ["Registrei o CNPJ *45.053.805/0001-31*"],
     "nao_espera": ["mais de um CNPJ"],
     "evento": "cotacao", "com_cnpj": False, "com_nome": False},

    {"nome": "Rápido: quem começou com oi e depois mandou tudo não é perguntado o nome",
     "mensagens": ["oi", "cotação de goiania go para palmas to, 450kg, "
                         "cnpj 11222333000181, sem medidas"],
     "espera": ["Valor estimado"],
     "nao_espera": ["primeiro nome"],
     "evento": "cotacao", "com_cnpj": False, "com_nome": False},

    {"nome": "Alerta: não repete o link em texto, só no botão",
     "mensagens": ["quero falar com alguém"],
     "alerta_link": "https://wa.me/5561900000071",
     "evento": "atendimento"},

    {"nome": "CNPJ: os achados são listados com número",
     "mensagens": ["cotação de goiania go para palmas to 450kg, "
                   "pagador 45053805000131, remetente 11222333000181"],
     "espera": ["1. 45053805000131", "2. 11222333000181", "Digite o *número*"],
     "evento": None, "com_cnpj": False, "com_nome": False},

    {"nome": "CNPJ: escolhido pelo número, a cotação segue sem redigitar nada",
     "mensagens": ["cotação de goiania go para palmas to 450kg, "
                   "pagador 45053805000131, remetente 11222333000181", "2", "pular"],
     "espera": ["Valor estimado"],
     "evento": "cotacao", "valor_preenchido": True,
     "coluna": ("cnpj", "11.222.333/0001-81"),
     "com_cnpj": False, "com_nome": False},

    # ---------- Menu e cotação ----------
    {"nome": "Primeira mensagem convida o cliente a escrever, sem jogar o menu",
     "mensagens": ["oi"],
     "espera": ["assistente virtual", "Me conta o que você precisa", "digite MENU"],
     "nao_espera": ["Escolha uma opção", "1\u20e3 Fazer uma cotação"],
     "evento": None},

    {"nome": "Cotação completa pelo menu, com medidas",
     "mensagens": ["1", "goiania go", "palmas to", "450", "3 caixas de 50x40x30"],
     "espera": ["Cotação de frete fracionado", "Peso cubado: 54 kg", "Peso considerado: 450 kg"],
     "evento": "cotacao", "valor_preenchido": True},

    {"nome": "Cotação pulando as medidas",
     "mensagens": ["1", "goiania go", "palmas to", "450", "pular"],
     "espera": ["Cotação de frete fracionado", "só pelo peso"],
     "evento": "cotacao"},

    # Mensagem real do WhatsApp: o cliente cita a cidade da empresa dele de
    # passagem, antes de dizer a rota. Vale a cidade colada no "para".
    {"nome": "Rota: cidade citada de passagem não vira a origem",
     "mensagens": ["Olá, tudo bem, sou da empresa tamarindo que tem sede em são paulo. "
                   "Gostaria de fazer uma cotação de Goiania para manaus, "
                   "valor da carga 300Kg as medidas eu não sei"],
     "espera": ["Origem: Goiânia - GO", "Destino: Manaus - AM", "300 kg"],
     "nao_espera": ["São Paulo"],
     "evento": "cotacao", "valor_preenchido": True},

    {"nome": "Rota: cidade citada depois do destino não vira o destino",
     "mensagens": ["quero fazer uma cotação de goiania para manaus, mas o transporte "
                   "não é para mim não, eu sou de Brasília, 300kg"],
     "espera": ["Origem: Goiânia - GO", "Destino: Manaus - AM"],
     "nao_espera": ["Brasília"],
     "evento": None},

    {"nome": "Rota: a origem continua sendo o nome inteiro da cidade",
     "mensagens": ["cotação de belo horizonte mg para salvador ba, 300kg"],
     "espera": ["Origem: Belo Horizonte - MG", "Destino: Salvador - BA"],
     "nao_espera": ["Horizonte - CE"],
     "evento": None},

    {"nome": "Rota: com uma cidade de cada lado, o bot usa as duas",
     "mensagens": ["sou de brasília e quero cotar para manaus, 300kg"],
     "espera": ["Origem: Brasília - DF", "Destino: Manaus - AM"],
     "evento": None},

    {"nome": "Rota: sem cidade antes do para, o bot pergunta em vez de inventar",
     "mensagens": ["cotação para manaus, 300kg"],
     "espera": ["cidade de origem"],
     "nao_espera": ["Valor estimado"],
     "evento": None},

    # O cliente diz com todas as letras de onde a carga sai, fora da ordem
    # "de X para Y". Isso não pode ser jogado fora.
    {"nome": "Rota: a origem marcada com 'a carga sai de' é aproveitada",
     "mensagens": ["cotação para manaus, a carga sai de goiania, 300kg"],
     "espera": ["Origem: Goiânia - GO", "Destino: Manaus - AM"],
     "evento": None},

    {"nome": "Rota: a origem marcada com 'coleta em' é aproveitada",
     "mensagens": ["cotação para manaus, coleta em goiania, 300kg"],
     "espera": ["Origem: Goiânia - GO"],
     "evento": None},

    {"nome": "Rota: coleta e entrega marcadas, sem a palavra para",
     "mensagens": ["coleta em goiania go, entrega em manaus, 300kg"],
     "espera": ["Origem: Goiânia - GO", "Destino: Manaus - AM"],
     "evento": None},

    # Duas cidades na mensagem são a rota, qualquer que seja a frase que as
    # apresentou. A única dúvida é qual é a origem e qual é o destino.
    {"nome": "Rota: com duas cidades, a que sobrou vira a ponta que falta",
     "mensagens": ["cotação para manaus, eu moro em brasilia, 300kg"],
     "espera": ["Origem: Brasília - DF", "Destino: Manaus - AM"],
     "evento": None},

    {"nome": "Rota: a cidade da nota fiscal serve quando é a única que sobrou",
     "mensagens": ["cotação para manaus, nota fiscal emitida em sao paulo, 300kg"],
     "espera": ["Origem: São Paulo - SP", "Destino: Manaus - AM"],
     "evento": None},

    # Com TRÊS cidades, a que sobrou não é escolhida: a rota já veio das outras duas.
    {"nome": "Rota: com três cidades, a citada de passagem continua fora",
     "mensagens": ["sou da empresa tamarindo que tem sede em são paulo, "
                   "cotação de goiania para manaus, 300kg"],
     "espera": ["Origem: Goiânia - GO", "Destino: Manaus - AM"],
     "nao_espera": ["São Paulo"],
     "evento": None},

    {"nome": "Rota: com duas cidades sobrando, o bot pergunta em vez de escolher",
     "mensagens": ["cotação para manaus, eu moro em brasilia, "
                   "a carga pode sair daqui ou de salvador ba, 300kg"],
     "espera": ["cidade de origem"],
     "evento": None},

    {"nome": "Rota: uma cidade só, sem saber se é origem ou destino, o bot pergunta",
     "mensagens": ["quero uma cotação, a nota é de sao paulo sp, 300kg"],
     "espera": ["cidade de origem"],
     "evento": None},

    # Sem "para" e sem expressão marcada, vale a ordem da frase.
    {"nome": "Rota: o 'pra mim' da conversa não vira separador da rota",
     "mensagens": ["realiza essa cotação pra mim por favor, de manaus para camboriu, 300kg"],
     "espera": ["Origem: Manaus - AM", "Destino: Camboriú - SC"],
     "evento": None},

    {"nome": "Rota: duas cidades soltas, a primeira é a origem",
     "mensagens": ["quero cotar brasilia manaus, 300kg"],
     "espera": ["Origem: Brasília - DF", "Destino: Manaus - AM"],
     "evento": None},

    {"nome": "Rota: duas cidades soltas, separadas por vírgula",
     "mensagens": ["goiania, manaus, 300kg"],
     "espera": ["Origem: Goiânia - GO", "Destino: Manaus - AM"],
     "evento": None},

    # Quando existe um sinal na frase, ele vale MAIS que a ordem: aqui o destino
    # está escrito primeiro e mesmo assim a rota sai certa.
    {"nome": "Rota: o destino escrito primeiro, com a origem marcada depois",
     "mensagens": ["manaus, mas a carga sai de goiania, 300kg"],
     "espera": ["Origem: Goiânia - GO", "Destino: Manaus - AM"],
     "evento": None},

    {"nome": "Rota: entrega escrita antes da coleta",
     "mensagens": ["entrega em manaus, coleta em goiania go, 300kg"],
     "espera": ["Origem: Goiânia - GO", "Destino: Manaus - AM"],
     "evento": None},

    {"nome": "Rota: o para manda mais que a ordem",
     "mensagens": ["moro em brasilia, cotação para manaus, 300kg"],
     "espera": ["Origem: Brasília - DF", "Destino: Manaus - AM"],
     "evento": None},

    {"nome": "Rota: com três cidades soltas, o bot pergunta em vez de chutar",
     "mensagens": ["cotação brasilia, goiania, manaus, 300kg"],
     "espera": ["cidade de origem"],
     "evento": None},

    {"nome": "Cotação numa frase só",
     "mensagens": ["goiania go para palmas to 450kg", "pular"],
     "espera": ["Cotação de frete fracionado"],
     "evento": "cotacao"},

    {"nome": "Quantidade informada vai para a planilha",
     "mensagens": ["1", "goiania go", "palmas to", "450", "3 caixas de 50x40x30"],
     "espera": ["3 volumes"],
     "evento": "cotacao", "coluna": ("preenchimento_qtd_transportada", "informado")},

    {"nome": "Medidas sem quantidade NÃO viram 1 na planilha",
     "mensagens": ["1", "goiania go", "palmas to", "450", "50x40x30"],
     "espera": ["Cotação de frete fracionado"],
     "evento": "cotacao", "coluna": ("preenchimento_qtd_transportada", "nao_informado")},

    {"nome": "Cidade com nome repetido pede para escolher",
     "mensagens": ["1", "goiania go", "palmas"],
     "espera": ["mais de uma cidade", "Digite o número"],
     "evento": None},

    {"nome": "Cidade que não existe pede de novo",
     "mensagens": ["1", "xxxxxxx"],
     "espera": ["Não encontrei essa cidade"],
     "evento": None},

    {"nome": "Medidas em metros são convertidas para centímetros",
     "mensagens": ["1", "goiania go", "palmas to", "450", "1x1x1 m"],
     "espera": ["100x100x100 cm", "Peso cubado: 300 kg"],
     "evento": "cotacao", "valor_preenchido": True},

    {"nome": "Medidas em milímetros também são convertidas",
     "mensagens": ["1", "goiania go", "palmas to", "450", "500x400x300 mm"],
     "espera": ["50x40x30 cm"],
     "evento": "cotacao", "valor_preenchido": True},

    {"nome": "Medidas em polegadas continuam sendo recusadas",
     "mensagens": ["1", "goiania go", "palmas to", "450", "20x16x12 polegadas"],
     "espera": ["centímetros"],
     "nao_espera": ["Valor estimado"],
     "evento": None},

    # ---------- Carga com volumes de tamanhos diferentes ----------
    # O pedido real do CRM: 9 volumes em 5 medidas, comprimento em metros e
    # seção em centímetros na mesma linha.
    {"nome": "Carga mista: soma o volume de cada linha",
     "mensagens": ["1", "goiania go", "palmas to", "240",
                   """2- volume de 4,86 por 30x30
2- volume de 3,60 por 30x30
2- volume de 2,50 por 30x30
2- volume de 0,40 por 30x30
1- volume de 0,80 por 30x30"""],
     "espera": ["Peso cubado: 635 kg", "Peso considerado: 635 kg"],
     "evento": "cotacao", "valor_preenchido": True},

    {"nome": "Carga mista: a quantidade total vai para a planilha",
     "mensagens": ["1", "goiania go", "palmas to", "240",
                   """2- volume de 4,86 por 30x30
2- volume de 3,60 por 30x30
2- volume de 2,50 por 30x30
2- volume de 0,40 por 30x30
1- volume de 0,80 por 30x30"""],
     "evento": "cotacao", "coluna": ("qtd_transportada", 9)},

    {"nome": "Carga mista: a planilha guarda todas as linhas de medida",
     "mensagens": ["1", "goiania go", "palmas to", "240",
                   """2- volume de 4,86 por 30x30
1- volume de 0,80 por 30x30"""],
     "evento": "cotacao", "coluna": ("medidas", "2x 486x30x30 cm | 1x 80x30x30 cm")},

    {"nome": "Carga mista numa frase só, com e",
     "mensagens": ["1", "goiania go", "palmas to", "450",
                   "2 caixas de 50x40x30 e 3 caixas de 80x60x40"],
     "espera": ["Peso cubado: 208,8 kg"],
     "evento": "cotacao", "valor_preenchido": True},

    {"nome": "Medida pequena demais para ser centímetro é lida como metro",
     "mensagens": ["1", "goiania go", "palmas to", "100", "4,86 por 30x30"],
     "espera": ["486x30x30 cm"],
     "evento": "cotacao", "valor_preenchido": True},

    {"nome": "Carga mista volumosa demais vai para o atendente",
     "mensagens": ["1", "goiania go", "palmas to", "100",
                   """10- volume de 4,86 por 100x100
10- volume de 3,60 por 100x100"""],
     "espera": ["volumosa", "protocolo"],
     "evento": "carga_volumosa"},

    {"nome": "Peso acima do limite avisa e volta ao menu",
     "mensagens": ["1", "goiania go", "palmas to", "5000"],
     "espera": ["cargas de até", "Escolha uma opção"],
     "evento": None},

    {"nome": "Carga volumosa vai para o atendente",
     "mensagens": ["1", "goiania go", "palmas to", "100", "10 caixas de 150x150x150"],
     "espera": ["volumosa", "protocolo"],
     "evento": "carga_volumosa"},

    # ---------- Peso informado como limite ----------
    {"nome": "Peso como limite pede o valor exato",
     "mensagens": ["1", "goiania go", "palmas to", "peso superior a 100 kg"],
     "espera": ["peso exato"],
     "nao_espera": ["protocolo"],
     "evento": None},

    {"nome": "Peso como limite na frase inteira não é aceito",
     "mensagens": ["goiania go para palmas to, mais de 500 kg"],
     "espera": ["Peso Total"],
     "evento": None},

    {"nome": "Peso aproximado continua sendo aceito",
     "mensagens": ["1", "goiania go", "palmas to", "aproximadamente 100 kg"],
     "espera": ["Peso: 100 kg", "Medidas"],
     "evento": None},

    # ---------- Frete dedicado ----------
    {"nome": "Dedicado: a palavra dedicado",
     "mensagens": ["quero frete dedicado"],
     "espera": ["frete dedicado", "protocolo"],
     "evento": "frete_dedicado", "valor_preenchido": False},

    {"nome": "Dedicado: nome do caminhão (carreta)",
     "mensagens": ["quero cotar uma carreta"],
     "espera": ["frete dedicado", "protocolo"],
     "evento": "frete_dedicado"},

    {"nome": "Dedicado: nome do caminhão (bitruck)",
     "mensagens": ["cota pra mim um bitruck"],
     "espera": ["protocolo"],
     "evento": "frete_dedicado"},

    {"nome": "Dedicado: 3/4 com barra",
     "mensagens": ["tem como ser 3/4?"],
     "espera": ["protocolo"],
     "evento": "frete_dedicado"},

    {"nome": "Dedicado: carga fechada",
     "mensagens": ["é carga fechada"],
     "espera": ["protocolo"],
     "evento": "frete_dedicado"},

    # O cliente já disse a rota e o peso na mesma frase do pedido de dedicado.
    # Isso não pode virar nao_informado na planilha: o atendente perguntaria de novo.
    {"nome": "Dedicado: a origem da frase vai para a planilha",
     "mensagens": ["quero um bitruck de ubatuba para sao paulo, mais ou menos uns 500kg de carga"],
     "evento": "frete_dedicado", "coluna": ("cidade_origem", "Ubatuba - SP")},

    {"nome": "Dedicado: o destino da frase vai para a planilha",
     "mensagens": ["quero um bitruck de ubatuba para sao paulo, mais ou menos uns 500kg de carga"],
     "evento": "frete_dedicado", "coluna": ("cidade_destino", "São Paulo - SP")},

    {"nome": "Dedicado: o peso da frase vai para a planilha",
     "mensagens": ["quero um bitruck de ubatuba para sao paulo, mais ou menos uns 500kg de carga"],
     "evento": "frete_dedicado", "coluna": ("peso_kg", 500.0)},

    {"nome": "Dedicado: aproveita os dados mas NÃO dá valor",
     "mensagens": ["quero um bitruck de ubatuba para sao paulo, mais ou menos uns 500kg de carga"],
     "nao_espera": ["Valor estimado", "R$"],
     "evento": "frete_dedicado", "valor_preenchido": False},

    {"nome": "Atendente: frase sem rota não inventa origem nenhuma",
     "mensagens": ["quero falar com alguém"],
     "evento": "atendimento", "coluna": ("cidade_origem", "nao_informado")},

    {"nome": "Ocorrência: a rota citada no problema vai para a planilha",
     "mensagens": ["minha carga de goiania go para palmas to chegou quebrada"],
     "evento": "ocorrencia", "coluna": ("cidade_origem", "Goiânia - GO")},

    {"nome": "Dedicado no meio da cotação abandona a cotação",
     "mensagens": ["1", "goiania go", "palmas to", "450", "na verdade seria carga fechada"],
     "espera": ["frete dedicado", "protocolo"],
     "evento": "frete_dedicado"},

    {"nome": "Dedicado depois da cotação marca a MESMA linha",
     "mensagens": ["goiania go para palmas to 450kg", "pular", "e se fosse um bitruck?"],
     "espera": ["protocolo"],
     "evento": "frete_dedicado", "valor_preenchido": True},

    # ---------- Dedicado: falsos positivos ----------
    {"nome": "Falso positivo: peso superior a 100 kg não é dedicado",
     "mensagens": ["1", "goiania go", "palmas to", "peso superior a 100 kg"],
     "nao_espera": ["frete dedicado", "protocolo"],
     "evento": None},

    {"nome": "Falso positivo: cidade Tocos do Moji não é toco",
     "mensagens": ["1", "tocos do moji mg"],
     "nao_espera": ["protocolo"],
     "evento": None},

    {"nome": "Falso positivo: 3 caixas de 50x40x30 não é dedicado",
     "mensagens": ["1", "goiania go", "palmas to", "450", "3 caixas de 50x40x30"],
     "nao_espera": ["protocolo"],
     "evento": "cotacao"},

    # ---------- Pedido de desconto ----------
    {"nome": "Desconto: tem algum desconto",
     "mensagens": ["goiania go para palmas to 450kg", "pular", "tem algum desconto?"],
     "espera": ["atendente", "protocolo"],
     "evento": "atendimento", "valor_preenchido": True},

    {"nome": "Desconto: faz um precinho",
     "mensagens": ["faz um precinho pra mim?"],
     "espera": ["protocolo"],
     "evento": "atendimento", "valor_preenchido": False},

    {"nome": "Desconto: ficou salgado",
     "mensagens": ["ficou salgado esse valor"],
     "espera": ["protocolo"],
     "evento": "atendimento"},

    {"nome": "Desconto: tem como ficar mais barato",
     "mensagens": ["tem como ficar mais barato?"],
     "espera": ["protocolo"],
     "evento": "atendimento"},

    {"nome": "Desconto: valor é negociável",
     "mensagens": ["esse valor é negociável?"],
     "espera": ["protocolo"],
     "evento": "atendimento"},

    {"nome": "Desconto: comparou com a concorrência",
     "mensagens": ["consegui mais barato em outra transportadora"],
     "espera": ["protocolo"],
     "evento": "atendimento"},

    {"nome": "Falso positivo: o fracionado é mais barato NÃO é desconto",
     "mensagens": ["o fracionado é mais barato?"],
     "espera": ["divide o espaço"],
     "nao_espera": ["protocolo"],
     "evento": None},

    # ---------- Problema com a carga ----------
    {"nome": "Ocorrência: carga chegou avariada",
     "mensagens": ["a carga chegou avariada"],
     "espera": ["transtorno", "protocolo"],
     "evento": "ocorrencia"},

    {"nome": "Ocorrência: mercadoria veio quebrada",
     "mensagens": ["minha mercadoria veio quebrada"],
     "espera": ["protocolo"],
     "evento": "ocorrencia"},

    {"nome": "Ocorrência: quero reclamar",
     "mensagens": ["quero reclamar"],
     "espera": ["protocolo"],
     "evento": "ocorrencia"},

    {"nome": "Falso positivo: tem seguro contra avaria é dúvida",
     "mensagens": ["tem seguro contra avaria?"],
     "espera": ["seguro da mercadoria"],
     "nao_espera": ["protocolo"],
     "evento": None},

    # ---------- Base de conhecimento ----------
    {"nome": "FAQ: prazo é contado da coleta",
     "mensagens": ["qual o prazo de entrega?"],
     "espera": ["a partir da coleta"],
     "evento": None},

    {"nome": "Quanto custa abre uma cotação",
     "mensagens": ["quanto custa o frete?"],
     "espera": ["cidade de origem"],
     "evento": None},

    {"nome": "Quanto tempo NÃO abre uma cotação",
     "mensagens": ["em quanto tempo vocês entregam?"],
     "espera": ["a partir da coleta"],
     "nao_espera": ["cidade de origem"],
     "evento": None},

    {"nome": "FAQ: 72 horas para coletar",
     "mensagens": ["em quanto tempo vocês coletam?"],
     "espera": ["72 horas"],
     "evento": None},

    {"nome": "FAQ: prazo escrito em dias",
     "mensagens": ["em quantos dias chega?"],
     "espera": ["a partir da coleta"],
     "evento": None},

    {"nome": "FAQ: prazo com cumprimento na frente",
     "mensagens": ["oi tudo bem, em quanto tempo vocês entregam?"],
     "espera": ["a partir da coleta"],
     "evento": None},

    {"nome": "FAQ: prazo com rodeio no meio",
     "mensagens": ["em quanto tempo mais ou menos a carga chega?"],
     "espera": ["a partir da coleta"],
     "evento": None},

    {"nome": "FAQ: status da carga é rastreamento",
     "mensagens": ["qual o status da minha carga?"],
     "espera": ["rastreamento"],
     "evento": None},

    {"nome": "FAQ: limite de peso é o peso máximo",
     "mensagens": ["qual o limite de peso da carga?"],
     "espera": ["kg"],
     "evento": None},

    {"nome": "FAQ: o que está incluso",
     "mensagens": ["o que está incluso no frete?"],
     "espera": ["porta a porta", "rastreamento"],
     "evento": None},

    {"nome": "FAQ: pagamento em boleto",
     "mensagens": ["aceita boleto?"],
     "espera": ["boleto", "10 dias"],
     "evento": None},

    {"nome": "FAQ: o que é o CT-e",
     "mensagens": ["o que é o cte?"],
     "espera": ["documento fiscal do transporte"],
     "evento": None},

    {"nome": "FAQ: seguro escrito de outro jeito",
     "mensagens": ["e se a carga quebrar?"],
     "espera": ["seguro da mercadoria"],
     "nao_espera": ["protocolo"],
     "evento": None},

    {"nome": "FAQ: sinistro não cai no fracionado",
     "mensagens": ["como funciona o sinistro?"],
     "espera": ["seguro da mercadoria"],
     "evento": None},

    {"nome": "FAQ: como funciona sozinho cai no fracionado",
     "mensagens": ["como funciona?"],
     "espera": ["divide o espaço"],
     "evento": None},

    {"nome": "FAQ: diferença entre fracionado e dedicado pelo número",
     "mensagens": ["2", "2"],
     "espera": ["veículo sai só com a sua mercadoria"],
     "evento": None},

    {"nome": "FAQ: lista tem 16 dúvidas",
     "mensagens": ["2"],
     "espera": ["16. Qual o horário de atendimento"],
     "evento": None},

    # ---------- Atendente ----------
    {"nome": "Atendente: pedido claro",
     "mensagens": ["quero falar com alguém"],
     "espera": ["protocolo"],
     "evento": "atendimento", "valor_preenchido": False},

    {"nome": "Atendente: palavra solta pergunta antes",
     "mensagens": ["dono"],
     "espera": ["quer falar com um atendente"],
     "nao_espera": ["protocolo"],
     "evento": None},

    {"nome": "Atendente: palavra solta e depois SIM",
     "mensagens": ["dono", "1"],
     "espera": ["protocolo"],
     "evento": "atendimento"},

    {"nome": "Atendente: palavra solta e depois NÃO volta à conversa",
     "mensagens": ["1", "goiania go", "gerente", "2"],
     "espera": ["Vamos continuar", "cidade de destino"],
     "nao_espera": ["protocolo"],
     "evento": None},

    {"nome": "Atendente: opção 3 do menu",
     "mensagens": ["3"],
     "espera": ["protocolo"],
     "evento": "atendimento"},

    # ---------- Dúvida e insistência ----------
    {"nome": "Dúvida: não estou entendendo",
     "mensagens": ["não estou entendendo"],
     "espera": ["protocolo"],
     "evento": "duvida"},

    {"nome": "Dúvida: só interrogação",
     "mensagens": ["???"],
     "espera": ["protocolo"],
     "evento": "duvida"},

    # Travar a primeira vez NÃO encaminha: o bot oferece ajuda e o cliente decide.
    {"nome": "Insistência: ao travar a primeira vez, o bot oferece ajuda",
     "mensagens": ["1", "xxxxxxx", "xxxxxxx", "xxxxxxx"],
     "espera": ["dificuldade", "falar com um atendente"],
     "nao_espera": ["protocolo"],
     "evento": None},

    {"nome": "Insistência: aceitando a ajuda, o bot pede o nome e encaminha",
     "mensagens": ["1", "xxxxxxx", "xxxxxxx", "xxxxxxx", "1", "Eduardo"],
     "espera": ["protocolo"],
     "evento": "atendimento", "com_nome": False},

    {"nome": "Insistência: recusando a ajuda, a conversa continua de onde parou",
     "mensagens": ["1", "xxxxxxx", "xxxxxxx", "xxxxxxx", "2"],
     "espera": ["cidade de origem"],
     "nao_espera": ["protocolo"],
     "evento": None},

    {"nome": "Insistência: travando de novo, aí o bot encaminha",
     "mensagens": ["1", "xxxxxxx", "xxxxxxx", "xxxxxxx", "2",
                   "xxxxxxx", "xxxxxxx", "xxxxxxx"],
     "espera": ["protocolo"],
     "evento": "insistencia"},

    # ---------- Aprendizado ----------
    {"nome": "Pergunta sem resposta: o bot admite e oferece atendente",
     "mensagens": ["vocês emitem certificado de origem?"],
     "espera": ["não sei te responder", "quer falar com um atendente"],
     "nao_espera": ["protocolo"],
     "evento": None, "anotou": True},

    {"nome": "Pergunta sem resposta: cliente aceita o atendente",
     "mensagens": ["vocês emitem certificado de origem?", "1"],
     "espera": ["protocolo"],
     "evento": "atendimento"},

    {"nome": "Pergunta sem resposta: cliente recusa e a conversa segue",
     "mensagens": ["vocês emitem certificado de origem?", "2"],
     "espera": ["Vamos continuar", "Escolha uma opção"],
     "nao_espera": ["protocolo"],
     "evento": None},

    {"nome": "Aprendizado: pergunta desconhecida no menu é anotada",
     "mensagens": ["oi", "vocês emitem certificado de origem?"],
     "espera": ["não sei te responder"],
     "evento": None, "anotou": True},

    {"nome": "Aprendizado: pergunta respondida pelo FAQ NÃO é anotada",
     "mensagens": ["tem seguro?"],
     "evento": None, "anotou": False},

    {"nome": "Aprendizado: erro de digitação de cidade NÃO é anotado",
     "mensagens": ["1", "goiania gooooo"],
     "evento": None, "anotou": False},

    {"nome": "Aprendizado: pergunta no meio da cotação é anotada",
     "mensagens": ["1", "goiania go", "palmas to", "vocês emitem certificado de origem?"],
     "evento": None, "anotou": True},

    {"nome": "FAQ: palavra ampla no meio da frase NÃO responde",
     "mensagens": ["oi", "vocês fazem entrega em condomínio?"],
     "espera": ["não sei te responder"],
     "nao_espera": ["a partir da coleta"],
     "evento": None, "anotou": True},

    # "quanto tempo" é palavra de prazo, mas aqui o assunto é outro: o bot não
    # pode responder o prazo de entrega. Tem que admitir que não sabe e anotar.
    {"nome": "FAQ: prazo de OUTRO assunto NÃO recebe a resposta de entrega",
     "mensagens": ["oi", "o certificado de origem é emitido em quanto tempo?"],
     "espera": ["não sei te responder", "quer falar com um atendente"],
     "nao_espera": ["a partir da coleta"],
     "evento": None, "anotou": True},

    {"nome": "FAQ: prazo para emitir nota NÃO é prazo de entrega",
     "mensagens": ["oi", "quanto tempo demora para emitir a nota?"],
     "espera": ["não sei te responder"],
     "nao_espera": ["a partir da coleta"],
     "evento": None, "anotou": True},

    {"nome": "FAQ: limite de crédito NÃO é peso máximo",
     "mensagens": ["oi", "qual o limite de crédito da empresa?"],
     "espera": ["não sei te responder"],
     "nao_espera": ["peso cubado", "peso real"],
     "evento": None, "anotou": True},

    {"nome": "FAQ: transportam geladeira vira pergunta nova",
     "mensagens": ["oi", "vocês transportam geladeira?"],
     "espera": ["não sei te responder"],
     "nao_espera": ["todo o Brasil"],
     "evento": None, "anotou": True},

    {"nome": "Pergunta no meio da cotação: admite, mas não larga a cotação",
     "mensagens": ["1", "goiania go", "palmas to", "vocês emitem certificado de origem?"],
     "espera": ["não sei te responder", "ATENDENTE", "Peso Total"],
     "nao_espera": ["protocolo"],
     "evento": None, "anotou": True},

    {"nome": "FAQ: entrega no sábado vira pergunta nova",
     "mensagens": ["oi", "vocês entregam no sábado?"],
     "nao_espera": ["a partir da coleta"],
     "evento": None, "anotou": True},

    {"nome": "FAQ: palavra ampla em mensagem curta ainda responde",
     "mensagens": ["oi", "vocês entregam?"],
     "espera": ["a partir da coleta"],
     "evento": None, "anotou": False},

    {"nome": "FAQ: que horas vocês abrem",
     "mensagens": ["que horas vocês abrem?"],
     "espera": ["atendimento funciona"],
     "evento": None},

    # ---------- Aprendizado: o que NÃO pode virar linha ----------
    {"nome": "Lixo: mensagem com CNPJ não é anotada",
     "mensagens": ["oi", "meu cnpj é 12.345.678/0001-90 pode cadastrar?"],
     "evento": None, "anotou": False},

    {"nome": "Lixo: mensagem com e-mail não é anotada",
     "mensagens": ["oi", "pode mandar para fulano@empresa.com depois?"],
     "evento": None, "anotou": False},

    {"nome": "Lixo: mensagem com telefone não é anotada",
     "mensagens": ["oi", "me chama no (61) 99999-8888 por favor"],
     "evento": None, "anotou": False},

    {"nome": "Lixo: link não é anotado",
     "mensagens": ["oi", "o endereço é esse https://maps.app.goo.gl/abcdef"],
     "evento": None, "anotou": False},

    {"nome": "Lixo: agradecimento não é anotado",
     "mensagens": ["oi", "valeu"],
     "evento": None, "anotou": False},

    {"nome": "Lixo: só emoji não é anotado",
     "mensagens": ["oi", "👍"],
     "evento": None, "anotou": False},

    {"nome": "Lixo: dia da semana não é anotado",
     "mensagens": ["oi", "quinta-feira"],
     "evento": None, "anotou": False},

    {"nome": "Lixo: peso solto não é anotado",
     "mensagens": ["oi", "22 toneladas"],
     "evento": None, "anotou": False},

    {"nome": "Lixo: cidade solta com interrogação não é anotada",
     "mensagens": ["oi", "goiania?"],
     "evento": None, "anotou": False},

    {"nome": "Lixo: mensagem comprida demais não é anotada",
     "mensagens": ["oi", "bom dia preciso de uma coleta amanha cedo no galpao do cliente "
                         "que fica depois do posto na entrada da cidade e a carga sao varias "
                         "caixas de tamanhos diferentes que ainda estao sendo separadas pela "
                         "equipe do deposito entao talvez mude ate la"],
     "evento": None, "anotou": False},

    {"nome": "Pergunta que CITA uma cidade continua sendo anotada",
     "mensagens": ["oi", "vocês têm filial em goiania?"],
     "evento": None, "anotou": True},

    {"nome": "Mesma pergunta repetida conta uma vez só",
     "mensagens": ["oi", "vocês emitem certificado de origem?",
                   "vocês emitem certificado de origem?"],
     "evento": None, "anotou_quantas": 1},

    # ---------- Aprendizado: a resposta aprovada entra em uso ----------
    {"nome": "Aprendizado: resposta aprovada na planilha é usada",
     "mensagens": ["oi", "vocês emitem certificado de origem?"],
     "aprovadas": {"vocês emitem certificado de origem?":
                   "Sim, emitimos o certificado de origem junto com o CT-e."},
     "espera": ["certificado de origem junto com o CT-e"],
     "evento": None, "anotou": False},

    {"nome": "Aprendizado: resposta aprovada vale para outro jeito de perguntar",
     "mensagens": ["oi", "tem como emitir certificado de origem?"],
     "aprovadas": {"vocês emitem certificado de origem?":
                   "Sim, emitimos o certificado de origem junto com o CT-e."},
     "espera": ["certificado de origem junto com o CT-e"],
     "evento": None, "anotou": False},

    {"nome": "Aprendizado: resposta aprovada NÃO invade outra pergunta",
     "mensagens": ["oi", "qual o prazo de entrega?"],
     "aprovadas": {"vocês emitem certificado de origem?":
                   "Sim, emitimos o certificado de origem junto com o CT-e."},
     "espera": ["a partir da coleta"],
     "nao_espera": ["certificado"],
     "evento": None},

    # ---------- Comandos ----------
    {"nome": "MENU volta para o início a qualquer momento",
     "mensagens": ["1", "goiania go", "menu"],
     "espera": ["Escolha uma opção"],
     "evento": None},

    {"nome": "Áudio recebe aviso de que o bot só lê texto",
     "mensagens": ["1", "goiania go", "/audio"],
     "espera": ["mensagens escritas"],
     "evento": None},
]


# =================================================================
# Execução
# =================================================================
def conferir_textos_do_bot():
    """
    Confere que NENHUMA mensagem do bot traz um CNPJ válido como exemplo.
    Se trouxesse, bastaria o cliente copiar o exemplo para passar pela porta de
    entrada, e a exigência do CNPJ não serviria para nada.
    Devolve a lista de problemas encontrados (vazia quando está tudo certo).
    """
    textos = {
        "TEXTO_PEDIR_CNPJ": conversa.TEXTO_PEDIR_CNPJ,
        "TEXTO_CNPJ_INVALIDO": conversa.TEXTO_CNPJ_INVALIDO,
        "TEXTO_CNPJ_COM_MASCARA": conversa.TEXTO_CNPJ_COM_MASCARA,
    }
    problemas = []
    for nome, texto in textos.items():
        for pedaco in re.findall(r"[0-9A-Za-z./-]{14,20}", texto):
            if cnpj.valido(pedaco):
                problemas.append(f"{nome} traz um CNPJ VÁLIDO como exemplo: {pedaco}")
    return problemas


# Os únicos emojis que o bot pode usar numa mensagem para o cliente: os números
# das opções. Eles não são enfeite, são a instrução do que digitar.
EMOJIS_PERMITIDOS = ("1️⃣", "2️⃣", "3️⃣")


def _mensagens_para_o_cliente():
    """Junta todas as mensagens que o bot pode mandar para o cliente."""
    textos = {nome: getattr(conversa, nome) for nome in dir(conversa)
              if nome.startswith("TEXTO_") and isinstance(getattr(conversa, nome), str)}
    textos["OPCOES_POS_COTACAO"] = conversa.OPCOES_POS_COTACAO
    for etapa, pergunta in conversa.PERGUNTAS.items():
        textos[f"PERGUNTAS[{etapa}]"] = pergunta
    for etapa, pedido in conversa.NOMES.items():
        textos[f"NOMES[{etapa}]"] = pedido
    textos["texto_menu()"] = conversa.texto_menu()
    textos["texto_convite()"] = conversa.texto_convite({})
    textos["faq.texto_lista()"] = faq.texto_lista()
    for numero, duvida in enumerate(faq.DUVIDAS, start=1):
        textos[f"resposta da dúvida {numero}"] = duvida["resposta"]
    return textos


def conferir_voz_do_bot():
    """
    Confere o jeito de falar do bot, que foi decidido de propósito:
      - sem abreviação de internet ("vc"): quem escreve pelo WhatsApp da empresa
        é uma pessoa, e o tratamento é "você" por extenso;
      - sem emoji de enfeite: ficam só os números das opções, que servem para o
        cliente saber o que digitar. Emoji solto deixa a conversa com cara de robô.
    Devolve a lista de problemas encontrados (vazia quando está tudo certo).
    """
    problemas = []
    for nome, texto in _mensagens_para_o_cliente().items():
        if re.search(r"\bvcs?\b", texto, re.IGNORECASE):
            problemas.append(f'{nome} usa "vc" em vez de "você"')
        limpo = texto
        for permitido in EMOJIS_PERMITIDOS:
            limpo = limpo.replace(permitido, "")
        sobrando = sorted({caractere for caractere in limpo if ord(caractere) >= 0x2190})
        if sobrando:
            problemas.append(f"{nome} tem emoji de enfeite: {' '.join(sobrando)}")
    return problemas


def rodar_caso(numero, caso):
    """Roda um caso e devolve (passou, motivo, última resposta)."""
    conversa.sessoes.clear()
    cep.limpar_cache()
    PlanilhaDeMentira.ultima = None
    Telegram.ultima = None
    Telegram.ultimo_link = None
    AprendizadoDeMentira.anotadas = []
    AprendizadoDeMentira.aprovadas = dict(caso.get("aprovadas", {}))
    telefone = f"55619{numero:08d}"

    # A conversa começa pedindo o CNPJ e depois o nome. Nos casos que não estão
    # testando essas duas portas, o teste já entra com as duas respondidas, para
    # medir só o que interessa.
    inicial = {"etapa": "inicio", "dados": {}, "ultima": MOMENTO}
    if caso.get("com_cnpj", True):
        inicial["cnpj"] = CNPJ_DE_TESTE
    if caso.get("com_nome", True):
        inicial["nome"] = NOME_DE_TESTE
    if "cnpj" in inicial or "nome" in inicial:
        conversa.sessoes[telefone] = inicial

    resposta = ""
    momento = MOMENTO
    for mensagem in caso["mensagens"]:
        if mensagem.startswith("/esperar"):
            # finge que passou esse tanto de minutos, para testar a conversa que expira
            momento += timedelta(minutes=int(mensagem.split()[1]))
            continue
        if mensagem == "/audio":
            resposta = conversa.responder_nao_texto(telefone, momento) or ""
        else:
            resposta = conversa.responder(telefone, mensagem, momento) or ""

    texto = simplificar(resposta)
    problemas = []

    for pedaco in caso.get("espera", []):
        if simplificar(pedaco) not in texto:
            problemas.append(f'faltou "{pedaco}"')

    for pedaco in caso.get("nao_espera", []):
        if simplificar(pedaco) in texto:
            problemas.append(f'não podia ter "{pedaco}"')

    linha = PlanilhaDeMentira.ultima
    evento_gravado = linha["evento"] if linha else None
    if caso["evento"] != evento_gravado:
        problemas.append(f'evento era "{caso["evento"]}" e veio "{evento_gravado}"')

    if "valor_preenchido" in caso:
        preenchido = bool(linha and linha.get("valor"))
        if preenchido != caso["valor_preenchido"]:
            esperado = "preenchido" if caso["valor_preenchido"] else "vazio"
            problemas.append(f"a coluna valor devia estar {esperado}")

    if "anotou_quantas" in caso:
        quantas = len(AprendizadoDeMentira.anotadas)
        if quantas != caso["anotou_quantas"]:
            problemas.append(f'era para anotar {caso["anotou_quantas"]} e anotou {quantas}')

    if "anotou" in caso:
        anotou = bool(AprendizadoDeMentira.anotadas)
        if anotou != caso["anotou"]:
            esperado = "anotar a pergunta" if caso["anotou"] else "NÃO anotar a pergunta"
            problemas.append(f"era para {esperado}")

    for pedaco in caso.get("alerta", []):
        if simplificar(pedaco) not in simplificar(Telegram.ultima or ""):
            problemas.append(f'faltou "{pedaco}" no alerta do Telegram')

    if "alerta_link" in caso and Telegram.ultimo_link != caso["alerta_link"]:
        problemas.append(f'o botão do alerta abriria "{Telegram.ultimo_link}"')

    if "coluna" in caso:
        nome_coluna, esperado = caso["coluna"]
        veio = linha.get(nome_coluna) if linha else None
        if veio != esperado:
            problemas.append(f'{nome_coluna} era "{esperado}" e veio "{veio}"')

    return (not problemas), "; ".join(problemas), resposta


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--detalhe", action="store_true", help="mostra a resposta de cada caso")
    parser.add_argument("--csv", action="store_true", help="salva resultado_dos_testes.csv")
    args = parser.parse_args()

    print("=" * 72)
    print(f"TESTE AUTOMÁTICO DO CHATBOT — {len(CASOS)} casos")
    print("(nada é enviado ao Telegram e nada é gravado na planilha)")
    print("=" * 72)

    resultados = []
    falhas = 0

    # Duas conferências que não são conversas: os textos do bot não podem trazer
    # um CNPJ válido de exemplo, e precisam seguir o jeito de falar combinado.
    problemas_de_texto = conferir_textos_do_bot()
    print(("OK    " if not problemas_de_texto else "FALHOU") +
          "   0. Nenhuma mensagem do bot traz um CNPJ válido de exemplo")
    for problema in problemas_de_texto:
        print(f"            {problema}")
        falhas += 1

    problemas_de_voz = conferir_voz_do_bot()
    print(("OK    " if not problemas_de_voz else "FALHOU") +
          "   0. Mensagens sem abreviação e sem emoji de enfeite")
    for problema in problemas_de_voz:
        print(f"            {problema}")
        falhas += 1

    for numero, caso in enumerate(CASOS, start=1):
        passou, motivo, resposta = rodar_caso(numero, caso)
        if not passou:
            falhas += 1
        marca = "OK    " if passou else "FALHOU"
        print(f"{marca} {numero:3}. {caso['nome']}")
        if motivo:
            print(f"            {motivo}")
        if args.detalhe:
            print("            " + resposta.replace("\n", "\n            ")[:600] + "\n")
        resultados.append({"numero": numero, "caso": caso["nome"],
                           "resultado": "ok" if passou else "falhou", "motivo": motivo})

    total = len(CASOS) + 2          # os casos, mais as duas conferências de texto
    acertos = total - falhas
    print("=" * 72)
    print(f"RESULTADO: {acertos} de {total} casos passaram ({acertos / total * 100:.1f}%)")
    if falhas:
        print(f"{falhas} caso(s) falharam. O detalhe de cada um está acima.")
    else:
        print("Nenhuma falha.")
    print("=" * 72)

    if args.csv:
        with open("resultado_dos_testes.csv", "w", newline="", encoding="utf-8-sig") as arquivo:
            escritor = csv.DictWriter(arquivo, fieldnames=["numero", "caso", "resultado", "motivo"])
            escritor.writeheader()
            escritor.writerows(resultados)
        print("Resultado salvo em resultado_dos_testes.csv")

    # Código de saída 1 quando algo falhou: serve para rodar isso automaticamente um dia
    sys.exit(1 if falhas else 0)


if __name__ == "__main__":
    main()