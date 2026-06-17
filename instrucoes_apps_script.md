# GMA — Guia de configuração: Google Forms + Apps Script

Este guia explica como criar o formulário de check-in e conectá-lo ao servidor GMA.
Escrito para quem nunca usou Google Apps Script.

---

## O que você vai configurar

1. Um **Google Forms** com os campos de check-in.
2. Um **Apps Script** que, a cada envio do formulário, manda os dados automaticamente
   para o servidor GMA rodando no seu computador.

Tempo estimado: 20 a 30 minutos na primeira vez.

---

## Parte 1 — Criar o formulário no Google Forms

### 1.1 Acesse o Google Forms

Abra o navegador e vá para: **forms.google.com**
Clique em **"+"** para criar um formulário em branco.

### 1.2 Nomeie o formulário

No campo "Formulário sem título", escreva algo como:
```
GMA Check-in — [Nome do Evento]
```

### 1.3 Adicione os campos na ordem certa

O script identifica cada campo pela **posição** (primeiro, segundo, terceiro…).
Por isso é fundamental respeitar a ordem abaixo.

---

**Campo 1 — Nome**
- Tipo: **Resposta curta**
- Pergunta: `Nome`
- Descrição sugerida: `Nome do profissional de captação (fotógrafo, videomaker, técnico de som)`
- Marque como **obrigatório**

---

**Campo 2 — Câmera**
- Tipo: **Múltipla escolha**
- Pergunta: `Câmera`
- Opções (adicione uma por uma):
  - Canon/Nikon/Fuji
  - Sony
  - Blackmagic
  - RED
  - Arri
  - Panasonic
  - GoPro
  - DJI

---

**Campo 3 — Tipo de material**
- Tipo: **Múltipla escolha**
- Pergunta: `Tipo de material`
- Opções:
  - VIDEO
  - FOTO
  - AUDIO

---

**Campo 4 — Data de gravação**
- Tipo: **Data**
- Pergunta: `Data de gravação`
- Marque como **obrigatório**

---

**Campo 5 — Nome do operador**
- Tipo: **Resposta curta**
- Pergunta: `Nome do operador`
- Deixe como opcional (não precisa marcar obrigatório)

---

### 1.4 Verifique a ordem

Clique em "Visualizar" (ícone de olho no canto superior direito) e confirme
que os campos aparecem exatamente nesta sequência:
1. Nome
2. Câmera
3. Tipo de material
4. Data de gravação
5. Nome do operador

Se algum campo estiver fora de ordem, arraste-o pelo ícone de seis pontos
no lado esquerdo de cada campo.

---

## Parte 2 — Adicionar o Apps Script

### 2.1 Abra o editor de script

No Google Forms, clique nos **três pontos** (canto superior direito)
e selecione **"Editor de script"**.

Uma nova aba vai abrir com o editor do Google Apps Script.
Você vai ver algo como:

```javascript
function myFunction() {

}
```

### 2.2 Cole o código

1. Selecione **todo o texto** que está no editor (Ctrl+A ou Cmd+A).
2. **Apague** (Delete ou Backspace).
3. Abra o arquivo `google_apps_script.js` (que está na pasta do GMA no seu computador).
4. Copie todo o conteúdo desse arquivo.
5. **Cole** no editor do Apps Script.

### 2.3 Salve o projeto

Clique em **"Salvar"** (ícone de disquete) ou pressione **Ctrl+S** (Cmd+S no Mac).

Quando pedir um nome para o projeto, use:
```
GMA Conector
```

---

## Parte 3 — Descobrir o IP da máquina GMA

O Apps Script precisa saber o endereço (IP) do computador onde o servidor GMA
está rodando na rede do evento.

### 3.1 No terminal do Mac

Abra o **Terminal** (procure por "Terminal" no Spotlight) e rode:

```bash
ifconfig | grep "inet " | grep -v 127.0.0.1
```

Vai aparecer algo como:
```
inet 192.168.1.10 netmask 0xffffff00 broadcast 192.168.1.255
```

O número após `inet` (no exemplo: **192.168.1.10**) é o IP que você vai usar.

**Dica:** Se aparecerem vários resultados, use o que começa com `192.168.` ou `10.`.
Ignore linhas que começam com `172.` (essas são redes internas do sistema).

### 3.2 No terminal do Windows

Abra o **Prompt de Comando** (procure por "cmd") e rode:

```
ipconfig
```

Procure a seção "Adaptador de Rede sem Fio Wi-Fi" (ou "Ethernet") e anote
o valor de **"Endereço IPv4"**. Vai ser algo como `192.168.1.10`.

---

## Parte 4 — Configurar o IP no script

### 4.1 Edite a constante no topo do arquivo

No editor do Apps Script, localize as duas linhas no início do código:

