"""
Converse com o chatbot pelo terminal, sem WhatsApp.

Como usar:
    python teste_simulador.py              -> usa o horário atual
    python teste_simulador.py --hora 22    -> finge que são 22h (testar fora do horário)

Comandos do simulador:
    /novo       -> começa como um cliente novo (outro telefone)
    /esperar 10 -> finge que o cliente ficou 10 minutos sem responder (para ver o lembrete automático)
    /audio      -> finge que o cliente mandou um áudio
    /sair       -> encerra
"""
import argparse
from datetime import timedelta

import todos_conversa as conversa

parser = argparse.ArgumentParser()
parser.add_argument("--hora", type=int, help="finge que é essa hora do dia (0 a 23)")
args = parser.parse_args()

minutos_passados = 0   # tempo "fingido" com o comando /esperar


def momento_atual():
    agora = conversa.agora_brasilia()
    if args.hora is not None:
        agora = agora.replace(hour=args.hora)
    return agora + timedelta(minutes=minutos_passados)


def mostrar(resposta):
    if resposta is None:
        # Cliente já está com o atendente e o protocolo foi lembrado há pouco
        print("(bot não respondeu — protocolo já lembrado há pouco; digite MENU para voltar)\n")
    else:
        print(f"\nBot:\n{resposta}\n")


telefone = "5561900000001"
print("=== Simulador do chatbot Deflo Express ===")
print("Digite como se fosse o cliente.")
print("/novo = cliente novo | /esperar 10 = passar 10 min | /audio = mandar áudio | /sair = encerrar\n")

while True:
    texto = input("Cliente: ")

    if texto == "/sair":
        break

    if texto == "/novo":
        telefone = str(int(telefone) + 1)
        print(f"(novo cliente: {telefone})\n")
        continue

    if texto.startswith("/esperar"):
        partes = texto.split()
        minutos = int(partes[1]) if len(partes) > 1 and partes[1].isdigit() else conversa.config.LEMBRETE_MIN
        minutos_passados += minutos
        print(f"(passaram {minutos} minutos...)")
        lembretes = conversa.verificar_lembretes(momento_atual())
        if not lembretes:
            print("(nenhum lembrete enviado)\n")
        for tel, mensagem in lembretes:
            print(f"\nBot (lembrete automático para {tel}):\n{mensagem}\n")
        continue

    if texto == "/audio":
        mostrar(conversa.responder_nao_texto(telefone, momento_atual()))
        continue

    mostrar(conversa.responder(telefone, texto, momento_atual()))