# Documento Mestre — Sistema GMA
## Gerenciamento de Mídia Audiovisual para Eventos ao Vivo

> Documento de arquitetura e estado do projeto. Serve como contexto completo para
> continuar o desenvolvimento (inclusive em sessões do Claude Code).
> Última atualização: 2026-06-14 (sessão 25 — BUILD: Passo 2 do Matcher IMPLEMENTADO e testado ponta a ponta. Tabela `match_candidatos` (que estava só desenhada, nunca criada) construída; `confirmar_match` atômica; Matcher persiste candidatos no empate + função de confirmação manual; painel com botões, tela de resumo (destino previsto) e disparo da transferência. 2 bugs pegos pelo teste de ciclo e corrigidos.)

## Estado atual (2026-06-14)

**✅ Sessão 25 (2026-06-14) — BUILD: Passo 2 do Matcher (resolução de empate no painel):**

Sessão de **build**, conduzida pelo orquestrador delegando aos agentes `banco-dados-gma` (banco + Flask)
e `checkin-gma` (Matcher), seguindo o desenho aprovado na sessão 24 (`desenho_passo2_matcher_GMA.md`).
Fecha a pendência aberta desde a sessão 13: o operador agora resolve empates de match com poucos cliques.

- **Pedra no caminho corrigida na largada:** o desenho (§4) afirmava que a tabela `match_candidatos`
  "já existia desde a sessão 18". **Não existia** — a sessão 18 foi só de desenho. O `gma.db` só tinha
  `matches`. Primeira tarefa do build virou **criar a tabela que faltava** (DDL + migração não-destrutiva
  `migrar_schema_match_candidatos`, chamada por `inicializar_banco`; o `gma.db` existente ganhou a tabela
  sem perder dados). Colunas: `cartao_id, formulario_id, nome, camera_ficha, score, criterios,
  status (pendente/escolhido/descartado), criado_em`; `UNIQUE(cartao_id, formulario_id)`.
- **Etapa 1 — banco (`banco_dados.py`):** `registrar_candidatos(conn, cartao_id, candidatos)` (idempotente,
  INSERT OR IGNORE) e `confirmar_match(conn, cartao_id, nome_escolhido)` **atômica** — grava o match
  confirmado (`confirmado=1`), marca o escolhido `escolhido` e os demais `descartado`, e **libera as
  fichas descartadas** (`formularios.status → aguardando_match`). `gravar_match` ganhou parâmetro opcional
  `confirmado` (caminho automático intocado).
- **Etapa 2 — Matcher (`matcher.py`):** no empate, o Matcher agora **persiste os candidatos** na tabela
  (`registrar_candidatos`), não só no JSON. Nova função `confirmar_par_manual(cartao_id, nome_escolhido)`
  que espelha o caminho automático (marca o JSON do material `matched` → **dispara a Transferência**),
  chama `confirmar_match` e `atualizar_perfil` (fecha o TODO antigo do `matcher.py`).
- **Etapa 3 — painel (`flask_gma.py`):** a seção "Aguardando confirmação" virou **blocos por cartão**
  (cabeçalho volume · nº arquivos · câmera + sub-bloco por candidato com nome · câmera da ficha ·
  **pista dos nomes de arquivo** + botão "Confirmar [NOME]"). Rota `POST /match/<id>/confirmar` →
  **tela de resumo** (nome · câmera · nº arquivos · **pasta de destino prevista** `NOME_NNN`), e só então
  `POST /match/<id>/iniciar` executa a confirmação. As rotas `/match/*` são de operação (403 no acesso
  remoto do câmera, como manda a sessão 21).
- **Pista dos nomes de arquivo (ajuste do orquestrador):** o desenho supunha uma lista de nomes de
  arquivo no JSON do material — **ela não existe**. A pista real são os radicais em `assinatura.prefixos`
  (ex.: `joe0258T · joe0259T · joe0260T`), que o Leitor já grava. O painel passou a ler de lá.
- **2 bugs pegos pelo teste de ciclo (os autotestes isolados dos agentes não pegaram):** (1) o painel
  quebrava (500) porque a função `painel()` tinha uma variável local `html` que sombreava o módulo
  `html` da stdlib usado em `html.escape` nos helpers aninhados → variável de página renomeada para
  `pagina_html`; (2) o Matcher **não gravava** os candidatos porque a Tarefa A reusava a sentinela
  `materiais_ambiguos_marcados` (já preenchida ao marcar o JSON na mesma iteração) → criada sentinela
  própria `materiais_candidatos_persistidos`. Lição: os autotestes injetavam linhas falsas em
  `match_candidatos`, pulando os caminhos reais de integração; **só o teste ponta a ponta (Matcher real
  + Flask real) revelou as falhas.**
- **Testado ponta a ponta (21 verificações, todas OK):** empate real entre 2 fichas (JOAO×PAULO) por
  1 cartão → Matcher marca `aguardando_confirmacao` e grava 2 candidatos `pendente` → painel mostra os
  blocos com a pista e os botões → tela de resumo mostra destino `JOAO_001` **sem confirmar ainda** →
  "Iniciar" grava match `confirmado=1`, JOAO `escolhido`, PAULO `descartado`, ficha do PAULO liberada,
  JSON do material `matched` (gatilho da cópia), perfil do JOAO atualizado. **Laboratório limpo** ao fim
  (todo registro/arquivo de teste removido; `gma.db` e filas idênticos ao estado inicial).
- **Arquivos tocados:** `banco_dados.py`, `matcher.py`, `flask_gma.py`. **Sem commit ainda** (a critério
  do idealizador).
- **⏭️ PRÓXIMO PASSO:** validar a tela com um empate de cartão **real** no fluxo ao vivo (o teste foi com
  fixtures forjadas, fiéis ao que o Matcher produz). Alternativa de build desbloqueada: Fatia 1 da Nova
  Ficha v2 (tabela `profissionais`), ver `desenho_nova_ficha_v2_GMA.md` §11.

**📐 Sessão 24 (2026-06-14) — DESENHO: Passo 2 do Matcher (botão de resolução de empate):**

Sessão de **desenho** (sem build), conduzida pelo orquestrador com o idealizador. Objetivo: fechar
o desenho do **Passo 2 do Matcher** — o botão que permite ao operador resolver empates de match com
1 clique no painel. Pendência aberta desde a sessão 13 e explicitamente adiada na sessão 23.

- **O que já existia:** Passo 1 (sessão 13) entregou a lógica de empate segura — cartão marcado
  como `aguardando_confirmacao`, candidatos salvos em `match_candidatos`, evento `match_ambiguo`
  no banco, seção no painel só leitura. O operador via o empate mas não conseguia resolver.
- **O que o operador vê:** para cada cartão ambíguo, o painel exibe cabeçalho (volume · nº arquivos
  · câmera detectada) + lista de candidatos, cada um com nome · câmera da ficha · **3–4 primeiros
  nomes de arquivo do cartão** (ex: `joe0258.mp4`) como pista de identificação + botão
  "Confirmar [NOME]". A pista dos nomes de arquivo é o que desempata na prática de set.
- **Fluxo de confirmação (2 passos, decisão do idealizador):** (1) operador clica "Confirmar JOAO"
  → sistema mostra **tela de resumo enxuta**: nome · câmera · nº arquivos · **pasta de destino
  prevista** (ex: `JOAO_002`) — confirmação do destino considerada útil pelo idealizador;
  (2) operador clica "Iniciar transferência" → sistema registra match, descarta candidatos, dispara
  fluxo normal. Motivo do passo extra: match errado gera pasta errada no HD; custo de 1 clique a
  mais é baixo, custo de erro é alto.
- **Candidatos descartados:** ficam na tabela `match_candidatos` com status `descartado` —
  auditável, rastreável. Fichas voltam a `aguardando_match`, livres para o próximo cartão.
  Tabela `match_candidatos` já foi desenhada na sessão 18 com este campo — build só usa o que existe.
- **Perfil:** ao confirmar, chama `atualizar_perfil(nome, assinatura)` — já previsto na sessão 13.
- **Arquivos tocados no build:** `flask_gma.py` (rota `POST /match/<id>/confirmar` + telas),
  `matcher.py` (função de confirmação manual), `banco_dados.py` (função `confirmar_match` atômica).
- **Status:** desenho aprovado, **NÃO implementado**. Referência: `desenho_passo2_matcher_GMA.md`.
- **⏭️ PRÓXIMO PASSO (próxima sessão de build):** implementar o Passo 2 via agentes `checkin-gma`
  + `banco-dados-gma`. Sem bloqueios — pode iniciar direto. Fatia 1 da Nova Ficha v2 (tabela
  `profissionais`) permanece como alternativa de build igualmente desbloqueada.

**📐 Sessão 23 (2026-06-12) — DESENHO: Nova Ficha v2 (duas caras, ordem tipo→nome, câmera pelo Leitor):**

Sessão de **desenho** (sem build), conduzida pelo orquestrador com o idealizador. Objetivo entregue:
fechar o desenho da **Nova Ficha v2** e gravá-lo em `desenho_nova_ficha_v2_GMA.md` (referência para o
build da próxima sessão). Disparada pelo pedido de "adicionar botões com funções e melhorias nas janelas".

- **Duas caras da ficha (mesma rota `/ficha`):** cara **CÂMERA** (remoto/túnel) vs. cara **OPERADOR**
  (base/localhost), com regras diferentes de campo — aprofunda o portão por papel da sessão 21.
- **NOME:** câmera usa **dropdown fechado** (não digita, não cria) — acaba a bagunça de nomenclatura;
  operador cria/edita. Dropdown de nome **filtrado pelo tipo** marcado.
- **CÂMERA/MODELO:** sai da ficha — **detectada pelo Leitor de Mídia (C1)**; só vira pergunta (com
  **aviso ao operador**) se o Leitor não detectar. **Resolve a tensão da sessão 13** (câmera segue
  dos dois lados do match, mas o câmera-pessoa não digita).
- **TIPO DE MATERIAL:** vira **multi-seleção** (Áudio/Foto/Vídeo) — material misto.
- **Ordem de preenchimento (insight do idealizador):** 1º tipo, depois nome. Foto/Vídeo → 1 dropdown
  de nome; Foto/Vídeo **+ Áudio** → **2 dropdowns** (o áudio quase sempre é outra pessoa — gravador).
- **Cadastro de profissional (Operação):** só por **tipo (F/A/V)** — nome + caixinhas. Câmera e
  materiais **variam**, não se amarram à pessoa (o perfil aprendido segue acumulando por baixo).
- **Decisões batidas:** (1) **login multiusuário** = ❌ agora, **radar da C5**; (2) **câmera pelo
  Leitor** = ✅; (3) **encoding da multi-seleção** = **FECHADO** — *conjunto fixo pequeno (Tipo A/F/V)
  = colunas booleanas (tem_audio/tem_foto/tem_video); lista aberta (marcas) = lista estruturada (JSON),
  exibida com `·`; **nunca por espaço***. Booleanos facilitam contar na planilha, ajudam o Matcher e
  são iguais ao cadastro de profissional (consistência); (4) **cadastro só por tipo** = ✅.
- **Ponta solta resolvida (JSON×banco×IA):** caminho recomendado = **unificar a leitura no banco**
  (Operação ainda lê filas JSON; Kanban/Planilha já leem o banco). IA lê **banco + planilha +
  manifesto**, nunca os JSON espalhados, nunca a mídia bruta. Fica no radar junto do encoding.
- **Adiado para próxima sessão (a pedido do idealizador):** Mural dos câmeras (2º monitor) + revisão
  das demais janelas; **menu de funções na Operação + botão do Matcher** (resolver ambíguo com 1
  clique — Passo 2 do Matcher).
- **Status:** desenho aprovado, **NÃO implementado**. Referência: `desenho_nova_ficha_v2_GMA.md`
  (inclui o plano de build em fatias, §11). Memória: `nova-ficha-v2-desenho`.
- **⏭️ PRÓXIMO PASSO (próxima sessão) = FATIA 1 do build:** tabela `profissionais` por tipo (nome +
  colunas booleanas `tem_foto`/`tem_audio`/`tem_video`) + funções criar/listar/filtrar — em C3, via
  `banco-dados-gma`. É a fundação do dropdown de nome filtrado e usa o mesmo mecanismo do §7. Livre
  (sem bloqueios). Teste: criar 3 profissionais e listar "só áudio". Demais fatias (2–5) em
  `desenho_nova_ficha_v2_GMA.md` §11.

**🗺️ Sessão 22 (2026-06-12) — Consulta à Camada 5: estimativa, configuração, ampliação de escopo e segurança/licenciamento:**

Sessão de **PLANEJAMENTO** (sem código de produto). O idealizador consultou o agente `plataforma-gma`
sobre quatro frentes; decisões tomadas e registradas nos mapas (`plano_camada5_GMA.md` §1.2, §4 e §6.1).

- **(1) Estimativa de construção (Fases 0→4):** ~**13–24 sessões** de trabalho e ~**2,2M–4,5M tokens**
  no total, quebrado por fase no `plano_camada5_GMA.md`. Premissa-chave: **migrar** ~12.650 linhas já
  validadas ≠ escrever do zero; teste e idas-e-voltas consomem mais token que código novo. Maior
  incerteza: **Fase 4 (multi-máquina com escrita)**. São faixas, não promessa de precisão.
- **(2) Configuração pós-pronto:** modelo de **configuração externa** (separar cérebro/config/dados).
  O idealizador edita dois arquivos de texto — `evento.toml` (nome do evento, pasta destino, banco do
  trabalho, porta, rótulos da ficha, 2º monitor) e `.env` (senha, credenciais) — **sem tocar no
  código**. Iniciar novo trabalho = copiar a config, trocar 3–4 linhas, apontar banco novo (zera só).
- **(3) Ampliação de escopo da C5 [DECIDIDO]:** a C5 passa a ser dona também das **janelas/abas** —
  abre as telas via **pywebview** (janela nativa), entrega **tempo real** via **SSE** (cópia e edições
  atualizando só o card que muda, sem recarregar), abre o **2º monitor** (Mural dos Câmeras) e é a
  **porta de despacho** para a IA da Camada 6 (enfileira manifesto + miniaturas; **mídia bruta nunca
  sai da máquina**). Fronteira mantida: lógica é das camadas 1–4/6; orquestração/janelas/portas é da C5.
- **(4) Segurança & licenciamento [DECIDIDO — honestidade técnica]:** Python é interpretado → **não há
  proteção de código inviolável**. O que **protege de verdade**: licença por máquina + separação
  cérebro/dados (+ Nuitka se houver venda ampla). O que é **teatro**: senha no `.app`, "criptografar" o
  Python. **Keygen por tempo limitado = FUTURO (Fase 4+)**, chave assinada com verificação
  **offline-first** (não trava o ciclo por falta de Wi-Fi). **Integração com APIs**: sempre por **fila
  assíncrona**, credenciais no `.env`, **mídia nunca viaja**. Detalhado em `plano_camada5_GMA.md` §6.1.
- **Decisões do idealizador nesta sessão:** **perfis dos profissionais ZERAM a cada evento**
  (isolamento total — coerente com "cada trabalho é um novo projeto"; resolve o "Aberto" do
  `plano_camada5_GMA.md` §1.1.A). **Distribuição (produto p/ terceiros × ferramenta interna):
  INDECISO** → keygen/licença ficam como possibilidade futura, sem comprometer o roteiro agora.
- **Estado:** segue **PLANEJAMENTO** — produto não iniciado; laboratório ativo. Próximo passo de produto
  permanece: rodar **2–3 cartões simultâneos** e fechar alinhamentos antes da Fase 0.

**✅ Sessão 21 (2026-06-10) — Ficha de check-in DENTRO do GMA (entrada própria, gabarito, edição, online):**

A Camada 1 deixou de depender **só** de ferramentas externas (Google Forms/Tally) para a entrada
de dados: agora existe uma **tela de inserção própria**, servida pelo Flask, alimentando a MESMA
função central já testada (`_processar_e_salvar_formulario`). Pedido do idealizador: "ter também a
tela para inserção de informações" + deixá-la online.

- **Decisão de canais (fechada com o idealizador):** **a nossa ficha (Flask) é o canal PRINCIPAL**
  — local + online — e é onde vivem o gabarito e a edição; **o Tally fica como canal de RESERVA**
  (rede de segurança: a nuvem dele reentrega o webhook se a base piscar offline). Motivo: editar
  uma ficha e montar gabaritos dinâmicos exige ler/gravar o *nosso* banco — o Tally só envia, nunca
  edita nossos registros. Respeita a fronteira C1↔C3 (sessão 18): perguntas/edição = C1; transporte
  (webhook/túnel) = C5; normalização na entrada = uma função só, que os dois canais já usam.
