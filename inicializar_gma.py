#!/usr/bin/env python3
"""
inicializar_gma.py
Camadas 1 e 2 do GMA — Script de inicialização do sistema completo.

Sobe todos os processos do GMA com um único comando:
  - porteiro.py       (detecta cartões novos)
  - leitor_midia.py   (analisa o conteúdo dos cartões)
  - flask_gma.py      (recebe formulários e serve o painel)
  - transferencia.py  (copia e verifica a integridade do material)

Cria o sentinela .gma_ativo antes de ligar os processos.
Mistura os logs dos quatro processos no terminal com um prefixo colorido
para facilitar o acompanhamento.
Ao apertar Ctrl+C, encerra tudo de forma limpa e remove o sentinela.

Uso:
    python3 /Users/serafa/GMA/inicializar_gma.py
"""

import os
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime


# ── CARREGAMENTO DO .env ───────────────────────────────────────────────────────
# Lê o arquivo .env (se existir) e exporta as variáveis para o ambiente ANTES
# de iniciar qualquer processo filho. Assim o Flask e os outros scripts herdam
# as variáveis automaticamente (ex: TALLY_WEBHOOK_SECRET).
#
# Regras de leitura:
#   - Linhas em branco → ignoradas
#   - Linhas começando com # → comentário, ignoradas
#   - CHAVE=VALOR → exporta os.environ["CHAVE"] = "VALOR"
#   - Aspas simples/duplas ao redor do valor são removidas automaticamente
#   - Variáveis já definidas no ambiente NÃO são sobrescritas (o sistema tem prioridade)

def carregar_dotenv(caminho_env):
    """
    Carrega variáveis de ambiente do arquivo .env sem dependências externas.
    Retorna o número de variáveis carregadas.
    """
    if not os.path.isfile(caminho_env):
        return 0  # arquivo não existe — ok, é opcional

    carregadas = 0
    try:
        with open(caminho_env, "r", encoding="utf-8") as f:
            for numero_linha, linha in enumerate(f, start=1):
                linha = linha.strip()

                # Ignora linhas vazias e comentários
                if not linha or linha.startswith("#"):
                    continue

                # Precisa ter um sinal de = para ser uma atribuição válida
                if "=" not in linha:
                    continue

                # Divide na primeira ocorrência de = (o valor pode conter =)
                chave, _, valor = linha.partition("=")
                chave = chave.strip()
                valor = valor.strip()

                # Remove aspas simples ou duplas ao redor do valor (se houver)
                if len(valor) >= 2 and valor[0] == valor[-1] and valor[0] in ('"', "'"):
                    valor = valor[1:-1]

                # Chave vazia ou contendo espaços → ignora (formato inválido)
                if not chave or " " in chave:
                    continue

                # Não sobrescreve variável já definida no ambiente do sistema
                if chave not in os.environ:
                    os.environ[chave] = valor
                    carregadas += 1

    except OSError as erro:
        # Não conseguiu ler o arquivo — avisa mas continua
        print(f"[GMA]          AVISO: nao foi possivel ler .env ({erro})", flush=True)

    return carregadas

# ── CONFIGURAÇÃO DE CAMINHOS ───────────────────────────────────────────────────

# Raiz do projeto GMA — todos os scripts estão aqui
RAIZ_GMA = "/Users/serafa/GMA"

# Arquivo sentinela: quando existe, o Porteiro processa eventos
SENTINELA = os.path.join(RAIZ_GMA, ".gma_ativo")

# Caminhos dos scripts que serão iniciados
SCRIPT_PORTEIRO      = os.path.join(RAIZ_GMA, "porteiro.py")
SCRIPT_LEITOR        = os.path.join(RAIZ_GMA, "leitor_midia.py")
SCRIPT_FLASK         = os.path.join(RAIZ_GMA, "flask_gma.py")
SCRIPT_TRANSFERENCIA = os.path.join(RAIZ_GMA, "transferencia.py")
SCRIPT_AUDITORIA     = os.path.join(RAIZ_GMA, "auditoria.py")
SCRIPT_SHEETS        = os.path.join(RAIZ_GMA, "exportador_sheets.py")

# Nome do interpretador Python atual (mesmo que está rodando este script)
PYTHON = sys.executable

# ── CONFIGURAÇÃO DE PREFIXOS ───────────────────────────────────────────────────
#
# Cada processo tem um prefixo fixo de 16 caracteres para alinhar as colunas
# no terminal. Assim fica fácil distinguir de qual processo vem cada linha.

PREFIXOS = {
    "porteiro":      "[PORTEIRO]     ",
    "leitor":        "[LEITOR]       ",
    "flask":         "[FLASK]        ",
    "transferencia": "[TRANSF]       ",
    "auditoria":     "[AUDITORIA]    ",
    "sheets":        "[SHEETS]       ",
    "sistema":       "[GMA]          ",
}


