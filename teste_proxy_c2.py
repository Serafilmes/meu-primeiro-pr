#!/usr/bin/env python3
"""
Testes da marca de proxy na Camada 2 (#2 Fatia B).

O que esta fatia garante:
  - O proxy (ex.: .LRV da GoPro) é SEMPRE copiado (nunca pulado) — pular deixaria
    o cartão com arquivos não verificados e o embaralhamento (Parashoot) apagaria
    material que nunca foi copiado.
  - Cada proxy é MARCADO (tipo=PROXY) e LIGADO ao clipe principal (proxy_de).
  - A marca atravessa o pipeline: copiador → .sppo → parser → banco.
  - O operador é AVISADO (total_proxies no resultado da cópia).

Casos cobertos:
  A) copiador marca tipo/proxy_de por arquivo e conta total_proxies.
  B) o .sppo carrega kind/proxyOf; o parser os lê de volta (+ total_proxies).
  C) gravar_arquivos_do_log persiste tipo/proxy_de na tabela arquivos.
"""
import os
import sys
import shutil
import tempfile

sys.path.insert(0, "/Users/serafa/GMA")

# Banco isolado em arquivo temporário — definido ANTES de importar banco_dados,
# que resolve o caminho do banco (GMA_DB) no import.
_DB_TMP = tempfile.mktemp(prefix="gma_proxy_db_", suffix=".db")
os.environ["GMA_DB"] = _DB_TMP

import copiador            # noqa: E402
import gma_relatorio_pdf   # noqa: E402
import banco_dados as bd   # noqa: E402

falhas = []


def checar(cond, msg):
    if not cond:
        falhas.append(msg)


def montar_cartao_gopro():
    """Cartão com clipe + proxy + foto + RAW-de-foto (.GPR)."""
    base = tempfile.mkdtemp(prefix="gma_proxy_")
    origem = os.path.join(base, "cartao")
    destino = os.path.join(base, "destino")
    os.makedirs(origem)
    os.makedirs(destino)
    # clipe principal de vídeo
    with open(os.path.join(origem, "GX019385.MP4"), "wb") as f:
        f.write(b"\x00\x11\x22\x33" * 4096)
    # proxy de baixa-res do MESMO clipe (GL019385 → GX019385.MP4)
    with open(os.path.join(origem, "GL019385.LRV"), "wb") as f:
        f.write(b"\x44\x55" * 2048)
    # foto + sua RAW (.GPR, antes caía em OUTRO; Fatia A → FOTO)
    with open(os.path.join(origem, "GOPR0001.JPG"), "wb") as f:
        f.write(b"\xff\xd8\xff" * 1024)
    with open(os.path.join(origem, "GOPR0001.GPR"), "wb") as f:
        f.write(b"\x01\x02\x03" * 1024)
    return base, origem, destino


# ── A) copiador marca tipo/proxy_de e conta proxies ──────────────────────────
def teste_copiador_marca_proxy():
    base, origem, destino = montar_cartao_gopro()
    try:
        r = copiador.copiar(origem, destino, "TESTE_PROXY")
    finally:
        pass

    checar(r["ok"], "A: a cópia deveria ser OK")
    checar(r.get("total_proxies") == 1, f"A: esperado 1 proxy, veio {r.get('total_proxies')}")

    por_nome = {a["nome"]: a for a in r["arquivos"]}
    checar(por_nome["GL019385.LRV"]["tipo"] == "PROXY", "A: .LRV deveria ser tipo PROXY")
    checar(
        por_nome["GL019385.LRV"]["proxy_de"] == "GX019385.MP4",
        f"A: .LRV deveria ligar a GX019385.MP4, veio {por_nome['GL019385.LRV']['proxy_de']}",
    )
    checar(por_nome["GX019385.MP4"]["tipo"] == "VIDEO", "A: .MP4 deveria ser tipo VIDEO")
    checar(por_nome["GX019385.MP4"]["proxy_de"] is None, "A: .MP4 não deveria ter proxy_de")
    checar(por_nome["GOPR0001.JPG"]["tipo"] == "FOTO", "A: .JPG deveria ser tipo FOTO")
    checar(por_nome["GOPR0001.GPR"]["tipo"] == "FOTO", "A: .GPR (RAW) deveria ser tipo FOTO")
    # proxy é footage derivado → continua CRÍTICO (copiado e verificado como tal)
    checar(por_nome["GL019385.LRV"]["critico"] is True, "A: .LRV deveria ser crítico (footage)")

    shutil.rmtree(base, ignore_errors=True)
    return r


# ── B) .sppo carrega kind/proxyOf; parser lê de volta ────────────────────────
def teste_sppo_e_parser():
    base, origem, destino = montar_cartao_gopro()
    r = copiador.copiar(origem, destino, "TESTE_PROXY_B")
    dados = gma_relatorio_pdf.parse_shotputpro_log(r["caminho_log"])

    checar(dados.get("total_proxies") == 1,
           f"B: parser deveria achar 1 proxy, veio {dados.get('total_proxies')}")
    por_nome = {a["nome"]: a for a in dados["arquivos"]}
    checar(por_nome["GL019385.LRV"]["tipo"] == "proxy",
           f"B: parser deveria ler kind=proxy, veio {por_nome['GL019385.LRV']['tipo']}")
    checar(por_nome["GL019385.LRV"]["proxy_de"] == "GX019385.MP4",
           "B: parser deveria ler proxyOf=GX019385.MP4")
    checar(por_nome["GX019385.MP4"]["tipo"] == "video",
           f"B: parser deveria ler kind=video, veio {por_nome['GX019385.MP4']['tipo']}")

    shutil.rmtree(base, ignore_errors=True)
    return dados


# ── C) banco persiste tipo/proxy_de ──────────────────────────────────────────
def teste_banco_persiste(dados_log):
    conn = bd.inicializar_banco()
    # cria um cartão mínimo para ter um cartao_id
    cartao_id = bd.gravar_cartao(conn, volume="CARTAO_PROXY",
                                 caminho_origem="/tmp/cartao_proxy",
                                 marca_camera="GoPro", tipo_material="VIDEO")
    bd.gravar_arquivos_do_log(conn, cartao_id, dados_log)

    rows = conn.execute(
        "SELECT nome_arquivo, tipo, proxy_de FROM arquivos WHERE cartao_id = ?",
        (cartao_id,),
    ).fetchall()
    por_nome = {r[0]: (r[1], r[2]) for r in rows}
    conn.close()

    checar(por_nome.get("GL019385.LRV") == ("proxy", "GX019385.MP4"),
           f"C: banco deveria guardar (proxy, GX019385.MP4), veio {por_nome.get('GL019385.LRV')}")
    checar(por_nome.get("GX019385.MP4", (None,))[0] == "video",
           f"C: banco deveria guardar tipo=video p/ o clipe, veio {por_nome.get('GX019385.MP4')}")


if __name__ == "__main__":
    teste_copiador_marca_proxy()
    dados_log = teste_sppo_e_parser()
    teste_banco_persiste(dados_log)

    # limpeza do banco temporário
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
    print("  TODOS OS TESTES DE PROXY (C2 — Fatia B) PASSARAM ✅")
    print("   A) copiador marca tipo/proxy_de e conta total_proxies")
    print("   B) .sppo carrega kind/proxyOf; parser lê de volta")
    print("   C) banco persiste tipo/proxy_de na tabela arquivos")
    print("=" * 60 + "\n")
    sys.exit(0)
