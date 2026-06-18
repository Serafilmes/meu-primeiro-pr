#!/bin/sh
# Atalho clicável: liga o sistema GMA completo (o maestro sobe os 6 processos
# já no projeto ativo definido no Painel de Controle). Dê dois cliques no Finder.
cd "/Users/serafa/GMA" || exit 1
exec /usr/bin/python3 inicializar_gma.py
