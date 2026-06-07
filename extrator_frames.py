#!/usr/bin/env python3
"""
extrator_frames.py  —  Executador mecânico de frames e metadados de mídia (GMA)

PAPEL NA ARQUITETURA
--------------------
Este módulo é o "especialista visual mecânico" do GMA. Ele roda DEPOIS que a
Camada 2 (cópia) terminou e confirmou a integridade — e lê SEMPRE do destino já
verificado, NUNCA do cartão (princípio nº 2: o material insubstituível não é
estressado).

É 100% MECÂNICO, OFFLINE e GRATUITO:
  - extrair um frame = "tirar uma foto" de um instante do vídeo (ffmpeg)
  - ler metadados   = codec, resolução, duração, câmera (ffprobe / exiftool)

NÃO é IA. Entender o que HÁ na imagem, escolher o frame "mais bonito", descrever
ou etiquetar o conteúdo é trabalho da Camada 6 (paga, assíncrona, opcional) — que
virá DEPOIS e apenas se aproveitará dos frames que este módulo já gerou.

O QUE ELE PRODUZ
----------------
1. Miniaturas (JPEG) numa subpasta `_GMA_frames/` ao lado do relatório.
2. Um `..._manifesto.json` — o índice de mídia (metadados + caminhos dos frames).
   Esse manifesto é a metade "mídia" do relatório; a outra metade ("integridade")
   é o próprio `.sppo`. O gerador de PDF/CSV só faz o JOIN dos dois e desenha.

LÓGICA DOS FRAMES (divisão simples e uniforme)
----------------------------------------------
Para um vídeo, pegamos um padrão FIXO de frames (FRAMES_POR_VIDEO = 10, igual ao
ShotPutPro), igualmente espaçados entre 5% e 95% do clipe (evita o preto das
pontas). Padrão fixo = folha de contato visualmente consistente. Fotos recebem
1 thumbnail. (Sem detecção de cena nem "escolher o melhor frame" — isso é
entender a imagem, trabalho da Camada 6.)

Dependências (todas já instaladas):
    ffmpeg / ffprobe   /opt/homebrew/bin
    exiftool           /opt/homebrew/bin
    Pillow             pip

Uso direto (teste):
    python3 extrator_frames.py caminho/para/log.sppo
    python3 extrator_frames.py --pasta caminho/da/pasta_destino

API (usada depois pelo gerador de PDF):
    from extrator_frames import gerar_manifesto
    manifesto = gerar_manifesto(caminho_sppo="...")        # a partir do .sppo
    manifesto = gerar_manifesto(pasta_destino="...")       # varrendo a pasta
"""

import os
import sys
import json
import subprocess
import logging
from pathlib import Path
from datetime import datetime
import xml.etree.ElementTree as ET


# ── CAMINHOS DAS FERRAMENTAS EXTERNAS ─────────────────────────────────────────

FFPROBE  = "/opt/homebrew/bin/ffprobe"
FFMPEG   = "/opt/homebrew/bin/ffmpeg"
EXIFTOOL = "/opt/homebrew/bin/exiftool"

# Pillow é opcional, mas muito recomendado (miniaturas de foto e redimensionamento)
try:
    from PIL import Image as PILImage
    PILLOW_DISPONIVEL = True
except ImportError:
    PILLOW_DISPONIVEL = False


# ── LOG ───────────────────────────────────────────────────────────────────────

PASTA_BASE = os.path.dirname(os.path.abspath(__file__))
PASTA_LOGS = os.path.join(PASTA_BASE, "logs")
os.makedirs(PASTA_LOGS, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(PASTA_LOGS, "extrator_frames.log")),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("extrator_frames")


# ── CLASSIFICAÇÃO DE ARQUIVOS ─────────────────────────────────────────────────

# Mídia de captação principal (aparece na folha de contato)
EXT_VIDEO = {'.mp4', '.mov', '.mxf', '.avi', '.mkv', '.mts', '.m4v',
             '.r3d', '.braw', '.ari', '.m2ts'}