# ── FUNÇÕES AUXILIARES ────────────────────────────────────────────────────────

def agora():
    """Retorna o timestamp atual no formato ISO-8601 sem microssegundos."""
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def log(prefixo_chave, mensagem):
    """
    Imprime uma linha no terminal com timestamp e prefixo identificador.
    Formato: [PROCESSO]      AAAA-MM-DDTHH:MM:SS | mensagem
    """
    prefixo = PREFIXOS.get(prefixo_chave, f"[{prefixo_chave.upper()}]")
    print(f"{prefixo} {agora()} | {mensagem}", flush=True)


def criar_sentinela():
    """
    Cria o arquivo sentinela .gma_ativo.
    Esse arquivo sinaliza para o Porteiro que o sistema está ativo
    e que ele deve processar eventos de cartão.
    """
    with open(SENTINELA, "w", encoding="utf-8") as f:
        f.write(f"GMA ativo desde {agora()}\n")
    log("sistema", f"Sentinela criado: {SENTINELA}")


def remover_sentinela():
    """
    Remove o arquivo sentinela .gma_ativo.
    Chamado durante o encerramento do sistema.
    Não falha se o arquivo já não existir.
    """
    if os.path.isfile(SENTINELA):
        os.remove(SENTINELA)
        log("sistema", "Sentinela removido.")
    else:
        log("sistema", "Sentinela já não existia.")


def verificar_script(caminho, nome):
    """
    Verifica se o script existe antes de tentar iniciar.
    Retorna True se existe, False se não.
    Avisa o operador caso esteja faltando.
    """
    if os.path.isfile(caminho):
        return True
    log("sistema", f"AVISO: script nao encontrado — {nome} ({caminho})")
    log("sistema", f"  O processo {nome} sera pulado. Verifique o caminho.")
    return False


# ── LEITURA DE LOGS EM TEMPO REAL ─────────────────────────────────────────────

def thread_leitura_log(processo, nome_prefixo, processo_nome_legivel):
    """
    Roda em uma thread separada para cada processo filho.
    Lê o stdout do processo linha por linha e imprime no terminal
    com o prefixo do processo correspondente.

    Quando o processo filho encerra (seja normalmente ou por crash),
    a thread detecta e avisa o operador — mas NÃO encerra os outros processos.

    Parâmetros:
      processo              — objeto subprocess.Popen
      nome_prefixo          — chave para o dicionário PREFIXOS (ex: "porteiro")
      processo_nome_legivel — nome amigável para mensagens (ex: "Porteiro")
    """
    try:
        # Lê linha por linha enquanto o processo estiver rodando
        for linha in processo.stdout:
            linha = linha.rstrip("\n")
            if linha:  # ignora linhas vazias
                log(nome_prefixo, linha)
    except Exception:
        # Se a leitura falhar (ex: processo encerrou abruptamente), sai silenciosamente
        pass

    # Chegou aqui: o processo filho encerrou ou o pipe foi fechado
    codigo_saida = processo.poll()
    if codigo_saida is not None and codigo_saida != 0:
        # Encerramento inesperado (código de saída diferente de zero)
        log("sistema", f"AVISO: {processo_nome_legivel} encerrou inesperadamente "
                       f"(codigo de saida: {codigo_saida}). Os outros processos continuam.")
    elif codigo_saida == 0:
        log("sistema", f"INFO: {processo_nome_legivel} encerrou normalmente.")


# ── VERIFICAÇÃO DE INSTÂNCIAS DUPLICADAS ──────────────────────────────────────

