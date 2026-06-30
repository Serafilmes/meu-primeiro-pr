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

import fcntl
import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime

# Painel de Controle (Camada 5): resolve qual projeto está ativo e aplica suas
# variáveis (GMA_DB, GMA_DESTINO) ao ambiente antes de subir os processos.
sys.path.insert(0, "/Users/serafa/GMA")
import painel_config


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

# Arquivos temporários do túnel Cloudflare.
# Devem ser IGUAIS aos caminhos usados pelo cloudflared_gma.sh para que os dois
# não pisem um no estado do outro.
CF_LOG       = "/tmp/cloudflared_gma.log"       # log do processo cloudflared
CF_URL_STATE = "/tmp/cloudflared_gma_url.txt"   # URL pública ativa (arquivo presente = túnel vivo)

# Arquivo sentinela: quando existe, o Porteiro processa eventos
SENTINELA = os.path.join(RAIZ_GMA, ".gma_ativo")

# Trava de instância única do maestro. Um lock de arquivo (flock) garante UM
# ÚNICO maestro por vez: se o "Iniciar" for acionado duas vezes, o segundo não
# consegue o lock e sai na hora (sem prompt, sem pendurar). O flock se solta
# sozinho quando o processo morre — então um maestro que caiu não deixa a trava
# presa (não precisa limpar PID velho).
TRAVA_MAESTRO = os.path.join(RAIZ_GMA, ".gma_maestro.lock")
_trava_handle = None  # mantém o arquivo aberto pela vida do processo (segura o lock)

# Sinal de encerrar (Camada 5). O Painel (Flask) cria este arquivo quando o
# operador clica em "Desligar o GMA"; quem comanda a sessão (hoje o SAGUÃO,
# saguao.py) vigia o arquivo e desce tudo de forma limpa.
# (A troca/reinício de projeto deixou de usar sinal: no modelo de 2 níveis o
#  saguão sobe e desce a sessão direto — ver saguao.py.)
SINAL_ENCERRAR = os.path.join(RAIZ_GMA, ".gma_encerrar")

# Caminhos dos scripts que serão iniciados
SCRIPT_PORTEIRO      = os.path.join(RAIZ_GMA, "porteiro.py")
SCRIPT_LEITOR        = os.path.join(RAIZ_GMA, "leitor_midia.py")
SCRIPT_FLASK         = os.path.join(RAIZ_GMA, "flask_gma.py")
SCRIPT_TRANSFERENCIA = os.path.join(RAIZ_GMA, "transferencia.py")
SCRIPT_AUDITORIA     = os.path.join(RAIZ_GMA, "auditoria.py")
SCRIPT_SHEETS        = os.path.join(RAIZ_GMA, "exportador_sheets.py")
# Camada 6 (IA): vigia que transcreve cartões de áudio sozinho (pós-cópia).
# Opcional — se a caixa .venv_ia não existir, ele dorme em silêncio.
SCRIPT_VIGIA_TRANSCRICAO = os.path.join(RAIZ_GMA, "vigia_transcricao.py")

# Todos os scripts GMA dependem de pacotes instalados no /usr/bin/python3 (3.9):
# Flask, gspread, google-auth, etc. O python3 do Homebrew (3.14) não os tem.
# Por isso usamos o caminho fixo, independente de qual python roda este script.
PYTHON = "/usr/bin/python3"

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
    "transcricao":   "[TRANSCRICAO]  ",
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


