#!/usr/bin/env bash
# ngrok_gma.sh
# Expõe o Flask do GMA (porta 5050) para a internet via ngrok.
#
# O Tally roda na nuvem e precisa de uma URL pública para enviar o webhook.
# Este script cria um túnel temporário com o ngrok e imprime a URL completa
# que o operador deve colar no painel do Tally.
#
# PRÉ-REQUISITO:
#   ngrok instalado e autenticado. Para instalar:
#     brew install ngrok/ngrok/ngrok
#   Para autenticar (gratuito, só precisa fazer uma vez):
#     ngrok config add-authtoken <SEU_TOKEN>
#   Token disponível em: https://dashboard.ngrok.com/get-started/your-authtoken
#
# USO (em um terminal separado, com o Flask já rodando):
#   ./ngrok_gma.sh
#
# IMPORTANTE:
#   - O Flask DEVE estar rodando antes de chamar este script.
#     Se não estiver, o ngrok sobe mas o túnel fica vazio.
#   - A URL muda a cada vez que o ngrok é reiniciado (plano gratuito).
#     Copie a URL nova e atualize no painel do Tally cada vez que reiniciar.
#   - Encerre o ngrok com Ctrl+C neste terminal quando terminar o evento.
#   - Este túnel conecta a internet à porta 5050 da sua máquina.
#     Nunca deixe o ngrok rodando sem necessidade.

set -e   # interrompe o script se qualquer comando falhar

# ── Verifica se o ngrok está instalado ────────────────────────────────────────
if ! command -v ngrok &>/dev/null; then
    echo ""
    echo "[NGROK] ERRO: ngrok nao encontrado no PATH."
    echo "[NGROK] Para instalar:"
    echo "[NGROK]   brew install ngrok/ngrok/ngrok"
    echo "[NGROK] Para autenticar (gratuito):"
    echo "[NGROK]   ngrok config add-authtoken <SEU_TOKEN>"
    echo "[NGROK] Token disponivel em: https://dashboard.ngrok.com/get-started/your-authtoken"
    echo ""
    exit 1
fi

# ── Verifica se o Flask está respondendo ──────────────────────────────────────
echo ""
echo "[NGROK] Verificando se o Flask GMA esta rodando na porta 5050..."
if ! curl -s --max-time 2 http://127.0.0.1:5050/status > /dev/null 2>&1; then
    echo "[NGROK] AVISO: Flask nao respondeu em http://127.0.0.1:5050"
    echo "[NGROK] Inicie o GMA primeiro:"
    echo "[NGROK]   python3 /Users/serafa/GMA/inicializar_gma.py"
    echo "[NGROK] Em seguida rode este script em outro terminal."
    echo ""
    exit 1
fi
echo "[NGROK] Flask respondendo. Iniciando tunel..."
echo ""

# ── Inicia o ngrok em background ──────────────────────────────────────────────
# A API interna do ngrok fica disponível em http://127.0.0.1:4040
ngrok http 5050 --log=stderr > /dev/null 2>&1 &
NGROK_PID=$!

# Aguarda o ngrok subir e registrar o túnel (geralmente leva 1-2 segundos)
sleep 3

# ── Obtém a URL pública gerada pelo ngrok ─────────────────────────────────────
# A API local do ngrok retorna um JSON com os túneis ativos.
# Usamos python3 (já disponível no sistema) para parsear o JSON sem dependências.
URL_PUBLICA=$(python3 -c "
import urllib.request
import json
import sys

try:
    resposta = urllib.request.urlopen('http://127.0.0.1:4040/api/tunnels', timeout=5)
    dados = json.loads(resposta.read().decode('utf-8'))
    tuneis = dados.get('tunnels', [])
    # Prefere o túnel HTTPS (mais seguro para receber webhooks)
    for tunel in tuneis:
        if tunel.get('proto') == 'https':
            print(tunel['public_url'])
            sys.exit(0)
    # Se só tiver HTTP, usa ele mesmo
    for tunel in tuneis:
        if tunel.get('proto') == 'http':
            print(tunel['public_url'])
            sys.exit(0)
    print('ERRO: nenhum tunel encontrado')
    sys.exit(1)
except Exception as e:
    print(f'ERRO: {e}')
    sys.exit(1)
" 2>&1)

# Verifica se conseguiu obter a URL
if echo "$URL_PUBLICA" | grep -q "ERRO"; then
    echo "[NGROK] $URL_PUBLICA"
    echo "[NGROK] O ngrok pode ainda estar inicializando. Aguarde 5 segundos e tente:"
    echo "[NGROK]   curl http://127.0.0.1:4040/api/tunnels"
    echo ""
    kill $NGROK_PID 2>/dev/null || true
    exit 1
fi

# ── Imprime as instruções para o operador ────────────────────────────────────
echo "============================================================"
echo "  NGROK ATIVO — Tunel criado com sucesso"
echo "============================================================"
echo ""
echo "  URL DO WEBHOOK (cole no painel do Tally):"
echo ""
echo "  >>> ${URL_PUBLICA}/forms/tally <<<"
echo ""
echo "  Interface do ngrok (monitoramento):"
echo "  >>> http://127.0.0.1:4040 <<<"
echo ""
echo "  LEMBRETE: esta URL muda cada vez que o ngrok e reiniciado."
echo "  Atualize no painel do Tally se reiniciar."
echo ""
echo "============================================================"
echo "  Pressione Ctrl+C neste terminal para encerrar o tunel."
echo "============================================================"
echo ""

# Mantém o script vivo (e o ngrok rodando em background)
# Quando o operador apertar Ctrl+C, encerra o ngrok também
trap "echo ''; echo '[NGROK] Encerrando tunel...'; kill $NGROK_PID 2>/dev/null; echo '[NGROK] Tunel encerrado.'; echo ''" INT TERM
wait $NGROK_PID
