#!/usr/bin/env python3
"""
matcher.py
Camada 1 do GMA — Cruzamento de material detectado com formulários de check-in.

Este módulo é chamado sempre que um novo arquivo chega em fila_material/ (material
detectado pelo Porteiro) ou em fila_forms/ (formulário recebido pelo Flask).

Responsabilidade:
  - Tentar fazer match de cada material com um formulário compatível.
  - Um "match" significa que o material físico e o formulário preenchido
    pela equipe referem-se ao mesmo cartão.
  - Quando o match é confirmado, os dois arquivos são atualizados e uma
    linha é gravada no log. O resultado combinado (material + form) é retornado
    para o próximo passo do fluxo GMA (o Leitor de Mídia / ler_cartao.py).
  - Quando há EMPATE ou QUASE-EMPATE, o sistema NÃO casa: marca os envolvidos como
    "aguardando_confirmacao" para o operador resolver manualmente no painel.

Pontuação de compatibilidade (basta ≥ 3 pontos para confirmar o match):
  +3  → marca da câmera bate entre material e formulário
  +2  → data do formulário é a mesma do timestamp do material (mesmo dia)
  +2  → origem é pasta_entrada e o nome da pasta contém o nome do profissional do form
  +1  → tipo de material do formulário (VIDEO/FOTO/AUDIO) bate com o tipo predominante
         detectado no cartão (via campo contagem_tipo do JSON do material)

Trava de segurança anti-ambiguidade:
  Um match só é confirmado automaticamente quando o vencedor é ESTRITAMENTE melhor
  que qualquer concorrente por pelo menos MARGEM_SEGURANCA ponto (de ambos os lados:
  o form não pode estar disputado entre cartões, e o cartão não pode estar disputado
  entre fichas). Em caso de empate ou quase-empate, o sistema segura e marca como
  "aguardando_confirmacao".

Sem dependências externas — usa só a biblioteca padrão do Python 3.

Uso direto (para teste):
    python3 matcher.py

Para criar um formulário de teste antes:
    python3 -c "from matcher import criar_form_teste; criar_form_teste('PRODUTORA_X', 'Blackmagic', 'VIDEO', '2026-06-05')"
"""

import os
import json
import logging
from datetime import datetime, timedelta

# ── CONFIGURAÇÃO DE CAMINHOS ───────────────────────────────────────────────────

# Raiz do projeto GMA
RAIZ_GMA = "/Users/serafa/GMA"

# Isolamento multi-projeto (Camada 5): as filas moram ao lado do banco do projeto
# ativo (GMA_DB); para o laboratório, são as pastas da raiz de sempre.
import sys
sys.path.insert(0, RAIZ_GMA)
import painel_config

# Pasta com os JSONs de material detectado pelo Porteiro (isolada por projeto)
PASTA_FILA_MATERIAL = painel_config.pasta_ao_lado_do_banco("fila_material")

# Pasta com os JSONs de formulários recebidos pelo Flask (isolada por projeto)
PASTA_FILA_FORMS = painel_config.pasta_ao_lado_do_banco("fila_forms")

# Arquivo de log específico do Matcher
ARQUIVO_LOG = os.path.join(RAIZ_GMA, "logs", "matcher.log")

# Pontuação mínima para confirmar um match
PONTUACAO_MINIMA_MATCH = 3

# Margem mínima de vantagem para casar automaticamente.
# Se o segundo melhor candidato estiver a menos de MARGEM_SEGURANCA pontos
# do melhor, consideramos AMBÍGUO e NÃO casamos (esperamos confirmação humana).
# Exemplo: score=6 e MARGEM=1 → qualquer concorrente com score > 5 (ou seja, ≥ 6)
# torna o match ambíguo. Um concorrente com score exatamente 5 ainda é seguro (5 não é > 5).
MARGEM_SEGURANCA = 1

# ── CONFIGURAÇÃO DO LOGGER ────────────────────────────────────────────────────

def configurar_logger():
    """
    Configura o sistema de log do Matcher.
    Grava em logs/matcher.log E mostra no terminal.
    """
    logger = logging.getLogger("matcher")
    logger.setLevel(logging.DEBUG)

    # Evita duplicar handlers se o logger já foi configurado antes
    if logger.handlers:
        return logger

    # Formato padrão GMA: timestamp | mensagem
    formato = logging.Formatter(
        fmt="%(asctime)s | %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S"
    )

    # Garante que a pasta de logs existe antes de abrir o arquivo
    os.makedirs(os.path.dirname(ARQUIVO_LOG), exist_ok=True)

    # Handler de arquivo (modo append — nunca sobrescreve)
    handler_arquivo = logging.FileHandler(ARQUIVO_LOG, encoding="utf-8")
    handler_arquivo.setFormatter(formato)
    logger.addHandler(handler_arquivo)

    # Handler de terminal para acompanhamento em tempo real
    handler_terminal = logging.StreamHandler()
    handler_terminal.setFormatter(formato)
    logger.addHandler(handler_terminal)

    return logger


# ── FUNÇÕES DE LEITURA DAS FILAS ─────────────────────────────────────────────

def ler_jsons_da_pasta(caminho_pasta, status_filtro):
    """
    Lê todos os arquivos .json de uma pasta e retorna os que têm o status indicado.

    Parâmetros:
      caminho_pasta — caminho da pasta a ler (fila_material/ ou fila_forms/)
      status_filtro — string de status que queremos filtrar (ex: "aguardando_match")

    Retorna uma lista de tuplas: (nome_do_arquivo, dicionario_de_dados)

    Erros em arquivos individuais são logados e ignorados — um JSON corrompido
    não para o processo inteiro.
    """
    logger = logging.getLogger("matcher")
    resultado = []

    # Se a pasta não existe, retorna lista vazia sem erro
    if not os.path.isdir(caminho_pasta):
        return resultado

    try:
        arquivos = os.listdir(caminho_pasta)
    except OSError as erro:
        logger.error(f"ERRO AO LER PASTA | {caminho_pasta} | {erro}")
        return resultado

    for nome_arquivo in sorted(arquivos):
        # Processa apenas arquivos .json
        if not nome_arquivo.endswith(".json"):
            continue

        caminho_completo = os.path.join(caminho_pasta, nome_arquivo)

        try:
            with open(caminho_completo, "r", encoding="utf-8") as f:
                dados = json.load(f)
        except (json.JSONDecodeError, OSError) as erro:
            logger.error(f"ERRO AO LER JSON | {nome_arquivo} | {erro}")
            continue  # Ignora este arquivo e passa para o próximo

        # Filtra pelo status desejado
        if dados.get("status") == status_filtro:
            resultado.append((nome_arquivo, dados))

    return resultado


