#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
vigia_transcricao.py — Camada 6 (IA): o GATILHO AUTOMÁTICO da transcrição.

O que faz (e só isso): de tempos em tempos, olha o banco à procura de cartões de
ÁUDIO já copiados que ainda não foram transcritos e dispara a transcrição sozinho
— sem ninguém clicar no botão 🎙. É o "vigia" da transcrição, irmão do
exportador_sheets.py: um laço simples, assíncrono, que roda FORA do ciclo crítico.

POR QUE EXISTE
--------------
Na s45 a transcrição nasceu com um botão manual na planilha. O idealizador pediu
(s47) que ela fosse AUTOMÁTICA: assim que um cartão de áudio termina a cópia, o
texto deve aparecer sozinho, sem trabalho do operador. Este vigia é esse gatilho.

PRINCÍPIOS QUE NUNCA QUEBRA (iguais aos do transcritor.py)
---------------------------------------------------------
1. Assíncrono e OPCIONAL — nunca entra no ciclo crítico (copiar/conferir/auditar).
   Se a caixa isolada da IA (.venv_ia) não existir, dorme em silêncio.
2. Lê SÓ o áudio já copiado no DESTINO (HD). Nunca toca no cartão físico.
3. Não move, não renomeia, não apaga NADA. Só lê o áudio e grava o TEXTO no banco.
4. 100% local, offline e de graça — o Whisper roda na máquina; a mídia NÃO sobe
   para a nuvem (só o texto vai, depois, para a planilha, por outra camada).

ONDE O WHISPER RODA
-------------------
Igual ao Flask: o motor pesado (faster-whisper) mora numa CAIXA ISOLADA
(.venv_ia/), separada do Python que roda este vigia e o ciclo crítico. Por isso
este arquivo NÃO importa o transcritor direto: chama transcritor.py como
SUBPROCESSO, com o python da caixa. Assim o vigia continua leve e o motor da IA
fica contido.

COMO RODA
---------
Sem argumentos → laço contínuo (modo de produção, subido pelo inicializar_gma):
    /usr/bin/python3 vigia_transcricao.py
--teste → roda UMA passada e sai (diagnóstico manual):
    /usr/bin/python3 vigia_transcricao.py --teste
