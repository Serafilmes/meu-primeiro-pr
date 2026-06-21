#!/usr/bin/env python3
"""
teste_recebidos_auditoria.py
Testes integrados da Fatia 5 do arco RECEBIDOS — Camada 4.

Cenários cobertos:
  A. Material recebido ÍNTEGRO  → concluido SEM Parashoot chamado
  B. Material recebido com DIVERGÊNCIA DE CONTAGEM → reprovado (auditoria_falhou)
  C. Cartão físico normal (origem='cartao') → fluxo COM Parashoot (mockado)

Princípio de segurança:
  - Bancos e pastas criados em /tmp — nunca toca no laboratório nem em dados reais.
  - O Parashoot NÃO é invocado de verdade: o cenário C moca a chamada e verifica
    que a função teria sido chamada (sem executar o binário).

Uso:
    python3 /tmp/teste_recebidos_auditoria.py
"""

import os
import sys
import json
import sqlite3
import tempfile
import shutil
import unittest
from unittest.mock import patch, MagicMock

# Adiciona a raiz do GMA ao path para importar os módulos
RAIZ_GMA = "/Users/serafa/GMA"
sys.path.insert(0, RAIZ_GMA)

# Pré-requisito: inicializar as variáveis de ambiente para o banco de testes
# (sobrescrito abaixo por cada teste com um banco isolado em /tmp)
os.environ.setdefault("GMA_DB", "/tmp/gma_teste_auditoria_fatia5.db")


def _criar_banco_teste(caminho_banco):
    """
    Cria um banco SQLite mínimo em /tmp com o schema necessário para os testes.
    Retorna uma conexão aberta (row_factory = sqlite3.Row).
    """
    conn = sqlite3.connect(caminho_banco)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")

    # Schema mínimo — apenas as colunas que a auditoria lê/escreve
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cartoes (
            id                              INTEGER PRIMARY KEY AUTOINCREMENT,
            volume                          TEXT NOT NULL DEFAULT '',
            caminho_origem                  TEXT NOT NULL DEFAULT '',
            numero_cartao                   TEXT,
            destino_pasta                   TEXT,
            total_arquivos_transferidos     INTEGER,
            tamanho_transferido_bytes       INTEGER,
            status                          TEXT NOT NULL DEFAULT 'transferencia_ok',
            origem_material                 TEXT NOT NULL DEFAULT 'cartao',
            criado_em                       TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            atualizado_em                   TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS eventos (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            tipo         TEXT NOT NULL,
            descricao    TEXT,
            cartao_id    INTEGER,
            dados        TEXT,
            criado_em    TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        )
    """)

    conn.commit()
    return conn


def _inserir_cartao(conn, numero, destino, total_arq, total_bytes,
                    status="transferencia_ok", origem="cartao", volume="VOL_TESTE"):
    """Insere um cartão de teste e retorna o id gerado."""
    cursor = conn.execute(
        """INSERT INTO cartoes
           (volume, caminho_origem, numero_cartao, destino_pasta,
            total_arquivos_transferidos, tamanho_transferido_bytes,
            status, origem_material)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (volume, f"/Volumes/{volume}", numero, destino,
         total_arq, total_bytes, status, origem)
    )
    conn.commit()
    return cursor.lastrowid


def _criar_pasta_destino_com_arquivos(raiz_tmp, nome_pasta, nomes_arquivos, tamanho_por_arquivo=1024):
    """
    Cria uma pasta temporária em /tmp e popula com arquivos de mídia fictícios.
    Retorna (caminho_pasta, total_bytes_reais).
    """
    pasta = os.path.join(raiz_tmp, nome_pasta)
    os.makedirs(pasta, exist_ok=True)
    total_bytes = 0
    for nome in nomes_arquivos:
        caminho = os.path.join(pasta, nome)
        dados = b"X" * tamanho_por_arquivo
        with open(caminho, "wb") as f:
            f.write(dados)
        total_bytes += tamanho_por_arquivo
    return pasta, total_bytes


def _listar_eventos(conn, cartao_id):
    """Retorna todos os eventos de um cartão como lista de dicts."""
    rows = conn.execute(
        "SELECT tipo, descricao, dados FROM eventos WHERE cartao_id = ? ORDER BY id",
        (cartao_id,)
    ).fetchall()
    return [{"tipo": r["tipo"], "descricao": r["descricao"],
             "dados": json.loads(r["dados"]) if r["dados"] else {}} for r in rows]


