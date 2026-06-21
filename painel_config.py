#!/usr/bin/env python3
"""
painel_config.py
Camada 5 do GMA — Painel de Controle (Fatia 1).

Fonte ÚNICA de verdade do "qual projeto está ativo e quais são as conexões dele".
Tanto o Flask (a aba "Painel") quanto o maestro (inicializar_gma.py) leem daqui —
assim os dois nunca divergem.

Como funciona, em português claro:
  - Existe um arquivo de estado (painel_estado.json) na raiz do GMA.
  - Ele guarda QUAL projeto está ativo e o cadastro de TODOS os projetos
    (cada um com seu nome, seu banco e sua pasta de destino dos materiais).
  - O "laboratório" é só mais um projeto: o gma.db da raiz (o de sempre).
  - Se o arquivo não existir, o sistema assume o laboratório com os valores
    padrão de hoje — ou seja, NADA muda no laboratório enquanto ninguém mexer
    no painel. Segurança: o estado é só configuração, nunca toca em mídia.

Princípio (Camada 5): isto é "configuração externa virando dado" — a base do
Painel de Controle. NÃO copia, move nem apaga arquivo de mídia.
"""

import json
import os
import re
import unicodedata

# ── CAMINHOS ───────────────────────────────────────────────────────────────────

RAIZ_GMA = "/Users/serafa/GMA"

# Arquivo de estado do painel (registro dos projetos + qual está ativo).
ARQUIVO_ESTADO = os.path.join(RAIZ_GMA, "painel_estado.json")

# Pasta onde nascem os projetos novos (cada um na sua subpasta isolada).
PASTA_PROJETOS = os.path.join(RAIZ_GMA, "projetos")

# Valores padrão do laboratório (o gma.db de sempre + a pasta de teste de sempre).
LAB_SLUG = "laboratorio"
LAB_NOME = "Laboratório"
LAB_DB = "gma.db"
DESTINO_PADRAO = "/Users/serafa/GMA/TESTE LOGAGEM"


# ── LEITURA E ESCRITA DO ESTADO ─────────────────────────────────────────────────

def _projeto_laboratorio():
    """O laboratório como entrada de projeto (sempre presente)."""
    return {"nome": LAB_NOME, "db": LAB_DB, "destino": DESTINO_PADRAO}


def descobrir_projetos():
    """
    Varre a pasta projetos/ procurando subpastas que tenham um gma.db.
    Retorna um dicionário {slug: config} para os projetos encontrados.
    É só LEITURA — não cria nem apaga nada.
    """
    achados = {}
    if not os.path.isdir(PASTA_PROJETOS):
        return achados
    for nome_pasta in sorted(os.listdir(PASTA_PROJETOS)):
        caminho = os.path.join(PASTA_PROJETOS, nome_pasta)
        if not os.path.isdir(caminho):
            continue
        if os.path.isfile(os.path.join(caminho, "gma.db")):
            achados[nome_pasta] = {
                "nome": nome_pasta.replace("_", " ").title(),
                "db": os.path.join("projetos", nome_pasta, "gma.db"),
                "destino": DESTINO_PADRAO,
            }
    return achados


def carregar_estado():
    """
    Carrega o estado do painel. Se o arquivo não existir, monta um estado
    padrão (laboratório ativo) e auto-descobre os projetos já existentes em
    projetos/. Nunca falha: em qualquer erro, devolve o estado padrão.
    """
    estado = {"projeto_ativo": LAB_SLUG, "projetos": {LAB_SLUG: _projeto_laboratorio()}}

    if os.path.isfile(ARQUIVO_ESTADO):
        try:
            with open(ARQUIVO_ESTADO, "r", encoding="utf-8") as f:
                lido = json.load(f)
            if isinstance(lido, dict) and isinstance(lido.get("projetos"), dict):
                estado = lido
        except (OSError, ValueError):
            pass  # arquivo corrompido — segue com o padrão (não derruba o sistema)

    # Garante que o laboratório sempre existe no registro.
    estado.setdefault("projetos", {})
    estado["projetos"].setdefault(LAB_SLUG, _projeto_laboratorio())

    # Mescla projetos descobertos na pasta projetos/ que ainda não estão no registro.
    for slug, cfg in descobrir_projetos().items():
        estado["projetos"].setdefault(slug, cfg)

    # Se o projeto ativo apontar para algo que não existe, volta ao laboratório.
    if estado.get("projeto_ativo") not in estado["projetos"]:
        estado["projeto_ativo"] = LAB_SLUG

    return estado


