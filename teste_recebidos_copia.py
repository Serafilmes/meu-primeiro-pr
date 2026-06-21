#!/usr/bin/env python3
"""
teste_recebidos_copia.py
Fatia 4 do arco "RECEBIDOS" — teste ponta a ponta da cópia de material satélite.

Cobre:
  (A) caminho feliz         — Post recebido + pronto → cópia OK → pasta renomeada
  (B) pasta vazia           — recusa com motivo 'pasta_vazia'
  (C) Post não-recebido     — recusa com motivo 'nao_e_recebido'
  (D) idempotência          — clicar "Copiar agora" 2× não duplica cópia

Segurança:
  - NUNCA toca no sp2b real (projetos/sp2b/gma.db nem /Users/serafa/GMA/RECEBIDOS/)
  - Trabalha sobre CÓPIAS em /tmp/gma_teste_recebidos_<id>/
  - O banco real e as pastas de mídia reais ficam intactos.

Uso:
    python3 /Users/serafa/GMA/teste_recebidos_copia.py

Pré-requisitos:
    pip install reportlab   (para gerar o PDF — mesmo pré-req do fluxo normal)
"""

import os
import sys
import json
import shutil
import sqlite3
import tempfile
import traceback
from datetime import datetime

# ── Aponta o Python para a raiz do GMA ────────────────────────────────────────

RAIZ_GMA = "/Users/serafa/GMA"
sys.path.insert(0, RAIZ_GMA)

# ── Pasta de trabalho isolada em /tmp ─────────────────────────────────────────

PASTA_TESTE = tempfile.mkdtemp(prefix="gma_teste_recebidos_")
print(f"\n{'='*60}")
print(f"  GMA — Fatia 4: teste ponta a ponta da cópia recebidos")
print(f"{'='*60}")
print(f"  Pasta de trabalho: {PASTA_TESTE}")
print()

BANCO_TESTE    = os.path.join(PASTA_TESTE, "gma.db")
DESTINO_TESTE  = os.path.join(PASTA_TESTE, "DESTINO")
RECEBIDOS_BASE = os.path.join(PASTA_TESTE, "recebidos")
os.makedirs(DESTINO_TESTE, exist_ok=True)
os.makedirs(RECEBIDOS_BASE, exist_ok=True)

# ── Configura as variáveis de ambiente ANTES de importar qualquer módulo GMA ──
# Isso isola este teste do projeto real (sp2b, laboratório, etc.).

os.environ["GMA_DB"]      = BANCO_TESTE
os.environ["GMA_DESTINO"] = DESTINO_TESTE

# painel_config.projeto_ativo() lê o painel_estado.json e pode apontar para o
# sp2b real. Para o teste, sobrescrevemos o que o transferencia.py precisa:
#   - GMA_DB já cuida do banco.
#   - caminho_recebidos é resolvido via painel_config.caminho_recebidos(config).
#   Para evitar que o transferencia.copiar_material_recebido() vá buscar a pasta
#   no sp2b real, montamos um painel_config "falso" via monkeypatch abaixo.

# ── Helpers ───────────────────────────────────────────────────────────────────

def _separador(titulo):
    print(f"\n{'─'*55}")
    print(f"  {titulo}")
    print(f"{'─'*55}")

def _ok(msg):
    print(f"  [PASS] {msg}")

def _falhou(msg):
    print(f"  [FAIL] {msg}")
    raise AssertionError(msg)

def _assert(condicao, msg):
    if condicao:
        _ok(msg)
    else:
        _falhou(msg)

# ── Cria alguns arquivos de teste (simula .NEF pequenos) ──────────────────────

def _criar_arquivos_teste(pasta, quantidade=3, tamanho_bytes=1024):
    """Cria <quantidade> arquivos .NEF falsos de <tamanho_bytes> bytes cada."""
    os.makedirs(pasta, exist_ok=True)
    for i in range(1, quantidade + 1):
        caminho = os.path.join(pasta, f"CAD_{7000+i:04d}.NEF")
        with open(caminho, "wb") as f:
            f.write(os.urandom(tamanho_bytes))

