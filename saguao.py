#!/usr/bin/env python3
"""
saguao.py
Camada 5 do GMA — o SAGUÃO (nível 1 da plataforma de 2 níveis).

A METÁFORA, em português claro:
  Pense no GMA como um prédio. O SAGUÃO é o térreo: você entra por ele, escolhe
  em qual projeto (em qual "andar") quer trabalhar e sobe. Cada projeto é uma
  SESSÃO (nível 2): ali rodam os processos de verdade (Flask na 5050, porteiro,
  leitor, transferência, etc.). Quando você quer trocar de projeto, você DESCE de
  volta ao saguão — sem desligar o prédio — e sobe noutro andar.

POR QUE ISSO EXISTE (o problema que resolve):
  Hoje o "maestro" (inicializar_gma.py) sobe os processos JÁ dentro de um projeto,
  e a tela do Painel é servida pelo Flask DESSE projeto (porta 5050). Trocar de
  projeto = derrubar tudo e subir de novo; se a subida falha, a tela morre e o
  operador fica sem nada na frente. O saguão elimina isso na raiz: ele tem o
  PRÓPRIO servidorzinho, numa PORTA FIXA SÓ DELE (5055), que NUNCA cai. Mesmo
  quando nenhum projeto está rodando, o saguão está de pé servindo a tela.

DESENHO (2 níveis):
  - Nível 1 = SAGUÃO  (este arquivo): sempre ligado. Mostra a lista de projetos +
    "criar novo" + qual está rodando agora. Não roda nenhum projeto sozinho.
  - Nível 2 = SESSÃO DO PROJETO: ao escolher um projeto, o saguão sobe os processos
    daquele projeto (reusando o motor que já existe no inicializar_gma.py).
  - TROCAR = descer só os processos do projeto e voltar ao saguão (que continuou
    de pé). Sem reinício frágil, sem tela morta.

PRINCÍPIOS (Camada 5): isto ORQUESTRA processos e serve uma tela enxuta. Não copia,
move nem apaga mídia. Não refaz a lógica das camadas 1–4 — só sobe e desce.

Tecnologia: usa o http.server da biblioteca padrão do Python (não um 2º Flask) —
o saguão precisa ser à prova de balas e nunca travar; um servidor mínimo de rotas
é mais fácil de manter blindado. Nada novo a instalar.

ESTADO: Fatia 1 — o saguão serve a tela e lista os projetos. Subir/descer a sessão
do projeto entra na Fatia 2.
"""

import fcntl
import html
import os
import signal
import subprocess
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import painel_config
# Reusa o motor de processos que já existe no maestro (subir/descer a sessão,
# sentinela, .env, caminhos). Importar é seguro: tudo lá está dentro de funções
# (o main() do maestro só roda quando ELE é o programa principal).
import inicializar_gma as maestro

# ── CONFIGURAÇÃO ────────────────────────────────────────────────────────────────

# A porta FIXA e exclusiva do saguão. Separada da 5050 (Flask do projeto) de
# propósito: o saguão vive ACIMA dos projetos e não disputa porta com eles.
PORTA_SAGUAO = int(os.environ.get("GMA_PORTA_SAGUAO", "5055"))

# Cor da identidade do GMA (mesma usada no resto do sistema).
VERDE_GMA = "#1D9E75"

# Trava de instância única do saguão (mesmo espírito da trava do maestro, mas com
# arquivo PRÓPRIO). Garante UM saguão por vez: um 2º "Iniciar" não sobe outro. O
# flock se solta sozinho quando o processo morre (não deixa trava presa).
TRAVA_SAGUAO = os.path.join(maestro.RAIZ_GMA, ".gma_saguao.lock")
_trava_handle = None  # mantém o arquivo aberto pela vida do processo (segura o lock)

# Sinal de encerrar (arquivo). O Painel do projeto (Flask) escreve este arquivo
# quando o operador clica em "Desligar o GMA"; o saguão — que é o PROCESSO PAI —
# vigia o arquivo e se desliga. Usamos arquivo (e não um sinal de processo) porque
# um filho mandar SIGTERM no próprio pai não é confiável no macOS; o pai vigiando
# um arquivo é simples e robusto. (Mesmo caminho que o maestro antigo já usava.)
SINAL_ENCERRAR = os.path.join(maestro.RAIZ_GMA, ".gma_encerrar")


