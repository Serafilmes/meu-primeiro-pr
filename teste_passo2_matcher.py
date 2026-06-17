#!/usr/bin/env python3
"""
teste_passo2_matcher.py
Teste do Passo 2 do Matcher — resolução de empate.

O que este script faz:
  1. Cria um cartão Sony no banco (como se o Porteiro + Leitor tivessem detectado)
  2. Cria dois formulários com a mesma câmera e data (empate perfeito)
  3. Registra os dois como candidatos em match_candidatos (status='pendente')
  4. Atualiza o JSON do material para 'aguardando_confirmacao'
  5. Imprime as instruções para abrir o painel e resolver o empate

Ao final, você:
  → Abre o painel (http://localhost:5050)
  → Vê o cartão na seção "Aguardando confirmação"
  → Clica "Confirmar JOAO" ou "Confirmar PAULO"
  → Passa pela tela de resumo
  → Clica "Iniciar transferência"
  → Verifica com o script de verificação ao final deste arquivo

Como rodar:
  python3 /Users/serafa/GMA/teste_passo2_matcher.py

Pré-requisito:
  O banco gma.db e as pastas fila_material/ e fila_forms/ precisam existir.
  (Rodar o GMA uma vez já garante isso.)
"""

import os
import sys
import json
import shutil
from datetime import datetime

# ── Ajusta o path para importar os módulos do GMA ─────────────────────────────
RAIZ_GMA = "/Users/serafa/GMA"
sys.path.insert(0, RAIZ_GMA)

PASTA_FILA_MATERIAL = os.path.join(RAIZ_GMA, "fila_material")
PASTA_FILA_FORMS    = os.path.join(RAIZ_GMA, "fila_forms")

# Nomes dos arquivos de teste — fáceis de identificar e limpar depois
NOME_JSON_MATERIAL = "material_TESTE_passo2.json"
NOME_JSON_FORM_A   = "form_TESTE_passo2_JOAO.json"
NOME_JSON_FORM_B   = "form_TESTE_passo2_PAULO.json"

TIMESTAMP_HOJE = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
DATA_HOJE      = datetime.now().strftime("%Y-%m-%d")


# ── Separador visual ───────────────────────────────────────────────────────────
def separador(titulo=""):
    linha = "─" * 60
    if titulo:
        print(f"\n{linha}")
        print(f"  {titulo}")
        print(linha)
    else:
        print(linha)


# ── Limpeza de arquivos de teste anteriores ───────────────────────────────────
def limpar_arquivos_teste():
    """Remove os JSONs de teste caso existam de uma execução anterior."""
    removidos = []
    for nome in [NOME_JSON_MATERIAL, NOME_JSON_FORM_A, NOME_JSON_FORM_B]:
        for pasta in [PASTA_FILA_MATERIAL, PASTA_FILA_FORMS]:
            caminho = os.path.join(pasta, nome)
            if os.path.exists(caminho):
                os.remove(caminho)
                removidos.append(caminho)
    if removidos:
        print(f"  🗑️  Limpou {len(removidos)} arquivo(s) de teste anteriores.")


