#!/usr/bin/env python3
"""
ler_cartao.py
Leitura e identificação de cartão de memória para o sistema GMA.

Lê uma pasta (cartão ou qualquer pasta), identifica os tipos de material por
extensão, tenta deduzir o modelo de câmera pelos padrões de nome de arquivo,
detecta o intervalo de datas de captura e avisa quando os arquivos abrangem
mais de um dia (cenário de cartão não formatado).

NÃO depende de nenhuma biblioteca externa — usa só a biblioteca padrão do Python.
As datas são lidas do sistema de arquivos (data de modificação), já que ler EXIF
exigiria uma biblioteca externa.

Uso:
    python ler_cartao.py /caminho/para/o/cartao

Exemplo:
    python ler_cartao.py /Volumes/CARTAO_SD
"""

import os
import sys
from datetime import datetime, date


# ── CLASSIFICAÇÃO DE MATERIAL POR EXTENSÃO ────────────────────────────────────

EXTENSOES = {
    "VIDEO": {
        ".mov", ".mp4", ".m4v", ".mxf", ".avi", ".mts", ".m2ts",
        ".r3d", ".braw", ".ari", ".arx", ".dpx",
    },
    "FOTO": {
        ".jpg", ".jpeg", ".png", ".tiff", ".tif", ".heic", ".heif",
        ".cr2", ".cr3", ".nef", ".arw", ".dng", ".raf", ".rw2", ".orf", ".raw",
        ".gpr",  # GoPro RAW (a foto crua que acompanha o .jpg) — antes caía em OUTRO
    },
    "AUDIO": {
        ".wav", ".bwf", ".aif", ".aiff", ".mp3", ".flac", ".m4a",
    },
    # PROXY = cópia derivada de baixa resolução, GRAVADA junto do clipe principal
    # pela própria câmera. NÃO é mídia primária: não conta como vídeo separado e
    # não gera frames — o report usa sempre o original. Fica ligado ao clipe pelo
    # número do nome (ver proxy_do_clipe).
    #   .lrv = Low Resolution Video — o proxy que a GoPro grava ao lado do .mp4
    "PROXY": {
        ".lrv",
    },
}


def classificar_extensao(nome_arquivo):
    """Retorna VIDEO, FOTO, AUDIO, PROXY ou OUTRO conforme a extensão."""
    _, ext = os.path.splitext(nome_arquivo.lower())
    for tipo, exts in EXTENSOES.items():
        if ext in exts:
            return tipo
    return "OUTRO"


def proxy_do_clipe(nome_arquivo):
    """
    Dado um arquivo de PROXY, devolve o NOME do clipe principal a que ele
    pertence — ou None se não for proxy ou se não souber a convenção da câmera.

    Convenção GoPro: o proxy `GL019385.LRV` acompanha o vídeo `GX019385.MP4`
    (mesma numeração, só muda o prefixo GL→GX). É uma pista por nome — quem é a
    autoridade da identidade continua sendo o Matcher ([[identidade-cartao-camadas]]).
    """
    if classificar_extensao(nome_arquivo) != "PROXY":
        return None
    base, _ext = os.path.splitext(nome_arquivo)
    # GoPro: GL<numero> → GX<numero>.MP4
    if base.upper().startswith("GL") and len(base) > 2:
        return "GX" + base[2:] + ".MP4"
    return None


# ── DEDUÇÃO DE MODELO DE CÂMERA POR PADRÃO DE NOME ────────────────────────────

# Cada entrada: (texto a procurar no nome do arquivo, modelo/câmera provável)
# A busca é case-insensitive e por prefixo/conteúdo do nome.
PADROES_CAMERA = [
    ("DJI_",   "DJI (drone ou Osmo)"),
    ("GOPR",   "GoPro"),
    ("GX",     "GoPro"),
    ("GH",     "Panasonic GH"),
    ("MVI_",   "Canon (vídeo)"),
    ("IMG_",   "Canon / iPhone"),
    ("DSC_",   "Nikon"),
    ("_DSC",   "Sony"),
    ("C0",     "Sony (XAVC)"),
    ("A0",     "RED / ARRI (clip)"),
    ("B0",     "RED / ARRI (clip)"),
    ("BMPCC",  "Blackmagic Pocket"),
    (".R3D",   "RED"),
    (".BRAW",  "Blackmagic"),
    (".ARI",   "ARRI"),
    (".CR2",   "Canon"),
    (".CR3",   "Canon"),
    (".NEF",   "Nikon"),
    (".ARW",   "Sony"),
    (".RAF",   "Fujifilm"),
    (".RW2",   "Panasonic"),
]


def deduzir_camera(nome_arquivo):
    """Tenta deduzir o modelo de câmera pelo padrão do nome. Retorna None se não achar."""
    nome_upper = nome_arquivo.upper()
    for padrao, camera in PADROES_CAMERA:
        if padrao.upper() in nome_upper:
            return camera
    return None


