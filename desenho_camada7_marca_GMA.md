# Desenho da Camada 7 — Marca & Identidade do 6floor

> Fonte de verdade da identidade visual. Antes deste arquivo, as decisões viviam
> só nos mapas (em palavras) e os rascunhos eram desenhos de tela que evaporavam
> entre sessões. Aqui ficam as decisões **e** os arquivos de marca, no disco.
>
> Arquivos vivos: `marca/6floor_simbolo.svg` · `marca/6floor_simbolo_trabalhando.svg` ·
> `marca/6floor_lockup.svg`.
>
> Histórico: identidade decidida na **s53** (sem código); glifo + animação fechados e
> salvos na **s54**; glifo **afinado na s56** — saiu do infinito cruzado para **dois "o"
> encostados** (mais unidade com a fonte) e o lockup ficou **fluido na palavra**.

---

## 1. O nome — 6floor

- **6floor** (minúsculas). O "6" nasceu de que a IA mora no 6º andar do prédio (Camada 6);
  ficou foneticamente embarcado.
- **Leitura dupla (de propósito):** pra fora soa **estrutura / prédio sólido** (não grita "IA");
  pra dentro guarda o sentido pessoal do idealizador.
- Mistura "6" (pt) + "floor" (en) fica como **estilização** — o nome de marca não é literal
  quanto à contagem de andares.
- "GMA" segue como **nome técnico interno** do projeto.

## 2. Tipografia — Space Grotesk

- **Space Grotesk** (proporcional nascida da monoespaçada Space Mono — moderna, com personalidade).
  Escolha do idealizador, depois de comparar IBM Plex Mono / Archivo / Sora / JetBrains Mono.
  (Eu havia recomendado uma mono pela credibilidade de "ferramenta séria" e por resolver o `l↔1`;
  ele preferiu a Space Grotesk pela cara.)
- **"l" reto mantido** — aceita a leve ambiguidade; o rabinho discreto fica disponível se ele quiser depois.
- Pesos em uso: **500 (medium)** no lockup.

## 3. Cor — acento teal

- **Acento:** `#2BB58C` (variação mais escura `#1D9E75`). "Sala de controle", calmo, atemporal.
- **Fundo do mundo:** escuro — neste desenho `#0E1513` (quase-preto esverdeado). Detalhes sutis
  em `#1C2622` (divisórias) e textos secundários em `#5E726C`. Texto claro: `#EAF0EE`.
- **Um acento só.** Nada de segunda cor decorativa.
- (Alternativas mostradas e descartadas na s53: ciano e âmbar.)

### Paleta completa (fechada na s54) — `marca/6floor_paleta.css`

Sistema de cor do mundo escuro. **Regra:** o teal é o único acento de identidade;
vermelho e âmbar entram **só para alerta**, nunca como decoração. Ao aplicar nas
telas, usar as variáveis CSS — nunca hex solto.

**Marca (o único acento)**
| token | hex | uso |
|---|---|---|
| `--6f-teal` | `#2BB58C` | acento principal |
| `--6f-teal-forte` | `#1D9E75` | pressionado / borda do acento |
| `--6f-teal-claro` | `#3DD3A6` | realce / hover sobre o escuro |
| `--6f-teal-trilho` | `#132F26` | teal apagado: trilho do infinito, fundos sutis |

**Fundos (sala de controle — do mais fundo ao mais alto)**
| token | hex | uso |
|---|---|---|
| `--6f-bg-base` | `#0B100E` | fundo do app |
| `--6f-bg-superficie` | `#0E1513` | painéis |
| `--6f-bg-elevado` | `#131C19` | cartões |
| `--6f-bg-hover` | `#1A2521` | item ativo / hover |

(O degrau de fundos cria "camadas" numa tela escura **sem usar sombra**.)

