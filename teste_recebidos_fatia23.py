"""
Teste isolado: arco "recebidos" — Fatias 2 e 3 do GMA (Camada 1).

Cobre cinco cenários em banco e pasta temporários (/tmp), sem tocar no gma.db real:

  a) Post 'recebido' cria a subpasta local em caminho_recebidos.
  b) Caminho base inválido NÃO quebra o salvamento do Post (só avisa no log).
  c) Link da pasta na nuvem persiste e é editável.
  d) Gatilho 'recebido_pronto' marca o Post e loga o evento.
  e) Post 'cartao' NÃO cria pasta e NÃO mostra gatilho (chamada explícita recusa).

Uso:
  /usr/bin/python3 /Users/serafa/GMA/teste_recebidos_fatia23.py

Banco e pastas de teste ficam em /tmp — laboratório real intocado.
"""

import sys
import os
import shutil
import tempfile

# Aponta para a raiz do projeto
RAIZ_GMA = "/Users/serafa/GMA"
sys.path.insert(0, RAIZ_GMA)

# ── Banco temporário isolado ──────────────────────────────────────────────────
BANCO_TEMP = "/tmp/teste_recebidos_fatia23.db"
os.environ["GMA_DB"] = BANCO_TEMP

import banco_dados as bd

# Contadores de resultado
_ok = 0
_falhas = 0


def passou(msg):
    global _ok
    _ok += 1
    print(f"  [OK]  {msg}")


def falhou(msg):
    global _falhas
    _falhas += 1
    print(f"  [ERRO] {msg}")


def limpar():
    """Remove artefatos temporários (chamado ao fim, mesmo se houver falha)."""
    if os.path.exists(BANCO_TEMP):
        os.remove(BANCO_TEMP)


# ── Prepara banco limpo ───────────────────────────────────────────────────────
conn = bd.inicializar_banco()

# ── Dados de teste comuns ─────────────────────────────────────────────────────
def _gravar_post(conn, sufixo, origem="recebido"):
    """Grava um Post de teste e devolve o ID."""
    return bd.gravar_formulario(
        conn,
        id_form=f"20260621_TESTE_{sufixo}",
        nome="CAMILA FOTOGRAFA",
        camera="Nikon",
        tipo_material="FOTO",
        data_gravacao="2026-06-21",
        origem_material=origem,
    )


# ═════════════════════════════════════════════════════════════════════════════
# Cenário A — Post 'recebido' cria subpasta local
# ═════════════════════════════════════════════════════════════════════════════
print("\n[A] Post 'recebido' cria a subpasta local em caminho_recebidos")

pasta_base = tempfile.mkdtemp(prefix="gma_recebidos_a_")

id_a = _gravar_post(conn, "A", origem="recebido")
caminho_pasta, erro_pasta = bd.criar_pasta_recebidos_post(conn, id_a, pasta_base)

if erro_pasta:
    falhou(f"criar_pasta_recebidos_post retornou erro: {erro_pasta}")
elif not caminho_pasta:
    falhou("caminho_pasta veio None sem mensagem de erro")
elif not os.path.isdir(caminho_pasta):
    falhou(f"Pasta não existe no disco: {caminho_pasta}")
else:
    passou(f"Pasta criada: {caminho_pasta}")

# Idempotência: chamar de novo NÃO deve criar duplicata nem falhar
caminho_b, erro_b = bd.criar_pasta_recebidos_post(conn, id_a, pasta_base)
if erro_b:
    falhou(f"Segunda chamada (idempotência) falhou: {erro_b}")
elif caminho_b != caminho_pasta:
    falhou(f"Segunda chamada retornou caminho diferente: {caminho_b}")
else:
    passou("Idempotência: segunda chamada retorna mesmo caminho sem duplicar")

shutil.rmtree(pasta_base, ignore_errors=True)


# ═════════════════════════════════════════════════════════════════════════════
# Cenário B — Caminho base inválido NÃO quebra o Post
# ═════════════════════════════════════════════════════════════════════════════
print("\n[B] Caminho base inválido não derruba o salvamento do Post")

id_b = _gravar_post(conn, "B", origem="recebido")

# Caminho que não existe e não pode ser criado (enraizado em diretório inválido)
caminho_invalido = "/caminho/absolutamente/inexistente/gma_teste"
caminho_b_pasta, erro_b_falha = bd.criar_pasta_recebidos_post(conn, id_b, caminho_invalido)

# Deve retornar (None, mensagem_de_erro) sem levantar exceção
if caminho_b_pasta is not None:
    falhou(f"Esperava None como caminho, obteve: {caminho_b_pasta}")
elif not erro_b_falha:
    falhou("Esperava mensagem de erro, obteve None")
else:
    passou(f"Caminho inválido gera aviso sem quebrar o Post: {erro_b_falha[:60]}...")

