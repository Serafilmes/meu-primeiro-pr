#!/usr/bin/env python3
"""
banco_dados.py
Camada 3 do GMA — Controle e segurança das informações.

Responsabilidade:
  - Criar e inicializar o banco de dados local gma.db (SQLite).
  - Definir o schema de todas as tabelas (nunca destrutivo — CREATE TABLE IF NOT EXISTS).
  - Fornecer a função obter_conexao() usada por todos os outros módulos.
  - Fornecer a função registrar_evento() como único ponto de escrita na tabela de auditoria.

Princípio de segurança:
  Este arquivo NUNCA apaga, move ou renomeia arquivos de mídia.
  O banco guarda apenas METADADOS — nunca conteúdo de mídia.
  Toda operação destrutiva no banco (DROP, DELETE em massa, migração que
  reescreve registros) exige confirmação explícita do orquestrador e backup
  do gma.db antes de executar.

Uso (inicializar o banco):
    python3 /Users/serafa/GMA/banco_dados.py

Pré-requisitos:
    Nenhuma dependência externa — usa apenas a biblioteca padrão do Python.
"""

import sqlite3
import os
import json
from datetime import datetime

# ── CONSTANTES ────────────────────────────────────────────────────────────────

# Raiz do projeto GMA
RAIZ_GMA = "/Users/serafa/GMA"

# Caminho do banco de dados local (fonte única de verdade)
CAMINHO_BANCO = os.path.join(RAIZ_GMA, "gma.db")


# ── CONEXÃO ───────────────────────────────────────────────────────────────────

def obter_conexao():
    """
    Retorna uma conexão com o banco de dados gma.db.

    Configurações aplicadas:
      - row_factory = sqlite3.Row: permite acessar colunas por nome (ex: linha["status"])
        em vez de só por índice numérico — muito mais legível no código.
      - PRAGMA journal_mode=WAL: modo Write-Ahead Logging, que permite múltiplos
        leitores simultâneos enquanto uma escrita está em andamento. Ideal para o
        GMA, onde vários processos (Porteiro, Leitor, Transferência, Flask) leem o
        banco ao mesmo tempo.
      - PRAGMA foreign_keys=ON: ativa a verificação de chaves estrangeiras (FK).
        Por padrão o SQLite as ignora — ligar garante que não haverá registros
        "órfãos" (ex: um arquivo sem cartão associado).

    Retorna um objeto sqlite3.Connection pronto para uso.
    """
    conexao = sqlite3.connect(CAMINHO_BANCO)

    # Acesso às colunas por nome em vez de índice
    conexao.row_factory = sqlite3.Row

    # Ativa WAL e chaves estrangeiras via PRAGMA
    conexao.execute("PRAGMA journal_mode=WAL;")
    conexao.execute("PRAGMA foreign_keys=ON;")

    return conexao


# ── INICIALIZAÇÃO DO BANCO ────────────────────────────────────────────────────