```javascript
const IP_FLASK = "192.168.1.10";  // ← trocar pelo IP real da máquina GMA no evento
const PORTA_FLASK = "5050";
```

Substitua `192.168.1.10` pelo IP que você anotou no passo anterior.
Exemplo: se o seu IP for `192.168.0.55`, a linha deve ficar:

```javascript
const IP_FLASK = "192.168.0.55";
```

**Atenção:** faça isso no **início de cada evento**, porque o IP pode mudar
quando você conecta em uma rede diferente.

### 4.2 Salve novamente

Ctrl+S (ou Cmd+S).

---

## Parte 5 — Criar o trigger (gatilho automático)

O "trigger" é o mecanismo que manda o Apps Script rodar automaticamente
cada vez que alguém preenche o formulário.

### 5.1 Abra o menu de triggers

No editor do Apps Script, clique no ícone de **relógio** na barra lateral
esquerda (chama-se "Acionadores" ou "Triggers").

### 5.2 Adicione um novo trigger

Clique em **"Adicionar acionador"** (botão azul no canto inferior direito).

### 5.3 Configure assim

| Campo | Valor |
|---|---|
| Escolha a função a ser executada | `aoEnviarFormulario` |
| Escolha a implantação | `Head` |
| Selecione a fonte do evento | `Do formulário` |
| Selecione o tipo de evento | `No envio do formulário` |

Clique em **"Salvar"**.

### 5.4 Autorize o script

O Google vai pedir permissão para o script acessar o formulário e fazer
requisições de rede. Siga os passos:

1. Clique em **"Revisar permissões"**.
2. Escolha sua conta Google.
3. Se aparecer "Este app não foi verificado", clique em **"Avançado"** e depois
   em **"Ir para GMA Conector (não seguro)"**.
   (Isso é normal para scripts pessoais — o aviso aparece porque o Google não
   "verificou" o app, mas o código é o que você mesmo colou.)
4. Clique em **"Permitir"**.

---

## Parte 6 — Testar

### 6.1 Teste rápido sem preencher o formulário

No editor do Apps Script:
1. No menu de funções (canto superior, perto do botão "Executar"), selecione
   `testarConexaoFlask`.
2. Clique em **"Executar"** (triângulo/play).
3. Clique em **"Execuções"** no menu lateral para ver o resultado.

Se o Flask estiver rodando e o IP estiver correto, você vai ver:
```
Código HTTP: 200
Resposta:    {"status": "ok", ...}
```

Se aparecer "FALHA" ou "ERRO de conexão", veja a seção de solução de
problemas no final deste guia.

### 6.2 Teste completo com o formulário

1. No Google Forms, clique em "Visualizar" (ícone de olho).
2. Preencha o formulário com dados de teste.
3. Clique em "Enviar".
4. Acesse o **painel GMA** no navegador: `http://[IP_DA_MAQUINA_GMA]:5050`
5. O registro de teste deve aparecer na lista de check-ins.

---

## Solução de problemas

### "ERRO de conexão" no log

**Causas possíveis:**
- O servidor Flask não está rodando. Solução: rode `python porteiro.py` no terminal.
- O IP está errado. Solução: rode `ifconfig` novamente e confira.
- O celular e o computador GMA estão em redes diferentes. Solução: certifique-se
  de que ambos estão no mesmo Wi-Fi ou roteador do evento.
- O firewall do Mac está bloqueando a porta 5050. Solução: vá em
  Preferências do Sistema > Segurança > Firewall e permita o Python.

### "Código HTTP: 404"

O Flask está respondendo, mas a rota `/forms` não existe. Verifique se o
`porteiro.py` está atualizado.

### "Código HTTP: 500"

O Flask recebeu os dados mas teve um erro interno. Veja o terminal onde o
Flask está rodando — o erro aparece lá.

### O trigger não foi criado

Se ao criar o trigger não apareceu a função `aoEnviarFormulario` na lista,
verifique se o código foi salvo corretamente. Abra o arquivo, salve com
Ctrl+S e tente criar o trigger novamente.

### A data chega no formato errado

O script tenta normalizar automaticamente os formatos mais comuns. Se mesmo
assim a data chegar estranha, veja no log de execuções qual formato o Forms
está enviando e avise o desenvolvedor para ajustar a função `normalizarData`.

---

## Resumo rápido para dias de evento

Checklist antes de ligar tudo:

- [ ] Servidor Flask rodando (`python porteiro.py`)
- [ ] IP da máquina GMA verificado (`ifconfig`)
- [ ] `IP_FLASK` no Apps Script atualizado
- [ ] Trigger "On form submit" ativo
- [ ] Teste rápido (`testarConexaoFlask`) passou com código 200
- [ ] Formulário acessível no celular dos operadores de campo

---

*Documento do projeto GMA — Camada 1: Check-in e identificação*