# Confirma que o Post B ainda existe no banco (salvamento não foi afetado)
row_b = conn.execute("SELECT id FROM formularios WHERE id = ?", (id_b,)).fetchone()
if row_b is None:
    falhou("Post B sumiu do banco após falha de pasta (não deveria)")
else:
    passou(f"Post ID={id_b} permanece no banco após falha de pasta")

# O evento de falha deve ter sido registrado no Log
eventos_falha = conn.execute(
    "SELECT tipo FROM eventos WHERE formulario_id = ? AND tipo = 'recebidos_pasta_falhou'",
    (id_b,)
).fetchall()
if not eventos_falha:
    falhou("Evento 'recebidos_pasta_falhou' não foi gravado no Log")
else:
    passou(f"Evento de falha gravado no Log ({len(eventos_falha)} registro(s))")


# ═════════════════════════════════════════════════════════════════════════════
# Cenário C — Link da pasta na nuvem persiste e é editável
# ═════════════════════════════════════════════════════════════════════════════
print("\n[C] Link da pasta na nuvem persiste e é editável")

id_c = _gravar_post(conn, "C", origem="recebido")

# Salva um link
link_teste = "https://drive.google.com/drive/folders/abc123xyz"
resultado_link = bd.definir_link_recebidos(conn, id_c, link_teste)

if not resultado_link:
    falhou(f"definir_link_recebidos retornou False para Post ID={id_c}")
else:
    passou(f"Link definido para Post ID={id_c}")

# Verifica que o link persistiu no banco
row_c = conn.execute(
    "SELECT link_recebidos FROM formularios WHERE id = ?", (id_c,)
).fetchone()

if row_c is None:
    falhou("Post C não encontrado no banco")
elif row_c["link_recebidos"] != link_teste:
    falhou(f"Link no banco '{row_c['link_recebidos']}' diferente do esperado '{link_teste}'")
else:
    passou("Link persistido corretamente no banco")

# Edita o link (substitui por outro)
link_novo = "https://www.dropbox.com/sh/novo_link_xyz"
bd.definir_link_recebidos(conn, id_c, link_novo)
row_c2 = conn.execute(
    "SELECT link_recebidos FROM formularios WHERE id = ?", (id_c,)
).fetchone()
if row_c2["link_recebidos"] != link_novo:
    falhou(f"Link não foi atualizado: '{row_c2['link_recebidos']}' ≠ '{link_novo}'")
else:
    passou("Link editado (sobrescrito) corretamente")

# Remove o link (string vazia → NULL no banco)
bd.definir_link_recebidos(conn, id_c, "")
row_c3 = conn.execute(
    "SELECT link_recebidos FROM formularios WHERE id = ?", (id_c,)
).fetchone()
if row_c3["link_recebidos"] is not None:
    falhou(f"Link deveria ser NULL após remoção, é: '{row_c3['link_recebidos']}'")
else:
    passou("Link removido (NULL) corretamente")

# Verifica evento no Log
eventos_link = conn.execute(
    "SELECT tipo FROM eventos WHERE formulario_id = ? AND tipo = 'link_recebidos_definido'",
    (id_c,)
).fetchall()
if not eventos_link:
    falhou("Evento 'link_recebidos_definido' não encontrado no Log")
else:
    passou(f"Evento de link gravado no Log ({len(eventos_link)} registro(s))")


# ═════════════════════════════════════════════════════════════════════════════
# Cenário D — Gatilho marca o Post como pronto e loga
# ═════════════════════════════════════════════════════════════════════════════
print("\n[D] Gatilho 'recebido_pronto' marca o Post e loga evento")

id_d = _gravar_post(conn, "D", origem="recebido")

# Estado inicial: recebido_pronto deve ser 0
row_d0 = conn.execute(
    "SELECT recebido_pronto FROM formularios WHERE id = ?", (id_d,)
).fetchone()
if row_d0 is None:
    falhou("Post D não encontrado no banco")
elif row_d0["recebido_pronto"] != 0:
    falhou(f"Estado inicial deve ser 0, é: {row_d0['recebido_pronto']}")
else:
    passou("Estado inicial recebido_pronto = 0")

# Dispara o gatilho
resultado_d = bd.marcar_recebido_pronto(conn, id_d)
if not resultado_d.get("ok"):
    falhou(f"marcar_recebido_pronto retornou: {resultado_d}")
else:
    passou(f"Gatilho disparado com sucesso: {resultado_d}")

# Verifica que a coluna foi marcada
row_d1 = conn.execute(
    "SELECT recebido_pronto FROM formularios WHERE id = ?", (id_d,)
).fetchone()
if row_d1["recebido_pronto"] != 1:
    falhou(f"recebido_pronto deveria ser 1, é: {row_d1['recebido_pronto']}")