def adquirir_trava_maestro():
    """
    Garante UM ÚNICO maestro: tenta travar (flock) o arquivo .gma_maestro.lock.

    Se outro maestro já segura o lock, NÃO inicia um segundo — é o que evita o
    "maestro duplicado" que aparecia quando o 'Iniciar' era acionado duas vezes
    (o segundo, antes, ficava pendurado no prompt de confirmação).

    O flock é POR PROCESSO e se solta automaticamente quando o processo morre —
    então um maestro que caiu não deixa a trava presa.

    Retorna True se conseguiu a trava (pode iniciar), False se já há outro maestro.
    """
    global _trava_handle
    try:
        _trava_handle = open(TRAVA_MAESTRO, "w")
        fcntl.flock(_trava_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False  # outro maestro já segura a trava
    try:
        _trava_handle.seek(0)
        _trava_handle.truncate()
        _trava_handle.write(str(os.getpid()))
        _trava_handle.flush()
    except OSError:
        pass  # gravar o PID é só informativo; o que vale é o flock
    return True


def liberar_trava_maestro():
    """Solta a trava do maestro (também sai sozinha quando o processo morre)."""
    global _trava_handle
    if _trava_handle is not None:
        try:
            fcntl.flock(_trava_handle.fileno(), fcntl.LOCK_UN)
            _trava_handle.close()
        except OSError:
            pass
        _trava_handle = None


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

def _tunel_url():
    """
    Lê a URL HTTPS pública do Cloudflare a partir do arquivo de estado.
    Retorna a URL (sem barra final) se o arquivo existir e contiver uma URL
    HTTPS válida, ou None se o arquivo não existir ou o conteúdo for inválido.
    O arquivo CF_URL_STATE é gravado pelo iniciar_cloudflared() assim que o
    túnel sobe; ausência do arquivo = sem túnel ativo.
    """
    try:
        with open(CF_URL_STATE, "r", encoding="utf-8") as _f:
            conteudo = _f.read().strip()
        if conteudo.startswith("https://"):
            return conteudo.rstrip("/")
    except Exception:
        pass
    return None


def _tunel_no_ar():
    """
    True se já existe um processo cloudflared rodando no sistema.
    Usa pgrep para detectar o processo de verdade — não confia só no arquivo
    de estado, que pode ter sobrado de uma sessão anterior sem túnel ativo.
    """
    try:
        resultado = subprocess.run(
            ["pgrep", "-f", "cloudflared tunnel"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return resultado.returncode == 0
    except Exception:
        # Se pgrep falhar por qualquer motivo, assume que não há túnel e
        # deixa o iniciar_cloudflared() tentar subir (o pior caso é um segundo
        # processo que o Cloudflare toleraria, mas preferimos não ter).
        return False


def iniciar_cloudflared():
    """
    Sobe o cloudflared como processo OPCIONAL do maestro — o túnel sobe junto
    com o sistema, sem terminal separado. Só age quando faz sentido:
      - o projeto ativo está com a ficha remota LIGADA (tunel_ativo), E
      - NÃO há link fixo/override (modo automático), E
      - o cloudflared está instalado, E
      - ainda não há um cloudflared no ar.

    Por que Cloudflare em vez do ngrok?
      - O ngrok gratuito exibe uma tela de aviso antes da ficha, atrapalhando
        o acesso por QR Code no set.
      - O Cloudflare Quick Tunnel não tem essa tela: o QR leva direto à ficha.
      - O cloudflared não tem API local (diferente do ngrok/4040): a URL pública
        só aparece no LOG do processo — por isso fazemos polling do arquivo de log.

    Se o cloudflared cair na primeira tentativa com o erro transitório
    "invalid UUID length: 0" (conhecido do Cloudflare), tenta uma segunda vez
    automaticamente antes de desistir.

    Offline-first: se não subir, o sistema continua de pé. A ficha ainda
    funciona na rede local. O QR só aparece quando o túnel está ativo.

    Retorna o Popen do cloudflared, ou None se não subiu / não se aplica.
    """
    # 1) A ficha remota está ligada neste projeto?
    try:
        _slug, cfg = painel_config.projeto_ativo()
    except Exception:
        cfg = {}
    if not cfg.get("tunel_ativo", True):
        log("sistema", "Tunel: ficha remota desativada no Painel — cloudflared nao iniciado.")
        return None

    # 2) Link fixo/override? O túnel é gerido externamente (domínio fixo/manual).
    if (cfg.get("tunel_link") or os.environ.get("GMA_LINK_FICHA", "")).strip():
        log("sistema", "Tunel: link fixo configurado — tunel nao e gerido pelo maestro.")
        return None

    # 3) cloudflared instalado?
    if not shutil.which("cloudflared"):
        log("sistema", "Tunel: cloudflared nao instalado — ficha so na rede local "
                       "(brew install cloudflared).")
        return None

    # 4) Já há um cloudflared no ar (ex.: subido à mão)? Não sobe outro.
    if _tunel_no_ar():
        log("sistema", "Tunel: ja ha um tunel cloudflared no ar — o maestro nao sobe outro.")
        return None

    # Porta do Flask (mesma lógica usada no resto do sistema).
    try:
        estado = painel_config.carregar_estado()
    except Exception:
        estado = {}
    porta = (estado.get("porta") or os.environ.get("GMA_PORT", "5050") or "5050").strip() or "5050"

    def _uma_tentativa():
        """
        Sobe um processo cloudflared e faz polling do log por até ~15s.
        Retorna (proc, url): proc é o Popen; url é a URL encontrada ou None.
        """
        # Remove arquivo de estado velho para não ler URL de sessão anterior.
        try:
            if os.path.isfile(CF_URL_STATE):
                os.remove(CF_URL_STATE)
        except OSError:
            pass

        try:
            log_handle = open(CF_LOG, "w", encoding="utf-8")
        except Exception as erro:
            log("sistema", f"Tunel: nao foi possivel abrir o log do cloudflared ({erro}). "
                           "Sistema segue sem tunel.")
            return None, None

        try:
            proc = subprocess.Popen(
                ["cloudflared", "tunnel", "--url", f"http://localhost:{porta}"],
                stdout=log_handle, stderr=log_handle, cwd=RAIZ_GMA,
            )
        except Exception as erro:
            log("sistema", f"Tunel: falha ao iniciar o cloudflared ({erro}). "
                           "Sistema segue sem tunel.")
            log_handle.close()
            return None, None

        # Polling do arquivo de log por até ~15s (30 × 0,5s).
        import re
        padrao_url = re.compile(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com")
        url_encontrada = None
        for _ in range(30):
            time.sleep(0.5)
            if proc.poll() is not None:
                # O processo morreu antes de criar o túnel (pode ser o erro
                # transitório "invalid UUID length: 0" do Cloudflare).
                break
            try:
                with open(CF_LOG, "r", encoding="utf-8") as _lf:
                    conteudo_log = _lf.read()
                match = padrao_url.search(conteudo_log)
                if match:
                    url_encontrada = match.group(0)
                    break
            except Exception:
                pass  # log ainda sendo escrito — tenta na próxima volta

        log_handle.close()
        return proc, url_encontrada

    # ── Primeira tentativa ────────────────────────────────────────────────────
    try:
        proc, url = _uma_tentativa()
    except Exception as erro:
        log("sistema", f"Tunel: erro inesperado ao tentar subir o cloudflared ({erro}). "
                       "Sistema segue sem tunel.")
        return None

    if proc is None:
        # Falha antes mesmo de criar o processo — não há o que repetir.
        return None

    if url:
        # Grava a URL no arquivo de estado para o Flask ler.
        try:
            with open(CF_URL_STATE, "w", encoding="utf-8") as _sf:
                _sf.write(url.rstrip("/"))
        except Exception:
            pass
        log("sistema", f"Tunel ATIVO: {url} (ficha remota e QR sobem sozinhos)")
        return proc

    # ── O processo morreu sem URL — tenta uma segunda vez (erro transitório) ──
    log("sistema", "Tunel: primeira tentativa do cloudflared nao estabeleceu o tunel "
                   "(erro transitorio, tentando de novo)...")
    try:
        proc.terminate()
    except Exception:
        pass

    try:
        proc2, url2 = _uma_tentativa()
    except Exception as erro:
        log("sistema", f"Tunel: erro inesperado na segunda tentativa ({erro}). "
                       "Sistema segue sem tunel.")
        return None

    if proc2 and url2:
        try:
            with open(CF_URL_STATE, "w", encoding="utf-8") as _sf:
                _sf.write(url2.rstrip("/"))
        except Exception:
            pass
        log("sistema", f"Tunel ATIVO: {url2} (ficha remota e QR sobem sozinhos)")
        return proc2

    # Desistiu — encerra o que sobrou e avisa sem derrubar o sistema.
    if proc2 is not None:
        try:
            proc2.terminate()
        except Exception:
            pass
    try:
        if os.path.isfile(CF_URL_STATE):
            os.remove(CF_URL_STATE)
    except OSError:
        pass
    log("sistema", "Tunel: o cloudflared nao estabeleceu o tunel (pode ser instabilidade "
                   "momentanea do Cloudflare ou falta de internet). Sistema segue sem tunel.")
    return None


def _porta_do_flask():
    """A porta em que o Flask escuta — mesma lógica usada no resto do sistema."""
    try:
        estado = painel_config.carregar_estado()
    except Exception:
        estado = {}
    return (estado.get("porta") or os.environ.get("GMA_PORT", "5050") or "5050").strip() or "5050"


def porta_livre(porta):
    """
    True se dá para escutar na porta AGORA (ninguém vivo a está segurando).
    Usa SO_REUSEADDR para espelhar como o Flask (Werkzeug) realmente faz o bind:
    assim só dá False quando há um processo de fato escutando — não por um
    socket em TIME_WAIT, que o Flask conseguiria reusar.
    """
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.bind(("127.0.0.1", int(porta)))
        return True
    except OSError:
        return False
    except Exception:
        return True  # na dúvida, não travamos a subida
    finally:
        s.close()


def esperar_porta_livre(porta, timeout=20):
    """Espera a porta liberar (poll de 0,5s até `timeout` s). True se liberou."""
    fim = time.time() + timeout
    while time.time() < fim:
        if porta_livre(porta):
            return True
        time.sleep(0.5)
    return porta_livre(porta)


def _flask_no_ar(processo, porta, espera=3.0):
    """Confere se o Flask subiu de verdade: processo vivo E já escutando na porta."""
    if processo is None:
        return False
    fim = time.time() + espera
    while time.time() < fim:
        if processo.poll() is not None:
            return False                 # morreu (provável "Address already in use")
        if not porta_livre(porta):
            return True                  # alguém está escutando = o Flask subiu
        time.sleep(0.3)
    return processo.poll() is None       # vivo mas ainda ligando — damos por no ar


def subir_todos():
    """
    Sobe os seis processos do GMA na ordem certa e devolve o dicionário deles.
    A ordem importa: Porteiro (detecta cartões) → Leitor (analisa) →
    Flask (interface) → Transferência (copia) → Auditoria → Sheets.
    O túnel (ngrok) sobe por último, opcional, se a ficha remota estiver ligada.
    """
    processos = {}
    processos["Porteiro"]        = iniciar_processo(SCRIPT_PORTEIRO,      "porteiro",      "Porteiro")
    processos["Leitor de Midia"] = iniciar_processo(SCRIPT_LEITOR,        "leitor",        "Leitor de Midia")

    # O Flask é o processo CRÍTICO — é ele que serve o painel/ficha. Numa troca
    # de projeto, o Flask anterior pode levar um instante para soltar a porta;
    # se subimos o novo cedo demais, ele morre com "Address already in use" e
    # o operador fica sem tela (foi o bug do teste s41). Por isso: (1) esperamos
    # a porta liberar de verdade antes de subir; (2) se mesmo assim não subir,
    # tentamos uma segunda vez. As outras camadas não disputam porta.
    porta = _porta_do_flask()
    if not esperar_porta_livre(porta, timeout=20):
        log("sistema", f"AVISO: porta {porta} ainda ocupada apos espera — subindo o Flask assim mesmo.")
    processos["Flask"] = iniciar_processo(SCRIPT_FLASK, "flask", "Flask")
    if not _flask_no_ar(processos["Flask"], porta):
        log("sistema", "Flask nao subiu (porta ocupada?). Aguardando a porta e tentando de novo...")
        encerrar_processo(processos["Flask"], "Flask")
        esperar_porta_livre(porta, timeout=15)
        processos["Flask"] = iniciar_processo(SCRIPT_FLASK, "flask", "Flask")
        if _flask_no_ar(processos["Flask"], porta):
            log("sistema", "Flask subiu na segunda tentativa.")
        else:
            log("sistema", "AVISO: Flask ainda nao subiu — o painel pode ficar indisponivel. "
                           "Use Encerrar GMA + Iniciar GMA se a tela nao responder.")

    processos["Transferencia"]   = iniciar_processo(SCRIPT_TRANSFERENCIA, "transferencia", "Transferencia")
    processos["Auditoria"]       = iniciar_processo(SCRIPT_AUDITORIA,     "auditoria",     "Auditoria")
    processos["Sheets"]          = iniciar_processo(SCRIPT_SHEETS,        "sheets",        "Exportador Sheets")
    # Camada 6 (IA), opcional: vigia que transcreve cartões de áudio sozinho. Sobe
    # como mais um processo de fundo; se a caixa .venv_ia não existir, ele apenas
    # dorme (nunca atrapalha o ciclo crítico).
    processos["Transcricao"]     = iniciar_processo(SCRIPT_VIGIA_TRANSCRICAO, "transcricao", "Vigia da Transcricao")

    iniciados = sum(1 for p in processos.values() if p is not None)
    print()
    log("sistema", f"{iniciados} de {len(processos)} processos iniciados com sucesso.")

    # Túnel opcional (Cloudflare) — sobe junto se a ficha remota estiver ligada.
    # Falha graciosa: se não subir, o sistema continua (a ficha segue na rede local).
    # Antes: ngrok (removido — conflitava com o Cloudflare e exibia tela de aviso no QR).
    processos["Cloudflare"] = iniciar_cloudflared()
    return processos


def descer_todos(processos):
    """Encerra os processos filhos na ordem inversa da inicialização."""
    encerrar_processo(processos.get("Cloudflare"),      "Tunel (cloudflared)")
    # Remove o arquivo de estado do túnel para o QR não mostrar uma URL morta
    # após o encerramento (o próximo Iniciar começa com a tela limpa).
    try:
        if os.path.isfile(CF_URL_STATE):
            os.remove(CF_URL_STATE)
    except OSError:
        pass
    encerrar_processo(processos.get("Transcricao"),     "Vigia da Transcricao")
    encerrar_processo(processos.get("Sheets"),          "Exportador Sheets")
    encerrar_processo(processos.get("Auditoria"),       "Auditoria")
    encerrar_processo(processos.get("Transferencia"),   "Transferencia")
    encerrar_processo(processos.get("Flask"),           "Flask")
    encerrar_processo(processos.get("Leitor de Midia"), "Leitor de Midia")
    encerrar_processo(processos.get("Porteiro"),        "Porteiro")


def limpar_sinais():
    """Remove o sinal de encerrar (caso tenha sobrado de uma sessão anterior)."""
    try:
        if os.path.isfile(SINAL_ENCERRAR):
            os.remove(SINAL_ENCERRAR)
    except OSError:
        pass


def main():
    """
    Fluxo principal do inicializador:

    1. Exibe o cabeçalho do GMA e aplica o projeto ativo (Painel de Controle).
    2. Cria o sentinela .gma_ativo.
    3. Sobe os seis processos no projeto ativo.
    4. Entra em modo de espera, mostrando os logs e vigiando o sinal de encerrar
       do painel (.gma_encerrar → desce tudo e finaliza).
    5. Ao receber Ctrl+C ou o sinal de encerrar: encerra tudo de forma limpa.

    Observação: hoje o ponto de entrada do GMA é o saguão (saguao.py), que sobe e
    desce a sessão do projeto. Este main() continua válido como arranque direto de
    emergência (um projeto, sem troca ao vivo), mas não é o caminho normal.
    """

    # ── Trava de instância única (ANTES de tudo) ─────────────────────────────
    # Um clique a mais no "Iniciar" não pode subir um segundo maestro. Se já há
    # um GMA rodando, este aqui para na hora — sem prompt, sem pendurar.
    if not adquirir_trava_maestro():
        # O sistema JA esta ligado. Em vez de so piscar uma mensagem que some
        # quando a janela fecha, abrimos o painel no navegador — assim o operador
        # ve na hora que o GMA esta no ar (e nao fica na duvida se ligou ou nao).
        painel_url = "http://127.0.0.1:5050/painel"
        print()
        print("  O GMA ja esta rodando (um so sistema por vez).")
        print(f"  Abrindo o painel no navegador: {painel_url}")
        print("  Para desligar, use 'Encerrar GMA'.")
        print()
        try:
            subprocess.run(["open", painel_url], timeout=5)
        except Exception:
            pass  # se nao abrir o navegador, a mensagem acima ja orienta
        sys.exit(0)

    print()
    print("=" * 60)
    print("  GMA — Gerenciamento de Midia Audiovisual")
    print(f"  Inicializando sistema em {agora()}")
    print("=" * 60)
    print()

    # ── Painel de Controle: aplica o projeto ativo ANTES do .env ─────────────
    # Define GMA_DB e GMA_DESTINO a partir do projeto ativo. Vem antes do .env
    # para ter prioridade; o .env (Sheets, senha, etc.) preenche o resto.
    try:
        slug, config = painel_config.aplicar_ao_ambiente(os.environ)
        log("sistema", f"Projeto ativo: {config.get('nome', slug)} "
                       f"(banco: {os.environ.get('GMA_DB')})")
    except Exception as erro:
        log("sistema", f"AVISO: nao foi possivel ler o projeto ativo ({erro}). Usando o laboratorio.")

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

    # ── Instrução sobre o túnel / Tally ──────────────────────────────────────
    # O cloudflared sobe AUTOMATICAMENTE junto com o sistema (se estiver instalado
    # e a ficha remota estiver ligada no projeto ativo). Não é preciso abrir outro
    # terminal. A URL pública aparece no log e o QR Code do painel atualiza sozinho.
    #
    # Se preferir subir o túnel manualmente (reserva ou depuração), use:
    #   ./cloudflared_gma.sh
    # Mas atenção: o script detecta se o maestro já subiu um túnel e sai sem criar
    # um segundo, para não gerar conflito nem sobrescrever a URL do QR.
    log("sistema", "Tunel Cloudflare: sobe automaticamente se cloudflared estiver instalado "
                   "e a ficha remota estiver ligada no projeto ativo.")

    # Verifica se já existem instâncias rodando antes de iniciar
    if not verificar_instancias_ativas():
        sys.exit(0)

    # Sinais antigos (de uma sessão anterior) não devem disparar nada agora
    limpar_sinais()

    # Cria o sentinela antes de ligar qualquer processo
    criar_sentinela()

    # Sobe os processos no projeto ativo
    processos = subir_todos()
    log("sistema", "Sistema GMA ativo. Ctrl+C encerra; o Painel de Controle pode "
                   "desligar o sistema.")
    print()

    # ── Loop de espera + vigia do sinal de encerrar ───────────────────────────
    # O processo principal fica vivo aqui. Além do Ctrl+C, ele observa o sinal
    # criados pelo Flask quando o operador usa o Painel de Controle.
    try:
        while True:
            time.sleep(1)

            # Sinal de ENCERRAR (botão "Encerrar sistema" no painel)
            if os.path.isfile(SINAL_ENCERRAR):
                os.remove(SINAL_ENCERRAR)
                print()
                log("sistema", "Sinal de ENCERRAR recebido pelo painel. Encerrando...")
                descer_todos(processos)
                remover_sentinela()
                liberar_trava_maestro()
                print()
                log("sistema", "Sistema GMA encerrado pelo painel.")
                print()
                return

    except KeyboardInterrupt:
        # Ctrl+C recebido — encerra tudo de forma limpa
        print()
        log("sistema", "Encerrando sistema...")
        descer_todos(processos)
        remover_sentinela()
        liberar_trava_maestro()
        print()
        log("sistema", "Sistema GMA encerrado com seguranca.")
        print()


if __name__ == "__main__":
    main()
