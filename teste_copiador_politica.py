#!/usr/bin/env python3
"""
Testes da política de integridade do copiador.py (denylist mídia vs. sistema)
e do fallback copy2 -> copyfile.

Casos cobertos:
  A) .url cujo copy2 falha (Operation not permitted) -> fallback copyfile -> MD5 OK.
  B) arquivo de SISTEMA (.log) cujo MD5 DIVERGE -> vira AVISO, ok continua True.
  C) arquivo de FOOTAGE (.MP4) cujo MD5 DIVERGE -> FALHA CRÍTICA, ok = False.
  D) classificacao eh_arquivo_sistema() direta.
  E) .sppo carrega critical="yes/no" e systemWarnings.
"""
import os
import sys
import shutil
import tempfile
import xml.etree.ElementTree as ET

sys.path.insert(0, "/Users/serafa/GMA")
import copiador  # noqa: E402

falhas_globais = []


def checar(cond, msg):
    if not cond:
        falhas_globais.append(msg)


# ── D) Classificacao direta ───────────────────────────────────────────────────
def teste_classificacao():
    checar(copiador.eh_arquivo_sistema("Get_started_with_GoPro.url"), "url deveria ser sistema")
    checar(copiador.eh_arquivo_sistema("mdb7.log"), ".log deveria ser sistema")
    checar(copiador.eh_arquivo_sistema("mdb_h7.bk"), ".bk deveria ser sistema")
    checar(not copiador.eh_arquivo_sistema("GOPR0001.MP4"), ".MP4 NAO eh sistema (footage)")
    checar(not copiador.eh_arquivo_sistema("clip.braw"), "extensao desconhecida deve ser critica")
    checar(not copiador.eh_arquivo_sistema("GH010001.LRV"), ".LRV (proxy) deve ser footage/critico")


# ── Monkeypatch helpers ───────────────────────────────────────────────────────
def instalar_copia_com_falhas(falha_copy2_em=(), corromper_md5_em=()):
    """Substitui copy2/copyfile.
       falha_copy2_em: nomes cujo copy2 lança PermissionError (forca fallback).
       corromper_md5_em: nomes cujos dados copiados sao alterados (MD5 diverge)."""
    copy2_orig = shutil.copy2
    copyfile_orig = shutil.copyfile

    def _copiar_real(src, dst):
        if os.path.basename(src) in corromper_md5_em:
            with open(dst, "wb") as f:
                f.write(b"CONTEUDO_CORROMPIDO_DIFERENTE")
        else:
            copyfile_orig(src, dst)

    def copy2_fake(src, dst, *a, **k):
        if os.path.basename(src) in falha_copy2_em:
            raise PermissionError(13, "Operation not permitted")
        _copiar_real(src, dst)

    def copyfile_fake(src, dst, *a, **k):
        _copiar_real(src, dst)

    shutil.copy2 = copy2_fake
    shutil.copyfile = copyfile_fake
    return (copy2_orig, copyfile_orig)


def restaurar_copia(originais):
    shutil.copy2, shutil.copyfile = originais


def montar_cartao():
    base = tempfile.mkdtemp(prefix="gma_pol_")
    origem = os.path.join(base, "cartao")
    destino = os.path.join(base, "destino")
    os.makedirs(origem)
    os.makedirs(destino)
    with open(os.path.join(origem, "Get_started_with_GoPro.url"), "wb") as f:
        f.write(b"[InternetShortcut]\r\nURL=https://gopro.com\r\n")
    with open(os.path.join(origem, "mdb7.log"), "wb") as f:
        f.write(b"log da camera\n")
    with open(os.path.join(origem, "GOPR0001.MP4"), "wb") as f:
        f.write(b"\x00\x11\x22\x33" * 4096)
    return base, origem, destino


# ── A) Fallback no .url ───────────────────────────────────────────────────────
def teste_fallback_url():
    base, origem, destino = montar_cartao()
    orig = instalar_copia_com_falhas(falha_copy2_em={"Get_started_with_GoPro.url"})
    try:
        r = copiador.copiar(origem, destino, "TESTE_A")
    finally:
        restaurar_copia(orig)
    checar(r["ok"], "A: ok deveria ser True (fallback resolve o .url)")
    checar(r["total_verificados"] == 3, f"A: esperado 3 verificados, veio {r['total_verificados']}")
    checar(r["total_avisos"] == 0, f"A: esperado 0 avisos, veio {r['total_avisos']}")
    shutil.rmtree(base, ignore_errors=True)


