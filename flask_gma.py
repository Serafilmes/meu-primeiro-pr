#!/usr/bin/env python3
"""
flask_gma.py
Camada 1 do GMA — Servidor Flask local para check-in de cartões.

Este arquivo é o ponto central da Camada 1. Ele faz duas coisas principais:
  1. Recebe os dados do Google Forms (via webhook do Google Apps Script)
     e salva na fila_forms/ para o Matcher processar.
  2. Serve um painel HTML simples para a segunda máquina acompanhar
     o estado do sistema em tempo real.

IMPORTANTE: este servidor roda APENAS em localhost (127.0.0.1:5050).
Nunca exposto à internet. Acesso da segunda máquina: pelo IP local da rede.

Uso:
    python3 flask_gma.py

Rotas disponíveis:
    GET  /                   → painel HTML com estado das filas
    POST /forms              → recebe formulário do Google Forms
    GET  /status             → retorna JSON com contagens das filas
    POST /porteiro/ativar    → cria o sentinela .gma_ativo
    POST /porteiro/desativar → remove o sentinela .gma_ativo
"""

import os
import json
import html
import logging
import random
import string
import hmac
import hashlib
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, redirect

# Gerador de QR Code (Python puro, offline). Opcional: se faltar, o painel do QR
# simplesmente não aparece — nada quebra.
try:
    import segno
    SEGNO_DISPONIVEL = True
except ImportError:
    SEGNO_DISPONIVEL = False

# ── CONFIGURAÇÃO DE CAMINHOS ──────────────────────────────────────────────────

# Raiz do projeto GMA
RAIZ_GMA = "/Users/serafa/GMA"

# Pasta onde os JSONs de formulários são salvos para o Matcher
PASTA_FILA_FORMS = os.path.join(RAIZ_GMA, "fila_forms")

# Pasta onde o Porteiro salva os JSONs de material detectado
PASTA_FILA_MATERIAL = os.path.join(RAIZ_GMA, "fila_material")

# Arquivo sentinela que ativa/desativa o Porteiro
SENTINELA_PORTEIRO = os.path.join(RAIZ_GMA, ".gma_ativo")

# Arquivo de log do Flask
ARQUIVO_LOG = os.path.join(RAIZ_GMA, "logs", "flask_gma.log")

# Campos obrigatórios que todo formulário deve conter
CAMPOS_OBRIGATORIOS = ["nome", "camera", "tipo_material", "data_gravacao"]

# Tempo em minutos para considerar um item como órfão no painel
MINUTOS_ORFAO = 10

# ── IMPORTAÇÃO DO MATCHER ─────────────────────────────────────────────────────

# O matcher.py está na raiz do projeto e precisa ser importado manualmente
import sys
sys.path.insert(0, RAIZ_GMA)

try:
    import matcher as modulo_matcher
    MATCHER_DISPONIVEL = True
except ImportError as erro_import:
    # Se o matcher não puder ser importado, o Flask ainda funciona
    # mas avisa no log que o cruzamento automático não vai rolar
    MATCHER_DISPONIVEL = False

# ── IMPORTAÇÃO DO BANCO DE DADOS (Camada 3 — fonte única de verdade) ──────────
# As telas Kanban (/kanban) e Planilha (/planilha) leem direto do gma.db, e o
# post-it grava de volta nele. Import protegido: se o banco não estiver
# disponível, o resto do Flask continua de pé (offline-first — uma tela nunca
# pode derrubar o servidor de check-in).
try:
    import banco_dados as bd
    BANCO_DISPONIVEL = True
except ImportError:
    BANCO_DISPONIVEL = False


# ── CONFIGURAÇÃO DO LOGGER ────────────────────────────────────────────────────

def configurar_logger():
    """
    Configura o sistema de log do Flask GMA.
    Grava em logs/flask_gma.log e também mostra no terminal.
    Usa o formato padrão GMA: timestamp | mensagem
    """
    logger = logging.getLogger("flask_gma")
    logger.setLevel(logging.DEBUG)

    # Evita duplicar handlers se a função for chamada mais de uma vez
    if logger.handlers:
        return logger

    # Garante que a pasta de logs existe
    os.makedirs(os.path.dirname(ARQUIVO_LOG), exist_ok=True)

    # Formato padrão: 2026-06-05T14:32:01 | mensagem
    formato = logging.Formatter(
        fmt="%(asctime)s | %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S"
    )

    # Handler de arquivo: modo append, nunca apaga o histórico
    handler_arquivo = logging.FileHandler(ARQUIVO_LOG, encoding="utf-8")
    handler_arquivo.setFormatter(formato)
    logger.addHandler(handler_arquivo)

    # Handler de terminal para acompanhamento em tempo real
    handler_terminal = logging.StreamHandler()
    handler_terminal.setFormatter(formato)
    logger.addHandler(handler_terminal)

    return logger


# ── FUNÇÕES AUXILIARES ────────────────────────────────────────────────────────

def gerar_id_form():
    """
    Gera um ID único para o formulário.
    Formato: AAAAMMDD_HHMMSS_XXXXXX (6 caracteres alfanuméricos aleatórios).
    Exemplo: 20260605_143000_ab12cd

    O ID é usado tanto no conteúdo do JSON quanto no nome do arquivo.
    """
    agora = datetime.now()
    sufixo_tempo = agora.strftime("%Y%m%d_%H%M%S")
    # 6 caracteres aleatórios: letras minúsculas + dígitos
    sufixo_aleatorio = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
    return f"{sufixo_tempo}_{sufixo_aleatorio}"


def normalizar_camera(nome_camera):
    """
    Normaliza o nome da câmera para um formato padronizado.
    A primeira palavra fica com inicial maiúscula, o resto em minúsculas.

    Exemplos:
      "blackmagic pocket" → "Blackmagic"
      "SONY FX3"          → "Sony"
      "canon"             → "Canon"

    Usamos apenas a primeira palavra porque é ela que identifica a marca,
    e o Matcher compara por marca no campo marca_camera do material.
    """
    if not nome_camera or not nome_camera.strip():
        return nome_camera

    # Pega apenas a primeira palavra e coloca inicial maiúscula
    primeira_palavra = nome_camera.strip().split()[0]
    return primeira_palavra.capitalize()


def validar_payload_form(dados):
    """
    Verifica se o payload recebido na rota /forms tem todos os campos
    obrigatórios e se o formato da data está correto.

    Retorna uma tupla (valido, mensagem_de_erro):
      - (True, None)          → tudo certo
      - (False, "mensagem")   → faltou algo ou formato inválido
    """
    # Verifica se todos os campos obrigatórios estão presentes e não vazios
    for campo in CAMPOS_OBRIGATORIOS:
        valor = dados.get(campo)
        if not valor or not str(valor).strip():
            return False, f"Campo obrigatório ausente ou vazio: '{campo}'"

    # Valida o formato da data: deve ser AAAA-MM-DD
    data_str = dados.get("data_gravacao", "")
    try:
        datetime.strptime(data_str, "%Y-%m-%d")
    except ValueError:
        return False, f"Formato de data inválido: '{data_str}'. Use AAAA-MM-DD (ex: 2026-06-05)"

    return True, None


def ler_jsons_da_pasta(caminho_pasta, filtro_status=None):
    """
    Lê todos os arquivos .json de uma pasta.
    Se filtro_status for informado, retorna apenas os que têm aquele status.

    Retorna lista de tuplas: (nome_do_arquivo, dicionario_de_dados)
    Arquivos com erro de leitura são silenciosamente ignorados.
    """
    resultado = []

    if not os.path.isdir(caminho_pasta):
        return resultado

    try:
        nomes_arquivos = sorted(os.listdir(caminho_pasta))
    except OSError:
        return resultado

    for nome_arquivo in nomes_arquivos:
        if not nome_arquivo.endswith(".json"):
            continue

        caminho_completo = os.path.join(caminho_pasta, nome_arquivo)

        try:
            with open(caminho_completo, "r", encoding="utf-8") as f:
                dados = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue  # arquivo corrompido — pula sem travar

        # Aplica o filtro de status, se foi pedido
        if filtro_status is None or dados.get("status") == filtro_status:
            resultado.append((nome_arquivo, dados))

    return resultado


def identificar_orfaos():
    """
    Varre as duas filas e retorna os itens que estão aguardando
    há mais de MINUTOS_ORFAO minutos sem encontrar correspondência.

    Retorna um dicionário com duas chaves:
      "materiais" — lista de dicionários de material órfão
      "forms"     — lista de dicionários de formulário órfão
    """
    agora = datetime.now()
    limite = timedelta(minutes=MINUTOS_ORFAO)

    materiais_orfaos = []
    forms_orfaos = []

    # Verifica materiais aguardando formulário
    for nome_arquivo, dados in ler_jsons_da_pasta(PASTA_FILA_MATERIAL, "aguardando_match"):
        timestamp_str = dados.get("timestamp", "")
        try:
            timestamp_item = datetime.strptime(timestamp_str, "%Y-%m-%dT%H:%M:%S")
            if (agora - timestamp_item) > limite:
                materiais_orfaos.append({"arquivo": nome_arquivo, "dados": dados})
        except ValueError:
            pass  # timestamp malformado — ignora

    # Verifica formulários aguardando material
    for nome_arquivo, dados in ler_jsons_da_pasta(PASTA_FILA_FORMS, "aguardando_material"):
        timestamp_str = dados.get("timestamp", "")
        try:
            timestamp_item = datetime.strptime(timestamp_str, "%Y-%m-%dT%H:%M:%S")
            if (agora - timestamp_item) > limite:
                forms_orfaos.append({"arquivo": nome_arquivo, "dados": dados})
        except ValueError:
            pass

    return {"materiais": materiais_orfaos, "forms": forms_orfaos}


def contar_matches_hoje():
    """
    Conta quantos materiais fizeram match hoje (pelo campo 'timestamp' do JSON).
    Percorre apenas fila_material/ com status 'matched'.
    """
    hoje = datetime.now().date()
    contagem = 0

    for _nome, dados in ler_jsons_da_pasta(PASTA_FILA_MATERIAL, "matched"):
        # Tenta usar o campo timestamp do material como referência de data
        timestamp_str = dados.get("timestamp", "")
        try:
            data_item = datetime.strptime(timestamp_str, "%Y-%m-%dT%H:%M:%S").date()
            if data_item == hoje:
                contagem += 1
        except ValueError:
            # Se o timestamp não puder ser lido, conta assim mesmo (margem de segurança)
            contagem += 1

    return contagem


