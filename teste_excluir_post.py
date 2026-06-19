#!/usr/bin/env python3
"""
Teste do excluir_formulario (hard delete de Post sem uso — #3 s39).

Cobre:
  A) exclui um Post sem uso → some de formularios; o Log SOBREVIVE (eventos
     desvinculados + evento post_excluido).
  B) cascata: chips e textos da ficha são apagados.
  C) guarda: Post com match REAL é recusado (ficha_em_uso), nada é apagado.
  D) ficha inexistente → ficha_inexistente.
"""
import os
import sys
import tempfile

sys.path.insert(0, "/Users/serafa/GMA")
_DB_TMP = tempfile.mktemp(prefix="gma_excluir_", suffix=".db")
os.environ["GMA_DB"] = _DB_TMP

import banco_dados as bd  # noqa: E402

falhas = []


def checar(cond, msg):
    if not cond:
        falhas.append(msg)


def _novo_post(conn, id_form, nome):
    bd.gravar_formulario(conn, id_form=id_form, nome=nome, camera="GoPro",
                         tipo_material="VIDEO", data_gravacao="2026-06-19")
    return conn.execute("SELECT id FROM formularios WHERE id_form_original = ?",
                        (id_form,)).fetchone()["id"]


def main():
    conn = bd.inicializar_banco()

    # ── A + B) Post sem uso, com chip e texto, é excluído; Log sobrevive ─────
    fid = _novo_post(conn, "form_a", "FULANO")
    # um item de lista + chip + texto ligados à ficha (filhos a apagar em cascata)
    item_id = bd.adicionar_item_lista(conn, "marca", "ITAU")["id"]
    bd.definir_chips_formulario(conn, fid, [item_id])
    conn.execute(
        "INSERT INTO formularios_textos (formulario_id, grupo_chave, valor) VALUES (?,?,?)",
        (fid, "tag", "entrevista"),
    )
    conn.commit()
    checar(len(bd.listar_chips_formulario(conn, fid)) == 1, "B: chip deveria existir antes")

    r = bd.excluir_formulario(conn, fid)
    checar(r["ok"], f"A: exclusão deveria dar ok, veio {r}")
    # sumiu de formularios
    existe = conn.execute("SELECT 1 FROM formularios WHERE id = ?", (fid,)).fetchone()
    checar(existe is None, "A: formulario deveria ter sido apagado")
    # cascata: chips e textos apagados
    n_chips = conn.execute("SELECT COUNT(*) FROM formularios_chips WHERE formulario_id = ?", (fid,)).fetchone()[0]
    n_txt = conn.execute("SELECT COUNT(*) FROM formularios_textos WHERE formulario_id = ?", (fid,)).fetchone()[0]
    checar(n_chips == 0, f"B: chips deveriam sumir, sobraram {n_chips}")
    checar(n_txt == 0, f"B: textos deveriam sumir, sobraram {n_txt}")
    # Log sobrevive: existe evento post_excluido com o nome no dados_json
    ev = conn.execute(
        "SELECT descricao FROM eventos WHERE tipo = 'post_excluido' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    checar(ev is not None and "FULANO" in ev["descricao"], "A: Log deveria registrar post_excluido com o nome")
    # eventos antigos da ficha foram DESVINCULADOS, não apagados (formulario_id NULL)
    orfaos = conn.execute(
        "SELECT COUNT(*) FROM eventos WHERE formulario_id = ?", (fid,)
    ).fetchone()[0]
    checar(orfaos == 0, f"A: não deveria sobrar evento ligado à ficha apagada, veio {orfaos}")

    # ── C) Post com match REAL é recusado ────────────────────────────────────
    fid2 = _novo_post(conn, "form_b", "BELTRANO")
    cartao_id = bd.gravar_cartao(conn, volume="CART_B", caminho_origem="/tmp/b",
                                 marca_camera="GoPro", tipo_material="VIDEO")
    bd.registrar_match_manual(conn, cartao_id, fid2)
    r2 = bd.excluir_formulario(conn, fid2)
    checar(not r2["ok"] and r2["motivo"] == "ficha_em_uso",
           f"C: Post com match real deveria ser recusado (ficha_em_uso), veio {r2}")
    ainda = conn.execute("SELECT 1 FROM formularios WHERE id = ?", (fid2,)).fetchone()
    checar(ainda is not None, "C: Post com match NÃO deveria ter sido apagado")

    # ── D) ficha inexistente ─────────────────────────────────────────────────
    r3 = bd.excluir_formulario(conn, 999999)
    checar(not r3["ok"] and r3["motivo"] == "ficha_inexistente",
           f"D: id inexistente deveria dar ficha_inexistente, veio {r3}")

    conn.close()


if __name__ == "__main__":
    main()
    try:
        os.remove(_DB_TMP)
    except OSError:
        pass
    print("\n" + "=" * 60)
    if falhas:
        print(f"  {len(falhas)} VERIFICACAO(OES) FALHARAM:")
        for f in falhas:
            print(f"   - {f}")
        print("=" * 60 + "\n")
        sys.exit(1)
    print("  TODOS OS TESTES DE EXCLUIR POST (#3) PASSARAM ✅")
    print("   A) exclui Post sem uso; Log sobrevive (desvincula + post_excluido)")
    print("   B) cascata apaga chips e textos")
    print("   C) Post com match real é recusado (ficha_em_uso)")
    print("   D) ficha inexistente tratada")
    print("=" * 60 + "\n")
    sys.exit(0)
