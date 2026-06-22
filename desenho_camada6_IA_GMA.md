# Desenho — Camada 6: Inteligência Artificial (assíncrona, opcional)

> Mapa da visão da IA no GMA, como o idealizador pensa o andar 6.
> Escrito na sessão 44 (2026-06-21). Documento de DESENHO — ainda não há código.
> Ler junto: `arquitetura_GMA.md` (princípios) e `contexto_atual_GMA.md` (estado).

---

## 0. A regra que nada quebra

A IA **nunca entra no ciclo crítico** (copiar → conferir → auditar). Esse ciclo
continua 100% offline, mecânico e gratuito. Toda a Camada 6 é **assíncrona e
opcional**: roda *antes* do evento (montar o projeto) ou *depois* da cópia (sobre
material já seguro no HD). Se a IA falhar ou faltar internet, o material continua
intacto e o sistema segue funcionando.

**Sobre internet (decisão do idealizador, s44):** em grandes eventos sempre haverá
um mínimo de internet. Por isso a Camada 6 **pode usar nuvem/API** quando isso traz
qualidade ao trabalho fino de apuração — o critério de cada camada é a **qualidade
da apuração**, não a restrição de rede. O que permanece sagradamente offline é só o
ciclo crítico. A mídia continua **nunca subindo** para a nuvem (sobe só *informação
sobre* ela: texto, tags, descrições).

---

## 1. As três camadas de IA (como o idealizador pensa)

### 1ª camada — a IA que dá forma ao projeto (no nascimento dele)
A IA monta a "cara" do sistema para cada evento. Existe um **lugar de upload de
materiais de referência** (briefing, planilhas antigas, line-up, regras do cliente)
e um **chat de esclarecimento**; a partir disso a **IA monta sozinha** o projeto:
quais Posts existem, quais grupos de classificação (palco/marca/pauta/tags), quais
listas alimentar. O operador **não aprova antes** — a IA gera e o operador **ajusta
depois**, usando os grupos editáveis que já construímos (1 ponto de criação → chip
na ficha + coluna na planilha). A IA gera; o humano refina.

- **Onde encaixa no que já existe:** é a evolução da *Central de Entrada / importação*
  (colar planilha/print/PDF → extrair → listas). Hoje o operador extrai/revisa à mão;
  a 1ª camada faz a IA propor o conjunto inteiro.
- **Pré-requisito/companheiro (registrado s44):** **controle por data na aba Listas** —
  poder criar grupo/lista amarrado a um **dia** (como os shows por data do Rock in Rio,
  a "virada das fichas"). É C1/C3 e generaliza o que já fizemos pro festival. A 1ª camada
  de IA vai *preencher* essa estrutura quando ler um line-up datado. Construir essa peça
  é degrau natural antes (ou junto) da 1ª camada.

### 2ª camada — a IA que entende o que entrou e atende o editor
O **agente conversacional** (a "Missão A"). No meio do evento o editor pede:
*"preciso de um vídeo com tal temática, tal contexto, essas pessoas, esse ambiente"*
— e o agente responde **quais arquivos têm aquilo, sugerindo os takes**. Ele cruza
tudo que o sistema sabe: a classificação que o profissional marcou no Post + o que a
IA extraiu do material (transcrição de áudio e, quando existir, a leitura de imagem
da 3ª camada).

### 3ª camada — a IA que olha as imagens e aprofunda o detalhamento
Análise de visão sobre o material captado, para enriquecer os metadados muito além
do que o profissional digitou: cenas, pessoas, objetos, ambiente, momento.

- **Estrela-guia (decisão do idealizador, s44):** *quanto mais profundo, maior o poder
  de venda do sistema*. O norte é chegar ao **momento/take dentro do arquivo (timecode)**,
  não só ao arquivo. Construímos em degraus — **arquivo → trecho → take** — mas mirando
  sempre o take.

---

