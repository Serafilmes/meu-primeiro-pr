#!/usr/bin/env python3
"""
teste_trava_maestro.py — trava de instância única do maestro (sessão 40).

Prova que dois maestros não sobem juntos: o 1º pega a trava (flock), um 2º
processo é RECUSADO, e depois que o 1º libera, um novo consegue. É a blindagem
contra o "maestro duplicado" que aparecia ao clicar 'Iniciar' duas vezes.

Usa um lock em /tmp (não toca no .gma_maestro.lock real). O processo-filho
recebe o caminho por variável de ambiente para travar o MESMO arquivo.

Rodar:  python3 teste_trava_maestro.py
"""

import os
import sys
import tempfile
import subprocess

import inicializar_gma as ig

# Snippet que uma 2ª instância roda: tenta a trava no MESMO arquivo e sai com
# 0 se conseguiu, 7 se foi recusada.
_FILHO = (
    "import os, sys, inicializar_gma as ig;"
    "ig.TRAVA_MAESTRO = os.environ['LOCK'];"
    "sys.exit(0 if ig.adquirir_trava_maestro() else 7)"
)


def _tentar_em_outro_processo(lock):
    r = subprocess.run([sys.executable, "-c", _FILHO],
                       env={**os.environ, "LOCK": lock},
                       capture_output=True, text=True)
    return r.returncode


def teste_trava_unica():
    with tempfile.TemporaryDirectory() as d:
        lock = os.path.join(d, "maestro.lock")
        ig.TRAVA_MAESTRO = lock

        # 1º maestro pega a trava
        assert ig.adquirir_trava_maestro() is True, "o 1º deveria conseguir a trava"

        # 2º (processo separado) é recusado enquanto o 1º segura
        rc = _tentar_em_outro_processo(lock)
        assert rc == 7, f"o 2º maestro deveria ser RECUSADO (esperado 7, veio {rc})"
        print("OK  com a trava tomada, um 2º maestro é recusado")

        # o 1º libera → agora um novo consegue
        ig.liberar_trava_maestro()
        rc2 = _tentar_em_outro_processo(lock)
        assert rc2 == 0, f"após liberar, um novo deveria conseguir (esperado 0, veio {rc2})"
        print("OK  após liberar a trava, um novo maestro consegue subir")


if __name__ == "__main__":
    teste_trava_unica()
    print("\nTODOS OS TESTES PASSARAM ✅  — um só maestro por vez")
