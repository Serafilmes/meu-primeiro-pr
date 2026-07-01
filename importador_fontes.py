#!/usr/bin/env python3
"""
importador_fontes.py
Camada 1 do GMA — Central de Entrada (importação de fontes).

Responsabilidade:
  - Ler uma FONTE externa de vocabulário (nesta fatia: uma planilha remota do
    Google Sheets, pelo link) e devolver as colunas + linhas como texto, para o
    operador REVISAR antes de virar vocabulário oficial das listas.

Princípios respeitados:
  - CUSTO MÍNIMO / OFFLINE-FIRST: usa só a biblioteca padrão do Python (urllib +
    csv). Nenhuma dependência nova, nenhuma chave, nenhuma IA. É leitura mecânica.
  - SEGURANÇA DA MÍDIA: este módulo NÃO toca em arquivo de mídia. Só lê texto de
    uma planilha e devolve em memória. Nada é gravado no banco aqui — quem grava é
    o Flask, e só DEPOIS que o operador confirma (nada entra cru).
  - BEST-EFFORT: a importação só acontece quando o operador pede explicitamente;
    qualquer falha de rede/formato vira uma mensagem clara, nunca derruba o sistema.

Fluxo (o Flask orquestra):
    link do operador → ler_planilha_remota(link) → (colunas, linhas)
    → operador escolhe a coluna + o grupo de destino → revisa → confirma
    → o Flask chama banco_dados.adicionar_item_lista() item a item.
"""

import csv
import io
import re
import urllib.request
import urllib.error
from html.parser import HTMLParser


# Erro de domínio: mensagem já pronta para mostrar ao operador (em português).
class ErroImportacao(Exception):
    """Falha esperada na importação (link inválido, planilha privada, rede)."""
    pass


def _baixar_bytes(url, tempo_limite=15):
    """
    Baixa o conteúdo bruto de uma URL (bytes). Traduz qualquer falha esperada de
    rede em ErroImportacao com mensagem amigável. Usado pela planilha E pela
    página de site — um só ponto de rede.
    """
    try:
        requisicao = urllib.request.Request(
            url, headers={"User-Agent": "GMA-Importador/1.0"}
        )
        with urllib.request.urlopen(requisicao, timeout=tempo_limite) as resposta:
            return resposta.read()
    except urllib.error.HTTPError as err:
        if err.code in (401, 403):
            raise ErroImportacao(
                "O endereço não está acessível. Se for uma planilha, deixe-a com "
                "'qualquer pessoa com o link pode ver' e tente de novo."
            )
        if err.code == 404:
            raise ErroImportacao("Endereço não encontrado — confira o link.")
        raise ErroImportacao(f"O servidor respondeu com erro {err.code}. Tente de novo.")
    except urllib.error.URLError:
        raise ErroImportacao(
            "Não consegui acessar o endereço. Verifique a internet e o link."
        )
    except Exception as err:  # rede imprevisível — nunca deixa vazar exceção crua
        raise ErroImportacao(f"Falha ao ler o endereço: {err}")


def _decodificar(bruto):
    """Bytes → texto, tolerante a codificação (utf-8 com/sem BOM, latin-1)."""
    try:
        return bruto.decode("utf-8-sig")
    except UnicodeDecodeError:
        return bruto.decode("latin-1")


def url_export_csv(link):
    """
    Transforma o link de uma planilha Google na URL de exportação em CSV.

    Aceita as formas comuns que o operador copia do navegador, por ex.:
      https://docs.google.com/spreadsheets/d/<ID>/edit#gid=<GID>
      https://docs.google.com/spreadsheets/d/<ID>/edit?usp=sharing
      https://docs.google.com/spreadsheets/d/<ID>/view
    e monta:
      https://docs.google.com/spreadsheets/d/<ID>/export?format=csv[&gid=<GID>]

    Se o link JÁ for um CSV/endereço direto (não for Google Sheets), devolve como
    veio — assim o mesmo caminho serve para um CSV publicado em qualquer lugar.

    Levanta ErroImportacao se o texto não parecer um endereço utilizável.
    """
    link = (link or "").strip()
    if not link:
        raise ErroImportacao("Cole o link da planilha antes de importar.")

    # É uma planilha do Google? Extrai o ID (o trecho depois de /d/).
    m = re.search(r"/spreadsheets/d/([a-zA-Z0-9_-]+)", link)
    if m:
        planilha_id = m.group(1)
        # gid = a aba específica; se não vier no link, o Google exporta a 1ª aba.
        gid_match = re.search(r"[#&?]gid=([0-9]+)", link)
        url = f"https://docs.google.com/spreadsheets/d/{planilha_id}/export?format=csv"
        if gid_match:
            url += f"&gid={gid_match.group(1)}"
        return url

    # Não é Google Sheets: só aceita http(s) direto (um CSV publicado, p.ex.).
    if link.startswith("http://") or link.startswith("https://"):
        return link

    raise ErroImportacao(
        "Não reconheci o link. Cole o endereço de uma planilha do Google Sheets "
        "(ou o link direto de um arquivo CSV)."
    )


