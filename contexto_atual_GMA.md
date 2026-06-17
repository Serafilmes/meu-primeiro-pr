# Contexto Atual — Sistema GMA
## Estado vivo do projeto (carregar em TODA sessão junto com `arquitetura_GMA.md`)

> Última atualização: 2026-06-16 (sessão 33)
> Para detalhes técnicos históricos, ver `historico_GMA.md` (não carregar por padrão).

---

## Estado das camadas (resumo rápido)

| Camada | Nome | Status |
|---|---|---|
| 1 | Check-in e identificação | ⚠️ Quase completa — Nova Ficha v2 ✅ + multi-seleção/data inteligente/"quem preencheu" (s33); falta mural dos câmeras, login do operador (2.3) e domínio fixo do túnel |
| 2 | Transferência | ✅ Concluída e testada com cartão real |
| 3 | Controle e segurança das informações | ✅ Quase completa — Kanban + Planilha + Molde; **grupos editáveis (lista/texto) → chip+coluna automáticos (s33)**; Google Sheets real NO AR via impersonação (s32); falta Fatia 5 (Sheets dinâmico + multi-projeto) |
| 4 | Auditoria + liberação do cartão | ✅ Concluída — ciclo integrado testado |
| 5 | Plataforma profissional + multi-máquina | 🔧 Em planejamento — agente `plataforma-gma` + blueprint criados |
| 6 | IA assíncrona | 📋 Futura |
| 7 | Marca e design | 📋 Planejada — foco desejado, **sem prazo de data** (s33) |

---

## O que acabou de ser feito (sessões recentes)

### ✅ Sessão 33 (BUILD) — GRUPOS EDITÁVEIS de classificação (Camada 3, peça grande)
**Arquivos:** `banco_dados.py`, `flask_gma.py`. **Tudo commitado.** Testado em navegador real (preview) + curl.
> Princípio do idealizador: **1 ponto de criação** — um grupo, ao ser criado, vira automaticamente um bloco de chips na ficha **e** uma coluna na planilha. "Tudo muito editável." Os grupos deixaram de ser fixos no código e viraram **dados**.

- **Fatia 1 — tabela `grupos_classificacao`** (`chave`·`rotulo`·`multipla`·`ordem`·`ativo`·`sistema`·`modo`). Semeia os 5 padrão (palco/marca/pauta/servico/tag) com as chaves atuais (migração não-destrutiva — `listas_contexto.tipo` segue apontando para a chave). Funções: criar/renomear/mover/ativar/excluir grupo. **Toda operação é logada em `eventos`** (fundação do log; instrumentação ampla + tela ficam com a Camada 5 — ver [[log-operacoes-requisito]]).
- **Fatia 2 — ficha lê os grupos do banco** (`_bloco_classificacao_ficha` itera `listar_grupos(apenas_ativos)`; rótulo e única/múltipla vêm de cada grupo). `CLASSIF_UNICA` esvaziado (regra agora é por grupo). Grupo vazio aparece p/ o operador (com "+ novo"); no remoto, some.
- **Fatia 3 — painel de grupos na aba "Listas"** (`_cabecalho_grupo_html` + rotas `/grupos`, `/grupos/<chave>/editar|mover|ativo|excluir`). Operador cria/renomeia/reordena/ativa/exclui grupos. Excluir só se não usado (senão desativa). Card "Novo grupo".
- **Fatia 4 — planilha gera colunas dos grupos** (`sincronizar_colunas_grupos`: cada grupo → coluna `chip_<chave>` no molde, visível por padrão; propaga rótulo/ordem; remove órfãs). `_colunas_visiveis` só mostra coluna de grupo ATIVO; ordena por bloco. `CATALOGO_PLANILHA` perdeu as 5 colunas chip fixas (agora dinâmicas).
- **+ Modo "escreve na hora" (texto livre)** — grupo ganha `modo` ('lista'|'texto'). No texto, a ficha mostra **caixa de tags** (vários valores por ficha, ex.: nome do entrevistado); tabela nova `formularios_textos`; planilha lê de `textos_por_formulario`. Funções: definir/listar/textos_por_formulario; `grupo_em_uso` cobre texto também.
- **Molde só reflete grupos + sistema** — **removido** o recurso de "coluna personalizada" solta (`/molde/nova`, `/molde/<chave>/excluir`, `adicionar/excluir_coluna_custom`): colunas só vêm dos grupos cadastrados e do sistema. Coluna órfã `custom_entrevistas` limpa. (Corrige a entrada antiga do Molde abaixo.)