def atualizar_json(caminho_pasta, nome_arquivo, atualizacoes):
    """
    Atualiza campos específicos de um arquivo JSON na pasta indicada.

    Parâmetros:
      caminho_pasta — pasta onde está o arquivo
      nome_arquivo  — nome do arquivo .json
      atualizacoes  — dicionário com os campos a sobrescrever (ex: {"status": "matched"})

    Lê o arquivo, aplica as atualizações e reescreve. Erros são logados.
    Retorna True se teve sucesso, False se deu erro.
    """
    logger = logging.getLogger("matcher")
    caminho_completo = os.path.join(caminho_pasta, nome_arquivo)

    try:
        with open(caminho_completo, "r", encoding="utf-8") as f:
            dados = json.load(f)
    except (json.JSONDecodeError, OSError) as erro:
        logger.error(f"ERRO AO LER PARA ATUALIZAR | {nome_arquivo} | {erro}")
        return False

    # Aplica cada campo da atualização
    dados.update(atualizacoes)

    try:
        with open(caminho_completo, "w", encoding="utf-8") as f:
            json.dump(dados, f, ensure_ascii=False, indent=2)
    except OSError as erro:
        logger.error(f"ERRO AO SALVAR ATUALIZAÇÃO | {nome_arquivo} | {erro}")
        return False

    return True


# ── LÓGICA DE PONTUAÇÃO ───────────────────────────────────────────────────────

def _camera_do_cadastro(nome):
    """
    Busca a câmera cadastrada para um profissional (pelo nome da ficha) na tabela
    `profissionais`. Fonte do critério +3 na Nova Ficha v2: a câmera saiu da ficha
    e passou a viver no cadastro.

    Best-effort e offline-first: se o banco não estiver disponível ou o nome não
    estiver cadastrado, devolve None (o critério +3 cai de volta para a câmera da
    ficha, e na falta dela simplesmente não pontua). Nunca derruba o match.
    """
    if not nome or not str(nome).strip():
        return None
    try:
        import banco_dados as _bd
        _conn = _bd.inicializar_banco()
        try:
            return _bd.camera_do_profissional(_conn, nome)
        finally:
            _conn.close()
    except Exception:
        return None


def calcular_pontuacao(dados_form, dados_material):
    """
    Calcula a pontuação de compatibilidade entre um formulário e um material.

    Quanto maior a pontuação, maior a chance de que o formulário e o material
    se refiram ao mesmo cartão.

    Regras de pontuação:
      +3 → marca_camera do material bate com o campo camera do formulário
           (comparação sem diferenciar maiúsculas)
      +2 → data_gravacao do formulário é o mesmo dia do timestamp do material
      +2 → material vem de pasta_entrada e o nome da pasta contém o nome do profissional
      +1 → tipo_material do formulário (VIDEO/FOTO/AUDIO) bate com o tipo predominante
           detectado no cartão (campo contagem_tipo do JSON do material)

    Retorna uma tupla: (pontuacao_total, lista_de_detalhes)
    """
    pontos = 0
    detalhes = []  # para debug/log

    # ── Critério 1: câmera bate (+3) ──────────────────────────────────────────
    # Na Nova Ficha v2 a câmera NÃO vem mais da ficha: mora no cadastro do
    # profissional. O Matcher busca a câmera do cadastro pelo nome da ficha; se o
    # nome não está cadastrado (ou está sem câmera), cai de volta para a câmera da
    # ficha — preserva o canal Tally de reserva, que ainda pode declarar câmera.
    marca_material = (dados_material.get("marca_camera") or "").strip().lower()
    camera_cadastro = _camera_do_cadastro(dados_form.get("nome"))
    camera_form = (camera_cadastro or dados_form.get("camera") or "").strip().lower()

    # Comparação flexível: verifica se a câmera do formulário aparece dentro
    # do nome da câmera do material (ou vice-versa). Isso resolve casos como
    # "canon" ⊂ "genérica/canon/nikon/fuji" que seriam perdidos com == exato.
    if marca_material and camera_form and (
        camera_form in marca_material or marca_material in camera_form
    ):
        pontos += 3
        detalhes.append("câmera:+3")

    # ── Critério 2: mesmo dia (+2) ────────────────────────────────────────────
    data_gravacao_form = dados_form.get("data_gravacao", "")
    timestamp_material = dados_material.get("timestamp", "")

    if data_gravacao_form and timestamp_material:
        try:
            # O formulário informa a data como string "AAAA-MM-DD"
            data_form = datetime.strptime(data_gravacao_form, "%Y-%m-%d").date()
            # O timestamp do material é "AAAA-MM-DDTHH:MM:SS"
            data_material = datetime.strptime(timestamp_material, "%Y-%m-%dT%H:%M:%S").date()
            if data_form == data_material:
                pontos += 2
                detalhes.append("data:+2")
        except ValueError:
            # Formato de data inesperado — ignora este critério silenciosamente
            pass

    # ── Critério 3: nome da pasta de entrada contém o nome do profissional (+2) ──
    origem_material = dados_material.get("origem", "")
    nome_material = (dados_material.get("nome") or "").lower()
    nome_form = (dados_form.get("nome") or "").strip().lower()

    if (
        origem_material == "pasta_entrada"
        and nome_form
        and nome_form in nome_material
    ):
        pontos += 2
        detalhes.append("nome_no_material:+2")

    # ── Critério 4: tipo de material bate (+1) ────────────────────────────────
    # O formulário tem o campo tipo_material (ex: "VIDEO", "FOTO", "AUDIO").
    # O material detectado pelo Leitor tem o campo contagem_tipo, que é um dicionário
    # com a quantidade de arquivos por tipo (ex: {"VIDEO": 45, "FOTO": 3, "OUTRO": 2}).
    # O tipo predominante do material é o que tem a maior contagem.
    # Se não houver contagem_tipo no JSON (cartão ainda não analisado), pula sem erro.
    tipo_form = (dados_form.get("tipo_material") or "").strip().upper()
    contagem_tipo = dados_material.get("contagem_tipo")  # pode ser None ou {}

    # Nova Ficha v2 (Fatia 5): a ficha pode marcar MAIS DE UM tipo (ex.: "FOTO+VIDEO").
    # Quebramos o texto nos tipos marcados (FOTO/AUDIO/VIDEO) e pontuamos se o tipo
    # predominante do cartão estiver ENTRE eles. Para ficha de tipo único, o
    # conjunto tem 1 elemento e o comportamento é idêntico ao de antes.
    tipos_form = {t for t in ("FOTO", "AUDIO", "VIDEO") if t in tipo_form}

    if tipos_form and contagem_tipo and isinstance(contagem_tipo, dict):
        # Identifica o tipo com maior contagem de arquivos no cartão
        tipo_predominante = max(contagem_tipo, key=contagem_tipo.get).upper()
        if tipo_predominante in tipos_form:
            pontos += 1
            detalhes.append("tipo:+1")

    return pontos, detalhes