def ler_planilha_remota(link, tempo_limite=15):
    """
    Baixa a planilha remota e devolve (colunas, linhas).

    Returns:
        colunas: lista com os nomes da 1ª linha (cabeçalho). Se a planilha não
                 tiver cabeçalho útil, vira ["Coluna 1", "Coluna 2", ...].
        linhas:  lista de listas (cada linha = os valores das células, como texto).

    Levanta ErroImportacao com mensagem amigável em qualquer falha esperada
    (rede, planilha privada, conteúdo que não é CSV).
    """
    url = url_export_csv(link)
    bruto = _baixar_bytes(url, tempo_limite)

    # O Google devolve HTML (não CSV) quando a planilha é privada / o link é de
    # edição sem permissão — detecta isso para dar uma mensagem clara.
    trecho = bruto[:200].lstrip().lower()
    if trecho.startswith(b"<!doctype html") or trecho.startswith(b"<html"):
        raise ErroImportacao(
            "A planilha veio como página web, não como dados. Confirme que ela está "
            "compartilhada como 'qualquer pessoa com o link pode ver'."
        )

    texto = _decodificar(bruto)
    leitor = csv.reader(io.StringIO(texto))
    todas = [linha for linha in leitor]

    # Remove linhas totalmente vazias (planilhas costumam ter linhas em branco no fim)
    todas = [ln for ln in todas if any((c or "").strip() for c in ln)]
    if not todas:
        raise ErroImportacao("A planilha está vazia.")

    cabecalho = [ (c or "").strip() for c in todas[0] ]
    corpo = todas[1:]

    # Cabeçalho utilizável = tem pelo menos um nome não-vazio. Se não, gera nomes.
    if not any(cabecalho):
        largura = max(len(ln) for ln in todas)
        cabecalho = [f"Coluna {i + 1}" for i in range(largura)]
        corpo = todas  # sem cabeçalho, toda linha é dado

    # Nomeia colunas sem título (buracos no cabeçalho) para não confundir o operador
    cabecalho = [
        nome if nome else f"Coluna {i + 1}"
        for i, nome in enumerate(cabecalho)
    ]

    return cabecalho, corpo


class _ExtratorTexto(HTMLParser):
    """Coleta o TEXTO VISÍVEL de uma página, ignorando script/style/etc.

    Não interpreta JavaScript (a biblioteca padrão não roda JS). Para páginas
    estáticas isso basta; para páginas montadas por JS o texto virá quase vazio
    — e ler_pagina_site avisa o operador a usar a captura com o Chrome (prep).
    """
    IGNORAR = {"script", "style", "noscript", "head", "meta", "link",
               "svg", "path", "template"}

    def __init__(self):
        super().__init__()
        self._ignorando = 0
        self.pedacos = []

    def handle_starttag(self, tag, attrs):
        if tag in self.IGNORAR:
            self._ignorando += 1

    def handle_endtag(self, tag):
        if tag in self.IGNORAR and self._ignorando:
            self._ignorando -= 1

    def handle_data(self, data):
        if self._ignorando:
            return
        texto = data.strip()
        if texto:
            self.pedacos.append(texto)


