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
import threading
from datetime import datetime, timedelta
import secrets
from flask import Flask, request, jsonify, redirect, session

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

# Isolamento multi-projeto (Camada 5): as filas moram ao lado do banco do projeto
# ativo (GMA_DB). Para o laboratório, resolvem para as pastas da raiz de sempre.
# Importa o painel_config cedo (stdlib pura) para resolver os caminhos por projeto.
import sys as _sys_cfg
_sys_cfg.path.insert(0, RAIZ_GMA)
try:
    import painel_config
    PAINEL_DISPONIVEL = True
    PASTA_FILA_FORMS = painel_config.pasta_ao_lado_do_banco("fila_forms")
    PASTA_FILA_MATERIAL = painel_config.pasta_ao_lado_do_banco("fila_material")
except Exception:
    # Sem o painel_config (situação degradada) → pastas da raiz, como antes.
    PAINEL_DISPONIVEL = False
    PASTA_FILA_FORMS = os.path.join(RAIZ_GMA, "fila_forms")
    PASTA_FILA_MATERIAL = os.path.join(RAIZ_GMA, "fila_material")

# Arquivo sentinela que ativa/desativa o Porteiro
SENTINELA_PORTEIRO = os.path.join(RAIZ_GMA, ".gma_ativo")

# Bilhete da cópia ao vivo, escrito pelo copiador.py (Camada 2). A aba Mural lê
# este arquivo para mostrar a velocidade de transferência em tempo real.
ARQUIVO_STATUS_COPIA = os.path.join(RAIZ_GMA, ".gma_copia_status.json")

# Arquivo de log do Flask
ARQUIVO_LOG = os.path.join(RAIZ_GMA, "logs", "flask_gma.log")

# Campos obrigatórios que todo formulário deve conter.
# A câmera SAIU desta lista na Nova Ficha v2 (Fatia 4): ela não é mais perguntada
# na ficha — vem do cadastro do profissional (e/ou é detectada pelo Leitor). O
# Matcher busca a câmera do cadastro pelo nome para o critério +3.
CAMPOS_OBRIGATORIOS = ["nome", "tipo_material", "data_gravacao"]

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

# ── PAINEL DE CONTROLE (Camada 5) ─────────────────────────────────────────────
# O painel_config já foi importado no topo (resolve as filas por projeto). Aqui
# só garantimos o subprocess (usado pelos testes de conexão e criação de projeto).
import subprocess


# ── CAMADA 6 (IA) — TRANSCRIÇÃO DE ÁUDIO (assíncrona, opcional) ────────────────
# O Whisper é pesado e mora numa CAIXA ISOLADA (.venv_ia/), separada do Python que
# roda este Flask e o ciclo crítico. Por isso NÃO importamos faster-whisper aqui:
# chamamos o transcritor.py como SUBPROCESSO, com o python da caixa.
PYTHON_IA = os.path.join(RAIZ_GMA, ".venv_ia", "bin", "python")
TRANSCRITOR_SCRIPT = os.path.join(RAIZ_GMA, "transcritor.py")

# Cartões com transcrição rodando agora (para a planilha mostrar "⏳ transcrevendo…"
# e para não disparar duas vezes o mesmo). Protegido por lock — várias requisições.
_transcricoes_em_andamento = set()
_lock_transcricao = threading.Lock()

# ── CAMADA 6 (IA) — MISSÃO A Fatia 2: busca conversacional (opcional) ──────────
# Põe um LLM por cima da busca mecânica da Fatia 1. Import protegido: se o módulo
# faltar, a barra de busca segue funcionando no modo mecânico (sem regressão).
try:
    import assistente_ia as aia
    AIA_OK = True
except Exception:
    AIA_OK = False


def _transcricao_disponivel():
    """True se a caixa isolada da IA e o transcritor existem (recurso instalado)."""
    return os.path.exists(PYTHON_IA) and os.path.exists(TRANSCRITOR_SCRIPT)


def _rodar_transcricao_async(cartao_id, destino_pasta):
    """Roda o Whisper local (subprocesso na caixa isolada) e grava o texto no banco.

    Executa DENTRO de uma thread — a tela não trava enquanto o áudio é transcrito
    (pode levar minutos). Nunca toca na mídia: só lê os áudios já copiados e grava
    o TEXTO resultante. Qualquer falha é logada; o cartão sai de "em andamento".
    """
    try:
        # timeout generoso: áudio longo demora; está em background, então tudo bem.
        proc = subprocess.run(
            [PYTHON_IA, TRANSCRITOR_SCRIPT, destino_pasta],
            capture_output=True, text=True, timeout=3600,
        )
        # O transcritor imprime UMA linha JSON em stdout (a última não-vazia).
        linha_json = ""
        for linha in (proc.stdout or "").splitlines():
            if linha.strip():
                linha_json = linha.strip()
        if not linha_json:
            logger.error(f"TRANSCRIÇÃO | Sem saída do transcritor | cartão {cartao_id} "
                         f"| stderr: {(proc.stderr or '')[:300]}")
            return
        resultado = json.loads(linha_json)
        if not resultado.get("ok"):
            logger.error(f"TRANSCRIÇÃO | Falhou | cartão {cartao_id} | {resultado.get('erro')}")
            return
        arquivos = resultado.get("arquivos", [])
        n_audios = resultado.get("n_audios", 0)
        conn = bd.obter_conexao()
        r = bd.salvar_transcricoes_arquivos(conn, cartao_id, arquivos)
        # Carimba o cartão como já processado para o VIGIA da transcrição automática
        # (vigia_transcricao.py) não repegar um cartão que o operador acabou de
        # transcrever na mão. Reprocessar pelo botão continua valendo (a rota não
        # filtra pelo carimbo); o vigia, sim.
        bd.marcar_transcricao_tentada(conn, cartao_id)
        conn.close()
        logger.info(f"TRANSCRIÇÃO | Concluída | cartão {cartao_id} | "
                    f"{n_audios} áudio(s) | {r.get('n_arquivos_atualizados', 0)} arquivo(s) gravado(s)")
    except subprocess.TimeoutExpired:
        logger.error(f"TRANSCRIÇÃO | Timeout (>1h) | cartão {cartao_id}")
    except Exception as erro:
        logger.error(f"TRANSCRIÇÃO | Exceção | cartão {cartao_id} | {erro}")
    finally:
        with _lock_transcricao:
            _transcricoes_em_andamento.discard(cartao_id)


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

    # O JSON da fila é o estado bruto e pode ficar PRESO: o material RECEBIDO pula o
    # Matcher (que avançaria o JSON), então um Post já copiado/concluído continua
    # marcado 'aguardando_material' no arquivo. O BANCO é a fonte de verdade — então
    # cruzamos por id e escondemos do aviso de órfão o que o banco já resolveu.
    # (Mesmo princípio dos filtros do painel de Operação — ver montar_painel.)
    forms_resolvidos = set()
    cartoes_concluidos = set()
    if BANCO_DISPONIVEL:
        try:
            _conn_o = bd.obter_conexao()
            forms_resolvidos = {
                linha["id"] for linha in _conn_o.execute(
                    "SELECT id FROM formularios "
                    "WHERE status NOT IN ('aguardando_match', 'aguardando_material')"
                ).fetchall()
            }
            cartoes_concluidos = {
                linha["id"] for linha in _conn_o.execute(
                    "SELECT id FROM cartoes WHERE status = 'concluido'"
                ).fetchall()
            }
            _conn_o.close()
        except Exception as _err_o:
            logger.error(f"ORFAOS | Falha ao ler estado resolvido do banco | {_err_o}")

    materiais_orfaos = []
    forms_orfaos = []

    # Verifica materiais aguardando formulário (esconde cartões já concluídos)
    for nome_arquivo, dados in ler_jsons_da_pasta(PASTA_FILA_MATERIAL, "aguardando_match"):
        if dados.get("db_cartao_id") in cartoes_concluidos:
            continue
        timestamp_str = dados.get("timestamp", "")
        try:
            timestamp_item = datetime.strptime(timestamp_str, "%Y-%m-%dT%H:%M:%S")
            if (agora - timestamp_item) > limite:
                materiais_orfaos.append({"arquivo": nome_arquivo, "dados": dados})
        except ValueError:
            pass  # timestamp malformado — ignora

    # Verifica formulários aguardando material (esconde Posts já resolvidos no banco)
    for nome_arquivo, dados in ler_jsons_da_pasta(PASTA_FILA_FORMS, "aguardando_material"):
        if dados.get("db_formulario_id") in forms_resolvidos:
            continue
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

import operadores  # Camada 5 — armazém global dos operadores (login)

app = Flask(__name__)
logger = configurar_logger()


def _carregar_secret():
    """
    Chave que ASSINA os cookies de sessão (login do operador). Precisa ser estável
    entre reinícios — senão todo mundo cai do login a cada Iniciar. Ordem: usa
    GMA_SECRET do .env se houver; senão gera uma e guarda em .gma_secret (fora do
    git). Assim o login sobrevive aos reinícios sem o operador configurar nada.
    """
    do_env = os.environ.get("GMA_SECRET", "").strip()
    if do_env:
        return do_env
    caminho = os.path.join(RAIZ_GMA, ".gma_secret")
    try:
        if os.path.isfile(caminho):
            with open(caminho, "r", encoding="utf-8") as f:
                guardada = f.read().strip()
            if guardada:
                return guardada
        nova = secrets.token_hex(32)
        with open(caminho, "w", encoding="utf-8") as f:
            f.write(nova)
        return nova
    except OSError:
        # Não deu para persistir (disco?) — usa uma chave da sessão deste processo.
        # O login funciona; só não sobrevive a um reinício (degradação aceitável).
        return secrets.token_hex(32)


app.secret_key = _carregar_secret()


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


# Rotas que NÃO exigem operador logado na base: o próprio fluxo de login, o caminho
# de preencher ficha (igual ao remoto) e os webhooks/saúde. Tudo mais (Painel,
# Kanban, Planilha, match, listas…) só com operador logado.
ROTAS_SEM_LOGIN_EXATAS = ("/login", "/logout", "/ficha", "/status")
ROTAS_SEM_LOGIN_PREFIXOS = ("/forms", "/static")


def _rota_livre_de_login(path):
    """True se a rota pode ser acessada na base SEM operador logado."""
    if path in ROTAS_SEM_LOGIN_EXATAS:
        return True
    return path.startswith(ROTAS_SEM_LOGIN_PREFIXOS)


def _operador_logado():
    """Nome do operador logado nesta sessão, ou None."""
    return session.get("operador")


@app.before_request
def _carimbar_operador():
    """
    Deixa o operador logado no CONTEXTO do banco (governança): qualquer evento
    gravado durante esta requisição sai carimbado com quem fez, sem precisar passar
    o operador por toda chamada. Roda em toda requisição da base; ações automáticas
    e webhooks ficam sem operador (NULL = sistema). Registrado ANTES do portão para
    valer mesmo nas rotas livres de login (ex.: a ficha preenchida na base).
    """
    if BANCO_DISPONIVEL:
        try:
            bd.definir_operador_contexto(session.get("operador"))
        except Exception:
            pass  # o carimbo é informativo; nunca pode derrubar a requisição


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

    # ── 1.5) Login do operador (só na BASE) ───────────────────────────────────
    # A operação na base exige um operador logado (identidade + barreira). O remoto
    # (câmera) nunca chega aqui — o passo 1 já o limita a /ficha. Sem operador na
    # sessão, manda ao /login, que oferece criar o PRIMEIRO operador quando ainda
    # não há nenhum (à prova de tranca: você nunca fica trancado pra fora).
    if _host_local() and not _rota_livre_de_login(request.path):
        if not _operador_logado():
            return redirect("/login")

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


# ── LOGIN DO OPERADOR (Camada 5) ─────────────────────────────────────────────
# Tela própria (sem as abas de operação — quem não entrou ainda não vê a operação).
# Identidade + barreira: a base só opera com um operador logado; o remoto (câmera)
# nunca chega aqui. Armazém global em operadores.py.

_VERDE_GMA = "#1D9E75"


# ── MARCA 6floor (Camada 7) ──────────────────────────────────────────────────
# Identidade visual aplicada às telas. A fonte de verdade da paleta é
# marca/6floor_paleta.css (s54); aqui as MESMAS cores viram um bloco :root que o
# Flask injeta no <head>. Regra: nunca cravar hex novo nas telas — usar var(--6f-…).

# Bloco :root com a paleta do 6floor, para embutir DENTRO de um <style> existente.
# Espelha marca/6floor_paleta.css (mundo escuro "sala de controle", um acento só).
MARCA_VARS = """
    :root {
      --6f-fonte: 'Space Grotesk', system-ui, -apple-system, BlinkMacSystemFont, sans-serif;
      --6f-teal:#2BB58C; --6f-teal-forte:#1D9E75; --6f-teal-claro:#3DD3A6; --6f-teal-trilho:#132F26;
      --6f-bg-base:#0B100E; --6f-bg-superficie:#0E1513; --6f-bg-elevado:#131C19; --6f-bg-hover:#1A2521;
      --6f-borda:#243430; --6f-texto:#EAF0EE; --6f-texto-2:#9DB0AA; --6f-texto-3:#5E726C;
      --6f-ok:#2BB58C; --6f-aviso:#E0A33B; --6f-erro:#E5645B;
    }
"""

# Carrega a Space Grotesk (Google Fonts). Precisa de internet; sem ela, o stack da
# fonte cai em system-ui — nada quebra (a fonte é cosmética, fora do ciclo crítico).
MARCA_FONTE = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">'
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
    '<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&display=swap" rel="stylesheet">'
)


def _marca_lockup(altura=20):
    """Wordmark do 6floor como UMA imagem SVG (6fl + símbolo + r, num só <svg>) — à prova de
    quebra de linha: não mistura texto HTML com <svg> inline, então nada empilha. O texto usa
    a fonte da página (Space Grotesk); `altura` = altura do lockup em px."""
    p = ("M0,0 C0,-27.6 -22.4,-50 -50,-50 C-77.6,-50 -100,-27.6 -100,0 "
         "C-100,27.6 -77.6,50 -50,50 C-22.4,50 0,27.6 0,0 "
         "C0,-27.6 22.4,-50 50,-50 C77.6,-50 100,-27.6 100,0 "
         "C100,27.6 77.6,50 50,50 C22.4,50 0,27.6 0,0 Z")
    txt = ("font-family:var(--6f-fonte);font-weight:600;font-size:56px;"
           "letter-spacing:-1px;fill:var(--6f-texto)")
    return (
        f'<svg height="{altura}" viewBox="0 6 178 60" role="img" '
        'style="display:inline-block;vertical-align:middle" xmlns="http://www.w3.org/2000/svg">'
        '<title>6floor</title>'
        f'<text x="8" y="56" textLength="72" lengthAdjust="spacing" style="{txt}">6fl</text>'
        '<g transform="translate(112.8,41.6) scale(0.288)">'
        f'<path fill="none" stroke="var(--6f-teal)" stroke-width="24" stroke-linecap="round" '
        f'stroke-linejoin="round" d="{p}"/>'
        '</g>'
        f'<text x="145.6" y="56" textLength="24" lengthAdjust="spacing" style="{txt}">r</text>'
        '</svg>'
    )


def _marca_icone(altura=24, cor="var(--6f-teal)"):
    """Só o símbolo (os dois "o" / ∞), em tamanho fixo — a opção de marca SEM a palavra.
    Para favicon, selos compactos, cabeçalho recolhido. Mesmo glifo do wordmark."""
    return (
        f'<svg height="{altura}" viewBox="0 0 224 124" role="img" '
        'style="vertical-align:middle;display:inline-block" xmlns="http://www.w3.org/2000/svg">'
        '<title>6floor</title>'
        '<g transform="translate(112,62)">'
        f'<path fill="none" stroke="{cor}" stroke-width="24" stroke-linecap="round" '
        'stroke-linejoin="round" '
        'd="M0,0 C0,-27.6 -22.4,-50 -50,-50 C-77.6,-50 -100,-27.6 -100,0 '
        'C-100,27.6 -77.6,50 -50,50 C-22.4,50 0,27.6 0,0 '
        'C0,-27.6 22.4,-50 50,-50 C77.6,-50 100,-27.6 100,0 '
        'C100,27.6 77.6,50 50,50 C22.4,50 0,27.6 0,0 Z"/>'
        '</g></svg>'
    )


def _pagina_acesso(corpo, titulo="Entrar", sub=""):
    """Molde escuro e centrado para as telas de login/operadores (sem abas)."""
    sub_html = f"<div class='sub'>{_esc(sub)}</div>" if sub else ""
    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>6floor — {_esc(titulo)}</title>
  {MARCA_FONTE}
  <style>
    {MARCA_VARS}
    * {{ box-sizing:border-box; }}
    body {{ font-family:var(--6f-fonte);
            background:var(--6f-bg-base); color:var(--6f-texto); margin:0; min-height:100vh;
            display:flex; flex-direction:column; align-items:center; padding:48px 20px; }}
    .marca {{ margin-bottom:16px; }}
    h1 {{ font-size:24px; margin:0 0 4px; font-weight:600; }}
    .sub {{ color:var(--6f-texto-2); margin-bottom:28px; font-size:15px; text-align:center; }}
    .cartao {{ width:100%; max-width:420px; background:var(--6f-bg-elevado); border:1px solid var(--6f-borda);
               border-radius:12px; padding:24px; }}
    label {{ display:block; font-size:13px; color:var(--6f-texto-2); margin:14px 0 5px; }}
    input, select {{ width:100%; font-family:inherit; font-size:15px; padding:11px 13px;
                     border-radius:9px; border:1px solid var(--6f-borda); background:var(--6f-bg-superficie); color:var(--6f-texto); }}
    input:focus, select:focus {{ outline:none; border-color:var(--6f-teal); }}
    button {{ font-family:inherit; font-size:15px; font-weight:600; cursor:pointer; border:none;
              border-radius:9px; padding:12px 20px; margin-top:20px; width:100%;
              background:var(--6f-teal); color:var(--6f-bg-base); transition:filter .12s; }}
    button:hover {{ filter:brightness(1.08); }}
    .erro {{ background:#2a1a1c; border:1px solid #5a3330; color:#f2b8b5; border-radius:9px;
             padding:11px 14px; margin-bottom:16px; font-size:14px; }}
    .ok {{ background:var(--6f-teal-trilho); border:1px solid #2f5a45; color:#a8e0c4; border-radius:9px;
           padding:11px 14px; margin-bottom:16px; font-size:14px; }}
    .lista-ops {{ list-style:none; padding:0; margin:0; }}
    .lista-ops li {{ display:flex; justify-content:space-between; align-items:center;
                     padding:11px 0; border-bottom:1px solid var(--6f-borda); }}
    .lista-ops li:last-child {{ border-bottom:none; }}
    .lista-ops .inativo {{ color:var(--6f-texto-3); }}
    .btn-mini {{ width:auto; margin:0; padding:6px 12px; font-size:13px; font-weight:600;
                 background:transparent; color:var(--6f-erro); border:1px solid #5a3330; }}
    .rodape {{ margin-top:24px; font-size:13px; }}
    .rodape a {{ color:var(--6f-texto-3); text-decoration:none; }}
    .rodape a:hover {{ color:var(--6f-texto); }}
  </style>
</head>
<body>
  <div class="marca">{_marca_lockup(26)}</div>
  <h1>{_esc(titulo)}</h1>
  {sub_html}
  {corpo}
</body>
</html>"""


def _pagina_login(erro=None):
    """Tela de login. Modo bootstrap (criar o 1º operador) quando não há nenhum ativo."""
    bootstrap = len(operadores.listar()) == 0
    erro_html = f"<div class='erro'>{_esc(erro)}</div>" if erro else ""

    if bootstrap:
        corpo = f"""
        <div class="cartao">
          {erro_html}
          <form method="post" action="/login">
            <p style="color:#b9c4d6;font-size:14px;margin:0 0 8px">Ainda não há nenhum operador.
               Crie o primeiro para começar a operar.</p>
            <label>Seu nome</label>
            <input type="text" name="nome" autocomplete="off" autofocus required>
            <label>Crie uma senha</label>
            <input type="password" name="senha" required>
            <label>Repita a senha</label>
            <input type="password" name="senha2" required>
            <button type="submit">Criar operador e entrar</button>
          </form>
        </div>"""
        return _pagina_acesso(corpo, titulo="Bem-vindo", sub="Primeiro acesso a esta máquina")

    opcoes = "".join(
        f"<option value=\"{_esc(o['nome'])}\">{_esc(o['nome'])}</option>"
        for o in operadores.listar()
    )
    corpo = f"""
    <div class="cartao">
      {erro_html}
      <form method="post" action="/login">
        <label>Operador</label>
        <select name="nome" required>{opcoes}</select>
        <label>Senha</label>
        <input type="password" name="senha" autofocus required>
        <button type="submit">Entrar</button>
      </form>
    </div>"""
    return _pagina_acesso(corpo, titulo="Entrar", sub="Quem está operando?")


@app.route("/login", methods=["GET", "POST"])
def login():
    # O login é só da base; o remoto (câmera) vai para a ficha.
    if not _host_local():
        return redirect("/ficha")

    if request.method == "GET":
        return _pagina_login()

    nome = (request.form.get("nome") or "").strip()
    senha = request.form.get("senha") or ""
    bootstrap = len(operadores.listar()) == 0

    if bootstrap:
        # Criação do PRIMEIRO operador (à prova de tranca). Operadores extras se
        # criam depois, já logado, na tela /operadores.
        senha2 = request.form.get("senha2") or ""
        if senha != senha2:
            return _pagina_login(erro="As duas senhas não são iguais.")
        try:
            operadores.criar(nome, senha)
        except ValueError as e:
            return _pagina_login(erro=str(e))
        session["operador"] = nome
        session.permanent = True
        logger.info(f"LOGIN | Primeiro operador criado e logado: {nome}")
        return redirect("/")

    op = operadores.verificar(nome, senha)
    if not op:
        logger.info(f"LOGIN | Falha de login para '{nome}'")
        return _pagina_login(erro="Nome ou senha incorretos.")
    session["operador"] = op["nome"]
    session.permanent = True
    logger.info(f"LOGIN | Operador logado: {op['nome']}")
    return redirect("/")


@app.route("/logout", methods=["GET", "POST"])
def logout():
    quem = session.pop("operador", None)
    if quem:
        logger.info(f"LOGIN | Operador saiu: {quem}")
    return redirect("/login")


def _pagina_operadores(aviso=None, erro=None):
    """Cadastro/gestão dos operadores (base, logado). Lista + criar + desativar."""
    logado = _operador_logado()
    erro_html = f"<div class='erro'>{_esc(erro)}</div>" if erro else ""
    aviso_html = f"<div class='ok'>{_esc(aviso)}</div>" if aviso else ""

    itens = []
    for o in operadores.listar(incluir_inativos=True):
        ativo = o["ativo"]
        marca_eu = " (você)" if o["nome"] == logado else ""
        if ativo:
            # Não deixa desativar a si mesmo nem o último operador ativo (tranca).
            pode_desativar = (o["nome"] != logado) and (len(operadores.listar()) > 1)
            acao = (
                f"<form method='post' action='/operadores/{_esc(o['nome'])}/desativar' style='margin:0'>"
                f"<button class='btn-mini' type='submit'>Desativar</button></form>"
                if pode_desativar else "<span style='color:#6c727b;font-size:13px'>—</span>"
            )
            itens.append(f"<li><span>{_esc(o['nome'])}{marca_eu}</span>{acao}</li>")
        else:
            acao = (
                f"<form method='post' action='/operadores/{_esc(o['nome'])}/reativar' style='margin:0'>"
                f"<button class='btn-mini' type='submit' "
                f"style='color:#7fb89a;border-color:#2f5a45'>Reativar</button></form>"
            )
            itens.append(f"<li class='inativo'><span>{_esc(o['nome'])} (desativado)</span>{acao}</li>")

    corpo = f"""
    <div class="cartao">
      {erro_html}{aviso_html}
      <ul class="lista-ops">{''.join(itens)}</ul>
      <form method="post" action="/operadores/criar" style="margin-top:18px">
        <label>Novo operador</label>
        <input type="text" name="nome" placeholder="Nome" autocomplete="off" required>
        <label>Senha</label>
        <input type="password" name="senha" required>
        <label>Repita a senha</label>
        <input type="password" name="senha2" required>
        <button type="submit">Cadastrar operador</button>
      </form>
    </div>
    <div class="rodape"><a href="/painel">← Voltar ao Sistema</a> &nbsp;·&nbsp;
      <a href="/logout">Sair ({_esc(logado or '')})</a></div>"""
    return _pagina_acesso(corpo, titulo="Operadores", sub="Quem pode operar esta máquina")


@app.route("/operadores", methods=["GET"])
def operadores_pagina():
    return _pagina_operadores()


@app.route("/operadores/criar", methods=["POST"])
def operadores_criar():
    nome = (request.form.get("nome") or "").strip()
    senha = request.form.get("senha") or ""
    senha2 = request.form.get("senha2") or ""
    if senha != senha2:
        return _pagina_operadores(erro="As duas senhas não são iguais.")
    try:
        operadores.criar(nome, senha)
    except ValueError as e:
        return _pagina_operadores(erro=str(e))
    logger.info(f"OPERADORES | Cadastrado: {nome} (por {_operador_logado()})")
    return _pagina_operadores(aviso=f"Operador “{nome}” cadastrado.")


@app.route("/operadores/<nome>/desativar", methods=["POST"])
def operadores_desativar(nome):
    if nome == _operador_logado():
        return _pagina_operadores(erro="Você não pode desativar a si mesmo enquanto está logado.")
    if len(operadores.listar()) <= 1:
        return _pagina_operadores(erro="É o último operador ativo — não dá para desativar (trancaria a base).")
    operadores.desativar(nome)
    logger.info(f"OPERADORES | Desativado: {nome} (por {_operador_logado()})")
    return _pagina_operadores(aviso=f"Operador “{nome}” desativado.")


@app.route("/operadores/<nome>/reativar", methods=["POST"])
def operadores_reativar(nome):
    operadores.reativar(nome)
    logger.info(f"OPERADORES | Reativado: {nome} (por {_operador_logado()})")
    return _pagina_operadores(aviso=f"Operador “{nome}” reativado.")


@app.route("/historico", methods=["GET"])
def historico():
    """
    Log de operações (governança) — quem fez o quê e quando. Só leitura, base +
    login (o portão já barra remoto e exige operador). Mostra os eventos mais
    recentes; ação automática do sistema (sem operador) aparece como “sistema”.
    """
    if not BANCO_DISPONIVEL:
        corpo = "<div class='legenda'>Banco de dados indisponível.</div>"
        return _pagina("Histórico", "painel", corpo, head_extra="")

    try:
        conn = bd.obter_conexao()
        eventos = bd.listar_eventos(conn, limite=300)
        conn.close()
    except Exception as e:
        logger.warning(f"HISTORICO | Falha ao ler eventos: {e}")
        corpo = f"<div class='legenda'>Não foi possível ler o histórico: {_esc(e)}</div>"
        return _pagina("Histórico", "painel", corpo, head_extra="")

    td = "padding:8px;border-bottom:1px solid var(--6f-borda);vertical-align:top"
    linhas = []
    for ev in eventos:
        quando = _esc(ev.get("criado_em", ""))
        quem = ev.get("operador")
        quem_html = (f"<b>{_esc(quem)}</b>" if quem
                     else "<span style='color:var(--6f-texto-3)'>sistema</span>")
        tipo = _esc((ev.get("tipo") or "").replace("_", " "))
        desc = _esc(ev.get("descricao", ""))
        linhas.append(
            f"<tr><td style='{td};white-space:nowrap;color:var(--6f-texto-2)'>{quando}</td>"
            f"<td style='{td}'>{quem_html}</td>"
            f"<td style='{td};font-size:0.85em;color:var(--6f-texto-2)'>{tipo}</td>"
            f"<td style='{td}'>{desc}</td></tr>"
        )

    if not linhas:
        corpo = "<div class='legenda'>Nenhum evento registrado ainda.</div>"
    else:
        corpo = (
            "<div class='legenda'>Log de operações (mais recentes primeiro). "
            "“sistema” = ação automática (porteiro, cópia, auditoria, vigias); "
            "um nome = operador que fez a ação na base.</div>"
            "<table style='width:100%;border-collapse:collapse;font-size:0.9em'>"
            "<thead><tr style='text-align:left;border-bottom:2px solid var(--6f-borda)'>"
            "<th style='padding:8px'>Quando</th><th style='padding:8px'>Quem</th>"
            "<th style='padding:8px'>Tipo</th><th style='padding:8px'>O quê</th></tr></thead>"
            "<tbody>" + "".join(linhas) + "</tbody></table>"
        )
    return _pagina("Histórico", "painel", corpo, head_extra="")


# ── MULTI-TIPO (Nova Ficha v2, Fatia 5) ──────────────────────────────────────
# O campo tipo_material chega como texto canônico unindo os tipos marcados
# (ex.: "FOTO", "FOTO+VIDEO", "AUDIO+VIDEO"). Estas duas funções traduzem entre
# esse texto e a forma estruturada (booleanos), que é como o banco guarda — §7.

def _derivar_tipos(tipo_material):
    """De "FOTO+VIDEO" → {'tem_foto':1, 'tem_audio':0, 'tem_video':1}.
    Robusto ao separador: aceita +, ·, vírgula, espaço (qualquer não-letra)."""
    txt = (tipo_material or "").upper()
    return {
        "tem_foto":  1 if "FOTO"  in txt else 0,
        "tem_audio": 1 if "AUDIO" in txt else 0,
        "tem_video": 1 if "VIDEO" in txt else 0,
    }


def _tipo_display(tipo_material):
    """Exibição amigável do multi-tipo: "FOTO+VIDEO" → "Foto · Vídeo" (§7: nunca
    por espaço cru; junta com ·). Mantém a ordem Foto · Áudio · Vídeo."""
    t = _derivar_tipos(tipo_material)
    partes = []
    if t["tem_foto"]:  partes.append("Foto")
    if t["tem_audio"]: partes.append("Áudio")
    if t["tem_video"]: partes.append("Vídeo")
    return " · ".join(partes) if partes else (tipo_material or "—")


def _tipo_canonico(tem_foto, tem_audio, tem_video):
    """Monta o texto canônico interno a partir dos booleanos: (1,0,1) → "FOTO+VIDEO".
    Ordem fixa FOTO+AUDIO+VIDEO; unido por "+". Vazio se nenhum tipo."""
    partes = []
    if tem_foto:  partes.append("FOTO")
    if tem_audio: partes.append("AUDIO")
    if tem_video: partes.append("VIDEO")
    return "+".join(partes)


# ── FUNÇÃO CENTRAL: VALIDAR, SALVAR E DISPARAR MATCHER ───────────────────────
# Esta função contém toda a lógica de processamento de um formulário recebido.
# Ela é chamada por /forms (Google Forms via Apps Script) e por /forms/tally
# (webhook nativo do Tally), que chegam em formatos diferentes mas precisam
# da mesma cadeia de validação + gravação + Matcher.

def _tentar_match_seguro(origem):
    """Dispara o Matcher de forma protegida (erro nele nunca derruba o check-in).
    Retorna a lista de matches gerados (vazia se indisponível ou em erro)."""
    if not MATCHER_DISPONIVEL:
        logger.warning(f"{origem} | Matcher não disponível — cruzamento automático desativado")
        return []
    try:
        matches = modulo_matcher.tentar_match()
        if matches:
            logger.info(f"{origem} | Matcher encontrou {len(matches)} match(es)")
        return matches or []
    except Exception as erro:
        logger.error(f"{origem} | Erro ao chamar Matcher | {erro}")
        return []


def _processar_e_salvar_formulario(dados_recebidos, origem="FORMS",
                                   entrega_id=None, disparar_matcher=True):
    """
    Recebe um dicionário com os campos do formulário já extraídos e normalizados
    no padrão esperado pelo GMA:
        nome, camera, tipo_material, data_gravacao, operador (opcional)

    Retorna uma tupla (resposta_flask, codigo_http) pronta para ser devolvida
    pela rota que chamou esta função.

    O parâmetro `origem` é só para o log distinguir de qual endpoint veio
    (ex: "FORMS" para Google Forms, "TALLY" para o webhook do Tally).

    Áudio é sempre transferência à parte (regra do idealizador): quando a ficha
    marca áudio JUNTO de foto/vídeo, ela descreve DUAS entregas (cartões diferentes).
    Nesse caso esta função se divide em duas fichas ligadas por um `entrega_id`
    comum — uma do foto/vídeo (nome) e uma do áudio (nome_audio, tipo AUDIO). Os
    parâmetros `entrega_id`/`disparar_matcher` servem à recursão dessa divisão
    (o Matcher roda UMA vez só, no fim do processamento externo).
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

    # Nova Ficha v2 (Fatia 5): deriva os booleanos de tipo e captura o 2º nome (áudio).
    tipo_material_norm = dados_recebidos.get("tipo_material", "").strip().upper()
    tipos = _derivar_tipos(tipo_material_norm)
    nome_audio_norm = (dados_recebidos.get("nome_audio", "") or "").strip().upper() or None

    # ── Áudio = transferência à parte: divide a ficha mista em duas ────────────
    # Só divide quando há áudio E foto/vídeo juntos E um nome de áudio informado.
    precisa_dividir = (
        tipos["tem_audio"] and (tipos["tem_foto"] or tipos["tem_video"]) and nome_audio_norm
    )
    if precisa_dividir:
        entrega = "E" + gerar_id_form()  # id que liga as duas fichas da entrega

        # Ficha 1 — foto/vídeo (sem o áudio). Mantém nome_audio como informação.
        dados_fv = dict(dados_recebidos)
        dados_fv["tipo_material"] = _tipo_canonico(tipos["tem_foto"], 0, tipos["tem_video"])
        # Ficha 2 — áudio (a 2ª pessoa): vira o "nome" da própria ficha, tipo AUDIO.
        dados_au = dict(dados_recebidos)
        dados_au["nome"] = nome_audio_norm
        dados_au["tipo_material"] = "AUDIO"
        dados_au["nome_audio"] = ""

        resp_fv, cod_fv = _processar_e_salvar_formulario(
            dados_fv, origem, entrega_id=entrega, disparar_matcher=False)
        resp_au, cod_au = _processar_e_salvar_formulario(
            dados_au, origem, entrega_id=entrega, disparar_matcher=False)

        # O Matcher roda UMA vez, agora que as duas fichas já estão na fila.
        matches = _tentar_match_seguro(origem)

        p_fv = resp_fv.get_json() if cod_fv == 201 else {}
        logger.info(f"{origem} | Entrega {entrega} dividida | foto/vídeo: {nome_normalizado} "
                    f"| áudio: {nome_audio_norm}")
        return jsonify({
            "ok":              True,
            "split":           True,
            "entrega_id":      entrega,
            "id_form":         p_fv.get("id_form"),
            "nome":            nome_normalizado,
            "nome_audio":      nome_audio_norm,
            "matches_gerados": len(matches),
            "mensagem":        "Entrega registrada como duas fichas (áudio à parte)."
        }), 201

    # Lê origem do material: "cartao" (padrão) ou "recebido" (pasta satélite).
    # Formulários externos (Tally/webhook) que não mandam o campo ficam com "cartao".
    _origem_raw = dados_recebidos.get("origem_material", "cartao") or "cartao"
    origem_material_norm = _origem_raw if _origem_raw in ("cartao", "recebido") else "cartao"

    dados_form = {
        "id_form":          id_form,
        "timestamp":        timestamp_iso,
        "nome":             nome_normalizado,
        "camera":           camera_normalizada,
        "tipo_material":    tipo_material_norm,
        "tem_foto":         tipos["tem_foto"],
        "tem_audio":        tipos["tem_audio"],
        "tem_video":        tipos["tem_video"],
        "nome_audio":       nome_audio_norm,
        "entrega_id":       entrega_id,
        "data_gravacao":    dados_recebidos.get("data_gravacao", "").strip(),
        # "Quem preencheu?": se o profissional marcou "Eu mesmo" (preenchido_por=
        # proprio), o operador é o próprio nome. Senão, vale o que foi digitado; e,
        # quando preenchido na BASE por um operador logado (login da Camada 5), cai
        # automaticamente no nome dele — sem digitar. Remoto sem login fica None.
        "operador":         (nome_normalizado
                             if dados_recebidos.get("preenchido_por") == "proprio"
                             else (dados_recebidos.get("operador", "").strip()
                                   or (_operador_logado() if _host_local() else None))),
        # Campos editoriais (opcionais — não bloqueiam validação nem matching)
        "modelo_camera":    dados_recebidos.get("modelo_camera", "").strip() or None,
        "tipo_conteudo":    dados_recebidos.get("tipo_conteudo", "").strip().upper() or None,
        "local_cena":       dados_recebidos.get("local_cena", "").strip() or None,
        "prioridade":       dados_recebidos.get("prioridade", "NORMAL").strip().upper() or "NORMAL",
        "observacoes":      dados_recebidos.get("observacoes", "").strip() or None,
        # Arco pasta satélite: de onde o material chega (não muda o fluxo nesta camada)
        "origem_material":  origem_material_norm,
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
            tem_foto=dados_form.get("tem_foto", 0),
            tem_audio=dados_form.get("tem_audio", 0),
            tem_video=dados_form.get("tem_video", 0),
            nome_audio=dados_form.get("nome_audio"),
            entrega_id=dados_form.get("entrega_id"),
            origem_material=dados_form.get("origem_material", "cartao"),
        )
        # Classificação por chips (ponte chips→ficha): grava os itens de lista
        # escolhidos. Vem da ficha local; webhooks externos não mandam e o default
        # é lista vazia. Numa entrega dividida (áudio à parte), as duas metades
        # carregam os mesmos chips — ambas descrevem o mesmo conteúdo.
        _chips = dados_recebidos.get("chips") or []
        # Grupos de TEXTO (escreve na hora): {grupo_chave: [valores]} (s33).
        _textos = dados_recebidos.get("textos") or {}
        if _db_id is not None:
            _bd.definir_chips_formulario(_conn_flask, _db_id, _chips)
            if _textos:
                _bd.definir_textos_formulario(_conn_flask, _db_id, _textos)
        # ── Peça 1 do arco "recebidos": cria subpasta local para Posts satélite ──
        # Quando o material NÃO vem por cartão físico, cria a pasta de destino
        # imediatamente — o profissional (ou o Drive/Dropbox) vai depositar lá.
        # Falha aqui é AVISO: o Post salva normalmente, só avisa no log.
        if origem_material_norm == "recebido" and _db_id is not None:
            try:
                import painel_config as _pc
                _slug_ativo, _cfg_ativo = _pc.projeto_ativo()
                _base_recebidos = _pc.caminho_recebidos(_cfg_ativo)
                _pasta_criada, _erro_pasta = _bd.criar_pasta_recebidos_post(
                    _conn_flask, _db_id, _base_recebidos
                )
                if _pasta_criada:
                    logger.info(f"RECEBIDOS | Pasta criada: {_pasta_criada}")
                    dados_form["pasta_recebidos"] = _pasta_criada
                else:
                    logger.warning(f"RECEBIDOS | Pasta não criada: {_erro_pasta}")
            except Exception as _err_pasta:
                logger.warning(f"RECEBIDOS | Erro ao criar pasta (Post salvo mesmo assim): {_err_pasta}")

        _conn_flask.close()
        # Salva o ID do banco de volta no JSON (ponte para o Matcher e Transferência)
        dados_form["db_formulario_id"] = _db_id
        if _chips:
            dados_form["chips"] = list(_chips)
        if _textos:
            dados_form["textos"] = _textos
        with open(caminho_arquivo, "w", encoding="utf-8") as _f:
            json.dump(dados_form, _f, ensure_ascii=False, indent=2)
        logger.info(f"BANCO | Formulário gravado | db_id={_db_id}")
    except Exception as _err_bd:
        logger.error(f"BANCO | Falha ao gravar formulário (fluxo JSON continua) | {_err_bd}")

    # ── Tenta fazer match com material já na fila ────────────────────────────
    # Pulado quando esta é uma das metades de uma entrega dividida (o chamador
    # externo dispara o Matcher uma vez só, depois de gravar as duas fichas).
    matches = _tentar_match_seguro(origem) if disparar_matcher else []

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
    # ── Banner de feedback (sucesso/aviso vindos por redirect ?ok=/?aviso=) ────
    # Usado pelo match manual e pela resolução de empate. Mensagens curtas e
    # legíveis; o aviso técnico vira um texto amigável quando reconhecido.
    _msg_ok    = (request.args.get("ok") or "").strip()
    _msg_aviso = (request.args.get("aviso") or "").strip()
    _avisos_legiveis = {
        "match_selecao_incompleta": "Escolha 1 cartão (esquerda) e 1 ficha (direita) antes de fazer o match.",
        "match_ficha_invalida":     "A ficha escolhida não foi encontrada. Atualize o painel.",
        "nome_vazio":               "Nome do profissional não recebido.",
        # Avisos da Fatia 4 — arco RECEBIDOS (cópia de material satélite)
        "nao_e_recebido":       "Este Post não é de origem 'recebido'. Use o fluxo normal de cartão.",
        "nao_esta_pronto":      "O material ainda não foi marcado como recebido. Clique em 'Material recebido — pronto para copiar' primeiro.",
        "pasta_vazia":          "A pasta de recebidos está vazia. Aguarde o material chegar e tente novamente.",
        "pasta_inexistente":    "A pasta de recebidos deste Post não foi encontrada. Verifique o caminho configurado.",
        "ja_tem_match":         "Este Post já foi copiado (ou está em andamento). Não é possível copiar novamente.",
        "destino_invalido":     "Não foi possível montar o caminho de destino. Verifique a data do Post.",
        "transferencia_falhou": "A cópia terminou mas o checksum falhou. Verifique os logs do sistema.",
        "banco_indisponivel":   "O banco de dados não está disponível. Tente reiniciar o sistema.",
        "post_inexistente":     "Post não encontrado no banco de dados.",
        "erro_interno":         "Ocorreu um erro interno. Verifique os logs do sistema.",
    }
    bloco_feedback = ""
    if _msg_ok:
        # Mensagem amigável para a cópia de recebidos (ok=copia_recebido_ok_NOME_NNN)
        if _msg_ok.startswith("copia_recebido_ok_"):
            _numero_cartao = _msg_ok[len("copia_recebido_ok_"):]
            _texto_ok = f"Material copiado com sucesso — cartão {_esc(_numero_cartao)}"
        else:
            _texto_ok = _esc(_msg_ok)
        bloco_feedback = (
            "<div style='background:var(--6f-teal-trilho);border:1px solid var(--6f-teal);color:var(--6f-teal-claro);"
            "border-radius:6px;padding:12px 16px;margin-bottom:16px;font-size:0.92em'>"
            f"✓ {_texto_ok}</div>"
        )
    elif _msg_aviso:
        _texto = _avisos_legiveis.get(_msg_aviso, _msg_aviso)
        bloco_feedback = (
            "<div style='background:var(--6f-bg-elevado);border:1px solid var(--6f-aviso);color:var(--6f-aviso);"
            "border-radius:6px;padding:12px 16px;margin-bottom:16px;font-size:0.92em'>"
            f"{_esc(_texto)}</div>"
        )

    # ── Coleta dados das filas ─────────────────────────────────────────────────
    material_aguardando = ler_jsons_da_pasta(PASTA_FILA_MATERIAL, "aguardando_match")
    forms_aguardando = ler_jsons_da_pasta(PASTA_FILA_FORMS, "aguardando_material")

    # Esconde Posts que o BANCO (fonte de verdade) já tirou de "aguardando":
    # recebidos copiados, matcheados, concluídos ou cancelados. O JSON da fila fica
    # preso em 'aguardando_material' (o material RECEBIDO pula o Matcher, que seria
    # quem avançaria o JSON), então cruzamos pelo db_formulario_id e confiamos no
    # status do banco — mesmo princípio do filtro de cartões concluídos abaixo.
    _forms_resolvidos = set()
    if BANCO_DISPONIVEL:
        try:
            _conn_f = bd.obter_conexao()
            _forms_resolvidos = {
                linha["id"] for linha in _conn_f.execute(
                    "SELECT id FROM formularios "
                    "WHERE status NOT IN ('aguardando_match', 'aguardando_material')"
                ).fetchall()
            }
            _conn_f.close()
        except Exception as _err_f:
            logger.error(f"OPERACAO | Falha ao ler formulários resolvidos do banco | {_err_f}")
    forms_aguardando = [
        (nome_arq, dados) for (nome_arq, dados) in forms_aguardando
        if dados.get("db_formulario_id") not in _forms_resolvidos
    ]

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
    # Esconde os cartões já CONCLUÍDOS (ejetados): eles saem da Operação e ficam
    # no Log do sistema + na Planilha. (O Acompanhamento mantém o Post em "Concluído".)
    _ids_concluidos = set()
    if BANCO_DISPONIVEL:
        try:
            _conn_c = bd.obter_conexao()
            _ids_concluidos = {
                linha["id"] for linha in
                _conn_c.execute("SELECT id FROM cartoes WHERE status = 'concluido'").fetchall()
            }
            _conn_c.close()
        except Exception as _err_c:
            logger.error(f"OPERACAO | Falha ao ler cartões concluídos do banco | {_err_c}")
    todos_matched = [
        (nome_arq, dados) for (nome_arq, dados) in todos_matched
        if dados.get("db_cartao_id") not in _ids_concluidos
    ]
    # Ordena por timestamp do arquivo (nome do arquivo já é cronológico)
    todos_matched.sort(key=lambda x: x[0], reverse=True)
    matches_recentes = todos_matched[:10]

    # Posts cancelados agora vivem na Nova Ficha (centro de controle dos Posts);
    # a Operação não os exibe mais.

    # Identifica órfãos
    orfaos = identificar_orfaos()
    total_orfaos = len(orfaos["materiais"]) + len(orfaos["forms"])

    # Estado do Porteiro
    porteiro_ativo = os.path.isfile(SENTINELA_PORTEIRO)
    porteiro_status_texto = "ATIVO" if porteiro_ativo else "INATIVO"
    porteiro_cor = "var(--6f-ok)" if porteiro_ativo else "var(--6f-erro)"

    # Hora atual para exibição
    hora_atual = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

    # ── Gera as linhas das tabelas ─────────────────────────────────────────────
    def linha_material(nome_arquivo, dados):
        """Gera uma linha <tr> para um item de material."""
        tempo = tempo_desde(dados.get("timestamp", ""))
        marca = dados.get("marca_camera") or "—"
        nome = dados.get("nome", "—")
        origem = dados.get("origem", "—")
        # Seletor para o match manual: rádio com o id do cartão no banco.
        # Só aparece quando o JSON tem db_cartao_id (cartões legados sem id ficam "—").
        cid = dados.get("db_cartao_id")
        sel = (
            f"<input type='radio' name='cartao_sel' value='{cid}' onclick='gmaMatchRefresh()'>"
            if cid is not None else "<span style='color:var(--6f-texto-3)'>—</span>"
        )
        return (
            f"<tr>"
            f"<td style='text-align:center'>{sel}</td>"
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
        cor_prioridade = "var(--6f-erro)" if prioridade == "URGENTE" else "var(--6f-texto-2)"
        # Seletor para o match manual: rádio com o id da ficha no banco.
        fid = dados.get("db_formulario_id")
        sel = (
            f"<input type='radio' name='ficha_sel' value='{fid}' onclick='gmaMatchRefresh()'>"
            if fid is not None else "<span style='color:var(--6f-texto-3)'>—</span>"
        )
        # Cancelar/restaurar/excluir agora moram na Nova Ficha (centro de controle
        # dos Posts). Aqui a Operação cuida só do match.
        return (
            f"<tr>"
            f"<td style='text-align:center'>{sel}</td>"
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
            <div style="border:1px solid var(--6f-aviso);border-radius:6px;padding:12px 16px;margin:8px 0;background:var(--6f-bg-elevado)">
                <strong>{nome}</strong> &middot; {camera}
                <span style="color:var(--6f-texto-3);font-size:0.85em"> — Post aguardando confirmacao</span>
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
                            style="background:var(--6f-teal);color:var(--6f-bg-base);border:none;border-radius:5px;
                                   padding:5px 14px;font-weight:700;font-size:0.85em;cursor:pointer;">
                        Confirmar {nome_cand}
                    </button>
                </form>"""
            else:
                botao = "<span style='color:var(--6f-texto-3);font-size:0.82em'>(sem id de cartao — nao e possivel confirmar)</span>"

            blocos_candidatos += f"""
            <div style="background:var(--6f-bg-superficie);border-radius:5px;padding:10px 14px;margin-top:8px">
                <div style="font-weight:700;font-size:0.95em">{nome_cand}
                    <span style="font-weight:400;color:var(--6f-texto-2);font-size:0.88em">
                        &middot; {cam_cand}
                        &middot; <span style="font-family:monospace">score {score_cand}</span>
                    </span>
                </div>
                <div style="color:var(--6f-texto-3);font-size:0.82em;margin:4px 0 8px;font-family:monospace">
                    {amostra}
                </div>
                {botao}
            </div>"""

        if not blocos_candidatos:
            blocos_candidatos = "<div style='color:var(--6f-texto-3);font-size:0.85em;margin-top:8px'>Sem candidatos registrados para este cartao.</div>"

        return f"""
        <div style="border:1px solid var(--6f-aviso);border-radius:6px;padding:14px 18px;margin:10px 0;background:var(--6f-bg-elevado)">
            <div style="font-weight:700;font-size:1em;margin-bottom:2px">
                {volume}
                <span style="font-weight:400;color:var(--6f-texto-2);font-size:0.88em">
                    &middot; {n_arquivos} arquivos &middot; {camera_detectada}
                </span>
            </div>
            <div style="color:var(--6f-aviso);font-size:0.82em;margin-bottom:6px">
                Quem e esse cartao?
            </div>
            {blocos_candidatos}
        </div>"""

    # Renderiza as linhas de cada seção
    linhas_material = "".join(
        linha_material(n, d) for n, d in material_aguardando
    ) or "<tr><td colspan='4' style='color:var(--6f-texto-3);text-align:center'>Nenhum material aguardando</td></tr>"

    linhas_forms = "".join(
        linha_form(n, d) for n, d in forms_aguardando
    ) or "<tr><td colspan='6' style='color:var(--6f-texto-3);text-align:center'>Nenhum Post aguardando</td></tr>"

    linhas_matches = "".join(
        linha_match(n, d) for n, d in matches_recentes
    ) or "<tr><td colspan='4' style='color:var(--6f-texto-3);text-align:center'>Nenhum match registrado hoje</td></tr>"

    # Renderiza os blocos da seção "Aguardando confirmacao" — cada cartão é um bloco
    blocos_confirmacao = "".join(
        bloco_confirmacao_cartao(nome_arq, tipo, dados)
        for nome_arq, (tipo, dados) in aguardando_confirmacao
    ) or "<p style='color:var(--6f-texto-3);text-align:center;padding:18px'>Nenhum item aguardando confirmacao</p>"

    # Alerta de órfãos (aparece destacado se houver algum)
    if total_orfaos > 0:
        nomes_orfaos_mat = ", ".join(d["dados"].get("nome", "?") for d in orfaos["materiais"])
        nomes_orfaos_form = ", ".join(d["dados"].get("nome", "?") for d in orfaos["forms"])
        partes_alerta = []
        if orfaos["materiais"]:
            partes_alerta.append(f"Material sem Post ({len(orfaos['materiais'])}): {nomes_orfaos_mat}")
        if orfaos["forms"]:
            partes_alerta.append(f"Post sem material ({len(orfaos['forms'])}): {nomes_orfaos_form}")
        bloco_orfaos = f"""
        <div style="background:var(--6f-bg-elevado);border:1px solid var(--6f-aviso);border-radius:6px;
                    padding:12px 18px;margin-bottom:20px;color:var(--6f-aviso);">
            <strong>Atencao: {total_orfaos} orfao(s) aguardando ha mais de {MINUTOS_ORFAO} minutos</strong><br>
            {"<br>".join(partes_alerta)}
        </div>"""
    else:
        bloco_orfaos = ""

    # Posts cancelados (restaurar/excluir) migraram para o centro de controle na
    # Nova Ficha; a Operação não monta mais esse bloco.

    # ── Monta a página pelo molde da marca (_pagina) ───────────────────────────
    # A aba Match agora usa o MESMO molde das outras 7 telas: o _pagina cuida do
    # cabeçalho 6floor (∞ + título), das abas e das variáveis da marca. Aqui fica
    # só o CSS próprio desta tela (classes exclusivas da Operação), escopado em
    # .pag-operacao e já no mundo escuro. As 4 categorias de card viram acento
    # semântico: matches = teal (sucesso); confirmação = âmbar (precisa de você);
    # as duas filas de espera = neutro.
    css_operacao = """
        .pag-operacao main { max-width:1200px; }
        .pag-operacao .grid { display:grid; grid-template-columns:1fr 1fr; gap:20px; margin-bottom:20px; }
        .pag-operacao .card { background:var(--6f-bg-elevado); border:1px solid var(--6f-borda);
                              border-radius:8px; overflow:hidden; }
        .pag-operacao .card-full { grid-column:1 / -1; }
        .pag-operacao .card-header { padding:12px 16px; font-weight:600; font-size:0.9em;
                                     letter-spacing:0.3px; display:flex; justify-content:space-between;
                                     align-items:center; background:var(--6f-bg-superficie);
                                     color:var(--6f-texto); border-bottom:1px solid var(--6f-borda); }
        .pag-operacao .card-header .badge { background:var(--6f-bg-hover); color:var(--6f-texto-2);
                                            border-radius:12px; padding:2px 10px; font-size:0.85em; font-weight:700; }
        .pag-operacao .header-matches     { border-bottom:2px solid var(--6f-teal); }
        .pag-operacao .header-confirmacao { border-bottom:2px solid var(--6f-aviso); }
        .pag-operacao table { width:100%; border-collapse:collapse; font-size:0.88em; }
        .pag-operacao th { padding:8px 12px; text-align:left; background:var(--6f-bg-superficie);
                           border-bottom:1px solid var(--6f-borda); font-weight:600; color:var(--6f-texto-2);
                           font-size:0.82em; text-transform:uppercase; letter-spacing:0.4px; }
        .pag-operacao td { padding:9px 12px; border-bottom:1px solid var(--6f-borda);
                           vertical-align:middle; color:var(--6f-texto); }
        .pag-operacao tr:last-child td { border-bottom:none; }
        .pag-operacao tr:hover td { background:var(--6f-bg-hover); }
        .pag-operacao .rodape { text-align:center; padding:16px; color:var(--6f-texto-3); font-size:0.8em; }
        .pag-operacao .controles { display:flex; gap:10px; margin-bottom:20px; align-items:center; flex-wrap:wrap; }
        .pag-operacao .btn { padding:8px 18px; border:none; border-radius:6px; font-size:0.88em;
                             font-weight:600; cursor:pointer; text-decoration:none; }
        .pag-operacao .btn-ativar    { background:var(--6f-teal); color:var(--6f-bg-base); }
        .pag-operacao .btn-desativar { background:var(--6f-erro); color:#fff; }
        .pag-operacao .match-acao { margin-bottom:16px; }
        .pag-operacao .btn-match { background:var(--6f-teal); color:var(--6f-bg-base); font-weight:700;
                                   letter-spacing:0.5px; padding:8px 28px; }
        .pag-operacao .btn-match:disabled { opacity:0.4; cursor:not-allowed; }
        .pag-operacao .status-porteiro { font-size:0.85em; color:var(--6f-texto-2); }
    """
    head_extra = f"<style>{css_operacao}</style>" + """<script>
    // ── Match manual: liga o botão só quando há 1 cartão + 1 ficha escolhidos ──
    function gmaMatchRefresh() {
        var c = document.querySelector('input[name=cartao_sel]:checked');
        var f = document.querySelector('input[name=ficha_sel]:checked');
        document.getElementById('btn-match').disabled = !(c && f);
    }
    function gmaMatchSubmit() {
        var c = document.querySelector('input[name=cartao_sel]:checked');
        var f = document.querySelector('input[name=ficha_sel]:checked');
        if (!c || !f) return;
        document.getElementById('match-cartao-id').value = c.value;
        document.getElementById('match-ficha-id').value = f.value;
        document.getElementById('form-match').submit();
    }
    // Auto-refresh de 5s — PAUSA enquanto há uma bolinha marcada (match na mão em curso).
    setTimeout(function() {
        var c = document.querySelector('input[name=cartao_sel]:checked');
        var f = document.querySelector('input[name=ficha_sel]:checked');
        if (c || f) return;
        location.reload();
    }, 5000);
    </script>"""

    corpo = f"""
        {bloco_feedback}
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
                Posts aguardando: <strong>{len(forms_aguardando)}</strong>
                &nbsp;|&nbsp;
                Matches hoje: <strong>{contar_matches_hoje()}</strong>
            </span>
        </div>

        <!-- Botão do match manual (último recurso do princípio nº 3): aparece sempre, -->
        <!-- mas só LIGA quando há 1 cartão (esq.) + 1 Post (dir.) marcados. -->
        <div class="match-acao">
            <button type="button" id="btn-match" class="btn btn-match" disabled
                    onclick="gmaMatchSubmit()">
                MATCH
            </button>
        </div>
        <form id="form-match" action="/match-manual/confirmar" method="post" style="display:none">
            <input type="hidden" name="cartao_id" id="match-cartao-id">
            <input type="hidden" name="formulario_id" id="match-ficha-id">
        </form>

        <div class="grid">
            <!-- Bloco: Material aguardando formulário -->
            <div class="card">
                <div class="card-header header-material">
                    Material aguardando Post
                    <span class="badge">{len(material_aguardando)}</span>
                </div>
                <table>
                    <tr>
                        <th style="width:34px"></th>
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
                    Posts aguardando material
                    <span class="badge">{len(forms_aguardando)}</span>
                </div>
                <table>
                    <tr>
                        <th style="width:34px"></th>
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
                        <th>ID do Post</th>
                        <th>Recebido ha</th>
                    </tr>
                    {linhas_matches}
                </table>
            </div>

            <!-- Bloco: Aguardando confirmacao humana (match ambiguo — ocupa largura total) -->
            <!-- O Matcher nao conseguiu dar match automaticamente porque havia dois ou mais -->
            <!-- candidatos com pontuacoes muito proximas. O operador escolhe aqui.        -->
            <div class="card card-full">
                <div class="card-header header-confirmacao">
                    Aguardando confirmacao
                    <span class="badge" style="background:var(--6f-bg-hover);color:var(--6f-aviso)">{len(aguardando_confirmacao)}</span>
                </div>
                <div style="padding:12px 16px">
                    {blocos_confirmacao}
                </div>
            </div>
        </div>

        <p class="rodape">
            GMA Camada 1 &mdash; Atualiza automaticamente a cada 5 segundos &mdash;
            <a href="/status" style="color:var(--6f-texto-3)">JSON de status</a>
        </p>"""

    return _pagina("Match", "operacao", corpo, head_extra), 200, {"Content-Type": "text/html; charset=utf-8"}


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
    .abas { display:flex; gap:4px; background:var(--6f-bg-superficie); padding:0 24px;
            border-bottom:1px solid var(--6f-borda); }
    .aba {
        padding:11px 20px; color:var(--6f-texto-2); text-decoration:none;
        font-size:0.9em; font-weight:600; border-bottom:3px solid transparent;
    }
    .aba:hover { color:var(--6f-texto); }
    .aba.ativa { color:var(--6f-texto); border-bottom-color:var(--6f-teal); background:var(--6f-bg-hover); }
"""


def barra_abas(ativa):
    """Barra de navegação entre as telas.
    'ativa' = ficha|operacao|kanban|planilha|molde|profissionais|listas|painel
    Chave interna → rótulo visível (s57): ficha→Posts · operacao→Match ·
    kanban→Mural · planilha→Entrega · profissionais→Cadastros ·
    listas→Programação · painel→Sistema. As URLs/chaves seguem as antigas DE
    PROPÓSITO (risco zero) — só o rótulo mudou."""
    def classe(nome):
        return "aba ativa" if nome == ativa else "aba"
    return f"""
    <nav class="abas">
        <a class="{classe('ficha')}" href="/ficha">Posts</a>
        <a class="{classe('operacao')}" href="/">Match</a>
        <a class="{classe('kanban')}" href="/kanban">Mural</a>
        <a class="{classe('planilha')}" href="/planilha">Entrega</a>
        <a class="{classe('profissionais')}" href="/profissionais">Cadastros</a>
        <a class="{classe('listas')}" href="/listas">Programação</a>
        <a class="{classe('painel')}" href="/painel">Sistema</a>
    </nav>"""


def _esc(valor):
    """Escapa texto para HTML (evita que um post-it com < > quebre a página)."""
    return html.escape(str(valor)) if valor is not None else ""


# NOTA (s34): a formatação de tamanho e os valores de chip/texto da planilha
# moram agora no montador compartilhado (banco_dados._fmt_tamanho_planilha e
# banco_dados.valor_celula_planilha), usado tanto aqui quanto pelo exportador.


# ── CATÁLOGO DA PLANILHA DE ENTREGA ──────────────────────────────────────────
# A fonte de verdade das colunas mora em banco_dados.CATALOGO_PLANILHA (montador
# compartilhado, s34) — a /planilha local e o exportador do Google Sheets leem do
# MESMO lugar. Aqui só referenciamos para _garantir_molde e o fallback sem banco.
# (Sem banco disponível, a planilha é uma vista vazia — ela é uma leitura do DB.)
CATALOGO_PLANILHA = bd.CATALOGO_PLANILHA if BANCO_DISPONIVEL else []

# Ordem e rótulos dos blocos (para a página /molde)
BLOCOS_PLANILHA = [
    ("identificacao", "Identificação"),
    ("classificacao",  "Classificação"),
    ("tecnicas",       "Técnicas"),
    ("pos_producao",   "Pós-produção"),
    ("custom",         "Personalizado"),
]

# Garante que a tabela molde_planilha existe (migração roda uma vez só).
_MOLDE_TABELA_OK = False


def _garantir_molde():
    """
    Garante a tabela molde_planilha + sincroniza as colunas:
      • catálogo fixo (identificação/técnicas/pós) — INSERT OR IGNORE
      • colunas dos GRUPOS (chip_<chave>) — criadas/atualizadas/removidas conforme
        os grupos de classificação (Fatia 4). Roda a cada chamada (barato) para
        refletir grupos criados/renomeados/excluídos depois do boot.
    """
    global _MOLDE_TABELA_OK
    if not BANCO_DISPONIVEL:
        return
    try:
        if not _MOLDE_TABELA_OK:
            conn = bd.inicializar_banco()  # cria todas as tabelas (idempotente)
            _MOLDE_TABELA_OK = True
        else:
            conn = bd.obter_conexao()
        bd.sincronizar_catalogo_molde(conn, CATALOGO_PLANILHA)
        bd.sincronizar_colunas_grupos(conn)
        conn.close()
    except Exception as e:
        logger.error(f"MOLDE | Erro ao sincronizar catálogo | {e}")


# ── COLUNAS DO KANBAN ─────────────────────────────────────────────────────────
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
    "transferencia_falhou":   "copiando",   # falha de cópia: fica em "Copiando" com badge vermelho
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
    <title>6floor — {titulo}</title>
    {MARCA_FONTE}
    <style>
        {MARCA_VARS}
        * {{ box-sizing:border-box; margin:0; padding:0; }}
        body {{ font-family:var(--6f-fonte);
                background:#f0f2f5; color:#1a1a1a; font-size:14px; }}
        header {{ background:var(--6f-bg-base); color:var(--6f-texto); padding:14px 24px;
                  border-bottom:1px solid var(--6f-borda);
                  display:flex; justify-content:space-between; align-items:center; }}
        header h1 {{ font-size:1.2em; font-weight:600; letter-spacing:0.3px;
                     display:flex; align-items:center; gap:12px; }}
        header .titulo-pagina {{ color:var(--6f-texto-2); font-weight:500; font-size:0.82em;
                                 padding-left:12px; border-left:1px solid var(--6f-borda); }}
        header .info {{ font-size:0.85em; color:var(--6f-texto-3); }}
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
        /* Coluna "Concluído" — barras agrupadas por dia (estilo ShotPut Pro) */
        .dia-grupo {{ margin-bottom:8px; }}
        .dia-head {{ cursor:pointer; font-size:0.82em; font-weight:600; color:#495057;
                     padding:4px 2px; list-style:none; user-select:none; }}
        .dia-head::-webkit-details-marker {{ display:none; }}
        .dia-head::before {{ content:'\\25B8'; display:inline-block; margin-right:6px; color:#adb5bd; }}
        .dia-grupo[open] > .dia-head::before {{ content:'\\25BE'; }}
        .dia-cont {{ color:#adb5bd; font-weight:400; margin-left:6px; }}
        .dia-corpo {{ display:flex; flex-direction:column; gap:8px; padding:6px 0 2px; }}
        .bar-concluido {{ background:#d6f0d8; border:1px solid #b6e0ba; border-radius:8px; padding:10px 12px; }}
        .bar-topo {{ display:flex; justify-content:space-between; align-items:center; gap:8px; }}
        .bar-titulo {{ font-weight:700; color:#1a1a2e; font-size:0.95em; }}
        .bar-tipo {{ font-size:0.7em; font-weight:700; color:#2e6b32; background:#bfe6c3;
                     border-radius:10px; padding:1px 8px; flex:none; white-space:nowrap; }}
        .bar-tam {{ color:#5f6b62; font-size:0.82em; margin-top:2px; }}
        .bar-rodape {{ color:#5f6b62; font-size:0.82em; margin-top:6px; }}
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
        .descartar-form {{ margin-top:6px; text-align:right; }}
        .btn-descartar {{ background:none; border:none; color:#c0392b; font-size:0.74em;
                          cursor:pointer; padding:0; text-decoration:underline; }}
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

        /* ── TEMA ESCURO 6floor — escopado à tela Acompanhamento (Kanban) ──
           Só vale em body.pag-kanban; as outras telas seguem claras até a sua
           própria fatia. Overrides depois das regras claras p/ vencer por ordem. */
        body.pag-kanban {{ background:var(--6f-bg-base); color:var(--6f-texto); }}
        .pag-kanban .legenda {{ color:var(--6f-texto-2); }}
        .pag-kanban .vazio, .pag-kanban .coluna-vazia {{ color:var(--6f-texto-3); }}
        .pag-kanban .coluna {{ background:var(--6f-bg-superficie); }}
        .pag-kanban .coluna-head {{ background:var(--6f-bg-elevado); color:var(--6f-texto);
                                    border-bottom:1px solid var(--6f-borda); }}
        .pag-kanban .contador {{ background:var(--6f-bg-hover); color:var(--6f-texto-2); }}
        .pag-kanban .dia-head {{ color:var(--6f-texto-2); }}
        .pag-kanban .dia-head::before {{ color:var(--6f-texto-3); }}
        .pag-kanban .dia-cont {{ color:var(--6f-texto-3); }}
        .pag-kanban .card-kanban {{ background:var(--6f-bg-elevado);
                                    border:1px solid var(--6f-borda); box-shadow:none; }}
        .pag-kanban .card-titulo {{ color:var(--6f-texto); }}
        .pag-kanban .card-meta {{ color:var(--6f-texto-2); }}
        /* Concluído = mundo de sucesso → tinta teal apagada, não verde claro */
        .pag-kanban .bar-concluido {{ background:var(--6f-teal-trilho);
                                      border:1px solid #2f5a45; }}
        .pag-kanban .bar-titulo {{ color:var(--6f-texto); }}
        .pag-kanban .bar-tipo {{ color:var(--6f-bg-base); background:var(--6f-teal); }}
        .pag-kanban .bar-tam, .pag-kanban .bar-rodape {{ color:var(--6f-texto-2); }}
        /* Post-it: nota discreta no escuro (nada de amarelo gritante) */
        .pag-kanban .postit {{ background:var(--6f-bg-superficie); border:1px solid var(--6f-borda);
                               color:var(--6f-texto); }}
        .pag-kanban .postit::placeholder {{ color:var(--6f-texto-3); }}
        .pag-kanban .btn-postit {{ background:var(--6f-teal); color:var(--6f-bg-base); }}
        .pag-kanban .btn-descartar {{ color:var(--6f-erro); }}

        /* ── TEMA ESCURO 6floor — escopado à tela Entrega (Planilha) ──
           Mesmo padrão do Kanban: só vale em body.pag-planilha; as demais telas
           seguem claras. A barra de busca e a caixa da IA usam estilo inline (já
           convertido para var(--6f-…) na rota), então aqui basta a tabela + o que
           o inline não alcança (placeholders). */
        body.pag-planilha {{ background:var(--6f-bg-base); color:var(--6f-texto); }}
        .pag-planilha .legenda {{ color:var(--6f-texto-2); }}
        .pag-planilha .vazio {{ color:var(--6f-texto-3); }}
        .pag-planilha .filtro {{ background:var(--6f-bg-elevado); border:1px solid var(--6f-borda);
                                 color:var(--6f-texto); }}
        .pag-planilha .filtro::placeholder {{ color:var(--6f-texto-3); }}
        .pag-planilha input::placeholder {{ color:var(--6f-texto-3); }}
        .pag-planilha .planilha-tabela {{ background:var(--6f-bg-superficie);
                                          box-shadow:none; border:1px solid var(--6f-borda); }}
        .pag-planilha .planilha-tabela th {{ background:var(--6f-bg-elevado); color:var(--6f-texto-2);
                                             border-bottom:1px solid var(--6f-borda); }}
        .pag-planilha .planilha-tabela td {{ color:var(--6f-texto); border-bottom:1px solid var(--6f-borda); }}
        .pag-planilha .planilha-tabela tr:hover td {{ background:var(--6f-bg-hover); }}
        .pag-planilha .mono {{ color:var(--6f-texto-2); }}

        /* ── TEMA ESCURO 6floor — escopado à aba Sistema (Painel + Histórico) ──
           O corpo do Painel é estilizado por PAINEL_CSS (injetado via head_extra,
           já convertido para var(--6f-…) porque é exclusivo desta tela); aqui fica
           o fundo do body + o que o Histórico usa do molde comum (.legenda). */
        body.pag-painel {{ background:var(--6f-bg-base); color:var(--6f-texto); }}
        .pag-painel .legenda {{ color:var(--6f-texto-2); }}
        .pag-painel .vazio {{ color:var(--6f-texto-3); }}

        /* ── TEMA ESCURO 6floor — escopado à aba Posts (Ficha) ──
           Vale nas DUAS caras (operador na base E câmera remota no celular — decisão
           do idealizador, marca coerente dentro e fora). O corpo é estilizado por
           CSS_FICHA (injetado via head_extra, já em var(--6f-…) porque é exclusivo
           da ficha); aqui fica o fundo do body + o que vem do molde comum. */
        body.pag-ficha {{ background:var(--6f-bg-base); color:var(--6f-texto); }}
        .pag-ficha .legenda {{ color:var(--6f-texto-2); }}
        .pag-ficha .vazio {{ color:var(--6f-texto-3); }}

        /* ── TEMA ESCURO 6floor — telas operacionais restantes (só-base):
           Configurar Colunas (molde), Cadastros (profissionais), Programação (listas).
           Estas telas são estilizadas inline nos próprios builders (já convertidos para
           var(--6f-…)); aqui fica só o fundo do body + o que vem do molde comum. */
        body.pag-molde, body.pag-profissionais, body.pag-listas {{
            background:var(--6f-bg-base); color:var(--6f-texto); }}
        .pag-molde .legenda, .pag-profissionais .legenda, .pag-listas .legenda {{ color:var(--6f-texto-2); }}
        .pag-molde .vazio, .pag-profissionais .vazio, .pag-listas .vazio {{ color:var(--6f-texto-3); }}
        .pag-molde .mono, .pag-profissionais .mono, .pag-listas .mono {{ color:var(--6f-texto-2); }}

        /* ── TEMA ESCURO 6floor — aba Match (Operação) ──
           A última tela operacional a entrar no escuro (s61). O corpo é estilizado
           por css_operacao (injetado via head_extra, exclusivo desta tela); aqui
           fica só o fundo do body. Com isto, TODAS as telas seguem o padrão. */
        body.pag-operacao {{ background:var(--6f-bg-base); color:var(--6f-texto); }}
    </style>
    {head_extra}
</head>
<body class="pag-{aba}">
    <header>
        <h1>{_marca_lockup(20)}<span class="titulo-pagina">{_esc(titulo)}</span></h1>
        <span class="info">Atualizado: {hora}</span>
    </header>
    {barra_abas(aba) if _host_local() else ''}
    <main>{corpo}</main>
</body>
</html>"""


def _fmt_data_extenso(iso):
    """'2026-05-31' -> '31 de maio de 2026' (cabeçalho de dia, estilo ShotPut Pro)."""
    from datetime import datetime
    meses = ["janeiro", "fevereiro", "março", "abril", "maio", "junho",
             "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]
    try:
        dt = datetime.strptime((iso or "")[:10], "%Y-%m-%d")
        return f"{dt.day} de {meses[dt.month - 1]} de {dt.year}"
    except Exception:
        return "Sem data"


def _fmt_data_curta(iso):
    """'2026-05-31' -> '31/05/2026'."""
    from datetime import datetime
    try:
        return datetime.strptime((iso or "")[:10], "%Y-%m-%d").strftime("%d/%m/%Y")
    except Exception:
        return "—"


def _tipos_post(row):
    """
    Tipos de material ANUNCIADOS no Post (foto/vídeo/áudio). Vêm dos booleanos do
    formulário (tem_foto/tem_audio/tem_video) que o JOIN do Kanban trouxe; se a
    ficha não veio (cartão sem match), cai para o tipo_material detectado no cartão.
    Retorna uma lista, ex.: ["Vídeo"] ou ["Foto", "Vídeo"].
    """
    tipos = []
    def _campo(nome):
        try:
            return row[nome]
        except (KeyError, IndexError):
            return None
    if _campo("tem_video"):
        tipos.append("Vídeo")
    if _campo("tem_foto"):
        tipos.append("Foto")
    if _campo("tem_audio"):
        tipos.append("Áudio")
    if not tipos:
        mapa = {"VIDEO": "Vídeo", "FOTO": "Foto", "AUDIO": "Áudio"}
        tm = (row["tipo_material"] or "").strip().upper()
        if tm in mapa:
            tipos.append(mapa[tm])
    return tipos


def _data_logagem(cartao):
    """
    Data em que o material foi LOGADO no sistema — a data que deve aparecer (e
    agrupar) na coluna "Concluído".

    Usa SEMPRE um carimbo do relógio do sistema, na ordem: fim da cópia →
    início da cópia → criação do registro. NUNCA usa data_inicio/data_fim, que
    são mtimes dos arquivos do cartão: com o relógio da câmera errado (ex.: GoPro
    travada em 2016) eles mentem a data e jogavam o Post em "01/01/2016". A pasta
    de destino já acertava porque usa a data informada na ficha; a coluna não.
    """
    def _campo(nome):
        try:
            return cartao[nome]
        except (KeyError, IndexError):
            return None
    return (_campo("transferencia_timestamp_fim")
            or _campo("transferencia_timestamp_inicio")
            or _campo("criado_em"))


def _bar_concluido(cartao):
    """
    Barra compacta de um Post CONCLUÍDO (cartão ejetado), no estilo da barra
    lateral do ShotPut Pro: NOME_NNN + tipo (foto/vídeo/áudio) + tamanho · nº de
    arquivos + "Concluído | DD/MM/AAAA". O cartão já saiu do fluxo operacional;
    aqui é só o registro do que foi entregue.
    """
    titulo = cartao["numero_cartao"] or cartao["volume"] or f"Cartão {cartao['id']}"
    tam_bytes = cartao["tamanho_transferido_bytes"] or cartao["tamanho_total_bytes_detectado"]
    tamanho = bd._fmt_tamanho_planilha(tam_bytes) if tam_bytes else "—"
    n_arq = cartao["total_arquivos_transferidos"] or cartao["total_arquivos_detectados"]
    info_tam = tamanho + (f" · {n_arq} arq." if n_arq else "")
    # Data da LOGAGEM (relógio do sistema), não o mtime dos arquivos (#4 s39).
    data = _data_logagem(cartao)
    tipos = _tipos_post(cartao)
    tipo_html = (f"<span class='bar-tipo'>{_esc(' · '.join(tipos))}</span>"
                 if tipos else "")
    return f"""
        <div class="bar-concluido">
            <div class="bar-topo">
                <span class="bar-titulo">{_esc(titulo)}</span>
                {tipo_html}
            </div>
            <div class="bar-tam">{_esc(info_tam)}</div>
            <div class="bar-rodape">Concluído | {_esc(_fmt_data_curta(data))}</div>
        </div>"""


def _coluna_concluido_corpo(cards):
    """
    Corpo da coluna "Concluído": agrupa os Posts por dia DA LOGAGEM (relógio do
    sistema — ver _data_logagem) em blocos recolhíveis (<details> nativo, sem JS),
    mais recentes no topo — exatamente como a barra lateral do ShotPut Pro.
    """
    if not cards:
        return "<p class='coluna-vazia'>—</p>"
    grupos = {}
    for c in cards:
        dia = (_data_logagem(c) or "")[:10]
        grupos.setdefault(dia, []).append(c)
    # Dias em ordem decrescente; "sem data" (string vazia) vai para o fim
    dias_ord = sorted(grupos.keys(), key=lambda d: d or "0000-00-00", reverse=True)
    html = ""
    for dia in dias_ord:
        barras = "".join(_bar_concluido(c) for c in grupos[dia])
        html += f"""
        <details class="dia-grupo" data-dia="{_esc(dia or 'sem-data')}" open>
            <summary class="dia-head">{_esc(_fmt_data_extenso(dia))}<span class="dia-cont">{len(grupos[dia])}</span></summary>
            <div class="dia-corpo">{barras}</div>
        </details>"""
    return html


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

    # Botão "descartar": só para cartão DETECTADO que ainda não virou entrega
    # (sem número, fora do fluxo de cópia). É a saída para sujeira/cartão errado.
    descartavel = (status in ("detectado", "aguardando_match", "sem_midia", "revisar")
                   and not cartao["numero_cartao"])
    botao_descartar = ""
    if descartavel:
        botao_descartar = (
            f"<form class='descartar-form' action='/cartao/{cartao['id']}/descartar' method='post' "
            f"onsubmit=\"return confirm('Descartar este cartão detectado? Ele sai das telas e "
            f"fica registrado no Log do sistema.');\">"
            f"<button type='submit' class='btn-descartar'>descartar</button></form>"
        )

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
            {botao_descartar}
        </div>"""


CSS_QR = """
    .qr-painel { background:var(--6f-bg-superficie); border:1px solid var(--6f-borda);
                 border-radius:8px; box-shadow:none;
                 padding:16px 18px; margin-bottom:18px; max-width:300px;
                 display:inline-flex; flex-direction:column; align-items:center; gap:8px;
                 vertical-align:top; }
    .qr-titulo { font-weight:700; color:var(--6f-texto); font-size:0.95em; align-self:flex-start; }
    /* O QR já vem com fundo branco embutido; a borda branca dá a moldura/quiet zone. */
    .qr-img { width:200px; height:200px; image-rendering:pixelated;
              background:#fff; border:6px solid #fff; border-radius:4px; }
    .qr-link a { color:var(--6f-teal-claro); text-decoration:none; font-size:0.82em; word-break:break-all;
                 text-align:center; }
    .qr-senha { font-size:0.85em; color:var(--6f-texto-2); }
    .qr-dica { font-size:0.78em; color:var(--6f-texto-3); text-align:center; }
    .qr-aviso { font-size:0.8em; color:var(--6f-texto-2); }
"""


def _qr_data_uri(texto, scale=5):
    """Gera o QR como data-URI SVG (embute na página, sem arquivo nem serviço externo)."""
    if not (SEGNO_DISPONIVEL and texto):
        return None
    try:
        # Fundo BRANCO embutido no próprio QR (light) + quiet zone maior (border):
        # garante leitura e visibilidade mesmo sobre o painel escuro do mundo 6floor —
        # QR precisa de alto contraste (preto sobre branco) para a câmera escanear.
        return segno.make(texto, error="m").svg_data_uri(
            scale=scale, border=4, dark="#000000", light="#ffffff"
        )
    except Exception as erro:
        logger.error(f"QR | Erro ao gerar QR | {erro}")
        return None


# Cache curto da URL descoberta do ngrok (evita consultar a API a cada refresh).
_cache_link_ficha = {"url": None, "ts": 0.0}


def _descobrir_link_ficha():
    """
    Descobre o link público da ficha, nesta ordem de prioridade:
      1. GMA_LINK_FICHA no ambiente (override manual — ex.: domínio fixo).
      2. AUTO: lê /tmp/cloudflared_gma_url.txt escrito pelo cloudflared_gma.sh.
         Arquivo presente = túnel Cloudflare vivo; ausente = sem túnel Cloudflare.
         Preferido ao ngrok porque o Cloudflare Quick Tunnel não exibe tela de aviso.
      3. AUTO: pergunta à API local do ngrok (127.0.0.1:4040) qual é a URL ativa
         e monta <url>/ficha. Fallback para quem ainda usa ngrok.
      4. None, se não houver túnel nem override.
    """
    # 1) override manual sempre vence
    manual = os.environ.get("GMA_LINK_FICHA", "").strip()
    if manual:
        return manual

    # cache de ~20s cobre as fontes 2 e 3 juntas
    import time
    agora = time.time()
    if _cache_link_ficha["url"] and (agora - _cache_link_ficha["ts"] < 20):
        return _cache_link_ficha["url"]

    url = None

    # 2) Cloudflare: lê o arquivo de estado gravado pelo cloudflared_gma.sh
    try:
        with open("/tmp/cloudflared_gma_url.txt", "r") as _f:
            conteudo = _f.read().strip()
        if conteudo.startswith("https://"):
            url = conteudo.rstrip("/") + "/ficha"
    except Exception:
        url = None  # arquivo ausente, vazio ou inválido → tenta ngrok

    # 3) ngrok: fallback via API local (só consulta se Cloudflare não retornou nada)
    if not url:
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
          <div class="qr-aviso">Suba o túnel (<code>./cloudflared_gma.sh</code> — ou ngrok)
             que o QR aparece sozinho — ou defina <b>GMA_LINK_FICHA</b> no
             <code>.env</code> (domínio fixo).</div>
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


def _ler_cartoes_kanban(conn):
    """
    Lê os cartões para o Kanban já com os tipos ANUNCIADOS no Post (foto/áudio/
    vídeo), via LEFT JOIN matches→formularios (1 match por cartão). Cartão sem
    ficha vem com os campos de tipo nulos (a barra cai para o tipo_material).
    """
    return conn.execute("""
        SELECT c.*, f.tem_foto, f.tem_audio, f.tem_video
        FROM cartoes c
        LEFT JOIN matches m ON m.cartao_id = c.id
        LEFT JOIN formularios f ON f.id = m.formulario_id
        ORDER BY c.id DESC
    """).fetchall()


def _montar_colunas_kanban(cartoes):
    """
    Distribui os cartões nas colunas conforme o status e devolve o HTML das
    colunas (sem o wrapper). Fonte única usada pela página /kanban E pela rota
    ao vivo /kanban/board — os dois nunca divergem.
    """
    baldes = {chave: [] for chave, _, _ in COLUNAS_KANBAN}
    for cartao in cartoes:
        if cartao["status"] in ("descartado", "ausente"):   # dispensado/invalidado → some das telas
            continue
        coluna = STATUS_PARA_COLUNA.get(cartao["status"], "detectado")
        if coluna not in baldes:   # status sem coluna (defensivo) — ignora
            continue
        baldes[coluna].append(cartao)

    colunas_html = ""
    for chave, rotulo, cor in COLUNAS_KANBAN:
        cards = baldes[chave]
        if chave == "concluido":
            # Coluna "Concluído" = Posts entregues, em barras por dia (estilo ShotPut Pro)
            cards_html = _coluna_concluido_corpo(cards)
        else:
            cards_html = "".join(_card_kanban(c) for c in cards) or "<p class='coluna-vazia'>—</p>"
        colunas_html += f"""
        <div class="coluna">
            <div class="coluna-head" style="border-top:3px solid {cor}">
                <span>{rotulo}</span><span class="contador">{len(cards)}</span>
            </div>
            <div class="coluna-corpo">{cards_html}</div>
        </div>"""
    return colunas_html


@app.route("/kanban", methods=["GET"])
def kanban():
    """
    Aba ACOMPANHAMENTO — o Quadro de Acompanhamento (Acesso 2).

    Lê os cartões direto do banco (fonte única) e os distribui em colunas
    conforme o status. Cada card tem um post-it que grava de volta no banco.
    Mostra também o QR Code do link da ficha (para os câmeras escanearem).

    AO VIVO: o quadro se atualiza sozinho a cada 1s buscando só o fragmento
    (/kanban/board) e trocando quando muda — sem recarregar a página inteira.
    """
    if not BANCO_DISPONIVEL:
        corpo = "<p class='vazio'>Banco de dados indisponível.</p>"
        return _pagina("Mural", "kanban", corpo), 200, {"Content-Type": "text/html; charset=utf-8"}

    try:
        conn = bd.obter_conexao()
        cartoes = _ler_cartoes_kanban(conn)
        conn.close()
    except Exception as erro:
        logger.error(f"KANBAN | Erro ao ler cartões | {erro}")
        cartoes = []

    colunas_html = _montar_colunas_kanban(cartoes)

    corpo = f"""
    <p class="legenda">Cada cartão é um card; ele anda da esquerda para a direita conforme o status muda no banco.
       Escreva um post-it em qualquer card e clique em <strong>Salvar</strong> — fica gravado na fonte única.</p>
    <div id="faixa-copia" class="faixa-copia" style="display:none">
      <div class="fc-topo">
        <span class="fc-titulo">📦 Copiando <strong id="fc-job"></strong></span>
        <span class="fc-vel"><strong id="fc-vel">—</strong> MB/s</span>
      </div>
      <div class="fc-barra"><div class="fc-preench" id="fc-preench"></div></div>
      <div class="fc-baixo">
        <span id="fc-detalhe"></span>
        <span id="fc-restante"></span>
      </div>
    </div>
    {_painel_qr_ficha()}
    <div class="kanban" id="kanban-board">{colunas_html}</div>"""

    # Acompanhamento AO VIVO (mínimo de delay): em vez de recarregar a página
    # inteira, busca só o quadro a cada 1s e troca quando muda. Pausa enquanto
    # você digita um post-it; preserva os grupos de dia recolhidos na coluna
    # "Concluído" (lembra pelo data-dia).
    css_faixa = """
      .faixa-copia{background:var(--6f-bg-elevado);border:1px solid var(--6f-teal);
        border-radius:10px;padding:12px 16px;margin:0 0 16px;}
      .fc-topo{display:flex;justify-content:space-between;align-items:baseline;gap:12px;}
      .fc-titulo{color:var(--6f-texto);font-size:15px;}
      .fc-vel{color:var(--6f-teal-claro);font-size:15px;white-space:nowrap;}
      .fc-vel strong{font-size:22px;font-variant-numeric:tabular-nums;}
      .fc-barra{height:10px;background:var(--6f-teal-trilho);border-radius:6px;
        overflow:hidden;margin:10px 0 8px;}
      .fc-preench{height:100%;background:var(--6f-teal);width:0%;transition:width .4s ease;}
      .fc-baixo{display:flex;justify-content:space-between;gap:12px;
        color:var(--6f-texto-2);font-size:13px;}
    """
    head_extra = f"<style>{CSS_QR}{css_faixa}</style>" + """<script>
      document.addEventListener('DOMContentLoaded', function() {
        var board = document.getElementById('kanban-board');
        if (!board) return;
        var ultimo = null;
        var fechados = new Set();
        document.addEventListener('toggle', function(e) {
          var d = e.target;
          if (d.tagName === 'DETAILS' && d.dataset && d.dataset.dia) {
            if (d.open) fechados.delete(d.dataset.dia); else fechados.add(d.dataset.dia);
          }
        }, true);
        function reaplicar() {
          board.querySelectorAll('details.dia-grupo').forEach(function(d) {
            if (fechados.has(d.dataset.dia)) d.open = false;
          });
        }
        function vivo() {
          var a = document.activeElement;
          if (a && a.tagName === 'TEXTAREA') return;  // pausa: você está digitando um post-it
          fetch('/kanban/board', {cache: 'no-store'})
            .then(function(r) { return r.text(); })
            .then(function(html) {
              if (html && html !== ultimo) {
                ultimo = html;
                board.innerHTML = html;
                reaplicar();
              }
            }).catch(function() {});
        }
        setInterval(vivo, 1000);

        // ── Faixa de velocidade da cópia AO VIVO (estilo ShotPut) ──────────────
        // Busca o bilhete que o copiador escreve; mostra a faixa enquanto copia e
        // a esconde quando fica ocioso. Só leitura — não interfere em nada.
        var faixa = document.getElementById('faixa-copia');
        function fmtTempo(seg) {
          seg = Math.max(0, Math.round(seg));
          if (seg < 60) return '~' + seg + ' s';
          var m = Math.floor(seg / 60), s = seg % 60;
          return '~' + m + ' min ' + (s < 10 ? '0' + s : s) + ' s';
        }
        function copiaVivo() {
          if (!faixa) return;
          fetch('/kanban/copia-status', {cache: 'no-store'})
            .then(function(r) { return r.json(); })
            .then(function(d) {
              if (!d || d.estado !== 'copiando') { faixa.style.display = 'none'; return; }
              document.getElementById('fc-job').textContent = d.job || '';
              document.getElementById('fc-vel').textContent =
                (d.velocidade_mbs != null ? d.velocidade_mbs.toFixed(0) : '—');
              document.getElementById('fc-preench').style.width = (d.percentual || 0) + '%';
              document.getElementById('fc-detalhe').textContent =
                'Arquivo ' + (d.arquivo_indice || 0) + ' de ' + (d.arquivo_total || 0) +
                (d.nome_atual ? ' · ' + d.nome_atual : '') + ' · ' + (d.percentual || 0) + '%';
              document.getElementById('fc-restante').textContent =
                (d.restante_seg > 0 ? fmtTempo(d.restante_seg) + ' restantes' : '');
              faixa.style.display = 'block';
            }).catch(function() {});
        }
        copiaVivo();
        setInterval(copiaVivo, 1000);
      });
    </script>"""
    return _pagina("Mural", "kanban", corpo, head_extra), 200, {"Content-Type": "text/html; charset=utf-8"}


@app.route("/kanban/board", methods=["GET"])
def kanban_board():
    """
    Fragmento HTML das colunas do Kanban (só o quadro), para o Acompanhamento ao
    vivo: a página busca isto a cada 1s e troca quando muda — sem recarregar a
    página inteira (sem flicker, sem perder o post-it em edição). Acesso só na
    base (o portão barra remoto, como toda rota fora de /ficha e /forms).
    """
    if not BANCO_DISPONIVEL:
        return "", 200, {"Content-Type": "text/html; charset=utf-8"}
    try:
        conn = bd.obter_conexao()
        cartoes = _ler_cartoes_kanban(conn)
        conn.close()
    except Exception as erro:
        logger.error(f"KANBAN BOARD | Erro ao ler cartões | {erro}")
        cartoes = []
    return _montar_colunas_kanban(cartoes), 200, {"Content-Type": "text/html; charset=utf-8"}


@app.route("/kanban/copia-status", methods=["GET"])
def kanban_copia_status():
    """
    Bilhete da cópia AO VIVO, para a faixa de velocidade no Mural.

    Lê o arquivo que o copiador.py escreve (.gma_copia_status.json) e o devolve
    como JSON. É tolerante a tudo: se o arquivo não existe, está vazio, ou o
    bilhete é velho (>8s sem atualizar — sinal de cópia que terminou ou travou),
    responde "ocioso" e a faixa some da tela. Nunca quebra. Só na base (o portão
    já barra o remoto, como toda rota fora de /ficha e /forms).
    """
    ocioso = {"estado": "ocioso"}
    try:
        with open(ARQUIVO_STATUS_COPIA, "r", encoding="utf-8") as f:
            dados = json.load(f)
    except (FileNotFoundError, ValueError, OSError):
        return jsonify(ocioso)

    if dados.get("estado") != "copiando":
        return jsonify(ocioso)
    # Bilhete velho = cópia que acabou sem fechar o bilhete, ou processo morto.
    try:
        if (datetime.now().timestamp() - float(dados.get("quando", 0))) > 8:
            return jsonify(ocioso)
    except (TypeError, ValueError):
        return jsonify(ocioso)
    return jsonify(dados)


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


def _arquivar_json_material(cartao_id):
    """
    Move o JSON do material (db_cartao_id == cartao_id) para a subpasta
    _arquivo_descartados/ — assim o cartão também sai da Operação. É REVERSÍVEL
    (o arquivo continua lá, só fora da fila); o banco guarda o status 'descartado'.
    """
    try:
        if not os.path.isdir(PASTA_FILA_MATERIAL):
            return
        destino_dir = os.path.join(PASTA_FILA_MATERIAL, "_arquivo_descartados")
        for nome in os.listdir(PASTA_FILA_MATERIAL):
            if not nome.endswith(".json"):
                continue
            caminho = os.path.join(PASTA_FILA_MATERIAL, nome)
            try:
                with open(caminho, "r", encoding="utf-8") as f:
                    dados = json.load(f)
            except (OSError, json.JSONDecodeError):
                continue
            if dados.get("db_cartao_id") == cartao_id:
                os.makedirs(destino_dir, exist_ok=True)
                os.rename(caminho, os.path.join(destino_dir, nome))
                logger.info(f"DESCARTAR CARTAO | JSON do material arquivado | {nome}")
                break
    except Exception as erro:
        logger.error(f"DESCARTAR CARTAO | Falha ao arquivar JSON do cartão {cartao_id} | {erro}")


@app.route("/cartao/<int:cartao_id>/descartar", methods=["POST"])
def descartar_cartao_rota(cartao_id):
    """
    Descarta um cartão DETECTADO que não vai ser usado (sujeira, cartão errado).
    Soft-delete no banco (status 'descartado' + evento no Log) e arquiva o JSON
    da fila — o cartão sai da Operação e do Acompanhamento, mas nada é apagado.
    Acesso só na base (o portão barra remoto).
    """
    resultado = {"ok": False, "motivo": "banco_indisponivel"}
    if BANCO_DISPONIVEL:
        try:
            conn = bd.obter_conexao()
            resultado = bd.descartar_cartao(conn, cartao_id, motivo="painel")
            conn.close()
        except Exception as erro:
            logger.error(f"DESCARTAR CARTAO | Erro | cartão {cartao_id} | {erro}")
            resultado = {"ok": False, "motivo": f"erro_interno: {erro}"}

    if resultado.get("ok"):
        _arquivar_json_material(cartao_id)
        logger.info(
            f"DESCARTAR CARTAO | Cartão {cartao_id} descartado | "
            f"volume={resultado.get('volume')}"
        )
    else:
        logger.warning(
            f"DESCARTAR CARTAO | Não descartado | cartão {cartao_id} | "
            f"motivo={resultado.get('motivo')}"
        )
    return redirect("/kanban")


@app.route("/cartao/<int:cartao_id>/transcrever", methods=["POST"])
def transcrever_cartao_rota(cartao_id):
    """
    Camada 6 (IA) — dispara a TRANSCRIÇÃO dos áudios já copiados deste cartão.

    Roda em SEGUNDO PLANO (thread): a tela volta na hora com um aviso, e o texto
    aparece na coluna "Transcrição" da planilha quando o Whisper terminar
    (recarregue a página). Nunca toca na mídia — só lê os áudios do destino e
    grava o texto. Acesso só na base (o portão barra remoto).
    """
    if not BANCO_DISPONIVEL:
        return redirect("/planilha?aviso=banco_indisponivel")
    if not _transcricao_disponivel():
        return redirect("/planilha?aviso=transcricao_indisponivel")

    # Busca o destino do cartão (a pasta com os áudios já copiados).
    try:
        conn = bd.obter_conexao()
        row = conn.execute(
            "SELECT destino_pasta FROM cartoes WHERE id = ?",
            (cartao_id,)
        ).fetchone()
        conn.close()
    except Exception as erro:
        logger.error(f"TRANSCRIÇÃO | Erro ao ler cartão {cartao_id} | {erro}")
        return redirect("/planilha?aviso=erro_interno")

    if row is None:
        return redirect("/planilha?aviso=cartao_inexistente")
    destino = (row["destino_pasta"] or "").strip()
    if not destino or not os.path.isdir(destino):
        return redirect("/planilha?aviso=sem_destino")

    # Não dispara duas vezes o mesmo cartão (idempotência do gatilho).
    with _lock_transcricao:
        if cartao_id in _transcricoes_em_andamento:
            return redirect("/planilha?aviso=transcricao_ja_rodando")
        _transcricoes_em_andamento.add(cartao_id)

    logger.info(f"TRANSCRIÇÃO | Iniciada | cartão {cartao_id} | pasta {destino}")
    threading.Thread(
        target=_rodar_transcricao_async, args=(cartao_id, destino), daemon=True
    ).start()
    return redirect("/planilha?ok=transcricao_iniciada")


@app.route("/cartao/<int:cartao_id>/transcricao", methods=["GET"])
def ver_transcricao_cartao(cartao_id):
    """
    Tela leve que mostra a transcrição POR ARQUIVO de um cartão (Camada 6).

    A planilha guarda só o status compacto; o texto completo de cada áudio vive
    aqui, um bloco por arquivo — o grão certo (é o que a Missão A vai pesquisar).
    Acesso só na base (o portão barra remoto).
    """
    if not BANCO_DISPONIVEL:
        corpo = "<p class='vazio'>Banco de dados indisponível.</p>"
        return _pagina("Transcrição", "planilha", corpo), 200, {"Content-Type": "text/html; charset=utf-8"}

    try:
        conn = bd.obter_conexao()
        cartao = conn.execute(
            "SELECT numero_cartao FROM cartoes WHERE id = ?", (cartao_id,)
        ).fetchone()
        arquivos = conn.execute(
            "SELECT nome_arquivo, transcricao, transcricao_em FROM arquivos "
            "WHERE cartao_id = ? AND transcricao IS NOT NULL ORDER BY nome_arquivo",
            (cartao_id,)
        ).fetchall()
        conn.close()
    except Exception as erro:
        logger.error(f"VER TRANSCRIÇÃO | Erro | cartão {cartao_id} | {erro}")
        corpo = "<p class='vazio'>Erro ao ler as transcrições.</p>"
        return _pagina("Transcrição", "planilha", corpo), 200, {"Content-Type": "text/html; charset=utf-8"}

    rotulo = _esc(cartao["numero_cartao"]) if cartao and cartao["numero_cartao"] else f"#{cartao_id}"

    if not arquivos:
        blocos = "<p class='vazio'>Este cartão ainda não tem transcrição.</p>"
    else:
        blocos = ""
        for a in arquivos:
            texto = (a["transcricao"] or "").strip() or "(sem fala detectada)"
            blocos += (
                "<div style='border:1px solid #e0e0e0;border-radius:8px;padding:14px 16px;margin-bottom:14px'>"
                f"<div style='font-weight:600;color:#1D9E75;margin-bottom:6px'>🎙 {_esc(a['nome_arquivo'])}</div>"
                f"<div style='white-space:pre-wrap;font-size:0.95em;line-height:1.5'>{_esc(texto)}</div>"
                "</div>"
            )

    corpo = f"""
    <div style="margin-bottom:14px">
      <a href="/planilha" style="color:#1D9E75">← voltar para a planilha</a>
    </div>
    <p class="legenda">Transcrição por arquivo do cartão <strong>{rotulo}</strong>
      — gerada localmente (Whisper), uma por áudio. É o que a busca conversacional vai pesquisar.</p>
    {blocos}"""
    return _pagina(f"Transcrição — {rotulo}", "planilha", corpo), 200, {"Content-Type": "text/html; charset=utf-8"}


def _mover_json_form(formulario_id, para_arquivo):
    """
    Move o JSON da ficha (db_formulario_id) entre a fila e a subpasta de cancelados.
    para_arquivo=True  → fila_forms/  →  fila_forms/_arquivo_cancelados/  (cancelar)
    para_arquivo=False → _arquivo_cancelados/  →  fila_forms/             (restaurar)
    Reversível; nada é apagado. Defensivo: falha só é logada.
    """
    try:
        if not os.path.isdir(PASTA_FILA_FORMS):
            return
        arquivados = os.path.join(PASTA_FILA_FORMS, "_arquivo_cancelados")
        origem_dir = PASTA_FILA_FORMS if para_arquivo else arquivados
        destino_dir = arquivados if para_arquivo else PASTA_FILA_FORMS
        if not os.path.isdir(origem_dir):
            return
        for nome in os.listdir(origem_dir):
            if not nome.endswith(".json"):
                continue
            caminho = os.path.join(origem_dir, nome)
            try:
                with open(caminho, "r", encoding="utf-8") as f:
                    dados = json.load(f)
            except (OSError, json.JSONDecodeError):
                continue
            if dados.get("db_formulario_id") == formulario_id:
                os.makedirs(destino_dir, exist_ok=True)
                os.rename(caminho, os.path.join(destino_dir, nome))
                logger.info(f"POST | JSON da ficha {'arquivado' if para_arquivo else 'restaurado'} | {nome}")
                break
    except Exception as erro:
        logger.error(f"POST | Falha ao mover JSON da ficha {formulario_id} | {erro}")


@app.route("/post/<int:formulario_id>/cancelar", methods=["POST"])
def post_cancelar(formulario_id):
    """
    Cancela um Post (ficha sem cartão): soft-delete no banco (status 'cancelado'
    + Log) e arquiva o JSON da fila — o Post sai da Operação/Planilha e vai para a
    seção "Posts cancelados". Reversível. Acesso só na base (portão barra remoto).
    """
    resultado = {"ok": False, "motivo": "banco_indisponivel"}
    if BANCO_DISPONIVEL:
        try:
            conn = bd.obter_conexao()
            resultado = bd.cancelar_formulario(conn, formulario_id, motivo="painel")
            conn.close()
        except Exception as erro:
            logger.error(f"POST CANCELAR | Erro | ficha {formulario_id} | {erro}")
            resultado = {"ok": False, "motivo": f"erro_interno: {erro}"}
    if resultado.get("ok"):
        _mover_json_form(formulario_id, para_arquivo=True)
        logger.info(f"POST CANCELAR | Ficha {formulario_id} cancelada | nome={resultado.get('nome')}")
    else:
        logger.warning(f"POST CANCELAR | Não cancelada | ficha {formulario_id} | motivo={resultado.get('motivo')}")
    return redirect("/")


@app.route("/post/<int:formulario_id>/restaurar", methods=["POST"])
def post_restaurar(formulario_id):
    """Restaura um Post cancelado: volta para 'aguardando_match' e devolve o JSON à fila."""
    resultado = {"ok": False, "motivo": "banco_indisponivel"}
    if BANCO_DISPONIVEL:
        try:
            conn = bd.obter_conexao()
            resultado = bd.restaurar_formulario(conn, formulario_id)
            conn.close()
        except Exception as erro:
            logger.error(f"POST RESTAURAR | Erro | ficha {formulario_id} | {erro}")
            resultado = {"ok": False, "motivo": f"erro_interno: {erro}"}
    if resultado.get("ok"):
        _mover_json_form(formulario_id, para_arquivo=False)
        logger.info(f"POST RESTAURAR | Ficha {formulario_id} restaurada | nome={resultado.get('nome')}")
    return redirect("/")


def _excluir_json_form(formulario_id):
    """
    Tombstone do JSON da ficha excluída: procura o JSON (na fila ou na subpasta de
    cancelados) pelo db_formulario_id e o move para fila_forms/_arquivo_excluidos/.

    Não APAGA o arquivo: o registro de verdade (a linha do banco) já saiu em
    excluir_formulario; aqui só tiramos o JSON de qualquer lugar operacional e o
    guardamos como lápide. JSON é metadado (não é mídia), mas a postura conservadora
    do projeto é nunca destruir sem necessidade. Defensivo: falha só é logada.
    """
    try:
        if not os.path.isdir(PASTA_FILA_FORMS):
            return
        arquivados = os.path.join(PASTA_FILA_FORMS, "_arquivo_cancelados")
        excluidos = os.path.join(PASTA_FILA_FORMS, "_arquivo_excluidos")
        # Procura nas duas origens prováveis: a fila viva e a pasta de cancelados.
        for origem_dir in (PASTA_FILA_FORMS, arquivados):
            if not os.path.isdir(origem_dir):
                continue
            for nome in os.listdir(origem_dir):
                if not nome.endswith(".json"):
                    continue
                caminho = os.path.join(origem_dir, nome)
                try:
                    with open(caminho, "r", encoding="utf-8") as f:
                        dados = json.load(f)
                except (OSError, json.JSONDecodeError):
                    continue
                if dados.get("db_formulario_id") == formulario_id:
                    os.makedirs(excluidos, exist_ok=True)
                    os.rename(caminho, os.path.join(excluidos, nome))
                    logger.info(f"POST | JSON da ficha excluída movido para lápide | {nome}")
                    return
    except Exception as erro:
        logger.error(f"POST | Falha ao mover JSON da ficha excluída {formulario_id} | {erro}")


@app.route("/post/<int:formulario_id>/excluir", methods=["POST"])
def post_excluir(formulario_id):
    """
    Exclui DEFINITIVAMENTE um Post sem uso (hard delete): apaga a linha do banco
    (cascata chips/textos/candidatos, desvincula os eventos do Log) e move o JSON
    para a lápide. Irreversível — sobra só o registro no Log. Recusa Post com match
    real. Acesso só na base (o portão barra remoto).
    """
    resultado = {"ok": False, "motivo": "banco_indisponivel"}
    if BANCO_DISPONIVEL:
        try:
            conn = bd.obter_conexao()
            resultado = bd.excluir_formulario(conn, formulario_id)
            conn.close()
        except Exception as erro:
            logger.error(f"POST EXCLUIR | Erro | ficha {formulario_id} | {erro}")
            resultado = {"ok": False, "motivo": f"erro_interno: {erro}"}
    if resultado.get("ok"):
        _excluir_json_form(formulario_id)
        logger.info(f"POST EXCLUIR | Ficha {formulario_id} excluída | nome={resultado.get('nome')}")
    else:
        logger.warning(f"POST EXCLUIR | Não excluída | ficha {formulario_id} | motivo={resultado.get('motivo')}")
    return redirect("/")


# ── ROTAS DO ARCO "RECEBIDOS" — Peça 2 (link) e Peça 3 (gatilho) ─────────────
# Acesso só na base (localhost). O portão _portao_de_acesso já barra remoto.

@app.route("/post/<int:formulario_id>/link-recebidos", methods=["POST"])
def post_link_recebidos(formulario_id):
    """
    Peça 2 — salva o link da pasta na nuvem para um Post satélite.
    O operador cola o link à mão (Drive/Dropbox/etc.). A criação automática
    via API Drive é fatia futura.
    """
    link = request.form.get("link_recebidos", "").strip()
    resultado = {"ok": False, "motivo": "banco_indisponivel"}
    if BANCO_DISPONIVEL:
        try:
            conn = bd.obter_conexao()
            atualizado = bd.definir_link_recebidos(conn, formulario_id, link)
            conn.close()
            resultado = {"ok": atualizado, "motivo": "" if atualizado else "post_inexistente"}
        except Exception as erro:
            logger.error(f"LINK RECEBIDOS | Erro | Post {formulario_id} | {erro}")
            resultado = {"ok": False, "motivo": f"erro_interno: {erro}"}
    if resultado.get("ok"):
        logger.info(f"LINK RECEBIDOS | Post {formulario_id} | link={'<vazio>' if not link else link[:60]}")
    return redirect(f"/?ok=link_salvo#{formulario_id}" if resultado.get("ok")
                    else f"/?aviso=link_nao_salvo#{formulario_id}")


@app.route("/post/<int:formulario_id>/recebido-pronto", methods=["POST"])
def post_recebido_pronto(formulario_id):
    """
    Peça 3 — gatilho do operador: sinaliza que o material do Post satélite chegou
    e está pronto para cópia. SÓ MARCA — NÃO dispara cópia.

    PRÓXIMA FATIA: a Camada 2 (copiador.py/transferencia.py) vai monitorar o flag
    'recebido_pronto' e iniciar a cópia a partir da pasta local de recebidos.
    """
    resultado = {"ok": False, "motivo": "banco_indisponivel"}
    if BANCO_DISPONIVEL:
        try:
            conn = bd.obter_conexao()
            resultado = bd.marcar_recebido_pronto(conn, formulario_id)
            conn.close()
        except Exception as erro:
            logger.error(f"RECEBIDO PRONTO | Erro | Post {formulario_id} | {erro}")
            resultado = {"ok": False, "motivo": f"erro_interno: {erro}"}
    if resultado.get("ok"):
        logger.info(f"RECEBIDO PRONTO | Post {formulario_id} marcado como pronto para cópia")
    else:
        logger.warning(f"RECEBIDO PRONTO | Não marcado | Post {formulario_id} | {resultado.get('motivo')}")
    return redirect(f"/?ok=recebido_pronto#{formulario_id}" if resultado.get("ok")
                    else f"/?aviso={resultado.get('motivo', 'erro')}#{formulario_id}")


@app.route("/post/<int:formulario_id>/copiar-recebido", methods=["POST"])
def post_copiar_recebido(formulario_id):
    """
    Fatia 4 — dispara a cópia real do material de um Post satélite.

    Pré-requisito: o Post deve ter origem_material='recebido' e recebido_pronto=1
    (o botão "📥 Material recebido — pronto para copiar" já foi clicado).
    A pasta RECEBIDOS/<NOME_id>/ deve existir e ter arquivos.

    Ações ao clicar:
      1. Chama transferencia.copiar_material_recebido() que faz o ciclo completo:
         registro do cartão virtual → match automático → copiador.py (MD5) →
         validação → PDF → resultado no banco.
      2. Em caso de sucesso: pasta de origem renomeada para <slug>_COPIADO.
      3. Redireciona com banner ?ok= ou ?aviso= conforme o resultado.

    Esta rota bloqueia até a cópia terminar. Para arquivos grandes, o Flask pode
    parecer travado — é esperado (o motor de cópia é síncrono e garante a integridade
    antes de retornar). Em uma próxima fatia, isso pode ser delegado a um thread/fila.
    """
    logger.info(f"COPIAR RECEBIDO | Botão acionado | Post {formulario_id}")

    # Guarda defensiva: banco deve estar disponível
    if not BANCO_DISPONIVEL:
        logger.error(f"COPIAR RECEBIDO | Banco indisponível | Post {formulario_id}")
        return redirect(f"/?aviso=banco_indisponivel#{formulario_id}")

    # Verifica rapidamente se o Post existe e está pronto ANTES de importar
    # transferencia (que pode ser pesado) — resposta rápida em caso de erro simples.
    try:
        conn_check = bd.obter_conexao()
        row_check = conn_check.execute(
            "SELECT id, nome, origem_material, recebido_pronto, status "
            "FROM formularios WHERE id = ?",
            (formulario_id,)
        ).fetchone()
        conn_check.close()
    except Exception as erro:
        logger.error(f"COPIAR RECEBIDO | Erro ao verificar Post | {erro}")
        return redirect(f"/?aviso=erro_interno#{formulario_id}")

    if row_check is None:
        return redirect(f"/?aviso=post_inexistente#{formulario_id}")
    if (row_check["origem_material"] or "cartao") != "recebido":
        return redirect(f"/?aviso=nao_e_recebido#{formulario_id}")
    if not row_check["recebido_pronto"]:
        return redirect(f"/?aviso=nao_esta_pronto#{formulario_id}")

    # Dispara a cópia (bloqueante até a cópia terminar)
    try:
        import transferencia as _transf
        resultado = _transf.copiar_material_recebido(formulario_id)
    except Exception as erro:
        logger.error(f"COPIAR RECEBIDO | Exceção inesperada | Post {formulario_id} | {erro}")
        return redirect(f"/?aviso=erro_interno#{formulario_id}")

    if resultado.get("ok"):
        numero = resultado.get("numero_cartao", "")
        logger.info(
            f"COPIAR RECEBIDO | Concluído | Post {formulario_id} | "
            f"Cartão {numero} | Destino: {resultado.get('destino')}"
        )
        return redirect(f"/?ok=copia_recebido_ok_{numero}#{formulario_id}")
    else:
        motivo = resultado.get("motivo", "erro_desconhecido")
        logger.warning(
            f"COPIAR RECEBIDO | Falhou | Post {formulario_id} | Motivo: {motivo}"
        )
        return redirect(f"/?aviso={motivo}#{formulario_id}")


def _celula_planilha(col, linha, chips, textos=None):
    """
    Renderiza o valor de uma célula da planilha em HTML.

    O VALOR vem do montador compartilhado (bd.valor_celula_planilha) — a mesma
    fonte do exportador do Google Sheets, para os dois nunca divergirem. Aqui só
    cuidamos da apresentação: escape de HTML e o destaque do 2º nome (áudio).

    Args:
        col:    dict do molde enriquecido com tipo_render e campo.
        linha:  linha do banco (sqlite3.Row).
        chips:  lista de chips desta ficha (bd.chips_por_formulario).
        textos: dict {grupo_chave: [valores]} desta ficha (bd.textos_por_formulario).
    """
    if col.get("tipo_render") == "especial":  # Profissional + 2º nome de áudio (HTML rico)
        profissional = linha["prof_nome"]
        if not profissional and linha["numero_cartao"]:
            profissional = linha["numero_cartao"].rsplit("_", 1)[0]
        html_val = _esc(profissional) or "—"
        if linha["prof_nome_audio"]:
            html_val += (f' <span style="color:var(--6f-texto-2);font-size:0.85em">'
                         f'+ {_esc(linha["prof_nome_audio"])} (áudio)</span>')
        return html_val

    return _esc(bd.valor_celula_planilha(col, linha, chips, textos))


def _colunas_visiveis():
    """
    Colunas visíveis da planilha (delega ao montador compartilhado em banco_dados).

    O Flask (HTML) e o exportador do Google Sheets leem as colunas DAQUI — fonte
    única, nunca divergem.
    """
    _garantir_molde()
    if not BANCO_DISPONIVEL:
        # Fallback sem banco: catálogo inteiro visível
        return [
            {"chave": e[0], "rotulo": e[1], "bloco": e[2],
             "tipo_render": e[3], "campo": e[4], "visivel": True, "sistema": True}
            for e in CATALOGO_PLANILHA if e[5]
        ]
    try:
        conn = bd.obter_conexao()
        cols = bd.colunas_planilha(conn)
        conn.close()
        return cols
    except Exception as e:
        logger.error(f"MOLDE | Erro ao listar | {e}")
        return []


def _celula_transcricao(linha):
    """HTML da célula da coluna "Transcrição" (Camada 6) — STATUS compacto, nunca o texto.

    O texto inteiro mora POR ARQUIVO na tabela `arquivos` e se lê na tela
    /cartao/<id>/transcricao — aqui a célula só indica o estado, para não inchar
    a planilha. Estados:
      • já transcrito        → "✓ N áudio(s)" + link "ver" (abre a tela por arquivo)
      • transcrevendo agora  → "⏳ transcrevendo…"
      • cartão de áudio copiado, ainda não transcrito → botão "🎙 Transcrever"
      • qualquer outro caso (não é áudio, sem destino) → "—"
    """
    cartao_id = linha["id"]
    try:
        n_transcritos = linha["n_transcritos"] or 0
    except (IndexError, KeyError):
        n_transcritos = 0
    if n_transcritos:
        return (f'✓ {n_transcritos} áudio(s) '
                f'<a href="/cartao/{cartao_id}/transcricao" '
                f'style="color:var(--6f-teal);font-size:0.85em">ver</a>')

    with _lock_transcricao:
        rodando = cartao_id in _transcricoes_em_andamento
    if rodando:
        return '<span style="color:var(--6f-aviso)">⏳ transcrevendo…</span>'

    # Elegível: cartão de ÁUDIO já copiado (tem pasta de destino). Primeiro tijolo:
    # só áudio (a trilha dos vídeos fica para uma fatia futura).
    tipo = (linha["tipo_material"] or "").strip().upper()
    destino = (linha["destino_pasta"] or "").strip()
    if tipo == "AUDIO" and destino and _transcricao_disponivel():
        return (f'<form method="POST" action="/cartao/{cartao_id}/transcrever" style="margin:0">'
                f'<button type="submit" style="font-size:0.82em;padding:3px 8px;'
                f'background:var(--6f-teal);color:var(--6f-bg-base);border:none;border-radius:4px;cursor:pointer">'
                f'🎙 Transcrever</button></form>')
    return "—"


@app.route("/planilha", methods=["GET"])
def planilha():
    """
    Aba PLANILHA — a Planilha de Análise / Entrega (Acesso 3), versão local.

    É o espelho do que vai para o Google Sheets (Camada 3): só metadados, nunca
    a mídia. Lê do banco juntando cartão + formulário (pelo match mais recente).
    As colunas renderizadas respeitam o molde configurado em /molde.

    Camada 6 — Missão A (Fatia 1): aceita ?busca=<termos> para filtrar/destacar
    linhas no servidor, cruzando identificação + classificação + transcrição.
    A busca é SERVER-SIDE (para alcançar o texto de transcrição, que não aparece
    nas células da tabela) e complementa o filtro JS rápido existente.
    """
    if not BANCO_DISPONIVEL:
        corpo = "<p class='vazio'>Banco de dados indisponível.</p>"
        return _pagina("Entrega", "planilha", corpo), 200, {"Content-Type": "text/html; charset=utf-8"}

    colunas = _colunas_visiveis()
    n_cols = len(colunas) or 1

    # Duas formas de buscar, ambas server-side (alcançam transcrição/classificação
    # que podem não estar na célula visível), diferentes do filtro JS rápido:
    #   • ?busca=     → busca MECÂNICA (Missão A, Fatia 1): palavras exatas.
    #   • ?pergunta=  → busca CONVERSACIONAL (Fatia 2): a IA traduz a pergunta em
    #                   linguagem natural e redige uma resposta. Só liga se a IA
    #                   estiver disponível (real/simulado); senão cai na mecânica.
    termo_busca = (request.args.get("busca") or "").strip()
    pergunta_ia = (request.args.get("pergunta") or "").strip()
    estado_ia = aia.estado_ia() if AIA_OK else "desligado"
    resposta_ia = None          # texto conversacional, quando houver pergunta
    usou_ia = False             # True quando a Fatia 2 respondeu de verdade

    try:
        conn = bd.obter_conexao()
        linhas = conn.execute(bd._SQL_PLANILHA).fetchall()
        form_ids = [l["form_id"] for l in linhas if l["form_id"]]
        chips_map = bd.chips_por_formulario(conn, form_ids) if form_ids else {}
        textos_map = bd.textos_por_formulario(conn, form_ids) if form_ids else {}

        # Busca profunda: monta o índice de resultados antes de renderizar as linhas.
        # resultados_busca: {(cartao_id, form_id) → dict com campos_bateram e arquivos}
        resultados_busca = {}
        if pergunta_ia and estado_ia != "desligado":
            # Fatia 2: a IA traduz, busca (Fatia 1 por dentro) e redige.
            res_ia = aia.responder(conn, pergunta_ia)
            resposta_ia = res_ia.get("resposta")
            usou_ia = True
            for res in res_ia.get("resultados", []):
                resultados_busca[(res["cartao_id"], res["form_id"])] = res
            termo_busca = pergunta_ia   # reusa o filtro/legenda das linhas
        elif termo_busca:
            for res in bd.buscar_na_planilha(conn, termo_busca):
                chave = (res["cartao_id"], res["form_id"])
                resultados_busca[chave] = res

        conn.close()
    except Exception as erro:
        logger.error(f"PLANILHA | Erro ao ler | {erro}")
        linhas = []
        chips_map = {}
        textos_map = {}
        resultados_busca = {}

    # ── Renderização das linhas ───────────────────────────────────────────────
    # Com busca ativa: só exibe linhas que bateram, com destaque e painel de arquivos.
    # Sem busca: exibe todas as linhas (comportamento original).
    linhas_html = ""
    for linha in linhas:
        chips  = chips_map.get(linha["form_id"], [])
        textos = textos_map.get(linha["form_id"], {})
        chave_linha = (linha["id"], linha["form_id"])

        # Com busca ativa: filtra no servidor (só mostra linhas que bateram)
        if termo_busca and chave_linha not in resultados_busca:
            continue

        celulas = "".join(
            f'<td class="{"mono" if c["chave"] == "destino_pasta" else ""}">'
            f'{_celula_transcricao(linha) if c["chave"] == "transcricao" else _celula_planilha(c, linha, chips, textos)}</td>'
            for c in colunas
        )

        # Painel de detalhe da busca: mostra quais arquivos contribuíram via transcrição
        painel_busca = ""
        if termo_busca and chave_linha in resultados_busca:
            res = resultados_busca[chave_linha]
            arqs = res.get("arquivos_transcritos", [])
            if arqs:
                itens_arq = "".join(
                    f'<li style="margin-bottom:4px"><strong>{_esc(a["nome_arquivo"])}</strong>'
                    f' — <em style="color:var(--6f-texto-2)">{_esc(a["trecho"])}</em>'
                    f' <a href="/cartao/{linha["id"]}/transcricao" '
                    f'style="color:var(--6f-teal);font-size:0.82em;white-space:nowrap">ver transcrição</a></li>'
                    for a in arqs
                )
                painel_busca = (
                    f'<tr class="busca-detalhe">'
                    f'<td colspan="{n_cols}" style="background:var(--6f-teal-trilho);padding:6px 14px;'
                    f'font-size:0.82em;border-bottom:2px solid var(--6f-teal)">'
                    f'Transcrição: <ul style="margin:4px 0 0 16px;padding:0">{itens_arq}</ul>'
                    f'</td></tr>'
                )
            # Destaque visual na linha que bateu
            linhas_html += (
                f'<tr style="background:var(--6f-teal-trilho);outline:2px solid var(--6f-teal)">{celulas}</tr>'
                + painel_busca
            )
        else:
            linhas_html += f"<tr>{celulas}</tr>"

    if not linhas_html:
        msg = (
            f"Nenhum resultado para <strong>{_esc(termo_busca)}</strong>."
            if termo_busca
            else "Nenhum cartão no banco ainda."
        )
        linhas_html = f"<tr><td colspan='{n_cols}' class='coluna-vazia'>{msg}</td></tr>"

    cabecalhos = "".join(f"<th>{_esc(c['rotulo'])}</th>" for c in colunas)

    # ── Banners de feedback ───────────────────────────────────────────────────
    _msg_ok = (request.args.get("ok") or "").strip()
    _msg_aviso = (request.args.get("aviso") or "").strip()
    _avisos_transc = {
        "transcricao_iniciada":      "Transcrição iniciada — o texto aparece aqui quando terminar (recarregue em instantes).",
        "transcricao_ja_rodando":    "Este cartão já está sendo transcrito. Aguarde terminar.",
        "transcricao_indisponivel":  "O motor de transcrição (IA) não está instalado nesta máquina.",
        "sem_destino":               "Este cartão não tem pasta de material copiado para transcrever.",
        "cartao_inexistente":        "Cartão não encontrado no banco.",
        "banco_indisponivel":        "O banco de dados não está disponível.",
        "erro_interno":              "Ocorreu um erro interno. Verifique os logs.",
    }
    bloco_feedback = ""
    if _msg_ok == "transcricao_iniciada":
        bloco_feedback = ("<div style='background:var(--6f-teal-trilho);border:1px solid var(--6f-ok);"
                          "color:var(--6f-texto);"
                          "border-radius:6px;padding:10px 14px;margin-bottom:12px;font-size:0.9em'>"
                          f"✓ {_avisos_transc['transcricao_iniciada']}</div>")
    elif _msg_aviso:
        bloco_feedback = ("<div style='background:var(--6f-bg-elevado);border:1px solid var(--6f-aviso);"
                          "color:var(--6f-aviso);"
                          "border-radius:6px;padding:10px 14px;margin-bottom:12px;font-size:0.9em'>"
                          f"{_esc(_avisos_transc.get(_msg_aviso, _msg_aviso))}</div>")

    # ── Barra de busca profunda (Missão A, Fatia 1) ───────────────────────────
    # Convive com o filtro JS rápido (que filtra no texto visível na tela):
    #   • Busca profunda (formulário POST → GET): alcança transcrição + classificação
    #     no servidor; ao submeter, recarrega a página mostrando só as linhas que batem.
    #   • Filtro rápido JS (campo de texto instant): filtra o que já está na tela,
    #     útil para afinar o resultado depois de uma busca, ou para filtros simples.
    n_resultados = len(resultados_busca) if termo_busca else None
    legenda_busca = ""
    if termo_busca and n_resultados is not None:
        cor = "var(--6f-ok)" if n_resultados else "var(--6f-aviso)"
        legenda_busca = (
            f'<span style="font-size:0.85em;color:{cor};margin-left:8px">'
            f'{n_resultados} resultado(s) para "{_esc(termo_busca)}"'
            f' — <a href="/planilha" style="color:{cor}">limpar</a></span>'
        )

    # ── Caixa de resposta da IA (Missão A, Fatia 2) ───────────────────────────
    # Só aparece quando a IA respondeu de fato. A resposta é texto; as LINHAS
    # destacadas continuam vindo da busca mecânica (a verdade), nunca da IA.
    bloco_ia = ""
    if usou_ia and resposta_ia:
        rotulo_estado = {"real": "🤖 Assistente IA",
                         "simulado": "🤖 Assistente IA · modo simulado (sem custo)"}.get(
                             estado_ia, "🤖 Assistente IA")
        resposta_html = _esc(resposta_ia).replace("\n", "<br>")
        bloco_ia = (
            f'<div style="background:var(--6f-teal-trilho);border:1px solid var(--6f-teal);'
            f'border-left:4px solid var(--6f-teal);border-radius:8px;padding:12px 16px;margin-bottom:12px">'
            f'<div style="font-size:0.76em;color:var(--6f-teal-claro);font-weight:600;margin-bottom:5px">'
            f'{rotulo_estado}</div>'
            f'<div style="font-size:0.92em;color:var(--6f-texto);line-height:1.45">{resposta_html}</div></div>'
        )

    # ── Barra de busca: conversacional (se a IA estiver ligada) + mecânica ─────
    if estado_ia != "desligado":
        placeholder_ia = ("pergunte em linguagem natural… "
                          "ex.: take do pôr do sol com a marca patrocinadora")
        barra_html = f"""
    <form method="GET" action="/planilha" style="display:flex;gap:8px;align-items:center;margin-bottom:8px">
        <input type="text" name="pergunta" value="{_esc(pergunta_ia)}"
               placeholder="{placeholder_ia}"
               style="flex:1;max-width:560px;padding:9px 12px;border:1px solid var(--6f-teal);
                      background:var(--6f-bg-elevado);color:var(--6f-texto);
                      border-radius:6px;font-size:0.9em"
               title="A IA entende a pergunta em linguagem natural, busca no acervo e redige a resposta.">
        <button type="submit"
                style="padding:9px 18px;background:var(--6f-teal);color:var(--6f-bg-base);border:none;
                       border-radius:6px;cursor:pointer;font-size:0.9em">🤖 Perguntar</button>
    </form>
    <form method="GET" action="/planilha" style="display:flex;gap:8px;align-items:center;margin-bottom:10px">
        <input type="text" name="busca" value="{_esc('' if usou_ia else termo_busca)}"
               placeholder="ou busca exata por palavras… palco, marca, profissional, data"
               style="flex:1;max-width:560px;padding:7px 12px;border:1px solid var(--6f-borda);
                      background:var(--6f-bg-elevado);color:var(--6f-texto);
                      border-radius:6px;font-size:0.85em">
        <button type="submit"
                style="padding:7px 14px;background:var(--6f-bg-elevado);color:var(--6f-teal);
                       border:1px solid var(--6f-teal);
                       border-radius:6px;cursor:pointer;font-size:0.85em">Buscar</button>
    </form>"""
    else:
        barra_html = f"""
    <form method="GET" action="/planilha" style="display:flex;gap:8px;align-items:center;margin-bottom:10px">
        <input type="text" name="busca" value="{_esc(termo_busca)}"
               placeholder="buscar… transcrição, palco, marca, profissional, data"
               style="flex:1;max-width:480px;padding:8px 12px;border:1px solid var(--6f-teal);
                      background:var(--6f-bg-elevado);color:var(--6f-texto);
                      border-radius:6px;font-size:0.9em"
               title="Busca profunda: alcança transcrições de áudio e classificação completa.
Múltiplas palavras = AND. Exemplo: sunset volkswagen">
        <button type="submit"
                style="padding:8px 16px;background:var(--6f-teal);color:var(--6f-bg-base);border:none;
                       border-radius:6px;cursor:pointer;font-size:0.9em">Buscar</button>
    </form>"""

    corpo = f"""
    {bloco_feedback}
    <div style="display:flex;gap:10px;align-items:flex-start;flex-wrap:wrap;margin-bottom:12px">
        <p class="legenda" style="margin:0;flex:1;min-width:180px">
            Espelho local da entrega — é o que vai para o Google Sheets
            (só informação, nunca o vídeo).</p>
        <a href="/molde" style="font-size:0.85em;color:var(--6f-teal);white-space:nowrap;align-self:center">
          ⚙ Configurar colunas</a>
    </div>

    {bloco_ia}
    {barra_html}
    {legenda_busca}

    <input type="text" id="filtro" class="filtro"
           placeholder="filtrar na tela… (afina o resultado acima)"
           style="margin-bottom:10px">

    <table class="planilha-tabela" id="tabela">
        <thead><tr>{cabecalhos}</tr></thead>
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
    return _pagina("Entrega", "planilha", corpo, head_extra), 200, {"Content-Type": "text/html; charset=utf-8"}


# ── ROTA: MOLDE DA PLANILHA (/molde) ─────────────────────────────────────────

@app.route("/molde", methods=["GET"])
def molde_planilha():
    """
    Página de configuração do molde da planilha.

    O operador pode aqui:
      - Ocultar/mostrar colunas individualmente (toggle)
      - Ocultar/mostrar um bloco inteiro de uma vez
      - Adicionar colunas personalizadas (nome + bloco)
      - Excluir colunas personalizadas que não são mais necessárias
    Colunas do sistema só podem ser ocultadas, nunca excluídas.
    """
    _garantir_molde()
    if not BANCO_DISPONIVEL:
        corpo = "<p class='vazio'>Banco de dados indisponível.</p>"
        return _pagina("Configurar Colunas", "molde", corpo), 200, {"Content-Type": "text/html; charset=utf-8"}

    try:
        conn = bd.obter_conexao()
        todas = bd.listar_molde(conn)
        conn.close()
    except Exception as e:
        logger.error(f"MOLDE | Erro ao listar | {e}")
        todas = []

    # Agrupa por bloco respeitando BLOCOS_PLANILHA como ordem
    ordem_blocos = [b[0] for b in BLOCOS_PLANILHA]
    rotulos_blocos = dict(BLOCOS_PLANILHA)
    por_bloco = {b: [] for b in ordem_blocos}
    for col in todas:
        bloco = col["bloco"] if col["bloco"] in por_bloco else "custom"
        por_bloco.setdefault(bloco, []).append(col)

    secoes_html = ""
    for bloco_chave in ordem_blocos:
        cols_bloco = por_bloco.get(bloco_chave, [])
        if not cols_bloco:
            continue
        rotulo_bloco = rotulos_blocos.get(bloco_chave, bloco_chave)

        n_visiveis = sum(1 for c in cols_bloco if c["visivel"])
        cor_bloco = "var(--6f-teal)" if n_visiveis == len(cols_bloco) else ("var(--6f-aviso)" if n_visiveis else "var(--6f-texto-3)")

        linhas_col = ""
        for col in cols_bloco:
            vis = col["visivel"]
            btn_label = "Ocultar" if vis else "Mostrar"
            btn_cor = "var(--6f-erro)" if vis else "var(--6f-teal)"
            badge_vis = (f'<span style="color:var(--6f-teal);font-size:0.8em">● visível</span>'
                         if vis else
                         f'<span style="color:var(--6f-texto-3);font-size:0.8em">○ oculta</span>')
            # As colunas vêm só dos grupos cadastrados e do sistema — não há mais
            # coluna "personalizada" solta (s33). Por isso, sem selo nem excluir aqui:
            # para tirar uma coluna de classificação, exclui-se o GRUPO na aba Listas.
            badge_sis = ""
            btn_excluir = ""
            linhas_col += f"""
            <tr style="border-bottom:1px solid var(--6f-borda)">
              <td style="padding:8px 12px">{_esc(col['rotulo'])}{badge_sis}</td>
              <td style="padding:8px 12px">{badge_vis}</td>
              <td style="padding:8px 12px;text-align:right">
                <form method="post" action="/molde/{_esc(col['chave'])}/visivel" style="display:inline">
                  <input type="hidden" name="visivel" value="{'0' if vis else '1'}">
                  <button type="submit" style="background:{btn_cor};color:var(--6f-bg-base);border:none;
                    border-radius:4px;padding:3px 10px;cursor:pointer;font-size:0.82em">
                    {btn_label}
                  </button>
                </form>
                {btn_excluir}
              </td>
            </tr>"""

        # Botões de bloco inteiro (ocultar/mostrar tudo)
        todos_vis = all(c["visivel"] for c in cols_bloco)
        todos_oc = not any(c["visivel"] for c in cols_bloco)
        btn_bloco = ""
        if not todos_oc:
            btn_bloco += (
                f'<form method="post" action="/molde/bloco/{bloco_chave}/ocultar" style="display:inline">'
                f'<button type="submit" style="background:none;border:1px solid var(--6f-borda);'
                f'border-radius:4px;padding:2px 8px;cursor:pointer;font-size:0.78em;color:var(--6f-texto-2)">'
                f'Ocultar bloco</button></form> '
            )
        if not todos_vis:
            btn_bloco += (
                f'<form method="post" action="/molde/bloco/{bloco_chave}/mostrar" style="display:inline">'
                f'<button type="submit" style="background:none;border:1px solid var(--6f-teal);'
                f'border-radius:4px;padding:2px 8px;cursor:pointer;font-size:0.78em;color:var(--6f-teal)">'
                f'Mostrar bloco</button></form>'
            )

        secoes_html += f"""
        <div style="background:var(--6f-bg-superficie);border:1px solid var(--6f-borda);border-radius:8px;
                    margin-bottom:18px;overflow:hidden">
          <div style="background:var(--6f-bg-elevado);padding:10px 16px;display:flex;
                      align-items:center;justify-content:space-between">
            <span style="font-weight:600;color:{cor_bloco}">{_esc(rotulo_bloco)}</span>
            <span style="font-size:0.82em;color:var(--6f-texto-2)">{n_visiveis}/{len(cols_bloco)} visíveis
              &nbsp;{btn_bloco}</span>
          </div>
          <table style="width:100%;border-collapse:collapse">
            <tbody>{linhas_col}</tbody>
          </table>
        </div>"""

    corpo = f"""
    <div style="display:flex;gap:10px;align-items:center;margin-bottom:16px">
      <div style="flex:1">
        <h2 style="margin:0;font-size:1.1em">Configurar colunas da planilha</h2>
        <p style="margin:4px 0 0 0;font-size:0.85em;color:var(--6f-texto-2)">
          Ligue/desligue as colunas. As colunas de classificação vêm dos grupos
          cadastrados na aba <a href="/listas" style="color:var(--6f-teal)">Programação</a> —
          para criar ou remover uma, mexa nos grupos lá.
        </p>
      </div>
      <a href="/planilha" style="font-size:0.85em;color:var(--6f-teal)">← Voltar à planilha</a>
    </div>
    {secoes_html}"""

    return _pagina("Configurar Colunas", "molde", corpo), 200, {"Content-Type": "text/html; charset=utf-8"}


@app.route("/molde/<chave>/visivel", methods=["POST"])
def molde_toggle(chave):
    """Liga ou desliga a visibilidade de uma coluna."""
    if not BANCO_DISPONIVEL:
        return redirect("/molde", 303)
    visivel = request.form.get("visivel", "1") == "1"
    try:
        conn = bd.obter_conexao()
        bd.definir_visivel_coluna(conn, chave, visivel)
        conn.close()
    except Exception as e:
        logger.error(f"MOLDE | toggle {chave} | {e}")
    return redirect("/molde", 303)


@app.route("/dia-ativo", methods=["POST"])
def dia_ativo_definir():
    """
    Troca o dia ATIVO da programação (cobertura de festival). A ficha passa a
    mostrar os shows desse dia. Só local — o portão de acesso já bloqueia o
    remoto (a câmera não troca o dia, só preenche).
    """
    if not BANCO_DISPONIVEL:
        return redirect("/ficha", 303)
    data = (request.form.get("data") or "").strip()
    if data:
        try:
            conn = bd.obter_conexao()
            bd.definir_dia_ativo(conn, data)
            conn.close()
        except Exception as e:
            logger.error(f"PROGRAMACAO | dia-ativo {data} | {e}")
    return redirect(request.referrer or "/ficha", 303)


@app.route("/programacao/add-show", methods=["POST"])
def programacao_add_show():
    """
    Adiciona um show ao DIA ATIVO num palco (Fatia B2 — edição ao vivo do line-up).
    Cria o show como item do grupo Show e liga em `programacao`. Só local (o portão
    barra remoto). Generaliza para qualquer evento com agenda (ex.: RIO2C — uma
    palestra numa sala num dia).
    """
    if not BANCO_DISPONIVEL:
        return ("", 204)
    nome = (request.form.get("nome") or "").strip()
    palco_id = (request.form.get("palco_item_id") or "").strip()
    if not (nome and palco_id):
        return ("faltou nome ou palco", 400)
    try:
        conn = bd.obter_conexao()
        dia = bd.dia_ativo(conn)
        # Descobre a chave do grupo Show (o tipo dos shows da programação; se ainda
        # não há programação, cai no grupo cujo rótulo é "Show").
        r = conn.execute("SELECT lc.tipo FROM programacao p "
                         "JOIN listas_contexto lc ON lc.id = p.show_item_id LIMIT 1").fetchone()
        show_chave = r[0] if r else None
        if not show_chave:
            r2 = conn.execute("SELECT chave FROM grupos_classificacao "
                              "WHERE LOWER(rotulo) = 'show'").fetchone()
            show_chave = r2[0] if r2 else None
        if show_chave:
            try:
                bd.adicionar_item_lista(conn, show_chave, nome)
            except Exception:
                pass  # já existia
            row = conn.execute("SELECT id FROM listas_contexto WHERE tipo = ? AND valor = ?",
                               (show_chave, nome)).fetchone()
            if row:
                bd.adicionar_programacao(conn, dia, int(palco_id), row[0])
        conn.close()
    except Exception as e:
        logger.error(f"PROGRAMACAO | add-show '{nome}' | {e}")
        return ("erro", 500)
    return ("ok", 200)


@app.route("/molde/bloco/<bloco_chave>/ocultar", methods=["POST"])
def molde_bloco_ocultar(bloco_chave):
    """Oculta todas as colunas de um bloco de uma vez."""
    if not BANCO_DISPONIVEL:
        return redirect("/molde", 303)
    try:
        conn = bd.obter_conexao()
        for col in bd.listar_molde(conn):
            if col["bloco"] == bloco_chave:
                bd.definir_visivel_coluna(conn, col["chave"], False)
        conn.close()
    except Exception as e:
        logger.error(f"MOLDE | ocultar bloco {bloco_chave} | {e}")
    return redirect("/molde", 303)


@app.route("/molde/bloco/<bloco_chave>/mostrar", methods=["POST"])
def molde_bloco_mostrar(bloco_chave):
    """Torna visíveis todas as colunas de um bloco de uma vez."""
    if not BANCO_DISPONIVEL:
        return redirect("/molde", 303)
    try:
        conn = bd.obter_conexao()
        for col in bd.listar_molde(conn):
            if col["bloco"] == bloco_chave:
                bd.definir_visivel_coluna(conn, col["chave"], True)
        conn.close()
    except Exception as e:
        logger.error(f"MOLDE | mostrar bloco {bloco_chave} | {e}")
    return redirect("/molde", 303)


# NOTA (s33): as rotas /molde/nova e /molde/<chave>/excluir foram removidas — não
# há mais "coluna personalizada" solta. As colunas de classificação vêm dos grupos
# (aba Listas); criar/remover coluna = criar/excluir grupo. O Molde só liga/desliga.


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
    .ficha-form { background:var(--6f-bg-superficie); border-radius:8px;
                  border:1px solid var(--6f-borda); box-shadow:none;
                  padding:22px 24px; max-width:680px; }
    .ficha-grid { display:grid; grid-template-columns:1fr 1fr; gap:14px 18px; }
    .campo { display:flex; flex-direction:column; gap:5px; }
    .campo.largo { grid-column:1 / -1; }
    .campo label { font-size:0.82em; font-weight:700; color:var(--6f-texto-2); }
    .campo .estrela { color:var(--6f-erro); }
    .campo .ajuda { font-weight:400; color:var(--6f-texto-3); font-size:0.92em; }
    .campo input, .campo select, .campo textarea {
        padding:9px 11px; border:1px solid var(--6f-borda); border-radius:6px;
        font-family:inherit; font-size:0.95em; background:var(--6f-bg-elevado); color:var(--6f-texto); }
    .campo input::placeholder, .campo textarea::placeholder { color:var(--6f-texto-3); }
    .campo textarea { min-height:64px; resize:vertical; }
    .grupo-titulo { grid-column:1 / -1; font-size:0.78em; font-weight:700; color:var(--6f-texto-3);
                    text-transform:uppercase; letter-spacing:0.5px; margin-top:8px;
                    border-top:1px solid var(--6f-borda); padding-top:14px; }
    .ficha-acoes { margin-top:20px; display:flex; gap:12px; align-items:center; }
    .btn-enviar { background:var(--6f-teal); color:var(--6f-bg-base); border:none; border-radius:6px;
                  padding:11px 28px; font-weight:700; font-size:0.95em; cursor:pointer; }
    .btn-enviar:hover { background:var(--6f-teal-forte); }
    .erro-box { background:var(--6f-bg-elevado); border:1px solid var(--6f-erro); color:var(--6f-erro);
                border-radius:6px; padding:11px 14px; margin-bottom:16px; font-size:0.9em; }
    .ok-box { background:var(--6f-teal-trilho); border:1px solid var(--6f-teal); color:var(--6f-texto);
              border-radius:8px; padding:20px 24px; max-width:680px; }
    .ok-box h2 { font-size:1.15em; margin-bottom:10px; }
    .ok-box .resumo { background:var(--6f-bg-elevado); border-radius:6px; padding:12px 16px; margin:12px 0;
                      color:var(--6f-texto); font-size:0.92em; line-height:1.7; }
    .ok-box .resumo b { display:inline-block; min-width:120px; color:var(--6f-texto-2); font-weight:600; }
    .btn-secundario { display:inline-block; background:var(--6f-bg-elevado); color:var(--6f-texto); text-decoration:none;
                      border:1px solid var(--6f-borda); border-radius:6px; padding:10px 20px; font-weight:600; font-size:0.9em; }
    .dica-gabarito { font-weight:400; color:var(--6f-texto-3); font-size:0.88em; }
    .campo input:disabled, .campo select:disabled {
        background:var(--6f-bg-hover); color:var(--6f-texto-3); cursor:not-allowed; }
    .aviso-trava { background:var(--6f-bg-elevado); border:1px solid var(--6f-aviso); color:var(--6f-aviso);
                   border-radius:6px; padding:10px 14px; margin-bottom:14px; font-size:0.88em; }
    /* ── Lista de fichas recentes (editar) ── */
    .recentes { margin-top:30px; max-width:880px; }
    .recentes h2 { font-size:1em; color:var(--6f-texto-2); margin-bottom:10px; }
    .tab-recentes { width:100%; border-collapse:collapse; background:var(--6f-bg-superficie); border-radius:8px;
                    overflow:hidden; box-shadow:none; border:1px solid var(--6f-borda); font-size:0.86em; }
    .tab-recentes th { text-align:left; padding:8px 12px; background:var(--6f-bg-elevado); color:var(--6f-texto-2);
                       text-transform:uppercase; font-size:0.76em; letter-spacing:0.4px;
                       border-bottom:1px solid var(--6f-borda); }
    .tab-recentes td { padding:8px 12px; border-bottom:1px solid var(--6f-borda); color:var(--6f-texto); }
    .tab-recentes tr:hover td { background:var(--6f-bg-hover); }
    .badge-mini { border-radius:10px; padding:1px 8px; font-size:0.74em; font-weight:700; color:#fff; }
    .link-editar { color:var(--6f-teal); text-decoration:none; font-weight:600; }
    .link-editar:hover { text-decoration:underline; }
    /* ── Grupos recolhíveis de Posts (centro de controle) ── */
    .grupo-posts { margin-bottom:12px; }
    .grupo-posts > summary { cursor:pointer; padding:9px 14px; background:var(--6f-bg-elevado);
        border-radius:8px; font-weight:600; font-size:0.9em; color:var(--6f-texto-2);
        list-style:none; user-select:none; }
    .grupo-posts > summary::-webkit-details-marker { display:none; }
    .grupo-posts > summary::before { content:"▸ "; color:var(--6f-texto-3); }
    .grupo-posts[open] > summary::before { content:"▾ "; }
    .grupo-posts[open] > summary { border-radius:8px 8px 0 0; }
    .grupo-posts .tab-recentes { border-radius:0 0 8px 8px; margin-top:0; }
    .grupo-posts .badge { background:var(--6f-bg-hover); color:var(--6f-texto-2); border-radius:10px;
        padding:1px 9px; font-size:0.82em; font-weight:700; margin-left:4px; }
    .grupo-cancelados > summary { background:var(--6f-bg-elevado); color:var(--6f-erro); }
    /* ── Tipo multi-seleção (checkboxes) ── */
    .tipo-checks { display:flex; gap:16px; align-items:center; flex-wrap:wrap; margin-top:2px; }
    .tipo-checks label { font-size:0.92em; font-weight:600; color:var(--6f-texto-2);
                         display:flex; align-items:center; gap:6px; cursor:pointer; }
    .tipo-checks input[type=checkbox] { width:17px; height:17px; cursor:pointer; accent-color:var(--6f-teal); }
    /* ── Dropdowns fechados de nome ── */
    .campo-nome-wrapper { display:flex; flex-direction:column; gap:14px; }
    .campo-nome-wrapper .campo { margin:0; }
    .aviso-sem-cadastro { font-size:0.8em; color:var(--6f-aviso); margin-top:4px; }
    /* ── Chips de classificação (listas de contexto) ── */
    .chip-area { display:flex; flex-direction:column; gap:14px; }
    .chip-bloco { display:flex; flex-direction:column; gap:7px; }
    .chip-rotulo { font-size:0.82em; font-weight:700; color:var(--6f-texto-2); }
    .chip-linha { display:flex; flex-wrap:wrap; gap:8px; }
    .chip { position:relative; display:inline-flex; align-items:center; cursor:pointer;
            user-select:none; border:1px solid var(--6f-borda); border-radius:16px;
            padding:5px 13px; font-size:0.88em; color:var(--6f-texto); background:var(--6f-bg-elevado);
            transition:background .12s, border-color .12s, color .12s; }
    .chip:hover { border-color:var(--6f-teal); }
    .chip input { position:absolute; opacity:0; width:0; height:0; margin:0; }
    .chip.sel { background:var(--6f-teal); border-color:var(--6f-teal); color:var(--6f-bg-base); font-weight:600; }
    .chip-vazio { font-size:0.84em; color:var(--6f-texto-3); font-style:italic; }
    .chip-contador { font-weight:600; font-size:0.85em; color:var(--6f-texto-3); }
    .chip-contador.tem { color:var(--6f-teal); }
    .chip-acao  { margin-top:5px; display:flex; align-items:center; gap:6px; flex-wrap:wrap; }
    .chip-btn-novo { background:none; border:1px dashed var(--6f-borda); border-radius:12px;
        padding:3px 10px; font-size:0.8em; color:var(--6f-texto-2); cursor:pointer; }
    .chip-btn-novo:hover { border-color:var(--6f-teal); color:var(--6f-teal); }
    .chip-novo-form { display:inline-flex; align-items:center; gap:4px; }
    .chip-novo-input { border:1px solid var(--6f-teal); border-radius:12px; padding:3px 10px;
        background:var(--6f-bg-elevado); color:var(--6f-texto);
        font-size:0.85em; outline:none; width:160px; }
    .chip-novo-ok, .chip-novo-cancel { background:none; border:none; cursor:pointer;
        font-size:1em; padding:0 4px; }
    .chip-novo-ok { color:var(--6f-teal); font-weight:700; }
    .chip-novo-cancel { color:var(--6f-texto-3); }
    /* Grupos de TEXTO: tags de valores livres + caixa de adicionar */
    .texto-tag { display:inline-flex; align-items:center; gap:6px; background:var(--6f-teal);
        color:var(--6f-bg-base); border-radius:16px; padding:5px 12px; font-size:0.88em; font-weight:600; }
    .texto-rm { background:none; border:none; color:var(--6f-bg-base); cursor:pointer; font-size:0.9em;
        padding:0; line-height:1; opacity:0.8; }
    .texto-rm:hover { opacity:1; }
    .texto-input { border:1px solid var(--6f-borda); border-radius:16px; padding:5px 13px;
        background:var(--6f-bg-elevado); color:var(--6f-texto);
        font-size:0.88em; font-family:inherit; outline:none; min-width:180px; }
    .texto-input:focus { border-color:var(--6f-teal); }
    .texto-add { background:none; border:1px dashed var(--6f-borda); border-radius:12px;
        padding:4px 12px; font-size:0.8em; color:var(--6f-texto-2); cursor:pointer; }
    .texto-add:hover { border-color:var(--6f-teal); color:var(--6f-teal); }
    /* Toggles "Quando foi gravado?" e "Quem está preenchendo?" */
    .radio-linha { display:flex; gap:18px; align-items:center; margin-top:2px; }
    .radio-op { font-size:0.92em; font-weight:600; color:var(--6f-texto-2);
                display:flex; align-items:center; gap:6px; cursor:pointer; }
    .radio-op input[type=radio] { width:16px; height:16px; cursor:pointer; accent-color:var(--6f-teal); }
    /* Toques maiores no celular: chips mais fáceis de acertar com o dedo. */
    @media (max-width: 600px) {
        .ficha-form { padding:16px 14px; }
        .ficha-grid { grid-template-columns:1fr; gap:12px; }
        .chip { padding:8px 15px; font-size:0.95em; }
        .chip-novo-input { width:100%; }
        .tipo-checks { gap:12px; }
    }
"""

# JS dos chips: torna o chip clicável (pinta quando marcado), mantém o contador de
# marcados por grupo e — se algum grupo for de escolha única (data-grupo preenchido)
# — desmarca os irmãos. Hoje todos os grupos são múltiplos (CLASSIF_UNICA vazio).
# Roda no navegador, offline, sem dependência externa. Inofensivo sem chips na página.
JS_CHIPS = """
<script>
(function(){
  function pinta(lbl){ if(lbl) lbl.classList.toggle('sel', lbl.querySelector('input').checked); }

  // Atualiza o contador de um grupo (tipo): "· 2 marcados".
  window.gmaAtualizaContador = function(tipo){
    if (!tipo) return;
    var linha = document.getElementById('chip-linha-' + tipo);
    var cont  = document.querySelector('.chip-contador[data-tipo="' + tipo + '"]');
    if (!linha || !cont) return;
    var n = linha.querySelectorAll('input[type=checkbox]:checked').length;
    cont.textContent = n ? ('· ' + n + (n > 1 ? ' marcados' : ' marcado')) : '';
    cont.classList.toggle('tem', n > 0);
  };

  function grupoDoChip(lbl){
    var linha = lbl.closest('.chip-linha');
    return linha ? linha.id.replace('chip-linha-', '') : '';
  }

  function init(){
    document.querySelectorAll('.chip input[type=checkbox]').forEach(function(inp){
      var lbl = inp.closest('.chip');
      inp.addEventListener('change', function(){
        var grupo = lbl.getAttribute('data-grupo');
        if (grupo && inp.checked) {  // escolha única: desmarca os irmãos
          document.querySelectorAll('.chip[data-grupo="'+grupo+'"] input').forEach(function(outro){
            if (outro !== inp) { outro.checked = false; pinta(outro.closest('.chip')); }
          });
        }
        pinta(lbl);
        window.gmaAtualizaContador(grupoDoChip(lbl));
      });
    });
    // Estado inicial dos contadores (edição/reabertura já com chips marcados).
    document.querySelectorAll('.chip-contador').forEach(function(c){
      window.gmaAtualizaContador(c.getAttribute('data-tipo'));
    });
  }

  // O script vive no <head>, então espera a página montar antes de buscar os chips.
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
</script>"""

JS_SHOWS_CASCATA = """
<script>
  // Troca o dia ativo sem submeter a ficha: POST /dia-ativo e recarrega.
  window.gmaTrocaDia = function(v){
    fetch('/dia-ativo', {
      method: 'POST',
      headers: {'Content-Type': 'application/x-www-form-urlencoded'},
      body: 'data=' + encodeURIComponent(v)
    }).then(function(){ location.reload(); });
  };
  // Adiciona um show ao DIA ATIVO num palco (Fatia B2 — operador). Cria o show e
  // liga na programação; recarrega para a cascata refletir.
  window.gmaAddShow = function(){
    var nome = (document.getElementById('show-add-nome')||{}).value || '';
    var palco = (document.getElementById('show-add-palco')||{}).value || '';
    nome = nome.trim();
    if (!nome || !palco){ return; }
    fetch('/programacao/add-show', {
      method: 'POST',
      headers: {'Content-Type': 'application/x-www-form-urlencoded'},
      body: 'nome=' + encodeURIComponent(nome) + '&palco_item_id=' + encodeURIComponent(palco)
    }).then(function(){ location.reload(); });
  };
(function(){
  // Cascata da PROGRAMAÇÃO DO DIA (cobertura de festival): ao escolher o palco,
  // mostra só os shows daquele palco no dia ativo. Os dados vêm de window.gmaProg
  // (mapa palco_item_id -> [{id, valor}]), embutido pelo servidor. Inofensivo
  // quando não há programação (gmaProg ausente/vazio).
  function render(){
    var tipo = window.gmaShowTipo, palcoTipo = window.gmaPalcoTipo;
    if (!tipo || !palcoTipo || !window.gmaProg) return;
    var linha = document.getElementById('chip-linha-' + tipo);
    var dica  = document.getElementById('show-dica');
    if (!linha) return;
    var palcoLinha = document.getElementById('chip-linha-' + palcoTipo);
    var marcados = palcoLinha ? [].slice.call(palcoLinha.querySelectorAll('input[type=checkbox]:checked')) : [];
    linha.innerHTML = '';
    if (!marcados.length){ if (dica) dica.style.display = ''; window.gmaAtualizaContador(tipo); return; }
    if (dica) dica.style.display = 'none';
    // União dos shows dos palcos marcados (uma pessoa pode cobrir vários palcos),
    // sem repetir o mesmo show.
    var vistos = {}, shows = [];
    marcados.forEach(function(p){
      (window.gmaProg[p.value] || []).forEach(function(s){
        if (!vistos[s.id]){ vistos[s.id] = 1; shows.push(s); }
      });
    });
    var jaSel = window.gmaShowSel || [];
    shows.forEach(function(s){
      var marcado = jaSel.indexOf(String(s.id)) >= 0;
      var lbl = document.createElement('label');
      lbl.className = 'chip' + (marcado ? ' sel' : '');
      var inp = document.createElement('input');
      inp.type = 'checkbox'; inp.name = 'chip'; inp.value = s.id;
      if (marcado) inp.checked = true;
      inp.addEventListener('change', function(){
        lbl.classList.toggle('sel', inp.checked);
        window.gmaAtualizaContador(tipo);
      });
      lbl.appendChild(inp);
      lbl.appendChild(document.createTextNode(' ' + s.valor));
      linha.appendChild(lbl);
    });
    window.gmaAtualizaContador(tipo);
  }
  function init(){
    var palcoLinha = document.getElementById('chip-linha-' + window.gmaPalcoTipo);
    if (palcoLinha) palcoLinha.addEventListener('change', render);
    render();  // estado inicial (edição já com palco escolhido)
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
</script>"""

JS_CHIP_NOVO = """
<script>
(function(){
  function init(){
    // Abre/fecha o mini-formulário de "+ novo"
    document.querySelectorAll('.chip-btn-novo').forEach(function(btn){
      btn.addEventListener('click', function(){
        var tipo = btn.getAttribute('data-tipo');
        var form = document.getElementById('novo-form-' + tipo);
        var inp  = document.getElementById('novo-input-' + tipo);
        btn.style.display = 'none';
        form.style.display = 'inline-flex';
        if (inp) inp.focus();
      });
    });

    // Cancelar
    document.querySelectorAll('.chip-novo-cancel').forEach(function(btn){
      btn.addEventListener('click', function(){
        var tipo = btn.getAttribute('data-tipo');
        fecharNovo(tipo);
      });
    });

    // Confirmar (botão ✓ ou Enter no campo)
    document.querySelectorAll('.chip-novo-ok').forEach(function(btn){
      btn.addEventListener('click', function(){ criarNovo(btn); });
    });
    document.querySelectorAll('.chip-novo-input').forEach(function(inp){
      inp.addEventListener('keydown', function(e){
        if (e.key === 'Enter') {
          e.preventDefault();
          var tipo = inp.id.replace('novo-input-', '');
          var ok = document.querySelector('.chip-novo-ok[data-tipo="' + tipo + '"]');
          if (ok) criarNovo(ok);
        }
        if (e.key === 'Escape') {
          var tipo = inp.id.replace('novo-input-', '');
          fecharNovo(tipo);
        }
      });
    });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();

  function fecharNovo(tipo){
    var form = document.getElementById('novo-form-' + tipo);
    var inp  = document.getElementById('novo-input-' + tipo);
    var btn  = document.querySelector('.chip-btn-novo[data-tipo="' + tipo + '"]');
    if (inp)  inp.value = '';
    if (form) form.style.display = 'none';
    if (btn)  btn.style.display = '';
  }

  function criarNovo(okBtn){
    var tipo  = okBtn.getAttribute('data-tipo');
    var grupo = okBtn.getAttribute('data-grupo');
    var inp   = document.getElementById('novo-input-' + tipo);
    var valor = (inp ? inp.value : '').trim();
    if (!valor) { if (inp) inp.focus(); return; }

    okBtn.disabled = true;
    var fd = new FormData();
    fd.append('tipo',  tipo);
    fd.append('valor', valor);

    fetch('/listas/criar-inline', { method: 'POST', body: fd })
      .then(function(r){ return r.json(); })
      .then(function(data){
        if (!data.ok) {
          alert(data.erro || 'Erro ao criar item.');
          okBtn.disabled = false;
          return;
        }
        // Cria o chip dinamicamente e o marca como selecionado
        var linha = document.getElementById('chip-linha-' + tipo);
        if (linha) {
          var lbl = document.createElement('label');
          lbl.className = 'chip sel';
          if (grupo) lbl.setAttribute('data-grupo', grupo);
          var chk = document.createElement('input');
          chk.type = 'checkbox';
          chk.name = 'chip';
          chk.value = String(data.id);
          chk.checked = true;
          // Se escolha única, desmarca irmãos
          if (grupo) {
            document.querySelectorAll('.chip[data-grupo="' + grupo + '"] input').forEach(function(o){
              o.checked = false;
              o.closest('.chip').classList.remove('sel');
            });
          }
          lbl.appendChild(chk);
          lbl.appendChild(document.createTextNode(data.valor));
          // Re-aplica listener do JS_CHIPS
          chk.addEventListener('change', function(){
            var g = lbl.getAttribute('data-grupo');
            if (g && chk.checked) {
              document.querySelectorAll('.chip[data-grupo="' + g + '"] input').forEach(function(o){
                if (o !== chk) { o.checked = false; o.closest('.chip').classList.remove('sel'); }
              });
            }
            lbl.classList.toggle('sel', chk.checked);
            if (window.gmaAtualizaContador) window.gmaAtualizaContador(tipo);
          });
          linha.appendChild(lbl);
          if (window.gmaAtualizaContador) window.gmaAtualizaContador(tipo);
        }
        fecharNovo(tipo);
        okBtn.disabled = false;
      })
      .catch(function(){ alert('Erro de conexão.'); okBtn.disabled = false; });
  }
})();
</script>"""

# JS dos grupos de TEXTO: adicionar/remover valores livres (tags). Vive no <head>.
JS_TEXTO_GRUPO = """
<script>
(function(){
  function init(){
    function atualiza(tipo){
      var cont = document.querySelector('.chip-contador[data-tipo="'+tipo+'"]');
      var box  = document.getElementById('texto-tags-'+tipo);
      if (cont && box){
        var n = box.querySelectorAll('input[type=hidden]').length;
        cont.textContent = n ? ('· '+n+(n>1?' valores':' valor')) : '';
        cont.classList.toggle('tem', n>0);
      }
    }
    function add(tipo){
      var inp = document.getElementById('texto-input-'+tipo);
      var box = document.getElementById('texto-tags-'+tipo);
      if (!inp || !box) return;
      var v = inp.value.trim();
      if (!v){ inp.focus(); return; }
      var bloco = box.closest('.chip-bloco');
      if (bloco && bloco.getAttribute('data-umso') === '1') box.innerHTML = '';
      var dup = [].some.call(box.querySelectorAll('input[type=hidden]'),
                 function(h){ return h.value.toLowerCase() === v.toLowerCase(); });
      if (!dup){
        var tag = document.createElement('span'); tag.className = 'texto-tag';
        tag.appendChild(document.createTextNode(v));
        var h = document.createElement('input'); h.type='hidden'; h.name='texto_'+tipo; h.value=v;
        tag.appendChild(h);
        var rm = document.createElement('button'); rm.type='button'; rm.className='texto-rm';
        rm.title='remover'; rm.textContent='✕'; tag.appendChild(rm);
        box.appendChild(tag);
      }
      inp.value=''; inp.focus(); atualiza(tipo);
    }
    document.querySelectorAll('.texto-add').forEach(function(b){
      b.addEventListener('click', function(){ add(b.getAttribute('data-tipo')); });
    });
    document.querySelectorAll('.texto-input').forEach(function(inp){
      inp.addEventListener('keydown', function(e){
        if (e.key === 'Enter'){ e.preventDefault(); add(inp.getAttribute('data-tipo')); }
      });
    });
    document.addEventListener('click', function(e){
      var t = e.target;
      if (t && t.classList && t.classList.contains('texto-rm')){
        var tag = t.closest('.texto-tag'); var box = tag.closest('.texto-tags');
        var tipo = box.id.replace('texto-tags-','');
        tag.remove(); atualiza(tipo);
      }
    });
    document.querySelectorAll('.texto-tags').forEach(function(box){
      atualiza(box.id.replace('texto-tags-',''));
    });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
</script>"""

# JS dos toggles da ficha: "Quando foi gravado?" (mostra a data só em "Outro dia")
# e "Quem está preenchendo?" (mostra o campo de nome só em "Outra pessoa").
JS_FICHA_TOGGLES = """
<script>
(function(){
  function init(){
    // Toggle da data: "Hoje" esconde o campo (volta p/ hoje); "Outro dia" abre.
    var campoData = document.getElementById('campo-data');
    document.querySelectorAll('input[name="grav_quando"]').forEach(function(r){
      r.addEventListener('change', function(){
        if (!campoData || !r.checked) return;
        if (r.value === 'outro') { campoData.style.display = ''; campoData.focus(); }
        else { campoData.style.display = 'none'; campoData.value = campoData.getAttribute('data-hoje'); }
      });
    });
    // Toggle do "quem preencheu": "Eu mesmo" esconde; "Outra pessoa" abre.
    var campoOp = document.getElementById('campo-operador');
    document.querySelectorAll('input[name="preenchido_por"]').forEach(function(r){
      r.addEventListener('change', function(){
        if (!campoOp || !r.checked) return;
        if (r.value === 'outro') { campoOp.style.display = ''; campoOp.focus(); }
        else { campoOp.style.display = 'none'; campoOp.value = ''; }
      });
    });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
</script>"""

# Quais grupos de classificação são de escolha ÚNICA (radio-like).
# DECISÃO s33: TODOS os grupos passaram a aceitar MÚLTIPLA escolha — um cartão
# cobre vários palcos, várias pautas, várias marcas. Quem tem só um, marca um.
# O conjunto fica vazio (nenhum grupo é único hoje); mantido para o futuro, quando
# os grupos forem editáveis e cada um carregar sua própria regra de única/múltipla.
CLASSIF_UNICA = set()


def _opcoes_select(lista, selecionado=""):
    """Monta os <option> de um <select>, marcando o valor previamente escolhido."""
    partes = []
    for valor in lista:
        sel = " selected" if valor == selecionado else ""
        partes.append(f'<option value="{_esc(valor)}"{sel}>{_esc(valor)}</option>')
    return "".join(partes)


# Status da ficha em que ainda é SEGURO editar os campos críticos (nome/câmera/
# tipo/data): só enquanto ela não tem match com material. Depois de 'matched' esses
# campos guiam a numeração e a pasta de destino — travamos por segurança.
STATUS_FICHA_LIVRE = {"aguardando_material", "aguardando_match", "", None}

# Cores por status para o selo da lista de fichas recentes.
COR_STATUS_FICHA = {
    "aguardando_material": "#6c757d",
    "aguardando_match":    "#6c757d",
    "matched":             "#2196f3",
    "concluido":           "#27ae60",
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


def _profissionais_para_ficha():
    """
    Busca todos os profissionais cadastrados e devolve uma lista de dicts
    prontos para serem injetados como JSON no JavaScript da ficha.

    Cada item tem: nome, tem_foto (bool), tem_audio (bool), tem_video (bool).
    Retorna lista vazia se o banco não estiver disponível — a ficha continua
    de pé, mas os dropdowns de nome ficarão vazios (sem travar o check-in).
    """
    if not BANCO_DISPONIVEL:
        return []
    try:
        conn = bd.obter_conexao()
        # apenas_ativos=True: profissionais desativados somem dos dropdowns da ficha.
        lista = bd.listar_profissionais(conn, apenas_ativos=True)
        conn.close()
        # Mantém só os campos que o JavaScript precisa
        return [
            {
                "nome":      p["nome"],
                "tem_foto":  p["tem_foto"],
                "tem_audio": p["tem_audio"],
                "tem_video": p["tem_video"],
            }
            for p in lista
        ]
    except Exception as erro:
        logger.error(f"FICHA | Erro ao carregar profissionais | {erro}")
        return []


def _bloco_tipo_nome_ficha(d, trava, profissionais):
    """
    Monta o bloco HTML de TIPO (checkboxes) + NOME (dropdown(s) fechado(s))
    da ficha de check-in — Nova Ficha v2, Fatia 3.

    Regras implementadas:
    - TIPO vira 3 checkboxes: Foto / Áudio / Vídeo.
    - NOME vira dropdown fechado filtrado pelo tipo marcado.
    - Se marcar Foto e/ou Vídeo + Áudio → aparecem 2 dropdowns (Foto/Vídeo e Áudio).
    - O JavaScript roda no navegador, offline, sem dependência externa.
    - Para compatibilidade com o backend atual, deriva via JS:
        * campo hidden "nome"         → nome do Foto/Vídeo (ou do Áudio se só áudio)
        * campo hidden "tipo_material" → tipos marcados unidos por "+" (ex: "FOTO+AUDIO")
        * campo hidden "nome_audio"    → nome do Áudio (quando 2 dropdowns); backend ignora por ora
    """
    import json as _json

    # Serializa a lista de profissionais como JSON puro para injetar no JS.
    # _json.dumps garante que os valores booleanos virem true/false (JavaScript).
    dados_js = _json.dumps(profissionais, ensure_ascii=False)

    # Valores que já existem na ficha (modo editar ou reapresentação de erro).
    # Usados para marcar as caixinhas e pré-selecionar os dropdowns.
    tipo_atual     = d.get("tipo_material", "")    # ex: "FOTO+AUDIO" ou "VIDEO"
    nome_atual     = d.get("nome", "")
    nome_audio_atual = d.get("nome_audio", "")

    # Origem do material: "cartao" (padrão, operação normal) ou "recebido" (pasta satélite).
    # Posts antigos não têm o campo — caem para "cartao" como esperado.
    origem_atual = d.get("origem_material", "cartao") or "cartao"

    # Descobre quais checkboxes marcar a partir do tipo já gravado.
    foto_chk  = "checked" if "FOTO"  in tipo_atual else ""
    audio_chk = "checked" if "AUDIO" in tipo_atual else ""
    video_chk = "checked" if "VIDEO" in tipo_atual else ""

    # Atributo que trava os controles quando a ficha já tem match com material.
    trava_chk     = " disabled" if trava.strip() else ""  # checkboxes usam "disabled" simples
    trava_sel     = trava                                  # selects já usam o atributo gerado

    bloco = f"""
        <!-- ── TIPO: multi-seleção ─────────────────────────────── -->
        <div class="campo largo">
          <label>Tipo de material <span class="estrela">★</span></label>
          <div class="tipo-checks">
            <label>
              <input type="checkbox" id="chk_foto"  value="FOTO"  {foto_chk}{trava_chk}
                     onchange="gma_atualizar_ficha()">
              Foto
            </label>
            <label>
              <input type="checkbox" id="chk_audio" value="AUDIO" {audio_chk}{trava_chk}
                     onchange="gma_atualizar_ficha()">
              Áudio
            </label>
            <label>
              <input type="checkbox" id="chk_video" value="VIDEO" {video_chk}{trava_chk}
                     onchange="gma_atualizar_ficha()">
              Vídeo
            </label>
          </div>
          <!-- campo hidden que o backend lê: "FOTO", "AUDIO+VIDEO", "FOTO+AUDIO", etc. -->
          <input type="hidden" id="campo_tipo_material" name="tipo_material"
                 value="{_esc(tipo_atual)}">
        </div>

        <!-- ── ORIGEM DO MATERIAL: cartão físico ou pasta satélite ─────────── -->
        <!-- Pergunta estrutural: comanda o fluxo do arco "recebidos".          -->
        <!-- Padrão = "cartao" → operação normal não muda em nada.              -->
        <div class="campo largo">
          <label>Como o material chega?</label>
          <div class="tipo-checks">
            <label>
              <input type="radio" name="origem_material" value="cartao"
                     {"checked" if origem_atual == "cartao" else ""}{trava_chk}>
              Cartão físico
            </label>
            <label>
              <input type="radio" name="origem_material" value="recebido"
                     {"checked" if origem_atual == "recebido" else ""}{trava_chk}>
              Pasta recebida (Drive/Dropbox)
            </label>
          </div>
        </div>

        <!-- ── NOME: dropdown(s) fechado(s), filtrados por tipo ── -->
        <div class="campo-nome-wrapper largo" id="bloco_nomes">

          <!-- Dropdown para Foto/Vídeo (visível quando Foto ou Vídeo marcados) -->
          <div class="campo" id="div_nome_fotovideo" style="display:none">
            <label id="label_nome_fotovideo">
              Nome Foto/Vídeo <span class="estrela">★</span>
            </label>
            <select id="sel_nome_fotovideo" onchange="gma_atualizar_ficha()"{trava_sel}>
              <option value="">— escolha —</option>
            </select>
          </div>

          <!-- Dropdown para Áudio (visível quando Áudio marcado) -->
          <div class="campo" id="div_nome_audio" style="display:none">
            <label>Nome Áudio <span class="estrela">★</span></label>
            <select id="sel_nome_audio" onchange="gma_atualizar_ficha()"{trava_sel}>
              <option value="">— escolha —</option>
            </select>
            <!-- campo extra para o áudio — o backend atual ignora, a Fatia 5 vai usar -->
            <input type="hidden" id="campo_nome_audio" name="nome_audio" value="{_esc(nome_audio_atual)}">
          </div>

          <!-- campo hidden "nome" que o backend obrigatório lê -->
          <input type="hidden" id="campo_nome" name="nome" value="{_esc(nome_atual)}">

          <!-- Aviso quando nenhum tipo está marcado ainda -->
          <p class="aviso-sem-cadastro" id="aviso_escolha_tipo"
             style="display:none">
            Marque ao menos um tipo acima para ver os nomes disponíveis.
          </p>
          <!-- Aviso quando o tipo está marcado mas não há profissionais cadastrados -->
          <p class="aviso-sem-cadastro" id="aviso_sem_prof" style="display:none">
            Nenhum profissional cadastrado para este tipo.
            Cadastre em <a href="/profissionais">Cadastros</a>.
          </p>
        </div>

        <!-- ── JavaScript (roda offline, no próprio navegador) ─── -->
        <script>
        // Lista completa de profissionais cadastrados, injetada pelo servidor.
        // Cada item: {{ nome, tem_foto, tem_audio, tem_video }}
        var GMA_PROFISSIONAIS = {dados_js};

        // Valores iniciais para pré-selecionar ao carregar (modo editar / reapresentação).
        var GMA_NOME_INICIAL       = "{_esc(nome_atual)}";
        var GMA_NOME_AUDIO_INICIAL = "{_esc(nome_audio_atual)}";

        /**
         * Reconstrói os dropdowns de nome e os campos hidden sempre que
         * o operador muda as caixinhas de tipo.
         */
        function gma_atualizar_ficha() {{
            var foto  = document.getElementById("chk_foto").checked;
            var audio = document.getElementById("chk_audio").checked;
            var video = document.getElementById("chk_video").checked;

            // ── 1. Atualiza o campo hidden tipo_material ──────────────────
            var tipos = [];
            if (foto)  tipos.push("FOTO");
            if (audio) tipos.push("AUDIO");
            if (video) tipos.push("VIDEO");
            document.getElementById("campo_tipo_material").value = tipos.join("+");

            // ── 2. Decide quantos dropdowns mostrar ───────────────────────
            // Regra do desenho §4:
            //   só áudio             → 1 dropdown (áudio)
            //   só foto/vídeo        → 1 dropdown (foto/vídeo)
            //   foto/vídeo + áudio   → 2 dropdowns
            var temFotoVideo = foto || video;
            var temAudio     = audio;
            var nenhum       = !temFotoVideo && !temAudio;

            // ── 3. Filtra profissionais por tipo ──────────────────────────
            // Dropdown Foto/Vídeo: mostra quem tem foto (se foto marcado)
            //                       OU tem video (se video marcado).
            var profFotoVideo = GMA_PROFISSIONAIS.filter(function(p) {{
                return (foto && p.tem_foto) || (video && p.tem_video);
            }});

            // Dropdown Áudio: só quem tem tem_audio = true.
            var profAudio = GMA_PROFISSIONAIS.filter(function(p) {{
                return p.tem_audio;
            }});

            // ── 4. Reconstrói as <option> de cada select ──────────────────
            gma_preencher_select("sel_nome_fotovideo", profFotoVideo, GMA_NOME_INICIAL);
            gma_preencher_select("sel_nome_audio",     profAudio,     GMA_NOME_AUDIO_INICIAL);

            // ── 5. Mostra/esconde os divs conforme a combinação ───────────
            document.getElementById("div_nome_fotovideo").style.display =
                temFotoVideo ? "flex" : "none";
            document.getElementById("div_nome_audio").style.display =
                temAudio ? "flex" : "none";

            // Ajusta o label do dropdown Foto/Vídeo: se só vídeo, diz "Vídeo";
            // se só foto, diz "Foto"; se os dois, diz "Foto / Vídeo".
            var labelFV = document.getElementById("label_nome_fotovideo");
            if (foto && video) {{
                labelFV.innerHTML = 'Nome Foto / Vídeo <span class="estrela">★</span>';
            }} else if (foto) {{
                labelFV.innerHTML = 'Nome Foto <span class="estrela">★</span>';
            }} else {{
                labelFV.innerHTML = 'Nome Vídeo <span class="estrela">★</span>';
            }}

            // ── 6. Avisos ────────────────────────────────────────────────
            document.getElementById("aviso_escolha_tipo").style.display =
                nenhum ? "block" : "none";

            // Aviso "sem profissionais": só quando há tipo marcado mas a lista está vazia.
            var listaVazia = (
                (temFotoVideo && profFotoVideo.length === 0) ||
                (temAudio     && profAudio.length === 0)
            );
            document.getElementById("aviso_sem_prof").style.display =
                (!nenhum && listaVazia) ? "block" : "none";

            // ── 7. Atualiza campos hidden que o backend lê ────────────────
            gma_sincronizar_hidden();
        }}

        /**
         * Preenche um <select> com a lista de profissionais filtrada.
         * Tenta manter o nome já selecionado anteriormente (pré-seleção).
         */
        function gma_preencher_select(id_select, lista, valor_inicial) {{
            var sel = document.getElementById(id_select);
            var anterior = sel.value || valor_inicial;  // preserva seleção atual

            // Limpa e reconstrói
            sel.innerHTML = '<option value="">— escolha —</option>';
            lista.forEach(function(p) {{
                var opt = document.createElement("option");
                opt.value = p.nome;
                opt.textContent = p.nome;
                if (p.nome === anterior) opt.selected = true;
                sel.appendChild(opt);
            }});
        }}

        /**
         * Copia os valores dos selects visíveis para os campos hidden
         * que o backend obrigatório lê ("nome" e "nome_audio").
         *
         * Regra: se só áudio marcado → "nome" recebe o áudio.
         *        se Foto/Vídeo marcado → "nome" recebe o Foto/Vídeo.
         */
        function gma_sincronizar_hidden() {{
            var foto  = document.getElementById("chk_foto").checked;
            var audio = document.getElementById("chk_audio").checked;
            var video = document.getElementById("chk_video").checked;
            var temFotoVideo = foto || video;

            var nomeFV    = document.getElementById("sel_nome_fotovideo").value;
            var nomeAudio = document.getElementById("sel_nome_audio").value;

            // "nome" → autoridade principal: Foto/Vídeo se houver; senão Áudio.
            document.getElementById("campo_nome").value =
                temFotoVideo ? nomeFV : nomeAudio;

            // "nome_audio" → segundo nome (a Fatia 5 vai gravar isso direito).
            document.getElementById("campo_nome_audio").value = nomeAudio;
        }}

        // Acionado também quando o operador muda um dropdown manualmente.
        document.getElementById("sel_nome_fotovideo").addEventListener(
            "change", gma_sincronizar_hidden);
        document.getElementById("sel_nome_audio").addEventListener(
            "change", gma_sincronizar_hidden);

        // Roda na carga da página para montar o estado inicial correto
        // (importante no modo editar, quando dados já vêm preenchidos).
        gma_atualizar_ficha();

        /**
         * Validação no submit: garante que tipo e nome estejam preenchidos
         * antes de enviar (os campos hidden não têm atributo "required" nativo
         * no HTML, então a conferência é feita aqui, no JavaScript).
         */
        document.querySelector("form.ficha-form").addEventListener("submit", function(ev) {{
            var tipo = document.getElementById("campo_tipo_material").value;
            var nome = document.getElementById("campo_nome").value;

            if (!tipo) {{
                ev.preventDefault();
                alert("Marque ao menos um tipo de material (Foto, Áudio ou Vídeo).");
                return;
            }}
            if (!nome) {{
                ev.preventDefault();
                alert("Escolha um nome no dropdown correspondente ao tipo marcado.");
                return;
            }}
        }});
        </script>
    """
    return bloco


# Centro de controle dos Posts (Nova Ficha): cada status vira um grupo recolhível.
# Ordem = do mais acionável (precisa de atenção) ao já resolvido. O que não estiver
# nesta lista cai num grupo "Outros" no fim, então nada some se surgir status novo.
_GRUPOS_POSTS = [
    ("aguardando_match",    "⏳ Aguardando match",    True),
    ("aguardando_material", "📭 Aguardando material", True),
    ("matched",             "✅ Com match",           True),
    # Posts cujo cartão já passou pela auditoria (entregues). Vêm recolhidos por
    # padrão (False): saíram da operação, ficam aqui como histórico do dia.
    ("concluido",           "📦 Concluído / entregue", False),
]


def _row_get(row, chave, padrao=None):
    """Lê uma coluna de um sqlite3.Row com segurança.

    Diferente de um dicionário, o sqlite3.Row NÃO tem .get() e levanta IndexError
    quando a coluna não veio no SELECT. Algumas queries (ex.: Posts cancelados) não
    trazem os campos do arco satélite — aqui devolvemos o padrão em vez de quebrar.
    """
    try:
        valor = row[chave]
    except (IndexError, KeyError):
        return padrao
    return padrao if valor is None else valor


def _linha_post_html(f):
    """Uma linha da tabela de Posts: dados + ações (editar / cancelar).

    Posts satélite (origem_material='recebido') ganham blocos extras:
      - campo para o operador colar/editar o link da pasta na nuvem;
      - botão "Material recebido — pronto para copiar" (gatilho, não dispara cópia).
    """
    fid = f["id"]
    status = f["status"] or ""
    cor = COR_STATUS_FICHA.get(status, "#495057")
    # Nome principal + (quando há áudio de outra pessoa) o 2º nome — Fatia 5.
    nome_html = f"<b>{_esc(f['nome'])}</b>"
    if f["nome_audio"]:
        nome_html += (f' <span style="color:var(--6f-texto-2);font-size:0.85em">'
                      f'+ {_esc(f["nome_audio"])} (áudio)</span>')
    # Ação "cancelar": soft-delete reversível → grupo "Posts cancelados" (mesmo
    # motor da Operação, rota /post/<id>/cancelar).
    cancelar = (
        f"<form action='/post/{fid}/cancelar' method='post' style='margin:0;display:inline' "
        f"onsubmit=\"return confirm('Cancelar este Post? Ele sai das telas e vai para "
        f"Posts cancelados (reversível).');\">"
        f"<button type='submit' style='background:none;border:none;color:var(--6f-erro);"
        f"font-size:0.82em;cursor:pointer;text-decoration:underline'>cancelar</button></form>"
    )

    # ── Blocos extras para Posts satélite ────────────────────────────────────
    # Mostrados SOMENTE quando origem_material = 'recebido'.
    # O operador (acesso local) vê o campo de link e o botão de gatilho.
    extra_satelite = ""
    eh_satelite = (_row_get(f, "origem_material") or "cartao") == "recebido"
    if eh_satelite:
        link_atual = _esc(_row_get(f, "link_recebidos") or "")
        ja_pronto = bool(_row_get(f, "recebido_pronto"))

        # Campo para colar/editar o link da pasta na nuvem (Peça 2).
        form_link = (
            f"<form action='/post/{fid}/link-recebidos' method='post' "
            f"style='margin:4px 0 0 0;display:flex;gap:6px;align-items:center'>"
            f"<label style='font-size:0.8em;color:var(--6f-texto-2);white-space:nowrap'>"
            f"Link p/ recebimento:</label>"
            f"<input type='url' name='link_recebidos' value='{link_atual}' "
            f"placeholder='https://drive.google.com/...' "
            f"style='flex:1;font-size:0.82em;padding:2px 6px;border:1px solid var(--6f-borda);"
            f"background:var(--6f-bg-elevado);color:var(--6f-texto);"
            f"border-radius:4px;min-width:160px'>"
            f"<button type='submit' style='font-size:0.8em;padding:2px 8px;"
            f"background:var(--6f-bg-hover);color:var(--6f-texto);border:1px solid var(--6f-borda);border-radius:4px;cursor:pointer'>"
            f"salvar</button></form>"
        )

        # Status do Post: se já tem match, a cópia já foi (ou está sendo) processada.
        ja_com_match = (status == "matched" or status == "transferencia_ok"
                        or status == "transferencia_falhou" or status == "concluido"
                        or status == "copiando")

        # Peça 3 — gatilho: só aparece se ainda não foi marcado como pronto.
        # NOTA: este botão SÓ MARCA — a cópia real é o botão "Copiar agora" (Fatia 4, C2).
        if ja_pronto:
            if ja_com_match:
                # Já tem match/cópia — mostra o status em vez do botão de cópia
                status_label = {
                    "copiando":             "Copiando…",
                    "transferencia_ok":     "Cópia concluída",
                    "transferencia_falhou": "Cópia falhou — verificar",
                    "concluido":            "Concluído",
                }.get(status, "Com match — aguardando")
                btn_gatilho = (
                    f"<span style='font-size:0.8em;color:var(--6f-teal);font-weight:600'>"
                    f"✅ {status_label}</span>"
                )
            else:
                # Pronto mas sem match ainda: mostra "pronto" + botão "Copiar agora" (Fatia 4)
                btn_gatilho = (
                    f"<span style='font-size:0.8em;color:var(--6f-teal);font-weight:600'>"
                    f"✅ Material pronto</span> "
                    f"<form action='/post/{fid}/copiar-recebido' method='post' "
                    f"style='margin:4px 0 0 0;display:inline' "
                    f"onsubmit=\"return confirm('Iniciar a cópia agora? O processo pode "
                    f"demorar alguns minutos para arquivos grandes.');\">"
                    f"<button type='submit' "
                    f"style='font-size:0.82em;padding:3px 12px;background:var(--6f-teal);"
                    f"color:var(--6f-bg-base);border:none;border-radius:4px;cursor:pointer;"
                    f"font-weight:600'>"
                    f"Copiar agora</button></form>"
                )
        else:
            btn_gatilho = (
                f"<form action='/post/{fid}/recebido-pronto' method='post' "
                f"style='margin:4px 0 0 0' "
                f"onsubmit=\"return confirm('Confirmar: o material deste Post chegou e "
                f"está pronto para cópia?');\">"
                f"<button type='submit' "
                f"style='font-size:0.82em;padding:3px 10px;background:var(--6f-teal);"
                f"color:var(--6f-bg-base);border:none;border-radius:4px;cursor:pointer'>"
                f"📥 Material recebido — pronto para copiar</button></form>"
            )

    # Linha principal da tabela
    linha = f"""
      <tr>
        <td class="mono">{fid}</td>
        <td>{nome_html}</td>
        <td>{_esc(_tipo_display(f['tipo_material']))}</td>
        <td class="mono">{_esc(f['data_gravacao'])}</td>
        <td><span class="badge-mini" style="background:{cor}">{_esc(status) or '—'}</span></td>
        <td style="white-space:nowrap">
          <a class="link-editar" href="/ficha/{fid}/editar">editar ✎</a>
          <span style="color:var(--6f-texto-3);margin:0 6px">·</span>
          {cancelar}
        </td>
      </tr>"""

    # Linha extra (apenas para Posts satélite): ocupa as 6 colunas com o campo
    # de link e o botão de gatilho. Reutiliza form_link e btn_gatilho já montados.
    if eh_satelite:
        linha += f"""
      <tr style="background:var(--6f-teal-trilho)">
        <td colspan="6" style="padding:4px 8px 8px 24px;border-top:none">
          <div style='font-size:0.78em;color:var(--6f-teal-claro);font-weight:600;margin-bottom:4px'>
            📂 Pasta satélite (material enviado digitalmente)</div>
          <div style='display:flex;flex-wrap:wrap;gap:8px;align-items:flex-start'>
            <div style='flex:1;min-width:200px'>{form_link}</div>
            <div style='padding-top:2px'>{btn_gatilho}</div>
          </div>
        </td>
      </tr>"""

    return linha


def _grupo_posts_html(titulo, fichas, aberto):
    """Bloco recolhível de um status, com a tabela de Posts daquele grupo."""
    if not fichas:
        return ""
    linhas = "".join(_linha_post_html(f) for f in fichas)
    open_attr = " open" if aberto else ""
    return f"""
    <details class="grupo-posts"{open_attr}>
      <summary>{titulo} <span class="badge">{len(fichas)}</span></summary>
      <table class="tab-recentes">
        <thead><tr><th>#</th><th>Nome</th><th>Tipo</th>
                   <th>Data</th><th>Status</th><th></th></tr></thead>
        <tbody>{linhas}</tbody>
      </table>
    </details>"""


def _grupo_cancelados_html(cancelados):
    """Grupo recolhível dos Posts cancelados: restaurar (volta) / excluir (de vez)."""
    if not cancelados:
        return ""
    linhas = "".join(
        f"<tr><td>{_esc(c['nome'])}</td>"
        f"<td>{_esc(_tipo_display(c['tipo_material']) if c['tipo_material'] else '—')}</td>"
        f"<td class='mono'>{_esc(c['data_gravacao'] or '—')}</td>"
        f"<td style='white-space:nowrap'>"
        f"<form action='/post/{c['id']}/restaurar' method='post' style='margin:0;display:inline'>"
        f"<button type='submit' style='background:none;border:none;color:var(--6f-teal);"
        f"font-size:0.82em;cursor:pointer;text-decoration:underline'>restaurar</button></form>"
        # Excluir definitivo: passo final para sobra/lixo. Irreversível — sobra só o Log.
        f"<span style='color:var(--6f-texto-3);margin:0 6px'>·</span>"
        f"<form action='/post/{c['id']}/excluir' method='post' style='margin:0;display:inline' "
        f"onsubmit=\"return confirm('Excluir {_esc(c['nome'])} DE VEZ? Não tem volta — "
        f"sobra só o registro no Log do sistema.');\">"
        f"<button type='submit' style='background:none;border:none;color:var(--6f-erro);"
        f"font-size:0.82em;cursor:pointer;text-decoration:underline'>excluir</button></form>"
        f"</td></tr>"
        for c in cancelados
    )
    return f"""
    <details class="grupo-posts grupo-cancelados">
      <summary>🗂️ Posts cancelados <span class="badge">{len(cancelados)}</span>
        <span style="font-weight:400;color:var(--6f-texto-3);font-size:0.85em">
          — fora das telas e da Planilha; restaurar ou excluir de vez</span>
      </summary>
      <table class="tab-recentes">
        <thead><tr><th>Nome</th><th>Tipo</th><th>Data</th><th></th></tr></thead>
        <tbody>{linhas}</tbody>
      </table>
    </details>"""


def _fichas_recentes_html(limite=40):
    """
    Centro de controle dos Posts: lista os Posts agrupados por status (cada grupo
    recolhível) com as ações editar/cancelar, e um grupo separado para os
    cancelados (restaurar/excluir). É a casa das ações que antes só existiam na
    Operação — lá fica só o match.
    """
    if not BANCO_DISPONIVEL:
        return ""
    try:
        conn = bd.obter_conexao()
        ativas = conn.execute(
            # Inclui os campos do arco satélite para renderizar o link e o botão
            "SELECT id, nome, nome_audio, tipo_material, data_gravacao, status, "
            "       origem_material, link_recebidos, recebido_pronto "
            "FROM formularios WHERE status <> 'cancelado' OR status IS NULL "
            "ORDER BY id DESC LIMIT ?", (limite,)
        ).fetchall()
        cancelados = bd.listar_formularios_cancelados(conn)
        conn.close()
    except Exception as erro:
        logger.error(f"FICHA | Erro ao listar Posts | {erro}")
        return ""

    if not ativas and not cancelados:
        return ""

    # Distribui os Posts ativos nos grupos conhecidos; o resto vai para "Outros".
    por_status = {}
    for f in ativas:
        por_status.setdefault(f["status"] or "", []).append(f)

    blocos = []
    for chave, titulo, aberto in _GRUPOS_POSTS:
        blocos.append(_grupo_posts_html(titulo, por_status.pop(chave, []), aberto))
    # Qualquer status não previsto não pode sumir — agrupa em "Outros".
    sobras = [f for grupo in por_status.values() for f in grupo]
    blocos.append(_grupo_posts_html("📋 Outros", sobras, True))
    blocos.append(_grupo_cancelados_html(cancelados))

    return f"""
    <div class="recentes">
      <h2>Posts (clique no grupo para abrir/fechar)</h2>
      {''.join(b for b in blocos if b)}
    </div>"""


def _bloco_texto_grupo_html(g, valores):
    """
    Bloco de um grupo de modo 'texto' na ficha: o profissional escreve valores
    livres (ex.: nome do entrevistado) e pode adicionar vários. Cada valor vira
    uma "tag" com um input escondido name="texto_<chave>"; o JS adiciona/remove.
    """
    tipo = g["chave"]
    rotulo = _esc(g["rotulo"])
    um_so = not g["multipla"]

    tags_html = ""
    for v in (valores or []):
        vesc = _esc(v)
        tags_html += (
            f'<span class="texto-tag">{vesc}'
            f'<input type="hidden" name="texto_{tipo}" value="{vesc}">'
            f'<button type="button" class="texto-rm" title="remover">✕</button></span>'
        )

    dica = ' <span class="ajuda">(um valor)</span>' if um_so else \
           f' <span class="chip-contador" data-tipo="{tipo}"></span>'
    return (
        f'<div class="chip-bloco" data-modo="texto" data-umso="{1 if um_so else 0}">'
        f'<div class="chip-rotulo">{rotulo}{dica}</div>'
        f'<div class="texto-tags chip-linha" id="texto-tags-{tipo}">{tags_html}</div>'
        f'<div class="chip-acao">'
        f'<input type="text" class="texto-input" id="texto-input-{tipo}" data-tipo="{tipo}" '
        f'placeholder="escrever e Enter…" maxlength="80" autocomplete="off">'
        f'<button type="button" class="chip-btn-novo texto-add" data-tipo="{tipo}">adicionar</button>'
        f'</div></div>'
    )


def _coletar_textos_form(form):
    """Extrai {grupo_chave: [valores]} dos campos 'texto_<chave>' do formulário."""
    out = {}
    for key in list(form.keys()):
        if key.startswith("texto_"):
            chave = key[len("texto_"):]
            vals = [v.strip() for v in form.getlist(key) if v and v.strip()]
            if vals:
                out[chave] = vals
    return out


def _fmt_dia_br(iso):
    """'2026-09-04' -> 'sexta 04/09' (rótulo curto em português para o banner)."""
    from datetime import datetime
    dias = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]
    try:
        dt = datetime.strptime(iso, "%Y-%m-%d")
        return f"{dias[dt.weekday()]} {dt.strftime('%d/%m')}"
    except Exception:
        return iso or ""


def _bloco_classificacao_ficha(chips_selecionados, eh_operador=False, textos_selecionados=None):
    """
    Monta o bloco de CLASSIFICAÇÃO da ficha: chips clicáveis montados a partir das
    listas de contexto ATIVAS (palco, marca, pauta, serviço, tags), que o operador
    gere na aba "Listas". É a ponte chips→ficha→planilha.

    Regras (Nova Ficha v2 / desenho s31):
    - O profissional só ESCOLHE da lista — vocabulário fechado, sem digitar.
    - palco/marca/pauta/serviço = escolha única; tags = múltipla (enforçado por JS).
    - Sem NENHUM item ativo → o bloco inteiro some (a ficha continua limpa).
    - A classificação é editorial: continua liberada mesmo quando a ficha já tem match
      (ao contrário de nome/tipo/data), por isso não recebe a trava.

    chips_selecionados: conjunto de ids (str) já escolhidos — edição ou
    reapresentação após erro de validação.
    """
    if not BANCO_DISPONIVEL:
        return ""
    # Contexto da PROGRAMAÇÃO DO DIA (cobertura de festival). Carregado num try
    # próprio: bancos sem as tabelas (lab antigo) simplesmente não têm programação
    # e a ficha segue normal (retrocompatível).
    prog_por_palco = {}
    show_chave = palco_chave = None
    dia_prog = None
    dias_prog = []
    try:
        conn = bd.obter_conexao()
        itens = bd.listar_itens_lista(conn, apenas_ativos=True)
        grupos = bd.listar_grupos(conn, apenas_ativos=True)
        try:
            dia_prog = bd.dia_ativo(conn)
            prog_por_palco = bd.programacao_do_dia_por_palco(conn, dia_prog)
            if prog_por_palco:
                r1 = conn.execute("SELECT lc.tipo FROM programacao p "
                                  "JOIN listas_contexto lc ON lc.id = p.show_item_id LIMIT 1").fetchone()
                r2 = conn.execute("SELECT lc.tipo FROM programacao p "
                                  "JOIN listas_contexto lc ON lc.id = p.palco_item_id LIMIT 1").fetchone()
                show_chave = r1[0] if r1 else None
                palco_chave = r2[0] if r2 else None
                dias_prog = bd.dias_com_programacao(conn)
        except Exception:
            prog_por_palco = {}  # banco sem as tabelas de programação
        conn.close()
    except Exception as erro:
        logger.error(f"FICHA | Erro ao carregar listas de contexto | {erro}")
        return ""

    if not grupos:
        return ""

    # Agrupa os itens por tipo (= chave do grupo).
    por_tipo = {}
    for it in itens:
        por_tipo.setdefault(it["tipo"], []).append(it)

    sel = {str(s) for s in (chips_selecionados or set())}
    textos_sel = textos_selecionados or {}

    blocos = []
    # Itera os GRUPOS ativos do banco (não mais a lista fixa) — Fatia 2 (s33).
    # Cada grupo traz seu rótulo e sua regra única/múltipla. Um grupo sem itens
    # ainda aparece para o operador (que pode criar via "+ novo"); no acesso
    # remoto (profissional), grupos vazios são omitidos.
    for g in grupos:
        tipo = g["chave"]

        # Grupo de TEXTO (escreve na hora) — caixa de múltiplos valores (s33).
        if g.get("modo") == "texto":
            blocos.append(_bloco_texto_grupo_html(g, textos_sel.get(tipo, [])))
            continue

        # Grupo SHOW da programação do dia (cobertura de festival): em vez de
        # listar os ~155 shows, mostra uma cascata — os chips aparecem quando o
        # palco é escolhido (preenchidos pelo JS a partir do dia ativo).
        if prog_por_palco and tipo == show_chave:
            # Operador pode ADICIONAR um show ao dia ativo num palco (Fatia B2).
            # Ex.: entrou um show surpresa, ou — no RIO2C — uma palestra numa sala.
            add_html = ""
            if eh_operador:
                palco_itens = por_tipo.get(palco_chave, [])
                palco_opts = "".join(
                    f'<option value="{it["id"]}">{_esc(it["valor"])}</option>'
                    for it in palco_itens
                )
                add_html = (
                    '<div class="show-add" style="margin-top:8px;display:flex;gap:6px;'
                    'flex-wrap:wrap;align-items:center">'
                    '<input type="text" id="show-add-nome" placeholder="adicionar show ao dia…" '
                    'maxlength="80" autocomplete="off" style="flex:1;min-width:160px;padding:4px 8px">'
                    f'<select id="show-add-palco">{palco_opts}</select>'
                    '<button type="button" class="chip-btn-novo" onclick="window.gmaAddShow()">'
                    '+ adicionar</button>'
                    '</div>'
                )
            blocos.append(
                f'<div class="chip-bloco">'
                f'<div class="chip-rotulo">{_esc(g["rotulo"])} '
                f'<span class="chip-contador" data-tipo="{tipo}"></span></div>'
                f'<div class="chip-linha" id="chip-linha-{tipo}"></div>'
                f'<div class="ajuda" id="show-dica" style="margin-top:4px">'
                f'Escolha o palco acima para ver os shows do dia.</div>'
                f'{add_html}'
                f'</div>'
            )
            continue

        lista = por_tipo.get(tipo, [])
        if not lista and not eh_operador:
            continue
        rotulo = g["rotulo"]
        unico = not g["multipla"]
        # data-grupo só nos grupos de escolha única (o JS usa para desmarcar irmãos).
        grupo_attr = tipo if unico else ""
        chips_html = ""
        for it in lista:
            iid = str(it["id"])
            marcado = iid in sel
            classe = "chip sel" if marcado else "chip"
            checked = " checked" if marcado else ""
            chips_html += (
                f'<label class="{classe}" data-grupo="{grupo_attr}">'
                f'<input type="checkbox" name="chip" value="{iid}"{checked}>'
                f'{_esc(it["valor"])}</label>'
            )
        # Todos os grupos são múltipla escolha hoje (CLASSIF_UNICA vazio). Mostramos
        # um contador discreto ao lado do rótulo, atualizado pelo JS ao marcar/desmarcar.
        dica = (' <span class="ajuda">(uma opção)</span>' if unico
                else f' <span class="chip-contador" data-tipo="{tipo}"></span>')
        # Botão "+ novo" — só para o operador (acesso local). O profissional
        # de captação (acesso remoto) só escolhe; nunca vê a opção de criar.
        btn_novo = ""
        if eh_operador:
            btn_novo = (
                f'<button type="button" class="chip-btn-novo" data-tipo="{tipo}" '
                f'title="Criar novo item em {_esc(rotulo)}">+ novo</button>'
                f'<span class="chip-novo-form" id="novo-form-{tipo}" style="display:none">'
                f'<input type="text" class="chip-novo-input" id="novo-input-{tipo}" '
                f'placeholder="nome do item…" maxlength="60" autocomplete="off">'
                f'<button type="button" class="chip-novo-ok" data-tipo="{tipo}" '
                f'data-grupo="{grupo_attr}">✓</button>'
                f'<button type="button" class="chip-novo-cancel" data-tipo="{tipo}">✕</button>'
                f'</span>'
            )
        blocos.append(
            f'<div class="chip-bloco"><div class="chip-rotulo">{_esc(rotulo)}{dica}</div>'
            f'<div class="chip-linha" id="chip-linha-{tipo}">{chips_html}</div>'
            f'<div class="chip-acao">{btn_novo}</div></div>'
        )

    if not blocos:
        return ""

    # Banner "Programação ativa: <dia>" + (só operador) seletor para trocar o dia.
    # Embute também os dados da programação do dia para a cascata (JS).
    import json
    banner = ""
    script = ""
    if prog_por_palco:
        rotulo_dia = _fmt_dia_br(dia_prog)
        troca = ""
        if eh_operador and dias_prog:
            opts = "".join(
                f'<option value="{_esc(d)}"{" selected" if d == dia_prog else ""}>'
                f'{_esc(_fmt_dia_br(d))}</option>'
                for d in dias_prog
            )
            # Sem <form> (estaria aninhado no form da ficha — HTML inválido, faria o
            # select submeter a ficha). Um select que chama fetch e recarrega.
            troca = (
                f' <select onchange="window.gmaTrocaDia(this.value)" '
                f'style="margin-left:6px">{opts}</select>'
            )
        banner = (
            '<div class="prog-banner" style="background:var(--6f-teal-trilho);color:var(--6f-teal-claro);'
            'border:1px solid var(--6f-teal);'
            'border-radius:8px;padding:8px 12px;margin-bottom:10px;font-size:0.95em">'
            f'📅 Programação ativa: <b>{_esc(rotulo_dia)}</b>{troca}</div>'
        )
        script = (
            f'<script>window.gmaProg={json.dumps(prog_por_palco)};'
            f'window.gmaShowTipo={json.dumps(show_chave)};'
            f'window.gmaPalcoTipo={json.dumps(palco_chave)};'
            f'window.gmaShowSel={json.dumps([str(s) for s in sel])};</script>'
        )

    blocos_html = "".join(blocos)
    return (
        banner +
        '<div class="grupo-titulo">Classificação '
        '<span class="ajuda" style="text-transform:none;letter-spacing:0">'
        '(ajuda os editores a achar o material)</span></div>'
        f'<div class="campo largo chip-area">{blocos_html}</div>'
        + script
    )


def _bloco_data_ficha(d, trava, hoje_iso):
    """
    Bloco "Quando foi gravado?" — assume HOJE por padrão e só pede a data quando
    o profissional diz que foi outro dia (2.1, decisão s33). Mais prático no set:
    a maioria entrega no mesmo dia. O Matcher recebe a data normalmente (critério +2).

    Travada (ficha já tem match): mostra só a data desabilitada, sem o toggle.
    """
    data_atual = (d.get("data_gravacao") or "").strip()
    if trava:
        return (
            '<div class="campo">'
            '<label>Data de gravação <span class="estrela">★</span></label>'
            f'<input type="date" name="data_gravacao" value="{_esc(data_atual)}" required disabled>'
            '</div>'
        )
    # Estado inicial: "hoje" — exceto edição de uma ficha com data diferente de hoje.
    eh_hoje = (not data_atual) or (data_atual == hoje_iso)
    valor = data_atual or hoje_iso
    chk_hoje = " checked" if eh_hoje else ""
    chk_outro = "" if eh_hoje else " checked"
    estilo = "display:none;" if eh_hoje else ""
    return (
        '<div class="campo largo">'
        '<label>Quando foi gravado? <span class="estrela">★</span></label>'
        '<div class="radio-linha">'
        f'<label class="radio-op"><input type="radio" name="grav_quando" value="hoje"{chk_hoje}> Hoje</label>'
        f'<label class="radio-op"><input type="radio" name="grav_quando" value="outro"{chk_outro}> Outro dia</label>'
        '</div>'
        f'<input type="date" name="data_gravacao" id="campo-data" value="{_esc(valor)}" '
        f'data-hoje="{hoje_iso}" required style="margin-top:8px;{estilo}">'
        '</div>'
    )


def _bloco_operador_ficha(d, eh_operador):
    """
    "Quem preencheu?" — diferente por contexto (2.2, decisão s33):

    - Base (operador local): campo de texto livre (o login real virá numa fatia
      futura; por ora o operador digita ou deixa em branco).
    - Remoto (profissional pelo celular): "Eu mesmo" (padrão) ou "Outra pessoa".
      Em "Eu mesmo" o campo de nome some — o servidor usa o próprio nome do
      profissional, sem redundância. Em "Outra pessoa", abre o campo do nome.
    """
    operador_atual = (d.get("operador") or "").strip()
    if eh_operador:
        return (
            '<div class="campo">'
            '<label>Quem preencheu <span class="ajuda">(operador do check-in)</span></label>'
            f'<input type="text" name="operador" value="{_esc(operador_atual)}" placeholder="opcional">'
            '</div>'
        )
    # Remoto: se já há um operador salvo (edição), começa em "Outra pessoa".
    tem_outro = bool(operador_atual)
    chk_proprio = "" if tem_outro else " checked"
    chk_outro = " checked" if tem_outro else ""
    estilo = "" if tem_outro else "display:none;"
    return (
        '<div class="campo largo">'
        '<label>Quem está preenchendo?</label>'
        '<div class="radio-linha">'
        f'<label class="radio-op"><input type="radio" name="preenchido_por" value="proprio"{chk_proprio}> Eu mesmo</label>'
        f'<label class="radio-op"><input type="radio" name="preenchido_por" value="outro"{chk_outro}> Outra pessoa</label>'
        '</div>'
        f'<input type="text" name="operador" id="campo-operador" value="{_esc(operador_atual)}" '
        f'placeholder="nome de quem preencheu" style="margin-top:8px;{estilo}">'
        '</div>'
    )


def _html_ficha(dados=None, erro=None, modo="nova", ficha_id=None,
                bloquear_criticos=False, mostrar_recentes=True,
                chips_selecionados=None, textos_selecionados=None, novo=False):
    """
    Monta o HTML do formulário de check-in.

    modo="nova"   → cria uma ficha (action /ficha).
    modo="editar" → edita a ficha ficha_id (action /ficha/<id>/editar).
    bloquear_criticos → trava nome/câmera/tipo/data (ficha já tem match: mexer aqui
                        afeta numeração/pasta de destino — segurança dos arquivos).
    chips_selecionados → conjunto de ids de itens de lista já escolhidos (edição /
                        reapresentação após erro), para remarcar os chips.
    """
    d = dados or {}
    sug = _sugestoes_gabarito()
    editando = (modo == "editar")

    # ── Tela de descanso da aba Posts (operador) ────────────────────────────
    # Inverte o peso (s57): o RELATÓRIO dos Posts é a tela de descanso e criar
    # vira um botão "+ Novo Post" (→ /ficha?novo=1). Só dispara no GET LIMPO do
    # operador: a câmera remota (mostrar_recentes False), a edição, e o
    # re-render após erro de envio (traz `erro`/`dados`) caem no formulário.
    if mostrar_recentes and not editando and not novo and not erro and dados is None:
        relatorio = _fichas_recentes_html()
        if not relatorio:
            relatorio = ('<p class="legenda" style="text-align:center;padding:28px 0">'
                         'Nenhum Post ainda. Crie o primeiro com "+ Novo Post".</p>')
        corpo_descanso = f"""
    <div style="display:flex;align-items:center;justify-content:space-between;gap:16px;margin-bottom:18px;flex-wrap:wrap">
      <p class="legenda" style="margin:0;max-width:560px">Os Posts deste evento, agrupados por status. Crie um novo ou gerencie os existentes (editar, cancelar, restaurar).</p>
      <a href="/ficha?novo=1" style="background:var(--6f-teal);color:var(--6f-bg-base);text-decoration:none;font-weight:600;padding:10px 22px;border-radius:8px;white-space:nowrap">+ Novo Post</a>
    </div>
    {relatorio}"""
        head_extra_descanso = f"<style>{CSS_FICHA}</style>{JS_CHIPS}{JS_CHIP_NOVO}{JS_TEXTO_GRUPO}{JS_FICHA_TOGGLES}{JS_SHOWS_CASCATA}"
        return _pagina("Posts", "ficha", corpo_descanso, head_extra_descanso)

    action = f"/ficha/{ficha_id}/editar" if editando else "/ficha"
    bloco_erro = f'<div class="erro-box">⚠️ {_esc(erro)}</div>' if erro else ""

    # Atributo HTML que desabilita os campos críticos quando a ficha já tem match.
    trava = " disabled" if bloquear_criticos else ""
    aviso_trava = (
        '<div class="aviso-trava">🔒 Post Matched — esta ficha já tem match com material. Nome, '
        'tipo e data ficam travados (mexer aqui afetaria a numeração e a pasta no HD). '
        'Você ainda pode ajustar os campos editoriais abaixo.</div>'
        if bloquear_criticos else ""
    )

    if editando:
        legenda = ('Edite os dados desta ficha. Campos com '
                   '<span style="color:var(--6f-erro)">★</span> são obrigatórios.')
        texto_botao = "Salvar alterações"
    else:
        legenda = ('Preencha a ficha do cartão que chegou na base. Campos com '
                   '<span style="color:var(--6f-erro)">★</span> são obrigatórios.')
        texto_botao = "Enviar ficha"

    # Carrega a lista de profissionais cadastrados para o JS da ficha.
    # Se falhar (banco indisponível), a ficha ainda abre — dropdowns ficarão vazios.
    profissionais = _profissionais_para_ficha()

    # Operador (base/local) vê ferramentas a mais que o profissional remoto.
    eh_operador = _host_local()
    # Data de hoje (para o bloco "Quando foi gravado?" assumir o caso comum).
    hoje_iso = datetime.now().strftime("%Y-%m-%d")

    # Monta o bloco TIPO (checkboxes) + NOME (dropdowns fechados) — Nova Ficha v2 Fatia 3.
    bloco_tipo_nome = _bloco_tipo_nome_ficha(d, trava, profissionais)

    # Bloco "Quando foi gravado?" (2.1) e "Quem preencheu?" (2.2).
    bloco_data = _bloco_data_ficha(d, trava, hoje_iso)
    bloco_operador = _bloco_operador_ficha(d, eh_operador)

    # Monta o bloco CLASSIFICAÇÃO (chips das listas de contexto) — ponte chips→ficha.
    bloco_classificacao = _bloco_classificacao_ficha(chips_selecionados,
                                                     eh_operador=eh_operador,
                                                     textos_selecionados=textos_selecionados)

    # Link de volta à tela de Posts (operador no modo formulário; não na edição,
    # que tem seu próprio Cancelar, nem no remoto, que não vê a lista de Posts).
    voltar_posts = ('<a class="btn-secundario" href="/ficha" '
                    'style="display:inline-block;margin-bottom:14px">← Voltar aos Posts</a>'
                    if (mostrar_recentes and not editando) else '')

    corpo = f"""
    {voltar_posts}
    <p class="legenda">{legenda}</p>
    {bloco_erro}
    {aviso_trava}
    <form class="ficha-form" action="{action}" method="post">
      {_datalist('lista_modelos', sug['modelos'])}
      <div class="ficha-grid">
        {bloco_tipo_nome}
        {bloco_data}

        {bloco_classificacao}

        <div class="grupo-titulo">Opcionais (ajudam o sistema e os editores)</div>

        {bloco_operador}
        <div class="campo">
          <label>Modelo da câmera</label>
          <input type="text" name="modelo_camera" list="lista_modelos"
                 value="{_esc(d.get('modelo_camera',''))}" placeholder="ex: FX3, HERO7">
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
    </form>"""

    head_extra = f"<style>{CSS_FICHA}</style>{JS_CHIPS}{JS_CHIP_NOVO}{JS_TEXTO_GRUPO}{JS_FICHA_TOGGLES}{JS_SHOWS_CASCATA}"
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
    if "tipo_material" in dados:
        out["tipo_material"] = dados.get("tipo_material", "").strip().upper()
        # Mantém os booleanos em sincronia com o texto editado (Fatia 5).
        tipos = _derivar_tipos(out["tipo_material"])
        out["tem_foto"], out["tem_audio"], out["tem_video"] = (
            tipos["tem_foto"], tipos["tem_audio"], tipos["tem_video"])
    if "nome_audio" in dados:     out["nome_audio"] = dados.get("nome_audio", "").strip().upper() or None
    if "data_gravacao" in dados:  out["data_gravacao"] = dados.get("data_gravacao", "").strip()
    if "operador" in dados:       out["operador"] = dados.get("operador", "").strip() or None
    if "modelo_camera" in dados:  out["modelo_camera"] = dados.get("modelo_camera", "").strip() or None
    if "tipo_conteudo" in dados:  out["tipo_conteudo"] = dados.get("tipo_conteudo", "").strip().upper() or None
    if "local_cena" in dados:     out["local_cena"] = dados.get("local_cena", "").strip() or None
    if "prioridade" in dados:     out["prioridade"] = dados.get("prioridade", "NORMAL").strip().upper() or "NORMAL"
    if "observacoes" in dados:    out["observacoes"] = dados.get("observacoes", "").strip() or None
    if "origem_material" in dados:
        # Garante que só valores válidos entram; qualquer outro vira "cartao" (padrão seguro).
        _orig = dados.get("origem_material", "cartao") or "cartao"
        out["origem_material"] = _orig if _orig in ("cartao", "recebido") else "cartao"
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
    novo = bool(request.args.get("novo"))
    return _html_ficha(mostrar_recentes=_host_local(), novo=novo), 200, {"Content-Type": "text/html; charset=utf-8"}


@app.route("/ficha", methods=["POST"])
def ficha_enviar():
    """
    Recebe o envio do formulário do navegador (form-encoded), reaproveita a função
    central de validação + gravação + Matcher, e mostra uma tela de confirmação
    (em vez do JSON cru que os webhooks recebem).
    """
    dados = request.form.to_dict()
    # to_dict() perde valores repetidos — os chips chegam como vários campos "chip".
    chips = request.form.getlist("chip")
    dados["chips"] = chips
    # Grupos de texto: campos "texto_<chave>" (vários por grupo) — Fatia texto (s33).
    textos = _coletar_textos_form(request.form)
    dados["textos"] = textos

    # A função central devolve (resposta_json, codigo_http). Reutilizamos toda a
    # lógica testada e só interpretamos o resultado para montar uma tela amigável.
    resposta, codigo = _processar_e_salvar_formulario(dados, origem="FICHA")
    payload = resposta.get_json()

    if not payload.get("ok"):
        # Validação falhou — remostra o formulário com o erro, os valores digitados
        # e os chips que o profissional já tinha marcado.
        corpo = _html_ficha(dados=dados, erro=payload.get("erro", "Erro ao salvar a ficha."),
                            chips_selecionados=set(chips), textos_selecionados=textos)
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
    if payload.get("split"):
        # Entrega mista: o áudio virou uma ficha à parte (transferência separada).
        titulo_ok = "✅ Entrega registrada — 2 fichas (áudio à parte)"
        tipo_fv = _tipo_display(_tipo_canonico(
            _derivar_tipos(dados.get('tipo_material',''))["tem_foto"], 0,
            _derivar_tipos(dados.get('tipo_material',''))["tem_video"]))
        resumo = f"""
      <div class="resumo">
        <div><b>Foto/Vídeo</b> {_esc(payload.get('nome'))} <span class="mono">({_esc(tipo_fv)})</span></div>
        <div><b>Áudio</b> {_esc(payload.get('nome_audio'))} <span class="mono">(à parte)</span></div>
        <div><b>Data</b> {_esc(dados.get('data_gravacao',''))}</div>
      </div>
      <p style="margin-top:8px;color:var(--6f-texto-2);font-size:0.9em">
        O áudio é sempre transferência separada — cada um dá match com seu próprio cartão.
      </p>"""
    else:
        titulo_ok = "✅ Ficha recebida com sucesso"
        # ── Bloco extra para Posts satélite (Peça 2 — acesso externo) ──────────
        # Quando o material NÃO vem por cartão físico, orienta o profissional remoto
        # sobre onde enviar o material. O link é definido pelo operador à mão;
        # enquanto vazio, exibe um aviso neutro.
        origem_enviada = (dados.get("origem_material") or "cartao")
        if origem_enviada == "recebido":
            # Tenta buscar o link já definido (o operador pode ter pré-configurado)
            link_nuvem = ""
            try:
                _conn_ficha = bd.obter_conexao()
                _id_form = payload.get("id_form")
                if _id_form:
                    _row_link = _conn_ficha.execute(
                        "SELECT link_recebidos FROM formularios WHERE id_form_original = ?",
                        (_id_form,)
                    ).fetchone()
                    if _row_link:
                        link_nuvem = (_row_link["link_recebidos"] or "").strip()
                _conn_ficha.close()
            except Exception:
                pass

            if link_nuvem:
                bloco_link = (
                    f"<div style='margin-top:12px;padding:10px 14px;background:var(--6f-teal-trilho);"
                    f"border-left:4px solid var(--6f-teal);border-radius:4px'>"
                    f"<b>📂 Envie seu material para:</b><br>"
                    f"<a href='{_esc(link_nuvem)}' target='_blank' "
                    f"style='word-break:break-all'>{_esc(link_nuvem)}</a></div>"
                )
            else:
                bloco_link = (
                    "<div style='margin-top:12px;padding:10px 14px;background:var(--6f-bg-elevado);"
                    "border-left:4px solid var(--6f-aviso);border-radius:4px;color:var(--6f-aviso)'>"
                    "📂 O operador vai disponibilizar o link de envio em breve. "
                    "Aguarde a confirmação antes de fazer o upload.</div>"
                )
        else:
            bloco_link = ""

        resumo = f"""
      <div class="resumo">
        <div><b>Nome</b> {_esc(payload.get('nome'))}</div>
        <div><b>Tipo</b> {_esc(_tipo_display(dados.get('tipo_material','')))}</div>
        <div><b>Data</b> {_esc(dados.get('data_gravacao',''))}</div>
        <div><b>ID da ficha</b> <span class="mono">{_esc(payload.get('id_form'))}</span></div>
      </div>
      {bloco_link}"""
    # Botões de gestão (Kanban/Planilha) só na BASE; o link remoto da câmera
    # recebe apenas "preencher outra ficha".
    if _host_local():
        botoes = """
        <a class="btn-secundario" href="/ficha?novo=1">Preencher outra ficha</a>
        <a class="btn-secundario" href="/kanban">Ver no Mural</a>
        <a class="btn-secundario" href="/planilha">Ver na Planilha</a>"""
    else:
        botoes = '<a class="btn-secundario" href="/ficha">Preencher outra ficha</a>'
    corpo = f"""
    <div class="ok-box">
      <h2>{titulo_ok}</h2>
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
    # Carrega os chips e os textos já preenchidos, para repor na ficha.
    chips_sel = set()
    textos_sel = {}
    try:
        conn = bd.obter_conexao()
        chips_sel = {str(c["item_id"]) for c in bd.listar_chips_formulario(conn, ficha_id)}
        textos_sel = bd.listar_textos_formulario(conn, ficha_id)
        conn.close()
    except Exception as erro:
        logger.error(f"FICHA | Erro ao carregar chips/textos da ficha {ficha_id} | {erro}")
    corpo = _html_ficha(dados=ficha, modo="editar", ficha_id=ficha_id,
                        bloquear_criticos=bloquear, chips_selecionados=chips_sel,
                        textos_selecionados=textos_sel)
    return corpo, 200, {"Content-Type": "text/html; charset=utf-8"}


@app.route("/ficha/<int:ficha_id>/editar", methods=["POST"])
def ficha_editar_salvar(ficha_id):
    """
    Salva a edição de uma ficha. Se a ficha já tem match, ignora os campos críticos
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
    # Chips de classificação (editoriais): editáveis mesmo com a ficha já com match.
    chips = request.form.getlist("chip")
    # Valores de texto (grupos de modo 'texto') — também editoriais.
    textos = _coletar_textos_form(request.form)

    # Se os críticos estão travados, descarta-os do que veio (defesa no servidor —
    # não confia só no 'disabled' do HTML).
    if bloquear:
        for campo in ("nome", "tipo_material", "data_gravacao"):
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
                bloquear_criticos=bloquear, chips_selecionados=set(chips),
                textos_selecionados=textos,
                erro=f"Formato de data inválido: '{campos['data_gravacao']}'. Use AAAA-MM-DD.",
            )
            return corpo, 422, {"Content-Type": "text/html; charset=utf-8"}

    # Grava no banco (whitelist na própria função) + sincroniza a fila JSON.
    # Os chips são gravados sempre — a classificação é editorial e pode mudar mesmo
    # quando nenhum outro campo mudou.
    try:
        conn = bd.obter_conexao()
        bd.atualizar_formulario(conn, ficha_id, campos)
        bd.definir_chips_formulario(conn, ficha_id, chips)
        bd.definir_textos_formulario(conn, ficha_id, textos)
        conn.close()
        _atualizar_json_fila(ficha.get("id_form_original"), campos)
        logger.info(f"FICHA | Ficha {ficha_id} editada | campos={list(campos.keys())} | chips={len(chips)} | textos={sum(len(v) for v in textos.values())}")
    except Exception as erro:
        logger.error(f"FICHA | Erro ao salvar edição da ficha {ficha_id} | {erro}")
        corpo = _html_ficha(
            dados={**ficha, **enviados}, modo="editar", ficha_id=ficha_id,
            bloquear_criticos=bloquear, chips_selecionados=set(chips),
            erro="Erro interno ao salvar. Tente de novo.",
        )
        return corpo, 500, {"Content-Type": "text/html; charset=utf-8"}

    atualizada = _carregar_ficha(ficha_id) or {}
    corpo = f"""
    <div class="ok-box">
      <h2>✅ Ficha #{ficha_id} atualizada</h2>
      <div class="resumo">
        <div><b>Nome</b> {_esc(atualizada.get('nome'))}</div>
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
    caminho = os.path.join(
        painel_config.pasta_ao_lado_do_banco("contadores") if PAINEL_DISPONIVEL
        else os.path.join(RAIZ_GMA, "contadores"),
        f"{nome}.json")
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


# ── ROTAS: MATCH MANUAL ABERTO (cartão órfão ↔ ficha escolhida a dedo) ────
#
# Diferente do match/<id>/confirmar (que resolve EMPATES já registrados), aqui o
# operador une um cartão detectado a uma ficha qualquer que esteja esperando,
# mesmo quando o Matcher não pontuou o suficiente para gerar candidato. É o
# "último recurso" do princípio nº 3: o sistema tenta sozinho; quando não dá match,
# o operador faz o match na mão. Acesso só na base (o portão já barra remoto).
#
#   1. /match-manual/confirmar (POST) — tela de resumo (revisar antes de gravar)
#   2. /match-manual/iniciar   (POST) — executa: chama matcher.fazer_match_manual


@app.route("/match-manual/confirmar", methods=["POST"])
def match_manual_confirmar():
    """
    Tela de resumo do match manual. Recebe cartao_id + formulario_id (as duas
    bolinhas escolhidas no painel) e mostra lado a lado o cartão e a ficha + a
    pasta de destino prevista, antes de gravar. Não dá match em nada ainda.
    """
    try:
        cartao_id     = int(request.form.get("cartao_id") or 0)
        formulario_id = int(request.form.get("formulario_id") or 0)
    except (TypeError, ValueError):
        cartao_id = formulario_id = 0

    if not cartao_id or not formulario_id:
        return redirect("/?aviso=match_selecao_incompleta")

    # Dados para o resumo
    volume = f"Cartao {cartao_id}"
    camera_detectada = "—"
    n_arquivos = "?"
    nome_ficha = ""
    camera_ficha = "—"

    if BANCO_DISPONIVEL:
        try:
            _conn = bd.obter_conexao()
            lc = _conn.execute(
                "SELECT volume, marca_camera, total_arquivos_detectados "
                "FROM cartoes WHERE id = ?", (cartao_id,)
            ).fetchone()
            lf = _conn.execute(
                "SELECT nome, camera, status FROM formularios WHERE id = ?",
                (formulario_id,)
            ).fetchone()
            _conn.close()
            if lc:
                volume           = lc["volume"] or volume
                camera_detectada = lc["marca_camera"] or "—"
                n_arquivos       = lc["total_arquivos_detectados"] or "?"
            if lf:
                nome_ficha   = (lf["nome"] or "").strip().upper()
                camera_ficha = lf["camera"] or "—"
        except Exception as _err:
            logger.error(f"MATCH MANUAL CONFIRMAR | Erro ao ler banco | {_err}")

    if not nome_ficha:
        return redirect("/?aviso=match_ficha_invalida")

    pasta = _pasta_prevista(nome_ficha)

    corpo = f"""
    <div style="background:#fff;border-radius:8px;box-shadow:0 1px 4px rgba(0,0,0,0.08);
                padding:24px 28px;max-width:640px;margin:0 auto">
        <h2 style="font-size:1.15em;margin-bottom:16px;color:#1a1a2e">
            Match na mão — revise antes de gravar
        </h2>
        <div style="display:flex;gap:16px;margin-bottom:20px;flex-wrap:wrap">
            <div style="flex:1;min-width:240px;background:#fff8e1;border:1px solid #f59e0b;
                        border-radius:6px;padding:14px 18px;line-height:1.9">
                <div style="font-weight:700;color:#92600a;margin-bottom:6px">CARTÃO</div>
                <div><b style="color:#6c757d">Volume</b> &nbsp;{_esc(volume)}</div>
                <div><b style="color:#6c757d">Câmera</b> &nbsp;{_esc(camera_detectada)}</div>
                <div><b style="color:#6c757d">Arquivos</b> &nbsp;{_esc(str(n_arquivos))}</div>
            </div>
            <div style="flex:1;min-width:240px;background:#e8f5e9;border:1px solid #4caf50;
                        border-radius:6px;padding:14px 18px;line-height:1.9">
                <div style="font-weight:700;color:#2e7d32;margin-bottom:6px">FICHA</div>
                <div><b style="color:#6c757d">Profissional</b> &nbsp;{_esc(nome_ficha)}</div>
                <div><b style="color:#6c757d">Câmera</b> &nbsp;{_esc(camera_ficha)}</div>
            </div>
        </div>
        <div style="background:#f8f9fa;border-radius:6px;padding:12px 18px;margin-bottom:20px">
            <b style="color:#6c757d">Pasta de destino prevista</b><br>
            <span style="font-family:monospace;font-size:1.1em;color:#1a1a2e">{_esc(pasta)}</span>
        </div>
        <p style="color:#856404;background:#fff3cd;border:1px solid #ffc107;border-radius:5px;
                  padding:10px 14px;margin-bottom:20px;font-size:0.9em">
            Confira se o cartão é mesmo deste profissional. Ao confirmar, a cópia
            começa e a pasta nasce com este nome — desfazer durante o evento é trabalhoso.
        </p>
        <div style="display:flex;gap:12px;align-items:center">
            <form action="/match-manual/iniciar" method="post">
                <input type="hidden" name="cartao_id" value="{cartao_id}">
                <input type="hidden" name="formulario_id" value="{formulario_id}">
                <button type="submit"
                        style="background:#8e44ad;color:#fff;border:none;border-radius:6px;
                               padding:10px 24px;font-weight:700;font-size:0.95em;cursor:pointer;">
                    Confirmar match e iniciar transferência
                </button>
            </form>
            <a href="/" style="background:#6c757d;color:#fff;text-decoration:none;border-radius:6px;
                      padding:10px 20px;font-weight:600;font-size:0.9em">Cancelar</a>
        </div>
    </div>"""

    return _pagina(f"Match na mão — {nome_ficha}", "operacao", corpo), 200, \
        {"Content-Type": "text/html; charset=utf-8"}


@app.route("/match-manual/iniciar", methods=["POST"])
def match_manual_iniciar():
    """
    Executa o match manual: chama matcher.fazer_match_manual(), que grava
    o par no banco e marca os JSONs como 'matched' (a Camada 2 inicia a cópia).
    Erros são tratados defensivamente — nunca derrubam o servidor.
    """
    try:
        cartao_id     = int(request.form.get("cartao_id") or 0)
        formulario_id = int(request.form.get("formulario_id") or 0)
    except (TypeError, ValueError):
        cartao_id = formulario_id = 0

    if not cartao_id or not formulario_id:
        return redirect("/?aviso=match_selecao_incompleta")

    resultado = {"ok": False, "motivo": "matcher_indisponivel"}
    if MATCHER_DISPONIVEL:
        try:
            resultado = modulo_matcher.fazer_match_manual(cartao_id, formulario_id)
        except Exception as _err_exec:
            logger.error(
                f"MATCH MANUAL INICIAR | Erro inesperado | Cartao: {cartao_id} "
                f"| Ficha: {formulario_id} | Erro: {_err_exec}"
            )
            resultado = {"ok": False, "motivo": f"erro_interno: {_err_exec}"}
    else:
        logger.error(
            f"MATCH MANUAL INICIAR | Matcher indisponivel | Cartao: {cartao_id} "
            f"| Ficha: {formulario_id}"
        )

    if resultado.get("ok"):
        nome = resultado.get("nome", "?")
        logger.info(
            f"MATCH MANUAL INICIAR | Match feito com sucesso | Cartao: {cartao_id} "
            f"| Ficha: {formulario_id} | Nome: {nome}"
        )
        return redirect(f"/?ok=Match feito — {nome} · transferencia iniciada")

    # Falha conhecida → mensagem legível
    motivo = resultado.get("motivo", "motivo_desconhecido")
    logger.warning(
        f"MATCH MANUAL INICIAR | Sem match | Cartao: {cartao_id} "
        f"| Ficha: {formulario_id} | Motivo: {motivo}"
    )
    mapa_msg = {
        "cartao_ja_com_match":  "Este cartão já tem match com uma ficha. Atualize o painel.",
        "ficha_ja_com_match":   "Esta ficha já tem match com um cartão. Atualize o painel.",
        "cartao_inexistente": "Cartão não encontrado no banco. Atualize o painel.",
        "ficha_inexistente":  "Ficha não encontrada no banco. Atualize o painel.",
        "matcher_indisponivel": ("O módulo Matcher não está disponível. "
                                 "Verifique matcher.py e reinicie o servidor."),
    }
    descricao = mapa_msg.get(motivo, f"Detalhe técnico: {_esc(motivo)}")

    corpo = f"""
    <div style="background:#fdecea;border:1px solid #f5c6cb;color:#c0392b;
                border-radius:6px;padding:16px 20px;max-width:540px;margin:0 auto">
        <strong>Não foi possível fazer o match.</strong>
        <br><br>{descricao}<br><br>
        <a href="/" style="color:#c0392b;font-weight:600">Voltar ao painel</a>
    </div>"""
    return _pagina("Erro — match na mão", "operacao", corpo), 409, \
        {"Content-Type": "text/html; charset=utf-8"}


# ── ROTA: CADASTRO E LISTAGEM DE PROFISSIONAIS ────────────────────────────────

@app.route("/profissionais", methods=["GET", "POST"])
def profissionais():
    """
    GET  /profissionais → lista os profissionais cadastrados + formulário de novo cadastro.
    POST /profissionais → cadastra um novo profissional e redireciona de volta.

    Acesso: somente base (localhost). Remoto recebe 403 pelo portão existente.
    """
    # ── POST: cadastrar novo profissional ─────────────────────────────────────
    if request.method == "POST":
        nome_raw   = (request.form.get("nome") or "").strip()
        tem_foto   = bool(request.form.get("tem_foto"))
        tem_audio  = bool(request.form.get("tem_audio"))
        tem_video  = bool(request.form.get("tem_video"))
        camera_raw = (request.form.get("camera") or "").strip()

        erro_cadastro = None

        if not nome_raw:
            erro_cadastro = "O nome não pode ser vazio."
        elif not (tem_foto or tem_audio or tem_video):
            erro_cadastro = "Marque ao menos um tipo (Foto, Áudio ou Vídeo)."
        elif not BANCO_DISPONIVEL:
            erro_cadastro = "Banco de dados indisponível. Verifique banco_dados.py."
        else:
            try:
                _conn = bd.obter_conexao()
                bd.criar_profissional(
                    _conn,
                    nome_raw,
                    {"foto": tem_foto, "audio": tem_audio, "video": tem_video},
                    camera=camera_raw,
                )
                _conn.close()
                logger.info(
                    f"PROFISSIONAIS | Cadastrado: {nome_raw.upper()} "
                    f"| foto={tem_foto} audio={tem_audio} video={tem_video} "
                    f"| camera={camera_raw or '—'}"
                )
                return redirect("/profissionais")
            except Exception as _err:
                import sqlite3 as _sqlite3
                if isinstance(_err, _sqlite3.IntegrityError):
                    # Distingue QUAL restrição UNIQUE estourou — antes assumíamos
                    # sempre o nome, o que mascarava uma colisão de letra.
                    if "letra" in str(_err).lower():
                        erro_cadastro = ("Conflito interno na letra sequencial. "
                                         "Isto não deveria acontecer — avise o desenvolvedor.")
                    else:
                        erro_cadastro = f"'{nome_raw.upper()}' já está cadastrado."
                else:
                    erro_cadastro = f"Erro ao cadastrar: {_err}"
                logger.warning(f"PROFISSIONAIS | Erro no cadastro: {_err}")

        # Houve erro → re-renderiza a página com a mensagem e preserva o digitado
        return _pagina_profissionais(
            erro=erro_cadastro,
            nome_digitado=nome_raw,
            foto_marcada=tem_foto,
            audio_marcado=tem_audio,
            video_marcado=tem_video,
            camera_digitada=camera_raw,
        )

    # ── GET: exibir lista + formulário ────────────────────────────────────────
    return _pagina_profissionais()


@app.route("/profissionais/<int:prof_id>/ativo", methods=["POST"])
def profissionais_ativo(prof_id):
    """
    Ativa ou desativa um profissional (soft-delete). O campo 'ativo' do form diz
    o estado desejado: "1" = ativar, "0" = desativar. Desativar NÃO apaga nada —
    o profissional só some dos dropdowns da ficha. Volta para a lista no fim.

    Acesso: somente base (localhost). Remoto recebe 403 pelo portão existente.
    """
    if not BANCO_DISPONIVEL:
        return _pagina_profissionais(erro="Banco de dados indisponível.")

    novo_estado = (request.form.get("ativo") == "1")
    try:
        _conn = bd.obter_conexao()
        ok = bd.definir_ativo_profissional(_conn, prof_id, novo_estado)
        _conn.close()
        if ok:
            logger.info(
                f"PROFISSIONAIS | id={prof_id} → {'ATIVADO' if novo_estado else 'DESATIVADO'}"
            )
        else:
            logger.warning(f"PROFISSIONAIS | id={prof_id} não encontrado ao alternar 'ativo'")
    except Exception as _err:
        logger.error(f"PROFISSIONAIS | Erro ao alternar 'ativo' (id={prof_id}): {_err}")
        return _pagina_profissionais(erro=f"Erro ao mudar a situação: {_err}")

    return redirect("/profissionais")


@app.route("/profissionais/<int:prof_id>/camera", methods=["POST"])
def profissionais_camera(prof_id):
    """
    Atualiza a câmera de um profissional (mini-form inline na tabela). A câmera é o
    que o Matcher compara com a marca detectada no cartão (critério +3). Vazio →
    grava NULL (profissional sem câmera definida). Volta para a lista no fim.

    Acesso: somente base (localhost). Remoto recebe 403 pelo portão existente.
    """
    if not BANCO_DISPONIVEL:
        return _pagina_profissionais(erro="Banco de dados indisponível.")

    camera_raw = (request.form.get("camera") or "").strip()
    try:
        _conn = bd.obter_conexao()
        ok = bd.definir_camera_profissional(_conn, prof_id, camera_raw)
        _conn.close()
        if ok:
            logger.info(f"PROFISSIONAIS | id={prof_id} câmera → {camera_raw or '—'}")
        else:
            logger.warning(f"PROFISSIONAIS | id={prof_id} não encontrado ao gravar câmera")
    except Exception as _err:
        logger.error(f"PROFISSIONAIS | Erro ao gravar câmera (id={prof_id}): {_err}")
        return _pagina_profissionais(erro=f"Erro ao gravar a câmera: {_err}")

    return redirect("/profissionais")


@app.route("/profissionais/<int:prof_id>/nomes", methods=["POST"])
def profissionais_nomes(prof_id):
    """
    Edita os nomes curtos de um profissional (#5 s39): pasta do dia (nome_raiz) e
    cartão (nome_curto). Só permitido ANTES do primeiro cartão logado — depois o
    banco trava (mudar quebraria pastas/numeração já criadas).

    Acesso: somente base (localhost). Remoto recebe 403 pelo portão existente.
    """
    if not BANCO_DISPONIVEL:
        return _pagina_profissionais(erro="Banco de dados indisponível.")

    nome_raiz = (request.form.get("nome_raiz") or "").strip()
    nome_curto = (request.form.get("nome_curto") or "").strip()
    try:
        _conn = bd.obter_conexao()
        resultado = bd.definir_nomes_profissional(
            _conn, prof_id, nome_raiz=nome_raiz, nome_curto=nome_curto
        )
        _conn.close()
    except Exception as _err:
        logger.error(f"PROFISSIONAIS | Erro ao gravar nomes (id={prof_id}): {_err}")
        return _pagina_profissionais(erro=f"Erro ao gravar os nomes: {_err}")

    if resultado == "travado":
        logger.warning(f"PROFISSIONAIS | nomes recusados (id={prof_id}): cartão já logado")
        return _pagina_profissionais(
            erro="Esse profissional já tem cartão logado — os nomes ficam travados "
                 "para não quebrar as pastas já criadas."
        )
    if resultado == "duplicado":
        return _pagina_profissionais(
            erro=f"O nome de cartão '{nome_curto.upper()}' já pertence a outro profissional."
        )
    if resultado == "vazio":
        return _pagina_profissionais(erro="Os nomes não podem ficar vazios.")
    if resultado == "inexistente":
        return redirect("/profissionais")

    logger.info(f"PROFISSIONAIS | id={prof_id} nomes → pasta={nome_raiz} cartão={nome_curto}")
    return redirect("/profissionais")


@app.route("/profissionais/<int:prof_id>/excluir", methods=["POST"])
def profissionais_excluir(prof_id):
    """
    Exclui um profissional DEFINITIVAMENTE — só se for sobra real (nenhuma ficha
    usa o nome). Se estiver em uso, recusa e orienta a desativar. Irreversível.

    Acesso: somente base (localhost). Remoto recebe 403 pelo portão existente.
    """
    if not BANCO_DISPONIVEL:
        return _pagina_profissionais(erro="Banco de dados indisponível.")

    try:
        _conn = bd.obter_conexao()
        resultado = bd.excluir_profissional(_conn, prof_id)
        _conn.close()
    except Exception as _err:
        logger.error(f"PROFISSIONAIS | Erro ao excluir (id={prof_id}): {_err}")
        return _pagina_profissionais(erro=f"Erro ao excluir: {_err}")

    if resultado == "em_uso":
        logger.warning(f"PROFISSIONAIS | Exclusão recusada (id={prof_id}): nome em uso por fichas")
        return _pagina_profissionais(
            erro="Não dá para excluir: esse nome já aparece em alguma ficha. "
                 "Use Desativar (reversível) no lugar."
        )
    if resultado == "inexistente":
        logger.warning(f"PROFISSIONAIS | Exclusão: id={prof_id} não encontrado")
        return redirect("/profissionais")

    logger.info(f"PROFISSIONAIS | id={prof_id} EXCLUÍDO (sobra sem fichas)")
    return redirect("/profissionais")


def _pagina_profissionais(
    erro=None,
    nome_digitado="",
    foto_marcada=False,
    audio_marcado=False,
    video_marcado=False,
    camera_digitada="",
):
    """
    Renderiza a página de profissionais.
    Separa a geração do HTML da lógica da rota para facilitar o reuso
    (a rota POST chama esta função com os dados preservados em caso de erro).
    """
    # ── Carrega a lista do banco ───────────────────────────────────────────────
    lista = []
    em_uso = set()  # nomes que aparecem em alguma ficha → não podem ser excluídos
    travados = set()  # nomes com cartão logado → nomes curtos travados p/ edição
    aviso_banco = ""
    if BANCO_DISPONIVEL:
        try:
            _conn = bd.obter_conexao()
            lista = bd.listar_profissionais(_conn)
            em_uso = bd.nomes_em_uso(_conn)
            travados = bd.profissionais_travados(_conn)
            _conn.close()
        except Exception as _err_lista:
            aviso_banco = f"Não foi possível carregar a lista: {_err_lista}"
    else:
        aviso_banco = "Banco de dados indisponível."

    # ── Monta as linhas da tabela ──────────────────────────────────────────────
    def _icone(valor):
        return "✓" if valor else "—"

    def _cor_icone(valor):
        return "color:var(--6f-teal);font-weight:700" if valor else "color:var(--6f-texto-3)"

    if lista:
        linhas_tabela = ""
        for p in lista:
            ativo = p.get("ativo", True)
            # Linha "apagadinha" quando o profissional está desativado.
            estilo_linha = "" if ativo else "opacity:0.5"
            # Botão que alterna o estado: desativados mostram "Ativar"; ativos, "Desativar".
            if ativo:
                botao = (
                    '<button type="submit" name="ativo" value="0" '
                    'style="background:var(--6f-bg-elevado);border:1px solid var(--6f-borda);color:var(--6f-erro);'
                    'border-radius:5px;padding:4px 10px;font-size:0.82em;cursor:pointer;'
                    'font-family:inherit">Desativar</button>'
                )
                selo = ""
            else:
                botao = (
                    '<button type="submit" name="ativo" value="1" '
                    'style="background:var(--6f-teal);border:1px solid var(--6f-teal);color:var(--6f-bg-base);'
                    'border-radius:5px;padding:4px 10px;font-size:0.82em;cursor:pointer;'
                    'font-family:inherit">Ativar</button>'
                )
                selo = ('<span style="background:var(--6f-bg-hover);color:var(--6f-texto-2);border-radius:4px;'
                        'padding:1px 7px;font-size:0.74em;font-weight:600;margin-right:8px">'
                        'inativo</span>')

            # Excluir SÓ aparece para sobras reais: nome que não está em nenhuma ficha.
            # Quem já tocou em material só pode ser desativado (princípio 2: não destruir).
            nome_norm = (p["nome"] or "").strip().upper()
            pode_excluir = nome_norm not in em_uso
            if pode_excluir:
                botao_excluir = (
                    f'<form action="/profissionais/{p["id"]}/excluir" method="post" '
                    f'style="margin:0" '
                    f'onsubmit="return confirm(\'Excluir {_esc(p["nome"])} de vez? '
                    f'Só é possível porque não há nenhuma ficha com esse nome. Não tem volta.\')">'
                    '<button type="submit" '
                    'style="background:none;border:none;color:var(--6f-texto-3);font-size:0.82em;'
                    'cursor:pointer;text-decoration:underline;font-family:inherit;padding:0">'
                    'excluir</button></form>'
                )
            else:
                botao_excluir = (
                    '<span title="Tem ficha usando este nome — só dá para desativar" '
                    'style="color:var(--6f-texto-3);font-size:0.82em;cursor:default">excluir</span>'
                )

            # Mini-form inline da câmera: campo de texto + botão salvar. Submete
            # sozinho para /profissionais/<id>/camera (o Matcher usa isto no +3).
            camera_atual = p.get("camera") or ""
            celula_camera = (
                f'<form action="/profissionais/{p["id"]}/camera" method="post" '
                f'style="margin:0;display:flex;gap:5px;align-items:center">'
                f'<input type="text" name="camera" value="{_esc(camera_atual)}" '
                f'placeholder="—" autocomplete="off" '
                f'style="width:92px;padding:4px 7px;border:1px solid var(--6f-borda);'
                f'background:var(--6f-bg-elevado);color:var(--6f-texto);'
                f'border-radius:5px;font-size:0.85em;font-family:inherit">'
                f'<button type="submit" title="Salvar câmera" '
                f'style="background:var(--6f-bg-elevado);border:1px solid var(--6f-borda);color:var(--6f-texto);'
                f'border-radius:5px;padding:4px 8px;font-size:0.8em;cursor:pointer;'
                f'font-family:inherit">salvar</button>'
                f'</form>'
            )

            # Célula dos NOMES CURTOS (#5 s39): pasta do dia (raiz) + cartão (curto).
            # Editável até o 1º cartão logado; depois TRAVA (mudar quebraria pastas).
            raiz_atual = p.get("nome_raiz") or ""
            curto_atual = p.get("nome_curto") or ""
            travado = nome_norm in travados
            if travado:
                celula_nomes = (
                    f'<div style="font-size:0.82em;line-height:1.5;text-align:left">'
                    f'<div><span style="color:var(--6f-texto-3)">pasta</span> '
                    f'<span style="font-family:ui-monospace,monospace">{_esc(raiz_atual) or "—"}</span></div>'
                    f'<div><span style="color:var(--6f-texto-3)">cartão</span> '
                    f'<span style="font-family:ui-monospace,monospace;font-weight:600">{_esc(curto_atual) or "—"}</span> '
                    f'<span title="Travado: já tem cartão logado">🔒</span></div>'
                    f'</div>'
                )
            else:
                celula_nomes = (
                    f'<form action="/profissionais/{p["id"]}/nomes" method="post" '
                    f'style="margin:0;display:flex;flex-direction:column;gap:4px;text-align:left">'
                    f'<div style="display:flex;gap:4px;align-items:center">'
                    f'<span style="color:var(--6f-texto-3);font-size:0.74em;width:42px">pasta</span>'
                    f'<input type="text" name="nome_raiz" value="{_esc(raiz_atual)}" '
                    f'placeholder="NOME_SOBRENOME" autocomplete="off" '
                    f'style="width:130px;padding:3px 6px;border:1px solid var(--6f-borda);'
                    f'background:var(--6f-bg-elevado);color:var(--6f-texto);'
                    f'border-radius:5px;font-size:0.8em;font-family:ui-monospace,monospace"></div>'
                    f'<div style="display:flex;gap:4px;align-items:center">'
                    f'<span style="color:var(--6f-texto-3);font-size:0.74em;width:42px">cartão</span>'
                    f'<input type="text" name="nome_curto" value="{_esc(curto_atual)}" '
                    f'placeholder="SOBRENOME" autocomplete="off" '
                    f'style="width:130px;padding:3px 6px;border:1px solid var(--6f-borda);'
                    f'background:var(--6f-bg-elevado);color:var(--6f-texto);'
                    f'border-radius:5px;font-size:0.8em;font-family:ui-monospace,monospace">'
                    f'<button type="submit" title="Salvar nomes" '
                    f'style="background:var(--6f-bg-elevado);border:1px solid var(--6f-borda);color:var(--6f-texto);'
                    f'border-radius:5px;padding:3px 7px;font-size:0.76em;cursor:pointer;'
                    f'font-family:inherit">salvar</button></div>'
                    f'</form>'
                )

            linhas_tabela += f"""
            <tr style="{estilo_linha}">
                <td style="font-family:ui-monospace,monospace;font-size:1.1em;
                            font-weight:700;color:var(--6f-teal);letter-spacing:1px">
                    {_esc(p['letra'])}
                </td>
                <td style="font-weight:600;color:var(--6f-texto)">{selo}{_esc(p['nome'])}</td>
                <td style="text-align:left">{celula_nomes}</td>
                <td style="text-align:center;{_cor_icone(p['tem_foto'])}">{_icone(p['tem_foto'])}</td>
                <td style="text-align:center;{_cor_icone(p['tem_audio'])}">{_icone(p['tem_audio'])}</td>
                <td style="text-align:center;{_cor_icone(p['tem_video'])}">{_icone(p['tem_video'])}</td>
                <td style="text-align:center">{celula_camera}</td>
                <td style="text-align:center">
                    <div style="display:flex;gap:10px;align-items:center;justify-content:center">
                        <form action="/profissionais/{p['id']}/ativo" method="post" style="margin:0">
                            {botao}
                        </form>
                        {botao_excluir}
                    </div>
                </td>
            </tr>"""
    else:
        linhas_tabela = """
            <tr>
                <td colspan="8" style="text-align:center;color:var(--6f-texto-3);padding:24px">
                    Nenhum profissional cadastrado ainda.
                </td>
            </tr>"""

    # ── Bloco de erro (POST com problema) ─────────────────────────────────────
    bloco_erro = ""
    if erro:
        bloco_erro = f"""
        <div style="background:var(--6f-bg-elevado);border:1px solid var(--6f-erro);color:var(--6f-erro);
                    border-radius:6px;padding:12px 16px;margin-bottom:16px;font-size:0.9em">
            <strong>Erro:</strong> {_esc(erro)}
        </div>"""

    # ── Bloco de aviso de banco ────────────────────────────────────────────────
    bloco_aviso = ""
    if aviso_banco:
        bloco_aviso = f"""
        <div style="background:var(--6f-bg-elevado);border:1px solid var(--6f-aviso);color:var(--6f-aviso);
                    border-radius:6px;padding:12px 16px;margin-bottom:16px;font-size:0.9em">
            {_esc(aviso_banco)}
        </div>"""

    # ── Checkboxes com estado preservado ──────────────────────────────────────
    def _checked(valor):
        return "checked" if valor else ""

    # ── Corpo da página ────────────────────────────────────────────────────────
    corpo = f"""
    <div style="display:grid;grid-template-columns:1fr 340px;gap:24px;align-items:start">

        <!-- Tabela de profissionais cadastrados -->
        <div>
            <h2 style="font-size:1em;font-weight:700;color:var(--6f-texto);margin-bottom:12px">
                Profissionais cadastrados
                <span style="font-size:0.8em;font-weight:400;color:var(--6f-texto-2);margin-left:8px">
                    ({len(lista)} {'profissional' if len(lista) == 1 else 'profissionais'})
                </span>
            </h2>
            {bloco_aviso}
            <style>
                /* Organização mínima: respiro + linha separadora entre profissionais,
                   pra nomes longos não embolarem uns nos outros. */
                .tab-prof td {{ padding:12px 12px; border-bottom:1px solid var(--6f-borda);
                                vertical-align:middle; }}
                .tab-prof tbody tr:last-child td {{ border-bottom:none; }}
                .tab-prof tbody tr:hover td {{ background:var(--6f-bg-hover); }}
            </style>
            <table class="tab-prof" style="width:100%;border-collapse:collapse;background:var(--6f-bg-superficie);
                          border-radius:8px;overflow:hidden;border:1px solid var(--6f-borda);
                          box-shadow:none;font-size:0.88em">
                <thead>
                    <tr>
                        <th style="padding:9px 12px;text-align:left;background:var(--6f-bg-elevado);
                                   color:var(--6f-texto-2);text-transform:uppercase;font-size:0.78em;
                                   letter-spacing:0.4px;border-bottom:1px solid var(--6f-borda);
                                   width:60px">Letra</th>
                        <th style="padding:9px 12px;text-align:left;background:var(--6f-bg-elevado);
                                   color:var(--6f-texto-2);text-transform:uppercase;font-size:0.78em;
                                   letter-spacing:0.4px;border-bottom:1px solid var(--6f-borda)">Nome</th>
                        <th style="padding:9px 12px;text-align:left;background:var(--6f-bg-elevado);
                                   color:var(--6f-texto-2);text-transform:uppercase;font-size:0.78em;
                                   letter-spacing:0.4px;border-bottom:1px solid var(--6f-borda);
                                   width:200px">Pasta · Cartão</th>
                        <th style="padding:9px 12px;text-align:center;background:var(--6f-bg-elevado);
                                   color:var(--6f-texto-2);text-transform:uppercase;font-size:0.78em;
                                   letter-spacing:0.4px;border-bottom:1px solid var(--6f-borda);
                                   width:70px">Foto</th>
                        <th style="padding:9px 12px;text-align:center;background:var(--6f-bg-elevado);
                                   color:var(--6f-texto-2);text-transform:uppercase;font-size:0.78em;
                                   letter-spacing:0.4px;border-bottom:1px solid var(--6f-borda);
                                   width:70px">Áudio</th>
                        <th style="padding:9px 12px;text-align:center;background:var(--6f-bg-elevado);
                                   color:var(--6f-texto-2);text-transform:uppercase;font-size:0.78em;
                                   letter-spacing:0.4px;border-bottom:1px solid var(--6f-borda);
                                   width:70px">Vídeo</th>
                        <th style="padding:9px 12px;text-align:center;background:var(--6f-bg-elevado);
                                   color:var(--6f-texto-2);text-transform:uppercase;font-size:0.78em;
                                   letter-spacing:0.4px;border-bottom:1px solid var(--6f-borda);
                                   width:170px">Câmera</th>
                        <th style="padding:9px 12px;text-align:center;background:var(--6f-bg-elevado);
                                   color:var(--6f-texto-2);text-transform:uppercase;font-size:0.78em;
                                   letter-spacing:0.4px;border-bottom:1px solid var(--6f-borda);
                                   width:160px">Situação</th>
                    </tr>
                </thead>
                <tbody>
                    {linhas_tabela}
                </tbody>
            </table>
            <p style="color:var(--6f-texto-3);font-size:0.8em;margin-top:10px">
                A letra é atribuída automaticamente na ordem de cadastro e é permanente.
                Ela identifica visualmente as câmeras no set — é pista, não autoridade.
            </p>
        </div>

        <!-- Formulário de novo cadastro -->
        <div style="background:var(--6f-bg-superficie);border:1px solid var(--6f-borda);border-radius:8px;padding:20px 22px;
                    box-shadow:none">
            <h2 style="font-size:1em;font-weight:700;color:var(--6f-texto);margin-bottom:16px">
                Novo profissional
            </h2>
            {bloco_erro}
            <form action="/profissionais" method="post">
                <div style="margin-bottom:14px">
                    <label style="display:block;font-size:0.85em;font-weight:600;
                                  color:var(--6f-texto-2);margin-bottom:5px">
                        Nome <span style="color:var(--6f-erro)">★</span>
                    </label>
                    <input type="text" name="nome"
                           value="{_esc(nome_digitado)}"
                           placeholder="Ex.: JOAO"
                           autocomplete="off"
                           style="width:100%;padding:9px 12px;border:1px solid var(--6f-borda);
                                  background:var(--6f-bg-elevado);color:var(--6f-texto);
                                  border-radius:6px;font-size:0.9em;font-family:inherit">
                </div>

                <div style="margin-bottom:18px">
                    <label style="display:block;font-size:0.85em;font-weight:600;
                                  color:var(--6f-texto-2);margin-bottom:8px">
                        Tipos de material <span style="color:var(--6f-erro)">★</span>
                    </label>
                    <label style="display:flex;align-items:center;gap:8px;
                                  margin-bottom:8px;cursor:pointer;font-size:0.9em">
                        <input type="checkbox" name="tem_foto" {_checked(foto_marcada)}
                               style="width:16px;height:16px">
                        Foto
                    </label>
                    <label style="display:flex;align-items:center;gap:8px;
                                  margin-bottom:8px;cursor:pointer;font-size:0.9em">
                        <input type="checkbox" name="tem_audio" {_checked(audio_marcado)}
                               style="width:16px;height:16px">
                        Áudio
                    </label>
                    <label style="display:flex;align-items:center;gap:8px;
                                  cursor:pointer;font-size:0.9em">
                        <input type="checkbox" name="tem_video" {_checked(video_marcado)}
                               style="width:16px;height:16px">
                        Vídeo
                    </label>
                </div>

                <div style="margin-bottom:18px">
                    <label style="display:block;font-size:0.85em;font-weight:600;
                                  color:var(--6f-texto-2);margin-bottom:5px">
                        Câmera <span style="color:var(--6f-texto-3);font-weight:400">(opcional)</span>
                    </label>
                    <input type="text" name="camera"
                           value="{_esc(camera_digitada)}"
                           placeholder="Ex.: Sony"
                           autocomplete="off"
                           style="width:100%;padding:9px 12px;border:1px solid var(--6f-borda);
                                  background:var(--6f-bg-elevado);color:var(--6f-texto);
                                  border-radius:6px;font-size:0.9em;font-family:inherit">
                    <p style="color:var(--6f-texto-3);font-size:0.78em;margin-top:5px">
                        O Matcher compara esta marca com a câmera detectada no cartão.
                    </p>
                </div>

                <button type="submit"
                        style="width:100%;background:var(--6f-teal);color:var(--6f-bg-base);border:none;
                               border-radius:6px;padding:10px;font-weight:700;
                               font-size:0.9em;cursor:pointer;letter-spacing:0.3px">
                    Cadastrar
                </button>
            </form>
        </div>
    </div>"""

    return _pagina("Cadastros", "profissionais", corpo)


# ── ROTA: GESTÃO DE LISTAS DE CONTEXTO ───────────────────────────────────────
#
# A aba "Listas" permite ao operador cadastrar e gerir os valores das listas de
# classificação usadas na ficha (palcos, marcas, pautas, serviços, tags).
#
# Acesso: somente base (localhost). O portão _portao_de_acesso já bloqueia
# qualquer rota fora de /ficha e /forms quando o acesso é remoto — portanto
# /listas e /listas/* recebem 403 automaticamente para o papel câmera.
#
# Padrão espelhado do cadastro de profissionais:
#   - Listar agrupado por tipo na ordem: Palcos, Marcas, Pautas, Serviços, Tags
#   - Adicionar item (tipo + valor)
#   - Ativar/Desativar (soft-delete — preserva histórico; reversível)
#   - Excluir definitivo (só se não em uso — por ora sempre libera, pois chips
#     ainda não foram conectados à ficha; ver comentário em itens_lista_em_uso)


@app.route("/listas", methods=["GET", "POST"])
def listas():
    """
    GET  /listas → exibe os itens agrupados por tipo + formulário de novo item.
    POST /listas → cadastra um item e redireciona de volta.

    Acesso: somente base (localhost). Remoto recebe 403 pelo portão existente.
    """
    # ── POST: adicionar novo item ─────────────────────────────────────────────
    if request.method == "POST":
        tipo_raw  = (request.form.get("tipo")  or "").strip().lower()
        valor_raw = (request.form.get("valor") or "").strip()

        erro_lista = None

        if not tipo_raw:
            erro_lista = "Escolha um tipo antes de adicionar."
        elif not valor_raw:
            erro_lista = "O valor não pode ser vazio."
        elif not BANCO_DISPONIVEL:
            erro_lista = "Banco de dados indisponível. Verifique banco_dados.py."
        else:
            try:
                _conn = bd.obter_conexao()
                bd.adicionar_item_lista(_conn, tipo_raw, valor_raw)
                _conn.close()
                logger.info(
                    f"LISTAS | Adicionado: tipo={tipo_raw} valor={valor_raw}"
                )
                return redirect("/listas")
            except Exception as _err:
                import sqlite3 as _sqlite3
                if isinstance(_err, _sqlite3.IntegrityError):
                    # Unicidade (tipo, valor) violada — item já existe
                    erro_lista = (
                        f"'{valor_raw}' já existe na lista de "
                        f"{bd.ROTULOS_LISTA_CONTEXTO.get(tipo_raw, tipo_raw)}."
                    )
                else:
                    erro_lista = str(_err)
                logger.warning(f"LISTAS | Erro ao adicionar item: {_err}")

        # Houve erro → re-renderiza preservando o que foi digitado
        return _pagina_listas(
            erro=erro_lista,
            tipo_digitado=tipo_raw,
            valor_digitado=valor_raw,
        )

    # ── GET: exibir a aba de listas ───────────────────────────────────────────
    return _pagina_listas()


@app.route("/listas/<int:item_id>/ativo", methods=["POST"])
def listas_ativo(item_id):
    """
    Ativa ou desativa um item de lista (soft-delete). O campo 'ativo' do form
    indica o estado desejado: "1" = ativar, "0" = desativar. Desativar não apaga
    o item — apenas o retira das próximas seleções da ficha. Volta para a lista.

    Acesso: somente base (localhost). Remoto recebe 403 pelo portão existente.
    """
    if not BANCO_DISPONIVEL:
        return _pagina_listas(erro="Banco de dados indisponível.")

    novo_estado = (request.form.get("ativo") == "1")
    try:
        _conn = bd.obter_conexao()
        ok = bd.definir_ativo_item_lista(_conn, item_id, novo_estado)
        _conn.close()
        if ok:
            logger.info(
                f"LISTAS | id={item_id} → {'ATIVADO' if novo_estado else 'DESATIVADO'}"
            )
        else:
            logger.warning(
                f"LISTAS | id={item_id} não encontrado ao alternar 'ativo'"
            )
    except Exception as _err:
        logger.error(f"LISTAS | Erro ao alternar 'ativo' (id={item_id}): {_err}")
        return _pagina_listas(erro=f"Erro ao mudar a situação: {_err}")

    return redirect("/listas")


@app.route("/listas/<int:item_id>/excluir", methods=["POST"])
def listas_excluir(item_id):
    """
    Exclui um item de lista DEFINITIVAMENTE — só se não estiver em uso por fichas.
    Se estiver em uso, recusa e orienta a desativar.

    Hoje, como os chips ainda não foram conectados à ficha, todos os itens passam
    no check de "em uso" (itens_lista_em_uso retorna conjunto vazio). Quando a
    integração com a ficha for construída, o guard passará a funcionar de verdade.

    Acesso: somente base (localhost). Remoto recebe 403 pelo portão existente.
    """
    if not BANCO_DISPONIVEL:
        return _pagina_listas(erro="Banco de dados indisponível.")

    try:
        _conn = bd.obter_conexao()
        resultado = bd.excluir_item_lista(_conn, item_id)
        _conn.close()
    except Exception as _err:
        logger.error(f"LISTAS | Erro ao excluir (id={item_id}): {_err}")
        return _pagina_listas(erro=f"Erro ao excluir: {_err}")

    if resultado == "em_uso":
        logger.warning(
            f"LISTAS | Exclusão recusada (id={item_id}): item em uso por fichas"
        )
        return _pagina_listas(
            erro="Não dá para excluir: este item já aparece em alguma ficha. "
                 "Use Desativar (reversível) no lugar."
        )

    if resultado == "inexistente":
        logger.warning(f"LISTAS | Exclusão: id={item_id} não encontrado")
        return redirect("/listas")

    logger.info(f"LISTAS | id={item_id} EXCLUÍDO")
    return redirect("/listas")


@app.route("/listas/criar-inline", methods=["POST"])
def listas_criar_inline():
    """
    Cria um item de lista de contexto inline, direto da ficha (AJAX).

    Só acessível localmente (operador na base). O profissional de captação
    acessa a ficha remotamente e nunca vê este botão nem esta rota.

    Recebe: tipo (palco/marca/pauta/servico/tag) + valor (texto do item).
    Devolve JSON: {ok, id, valor} em sucesso ou {ok: false, erro} em falha.
    """
    # Dupla proteção: portão já bloquearia remoto, mas garantimos aqui também.
    if not _host_local():
        return jsonify({"ok": False, "erro": "Acesso restrito ao operador."}), 403

    if not BANCO_DISPONIVEL:
        return jsonify({"ok": False, "erro": "Banco indisponível."}), 503

    tipo  = (request.form.get("tipo")  or "").strip().lower()
    valor = (request.form.get("valor") or "").strip()

    if not tipo or not valor:
        return jsonify({"ok": False, "erro": "Tipo e valor são obrigatórios."}), 400

    try:
        conn = bd.obter_conexao()
        item = bd.adicionar_item_lista(conn, tipo, valor)
        conn.close()
        logger.info(f"LISTAS-INLINE | {tipo} → '{valor}' (id={item['id']})")
        return jsonify({"ok": True, "id": item["id"], "valor": item["valor"]})
    except Exception as e:
        msg = str(e)
        # Duplicata: item já existe — informa para o operador não criar de novo
        if "UNIQUE" in msg or "já existe" in msg.lower():
            # Tenta devolver o id existente para que o chip seja selecionado
            try:
                conn = bd.obter_conexao()
                row = conn.execute(
                    "SELECT id, valor FROM listas_contexto WHERE tipo=? AND valor=?",
                    (tipo, valor)
                ).fetchone()
                conn.close()
                if row:
                    return jsonify({"ok": True, "id": row["id"], "valor": row["valor"]})
            except Exception:
                pass
            return jsonify({"ok": False, "erro": f'"{valor}" já existe nesta lista.'}), 409
        logger.error(f"LISTAS-INLINE | Erro ao criar {tipo}='{valor}': {e}")
        return jsonify({"ok": False, "erro": "Erro interno ao criar item."}), 500


# ── ROTAS: GESTÃO DE GRUPOS DE CLASSIFICAÇÃO (Fatia 3) ───────────────────────
# Só operador local edita grupos (o portão de acesso já barra /grupos no remoto).

@app.route("/grupos", methods=["POST"])
def grupos_criar():
    """Cria um grupo de classificação novo (nome + múltipla/única)."""
    if not BANCO_DISPONIVEL:
        return _pagina_listas(erro="Banco de dados indisponível.")
    rotulo = (request.form.get("rotulo") or "").strip()
    multipla = (request.form.get("multipla", "1") == "1")
    modo = (request.form.get("modo") or "lista").strip()
    try:
        conn = bd.obter_conexao()
        novo = bd.criar_grupo(conn, rotulo, multipla=multipla, modo=modo)
        conn.close()
        logger.info(f"GRUPOS | criado '{rotulo}' ({novo['chave']}, modo={modo})")
    except ValueError as e:
        return _pagina_listas(erro=str(e))
    except Exception as e:
        msg = str(e)
        if "UNIQUE" in msg or "PRIMARY" in msg:
            return _pagina_listas(erro=f'Já existe um grupo parecido com "{rotulo}".')
        logger.error(f"GRUPOS | erro ao criar '{rotulo}': {e}")
        return _pagina_listas(erro="Erro ao criar o grupo.")
    return redirect("/listas")


@app.route("/grupos/<chave>/editar", methods=["POST"])
def grupos_editar(chave):
    """Renomeia o grupo e ajusta a regra única/múltipla de uma vez."""
    if not BANCO_DISPONIVEL:
        return redirect("/listas")
    rotulo = (request.form.get("rotulo") or "").strip()
    multipla = (request.form.get("multipla", "1") == "1")
    try:
        conn = bd.obter_conexao()
        if rotulo:
            res = bd.renomear_grupo(conn, chave, rotulo)
            if res == "ok":
                bd.definir_multipla_grupo(conn, chave, multipla)
        conn.close()
        if rotulo and res != "ok":
            return _pagina_listas(erro="Grupo não encontrado.")
        if not rotulo:
            return _pagina_listas(erro="O nome do grupo não pode ser vazio.")
    except Exception as e:
        logger.error(f"GRUPOS | erro ao editar {chave}: {e}")
        return _pagina_listas(erro="Erro ao editar o grupo.")
    return redirect("/listas")


@app.route("/grupos/<chave>/mover", methods=["POST"])
def grupos_mover(chave):
    """Sobe ou desce o grupo na ordem de exibição."""
    if not BANCO_DISPONIVEL:
        return redirect("/listas")
    direcao = "cima" if request.form.get("dir") == "cima" else "baixo"
    try:
        conn = bd.obter_conexao()
        bd.mover_grupo(conn, chave, direcao)
        conn.close()
    except Exception as e:
        logger.error(f"GRUPOS | erro ao mover {chave}: {e}")
    return redirect("/listas")


@app.route("/grupos/<chave>/ativo", methods=["POST"])
def grupos_ativo(chave):
    """Ativa ou desativa um grupo (soft-delete)."""
    if not BANCO_DISPONIVEL:
        return redirect("/listas")
    ativo = (request.form.get("ativo") == "1")
    try:
        conn = bd.obter_conexao()
        bd.definir_ativo_grupo(conn, chave, ativo)
        conn.close()
    except Exception as e:
        logger.error(f"GRUPOS | erro ao ativar/desativar {chave}: {e}")
    return redirect("/listas")


@app.route("/grupos/<chave>/excluir", methods=["POST"])
def grupos_excluir(chave):
    """Exclui um grupo de vez — só se não foi usado em nenhuma ficha."""
    if not BANCO_DISPONIVEL:
        return redirect("/listas")
    try:
        conn = bd.obter_conexao()
        res = bd.excluir_grupo(conn, chave)
        conn.close()
    except Exception as e:
        logger.error(f"GRUPOS | erro ao excluir {chave}: {e}")
        return _pagina_listas(erro="Erro ao excluir o grupo.")
    if res == "em_uso":
        return _pagina_listas(erro="Este grupo já foi usado em fichas — só pode ser desativado.")
    return redirect("/listas")


def _cabecalho_grupo_html(g, total, em_uso):
    """
    Cabeçalho de um grupo na aba Listas: nome editável + múltipla/única + contador
    + controles (mover, ativar/desativar, excluir). Tudo via forms POST (sem JS).
    """
    chave = _esc(g["chave"])
    rotulo = _esc(g["rotulo"])
    ativo = g["ativo"]

    sel_mult = "selected" if g["multipla"] else ""
    sel_uni = "" if g["multipla"] else "selected"
    estilo_btn = ("background:var(--6f-bg-elevado);border:1px solid var(--6f-borda);color:var(--6f-texto-2);border-radius:5px;"
                  "padding:3px 9px;font-size:0.8em;cursor:pointer;font-family:inherit")

    # Renomear + múltipla num só form
    form_editar = (
        f'<form action="/grupos/{chave}/editar" method="post" '
        f'style="display:flex;gap:6px;align-items:center;margin:0;flex:1">'
        f'<input type="text" name="rotulo" value="{rotulo}" maxlength="40" '
        f'style="font-weight:700;font-size:0.95em;border:1px solid transparent;'
        f'border-radius:5px;padding:3px 6px;font-family:inherit;color:var(--6f-texto);'
        f'background:var(--6f-bg-elevado);width:160px">'
        f'<select name="multipla" style="{estilo_btn}">'
        f'<option value="1" {sel_mult}>marca vários</option>'
        f'<option value="0" {sel_uni}>escolhe um</option>'
        f'</select>'
        f'<button type="submit" style="{estilo_btn};color:var(--6f-teal);font-weight:700">salvar</button>'
        f'</form>'
    )

    # Mover cima/baixo
    btn_mover = (
        f'<form action="/grupos/{chave}/mover" method="post" style="margin:0">'
        f'<button name="dir" value="cima" style="{estilo_btn}" title="Subir">↑</button></form>'
        f'<form action="/grupos/{chave}/mover" method="post" style="margin:0">'
        f'<button name="dir" value="baixo" style="{estilo_btn}" title="Descer">↓</button></form>'
    )

    # Ativar/Desativar
    if ativo:
        btn_ativo = (
            f'<form action="/grupos/{chave}/ativo" method="post" style="margin:0">'
            f'<button name="ativo" value="0" style="{estilo_btn};color:var(--6f-erro)">Desativar</button></form>'
        )
        selo = ""
    else:
        btn_ativo = (
            f'<form action="/grupos/{chave}/ativo" method="post" style="margin:0">'
            f'<button name="ativo" value="1" style="background:var(--6f-teal);border:1px solid var(--6f-teal);'
            f'color:var(--6f-bg-base);border-radius:5px;padding:3px 9px;font-size:0.8em;cursor:pointer;'
            f'font-family:inherit">Ativar</button></form>'
        )
        selo = ('<span style="background:var(--6f-bg-hover);color:var(--6f-texto-2);border-radius:4px;'
                'padding:1px 7px;font-size:0.72em;font-weight:600">inativo</span>')

    # Excluir — só se NÃO está em uso (s33). Em uso → dica de desativar.
    if em_uso:
        btn_excluir = ('<span style="color:var(--6f-texto-3);font-size:0.76em" '
                       'title="Já usado em fichas — só pode desativar">em uso</span>')
    else:
        btn_excluir = (
            f'<form action="/grupos/{chave}/excluir" method="post" style="margin:0" '
            f'onsubmit="return confirm(\'Excluir o grupo {rotulo} e seus itens? Não tem volta.\')">'
            f'<button type="submit" style="background:none;border:none;color:var(--6f-erro);'
            f'font-size:0.78em;cursor:pointer;text-decoration:underline;font-family:inherit;'
            f'padding:0">excluir</button></form>'
        )

    # Grupo de texto não tem itens — mostra o nº só nos de lista.
    eh_texto = g.get("modo") == "texto"
    badge = "" if eh_texto else (
        f'<span style="background:var(--6f-bg-hover);color:var(--6f-texto-2);border-radius:12px;'
        f'padding:1px 10px;font-size:0.8em;font-weight:700">{total}</span>')
    badge_modo = (
        '<span style="background:var(--6f-bg-elevado);color:var(--6f-teal-claro);border-radius:4px;'
        'padding:1px 8px;font-size:0.72em;font-weight:600">escreve na hora</span>'
        if eh_texto else "")

    return (
        '<div style="display:flex;align-items:center;gap:10px;margin-bottom:10px;flex-wrap:wrap">'
        f'{form_editar}{badge}{badge_modo}{selo}'
        '<div style="display:flex;gap:6px;align-items:center">'
        f'{btn_mover}{btn_ativo}{btn_excluir}</div>'
        '</div>'
    )


def _grupo_colapsavel_html(chave, dim, cabecalho, corpo):
    """
    Envolve um grupo da aba Listas num bloco colapsável: um botão de minimizar ao
    lado do cabeçalho e o corpo (tabela/nota) escondível. O estado minimizado é
    lembrado em localStorage (ver JS_LISTAS_COLAPSAR), então reordenar os grupos
    — que recarrega a página — mantém minimizado o que estava fechado.
    """
    return (
        f'<div class="grupo-bloco" data-chave="{_esc(chave)}" style="margin-bottom:24px{dim}">'
        '<div style="display:flex;align-items:flex-start;gap:8px">'
        '<button type="button" class="grupo-toggle" onclick="gmaToggleGrupo(this)" '
        'title="Minimizar / expandir" style="background:var(--6f-bg-elevado);border:1px solid var(--6f-borda);color:var(--6f-texto-2);'
        'border-radius:5px;cursor:pointer;font-size:0.8em;line-height:1;padding:6px 9px;'
        'margin-top:1px;font-family:inherit">▾</button>'
        f'<div style="flex:1;min-width:0">{cabecalho}</div>'
        '</div>'
        f'<div class="grupo-corpo" style="margin-top:8px">{corpo}</div>'
        '</div>'
    )


# JS da aba Listas: minimizar/expandir grupos, com estado lembrado por localStorage.
JS_LISTAS_COLAPSAR = """
<script>
(function(){
  var KEY = 'gma_listas_minimizados';
  function lerSet(){ try { return new Set(JSON.parse(localStorage.getItem(KEY) || '[]')); } catch(e){ return new Set(); } }
  function salvar(s){ try { localStorage.setItem(KEY, JSON.stringify(Array.from(s))); } catch(e){} }
  function aplicar(bloco, min){
    var corpo = bloco.querySelector('.grupo-corpo');
    var btn = bloco.querySelector('.grupo-toggle');
    if (corpo) corpo.style.display = min ? 'none' : '';
    if (btn) btn.textContent = min ? '▸' : '▾';  // ▸ / ▾
  }
  window.gmaToggleGrupo = function(btn){
    var bloco = btn.closest('.grupo-bloco'); if (!bloco) return;
    var corpo = bloco.querySelector('.grupo-corpo');
    var min = corpo.style.display !== 'none';
    aplicar(bloco, min);
    var s = lerSet(), c = bloco.getAttribute('data-chave');
    if (min) s.add(c); else s.delete(c);
    salvar(s);
  };
  window.gmaTodasGrupos = function(min){
    var s = lerSet();
    document.querySelectorAll('.grupo-bloco').forEach(function(b){
      aplicar(b, min);
      var c = b.getAttribute('data-chave');
      if (min) s.add(c); else s.delete(c);
    });
    salvar(s);
  };
  function init(){
    var s = lerSet();
    document.querySelectorAll('.grupo-bloco').forEach(function(b){
      if (s.has(b.getAttribute('data-chave'))) aplicar(b, true);
    });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
</script>"""


def _pagina_listas(erro=None, tipo_digitado="", valor_digitado=""):
    """
    Renderiza a aba de Listas de Contexto.

    Exibe os itens agrupados por tipo na ordem fixada (Palcos, Marcas, Pautas,
    Serviços, Tags), com botões de ativar/desativar e excluir em cada linha.
    À direita, um formulário para adicionar novos itens.

    Separada da lógica da rota para facilitar reuso em caso de erro no POST.
    """
    # ── Carrega todos os itens do banco ──────────────────────────────────────
    todos_itens = []
    aviso_banco = ""

    if BANCO_DISPONIVEL:
        try:
            _conn = bd.obter_conexao()
            todos_itens = bd.listar_itens_lista(_conn)
            _conn.close()
        except Exception as _err_lista:
            aviso_banco = f"Não foi possível carregar as listas: {_err_lista}"
    else:
        aviso_banco = "Banco de dados indisponível."

    # ── Carrega os GRUPOS (dinâmicos) e o que está em uso ─────────────────────
    grupos_def = []
    grupos_em_uso = set()
    if BANCO_DISPONIVEL:
        try:
            _conn = bd.obter_conexao()
            grupos_def = bd.listar_grupos(_conn)
            grupos_em_uso = {g["chave"] for g in grupos_def if bd.grupo_em_uso(_conn, g["chave"])}
            _conn.close()
        except Exception as _err_g:
            aviso_banco = aviso_banco or f"Não foi possível carregar os grupos: {_err_g}"

    # Agrupa os itens por tipo (= chave do grupo)
    itens_por_tipo = {}
    for item in todos_itens:
        itens_por_tipo.setdefault(item["tipo"], []).append(item)

    # ── Monta os blocos HTML de cada grupo (na ordem definida) ────────────────
    blocos_grupos = ""
    for g in grupos_def:
        tipo = g["chave"]
        rotulo = g["rotulo"]
        itens_do_tipo = itens_por_tipo.get(tipo, [])
        total = len(itens_do_tipo)
        cabecalho_grupo = _cabecalho_grupo_html(g, total, tipo in grupos_em_uso)

        # Grupo de TEXTO: não tem itens a cadastrar — o profissional escreve na
        # ficha. Mostra só uma nota no lugar da tabela.
        if g.get("modo") == "texto":
            dim = ";opacity:0.55" if not g["ativo"] else ""
            corpo_grupo = (
                '<p style="color:var(--6f-texto-2);font-size:0.85em;background:var(--6f-bg-superficie);border-radius:8px;'
                'border:1px solid var(--6f-borda);padding:12px 16px;box-shadow:none;margin:0">'
                'Grupo de preenchimento — o profissional escreve o valor na ficha '
                '(ex.: nome do entrevistado). Não tem itens a cadastrar aqui.</p>'
            )
            blocos_grupos += _grupo_colapsavel_html(tipo, dim, cabecalho_grupo, corpo_grupo)
            continue

        # Monta as linhas da tabela deste grupo
        if itens_do_tipo:
            linhas_tipo = ""
            for item in itens_do_tipo:
                ativo = item["ativo"]

                # Estilo da linha: "apagadinha" quando inativo
                estilo_linha = "" if ativo else "opacity:0.5"

                # Selo "inativo" e botão que alterna o estado
                if ativo:
                    selo = ""
                    botao_ativo = (
                        f'<form action="/listas/{item["id"]}/ativo" method="post" style="margin:0">'
                        '<button type="submit" name="ativo" value="0" '
                        'style="background:var(--6f-bg-elevado);border:1px solid var(--6f-borda);color:var(--6f-erro);'
                        'border-radius:5px;padding:3px 10px;font-size:0.82em;cursor:pointer;'
                        'font-family:inherit">Desativar</button>'
                        '</form>'
                    )
                else:
                    selo = ('<span style="background:var(--6f-bg-hover);color:var(--6f-texto-2);border-radius:4px;'
                            'padding:1px 7px;font-size:0.74em;font-weight:600;margin-right:6px">'
                            'inativo</span>')
                    botao_ativo = (
                        f'<form action="/listas/{item["id"]}/ativo" method="post" style="margin:0">'
                        '<button type="submit" name="ativo" value="1" '
                        'style="background:var(--6f-teal);border:1px solid var(--6f-teal);color:var(--6f-bg-base);'
                        'border-radius:5px;padding:3px 10px;font-size:0.82em;cursor:pointer;'
                        'font-family:inherit">Ativar</button>'
                        '</form>'
                    )

                # Botão excluir: disponível para todos os itens nesta fatia
                # (chips ainda não conectados à ficha → nenhum item "em uso" ainda).
                # O comentário abaixo lembra que o guard muda quando os chips entrarem.
                valor_esc = _esc(item["valor"])
                botao_excluir = (
                    f'<form action="/listas/{item["id"]}/excluir" method="post" '
                    f'style="margin:0" '
                    f'onsubmit="return confirm(\'Excluir {valor_esc} de vez? Não tem volta.\')">'
                    '<button type="submit" '
                    'style="background:none;border:none;color:var(--6f-texto-3);font-size:0.82em;'
                    'cursor:pointer;text-decoration:underline;font-family:inherit;padding:0">'
                    'excluir</button>'
                    '</form>'
                )

                linhas_tipo += f"""
                <tr style="{estilo_linha}">
                    <td style="font-weight:600">{selo}{valor_esc}</td>
                    <td style="color:var(--6f-texto-3);font-size:0.82em">{_esc(item['criado_em'][:10])}</td>
                    <td>
                        <div style="display:flex;gap:10px;align-items:center">
                            {botao_ativo}
                            {botao_excluir}
                        </div>
                    </td>
                </tr>"""
        else:
            linhas_tipo = """
                <tr>
                    <td colspan="3" style="text-align:center;color:var(--6f-texto-3);
                                           padding:14px;font-size:0.85em">
                        Nenhum item cadastrado ainda.
                    </td>
                </tr>"""

        corpo_grupo = f"""
            <table style="width:100%;border-collapse:collapse;background:var(--6f-bg-superficie);
                          border-radius:8px;overflow:hidden;border:1px solid var(--6f-borda);
                          box-shadow:none;font-size:0.88em">
                <thead>
                    <tr>
                        <th style="padding:8px 12px;text-align:left;background:var(--6f-bg-elevado);
                                   color:var(--6f-texto-2);text-transform:uppercase;font-size:0.78em;
                                   letter-spacing:0.4px;border-bottom:1px solid var(--6f-borda)">
                            Valor
                        </th>
                        <th style="padding:8px 12px;text-align:left;background:var(--6f-bg-elevado);
                                   color:var(--6f-texto-2);text-transform:uppercase;font-size:0.78em;
                                   letter-spacing:0.4px;border-bottom:1px solid var(--6f-borda);
                                   width:110px">
                            Criado em
                        </th>
                        <th style="padding:8px 12px;text-align:left;background:var(--6f-bg-elevado);
                                   color:var(--6f-texto-2);text-transform:uppercase;font-size:0.78em;
                                   letter-spacing:0.4px;border-bottom:1px solid var(--6f-borda);
                                   width:180px">
                            Ação
                        </th>
                    </tr>
                </thead>
                <tbody>
                    {linhas_tipo}
                </tbody>
            </table>"""
        dim = ";opacity:0.55" if not g['ativo'] else ""
        blocos_grupos += _grupo_colapsavel_html(tipo, dim, cabecalho_grupo, corpo_grupo)

    # ── Bloco de erro (POST com problema) ─────────────────────────────────────
    bloco_erro = ""
    if erro:
        bloco_erro = f"""
        <div style="background:var(--6f-bg-elevado);border:1px solid var(--6f-erro);color:var(--6f-erro);
                    border-radius:6px;padding:12px 16px;margin-bottom:16px;font-size:0.9em">
            <strong>Erro:</strong> {_esc(erro)}
        </div>"""

    # ── Bloco de aviso de banco ────────────────────────────────────────────────
    bloco_aviso = ""
    if aviso_banco:
        bloco_aviso = f"""
        <div style="background:var(--6f-bg-elevado);border:1px solid var(--6f-aviso);color:var(--6f-aviso);
                    border-radius:6px;padding:12px 16px;margin-bottom:16px;font-size:0.9em">
            {_esc(aviso_banco)}
        </div>"""

    # Monta as <option> do select de tipo no formulário de adição (grupos ativos
    # de LISTA — grupos de texto não recebem itens cadastrados).
    opcoes_tipo = ""
    for g in grupos_def:
        if not g["ativo"] or g.get("modo") == "texto":
            continue
        sel = " selected" if g["chave"] == tipo_digitado else ""
        opcoes_tipo += f'<option value="{_esc(g["chave"])}"{sel}>{_esc(g["rotulo"])}</option>'

    # ── Corpo da página ────────────────────────────────────────────────────────
    corpo = f"""
    <div style="display:grid;grid-template-columns:1fr 300px;gap:24px;align-items:start">

        <!-- Listas agrupadas por tipo -->
        <div>
            <p style="color:var(--6f-texto-2);font-size:0.9em;margin-bottom:20px;line-height:1.5">
                Estas listas fornecem as opções de classificação da ficha de check-in
                (palcos, marcas, pautas, serviços e tags). O profissional escolhe
                da lista — nunca digita livremente. Itens desativados preservam o
                histórico mas somem das próximas fichas.
            </p>
            <div style="display:flex;gap:8px;margin-bottom:16px">
                <button type="button" onclick="gmaTodasGrupos(true)"
                        style="background:var(--6f-bg-elevado);border:1px solid var(--6f-borda);color:var(--6f-texto-2);border-radius:5px;
                               padding:5px 11px;font-size:0.82em;cursor:pointer;font-family:inherit">
                    ▸ minimizar todas</button>
                <button type="button" onclick="gmaTodasGrupos(false)"
                        style="background:var(--6f-bg-elevado);border:1px solid var(--6f-borda);color:var(--6f-texto-2);border-radius:5px;
                               padding:5px 11px;font-size:0.82em;cursor:pointer;font-family:inherit">
                    ▾ expandir todas</button>
            </div>
            {bloco_aviso}
            {blocos_grupos}
        </div>

        <!-- Coluna de formulários (grupo + item) -->
        <div style="display:flex;flex-direction:column;gap:18px;position:sticky;top:20px">

        <!-- Formulário de novo GRUPO -->
        <div style="background:var(--6f-bg-superficie);border:1px solid var(--6f-borda);border-radius:8px;padding:20px 22px;
                    box-shadow:none">
            <h2 style="font-size:1em;font-weight:700;color:var(--6f-texto);margin-bottom:6px">
                Novo grupo
            </h2>
            <p style="color:var(--6f-texto-3);font-size:0.78em;margin-bottom:14px;line-height:1.5">
                Um grupo vira um bloco de chips na ficha e uma coluna na planilha.
            </p>
            <form action="/grupos" method="post">
                <div style="margin-bottom:12px">
                    <label style="display:block;font-size:0.85em;font-weight:600;
                                  color:var(--6f-texto-2);margin-bottom:5px">Nome do grupo
                        <span style="color:var(--6f-erro)">★</span></label>
                    <input type="text" name="rotulo" autocomplete="off"
                           placeholder="Ex.: Salas, Patrocinador, Idioma"
                           style="width:100%;padding:9px 12px;border:1px solid var(--6f-borda);
                                  background:var(--6f-bg-elevado);color:var(--6f-texto);
                                  border-radius:6px;font-size:0.9em;font-family:inherit">
                </div>
                <div style="margin-bottom:12px">
                    <label style="display:block;font-size:0.85em;font-weight:600;
                                  color:var(--6f-texto-2);margin-bottom:5px">Como preenche?</label>
                    <select name="modo"
                            style="width:100%;padding:9px 12px;border:1px solid var(--6f-borda);
                                   background:var(--6f-bg-elevado);color:var(--6f-texto);
                                   border-radius:6px;font-size:0.9em;font-family:inherit">
                        <option value="lista">Escolhe da lista (chips)</option>
                        <option value="texto">Escreve na hora (texto)</option>
                    </select>
                </div>
                <div style="margin-bottom:16px">
                    <label style="display:block;font-size:0.85em;font-weight:600;
                                  color:var(--6f-texto-2);margin-bottom:5px">Quantos por ficha</label>
                    <select name="multipla"
                            style="width:100%;padding:9px 12px;border:1px solid var(--6f-borda);
                                   background:var(--6f-bg-elevado);color:var(--6f-texto);
                                   border-radius:6px;font-size:0.9em;font-family:inherit">
                        <option value="1">Vários</option>
                        <option value="0">Um só</option>
                    </select>
                </div>
                <button type="submit"
                        style="width:100%;background:var(--6f-teal);color:var(--6f-bg-base);border:none;
                               border-radius:6px;padding:10px;font-weight:700;
                               font-size:0.9em;cursor:pointer;letter-spacing:0.3px">
                    Criar grupo
                </button>
            </form>
        </div>

        <!-- Formulário de novo item -->
        <div style="background:var(--6f-bg-superficie);border:1px solid var(--6f-borda);border-radius:8px;padding:20px 22px;
                    box-shadow:none">
            <h2 style="font-size:1em;font-weight:700;color:var(--6f-texto);margin-bottom:16px">
                Adicionar item
            </h2>
            {bloco_erro}
            <form action="/listas" method="post">
                <div style="margin-bottom:14px">
                    <label style="display:block;font-size:0.85em;font-weight:600;
                                  color:var(--6f-texto-2);margin-bottom:5px">
                        Tipo <span style="color:var(--6f-erro)">★</span>
                    </label>
                    <select name="tipo"
                            style="width:100%;padding:9px 12px;border:1px solid var(--6f-borda);
                                   background:var(--6f-bg-elevado);color:var(--6f-texto);
                                   border-radius:6px;font-size:0.9em;font-family:inherit">
                        <option value="">— escolha —</option>
                        {opcoes_tipo}
                    </select>
                </div>

                <div style="margin-bottom:18px">
                    <label style="display:block;font-size:0.85em;font-weight:600;
                                  color:var(--6f-texto-2);margin-bottom:5px">
                        Valor <span style="color:var(--6f-erro)">★</span>
                    </label>
                    <input type="text" name="valor"
                           value="{_esc(valor_digitado)}"
                           placeholder="Ex.: RedBull, Palco Principal"
                           autocomplete="off"
                           style="width:100%;padding:9px 12px;border:1px solid var(--6f-borda);
                                  background:var(--6f-bg-elevado);color:var(--6f-texto);
                                  border-radius:6px;font-size:0.9em;font-family:inherit">
                    <p style="color:var(--6f-texto-3);font-size:0.78em;margin-top:5px">
                        Aparece como opção na ficha de check-in.
                    </p>
                </div>

                <button type="submit"
                        style="width:100%;background:var(--6f-teal);color:var(--6f-bg-base);border:none;
                               border-radius:6px;padding:10px;font-weight:700;
                               font-size:0.9em;cursor:pointer;letter-spacing:0.3px">
                    Adicionar
                </button>
            </form>

            <p style="color:var(--6f-texto-3);font-size:0.78em;margin-top:18px;line-height:1.5">
                Itens desativados somem das fichas mas ficam no banco (proteção do
                histórico). Itens já usados numa ficha não podem ser excluídos de
                vez — só desativados.
            </p>
        </div>

        </div><!-- fim da coluna de formulários -->
    </div>"""

    return _pagina("Programação", "listas", corpo, JS_LISTAS_COLAPSAR)


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


# ══════════════════════════════════════════════════════════════════════════════
#  PAINEL DE CONTROLE (Camada 5 — Fatia 1)
#  Cockpit do operador: projeto ativo, troca de projeto (com reinício guiado),
#  criação de projeto, conexões com teste ("ligar os motores") e controle do
#  sistema (reiniciar/encerrar). Tudo SÓ na base (localhost) — o portão por papel
#  já barra qualquer acesso remoto a estas rotas (403).
# ══════════════════════════════════════════════════════════════════════════════

PAINEL_CSS = """
.painel-secao { background:var(--6f-bg-superficie); border-radius:10px;
                border:1px solid var(--6f-borda); box-shadow:none;
                padding:18px 20px; margin-bottom:18px; }
.painel-secao h2 { font-size:1.05em; margin-bottom:4px; color:var(--6f-texto); }
.painel-secao .sub { color:var(--6f-texto-2); font-size:0.85em; margin-bottom:14px; line-height:1.5; }
.projeto-ativo { display:flex; align-items:baseline; gap:12px; flex-wrap:wrap; }
.projeto-ativo .nome { font-size:1.4em; font-weight:700; color:var(--6f-teal); }
.projeto-ativo .db { font-family:ui-monospace,Menlo,monospace; font-size:0.85em; color:var(--6f-texto-2); }
.proj-lista { display:flex; flex-direction:column; gap:8px; }
.proj-item { display:flex; align-items:center; justify-content:space-between; gap:12px;
             padding:10px 12px; border:1px solid var(--6f-borda); border-radius:8px; }
.proj-item.ativo { border-color:var(--6f-teal); background:var(--6f-teal-trilho); }
.proj-item .info b { font-size:0.98em; }
.proj-item .info .cam { font-family:ui-monospace,Menlo,monospace; font-size:0.8em; color:var(--6f-texto-3); }
.tag-ativo { background:var(--6f-teal); color:var(--6f-bg-base); border-radius:10px; padding:2px 10px; font-size:0.74em; font-weight:700; }
.conexoes { display:grid; grid-template-columns:repeat(auto-fill,minmax(300px,1fr)); gap:12px; }
.conexao { border:1px solid var(--6f-borda); border-radius:8px; padding:12px 14px; }
.conexao .top { display:flex; align-items:center; gap:8px; margin-bottom:4px; }
.dot { width:10px; height:10px; border-radius:50%; flex:none; }
.dot.ok { background:var(--6f-ok); } .dot.aviso { background:var(--6f-aviso); }
.dot.off { background:var(--6f-texto-3); } .dot.erro { background:var(--6f-erro); }
.conexao .rot { font-weight:700; font-size:0.95em; }
.conexao .val { font-family:ui-monospace,Menlo,monospace; font-size:0.82em; color:var(--6f-texto-2);
                word-break:break-all; margin:2px 0 8px; }
.conexao .desc { color:var(--6f-texto-3); font-size:0.8em; margin-bottom:8px; line-height:1.4; }
.btn { border:none; border-radius:6px; padding:6px 14px; font-weight:600; font-size:0.82em;
       cursor:pointer; font-family:inherit; }
.btn-testar { background:var(--6f-bg-elevado); color:var(--6f-teal-claro); }
.btn-trocar { background:var(--6f-teal); color:var(--6f-bg-base); }
.btn-secund { background:var(--6f-bg-elevado); color:var(--6f-texto-2); }
.btn-perigo { background:var(--6f-erro); color:var(--6f-bg-base); }
.btn:disabled { opacity:0.5; cursor:default; }
.linha-form { display:flex; gap:8px; flex-wrap:wrap; align-items:center; margin-top:6px; }
.linha-form input[type=text] { flex:1; min-width:180px; padding:7px 10px; border:1px solid var(--6f-borda);
                               background:var(--6f-bg-elevado); color:var(--6f-texto);
                               border-radius:6px; font-size:0.85em; font-family:inherit; }
.linha-form input[type=text]::placeholder { color:var(--6f-texto-3); }
.aviso-painel { padding:10px 14px; border-radius:8px; margin-bottom:16px; font-size:0.9em; }
.aviso-painel.ok { background:var(--6f-teal-trilho); border:1px solid var(--6f-teal); color:var(--6f-texto); }
.aviso-painel.erro { background:var(--6f-bg-elevado); border:1px solid var(--6f-erro); color:var(--6f-erro); }
.resultado-teste { background:var(--6f-bg-elevado); border:1px solid var(--6f-borda); border-radius:6px;
                   color:var(--6f-texto-2); padding:7px 10px; font-size:0.82em; margin-top:6px; }
.controle-sistema { display:flex; gap:10px; flex-wrap:wrap; }
.nota-command { color:var(--6f-texto-3); font-size:0.82em; margin-top:12px; line-height:1.5; }
.conexao-botoes { display:flex; gap:6px; flex-wrap:wrap; margin-bottom:6px; }
.conexao.inativo { opacity:0.65; }
.ajuda-sheets { background:var(--6f-teal-trilho); border:1px solid var(--6f-borda); border-radius:6px;
                padding:8px 10px; margin-bottom:8px; }
.ajuda-passos { font-size:0.78em; color:var(--6f-texto-2); margin-bottom:6px; line-height:1.4; }
.ajuda-sa { display:flex; align-items:center; gap:6px; }
.ajuda-sa code { flex:1; background:var(--6f-bg-elevado); border:1px solid var(--6f-borda); border-radius:5px;
                 padding:5px 8px; font-size:0.76em; color:var(--6f-texto); word-break:break-all; }
.btn-copiar { background:var(--6f-teal); color:var(--6f-bg-base); border:none; border-radius:5px;
              padding:5px 10px; font-size:0.76em; cursor:pointer; white-space:nowrap; }
.btn-copiar:hover { background:var(--6f-teal-forte); }
"""


def _painel_raiz():
    return RAIZ_GMA


def _painel_criar_sinal(nome):
    """Cria um arquivo-sinal que o saguão (saguao.py) observa — hoje só .gma_encerrar."""
    caminho = os.path.join(_painel_raiz(), nome)
    with open(caminho, "w", encoding="utf-8") as f:
        f.write(datetime.now().isoformat())


def _saguao_rodando():
    """True se o saguao.py (o térreo, nível 1) está no ar — quem comanda hoje."""
    try:
        r = subprocess.run(["pgrep", "-f", "saguao.py"],
                           capture_output=True, text=True, timeout=5)
        return r.returncode == 0 and r.stdout.strip() != ""
    except Exception:
        return False


# (_inicializar_banco_projeto saiu junto com a rota /painel/novo: criar projeto
#  — e preparar o banco dele — agora é só no saguão, em criar_projeto_novo.)


def _testar_conexao(chave):
    """Roda o teste de uma conexão. Retorna (ok: bool, mensagem: str)."""
    if chave == "destino":
        _slug, cfg = painel_config.projeto_ativo()
        caminho = cfg.get("destino") or painel_config.DESTINO_PADRAO
        if not os.path.isdir(caminho):
            return False, f"A pasta não existe: {caminho}"
        try:
            teste = os.path.join(caminho, ".gma_teste_escrita")
            with open(teste, "w") as f:
                f.write("ok")
            os.remove(teste)
            return True, f"Pasta acessível e gravável."
        except OSError as e:
            return False, f"A pasta existe mas não dá para gravar: {e}"

    if chave == "banco":
        _slug, cfg = painel_config.projeto_ativo()
        db = painel_config.caminho_db(cfg)
        if not os.path.isfile(db):
            return False, f"O banco ainda não existe: {db}"
        try:
            import sqlite3
            c = sqlite3.connect(db)
            c.execute("SELECT 1")
            c.close()
            return True, "O banco abre normalmente."
        except Exception as e:
            return False, f"O banco não abre: {e}"

    if chave == "sheets":
        sid = os.environ.get("GMA_SHEETS_ID", "").strip()
        sa = os.environ.get("GMA_SHEETS_SA", "").strip()
        if not sid:
            return False, "GMA_SHEETS_ID não está configurado (.env)."
        if not sa:
            return False, "GMA_SHEETS_SA (conta de serviço) não está configurado (.env)."
        try:
            r = subprocess.run(
                ["gcloud", "auth", "print-access-token", f"--impersonate-service-account={sa}"],
                capture_output=True, text=True, timeout=30)
            if r.returncode == 0 and r.stdout.strip():
                return True, "Autenticação OK — token gerado para a planilha."
            return False, "Falha ao gerar token. Talvez precise refazer o 'gcloud auth login'."
        except FileNotFoundError:
            return False, "gcloud não encontrado no PATH."
        except subprocess.TimeoutExpired:
            return False, "Tempo esgotado ao falar com o gcloud."

    if chave == "recebidos":
        _slug, cfg = painel_config.projeto_ativo()
        caminho = painel_config.caminho_recebidos(cfg)
        return painel_config.checar_recebidos(caminho)

    if chave == "tunel":
        try:
            import urllib.request
            with urllib.request.urlopen("http://127.0.0.1:4040/api/tunnels", timeout=3) as resp:
                dados = json.loads(resp.read().decode())
            for t in dados.get("tunnels", []):
                url = t.get("public_url", "")
                if url.startswith("https"):
                    return True, f"Túnel ativo: {url}"
            return False, "O ngrok responde, mas não há túnel HTTPS ativo."
        except Exception:
            return False, "O ngrok não está rodando (rode ./ngrok_gma.sh em outro terminal)."

    return False, "Conexão desconhecida."


def _ajuda_sheets_html():
    """Caixa de ajuda do Google Sheets: a conta de serviço pronta para copiar.

    O operador precisa COMPARTILHAR a planilha nova (como Editor) com esta conta —
    senão o exportador não consegue escrever. Deixar o e-mail copiável aqui, ao lado
    da caixinha, evita ter de procurá-lo em outro lugar (pedido do idealizador).
    """
    sa = (os.environ.get("GMA_SHEETS_SA", "") or "").strip()
    if not sa:
        return ""
    sa_esc = _esc(sa)
    return (
        "<div class='ajuda-sheets'>"
        "<div class='ajuda-passos'>Planilha NOVA por projeto → "
        "<b>Compartilhar</b> como <b>Editor</b> com esta conta → cole o link aqui:</div>"
        "<div class='ajuda-sa'>"
        f"<code id='sa-email'>{sa_esc}</code>"
        f"<button type='button' class='btn btn-copiar' "
        f"onclick=\"navigator.clipboard.writeText('{sa_esc}').then(function(){{"
        "var b=event.target;var t=b.textContent;b.textContent='copiado ✓';"
        "setTimeout(function(){b.textContent=t;},1500);})\">copiar</button>"
        "</div></div>"
    )


def _status_sheets_bilhete(slug_ativo):
    """
    Lê o "bilhete de status" que o exportador (Camada 3) grava a cada ciclo
    (.gma_sheets_status.json) e traduz em (bolinha, nota) para a caixa do Google
    Sheets no Painel. Assim uma falha (ex.: login do gcloud expirado) aparece na
    tela em vez de ficar escondida no log — o problema que travou o Sheet em
    silêncio na s43.

    Retorna (dot, nota) ou None se não houver bilhete confiável (sem arquivo,
    velho demais, ou de OUTRO projeto — o exportador roda um projeto por vez).
    """
    caminho = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           ".gma_sheets_status.json")
    try:
        with open(caminho, "r", encoding="utf-8") as f:
            b = json.load(f)
    except Exception:
        return None

    # Bilhete de outro projeto não vale para este Painel.
    if (b.get("projeto") or "") and slug_ativo and b.get("projeto") != slug_ativo:
        return None

    # Bilhete velho (exportador parado/derrubado) não é confiável — o ciclo é de
    # 60s; depois de ~5min sem novo bilhete, melhor não afirmar nada.
    try:
        from datetime import datetime as _dt
        idade = (_dt.now() - _dt.fromisoformat(b.get("quando"))).total_seconds()
        if idade > 300:
            return None
    except Exception:
        pass

    estado = b.get("estado", "")
    hora = b.get("horario", "")
    msg = (b.get("mensagem") or "").strip()
    mapa = {
        "ok":             ("ok",    f"🟢 atualizado às {hora}"),
        "login-vencido":  ("erro",  "🔴 Google precisa de login — rode no Terminal: gcloud auth login"),
        "sem-internet":   ("aviso", "🟡 sem internet — sincronização adiada"),
        "pausado":        ("aviso", "⏸ " + (msg or "sincronização pausada")),
        "nao-configurado":("aviso", msg or "exportador sem credenciais"),
        "erro":           ("erro",  "🔴 falha na sincronização" + (f": {msg}" if msg else "")),
    }
    return mapa.get(estado)


def _conexoes_cockpit():
    """Monta a lista de conexões do projeto ativo para o cockpit."""
    _slug, cfg = painel_config.projeto_ativo()
    db = painel_config.caminho_db(cfg)
    destino = cfg.get("destino") or painel_config.DESTINO_PADRAO
    estado = painel_config.carregar_estado()

    def sit(valor):
        return ("definida", "ok") if (valor or "").strip() else ("— (vazia)", "off")

    # Google Sheets — ID por projeto (painel_estado) ou fallback no .env
    sid = (cfg.get("sheets_id") or os.environ.get("GMA_SHEETS_ID", "")).strip()
    sheets_ativo = cfg.get("sheets_ativo", True)
    sheets_txt = ("…" + sid[-8:]) if sid else "— (não configurado)"
    sheets_nota = ""  # estado VIVO do exportador (bolinha 🟢/🔴/🟡), quando houver
    if not sheets_ativo:
        sheets_status = "off"
    elif sid:
        sheets_status = "ok"
    else:
        sheets_status = "aviso"
    # Sobrepõe com o que o exportador realmente reportou no último ciclo (s46):
    # login vencido → 🔴, sem internet → 🟡, ok → 🟢 "atualizado HH:MM".
    if sheets_ativo:
        bilhete = _status_sheets_bilhete(_slug)
        if bilhete:
            sheets_status, sheets_nota = bilhete

    # Túnel — link override por projeto (painel_estado) ou fallback no .env
    tunel_link = (cfg.get("tunel_link") or os.environ.get("GMA_LINK_FICHA", "")).strip()
    tunel_ativo = cfg.get("tunel_ativo", True)
    tunel_url_real = tunel_link
    if not tunel_link and tunel_ativo:
        # Verifica ngrok ao vivo (timeout curto para não travar o carregamento)
        try:
            import urllib.request as _ur
            with _ur.urlopen("http://127.0.0.1:4040/api/tunnels", timeout=2) as resp:
                dados = json.loads(resp.read().decode())
            for t in dados.get("tunnels", []):
                url = t.get("public_url", "")
                if url.startswith("https"):
                    tunel_url_real = url + "/ficha"
                    break
        except Exception:
            pass
    if not tunel_ativo:
        tunel_status, tunel_txt = "off", "desativado"
    elif tunel_url_real:
        tunel_status, tunel_txt = "ok", tunel_url_real
    else:
        tunel_status, tunel_txt = "aviso", "ngrok não encontrado — suba o túnel"

    # Porta / host — estado global ou fallback no .env
    host = (estado.get("host") or os.environ.get("GMA_HOST", "127.0.0.1")).strip() or "127.0.0.1"
    porta = (estado.get("porta") or os.environ.get("GMA_PORT", "5050")).strip() or "5050"
    host_rede = host not in ("127.0.0.1", "localhost")

    senha_txt, senha_st = sit(os.environ.get("GMA_SENHA"))

    # Pasta de recebidos (satélite) — material que NÃO vem por cartão físico.
    recebidos_dir = painel_config.caminho_recebidos(cfg)
    recebidos_override = (cfg.get("recebidos") or "").strip()
    recebidos_txt = recebidos_dir if recebidos_override else f"{recebidos_dir}  (padrão)"
    recebidos_status = "ok" if os.path.isdir(recebidos_dir) else "aviso"

    return [
        {"chave": "banco", "rot": "Banco do projeto", "val": db,
         "desc": "Onde ficam os dados deste projeto (fichas, cartões, planilha).",
         "status": "ok" if os.path.isfile(db) else "aviso", "testavel": True,
         "direcionar": True, "campo": db, "acao": "/painel/banco",
         "placeholder": "Caminho do banco (ex.: projetos/meu_evento/gma.db)"},
        {"chave": "destino", "rot": "Pasta dos materiais", "val": destino,
         "desc": "Para onde o material é copiado e organizado (EVENTO/DATA/TIPO/NOME).",
         "status": "ok" if os.path.isdir(destino) else "aviso", "testavel": True,
         "direcionar": True, "campo": destino, "acao": "/painel/destino",
         "placeholder": "Caminho da pasta de destino"},
        {"chave": "recebidos", "rot": "Pasta de recebidos", "val": recebidos_txt,
         "desc": "Entrada do material que NÃO vem por cartão (entregue por link/Drive/Dropbox). "
                 "Cada Post de origem satélite ganha uma subpasta aqui.",
         "status": recebidos_status, "testavel": True,
         "direcionar": True, "campo": recebidos_override, "acao": "/painel/recebidos",
         "placeholder": "Pasta sincronizada (ex.: ~/Library/CloudStorage/...) — vazio = padrão do projeto"},
        {"chave": "sheets", "rot": "Google Sheets", "val": sheets_txt,
         "desc": "Espelho de entrega na nuvem. ID salvo por projeto."
                 + (f"  ·  {sheets_nota}" if sheets_nota else ""),
         "status": sheets_status, "testavel": bool(sid),
         "direcionar": True, "campo": sid, "acao": "/painel/sheets-id",
         "placeholder": "Cole o link (ou o ID) da planilha Google deste projeto",
         "ajuda_html": _ajuda_sheets_html(),
         "ativavel": True, "ativo": sheets_ativo, "acao_ativar": "/painel/sheets-ativo"},
        {"chave": "tunel", "rot": "Túnel / ficha remota", "val": tunel_txt,
         "desc": "Link público da ficha (ngrok). Vazio = detecta automaticamente.",
         "status": tunel_status, "testavel": True,
         "direcionar": True, "campo": tunel_link, "acao": "/painel/tunel-link",
         "placeholder": "Link override (ex.: https://xyz.ngrok.io) — vazio = auto",
         "ativavel": True, "ativo": tunel_ativo, "acao_ativar": "/painel/tunel-ativo"},
        {"chave": "senha", "rot": "Senha das telas", "val": senha_txt,
         "desc": "Portão para a internet. Vazia = uso local livre.",
         "status": senha_st, "testavel": False},
        {"chave": "porta", "rot": "Porta / host", "val": f"{host}:{porta}",
         "desc": "Onde o painel escuta. 0.0.0.0 = libera para a rede local (celulares no Wi-Fi).",
         "status": "ok", "testavel": False,
         "direcionar_host": True, "campo_host": host, "campo_porta": porta,
         "acao": "/painel/host",
         "ativavel": True, "ativo": host_rede,
         "acao_ativar": "/painel/host-rede",
         "label_ativar": "Liberar rede local", "label_desativar": "Só local"},
    ]


def _pagina_painel(aviso=None, erro=None, resultado_teste=None):
    """Renderiza o cockpit do Painel de Controle."""
    if not PAINEL_DISPONIVEL:
        return _pagina("Sistema", "painel",
                       "<div class='painel-secao'>Painel indisponível (painel_config.py não carregou).</div>",
                       head_extra=f"<style>{PAINEL_CSS}</style>")

    estado = painel_config.carregar_estado()
    ativo_slug = estado["projeto_ativo"]
    ativo_cfg = estado["projetos"][ativo_slug]
    porta_saguao = os.environ.get("GMA_PORTA_SAGUAO", "5055")

    partes = []

    # ── Avisos / resultado de teste ──────────────────────────────────────────
    if aviso:
        partes.append(f"<div class='aviso-painel ok'>{_esc(aviso)}</div>")
    if erro:
        partes.append(f"<div class='aviso-painel erro'>{_esc(erro)}</div>")

    # ── Voltar ao saguão (térreo do sistema) ─────────────────────────────────
    # Trocar de projeto agora se faz pelo SAGUÃO: ele desce só esta sessão e
    # mostra a lista de projetos, sem reiniciar o sistema. O saguão fica sempre
    # de pé na porta dele (5055), separado deste Flask do projeto.
    partes.append(
        "<div class='painel-secao' style='display:flex;align-items:center;"
        "justify-content:space-between;gap:14px;flex-wrap:wrap'>"
        "<div><b>Você está dentro de um projeto.</b>"
        "<div class='sub'>Para trocar de projeto, volte ao saguão — o sistema não "
        "reinicia, só desce esta sessão.</div></div>"
        f"<a class='btn btn-secund' href='http://127.0.0.1:{_esc(porta_saguao)}/'>"
        "⬅ Voltar ao saguão</a>"
        "</div>"
    )

    # ── Operador logado (login da Camada 5) ──────────────────────────────────
    _logado = _operador_logado()
    if _logado:
        partes.append(
            "<div class='painel-secao' style='display:flex;align-items:center;"
            "justify-content:space-between;gap:14px;flex-wrap:wrap'>"
            f"<div>Operando como <b>{_esc(_logado)}</b></div>"
            "<div style='display:flex;gap:10px'>"
            "<a class='btn btn-secund' href='/historico'>Histórico</a>"
            "<a class='btn btn-secund' href='/operadores'>Operadores</a>"
            "<a class='btn btn-secund' href='/logout'>Sair</a>"
            "</div></div>"
        )

    # ── Projeto ativo ────────────────────────────────────────────────────────
    partes.append(
        "<div class='painel-secao'><h2>Projeto ativo</h2>"
        "<div class='projeto-ativo'>"
        f"<span class='nome'>{_esc(ativo_cfg.get('nome', ativo_slug))}</span>"
        f"<span class='db'>{_esc(painel_config.caminho_db(ativo_cfg))}</span>"
        "</div></div>"
    )

    # ── (Lista de projetos saiu daqui) ───────────────────────────────────────
    # Listar/trocar/criar projeto agora é só no SAGUÃO (o térreo): lá ficam a
    # lista, o "Entrar" e o "Criar projeto". Tê-los também aqui era duplicação —
    # a caixa "Projeto ativo" acima já basta para saber onde você está. Para
    # mexer em projetos, use "⬅ Voltar ao saguão" no topo.

    # ── Conexões (cockpit) ───────────────────────────────────────────────────
    cards = []
    for c in _conexoes_cockpit():
        chave = c["chave"]
        c_status = c["status"]
        c_rot = _esc(c["rot"])
        c_val = _esc(c["val"])
        c_desc = _esc(c["desc"])
        c_ativo = c.get("ativo", True)

        res_html = ""
        if resultado_teste and resultado_teste[0] == chave:
            _ch, ok, msg = resultado_teste
            icone = "✅" if ok else "⚠️"
            res_html = f"<div class='resultado-teste'>{icone} {_esc(msg)}</div>"

        # Botão Testar
        botao_testar = ""
        if c.get("testavel") and c_ativo:
            botao_testar = (
                "<form method='POST' action='/painel/testar/" + chave + "' style='margin:0'>"
                "<button class='btn btn-testar' type='submit'>Testar</button></form>"
            )

        # Botão Ativar / Desativar
        ativar_form = ""
        if c.get("ativavel"):
            acao_ativar = c.get("acao_ativar", "")
            if c_ativo:
                label = c.get("label_desativar", "Desativar")
                ativar_form = (
                    f"<form method='POST' action='{acao_ativar}' style='margin:0'>"
                    f"<input type='hidden' name='slug' value='{_esc(ativo_slug)}'>"
                    "<input type='hidden' name='ativo' value='0'>"
                    f"<button class='btn btn-secund' type='submit'>{label}</button></form>"
                )
            else:
                label = c.get("label_ativar", "Ativar")
                ativar_form = (
                    f"<form method='POST' action='{acao_ativar}' style='margin:0'>"
                    f"<input type='hidden' name='slug' value='{_esc(ativo_slug)}'>"
                    "<input type='hidden' name='ativo' value='1'>"
                    f"<button class='btn btn-trocar' type='submit'>{label}</button></form>"
                )

        botoes = ""
        if botao_testar or ativar_form:
            botoes = f"<div class='conexao-botoes'>{botao_testar}{ativar_form}</div>"

        # Formulário de redirecionamento
        redir_form = ""
        if c.get("direcionar"):
            ph = _esc(c.get("placeholder", "Caminho ou endereço"))
            val_campo = _esc(c.get("campo", ""))
            acao = c.get("acao", "")
            redir_form = (
                f"<form method='POST' action='{acao}' class='linha-form'>"
                f"<input type='hidden' name='slug' value='{_esc(ativo_slug)}'>"
                f"<input type='text' name='valor' value='{val_campo}' placeholder='{ph}'>"
                "<button class='btn btn-secund' type='submit'>Redirecionar</button></form>"
            )
        elif c.get("direcionar_host"):
            acao = c.get("acao", "")
            val_host = _esc(c.get("campo_host", ""))
            val_porta = _esc(c.get("campo_porta", ""))
            redir_form = (
                f"<form method='POST' action='{acao}' class='linha-form'>"
                f"<input type='hidden' name='slug' value='{_esc(ativo_slug)}'>"
                f"<input type='text' name='host' value='{val_host}' "
                "placeholder='host' style='max-width:140px'>"
                f"<input type='text' name='porta' value='{val_porta}' "
                "placeholder='porta' style='max-width:72px'>"
                "<button class='btn btn-secund' type='submit'>Aplicar</button></form>"
            )

        # "inativo" só para conexões com ativável real (sheets, túnel), não para host
        inativo_cls = " inativo" if (c.get("ativavel") and not c_ativo and "acao_ativar" in c and c["chave"] != "porta") else ""
        cards.append(
            f"<div class='conexao{inativo_cls}'>"
            f"<div class='top'><span class='dot {c_status}'></span>"
            f"<span class='rot'>{c_rot}</span></div>"
            f"<div class='val'>{c_val}</div>"
            f"<div class='desc'>{c_desc}</div>"
            f"{c.get('ajuda_html', '')}"
            f"{botoes}{redir_form}{res_html}"
            "</div>"
        )
    partes.append(
        "<div class='painel-secao'><h2>Conexões (cockpit)</h2>"
        "<div class='sub'>Os \"motores\" deste projeto. Use <b>Testar</b> para ligar e conferir cada um "
        "antes de começar a logar. Mudanças de pasta só valem após reiniciar.</div>"
        f"<div class='conexoes'>{''.join(cards)}</div></div>"
    )

    # ── Controle do sistema ──────────────────────────────────────────────────
    # No modelo de 2 níveis, quem comanda é o SAGUÃO (saguao.py). Encerrar daqui
    # encerra o saguão, que desce esta sessão sozinho. Trocar de projeto é pelo
    # "⬅ Voltar ao saguão" (lá em cima) — por isso não há mais "Reiniciar" aqui.
    sob_saguao = _saguao_rodando()
    estado_sis = (
        "<span class='dot ok'></span> O GMA está sob o saguão (o térreo, na porta "
        f"{_esc(porta_saguao)}). Encerrar por aqui desliga tudo."
        if sob_saguao else
        "<span class='dot aviso'></span> O saguão não está no ar — para ligar o sistema, "
        "use o atalho <b>Iniciar GMA</b> na pasta do projeto."
    )
    partes.append(
        "<div class='painel-secao'><h2>Controle do sistema</h2>"
        f"<div class='sub'>{estado_sis}</div>"
        "<div class='controle-sistema'>"
        f"<a class='btn btn-secund' href='http://127.0.0.1:{_esc(porta_saguao)}/'>⬅ Voltar ao saguão</a>"
        "<form method='POST' action='/painel/encerrar' style='margin:0' "
        "onsubmit=\"return confirm('Desligar todo o GMA agora?');\">"
        "<button class='btn btn-perigo' type='submit'>⏻ Desligar o GMA</button></form>"
        "</div>"
        "<div class='nota-command'>Para <b>ligar</b> o sistema sem depender do terminal, dê dois cliques em "
        "<b>“Iniciar GMA.command”</b> dentro da pasta GMA. Para <b>desligar</b>, use o botão acima ou "
        "<b>“Encerrar GMA.command”</b>.</div>"
        "</div>"
    )

    return _pagina("Sistema", "painel", "".join(partes),
                   head_extra=f"<style>{PAINEL_CSS}</style>")


@app.route("/painel", methods=["GET"])
def painel_cockpit():
    """Cockpit do operador (só base). Remoto recebe 403 pelo portão existente."""
    return _pagina_painel()


# (A rota /painel/novo saiu: criar projeto agora é só no saguão, via /criar.
#  A caixa "Projetos" do Painel — único lugar que postava aqui — foi removida.)


@app.route("/painel/destino", methods=["POST"])
def painel_destino():
    """Direciona a pasta dos materiais do projeto ativo."""
    slug = (request.form.get("slug") or "").strip()
    # Aceita tanto 'valor' (novo padrão) quanto 'destino' (retrocompat)
    caminho = (request.form.get("valor") or request.form.get("destino") or "").strip()
    try:
        painel_config.definir_destino(slug, caminho)
        logger.info(f"PAINEL | Destino de '{slug}' → {caminho}")
        return _pagina_painel(aviso="Pasta de destino atualizada. Reinicie o sistema para aplicar.")
    except Exception as e:
        logger.warning(f"PAINEL | Falha ao direcionar destino: {e}")
        return _pagina_painel(erro=f"Não deu para direcionar a pasta: {e}")


@app.route("/painel/recebidos", methods=["POST"])
def painel_recebidos():
    """Direciona a pasta-raiz de recebidos (material que não vem por cartão)."""
    slug = (request.form.get("slug") or "").strip()
    caminho = (request.form.get("valor") or "").strip()
    try:
        painel_config.definir_recebidos(slug, caminho)
        logger.info(f"PAINEL | Recebidos de '{slug}' → {caminho or '(padrão)'}")
        msg = ("Pasta de recebidos atualizada. Reinicie o sistema para aplicar."
               if caminho else
               "Override removido — usando a pasta padrão do projeto. Reinicie para aplicar.")
        return _pagina_painel(aviso=msg)
    except Exception as e:
        logger.warning(f"PAINEL | Falha ao direcionar recebidos: {e}")
        return _pagina_painel(erro=f"Não deu para direcionar a pasta de recebidos: {e}")


@app.route("/painel/banco", methods=["POST"])
def painel_banco():
    """Redireciona o caminho do banco do projeto ativo."""
    slug = (request.form.get("slug") or "").strip()
    valor = (request.form.get("valor") or "").strip()
    try:
        painel_config.definir_banco(slug, valor)
        logger.info(f"PAINEL | Banco de '{slug}' → {valor}")
        return _pagina_painel(aviso="Caminho do banco atualizado. Reinicie o sistema para aplicar.")
    except Exception as e:
        logger.warning(f"PAINEL | Falha ao redirecionar banco: {e}")
        return _pagina_painel(erro=f"Não deu para atualizar o banco: {e}")


@app.route("/painel/sheets-id", methods=["POST"])
def painel_sheets_id():
    """Define o ID da planilha Google do projeto ativo."""
    slug = (request.form.get("slug") or "").strip()
    valor = (request.form.get("valor") or "").strip()
    try:
        painel_config.definir_sheets(slug, valor)
        logger.info(f"PAINEL | Sheets ID de '{slug}' atualizado")
        return _pagina_painel(aviso="ID da planilha atualizado. Reinicie para aplicar ao exportador.")
    except Exception as e:
        logger.warning(f"PAINEL | Falha ao atualizar Sheets ID: {e}")
        return _pagina_painel(erro=f"Não deu para atualizar o Sheets: {e}")


@app.route("/painel/sheets-ativo", methods=["POST"])
def painel_sheets_ativo():
    """Ativa ou desativa a sincronização com o Google Sheets."""
    slug = (request.form.get("slug") or "").strip()
    ativo = request.form.get("ativo", "1") == "1"
    try:
        painel_config.definir_sheets_ativo(slug, ativo)
        msg = "Google Sheets ativado." if ativo else "Google Sheets desativado (exportador pausado)."
        logger.info(f"PAINEL | Sheets de '{slug}' → {'ativo' if ativo else 'inativo'}")
        return _pagina_painel(aviso=msg)
    except Exception as e:
        logger.warning(f"PAINEL | Falha ao mudar estado Sheets: {e}")
        return _pagina_painel(erro=f"Não deu para mudar o estado do Sheets: {e}")


@app.route("/painel/tunel-link", methods=["POST"])
def painel_tunel_link():
    """Define o link override do túnel do projeto ativo."""
    slug = (request.form.get("slug") or "").strip()
    valor = (request.form.get("valor") or "").strip()
    try:
        painel_config.definir_tunel_link(slug, valor)
        logger.info(f"PAINEL | Link do túnel de '{slug}' → {valor or '(auto)'}")
        msg = (f"Link do túnel configurado." if valor
               else "Link removido — o painel vai detectar o ngrok automaticamente.")
        return _pagina_painel(aviso=msg)
    except Exception as e:
        logger.warning(f"PAINEL | Falha ao atualizar link do túnel: {e}")
        return _pagina_painel(erro=f"Não deu para atualizar o túnel: {e}")


@app.route("/painel/tunel-ativo", methods=["POST"])
def painel_tunel_ativo():
    """Ativa ou desativa o acesso remoto (ficha via túnel)."""
    slug = (request.form.get("slug") or "").strip()
    ativo = request.form.get("ativo", "1") == "1"
    try:
        painel_config.definir_tunel_ativo(slug, ativo)
        msg = ("Ficha remota ativada — o QR voltará a aparecer." if ativo
               else "Ficha remota desativada — só operador local acessa agora.")
        logger.info(f"PAINEL | Túnel de '{slug}' → {'ativo' if ativo else 'inativo'}")
        return _pagina_painel(aviso=msg)
    except Exception as e:
        logger.warning(f"PAINEL | Falha ao mudar estado do túnel: {e}")
        return _pagina_painel(erro=f"Não deu para mudar o estado do túnel: {e}")


@app.route("/painel/host", methods=["POST"])
def painel_host():
    """Define o host e porta do Flask (aplica no próximo reinício)."""
    host = (request.form.get("host") or "127.0.0.1").strip()
    porta = (request.form.get("porta") or "5050").strip()
    try:
        painel_config.definir_host_porta(host, porta)
        logger.info(f"PAINEL | Host/porta → {host}:{porta}")
        return _pagina_painel(aviso=f"Host configurado para {host}:{porta}. Reinicie o sistema para aplicar.")
    except Exception as e:
        logger.warning(f"PAINEL | Falha ao atualizar host/porta: {e}")
        return _pagina_painel(erro=f"Não deu para atualizar o host: {e}")


@app.route("/painel/host-rede", methods=["POST"])
def painel_host_rede():
    """Toggle rápido: libera para a rede local (0.0.0.0) ou volta ao local (127.0.0.1)."""
    ativo = request.form.get("ativo", "1") == "1"
    estado = painel_config.carregar_estado()
    porta = (estado.get("porta") or os.environ.get("GMA_PORT", "5050")).strip() or "5050"
    host = "0.0.0.0" if ativo else "127.0.0.1"
    try:
        painel_config.definir_host_porta(host, porta)
        msg = ("Rede local liberada (0.0.0.0). Reinicie para aplicar — celulares no Wi-Fi vão conseguir acessar."
               if ativo else "Voltou para acesso só local (127.0.0.1). Reinicie para aplicar.")
        logger.info(f"PAINEL | Host-rede → {host}")
        return _pagina_painel(aviso=msg)
    except Exception as e:
        return _pagina_painel(erro=f"Não deu para mudar o host: {e}")


@app.route("/painel/testar/<chave>", methods=["POST"])
def painel_testar(chave):
    """Testa uma conexão ('liga o motor') e mostra o resultado no cockpit."""
    ok, msg = _testar_conexao(chave)
    logger.info(f"PAINEL | Teste '{chave}': {'OK' if ok else 'FALHA'} — {msg}")
    return _pagina_painel(resultado_teste=(chave, ok, msg))


@app.route("/painel/encerrar", methods=["POST"])
def painel_encerrar():
    """
    Desliga o GMA inteiro. No modelo de 2 níveis, isso = encerrar o SAGUÃO
    (saguao.py): ao receber o SIGTERM, ele desce esta sessão (Flask + processos)
    e se desliga de forma limpa — o mesmo caminho do atalho "Encerrar GMA".
    """
    logger.info("PAINEL | Desligamento do GMA solicitado")
    # Escreve o sinal de encerrar SEMPRE — quem comanda (o SAGUÃO de hoje ou o
    # maestro antigo) vigia este arquivo e se desliga, descendo esta sessão junto.
    # Como esta tela só existe DENTRO de uma sessão, há sempre um supervisor para
    # consumir o sinal; se sobrar, é limpo no próximo arranque. Usamos arquivo de
    # propósito: um filho (Flask) mandar sinal no processo pai não é confiável.
    _painel_criar_sinal(".gma_encerrar")
    aviso = ("Desligando o GMA… o sistema está descendo esta sessão e se desligando. "
             "Em instantes esta página deixa de responder — pode fechar a janela.")
    return _pagina_painel(aviso=aviso)


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