# ── FUNÇÃO PRINCIPAL: TENTAR MATCH ───────────────────────────────────────────

def tentar_match():
    """
    Função principal do Matcher.

    Lê todos os formulários aguardando material e todos os materiais aguardando
    formulário. Para cada par possível, calcula a pontuação de compatibilidade.

    Trava de segurança anti-ambiguidade:
      Um match só é confirmado automaticamente se o par vencedor for ESTRITAMENTE
      melhor que qualquer concorrente por pelo menos MARGEM_SEGURANCA ponto,
      verificando dos dois lados:
        - Nenhum outro material pode estar a menos de MARGEM_SEGURANCA do melhor
          par para este form (o form não pode estar "dividido" entre cartões).
        - Nenhum outro form pode estar a menos de MARGEM_SEGURANCA do melhor
          par para este material (o cartão não pode estar "disputado" entre fichas).

    Pares que atingem a pontuação mínima mas não satisfazem a trava são marcados
    como "aguardando_confirmacao" para o operador resolver no painel.

    Retorna uma lista de dicionários com os dados unidos (material + form),
    prontos para serem passados ao próximo módulo (Leitor de Mídia).
    """
    logger = configurar_logger()

    # ── Carrega as filas ───────────────────────────────────────────────────────
    # Importante: só lemos status "aguardando_material" e "aguardando_match".
    # Itens com status "aguardando_confirmacao" naturalmente ficam de fora
    # (filtro por status exclui eles), então nunca são reprocessados aqui.
    forms_aguardando = ler_jsons_da_pasta(PASTA_FILA_FORMS, "aguardando_material")
    materiais_aguardando = ler_jsons_da_pasta(PASTA_FILA_MATERIAL, "aguardando_match")

    if not forms_aguardando:
        logger.info("MATCHER | Nenhum formulário aguardando material")
    if not materiais_aguardando:
        logger.info("MATCHER | Nenhum material aguardando formulário")

    if not forms_aguardando or not materiais_aguardando:
        return []  # Nada para processar por enquanto

    logger.info(
        f"MATCHER | Tentando match: {len(forms_aguardando)} formulário(s) "
        f"x {len(materiais_aguardando)} material(is)"
    )

    # ── Calcula pontuações de todos os pares possíveis ────────────────────────
    # Monta uma tabela de scores: scores[(nome_form, nome_material)] = (pontuacao, detalhes)
    # Também mantemos listas auxiliares para verificar concorrentes facilmente.
    scores = {}  # {(nome_form, nome_material): (pontuacao, detalhes)}

    for nome_form, dados_form in forms_aguardando:
        for nome_material, dados_material in materiais_aguardando:
            pontuacao, detalhes = calcular_pontuacao(dados_form, dados_material)
            if pontuacao >= PONTUACAO_MINIMA_MATCH:
                scores[(nome_form, nome_material)] = (pontuacao, detalhes)

    if not scores:
        logger.info("MATCHER | Nenhum par atingiu pontuação mínima de match")
        return []

    # ── Classifica os pares em SEGUROS (casar automático) e AMBÍGUOS (segurar) ──
    #
    # Um par (form F, material M) com score S é SEGURO se:
    #   1. S >= PONTUACAO_MINIMA_MATCH (já garantido por estar em `scores`)
    #   2. Nenhum outro material M' tem score(F, M') > S - MARGEM_SEGURANCA
    #      → o form não está "dividido" entre cartões
    #   3. Nenhum outro form F' tem score(F', M) > S - MARGEM_SEGURANCA
    #      → o cartão não está "disputado" entre fichas
    #
    # Limiar: um concorrente é problemático se seu score é MAIOR QUE S - MARGEM_SEGURANCA.
    # Com S=6 e MARGEM=1, limiar = 5. Concorrente com score=5 NÃO é problemático (5 não é > 5).
    # Concorrente com score=6 SIM é problemático (6 > 5). Isso garante o caso de desempate.

    pares_seguros = []   # lista de (nome_form, nome_material, pontuacao, detalhes)
    pares_ambiguos = []  # lista de (nome_form, nome_material, pontuacao, detalhes)

    for (nome_form, nome_material), (score, detalhes) in scores.items():
        limiar_concorrente = score - MARGEM_SEGURANCA

        # Verifica se algum outro material concorre com este form
        form_dividido = any(
            score_outro > limiar_concorrente
            for (f, m), (score_outro, _) in scores.items()
            if f == nome_form and m != nome_material
        )

        # Verifica se algum outro form concorre com este material
        material_disputado = any(
            score_outro > limiar_concorrente
            for (f, m), (score_outro, _) in scores.items()
            if m == nome_material and f != nome_form
        )

        if form_dividido or material_disputado:
            pares_ambiguos.append((nome_form, nome_material, score, detalhes))
        else:
            pares_seguros.append((nome_form, nome_material, score, detalhes))

    # Ordena seguros por pontuação decrescente (melhores primeiro)
    pares_seguros.sort(key=lambda x: x[2], reverse=True)

    # ── FASE 1: Confirma os matches seguros ───────────────────────────────────
    # Um form ou material já confirmado não pode entrar em outro par nesta rodada.
    forms_ja_matched = set()
    materiais_ja_matched = set()
    matches_confirmados = []

    # Mapa de dados para acesso rápido
    mapa_forms = {nome: dados for nome, dados in forms_aguardando}
    mapa_materiais = {nome: dados for nome, dados in materiais_aguardando}

    for nome_form, nome_material, pontuacao, detalhes in pares_seguros:
        # Pula se algum dos dois já teve match nesta rodada
        if nome_form in forms_ja_matched or nome_material in materiais_ja_matched:
            continue

        dados_form = mapa_forms[nome_form]
        dados_material = mapa_materiais[nome_material]

        # ── Confirma o match ──────────────────────────────────────────────────
        logger.info(
            f"MATCH CONFIRMADO | Pontuação: {pontuacao} | "
            f"Critérios: {', '.join(detalhes)} | "
            f"Form: {nome_form} | Material: {nome_material}"
        )

        # Atualiza o JSON do material: marca como matched e registra qual form
        atualizar_json(PASTA_FILA_MATERIAL, nome_material, {
            "status": "matched",
            "form_match": nome_form,
        })

        # Atualiza o JSON do formulário: marca como matched e registra qual material
        atualizar_json(PASTA_FILA_FORMS, nome_form, {
            "status": "matched",
            "material_match": nome_material,
        })

        # ── Integração Camada 3: grava o match no banco SQLite ────────────────
        # Este bloco é ADITIVO — se o banco falhar, o fluxo JSON continua normalmente.
        # Os IDs do banco foram gravados nos JSONs pelo Leitor (db_cartao_id) e
        # pelo Flask (db_formulario_id) em etapas anteriores do fluxo.
        try:
            import banco_dados as _bd
            # Relê os JSONs atualizados para pegar os IDs do banco
            _dados_material_relido = {}
            _dados_form_relido = {}
            _caminho_material = os.path.join(PASTA_FILA_MATERIAL, nome_material)
            _caminho_form = os.path.join(PASTA_FILA_FORMS, nome_form)
            try:
                with open(_caminho_material, "r", encoding="utf-8") as _f:
                    _dados_material_relido = json.load(_f)
                with open(_caminho_form, "r", encoding="utf-8") as _f:
                    _dados_form_relido = json.load(_f)
            except (OSError, json.JSONDecodeError):
                pass  # se não conseguir reler, usa os dicts originais
            _db_cartao_id = _dados_material_relido.get("db_cartao_id") or dados_material.get("db_cartao_id")
            _db_formulario_id = _dados_form_relido.get("db_formulario_id") or dados_form.get("db_formulario_id")
            if _db_cartao_id and _db_formulario_id:
                _conn_matcher = _bd.inicializar_banco()
                _bd.gravar_match(
                    _conn_matcher,
                    cartao_id=_db_cartao_id,
                    formulario_id=_db_formulario_id,
                    score=pontuacao,
                    criterios_lista=detalhes,
                )
                logger.info(
                    f"BANCO | Match gravado | cartao={_db_cartao_id} form={_db_formulario_id}"
                )

                # ── Fase 1 do perfil: alimenta o perfil do profissional (aditivo) ──
                # Aprende a assinatura deste cartão sob o nome do profissional
                # do formulário. NÃO altera o resultado do match — só registra
                # para uso futuro na Fase 2 (desempatar matches ambíguos).
                #
                # Passo 2 IMPLEMENTADO: a confirmação manual de empates também
                # chama atualizar_perfil() — ver função confirmar_par_manual()
                # neste mesmo arquivo. Matches automáticos e manuais alimentam
                # o aprendizado pelo mesmo mecanismo.
                try:
                    _assinatura = (
                        _dados_material_relido.get("assinatura")
                        or dados_material.get("assinatura")
                    )
                    _nome_prof = (
                        _dados_form_relido.get("nome")
                        or dados_form.get("nome")
                    )
                    if _assinatura and _nome_prof:
                        _bd.atualizar_perfil(_conn_matcher, _nome_prof, _assinatura)
                        logger.info(f"PERFIL | Assinatura aprendida para {_nome_prof}")
                    else:
                        logger.info(
                            f"PERFIL | Sem assinatura ou nome para aprender "
                            f"(assinatura={bool(_assinatura)}, nome={_nome_prof})"
                        )
                except Exception as _err_perfil:
                    logger.error(
                        f"PERFIL | Falha ao atualizar perfil (fluxo continua) | {_err_perfil}"
                    )

                _conn_matcher.close()
            else:
                logger.warning(
                    f"BANCO | IDs ausentes nos JSONs — match não gravado no banco "
                    f"(fluxo continua) | cartao_id={_db_cartao_id} form_id={_db_formulario_id}"
                )
        except Exception as _err_bd:
            logger.error(f"BANCO | Falha ao gravar match (fluxo continua) | {_err_bd}")

        # Marca os dois como usados para não fazer match de novo nesta rodada
        forms_ja_matched.add(nome_form)
        materiais_ja_matched.add(nome_material)

        # Monta o dicionário unificado para o próximo módulo
        dados_unidos = {
            # Metadados do match
            "match_timestamp":       datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "match_pontuacao":       pontuacao,
            "match_criterios":       detalhes,
            "nome_arquivo_form":     nome_form,
            "nome_arquivo_material": nome_material,
            # Dados do material (Porteiro)
            "material_caminho":      dados_material.get("caminho"),
            "material_nome":         dados_material.get("nome"),
            "material_origem":       dados_material.get("origem"),
            "material_marca":        dados_material.get("marca_camera"),
            "material_criterio":     dados_material.get("criterio_deteccao"),
            "material_timestamp":    dados_material.get("timestamp"),
            # Dados do formulário (check-in)
            "form_nome":             dados_form.get("nome"),
            "form_camera":           dados_form.get("camera"),
            "form_tipo_material":    dados_form.get("tipo_material"),
            "form_data_gravacao":    dados_form.get("data_gravacao"),
            "form_operador":         dados_form.get("operador"),
        }

        matches_confirmados.append(dados_unidos)

    # ── FASE 2: Marca os pares ambíguos que não foram resolvidos na Fase 1 ────
    # Um par ambíguo só vira "aguardando_confirmacao" se AMBOS ainda não foram
    # confirmados na Fase 1 (não queremos marcar como ambíguo quem já foi casado).
    forms_ambiguos_marcados = set()     # controla quem já recebeu o status
    materiais_ambiguos_marcados = set()
    # Sentinela SEPARADA para a persistência dos candidatos (Tarefa A do Passo 2).
    # NÃO reutilizar 'materiais_ambiguos_marcados': ela já é preenchida ao marcar o
    # JSON (logo acima), o que zeraria a condição e impediria registrar_candidatos().
    materiais_candidatos_persistidos = set()

    for nome_form, nome_material, score, detalhes in pares_ambiguos:
        # Se algum dos dois já foi casado na Fase 1, ignora
        if nome_form in forms_ja_matched or nome_material in materiais_ja_matched:
            continue

        dados_form = mapa_forms[nome_form]
        dados_material = mapa_materiais[nome_material]

        logger.warning(
            f"MATCH AMBÍGUO | Pontuação: {score} | "
            f"Critérios: {', '.join(detalhes)} | "
            f"Form: {nome_form} | Material: {nome_material} | "
            f"Aguardando confirmação humana"
        )

        # Monta a estrutura de candidatos para exibição no painel
        # (lista dos pares possíveis para este item)
        candidato_info = {
            "nome_arquivo_form": nome_form,
            "nome_arquivo_material": nome_material,
            "nome_profissional": dados_form.get("nome"),
            "marca": dados_material.get("marca_camera"),
            "score": score,
            "criterios": detalhes,
        }

        # ── Atualiza o JSON do material (se ainda não foi marcado como ambíguo) ──
        if nome_material not in materiais_ambiguos_marcados:
            # Coleta TODOS os forms que competem por este material
            candidatos_para_este_material = [
                {
                    "nome_arquivo_form": f,
                    "nome_profissional": mapa_forms[f].get("nome"),
                    "marca": dados_material.get("marca_camera"),
                    "score": s,
                    "criterios": d,
                }
                for (f, m), (s, d) in scores.items()
                if m == nome_material
            ]
            atualizar_json(PASTA_FILA_MATERIAL, nome_material, {
                "status": "aguardando_confirmacao",
                "candidatos_match": candidatos_para_este_material,
            })
            materiais_ambiguos_marcados.add(nome_material)

        # ── Atualiza o JSON do form (se ainda não foi marcado como ambíguo) ──
        if nome_form not in forms_ambiguos_marcados:
            # Coleta TODOS os materiais que competem por este form
            candidatos_para_este_form = [
                {
                    "nome_arquivo_material": m,
                    "nome_profissional": dados_form.get("nome"),
                    "marca": mapa_materiais[m].get("marca_camera"),
                    "score": s,
                    "criterios": d,
                }
                for (f, m), (s, d) in scores.items()
                if f == nome_form
            ]
            atualizar_json(PASTA_FILA_FORMS, nome_form, {
                "status": "aguardando_confirmacao",
                "candidatos_match": candidatos_para_este_form,
            })
            forms_ambiguos_marcados.add(nome_form)

        # ── Integração Camada 3: registra evento de match ambíguo e persiste candidatos ──
        # Este bloco é ADITIVO — se o banco falhar, o fluxo JSON continua.
        # O caso que interessa para a resolução do painel é:
        #   1 cartão com N fichas candidatas (material_disputado).
        # Nesse caso, persistimos os candidatos na tabela match_candidatos para que
        # o Flask possa exibi-los no painel e o operador resolva com 1 clique.
        try:
            import banco_dados as _bd
            _db_cartao_id = dados_material.get("db_cartao_id")
            _db_formulario_id = dados_form.get("db_formulario_id")
            _conn_ambiguo = _bd.inicializar_banco()

            # Registra evento de auditoria (sempre, mesmo sem IDs do banco)
            _bd.registrar_evento(
                _conn_ambiguo,
                tipo="match_ambiguo",
                descricao=(
                    f"Match ambíguo — aguardando confirmação | "
                    f"Form: {nome_form} | Material: {nome_material} | Score: {score}"
                ),
                cartao_id=_db_cartao_id,
                formulario_id=_db_formulario_id,
                dados={
                    "score": score,
                    "criterios": detalhes,
                    "nome_form": nome_form,
                    "nome_material": nome_material,
                }
            )

            # ── Persistência dos candidatos (Tarefa A do Passo 2) ─────────────
            # Só persiste quando este material acaba de ser marcado como ambíguo
            # (primeira vez que chegamos nele neste loop). Isso evita chamar
            # registrar_candidatos() repetidamente para o mesmo cartão.
            # A tabela match_candidatos usa INSERT OR IGNORE, então chamar mais
            # de uma vez é inofensivo, mas desnecessário.
            if nome_material not in materiais_candidatos_persistidos:
                materiais_candidatos_persistidos.add(nome_material)
                # Só persiste se temos o ID do cartão no banco
                if _db_cartao_id:
                    # Monta a lista de candidatos para este cartão:
                    # cada candidato é uma ficha (formulário) que compete pelo mesmo material.
                    # Precisamos do db_formulario_id de cada ficha — ele vem do JSON do form.
                    candidatos_para_banco = []
                    for (f_nome, m_nome), (s, d) in scores.items():
                        if m_nome != nome_material:
                            continue  # só candidatos deste cartão

                        # Pega o ID do banco do formulário candidato
                        _dados_form_candidato = mapa_forms.get(f_nome, {})
                        _db_form_id_candidato = _dados_form_candidato.get("db_formulario_id")

                        if not _db_form_id_candidato:
                            # Sem ID no banco, este candidato não pode ser gravado na tabela
                            logger.warning(
                                f"BANCO | Candidato sem db_formulario_id — não gravado | "
                                f"Form: {f_nome} | Material: {nome_material}"
                            )
                            continue

                        candidatos_para_banco.append({
                            "formulario_id": _db_form_id_candidato,
                            "nome":          _dados_form_candidato.get("nome", ""),
                            "camera_ficha":  _dados_form_candidato.get("camera"),
                            "score":         s,
                            "criterios":     d,
                        })

                    if candidatos_para_banco:
                        _inseridos = _bd.registrar_candidatos(
                            _conn_ambiguo, _db_cartao_id, candidatos_para_banco
                        )
                        logger.info(
                            f"BANCO | Candidatos persistidos | Cartão: {_db_cartao_id} "
                            f"| Inseridos: {_inseridos} | Total: {len(candidatos_para_banco)}"
                        )
                    else:
                        logger.warning(
                            f"BANCO | Nenhum candidato com ID válido para persistir "
                            f"(material: {nome_material})"
                        )
                else:
                    logger.warning(
                        f"BANCO | db_cartao_id ausente — candidatos não persistidos "
                        f"(fluxo JSON continua) | Material: {nome_material}"
                    )

            _conn_ambiguo.close()
        except Exception as _err_bd:
            logger.error(
                f"BANCO | Falha ao registrar evento match_ambiguo (fluxo continua) | {_err_bd}"
            )

    if forms_ambiguos_marcados or materiais_ambiguos_marcados:
        logger.warning(
            f"MATCHER | {len(materiais_ambiguos_marcados)} material(is) e "
            f"{len(forms_ambiguos_marcados)} formulário(s) marcados como aguardando_confirmacao"
        )

    logger.info(
        f"MATCHER | {len(matches_confirmados)} match(es) confirmado(s) nesta rodada"
    )

    return matches_confirmados


