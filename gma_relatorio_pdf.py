#!/usr/bin/env python3
"""
gma_relatorio_pdf.py  —  versão 2
Gera relatório PDF rico de transferência de mídia.

Estrutura do PDF (paisagem, letter):
  Parte 1 — Cabeçalho com resumo em 3 colunas (tamanho/integridade | tempo | dados do profissional)
  Parte 2 — Folha de contato: um bloco por arquivo de mídia com thumbnails + metadados
  Parte 3 — Tabela completa de todos os arquivos (inclusive sistema) com checksums

Dependências:
    pip install reportlab Pillow
    brew install ffmpeg exiftool

Uso direto (teste):
    python3 gma_relatorio_pdf.py caminho/para/log.sppo

API usada pelo transferencia.py:
    from gma_relatorio_pdf import parse_shotputpro_log, gerar_pdf
    dados = parse_shotputpro_log(caminho_log)
    gerar_pdf(dados, caminho_pdf, dados_match={"nome": "...", "camera": "...", ...})
"""

import xml.etree.ElementTree as ET
import sys
import os
import json
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

try:
    from reportlab.lib.pagesizes import letter, landscape
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer,
        Table, TableStyle, HRFlowable, PageBreak, KeepTogether,
    )
    from reportlab.platypus import Image as RLImage
    from reportlab.lib.enums import TA_CENTER, TA_LEFT
except ImportError:
    print("ERRO: reportlab não instalado. Execute: pip install reportlab")
    sys.exit(1)

try:
    from PIL import Image as PILImage
    PILLOW_DISPONIVEL = True
except ImportError:
    PILLOW_DISPONIVEL = False


# ── CAMINHOS DAS FERRAMENTAS EXTERNAS ────────────────────────────────────────

FFPROBE  = "/opt/homebrew/bin/ffprobe"
FFMPEG   = "/opt/homebrew/bin/ffmpeg"
EXIFTOOL = "/opt/homebrew/bin/exiftool"


# ── CORES DA IDENTIDADE GMA ───────────────────────────────────────────────────

COR_PRIMARIA     = colors.HexColor("#1D9E75")   # verde teal
COR_TITULO       = colors.HexColor("#2C2C2A")   # quase-preto
COR_MUTED        = colors.HexColor("#5F5E5A")   # cinza médio
COR_SUCESSO      = colors.HexColor("#1D9E75")
COR_ERRO         = colors.HexColor("#E24B4A")
COR_AVISO        = colors.HexColor("#B26A00")
COR_FUNDO_ALT    = colors.HexColor("#F1EFE8")   # bege claro (linhas alternadas)
COR_BORDA        = colors.HexColor("#D3D1C7")
COR_FUNDO_HEADER = colors.HexColor("#F7F6F2")   # cinza quase-branco


# ── LAYOUT (paisagem letter) ──────────────────────────────────────────────────

# Margens: 1.5 cm cada lado
MARGEM = 1.5 * cm

# Largura útil: 792 (letter landscape) − 2 × margem
LARGURA_UTIL = landscape(letter)[0] - 2 * MARGEM   # ≈ 707 pts

# Coluna de metadados na Parte 2
COL_META_LARGURA = 195  # pts

# Coluna do filmstrip: o restante
COL_FILMSTRIP_LARGURA = LARGURA_UTIL - COL_META_LARGURA

# Altura máxima de um thumbnail
THUMB_ALTURA_MAX = 108  # pts (~3,8 cm)


# ── CLASSIFICAÇÃO DE ARQUIVOS ─────────────────────────────────────────────────

# Extensões consideradas mídia de captação principal
EXT_VIDEO = {'.mp4', '.mov', '.mxf', '.avi', '.mkv', '.mts', '.m4v',
             '.r3d', '.braw', '.ari', '.m2ts'}
EXT_FOTO  = {'.jpg', '.jpeg', '.png', '.tif', '.tiff', '.dng',
             '.cr2', '.cr3', '.nef', '.raf', '.arw', '.rw2', '.gpr'}

# Proxies GoPro: usados como fonte de thumbnails, não aparecem na folha de contato
EXT_PROXY_VIDEO = {'.lrv'}
EXT_PROXY_FOTO  = {'.thm'}


def classificar_arquivo(nome):
    """
    Classifica um arquivo pela extensão.
    Retorna: 'video' | 'foto' | 'proxy_video' | 'proxy_foto' | 'outro'
    """
    ext = Path(nome).suffix.lower()
    if ext in EXT_VIDEO:        return 'video'
    if ext in EXT_FOTO:         return 'foto'
    if ext in EXT_PROXY_VIDEO:  return 'proxy_video'
    if ext in EXT_PROXY_FOTO:   return 'proxy_foto'
    return 'outro'


def eh_midia(nome):
    """True se o arquivo é mídia de captação (vídeo ou foto principal — não proxy)."""
    return classificar_arquivo(nome) in ('video', 'foto')


# ── UTILITÁRIOS ───────────────────────────────────────────────────────────────

def formatar_tamanho(bytes_val):
    """Converte bytes para string legível (KB, MB, GB, TB)."""
    try:
        b = int(bytes_val)
    except (ValueError, TypeError):
        return str(bytes_val)
    for unidade in ["B", "KB", "MB", "GB", "TB"]:
        if b < 1024:
            return f"{b:.1f} {unidade}"
        b /= 1024
    return f"{b:.1f} TB"


def formatar_duracao(segundos):
    """Converte segundos (float) para string HH:MM:SS ou MM:SS."""
    try:
        s = int(float(segundos))
        h, resto = divmod(s, 3600)
        m, s = divmod(resto, 60)
        if h > 0:
            return f"{h:02d}:{m:02d}:{s:02d}"
        return f"{m:02d}:{s:02d}"
    except (ValueError, TypeError):
        return "—"


def buscar(elemento, *tags):
    """Busca um atributo em múltiplos nomes possíveis."""
    for tag in tags:
        v = elemento.get(tag)
        if v is not None:
            return v
    return ""


