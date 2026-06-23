"""
Verificação da Fatia 1 do login do operador (Camada 5):
  - operadores.py: armazém global (criar, conferir senha, duplicado, desativar…)
  - flask_gma.py: a porta (barreira na base, /login, /operadores, remoto intacto)

Tudo ISOLADO: GMA_OPERADORES e GMA_DB apontam para arquivos temporários ANTES de
qualquer import do GMA (lição da s48 — nunca tocar nos dados reais no teste).
"""
import os
import tempfile

_TMP = tempfile.mkdtemp(prefix="gma_teste_login_")
os.environ["GMA_OPERADORES"] = os.path.join(_TMP, "operadores.json")
os.environ["GMA_DB"] = os.path.join(_TMP, "gma.db")
os.environ["GMA_SECRET"] = "segredo-de-teste-fixo"
os.environ["GMA_SENHA"] = ""  # sem Basic Auth no teste

import operadores

ok = True
def checa(cond, nome):
    global ok
    print(("  ✅" if cond else "  ❌") + " " + nome)
    ok = ok and cond

print("PARTE 1 — armazém operadores.py:")
checa(operadores.existe_algum() is False, "começa vazio (existe_algum=False)")
checa(operadores.listar() == [], "lista vazia no começo")

op = operadores.criar("Alexandre", "segredo1")
checa(op["nome"] == "Alexandre" and "senha" not in op, "criar devolve operador SEM o hash")
checa(operadores.existe_algum() is True, "depois de criar, existe_algum=True")

# senha nunca em texto puro no arquivo
import json
with open(os.environ["GMA_OPERADORES"], encoding="utf-8") as f:
    bruto = f.read()
checa("segredo1" not in bruto, "a senha NÃO aparece em texto puro no arquivo")
checa("pbkdf2_sha256$" in bruto, "a senha é guardada como hash pbkdf2")

checa(operadores.verificar("Alexandre", "segredo1") is not None, "senha certa → entra")
checa(operadores.verificar("Alexandre", "errada") is None, "senha errada → não entra")
checa(operadores.verificar("alexandre", "segredo1") is not None, "nome não diferencia maiúsc./minúsc.")
checa(operadores.verificar("Fulano", "x") is None, "nome inexistente → não entra")

try:
    operadores.criar("Alexandre", "outra")
    checa(False, "criar duplicado deveria falhar")
except ValueError:
    checa(True, "criar nome duplicado → ValueError")
try:
    operadores.criar("Curto", "ab")
    checa(False, "senha curta deveria falhar")
except ValueError:
    checa(True, "senha curta demais → ValueError")

operadores.criar("Bruna", "segredo2")
checa(len(operadores.listar()) == 2, "agora há 2 operadores ativos")
operadores.desativar("Bruna")
checa(len(operadores.listar()) == 1, "desativar tira da lista de ativos")
checa(operadores.verificar("Bruna", "segredo2") is None, "operador desativado não entra")
operadores.reativar("Bruna")
checa(operadores.verificar("Bruna", "segredo2") is not None, "reativar volta a deixar entrar")
operadores.trocar_senha("Bruna", "novasenha")
checa(operadores.verificar("Bruna", "novasenha") is not None and
      operadores.verificar("Bruna", "segredo2") is None, "trocar senha funciona")

# Zera o armazém para o teste de bootstrap do Flask começar do vazio.
os.remove(os.environ["GMA_OPERADORES"])

print("PARTE 2 — a porta no Flask (test client):")
import flask_gma
flask_gma.app.testing = True
c = flask_gma.app.test_client()

# Sem login: rota de operação redireciona para /login (gate roda ANTES da rota).
r = c.get("/painel")
checa(r.status_code == 302 and "/login" in r.headers.get("Location", ""),
      "sem login: /painel redireciona para /login")
r = c.get("/")
checa(r.status_code == 302 and "/login" in r.headers.get("Location", ""),
      "sem login: / redireciona para /login")

# /login (bootstrap) abre sem login e oferece criar o primeiro operador.
r = c.get("/login")
checa(r.status_code == 200 and "Primeiro acesso" in r.get_data(as_text=True),
      "/login no vazio mostra o bootstrap (criar 1º operador)")

# Remoto (Host de fora) NUNCA vê o login: cai na ficha (/) ou 403 (/operadores).
r = c.get("/", headers={"Host": "exemplo.com"})
checa(r.status_code == 302 and "/ficha" in r.headers.get("Location", ""),
      "remoto em / vai pra /ficha (não pro login)")
r = c.get("/operadores", headers={"Host": "exemplo.com"})
checa(r.status_code == 403, "remoto em /operadores recebe 403 (login não exposto)")

# Cria o primeiro operador pelo /login e entra.
r = c.post("/login", data={"nome": "Alexandre", "senha": "segredo1", "senha2": "segredo1"})
checa(r.status_code == 302 and r.headers.get("Location", "").endswith("/"),
      "criar 1º operador loga e redireciona pra /")

# Logado: /operadores abre (rota protegida, sem tocar no banco) e mostra o nome.
r = c.get("/operadores")
checa(r.status_code == 200 and "Alexandre" in r.get_data(as_text=True),
      "logado: /operadores abre e mostra o operador")

# Senha errada não entra (sessão nova).
c2 = flask_gma.app.test_client()
r = c2.post("/login", data={"nome": "Alexandre", "senha": "ERRADA"})
checa(r.status_code == 200 and "incorretos" in r.get_data(as_text=True),
      "login com senha errada → fica na tela com erro")

# Sair derruba a sessão: volta a ser barrado.
r = c.get("/logout")
checa(r.status_code == 302 and "/login" in r.headers.get("Location", ""), "sair redireciona pra /login")
r = c.get("/operadores")
checa(r.status_code == 302 and "/login" in r.headers.get("Location", ""),
      "depois de sair, /operadores volta a barrar")

import shutil
shutil.rmtree(_TMP, ignore_errors=True)
print()
print("RESULTADO:", "TODOS PASSARAM ✅" if ok else "ALGO FALHOU ❌")
import sys; sys.exit(0 if ok else 1)
