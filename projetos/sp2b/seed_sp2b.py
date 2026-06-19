#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Povoa o PROJETO "SP2B (teste)" num banco SEPARADO do laboratório.

SP2B = São Paulo Beyond Business — festival de inovação estilo SXSW, no Parque
Ibirapuera (09–16/ago/2026). É um evento do tipo CONGRESSO (como o RIO2C): em vez
de "palco→show" (festival de música), a lógica é "trilha→palco→painel". Este seed
prova a generalização festival→congresso reaproveitando TODO o mecanismo já pronto
(grupos editáveis, chips na ficha, coluna na planilha, programação do dia).

Decisões deste seed (desenhadas a partir da planilha de referência do RIO2C, que
tem as colunas variáveis PALCOS · EXPERIÊNCIAS(marcas) · SERVIÇOS(locais) · TAGS):
  - Profissionais: FICTÍCIOS — reaproveita os nomes que já temos (os 28 do Rock in
    Rio) só para dar "uma cara" ao sistema e exercitar as funcionalidades.
  - Vocabulário REAL capturado do site sp2b.com.br (trilhas, palcos, locais,
    parceiros).
  - "Painéis" é o equivalente do "Show" do festival: nasce VAZIO; a grade de
    painéis entra depois, pela programação do dia / importação de fontes (a grade
    ainda não foi publicada a ~50 dias do evento).

Como usar:
    /usr/bin/python3 projetos/sp2b/seed_sp2b.py

Para rodar o SISTEMA neste projeto depois (ou troque pelo Painel de Controle):
    GMA_DB="projetos/sp2b/gma.db" /usr/bin/python3 inicializar_gma.py