def caminho_destino_arquivo(src_path, source_root, pasta_destino):
    """
    Reconstrói o caminho de destino de um arquivo a partir do caminho de origem.

    Exemplo:
      src_path     = "/Volumes/Untitled/DCIM/100GOPRO/GX019385.MP4"
      source_root  = "/Volumes/Untitled"
      pasta_destino = "/GMA/TESTE LOGAGEM/.../NOME_001"
      → "/GMA/TESTE LOGAGEM/.../NOME_001/DCIM/100GOPRO/GX019385.MP4"
    """
    if src_path and source_root and pasta_destino:
        caminho_relativo = src_path[len(source_root):].lstrip('/')
        return os.path.join(pasta_destino, caminho_relativo)
    # Fallback: só pelo nome do arquivo
    nome = os.path.basename(src_path) if src_path else ""
    return os.path.join(pasta_destino, nome) if pasta_destino else nome


# ── PARSER DO LOG .sppo ───────────────────────────────────────────────────────

def parse_shotputpro_log(caminho_log):
    """
    Parseia o log XML .sppo gerado pelo copiador.py (ou pelo ShotPutPro).

    Retorna dicionário com:
      nome_job, data, hora, operador
      origem (nome do volume), source_root (caminho completo)
      destinos (lista de caminhos de destino)
      arquivos: lista de dicts —
        nome, src_path, tamanho, checksum_src, checksum_dst, ok, critico
      total_arquivos, total_verificados, total_falhos, total_avisos
      tamanho_total, duracao, velocidade
    """
    try:
        tree = ET.parse(caminho_log)
    except ET.ParseError as e:
        print(f"ERRO ao ler XML: {e}")
        sys.exit(1)

    root = tree.getroot()

    dados = {
        "nome_job":          "",
        "data":              "",
        "hora":              "",
        "operador":          "",
        "origem":            "",
        "source_root":       "",   # caminho completo da origem (ex: /Volumes/Untitled)
        "destinos":          [],
        "arquivos":          [],
        "total_arquivos":    0,
        "total_verificados": 0,
        "total_falhos":      0,
        "total_avisos":      0,
        "total_proxies":     0,
        "tamanho_total":     0,
        "duracao":           "",
        "velocidade":        "",
    }

    # Cabeçalho do job
    # ATENÇÃO: ElementTree retorna False para elementos sem filhos (tag auto-fechada).
    # Por isso usamos "is not None" em vez de "or" — o or pularia para o próximo.
    job = root.find("job")
    if job is None:
        job = root.find("Job")
    if job is None:
        job = root
    if job is not None:
        dados["nome_job"] = buscar(job, "name", "Name", "jobName") or "Sem nome"
        dados["data"]     = buscar(job, "date", "Date")
        dados["hora"]     = buscar(job, "time", "Time")
        dados["operador"] = buscar(job, "operator", "Operator", "user")

    # Origem: salva tanto o nome do volume quanto o caminho completo
    origem = root.find(".//source")
    if origem is None:
        origem = root.find(".//Source")
    if origem is not None:
        dados["origem"]      = (buscar(origem, "volume", "Volume", "name", "Name")
                                or buscar(origem, "path", "Path"))
        dados["source_root"] = buscar(origem, "path", "Path") or ""

    # Destinos
    for dest in root.findall(".//destination") + root.findall(".//Destination"):
        p = buscar(dest, "path", "Path", "volume", "Volume")
        if p:
            dados["destinos"].append(p)

    # Arquivos individuais
    for arq in root.findall(".//file") + root.findall(".//File"):
        src_path   = buscar(arq, "src", "Src", "source", "Source", "path")
        nome       = os.path.basename(src_path) if src_path else buscar(arq, "name", "Name")
        tamanho    = buscar(arq, "size", "Size", "fileSize") or "0"
        chk_src    = buscar(arq, "srcMD5", "srcChecksum", "md5", "checksum", "hash")
        chk_dst    = buscar(arq, "dstMD5", "dstChecksum")
        verificado = buscar(arq, "verified", "Verified", "status", "Status")
        ok         = verificado.lower() in ("yes", "true", "verified", "ok", "pass", "1")

        # "critical" é gerado pelo copiador.py.
        # Logs sem o atributo (ShotPutPro ou versão antiga) = crítico por segurança.
        critico_attr = buscar(arq, "critical", "Critical")
        critico = critico_attr.lower() != "no" if critico_attr else True

        # Tipo honesto do arquivo (Fatia B): o copiador grava "kind" no .sppo
        # (video/foto/audio/proxy/outro). Logs antigos sem o atributo caem no
        # classificador por extensão (mesma resposta), então nada quebra.
        kind = (buscar(arq, "kind", "Kind") or "").lower()
        if not kind and (nome or src_path):
            kind = classificar_arquivo(nome or os.path.basename(src_path or ""))
        # Para proxy, o clipe principal a que ele pertence (pista por nome).
        proxy_de = buscar(arq, "proxyOf", "ProxyOf")

        dados["arquivos"].append({
            "nome":         nome or "(sem nome)",
            "src_path":     src_path or "",
            "tamanho":      tamanho,
            "checksum_src": chk_src or "",
            "checksum_dst": chk_dst or "",
            # versão curta para tabelas de resumo
            "checksum":     (chk_src[:16] + "...") if len(chk_src) > 16 else chk_src,
            "ok":           ok,
            "critico":      critico,
            "tipo":         kind,
            "proxy_de":     proxy_de,
        })

    # Resumo geral
    resumo = root.find(".//summary")
    if resumo is None:
        resumo = root.find(".//Summary")
    if resumo is not None:
        dados["total_arquivos"]    = int(buscar(resumo, "totalFiles", "total", "count") or len(dados["arquivos"]))
        dados["total_verificados"] = int(buscar(resumo, "verified", "Verified") or 0)
        dados["total_falhos"]      = int(buscar(resumo, "failed", "Failed", "errors") or 0)
        dados["total_avisos"]      = int(buscar(resumo, "systemWarnings", "warnings") or 0)
        # Proxies copiados (não contam como vídeo). Atributo gravado pelo copiador;
        # se faltar (log antigo), conta pelos arquivos marcados como proxy.
        proxies_attr = buscar(resumo, "proxies", "Proxies")
        dados["total_proxies"]     = (int(proxies_attr) if proxies_attr
                                      else sum(1 for a in dados["arquivos"]
                                               if str(a.get("tipo", "")).startswith("proxy")))
        dados["tamanho_total"]     = int(buscar(resumo, "totalSize", "size", "totalBytes") or 0)
        dados["duracao"]           = buscar(resumo, "duration", "Duration", "elapsed")
        dados["velocidade"]        = buscar(resumo, "speed", "Speed", "avgSpeed")
    elif dados["arquivos"]:
        # Calcula a partir dos arquivos se não houver nó <summary>
        dados["total_arquivos"]    = len(dados["arquivos"])
        dados["total_verificados"] = sum(1 for a in dados["arquivos"] if a["ok"])
        dados["total_falhos"]      = sum(1 for a in dados["arquivos"] if not a["ok"] and a.get("critico", True))
        dados["total_avisos"]      = sum(1 for a in dados["arquivos"] if not a["ok"] and not a.get("critico", True))
        dados["total_proxies"]     = sum(1 for a in dados["arquivos"]
                                         if str(a.get("tipo", "")).startswith("proxy"))
        try:
            dados["tamanho_total"] = sum(int(a["tamanho"]) for a in dados["arquivos"]
                                         if str(a["tamanho"]).isdigit())
        except Exception:
            dados["tamanho_total"] = 0

    return dados