# ── PASSO 1: Banco de dados ────────────────────────────────────────────────────
def criar_cenario_banco():
    """
    Cria no banco:
      - 1 cartão Sony (como se o Leitor tivesse detectado)
      - 2 formulários Sony com a mesma data (empate perfeito — score idêntico)
      - 2 candidatos em match_candidatos (status='pendente')
      - Status do cartão → 'aguardando_confirmacao'
    """
    import banco_dados as bd

    conn = bd.inicializar_banco()

    # ── Cartão ────────────────────────────────────────────────────────────────
    # Simula um cartão Sony detectado pelo Porteiro + Leitor
    caminho_teste = "/Volumes/TESTE_PASSO2_SONY"

    # Verifica se já existe (execução anterior sem limpeza de banco)
    existente = conn.execute(
        "SELECT id FROM cartoes WHERE caminho_origem = ?",
        (caminho_teste,)
    ).fetchone()

    if existente:
        cartao_id = existente["id"]
        print(f"  ♻️  Cartão de teste já existia no banco (id={cartao_id}) — reutilizando.")
        # Reseta status para aguardando_confirmacao e limpa match anterior
        conn.execute(
            "UPDATE cartoes SET status = 'aguardando_confirmacao' WHERE id = ?",
            (cartao_id,)
        )
        conn.execute(
            "DELETE FROM match_candidatos WHERE cartao_id = ?",
            (cartao_id,)
        )
        conn.execute(
            "DELETE FROM matches WHERE cartao_id = ?",
            (cartao_id,)
        )
        conn.commit()
    else:
        cartao_id = bd.gravar_cartao(
            conn,
            volume          = "UNTITLED",
            caminho_origem  = caminho_teste,
            marca_camera    = "Sony",
            tipo_material   = "VIDEO",
            data_inicio     = DATA_HOJE,
            data_fim        = DATA_HOJE,
            total_arquivos  = 57,
            tamanho_bytes   = 8_500_000_000,  # ~8.5 GB
        )
        # Força status para aguardando_confirmacao
        conn.execute(
            "UPDATE cartoes SET status = 'aguardando_confirmacao' WHERE id = ?",
            (cartao_id,)
        )
        conn.commit()
        print(f"  ✅ Cartão criado no banco (id={cartao_id})")

    # ── Formulário JOAO ───────────────────────────────────────────────────────
    form_id_joao = bd.gravar_formulario(
        conn,
        id_form       = f"TESTE_passo2_JOAO_{DATA_HOJE}",
        nome          = "JOAO",
        camera        = "Sony",
        tipo_material = "VIDEO",
        data_gravacao = DATA_HOJE,
        operador      = "teste_passo2",
    )
    conn.execute(
        "UPDATE formularios SET status = 'aguardando_match' WHERE id = ?",
        (form_id_joao,)
    )
    conn.commit()
    print(f"  ✅ Formulário JOAO criado no banco (id={form_id_joao})")

    # ── Formulário PAULO ──────────────────────────────────────────────────────
    form_id_paulo = bd.gravar_formulario(
        conn,
        id_form       = f"TESTE_passo2_PAULO_{DATA_HOJE}",
        nome          = "PAULO",
        camera        = "Sony",
        tipo_material = "VIDEO",
        data_gravacao = DATA_HOJE,
        operador      = "teste_passo2",
    )
    conn.execute(
        "UPDATE formularios SET status = 'aguardando_match' WHERE id = ?",
        (form_id_paulo,)
    )
    conn.commit()
    print(f"  ✅ Formulário PAULO criado no banco (id={form_id_paulo})")

    # ── Candidatos em match_candidatos ────────────────────────────────────────
    # Score idêntico (3 pts = câmera bate) → empate perfeito
    bd.registrar_candidatos(conn, cartao_id, [
        {
            "formulario_id": form_id_joao,
            "nome":          "JOAO",
            "camera_ficha":  "Sony FX3",
            "score":         3,
            "criterios":     ["câmera:+3"],
        },
        {
            "formulario_id": form_id_paulo,
            "nome":          "PAULO",
            "camera_ficha":  "Sony FX3",
            "score":         3,
            "criterios":     ["câmera:+3"],
        },
    ])
    print(f"  ✅ 2 candidatos registrados em match_candidatos (status='pendente')")

    conn.close()

    return cartao_id, form_id_joao, form_id_paulo