# ── Importa os módulos do GMA (após definir GMA_DB) ──────────────────────────

import banco_dados as bd
import painel_config as _pc

# Monkeypatch em painel_config: faz caminho_recebidos() devolver RECEBIDOS_BASE
# e projeto_ativo() devolver um projeto que aponta para BANCO_TESTE. Assim o
# transferencia.py não vai buscar nada no sp2b real.
_config_teste = {
    "db": BANCO_TESTE,
    "destino": DESTINO_TESTE,
    "recebidos": RECEBIDOS_BASE,
    "nome": "Teste",
}
_pc_projeto_ativo_original = _pc.projeto_ativo
_pc_caminho_recebidos_original = _pc.caminho_recebidos

_pc.projeto_ativo = lambda: ("teste", _config_teste)
_pc.caminho_recebidos = lambda config: RECEBIDOS_BASE

import transferencia as transf
# Após importar o transferencia, redefine PASTA_DESTINO_BASE para o destino de teste
# (o módulo já leu o GMA_DESTINO do ambiente no import, mas garantimos o monkeypatch)
transf.PASTA_DESTINO_BASE = DESTINO_TESTE

# ── Inicializa o banco de teste ────────────────────────────────────────────────

conn_init = bd.inicializar_banco()
conn_init.close()
print(f"  Banco de teste inicializado: {BANCO_TESTE}")

# ── Cria os Posts e pastas necessários para o teste ──────────────────────────

def _criar_post_recebido(nome, data="2026-06-21", pronto=True):
    """
    Insere um Post com origem_material='recebido' no banco de teste.
    Retorna o id do formulário.
    """
    conn = bd.obter_conexao()
    id_form = f"teste_{nome.lower().replace(' ','_')}_{datetime.now().strftime('%H%M%S%f')}"
    fid = bd.gravar_formulario(
        conn, id_form=id_form, nome=nome, camera="Nikon D850",
        tipo_material="FOTO", data_gravacao=data, operador="OPERADOR_TESTE",
        tem_foto=1, tem_audio=0, tem_video=0,
        origem_material="recebido",
    )
    if pronto:
        bd.marcar_recebido_pronto(conn, fid)
    conn.close()
    return fid


def _criar_post_cartao(nome, data="2026-06-21"):
    """
    Insere um Post com origem_material='cartao' (normal) no banco de teste.
    """
    conn = bd.obter_conexao()
    id_form = f"teste_cartao_{nome.lower()}_{datetime.now().strftime('%H%M%S%f')}"
    fid = bd.gravar_formulario(
        conn, id_form=id_form, nome=nome, camera="Sony FX6",
        tipo_material="VIDEO", data_gravacao=data, operador="OPERADOR_TESTE",
        tem_foto=0, tem_audio=0, tem_video=1,
        origem_material="cartao",
    )
    conn.close()
    return fid


# ══════════════════════════════════════════════════════════════════════════════
# Caso A — Caminho feliz
# Post recebido + pronto + pasta com arquivos → cópia OK → pasta renomeada
# ══════════════════════════════════════════════════════════════════════════════

_separador("Caso A — Caminho feliz")

# 1. Cria o Post
fid_a = _criar_post_recebido("FOTOGRAFO TESTE")
print(f"  Post ID={fid_a} criado (origem_material='recebido', pronto=1)")

# 2. Cria a pasta de material (slug = FOTOGRAFO_TESTE_<id>)
import banco_dados as _bd_aux

slug_a = f"{_bd_aux._sanitizar_nome_pasta('FOTOGRAFO TESTE')}_{fid_a}"
pasta_a = os.path.join(RECEBIDOS_BASE, slug_a)
_criar_arquivos_teste(pasta_a, quantidade=5, tamanho_bytes=2048)
print(f"  Pasta criada: {pasta_a} (5 arquivos .NEF)")