def _status_cartao(conn, cartao_id):
    """Retorna o status atual do cartão no banco."""
    row = conn.execute("SELECT status FROM cartoes WHERE id = ?", (cartao_id,)).fetchone()
    return row["status"] if row else None


# ── MONKEYPATCH: funções do banco_dados que usam o GMA_DB global ───────────────

def _patch_banco(conn_teste):
    """
    Retorna um contexto que redireciona banco_dados.obter_conexao e as funções
    de escrita para o banco de teste isolado — sem tocar no gma.db real.
    """
    import banco_dados as bd

    def _atualizar(conn_ignorado, cartao_id, campos):
        """Replica atualizar_cartao no banco de teste."""
        if not campos:
            return False
        colunas = ", ".join(f"{c} = ?" for c in campos)
        valores = list(campos.values()) + [cartao_id]
        conn_teste.execute(f"UPDATE cartoes SET {colunas} WHERE id = ?", valores)
        conn_teste.commit()
        return True

    def _registrar(conn_ignorado, tipo, descricao, cartao_id=None, dados=None):
        """Replica registrar_evento no banco de teste."""
        dados_json = json.dumps(dados, ensure_ascii=False) if dados else None
        conn_teste.execute(
            "INSERT INTO eventos (tipo, descricao, cartao_id, dados) VALUES (?,?,?,?)",
            (tipo, descricao, cartao_id, dados_json)
        )
        conn_teste.commit()

    return patch.multiple(
        bd,
        atualizar_cartao=_atualizar,
        registrar_evento=_registrar,
    )


# ══════════════════════════════════════════════════════════════════════════════
# TESTES
# ══════════════════════════════════════════════════════════════════════════════

