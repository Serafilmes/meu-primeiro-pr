#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
teste_transcricao.py — Camada 6, 1º tijolo (transcrição de áudio).

Cobre as partes MECÂNICAS (sem rodar o Whisper, que é pesado e mora na .venv_ia):
  1. arquivos_de_audio() acha só áudio e ignora não-mídia (régua única).
  2. transcrever_pasta() numa pasta SEM áudio devolve ok com n_audios=0.
  3. Banco: salvar_transcricao() grava texto + carimbo + evento no Log.
  4. Planilha: a coluna "Transcrição" existe, fica no bloco TÉCNICO (fixo) e
     ANTES da classificação variável; o valor sai certo.

A transcrição de verdade (Whisper) é validada ao vivo (ver contexto da sessão);
aqui o foco é a plumbing que sustenta o tijolo.

Rodar:  /usr/bin/python3 teste_transcricao.py
"""

import os
import sys
import tempfile

RAIZ = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, RAIZ)


def _ok(cond, msg):
    print(("PASS" if cond else "FALHOU") + " | " + msg)
    if not cond:
        raise AssertionError(msg)


def teste_arquivos_de_audio():
    import transcritor
    with tempfile.TemporaryDirectory() as d:
        sub = os.path.join(d, "AUDIO_001")
        os.makedirs(sub)
        # cria arquivos vazios de vários tipos
        for nome in ("gravacao.wav", "trilha.mp3", "clipe.mp4", "foto.jpg",
                     ".DS_Store", "relatorio_manifesto.json"):
            open(os.path.join(sub, nome), "w").close()
        achados = [os.path.basename(p) for p in transcritor.arquivos_de_audio(d)]
        _ok(set(achados) == {"gravacao.wav", "trilha.mp3"},
            f"acha só áudio, ignora vídeo/foto/lixo (achou {achados})")


def teste_pasta_sem_audio():
    import transcritor
    with tempfile.TemporaryDirectory() as d:
        open(os.path.join(d, "clipe.mp4"), "w").close()
        r = transcritor.transcrever_pasta(d)
        _ok(r["ok"] and r["n_audios"] == 0 and r["texto"] == "",
            "pasta sem áudio: ok=True, n_audios=0, texto vazio (não carrega Whisper)")
    # pasta inexistente
    r = transcritor.transcrever_pasta("/caminho/que/nao/existe")
    _ok(r["ok"] is False and "não encontrada" in (r["erro"] or ""),
        "pasta inexistente: ok=False com erro claro")


def teste_banco_e_planilha():
    db = os.path.join(tempfile.gettempdir(), "teste_transc_unit.db")
    for f in (db, db + "-wal", db + "-shm"):
        if os.path.exists(f):
            os.remove(f)
    os.environ["GMA_DB"] = db
    import banco_dados as bd
    bd.inicializar_banco()
    conn = bd.obter_conexao()

    cid = bd.gravar_cartao(conn, volume="AUD", caminho_origem="/Volumes/AUD",
                           marca_camera="Zoom", tipo_material="AUDIO")
    conn.execute("UPDATE cartoes SET numero_cartao='X_001', destino_pasta='/tmp/x', "
                 "status='concluido' WHERE id=?", (cid,))
    fid = bd.gravar_formulario(conn, id_form="f1", nome="FULANO", camera="Zoom",
                               tipo_material="AUDIO", data_gravacao="2026-06-21", tem_audio=1)
    bd.gravar_match(conn, cid, fid, score=9, criterios_lista=["t"], confirmado=1)
    # duas linhas em `arquivos` (uma por áudio), como a Camada 2 grava
    for nome in ("GRAVA_A.wav", "GRAVA_B.wav"):
        conn.execute("INSERT INTO arquivos (cartao_id, nome_arquivo, caminho_origem, tipo) "
                     "VALUES (?, ?, ?, 'AUDIO')", (cid, nome, "/Volumes/AUD/" + nome))
    conn.commit()

    # grava POR ARQUIVO (formato que o transcritor devolve)
    resultados = [
        {"nome": "GRAVA_A.wav", "texto": "fala do palco A", "erro": None},
        {"nome": "GRAVA_B.wav", "texto": "", "erro": None},  # áudio sem fala
    ]
    r = bd.salvar_transcricoes_arquivos(conn, cid, resultados)
    _ok(r["ok"] and r["n_arquivos_atualizados"] == 2,
        f"salvar_transcricoes_arquivos atualizou 2 arquivos ({r})")

    # cada arquivo guarda a SUA transcrição + carimbo
    linhas_arq = conn.execute(
        "SELECT nome_arquivo, transcricao, transcricao_em FROM arquivos "
        "WHERE cartao_id=? ORDER BY nome_arquivo", (cid,)).fetchall()
    _ok(linhas_arq[0]["transcricao"] == "fala do palco A" and linhas_arq[0]["transcricao_em"],
        "arquivo A tem sua transcrição e carimbo")
    _ok(linhas_arq[1]["transcricao"] == "" and linhas_arq[1]["transcricao_em"],
        "arquivo B (sem fala) fica processado com texto vazio (não NULL)")

    # evento no Log (governança)
    ev = conn.execute("SELECT COUNT(*) FROM eventos WHERE tipo='transcricao_concluida' "
                      "AND cartao_id=?", (cid,)).fetchone()[0]
    _ok(ev == 1, "evento 'transcricao_concluida' no Log")

    # coluna na planilha: existe, bloco técnico, antes da classificação, STATUS compacto
    colunas, linhas = bd.montar_planilha(conn)
    rotulos = [c["rotulo"] for c in colunas]
    _ok("Transcrição" in rotulos, "coluna Transcrição existe na planilha")
    col_transc = next(c for c in colunas if c["rotulo"] == "Transcrição")
    _ok(col_transc["bloco"] == "tecnicas", "coluna fica no bloco técnico (fixo)")

    idx_transc = rotulos.index("Transcrição")
    blocos = [c["bloco"] for c in colunas]
    if "classificacao" in blocos:
        idx_classif = blocos.index("classificacao")
        _ok(idx_transc < idx_classif,
            "Transcrição (fixo) vem ANTES da classificação variável")

    valor = linhas[0][idx_transc]
    _ok(valor == "2 áudio(s) transcrito(s)",
        f"célula mostra STATUS compacto, não o texto ({valor!r})")

    # idempotência defensiva: lista vazia não quebra
    r2 = bd.salvar_transcricoes_arquivos(conn, cid, [])
    _ok(r2["ok"] and r2["n_arquivos_atualizados"] == 0,
        "lista vazia: ok, 0 atualizados")
    conn.close()


if __name__ == "__main__":
    teste_arquivos_de_audio()
    teste_pasta_sem_audio()
    teste_banco_e_planilha()
    print("\nTODOS OS TESTES PASSARAM ✅")