# 3. Dispara a cópia
resultado_a = transf.copiar_material_recebido(fid_a)
print(f"  Resultado: {resultado_a}")

_assert(resultado_a.get("ok"), "Cópia deve retornar ok=True")

numero_a = resultado_a.get("numero_cartao", "")
_assert(bool(numero_a), f"Deve retornar numero_cartao (got: {numero_a!r})")

destino_a = resultado_a.get("destino", "")
_assert(os.path.isdir(destino_a), f"Pasta de destino deve existir: {destino_a}")

arquivos_no_destino = [f for f in os.listdir(destino_a) if f.endswith(".NEF")]
_assert(len(arquivos_no_destino) == 5, f"5 .NEF no destino (got: {len(arquivos_no_destino)})")

# 4. Verifica que a pasta de ORIGEM foi renomeada para _COPIADO
pasta_copiada_a = resultado_a.get("caminho_pasta_copiada", "")
_assert(
    pasta_copiada_a.endswith("_COPIADO"),
    f"Pasta de origem deve terminar em _COPIADO (got: {pasta_copiada_a!r})"
)
_assert(os.path.isdir(pasta_copiada_a), f"Pasta _COPIADO deve existir: {pasta_copiada_a}")
_assert(
    not os.path.isdir(pasta_a),
    f"Pasta original NÃO deve mais existir com o nome antigo: {pasta_a}"
)

# 5. Verifica o banco: cartão com origem_material='recebido'
conn_v = bd.obter_conexao()
cartao_a = conn_v.execute(
    "SELECT * FROM cartoes ORDER BY id DESC LIMIT 1"
).fetchone()
_assert(cartao_a is not None, "Deve existir um cartão no banco")
_assert(cartao_a["origem_material"] == "recebido",
        f"origem_material deve ser 'recebido' (got: {cartao_a['origem_material']!r})")
_assert(cartao_a["status"] == "transferencia_ok",
        f"status deve ser 'transferencia_ok' (got: {cartao_a['status']!r})")
_assert(cartao_a["numero_cartao"] == numero_a,
        f"numero_cartao no banco deve bater com o retorno da função")

# 6. Verifica o match
match_a = conn_v.execute(
    "SELECT * FROM matches WHERE formulario_id = ?", (fid_a,)
).fetchone()
_assert(match_a is not None, "Deve existir um match no banco para este Post")
_assert(match_a["confirmado"] == 1, "Match deve estar confirmado=1")
conn_v.close()

print(f"\n  Numero do cartao: {numero_a}")
print(f"  Destino: {destino_a}")
print(f"  Pasta origem renomeada: {pasta_copiada_a}")


# ══════════════════════════════════════════════════════════════════════════════
# Caso B — Pasta vazia
# Deve recusar com motivo 'pasta_vazia'
# ══════════════════════════════════════════════════════════════════════════════

_separador("Caso B — Pasta vazia")

fid_b = _criar_post_recebido("FOTOGRAFO VAZIO")
slug_b = f"{_bd_aux._sanitizar_nome_pasta('FOTOGRAFO VAZIO')}_{fid_b}"
pasta_b = os.path.join(RECEBIDOS_BASE, slug_b)
os.makedirs(pasta_b, exist_ok=True)  # pasta existe mas está vazia
print(f"  Post ID={fid_b} | Pasta criada vazia: {pasta_b}")

resultado_b = transf.copiar_material_recebido(fid_b)
print(f"  Resultado: {resultado_b}")

_assert(not resultado_b.get("ok"), "Deve retornar ok=False para pasta vazia")
_assert(
    resultado_b.get("motivo") == "pasta_vazia",
    f"Motivo deve ser 'pasta_vazia' (got: {resultado_b.get('motivo')!r})"
)


# ══════════════════════════════════════════════════════════════════════════════
# Caso C — Post não-recebido (origem='cartao')
# Deve recusar com motivo 'nao_e_recebido'
# ══════════════════════════════════════════════════════════════════════════════

_separador("Caso C — Post de origem 'cartao' (nao recebido)")

