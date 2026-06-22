"""
Teste do "bilhete de status" do exportador do Google Sheets (s46).

O que cobre:
  - o exportador classifica corretamente "login vencido" (sessão do gcloud
    expirada) vs. outros erros;
  - grava o bilhete (.gma_sheets_status.json) com troca atômica;
  - o Painel lê o bilhete e o traduz na bolinha certa (🟢/🔴/🟡), ignorando
    bilhete velho ou de outro projeto.

Rodar:  /usr/bin/python3 teste_status_sheets.py
"""

import json
import os
from datetime import datetime, timedelta

import exportador_sheets as ex
import flask_gma as fg

CAMINHO = ex.ARQUIVO_STATUS
falhas = []


def checa(cond, nome):
    print(("  OK  " if cond else " FALHA ") + nome)
    if not cond:
        falhas.append(nome)


def _grava(estado, projeto, quando, mensagem="x"):
    with open(CAMINHO, "w", encoding="utf-8") as f:
        json.dump({"estado": estado, "mensagem": mensagem, "projeto": projeto,
                   "horario": "10:00:00",
                   "quando": quando.isoformat(timespec="seconds")}, f)


print("\n== Classificador de login vencido ==")
sim = [
    "Reauthentication failed. cannot prompt during non-interactive execution",
    "Falha ao gerar token de impersonação: invalid_grant: Token has expired",
    "please run gcloud auth login to continue",
]
nao = [
    "APIError: 404 spreadsheet not found",
    "Quota exceeded for quota metric writes",
    "Connection reset by peer",
]
checa(all(ex._erro_eh_login_vencido(c) for c in sim), "detecta login vencido")
checa(not any(ex._erro_eh_login_vencido(c) for c in nao), "não dá falso positivo")

print("\n== Gravação do bilhete (troca atômica) ==")
ex._escrever_status("login-vencido", "teste")
with open(CAMINHO, encoding="utf-8") as f:
    b = json.load(f)
checa(b["estado"] == "login-vencido", "estado gravado")
checa("horario" in b and "quando" in b, "carimbo de tempo presente")
checa(not os.path.exists(CAMINHO + ".tmp"), "arquivo temporário foi removido")

print("\n== Leitura/tradução pelo Painel ==")
agora = datetime.now()

_grava("login-vencido", "sp2b", agora)
r = fg._status_sheets_bilhete("sp2b")
checa(r is not None and r[0] == "erro", "login vencido -> bolinha vermelha")

_grava("ok", "sp2b", agora)
r = fg._status_sheets_bilhete("sp2b")
checa(r is not None and r[0] == "ok", "ok -> bolinha verde")

_grava("sem-internet", "sp2b", agora)
r = fg._status_sheets_bilhete("sp2b")
checa(r is not None and r[0] == "aviso", "sem internet -> bolinha amarela")

_grava("ok", "rock_in_rio", agora)
checa(fg._status_sheets_bilhete("sp2b") is None, "bilhete de outro projeto é ignorado")

_grava("ok", "sp2b", agora - timedelta(minutes=10))
checa(fg._status_sheets_bilhete("sp2b") is None, "bilhete velho (>5min) é ignorado")

# limpeza
if os.path.exists(CAMINHO):
    os.remove(CAMINHO)

print()
if falhas:
    print(f"== {len(falhas)} FALHA(S): " + "; ".join(falhas))
    raise SystemExit(1)
print("== TODOS OS TESTES PASSARAM ==")
