"""
Verificação da Fatia 2 do login (Camada 5): o CARIMBO do operador no log de eventos.
  - banco_dados: coluna operador, registrar_evento carimba o contexto, migração, listar
  - flask_gma: o before_request leva o operador logado ao contexto do banco

Isolado: GMA_DB/GMA_OPERADORES em pasta temporária ANTES de importar (lição da s48).
"""
import os
import sqlite3
import tempfile

_TMP = tempfile.mkdtemp(prefix="gma_teste_carimbo_")
os.environ["GMA_DB"] = os.path.join(_TMP, "gma.db")
os.environ["GMA_OPERADORES"] = os.path.join(_TMP, "operadores.json")
os.environ["GMA_SECRET"] = "segredo-de-teste-fixo"
os.environ["GMA_SENHA"] = ""

import banco_dados as bd

ok = True
def checa(cond, nome):
    global ok
    print(("  ✅" if cond else "  ❌") + " " + nome)
    ok = ok and cond

print("PARTE 1 — carimbo no banco_dados:")
conn = bd.inicializar_banco()

cols = {r[1] for r in conn.execute("PRAGMA table_info(eventos)")}
checa("operador" in cols, "tabela eventos tem a coluna operador")

# Sem contexto → NULL (ação do sistema)
bd.definir_operador_contexto(None)
e1 = bd.registrar_evento(conn, "teste", "ação automática")
op1 = conn.execute("SELECT operador FROM eventos WHERE id=?", (e1,)).fetchone()[0]
checa(op1 is None, "sem contexto → operador NULL (sistema)")

# Com contexto → carimba o nome
bd.definir_operador_contexto("Alexandre")
e2 = bd.registrar_evento(conn, "teste", "ação do operador")
op2 = conn.execute("SELECT operador FROM eventos WHERE id=?", (e2,)).fetchone()[0]
checa(op2 == "Alexandre", "com contexto → carimba o operador")

# Parâmetro explícito vence o contexto
e3 = bd.registrar_evento(conn, "teste", "explícito", operador="Bruna")
op3 = conn.execute("SELECT operador FROM eventos WHERE id=?", (e3,)).fetchone()[0]
checa(op3 == "Bruna", "operador explícito vence o contexto")

# Limpar o contexto volta a NULL
bd.definir_operador_contexto(None)
e4 = bd.registrar_evento(conn, "teste", "de novo automático")
op4 = conn.execute("SELECT operador FROM eventos WHERE id=?", (e4,)).fetchone()[0]
checa(op4 is None, "limpar o contexto volta a NULL")

# listar_eventos: mais novo primeiro, traz o operador
evs = bd.listar_eventos(conn, limite=10)
checa(len(evs) >= 4 and evs[0]["id"] > evs[1]["id"], "listar_eventos: mais recente primeiro")
checa("operador" in evs[0], "listar_eventos traz o campo operador")
conn.close()

print("PARTE 2 — migração de banco antigo (sem a coluna):")
caminho_velho = os.path.join(_TMP, "velho.db")
c = sqlite3.connect(caminho_velho)
c.execute("""CREATE TABLE eventos (id INTEGER PRIMARY KEY AUTOINCREMENT,
             tipo TEXT NOT NULL, cartao_id INTEGER, formulario_id INTEGER,
             descricao TEXT NOT NULL, dados_json TEXT,
             criado_em TEXT NOT NULL DEFAULT (datetime('now','localtime')))""")
c.commit()
antes = {r[1] for r in c.execute("PRAGMA table_info(eventos)")}
checa("operador" not in antes, "banco velho começa SEM a coluna operador")
bd.migrar_schema_eventos(c)
depois = {r[1] for r in c.execute("PRAGMA table_info(eventos)")}
checa("operador" in depois, "migração adiciona a coluna operador")
bd.migrar_schema_eventos(c)  # idempotente
checa(True, "migração roda 2x sem erro (idempotente)")
c.close()

print("PARTE 3 — fiação no Flask (before_request leva o operador ao contexto):")
import flask_gma
flask_gma.app.testing = True
cl = flask_gma.app.test_client()
# cria o 1º operador e loga
cl.post("/login", data={"nome": "Alexandre", "senha": "segredo1", "senha2": "segredo1"})

# captura o que o before_request manda ao contexto do banco
capturado = []
orig = bd.definir_operador_contexto
bd.definir_operador_contexto = lambda nome: capturado.append(nome)
try:
    r = cl.get("/historico")
    checa(r.status_code == 200, "/historico abre logado (200)")
    checa(capturado and capturado[-1] == "Alexandre",
          "logado: o contexto recebe o operador da sessão")

    # cliente anônimo (sem login): contexto recebe None
    capturado.clear()
    anon = flask_gma.app.test_client()
    anon.get("/login")  # rota livre; o before_request roda mesmo assim
    checa(capturado and capturado[-1] is None,
          "anônimo: o contexto recebe None (sistema)")
finally:
    bd.definir_operador_contexto = orig

import shutil
shutil.rmtree(_TMP, ignore_errors=True)
print()
print("RESULTADO:", "TODOS PASSARAM ✅" if ok else "ALGO FALHOU ❌")
import sys; sys.exit(0 if ok else 1)