# ── CONFIRMAÇÃO MANUAL DE EMPATE (PASSO 2 DO MATCHER) ────────────────────────

def confirmar_par_manual(cartao_id, nome_escolhido):
    """
    Resolve um empate de match manualmente, confirmando o par cartão ↔ profissional.

    Esta função é chamada pelo Flask (flask_gma.py) quando o operador clica em
    "Iniciar transferência" na tela de confirmação do empate.

    Ela espelha o caminho automático de tentar_match(): basta marcar o JSON do
    material como status="matched" para que a Camada 2 (Transferência) detecte
    e inicie a cópia.

    Parâmetros:
      cartao_id      — ID do cartão no banco (int) — o db_cartao_id do JSON do material
      nome_escolhido — nome do profissional escolhido pelo operador (ex: "JOAO")
                       deve corresponder exatamente ao campo 'nome' do candidato

    Retorna um dicionário:
      Caso de sucesso:
        {
          "ok":            True,
          "nome":          "JOAO",                    # profissional confirmado
          "formulario_id": 3,                          # ID da ficha escolhida no banco
          "material":      "material_20260614.json",   # nome do arquivo JSON do cartão
          "descartados":   [5, 7]                      # IDs de fichas liberadas de volta
        }

      Caso de "já resolvido" (empate resolvido por outro processo antes deste clique):
        {"ok": False, "motivo": "empate_ja_resolvido"}

      Caso de erro (banco falhou, arquivo não encontrado, etc.):
        {"ok": False, "motivo": "<descrição do erro>"}

    Segurança:
      A transferência SÓ é disparada (material marcado "matched") se a confirmação
      no banco der certo (bd.confirmar_match retornar um resultado não-None).
      Se o banco falhar ou retornar None, o material NÃO é marcado e nenhuma
      cópia é iniciada.
    """
    logger = configurar_logger()

    logger.info(
        f"CONFIRMAÇÃO MANUAL | Iniciando | Cartão: {cartao_id} | Escolhido: {nome_escolhido}"
    )

    # ── Passo 1: abre conexão com o banco e confirma o empate atomicamente ────
    try:
        import banco_dados as bd
        conn = bd.inicializar_banco()
    except Exception as _err_conn:
        _msg = f"falha_ao_abrir_banco: {_err_conn}"
        logger.error(f"CONFIRMAÇÃO MANUAL | {_msg}")
        return {"ok": False, "motivo": _msg}

    try:
        resultado = bd.confirmar_match(conn, cartao_id, nome_escolhido)
    except Exception as _err_confirmar:
        _msg = f"falha_ao_confirmar_match: {_err_confirmar}"
        logger.error(f"CONFIRMAÇÃO MANUAL | {_msg}")
        conn.close()
        return {"ok": False, "motivo": _msg}

    # Se resultado for None, o empate já foi resolvido (ou o nome não existia)
    if resultado is None:
        logger.info(
            f"CONFIRMAÇÃO MANUAL | Empate já resolvido ou candidato não encontrado "
            f"| Cartão: {cartao_id} | Nome: {nome_escolhido}"
        )
        conn.close()
        return {"ok": False, "motivo": "empate_ja_resolvido"}

    # A partir daqui, o banco já foi atualizado com sucesso.
    # Agora sincronizamos os JSONs das filas para que a Camada 2 e o painel
    # vejam o mesmo estado que o banco.

    formulario_id_escolhido  = resultado["formulario_id"]
    ids_descartados          = resultado["descartados"]

    # ── Passo 2: localiza o JSON do material na fila_material/ ────────────────
    # Percorre todos os JSONs da pasta procurando o que tem db_cartao_id == cartao_id.
    nome_arquivo_material = None
    dados_material        = None

    if os.path.isdir(PASTA_FILA_MATERIAL):
        for _nome in sorted(os.listdir(PASTA_FILA_MATERIAL)):
            if not _nome.endswith(".json"):
                continue
            _caminho = os.path.join(PASTA_FILA_MATERIAL, _nome)
            try:
                with open(_caminho, "r", encoding="utf-8") as _f:
                    _dados = json.load(_f)
            except (OSError, json.JSONDecodeError):
                continue
            if _dados.get("db_cartao_id") == cartao_id:
                nome_arquivo_material = _nome
                dados_material        = _dados
                break

    if not nome_arquivo_material:
        _msg = (
            f"json_material_nao_encontrado: "
            f"nenhum arquivo em fila_material/ com db_cartao_id={cartao_id}"
        )
        logger.error(f"CONFIRMAÇÃO MANUAL | {_msg}")
        conn.close()
        return {"ok": False, "motivo": _msg}

    # ── Passo 3: localiza o JSON da ficha escolhida na fila_forms/ ───────────
    # Percorre todos os JSONs da pasta procurando o que tem
    # db_formulario_id == formulario_id_escolhido.
    nome_arquivo_form_escolhido = None

    if os.path.isdir(PASTA_FILA_FORMS):
        for _nome in sorted(os.listdir(PASTA_FILA_FORMS)):
            if not _nome.endswith(".json"):
                continue
            _caminho = os.path.join(PASTA_FILA_FORMS, _nome)
            try:
                with open(_caminho, "r", encoding="utf-8") as _f:
                    _dados = json.load(_f)
            except (OSError, json.JSONDecodeError):
                continue
            if _dados.get("db_formulario_id") == formulario_id_escolhido:
                nome_arquivo_form_escolhido = _nome
                break

    # ── Passo 4: localiza os JSONs das fichas descartadas ────────────────────
    # Cada ficha descartada precisa ter seu JSON atualizado de volta para
    # "aguardando_match", para ficar disponível para o próximo cartão.
    mapa_forms_descartados = {}  # {db_formulario_id: nome_do_arquivo_json}

    if ids_descartados and os.path.isdir(PASTA_FILA_FORMS):
        for _nome in sorted(os.listdir(PASTA_FILA_FORMS)):
            if not _nome.endswith(".json"):
                continue
            _caminho = os.path.join(PASTA_FILA_FORMS, _nome)
            try:
                with open(_caminho, "r", encoding="utf-8") as _f:
                    _dados = json.load(_f)
            except (OSError, json.JSONDecodeError):
                continue
            _fid = _dados.get("db_formulario_id")
            if _fid in ids_descartados:
                mapa_forms_descartados[_fid] = _nome
            # Para quando já encontrou todos
            if len(mapa_forms_descartados) == len(ids_descartados):
                break

    # ── Passo 5: atualiza o JSON do material → status="matched" ──────────────
    # Este é o gatilho que faz a Camada 2 (Transferência) iniciar a cópia.
    # Só chegamos aqui porque bd.confirmar_match() deu certo — segurança garantida.
    sucesso_material = atualizar_json(PASTA_FILA_MATERIAL, nome_arquivo_material, {
        "status":     "matched",
        "form_match": nome_arquivo_form_escolhido or nome_escolhido,
    })

    if not sucesso_material:
        logger.error(
            f"CONFIRMAÇÃO MANUAL | Falha ao atualizar JSON do material "
            f"| Arquivo: {nome_arquivo_material}"
        )
        # Não revertemos o banco — o estado do banco é correto; o JSON é quem está para trás.
        # O operador pode perceber pelo painel (status no banco está matched,
        # JSON ainda não). Registramos como aviso e retornamos com o que temos.

    # ── Passo 6: atualiza o JSON da ficha escolhida → status="matched" ───────
    if nome_arquivo_form_escolhido:
        atualizar_json(PASTA_FILA_FORMS, nome_arquivo_form_escolhido, {
            "status":         "matched",
            "material_match": nome_arquivo_material,
        })
    else:
        logger.warning(
            f"CONFIRMAÇÃO MANUAL | JSON da ficha escolhida não encontrado em fila_forms/ "
            f"(db_formulario_id={formulario_id_escolhido}) — banco está correto, JSON não atualizado"
        )

    # ── Passo 7: devolve as fichas descartadas à fila ─────────────────────────
    # Remove o material_match e volta status para "aguardando_match" para que
    # a ficha possa casar com o próximo cartão do mesmo profissional.
    for _fid, _nome_form in mapa_forms_descartados.items():
        atualizar_json(PASTA_FILA_FORMS, _nome_form, {
            "status":         "aguardando_match",
            "material_match": None,   # limpa o vínculo que ficou do empate
        })
        logger.info(f"CONFIRMAÇÃO MANUAL | Ficha devolvida à fila | {_nome_form}")

    # Avisa se alguma ficha descartada não foi encontrada no JSON
    _fids_nao_encontrados = set(ids_descartados) - set(mapa_forms_descartados.keys())
    for _fid in _fids_nao_encontrados:
        logger.warning(
            f"CONFIRMAÇÃO MANUAL | Ficha descartada não encontrada em fila_forms/ "
            f"(db_formulario_id={_fid}) — banco liberado, JSON pendente"
        )

    # ── Passo 8: atualiza o perfil do profissional ────────────────────────────
    # Fecha o TODO que existia nas linhas 452-455: a confirmação manual também
    # alimenta o aprendizado de perfil, exatamente como o caminho automático faz.
    try:
        _assinatura = dados_material.get("assinatura") if dados_material else None
        if _assinatura and nome_escolhido:
            bd.atualizar_perfil(conn, nome_escolhido, _assinatura)
            logger.info(
                f"PERFIL | Assinatura aprendida (confirmação manual) | {nome_escolhido}"
            )
        else:
            logger.info(
                f"PERFIL | Sem assinatura no JSON do material — perfil não atualizado "
                f"(assinatura={bool(_assinatura)}, nome={nome_escolhido})"
            )
    except Exception as _err_perfil:
        logger.error(
            f"PERFIL | Falha ao atualizar perfil na confirmação manual "
            f"(fluxo continua) | {_err_perfil}"
        )

    conn.close()

    logger.info(
        f"CONFIRMAÇÃO MANUAL | Concluída | Cartão: {cartao_id} "
        f"| Nome: {nome_escolhido} | Material JSON: {nome_arquivo_material} "
        f"| Form escolhido: {nome_arquivo_form_escolhido} "
        f"| Descartados: {ids_descartados}"
    )

    return {
        "ok":            True,
        "nome":          nome_escolhido,
        "formulario_id": formulario_id_escolhido,
        "material":      nome_arquivo_material,
        "descartados":   ids_descartados,
    }