- **`GET/POST /ficha` (nova):** página de formulário no padrão visual das outras telas (núcleo
  obrigatório nome★/câmera★/tipo★/data★ + editoriais). Aba **"Nova Ficha"** somada à barra. Erro de
  validação volta na própria tela sem perder o digitado; sucesso mostra confirmação + nº de matches.
- **Gabarito (selecionável que aprende):** nome/câmera/modelo viram **datalists** (dropdown que
  também aceita digitar), alimentados pelos valores **distintos já no banco** (`_sugestoes_gabarito`).
  Quanto mais o sistema roda, mais ele sugere. Degrada para digitação livre se o banco falhar.
- **Edição de fichas (`GET/POST /ficha/<id>/editar`):** lista de **fichas recentes** com link
  "editar"; formulário pré-preenchido. Nova função C3 `atualizar_formulario(conn, id, campos)`
  (whitelist de colunas + evento `formulario_editado`) espelhando `atualizar_cartao`. A fila JSON é
  sincronizada (`_atualizar_json_fila`) para o Matcher/Transferência verem o mesmo dado.
  - **Trava de segurança (princípio nº 2):** se a ficha **já casou** (status fora de
    `STATUS_FICHA_LIVRE`), os campos críticos (nome/câmera/tipo/data) ficam **travados** — mexer
    neles afetaria a numeração e a pasta no HD. Defesa **no servidor** (não confia só no `disabled`
    do HTML): o POST descarta esses campos. Só os editoriais passam. Testado: tentativa de trocar o
    nome de uma ficha matched foi ignorada; obs mudou.
- **Caminho para "online" (Camada 5, prep feito):**
  - **`GMA_HOST`/`GMA_PORT`** configuráveis (padrão SEGURO `127.0.0.1`). `GMA_HOST=0.0.0.0` libera a
    ficha na **rede local** (celulares no Wi-Fi do evento → `http://IP_LOCAL:5050/ficha`). Capacidade
    pronta, **não ligada** (idealizador ainda decide).
  - **`GMA_SENHA` (portão Basic Auth):** pré-requisito do princípio inegociável "nunca expor o Flask
    à internet sem autenticação". Vazia → uso local livre; definida → navegador pede senha em todas
    as telas; webhooks `/forms*` isentos (têm HMAC). Testado (401 sem/errada, 200 com a certa,
    webhook não bloqueado). Documentado no `.env.exemplo`.
  - **Internet via túnel — TESTADA AO VIVO:** ngrok instalado (`brew`), authtoken do idealizador
    registrado, túnel temporário no ar. Ficha aberta pela internet **com senha** (`.env` criado,
    `GMA_SENHA=gma123` provisória). Sem domínio fixo por ora (idealizador dispensou) → URL temporária.
- **Acesso remoto POR PAPEL (decisão + implementação, sessão 21):** o idealizador definiu que o link
  público é **só para câmeras preencherem a ficha**, e teve a ideia de um **2º link de supervisão**
  (monitoramento remoto). Régua: **operação completa só na BASE (localhost); remoto é restrito por
  papel.** Implementado o **papel CÂMERA** (`_portao_de_acesso` + `_remoto_pode_acessar`): o acesso
  remoto só alcança **`/ficha` exato** (ficha NOVA — GET do formulário + POST do envio) e webhooks
  `/forms`; **tudo mais → 403**, raiz redireciona à ficha. Reforço de UI no remoto: somem a lista de
  **"fichas recentes"**, as **abas** de navegação e os botões de gestão — o câmera **não vê nem edita**
  fichas alheias. A **edição** (`/ficha/<id>/editar`) é **só na BASE**. Testado pela URL real do ngrok:
  `/ficha` 200 (sem recentes/abas); `/ficha/<id>/editar`, `/kanban`, `/porteiro/ativar` **403**; base
  intacta. Fecha o risco de mexerem no Porteiro **e** de editarem fichas alheias pela internet.
  **QR code da ficha — FEITO:** painel na janela de Acompanhamento (`/kanban`) com o QR do link
  público (gerado por **segno**, Python puro/offline, SVG embutido — sem serviço externo). O link é
  resolvido por `_descobrir_link_ficha()`: override `GMA_LINK_FICHA` **ou auto-detecção da URL ativa
  do ngrok** (API local `127.0.0.1:4040`) — o QR se atualiza sozinho quando o túnel muda de endereço,
  sem editar o `.env`. Testado (detecta a URL viva; segue a mudança). **MURAL DOS CÂMERAS** (a metade
  read-only do Acesso 2, num 2º monitor, status em linguagem de câmera + QR fixo): **DESENHO aprovado,
  a construir** — layout (lista × colunas) em aberto; detalhado em `plano_camada5_GMA.md` §1.1.B.
  **Papel SUPERVISÃO:** ainda a desenhar (C5).
- **Reportado ao agente C5 (`plano_camada5_GMA.md` §1.1):** (A) **multi-projeto** — cada trabalho é
  uma nova instância do GMA (config externa por evento); (B) **acesso remoto por papel**. Memórias:
  `ficha-canais-decisao`, `multi-projeto-por-trabalho`.
- **Arquivos tocados:** `flask_gma.py` (rotas + gabarito + edição + portão de acesso/senha + escopo
  remoto + host configurável), `banco_dados.py` (`atualizar_formulario`), `.env.exemplo` + `.env`
  (GMA_HOST/PORT/SENHA), `plano_camada5_GMA.md` (§1.1).
- **Testado:** envio válido/inválido pela ficha; gravação em fila JSON + banco; gabarito do histórico;
  edição livre vs. travada; portão de senha; **escopo remoto (câmera só-ficha) pela internet real**.
  Registros de teste limpos do banco.
- **Fecho da sessão:** mapas atualizados (este documento, `organograma_GMA.md`, `plano_camada5_GMA.md`)
  e memória (`ficha-canais-decisao`, `multi-projeto-por-trabalho`). **Versão salva no git** (commit
  `06de4a0` — também passou a versionar o restante do sistema, antes não rastreado). **README próprio
  do GMA** escrito, substituindo o placeholder de aprendizado (commit `d6953ee`, fecha a branch
  `melhoria/readme`). **Sem PR/push** — ficou para depois, por opção do idealizador.
- **Achado de teste pós-commit + correção (cartão SEM MÍDIA):** num teste, um cartão ARRI físico
  ("MINI") que era só **configuração** (`ARRI/ALEXA/Framelines/`, 0 mídia, 2 XMLs) expôs duas falhas:
  (1) o **Porteiro** decide a marca só pelo nome da pasta (`pasta:ARRI`), sem conferir mídia; (2) o
  **Leitor** detectava "sem mídia" mas só logava — o cartão seguia para o Matcher. **Corrigido na
  Camada 1** (agente `checkin-gma`, 2 etapas): o Leitor agora classifica em **dois níveis** quando
  `total_midia == 0` (conta só VIDEO+FOTO+AUDIO): **`sem_midia`** (conteúdo trivial/config → fim de
  linha, "sem mídia — ignorado", laranja, não entra em match/cópia) e **`revisar`** (há arquivos
  OUTRO **grandes** — possível footage em formato não mapeado → "verificar — arquivos não reconhecidos",
  vermelho, **chama o operador**, não copia). Limiares como constantes (50 MB/arquivo, 500 MB total).
  **Segurança (princípio nº 1):** a lista `EXTENSOES` (ler_cartao.py) é a guardiã — cobre ARRI/RED/
  Blackmagic/etc.; em dúvida o sistema prefere `revisar` a ignorar (nunca pular footage). Testado:
  MINI → `sem_midia`; arquivo .xyz de 60 MB → `revisar`; cartão com mídia → fluxo normal. Memória:
  `cartao-sem-midia`. ⚠️ **Estas mudanças (leitor_midia.py, flask_gma.py) ainda NÃO foram commitadas.**
- **Pendente do teste original:** o ciclo completo de cartão ainda não foi exercitado nesta rodada —
  o Porteiro nem chegou a rodar (só o Flask estava no ar; o sentinela `.gma_ativo` existia, mas o
  processo não). Para testar de verdade: `encerrar_gma.py` → `inicializar_gma.py` e reconectar um
  cartão **com mídia** (o MINI não serve — é de ajustes).

**🔧 Sessão 20 (2026-06-10) — VIRADA protótipo → produto: planejamento da Camada 5:**

O idealizador definiu o objetivo principal: transformar o protótipo (scripts validados) num
**software profissional** — a Camada 5. Decisão de **NÃO construir ainda**: seguimos no laboratório
(pasta `GMA/`), pois faltam testes (rodar 2–3 cartões simultâneos) e alinhamentos. Sessão de
**planejamento + preparação do agente**, sem código de produto.

- **Decisão de stack** (idealizador delegou; critérios: segurança, adaptabilidade, integração com o
  Parashoot): **Python continua o cérebro** — não reescrever, para preservar a validação com cartão
  real. Camada de produto: **Flask** (telas, já existe) + **pywebview** (janela nativa) + **py2app**
  (app `.app` clicável) + **configuração externa** + **supervisor** de processos.
- **Escopo da C5** (o que a plataforma entrega): programa único, robusto e integrado — tela do
  Operador, tela de Monitoração (2ª máquina), planilha de entrega, recebimentos externos
  (Forms/Tally, post-its, profissionais), acesso à máquina (Porteiro), Parashoot no fluxo, e
  multi-máquina (2–3 cartões/máquinas). **Foco: consistência e integração, NÃO estética** (estética
  é a Camada 7, prazo 20/06).
- **Roteiro em 5 fases:** 0 Fundação · 1 Migração do núcleo · 2 Robustez · 3 Empacotamento ·
  4 Multi-máquina + integrações. Cada fase é um entregável testável.
- **Princípio de migração:** laboratório (`GMA/`) **intocado**; o produto nasce na pasta nova
  **`GMA-TESTE`** (nome provisório, o definitivo virá com a C7), copiando camada por camada; nada
  que funciona é apagado.
- **Entregáveis desta sessão:** agente **`plataforma-gma`** (`.claude/agents/`), ciente de tudo e do
  estado de teste; blueprint **`plano_camada5_GMA.md`** (a referência do agente); `CLAUDE.md`
  atualizado (lista de subagentes).
- **Pré-requisitos antes de construir** (decididos hoje): rodar **2–3 cartões simultâneos** no
  laboratório (capacidade + concorrência) e fechar os alinhamentos pendentes.

**✅ Sessão 19 (2026-06-10) — telas "uma fonte → três vistas": Acessos 2 e 3 no ar (C1↔C3 juntas):**

Sessão de integração entre a Camada 1 (Flask/entrada) e a Camada 3 (banco/telas), pedida pelo
idealizador como uma *demonstração do sistema rodando* — poder mandar um formulário e um post-it e
ver refletir nas telas. Construídas as DUAS telas que faltavam, lendo direto da fonte única
(`gma.db`), tudo no `flask_gma.py` (nenhuma mudança no schema do banco):

- **Barra de abas** ligando as três vistas: **Operação** (`/`) · **Acompanhamento** (`/kanban`) ·
  **Planilha de Entrega** (`/planilha`).
- **Acesso 2 — Kanban (`/kanban`):** lê `cartoes` do banco e distribui em 5 colunas (Detectado →
  Match → Copiando → Verificado → Concluído), via `STATUS_PARA_COLUNA`. Auto-refresh de 8 s que
  **pausa** quando o operador está escrevendo um post-it (não perde o texto).
- **Post-it por cartão:** usa a coluna `observacoes` que **já existia** na tabela `cartoes` (zero
  mudança de schema). Rota `POST /cartao/<id>/observacao` → `bd.atualizar_cartao()` → grava no banco
  **e registra evento** (auditoria append-only).
- **Acesso 3 — Planilha (`/planilha`):** JOIN `cartoes` + `matches` + `formularios` (match mais
  recente); 9 colunas (profissional, câmera, tipo, data, nº cartão, nº arquivos, tamanho, status,
  caminho no HD); filtro de busca client-side. É o **espelho local** do que vai para o Google Sheets.
- **Testado ponta a ponta (curl):** `/` (abas), `/kanban` (3 cartões nas colunas certas — JOE_001 em
  Concluído, SONY_CARD e GOPRO_TESTE em Match), `/planilha` (3 linhas); **post-it**: POST no cartão 2
  → gravou em `gma.db` → reapareceu no `/kanban` → evento na tabela `eventos`. Servidor sem erros.
- **Decisão consciente:** o **painel de Operação (`/`) ainda lê as filas JSON**, não o banco — passo
  pequeno, para não mexer no que já funciona. As duas telas novas leem do banco. Unificar o painel
  na fonte única é o passo seguinte natural.
- **Visual de rascunho proposital** (sem identidade visual — isso é o Andar 7). **Pendente para a
  próxima sessão** (a pedido do idealizador): revisar as **informações e colunas** das telas (campos
  do card no Kanban; colunas da Planilha). O evento do post-it hoje é gravado como `status_atualizado`
  (genérico) — dá para criar um tipo `post_it` dedicado.
- **Arquivo tocado:** `flask_gma.py` (3 rotas novas + barra de abas + helpers de UI).

**📐 Sessão 18 (2026-06-10) — DESENHO: fronteira C1 ↔ C3 (a troca de informação nas fichas):**

