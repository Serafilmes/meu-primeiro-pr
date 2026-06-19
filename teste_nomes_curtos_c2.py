#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Teste da Fatia 2 do #5 (nomes curtos na C2) — banco e destino isolados em /tmp.

Cobre:
  A) profissional cadastrado → pasta do dia = nome_raiz, cartão = nome_curto_NNN
  B) numeração incrementa por NOME CURTO (contador DUMITRIU.json)
  C) profissional NÃO cadastrado → fallback no nome sanitizado da ficha
"""
import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="gma_teste_c2_")
os.environ["GMA_DB"] = os.path.join(_tmp, "gma_teste.db")
os.environ["GMA_DESTINO"] = os.path.join(_tmp, "DESTINO")

import banco_dados as bd
import transferencia as tr

falhas = []


def checar(condicao, descricao):
    print(f"  [{'OK ' if condicao else 'FALHOU'}] {descricao}")
    if not condicao:
        falhas.append(descricao)


def main():
    conn = bd.inicializar_banco()
    bd.criar_profissional(conn, "Fernando Dumitriu", {"video": True})
    conn.close()

    form = {"nome": "Fernando Dumitriu", "data_gravacao": "2026-06-19", "tipo_material": "VIDEO"}
    material = {}

    # ── A) cadastrado → raiz + curto ──────────────────────────────────────────
    print("\nA) Profissional cadastrado")
    caminho = tr.montar_caminho_destino(material, form)
    partes = caminho.split(os.sep)
    checar("FERNANDO_DUMITRIU" in partes, f"pasta do dia = FERNANDO_DUMITRIU (caminho: {caminho})")
    checar(partes[-1] == "DUMITRIU_001", f"cartão = DUMITRIU_001 (got {partes[-1]})")

    # ── B) numeração por nome curto ───────────────────────────────────────────
    print("\nB) Numeração incrementa por nome curto")
    caminho2 = tr.montar_caminho_destino(material, form)
    checar(caminho2.split(os.sep)[-1] == "DUMITRIU_002",
           f"2º cartão = DUMITRIU_002 (got {caminho2.split(os.sep)[-1]})")
    contador = os.path.join(_tmp, "contadores", "DUMITRIU.json")
    checar(os.path.exists(contador), f"contador por curto existe: {contador}")

    # ── C) não cadastrado → fallback sanitizado ───────────────────────────────
    print("\nC) Profissional não cadastrado (fallback)")
    form_nc = {"nome": "Alguém Não Cadastrado", "data_gravacao": "2026-06-19", "tipo_material": "FOTO"}
    caminho3 = tr.montar_caminho_destino(material, form_nc)
    partes3 = caminho3.split(os.sep)
    checar(partes3[-2] == "ALGUEM_NAO_CADASTRADO",
           f"fallback sem acento, ASCII limpo (pasta dia: {partes3[-2]})")
    checar(partes3[-1].endswith("_001"),
           f"cartão fallback numerado _001 (got {partes3[-1]})")

    print("\n" + "=" * 50)
    if falhas:
        print(f"❌ {len(falhas)} FALHA(S):")
        for f in falhas:
            print(f"   - {f}")
        raise SystemExit(1)
    print("✅ Todos os testes da Fatia 2 passaram.")


if __name__ == "__main__":
    main()
