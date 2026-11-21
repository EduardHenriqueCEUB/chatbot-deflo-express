# Chatbot Deflo Express

Bot de WhatsApp, feito em Python, que atende os clientes da Deflo Express.

* Faz a **cotação de frete fracionado** (cargas de até 1.000 kg) para **qualquer cidade do Brasil**, usando a tabela de preços da empresa.
* Responde as **dúvidas mais comuns** e aprende respostas novas com a ajuda de uma pessoa.
* Usa a **IA do Google (Gemini)** só onde as regras não entendem. A IA nunca dá preço: o valor sai sempre da tabela.
* Chama um **atendente pelo Telegram** quando o cliente precisa de uma pessoa, com um **número de protocolo**.
* Avisa no Telegram quando chega um **e-mail novo** na caixa da empresa.

**OBS.:** Os arquivos `teste_` e `producao_` usam os mesmos arquivos `todos_`. Assim, tudo o que é corrigido no teste já vale na produção, e nenhuma correção se perde.

################################################################################################

##############################
####### ANTES DE COMEÇAR #######
##############################

1 - Instale as bibliotecas:

```
python -m pip install -r requirements.txt
```

2 - Guarde a chave da conta robô do Google (arquivo `.json`) numa pasta segura do computador, **fora** da pasta do projeto.

3 - Copie o `.env_exemplo`, renomeie a cópia para `.env` e preencha as senhas.

4 - Os dados da empresa (tabela de preços, lista de cidades e planilhas) **não ficam no GitHub**: ficam numa pasta privada do Google Drive, e o bot busca de lá.

Nos comandos deste guia, troque os textos em maiúsculas pelos seus:

* `SEU-ENDERECO.ngrok-free.dev` → o seu endereço fixo, no painel do ngrok, em **Domains**.
* `ID_DA_CONTA` → o "ID da conta do WhatsApp Business", no painel da Meta, na **Etapa 2**.

################################################################################################

####################################
####### O QUE CADA ARQUIVO FAZ #######
####################################

Arquivos que **só servem para ser lidos** pelo bot dizem "Não roda sozinho". Os outros mostram o comando para rodar no terminal, dentro da pasta do projeto.

################################################################################################

### Configuração e senhas

#### `.env_exemplo`
* **Para que serve:** modelo do arquivo de senhas. Mostra todas as senhas que o projeto precisa, com os campos em branco.
* **Como usar:** copie, renomeie a cópia para `.env` e preencha. O `.env` de verdade **nunca** vai para o GitHub.

#### `.gitignore`
* **Para que serve:** lista do que o Git nunca pode mandar para o GitHub: o `.env`, a chave do Google (`.json`) e a pasta `dados/`.
* **Como usar:** não roda. O Git lê sozinho.

#### `requirements.txt`
* **Para que serve:** lista das bibliotecas do Python que o projeto usa, nas versões testadas. O Render também usa essa lista.
* **Como usar:** `python -m pip install -r requirements.txt`

#### `todos_config.py`
* **Para que serve:** todas as regras do bot num lugar só: horário de atendimento, peso máximo, fator de cubagem, se exige CNPJ, quantas tentativas antes de chamar o atendente, e o interruptor da IA (`IA_LIGADA`).
* **Como usar:** não roda sozinho. Para mudar uma regra, mude aqui.

################################################################################################

### A conversa

#### `todos_conversa.py`
* **Para que serve:** o "cérebro" do bot. Conduz a conversa, pede o CNPJ e o primeiro nome, junta origem, destino, peso e medidas, faz a cotação e cria o protocolo quando chama um atendente. É aqui que fica o jeito de falar do bot.
* **Como usar:** não roda sozinho. Para conversar com ele, use o `teste_simulador.py`.

#### `todos_faq.py`
* **Para que serve:** as dúvidas frequentes e as respostas, tiradas de conversas reais da empresa. Cada dúvida tem palavras-chave **fortes** (uma já basta) e **fracas** (só valem quando a frase inteira é daquele assunto). Assim o bot não dá uma resposta certa para a pergunta errada.
* **Como usar:** não roda sozinho. Para mudar uma resposta, edite o texto aqui.

#### `todos_aprendizado.py`
* **Para que serve:** anota na planilha `base_conhecimento` as perguntas que o bot não soube responder, juntando as parecidas. Quando uma pessoa escreve a resposta e marca `aprovada`, o bot passa a responder aquilo sozinho. Uma vez por semana, manda no Telegram um resumo do que está esperando resposta.
* **Como usar:**

```
python todos_aprendizado.py
```