def inicializar_banco():
    """
    Cria o arquivo gma.db (se não existir) e todas as tabelas necessárias.

    Usa CREATE TABLE IF NOT EXISTS em todas as tabelas — ou seja, se o banco
    já existir com dados, esta função não apaga nem altera nada.
    É seguro chamar várias vezes.

    Tabelas criadas:
      - cartoes     : um registro por cartão físico de memória
      - formularios : um registro por check-in (formulário recebido)
      - matches     : vínculo entre um cartão e um formulário
      - arquivos    : um registro por arquivo copiado (tabela-chave dos relatórios)
      - eventos     : log append-only de auditoria (nunca apagar linhas)

    Retorna a conexão aberta (o chamador é responsável por fechar).
    """
    conn = obter_conexao()

    # Usamos um bloco "with conn" para que o CREATE TABLE seja atômico:
    # se qualquer tabela falhar, nenhuma é criada parcialmente.
    with conn:

        # ── Tabela: cartoes ───────────────────────────────────────────────────
        # Um registro por cartão físico de memória que entrou no sistema.
        # Substitui os JSONs da fila_material/ como fonte de verdade.
        #
        # Campos da Camada 1 (Porteiro + Leitor de Mídia):
        #   volume, caminho_origem, marca_camera, tipo_material,
        #   data_inicio, data_fim, alerta_multidia, dias_distintos
        #
        # Campos da Camada 2 (Transferência — escritos por transferencia.py):
        #   numero_cartao, status, destino_pasta,
        #   transferencia_timestamp_inicio, transferencia_timestamp_fim,
        #   total_arquivos_transferidos, total_falhos, tamanho_transferido_bytes,
        #   transferencia_relatorio_pdf
        conn.execute("""
            CREATE TABLE IF NOT EXISTS cartoes (
                -- Identificador único gerado automaticamente pelo banco
                id                              INTEGER PRIMARY KEY AUTOINCREMENT,

                -- ── Campos da Camada 1 (detectados pelo Porteiro/Leitor) ──────
                -- Nome do volume montado (ex: "Untitled", "SD_CARD_01")
                volume                          TEXT NOT NULL,

                -- Caminho completo do volume (ex: "/Volumes/Untitled")
                caminho_origem                  TEXT NOT NULL,

                -- Marca da câmera detectada pelo Leitor (ex: "GoPro", "Sony")
                marca_camera                    TEXT,

                -- Tipo predominante de material (ex: "VIDEO", "FOTO", "AUDIO")
                tipo_material                   TEXT,

                -- Data do arquivo mais antigo encontrado no cartão (ISO-8601)
                data_inicio                     TEXT,

                -- Data do arquivo mais recente encontrado no cartão (ISO-8601)
                data_fim                        TEXT,

                -- 1 se o cartão tem arquivos de dias diferentes (não formatado), 0 caso contrário
                alerta_multidia                 INTEGER NOT NULL DEFAULT 0,

                -- Quantidade de dias distintos encontrados (ex: 4 = cartão de 4 dias)
                dias_distintos                  INTEGER NOT NULL DEFAULT 1,

                -- Total de arquivos encontrados no cartão (contagem do Leitor)
                total_arquivos_detectados       INTEGER,

                -- Tamanho total em bytes (estimativa do Leitor antes da cópia)
                tamanho_total_bytes_detectado   INTEGER,

                -- ── Status do ciclo de vida ────────────────────────────────
                -- Valores possíveis (ciclo de vida do cartão):
                --   detectado        : Porteiro encontrou o cartão, Leitor ainda não analisou
                --   aguardando_match : Leitor analisou, aguarda formulário do Forms
                --   matched          : Leitor + Matcher confirmaram o par cartão+formulário
                --   copiando         : Camada 2 iniciou a cópia
                --   transferencia_ok : cópia concluída, todos os checksums MD5 OK (Camada 2)
                --   transferencia_falhou : cópia concluída com falha de checksum crítico
                --   concluido        : Camada 4 confirmou estrutura (contagem + tamanho) e
                --                     acionou o Parashoot — cartão liberado para reutilização
                --
                -- Nota: "concluido" encerra o processo de logagem. O status
                -- reflete o processo, não o estado físico do cartão.
                status                          TEXT NOT NULL DEFAULT 'detectado',

                -- ── Campos da Camada 2 (escritos por transferencia.py) ────────
                -- Número sequencial do cartão: "JOAO_003" (gerado pelo contador)
                numero_cartao                   TEXT,

                -- Caminho completo da pasta de destino criada no storage
                destino_pasta                   TEXT,

                -- Timestamp de início da cópia (ISO-8601)
                transferencia_timestamp_inicio  TEXT,

                -- Timestamp de fim da cópia (ISO-8601)
                transferencia_timestamp_fim     TEXT,

                -- Quantidade de arquivos efetivamente copiados e verificados
                total_arquivos_transferidos     INTEGER,

                -- Quantidade de arquivos com falha de checksum crítico
                total_falhos                    INTEGER,

                -- Avisos (arquivos de sistema não verificados — não zera a transferência)
                total_avisos                    INTEGER,

                -- Tamanho total efetivamente copiado em bytes
                tamanho_transferido_bytes       INTEGER,

                -- Caminho do arquivo PDF de relatório gerado pela Camada 2
                transferencia_relatorio_pdf     TEXT,

                -- ── Observações livres do operador ─────────────────────────
                -- Campo de texto livre para notas do operador no painel
                -- (ex: "veio com 2 dias", "produtora pediu prioridade")
                observacoes                     TEXT,

                -- ── Timestamps de controle ──────────────────────────────────
                -- Criado: quando o registro entrou no banco
                criado_em                       TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),

                -- Atualizado: última vez que qualquer campo foi modificado
                atualizado_em                   TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
            );
        """)

        # ── Tabela: formularios ───────────────────────────────────────────────
        # Um registro por check-in recebido via Google Forms / webhook.
        # Substitui os JSONs da fila_forms/ como fonte de verdade.
        #
        # Campo chave: "nome" = profissional de captação (fotógrafo, videomaker...).
        # NÃO é o nome da produtora — o GMA roda para uma produtora por instância;
        # o que varia é o profissional. Decisão documentada em 2026-06-07.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS formularios (
                -- Identificador único gerado automaticamente pelo banco
                id              INTEGER PRIMARY KEY AUTOINCREMENT,

                -- ID original do formulário (vem do nome do arquivo JSON, ex: "20260606_164602_x0b3iy")
                -- Útil para rastrear a origem e evitar reimportações duplicadas
                id_form_original TEXT UNIQUE,

                -- Nome do profissional de captação (ex: "JOAO", "PAULO")
                -- Campo normalizado: maiúsculas, sem espaços extras
                nome            TEXT NOT NULL,

                -- Câmera usada (ex: "GoPro", "Sony FX6", "Canon R5")
                camera          TEXT,

                -- Tipo de material gravado. Texto canônico interno unindo os tipos
                -- marcados (ex: "VIDEO", "FOTO+VIDEO"). Mantido para compatibilidade
                -- e exibição; a verdade estruturada são os booleanos abaixo.
                tipo_material   TEXT,

                -- Multi-seleção de tipo (Nova Ficha v2, §7): conjunto fixo pequeno =
                -- colunas booleanas. Facilitam contar na planilha e ajudam o Matcher.
                tem_foto        INTEGER NOT NULL DEFAULT 0,
                tem_audio       INTEGER NOT NULL DEFAULT 0,
                tem_video       INTEGER NOT NULL DEFAULT 0,

                -- Segundo nome: o operador de áudio, quando a entrega tem áudio junto
                -- de foto/vídeo (o áudio quase sempre é outra pessoa). NULL se não houver.
                -- Informativo: o áudio vira uma ficha PRÓPRIA (ver entrega_id abaixo).
                nome_audio      TEXT,

                -- Liga fichas que vieram de um mesmo check-in misto. O áudio é sempre
                -- transferência à parte (cartão/match/linha próprios), então uma ficha
                -- "foto/vídeo + áudio" é gravada como DUAS fichas com o mesmo entrega_id.
                -- NULL quando a ficha não faz parte de uma entrega dividida.
                entrega_id      TEXT,

                -- Data de gravação informada pelo profissional (formato AAAA-MM-DD)
                data_gravacao   TEXT,

                -- Nome do operador que preencheu o formulário
                operador        TEXT,

                -- ── Campos adicionais do check-in (Tally — Sessão A) ─────────
                -- Modelo específico da câmera (ex: "HERO11", "Sony FX6")
                modelo_camera   TEXT,

                -- Classificação editorial do material (ex: "B-ROLL", "ENTREVISTA")
                tipo_conteudo   TEXT,

                -- Local ou cena onde o material foi gravado (ex: "Backstage")
                local_cena      TEXT,

                -- Nível de urgência do cartão (ex: "NORMAL", "URGENTE")
                prioridade      TEXT DEFAULT 'NORMAL',

                -- Observações livres do profissional ao fazer o check-in
                observacoes     TEXT,

                -- Status do formulário no ciclo de match
                -- Valores: aguardando_match, matched, orfao
                status          TEXT NOT NULL DEFAULT 'aguardando_match',

                -- Timestamp de quando o formulário foi recebido pelo Flask
                recebido_em     TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
            );
        """)

        # ── Tabela: matches ───────────────────────────────────────────────────
        # Registra o vínculo entre um cartão e um formulário.
        # O Matcher (Camada 1) é quem cria esses registros.
        #
        # Um cartão tem exatamente um formulário associado (e vice-versa).
        # O score indica a confiança do match (sistema de pontuação do Matcher).
        conn.execute("""
            CREATE TABLE IF NOT EXISTS matches (
                -- Identificador único gerado automaticamente
                id              INTEGER PRIMARY KEY AUTOINCREMENT,

                -- FK para o cartão associado
                cartao_id       INTEGER NOT NULL REFERENCES cartoes(id),

                -- FK para o formulário associado
                formulario_id   INTEGER NOT NULL REFERENCES formularios(id),

                -- Pontuação calculada pelo Matcher (ex: 5 = câmera+3, data+2)
                score           INTEGER NOT NULL DEFAULT 0,

                -- JSON com os critérios que contribuíram para o score
                -- Ex: '{"camera": 3, "data": 2}'
                criterios       TEXT,

                -- 1 se o match foi confirmado automaticamente (score >= 3)
                -- 0 se está pendente de confirmação manual
                confirmado      INTEGER NOT NULL DEFAULT 0,

                -- Timestamp de quando o match foi realizado
                match_timestamp TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),

                -- Garante que um cartão só pode estar em um match ativo
                UNIQUE(cartao_id),
                -- Garante que um formulário só pode estar em um match ativo
                UNIQUE(formulario_id)
            );
        """)

        # ── Tabela: arquivos ──────────────────────────────────────────────────
        # A TABELA-CHAVE do sistema: um registro por arquivo copiado.
        #
        # Esta tabela é o JOIN das duas especialidades:
        #   - Camada 1 (Leitor de Mídia via ffprobe/exiftool) → campos de mídia
        #   - Camada 2 (copiador.py) → campos de integridade
        #
        # É o que alimenta as 3 telas (Acessos 1–3) e os 3 relatórios
        # (TXT/CSV/PDF), conforme spec §12 do arquitetura_GMA.md.
        #
        # Os campos de mídia (codec, resolucao, etc.) podem ficar NULL até que
        # a Camada 1 enriqueça o arquivo com ffprobe/exiftool — isso acontece
        # depois da cópia, sobre o arquivo já verificado no destino.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS arquivos (
                -- Identificador único gerado automaticamente
                id                      INTEGER PRIMARY KEY AUTOINCREMENT,

                -- FK para o cartão ao qual este arquivo pertence
                cartao_id               INTEGER NOT NULL REFERENCES cartoes(id),

                -- ── Identificação do arquivo ──────────────────────────────
                -- Nome do arquivo sem o caminho (ex: "GOPR0001.MP4")
                nome_arquivo            TEXT NOT NULL,

                -- Caminho completo na origem (no cartão)
                caminho_origem          TEXT NOT NULL,

                -- Caminho completo no destino (no storage já copiado)
                caminho_destino         TEXT,

                -- ── Campos de integridade (Camada 2 — copiador.py) ────────
                -- Tamanho em bytes (medido na origem antes da cópia)
                tamanho_bytes           INTEGER,

                -- Hash MD5 calculado no arquivo de ORIGEM
                checksum_md5_origem     TEXT,

                -- Hash MD5 calculado no arquivo de DESTINO (após a cópia)
                checksum_md5_destino    TEXT,

                -- 1 se os dois MD5s batem (cópia íntegra), 0 se houver divergência
                verificado              INTEGER NOT NULL DEFAULT 0,

                -- 1 se for arquivo de sistema da câmera (ex: .url, .log da GoPro)
                -- Falha em arquivo de sistema = AVISO (não zera a transferência)
                -- Falha em arquivo crítico (footage) = FALHA CRÍTICA
                eh_arquivo_sistema      INTEGER NOT NULL DEFAULT 0,

                -- Status da cópia deste arquivo:
                --   ok             : copiado e verificado com sucesso
                --   aviso          : arquivo de sistema não verificado (não-crítico)
                --   falha_critica  : footage com falha de checksum ou cópia
                status_copia            TEXT NOT NULL DEFAULT 'ok',

                -- Mensagem de erro, se houver (NULL se tudo correu bem)
                erro_detalhe            TEXT,

                -- ── Campos de mídia (Camada 1 — ffprobe/exiftool) ──────────
                -- Todos podem ser NULL enquanto o Leitor não enriquecer o registro.
                -- O Leitor preenche esses campos lendo o arquivo NO DESTINO
                -- (depois de verificado), para não competir com a cópia.

                -- Codec de vídeo (ex: "hevc", "h264", "prores")
                codec                   TEXT,

                -- Resolução em formato "LARGURAxALTURA" (ex: "3840x2160")
                resolucao               TEXT,

                -- Duração do clipe em segundos (ex: 25.71)
                duracao_segundos        REAL,

                -- Frames por segundo (ex: 23.976, 29.97, 60.0)
                fps                     REAL,

                -- Total de frames do clipe (ex: 615)
                total_frames            INTEGER,

                -- Timecode de início (ex: "00:00:00:00")
                timecode                TEXT,

                -- Codec de áudio (ex: "aac", "pcm_s24le")
                audio_codec             TEXT,

                -- Bitrate de áudio em kbps (ex: 128, 320)
                audio_bitrate           INTEGER,

                -- Sample rate de áudio em Hz (ex: 48000, 44100)
                audio_sample_rate       INTEGER,

                -- Número de canais de áudio (ex: 1 = mono, 2 = estéreo, 6 = 5.1)
                audio_canais            INTEGER,

                -- Modelo da câmera retornado pelo exiftool/ffprobe
                -- (ex: "GoPro HERO7 Black", "Canon EOS R5")
                modelo_camera           TEXT,

                -- Caminho do thumbnail/frame extraído para o PDF (no storage)
                caminho_thumbnail       TEXT,

                -- ── Timestamp de controle ──────────────────────────────────
                -- Criado: quando o registro foi inserido no banco
                criado_em               TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
            );
        """)

        # ── Índice único na tabela arquivos ──────────────────────────────────
        # Garante que o par (cartao_id + caminho_origem) nunca seja duplicado.
        # Isso permite usar INSERT OR IGNORE para idempotência em gravar_arquivos_do_log().
        # CREATE UNIQUE INDEX IF NOT EXISTS é seguro em bancos já existentes —
        # não apaga dados, apenas cria o índice se ainda não existir.
        conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_arquivos_cartao_caminho
            ON arquivos (cartao_id, caminho_origem);
        """)

        # ── Tabela: eventos ───────────────────────────────────────────────────
        # Log de auditoria APPEND-ONLY.
        # NUNCA edite ou apague linhas desta tabela — só acrescente.
        # É o registro permanente de tudo que aconteceu no sistema.
        #
        # Exemplos de tipo de evento:
        #   cartao_detectado, cartao_analisado, match_confirmado,
        #   copia_iniciada, copia_concluida, copia_falhou,
        #   formulario_recebido, cartao_ejetado, erro_sistema
        conn.execute("""
            CREATE TABLE IF NOT EXISTS eventos (
                -- Identificador único — cresce sempre, nunca é reutilizado
                id              INTEGER PRIMARY KEY AUTOINCREMENT,

                -- Tipo do evento (ver exemplos no comentário acima)
                tipo            TEXT NOT NULL,

                -- FK para o cartão relacionado (NULL se o evento não é sobre um cartão)
                cartao_id       INTEGER REFERENCES cartoes(id),

                -- FK para o formulário relacionado (NULL se não se aplica)
                formulario_id   INTEGER REFERENCES formularios(id),

                -- Descrição legível do evento (para o operador entender no painel)
                descricao       TEXT NOT NULL,

                -- Detalhes extras em formato JSON (livre — para depuração e auditoria)
                -- Ex: '{"score": 5, "criterios": {"camera": 3, "data": 2}}'
                dados_json      TEXT,

                -- Timestamp de quando o evento ocorreu (sempre gravado, nunca editado)
                criado_em       TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
            );
        """)

        # ── Tabela: match_candidatos ──────────────────────────────────────────
        # Lista de candidatos em empate para um cartão específico.
        #
        # Criada quando o Matcher detecta dois ou mais formulários igualmente
        # pontuados para o mesmo cartão. Cada linha representa um candidato.
        # O operador resolve o empate pelo painel (botão "Confirmar [NOME]"),
        # e a função confirmar_match() marca um como 'escolhido' e os demais
        # como 'descartado'.
        #
        # IMPORTANTE: ao contrário de 'matches', NÃO há UNIQUE(cartao_id) —
        # um cartão em empate PRECISA ter várias linhas aqui (uma por candidato).
        # A unicidade é só no par (cartao_id, formulario_id): a mesma ficha
        # não aparece duas vezes para o mesmo cartão.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS match_candidatos (
                -- Identificador único gerado automaticamente pelo banco
                id              INTEGER PRIMARY KEY AUTOINCREMENT,

                -- FK para o cartão que está em estado de empate
                cartao_id       INTEGER NOT NULL REFERENCES cartoes(id),

                -- FK para o formulário candidato a ser associado ao cartão
                formulario_id   INTEGER NOT NULL REFERENCES formularios(id),

                -- Nome do profissional (denormalizado para o painel exibir sem JOIN)
                -- Ex: "JOAO", "PAULO"
                nome            TEXT NOT NULL,

                -- Câmera declarada na ficha deste candidato
                -- Ex: "Sony FX3", "GoPro"
                camera_ficha    TEXT,

                -- Pontuação deste candidato no empate (calculada pelo Matcher)
                score           INTEGER NOT NULL DEFAULT 0,

                -- JSON com os critérios que contribuíram para o score
                -- Ex: '["câmera:+3", "data:+2"]'
                criterios       TEXT,

                -- Estado deste candidato no processo de resolução:
                --   pendente   : aguardando escolha do operador (estado inicial)
                --   escolhido  : operador selecionou este candidato
                --   descartado : operador escolheu outro; esta ficha volta para fila
                status          TEXT NOT NULL DEFAULT 'pendente',

                -- Timestamp de quando este candidato foi registrado
                criado_em       TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),

                -- Unicidade: um par cartão+formulário aparece UMA vez na tabela.
                -- Não há UNIQUE(cartao_id) sozinho — um cartão TEM múltiplos candidatos.
                UNIQUE(cartao_id, formulario_id)
            );
        """)

        # ── Tabela: perfis ────────────────────────────────────────────────────
        # Perfil acumulado de cada profissional de captação.
        #
        # A cada match confirmado (cartão ↔ profissional), a função
        # atualizar_perfil() acumula aqui os dados do cartão. Com o tempo
        # este histórico forma uma "assinatura" do profissional — câmeras que
        # ele usa, prefixos de arquivo, faixas de numeração — que na Fase 2
        # ajudará a desempatar matches ambíguos sem chamar o operador.
        #
        # Todos os campos JSON são acumulativos: nunca sobrescritos, sempre somados.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS perfis (
                -- Identificador único gerado automaticamente pelo banco
                id              INTEGER PRIMARY KEY AUTOINCREMENT,

                -- Nome do profissional de captação — chave única do perfil
                -- (ex: "JOAO", "PAULO") — normalizado em maiúsculas
                nome            TEXT NOT NULL UNIQUE,

                -- JSON: contagem de cada marca de câmera vista
                -- Ex: {"GoPro": 5, "Sony": 1}
                cameras_vistas  TEXT,

                -- JSON: contagem de cada modelo de câmera visto
                -- Ex: {"GoPro HERO7 Black": 5, "Sony FX6": 1}
                modelos_vistos  TEXT,

                -- JSON: contagem de cada prefixo de arquivo visto
                -- Ex: {"GOPR": 5, "GX": 2}
                prefixos_vistos TEXT,

                -- Maior número de arquivo já visto neste perfil
                -- Usado para inferir continuidade: se o próximo cartão começa onde
                -- o anterior parou (ex: último foi 200, novo começa em 201),
                -- é provável que seja o mesmo profissional
                ultimo_num_max  INTEGER,

                -- JSON: lista de faixas [min, max] por cartão, em ordem de chegada
                -- Ex: [[1, 200], [201, 400]]
                -- Permite reconstruir o histórico completo de numeração
                faixas_vistas   TEXT,

                -- Quantidade total de cartões matched para este profissional
                total_cartoes   INTEGER NOT NULL DEFAULT 0,

                -- Timestamp do primeiro match registrado para este profissional
                primeiro_visto  TEXT,

                -- Timestamp do último match registrado para este profissional
                ultimo_visto    TEXT,

                -- Timestamp da última vez que este registro foi modificado
                atualizado_em   TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
            );
        """)

    # Migração incremental: garante que o banco existente tenha as novas colunas
    # de formularios (modelo_camera, tipo_conteudo, local_cena, prioridade, observacoes).
    # Bancos criados do zero já têm essas colunas no DDL acima; bancos antigos recebem
    # aqui via ALTER TABLE — sem perda de dados, seguro chamar quantas vezes quiser.
    migrar_schema_formularios(conn)

    # Migração incremental: cria a tabela match_candidatos se ainda não existir.
    # Bancos criados do zero também já recebem via o DDL abaixo nesta mesma função;
    # esta chamada explícita garante que bancos antigos sejam atualizados.
    migrar_schema_match_candidatos(conn)

    # Migração incremental: cria a tabela profissionais (Nova Ficha v2) se ainda
    # não existir. Guarda nome + tipos de material + letra sequencial imutável.
    migrar_schema_profissionais(conn)

    # Migração incremental: cria a tabela listas_contexto (Gestão de Listas) se
    # ainda não existir. Guarda as opções de classificação dinâmicas do evento
    # (palco, marca, pauta, serviço, tag) geridas pelo operador.
    migrar_schema_listas_contexto(conn)

    # Migração incremental: cria a tabela formularios_chips (a ponte chips→ficha)
    # se ainda não existir. Liga cada ficha aos itens de listas_contexto que o
    # profissional escolheu como classificação.
    migrar_schema_formularios_chips(conn)

    # Migração incremental: cria a tabela molde_planilha se ainda não existir.
    # Guarda quais colunas estão visíveis e quais colunas personalizadas o
    # operador criou para este evento. O catálogo de colunas padrão é sincronizado
    # pelo Flask (que é quem o define) via sincronizar_catalogo_molde().
    migrar_schema_molde_planilha(conn)

    # Migração incremental: cria a tabela grupos_classificacao e semeia os 5 grupos
    # padrão. Os grupos de classificação (palco/marca/pauta/servico/tag) deixam de
    # ser fixos no código e viram dados editáveis pelo operador (s33).
    migrar_schema_grupos_classificacao(conn)

    return conn


# ── REGISTRO DE EVENTOS ───────────────────────────────────────────────────────

def registrar_evento(conn, tipo, descricao, cartao_id=None, formulario_id=None, dados=None):
    """
    Insere um novo evento na tabela de auditoria.

    Esta é a ÚNICA função que deve escrever na tabela 'eventos'.
    Centralizar os inserts aqui garante que a tabela permaneça append-only
    (nunca editada, nunca deletada) e que o formato seja consistente.

    Parâmetros:
      conn          — conexão SQLite aberta (de obter_conexao())
      tipo          — string identificando o tipo de evento
                      (ex: "cartao_detectado", "copia_iniciada")
      descricao     — texto legível descrevendo o que aconteceu
                      (ex: "Cartão GoPro detectado em /Volumes/Untitled")
      cartao_id     — ID do cartão relacionado (None se não se aplica)
      formulario_id — ID do formulário relacionado (None se não se aplica)
      dados         — dicionário Python com detalhes extras (será convertido para JSON)
                      None se não houver detalhes adicionais

    Retorna o ID do evento inserido.

    Exemplo de uso:
      registrar_evento(
          conn,
          tipo="cartao_detectado",
          descricao="Cartão GoPro detectado em /Volumes/Untitled",
          cartao_id=42,
          dados={"marca": "GoPro", "total_arquivos": 106}
      )
    """
    # Converte o dicionário de dados para texto JSON (ou None se não houver dados)
    dados_json = json.dumps(dados, ensure_ascii=False) if dados is not None else None

    timestamp_agora = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    cursor = conn.execute(
        """
        INSERT INTO eventos (tipo, cartao_id, formulario_id, descricao, dados_json, criado_em)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (tipo, cartao_id, formulario_id, descricao, dados_json, timestamp_agora)
    )

    conn.commit()

    return cursor.lastrowid


