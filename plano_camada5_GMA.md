# Plano da Camada 5 — A Plataforma GMA

> Blueprint da construção do GMA como **software profissional**. Documento de planejamento.
> Criado na sessão 20 (2026-06-10). Referência do agente `plataforma-gma`.
> **Estado: PLANEJAMENTO.** Não há construção de produto em curso — seguimos no laboratório.

---

## 0. A virada (por que este documento existe)

Até a sessão 19, o GMA foi um **protótipo**: scripts Python soltos, rodados pelo terminal,
validados com cartões reais (GoPro 7,7 GB; Sony "Joe" 1,6 GB). O protótipo **provou que o conceito
funciona** — o ciclo de vida completo do cartão roda, e as três telas leem de uma fonte única.

A Camada 5 é a virada de **protótipo → produto**: transformar isso num **programa profissional,
consistente e integrado**, que o operador abre e usa sem depender do terminal nem do Claude.

> Decisão do idealizador (sessão 20): a Camada 5 **não é sobre beleza** (isso é a Camada 7 / marca,
> prazo 20/06). É sobre **consistência, robustez e integração** — "um programa consistente, sem
> falhas, com a integração necessária para todos os níveis do processo".

---

## 1. O que a plataforma precisa entregar

Um programa único que, ao abrir, sobe tudo e entrega, **integrado**:

| # | Funcionalidade | Hoje (protótipo) |
|---|---|---|
| 1 | 🎛️ Tela do Operador (controle + edições) — máquina principal | `flask_gma.py` `/` (parcial, lê filas JSON) |
| 2 | 🖥️ Tela de Monitoração — 2ª tela / 2ª máquina (rede local) | `/kanban` (rascunho, lê do banco) |
| 3 | 📊 Planilha de entrega — local + Google Sheets real | `/planilha` (local) + `exportador_sheets.py` (sem credenciais) |
| 4 | 📥 Recebimentos externos — Forms/Tally, post-its, profissionais | `/forms`, `/forms/tally`, post-it no Kanban |
| 5 | 🚪 Acesso à máquina — Porteiro detecta cartões | `porteiro.py` |
| 6 | ✂️ Parashoot por dentro do fluxo | `auditoria.py` (CLI testado) |
| 7 | 🔁 Multi-máquina — 2–3 máquinas/cartões simultâneos | **não existe** (o grande desafio da C5) |

---

## 1.1. Princípios reportados na sessão 21 (idealizador) — a C5 deve carregar

### A) Multi-projeto: **cada trabalho é um novo projeto de sistema**

Insight do idealizador: "sempre haverá um novo projeto de sistema para cada trabalho que se
desenvolve no sistema". Ou seja, **cada evento/trabalho = uma nova instância** do GMA — não é o
mesmo banco crescendo para sempre. Implicações para a C5 (todas via **configuração externa**, não
recompilação):

- **Novo projeto do zero, fácil:** nome do evento, pasta de destino, banco próprio (`gma.db` por
  trabalho), contadores zerados, rótulos da ficha (lacunas de contexto: festival ≠ congresso —
  ver [[modelo-ficha-por-trabalho]]), senha e túnel daquele evento.
- **Isolamento entre trabalhos:** um evento não contamina o outro (numeração, perfis, planilha).
- Conecta com a config externa já prevista (seção 2) e com a memória `camada5-escopo-configuracao`.
- **Aberto:** os perfis aprendidos por nome ([[perfil-do-profissional]]) são por-trabalho ou
  acumulam entre trabalhos do mesmo profissional? A decidir no desenho da C5.

### B) Acesso remoto **por papel** (dois links com escopos diferentes)

Disparado pelo teste do túnel (ficha online). Régua: **a operação completa fica só na BASE
(localhost); quem chega de fora é restrito por papel.**

- **Papel CÂMERA (link público):** só o **preenchimento da ficha** (`/ficha` + webhooks). **JÁ
  implementado no laboratório** (sessão 21): escopo por origem no `flask_gma.py` — acesso remoto a
  qualquer tela de operação dá 403; a raiz redireciona para `/ficha`. Fecha o risco de mexerem no
  Porteiro pela internet.
- **Papel SUPERVISÃO/GERÊNCIA (2º link, a desenhar):** **monitoramento remoto** do processo —
  ver Kanban/Planilha/status de longe, **read-only**, **sem** controle do Porteiro. É a "tela de
  monitoração" (item 2) exposta com escopo próprio. Provável evolução: escopo por **credencial/papel**
  (cada link tem sua senha → seu escopo), não só por origem.
