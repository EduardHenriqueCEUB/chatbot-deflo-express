# Chatbot Deflo Express

Bot de WhatsApp, feito em Python, que atende os clientes da Deflo Express.

* Faz a **cotação de frete fracionado** (cargas de até 1.000 kg) usando a tabela de preços da empresa.
* Responde as **dúvidas mais comuns**.
* Quando o cliente quer negociar, **avisa um atendente pelo Telegram** e passa ao cliente um **número de protocolo** do atendimento.

O bot não substitui a negociação: ele adianta o atendimento e chama uma pessoa.

**OBS.:** O projeto foi dividido em arquivos de `teste` e de `producao`, que usam alguns **arquivos em comum** que estão declarados como `todos` para rodar exatamente a mesma lógica. Foi feito assim para que **nenhuma alteração se perca**, tudo o que é corrigido ou melhorado no teste já está, automaticamente, na produção, porque os dois usam os mesmos arquivos. Se cada lado tivesse a sua própria cópia, uma correção feita no teste poderia não chegar à produção.

################################################################################################

######################################
####### O QUE CADA ARQUIVO FAZ #######
######################################

### Senhas e configuração:
* `.env_exemplo` → Modelo do arquivo de senhas. Mostra quais senhas o projeto precisa, mas vem vazio. Quem for rodar o projeto copia este arquivo, renomeia a cópia para `.env` e preenche com as próprias senhas.
* `.env` → o arquivo de senhas de verdade. **Não vai para o GitHub** por segurança, existe só no computador de quem roda o teste.
* `.gitignore` → lista do que o Git `NUNCA` pode enviar ao GitHub, como o `.env` e o registro de cotações (que tem telefones de clientes).
* `requirements.txt` → lista das bibliotecas do Python que o projeto usa, com as versões que foram testadas.



### Arquivos em comum (Usados pelo teste e pela produção):
* `todos_config.py` → todas as configurações em um lugar só: horário de atendimento, peso máximo, fator de cubagem etc. Para mudar uma regra, mexa aqui.
* `todos_conversa.py` → o "cérebro" do bot: conduz a conversa, pede as informações, faz a cotação e cria o número de protocolo quando o cliente chama um atendente.
* `todos_tabela.py` → lê a tabela de preços e encontra o valor do frete.
* `todos_distancia.py` → encontra as cidades que o cliente digitou e calcula a distância entre elas.
* `todos_faq.py` → as perguntas frequentes e as respostas.
* `todos_alerta.py` → manda o alerta para o Telegram do atendente.
* `todos_registro.py` → salva cada cotação em `dados/cotacoes_registradas.csv`, junto com o número de protocolo quando o cliente foi passado para um atendente.
* `todos_whatsapp.py` → recebe as mensagens do WhatsApp e envia as respostas.
* `todos_assinar_webhook.py` → diz à Meta (dona do WhatsApp) para onde mandar as mensagens: para o teste ou para a produção.
* `dados/` → a tabela de preços (`TabelaCotacao.xlsx`) e a lista de cidades e estados do Brasil.



### Arquivos só do teste:
* `teste_simulador.py` → conversa com o bot pelo terminal, sem WhatsApp. Serve para testar rápido.
* `teste_app.py` → servidor de teste: liga o bot no computador para testar no WhatsApp de verdade.



### Arquivos só da produção:
* `producao_app.py` → servidor de produção: o bot que fica no ar 24 horas, na nuvem. Tem regras de segurança mais rígidas que o teste.



### Arquivo de apoio:
* `descobrir_chat_id.py` → ajuda a configurar o Telegram (usado uma vez só).

################################################################################################

####################################
######## COMO RODAR O TESTE ########
####################################

### Antes da primeira vez:
1 - Instale as bibliotecas: `python -m pip install -r requirements.txt`
2 - Crie o `.env` a partir do `.env_exemplo` e preencha as senhas.
3 - Instale o ngrok (pela Microsoft Store) e registre a sua conta com `ngrok config add-authtoken SEU_AUTHTOKEN`.



