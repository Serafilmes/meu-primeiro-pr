#!/usr/bin/env python3
"""
transferencia.py
Camada 2 do GMA — Transferência de arquivos e verificação de integridade.

Responsabilidade:
  - Monitorar a fila_material/ procurando JSONs com status "matched".
  - Montar o caminho de destino correto com base nos dados do formulário.
  - Chamar o copiador.py para executar a cópia com verificação de checksum MD5.
  - Validar a integridade (zero falhos = transferência OK).
  - Gerar o relatório PDF automaticamente.
  - Atualizar o JSON do material com todos os resultados da transferência.

Princípio de segurança:
  Este script NUNCA apaga, move ou renomeia arquivos de mídia.
  Ele apenas lê, monitora e registra. O material original no cartão
  fica intacto até que a Camada 4 (ejeção) decida o que fazer.

Uso:
    python3 /Users/serafa/GMA/transferencia.py

Pré-requisitos:
    pip install reportlab   (para gerar o PDF)
"""

import os
import sys
import json
import time
import logging
from datetime import datetime

# ── CONFIGURAÇÃO DE CAMINHOS E CONSTANTES ─────────────────────────────────────
#
# IMPORTANTE: ajuste PASTA_DESTINO_BASE antes de cada evento.
# As demais constantes só precisam ser alteradas se a estrutura do projeto mudar.

# Raiz do projeto GMA
RAIZ_GMA = "/Users/serafa/GMA"

# Pasta com os JSONs de material detectado (onde buscamos os "casados")
PASTA_FILA_MATERIAL = os.path.join(RAIZ_GMA, "fila_material")

# Pasta com os JSONs de formulários recebidos pelo Flask
PASTA_FILA_FORMS = os.path.join(RAIZ_GMA, "fila_forms")

# Arquivo sentinela: se não existir, o script aguarda sem processar
SENTINELA = os.path.join(RAIZ_GMA, ".gma_ativo")

# NOTA: o motor de cópia é agora o copiador.py (Python puro, MD5).
# O ShotPutPro foi substituído para eliminar dependência de app externo sem CLI.

# Pasta raiz de destino das transferências
# *** TROQUE ESTE VALOR ANTES DE CADA EVENTO ***
# Para testes locais: "/Users/serafa/GMA/TESTE LOGAGEM"
# Para evento real:   "/Volumes/NOME_DO_HD_EXTERNO"
#
# Por padrão usa a pasta de teste de sempre, mas o Painel de Controle (Camada 5)
# pode direcionar a pasta por projeto via a variável GMA_DESTINO — lida no boot,
# exatamente como o GMA_DB do banco. Se a variável não existir, nada muda.
PASTA_DESTINO_BASE = os.environ.get("GMA_DESTINO", "").strip() or "/Users/serafa/GMA/TESTE LOGAGEM"

# Intervalo entre cada varredura da fila_material/ (em segundos)
INTERVALO_POLLING = 5

# Tempo máximo aguardando o ShotPutPro terminar (em segundos)
# Se o log não aparecer dentro deste prazo, marca como falha
TIMEOUT_TRANSFERENCIA = 3600   # 1 hora

# Arquivo de log do processo de transferência
ARQUIVO_LOG = os.path.join(RAIZ_GMA, "logs", "transferencia.log")


# ── IMPORTAÇÃO DO MÓDULO DE PDF ───────────────────────────────────────────────

# Garante que os módulos do GMA sejam encontrados mesmo que o script
# seja chamado de outro diretório
sys.path.insert(0, RAIZ_GMA)

# Motor de cópia OFICIAL: copiador.py (Python puro, MD5, offline-first).
# Decisão de 2026-06-06 (pós-teste com cartão real): o ShotPutPro foi removido
# do ciclo por não se deixar automatizar. O integrador_spp.py (ponte ShotPutPro)
# permanece no repositório como plano B histórico — não apagar, mas não é usado.
import copiador

try:
    from gma_relatorio_pdf import parse_shotputpro_log, gerar_pdf
    MODULO_PDF_DISPONIVEL = True
except (ImportError, SystemExit) as erro_import:
    # O gma_relatorio_pdf chama sys.exit(1) se o reportlab não estiver instalado.
    # Capturamos SystemExit junto com ImportError para não derrubar o processo.
    # Neste caso, o script continua funcionando, apenas sem geração de PDF.
    MODULO_PDF_DISPONIVEL = False
    _ERRO_IMPORT_PDF = str(erro_import)


# ── CONFIGURAÇÃO DO LOGGER ────────────────────────────────────────────────────