EXT_FOTO  = {'.jpg', '.jpeg', '.png', '.tif', '.tiff', '.dng',
             '.cr2', '.cr3', '.nef', '.raf', '.arw', '.rw2', '.gpr'}

# Proxies GoPro: SÃO usados como fonte de thumbnails, mas não viram entrada própria
EXT_PROXY_VIDEO = {'.lrv'}   # proxy de vídeo de baixa resolução
EXT_PROXY_FOTO  = {'.thm'}   # thumbnail nativo


def classificar_arquivo(nome):
    """Retorna 'video' | 'foto' | 'proxy_video' | 'proxy_foto' | 'outro'."""
    ext = Path(nome).suffix.lower()
    if ext in EXT_VIDEO:        return 'video'
    if ext in EXT_FOTO:         return 'foto'
    if ext in EXT_PROXY_VIDEO:  return 'proxy_video'
    if ext in EXT_PROXY_FOTO:   return 'proxy_foto'
    return 'outro'


def eh_midia(nome):
    """True se o arquivo é mídia de captação (vídeo ou foto — não proxy, não sistema)."""
    return classificar_arquivo(nome) in ('video', 'foto')


# ── LÓGICA DOS FRAMES (divisão uniforme) ──────────────────────────────────────

# Padrão fixo de frames por vídeo (decisão de 2026-06-07, igual ao ShotPutPro):
# todo clipe gera a MESMA quantidade — folha de contato visualmente consistente
# (grade 5×2 sempre cheia), independente da duração. Tempo extra é aceitável.
# Fotos sempre geram 1 thumbnail. Ajuste só aqui se quiser outro padrão.
FRAMES_POR_VIDEO = 10


def numero_de_frames(duracao_seg):
    """Quantos frames extrair de um vídeo. Padrão fixo (ver FRAMES_POR_VIDEO)."""
    return FRAMES_POR_VIDEO


def instantes_para_amostrar(duracao_seg, n):
    """
    Retorna a lista de instantes (em segundos) onde tirar cada frame.
    Espalha N frames igualmente entre 5% e 95% da duração (evita preto das pontas).
    """
    if n <= 0:
        return []
    if n == 1:
        return [duracao_seg * 0.5]
    inicio_pct, fim_pct = 0.05, 0.95
    return [
        duracao_seg * (inicio_pct + (fim_pct - inicio_pct) * i / (n - 1))
        for i in range(n)
    ]


# ── UTILITÁRIOS ───────────────────────────────────────────────────────────────

def _ferramentas_ok():
    """Avisa no log se alguma ferramenta externa estiver faltando."""
    faltando = []
    for nome, caminho in (("ffprobe", FFPROBE), ("ffmpeg", FFMPEG),
                          ("exiftool", EXIFTOOL)):
        if not os.path.isfile(caminho):
            faltando.append(f"{nome} ({caminho})")
    if faltando:
        logger.warning("Ferramentas ausentes (frames/metadados podem ficar incompletos): "
                       + ", ".join(faltando))
    if not PILLOW_DISPONIVEL:
        logger.warning("Pillow ausente — miniaturas de foto e redimensionamento limitados. "
                       "Instale com: pip install Pillow")


def formatar_duracao(segundos):
    """Segundos (float) → 'MM:SS' ou 'HH:MM:SS'."""
    try:
        s = int(float(segundos))
        h, resto = divmod(s, 3600)
        m, s = divmod(resto, 60)
        return f"{h:02d}:{m:02d}:{s:02d}" if h > 0 else f"{m:02d}:{s:02d}"
    except (ValueError, TypeError):
        return "—"


def _buscar(elemento, *tags):
    """Lê um atributo XML tentando vários nomes possíveis."""
    for tag in tags:
        v = elemento.get(tag)
        if v is not None:
            return v
    return ""


# ── METADADOS DE VÍDEO (ffprobe) ──────────────────────────────────────────────

