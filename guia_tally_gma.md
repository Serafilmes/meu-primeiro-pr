# Guia Tally GMA — Como montar o formulário de check-in

Este guia explica passo a passo como criar o formulário de check-in no Tally e conectá-lo
ao sistema GMA. Não é necessária experiência técnica — siga as seções na ordem.

---

## Seção 1 — Criar o formulário no Tally

### 1.1 Acessar o Tally

1. Abra o navegador e acesse **tally.so**
2. Faça login (ou crie uma conta gratuita)
3. Clique em **"Nova pesquisa"** (ou **"New form"** se estiver em inglês)
4. Dê o título: **GMA — Check-in de Cartão**

---

### 1.2 Criar os campos do formulário

> **ATENÇÃO — ponto crítico:** o "label" (rótulo) de cada campo é o que o sistema GMA usa
> para identificar a informação. Se o label estiver diferente do que está aqui (ex: "Nome"
> com N maiúsculo em vez de "nome"), o sistema não vai reconhecer o campo. Use exatamente
> os labels listados abaixo, com letras minúsculas e underline (underscore `_`) entre palavras.

Crie os campos na ordem abaixo:

---

**Campo 1 — Nome do profissional**
- Label (rótulo): `nome`
- Tipo: Texto curto
- Obrigatório: SIM
- Dica para o usuário (opcional): "Seu nome completo ou apelido usado no set"

---

**Campo 2 — Câmera**
- Label (rótulo): `camera`
- Tipo: Múltipla escolha (Dropdown)
- Obrigatório: SIM
- Opções:
  - GoPro
  - Sony
  - Canon
  - Blackmagic
  - DJI
  - RED
  - Arri
  - Panasonic
  - Outro

---

**Campo 3 — Tipo de material**
- Label (rótulo): `tipo_material`
- Tipo: Múltipla escolha (Dropdown)
- Obrigatório: SIM
- Opções:
  - VIDEO
  - FOTO
  - AUDIO
  - SONORIZAÇÃO

---

**Campo 4 — Data de gravação**
- Label (rótulo): `data_gravacao`
- Tipo: Data
- Obrigatório: SIM
- Observação: o sistema espera o formato AAAA-MM-DD (o Tally envia nesse formato automaticamente)

---

**Campo 5 — Operador do check-in**
- Label (rótulo): `operador`
- Tipo: Texto curto
- Obrigatório: NÃO (opcional)
- Dica para o usuário (opcional): "Quem está recebendo o cartão na base"

---

**Campo 6 — Modelo da câmera**
- Label (rótulo): `modelo_camera`
- Tipo: Texto curto
- Obrigatório: NÃO (opcional)
- Dica para o usuário (opcional): "Preencha o modelo completo (ex: HERO11 Black, FX6, EOS R5)"

---

**Campo 7 — Tipo de conteúdo**
- Label (rótulo): `tipo_conteudo`
- Tipo: Múltipla escolha (Dropdown)
- Obrigatório: NÃO (opcional)
- Opções:
  - B-ROLL
  - ENTREVISTA
  - PALCO PRINCIPAL
  - COBERTURA
  - ABERTURA
  - ENCERRAMENTO
  - OUTRO

---

**Campo 8 — Local / Cena**
- Label (rótulo): `local_cena`
- Tipo: Texto curto
- Obrigatório: NÃO (opcional)
- Dica para o usuário (opcional): "Onde o material foi gravado (ex: Palco Principal, Backstage, Área VIP)"

---

**Campo 9 — Prioridade**
- Label (rótulo): `prioridade`
- Tipo: Múltipla escolha (Dropdown)
- Obrigatório: NÃO (opcional)
- Opções:
  - NORMAL
  - URGENTE

---

**Campo 10 — Observações**
- Label (rótulo): `observacoes`
- Tipo: Texto longo
- Obrigatório: NÃO (opcional)
- Dica para o usuário (opcional): "Qualquer informação relevante (ex: cartão quase cheio, entrevista exclusiva)"

---

## Seção 2 — Configurar o webhook

### O que é um webhook?

Pense no webhook como um "mensageiro automático": toda vez que alguém preenche o formulário
no Tally, esse mensageiro envia os dados imediatamente para o sistema GMA. Sem webhook,
o GMA não recebe as informações.

### 2.1 Iniciar o ngrok (obrigatório antes de configurar o webhook)

O sistema GMA roda na sua máquina local. Para o Tally (que está na internet) conseguir
enviar os dados, é preciso abrir um "túnel" temporário usando o ngrok.

1. Abra o Terminal
2. Execute o comando:
   ```bash
   bash /Users/serafa/GMA/ngrok_gma.sh
   ```
3. O terminal vai exibir uma URL parecida com:
   ```
   Webhook URL: https://abc123.ngrok-free.app/forms/tally
   ```
4. Copie essa URL completa — você vai precisar dela no próximo passo