Nos comandos abaixo, troque os textos em maiúsculas pelos seus:
* `SEU-ENDERECO.ngrok-free.dev` → o seu endereço fixo, que fica no painel do ngrok, em **Domains**.
* `ID_DA_CONTA` → o "ID da conta do WhatsApp Business", que fica no painel da Meta, na **Etapa 2**.



### Passo a passo:

1 - **Ligar o bot**
    Terminal 1   ->   ``` python -m uvicorn teste_app:app --port 8000 ```


2 - **Ligar o ngrok**
    Terminal 2   ->   ``` ngrok http 8000 --url https://SEU-ENDERECO.ngrok-free.dev ```


3 - **Mandar as mensagens para o teste**
    Terminal 3   ->   ``` python todos_assinar_webhook.py ID_DA_CONTA https://SEU-ENDERECO.ngrok-free.dev/webhook ```


4 - **Testar**
    Mande uma mensagem para o número do bot pelo WhatsApp e faça a cotação normalmente.


5 - **Devolver as mensagens para a produção (ao terminar)**
    Enquanto o teste está ligado, a produção não recebe mensagens. 
    

OBS.: Ao terminar o Teste, para fazer com que o ChatBot sai do Teste e vá para o ambiente de produção, rode:
    Terminal 3   ->   ``` python todos_assinar_webhook.py ID_DA_CONTA https://chatbot-deflo.onrender.com/webhook ```

Depois, pode fechar todos os terminais.

################################################################################################

################################################
####### COMO FUNCIONA A PRODUÇÃO (NUVEM) #######
################################################

No Teste, o bot roda `no computador` e só funciona enquanto ele está ligado. Na Produção, o bot roda `na nuvem`: num computador alugado que fica ligado o tempo todo. Assim, os clientes são atendidos a qualquer hora, sem depender de ninguém.


### As peças que foram integradas:
* **GitHub** → Guarda o código do projeto, em repositório privado. A nuvem pega o código daqui.
* **Render** → A nuvem onde o bot fica no ar, no endereço `https://chatbot-deflo.onrender.com`. Ele baixa o código do GitHub, instala as bibliotecas e liga o `producao_app.py`.
* **Senhas no Render** → Como o `.env` não vai para o GitHub, as senhas da produção são cadastradas direto no painel do Render, onde ninguém mais vê.
* **Webhook da Meta** → O endereço para onde a Meta entrega as mensagens do WhatsApp. Na produção, ele aponta para o Render.
* **UptimeRobot** → Visita o bot a cada 5 minutos. O plano grátis do Render "dorme" depois de 15 minutos parado, e essas visitas o mantêm acordado.


### O caminho de uma mensagem:
1 - O cliente manda uma mensagem no WhatsApp.
2 - A Meta entrega a mensagem no Render (webhook).
3 - O `producao_app.py` confere se a mensagem veio mesmo da Meta.
4 - O "cérebro" (`todos_conversa.py`) monta a resposta.
5 - A resposta volta para o cliente pelo WhatsApp. Se ele quiser negociar, recebe um número de protocolo e o atendente recebe o alerta no Telegram com o mesmo protocolo e um link para chamar o cliente pelo WhatsApp oficial da empresa.

### Por que a produção é mais rígida que o teste:
* Se faltar alguma senha, ela nem liga e avisa qual está faltando.
* Ela recusa qualquer mensagem que não tenha vindo comprovadamente da Meta.
* Ela esconde a página técnica `/docs`, para estranhos não verem como o servidor funciona.

### Atualizações não vão para a produção sozinhas:
O deploy automático do Render está **desligado**, uma mudança no código só chega à produção quando alguém clica em **Manual Deploy**, depois de testar. É o "testar antes de colocar no ar" funcionando na prática.
