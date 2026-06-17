#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Povoa o PROJETO-FESTIVAL "Rock in Rio (teste)" num banco SEPARADO do laboratório.

Princípio (multi-projeto por trabalho): cada evento é uma instância própria. Aqui
isso é feito do jeito barato — um gma.db só para este projeto — apontando a
variável de ambiente GMA_DB para ele ANTES de importar o banco_dados. O laboratório
(o gma.db da raiz) fica intocado.

Como usar:
    /usr/bin/python3 projetos/rock_in_rio/seed_rock_in_rio.py

Para rodar o SISTEMA neste projeto depois:
    GMA_DB="projetos/rock_in_rio/gma.db" /usr/bin/python3 inicializar_gma.py

O script é idempotente: rodar de novo não duplica nem quebra (ignora o que já existe).
"""

import os
import sys
import sqlite3

# Raiz do GMA e caminho deste projeto.
RAIZ_GMA = "/Users/serafa/GMA"
BANCO_PROJETO = os.path.join(RAIZ_GMA, "projetos", "rock_in_rio", "gma.db")

# 1) Aponta o banco ANTES de importar o módulo (o banco_dados lê GMA_DB na importação).
os.makedirs(os.path.dirname(BANCO_PROJETO), exist_ok=True)
os.environ["GMA_DB"] = BANCO_PROJETO
sys.path.insert(0, RAIZ_GMA)

import banco_dados as bd  # noqa: E402  (precisa vir depois de setar GMA_DB)


# ── Dados do festival ─────────────────────────────────────────────────────────

# Profissionais (da lista enviada). Tipo define o filtro do dropdown da ficha.
CINEGRAFISTAS = [  # tipo vídeo
    "FERNANDO EUGEN GOUVEIA DE ALMEIDA DUMITRIU",
    "LEONARDO BRANDÃO DE MELLO",
    "NICOLAS FERANDES DE SOUZA SADOYAMA",
    "ANDRE LUIS CORREA MONTEIRO",
    "MARCOS DE SOUZA GOUVEA FILHO",
    "RAFAEL PORTO DE OLIVEIRA",
    "JOÃO ALEXANDRE DA SILVA JÚNIOR",
    "MARCO ANTÔNIO DE OLIVEIRA SANTOS DA SILVA",
    "YAN ANTUNES AUGUSTO",
    "ANDRÉ LUIZ RODRIGUES",
    "ERICK RANGEL CALABRIA",
    "LUCAS JONES DIAS",
    "PHILLIP MARTINS CORREIA",
    "BRUNO ROCHA DA SILVA",
    "CHRISTOFFER PIXININE GONÇALVES",
    "RENAN DO CARMO VIEIRA",
    "DANIEL LEE LÚCIO BARBOZA",
    "FABIO NOMURA",
]

FOTOGRAFOS = [  # tipo foto
    "DIEGO MARCELLO PADILHA DE OLIVEIRA PEREIRA",
    "ANDRÉ LUIZ DE SOUZA MELLO",
    "FABIANO NUNES DA CUNHA BATTAGLIN",
    "CARLOS ERBS DOS SANTOS JUNIOR",
    "LEONARDO DA SILVA MARINHO",
    "ROBERTO SOUZA TEIXEIRA",
    "MARCIO MERCANTE CARREIRA",
    "MARCELO HENRIQUE NEVES MARTINS",
    "MARCUS FERREIRA MENDONÇA",
    "CARLOS EDUARDO PILOTTO",
]

# Grupos novos do festival (palco/marca/tag já vêm do schema padrão).
# (rótulo, múltipla?, modo)
GRUPOS_NOVOS = [
    ("Show",     True,  "lista"),   # vira a cada dia — itens entram na Fatia B (programação)
    ("Lugares",  True,  "lista"),
    ("Momentos", True,  "lista"),
]

# Itens dos grupos de SISTEMA (chave fixa conhecida).
ITENS_SISTEMA = {
    "palco": [  # os 6 palcos reais do Rock in Rio
        "Palco Mundo", "Sunset", "New Dance Order",
        "Espaço Favela", "Global Village", "Supernova",
    ],
    "marca": [  # patrocinadores reais do Rock in Rio 2026 (lidos do site)
        "Itaú",            # patrocinador master
        "Heineken", "Coca-Cola", "Seara", "Ipiranga", "KitKat", "Prudential",
        "TIM", "Natura", "Doritos", "Superbet", "iFood", "C&A", "Volkswagen",
    ],
}

# Itens dos grupos NOVOS, por rótulo (a chave real, com prefixo custom_, é
# resolvida em tempo de execução a partir do retorno de criar_grupo).
ITENS_NOVOS = {
    "Lugares": [
        "Roda-gigante", "Tirolesa", "Pórtico",
        "Praça de alimentação", "Espaço instagramável", "Mirante",
    ],
    "Momentos": [
        "Abertura", "Pôr do sol", "Fogos", "Brinde", "Público", "Encerramento",
    ],
    # "Show" fica VAZIO de propósito: o line-up entra pela programação do dia (Fatia B).
}


# ── Helpers idempotentes ──────────────────────────────────────────────────────

def add_profissional(conn, nome, tipos):
    try:
        bd.criar_profissional(conn, nome, tipos)
        return "novo"
    except sqlite3.IntegrityError:
        return "já existia"


def add_grupo(conn, rotulo, multipla, modo):
    """Cria o grupo (ou reaproveita) e devolve (chave_real, status)."""
    try:
        g = bd.criar_grupo(conn, rotulo, multipla=multipla, modo=modo)
        return g["chave"], "novo"
    except sqlite3.IntegrityError:
        return bd._slug_grupo(rotulo), "já existia"


def add_item(conn, tipo, valor):
    try:
        bd.adicionar_item_lista(conn, tipo, valor)
        return True
    except sqlite3.IntegrityError:
        return False


# ── Execução ──────────────────────────────────────────────────────────────────

def main():
    print(f"Projeto:  Rock in Rio (teste)")
    print(f"Banco:    {BANCO_PROJETO}")
    print(f"(o gma.db do laboratório NÃO é tocado)\n")

    # Cria/garante o schema + grupos de sistema padrão neste banco isolado.
    conn = bd.inicializar_banco()

    # 1) Profissionais
    print("— Profissionais —")
    nv = nv_e = 0
    for nome in CINEGRAFISTAS:
        if add_profissional(conn, nome, {"video": True}) == "novo": nv += 1
        else: nv_e += 1
    nf = nf_e = 0
    for nome in FOTOGRAFOS:
        if add_profissional(conn, nome, {"foto": True}) == "novo": nf += 1
        else: nf_e += 1
    print(f"  vídeo: {nv} novos ({nv_e} já existiam) · foto: {nf} novos ({nf_e} já existiam)")

    # 2) Grupos novos do festival (guarda a chave real de cada um)
    print("— Grupos —")
    chave_de = {}
    for rotulo, multipla, modo in GRUPOS_NOVOS:
        chave, status = add_grupo(conn, rotulo, multipla, modo)
        chave_de[rotulo] = chave
        print(f"  {rotulo} ({chave}): {status}")

    # Ajustes nos grupos para a cara do festival (reversível pelo painel):
    #  - Palco: MÚLTIPLA (uma pessoa pode cobrir mais de um palco; a cascata soma
    #    os shows dos palcos marcados).
    #  - Pauta, Serviço e Tags: desligados — ficha mais limpa e objetiva (o
    #    idealizador não usa esses no festival). DESATIVA (ativo=0), não exclui:
    #    excluir um grupo de sistema faz o re-seed do boot recriá-lo ativo; com a
    #    linha desativada, o INSERT OR IGNORE do seed a respeita e fica off.
    bd.definir_multipla_grupo(conn, "palco", True)
    for chave in ("pauta", "servico", "tag"):
        try:
            bd.definir_ativo_grupo(conn, chave, False)
        except Exception:
            pass

    # 3) Itens das listas (só funciona depois dos grupos existirem).
    # Junta os de sistema (chave fixa) com os novos (chave resolvida acima).
    print("— Itens —")
    itens_por_chave = dict(ITENS_SISTEMA)
    for rotulo, valores in ITENS_NOVOS.items():
        itens_por_chave[chave_de[rotulo]] = valores
    for tipo, valores in itens_por_chave.items():
        novos = sum(1 for v in valores if add_item(conn, tipo, v))
        print(f"  {tipo}: {novos}/{len(valores)} adicionados")

    # 3b) Reconcilia as MARCAS: remove itens fora da lista oficial (placeholders
    # antigos como Trident/Claro). Só remove se não estiver em uso; senão desativa.
    oficiais = set(ITENS_SISTEMA["marca"])
    removidas = 0
    for it in bd.listar_itens_lista(conn, tipo="marca"):
        if it["valor"] not in oficiais:
            try:
                bd.excluir_item_lista(conn, it["id"])
            except Exception:
                bd.definir_ativo_item_lista(conn, it["id"], False)
            removidas += 1
    if removidas:
        print(f"  marca: {removidas} item(ns) fora da lista removido(s)/desativado(s)")

    # 4) Garante uma coluna de planilha por grupo (espelha na /planilha e no Sheets)
    bd.sincronizar_colunas_grupos(conn)

    conn.close()
    print("\nPronto. Para abrir a ficha do festival:")
    print('  GMA_DB="projetos/rock_in_rio/gma.db" /usr/bin/python3 inicializar_gma.py')


if __name__ == "__main__":
    main()