"""

import os
import sys
import json
import time
import logging
import subprocess
from datetime import datetime

import banco_dados

# ── CONSTANTES ─────────────────────────────────────────────────────────────────

RAIZ_GMA = "/Users/serafa/GMA"

# Intervalo entre varreduras da fila (segundos). Generoso de propósito: a
# transcrição é assíncrona e opcional; não há pressa nenhuma.
INTERVALO_VARREDURA = 60

# A caixa isolada da IA e o motor de transcrição (mesmos caminhos do Flask).
PYTHON_IA = os.path.join(RAIZ_GMA, ".venv_ia", "bin", "python")
TRANSCRITOR_SCRIPT = os.path.join(RAIZ_GMA, "transcritor.py")

# Teto de tempo por cartão (1h). Áudio longo demora; está em background, tudo bem.
TIMEOUT_POR_CARTAO = 3600

# ── LOG ────────────────────────────────────────────────────────────────────────

os.makedirs(os.path.join(RAIZ_GMA, "logs"), exist_ok=True)

logging.basicConfig(
    filename=os.path.join(RAIZ_GMA, "logs", "vigia_transcricao.log"),
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
log = logging.getLogger(__name__)


# ── PRÉ-CONDIÇÃO ───────────────────────────────────────────────────────────────

def transcricao_disponivel():
    """True se a caixa isolada da IA e o transcritor existem (recurso instalado).

    Quando False, o vigia não tem como transcrever nada — então dorme em silêncio
    em vez de ficar tentando. Mantém o princípio do recurso OPCIONAL: uma máquina
    sem a .venv_ia simplesmente não faz transcrição, e o resto do GMA segue igual.
    """
    return os.path.exists(PYTHON_IA) and os.path.exists(TRANSCRITOR_SCRIPT)


# ── TRANSCRIÇÃO DE UM CARTÃO ───────────────────────────────────────────────────

def transcrever_cartao(conn, cartao):
    """
    Transcreve UM cartão de áudio (chama o transcritor.py como subprocesso) e
    grava o resultado no banco. Ao final, CARIMBA o cartão como tentado — assim
    ele sai da fila mesmo que não tenha achado fala (impede o vigia de repetir
    eternamente um cartão só-metadados, como o Sound Devices do teste s47).

    Nunca levanta exceção para fora: qualquer falha é logada e o cartão é
    carimbado mesmo assim (uma falha transitória pode ser reprocessada no botão
    manual 🎙, que limpa o carimbo). Devolve True se gravou alguma transcrição.

    Retorna (gravou: bool, n_audios: int).
    """
    cartao_id = cartao["id"]
    destino = (cartao.get("destino_pasta") or "").strip()
    rotulo = cartao.get("numero_cartao") or f"cartão {cartao_id}"

    if not destino or not os.path.isdir(destino):
        # Sem pasta de destino real não há o que transcrever; carimba e segue.
        log.warning(f"{rotulo}: destino inexistente ({destino!r}) — pulando.")
        banco_dados.marcar_transcricao_tentada(conn, cartao_id)
        return False, 0

    log.info(f"{rotulo}: transcrevendo áudio em {destino} …")
    try:
        proc = subprocess.run(
            [PYTHON_IA, TRANSCRITOR_SCRIPT, destino],
            capture_output=True, text=True, timeout=TIMEOUT_POR_CARTAO,
        )
        # O transcritor imprime UMA linha JSON em stdout (a última não-vazia).
        linha_json = ""
        for linha in (proc.stdout or "").splitlines():
            if linha.strip():
                linha_json = linha.strip()

        if not linha_json:
            log.error(f"{rotulo}: sem saída do transcritor | "
                      f"stderr: {(proc.stderr or '')[:300]}")
            banco_dados.marcar_transcricao_tentada(conn, cartao_id)
            return False, 0

        resultado = json.loads(linha_json)
        if not resultado.get("ok"):
            log.error(f"{rotulo}: transcritor falhou | {resultado.get('erro')}")
            banco_dados.marcar_transcricao_tentada(conn, cartao_id)
            return False, 0

        arquivos = resultado.get("arquivos", [])
        n_audios = resultado.get("n_audios", 0)
        r = banco_dados.salvar_transcricoes_arquivos(conn, cartao_id, arquivos)
        banco_dados.marcar_transcricao_tentada(conn, cartao_id)
        n_grav = r.get("n_arquivos_atualizados", 0)
        log.info(f"{rotulo}: concluído | {n_audios} áudio(s) | "
                 f"{n_grav} arquivo(s) gravado(s)")
        return n_grav > 0, n_audios

    except subprocess.TimeoutExpired:
        log.error(f"{rotulo}: timeout (>{TIMEOUT_POR_CARTAO}s) na transcrição.")
        banco_dados.marcar_transcricao_tentada(conn, cartao_id)
        return False, 0
    except Exception as e:
        log.error(f"{rotulo}: exceção na transcrição | {e}")
        banco_dados.marcar_transcricao_tentada(conn, cartao_id)
        return False, 0


def varrer_uma_vez(conn):
    """
    Uma passada: pega todos os cartões de áudio pendentes e transcreve um a um.
    Devolve quantos cartões foram processados nesta passada (0 = fila vazia).
    """
    pendentes = banco_dados.cartoes_pendentes_transcricao(conn)
    if not pendentes:
        return 0
    log.info(f"{len(pendentes)} cartão(ões) de áudio na fila de transcrição.")
    for cartao in pendentes:
        transcrever_cartao(conn, cartao)
    return len(pendentes)


# ── LOOP CONTÍNUO ──────────────────────────────────────────────────────────────

def loop_vigia():
    """
    Laço contínuo (roda como processo independente, subido pelo inicializar_gma).
    A cada INTERVALO_VARREDURA segundos, varre a fila de cartões de áudio
    pendentes e transcreve os que houver. Se a caixa da IA não estiver instalada,
    avisa uma vez e segue dormindo (recurso opcional).
    """
    print("[TRANSCRICAO]   Vigia da transcrição (Camada 6) iniciado.", flush=True)

    if not transcricao_disponivel():
        print("[TRANSCRICAO]   AVISO: caixa da IA (.venv_ia) não encontrada — "
              "transcrição automática desativada nesta máquina.", flush=True)
        log.warning("Caixa .venv_ia ausente — vigia em modo dormente.")

    while True:
        try:
            if transcricao_disponivel():
                conn = banco_dados.obter_conexao()
                n = varrer_uma_vez(conn)
                conn.close()
                if n:
                    print(f"[TRANSCRICAO]   {n} cartão(ões) processado(s) em "
                          f"{datetime.now().strftime('%H:%M:%S')}.", flush=True)
        except Exception as e:
            log.error(f"Erro no laço do vigia: {e}")

        time.sleep(INTERVALO_VARREDURA)


# ── PONTO DE ENTRADA ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    sys.path.insert(0, RAIZ_GMA)

    modo_teste = "--teste" in sys.argv

    if modo_teste:
        print()
        print("=" * 60)
        print("  GMA — Vigia da transcrição (passada única de teste)")
        print("=" * 60)
        print()

        if not transcricao_disponivel():
            print("ERRO: caixa da IA (.venv_ia) não encontrada.")
            print(f"  Esperado: {PYTHON_IA}")
            sys.exit(1)

        conn = banco_dados.obter_conexao()
        pendentes = banco_dados.cartoes_pendentes_transcricao(conn)
        print(f"Cartões de áudio pendentes: {len(pendentes)}")
        for c in pendentes:
            print(f"  • {c.get('numero_cartao') or c['id']}  →  {c['destino_pasta']}")
        print()
        if pendentes:
            print("Transcrevendo...")
            n = varrer_uma_vez(conn)
            print(f"OK — {n} cartão(ões) processado(s). Veja logs/vigia_transcricao.log")
        else:
            print("Nada na fila. (Nenhum cartão de áudio copiado e não transcrito.)")
        conn.close()
    else:
        loop_vigia()
