# Arquitetura — Sistema GMA
## Referência técnica estável (carregar em TODA sessão junto com `contexto_atual_GMA.md`)

> Este arquivo contém o que **não muda** — princípios, stack, fluxo, camadas e estrutura.
> Para o estado atual e próximos passos, ver `contexto_atual_GMA.md`.
> Para histórico detalhado de sessões, ver `historico_GMA.md`.

---

## 1. O que é o GMA

Sistema profissional de gerenciamento de mídia audiovisual para eventos ao vivo. Automatiza o ciclo completo de tratamento dos cartões de memória entregues pelas equipes de captação: identificação, transferência segura com verificação de integridade, registro em banco de dados e embaralhamento/ejeção do cartão para reutilização.

Construído em Python, **offline-first**, custo mínimo, autonomia máxima e segurança absoluta dos arquivos.

---

## 2. Princípios inegociáveis

1. **Offline-first** — ciclo crítico funciona 100% sem internet. Tarefas de nuvem ficam em fila.
2. **Segurança dos arquivos acima de tudo** — material nunca pode ser perdido. Mídia **nunca** vai para a nuvem.
3. **Custo mínimo** — ferramentas gratuitas e processamento mecânico. IA só na Camada 6 (opcional).
4. **Autonomia máxima** — o sistema decide e executa sozinho. Operador é acionado só como último recurso.
5. **Sem filas no set** — ações ágeis no check-in.
6. **Intuitivo para terceirização** — interface simples para operar.

---

## 3. Regras de ouro (não se mexe)

| Regra | Por quê |
|---|---|
| 🐍 Motor de cópia é o `copiador.py` (Python puro) | ShotPutPro não é automatizável |
| 🛡️ Material insubstituível nunca é apagado/movido sem conferir | Princípio nº 2 — em dúvida, não destrói |
| ☁️ Vídeo nunca sobe para a nuvem — só informação sobre ele | Segurança + custo |
| 💰 Sem IA no ciclo principal — só no Andar 6, opcional | Custo mínimo; ciclo roda grátis e offline |
| ⚡ Tudo funciona sem internet | Nuvem só sincroniza depois |
| 🤖 Autonomia máxima — operador é último recurso | Sem filas no set |
| 🎙️ Áudio é SEMPRE transferência à parte | Vem em outro cartão; ficha mista = duas fichas ligadas por `entrega_id` |

---

## 4. Arquitetura: modelo híbrido

- **Filas JSON locais** (`fila_material/`, `fila_forms/`) — comunicação entre processos da C1. Simples, offline.
- **SQLite local** (`gma.db`) — banco operacional. Rápido, offline, gratuito. **Fonte única de verdade.**
- **Google Sheets** — espelho de entrega para editores. Só metadados, nunca mídia.
- **Flask local** — recebe dados da ficha + serve o painel. Porta 5050.

**Princípio central:** UMA fonte de verdade → TRÊS vistas. O dado mora em um lugar só; as telas são formas diferentes de lê-lo.

---

## 5. As 3 zonas e o fluxo completo

```
ZONA 1 — CAMPO/SET
  Câmeras → Cartão → Base
  Profissional preenche ficha (celular/remoto/operador)

ZONA 2 — MÁQUINA GMA (offline-first)
  [C1] Porteiro detecta cartão
  [C1] Leitor analisa conteúdo (extensões, datas, alerta multi-dia)
  [C1] Matcher cruza material + formulário (score ≥ 3 = match)
  [C2] Atribui número (NOME_NNN via contador)
  [C2] copiador.py copia + MD5 por arquivo + gera .sppo
  [C2] extrator_frames.py → manifesto.json + miniaturas
  [C2] Gerador de PDF (lê manifesto + .sppo)
  [C3] SQLite registra / Google Sheets sincroniza
  [C4] Auditoria independente → parashoot check → parashoot erase → cartão ejetado

ZONA 3 — NUVEM/ENTREGA
  Google Sheets — espelho de entrega
  Portal online (futuro)
```

---

## 6. Os 3 pontos de acesso