class TestAuditoriaRecebidos(unittest.TestCase):

    def setUp(self):
        """Cria ambiente isolado em /tmp para cada teste."""
        self.tmp = tempfile.mkdtemp(prefix="gma_audit_test_")
        caminho_banco = os.path.join(self.tmp, "gma_teste.db")
        self.conn = _criar_banco_teste(caminho_banco)

        # Importa auditoria DEPOIS de configurar o ambiente (path já no sys.path)
        import auditoria as aud
        self.aud = aud

    def tearDown(self):
        """Remove tudo em /tmp após cada teste."""
        try:
            self.conn.close()
        except Exception:
            pass
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ── Cenário A: recebido íntegro → concluido SEM Parashoot ─────────────────

    def test_A_recebido_integro_concluido_sem_parashoot(self):
        """
        Dado: cartão com origem='recebido', destino íntegro (contagem e tamanho batem).
        Esperado:
          - status → 'concluido'
          - evento 'auditoria_recebido_concluida' no Log com motivo explicando o desvio
          - Parashoot NÃO chamado (sem chamada a _rodar_parashoot nem a subprocess)
        """
        # Prepara pasta de destino com 3 arquivos de vídeo
        arquivos = ["clip001.mp4", "clip002.mp4", "clip003.mp4"]
        pasta_destino, total_bytes = _criar_pasta_destino_com_arquivos(
            self.tmp, "RECEBIDO_001", arquivos, tamanho_por_arquivo=500_000
        )

        cartao_id = _inserir_cartao(
            self.conn,
            numero="REC_001",
            destino=pasta_destino,
            total_arq=3,
            total_bytes=total_bytes,
            origem="recebido",
            volume="",  # sem volume físico
        )

        # Monta o dict que auditar_cartao recebe (simula o SELECT do loop)
        cartao_row = self.conn.execute(
            """SELECT id, numero_cartao, destino_pasta, volume,
                      total_arquivos_transferidos, tamanho_transferido_bytes,
                      origem_material
               FROM cartoes WHERE id = ?""",
            (cartao_id,)
        ).fetchone()

        parashoot_chamado = []

        def _parashoot_mock(subcomando, mount, destino, timeout):
            parashoot_chamado.append(subcomando)
            return {"ok": True, "missing": 0, "total": 3, "found": 3, "raw": {}, "erro": ""}

        with _patch_banco(self.conn):
            with patch.object(self.aud, "_rodar_parashoot", side_effect=_parashoot_mock):
                resultado = self.aud.auditar_cartao(cartao_row, self.conn)

        # Resultado: aprovado
        self.assertTrue(resultado, "auditar_cartao deve retornar True para recebido íntegro")

        # Status no banco: concluido
        self.assertEqual(_status_cartao(self.conn, cartao_id), "concluido",
                         "Status deve ser 'concluido'")

        # Evento registrado
        eventos = _listar_eventos(self.conn, cartao_id)
        tipos = [e["tipo"] for e in eventos]
        self.assertIn("auditoria_recebido_concluida", tipos,
                      "Deve registrar evento 'auditoria_recebido_concluida'")

        # O evento deve explicar que o Parashoot foi ignorado
        evt = next(e for e in eventos if e["tipo"] == "auditoria_recebido_concluida")
        dados = evt["dados"]
        self.assertIn("recebido", dados.get("motivo_sem_parashoot", "").lower(),
                      "O campo motivo_sem_parashoot deve mencionar 'recebido'")

        # Parashoot NÃO deve ter sido chamado
        self.assertEqual(parashoot_chamado, [],
                         f"Parashoot NÃO deve ser chamado para material recebido. "
                         f"Chamadas: {parashoot_chamado}")

        print("[OK] Cenário A: recebido íntegro → concluido SEM Parashoot")

    # ── Cenário B: recebido com divergência de contagem → reprovado ───────────

    def test_B_recebido_contagem_divergente_reprovado(self):
        """
        Dado: cartão com origem='recebido', mas destino tem 2 arquivos e o banco
              registra 3 esperados (arquivo sumiu entre a cópia e a auditoria).
        Esperado:
          - status permanece 'transferencia_ok' (NÃO muda — cartão bloqueado)
          - evento 'auditoria_falhou' no Log com o motivo da divergência
          - Parashoot NÃO chamado
        """
        # Destino tem só 2 arquivos (1 sumiu)
        arquivos = ["clip001.mp4", "clip002.mp4"]
        pasta_destino, total_bytes = _criar_pasta_destino_com_arquivos(
            self.tmp, "RECEBIDO_002", arquivos, tamanho_por_arquivo=500_000
        )

        cartao_id = _inserir_cartao(
            self.conn,
            numero="REC_002",
            destino=pasta_destino,
            total_arq=3,          # banco esperava 3
            total_bytes=total_bytes + 500_000,  # e mais 500 KB
            origem="recebido",
            volume="",
        )

        cartao_row = self.conn.execute(
            """SELECT id, numero_cartao, destino_pasta, volume,
                      total_arquivos_transferidos, tamanho_transferido_bytes,
                      origem_material
               FROM cartoes WHERE id = ?""",
            (cartao_id,)
        ).fetchone()

        parashoot_chamado = []

        def _parashoot_mock(subcomando, mount, destino, timeout):
            parashoot_chamado.append(subcomando)
            return {"ok": True, "missing": 0, "total": 0, "found": 0, "raw": {}, "erro": ""}

        with _patch_banco(self.conn):
            with patch.object(self.aud, "_rodar_parashoot", side_effect=_parashoot_mock):
                resultado = self.aud.auditar_cartao(cartao_row, self.conn)

        # Resultado: reprovado
        self.assertFalse(resultado, "auditar_cartao deve retornar False com divergência")

        # Status NÃO deve ter mudado (cartão bloqueado em transferencia_ok)
        self.assertEqual(_status_cartao(self.conn, cartao_id), "transferencia_ok",
                         "Status deve permanecer 'transferencia_ok' ao reprovar")

        # Evento de falha registrado
        eventos = _listar_eventos(self.conn, cartao_id)
        tipos = [e["tipo"] for e in eventos]
        self.assertIn("auditoria_falhou", tipos,
                      "Deve registrar evento 'auditoria_falhou'")

        # Parashoot NÃO deve ter sido chamado
        self.assertEqual(parashoot_chamado, [],
                         f"Parashoot NÃO deve ser chamado mesmo ao reprovar. "
                         f"Chamadas: {parashoot_chamado}")

        print("[OK] Cenário B: recebido com divergência → reprovado SEM Parashoot")

    # ── Cenário C: cartão físico normal → fluxo COM Parashoot mockado ─────────

    def test_C_cartao_fisico_parashoot_chamado(self):
        """
        Dado: cartão com origem='cartao' (fluxo normal), destino íntegro,
              volume montado (mockado via os.path.isdir).
        Esperado:
          - status → 'concluido' (ou 'verificado_parashoot' no caminho intermediário)
          - Parashoot 'check' E 'erase' SÃO chamados (mocked)
          - evento 'auditoria_concluida' no Log (NÃO 'auditoria_recebido_concluida')
        """
        arquivos = ["footage_A.mp4", "footage_B.mp4"]
        pasta_destino, total_bytes = _criar_pasta_destino_com_arquivos(
            self.tmp, "CARTAO_001", arquivos, tamanho_por_arquivo=2_000_000
        )

        volume = "EOS_DIGITAL_TESTE"
        mount_esperado = f"/Volumes/{volume}"

        cartao_id = _inserir_cartao(
            self.conn,
            numero="JOAO_001",
            destino=pasta_destino,
            total_arq=2,
            total_bytes=total_bytes,
            origem="cartao",
            volume=volume,
        )

        cartao_row = self.conn.execute(
            """SELECT id, numero_cartao, destino_pasta, volume,
                      total_arquivos_transferidos, tamanho_transferido_bytes,
                      origem_material
               FROM cartoes WHERE id = ?""",
            (cartao_id,)
        ).fetchone()

        parashoot_chamadas = []

        def _parashoot_mock(subcomando, mount, destino, timeout):
            parashoot_chamadas.append(subcomando)
            if subcomando == "check":
                return {"ok": True, "missing": -1, "total": 0, "found": 0, "raw": [{"status": "check_complete"}], "erro": ""}
            if subcomando == "erase":
                return {"ok": True, "missing": -1, "total": 0, "found": 0, "raw": [{"status": "erase_complete"}], "erro": ""}
            return {"ok": False, "missing": -1, "total": 0, "found": 0, "raw": {}, "erro": "subcomando desconhecido"}

        def _isdir_mock(caminho):
            """Faz o mountpoint do cartão 'existir' sem cartão real."""
            if caminho == mount_esperado:
                return True
            # Para a pasta de destino, usa o os.path.isdir real
            return os.path.isdir.__wrapped__(caminho) if hasattr(os.path.isdir, "__wrapped__") else _isdir_real(caminho)

        _isdir_real = os.path.isdir

        def _isdir_seletivo(caminho):
            if caminho == mount_esperado:
                return True
            return _isdir_real(caminho)

        with _patch_banco(self.conn):
            with patch.object(self.aud, "_rodar_parashoot", side_effect=_parashoot_mock):
                with patch.object(self.aud, "_parashoot_disponivel", return_value=True):
                    with patch("os.path.isdir", side_effect=_isdir_seletivo):
                        resultado = self.aud.auditar_cartao(cartao_row, self.conn)

        # Resultado: aprovado
        self.assertTrue(resultado, "auditar_cartao deve retornar True para cartão físico OK")

        # Status: concluido
        self.assertEqual(_status_cartao(self.conn, cartao_id), "concluido",
                         "Status deve ser 'concluido'")

        # Parashoot check E erase DEVEM ter sido chamados (nessa ordem)
        self.assertIn("check", parashoot_chamadas,
                      "Parashoot 'check' deve ser chamado para cartão físico")
        self.assertIn("erase", parashoot_chamadas,
                      "Parashoot 'erase' deve ser chamado para cartão físico")
        self.assertEqual(parashoot_chamadas.index("check"),
                         parashoot_chamadas.index("erase") - 1,
                         "check deve vir ANTES do erase")

        # Evento: auditoria_concluida (e NÃO auditoria_recebido_concluida)
        eventos = _listar_eventos(self.conn, cartao_id)
        tipos = [e["tipo"] for e in eventos]
        self.assertIn("auditoria_concluida", tipos,
                      "Deve registrar 'auditoria_concluida' para cartão físico")
        self.assertNotIn("auditoria_recebido_concluida", tipos,
                         "NÃO deve registrar 'auditoria_recebido_concluida' para cartão físico")

        print("[OK] Cenário C: cartão físico → Parashoot chamado (check + erase)")


# ── PONTO DE ENTRADA ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 70)
    print("Teste Fatia 5 — Auditoria de material recebido (Camada 4)")
    print("=" * 70)
    loader = unittest.TestLoader()
    # Garante ordem A → B → C
    loader.sortTestMethodsUsing = lambda a, b: (a > b) - (a < b)
    suite = loader.loadTestsFromTestCase(TestAuditoriaRecebidos)
    runner = unittest.TextTestRunner(verbosity=2)
    resultado = runner.run(suite)
    sys.exit(0 if resultado.wasSuccessful() else 1)
