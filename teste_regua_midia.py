#!/usr/bin/env python3
"""
teste_regua_midia.py — Régua única do que é "mídia real" (sessão 40).

Prova que a Camada 2 (copiador, ao contar o que copia da ORIGEM) e a Camada 4
(auditoria, ao contar o DESTINO) usam a MESMA régua e chegam ao MESMO número —
fechando a ferida da sessão 39 (a auditoria travava contando um `.DS_Store` que
o Finder criou no destino: "108 vs 106").

Não toca em cartão real nem no banco: monta árvores de arquivos em /tmp.

Rodar:  python3 teste_regua_midia.py
"""

import os
import tempfile

import ler_cartao
import copiador
import auditoria


def _criar(raiz, caminho_relativo, conteudo=b"x"):
    """Cria um arquivo (com as subpastas necessárias) e devolve o caminho."""
    destino = os.path.join(raiz, caminho_relativo)
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    with open(destino, "wb") as f:
        f.write(conteudo)
    return destino


def teste_classificacao_basica():
    """A régua reconhece os 3 baldes de não-mídia + download, e poupa o material."""
    # Material → NÃO é "não-mídia"
    for nome in ("GX010001.MP4", "GOPR1234.JPG", "audio.wav", "raw.NEF",
                 "GL010001.LRV", "footage.xyz"):  # .xyz = desconhecido, é material
        assert not ler_cartao.eh_nao_midia(nome), f"{nome} deveria contar como material"

    # Balde 1 (SO) · 2 (cartão) · 3 (GMA) · download → SÃO não-mídia
    for nome in (".DS_Store", "Thumbs.db", "desktop.ini",          # SO
                 ".fseventsd", "._GX010001.MP4",                    # cartão/oculto
                 "JOAO_001_20260607.sppo", "x_relatorio.pdf",       # GMA
                 "x_manifesto.json",
                 "video.mp4.part", "foto.jpg.crdownload"):          # download
        assert ler_cartao.eh_nao_midia(nome), f"{nome} deveria ser ignorado"

    # Pastas ignoradas
    for pasta in (".Spotlight-V100", ".Trashes", "__MACOSX", "_GMA_frames"):
        assert ler_cartao.eh_pasta_ignorada(pasta), f"pasta {pasta} deveria ser podada"
    for pasta in ("VIDEO", "JOAO_001", "DCIM"):
        assert not ler_cartao.eh_pasta_ignorada(pasta), f"pasta {pasta} é material"
    print("OK  classificação básica (3 baldes + download + pastas)")


def teste_origem_e_destino_batem():
    """
    Reproduz a s39: a ORIGEM tem 4 mídias; o DESTINO recebe as mesmas 4 + o lixo
    que o Finder/GMA criam depois. As duas contagens têm que dar 4.
    """
    with tempfile.TemporaryDirectory() as base:
        origem  = os.path.join(base, "cartao")
        destino = os.path.join(base, "destino")

        # ORIGEM (cartão): 4 mídias + lixo de sistema do cartão
        for rel in ("DCIM/GX010001.MP4", "DCIM/GX010002.MP4",
                    "DCIM/GOPR1001.JPG", "DCIM/GL010001.LRV"):
            _criar(origem, rel)
        _criar(origem, ".fseventsd/0001")            # sistema do cartão (oculto)
        _criar(origem, "DCIM/.DS_Store")             # lixo do SO

        # DESTINO: as mesmas 4 mídias + arquivos do GMA + .DS_Store NOVO do Finder
        for rel in ("VIDEO/GX010001.MP4", "VIDEO/GX010002.MP4",
                    "FOTO/GOPR1001.JPG", "VIDEO/GL010001.LRV"):
            _criar(destino, rel)
        _criar(destino, "JOAO_001_20260607_022552.sppo")          # GMA
        _criar(destino, "JOAO_001_20260607_022552_relatorio.pdf") # GMA
        _criar(destino, "JOAO_001_20260607_022552_manifesto.json")# GMA
        _criar(destino, "_GMA_frames/GX010001_f01.jpg")           # GMA (pasta)
        _criar(destino, "VIDEO/.DS_Store")                        # <-- o vilão da s39
        _criar(destino, ".DS_Store")

        total_origem  = len(copiador.listar_arquivos_origem(origem))
        total_destino, _bytes = auditoria._auditar_destino(destino)

        assert total_origem == 4, f"origem deveria contar 4, contou {total_origem}"
        assert total_destino == 4, f"destino deveria contar 4, contou {total_destino}"
        assert total_origem == total_destino, "origem e destino divergiram!"
        print(f"OK  origem={total_origem} == destino={total_destino} "
              f"(o .DS_Store/.sppo/_GMA_frames não inflam mais a contagem)")


def teste_satelite_lixo_download():
    """Pasta satélite (Drive/Dropbox): __MACOSX e .part não contam; mídia conta."""
    with tempfile.TemporaryDirectory() as base:
        recebidos = os.path.join(base, "recebidos", "post42")
        for rel in ("entrega.mov", "foto1.jpg", "foto2.jpg"):
            _criar(recebidos, rel)
        _criar(recebidos, "__MACOSX/._entrega.mov")     # lixo de zip do macOS
        _criar(recebidos, "incompleto.mov.part")        # download pela metade
        _criar(recebidos, ".DS_Store")

        total = len(copiador.listar_arquivos_origem(recebidos))
        assert total == 3, f"satélite deveria contar 3 mídias, contou {total}"
        print(f"OK  pasta satélite: {total} mídias (lixo de download ignorado)")


if __name__ == "__main__":
    teste_classificacao_basica()
    teste_origem_e_destino_batem()
    teste_satelite_lixo_download()
    print("\nTODOS OS TESTES PASSARAM ✅  — régua única ligada na C2 e na C4")
