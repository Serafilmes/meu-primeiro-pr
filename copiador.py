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
import json
import hashlib
import shutil
import logging
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

# ── CONSTANTES ────────────────────────────────────────────────────────────────

# Raiz do projeto GMA
RAIZ_GMA = "/Users/serafa/GMA"

# Classificador de extensão e ponte proxy→clipe — fonte ÚNICA da identidade do
# tipo de arquivo (VIDEO/FOTO/AUDIO/PROXY/OUTRO). Usar ler_cartao aqui evita uma
# segunda tabela de extensões divergente dentro do copiador.
sys.path.insert(0, RAIZ_GMA)
import ler_cartao

# Arquivo de log deste módulo (separado do log de transferencia.py)
ARQUIVO_LOG = os.path.join(RAIZ_GMA, "logs", "copiador.log")

# Bilhete de progresso da cópia AO VIVO — a aba Mural lê este arquivo para mostrar
# a velocidade em tempo real (estilo ShotPut). Mesma técnica do bilhete do
# exportador Sheets: escreve num .tmp e os.replace (troca atômica), para a tela
# nunca ler pela metade. É SEMPRE best-effort — falhar aqui NUNCA derruba a cópia
# (princípio nº2: o indicador jamais põe a mídia em risco). Só observa bytes que já
# estão sendo lidos para o MD5; não toca, move nem apaga nada.
ARQUIVO_STATUS_COPIA = os.path.join(RAIZ_GMA, ".gma_copia_status.json")

# Tamanho dos blocos lidos para calcular MD5 (1 MB por bloco)
# Blocos menores usam menos memória RAM mas são mais lentos para arquivos grandes.
# 1 MB é um bom equilíbrio para arquivos de vídeo (tipicamente 1–128 GB).
TAMANHO_BLOCO_MD5 = 1024 * 1024  # 1 MB

# O QUE NÃO É MATERIAL (lixo do SO/cartão/GMA + download) é decidido pela RÉGUA
# ÚNICA em ler_cartao.eh_pasta_ignorada / eh_nao_midia — a MESMA que a auditoria
# (C4) usa, para a contagem da origem e a do destino baterem sempre.

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

