#!/usr/bin/env python3
"""
leitor_midia.py
Camada 1 do GMA — Análise de conteúdo dos cartões detectados pelo Porteiro.

O Porteiro detecta cartões e grava JSONs em fila_material/ com status
"aguardando_match". O Leitor de Mídia é o processo que consome esses
JSONs e faz a análise real do conteúdo:

  1. Detecta JSONs novos (não analisados) em fila_material/
  2. Lê os arquivos do cartão usando ler_cartao.varrer_pasta() e analisar()
  3. Enriquece o JSON com os dados da análise (total de arquivos, tipos,
     câmeras detectadas, intervalo de datas, etc.)
  4. Emite alerta se o cartão contém arquivos de mais de um dia
  5. Chama matcher.tentar_match() para tentar cruzar o material com um formulário
  6. Loga tudo em logs/leitor_midia.log

O critério para "não analisado" é: o campo "analise_realizada" está ausente
ou é False. JSONs gravados pelo Porteiro não têm esse campo — são tratados
como não analisados.

Uso:
    python3 leitor_midia.py

Controlado pelo mesmo sentinela .gma_ativo do Porteiro.
Encerrar com Ctrl+C.
"""

import os
import json
import time
import logging
import subprocess
from datetime import datetime

# Importa os módulos locais do GMA
import ler_cartao
import matcher

# ── CONFIGURAÇÃO DE CAMINHOS ───────────────────────────────────────────────────

# Raiz do projeto GMA
RAIZ_GMA = "/Users/serafa/GMA"

# Isolamento multi-projeto (Camada 5): a fila mora ao lado do banco do projeto
# ativo (GMA_DB); para o laboratório, é a pasta da raiz de sempre.
import sys
sys.path.insert(0, RAIZ_GMA)
import painel_config

# Pasta onde o Porteiro deposita os JSONs de material detectado (isolada por projeto)
PASTA_FILA_MATERIAL = painel_config.pasta_ao_lado_do_banco("fila_material")

# Arquivo sentinela: se existir, o sistema está ativo e processando
SENTINELA = os.path.join(RAIZ_GMA, ".gma_ativo")

# Arquivo de log do Leitor de Mídia
ARQUIVO_LOG = os.path.join(RAIZ_GMA, "logs", "leitor_midia.log")

# Intervalo entre cada ciclo de varredura da fila, em segundos
INTERVALO_POLLING = 3.0


# ── CONFIGURAÇÃO DO LOGGER ────────────────────────────────────────────────────

def configurar_logger():
    """
    Configura o sistema de log do Leitor de Mídia.
    Grava em logs/leitor_midia.log E mostra no terminal ao mesmo tempo.
    Formato padrão GMA: AAAA-MM-DDTHH:MM:SS | mensagem
    """
    logger = logging.getLogger("leitor_midia")
    logger.setLevel(logging.DEBUG)

    # Evita duplicar handlers se o logger já foi configurado antes
    if logger.handlers:
        return logger

    # Formato com timestamp ISO-8601 sem milissegundos
    formato = logging.Formatter(
        fmt="%(asctime)s | %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S"
    )

    # Garante que a pasta de logs existe antes de abrir o arquivo
    os.makedirs(os.path.dirname(ARQUIVO_LOG), exist_ok=True)

    # Handler de arquivo (modo append — nunca sobrescreve linhas antigas)
    handler_arquivo = logging.FileHandler(ARQUIVO_LOG, encoding="utf-8")
    handler_arquivo.setFormatter(formato)
    logger.addHandler(handler_arquivo)

    # Handler de terminal para acompanhamento em tempo real
    handler_terminal = logging.StreamHandler()
    handler_terminal.setFormatter(formato)
    logger.addHandler(handler_terminal)

    return logger


# ── LEITURA E ESCRITA DE JSONs ────────────────────────────────────────────────