# ── ESTADO DA SESSÃO (qual projeto está rodando agora) ──────────────────────────
#
# O saguão guarda UMA sessão por vez: o slug do projeto que está no ar e os
# processos filhos dele. Em Fatia 1 isto fica sempre "nenhum projeto rodando";
# a Fatia 2 passa a preencher de verdade ao subir/descer a sessão.
#
# O _trava_sessao protege o dicionário porque o http.server atende cada requisição
# numa thread — duas ações (ex.: dois cliques em "Entrar") não podem mexer no
# estado ao mesmo tempo.
_sessao = {"slug": None, "processos": {}}
_trava_sessao = threading.Lock()


def projeto_rodando():
    """Retorna o slug do projeto rodando agora, ou None se o saguão está ocioso."""
    with _trava_sessao:
        return _sessao["slug"]


# ── SUBIR / DESCER A SESSÃO DO PROJETO (nível 2) ────────────────────────────────

def entrar_no_projeto(slug):
    """
    Sobe a sessão de um projeto (nível 2): aplica o projeto ao ambiente e liga os
    processos dele (Flask na 5050 + porteiro/leitor/transferência/etc.), reusando
    o motor do maestro. Se já houver OUTRO projeto rodando, desce ele antes — um
    projeto por vez. Entrar no mesmo que já roda é no-op (só leva o operador lá).

    Segura o _trava_sessao a subida inteira de propósito: um 2º clique espera o 1º
    terminar, em vez de subir dois conjuntos de processos disputando a porta.
    """
    estado = painel_config.carregar_estado()
    if slug not in estado.get("projetos", {}):
        raise ValueError(f"Projeto desconhecido: {slug}")

    with _trava_sessao:
        if _sessao["slug"] == slug:
            return  # já está rodando este projeto — nada a fazer

        # Outro projeto no ar? Desce ele primeiro (volta ao saguão, sem reiniciar).
        if _sessao["slug"] is not None:
            maestro.descer_todos(_sessao["processos"])
            _sessao["slug"] = None
            _sessao["processos"] = {}

        # Marca como ativo e exporta GMA_DB/GMA_DESTINO/etc. para o ambiente — os
        # processos filhos herdam isto e nascem já dentro do projeto certo.
        painel_config.definir_ativo(slug)
        painel_config.aplicar_ao_ambiente(os.environ, forcar=True)

        maestro.criar_sentinela()          # liga o processamento (o Porteiro lê isto)
        _sessao["processos"] = maestro.subir_todos()
        _sessao["slug"] = slug


def voltar_ao_saguao():
    """
    Desce SÓ os processos do projeto atual e volta ao saguão (nível 1). O saguão
    em si nunca cai — é isto que elimina a tela morta da troca de projeto.
    """
    with _trava_sessao:
        if _sessao["slug"] is None:
            return
        maestro.descer_todos(_sessao["processos"])
        maestro.remover_sentinela()        # desliga o processamento
        _sessao["slug"] = None
        _sessao["processos"] = {}


def _desligar_em_breve():
    """Espera a resposta sair e manda SIGTERM para o próprio saguão (encerra limpo)."""
    time.sleep(0.3)
    os.kill(os.getpid(), signal.SIGTERM)


def criar_projeto_novo(nome):
    """
    Cria um projeto novo (a subpasta isolada + registro) e inicializa o banco
    vazio dele num subprocesso isolado, espelhando o que o Flask já fazia. NÃO
    entra automaticamente — devolve o slug para o operador clicar em "Entrar".
    """
    slug = painel_config.criar_projeto(nome)   # pode levantar ValueError (nome vazio/duplicado)
    estado = painel_config.carregar_estado()
    db = painel_config.caminho_db(estado["projetos"][slug])
    env = dict(os.environ)
    env["GMA_DB"] = db
    subprocess.run([maestro.PYTHON, "banco_dados.py"],
                   cwd=maestro.RAIZ_GMA, env=env, capture_output=True, text=True, timeout=120)
    return slug


