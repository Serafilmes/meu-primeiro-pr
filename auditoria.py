#!/usr/bin/env python3
"""
auditoria.py
Camada 4 do GMA — Auditoria estrutural e liberação do cartão.

Responsabilidade:
  1. Monitorar o banco para cartões com status 'transferencia_ok'.
  2. Fazer uma auditoria INDEPENDENTE da Camada 2:
       - Camada 2 verificou CADA ARQUIVO individualmente (MD5 bit a bit).
       - Camada 4 verifica a ESTRUTURA COMPLETA depois (contagem + tamanho total)
         E depois chama o Parashoot CLI para verificar arquivo a arquivo também.
         São ângulos complementares: o GMA confirma a estrutura antes de pedir
         ao Parashoot para embaralhar.
  3. Chamar `parashoot check` via CLI para verificação definitiva (arquivo a arquivo).
  4. Chamar `parashoot erase` via CLI para embaralhar o cartão (fake-format).
  5. Registrar tudo na tabela 'eventos' (append-only).

Mapa de status do ciclo de vida nesta camada:
  transferencia_ok    → entrada: cartão pronto para auditoria (gravado pela Camada 2)
  verificado_parashoot → Parashoot check OK (missingFiles == 0)
  verificacao_falhou  → Parashoot check encontrou missingFiles > 0 ou erro inesperado
  erase_falhou        → Parashoot erase falhou
  concluido           → ciclo completo: check + erase OK, cartão liberado para reutilização

Princípio de segurança central:
  - Este script NUNCA apaga, move ou renomeia arquivos de mídia.
  - Só lê o sistema de arquivos (contagem + tamanho) e escreve no banco.
  - O embaralhamento físico do cartão é delegado EXCLUSIVAMENTE ao CLI do Parashoot
    via `parashoot erase`. O GMA nunca chama `fake_format` diretamente.
  - Falha segura: se o JSON do Parashoot for inesperado, ambíguo ou inválido,
    o cartão NÃO é embaralhado e NÃO é marcado concluido.

Uso:
    python3 /Users/serafa/GMA/auditoria.py
"""

import json
import logging
import os
import subprocess
import time
from datetime import datetime

import banco_dados
import ler_cartao  # RÉGUA ÚNICA do que é "material" (compartilhada com a C2)

# ── CONSTANTES ─────────────────────────────────────────────────────────────────

RAIZ_GMA = "/Users/serafa/GMA"

# Intervalo de polling: verifica o banco a cada N segundos
INTERVALO_POLLING = 10

# Tolerância de tamanho aceitável entre destino e registrado.
# Diferença de até 0,5% é considerada ok (pode variar por arredondamento do FS).
TOLERANCIA_TAMANHO = 0.005

# O que NÃO conta na auditoria (lixo do SO/cartão, arquivos do próprio GMA e
# download incompleto) é decidido pela RÉGUA ÚNICA em ler_cartao.eh_nao_midia /
# eh_pasta_ignorada — a MESMA que o copiador (C2) usa ao contar o que copiou.
# Antes esta lista vivia só aqui e não conhecia o `.DS_Store` que o Finder cria
# no destino → contava 108 vs 106 e travava o ciclo (sessão 39).

# Caminho do CLI do Parashoot.
# Se o binário não existir (máquina de dev sem Parashoot instalado), a auditoria
# vai degradar com aviso — NÃO vai crashar o loop principal.
PARASHOOT_CLI = "/Applications/ParaShoot.app/Contents/MacOS/cli/parashoot"

# Timeout para o `parashoot check` em segundos.
# O check é rápido (a cópia já terminou) — 120 s é generoso.
TIMEOUT_PARASHOOT_CHECK = 120

# Timeout para o `parashoot erase` em segundos.
# O erase executa o fake-format (inverte 2 MB do MBR) — deve ser rápido também,
# mas damos 300 s para acomodar cartões lentos ou HDs externos.
TIMEOUT_PARASHOOT_ERASE = 300

# ── LOG ────────────────────────────────────────────────────────────────────────

os.makedirs(os.path.join(RAIZ_GMA, "logs"), exist_ok=True)

