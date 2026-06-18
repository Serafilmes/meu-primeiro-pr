#!/usr/bin/env python3
"""
porteiro.py
Camada 1 do GMA — Detecção de cartões de memória e material de entrada.

O Porteiro fica rodando em segundo plano e tem UMA única responsabilidade:
detectar quando novo material chega ao sistema GMA — seja via cartão de
memória físico montado em /Volumes/, seja via pasta de entrada manual —
e anunciar esse evento para o restante do sistema.

Ele NÃO analisa arquivos, NÃO lê metadados, NÃO processa nada.
Só detecta e registra.

Funcionamento:
  - Usa polling simples: a cada intervalo, compara os volumes montados
    em /Volumes/ com a lista que havia antes.
  - Faz o mesmo para subpastas e arquivos em GMA/entrada/.
  - Se aparecer um volume novo em /Volumes/ → verifica se parece câmera.
      - Se sim → loga CÂMERA DETECTADA e cria JSON na fila_material/.
      - Se não  → loga VOLUME IGNORADO e não age.
  - Se aparecer subpasta ou arquivo novo em entrada/ → cria JSON na fila_material/.
  - Se o arquivo sentinela .gma_ativo não existir → fica rodando mas
    ignora os eventos (não age, não desliga).

Uso:
    python3 porteiro.py

Para ligar o processamento (criar sentinela):
    touch /Users/serafa/GMA/.gma_ativo

Para desligar o processamento (remover sentinela):
    rm /Users/serafa/GMA/.gma_ativo

Para encerrar o Porteiro completamente:
    Ctrl+C no terminal onde está rodando
    (ou kill <pid> se estiver em segundo plano)
"""

import os
import json
import time
import logging
from datetime import datetime

# ── CONFIGURAÇÃO DE CAMINHOS ───────────────────────────────────────────────────

# Raiz do projeto GMA
RAIZ_GMA = "/Users/serafa/GMA"

# Isolamento multi-projeto (Camada 5): as filas moram AO LADO do banco do projeto
# ativo (GMA_DB). Para o laboratório, resolvem para as pastas da raiz de sempre —
# então nada muda no laboratório; só projetos novos ganham as suas próprias filas.
import sys
sys.path.insert(0, RAIZ_GMA)
import painel_config

# Pasta onde os volumes de mídia são montados no macOS
PASTA_VOLUMES = "/Volumes"

# Pasta de ingestão manual: AirDrop, download, ou qualquer outro meio
PASTA_ENTRADA = os.path.join(RAIZ_GMA, "entrada")

# Arquivo sentinela: se existir, o Porteiro processa eventos
SENTINELA = os.path.join(RAIZ_GMA, ".gma_ativo")

# Arquivo de log do Porteiro
ARQUIVO_LOG = os.path.join(RAIZ_GMA, "logs", "porteiro.log")

# Pasta onde os JSONs de material detectado ficam aguardando o Matcher
# (renomeada de fila/ para fila_material/ para distinguir do fila_forms/)
# Isolada por projeto (mora ao lado do banco ativo; raiz para o laboratório).
PASTA_FILA = painel_config.pasta_ao_lado_do_banco("fila_material")

# Intervalo entre cada verificação, em segundos
INTERVALO_POLLING = 2.0

# ── TABELA DE ASSINATURAS DE CÂMERA ───────────────────────────────────────────
#
# Cada câmera ou família de câmeras tem uma assinatura: pastas características
# que ela cria na raiz do cartão, e extensões de arquivo exclusivas.
#
# A detecção tenta primeiro as pastas (rápido) e só depois as extensões
# (percorre arquivos, mais lento — limitado a 2 níveis de profundidade).
#
# Para adicionar uma câmera nova, basta acrescentar um dicionário à lista.

