#!/usr/bin/env python3
"""
integrador_spp.py
Camada 2 do GMA — Ponte GMA ↔ ShotPutPro.

O que este arquivo faz:
  - Expõe a função copiar(caminho_origem, caminho_destino, nome_job)
    que é chamada pelo transferencia.py no lugar do antigo copiador.py.
  - Aciona o ShotPutPro via AppleScript (GUI scripting) para iniciar a cópia.
  - Monitora a pasta de destino aguardando o arquivo .sppo aparecer.
  - Verifica que o destino registrado no log bate com o destino esperado
    (verificação de "material no lugar certo" — coração da segurança).
  - Verifica checksums: zero falhos = transferência OK.
  - Retorna um dicionário com ok/caminho_log/total_arquivos/tamanho_bytes/alertas.

Pré-requisito:
  - ShotPutPro configurado com "Salvar relatórios com o trabalho" LIGADO.
    (Configurações → Relatórios → "Salvar relatórios com o trabalho")
  - macOS com osascript disponível (vem de fábrica no macOS).

Como testar manualmente:
  python3 /Users/serafa/GMA/integrador_spp.py <caminho_origem> <caminho_destino>

  Exemplo:
    python3 /Users/serafa/GMA/integrador_spp.py \
        /Volumes/MeuCartao \
        "/Users/serafa/GMA/TESTE LOGAGEM/20260606/VIDEO/PRODUTORA_TESTE/PRODUTORA_TESTE_001"

  Sem argumentos, usa pastas de teste locais automáticas.
"""

import os
import sys
import time
import glob
import logging
import subprocess
from datetime import datetime

# ── CONSTANTES CONFIGURÁVEIS ──────────────────────────────────────────────────
#
# Ajuste aqui sem precisar mexer no resto do código.

# Tempo máximo esperando o ShotPutPro terminar (em segundos).
# 1 hora = 3600. Para cartões grandes (256 GB), pode precisar de mais.
TIMEOUT_TRANSFERENCIA = 3600

# Intervalo entre cada verificação de .sppo novo (em segundos).
INTERVALO_POLLING = 3

# Caminho do arquivo de log deste módulo.
ARQUIVO_LOG = "/Users/serafa/GMA/logs/integrador_spp.log"

# Ativa o acionamento automático via AppleScript (GUI scripting).
# Se True: tenta abrir/usar o ShotPutPro via AppleScript.
# Se False: cai direto no modo handoff (instrui o operador a iniciar manualmente).
#
# IMPORTANTE: o GUI scripting depende da tela real do ShotPutPro.
# Habilite somente após validar no hardware real com as telas corretas.
# Veja os comentários marcados com "# AJUSTAR NO HARDWARE REAL" abaixo.
ACIONAMENTO_AUTOMATICO = False

# Nome do aplicativo exatamente como aparece no macOS (para o AppleScript).
# AJUSTAR NO HARDWARE REAL: verifique com: osascript -e 'tell application "ShotPutPro" to get name'
NOME_APP_SHOTPUTPRO = "ShotPutPro"


# ── IMPORTAÇÃO DO PARSER DO LOG ───────────────────────────────────────────────
#
# Reutiliza parse_shotputpro_log() do gma_relatorio_pdf.py.
# Essa função já existe, está testada, e sabe lidar com variações do XML.

# Garante que o diretório do GMA esteja no caminho de busca de módulos.
RAIZ_GMA = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, RAIZ_GMA)

try:
    from gma_relatorio_pdf import parse_shotputpro_log
    _PARSER_DISPONIVEL = True
except (ImportError, SystemExit) as _erro_import_parser:
    # gma_relatorio_pdf chama sys.exit(1) se reportlab não estiver instalado.
    # Capturamos SystemExit para não derrubar o processo inteiro.
    _PARSER_DISPONIVEL = False
    _MENSAGEM_ERRO_PARSER = str(_erro_import_parser)


# ── CONFIGURAÇÃO DO LOGGER ────────────────────────────────────────────────────