fid_c = _criar_post_cartao("VIDEOMAKER NORMAL")
print(f"  Post ID={fid_c} criado (origem_material='cartao')")

resultado_c = transf.copiar_material_recebido(fid_c)
print(f"  Resultado: {resultado_c}")

_assert(not resultado_c.get("ok"), "Deve retornar ok=False para Post de origem 'cartao'")
_assert(
    resultado_c.get("motivo") == "nao_e_recebido",
    f"Motivo deve ser 'nao_e_recebido' (got: {resultado_c.get('motivo')!r})"
)


# ══════════════════════════════════════════════════════════════════════════════
# Caso D — Idempotência: clicar "Copiar agora" duas vezes não duplica
# Segunda chamada deve retornar ok=False com motivo 'ja_tem_match'
# ══════════════════════════════════════════════════════════════════════════════

_separador("Caso D — Idempotencia (clicar 2x nao duplica)")

# Reutiliza o fid_a que já foi copiado com sucesso no Caso A.
# A pasta foi renomeada para _COPIADO, o match já existe.
resultado_d = transf.copiar_material_recebido(fid_a)
print(f"  Resultado (2a chamada para Post {fid_a}): {resultado_d}")

_assert(not resultado_d.get("ok"), "Segunda chamada deve retornar ok=False")
_assert(
    resultado_d.get("motivo") == "ja_tem_match",
    f"Motivo deve ser 'ja_tem_match' (got: {resultado_d.get('motivo')!r})"
)

# Confirma que o banco NÃO tem cartão duplicado
conn_d = bd.obter_conexao()
qtd_cartoes = conn_d.execute(
    "SELECT COUNT(*) FROM matches WHERE formulario_id = ?", (fid_a,)
).fetchone()[0]
_assert(qtd_cartoes == 1, f"Deve existir exatamente 1 match para o Post {fid_a} (got: {qtd_cartoes})")
conn_d.close()


# ══════════════════════════════════════════════════════════════════════════════
# Caso E — Post recebido mas NÃO marcado como pronto
# Deve recusar com motivo 'nao_esta_pronto'
# ══════════════════════════════════════════════════════════════════════════════

_separador("Caso E — Post nao marcado como pronto")

fid_e = _criar_post_recebido("FOTOGRAFO AGUARDANDO", pronto=False)
slug_e = f"{_bd_aux._sanitizar_nome_pasta('FOTOGRAFO AGUARDANDO')}_{fid_e}"
pasta_e = os.path.join(RECEBIDOS_BASE, slug_e)
_criar_arquivos_teste(pasta_e, quantidade=2)
print(f"  Post ID={fid_e} criado (recebido_pronto=0) | Pasta: {pasta_e}")

resultado_e = transf.copiar_material_recebido(fid_e)
print(f"  Resultado: {resultado_e}")

_assert(not resultado_e.get("ok"), "Deve retornar ok=False para Post nao pronto")
_assert(
    resultado_e.get("motivo") == "nao_esta_pronto",
    f"Motivo deve ser 'nao_esta_pronto' (got: {resultado_e.get('motivo')!r})"
)


# ══════════════════════════════════════════════════════════════════════════════
# Resumo
# ══════════════════════════════════════════════════════════════════════════════

print(f"\n{'='*60}")
print(f"  Todos os casos passaram.")
print(f"{'='*60}")
print(f"\n  Pasta de trabalho (pode inspecionar ou apagar):")
print(f"    {PASTA_TESTE}")
print()
print(f"  Banco de teste: {BANCO_TESTE}")
print(f"  Destino de teste: {DESTINO_TESTE}")
print(f"  Recebidos de teste: {RECEBIDOS_BASE}")
print()
print("  Para inspecionar o banco:")
print(f"    sqlite3 {BANCO_TESTE} \"SELECT id, volume, status, origem_material, numero_cartao FROM cartoes\"")
print()
print("  Para limpar:")
print(f"    rm -rf {PASTA_TESTE}")
print()