logging.basicConfig(
    filename=os.path.join(RAIZ_GMA, "logs", "auditoria.log"),
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
log = logging.getLogger(__name__)


# ── ANÁLISE DO DESTINO (pré-check GMA) ────────────────────────────────────────

def _auditar_destino(destino_pasta):
    """
    Percorre a pasta de destino, contando arquivos e somando tamanho total.

    Conta SÓ o material: a RÉGUA ÚNICA (ler_cartao) descarta o lixo do SO/cartão
    (.DS_Store, ocultos), os arquivos do próprio GMA (.sppo, relatório, manifesto,
    _GMA_frames/) e o download incompleto (.part…) — exatamente o mesmo conjunto
    que o copiador (C2) descartou ao contar o que copiou. Assim a contagem do
    destino bate com a `total_arquivos_transferidos` gravada pela C2.

    Retorna (total_arquivos: int, total_bytes: int).
    """
    total_arquivos = 0
    total_bytes    = 0

    if not os.path.isdir(destino_pasta):
        return 0, 0

    for raiz, dirs, arquivos in os.walk(destino_pasta):
        # Poda as pastas que a régua manda ignorar (ocultas, __MACOSX, _GMA_frames).
        dirs[:] = [d for d in dirs if not ler_cartao.eh_pasta_ignorada(d)]

        for nome in arquivos:
            if ler_cartao.eh_nao_midia(nome):
                continue

            caminho = os.path.join(raiz, nome)
            try:
                total_bytes += os.path.getsize(caminho)
                total_arquivos += 1
            except OSError:
                pass

    return total_arquivos, total_bytes


# ── INTEGRAÇÃO COM O CLI DO PARASHOOT ─────────────────────────────────────────

def _parashoot_disponivel():
    """Retorna True se o binário do Parashoot CLI existir e for executável."""
    return os.path.isfile(PARASHOOT_CLI) and os.access(PARASHOOT_CLI, os.X_OK)


def _rodar_parashoot(subcomando, mount, destino_pasta, timeout):
    """
    Executa um subcomando do CLI do Parashoot e retorna um dict normalizado.

    Parâmetros:
      subcomando    — "check" ou "erase"
      mount         — caminho do cartão montado (ex: "/Volumes/EOS_DIGITAL")
      destino_pasta — caminho da pasta de destino (ex: "/Volumes/.../ERBS_015")
      timeout       — timeout em segundos para o processo

    Retorna um dicionário normalizado:
      {
        "ok":      bool,   # True se o Parashoot reportou sucesso sem arquivos faltando
        "missing": int,    # número de arquivos faltando (0 = perfeito)
        "total":   int,    # total de arquivos verificados
        "found":   int,    # arquivos encontrados no destino
        "raw":     dict,   # JSON bruto retornado pelo CLI (para log/auditoria)
        "erro":    str,    # mensagem de erro legível (vazia se ok=True)
      }

    FORMATOS REAIS DO CLI (validados com cartão real — Sony "Joe", 2026-06-09):
      O Parashoot emite JSON LINES (NDJSON): um objeto JSON por linha, em streaming.
      O `erase` emite uma linha de início e uma de fim:
        {"status":"erase_start", "message":"Starting card erasure"}
        {"status":"erase_complete", "message":"Card has been successfully erased"}
      O `check` de sucesso emite uma linha:
        {"status":"check_complete", "message":"Card is successfully backed up to all destinations"}
      O erro sai no STDERR como uma linha:
        {"status":"error","error":"unknown_error","message":"Exception: Could not stat ..."}

      Por isso o parser:
      - Lê TODAS as linhas (stdout + stderr), parseando cada uma como JSON.
      - Usa o ÚLTIMO objeto com status TERMINAL (sucesso ou erro) para decidir.
      - Status terminais de SUCESSO: 'check_complete', 'erase_complete'.
      - Status terminal de ERRO: 'error'.
      - Status intermediários ('erase_start', progresso) são ignorados na decisão.
      - O JSON de sucesso NÃO traz contagens (missing/found/total) — quando vierem
        (ex.: check com faltas), são capturados de forma defensiva (camel/snake_case).
      - Falha segura: sem status terminal de sucesso reconhecido → NÃO embaralha.
    """
    # Status terminais que o CLI usa para sinalizar conclusão por subcomando.
    STATUS_SUCESSO = {"check_complete", "erase_complete"}
    STATUS_ERRO    = {"error"}
    if not _parashoot_disponivel():
        return {
            "ok":      False,
            "missing": -1,
            "total":   0,
            "found":   0,
            "raw":     {},
            "erro":    f"CLI do Parashoot não encontrado em {PARASHOOT_CLI}",
        }

    # Monta o comando com flags explícitas
    # --destinations passa o destino_pasta diretamente (não depende das settings da GUI)
    cmd = [
        PARASHOOT_CLI,
        subcomando,
        "--card", mount,
        "--destinations", destino_pasta,
        "--machine-readable",   # saída em JSON
    ]

    log.info(f"Parashoot {subcomando}: {' '.join(cmd)}")
    print(f"[AUDITORIA]     Parashoot {subcomando}: {mount} → {destino_pasta}", flush=True)

    try:
        resultado = subprocess.run(
            cmd,
            timeout=timeout,
            capture_output=True,
            text=True,
        )
    except subprocess.TimeoutExpired:
        mensagem = f"Parashoot {subcomando} excedeu o timeout de {timeout}s"
        log.error(mensagem)
        return {
            "ok":      False,
            "missing": -1,
            "total":   0,
            "found":   0,
            "raw":     {},
            "erro":    mensagem,
        }
    except Exception as e:
        mensagem = f"Erro ao executar Parashoot {subcomando}: {e}"
        log.error(mensagem)
        return {
            "ok":      False,
            "missing": -1,
            "total":   0,
            "found":   0,
            "raw":     {},
            "erro":    mensagem,
        }

    # Captura stdout e stderr para diagnóstico
    stdout_bruto = resultado.stdout.strip()
    stderr_bruto = resultado.stderr.strip()

    if stderr_bruto:
        log.warning(f"Parashoot {subcomando} stderr: {stderr_bruto}")

    log.info(f"Parashoot {subcomando} exit_code={resultado.returncode} stdout={stdout_bruto[:300]}")

    # ── Parse JSON Lines (NDJSON) ─────────────────────────────────────────────
    # O CLI emite um objeto JSON por linha (streaming de progresso). Lemos todas
    # as linhas de stdout E stderr (erro sai no stderr), parseando cada uma.
    objetos = []
    for texto in (stdout_bruto, stderr_bruto):
        if not texto:
            continue
        for linha in texto.splitlines():
            linha = linha.strip()
            if not linha:
                continue
            try:
                obj = json.loads(linha)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                objetos.append(obj)

    # Nenhuma linha JSON válida → falha segura
    if not objetos:
        mensagem = (
            f"Parashoot {subcomando} não retornou nenhuma linha JSON válida "
            f"(exit_code={resultado.returncode})"
        )
        log.error(f"{mensagem} | stdout={stdout_bruto[:150]} | stderr={stderr_bruto[:150]}")
        return {
            "ok":      False,
            "missing": -1,
            "total":   0,
            "found":   0,
            "raw":     {"stdout_bruto": stdout_bruto, "stderr_bruto": stderr_bruto},
            "erro":    mensagem,
        }

    # Extrai contagens de forma defensiva de QUALQUER objeto que as traga
    # (o JSON de sucesso não traz; o de faltas provavelmente sim).
    def _primeiro_int(chave_camel, chave_snake, chave_curta):
        for obj in objetos:
            for k in (chave_camel, chave_snake, chave_curta):
                if obj.get(k) is not None:
                    try:
                        return int(obj[k])
                    except (ValueError, TypeError):
                        pass
        return None

    missing_raw = _primeiro_int("missingFiles", "missing_files", "missing")
    total_raw   = _primeiro_int("totalFiles",   "total_files",   "total")
    found_raw   = _primeiro_int("foundFiles",   "found_files",   "found")

    missing = missing_raw if missing_raw is not None else -1
    total   = total_raw   if total_raw   is not None else 0
    found   = found_raw   if found_raw   is not None else 0

    # Decide pelo ÚLTIMO objeto que traz um status TERMINAL (sucesso ou erro).
    # Status intermediários (erase_start, progresso) são ignorados na decisão.
    status_terminal = None
    obj_terminal    = {}
    for obj in objetos:
        s = obj.get("status", "")
        if s in STATUS_SUCESSO or s in STATUS_ERRO:
            status_terminal = s
            obj_terminal     = obj

    # Erro explícito reportado pelo CLI
    if status_terminal in STATUS_ERRO:
        mensagem = obj_terminal.get("message") or obj_terminal.get("error") or "Erro desconhecido"
        log.error(f"Parashoot {subcomando} reportou erro: {mensagem}")
        return {
            "ok":      False,
            "missing": missing,
            "total":   total,
            "found":   found,
            "raw":     objetos,
            "erro":    f"Parashoot reportou erro: {mensagem}",
        }

    # Sucesso terminal reconhecido + exit code 0 + sem arquivos faltando.
    # (missing == -1 significa "não informado", aceito porque o sucesso não traz contagem.)
    sucesso = (
        status_terminal in STATUS_SUCESSO
        and resultado.returncode == 0
        and missing <= 0
    )

    if not sucesso:
        # Nenhum status terminal de sucesso reconhecido → falha segura, NÃO embaralha.
        mensagem = (
            f"Parashoot {subcomando} sem status terminal de sucesso reconhecido "
            f"(status={status_terminal!r}, exit_code={resultado.returncode}, missing={missing})"
        )
        log.error(mensagem)
        return {
            "ok":      False,
            "missing": missing,
            "total":   total,
            "found":   found,
            "raw":     objetos,
            "erro":    mensagem,
        }

    return {
        "ok":      True,
        "missing": missing,
        "total":   total,
        "found":   found,
        "raw":     objetos,
        "erro":    "",
    }


# ── NOTIFICAÇÕES MACOS ─────────────────────────────────────────────────────────

def _notificar_operador(titulo, mensagem, som="Glass"):
    """
    Envia uma notificação macOS ao operador via osascript.
    Usado apenas em situações que exigem atenção humana (ocasiões vitais):
      - Parashoot check com arquivos faltando
      - Parashoot check com erro inesperado
      - Parashoot erase falhou

    Em caso de sucesso (ciclo normal), NÃO envia notificação —
    o operador é acionado apenas quando há problema.
    """
    try:
        subprocess.run(
            [
                "osascript", "-e",
                f'display notification "{mensagem}" '
                f'with title "{titulo}" sound name "{som}"',
            ],
            timeout=5,
            capture_output=True,
        )
    except Exception as e:
        log.warning(f"Não foi possível enviar notificação macOS: {e}")


# ── REPROVAR (auditoria estrutural GMA) ───────────────────────────────────────

def _reprovar(cartao_id, numero_cartao, motivo, conn, dados=None):
    """
    Registra uma reprovação da auditoria estrutural GMA no banco e no terminal.
    NÃO altera o status do cartão (permanece em 'transferencia_ok').
    NÃO aciona o Parashoot.
    """
    print(f"[AUDITORIA]     {numero_cartao} — FALHA ESTRUTURAL: {motivo}", flush=True)
    log.warning(f"Cartão {cartao_id} reprovado (auditoria GMA): {motivo}")

    dados_completos = {"motivo": motivo}
    if dados:
        dados_completos.update(dados)

    banco_dados.registrar_evento(
        conn,
        tipo="auditoria_falhou",
        descricao=f"Auditoria falhou — {numero_cartao}: {motivo}",
        cartao_id=cartao_id,
        dados=dados_completos,
    )


# ── APROVAÇÃO DE MATERIAL RECEBIDO (sem Parashoot) ────────────────────────────

def _aprovar_recebido(cartao_id, numero_cartao, volume,
                      total_destino, tamanho_destino,
                      total_esperado, tamanho_esperado,
                      conn):
    """
    Marca um material recebido (pasta satélite) como 'concluido' sem acionar
    o Parashoot.

    Chamada SOMENTE quando origem_material == 'recebido'. A auditoria estrutural
    (contagem + tamanho) já foi feita em auditar_cartao() antes desta chamada —
    esta função só registra a aprovação e marca o status.

    Não há cartão físico a embaralhar/ejetar: chamar o Parashoot para material
    recebido seria um erro grave (o Parashoot operaria sobre o disco errado ou
    falharia sem um volume de cartão presente).

    Retorna True (material aprovado e marcado concluido).
    """
    print(
        f"[AUDITORIA]     {numero_cartao} — material RECEBIDO (pasta satélite): "
        f"Parashoot ignorado — sem cartão físico a ejetar.",
        flush=True,
    )
    log.info(
        f"Cartão {cartao_id} ({numero_cartao}) — recebido/satélite: "
        f"pré-check OK, marcando concluido sem Parashoot."
    )

    banco_dados.atualizar_cartao(conn, cartao_id, {"status": "concluido"})
    # O Post ligado a este cartão acompanha: sai de 'matched' e vira 'concluido'
    # (senão ficaria preso "em operação" na Nova Ficha mesmo já entregue).
    banco_dados.concluir_formulario_do_cartao(conn, cartao_id)

    banco_dados.registrar_evento(
        conn,
        tipo="auditoria_recebido_concluida",
        descricao=(
            f"Auditoria de material recebido concluída — {numero_cartao} | "
            f"Parashoot ignorado (sem cartão físico) | "
            f"{total_destino} arq / {tamanho_destino:,} bytes"
        ),
        cartao_id=cartao_id,
        dados={
            "motivo_sem_parashoot":    "origem_material=recebido — pasta satélite, sem cartão físico",
            "total_arquivos_destino":  total_destino,
            "total_arquivos_esperado": total_esperado,
            "tamanho_destino_bytes":   tamanho_destino,
            "tamanho_esperado_bytes":  tamanho_esperado,
            "volume":                  volume,
        },
    )

    print(
        f"[AUDITORIA]     {numero_cartao} — CONCLUIDO (recebido): "
        f"auditoria estrutural OK, Parashoot não acionado.",
        flush=True,
    )
    log.info(f"Cartão {cartao_id} ({numero_cartao}) — CONCLUIDO (recebido).")

    return True


# ── AUDITORIA PRINCIPAL DE UM CARTÃO ──────────────────────────────────────────

def auditar_cartao(cartao, conn):
    """
    Executa o ciclo completo de auditoria e liberação de um cartão.

    Fluxo:
      1. Verifica pasta de destino (existe?)
      2. Pré-check GMA: contagem de arquivos + tamanho total (±0,5%)
      3. Descobre o mountpoint do cartão (/Volumes/<volume>)
      4. Parashoot check (arquivo a arquivo via CLI)
      5. Parashoot erase (embaralhamento via CLI)

    Retorna True se o ciclo completo foi concluído com sucesso, False caso contrário.
    """
    cartao_id        = cartao["id"]
    numero_cartao    = cartao["numero_cartao"] or f"ID-{cartao_id}"
    destino_pasta    = cartao["destino_pasta"]
    total_esperado   = cartao["total_arquivos_transferidos"] or 0
    tamanho_esperado = cartao["tamanho_transferido_bytes"] or 0
    volume           = cartao["volume"] or "?"

    # Lê a origem: "cartao" (fluxo normal) ou "recebido" (pasta satélite).
    # Cartões antigos (coluna ausente) são tratados como "cartao" por segurança.
    try:
        origem_material = cartao["origem_material"] or "cartao"
    except (IndexError, KeyError):
        origem_material = "cartao"
    e_material_recebido = (origem_material == "recebido")

    print(f"[AUDITORIA]     Auditando {numero_cartao}...", flush=True)
    log.info(
        f"Auditoria iniciada | cartão {cartao_id} ({numero_cartao}) | "
        f"destino: {destino_pasta} | volume: {volume}"
    )

    # ── ETAPA 1: Pasta de destino existe? ─────────────────────────────────────
    if not destino_pasta or not os.path.isdir(destino_pasta):
        motivo = f"Pasta de destino não encontrada: {destino_pasta}"
        _reprovar(cartao_id, numero_cartao, motivo, conn)
        return False

    # ── ETAPA 2: Pré-check GMA (contagem + tamanho) ───────────────────────────
    total_destino, tamanho_destino = _auditar_destino(destino_pasta)

    print(
        f"[AUDITORIA]     {numero_cartao}: "
        f"destino={total_destino} arq / {tamanho_destino:,} bytes | "
        f"esperado={total_esperado} arq / {tamanho_esperado:,} bytes",
        flush=True,
    )

    # Contagem bate?
    if total_esperado > 0 and total_destino != total_esperado:
        motivo = (
            f"Contagem divergente: {total_destino} arquivos no destino "
            f"vs {total_esperado} esperados"
        )
        _reprovar(
            cartao_id, numero_cartao, motivo, conn,
            dados={"total_destino": total_destino, "total_esperado": total_esperado},
        )
        return False

    # Tamanho bate (com tolerância)?
    if tamanho_esperado > 0:
        diferenca = abs(tamanho_destino - tamanho_esperado) / tamanho_esperado
        if diferenca > TOLERANCIA_TAMANHO:
            motivo = (
                f"Tamanho divergente: {tamanho_destino:,} bytes no destino "
                f"vs {tamanho_esperado:,} bytes esperados "
                f"({diferenca:.2%} de diferença)"
            )
            _reprovar(
                cartao_id, numero_cartao, motivo, conn,
                dados={
                    "tamanho_destino":  tamanho_destino,
                    "tamanho_esperado": tamanho_esperado,
                    "diferenca_pct":    round(diferenca * 100, 3),
                },
            )
            return False

    print(
        f"[AUDITORIA]     {numero_cartao} — pré-check GMA OK "
        f"(contagem + tamanho dentro da tolerância)",
        flush=True,
    )

    # ── RAMIFICAÇÃO: material recebido (pasta satélite) ────────────────────────
    # Quando a origem for "recebido", NÃO há cartão físico a embaralhar/ejetar.
    # Chamamos o Parashoot neste caso seria um erro grave. O ciclo é:
    #   1. Pasta de destino existe?       (etapa 1 — já feito)
    #   2. Contagem + tamanho OK?         (etapa 2 — já feito)
    #   3. → Marca concluido + registra evento explicando o desvio. FIM.
    #
    # A pasta de origem em RECEBIDOS já foi marcada "_COPIADO" pela C2.
    # A C4 NÃO toca na pasta de origem — só lê o destino (auditoria independente).
    if e_material_recebido:
        return _aprovar_recebido(
            cartao_id, numero_cartao, volume,
            total_destino, tamanho_destino,
            total_esperado, tamanho_esperado,
            conn,
        )

    # ── ETAPA 3: Descobrir o mountpoint do cartão ──────────────────────────────
    # O campo `volume` do banco contém o nome do volume (ex: "EOS_DIGITAL").
    # O mountpoint esperado é /Volumes/<volume>.
    # Se o cartão não estiver mais montado, NÃO é possível embaralhar —
    # registra evento e pula (não reprova: a cópia já foi verificada).
    if volume and volume != "?":
        mount = os.path.join("/Volumes", volume)
    else:
        mount = None

    if not mount or not os.path.isdir(mount):
        motivo = (
            f"Cartão não está montado em {mount} — "
            f"impossível acionar o Parashoot sem o cartão presente. "
            f"Verifique se o volume '{volume}' ainda está conectado."
        )
        print(f"[AUDITORIA]     {numero_cartao} — AVISO: {motivo}", flush=True)
        log.warning(f"Cartão {cartao_id}: mountpoint não encontrado ({mount})")

        banco_dados.registrar_evento(
            conn,
            tipo="cartao_nao_montado",
            descricao=f"Mountpoint não encontrado — {numero_cartao}: {motivo}",
            cartao_id=cartao_id,
            dados={
                "volume":    volume,
                "mountpoint_esperado": mount,
                "motivo":    "cartão pode ter sido ejetado antes do erase",
            },
        )
        # Não reprova nem aprova — aguarda o operador resolver
        return False

    # ── ETAPA 4: Parashoot check ───────────────────────────────────────────────
    # TODO: quando o extrator_frames.py for configurado para ler os frames
    # diretamente do cartão (caso o destino seja servidor de rede), adicionar
    # aqui uma espera: aguardar os frames terminarem ANTES de chamar o erase.
    # Ordem segura: cópia → verificação → frames do cartão → check → erase.

    if not _parashoot_disponivel():
        # Parashoot não instalado (máquina de dev) — degrada com aviso,
        # NÃO aprova nem reprovação — só registra e pula o ciclo Parashoot.
        aviso = f"CLI do Parashoot não disponível em {PARASHOOT_CLI} — embaralhamento ignorado"
        print(f"[AUDITORIA]     {numero_cartao} — AVISO: {aviso}", flush=True)
        log.warning(f"Cartão {cartao_id}: {aviso}")

        banco_dados.registrar_evento(
            conn,
            tipo="parashoot_indisponivel",
            descricao=f"Parashoot CLI não encontrado — {numero_cartao}",
            cartao_id=cartao_id,
            dados={"cli_esperado": PARASHOOT_CLI, "motivo": aviso},
        )
        return False

    resultado_check = _rodar_parashoot(
        "check", mount, destino_pasta, TIMEOUT_PARASHOOT_CHECK
    )

    if not resultado_check["ok"]:
        # Check falhou — material pode estar faltando no destino.
        # Esta é uma OCASIÃO VITAL: notifica o operador.
        motivo_check = resultado_check["erro"] or "Parashoot check falhou"
        missing_info = resultado_check["missing"]

        if missing_info > 0:
            descricao_falha = (
                f"Parashoot check: {missing_info} arquivo(s) faltando no destino — "
                f"NÃO embaralhado. Verifique o destino antes de liberar o cartão."
            )
        else:
            descricao_falha = (
                f"Parashoot check retornou erro inesperado — "
                f"NÃO embaralhado. Motivo: {motivo_check}"
            )

        print(f"[AUDITORIA]     {numero_cartao} — FALHA CHECK: {descricao_falha}", flush=True)
        log.error(f"Cartão {cartao_id} — check falhou: {descricao_falha}")

        # Atualiza o status para 'verificacao_falhou' (cartão bloqueado para erase)
        banco_dados.atualizar_cartao(conn, cartao_id, {"status": "verificacao_falhou"})

        banco_dados.registrar_evento(
            conn,
            tipo="parashoot_check_falhou",
            descricao=f"Parashoot check falhou — {numero_cartao}: {descricao_falha}",
            cartao_id=cartao_id,
            dados={
                "motivo":        motivo_check,
                "missing_files": missing_info,
                "total_files":   resultado_check["total"],
                "found_files":   resultado_check["found"],
                "raw":           resultado_check["raw"],
            },
        )

        # Notifica o operador — esta é uma ocasião vital que exige atenção humana
        _notificar_operador(
            titulo="GMA — Auditoria Camada 4",
            mensagem=f"ATENÇÃO: Cartão {numero_cartao} — {descricao_falha}",
            som="Basso",
        )

        return False

    # Check OK — registra o status intermediário.
    # O JSON de sucesso do check não traz contagem (total=0); só mostra os números
    # quando o CLI de fato os reportar (ex.: caso de faltas).
    if resultado_check["total"] > 0:
        detalhe_check = f"({resultado_check['found']}/{resultado_check['total']} arquivos verificados)"
    else:
        detalhe_check = "(backup confirmado — Parashoot validou todos os arquivos)"
    print(
        f"[AUDITORIA]     {numero_cartao} — Parashoot check OK {detalhe_check}",
        flush=True,
    )
    log.info(f"Cartão {cartao_id}: Parashoot check OK")

    banco_dados.atualizar_cartao(conn, cartao_id, {"status": "verificado_parashoot"})

    banco_dados.registrar_evento(
        conn,
        tipo="parashoot_check_ok",
        descricao=(
            f"Parashoot check OK — {numero_cartao} | "
            f"{resultado_check['found']}/{resultado_check['total']} arquivos"
        ),
        cartao_id=cartao_id,
        dados={
            "total_files":   resultado_check["total"],
            "found_files":   resultado_check["found"],
            "missing_files": resultado_check["missing"],
            "raw":           resultado_check["raw"],
        },
    )

    # ── ETAPA 5: Parashoot erase ───────────────────────────────────────────────
    # Só chega aqui se o check foi 100% OK.
    # O erase executa o fake-format (inverte primeiros 2 MB do MBR do cartão).
    # Esta ação é delegada ao Parashoot — o GMA nunca chama fake_format diretamente.
    print(
        f"[AUDITORIA]     {numero_cartao} — iniciando Parashoot erase...",
        flush=True,
    )

    resultado_erase = _rodar_parashoot(
        "erase", mount, destino_pasta, TIMEOUT_PARASHOOT_ERASE
    )

    if not resultado_erase["ok"]:
        motivo_erase = resultado_erase["erro"] or "Parashoot erase falhou"

        print(f"[AUDITORIA]     {numero_cartao} — FALHA ERASE: {motivo_erase}", flush=True)
        log.error(f"Cartão {cartao_id} — erase falhou: {motivo_erase}")

        # Atualiza o status para 'erase_falhou'
        banco_dados.atualizar_cartao(conn, cartao_id, {"status": "erase_falhou"})

        banco_dados.registrar_evento(
            conn,
            tipo="parashoot_erase_falhou",
            descricao=f"Parashoot erase falhou — {numero_cartao}: {motivo_erase}",
            cartao_id=cartao_id,
            dados={
                "motivo": motivo_erase,
                "raw":    resultado_erase["raw"],
            },
        )

        # Notifica o operador — occasião vital
        _notificar_operador(
            titulo="GMA — Auditoria Camada 4",
            mensagem=(
                f"ATENÇÃO: Cartão {numero_cartao} verificado mas erase FALHOU. "
                f"Verifique e embaralhe manualmente no Parashoot."
            ),
            som="Basso",
        )

        return False

    # ── Ciclo completo concluído ───────────────────────────────────────────────
    print(
        f"[AUDITORIA]     {numero_cartao} — CONCLUIDO: check + erase OK. "
        f"Cartão liberado para reutilização.",
        flush=True,
    )
    log.info(f"Cartão {cartao_id} ({numero_cartao}) — CONCLUIDO.")

    banco_dados.atualizar_cartao(conn, cartao_id, {"status": "concluido"})
    # O Post ligado a este cartão acompanha: sai de 'matched' e vira 'concluido'
    # (senão ficaria preso "em operação" na Nova Ficha mesmo já entregue).
    banco_dados.concluir_formulario_do_cartao(conn, cartao_id)

    banco_dados.registrar_evento(
        conn,
        tipo="auditoria_concluida",
        descricao=(
            f"Auditoria completa — {numero_cartao} | "
            f"check OK + erase OK | "
            f"{total_destino} arq / {tamanho_destino:,} bytes"
        ),
        cartao_id=cartao_id,
        dados={
            "total_arquivos_destino":  total_destino,
            "total_arquivos_esperado": total_esperado,
            "tamanho_destino_bytes":   tamanho_destino,
            "tamanho_esperado_bytes":  tamanho_esperado,
            "parashoot_total":         resultado_check["total"],
            "parashoot_found":         resultado_check["found"],
        },
    )

    banco_dados.registrar_evento(
        conn,
        tipo="cartao_embaralhado",
        descricao=f"Cartão embaralhado via Parashoot erase — {numero_cartao} | Volume: {volume}",
        cartao_id=cartao_id,
        dados={
            "numero_cartao": numero_cartao,
            "volume":        volume,
            "mountpoint":    mount,
        },
    )

    return True


# ── LOOP CONTÍNUO ──────────────────────────────────────────────────────────────

def loop_auditoria():
    """
    Loop de auditoria contínua (roda como processo independente).
    A cada INTERVALO_POLLING segundos, verifica se há cartões com
    'transferencia_ok' prontos para auditar.
    """
    print("[AUDITORIA]     Auditoria Camada 4 iniciada.", flush=True)
    log.info("Loop de auditoria iniciado.")

    # Avisa na inicialização se o Parashoot não estiver instalado
    if not _parashoot_disponivel():
        aviso = (
            f"[AUDITORIA]     AVISO: CLI do Parashoot não encontrado em {PARASHOOT_CLI}. "
            f"O embaralhamento automático estará desativado até que o Parashoot seja instalado."
        )
        print(aviso, flush=True)
        log.warning(aviso)

    while True:
        try:
            conn = banco_dados.obter_conexao()

            cursor = conn.execute("""
                SELECT id, numero_cartao, destino_pasta, volume,
                       total_arquivos_transferidos, tamanho_transferido_bytes,
                       origem_material
                FROM cartoes
                WHERE status = 'transferencia_ok'
                ORDER BY id
            """)
            pendentes = cursor.fetchall()

            for cartao in pendentes:
                try:
                    auditar_cartao(cartao, conn)
                except Exception as e:
                    log.error(f"Erro ao auditar cartão {cartao['id']}: {e}")

            conn.close()

        except Exception as e:
            log.error(f"Erro no loop de auditoria: {e}")

        time.sleep(INTERVALO_POLLING)


# ── PONTO DE ENTRADA ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    loop_auditoria()
