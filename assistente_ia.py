"""
assistente_ia.py — Camada 6 (IA), MISSÃO A · Fatia 2: a busca conversacional.

Põe um LLM (Claude) POR CIMA da busca mecânica da Fatia 1
(`banco_dados.buscar_na_planilha`). O editor pergunta em LINGUAGEM NATURAL e a IA:
  1) TRADUZ a pergunta em termos de busca (lendo o "cardápio" do evento);
  2) roda a busca mecânica da Fatia 1 — que continua sendo a VERDADE;
  3) REDIGE uma resposta curta apontando os arquivos/takes que servem.

PRINCÍPIOS QUE NUNCA QUEBRA
  • Assíncrono e OPCIONAL, fora do ciclo crítico. Sem chave/internet, a busca
    volta a ser mecânica (Fatia 1) — nenhuma regressão.
  • A MÍDIA NUNCA SOBE: só TEXTO (transcrição, classificação, identificação) vai
    para a API. O vídeo/áudio nunca sai do HD.
  • A busca mecânica é a autoridade — a IA traduz e redige, NUNCA inventa arquivo.
    Tudo que aparece destacado na planilha vem de `buscar_na_planilha`.
  • Custo mínimo: modelo barato (Haiku) e só chama a API quando há pergunta.

TRÊS ESTADOS (ver `estado_ia`):
  • 'real'      — há chave (GMA_ANTHROPIC_KEY); chama o Claude na caixa .venv_ia.
  • 'simulado'  — GMA_IA_SIMULADA=1 e sem chave: LLM FALSO em processo, custo
                  ZERO — para ver o fluxo conversacional antes de criar o custo.
  • 'desligado' — sem chave e sem simulação: o Flask cai na busca mecânica.

O motor pesado (biblioteca da Anthropic) mora na CAIXA ISOLADA .venv_ia/, igual
ao Whisper, e é chamado como SUBPROCESSO (`assistente_ia_motor.py`). Este módulo
roda no Python do ciclo crítico e só importa a biblioteca padrão + banco_dados.
"""
import json
import os
import subprocess

import banco_dados as bd

RAIZ_GMA = os.path.dirname(os.path.abspath(__file__))
PYTHON_IA = os.path.join(RAIZ_GMA, ".venv_ia", "bin", "python")
MOTOR_SCRIPT = os.path.join(RAIZ_GMA, "assistente_ia_motor.py")
MODELO_PADRAO = "claude-haiku-4-5"   # rápido e barato; ideal para traduzir + redigir

# Palavras de enchimento que o "tradutor simulado" descarta para sobrar só o que
# interessa buscar. (No modo 'real', quem faz esse trabalho é o próprio Claude.)
_ENCHIMENTO = {
    "o", "a", "os", "as", "um", "uma", "uns", "umas", "de", "do", "da", "dos",
    "das", "no", "na", "nos", "nas", "em", "com", "sem", "que", "qual", "quais",
    "e", "ou", "para", "pra", "por", "preciso", "quero", "queria", "tem", "ter",
    "ache", "achar", "busca", "buscar", "procura", "procurar", "mostra", "mostrar",
    "me", "algum", "alguma", "algo", "take", "takes", "video", "videos", "audio",
    "audios", "arquivo", "arquivos", "material", "imagem", "cena", "trecho",
    "momento", "onde", "tenha", "tendo", "seja", "ser", "esta", "este", "essa",
    "esse", "aquele", "aquela", "isso", "aqui", "ali",
}

# ── Prompts do LLM (modo 'real') ─────────────────────────────────────────────
_SYSTEM_TRADUTOR = (
    "Você ajuda um editor de vídeo a buscar material num acervo de evento ao vivo. "
    "Recebe o cardápio de classificação do evento (palcos, marcas, pautas, nomes) "
    "e uma pergunta em linguagem natural. Sua tarefa é extrair APENAS as "
    "palavras-chave de busca — preferindo termos que existam no cardápio ou seus "
    "sinônimos diretos. Responda SÓ com as palavras, separadas por espaço, em "
    "minúsculas, sem pontuação, sem explicação. Se nada for buscável, responda vazio."
)
_SYSTEM_REDATOR = (
    "Você ajuda um editor de vídeo. Recebe a pergunta dele e a lista de materiais "
    "que o sistema encontrou (com profissional, número do cartão e trechos de "
    "transcrição). Escreva uma resposta curta (2 a 4 frases), em português, "
    "apontando quais materiais servem e por quê, citando o número do cartão e o "
    "arquivo quando houver. NÃO invente material que não esteja na lista. Se a "
    "lista estiver vazia, diga que não achou e sugira refinar a busca."
)


# ── Leitura de configuração ──────────────────────────────────────────────────

