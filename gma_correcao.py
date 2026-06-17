#!/usr/bin/env python3
"""
gma_correcao.py
Ferramenta de correção de registros de check-in do GMA.

Princípio: nunca deletar, sempre corrigir com histórico.
Cada correção é um novo registro que referencia o original.
O log é append-only — como contabilidade.

Uso:
    python gma_correcao.py                      # modo interativo
    python gma_correcao.py --buscar CART_042    # busca direta
    python gma_correcao.py --auditoria          # relatório de correções
    python gma_correcao.py --duplicatas         # lista possíveis duplicatas

Depende do arquivo de log JSON gerado pelo sistema GMA (gma_log.jsonl).
"""

import json
import os
import sys
import argparse
from datetime import datetime
from pathlib import Path


# ── CONFIGURAÇÃO ──────────────────────────────────────────────────────────────

LOG_PADRAO = "gma_log.jsonl"     # um registro JSON por linha
CAMPOS_EDITAVEIS = [
    "nome",          # nome da produtora / equipe
    "operador",      # operador que fez o check-in
    "tipo_material", # VIDEO, FOTO, AUDIO, MISTO
    "camera",        # modelo de câmera detectado
    "observacoes",   # campo livre
]

CORES = {
    "verde":    "\033[92m",
    "amarelo":  "\033[93m",
    "vermelho": "\033[91m",
    "azul":     "\033[94m",
    "cinza":    "\033[90m",
    "reset":    "\033[0m",
    "negrito":  "\033[1m",
}

def cor(texto, nome_cor):
    """Aplica cor ANSI se o terminal suportar."""
    if sys.stdout.isatty():
        return f"{CORES.get(nome_cor, '')}{texto}{CORES['reset']}"
    return texto


# ── LEITURA E ESCRITA DO LOG ──────────────────────────────────────────────────

def carregar_log(caminho_log):
    """Carrega todos os registros do log JSONL. Retorna lista de dicts."""
    registros = []
    if not os.path.exists(caminho_log):
        return registros
    with open(caminho_log, "r", encoding="utf-8") as f:
        for linha in f:
            linha = linha.strip()
            if linha:
                try:
                    registros.append(json.loads(linha))
                except json.JSONDecodeError:
                    pass
    return registros


def salvar_registro(caminho_log, registro):
    """Acrescenta um único registro ao final do log (append-only)."""
    with open(caminho_log, "a", encoding="utf-8") as f:
        f.write(json.dumps(registro, ensure_ascii=False) + "\n")
    return registro


def estado_atual(registros, ref_id):
    """
    Reconstrói o estado atual de um registro aplicando todas as
    correções em ordem cronológica. Retorna o dict com valores vigentes.
    """
    original = next((r for r in registros if r.get("id") == ref_id
                     and r.get("tipo") != "correcao"), None)
    if not original:
        return None

    estado = dict(original)

    correcoes = sorted(
        [r for r in registros
         if r.get("tipo") == "correcao" and r.get("ref_id") == ref_id],
        key=lambda x: x.get("ts", "")
    )
    for c in correcoes:
        campo = c.get("campo")
        if campo:
            estado[campo] = c.get("valor_novo", "")
        if c.get("status_novo"):
            estado["status"] = c["status_novo"]

    estado["_correcoes"] = len(correcoes)
    return estado


# ── BUSCA DE REGISTROS ────────────────────────────────────────────────────────

def buscar_registros(registros, termo):
    """
    Busca registros originais (não correções) por:
    - ID exato ou parcial
    - Nome da produtora
    - Número de cartão
    Retorna lista de estados atuais.
    """
    termo_lower = termo.lower()
    encontrados = []
    ids_vistos = set()

    for r in registros:
        if r.get("tipo") == "correcao":
            continue
        rid = r.get("id", "")
        if rid in ids_vistos:
            continue
        ids_vistos.add(rid)

        estado = estado_atual(registros, rid)
        if not estado:
            continue

        campos_busca = [
            estado.get("id", ""),
            estado.get("nome", ""),
            estado.get("num_cartao", ""),
            estado.get("operador", ""),
        ]
        if any(termo_lower in str(c).lower() for c in campos_busca):
            encontrados.append(estado)

    return encontrados


# ── EXIBIÇÃO ──────────────────────────────────────────────────────────────────