def extrair_metadados_video(caminho):
    """
    Metadados de um vídeo via ffprobe. Nunca lança exceção: em caso de falha,
    devolve campos com '—'.
    """
    vazio = {
        'codec': '—', 'resolucao': '—', 'fps': '—',
        'duracao_seg': 0.0, 'duracao_str': '—', 'frames_total': '—',
        'audio': '', 'camera': '—',
    }
    if not os.path.isfile(str(caminho)):
        return vazio
    try:
        res = subprocess.run(
            [FFPROBE, '-v', 'quiet', '-print_format', 'json',
             '-show_streams', '-show_format', str(caminho)],
            capture_output=True, text=True, timeout=30
        )
        info = json.loads(res.stdout)
    except Exception as e:
        logger.warning(f"ffprobe falhou em {os.path.basename(str(caminho))}: {e}")
        return vazio

    meta = dict(vazio)

    # Vídeo
    for s in info.get('streams', []):
        if s.get('codec_type') == 'video':
            meta['codec'] = (s.get('codec_name') or '—').upper()
            w, h = s.get('width', 0), s.get('height', 0)
            if w and h:
                meta['resolucao'] = f"{w}×{h}"
            fps = s.get('r_frame_rate', '')
            if '/' in fps:
                try:
                    num, den = fps.split('/')
                    val = float(num) / float(den)
                    meta['fps'] = f"{val:.3f}".rstrip('0').rstrip('.') + " fps"
                except Exception:
                    pass
            dur = s.get('duration') or info.get('format', {}).get('duration')
            if dur:
                try:
                    meta['duracao_seg'] = float(dur)
                    meta['duracao_str'] = formatar_duracao(dur)
                except ValueError:
                    pass
            meta['frames_total'] = s.get('nb_frames', '—')
            break

    # Áudio (resumido numa string só)
    for s in info.get('streams', []):
        if s.get('codec_type') == 'audio':
            partes = [(s.get('codec_name') or '').upper()]
            if s.get('channels'):
                partes.append(f"{s['channels']}ch")
            if s.get('sample_rate'):
                partes.append(f"{s['sample_rate']} Hz")
            if s.get('bit_rate'):
                partes.append(f"{int(s['bit_rate'])//1000} kbps")
            meta['audio'] = " · ".join(p for p in partes if p)
            break

    # Modelo da câmera (tags do container)
    tags = info.get('format', {}).get('tags', {})
    make  = tags.get('make')  or tags.get('Make')  or ''
    model = tags.get('model') or tags.get('Model') or ''
    if make or model:
        meta['camera'] = f"{make} {model}".strip()

    # Fallback: o ffprobe costuma não achar a câmera no MP4 da GoPro, mas o
    # exiftool lê o 'CameraModelName' do QuickTime. Tenta quando ainda está '—'.
    if meta['camera'] == '—':
        cam = _camera_via_exiftool(caminho)
        if cam:
            meta['camera'] = cam

    return meta


def _camera_via_exiftool(caminho):
    """Lê o modelo da câmera via exiftool (Make/Model/CameraModelName). '' se falhar."""
    if not os.path.isfile(str(caminho)):
        return ''
    try:
        res = subprocess.run(
            [EXIFTOOL, '-json', '-Make', '-Model', '-CameraModelName', str(caminho)],
            capture_output=True, text=True, timeout=15
        )
        d = (json.loads(res.stdout) or [{}])[0]
    except Exception:
        return ''
    make  = d.get('Make', '')
    model = d.get('Model') or d.get('CameraModelName') or ''
    return f"{make} {model}".strip()


# ── METADADOS DE FOTO (exiftool) ──────────────────────────────────────────────

