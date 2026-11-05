"""
Guarda cada cotação (ou pedido de atendimento) na planilha "cotacoes_registradas",
que fica na pasta de dados do Google Drive.

Por quê? Com o tempo, essa planilha vira uma base de dados valiosa:
quantas cotações foram feitas, para quais rotas, quantas viraram
contato com uma pessoa e com que frequência as cargas são volumosas.

Por que no Drive e não num arquivo do servidor?
  O disco do Render gratuito é apagado a cada reinício. No Drive, o
  histórico fica guardado para sempre, e o dono pode abrir a planilha
  a qualquer momento.

Regra: UMA LINHA POR CONVERSA DE COTAÇÃO.
  A linha é criada quando o bot mostra a cotação, com evento = cotacao e
  protocolo = nao_se_aplica.
  Se a conversa mudar de rumo depois disso (o cliente pedir um atendente, pedir
  desconto, falar de frete dedicado, relatar um problema), o bot volta NA MESMA
  LINHA, preenche o protocolo e TROCA o evento pelo novo. Ou seja, o evento guarda
  como a conversa terminou, e não só como ela começou.
  Se o cliente pedir atendente sem ter feito cotação, é criada uma linha nova
  com evento = atendimento.

  Como saber se houve cotação, mesmo quando o evento mudou? A coluna valor.
  Valor preenchido = o cliente chegou a ver uma cotação.
  Como saber QUEM decidiu chamar o atendente? O próprio evento:
    atendimento                       -> o CLIENTE pediu
    frete_dedicado, ocorrencia,
    carga_volumosa, insistencia,
    duvida                            -> o BOT decidiu

Colunas (a primeira linha da planilha tem estes títulos, nesta ordem):
  data_hora                    -> quando aconteceu (AAAA-MM-DD HH:MM)                 [sempre preenchida]
  telefone                     -> WhatsApp do cliente                                 [sempre preenchida]
  cnpj                         -> CNPJ da empresa do cliente, já com máscara          [sempre preenchida]
                                  Ex.: 11.222.333/0001-81. Quando não foi informado: nao_informado.
                                  O bot confere só os dígitos verificadores: isso diz que o número é
                                  bem formado, e NÃO que a empresa existe. Quem confere o cadastro
                                  é o atendente.
  protocolo                    -> ex.: ATD-24102026-2111-WQ, ou nao_se_aplica          [sempre preenchida]
  cidade_origem                -> ex.: "Goiânia - GO", ou nao_informado                [sempre preenchida]
  cep_origem                   -> ex.: "74486-225", ou nao_informado                   [sempre preenchida]
  cidade_destino               -> ex.: "Palmas - TO", ou nao_informado                 [sempre preenchida]
  cep_destino                  -> ex.: "39948-000", ou nao_informado                   [sempre preenchida]
                                  Cidade e CEP guardam o que o CLIENTE informou, e não o que
                                  o bot descobriu. Quem pede por cidade preenche a coluna da
                                  cidade; quem pede por CEP preenche a coluna do CEP. O bot
                                  descobre a cidade do CEP só para calcular a distância.
                                  A rota NÃO mistura: ou as duas colunas de cidade estão
                                  preenchidas, ou as duas de CEP, nunca metade de cada.
                                  Quem decide é o primeiro lado que o cliente informar.
  distancia_km                 -> número (vazio quando não houve cotação)
  peso_kg                      -> número (vazio quando o cliente não informou)
  qtd_transportada             -> número de volumes que o CLIENTE informou, ex.: 3
                                  (vazio quando ele pulou as medidas ou mandou só "50x40x30" sem dizer
                                  quantos volumes; nesse caso o bot calcula como 1 volume, mas não registra)
  preenchimento_qtd_transportada -> informado / nao_informado                       [sempre preenchida]
  medidas                      -> ex.: "50x40x30 cm" (vazio quando o cliente pulou)
  peso_cubado_kg               -> número (vazio quando não há medidas)
  preenchimento_medidas_cubado -> informado / nao_informado                         [sempre preenchida]
  peso_considerado_kg          -> número, o maior entre o peso real e o cubado (vazio quando não houve cotação)
  valor                        -> número, valor da tabela (vazio quando não houve cotação)
  evento                       -> o que aconteceu de mais relevante na conversa     [sempre preenchida]
                                  cotacao        = o bot mostrou a cotação e parou por aí
                                  atendimento    = o CLIENTE pediu para falar com um atendente
                                                   (inclusive pedido de desconto)
                                  cnpj           = cliente é pessoa física, ou não informou um CNPJ
                                                   válido nas tentativas
                                  frete_dedicado = cliente quis um veículo só para a carga dele
                                                   (o bot cota só o fracionado)
                                  ocorrencia     = cliente relatou problema com uma carga já enviada
                                                   (avaria, extravio, reclamação)
                                  carga_volumosa = peso acima do limite: foi direto para o atendente
                                  insistencia    = o bot não conseguiu ajudar 3 vezes seguidas
                                  duvida         = o cliente mostrou dúvida ("não estou entendendo", "?")

Boa prática para análise de dados (cada coluna tem UM tipo só):
  - colunas de TEXTO obrigatórias nunca ficam vazias: usam nao_informado ou nao_se_aplica;
  - colunas de NÚMERO nunca recebem 0 no lugar do vazio: vazio vira NaN no pandas e é
    ignorado nas médias e somas (um 0 entraria na conta e distorceria o resultado);
  - todo vazio tem explicação em outra coluna (preenchimento_qtd_transportada,
    preenchimento_medidas_cubado, evento).

Atenção (LGPD): o telefone e o nome do cliente são dados pessoais. A planilha
fica numa pasta privada do Drive, compartilhada só com a conta robô do bot.
"""
import threading