def exibir_registro(estado, mostrar_historico=False, registros_todos=None):
    """Exibe um registro formatado no terminal."""
    print()
    marcador = cor("▶", "verde") if estado.get("status") == "checkin_ok" else cor("!", "amarelo")
    print(f"  {marcador}  {cor(estado.get('id', '—'), 'negrito')}", end="")
    if estado.get("_correcoes", 0) > 0:
        print(f"  {cor(f'[{estado[\"_correcoes\"]} correção(ões)]', 'amarelo')}", end="")
    print()

    linhas = [
        ("Nome / produtora",  "nome"),
        ("Operador",          "operador"),
        ("Tipo de material",  "tipo_material"),
        ("Câmera",            "camera"),
        ("Data captura",      "data_captura"),
        ("Observações",       "observacoes"),
        ("Status",            "status"),
        ("Check-in em",       "ts"),
    ]
    for label, campo in linhas:
        val = estado.get(campo)
        if val:
            print(f"     {cor(label + ':', 'cinza'):<28} {val}")

    if mostrar_historico and registros_todos:
        correcoes = [r for r in registros_todos
                     if r.get("tipo") == "correcao"
                     and r.get("ref_id") == estado.get("id")]
        if correcoes:
            print(f"\n     {cor('Histórico de correções:', 'cinza')}")
            for c in sorted(correcoes, key=lambda x: x.get("ts", "")):
                ts = c.get("ts", "")[:19]
                campo = c.get("campo", c.get("status_novo", "?"))
                antes = c.get("valor_anterior", "—")
                depois = c.get("valor_novo", c.get("status_novo", "—"))
                op_c = c.get("op_correcao", "?")
                motivo = c.get("motivo", "")
                print(f"       {cor(ts, 'cinza')}  {campo}: "
                      f"{cor(antes, 'vermelho')} → {cor(depois, 'verde')}  "
                      f"por {op_c}" + (f"  ({motivo})" if motivo else ""))
    print()


# ── FLUXO DE CORREÇÃO INTERATIVA ──────────────────────────────────────────────

def fazer_correcao(caminho_log, registros, estado, operador):
    """
    Guia o operador pelo processo de correção de um registro.
    Grava o registro de correção e retorna o ID gerado.
    """
    ref_id = estado.get("id")

    print(cor("\n  Campos disponíveis para correção:", "azul"))
    campos_disponiveis = [c for c in CAMPOS_EDITAVEIS if estado.get(c)]

    for i, campo in enumerate(campos_disponiveis, 1):
        valor_atual = estado.get(campo, "—")
        print(f"    {i}. {campo:<20} {cor(valor_atual, 'negrito')}")

    print(f"    {len(campos_disponiveis)+1}. {cor('Suspender registro', 'amarelo')} (cartão voltou ao set)")
    print(f"    {len(campos_disponiveis)+2}. {cor('Anular registro', 'vermelho')} (check-in duplicado)")
    print(f"    0. Cancelar")

    escolha = input("\n  Qual campo corrigir? ").strip()
    if escolha == "0" or not escolha:
        print(cor("  Cancelado.", "cinza"))
        return None

    ts_agora = datetime.now().isoformat(timespec="seconds")
    id_correcao = f"{ref_id}-COR-{ts_agora[11:19].replace(':', '')}"

    try:
        n = int(escolha)
    except ValueError:
        print(cor("  Opção inválida.", "vermelho"))
        return None

    registro_correcao = {
        "id":          id_correcao,
        "ts":          ts_agora,
        "tipo":        "correcao",
        "ref_id":      ref_id,
        "op_correcao": operador,
    }

    if 1 <= n <= len(campos_disponiveis):
        campo = campos_disponiveis[n - 1]
        valor_atual = estado.get(campo, "")
        print(f"\n  Campo:         {cor(campo, 'cinza')}")
        print(f"  Valor atual:   {cor(valor_atual, 'amarelo')}")
        valor_novo = input("  Valor correto: ").strip()

        if not valor_novo:
            print(cor("  Nenhum valor digitado. Cancelado.", "cinza"))
            return None

        motivo = input("  Motivo (opcional, Enter para pular): ").strip()

        registro_correcao.update({
            "campo":          campo,
            "valor_anterior": valor_atual,
            "valor_novo":     valor_novo,
            "motivo":         motivo,
        })

    elif n == len(campos_disponiveis) + 1:
        # Suspensão
        motivo = input("  Motivo da suspensão: ").strip()
        registro_correcao.update({
            "campo":      "status",
            "status_novo": "suspenso",
            "valor_anterior": estado.get("status", ""),
            "valor_novo":     "suspenso",
            "motivo":     motivo or "cartão retornou ao set",
        })

    elif n == len(campos_disponiveis) + 2:
        # Anulação
        ref_duplicata = input("  ID do registro correto (que permanece): ").strip()
        motivo = input("  Motivo da anulação: ").strip()
        registro_correcao.update({
            "campo":       "status",
            "status_novo": "anulado",
            "valor_anterior": estado.get("status", ""),
            "valor_novo":     "anulado",
            "ref_duplicata":  ref_duplicata,
            "motivo":      motivo or "check-in duplicado",
        })
    else:
        print(cor("  Opção inválida.", "vermelho"))
        return None

    # Confirmação
    print()
    print(cor("  Confirmar correção:", "azul"))
    print(f"    Registro:  {ref_id}")
    if "campo" in registro_correcao and registro_correcao.get("campo") != "status":
        print(f"    Campo:     {registro_correcao['campo']}")
        print(f"    De:        {cor(registro_correcao.get('valor_anterior',''), 'vermelho')}")
        print(f"    Para:      {cor(registro_correcao.get('valor_novo',''), 'verde')}")
    else:
        print(f"    Ação:      {cor(registro_correcao.get('status_novo',''), 'amarelo')}")
    if registro_correcao.get("motivo"):
        print(f"    Motivo:    {registro_correcao['motivo']}")

    conf = input("\n  Confirmar? [s/N] ").strip().lower()
    if conf != "s":
        print(cor("  Cancelado.", "cinza"))
        return None

    salvar_registro(caminho_log, registro_correcao)
    print(cor(f"\n  Correção gravada: {id_correcao}", "verde"))

    # Avisa sobre pasta se o campo nome foi alterado
    if registro_correcao.get("campo") == "nome":
        print(cor("\n  Atenção: o nome da pasta no disco pode precisar ser renomeado.", "amarelo"))
        print(f"  Nome anterior da pasta: {registro_correcao['valor_anterior']}")
        print(f"  Nome novo:              {registro_correcao['valor_novo']}")
        renomear = input("  Tentar renomear a pasta agora? [s/N] ").strip().lower()
        if renomear == "s":
            renomear_pasta(estado, registro_correcao)

    return id_correcao