def _configurar_logger():
    """
    Configura o logger do integrador_spp.
    Grava em logs/integrador_spp.log E exibe no terminal.
    Formato padrão GMA: timestamp ISO-8601 | mensagem.
    """
    logger = logging.getLogger("integrador_spp")
    logger.setLevel(logging.DEBUG)

    # Evita criar handlers duplicados se o módulo for importado mais de uma vez.
    if logger.handlers:
        return logger

    formato = logging.Formatter(
        fmt="%(asctime)s | %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S"
    )

    # Garante que a pasta de logs existe.
    os.makedirs(os.path.dirname(ARQUIVO_LOG), exist_ok=True)

    # Handler de arquivo — nunca sobrescreve, sempre acrescenta ao final.
    handler_arquivo = logging.FileHandler(ARQUIVO_LOG, encoding="utf-8")
    handler_arquivo.setFormatter(formato)
    logger.addHandler(handler_arquivo)

    # Handler de terminal — para acompanhamento em tempo real.
    handler_terminal = logging.StreamHandler()
    handler_terminal.setFormatter(formato)
    logger.addHandler(handler_terminal)

    return logger


# Cria o logger no momento em que o módulo é carregado.
logger = _configurar_logger()


# ── LEMBRETE DE INÍCIO DE DIA ─────────────────────────────────────────────────

def exibir_lembrete_inicio_de_dia():
    """
    Exibe no terminal o lembrete para o operador conferir a pasta de relatórios
    do ShotPutPro no início de cada dia de evento.

    Este lembrete NÃO bloqueia o sistema — é informativo apenas.
    O sistema detecta o fim da cópia pelo .sppo, não pela pasta centralizada.
    """
    data_hoje = datetime.now().strftime("%Y%m%d")
    print("\n" + "=" * 55)
    print(f"  GMA — INÍCIO DE DIA: {data_hoje}")
    print("=" * 55)
    print("  No ShotPutPro → Configurações → Relatórios")
    print("  confirme que 'Salvar relatórios em pasta' aponta")
    print(f"  para a pasta do dia atual (ex: RELATORIOS/{data_hoje}/)")
    print("")
    print("  A cópia iniciará automaticamente. Este aviso é")
    print("  apenas para a pasta centralizada de relatórios.")
    print("=" * 55 + "\n")


# ── SNAPSHOT DE LOGS EXISTENTES ───────────────────────────────────────────────

def _listar_sppos_existentes(pasta):
    """
    Lista todos os arquivos .sppo já presentes dentro de uma pasta
    (incluindo subpastas) para fazer um snapshot antes da cópia.

    Isso evita confundir um log antigo com o novo que o ShotPutPro vai gerar.

    Retorna um conjunto (set) de caminhos absolutos.
    """
    padrao = os.path.join(pasta, "**", "*.sppo")
    encontrados = glob.glob(padrao, recursive=True)
    return set(os.path.abspath(f) for f in encontrados)


# ── ACIONAMENTO VIA APPLESCRIPT ───────────────────────────────────────────────

