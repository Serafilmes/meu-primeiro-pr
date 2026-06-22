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

# Arquivo sentinela: quando existe, o Porteiro processa eventos
SENTINELA = os.path.join(RAIZ_GMA, ".gma_ativo")

# Trava de instância única do maestro. Um lock de arquivo (flock) garante UM
# ÚNICO maestro por vez: se o "Iniciar" for acionado duas vezes, o segundo não
# consegue o lock e sai na hora (sem prompt, sem pendurar). O flock se solta
# sozinho quando o processo morre — então um maestro que caiu não deixa a trava
# presa (não precisa limpar PID velho).
TRAVA_MAESTRO = os.path.join(RAIZ_GMA, ".gma_maestro.lock")
_trava_handle = None  # mantém o arquivo aberto pela vida do processo (segura o lock)

# Sinais do Painel de Controle (Camada 5). O Flask cria estes arquivos quando o
# operador clica em "Trocar projeto" / "Reiniciar" / "Encerrar". O maestro vigia
# o laço de espera e age:
#   .gma_reiniciar → desce todos os processos e sobe de novo no projeto escolhido
#   .gma_encerrar  → desce tudo e finaliza o sistema (botão "Encerrar")
SINAL_REINICIAR = os.path.join(RAIZ_GMA, ".gma_reiniciar")
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