O script é idempotente: rodar de novo não duplica nem quebra (ignora o que já existe).
"""

import os
import sys
import sqlite3

# Raiz do GMA e caminho deste projeto.
RAIZ_GMA = "/Users/serafa/GMA"
BANCO_PROJETO = os.path.join(RAIZ_GMA, "projetos", "sp2b", "gma.db")

# 1) Aponta o banco ANTES de importar o módulo (o banco_dados lê GMA_DB na importação).
os.makedirs(os.path.dirname(BANCO_PROJETO), exist_ok=True)
os.environ["GMA_DB"] = BANCO_PROJETO
sys.path.insert(0, RAIZ_GMA)

import banco_dados as bd  # noqa: E402  (precisa vir depois de setar GMA_DB)


# ── Profissionais (FICTÍCIOS — nomes reaproveitados só para dar cara ao sistema) ──

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


# ── Grupos NOVOS do congresso (palco/marca/servico/tag já vêm do schema padrão) ──
# (rótulo, múltipla?, modo)
GRUPOS_NOVOS = [
    ("Trilhas", True, "lista"),   # a camada a mais do congresso: trilha agrupa palcos
    ("Painéis", True, "lista"),   # equivalente do "Show": nasce VAZIO (programação preenche)
]

# Itens dos grupos de SISTEMA (chave fixa conhecida).
ITENS_SISTEMA = {
    "palco": [  # os 9 palcos "BE…" reais do SP2B (lidos do site)
        "BESPOKE", "BESIDE", "BEATS", "BELONG", "BEGINNING",
        "BELIEVE", "BEYOND", "BEEHIVE", "BETWEEN",
    ],
    # SERVIÇOS no RIO2C = LOCAIS. Aqui o grupo de sistema "servico" é renomeado para
    # "Locais" (abaixo) e recebe as áreas físicas do Parque Ibirapuera.
    "servico": [
        "Auditório Ibirapuera", "Jardim do Auditório", "Marquise", "OCA",
        "Museu Afro Brasil", "Planetário", "Pacubra", "Pavilhão da Bienal",
        "Praça de Alimentação", "MAM (Estacionamento)",
    ],
    "marca": [  # patrocinadores/parceiros reais do SP2B (lidos do site)
        "Prefeitura de São Paulo", "Governo do Estado de SP", "B3", "Globo",
        "LinkedIn", "Billboard", "Ticketmaster", "Urbia", "ESPM",
        "Eletromidia", "SPCine", "Invest SP", "Musicalize", "DA20",
    ],
    "tag": [  # categorias de CONTEÚDO/formato (equivale ao TAGS do RIO2C)
        "Keynote", "Painel", "Talk", "Workshop", "Show",
        "Entrevista", "Ativação de marca", "Networking", "Bastidores",
    ],
}

# Itens dos grupos NOVOS, por rótulo (a chave real, com prefixo custom_, é
# resolvida em tempo de execução a partir do retorno de criar_grupo).
ITENS_NOVOS = {
    "Trilhas": [
        "Business Area", "Transformação", "Reconhecimento",
        "Vibração", "Inspiração",
    ],
    # "Painéis" fica VAZIO de propósito: a grade entra pela programação do dia /
    # importação de fontes, quando o site publicar.
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


def reconciliar_itens(conn, tipo, oficiais):
    """Remove itens fora da lista oficial (placeholders de teste). Só remove se
    não estiver em uso; senão desativa."""
    oficiais = set(oficiais)
    mexidos = 0
    for it in bd.listar_itens_lista(conn, tipo=tipo):
        if it["valor"] not in oficiais:
            try:
                bd.excluir_item_lista(conn, it["id"])
            except Exception:
                bd.definir_ativo_item_lista(conn, it["id"], False)
            mexidos += 1
    return mexidos


# ── Execução ──────────────────────────────────────────────────────────────────

def main():
    print("Projeto:  SP2B (teste) — congresso/festival de inovação")
    print(f"Banco:    {BANCO_PROJETO}")
    print("(o gma.db do laboratório NÃO é tocado)\n")

    # Cria/garante o schema + grupos de sistema padrão neste banco isolado.
    conn = bd.inicializar_banco()

    # 1) Profissionais (fictícios)
    print("— Profissionais (fictícios) —")
    nv = nv_e = 0
    for nome in CINEGRAFISTAS:
        if add_profissional(conn, nome, {"video": True}) == "novo": nv += 1
        else: nv_e += 1
    nf = nf_e = 0
    for nome in FOTOGRAFOS:
        if add_profissional(conn, nome, {"foto": True}) == "novo": nf += 1
        else: nf_e += 1
    print(f"  vídeo: {nv} novos ({nv_e} já existiam) · foto: {nf} novos ({nf_e} já existiam)")

    # 2) Grupos novos do congresso (guarda a chave real de cada um)
    print("— Grupos —")
    chave_de = {}
    for rotulo, multipla, modo in GRUPOS_NOVOS:
        chave, status = add_grupo(conn, rotulo, multipla, modo)
        chave_de[rotulo] = chave
        print(f"  {rotulo} ({chave}): {status}")

    # Ajustes nos grupos para a cara do congresso (tudo reversível pelo painel):
    #  - "servico" vira "Locais" (no RIO2C, a coluna SERVIÇOS guardava os locais).
    #  - palco/servico/marca/tag MÚLTIPLOS (uma captação cobre vários).
    #  - Pauta desligada — não usada neste evento (desativa, não exclui: o re-seed
    #    do boot recriaria um grupo de sistema excluído; desativado ele respeita).
    try:
        bd.renomear_grupo(conn, "servico", "Locais")
    except Exception:
        pass
    for chave in ("palco", "servico", "marca", "tag"):
        try:
            bd.definir_multipla_grupo(conn, chave, True)
        except Exception:
            pass
    try:
        bd.definir_ativo_grupo(conn, "pauta", False)
    except Exception:
        pass

    # 3) Itens das listas (só funciona depois dos grupos existirem).
    print("— Itens —")
    itens_por_chave = dict(ITENS_SISTEMA)
    for rotulo, valores in ITENS_NOVOS.items():
        itens_por_chave[chave_de[rotulo]] = valores
    for tipo, valores in itens_por_chave.items():
        novos = sum(1 for v in valores if add_item(conn, tipo, v))
        print(f"  {tipo}: {novos}/{len(valores)} adicionados")

    # 3b) Reconcilia palco/servico/marca/tag: remove placeholders fora da lista
    #     oficial (sobras de teste). Não toca em item em uso.
    for tipo, valores in ITENS_SISTEMA.items():
        n = reconciliar_itens(conn, tipo, valores)
        if n:
            print(f"  {tipo}: {n} item(ns) fora da lista removido(s)/desativado(s)")

    # 4) Garante uma coluna de planilha por grupo (espelha na /planilha e no Sheets)
    bd.sincronizar_colunas_grupos(conn)

    conn.close()
    print("\nPronto. Para abrir a ficha do SP2B:")
    print('  GMA_DB="projetos/sp2b/gma.db" /usr/bin/python3 inicializar_gma.py')
    print("  (ou troque para o projeto SP2B pelo Painel de Controle)")


if __name__ == "__main__":
    main()