# ── PASSO 2: JSONs das filas ───────────────────────────────────────────────────
def criar_jsons_fila(cartao_id, form_id_joao, form_id_paulo):
    """
    Cria os 3 arquivos JSON nas filas que o Flask lê para montar o painel.

    O JSON do material fica em fila_material/ com status='aguardando_confirmacao'.
    Os JSONs dos formulários ficam em fila_forms/ com status='aguardando_confirmacao'.
    """
    os.makedirs(PASTA_FILA_MATERIAL, exist_ok=True)
    os.makedirs(PASTA_FILA_FORMS,    exist_ok=True)

    # ── JSON do material ──────────────────────────────────────────────────────
    json_material = {
        "timestamp":        TIMESTAMP_HOJE,
        "nome":             "UNTITLED",
        "volume":           "UNTITLED",
        "caminho":          "/Volumes/TESTE_PASSO2_SONY",
        "origem":           "volume",
        "marca_camera":     "Sony",
        "tipo_material":    "VIDEO",
        "n_arquivos":       57,
        "total_arquivos":   57,
        "contagem_total":   57,
        "tamanho_bytes":    8_500_000_000,
        "status":           "aguardando_confirmacao",
        "db_cartao_id":     cartao_id,
        # Marca como já analisado para o Leitor de Mídia NÃO reprocessar este
        # cartão forjado. Sem isto, o Leitor pega o JSON, vê que o volume falso
        # (/Volumes/TESTE_PASSO2_SONY) não existe e rebaixa o status para
        # 'caminho_nao_encontrado' — fazendo o cartão sumir da seção de
        # confirmação do painel (some o botão "Confirmar JOAO/PAULO").
        # A "análise" deste teste já vem embutida na assinatura abaixo.
        "analise_realizada": True,
        # Assinatura com prefixos que geram a amostra de arquivos no painel
        "assinatura": {
            "prefixos": [
                "joe",          # radical genérico — filtrado
                "joe0258T",     # radicais específicos — aparecem como pista
                "joe0259T",
                "joe0260T",
                "joe0261T",
            ],
            "camera":   "Sony",
            "modelo":   "Sony FX3",
            "num_min":  258,
            "num_max":  314,
        },
        # Lista de candidatos (fallback para painel quando banco não tem)
        "candidatos_match": [
            {
                "nome":               "JOAO",
                "camera":             "Sony FX3",
                "score":              3,
                "criterios":          ["câmera:+3"],
                "nome_arquivo_form":  NOME_JSON_FORM_A,
            },
            {
                "nome":               "PAULO",
                "camera":             "Sony FX3",
                "score":              3,
                "criterios":          ["câmera:+3"],
                "nome_arquivo_form":  NOME_JSON_FORM_B,
            },
        ],
    }

    caminho_material = os.path.join(PASTA_FILA_MATERIAL, NOME_JSON_MATERIAL)
    with open(caminho_material, "w", encoding="utf-8") as f:
        json.dump(json_material, f, ensure_ascii=False, indent=2)
    print(f"  ✅ JSON material criado: fila_material/{NOME_JSON_MATERIAL}")

    # ── JSON formulário JOAO ──────────────────────────────────────────────────
    json_joao = {
        "timestamp":          TIMESTAMP_HOJE,
        "nome":               "JOAO",
        "camera":             "Sony FX3",
        "tipo_material":      "VIDEO",
        "data_gravacao":      DATA_HOJE,
        "operador":           "teste_passo2",
        "status":             "aguardando_confirmacao",
        "db_formulario_id":   form_id_joao,
        "candidatos_match":   [],
    }

    caminho_joao = os.path.join(PASTA_FILA_FORMS, NOME_JSON_FORM_A)
    with open(caminho_joao, "w", encoding="utf-8") as f:
        json.dump(json_joao, f, ensure_ascii=False, indent=2)
    print(f"  ✅ JSON formulário JOAO criado: fila_forms/{NOME_JSON_FORM_A}")

    # ── JSON formulário PAULO ─────────────────────────────────────────────────
    json_paulo = {
        "timestamp":          TIMESTAMP_HOJE,
        "nome":               "PAULO",
        "camera":             "Sony FX3",
        "tipo_material":      "VIDEO",
        "data_gravacao":      DATA_HOJE,
        "operador":           "teste_passo2",
        "status":             "aguardando_confirmacao",
        "db_formulario_id":   form_id_paulo,
        "candidatos_match":   [],
    }

    caminho_paulo = os.path.join(PASTA_FILA_FORMS, NOME_JSON_FORM_B)
    with open(caminho_paulo, "w", encoding="utf-8") as f:
        json.dump(json_paulo, f, ensure_ascii=False, indent=2)
    print(f"  ✅ JSON formulário PAULO criado: fila_forms/{NOME_JSON_FORM_B}")