def verificar_instancias_ativas():
    """
    Verifica se processos GMA já estão rodando antes de iniciar.

    Se encontrar processos ativos, exibe um aviso e aguarda ENTER para encerrá-los
    automaticamente antes de continuar. Ctrl+C aborta a operação.

    Retorna True se pode prosseguir, False se o operador cancelou.
    """
    scripts = [
        ("porteiro.py",     "Porteiro"),
        ("leitor_midia.py", "Leitor de Midia"),
        ("flask_gma.py",    "Flask"),
        ("transferencia.py","Transferencia"),
    ]

    meu_pid = os.getpid()
    encontrados = []

    for script, nome in scripts:
        try:
            resultado = subprocess.run(
                ["pgrep", "-f", script],
                capture_output=True, text=True
            )
            if resultado.returncode == 0:
                pids = [
                    int(p) for p in resultado.stdout.strip().splitlines()
                    if p.strip().isdigit() and int(p.strip()) != meu_pid
                ]
                if pids:
                    encontrados.append((nome, pids))
        except Exception:
            pass

    if not encontrados:
        return True  # Nenhum processo GMA rodando — pode iniciar

    print()
    log("sistema", "ATENCAO: processos GMA ja estao rodando:")
    for nome, pids in encontrados:
        log("sistema", f"  {nome}: PIDs {pids}")
    print()
    log("sistema", "Iniciar sem encerrar causara instancias duplicadas (zumbis).")
    log("sistema", "Pressione ENTER para encerrar os processos antigos e continuar.")
    log("sistema", "Pressione Ctrl+C para cancelar.")
    print()

    try:
        input()
    except KeyboardInterrupt:
        print()
        log("sistema", "Operacao cancelada pelo operador.")
        return False

    # Envia SIGTERM para todos
    for nome, pids in encontrados:
        for pid in pids:
            try:
                os.kill(pid, signal.SIGTERM)
                log("sistema", f"{nome} (PID {pid}) — encerrando...")
            except ProcessLookupError:
                pass
            except Exception as erro:
                log("sistema", f"Aviso ao encerrar {nome} PID {pid}: {erro}")

    # Aguarda até 5 segundos
    time.sleep(5)

    # SIGKILL nos que ainda resistirem
    for nome, pids in encontrados:
        for pid in pids:
            try:
                os.kill(pid, 0)            # verifica se ainda existe
                os.kill(pid, signal.SIGKILL)
                log("sistema", f"{nome} (PID {pid}) — encerrado forcado.")
            except ProcessLookupError:
                pass  # ja encerrou — ok
            except Exception:
                pass

    log("sistema", "Processos anteriores encerrados. Iniciando sistema limpo...")
    print()
    return True


# ── INICIO DOS PROCESSOS ──────────────────────────────────────────────────────

def iniciar_processo(script, nome_prefixo, nome_legivel):
    """
    Inicia um script Python como processo filho em background.

    - stdout e stderr do filho são capturados (pipe) para exibição aqui.
    - Uma thread separada fica lendo a saída e imprimindo com o prefixo certo.

    Retorna o objeto Popen se conseguiu iniciar, None se falhou.
    """
    if not verificar_script(script, nome_legivel):
        return None

    try:
        processo = subprocess.Popen(
            [PYTHON, script],           # comando: python3 script.py
            stdout=subprocess.PIPE,     # captura a saída padrão
            stderr=subprocess.STDOUT,   # mistura stderr com stdout (um único stream)
            text=True,                  # decodifica bytes para string automaticamente
            bufsize=1,                  # buffer linha a linha (importante para ver em tempo real)
            cwd=RAIZ_GMA,              # roda com a raiz GMA como diretório de trabalho
        )

        log("sistema", f"{nome_legivel} iniciado (PID {processo.pid})")

        # Inicia a thread que vai ler e exibir os logs deste processo
        t = threading.Thread(
            target=thread_leitura_log,
            args=(processo, nome_prefixo, nome_legivel),
            daemon=True,    # thread daemon: morre automaticamente quando o processo principal sai
        )
        t.start()

        return processo

    except Exception as erro:
        log("sistema", f"ERRO ao iniciar {nome_legivel}: {erro}")
        return None


# ── ENCERRAMENTO LIMPO ────────────────────────────────────────────────────────

def encerrar_processo(processo, nome_legivel, timeout=5):
    """
    Encerra um processo filho de forma limpa.

    Estratégia:
      1. Envia SIGTERM (pedido gentil para encerrar).
      2. Aguarda até `timeout` segundos.
      3. Se ainda estiver rodando, envia SIGKILL (encerramento forçado).

    Parâmetros:
      processo      — objeto subprocess.Popen (pode ser None se não iniciou)
      nome_legivel  — nome para exibir no log
      timeout       — segundos de espera antes do SIGKILL
    """
    if processo is None:
        return  # processo não foi iniciado, nada a fazer

    if processo.poll() is not None:
        # Processo já encerrou por conta própria
        log("sistema", f"{nome_legivel} ja havia encerrado.")
        return

    try:
        # Pedido gentil de encerramento
        processo.terminate()
        processo.wait(timeout=timeout)
        log("sistema", f"{nome_legivel} encerrado.")
    except subprocess.TimeoutExpired:
        # Não respondeu no tempo — força o encerramento
        log("sistema", f"{nome_legivel} nao respondeu. Forcando encerramento...")
        processo.kill()
        processo.wait()
        log("sistema", f"{nome_legivel} encerrado forcadamente.")
    except Exception as erro:
        log("sistema", f"Erro ao encerrar {nome_legivel}: {erro}")


# ── PONTO DE ENTRADA ──────────────────────────────────────────────────────────

