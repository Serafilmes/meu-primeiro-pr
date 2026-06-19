#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Teste da Fatia 3 do #5 — a planilha carrega raiz (Pasta) E curto (Nº cartão).
Banco isolado em /tmp; laboratório intocado.
"""
import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="gma_teste_c3_")
os.environ["GMA_DB"] = os.path.join(_tmp, "gma_teste.db")

import banco_dados as bd

falhas = []


def checar(condicao, descricao):
    print(f"  [{'OK ' if condicao else 'FALHOU'}] {descricao}")
    if not condicao:
        falhas.append(descricao)


def main():
    conn = bd.inicializar_banco()
    bd.criar_profissional(conn, "Fernando Dumitriu", {"video": True})

    # Ficha + cartão numerado + match (uma entrega completa).
    conn.execute("INSERT INTO formularios (nome, tipo_material, data_gravacao) "
                 "VALUES ('Fernando Dumitriu', 'VIDEO', '2026-06-19')")
    fid = conn.execute("SELECT id FROM formularios WHERE nome='Fernando Dumitriu'").fetchone()[0]
    conn.execute("INSERT INTO cartoes (volume, caminho_origem, numero_cartao, status, "
                 "total_arquivos_transferidos, tamanho_transferido_bytes) "
                 "VALUES ('VOL1', '/Volumes/VOL1', 'DUMITRIU_001', 'concluido', 106, 1024)")
    cid = conn.execute("SELECT id FROM cartoes WHERE numero_cartao='DUMITRIU_001'").fetchone()[0]
    conn.execute("INSERT INTO matches (cartao_id, formulario_id, score) VALUES (?, ?, 3)", (cid, fid))
    conn.commit()

    colunas, linhas = bd.montar_planilha(conn)
    rotulos = [c["rotulo"] for c in colunas]
    print("\nColunas:", rotulos)

    checar("Nome" in rotulos, "coluna 'Nome' (raiz) presente")
    checar("Cartão" in rotulos, "coluna 'Cartão' (curto) presente")

    # Acha a linha do nosso cartão e confere os valores.
    idx = {c["rotulo"]: i for i, c in enumerate(colunas)}
    linha = linhas[0]
    print("Linha:", {r: linha[idx[r]] for r in ("Nome", "Cartão")})

    checar(linha[idx["Nome"]] == "FERNANDO_DUMITRIU",
           f"Nome = FERNANDO_DUMITRIU (got {linha[idx['Nome']]})")
    checar(linha[idx["Cartão"]] == "DUMITRIU",
           f"Cartão = DUMITRIU (got {linha[idx['Cartão']]})")

    conn.close()

    print("\n" + "=" * 50)
    if falhas:
        print(f"❌ {len(falhas)} FALHA(S):")
        for f in falhas:
            print(f"   - {f}")
        raise SystemExit(1)
    print("✅ Todos os testes da Fatia 3 passaram.")


if __name__ == "__main__":
    main()