def _acionar_shotputpro(caminho_origem, caminho_destino, nome_job):
    """
    Tenta acionar o ShotPutPro via AppleScript/GUI scripting.

    Estratégia:
      1. Ativa o ShotPutPro (abre/traz para frente).
      2. Tenta usar GUI scripting via System Events para configurar origem/destino.
      3. Se qualquer passo falhar, imprime as instruções de handoff manual.

    A detecção do fim da cópia é sempre feita pelo monitor do .sppo —
    nunca dependemos de confirmação do operador para saber quando terminou.

    Parâmetros:
      caminho_origem  — caminho completo do cartão/volume de origem
      caminho_destino — caminho completo da pasta de destino (já criada pelo transferencia.py)
      nome_job        — nome do job (ex: "PRODUTORA_X_001")

    Retorna True se o acionamento automático foi disparado sem erro, False caso contrário.
    """
    logger.info(f"ACIONANDO SHOTPUTPRO | Job: {nome_job} | Origem: {caminho_origem}")
    logger.info(f"ACIONANDO SHOTPUTPRO | Destino: {caminho_destino}")

    if not ACIONAMENTO_AUTOMATICO:
        logger.info("MODO HANDOFF | Acionamento automático desativado (ACIONAMENTO_AUTOMATICO = False)")
        _exibir_instrucoes_handoff(caminho_origem, caminho_destino, nome_job)
        return False

    # ── Passo 1: Ativa/abre o ShotPutPro ─────────────────────────────────────
    # Este passo é confiável — AppleScript básico funciona sem acessibilidade.
    script_ativar = f'tell application "{NOME_APP_SHOTPUTPRO}" to activate'
    try:
        subprocess.run(
            ["osascript", "-e", script_ativar],
            check=True,
            capture_output=True,
            text=True,
            timeout=10
        )
        logger.info("SHOTPUTPRO ATIVADO | Aplicativo em primeiro plano")
    except subprocess.CalledProcessError as erro:
        logger.error(f"ERRO AO ATIVAR SHOTPUTPRO | {erro.stderr.strip()}")
        _exibir_instrucoes_handoff(caminho_origem, caminho_destino, nome_job)
        return False
    except subprocess.TimeoutExpired:
        logger.error("TIMEOUT AO ATIVAR SHOTPUTPRO | osascript demorou demais")
        _exibir_instrucoes_handoff(caminho_origem, caminho_destino, nome_job)
        return False

    # Aguarda o app abrir e estabilizar.
    time.sleep(2)

    # ── Passo 2: GUI scripting via System Events ───────────────────────────────
    #
    # NOTA IMPORTANTE: GUI scripting depende de:
    #   a) Permissões de Acessibilidade: Preferências → Privacidade → Acessibilidade
    #      → adicionar Terminal (ou Python) como app permitido.
    #   b) O layout real da janela do ShotPutPro estar como esperado.
    #
    # A automação abaixo tenta o fluxo mais simples:
    # Quando "Automação da Fila" estiver ativada no ShotPutPro, apenas montar
    # o volume de origem já dispara a cópia automaticamente.
    # O GMA não precisa clicar em nada — só garantir que o app está aberto.
    #
    # Se a "Automação da Fila" NÃO estiver ativa, o script tenta usar
    # o menu ou botão via GUI scripting. Esta parte PRECISA ser ajustada
    # no hardware real conforme a versão e idioma do ShotPutPro.
    #
    # AJUSTAR NO HARDWARE REAL: valide o script abaixo rodando manualmente:
    #   osascript -e 'tell application "System Events" to tell process "ShotPutPro" to get entire contents'
    # Isso lista todos os elementos da janela para mapear os nomes corretos.

    script_gui = f"""
tell application "System Events"
    -- Garante que o app está em primeiro plano
    set frontmost of process "{NOME_APP_SHOTPUTPRO}" to true
    delay 1

    -- Tenta obter a janela principal
    -- AJUSTAR NO HARDWARE REAL: o nome da janela pode ser diferente
    tell process "{NOME_APP_SHOTPUTPRO}"
        -- Apenas traz a janela para frente; com "Automação da Fila" ativa,
        -- o SPP já reagiu ao volume montado. Não tentamos clicar em botões
        -- específicos pois posições/nomes variam por versão e idioma.
        -- A rede de segurança é a verificação do .sppo no passo de monitoramento.
        set frontWindow to window 1
        set visible of frontWindow to true
    end tell
end tell
"""

    try:
        resultado = subprocess.run(
            ["osascript", "-e", script_gui],
            capture_output=True,
            text=True,
            timeout=15
        )
        if resultado.returncode != 0:
            erro_msg = resultado.stderr.strip()
            # Erros de permissão de acessibilidade são comuns na primeira execução.
            if "not allowed" in erro_msg.lower() or "accessibility" in erro_msg.lower():
                logger.warning(
                    "GUI SCRIPTING BLOQUEADO | Permissão de Acessibilidade necessária. "
                    "Vá em: Preferências → Privacidade → Acessibilidade → adicione o Terminal."
                )
            else:
                logger.warning(f"GUI SCRIPTING FALHOU | {erro_msg} | Modo handoff ativado")
            _exibir_instrucoes_handoff(caminho_origem, caminho_destino, nome_job)
            return False

        logger.info("GUI SCRIPTING OK | ShotPutPro em primeiro plano, aguardando operação")
        return True

    except subprocess.TimeoutExpired:
        logger.warning("TIMEOUT NO GUI SCRIPTING | Modo handoff ativado")
        _exibir_instrucoes_handoff(caminho_origem, caminho_destino, nome_job)
        return False
    except Exception as erro:
        logger.warning(f"ERRO NO GUI SCRIPTING | {erro} | Modo handoff ativado")
        _exibir_instrucoes_handoff(caminho_origem, caminho_destino, nome_job)
        return False