### ✅ Sessão 33 (BUILD) — Nova Ficha: multi-seleção, reordenação, data e "quem preencheu"
**Arquivo:** `flask_gma.py`. **Commitado.** Revisão estrutural conduzida com o agente `checkin-gma`.
- **Multi-seleção em TODOS os grupos** (palco/marca/pauta/serviço): um cartão cobre vários. Banco já suportava (`formularios_chips` é N-N) — zero migração. **Contador** "· N marcados" por grupo.
- **Campos antigos aposentados da ficha** ("Tipo de conteúdo" e "Local/cena" — sobrepunham os chips); colunas mantidas no banco p/ fichas antigas. **Chips reordenados** para logo após a data. **Responsivo** no celular (`@media`).
- **"+ novo" inline** nos chips (só operador/local) → cria item na hora via `/listas/criar-inline`.
- **Data inteligente (2.1):** "Quando foi gravado?" assume **Hoje**; só abre o campo de data em "Outro dia".
- **"Quem está preenchendo?" (2.2):** na ficha REMOTA, "Eu mesmo" (operador = o próprio nome) ou "Outra pessoa". Na base segue texto livre (login do operador = **2.3 adiado**).
- **🐛 Fix:** os chips não selecionavam — o JS rodava no `<head>` antes do DOM. Envolvido em `DOMContentLoaded` (vale p/ `JS_CHIPS`, `JS_CHIP_NOVO`, `JS_TEXTO_GRUPO`, `JS_FICHA_TOGGLES`).

### ✅ Sessão 33 (BUILD) — Molde da Planilha (Camada 3) — base
**Arquivos:** `banco_dados.py`, `flask_gma.py`. **Commitado.**
- **Banco:** tabela `molde_planilha` (chave · rótulo · bloco · ordem · visível · sistema). Funções: `sincronizar_catalogo_molde`, `listar_molde(_visivel)`, `definir_visivel_coluna`. (As funções de coluna custom foram **removidas** depois — ver acima.)
- **Flask:** `/planilha` lê as colunas do molde dinamicamente; `GET /molde` liga/desliga colunas individuais e blocos inteiros (pós-produção oculta por padrão). Colunas de classificação vêm dos grupos (Fatia 4).

### ✅ Sessão 32 (BUILD) — Google Sheets real NO AR (Camada 3, via impersonação)
**Arquivos:** `exportador_sheets.py`, `.env`, `.gitignore`. **Sem commit.** Configuração feita com o idealizador (gcloud + autorizações no navegador).
- **Bloqueios encontrados (Workspace `serafa.me`):** (1) a política da org **proíbe baixar chaves de conta de serviço**; (2) o Google **bloqueia o cliente OAuth compartilhado do gcloud** para escopos de Planilhas/Drive. Os dois caminhos clássicos (chave JSON e ADC do usuário) estão fechados.
- **Solução adotada — impersonação de conta de serviço, SEM chave:** a SA `gma-exportador@gma-sheets-65a228.iam.gserviceaccount.com` (projeto `gma-sheets-65a228`); a conta `ale@serafa.me` tem `roles/iam.serviceAccountTokenCreator` sobre ela; o gcloud gera **tokens curtos** sob demanda (`gcloud auth print-access-token --impersonate-service-account=…`). Respeita a política da org e não deixa segredo no disco. Detalhes na memória [[sheets-auth-impersonacao]].
- **Planilha:** criada pelo idealizador (a SA não tem Drive próprio → erro de quota se ela criar) e **compartilhada como Editor com a SA**. ID no `.env`. A SA só enxerga essa planilha.
- **Código (`exportador_sheets.py`):** 🐛 corrigido o bug da `gspread 6.x` (`update(values, range_name)`); ➕ 5 colunas de classificação (chips) → 26 colunas, espelho fiel da `/planilha`; 🔌 carrega o `.env` sozinho; 🔑 novo modo de auth por `GMA_SHEETS_SA` (impersonação) além da chave clássica.
- **Segurança:** `.gitignore` agora bloqueia `credenciais_google.json` e variações (não há chave hoje, mas previne vazamento futuro).
- **Testado:** sincronização real escreveu cabeçalho + 3 linhas na aba "GMA". ⚠️ **Roda com `/usr/bin/python3` (3.9, tem gspread)** — o gcloud trouxe um python@3.14 que NÃO tem as libs.