def ler_pagina_site(link, tempo_limite=15, min_tam=2, max_tam=80):
    """
    Baixa uma PÁGINA DE SITE e devolve a lista de candidatos a item (o texto
    visível, limpo). Pensado para páginas de line-up/grade em que cada linha
    curta é um nome (show, palco, marca).

    Filtro dos candidatos:
      - tira espaços das pontas;
      - descarta vazios e o que estiver fora da faixa de tamanho (parágrafos e
        frases longas não são itens de lista);
      - remove repetições preservando a ordem.

    Se a página voltar praticamente sem texto (típico de site feito em
    JavaScript, como o line-up do Rock in Rio), levanta ErroImportacao com a
    dica de usar a captura assistida (Chrome renderizado, na preparação).

    Returns: lista de strings (candidatos prontos para a revisão do operador).
    """
    link = (link or "").strip()
    if not (link.startswith("http://") or link.startswith("https://")):
        raise ErroImportacao("Cole um endereço de página começando com http:// ou https://.")

    bruto = _baixar_bytes(link, tempo_limite)
    html_texto = _decodificar(bruto)

    parser = _ExtratorTexto()
    try:
        parser.feed(html_texto)
    except Exception:
        pass  # HTML quebrado não deve derrubar nada — usa o que já coletou

    vistos = set()
    candidatos = []
    for pedaco in parser.pedacos:
        valor = pedaco.strip()
        if not valor or not (min_tam <= len(valor) <= max_tam):
            continue
        chave = valor.lower()
        if chave in vistos:
            continue
        vistos.add(chave)
        candidatos.append(valor)

    if len(candidatos) < 3:
        raise ErroImportacao(
            "Esta página quase não trouxe texto — provavelmente é feita em "
            "JavaScript (como o line-up do Rock in Rio). Para páginas assim, me "
            "passe o link numa conversa de preparação: eu capturo com o navegador "
            "renderizado e te devolvo a lista pronta para importar."
        )

    return candidatos


def normalizar_data(texto, ano_padrao=None):
    """
    Converte um valor de data da planilha para o formato ISO 'AAAA-MM-DD', que é
    o que a tabela `programacao` espera. Tolera os formatos comuns em planilhas
    brasileiras:
      2026-09-04  (ISO)          → 2026-09-04
      04/09/2026  (dia/mês/ano)  → 2026-09-04
      04/09       (sem ano)      → usa ano_padrao (ou o ano atual)
      4-9-26      (ano curto)    → 2026-09-04

    Ordem dia/mês (padrão BR), não mês/dia. Devolve None se não conseguir ler —
    aí a linha é marcada na revisão para o operador decidir (nunca chuta o dia).
    """
    from datetime import date
    t = (texto or "").strip()
    if not t:
        return None

    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})$", t)
    if m:
        ano, mes, dia = int(m.group(1)), int(m.group(2)), int(m.group(3))
    else:
        m = re.match(r"^(\d{1,2})[/\-.](\d{1,2})(?:[/\-.](\d{2,4}))?$", t)
        if not m:
            return None
        dia, mes = int(m.group(1)), int(m.group(2))
        if m.group(3):
            ano = int(m.group(3))
            if ano < 100:
                ano += 2000
        else:
            ano = ano_padrao or date.today().year

    try:
        return date(ano, mes, dia).isoformat()
    except ValueError:
        return None


def valores_da_coluna(colunas, linhas, indice_coluna):
    """
    Extrai os valores de UMA coluna, já limpos para virar itens de lista:
      - tira espaços das pontas;
      - descarta vazios;
      - remove repetições preservando a ordem de aparição.

    Returns: lista de strings (os candidatos a item, prontos para revisão).
    """
    vistos = set()
    saida = []
    for linha in linhas:
        if indice_coluna >= len(linha):
            continue
        valor = (linha[indice_coluna] or "").strip()
        if not valor:
            continue
        chave = valor.lower()
        if chave in vistos:
            continue
        vistos.add(chave)
        saida.append(valor)
    return saida


# Execução direta = teste rápido pelo terminal (ajuda o idealizador a conferir).
if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Uso: python3 importador_fontes.py <link-da-planilha>")
        sys.exit(1)
    try:
        cols, rows = ler_planilha_remota(sys.argv[1])
        print(f"Colunas ({len(cols)}): {cols}")
        print(f"Linhas de dados: {len(rows)}")
        for i, nome in enumerate(cols):
            vals = valores_da_coluna(cols, rows, i)
            print(f"  [{i}] {nome!r}: {len(vals)} itens únicos → {vals[:5]}{'…' if len(vals) > 5 else ''}")
    except ErroImportacao as e:
        print(f"ERRO: {e}")
        sys.exit(2)
