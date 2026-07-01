#!/usr/bin/env python3
"""
operadores.py
Camada 5 do GMA — armazém GLOBAL dos operadores (login do operador).

O QUE É (em português claro):
  Os operadores são a EQUIPE que opera a base — as mesmas pessoas de evento para
  evento. Por isso eles vivem num lugar ÚNICO e GLOBAL (um arquivo na raiz do GMA),
  e não dentro de cada projeto: você cadastra o operador UMA vez e ele vale em todos
  os projetos, sem recadastrar (com senha!) a cada evento.

O QUE GUARDA:
  Para cada operador: o nome e a SENHA — mas a senha NUNCA em texto puro. Guardamos
  só um "resumo embaralhado" dela (hash pbkdf2, da biblioteca padrão do Python — nada
  a instalar). Dá para CONFERIR uma senha digitada contra o resumo, mas não dá para
  voltar do resumo à senha. Se o arquivo vazar, as senhas não vão junto.

SEGURANÇA:
  - O arquivo `operadores.json` fica FORA do git (.gitignore) por conter os hashes.
  - Hash = pbkdf2_hmac(sha256) com sal aleatório por operador + muitas iterações.
  - A conferência usa hmac.compare_digest (tempo constante, não vaza por timing).

Este módulo é só o ARMAZÉM (dados + senha). A tela de login, a sessão e a barreira
de acesso ficam no Flask (flask_gma.py). Sem efeitos colaterais ao importar.
"""

import hashlib
import hmac
import json
import os
import secrets
from datetime import datetime

# Raiz do GMA (mesma do resto do sistema). O caminho do arquivo pode ser trocado
# por GMA_OPERADORES — usado pelos testes para não tocar no arquivo real.
RAIZ_GMA = os.path.dirname(os.path.abspath(__file__))

# Parâmetros do hash de senha. 200 mil iterações = lento o bastante para azedar
# ataque de força bruta, rápido o bastante para um login instantâneo.
_ITERACOES = 200_000
_TAM_SAL = 16

# Regras mínimas (leves — é uma ferramenta local de confiança, não um banco).
TAM_MIN_SENHA = 4


def _caminho():
    """Caminho do arquivo de operadores (trocável por GMA_OPERADORES nos testes)."""
    env = os.environ.get("GMA_OPERADORES", "").strip()
    return env if env else os.path.join(RAIZ_GMA, "operadores.json")


# ── Armazenamento (JSON atômico) ────────────────────────────────────────────────

def _carregar():
    """Lê o arquivo de operadores. Se não existe ou está corrompido, começa vazio."""
    caminho = _caminho()
    if not os.path.isfile(caminho):
        return {"operadores": [], "proximo_id": 1}
    try:
        with open(caminho, "r", encoding="utf-8") as f:
            dados = json.load(f)
        dados.setdefault("operadores", [])
        dados.setdefault("proximo_id", len(dados["operadores"]) + 1)
        return dados
    except (json.JSONDecodeError, OSError):
        # Arquivo ilegível não pode trancar o sistema: trata como vazio (o bootstrap
        # do login deixa criar o primeiro operador de novo).
        return {"operadores": [], "proximo_id": 1}


def _salvar(dados):
    """Grava o arquivo com troca atômica (os.replace) — nunca deixa meio-escrito."""
    caminho = _caminho()
    tmp = caminho + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)
    os.replace(tmp, caminho)


# ── Senha (hash pbkdf2 + conferência em tempo constante) ────────────────────────

def _hash_senha(senha, sal=None):
    """Devolve a string guardável 'pbkdf2_sha256$iter$sal_hex$hash_hex'."""
    if sal is None:
        sal = secrets.token_bytes(_TAM_SAL)
    digesto = hashlib.pbkdf2_hmac("sha256", senha.encode("utf-8"), sal, _ITERACOES)
    return f"pbkdf2_sha256${_ITERACOES}${sal.hex()}${digesto.hex()}"


def _conferir_hash(senha, guardado):
    """True se a senha digitada bate com o hash guardado. Falha fechada (False)."""
    try:
        algoritmo, iteracoes, sal_hex, hash_hex = guardado.split("$")
        if algoritmo != "pbkdf2_sha256":
            return False
        sal = bytes.fromhex(sal_hex)
        calc = hashlib.pbkdf2_hmac("sha256", senha.encode("utf-8"), sal, int(iteracoes))
        return hmac.compare_digest(calc.hex(), hash_hex)
    except (ValueError, AttributeError):
        return False