def main():
    """
    Fluxo principal do inicializador:

    1. Exibe o cabeçalho do GMA.
    2. Cria o sentinela .gma_ativo.
    3. Inicia os quatro processos (Porteiro, Leitor, Flask, Transferência).
    4. Entra em modo de espera, mostrando os logs em tempo real.
    5. Ao receber Ctrl+C: encerra tudo de forma limpa e remove o sentinela.
    """

    print()
    print("=" * 60)
    print("  GMA — Gerenciamento de Midia Audiovisual")
    print(f"  Inicializando sistema em {agora()}")
    print("=" * 60)
    print()

    # ── Carrega o .env ANTES de qualquer processo filho ───────────────────────
    # O .env contém variáveis opcionais como TALLY_WEBHOOK_SECRET.
    # Se o arquivo não existir, segue normalmente sem erro.
    caminho_env = os.path.join(RAIZ_GMA, ".env")
    qtd_vars = carregar_dotenv(caminho_env)
    if qtd_vars > 0:
        log("sistema", f".env carregado: {qtd_vars} variavel(is) de ambiente definida(s).")
    elif os.path.isfile(caminho_env):
        log("sistema", ".env encontrado mas sem variaveis novas para carregar.")
    # Se o .env não existir, não imprime nada (silêncio é ok — é opcional)

    # ── Instrução sobre o Tally / ngrok ──────────────────────────────────────
    # O ngrok NÃO é iniciado automaticamente porque:
    #   - É opcional (usado só quando o Tally é o formulário de check-in)
    #   - Requer conta gratuita no ngrok (ngrok.com)
    #   - A URL pública muda a cada reinicialização e precisa ser copiada manualmente
    # Para usar o Tally, em um terminal SEPARADO rode:
    #   ./ngrok_gma.sh
    # O script vai imprimir a URL pública que você cola no painel do Tally.
    log("sistema", "Para usar o Tally como formulario: rode './ngrok_gma.sh' em outro terminal.")

    # Verifica se já existem instâncias rodando antes de iniciar
    if not verificar_instancias_ativas():
        sys.exit(0)

    # Cria o sentinela antes de ligar qualquer processo
    criar_sentinela()

    # Dicionário que guarda os processos filhos iniciados
    # Chave: nome legivel | Valor: objeto Popen (ou None)
    processos = {}

    # Inicia cada processo
    # A ordem importa: Porteiro primeiro (detecta cartões),
    # depois Leitor (analisa), depois Flask (interface),
    # e por último a Transferência (aguarda materiais matched na fila)
    processos["Porteiro"]        = iniciar_processo(SCRIPT_PORTEIRO,      "porteiro",      "Porteiro")
    processos["Leitor de Midia"] = iniciar_processo(SCRIPT_LEITOR,        "leitor",        "Leitor de Midia")
    processos["Flask"]           = iniciar_processo(SCRIPT_FLASK,         "flask",         "Flask")
    processos["Transferencia"]   = iniciar_processo(SCRIPT_TRANSFERENCIA, "transferencia", "Transferencia")
    processos["Auditoria"]       = iniciar_processo(SCRIPT_AUDITORIA,     "auditoria",     "Auditoria")
    processos["Sheets"]          = iniciar_processo(SCRIPT_SHEETS,        "sheets",        "Exportador Sheets")

    # Conta quantos processos foram realmente iniciados
    iniciados = sum(1 for p in processos.values() if p is not None)
    print()
    log("sistema", f"{iniciados} de {len(processos)} processos iniciados com sucesso.")
    log("sistema", "Sistema GMA ativo. Pressione Ctrl+C para encerrar.")
    print()

    # ── Loop de espera ────────────────────────────────────────────────────────
    # O processo principal fica vivo aqui, apenas aguardando o Ctrl+C.
    # Os logs chegam pelas threads de leitura de cada processo filho.
    try:
        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        # Ctrl+C recebido — encerra tudo de forma limpa
        print()
        log("sistema", "Encerrando sistema...")

        # Encerra os processos filhos na ordem inversa da inicialização
        encerrar_processo(processos.get("Sheets"),          "Exportador Sheets")
        encerrar_processo(processos.get("Auditoria"),       "Auditoria")
        encerrar_processo(processos.get("Transferencia"),   "Transferencia")
        encerrar_processo(processos.get("Flask"),           "Flask")
        encerrar_processo(processos.get("Leitor de Midia"), "Leitor de Midia")
        encerrar_processo(processos.get("Porteiro"),        "Porteiro")

        # Remove o sentinela para sinalizar que o sistema está parado
        remover_sentinela()

        print()
        log("sistema", "Sistema GMA encerrado com seguranca.")
        print()


if __name__ == "__main__":
    main()
