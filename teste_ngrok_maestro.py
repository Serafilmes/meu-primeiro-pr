#!/usr/bin/env python3
"""
teste_ngrok_maestro.py — ngrok como processo opcional do maestro (sessão 40).

Cobre as decisões de QUANDO o maestro NÃO sobe o ngrok (os caminhos seguros, que
não lançam o ngrok de verdade — isso exigiria authtoken + internet):
  1. ficha remota desligada no Painel
  2. link fixo/override configurado (você gere o túnel)
  3. ngrok não instalado

O caminho feliz (subir o túnel e detectar a URL no 4040) é verificado à mão, com
o authtoken configurado — não dá para automatizar sem credencial/rede.

Rodar:  python3 teste_ngrok_maestro.py
"""

import os
import shutil

import inicializar_gma as ig
import painel_config


def _patch_projeto(tunel_ativo=True, tunel_link=""):
    painel_config.projeto_ativo = lambda: (
        "teste", {"tunel_ativo": tunel_ativo, "tunel_link": tunel_link})


def teste_pula_sem_lancar_ngrok():
    orig_pa = painel_config.projeto_ativo
    orig_which = shutil.which
    orig_link = os.environ.get("GMA_LINK_FICHA")
    try:
        os.environ.pop("GMA_LINK_FICHA", None)

        # 1) ficha remota desligada → não sobe
        _patch_projeto(tunel_ativo=False)
        assert ig.iniciar_ngrok() is None
        print("OK  ficha remota desligada → maestro não sobe ngrok")

        # 2) link fixo/override → o maestro não gere o túnel
        _patch_projeto(tunel_ativo=True, tunel_link="https://meu.dominio.fixo")
        assert ig.iniciar_ngrok() is None
        print("OK  link fixo → maestro não sobe ngrok (você gere)")

        # 3) ngrok não instalado → segue sem túnel, sem quebrar
        _patch_projeto(tunel_ativo=True, tunel_link="")
        shutil.which = lambda nome: None
        assert ig.iniciar_ngrok() is None
        print("OK  ngrok não instalado → segue sem túnel (graceful)")
    finally:
        painel_config.projeto_ativo = orig_pa
        shutil.which = orig_which
        if orig_link is not None:
            os.environ["GMA_LINK_FICHA"] = orig_link


if __name__ == "__main__":
    teste_pula_sem_lancar_ngrok()
    print("\nTODOS OS TESTES PASSARAM ✅  — ngrok opcional, sobe só quando faz sentido")
