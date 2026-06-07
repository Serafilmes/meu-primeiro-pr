# Documento Mestre — Sistema GMA
## Gerenciamento de Mídia Audiovisual para Eventos ao Vivo

> Documento de arquitetura e estado do projeto. Serve como contexto completo para
> continuar o desenvolvimento (inclusive em sessões do Claude Code).
> Última atualização: 2026-06-07 (sessão 8 — PDF rico com thumbnails e folha de contato)

## Estado atual (2026-06-07)

| Camada | Nome | Status |
|---|---|---|
| 1 | Check-in e identificação | ✅ Concluída |
| 2 | Transferência | ✅ Concluída (PDF rico entregue na sessão 8) |
| 3 | Controle e segurança das informações | 🔧 Pronta para teste — SQLite integrado em todos os processos; falta exportação para Google Sheets |
| 4 | Auditoria estrutural e liberação do cartão | 📋 Planejada |
| 5 | Interface (GUI) e multi-máquina | 📋 Futura |
| 6 | IA assíncrona | 📋 Futura |
| 7 | Marca e design | 📋 Planejada (prazo: 2026-06-20) |

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
| 1 | **Painel do Operador** (Centro de Comando) | Operador (base + 2ª/3ª máquina) | Flask local `:5050` — **offline-first** | Parcial (Camada 1) |
| 2 | **Quadro de Acompanhamento** (Kanban dos cartões + post-its) | Operador + set/equipes (read-only) | Flask local — **offline-first** + espelho opcional no **Notion** | A construir (Camada 3 dados + 5 tela) |
| 3 | **Planilha de Análise / Entrega** | Editores + cliente | **Google Sheets** (nuvem) | A construir (Camada 3) |

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

### Camada 3 — Controle e segurança das informações `[EM BUILD 🏗️]`
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

**Próximos passos da Camada 3:**
1. ~~Ligar os processos ao banco~~ ✅ **FEITO (sessão 5)**
2. ~~Migração incremental das filas JSON → SQLite~~ ✅ **FEITO (integração paralela — JSONs ainda existem como backup)**
3. Exportação para Google Sheets (assíncrona, offline-first) — **PRÓXIMO**

### Camada 4 — Auditoria estrutural e liberação do cartão `[PLANEJADO]`

**Redefinido em 2026-06-07.** A Camada 4 é uma **auditoria independente** da Camada 2 — os dois
processos verificam o mesmo material por ângulos diferentes:

- **Camada 2** verifica *arquivo por arquivo* durante a cópia (MD5 criptográfico — cada byte).
- **Camada 4** verifica *a estrutura completa* depois da cópia:
  - Conta pastas e arquivos no destino
  - Compara tamanho total (destino vs. cartão)
  - Confirma que a árvore de destino é estruturalmente idêntica à de origem
  - Se tudo bate → **status do cartão: `concluido`**

**Sobre o embaralhamento (Parashoot):**
O GMA aciona o Parashoot para embaralhar e ejetar o cartão — mas **não tenta replicar** o que
o Parashoot faz internamente. O embaralhamento é uma operação destrutiva e irreversível; feita
errado, a câmera pode não reconhecer o cartão. O Parashoot sabe o que a câmera espera encontrar
após o formato — o GMA só confirma que é hora de acionar e monitora o resultado.

**Fluxo da Camada 4:**
1. Detecta cartão com `status = transferencia_ok`
2. Faz auditoria estrutural (contagem + tamanho)
3. Se confirmado → atualiza status para `concluido` no banco
4. Aciona o Parashoot para embaralhamento/ejeção
5. Registra o evento de conclusão na tabela `eventos`

> **A analisar:** como o Parashoot expõe sua interface para ser acionado pelo GMA
> (CLI, AppleScript, URL scheme). Investigar antes de codar a integração.

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

1. ~~**PDF rico com frames/thumbnails**~~ ✅ **FEITO (sessão 8):** `gma_relatorio_pdf.py` v2
   entregue. 22 páginas, 3 partes: cabeçalho rico + folha de contato + tabela completa.
   GoPro: `.THM`/`.LRV` como proxies. Modelo da câmera detectado via exiftool.

2. **Sistema de relatórios rico (TXT/CSV/PDF, padrão ShotPutPro):** spec completo na **§13.2**.
   Referência (TXT/CSV/PDF) já recebida e analisada. Implica enriquecer o **Leitor (Camada 1)** com
   metadados por arquivo + frames e fazer o JOIN com a integridade do **copiador (Camada 2)**.
   Instalar `ffmpeg`/`exiftool`/`poppler`.
2. **Fichas online (entrada de dados):** ✅ Endpoint `/forms/tally` pronto no Flask. A escolha da ferramenta de formulário (Tally ou outra) e a integração com o Flask são decisões da **Camada 3** (guardiã do fluxo de informação). Pendente (→ **Camada 5**): instalação do ngrok por máquina, autenticação, configuração do webhook e do `.env` em cada máquina.
3. **Organograma no Miro:** desenvolver o organograma (hoje em `organograma_GMA.md`) no **Miro**,
   aproveitando a colaboração de outros agentes IA. Conector Miro já disponível.

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