- **QR code da ficha — FEITO (sessão 21):** painel na janela de Acompanhamento (`/kanban`), QR
  gerado por **segno** (Python puro/offline, SVG embutido). Link resolvido por
  `_descobrir_link_ficha()`: override `GMA_LINK_FICHA` **ou auto-detecção** da URL ativa do ngrok
  (API local `127.0.0.1:4040`, cache ~20s) — o QR se atualiza sozinho quando o túnel muda de endereço.
- **MURAL DOS CÂMERAS (a "janela de status") — DESENHO aprovado, a construir (sessão 21):** a metade
  **read-only** do Acesso 2, virada para o set num **2º monitor em tela cheia**. É a comunicação de
  status dos cartões para os câmeras ("meu material já está salvo?") e também serve a quem injeta/ejeta
  (verde = pode mexer; laranja = não toque). Distinta do `/kanban` do operador (que mantém o post-it
  editável). Características desenhadas:
  - **Linguagem de câmera** (traduzir o status técnico): detectado/aguardando → "Recebido"; copiando →
    "Copiando… não retire o cartão"; copiado/verificado → "Material salvo ✅"; concluído → "Concluído —
    pode liberar"; falha → "Procurar o operador".
  - **Cada card:** nome + número (ex.: JOÃO_001) + status grande/colorido. O **QR fixo** nesta tela.
  - **Auto-refresh**, alto contraste, fontes grandes (tela de parede).
  - **Layout: EM ABERTO** — lista por nome (estilo painel de aeroporto) × colunas read-only; não
    decidido ainda.
  - **Privacidade:** mostra nomes de todos; se a tela ficar muito exposta, reduzir a nome+número.
  - **2º monitor automático** (abrir em tela cheia no display certo ao ligar) = empacotamento da C5.
- **Pré-requisito atravessado:** ir para a internet exige `GMA_SENHA` (Basic Auth) — princípio
  inegociável "nunca expor o Flask sem autenticação".

---

## 2. Decisão de stack (justificada)

**Python continua o cérebro.** Critérios do idealizador: segurança, adaptabilidade, integração
com o Parashoot.

- **Segurança** — ciclo 100% local, nada na internet, auditável; offline-first. Trocar de
  linguagem reintroduziria bugs já caçados (zumbis, detecção GoPro, fallback de cópia, JSON-por-
  linhas do Parashoot).
- **Adaptabilidade** — sistema modular por camadas; regras mudam por **configuração**, não por
  recompilação.
- **Parashoot** — app Mac com CLI; integra via `subprocess`, já testado (sessão 16).

**Componentes do "programa":**

| Peça | Papel | Em português claro |
|---|---|---|
| Flask local | Servidor das telas + webhooks | Já existe; mantém |
| pywebview | Janela nativa do Mac | O painel abre como programa, não como aba de navegador |
| py2app / PyInstaller | Empacotamento | Gera o `GMA-TESTE.app` clicável |
| Configuração externa | Ajustes fora do código | Arquivo editável por máquina/evento (caminhos, porta, evento, rótulos, segredos) |
| Supervisor | Orquestra os processos | Sobe os filhos e **reergue** qualquer um que caia |

---

## 3. Estrutura profissional proposta (rascunho — a refinar na Fase 0)

```
GMA-TESTE/                      (nome provisório; final com a Camada 7)
├── gma/                        ← o pacote Python (o cérebro)
│   ├── camada1_checkin/        ← porteiro, leitor, matcher
│   ├── camada2_transferencia/  ← copiador, transferência, relatório
│   ├── camada3_banco/          ← banco, exportador sheets
│   ├── camada4_auditoria/      ← auditoria + Parashoot
│   ├── web/                    ← Flask + templates das 3 telas
│   ├── nucleo/                 ← supervisor, configuração, logging
│   └── config.py               ← carrega a configuração externa
├── config/                     ← ajustes por máquina/evento (.env, evento.toml)
├── dados/                      ← gma.db, contadores, filas (fora do código)
├── testes/                     ← testes de regressão automatizados
├── dist/                       ← o .app empacotado
├── docs/                       ← guia de instalação e operação
└── GMA.command / main.py       ← ponto de entrada
```

> Princípio: **separar o cérebro (gma/) da configuração (config/) e dos dados (dados/)**.
> É o que dá adaptabilidade (muda config sem tocar no código) e segurança (dados isolados).

---

## 4. Roteiro de fases (cada fase = um entregável testável)