# ── EXTRAÇÃO DE METADADOS ─────────────────────────────────────────────────────

def extrair_metadados_video(caminho):
    """
    Usa ffprobe para extrair metadados de um arquivo de vídeo.
    Retorna dict com: codec, resolucao, fps, duracao_seg, duracao_str,
                      frames, audio_codec, audio_canais, audio_sample,
                      audio_bitrate, modelo_camera
    Se o arquivo não existir ou falhar, retorna valores '—'.
    """
    vazio = {
        'codec': '—', 'resolucao': '—', 'fps': '—',
        'duracao_seg': 0.0, 'duracao_str': '—', 'frames': '—',
        'audio_codec': '', 'audio_canais': '', 'audio_sample': '',
        'audio_bitrate': '', 'modelo_camera': '—',
    }
    if not os.path.isfile(str(caminho)):
        return vazio
    try:
        resultado = subprocess.run(
            [FFPROBE, '-v', 'quiet', '-print_format', 'json',
             '-show_streams', '-show_format', str(caminho)],
            capture_output=True, text=True, timeout=30
        )
        dados_ffprobe = json.loads(resultado.stdout)
    except Exception:
        return vazio

    meta = dict(vazio)

    # Stream de vídeo
    for stream in dados_ffprobe.get('streams', []):
        if stream.get('codec_type') == 'video':
            meta['codec'] = stream.get('codec_name', '—').upper()
            w = stream.get('width', 0)
            h = stream.get('height', 0)
            if w and h:
                meta['resolucao'] = f"{w}×{h}"

            # FPS: "24000/1001" → "23.976 fps"
            fps_str = stream.get('r_frame_rate', '')
            if '/' in fps_str:
                try:
                    num, den = fps_str.split('/')
                    fps_val = float(num) / float(den)
                    meta['fps'] = f"{fps_val:.3f}".rstrip('0').rstrip('.') + " fps"
                except Exception:
                    pass

            # Duração (usa o formato se o stream não tiver)
            dur = (stream.get('duration')
                   or dados_ffprobe.get('format', {}).get('duration'))
            if dur:
                try:
                    meta['duracao_seg'] = float(dur)
                    meta['duracao_str'] = formatar_duracao(dur)
                except ValueError:
                    pass

            # Número de frames
            meta['frames'] = stream.get('nb_frames', '—')
            break  # basta o primeiro stream de vídeo

    # Stream de áudio
    for stream in dados_ffprobe.get('streams', []):
        if stream.get('codec_type') == 'audio':
            meta['audio_codec']  = stream.get('codec_name', '').upper()
            meta['audio_canais'] = str(stream.get('channels', ''))
            sr = stream.get('sample_rate')
            meta['audio_sample'] = f"{sr} Hz" if sr else ''
            br = stream.get('bit_rate')
            if br:
                meta['audio_bitrate'] = f"{int(br)//1000} kbps"
            break  # basta o primeiro stream de áudio

    # Modelo da câmera (tags do container)
    tags = dados_ffprobe.get('format', {}).get('tags', {})
    make  = tags.get('make')  or tags.get('Make')  or ''
    model = tags.get('model') or tags.get('Model') or ''
    if make or model:
        meta['modelo_camera'] = f"{make} {model}".strip()

    return meta


def extrair_metadados_foto(caminho):
    """
    Usa exiftool para extrair metadados de foto ou RAW.
    Retorna dict com: resolucao, modelo_camera, data_criacao
    """
    vazio = {'resolucao': '—', 'modelo_camera': '—', 'data_criacao': '—'}
    if not os.path.isfile(str(caminho)):
        return vazio
    try:
        resultado = subprocess.run(
            [EXIFTOOL, '-json', '-Make', '-Model',
             '-ImageWidth', '-ImageHeight', '-CreateDate', '-FileModifyDate',
             str(caminho)],
            capture_output=True, text=True, timeout=15
        )
        lista = json.loads(resultado.stdout)
        if not lista:
            return vazio
        d = lista[0]
    except Exception:
        return vazio

    meta = dict(vazio)

    make  = d.get('Make', '')
    model = d.get('Model', '')
    if make or model:
        meta['modelo_camera'] = f"{make} {model}".strip()

    w = d.get('ImageWidth', 0)
    h = d.get('ImageHeight', 0)
    if w and h:
        meta['resolucao'] = f"{w}×{h}"

    data = d.get('CreateDate') or d.get('FileModifyDate', '')
    if data:
        # Formato exiftool: "2016:01:04 10:10:41+00:00" ou "2016:01:04 10:10:41"
        meta['data_criacao'] = data.replace(':', '-', 2).split('+')[0].split('-0')[0].strip()

    return meta


# ── EXTRAÇÃO DE THUMBNAILS ────────────────────────────────────────────────────