def iniciar_ngrok():
    """
    Sobe o ngrok como processo OPCIONAL do maestro — o túnel sobe junto com o
    sistema, sem terminal separado. Só age quando faz sentido:
      - o projeto ativo está com a ficha remota LIGADA (tunel_ativo), E
      - NÃO há link fixo/override (modo automático — caso do plano gratuito), E
      - o ngrok está instalado, E
      - ainda não há um ngrok no ar.

    Verifica DE VERDADE: espera o túnel aparecer na API local (127.0.0.1:4040).
    Se não subir (falta authtoken ou internet), AVISA e segue — o sistema todo
    continua de pé (offline-first: o túnel é sempre opcional; as câmeras ainda
    alcançam a ficha pela rede local). O Flask detecta a URL sozinho, então o QR
    aparece quando o túnel sobe.

    Retorna o Popen do ngrok, ou None se não subiu / não se aplica.
    """
    # 1) A ficha remota está ligada neste projeto?
    try:
        _slug, cfg = painel_config.projeto_ativo()
    except Exception:
        cfg = {}
    if not cfg.get("tunel_ativo", True):
        log("sistema", "Tunel: ficha remota desativada no Painel — ngrok nao iniciado.")
        return None

    # 2) Link fixo/override? Então o túnel é gerido por você (domínio fixo/manual).
    if (cfg.get("tunel_link") or os.environ.get("GMA_LINK_FICHA", "")).strip():
        log("sistema", "Tunel: link fixo configurado — ngrok nao e gerido pelo maestro.")
        return None

    # 3) ngrok instalado?
    if not shutil.which("ngrok"):
        log("sistema", "Tunel: ngrok nao instalado — ficha so na rede local "
                       "(brew install ngrok/ngrok/ngrok).")
        return None

    # 4) Já há um ngrok no ar (ex.: subido à mão)? Não sobe outro (evita conflito no 4040).
    if _tunel_no_ar():
        log("sistema", "Tunel: ja ha um ngrok no ar — o maestro nao sobe outro.")
        return None

    # Sobe o ngrok apontando para a porta do Flask.
    estado = painel_config.carregar_estado()
    porta = (estado.get("porta") or os.environ.get("GMA_PORT", "5050") or "5050").strip() or "5050"
    try:
        proc = subprocess.Popen(
            ["ngrok", "http", str(porta), "--log=stderr"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=RAIZ_GMA,
        )
    except Exception as erro:
        log("sistema", f"Tunel: falha ao iniciar o ngrok ({erro}). Sistema segue sem tunel.")
        return None

    # Verifica: o túnel aparece na API local em até ~6s?
    url = None
    for _ in range(12):
        time.sleep(0.5)
        if proc.poll() is not None:
            break  # o ngrok já morreu (provável authtoken/credencial)
        url = _tunel_url()
        if url:
            break

    if url:
        log("sistema", f"Tunel ATIVO: {url} (ficha remota e QR sobem sozinhos)")
        return proc

    # Não subiu — encerra o que ficou e avisa, sem derrubar o sistema.
    log("sistema", "Tunel: o ngrok nao estabeleceu o tunel. Confira o authtoken "
                   "(ngrok config add-authtoken <token>) e a internet. Sistema segue sem tunel.")
    try:
        proc.terminate()
    except Exception:
        pass
    return None


def _tunel_url():
    """URL HTTPS pública do ngrok agora (via API local 127.0.0.1:4040), ou None."""
    import urllib.request
    try:
        with urllib.request.urlopen("http://127.0.0.1:4040/api/tunnels", timeout=1) as r:
            dados = json.loads(r.read().decode())
        for t in dados.get("tunnels", []):
            if t.get("public_url", "").startswith("https"):
                return t["public_url"]
    except Exception:
        pass
    return None


def _tunel_no_ar():
    """True se já existe um túnel ngrok HTTPS ativo na API local."""
    return _tunel_url() is not None


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

    # Túnel opcional (ngrok) — sobe junto se a ficha remota estiver ligada.
    # Falha graciosa: se não subir, o sistema continua (a ficha segue na rede local).
    processos["Ngrok"] = iniciar_ngrok()
    return processos


def descer_todos(processos):
    """Encerra os processos filhos na ordem inversa da inicialização."""
    encerrar_processo(processos.get("Ngrok"),           "Tunel (ngrok)")
    encerrar_processo(processos.get("Transcricao"),     "Vigia da Transcricao")
    encerrar_processo(processos.get("Sheets"),          "Exportador Sheets")
    encerrar_processo(processos.get("Auditoria"),       "Auditoria")
    encerrar_processo(processos.get("Transferencia"),   "Transferencia")
    encerrar_processo(processos.get("Flask"),           "Flask")
    encerrar_processo(processos.get("Leitor de Midia"), "Leitor de Midia")
    encerrar_processo(processos.get("Porteiro"),        "Porteiro")


def limpar_sinais():
    """Remove os sinais do painel (caso tenham sobrado de uma sessão anterior)."""
    for caminho in (SINAL_REINICIAR, SINAL_ENCERRAR):
        try:
            if os.path.isfile(caminho):
                os.remove(caminho)
        except OSError:
            pass


def main():
    """
    Fluxo principal do inicializador:

    1. Exibe o cabeçalho do GMA e aplica o projeto ativo (Painel de Controle).
    2. Cria o sentinela .gma_ativo.
    3. Sobe os seis processos no projeto ativo.
    4. Entra em modo de espera, mostrando os logs e vigiando os sinais do painel
       (.gma_reiniciar → reinicia no projeto escolhido; .gma_encerrar → encerra).
    5. Ao receber Ctrl+C ou o sinal de encerrar: encerra tudo de forma limpa.
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

    # Sinais antigos (de uma sessão anterior) não devem disparar nada agora
    limpar_sinais()

    # Cria o sentinela antes de ligar qualquer processo
    criar_sentinela()

    # Sobe os processos no projeto ativo
    processos = subir_todos()
    log("sistema", "Sistema GMA ativo. Ctrl+C encerra; o Painel de Controle pode "
                   "reiniciar/trocar de projeto/encerrar.")
    print()

    # ── Loop de espera + vigia dos sinais do painel ───────────────────────────
    # O processo principal fica vivo aqui. Além do Ctrl+C, ele observa os sinais
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

            # Sinal de REINICIAR (botão "Trocar projeto" / "Reiniciar" no painel)
            if os.path.isfile(SINAL_REINICIAR):
                os.remove(SINAL_REINICIAR)
                print()
                log("sistema", "Sinal de REINICIAR recebido pelo painel. Reiniciando...")

                # ── BLINDAGEM: a troca de projeto NUNCA pode derrubar o maestro ──
                # Se uma etapa falhar (projeto com caminho ruim, porta presa etc.),
                # registramos o aviso e SEGUIMOS DE PÉ — o operador continua podendo
                # escolher outro projeto pelo painel. Antes, uma exceção aqui matava
                # o maestro e deixava o Flask órfão vivo: a tela respondia mas dizia
                # "o maestro não está rodando". É também o 1º tijolo do modelo de
                # 2 níveis (o "saguão" do nível 1 não cai quando o projeto troca).
                try:
                    descer_todos(processos)
                except Exception as erro:
                    log("sistema", f"AVISO: falha ao descer os processos ({erro}).")

                # Re-aplica o projeto ativo FORÇANDO (a escolha do operador vence).
                try:
                    slug, config = painel_config.aplicar_ao_ambiente(os.environ, forcar=True)
                    log("sistema", f"Reiniciando no projeto: {config.get('nome', slug)} "
                                   f"(banco: {os.environ.get('GMA_DB')})")
                except Exception as erro:
                    log("sistema", f"AVISO: falha ao reaplicar o projeto ({erro}).")

                time.sleep(2)  # respiro para as portas/arquivos liberarem

                try:
                    processos = subir_todos()
                    log("sistema", "Sistema GMA reiniciado.")
                except Exception as erro:
                    # A subida falhou — o maestro NÃO morre. Sem isto, sobraria um
                    # Flask órfão e o painel acusaria "maestro não está rodando".
                    processos = {}
                    log("sistema", f"ERRO ao subir o projeto ({erro}). O maestro segue "
                                   f"de pé — escolha outro projeto no painel ou tente de novo.")
                print()

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
