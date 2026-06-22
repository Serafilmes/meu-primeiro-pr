"""
Testes de concluir_formulario_do_cartao (banco_dados) — o conserto do status do Post.

Contexto do bug: a auditoria marcava o CARTÃO como 'concluido' mas nunca avançava
o POST (formulário) ligado a ele, que ficava preso em 'matched' para sempre — então
a Nova Ficha mostrava o Post "em operação" mesmo já entregue. Esta função fecha o
descompasso, e estes testes garantem que ela:

  1. promove um Post 'matched' → 'concluido' quando o cartão conclui;
  2. registra o evento 'post_concluido' no Log;
  3. NÃO reabre um Post 'cancelado';
  4. é idempotente (Post já 'concluido' → não faz nada, não duplica evento);
  5. devolve None quando o cartão não tem match;
  6. promove outros estados "em andamento" (ex.: 'transferencia_ok');
  7. nunca levanta exceção (cartão inexistente → None).

Roda sem servidor Flask nem internet. Banco em memória (:memory:).
"""

import sys
import os
import unittest
import sqlite3

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import banco_dados as bd


def _banco_de_teste():
    """Banco em memória com só as tabelas que esta função toca."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE cartoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            status TEXT NOT NULL DEFAULT 'detectado',
            numero_cartao TEXT
        );
        CREATE TABLE formularios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'aguardando_match'
        );
        CREATE TABLE matches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cartao_id INTEGER NOT NULL,
            formulario_id INTEGER NOT NULL,
            score INTEGER NOT NULL DEFAULT 0,
            criterios TEXT,
            confirmado INTEGER NOT NULL DEFAULT 0,
            match_timestamp TEXT
        );
        CREATE TABLE eventos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tipo TEXT NOT NULL,
            cartao_id INTEGER,
            formulario_id INTEGER,
            descricao TEXT NOT NULL,
            dados_json TEXT,
            criado_em TEXT
        );
    """)
    return conn


def _montar(conn, status_form="matched", confirmado=1, com_match=True):
    """Cria 1 cartão concluído + 1 Post + (opcional) o match confirmado.

    Retorna (cartao_id, form_id).
    """
    cur = conn.execute(
        "INSERT INTO cartoes (status, numero_cartao) VALUES ('concluido', 'TESTE_001')"
    )
    cartao_id = cur.lastrowid
    cur = conn.execute(
        "INSERT INTO formularios (nome, status) VALUES ('FULANO', ?)", (status_form,)
    )
    form_id = cur.lastrowid
    if com_match:
        conn.execute(
            "INSERT INTO matches (cartao_id, formulario_id, confirmado) VALUES (?, ?, ?)",
            (cartao_id, form_id, confirmado),
        )
    conn.commit()
    return cartao_id, form_id


def _status_form(conn, form_id):
    return conn.execute(
        "SELECT status FROM formularios WHERE id = ?", (form_id,)
    ).fetchone()["status"]


def _eventos_post_concluido(conn):
    return conn.execute(
        "SELECT COUNT(*) AS n FROM eventos WHERE tipo = 'post_concluido'"
    ).fetchone()["n"]


class TestConcluirFormulario(unittest.TestCase):

    def setUp(self):
        self.conn = _banco_de_teste()

    def tearDown(self):
        self.conn.close()

    def test_promove_matched(self):
        """Post 'matched' + cartão concluído → 'concluido' e devolve o id."""
        cartao_id, form_id = _montar(self.conn, status_form="matched")
        ret = bd.concluir_formulario_do_cartao(self.conn, cartao_id)
        self.assertEqual(ret, form_id)
        self.assertEqual(_status_form(self.conn, form_id), "concluido")

    def test_registra_evento(self):
        """Promover grava exatamente um evento 'post_concluido' no Log."""
        cartao_id, form_id = _montar(self.conn, status_form="matched")
        bd.concluir_formulario_do_cartao(self.conn, cartao_id)
        self.assertEqual(_eventos_post_concluido(self.conn), 1)

    def test_nao_reabre_cancelado(self):
        """Post 'cancelado' NUNCA volta — fica cancelado e devolve None."""
        cartao_id, form_id = _montar(self.conn, status_form="cancelado")
        ret = bd.concluir_formulario_do_cartao(self.conn, cartao_id)
        self.assertIsNone(ret)
        self.assertEqual(_status_form(self.conn, form_id), "cancelado")
        self.assertEqual(_eventos_post_concluido(self.conn), 0)

    def test_idempotente_ja_concluido(self):
        """Post já 'concluido' → None, sem novo evento (pode chamar 2x sem efeito)."""
        cartao_id, form_id = _montar(self.conn, status_form="concluido")
        ret = bd.concluir_formulario_do_cartao(self.conn, cartao_id)
        self.assertIsNone(ret)
        self.assertEqual(_status_form(self.conn, form_id), "concluido")
        self.assertEqual(_eventos_post_concluido(self.conn), 0)

    def test_sem_match_devolve_none(self):
        """Cartão sem match confirmado → None, nada muda."""
        cartao_id, form_id = _montar(self.conn, status_form="matched", com_match=False)
        ret = bd.concluir_formulario_do_cartao(self.conn, cartao_id)
        self.assertIsNone(ret)
        self.assertEqual(_status_form(self.conn, form_id), "matched")

    def test_match_nao_confirmado_ignorado(self):
        """Match com confirmado=0 não conta como vínculo válido."""
        cartao_id, form_id = _montar(self.conn, status_form="matched", confirmado=0)
        ret = bd.concluir_formulario_do_cartao(self.conn, cartao_id)
        self.assertIsNone(ret)
        self.assertEqual(_status_form(self.conn, form_id), "matched")

    def test_promove_transferencia_ok(self):
        """Outros estados 'em andamento' (transferencia_ok) também concluem."""
        cartao_id, form_id = _montar(self.conn, status_form="transferencia_ok")
        ret = bd.concluir_formulario_do_cartao(self.conn, cartao_id)
        self.assertEqual(ret, form_id)
        self.assertEqual(_status_form(self.conn, form_id), "concluido")

    def test_cartao_inexistente_nao_quebra(self):
        """Cartão que não existe → None, sem exceção (a conclusão jamais quebra)."""
        ret = bd.concluir_formulario_do_cartao(self.conn, 99999)
        self.assertIsNone(ret)


if __name__ == "__main__":
    unittest.main(verbosity=2)