> **Importante:** a URL do ngrok muda toda vez que você reinicia. Sempre que for usar o
> sistema num evento, repita esse passo e atualize a URL no Tally.

---

### 2.2 Configurar o webhook no Tally

1. No painel do seu formulário no Tally, clique em **"Integrations"** (Integrações)
2. Procure por **"Webhooks"** e clique em **"Connect"** (Conectar)
3. No campo de URL, cole a URL que o ngrok exibiu:
   ```
   https://abc123.ngrok-free.app/forms/tally
   ```
   (substitua `abc123.ngrok-free.app` pela URL real que apareceu no seu terminal)
4. Clique em **"Save"** (Salvar)

O Tally vai enviar os dados para essa URL toda vez que alguém preencher o formulário.

---

## Seção 3 — Testar sem o Tally (com curl)

Antes de usar o formulário de verdade, você pode testar se o Flask GMA está recebendo
os dados corretamente. Este comando simula exatamente o que o Tally enviaria.

**Pré-requisito:** o Flask GMA precisa estar rodando. Para subir o sistema:
```bash
python3 /Users/serafa/GMA/inicializar_gma.py
```

**Comando de teste (copie e cole no Terminal):**

```bash
curl -X POST http://127.0.0.1:5050/forms/tally \
  -H "Content-Type: application/json" \
  -d '{
    "data": {
      "fields": [
        {"label": "nome",          "value": "JOAO"},
        {"label": "camera",        "value": "GoPro"},
        {"label": "tipo_material", "value": "VIDEO"},
        {"label": "data_gravacao", "value": "2026-06-08"},
        {"label": "operador",      "value": "Teste"},
        {"label": "modelo_camera", "value": "HERO11 Black"},
        {"label": "tipo_conteudo", "value": "B-ROLL"},
        {"label": "local_cena",    "value": "Palco Principal"},
        {"label": "prioridade",    "value": "NORMAL"},
        {"label": "observacoes",   "value": "Primeiro teste com campos novos"}
      ]
    }
  }'
```

**Resposta esperada** (o sistema vai devolver algo parecido com isso):
```json
{"ok": true, "id_form": "20260608_143201_ab12cd", "mensagem": "Formulário recebido com sucesso."}
```

Se aparecer `"ok": true`, o sistema recebeu tudo corretamente. Se aparecer `"ok": false`,
verifique se o Flask está rodando e se o comando foi copiado corretamente.

---

## Seção 4 — Verificar no banco de dados

Depois de enviar o teste (Seção 3), você pode confirmar que os dados foram salvos no banco.
Copie e cole este comando no Terminal:

```bash
python3 -c "
import sqlite3
conn = sqlite3.connect('/Users/serafa/GMA/gma.db')
conn.row_factory = sqlite3.Row
for r in conn.execute('SELECT nome, camera, modelo_camera, tipo_conteudo, local_cena, prioridade, observacoes FROM formularios ORDER BY id DESC LIMIT 3'):
    print(dict(r))
conn.close()
"
```

**O que esperar:** o comando vai mostrar os 3 últimos registros do banco. Para o teste da
Seção 3, você deve ver algo assim:

```
{'nome': 'JOAO', 'camera': 'Gopro', 'modelo_camera': 'HERO11 Black', 'tipo_conteudo': 'B-ROLL', 'local_cena': 'Palco Principal', 'prioridade': 'NORMAL', 'observacoes': 'Primeiro teste com campos novos'}
```

Se os campos aparecerem com os valores que você enviou, está tudo funcionando.

---

## Seção 5 — Importante: como o label do Tally chega no sistema

### Por que o label é tão importante?

Quando você preenche o formulário no Tally e clica em enviar, o Tally manda os dados para
o GMA numa lista assim:

```
Campo 1: label = "nome",          valor = "JOAO"
Campo 2: label = "camera",        valor = "GoPro"
Campo 3: label = "tipo_material", valor = "VIDEO"
...
```

O GMA lê essa lista e procura cada campo pelo seu label. Se o label estiver errado — mesmo
que só uma letra diferente — o campo não será reconhecido e a informação será perdida.

### Exemplos de erros comuns:

| Label errado (não usar) | Label correto (usar este) |
|---|---|
| `Nome` | `nome` |
| `Camera` | `camera` |
| `tipo material` (com espaço) | `tipo_material` (com underscore) |
| `DataGravacao` | `data_gravacao` |
| `Prioridade` | `prioridade` |

### Regra de ouro:

Use exatamente os labels listados na Seção 1 deste guia:
- Sem acentos (não "câmera", mas "camera")
- Sem letras maiúsculas
- Palavras separadas por underline `_` (não por espaço)

Os campos obrigatórios (`nome`, `camera`, `tipo_material`, `data_gravacao`) precisam ter
o label exato ou o sistema vai recusar o formulário. Os campos opcionais com label errado
são simplesmente ignorados — não travam o sistema, mas os dados são perdidos.
