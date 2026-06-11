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

# Colunas exportadas para o Sheets (cabeçalho — 21 colunas)
# Ordem: identificação → campos do formulário (Camada 1) → status/integridade (Camada 2) → timestamps
CABECALHO = [
    "ID", "Cartão", "Profissional", "Câmera", "Modelo Câmera",
    "Tipo", "Tipo Conteúdo", "Local / Cena",
    "Data Gravação", "Prioridade",
    "Status", "Arquivos", "Tamanho", "Falhos", "Avisos",
    "Início Cópia", "Fim Cópia", "Pasta Destino",
    "Obs. Operador", "Obs. Formulário", "Criado em"
]

# ── LOG ────────────────────────────────────────────────────────────────────────

os.makedirs(os.path.join(RAIZ_GMA, "logs"), exist_ok=True)

logging.basicConfig(
    filename=os.path.join(RAIZ_GMA, "logs", "exportador_sheets.log"),
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
log = logging.getLogger(__name__)


# ── VERIFICAÇÕES DE PRÉ-CONDIÇÃO ───────────────────────────────────────────────

def _credenciais_configuradas():
    """Retorna (True, None) se as variáveis de ambiente estão definidas e o JSON existe."""
    cred = os.environ.get("GOOGLE_CREDENTIALS_JSON", "").strip()
    sheet_id = os.environ.get("GMA_SHEETS_ID", "").strip()

    if not cred or not sheet_id:
        return False, "GOOGLE_CREDENTIALS_JSON ou GMA_SHEETS_ID não definidos no .env"

    if cred == "cole_aqui_o_caminho_do_json":
        return False, "Credenciais ainda com valor padrão — preencha o .env"

    if not os.path.isfile(cred):
        return False, f"Arquivo de credenciais não encontrado: {cred}"

    return True, None


def _tem_internet(host="www.google.com", porta=443, timeout=5):
    """Testa se há conectividade com a internet tentando abrir um socket."""
    try:
        socket.setdefaulttimeout(timeout)
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect((host, porta))
        return True
    except Exception:
        return False


# ── LEITURA DO BANCO ───────────────────────────────────────────────────────────

def _ler_dados_do_banco(conn):
    """
    Consulta o banco e retorna uma lista de listas pronta para escrita no Sheets.
    Cada lista interna = uma linha (um cartão).
    """
    cursor = conn.execute("""
        SELECT
            c.id,
            c.numero_cartao,
            COALESCE(f.nome, '—')                              AS nome,
            COALESCE(f.camera, '—')                            AS camera,
            COALESCE(f.modelo_camera, '')                      AS modelo_camera,
            COALESCE(f.tipo_material, c.tipo_material, '—')   AS tipo_material,
            COALESCE(f.tipo_conteudo, '')                      AS tipo_conteudo,
            COALESCE(f.local_cena, '')                         AS local_cena,
            COALESCE(f.data_gravacao, '—')                     AS data_gravacao,
            COALESCE(f.prioridade, 'NORMAL')                   AS prioridade,
            c.status,
            COALESCE(c.total_arquivos_transferidos, 0)         AS total_arquivos,
            COALESCE(c.tamanho_transferido_bytes, 0)           AS tamanho_bytes,
            COALESCE(c.total_falhos, 0)                        AS falhos,
            COALESCE(c.total_avisos, 0)                        AS avisos,
            COALESCE(c.transferencia_timestamp_inicio, '')     AS inicio,
            COALESCE(c.transferencia_timestamp_fim, '')        AS fim,
            COALESCE(c.destino_pasta, '')                      AS destino,
            COALESCE(c.observacoes, '')                        AS obs_operador,
            COALESCE(f.observacoes, '')                        AS obs_form,
            c.criado_em
        FROM cartoes c
        LEFT JOIN matches m    ON m.cartao_id    = c.id
        LEFT JOIN formularios f ON f.id          = m.formulario_id
        ORDER BY c.id
    """)

    linhas = []
    for r in cursor.fetchall():
        tamanho_fmt = (
            f"{r['tamanho_bytes'] / 1_073_741_824:.2f} GB"
            if r["tamanho_bytes"]
            else "—"
        )
        linhas.append([
            str(r["id"]),
            r["numero_cartao"] or "—",
            r["nome"],
            r["camera"],
            r["modelo_camera"],       # NOVO — modelo específico da câmera
            r["tipo_material"],
            r["tipo_conteudo"],       # NOVO — classificação editorial (B-ROLL, ENTREVISTA...)
            r["local_cena"],          # NOVO — local ou cena de gravação
            r["data_gravacao"],
            r["prioridade"],          # NOVO — nível de urgência do cartão
            r["status"],
            str(r["total_arquivos"]),
            tamanho_fmt,
            str(r["falhos"]),
            str(r["avisos"]),
            r["inicio"],
            r["fim"],
            r["destino"],
            r["obs_operador"],        # era "observacoes" — notas do operador no painel
            r["obs_form"],            # NOVO — observações do profissional no formulário
            r["criado_em"],
        ])

    return linhas


# ── SINCRONIZAÇÃO COM O SHEETS ─────────────────────────────────────────────────

def _abrir_planilha():
    """Abre a planilha usando a conta de serviço configurada no .env."""
    import gspread
    from google.oauth2.service_account import Credentials

    SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
    cred_path = os.environ["GOOGLE_CREDENTIALS_JSON"]
    sheet_id  = os.environ["GMA_SHEETS_ID"]

    credenciais = Credentials.from_service_account_file(cred_path, scopes=SCOPES)
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
        planilha = _abrir_planilha()

        # Garante que a aba 'GMA' existe (cria se não existir)
        try:
            aba = planilha.worksheet("GMA")
        except Exception:
            aba = planilha.add_worksheet(title="GMA", rows=2000, cols=len(CABECALHO) + 2)

        linhas = _ler_dados_do_banco(conn)

        # Monta o conteúdo completo: cabeçalho + linhas de dados
        conteudo = [CABECALHO] + linhas

        # Limpa a aba e reescreve tudo de uma vez (uma única chamada à API)
        aba.clear()
        if conteudo:
            aba.update("A1", conteudo)

        # Formata o cabeçalho em negrito
        aba.format(f"A1:{_coluna_letra(len(CABECALHO))}1", {"textFormat": {"bold": True}})

        log.info(f"Sheets sincronizado com sucesso: {len(linhas)} cartão(ões).")
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
