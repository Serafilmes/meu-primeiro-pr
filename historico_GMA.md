# Histórico de Sessões — Sistema GMA
## Arquivo de referência — NÃO carregar por padrão nas sessões

> Carregue este arquivo apenas quando precisar consultar o raciocínio ou contexto de uma sessão específica.
> Para o estado atual do projeto, use `contexto_atual_GMA.md` + `arquitetura_GMA.md`.

---

## Linha do tempo resumida

| Sessão | Data | Tipo | O que foi feito |
|---|---|---|---|
| 1 | 2026-06-06 | Build | 1º teste com cartão real (GoPro, 106 arq/7,7 GB) — pipeline funcionou ponta a ponta |
| 2 | 2026-06-06 | Build | Correção dos bugs da S1 + terminologia match/matched |
| 3 | 2026-06-06 | Build | Política de integridade mídia vs. sistema + religação do motor |
| 4 | 2026-06-07 | Build | Contador de cartões + redefinição de escopo das camadas |
| 5 | 2026-06-07 | Build | Integração SQLite em todos os processos (paralelo com filas JSON) |
| 6 | 2026-06-07 | Build | Endpoint `/forms/tally` + ngrok_gma.sh + .env.exemplo |
| 7 | 2026-06-07 | Teste | Teste com cartão real + organograma FigJam |
| 8 | 2026-06-07 | Build | PDF rico com thumbnails (gma_relatorio_pdf.py v2) |
| 9 | 2026-06-07 | Build | extrator_frames.py + manifesto.json + decisão Overview vs Filmstrip |
| 10 | 2026-06-07 | Orientação | Mapa Vivo — reescrita do organograma + board Miro |
| 11 | 2026-06-08 | Build | exportador_sheets.py (C3) + auditoria.py (C4) |
| 12 | 2026-06-08 | Correção | C3 e C4 declaradas fechadas prematuramente — buracos identificados |
| 13 | 2026-06-08 | Build | Fichas personalizáveis (5 campos editoriais) + Matcher seguro (Passo 1) + Perfil Fase 1 |
| 14 | 2026-06-08 | Build | Agente auditoria-gma criado |
| 15 | 2026-06-09 | Build | Camada 4 reescrita — CLI do Parashoot descoberto e integrado |
| 16 | 2026-06-09 | Teste | Teste de ciclo COMPLETO com cartão Sony "Joe" (57 arq/1,6 GB) |
| 17 | 2026-06-10 | Desenho | Identidade do cartão em camadas (Matcher como autoridade única) |
| 18 | 2026-06-10 | Desenho | Fronteira C1↔C3 (perguntas da ficha vs. plataforma de entrada) |
| 19 | 2026-06-10 | Build | Telas Kanban + Planilha no ar (uma fonte → três vistas) |
| 20 | 2026-06-10 | Planejamento | Virada protótipo → produto: planejamento da Camada 5 |
| 21 | 2026-06-10 | Build | Ficha própria do GMA + ngrok + portão por papel (câmera só-ficha) + QR |
| 22 | 2026-06-12 | Planejamento | Consulta à C5: estimativa, configuração, ampliação de escopo, segurança |
| 23 | 2026-06-12 | Desenho | Nova Ficha v2 — duas caras, ordem tipo→nome, câmera pelo Leitor |
| 24 | 2026-06-14 | Desenho | Passo 2 do Matcher (botão de resolução de empate) |
| 25 | 2026-06-14 | Build | Passo 2 do Matcher implementado e testado |
| 26 | 2026-06-15 | Teste | Validação do Passo 2 com sistema inteiro no ar |
| 27 | 2026-06-15 | Build | Nova Ficha v2 — Fatias 1 e 2 (tabela profissionais + aba Flask) |
| 28 | 2026-06-15 | Build | Nova Ficha v2 — Fatia 3 + gestão de profissionais (ativar/desativar/excluir) |
| 29 | 2026-06-15 | Build | Nova Ficha v2 — Fatia 4 (câmera no cadastro do profissional) |
| 30 | 2026-06-15 | Build | Nova Ficha v2 — Fatia 5 (multi-tipo booleanos + 2º nome) — **FECHA a Nova Ficha v2** |

---

## Sessões 1–4 — Primeiros testes e fundação