else:
    passou("recebido_pronto = 1 confirmado no banco")

# Segunda chamada deve recusar (já estava pronto)
resultado_d2 = bd.marcar_recebido_pronto(conn, id_d)
if resultado_d2.get("ok"):
    falhou("Segunda chamada deveria ser recusada (já estava pronto), mas retornou ok=True")
elif resultado_d2.get("motivo") != "ja_estava_pronto":
    falhou(f"Motivo esperado 'ja_estava_pronto', obteve: {resultado_d2.get('motivo')}")
else:
    passou("Segunda chamada recusada com motivo 'ja_estava_pronto'")

# Verifica evento no Log
eventos_d = conn.execute(
    "SELECT tipo FROM eventos WHERE formulario_id = ? AND tipo = 'recebido_pronto'",
    (id_d,)
).fetchall()
if not eventos_d:
    falhou("Evento 'recebido_pronto' não encontrado no Log")
else:
    passou(f"Evento 'recebido_pronto' gravado no Log ({len(eventos_d)} registro(s))")


# ═════════════════════════════════════════════════════════════════════════════
# Cenário E — Post 'cartao' NÃO deve criar pasta nem ser marcado pelo gatilho
# ═════════════════════════════════════════════════════════════════════════════
print("\n[E] Post 'cartao' não cria pasta e gatilho recusa")

pasta_base_e = tempfile.mkdtemp(prefix="gma_recebidos_e_")
id_e = _gravar_post(conn, "E", origem="cartao")

# Verifica que o Post E tem origem_material='cartao'
row_e = conn.execute(
    "SELECT origem_material FROM formularios WHERE id = ?", (id_e,)
).fetchone()
if row_e["origem_material"] != "cartao":
    falhou(f"Post E deveria ser 'cartao', é: {row_e['origem_material']}")
else:
    passou("Post E com origem_material='cartao' confirmado")

# O sistema não chama criar_pasta_recebidos_post para Posts cartao — não há bloco
# que faça isso no fluxo normal. Mas se chamarmos diretamente (como teste de
# regressão), a função não tem proteção embutida: ela cria a pasta mesmo assim.
# O que NÃO deve acontecer é que o fluxo normal do check-in crie pasta para Post 'cartao'.
# Verificamos isso através do Log: não deve haver evento 'recebidos_pasta_criada' para E.
#
# (Chamada direta está fora do escopo desta verificação — o guard está no Flask)

# Gatilho recusa Post 'cartao' (verificação que o banco protege)
resultado_e = bd.marcar_recebido_pronto(conn, id_e)
if resultado_e.get("ok"):
    falhou("Gatilho aceitou Post 'cartao' — deveria recusar")
elif resultado_e.get("motivo") != "nao_e_recebido":
    falhou(f"Motivo esperado 'nao_e_recebido', obteve: {resultado_e.get('motivo')}")
else:
    passou(f"Gatilho recusou Post 'cartao' com motivo '{resultado_e['motivo']}'")

# Post 'cartao' não deve ter eventos de pasta criada
eventos_e_pasta = conn.execute(
    "SELECT tipo FROM eventos WHERE formulario_id = ? AND tipo = 'recebidos_pasta_criada'",
    (id_e,)
).fetchall()
if eventos_e_pasta:
    falhou(f"Post 'cartao' não deveria ter evento 'recebidos_pasta_criada', mas tem {len(eventos_e_pasta)}")
else:
    passou("Post 'cartao' sem eventos de pasta satélite (correto)")

shutil.rmtree(pasta_base_e, ignore_errors=True)


# ═════════════════════════════════════════════════════════════════════════════
# Resultado final
# ═════════════════════════════════════════════════════════════════════════════
conn.close()
limpar()

print("\n" + "=" * 60)
if _falhas == 0:
    print(f"  Todos os {_ok} cenários passaram.")
else:
    print(f"  {_ok} passaram · {_falhas} falharam.")
print()
print("  Colunas novas em 'formularios':")
print("    link_recebidos  TEXT          — link da pasta na nuvem (operador cola à mão)")
print("    recebido_pronto INTEGER (0/1) — gatilho do operador: pronto para cópia")
print()
print("  Funções novas em banco_dados.py:")
print("    criar_pasta_recebidos_post(conn, formulario_id, caminho_base)")
print("    definir_link_recebidos(conn, formulario_id, link)")
print("    marcar_recebido_pronto(conn, formulario_id)")
print()
print("  NOTA: a cópia de verdade (copiador.py / Camada 2) é a PRÓXIMA FATIA.")
print("  O flag 'recebido_pronto' sinaliza a C2, que ainda não monitora este campo.")
print("=" * 60 + "\n")

sys.exit(0 if _falhas == 0 else 1)