# ── RENDERIZAÇÃO DA TELA ─────────────────────────────────────────────────────────

def _pagina(corpo_html):
    """Embrulha o corpo numa página HTML completa, com o estilo do GMA."""
    return f"""<!DOCTYPE html>
<html lang="pt-br">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>GMA — Saguão</title>
  <style>
    * {{ box-sizing: border-box; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background: #0f1115; color: #e8eaed; margin: 0;
      min-height: 100vh; display: flex; flex-direction: column; align-items: center;
      padding: 48px 20px;
    }}
    .marca {{ font-size: 13px; letter-spacing: 3px; color: {VERDE_GMA};
              text-transform: uppercase; font-weight: 700; margin-bottom: 6px; }}
    h1 {{ font-size: 26px; margin: 0 0 4px; font-weight: 600; }}
    .sub {{ color: #9aa0a8; margin-bottom: 32px; font-size: 15px; }}
    .lista {{ width: 100%; max-width: 560px; display: flex; flex-direction: column; gap: 12px; }}
    .projeto {{
      background: #1a1d24; border: 1px solid #2a2e37; border-radius: 12px;
      padding: 18px 20px; display: flex; align-items: center; justify-content: space-between;
      gap: 16px;
    }}
    .projeto .nome {{ font-size: 17px; font-weight: 600; }}
    .projeto .det {{ font-size: 13px; color: #80868f; margin-top: 3px; word-break: break-all; }}
    .projeto.ativo {{ border-color: {VERDE_GMA}; box-shadow: 0 0 0 1px {VERDE_GMA}; }}
    .pill {{ font-size: 12px; font-weight: 700; color: {VERDE_GMA};
             border: 1px solid {VERDE_GMA}; border-radius: 20px; padding: 3px 12px; white-space: nowrap; }}
    button, .botao {{
      font-family: inherit; font-size: 14px; font-weight: 600; cursor: pointer;
      border: none; border-radius: 9px; padding: 10px 20px; white-space: nowrap;
      background: {VERDE_GMA}; color: #07130d; transition: filter .12s;
    }}
    button:hover, .botao:hover {{ filter: brightness(1.1); }}
    .novo {{ width: 100%; max-width: 560px; margin-top: 22px; display: flex; gap: 10px; }}
    .novo input {{
      flex: 1; font-family: inherit; font-size: 14px; padding: 11px 14px;
      border-radius: 9px; border: 1px solid #2a2e37; background: #14171d; color: #e8eaed;
    }}
    .rodape {{ margin-top: 36px; color: #5c626b; font-size: 12px; text-align: center; line-height: 1.6; }}
    .aviso {{ width: 100%; max-width: 560px; background: #1f2530; border: 1px solid #33405a;
              border-radius: 10px; padding: 12px 16px; margin-bottom: 20px; font-size: 14px; color: #b9c4d6; }}
  </style>
</head>
<body>
  <div class="marca">GMA</div>
  <h1>Saguão</h1>
  <div class="sub">Em qual projeto você quer entrar?</div>
  {corpo_html}
  <div class="rodape">
    O saguão fica sempre ligado nesta porta ({PORTA_SAGUAO}).<br>
    Cada projeto roda na sua própria sessão (Flask na 5050) — trocar volta para cá sem desligar o sistema.
  </div>
</body>
</html>"""