| # | Tela | Público | Onde vive | Status |
|---|---|---|---|---|
| 1 | Painel do Operador | Operador (base) | Flask `:5050` — offline-first | ✅ No ar |
| 2 | Acompanhamento (Kanban + post-its) | Operador + set (read-only) | Flask `/kanban` — offline-first | ✅ Rascunho no ar |
| 3 | Planilha de Entrega | Editores + cliente | Google Sheets (nuvem) | ⚠️ Espelho local no ar; Sheets real pendente |

---

## 7. As 7 camadas do roadmap

### Camada 1 — Check-in e identificação ✅
Processos: `porteiro.py` · `leitor_midia.py` · `matcher.py` · `flask_gma.py`

- **Porteiro:** filesystem watcher, detecta volumes novos a cada 2s
- **Leitor:** analisa conteúdo, detecta multi-dia, classifica cartão sem mídia em `sem_midia` (trivial/config) ou `revisar` (arquivos grandes não reconhecidos)
- **Matcher:** pontuação — câmera +3 · data +2 · nome na pasta +2 · tipo de material +1. Score ≥ 3 = match. Margem de segurança = 1 (empate → `aguardando_confirmacao`).
- **Flask:** recebe fichas, serve painel, portão de acesso por papel (câmera só enxerga `/ficha`; operação completa só na base)

**Nova Ficha v2 (completa — Fatias 1–5):**
- Tabela `profissionais` com letra sequencial (A, B, C…) — pista visual, não autoridade
- Câmera no cadastro do profissional (não na ficha)
- TIPO em caixinhas multi-seleção; NOME em dropdown fechado filtrado pelo tipo
- Multi-tipo grava como booleanos (`tem_foto`, `tem_audio`, `tem_video`) + 2º nome (`nome_audio`)
- Ficha mista com áudio → duas fichas ligadas por `entrega_id`
- **Classificação na ficha (s31):** o profissional marca palco/marca/serviço/pauta/tags por *chips* de listas geridas pelo operador (ver Camada 3); identidade/numeração ficam separadas da classificação

**Perfil por profissional (Fase 1 — aprender):** a cada match confirmado, o sistema acumula câmera/modelo/prefixo/faixa de numeração. Fase 2 (usar para desempatar) = próximo passo.

**Passo 2 do Matcher:** empate resolve no painel — bloco por cartão com prefixos de arquivo como pista + botão "Confirmar" → tela de resumo com destino previsto → "Iniciar".

### Camada 2 — Transferência ✅
Processos: `transferencia.py` · `copiador.py` · `extrator_frames.py` · `gma_relatorio_pdf.py`

- **Estrutura de pastas:** `EVENTO / DATA(AAAAMMDD) / TIPO / NOME / NOME_NNN`
- **Contador:** `contadores/<NOME>.json` — atômico, independente por profissional
- **copiador.py:** MD5 por arquivo em blocos de 1 MB; fallback `copy2→copyfile` para arquivos de sistema; gera `.sppo` (XML)
- **Política mídia vs. sistema:** falha em arquivo de sistema = AVISO (não zera transferência); falha em footage = CRÍTICO (zera)
- **extrator_frames.py:** 10 frames por vídeo (5%–95%, divisão uniforme); usa `.LRV`/`.THM` da GoPro como proxy; grava `manifesto.json` + miniaturas em `_GMA_frames/`; idempotente

### Camada 3 — Controle e segurança das informações ⚠️
Processo: `banco_dados.py` · `exportador_sheets.py` · Flask (telas `/kanban` e `/planilha`)

**5 tabelas do `gma.db`:**
- `cartoes` — um por cartão detectado
- `formularios` — um por ficha de check-in (14+ colunas incluindo booleanos de tipo, `nome_audio`, `entrega_id`)
- `matches` — vínculo cartão↔formulário confirmado
- `match_candidatos` — candidatos de empate (pendente/escolhido/descartado)
- `arquivos` — **tabela-chave**: 1 linha por arquivo (mídia da C1 + integridade da C2)
- `eventos` — log append-only (auditoria)
- `perfis` — assinatura acumulada por profissional
- `profissionais` — cadastro com letra, tipos e câmera