def salvar_estado(estado):
    """Grava o estado no disco (escrita atômica via arquivo temporário)."""
    temporario = ARQUIVO_ESTADO + ".tmp"
    with open(temporario, "w", encoding="utf-8") as f:
        json.dump(estado, f, ensure_ascii=False, indent=2)
    os.replace(temporario, ARQUIVO_ESTADO)


# ── CONSULTAS ────────────────────────────────────────────────────────────────────

def projeto_ativo():
    """Retorna (slug, config) do projeto ativo."""
    estado = carregar_estado()
    slug = estado["projeto_ativo"]
    return slug, estado["projetos"][slug]


def caminho_db(config):
    """Resolve o caminho absoluto do banco de um projeto (a partir da raiz)."""
    db = config.get("db", LAB_DB)
    return db if os.path.isabs(db) else os.path.join(RAIZ_GMA, db)


def pasta_ao_lado_do_banco(nome_sub, criar=True):
    """
    Resolve uma pasta de trabalho do projeto (fila_forms, fila_material,
    contadores) ISOLADA por projeto — ela mora ao lado do banco daquele projeto.

    Como acha o projeto:
      - se GMA_DB estiver no ambiente (o maestro define no boot), usa a pasta DELE;
      - senão, cai no projeto ativo do painel_estado.json.

    Para o laboratório (banco = gma.db da raiz), a pasta resolvida é a da raiz —
    ou seja, as pastas globais de sempre (fila_forms/, fila_material/, contadores/).
    Assim NADA muda no laboratório; só os projetos novos ganham as suas próprias.
    """
    db = os.environ.get("GMA_DB", "").strip()
    if db:
        base = os.path.dirname(db if os.path.isabs(db) else os.path.join(RAIZ_GMA, db))
    else:
        _slug, cfg = projeto_ativo()
        base = os.path.dirname(caminho_db(cfg))
    caminho = os.path.join(base, nome_sub)
    if criar:
        try:
            os.makedirs(caminho, exist_ok=True)
        except OSError:
            pass
    return caminho


def caminho_recebidos(config):
    """
    Resolve a pasta-raiz de RECEBIDOS de um projeto — onde cai o material que
    NÃO vem por cartão físico (entregue por link/Drive/Dropbox). Cada Post de
    origem satélite ganha uma subpasta aqui (fluxo da Camada 1, a construir).

    Override do painel (campo 'recebidos') tem prioridade; vazio = padrão ao lado
    do banco do projeto (projetos/<slug>/recebidos; no laboratório, GMA/recebidos).
    """
    valor = (config.get("recebidos") or "").strip()
    if valor:
        return valor if os.path.isabs(valor) else os.path.join(RAIZ_GMA, valor)
    base = os.path.dirname(caminho_db(config))
    return os.path.join(base, "recebidos")


def checar_recebidos(caminho):
    """
    O "Testar" da caixa de recebidos: confere que a pasta existe, é gravável e
    que os arquivos estão DE FATO baixados (não são só atalhos de nuvem).

    A armadilha do Drive/Dropbox: um arquivo "só na nuvem" aparece na pasta mas o
    conteúdo ainda não desceu — copiar antes pegaria arquivo vazio. Heurística
    mecânica (sem IA): um placeholder reporta tamanho > 0 mas 0 blocos no disco.
    Usa a RÉGUA ÚNICA (ler_cartao) para olhar só o material e ignorar o lixo.

    Retorna (ok: bool, mensagem: str).
    """
    import ler_cartao  # régua única do que é "material"

    if not os.path.isdir(caminho):
        return False, (f"A pasta de recebidos ainda não existe: {caminho}. "
                       f"Aponte para a pasta sincronizada (Drive/Dropbox) ou crie-a.")
    try:
        teste = os.path.join(caminho, ".gma_teste_escrita")
        with open(teste, "w") as f:
            f.write("ok")
        os.remove(teste)
    except OSError as e:
        return False, f"A pasta existe mas não dá para gravar nela: {e}"

    so_na_nuvem = []
    baixados = 0
    for raiz, dirs, arqs in os.walk(caminho):
        dirs[:] = [d for d in dirs if not ler_cartao.eh_pasta_ignorada(d)]
        for nome in arqs:
            if ler_cartao.eh_nao_midia(nome):
                continue
            try:
                st = os.stat(os.path.join(raiz, nome))
            except OSError:
                continue
            # st_blocks == 0 com tamanho > 0 = placeholder de nuvem (não baixado).
            if st.st_size > 0 and getattr(st, "st_blocks", 1) == 0:
                so_na_nuvem.append(nome)
            else:
                baixados += 1
            if len(so_na_nuvem) + baixados >= 80:  # amostra suficiente
                break
        if len(so_na_nuvem) + baixados >= 80:
            break

    if so_na_nuvem:
        return False, (
            f"Pasta acessível, mas {len(so_na_nuvem)} arquivo(s) parecem estar SÓ NA "
            f"NUVEM (atalhos não baixados) — ex.: {so_na_nuvem[0]}. Ative 'disponível "
            f"offline' no Drive/Dropbox, senão a cópia pegaria arquivo vazio.")
    if baixados == 0:
        return True, f"Pasta acessível e gravável (vazia por enquanto)."
    return True, f"Pasta acessível, gravável e com {baixados} arquivo(s) baixado(s) localmente."