def renomear_pasta(estado, correcao):
    """Renomeia a pasta no disco de forma segura, com verificação."""
    pasta_base = estado.get("pasta_destino", "")
    if not pasta_base:
        print(cor("  Caminho da pasta não encontrado no registro.", "cinza"))
        return

    nome_antigo = correcao.get("valor_anterior", "")
    nome_novo   = correcao.get("valor_novo", "")

    pasta_atual = Path(pasta_base) / nome_antigo
    pasta_nova  = Path(pasta_base) / nome_novo

    if not pasta_atual.exists():
        print(cor(f"  Pasta não encontrada: {pasta_atual}", "vermelho"))
        return

    if pasta_nova.exists():
        print(cor(f"  Conflito: pasta '{nome_novo}' já existe. Renomeação cancelada.", "vermelho"))
        return

    try:
        pasta_atual.rename(pasta_nova)
        print(cor(f"  Pasta renomeada: {pasta_atual} → {pasta_nova}", "verde"))
    except OSError as e:
        print(cor(f"  Erro ao renomear: {e}", "vermelho"))


# ── RELATÓRIO DE AUDITORIA ────────────────────────────────────────────────────

def relatorio_auditoria(registros):
    """Lista todas as correções do evento para fins de auditoria."""
    correcoes = [r for r in registros if r.get("tipo") == "correcao"]

    if not correcoes:
        print(cor("\n  Nenhuma correção registrada neste evento.\n", "cinza"))
        return

    print(cor(f"\n  Correções registradas: {len(correcoes)}\n", "azul"))
    print(f"  {'Timestamp':<22} {'Registro':<22} {'Campo':<16} {'De':<20} {'Para':<20} {'Por'}")
    print("  " + "─" * 110)

    for c in sorted(correcoes, key=lambda x: x.get("ts", "")):
        ts = c.get("ts", "")[:19]
        ref = c.get("ref_id", "?")[:20]
        campo = c.get("campo", c.get("status_novo", "?"))[:14]
        antes = str(c.get("valor_anterior", "—"))[:18]
        depois = str(c.get("valor_novo", c.get("status_novo", "—")))[:18]
        op_c = c.get("op_correcao", "?")[:12]
        print(f"  {ts:<22} {ref:<22} {campo:<16} {antes:<20} {depois:<20} {op_c}")

    print()


# ── DETECTOR DE DUPLICATAS ────────────────────────────────────────────────────