def _exibir_instrucoes_handoff(caminho_origem, caminho_destino, nome_job):
    """
    Exibe no terminal as instruções para o operador iniciar a cópia manualmente
    no ShotPutPro.

    É chamada quando o acionamento automático falha ou está desativado.
    O sistema continua monitorando o .sppo — o operador não precisa fazer nada
    além de iniciar a cópia no ShotPutPro.
    """
    print("\n" + "=" * 60)
    print("  GMA — ACAO NECESSARIA: inicie a copia no ShotPutPro")
    print("=" * 60)
    print(f"  Job:     {nome_job}")
    print(f"  Origem:  {caminho_origem}")
    print(f"  Destino: {caminho_destino}")
    print("")
    print("  INSTRUCOES:")
    print("  1. Abra o ShotPutPro")
    print(f"  2. Arraste a origem ({os.path.basename(caminho_origem)}) para 'Copiar De'")
    print(f"  3. Configure o destino para EXATAMENTE:")
    print(f"     {caminho_destino}")
    print("  4. Clique em 'Iniciar'")
    print("")
    print("  O GMA detectara o fim automaticamente. Nao pressione ENTER.")
    print("=" * 60 + "\n")
    logger.info(
        f"HANDOFF MANUAL | Operador deve iniciar ShotPutPro | "
        f"Origem: {caminho_origem} | Destino: {caminho_destino}"
    )


# ── MONITOR DO .SPPO ──────────────────────────────────────────────────────────

def _aguardar_novo_sppo(pasta_destino, sppos_antes, timeout_segundos):
    """
    Fica em polling dentro de pasta_destino esperando um arquivo .sppo NOVO surgir.

    "Novo" = caminho que NÃO estava no snapshot tirado antes de acionar o ShotPutPro.
    Isso garante que não confundiremos um log antigo com o log desta cópia.

    Parâmetros:
      pasta_destino     — pasta onde o .sppo deve aparecer (busca recursiva)
      sppos_antes       — conjunto de caminhos .sppo já existentes antes da cópia
      timeout_segundos  — segundos máximos de espera

    Retorna o caminho do .sppo novo encontrado, ou None se der timeout.
    """
    logger.info(
        f"MONITORANDO DESTINO | {pasta_destino} | "
        f"Timeout: {timeout_segundos}s | Polling: {INTERVALO_POLLING}s"
    )

    tempo_inicio = time.time()

    while True:
        # Verifica se excedeu o tempo limite.
        tempo_decorrido = time.time() - tempo_inicio
        if tempo_decorrido >= timeout_segundos:
            logger.error(
                f"TIMEOUT | Nenhum .sppo novo em {timeout_segundos}s | "
                "ShotPutPro pode não ter iniciado ou demorou demais."
            )
            return None

        # Busca todos os .sppo presentes agora na pasta de destino.
        sppos_agora = _listar_sppos_existentes(pasta_destino)

        # Compara com o snapshot para encontrar arquivos novos.
        sppos_novos = sppos_agora - sppos_antes

        if sppos_novos:
            # Pode haver mais de um se o ShotPutPro gerar logs parciais.
            # Pega o mais recente (maior timestamp de modificação).
            sppo_novo = max(sppos_novos, key=os.path.getmtime)
            logger.info(f"SPPO DETECTADO | {sppo_novo} | Decorrido: {tempo_decorrido:.0f}s")
            return sppo_novo

        # Aguarda antes da próxima verificação.
        time.sleep(INTERVALO_POLLING)