| Fase | Nome | Entregável | Pré-requisito |
|---|---|---|---|
| 0 | **Fundação** | Pasta nova + estrutura + este blueprint refinado + config externa desenhada | Sair da fase de teste |
| 1 | **Migração do núcleo** | Camadas 1–4 na nova casa, rodando idêntico ao protótipo, com config externa | Fase 0 |
| 2 | **Robustez** | Supervisor + erro tratado + logging central + testes de regressão | Fase 1 |
| 3 | **Empacotamento** | `GMA-TESTE.app` clicável + janela nativa + guia de instalação | Fase 2 |
| 4 | **Multi-máquina + integrações** | Modelo cliente-servidor na rede; Google Sheets real; Forms/Tally em produção | Fase 3 |

---

## 5. O "sem falhas" — o que significa robustez aqui

Software 100% sem falha não existe. O que a C5 entrega:
- **Erro tratado em cada ponto crítico** — nada de stacktrace na cara do operador.
- **Processos que se recuperam** — o supervisor reergue um processo que caiu.
- **Testes de regressão** — uma bateria automatizada que pega quando uma mudança quebra algo
  que funcionava (já há semente: `teste_copiador_politica.py`).
- **Logging central** — um lugar para ver o que aconteceu quando algo der errado.
- **Princípio inegociável** — nunca destruir mídia; em dúvida, não destrói.

---

## 6. Multi-máquina — o desafio maior (a desenhar)

A parte mais difícil e ainda não resolvida. Perguntas em aberto:
- **Modelo:** 1 máquina = SERVIDOR (banco + núcleo); as outras = TERMINAIS (telas pela rede)?
  Ou cada máquina roda uma instância e elas sincronizam?
- **Numeração compartilhada:** como `JOAO_003` numa máquina não colide com `JOAO_003` em outra?
- **Banco único vs. réplicas:** o `gma.db` fica numa máquina e as outras leem pela rede, ou cada
  uma tem o seu e há sincronização?
- **Consistência:** dois cartões com o mesmo nome de volume ("Untitled") não podem colidir
  (dívida da C3 — ver `banco-reuso-registro-volume`); resolver com identidade real do cartão.

Recomendação inicial: **começar simples** — 1 máquina servidora sólida + 2ª/3ª máquinas como
**monitoração (read-only)** pela rede. Multi-máquina-com-escrita (cada uma conectando cartões)
fica para depois, com desenho dedicado.

---

## 7. Testes e alinhamentos pendentes ANTES de construir

Decididos pelo idealizador na sessão 20 — o laboratório precisa passar por isto primeiro:
- [ ] **Rodar 2 a 3 cartões ao mesmo tempo** — testar capacidade da máquina e concorrência
      (I/O das cópias paralelas, banco em WAL, ambiguidade do Matcher com vários cartões).
- [ ] **Alinhar pontos em aberto** (o idealizador quer revisar alguns) — registrar aqui conforme
      surgirem.
- [ ] Confiança suficiente no protótipo para então fundar o produto.

Outros já mapeados (dívidas que a C5 deve carregar):
- Consistência do banco por identidade real do cartão (não pelo nome do volume).
- Identidade do cartão em camadas no Matcher (serial → assinatura → código → operador).
- Migrar o painel de Operação para ler do banco (hoje lê filas JSON).
- Refinar informações/colunas das telas (Kanban e Planilha) — pendência da sessão 19.
- **Multi-projeto por trabalho** (seção 1.1.A) — "novo projeto do zero" como configuração externa.
- **Papel SUPERVISÃO remoto** (seção 1.1.B) — 2º link read-only de monitoramento, escopo por papel.
- **QR code do link da ficha + janela de status do câmera** (seção 1.1.B) — desenhar juntos.

---

## 8. Princípio de migração (segurança)

- A pasta `/Users/serafa/GMA/` (laboratório) fica **intocada** durante toda a migração —
  protótipo validado + documento mestre + organograma.
- O produto nasce na pasta nova (`GMA-TESTE`), **copiando camada por camada**, com refatoração e
  testes.
- **Nada que funciona é apagado** até o produto estar provado tão robusto quanto o protótipo.
- A aposentadoria da pasta `GMA/` só acontece por **decisão explícita** do idealizador.

---

## 9. Estado e próximo passo

- **Estado:** PLANEJAMENTO. Produto não iniciado. Laboratório ativo em fase de teste.
- **Agente responsável:** `plataforma-gma` (criado na sessão 20).
- **Próximo passo concreto:** rodar o teste de 2–3 cartões simultâneos no laboratório e fechar os
  alinhamentos pendentes. Só então a Fase 0 (Fundação) começa.
