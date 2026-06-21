#!/bin/sh
# Atalho clicável: encerra o GMA. Manda um sinal de encerramento ao saguão, que
# desce a sessão do projeto (Flask + processos) e se desliga de forma limpa.
# Se o saguão não estiver no ar, cai no encerrador direto (rede de segurança).
cd "/Users/serafa/GMA" || exit 1
if pgrep -f saguao.py >/dev/null 2>&1; then
    pkill -TERM -f saguao.py
    echo "Sinal de encerramento enviado ao saguão. Aguarde alguns segundos."
    sleep 4
else
    /usr/bin/python3 encerrar_gma.py
fi