# ── VERIFICAÇÃO DE DESTINO CORRETO ────────────────────────────────────────────

def _verificar_destino_no_log(dados_log, caminho_destino_esperado):
    """
    VERIFICACAO DE SEGURANCA CENTRAL:
    Confirma que o destino registrado no log .sppo bate com o destino
    que o GMA configurou. Protege contra o operador ter configurado o
    ShotPutPro com um destino errado sem perceber.

    Lógica de comparação:
      - Normaliza ambos os caminhos com os.path.realpath (resolve symlinks e ..)
      - Aceita que o destino do log seja igual OU seja subpasta do esperado.
        (o ShotPutPro às vezes registra a subpasta criada dentro do destino)
      - Comparação case-insensitive para compatibilidade com HDs exFAT.

    Parâmetros:
      dados_log                — dicionário retornado por parse_shotputpro_log()
      caminho_destino_esperado — caminho que o GMA definiu como destino

    Retorna um dicionário com:
      "ok"      → True se destino conferido, False se divergente ou ausente
      "motivo"  → string explicando o problema (vazia se ok=True)
    """
    # Normaliza o destino esperado.
    destino_esperado_norm = os.path.normpath(
        os.path.realpath(caminho_destino_esperado)
    ).lower()

    # Extrai os destinos registrados no log.
    destinos_no_log = dados_log.get("destinos", [])

    if not destinos_no_log:
        # O log não tem campo de destino — pode ser versão mais antiga do SPP
        # ou o log foi gerado incompleto. Alerta mas não bloqueia por este motivo
        # (o checksum de zero falhos ainda é a validação principal).
        logger.warning(
            "DESTINO NAO ENCONTRADO NO LOG | O .sppo nao registrou destino. "
            "Verifique manualmente se a copia foi para o lugar certo."
        )
        return {
            "ok": False,
            "motivo": (
                "Log nao contem campo de destino. "
                "Verifique manualmente: " + caminho_destino_esperado
            )
        }

    # Verifica cada destino registrado no log.
    for destino_log_bruto in destinos_no_log:
        destino_log_norm = os.path.normpath(
            os.path.realpath(destino_log_bruto)
        ).lower()

        # Aceita igualdade exata.
        if destino_log_norm == destino_esperado_norm:
            logger.info(
                f"DESTINO CORRETO | Log: {destino_log_bruto} == "
                f"Esperado: {caminho_destino_esperado}"
            )
            return {"ok": True, "motivo": ""}

        # Aceita que o log registre a subpasta criada dentro do destino.
        # Exemplo: esperado=/GMA/TESTE/PROD_001 e log=/GMA/TESTE/PROD_001/PROD_001
        if destino_log_norm.startswith(destino_esperado_norm + os.sep):
            logger.info(
                f"DESTINO CORRETO (subpasta aceita) | "
                f"Log: {destino_log_bruto} | Esperado: {caminho_destino_esperado}"
            )
            return {"ok": True, "motivo": ""}

        # Aceita que o esperado contenha o log (quando o log registra a pasta pai).
        if destino_esperado_norm.startswith(destino_log_norm + os.sep):
            logger.info(
                f"DESTINO CORRETO (pasta pai aceita) | "
                f"Log: {destino_log_bruto} | Esperado: {caminho_destino_esperado}"
            )
            return {"ok": True, "motivo": ""}

    # Nenhum destino do log bateu com o esperado.
    destinos_str = " | ".join(destinos_no_log)
    motivo = (
        f"Destino no log ({destinos_str}) NAO bate com o esperado "
        f"({caminho_destino_esperado}). "
        "ATENCAO: o material pode ter ido para o lugar errado!"
    )
    logger.error(f"DESTINO DIVERGENTE | {motivo}")
    return {"ok": False, "motivo": motivo}


