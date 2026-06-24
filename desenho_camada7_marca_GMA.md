# Desenho da Camada 7 — Marca & Identidade do 6floor

> Fonte de verdade da identidade visual. Antes deste arquivo, as decisões viviam
> só nos mapas (em palavras) e os rascunhos eram desenhos de tela que evaporavam
> entre sessões. Aqui ficam as decisões **e** os arquivos de marca, no disco.
>
> Arquivos vivos: `marca/6floor_simbolo.svg` · `marca/6floor_simbolo_trabalhando.svg` ·
> `marca/6floor_lockup.svg`.
>
> Histórico: identidade decidida na **s53** (sem código); glifo + animação fechados e
> salvos na **s54**.

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

## 4. O símbolo — o infinito que vira status

Os dois "o" de *floor* viram um **infinito (∞) monoline**, no estilo da fonte.

### Forma (o glifo) — fechado na s54
- **Infinito CRUZADO:** a linha passa por si mesma no meio (como o ∞ tipográfico). É o que faz
  ele ler como infinito mesmo pequeno.
- **Espessura: MÉDIA.** Afina o suficiente pra ganhar elegância/precisão **e** ainda sobreviver
  no 16px do ícone. (Espessa demais pesa; fina demais some no 16px.)
- **Legível até 16px** — o "chão" do ícone do app; a espessura tem que aguentar esse tamanho.
- **Cantos arredondados** (`stroke-linecap`/`linejoin: round`).

Path canônico (centrado em 0,0; vão ±106 em x, ±48 em y; stroke-width 13 = peso médio):

```
M0,0 C-32,-48 -106,-48 -106,0 C-106,48 -32,48 0,0 C32,-48 106,-48 106,0 C106,48 32,48 0,0 Z
```

### Estado vivo — repouso × trabalhando
- **Repouso:** ∞ calmo, traço teal sólido.
- **Trabalhando:** **"forma e dissolve"** — o laço se desenha do zero, fica **inteiro aceso por
  um instante** (o "selo" da marca) e dissolve pelo mesmo caminho. Ritmo **lento e espacial**
  (~6s, `ease-in-out`), pra gerar calma — "o sistema trabalha em silêncio", não corre.
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
- **Anéis lado a lado:** não liam como infinito (pareciam dois "o" soltos).
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
