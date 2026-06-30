#!/usr/bin/env bash
# cloudflared_gma.sh
# Expõe o Flask do GMA (porta 5050) para a internet via Cloudflare Tunnel.
#
# Por que Cloudflare em vez do ngrok?
#   - O ngrok gratuito mostra uma tela de aviso ("You are about to visit…")
#     antes de chegar à ficha — o que atrapalha o acesso por QR Code no set.
#   - O Cloudflare Quick Tunnel NÃO tem essa tela de aviso: o QR Code leva
#     direto à ficha, sem clique extra.
#   - O ngrok gratuito permite apenas 1 túnel por vez. O Cloudflare permite
#     vários túneis simultâneos de graça — útil quando o projeto crescer para
#     multi-máquina.
#
# PRÉ-REQUISITO:
#   cloudflared instalado. Para instalar (uma única vez):
#     brew install cloudflared
#   NÃO é necessário criar conta nem fazer login — o modo rápido (Quick Tunnel)
#   funciona direto, sem autenticação.
#
# USO (em um terminal separado, com o Flask já rodando):
#   ./cloudflared_gma.sh
#
# IMPORTANTE:
#   - O Flask DEVE estar rodando antes de chamar este script.
#     Se não estiver, o túnel sobe mas não chega a nada.
#   - A URL muda a cada vez que o cloudflared é reiniciado (modo rápido).
#     Copie a URL nova e atualize no painel do Tally cada vez que reiniciar.
#   - Encerre o túnel com Ctrl+C neste terminal quando terminar o evento.
#   - Este túnel conecta a internet à porta 5050 da sua máquina.
#     Nunca deixe o cloudflared rodando sem necessidade.

set -e   # interrompe o script se qualquer comando falhar

# Arquivo temporário onde o cloudflared escreve seu log (incluindo a URL pública).
# Diferente do ngrok, o cloudflared não tem uma API local — a URL aparece no log.
LOG_TEMP="/tmp/cloudflared_gma.log"

# Arquivo de estado: quando o túnel está vivo, contém a URL pública (sem barra final).
# O Flask lê este arquivo para montar o QR Code automaticamente.
# Arquivo presente = túnel vivo; arquivo ausente = sem túnel.
URL_STATE="/tmp/cloudflared_gma_url.txt"

# ── Verifica se o cloudflared está instalado ──────────────────────────────────
if ! command -v cloudflared &>/dev/null; then
    echo ""
    echo "[CLOUDFLARE] ERRO: cloudflared nao encontrado no PATH."
    echo "[CLOUDFLARE] Para instalar (uma unica vez, nao precisa de conta):"
    echo "[CLOUDFLARE]   brew install cloudflared"
    echo ""
    exit 1
fi

# ── Verifica se o Flask está respondendo ──────────────────────────────────────
echo ""
echo "[CLOUDFLARE] Verificando se o Flask GMA esta rodando na porta 5050..."
if ! curl -s --max-time 2 http://127.0.0.1:5050/status > /dev/null 2>&1; then
    echo "[CLOUDFLARE] AVISO: Flask nao respondeu em http://127.0.0.1:5050"
    echo "[CLOUDFLARE] Inicie o GMA primeiro (atalho 'Iniciar GMA' ou: python3 /Users/serafa/GMA/saguao.py)"
    echo "[CLOUDFLARE] e entre num projeto pelo saguao. Em seguida rode este script em outro terminal."
    echo ""
    exit 1
fi
echo "[CLOUDFLARE] Flask respondendo. Iniciando tunel Cloudflare..."
echo ""

# Limpa o log anterior e o arquivo de estado para não ler uma URL velha por engano
rm -f "$LOG_TEMP"
rm -f "$URL_STATE"

# ── Inicia o cloudflared em background, gravando o log no arquivo temporário ──
# O cloudflared imprime a URL pública no stderr — redirecionamos para o log.
cloudflared tunnel --url http://localhost:5050 > "$LOG_TEMP" 2>&1 &
CF_PID=$!

# ── Faz polling do log por até ~15 segundos procurando a URL pública ──────────
# A URL tem o formato: https://<aleatorio>.trycloudflare.com
# Ela aparece no log alguns segundos após o cloudflared subir.
URL_PUBLICA=""
TENTATIVAS=0
MAX_TENTATIVAS=15   # 15 tentativas × 1 segundo = 15 segundos de espera máxima

echo "[CLOUDFLARE] Aguardando URL publica (pode levar alguns segundos)..."

while [ $TENTATIVAS -lt $MAX_TENTATIVAS ]; do
    # Verifica se o processo ainda está vivo (falha rápida)
    if ! kill -0 "$CF_PID" 2>/dev/null; then
        echo ""
        echo "[CLOUDFLARE] ERRO: o cloudflared encerrou antes de criar o tunel."
        echo "[CLOUDFLARE] Veja o log para detalhes: $LOG_TEMP"
        echo ""
        exit 1
    fi

    # Procura no log uma linha com a URL do Cloudflare Quick Tunnel
    URL_PUBLICA=$(grep -o 'https://[a-zA-Z0-9-]*\.trycloudflare\.com' "$LOG_TEMP" 2>/dev/null | head -1 || true)

    if [ -n "$URL_PUBLICA" ]; then
        break   # encontrou a URL — sai do loop
    fi

    sleep 1
    TENTATIVAS=$((TENTATIVAS + 1))
done

# ── Verifica se a URL foi encontrada no prazo ─────────────────────────────────
if [ -z "$URL_PUBLICA" ]; then
    echo ""
    echo "[CLOUDFLARE] ERRO: URL publica nao apareceu no log em ${MAX_TENTATIVAS} segundos."
    echo "[CLOUDFLARE] Verifique a conexao com a internet e tente novamente."
    echo "[CLOUDFLARE] Log completo disponivel em: $LOG_TEMP"
    echo ""
    kill "$CF_PID" 2>/dev/null || true
    exit 1
fi

# ── Grava a URL no arquivo de estado (Flask lê para montar o QR automaticamente) ─
# A URL é escrita sem barra final; arquivo presente = túnel vivo.
printf '%s' "${URL_PUBLICA}" > "$URL_STATE"

# ── Imprime as instruções para o operador ─────────────────────────────────────
echo ""
echo "============================================================"
echo "  CLOUDFLARE TUNNEL ATIVO — Tunel criado com sucesso"
echo "============================================================"
echo ""
echo "  URL PUBLICA (acesso direto, sem tela de aviso):"
echo ""
echo "  >>> ${URL_PUBLICA} <<<"
echo ""
echo "  URL DO WEBHOOK (cole no painel do Tally):"
echo ""
echo "  >>> ${URL_PUBLICA}/forms/tally <<<"
echo ""
echo "  LEMBRETE: esta URL muda cada vez que o cloudflared e reiniciado."
echo "  Atualize no painel do Tally se reiniciar."
echo ""
echo "  Log do cloudflared (para depuracao): $LOG_TEMP"
echo ""
echo "============================================================"
echo "  Pressione Ctrl+C neste terminal para encerrar o tunel."
echo "============================================================"
echo ""

# ── Mantém o script vivo enquanto o túnel estiver ativo ───────────────────────
# Quando o operador apertar Ctrl+C, encerra o cloudflared também.
trap "echo ''; echo '[CLOUDFLARE] Encerrando tunel...'; kill $CF_PID 2>/dev/null; rm -f \"$URL_STATE\"; echo '[CLOUDFLARE] Tunel encerrado.'; echo ''" INT TERM
wait $CF_PID