# ── FUNÇÃO SECUNDÁRIA: VERIFICAR ÓRFÃOS ───────────────────────────────────────

def verificar_orfaos(minutos=10):
    """
    Verifica se há materiais ou formulários aguardando há mais de X minutos
    sem encontrar correspondência. Esses são os "órfãos" do sistema.

    Um órfão pode indicar:
      - Equipe entregou o cartão mas não preencheu o formulário (ou vice-versa).
      - Câmera no formulário diverge da câmera detectada (ex: "blackmagic" vs "Blackmagic").
      - Material chegou muito antes ou depois do formulário.

    Parâmetros:
      minutos — tempo limite em minutos. Padrão: 10 minutos.

    Retorna um dicionário com duas listas:
      "materiais_orfaos" — materiais sem formulário correspondente
      "forms_orfaos"     — formulários sem material correspondente
    """
    logger = configurar_logger()
    agora = datetime.now()
    limite = timedelta(minutes=minutos)

    materiais_orfaos = []
    forms_orfaos = []

    # ── Verifica materiais aguardando formulário ────────────────────────────────
    materiais_aguardando = ler_jsons_da_pasta(PASTA_FILA_MATERIAL, "aguardando_match")

    for nome_arquivo, dados in materiais_aguardando:
        timestamp_str = dados.get("timestamp", "")
        try:
            timestamp_item = datetime.strptime(timestamp_str, "%Y-%m-%dT%H:%M:%S")
            tempo_esperando = agora - timestamp_item
            if tempo_esperando > limite:
                logger.warning(
                    f"ALERTA: material órfão | "
                    f"Aguardando há {int(tempo_esperando.total_seconds() // 60)} min | "
                    f"Arquivo: {nome_arquivo} | "
                    f"Volume: {dados.get('nome')} | "
                    f"Câmera: {dados.get('marca_camera')}"
                )
                materiais_orfaos.append({"arquivo": nome_arquivo, "dados": dados})
        except ValueError:
            # Timestamp com formato inesperado — registra mas não trava
            logger.error(f"ORFÃO | Timestamp inválido em material: {nome_arquivo}")

    # ── Verifica formulários aguardando material ────────────────────────────────
    forms_aguardando = ler_jsons_da_pasta(PASTA_FILA_FORMS, "aguardando_material")

    for nome_arquivo, dados in forms_aguardando:
        timestamp_str = dados.get("timestamp", "")
        try:
            timestamp_item = datetime.strptime(timestamp_str, "%Y-%m-%dT%H:%M:%S")
            tempo_esperando = agora - timestamp_item
            if tempo_esperando > limite:
                logger.warning(
                    f"ALERTA: formulário sem material | "
                    f"Aguardando há {int(tempo_esperando.total_seconds() // 60)} min | "
                    f"Arquivo: {nome_arquivo} | "
                    f"Nome: {dados.get('nome')} | "
                    f"Câmera: {dados.get('camera')}"
                )
                forms_orfaos.append({"arquivo": nome_arquivo, "dados": dados})
        except ValueError:
            logger.error(f"ORFÃO | Timestamp inválido em formulário: {nome_arquivo}")

    return {
        "materiais_orfaos": materiais_orfaos,
        "forms_orfaos": forms_orfaos,
    }