### ✅ Sessão 32 (BUILD) — Chips na ficha: a ponte chips→ficha→planilha
**Arquivos:** `banco_dados.py`, `flask_gma.py`. **Sem commit.** Conduzido pelo orquestrador; testado ponta a ponta.
- **Banco:** tabela-ponte nova `formularios_chips` (`formulario_id`·`item_id`, PK composta) ligando cada ficha aos itens de `listas_contexto`. Migração não-destrutiva em `inicializar_banco()`. Funções: `definir_chips_formulario` (substitui o conjunto, valida ids contra o vocabulário), `listar_chips_formulario`, `chips_por_formulario` (lote p/ a planilha). **Guard `itens_lista_em_uso` religado** → agora consulta `formularios_chips` (excluir item em uso = recusado; só soft-delete). Decisão: guardar **id** (não texto) — id é estável, planilha faz JOIN, respeita soft-delete.
- **Ficha:** bloco "Classificação" com **chips clicáveis** montados das listas ATIVAS (palco/marca/pauta/serviço = escolha única via JS; tags = múltipla). Vocabulário fechado (só escolhe, não digita). Sem itens ativos → bloco some. Chips são editoriais: **continuam liberados mesmo com a ficha já casada**. Gravados no POST da ficha nova e na edição; remarcados ao reabrir; preservados em erro de validação. Numa entrega dividida (áudio à parte), as duas metades herdam os mesmos chips.
- **Planilha:** 5 colunas novas de classificação (Palco·Marca·Pauta·Serviço·Tags) entre identificação e técnicas, alimentadas por `chips_por_formulario` (1 query).
- **Testado ponta a ponta** (banco isolado + test client do Flask): render dos chips, item desativado não aparece, POST grava, edição substitui, reabertura remarca, guard recusa exclusão de item em uso, planilha renderiza. `gma.db` intocado, fila limpa.
- **`formularios_chips` no `gma.db` real:** será criada no próximo boot (`inicializar_banco`); o guard tem fallback `OperationalError` até lá.
- **Próxima fatia:** blocos/colunas que ligam-desligam por evento (o "molde" da planilha) + importação de fontes para montar as listas.

### 🗺️ Sessão 31 (alinhamento) — Central de Entrada: dois modos + importação (no papel, sem código)
Depois de testar a Fatia 1, o idealizador esclareceu e expandiu:
- A aba **"Listas" é para adição AO VIVO** (evento rolando), não o caminho principal de montar a entrada. O "salvei mas não apareceu na planilha" **não é bug** — falta a ponte chips→ficha→planilha.
- Para montar o grosso da entrada (e criar **moldes/fichas diferentes dentro do mesmo projeto**), quer **importar fontes** — as **4**: lista colada · planilha remota/CSV · PDF/texto · print/imagem.
- **Pipeline desenhado:** Fontes → Extração (candidatos) → **Revisão do operador** (gate: define o tipo, limpa o ruído, confirma) → `listas_contexto`. Os dois modos terminam na MESMA tabela; nada entra cru.
- **Princípios:** colar/CSV/PDF = mecânico, grátis, offline; print = OCR (local grátis ou IA), ok por ser preparação fora do ciclo crítico. "Planilha remota" já provada (li as 5 planilhas Google via export CSV).
- Detalhes na memória do projeto (`entrada-listas-vs-importacao`).

### ✅ Sessão 31 (BUILD) — Aba "Listas de Contexto" (Fatia 1 da gestão de listas)
**Arquivos:** `banco_dados.py`, `flask_gma.py`. **Sem commit.** Delegado ao `checkin-gma`, conferido pelo orquestrador (código presente + tabela criada no `gma.db`).
- **Banco:** tabela nova `listas_contexto` (`id`·`tipo`·`valor`·`ativo`·`ordem`·`criado_em`, `UNIQUE(tipo,valor)`); migração não-destrutiva chamada em `inicializar_banco()`. Tipos: `palco`/`marca`/`pauta`/`servico`/`tag`. Funções: adicionar/listar/ativar-desativar/excluir + guard `itens_lista_em_uso` (hoje vazio — TODO até os chips entrarem na ficha).
- **Flask:** aba "Listas" + rotas `GET/POST /listas`, `POST /listas/<id>/ativo`, `POST /listas/<id>/excluir`. Itens agrupados por tipo; soft-delete preserva histórico; excluir só se não em uso.
- **Portão por papel:** automático — `_portao_de_acesso` já barra qualquer rota fora de `/ficha` e `/forms*` no acesso remoto (testado: `/listas` remoto = 403).
- **Testado ponta a ponta** (adicionar/listar/desativar/reativar/excluir + duplicata + 403 remoto). Laboratório limpo (tabela vazia ao fim).
- **Próxima fatia:** ligar esses itens como *chips* na ficha.