**Linhas e texto**
| token | hex | uso |
|---|---|---|
| `--6f-borda` | `#243430` | linhas / separadores |
| `--6f-texto` | `#EAF0EE` | texto primário |
| `--6f-texto-2` | `#9DB0AA` | texto secundário |
| `--6f-texto-3` | `#5E726C` | texto terciário / dicas |

**Estados (só para alerta — ok = a própria marca)**
| token | hex | uso |
|---|---|---|
| `--6f-ok` | `#2BB58C` | saúde / sucesso (= teal) |
| `--6f-aviso` | `#E0A33B` | âmbar |
| `--6f-erro` | `#E5645B` | vermelho |

Conversa direto com o que já existe: a bolinha 🟢/🔴/🟡 do Sheets no Painel e as
barras de progresso por andar.

## 4. O símbolo — o infinito que vira status

Os dois "o" de *floor* viram um **infinito (∞) monoline**, no estilo da fonte.

### Forma (o glifo) — afinado na s56 (era cruzado na s54)
- **DOIS "o" ENCOSTADOS (infinito insinuado):** dois círculos do tamanho do "o" da Space Grotesk,
  ligados por uma linha contínua que só se **toca** no meio (não cruza por cima de si mesma). O
  infinito fica **sugerido** — a leitura primeira é "os dois o de *floor* fundidos", o que dá a
  **unidade com a fonte** que o pedido da s56 buscava. (O ∞ cruzado da s54 ficava "da cara" demais
  como símbolo avulso; ver caminhos rejeitados.)
- **Espessura casada com a fonte:** o traço tem o mesmo peso da haste das letras (razão
  traço/diâmetro ≈ 0,22, a mesma do "o" da Space Grotesk). É o que faz a "tinta" do símbolo bater
  com a da palavra.
- **Assentado na altura do "o"** (x-height) — no lockup o símbolo senta exatamente onde os dois "o"
  sentariam, não flutua.
- **Legível até 16px** — o "chão" do ícone do app.
- **Cantos arredondados** (`stroke-linecap`/`linejoin: round`).

Path canônico (centrado em 0,0; dois círculos tangentes de raio 50 → vão ±100 em x, ±50 em y;
stroke-width 24 no símbolo cheio = razão ≈ 0,22). É o **mesmo path** nos três SVGs; o lockup o usa
em `scale(0.369)` com `vector-effect:non-scaling-stroke` stroke 8 (peso do "o" da fonte):

```
M0,0 C0,-27.6 -22.4,-50 -50,-50 C-77.6,-50 -100,-27.6 -100,0 C-100,27.6 -77.6,50 -50,50 C-22.4,50 0,27.6 0,0 C0,-27.6 22.4,-50 50,-50 C77.6,-50 100,-27.6 100,0 C100,27.6 77.6,50 50,50 C22.4,50 0,27.6 0,0 Z
```

### Estado vivo — repouso × trabalhando
- **Repouso:** ∞ calmo, traço teal sólido.
- **Trabalhando:** **"forma e dissolve"** — o laço se desenha do zero, fica **inteiro aceso por
  um instante** (o "selo" da marca) e dissolve pelo mesmo caminho. Ritmo **lento e espacial**
  (~6s, `ease-in-out`), pra gerar calma — "o sistema trabalha em silêncio", não corre.
  Como o traço é uma linha contínua, ele **contorna um "o" e depois o outro** (esquerdo → direito):
  o desenho **forma um laço por vez**, e parece a palavra se formando (decisão da s56).
- O símbolo **vira indicador de status**: ecoa as barras de progresso por andar e o andar 8/P&D
  (permanente, ♾️).

Animação (CSS, com uma linha-fantasma 10% por baixo pra dar espaço):

```
stroke-dasharray: 1000 1000;   /* com pathLength="1000" no path */
animation: forma 6s ease-in-out infinite;
@keyframes forma {
  0%   { stroke-dashoffset: 1000; }   /* vazio */
  46%  { stroke-dashoffset: 0; }      /* desenhado */
  54%  { stroke-dashoffset: 0; }      /* segura inteiro aceso */
  100% { stroke-dashoffset: -1000; }  /* dissolve (costura sem pulo) */
}
```

