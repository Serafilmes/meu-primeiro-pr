#!/usr/bin/env python3
"""
copiador.py
Camada 2 do GMA — Motor de cópia com verificação de integridade MD5.

Responsabilidade:
  - Copiar todos os arquivos de um volume/pasta de origem para o destino.
  - Calcular e comparar MD5 de origem e destino para cada arquivo.
  - Gerar um arquivo de log .sppo (XML) compatível com gma_relatorio_pdf.py.
  - NUNCA apagar, mover ou renomear arquivos de mídia.

Princípio de segurança:
  Se a cópia de qualquer arquivo falhar, o erro é registrado e o processo
  continua com os demais. O cartão de origem NUNCA é tocado.

Uso (teste direto):
    python3 /Users/serafa/GMA/copiador.py /Volumes/Untitled "/Users/serafa/GMA/TESTE LOGAGEM/teste_direto"
    python3 /Users/serafa/GMA/copiador.py /Volumes/Untitled "/Users/serafa/GMA/TESTE LOGAGEM/teste_direto" "NOME_DO_JOB"

Pré-requisitos:
    Nenhuma dependência externa — usa apenas a biblioteca padrão do Python.
"""

import os
import sys
import hashlib
import shutil
import logging
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

# ── CONSTANTES ────────────────────────────────────────────────────────────────

# Raiz do projeto GMA
RAIZ_GMA = "/Users/serafa/GMA"

# Arquivo de log deste módulo (separado do log de transferencia.py)
ARQUIVO_LOG = os.path.join(RAIZ_GMA, "logs", "copiador.log")

# Tamanho dos blocos lidos para calcular MD5 (1 MB por bloco)
# Blocos menores usam menos memória RAM mas são mais lentos para arquivos grandes.
# 1 MB é um bom equilíbrio para arquivos de vídeo (tipicamente 1–128 GB).
TAMANHO_BLOCO_MD5 = 1024 * 1024  # 1 MB

# Arquivos que devem ser ignorados durante a cópia
# .DS_Store e Thumbs.db são metadados do SO, não fazem parte do material.
ARQUIVOS_IGNORADOS = {".DS_Store", "Thumbs.db", "desktop.ini"}

# ── POLÍTICA DE INTEGRIDADE: arquivos CRÍTICOS vs. de SISTEMA ──────────────────
#
# Decisão (2026-06-06): uma falha de cópia/MD5 num arquivo de SISTEMA do cartão
# (housekeeping de câmera — ex: .url, .log, .bk da GoPro) vira AVISO e NÃO zera a
# transferência. QUALQUER outro arquivo — TODO o footage e qualquer extensão
# desconhecida — é tratado como CRÍTICO: uma falha nele zera a transferência.
#
# Por que DENYLIST (lista de sistema) e não ALLOWLIST (lista de mídia)?
#   Porque a direção é segura: só nomes/extensões explicitamente listados aqui
#   podem ser rebaixados de FALHA para AVISO. Uma extensão de mídia nova ou
#   desconhecida cai automaticamente em "crítico" — logo, uma falha de footage
#   NUNCA é silenciada. Mantenha esta lista deliberadamente curta e explícita.
#
# NÃO incluir proxies/úteis aqui (ex: .lrv low-res e .thm thumbnail da GoPro são
# tratados como footage, portanto críticos).
EXTENSOES_SISTEMA = {".url", ".log", ".bk", ".bak", ".ini"}

# Nomes de arquivo (minúsculos) sempre considerados de sistema, independente da
# extensão. Ex: o arquivo de boas-vindas que a GoPro grava na raiz do cartão.
NOMES_SISTEMA = {"get_started_with_gopro.url"}


def eh_arquivo_sistema(nome_arquivo):
    """
    Decide se um arquivo é de SISTEMA do cartão (housekeeping disposável) e,
    portanto, NÃO-CRÍTICO para a integridade da transferência.

    Denylist conservadora: só nomes (NOMES_SISTEMA) ou extensões
    (EXTENSOES_SISTEMA) explicitamente listados contam como sistema. Todo o
    resto — incluindo footage e extensões desconhecidas — é CRÍTICO.

    Parâmetros:
      nome_arquivo — nome do arquivo (sem caminho), ex: "Get_started_with_GoPro.url"

    Retorna True se for arquivo de sistema (não-crítico), False caso contrário.
    """
    nome_lower = nome_arquivo.lower()
    if nome_lower in NOMES_SISTEMA:
        return True
    _, extensao = os.path.splitext(nome_lower)
    return extensao in EXTENSOES_SISTEMA