def _salvar_thumb_pil(img_pil, caminho_saida):
    """Redimensiona e salva uma imagem PIL como JPEG (320×320 max)."""
    try:
        img_pil = img_pil.convert('RGB')
        img_pil.thumbnail((320, 320), PILImage.LANCZOS)
        img_pil.save(caminho_saida, 'JPEG', quality=85)
        return True
    except Exception:
        return False


def _thm_para_video(caminho_video):
    """
    Retorna o caminho do .THM nativo GoPro para um .MP4, ou None.
    GX019385.MP4 → GX019385.THM (mesmo prefixo, extensão .THM)
    """
    p = Path(caminho_video)
    thm = p.with_suffix('.THM')
    return str(thm) if thm.exists() else None


def _lrv_para_video(caminho_video):
    """
    Retorna o caminho do .LRV (proxy) GoPro para um .MP4, ou None.
    GX019385.MP4 → GL019385.LRV  (GX → GL, extensão .LRV)
    """
    p = Path(caminho_video)
    stem = p.stem  # ex: "GX019385"
    # Substitui a segunda letra (X, H, S) por L
    if len(stem) >= 2 and stem[0] == 'G' and stem[1] in ('X', 'H', 'S'):
        stem_lrv = stem[0] + 'L' + stem[2:]
        lrv = p.parent / (stem_lrv + '.LRV')
        if lrv.exists():
            return str(lrv)
    return None


def _n_thumbs_para_duracao(duracao_seg):
    """Número de frames a extrair, baseado na duração do clipe."""
    if duracao_seg <= 15:   return 2
    if duracao_seg <= 60:   return 3
    if duracao_seg <= 300:  return 4
    return 5


def obter_thumbnails_video(caminho_video, tmpdir, nome_base):
    """
    Extrai thumbnails de um vídeo.
    Para GoPro: usa .THM (1 frame nativo) como primeiro frame;
                usa .LRV (proxy) para frames adicionais.
    Para outros: extrai direto do arquivo de destino com ffmpeg.

    Retorna lista de caminhos para arquivos JPEG temporários.
    """
    thumbs = []
    caminho = str(caminho_video)

    if not os.path.isfile(caminho):
        return thumbs

    # ── Caso GoPro: .THM disponível ──────────────────────────────────────────
    thm = _thm_para_video(caminho)
    if thm and PILLOW_DISPONIVEL:
        try:
            saida = os.path.join(tmpdir, f"{nome_base}_0.jpg")
            img = PILImage.open(thm)
            if _salvar_thumb_pil(img, saida):
                thumbs.append(saida)
        except Exception:
            pass

    # Fonte para frames extras: .LRV (proxy) ou o próprio vídeo
    lrv = _lrv_para_video(caminho)
    fonte_extra = lrv if lrv else caminho

    # Descobre a duração para amostrar
    duracao = 0.0
    try:
        res = subprocess.run(
            [FFPROBE, '-v', 'quiet', '-print_format', 'json', '-show_format', fonte_extra],
            capture_output=True, text=True, timeout=20
        )
        info = json.loads(res.stdout)
        duracao = float(info.get('format', {}).get('duration', 0))
    except Exception:
        duracao = 30.0

    if duracao <= 0:
        duracao = 30.0

    n_extra = _n_thumbs_para_duracao(duracao) - len(thumbs)
    if n_extra <= 0:
        n_extra = 1

    # Timestamps amostrados entre 10% e 90% do clipe (evita preto no início/fim)
    inicio_pct = 0.1
    fim_pct    = 0.9
    if n_extra == 1:
        timestamps = [duracao * 0.5]
    else:
        timestamps = [
            duracao * (inicio_pct + (fim_pct - inicio_pct) * i / (n_extra - 1))
            for i in range(n_extra)
        ]

    for i, ts in enumerate(timestamps):
        idx = len(thumbs)
        saida = os.path.join(tmpdir, f"{nome_base}_{idx}.jpg")
        try:
            subprocess.run(
                [FFMPEG, '-ss', str(ts), '-i', fonte_extra,
                 '-vframes', '1', '-q:v', '3',
                 '-vf', 'scale=320:-2',
                 '-y', saida],
                capture_output=True, timeout=30
            )
            if os.path.exists(saida) and os.path.getsize(saida) > 200:
                thumbs.append(saida)
        except Exception:
            pass

    return thumbs


def obter_thumbnail_foto(caminho_foto, tmpdir, nome_base):
    """
    Gera thumbnail de foto ou RAW.
    - JPEG/PNG: abre com Pillow.
    - GPR (GoPro RAW): usa .THM nativo se existir.
    - Outros RAW: exiftool extrai JPEG embutido.
    Retorna caminho do JPEG temporário, ou None.
    """
    caminho = str(caminho_foto)
    if not os.path.isfile(caminho):
        return None

    ext = Path(caminho).suffix.lower()
    saida = os.path.join(tmpdir, f"{nome_base}_0.jpg")

    # JPEG e PNG: Pillow direto
    if ext in ('.jpg', '.jpeg', '.png') and PILLOW_DISPONIVEL:
        try:
            img = PILImage.open(caminho)
            if _salvar_thumb_pil(img, saida):
                return saida
        except Exception:
            pass

    # GPR (GoPro RAW): tenta .THM com mesmo base name
    thm = Path(caminho).with_suffix('.THM')
    if thm.exists() and PILLOW_DISPONIVEL:
        try:
            img = PILImage.open(str(thm))
            if _salvar_thumb_pil(img, saida):
                return saida
        except Exception:
            pass

    # RAW genérico: exiftool extrai JPEG embutido
    for flag in ('-ThumbnailImage', '-PreviewImage', '-JpgFromRaw'):
        try:
            resultado = subprocess.run(
                [EXIFTOOL, '-b', flag, caminho],
                capture_output=True, timeout=15
            )
            if resultado.stdout and len(resultado.stdout) > 500:
                with open(saida, 'wb') as f:
                    f.write(resultado.stdout)
                return saida
        except Exception:
            pass

    return None


# ── CONSTRUÇÃO DO BLOCO DE MÍDIA (Parte 2) ────────────────────────────────────