ASSINATURAS_CAMERA = [
    # ── Câmeras com arquivos únicos na raiz (mais específicas — verificadas primeiro) ──
    {
        "marca": "GoPro",
        "arquivos_raiz": ["Get_started_with_GoPro.url", "MISC"],  # arquivo exclusivo GoPro
        "pastas": ["DCIM"],
        "extensoes": [".mp4"],
    },
    # ── Câmeras com pastas únicas na raiz ─────────────────────────────────────
    {
        "marca": "Sony",
        "arquivos_raiz": [],
        "pastas": ["PRIVATE", "AVCHD"],
        "extensoes": [".arw", ".mxf", ".mp4"],
    },
    {
        "marca": "Blackmagic",
        "arquivos_raiz": [],
        "pastas": ["Blackmagic Design", "Blackmagic"],
        "extensoes": [".braw"],
    },
    {
        "marca": "RED",
        "arquivos_raiz": [],
        "pastas": ["RDC", "REEL"],
        "extensoes": [".r3d"],
    },
    {
        "marca": "Arri",
        "arquivos_raiz": [],
        "pastas": ["Arri"],
        "extensoes": [".ari", ".mxf"],
    },
    {
        "marca": "Panasonic",
        "arquivos_raiz": [],
        "pastas": ["PRIVATE", "CONTENTS"],
        "extensoes": [".rw2", ".mts", ".mov"],
    },
    {
        "marca": "DJI",
        "arquivos_raiz": [],
        "pastas": ["DJI"],   # DJI cria pasta DJI/ na raiz além de DCIM/
        "extensoes": [".dng", ".mp4", ".mov"],
    },
    # ── Genérica: DCIM sem assinatura específica — verificada por último ──────
    {
        "marca": "Genérica/Canon/Nikon/Fuji",
        "arquivos_raiz": [],
        "pastas": ["DCIM"],
        "extensoes": [".cr2", ".cr3", ".nef", ".raf", ".jpg", ".jpeg"],
    },
]

# Extensões genéricas usadas como último recurso (para a pasta de entrada manual)
EXTENSOES_GENERICAS = {
    ".mp4", ".mxf", ".mov", ".arw", ".cr2", ".cr3",
    ".nef", ".raf", ".rw2", ".dng", ".braw", ".r3d",
    ".ari", ".mts",
}

# ── CONFIGURAÇÃO DO LOGGER ────────────────────────────────────────────────────

def configurar_logger():
    """
    Configura o sistema de log do Porteiro.
    Grava em arquivo (porteiro.log) E mostra no terminal ao mesmo tempo.
    O formato é o pedido pelo GMA:
        2026-06-05T14:32:01 | CÂMERA DETECTADA | Volume: X | Caminho: Y
    """
    logger = logging.getLogger("porteiro")
    logger.setLevel(logging.DEBUG)

    # Formato com timestamp ISO-8601 sem milissegundos
    formato = logging.Formatter(
        fmt="%(asctime)s | %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S"
    )

    # Handler que grava no arquivo (modo append — nunca sobrescreve)
    handler_arquivo = logging.FileHandler(ARQUIVO_LOG, encoding="utf-8")
    handler_arquivo.setFormatter(formato)
    logger.addHandler(handler_arquivo)

    # Handler que exibe no terminal para acompanhamento em tempo real
    handler_terminal = logging.StreamHandler()
    handler_terminal.setFormatter(formato)
    logger.addHandler(handler_terminal)

    return logger


# ── FUNÇÕES DE DETECÇÃO ───────────────────────────────────────────────────────

