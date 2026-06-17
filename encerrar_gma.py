#!/usr/bin/env python3
"""
encerrar_gma.py
Camada 1 do GMA — Encerramento de emergência do sistema.

Usado quando o operador fechou o terminal acidentalmente e os processos
do GMA ainda estão rodando em segundo plano (sem Ctrl+C).

Este script:
  1. Localiza os processos porteiro.py, leitor_midia.py e flask_gma.py
     usando o comando `pgrep -f` do macOS (sem dependências externas).
  2. Encerra cada processo encontrado.
  3. Remove o arquivo sentinela .gma_ativo.
  4. Confirma o que foi feito.

Uso:
    python3 /Users/serafa/GMA/encerrar_gma.py

Seguranca:
  - Nunca encerra processos pelo nome generico "python" (evita matar
    outros scripts por engano). Busca pelo nome especifico do script.
  - Nunca apaga arquivos de midia — apenas o sentinela GMA.
"""

import os
import subprocess
import sys
from datetime import datetime

# ── CONFIGURAÇÃO ───────────────────────────────────────────────────────────────

# Raiz do projeto GMA
RAIZ_GMA = "/Users/serafa/GMA"

# Arquivo sentinela do sistema GMA
SENTINELA = os.path.join(RAIZ_GMA, ".gma_ativo")

# Lista dos scripts GMA que devem ser encerrados.
# Cada item é um dicionário com:
#   "script"  — trecho do caminho usado no pgrep (deve ser unico o suficiente)
#   "nome"    — nome legivel para exibir no terminal
SCRIPTS_GMA = [
    {"script": "porteiro.py",          "nome": "Porteiro"},
    {"script": "leitor_midia.py",      "nome": "Leitor de Midia"},
    {"script": "flask_gma.py",         "nome": "Flask"},
    {"script": "transferencia.py",     "nome": "Transferencia"},
    {"script": "auditoria.py",         "nome": "Auditoria"},
    {"script": "exportador_sheets.py", "nome": "Exportador Sheets"},
]


# ── FUNÇÕES AUXILIARES ────────────────────────────────────────────────────────

def agora():
    """Retorna o timestamp atual no formato ISO-8601."""
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def log(mensagem):
    """Imprime uma linha com prefixo e timestamp."""
    print(f"[GMA]          {agora()} | {mensagem}", flush=True)


def buscar_pids(nome_script):
    """
    Usa `pgrep -f nome_script` para encontrar os PIDs de processos
    que contêm o nome do script na linha de comando com que foram iniciados.

    O `-f` faz o pgrep buscar no comando completo (incluindo argumentos),
    não apenas no nome do executavel. Assim encontra "python3 porteiro.py".

    Retorna uma lista de inteiros (PIDs). Lista vazia se nenhum encontrado.
    """
    try:
        resultado = subprocess.run(
            ["pgrep", "-f", nome_script],
            capture_output=True,     # captura stdout e stderr
            text=True,               # decodifica para string
        )

        if resultado.returncode != 0:
            # pgrep retorna codigo 1 quando nao encontra nada — nao é erro
            return []

        # Cada linha do stdout é um PID
        pids = []
        for linha in resultado.stdout.strip().splitlines():
            linha = linha.strip()
            if linha.isdigit():
                pids.append(int(linha))

        return pids

    except FileNotFoundError:
        # pgrep não está disponível no sistema (improvavel no macOS)
        log("ERRO: comando 'pgrep' nao encontrado. Instale as ferramentas de sistema.")
        return []

    except Exception as erro:
        log(f"ERRO ao buscar PIDs de '{nome_script}': {erro}")
        return []


def encerrar_pid(pid, nome_legivel):
    """
    Encerra um processo pelo PID.

    Estrategia:
      1. Envia SIGTERM via `kill` (pedido gentil).
      2. Aguarda ate 5 segundos.
      3. Se ainda rodar, envia SIGKILL (forca).

    Parâmetros:
      pid           — inteiro, o PID do processo
      nome_legivel  — nome para exibir no log
    """
    import signal
    import time

    try:
        # Verifica se o processo ainda existe antes de enviar o sinal
        os.kill(pid, 0)  # sinal 0 = apenas verifica existencia, nao mata
    except ProcessLookupError:
        log(f"{nome_legivel} (PID {pid}) ja havia encerrado.")
        return
    except PermissionError:
        log(f"ERRO: sem permissao para encerrar {nome_legivel} (PID {pid}).")
        return

    # Envia SIGTERM — pedido gentil de encerramento
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        log(f"{nome_legivel} (PID {pid}) ja havia encerrado.")
        return

    # Aguarda ate 5 segundos para o processo encerrar
    for _ in range(10):  # 10 tentativas de 0.5s = 5 segundos no total
        time.sleep(0.5)
        try:
            os.kill(pid, 0)  # verifica se ainda existe
        except ProcessLookupError:
            # Processo encerrou — sucesso
            log(f"{nome_legivel} (PID {pid}) encerrado.")
            return

    # Ainda rodando apos 5 segundos — SIGKILL
    try:
        os.kill(pid, signal.SIGKILL)
        log(f"{nome_legivel} (PID {pid}) encerrado forcadamente.")
    except ProcessLookupError:
        log(f"{nome_legivel} (PID {pid}) encerrou durante a espera.")
    except Exception as erro:
        log(f"ERRO ao forcar encerramento de {nome_legivel} (PID {pid}): {erro}")


def remover_sentinela():
    """
    Remove o arquivo sentinela .gma_ativo.
    Nao falha se o arquivo ja nao existir.
    """
    if os.path.isfile(SENTINELA):
        os.remove(SENTINELA)
        log("Sentinela .gma_ativo removido.")
    else:
        log("Sentinela .gma_ativo nao encontrado (ja foi removido ou nunca existiu).")


# ── PONTO DE ENTRADA ──────────────────────────────────────────────────────────

def main():
    """
    Fluxo do encerrador de emergencia:

    1. Para cada script GMA (Porteiro, Leitor, Flask):
       a. Busca os PIDs com pgrep.
       b. Encerra cada PID encontrado.
    2. Remove o sentinela .gma_ativo.
    3. Exibe resumo do que foi feito.
    """

    print()
    print("=" * 60)
    print("  GMA — Encerramento de Emergencia")
    print(f"  {agora()}")
    print("=" * 60)
    print()

    # Guarda o total de processos encerrados para o resumo final
    total_encerrados = 0

    for item in SCRIPTS_GMA:
        nome_script  = item["script"]
        nome_legivel = item["nome"]

        pids = buscar_pids(nome_script)

        if not pids:
            log(f"{nome_legivel}: nenhum processo ativo encontrado.")
            continue

        for pid in pids:
            # Pequena protecao: nao encerrar o proprio processo deste script
            if pid == os.getpid():
                continue
            encerrar_pid(pid, nome_legivel)
            total_encerrados += 1

    # Remove o sentinela
    print()
    remover_sentinela()

    # Resumo final
    print()
    if total_encerrados == 0:
        log("Nenhum processo GMA estava rodando. Nada foi encerrado.")
    else:
        log(f"{total_encerrados} processo(s) encerrado(s).")

    log("Encerramento de emergencia concluido.")
    print()


if __name__ == "__main__":
    main()