**Google Sheets:** `exportador_sheets.py` assíncrono, offline-first. Ativar: preencher `GOOGLE_CREDENTIALS_JSON` e `GMA_SHEETS_ID` no `.env`.

**Planilha de Entrega (colunas) — desenho (s31):** é a *vista de entrega* do banco, em 4 blocos:
- **Identificação:** data · nome/fonte (profissional **ou** PGM/feed) · material (F/A/V) · nº do cartão (`NOME_NNN`)
- **Classificação:** conteúdo · tags · palco/sala · marca · serviço/pauta — preenchida pelo **profissional na própria ficha**, por *chips* de listas prontas (não digitação); operador revisa só se quiser. Ficha prática e objetiva.
- **Técnicas (o sistema gera sozinho):** nº de arquivos · tamanho · íntegro? (checksum) · status. Ganho sobre a logagem manual.
- **Futuro:** transcrição (nos cartões de áudio) → alimenta a Missão A.
- **Pós-produção (opcional, variável por evento):** editor · edição · upload — preenchidas pela equipe de edição **depois** da entrega. O GMA entrega até "íntegro/loggado" e passa o bastão; o histórico mostra que a planilha também servia de painel da pós, mas nem todo evento precisa.

**Listas de contexto dinâmicas:** as opções de classificação (marcas, pautas, palcos, serviços, tags) são **listas geridas pelo operador** numa página da central de controle, editáveis **durante o evento** (criar marca/pauta/palco na hora; a opção aparece na ficha em tempo real). Só o operador edita (portão por papel — a câmera escolhe, nunca cria). Mesmo padrão do cadastro de profissionais: soft-delete (ativar/desativar) preserva o histórico; excluir só se não estiver em uso. **A numeração `NOME_NNN` é independente dessas listas e contínua por profissional** — mudar as listas de um dia para o outro nunca afeta a numeração. Referência de colunas: base Notion "Loggagem" do RIO2C. **Não só as opções são variáveis — os próprios blocos/colunas ligam-desligam por evento** (ex.: o bloco de pós-produção aparece só quando o evento precisa): o operador monta o "molde" da planilha daquele trabalho. A planilha também deve poder **agrupar por profissional** (modelo nativo das planilhas antigas), não só por dia.

**Entrada do vocabulário — 2 modos (desenho s31, só a Fatia 1 construída):** (a) *ao vivo* — a aba "Listas" no painel (✅ Fatia 1, manual, 1 item na correria); (b) *importação de fontes* (a fazer) — lista colada · planilha remota/CSV · PDF/texto · print(OCR) → **Extração** (vira candidatos) → **Revisão do operador** (gate: define o tipo, limpa o ruído, confirma) → `listas_contexto`. Os dois modos caem na MESMA tabela; **nada entra cru**. Colar/CSV/PDF = mecânico, grátis, offline; só o print usa OCR (local grátis ou IA), aceitável por ser preparação fora do ciclo crítico. A "planilha remota" lê-se pelo export CSV (provado com as planilhas do RIO2C).

### Camada 4 — Auditoria e liberação do cartão ✅
Processo: `auditoria.py`

Fluxo **totalmente automático:**
1. Polling a cada 10s por cartões `transferencia_ok`
2. Pré-check GMA (pasta existe · contagem bate · tamanho ±0,5%)
3. `parashoot check` (arquivo por arquivo) → `verificado_parashoot`
4. `parashoot erase` → embaralha + ejeta → `concluido`

**Parashoot CLI:** `/Applications/ParaShoot.app/Contents/MacOS/cli/parashoot`. Saída em **JSON Lines (NDJSON)**. `check` sucesso → `{"status":"check_complete",...}`. `erase` → `erase_start` + `erase_complete`. Erro no stderr → `{"status":"error",...}`. O fake-format é **reversível** (inverte 2 MB do MBR; footage intacto).

