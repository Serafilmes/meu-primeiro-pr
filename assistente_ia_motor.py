"""
assistente_ia_motor.py — Camada 6 (IA): o MOTOR da Missão A Fatia 2.

Roda DENTRO da caixa isolada .venv_ia/ (onde mora a biblioteca oficial da
Anthropic), chamado como SUBPROCESSO por assistente_ia.py — exatamente como o
transcritor.py roda o Whisper. Assim o Python do ciclo crítico NUNCA importa a
biblioteca da Anthropic nem ganha dependência nova.

Contrato (mesma forma do transcritor.py):
  • Entrada: UMA linha JSON no stdin:
        {"system": str, "prompt": str, "modelo": str, "max_tokens": int}
  • Saída:   UMA linha JSON no stdout:
        {"ok": bool, "texto": str, "erro": str}

A chave da API vem do AMBIENTE (GMA_ANTHROPIC_KEY ou ANTHROPIC_API_KEY) — nunca
do código-fonte. Só TEXTO trafega (pergunta + transcrição + classificação); a
mídia NUNCA sobe.

Instalar a biblioteca na caixa isolada (passo único, quando ligar a chave):
    .venv_ia/bin/pip install anthropic
"""
import json
import os
import sys


def _chave():
    """Lê a chave da API do ambiente. Vazia = não configurada."""
    return (os.environ.get("GMA_ANTHROPIC_KEY")
            or os.environ.get("ANTHROPIC_API_KEY")
            or "").strip()


def responder(system, prompt, modelo, max_tokens):
    """Faz UMA chamada ao Claude e devolve só o texto da resposta."""
    import anthropic  # vive na .venv_ia; só é importado aqui dentro

    cliente = anthropic.Anthropic(api_key=_chave())
    resposta = cliente.messages.create(
        model=modelo,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    # response.content é uma lista de blocos; juntamos só os de texto.
    partes = [b.text for b in resposta.content if getattr(b, "type", None) == "text"]
    return "".join(partes).strip()


def main():
    try:
        entrada = json.loads(sys.stdin.read() or "{}")
    except Exception as e:
        print(json.dumps({"ok": False, "texto": "", "erro": f"entrada inválida: {e}"}))
        return 2

    if not _chave():
        print(json.dumps({"ok": False, "texto": "",
                          "erro": "sem chave da API (defina GMA_ANTHROPIC_KEY no .env)"}))
        return 1

    try:
        texto = responder(
            entrada.get("system", ""),
            entrada.get("prompt", ""),
            entrada.get("modelo") or "claude-haiku-4-5",
            int(entrada.get("max_tokens") or 1024),
        )
        print(json.dumps({"ok": True, "texto": texto, "erro": ""}, ensure_ascii=False))
        return 0
    except Exception as e:
        # Nunca estoura: o subprocesso sempre devolve JSON (o chamador degrada sozinho).
        print(json.dumps({"ok": False, "texto": "", "erro": str(e)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    sys.exit(main())