## 2. O centro: planilha + busca conversacional

Tudo converge numa **planilha com filtros avançados + uma barra de busca conversacional**
— o lugar onde o editor trabalha sob a pressão do real-time. As camadas 2 e 3 **não são
telas novas**: elas *enriquecem a planilha que já existe* e colocam uma conversa por cima.

### Decisão estrutural — ordem das colunas (núcleo fixo, variável no fim)
A planilha cresce e encolhe colunas (grupos editáveis). Isso **quebra filtros e fórmulas**
se a parte variável ficar no meio (no Google Sheets, filtros salvos e fórmulas se prendem
à *posição* da coluna). Regra adotada:

```
[ 1. IDENTIFICAÇÃO — fixo ]       profissional · cartão NOME_NNN · tipo · data · câmera
[ 2. TÉCNICAS DO SISTEMA — fixo ] nº arquivos · tamanho · caminho · status · TRANSCRIÇÃO
[ 3. CLASSIFICAÇÃO — variável ]   palco · marca · pauta · tags…  ← cresce/encolhe AQUI, no fim
```

- A **coluna de transcrição é fixa do sistema** (não varia por evento) → mora no bloco
  técnico estável, nunca dança.
- Só o bloco de **classificação** cresce/encolhe, sempre **acrescentando ao final**.
- Assim os filtros do editor sobre identificação e técnicas **nunca quebram** no meio do evento.
- Implementação: a `banco_dados.montar_planilha` é a **fonte única** da ordem das colunas —
  é lá que essa ordem se garante quando mexermos na planilha.

---

## 3. Ordem de construção (combinada)

A ordem **conceitual** (1→2→3) **não é** a ordem de **construir**. A 3ª alimenta a 2ª, e
o caminho mais barato/seguro começa pelo que não cruza com nada:

1. **Transcrição de áudio (Whisper local, grátis/offline)** → vira uma **coluna na planilha**.
   Peça **básica e isolada** (não cruza com outra atividade). É o **primeiro tijolo**.
2. **Busca conversacional (2ª camada — Missão A)** sobre o que a planilha já sabe
   (classificação do Post + transcrição). Pode usar API/nuvem pela qualidade.
3. **Leitura de imagem (3ª camada — Missão B)** por último — a mais cara e pesada;
   aprofunda até o take/timecode. Cloud-first onde a qualidade exigir.

---

## 4. Custo × motor, por camada

| Camada | Motor provável | Internet | Custo |
|---|---|---|---|
| Transcrição (tijolo 1) | Whisper **local** | não precisa | grátis |
| 1ª — montar projeto | LLM (API) | sim (no setup) | por evento |
| 2ª — busca conversacional | LLM (API) | sim (mínimo dos grandes eventos) | por uso |
| 3ª — leitura de imagem | visão (API) | sim | o mais alto — mas é o poder de venda |

A mídia **nunca** sobe; o que vai pra API é *informação sobre* o material
(transcrição, frames já extraídos localmente, descrições).

---

## 5. O que falta decidir / construir (radar)

- **Controle por data na aba Listas** (pré-requisito da 1ª camada) — C1/C3.
- Onde a **barra de busca conversacional** vive exatamente (dentro da planilha de
  entrega × chat à parte) — definir quando chegarmos na 2ª camada.
- Modelo/custo de cada API (qual LLM, qual visão) — decidir camada a camada.
- Granularidade da 3ª camada por degrau (arquivo → trecho → take).

---

## 6. Primeiro tijolo desta linha

**Transcrição de áudio (Whisper local) → coluna fixa na planilha.** Sem internet,
sem custo, sem cruzar com o resto. Detalhe de escopo a fechar com o agente `ia-gma`
na próxima sessão: onde roda (gatilho pós-cópia, assíncrono), em qual material
(áudio dos cartões de áudio e/ou trilha dos vídeos), e como grava a coluna via a
fonte única (`montar_planilha`).