### 🗺️ Sessão 31 (2026-06-15) — Desenho da Planilha de Entrega + IA (planejamento, sem código)
**Conversa de planejamento das Camadas 3 (Sheets) e 6 (IA).** Decisões:
- **Planilha de Entrega = ficha do profissional + colunas técnicas que o sistema gera** (nº de arquivos, tamanho, "íntegro?", status). 4 blocos: identificação · classificação · técnicas · futuro. Referência: base Notion "Loggagem" do RIO2C.
- **Classificação preenchida pelo profissional na ficha, por chips** (palco/marca/serviço/pauta/tags de listas prontas, sem digitação). Operador revisa só se quiser. Ficha tem que ser **prática e objetiva**.
- **Listas de contexto são dinâmicas e geridas só pelo operador** numa página da central — adiciona marca/pauta/palco durante o evento e a opção aparece na hora na ficha. Generaliza o cadastro de profissionais (ativar/desativar/excluir; soft-delete protege o histórico).
- **Numeração `NOME_NNN` é independente da ficha e contínua por profissional** — não reseta por dia, não quebra quando as listas mudam. Planilha continua fatiável por dia (data é coluna).
- **IA — rumo:** Missão A (busca conversacional sobre dados/transcrições) → transcrição de áudio (Whisper **local**, offline, grátis) → análise de imagem (Missão B) por último.

### ✅ Sessão 30 (2026-06-15) — Nova Ficha v2 COMPLETA (Fatia 5 — última)
**Arquivos tocados:** `banco_dados.py`, `flask_gma.py`, `matcher.py`. **Sem commit ainda.**

- **Banco:** tabela `formularios` ganhou 4 colunas (`tem_foto`, `tem_audio`, `tem_video` como booleanos + `nome_audio`). Migração não-destrutiva.
- **Flask:** helpers `_derivar_tipos` e `_tipo_display`; `_processar_e_salvar_formulario` deriva os booleanos, captura `nome_audio` e grava no banco E no JSON da fila.
- **Matcher:** critério de tipo (+1) entende multi-tipo — quebra `tipo_material` em conjunto e pontua se o tipo predominante do cartão estiver entre eles.
- **🔶 REGRA DO IDEALIZADOR — ÁUDIO É SEMPRE TRANSFERÊNCIA À PARTE:** ficha mista (áudio + foto/vídeo) é dividida em **duas fichas** com o mesmo `entrega_id`. Coluna nova `entrega_id` em `formularios`.
- **🔶 DECISÃO ADIADA:** foto+vídeo na estrutura de pastas → resolver com a Camada 2.
- **Testado ponta a ponta.** Laboratório limpo ao fim.

### ✅ Sessão 29 (2026-06-15) — Câmera no cadastro do profissional (Fatia 4)
- Câmera saiu da ficha → mora no cadastro (`profissionais.camera`).
- Matcher busca câmera do cadastro pelo nome; queda de volta para câmera da ficha se não cadastrada.
- **Bug corrigido:** `_proxima_letra` passou a usar a MAIOR letra já atribuída (não COUNT), robusto a exclusões.

### ✅ Sessão 28 (2026-06-15) — Fatia 3 + gestão de profissionais
- Campo TIPO virou caixinhas multi-seleção (Foto/Áudio/Vídeo); NOME virou dropdown fechado filtrado pelo tipo.
- Ativar/Desativar (soft-delete) e Excluir definitivo (só se não em uso) de profissionais.

### ✅ Sessão 27 (2026-06-15) — Fatias 1 e 2 da Nova Ficha v2
- Tabela `profissionais` criada com letra sequencial (A, B, C… estilo Excel).
- Aba **Profissionais** no Flask com cadastro e listagem.

### ✅ Sessão 25 (2026-06-14) — Passo 2 do Matcher (resolução de empate no painel)
- Operador resolve empates com poucos cliques: bloco por cartão + pista dos prefixos de arquivo + botão "Confirmar".
- Tela de resumo antes de confirmar (mostra destino previsto `NOME_NNN`).
- Tabela `match_candidatos` criada (estava no desenho da S18 mas nunca tinha sido construída).