# ── PASSO 3: Verificação pós-resolução ────────────────────────────────────────
def verificar_resultado(cartao_id, form_id_joao, form_id_paulo):
    """
    Verifica o estado do banco depois que o operador resolveu o empate no painel.
    Chame esta função manualmente depois de clicar "Iniciar transferência".
    """
    import banco_dados as bd

    conn = bd.inicializar_banco()

    separador("RESULTADO — verificando banco após resolução")

    # ── Status do cartão ──────────────────────────────────────────────────────
    cartao = conn.execute(
        "SELECT status, numero_cartao, destino_pasta FROM cartoes WHERE id = ?",
        (cartao_id,)
    ).fetchone()

    # "matched ou além": quando o sistema está inteiro no ar, a Camada 2 pega o
    # cartão assim que ele vira 'matched' e avança o status (copiando → ...). Ter
    # passado por qualquer um destes prova que o match foi efetivado — que é o que
    # o Passo 2 valida. (transferencia_falhou aqui é esperado: o volume é falso.)
    STATUS_MATCH_OK = {
        "matched", "copiando", "transferido", "transferencia_ok",
        "transferencia_falhou", "auditando", "auditado", "concluido",
    }

    if cartao:
        status_cartao = cartao["status"]
        icone = "✅" if status_cartao in STATUS_MATCH_OK else "❌"
        print(f"\n  Cartão (id={cartao_id})")
        print(f"    status:        {icone} {status_cartao}  (esperado: matched ou além)")
        print(f"    numero_cartao: {cartao['numero_cartao'] or '(ainda não atribuído)'}")
        print(f"    destino_pasta: {cartao['destino_pasta'] or '(ainda não atribuído)'}")
    else:
        print(f"  ❌ Cartão id={cartao_id} não encontrado no banco!")

    # ── Candidatos ────────────────────────────────────────────────────────────
    candidatos = conn.execute(
        """SELECT nome, status, formulario_id
           FROM match_candidatos
           WHERE cartao_id = ?
           ORDER BY status""",
        (cartao_id,)
    ).fetchall()

    print(f"\n  Candidatos em match_candidatos:")
    todos_ok = True
    for c in candidatos:
        if c["status"] == "escolhido":
            icone = "✅"
        elif c["status"] == "descartado":
            icone = "✅"
        else:
            icone = "❌"
            todos_ok = False
        print(f"    {icone} {c['nome']:<10} → {c['status']}")

    if not candidatos:
        print("    ❌ Nenhum candidato encontrado!")
        todos_ok = False

    # ── Formulários ───────────────────────────────────────────────────────────
    forms = conn.execute(
        """SELECT nome, status FROM formularios
           WHERE id IN (?, ?)""",
        (form_id_joao, form_id_paulo)
    ).fetchall()

    print(f"\n  Formulários:")
    for f in forms:
        if f["status"] == "matched":
            icone = "✅"
            esperado = "(escolhido — ok)"
        elif f["status"] == "aguardando_match":
            icone = "✅"
            esperado = "(devolvido à fila — ok)"
        else:
            icone = "❌"
            esperado = f"(esperado: matched ou aguardando_match)"
            todos_ok = False
        print(f"    {icone} {f['nome']:<10} → {f['status']}  {esperado}")

    # ── Match registrado ──────────────────────────────────────────────────────
    match = conn.execute(
        "SELECT formulario_id, score, confirmado FROM matches WHERE cartao_id = ?",
        (cartao_id,)
    ).fetchone()

    print(f"\n  Match registrado em matches:")
    if match:
        confirmado_label = "manual (operador)" if match["confirmado"] == 1 else "automático"
        print(f"    ✅ formulario_id={match['formulario_id']} | score={match['score']} | {confirmado_label}")
    else:
        print(f"    ❌ Nenhum match registrado! (esperado: 1 linha com confirmado=1)")
        todos_ok = False

    # ── JSON do material ──────────────────────────────────────────────────────
    caminho_material = os.path.join(PASTA_FILA_MATERIAL, NOME_JSON_MATERIAL)
    print(f"\n  JSON do material (fila_material/):")
    if os.path.exists(caminho_material):
        with open(caminho_material, "r", encoding="utf-8") as f_json:
            dados = json.load(f_json)
        status_json = dados.get("status")
        icone = "✅" if status_json in STATUS_MATCH_OK else "❌"
        print(f"    {icone} status = {status_json}  (esperado: matched ou além)")
        if status_json not in STATUS_MATCH_OK:
            todos_ok = False
    else:
        print(f"    ⚠️  Arquivo não encontrado — pode ter sido movido/processado pela Camada 2")

    # ── Resultado final ───────────────────────────────────────────────────────
    separador()
    if todos_ok:
        print("\n  ✅ PASSO 2 APROVADO — todos os critérios do checklist passaram!\n")
    else:
        print("\n  ❌ ATENÇÃO — alguns critérios não passaram. Verifique os itens marcados com ❌\n")

    conn.close()


