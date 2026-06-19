#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Teste da Fatia 1 do #5 (nomes curtos) — banco isolado em /tmp, laboratório intocado.

Cobre:
  A) migração cria nome_raiz/nome_curto; criar_profissional preenche o palpite
  B) colisão de sobrenome gera curtos distintos (token único, NOME_NNN)
  C) backfill preenche cadastros antigos sem curto
  D) edição (definir_nomes_profissional): ok / duplicado / vazio
  E) trava: profissional com cartão logado não pode editar os nomes
"""
import os
import tempfile

# Aponta o banco para um arquivo temporário ANTES de importar o banco_dados,
# porque CAMINHO_BANCO é resolvido na importação a partir de GMA_DB.
_tmp = tempfile.mkdtemp(prefix="gma_teste_nomes_")
os.environ["GMA_DB"] = os.path.join(_tmp, "gma_teste.db")

import banco_dados as bd

falhas = []


def checar(condicao, descricao):
    marca = "OK " if condicao else "FALHOU"
    print(f"  [{marca}] {descricao}")
    if not condicao:
        falhas.append(descricao)


def main():
    conn = bd.inicializar_banco()

    # ── A) migração + defaults no cadastro ────────────────────────────────────
    print("\nA) Migração e defaults no cadastro")
    colunas = [r[1] for r in conn.execute("PRAGMA table_info(profissionais)").fetchall()]
    checar("nome_raiz" in colunas and "nome_curto" in colunas,
           "colunas nome_raiz e nome_curto existem")

    p = bd.criar_profissional(conn, "Fernando Dumitriu", {"video": True})
    checar(p["nome_raiz"] == "FERNANDO_DUMITRIU", f"raiz = FERNANDO_DUMITRIU (got {p['nome_raiz']})")
    checar(p["nome_curto"] == "DUMITRIU", f"curto = DUMITRIU (got {p['nome_curto']})")

    # ── B) colisão de sobrenome → token único distinto ────────────────────────
    print("\nB) Colisão de sobrenome (curto sempre 1 token)")
    bd.criar_profissional(conn, "João Silva", {"video": True})
    p2 = bd.criar_profissional(conn, "Pedro Silva", {"video": True})
    checar(p2["nome_curto"] == "PEDRO", f"2º Silva vira PEDRO (got {p2['nome_curto']})")
    checar("_" not in p2["nome_curto"], "curto é token único (sem '_')")

    p3 = bd.criar_profissional(conn, "Carlos Erbs dos Santos Junior", {"video": True})
    checar(p3["nome_curto"] == "SANTOS", f"sufixo Junior pulado → SANTOS (got {p3['nome_curto']})")
    checar(p3["nome_raiz"] == "CARLOS_SANTOS", f"raiz CARLOS_SANTOS (got {p3['nome_raiz']})")

    # ── C) backfill de cadastro antigo sem curto ──────────────────────────────
    print("\nC) Backfill de cadastro antigo")
    # Simula um registro pré-s39: insere direto sem nome_curto/raiz.
    conn.execute(
        "INSERT INTO profissionais (nome, tem_foto, tem_audio, tem_video, letra) "
        "VALUES ('Beatriz Souza', 0, 0, 1, 'ZZ')"
    )
    conn.commit()
    bd.backfill_nomes_curtos(conn)
    row = conn.execute(
        "SELECT nome_raiz, nome_curto FROM profissionais WHERE nome = 'Beatriz Souza'"
    ).fetchone()
    checar(row[1] == "SOUZA", f"backfill curto = SOUZA (got {row[1]})")
    checar(row[0] == "BEATRIZ_SOUZA", f"backfill raiz = BEATRIZ_SOUZA (got {row[0]})")

    # ── D) edição: ok / duplicado / vazio ─────────────────────────────────────
    print("\nD) Edição dos nomes (definir_nomes_profissional)")
    r_ok = bd.definir_nomes_profissional(conn, p["id"], nome_curto="FERNANDO")
    checar(r_ok == "ok", f"editar curto livre → ok (got {r_ok})")
    novo = conn.execute("SELECT nome_curto FROM profissionais WHERE id = ?", (p["id"],)).fetchone()[0]
    checar(novo == "FERNANDO", f"gravou FERNANDO (got {novo})")

    r_dup = bd.definir_nomes_profissional(conn, p2["id"], nome_curto="SANTOS")  # já é do p3
    checar(r_dup == "duplicado", f"curto já usado → duplicado (got {r_dup})")

    r_vazio = bd.definir_nomes_profissional(conn, p2["id"], nome_curto="!!!")
    checar(r_vazio == "vazio", f"curto que sanitiza p/ vazio → vazio (got {r_vazio})")

    # Iniciais manuais (JA) — caso do último projeto.
    r_ja = bd.definir_nomes_profissional(conn, p2["id"], nome_curto="JA", nome_raiz="JOAO_ALEXANDRE")
    checar(r_ja == "ok", f"definir JA manualmente → ok (got {r_ja})")

    # ── E) trava: cartão logado bloqueia a edição ─────────────────────────────
    print("\nE) Trava após cartão logado")
    # Monta um cartão numerado ligado ao Fernando por match → formulario.nome.
    conn.execute(
        "INSERT INTO formularios (nome, tipo_material) VALUES ('Fernando Dumitriu', 'VIDEO')"
    )
    fid = conn.execute("SELECT id FROM formularios WHERE nome='Fernando Dumitriu'").fetchone()[0]
    conn.execute(
        "INSERT INTO cartoes (volume, caminho_origem, numero_cartao, status) "
        "VALUES ('VOL1', '/Volumes/VOL1', 'FERNANDO_001', 'concluido')"
    )
    cid = conn.execute("SELECT id FROM cartoes WHERE numero_cartao='FERNANDO_001'").fetchone()[0]
    conn.execute(
        "INSERT INTO matches (cartao_id, formulario_id, score) VALUES (?, ?, 3)",
        (cid, fid),
    )
    conn.commit()

    checar(bd.profissional_tem_cartao_logado(conn, "Fernando Dumitriu") is True,
           "Fernando agora tem cartão logado")
    r_trava = bd.definir_nomes_profissional(conn, p["id"], nome_curto="OUTRO")
    checar(r_trava == "travado", f"editar travado após cartão → travado (got {r_trava})")
    # Confirma que NADA mudou.
    final = conn.execute("SELECT nome_curto FROM profissionais WHERE id = ?", (p["id"],)).fetchone()[0]
    checar(final == "FERNANDO", f"curto preservado na trava (got {final})")

    conn.close()

    print("\n" + "=" * 50)
    if falhas:
        print(f"❌ {len(falhas)} FALHA(S):")
        for f in falhas:
            print(f"   - {f}")
        raise SystemExit(1)
    print("✅ Todos os testes da Fatia 1 passaram.")
    print(f"(banco de teste em {os.environ['GMA_DB']})")


if __name__ == "__main__":
    main()