# ── FUNÇÕES AUXILIARES DE ESCRITA ────────────────────────────────────────────
#
# Estas funções são chamadas pelos módulos das Camadas 1 e 2 para gravar
# informações no banco. Todas seguem a regra de ouro:
#   - nunca apagam dados existentes
#   - são idempotentes (chamar duas vezes não duplica registros)
#   - qualquer falha deve ser capturada pelo chamador com try/except


def gravar_formulario(conn, id_form, nome, camera, tipo_material, data_gravacao, operador=None,
                      modelo_camera=None, tipo_conteudo=None, local_cena=None,
                      prioridade=None, observacoes=None,
                      tem_foto=0, tem_audio=0, tem_video=0, nome_audio=None,
                      entrega_id=None):
    """
    Insere um formulário de check-in na tabela 'formularios'.

    Usa INSERT OR IGNORE para garantir que o mesmo id_form não seja duplicado,
    mesmo que o Flask chame esta função duas vezes por algum motivo.

    Parâmetros:
      conn          — conexão SQLite aberta (de inicializar_banco() ou obter_conexao())
      id_form       — ID único do formulário gerado pelo Flask (ex: "20260606_164602_x0b3iy")
      nome          — nome do profissional de captação, já normalizado em maiúsculas
      camera        — câmera declarada no formulário (ex: "GoPro")
      tipo_material — tipo de material canônico (ex: "VIDEO", "FOTO+VIDEO")
      data_gravacao — data de gravação no formato "AAAA-MM-DD"
      operador      — nome do operador que preencheu o formulário (pode ser None)

      Campos novos (opcionais — vindos dos campos adicionais do Tally):
      modelo_camera — modelo específico da câmera (ex: "HERO11", "Sony FX6")
      tipo_conteudo — classificação editorial do material (ex: "B-ROLL", "ENTREVISTA")
      local_cena    — local ou cena de onde o material foi gravado (ex: "Backstage")
      prioridade    — nível de urgência do cartão (ex: "NORMAL", "URGENTE")
      observacoes   — observações livres do profissional ao fazer o check-in

      Nova Ficha v2 (Fatia 5):
      tem_foto/tem_audio/tem_video — multi-seleção de tipo como booleanos (0/1)
      nome_audio    — segundo nome (operador de áudio), quando a entrega tem áudio

    Retorna o ID (rowid) do registro inserido ou o ID já existente se já havia no banco.
    """
    cursor = conn.execute(
        """
        INSERT OR IGNORE INTO formularios
            (id_form_original, nome, camera, tipo_material, data_gravacao, operador,
             modelo_camera, tipo_conteudo, local_cena, prioridade, observacoes,
             tem_foto, tem_audio, tem_video, nome_audio, entrega_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (id_form, nome, camera, tipo_material, data_gravacao, operador,
         modelo_camera, tipo_conteudo, local_cena, prioridade, observacoes,
         int(bool(tem_foto)), int(bool(tem_audio)), int(bool(tem_video)),
         (nome_audio or "").strip().upper() or None, entrega_id)
    )
    conn.commit()

    # Se o INSERT foi ignorado (id_form já existia), busca o ID existente
    if cursor.lastrowid == 0 or cursor.rowcount == 0:
        resultado = conn.execute(
            "SELECT id FROM formularios WHERE id_form_original = ?",
            (id_form,)
        ).fetchone()
        id_registro = resultado["id"] if resultado else None
    else:
        id_registro = cursor.lastrowid

    # Registra evento de auditoria (append-only)
    registrar_evento(
        conn,
        tipo="formulario_recebido",
        descricao=f"Formulário recebido | Nome: {nome} | Câmera: {camera}",
        formulario_id=id_registro,
        dados={"id_form": id_form, "nome": nome, "camera": camera, "tipo_material": tipo_material}
    )

    return id_registro


def migrar_schema_formularios(conn):
    """
    Adiciona as novas colunas à tabela 'formularios' em bancos já existentes.

    SQLite não suporta ALTER TABLE ADD COLUMN IF NOT EXISTS, então a lógica é:
      1. Consulta o PRAGMA table_info para listar as colunas atuais.
      2. Para cada coluna nova, adiciona somente se ainda não existir.

    Seguro para chamar várias vezes — não duplica colunas nem altera dados.
    """
    # Lê a lista de colunas que já existem na tabela
    colunas_existentes = {row[1] for row in conn.execute("PRAGMA table_info(formularios)")}

    # Pares (nome_da_coluna, tipo_SQL) que precisam existir na tabela
    novos_campos = [
        ("modelo_camera", "TEXT"),
        ("tipo_conteudo",  "TEXT"),
        ("local_cena",     "TEXT"),
        ("prioridade",     "TEXT DEFAULT 'NORMAL'"),
        ("observacoes",    "TEXT"),
        # Nova Ficha v2, Fatia 5 — multi-tipo (booleanos) + segundo nome (áudio)
        ("tem_foto",       "INTEGER NOT NULL DEFAULT 0"),
        ("tem_audio",      "INTEGER NOT NULL DEFAULT 0"),
        ("tem_video",      "INTEGER NOT NULL DEFAULT 0"),
        ("nome_audio",     "TEXT"),
        # Liga as duas fichas de uma entrega mista (áudio = transferência à parte)
        ("entrega_id",     "TEXT"),
    ]

    for nome_col, tipo_col in novos_campos:
        if nome_col not in colunas_existentes:
            # ALTER TABLE é seguro: acrescenta a coluna sem tocar nos dados existentes
            conn.execute(f"ALTER TABLE formularios ADD COLUMN {nome_col} {tipo_col}")

    conn.commit()


def migrar_schema_match_candidatos(conn):
    """
    Cria a tabela 'match_candidatos' em bancos já existentes (se ainda não existir).

    Usa CREATE TABLE IF NOT EXISTS — completamente não-destrutivo.
    Seguro chamar várias vezes: se a tabela já existir, não faz nada.

    Bancos criados do zero já recebem a tabela via o DDL em inicializar_banco().
    Esta função existe para atualizar bancos antigos que ainda não têm a tabela
    (como o gma.db que existia antes desta sessão de build).
    """
    conn.execute("""
        CREATE TABLE IF NOT EXISTS match_candidatos (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            cartao_id       INTEGER NOT NULL REFERENCES cartoes(id),
            formulario_id   INTEGER NOT NULL REFERENCES formularios(id),
            nome            TEXT NOT NULL,
            camera_ficha    TEXT,
            score           INTEGER NOT NULL DEFAULT 0,
            criterios       TEXT,
            status          TEXT NOT NULL DEFAULT 'pendente',
            criado_em       TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            UNIQUE(cartao_id, formulario_id)
        );
    """)
    conn.commit()


def registrar_candidatos(conn, cartao_id, candidatos):
    """
    Persiste os candidatos de um empate na tabela 'match_candidatos'.

    Chamada pelo Matcher (matcher.py) quando detecta dois ou mais formulários
    empatados para o mesmo cartão. Cada candidato vira uma linha com status
    'pendente', aguardando resolução manual pelo operador no painel.

    Parâmetros:
      conn       — conexão SQLite aberta
      cartao_id  — ID do cartão em estado de empate
      candidatos — lista de dicionários, um por candidato, com as chaves:
                     formulario_id  : ID do formulário candidato (int)
                     nome           : nome do profissional (ex: "JOAO")
                     camera_ficha   : câmera declarada na ficha (pode ser None)
                     score          : pontuação calculada pelo Matcher (int)
                     criterios      : lista de strings OU string JSON com os critérios
                                      (ex: ["câmera:+3", "data:+2"] ou já serializado)

    Comportamento:
      - Usa INSERT OR IGNORE no par único (cartao_id, formulario_id).
      - Idempotente: se o Matcher reprocessar o mesmo empate (ex: loop de polling),
        as linhas já existentes não são duplicadas nem sobrescritas.
        Isso preserva qualquer 'status' que já tenha sido atualizado (ex: 'escolhido').
      - Registra evento 'candidatos_registrados' no log de auditoria.

    Retorna o número de candidatos efetivamente inseridos (0 se todos já existiam).
    """
    inseridos = 0

    for candidato in candidatos:
        formulario_id = candidato["formulario_id"]
        nome          = candidato["nome"]
        camera_ficha  = candidato.get("camera_ficha")
        score         = candidato.get("score", 0)

        # Normaliza 'criterios': aceita lista de strings ou string JSON
        criterios_raw = candidato.get("criterios")
        if isinstance(criterios_raw, list):
            # Lista de strings → serializa para JSON antes de guardar
            criterios_json = json.dumps(criterios_raw, ensure_ascii=False)
        elif isinstance(criterios_raw, str):
            # Já é string (JSON ou texto simples) — guarda como veio
            criterios_json = criterios_raw
        else:
            # None ou tipo inesperado → grava NULL
            criterios_json = None

        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO match_candidatos
                (cartao_id, formulario_id, nome, camera_ficha, score, criterios, status)
            VALUES (?, ?, ?, ?, ?, ?, 'pendente')
            """,
            (cartao_id, formulario_id, nome, camera_ficha, score, criterios_json)
        )

        if cursor.rowcount > 0:
            inseridos += 1

    conn.commit()

    # Registra evento de auditoria com o total de candidatos persistidos
    registrar_evento(
        conn,
        tipo="candidatos_registrados",
        descricao=(
            f"Candidatos de empate registrados | Cartão: {cartao_id} "
            f"| Total inseridos: {inseridos} | Total recebidos: {len(candidatos)}"
        ),
        cartao_id=cartao_id,
        dados={"total_inseridos": inseridos, "total_recebidos": len(candidatos)}
    )

    return inseridos


def confirmar_match(conn, cartao_id, nome_escolhido):
    """
    Resolve um empate: registra o match do candidato escolhido e descarta os demais.

    Esta função é chamada pelo Flask (flask_gma.py) quando o operador clica em
    "Iniciar transferência" na tela de confirmação do empate. Toda a operação é
    atômica — se qualquer passo falhar, NADA é gravado (rollback automático).

    Fluxo interno (numa única transação):
      1. Busca o candidato 'pendente' com o nome escolhido para este cartão.
      2. Registra o match na tabela 'matches' com confirmado=1 (manual).
      3. Marca o candidato escolhido como 'escolhido' em match_candidatos.
      4. Marca todos os demais candidatos 'pendentes' do cartão como 'descartado'.
      5. Atualiza o formulário escolhido → status 'matched'.
      6. Libera os formulários descartados → status 'aguardando_match'
         (ficam livres para casar com o próximo cartão do profissional).
      7. Registra evento 'match_confirmado_manual' no log de auditoria.

    Parâmetros:
      conn           — conexão SQLite aberta
      cartao_id      — ID do cartão que estava em empate
      nome_escolhido — nome do profissional escolhido pelo operador (ex: "JOAO")
                       deve corresponder exatamente ao campo 'nome' do candidato

    Retorna um dicionário com:
      {
        "formulario_id": <ID do formulário escolhido>,
        "nome":          <nome do profissional escolhido>,
        "descartados":   [<lista de formulario_ids descartados>]
      }

    Retorna None se não houver candidato 'pendente' com esse nome para o cartão
    (ex: empate já foi resolvido). Nenhum dado é gravado nesse caso.

    Levanta ValueError se encontrar mais de um candidato pendente com o mesmo nome
    (situação anômala — indica problema na inserção de candidatos).
    """
    # Usamos "with conn:" para garantir atomicidade:
    # se qualquer linha falhar, todas as alterações desta transação são revertidas.
    with conn:

        # ── Passo 1: localiza o candidato pendente com o nome escolhido ───────
        candidatos_pendentes = conn.execute(
            """
            SELECT id, formulario_id, score, criterios
            FROM match_candidatos
            WHERE cartao_id = ? AND nome = ? AND status = 'pendente'
            """,
            (cartao_id, nome_escolhido)
        ).fetchall()

        if not candidatos_pendentes:
            # Empate já resolvido ou nome não encontrado — não grava nada
            return None

        if len(candidatos_pendentes) > 1:
            # Situação anômala: nunca deveria acontecer com o UNIQUE(cartao_id, formulario_id)
            raise ValueError(
                f"Anomalia: {len(candidatos_pendentes)} candidatos pendentes com o nome "
                f"'{nome_escolhido}' para o cartão {cartao_id}. "
                f"Esperado: exatamente 1."
            )

        candidato_escolhido = candidatos_pendentes[0]
        formulario_id_escolhido = candidato_escolhido["formulario_id"]
        score_escolhido         = candidato_escolhido["score"]
        criterios_json          = candidato_escolhido["criterios"]

        # Converte o JSON de critérios de volta para lista (gravar_match espera lista)
        if criterios_json:
            try:
                criterios_lista = json.loads(criterios_json)
            except (json.JSONDecodeError, TypeError):
                # Se não for JSON válido, guarda como lista com o texto bruto
                criterios_lista = [criterios_json]
        else:
            criterios_lista = []

        # ── Passo 2: registra o match confirmado (confirmado=1 = escolha manual) ──
        # gravar_match também atualiza cartoes.status → 'matched' e grava evento.
        gravar_match(
            conn,
            cartao_id,
            formulario_id_escolhido,
            score_escolhido,
            criterios_lista,
            confirmado=1      # marca explicitamente como confirmação manual do operador
        )

        # ── Passo 3: marca o candidato escolhido como 'escolhido' ─────────────
        conn.execute(
            """
            UPDATE match_candidatos
            SET status = 'escolhido'
            WHERE cartao_id = ? AND formulario_id = ?
            """,
            (cartao_id, formulario_id_escolhido)
        )

        # ── Passo 4: descarta os demais candidatos pendentes do mesmo cartão ──
        # Busca os formulário_ids dos candidatos que serão descartados (para retornar)
        descartados_rows = conn.execute(
            """
            SELECT formulario_id
            FROM match_candidatos
            WHERE cartao_id = ? AND status = 'pendente'
            """,
            (cartao_id,)
        ).fetchall()

        ids_formularios_descartados = [row["formulario_id"] for row in descartados_rows]

        # Descarta todos os candidatos ainda pendentes (exceto o escolhido, já atualizado)
        conn.execute(
            """
            UPDATE match_candidatos
            SET status = 'descartado'
            WHERE cartao_id = ? AND status = 'pendente'
            """,
            (cartao_id,)
        )

        # ── Passo 5: libera os formulários descartados para o próximo match ───
        # Cada ficha descartada volta a 'aguardando_match', ficando disponível
        # para casar com o próximo cartão do mesmo profissional.
        # (O formulário escolhido já foi marcado 'matched' por gravar_match acima.)
        for fid in ids_formularios_descartados:
            conn.execute(
                "UPDATE formularios SET status = 'aguardando_match' WHERE id = ?",
                (fid,)
            )

        # ── Passo 6: registra evento de auditoria ─────────────────────────────
        registrar_evento(
            conn,
            tipo="match_confirmado_manual",
            descricao=(
                f"Empate resolvido manualmente | Cartão: {cartao_id} "
                f"| Escolhido: {nome_escolhido} (form {formulario_id_escolhido}) "
                f"| Descartados: {ids_formularios_descartados}"
            ),
            cartao_id=cartao_id,
            formulario_id=formulario_id_escolhido,
            dados={
                "nome_escolhido":          nome_escolhido,
                "formulario_id_escolhido": formulario_id_escolhido,
                "score":                   score_escolhido,
                "ids_descartados":         ids_formularios_descartados,
            }
        )

    # ── Passo 7: retorna o resultado para o chamador (Flask / Matcher) ────────
    return {
        "formulario_id": formulario_id_escolhido,
        "nome":          nome_escolhido,
        "descartados":   ids_formularios_descartados,
    }