def extrair_metadados_foto(caminho):
    """Metadados de foto/RAW via exiftool. Nunca lança exceção."""
    vazio = {'resolucao': '—', 'camera': '—', 'data_criacao': '—'}
    if not os.path.isfile(str(caminho)):
        return vazio
    try:
        res = subprocess.run(
            [EXIFTOOL, '-json', '-Make', '-Model',
             '-ImageWidth', '-ImageHeight', '-CreateDate', '-FileModifyDate',
             str(caminho)],
            capture_output=True, text=True, timeout=15
        )
        lista = json.loads(res.stdout)
        d = lista[0] if lista else {}
    except Exception as e:
        logger.warning(f"exiftool falhou em {os.path.basename(str(caminho))}: {e}")
        return vazio

    meta = dict(vazio)
    make, model = d.get('Make', ''), d.get('Model', '')
    if make or model:
        meta['camera'] = f"{make} {model}".strip()
    w, h = d.get('ImageWidth', 0), d.get('ImageHeight', 0)
    if w and h:
        meta['resolucao'] = f"{w}×{h}"
    data = d.get('CreateDate') or d.get('FileModifyDate', '')
    if data:
        meta['data_criacao'] = str(data).replace(':', '-', 2).split('+')[0].strip()
    return meta


# ── PROXIES GoPro ─────────────────────────────────────────────────────────────

def _thm_de(caminho_arquivo):
    """Caminho do .THM (thumbnail nativo) com mesmo prefixo, ou None."""
    thm = Path(caminho_arquivo).with_suffix('.THM')
    return str(thm) if thm.exists() else None


def _lrv_de_video(caminho_video):
    """
    Caminho do .LRV (proxy de baixa resolução) para um vídeo GoPro, ou None.
    GoPro nomeia GX019385.MP4 → GL019385.LRV (troca a 2ª letra por 'L').
    """
    p = Path(caminho_video)
    stem = p.stem
    if len(stem) >= 2 and stem[0] == 'G' and stem[1] in ('X', 'H', 'S'):
        lrv = p.parent / (stem[0] + 'L' + stem[2:] + '.LRV')
        if lrv.exists():
            return str(lrv)
    return None


# ── EXTRAÇÃO DE THUMBNAILS ────────────────────────────────────────────────────

def _salvar_pil(img_pil, destino, lado_max=480):
    """Redimensiona (mantendo proporção) e salva como JPEG. True se deu certo."""
    try:
        img_pil = img_pil.convert('RGB')
        img_pil.thumbnail((lado_max, lado_max), PILImage.LANCZOS)
        img_pil.save(destino, 'JPEG', quality=85)
        return True
    except Exception:
        return False


def _frame_ffmpeg(fonte, instante_seg, destino):
    """Extrai 1 frame do vídeo 'fonte' no instante dado. True se deu certo."""
    try:
        subprocess.run(
            [FFMPEG, '-ss', str(instante_seg), '-i', str(fonte),
             '-vframes', '1', '-q:v', '3', '-vf', 'scale=480:-2', '-y', str(destino)],
            capture_output=True, timeout=40
        )
        return os.path.isfile(destino) and os.path.getsize(destino) > 200
    except Exception:
        return False


def thumbnails_de_video(caminho_video, pasta_frames, nome_base):
    """
    Gera N thumbnails de um vídeo (divisão uniforme no tempo).
    Usa o .LRV (proxy) como fonte quando existe — muito mais rápido.
    Idempotente: se a miniatura já existe, reaproveita.
    Retorna (lista_de_caminhos, nome_da_fonte_usada).
    """
    caminho_video = str(caminho_video)
    if not os.path.isfile(caminho_video):
        return [], None

    lrv = _lrv_de_video(caminho_video)
    fonte = lrv if lrv else caminho_video
    nome_fonte = os.path.basename(fonte)

    # Duração (da fonte que vamos amostrar)
    duracao = 0.0
    try:
        res = subprocess.run(
            [FFPROBE, '-v', 'quiet', '-print_format', 'json', '-show_format', fonte],
            capture_output=True, text=True, timeout=20
        )
        duracao = float(json.loads(res.stdout).get('format', {}).get('duration', 0))
    except Exception:
        duracao = 0.0
    if duracao <= 0:
        duracao = 30.0  # fallback prudente

    n = numero_de_frames(duracao)
    instantes = instantes_para_amostrar(duracao, n)

    caminhos = []
    for i, ts in enumerate(instantes):
        destino = os.path.join(pasta_frames, f"{nome_base}_{i}.jpg")
        if os.path.isfile(destino) and os.path.getsize(destino) > 200:
            caminhos.append(destino)          # idempotência: reaproveita
            continue
        if _frame_ffmpeg(fonte, ts, destino):
            caminhos.append(destino)

    return caminhos, nome_fonte