---

## Próximos passos (em ordem de prioridade)

1. 🎨 **Andar 7 — Marca/identidade visual** — **sem prazo de data** (a meta de 20/06 foi descartada na s33). Definir logo, paleta, tipografia e grid **antes** de refazer o PDF, para ele nascer com padrão visual. Filosofia do idealizador: pensar o processo inteiro → mínimo de layout → refinar; fazer certo antes de fazer rápido.

2. 📄 **PDF Overview** — reescrever o gerador no estilo dashboard + folha de contato, lendo `manifesto.json` + `.sppo`. Briefing completo em `arquitetura_GMA.md §PDF`. Material de teste já gerado (224 frames, 62 mídias).

3. 🔌 **Ligar extrator de frames ao fluxo automático** — hoje roda à mão após a cópia; plugar dentro do `transferencia.py`.

4. 🧠 **Fase 2 do perfil** — Matcher usar o perfil aprendido para desempatar sozinho (câmera, prefixo, faixa de numeração). Reduz chamadas ao operador.

5. 📊 **Google Sheets real** (Camada 3) — ✅ **NO AR (s32)** via impersonação. Pendências menores: o exportador precisa do `gcloud` no PATH e roda na sincronização do `inicializar_gma` a cada 60s; testar dentro do sistema completo (até agora só rodado à mão).

8. 🗂️ **Gestão de listas/grupos de contexto** (operador) — Fatia 1 ✅ (aba "Listas", s31); ponte chips→ficha→planilha ✅ (s32); Molde da Planilha ✅ (s33); **GRUPOS EDITÁVEIS Fatias 1-4 ✅ + modo texto ✅ (s33)** — 1 ponto de criação: grupo → chip na ficha + coluna na planilha; lista ou preenchimento livre. **Próxima — FATIA 5 (próxima sessão):** espelhar no Google Sheets as colunas dinâmicas dos grupos **+ multi-projeto** (cada evento = uma planilha Google nova conectada). Cruza Camada 3/5. Ver desenho na memória [[grupos-editaveis-design]]. Pendências menores: agrupar a planilha por profissional; login do operador (2.3 da ficha).

9. 📥 **Central de Entrada — importação de fontes** (preparação) — montar as listas a partir de lista colada / planilha remota-CSV / PDF / print(OCR); pipeline Fontes→Extração→Revisão do operador→`listas_contexto`. Desenho alinhado (s31, sem código); começar pela planilha remota/CSV (já provada).

6. 🖥️ **Mural dos câmeras** (2º monitor) — tela read-only de status + QR fixo (desenho pronto, sessão 21).

7. **foto+vídeo na estrutura de pastas** — decidir junto com Camada 2 (adiado da S30).

---

## 🎯 Próxima sessão — FATIA 5: Sheets dinâmico + multi-projeto

**Objetivo:** fechar o ciclo dos grupos editáveis na nuvem e introduzir o multi-projeto.

Duas frentes que se cruzam (Camada 3 + Camada 5):
1. **Sheets dinâmico** — `exportador_sheets.py` hoje tem 26 colunas FIXAS. Precisa ler as colunas do **molde + grupos** (mesma lógica de `_colunas_visiveis`/`_celula_planilha` da `/planilha`), incluindo os grupos de **texto** (`textos_por_formulario`). Ideal: extrair um "montador de linhas da planilha" compartilhado entre a `/planilha` local e o exportador, p/ não duplicar.
2. **Multi-projeto** — cada evento = uma **planilha Google nova conectada**. Hoje o `.env` tem 1 `GMA_SHEETS_ID` fixo. Decidir: como o operador cria/troca o projeto ativo? (tabela `projetos`? seleção na central? uma planilha por projeto criada pelo idealizador e colada o ID?). O `gma.db` é por-instância/por-trabalho (princípio C5, ver [[multi-projeto-por-trabalho]]) — alinhar se multi-projeto é trocar de instância ou conviver num só banco.

**Antes de codar:** desenhar o multi-projeto com o idealizador (como fizemos com os grupos) — é decisão de arquitetura. O Sheets dinâmico em si é mecânico.
**Lembrar:** roda com `/usr/bin/python3` (3.9 tem gspread); precisa do `gcloud` no PATH; auth por impersonação ([[sheets-auth-impersonacao]]).

