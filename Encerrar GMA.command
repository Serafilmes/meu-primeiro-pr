#!/bin/sh
# Atalho clicável: encerra o sistema GMA. Tenta primeiro pelo sinal do maestro
# (encerramento limpo); se o maestro não estiver no ar, usa o encerrador direto.
cd "/Users/serafa/GMA" || exit 1
if pgrep -f inicializar_gma.py >/dev/null 2>&1; then
    : > .gma_encerrar
    echo "Sinal de encerramento enviado ao maestro. Aguarde alguns segundos."
    sleep 4
else
    /usr/bin/python3 encerrar_gma.py
fi