def thumbnail_de_foto(caminho_foto, pasta_frames, nome_base):
    """
    Gera 1 thumbnail de foto/RAW.
      JPEG/PNG  → Pillow direto.
      .GPR/RAW  → .THM irmão (GoPro) se existir; senão JPEG embutido via exiftool.
    Idempotente. Retorna (caminho | None, fonte_usada | None).
    """
    caminho_foto = str(caminho_foto)
    if not os.path.isfile(caminho_foto):
        return None, None

    destino = os.path.join(pasta_frames, f"{nome_base}_0.jpg")
    if os.path.isfile(destino) and os.path.getsize(destino) > 200:
        return destino, "(cache)"

    ext = Path(caminho_foto).suffix.lower()

    # 1) JPEG / PNG: Pillow direto
    if ext in ('.jpg', '.jpeg', '.png') and PILLOW_DISPONIVEL:
        try:
            if _salvar_pil(PILImage.open(caminho_foto), destino):
                return destino, os.path.basename(caminho_foto)
        except Exception:
            pass

    # 2) RAW (.GPR/.DNG/etc.): usa o JPG irmão de mesmo nome, se existir.
    #    GoPro salva GOPR9400.JPG + GOPR9400.GPR (mesma foto, dois formatos).
    if PILLOW_DISPONIVEL:
        for ext_irmao in ('.JPG', '.jpg', '.JPEG', '.jpeg'):
            irmao = Path(caminho_foto).with_suffix(ext_irmao)
            if irmao.exists():
                try:
                    if _salvar_pil(PILImage.open(str(irmao)), destino):
                        return destino, os.path.basename(str(irmao))
                except Exception:
                    pass

    # 2b) Senão, tenta o .THM irmão (alguns modos geram thumbnail nativo)
    thm = _thm_de(caminho_foto)
    if thm and PILLOW_DISPONIVEL:
        try:
            if _salvar_pil(PILImage.open(thm), destino):
                return destino, os.path.basename(thm)
        except Exception:
            pass

    # 3) RAW genérico: JPEG embutido via exiftool
    for flag in ('-ThumbnailImage', '-PreviewImage', '-JpgFromRaw'):
        try:
            res = subprocess.run([EXIFTOOL, '-b', flag, caminho_foto],
                                 capture_output=True, timeout=15)
            if res.stdout and len(res.stdout) > 500:
                with open(destino, 'wb') as f:
                    f.write(res.stdout)
                return destino, f"exiftool {flag}"
        except Exception:
            pass

    return None, None


# ── LEITURA DO .sppo (lista de arquivos + caminhos) ───────────────────────────

def _ler_sppo(caminho_sppo):
    """
    Parser mínimo do .sppo (sem depender do reportlab/gerador de PDF).
    Retorna (pasta_destino, source_root, [arquivos]) onde cada arquivo é
    {nome, src_path, tamanho}.
    """
    tree = ET.parse(caminho_sppo)
    root = tree.getroot()

    # Origem (ATENÇÃO: ElementTree trata elemento sem filhos como falsy → use is None)
    origem = root.find(".//source")
    if origem is None:
        origem = root.find(".//Source")
    source_root = _buscar(origem, "path", "Path") if origem is not None else ""

    # Destino
    pasta_destino = ""
    dest = root.find(".//destination")
    if dest is None:
        dest = root.find(".//Destination")
    if dest is not None:
        pasta_destino = _buscar(dest, "path", "Path", "volume", "Volume")

    # Arquivos
    arquivos = []
    for arq in root.findall(".//file") + root.findall(".//File"):
        src = _buscar(arq, "src", "Src", "source", "Source", "path")
        nome = os.path.basename(src) if src else _buscar(arq, "name", "Name")
        arquivos.append({
            "nome": nome or "(sem nome)",
            "src_path": src or "",
            "tamanho": _buscar(arq, "size", "Size", "fileSize") or "0",
        })
    return pasta_destino, source_root, arquivos