### Sessão 1 (2026-06-06) — 1º teste com cartão real
Pipeline funcionou ponta a ponta: GoPro, 106 arquivos / 7,7 GB. Bugs encontrados:
1. Processos zumbis (transferencia.py faltava no encerrar_gma.py)
2. Detecção GoPro errada ("Genérica/Canon" disparava antes)
3. copiador.py marcava falha por 3 arquivos de sistema (copy2 falhava)
4. Terminologia: adotado match/matched no lugar de casado/casamento

### Sessão 2 (2026-06-06) — Correção dos bugs
1. Terminologia match/matched aplicada em 5 arquivos
2. Processos zumbis: transferencia.py adicionado ao encerrar; inicializar detecta duplicatas
3. Fallback copy2 → copyfile para arquivos de sistema da câmera
4. Detecção GoPro: "Pass 0" verifica arquivos na raiz antes das pastas

### Sessão 3 (2026-06-06) — Política de integridade
1. Política mídia vs. sistema: falha em arquivo de sistema = AVISO; footage = CRÍTICO
2. PDF: falhas não-críticas como AVISO (âmbar), não FALHO (vermelho)
3. transferencia.py religado ao copiador.py (antes ainda importava integrador_spp)
4. Teste de regressão: 5 casos passando

### Sessão 4 (2026-06-07) — Contador + redefinição de escopo
1. Contador por profissional: `contadores/<NOME>.json` (substitui contagem frágil de pastas)
2. Campo `produtora` → `nome` em todo o transferencia.py
3. Estrutura de pasta confirmada: `EVENTO/DATA/TIPO/NOME/NOME_NNN`
4. Redefinição: numeração → C2; C3 = controle/banco; multi-máquina → C5

---

## Sessões 5–9 — Banco, PDF e frames

### Sessão 5 (2026-06-07) — Integração SQLite
- SQLite integrado em flask, leitor, matcher e transferencia (paralelo com JSONs)
- 5 funções auxiliares em banco_dados.py: gravar_formulario, gravar_cartao, atualizar_cartao, gravar_match, gravar_arquivos_do_log
- IDs do banco salvos de volta nos JSONs como ponte entre processos

### Sessão 6 (2026-06-07) — Tally + ngrok
- Endpoint `POST /forms/tally` no Flask com verificação HMAC-SHA256 opcional
- `ngrok_gma.sh`: expõe Flask na porta 5050, imprime URL do webhook
- `.env.exemplo`, `.gitignore`

### Sessão 7 (2026-06-07) — Teste real + FigJam
- Organograma visual criado no FigJam
- Teste com GoPro: tripla verificação passou (CHECKSUM + CONTAGEM + TAMANHO OK)
- Bug identificado: banco gravou 0 arquivos (índice único bloqueando reinserção)
- Decisão: ejeção só após Camada 4 (não após transferencia_ok)

### Sessão 8 (2026-06-07) — PDF rico
- gma_relatorio_pdf.py v2: cabeçalho 3 colunas + folha de contato (thumbnails) + tabela de auditoria
- GoPro: usa .THM e .LRV como proxies para não reextrair do .MP4
- Bug no parser XML corrigido (`root.find("job") or ...` → `is not None`)
- PDF de 22 páginas gerado (106 arquivos, 62 mídia, 7,7 GB, GoPro HERO7 Black)

### Sessão 9 (2026-06-07) — extrator_frames.py
- Decisão: extrair frames é mecânico (fica no ciclo); *entender* o frame é IA (Camada 6)
- extrator_frames.py: 10 frames por vídeo (5%–95% uniforme); usa .LRV/.THM da GoPro; grava manifesto.json
- 62 mídias / 179 frames em ~17s no teste real
- Estilo Overview escolhido para o PDF (vs. Filmstrip)

---

## Sessões 10–13 — Consolidação e segurança

### Sessão 10 (2026-06-07) — Mapa Vivo
- Idealizador sinalizou sensação de estar perdido com o volume de decisões
- organograma_GMA.md reescrito como "Mapa Vivo" (prédio de 7 andares + fluxo + linha do tempo)
- Board Miro criado: https://miro.com/app/board/uXjVHI0rvt4=
- Combinado de método: antes de cada sessão — ler doc mestre, apontar riscos, propor objetivo do dia

### Sessão 11 (2026-06-08) — Scripts C3 e C4
- exportador_sheets.py: sincroniza banco → Google Sheets a cada 60s (offline-first)
- auditoria.py: polling a cada 10s por cartões transferencia_ok; pré-check (pasta + contagem + tamanho ±0,5%)
- inicializar_gma.py: sobe 6 processos (adicionados auditoria + sheets)