### Camada 5 — Interface + multi-máquina `[Planejamento]`
- pywebview (janela nativa) + SSE (tempo real sem recarregar)
- 2º monitor: Mural dos Câmeras (read-only, QR fixo)
- Configuração externa por evento (`evento.toml` + `.env`)
- Porta de despacho para IA da C6 (enfileira, nunca expõe mídia bruta)
- Agente `plataforma-gma` criado em `.claude/agents/`

### Camada 6 — IA assíncrona `[Futuro]`
- **Rumo definido (s31):** (1) **Missão A — busca conversacional** sobre os dados estruturados + transcrições; (2) **transcrição de áudio** com Whisper **local** (offline, grátis — respeita os 3 princípios; o áudio não sobe); (3) **Missão B — análise de imagem** das miniaturas (Gemini API) por último.
- A transcrição nasce colada à entrega de áudio (`entrega_id`); só o texto/resumo vai para a planilha, nunca o arquivo.
- Sempre assíncrono, depois do evento, nunca no ciclo crítico.

### Camada 7 — Marca & Design `[Prazo 20/06]`
- Logo, paleta, tipografia, grid
- Layouts de interface e materiais de apresentação

---

## 8. Estrutura de pastas do projeto

```
/Users/serafa/GMA/
├── inicializar_gma.py       ← PONTO DE ENTRADA (sobe todos os processos)
├── encerrar_gma.py          ← encerramento de emergência
├── porteiro.py              ← [C1] detecta cartões/volumes
├── leitor_midia.py          ← [C1] analisa conteúdo
├── matcher.py               ← [C1] cruza material + formulário
├── flask_gma.py             ← [C1] servidor local
├── transferencia.py         ← [C2] polling + cópia + validação + PDF
├── copiador.py              ← [C2] motor oficial MD5 + .sppo
├── extrator_frames.py       ← [C2] frames + manifesto.json
├── banco_dados.py           ← [C3] schema SQLite + funções
├── gma.db                   ← [C3] banco fonte única de verdade
├── exportador_sheets.py     ← [C3] espelho Google Sheets (assíncrono)
├── auditoria.py             ← [C4] auditoria + Parashoot
├── gma_relatorio_pdf.py     ← gerador de PDF (lê manifesto + .sppo)
├── ler_cartao.py            ← leitura e classificação de material
├── fila_material/           ← JSONs cartões detectados
├── fila_forms/              ← JSONs formulários recebidos
├── contadores/              ← <NOME>.json: próximo nº por profissional
├── logs/                    ← porteiro · leitor · flask · matcher · transferencia · copiador
├── TESTE LOGAGEM/           ← destino de teste local
├── documento_mestre_GMA.md  ← arquivo original (referência histórica)
├── organograma_GMA.md       ← mapa visual do projeto
├── contexto_atual_GMA.md    ← estado atual + próximos passos (CARREGAR SEMPRE)
├── arquitetura_GMA.md       ← este arquivo (CARREGAR SEMPRE)
├── historico_GMA.md         ← histórico de sessões (carregar só quando necessário)
└── CLAUDE.md                ← instruções para o orquestrador
```

---

## 9. Detecção de câmeras (Camada 1)

| Marca | Reconhecida por |
|---|---|
| GoPro | `Get_started_with_GoPro.url` na raiz (Pass 0) + `.mp4` |
| Sony | Pasta `PRIVATE/` ou `AVCHD/` + `.arw/.mxf/.mp4` |
| Blackmagic | Pasta `Blackmagic Design/` ou `.braw` |
| RED | Pasta `RDC/` ou `REEL/` + `.r3d` |
| Arri | Pasta `Arri/` + `.ari/.mxf` |
| Panasonic | Pasta `CONTENTS/` + `.rw2/.mts/.mov` |
| Canon/Nikon/Fuji | Pasta `DCIM/` + `.cr2/.cr3/.nef/.raf` |
| DJI | Pasta `DJI/` + `.dng/.mp4/.mov` |

Câmera real confirmada via **exiftool** (campo `Make`/`Model`) em até 3 arquivos — nunca estressa o cartão.

---

## 10. Sistema de match (pontuação)