def detectar_duplicatas(registros):
    """
    Detecta registros originais com mesmo nome+data que podem ser duplicatas.
    Não detecta automaticamente como erro — só alerta para revisão humana.
    """
    originais = [r for r in registros if r.get("tipo") != "correcao"
                 and r.get("status") not in ("anulado",)]

    vistos = {}
    duplicatas = []

    for r in originais:
        chave = (
            r.get("nome", "").lower().strip(),
            r.get("data_captura", "")[:10],
        )
        if chave in vistos:
            duplicatas.append((vistos[chave], r))
        else:
            vistos[chave] = r

    if not duplicatas:
        print(cor("\n  Nenhuma duplicata suspeita encontrada.\n", "verde"))
        return

    print(cor(f"\n  {len(duplicatas)} par(es) suspeito(s) de duplicata:\n", "amarelo"))
    for a, b in duplicatas:
        print(f"    {cor(a['id'], 'negrito')}  ←→  {cor(b['id'], 'negrito')}")
        print(f"    Nome: {a.get('nome')}  |  Data: {a.get('data_captura','')[:10]}")
        print(f"    Registrados em: {a.get('ts','')[:19]}  e  {b.get('ts','')[:19]}")
        print()


# ── MODO INTERATIVO PRINCIPAL ─────────────────────────────────────────────────

def modo_interativo(caminho_log):
    registros = carregar_log(caminho_log)
    total = sum(1 for r in registros if r.get("tipo") != "correcao")

    print(cor("\n  GMA — Correção de registros", "negrito"))
    print(f"  Log: {caminho_log}  |  Registros: {total}")
    print()

    operador = input("  Seu nome (operador de correção): ").strip()
    if not operador:
        operador = "desconhecido"

    while True:
        print(cor("\n  O que fazer?", "azul"))
        print("    1. Buscar e corrigir um registro")
        print("    2. Ver relatório de auditoria")
        print("    3. Verificar duplicatas suspeitas")
        print("    0. Sair")

        op = input("\n  Opção: ").strip()

        if op == "0":
            print(cor("\n  Encerrando.\n", "cinza"))
            break

        elif op == "1":
            termo = input("  Buscar por (número do cartão, nome, ID): ").strip()
            if not termo:
                continue

            encontrados = buscar_registros(registros, termo)

            if not encontrados:
                print(cor(f"\n  Nenhum registro encontrado para '{termo}'.", "cinza"))
                continue

            print(cor(f"\n  {len(encontrados)} registro(s) encontrado(s):", "azul"))
            for i, est in enumerate(encontrados, 1):
                print(f"\n  [{i}]", end="")
                exibir_registro(est, mostrar_historico=True, registros_todos=registros)

            if len(encontrados) == 1:
                escolhido = encontrados[0]
            else:
                try:
                    n = int(input("  Qual corrigir? (número): ").strip())
                    escolhido = encontrados[n - 1]
                except (ValueError, IndexError):
                    print(cor("  Seleção inválida.", "vermelho"))
                    continue

            id_correcao = fazer_correcao(caminho_log, registros, escolhido, operador)
            if id_correcao:
                registros = carregar_log(caminho_log)  # recarrega com a correção

        elif op == "2":
            relatorio_auditoria(registros)

        elif op == "3":
            detectar_duplicatas(registros)

        else:
            print(cor("  Opção inválida.", "vermelho"))


# ── PONTO DE ENTRADA ──────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="GMA — ferramenta de correção de registros de check-in"
    )
    parser.add_argument("--log", default=LOG_PADRAO,
                        help=f"Caminho do arquivo de log (padrão: {LOG_PADRAO})")
    parser.add_argument("--buscar", metavar="TERMO",
                        help="Buscar registro diretamente e entrar no fluxo de correção")
    parser.add_argument("--auditoria", action="store_true",
                        help="Exibir relatório de auditoria de correções")
    parser.add_argument("--duplicatas", action="store_true",
                        help="Listar pares suspeitos de duplicata")

    args = parser.parse_args()

    if not os.path.exists(args.log):
        print(cor(f"\n  Arquivo de log não encontrado: {args.log}", "vermelho"))
        print(f"  Verifique o caminho ou use --log para especificar outro arquivo.\n")
        sys.exit(1)

    registros = carregar_log(args.log)

    if args.auditoria:
        relatorio_auditoria(registros)
    elif args.duplicatas:
        detectar_duplicatas(registros)
    elif args.buscar:
        encontrados = buscar_registros(registros, args.buscar)
        if not encontrados:
            print(cor(f"\n  Nenhum registro para '{args.buscar}'.\n", "cinza"))
            sys.exit(0)
        for est in encontrados:
            exibir_registro(est, mostrar_historico=True, registros_todos=registros)
        if encontrados:
            operador = input("  Seu nome para fazer correção (Enter para só visualizar): ").strip()
            if operador:
                fazer_correcao(args.log, registros, encontrados[0], operador)
    else:
        modo_interativo(args.log)


if __name__ == "__main__":
    main()