### Caminhos REJEITADOS (não revisitar sem motivo novo)
- **Pupilas literais / "olhar":** a ideia inicial era vigilância/olho; as pupilas literais não
  funcionaram. O sentido de "olhar" ficou só **nas entrelinhas**.
- **Laço cruzado "fita/gravata":** destoava da tipografia.
- **Infinito CRUZADO (o glifo da s54):** era correto, mas lia "da cara" demais como um ∞ avulso
  colado no meio da palavra. Na s56 o idealizador pediu **menos infinito, mais os dois "o"** → daí
  a forma encostada (tangente) atual. O cruzado fica como registro, não como caminho a seguir.
- **Anéis lado a lado:** não liam como infinito (pareciam dois "o" soltos). Diferente dos "dois o
  encostados" atuais, que se **tocam** por uma linha contínua — aí a leitura de infinito acontece.
- **Animações agitadas (fluxo de pontos / pacotes / varredura):** "informação correndo" tinha
  **trânsito demais**; o idealizador pediu algo mais espacial e calmo → daí a "forma e dissolve".

## 5. Mundo visual

Ferramenta séria de logagem/DIT **moderna** — linhagem Hedge / Pomfort Silverstack / ShotPut +
Frame.io / Linear. Fundo escuro, um acento só, ícone do app legível **até 16px**.

## 6. O que ainda falta na Camada 7 (build futuro)

- **Ícone do app de verdade** (o símbolo no tile arredondado escuro, exportado nos tamanhos do macOS)
  — peça da Camada 5 quando empacotar o `.app`.
- **Paleta completa** (escala de cinzas/teal, estados ok/erro/aviso alinhados ao teal).
- **Grid e construção** do glifo (proporções formais).
- **Aplicar a marca nas telas** do Flask (Painel/Kanban/Planilha/ficha).
- **Lockup em contornos** (converter o texto Space Grotesk em paths) pra um SVG 100% portátil
  sem depender de carregar a fonte.
- **Materiais de apresentação.**

## 7. Notas técnicas dos arquivos

- Os SVGs usam o **mesmo path canônico** (seção 4) — qualquer ajuste de forma muda nos três.
- O lockup carrega a Space Grotesk via `@import` do Google Fonts → **precisa de internet** pra
  renderizar a palavra com a fonte certa (o símbolo não depende disso). Por isso o "lockup em
  contornos" está na lista do que falta.
- O símbolo sozinho é fundo **transparente** (reutilizável); o lockup vem sobre painel escuro
  porque o mundo da marca é escuro.

### Wordmark nas telas do Flask (s56, 2ª parte)

- **Decisão:** nas telas usa-se o **wordmark integrado "6fl∞r"** (o símbolo é o "oo" da palavra),
  no login E no cabeçalho/abas — **não** o mark separado seguido de "6floor".
- **Como é feito (importante):** o wordmark é **UMA imagem `<svg>` única** (`_marca_lockup` no
  `flask_gma.py`) — os textos "6fl" e "r" e o glifo desenhados dentro do mesmo svg, com
  `textLength` pra a largura ser estável mesmo sem a fonte carregada.
- **Por que svg único, e não texto HTML + svg inline:** a versão "texto + `<svg>` no meio"
  **empilhava** ("6fl" / ∞ / "r" em 3 linhas) porque o ambiente aplica um reset
  **`svg{display:block}`** que torna o símbolo um bloco. Como imagem única isso é impossível —
  não há fluxo de texto pra quebrar. (Lição: ao embutir um glifo no meio de palavra em HTML,
  preferir o svg único, ou forçar `display:inline-block` **inline** no próprio elemento.)
- **Opção só-símbolo:** `_marca_icone(altura)` rende **só o ∞**, sem a palavra (favicon, cabeçalho
  recolhido, selos). Mesmo glifo. Onde aplicar ainda será definido.
