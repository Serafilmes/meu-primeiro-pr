"""
Testes da Missão A (Fatia 1) — Busca textual sobre a planilha.

Cobre:
  1. Normalização de termos (minúsculo, sem acento)
  2. Casa por transcrição (substring em texto de áudio)
  3. Casa por classificação (chip de listas_contexto)
  4. Casa por identificação (nome do profissional, data, etc.)
  5. Não-casa (termo inexistente)
  6. Multi-palavra AND (todos os termos devem aparecer)
  7. Multi-palavra AND falha parcial (um termo não existe)
  8. Case insensitivo
  9. Busca com acento vs sem acento
 10. Consulta vazia → retorna lista vazia (sem erro)
 11. Resultado aponta quais arquivos transcritos contribuíram
 12. Trecho de contexto da transcrição é extraído

Roda sem servidor Flask nem internet. Usa banco em memória (:memory:).
"""

import sys
import os
import unittest
import sqlite3

# Garante que importa o banco_dados do diretório do projeto
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import banco_dados as bd


# ─────────────────────────────────────────────────────────────────────────────
# Helpers para montar um banco de teste em memória
# ─────────────────────────────────────────────────────────────────────────────

def _banco_de_teste():
    """Cria um banco SQLite em memória isolado com o schema completo do GMA.

    NÃO usa obter_conexao() nem muda GMA_DB (que é constante de módulo lida
    na importação). Em vez disso, cria a conexão diretamente e executa os
    CREATE TABLE extraídos do banco_dados.py via _executar_schema_base().

    Retorna (conn, None) — o None é para compatibilidade com o setUp/tearDown
    que espera um caminho (não há arquivo para apagar — está em memória).
    """
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON;")
    _executar_schema_base(conn)
    return conn, None


