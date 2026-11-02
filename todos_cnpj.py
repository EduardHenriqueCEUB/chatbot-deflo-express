"""
Conferência do CNPJ que o cliente digita.

Para que serve:
  A empresa trabalha só com outras empresas (CNPJ). Antes de passar uma cotação,
  o bot pede o CNPJ e confere se o número está bem formado.

O que esta conferência FAZ:
  Confere os dois últimos dígitos, chamados dígitos verificadores. Eles são
  calculados a partir dos outros doze por uma conta fixa (módulo 11). É a mesma
  conta que a Receita usa. Com isso:
    - erro de digitação é reprovado quase sempre (é para isso que eles existem);
    - número batido ao acaso é reprovado em 99 das 100 vezes, porque a chance de
      acertar os dois dígitos por sorte é de 1 em 100.

O que esta conferência NÃO FAZ, e isso precisa ficar claro:
  Ela NÃO diz que a empresa existe, nem que o CNPJ é de quem está falando.
  Ela diz só que o número é bem formado. É parecido com conferir se um e-mail
  tem arroba: o arroba estar lá não quer dizer que a caixa exista.
  A conferência cadastral (existe? está ativa? é dessa empresa?) é feita pelo
  atendente, que recebe o CNPJ no alerta do Telegram e na planilha.
  Para isso não depender de internet nem de serviço de terceiro, o bot NÃO
  consulta nenhuma API. Assim ele nunca barra uma empresa recém-aberta só
  porque uma base externa ainda não foi atualizada.

CNPJ alfanumérico:
  Desde julho de 2026, os CNPJs NOVOS podem ter letras nos doze primeiros
  caracteres (ex.: 12.ABC.345/01DE-35). Os CNPJs antigos, só com números,
  continuam valendo. Por isso esta conferência aceita os dois formatos.
  A conta é a mesma: cada caractere vira um número pelo código ASCII menos 48
  (então '0' vale 0, '9' vale 9, 'A' vale 17, 'B' vale 18, e assim por diante).
  Os DOIS últimos caracteres são sempre números, nunca letras.

Como o cliente digita e como fica guardado:
  No atendimento, o bot pede os 14 caracteres SEM ponto, barra ou traço, para
  todo mundo responder do mesmo jeito. Na planilha e no alerta do Telegram, o
  próprio código coloca a máscara de volta. Assim a conversa é simples e o dado
  sai padronizado.

Funções:
  limpar(texto)        -> tira pontuação e deixa maiúsculo: '12.345.678/0001-95' -> '12345678000195'
  sem_pontuacao(texto) -> True se o cliente digitou só os 14 caracteres, sem máscara
  valido(texto)        -> True se os dígitos verificadores batem
  formatar(texto)      -> devolve com a máscara: '12345678000195' -> '12.345.678/0001-95'
  achar_no_texto(texto)-> acha os CNPJs dentro de uma mensagem maior, como o cliente escreveu
  distintos_no_texto(texto) -> os mesmos, sem repetir e já limpos
"""
import re

TAMANHO = 14
# Pesos da conta, do jeito que a Receita define. O primeiro dígito usa 12 pesos,
# o segundo usa 13 (porque já inclui o primeiro dígito no cálculo).
PESOS_PRIMEIRO = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
PESOS_SEGUNDO = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]


def limpar(texto):
    """Deixa só letras e números, em maiúsculas. Tira ponto, barra e traço."""
    return re.sub(r"[^0-9A-Z]", "", str(texto).upper())


# Os 14 caracteres, sem nada no meio: é assim que o bot pede no atendimento.
REGEX_SO_CARACTERES = re.compile(r"^[0-9A-Z]{14}$")


def sem_pontuacao(texto):
    """
    True quando o cliente digitou só os caracteres, do jeito que o bot pede.
      '11222333000181'     -> True
      '11.222.333/0001-81' -> False (tem máscara)
      '11222333000181 '    -> True  (espaço nas pontas não conta)
    """
    return bool(REGEX_SO_CARACTERES.match(str(texto).strip().upper()))