# ── CONFIGURAÇÃO DO LOGGER ────────────────────────────────────────────────────

def configurar_logger():
    """
    Configura o sistema de log do copiador.
    Grava em logs/copiador.log E mostra no terminal.
    Formato padrão GMA: timestamp ISO-8601 | mensagem
    """
    logger = logging.getLogger("copiador")
    logger.setLevel(logging.DEBUG)

    # Evita duplicar handlers se a função for chamada mais de uma vez
    if logger.handlers:
        return logger

    # Formato padrão do GMA: 2026-06-05T14:32:01 | mensagem
    formato = logging.Formatter(
        fmt="%(asctime)s | %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S"
    )

    # Garante que a pasta de logs existe antes de tentar criar o arquivo
    os.makedirs(os.path.dirname(ARQUIVO_LOG), exist_ok=True)

    # Handler de arquivo (append — nunca sobrescreve o histórico de logs)
    handler_arquivo = logging.FileHandler(ARQUIVO_LOG, encoding="utf-8")
    handler_arquivo.setFormatter(formato)
    logger.addHandler(handler_arquivo)

    # Handler de terminal para acompanhamento em tempo real
    handler_terminal = logging.StreamHandler()
    handler_terminal.setFormatter(formato)
    logger.addHandler(handler_terminal)

    return logger


# ── FUNÇÕES DE CHECKSUM ───────────────────────────────────────────────────────

def calcular_md5(caminho_arquivo):
    """
    Calcula o hash MD5 de um arquivo lendo em blocos de TAMANHO_BLOCO_MD5.
    Ler em blocos evita carregar arquivos de vídeo inteiros na memória RAM.

    Parâmetros:
      caminho_arquivo — caminho completo do arquivo

    Retorna a string hexadecimal do MD5 (ex: "d41d8cd98f00b204e9800998ecf8427e").
    Lança OSError se o arquivo não puder ser lido.
    """
    hasher = hashlib.md5()

    with open(caminho_arquivo, "rb") as arquivo:
        while True:
            bloco = arquivo.read(TAMANHO_BLOCO_MD5)
            if not bloco:
                break  # Chegou ao fim do arquivo
            hasher.update(bloco)

    return hasher.hexdigest()


def formatar_tamanho(bytes_val):
    """
    Converte um número de bytes em string legível (ex: "1.2 GB").

    Parâmetros:
      bytes_val — número inteiro de bytes

    Retorna string formatada.
    """
    try:
        b = float(bytes_val)
    except (ValueError, TypeError):
        return str(bytes_val)

    for unidade in ["B", "KB", "MB", "GB", "TB"]:
        if b < 1024:
            return f"{b:.1f} {unidade}"
        b /= 1024
    return f"{b:.1f} TB"


def formatar_duracao(segundos_total):
    """
    Converte segundos em string no formato HH:MM:SS.

    Parâmetros:
      segundos_total — número inteiro ou float de segundos

    Retorna string no formato "00:08:42".
    """
    segundos_total = int(segundos_total)
    horas = segundos_total // 3600
    minutos = (segundos_total % 3600) // 60
    segundos = segundos_total % 60
    return f"{horas:02d}:{minutos:02d}:{segundos:02d}"


# ── FUNÇÃO DE VARREDURA ───────────────────────────────────────────────────────

def listar_arquivos_origem(caminho_origem):
    """
    Varre a pasta de origem recursivamente e retorna a lista de todos os
    arquivos que devem ser copiados (excluindo arquivos ignorados e ocultos).

    Parâmetros:
      caminho_origem — caminho da pasta/volume a varrer

    Retorna lista de caminhos absolutos.
    """
    logger = logging.getLogger("copiador")
    arquivos_encontrados = []

    for raiz, subpastas, arquivos in os.walk(caminho_origem):
        # Remove subpastas ocultas da varredura (ex: .Spotlight-V100, .Trashes)
        # A modificação in-place da lista subpastas instrui os.walk a não entrar nelas.
        subpastas[:] = [
            s for s in subpastas
            if not s.startswith(".")
        ]

        for nome_arquivo in arquivos:
            # Pula arquivos ignorados (lista de nomes exatos)
            if nome_arquivo in ARQUIVOS_IGNORADOS:
                logger.debug(f"Ignorado: {nome_arquivo}")
                continue

            # Pula arquivos ocultos (nome começa com ponto)
            if nome_arquivo.startswith("."):
                logger.debug(f"Ignorado (oculto): {nome_arquivo}")
                continue

            caminho_completo = os.path.join(raiz, nome_arquivo)
            arquivos_encontrados.append(caminho_completo)

    return arquivos_encontrados