class MedidorProgresso:
    """
    Acompanha o andamento de UMA cópia e publica um 'bilhete'
    (.gma_copia_status.json) que a aba Mural lê para mostrar a velocidade em tempo
    real. NÃO toca em mídia — só conta bytes que já estão sendo lidos para o MD5.

    Tudo aqui é best-effort: qualquer erro ao medir ou publicar é engolido e a
    cópia segue intacta. O medidor jamais pode ser a causa de uma transferência
    falhar (princípio nº2).

    Como mede: o copiador lê cada arquivo DUAS vezes para o MD5 (origem + destino),
    em blocos de 1 MB. A cada bloco lido, somamos os bytes. O "trabalho total" é,
    portanto, 2× o tamanho do material. A barra anda por esse trabalho de leitura
    (suave, porque cobre ~2/3 do tempo de cada arquivo); a velocidade é a taxa de
    leitura recente (o pulso de MB/s que se vê na tela).
    """

    INTERVALO_PUBLICACAO = 0.5  # segundos entre bilhetes (não escreve a cada bloco)

    def __init__(self, nome_job, total_arquivos, bytes_total):
        self.nome_job = nome_job
        self.total_arquivos = total_arquivos
        self.bytes_total = max(int(bytes_total), 1)     # evita divisão por zero
        self.trabalho_total = self.bytes_total * 2      # lê cada arquivo 2x (origem+destino)
        self.bytes_lidos = 0                            # progresso de leitura acumulado
        self.indice_atual = 0
        self.nome_atual = ""
        self.t_inicio = time.time()
        self._ultimo_publicado = 0.0
        self._bytes_no_ultimo = 0
        self._t_ultimo = self.t_inicio
        self.velocidade_mbs = 0.0

    def novo_arquivo(self, indice, nome):
        """Marca o início de um arquivo (atualiza o 'arquivo X de Y' e publica)."""
        self.indice_atual = indice
        self.nome_atual = nome
        self._publicar(forcar=True)

    def somar_bytes(self, n):
        """Callback passado ao calcular_md5: chamado a cada bloco de 1 MB lido."""
        self.bytes_lidos += n
        self._publicar()

    def _publicar(self, forcar=False):
        agora = time.time()
        if not forcar and (agora - self._ultimo_publicado) < self.INTERVALO_PUBLICACAO:
            return
        try:
            # Velocidade instantânea: bytes lidos desde o último bilhete ÷ tempo.
            dt = agora - self._t_ultimo
            if dt > 0:
                bytes_recentes = self.bytes_lidos - self._bytes_no_ultimo
                self.velocidade_mbs = (bytes_recentes / dt) / (1024 * 1024)
            self._bytes_no_ultimo = self.bytes_lidos
            self._t_ultimo = agora
            self._ultimo_publicado = agora

            frac = min(self.bytes_lidos / self.trabalho_total, 1.0)
            # Tempo restante pela média desde o início (mais estável que a janela).
            decorrido = agora - self.t_inicio
            media_bps = (self.bytes_lidos / decorrido) if decorrido > 0 else 0
            restante_bytes = max(self.trabalho_total - self.bytes_lidos, 0)
            restante_seg = (restante_bytes / media_bps) if media_bps > 0 else 0

            self._escrever({
                "estado": "copiando",
                "job": self.nome_job,
                "arquivo_indice": self.indice_atual,
                "arquivo_total": self.total_arquivos,
                "nome_atual": self.nome_atual,
                "percentual": round(frac * 100, 1),
                "velocidade_mbs": round(max(self.velocidade_mbs, 0.0), 1),
                "restante_seg": int(restante_seg),
                "bytes_total": self.bytes_total,
                "quando": agora,
            })
        except Exception:
            pass  # best-effort: nunca derruba a cópia

    def finalizar(self):
        """Marca o fim da cópia: a tela deixa de mostrar a faixa de velocidade."""
        try:
            self._escrever({"estado": "ocioso", "quando": time.time()})
        except Exception:
            pass

    @staticmethod
    def _escrever(dados):
        tmp = ARQUIVO_STATUS_COPIA + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(dados, f, ensure_ascii=False)
        os.replace(tmp, ARQUIVO_STATUS_COPIA)  # troca atômica — a tela nunca lê pela metade