Mostra quantas perguntas estão anotadas, quais esperam resposta e como ficaria o resumo semanal. Só lê a planilha, não muda nada.

#### `todos_ia.py`
* **Para que serve:** a IA do Google (Gemini). Ela só entra quando as regras falham: responde dúvidas usando **só** as informações da empresa, lê pedidos escritos do jeito do cliente ("meia tonelada", "capital do Tocantins") e corrige cidades que as regras leram errado. Antes de mandar a mensagem para o Google, tira CNPJ, CPF, CEP, e-mail e telefone. Se o modelo principal estiver sobrecarregado, tenta uma vez o modelo reserva.
* **Como usar:** liga e desliga pelo `IA_LIGADA` do `todos_config.py`. A chave vai no `.env` e no Render, como `GEMINI_API_KEY`. Para testar a chave:

```
python todos_ia.py
python todos_ia.py "sua frase de teste aqui"
```

Mostra o que a IA leu em cada frase e se o modelo reserva está respondendo. Funciona com o interruptor ligado ou desligado.

################################################################################################

### A cotação

#### `todos_distancia.py`
* **Para que serve:** encontra as cidades que o cliente escreveu e calcula a distância entre elas.
* **Como usar:**

```
python todos_distancia.py
```

Mostra a distância de Goiânia até Palmas, para conferir se a lista de cidades está carregando.

#### `todos_tabela.py`
* **Para que serve:** lê a tabela de preços e encontra o valor do frete pela distância e pelo peso.
* **Como usar:**

```
python todos_tabela.py
```

Mostra as faixas da tabela e alguns valores de exemplo.

#### `todos_cep.py`
* **Para que serve:** reconhece o CEP na mensagem e descobre a cidade pelo ViaCEP. Se a consulta falhar, o bot pede a cidade escrita.
* **Como usar:**

```
python todos_cep.py
```

Mostra a cidade de alguns CEPs de exemplo. Precisa de internet.

#### `todos_cnpj.py`
* **Para que serve:** confere se o CNPJ digitado é bem formado, pela conta dos dígitos verificadores, sem consultar nada na internet. Aceita também o CNPJ novo, com letras.
* **Como usar:**

```
python todos_cnpj.py
```

Mostra quais CNPJs de exemplo são válidos e quais não são.

################################################################################################

### Atendente, e-mail e planilhas

#### `todos_alerta.py`
* **Para que serve:** manda o alerta para o Telegram do atendente. Todo alerta chega com ❌ e dois botões: um abre a conversa do cliente e o outro, **Já atendi**, troca o ❌ por ✅.
* **Como usar:** para o botão funcionar, o endereço do servidor precisa ser cadastrado no Telegram, uma vez só:

```
python todos_alerta.py https://chatbot-deflo.onrender.com/telegram
```

Se o botão parar de funcionar, este comando mostra o último erro do Telegram:

```
python todos_alerta.py --conferir
```

#### `descobrir_chat_id.py`
* **Para que serve:** descobre o número da conversa do Telegram do atendente (o `TELEGRAM_CHAT_ID` do `.env`). Usado uma vez só, na configuração.
* **Como usar:** coloque o `TELEGRAM_TOKEN` no `.env`, mande um "oi" para o bot pelo Telegram do atendente e rode:

```
python descobrir_chat_id.py
```

Copie o número que aparecer para o `TELEGRAM_CHAT_ID` do `.env`.

#### `todos_email.py`
* **Para que serve:** olha a caixa de entrada do e-mail da empresa. A cada e-mail novo de cliente, cria um protocolo, avisa no Telegram e grava na planilha `emails_registrados`. Só lê: o e-mail continua como não lido. Só roda na produção.
* **Como usar:** para testar a ligação com o e-mail:

```
python todos_email.py
```

Usa o e-mail mais recente da caixa: manda um aviso marcado como TESTE no Telegram e grava uma linha na planilha, que depois pode ser apagada.

#### `todos_registro.py`
* **Para que serve:** grava cada cotação na planilha `cotacoes_registradas`, uma linha por conversa. Se o cliente chamar um atendente depois, a mesma linha recebe o protocolo. O significado de cada coluna está no começo do arquivo.
* **Como usar:** não roda sozinho.

#### `todos_drive.py`
* **Para que serve:** a ligação do bot com a pasta de dados no Google Drive. Baixa a tabela de preços e as listas de cidades, e escreve nas planilhas.
* **Como usar:**

```
python todos_drive.py
```

Tem que terminar com "Ligação com o Google Drive funcionando.".

################################################################################################

### WhatsApp e servidores

