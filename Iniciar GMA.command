#!/bin/sh
# Atalho clicável: abre o SAGUÃO do GMA (o térreo do sistema). O saguão sobe na
# porta 5055, abre no navegador e mostra a lista de projetos — você escolhe em
# qual entrar. Cada projeto roda na sua própria sessão (Flask na 5050). Trocar de
# projeto é só voltar ao saguão, sem desligar o sistema. Dê dois cliques no Finder.
cd "/Users/serafa/GMA" || exit 1
exec /usr/bin/python3 saguao.py