def _corpo_lobby(aviso=None):
    """Monta o miolo da tela: a lista de projetos + o campo de criar novo."""
    estado = painel_config.carregar_estado()
    projetos = estado.get("projetos", {})
    rodando = projeto_rodando()

    partes = []
    if aviso:
        partes.append(f"<div class='aviso'>{html.escape(aviso)}</div>")

    partes.append("<div class='lista'>")
    for slug, cfg in projetos.items():
        nome = html.escape(cfg.get("nome", slug))
        db = html.escape(cfg.get("db", ""))
        eh_ativo = (slug == rodando)
        classe = "projeto ativo" if eh_ativo else "projeto"

        if eh_ativo:
            direita = (
                "<span class='pill'>● rodando</span>"
                f"<form method='post' action='/sair' style='margin:0'>"
                f"<button type='submit'>Voltar ao saguão</button></form>"
            )
        else:
            direita = (
                f"<form method='post' action='/entrar' style='margin:0'>"
                f"<input type='hidden' name='slug' value='{html.escape(slug)}'>"
                f"<button type='submit'>Entrar</button></form>"
            )

        partes.append(
            f"<div class='{classe}'>"
            f"  <div><div class='nome'>{nome}</div><div class='det'>{db}</div></div>"
            f"  <div style='display:flex; gap:10px; align-items:center'>{direita}</div>"
            f"</div>"
        )
    partes.append("</div>")

    partes.append(
        "<form class='novo' method='post' action='/criar'>"
        "  <input type='text' name='nome' placeholder='Nome de um projeto novo…' autocomplete='off'>"
        "  <button type='submit'>Criar projeto</button>"
        "</form>"
    )

    # Desligar o GMA inteiro — desce a sessão (se houver) e encerra o saguão.
    partes.append(
        "<form method='post' action='/encerrar' style='margin-top:26px' "
        "onsubmit=\"return confirm('Desligar todo o GMA agora?');\">"
        "<button type='submit' style='background:transparent;color:#c2554f;"
        "border:1px solid #5a3330'>⏻ Desligar o GMA</button></form>"
    )
    return "".join(partes)


# ── SERVIDOR HTTP ────────────────────────────────────────────────────────────────

class SaguaoHandler(BaseHTTPRequestHandler):
    """Atende as rotas do saguão. Mínimo de rotas, máximo de robustez."""

    # Silencia o log padrão barulhento do http.server (uma linha por requisição).
    def log_message(self, *args):
        pass

    def _responder(self, conteudo, status=200, tipo="text/html; charset=utf-8"):
        corpo = conteudo.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def _redirecionar(self, destino):
        self.send_response(303)            # "See Other" — o navegador segue com GET
        self.send_header("Location", destino)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _ler_form(self):
        """Lê o corpo de um POST de formulário e devolve um dict {campo: valor}."""
        try:
            tamanho = int(self.headers.get("Content-Length", 0))
        except (TypeError, ValueError):
            tamanho = 0
        bruto = self.rfile.read(tamanho).decode("utf-8") if tamanho else ""
        campos = urllib.parse.parse_qs(bruto)
        return {chave: valores[0] for chave, valores in campos.items()}

    def do_GET(self):
        if self.path in ("/", "/saguao"):
            self._responder(_pagina(_corpo_lobby()))
        else:
            self._responder(_pagina("<div class='aviso'>Página não encontrada.</div>"), status=404)

    def do_POST(self):
        dados = self._ler_form()
        try:
            if self.path == "/entrar":
                slug = (dados.get("slug") or "").strip()
                entrar_no_projeto(slug)
                # Leva o operador para dentro do projeto (o Flask já subiu — o
                # subir_todos espera o Flask responder antes de retornar).
                porta = (painel_config.carregar_estado().get("porta") or "5050")
                self._redirecionar(f"http://127.0.0.1:{porta}/")
                return
            if self.path == "/sair":
                voltar_ao_saguao()
                self._redirecionar("/")
                return
            if self.path == "/encerrar":
                # Responde primeiro (a tela confirma) e ENTÃO manda o sinal de
                # encerrar para si mesmo — o mesmo caminho do SIGTERM, que no
                # finally desce a sessão e desliga o saguão de forma limpa.
                self._responder(_pagina(
                    "<div class='aviso'>Desligando o GMA… pode fechar esta janela.</div>"))
                threading.Thread(target=_desligar_em_breve, daemon=True).start()
                return
            if self.path == "/criar":
                nome = (dados.get("nome") or "").strip()
                criar_projeto_novo(nome)
                self._responder(_pagina(_corpo_lobby(
                    aviso=f"Projeto “{nome}” criado. Clique em “Entrar” para começar nele.")))
                return
        except Exception as erro:
            # Nada de tela morta: qualquer falha vira um aviso claro no próprio saguão.
            self._responder(_pagina(_corpo_lobby(aviso=f"Não deu certo: {erro}")))
            return

        self._responder(_pagina(_corpo_lobby(aviso="Ação desconhecida.")), status=404)


