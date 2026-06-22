#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
teste_vigia_transcricao.py — Camada 6: o GATILHO AUTOMÁTICO da transcrição (s48).

Cobre a lógica do vigia SEM rodar o Whisper de verdade (pesado, mora na .venv_ia):
um `subprocess.run` FALSO devolve o JSON que o transcritor.py produziria, para
exercitar parse → gravação → carimbo → saída da fila.

O que valida:
  1. cartoes_pendentes_transcricao(): só pega cartão de ÁUDIO, copiado, não-tentado.
     Exclui: não-áudio, sem destino, status errado, já carimbado.
  2. marcar_/limpar_transcricao_tentada(): carimbar tira da fila; limpar devolve.
  3. transcrever_cartao(): grava a transcrição, carimba e o cartão SAI da fila.
  4. Cartão de áudio SEM fala (0 áudios — caso Sound Devices da s47): é carimbado
     UMA vez e some da fila (não fica repetindo para sempre).

Rodar:  /usr/bin/python3 teste_vigia_transcricao.py
"""

import os
import sys
import json
import tempfile

RAIZ = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, RAIZ)

# CRÍTICO: o banco_dados fixa o caminho do banco (CAMINHO_BANCO) NO IMPORT, lendo
# GMA_DB. Por isso precisamos apontar para um banco de TESTE ANTES de qualquer
# import do GMA (banco_dados/vigia_transcricao) — senão os testes escreveriam no
# gma.db real do laboratório. Define aqui, no topo, e o _banco_limpo reusa.
BANCO_TESTE = os.path.join(tempfile.gettempdir(), "teste_vigia_transc.db")
os.environ["GMA_DB"] = BANCO_TESTE


def _ok(cond, msg):
    print(("PASS" if cond else "FALHOU") + " | " + msg)
    if not cond:
        raise AssertionError(msg)


class _ProcFalso:
    """Imita o objeto devolvido por subprocess.run: .stdout / .stderr."""
    def __init__(self, stdout, stderr=""):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = 0


def _banco_limpo():
    db = BANCO_TESTE  # mesmo caminho que CAMINHO_BANCO fixou no import (topo do arquivo)
    for f in (db, db + "-wal", db + "-shm"):
        if os.path.exists(f):
            os.remove(f)
    import banco_dados as bd
    bd.inicializar_banco()
    return bd, bd.obter_conexao()


def _criar_cartao_audio(bd, conn, volume, destino, status="concluido",
                        tipo="AUDIO", arquivos=("A.wav", "B.wav")):
    """Cria um cartão e suas linhas em `arquivos`, como a Camada 2 deixaria."""
    cid = bd.gravar_cartao(conn, volume=volume, caminho_origem="/Volumes/" + volume,
                           marca_camera="Zoom", tipo_material=tipo)
    conn.execute("UPDATE cartoes SET numero_cartao=?, destino_pasta=?, status=? "
                 "WHERE id=?", (volume + "_001", destino, status, cid))
    for nome in arquivos:
        conn.execute("INSERT INTO arquivos (cartao_id, nome_arquivo, caminho_origem, tipo) "
                     "VALUES (?, ?, ?, 'AUDIO')", (cid, nome, destino + "/" + nome))
    conn.commit()
    return cid


def teste_fila_pendentes():
    bd, conn = _banco_limpo()
    with tempfile.TemporaryDirectory() as d:
        # (a) áudio copiado e concluído → ENTRA na fila
        cid_ok = _criar_cartao_audio(bd, conn, "AUD", d, status="concluido")
        # (b) áudio só copiado (transferencia_ok) → ENTRA (gatilho é pós-cópia)
        cid_tok = _criar_cartao_audio(bd, conn, "TOK", d, status="transferencia_ok")
        # (c) áudio ainda copiando → FORA
        _criar_cartao_audio(bd, conn, "COP", d, status="copiando")
        # (d) áudio sem destino → FORA
        cid_sd = _criar_cartao_audio(bd, conn, "SEMD", d, status="concluido")
        conn.execute("UPDATE cartoes SET destino_pasta=NULL WHERE id=?", (cid_sd,))
        # (e) NÃO-áudio (vídeo) copiado → FORA
        _criar_cartao_audio(bd, conn, "VID", d, status="concluido", tipo="VIDEO")
        conn.commit()

        ids = {c["id"] for c in bd.cartoes_pendentes_transcricao(conn)}
        _ok(ids == {cid_ok, cid_tok},
            f"fila = só áudio copiado/concluído com destino (esperado {{{cid_ok},{cid_tok}}}, veio {ids})")
    conn.close()


def teste_carimbo_entra_e_sai_da_fila():
    bd, conn = _banco_limpo()
    with tempfile.TemporaryDirectory() as d:
        cid = _criar_cartao_audio(bd, conn, "AUD", d)
        _ok(any(c["id"] == cid for c in bd.cartoes_pendentes_transcricao(conn)),
            "cartão novo começa NA fila")

        bd.marcar_transcricao_tentada(conn, cid)
        _ok(not any(c["id"] == cid for c in bd.cartoes_pendentes_transcricao(conn)),
            "depois de carimbado, SAI da fila")

        bd.limpar_transcricao_tentada(conn, cid)
        _ok(any(c["id"] == cid for c in bd.cartoes_pendentes_transcricao(conn)),
            "limpar o carimbo DEVOLVE à fila (reprocessar)")
    conn.close()


def teste_transcrever_cartao_grava_e_carimba(monkeypatch_run):
    bd, conn = _banco_limpo()
    import vigia_transcricao as vt
    with tempfile.TemporaryDirectory() as d:
        cid = _criar_cartao_audio(bd, conn, "AUD", d, arquivos=("A.wav", "B.wav"))

        # subprocess.run FALSO: devolve o JSON que o transcritor.py produziria.
        saida = {"ok": True, "n_audios": 2, "erro": None, "arquivos": [
            {"nome": "A.wav", "texto": "fala do palco principal", "erro": None},
            {"nome": "B.wav", "texto": "", "erro": None},
        ]}
        monkeypatch_run(vt, _ProcFalso(json.dumps(saida, ensure_ascii=False)))

        cartao = bd.cartoes_pendentes_transcricao(conn)[0]
        gravou, n = vt.transcrever_cartao(conn, cartao)
        _ok(gravou and n == 2, f"transcrever_cartao gravou ({gravou}) e contou 2 áudios ({n})")

        # o texto foi gravado POR ARQUIVO
        txt = conn.execute("SELECT transcricao FROM arquivos WHERE cartao_id=? AND nome_arquivo='A.wav'",
                           (cid,)).fetchone()["transcricao"]
        _ok(txt == "fala do palco principal", "transcrição do arquivo A gravada no banco")

        # e o cartão saiu da fila (carimbado)
        _ok(not bd.cartoes_pendentes_transcricao(conn),
            "depois de transcrito, o cartão SAI da fila")
    conn.close()


def teste_cartao_sem_fala_sai_da_fila(monkeypatch_run):
    """Caso Sound Devices (s47): cartão de áudio com 0 áudios reais. Tem de ser
    carimbado UMA vez e sumir da fila — nunca ficar repetindo."""
    bd, conn = _banco_limpo()
    import vigia_transcricao as vt
    with tempfile.TemporaryDirectory() as d:
        # cartão de áudio SEM linhas de arquivo de áudio (só metadados na vida real)
        cid = _criar_cartao_audio(bd, conn, "SDEV", d, arquivos=())

        # transcritor devolve ok com 0 áudios
        saida = {"ok": True, "n_audios": 0, "erro": None, "arquivos": []}
        monkeypatch_run(vt, _ProcFalso(json.dumps(saida)))

        cartao = bd.cartoes_pendentes_transcricao(conn)[0]
        gravou, n = vt.transcrever_cartao(conn, cartao)
        _ok(gravou is False and n == 0, "cartão sem fala: nada gravado, 0 áudios")
        _ok(not bd.cartoes_pendentes_transcricao(conn),
            "cartão sem fala foi carimbado e NÃO volta à fila (sem loop eterno)")

        carimbo = conn.execute("SELECT transcricao_tentada_em FROM cartoes WHERE id=?",
                              (cid,)).fetchone()["transcricao_tentada_em"]
        _ok(bool(carimbo), "carimbo transcricao_tentada_em preenchido")
    conn.close()


def teste_varrer_uma_vez_processa_todos(monkeypatch_run):
    bd, conn = _banco_limpo()
    import vigia_transcricao as vt
    with tempfile.TemporaryDirectory() as d:
        for v in ("UM", "DOIS", "TRES"):
            _criar_cartao_audio(bd, conn, v, d, arquivos=("G.wav",))
        saida = {"ok": True, "n_audios": 1, "erro": None,
                 "arquivos": [{"nome": "G.wav", "texto": "oi", "erro": None}]}
        monkeypatch_run(vt, _ProcFalso(json.dumps(saida)))

        n = vt.varrer_uma_vez(conn)
        _ok(n == 3, f"varreu e processou os 3 cartões ({n})")
        _ok(vt.varrer_uma_vez(conn) == 0,
            "segunda varredura: fila vazia (todos carimbados) — nada a refazer")
    conn.close()


if __name__ == "__main__":
    import subprocess

    def _patch(modulo, proc_falso):
        """Substitui subprocess.run dentro do módulo do vigia por um que devolve
        o objeto falso (sem chamar o Whisper)."""
        modulo.subprocess.run = lambda *a, **k: proc_falso

    # Garante o módulo importado e restaura no fim.
    import vigia_transcricao as _vt
    _run_original = subprocess.run
    try:
        teste_fila_pendentes()
        teste_carimbo_entra_e_sai_da_fila()
        teste_transcrever_cartao_grava_e_carimba(_patch)
        teste_cartao_sem_fala_sai_da_fila(_patch)
        teste_varrer_uma_vez_processa_todos(_patch)
    finally:
        _vt.subprocess.run = _run_original
    print("\nTODOS OS TESTES PASSARAM ✅")