def configurar_logger():
    """
    Configura o sistema de log da Transferência.
    Grava em logs/transferencia.log E mostra no terminal.
    Formato padrão GMA: timestamp ISO-8601 | mensagem
    """
    logger = logging.getLogger("transferencia")
    logger.setLevel(logging.DEBUG)

    # Evita duplicar handlers se a função for chamada mais de uma vez
    if logger.handlers:
        return logger

    # Formato padrão do GMA: 2026-06-05T14:32:01 | mensagem
    formato = logging.Formatter(
        fmt="%(asctime)s | %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S"
    )

    # Garante que a pasta de logs existe
    os.makedirs(os.path.dirname(ARQUIVO_LOG), exist_ok=True)

    # Handler de arquivo (append — nunca sobrescreve o histórico)
    handler_arquivo = logging.FileHandler(ARQUIVO_LOG, encoding="utf-8")
    handler_arquivo.setFormatter(formato)
    logger.addHandler(handler_arquivo)

    # Handler de terminal para acompanhamento em tempo real
    handler_terminal = logging.StreamHandler()
    handler_terminal.setFormatter(formato)
    logger.addHandler(handler_terminal)

    return logger


# ── FUNÇÕES AUXILIARES DE JSON ────────────────────────────────────────────────

def ler_json(caminho_arquivo):
    """
    Lê e retorna o conteúdo de um arquivo JSON.
    Retorna None se o arquivo não existir ou estiver corrompido.

    Parâmetros:
      caminho_arquivo — caminho completo do arquivo .json
    """
    try:
        with open(caminho_arquivo, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return None
    except json.JSONDecodeError as erro:
        logging.getLogger("transferencia").error(
            f"JSON CORROMPIDO | {caminho_arquivo} | {erro}"
        )
        return None
    except OSError as erro:
        logging.getLogger("transferencia").error(
            f"ERRO AO LER JSON | {caminho_arquivo} | {erro}"
        )
        return None


def salvar_json(caminho_arquivo, dados):
    """
    Salva um dicionário como JSON no caminho indicado.
    Retorna True se salvou com sucesso, False se deu erro.

    Parâmetros:
      caminho_arquivo — caminho completo do arquivo .json
      dados           — dicionário a ser salvo
    """
    try:
        with open(caminho_arquivo, "w", encoding="utf-8") as f:
            json.dump(dados, f, ensure_ascii=False, indent=2)
        return True
    except OSError as erro:
        logging.getLogger("transferencia").error(
            f"ERRO AO SALVAR JSON | {caminho_arquivo} | {erro}"
        )
        return False


def atualizar_json(caminho_arquivo, atualizacoes):
    """
    Lê um JSON existente, aplica as atualizações do dicionário passado
    e reescreve o arquivo.
    Retorna True se teve sucesso, False se deu erro.

    Parâmetros:
      caminho_arquivo — caminho completo do arquivo .json
      atualizacoes    — dicionário com os campos a sobrescrever
    """
    dados = ler_json(caminho_arquivo)
    if dados is None:
        return False
    dados.update(atualizacoes)
    return salvar_json(caminho_arquivo, dados)


# ── FUNÇÕES DE FILA ───────────────────────────────────────────────────────────

def buscar_materiais_para_transferir():
    """
    Varre a fila_material/ procurando JSONs que:
      - Têm status "matched"  →  foram cruzados com um formulário pelo Matcher
      - NÃO têm "transferencia_iniciada": true  →  ainda não foram pegos por nós

    Retorna uma lista de tuplas: (caminho_completo_do_json, dicionário_de_dados)
    Lista vazia se não houver nenhum pendente.
    """
    logger = logging.getLogger("transferencia")
    resultado = []

    # Se a pasta não existe, retorna vazio sem erro
    if not os.path.isdir(PASTA_FILA_MATERIAL):
        return resultado

    try:
        arquivos = sorted(os.listdir(PASTA_FILA_MATERIAL))
    except OSError as erro:
        logger.error(f"ERRO AO LER FILA | {PASTA_FILA_MATERIAL} | {erro}")
        return resultado

    for nome_arquivo in arquivos:
        if not nome_arquivo.endswith(".json"):
            continue

        caminho_completo = os.path.join(PASTA_FILA_MATERIAL, nome_arquivo)
        dados = ler_json(caminho_completo)

        if dados is None:
            continue

        # Critério de seleção: matched e sem transferência iniciada
        if (
            dados.get("status") == "matched"
            and not dados.get("transferencia_iniciada", False)
        ):
            resultado.append((caminho_completo, dados))

    return resultado


# ── FUNÇÕES DE MONTAGEM DO DESTINO ────────────────────────────────────────────

def proximo_numero_sequencial(nome):
    """
    Retorna o próximo número sequencial para o profissional e já incrementa o contador.

    Usa um arquivo JSON por profissional em GMA/contadores/<NOME>.json.
    Exemplo: contadores/SERAFA.json → {"proximo": 3}
    Ao chamar esta função, o arquivo passa a ter {"proximo": 4}.

    Vantagem sobre contar pastas: não depende de nada no destino.
    Renomear, mover ou apagar pastas não afeta o número do próximo cartão.

    Parâmetros:
      nome — nome do profissional de captação já sanitizado (ex: "SERAFA", "JOAO_CAM")

    Retorna um inteiro (começa em 1 na primeira vez que o profissional aparece).
    """
    logger = logging.getLogger("transferencia")

    # Pasta de contadores dentro do projeto GMA
    pasta_contadores = os.path.join(RAIZ_GMA, "contadores")
    os.makedirs(pasta_contadores, exist_ok=True)

    # Um arquivo por profissional: contadores/SERAFA.json
    caminho_contador = os.path.join(pasta_contadores, f"{nome}.json")

    # Lê o contador atual (ou começa em 1 se for o primeiro cartão deste profissional)
    try:
        with open(caminho_contador, "r", encoding="utf-8") as f:
            dados = json.load(f)
        numero_atual = dados.get("proximo", 1)
    except FileNotFoundError:
        # Primeiro cartão deste profissional — começa em 1
        numero_atual = 1
    except (json.JSONDecodeError, OSError) as erro:
        logger.warning(
            f"CONTADOR CORROMPIDO | {caminho_contador} | {erro} | "
            "Usando número 1 como segurança — verifique o arquivo manualmente"
        )
        numero_atual = 1

    # Grava o próximo número antes de retornar
    # (se o sistema cair entre aqui e criar a pasta, o número é "perdido" —
    # aceitável: melhor um número a mais do que dois cartões com o mesmo nome)
    try:
        with open(caminho_contador, "w", encoding="utf-8") as f:
            json.dump({"proximo": numero_atual + 1}, f)
    except OSError as erro:
        logger.error(
            f"ERRO AO GRAVAR CONTADOR | {caminho_contador} | {erro} | "
            "O número será reutilizado no próximo ciclo — risco de colisão de nome"
        )

    logger.info(
        f"CONTADOR | Nome: {nome} | Número atribuído: {numero_atual:03d} | "
        f"Próximo será: {numero_atual + 1:03d}"
    )
    return numero_atual


def montar_caminho_destino(dados_material, dados_form):
    """
    Monta o caminho de destino para a transferência com base nos dados
    do formulário e do material.

    Estrutura do caminho:
      PASTA_DESTINO_BASE / DATA_AAAAMMDD / TIPO_MATERIAL / PRODUTORA / PRODUTORA_NNN

    Exemplo:
      /Volumes/GMA_STORAGE/20260605/VIDEO/PRODUTORA_X/PRODUTORA_X_001

    Parâmetros:
      dados_material — dicionário do JSON do material (fila_material/)
      dados_form     — dicionário do JSON do formulário (fila_forms/)

    Retorna o caminho completo como string, ou None se os dados estiverem incompletos.
    """
    logger = logging.getLogger("transferencia")

    # ── Extrai os campos necessários ──────────────────────────────────────────

    # Data de gravação vem do formulário no formato "AAAA-MM-DD"
    data_gravacao = dados_form.get("data_gravacao", "")
    if not data_gravacao:
        # Tenta usar a data_inicio do material como fallback
        data_gravacao = (dados_material.get("data_inicio") or "")[:10]

    if not data_gravacao:
        logger.error("SEM DATA DE GRAVAÇÃO | Não foi possível montar caminho de destino")
        return None

    # Remove os hifens para o formato AAAAMMDD usado nas pastas
    data_formatada = data_gravacao.replace("-", "")

    # Tipo de material (ex: "VIDEO", "FOTO", "AUDIO")
    tipo_material = (dados_form.get("tipo_material") or "MATERIAL").upper().strip()

    # Nome do profissional de captação — sanitizado para uso seguro em nomes de pasta
    # (ex: "Serafa" → "SERAFA", "João Cam" → "JOAO_CAM")
    nome_bruto = dados_form.get("nome") or "SEM_NOME"
    nome = "".join(
        c if c.isalnum() or c in "-_" else "_"
        for c in nome_bruto.upper().strip()
    )

    # ── Monta o caminho passo a passo ────────────────────────────────────────

    # Pasta do profissional: .../DATA/TIPO/SERAFA/
    pasta_profissional = os.path.join(PASTA_DESTINO_BASE, data_formatada, tipo_material, nome)

    # Busca o próximo número do cartão deste profissional (no arquivo-contador)
    # Conceito: "é o 3º cartão que o fulano entrega neste trabalho"
    numero = proximo_numero_sequencial(nome)

    # Nome final da subpasta: NOME_NNN → JOAO_001, PAULO_005...
    # A pasta carrega o nome do profissional + o número do cartão na sequência dele
    nome_subpasta = f"{nome}_{numero:03d}"

    # Caminho completo de destino: .../JOAO/JOAO_001
    caminho_destino = os.path.join(pasta_profissional, nome_subpasta)

    logger.info(
        f"DESTINO MONTADO | Data: {data_formatada} | Tipo: {tipo_material} | "
        f"Nome: {nome} | Cartão nº: {numero:03d} | Caminho: {caminho_destino}"
    )

    return caminho_destino


def criar_pasta_destino(caminho_destino):
    """
    Cria a pasta de destino se ela ainda não existir.
    Cria todos os diretórios intermediários necessários (como mkdir -p).
    Retorna True se bem-sucedido, False se der erro.

    Parâmetros:
      caminho_destino — caminho completo da pasta a criar
    """
    logger = logging.getLogger("transferencia")
    try:
        os.makedirs(caminho_destino, exist_ok=True)
        logger.info(f"PASTA CRIADA | {caminho_destino}")
        return True
    except OSError as erro:
        logger.error(f"ERRO AO CRIAR PASTA | {caminho_destino} | {erro}")
        return False


# ── NOTA: FUNÇÕES DO SHOTPUTPRO REMOVIDAS ────────────────────────────────────
#
# As funções acionar_shotputpro(), listar_logs_shotputpro() e
# aguardar_log_transferencia() foram removidas nesta versão.
#
# Motivo: o ShotPutPro não possui interface de linha de comando para automação.
# O motor de cópia passou a ser o copiador.py (Python puro, MD5, offline-first),
# que é chamado diretamente em processar_material() no Passo 4.


# ── FUNÇÕES DE VALIDAÇÃO DE INTEGRIDADE ──────────────────────────────────────

def validar_transferencia(caminho_log_xml, dados_material_original):
    """
    Lê o log XML do ShotPutPro e realiza a validação tripla:
      1. Zero falhos conforme o log do ShotPutPro (checksum verificado)
      2. Contagem de arquivos bate (log vs. material detectado pelo Porteiro)
      3. Tamanho total coerente (log vs. material detectado pelo Porteiro)

    A Camada 2 não pode confirmar a transferência sem que todos os critérios
    possíveis de validação apontem para sucesso.

    Parâmetros:
      caminho_log_xml        — caminho do arquivo .sppo gerado pelo ShotPutPro
      dados_material_original — dicionário do JSON do material (para comparação)

    Retorna um dicionário com:
      "ok"              → True se transferência perfeita, False se qualquer problema
      "total_falhos"    → número de arquivos com falha de checksum
      "total_arquivos"  → total de arquivos no log
      "tamanho_bytes"   → tamanho total em bytes conforme o log
      "alertas"         → lista de strings descrevendo problemas encontrados
      "dados_log"       → dicionário completo retornado pelo parser
    """
    logger = logging.getLogger("transferencia")
    alertas = []
    resultado_ok = True

    # ── Lê e parseia o log XML ───────────────────────────────────────────────
    if not MODULO_PDF_DISPONIVEL:
        logger.error(
            f"MÓDULO PDF INDISPONÍVEL | {_ERRO_IMPORT_PDF} | "
            "Não é possível ler o log. Marque como falha e investigue manualmente."
        )
        return {
            "ok": False,
            "total_falhos": -1,
            "total_arquivos": 0,
            "tamanho_bytes": 0,
            "alertas": ["Módulo gma_relatorio_pdf não disponível — log não lido"],
            "dados_log": {},
        }

    try:
        dados_log = parse_shotputpro_log(caminho_log_xml)
    except Exception as erro:
        logger.error(f"ERRO AO PARSEAR LOG | {caminho_log_xml} | {erro}")
        return {
            "ok": False,
            "total_falhos": -1,
            "total_arquivos": 0,
            "tamanho_bytes": 0,
            "alertas": [f"Erro ao ler log XML: {erro}"],
            "dados_log": {},
        }

    # ── Validação 1: checksums (critério principal) ───────────────────────────
    total_falhos = dados_log.get("total_falhos", 0)
    if total_falhos > 0:
        msg = f"CHECKSUM FALHOU | {total_falhos} arquivo(s) com falha de verificação"
        logger.error(msg)
        alertas.append(msg)
        resultado_ok = False
    else:
        logger.info("CHECKSUM OK | Todos os arquivos verificados sem falha")

    # ── Validação 2: contagem de arquivos ────────────────────────────────────
    total_log = dados_log.get("total_arquivos", 0)
    total_original = dados_material_original.get("total_arquivos", 0)

    if total_original and total_original > 0:
        if total_log != total_original:
            msg = (
                f"CONTAGEM DIVERGENTE | Log: {total_log} arquivos | "
                f"Original: {total_original} arquivos | "
                "Pode ter havido arquivos não copiados"
            )
            logger.warning(msg)
            alertas.append(msg)
            # Diferença de contagem gera alerta mas não reprovação automática —
            # o ShotPutPro pode ter excluído arquivos do sistema (.DS_Store, etc.)
            # O operador deve avaliar se a diferença é aceitável.
        else:
            logger.info(
                f"CONTAGEM OK | {total_log} arquivos no log == {total_original} no material"
            )
    else:
        logger.info(
            "CONTAGEM NÃO VERIFICADA | Total do material original não disponível no JSON"
        )

    # ── Validação 3: tamanho total ────────────────────────────────────────────
    tamanho_log = dados_log.get("tamanho_total", 0)
    tamanho_original = dados_material_original.get("tamanho_total_bytes", 0)

    if tamanho_original and tamanho_original > 0 and tamanho_log > 0:
        # Tolerância de 1% para diferenças de metadados do sistema de arquivos
        diferenca_percentual = abs(tamanho_log - tamanho_original) / tamanho_original
        if diferenca_percentual > 0.01:
            msg = (
                f"TAMANHO DIVERGENTE | Log: {tamanho_log} bytes | "
                f"Original: {tamanho_original} bytes | "
                f"Diferença: {diferenca_percentual * 100:.1f}%"
            )
            logger.warning(msg)
            alertas.append(msg)
            # Divergência de tamanho é alerta, não reprovação — o ShotPutPro
            # pode reportar tamanhos diferentes por arquivos do sistema excluídos.
        else:
            logger.info(
                f"TAMANHO OK | {tamanho_log} bytes ≈ {tamanho_original} bytes "
                f"(diferença: {diferenca_percentual * 100:.2f}%)"
            )
    else:
        logger.info("TAMANHO NÃO VERIFICADO | Dados de tamanho incompletos")

    # ── Resultado final ───────────────────────────────────────────────────────
    if resultado_ok and not alertas:
        logger.info("VALIDAÇÃO COMPLETA | Transferência verificada com sucesso (tripla verificação)")
    elif resultado_ok and alertas:
        logger.warning(
            f"VALIDAÇÃO COM ALERTAS | Checksum OK mas {len(alertas)} alerta(s) — "
            "revisar antes de liberar o cartão"
        )
    else:
        logger.error(
            f"VALIDAÇÃO REPROVADA | {len(alertas)} problema(s) encontrado(s) — "
            "NÃO libere o cartão"
        )

    return {
        "ok": resultado_ok,
        "total_falhos": total_falhos,
        "total_arquivos": total_log,
        "tamanho_bytes": tamanho_log,
        "alertas": alertas,
        "dados_log": dados_log,
    }


# ── GERAÇÃO DE RELATÓRIO PDF ─────────────────────────────────────────────────

def gerar_relatorio_pdf(caminho_log_xml, dados_log, dados_match=None):
    """
    Gera o relatório PDF da transferência e o salva na mesma pasta do log .sppo.
    O nome do PDF é o mesmo do log, com sufixo _relatorio.pdf.

    Parâmetros:
      caminho_log_xml — caminho do arquivo .sppo
      dados_log       — dicionário já parseado (retornado por parse_shotputpro_log)
      dados_match     — (opcional) dict do formulário de check-in:
                        {'nome': ..., 'camera': ..., 'tipo_material': ..., 'operador': ...}
                        Exibe dados do profissional na coluna direita do cabeçalho.

    Retorna o caminho do PDF gerado, ou None se a geração falhar.
    """
    logger = logging.getLogger("transferencia")

    if not MODULO_PDF_DISPONIVEL:
        logger.warning("PDF NÃO GERADO | Módulo gma_relatorio_pdf indisponível")
        return None

    # Monta o nome do PDF baseado no nome do log
    base = os.path.splitext(caminho_log_xml)[0]
    caminho_pdf = base + "_relatorio.pdf"

    try:
        gerar_pdf(dados_log, caminho_pdf, dados_match=dados_match)
        logger.info(f"PDF GERADO | {caminho_pdf}")
        return caminho_pdf
    except Exception as erro:
        logger.error(f"ERRO AO GERAR PDF | {erro}")
        return None


# ── PROCESSAMENTO DE UM MATERIAL ──────────────────────────────────────────────

def processar_material(caminho_json_material, dados_material):
    """
    Executa o ciclo completo de transferência para um material.

    Etapas:
      1. Lê o formulário associado (form_match)
      2. Monta e cria a pasta de destino
      3. Registra início no JSON (evita que outro ciclo pegue este material)
      4. Executa a cópia com verificação MD5 via copiador.py (bloqueante)
      5. Valida a integridade (tripla verificação)
      6. Gera o relatório PDF
      7. Atualiza o JSON do material com todos os resultados

    Parâmetros:
      caminho_json_material — caminho completo do JSON do material
      dados_material        — dicionário com os dados do material

    Não retorna valor. Todos os resultados são gravados no JSON do material.
    """
    logger = logging.getLogger("transferencia")
    nome_json = os.path.basename(caminho_json_material)

    logger.info(f"INICIANDO TRANSFERÊNCIA | Material: {nome_json}")

    # ── Passo 1: Lê o formulário associado ───────────────────────────────────
    id_form = dados_material.get("form_match")
    if not id_form:
        logger.error(f"SEM FORMULÁRIO MATCH | Material: {nome_json} | Pulando")
        return

    # O campo form_match pode ser o nome do arquivo completo ou só o ID
    # Tenta ambos os formatos
    caminho_form = os.path.join(PASTA_FILA_FORMS, id_form)
    if not caminho_form.endswith(".json"):
        caminho_form += ".json"

    dados_form = ler_json(caminho_form)
    if dados_form is None:
        logger.error(
            f"FORMULÁRIO NÃO ENCONTRADO | {caminho_form} | "
            "Verifique se o Matcher gravou o nome correto em form_match"
        )
        return

    logger.info(
        f"FORMULÁRIO LIDO | Nome: {dados_form.get('nome')} | "
        f"Câmera: {dados_form.get('camera')} | Tipo: {dados_form.get('tipo_material')}"
    )

    # ── Passo 2: Monta e cria a pasta de destino ──────────────────────────────
    caminho_destino = montar_caminho_destino(dados_material, dados_form)
    if caminho_destino is None:
        logger.error(f"DESTINO INVÁLIDO | Material: {nome_json} | Pulando")
        return

    if not criar_pasta_destino(caminho_destino):
        logger.error(
            f"FALHA AO CRIAR PASTA DE DESTINO | {caminho_destino} | "
            "Verifique se o storage está montado e com espaço disponível"
        )
        return

    # ── Passo 3: Marca transferência como iniciada (evita reprocessamento) ───
    timestamp_inicio = datetime.now()
    timestamp_inicio_str = timestamp_inicio.strftime("%Y-%m-%dT%H:%M:%S")

    sucesso_marcacao = atualizar_json(caminho_json_material, {
        "transferencia_iniciada":  True,
        "transferencia_timestamp_inicio": timestamp_inicio_str,
        "destino_pasta":           caminho_destino,
    })

    if not sucesso_marcacao:
        logger.error(
            f"FALHA AO MARCAR INÍCIO | {nome_json} | "
            "Risco de processamento duplicado. Abortando esta transferência."
        )
        return

    # ── Integração Camada 3 (Passo 3): marca início da cópia no banco ────────
    # Este bloco é ADITIVO — se o banco falhar, o fluxo continua normalmente.
    _db_cartao_id = dados_material.get("db_cartao_id")
    try:
        import banco_dados as _bd
        if _db_cartao_id:
            _conn_transf = _bd.inicializar_banco()
            _bd.atualizar_cartao(_conn_transf, _db_cartao_id, {
                "status": "copiando",
                "destino_pasta": caminho_destino,
                "transferencia_timestamp_inicio": timestamp_inicio_str,
            })
            _conn_transf.close()
        else:
            logger.warning("BANCO | db_cartao_id ausente no JSON — início não gravado no banco")
    except Exception as _err_bd:
        logger.error(f"BANCO | Falha ao marcar copiando (fluxo continua) | {_err_bd}")

    # ── Passo 4: Executa a cópia com verificação MD5 (bloqueante) ───────────────
    # copiador.copiar() só retorna quando todos os arquivos foram copiados
    # e verificados. O processo bloqueia aqui até a cópia terminar.
    caminho_origem = dados_material.get("caminho")
    if not caminho_origem:
        logger.error(f"CAMINHO DE ORIGEM AUSENTE | Material: {nome_json}")
        _marcar_falha(caminho_json_material, "Caminho de origem ausente no JSON do material")
        return

    nome_job = os.path.basename(caminho_destino)  # ex: "PRODUTORA_X_001"
    logger.info(f"INICIANDO CÓPIA | Origem: {caminho_origem} → Destino: {caminho_destino}")

    resultado_copia = copiador.copiar(
        caminho_origem=caminho_origem,
        caminho_destino=caminho_destino,
        nome_job=nome_job,
    )

    caminho_log_xml = resultado_copia.get("caminho_log")
    if not caminho_log_xml:
        _marcar_falha(caminho_json_material, "Copiador não gerou arquivo de log")
        return

    # ── Passo 5: Valida a integridade (tripla verificação) ───────────────────
    resultado_validacao = validar_transferencia(caminho_log_xml, dados_material)

    # ── Passo 6: Gera o relatório PDF ────────────────────────────────────────
    caminho_pdf = None
    if resultado_validacao.get("dados_log"):
        caminho_pdf = gerar_relatorio_pdf(caminho_log_xml, resultado_validacao["dados_log"],
                                           dados_match=dados_form)

    # ── Passo 7: Atualiza o JSON do material com todos os resultados ─────────
    timestamp_conclusao = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    transferencia_ok = resultado_validacao.get("ok", False)

    atualizacoes_finais = {
        "transferencia_iniciada":           True,
        "transferencia_concluida":          True,
        "transferencia_ok":                 transferencia_ok,
        "transferencia_timestamp":          timestamp_conclusao,
        "transferencia_log_xml":            caminho_log_xml,
        "total_arquivos_transferidos":      resultado_validacao.get("total_arquivos", 0),
        "total_falhos":                     resultado_validacao.get("total_falhos", 0),
        "tamanho_transferido_bytes":        resultado_validacao.get("tamanho_bytes", 0),
        "transferencia_alertas":            resultado_validacao.get("alertas", []),
    }

    # Adiciona o caminho do PDF se foi gerado
    if caminho_pdf:
        atualizacoes_finais["transferencia_relatorio_pdf"] = caminho_pdf

    # Status final: se transferência falhou, marca para o operador investigar
    if not transferencia_ok:
        atualizacoes_finais["status"] = "transferencia_falhou"
        logger.error(
            f"TRANSFERÊNCIA FALHOU | Material: {nome_json} | "
            f"Alertas: {resultado_validacao.get('alertas', [])}"
        )
    else:
        # Mantém o status "matched" — a Camada 4 irá mudar para "ejetado"
        # quando o cartão for liberado após confirmação de integridade
        logger.info(
            f"TRANSFERÊNCIA CONCLUÍDA COM SUCESSO | Material: {nome_json} | "
            f"Destino: {caminho_destino}"
        )

    atualizar_json(caminho_json_material, atualizacoes_finais)

    # ── Integração Camada 3 (Passo 7): grava resultado final no banco ─────────
    # Este bloco é ADITIVO — se o banco falhar, o fluxo já terminou normalmente.
    # _db_cartao_id foi definido no Passo 3 da mesma função.
    try:
        import banco_dados as _bd
        if _db_cartao_id:
            _conn_transf2 = _bd.inicializar_banco()
            _bd.atualizar_cartao(_conn_transf2, _db_cartao_id, {
                "status": "transferencia_ok" if transferencia_ok else "transferencia_falhou",
                "numero_cartao": nome_job,
                "transferencia_timestamp_fim": timestamp_conclusao,
                "total_arquivos_transferidos": resultado_validacao.get("total_arquivos", 0),
                "total_falhos": resultado_validacao.get("total_falhos", 0),
                "tamanho_transferido_bytes": resultado_validacao.get("tamanho_bytes", 0),
                "transferencia_relatorio_pdf": caminho_pdf,
            })
            # Popula a tabela 'arquivos' com cada arquivo do .sppo
            if resultado_validacao.get("dados_log"):
                qtd = _bd.gravar_arquivos_do_log(
                    _conn_transf2, _db_cartao_id, resultado_validacao["dados_log"]
                )
                logger.info(f"BANCO | {qtd} arquivo(s) gravado(s) na tabela arquivos")
            _conn_transf2.close()
        else:
            logger.warning("BANCO | db_cartao_id ausente no JSON — resultado final não gravado")
    except Exception as _err_bd:
        logger.error(f"BANCO | Falha ao gravar resultado final (fluxo continua) | {_err_bd}")


def _marcar_falha(caminho_json_material, motivo):
    """
    Função interna: marca um material como falha de transferência.
    Usada nos pontos de saída antecipada de processar_material().

    Parâmetros:
      caminho_json_material — caminho do JSON do material
      motivo                — string descrevendo o problema
    """
    logger = logging.getLogger("transferencia")
    timestamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    atualizar_json(caminho_json_material, {
        "transferencia_concluida":  True,
        "transferencia_ok":         False,
        "transferencia_timestamp":  timestamp,
        "transferencia_motivo_falha": motivo,
        "status":                   "transferencia_falhou",
    })

    logger.error(f"FALHA REGISTRADA | {os.path.basename(caminho_json_material)} | {motivo}")


# ── VERIFICAÇÃO DO SENTINELA ──────────────────────────────────────────────────

def sentinela_ativo():
    """
    Retorna True se o arquivo sentinela .gma_ativo existir.
    Quando o sentinela está ausente, o script aguarda sem processar nada.
    """
    return os.path.isfile(SENTINELA)


# ── LOOP PRINCIPAL ────────────────────────────────────────────────────────────

def main():
    """
    Ponto de entrada do processo de transferência.

    Fluxo:
      1. Configura o logger e verifica o ambiente.
      2. Entra em loop de polling (a cada INTERVALO_POLLING segundos):
         a. Verifica se o sentinela está ativo.
         b. Busca materiais na fila com status "matched" e sem transferência iniciada.
         c. Para cada material encontrado, executa o ciclo completo de transferência.
      3. Erros em um material não param o loop — o próximo material é processado.
      4. Encerra ao receber Ctrl+C.
    """
    logger = configurar_logger()

    logger.info(
        f"TRANSFERÊNCIA INICIADA | Polling a cada {INTERVALO_POLLING}s | "
        f"Destino base: {PASTA_DESTINO_BASE}"
    )
    logger.info(f"SENTINELA | {SENTINELA}")
    logger.info(f"MOTOR DE CÓPIA | copiador.py (Python puro + checksum MD5)")

    if not MODULO_PDF_DISPONIVEL:
        logger.warning(
            "AVISO: módulo gma_relatorio_pdf não disponível — relatórios PDF desativados. "
            "Execute: pip install reportlab"
        )

    # Avisa se o storage de destino não está montado (verificação não bloqueante)
    if not os.path.isdir(PASTA_DESTINO_BASE):
        logger.warning(
            f"STORAGE NÃO ENCONTRADO | {PASTA_DESTINO_BASE} | "
            "Monte o storage antes de iniciar as transferências, "
            "ou ajuste a constante PASTA_DESTINO_BASE no topo do script."
        )

    while True:
        try:
            time.sleep(INTERVALO_POLLING)

            # Sem sentinela = sistema em espera, não processa
            if not sentinela_ativo():
                continue

            # Busca materiais prontos para transferir
            materiais_pendentes = buscar_materiais_para_transferir()

            if not materiais_pendentes:
                continue  # Nada na fila — aguarda o próximo ciclo

            logger.info(
                f"FILA | {len(materiais_pendentes)} material(is) aguardando transferência"
            )

            # Processa um material por ciclo para não sobrecarregar o storage
            # (o ShotPutPro já é um processo pesado por si só)
            for caminho_json, dados in materiais_pendentes:
                try:
                    processar_material(caminho_json, dados)
                except Exception as erro:
                    # Erro inesperado em um material não para o loop
                    logger.error(
                        f"ERRO INESPERADO | Material: {os.path.basename(caminho_json)} | "
                        f"{erro} | Continuando com o próximo"
                    )

        except KeyboardInterrupt:
            logger.info("TRANSFERÊNCIA ENCERRADA | Interrompido pelo operador (Ctrl+C)")
            break

        except Exception as erro:
            # Erro no próprio loop — registra e continua
            logger.error(f"ERRO NO LOOP PRINCIPAL | {erro} | Continuando...")


# ── PONTO DE ENTRADA ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    main()