---

## Decisões importantes recentes (não mudar sem discussão)

| Decisão | Sessão |
|---|---|
| **Grupos de classificação são EDITÁVEIS (dados, não código)** — 1 ponto de criação: criar um grupo → vira chip na ficha **e** coluna na planilha (visível por padrão). Cada grupo tem regra própria (lista/texto, único/vários). Grupo do sistema ou em uso: só desativa; não usado: pode excluir | S33 |
| **Grupo tem 2 modos: "escolhe da lista" (chips) e "escreve na hora" (texto livre)** — texto guarda vários valores por ficha em `formularios_textos` | S33 |
| **Colunas da planilha vêm SÓ de grupos cadastrados + sistema** — sem coluna "personalizada" solta (removida); Molde só liga/desliga | S33 |
| **Multi-seleção em todos os grupos de chips**; "Tipo de conteúdo"/"Local-cena" aposentados da ficha (chips cobrem) | S33 |
| **Ficha: data assume Hoje** (só pede em "Outro dia"); **"quem preencheu"** = o próprio profissional no remoto; login do operador (2.3) adiado | S33 |
| **Log de operações é da Camada 5** — fundação (tabela `eventos` + grupos já logam) pronta; instrumentação ampla + tela `/historico` ficam com `plataforma-gma` | S33 |
| **Áudio é SEMPRE transferência à parte** — ficha mista gera 2 fichas com `entrega_id` comum | S30 |
| **Planilha de Entrega = ficha do profissional + colunas técnicas do sistema**; classificação por chips (profissional preenche, operador revisa opcional) | S31 |
| **Listas de contexto (palco/marca/serviço/pauta/tags) são dinâmicas**, geridas só pelo operador na central; numeração `NOME_NNN` é independente e contínua | S31 |
| **IA: Missão A (busca) + transcrição local primeiro; imagem (Missão B) depois** | S31 |
| **Planilha inclui bloco de pós (editor/edição/upload), mas variável/opcional por evento** — editores preenchem após a entrega; GMA passa o bastão no "íntegro/loggado"; blocos/colunas inteiros ligam-desligam por evento | S31 |
| **Entrada do vocabulário em 2 modos → mesma lista**: aba "Listas" (ao vivo) + importação de fontes (colar/CSV/PDF/print), com a **revisão do operador como gate** — nada entra cru | S31 |
| **Câmera mora no cadastro do profissional**, não na ficha | S29 |
| **NOME é dropdown fechado** na ficha (sem digitação livre) | S28 |
| **Letra sequencial do profissional** (A, B, C…) é pista visual, não autoridade de identidade | S27 |
| **Passo 2 do Matcher** implementado — empate resolve com tela de resumo (2 cliques) | S25 |
| **Trabalho da s33 todo commitado** na branch `melhoria/readme` (o "sem commit" das s27–32 estava desatualizado — o código já estava commitado) | S33 |

---

## Arquivos com mudanças não commitadas (atenção)

- `exportador_sheets.py` — auth por impersonação (`GMA_SHEETS_SA`), fix gspread 6.x, 5 colunas de chips, carrega `.env` sozinho (s32). **Sem commit.** ⚠️ Ainda tem só 26 colunas FIXAS — **na Fatia 5 precisa virar dinâmico** (ler os grupos, igual à `/planilha`).
- `contexto_atual_GMA.md` + `arquitetura_GMA.md` — docs de fim da s33 (este commit).
- Todos os demais (`banco_dados.py`, `flask_gma.py`, `.claude/launch.json`) **já commitados** na s33.

---

## Links úteis

- **Painel local:** `http://127.0.0.1:5050`
- **Iniciar sistema:** `python3 /Users/serafa/GMA/inicializar_gma.py`
- **Encerrar Flask:** `pkill -f "flask_gma.py"`
- **Board Miro:** https://miro.com/app/board/uXjVHI0rvt4=
- **Banco:** `/Users/serafa/GMA/gma.db`

---

## Pendências menores (não bloqueiam, mas registradas)

- Bug do "0 arquivos no banco" ao regravar o mesmo cartão físico (sessão 7) — índice único colide
- Consistência do banco quando dois cartões têm o mesmo nome de volume ("Untitled")
- Renomear campo `produtora` → `nome` no Google Forms (ainda pendente no Forms externo)
- Loop automático da `auditoria.py` via `inicializar_gma.py` ainda não exercitado em produção