def gravar_cartao(conn, volume, caminho_origem, marca_camera=None, tipo_material=None,
                  data_inicio=None, data_fim=None, alerta_multidia=False, dias_distintos=1,
                  total_arquivos=None, tamanho_bytes=None):
    """
    Insere um cartão físico de memória na tabela 'cartoes'.

    Usa o caminho_origem como chave de unicidade — se o mesmo cartão (mesmo caminho)
    já estiver no banco, retorna o ID existente sem criar duplicata.

    Parâmetros:
      conn           — conexão SQLite aberta
      volume         — nome do volume montado (ex: "Untitled", "SD_CARD_01")
      caminho_origem — caminho completo do volume (ex: "/Volumes/Untitled") — chave única
      marca_camera   — marca detectada pelo Leitor (ex: "GoPro", "Sony")
      tipo_material  — tipo predominante (ex: "VIDEO", "FOTO", "AUDIO")
      data_inicio    — data do arquivo mais antigo (ISO-8601)
      data_fim       — data do arquivo mais recente (ISO-8601)
      alerta_multidia — True se o cartão contém arquivos de mais de um dia
      dias_distintos — quantidade de dias distintos encontrados no cartão
      total_arquivos — total de arquivos encontrados (contagem do Leitor)
      tamanho_bytes  — tamanho total estimado em bytes

    Retorna o ID do registro inserido ou o ID já existente.
    """
    # Verifica se o cartão já está no banco pelo caminho de origem
    resultado_existente = conn.execute(
        "SELECT id FROM cartoes WHERE caminho_origem = ?",
        (caminho_origem,)
    ).fetchone()

    if resultado_existente:
        # Cartão já existe — retorna o ID sem duplicar
        return resultado_existente["id"]

    # Insere o novo cartão com status inicial 'aguardando_match'
    cursor = conn.execute(
        """
        INSERT INTO cartoes
            (volume, caminho_origem, marca_camera, tipo_material,
             data_inicio, data_fim, alerta_multidia, dias_distintos,
             total_arquivos_detectados, tamanho_total_bytes_detectado, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'aguardando_match')
        """,
        (
            volume, caminho_origem, marca_camera, tipo_material,
            data_inicio, data_fim,
            1 if alerta_multidia else 0,  # SQLite armazena booleano como 0/1
            dias_distintos,
            total_arquivos, tamanho_bytes
        )
    )
    conn.commit()

    id_cartao = cursor.lastrowid

    # Registra evento de auditoria
    registrar_evento(
        conn,
        tipo="cartao_analisado",
        descricao=f"Cartão analisado | Volume: {volume} | Câmera: {marca_camera}",
        cartao_id=id_cartao,
        dados={
            "volume": volume,
            "caminho_origem": caminho_origem,
            "marca_camera": marca_camera,
            "total_arquivos": total_arquivos,
            "alerta_multidia": alerta_multidia,
        }
    )

    return id_cartao


def atualizar_cartao(conn, cartao_id, campos):
    """
    Atualiza campos específicos de um cartão na tabela 'cartoes'.

    Parâmetros:
      conn      — conexão SQLite aberta
      cartao_id — ID do cartão a atualizar (número inteiro)
      campos    — dicionário com os campos a atualizar
                  Ex: {"status": "copiando", "destino_pasta": "/Volumes/..."}

    Atualiza 'atualizado_em' automaticamente com o timestamp atual.
    Registra evento usando o valor de 'status' no dicionário (se presente).

    Retorna True se atualizou com sucesso, False se o cartao_id não existia.
    """
    if not campos:
        return False

    # Adiciona o timestamp de atualização automaticamente
    timestamp_agora = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    campos_com_timestamp = dict(campos)
    campos_com_timestamp["atualizado_em"] = timestamp_agora

    # Monta a cláusula SET dinamicamente a partir das chaves do dicionário
    # Exemplo: "status = ?, destino_pasta = ?, atualizado_em = ?"
    colunas_sql = ", ".join(f"{coluna} = ?" for coluna in campos_com_timestamp)
    valores = list(campos_com_timestamp.values()) + [cartao_id]

    cursor = conn.execute(
        f"UPDATE cartoes SET {colunas_sql} WHERE id = ?",
        valores
    )
    conn.commit()

    # rowcount = 0 significa que nenhuma linha foi atualizada (ID não existe)
    if cursor.rowcount == 0:
        return False

    # Tipo do evento baseado no status novo (se o dicionário trouxer status)
    tipo_evento = f"status_{campos.get('status', 'atualizado')}"

    registrar_evento(
        conn,
        tipo=tipo_evento,
        descricao=f"Cartão atualizado | ID: {cartao_id} | Campos: {list(campos.keys())}",
        cartao_id=cartao_id,
        dados=campos
    )

    return True


def atualizar_formulario(conn, formulario_id, campos):
    """
    Atualiza campos editáveis de uma ficha (tabela 'formularios').

    Espelha 'atualizar_cartao': monta o UPDATE dinamicamente e registra um evento
    de auditoria. Só aceita colunas da LISTA BRANCA abaixo — nunca deixa mexer em
    id, id_form_original, recebido_em (chaves/rastreio).

    Parâmetros:
      conn          — conexão SQLite aberta
      formulario_id — ID da ficha a atualizar (inteiro)
      campos        — dicionário com os campos a atualizar

    Retorna True se atualizou, False se o ID não existia ou não havia campo válido.
    """
    COLUNAS_EDITAVEIS = {
        "nome", "camera", "tipo_material", "data_gravacao", "operador",
        "modelo_camera", "tipo_conteudo", "local_cena", "prioridade", "observacoes",
        # Nova Ficha v2, Fatia 5 — multi-tipo (booleanos) + segundo nome (áudio)
        "tem_foto", "tem_audio", "tem_video", "nome_audio",
    }
    # Filtra só o que é permitido editar (segurança: ignora qualquer campo estranho)
    campos_limpos = {c: v for c, v in (campos or {}).items() if c in COLUNAS_EDITAVEIS}
    if not campos_limpos:
        return False

    colunas_sql = ", ".join(f"{coluna} = ?" for coluna in campos_limpos)
    valores = list(campos_limpos.values()) + [formulario_id]

    cursor = conn.execute(
        f"UPDATE formularios SET {colunas_sql} WHERE id = ?",
        valores
    )
    conn.commit()

    if cursor.rowcount == 0:
        return False

    registrar_evento(
        conn,
        tipo="formulario_editado",
        descricao=f"Ficha editada | ID: {formulario_id} | Campos: {list(campos_limpos.keys())}",
        formulario_id=formulario_id,
        dados=campos_limpos
    )

    return True


def gravar_match(conn, cartao_id, formulario_id, score, criterios_lista, confirmado=None):
    """
    Registra o vínculo entre um cartão e um formulário na tabela 'matches'.

    Também atualiza o status do cartão para 'matched' e do formulário para 'matched'.
    Se já existir um match para este cartão (UNIQUE(cartao_id)), usa INSERT OR IGNORE.

    Parâmetros:
      conn            — conexão SQLite aberta
      cartao_id       — ID do cartão (FK para tabela 'cartoes')
      formulario_id   — ID do formulário (FK para tabela 'formularios')
      score           — pontuação calculada pelo Matcher (ex: 5)
      criterios_lista — lista de strings descrevendo os critérios
                        (ex: ["câmera:+3", "data:+2"])
      confirmado      — (opcional) 0 ou 1 para forçar o valor do campo 'confirmado'.
                        Se None (padrão), o valor é calculado automaticamente:
                        score >= 3 → confirmado=1 (regra do Matcher automático).
                        Passe confirmado=1 explicitamente ao registrar um match manual
                        escolhido pelo operador via botão de resolução de empate.

    Retorna o ID do match inserido.
    """
    # Converte a lista de critérios para JSON para armazenar na coluna TEXT
    criterios_json = json.dumps(criterios_lista, ensure_ascii=False)

    # Determina o valor de 'confirmado':
    #   - caminho automático (Matcher): score >= 3 = confirmado
    #   - caminho manual (operador): o chamador passa confirmado=1 explicitamente
    if confirmado is None:
        confirmado = 1 if score >= 3 else 0

    cursor = conn.execute(
        """
        INSERT OR IGNORE INTO matches
            (cartao_id, formulario_id, score, criterios, confirmado)
        VALUES (?, ?, ?, ?, ?)
        """,
        (cartao_id, formulario_id, score, criterios_json, confirmado)
    )
    conn.commit()

    id_match = cursor.lastrowid

    # Atualiza o status do cartão para 'matched'
    atualizar_cartao(conn, cartao_id, {"status": "matched"})

    # Atualiza o status do formulário para 'matched'
    conn.execute(
        "UPDATE formularios SET status = 'matched' WHERE id = ?",
        (formulario_id,)
    )
    conn.commit()

    # Registra evento de auditoria do match
    registrar_evento(
        conn,
        tipo="match_confirmado",
        descricao=f"Match confirmado | Cartão: {cartao_id} | Form: {formulario_id} | Score: {score}",
        cartao_id=cartao_id,
        formulario_id=formulario_id,
        dados={"score": score, "criterios": criterios_lista, "confirmado": bool(confirmado)}
    )

    return id_match


def gravar_arquivos_do_log(conn, cartao_id, dados_log):
    """
    Insere na tabela 'arquivos' um registro para cada arquivo do log .sppo.

    Recebe o dicionário retornado por parse_shotputpro_log() de gma_relatorio_pdf.py.
    Para cada arquivo no log, determina o status_copia:
      - 'ok'            → arquivo verificado com sucesso (ok=True)
      - 'aviso'         → arquivo de sistema não verificado (ok=False, critico=False)
      - 'falha_critica' → arquivo de conteúdo com falha de checksum (ok=False, critico=True)

    Usa INSERT OR IGNORE para evitar duplicar arquivos se a função for chamada duas vezes.

    Parâmetros:
      conn       — conexão SQLite aberta
      cartao_id  — ID do cartão ao qual os arquivos pertencem
      dados_log  — dicionário retornado por parse_shotputpro_log()

    Retorna a contagem de arquivos efetivamente inseridos (novos, não duplicatas).
    """
    lista_arquivos = dados_log.get("arquivos", [])
    inseridos = 0

    for arq in lista_arquivos:
        nome_arquivo = arq.get("nome", "(sem nome)")
        # O parser já construiu o nome a partir do src — usamos como caminho_origem
        caminho_origem = arq.get("src", "")  # pode não existir no dict do parser
        tamanho = arq.get("tamanho", 0)
        checksum = arq.get("checksum", None)  # o parser já trunca para 16 chars
        ok = bool(arq.get("ok", False))
        critico = bool(arq.get("critico", True))

        # Determina o status da cópia deste arquivo
        if ok:
            status_copia = "ok"
        elif not critico:
            status_copia = "aviso"            # arquivo de sistema sem verificação
        else:
            status_copia = "falha_critica"    # footage com problema — sério

        # Converte o tamanho para inteiro (pode vir como string do XML)
        try:
            tamanho_int = int(tamanho)
        except (ValueError, TypeError):
            tamanho_int = 0

        # Caminho de origem: usa nome_arquivo se src não estava no dicionário
        if not caminho_origem:
            caminho_origem = nome_arquivo

        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO arquivos
                (cartao_id, nome_arquivo, caminho_origem,
                 tamanho_bytes, checksum_md5_origem,
                 verificado, eh_arquivo_sistema, status_copia)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                cartao_id,
                nome_arquivo,
                caminho_origem,
                tamanho_int,
                checksum,
                1 if ok else 0,
                0 if critico else 1,   # critico=False → é arquivo de sistema
                status_copia,
            )
        )

        if cursor.rowcount > 0:
            inseridos += 1

    conn.commit()

    # Registra evento de auditoria com o total de arquivos gravados
    if inseridos > 0:
        registrar_evento(
            conn,
            tipo="arquivos_gravados",
            descricao=f"Arquivos do log gravados | Cartão: {cartao_id} | Total: {inseridos}",
            cartao_id=cartao_id,
            dados={"total_inseridos": inseridos, "total_no_log": len(lista_arquivos)}
        )

    return inseridos