def adquirir_trava_saguao():
    """Tenta travar o saguão (flock). Retorna True se conseguiu, False se já há um."""
    global _trava_handle
    try:
        _trava_handle = open(TRAVA_SAGUAO, "w")
        fcntl.flock(_trava_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    try:
        _trava_handle.seek(0)
        _trava_handle.truncate()
        _trava_handle.write(str(os.getpid()))
        _trava_handle.flush()
    except OSError:
        pass
    return True


def _vigia_sinal_encerrar():
    """
    Thread de fundo: vigia o arquivo .gma_encerrar (criado pelo Painel do projeto)
    e, quando aparece, desliga o saguão MANDANDO SIGTERM para si mesmo — o mesmo
    caminho do botão "Desligar" e do atalho Encerrar GMA (o único 100% confiável;
    chamar servidor.shutdown() direto da thread se mostrou intermitente). O handler
    de SIGTERM para o serve_forever e o finally do main() desce a sessão.
    """
    while True:
        time.sleep(1)
        if os.path.isfile(SINAL_ENCERRAR):
            try:
                os.remove(SINAL_ENCERRAR)
            except OSError:
                pass
            print("[SAGUÃO] sinal de encerrar recebido (Painel) — desligando…")
            os.kill(os.getpid(), signal.SIGTERM)
            return


def main():
    """Sobe o servidor do saguão e fica de pé até Ctrl+C ou sinal de encerrar."""
    # ── Trava de instância única ────────────────────────────────────────────────
    if not adquirir_trava_saguao():
        url = f"http://127.0.0.1:{PORTA_SAGUAO}/"
        print(f"  O GMA já está no ar (um saguão por vez). Abrindo: {url}")
        try:
            subprocess.run(["open", url], timeout=5)
        except Exception:
            pass
        sys.exit(0)

    # Carrega o .env uma vez (TALLY secret, etc.) — os processos filhos de cada
    # sessão herdam estas variáveis. A config por projeto (GMA_DB/destino) é
    # aplicada por cima, na hora de entrar no projeto.
    maestro.carregar_dotenv(os.path.join(maestro.RAIZ_GMA, ".env"))

    # Um sinal de encerrar que tenha sobrado de uma sessão anterior não pode
    # desligar o saguão recém-aberto.
    try:
        if os.path.isfile(SINAL_ENCERRAR):
            os.remove(SINAL_ENCERRAR)
    except OSError:
        pass

    servidor = ThreadingHTTPServer(("127.0.0.1", PORTA_SAGUAO), SaguaoHandler)
    threading.Thread(target=_vigia_sinal_encerrar, daemon=True).start()

    # Encerramento limpo pelo atalho "Encerrar GMA" (que manda SIGTERM): paramos o
    # serve_forever DE OUTRA THREAD (chamar shutdown() na própria thread do laço
    # travaria). O bloco finally cuida de descer a sessão e soltar tudo.
    def _encerrar(signum, frame):
        threading.Thread(target=servidor.shutdown, daemon=True).start()
    signal.signal(signal.SIGTERM, _encerrar)

    print(f"[SAGUÃO] no ar em http://127.0.0.1:{PORTA_SAGUAO}")
    print("[SAGUÃO] Ctrl+C (ou 'Encerrar GMA') encerra.")

    # Abre o saguão no navegador quando ligado pelo atalho (Terminal = tty).
    # Em teste/automação (saída redirecionada) não abre nada.
    if sys.stdout.isatty():
        try:
            subprocess.run(["open", f"http://127.0.0.1:{PORTA_SAGUAO}/"], timeout=5)
        except Exception:
            pass

    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\n[SAGUÃO] encerrando…")
    finally:
        # Se um projeto estava rodando, desce a sessão dele antes de sair — não
        # deixamos processos órfãos (Flask/porteiro/etc.) vivos sem o saguão.
        voltar_ao_saguao()
        servidor.shutdown()
        servidor.server_close()


if __name__ == "__main__":
    main()