def volume_parece_camera(caminho_volume):
    """
    Verifica se um volume montado parece ser um cartão de câmera.

    Retorna uma tupla (resultado, marca, criterio):
      - resultado: True se parece câmera, False caso contrário.
      - marca:     nome da câmera identificada (ex: "Blackmagic"), ou None.
      - criterio:  string descrevendo o que foi encontrado (ex: "pasta:DCIM",
                   "extensao:.braw"), ou None se não passou em nenhum critério.

    Estratégia de detecção (ordem de prioridade):
      1. Para cada assinatura na tabela ASSINATURAS_CAMERA:
         a. Verifica se alguma das pastas características existe na raiz do volume.
            → Mais rápido e mais confiável. Retorna imediatamente se encontrar.
      2. Se nenhuma pasta correspondeu: percorre os arquivos até 2 níveis de
         profundidade e compara a extensão com cada assinatura.
         → Cobre câmeras como Blackmagic que usam exFAT sem estrutura DCIM.
      3. Se ainda não encontrou nada → retorna (False, None, None).

    O limite de 2 níveis de profundidade evita que a busca fique lenta em
    volumes com muitos arquivos (ex: SSD de backup com estrutura complexa).
    """
    # Tenta listar o conteúdo da raiz do volume
    try:
        itens_raiz = os.listdir(caminho_volume)
    except OSError:
        # Não foi possível ler o volume — ignora por segurança
        return False, None, "erro_leitura"

    # Conjunto de nomes na raiz (para busca rápida sem diferenciar maiúsculas)
    # Guardamos também o nome original para o critério legível
    nomes_raiz = {item.lower(): item for item in itens_raiz}

    # ── Passo 0: verificar arquivos únicos na raiz (mais específico que pasta) ─
    # Câmeras como GoPro têm arquivos exclusivos na raiz (ex: Get_started_with_GoPro.url)
    # que identificam a marca antes de qualquer verificação de pasta genérica.
    for assinatura in ASSINATURAS_CAMERA:
        for arquivo_buscado in assinatura.get("arquivos_raiz", []):
            if arquivo_buscado.lower() in nomes_raiz:
                nome_encontrado = nomes_raiz[arquivo_buscado.lower()]
                caminho_item = os.path.join(caminho_volume, nome_encontrado)
                if os.path.isfile(caminho_item):
                    criterio = f"arquivo_raiz:{nome_encontrado}"
                    return True, assinatura["marca"], criterio

    # ── Passo 1: verificar pastas características na raiz ─────────────────────
    for assinatura in ASSINATURAS_CAMERA:
        for pasta_buscada in assinatura["pastas"]:
            # Compara sem diferenciar maiúsculas de minúsculas
            if pasta_buscada.lower() in nomes_raiz:
                nome_encontrado = nomes_raiz[pasta_buscada.lower()]
                caminho_item = os.path.join(caminho_volume, nome_encontrado)
                # Confirma que é de fato uma pasta (não um arquivo de mesmo nome)
                if os.path.isdir(caminho_item):
                    criterio = f"pasta:{nome_encontrado}"
                    return True, assinatura["marca"], criterio

    # ── Passo 2: verificar extensões nos primeiros 2 níveis de profundidade ───
    # Nível 0 = raiz do volume, nível 1 = subpastas diretas da raiz
    for item_raiz in itens_raiz:
        caminho_nivel1 = os.path.join(caminho_volume, item_raiz)

        # Arquivos soltos na raiz (nível 0)
        if os.path.isfile(caminho_nivel1):
            _, extensao = os.path.splitext(item_raiz)
            ext = extensao.lower()
            for assinatura in ASSINATURAS_CAMERA:
                if ext in assinatura["extensoes"]:
                    criterio = f"extensao:{ext}"
                    return True, assinatura["marca"], criterio

        # Subpastas de primeiro nível
        elif os.path.isdir(caminho_nivel1):
            try:
                itens_nivel2 = os.listdir(caminho_nivel1)
            except OSError:
                continue  # Não conseguiu ler a subpasta — pula

            for item_nivel2 in itens_nivel2:
                caminho_nivel2 = os.path.join(caminho_nivel1, item_nivel2)
                if os.path.isfile(caminho_nivel2):
                    _, extensao = os.path.splitext(item_nivel2)
                    ext = extensao.lower()
                    for assinatura in ASSINATURAS_CAMERA:
                        if ext in assinatura["extensoes"]:
                            criterio = f"extensao:{ext}"
                            return True, assinatura["marca"], criterio

    # Nenhum critério foi atendido
    return False, None, None


def material_tem_midia(caminho):
    """
    Verifica se uma pasta ou arquivo avulso depositado em entrada/
    contém alguma extensão de mídia reconhecida pelo GMA.

    Para a pasta de entrada somos mais permissivos: qualquer extensão
    genérica de câmera já é suficiente para aceitar o material.

    Retorna True se encontrar pelo menos um arquivo de mídia, False caso contrário.
    """
    # Se for arquivo avulso, verifica a extensão diretamente
    if os.path.isfile(caminho):
        _, extensao = os.path.splitext(caminho)
        return extensao.lower() in EXTENSOES_GENERICAS

    # Se for pasta, percorre recursivamente
    for pasta_atual, subpastas, arquivos in os.walk(caminho):
        for arquivo in arquivos:
            _, extensao = os.path.splitext(arquivo)
            if extensao.lower() in EXTENSOES_GENERICAS:
                return True

    return False


def listar_volumes_atuais():
    """
    Retorna um conjunto (set) com os nomes de todos os volumes
    montados agora em /Volumes/.

    Usa os.listdir() — sem dependências externas.
    Ignora entradas que não existam como diretório (ex: links quebrados).
    """
    try:
        entradas = os.listdir(PASTA_VOLUMES)
    except OSError:
        # Se /Volumes/ não puder ser lido, retorna vazio
        return set()

    volumes = set()
    for entrada in entradas:
        caminho = os.path.join(PASTA_VOLUMES, entrada)
        if os.path.isdir(caminho):
            volumes.add(entrada)

    return volumes