import todos_config as config
import todos_drive as drive

COLUNAS = ["data_hora", "telefone", "cnpj", "protocolo",
           "cidade_origem", "cep_origem", "cidade_destino", "cep_destino",
           "distancia_km", "peso_kg",
           "qtd_transportada", "preenchimento_qtd_transportada", "medidas", "peso_cubado_kg",
           "preenchimento_medidas_cubado",
           "peso_considerado_kg", "valor", "evento"]


def _letra_da_coluna(nome):
    """'protocolo' -> 'C' (posição da coluna na planilha, contando de A)."""
    return chr(ord("A") + COLUNAS.index(nome))


class Registro:
    """
    Uma linha da planilha. A gravação roda "em paralelo" (thread), para o cliente
    não esperar o Google responder antes de receber a mensagem do bot.
    """

    def __init__(self, dados):
        self.linha = None   # número da linha na planilha, preenchido depois de gravar
        valores = ["" if dados.get(coluna) is None else dados.get(coluna) for coluna in COLUNAS]
        # daemon=False: se o programa for fechado (ex.: /sair no simulador),
        # o Python espera a gravação terminar antes de fechar, e nenhuma linha se perde.
        self._gravacao = threading.Thread(target=self._gravar, args=(valores,), daemon=False)
        self._gravacao.start()

    def _gravar(self, valores):
        try:
            self.linha = drive.acrescentar_linha(config.NOME_PLANILHA_REGISTRO, valores)
        except Exception as erro:
            # O registro não pode travar o atendimento: se o Drive falhar,
            # o cliente continua sendo atendido e o erro aparece no log.
            print(f"[REGISTRO] Não consegui gravar a linha no Drive ({erro}): {valores}")

    def marcar_evento(self, protocolo, evento):
        """
        A conversa mudou de rumo depois da cotação: preenche o protocolo e troca
        o evento desta linha (atendimento, frete_dedicado, ocorrencia...).
        """
        threading.Thread(target=self._atualizar, args=(protocolo, evento), daemon=False).start()

    def _atualizar(self, protocolo, evento):
        self._gravacao.join()          # espera a linha terminar de ser criada
        if self.linha is None:         # não sabemos em qual linha a cotação ficou
            print("[REGISTRO] Não consegui atualizar o evento: a linha da cotação não foi "
                  "gravada ou o todos_drive.py não informou o número da linha.")
            return
        try:
            drive.atualizar_celulas(config.NOME_PLANILHA_REGISTRO, {
                f"{_letra_da_coluna('protocolo')}{self.linha}": protocolo,
                f"{_letra_da_coluna('evento')}{self.linha}": evento,
            })
        except Exception as erro:
            print(f"[REGISTRO] Não consegui atualizar o evento na linha {self.linha} ({erro}).")


def registrar(dados):
    """Cria a linha na planilha do Drive e devolve o Registro (para atualizar depois)."""
    return Registro(dados)