def calcular_md5(caminho_arquivo, ao_ler=None):
    """
    Calcula o hash MD5 de um arquivo lendo em blocos de TAMANHO_BLOCO_MD5.
    Ler em blocos evita carregar arquivos de vídeo inteiros na memória RAM.

    Parâmetros:
      caminho_arquivo — caminho completo do arquivo
      ao_ler — função opcional chamada a cada bloco com o nº de bytes lidos
               (usada pelo MedidorProgresso para a velocidade ao vivo). Quando
               None, o comportamento é exatamente o de antes — custo zero.

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
            if ao_ler is not None:
                ao_ler(len(bloco))

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
        # Poda as pastas que a régua única manda ignorar (ocultas como
        # .Spotlight-V100/.Trashes, lixo __MACOSX, pastas do GMA _GMA_frames).
        # A modificação in-place instrui o os.walk a não entrar nelas.
        subpastas[:] = [
            s for s in subpastas
            if not ler_cartao.eh_pasta_ignorada(s)
        ]

        for nome_arquivo in arquivos:
            # Régua única: pula tudo que não é material (lixo do SO/cartão/GMA
            # e download incompleto). Footage desconhecido nunca cai aqui.
            if ler_cartao.eh_nao_midia(nome_arquivo):
                logger.debug(f"Ignorado (não-mídia): {nome_arquivo}")
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
    # Proxies copiados (não contam como vídeo) — informativo para o relatório.
    total_proxies = sum(1 for r in lista_resultados if r.get("tipo") == "PROXY")
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
            # Tipo honesto do arquivo (video/foto/audio/proxy/outro). O relatório e
            # o banco usam isto para tratar o proxy como derivado, não como vídeo.
            "kind":     (resultado.get("tipo") or "OUTRO").lower(),
        }
        # Se for proxy, registra o clipe principal a que ele pertence (pista por nome).
        if resultado.get("proxy_de"):
            attrib_arquivo["proxyOf"] = resultado["proxy_de"]
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
        "proxies":        str(total_proxies),        # proxies copiados (não são vídeo)
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
            "total_proxies": 0,
            "tamanho_total_bytes": 0,
            "duracao_segundos": 0,
            "arquivos": [],
        }

    logger.info(f"ARQUIVOS ENCONTRADOS | {total} arquivo(s) para copiar")

    # ── Medidor de velocidade AO VIVO (best-effort, não toca em mídia) ─────────
    # Soma os tamanhos uma vez para a barra/tempo restante; um getsize que falhe
    # apenas subestima o total — nunca interrompe a cópia.
    bytes_total_estimado = 0
    for _caminho in lista_arquivos_origem:
        try:
            bytes_total_estimado += os.path.getsize(_caminho)
        except OSError:
            pass
    medidor = MedidorProgresso(nome_job, total, bytes_total_estimado)

    # ── Loop de cópia ─────────────────────────────────────────────────────────

    lista_resultados = []
    tempo_copia_inicio = time.time()

    for indice, caminho_arquivo_origem in enumerate(lista_arquivos_origem, start=1):
        nome_arquivo = os.path.basename(caminho_arquivo_origem)
        medidor.novo_arquivo(indice, nome_arquivo)

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

        # Classificação honesta do tipo (Fatia B): VIDEO/FOTO/AUDIO/PROXY/OUTRO.
        # O proxy (ex.: .LRV da GoPro) é SEMPRE copiado — pular a cópia deixaria o
        # cartão com arquivos que nunca foram verificados, e a Camada 4 liberaria
        # o embaralhamento (Parashoot) apagando material não copiado. Em vez de
        # pular, MARCAMOS o proxy e o ligamos ao clipe principal: assim ele não
        # conta como vídeo nem gera frames lá na frente, mas a cópia fica completa.
        tipo_arquivo = ler_cartao.classificar_extensao(nome_arquivo)
        proxy_de = ler_cartao.proxy_do_clipe(nome_arquivo) if tipo_arquivo == "PROXY" else None

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
            # O proxy é crítico (footage derivado) — copiado e verificado como tal.
            "critico":         not eh_arquivo_sistema(nome_arquivo),
            # Tipo do arquivo e, se for proxy, o nome do clipe principal a que ele
            # pertence (pista por nome; o Matcher segue sendo a autoridade).
            "tipo":            tipo_arquivo,
            "proxy_de":        proxy_de,
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
            md5_origem = calcular_md5(caminho_arquivo_origem, ao_ler=medidor.somar_bytes)
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
            md5_destino = calcular_md5(caminho_arquivo_destino, ao_ler=medidor.somar_bytes)
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

    medidor.finalizar()  # bilhete volta a "ocioso" — a faixa de velocidade some da tela

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
    # PROXIES: derivados de baixa resolução (ex.: .LRV) copiados junto. São SEMPRE
    # copiados e verificados como footage; aqui só os contamos para avisar o
    # operador — eles não contam como vídeo nem geram frames lá na frente.
    total_proxies = sum(1 for r in lista_resultados if r.get("tipo") == "PROXY")
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

    # Aviso de proxy: copiados e marcados, ligados aos clipes principais.
    if total_proxies:
        logger.info(
            f"PROXY | {total_proxies} arquivo(s) de proxy copiado(s) e marcado(s) "
            f"(ligados aos clipes; não contam como vídeo nem geram frames)"
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
        "total_proxies":       total_proxies,
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
        "total_proxies":       0,
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