# ── FUNÇÃO PRINCIPAL: copiar() ────────────────────────────────────────────────

def copiar(caminho_origem, caminho_destino, nome_job):
    """
    Função principal da Camada 2: aciona o ShotPutPro e aguarda a cópia terminar.

    É chamada pelo transferencia.py no lugar do antigo copiador.copiar().
    A assinatura (parâmetros e retorno) é idêntica para ser um drop-in replacement.

    Fluxo:
      1. Garante que a pasta de destino existe.
      2. Tira snapshot dos .sppo já existentes (para não confundir com log novo).
      3. Aciona o ShotPutPro (ou instrui o operador — modo handoff).
      4. Monitora a pasta de destino aguardando um .sppo novo surgir.
      5. Parseia o log com parse_shotputpro_log() (reutilizado do gma_relatorio_pdf).
      6. Verifica que o destino no log bate com o esperado (SEGURANCA CENTRAL).
      7. Verifica checksums: zero falhos = ok.
      8. Retorna dicionário com todos os resultados.

    Parâmetros:
      caminho_origem  — caminho do cartão/volume de origem (ex: /Volumes/A007)
      caminho_destino — caminho completo da pasta de destino já montada pelo
                        transferencia.py (ex: /TESTE LOGAGEM/20260606/VIDEO/PROD/PROD_001)
      nome_job        — nome identificador do job (ex: "PRODUTORA_X_001")

    Retorna um dicionário com as chaves:
      "ok"              → True se cópia verificada e destino correto. False em qualquer falha.
      "caminho_log"     → caminho completo do .sppo gerado (str), ou None se não encontrado.
      "total_arquivos"  → número de arquivos no log (int)
      "tamanho_bytes"   → tamanho total em bytes (int)
      "alertas"         → lista de strings com avisos (pode estar vazia se ok=True)
      "motivo_falha"    → string descrevendo o motivo (vazia se ok=True)
    """
    alertas = []
    resultado_base = {
        "ok":             False,
        "caminho_log":    None,
        "total_arquivos": 0,
        "tamanho_bytes":  0,
        "alertas":        alertas,
        "motivo_falha":   "",
    }

    logger.info(
        f"COPIA INICIADA | Job: {nome_job} | "
        f"Origem: {caminho_origem} | Destino: {caminho_destino}"
    )

    # ── Passo 1: Garante que a pasta de destino existe ────────────────────────
    # O transferencia.py já criou a pasta, mas reforçamos por segurança.
    try:
        os.makedirs(caminho_destino, exist_ok=True)
    except OSError as erro:
        motivo = f"Nao foi possivel criar/confirmar pasta de destino: {erro}"
        logger.error(f"ERRO NO DESTINO | {motivo}")
        resultado_base["motivo_falha"] = motivo
        return resultado_base

    # Verifica se a origem existe antes de tentar qualquer coisa.
    if not os.path.exists(caminho_origem):
        motivo = f"Origem nao encontrada: {caminho_origem}"
        logger.error(f"ORIGEM INEXISTENTE | {motivo}")
        resultado_base["motivo_falha"] = motivo
        return resultado_base

    # ── Passo 2: Snapshot anti-falso-positivo ─────────────────────────────────
    # Lista todos os .sppo dentro do destino ANTES de acionar o ShotPutPro.
    # Depois buscamos apenas os .sppo que apareceram DEPOIS deste snapshot.
    sppos_antes = _listar_sppos_existentes(caminho_destino)
    logger.info(
        f"SNAPSHOT | {len(sppos_antes)} .sppo(s) ja existentes em {caminho_destino}"
    )

    # ── Passo 3: Aciona o ShotPutPro ─────────────────────────────────────────
    acionamento_ok = _acionar_shotputpro(caminho_origem, caminho_destino, nome_job)

    if not acionamento_ok:
        # Modo handoff: o operador vai iniciar manualmente.
        # O sistema continua monitorando. Registra o aviso mas não para.
        alertas.append(
            "Acionamento automatico falhou ou esta desativado. "
            "Operador deve iniciar a copia manualmente no ShotPutPro."
        )

    # ── Passo 4: Monitora o destino aguardando o .sppo novo ───────────────────
    caminho_sppo = _aguardar_novo_sppo(
        pasta_destino=caminho_destino,
        sppos_antes=sppos_antes,
        timeout_segundos=TIMEOUT_TRANSFERENCIA,
    )

    if caminho_sppo is None:
        motivo = (
            f"Nenhum .sppo detectado em {caminho_destino} "
            f"dentro de {TIMEOUT_TRANSFERENCIA}s. "
            "O ShotPutPro pode nao ter iniciado ou a copia falhou antes de gerar o log."
        )
        logger.error(f"SPPO NAO DETECTADO | {motivo}")
        resultado_base["motivo_falha"] = motivo
        resultado_base["alertas"] = alertas
        return resultado_base

    resultado_base["caminho_log"] = caminho_sppo

    # ── Passo 5: Parseia o log ────────────────────────────────────────────────
    if not _PARSER_DISPONIVEL:
        motivo = (
            f"Modulo gma_relatorio_pdf nao disponivel ({_MENSAGEM_ERRO_PARSER}). "
            "Instale reportlab: pip install reportlab"
        )
        logger.error(f"PARSER INDISPONIVEL | {motivo}")
        resultado_base["motivo_falha"] = motivo
        resultado_base["alertas"] = alertas
        return resultado_base

    try:
        dados_log = parse_shotputpro_log(caminho_sppo)
    except Exception as erro:
        motivo = f"Erro ao parsear .sppo ({caminho_sppo}): {erro}"
        logger.error(f"ERRO NO PARSER | {motivo}")
        resultado_base["motivo_falha"] = motivo
        resultado_base["alertas"] = alertas
        return resultado_base

    # Preenche os campos de contagem e tamanho a partir do log parseado.
    resultado_base["total_arquivos"] = dados_log.get("total_arquivos", 0)
    resultado_base["tamanho_bytes"]  = dados_log.get("tamanho_total", 0)

    # ── Passo 6: VERIFICACAO DE DESTINO CORRETO ───────────────────────────────
    # Esta é a verificação de segurança central: garante que o material
    # foi copiado para o lugar que o GMA esperava, não para outro lugar.
    verificacao_destino = _verificar_destino_no_log(dados_log, caminho_destino)

    if not verificacao_destino["ok"]:
        motivo = verificacao_destino["motivo"]
        alertas.append(motivo)
        logger.error(f"DESTINO DIVERGENTE | COPIA NAO CONFIRMADA | {motivo}")
        resultado_base["motivo_falha"] = motivo
        resultado_base["alertas"] = alertas
        # Retorna ok=False: a Camada 2 NAO confirma transferência com destino errado.
        return resultado_base

    # ── Passo 7: Verifica checksums ───────────────────────────────────────────
    total_falhos = dados_log.get("total_falhos", 0)

    if total_falhos > 0:
        motivo = (
            f"Checksum falhou em {total_falhos} arquivo(s). "
            "Nao libere o cartao — investigue o log: " + caminho_sppo
        )
        alertas.append(motivo)
        logger.error(f"CHECKSUM FALHOU | {total_falhos} arquivo(s) | {caminho_sppo}")
        resultado_base["motivo_falha"] = motivo
        resultado_base["alertas"] = alertas
        return resultado_base

    # ── Passo 8: Tudo OK — transferência confirmada ───────────────────────────
    total_verificados = dados_log.get("total_verificados", 0)
    tamanho_formatado = _formatar_tamanho(resultado_base["tamanho_bytes"])

    logger.info(
        f"TRANSFERENCIA CONFIRMADA | Job: {nome_job} | "
        f"Arquivos: {resultado_base['total_arquivos']} verificados: {total_verificados} "
        f"falhos: {total_falhos} | Tamanho: {tamanho_formatado}"
    )
    logger.info(f"LOG: {caminho_sppo}")

    resultado_base["ok"]      = True
    resultado_base["alertas"] = alertas  # pode ter alertas de handoff mesmo sendo ok=True
    return resultado_base