# ── PERFIS DE PROFISSIONAIS ───────────────────────────────────────────────────
#
# Estas funções formam a fundação do perfil de cada profissional de captação.
# A ideia: a cada match confirmado, o sistema acumula a "assinatura" do cartão
# (câmera, modelo, prefixos de arquivo, faixas de numeração) sob o nome do
# profissional. Com o tempo, isso permite desempatar matches ambíguos na Fase 2
# sem precisar chamar o operador.
#
# IMPORTANTE: estas funções guardam apenas metadados — nunca conteúdo de mídia.


def atualizar_perfil(conn, nome, assinatura):
    """
    Faz upsert acumulativo do perfil de um profissional de captação.

    Chamada pela Camada 1 sempre que um match é confirmado. Se o perfil
    ainda não existe, cria um novo. Se já existe, acumula os dados do
    novo cartão sem apagar o histórico anterior.

    Lógica de acumulação:
      - cameras_vistas  : incrementa a contagem da marca (se não for None)
      - modelos_vistos  : incrementa a contagem do modelo (se não for None)
      - prefixos_vistos : incrementa a contagem de cada prefixo da lista
      - ultimo_num_max  : guarda o MAIOR entre o atual e o novo (se não for None)
      - faixas_vistas   : faz append de [num_min, num_max] (se ambos não forem None)
      - total_cartoes   : +1
      - ultimo_visto e atualizado_em : timestamp de agora

    Parâmetros:
      conn       — conexão SQLite aberta (de inicializar_banco() ou obter_conexao())
      nome       — nome do profissional de captação, normalizado em maiúsculas
                   (ex: "JOAO", "PAULO")
      assinatura — dicionário com os dados do cartão recém-matched:
                   {
                     "camera":   "GoPro",           # marca (pode ser None)
                     "modelo":   "GoPro HERO7 Black",# modelo via exiftool (pode ser None)
                     "prefixos": ["GOPR"],           # lista de prefixos (pode ser [])
                     "num_min":  1,                  # menor nº de arquivo (pode ser None)
                     "num_max":  200,                # maior nº de arquivo (pode ser None)
                   }

    Retorna o ID do perfil (novo ou existente).
    """
    timestamp_agora = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    # Lê os campos da assinatura com fallback seguro para None/ausente
    camera   = assinatura.get("camera")
    modelo   = assinatura.get("modelo")
    prefixos = assinatura.get("prefixos") or []   # garante lista mesmo se vier None
    num_min  = assinatura.get("num_min")
    num_max  = assinatura.get("num_max")

    # Busca o perfil existente para este profissional
    linha = conn.execute(
        "SELECT * FROM perfis WHERE nome = ?", (nome,)
    ).fetchone()

    if linha is None:
        # ── Perfil novo: inicializa a partir desta assinatura ─────────────────

        # Inicializa os dicionários de contagem com o que veio desta assinatura
        cameras_dict  = {camera: 1}  if camera  else {}
        modelos_dict  = {modelo: 1}  if modelo  else {}
        prefixos_dict = {p: 1 for p in prefixos} if prefixos else {}

        # Faixas: lista de listas [[min, max]] — só registra se ambos existirem
        faixas_lista = [[num_min, num_max]] if (num_min is not None and num_max is not None) else []

        conn.execute(
            """
            INSERT INTO perfis
                (nome, cameras_vistas, modelos_vistos, prefixos_vistos,
                 ultimo_num_max, faixas_vistas, total_cartoes,
                 primeiro_visto, ultimo_visto, atualizado_em)
            VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
            """,
            (
                nome,
                json.dumps(cameras_dict,  ensure_ascii=False),
                json.dumps(modelos_dict,  ensure_ascii=False),
                json.dumps(prefixos_dict, ensure_ascii=False),
                num_max,                                          # ultimo_num_max
                json.dumps(faixas_lista,  ensure_ascii=False),
                timestamp_agora,                                  # primeiro_visto
                timestamp_agora,                                  # ultimo_visto
                timestamp_agora,                                  # atualizado_em
            )
        )
        conn.commit()

        # Busca o ID recem-criado
        id_perfil = conn.execute(
            "SELECT id FROM perfis WHERE nome = ?", (nome,)
        ).fetchone()["id"]

    else:
        # ── Perfil existente: acumula os dados do novo cartão ─────────────────

        id_perfil = linha["id"]

        # Desserializa os campos JSON (tratando None ou vazio como {} ou [])
        cameras_dict  = json.loads(linha["cameras_vistas"]  or "{}") or {}
        modelos_dict  = json.loads(linha["modelos_vistos"]   or "{}") or {}
        prefixos_dict = json.loads(linha["prefixos_vistos"]  or "{}") or {}
        faixas_lista  = json.loads(linha["faixas_vistas"]    or "[]") or []

        # Acumula a câmera (marca)
        if camera:
            cameras_dict[camera] = cameras_dict.get(camera, 0) + 1

        # Acumula o modelo
        if modelo:
            modelos_dict[modelo] = modelos_dict.get(modelo, 0) + 1

        # Acumula cada prefixo da lista
        for prefixo in prefixos:
            if prefixo:
                prefixos_dict[prefixo] = prefixos_dict.get(prefixo, 0) + 1

        # Atualiza o maior número de arquivo já visto
        ultimo_num_max_atual = linha["ultimo_num_max"]
        if num_max is not None:
            if ultimo_num_max_atual is None:
                novo_ultimo_num_max = num_max
            else:
                novo_ultimo_num_max = max(ultimo_num_max_atual, num_max)
        else:
            novo_ultimo_num_max = ultimo_num_max_atual

        # Registra a nova faixa no histórico (só se ambos os limites existirem)
        if num_min is not None and num_max is not None:
            faixas_lista.append([num_min, num_max])

        conn.execute(
            """
            UPDATE perfis SET
                cameras_vistas  = ?,
                modelos_vistos  = ?,
                prefixos_vistos = ?,
                ultimo_num_max  = ?,
                faixas_vistas   = ?,
                total_cartoes   = total_cartoes + 1,
                ultimo_visto    = ?,
                atualizado_em   = ?
            WHERE nome = ?
            """,
            (
                json.dumps(cameras_dict,  ensure_ascii=False),
                json.dumps(modelos_dict,  ensure_ascii=False),
                json.dumps(prefixos_dict, ensure_ascii=False),
                novo_ultimo_num_max,
                json.dumps(faixas_lista,  ensure_ascii=False),
                timestamp_agora,   # ultimo_visto
                timestamp_agora,   # atualizado_em
                nome,
            )
        )
        conn.commit()

    # Registra evento de auditoria (append-only)
    registrar_evento(
        conn,
        tipo="perfil_atualizado",
        descricao=f"Perfil atualizado | Profissional: {nome} | Câmera: {camera}",
        dados={
            "nome":     nome,
            "camera":   camera,
            "modelo":   modelo,
            "prefixos": prefixos,
            "num_min":  num_min,
            "num_max":  num_max,
        }
    )

    return id_perfil


def consultar_perfil(conn, nome):
    """
    Retorna o perfil de um profissional com os campos JSON já desserializados.

    Os campos cameras_vistas, modelos_vistos, prefixos_vistos e faixas_vistas
    são retornados como dict/list Python (não como strings JSON brutas).

    Parâmetros:
      conn — conexão SQLite aberta (de inicializar_banco() ou obter_conexao())
      nome — nome do profissional (ex: "JOAO") — maiúsculas, como gravado

    Retorna um dicionário com todos os campos do perfil, ou None se o
    profissional ainda não tiver nenhum match registrado.

    Exemplo de retorno:
      {
        "id":             1,
        "nome":           "JOAO",
        "cameras_vistas": {"GoPro": 2},
        "modelos_vistos": {"GoPro HERO7 Black": 2},
        "prefixos_vistos":{"GOPR": 2},
        "ultimo_num_max": 400,
        "faixas_vistas":  [[1, 200], [201, 400]],
        "total_cartoes":  2,
        "primeiro_visto": "2026-06-08T10:00:00",
        "ultimo_visto":   "2026-06-08T10:05:00",
        "atualizado_em":  "2026-06-08T10:05:00",
      }
    """
    linha = conn.execute(
        "SELECT * FROM perfis WHERE nome = ?", (nome,)
    ).fetchone()

    if linha is None:
        return None

    # Constrói o dicionário desserializando os campos JSON
    perfil = {
        "id":              linha["id"],
        "nome":            linha["nome"],
        "cameras_vistas":  json.loads(linha["cameras_vistas"]  or "{}") or {},
        "modelos_vistos":  json.loads(linha["modelos_vistos"]   or "{}") or {},
        "prefixos_vistos": json.loads(linha["prefixos_vistos"]  or "{}") or {},
        "ultimo_num_max":  linha["ultimo_num_max"],
        "faixas_vistas":   json.loads(linha["faixas_vistas"]    or "[]") or [],
        "total_cartoes":   linha["total_cartoes"],
        "primeiro_visto":  linha["primeiro_visto"],
        "ultimo_visto":    linha["ultimo_visto"],
        "atualizado_em":   linha["atualizado_em"],
    }

    return perfil


# ── PROFISSIONAIS (Nova Ficha v2) ─────────────────────────────────────────────
#
# Tabela `profissionais`: nome + booleanos de tipo de material + letra sequencial
# imutável (A, B, C…). A letra é pista visual das câmeras no set, NÃO autoridade
# de identidade (a B do set pode não ser a B do cadastro).

def migrar_schema_profissionais(conn):
    """Cria a tabela `profissionais` se não existir. Segura para bancos existentes."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS profissionais (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            nome      TEXT    NOT NULL UNIQUE,
            tem_foto  INTEGER NOT NULL DEFAULT 0,
            tem_audio INTEGER NOT NULL DEFAULT 0,
            tem_video INTEGER NOT NULL DEFAULT 0,
            letra     TEXT    NOT NULL UNIQUE,
            ativo     INTEGER NOT NULL DEFAULT 1,
            camera    TEXT,
            criado_em TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
        )
    """)

    # Migração para bancos que já tinham a tabela SEM a coluna 'ativo'.
    # 'ativo' = 1 (todos começam ativos); desativar é soft-delete: o profissional
    # some dos dropdowns da ficha mas continua no cadastro, pronto pra reativar.
    colunas = [linha[1] for linha in conn.execute("PRAGMA table_info(profissionais)").fetchall()]
    if "ativo" not in colunas:
        conn.execute("ALTER TABLE profissionais ADD COLUMN ativo INTEGER NOT NULL DEFAULT 1")

    # Migração para bancos sem a coluna 'camera' (Nova Ficha v2, Fatia 4).
    # A câmera saiu da ficha e passou a morar no cadastro do profissional: é o
    # campo que o Matcher usa para o critério +3 (compara com a marca detectada
    # no cartão). NULL por padrão — câmera é opcional no cadastro.
    if "camera" not in colunas:
        conn.execute("ALTER TABLE profissionais ADD COLUMN camera TEXT")

    conn.commit()


def _indice_para_letra(n):
    """Converte um índice 0-based em letra (0→A, 1→B, …, 25→Z, 26→AA, …).
    Codificação base-26 sem zero (bijetiva, estilo coluna de Excel)."""
    resultado = []
    n += 1  # transforma 0-based em 1-based para o algoritmo
    while n > 0:
        n, resto = divmod(n - 1, 26)
        resultado.append(chr(ord('A') + resto))
    return ''.join(reversed(resultado))


def _letra_para_indice(letra):
    """Inverso de _indice_para_letra: 'A'→0, 'Z'→25, 'AA'→26, …"""
    n = 0
    for ch in (letra or "").strip().upper():
        n = n * 26 + (ord(ch) - ord('A') + 1)
    return n - 1


def _proxima_letra(conn):
    """
    Retorna a próxima letra sequencial (A, B, C, …, Z, AA, AB, …).

    Baseia-se na MAIOR letra já atribuída — NÃO na contagem de registros. Por quê:
    a contagem quebra quando se exclui um profissional do meio. Ex.: com A, B, D
    cadastrados (o C foi excluído), COUNT=3 calcularia "D" de novo → colisão com a
    letra única já existente, e o cadastro falha para QUALQUER nome novo.

    Apagar um nome do meio NÃO reaproveita a letra dele: a "C" fica queimada de
    propósito (a letra é pista permanente das câmeras no set — reusá-la para outra
    pessoa confundiria a identificação). A letra só "volta" se você excluir o último
    cadastrado (aí o próximo legitimamente reutiliza aquela posição). Tabela vazia → A.
    """
    rows = conn.execute("SELECT letra FROM profissionais").fetchall()
    if not rows:
        return _indice_para_letra(0)
    maior = max(_letra_para_indice(r[0]) for r in rows)
    return _indice_para_letra(maior + 1)


