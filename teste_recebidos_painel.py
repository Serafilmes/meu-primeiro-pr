#!/usr/bin/env python3
"""
teste_recebidos_painel.py — caixa de "recebidos" no Painel (sessão 40, função B).

Cobre as funções puras que sustentam a caixa do cockpit:
  - painel_config.caminho_recebidos: padrão por projeto + override
  - painel_config.checar_recebidos:  o "Testar" (existe · gravável · só-na-nuvem),
    usando a régua única para ignorar lixo (.DS_Store, __MACOSX).

Não mexe no painel_estado.json real: usa dicts de config e pastas em /tmp.

Rodar:  python3 teste_recebidos_painel.py
"""

import os
import tempfile

import painel_config


def teste_caminho_padrao_e_override():
    # Laboratório (banco na raiz) → GMA/recebidos
    p = painel_config.caminho_recebidos({"db": "gma.db"})
    assert p == os.path.join(painel_config.RAIZ_GMA, "recebidos"), p
    # Projeto → ao lado do banco do projeto
    p2 = painel_config.caminho_recebidos({"db": os.path.join("projetos", "x", "gma.db")})
    assert p2 == os.path.join(painel_config.RAIZ_GMA, "projetos", "x", "recebidos"), p2
    # Override absoluto vence o padrão
    assert painel_config.caminho_recebidos({"db": "gma.db", "recebidos": "/tmp/minha"}) == "/tmp/minha"
    print("OK  caminho_recebidos: padrão por projeto + override")


def teste_testar_pasta():
    # Pasta inexistente → reprova com mensagem clara
    ok, msg = painel_config.checar_recebidos("/caminho/que/nao/existe/zzz")
    assert not ok and "não existe" in msg, msg

    with tempfile.TemporaryDirectory() as d:
        # Vazia mas gravável → aprova
        ok, msg = painel_config.checar_recebidos(d)
        assert ok and "vazia" in msg, msg

        # Com 1 mídia baixada + lixo que a régua ignora
        with open(os.path.join(d, "clipe.mov"), "wb") as f:
            f.write(b"x" * 100)
        with open(os.path.join(d, ".DS_Store"), "wb") as f:
            f.write(b"x")
        os.makedirs(os.path.join(d, "__MACOSX"), exist_ok=True)
        with open(os.path.join(d, "__MACOSX", "._clipe.mov"), "wb") as f:
            f.write(b"x")

        ok, msg = painel_config.checar_recebidos(d)
        assert ok and "1 arquivo" in msg, msg  # só o clipe.mov conta
    print("OK  checar_recebidos: inexistente · vazia · 1 mídia (lixo ignorado)")


if __name__ == "__main__":
    teste_caminho_padrao_e_override()
    teste_testar_pasta()
    print("\nTODOS OS TESTES PASSARAM ✅  — caixa de recebidos no Painel")