| Critério | Pontos |
|---|---|
| Câmera bate (lida do cadastro do profissional) | +3 |
| Data de gravação bate | +2 |
| Nome aparece no nome da pasta de entrada | +2 |
| Tipo de material bate | +1 |
| **Score ≥ 3 + margem ≥ 1 acima do 2º** | **= match automático** |
| Empate ou margem < 1 | = `aguardando_confirmacao` → Passo 2 |

Material ou formulário sem par após 10 minutos → alerta de órfão no painel.

---

## 11. Acesso remoto e segurança

- **Portão por papel:** acesso remoto (ngrok/internet) só enxerga `/ficha`. Tudo mais → 403.
- **Portão por senha:** `GMA_SENHA` no `.env`; vazia = uso local livre; webhooks `/forms*` isentos.
- **QR da ficha:** detecta URL ativa do ngrok automaticamente (API local `127.0.0.1:4040`). Se-auto-atualiza quando o túnel muda.
- **Flask local:** nunca expor sem autenticação; mídia nunca servida pelo Flask; porta 5050.
- **`GMA_HOST=0.0.0.0`** libera para a rede local (celulares no Wi-Fi do evento).

---

## 12. Spec do PDF Overview (próxima sessão de build)

**Objetivo:** gerador que apenas DESENHA — não extrai nada. Lê duas fontes prontas:
- `manifesto.json` (mídia: metadados + caminhos dos thumbnails) — do `extrator_frames.py`
- `.sppo` (integridade: checksums e status por arquivo) — do `copiador.py`

**Estrutura:**
- **Página 1:** dashboard em cartões — nome do job, tempo, status, velocidade, máquina, verificação, origem, destino, arquivos, mídia, dados do match
- **Páginas seguintes:** folha de contato — um bloco por arquivo de mídia com 10 frames + metadados
- **Últimas páginas:** auditoria — tabela completa com checksums origem × destino

**Regras:** não chama ffmpeg/exiftool; roda offline; nunca quebra se faltar thumbnail; paisagem letter; cores GMA (`#1D9E75`). JOIN pela chave = caminho/nome do arquivo.

**Material de teste pronto:**
```
TESTE LOGAGEM/20260607/VIDEO/NOME_DO_PROFISSIONAL/NOME_DO_PROFISSIONAL_001/
├── ..._022552.sppo           (106 arquivos)
├── ..._022552_manifesto.json (62 mídias, 224 frames)
└── _GMA_frames/              (224 miniaturas JPEG)
```

---

## 13. Glossário

- **GMA** — Gerenciamento de Mídia Audiovisual.
- **Check-in** — registro de entrada do cartão no sistema.
- **Porteiro** — processo que monitora montagem de volumes e detecta cartões novos.
- **Leitor de Mídia** — processo que analisa o conteúdo de um cartão detectado.
- **Matcher** — módulo que cruza material detectado com formulário. Usa `tentar_match()`.
- **Match** — par confirmado: cartão + formulário. Score ≥ 3. Status JSON: `matched`.
- **Sentinela** — arquivo `.gma_ativo` que liga/desliga o processamento.
- **Órfão** — material ou formulário sem par após 10 minutos.
- **Embaralhamento** — processo via Parashoot que prepara o cartão para reutilização.
- **Offline-first** — sistema funciona sem internet; sincroniza depois.
- **Append-only** — log que só recebe novas linhas; nada é editado ou apagado.
- **entrega_id** — vínculo entre duas fichas geradas de uma ficha mista com áudio.
- **Letra sequencial** — A, B, C… atribuída ao profissional no cadastro; pista visual das câmeras no set, nunca autoridade de identidade.
- **Missão A** — IA que conversa com os dados estruturados + transcrições (busca conversacional do acervo). Missão B = análise de imagem (futuro).
- **Transcrição** — fala → texto, gerada localmente (Whisper) nos cartões de áudio; informação pesquisável que alimenta a Missão A.
- **Listas de contexto** — opções de classificação (palco, marca, serviço, pauta, tags), geridas pelo operador e dinâmicas por evento; o profissional só escolhe da lista na ficha.
- **Pauta** — assunto/atribuição de captação; pode ser adicionada pelo operador durante o evento.