def listar_conteudo_entrada():
    """
    Retorna um conjunto (set) com os nomes de todos os itens
    (subpastas e arquivos avulsos) diretamente dentro de GMA/entrada/.

    Só olha o primeiro nível — cada subpasta é tratada como um "material"
    completo, mesmo que ela tenha muitos arquivos dentro.
    """
    try:
        itens = os.listdir(PASTA_ENTRADA)
    except OSError:
        # Se a pasta não existir ou não puder ser lida, retorna vazio
        return set()

    return set(itens)


# ── FUNÇÕES DE GERAÇÃO DE FILA ────────────────────────────────────────────────

def gerar_arquivo_fila(nome, caminho, origem, tipo_detectado, marca_camera, criterio_deteccao):
    """
    Grava um arquivo JSON na pasta fila_material/ com os dados do evento detectado.
    Esse arquivo é o "bilhete" que o Matcher vai consumir para cruzar com o formulário.

    Parâmetros:
      nome               — nome do volume ou item detectado (ex: "CARTAO_BMPCC")
      caminho            — caminho completo até o material
      origem             — "volume_fisico" ou "pasta_entrada"
      tipo_detectado     — "camera" ou "entrada_manual"
      marca_camera       — câmera identificada (ex: "Blackmagic") ou None
      criterio_deteccao  — o que determinou a identificação (ex: "pasta:Blackmagic Design")

    Formato do arquivo de saída (nome): porteiro_AAAAMMDD_HHMMSS_SSSSSS_NOME.json
    O timestamp com microssegundos garante unicidade absoluta mesmo com
    dois cartões inseridos quase ao mesmo tempo.
    """
    # Timestamp com microssegundos para unicidade absoluta
    agora = datetime.now()
    sufixo_tempo = agora.strftime("%Y%m%d_%H%M%S_%f")
    timestamp_iso = agora.strftime("%Y-%m-%dT%H:%M:%S")

    # Sanitiza o nome para uso seguro em nome de arquivo
    # (troca espaços e caracteres especiais por hífen)
    nome_seguro = "".join(
        c if c.isalnum() or c in "-_" else "-"
        for c in nome
    )

    nome_arquivo = f"porteiro_{sufixo_tempo}_{nome_seguro}.json"
    caminho_arquivo = os.path.join(PASTA_FILA, nome_arquivo)

    # Monta o dicionário no formato padronizado do GMA.
    # Os campos "status" e "form_match" são usados pelo Matcher para controle do fluxo.
    dados_evento = {
        "timestamp":          timestamp_iso,
        "origem":             origem,             # "volume_fisico" ou "pasta_entrada"
        "nome":               nome,
        "caminho":            caminho,
        "tipo_detectado":     tipo_detectado,     # "camera" ou "entrada_manual"
        "marca_camera":       marca_camera,       # ex: "Blackmagic", "Sony", None
        "criterio_deteccao":  criterio_deteccao,  # ex: "pasta:Blackmagic Design", "extensao:.braw"
        "status":             "aguardando_match",  # estado inicial para o Matcher
        "form_match":         None,               # preenchido pelo Matcher quando houver match
    }

    # Gravação segura: escreve tudo de uma vez e fecha
    with open(caminho_arquivo, "w", encoding="utf-8") as f:
        json.dump(dados_evento, f, ensure_ascii=False, indent=2)

    return caminho_arquivo, nome_arquivo


# ── FUNÇÕES DE PROCESSAMENTO DE EVENTOS ──────────────────────────────────────