def criar_profissional(conn, nome, tipos, camera=None):
    """
    Cadastra um novo profissional e atribui a próxima letra sequencial.

    Args:
        conn:   conexão SQLite aberta.
        nome:   nome do profissional (ex.: "JOAO"). UNIQUE — erro se duplicado.
        tipos:  dict com chaves "foto", "audio", "video" (bool ou 0/1).
                Exemplo: {"foto": True, "audio": False, "video": True}
        camera: marca da câmera do profissional (ex.: "Sony"). Opcional — é o que o
                Matcher compara com a marca detectada no cartão (critério +3).

    Returns:
        dict com id, nome, tem_foto, tem_audio, tem_video, letra, camera, criado_em.

    Raises:
        sqlite3.IntegrityError: se o nome já existir.
        ValueError: se nenhum tipo for marcado.
    """
    nome = nome.strip().upper()
    if not nome:
        raise ValueError("Nome não pode ser vazio.")

    tem_foto  = int(bool(tipos.get("foto",  False)))
    tem_audio = int(bool(tipos.get("audio", False)))
    tem_video = int(bool(tipos.get("video", False)))

    if not (tem_foto or tem_audio or tem_video):
        raise ValueError(f"Profissional '{nome}' precisa ter ao menos um tipo marcado.")

    camera = (camera or "").strip() or None

    letra = _proxima_letra(conn)

    conn.execute(
        """
        INSERT INTO profissionais (nome, tem_foto, tem_audio, tem_video, letra, camera)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (nome, tem_foto, tem_audio, tem_video, letra, camera),
    )
    conn.commit()

    row = conn.execute(
        "SELECT id, nome, tem_foto, tem_audio, tem_video, letra, camera, criado_em "
        "FROM profissionais WHERE nome = ?",
        (nome,),
    ).fetchone()

    return {
        "id":        row[0],
        "nome":      row[1],
        "tem_foto":  bool(row[2]),
        "tem_audio": bool(row[3]),
        "tem_video": bool(row[4]),
        "letra":     row[5],
        "camera":    row[6],
        "criado_em": row[7],
    }


def definir_ativo_profissional(conn, prof_id, ativo):
    """
    Liga (ativo=True) ou desliga (ativo=False) um profissional — soft-delete.

    Desativar NÃO apaga o registro nem mexe na letra sequencial: o profissional
    apenas some dos dropdowns da ficha (que carrega só ativos). Reativar traz de volta.

    Args:
        conn:    conexão SQLite aberta.
        prof_id: id do profissional.
        ativo:   True (ativar) ou False (desativar).

    Returns:
        True se algum registro foi alterado; False se o id não existia.
    """
    cursor = conn.execute(
        "UPDATE profissionais SET ativo = ? WHERE id = ?",
        (int(bool(ativo)), prof_id),
    )
    conn.commit()
    return cursor.rowcount > 0


def nomes_em_uso(conn):
    """
    Devolve o conjunto de nomes (MAIÚSCULAS, sem espaços nas pontas) que aparecem
    em alguma ficha (`formularios.nome`). Usado para saber quais profissionais NÃO
    podem ser excluídos — só os que não tocaram em material algum são sobras reais.
    """
    rows = conn.execute(
        "SELECT DISTINCT UPPER(TRIM(nome)) FROM formularios "
        "WHERE nome IS NOT NULL AND TRIM(nome) <> ''"
    ).fetchall()
    return {r[0] for r in rows}


def excluir_profissional(conn, prof_id):
    """
    Exclui um profissional DEFINITIVAMENTE — mas só se for sobra real, ou seja, se
    o nome não aparece em NENHUMA ficha. Princípio 2 do projeto: nunca destruir o
    que está em uso. Para tirar de circulação algo que já tem material, use
    `definir_ativo_profissional` (desativar — reversível).

    Returns:
        "excluido"    — apagado com sucesso.
        "em_uso"      — recusado: o nome aparece em ao menos uma ficha.
        "inexistente" — não havia profissional com esse id.
    """
    row = conn.execute("SELECT nome FROM profissionais WHERE id = ?", (prof_id,)).fetchone()
    if row is None:
        return "inexistente"

    nome = row[0]
    usos = conn.execute(
        "SELECT COUNT(*) FROM formularios WHERE UPPER(TRIM(nome)) = UPPER(TRIM(?))",
        (nome,),
    ).fetchone()[0]
    if usos > 0:
        return "em_uso"

    conn.execute("DELETE FROM profissionais WHERE id = ?", (prof_id,))
    conn.commit()
    return "excluido"


def listar_profissionais(conn, filtro_tipo=None, apenas_ativos=False):
    """
    Retorna profissionais cadastrados, ordenados pela letra (A → Z → AA…).

    Args:
        conn:          conexão SQLite aberta.
        filtro_tipo:   "foto" | "audio" | "video" | None (todos).
                       Filtra profissionais que têm aquele tipo marcado.
        apenas_ativos: se True, devolve só os ativos (a ficha usa isto). Se False,
                       devolve todos — incluindo desativados (a tela de cadastro usa).

    Returns:
        Lista de dicts com id, nome, tem_foto, tem_audio, tem_video, letra, ativo.
    """
    COLUNAS_TIPO = {"foto": "tem_foto", "audio": "tem_audio", "video": "tem_video"}

    condicoes = []
    if filtro_tipo is not None:
        coluna = COLUNAS_TIPO.get(filtro_tipo.lower())
        if coluna is None:
            raise ValueError(f"filtro_tipo inválido: '{filtro_tipo}'. Use foto, audio ou video.")
        condicoes.append(f"{coluna} = 1")
    if apenas_ativos:
        condicoes.append("ativo = 1")

    where = (" WHERE " + " AND ".join(condicoes)) if condicoes else ""
    sql = (
        "SELECT id, nome, tem_foto, tem_audio, tem_video, letra, ativo, camera "
        f"FROM profissionais{where} ORDER BY length(letra), letra"
    )
    rows = conn.execute(sql).fetchall()

    return [
        {
            "id":        r[0],
            "nome":      r[1],
            "tem_foto":  bool(r[2]),
            "tem_audio": bool(r[3]),
            "tem_video": bool(r[4]),
            "letra":     r[5],
            "ativo":     bool(r[6]),
            "camera":    r[7],
        }
        for r in rows
    ]


def definir_camera_profissional(conn, prof_id, camera):
    """
    Atualiza a câmera de um profissional (edição inline na aba Profissionais).

    Args:
        conn:    conexão SQLite aberta.
        prof_id: id do profissional.
        camera:  marca da câmera (ex.: "Sony"). Vazio → grava NULL (sem câmera).

    Returns:
        True se algum registro foi alterado; False se o id não existia.
    """
    camera = (camera or "").strip() or None
    cursor = conn.execute(
        "UPDATE profissionais SET camera = ? WHERE id = ?",
        (camera, prof_id),
    )
    conn.commit()
    return cursor.rowcount > 0


def camera_do_profissional(conn, nome):
    """
    Devolve a câmera cadastrada para um profissional, buscando pelo nome (ignora
    maiúsculas/espaços). É a fonte do critério +3 do Matcher na Nova Ficha v2:
    a câmera não vem mais da ficha, vem do cadastro.

    Returns:
        A marca da câmera (str) ou None se o nome não está cadastrado ou não tem câmera.
    """
    if not nome or not str(nome).strip():
        return None
    row = conn.execute(
        "SELECT camera FROM profissionais WHERE UPPER(TRIM(nome)) = UPPER(TRIM(?))",
        (nome,),
    ).fetchone()
    return row[0] if row else None


# ── LISTAS DE CONTEXTO (Classificação dinâmica por evento) ───────────────────
#
# As opções de classificação da ficha (palco, marca, serviço, pauta, tags) são
# geridas aqui pelo operador. Ele cria/ativa/desativa itens durante o evento;
# a ficha lê em tempo real apenas os itens ativos.
#
# Tabela: listas_contexto
#   tipo  : categoria do item — conjunto fixo: palco, marca, pauta, servico, tag
#   valor : o texto do item (ex: "RedBull", "Palco Principal")
#   ativo : 1 = aparece na ficha / 0 = desativado (soft-delete, preserva histórico)
#   ordem : inteiro para ordenação manual (não implementada na ficha ainda; default 0)
#
# Padrão idêntico ao de profissionais:
#   - Soft-delete via campo `ativo` (desativar é reversível)
#   - Excluir definitivo SÓ se o item não estiver "em uso"
#   - Unicidade: não permite dois itens com o mesmo (tipo, valor)
#
# NOTA FUTURA: quando os chips entrarem na ficha (fatia futura), a coluna
# "em_uso" passará a verificar se o item aparece em formulários. Por ora,
# a verificação sempre retorna "não em uso" — o guard já existe, mas é
# "transparente" até a integração com a ficha ser construída.

# Tipos válidos de lista. Conjunto fixo nesta fatia — extensível no futuro.
TIPOS_LISTA_CONTEXTO = {"palco", "marca", "pauta", "servico", "tag"}

# Rótulos legíveis para exibição na aba Listas.
ROTULOS_LISTA_CONTEXTO = {
    "palco":   "Palcos",
    "marca":   "Marcas",
    "pauta":   "Pautas",
    "servico": "Serviços",
    "tag":     "Tags",
}

# Ordem de exibição na aba Listas (a mesma descrita no briefing).
ORDEM_TIPOS_LISTA = ["palco", "marca", "pauta", "servico", "tag"]


# ─────────────────────────────────────────────────────────────────────────────
# Grupos de classificação editáveis (tabela grupos_classificacao)
# ─────────────────────────────────────────────────────────────────────────────
# Os grupos (palco/marca/pauta/servico/tag) deixam de ser constantes fixas e
# viram dados editáveis pelo operador (decisão s33). Um único ponto de criação
# que alimenta a ficha (chips) E a planilha (coluna). Cada grupo:
#   chave    — identificador estável (ex: "palco", "custom_sala"); = listas_contexto.tipo
#   rotulo   — nome exibido (editável; ex: "Palcos")
#   multipla — 1 = marca vários / 0 = escolhe um (regra POR grupo; substitui CLASSIF_UNICA)
#   ordem    — ordem de exibição
#   ativo    — 1 = aparece na ficha / 0 = desativado (soft-delete preserva histórico)
#   sistema  — 1 = grupo padrão semeado pelo sistema / 0 = criado pelo operador
#
# Regra de exclusão (s33): pode excluir de vez SÓ se o grupo não foi usado em
# nenhuma ficha; se já foi usado, só desativa. O guard é "em uso?", não "sistema?".

# Os 5 grupos padrão semeados em todo banco novo: (chave, rotulo, multipla, ordem).
GRUPOS_PADRAO = [
    ("palco",   "Palcos",   1, 0),
    ("marca",   "Marcas",   1, 1),
    ("pauta",   "Pautas",   1, 2),
    ("servico", "Serviços", 1, 3),
    ("tag",     "Tags",     1, 4),
]


def migrar_schema_grupos_classificacao(conn):
    """
    Cria a tabela `grupos_classificacao` se ainda não existir e semeia os 5 grupos
    padrão (INSERT OR IGNORE — não sobrescreve o que o operador já editou).

    Não-destrutivo: seguro chamar em bancos existentes.
    """
    conn.execute("""
        CREATE TABLE IF NOT EXISTS grupos_classificacao (
            chave    TEXT PRIMARY KEY,
            rotulo   TEXT NOT NULL,
            multipla INTEGER NOT NULL DEFAULT 1,
            ordem    INTEGER NOT NULL DEFAULT 0,
            ativo    INTEGER NOT NULL DEFAULT 1,
            sistema  INTEGER NOT NULL DEFAULT 0
        )
    """)
    for chave, rotulo, multipla, ordem in GRUPOS_PADRAO:
        conn.execute(
            "INSERT OR IGNORE INTO grupos_classificacao "
            "(chave, rotulo, multipla, ordem, ativo, sistema) VALUES (?, ?, ?, ?, 1, 1)",
            (chave, rotulo, multipla, ordem),
        )
    conn.commit()


def listar_grupos(conn, apenas_ativos=False):
    """Retorna os grupos de classificação, ordenados por `ordem`."""
    where = " WHERE ativo = 1" if apenas_ativos else ""
    rows = conn.execute(
        f"SELECT chave, rotulo, multipla, ordem, ativo, sistema "
        f"FROM grupos_classificacao{where} ORDER BY ordem, rotulo"
    ).fetchall()
    return [
        {"chave": r[0], "rotulo": r[1], "multipla": bool(r[2]),
         "ordem": r[3], "ativo": bool(r[4]), "sistema": bool(r[5])}
        for r in rows
    ]


def _slug_grupo(rotulo):
    """Deriva uma chave estável (custom_<slug>) a partir do rótulo digitado."""
    import re
    base = re.sub(r"[^a-z0-9_]", "_", (rotulo or "").lower().replace(" ", "_"))[:30]
    return "custom_" + base.strip("_")


def criar_grupo(conn, rotulo, multipla=True):
    """
    Cria um grupo de classificação novo (sistema=0). A chave é derivada do rótulo.

    Returns: dict do grupo criado, ou levanta ValueError se rótulo vazio /
    sqlite3.IntegrityError se a chave colidir.
    """
    rotulo = (rotulo or "").strip()
    if not rotulo:
        raise ValueError("O nome do grupo não pode ser vazio.")
    chave = _slug_grupo(rotulo)
    if chave == "custom_":
        raise ValueError("Nome inválido para o grupo.")
    ordem = conn.execute(
        "SELECT COALESCE(MAX(ordem), -1) + 1 FROM grupos_classificacao"
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO grupos_classificacao (chave, rotulo, multipla, ordem, ativo, sistema) "
        "VALUES (?, ?, ?, ?, 1, 0)",
        (chave, rotulo, 1 if multipla else 0, ordem),
    )
    conn.commit()
    registrar_evento(conn, "grupo_criado", f"Grupo de classificação criado: {rotulo}",
                     dados={"chave": chave, "multipla": bool(multipla)})
    return {"chave": chave, "rotulo": rotulo, "multipla": bool(multipla),
            "ordem": ordem, "ativo": True, "sistema": False}


def renomear_grupo(conn, chave, novo_rotulo):
    """Renomeia um grupo (vale para padrão e personalizado). Loga a operação."""
    novo_rotulo = (novo_rotulo or "").strip()
    if not novo_rotulo:
        raise ValueError("O nome do grupo não pode ser vazio.")
    row = conn.execute(
        "SELECT rotulo FROM grupos_classificacao WHERE chave = ?", (chave,)
    ).fetchone()
    if row is None:
        return "inexistente"
    antigo = row[0]
    conn.execute("UPDATE grupos_classificacao SET rotulo = ? WHERE chave = ?",
                 (novo_rotulo, chave))
    conn.commit()
    registrar_evento(conn, "grupo_renomeado",
                     f"Grupo renomeado: {antigo} → {novo_rotulo}", dados={"chave": chave})
    return "ok"


def definir_multipla_grupo(conn, chave, multipla):
    """Define se o grupo aceita múltipla escolha (True) ou só uma (False)."""
    row = conn.execute(
        "SELECT rotulo FROM grupos_classificacao WHERE chave = ?", (chave,)
    ).fetchone()
    if row is None:
        return "inexistente"
    conn.execute("UPDATE grupos_classificacao SET multipla = ? WHERE chave = ?",
                 (1 if multipla else 0, chave))
    conn.commit()
    registrar_evento(conn, "grupo_alterado",
                     f"Grupo '{row[0]}': múltipla={bool(multipla)}", dados={"chave": chave})
    return "ok"


def definir_ativo_grupo(conn, chave, ativo):
    """Ativa/desativa um grupo (soft-delete). Loga a operação."""
    row = conn.execute(
        "SELECT rotulo FROM grupos_classificacao WHERE chave = ?", (chave,)
    ).fetchone()
    if row is None:
        return "inexistente"
    conn.execute("UPDATE grupos_classificacao SET ativo = ? WHERE chave = ?",
                 (1 if ativo else 0, chave))
    conn.commit()
    estado = "ativado" if ativo else "desativado"
    registrar_evento(conn, "grupo_alterado", f"Grupo '{row[0]}' {estado}",
                     dados={"chave": chave, "ativo": bool(ativo)})
    return "ok"


def mover_grupo(conn, chave, direcao):
    """
    Move um grupo para cima ou para baixo na ordem de exibição, trocando a
    posição com o vizinho. `direcao` ∈ {"cima", "baixo"}. Loga a operação.

    Returns: "ok" (inclusive se já está no limite) | "inexistente".
    """
    grupos = listar_grupos(conn)  # ordenados por `ordem`
    idx = next((i for i, g in enumerate(grupos) if g["chave"] == chave), None)
    if idx is None:
        return "inexistente"
    alvo = idx - 1 if direcao == "cima" else idx + 1
    if alvo < 0 or alvo >= len(grupos):
        return "ok"  # já no topo/fundo — nada a fazer
    a, b = grupos[idx], grupos[alvo]
    conn.execute("UPDATE grupos_classificacao SET ordem = ? WHERE chave = ?",
                 (b["ordem"], a["chave"]))
    conn.execute("UPDATE grupos_classificacao SET ordem = ? WHERE chave = ?",
                 (a["ordem"], b["chave"]))
    conn.commit()
    registrar_evento(conn, "grupo_alterado",
                     f"Grupo '{a['rotulo']}' movido para {direcao}", dados={"chave": chave})
    return "ok"


def grupo_em_uso(conn, chave):
    """
    True se algum item deste grupo já aparece em alguma ficha (formularios_chips).
    Usa a chave do grupo = listas_contexto.tipo.
    """
    try:
        n = conn.execute(
            "SELECT COUNT(*) FROM formularios_chips fc "
            "JOIN listas_contexto lc ON lc.id = fc.item_id "
            "WHERE lc.tipo = ?", (chave,)
        ).fetchone()[0]
        return n > 0
    except sqlite3.OperationalError:
        return False


def excluir_grupo(conn, chave):
    """
    Exclui um grupo DEFINITIVAMENTE — só se não foi usado em nenhuma ficha (s33).
    Remove junto os itens (não usados) daquele grupo. Se já foi usado, recusa
    (o operador deve desativar). Loga a operação.

    Returns: "excluido" | "em_uso" | "inexistente".
    """
    row = conn.execute(
        "SELECT rotulo FROM grupos_classificacao WHERE chave = ?", (chave,)
    ).fetchone()
    if row is None:
        return "inexistente"
    if grupo_em_uso(conn, chave):
        return "em_uso"
    # Remove os itens (todos não usados, já que o grupo não está em uso) e o grupo.
    conn.execute("DELETE FROM listas_contexto WHERE tipo = ?", (chave,))
    conn.execute("DELETE FROM grupos_classificacao WHERE chave = ?", (chave,))
    conn.commit()
    registrar_evento(conn, "grupo_excluido", f"Grupo excluído: {row[0]}",
                     dados={"chave": chave})
    return "excluido"


def migrar_schema_listas_contexto(conn):
    """
    Cria a tabela `listas_contexto` se ainda não existir.

    Usa CREATE TABLE IF NOT EXISTS — não-destrutivo. Seguro chamar
    quantas vezes quiser em bancos existentes. Bancos novos também
    recebem a tabela via inicializar_banco() que chama esta função.

    Unicidade: (tipo, valor) — o mesmo palco não pode ser cadastrado
    duas vezes, mas o mesmo valor pode existir em tipos diferentes
    (ex: "Sala VIP" como palco e como tag não colide).
    """
    conn.execute("""
        CREATE TABLE IF NOT EXISTS listas_contexto (
            -- Identificador único gerado automaticamente
            id         INTEGER PRIMARY KEY AUTOINCREMENT,

            -- Categoria do item: palco | marca | pauta | servico | tag
            tipo       TEXT NOT NULL,

            -- Texto do item (ex: "RedBull", "Palco Principal")
            valor      TEXT NOT NULL,

            -- 1 = ativo (aparece na ficha) / 0 = desativado (soft-delete)
            ativo      INTEGER NOT NULL DEFAULT 1,

            -- Ordem de exibição manual (reservado para uso futuro; default 0)
            ordem      INTEGER NOT NULL DEFAULT 0,

            -- Timestamp de criação (nunca editado após inserção)
            criado_em  TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),

            -- Um mesmo (tipo + valor) não pode aparecer duas vezes
            UNIQUE(tipo, valor)
        )
    """)
    conn.commit()


def adicionar_item_lista(conn, tipo, valor):
    """
    Adiciona um item novo à tabela listas_contexto.

    Args:
        conn:  conexão SQLite aberta.
        tipo:  categoria do item (ex: "palco"). Deve estar em TIPOS_LISTA_CONTEXTO.
        valor: texto do item (ex: "Palco Principal").

    Returns:
        dict com id, tipo, valor, ativo, ordem, criado_em.

    Raises:
        ValueError: se o tipo for inválido ou o valor estiver vazio.
        sqlite3.IntegrityError: se já existir (tipo, valor) idêntico.
    """
    tipo = (tipo or "").strip().lower()
    # O tipo precisa ser uma chave de grupo cadastrada (fonte de verdade dinâmica,
    # s33). Cai no conjunto fixo só se a tabela de grupos ainda não existir.
    try:
        existe = conn.execute(
            "SELECT 1 FROM grupos_classificacao WHERE chave = ?", (tipo,)
        ).fetchone()
        if existe is None:
            validos = [r[0] for r in conn.execute(
                "SELECT chave FROM grupos_classificacao ORDER BY ordem")]
            raise ValueError(f"Tipo '{tipo}' inválido. Use: {', '.join(validos)}")
    except sqlite3.OperationalError:
        if tipo not in TIPOS_LISTA_CONTEXTO:
            raise ValueError(
                f"Tipo '{tipo}' inválido. Use: {', '.join(sorted(TIPOS_LISTA_CONTEXTO))}"
            )

    valor = (valor or "").strip()
    if not valor:
        raise ValueError("O valor não pode ser vazio.")

    conn.execute(
        "INSERT INTO listas_contexto (tipo, valor) VALUES (?, ?)",
        (tipo, valor),
    )
    conn.commit()

    row = conn.execute(
        "SELECT id, tipo, valor, ativo, ordem, criado_em "
        "FROM listas_contexto WHERE tipo = ? AND valor = ?",
        (tipo, valor),
    ).fetchone()

    return {
        "id":        row[0],
        "tipo":      row[1],
        "valor":     row[2],
        "ativo":     bool(row[3]),
        "ordem":     row[4],
        "criado_em": row[5],
    }


def listar_itens_lista(conn, tipo=None, apenas_ativos=False):
    """
    Retorna itens da tabela listas_contexto, agrupáveis por tipo.

    Args:
        conn:         conexão SQLite aberta.
        tipo:         filtra por tipo específico (ex: "palco"). None = todos.
        apenas_ativos: True = só retorna ativos; False = retorna todos.

    Returns:
        Lista de dicts com id, tipo, valor, ativo, ordem, criado_em.
        Ordenada por tipo (na ordem de ORDEM_TIPOS_LISTA), depois por valor.
    """
    condicoes = []
    params = []

    if tipo is not None:
        condicoes.append("tipo = ?")
        params.append(tipo)

    if apenas_ativos:
        condicoes.append("ativo = 1")

    where = (" WHERE " + " AND ".join(condicoes)) if condicoes else ""
    sql = f"SELECT id, tipo, valor, ativo, ordem, criado_em FROM listas_contexto{where} ORDER BY tipo, valor"

    rows = conn.execute(sql, params).fetchall()

    return [
        {
            "id":        r[0],
            "tipo":      r[1],
            "valor":     r[2],
            "ativo":     bool(r[3]),
            "ordem":     r[4],
            "criado_em": r[5],
        }
        for r in rows
    ]


def definir_ativo_item_lista(conn, item_id, ativo):
    """
    Ativa (ativo=True) ou desativa (ativo=False) um item — soft-delete.

    Desativar NÃO apaga o registro: o item apenas para de aparecer nas
    seleções da ficha. Reativar traz de volta. O histórico é preservado.

    Args:
        conn:    conexão SQLite aberta.
        item_id: id do item.
        ativo:   True (ativar) ou False (desativar).

    Returns:
        True se algum registro foi alterado; False se o id não existe.
    """
    cursor = conn.execute(
        "UPDATE listas_contexto SET ativo = ? WHERE id = ?",
        (int(bool(ativo)), item_id),
    )
    conn.commit()
    return cursor.rowcount > 0


def itens_lista_em_uso(conn):
    """
    Devolve o conjunto de ids de itens referenciados por ao menos uma ficha.

    Liga-se à tabela formularios_chips (a ponte chips→ficha, construída na fatia
    "chips na ficha"). Um item em uso só pode ser DESATIVADO (soft-delete, via
    definir_ativo_item_lista), nunca excluído de vez — princípio 2 do projeto.
    """
    try:
        return {
            r[0] for r in conn.execute(
                "SELECT DISTINCT item_id FROM formularios_chips"
            )
        }
    except sqlite3.OperationalError:
        # Banco antigo sem a tabela ainda — trata como "nada em uso".
        return set()


def excluir_item_lista(conn, item_id):
    """
    Exclui um item DEFINITIVAMENTE — só se não estiver em uso por fichas.

    Princípio 2 do projeto: nunca destruir o que está em uso. Para tirar
    de circulação um item que já aparece em fichas, use
    `definir_ativo_item_lista` (desativar — reversível).

    Returns:
        "excluido"    — apagado com sucesso.
        "em_uso"      — recusado: o item aparece em ao menos uma ficha.
        "inexistente" — não havia item com esse id.
    """
    row = conn.execute(
        "SELECT id FROM listas_contexto WHERE id = ?", (item_id,)
    ).fetchone()

    if row is None:
        return "inexistente"

    # Verifica se o item está em uso por alguma ficha.
    # Por ora este conjunto sempre é vazio (ver itens_lista_em_uso).
    em_uso = itens_lista_em_uso(conn)
    if item_id in em_uso:
        return "em_uso"

    conn.execute("DELETE FROM listas_contexto WHERE id = ?", (item_id,))
    conn.commit()
    return "excluido"


# ─────────────────────────────────────────────────────────────────────────────
# Ponte chips → ficha (tabela formularios_chips)
# ─────────────────────────────────────────────────────────────────────────────
# Tabela de associação: liga cada ficha (formularios) aos itens de listas_contexto
# que o profissional escolheu como classificação na ficha (palco, marca, pauta,
# serviço, tags). Normalizada — uma linha por (ficha, item). A multi-seleção (tags)
# sai de graça; a escolha única (palco/marca/…) é só convenção da interface.
#
# Por que guardar o id e não o texto: o item nunca é renomeado (UNIQUE tipo+valor)
# e só pode ser excluído de vez se NÃO estiver em uso (guard itens_lista_em_uso).
# Logo o id é estável; a planilha faz JOIN para mostrar o texto atual e respeita o
# soft-delete — um item desativado continua aparecendo nas fichas antigas, o que
# preserva o histórico (princípio 2).

def migrar_schema_formularios_chips(conn):
    """
    Cria a tabela `formularios_chips` se ainda não existir.

    Usa CREATE TABLE IF NOT EXISTS — não-destrutivo, seguro chamar várias vezes.
    """
    conn.execute("""
        CREATE TABLE IF NOT EXISTS formularios_chips (
            -- A ficha que recebeu a classificação
            formulario_id INTEGER NOT NULL REFERENCES formularios(id),

            -- O item de listas_contexto escolhido (palco/marca/pauta/serviço/tag)
            item_id       INTEGER NOT NULL REFERENCES listas_contexto(id),

            -- Um mesmo item não se repete na mesma ficha
            PRIMARY KEY (formulario_id, item_id)
        )
    """)
    conn.commit()


def definir_chips_formulario(conn, formulario_id, item_ids):
    """
    Define (substitui) o conjunto de chips de classificação de uma ficha.

    Apaga as escolhas anteriores da ficha e grava as novas. Só aceita item_ids que
    existam de fato em listas_contexto — ignora silenciosamente ids inválidos (a
    ficha é vocabulário fechado, mas defendemos no servidor mesmo assim).

    Args:
        conn:          conexão SQLite aberta.
        formulario_id: id da ficha (tabela formularios).
        item_ids:      iterável de ids de listas_contexto (str ou int).

    Returns:
        Número de chips efetivamente gravados.
    """
    # Normaliza os ids para inteiros, descartando o que não for número.
    ids_norm = []
    for x in (item_ids or []):
        try:
            ids_norm.append(int(x))
        except (TypeError, ValueError):
            continue

    # Mantém só os ids que existem em listas_contexto (vocabulário fechado),
    # preservando a ordem de chegada e sem duplicar.
    validos = []
    if ids_norm:
        marcadores = ",".join("?" for _ in ids_norm)
        existentes = {
            r[0] for r in conn.execute(
                f"SELECT id FROM listas_contexto WHERE id IN ({marcadores})",
                ids_norm,
            )
        }
        vistos = set()
        for i in ids_norm:
            if i in existentes and i not in vistos:
                validos.append(i)
                vistos.add(i)

    # Substitui: limpa as escolhas antigas e grava as novas (transação única).
    conn.execute("DELETE FROM formularios_chips WHERE formulario_id = ?", (formulario_id,))
    conn.executemany(
        "INSERT OR IGNORE INTO formularios_chips (formulario_id, item_id) VALUES (?, ?)",
        [(formulario_id, i) for i in validos],
    )
    conn.commit()
    return len(validos)


def listar_chips_formulario(conn, formulario_id):
    """
    Devolve os chips de classificação escolhidos por UMA ficha.

    Returns:
        Lista de dicts {item_id, tipo, valor, ativo}, ordenada por tipo
        (ORDEM_TIPOS_LISTA) e depois por valor. Inclui itens desativados
        (soft-delete) que ainda constam na ficha — preserva o histórico.
    """
    rows = conn.execute("""
        SELECT lc.id, lc.tipo, lc.valor, lc.ativo
        FROM formularios_chips fc
        JOIN listas_contexto lc ON lc.id = fc.item_id
        WHERE fc.formulario_id = ?
    """, (formulario_id,)).fetchall()

    itens = [
        {"item_id": r[0], "tipo": r[1], "valor": r[2], "ativo": bool(r[3])}
        for r in rows
    ]
    ordem = {t: i for i, t in enumerate(ORDEM_TIPOS_LISTA)}
    itens.sort(key=lambda it: (ordem.get(it["tipo"], 99), it["valor"].lower()))
    return itens


def chips_por_formulario(conn, formulario_ids=None):
    """
    Versão em lote de listar_chips_formulario — para a Planilha (muitas linhas).

    Args:
        conn:           conexão SQLite aberta.
        formulario_ids: lista de ids para filtrar. None/vazio = todas as fichas.

    Returns:
        dict {formulario_id: [ {item_id, tipo, valor, ativo}, ... ]}, cada lista
        ordenada por tipo (ORDEM_TIPOS_LISTA) e depois por valor.
    """
    where = ""
    params = []
    if formulario_ids:
        ids = [int(x) for x in formulario_ids]
        if not ids:
            return {}
        marcadores = ",".join("?" for _ in ids)
        where = f" WHERE fc.formulario_id IN ({marcadores})"
        params = ids

    rows = conn.execute(f"""
        SELECT fc.formulario_id, lc.id, lc.tipo, lc.valor, lc.ativo
        FROM formularios_chips fc
        JOIN listas_contexto lc ON lc.id = fc.item_id
        {where}
    """, params).fetchall()

    ordem = {t: i for i, t in enumerate(ORDEM_TIPOS_LISTA)}
    mapa = {}
    for r in rows:
        mapa.setdefault(r[0], []).append(
            {"item_id": r[1], "tipo": r[2], "valor": r[3], "ativo": bool(r[4])}
        )
    for lista in mapa.values():
        lista.sort(key=lambda it: (ordem.get(it["tipo"], 99), it["valor"].lower()))
    return mapa


# ─────────────────────────────────────────────────────────────────────────────
# Molde da Planilha — quais colunas ficam visíveis e quais são personalizadas
# ─────────────────────────────────────────────────────────────────────────────
# Cada coluna da Planilha de Entrega tem um registro aqui:
#   chave   — identificador único (fixo para colunas do sistema)
#   rotulo  — nome exibido no cabeçalho (editável via interface)
#   bloco   — agrupamento: identificacao | classificacao | tecnicas | pos_producao | custom
#   ordem   — posição dentro do bloco
#   visivel — 1 = aparece na planilha / 0 = oculta
#   sistema — 1 = vem do catálogo do código (só pode ocultar, não excluir)
#             0 = criada pelo operador (pode ser excluída)
#
# O catálogo de colunas padrão é definido em flask_gma.py (CATALOGO_PLANILHA) e
# sincronizado no banco via sincronizar_catalogo_molde(). INSERT OR IGNORE garante
# que colunas já existentes não perdem o estado visivel que o operador configurou.

def migrar_schema_molde_planilha(conn):
    """
    Cria a tabela `molde_planilha` se ainda não existir.

    Não-destrutiva: seguro chamar em bancos existentes. O estado de visibilidade
    de colunas já configuradas pelo operador é preservado.
    """
    conn.execute("""
        CREATE TABLE IF NOT EXISTS molde_planilha (
            -- Identificador único da coluna (ex: "prof_nome", "chip_palco")
            chave   TEXT PRIMARY KEY,

            -- Rótulo exibido no cabeçalho da planilha
            rotulo  TEXT NOT NULL,

            -- Bloco ao qual pertence (identificacao/classificacao/tecnicas/pos_producao/custom)
            bloco   TEXT NOT NULL,

            -- Posição dentro do bloco (menor = primeiro)
            ordem   INTEGER NOT NULL DEFAULT 0,

            -- 1 = visível na planilha / 0 = oculta
            visivel INTEGER NOT NULL DEFAULT 1,

            -- 1 = coluna do sistema (não pode ser excluída, só ocultada)
            -- 0 = coluna personalizada criada pelo operador (pode ser excluída)
            sistema INTEGER NOT NULL DEFAULT 1
        )
    """)
    conn.commit()


def sincronizar_catalogo_molde(conn, catalogo):
    """
    Registra no banco as colunas do catálogo padrão que ainda não existem.

    Usa INSERT OR IGNORE — colunas já existentes mantêm o estado visivel
    que o operador configurou. Só insere entradas novas.

    Args:
        conn:     conexão SQLite aberta.
        catalogo: CATALOGO_PLANILHA de flask_gma.py — lista de tuplas
                  (chave, rotulo, bloco, tipo_render, campo, visivel_padrao).
    """
    for ordem, entrada in enumerate(catalogo):
        chave, rotulo, bloco = entrada[0], entrada[1], entrada[2]
        visivel_padrao = entrada[5] if len(entrada) > 5 else 1
        conn.execute(
            """INSERT OR IGNORE INTO molde_planilha
               (chave, rotulo, bloco, ordem, visivel, sistema)
               VALUES (?, ?, ?, ?, ?, 1)""",
            (chave, rotulo, bloco, ordem, visivel_padrao),
        )
    conn.commit()


def sincronizar_colunas_grupos(conn):
    """
    Garante uma coluna de planilha por grupo de classificação (Fatia 4, s33).

    Para cada grupo existente cria/atualiza a coluna `chip_<chave>` no molde
    (bloco 'classificacao', visível por padrão — decisão s33). Propaga o rótulo
    e a ordem do grupo. Remove colunas `chip_*` órfãs (grupo excluído).

    A coluna existir não significa aparecer: a planilha só mostra a coluna de um
    grupo ATIVO (filtro na renderização) e respeitando o liga/desliga do molde.
    """
    try:
        grupos = listar_grupos(conn)
    except sqlite3.OperationalError:
        return  # tabela de grupos ainda não existe (banco muito antigo)

    chaves_validas = set()
    for g in grupos:
        col = "chip_" + g["chave"]
        chaves_validas.add(col)
        existe = conn.execute(
            "SELECT 1 FROM molde_planilha WHERE chave = ?", (col,)
        ).fetchone()
        if existe is None:
            conn.execute(
                "INSERT INTO molde_planilha (chave, rotulo, bloco, ordem, visivel, sistema) "
                "VALUES (?, ?, 'classificacao', ?, 1, 1)",
                (col, g["rotulo"], g["ordem"]),
            )
        else:
            # Propaga rótulo e ordem do grupo (renomear/reordenar reflete na planilha).
            conn.execute(
                "UPDATE molde_planilha SET rotulo = ?, ordem = ? WHERE chave = ?",
                (g["rotulo"], g["ordem"], col),
            )
    # Limpa colunas chip_* de grupos que não existem mais.
    for r in conn.execute(
        "SELECT chave FROM molde_planilha WHERE chave LIKE 'chip\\_%' ESCAPE '\\'"
    ).fetchall():
        if r[0] not in chaves_validas:
            conn.execute("DELETE FROM molde_planilha WHERE chave = ?", (r[0],))
    conn.commit()


def listar_molde(conn):
    """
    Retorna todas as colunas do molde, ordenadas por ordem global.

    Returns:
        Lista de dicts com chave, rotulo, bloco, ordem, visivel, sistema.
    """
    rows = conn.execute(
        "SELECT chave, rotulo, bloco, ordem, visivel, sistema "
        "FROM molde_planilha ORDER BY ordem"
    ).fetchall()
    return [
        {"chave": r[0], "rotulo": r[1], "bloco": r[2],
         "ordem": r[3], "visivel": bool(r[4]), "sistema": bool(r[5])}
        for r in rows
    ]


def listar_molde_visivel(conn):
    """
    Retorna apenas as colunas marcadas como visíveis, em ordem.

    Usada pela rota /planilha para decidir quais colunas renderizar.
    """
    rows = conn.execute(
        "SELECT chave, rotulo, bloco, ordem, visivel, sistema "
        "FROM molde_planilha WHERE visivel = 1 ORDER BY ordem"
    ).fetchall()
    return [
        {"chave": r[0], "rotulo": r[1], "bloco": r[2],
         "ordem": r[3], "visivel": True, "sistema": bool(r[5])}
        for r in rows
    ]


def definir_visivel_coluna(conn, chave, visivel):
    """
    Liga ou desliga a visibilidade de uma coluna na planilha.

    Args:
        conn:    conexão SQLite aberta.
        chave:   chave da coluna (ex: "prof_nome").
        visivel: True/1 para mostrar, False/0 para ocultar.

    Returns:
        "ok" se atualizou, "inexistente" se a chave não existir.
    """
    row = conn.execute(
        "SELECT chave FROM molde_planilha WHERE chave = ?", (chave,)
    ).fetchone()
    if row is None:
        return "inexistente"
    conn.execute(
        "UPDATE molde_planilha SET visivel = ? WHERE chave = ?",
        (1 if visivel else 0, chave),
    )
    conn.commit()
    return "ok"


def adicionar_coluna_custom(conn, chave, rotulo, bloco):
    """
    Adiciona uma coluna personalizada ao molde (sistema=0, pode ser excluída).

    Args:
        conn:   conexão SQLite aberta.
        chave:  chave única derivada do rótulo (sem espaços/acentos).
        rotulo: nome exibido no cabeçalho.
        bloco:  bloco onde aparece (ex: "pos_producao", "custom").

    Returns:
        "ok"        — adicionada com sucesso.
        "duplicada" — já existe uma coluna com esta chave.
        "invalida"  — chave ou rótulo vazio.
    """
    chave = (chave or "").strip()
    rotulo = (rotulo or "").strip()
    if not chave or not rotulo:
        return "invalida"

    ordem = conn.execute(
        "SELECT COALESCE(MAX(ordem), 0) + 1 FROM molde_planilha"
    ).fetchone()[0]

    try:
        conn.execute(
            """INSERT INTO molde_planilha (chave, rotulo, bloco, ordem, visivel, sistema)
               VALUES (?, ?, ?, ?, 1, 0)""",
            (chave, rotulo, bloco, ordem),
        )
        conn.commit()
        return "ok"
    except Exception:
        return "duplicada"


def excluir_coluna_custom(conn, chave):
    """
    Exclui uma coluna personalizada (sistema=0) definitivamente.

    Colunas do sistema (sistema=1) não podem ser excluídas — use
    definir_visivel_coluna para ocultá-las.

    Returns:
        "excluido"   — removida com sucesso.
        "sistema"    — coluna protegida, não pode excluir.
        "inexistente"— não havia coluna com esta chave.
    """
    row = conn.execute(
        "SELECT sistema FROM molde_planilha WHERE chave = ?", (chave,)
    ).fetchone()
    if row is None:
        return "inexistente"
    if row[0] == 1:
        return "sistema"
    conn.execute("DELETE FROM molde_planilha WHERE chave = ?", (chave,))
    conn.commit()
    return "excluido"


# ── PONTO DE ENTRADA (INICIALIZAÇÃO DIRETA) ───────────────────────────────────

if __name__ == "__main__":
    """
    Quando executado diretamente (python3 banco_dados.py), inicializa o banco
    e imprime uma confirmação com as tabelas criadas e contagem de colunas.
    """
    print()
    print("=" * 60)
    print("  GMA — Camada 3: Inicialização do banco de dados")
    print("=" * 60)
    print(f"  Arquivo: {CAMINHO_BANCO}")
    print()

    # Verifica se o banco já existia antes de inicializar
    banco_ja_existia = os.path.isfile(CAMINHO_BANCO)

    # Inicializa (cria o arquivo e todas as tabelas se necessário)
    conn = inicializar_banco()

    if banco_ja_existia:
        print("  Banco já existia — tabelas verificadas (nenhum dado alterado).")
    else:
        print("  Banco criado do zero.")

    print()

    # Lista as tabelas criadas com a contagem de colunas de cada uma
    cursor = conn.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table'
        ORDER BY name;
    """)
    tabelas = [linha["name"] for linha in cursor.fetchall()]

    print("  Tabelas no banco:")
    print()

    for nome_tabela in tabelas:
        # PRAGMA table_info retorna uma linha por coluna
        cursor_colunas = conn.execute(f"PRAGMA table_info({nome_tabela});")
        colunas = cursor_colunas.fetchall()
        print(f"    {nome_tabela:<20} — {len(colunas)} coluna(s)")

    print()

    # Registra o evento de inicialização no próprio banco (auditoria)
    id_evento = registrar_evento(
        conn,
        tipo="banco_inicializado",
        descricao="Banco gma.db inicializado (CREATE TABLE IF NOT EXISTS executado)",
        dados={"tabelas": tabelas, "banco_ja_existia": banco_ja_existia}
    )

    print(f"  Evento de inicialização registrado (id={id_evento}).")
    print()
    print("  Para testar:")
    print("    python3 /Users/serafa/GMA/banco_dados.py")
    print()
    print("=" * 60)
    print()

    conn.close()