# ── FUNÇÃO UTILITÁRIA: CRIAR FORM DE TESTE ────────────────────────────────────

def criar_form_teste(nome, camera, tipo, data):
    """
    Cria um arquivo JSON de exemplo em fila_forms/ para facilitar testes.
    Simula o que o Flask gravaria ao receber um formulário do Google Forms.

    Parâmetros:
      nome   — nome do profissional de captação (ex: "JOAO", "PAULO")
      camera — câmera declarada no formulário (ex: "Blackmagic")
      tipo   — tipo de material (ex: "VIDEO", "FOTO", "AUDIO")
      data   — data de gravação no formato "AAAA-MM-DD" (ex: "2026-06-05")

    Retorna o caminho do arquivo criado.
    """
    # Garante que a pasta existe
    os.makedirs(PASTA_FILA_FORMS, exist_ok=True)

    # Timestamp com microssegundos para unicidade
    agora = datetime.now()
    sufixo_tempo = agora.strftime("%Y%m%d_%H%M%S_%f")
    timestamp_iso = agora.strftime("%Y-%m-%dT%H:%M:%S")

    # Nome seguro para o arquivo
    nome_seguro = "".join(
        c if c.isalnum() or c in "-_" else "-"
        for c in nome
    )
    nome_arquivo = f"form_{sufixo_tempo}_{nome_seguro}.json"
    caminho_arquivo = os.path.join(PASTA_FILA_FORMS, nome_arquivo)

    dados_form = {
        "timestamp":      timestamp_iso,
        "nome":           nome,
        "camera":         camera,
        "tipo_material":  tipo,
        "data_gravacao":  data,
        "operador":       "teste_manual",
        "status":         "aguardando_material",  # estado inicial — esperando o Porteiro
        "material_match": None,                   # preenchido pelo Matcher quando houver match
    }

    with open(caminho_arquivo, "w", encoding="utf-8") as f:
        json.dump(dados_form, f, ensure_ascii=False, indent=2)

    print(f"Formulário de teste criado: {caminho_arquivo}")
    return caminho_arquivo