# ── API pública ─────────────────────────────────────────────────────────────────

# Papéis de acesso: "operador" = base inteira; "editor" = só a aba Entrega.
PAPEIS = ("operador", "editor")


def _publico(op):
    """Versão de um operador SEM o hash da senha (segura para telas/respostas)."""
    return {"id": op["id"], "nome": op["nome"],
            "ativo": op.get("ativo", True), "criado_em": op.get("criado_em", ""),
            # Contas antigas (sem o campo) são operadores por padrão.
            "papel": op.get("papel", "operador")}


def existe_algum():
    """True se há QUALQUER operador cadastrado (ativo ou não). Guia o bootstrap."""
    return len(_carregar()["operadores"]) > 0


def listar(incluir_inativos=False):
    """Lista os operadores (sem o hash). Por padrão só os ativos, ordenados por nome."""
    ops = _carregar()["operadores"]
    if not incluir_inativos:
        ops = [o for o in ops if o.get("ativo", True)]
    return sorted((_publico(o) for o in ops), key=lambda o: o["nome"].lower())


def _achar(dados, nome):
    """Acha o registro cru (com hash) pelo nome, sem diferenciar maiúsc./minúsc."""
    alvo = (nome or "").strip().lower()
    for o in dados["operadores"]:
        if o["nome"].strip().lower() == alvo:
            return o
    return None


def criar(nome, senha, papel="operador"):
    """
    Cadastra uma conta nova. `papel` = "operador" (base inteira) ou "editor" (só a
    aba Entrega). Levanta ValueError se o nome estiver vazio/duplicado, a senha for
    curta demais ou o papel for inválido. Devolve a conta (sem o hash).
    """
    nome = (nome or "").strip()
    senha = senha or ""
    papel = (papel or "operador").strip().lower()
    if not nome:
        raise ValueError("O nome não pode ficar em branco.")
    if papel not in PAPEIS:
        raise ValueError("Papel inválido (use operador ou editor).")
    if len(senha) < TAM_MIN_SENHA:
        raise ValueError(f"A senha precisa ter pelo menos {TAM_MIN_SENHA} caracteres.")

    dados = _carregar()
    if _achar(dados, nome) is not None:
        raise ValueError(f"Já existe alguém chamado “{nome}”.")

    op = {
        "id": dados["proximo_id"],
        "nome": nome,
        "senha": _hash_senha(senha),
        "ativo": True,
        "papel": papel,
        "criado_em": datetime.now().isoformat(timespec="seconds"),
    }
    dados["operadores"].append(op)
    dados["proximo_id"] += 1
    _salvar(dados)
    return _publico(op)


def verificar(nome, senha):
    """
    Confere o login. Devolve o operador (sem hash) se o nome existe, está ATIVO e a
    senha bate; senão devolve None. É a única porta de entrada do login.
    """
    dados = _carregar()
    op = _achar(dados, nome)
    if op is None or not op.get("ativo", True):
        return None
    if _conferir_hash(senha or "", op.get("senha", "")):
        return _publico(op)
    return None


def desativar(nome):
    """Desativa um operador (soft-delete: preserva o histórico). True se mexeu."""
    dados = _carregar()
    op = _achar(dados, nome)
    if op is None or not op.get("ativo", True):
        return False
    op["ativo"] = False
    _salvar(dados)
    return True


def reativar(nome):
    """Religa um operador desativado. True se mexeu."""
    dados = _carregar()
    op = _achar(dados, nome)
    if op is None or op.get("ativo", True):
        return False
    op["ativo"] = True
    _salvar(dados)
    return True


def trocar_senha(nome, senha_nova):
    """Troca a senha de um operador existente. Levanta ValueError se curta demais."""
    if len(senha_nova or "") < TAM_MIN_SENHA:
        raise ValueError(f"A senha precisa ter pelo menos {TAM_MIN_SENHA} caracteres.")
    dados = _carregar()
    op = _achar(dados, nome)
    if op is None:
        raise ValueError(f"Operador “{nome}” não encontrado.")
    op["senha"] = _hash_senha(senha_nova)
    _salvar(dados)
    return True


if __name__ == "__main__":
    # Execução direta = diagnóstico rápido (não cria nada).
    print(f"Arquivo de operadores: {_caminho()}")
    print(f"Existe algum? {existe_algum()}")
    for o in listar(incluir_inativos=True):
        marca = "" if o["ativo"] else " (desativado)"
        print(f"  - {o['nome']}{marca}")
