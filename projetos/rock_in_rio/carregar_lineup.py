#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Carrega o line-up real (lineup_2026.json) na PROGRAMAÇÃO do projeto Rock in Rio.

O que faz (idempotente):
  - cria cada show como item do grupo "Show" (listas_contexto), e
  - liga (dia · palco · show) na tabela `programacao`.

Os palcos já existem (criados pelo seed). Os shows entram aqui porque mudam por
dia — eles são a "virada da ficha".

Uso:
    /usr/bin/python3 projetos/rock_in_rio/carregar_lineup.py
"""

import os
import sys
import json
import sqlite3

RAIZ_GMA = "/Users/serafa/GMA"
BANCO_PROJETO = os.path.join(RAIZ_GMA, "projetos", "rock_in_rio", "gma.db")
ARQUIVO_LINEUP = os.path.join(RAIZ_GMA, "projetos", "rock_in_rio", "lineup_2026.json")

os.environ["GMA_DB"] = BANCO_PROJETO
sys.path.insert(0, RAIZ_GMA)
import banco_dados as bd  # noqa: E402


def chave_grupo_show(conn):
    """
    Acha a chave do grupo 'Show'. Se ele não existir (ex.: foi excluído no
    painel), recria — o grupo Show é essencial para a programação do dia.
    """
    row = conn.execute(
        "SELECT chave FROM grupos_classificacao WHERE LOWER(rotulo) = 'show'"
    ).fetchone()
    if row:
        return row[0]
    g = bd.criar_grupo(conn, "Show", multipla=True, modo="lista")
    print("  (grupo 'Show' não existia — recriado)")
    return g["chave"]


def mapa_palcos(conn):
    """{valor do palco -> id do item} para os palcos cadastrados."""
    return {r[1]: r[0] for r in conn.execute(
        "SELECT id, valor FROM listas_contexto WHERE tipo = 'palco'"
    ).fetchall()}


def garantir_show(conn, chave_show, nome):
    """Cria o show (se preciso) e devolve o id do item."""
    try:
        bd.adicionar_item_lista(conn, chave_show, nome)
    except sqlite3.IntegrityError:
        pass  # já existia
    row = conn.execute(
        "SELECT id FROM listas_contexto WHERE tipo = ? AND valor = ?",
        (chave_show, nome),
    ).fetchone()
    return row[0] if row else None


def main():
    dados = json.load(open(ARQUIVO_LINEUP, encoding="utf-8"))
    conn = bd.inicializar_banco()

    chave_show = chave_grupo_show(conn)
    palcos = mapa_palcos(conn)
    print(f"Grupo de shows: {chave_show}")
    print(f"Palcos cadastrados: {', '.join(palcos.keys())}\n")

    shows_novos = 0
    linhas = 0
    sem_palco = set()

    for dia, por_palco in dados["dias"].items():
        for nome_palco, shows in por_palco.items():
            palco_id = palcos.get(nome_palco)
            if palco_id is None:
                sem_palco.add(nome_palco)
                continue
            for nome_show in shows:
                antes = conn.execute(
                    "SELECT COUNT(*) FROM listas_contexto WHERE tipo = ? AND valor = ?",
                    (chave_show, nome_show),
                ).fetchone()[0]
                show_id = garantir_show(conn, chave_show, nome_show)
                if antes == 0:
                    shows_novos += 1
                bd.adicionar_programacao(conn, dia, palco_id, show_id)
                linhas += 1

    print(f"Shows criados (novos): {shows_novos}")
    print(f"Linhas de programação processadas: {linhas}")
    if sem_palco:
        print(f"ATENÇÃO — palcos do JSON sem item cadastrado: {sorted(sem_palco)}")

    # Confirma e deixa o 1º dia como ativo (se nenhum dia ativo fizer sentido).
    dias = bd.dias_com_programacao(conn)
    print(f"\nDias com programação: {dias}")
    for d in dias:
        n = len(bd.shows_do_dia(conn, d))
        print(f"  {d}: {n} shows")
    if dias:
        bd.definir_dia_ativo(conn, dias[0])
        print(f"\nDia ativo: {bd.dia_ativo(conn)}")
    # Garante a coluna 'Show' na planilha (caso o grupo tenha sido recriado).
    bd.sincronizar_colunas_grupos(conn)
    conn.close()


if __name__ == "__main__":
    main()