# ── VARREDURA DA PASTA ────────────────────────────────────────────────────────

def varrer_pasta(caminho):
    """
    Percorre a pasta (e subpastas) e coleta informações de cada arquivo.
    Retorna a lista de arquivos com tipo, câmera deduzida, data e tamanho.
    """
    arquivos = []

    for raiz, _dirs, nomes in os.walk(caminho):
        for nome in nomes:
            # Ignora arquivos ocultos do sistema (ex.: .DS_Store no Mac)
            if nome.startswith("."):
                continue

            caminho_completo = os.path.join(raiz, nome)

            try:
                tamanho = os.path.getsize(caminho_completo)
                mtime = os.path.getmtime(caminho_completo)
                data_arquivo = datetime.fromtimestamp(mtime)
            except OSError:
                continue

            arquivos.append({
                "nome":     nome,
                "tipo":     classificar_extensao(nome),
                "camera":   deduzir_camera(nome),
                "data":     data_arquivo,
                "tamanho":  tamanho,
            })

    return arquivos


# ── UTILITÁRIOS DE EXIBIÇÃO ───────────────────────────────────────────────────

def formatar_tamanho(bytes_val):
    """Converte bytes para texto legível (KB, MB, GB, TB)."""
    b = float(bytes_val)
    for unidade in ["B", "KB", "MB", "GB", "TB"]:
        if b < 1024:
            return f"{b:.1f} {unidade}"
        b /= 1024
    return f"{b:.1f} PB"


# ── ANÁLISE E RELATÓRIO ───────────────────────────────────────────────────────

def analisar(arquivos):
    """Monta um resumo a partir da lista de arquivos varridos."""
    if not arquivos:
        return None

    # Contagem por tipo
    contagem_tipo = {}
    tamanho_total = 0
    for a in arquivos:
        contagem_tipo[a["tipo"]] = contagem_tipo.get(a["tipo"], 0) + 1
        tamanho_total += a["tamanho"]

    # Câmeras detectadas
    cameras = sorted({a["camera"] for a in arquivos if a["camera"]})

    # Intervalo de datas
    datas = sorted(a["data"] for a in arquivos)
    data_inicio = datas[0]
    data_fim = datas[-1]

    # Dias distintos abrangidos
    dias = sorted({d.date() for d in datas})

    return {
        "total":         len(arquivos),
        "contagem_tipo": contagem_tipo,
        "tamanho_total": tamanho_total,
        "cameras":       cameras,
        "data_inicio":   data_inicio,
        "data_fim":      data_fim,
        "dias":          dias,
    }


def imprimir_relatorio(caminho, resumo):
    """Imprime o relatório no terminal."""
    print()
    print("=" * 56)
    print("  GMA — Leitura de cartão")
    print("=" * 56)
    print(f"  Pasta analisada: {caminho}")
    print()

    if resumo is None:
        print("  Nenhum arquivo de mídia encontrado nesta pasta.")
        print()
        return

    print(f"  Total de arquivos: {resumo['total']}")
    print(f"  Tamanho total:     {formatar_tamanho(resumo['tamanho_total'])}")
    print()

    print("  Material por tipo:")
    for tipo, qtd in sorted(resumo["contagem_tipo"].items()):
        print(f"    {tipo:<8} {qtd}")
    print()

    if resumo["cameras"]:
        print("  Câmeras detectadas:")
        for cam in resumo["cameras"]:
            print(f"    - {cam}")
    else:
        print("  Câmeras detectadas: nenhuma (padrão de nome não reconhecido)")
    print()

    print(f"  Primeira captura: {resumo['data_inicio'].strftime('%d/%m/%Y %H:%M')}")
    print(f"  Última captura:   {resumo['data_fim'].strftime('%d/%m/%Y %H:%M')}")
    print()

    # Alerta de cartão não formatado (arquivos de múltiplos dias)
    if len(resumo["dias"]) > 1:
        print("  " + "!" * 52)
        print("  ATENÇÃO: arquivos de mais de um dia neste cartão.")
        print(f"  Dias encontrados: {', '.join(d.strftime('%d/%m/%Y') for d in resumo['dias'])}")
        print("  Possível cartão NÃO FORMATADO. Verifique antes de copiar.")
        print("  " + "!" * 52)
        print()
    else:
        print(f"  Tudo de um único dia: {resumo['dias'][0].strftime('%d/%m/%Y')}  (ok)")
        print()

    print("=" * 56)
    print()


# ── EXTRAÇÃO DE PREFIXO E NÚMERO DE ARQUIVO ──────────────────────────────────