def _caminho_no_destino(src_path, source_root, pasta_destino):
    """Reconstrói o caminho do arquivo dentro da pasta de destino."""
    if src_path and source_root and pasta_destino:
        rel = src_path[len(source_root):].lstrip('/')
        return os.path.join(pasta_destino, rel)
    nome = os.path.basename(src_path) if src_path else ""
    return os.path.join(pasta_destino, nome) if pasta_destino else nome


def _listar_pasta(pasta_destino):
    """
    Quando não há .sppo: varre a pasta de destino e devolve a lista de arquivos
    no mesmo formato de _ler_sppo (nome, src_path = caminho real, tamanho).
    """
    arquivos = []
    for raiz, _dirs, nomes in os.walk(pasta_destino):
        # ignora a própria pasta de frames e ocultos
        if os.path.basename(raiz).startswith('.') or '_GMA_frames' in raiz:
            continue
        for nome in nomes:
            if nome.startswith('.'):
                continue
            caminho = os.path.join(raiz, nome)
            try:
                tam = os.path.getsize(caminho)
            except OSError:
                tam = 0
            arquivos.append({"nome": nome, "src_path": caminho, "tamanho": str(tam)})
    return arquivos


# ── FUNÇÃO PRINCIPAL: GERAR O MANIFESTO ───────────────────────────────────────

