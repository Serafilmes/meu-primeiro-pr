#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
transcritor.py — Camada 6 (IA), o PRIMEIRO TIJOLO: transcrição de áudio.

O que faz (e só isso): pega uma pasta de material JÁ COPIADO no HD, acha os
arquivos de áudio e os transforma em TEXTO, usando o Whisper LOCAL
(faster-whisper). Devolve o texto. Não interpreta, não filtra, não decide nada —
é matéria-prima crua que depois alimenta a busca conversacional (Missão A).

PRINCÍPIOS QUE ESTE MÓDULO NUNCA QUEBRA
---------------------------------------
1. Assíncrono e OPCIONAL — nunca entra no ciclo crítico (copiar/conferir/auditar).
2. Lê SÓ o áudio já copiado no DESTINO (HD). Nunca toca no cartão.
3. Não move, não renomeia, não apaga NADA. Só lê.
4. A mídia NÃO sobe pra nuvem — o Whisper roda 100% local, offline e de graça.
   Só o TEXTO resultante é que vai (depois, por outra camada) para a planilha.

ONDE ESTE CÓDIGO RODA
---------------------
O faster-whisper é pesado e mora numa CAIXA ISOLADA (.venv_ia/), separada do
Python que roda o ciclo crítico. Por isso o resto do GMA (que roda no
/usr/bin/python3) NÃO importa este módulo direto: ele o chama como um
SUBPROCESSO, com o python da caixa:

    .venv_ia/bin/python transcritor.py <pasta_do_cartao>

A saída é uma linha JSON (fácil de o Flask ler de volta):

    {"ok": true, "texto": "...", "n_audios": 2, "arquivos": [...], "erro": null}

Pode também ser importado DENTRO da .venv_ia (ex.: testes) e usar as funções
transcrever_pasta()/arquivos_de_audio() diretamente.
"""

import os
import sys
import json

import ler_cartao  # régua única: o que é áudio / o que é não-mídia


# Modelo padrão do Whisper. "small" tem boa qualidade em português e roda em CPU.
# Trocável por "base" (mais rápido, menos preciso) ou "medium" (mais lento, melhor).
MODELO_PADRAO = "small"


def arquivos_de_audio(pasta):
    """
    Varre a pasta (e subpastas) e devolve os caminhos dos arquivos de ÁUDIO,
    na ordem do nome. Usa a régua única do GMA (ler_cartao) como fonte da verdade
    do que é áudio e do que é não-mídia a ignorar — nada de lista paralela.

    Poda as pastas ignoradas (ocultas, lixo do SO/cartão, pastas do próprio GMA)
    igual a C2/C4 fazem, para não tropeçar em sobras.
    """
    encontrados = []
    for raiz, dirs, nomes in os.walk(pasta):
        # Poda as pastas que nem a cópia nem a auditoria percorrem.
        dirs[:] = [d for d in dirs if not ler_cartao.eh_pasta_ignorada(d)]
        for nome in nomes:
            if ler_cartao.eh_nao_midia(nome):
                continue
            if ler_cartao.classificar_extensao(nome) == "AUDIO":
                encontrados.append(os.path.join(raiz, nome))
    encontrados.sort()
    return encontrados


def _carregar_modelo(modelo_nome):
    """Carrega o Whisper local (faster-whisper). Importado aqui dentro para que
    importar este módulo NÃO exija a biblioteca pesada quem só quer
    arquivos_de_audio()."""
    from faster_whisper import WhisperModel
    # int8 na CPU: leve e suficiente para fala; offline depois do 1º download.
    return WhisperModel(modelo_nome, device="cpu", compute_type="int8")


def transcrever_arquivo(modelo, caminho):
    """Transcreve UM arquivo de áudio e devolve o texto (string).

    language='pt' fixa o português (o material do GMA é em PT) — evita o Whisper
    "adivinhar" um idioma errado num trecho curto ou com ruído.
    """
    segmentos, _info = modelo.transcribe(caminho, language="pt")
    return " ".join(s.text.strip() for s in segmentos).strip()


def transcrever_pasta(pasta, modelo_nome=MODELO_PADRAO):
    """
    Transcreve TODOS os áudios de uma pasta de material já copiado.

    Devolve um dict pronto para virar JSON:
      ok        — True se rodou sem erro fatal (mesmo que não ache áudio)
      texto     — texto juntado de todos os áudios (o que vai pra coluna da planilha)
      n_audios  — quantos arquivos de áudio foram encontrados
      arquivos  — lista de {nome, texto, erro} por arquivo (rastro/diagnóstico)
      erro      — mensagem de erro fatal, ou None

    NUNCA levanta exceção para fora: erro vira campo no dict (o chamador é um
    subprocesso; é mais seguro ele sempre devolver JSON do que estourar).
    """
    if not pasta or not os.path.isdir(pasta):
        return {"ok": False, "texto": "", "n_audios": 0, "arquivos": [],
                "erro": f"pasta não encontrada: {pasta}"}

    audios = arquivos_de_audio(pasta)
    if not audios:
        return {"ok": True, "texto": "", "n_audios": 0, "arquivos": [],
                "erro": None}

    try:
        modelo = _carregar_modelo(modelo_nome)
    except Exception as e:  # falta da lib, modelo, etc. — vira erro de dado.
        return {"ok": False, "texto": "", "n_audios": len(audios), "arquivos": [],
                "erro": f"não consegui carregar o modelo Whisper: {e}"}

    resultados = []
    partes = []
    for caminho in audios:
        nome = os.path.basename(caminho)
        try:
            texto = transcrever_arquivo(modelo, caminho)
            resultados.append({"nome": nome, "caminho": caminho, "texto": texto, "erro": None})
            if texto:
                partes.append(f"[{nome}]\n{texto}")
        except Exception as e:
            resultados.append({"nome": nome, "caminho": caminho, "texto": "", "erro": str(e)})

    # `texto` aqui é só um resumo juntado (diagnóstico/Log). A verdade fica em
    # `arquivos` — uma transcrição POR ARQUIVO — que o banco grava separadamente.
    return {
        "ok": True,
        "texto": "\n\n".join(partes).strip(),
        "n_audios": len(audios),
        "arquivos": resultados,
        "erro": None,
    }


def main(argv):
    """Uso: transcritor.py <pasta> [modelo]
    Imprime UMA linha JSON com o resultado (o Flask lê de volta)."""
    if len(argv) < 2:
        print(json.dumps({"ok": False, "texto": "", "n_audios": 0,
                          "arquivos": [], "erro": "uso: transcritor.py <pasta> [modelo]"}))
        return 2
    pasta = argv[1]
    modelo_nome = argv[2] if len(argv) > 2 else MODELO_PADRAO
    resultado = transcrever_pasta(pasta, modelo_nome)
    print(json.dumps(resultado, ensure_ascii=False))
    return 0 if resultado["ok"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