### Sessão 12 (2026-06-08) — Correção de prematuridade
C3 e C4 declaradas fechadas prematuramente. Buracos identificados:
- C3: planilha Google real nunca criada; Kanban não existia como código; formulário Tally nunca criado
- C4: teste de ciclo integrado nunca executado (só teste de componente)
Plano de sessões A–D criado para fechar os buracos.

### Sessão 13 (2026-06-08) — Fichas + Matcher seguro + Perfil
- 5 campos editoriais novos na ficha (modelo_camera, tipo_conteudo, local_cena, prioridade, observacoes)
- banco_dados.py: migração não-destrutiva das 5 colunas; exportador_sheets.py: 21 colunas
- Decisão de design da ficha: câmera/modelo saem (sistema detecta); NOME é a chave de aprendizado
- **Matcher reescrito (Passo 1):** pontuação câmera+3/data+2/tipo+1/nome+2; margem de segurança = 1; `aguardando_confirmacao` em empate
- **Perfil Fase 1 (aprender):** tabela `perfis` + `atualizar_perfil`; 4 ingredientes: marca/modelo/prefixo/faixa de numeração
- guia_tally_gma.md criado
- **Regra de ouro da numeração:** gaps entre cartões são normais (câmera não reseta); a numeração só ADICIONA confiança, nunca pune

---

## Sessões 14–17 — Camada 4 e identidade do cartão

### Sessão 14 (2026-06-08) — Agente C4
- Subagente auditoria-gma criado em .claude/agents/auditoria-gma.md
- CLAUDE.md atualizado com lista de subagentes

### Sessão 15 (2026-06-09) — CLI do Parashoot descoberto
- Parashoot TEM CLI completo: `parashoot check` e `parashoot erase --machine-readable`
- fake-format é REVERSÍVEL (inverte 2 MB do MBR; footage intacto)
- auditoria.py reescrito: fluxo totalmente automático (sem confirmação do operador no caminho feliz)
- Bug: JSON de erro sai no stderr (não stdout) — parser ajustado

### Sessão 16 (2026-06-09) — Teste de ciclo COMPLETO (cartão Sony "Joe")
- Sony FX3, 57 arquivos / 1,6 GB, 17 clipes MP4 joe0258–joe0274
- Ciclo completo: Porteiro → Leitor (alerta multi-dia correto) → Match → Transferência → extrator_frames → C4 (check → erase → cartão embaralhado e ejetado de fato ✅)
- Bug real: parser do Parashoot fazia `json.loads` do texto inteiro → quebrava no erase multi-linha → reescrito para NDJSON
- **Formato JSON Lines (NDJSON) validado:** `check_complete` / `erase_start` + `erase_complete` / `error` no stderr
- Restore validado pela GUI do Parashoot (footage intacto após embaralhamento)

### Sessão 17 (2026-06-10) — Identidade do cartão em camadas
- Decisão: Matcher = AUTORIDADE ÚNICA da identidade do cartão
- Identidade em 4 camadas: nº de série > modelo+lente+prefixo+faixa > código na ficha/prefixo custom > operador
- Placeholder `4294967295` (0xFFFFFFFF) e `0` = IGNORAR (seria pior que o bug do "Untitled")
- Sony FX3 (Joe): serial mascarado; Nikon Z6_3 (Cadu): serial real `3003572` + Shutter Count

---

## Sessões 18–22 — Interface e planejamento da plataforma

### Sessão 18 (2026-06-10) — Fronteira C1↔C3
- Debate entre agentes checkin-gma e banco-dados-gma sobre quem "cria" a ficha
- Régua: perguntas da ficha = C1; plataforma + cano de entrada (Tally/Forms) = C3
- Rótulos agnósticos: núcleo fixo em colunas + gaveta `campos_extras` (JSON)
- Tabela `match_candidatos` desenhada (1 linha por candidato, status pendente/escolhido/descartado)
- Aprovado, NÃO implementado. Memória: `fronteira-c1-c3-fichas`

### Sessão 19 (2026-06-10) — Telas Kanban + Planilha
- Barra de abas ligando Operação / Acompanhamento (Kanban) / Planilha de Entrega
- /kanban: 5 colunas (Detectado → Match → Copiando → Verificado → Concluído); auto-refresh 8s
- Post-it por cartão: coluna `observacoes` já existia (zero mudança de schema)
- /planilha: JOIN cartoes + matches + formularios; 9 colunas; filtro client-side
- Painel de Operação ainda lê filas JSON (decisão consciente — não mexer no que funciona)