def extrair_prefixo_e_numero(nome_arquivo):
    """
    Separa o prefixo de texto e o número sequencial de um nome de arquivo.

    Remove a extensão, depois procura o ÚLTIMO grupo de dígitos contíguos
    no fim do nome — esse grupo é o número; tudo que vem antes é o prefixo.

    Exemplos:
      "GOPR0001.MP4"      → ("GOPR",      1)
      "IMG_4521.CR3"      → ("IMG_",   4521)
      "DSC01234.ARW"      → ("DSC",    1234)
      "_DSC4521.ARW"      → ("_DSC",   4521)
      "DJI_0001_0002.MP4" → ("DJI_0001_",  2)   ← último grupo
      "arquivo.mov"       → ("arquivo",  None)   ← sem dígitos no fim

    Parâmetros:
      nome_arquivo — string com o nome do arquivo (pode ou não ter extensão)

    Retorna uma tupla (prefixo_str, numero_int_ou_None).
    """
    import re

    # Remove a extensão para trabalhar só com o nome base
    nome_base, _ = os.path.splitext(nome_arquivo)

    # Procura o ÚLTIMO grupo de dígitos que termina o nome base
    # Padrão: qualquer coisa + (grupo de dígitos) no fim da string
    correspondencia = re.search(r'^(.*?)(\d+)$', nome_base)

    if correspondencia:
        prefixo = correspondencia.group(1)   # tudo antes dos dígitos finais
        numero  = int(correspondencia.group(2))  # os dígitos finais como inteiro
        return (prefixo, numero)
    else:
        # Nome sem dígitos no fim — retorna o nome base como prefixo, número None
        return (nome_base, None)


def extrair_assinatura(lista_arquivos):
    """
    Analisa a lista retornada por varrer_pasta() e extrai a "assinatura" do cartão.

    A assinatura é um dicionário parcial com as características observáveis
    apenas a partir dos arquivos: câmera, prefixos de nome, e faixa de numeração.
    O campo "modelo" NÃO é preenchido aqui — ele vem do exiftool e é adicionado
    pelo leitor_midia.py.

    Considera apenas arquivos de mídia (VIDEO, FOTO, AUDIO) — tipo OUTRO é ignorado.

    Retorna:
      {
        "camera":   str ou None,       # marca mais comum detectada (ou None)
        "prefixos": [str, ...],        # prefixos distintos, mais frequentes primeiro
        "num_min":  int ou None,       # menor número sequencial encontrado
        "num_max":  int ou None,       # maior número sequencial encontrado
      }

    Parâmetros:
      lista_arquivos — lista de dicionários retornada por varrer_pasta()
    """
    from collections import Counter

    # Filtra para considerar apenas arquivos de mídia (ignora tipo OUTRO)
    tipos_midia = {"VIDEO", "FOTO", "AUDIO"}
    midias = [a for a in lista_arquivos if a.get("tipo") in tipos_midia]

    if not midias:
        # Cartão sem mídia — assinatura vazia
        return {
            "camera":   None,
            "prefixos": [],
            "num_min":  None,
            "num_max":  None,
        }

    # ── Câmera predominante ───────────────────────────────────────────────────
    # Conta as marcas detectadas; a câmera mais comum vira a câmera do cartão
    contagem_cameras = Counter(
        a["camera"] for a in midias if a.get("camera")
    )
    camera_predominante = contagem_cameras.most_common(1)[0][0] if contagem_cameras else None

    # ── Prefixos e números sequenciais ───────────────────────────────────────
    contagem_prefixos = Counter()
    numeros_encontrados = []

    for arq in midias:
        prefixo, numero = extrair_prefixo_e_numero(arq["nome"])

        # Acumula o prefixo (ignora prefixo vazio ou só espaços)
        if prefixo and prefixo.strip():
            contagem_prefixos[prefixo] += 1

        # Acumula o número (ignora None)
        if numero is not None:
            numeros_encontrados.append(numero)

    # Prefixos ordenados por frequência (mais comuns primeiro), sem duplicatas
    prefixos_ordenados = [p for p, _ in contagem_prefixos.most_common()]

    # Faixa de numeração: menor e maior número encontrado nos arquivos de mídia
    num_min = min(numeros_encontrados) if numeros_encontrados else None
    num_max = max(numeros_encontrados) if numeros_encontrados else None

    return {
        "camera":   camera_predominante,
        "prefixos": prefixos_ordenados,
        "num_min":  num_min,
        "num_max":  num_max,
    }


# ── PONTO DE ENTRADA ──────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print("Uso:     python ler_cartao.py /caminho/para/o/cartao")
        print("Exemplo: python ler_cartao.py /Volumes/CARTAO_SD")
        sys.exit(1)

    caminho = sys.argv[1]

    if not os.path.isdir(caminho):
        print(f"Pasta não encontrada: {caminho}")
        sys.exit(1)

    arquivos = varrer_pasta(caminho)
    resumo = analisar(arquivos)
    imprimir_relatorio(caminho, resumo)


if __name__ == "__main__":
    main()