# ── UTILITÁRIO DE FORMATAÇÃO ──────────────────────────────────────────────────

def _formatar_tamanho(bytes_val):
    """Converte bytes para string legível (B, KB, MB, GB, TB)."""
    try:
        b = int(bytes_val)
    except (ValueError, TypeError):
        return str(bytes_val)
    for unidade in ["B", "KB", "MB", "GB", "TB"]:
        if b < 1024:
            return f"{b:.1f} {unidade}"
        b /= 1024
    return f"{b:.1f} TB"


# ── TESTE MANUAL ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    """
    Permite testar o integrador diretamente no terminal.

    Uso:
      python3 /Users/serafa/GMA/integrador_spp.py <origem> <destino>

    Exemplos:
      # Com cartão real:
      python3 /Users/serafa/GMA/integrador_spp.py \
          /Volumes/MeuCartao \
          "/Users/serafa/GMA/TESTE LOGAGEM/20260606/VIDEO/PROD_TESTE/PROD_TESTE_001"

      # Teste com pastas locais (cria as pastas automaticamente):
      python3 /Users/serafa/GMA/integrador_spp.py
    """
    print("\n" + "=" * 60)
    print("  GMA — Teste manual do integrador_spp.py")
    print("=" * 60)

    # Define origem e destino a partir dos argumentos ou usa padrões de teste.
    if len(sys.argv) >= 3:
        origem_teste  = sys.argv[1]
        destino_teste = sys.argv[2]
    else:
        # Pastas de teste locais dentro do próprio projeto GMA.
        origem_teste  = os.path.join(RAIZ_GMA, "TESTE LOGAGEM", "_ORIGEM_TESTE")
        destino_teste = os.path.join(
            RAIZ_GMA, "TESTE LOGAGEM",
            "20260606", "VIDEO", "PROD_TESTE", "PROD_TESTE_001"
        )
        # Cria as pastas de teste para que o script não falhe na verificação de existência.
        os.makedirs(origem_teste,  exist_ok=True)
        os.makedirs(destino_teste, exist_ok=True)
        print(f"\nSem argumentos — usando pastas de teste locais:")
        print(f"  Origem:  {origem_teste}")
        print(f"  Destino: {destino_teste}")

    exibir_lembrete_inicio_de_dia()

    print(f"\nIniciando copiar()...")
    print(f"  Origem:  {origem_teste}")
    print(f"  Destino: {destino_teste}")
    print(f"  Job:     PROD_TESTE_001")
    print(f"\nAguardando o ShotPutPro gerar o .sppo em {destino_teste} ...")
    print(f"(timeout: {TIMEOUT_TRANSFERENCIA}s — pressione Ctrl+C para cancelar)\n")

    resultado = copiar(
        caminho_origem=origem_teste,
        caminho_destino=destino_teste,
        nome_job="PROD_TESTE_001",
    )

    print("\n" + "=" * 60)
    print("  RESULTADO DA COPIA")
    print("=" * 60)
    print(f"  ok:              {resultado['ok']}")
    print(f"  caminho_log:     {resultado['caminho_log']}")
    print(f"  total_arquivos:  {resultado['total_arquivos']}")
    print(f"  tamanho_bytes:   {resultado['tamanho_bytes']}")
    print(f"  motivo_falha:    {resultado['motivo_falha'] or '(nenhum)'}")

    if resultado['alertas']:
        print(f"  alertas:")
        for alerta in resultado['alertas']:
            print(f"    - {alerta}")
    else:
        print(f"  alertas:         (nenhum)")

    print("=" * 60 + "\n")
    sys.exit(0 if resultado['ok'] else 1)