# ── GERAÇÃO DO LOG XML ────────────────────────────────────────────────────────

def gerar_log_xml(
    caminho_destino,
    nome_job,
    caminho_origem,
    lista_resultados,
    duracao_segundos,
    timestamp_inicio,
):
    """
    Gera o arquivo de log .sppo (XML) na pasta de destino.
    O formato é compatível com o parser parse_shotputpro_log() em gma_relatorio_pdf.py.

    Parâmetros:
      caminho_destino  — pasta onde o .sppo será salvo
      nome_job         — identificador do job (usado no nome do arquivo e no XML)
      caminho_origem   — caminho de origem para registrar no XML
      lista_resultados — lista de dicionários, um por arquivo copiado
      duracao_segundos — duração total da cópia em segundos
      timestamp_inicio — objeto datetime com o início da cópia

    Retorna o caminho completo do arquivo .sppo gerado.
    """
    logger = logging.getLogger("copiador")

    # Nome do volume de origem (último componente do caminho, ex: "Untitled")
    nome_volume = os.path.basename(caminho_origem) or caminho_origem

    # Data e hora no formato esperado pelo parser
    data_str = timestamp_inicio.strftime("%Y-%m-%d")
    hora_str = timestamp_inicio.strftime("%H:%M:%S")

    # Calcula totais para o nó <summary>.
    # "failed" conta apenas falhas CRÍTICAS (footage/desconhecidos) — é o número
    # que zera a transferência a jusante (transferencia.py lê este campo).
    # "systemWarnings" conta arquivos de SISTEMA não verificados (não-crítico).
    total_arquivos = len(lista_resultados)
    total_verificados = sum(1 for r in lista_resultados if r["verificado"])
    total_falhos = sum(
        1 for r in lista_resultados if r.get("critico", True) and not r["verificado"]
    )
    total_avisos = sum(
        1 for r in lista_resultados if not r.get("critico", True) and not r["verificado"]
    )
    tamanho_total = sum(r["tamanho_bytes"] for r in lista_resultados)

    # Velocidade média em MB/s (evita divisão por zero)
    if duracao_segundos > 0 and tamanho_total > 0:
        velocidade_mbs = (tamanho_total / 1024 / 1024) / duracao_segundos
        velocidade_str = f"{velocidade_mbs:.0f} MB/s"
    else:
        velocidade_str = "—"

    duracao_str = formatar_duracao(duracao_segundos)

    # ── Monta a árvore XML ────────────────────────────────────────────────────

    # Elemento raiz
    raiz_xml = ET.Element("report")

    # Nó <job> — informações do job
    ET.SubElement(raiz_xml, "job", attrib={
        "name":     nome_job,
        "date":     data_str,
        "time":     hora_str,
        "operator": "GMA-Automatico",
    })

    # Nó <source> — origem
    ET.SubElement(raiz_xml, "source", attrib={
        "volume": nome_volume,
        "path":   caminho_origem,
    })

    # Nó <destination> — destino
    ET.SubElement(raiz_xml, "destination", attrib={
        "path": caminho_destino,
    })

    # Nó <files> — um filho <file> por arquivo copiado
    no_arquivos = ET.SubElement(raiz_xml, "files")
    for resultado in lista_resultados:
        attrib_arquivo = {
            "src":      resultado["caminho_origem"],
            "name":     resultado["nome"],
            "size":     str(resultado["tamanho_bytes"]),
            "srcMD5":   resultado["md5_origem"],
            "dstMD5":   resultado["md5_destino"],
            "verified": "yes" if resultado["verificado"] else "no",
            # "yes" = arquivo crítico (footage); "no" = arquivo de sistema.
            # Permite ao relatório PDF mostrar falha não-crítica como AVISO.
            "critical": "yes" if resultado.get("critico", True) else "no",
        }
        # Se houve erro, registra a mensagem de erro como atributo
        if resultado.get("erro"):
            attrib_arquivo["error"] = resultado["erro"]

        ET.SubElement(no_arquivos, "file", attrib=attrib_arquivo)

    # Nó <summary> — totais
    ET.SubElement(raiz_xml, "summary", attrib={
        "totalFiles":     str(total_arquivos),
        "verified":       str(total_verificados),
        "failed":         str(total_falhos),         # apenas falhas CRÍTICAS
        "systemWarnings": str(total_avisos),         # falhas em arquivos de sistema
        "totalSize":      str(tamanho_total),
        "duration":       duracao_str,
        "speed":          velocidade_str,
    })

    # ── Serializa o XML com indentação legível ────────────────────────────────
    # ET.indent() está disponível a partir do Python 3.9.
    # Para compatibilidade com versões mais antigas, usamos uma função manual.
    _indentar_xml(raiz_xml)

    arvore = ET.ElementTree(raiz_xml)

    # Nome do arquivo: {nome_job}_{timestamp}.sppo
    timestamp_str = timestamp_inicio.strftime("%Y%m%d_%H%M%S")
    nome_arquivo_log = f"{nome_job}_{timestamp_str}.sppo"
    caminho_log = os.path.join(caminho_destino, nome_arquivo_log)

    # Escreve o arquivo com declaração XML no início
    with open(caminho_log, "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        arvore.write(f, encoding="unicode", xml_declaration=False)

    logger.info(f"LOG XML GERADO | {caminho_log}")
    return caminho_log


def _indentar_xml(elemento, nivel=0, prefixo="  "):
    """
    Adiciona indentação legível à árvore XML (compatível com Python 3.8+).
    Modifica a árvore in-place.

    Parâmetros:
      elemento — elemento raiz da árvore ET
      nivel    — nível atual de indentação (começa em 0)
      prefixo  — string usada como um nível de indentação
    """
    recuo = "\n" + (nivel * prefixo)
    recuo_filho = "\n" + ((nivel + 1) * prefixo)

    if len(elemento):  # Se o elemento tem filhos
        if not elemento.text or not elemento.text.strip():
            elemento.text = recuo_filho
        if not elemento.tail or not elemento.tail.strip():
            elemento.tail = recuo
        for filho in elemento:
            _indentar_xml(filho, nivel + 1, prefixo)
        # O último filho tem recuo do nível pai (para fechar o bloco corretamente)
        if not filho.tail or not filho.tail.strip():
            filho.tail = recuo
    else:
        if nivel > 0 and (not elemento.tail or not elemento.tail.strip()):
            elemento.tail = recuo


# ── FUNÇÃO PRINCIPAL DE CÓPIA ─────────────────────────────────────────────────

def copiar(caminho_origem, caminho_destino, nome_job=""):
    """
    Executa a cópia completa com verificação MD5 de todos os arquivos da origem.

    Fluxo para cada arquivo:
      1. Calcula MD5 da origem
      2. Copia para o destino mantendo a estrutura de subpastas e timestamps
      3. Calcula MD5 do destino
      4. Compara os dois MD5s — divergência marca como falha

    Ao final, gera o arquivo de log .sppo na pasta de destino.

    Parâmetros:
      caminho_origem  — pasta ou volume de origem (ex: /Volumes/Untitled)
      caminho_destino — pasta de destino já criada (ex: .../PRODUTORA_X_001)
      nome_job        — identificador do job para o log (padrão: nome da pasta destino)

    Retorna um dicionário com os resultados da cópia:
      "ok"                  — True se todos os checksums bateram
      "caminho_log"         — caminho do arquivo .sppo gerado
      "total_arquivos"      — número total de arquivos processados
      "total_verificados"   — número de arquivos com checksum OK
      "total_falhos"        — número de arquivos com falha de checksum
      "tamanho_total_bytes" — soma dos tamanhos em bytes
      "duracao_segundos"    — duração total em segundos
      "arquivos"            — lista de dicionários, um por arquivo
    """
    logger = configurar_logger()

    # Se nome_job não foi fornecido, usa o nome da pasta de destino
    if not nome_job:
        nome_job = os.path.basename(caminho_destino)

    timestamp_inicio = datetime.now()
    logger.info(
        f"CÓPIA INICIADA | Job: {nome_job} | "
        f"Origem: {caminho_origem} | Destino: {caminho_destino}"
    )

    # ── Validações iniciais ───────────────────────────────────────────────────

    if not os.path.isdir(caminho_origem):
        logger.error(f"ORIGEM NÃO ENCONTRADA | {caminho_origem}")
        return _resultado_falha(nome_job, "Pasta de origem não encontrada")

    if not os.path.isdir(caminho_destino):
        logger.error(f"DESTINO NÃO ENCONTRADO | {caminho_destino}")
        return _resultado_falha(nome_job, "Pasta de destino não encontrada")

    # ── Varredura dos arquivos de origem ─────────────────────────────────────

    logger.info(f"VARRENDO ORIGEM | {caminho_origem}")
    lista_arquivos_origem = listar_arquivos_origem(caminho_origem)
    total = len(lista_arquivos_origem)

    if total == 0:
        logger.warning(f"ORIGEM VAZIA | Nenhum arquivo encontrado em {caminho_origem}")
        # Gera log vazio mas não considera falha — pode ser intencional
        caminho_log = gerar_log_xml(
            caminho_destino, nome_job, caminho_origem, [], 0, timestamp_inicio
        )
        return {
            "ok": True,
            "caminho_log": caminho_log,
            "total_arquivos": 0,
            "total_verificados": 0,
            "total_falhos": 0,
            "total_avisos": 0,
            "tamanho_total_bytes": 0,
            "duracao_segundos": 0,
            "arquivos": [],
        }

    logger.info(f"ARQUIVOS ENCONTRADOS | {total} arquivo(s) para copiar")

    # ── Loop de cópia ─────────────────────────────────────────────────────────

    lista_resultados = []
    tempo_copia_inicio = time.time()

    for indice, caminho_arquivo_origem in enumerate(lista_arquivos_origem, start=1):
        nome_arquivo = os.path.basename(caminho_arquivo_origem)

        # Tamanho do arquivo para log de progresso
        try:
            tamanho_bytes = os.path.getsize(caminho_arquivo_origem)
        except OSError:
            tamanho_bytes = 0

        tamanho_legivel = formatar_tamanho(tamanho_bytes)
        logger.info(f"Copiando {indice}/{total}: {nome_arquivo} ({tamanho_legivel})")

        # Monta o caminho de destino preservando a estrutura de subpastas.
        # Ex: origem=/Volumes/SD/DCIM/100GOPRO/GOPR0001.MP4
        #    destino=/GMA/.../PRODUTORA_X_001/DCIM/100GOPRO/GOPR0001.MP4
        caminho_relativo = os.path.relpath(caminho_arquivo_origem, caminho_origem)
        caminho_arquivo_destino = os.path.join(caminho_destino, caminho_relativo)
        pasta_pai_destino = os.path.dirname(caminho_arquivo_destino)

        resultado_arquivo = {
            "nome":            nome_arquivo,
            "caminho_origem":  caminho_arquivo_origem,
            "caminho_destino": caminho_arquivo_destino,
            "tamanho_bytes":   tamanho_bytes,
            "md5_origem":      "",
            "md5_destino":     "",
            "verificado":      False,
            # Crítico = footage e qualquer coisa não listada como sistema.
            # Uma falha em arquivo crítico zera a transferência; em arquivo de
            # sistema vira só AVISO. Ver eh_arquivo_sistema() e a política acima.
            "critico":         not eh_arquivo_sistema(nome_arquivo),
            "erro":            "",
        }

        # ── Verifica se o arquivo já existe no destino ────────────────────────
        if os.path.isfile(caminho_arquivo_destino):
            aviso = f"ARQUIVO JÁ EXISTE NO DESTINO — pulando | {caminho_arquivo_destino}"
            logger.warning(aviso)
            resultado_arquivo["erro"] = "Arquivo já existia no destino — não sobrescrito"
            # Ainda tenta verificar o MD5 do existente para registrar no log
            try:
                resultado_arquivo["md5_destino"] = calcular_md5(caminho_arquivo_destino)
            except OSError:
                pass
            lista_resultados.append(resultado_arquivo)
            continue

        # ── Passo 1: MD5 da origem ────────────────────────────────────────────
        try:
            md5_origem = calcular_md5(caminho_arquivo_origem)
            resultado_arquivo["md5_origem"] = md5_origem
        except OSError as erro:
            msg_erro = f"Erro ao calcular MD5 da origem: {erro}"
            logger.error(f"ERRO MD5 ORIGEM | {nome_arquivo} | {erro}")
            resultado_arquivo["erro"] = msg_erro
            lista_resultados.append(resultado_arquivo)
            continue  # Não tenta copiar — passa para o próximo arquivo

        # ── Passo 2: Cria subpastas e copia o arquivo ─────────────────────────
        try:
            os.makedirs(pasta_pai_destino, exist_ok=True)
            try:
                # copy2 preserva timestamps — preferido para arquivos de mídia
                shutil.copy2(caminho_arquivo_origem, caminho_arquivo_destino)
            except OSError as erro_copy2:
                # Fallback: câmeras GoPro e similares têm arquivos de sistema
                # (.url, .log, .bk) cujas flags/xattrs o copy2 não consegue copiar.
                # copyfile copia só os dados — suficiente para esses arquivos.
                logger.warning(
                    f"copy2 falhou em {nome_arquivo} ({erro_copy2}) — "
                    f"tentando copyfile como fallback"
                )
                shutil.copyfile(caminho_arquivo_origem, caminho_arquivo_destino)
        except OSError as erro:
            msg_erro = f"Erro ao copiar arquivo: {erro}"
            logger.error(f"ERRO NA CÓPIA | {nome_arquivo} | {erro}")
            resultado_arquivo["erro"] = msg_erro
            lista_resultados.append(resultado_arquivo)
            continue

        # ── Passo 3: MD5 do destino ───────────────────────────────────────────
        try:
            md5_destino = calcular_md5(caminho_arquivo_destino)
            resultado_arquivo["md5_destino"] = md5_destino
        except OSError as erro:
            msg_erro = f"Erro ao calcular MD5 do destino: {erro}"
            logger.error(f"ERRO MD5 DESTINO | {nome_arquivo} | {erro}")
            resultado_arquivo["erro"] = msg_erro
            lista_resultados.append(resultado_arquivo)
            continue

        # ── Passo 4: Compara os MD5s ──────────────────────────────────────────
        if md5_origem == md5_destino:
            resultado_arquivo["verificado"] = True
            logger.info(f"[{indice}/{total}] {nome_arquivo} — {tamanho_legivel} — MD5 OK")
        else:
            resultado_arquivo["verificado"] = False
            resultado_arquivo["erro"] = "MD5 divergente entre origem e destino"
            logger.error(
                f"!!! FALHA MD5 !!! {nome_arquivo} — "
                f"origem: {md5_origem} | destino: {md5_destino}"
            )

        lista_resultados.append(resultado_arquivo)

    # ── Totais finais ─────────────────────────────────────────────────────────

    tempo_copia_fim = time.time()
    duracao_segundos = tempo_copia_fim - tempo_copia_inicio

    total_verificados = sum(1 for r in lista_resultados if r["verificado"])
    # Falhas CRÍTICAS: arquivos críticos (footage/desconhecidos) que NÃO verificaram.
    # São essas que zeram a transferência.
    total_falhos = sum(
        1 for r in lista_resultados if r["critico"] and not r["verificado"]
    )
    # AVISOS: arquivos de SISTEMA que não verificaram — não zeram a transferência.
    total_avisos = sum(
        1 for r in lista_resultados if not r["critico"] and not r["verificado"]
    )
    tamanho_total = sum(r["tamanho_bytes"] for r in lista_resultados)
    copia_ok = (total_falhos == 0)

    # ── Gera o log XML ────────────────────────────────────────────────────────

    caminho_log = gerar_log_xml(
        caminho_destino=caminho_destino,
        nome_job=nome_job,
        caminho_origem=caminho_origem,
        lista_resultados=lista_resultados,
        duracao_segundos=duracao_segundos,
        timestamp_inicio=timestamp_inicio,
    )

    # ── Log resumo final ──────────────────────────────────────────────────────

    # Sufixo de aviso para os logs, quando há arquivos de sistema não verificados.
    sufixo_avisos = (
        f" | {total_avisos} arquivo(s) de sistema com aviso (não-crítico)"
        if total_avisos else ""
    )

    if copia_ok:
        logger.info(
            f"CÓPIA CONCLUÍDA COM SUCESSO | Job: {nome_job} | "
            f"{total_verificados}/{total} arquivos verificados | "
            f"Total: {formatar_tamanho(tamanho_total)} | "
            f"Duração: {formatar_duracao(duracao_segundos)}{sufixo_avisos}"
        )
    else:
        logger.error(
            f"CÓPIA CONCLUÍDA COM FALHAS | Job: {nome_job} | "
            f"{total_falhos} arquivo(s) crítico(s) com falha | "
            f"{total_verificados}/{total} OK{sufixo_avisos} | "
            f"Verifique o log: {caminho_log}"
        )

    return {
        "ok":                  copia_ok,
        "caminho_log":         caminho_log,
        "total_arquivos":      total,
        "total_verificados":   total_verificados,
        "total_falhos":        total_falhos,
        "total_avisos":        total_avisos,
        "tamanho_total_bytes": tamanho_total,
        "duracao_segundos":    duracao_segundos,
        "arquivos":            lista_resultados,
    }


# ── FUNÇÃO AUXILIAR DE RESULTADO FALHA ───────────────────────────────────────

def _resultado_falha(nome_job, motivo):
    """
    Retorna um dicionário de resultado padronizado para casos de falha total
    (quando a cópia nem começa — ex: origem não encontrada).

    Parâmetros:
      nome_job — identificador do job
      motivo   — descrição textual da falha

    Retorna o dicionário de resultado com ok=False e caminho_log vazio.
    """
    logger = logging.getLogger("copiador")
    logger.error(f"FALHA TOTAL | Job: {nome_job} | {motivo}")
    return {
        "ok":                  False,
        "caminho_log":         "",
        "total_arquivos":      0,
        "total_verificados":   0,
        "total_falhos":        0,
        "total_avisos":        0,
        "tamanho_total_bytes": 0,
        "duracao_segundos":    0,
        "arquivos":            [],
    }


# ── PONTO DE ENTRADA (TESTE DIRETO) ──────────────────────────────────────────

def main():
    """
    Permite testar o copiador diretamente na linha de comando:

        python3 copiador.py <origem> <destino> [nome_job]

    Exemplos:
        python3 copiador.py /Volumes/Untitled "/Users/serafa/GMA/TESTE LOGAGEM/teste_direto"
        python3 copiador.py /Volumes/Untitled "/Users/serafa/GMA/TESTE LOGAGEM/teste_direto" "PROD_X_001"
    """
    configurar_logger()
    logger = logging.getLogger("copiador")

    if len(sys.argv) < 3:
        print("")
        print("Uso:    python3 copiador.py <origem> <destino> [nome_job]")
        print("")
        print("Exemplos:")
        print('  python3 copiador.py /Volumes/Untitled "/Users/serafa/GMA/TESTE LOGAGEM/teste_direto"')
        print('  python3 copiador.py /Volumes/Untitled "/Users/serafa/GMA/TESTE LOGAGEM/teste_direto" "PROD_X_001"')
        print("")
        sys.exit(1)

    caminho_origem = sys.argv[1]
    caminho_destino = sys.argv[2]
    nome_job = sys.argv[3] if len(sys.argv) >= 4 else ""

    # Cria a pasta de destino se não existir
    if not os.path.isdir(caminho_destino):
        logger.info(f"Criando pasta de destino: {caminho_destino}")
        try:
            os.makedirs(caminho_destino, exist_ok=True)
        except OSError as erro:
            logger.error(f"Não foi possível criar a pasta de destino: {erro}")
            sys.exit(1)

    # Executa a cópia
    resultado = copiar(
        caminho_origem=caminho_origem,
        caminho_destino=caminho_destino,
        nome_job=nome_job,
    )

    # Exibe o resumo final no terminal
    print("")
    print("=" * 60)
    print(f"  RESULTADO DA CÓPIA: {'OK' if resultado['ok'] else 'FALHA'}")
    print("=" * 60)
    print(f"  Arquivos processados : {resultado['total_arquivos']}")
    print(f"  Verificados (MD5 OK) : {resultado['total_verificados']}")
    print(f"  Falhas críticas      : {resultado['total_falhos']}")
    print(f"  Avisos (sistema)     : {resultado.get('total_avisos', 0)}")
    print(f"  Tamanho total        : {formatar_tamanho(resultado['tamanho_total_bytes'])}")
    print(f"  Duração              : {formatar_duracao(resultado['duracao_segundos'])}")
    print(f"  Log XML              : {resultado['caminho_log']}")
    print("=" * 60)
    print("")

    # Código de saída: 0 = sucesso, 1 = falha (útil para scripts)
    sys.exit(0 if resultado["ok"] else 1)


if __name__ == "__main__":
    main()