def _carregar_env():
    """Carrega o .env do projeto para o ambiente SEM sobrescrever o que já existe.

    Mesmo padrão do exportador_sheets: quando o módulo roda dentro do sistema o
    .env já foi aplicado e isto vira no-op; rodado avulso (testes), preenche o
    que faltar (GMA_ANTHROPIC_KEY, GMA_IA_SIMULADA, GMA_IA_MODELO).
    """
    caminho = os.path.join(RAIZ_GMA, ".env")
    if not os.path.exists(caminho):
        return
    try:
        with open(caminho, encoding="utf-8") as f:
            for linha in f:
                linha = linha.strip()
                if not linha or linha.startswith("#") or "=" not in linha:
                    continue
                chave, _, valor = linha.partition("=")
                chave, valor = chave.strip(), valor.strip().strip('"').strip("'")
                if chave and chave not in os.environ:
                    os.environ[chave] = valor
    except Exception:
        pass  # configuração é best-effort; falha aqui nunca quebra a busca


def chave_api():
    """A chave da Anthropic configurada (string vazia = não há)."""
    _carregar_env()
    return (os.environ.get("GMA_ANTHROPIC_KEY")
            or os.environ.get("ANTHROPIC_API_KEY")
            or "").strip()


def _modelo():
    return (os.environ.get("GMA_IA_MODELO") or MODELO_PADRAO).strip()


def _simulacao_ligada():
    return (os.environ.get("GMA_IA_SIMULADA") or "").strip().lower() in ("1", "true", "sim")


def estado_ia():
    """Devolve 'real', 'simulado' ou 'desligado' conforme a configuração."""
    _carregar_env()
    if chave_api():
        return "real"
    if _simulacao_ligada():
        return "simulado"
    return "desligado"


def disponivel():
    """True se a busca conversacional está ligada (real ou simulado)."""
    return estado_ia() != "desligado"


def _motor_instalado():
    """True se a caixa isolada e o motor existem (necessário só no modo 'real')."""
    return os.path.exists(PYTHON_IA) and os.path.exists(MOTOR_SCRIPT)


# ── Motor real: subprocesso na caixa isolada ─────────────────────────────────

def _motor_real(system, prompt, max_tokens=1024):
    """Chama o Claude pelo subprocesso na .venv_ia. Devolve (texto, erro).

    Nunca estoura: qualquer falha (caixa ausente, sem internet, chave inválida,
    timeout) volta como (None, mensagem) para o chamador degradar com elegância.
    """
    if not _motor_instalado():
        return None, "caixa .venv_ia ou motor ausente"
    try:
        proc = subprocess.run(
            [PYTHON_IA, MOTOR_SCRIPT],
            input=json.dumps({"system": system, "prompt": prompt,
                              "modelo": _modelo(), "max_tokens": max_tokens}),
            capture_output=True, text=True, timeout=60,
        )
        linha = next((l for l in reversed(proc.stdout.splitlines()) if l.strip()), "")
        if not linha:
            return None, f"motor sem saída (rc={proc.returncode})"
        dado = json.loads(linha)
        if dado.get("ok"):
            return dado.get("texto", ""), None
        return None, dado.get("erro", "erro desconhecido do motor")
    except subprocess.TimeoutExpired:
        return None, "motor demorou demais (timeout)"
    except Exception as e:
        return None, str(e)


# ── Cardápio do evento (contexto para o tradutor) ────────────────────────────

def montar_vocabulario(conn, limite_por_tipo=40):
    """Texto compacto com o vocabulário do evento: grupos, listas e profissionais.

    É o "cardápio" que o tradutor lê para mapear a pergunta em termos reais. Só
    TEXTO de classificação/identificação — nunca toca na mídia. Nunca estoura.
    """
    linhas = []
    try:
        grupos = bd.listar_grupos(conn, apenas_ativos=True)
        rotulos = [g["rotulo"] for g in grupos if g.get("rotulo")]
        if rotulos:
            linhas.append("Categorias: " + ", ".join(rotulos))
    except Exception:
        pass
    try:
        itens = bd.listar_itens_lista(conn, apenas_ativos=True)
        por_tipo = {}
        for it in itens:
            por_tipo.setdefault(it["tipo"], []).append(it["valor"])
        for tipo, valores in por_tipo.items():
            valores = [v for v in valores if v][:limite_por_tipo]
            if valores:
                linhas.append(f"{tipo}: " + ", ".join(valores))
    except Exception:
        pass
    try:
        profs = bd.listar_profissionais(conn)
        nomes = [p["nome"] for p in profs if p.get("nome")]
        if nomes:
            linhas.append("Profissionais: " + ", ".join(nomes))
    except Exception:
        pass
    return "\n".join(linhas)


# ── Tradutor: pergunta → termos de busca ─────────────────────────────────────

def _termos_simulados(pergunta):
    """LLM FALSO (modo simulado): tira o enchimento e devolve as palavras úteis.

    Determinístico e grátis — imita "entender a pergunta" descartando palavras
    de ligação. Não é tão esperto quanto o Claude, mas mostra o fluxo sem custo.
    """
    return [t for t in bd._extrair_termos(pergunta) if t not in _ENCHIMENTO]