# ── FUNÇÕES DE SUPORTE ────────────────────────────────────────────────────────

def verificar_ambiente():
    """
    Garante que as pastas necessárias existem antes de rodar.
    """
    for pasta in [PASTA_FILA_MATERIAL, PASTA_FILA_FORMS, os.path.dirname(ARQUIVO_LOG)]:
        os.makedirs(pasta, exist_ok=True)


# ── PONTO DE ENTRADA (TESTE RÁPIDO) ───────────────────────────────────────────

if __name__ == "__main__":
    """
    Quando rodado diretamente, executa um ciclo de match e mostra o resultado.
    Use criar_form_teste() e o Porteiro para popular as filas antes de rodar isto.
    """
    verificar_ambiente()

    print()
    print("=" * 60)
    print("  GMA — Matcher (teste de ciclo completo)")
    print("=" * 60)
    print()

    # Exibe o estado atual das filas antes de tentar o match
    forms = ler_jsons_da_pasta(PASTA_FILA_FORMS, "aguardando_material")
    materiais = ler_jsons_da_pasta(PASTA_FILA_MATERIAL, "aguardando_match")
    print(f"  Formulários aguardando: {len(forms)}")
    print(f"  Materiais aguardando:   {len(materiais)}")
    print()

    # Tenta fazer match
    matches = tentar_match()

    print()
    if matches:
        print(f"  {len(matches)} match(es) confirmado(s):")
        for m in matches:
            print(f"    - {m['form_nome']} | {m['material_marca']} | "
                  f"pontos: {m['match_pontuacao']}")
    else:
        print("  Nenhum match confirmado nesta rodada.")

    # Verifica órfãos (tempo zero para fins de teste — vai listar tudo que sobrou)
    print()
    print("  Verificando órfãos (tempo limite: 0 minutos para teste)...")
    orfaos = verificar_orfaos(minutos=0)
    print(f"  Materiais órfãos:    {len(orfaos['materiais_orfaos'])}")
    print(f"  Formulários órfãos:  {len(orfaos['forms_orfaos'])}")

    print()
    print("=" * 60)
    print()