def tempo_desde(timestamp_str):
    """
    Calcula há quantos minutos um item está na fila.
    Retorna uma string legível: "3 min", "1h 12min", etc.
    Retorna "?" se o timestamp for inválido.
    """
    try:
        timestamp_item = datetime.strptime(timestamp_str, "%Y-%m-%dT%H:%M:%S")
        delta = datetime.now() - timestamp_item
        minutos_totais = int(delta.total_seconds() // 60)
        if minutos_totais < 60:
            return f"{minutos_totais} min"
        horas = minutos_totais // 60
        minutos_restantes = minutos_totais % 60
        return f"{horas}h {minutos_restantes}min"
    except ValueError:
        return "?"


# ── CRIAÇÃO DO APP FLASK ──────────────────────────────────────────────────────

app = Flask(__name__)
logger = configurar_logger()


# ── PORTÃO DE ACESSO (escopo por papel + autenticação) ───────────────────────
# Duas camadas de proteção, nesta ordem, para toda requisição:
#
# 1) ESCOPO POR ORIGEM (papel). Princípio: a OPERAÇÃO completa (painel, Kanban,
#    Planilha, controle do Porteiro) só existe na BASE (localhost). Quem chega de
#    FORA (link público das câmeras, via túnel/rede) só alcança o preenchimento da
#    FICHA — e os webhooks de entrada. Fecha o risco de alguém com o link mexer no
#    Porteiro ou ver as telas de gestão.
#    (O papel remoto de SUPERVISÃO — monitorar o processo de longe — é um 2º link
#    com escopo próprio, ainda a desenhar: é design da Camada 5.)
#
# 2) AUTENTICAÇÃO (Basic Auth) — pré-requisito inegociável para expor na internet.
#    Liga com a variável GMA_SENHA. Vazia → sem senha (uso local livre). Definida →
#    o navegador pede login. Webhooks /forms ficam ISENTOS de senha (têm HMAC).
ROTAS_SEM_SENHA = ("/forms",)  # webhooks de entrada (sem Basic Auth)


def _host_local():
    """True se a requisição veio da própria máquina (base), False se veio de fora."""
    host = (request.host or "").split(":")[0]
    return host in ("127.0.0.1", "localhost")


def _remoto_pode_acessar(path):
    """
    O que o link público (câmera) alcança: SÓ preencher uma ficha NOVA
    (exatamente /ficha — GET do formulário e POST do envio) e os webhooks de
    entrada (/forms*). Tudo mais fica só na BASE — inclusive EDITAR fichas
    (/ficha/<id>/editar) e as telas de gestão (Kanban, Planilha, Porteiro).
    """
    if path == "/ficha":            # nova ficha: formulário (GET) e envio (POST)
        return True
    if path.startswith("/forms"):   # webhooks de entrada (Tally/Forms)
        return True
    return False                    # bloqueia edição de fichas e telas de gestão


@app.before_request
def _portao_de_acesso():
    # ── 1) Escopo por origem (papel) ──────────────────────────────────────────
    if not _host_local() and not _remoto_pode_acessar(request.path):
        # Acesso remoto a uma rota de operação → bloqueia. Se for a raiz, manda
        # gentilmente para a ficha (a câmera não precisa saber das outras telas).
        if request.path == "/":
            return redirect("/ficha")
        return (
            '<h2 style="font-family:sans-serif">GMA</h2>'
            '<p style="font-family:sans-serif">Este link dá acesso apenas ao '
            'preenchimento da ficha. <a href="/ficha">Ir para a ficha →</a></p>',
            403,
            {"Content-Type": "text/html; charset=utf-8"},
        )

    # ── 2) Autenticação por senha ─────────────────────────────────────────────
    senha_exigida = os.environ.get("GMA_SENHA", "").strip()
    if not senha_exigida:
        return  # sem senha configurada → acesso livre (uso local)

    if request.path.startswith(ROTAS_SEM_SENHA):
        return  # webhooks têm HMAC próprio

    auth = request.authorization
    senha_enviada = auth.password if (auth and auth.password) else ""
    # compare_digest evita vazar o tamanho/posição por tempo de resposta.
    if auth and hmac.compare_digest(senha_enviada, senha_exigida):
        return  # senha correta → libera

    # Sem credencial válida → pede login do navegador (401 + WWW-Authenticate).
    return (
        '<h2 style="font-family:sans-serif">GMA — acesso restrito</h2>'
        '<p style="font-family:sans-serif">Esta tela exige senha.</p>',
        401,
        {"WWW-Authenticate": 'Basic realm="GMA"', "Content-Type": "text/html; charset=utf-8"},
    )


# ── FUNÇÃO CENTRAL: VALIDAR, SALVAR E DISPARAR MATCHER ───────────────────────
# Esta função contém toda a lógica de processamento de um formulário recebido.
# Ela é chamada por /forms (Google Forms via Apps Script) e por /forms/tally
# (webhook nativo do Tally), que chegam em formatos diferentes mas precisam
# da mesma cadeia de validação + gravação + Matcher.

def _processar_e_salvar_formulario(dados_recebidos, origem="FORMS"):
    """
    Recebe um dicionário com os campos do formulário já extraídos e normalizados
    no padrão esperado pelo GMA:
        nome, camera, tipo_material, data_gravacao, operador (opcional)

    Retorna uma tupla (resposta_flask, codigo_http) pronta para ser devolvida
    pela rota que chamou esta função.

    O parâmetro `origem` é só para o log distinguir de qual endpoint veio
    (ex: "FORMS" para Google Forms, "TALLY" para o webhook do Tally).
    """
    # ── Valida os campos obrigatórios ──────────────────────────────────────────
    valido, mensagem_erro = validar_payload_form(dados_recebidos)
    if not valido:
        logger.warning(
            f"{origem} | Validação falhou | {mensagem_erro} | IP: {request.remote_addr}"
        )
        return jsonify({"ok": False, "erro": mensagem_erro}), 422

    # ── Monta o dicionário do formulário ───────────────────────────────────────
    id_form = gerar_id_form()
    agora = datetime.now()
    timestamp_iso = agora.strftime("%Y-%m-%dT%H:%M:%S")

    # Normaliza campos de texto: câmera com inicial maiúscula, nome em maiúsculas
    camera_normalizada = normalizar_camera(dados_recebidos.get("camera", ""))
    nome_normalizado = dados_recebidos.get("nome", "").strip().upper()

    dados_form = {
        "id_form":          id_form,
        "timestamp":        timestamp_iso,
        "nome":             nome_normalizado,
        "camera":           camera_normalizada,
        "tipo_material":    dados_recebidos.get("tipo_material", "").strip().upper(),
        "data_gravacao":    dados_recebidos.get("data_gravacao", "").strip(),
        "operador":         dados_recebidos.get("operador", "").strip() or None,
        # Campos editoriais (opcionais — não bloqueiam validação nem matching)
        "modelo_camera":    dados_recebidos.get("modelo_camera", "").strip() or None,
        "tipo_conteudo":    dados_recebidos.get("tipo_conteudo", "").strip().upper() or None,
        "local_cena":       dados_recebidos.get("local_cena", "").strip() or None,
        "prioridade":       dados_recebidos.get("prioridade", "NORMAL").strip().upper() or "NORMAL",
        "observacoes":      dados_recebidos.get("observacoes", "").strip() or None,
        "status":           "aguardando_material",  # estado inicial
        "material_match":   None,                   # preenchido pelo Matcher
    }

    # ── Salva o JSON em fila_forms/ ───────────────────────────────────────────
    # Nome do arquivo: form_AAAAMMDD_HHMMSS_XXXX.json (baseado no id_form)
    nome_arquivo = f"form_{id_form}.json"
    caminho_arquivo = os.path.join(PASTA_FILA_FORMS, nome_arquivo)

    try:
        os.makedirs(PASTA_FILA_FORMS, exist_ok=True)
        with open(caminho_arquivo, "w", encoding="utf-8") as f:
            json.dump(dados_form, f, ensure_ascii=False, indent=2)
        logger.info(
            f"{origem} | Formulário salvo | ID: {id_form} | "
            f"Nome: {nome_normalizado} | "
            f"Câmera: {camera_normalizada} | "
            f"Arquivo: {nome_arquivo}"
        )
    except OSError as erro:
        logger.error(f"{origem} | Erro ao salvar arquivo | {erro}")
        return jsonify({
            "ok": False,
            "erro": "Erro interno ao salvar o formulário. Tente novamente."
        }), 500

    # ── Integração Camada 3: grava no banco de dados SQLite ─────────────────
    # Este bloco é ADITIVO — se falhar, o fluxo JSON continua normalmente.
    # O banco é uma camada de segurança extra, nunca um ponto de falha.
    try:
        import banco_dados as _bd
        _conn_flask = _bd.inicializar_banco()
        _db_id = _bd.gravar_formulario(
            _conn_flask,
            id_form=id_form,
            nome=nome_normalizado,
            camera=camera_normalizada,
            tipo_material=dados_form["tipo_material"],
            data_gravacao=dados_form["data_gravacao"],
            operador=dados_form.get("operador"),
            modelo_camera=dados_form.get("modelo_camera"),
            tipo_conteudo=dados_form.get("tipo_conteudo"),
            local_cena=dados_form.get("local_cena"),
            prioridade=dados_form.get("prioridade"),
            observacoes=dados_form.get("observacoes"),
        )
        _conn_flask.close()
        # Salva o ID do banco de volta no JSON (ponte para o Matcher e Transferência)
        dados_form["db_formulario_id"] = _db_id
        with open(caminho_arquivo, "w", encoding="utf-8") as _f:
            json.dump(dados_form, _f, ensure_ascii=False, indent=2)
        logger.info(f"BANCO | Formulário gravado | db_id={_db_id}")
    except Exception as _err_bd:
        logger.error(f"BANCO | Falha ao gravar formulário (fluxo JSON continua) | {_err_bd}")

    # ── Tenta fazer match com material já na fila ────────────────────────────
    matches = []
    if MATCHER_DISPONIVEL:
        try:
            matches = modulo_matcher.tentar_match()
            if matches:
                logger.info(
                    f"{origem} | Matcher encontrou {len(matches)} match(es) "
                    f"após receber formulário {id_form}"
                )
        except Exception as erro:
            # Erro no Matcher não impede o registro do formulário
            logger.error(f"{origem} | Erro ao chamar Matcher | {erro}")
    else:
        logger.warning(f"{origem} | Matcher não disponível — cruzamento automático desativado")

    # ── Retorna confirmação ────────────────────────────────────────────────────
    return jsonify({
        "ok":              True,
        "id_form":         id_form,
        "nome":            nome_normalizado,
        "camera":          camera_normalizada,
        "matches_gerados": len(matches),
        "mensagem":        "Formulário recebido com sucesso."
    }), 201


# ── ROTA 1: RECEBER FORMULÁRIO DO GOOGLE FORMS ────────────────────────────────

@app.route("/forms", methods=["POST"])
def receber_formulario():
    """
    Recebe os dados do Google Forms enviados pelo Google Apps Script (webhook).

    O Apps Script deve enviar um POST para http://<ip-local>:5050/forms
    com Content-Type: application/json e o payload descrito no topo deste arquivo.

    Passos:
      1. Lê e valida o JSON recebido.
      2. Delega validação, gravação e Matcher para _processar_e_salvar_formulario().
      3. Retorna resposta JSON com status e id_form.
    """
    # ── Lê o corpo da requisição ───────────────────────────────────────────────
    try:
        dados_recebidos = request.get_json(force=True)
        if dados_recebidos is None:
            raise ValueError("corpo da requisição vazio ou não é JSON válido")
    except Exception as erro:
        logger.warning(f"FORMS | Payload inválido recebido | Erro: {erro}")
        return jsonify({
            "ok": False,
            "erro": "Payload inválido. Envie JSON com Content-Type: application/json."
        }), 400

    # Delega toda a lógica de validação + gravação + Matcher para a função central
    return _processar_e_salvar_formulario(dados_recebidos, origem="FORMS")


# ── ROTA 1b: RECEBER WEBHOOK NATIVO DO TALLY ─────────────────────────────────
# O Tally envia os dados em um envelope diferente do Google Forms:
#   { "data": { "fields": [ { "label": "nome", "value": "JOAO" }, ... ] } }
# Este endpoint desempacota esse envelope e repassa os campos para a mesma
# lógica de validação e processamento usada pela rota /forms.
#
# Os labels esperados (configurados no formulário Tally) são exatamente:
#   nome, camera, tipo_material, data_gravacao, operador

@app.route("/forms/tally", methods=["POST"])
def receber_formulario_tally():
    """
    Recebe o webhook nativo do Tally (formato data.fields).

    Verificação HMAC-SHA256 (header 'tally-signature'):
      - Se a variável de ambiente TALLY_WEBHOOK_SECRET estiver definida,
        verifica a assinatura e rejeita a requisição se for inválida.
      - Se a variável NÃO estiver definida, aceita normalmente sem verificar.
        (Útil em testes locais ou quando a segurança é garantida pela rede.)

    Após desempacotar o envelope, os dados passam pela mesma cadeia de
    validação + gravação + Matcher que o endpoint /forms usa.
    """
    corpo_bytes = request.get_data()  # lê os bytes brutos antes de parsear

    # ── Verificação HMAC opcional ──────────────────────────────────────────────
    segredo = os.environ.get("TALLY_WEBHOOK_SECRET")
    if segredo:
        # O Tally envia o header 'tally-signature' com a assinatura HMAC-SHA256
        # do corpo da requisição usando o segredo configurado no painel do Tally.
        assinatura_recebida = request.headers.get("tally-signature", "")
        # Calcula a assinatura esperada com o segredo e o corpo bruto
        assinatura_esperada = hmac.new(
            segredo.encode("utf-8"),
            corpo_bytes,
            hashlib.sha256
        ).hexdigest()
        # Comparação segura contra timing attacks (não usar ==)
        if not hmac.compare_digest(assinatura_recebida, assinatura_esperada):
            logger.warning(
                f"TALLY | Assinatura HMAC inválida | IP: {request.remote_addr}"
            )
            return jsonify({
                "ok": False,
                "erro": "Assinatura inválida. Verifique o TALLY_WEBHOOK_SECRET."
            }), 401
        logger.info("TALLY | Assinatura HMAC verificada com sucesso")
    else:
        # Sem segredo configurado: aceita normalmente (modo desenvolvimento/rede confiável)
        logger.info("TALLY | TALLY_WEBHOOK_SECRET não configurado — aceitando sem verificação")

    # ── Lê e valida o corpo JSON ───────────────────────────────────────────────
    try:
        payload = json.loads(corpo_bytes)
        if payload is None:
            raise ValueError("corpo vazio")
    except Exception as erro:
        logger.warning(f"TALLY | Payload inválido | Erro: {erro}")
        return jsonify({
            "ok": False,
            "erro": "Payload inválido. Envie JSON com Content-Type: application/json."
        }), 400

    # ── Desempacota o envelope do Tally ───────────────────────────────────────
    # O Tally envia: { "data": { "fields": [ { "label": "...", "value": "..." }, ... ] } }
    # Percorre a lista de campos e monta um dicionário simples {label: value}
    # para poder usar a mesma validação e processamento do /forms.
    try:
        campos_lista = payload["data"]["fields"]
        dados_recebidos = {
            campo["label"]: campo.get("value", "")
            for campo in campos_lista
            if campo.get("label")  # ignora entradas sem label
        }
    except (KeyError, TypeError) as erro:
        logger.warning(f"TALLY | Envelope inesperado | Erro: {erro} | Payload: {payload}")
        return jsonify({
            "ok": False,
            "erro": (
                "Formato de payload do Tally não reconhecido. "
                "Esperado: {\"data\": {\"fields\": [{\"label\": ..., \"value\": ...}]}}"
            )
        }), 400

    logger.info(
        f"TALLY | Campos extraídos do envelope: {list(dados_recebidos.keys())} | "
        f"IP: {request.remote_addr}"
    )

    # Delega toda a lógica de validação + gravação + Matcher para a função central
    return _processar_e_salvar_formulario(dados_recebidos, origem="TALLY")


# ── ROTA 2: PAINEL HTML DA SEGUNDA MÁQUINA ────────────────────────────────────

@app.route("/", methods=["GET"])
def painel():
    """
    Gera e retorna a página HTML do painel de monitoramento.

    Mostra em tempo real (auto-refresh a cada 5 segundos):
      - Material aguardando match (Porteiro anotou, form não chegou)
      - Forms aguardando material (form chegou, Porteiro ainda não anotou)
      - Matches recentes (últimos 10)
      - Órfãos (esperando mais de MINUTOS_ORFAO minutos)
      - Status do Porteiro (ativo/inativo)

    HTML puro com CSS inline — sem frameworks externos.
    """
    # ── Coleta dados das filas ─────────────────────────────────────────────────
    material_aguardando = ler_jsons_da_pasta(PASTA_FILA_MATERIAL, "aguardando_match")
    forms_aguardando = ler_jsons_da_pasta(PASTA_FILA_FORMS, "aguardando_material")

    # Itens aguardando confirmação humana (match ambíguo detectado pelo Matcher)
    # Lemos das duas filas e consolidamos numa lista única para exibição.
    # Usamos um dicionário para deduplicar por nome de arquivo.
    _confirmacao_bruto = {}
    for nome_arq, dados_arq in ler_jsons_da_pasta(PASTA_FILA_MATERIAL, "aguardando_confirmacao"):
        _confirmacao_bruto[nome_arq] = ("material", dados_arq)
    for nome_arq, dados_arq in ler_jsons_da_pasta(PASTA_FILA_FORMS, "aguardando_confirmacao"):
        _confirmacao_bruto[nome_arq] = ("form", dados_arq)
    aguardando_confirmacao = list(_confirmacao_bruto.items())  # [(nome_arq, (tipo, dados))]

    # Matches recentes (todos com status matched, ordena por timestamp decrescente)
    todos_matched = ler_jsons_da_pasta(PASTA_FILA_MATERIAL, "matched")
    # Ordena por timestamp do arquivo (nome do arquivo já é cronológico)
    todos_matched.sort(key=lambda x: x[0], reverse=True)
    matches_recentes = todos_matched[:10]

    # Identifica órfãos
    orfaos = identificar_orfaos()
    total_orfaos = len(orfaos["materiais"]) + len(orfaos["forms"])

    # Estado do Porteiro
    porteiro_ativo = os.path.isfile(SENTINELA_PORTEIRO)
    porteiro_status_texto = "ATIVO" if porteiro_ativo else "INATIVO"
    porteiro_cor = "#27ae60" if porteiro_ativo else "#c0392b"

    # Hora atual para exibição
    hora_atual = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

    # ── Gera as linhas das tabelas ─────────────────────────────────────────────
    def linha_material(nome_arquivo, dados):
        """Gera uma linha <tr> para um item de material."""
        tempo = tempo_desde(dados.get("timestamp", ""))
        marca = dados.get("marca_camera") or "—"
        nome = dados.get("nome", "—")
        origem = dados.get("origem", "—")
        return (
            f"<tr>"
            f"<td>{nome}</td>"
            f"<td>{marca}</td>"
            f"<td>{origem}</td>"
            f"<td>{tempo}</td>"
            f"</tr>"
        )

    def linha_form(nome_arquivo, dados):
        """Gera uma linha <tr> para um item de formulário."""
        tempo = tempo_desde(dados.get("timestamp", ""))
        nome = dados.get("nome", "—")
        camera = dados.get("camera", "—")
        operador = dados.get("operador") or "—"
        # Monta coluna "Conteudo": junta tipo_conteudo e local_cena quando disponíveis
        # Exemplo: "B-ROLL — Backstage" ou apenas "ENTREVISTA" se local_cena estiver vazio
        tipo_conteudo = dados.get("tipo_conteudo") or ""
        local_cena = dados.get("local_cena") or ""
        if tipo_conteudo and local_cena:
            conteudo = f"{tipo_conteudo} &mdash; {local_cena}"
        elif tipo_conteudo:
            conteudo = tipo_conteudo
        elif local_cena:
            conteudo = local_cena
        else:
            # Fallback para tipo_material quando campos editoriais não foram preenchidos
            conteudo = dados.get("tipo_material", "—")
        # Prioridade: destaca URGENTE em vermelho
        prioridade = dados.get("prioridade") or "NORMAL"
        cor_prioridade = "#c0392b" if prioridade == "URGENTE" else "#6c757d"
        return (
            f"<tr>"
            f"<td>{nome}</td>"
            f"<td>{camera}</td>"
            f"<td>{conteudo}</td>"
            f"<td style='color:{cor_prioridade};font-weight:600'>{prioridade}</td>"
            f"<td>{operador}</td>"
            f"<td>{tempo}</td>"
            f"</tr>"
        )

    def linha_match(nome_arquivo, dados):
        """Gera uma linha <tr> para um match confirmado."""
        nome = dados.get("nome", "—")
        marca = dados.get("marca_camera") or "—"
        form_match = dados.get("form_match", "—")
        # Extrai apenas o ID do formulário (remove o prefixo "form_" e a extensão)
        if form_match and form_match.startswith("form_"):
            id_form_exibido = form_match[5:].replace(".json", "")
        else:
            id_form_exibido = form_match or "—"
        tempo = tempo_desde(dados.get("timestamp", ""))
        return (
            f"<tr>"
            f"<td>{nome}</td>"
            f"<td>{marca}</td>"
            f"<td style='font-family:monospace;font-size:0.85em'>{id_form_exibido}</td>"
            f"<td>{tempo}</td>"
            f"</tr>"
        )

    def _amostra_arquivos_material(dados_json):
        """
        Monta uma pista de 3-4 "nomes de arquivo" do cartão para o operador
        reconhecer de quem é o material na tela de empate (desenho §2 — a pista
        que desempata na prática de set).

        IMPORTANTE: o Leitor NÃO guarda a lista completa de nomes de arquivo no
        JSON do material — ele guarda os RADICAIS dos arquivos dentro de
        'assinatura.prefixos' (ex.: ['joe', 'joe0258T', 'joe0259T', ...]). O
        primeiro costuma ser o radical comum genérico ('joe'); os seguintes são
        os radicais de cada arquivo, que é justamente a pista útil. Caso um dia
        o Leitor passe a gravar uma lista de nomes completos, também a usamos.
        """
        # 1) Se algum dia existir uma lista de nomes de arquivo de fato, use-a.
        lista = (
            dados_json.get("arquivos_midia")
            or dados_json.get("arquivos")
            or dados_json.get("lista_arquivos")
            or []
        )
        nomes = []
        for item in lista[:4]:
            if isinstance(item, str):
                nomes.append(os.path.basename(item))
            elif isinstance(item, dict):
                # Formato alternativo: {"nome": "...", "tamanho": ...}
                nomes.append(os.path.basename(item.get("nome", "") or ""))
        nomes = [n for n in nomes if n]  # remove vazios
        if nomes:
            return " · ".join(nomes)

        # 2) Fonte real hoje: os radicais dos arquivos na assinatura do cartão.
        assinatura = dados_json.get("assinatura") or {}
        prefixos = assinatura.get("prefixos") or []
        # Prioriza os radicais que parecem nome de arquivo (têm dígitos),
        # deixando de fora o radical comum genérico (ex.: 'joe').
        especificos = [
            p for p in prefixos
            if isinstance(p, str) and any(caractere.isdigit() for caractere in p)
        ]
        if especificos:
            return " · ".join(especificos[:4])
        # Sem radicais específicos: mostra os primeiros prefixos que houver.
        genericos = [p for p in prefixos if isinstance(p, str)][:4]
        if genericos:
            return " · ".join(genericos)

        return "(sem amostra de arquivos)"

    def bloco_confirmacao_cartao(nome_arquivo, tipo, dados):
        """
        Gera um bloco HTML completo para um cartão aguardando confirmacao humana.

        Cada bloco mostra:
          - Cabeçalho: volume · nº de arquivos · câmera detectada
          - Um sub-bloco por candidato com nome, câmera da ficha, amostra de
            arquivos e botão "Confirmar [NOME]"

        Para os candidatos, consulta a tabela match_candidatos no banco (fonte
        definitiva). Se o banco não tiver candidatos (empate antigo gravado só
        no JSON), faz fallback para o campo candidatos_match do próprio JSON.
        """
        # Só cartões de material têm candidatos (forms em aguardando_confirmacao
        # são raros e não têm db_cartao_id). Exibe resumo simples para forms.
        if tipo == "form":
            nome = html.escape(dados.get("nome", "—"))
            camera = html.escape(dados.get("camera", "—"))
            return f"""
            <div style="border:1px solid #f48fb1;border-radius:6px;padding:12px 16px;margin:8px 0;background:#fff5f7">
                <strong>{nome}</strong> &middot; {camera}
                <span style="color:#888;font-size:0.85em"> — formulario aguardando confirmacao</span>
            </div>"""

        # ── Cabeçalho do cartão ───────────────────────────────────────────────
        volume = html.escape(dados.get("nome") or dados.get("volume") or "—")
        camera_detectada = html.escape(dados.get("marca_camera") or "—")
        # Conta arquivos: pode estar em n_arquivos, total_arquivos ou contagem_total
        n_arquivos = (
            dados.get("n_arquivos")
            or dados.get("total_arquivos")
            or dados.get("contagem_total")
            or "?"
        )
        cartao_id = dados.get("db_cartao_id")

        # Pista de arquivos: lista de nomes do JSON (antes da transferência)
        amostra = html.escape(_amostra_arquivos_material(dados))

        # ── Candidatos: busca no banco (fonte definitiva) ─────────────────────
        candidatos_banco = []
        if BANCO_DISPONIVEL and cartao_id:
            try:
                _conn = bd.obter_conexao()
                candidatos_banco = _conn.execute(
                    """SELECT nome, camera_ficha, score, formulario_id
                       FROM match_candidatos
                       WHERE cartao_id = ? AND status = 'pendente'
                       ORDER BY score DESC""",
                    (cartao_id,)
                ).fetchall()
                _conn.close()
            except Exception as _err_cand:
                logger.error(
                    f"PAINEL | Erro ao buscar candidatos do cartão {cartao_id} | {_err_cand}"
                )

        # Fallback: usa a lista do JSON quando o banco não tem candidatos
        # (empate antigo registrado antes desta feature entrar)
        if not candidatos_banco:
            candidatos_json = dados.get("candidatos_match") or []
            # Converte para o mesmo formato de dicionário que o banco devolveria
            candidatos_banco = [
                {
                    "nome":         c.get("nome", "—") if isinstance(c, dict) else str(c),
                    "camera_ficha": c.get("camera", "—") if isinstance(c, dict) else "—",
                    "score":        c.get("score", "?") if isinstance(c, dict) else "?",
                }
                for c in candidatos_json
            ]

        # Monta os sub-blocos de cada candidato
        blocos_candidatos = ""
        for cand in candidatos_banco:
            nome_cand = html.escape(str(cand["nome"] if hasattr(cand, "__getitem__") else "—"))
            cam_cand  = html.escape(str(cand["camera_ficha"] if hasattr(cand, "__getitem__") else "—"))
            score_cand = cand["score"] if hasattr(cand, "__getitem__") else "?"

            # Se cartao_id existe, monta o botão de confirmação; senão, só info
            if cartao_id:
                botao = f"""
                <form action="/match/{cartao_id}/confirmar" method="post" style="display:inline">
                    <input type="hidden" name="nome" value="{nome_cand}">
                    <button type="submit"
                            style="background:#27ae60;color:#fff;border:none;border-radius:5px;
                                   padding:5px 14px;font-weight:700;font-size:0.85em;cursor:pointer;">
                        Confirmar {nome_cand}
                    </button>
                </form>"""
            else:
                botao = "<span style='color:#888;font-size:0.82em'>(sem id de cartao — nao e possivel confirmar)</span>"

            blocos_candidatos += f"""
            <div style="background:#f8f9fa;border-radius:5px;padding:10px 14px;margin-top:8px">
                <div style="font-weight:700;font-size:0.95em">{nome_cand}
                    <span style="font-weight:400;color:#6c757d;font-size:0.88em">
                        &middot; {cam_cand}
                        &middot; <span style="font-family:monospace">score {score_cand}</span>
                    </span>
                </div>
                <div style="color:#888;font-size:0.82em;margin:4px 0 8px;font-family:monospace">
                    {amostra}
                </div>
                {botao}
            </div>"""

        if not blocos_candidatos:
            blocos_candidatos = "<div style='color:#888;font-size:0.85em;margin-top:8px'>Sem candidatos registrados para este cartao.</div>"

        return f"""
        <div style="border:1px solid #f48fb1;border-radius:6px;padding:14px 18px;margin:10px 0;background:#fff5f7">
            <div style="font-weight:700;font-size:1em;margin-bottom:2px">
                {volume}
                <span style="font-weight:400;color:#6c757d;font-size:0.88em">
                    &middot; {n_arquivos} arquivos &middot; {camera_detectada}
                </span>
            </div>
            <div style="color:#c0392b;font-size:0.82em;margin-bottom:6px">
                Quem e esse cartao?
            </div>
            {blocos_candidatos}
        </div>"""

    # Renderiza as linhas de cada seção
    linhas_material = "".join(
        linha_material(n, d) for n, d in material_aguardando
    ) or "<tr><td colspan='4' style='color:#888;text-align:center'>Nenhum material aguardando</td></tr>"

    linhas_forms = "".join(
        linha_form(n, d) for n, d in forms_aguardando
    ) or "<tr><td colspan='6' style='color:#888;text-align:center'>Nenhum formulário aguardando</td></tr>"

    linhas_matches = "".join(
        linha_match(n, d) for n, d in matches_recentes
    ) or "<tr><td colspan='4' style='color:#888;text-align:center'>Nenhum match registrado hoje</td></tr>"

    # Renderiza os blocos da seção "Aguardando confirmacao" — cada cartão é um bloco
    blocos_confirmacao = "".join(
        bloco_confirmacao_cartao(nome_arq, tipo, dados)
        for nome_arq, (tipo, dados) in aguardando_confirmacao
    ) or "<p style='color:#888;text-align:center;padding:18px'>Nenhum item aguardando confirmacao</p>"

    # Alerta de órfãos (aparece destacado se houver algum)
    if total_orfaos > 0:
        nomes_orfaos_mat = ", ".join(d["dados"].get("nome", "?") for d in orfaos["materiais"])
        nomes_orfaos_form = ", ".join(d["dados"].get("nome", "?") for d in orfaos["forms"])
        partes_alerta = []
        if orfaos["materiais"]:
            partes_alerta.append(f"Material sem form ({len(orfaos['materiais'])}): {nomes_orfaos_mat}")
        if orfaos["forms"]:
            partes_alerta.append(f"Form sem material ({len(orfaos['forms'])}): {nomes_orfaos_form}")
        bloco_orfaos = f"""
        <div style="background:#fff3cd;border:1px solid #ffc107;border-radius:6px;
                    padding:12px 18px;margin-bottom:20px;color:#856404;">
            <strong>Atencao: {total_orfaos} orfao(s) aguardando ha mais de {MINUTOS_ORFAO} minutos</strong><br>
            {"<br>".join(partes_alerta)}
        </div>"""
    else:
        bloco_orfaos = ""

    # ── Monta o HTML completo ──────────────────────────────────────────────────
    pagina_html = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>GMA — Painel de Check-in</title>
    <meta http-equiv="refresh" content="5">
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            background: #f0f2f5;
            color: #1a1a1a;
            font-size: 14px;
        }}
        header {{
            background: #1a1a2e;
            color: white;
            padding: 14px 24px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        header h1 {{ font-size: 1.2em; font-weight: 600; letter-spacing: 0.5px; }}
        header .info {{ font-size: 0.85em; opacity: 0.75; }}
        .porteiro-badge {{
            display: inline-block;
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 0.8em;
            font-weight: 700;
            letter-spacing: 1px;
            background: {porteiro_cor};
            color: white;
        }}
        main {{ padding: 20px 24px; max-width: 1200px; margin: 0 auto; }}
        .grid {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
            margin-bottom: 20px;
        }}
        .card {{
            background: white;
            border-radius: 8px;
            box-shadow: 0 1px 4px rgba(0,0,0,0.08);
            overflow: hidden;
        }}
        .card-full {{ grid-column: 1 / -1; }}
        .card-header {{
            padding: 12px 16px;
            font-weight: 600;
            font-size: 0.9em;
            letter-spacing: 0.3px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        .card-header .badge {{
            background: #e9ecef;
            color: #495057;
            border-radius: 12px;
            padding: 2px 10px;
            font-size: 0.85em;
            font-weight: 700;
        }}
        .header-material    {{ background: #fff8e1; border-bottom: 2px solid #f59e0b; }}
        .header-forms       {{ background: #e8f5e9; border-bottom: 2px solid #4caf50; }}
        .header-matches     {{ background: #e3f2fd; border-bottom: 2px solid #2196f3; }}
        .header-confirmacao {{ background: #fce4ec; border-bottom: 2px solid #e91e63; }}
        table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 0.88em;
        }}
        th {{
            padding: 8px 12px;
            text-align: left;
            background: #f8f9fa;
            border-bottom: 1px solid #dee2e6;
            font-weight: 600;
            color: #6c757d;
            font-size: 0.82em;
            text-transform: uppercase;
            letter-spacing: 0.4px;
        }}
        td {{
            padding: 9px 12px;
            border-bottom: 1px solid #f1f3f5;
            vertical-align: middle;
        }}
        tr:last-child td {{ border-bottom: none; }}
        tr:hover td {{ background: #f8f9fa; }}
        .rodape {{
            text-align: center;
            padding: 16px;
            color: #adb5bd;
            font-size: 0.8em;
        }}
        .controles {{
            display: flex;
            gap: 10px;
            margin-bottom: 20px;
            align-items: center;
        }}
        .btn {{
            padding: 8px 18px;
            border: none;
            border-radius: 6px;
            font-size: 0.88em;
            font-weight: 600;
            cursor: pointer;
            text-decoration: none;
        }}
        .btn-ativar   {{ background: #27ae60; color: white; }}
        .btn-desativar {{ background: #c0392b; color: white; }}
        .status-porteiro {{
            font-size: 0.85em;
            color: #6c757d;
        }}
        {CSS_ABAS}
    </style>
</head>
<body>
    <header>
        <h1>GMA — Painel de Check-in</h1>
        <div style="display:flex;align-items:center;gap:16px">
            <span class="porteiro-badge">PORTEIRO: {porteiro_status_texto}</span>
            <span class="info">Atualizado: {hora_atual}</span>
        </div>
    </header>
    {barra_abas('operacao')}

    <main>
        {bloco_orfaos}

        <div class="controles">
            <form action="/porteiro/ativar" method="post" style="display:inline">
                <button type="submit" class="btn btn-ativar">Ativar Porteiro</button>
            </form>
            <form action="/porteiro/desativar" method="post" style="display:inline">
                <button type="submit" class="btn btn-desativar">Desativar Porteiro</button>
            </form>
            <span class="status-porteiro">
                Porteiro: <strong style="color:{porteiro_cor}">{porteiro_status_texto}</strong>
                &nbsp;|&nbsp;
                Material aguardando: <strong>{len(material_aguardando)}</strong>
                &nbsp;|&nbsp;
                Forms aguardando: <strong>{len(forms_aguardando)}</strong>
                &nbsp;|&nbsp;
                Matches hoje: <strong>{contar_matches_hoje()}</strong>
            </span>
        </div>

        <div class="grid">
            <!-- Bloco: Material aguardando formulário -->
            <div class="card">
                <div class="card-header header-material">
                    Material aguardando formulario
                    <span class="badge">{len(material_aguardando)}</span>
                </div>
                <table>
                    <tr>
                        <th>Volume / Item</th>
                        <th>Camera</th>
                        <th>Origem</th>
                        <th>Ha quanto tempo</th>
                    </tr>
                    {linhas_material}
                </table>
            </div>

            <!-- Bloco: Formulários aguardando material -->
            <div class="card">
                <div class="card-header header-forms">
                    Formularios aguardando material
                    <span class="badge">{len(forms_aguardando)}</span>
                </div>
                <table>
                    <tr>
                        <th>Nome</th>
                        <th>Camera</th>
                        <th>Conteudo</th>
                        <th>Prioridade</th>
                        <th>Operador</th>
                        <th>Ha quanto tempo</th>
                    </tr>
                    {linhas_forms}
                </table>
            </div>

            <!-- Bloco: Matches recentes (ocupa largura total) -->
            <div class="card card-full">
                <div class="card-header header-matches">
                    Matches recentes (ultimos 10)
                    <span class="badge">{len(matches_recentes)}</span>
                </div>
                <table>
                    <tr>
                        <th>Volume / Item</th>
                        <th>Camera</th>
                        <th>ID do Formulario</th>
                        <th>Recebido ha</th>
                    </tr>
                    {linhas_matches}
                </table>
            </div>

            <!-- Bloco: Aguardando confirmacao humana (match ambiguo — ocupa largura total) -->
            <!-- O Matcher nao conseguiu casar automaticamente porque havia dois ou mais    -->
            <!-- candidatos com pontuacoes muito proximas. O operador escolhe aqui.        -->
            <div class="card card-full">
                <div class="card-header header-confirmacao">
                    Aguardando confirmacao
                    <span class="badge" style="background:#fce4ec;color:#c0392b">{len(aguardando_confirmacao)}</span>
                </div>
                <div style="padding:12px 16px">
                    {blocos_confirmacao}
                </div>
            </div>
        </div>

        <p class="rodape">
            GMA Camada 1 &mdash; Atualiza automaticamente a cada 5 segundos &mdash;
            <a href="/status" style="color:#adb5bd">JSON de status</a>
        </p>
    </main>
</body>
</html>"""

    return pagina_html, 200, {"Content-Type": "text/html; charset=utf-8"}


# ═══════════════════════════════════════════════════════════════════════════════
# TELAS "UMA FONTE → TRÊS VISTAS"  (integração Camada 1 ↔ Camada 3)
#
# O coração do GMA: um só banco (gma.db) alimenta três telas diferentes.
#   • Aba OPERAÇÃO        → "/"          painel do operador (já existia)
#   • Aba ACOMPANHAMENTO  → "/kanban"    cartões andando pelas colunas + post-its
#   • Aba PLANILHA        → "/planilha"  espelho local da entrega (vira o Sheets)
#
# Kanban e Planilha leem DIRETO do banco (Camada 3). O post-it grava de volta no
# banco (coluna 'observacoes' da tabela cartoes). Assim dá para testar ao vivo a
# integração: um cartão entra pela Camada 1 e aparece aqui; um post-it escrito
# aqui fica gravado na fonte única, visível em todas as telas.
# ═══════════════════════════════════════════════════════════════════════════════

# CSS da barra de abas — compartilhado pelas três telas (entra também no painel).
# String normal (não f-string): as chaves { } abaixo são CSS literal.
CSS_ABAS = """
    .abas { display:flex; gap:4px; background:#16213e; padding:0 24px; }
    .aba {
        padding:11px 20px; color:#aeb8d0; text-decoration:none;
        font-size:0.9em; font-weight:600; border-bottom:3px solid transparent;
    }
    .aba:hover { color:#ffffff; }
    .aba.ativa { color:#ffffff; border-bottom-color:#27ae60; background:#1a1a2e; }
"""


def barra_abas(ativa):
    """Barra de navegação entre as telas. 'ativa' = ficha|operacao|kanban|planilha."""
    def classe(nome):
        return "aba ativa" if nome == ativa else "aba"
    return f"""
    <nav class="abas">
        <a class="{classe('ficha')}" href="/ficha">Nova Ficha</a>
        <a class="{classe('operacao')}" href="/">Operação</a>
        <a class="{classe('kanban')}" href="/kanban">Acompanhamento</a>
        <a class="{classe('planilha')}" href="/planilha">Planilha de Entrega</a>
    </nav>"""


def _esc(valor):
    """Escapa texto para HTML (evita que um post-it com < > quebre a página)."""
    return html.escape(str(valor)) if valor is not None else ""


def _fmt_tamanho(num_bytes):
    """Formata um número de bytes em algo legível (KB/MB/GB)."""
    try:
        tamanho = float(num_bytes or 0)
    except (TypeError, ValueError):
        return "—"
    if tamanho <= 0:
        return "—"
    for unidade in ("B", "KB", "MB", "GB", "TB"):
        if tamanho < 1024:
            return f"{tamanho:.1f} {unidade}"
        tamanho /= 1024
    return f"{tamanho:.1f} PB"


# Colunas do Kanban (chave · rótulo · cor). O card "anda" da esquerda p/ direita.
COLUNAS_KANBAN = [
    ("detectado",  "Detectado",  "#6c757d"),
    ("match",      "Match",      "#2196f3"),
    ("copiando",   "Copiando",   "#f59e0b"),
    ("verificado", "Verificado", "#0ea5e9"),
    ("concluido",  "Concluído",  "#27ae60"),
]

# De cada status real do banco para a coluna onde o card deve aparecer.
STATUS_PARA_COLUNA = {
    "detectado":              "detectado",
    "aguardando_match":       "detectado",
    # Cartão sem mídia (conteúdo trivial — config/sistema, ex.: XMLs de framelines ARRI):
    # aparece em "Detectado" como fim de linha explícito, badge laranja "sem mídia — ignorado".
    "sem_midia":              "detectado",
    # Cartão com arquivos não reconhecidos como mídia mas de tamanho suspeito:
    # pode ser footage num formato não mapeado na lista EXTENSOES. Aparece em "Detectado"
    # com badge vermelho "verificar — arquivos não reconhecidos" para o operador conferir.
    # NÃO entra no Matcher nem na Transferência automática.
    "revisar":                "detectado",
    "matched":                "match",
    "aguardando_confirmacao": "match",
    "copiando":               "copiando",
    "falhou":                 "copiando",
    "transferencia_ok":       "verificado",
    "verificado_parashoot":   "verificado",
    "verificacao_falhou":     "verificado",
    "erase_falhou":           "verificado",
    "concluido":              "concluido",
}


def _pagina(titulo, aba, corpo, head_extra=""):
    """Molde HTML comum das telas novas (Kanban e Planilha): header + abas + corpo."""
    hora = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>GMA — {titulo}</title>
    <style>
        * {{ box-sizing:border-box; margin:0; padding:0; }}
        body {{ font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
                background:#f0f2f5; color:#1a1a1a; font-size:14px; }}
        header {{ background:#1a1a2e; color:#fff; padding:14px 24px;
                  display:flex; justify-content:space-between; align-items:center; }}
        header h1 {{ font-size:1.2em; font-weight:600; letter-spacing:0.5px; }}
        header .info {{ font-size:0.85em; opacity:0.75; }}
        {CSS_ABAS}
        main {{ padding:20px 24px; max-width:1320px; margin:0 auto; }}
        .legenda {{ color:#6c757d; font-size:0.9em; margin-bottom:16px; line-height:1.5; }}
        .vazio, .coluna-vazia {{ color:#adb5bd; text-align:center; padding:18px; font-size:0.85em; }}
        /* ── Kanban ── */
        .kanban {{ display:grid; grid-template-columns:repeat(5,1fr); gap:12px; align-items:start; }}
        .coluna {{ background:#e9edf2; border-radius:8px; overflow:hidden; }}
        .coluna-head {{ padding:10px 12px; font-weight:700; font-size:0.85em; background:#fff;
                        display:flex; justify-content:space-between; align-items:center; }}
        .contador {{ background:#e9ecef; color:#495057; border-radius:12px;
                     padding:1px 9px; font-size:0.9em; }}
        .coluna-corpo {{ padding:10px; display:flex; flex-direction:column; gap:10px; min-height:40px; }}
        .card-kanban {{ background:#fff; border-radius:6px; box-shadow:0 1px 3px rgba(0,0,0,0.1); padding:10px; }}
        .card-titulo {{ font-weight:700; font-size:0.95em; }}
        .card-meta {{ color:#6c757d; font-size:0.82em; margin:3px 0 7px; }}
        .card-badges {{ display:flex; gap:5px; flex-wrap:wrap; margin-bottom:8px; }}
        .badge-status {{ color:#fff; border-radius:10px; padding:1px 8px; font-size:0.72em; font-weight:700; }}
        .selo-alerta {{ background:#f59e0b; color:#fff; border-radius:10px; padding:1px 8px; font-size:0.72em; font-weight:700; }}
        .postit-form {{ display:flex; flex-direction:column; gap:5px; }}
        .postit {{ width:100%; min-height:46px; border:1px solid #ffe08a; background:#fffbea;
                   border-radius:5px; padding:6px; font-family:inherit; font-size:0.82em; resize:vertical; }}
        .btn-postit {{ align-self:flex-end; background:#27ae60; color:#fff; border:none;
                       border-radius:5px; padding:4px 14px; font-weight:600; font-size:0.8em; cursor:pointer; }}
        /* ── Planilha ── */
        .filtro {{ width:100%; max-width:360px; padding:8px 12px; border:1px solid #ced4da;
                   border-radius:6px; margin-bottom:14px; font-size:0.9em; }}
        .planilha-tabela {{ width:100%; border-collapse:collapse; background:#fff; border-radius:8px;
                            overflow:hidden; box-shadow:0 1px 4px rgba(0,0,0,0.08); font-size:0.86em; }}
        .planilha-tabela th {{ text-align:left; padding:9px 12px; background:#f8f9fa; color:#6c757d;
                               text-transform:uppercase; font-size:0.78em; letter-spacing:0.4px;
                               border-bottom:1px solid #dee2e6; }}
        .planilha-tabela td {{ padding:9px 12px; border-bottom:1px solid #f1f3f5; }}
        .planilha-tabela tr:hover td {{ background:#f8f9fa; }}
        .mono {{ font-family:ui-monospace,Menlo,monospace; font-size:0.92em; color:#495057; }}
    </style>
    {head_extra}
</head>
<body>
    <header>
        <h1>GMA — {titulo}</h1>
        <span class="info">Atualizado: {hora}</span>
    </header>
    {barra_abas(aba) if _host_local() else ''}
    <main>{corpo}</main>
</body>
</html>"""


def _card_kanban(cartao):
    """HTML de um card do Kanban a partir de uma linha da tabela cartoes."""
    titulo = cartao["numero_cartao"] or cartao["volume"] or f"Cartão {cartao['id']}"
    status = cartao["status"] or ""

    # Cores do badge de status:
    #   vermelho escuro → qualquer falha técnica (transferência, verificação)
    #   vermelho vivo   → "revisar": conteúdo não reconhecido mas suspeito de footage;
    #                     exige atenção IMEDIATA do operador — não pode ser ignorado
    #   laranja         → "sem_midia": conteúdo trivial confirmado (config/sistema);
    #                     fim de linha explícito, não é erro mas chama atenção
    #   cinza           → estado normal de espera no fluxo
    if "falh" in status:
        cor_status = "#c0392b"   # vermelho escuro — falha técnica
    elif status == "revisar":
        cor_status = "#e74c3c"   # vermelho vivo — operador DEVE verificar
    elif status == "sem_midia":
        cor_status = "#e67e22"   # laranja — ignorado com segurança
    else:
        cor_status = "#6c757d"   # cinza — espera normal

    # Rótulo legível para o badge — traduz os status internos para texto claro
    if status == "sem_midia":
        rotulo_status = "sem mídia — ignorado"
    elif status == "revisar":
        rotulo_status = "verificar — arquivos não reconhecidos"
    else:
        rotulo_status = status

    meta = " · ".join(p for p in [cartao["marca_camera"], cartao["tipo_material"]] if p)

    selo_multidia = "<span class='selo-alerta'>multi-dia</span>" if cartao["alerta_multidia"] else ""
    obs = cartao["observacoes"] or ""

    return f"""
        <div class="card-kanban">
            <div class="card-titulo">{_esc(titulo)}</div>
            <div class="card-meta">{_esc(meta) or '—'}</div>
            <div class="card-badges">
                <span class="badge-status" style="background:{cor_status}">{_esc(rotulo_status) or '—'}</span>
                {selo_multidia}
            </div>
            <form class="postit-form" action="/cartao/{cartao['id']}/observacao" method="post">
                <textarea name="observacao" class="postit" placeholder="post-it: observação livre…">{_esc(obs)}</textarea>
                <button type="submit" class="btn-postit">Salvar</button>
            </form>
        </div>"""


CSS_QR = """
    .qr-painel { background:#fff; border-radius:8px; box-shadow:0 1px 4px rgba(0,0,0,0.08);
                 padding:16px 18px; margin-bottom:18px; max-width:300px;
                 display:inline-flex; flex-direction:column; align-items:center; gap:8px;
                 vertical-align:top; }
    .qr-titulo { font-weight:700; color:#1a1a2e; font-size:0.95em; align-self:flex-start; }
    .qr-img { width:200px; height:200px; image-rendering:pixelated; }
    .qr-link a { color:#2196f3; text-decoration:none; font-size:0.82em; word-break:break-all;
                 text-align:center; }
    .qr-senha { font-size:0.85em; color:#495057; }
    .qr-dica { font-size:0.78em; color:#adb5bd; text-align:center; }
    .qr-aviso { font-size:0.8em; color:#adb5bd; }
"""


def _qr_data_uri(texto, scale=5):
    """Gera o QR como data-URI SVG (embute na página, sem arquivo nem serviço externo)."""
    if not (SEGNO_DISPONIVEL and texto):
        return None
    try:
        return segno.make(texto, error="m").svg_data_uri(scale=scale, border=2)
    except Exception as erro:
        logger.error(f"QR | Erro ao gerar QR | {erro}")
        return None


# Cache curto da URL descoberta do ngrok (evita consultar a API a cada refresh).
_cache_link_ficha = {"url": None, "ts": 0.0}


def _descobrir_link_ficha():
    """
    Descobre o link público da ficha, nesta ordem de prioridade:
      1. GMA_LINK_FICHA no ambiente (override manual — ex.: domínio fixo).
      2. AUTO: pergunta à API local do ngrok (127.0.0.1:4040) qual é a URL ativa
         e monta <url>/ficha. Assim, quando o ngrok reinicia e muda de endereço,
         o QR se atualiza sozinho — sem editar o .env.
      3. None, se não houver túnel nem override.
    """
    # 1) override manual sempre vence
    manual = os.environ.get("GMA_LINK_FICHA", "").strip()
    if manual:
        return manual

    # 2) auto-detecção via ngrok (com cache de ~20s)
    import time
    agora = time.time()
    if _cache_link_ficha["url"] and (agora - _cache_link_ficha["ts"] < 20):
        return _cache_link_ficha["url"]

    url = None
    try:
        import urllib.request
        resposta = urllib.request.urlopen("http://127.0.0.1:4040/api/tunnels", timeout=1.5)
        dados = json.loads(resposta.read().decode("utf-8"))
        for tunel in dados.get("tunnels", []):
            if tunel.get("proto") == "https":
                url = tunel["public_url"].rstrip("/") + "/ficha"
                break
    except Exception:
        url = None  # ngrok parado / sem API → sem link (painel mostra aviso)

    _cache_link_ficha["url"] = url
    _cache_link_ficha["ts"] = agora
    return url


def _painel_qr_ficha():
    """
    Painel com o QR Code do link público da ficha (para os câmeras escanearem).
    O link é resolvido por _descobrir_link_ficha() (override manual OU auto-detecção
    do ngrok). Sem túnel no ar nem override, mostra um aviso curto em vez do QR.
    """
    link = _descobrir_link_ficha()
    if not link:
        return """
        <div class="qr-painel">
          <div class="qr-titulo">📷 Ficha para os câmeras</div>
          <div class="qr-aviso">Suba o túnel (ngrok) que o QR aparece sozinho —
             ou defina <b>GMA_LINK_FICHA</b> no <code>.env</code> (domínio fixo).</div>
        </div>"""

    data_uri = _qr_data_uri(link, scale=5)
    senha = os.environ.get("GMA_SENHA", "").strip()
    nota_senha = f'<div class="qr-senha">senha: <b>{_esc(senha)}</b></div>' if senha else ""
    if data_uri:
        img = f'<img class="qr-img" src="{data_uri}" alt="QR da ficha">'
    else:
        img = '<div class="qr-aviso">(gerador de QR indisponível — instale o segno)</div>'
    return f"""
    <div class="qr-painel">
      <div class="qr-titulo">📷 Ficha para os câmeras</div>
      {img}
      <div class="qr-link"><a href="{_esc(link)}" target="_blank">{_esc(link)}</a></div>
      {nota_senha}
      <div class="qr-dica">Aponte a câmera do celular para o QR para preencher a ficha.</div>
    </div>"""


@app.route("/kanban", methods=["GET"])
def kanban():
    """
    Aba ACOMPANHAMENTO — o Quadro de Acompanhamento (Acesso 2).

    Lê os cartões direto do banco (fonte única) e os distribui em colunas
    conforme o status. Cada card tem um post-it que grava de volta no banco.
    Mostra também o QR Code do link da ficha (para os câmeras escanearem).
    """
    if not BANCO_DISPONIVEL:
        corpo = "<p class='vazio'>Banco de dados indisponível.</p>"
        return _pagina("Acompanhamento", "kanban", corpo), 200, {"Content-Type": "text/html; charset=utf-8"}

    try:
        conn = bd.obter_conexao()
        cartoes = conn.execute("SELECT * FROM cartoes ORDER BY id DESC").fetchall()
        conn.close()
    except Exception as erro:
        logger.error(f"KANBAN | Erro ao ler cartões | {erro}")
        cartoes = []

    # Distribui cada cartão na coluna certa conforme o status
    baldes = {chave: [] for chave, _, _ in COLUNAS_KANBAN}
    for cartao in cartoes:
        coluna = STATUS_PARA_COLUNA.get(cartao["status"], "detectado")
        baldes[coluna].append(cartao)

    # Monta as 5 colunas
    colunas_html = ""
    for chave, rotulo, cor in COLUNAS_KANBAN:
        cards = baldes[chave]
        cards_html = "".join(_card_kanban(c) for c in cards)
        if not cards_html:
            cards_html = "<p class='coluna-vazia'>—</p>"
        colunas_html += f"""
        <div class="coluna">
            <div class="coluna-head" style="border-top:3px solid {cor}">
                <span>{rotulo}</span><span class="contador">{len(cards)}</span>
            </div>
            <div class="coluna-corpo">{cards_html}</div>
        </div>"""

    corpo = f"""
    <p class="legenda">Cada cartão é um card; ele anda da esquerda para a direita conforme o status muda no banco.
       Escreva um post-it em qualquer card e clique em <strong>Salvar</strong> — fica gravado na fonte única.</p>
    {_painel_qr_ficha()}
    <div class="kanban">{colunas_html}</div>"""

    # Auto-refresh de 8s para ver os cards andando — mas pausa enquanto você
    # estiver escrevendo um post-it (não recarrega e perde o texto).
    head_extra = f"<style>{CSS_QR}</style>" + """<script>
      document.addEventListener('DOMContentLoaded', function() {
        var timer = setTimeout(function(){ location.reload(); }, 8000);
        document.querySelectorAll('textarea').forEach(function(el){
          el.addEventListener('focus', function(){ clearTimeout(timer); });
        });
      });
    </script>"""
    return _pagina("Acompanhamento", "kanban", corpo, head_extra), 200, {"Content-Type": "text/html; charset=utf-8"}


@app.route("/cartao/<int:cartao_id>/observacao", methods=["POST"])
def salvar_observacao(cartao_id):
    """
    Grava o post-it (observação livre) de um cartão na fonte única (gma.db),
    na coluna 'observacoes' da tabela cartoes. A função atualizar_cartao já
    registra o evento de auditoria. Depois volta para o Kanban.
    """
    texto = (request.form.get("observacao") or "").strip()
    if BANCO_DISPONIVEL:
        try:
            conn = bd.obter_conexao()
            bd.atualizar_cartao(conn, cartao_id, {"observacoes": texto})
            conn.close()
            logger.info(f"POST-IT | Cartão {cartao_id} | observação salva no banco")
        except Exception as erro:
            logger.error(f"POST-IT | Erro ao salvar no cartão {cartao_id} | {erro}")
    return redirect("/kanban")


@app.route("/planilha", methods=["GET"])
def planilha():
    """
    Aba PLANILHA — a Planilha de Análise / Entrega (Acesso 3), versão local.

    É o espelho do que vai para o Google Sheets (Camada 3): só metadados, nunca
    a mídia. Lê do banco juntando cartão + formulário (pelo match mais recente).
    """
    if not BANCO_DISPONIVEL:
        corpo = "<p class='vazio'>Banco de dados indisponível.</p>"
        return _pagina("Planilha de Entrega", "planilha", corpo), 200, {"Content-Type": "text/html; charset=utf-8"}

    try:
        conn = bd.obter_conexao()
        linhas = conn.execute("""
            SELECT c.id, c.numero_cartao, c.volume, c.marca_camera, c.tipo_material,
                   c.status, c.total_arquivos_transferidos, c.tamanho_transferido_bytes,
                   c.destino_pasta,
                   f.nome AS prof_nome, f.data_gravacao
            FROM cartoes c
            LEFT JOIN matches m ON m.id = (
                SELECT id FROM matches WHERE cartao_id = c.id ORDER BY id DESC LIMIT 1
            )
            LEFT JOIN formularios f ON f.id = m.formulario_id
            ORDER BY c.id DESC
        """).fetchall()
        conn.close()
    except Exception as erro:
        logger.error(f"PLANILHA | Erro ao ler | {erro}")
        linhas = []

    linhas_html = ""
    for linha in linhas:
        # Profissional: nome do formulário; senão deriva do número (JOE_001 → JOE)
        profissional = linha["prof_nome"]
        if not profissional and linha["numero_cartao"]:
            profissional = linha["numero_cartao"].rsplit("_", 1)[0]

        n_arquivos = linha["total_arquivos_transferidos"]
        n_arquivos = n_arquivos if n_arquivos is not None else "—"

        linhas_html += f"""
        <tr>
            <td>{_esc(profissional) or '—'}</td>
            <td>{_esc(linha['marca_camera']) or '—'}</td>
            <td>{_esc(linha['tipo_material']) or '—'}</td>
            <td>{_esc(linha['data_gravacao']) or '—'}</td>
            <td>{_esc(linha['numero_cartao']) or '—'}</td>
            <td>{n_arquivos}</td>
            <td>{_fmt_tamanho(linha['tamanho_transferido_bytes'])}</td>
            <td>{_esc(linha['status']) or '—'}</td>
            <td class="mono">{_esc(linha['destino_pasta']) or '—'}</td>
        </tr>"""

    if not linhas_html:
        linhas_html = "<tr><td colspan='9' class='coluna-vazia'>Nenhum cartão no banco ainda.</td></tr>"

    corpo = f"""
    <p class="legenda">Espelho local da entrega — é o que vai para o Google Sheets (só informação, nunca o vídeo).
       Mesma fonte que alimenta as outras telas.</p>
    <input type="text" id="filtro" class="filtro" placeholder="filtrar… (profissional, câmera, status)">
    <table class="planilha-tabela" id="tabela">
        <thead><tr>
            <th>Profissional</th><th>Câmera</th><th>Tipo</th><th>Data</th>
            <th>Nº cartão</th><th>Nº arquivos</th><th>Tamanho</th>
            <th>Status</th><th>Caminho no HD</th>
        </tr></thead>
        <tbody>{linhas_html}</tbody>
    </table>"""

    head_extra = """<script>
      document.addEventListener('DOMContentLoaded', function() {
        var filtro = document.getElementById('filtro');
        if (!filtro) return;
        filtro.addEventListener('input', function() {
          var termo = this.value.toLowerCase();
          document.querySelectorAll('#tabela tbody tr').forEach(function(tr) {
            tr.style.display = tr.textContent.toLowerCase().indexOf(termo) >= 0 ? '' : 'none';
          });
        });
      });
    </script>"""
    return _pagina("Planilha de Entrega", "planilha", corpo, head_extra), 200, {"Content-Type": "text/html; charset=utf-8"}


# ── ROTA: FICHA DE CHECK-IN (tela de inserção local) ─────────────────────────
# Esta é a "tela de inserção de informações" do GMA: uma página de formulário
# servida pelo próprio Flask (offline-first). O operador/profissional preenche
# direto no navegador (computador da base ou celular via rede local/ngrok) e o
# envio cai na MESMA função central usada pelos webhooks do Google Forms/Tally.
#
# É só uma porta de entrada nova — não muda nada do schema nem do processamento.

# Opções dos campos de seleção (espelham o guia_tally_gma.md / campos editoriais)
OPCOES_TIPO_MATERIAL = ["VIDEO", "FOTO", "AUDIO"]
OPCOES_TIPO_CONTEUDO = [
    "B-ROLL", "ENTREVISTA", "PALCO", "COBERTURA",
    "ABERTURA", "ENCERRAMENTO", "OUTRO",
]
OPCOES_PRIORIDADE = ["NORMAL", "URGENTE"]

CSS_FICHA = """
    .ficha-form { background:#fff; border-radius:8px; box-shadow:0 1px 4px rgba(0,0,0,0.08);
                  padding:22px 24px; max-width:680px; }
    .ficha-grid { display:grid; grid-template-columns:1fr 1fr; gap:14px 18px; }
    .campo { display:flex; flex-direction:column; gap:5px; }
    .campo.largo { grid-column:1 / -1; }
    .campo label { font-size:0.82em; font-weight:700; color:#495057; }
    .campo .estrela { color:#c0392b; }
    .campo .ajuda { font-weight:400; color:#adb5bd; font-size:0.92em; }
    .campo input, .campo select, .campo textarea {
        padding:9px 11px; border:1px solid #ced4da; border-radius:6px;
        font-family:inherit; font-size:0.95em; background:#fff; }
    .campo textarea { min-height:64px; resize:vertical; }
    .grupo-titulo { grid-column:1 / -1; font-size:0.78em; font-weight:700; color:#adb5bd;
                    text-transform:uppercase; letter-spacing:0.5px; margin-top:8px;
                    border-top:1px solid #f1f3f5; padding-top:14px; }
    .ficha-acoes { margin-top:20px; display:flex; gap:12px; align-items:center; }
    .btn-enviar { background:#27ae60; color:#fff; border:none; border-radius:6px;
                  padding:11px 28px; font-weight:700; font-size:0.95em; cursor:pointer; }
    .btn-enviar:hover { background:#229954; }
    .erro-box { background:#fdecea; border:1px solid #f5c6cb; color:#c0392b;
                border-radius:6px; padding:11px 14px; margin-bottom:16px; font-size:0.9em; }
    .ok-box { background:#eafaf1; border:1px solid #abebc6; color:#1e8449;
              border-radius:8px; padding:20px 24px; max-width:680px; }
    .ok-box h2 { font-size:1.15em; margin-bottom:10px; }
    .ok-box .resumo { background:#fff; border-radius:6px; padding:12px 16px; margin:12px 0;
                      color:#1a1a1a; font-size:0.92em; line-height:1.7; }
    .ok-box .resumo b { display:inline-block; min-width:120px; color:#6c757d; font-weight:600; }
    .btn-secundario { display:inline-block; background:#1a1a2e; color:#fff; text-decoration:none;
                      border-radius:6px; padding:10px 20px; font-weight:600; font-size:0.9em; }
    .dica-gabarito { font-weight:400; color:#adb5bd; font-size:0.88em; }
    .campo input:disabled, .campo select:disabled {
        background:#f1f3f5; color:#868e96; cursor:not-allowed; }
    .aviso-trava { background:#fff8e1; border:1px solid #ffe08a; color:#8a6d3b;
                   border-radius:6px; padding:10px 14px; margin-bottom:14px; font-size:0.88em; }
    /* ── Lista de fichas recentes (editar) ── */
    .recentes { margin-top:30px; max-width:880px; }
    .recentes h2 { font-size:1em; color:#495057; margin-bottom:10px; }
    .tab-recentes { width:100%; border-collapse:collapse; background:#fff; border-radius:8px;
                    overflow:hidden; box-shadow:0 1px 4px rgba(0,0,0,0.08); font-size:0.86em; }
    .tab-recentes th { text-align:left; padding:8px 12px; background:#f8f9fa; color:#6c757d;
                       text-transform:uppercase; font-size:0.76em; letter-spacing:0.4px;
                       border-bottom:1px solid #dee2e6; }
    .tab-recentes td { padding:8px 12px; border-bottom:1px solid #f1f3f5; }
    .tab-recentes tr:hover td { background:#f8f9fa; }
    .badge-mini { border-radius:10px; padding:1px 8px; font-size:0.74em; font-weight:700; color:#fff; }
    .link-editar { color:#2196f3; text-decoration:none; font-weight:600; }
    .link-editar:hover { text-decoration:underline; }
"""


def _opcoes_select(lista, selecionado=""):
    """Monta os <option> de um <select>, marcando o valor previamente escolhido."""
    partes = []
    for valor in lista:
        sel = " selected" if valor == selecionado else ""
        partes.append(f'<option value="{_esc(valor)}"{sel}>{_esc(valor)}</option>')
    return "".join(partes)


# Status da ficha em que ainda é SEGURO editar os campos críticos (nome/câmera/
# tipo/data): só enquanto ela não casou com material. Depois de 'matched' esses
# campos guiam a numeração e a pasta de destino — travamos por segurança.
STATUS_FICHA_LIVRE = {"aguardando_material", "aguardando_match", "", None}

# Cores por status para o selo da lista de fichas recentes.
COR_STATUS_FICHA = {
    "aguardando_material": "#6c757d",
    "aguardando_match":    "#6c757d",
    "matched":             "#2196f3",
}


def _sugestoes_gabarito():
    """
    Lê do banco os valores já usados (nomes, câmeras, modelos) para alimentar o
    'gabarito': dropdowns selecionáveis que aprendem com o histórico. Quanto mais
    o sistema é usado, mais ele sugere. Nunca trava — se o banco falhar, devolve
    listas vazias e a ficha continua sendo de digitação livre.
    """
    vazio = {"nomes": [], "cameras": [], "modelos": []}
    if not BANCO_DISPONIVEL:
        return vazio
    try:
        conn = bd.obter_conexao()
        def distintos(coluna):
            linhas = conn.execute(
                f"SELECT DISTINCT {coluna} FROM formularios "
                f"WHERE {coluna} IS NOT NULL AND TRIM({coluna}) <> '' "
                f"ORDER BY {coluna}"
            ).fetchall()
            return [linha[0] for linha in linhas]
        sugestoes = {
            "nomes":   distintos("nome"),
            "cameras": distintos("camera"),
            "modelos": distintos("modelo_camera"),
        }
        conn.close()
        return sugestoes
    except Exception as erro:
        logger.error(f"FICHA | Erro ao montar sugestões do gabarito | {erro}")
        return vazio


def _datalist(id_lista, valores):
    """Monta um <datalist> (dropdown selecionável que também aceita digitação)."""
    opcoes = "".join(f'<option value="{_esc(v)}">' for v in valores)
    return f'<datalist id="{id_lista}">{opcoes}</datalist>'


def _fichas_recentes_html(limite=12):
    """Tabela das fichas mais recentes, cada uma com um link para editar."""
    if not BANCO_DISPONIVEL:
        return ""
    try:
        conn = bd.obter_conexao()
        fichas = conn.execute(
            "SELECT id, nome, camera, tipo_material, data_gravacao, status "
            "FROM formularios ORDER BY id DESC LIMIT ?", (limite,)
        ).fetchall()
        conn.close()
    except Exception as erro:
        logger.error(f"FICHA | Erro ao listar fichas recentes | {erro}")
        return ""

    if not fichas:
        return ""

    linhas = []
    for f in fichas:
        status = f["status"] or ""
        cor = COR_STATUS_FICHA.get(status, "#495057")
        linhas.append(f"""
          <tr>
            <td class="mono">{f['id']}</td>
            <td><b>{_esc(f['nome'])}</b></td>
            <td>{_esc(f['camera'])}</td>
            <td>{_esc(f['tipo_material'])}</td>
            <td class="mono">{_esc(f['data_gravacao'])}</td>
            <td><span class="badge-mini" style="background:{cor}">{_esc(status) or '—'}</span></td>
            <td><a class="link-editar" href="/ficha/{f['id']}/editar">editar ✎</a></td>
          </tr>""")
    return f"""
    <div class="recentes">
      <h2>Fichas recentes (clique para editar)</h2>
      <table class="tab-recentes">
        <thead><tr><th>#</th><th>Nome</th><th>Câmera</th><th>Tipo</th>
                   <th>Data</th><th>Status</th><th></th></tr></thead>
        <tbody>{''.join(linhas)}</tbody>
      </table>
    </div>"""


def _html_ficha(dados=None, erro=None, modo="nova", ficha_id=None,
                bloquear_criticos=False, mostrar_recentes=True):
    """
    Monta o HTML do formulário de check-in.

    modo="nova"   → cria uma ficha (action /ficha).
    modo="editar" → edita a ficha ficha_id (action /ficha/<id>/editar).
    bloquear_criticos → trava nome/câmera/tipo/data (ficha já casou: mexer aqui
                        afeta numeração/pasta de destino — segurança dos arquivos).
    """
    d = dados or {}
    sug = _sugestoes_gabarito()
    editando = (modo == "editar")
    action = f"/ficha/{ficha_id}/editar" if editando else "/ficha"
    bloco_erro = f'<div class="erro-box">⚠️ {_esc(erro)}</div>' if erro else ""

    # Atributo HTML que desabilita os campos críticos quando a ficha já casou.
    trava = " disabled" if bloquear_criticos else ""
    aviso_trava = (
        '<div class="aviso-trava">🔒 Esta ficha já casou com material. Nome, câmera, '
        'tipo e data ficam travados (mexer aqui afetaria a numeração e a pasta no HD). '
        'Você ainda pode ajustar os campos editoriais abaixo.</div>'
        if bloquear_criticos else ""
    )

    if editando:
        legenda = ('Edite os dados desta ficha. Campos com '
                   '<span style="color:#c0392b">★</span> são obrigatórios.')
        texto_botao = "Salvar alterações"
    else:
        legenda = ('Preencha a ficha do cartão que chegou na base. Campos com '
                   '<span style="color:#c0392b">★</span> são obrigatórios. Nome e câmera '
                   'já sugerem valores usados antes — é só escolher ou digitar um novo.')
        texto_botao = "Enviar ficha"

    corpo = f"""
    <p class="legenda">{legenda}</p>
    {bloco_erro}
    {aviso_trava}
    <form class="ficha-form" action="{action}" method="post">
      {_datalist('lista_nomes', sug['nomes'])}
      {_datalist('lista_cameras', sug['cameras'])}
      {_datalist('lista_modelos', sug['modelos'])}
      <div class="ficha-grid">
        <div class="campo">
          <label>Nome <span class="estrela">★</span> <span class="dica-gabarito">(escolha ou digite)</span></label>
          <input type="text" name="nome" list="lista_nomes" value="{_esc(d.get('nome',''))}"
                 required autofocus placeholder="ex: JOÃO"{trava}>
        </div>
        <div class="campo">
          <label>Câmera <span class="estrela">★</span> <span class="dica-gabarito">(escolha ou digite)</span></label>
          <input type="text" name="camera" list="lista_cameras" value="{_esc(d.get('camera',''))}"
                 required placeholder="ex: Sony, GoPro, Nikon"{trava}>
        </div>
        <div class="campo">
          <label>Tipo de material <span class="estrela">★</span></label>
          <select name="tipo_material" required{trava}>
            <option value="">— escolha —</option>
            {_opcoes_select(OPCOES_TIPO_MATERIAL, d.get('tipo_material',''))}
          </select>
        </div>
        <div class="campo">
          <label>Data de gravação <span class="estrela">★</span></label>
          <input type="date" name="data_gravacao" value="{_esc(d.get('data_gravacao',''))}" required{trava}>
        </div>

        <div class="grupo-titulo">Opcionais (ajudam o sistema e os editores)</div>

        <div class="campo">
          <label>Operador <span class="ajuda">(quem fez o check-in)</span></label>
          <input type="text" name="operador" value="{_esc(d.get('operador',''))}" placeholder="opcional">
        </div>
        <div class="campo">
          <label>Modelo da câmera</label>
          <input type="text" name="modelo_camera" list="lista_modelos"
                 value="{_esc(d.get('modelo_camera',''))}" placeholder="ex: FX3, HERO7">
        </div>
        <div class="campo">
          <label>Tipo de conteúdo</label>
          <select name="tipo_conteudo">
            <option value="">— nenhum —</option>
            {_opcoes_select(OPCOES_TIPO_CONTEUDO, d.get('tipo_conteudo',''))}
          </select>
        </div>
        <div class="campo">
          <label>Local / cena</label>
          <input type="text" name="local_cena" value="{_esc(d.get('local_cena',''))}" placeholder="ex: PALCO PRINCIPAL">
        </div>
        <div class="campo">
          <label>Prioridade</label>
          <select name="prioridade">
            {_opcoes_select(OPCOES_PRIORIDADE, d.get('prioridade','') or 'NORMAL')}
          </select>
        </div>
        <div class="campo largo">
          <label>Observações</label>
          <textarea name="observacoes" placeholder="anotações livres sobre o cartão…">{_esc(d.get('observacoes',''))}</textarea>
        </div>
      </div>
      <div class="ficha-acoes">
        <button type="submit" class="btn-enviar">{texto_botao}</button>
        {'<a class="btn-secundario" href="/ficha">Cancelar</a>' if editando else ''}
      </div>
    </form>
    {_fichas_recentes_html() if (mostrar_recentes and not editando) else ''}"""

    head_extra = f"<style>{CSS_FICHA}</style>"
    titulo = "Editar ficha" if editando else "Nova Ficha"
    return _pagina(titulo, "ficha", corpo, head_extra)


def _normalizar_campos_ficha(dados):
    """
    Normaliza os campos de uma ficha no mesmo padrão de _processar_e_salvar_formulario
    (nome em maiúsculas, câmera com inicial maiúscula, etc.). Usado na edição.
    """
    out = {}
    if "nome" in dados:          out["nome"] = dados.get("nome", "").strip().upper()
    if "camera" in dados:        out["camera"] = normalizar_camera(dados.get("camera", ""))
    if "tipo_material" in dados:  out["tipo_material"] = dados.get("tipo_material", "").strip().upper()
    if "data_gravacao" in dados:  out["data_gravacao"] = dados.get("data_gravacao", "").strip()
    if "operador" in dados:       out["operador"] = dados.get("operador", "").strip() or None
    if "modelo_camera" in dados:  out["modelo_camera"] = dados.get("modelo_camera", "").strip() or None
    if "tipo_conteudo" in dados:  out["tipo_conteudo"] = dados.get("tipo_conteudo", "").strip().upper() or None
    if "local_cena" in dados:     out["local_cena"] = dados.get("local_cena", "").strip() or None
    if "prioridade" in dados:     out["prioridade"] = dados.get("prioridade", "NORMAL").strip().upper() or "NORMAL"
    if "observacoes" in dados:    out["observacoes"] = dados.get("observacoes", "").strip() or None
    return out


def _atualizar_json_fila(id_form_original, campos):
    """
    Mantém a fila JSON em sincronia com a edição no banco (o Matcher/Transferência
    leem dos JSONs). Best-effort: se o arquivo não existir, não faz nada.
    """
    if not id_form_original:
        return
    caminho = os.path.join(PASTA_FILA_FORMS, f"form_{id_form_original}.json")
    if not os.path.isfile(caminho):
        return
    try:
        with open(caminho, "r", encoding="utf-8") as f:
            dados_json = json.load(f)
        dados_json.update({k: v for k, v in campos.items()})
        with open(caminho, "w", encoding="utf-8") as f:
            json.dump(dados_json, f, ensure_ascii=False, indent=2)
        logger.info(f"FICHA | Fila JSON sincronizada após edição | {os.path.basename(caminho)}")
    except Exception as erro:
        logger.error(f"FICHA | Erro ao sincronizar fila JSON (banco já atualizado) | {erro}")


@app.route("/ficha", methods=["GET"])
def ficha_formulario():
    """
    Mostra a tela de inserção de informações (formulário de check-in).

    A lista de 'fichas recentes' (com edição) só aparece na BASE (localhost). No
    acesso remoto (link público das câmeras) ela é omitida — o câmera só preenche
    uma ficha nova, nunca vê nem edita as fichas dos outros.
    """
    return _html_ficha(mostrar_recentes=_host_local()), 200, {"Content-Type": "text/html; charset=utf-8"}


@app.route("/ficha", methods=["POST"])
def ficha_enviar():
    """
    Recebe o envio do formulário do navegador (form-encoded), reaproveita a função
    central de validação + gravação + Matcher, e mostra uma tela de confirmação
    (em vez do JSON cru que os webhooks recebem).
    """
    dados = request.form.to_dict()

    # A função central devolve (resposta_json, codigo_http). Reutilizamos toda a
    # lógica testada e só interpretamos o resultado para montar uma tela amigável.
    resposta, codigo = _processar_e_salvar_formulario(dados, origem="FICHA")
    payload = resposta.get_json()

    if not payload.get("ok"):
        # Validação falhou — remostra o formulário com o erro e os valores digitados.
        corpo = _html_ficha(dados=dados, erro=payload.get("erro", "Erro ao salvar a ficha."))
        return corpo, codigo, {"Content-Type": "text/html; charset=utf-8"}

    # Sucesso — tela de confirmação com o resumo do que foi gravado.
    n_matches = payload.get("matches_gerados", 0)
    nota_match = (
        f"<p style='margin-top:8px'>🔗 O Matcher já cruzou e gerou <b>{n_matches}</b> "
        f"match(es) com material na fila.</p>"
        if n_matches else
        "<p style='margin-top:8px'>A ficha ficou aguardando o material do cartão chegar "
        "para o Matcher cruzar.</p>"
    )
    resumo = f"""
      <div class="resumo">
        <div><b>Nome</b> {_esc(payload.get('nome'))}</div>
        <div><b>Câmera</b> {_esc(payload.get('camera'))}</div>
        <div><b>Tipo</b> {_esc(dados.get('tipo_material',''))}</div>
        <div><b>Data</b> {_esc(dados.get('data_gravacao',''))}</div>
        <div><b>ID da ficha</b> <span class="mono">{_esc(payload.get('id_form'))}</span></div>
      </div>"""
    # Botões de gestão (Kanban/Planilha) só na BASE; o link remoto da câmera
    # recebe apenas "preencher outra ficha".
    if _host_local():
        botoes = """
        <a class="btn-secundario" href="/ficha">Preencher outra ficha</a>
        <a class="btn-secundario" href="/kanban">Ver no Acompanhamento</a>
        <a class="btn-secundario" href="/planilha">Ver na Planilha</a>"""
    else:
        botoes = '<a class="btn-secundario" href="/ficha">Preencher outra ficha</a>'
    corpo = f"""
    <div class="ok-box">
      <h2>✅ Ficha recebida com sucesso</h2>
      {resumo}
      {nota_match}
      <div style="margin-top:18px; display:flex; gap:12px;">{botoes}</div>
    </div>"""
    head_extra = f"<style>{CSS_FICHA}</style>"
    return _pagina("Ficha enviada", "ficha", corpo, head_extra), 201, {"Content-Type": "text/html; charset=utf-8"}


def _carregar_ficha(ficha_id):
    """Lê uma ficha do banco como dicionário. Retorna None se não existir."""
    if not BANCO_DISPONIVEL:
        return None
    try:
        conn = bd.obter_conexao()
        linha = conn.execute("SELECT * FROM formularios WHERE id = ?", (ficha_id,)).fetchone()
        conn.close()
        return dict(linha) if linha else None
    except Exception as erro:
        logger.error(f"FICHA | Erro ao carregar ficha {ficha_id} | {erro}")
        return None


@app.route("/ficha/<int:ficha_id>/editar", methods=["GET"])
def ficha_editar_form(ficha_id):
    """Mostra o formulário pré-preenchido para editar uma ficha existente."""
    ficha = _carregar_ficha(ficha_id)
    if ficha is None:
        corpo = ('<div class="erro-box">Ficha não encontrada.</div>'
                 '<a class="btn-secundario" href="/ficha">Voltar</a>')
        return _pagina("Editar ficha", "ficha", corpo, f"<style>{CSS_FICHA}</style>"), 404, \
            {"Content-Type": "text/html; charset=utf-8"}

    bloquear = ficha.get("status") not in STATUS_FICHA_LIVRE
    corpo = _html_ficha(dados=ficha, modo="editar", ficha_id=ficha_id, bloquear_criticos=bloquear)
    return corpo, 200, {"Content-Type": "text/html; charset=utf-8"}


@app.route("/ficha/<int:ficha_id>/editar", methods=["POST"])
def ficha_editar_salvar(ficha_id):
    """
    Salva a edição de uma ficha. Se a ficha já casou, ignora os campos críticos
    (nome/câmera/tipo/data) por segurança — só os editoriais passam.
    """
    ficha = _carregar_ficha(ficha_id)
    if ficha is None:
        corpo = ('<div class="erro-box">Ficha não encontrada.</div>'
                 '<a class="btn-secundario" href="/ficha">Voltar</a>')
        return _pagina("Editar ficha", "ficha", corpo, f"<style>{CSS_FICHA}</style>"), 404, \
            {"Content-Type": "text/html; charset=utf-8"}

    bloquear = ficha.get("status") not in STATUS_FICHA_LIVRE
    enviados = request.form.to_dict()

    # Se os críticos estão travados, descarta-os do que veio (defesa no servidor —
    # não confia só no 'disabled' do HTML).
    if bloquear:
        for campo in ("nome", "camera", "tipo_material", "data_gravacao"):
            enviados.pop(campo, None)

    campos = _normalizar_campos_ficha(enviados)

    # Valida a data só se ela está sendo editada (campo crítico liberado).
    if "data_gravacao" in campos:
        try:
            datetime.strptime(campos["data_gravacao"], "%Y-%m-%d")
        except ValueError:
            dados_reexibir = dict(ficha); dados_reexibir.update(enviados)
            corpo = _html_ficha(
                dados=dados_reexibir, modo="editar", ficha_id=ficha_id,
                bloquear_criticos=bloquear,
                erro=f"Formato de data inválido: '{campos['data_gravacao']}'. Use AAAA-MM-DD.",
            )
            return corpo, 422, {"Content-Type": "text/html; charset=utf-8"}

    # Grava no banco (whitelist na própria função) + sincroniza a fila JSON.
    try:
        conn = bd.obter_conexao()
        bd.atualizar_formulario(conn, ficha_id, campos)
        conn.close()
        _atualizar_json_fila(ficha.get("id_form_original"), campos)
        logger.info(f"FICHA | Ficha {ficha_id} editada | campos={list(campos.keys())}")
    except Exception as erro:
        logger.error(f"FICHA | Erro ao salvar edição da ficha {ficha_id} | {erro}")
        corpo = _html_ficha(
            dados={**ficha, **enviados}, modo="editar", ficha_id=ficha_id,
            bloquear_criticos=bloquear, erro="Erro interno ao salvar. Tente de novo.",
        )
        return corpo, 500, {"Content-Type": "text/html; charset=utf-8"}

    atualizada = _carregar_ficha(ficha_id) or {}
    corpo = f"""
    <div class="ok-box">
      <h2>✅ Ficha #{ficha_id} atualizada</h2>
      <div class="resumo">
        <div><b>Nome</b> {_esc(atualizada.get('nome'))}</div>
        <div><b>Câmera</b> {_esc(atualizada.get('camera'))}</div>
        <div><b>Tipo</b> {_esc(atualizada.get('tipo_material'))}</div>
        <div><b>Data</b> {_esc(atualizada.get('data_gravacao'))}</div>
        <div><b>Prioridade</b> {_esc(atualizada.get('prioridade'))}</div>
      </div>
      <div style="margin-top:18px; display:flex; gap:12px;">
        <a class="btn-secundario" href="/ficha">Voltar às fichas</a>
        <a class="btn-secundario" href="/planilha">Ver na Planilha</a>
      </div>
    </div>"""
    head_extra = f"<style>{CSS_FICHA}</style>"
    return _pagina("Ficha atualizada", "ficha", corpo, head_extra), 200, \
        {"Content-Type": "text/html; charset=utf-8"}


# ── ROTA 3: STATUS JSON DA FILA ───────────────────────────────────────────────

@app.route("/status", methods=["GET"])
def status_fila():
    """
    Retorna um JSON com as contagens atuais das filas.
    Útil para monitoramento externo ou integração com outros scripts.

    Exemplo de resposta:
    {
        "material_aguardando": 2,
        "forms_aguardando": 1,
        "matches_hoje": 5,
        "orfaos": 0,
        "porteiro_ativo": true
    }
    """
    try:
        orfaos = identificar_orfaos()
        total_orfaos = len(orfaos["materiais"]) + len(orfaos["forms"])

        dados_status = {
            "material_aguardando": len(ler_jsons_da_pasta(PASTA_FILA_MATERIAL, "aguardando_match")),
            "forms_aguardando":    len(ler_jsons_da_pasta(PASTA_FILA_FORMS, "aguardando_material")),
            "matches_hoje":        contar_matches_hoje(),
            "orfaos":              total_orfaos,
            "porteiro_ativo":      os.path.isfile(SENTINELA_PORTEIRO),
            "timestamp":           datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        }
        return jsonify(dados_status), 200

    except Exception as erro:
        logger.error(f"STATUS | Erro ao gerar status | {erro}")
        return jsonify({"ok": False, "erro": "Erro interno ao gerar status."}), 500


# ── ROTA 4: ATIVAR E DESATIVAR O PORTEIRO ────────────────────────────────────

@app.route("/porteiro/ativar", methods=["POST"])
def porteiro_ativar():
    """
    Cria o arquivo sentinela .gma_ativo para ligar o Porteiro.
    O Porteiro verifica a existência deste arquivo a cada ciclo de polling.
    """
    try:
        # Cria o arquivo sentinela (equivalente ao comando 'touch .gma_ativo')
        with open(SENTINELA_PORTEIRO, "w") as f:
            f.write(datetime.now().strftime("%Y-%m-%dT%H:%M:%S"))

        logger.info("PORTEIRO | Ativado via painel web")

        # Se a requisição veio de um formulário HTML, redireciona para o painel
        if request.content_type and "application/json" in request.content_type:
            return jsonify({"ok": True, "porteiro_ativo": True}), 200
        else:
            # Redireciona para o painel (botão no HTML)
            from flask import redirect
            return redirect("/")

    except OSError as erro:
        logger.error(f"PORTEIRO | Erro ao criar sentinela | {erro}")
        return jsonify({"ok": False, "erro": "Erro ao ativar o Porteiro."}), 500


@app.route("/porteiro/desativar", methods=["POST"])
def porteiro_desativar():
    """
    Remove o arquivo sentinela .gma_ativo para desligar o Porteiro.
    O Porteiro continua rodando mas para de processar eventos.
    """
    try:
        if os.path.isfile(SENTINELA_PORTEIRO):
            os.remove(SENTINELA_PORTEIRO)
            logger.info("PORTEIRO | Desativado via painel web")
        else:
            logger.info("PORTEIRO | Já estava inativo quando desativar foi chamado")

        # Redireciona para o painel se veio de formulário HTML
        if request.content_type and "application/json" in request.content_type:
            return jsonify({"ok": True, "porteiro_ativo": False}), 200
        else:
            from flask import redirect
            return redirect("/")

    except OSError as erro:
        logger.error(f"PORTEIRO | Erro ao remover sentinela | {erro}")
        return jsonify({"ok": False, "erro": "Erro ao desativar o Porteiro."}), 500


# ── RESOLUÇÃO DE EMPATE (Passo 2 do Matcher) ─────────────────────────────────
#
# Fluxo em 3 etapas:
#   1. Painel (/) — operador vê os candidatos e clica "Confirmar NOME"
#   2. /match/<id>/confirmar (POST) — tela de resumo ANTES de executar
#   3. /match/<id>/iniciar  (POST) — executa de fato, chama confirmar_par_manual
#
# Segurança: estas rotas são ações de operação — só acessíveis na BASE (localhost).
# O portão _portao_de_acesso já bloqueia remoto para qualquer rota fora de /ficha
# e /forms, então /match/* recebe 403 automaticamente no acesso remoto.


def _ler_contador(nome):
    """
    Lê o arquivo contadores/<NOME>.json e retorna o próximo número sequencial
    (sem incrementar — só leitura, para calcular a pasta prevista).

    Retorna um inteiro. Se o arquivo não existir ou tiver erro, retorna 1
    (significando que seria o primeiro cartão deste profissional).
    """
    caminho = os.path.join(RAIZ_GMA, "contadores", f"{nome}.json")
    try:
        with open(caminho, "r", encoding="utf-8") as f:
            dados = json.load(f)
        return int(dados.get("proximo", 1))
    except (OSError, json.JSONDecodeError, ValueError, TypeError):
        return 1


def _pasta_prevista(nome):
    """
    Calcula a pasta de destino prevista para o próximo cartão deste profissional.

    Formato: NOME_NNN (zero-padded com 3 dígitos), ex: JOAO_003.
    Lê o contador atual e usa o número "proximo" — é o que a Camada 2 vai usar
    quando a transferência for de fato iniciada.
    """
    proximo = _ler_contador(nome)
    return f"{nome}_{proximo:03d}"


@app.route("/match/<int:cartao_id>/confirmar", methods=["POST"])
def match_confirmar(cartao_id):
    """
    Tela de resumo antes de executar o match (Passo 3a do desenho).

    Recebe o nome do profissional escolhido (campo 'nome' do form POST).
    Mostra um resumo enxuto — nome, câmera, nº arquivos, pasta prevista —
    e dois botões: "Iniciar transferência" e "Cancelar".

    NAO executa a transferência ainda. Isso evita match errado por clique
    acidental: 1 clique a mais é barato; reverter uma pasta errada no HD é caro.
    """
    nome_escolhido = (request.form.get("nome") or "").strip().upper()
    if not nome_escolhido:
        # Nome vazio — volta ao painel com aviso simples
        return redirect("/?aviso=nome_vazio")

    # Lê os dados do cartão no banco para montar o resumo
    camera_detectada = "—"
    n_arquivos = "?"
    volume = f"Cartao {cartao_id}"

    if BANCO_DISPONIVEL:
        try:
            _conn = bd.obter_conexao()
            linha_cartao = _conn.execute(
                "SELECT volume, marca_camera, total_arquivos_detectados FROM cartoes WHERE id = ?",
                (cartao_id,)
            ).fetchone()
            _conn.close()
            if linha_cartao:
                volume           = linha_cartao["volume"] or volume
                camera_detectada = linha_cartao["marca_camera"] or "—"
                n_arquivos       = linha_cartao["total_arquivos_detectados"] or "?"
        except Exception as _err:
            logger.error(f"MATCH CONFIRMAR | Erro ao ler cartao {cartao_id} do banco | {_err}")

    # Pasta prevista: lê o contador e calcula sem incrementar
    pasta = _pasta_prevista(nome_escolhido)

    # Monta a tela de resumo
    corpo = f"""
    <div style="background:#fff;border-radius:8px;box-shadow:0 1px 4px rgba(0,0,0,0.08);
                padding:24px 28px;max-width:600px;margin:0 auto">
        <h2 style="font-size:1.15em;margin-bottom:16px;color:#1a1a2e">
            Confirmar match — revise antes de iniciar
        </h2>
        <div style="background:#f8f9fa;border-radius:6px;padding:14px 18px;
                    margin-bottom:20px;line-height:2">
            <div>
                <b style="display:inline-block;min-width:140px;color:#6c757d">Profissional</b>
                {_esc(nome_escolhido)}
            </div>
            <div>
                <b style="display:inline-block;min-width:140px;color:#6c757d">Camera detectada</b>
                {_esc(camera_detectada)}
            </div>
            <div>
                <b style="display:inline-block;min-width:140px;color:#6c757d">Numero de arquivos</b>
                {_esc(str(n_arquivos))}
            </div>
            <div>
                <b style="display:inline-block;min-width:140px;color:#6c757d">Pasta de destino</b>
                <span style="font-family:monospace;font-size:1.05em;color:#1a1a2e">{_esc(pasta)}</span>
            </div>
        </div>
        <p style="color:#856404;background:#fff3cd;border:1px solid #ffc107;border-radius:5px;
                  padding:10px 14px;margin-bottom:20px;font-size:0.9em">
            Verifique se o profissional e a pasta estao certos. Um match errado gera
            uma pasta com nome errado no HD — e desfazer durante o evento e trabalhoso.
        </p>
        <div style="display:flex;gap:12px;align-items:center">
            <form action="/match/{cartao_id}/iniciar" method="post">
                <input type="hidden" name="nome" value="{_esc(nome_escolhido)}">
                <button type="submit"
                        style="background:#27ae60;color:#fff;border:none;border-radius:6px;
                               padding:10px 24px;font-weight:700;font-size:0.95em;cursor:pointer;">
                    Iniciar transferencia
                </button>
            </form>
            <a href="/"
               style="background:#6c757d;color:#fff;text-decoration:none;border-radius:6px;
                      padding:10px 20px;font-weight:600;font-size:0.9em">
                Cancelar
            </a>
        </div>
    </div>"""

    return _pagina(
        f"Confirmar match — {nome_escolhido}",
        "operacao",
        corpo,
    ), 200, {"Content-Type": "text/html; charset=utf-8"}


@app.route("/match/<int:cartao_id>/iniciar", methods=["POST"])
def match_iniciar(cartao_id):
    """
    Executa o match confirmado pelo operador (Passo 3b do desenho).

    Chama confirmar_par_manual(cartao_id, nome) do Matcher, que:
      - Registra o match na tabela matches
      - Marca o candidato escolhido como 'escolhido' e os demais como 'descartado'
      - Atualiza o status do cartão para 'matched'
      - Chama atualizar_perfil() para o profissional aprender com esta confirmação
      - Marca o JSON do material como matched → a Camada 2 detecta e inicia a cópia

    Trata erros defensivamente: uma falha aqui nunca derruba o servidor.
    """
    nome_escolhido = (request.form.get("nome") or "").strip().upper()
    if not nome_escolhido:
        # Nome vazio não deveria chegar aqui (a tela de resumo já valida),
        # mas defendemos no servidor por segurança.
        corpo = """
        <div style="background:#fdecea;border:1px solid #f5c6cb;color:#c0392b;
                    border-radius:6px;padding:16px 20px;max-width:540px;margin:0 auto">
            <strong>Erro:</strong> Nome do profissional nao recebido.
            <br><br>
            <a href="/" style="color:#c0392b">Voltar ao painel</a>
        </div>"""
        return _pagina("Erro — match", "operacao", corpo), 400, \
            {"Content-Type": "text/html; charset=utf-8"}

    # ── Chama o Matcher para confirmar o par ──────────────────────────────────
    resultado = {"ok": False, "motivo": "matcher_indisponivel"}
    if MATCHER_DISPONIVEL:
        try:
            resultado = modulo_matcher.confirmar_par_manual(cartao_id, nome_escolhido)
        except Exception as _err_exec:
            # Captura qualquer exceção para não derrubar o servidor
            logger.error(
                f"MATCH INICIAR | Erro inesperado ao chamar confirmar_par_manual "
                f"| Cartao: {cartao_id} | Nome: {nome_escolhido} | Erro: {_err_exec}"
            )
            resultado = {"ok": False, "motivo": f"erro_interno: {_err_exec}"}
    else:
        logger.error(
            f"MATCH INICIAR | Matcher indisponivel | Cartao: {cartao_id} | Nome: {nome_escolhido}"
        )

    # ── Trata o resultado ─────────────────────────────────────────────────────
    if resultado.get("ok"):
        logger.info(
            f"MATCH INICIAR | Match confirmado com sucesso "
            f"| Cartao: {cartao_id} | Nome: {nome_escolhido}"
        )
        # Redireciona para o painel com mensagem de sucesso na query string
        # (mecanismo simples — sem flash session, consistente com o resto do app)
        mensagem = f"Match confirmado — {nome_escolhido} · transferencia iniciada"
        return redirect(f"/?ok={mensagem}")

    else:
        # Falha conhecida (empate já resolvido, banco falhou, etc.)
        motivo = resultado.get("motivo", "motivo_desconhecido")
        logger.warning(
            f"MATCH INICIAR | Match nao confirmado "
            f"| Cartao: {cartao_id} | Nome: {nome_escolhido} | Motivo: {motivo}"
        )

        # Mensagem legível para cada tipo de falha
        if motivo == "empate_ja_resolvido":
            descricao = (
                "Este empate ja foi resolvido (talvez por outra aba ou processo). "
                "O painel vai se atualizar em instantes com o estado atual."
            )
        elif motivo == "matcher_indisponivel":
            descricao = (
                "O modulo Matcher nao esta disponivel. "
                "Verifique se matcher.py esta na raiz do projeto e reinicie o servidor."
            )
        else:
            descricao = f"Detalhe tecnico: {_esc(motivo)}"

        corpo = f"""
        <div style="background:#fdecea;border:1px solid #f5c6cb;color:#c0392b;
                    border-radius:6px;padding:16px 20px;max-width:540px;margin:0 auto">
            <strong>Nao foi possivel confirmar o match.</strong>
            <br><br>
            {descricao}
            <br><br>
            <a href="/" style="color:#c0392b;font-weight:600">Voltar ao painel</a>
        </div>"""
        return _pagina("Erro — match", "operacao", corpo), 409, \
            {"Content-Type": "text/html; charset=utf-8"}


# ── TRATAMENTO DE ERROS GLOBAIS ───────────────────────────────────────────────

@app.errorhandler(404)
def rota_nao_encontrada(erro):
    """Retorna JSON amigável para rotas inexistentes (nunca mostra stacktrace)."""
    return jsonify({
        "ok": False,
        "erro": f"Rota nao encontrada. Rotas disponíveis: GET /, GET /status, POST /forms, POST /porteiro/ativar, POST /porteiro/desativar"
    }), 404


@app.errorhandler(405)
def metodo_nao_permitido(erro):
    """Retorna JSON amigável quando o método HTTP está errado."""
    return jsonify({
        "ok": False,
        "erro": "Método HTTP não permitido nesta rota."
    }), 405


@app.errorhandler(500)
def erro_interno(erro):
    """Captura erros inesperados sem expor stacktrace ao cliente."""
    logger.error(f"ERRO INTERNO | {erro}")
    return jsonify({
        "ok": False,
        "erro": "Erro interno do servidor GMA. Verifique os logs."
    }), 500


# ── PONTO DE ENTRADA ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Garante que as pastas necessárias existem antes de iniciar
    os.makedirs(PASTA_FILA_FORMS, exist_ok=True)
    os.makedirs(PASTA_FILA_MATERIAL, exist_ok=True)
    os.makedirs(os.path.dirname(ARQUIVO_LOG), exist_ok=True)

    # ── Endereço de escuta (configurável — responsabilidade da Camada 5) ──────
    # Padrão SEGURO: 127.0.0.1 (só a própria máquina). Para liberar o acesso de
    # celulares na MESMA rede local do evento (ex.: a ficha online no set), defina
    # GMA_HOST=0.0.0.0 no ambiente. O servidor só escuta na rede quando VOCÊ pede.
    #
    # ATENÇÃO: 0.0.0.0 expõe o Flask para QUALQUER aparelho na rede local. É seguro
    # numa rede de evento confiável (a ficha só GRAVA check-in; mídia nunca trafega
    # aqui), mas nunca aponte um túnel público para cá sem autenticação.
    host_escuta = os.environ.get("GMA_HOST", "127.0.0.1").strip() or "127.0.0.1"
    porta_escuta = int(os.environ.get("GMA_PORT", "5050"))
    na_rede = host_escuta not in ("127.0.0.1", "localhost")

    # Aviso de inicialização
    logger.info("=" * 60)
    logger.info("GMA FLASK | Servidor de check-in iniciando")
    if na_rede:
        logger.info(f"GMA FLASK | Porta: {porta_escuta} | Host: {host_escuta} (ABERTO NA REDE LOCAL)")
    else:
        logger.info(f"GMA FLASK | Porta: {porta_escuta} | Host: {host_escuta} (somente local)")
    logger.info(f"GMA FLASK | Fila material: {PASTA_FILA_MATERIAL}")
    logger.info(f"GMA FLASK | Fila forms:    {PASTA_FILA_FORMS}")
    logger.info(f"GMA FLASK | Log:           {ARQUIVO_LOG}")
    logger.info(f"GMA FLASK | Matcher:       {'disponivel' if MATCHER_DISPONIVEL else 'INDISPONIVEL'}")
    logger.info("=" * 60)

    # debug=False em produção para não expor informações do sistema
    app.run(
        host=host_escuta,
        port=porta_escuta,
        debug=False,        # False em produção; True só para desenvolvimento
    )