def gerar_manifesto(caminho_sppo=None, pasta_destino=None, pasta_frames=None):
    """
    Gera o manifesto de mídia (metadados + frames) de um cartão já copiado.

    Informe UM dos dois:
      caminho_sppo   — caminho do .sppo (recomendado: alinha com a integridade)
      pasta_destino  — pasta do destino já verificado (varre os arquivos)

    pasta_frames (opcional) — onde salvar as miniaturas. Padrão: subpasta
      `_GMA_frames/` ao lado do relatório. NUNCA toca nos arquivos de mídia.

    Retorna o dicionário do manifesto e grava `..._manifesto.json` no disco.
    """
    _ferramentas_ok()

    # ── Descobre a lista de arquivos e a pasta de destino ─────────────────────
    if caminho_sppo:
        pasta_destino, source_root, arquivos = _ler_sppo(caminho_sppo)
        base_saida = os.path.splitext(caminho_sppo)[0]   # ..._022552
        job = os.path.basename(pasta_destino) if pasta_destino else "cartao"
    elif pasta_destino:
        source_root = pasta_destino
        arquivos = _listar_pasta(pasta_destino)
        job = os.path.basename(os.path.normpath(pasta_destino))
        base_saida = os.path.join(pasta_destino, job)
    else:
        raise ValueError("Informe caminho_sppo ou pasta_destino.")

    if not pasta_destino or not os.path.isdir(pasta_destino):
        raise FileNotFoundError(f"Pasta de destino não encontrada: {pasta_destino}")

    # ── Prepara a pasta de frames (não destrutivo) ────────────────────────────
    if pasta_frames is None:
        pasta_frames = os.path.join(pasta_destino, "_GMA_frames")
    os.makedirs(pasta_frames, exist_ok=True)

    arquivos_midia = [a for a in arquivos if eh_midia(a["nome"])]
    logger.info(f"MANIFESTO | Job: {job} | Total: {len(arquivos)} | "
                f"Mídia: {len(arquivos_midia)} | Frames em: {pasta_frames}")

    # ── Processa cada arquivo de mídia ────────────────────────────────────────
    itens = []
    for n, arq in enumerate(arquivos_midia, start=1):
        nome = arq["nome"]
        tipo = classificar_arquivo(nome)
        caminho = _caminho_no_destino(arq["src_path"], source_root, pasta_destino)
        nome_base = nome.replace('.', '_').replace(' ', '_')

        # caminho relativo à pasta de destino (útil para PDF/CSV/painel)
        try:
            rel = os.path.relpath(caminho, pasta_destino)
        except ValueError:
            rel = nome

        item = {
            "nome": nome,
            "caminho_rel": rel,
            "tipo": tipo,
            "tamanho": int(arq["tamanho"]) if str(arq["tamanho"]).isdigit() else 0,
            "thumbnails": [],       # caminhos relativos ao .json
            "fonte_frames": None,
        }

        if tipo == 'video':
            meta = extrair_metadados_video(caminho)
            item.update({
                "codec": meta['codec'], "resolucao": meta['resolucao'],
                "fps": meta['fps'], "duracao_seg": round(meta['duracao_seg'], 2),
                "duracao_str": meta['duracao_str'], "frames_total": meta['frames_total'],
                "audio": meta['audio'], "camera": meta['camera'],
            })
            thumbs, fonte = thumbnails_de_video(caminho, pasta_frames, nome_base)
        else:  # foto
            meta = extrair_metadados_foto(caminho)
            item.update({
                "resolucao": meta['resolucao'], "camera": meta['camera'],
                "data_criacao": meta['data_criacao'],
            })
            t, fonte = thumbnail_de_foto(caminho, pasta_frames, nome_base)
            thumbs = [t] if t else []

        # guarda os caminhos das miniaturas relativos à pasta do manifesto
        pasta_json = os.path.dirname(base_saida)
        item["thumbnails"]   = [os.path.relpath(t, pasta_json) for t in thumbs]
        item["fonte_frames"] = fonte

        itens.append(item)
        logger.info(f"  [{n}/{len(arquivos_midia)}] {nome} | {tipo} | "
                    f"{len(thumbs)} frame(s)"
                    + (f" (fonte: {fonte})" if fonte else ""))

    # ── Monta e grava o manifesto ─────────────────────────────────────────────
    manifesto = {
        "job": job,
        "pasta_destino": pasta_destino,
        "gerado_em": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "total_arquivos": len(arquivos),
        "total_midia": len(arquivos_midia),
        "pasta_frames": os.path.relpath(pasta_frames, os.path.dirname(base_saida)),
        "arquivos": itens,
    }

    caminho_manifesto = base_saida + "_manifesto.json"
    with open(caminho_manifesto, "w", encoding="utf-8") as f:
        json.dump(manifesto, f, ensure_ascii=False, indent=2)

    total_thumbs = sum(len(i["thumbnails"]) for i in itens)
    logger.info(f"MANIFESTO GRAVADO | {caminho_manifesto} | "
                f"{len(itens)} mídia(s), {total_thumbs} frame(s)")
    manifesto["_caminho_manifesto"] = caminho_manifesto
    return manifesto


# ── PONTO DE ENTRADA (uso direto via terminal) ────────────────────────────────

def main():
    argv = sys.argv[1:]
    if not argv:
        print("Uso:")
        print("  python3 extrator_frames.py caminho/para/log.sppo")
        print("  python3 extrator_frames.py --pasta caminho/da/pasta_destino")
        sys.exit(1)

    if argv[0] == "--pasta":
        if len(argv) < 2:
            print("Faltou o caminho da pasta após --pasta")
            sys.exit(1)
        manifesto = gerar_manifesto(pasta_destino=argv[1])
    else:
        caminho = argv[0]
        if not os.path.exists(caminho):
            print(f"Arquivo não encontrado: {caminho}")
            sys.exit(1)
        manifesto = gerar_manifesto(caminho_sppo=caminho)

    print()
    print(f"Job:           {manifesto['job']}")
    print(f"Arquivos:      {manifesto['total_arquivos']}  "
          f"(mídia: {manifesto['total_midia']})")
    print(f"Frames totais: {sum(len(i['thumbnails']) for i in manifesto['arquivos'])}")
    print(f"Manifesto:     {manifesto['_caminho_manifesto']}")


if __name__ == "__main__":
    main()