def processar_novo_volume(nome_volume, logger):
    """
    Chamado quando um volume novo é detectado em /Volumes/ e o sentinela
    está ativo.

    Primeiro verifica se o volume parece ser um cartão de câmera.
    Se sim   → loga CÂMERA DETECTADA e grava o arquivo na fila_material/.
    Se não   → loga VOLUME IGNORADO e para por aqui.
    """
    caminho_volume = os.path.join(PASTA_VOLUMES, nome_volume)

    # Verifica se o volume passa nos critérios de câmera
    parece_camera, marca_camera, criterio = volume_parece_camera(caminho_volume)

    if not parece_camera:
        # Volume não identificado como câmera — ignora silenciosamente
        logger.info(
            f"VOLUME IGNORADO  | Não parece câmera | Volume: {nome_volume} | "
            f"Dica: SSDs de backup podem ser conectados normalmente"
        )
        return  # Sai da função sem criar arquivo na fila

    # Volume identificado como câmera — segue o fluxo normal
    logger.info(
        f"CÂMERA DETECTADA | Marca: {marca_camera} | Volume: {nome_volume} | "
        f"Caminho: {caminho_volume} | Critério: {criterio}"
    )

    # Grava o arquivo de fila e anota o caminho dele no log
    try:
        caminho_fila, nome_arquivo_fila = gerar_arquivo_fila(
            nome=nome_volume,
            caminho=caminho_volume,
            origem="volume_fisico",
            tipo_detectado="camera",
            marca_camera=marca_camera,
            criterio_deteccao=criterio,
        )
        logger.info(f"FILA GRAVADA     | Arquivo: {nome_arquivo_fila}")
    except Exception as erro:
        # Erro aqui não pode travar o Porteiro — apenas registra e segue
        logger.error(
            f"ERRO AO GRAVAR FILA | Volume: {nome_volume} | Erro: {erro}"
        )


def processar_novo_material_entrada(nome_item, logger):
    """
    Chamado quando um novo item (pasta ou arquivo) aparece em GMA/entrada/
    e o sentinela está ativo.

    Verifica se o material contém extensões de mídia reconhecidas.
    Se sim   → loga MATERIAL DETECTADO e grava o arquivo na fila_material/.
    Se não   → loga ENTRADA IGNORADA e para por aqui.
    """
    caminho_item = os.path.join(PASTA_ENTRADA, nome_item)

    # Verifica se o material tem algum arquivo de mídia reconhecido
    if not material_tem_midia(caminho_item):
        logger.info(
            f"ENTRADA IGNORADA | Sem mídia reconhecida | "
            f"Item: {nome_item} | Caminho: {caminho_item}"
        )
        return  # Sai sem criar arquivo na fila

    # Material tem mídia — loga e cria o bilhete na fila
    logger.info(
        f"MATERIAL DETECTADO VIA ENTRADA | Item: {nome_item} | Caminho: {caminho_item}"
    )

    try:
        caminho_fila, nome_arquivo_fila = gerar_arquivo_fila(
            nome=nome_item,
            caminho=caminho_item,
            origem="pasta_entrada",
            tipo_detectado="entrada_manual",
            marca_camera=None,       # não identificamos câmera para entrada manual
            criterio_deteccao="entrada_manual",
        )
        logger.info(f"FILA GRAVADA     | Arquivo: {nome_arquivo_fila}")
    except Exception as erro:
        logger.error(
            f"ERRO AO GRAVAR FILA | Item: {nome_item} | Erro: {erro}"
        )


def sentinela_ativo():
    """
    Retorna True se o arquivo sentinela .gma_ativo existe.
    O Porteiro só age quando esse arquivo está presente.
    """
    return os.path.isfile(SENTINELA)


# ── LOOP PRINCIPAL ────────────────────────────────────────────────────────────