def _valor(caractere):
    """Converte o caractere em número: '0' -> 0, '9' -> 9, 'A' -> 17, 'B' -> 18..."""
    return ord(caractere) - 48


def _digito(caracteres, pesos):
    """Calcula um dígito verificador pela regra do módulo 11."""
    soma = sum(_valor(c) * peso for c, peso in zip(caracteres, pesos))
    resto = soma % 11
    return 0 if resto < 2 else 11 - resto


def valido(texto):
    """
    True quando o CNPJ está bem formado e os dígitos verificadores batem.
      '11.222.333/0001-81' -> True
      '11222333000182'     -> False (último dígito errado)
      '12345678901234'     -> False
      '00000000000000'     -> False (todos iguais, recusado de propósito)
    """
    limpo = limpar(texto)
    if len(limpo) != TAMANHO:
        return False
    if limpo == limpo[0] * TAMANHO:          # 000..., 111..., passam na conta mas não existem
        return False
    base, digitos = limpo[:12], limpo[12:]
    if not digitos.isdigit():                # os dois últimos são sempre números
        return False

    primeiro = _digito(base, PESOS_PRIMEIRO)
    segundo = _digito(base + str(primeiro), PESOS_SEGUNDO)
    return digitos == f"{primeiro}{segundo}"


# Um CNPJ dentro de uma mensagem maior. O cliente escreve de muitos jeitos:
#   45053805000131          (os 14 seguidos)
#   45.053.805/0001-31      (com a máscara certa)
#   309781170001/05         (com a barra fora do lugar, mas é um CNPJ de verdade)
# Por isso o bot não procura um formato exato: ele pega qualquer pedaço colado
# feito de letras, números, ponto, barra e traço, limpa e vê se sobram 14
# caracteres que passam na conta do dígito verificador.
REGEX_CANDIDATO = re.compile(
    r"(?<![0-9A-Za-z])[0-9A-Za-z][0-9A-Za-z./-]{10,24}[0-9A-Za-z](?![0-9A-Za-z])")


def achar_no_texto(texto):
    """
    Acha os CNPJs que estão dentro de uma mensagem maior, DO JEITO QUE O CLIENTE
    ESCREVEU, na ordem em que aparecem, sem tirar os repetidos.

    Para que serve: muito cliente manda o pedido todo numa mensagem só, com os
    CNPJs do pagador, do remetente e do destinatário numa lista. O bot mostra a
    lista de volta para o cliente escolher, e ela precisa ser igual à que ele
    escreveu, senão ele não reconhece qual é qual.

    Só entram os que passam na conta do dígito verificador. Um pedaço qualquer
    de 14 caracteres tem 1 chance em 100 de passar, então telefone, CEP, data,
    valor e número de protocolo não viram CNPJ por acidente.
    """
    return [pedaco for pedaco in REGEX_CANDIDATO.findall(str(texto)) if valido(pedaco)]


def distintos_no_texto(texto):
    """Os CNPJs achados, sem repetir, já limpos. Serve para contar quantos são de verdade."""
    vistos = []
    for achado in achar_no_texto(texto):
        limpo = limpar(achado)
        if limpo not in vistos:
            vistos.append(limpo)
    return vistos


def formatar(texto):
    """'12345678000195' -> '12.345.678/0001-95'. Devolve o texto original se não der."""
    limpo = limpar(texto)
    if len(limpo) != TAMANHO:
        return str(texto).strip()
    return f"{limpo[:2]}.{limpo[2:5]}.{limpo[5:8]}/{limpo[8:12]}-{limpo[12:]}"


if __name__ == "__main__":
    # Teste rápido: python todos_cnpj.py
    exemplos = ["11222333000181", "11.222.333/0001-81", "11222333000182",
                "12345678901234", "00000000000000", "123", "abc", "12ABC34501DE35"]
    for exemplo in exemplos:
        certo = valido(exemplo)
        situacao = "válido" if certo else "INVÁLIDO"
        aviso = "  (o bot pediria sem a máscara)" if certo and not sem_pontuacao(exemplo) else ""
        print(f"{exemplo:22} -> {situacao}{aviso}")