#### `todos_whatsapp.py`
* **Para que serve:** recebe as mensagens do WhatsApp, passa para o `todos_conversa.py` e envia a resposta. Também lembra o cliente que parou no meio da cotação por 10 minutos.
* **Como usar:** não roda sozinho. É usado pelo `teste_app.py` e pelo `producao_app.py`.

#### `todos_assinar_webhook.py`
* **Para que serve:** diz à Meta para qual servidor mandar as mensagens do WhatsApp. A Meta entrega em **um** endereço só: ou o teste, ou a produção.
* **Como usar:**

Para mandar as mensagens para o **teste**:

```
python todos_assinar_webhook.py ID_DA_CONTA https://SEU-ENDERECO.ngrok-free.dev/webhook
```

Para devolver as mensagens para a **produção**:

```
python todos_assinar_webhook.py ID_DA_CONTA https://chatbot-deflo.onrender.com/webhook
```

O servidor do endereço precisa estar ligado na hora. Tem que aparecer "Assinatura feita com sucesso".

#### `teste_app.py`
* **Para que serve:** o servidor de teste. Liga o bot no seu computador para testar no WhatsApp de verdade, antes de mandar qualquer mudança para a produção.
* **Como usar:** precisa do ngrok instalado (pela Microsoft Store) e registrado uma vez com `ngrok config add-authtoken SEU_AUTHTOKEN`. Depois, use três terminais:

1 - **Ligar o bot**, no Terminal 1:

```
python -m uvicorn teste_app:app --port 8000
```

2 - **Ligar o ngrok**, no Terminal 2:

```
ngrok http 8000 --url https://SEU-ENDERECO.ngrok-free.dev
```

3 - **Mandar as mensagens para o teste**, no Terminal 3:

```
python todos_assinar_webhook.py ID_DA_CONTA https://SEU-ENDERECO.ngrok-free.dev/webhook
```

4 - **Testar:** mande uma mensagem para o número do bot pelo WhatsApp.

5 - **Ao terminar**, devolva as mensagens para a produção, no Terminal 3:

```
python todos_assinar_webhook.py ID_DA_CONTA https://chatbot-deflo.onrender.com/webhook
```

Depois, pode fechar os terminais. Enquanto o teste está ligado, a produção não recebe mensagens.

Toda vez que mudar o código, feche o bot (Ctrl+C no Terminal 1) e ligue de novo. O bot que já estava rodando continua com o código antigo.

#### `producao_app.py`
* **Para que serve:** o servidor de produção, o bot que fica no ar 24 horas no Render. É mais rígido que o teste: se faltar uma senha, ele nem liga.
* **Como usar:** não roda no seu computador. Depois de cada commit, publique a versão nova pelo botão **Manual Deploy**, no painel do Render. O Render liga o bot com o comando:

```
uvicorn producao_app:app --host 0.0.0.0 --port $PORT
```

As senhas ficam no painel do Render, em **Environment**, e a chave do Google em **Secret Files**. Para ver o que está acontecendo, use a aba **Logs** do Render.

################################################################################################

### Testes

#### `teste_simulador.py`
* **Para que serve:** conversa com o bot pelo terminal, sem WhatsApp. É o jeito mais rápido de testar na mão.
* **Como usar:**

```
python teste_simulador.py
python teste_simulador.py --hora 22
```

O `--hora 22` finge que são 22h, para testar fora do horário. Dentro do simulador:

* `/novo` → começa como um cliente novo
* `/esperar 10` → finge que o cliente ficou 10 minutos sem responder
* `/audio` → finge que o cliente mandou um áudio
* `/sair` → encerra

Na abertura, ele mostra se a IA está ligada ou não.

#### `teste_automatico.py`
* **Para que serve:** roda sozinho mais de 200 conversas e confere as respostas. Toda vez que o código mudar, ele diz na hora se alguma coisa que funcionava parou de funcionar. Não manda nada para o Telegram, não grava nada na planilha e não chama o Google: essas partes são trocadas por versões de mentira.
* **Como usar:**

```
python teste_automatico.py
python teste_automatico.py --detalhe
python teste_automatico.py --csv
```

O `--detalhe` mostra a resposta do bot em cada caso. O `--csv` salva o resultado em `resultado_dos_testes.csv`. Precisa do `.env` preenchido, porque a lista de cidades e a tabela vêm do Drive.

################################################################################################

### Documentação

#### `DocumentacaoDeflo.pdf`
* **Para que serve:** a documentação completa do projeto, com o problema da empresa, a solução e como o bot funciona.
* **Como usar:** é só abrir.