### Sessão 20 (2026-06-10) — Planejamento da Camada 5
- Stack: Flask + pywebview + py2app + configuração externa + supervisor de processos
- Roteiro em 5 fases: 0 Fundação · 1 Migração · 2 Robustez · 3 Empacotamento · 4 Multi-máquina
- Agente plataforma-gma + plano_camada5_GMA.md criados
- Laboratório (GMA/) intocado; produto nascerá em pasta nova (GMA-TESTE)

### Sessão 21 (2026-06-10) — Ficha própria + ngrok + portão por papel
- Canal decisão: ficha Flask = canal PRINCIPAL; Tally = reserva opcional
- GET/POST /ficha: formulário no padrão visual + aba "Nova Ficha"
- Gabarito seletável: datalists alimentados por valores distintos no banco
- Edição de fichas: trava de segurança — campos críticos travados se ficha já casou
- Portão por papel: acesso remoto só alcança /ficha; tudo mais → 403
- QR code: detecta URL ativa do ngrok automaticamente (API local 4040)
- Cartão SEM MÍDIA: dois níveis — `sem_midia` (config/trivial) e `revisar` (arquivos grandes não reconhecidos)
- Commit 06de4a0 (sistema versionado pela primeira vez); README próprio do GMA escrito

### Sessão 22 (2026-06-12) — Consulta à Camada 5
- Estimativa: ~13–24 sessões e ~2,2M–4,5M tokens total (5 fases)
- Configuração externa: `evento.toml` + `.env` (sem tocar no código para novo trabalho)
- C5 também dona das janelas (pywebview) + SSE (tempo real) + 2º monitor + despacho para C6
- Segurança: proteção honesta (licença por máquina + separação cérebro/dados; não há inviolável em Python)
- Perfis de profissionais ZERAM a cada evento (decisão do idealizador)

---

## Sessões 23–26 — Nova Ficha v2 (desenho e Passo 2 do Matcher)

### Sessão 23 (2026-06-12) — Desenho da Nova Ficha v2
- Duas caras da ficha (mesma rota /ficha): cara CÂMERA (remoto) vs. cara OPERADOR (base)
- NOME: dropdown fechado (câmera não digita); operador cria/edita
- CÂMERA/MODELO: sai da ficha → detectada pelo Leitor; só pergunta se Leitor não detectar
- TIPO: multi-seleção (Áudio/Foto/Vídeo)
- Ordem: 1º tipo, depois nome. Foto/Vídeo + Áudio → 2 dropdowns
- Encoding fechado: conjunto fixo (A/F/V) = colunas booleanas; lista aberta = JSON com `·`
- Referência: desenho_nova_ficha_v2_GMA.md (plano de fatias §11)

### Sessão 24 (2026-06-14) — Desenho do Passo 2 do Matcher
- Para cada cartão ambíguo: bloco com cabeçalho + candidatos + prefixos de arquivo como pista
- Fluxo de 2 passos: "Confirmar JOAO" → tela de resumo (destino previsto JOAO_002) → "Iniciar"
- Candidatos descartados: ficam na tabela com status `descartado` (auditável)
- Aprovado, NÃO implementado. Referência: desenho_passo2_matcher_GMA.md

### Sessão 25 (2026-06-14) — Passo 2 do Matcher implementado
- Pedra no caminho: `match_candidatos` não existia (sessão 18 foi só desenho) — criada na hora
- banco_dados.py: `registrar_candidatos` (idempotente) + `confirmar_match` (atômica)
- matcher.py: persiste candidatos + `confirmar_par_manual` espelha caminho automático
- flask_gma.py: blocos por cartão + pista dos prefixos + rotas `/match/<id>/confirmar` e `/match/<id>/iniciar`
- 2 bugs pegos só no teste ponta a ponta (não pelos autotestes isolados):
  - Variável `html` sombreava módulo `html` da stdlib → renomeada
  - Sentinela `materiais_ambiguos_marcados` já preenchida → criada sentinela própria `materiais_candidatos_persistidos`
- 21 verificações OK. Laboratório limpo.

### Sessão 26 (2026-06-15) — Validação do Passo 2
- Teste com sistema inteiro no ar (Matcher real + Flask real)
- Empate real entre 2 fichas → Passo 2 resolve → match manual gravado, candidato descartado, cartão segue para C2
- Aprovado e testado. Próximo passo: Nova Ficha v2

