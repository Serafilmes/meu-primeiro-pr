#!/usr/bin/env python3
"""
exportador_sheets.py
Camada 3 do GMA — Exportação assíncrona para Google Sheets.

Responsabilidade:
  - Ler os metadados do banco local (gma.db) e espelhar na planilha do evento.
  - Offline-first: quando não há internet, aguarda silenciosamente e tenta de
    novo na próxima rodada do loop.
  - Só exporta metadados — NUNCA arquivos de mídia.
  - Reescreve a aba 'GMA' completa a cada sincronização (sem append parcial),
    o que garante que qualquer correção ou atualização de status apareça.

Variáveis de ambiente necessárias (configurar no .env):
    GOOGLE_CREDENTIALS_JSON  — caminho do arquivo JSON da conta de serviço
    GMA_SHEETS_ID            — ID da planilha Google Sheets (do URL: /d/<ID>/edit)

Como obter as credenciais:
    1. Acesse console.cloud.google.com e crie (ou abra) um projeto.
    2. Ative a API "Google Sheets API" no projeto.
    3. Vá em "Credenciais" → "Criar credenciais" → "Conta de serviço".
    4. Baixe o JSON da conta de serviço e salve em algum lugar seguro
       (ex: /Users/serafa/GMA/credenciais_google.json).
    5. Abra a planilha do evento e compartilhe com o e-mail da conta de serviço
       (campo "client_email" dentro do JSON) dando permissão de edição.
    6. Copie o ID da planilha do URL e cole em GMA_SHEETS_ID no .env.

Uso para testar:
    python3 /Users/serafa/GMA/exportador_sheets.py
"""

import os
import time
import logging
import socket
from datetime import datetime

import banco_dados

# ── CONSTANTES ─────────────────────────────────────────────────────────────────

RAIZ_GMA = "/Users/serafa/GMA"

# Intervalo entre tentativas de sincronização (segundos)
INTERVALO_SYNC = 60

# As COLUNAS são DINÂMICAS (s34 — Fatia 5): vêm do mesmo montador que a /planilha
# local (banco_dados.montar_planilha), refletindo o Molde + os grupos editáveis.
# Criar/renomear/ligar/desligar uma coluna ou um grupo aparece aqui automaticamente,
# sem mexer neste arquivo. O Sheets é espelho FIEL da /planilha do Flask.

# ── LOG ────────────────────────────────────────────────────────────────────────

os.makedirs(os.path.join(RAIZ_GMA, "logs"), exist_ok=True)