Sessão de desenho (debate entre os agentes `checkin-gma` e `banco-dados-gma`, mediado pelo
orquestrador). Provocada pela pergunta do idealizador: *"quem cria as fichas? a C3 não deveria
escolher a plataforma e zelar pela integridade, e a C1 cuidar das perguntas e das entregas?"*. Os
dois especialistas CONCORDARAM com essa divisão — que ainda reforça a decisão de 2026-06-07 (escolha
da ferramenta de formulário é da C3). **Aprovado, NÃO implementado** ("aprovo por hora, depois
revemos para não parar a progressão" — é um checkpoint, não um ponto final).

- **A régua da fronteira (quem é dono de quê):**
  - **Perguntas da ficha (o que se pergunta no set) → C1.** C1 propõe; C3 aprova como cada pergunta
    vira coluna/contrato no banco. As perguntas são sinais do Matcher, por isso são da C1.
  - **Plataforma + cano de entrada (Tally/Forms, webhook, formato do payload) → C3.** Guardiã do
    fluxo que entra no banco. Mudança que afete o payload passa pela C1 antes de produção.
  - **"Criar a ficha" tinha 2 sentidos embolados:** bolar as perguntas (C1) ≠ escolher/configurar a
    ferramenta (C3). O **"leitor das fichas"** (recebe o envio do Tally, hoje no Flask) é a JUNTA:
    mora na infra da C1, mas obedece ao contrato da C3.
  - **Validar/normalizar na entrada → uma função só, escrita pela C3, revisada pela C1.** Régua
    única → acaba o risco de a C3 "arrumar" a câmera diferente do que o Matcher espera (medo da C1).
    Rejeita LIXO na porta (ficha sem nome, data inválida), mas a gravação no banco continua
    NÃO-BLOQUEANTE (princípio offline-first nº 1: SQLite engasgado nunca trava o check-in do set).
  - **Identidade do cartão → C1 (Matcher), antes de chamar a C3.** A C3 só aceita cartão já
    identificado; "Untitled" não é problema dela. Conserta o bug do Joe (liga com a sessão 17 e as
    memórias `banco-reuso-registro-volume` / `identidade-cartao-camadas`).
- **Decisões concretas de schema (a implementar):**
  - **Rótulos agnósticos (B):** híbrido — núcleo fixo em colunas (o que o Matcher usa) + gaveta
    `campos_extras` (JSON) para lacunas que mudam por evento (PALCO/ARTISTA ≠ SALA/PALESTRANTE). O
    custo cai todo na C3: o Google Sheets precisa de colunas dinâmicas por evento (lê os rótulos via
    `json_each`). O Matcher continua lendo SÓ as colunas fixas.
  - **Matches ambíguos (C):** nova tabela `match_candidatos` (1 linha por candidato, status
    pendente/escolhido/descartado); a tabela `matches` fica só para os confirmados. Auditável e não
    mexe na tabela atual. Painel/operador resolvem depois (é o Passo 2 do Matcher, ainda pendente).
  - **Contrato de entrada que a C3 exige da C1:** `id_form_original` (gerado pela C1, para dedup de
    webhook), `nome`/`camera`/`data_gravacao`/`tipo_material` obrigatórios e normalizados; transação
    atômica (formulário + evento num commit só).
- **Pendência de coerência revelada:** a descrição do agente `checkin-gma` ainda lista "Google Forms"
  como dele — conflita com "plataforma é da C3". Reconciliar as descrições dos agentes quando esta
  decisão for implementada.
- **Status:** desenho aprovado, NÃO implementado. Memória: `fronteira-c1-c3-fichas`.

**📐 Sessão 17 (2026-06-10) — DESENHO: identidade do cartão em camadas:**

Sessão de desenho (não de implementação), disparada pela dívida de consistência da C3 (cartões com
mesmo nome de volume colidindo — bug do Joe). Decisão de arquitetura e validação com material real.

- **O Matcher passa a ser a AUTORIDADE única da identidade do cartão:** ele decide de quem é o
  cartão e repassa o nome pronto para a C2 (numeração) e a C3 (chave do registro), em vez de a C3
  adivinhar pelo nome do volume. Conserta o bug do "Untitled" na raiz.
- **Identidade = impressão digital em camadas** (Matcher escolhe o sinal mais forte disponível):
  1. **Nº de série do corpo** — se for real. Único por câmera física. **Regra de ouro: ignorar
     placeholder** `4294967295` (0xFFFFFFFF), `0` ou vazio (senão todas as câmeras do mesmo modelo
     colidem — pior que o bug do Joe).
  2. **Modelo + lente + prefixo + faixa de numeração** (assinatura que a C1 já extrai). Caso comum.
  3. **Código na ficha** (campo novo) e/ou **prefixo customizado** (ex. `CAD_` = iniciais do Cadu na
     câmera) → âncora humana na 1ª entrega; o Matcher amarra código ↔ assinatura.
  4. **Operador casa card↔ficha na mão** → último recurso, só nos empates reais (decisão: confirmar
     só quando há dúvida, não sempre).
- **Validado com exiftool em material real:** Sony FX3 (Joe) → modelo+lente OK, mas serial MASCARADO
  (`4294967295`). Nikon Z6_3 (Cadu) → serial REAL (`3003572`) + lente + Shutter Count (contador do
  corpo que nunca zera). **Conclusão: serial varia por marca** — por isso o desenho em camadas.
- **Status:** desenho aprovado, NÃO implementado. Construção futura: lógica de identidade em camadas
  no `matcher.py` + campo de código na ficha (Tally) + chave de identidade da C3. Memória:
  `identidade-cartao-camadas` e `banco-reuso-registro-volume`.

**⏭️ PRÓXIMO PASSO concreto:** passar o cartão **`CADU_03`** (Nikon, foto, serial válido — hoje solto
na raiz de `TESTE LOGAGEM/` sem a estrutura `DATA/TIPO/NOME/`) pelo **fluxo real de ponta a ponta**.
Seria o 2º teste real do sistema (o 1º foi a Sony do Joe), exercitando vídeo→foto, outra marca, e o
serial válido — base prática pra implementar a identidade em camadas.

**✅ Sessão 16 (2026-06-09) — TESTE DE CICLO COMPLETO com cartão real (Sony "Joe"):**

Primeiro teste de ponta a ponta com cartão físico real, exercitando todas as funções operacionais.
Cartão Sony (`PRIVATE/SONY` + `M4ROOT`), 57 arquivos de mídia / 1,6 GB (17 clipes MP4 `joe0258`–`joe0274`
+ XMLs + thumbnails), gravação real 2025-08-05.

**Ciclo executado (tudo funcionou na prática):**
1. **Porteiro** detectou o cartão (Sony, via `pasta:PRIVATE`) após desmontar/remontar (ele ignora
   volumes já montados na largada — por isso o `diskutil unmount`+`mount` para simular reconexão).
2. **Leitor** analisou: detectou Sony, extraiu assinatura (prefixo `joe`, faixa 1–274), e disparou
   **alerta multi-dia** correto (3 datas: 1980 sem-data, 2025-08-05 real, 2026-06-09 da remontagem).
3. **Formulário** (JOE/Sony/VIDEO/2025-08-05, via curl no Flask) → **Matcher** casou (score 3, câmera
   Sony +3), perfil do JOE aprendido.
4. **Transferência**: contador deu JOE_001, destino `TESTE LOGAGEM/20250805/VIDEO/JOE/JOE_001`,
   `copiador.py` copiou 57 arquivos com MD5 OK, tamanho 0,00% de diferença, `.sppo` + PDF gerados.
   (Alerta benigno "57 vs 58": 1 arquivo de sistema/oculto que o copiador conta mas pula — política
   mídia-vs-sistema funcionando.)
5. **Extrator de frames** (rodado manual, pós-cópia): 34 mídias, 187 frames, `manifesto.json` gravado.
6. **Camada 4**: pré-check GMA (57 arq / tamanho OK) → `parashoot check` (`check_complete`) →
   `parashoot erase` (`erase_complete`) → **cartão embaralhado e ejetado de fato** ✅.

**Bug real pego pelo teste (e corrigido na hora):** o `parashoot --machine-readable` emite **JSON
Lines** (um objeto por linha, streaming). O parser da sessão 15 fazia `json.loads` do texto inteiro
→ quebrava no `erase` multi-linha (`erase_start`+`erase_complete`) → marcava `erase_falhou` mesmo
com o cartão embaralhado de verdade. Parser reescrito para ler NDJSON e decidir pelo último status
terminal (`check_complete`/`erase_complete` = ok; `error` = falha; intermediários ignorados;
sem sucesso reconhecido = falha segura). Validado contra os 5 formatos reais. Status do JOE_001
corrigido para `concluido` no banco. **Formatos JSON reais agora documentados** (ver §Camada 4).

**Restore validado (fecha o ciclo de vida do cartão):** após o erase, o idealizador restaurou o
cartão Joe pela GUI do Parashoot — voltou a montar em `/Volumes/Untitled` com os 17 clipes intactos
(`NORMAL DISK (has valid MBR)`). Provou na prática que o embaralhamento é 100% reversível.
- **Mecanismo:** restore = inverter os mesmos 2 MB de novo (simétrico). Exige root (escrever em
  `/dev/rdiskN`, que é `root:operator`). O GMA NÃO faz isso sozinho — delega ao Parashoot (que tem
  Full Disk Access). O socket de API do Parashoot só expõe `check`/`erase`, sem `restore`; o restore
  hoje é só pela GUI. Design do "botão de restore" do GMA registrado na memória `restore-cartao-parashoot`.

**Pendências reveladas pelo teste (próximos passos — em novas sessões):**
- **Camada 7 (Marca & Design) PRIMEIRO:** o idealizador achou a entrega do PDF abaixo do esperado
  (sem padrão, layout fraco). Definir identidade visual (logo, paleta, tipografia, grid) antes de
  reescrever o gerador de PDF.
- **PDF Overview:** reescrever o gerador no estilo Overview (briefing na §13.4) lendo o
  `manifesto.json` + `.sppo`, já aplicando o padrão visual da C7.
- **`extrator_frames.py` + PDF no fluxo automático** do `transferencia.py` — hoje rodados manualmente.
- **Reuso de registro no banco:** cartão Joe gravou no `db_id=1` (mesmo volume "Untitled" do teste
  GoPro). Resultado final correto, mas revisar consistência da Camada 3 quando dois cartões físicos
  montam com o mesmo nome de volume (usar UUID em vez do nome). Ver memória `banco-reuso-registro-volume`.
- Loop automático da `auditoria.py` (via `inicializar_gma.py`) ainda não exercitado — o teste rodou
  a C4 manualmente para controlar a ordem (frames antes do erase).

**✅ Sessão 15 (2026-06-09) — Camada 4 reescrita: integração automática com o CLI do Parashoot:**

Duas entregas: (A) primeiro teste de ciclo integrado da C4; (B) reescrita do `auditoria.py` depois
que a investigação do Parashoot revelou um CLI completo e automatizável.

**(A) Teste de ciclo integrado (versão antiga do auditoria.py):** registro `transferencia_ok` no
banco → detectado → auditado (106 arq / 8,25 GB do material da sessão 7) → `concluido` → eventos.
Reprovação também testada (contagem errada → bloqueou). Banco limpo depois.

**(B) Investigação do Parashoot + reescrita (mudança de design):**
- **Descoberto:** o Parashoot tem CLI documentado (`check`/`erase` com `--machine-readable` JSON),
  o `check` verifica arquivo por arquivo (mais forte que contagem+tamanho), e o **fake-format é
  REVERSÍVEL** (inverte 2 MB do MBR; footage intacto; recuperável). Detalhes na §Camada 4 abaixo.
- **`auditoria.py` reescrito:** fluxo `transferencia_ok` → pré-check GMA → `parashoot check` →
  `verificado_parashoot` → `parashoot erase` → `concluido`. TOTALMENTE AUTOMÁTICO, sem confirmação
  do operador no caminho feliz (o `check` é a confirmação do processo). Operador só é notificado em
  ocasiões vitais (check com faltando / erase falhou). Degrada sem crashar se o Parashoot não estiver
  instalado. Novos status: `verificado_parashoot`, `verificacao_falhou`, `erase_falhou`.
- **Bug corrigido na revisão:** o JSON de erro do Parashoot sai no **stderr** (não stdout) — o
  parser foi ajustado para tentar os dois. Testado contra o erro real do CLI (captura o `status:error`).
- Import + parse defensivo testados nesta máquina (Parashoot 2.3.5 instalado).

**Pendências remanescentes da C4:**
- **Teste com cartão REAL** (físico + material em destino) — valida formato exato do JSON de
  sucesso de `check`/`erase`, o nome do volume em `/Volumes/`, e o exit code de sucesso. PRÓXIMO PASSO.
- Loop de polling real (`loop_auditoria()` via `inicializar_gma.py`) ainda não exercitado ponta a ponta.
- Dependência do extrator de frames (esperar frames antes do erase quando a fonte for o cartão) —
  TODO já marcado no ponto certo do código.

**✅ Sessão 14 (2026-06-08) — agente da Camada 4 (`auditoria-gma`) criado:**

Criado o subagente especialista da Camada 4 em `.claude/agents/auditoria-gma.md`, no mesmo
padrão dos três existentes (checkin-gma, transferencia-gma, banco-dados-gma). Ele cobre a
auditoria estrutural independente (contagem + tamanho, tolerância 0,5%), a mudança de status
para `concluido` e o acionamento do Parashoot (`open -a ParaShoot` — o operador confirma o
embaralhamento/ejeção; o GMA nunca formata sozinho). Registra a regra de ouro: nunca liberar
cartão cuja contagem/tamanho não bate; nunca sugerir ejeção antes da auditoria. Lista de
subagentes no `CLAUDE.md` atualizada (transferencia-gma e banco-dados-gma deixaram de figurar
como "futuros").

**✅ Sessão 13 (2026-06-08) — Sessão A: fichas de check-in personalizáveis (C1 + C3):**

Expandido o formulário de check-in para capturar **5 campos editoriais novos** (opcionais, além
dos 4 obrigatórios do matching), pensados para ajudar tanto o sistema quanto os editores:
`modelo_camera`, `tipo_conteudo` (B-ROLL/ENTREVISTA/PALCO/COBERTURA/ABERTURA/ENCERRAMENTO/OUTRO),
`local_cena`, `prioridade` (NORMAL/URGENTE), `observacoes`.

- **C3 (`banco_dados.py`):** `gravar_formulario()` recebe os 5 campos; nova função
  `migrar_schema_formularios(conn)` (ALTER TABLE seguro, não-destrutivo) chamada por
  `inicializar_banco()`; DDL de `formularios` atualizado (bancos novos já nascem completos).
  Tabela `formularios` agora tem 14 colunas. `gma.db` existente migrado com sucesso.
- **C3 (`exportador_sheets.py`):** `CABECALHO` ampliado de 16 → **21 colunas** (inclui modelo,
  tipo de conteúdo, local/cena, prioridade e separa Obs. Operador de Obs. Formulário); SELECT e
  montagem de linhas atualizados.
- **C1 (`flask_gma.py`):** `_processar_e_salvar_formulario()` captura e repassa os 5 campos ao
  banco; painel HTML ganhou coluna "Conteúdo" (tipo + local) e "Prioridade" (URGENTE em vermelho).
- **Guia novo (`guia_tally_gma.md`):** passo a passo para montar o formulário no Tally (labels
  exatos, tipos de campo, opções dos dropdowns, webhook via ngrok, teste com curl, verificação
  no banco). Resolve a pendência "formulário Tally nunca criado".
- **Teste ponta a ponta OK:** curl → Flask → validação → JSON → banco, com os 5 campos chegando
  íntegros na tabela `formularios`.
- **Pendente (Sessão A):** o operador ainda precisa **criar de fato o formulário no Tally**
  seguindo o `guia_tally_gma.md` e testar o webhook real (ngrok → Tally → Flask).

**Decisão de design da ficha (conversa de 2026-06-08, após o idealizador trazer uma ficha real):**

A ficha de check-in foi repensada para ser **enxuta e personalizável por trabalho** (o pedido
original da Sessão A). Princípio do idealizador: **não complicar** — começar pelo contexto e pelas
informações iniciais, e deixar o processo automático crescer depois.

- **Ficha concreta fechada:** `NOME ★ · DATA ★ · TIPO DE MATERIAL ★ (VIDEO/FOTO/AUDIO) ·
  [lacunas de contexto, ex. PALCO · ARTISTA/SHOW] · INFORMAÇÕES ADICIONAIS`.
- **Câmera/modelo saem da ficha** — o sistema detecta do cartão (assinatura + exiftool + extensões).
  **Tipo de material fica** (o profissional sabe na hora; resolve o caso da entrevista: card de
  áudio marcado `AUDIO` = gravador).
- **Lacunas de contexto = configuráveis por trabalho.** O sistema é **agnóstico ao rótulo** —
  guarda `rótulo: valor` como veio do Tally. A mesma programação serve a festival, congresso,
  entrevista; troca-se só os rótulos ao iniciar um trabalho. Próximo trabalho-alvo = **festival
  de música** (por isso "sala/palestra" não serve — precisa ser configurável).
- **O NOME é a chave de aprendizado:** o sistema memoriza a assinatura de cada profissional
  (câmera/modelo, estrutura de pastas, padrão de nomes) e constrói um **perfil por nome** que
  fortalece o match ao longo do tempo (começa manual → vira automático).
- **Evolução futura (em segundo plano):** conceito de **gabarito** — o profissional seleciona
  caixas pré-montadas (line-up do festival conhecido de antemão) em vez de digitar. Exige Tally
  mais elaborado por evento; adiado para não travar o ponto concreto.

**✅ Passo 1 do Matcher seguro — CONCLUÍDO E TESTADO (2026-06-08, sessão 13):**

Decidiu-se MANTER a câmera na ficha (como seleção/dropdown), porque ela é um dos poucos sinais
que aparece nos DOIS lados (o cartão revela via exiftool; a ficha declara) — é peça-chave do
casamento. O `matcher.py` foi reescrito para ser **seguro contra ambiguidade**:
- **Pontuação:** câmera +3 · data +2 · **tipo de material +1** (NOVO — lê `contagem_tipo` do
  material gravado pelo Leitor) · nome na pasta de entrada +2.
- **Trava anti-ambiguidade (`MARGEM_SEGURANCA = 1`):** só casa automático quando o vencedor é
  estritamente melhor que qualquer concorrente por ≥1 ponto, **dos dois lados** (a ficha não
  pode estar dividida entre cartões, nem o cartão disputado entre fichas). Em empate/dúvida →
  `status: "aguardando_confirmacao"` + campo `candidatos_match` (lista as opções p/ o operador) +
  evento `match_ambiguo` no banco. **Nunca chuta** — prefere perguntar a arriscar trocar material.
- **Painel (`flask_gma.py`):** nova seção "Aguardando confirmação" lista os ambíguos (só leitura).
- **Testado:** (1) câmeras diferentes → casam certo; (2) empate total (3 fichas + 3 cartões Canon
  idênticos) → nenhum casa, todos aguardando_confirmacao com 3 candidatos cada; (3) desempate
  pelo tipo (vídeo vs foto) → casa o correto. Validado pelo agente E por teste independente.

**✅ Passo 3 — Perfil do profissional, FASE 1 (aprender) — CONCLUÍDA E TESTADA (2026-06-08, sessão 13):**

O sistema agora **aprende a assinatura de cada profissional** a cada match confirmado (sem ainda
mudar o comportamento do match — Fase 1 é só observar e guardar). A assinatura tem 4 ingredientes:
marca · modelo (exiftool) · prefixo do nome de arquivo · **faixa de numeração** (num_min/num_max).
A numeração é insight do idealizador: câmeras têm contador contínuo entre cartões, então a faixa
liga cartões da mesma pessoa e distingue duas pessoas com câmera idêntica.

- **`banco_dados.py`:** tabela `perfis` (11 colunas) + `atualizar_perfil(conn, nome, assinatura)`
  (upsert acumulativo: soma câmeras/modelos/prefixos, guarda `ultimo_num_max`, faz append das
  faixas, conta cartões) + `consultar_perfil(conn, nome)`.
- **`ler_cartao.py`:** `extrair_prefixo_e_numero()` e `extrair_assinatura()` (Python puro — separa
  prefixo e número sequencial dos nomes; monta câmera/prefixos/num_min/num_max).
- **`leitor_midia.py`:** `detectar_modelo_camera()` via exiftool (máx. 3 arquivos, não estressa o
  cartão) + grava `dados["assinatura"]` no JSON do material.
- **`matcher.py`:** ao confirmar match, chama `atualizar_perfil(nome_do_form, assinatura_do_material)`
  (aditivo, try/except). Só nos matches CONFIRMADOS, nunca nos ambíguos. TODO marcado para o Passo 2
  também alimentar o perfil ao resolver ambíguos.
- **Testado:** extração (GoPro 1-200, casos de borda de prefixo/número) + **ciclo integrado**:
  2 cartões do mesmo João (faixas 1-200 e 201-400) → perfil acumulou `total_cartoes=2`,
  `ultimo_num_max=400`, `faixas=[[1,200],[201,400]]`, câmeras/modelos/prefixos somados. Continuidade
  detectada. Registros de teste removidos do banco.

**⏭️ Próximas etapas da Camada 1 (em ordem):**
1. **Passo 3 — Fase 2 (usar):** o Matcher consulta o perfil para desempatar matches ambíguos
   (cartão cujo prefixo/modelo/faixa de numeração bate com o perfil de um nome → +pontos →
   desempata sozinho). Reduz a frequência com que o operador é chamado.
   > **REGRA DE OURO DA NUMERAÇÃO (insight do idealizador, 2026-06-08):** a numeração não é
   > contínua de forma estrita — fotógrafos testam fotometria e apagam os primeiros frames, mas o
   > contador da câmera não volta (ex.: card 2 termina em 2021, card 3 começa em 2030 = gap de 9).
   > Na Fase 2 **a numeração só ADICIONA confiança, nunca pune:** gap pequeno/moderado (dentro de
   > uma TOLERÂNCIA configurável) = continuidade plena; gap grande = só ignora o sinal e se apoia
   > em câmera/modelo/prefixo. Um gap **jamais** aciona o operador sozinho.
2. **Passo 2 — tela de confirmação no painel:** rota POST no Flask para o operador resolver, com um
   clique, os ambíguos que sobrarem (escolhe entre os `candidatos_match`, mostra os nomes dos
   arquivos como pista). É a rede de segurança final; deve também chamar `atualizar_perfil`.

**⚠️ CORREÇÃO da sessão 12 (2026-06-08) — C3 e C4 foram declaradas fechadas prematuramente:**

**Camada 3 — PARCIAL. Buracos pendentes:**
- `exportador_sheets.py` escrito, mas a planilha Google real nunca foi criada, credenciais
  nunca configuradas, e o fluxo banco → Sheets nunca testado de ponta a ponta.
- **Janela de monitoramento (Acesso 2 — Kanban):** não existe como código. É a tela que
  videomakers/fotógrafos acessam para ver em que etapa está cada cartão deles.
  A fonte de dados (SQLite) está pronta; a rota Flask + HTML não foi construída.
- **Formulário Tally (entrada de dados):** endpoint Flask `/forms/tally` existe e `ngrok_gma.sh`
  existe, mas o formulário no Tally nunca foi criado. Sem isso o ciclo inteiro não tem entrada.

**Camada 4 — PARCIAL. Buracos pendentes:**
- `auditoria.py` escrito. O que foi "testado": contar arquivos numa pasta existente com dados
  já no banco. Isso NÃO é teste de ciclo integrado.
- Teste real exige: check-in → transferência → `transferencia_ok` no banco → auditoria detecta
  automaticamente → audita → muda para `concluido` → Parashoot abre. Nunca foi executado.

**Plano de sessões para fechar os buracos (em ordem):**
1. **Sessão A** (`checkin-gma`): Formulário Tally + teste webhook → Flask → banco
2. **Sessão B** (`banco-dados-gma`): Google Sheets real — criar planilha, credenciais, teste
3. **Sessão C** (`banco-dados-gma`): Janela de monitoramento Kanban no Flask (rota `/monitor`)
4. **Sessão D**: Teste de ciclo integrado C4 (pode ser com dados simulados)

**Decisões da sessão 11 (2026-06-08) — scripts criados (mas não validados como entrega):**
- **`exportador_sheets.py` criado (Camada 3):** exportação offline-first para Google Sheets.
  Sincroniza a cada 60 s quando há internet. Reescreve a aba 'GMA' completa (sem append).
  Sem credenciais no .env → aguarda silenciosamente sem travar o sistema.
  Loop inicia como 6º processo no `inicializar_gma.py`.
- **`auditoria.py` criado (Camada 4):** polling a cada 10 s por cartões `transferencia_ok`.
  3 verificações: pasta existe · contagem de arquivos · tamanho total (± 0,5%).
  Ao aprovar: status → `concluido` + abre Parashoot + notificação macOS.
- **Filtro de arquivos GMA** (auditoria): exclui `.sppo`, `*_relatorio.pdf`, `*_manifesto.json`
  e a pasta `_GMA_frames/` da contagem — apenas material copiado do cartão entra.
- **Parashoot:** integrado via `open -a ParaShoot` (operador confirma; nunca chamamos `fake_format`).
- **`inicializar_gma.py`:** sobe 6 processos (adicionados Auditoria + Sheets).
- **`encerrar_gma.py`:** lista de kill inclui `auditoria.py` e `exportador_sheets.py`.
- **`gspread` + `google-auth` instalados** via pip.

**Decisões da sessão 10 (2026-06-07) — mapa vivo (reorientação do idealizador):**
- O idealizador sinalizou sensação de estar perdido com o volume de decisões (9 sessões em 2 dias).
  Sessão dedicada a **parar e olhar o todo** — sem código novo.
- **`organograma_GMA.md` reescrito como "Mapa Vivo"**: agora abre com o quadro de orientação
  rápida (prédio de 7 andares com barra de progresso · fluxo do cartão em linguagem de set ·
  linha do tempo das decisões · regras de ouro) e só depois traz a parte técnica (3 zonas,
  3 acessos, organograma de processos e de desenvolvimento). Estava parado em 06/06 e
  desatualizado (citava "Ejetado" e o ShotPutPro no fluxo).
- **Board visual criado no Miro** — "GMA — Mapa Vivo do Projeto":
  https://miro.com/app/board/uXjVHI0rvt4=/ — com 3 diagramas: (1) fluxo do cartão colorido por
  status e agrupado por andar; (2) prédio de 7 andares; (3) linha do tempo das 10 sessões
  (verde = teste real, laranja = decisão grande, amarelo = trabalho normal). Cumpre o
  "Organograma no Miro" que estava em §13.1.
- **Combinado de método de trabalho** (a manter pelo orquestrador): antes de cada sessão, ler o
  documento mestre, apontar riscos e propor o objetivo do dia; durante, confirmar entendimento
  antes de codar; depois, atualizar os mapas (documento mestre + organograma + Miro).



| Camada | Nome | Status |
|---|---|---|
| 1 | Check-in e identificação | ⚠️ Parcial — ficha PRÓPRIA no GMA ✅ (gabarito + edição + online c/ senha + link de câmera só-ficha + QR, sessão 21); Tally vira reserva; falta domínio fixo do túnel e o mural dos câmeras |
| 2 | Transferência | ✅ Concluída e testada com cartão real |
| 3 | Controle e segurança das informações | ⚠️ Parcial — SQLite + telas Kanban/Planilha locais prontas (sessão 19); Google Sheets real pendente |
| 4 | Auditoria estrutural e liberação do cartão | ✅ Concluída — código pronto + ciclo integrado testado (aprovação + reprovação) |
| 5 | Plataforma (produto profissional) + interface + multi-máquina | 🔧 EM PLANEJAMENTO (sessão 20) — agente `plataforma-gma` + blueprint criados; construção só após a fase de teste |
| 6 | IA assíncrona | 📋 Futura |
| 7 | Marca e design | 📋 Planejada (prazo: 2026-06-20) |

**Decisões da sessão 9 (2026-06-07) — executador de frames + divisão de responsabilidade visual:**
- **Decisão de arquitetura (frames mecânicos vs. IA):** extrair frame e ler metadados é **mecânico, offline e grátis** (ffmpeg/ffprobe/exiftool) → fica no **ciclo operacional**, NUNCA na Camada 6. *Entender* o frame (escolher o mais representativo, descrever, etiquetar, busca semântica) é **IA → Camada 6** (paga, assíncrona, opcional, vem depois). Motivo: o PDF de entrega precisa sair completo, com thumbnails, offline na base — não pode depender de API paga/internet.
- **O Leitor (Camada 1) fica enxuto** (só estrutura: codec, resolução, duração, datas, câmera, para match e painel). A extração de frames vira um **passo mecânico pós-cópia** que lê o **destino já verificado** (princípio nº 2 — nunca estressa o cartão).
- **`extrator_frames.py` criado** — o "executador dos frames": lê o `.sppo` + a pasta de destino, extrai metadados + um **padrão fixo de 10 frames por vídeo** (**divisão uniforme no tempo** entre 5% e 95%, igual ao ShotPutPro — folha de contato visualmente consistente; decisão de 2026-06-07: tempo extra é aceitável, padrão importa mais), e grava um **`manifesto.json`** (índice de mídia: metadados + caminhos das miniaturas). Salva thumbnails em `_GMA_frames/` ao lado do relatório. É **idempotente** (reaproveita miniaturas), **não-destrutivo** (só lê a mídia; escreve apenas thumbnails + manifesto).
- **Truque de velocidade confirmado:** usa o `.LRV` (proxy GoPro) como fonte dos frames de vídeo e o JPG irmão para o RAW `.GPR`. Resultado no teste real: **62 mídias / 179 frames em ~17 s**, câmera detectada ("GoPro HERO7 Black" via exiftool, inclusive nos MP4 que o ffprobe não pega).
- **Layout do relatório (em definição):** o idealizador prefere o estilo **Overview** (dashboard + folha de contato com vários frames por arquivo) para o contexto atual (cartão com conteúdo variado, ajudar editores). O **Filmstrip** (10 frames/arquivo) fica para publicidade/docs/cinema. O `manifesto.json` é **agnóstico ao layout** — serve aos dois.
- **Fonte dos frames — avaliação automática (plano APROVADO, a implementar na integração ao fluxo):** depois da cópia **verificada**, o extrator pode ler os frames do **próprio cartão** (em vez do destino) quando o destino for um **servidor de rede compartilhado** — assim alivia a banda da rede para os outros acessos. É seguro porque o material já tem backup íntegro (MD5 conferido) e a leitura é não-destrutiva. **Regras inegociáveis:** (1) só com `transferencia_ok`; (2) cartão ainda montado; (3) só-leitura no cartão (miniaturas vão para o destino/local); (4) **terminar antes da ejeção** (Camada 4). **Lógica:** destino é rede + cartão montado → lê do cartão; senão (destino local ou cartão ejetado) → lê do destino. **Critério é aliviar a rede, não velocidade.** Implementar quando o extrator for ligado ao fluxo (`transferencia.py`).
- **Próximo passo:** reescrever o gerador de PDF para o estilo **Overview** (escolhido pelo idealizador para o contexto de entrega de conteúdo variado), lendo do `manifesto.json` (mídia) + `.sppo` (integridade) — sem extrair nada (extração já foi feita uma vez pelo executador).

**Decisões da sessão 8 (2026-06-07) — PDF rico com thumbnails:**
- `gma_relatorio_pdf.py` reescrito (versão 2): 3 partes — cabeçalho com 3 colunas, folha de contato com thumbnails, tabela completa de todos os arquivos com checksums.
- Folha de contato: um bloco por arquivo de mídia (vídeo ou foto), coluna de metadados (ffprobe/exiftool) + filmstrip de thumbnails extraídos ao longo do clipe.
- GoPro: usa `.THM` (thumbnail nativo) para fotos/RAW e `.LRV` (proxy de baixa resolução) para extração rápida de frames de vídeo — nunca re-extrai do `.MP4`.
- `transferencia.py` atualizado: passa `dados_form` como `dados_match` ao gerar o PDF, ativando a coluna do profissional no cabeçalho.
- Bug corrigido no parser XML: `root.find("job") or ...` era inválido para ElementTree (elementos sem filhos são falsy em Python). Substituído por comparação `is not None`.
- PDF de 22 páginas gerado com sucesso a partir do `.sppo` de teste (106 arquivos, 62 de mídia, 7.7 GB, GoPro HERO7 Black).
- Critérios de conclusão atendidos: thumbnail por vídeo (3 frames), thumbnail por foto (JPEG nativo), câmera detectada via exiftool ("GoPro HERO7 Black"), tabela de auditoria completa.

**Decisões da sessão 6 (2026-06-07):**
- Divisão de responsabilidade confirmada: Camada 3 cuida do schema do Forms (campo `produtora → nome`); Camada 1 cuida da interface de entrada (Tally)
- Endpoint `POST /forms/tally` adicionado ao `flask_gma.py` — aceita webhook nativo do Tally (envelope `data.fields`), com verificação HMAC-SHA256 opcional via `TALLY_WEBHOOK_SECRET`
- `ngrok_gma.sh` criado: expõe Flask na porta 5050 para o Tally alcançar via internet, imprime a URL do webhook pronta para copiar
- `.env.exemplo` criado: modelo para configurar `TALLY_WEBHOOK_SECRET` sem hardcode no código
- `.gitignore` criado: protege `.env`, `gma.db`, `.gma_ativo`, logs e contadores
- `inicializar_gma.py` atualizado: carrega `.env` automaticamente ao subir (sem dependências externas)
- `instrucoes_apps_script.md` corrigido: "Produtora / Equipe" → "Nome" — cadeia Forms → Apps Script → Flask → banco usa `nome` de ponta a ponta

**Decisões da sessão 5 (2026-06-07):**
- Integração SQLite em todos os processos: Flask, Leitor, Matcher e Transferência agora escrevem no banco em paralelo com os JSONs
- Banco passa a ser populado automaticamente no ciclo completo (sem mudança no fluxo JSON existente)
- Adicionadas 5 funções auxiliares em `banco_dados.py`: `gravar_formulario`, `gravar_cartao`, `atualizar_cartao`, `gravar_match`, `gravar_arquivos_do_log`
- IDs do banco são salvos de volta nos JSONs (`db_formulario_id`, `db_cartao_id`) como ponte entre processos
- Índice único criado em `arquivos(cartao_id, caminho_origem)` para idempotência

**Decisões da sessão 4 (2026-06-07):**
- Numeração dos cartões → Camada 2 (feita via `contadores/<NOME>.json`)
- Camada 3 → exclusiva de controle/segurança das informações (SQLite + Sheets)
- Camada 4 → redefinida como **auditoria estrutural** (contagem + tamanho) + acionamento do Parashoot
- Status final do processo → **`concluido`** (não mais `ejetado`)
- Multi-máquina → Camada 5
- Campo `produtora` → **`nome`** (profissional de captação) em todo o sistema
- Schema SQLite criado: 5 tabelas (`cartoes`, `formularios`, `matches`, `arquivos`, `eventos`)

---

## 1. Visão geral

O GMA é um sistema profissional de logagem (gerenciamento) de mídia audiovisual
para festivais e eventos ao vivo. Automatiza o ciclo completo de tratamento dos
cartões de memória entregues pelas equipes de captação: identificação, transferência
segura com verificação de integridade, registro em banco de dados, e ejeção/embaralhamento
do cartão para reutilização.

O sistema é construído em Python, com foco em operação **offline-first**, **custo mínimo**,
**autonomia máxima** e **segurança absoluta dos arquivos** — que são insubstituíveis.

### Casos de uso
- **Eventos grandes**: festivais com múltiplas câmeras e equipes, alto volume de cartões,
  possivelmente com 2–3 máquinas de logagem operando em paralelo.
- **Projetos menores / modo solo** (no radar): operador único que assume transferência,
  checagem e recorte de frames para entrega remota, com custo de operação reduzido.

---

## 2. Princípios-guia (inegociáveis)

1. **Offline-first** — todo o ciclo crítico funciona 100% sem internet. Tarefas que
   dependem de nuvem (sincronização, entrega) ficam em fila e executam quando a conexão volta.
2. **Segurança dos arquivos acima de tudo** — material nunca pode ser perdido. Cada decisão
   do fluxo deve proteger os arquivos. Os arquivos de mídia **nunca** vão para a nuvem.
3. **Custo mínimo de operação** — priorizar ferramentas gratuitas e processamento mecânico
   (metadados, checksums). IA fica confinada a uma camada opcional e assíncrona.
4. **Autonomia máxima** — o sistema decide e executa sozinho na maioria dos casos. O operador
   é acionado apenas como último recurso, quando há ambiguidade real.
5. **Velocidade / sem filas** — ações ágeis no ciclo de check-in para não gerar gargalos no set.
6. **Intuitivo para terceirização** — o sistema será operado primeiro pelo idealizador para
   afinar o processo, e depois por terceiros. A interface precisa ser simples.

---

## 3. Decisão de arquitetura: modelo HÍBRIDO (Opção B)

A arquitetura escolhida combina banco local para operação e nuvem para entrega:

- **Filas JSON locais** — arquivos `.json` em `fila_material/` e `fila_forms/` para comunicação
  entre os processos da Camada 1. Simples, offline, sem dependências. Migração para SQLite na Camada 3.
- **SQLite local** — banco de dados operacional na máquina GMA. Rápido, offline, sem limite, gratuito.
  Será implementado na Camada 3.
- **Google Sheets (nuvem)** — espelho de entrega. Editores acessam online em tempo real (quando há
  internet) ou via XLS baixado (offline).
- **Notion** — opcional, para visualizações ricas e organização do projeto. **Não é o núcleo operacional.**
- **Flask local** — mini-servidor na máquina principal que (a) recebe os dados do Google Forms e
  (b) serve o painel para a segunda máquina na rede local.

### Por que filas JSON (e não SQLite direto na Camada 1)
- Zero dependências externas no ciclo crítico.
- Cada processo lê/escreve arquivos independentemente — sem locks de banco de dados.
- Auditoria simples: cada arquivo JSON é um registro legível e rastreável.
- Migração para SQLite na Camada 3 é incremental e não quebra nada.

---

## 4. Stack de ferramentas e status

| Ferramenta | Papel | Status | Custo |
|---|---|---|---|
| Python 3.x | Núcleo do sistema, automação | Em uso | Gratuito |
| Flask | Servidor local (formulário + painel 2ª máquina) | **PRONTO** | Gratuito |
| Google Forms | Formulário de check-in (entrada de dados) | **Configurado** | Gratuito, ilimitado |
| Google Apps Script | Conector Forms → Flask (webhook) | **PRONTO** | Gratuito |
| SQLite (`banco_dados.py`) | Banco de dados operacional local | **EM BUILD** — schema criado, migração pendente | Gratuito |
| Google Sheets / XLS | Espelho de entrega ao cliente | A integrar (Camada 3) | Gratuito |
| copiador.py (Python) | **Motor de cópia OFICIAL**: cópia + checksum MD5 + log `.sppo` (XML) | **Em uso** (validado em cartão real) | Gratuito |
| ShotPutPro | ~~Motor de cópia~~ **REMOVIDO do ciclo** (GUI não automatizável). Referência de qualidade para o relatório PDF | Fora de cena | ~US$150/ano |
| Parashoot | Ejeção e embaralhamento do cartão | Em uso | Pago |
| Notion | Visualização rica (opcional) | Opcional | Gratuito c/ limites |
| Gemini API | Análise visual de conteúdo (Camada 6) | Futuro | Por uso |
| Claude API | Busca conversacional do acervo (Camada 6) | Futuro | Por uso |

---

## 5. Ecossistema e fluxo de dados

Três zonas:

### Zona 1 — Campo / Set
- **Câmeras** geram o material.
- **Google Forms** (no celular do operador) coleta os metadados humanos: **nome** do profissional
  de captação, câmera, tipo de material, data de gravação.
- **Cartão de memória** é entregue na base.

### Zona 2 — Máquina GMA (offline-first)
- **Python (núcleo)** — lê o cartão, faz match, atribui número sequencial, cria pasta, copia
  com verificação MD5, grava no banco, aciona Parashoot após auditoria, grava log.
- **`copiador.py`** — motor de cópia oficial (Python puro): MD5 por arquivo, fallback
  `copy2→copyfile`, log `.sppo`. ShotPutPro foi descartado (não automatizável).
- **Parashoot** — embaralha e ejeta o cartão após auditoria estrutural confirmada (Camada 4).
  O GMA aciona; o Parashoot executa — o embaralhamento nunca é feito pelo GMA diretamente.
- **SQLite local (`gma.db`)** — fonte única de verdade operacional, sempre offline.

### Zona 3 — Nuvem / Entrega
- **Google Sheets** — espelho de entrega, acessível por link, sem necessidade de conta.
- **Notion** (opcional) — visualização rica.
- **Portal online** (futuro) — plataforma de acesso à informação do evento.

### Fluxo completo (Camadas 1–4)
```
Câmera → Cartão conectado → [C1] Porteiro detecta
                                        ↓
                             [C1] Leitor analisa conteúdo
                             (extensões, datas, alerta multi-dia)
                                        ↓
Google Forms (celular) → Flask recebe → fila_forms/
                                        ↓
                             [C1] Matcher cruza material + formulário
                             (score ≥ 3 = match confirmado)
                                        ↓
                             [C2] Atribui número (NOME_NNN via contador)
                             Cria pasta de destino
                             Anuncia "copiando" no banco
                                        ↓
                             [C2] copiador.py copia + MD5 por arquivo
                             Gera log .sppo + relatório PDF
                             Grava resultado no banco
                                        ↓
                             [C3] SQLite registra / Google Sheets sincroniza
                                        ↓
                             [C4] Auditoria estrutural independente
                             (conta pastas/arquivos, compara tamanho total)
                             Status → "concluido"
                             Aciona Parashoot → embaralha + ejeta cartão
                                        ↓
                             Editores acessam via Google Sheets
```

---

## 5.1. Os 3 pontos de acesso (decisão de 2026-06-06)

A informação do GMA é consumida por três públicos diferentes. A decisão de arquitetura é
servir os três a partir de **uma única fonte de verdade** (filas JSON hoje → SQLite na Camada 3),
com **três vistas (telas)** distintas. Não são bancos separados — são jeitos diferentes de ler o
mesmo dado, o que impede divergência.

| # | Tela | Público | Onde vive | Status |
|---|---|---|---|---|
| 1 | **Painel do Operador** (Centro de Comando) | Operador (base + 2ª/3ª máquina) | Flask local `:5050` — **offline-first** | No ar com barra de abas (sessão 19); ainda lê filas JSON |
| 2 | **Quadro de Acompanhamento** (Kanban dos cartões + post-its) | Operador + set/equipes (read-only) | Flask local — **offline-first** + espelho opcional no **Notion** | ✅ Rascunho no ar (sessão 19): `/kanban` lê do banco; post-it grava no banco; visual/colunas a refinar |
| 3 | **Planilha de Análise / Entrega** | Editores + cliente | **Google Sheets** (nuvem) | ⚠️ Espelho local no ar (sessão 19): `/planilha` lê do banco; Google Sheets real (credenciais) pendente |

**Regras:**
- Acessos 1 e 2 são **operação** → offline-first, vivem no Flask. Acesso 3 é **entrega** → nuvem.
- O **Notion é sempre só vitrine** espelhada, nunca o operacional crítico.
- Acesso 2: cada cartão é um "card" que percorre as colunas **Detectado → Match → Copiando →
  Verificado ✅ → Concluído**. Os "post-its" são um campo de **observações livres por cartão**
  ("veio com 2 dias", "produtora pediu prioridade", "card riscado").
- Consequência de projeto: esta decisão motiva **desenhar o esquema do SQLite desde já**, pois as
  três telas precisam concordar sobre quais campos cada cartão tem.

Diagrama completo no `organograma_GMA.md`.

---

## 6. As 7 camadas do roadmap

### Camada 1 — Check-in e identificação `[CONCLUÍDA ✅]`
Todos os componentes entregues e testados em 2026-06-05.

- `ler_cartao.py` — leitura e classificação de material **[FEITO]**
- `gma_correcao.py` — sistema de correção de registros **[FEITO]**
- `porteiro.py` — filesystem watcher, detecta cartões/volumes novos **[FEITO]**
- `leitor_midia.py` — analisa conteúdo, detecta multi-dia, chama Matcher **[FEITO]**
- `matcher.py` — cruza material + formulário por pontuação **[FEITO]**
- `flask_gma.py` — recebe Google Forms, serve painel, controla Porteiro **[FEITO]**
- `google_apps_script.js` — conector Forms → Flask **[FEITO]**
- `inicializar_gma.py` — sobe todos os processos com um comando **[FEITO]**
- `encerrar_gma.py` — encerramento de emergência **[FEITO]**

**Para usar:**
```bash
python3 /Users/serafa/GMA/inicializar_gma.py   # liga tudo
# Ctrl+C para encerrar
```
**Painel:** `http://127.0.0.1:5050`

### Camada 2 — Transferência `[CONCLUÍDA ✅]`
Todos os componentes entregues e validados com cartão real (sessões 1–4 + 7 + 8).
Pendência externa: renomear campo `produtora` → `nome` no Google Forms.

- `gma_relatorio_pdf.py` v2 — PDF rico: cabeçalho 3 colunas + folha de contato (thumbnails + metadados) + tabela completa de auditoria **[FEITO — sessão 8]**
- `transferencia.py` — processo de polling + motor de cópia + validação + PDF **[FEITO]**
- `copiador.py` — motor de cópia MD5 + fallback `copy2→copyfile` + log `.sppo` **[FEITO]**
- **Contador de cartões por profissional** (`contadores/<NOME>.json`) **[FEITO — sessão 4]**

**Numeração dos cartões (decisão de 2026-06-07 — pertence à Camada 2):**

A nomenclatura dos cartões é uma etapa do ciclo de transferência (junto com copiar, checksum,
`.sppo` e PDF), por isso vive na Camada 2 — não na Camada 3.

- **Modelo mental:** o GMA roda para **uma produtora por instância/trabalho**. A produtora não
  distingue nada — é o contexto do trabalho inteiro. O que varia são os **profissionais de
  captação** (fotógrafo/videomaker/técnico de som), cadastrados pelo **`nome`** no formulário.
- **Conceito de "cartão":** termo genérico do processo — "o cartão do fulano chegou pela 3ª vez,
  agora é o cartão 3". É como se fala do que está acontecendo.
- **Estrutura da pasta:** `EVENTO / DATA / TIPO / NOME / NOME_NNN`
  Ex.: `RIO2C / 20260615 / VIDEO / JOAO / JOAO_001`, `JOAO_002`; `PAULO / PAULO_005`.
  A pasta-pai leva o nome do profissional; a subpasta repete o nome + número sequencial dele.
- **Contador (fonte da verdade):** um arquivo `contadores/<NOME>.json` (ex.: `{"proximo": 4}`)
  por profissional. Lido e incrementado de forma atômica a cada cartão. **Substitui** a contagem
  de pastas no destino (frágil: quebrava se alguém renomeasse/movesse/apagasse uma pasta). Cada
  profissional tem sua própria sequência — o `JOAO_001` e o `PAULO_001` são independentes.
- **Campo do formulário:** `nome` (antes era `produtora`). **Pendência:** renomear também o campo
  no Google Forms / próxima ficha online (Tally).

**Decisão de arquitetura FINAL (2026-06-06, após teste com cartão real):** o **`copiador.py`
(Python puro) é o motor de cópia oficial** do GMA. O teste com cartão real confirmou na prática
que o **ShotPutPro não se deixa automatizar** (sem CLI, sem AppleScript de cópia, GUI hostil ao
GUI scripting) — ele seria sempre um gargalo para o objetivo de "sistema todo automático". O
`copiador.py` copiou 7,7 GB reais com verificação MD5 por arquivo, 100% automático, grátis e
offline-first — alinhado com todos os princípios inegociáveis.

> **O que mantemos do ShotPutPro:** ele continua sendo a **referência de qualidade** para o que
> queremos replicar em casa — sobretudo a **segurança/registro** e um **relatório PDF rico (com
> frames/thumbnails, metadados, etc.)**. Meta da próxima fase: aproximar o PDF do GMA do padrão
> ShotPutPro. (Documento de referência do relatório a ser enviado pelo idealizador.)

_Histórico: antes desta data o ShotPutPro chegou a ser cogitado como motor (integração
semi-automática). O teste real descartou essa via._

#### Investigação técnica do ShotPutPro (versão 2026.2.4) — feita em 2026-06-06

Exploração completa da aplicação (interface + arquivos internos) para mapear o que serve à automação.

**O que o ShotPutPro OFERECE (recursos úteis):**

| Recurso | Onde fica | Uso no GMA |
|---|---|---|
| Salvar relatório `.sppo` na pasta de destino | Configurações → Relatórios → "Salvar relatórios com o trabalho" (**já ativo**) | GMA detecta o `.sppo` aparecendo = cópia terminou |
| Algoritmos de checksum | Configurações → preset → Verificação (xxHash64 padrão; MD5, SHA-1/256/512, C4, CRC-32 disponíveis) | Verificação de integridade profissional |
| Automação da Fila | Configurações → Geral → Automação da Fila | "Adicionar unidade automaticamente à fila" + "Iniciar tarefa ao entrar na fila" |
| Modo "Predefinição" (presets) | Dropdown topo da janela: Predefinição / Simples / Relatório | Destino fixo + esquema de nomenclatura por preset |
| Esquema de nomenclatura dinâmico | Preset → aba Organização → "Adicionar estrutura de pasta de saída" | Tokens arrastáveis: Nome da Unidade, Numeração Automática, Data (hoje), Data de Criação, Data de Modificação |
| Relatório PDF próprio | Configurações → Relatórios → Relatórios PDF | Alternativa/complemento ao PDF do GMA |
| Ejeção automática após conclusão | Automação da Fila → "Ejetar origem automaticamente" | Útil na Camada 4 (ejeção) |
| Responde a AppleScript básico | `osascript -e 'tell application "ShotPutPro" to get name'` | Base para acionamento via GUI scripting |

**O que o ShotPutPro NÃO TEM (limitações confirmadas):**
- **Sem CLI real** — não existe comando tipo `shotputpro --source=X --dest=Y`. (Há binários internos
  `sppmedia` e `sppspeed` no bundle, mas exigem argumentos não documentados e deram erro nos testes.)
- **Sem dicionário AppleScript** — responde só ao básico (`get name`); não expõe comandos de cópia.
- **Sem URL scheme** — não há `shotputpro://...` registrado no `Info.plist`.
- **Presets em formato binário** — guardados nas preferences (`com.imagineproducts.ShotPutPro`)
  como `NSKeyedArchiver` contendo Protocol Buffers. Difícil criar do zero por fora; mais seguro
  criar o preset uma vez pela interface e o GMA só ajustar o destino.

**Onde o ShotPutPro guarda as coisas (caminhos descobertos):**
```
~/Library/Preferences/com.imagineproducts.ShotPutPro.plist   ← presets, favoritos, todas as configs
~/Library/Application Support/ImagineProducts/102/UserResources/jobs/<UUID>/   ← histórico de jobs
        ├── jobInfo/job.job         (binário: metadados do job, volume, datas)
        └── tree/*.repD             (JSON+binário: árvore de arquivos copiados, checksums)
```
- Chave do preset nas preferences: `spppreset-<id>` + lista `replicationPresetOrderedIds`.
- Favoritos de destino: `AttachedDrivesVC_favoriteLocationsSaveKey` (array de URLs `file://`).
- Verificação ativa por padrão: `kReplicationVerificationOption = 1`, PDF ligado, MHL/ASC-MHL ligado.

#### Estratégia de integração escolhida (semi-automática) — 3 partes

1. **Configuração única (operador, uma vez por máquina):**
   - Ativar Automação da Fila (adicionar à fila + iniciar ao entrar).
   - Criar **um preset permanente "GMA"** com a pasta-raiz do storage como destino e o esquema de
     nomenclatura desejado.

2. **`integrador_spp.py` (a construir):** antes de cada cópia, o GMA injeta o destino correto na
   config do ShotPutPro (via `defaults write` no array de favoritos / no destino do preset) e
   aciona o ShotPutPro. ShotPutPro copia + verifica + gera `.sppo`.

3. **Monitoramento (já estruturado no `transferencia.py`):** observa a pasta de destino esperando o
   `.sppo` surgir → chama `gma_relatorio_pdf.py` para gerar o relatório GMA.

**Formato XML `.sppo` (compatível com `parse_shotputpro_log`) — referência:**
```xml
<?xml version="1.0" encoding="UTF-8"?>
<report>
  <job name="PRODUTORA_001" date="2026-06-06" time="14:32:01" operator="GMA-Automatico"/>
  <source volume="Untitled" path="/Volumes/Untitled"/>
  <destination path="/caminho/destino"/>
  <files>
    <file src="/origem/arq.mp4" name="arq.mp4" size="1234" srcMD5="abc..." dstMD5="abc..." verified="yes"/>
  </files>
  <summary totalFiles="107" verified="107" failed="0" totalSize="8254943140" duration="00:08:42" speed="245 MB/s"/>
</report>
```

**Motor de cópia oficial — `copiador.py` (Python puro):**
função `copiar(origem, destino, nome_job)` bloqueante; `os.walk()` ignorando ocultos; MD5 por
arquivo em blocos de 1 MB origem+destino; `shutil.copy2` com fallback automático para
`shutil.copyfile` em arquivos de sistema da câmera (ex: `.url`, `.log`, `.bk` da GoPro);
nunca sobrescreve; gera `.sppo` ao final; retorna `ok`/`caminho_log`/contagens/tamanho;
log em `logs/copiador.log`.

### Camada 3 — Controle e segurança das informações `[CONCLUÍDA ✅]`
**Escopo (redefinido em 2026-06-07):** a Camada 3 é a guardiã das informações — não faz contagem
de cartões (isso é da Camada 2) nem coordenação multi-máquina (isso é da Camada 5). Ela:
- SQLite como banco operacional local (substitui as filas JSON) — **fonte única de verdade**
- Exportação automática (assíncrona, offline-first) para Google Sheets — só metadados, nunca mídia
- Controle de consistência **entre os processos** das Camadas 1 e 2 (sem duplicatas, sem registros
  perdidos) e auditoria append-only (tabela `eventos`)
- A tabela-chave `arquivos` (JOIN mídia da Camada 1 + integridade da Camada 2) que alimenta as
  3 telas e os 3 relatórios

> **Movido para fora da Camada 3:** a **numeração dos cartões** foi para a **Camada 2** (já feita,
> via `contadores/<NOME>.json`); o **suporte multi-máquina e a consistência entre instâncias**
> foram para a **Camada 5** (é interface/distribuição na rede local).

**O que já foi entregue da Camada 3:**
- ✅ `banco_dados.py` — inicializa `gma.db`, cria as 5 tabelas, fornece `obter_conexao()`,
  `registrar_evento()` e as 5 funções auxiliares de integração. (sessão 4 + sessão 5)
- ✅ `gma.db` criado em `/Users/serafa/GMA/gma.db` com 5 tabelas prontas + índice único em `arquivos`
- ✅ Agente `banco-dados-gma` criado em `.claude/agents/` (sessão 4)
- ✅ Integração SQLite em `flask_gma.py` — formulário recebido → `formularios` table (sessão 5)
- ✅ Integração SQLite em `leitor_midia.py` — cartão analisado → `cartoes` table (sessão 5)
- ✅ Integração SQLite em `matcher.py` — match confirmado → `matches` table (sessão 5)
- ✅ Integração SQLite em `transferencia.py` — status `copiando` → `transferencia_ok`/`falhou` + `arquivos` table (sessão 5)

**O que foi entregue na Camada 3 (completo):**
1. ~~Ligar os processos ao banco~~ ✅ **FEITO (sessão 5)**
2. ~~Migração incremental das filas JSON → SQLite~~ ✅ **FEITO (integração paralela — JSONs ainda existem como backup)**
3. ~~Exportação para Google Sheets (assíncrona, offline-first)~~ ✅ **FEITO (sessão 11) — `exportador_sheets.py`**

**Para ativar a exportação (Camada 3):** preencher `GOOGLE_CREDENTIALS_JSON` e `GMA_SHEETS_ID` no `.env` (ver `.env.exemplo` para o guia de 9 passos).

### Camada 4 — Auditoria estrutural e liberação do cartão `[CONCLUÍDA ✅]`

**Entregue na sessão 11.** A Camada 4 é uma **auditoria independente** da Camada 2:

- **Camada 2** verifica *arquivo por arquivo* durante a cópia (MD5 criptográfico — cada byte).
- **Camada 4** verifica *a estrutura completa* depois da cópia:
  - Conta arquivos no destino (excluindo arquivos adicionados pelo GMA)
  - Compara tamanho total com o registrado pela Camada 2
  - Tolerância de 0,5% no tamanho (variação de filesystem)
  - Se tudo bate → **status do cartão: `concluido`**

**Sobre o Parashoot (REINVESTIGADO na sessão 15, 2026-06-09 — descobertas que mudam o design):**
- **O Parashoot TEM CLI completo e automatizável** em
  `/Applications/ParaShoot.app/Contents/MacOS/cli/parashoot` (a decisão antiga de "só abrir a GUI
  e o operador confirma" está OBSOLETA):
  - `parashoot check --card <mount> --destinations <dest> --machine-readable` → verifica
    **arquivo por arquivo** (gera assinaturas e compara cartão vs. destino — mais forte que
    contagem+tamanho).
  - `parashoot erase --card <mount> --destinations <dest> --machine-readable` → embaralha + ejeta.
    Só apaga se o material estiver em ≥ `min-destinations`.
  - Também: `parashoot is-card <mount>`, `parashoot settings`.
  - **Formato de saída (validado com cartão real, sessão 16):** é **JSON Lines (NDJSON)** — um
    objeto JSON por linha, em streaming. NÃO é um único JSON.
    - `check` sucesso (stdout): `{"status":"check_complete","message":"Card is successfully backed up to all destinations"}`
    - `erase` (stdout, 2+ linhas): `{"status":"erase_start",...}` → `{"status":"erase_complete","message":"Card has been successfully erased"}`
    - erro (stderr): `{"status":"error","error":"unknown_error","message":"..."}`
    - O JSON de sucesso NÃO traz contagem (missing/found/total) — só status + message.
    - O parser do GMA lê todas as linhas (stdout+stderr) e decide pelo último status TERMINAL
      (`check_complete`/`erase_complete` = ok; `error` = falha; intermediários ignorados; sem
      sucesso reconhecido = falha segura).
- **O fake-format é REVERSÍVEL:** `fake_format v2.0.2` só inverte os primeiros 2 MB (cabeçalho/MBR);
  o footage nunca é tocado; inverter de novo restaura (`fake_format --check`: exit 0 = "restorable").
  Liberar o cartão NÃO destrói material — é recuperável pelo próprio Parashoot.
- Também há uma API JSON-RPC interna (socket `~/Library/Application Support/ParaShoot/api.sock`,
  `ping` → capabilities `check`/`erase.non_interactive`), mas o CLI é mais simples e foi o escolhido.
- O GMA NUNCA chama `fake_format` diretamente — sempre via `parashoot erase`.

**Fluxo da Camada 4 (reescrito em `auditoria.py`, sessão 15 — TOTALMENTE AUTOMÁTICO):**
1. Polling a cada 10 s por cartões com `status = 'transferencia_ok'`
2. Pré-check GMA (barato): pasta existe; contagem bate; tamanho bate (± 0,5%)
3. Descobre o mountpoint (`/Volumes/<volume>`). Cartão não montado → evento `cartao_nao_montado`, pula
4. `parashoot check` (arquivo a arquivo). `missingFiles == 0` → `status = 'verificado_parashoot'`.
   Faltando ou erro → `status = 'verificacao_falhou'` + notifica operador (ocasião vital), NÃO embaralha
5. `parashoot erase` → embaralha + ejeta. Sucesso → `status = 'concluido'`.
   Falha → `status = 'erase_falhou'` + notifica operador
6. SEM confirmação do operador no caminho feliz — o `check` do Parashoot É a confirmação do processo
   (diretriz: operador é último recurso). Novos status: `verificado_parashoot`, `verificacao_falhou`,
   `erase_falhou`.

> **Validado no teste com cartão real (sessão 16):** formato JSON do `check`/`erase` (JSON Lines,
> ver acima); o campo `volume` do banco bate com `/Volumes/<volume>`; exit code 0 = sucesso. O ciclo
> `check → erase → ejeta` rodou de ponta a ponta com o cartão Sony "Joe". Falta: integrar ao loop
> automático da `auditoria.py` e exercitar via `inicializar_gma.py`.

> **Dependência da fonte de frames (decisão 2026-06-07):** quando o extrator
> estiver configurado para ler os frames do **cartão** (destino em servidor de rede),
> a Camada 4 deve esperar os frames terminarem antes de acionar o Parashoot.
> Ordem segura: cópia → verificação → frames do cartão → auditoria C4 → Parashoot.
> A implementar quando o extrator for integrado ao fluxo (próxima fase).

### Camada 5 — Interface (GUI), multi-máquina e terceirização `[FUTURO]`
- Interface visual para operador (substitui o terminal)
- Painel web servido pelo Flask, acessível pela segunda e terceira máquinas
- **Suporte multi-máquina (2–3 bases) + consistência entre instâncias:** coordenação na rede
  local, identificação de qual base originou cada registro, como as bases compartilham a
  numeração.
- Documentação e treinamento para operadores terceirizados
- **Configuração por máquina (decisão 2026-06-07):** tudo que depende de instalação e setup
  em cada máquina GMA (ngrok, autenticação, webhook, `.env`) é responsabilidade e supervisão
  da Camada 5 — integração total do sistema.
- **Processos internos e integração de ferramentas (decisão 2026-06-07):** decisões sobre
  qual ferramenta de formulário usar (Tally, Google Forms ou outra futura) e como ela se
  integra ao Flask são da **Camada 3** — guardiã do fluxo de informação que entra no banco.
- **Janelas e tempo real (decisão 2026-06-12):** a C5 abre as telas como **janela nativa**
  (pywebview) e entrega atualização em **tempo real** (SSE — cópia e edições atualizam só o card
  que muda, sem recarregar). Inclui o **2º monitor** (Mural dos Câmeras em tela cheia).
- **Porta de despacho para a IA (Camada 6):** a C5 **enfileira** tarefas de análise (manifesto +
  miniaturas) de forma assíncrona — nunca executa a IA e **nunca expõe mídia bruta**.
- **Segurança e licenciamento do produto (decisão 2026-06-12):** proteção honesta (licença por
  máquina + separação cérebro/dados; ofuscação/Nuitka só se houver venda ampla). **Keygen** por
  tempo limitado = futuro (Fase 4+), verificação offline-first. Integração com APIs sempre por
  **fila assíncrona**, credenciais no `.env`, **mídia nunca viaja**. Detalhe em `plano_camada5_GMA.md` §6.1.

### Camada 6 — IA assíncrona (opcional) `[FUTURO]`
- Gemini API — análise visual de conteúdo
- Claude API — busca conversacional do acervo
- Roda em fila assíncrona, desacoplada do ciclo rápido, com controle de custo

### Camada 7 — Marca & Design `[PLANEJADO]`
- Identidade visual do GMA (logo, paleta, tipografia)
- Layouts de interface e materiais de apresentação
- Ações de venda e estratégia de distribuição do produto
- **Prazo inicial:** identidade visual pronta até 2026-06-20

---

## 7. Estrutura de pastas do projeto

```
/Users/serafa/GMA/
│
├── inicializar_gma.py       ← PONTO DE ENTRADA: sobe 4 processos com um comando
├── encerrar_gma.py          ← encerramento de emergência
│
├── porteiro.py              ← [Camada 1] detecta cartões/volumes novos
├── leitor_midia.py          ← [Camada 1] analisa conteúdo dos cartões
├── matcher.py               ← [Camada 1] cruza material + formulário
├── flask_gma.py             ← [Camada 1] servidor local (formulários + painel)
│
├── transferencia.py         ← [Camada 2] polling, monta destino, aciona copiador, valida, gera PDF
├── copiador.py              ← [Camada 2] MOTOR OFICIAL — cópia MD5 + fallback copyfile + log .sppo
│
├── banco_dados.py           ← [Camada 3] inicializa gma.db, define schema, obter_conexao(), registrar_evento()
├── gma.db                   ← [Camada 3] banco SQLite local — fonte única de verdade (5 tabelas)
│
├── extrator_frames.py       ← [mecânico, pós-cópia] extrai frames + metadados do destino → manifesto.json (alimenta PDF/CSV/painel)
│
├── ler_cartao.py            ← leitura e classificação de material
├── gma_correcao.py          ← correção de registros (append-only)
├── gma_relatorio_pdf.py     ← parser XML .sppo + gerador de PDF
│
├── google_apps_script.js    ← código para colar no Google Apps Script
├── instrucoes_apps_script.md ← guia de configuração do Forms
│
├── fila_material/           ← JSONs de cartões detectados (Porteiro → Leitor)
├── fila_forms/              ← JSONs de formulários recebidos (Flask → Matcher)
├── contadores/              ← [Camada 2] <NOME>.json: próximo nº de cartão por profissional
├── entrada/                 ← pasta de ingestão manual (AirDrop, link externo)
│
├── TESTE LOGAGEM/           ← destino de teste local (em vez de HD externo)
│
├── logs/
│   ├── porteiro.log
│   ├── leitor_midia.log
│   ├── flask_gma.log
│   ├── matcher.log
│   ├── transferencia.log
│   └── copiador.log         ← será criado junto com copiador.py
│
├── RELATORIOS/                  ← relatórios do ShotPutPro organizados por dia
│   ├── 20260606/
│   │   ├── relatorio_*.pdf      ← gerado pelo SPP ao final de cada cópia
│   │   └── apanhado_20260606.pdf ← consolidado do dia (feature nativa SPP)
│   └── 20260607/
│       └── ...
│
├── documento_mestre_GMA.md  ← este arquivo
├── organograma_GMA.md       ← mapa visual: 3 zonas, processos, 3 acessos, subagentes
├── CLAUDE.md                ← instruções para o orquestrador Claude
└── .gma_ativo               ← sentinela: existe = sistema ativo
```

### Estrutura de pastas de destino (material transferido)
```
EVENTO / DATA(AAAAMMDD) / TIPO DE MATERIAL / NOME / NOME_NNN
```
- `NOME` = nome do profissional de captação (campo `nome` do formulário).
- `NOME_NNN` = nome + número sequencial do cartão dele (vem do `contadores/<NOME>.json`).
Exemplo:
```
RIO2C / 20260315 / VIDEO / JOAO  / JOAO_001
                                   JOAO_002
                          PAULO / PAULO_005
```

---

## 8. Arquitetura da Camada 1 (detalhes técnicos)

### Os 4 processos que rodam em paralelo

| Processo | Arquivo | Função | Intervalo |
|---|---|---|---|
| Porteiro | `porteiro.py` | Detecta volumes novos em `/Volumes/` e `entrada/` | 2s |
| Leitor | `leitor_midia.py` | Analisa JSONs novos em `fila_material/` | 3s |
| Flask | `flask_gma.py` | Recebe Forms, serve painel, chama Matcher | sob demanda |
| Matcher | `matcher.py` | Chamado pelo Leitor e pelo Flask após cada evento | sob demanda |

### Tabela ASSINATURAS_CAMERA (8 marcas)

| Marca | Reconhecida por |
|---|---|
| Canon/Nikon/Fuji genérica | Pasta `DCIM/` + extensões `.cr2/.cr3/.nef/.raf` |
| Sony | Pasta `PRIVATE/` ou `AVCHD/` + `.arw/.mxf/.mp4` |
| Blackmagic | Pasta `Blackmagic Design/` ou arquivos `.braw` |
| RED | Pasta `RDC/` ou `REEL/` + `.r3d` |
| Arri | Pasta `Arri/` + `.ari/.mxf` |
| Panasonic | Pasta `CONTENTS/` + `.rw2/.mts/.mov` |
| GoPro | `DCIM/` + `Get_started_with_GoPro.url` + `.mp4` |
| DJI | Pasta `DJI/` + `.dng/.mp4/.mov` |

### Sistema de match (pontuação)

| Critério | Pontos |
|---|---|
| Marca da câmera bate | +3 |
| Data de gravação bate | +2 |
| Nome da produtora aparece no nome da pasta | +2 |
| **Score ≥ 3** | **= match confirmado** |

Material ou formulário sem par após 10 minutos → **alerta de órfão** no painel.

### Sentinela de ativação
- `touch /Users/serafa/GMA/.gma_ativo` → liga o sistema
- `rm /Users/serafa/GMA/.gma_ativo` → pausa (processos continuam rodando, mas não processam)
- O painel web tem botões Ativar/Desativar que fazem isso automaticamente

### Normalização de dados (Forms → Matcher)
- Câmera: primeira palavra com inicial maiúscula (`"blackmagic pocket"` → `"Blackmagic"`)
- Produtora: maiúsculas (`"produtora x"` → `"PRODUTORA X"`)
- Data: sempre `AAAA-MM-DD` (Apps Script normaliza os formatos do locale)

---

## 9. Tratamento de riscos

### Cartão não formatado (conteúdo de múltiplos dias)
- Detectado pelo `leitor_midia.py` ao comparar as datas de modificação dos arquivos.
- Se `dias_distintos > 1`: campo `alerta_multidia: true` no JSON + log destacado.
- O painel Flask exibe o alerta automaticamente.
- **Fluxo atual**: alerta ao operador → decisão manual → cópia seletiva se necessário.
- **Meta Camada 4**: sistema decide sozinho, escala ao operador só em caso de ambiguidade real.

### Verificação de data/hora das câmeras
- **Estágio 1 (implementado)**: datas de modificação dos arquivos vs. data informada no Forms.
  Divergência → `alerta_multidia: true`.
- **Estágio 2 (estudar)**: verificação cruzada de hora entre câmeras (ver seção original).

### Cartão ejetado antes da análise
- `leitor_midia.py` verifica se o caminho ainda existe antes de analisar.
- Se não existe: `"status": "caminho_nao_encontrado"` — não bloqueia nada.

### Flask fora do ar (celular em 4G)
- O Apps Script registra o erro no log de Execuções mas não trava o Forms.
- O operador precisa verificar se o celular está na mesma rede Wi-Fi do evento.

---

## 10. Modelo de segurança

**Regra de ouro: o Flask controla o processo, nunca o conteúdo.**

- Os arquivos de mídia ficam exclusivamente no HD físico da máquina GMA ou no storage
  do cliente. **Nunca** sobem para a nuvem.
- O que pode ir para a nuvem: metadados, log de check-in, relatórios XLS — nunca arquivos de mídia.
- Quem precisa dos arquivos acessa o HD diretamente, com permissões físicas.

### Segurança do Flask local
**Aplicar:** login com senha; servir só metadados; rede local privada do evento (roteador
dedicado); log de cada acesso; porta não-padrão (5050).
**Nunca:** expor o Flask à internet sem autenticação; servir arquivos de mídia pelo Flask;
usar Wi-Fi público do evento; rodar sem senha em rede compartilhada; guardar credenciais no código.

**Acesso da segunda máquina:** trocar `host="127.0.0.1"` por `host="0.0.0.0"` em `flask_gma.py`
apenas na rede local confiável do evento. Nunca em Wi-Fi público.

### Proteção do software e dos dados (nota da Camada 5 — 2026-06-12)
**Honestidade técnica:** Python é interpretado — **não há proteção de código-fonte inviolável**; um
`.app` pode ser revertido por alguém técnico. O que **protege de verdade**: **licença por máquina**
(impressão digital do hardware) + **separação cérebro/config/dados** (quem copia o app não leva
credenciais, banco nem destino). O que é **teatro**: senha embutida no `.app`, "criptografar" o
Python. Compilar com **Nuitka** só compensa com venda ampla. **Keygen por tempo limitado** (chave
assinada, validação **offline-first**) e **licença por máquina** ficam como item **FUTURO** da
Camada 5 (Fase 4+); distribuição para terceiros ainda **indecisa**. Detalhe em `plano_camada5_GMA.md` §6.1.

---

## 11. Segunda máquina (operação em paralelo)

- A máquina principal roda o Flask na porta 5050.
- A segunda máquina acessa pelo navegador via IP da rede local: `http://192.168.x.x:5050`
- Mesmo servidor Flask que recebe o formulário serve o painel (um código, dois usos).
- Acesso remoto: possível via **ngrok** (gratuito, com limitações). VPS só quando o sistema
  estiver maduro.

---

## 12. Scripts desenvolvidos

### Camada 1 — todos prontos ✅

| Script | Função |
|---|---|
| `inicializar_gma.py` | Sobe **4 processos** + detecta zumbis antes de iniciar. `python3 inicializar_gma.py` |
| `encerrar_gma.py` | Encerramento de emergência (mata todos os 4 scripts). `python3 encerrar_gma.py` |
| `porteiro.py` | Filesystem watcher. Detecta volumes e `entrada/`. Escreve JSONs em `fila_material/`. Detecção GoPro via arquivo `Get_started_with_GoPro.url` (Pass 0) |
| `leitor_midia.py` | Consome `fila_material/`, analisa conteúdo, detecta multi-dia, chama Matcher |
| `matcher.py` | Cruza `fila_material/` com `fila_forms/` por pontuação. `tentar_match()`, `verificar_orfaos()` |
| `flask_gma.py` | Recebe Forms (POST /forms), serve painel (GET /), controla sentinela |
| `ler_cartao.py` | Leitura e classificação por extensão, dedução de câmera, análise de datas |
| `gma_correcao.py` | Correção de registros (append-only, auditoria completa) |
| `gma_relatorio_pdf.py` | Parseia log XML `.sppo` e gera PDF formatado |
| `google_apps_script.js` | Conector Google Forms → Flask. Colar no Apps Script do evento |
| `ngrok_gma.sh` | Expõe Flask (porta 5050) via túnel público ngrok — imprime URL pronta para o painel do Tally |
| `.env.exemplo` | Modelo de configuração de segredos (copiar para `.env` e preencher `TALLY_WEBHOOK_SECRET`) |

### Camada 2 — pronta para teste ✅

| Script | Função |
|---|---|
| `transferencia.py` | Polling da fila, monta destino, aciona `copiador`, valida integridade, gera PDF |
| `copiador.py` | **MOTOR OFICIAL**: cópia MD5 por arquivo + fallback `copy2→copyfile` em arquivos de sistema + log `.sppo` |

---

## 13. Histórico de sessões — Camada 2

### Sessão 1 — 2026-06-06: 1º teste com cartão real

Pipeline do GMA funcionou ponta a ponta (detecção → análise → match → cálculo de destino →
cópia → PDF). GoPro, 106 arquivos / 7,7 GB. **Bugs encontrados:**

1. Processos zumbis: `transferencia.py` faltava na lista de kill do `encerrar_gma.py`; `inicializar_gma.py` não verificava instâncias duplicadas.
2. Detecção GoPro errada: "Genérica/Canon" (com `DCIM/`) disparava antes da assinatura GoPro.
3. `copiador.py` marcava `transferencia_ok=False` por 3 arquivos de sistema da GoPro (`copy2` falhava com "Operation not permitted").
4. Terminologia: decidido adotar **match/matched** em vez de casado/casamento.

**O que já funcionou:**
- Sistema subindo com 4 processos via `inicializar_gma.py` ✅
- Porteiro detectando cartão automaticamente ✅
- Leitor analisando conteúdo e disparando alerta multi-dia ✅
- Flask recebendo formulário e chamando Matcher ✅
- Match confirmado: pontuação 5 (câmera +3, data +2) ✅
- Transferência detectando o matched e criando pasta de destino ✅
- Estrutura de pasta criada: `TESTE LOGAGEM/20260606/VIDEO/PRODUTORA_TESTE/PRODUTORA_TESTE_001` ✅
- PDF gerado corretamente a partir do `.sppo` ✅

---

### Sessão 2 — 2026-06-06: correção dos bugs + terminologia

Todos os bugs da sessão 1 corrigidos:

1. ✅ **Terminologia match/matched** aplicada em todo o código e UI (5 arquivos alterados). Status nos JSONs: `"aguardando_match"` e `"matched"`. Campos: `"form_match"`, `"material_match"`, `"match_timestamp/pontuacao/criterios"`. Função `tentar_match()`.
2. ✅ **Processos zumbis:** `transferencia.py` adicionado à lista de kill do `encerrar_gma.py`. `inicializar_gma.py` agora detecta instâncias ativas e oferece encerramento automático (SIGTERM + SIGKILL) antes de subir.
3. ✅ **Fallback `copy2 → copyfile`:** `copiador.py` tenta `shutil.copy2` e, em caso de "Operation not permitted" (arquivos de sistema da câmera), cai automaticamente para `shutil.copyfile`. Resultado: 106/106 arquivos da GoPro passam sem erro.
4. ✅ **Detecção GoPro:** adicionado "Pass 0" em `volume_parece_camera()` que verifica `arquivos_raiz` (arquivos únicos na raiz do cartão) antes de qualquer verificação de pasta. GoPro detectada via `Get_started_with_GoPro.url`. "Genérica/Canon/Nikon/Fuji" movida para o fim da tabela `ASSINATURAS_CAMERA`.

---

### Sessão 3 — 2026-06-06: política de integridade + religação do motor

1. ✅ **Política mídia vs. sistema (denylist conservadora)** no `copiador.py`: `eh_arquivo_sistema()`
   classifica cada arquivo. Falha de cópia/MD5 em arquivo de SISTEMA do cartão (`.url`, `.log`,
   `.bk`, `.bak`, `.ini` + nomes explícitos) vira **AVISO** e NÃO zera a transferência; footage e
   qualquer extensão desconhecida continuam **CRÍTICOS**. `copia_ok = (zero falhas críticas)`.
   Direção segura: uma falha de footage nunca é silenciada. O `.sppo` ganhou `critical="yes/no"`
   por arquivo e `systemWarnings` no `<summary>` (retrocompatível). Motivo: no 1º teste, 3 arquivos
   de sistema da GoPro zeravam uma transferência com 103/103 do footage íntegro.
2. ✅ **Relatório PDF** (`gma_relatorio_pdf.py`): falhas não-críticas aparecem como **AVISO** (âmbar)
   em vez de FALHO (vermelho); linha "Avisos (sistema)" no resumo. Logs sem o atributo `critical`
   são tratados como crítico (comportamento antigo preservado).
3. ✅ **`transferencia.py` religado ao `copiador.py`** (linha 78: `import copiador`). Antes ainda
   importava `integrador_spp` (ponte ShotPutPro), contradizendo a decisão de motor. Agora o motor
   oficial roda de fato em produção. `integrador_spp.py` fica como plano B histórico (não apagar).
4. ✅ **Teste de regressão** `teste_copiador_politica.py` (5 casos: fallback, aviso de sistema,
   falha crítica de footage, classificação, atributos do `.sppo`) — todos passando.

### Sessão 4 — 2026-06-07: contador de cartões + redefinição de escopo das camadas

1. ✅ **Contador de cartões por profissional** no `transferencia.py`: função antiga
   `calcular_numero_sequencial()` (contava pastas no destino — frágil) substituída por
   `proximo_numero_sequencial(nome)`, que lê e incrementa um arquivo `contadores/<NOME>.json`.
   Não depende mais do estado das pastas no destino. Direção segura: prefere "pular" um número a
   gerar dois cartões com o mesmo nome.
2. ✅ **Campo `produtora` → `nome`** em todo o `transferencia.py` (o GMA roda para uma produtora
   por instância; o que varia é o profissional de captação). Pendência: renomear o campo também
   no Google Forms / ficha online.
3. ✅ **Estrutura de pasta** confirmada: `EVENTO/DATA/TIPO/NOME/NOME_NNN` (ex.: `JOAO/JOAO_001`).
4. ✅ **Redefinição de escopo das camadas:** numeração de cartões → Camada 2 (feita);
   Camada 3 fica exclusiva de controle/segurança das informações (SQLite + Sheets);
   multi-máquina + consistência entre instâncias → Camada 5.

### Sessão 7 — 2026-06-07: teste com cartão real + organograma FigJam

1. ✅ **Organograma visual criado no FigJam** com estado atual de todas as camadas, cores por
   status (verde = concluído, laranja = em build/teste, cinza = planejado, amarelo = prazo próximo)
   e os 3 pontos de acesso. URL: https://www.figma.com/board/UxCKrA3q1vMvfiZQCtKVCf

2. ✅ **Teste com cartão real (GoPro, 7,7 GB)** — ciclo completo bem-sucedido:
   - Porteiro detectou o cartão automaticamente ✅
   - Formulário recebido e match confirmado ✅
   - **Tripla verificação passou**: CHECKSUM OK + CONTAGEM OK (106==106) + TAMANHO OK (0.00%) ✅
   - PDF gerado ✅
   - **CONTAGEM DIVERGENTE do teste anterior foi resolvida** — desta vez CONTAGEM OK ✅

3. 🐛 **Bug identificado: banco gravou 0 arquivos** — `BANCO | 0 arquivo(s) gravado(s) na tabela
   arquivos`. Suspeita: índice único `(cartao_id, caminho_origem)` bloqueando reinserção quando o
   mesmo cartão físico é transferido mais de uma vez (caminhos de origem idênticos, novo `cartao_id`).
   A investigar na Camada 3.

4. 📌 **Decisão confirmada: ejeção depende da Camada 4** — o operador não deve ejetar o cartão
   após `transferencia_ok`. A ejeção só ocorre depois que a Camada 4 (ainda não construída) faz
   a auditoria independente e marca `status = concluido`. Em testes, a ejeção é manual e consciente.

5. 📌 **Placeholder de nome confirmado**: usar `NOME_DO_PROFISSIONAL` como exemplo genérico em
   comandos curl e documentação (autoexplicativo, em vez de `JOAO`).

6. ⚠️ **PDF sem frames/thumbnails** — o `gma_relatorio_pdf.py` atual só lê o `.sppo` e gera
   tabela de arquivos. Ferramentas instaladas (ffmpeg, exiftool, mediainfo, Pillow, reportlab)
   mas nunca chamadas. **Próxima sessão: implementar o PDF rico com folha de contato e thumbnails.**

### Como testar (próximo teste com cartão real)

**Preparação:**
- Cartão de memória com material real em mãos
- Terminal com Full Disk Access concedido (Configurações → Privacidade → Acesso Total ao Disco)
- Formulário de teste pronto (celular ou curl abaixo)

**Iniciar o sistema:**
```bash
python3 /Users/serafa/GMA/inicializar_gma.py
```
Se houver processos rodando, o sistema pergunta antes de continuar. Conectar cartão + enviar formulário → ciclo completo automático.

**Formulário de teste via curl:**
```bash
curl -X POST http://127.0.0.1:5050/forms \
  -H "Content-Type: application/json" \
  -d '{"nome":"JOAO","camera":"GoPro","tipo_material":"VIDEO","data_gravacao":"2026-06-07","operador":"Teste"}'
```

**Ciclo esperado:**
Matcher faz match → Transferência monta destino → `copiador.py` copia + MD5 + gera `.sppo` →
`transferencia.py` detecta o `.sppo`, valida checksums → gera PDF → marca `transferencia_ok: true`.

### Configuração de permissão necessária (feita uma vez por máquina)
**Terminal precisa de Full Disk Access** para acessar cartões de memória sem diálogo de permissão.
Configurações do Sistema → Privacidade e Segurança → Acesso Total ao Disco → adicionar Terminal.

---

## 13.1. Próximos passos

1. **PDF Overview — PRÓXIMA SESSÃO:** criar o gerador de PDF no estilo **Overview** (dashboard +
   folha de contato) que **lê** o `manifesto.json` (mídia) + `.sppo` (integridade) e só **desenha**
   (não extrai nada). Briefing completo na **§13.4**. Material de teste (manifesto + 224 frames)
   já gerado pelo `extrator_frames.py`.

2. ~~**Sistema de relatórios — extração de frames/metadados**~~ ✅ **FEITO (sessão 9):**
   `extrator_frames.py` gera o `manifesto.json` (metadados + 10 frames por vídeo). A inteligência
   de mídia (antes prevista no Leitor) virou um passo mecânico pós-cópia. Ver §13.2 e sessão 9.

3. **Integrar o extrator ao fluxo + fonte automática de frames:** ligar
   `extrator_frames.gerar_manifesto()` no `transferencia.py` após a cópia verificada, e implementar
   a **escolha automática da fonte** dos frames (cartão vs destino — plano aprovado na sessão 9).

4. **Relatórios CSV/TXT (Acesso 3):** a partir do mesmo `manifesto.json` + `.sppo` (1 linha por
   arquivo; o CSV alimenta a Planilha de Análise).

5. **Exportação para Google Sheets (Camada 3):** assíncrona, offline-first, só metadados.

6. **Fichas online (entrada de dados):** ✅ Endpoint `/forms/tally` pronto no Flask. Pendente
   (→ **Camada 5**): ngrok por máquina, autenticação, webhook e `.env` em cada máquina.

7. ~~**Organograma no Miro**~~ ✅ **FEITO (sessão 10):** board "GMA — Mapa Vivo do Projeto"
   em https://miro.com/app/board/uXjVHI0rvt4=/ (fluxo do cartão + prédio de 7 andares + linha
   do tempo). Manter sincronizado com o `organograma_GMA.md` a cada decisão grande.

---

## 13.2. Spec do sistema de relatórios (referência: ShotPutPro) — 2026-06-06

Definido a partir dos 3 modelos de relatório do ShotPutPro (TXT, CSV, PDF) enviados pelo
idealizador. **Princípio central:** o relatório é o **JOIN de dois especialistas, pela chave =
caminho/nome do arquivo** — a inteligência de mídia (Camada 1) + a integridade (Camada 2).

### Divisão por especialista (troca de informação Camada 1 ↔ Camada 2)

| Camada 1 — **Leitor** (mídia) → `manifesto.json` por arquivo | Camada 2 — **copiador** (integridade) → `.sppo` por arquivo |
|---|---|
| codec, resolução, duração, **timecode**, **total de frames**, fps | tamanho (origem + destino) |
| áudio: formato, bitrate, sample rate | checksum (MD5 mínimo; opc. xxHash64) |
| modelo da câmera, tipo/classificação | status: copiado → verificado |
| **frame/thumbnail** extraído | origem / destino + resultado da verificação |

O **gerador de relatórios** junta os dois e emite **3 saídas** (espelhando o ShotPutPro):
- **CSV** — 1 linha por arquivo (mídia + integridade) → alimenta a **Planilha de Análise (Acesso 3)**.
- **PDF rico** — relatório de entrega com **frames/thumbnails**, metadados e layout profissional.
- **TXT** — log hierárquico de auditoria/arquivo (o `.sppo` XML continua sendo o registro de máquina).

### Cabeçalho/resumo do relatório (do TXT do ShotPutPro)
Nome da replicação (= cartão/job), status final, tamanho total, tipo de checksum, início/fim,
tempo decorrido, detalhes do sistema (macOS, CPU, RAM, versão), checksum da raiz origem vs destino.
Acrescentar o que o ShotPutPro não tem: **dados do match** (produtora, câmera, tipo — vindos do form).

### Ferramentas (todas gratuitas) — INSTALADAS em 2026-06-06 ✅
- **ffmpeg/ffprobe 8.1.1** (`/opt/homebrew/bin`) — metadados de vídeo + extração de frames. **Chave.**
  Testado: extrai codec/resolução/frames/duração + áudio, e gera thumbnail. ✅
- **mediainfo 26.05** — metadados com saída templável (`--Inform`), limpa para relatórios.
  Testado: `HEVC | 4000x3000 | 23.976 fps | 615 frames | AAC 48kHz`. Complementa o ffprobe. ✅
- **exiftool** — EXIF de foto/RAW. Testado: retorna `Make`/`Model` (ex.: **GoPro / HERO7 Black**),
  dimensão, data. ✅
- **poppler** (`pdftoppm`, `pdfinfo`) — renderizar/analisar o PDF de referência do ShotPutPro. ✅
- **Pillow** + **reportlab** (já estavam) — miniaturas e geração de PDF.

> **Achado bônus:** o `exiftool`/`ffprobe` dão o **modelo real da câmera** (ex.: "GoPro HERO7 Black"),
> que é a identificação autoritativa — **resolve também o bug de detecção GoPro** da Camada 1
> (substituir a heurística de pasta por leitura de metadados quando disponível).

### Regras de segurança/performance
- Extrair frames/metadados **do arquivo no destino já verificado** (não do cartão) para não
  competir com a cópia nem estressar o cartão.
- Aproveitar proxies que o cartão já traz (GoPro: `.THM` = thumbnail, `.LRV` = proxy) quando existirem.

### Layout do PDF (mapeado do modelo renderizado — 2026-06-06)

O PDF de referência (`TESTEGOPRO.pdf`, 11 págs, paisagem letter) tem **3 partes**:

**1. Cabeçalho** (topo da pág. 1): logo + **título = nome do cartão/job** + resumo em **3 colunas**:
   - Col A: Final Status · Size of replication (GB + bytes) · Verification (ex.: Full Checksum) · Total Files
   - Col B: Replication Start · Finish · Elapsed Time · **Media Files** (contagem só de mídia)
   - Col C: macOS · Processors · System Ram
   - GMA acrescenta aqui: **produtora · câmera · tipo · operador** (dados do match).

**2. Folha de contato (só arquivos de MÍDIA):** um bloco por arquivo —
   - **Esquerda (metadados):** Nome (bold) · Size · Created · `formato · resolução · codec` ·
     modelo da câmera · `Duration · TC (timecode) · Frames` · faixa de áudio (`canais · codec · bitrate · sample rate`).
   - **Direita (filmstrip):** **N thumbnails** amostrados ao longo do clipe (N maior p/ clipes mais
     longos). Foto = 1 thumbnail. (Para GoPro, usar o `.LRV`/`.THM`; senão extrair com ffmpeg do destino.)

**3. Detalhes completos (últimas páginas):** "All file details for root source: <pasta>" — bloco de
   texto por arquivo (inclusive os de **sistema**, sem thumbnail), com **tabela de checksums
   origem × destino** (todos os algoritmos), Full Path, Destination, Status, Created/Modified.
   É a parte de auditoria (equivale ao TXT, dentro do PDF).

> Distinção importante: a **folha de contato** mostra só mídia (no modelo: 36 de 106); os arquivos
> de sistema entram só na contagem total e na seção de detalhes. Isso casa com a política do
> copiador (mídia íntegra é o que importa; arquivos de sistema da câmera são secundários).

Renders de referência salvos em `/tmp/gma_pdf_ref/` (efêmero) — regenerar com
`pdftoppm -png -r 150 "<PDF>" saida`.

### Conexão com a Camada 3
Na Camada 3 isso converge para **uma tabela `arquivos`** no SQLite: Camada 1 preenche as colunas de
mídia, Camada 2 as de integridade. As **3 telas** e os **3 relatórios** leem da mesma tabela
(reforça "uma fonte de verdade, três vistas").

### Insumo desbloqueado
O `poppler` foi instalado, então o **PDF de referência** do ShotPutPro
(`/Users/serafa/TESTES LOGAGEM/CARD GOPRO TESTE/TESTEGOPRO_Relatórios/TESTEGOPRO.pdf`) já pode ser
renderizado e estudado por dentro (frames, disposição) para copiar o layout fielmente.

---

## 13.3. Passos para a próxima sessão — criar o agente da Camada 3 (banco-dados-gma)

A Camada 3 é o **banco de dados** (SQLite local) que substitui as filas JSON e vira a **fonte única
de verdade** que alimenta as 3 telas (Acessos 1–3) e os 3 relatórios (§13.2). É o agente que
"costura" tudo. Passos para a sessão de criação:

**1. Criar o arquivo do agente** `.claude/agents/banco-dados-gma.md`, seguindo o padrão dos agentes
existentes (frontmatter `name`, `description`, `tools: Read, Write, Edit, Bash, Glob, Grep`,
`model: sonnet`). Descrição deve deixar claro: cuida de SQLite, exportação para Sheets, a tabela
`arquivos` e o controle de consistência entre os processos; **não** cuida de check-in,
transferência, **numeração de cartões (é da Camada 2)**, ejeção, **multi-máquina (é da Camada 5)**
ou IA.

**2. Desenhar o schema do SQLite** (offline-first, arquivo local em `gma.db`). Tabelas mínimas:
   - `cartoes` — um registro por cartão (ex-`fila_material`): id, volume, caminho, câmera, datas,
     multidia, status, máquina de origem (multi-máquina), timestamps.
   - `formularios` — um por check-in (ex-`fila_forms`): **nome** (profissional de captação),
     câmera, tipo, data, operador.
   - `matches` — o vínculo cartão↔formulário (score, confirmado) — terminologia **match**.
   - `arquivos` — **a tabela-chave**: 1 linha por arquivo, com colunas de **mídia (Camada 1)** +
     **integridade (Camada 2)** (ver §13.2). É o que alimenta CSV/PDF/telas.
   - `eventos` — log append-only de tudo (auditoria).

**3. Migração incremental das filas JSON → SQLite** sem quebrar o que roda: os processos atuais
continuam, mas passam a ler/gravar no banco. Manter os JSON como backup durante a transição.

**4. Exportação para Google Sheets** (espelho de entrega / Acesso 3): só metadados, nunca mídia.
Roda em fila assíncrona (offline-first: enfileira e sincroniza quando há internet).

**5. Controle de consistência entre processos:** garantir que o que a Camada 1 produz e o que a
Camada 2 consome estão coerentes (sem duplicatas, sem registros perdidos); auditoria append-only.

**6. Limites de segurança do agente:** nunca apagar mídia; banco é só metadados; toda operação
destrutiva no banco exige confirmação; backup do `gma.db` antes de migrações.

> **Fora do escopo da Camada 3 (decisão 2026-06-07):** a **numeração dos cartões** já está na
> Camada 2 (`contadores/<NOME>.json`, feito); o **suporte multi-máquina** foi para a Camada 5.

> Pré-requisito recomendado antes desta sessão: ter o **sistema de relatórios (§13.2)** ao menos
> esboçado, pois o schema da tabela `arquivos` precisa casar com os campos dos relatórios.

---

## 13.4. Briefing — próxima sessão: PDF Overview (lendo o manifesto)

**Objetivo da sessão:** criar o gerador de PDF no estilo **Overview** (dashboard + folha de
contato) que apenas **DESENHA** lendo duas fontes prontas — **não extrai mais nada**:
- `manifesto.json` (mídia: metadados + caminhos dos thumbnails) — do `extrator_frames.py`
- `.sppo` (integridade: checksums e status por arquivo) — do `copiador.py`

> **Mudança de abordagem (sessão 9):** na sessão 8, o `gma_relatorio_pdf.py` v2 extraía os frames
> na hora. Agora a extração é do `extrator_frames.py` (feito, mecânico, roda uma vez). O novo
> gerador só faz o **JOIN** (manifesto + sppo) e o layout. Estilo escolhido: **Overview** (não o
> Filmstrip), para o contexto de entrega de conteúdo variado. O gerador atual
> (`gma_relatorio_pdf.py`) pode virar base — mas trocando a extração ao vivo por leitura do manifesto.

### Estrutura do PDF

**Página 1 — Dashboard em cartões** (inspirado no "Summary Overview" do ShotPutPro):
- Topo: nome do job + início/fim
- Cartões: Tempo decorrido · Status (✓ Verificado) · Velocidade
- Máquina (macOS · RAM · CPU) · Verificação (MD5 completo)
- Origem (volume · tamanho) · Destino (pasta)
- Duas colunas: **Arquivos** (total, pastas, barra de tipos vídeo/foto/outro) ·
  **Mídia** (nº de mídia, câmeras, duração total, formatos, resoluções, fps) + **dados do match**
  (profissional · tipo · operador)

**Páginas seguintes — Folha de contato:** um bloco por arquivo de mídia, com os **10 frames**
(do manifesto) + metadados ao lado. Mais frames por arquivo que o Overview do SPP (que usa 1) —
decisão do idealizador para ajudar os editores a ver o conteúdo.

**Últimas páginas — Auditoria:** tabela completa de todos os arquivos com checksum origem ×
destino e status (já existe no gerador atual — reaproveitar).

### De onde vem cada dado
| Bloco | Fonte |
|---|---|
| Tamanho, duração, velocidade, status, checksums | `.sppo` |
| Codec, resolução, fps, câmera, duração, thumbnails | `manifesto.json` |
| Profissional · tipo de material · operador | formulário (passar como `dados_match`) |
| macOS · RAM · CPU | `platform` / `os` (Python) |

### Regras de implementação
- O gerador **não chama ffmpeg/exiftool** — isso já foi feito pelo `extrator_frames.py`. Só lê o
  `manifesto.json` (mídia) + o `.sppo` (integridade) e faz o JOIN pela chave = caminho/nome.
- Rodar **offline** e nunca quebrar se um thumbnail faltar (mostra "sem preview").
- Paisagem letter, cores GMA (verde teal `#1D9E75`). Reaproveitar estilos do `gma_relatorio_pdf.py`.
- Caminhos dos thumbnails no manifesto são **relativos à pasta do manifesto** — resolver a partir dela.
- Ao integrar no fluxo: `transferencia.py` chama `extrator_frames.gerar_manifesto(...)` após a
  cópia verificada e, em seguida, o gerador do PDF Overview.

### Material de teste pronto (cartão GoPro real) — JÁ GERADO na sessão 9
```
TESTE LOGAGEM/20260607/VIDEO/NOME_DO_PROFISSIONAL/NOME_DO_PROFISSIONAL_001/
├── ..._022552.sppo                 ← integridade (106 arquivos)
├── ..._022552_manifesto.json       ← mídia + 224 frames (62 mídias) — PRONTO
└── _GMA_frames/                    ← 224 miniaturas JPEG — PRONTAS
```
Regenerar manifesto/frames (se precisar): `python3 extrator_frames.py "<caminho do .sppo>"`

### Critério de conclusão da sessão
PDF Overview gerado a partir do `manifesto.json` + `.sppo`, com:
- [ ] Página 1: dashboard em cartões (tempo, status, máquina, origem/destino, arquivos, mídia, match)
- [ ] Folha de contato com os 10 frames por vídeo + metadados (lendo do manifesto)
- [ ] Auditoria: tabela completa com checksums origem × destino
- [ ] Gerador **não extrai nada** (só lê manifesto + sppo)
- [ ] Testado sobre o material de teste acima

---

## 14. No radar (não é agora, mas registrado)

- ✅ ~~Numeração sequencial dos cartões~~ — **FEITO na Camada 2** (sessão 4): `contadores/<NOME>.json`
  por profissional. (Na Camada 5, definir como as bases multi-máquina compartilham a numeração.)
- **Plataforma de acesso online à informação do evento** — terceiro destino da informação.
- **Modo solo / projeto pequeno** — operador único, custo mínimo.
- **Transcrição de áudios** organizados por cartão no Sheets.
- **Verificação de hora das câmeras** (Estágio 2) — descrito na seção 9.
- **Marca / identidade visual do GMA** — necessária para apresentação até 2026-06-20.

---

## 15. Prazo e meta de apresentação

**Data:** 2026-06-20 (14 dias a partir de 2026-06-06)

**Escopo mínimo para apresentação:**
- ✅ Camada 1 completa e funcionando
- 🔧 Camada 2 (transferência) — em construção
- 🎨 Marca / identidade visual do GMA

**Como iniciar o sistema para demonstração:**
```bash
python3 /Users/serafa/GMA/inicializar_gma.py
```
Painel: `http://127.0.0.1:5050`

---

## 16. Glossário rápido

- **GMA** — Gerenciamento de Mídia Audiovisual.
- **Check-in** — registro de entrada do cartão no sistema.
- **Porteiro** — processo que monitora montagem de volumes e detecta cartões novos.
- **Leitor de Mídia** — processo que analisa o conteúdo de um cartão detectado.
- **Matcher** — módulo (`matcher.py`) que cruza material detectado com formulário recebido. Internamente usa a função `tentar_match()`.
- **Match** — par confirmado: um cartão detectado + um formulário correspondente. Score ≥ 3 confirma. Status JSON: `matched`.
- **Sentinela** — arquivo `.gma_ativo` que liga/desliga o processamento.
- **Fila** — pasta com arquivos JSON representando eventos pendentes.
- **Órfão** — material ou formulário sem par após 10 minutos.
- **Embaralhamento (scrambling)** — processo (via Parashoot) que prepara o cartão para
  reutilização segura após a transferência confirmada.
- **Cartão não formatado** — cartão com conteúdo de múltiplos dias, que exige tratamento manual.
- **Tripla verificação** — conferência redundante da integridade antes de liberar o cartão.
- **Offline-first** — arquitetura em que o sistema funciona sem internet e sincroniza depois.
- **Append-only** — log que só recebe novas linhas; nada é editado ou apagado.