def interpretar_pergunta(pergunta, vocabulario, motor=None):
    """Converte a pergunta em linguagem natural numa lista de termos de busca.

    motor=None → tradutor simulado (em processo). Senão chama o Claude e, se
    falhar, cai no extrator mecânico da própria pergunta (degradação suave).
    """
    if motor is None:
        return _termos_simulados(pergunta)
    prompt = (f"Cardápio do evento:\n{vocabulario or '(vazio)'}\n\n"
              f"Pergunta do editor:\n{pergunta}\n\n"
              f"Palavras-chave de busca:")
    texto, erro = motor(_SYSTEM_TRADUTOR, prompt)
    if erro or not texto:
        # Sem IA disponível: ainda extrai termos da pergunta crua (Fatia 1).
        return [t for t in bd._extrair_termos(pergunta) if t not in _ENCHIMENTO]
    return bd._extrair_termos(texto)


# ── Redator: resultados → resposta em linguagem natural ──────────────────────

def _resumir_resultados(resultados, limite=15):
    """Texto compacto dos resultados para alimentar o redator. Só texto."""
    linhas = []
    for res in resultados[:limite]:
        prof = res.get("prof_nome") or "(sem nome)"
        cartao = res.get("numero_cartao") or "—"
        pedaco = f"- {prof} · cartão {cartao}"
        campos = res.get("campos_bateram") or []
        if campos:
            pedaco += f" · bateu em: {', '.join(campos)}"
        for arq in (res.get("arquivos_transcritos") or [])[:3]:
            pedaco += f"\n    áudio {arq.get('nome_arquivo','')}: \"{arq.get('trecho','')}\""
        linhas.append(pedaco)
    return "\n".join(linhas) if linhas else "(nenhum material encontrado)"


def _resposta_simulada(pergunta, resultados):
    """Resposta FALSA (modo simulado): monta um texto de molde a partir dos achados."""
    n = len(resultados)
    if n == 0:
        return ("Não encontrei material com essas palavras. No modo simulado eu só acho "
                "o que está ESCRITO no acervo (transcrição, marca, palco, nome) — "
                "tente o nome de um show, uma marca ou um palco. "
                "Perguntas de entender ou listar (ex.: \"quem são os entrevistados\") só "
                "funcionam com a IA real ligada (chave da Anthropic). "
                "(modo simulado)")
    partes = [f"Encontrei {n} material(is) que pode(m) servir:"]
    for res in resultados[:3]:
        prof = res.get("prof_nome") or "(sem nome)"
        cartao = res.get("numero_cartao") or "—"
        trecho = ""
        arqs = res.get("arquivos_transcritos") or []
        if arqs:
            trecho = f' — áudio "{arqs[0].get("trecho","")}"'
        partes.append(f"• {prof} (cartão {cartao}){trecho}")
    if n > 3:
        partes.append(f"…e mais {n - 3}.")
    partes.append("(modo simulado — ligue a chave da Anthropic para respostas reais)")
    return "\n".join(partes)


def redigir_resposta(pergunta, resultados, motor=None):
    """Escreve a resposta em linguagem natural apontando os materiais que servem.

    motor=None → redator simulado. Senão chama o Claude; se falhar, cai no molde.
    """
    if motor is None:
        return _resposta_simulada(pergunta, resultados)
    prompt = (f"Pergunta do editor:\n{pergunta}\n\n"
              f"Materiais encontrados pelo sistema:\n{_resumir_resultados(resultados)}\n\n"
              f"Sua resposta:")
    texto, erro = motor(_SYSTEM_REDATOR, prompt)
    if erro or not texto:
        return _resposta_simulada(pergunta, resultados)
    return texto.strip()


# ── Orquestração ─────────────────────────────────────────────────────────────

def responder(conn, pergunta, motor=None):
    """Fluxo completo: traduz → busca (Fatia 1) → redige.

    Devolve um dict:
        {
          "estado":    'real' | 'simulado' | 'desligado',
          "pergunta":  str,
          "termos":    [str, ...],   # o que a IA decidiu buscar
          "resposta":  str | None,   # texto conversacional (None se desligado)
          "resultados": [ ... ],     # saída de buscar_na_planilha (a VERDADE)
        }

    Se estiver 'desligado', devolve resultados=[] e o Flask cai na busca mecânica.
    Nunca lança: em qualquer erro, devolve o que conseguiu sem quebrar a planilha.
    """
    estado = estado_ia()
    base = {"estado": estado, "pergunta": pergunta, "termos": [],
            "resposta": None, "resultados": []}

    pergunta = (pergunta or "").strip()
    if estado == "desligado" or not pergunta:
        return base

    # No modo 'real' o motor é o subprocesso; no 'simulado' fica None (LLM falso).
    if motor is None and estado == "real":
        motor = _motor_real

    try:
        vocab = montar_vocabulario(conn)
        termos = interpretar_pergunta(pergunta, vocab, motor)
        consulta = " ".join(termos)
        resultados = bd.buscar_na_planilha(conn, consulta) if consulta else []
        resposta = redigir_resposta(pergunta, resultados, motor)
        base.update(termos=termos, resposta=resposta, resultados=resultados)
    except Exception:
        # A busca é opcional: se algo falhar, devolve o estado parcial sem quebrar.
        pass
    return base