logging.basicConfig(
    filename=os.path.join(RAIZ_GMA, "logs", "exportador_sheets.log"),
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
log = logging.getLogger(__name__)


# ── CARREGAMENTO DO .env ───────────────────────────────────────────────────────

def _carregar_env_local():
    """
    Carrega o .env do projeto para o ambiente, SEM sobrescrever o que já existe.

    Por que existe: o exportador lê as credenciais de os.environ. Quando rodado
    pelo inicializar_gma, o .env já foi carregado e isto vira no-op. Quando rodado
    SOZINHO para teste (`python3 exportador_sheets.py`), é isto que faz as
    variáveis GOOGLE_CREDENTIALS_JSON / GMA_SHEETS_ID aparecerem.
    """
    caminho = os.path.join(RAIZ_GMA, ".env")
    if not os.path.isfile(caminho):
        return
    try:
        with open(caminho, "r", encoding="utf-8") as f:
            for linha in f:
                linha = linha.strip()
                if not linha or linha.startswith("#") or "=" not in linha:
                    continue
                chave, _, valor = linha.partition("=")
                chave, valor = chave.strip(), valor.strip()
                if chave and chave not in os.environ:
                    os.environ[chave] = valor
    except Exception as e:
        log.warning(f"Não consegui ler o .env: {e}")


# ── VERIFICAÇÕES DE PRÉ-CONDIÇÃO ───────────────────────────────────────────────

def _gcloud_bin():
    """Localiza o executável do gcloud (necessário para a impersonação)."""
    import shutil
    cam = shutil.which("gcloud")
    if cam:
        return cam
    for c in ("/opt/homebrew/bin/gcloud", "/usr/local/bin/gcloud",
              os.path.expanduser("~/google-cloud-sdk/bin/gcloud")):
        if os.path.isfile(c):
            return c
    return None


def _credenciais_configuradas():
    """
    Verifica se dá para exportar. Dois modos de autenticação:

      (A) Impersonação de conta de serviço — RECOMENDADO para Google Workspace:
          GMA_SHEETS_SA = e-mail da conta de serviço. Usa o gcloud para gerar
          tokens curtos sob demanda, SEM nenhum arquivo de chave. Respeita a
          política de organização que bloqueia download de chaves de SA.

      (B) Chave de conta de serviço (clássico):
          GOOGLE_CREDENTIALS_JSON = caminho do arquivo JSON da conta de serviço.

    Em ambos os modos, GMA_SHEETS_ID é obrigatório.
    """
    sheet_id = os.environ.get("GMA_SHEETS_ID", "").strip()
    if not sheet_id:
        return False, "GMA_SHEETS_ID não definido no .env"

    # Modo A — impersonação
    sa = os.environ.get("GMA_SHEETS_SA", "").strip()
    if sa:
        if not _gcloud_bin():
            return False, "GMA_SHEETS_SA definido, mas o gcloud não foi encontrado no PATH"
        return True, None

    # Modo B — chave JSON
    cred = os.environ.get("GOOGLE_CREDENTIALS_JSON", "").strip()
    if not cred:
        return False, "Defina GMA_SHEETS_SA (impersonação) OU GOOGLE_CREDENTIALS_JSON no .env"
    if cred == "cole_aqui_o_caminho_do_json":
        return False, "Credenciais ainda com valor padrão — preencha o .env"
    if not os.path.isfile(cred):
        return False, f"Arquivo de credenciais não encontrado: {cred}"
    return True, None


def _token_impersonado(sa):
    """
    Gera um access token curto da conta de serviço via gcloud (impersonação).
    O token fica só em memória — nunca é gravado em disco.
    """
    import subprocess
    gcloud = _gcloud_bin()
    if not gcloud:
        raise RuntimeError("gcloud não encontrado para a impersonação.")
    r = subprocess.run(
        [gcloud, "auth", "print-access-token",
         "--impersonate-service-account=" + sa,
         "--scopes=https://www.googleapis.com/auth/spreadsheets"],
        capture_output=True, text=True, timeout=60,
    )
    if r.returncode != 0:
        raise RuntimeError(f"Falha ao gerar token de impersonação: {r.stderr.strip()[:200]}")
    return r.stdout.strip()


def _tem_internet(host="www.google.com", porta=443, timeout=5):
    """Testa se há conectividade com a internet tentando abrir um socket."""
    try:
        socket.setdefaulttimeout(timeout)
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect((host, porta))
        return True
    except Exception:
        return False


# ── SINCRONIZAÇÃO COM O SHEETS ─────────────────────────────────────────────────

def _abrir_planilha():
    """
    Abre a planilha. Usa impersonação (GMA_SHEETS_SA) quando configurada — sem
    chave; senão cai para a chave de conta de serviço (GOOGLE_CREDENTIALS_JSON).
    """
    import gspread
    sheet_id = os.environ["GMA_SHEETS_ID"]
    sa = os.environ.get("GMA_SHEETS_SA", "").strip()

    if sa:
        # Modo A — impersonação: token curto gerado pelo gcloud, sem arquivo de chave.
        from google.oauth2.credentials import Credentials
        credenciais = Credentials(token=_token_impersonado(sa))
    else:
        # Modo B — chave de conta de serviço.
        from google.oauth2.service_account import Credentials as SACredentials
        SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
        credenciais = SACredentials.from_service_account_file(
            os.environ["GOOGLE_CREDENTIALS_JSON"], scopes=SCOPES)

    cliente = gspread.authorize(credenciais)
    return cliente.open_by_key(sheet_id)


def sincronizar(conn):
    """
    Exporta todos os cartões do banco para a aba 'GMA' da planilha.

    Estratégia: reescreve a aba completa (clear + update) em vez de append.
    Isso garante que atualizações de status (ex: 'copiando' → 'concluido')
    apareçam corretamente sem duplicar linhas.

    Retorna True se bem-sucedido, False se falhou.
    """
    ok, erro = _credenciais_configuradas()
    if not ok:
        log.warning(f"Exportação não configurada: {erro}")
        return False

    if not _tem_internet():
        log.info("Sem internet — sincronização adiada.")
        return False

    try:
        # Monta colunas + linhas a partir da MESMA fonte da /planilha local
        # (Molde + grupos editáveis). É o que torna o Sheets dinâmico (s34).
        colunas, linhas = banco_dados.montar_planilha(conn)
        cabecalho = [c["rotulo"] for c in colunas]
        n_cols = len(cabecalho)
        conteudo = [cabecalho] + linhas

        planilha = _abrir_planilha()

        # Garante que a aba 'GMA' existe (cria se não existir)
        try:
            aba = planilha.worksheet("GMA")
        except Exception:
            aba = planilha.add_worksheet(title="GMA", rows=2000, cols=n_cols + 4)

        # Limpa a aba e reescreve tudo de uma vez (uma única chamada à API).
        # gspread 6.x: update(values, range_name) — usamos argumentos nomeados
        # para não depender da ordem (a 5.x era o inverso).
        aba.clear()
        if conteudo:
            aba.update(values=conteudo, range_name="A1")

        # Formata o cabeçalho em negrito
        if n_cols:
            aba.format(f"A1:{_coluna_letra(n_cols)}1", {"textFormat": {"bold": True}})

        log.info(f"Sheets sincronizado: {len(linhas)} cartão(ões), {n_cols} coluna(s).")
        return True

    except Exception as e:
        log.warning(f"Falha na sincronização: {e}")
        return False


def _coluna_letra(n):
    """Converte número de coluna (1-based) para letra do Sheets (ex: 16 → 'P')."""
    resultado = ""
    while n > 0:
        n, resto = divmod(n - 1, 26)
        resultado = chr(65 + resto) + resultado
    return resultado


# ── LOOP CONTÍNUO ──────────────────────────────────────────────────────────────

def loop_exportador():
    """
    Loop de sincronização contínua (roda como processo independente).
    Tenta sincronizar a cada INTERVALO_SYNC segundos.
    Se não houver credenciais configuradas, aguarda em silêncio.
    """
    print("[SHEETS]        Exportador Camada 3 iniciado.", flush=True)

    _carregar_env_local()  # garante as credenciais mesmo se rodado fora do inicializar_gma

    ok, erro = _credenciais_configuradas()
    if not ok:
        print(f"[SHEETS]        AVISO: {erro}", flush=True)
        print("[SHEETS]        Configure GOOGLE_CREDENTIALS_JSON e GMA_SHEETS_ID no .env.", flush=True)
        print("[SHEETS]        Exportação automática desativada até configuração.", flush=True)

    while True:
        try:
            conn = banco_dados.obter_conexao()
            sucesso = sincronizar(conn)
            conn.close()

            if sucesso:
                print(f"[SHEETS]        Planilha atualizada em {datetime.now().strftime('%H:%M:%S')}.",
                      flush=True)

        except Exception as e:
            log.error(f"Erro no loop do exportador: {e}")

        time.sleep(INTERVALO_SYNC)


# ── PONTO DE ENTRADA (MODO DE TESTE) ──────────────────────────────────────────

if __name__ == "__main__":
    import sys
    sys.path.insert(0, RAIZ_GMA)

    _carregar_env_local()  # carrega GOOGLE_CREDENTIALS_JSON / GMA_SHEETS_ID do .env

    print()
    print("=" * 60)
    print("  GMA — Exportador Google Sheets (teste imediato)")
    print("=" * 60)
    print()

    ok, erro = _credenciais_configuradas()
    if not ok:
        print(f"ERRO: {erro}")
        print()
        print("Configure no .env:")
        print("  GOOGLE_CREDENTIALS_JSON=/Users/serafa/GMA/credenciais_google.json")
        print("  GMA_SHEETS_ID=cole_aqui_o_id_da_planilha")
        print()
        print("Guia de configuração:")
        print("  1. console.cloud.google.com → projeto → Ativar Google Sheets API")
        print("  2. Credenciais → Criar → Conta de serviço → baixar JSON")
        print("  3. Abrir a planilha → Compartilhar com o e-mail da conta de serviço")
        print("  4. Copiar o ID da planilha do URL e colar em GMA_SHEETS_ID")
        sys.exit(1)

    print("Verificando internet...")
    if not _tem_internet():
        print("Sem conexão com a internet. Tente novamente quando conectado.")
        sys.exit(1)

    conn = banco_dados.obter_conexao()
    print("Sincronizando...")
    sucesso = sincronizar(conn)
    conn.close()

    if sucesso:
        sheet_id = os.environ.get("GMA_SHEETS_ID", "")
        print(f"OK — planilha atualizada.")
        print(f"URL: https://docs.google.com/spreadsheets/d/{sheet_id}")
    else:
        print("FALHA — verifique logs/exportador_sheets.log")
        sys.exit(1)