---

## Sessões 27–30 — Nova Ficha v2 (build completo)

### Sessão 27 (2026-06-15) — Fatias 1 e 2
- banco_dados.py: tabela `profissionais` (nome UNIQUE, tem_foto/audio/video, letra UNIQUE, criado_em)
- `_proxima_letra`: base-26 estilo Excel (A…Z, AA…); atribuição imutável mesmo após exclusões
- flask_gma.py: rota GET/POST /profissionais + aba Profissionais
- 13 testes via test client Flask. JOAO de teste inserido e removido (banco voltou limpo)

### Sessão 28 (2026-06-15) — Fatia 3 + gestão de profissionais
- TIPO: caixinhas multi-seleção (Foto/Áudio/Vídeo)
- NOME: dropdown fechado filtrado pelo tipo marcado (JavaScript offline)
- Envio compatível com backend via campos hidden (multi-tipo grava de verdade na Fatia 5)
- Ativar/Desativar: coluna `ativo` em `profissionais` (soft-delete, letra não muda)
- Excluir: só se nome não aparece em nenhuma ficha (`formularios.nome`)
- Conceito: aba Profissionais é "fonte/origem de material" — pode ser pessoa, feed/sistema, etc.

### Sessão 29 (2026-06-15) — Fatia 4 (câmera no cadastro)
- banco_dados.py: coluna `camera TEXT` em `profissionais` (migração não-destrutiva)
- flask_gma.py: coluna Câmera na aba Profissionais com edição inline; campo câmera saiu da ficha
- matcher.py: busca câmera do cadastro pelo nome (`_camera_do_cadastro`); queda para câmera da ficha se sem cadastro
- **Bug corrigido:** `_proxima_letra` usava COUNT(*) → colisão com letras de excluídos → passou a usar MAIOR letra (robusto)
- Mensagem de erro distingue colisão de nome × de letra

### Sessão 30 (2026-06-15) — Fatia 5 (multi-tipo booleanos + 2º nome) — FECHA a Nova Ficha v2
- banco_dados.py: 4 colunas em `formularios` (`tem_foto`, `tem_audio`, `tem_video`, `nome_audio`) + `entrega_id`
- flask_gma.py: helpers `_derivar_tipos` e `_tipo_display`; `_processar_e_salvar_formulario` divide ficha mista em 2 fichas
- matcher.py: critério de tipo (+1) entende multi-tipo
- **REGRA DO IDEALIZADOR:** áudio é SEMPRE transferência à parte → ficha mista = 2 fichas com mesmo `entrega_id`
- **DECISÃO ADIADA:** foto+vídeo na estrutura de pastas → resolver com Camada 2
- Testado: Foto+Áudio (JOAO+MARINA) → 2 fichas; Foto+Vídeo → 1; só Áudio → 1

---

## Investigações técnicas de referência

### ShotPutPro (versão 2026.2.4) — sessão 2
**Tem:** relatório .sppo, checksums configuráveis, automação da fila, nomenclatura dinâmica, ejeção automática.
**Não tem:** CLI real, dicionário AppleScript, URL scheme, presets editáveis.
**Presets:** formato binário NSKeyedArchiver + Protocol Buffers em `~/Library/Preferences/com.imagineproducts.ShotPutPro.plist`.
**Conclusão:** não automatizável → copiador.py é o motor oficial.

### Parashoot CLI — sessão 15
**Caminho:** `/Applications/ParaShoot.app/Contents/MacOS/cli/parashoot`
**Comandos:** `check` · `erase` · `is-card` · `settings`
**Saída:** JSON Lines (NDJSON) — um objeto por linha
**Sucesso check:** `{"status":"check_complete",...}` (stdout)
**Sucesso erase:** `{"status":"erase_start",...}` → `{"status":"erase_complete",...}` (stdout)
**Erro:** `{"status":"error","error":"unknown_error",...}` (stderr)
**fake-format:** inverte 2 MB do MBR; reversível pelo próprio Parashoot

### Identidade de cartão por marca — sessão 17
- Sony FX3: serial mascarado (`4294967295` = 0xFFFFFFFF = placeholder). Usar modelo+lente+prefixo.
- Nikon Z6_3: serial real (`3003572`) + Shutter Count (nunca zera entre cartões). Identificação forte.
- Regra: ignorar `4294967295`, `0` ou vazio como serial (todas as câmeras do mesmo modelo colidiriam).