def ler_json(caminho_arquivo):
    """
    Lê um arquivo JSON e retorna o dicionário de dados.
    Retorna None se o arquivo não puder ser lido ou estiver corrompido.
    """
    try:
        with open(caminho_arquivo, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def salvar_json(caminho_arquivo, dados):
    """
    Sobrescreve o arquivo JSON com os novos dados.
    Retorna True se conseguiu salvar, False se deu erro.
    """
    try:
        with open(caminho_arquivo, "w", encoding="utf-8") as f:
            json.dump(dados, f, ensure_ascii=False, indent=2)
        return True
    except OSError:
        return False


# ── BUSCA DE JSONs NÃO ANALISADOS ────────────────────────────────────────────

def listar_nao_analisados():
    """
    Percorre fila_material/ e retorna os JSONs que ainda precisam ser analisados.

    Um JSON é considerado "não analisado" quando:
      - O campo "analise_realizada" não existe no arquivo (JSONs do Porteiro), OU
      - O campo "analise_realizada" existe e é False (explicitamente marcado)

    Retorna uma lista de tuplas: (caminho_completo, nome_do_arquivo, dicionario_de_dados)
    """
    resultado = []

    # Se a pasta não existir, retorna vazio sem erro
    if not os.path.isdir(PASTA_FILA_MATERIAL):
        return resultado

    try:
        arquivos = sorted(os.listdir(PASTA_FILA_MATERIAL))
    except OSError:
        return resultado

    for nome_arquivo in arquivos:
        # Processa apenas arquivos .json
        if not nome_arquivo.endswith(".json"):
            continue

        caminho_completo = os.path.join(PASTA_FILA_MATERIAL, nome_arquivo)
        dados = ler_json(caminho_completo)

        # Arquivo ilegível ou corrompido — ignora e passa para o próximo
        if dados is None:
            continue

        # Considera não analisado se o campo estiver ausente OU for False
        ja_analisado = dados.get("analise_realizada", False)
        if not ja_analisado:
            resultado.append((caminho_completo, nome_arquivo, dados))

    return resultado


# ── CAMINHO DO EXIFTOOL (mesma convenção do extrator_frames.py) ──────────────

EXIFTOOL = "/opt/homebrew/bin/exiftool"


# ── DETECÇÃO DO MODELO DA CÂMERA VIA EXIFTOOL ────────────────────────────────

def detectar_modelo_camera(caminho_cartao, lista_arquivos):
    """
    Usa o exiftool para ler o campo 'Model' de até 3 arquivos de mídia do cartão.

    Princípio de segurança nº 2: lê no máximo 3 arquivos — não estressamos o
    cartão com material insubstituível.

    O exiftool é chamado via subprocess, seguindo o padrão defensivo do projeto:
    qualquer erro (exiftool ausente, arquivo corrompido, timeout) retorna None
    sem travar o fluxo.

    Parâmetros:
      caminho_cartao — caminho da pasta raiz do cartão (para montar caminhos)
      lista_arquivos — lista de dicts retornada por varrer_pasta() (campo 'nome')

    Retorna a string do modelo (ex: "GoPro HERO7 Black") ou None.
    """
    # Verifica se o exiftool está instalado no caminho esperado
    if not os.path.isfile(EXIFTOOL):
        return None

    # Filtra para tentar apenas arquivos de mídia real (VIDEO ou FOTO)
    tipos_midia = {"VIDEO", "FOTO"}
    candidatos = [
        a for a in lista_arquivos if a.get("tipo") in tipos_midia
    ]

    # Tenta no máximo 3 arquivos para não estressar o cartão
    for arq in candidatos[:3]:
        # Reconstrói o caminho completo do arquivo no cartão
        # A varredura não guarda o caminho completo, mas podemos encontrá-lo
        # percorrendo o cartão de forma eficiente via os.walk
        caminho_arquivo = _encontrar_arquivo_no_cartao(caminho_cartao, arq["nome"])
        if not caminho_arquivo:
            continue

        try:
            resultado = subprocess.run(
                [EXIFTOOL, "-json", "-Model", "-CameraModelName", caminho_arquivo],
                capture_output=True,
                text=True,
                timeout=15,   # segundos — suficiente para ler metadados
            )
            dados = (json.loads(resultado.stdout) or [{}])[0]

            # Tenta os campos em ordem de preferência
            modelo = dados.get("CameraModelName") or dados.get("Model")
            if modelo and modelo.strip():
                return modelo.strip()

        except Exception:
            # Qualquer erro (exiftool, JSON inválido, timeout) — tenta o próximo arquivo
            continue

    # Nenhum dos candidatos retornou modelo — retorna None sem quebrar
    return None


def _encontrar_arquivo_no_cartao(caminho_cartao, nome_arquivo):
    """
    Encontra o caminho completo de um arquivo no cartão, dado só o nome.
    Percorre a pasta recursivamente e retorna o primeiro que encontrar.
    Retorna None se não achar.

    Nota: esta função é auxiliar de detectar_modelo_camera — percorre apenas
    o suficiente para encontrar o arquivo pedido.
    """
    try:
        for raiz, _dirs, nomes in os.walk(caminho_cartao):
            for nome in nomes:
                if nome == nome_arquivo:
                    return os.path.join(raiz, nome)
    except OSError:
        pass
    return None


# ── ANÁLISE DE UM CARTÃO ──────────────────────────────────────────────────────

def analisar_cartao(caminho_cartao, logger):
    """
    Usa as funções de ler_cartao.py para varrer a pasta do cartão e montar
    o resumo de conteúdo.

    Parâmetros:
      caminho_cartao — caminho para a pasta/volume do cartão (ex: /Volumes/CARTAO_BM)
      logger         — logger configurado do Leitor de Mídia

    Retorna um dicionário com os campos de análise prontos para enriquecer o JSON.
    Em caso de erro, retorna um dicionário com os campos zerados e uma indicação
    de erro, mas nunca levanta exceção — o loop principal não pode travar.
    """
    logger.info(f"ANÁLISE INICIADA | Caminho: {caminho_cartao}")

    try:
        # Varre a pasta e coleta os arquivos
        lista_arquivos = ler_cartao.varrer_pasta(caminho_cartao)
    except PermissionError as erro:
        # Sem permissão para ler o cartão — erro grave mas recuperável
        logger.error(f"ERRO DE PERMISSÃO | Não foi possível ler {caminho_cartao} | {erro}")
        return {
            "status_analise": "erro_permissao",
            "analise_realizada": True,  # Marca como analisado para não tentar de novo
            "analise_timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "total_arquivos": 0,
        }
    except Exception as erro:
        # Qualquer outro erro inesperado na leitura da pasta
        logger.error(f"ERRO INESPERADO NA VARREDURA | {caminho_cartao} | {erro}")
        return {
            "status_analise": "erro_varredura",
            "analise_realizada": True,
            "analise_timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "total_arquivos": 0,
        }

    # Pasta completamente vazia (sem nenhum arquivo, nem de sistema)
    if not lista_arquivos:
        logger.warning(f"AVISO: CARTÃO VAZIO | Nenhum arquivo encontrado em: {caminho_cartao}")
        return {
            "analise_realizada": True,
            "analise_timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "total_arquivos": 0,
            "total_midia": 0,          # arquivos VIDEO+FOTO+AUDIO
            "tamanho_total_bytes": 0,
            "contagem_tipo": {},
            "cameras_detectadas": [],
            "data_inicio": None,
            "data_fim": None,
            "dias_encontrados": [],
            "alerta_multidia": False,
            "dias_distintos": 0,
            # Assinatura vazia — cartão sem mídia não tem o que aprender
            "_lista_arquivos_para_assinatura": [],
        }

    # Monta o resumo com as funções de ler_cartao.py
    resumo = ler_cartao.analisar(lista_arquivos)

    # Conta apenas arquivos de mídia real (VIDEO, FOTO, AUDIO) — exclui OUTRO.
    # "OUTRO" inclui arquivos de sistema, XML de framelines, thumbnails, etc.
    # Esse número é a fonte de verdade para decidir se há footage real no cartão.
    TIPOS_MIDIA_REAL = {"VIDEO", "FOTO", "AUDIO"}
    contagem_tipo = resumo["contagem_tipo"]
    total_midia_real = sum(
        qtd for tipo, qtd in contagem_tipo.items() if tipo in TIPOS_MIDIA_REAL
    )

    # Converte os objetos date e datetime para strings ISO-8601
    # (JSON não serializa datetime nativamente)
    data_inicio_str = resumo["data_inicio"].strftime("%Y-%m-%dT%H:%M:%S")
    data_fim_str    = resumo["data_fim"].strftime("%Y-%m-%dT%H:%M:%S")

    # Dias distintos como strings "AAAA-MM-DD" para facilitar leitura no painel
    dias_str = [d.strftime("%Y-%m-%d") for d in resumo["dias"]]
    qtd_dias = len(dias_str)

    # Alerta de cartão não formatado: mais de um dia de material no cartão
    alerta_multidia = qtd_dias > 1

    if alerta_multidia:
        logger.warning(
            f"!!! ALERTA MULTI-DIA !!! | "
            f"Cartão com arquivos de {qtd_dias} dias diferentes | "
            f"Dias: {', '.join(dias_str)} | "
            f"Caminho: {caminho_cartao} | "
            f"Possível cartão não formatado — verifique antes de copiar"
        )
    else:
        logger.info(
            f"ANÁLISE OK | "
            f"{resumo['total']} arquivos ({total_midia_real} de mídia) | "
            f"Tamanho: {ler_cartao.formatar_tamanho(resumo['tamanho_total'])} | "
            f"Dia único: {dias_str[0] if dias_str else '?'}"
        )

    # Monta o dicionário de campos para enriquecer o JSON da fila_material/
    # O campo _lista_arquivos_para_assinatura é interno: é passado para
    # processar_json() montar a assinatura completa e depois removido do JSON.
    return {
        "analise_realizada": True,
        "analise_timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "total_arquivos": resumo["total"],
        "total_midia": total_midia_real,   # apenas VIDEO+FOTO+AUDIO (fonte de verdade)
        "tamanho_total_bytes": resumo["tamanho_total"],
        "contagem_tipo": resumo["contagem_tipo"],
        "cameras_detectadas": resumo["cameras"],
        "data_inicio": data_inicio_str,
        "data_fim": data_fim_str,
        "dias_encontrados": dias_str,
        "alerta_multidia": alerta_multidia,
        "dias_distintos": qtd_dias,
        # Passagem interna da lista de arquivos — NÃO vai para o JSON final
        "_lista_arquivos_para_assinatura": lista_arquivos,
    }


# ── PROCESSAMENTO DE UM JSON DA FILA ─────────────────────────────────────────

def processar_json(caminho_arquivo, nome_arquivo, dados, logger):
    """
    Processa um único JSON de fila_material/ que ainda não foi analisado.

    Etapas:
      1. Verifica se o caminho do cartão ainda existe (pode ter sido ejetado)
      2. Chama analisar_cartao() para ler o conteúdo
      3. Enriquece o JSON com os dados da análise e salva
      4. Chama matcher.tentar_match() para tentar o match com um formulário

    Parâmetros:
      caminho_arquivo — caminho completo do arquivo JSON em fila_material/
      nome_arquivo    — só o nome do arquivo (para log)
      dados           — dicionário já carregado do JSON
      logger          — logger configurado
    """
    caminho_cartao = dados.get("caminho", "")
    nome_cartao = dados.get("nome", nome_arquivo)

    logger.info(f"PROCESSANDO | Arquivo: {nome_arquivo} | Cartão: {nome_cartao}")

    # ── Passo 1: verifica se o caminho do cartão ainda existe ─────────────────
    if not caminho_cartao or not os.path.exists(caminho_cartao):
        logger.warning(
            f"CAMINHO NÃO ENCONTRADO | Cartão: {nome_cartao} | "
            f"Caminho: {caminho_cartao} | Cartão pode ter sido ejetado antes da análise"
        )
        # Marca no JSON e salva — não tenta analisar um cartão que sumiu
        dados["analise_realizada"] = True
        dados["analise_timestamp"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        dados["status"] = "caminho_nao_encontrado"
        salvar_json(caminho_arquivo, dados)
        return

    # ── Passo 2: analisa o conteúdo do cartão ────────────────────────────────
    resultado_analise = analisar_cartao(caminho_cartao, logger)

    # Trata erro de permissão: atualiza o status do JSON e encerra
    if resultado_analise.get("status_analise") in ("erro_permissao", "erro_varredura"):
        dados.update(resultado_analise)
        dados["status"] = "erro_leitura"
        sucesso = salvar_json(caminho_arquivo, dados)
        if not sucesso:
            logger.error(f"FALHA AO SALVAR JSON | Arquivo: {nome_arquivo}")
        return

    # ── Passo 2b: cartão sem mídia reconhecida — dois casos possíveis ────────────
    #
    # "total_midia" conta apenas arquivos VIDEO+FOTO+AUDIO (extensões listadas em
    # ler_cartao.EXTENSOES). Arquivos com extensão desconhecida viram tipo OUTRO.
    #
    # ATENÇÃO — limitação real da lista EXTENSOES:
    #   A lista é a guardiã, mas NÃO é perfeita nem exaustiva. Se um cartão tiver
    #   footage num formato que ainda não está na lista (câmera nova, codec proprietário
    #   pouco conhecido), esses arquivos viram OUTRO, total_midia dá zero, e o cartão
    #   correria o risco de ser silenciosamente ignorado como "sem mídia".
    #   Isso seria um FALSO NEGATIVO — a pior direção, pois footage real seria perdida.
    #
    # Para evitar o falso negativo usamos o TAMANHO do conteúdo não-mídia (OUTRO):
    #   • Footage é GRANDE: clips de cinema facilmente chegam a GBs; mesmo um único
    #     arquivo de 50 MB já seria um RAW de foto pesado ou um clip muito curto.
    #   • Configuração/sistema é MINÚSCULA: XML de framelines, LUTs, thumbnails,
    #     logs de câmera — normalmente ficam abaixo de 1 MB cada, total abaixo de 10 MB.
    #
    # Critério de decisão (constantes ajustáveis abaixo):
    #   - Se algum arquivo OUTRO tiver tamanho >= LIMIAR_ARQUIVO_OUTRO_BYTES → "revisar"
    #   - Se a soma de todos os OUTRO tiver tamanho >= LIMIAR_TOTAL_OUTRO_BYTES → "revisar"
    #   - Caso contrário → "sem_midia" (conteúdo trivial, pode ignorar com segurança)
    #
    # Em dúvida, SEMPRE prefira "revisar" (chamar o operador) a "sem_midia" (ignorar).
    # Melhor incomodar o operador do que silenciosamente jogar footage no lixo.

    # Arquivo individual OUTRO acima deste tamanho → suspeito de footage não reconhecida.
    # 50 MB: menor que qualquer clip de câmera profissional, maior que qualquer config.
    LIMIAR_ARQUIVO_OUTRO_BYTES = 50 * 1024 * 1024   # 50 MB

    # Soma de todos os arquivos OUTRO acima deste total → suspeito de footage.
    # 500 MB: uma pasta de configuração nunca chega aqui; uma cartão com footage sim.
    LIMIAR_TOTAL_OUTRO_BYTES   = 500 * 1024 * 1024  # 500 MB

    if resultado_analise.get("total_midia", 0) == 0:

        # ── Avalia o conteúdo não-mídia (tipo OUTRO) para decidir entre os dois casos
        lista_arquivos_para_avaliacao = resultado_analise.get(
            "_lista_arquivos_para_assinatura", []
        )
        arquivos_outro = [
            a for a in lista_arquivos_para_avaliacao if a.get("tipo") == "OUTRO"
        ]
        maior_arquivo_outro    = max((a["tamanho"] for a in arquivos_outro), default=0)
        tamanho_total_outro    = sum(a["tamanho"] for a in arquivos_outro)

        # Verifica se algum arquivo OUTRO é grande o suficiente para ser footage
        ha_arquivo_outro_grande = maior_arquivo_outro >= LIMIAR_ARQUIVO_OUTRO_BYTES
        ha_volume_outro_grande  = tamanho_total_outro >= LIMIAR_TOTAL_OUTRO_BYTES
        conteudo_suspeito       = ha_arquivo_outro_grande or ha_volume_outro_grande

        if conteudo_suspeito:
            # ── CASO 2: arquivos não reconhecidos mas de tamanho compatível com footage ──
            # NÃO ignoramos — chamamos o operador para verificar manualmente.
            # O cartão recebe status "revisar" e aparece no painel com cor de atenção.
            # Ele NÃO entra no Matcher nem na Transferência automática.
            status_sem_midia = "revisar"
            logger.warning(
                f"ATENÇÃO — REVISAR | Cartão: {nome_cartao} | "
                f"0 arquivos de mídia reconhecida, MAS há {len(arquivos_outro)} arquivo(s) "
                f"OUTRO com tamanho suspeito | "
                f"Maior arquivo: {ler_cartao.formatar_tamanho(maior_arquivo_outro)} | "
                f"Total não-mídia: {ler_cartao.formatar_tamanho(tamanho_total_outro)} | "
                f"Possível footage em formato não mapeado — operador deve verificar: "
                f"{caminho_cartao}"
            )
        else:
            # ── CASO 1: conteúdo trivial (config, sistema, XML de câmera) ──────────────
            # Arquivos OUTRO existem mas são todos pequenos — seguro ignorar.
            # Ex.: ARRI /Volumes/MINI com 2 XMLs de framelines totalizando alguns KB.
            status_sem_midia = "sem_midia"
            logger.warning(
                f"SEM MÍDIA — IGNORADO | Cartão: {nome_cartao} | "
                f"Marca detectada pelo Porteiro: {dados.get('marca_camera', '?')} | "
                f"0 arquivos de mídia reconhecida em: {caminho_cartao} | "
                f"Conteúdo OUTRO é trivial ({ler_cartao.formatar_tamanho(tamanho_total_outro)}) | "
                f"Cartão não entra no Matcher nem na Transferência."
            )

        # Enriquece o JSON com os dados da análise (timestamps, contagens) e salva
        lista_arquivos_analise = resultado_analise.pop("_lista_arquivos_para_assinatura", [])
        dados.update(resultado_analise)
        dados["status"] = status_sem_midia

        salvar_json(caminho_arquivo, dados)

        # Grava no banco para aparecer no Kanban com o rótulo correto
        try:
            import banco_dados as _bd
            _conn_sem_midia = _bd.inicializar_banco()
            _db_id_sem_midia = _bd.gravar_cartao(
                _conn_sem_midia,
                volume=dados.get("volume", dados.get("nome", "")),
                caminho_origem=dados.get("caminho", ""),
                marca_camera=dados.get("marca_camera"),
                tipo_material=dados.get("tipo_material"),
                data_inicio=None,
                data_fim=None,
                alerta_multidia=False,
                dias_distintos=0,
                total_arquivos=dados.get("total_arquivos", 0),
                tamanho_bytes=dados.get("tamanho_total_bytes", 0),
            )
            # Aplica o status terminal no banco (gravar_cartao usa "detectado" por padrão)
            _bd.atualizar_cartao(_conn_sem_midia, _db_id_sem_midia, {"status": status_sem_midia})
            _conn_sem_midia.close()
            dados["db_cartao_id"] = _db_id_sem_midia
            salvar_json(caminho_arquivo, dados)
            logger.info(
                f"BANCO | Gravado | db_id={_db_id_sem_midia} | status={status_sem_midia}"
            )
        except Exception as _err_sm:
            logger.error(f"BANCO | Falha ao gravar {status_sem_midia} (fluxo continua) | {_err_sm}")

        # Para aqui — sem assinatura, sem Matcher, sem Transferência
        return

    # ── Passo 3: enriquece e salva o JSON com os dados da análise ─────────────
    # Extrai a lista de arquivos antes de gravar (campo interno, não vai para o JSON)
    lista_arquivos_analise = resultado_analise.pop("_lista_arquivos_para_assinatura", [])

    dados.update(resultado_analise)

    # ── Montagem da assinatura do cartão (Fase 1 do perfil de profissional) ────
    # A assinatura é um dicionário com a "impressão digital" do cartão:
    # câmera, prefixos de nome e faixa de numeração. O modelo é adicionado via
    # exiftool (máximo 3 leituras — não estressamos o cartão).
    # Se qualquer parte falhar, a assinatura fica ausente/parcial sem travar.
    try:
        assinatura_parcial = ler_cartao.extrair_assinatura(lista_arquivos_analise)
        # Adiciona o modelo via exiftool (defensivo: retorna None se falhar)
        modelo_detectado = detectar_modelo_camera(caminho_cartao, lista_arquivos_analise)
        assinatura_parcial["modelo"] = modelo_detectado
        dados["assinatura"] = assinatura_parcial
        logger.info(
            f"ASSINATURA | câmera={assinatura_parcial.get('camera')} "
            f"modelo={modelo_detectado} "
            f"prefixos={assinatura_parcial.get('prefixos')} "
            f"faixa=[{assinatura_parcial.get('num_min')}, {assinatura_parcial.get('num_max')}]"
        )
    except Exception as _err_ass:
        # Falha na assinatura não trava a análise — fluxo continua sem ela
        logger.error(f"ASSINATURA | Falha ao extrair (fluxo continua) | {_err_ass}")

    sucesso = salvar_json(caminho_arquivo, dados)

    if not sucesso:
        logger.error(
            f"FALHA AO SALVAR ANÁLISE | Arquivo: {nome_arquivo} | "
            f"Os dados de análise foram perdidos"
        )
        return

    logger.info(f"JSON ATUALIZADO | Arquivo: {nome_arquivo}")

    # ── Integração Camada 3: grava o cartão no banco SQLite ──────────────────
    # Este bloco é ADITIVO — se o banco falhar, o fluxo JSON continua normalmente.
    try:
        import banco_dados as _bd
        _conn_leitor = _bd.inicializar_banco()
        _db_cartao_id = _bd.gravar_cartao(
            _conn_leitor,
            volume=dados.get("volume", dados.get("nome", "")),
            caminho_origem=dados.get("caminho", ""),
            marca_camera=dados.get("marca_camera"),
            tipo_material=dados.get("tipo_material"),
            data_inicio=dados.get("data_inicio"),
            data_fim=dados.get("data_fim"),
            alerta_multidia=bool(dados.get("alerta_multidia", False)),
            dias_distintos=dados.get("dias_distintos", 1),
            total_arquivos=dados.get("total_arquivos"),
            tamanho_bytes=dados.get("tamanho_total_bytes"),
        )
        _conn_leitor.close()
        # Salva o ID do banco no JSON — ponte para o Matcher e Transferência
        dados["db_cartao_id"] = _db_cartao_id
        salvar_json(caminho_arquivo, dados)
        logger.info(f"BANCO | Cartão gravado | db_id={_db_cartao_id}")
    except Exception as _err_bd:
        logger.error(f"BANCO | Falha ao gravar cartão (fluxo continua) | {_err_bd}")

    # ── Passo 4: chama o Matcher para tentar cruzar com um formulário ──────────
    logger.info(f"CHAMANDO MATCHER | Para: {nome_arquivo}")
    try:
        matches = matcher.tentar_match()
        if matches:
            logger.info(
                f"MATCH REALIZADO | {len(matches)} par(es) encontrado(s) | "
                f"Arquivo: {nome_arquivo}"
            )
        else:
            logger.info(
                f"SEM MATCH | Nenhum formulário compatível ainda | "
                f"Arquivo: {nome_arquivo}"
            )
    except Exception as erro:
        # Erro no Matcher não pode parar o Leitor — apenas loga e segue
        logger.error(f"ERRO NO MATCHER | Arquivo: {nome_arquivo} | {erro}")


# ── VERIFICAÇÕES DO AMBIENTE ─────────────────────────────────────────────────

def verificar_ambiente():
    """
    Garante que as pastas necessárias existem antes de começar o loop.
    Cria fila_material/ e logs/ se ainda não existirem.
    """
    for pasta in [PASTA_FILA_MATERIAL, os.path.dirname(ARQUIVO_LOG)]:
        os.makedirs(pasta, exist_ok=True)


def sentinela_ativo():
    """
    Retorna True se o arquivo sentinela .gma_ativo existe.
    O Leitor só processa quando esse arquivo está presente.
    """
    return os.path.isfile(SENTINELA)


# ── LOOP PRINCIPAL ────────────────────────────────────────────────────────────

def main():
    """
    Ponto de entrada do Leitor de Mídia.

    Fica em loop contínuo, verificando a fila a cada INTERVALO_POLLING segundos.
    Para cada JSON não analisado encontrado:
      - Se o sentinela estiver ativo → processa.
      - Se não → registra no log e pula.

    Encerrado com Ctrl+C ou kill do processo.
    """
    verificar_ambiente()
    logger = configurar_logger()

    logger.info(
        f"LEITOR DE MÍDIA INICIADO | Monitorando fila_material/ "
        f"a cada {INTERVALO_POLLING}s"
    )
    logger.info(f"SENTINELA | Caminho: {SENTINELA}")
    logger.info(f"FILA      | Caminho: {PASTA_FILA_MATERIAL}")

    # Loop infinito — só para com Ctrl+C ou kill
    while True:
        try:
            time.sleep(INTERVALO_POLLING)

            # Busca JSONs que ainda não foram analisados
            pendentes = listar_nao_analisados()

            if not pendentes:
                # Sem nada novo — só continua o loop silenciosamente
                continue

            logger.info(f"FILA | {len(pendentes)} JSON(s) pendente(s) para análise")

            for caminho_arquivo, nome_arquivo, dados in pendentes:
                if not sentinela_ativo():
                    # Sistema pausado — registra e pula sem processar
                    logger.info(
                        f"IGNORADO | Sentinela ausente | Arquivo: {nome_arquivo} | "
                        f"Crie {SENTINELA} para ativar o processamento"
                    )
                    continue

                try:
                    processar_json(caminho_arquivo, nome_arquivo, dados, logger)
                except Exception as erro:
                    # Erro inesperado em um JSON não pode travar todo o loop
                    logger.error(
                        f"ERRO INESPERADO | Arquivo: {nome_arquivo} | "
                        f"{type(erro).__name__}: {erro}"
                    )

        except KeyboardInterrupt:
            # Ctrl+C: encerra de forma limpa e informa no log
            logger.info("LEITOR DE MÍDIA ENCERRADO | Interrompido pelo operador (Ctrl+C)")
            break

        except Exception as erro:
            # Erro no próprio loop — registra mas nunca para
            logger.error(f"ERRO NO LOOP PRINCIPAL | {erro} | Leitor continua rodando")


# ── PONTO DE ENTRADA ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    main()