def aplicar_ao_ambiente(os_environ, forcar=False):
    """
    Exporta as variáveis do projeto ativo para o ambiente recebido.
    Chamado pelo maestro (inicializar_gma.py) ANTES de subir os processos e
    ANTES de carregar o .env — assim a config do projeto tem prioridade, e o
    .env preenche só o que faltar (Sheets, senha, etc.).

    Define GMA_DB (caminho do banco) e GMA_DESTINO (pasta dos materiais).
      - forcar=False (1º boot): só define se ainda não estiver no ambiente
        (respeita um GMA_DB exportado à mão para uso avançado).
      - forcar=True (reinício pelo painel): SOBRESCREVE — quando o operador
        troca de projeto no painel, a escolha dele sempre vence.
    Retorna (slug, config) do projeto aplicado.
    """
    slug, config = projeto_ativo()
    db = caminho_db(config)
    destino = config.get("destino") or DESTINO_PADRAO
    if forcar:
        os_environ["GMA_DB"] = db
        os_environ["GMA_DESTINO"] = destino
        if config.get("sheets_id"):
            os_environ["GMA_SHEETS_ID"] = config["sheets_id"]
        if config.get("tunel_link"):
            os_environ["GMA_LINK_FICHA"] = config["tunel_link"]
    else:
        os_environ.setdefault("GMA_DB", db)
        os_environ.setdefault("GMA_DESTINO", destino)
        if config.get("sheets_id"):
            os_environ.setdefault("GMA_SHEETS_ID", config["sheets_id"])
        if config.get("tunel_link"):
            os_environ.setdefault("GMA_LINK_FICHA", config["tunel_link"])
    return slug, config


# ── OPERAÇÕES DO PAINEL ───────────────────────────────────────────────────────────

def definir_ativo(slug):
    """Marca um projeto como ativo. Levanta ValueError se não existir."""
    estado = carregar_estado()
    if slug not in estado["projetos"]:
        raise ValueError(f"Projeto desconhecido: {slug}")
    estado["projeto_ativo"] = slug
    salvar_estado(estado)
    return slug


def definir_destino(slug, caminho):
    """Define a pasta de destino dos materiais de um projeto."""
    estado = carregar_estado()
    if slug not in estado["projetos"]:
        raise ValueError(f"Projeto desconhecido: {slug}")
    estado["projetos"][slug]["destino"] = caminho.strip()
    salvar_estado(estado)


def definir_recebidos(slug, caminho):
    """Define a pasta-raiz de recebidos (satélite) de um projeto. Vazio = padrão."""
    estado = carregar_estado()
    if slug not in estado["projetos"]:
        raise ValueError(f"Projeto desconhecido: {slug}")
    estado["projetos"][slug]["recebidos"] = caminho.strip()
    salvar_estado(estado)


def definir_banco(slug, db):
    """Define o caminho do banco de um projeto."""
    estado = carregar_estado()
    if slug not in estado["projetos"]:
        raise ValueError(f"Projeto desconhecido: {slug}")
    estado["projetos"][slug]["db"] = db.strip()
    salvar_estado(estado)