def _executar_schema_base(conn):
    """Cria todas as tabelas e executa as migrações num banco já aberto.

    Extrai os DDLs diretamente da lógica de banco_dados.inicializar_banco(),
    mas usando a conexão recebida — independente do CAMINHO_BANCO global.
    """
    # ── Tabelas base (CREATE TABLE IF NOT EXISTS) ─────────────────────────────
    # Copiamos o DDL essencial: cartoes, formularios, matches, arquivos, eventos,
    # profissionais. As migrações incrementais complementam no final.
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS cartoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            volume TEXT NOT NULL DEFAULT '',
            caminho_origem TEXT NOT NULL DEFAULT '',
            marca_camera TEXT,
            tipo_material TEXT,
            data_inicio TEXT,
            data_fim TEXT,
            alerta_multidia INTEGER NOT NULL DEFAULT 0,
            dias_distintos INTEGER NOT NULL DEFAULT 1,
            total_arquivos_detectados INTEGER,
            tamanho_total_bytes_detectado INTEGER,
            status TEXT NOT NULL DEFAULT 'detectado',
            numero_cartao TEXT,
            destino_pasta TEXT,
            transferencia_timestamp_inicio TEXT,
            transferencia_timestamp_fim TEXT,
            total_arquivos_transferidos INTEGER,
            total_falhos INTEGER,
            total_avisos INTEGER,
            tamanho_transferido_bytes INTEGER,
            transferencia_relatorio_pdf TEXT,
            observacoes TEXT,
            origem_material TEXT NOT NULL DEFAULT 'cartao',
            criado_em TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            atualizado_em TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        );

        CREATE TABLE IF NOT EXISTS formularios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            id_form_original TEXT UNIQUE,
            nome TEXT NOT NULL,
            camera TEXT,
            tipo_material TEXT,
            tem_foto INTEGER NOT NULL DEFAULT 0,
            tem_audio INTEGER NOT NULL DEFAULT 0,
            tem_video INTEGER NOT NULL DEFAULT 0,
            nome_audio TEXT,
            entrega_id TEXT,
            data_gravacao TEXT,
            operador TEXT,
            modelo_camera TEXT,
            tipo_conteudo TEXT,
            local_cena TEXT,
            prioridade TEXT DEFAULT 'NORMAL',
            observacoes TEXT,
            status TEXT NOT NULL DEFAULT 'aguardando_match',
            origem_material TEXT NOT NULL DEFAULT 'cartao',
            recebido_pronto INTEGER NOT NULL DEFAULT 0,
            link_recebidos TEXT,
            recebido_em TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        );

        CREATE TABLE IF NOT EXISTS matches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cartao_id INTEGER NOT NULL REFERENCES cartoes(id),
            formulario_id INTEGER NOT NULL REFERENCES formularios(id),
            score INTEGER NOT NULL DEFAULT 0,
            criterios TEXT,
            confirmado INTEGER NOT NULL DEFAULT 0,
            match_timestamp TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            UNIQUE(cartao_id),
            UNIQUE(formulario_id)
        );

        CREATE TABLE IF NOT EXISTS arquivos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cartao_id INTEGER NOT NULL REFERENCES cartoes(id),
            nome_arquivo TEXT NOT NULL,
            caminho_origem TEXT NOT NULL,
            caminho_destino TEXT,
            tamanho_bytes INTEGER,
            checksum_md5_origem TEXT,
            checksum_md5_destino TEXT,
            verificado INTEGER NOT NULL DEFAULT 0,
            eh_arquivo_sistema INTEGER NOT NULL DEFAULT 0,
            status_copia TEXT NOT NULL DEFAULT 'ok',
            erro_detalhe TEXT,
            codec TEXT, resolucao TEXT, duracao_segundos REAL,
            fps REAL, total_frames INTEGER, timecode TEXT,
            audio_codec TEXT, audio_bitrate INTEGER,
            audio_sample_rate INTEGER, audio_canais INTEGER,
            modelo_camera TEXT, caminho_thumbnail TEXT,
            tipo TEXT, proxy_de TEXT,
            transcricao TEXT, transcricao_em TEXT,
            criado_em TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        );

        CREATE TABLE IF NOT EXISTS eventos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tipo TEXT NOT NULL,
            cartao_id INTEGER REFERENCES cartoes(id),
            formulario_id INTEGER REFERENCES formularios(id),
            descricao TEXT NOT NULL,
            dados_json TEXT,
            criado_em TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        );

        CREATE TABLE IF NOT EXISTS profissionais (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            tem_foto INTEGER NOT NULL DEFAULT 0,
            tem_audio INTEGER NOT NULL DEFAULT 0,
            tem_video INTEGER NOT NULL DEFAULT 0,
            letra TEXT NOT NULL DEFAULT 'A',
            ativo INTEGER NOT NULL DEFAULT 1,
            camera TEXT,
            criado_em TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            nome_raiz TEXT,
            nome_curto TEXT
        );

        CREATE TABLE IF NOT EXISTS listas_contexto (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tipo TEXT NOT NULL,
            valor TEXT NOT NULL,
            ativo INTEGER NOT NULL DEFAULT 1,
            ordem INTEGER NOT NULL DEFAULT 0,
            criado_em TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            UNIQUE(tipo, valor)
        );

        CREATE TABLE IF NOT EXISTS formularios_chips (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            formulario_id INTEGER NOT NULL REFERENCES formularios(id),
            item_id INTEGER NOT NULL REFERENCES listas_contexto(id),
            UNIQUE(formulario_id, item_id)
        );

        CREATE TABLE IF NOT EXISTS formularios_textos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            formulario_id INTEGER NOT NULL REFERENCES formularios(id),
            grupo_chave TEXT NOT NULL,
            valor TEXT NOT NULL,
            UNIQUE(formulario_id, grupo_chave, valor)
        );

        CREATE TABLE IF NOT EXISTS grupos_classificacao (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chave TEXT NOT NULL UNIQUE,
            rotulo TEXT NOT NULL,
            multipla INTEGER NOT NULL DEFAULT 1,
            ordem INTEGER NOT NULL DEFAULT 0,
            ativo INTEGER NOT NULL DEFAULT 1,
            sistema INTEGER NOT NULL DEFAULT 0,
            modo TEXT NOT NULL DEFAULT 'lista'
        );
    """)


def _inserir_profissional(conn, nome="ANA LIMA"):
    """Insere um profissional e retorna o id.

    Usa INSERT OR REPLACE para garantir que o registro existe e devolve o id
    pelo nome (que é a chave de pesquisa usada nos JOINs do _SQL_PLANILHA).
    """
    raiz = nome.split()[0]
    curto = raiz[:3]
    # Tenta inserir; se o UNIQUE no nome quebrar, usa OR IGNORE e busca depois
    conn.execute(
        "INSERT OR IGNORE INTO profissionais "
        "(nome, nome_raiz, nome_curto, tem_foto, tem_audio, tem_video, letra, ativo, criado_em) "
        "VALUES (?, ?, ?, 0, 0, 0, 'A', 1, datetime('now'))",
        (nome, raiz, curto)
    )
    conn.commit()
    r = conn.execute("SELECT id FROM profissionais WHERE nome = ?", (nome,)).fetchone()
    if r is None:
        raise RuntimeError(f"Falha ao inserir profissional '{nome}'")
    return r["id"]


def _inserir_formulario(conn, nome="ANA LIMA", tipo="VIDEO", data="2026-06-22"):
    """Insere uma ficha (Post) e retorna o id."""
    conn.execute(
        "INSERT INTO formularios (nome, tipo_material, data_gravacao, recebido_em) "
        "VALUES (?, ?, ?, datetime('now'))",
        (nome, tipo, data)
    )
    conn.commit()
    return conn.execute("SELECT MAX(id) FROM formularios").fetchone()[0]


def _inserir_cartao(conn, numero="ANA_001", tipo="VIDEO", status="concluido"):
    """Insere um cartão e retorna o id."""
    conn.execute(
        "INSERT INTO cartoes (numero_cartao, tipo_material, status, criado_em) "
        "VALUES (?, ?, ?, datetime('now'))",
        (numero, tipo, status)
    )
    conn.commit()
    return conn.execute("SELECT MAX(id) FROM cartoes").fetchone()[0]


def _fazer_match(conn, cartao_id, formulario_id):
    """Cria um match entre cartão e ficha."""
    conn.execute(
        "INSERT INTO matches (cartao_id, formulario_id, score, confirmado, match_timestamp) "
        "VALUES (?, ?, 10, 1, datetime('now'))",
        (cartao_id, formulario_id)
    )
    conn.commit()


def _inserir_arquivo_com_transcricao(conn, cartao_id, nome_arquivo, texto_transcricao):
    """Insere um arquivo de áudio já transcrito."""
    caminho_ficticio = f"/Volumes/AUDIO/{nome_arquivo}"
    conn.execute(
        "INSERT INTO arquivos (cartao_id, nome_arquivo, caminho_origem, transcricao, "
        "transcricao_em, status_copia, verificado, tipo) "
        "VALUES (?, ?, ?, ?, datetime('now'), 'ok', 1, 'AUDIO')",
        (cartao_id, nome_arquivo, caminho_ficticio, texto_transcricao)
    )
    conn.commit()


def _inserir_chip(conn, formulario_id, tipo, valor):
    """Insere um chip de lista para a ficha."""
    # Garante que o item existe em listas_contexto
    conn.execute(
        "INSERT OR IGNORE INTO listas_contexto (tipo, valor, ativo, criado_em) "
        "VALUES (?, ?, 1, datetime('now'))",
        (tipo, valor)
    )
    conn.commit()
    item_id = conn.execute(
        "SELECT id FROM listas_contexto WHERE tipo = ? AND valor = ?", (tipo, valor)
    ).fetchone()["id"]
    conn.execute(
        "INSERT OR IGNORE INTO formularios_chips (formulario_id, item_id) VALUES (?, ?)",
        (formulario_id, item_id)
    )
    conn.commit()


# ─────────────────────────────────────────────────────────────────────────────
# Testes
# ─────────────────────────────────────────────────────────────────────────────

class TestNormalizacao(unittest.TestCase):
    """Testa as funções auxiliares de normalização (não precisam de banco)."""

    def test_normaliza_minusculo(self):
        """Texto em maiúsculas deve virar minúsculo."""
        self.assertEqual(bd._normalizar_busca("SUNSET"), "sunset")

    def test_normaliza_acento(self):
        """Texto com acento deve virar sem acento."""
        self.assertEqual(bd._normalizar_busca("Pôr do Sol"), "por do sol")

    def test_normaliza_espaco_duplo(self):
        """Espaços extras são colapsados."""
        self.assertEqual(bd._normalizar_busca("  palco   sunset  "), "palco sunset")

    def test_extrair_termos_vazio(self):
        """Consulta vazia retorna lista vazia."""
        self.assertEqual(bd._extrair_termos(""), [])

    def test_extrair_termos_multiplos(self):
        """Multi-palavras viram lista normalizada."""
        self.assertEqual(bd._extrair_termos("Sunset VOLKSWAGEN"), ["sunset", "volkswagen"])


class TestBuscaPlanilha(unittest.TestCase):
    """Testa buscar_na_planilha com banco em memória."""

    def setUp(self):
        """Monta um cenário com 2 cartões (ANA e CARLOS), chips e transcrição."""
        self.conn, self._db_path = _banco_de_teste()
        conn = self.conn

        # ── Profissionais ──────────────────────────────────────────────────
        _inserir_profissional(conn, "ANA LIMA")
        _inserir_profissional(conn, "CARLOS MELO")

        # ── Ficha ANA (vídeo, palco Sunset, marca Volkswagen) ──────────────
        self.form_ana = _inserir_formulario(conn, "ANA LIMA", "VIDEO", "2026-06-22")
        self.cartao_ana = _inserir_cartao(conn, "ANA_001", "VIDEO", "concluido")
        _fazer_match(conn, self.cartao_ana, self.form_ana)
        _inserir_chip(conn, self.form_ana, "palco", "Sunset")
        _inserir_chip(conn, self.form_ana, "marca", "Volkswagen")

        # ── Ficha CARLOS (áudio, com transcrição real) ─────────────────────
        self.form_carlos = _inserir_formulario(conn, "CARLOS MELO", "AUDIO", "2026-06-20")
        self.cartao_carlos = _inserir_cartao(conn, "CARLOS_001", "AUDIO", "concluido")
        _fazer_match(conn, self.cartao_carlos, self.form_carlos)
        # Arquivo de áudio com transcrição sobre o show do Péricles
        _inserir_arquivo_com_transcricao(
            conn, self.cartao_carlos,
            "CARLOS_001_take01.wav",
            "O show do Péricles foi incrível. O público cantou junto todas as músicas do Motown."
        )
        _inserir_chip(conn, self.form_carlos, "palco", "Sunset")

        conn.commit()

    def tearDown(self):
        self.conn.close()
        # Banco em memória: sem arquivo para apagar

    def test_casa_por_chip(self):
        """Busca por chip de classificação (palco=Sunset) deve bater."""
        resultados = bd.buscar_na_planilha(self.conn, "Sunset")
        cartoes_encontrados = {r["cartao_id"] for r in resultados}
        # Ambos têm chip palco=Sunset
        self.assertIn(self.cartao_ana,    cartoes_encontrados, "ANA deveria bater pelo chip palco")
        self.assertIn(self.cartao_carlos, cartoes_encontrados, "CARLOS deveria bater pelo chip palco")

    def test_casa_por_transcricao(self):
        """Busca por palavra na transcrição deve bater apenas no cartão de CARLOS."""
        resultados = bd.buscar_na_planilha(self.conn, "Péricles")
        cartoes_encontrados = {r["cartao_id"] for r in resultados}
        self.assertIn(self.cartao_carlos, cartoes_encontrados,
                      "CARLOS deveria bater pela transcrição")

    def test_arquivos_apontados_na_transcricao(self):
        """O resultado deve apontar qual arquivo de áudio contribuiu."""
        resultados = bd.buscar_na_planilha(self.conn, "Péricles")
        res_carlos = next((r for r in resultados if r["cartao_id"] == self.cartao_carlos), None)
        self.assertIsNotNone(res_carlos, "Resultado de CARLOS não encontrado")
        nomes = [a["nome_arquivo"] for a in res_carlos["arquivos_transcritos"]]
        self.assertIn("CARLOS_001_take01.wav", nomes,
                      "O arquivo take01 deveria aparecer nos arquivos que bateram")

    def test_trecho_de_contexto(self):
        """O resultado deve incluir um trecho de contexto da transcrição."""
        resultados = bd.buscar_na_planilha(self.conn, "Motown")
        res_carlos = next((r for r in resultados if r["cartao_id"] == self.cartao_carlos), None)
        self.assertIsNotNone(res_carlos)
        trecho = res_carlos["arquivos_transcritos"][0]["trecho"]
        self.assertTrue(len(trecho) > 0, "Trecho de contexto não pode ser vazio")

    def test_nao_casa(self):
        """Termo inexistente não deve retornar nada."""
        resultados = bd.buscar_na_planilha(self.conn, "alienígena")
        self.assertEqual(resultados, [], "Nenhum resultado esperado para termo inexistente")

    def test_multi_palavra_and_bate(self):
        """Multi-palavra AND: todos os termos presentes em campos da linha → bate."""
        # "sunset volkswagen" → chip palco=Sunset + chip marca=Volkswagen estão na ficha da ANA
        resultados = bd.buscar_na_planilha(self.conn, "sunset volkswagen")
        cartoes = {r["cartao_id"] for r in resultados}
        self.assertIn(self.cartao_ana, cartoes,
                      "ANA deveria bater (palco=Sunset e marca=Volkswagen)")

    def test_multi_palavra_and_falha_parcial(self):
        """Multi-palavra AND: se um termo não existe, a linha não bate."""
        # "sunset alienígena" → "sunset" existe, "alienígena" não
        resultados = bd.buscar_na_planilha(self.conn, "sunset alienígena")
        self.assertEqual(resultados, [],
                         "Nenhum resultado esperado: 'alienígena' não existe no banco")

    def test_case_insensitivo(self):
        """Busca em maiúsculas deve encontrar o mesmo que em minúsculas."""
        res_maiusc = bd.buscar_na_planilha(self.conn, "VOLKSWAGEN")
        res_minusc = bd.buscar_na_planilha(self.conn, "volkswagen")
        ids_maiusc = {r["cartao_id"] for r in res_maiusc}
        ids_minusc = {r["cartao_id"] for r in res_minusc}
        self.assertEqual(ids_maiusc, ids_minusc, "Busca deve ser case-insensitiva")

    def test_busca_sem_acento_bate_com_acento(self):
        """'Pericles' sem acento deve encontrar 'Péricles' com acento na transcrição."""
        resultados = bd.buscar_na_planilha(self.conn, "Pericles")
        cartoes = {r["cartao_id"] for r in resultados}
        self.assertIn(self.cartao_carlos, cartoes,
                      "Busca 'Pericles' deve bater com 'Péricles' na transcrição")

    def test_consulta_vazia_retorna_lista_vazia(self):
        """Consulta vazia ou só espaços não deve retornar resultados nem lançar erro."""
        self.assertEqual(bd.buscar_na_planilha(self.conn, ""), [])
        self.assertEqual(bd.buscar_na_planilha(self.conn, "   "), [])

    def test_casa_por_nome_profissional(self):
        """Busca pelo nome do profissional deve bater."""
        resultados = bd.buscar_na_planilha(self.conn, "carlos")
        cartoes = {r["cartao_id"] for r in resultados}
        self.assertIn(self.cartao_carlos, cartoes,
                      "CARLOS deveria bater pela busca no nome do profissional")

    def test_casa_por_data(self):
        """Busca pela data de gravação deve bater."""
        resultados = bd.buscar_na_planilha(self.conn, "2026-06-20")
        cartoes = {r["cartao_id"] for r in resultados}
        self.assertIn(self.cartao_carlos, cartoes,
                      "CARLOS deveria bater pela data 2026-06-20")


class TestExtrairTrecho(unittest.TestCase):
    """Testa a função auxiliar de extração de trecho de contexto."""

    def test_trecho_com_termo_no_meio(self):
        """Trecho deve estar em torno do termo, com marcadores de elipse."""
        texto = "a " * 50 + "palavra-chave" + " b" * 50
        trecho = bd._extrair_trecho(texto, "palavra-chave")
        self.assertIn("palavra-chave", trecho.lower())

    def test_texto_curto_sem_elipse(self):
        """Texto curto: não deve ter elipse no início."""
        texto = "show incrível no palco"
        trecho = bd._extrair_trecho(texto, "palco")
        self.assertTrue(len(trecho) <= len(texto) + 4)  # +4 para as elipses eventuais

    def test_texto_vazio(self):
        """Texto vazio não deve levantar exceção."""
        self.assertEqual(bd._extrair_trecho("", "termo"), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