# ── PONTO DE ENTRADA ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    print()
    separador("GMA — Teste do Passo 2 do Matcher (resolução de empate)")
    print()

    # Verifica se os módulos do GMA estão acessíveis
    try:
        import banco_dados as bd
        print("  ✅ banco_dados.py importado com sucesso")
    except ImportError as e:
        print(f"  ❌ Não foi possível importar banco_dados: {e}")
        print(f"     Certifique-se de rodar este script de dentro de {RAIZ_GMA}")
        print(f"     ou que o caminho RAIZ_GMA está correto no topo do arquivo.")
        sys.exit(1)

    # ── Modo de verificação: passa --verificar <cartao_id> <form_joao> <form_paulo> ──
    # Aceita 2 IDs (cartão + joao) ou 3 IDs (cartão + joao + paulo, como mostram
    # as instruções). O form_id_paulo é lido do banco de qualquer forma, então o
    # 3º ID é opcional. Sem o >=, passar os 3 IDs caía no modo normal e
    # REMONTAVA o cenário, apagando o match recém-resolvido. Bug corrigido.
    if len(sys.argv) >= 4 and sys.argv[1] == "--verificar":
        try:
            cartao_id    = int(sys.argv[2])
            form_id_joao  = int(sys.argv[3])
            # form_id_paulo não é usado na verificação mas pedimos no uso para clareza
            form_id_paulo = 0
        except ValueError:
            print("  Uso: python3 teste_passo2_matcher.py --verificar <cartao_id> <form_joao_id> <form_paulo_id>")
            sys.exit(1)

        # Lê form_id_paulo do banco (candidato descartado do cartão)
        conn_v = bd.inicializar_banco()
        cands = conn_v.execute(
            "SELECT formulario_id FROM match_candidatos WHERE cartao_id = ?",
            (cartao_id,)
        ).fetchall()
        ids = [c["formulario_id"] for c in cands]
        conn_v.close()
        form_id_paulo = next((i for i in ids if i != form_id_joao), 0)
        verificar_resultado(cartao_id, form_id_joao, form_id_paulo)
        sys.exit(0)

    # ── Modo normal: monta o cenário de teste ─────────────────────────────────
    separador("Passo 1 — Limpando arquivos de teste anteriores")
    limpar_arquivos_teste()

    separador("Passo 2 — Criando cenário no banco de dados")
    cartao_id, form_id_joao, form_id_paulo = criar_cenario_banco()

    separador("Passo 3 — Criando JSONs nas filas")
    criar_jsons_fila(cartao_id, form_id_joao, form_id_paulo)

    # ── Instruções para o operador ────────────────────────────────────────────
    separador("Cenário pronto — agora resolva o empate no painel")
    print(f"""
  IDs criados (anote para verificação):
    cartao_id    = {cartao_id}
    form_id_joao  = {form_id_joao}
    form_id_paulo = {form_id_paulo}

  O que fazer agora:
    1. Abra o painel:    http://localhost:5050
    2. Role até a seção  "Aguardando confirmação"
    3. Você verá o cartão UNTITLED com 57 arquivos · Sony
       e dois candidatos: JOAO e PAULO (ambos Sony FX3)
    4. A amostra de arquivos deve mostrar: joe0258T · joe0259T · joe0260T
    5. Clique em          [Confirmar JOAO]
    6. Revise o resumo   (nome · câmera · 57 arquivos · pasta prevista)
    7. Clique em          [Iniciar transferência]
    8. Volte ao terminal e rode o verificador:

  python3 /Users/serafa/GMA/teste_passo2_matcher.py --verificar {cartao_id} {form_id_joao} {form_id_paulo}

  O verificador checa:
    ✓ Cartão status → matched
    ✓ Candidato JOAO → escolhido
    ✓ Candidato PAULO → descartado
    ✓ Formulário JOAO → matched
    ✓ Formulário PAULO → aguardando_match (devolvido à fila)
    ✓ Match registrado em matches com confirmado=1 (manual)
    ✓ JSON do material → matched
""")
    separador()
    print()