def _so_o_id_da_planilha(valor):
    """Extrai o ID puro de uma URL do Google Sheets (ou devolve o valor cru)."""
    import re
    valor = (valor or "").strip()
    m = re.search(r"/d/([a-zA-Z0-9_-]+)", valor)
    return m.group(1) if m else valor


def definir_sheets(slug, sheets_id):
    """Define o ID da planilha Google de um projeto (por projeto, não no .env).

    Aceita URL inteira colada do navegador ou o ID puro — guarda sempre o ID puro.

    GUARDA ANTI-COLISÃO: recusa um ID que já pertence a OUTRO projeto. Cada projeto
    tem a SUA planilha; reusar a de outro faria o exportador escrever por cima da
    entrega alheia (princípio de segurança: nunca destruir dado existente).
    """
    estado = carregar_estado()
    if slug not in estado["projetos"]:
        raise ValueError(f"Projeto desconhecido: {slug}")
    novo_id = _so_o_id_da_planilha(sheets_id)
    if novo_id:
        for outro_slug, outro_cfg in estado["projetos"].items():
            if outro_slug != slug and outro_cfg.get("sheets_id") == novo_id:
                nome_outro = outro_cfg.get("nome", outro_slug)
                raise ValueError(
                    f"essa planilha já é do projeto \"{nome_outro}\". "
                    f"Crie uma planilha NOVA para este projeto (sheets.new) para não "
                    f"sobrescrever a entrega do \"{nome_outro}\"."
                )
    estado["projetos"][slug]["sheets_id"] = novo_id
    salvar_estado(estado)


def definir_sheets_ativo(slug, ativo):
    """Ativa ou desativa a sincronização com o Google Sheets de um projeto."""
    estado = carregar_estado()
    if slug not in estado["projetos"]:
        raise ValueError(f"Projeto desconhecido: {slug}")
    estado["projetos"][slug]["sheets_ativo"] = bool(ativo)
    salvar_estado(estado)


def definir_tunel_link(slug, link):
    """Define o link override do túnel (vazio = detecta o ngrok automaticamente)."""
    estado = carregar_estado()
    if slug not in estado["projetos"]:
        raise ValueError(f"Projeto desconhecido: {slug}")
    estado["projetos"][slug]["tunel_link"] = link.strip()
    salvar_estado(estado)


def definir_tunel_ativo(slug, ativo):
    """Ativa ou desativa o acesso remoto (ficha via túnel) de um projeto."""
    estado = carregar_estado()
    if slug not in estado["projetos"]:
        raise ValueError(f"Projeto desconhecido: {slug}")
    estado["projetos"][slug]["tunel_ativo"] = bool(ativo)
    salvar_estado(estado)


def definir_host_porta(host, porta):
    """Define o host e porta do Flask (configuração global; aplica no próximo reinício)."""
    estado = carregar_estado()
    estado["host"] = host.strip()
    estado["porta"] = porta.strip()
    salvar_estado(estado)


def gerar_slug(nome):
    """Transforma 'Rock in Rio 2026' em 'rock_in_rio_2026' (sem acento/espaço)."""
    sem_acento = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode("ascii")
    limpo = re.sub(r"[^a-zA-Z0-9]+", "_", sem_acento).strip("_").lower()
    return limpo or "projeto"


def criar_projeto(nome):
    """
    Cria um projeto novo: a subpasta isolada em projetos/<slug>/ e registra no
    estado. NÃO inicializa o banco aqui (quem chama roda banco_dados.py com o
    GMA_DB apontado — ver flask_gma.py). Retorna o slug criado.
    Levanta ValueError se o nome for vazio ou o slug já existir.
    """
    nome = (nome or "").strip()
    if not nome:
        raise ValueError("O nome do projeto não pode ficar vazio.")
    slug = gerar_slug(nome)

    estado = carregar_estado()
    if slug in estado["projetos"]:
        raise ValueError(f"Já existe um projeto com esse nome ({slug}).")

    pasta = os.path.join(PASTA_PROJETOS, slug)
    os.makedirs(pasta, exist_ok=True)

    estado["projetos"][slug] = {
        "nome": nome,
        "db": os.path.join("projetos", slug, "gma.db"),
        "destino": DESTINO_PADRAO,
    }
    salvar_estado(estado)
    return slug