## 13.4. Briefing — próxima sessão: PDF rico com frames e thumbnails

**Objetivo da sessão:** reescrever `gma_relatorio_pdf.py` para gerar o relatório no padrão
ShotPutPro — com folha de contato visual (thumbnails + metadados por arquivo de mídia).

### O que existe hoje (versão 1)
`gma_relatorio_pdf.py` lê o `.sppo` (XML) e gera: cabeçalho → tabela de arquivos → rodapé.
Sem imagens, sem metadados de mídia. Funcional para auditoria, mas sem valor visual.

### O que queremos (versão 2 — padrão ShotPutPro)

**Estrutura do PDF em 3 partes:**

**Parte 1 — Cabeçalho/resumo** (já existe, melhorar):
- Nome do job + status final + 3 colunas:
  - Col A: tamanho total · verificação · total de arquivos
  - Col B: início · fim · duração · arquivos de mídia (só os de mídia)
  - Col C: dados do match (nome do profissional · câmera · tipo · operador)

**Parte 2 — Folha de contato** (a construir — o coração do relatório):
- Um bloco por arquivo de **mídia** (`.mp4`, `.mov`, `.mxf`, `.jpg`, `.jpeg`, `.png`, `.dng`, `.raw`, `.arw`, etc.)
- **Coluna esquerda (metadados):**
  - Nome do arquivo (bold)
  - Tamanho · data de criação
  - Formato · resolução · codec (vídeo) ou dimensões (foto)
  - Modelo da câmera (via exiftool)
  - Duração · timecode · frames · fps (vídeo) ou `—` (foto)
  - Áudio: canais · codec · bitrate · sample rate (se houver)
- **Coluna direita (filmstrip):**
  - Vídeo: N thumbnails amostrados ao longo do clipe (mín. 3, mais para clipes longos)
    - GoPro: usar `.LRV` como proxy (mais rápido) ou extrair do `.MP4` com ffmpeg
    - Outros: extrair direto do arquivo de destino com ffmpeg
  - Foto/RAW: 1 thumbnail (via Pillow para JPEG, exiftool para RAW)

**Parte 3 — Detalhes completos** (a construir):
- Todos os arquivos (inclusive os de sistema), sem thumbnail
- Tabela: nome · origem · destino · tamanho · checksum origem × destino · status

### Ferramentas disponíveis (todas instaladas em 2026-06-06)
```
ffmpeg/ffprobe  /opt/homebrew/bin/ffprobe   — metadata de vídeo + extração de frames
mediainfo       /opt/homebrew/bin/mediainfo  — metadata com saída templável
exiftool        /opt/homebrew/bin/exiftool   — EXIF de foto/RAW + modelo da câmera
Pillow          pip                          — miniaturas + composição de imagens
reportlab       pip                          — geração de PDF (já em uso)
```

### Regras de implementação
- Extrair frames/metadados **do arquivo no destino verificado** — nunca do cartão.
- GoPro traz `.THM` (thumbnail JPEG nativo) e `.LRV` (proxy de baixa resolução) junto com cada
  `.MP4`. Usar `.THM`/`.LRV` quando existirem — evita re-encodar o clipe original.
- A Parte 2 (folha de contato) é gerada em uma **passagem separada** após a cópia: o
  `transferencia.py` já chama `gma_relatorio_pdf.py` passando o `.sppo`; ajustar a chamada
  para também passar o caminho da pasta de destino.
- O `.sppo` já tem os caminhos dos arquivos de destino — usar como índice.

### Material de teste disponível agora
```
/Users/serafa/GMA/TESTE LOGAGEM/20260607/VIDEO/NOME_DO_PROFISSIONAL/NOME_DO_PROFISSIONAL_001/
├── NOME_DO_PROFISSIONAL_001_20260607_022552.sppo     ← log XML com 106 arquivos
├── NOME_DO_PROFISSIONAL_001_20260607_022552_relatorio.pdf  ← PDF atual (sem frames)
├── DCIM/...                                          ← material GoPro (fotos + vídeos)
├── *.LRV  *.THM                                      ← proxies GoPro prontos para usar
└── ...
```
Testar o PDF novo sobre este material antes de declarar a sessão concluída.

### Critério de conclusão da sessão
PDF gerado a partir do `.sppo` + pasta de destino, com:
- [ ] Folha de contato com pelo menos 1 thumbnail por vídeo e 1 por foto
- [ ] Metadados: nome, tamanho, resolução/duração, modelo de câmera
- [ ] GoPro usando `.THM` como thumbnail (não re-extrai do .MP4)
- [ ] Parte 3 com tabela completa de todos os arquivos
- [ ] `transferencia.py` chamando a nova versão automaticamente ao final da cópia

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