def _rl_thumbnail(caminho_thumb, altura_max=THUMB_ALTURA_MAX):
    """
    Cria um elemento RLImage (reportlab) a partir de um arquivo JPEG.
    Preserva a proporção original, respeitando a altura máxima.
    Retorna RLImage ou None se falhar.
    """
    if not caminho_thumb or not os.path.isfile(caminho_thumb):
        return None
    try:
        with PILImage.open(caminho_thumb) as img:
            w_orig, h_orig = img.size
        if h_orig == 0:
            return None
        razao = w_orig / h_orig
        h = altura_max
        w = int(h * razao)
        return RLImage(caminho_thumb, width=w, height=h)
    except Exception:
        return None


def construir_bloco_midia(arq_info, pasta_destino, source_root, tmpdir, estilos):
    """
    Monta um bloco de mídia para a Parte 2 (folha de contato).

    Estrutura visual:
      ┌─────────────────────┬──────────────────────────────────────────────┐
      │ Nome (bold)         │  [thumb1] [thumb2] [thumb3]                  │
      │ Tamanho · Status    │                                               │
      │ Câmera              │                                               │
      │ Codec · Resolução   │                                               │
      │ Duração · Frames    │                                               │
      │ Áudio               │                                               │
      └─────────────────────┴──────────────────────────────────────────────┘

    Retorna uma Table de 2 colunas, ou None se o arquivo não existir.
    """
    nome = arq_info['nome']
    tipo = classificar_arquivo(nome)

    # Caminho do arquivo no destino
    caminho_arq = caminho_destino_arquivo(
        arq_info.get('src_path', ''),
        source_root,
        pasta_destino
    )

    st_nome   = estilos['nome_arq']
    st_meta   = estilos['meta_arq']

    tamanho_str = formatar_tamanho(arq_info.get('tamanho', 0))

    if arq_info['ok']:
        status_str = "✓ OK"
    elif not arq_info.get('critico', True):
        status_str = "⚠ AVISO"
    else:
        status_str = "✗ FALHO"

    # ── Coluna de metadados ───────────────────────────────────────────────────
    meta_items = []
    meta_items.append(Paragraph(nome, st_nome))
    meta_items.append(Spacer(1, 3))
    meta_items.append(Paragraph(
        f"<b>Tamanho:</b> {tamanho_str}&nbsp;&nbsp;&nbsp;<b>Status:</b> {status_str}",
        st_meta
    ))

    nome_base_safe = nome.replace('.', '_').replace(' ', '_')

    if tipo == 'video':
        meta = extrair_metadados_video(caminho_arq)
        if meta['modelo_camera'] != '—':
            meta_items.append(Paragraph(f"<b>Câmera:</b> {meta['modelo_camera']}", st_meta))
        meta_items.append(Paragraph(
            f"<b>Codec:</b> {meta['codec']}&nbsp;&nbsp;&nbsp;<b>Res:</b> {meta['resolucao']}",
            st_meta
        ))
        meta_items.append(Paragraph(
            f"<b>Duração:</b> {meta['duracao_str']}&nbsp;&nbsp;&nbsp;"
            f"<b>Frames:</b> {meta['frames']}&nbsp;&nbsp;&nbsp;"
            f"<b>FPS:</b> {meta['fps']}",
            st_meta
        ))
        if meta['audio_codec']:
            audio = meta['audio_codec']
            if meta['audio_canais']:
                audio += f" {meta['audio_canais']}ch"
            if meta['audio_sample']:
                audio += f" · {meta['audio_sample']}"
            if meta['audio_bitrate']:
                audio += f" · {meta['audio_bitrate']}"
            meta_items.append(Paragraph(f"<b>Áudio:</b> {audio}", st_meta))
        thumbs_paths = obter_thumbnails_video(caminho_arq, tmpdir, nome_base_safe)

    else:  # foto
        meta = extrair_metadados_foto(caminho_arq)
        if meta['modelo_camera'] != '—':
            meta_items.append(Paragraph(f"<b>Câmera:</b> {meta['modelo_camera']}", st_meta))
        meta_items.append(Paragraph(f"<b>Resolução:</b> {meta['resolucao']}", st_meta))
        if meta['data_criacao'] != '—':
            meta_items.append(Paragraph(f"<b>Criado:</b> {meta['data_criacao']}", st_meta))
        thumbs_paths = []
        t = obter_thumbnail_foto(caminho_arq, tmpdir, nome_base_safe)
        if t:
            thumbs_paths = [t]

    # ── Coluna do filmstrip ───────────────────────────────────────────────────
    # Distribui a largura disponível entre os thumbnails
    n = len(thumbs_paths)
    elementos_filmstrip = []

    if n > 0:
        # Largura disponível para os thumbs (desconta padding da coluna)
        largura_disponivel = COL_FILMSTRIP_LARGURA - 12
        # Cria os elementos RLImage
        imgs_rl = []
        for p in thumbs_paths:
            img = _rl_thumbnail(p, THUMB_ALTURA_MAX)
            if img:
                imgs_rl.append(img)

        if imgs_rl:
            # Calcula largura total dos thumbs e verifica se cabe
            largura_total_thumbs = sum(img.drawWidth for img in imgs_rl)
            gap = 4 * (len(imgs_rl) - 1)  # 4 pts entre cada thumbnail

            if largura_total_thumbs + gap > largura_disponivel:
                # Escala todos para caber
                escala = (largura_disponivel - gap) / largura_total_thumbs
                for img in imgs_rl:
                    img.drawWidth  = int(img.drawWidth  * escala)
                    img.drawHeight = int(img.drawHeight * escala)

            # Cria a linha de thumbnails como Table
            larguras_cols = [img.drawWidth + 4 for img in imgs_rl]
            filmstrip = Table(
                [imgs_rl],
                colWidths=larguras_cols,
                hAlign='LEFT'
            )
            filmstrip.setStyle(TableStyle([
                ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
                ('ALIGN',         (0, 0), (-1, -1), 'CENTER'),
                ('LEFTPADDING',   (0, 0), (-1, -1), 2),
                ('RIGHTPADDING',  (0, 0), (-1, -1), 2),
                ('TOPPADDING',    (0, 0), (-1, -1), 0),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
            ]))
            elementos_filmstrip = [filmstrip]

    if not elementos_filmstrip:
        st_sem_preview = estilos.get('sem_preview', estilos['meta_arq'])
        elementos_filmstrip = [Paragraph("(sem preview)", st_sem_preview)]

    # ── Bloco final (2 colunas) ───────────────────────────────────────────────
    bloco = Table(
        [[meta_items, elementos_filmstrip]],
        colWidths=[COL_META_LARGURA, COL_FILMSTRIP_LARGURA],
        hAlign='LEFT'
    )
    bloco.setStyle(TableStyle([
        ('VALIGN',        (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING',   (0, 0), (-1, -1), 6),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 6),
        ('TOPPADDING',    (0, 0), (-1, -1), 7),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
        ('LINEBELOW',     (0, 0), (-1, -1), 0.4, COR_BORDA),
    ]))

    return bloco


# ── GERADOR DE ESTILOS ────────────────────────────────────────────────────────

def _montar_estilos():
    """Cria e retorna o dicionário de estilos usados no PDF."""
    base = getSampleStyleSheet()

    def estilo(nome, parent='Normal', **kw):
        return ParagraphStyle(nome, parent=base[parent], **kw)

    return {
        # Cabeçalho
        'label_gma': estilo('label_gma',
            fontSize=9, fontName='Helvetica', textColor=COR_MUTED),
        'titulo_job': estilo('titulo_job',
            fontSize=20, fontName='Helvetica-Bold', textColor=COR_TITULO, spaceAfter=3),
        'subtitulo': estilo('subtitulo',
            fontSize=10, fontName='Helvetica', textColor=COR_MUTED, spaceAfter=10),

        # Resumo
        'resumo_label': estilo('resumo_label',
            fontSize=8, fontName='Helvetica-Bold', textColor=COR_MUTED),
        'resumo_valor': estilo('resumo_valor',
            fontSize=9, fontName='Helvetica', textColor=COR_TITULO),
        'resumo_valor_bold': estilo('resumo_valor_bold',
            fontSize=9, fontName='Helvetica-Bold', textColor=COR_TITULO),
        'status_ok': estilo('status_ok',
            fontSize=11, fontName='Helvetica-Bold', textColor=COR_SUCESSO),
        'status_erro': estilo('status_erro',
            fontSize=11, fontName='Helvetica-Bold', textColor=COR_ERRO),

        # Seções
        'titulo_secao': estilo('titulo_secao',
            fontSize=12, fontName='Helvetica-Bold', textColor=COR_PRIMARIA,
            spaceBefore=10, spaceAfter=4),

        # Blocos de mídia (Parte 2)
        'nome_arq': estilo('nome_arq',
            fontSize=8.5, fontName='Helvetica-Bold', textColor=COR_TITULO),
        'meta_arq': estilo('meta_arq',
            fontSize=7.5, fontName='Helvetica', textColor=COR_MUTED, spaceAfter=1),
        'sem_preview': estilo('sem_preview',
            fontSize=8, fontName='Helvetica', textColor=COR_BORDA,
            alignment=TA_CENTER),

        # Tabela de detalhes (Parte 3)
        'tabela_cabecalho': estilo('tabela_cabecalho',
            fontSize=7.5, fontName='Helvetica-Bold', textColor=colors.white),
        'tabela_corpo': estilo('tabela_corpo',
            fontSize=7, fontName='Helvetica', textColor=COR_TITULO),
        'tabela_ok': estilo('tabela_ok',
            fontSize=7, fontName='Helvetica-Bold', textColor=COR_SUCESSO),
        'tabela_aviso': estilo('tabela_aviso',
            fontSize=7, fontName='Helvetica-Bold', textColor=COR_AVISO),
        'tabela_falho': estilo('tabela_falho',
            fontSize=7, fontName='Helvetica-Bold', textColor=COR_ERRO),

        # Rodapé
        'rodape': estilo('rodape',
            fontSize=7.5, textColor=COR_BORDA, alignment=TA_CENTER),
    }


# ── PARTE 1: CABEÇALHO ────────────────────────────────────────────────────────

def _gerar_parte1_cabecalho(dados, dados_match, estilos):
    """
    Gera os elementos da Parte 1: cabeçalho com título do job e resumo em 3 colunas.

      Col A: tamanho total · verificação · total de arquivos · arquivos de mídia
      Col B: início · velocidade · duração
      Col C: dados do match (profissional · câmera · tipo · operador)
    """
    elementos = []

    # Topo
    elementos.append(Paragraph("GMA — Gerenciamento de Mídia Audiovisual", estilos['label_gma']))
    elementos.append(Spacer(1, 0.2*cm))
    elementos.append(Paragraph(f"Relatório de transferência: {dados['nome_job']}", estilos['titulo_job']))

    gerado_em = datetime.now().strftime('%d/%m/%Y  %H:%M')
    transferencia = f"{dados['data']}  {dados['hora']}".strip() or "—"
    elementos.append(Paragraph(
        f"Gerado em {gerado_em}   ·   Transferência: {transferencia}",
        estilos['subtitulo']
    ))

    elementos.append(HRFlowable(width='100%', thickness=2, color=COR_PRIMARIA))
    elementos.append(Spacer(1, 0.3*cm))

    # Status do job
    avisos = dados.get('total_avisos', 0)
    if dados['total_falhos'] > 0:
        st_status = estilos['status_erro']
        txt_status = f"✗  ATENÇÃO — {dados['total_falhos']} arquivo(s) com falha crítica"
    elif avisos > 0:
        st_status = estilos['status_ok']
        txt_status = (f"✓  VERIFICADO — footage íntegro  "
                      f"({avisos} arquivo(s) de sistema com aviso, não-crítico)")
    else:
        st_status = estilos['status_ok']
        txt_status = "✓  VERIFICADO — tudo OK"

    elementos.append(Paragraph(txt_status, st_status))
    elementos.append(Spacer(1, 0.3*cm))

    # 3 colunas de resumo
    n_midia = sum(1 for a in dados['arquivos'] if eh_midia(a['nome']))

    def _kv(label, valor):
        """Retorna duas linhas: label (cinza) + valor (escuro)."""
        return [
            Paragraph(label.upper(), estilos['resumo_label']),
            Paragraph(str(valor),    estilos['resumo_valor']),
            Spacer(1, 6),
        ]

    # Col A — Tamanho e integridade
    col_a = []
    col_a += _kv("Tamanho total",    formatar_tamanho(dados['tamanho_total']))
    col_a += _kv("Verificação",      "MD5 completo (arquivo a arquivo)")
    col_a += _kv("Total de arquivos", dados['total_arquivos'])
    col_a += _kv("Arquivos de mídia", n_midia)
    col_a += _kv("Verificados OK",    dados['total_verificados'])
    if dados['total_falhos'] > 0:
        col_a += _kv("Falhas críticas", dados['total_falhos'])
    if avisos > 0:
        col_a += _kv("Avisos (sistema)", avisos)

    # Col B — Tempo e velocidade
    col_b = []
    col_b += _kv("Início",     f"{dados['data']}  {dados['hora']}".strip() or "—")
    col_b += _kv("Duração",    dados['duracao'] or "—")
    col_b += _kv("Velocidade", dados['velocidade'] or "—")
    if dados['destinos']:
        col_b += _kv("Destino", dados['destinos'][0])
    if dados['origem']:
        col_b += _kv("Origem (volume)", dados['origem'])

    # Col C — Dados do match
    col_c = []
    if dados_match:
        col_c += _kv("Profissional",   dados_match.get('nome', '—'))
        col_c += _kv("Câmera",         dados_match.get('camera', '—'))
        col_c += _kv("Tipo de material", dados_match.get('tipo_material', '—'))
        col_c += _kv("Operador",       dados_match.get('operador', '—'))
    col_c += _kv("Gerado por", "GMA — Relatório automático")

    largura_col = LARGURA_UTIL / 3

    tabela_colunas = Table(
        [[col_a, col_b, col_c]],
        colWidths=[largura_col, largura_col, largura_col],
        hAlign='LEFT'
    )
    tabela_colunas.setStyle(TableStyle([
        ('VALIGN',        (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING',   (0, 0), (-1, -1), 10),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 10),
        ('TOPPADDING',    (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
        ('BACKGROUND',    (0, 0), (-1, -1), COR_FUNDO_HEADER),
        ('LINEAFTER',     (0, 0), (1, -1),  0.5, COR_BORDA),
    ]))

    elementos.append(tabela_colunas)

    return elementos


# ── PARTE 2: FOLHA DE CONTATO ─────────────────────────────────────────────────

def _gerar_parte2_folha_contato(dados, pasta_destino, source_root, tmpdir, estilos):
    """
    Gera os elementos da Parte 2: uma folha de contato com thumbnails e
    metadados para cada arquivo de mídia.
    """
    arquivos_midia = [a for a in dados['arquivos'] if eh_midia(a['nome'])]
    if not arquivos_midia:
        return []

    elementos = []
    elementos.append(PageBreak())
    elementos.append(Paragraph(
        f"Folha de contato — arquivos de mídia ({len(arquivos_midia)} de {dados['total_arquivos']})",
        estilos['titulo_secao']
    ))
    elementos.append(HRFlowable(width='100%', thickness=0.5, color=COR_BORDA))
    elementos.append(Spacer(1, 0.2*cm))

    for arq_info in arquivos_midia:
        bloco = construir_bloco_midia(
            arq_info, pasta_destino, source_root, tmpdir, estilos
        )
        if bloco:
            elementos.append(bloco)

    return elementos


# ── PARTE 3: TABELA COMPLETA ──────────────────────────────────────────────────

def _gerar_parte3_detalhes(dados, pasta_destino, source_root, estilos):
    """
    Gera os elementos da Parte 3: tabela de auditoria com todos os arquivos,
    incluindo os de sistema (sem thumbnail). Exibe checksums de origem e destino.
    """
    if not dados['arquivos']:
        return []

    elementos = []
    elementos.append(PageBreak())
    elementos.append(Paragraph(
        f"Detalhes completos — todos os {dados['total_arquivos']} arquivos",
        estilos['titulo_secao']
    ))
    elementos.append(HRFlowable(width='100%', thickness=0.5, color=COR_BORDA))
    elementos.append(Spacer(1, 0.2*cm))

    st_corpo  = estilos['tabela_corpo']
    st_ok     = estilos['tabela_ok']
    st_aviso  = estilos['tabela_aviso']
    st_falho  = estilos['tabela_falho']

    cabecalho = [[
        Paragraph("Arquivo",           estilos['tabela_cabecalho']),
        Paragraph("Pasta",             estilos['tabela_cabecalho']),
        Paragraph("Tamanho",           estilos['tabela_cabecalho']),
        Paragraph("MD5 Origem",        estilos['tabela_cabecalho']),
        Paragraph("MD5 Destino",       estilos['tabela_cabecalho']),
        Paragraph("Status",            estilos['tabela_cabecalho']),
    ]]

    linhas = []
    for arq in dados['arquivos']:
        nome_arq = arq['nome']
        src_path = arq.get('src_path', '')

        # Pasta relativa (a partir da raiz de destino)
        if src_path and source_root:
            caminho_relativo = src_path[len(source_root):].lstrip('/')
            pasta_rel = str(Path(caminho_relativo).parent)
            if pasta_rel == '.':
                pasta_rel = '(raiz)'
        else:
            pasta_rel = '—'

        tamanho_str = formatar_tamanho(arq.get('tamanho', 0))
        chk_src = arq.get('checksum_src', '') or '—'
        chk_dst = arq.get('checksum_dst', '') or '—'
        # Encurta os checksums para caber na coluna (primeiros 12 + "…")
        chk_src_curto = (chk_src[:12] + '…') if len(chk_src) > 13 else chk_src
        chk_dst_curto = (chk_dst[:12] + '…') if len(chk_dst) > 13 else chk_dst

        if arq['ok']:
            st_status = st_ok
            txt_status = "OK"
        elif not arq.get('critico', True):
            st_status = st_aviso
            txt_status = "AVISO"
        else:
            st_status = st_falho
            txt_status = "FALHO"

        linhas.append([
            Paragraph(nome_arq,        st_corpo),
            Paragraph(pasta_rel,       st_corpo),
            Paragraph(tamanho_str,     st_corpo),
            Paragraph(chk_src_curto,   st_corpo),
            Paragraph(chk_dst_curto,   st_corpo),
            Paragraph(txt_status,      st_status),
        ])

    tab = Table(
        cabecalho + linhas,
        colWidths=[
            LARGURA_UTIL * 0.22,   # nome arquivo
            LARGURA_UTIL * 0.18,   # pasta
            LARGURA_UTIL * 0.09,   # tamanho
            LARGURA_UTIL * 0.19,   # md5 origem
            LARGURA_UTIL * 0.19,   # md5 destino
            LARGURA_UTIL * 0.08,   # status
        ],
        hAlign='LEFT',
        repeatRows=1,  # repete cabeçalho em cada página
    )
    tab.setStyle(TableStyle([
        # Cabeçalho
        ('BACKGROUND',     (0, 0), (-1, 0),  COR_TITULO),
        ('FONTNAME',       (0, 0), (-1, 0),  'Helvetica-Bold'),
        ('FONTSIZE',       (0, 0), (-1, 0),  7.5),
        # Corpo
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, COR_FUNDO_ALT]),
        ('FONTNAME',       (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE',       (0, 1), (-1, -1), 7),
        # Alinhamentos
        ('ALIGN',          (2, 0), (2, -1),  'RIGHT'),  # tamanho
        ('ALIGN',          (5, 0), (5, -1),  'CENTER'), # status
        # Padding
        ('TOPPADDING',     (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING',  (0, 0), (-1, -1), 3),
        ('LEFTPADDING',    (0, 0), (-1, -1), 5),
        ('RIGHTPADDING',   (0, 0), (-1, -1), 5),
        # Bordas
        ('GRID',           (0, 0), (-1, -1), 0.25, COR_BORDA),
        ('LINEBELOW',      (0, 0), (-1, 0),  1,    COR_TITULO),
    ]))

    elementos.append(tab)
    return elementos


# ── GERADOR PRINCIPAL DE PDF ──────────────────────────────────────────────────

def gerar_pdf(dados, caminho_saida, dados_match=None):
    """
    Gera o relatório PDF completo (Partes 1, 2 e 3) e salva em caminho_saida.

    Parâmetros:
      dados       — dicionário retornado por parse_shotputpro_log()
      caminho_saida — caminho completo do arquivo PDF a gerar
      dados_match — (opcional) dicionário com dados do formulário:
                    {'nome': ..., 'camera': ..., 'tipo_material': ..., 'operador': ...}
                    Se não fornecido, as colunas de match mostram '—'.
    """
    # Pasta de destino vem do próprio .sppo (primeiro destino listado)
    pasta_destino = dados['destinos'][0] if dados['destinos'] else ""
    source_root   = dados.get('source_root', '')

    # Diretório temporário para thumbnails (limpo ao final)
    tmpdir = tempfile.mkdtemp(prefix='gma_thumbs_')

    try:
        doc = SimpleDocTemplate(
            caminho_saida,
            pagesize=landscape(letter),
            leftMargin=MARGEM, rightMargin=MARGEM,
            topMargin=MARGEM,  bottomMargin=MARGEM,
            title=f"Relatorio GMA — {dados['nome_job']}",
            author="GMA — Gerenciamento de Midia Audiovisual",
        )

        estilos = _montar_estilos()
        conteudo = []

        # ── Parte 1 — Cabeçalho ──────────────────────────────────────────────
        conteudo += _gerar_parte1_cabecalho(dados, dados_match, estilos)

        # ── Parte 2 — Folha de contato ───────────────────────────────────────
        conteudo += _gerar_parte2_folha_contato(
            dados, pasta_destino, source_root, tmpdir, estilos
        )

        # ── Parte 3 — Detalhes completos ─────────────────────────────────────
        conteudo += _gerar_parte3_detalhes(dados, pasta_destino, source_root, estilos)

        # ── Rodapé (última linha) ─────────────────────────────────────────────
        conteudo.append(Spacer(1, 0.5*cm))
        conteudo.append(HRFlowable(width='100%', thickness=0.5, color=COR_BORDA))
        conteudo.append(Spacer(1, 0.2*cm))
        conteudo.append(Paragraph(
            "GMA — Gerenciamento de Mídia Audiovisual  ·  Documento gerado automaticamente",
            estilos['rodape']
        ))

        doc.build(conteudo)
        print(f"\nPDF gerado: {caminho_saida}")

    finally:
        # Apaga os thumbnails temporários em qualquer caso
        import shutil
        try:
            shutil.rmtree(tmpdir, ignore_errors=True)
        except Exception:
            pass


# ── PONTO DE ENTRADA (uso direto via terminal) ────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print("Uso:     python3 gma_relatorio_pdf.py caminho/para/log.sppo")
        print("Exemplo: python3 gma_relatorio_pdf.py ~/Desktop/NOME_001.sppo")
        sys.exit(1)

    caminho_log = sys.argv[1]

    if not os.path.exists(caminho_log):
        print(f"Arquivo não encontrado: {caminho_log}")
        sys.exit(1)

    base = os.path.splitext(caminho_log)[0]
    caminho_pdf = base + "_relatorio.pdf"

    print(f"Lendo log:  {caminho_log}")
    dados = parse_shotputpro_log(caminho_log)

    n_midia = sum(1 for a in dados['arquivos'] if eh_midia(a['nome']))
    print(f"Job:        {dados['nome_job']}")
    print(f"Arquivos:   {dados['total_arquivos']}  (mídia: {n_midia})  |  "
          f"Verificados: {dados['total_verificados']}  |  "
          f"Falhos: {dados['total_falhos']}")
    print(f"Tamanho:    {formatar_tamanho(dados['tamanho_total'])}")
    print(f"Gerando PDF rico (pode levar alguns segundos para extrair thumbnails)...")

    gerar_pdf(dados, caminho_pdf)


if __name__ == "__main__":
    main()