# ── B) MD5 divergente em arquivo de SISTEMA -> AVISO, ok True ─────────────────
def teste_md5_sistema_vira_aviso():
    base, origem, destino = montar_cartao()
    orig = instalar_copia_com_falhas(corromper_md5_em={"mdb7.log"})
    try:
        r = copiador.copiar(origem, destino, "TESTE_B")
    finally:
        restaurar_copia(orig)
    checar(r["ok"], "B: ok deveria continuar True (falha so em arquivo de sistema)")
    checar(r["total_falhos"] == 0, f"B: esperado 0 falhas criticas, veio {r['total_falhos']}")
    checar(r["total_avisos"] == 1, f"B: esperado 1 aviso, veio {r['total_avisos']}")
    # origem intacta
    checar(os.path.isfile(os.path.join(origem, "mdb7.log")), "B: origem foi tocada!")
    shutil.rmtree(base, ignore_errors=True)


# ── C) MD5 divergente em FOOTAGE -> FALHA CRITICA, ok False ──────────────────
def teste_md5_footage_falha_critica():
    base, origem, destino = montar_cartao()
    orig = instalar_copia_com_falhas(corromper_md5_em={"GOPR0001.MP4"})
    try:
        r = copiador.copiar(origem, destino, "TESTE_C")
    finally:
        restaurar_copia(orig)
    checar(not r["ok"], "C: ok deveria ser False (footage com MD5 divergente)")
    checar(r["total_falhos"] == 1, f"C: esperado 1 falha critica, veio {r['total_falhos']}")
    checar(r["total_avisos"] == 0, f"C: esperado 0 avisos, veio {r['total_avisos']}")
    shutil.rmtree(base, ignore_errors=True)


# ── E) .sppo carrega critical e systemWarnings ───────────────────────────────
def teste_sppo_atributos():
    base, origem, destino = montar_cartao()
    orig = instalar_copia_com_falhas(corromper_md5_em={"mdb7.log"})
    try:
        r = copiador.copiar(origem, destino, "TESTE_E")
    finally:
        restaurar_copia(orig)
    arvore = ET.parse(r["caminho_log"])
    raiz = arvore.getroot()
    summary = raiz.find("summary")
    checar(summary.get("systemWarnings") == "1",
           f"E: systemWarnings deveria ser 1, veio {summary.get('systemWarnings')}")
    checar(summary.get("failed") == "0",
           f"E: failed deveria ser 0, veio {summary.get('failed')}")
    # atributos critical por arquivo
    por_nome = {f.get("name"): f.get("critical") for f in raiz.find("files")}
    checar(por_nome.get("GOPR0001.MP4") == "yes", "E: MP4 deveria ser critical=yes")
    checar(por_nome.get("mdb7.log") == "no", "E: .log deveria ser critical=no")
    checar(por_nome.get("Get_started_with_GoPro.url") == "no", "E: .url deveria ser critical=no")
    shutil.rmtree(base, ignore_errors=True)


if __name__ == "__main__":
    teste_classificacao()
    teste_fallback_url()
    teste_md5_sistema_vira_aviso()
    teste_md5_footage_falha_critica()
    teste_sppo_atributos()

    print("\n" + "=" * 60)
    if falhas_globais:
        print(f"  {len(falhas_globais)} VERIFICACAO(OES) FALHARAM:")
        for f in falhas_globais:
            print(f"   - {f}")
        print("=" * 60 + "\n")
        sys.exit(1)
    print("  TODOS OS TESTES PASSARAM ✅")
    print("   A) fallback copy2->copyfile no .url")
    print("   B) MD5 divergente em arquivo de sistema -> AVISO (ok=True)")
    print("   C) MD5 divergente em footage -> FALHA CRITICA (ok=False)")
    print("   D) classificacao eh_arquivo_sistema()")
    print("   E) .sppo carrega critical + systemWarnings")
    print("=" * 60 + "\n")
    sys.exit(0)