def main():
    """
    Ponto de entrada do Porteiro.

    Monitora duas fontes em paralelo, a cada ciclo de polling:

    Fonte 1 — /Volumes/ (cartões físicos):
      1. Fotografa os volumes já montados ao iniciar (estado inicial).
      2. A cada ciclo, lista os volumes atuais.
      3. Volume novo → verifica se parece câmera → processa ou ignora.
      4. Volume removido → registra no log (informativo).

    Fonte 2 — GMA/entrada/ (ingestão manual):
      1. Fotografa o conteúdo da pasta ao iniciar.
      2. A cada ciclo, lista o conteúdo atual.
      3. Item novo → verifica se tem mídia → processa ou ignora.
      4. Item removido → registra no log (informativo).

    Em ambas as fontes:
      - Se o sentinela estiver ativo → processa.
      - Se não → registra que foi visto e ignorado.
      - Erro em um evento não para o loop.
    """
    logger = configurar_logger()

    logger.info(
        f"PORTEIRO INICIADO | Monitorando /Volumes/ e entrada/ "
        f"a cada {INTERVALO_POLLING}s"
    )
    logger.info(f"SENTINELA         | Caminho: {SENTINELA}")
    logger.info(f"PASTA ENTRADA     | Caminho: {PASTA_ENTRADA}")
    logger.info(f"PASTA FILA        | Caminho: {PASTA_FILA}")

    # ── Fotografia inicial: /Volumes/ ──────────────────────────────────────────
    # Volumes que JÁ estavam montados antes do Porteiro ligar são ignorados.
    volumes_conhecidos = listar_volumes_atuais()
    logger.info(
        "VOLUMES IGNORADOS | Já montados ao iniciar: "
        + (", ".join(sorted(volumes_conhecidos)) if volumes_conhecidos else "(nenhum)")
    )

    # ── Fotografia inicial: GMA/entrada/ ───────────────────────────────────────
    # Itens que JÁ estavam na pasta ao ligar o Porteiro são ignorados.
    entrada_conhecida = listar_conteudo_entrada()
    logger.info(
        "ENTRADA IGNORADA  | Já existia ao iniciar: "
        + (", ".join(sorted(entrada_conhecida)) if entrada_conhecida else "(nenhum)")
    )

    # Loop infinito — o Porteiro só para com Ctrl+C ou kill
    while True:
        try:
            # Aguarda o intervalo antes de verificar novamente
            time.sleep(INTERVALO_POLLING)

            # ── Verificação de /Volumes/ ───────────────────────────────────────
            volumes_agora = listar_volumes_atuais()

            # Volumes novos = estão agora mas não estavam antes
            volumes_novos = volumes_agora - volumes_conhecidos
            for nome_volume in sorted(volumes_novos):
                if sentinela_ativo():
                    processar_novo_volume(nome_volume, logger)
                else:
                    logger.info(
                        f"VOLUME IGNORADO  | Volume: {nome_volume} | "
                        f"Sentinela ausente — crie {SENTINELA} para ativar"
                    )

            # Volumes removidos = estavam antes mas não estão mais
            volumes_removidos = volumes_conhecidos - volumes_agora
            for nome_volume in sorted(volumes_removidos):
                logger.info(f"VOLUME REMOVIDO  | Volume: {nome_volume}")

            # Atualiza a lista de volumes conhecidos para o próximo ciclo
            volumes_conhecidos = volumes_agora

            # ── Verificação de GMA/entrada/ ────────────────────────────────────
            entrada_agora = listar_conteudo_entrada()

            # Itens novos = estão agora mas não estavam antes
            itens_novos = entrada_agora - entrada_conhecida
            for nome_item in sorted(itens_novos):
                if sentinela_ativo():
                    processar_novo_material_entrada(nome_item, logger)
                else:
                    logger.info(
                        f"ENTRADA IGNORADA | Item: {nome_item} | "
                        f"Sentinela ausente — crie {SENTINELA} para ativar"
                    )

            # Itens removidos da pasta de entrada (informativo)
            itens_removidos = entrada_conhecida - entrada_agora
            for nome_item in sorted(itens_removidos):
                logger.info(f"ENTRADA REMOVIDA | Item: {nome_item}")

            # Atualiza a lista de itens conhecidos para o próximo ciclo
            entrada_conhecida = entrada_agora

        except KeyboardInterrupt:
            # Ctrl+C: encerra de forma limpa
            logger.info("PORTEIRO ENCERRADO | Interrompido pelo operador (Ctrl+C)")
            break

        except Exception as erro:
            # Qualquer outro erro: registra e continua (nunca trava)
            logger.error(f"ERRO INESPERADO  | {erro} | Porteiro continua rodando")


# ── VERIFICAÇÃO DE DEPENDÊNCIAS E PASTAS ──────────────────────────────────────

def verificar_ambiente():
    """
    Verifica se as pastas necessárias existem e as cria se preciso.
    Roda antes do loop principal para garantir que o ambiente está pronto.

    Pastas gerenciadas:
      - logs/           — arquivo de log do Porteiro
      - fila_material/  — JSONs de material detectado aguardando o Matcher
      - entrada/        — pasta de ingestão manual (AirDrop, download, etc.)
    """
    pastas_necessarias = [
        os.path.join(RAIZ_GMA, "logs"),
        PASTA_FILA,   # fila_material do projeto ativo (isolada por projeto)
        PASTA_ENTRADA,   # pasta de ingestão manual
    ]
    for pasta in pastas_necessarias:
        os.makedirs(pasta, exist_ok=True)


# ── PONTO DE ENTRADA ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    verificar_ambiente()
    main()
