# Mapa Vivo do GMA
## Gerenciamento de Mídia Audiovisual — onde estamos, o que fizemos, pra onde vamos

> Este é o **mapa do processo**. Sempre que bater a sensação de "estou perdido,
> o que já fizemos?", abra este arquivo: ele mostra o quadro inteiro de uma vez.
> Para os detalhes técnicos, ver `arquitetura_GMA.md`; para o histórico completo, `historico_GMA.md`.
>
> Princípio central de tudo: **UMA fonte de verdade → TRÊS vistas.**
> O sistema guarda o dado em um lugar só; as telas são jeitos diferentes de LER
> esse mesmo dado. Nada diverge.
>
> Última atualização: 2026-06-30 (sessão 63 — BUILD/CAMADA 5: TÚNEL CLOUDFLARE como alternativa ao ngrok. O idealizador mostrou (print do celular) que o QR Code da ficha cai numa TELA DE AVISO do ngrok grátis ("You are about to visit… Visit Site") ANTES de chegar na ficha — atrito no set. Diagnóstico: essa tela é trava do plano grátis do ngrok e NÃO dá pra pular num acesso por QR (o navegador do celular faz a 1ª requisição sem o cabeçalho ngrok-skip-browser-warning). Decisão: trocar o cano por CLOUDFLARE QUICK TUNNEL, que NÃO tem essa tela e ainda NÃO trava em 1 túnel (o ngrok grátis trava — bloqueia multi-máquina). Ele perguntou sobre limites do Cloudflare p/ multi-máquina: respondi que o grátis NÃO limita túneis simultâneos nem cobra banda (e o GMA só trafega formulário/texto — mídia nunca passa pela rede), então não bloqueia o caminho que o ngrok grátis bloqueia. Decidimos MAIN (mudança aditiva; ele roda o sistema ao vivo do disco) e fomos DIRETO ao automático. CONSTRUÍDO (via plataforma-gma): (1) cloudflared_gma.sh NOVO, espelho do ngrok_gma.sh (mesmo tom p/ iniciante) — verifica cloudflared no PATH (brew install cloudflared, sem login no modo rápido) e o Flask na 5050; sobe `cloudflared tunnel --url http://localhost:5050` em background gravando o log em /tmp/cloudflared_gma.log; faz POLLING do log (até 15s) procurando https://*.trycloudflare.com (o Cloudflare NÃO tem API local como o ngrok no 4040 — a URL só sai no log); imprime a URL + o webhook do Tally; trap mata o cloudflared no Ctrl+C; ngrok INTACTO como reserva. (2) AUTO-DETECÇÃO por ARQUIVO DE ESTADO — o script grava a URL pura em /tmp/cloudflared_gma_url.txt ao subir e APAGA no Ctrl+C (presente=túnel vivo; ausente=sem túnel, evita URL velha); _descobrir_link_ficha() (flask_gma.py) ganhou nova prioridade: override GMA_LINK_FICHA > CLOUDFLARE (lê o arquivo, valida https://, monta <url>/ficha) > ngrok via 4040 (agora explicitamente fallback), mesmo cache de ~20s, mesmo try/except defensivo → o QR TROCA SOZINHO, o operador não copia URL nenhuma. (3) Cosmético: o aviso "sem túnel" do painel do QR deixou de citar só "ngrok", agora menciona ./cloudflared_gma.sh. VERIFICADO: ast.parse do flask OK, bash -n do .sh OK, diff do flask revisado à mão. NÃO testado ao vivo — falta o idealizador rodar `brew install cloudflared` (o programa AINDA NÃO está instalado) e fazer o teste real no celular (QR → ficha, sem tela cinza); mudou flask_gma.py → exige Voltar ao saguão + Entrar. DIREÇÃO COMBINADA: validado no set, o NGROK SAI (remover ngrok_gma.sh, o iniciar_ngrok() do maestro e a leitura do 4040, deixando o Cloudflare como cano único). Possíveis fatias depois: o maestro subir o cloudflared sozinho (hoje é à mão) e o MODO NOMEADO (subdomínio fixo por máquina — resolve a URL que muda). Commitado no main (29dda8c, 3277759 + commit final com cosmético+mapas). 2ª PARTE DA SESSÃO — NGROK REMOVIDO, CLOUDFLARE = CANO ÚNICO: no teste o QR continuava no ngrok (faltou Voltar+Entrar p/ o Flask reler + o cloudflared precisa estar rodando). O idealizador decidiu "somente Cloudflare, para não gerar conflito". Em vez de rodar script à mão, o MAESTRO passa a subir o cloudflared SOZINHO (igual o ngrok subia). Delegado ao plataforma-gma: inicializar_gma.py — iniciar_ngrok() virou iniciar_cloudflared() (mesmos 4 portões; sobe cloudflared tunnel --url http://localhost:porta, polling do log, grava /tmp/cloudflared_gma_url.txt, RETRY pro erro transitório "invalid UUID length: 0", best-effort offline-first); _tunel_url() lê o arquivo, _tunel_no_ar() usa pgrep; subir_todos usa processos["Cloudflare"], descer_todos encerra E apaga o arquivo de estado. flask_gma.py — _descobrir_link_ficha(), botão Testar e cockpit de conexões deixam de consultar o ngrok/4040, leem só o arquivo do Cloudflare. ngrok_gma.sh APAGADO (git rm); cloudflared_gma.sh ganhou guarda anti-duplicado (pgrep). VERIFICADO AO VIVO no maestro: chamei iniciar_cloudflared() num processo à parte → subiu o túnel real, achou a URL, gravou o arquivo, logou "Tunel ATIVO"; descer_todos encerrou e limpou. (O acesso do celular não dá p/ testar daqui — o ambiente filtra a saída p/ subdomínios novos do trycloudflare; o celular na internet real alcança.) Commits c51067a (código) + mapas. FALTA o teste no set: o idealizador faz Encerrar+Iniciar (mexeu no maestro), confere no log "Tunel ATIVO: https://…trycloudflare.com" e escaneia o QR no celular (direto na ficha, sem tela cinza). Fatia futura: MODO NOMEADO do Cloudflare (subdomínio fixo por máquina, resolve a URL que muda — precisa conta+domínio). — anterior s62 — SUPORTE/FIX. O idealizador esqueceu a senha de acesso. Descobrimos DUAS portas distintas na entrada: (1) o popup Basic Auth do navegador (GMA_SENHA=gma123, do .env) e (2) o login de operador (tela escura do 6floor, operadores.json com hash pbkdf2). Ele tentava 1234 no popup, mas 1234 é a senha do OPERADOR — redefinida nesta sessão via operadores.trocar_senha('serafa','1234') e confirmada por curl no servidor vivo (sem Basic Auth → 401; com -u gma:gma123 + nome=Serafa&senha=1234 → 302 /). A pedido dele ("tira o pop-up"), ESVAZIEI GMA_SENHA no .env (seguro: GMA_HOST=127.0.0.1, só local; comentário no .env lembrando de repor se expor na internet) — efetiva no próximo Voltar+Entrar; o login de operador continua. FIX commitado (3bb6911): o aviso de órfão da aba Match mostrava "2 órfãos: CALIFA, CALIFA" mesmo os dois Posts já estando 'concluido' no banco — identificar_orfaos() lia os JSONs crus da fila, e o material RECEBIDO pula o Matcher (que avançaria o JSON), prendendo o arquivo em 'aguardando_material'; a s47 corrigiu isso no PAINEL mas não no AVISO. Agora identificar_orfaos() cruza com o banco (fonte de verdade) nos dois lados (esconde Posts resolvidos e cartões concluídos); verificado contra o sp2b real → 0 órfãos. IDEIA FUTURA registrada (memória keygen-licenciamento-venda): KEYGEN/LICENCIAMENTO por tempo — keygen + tabela de senhas com limite de data p/ vender pacotes por tempo limitado (virada protótipo→produto, encaixa na C5; seria uma 3ª camada de acesso = licença do PRODUTO, não identidade de quem opera); "pensamos nisto depois", NÃO construir ainda. Config local (operadores.json, .env) fora do git; só o fix do flask_gma.py foi commitado. — anterior s61 — CAMADA 7: FECHADO O PADRÃO FULL-DARK. O idealizador pediu para "fechar o padrão para todas as telas". A única tela operacional ainda clara era a MATCH/OPERAÇÃO (rota /, aba "Match") — deixada por último porque é a mais densa E porque, diferente das outras 7, NÃO usava o molde _pagina: montava o HTML do zero com <head>/<style>/<header> próprios ("GMA — Painel de Check-in", azul-marinho #1a1a2e) e nem recebia as variáveis da marca. Perguntei o que "fechar o padrão" significava (levar a última ao escuro × tornar o escuro o tema-base/refactor) → ele escolheu INCREMENTAL; e sobre o cabeçalho (manter o próprio × trocar pelo da marca) → ele escolheu TROCAR PELO DA MARCA. DECISÃO-CHAVE: em vez de só repintar, MIGREI a painel() para o molde _pagina (o mesmo das outras 7) — assim ela ganha de graça o cabeçalho da marca (∞ 6floor + título "Match" + abas, ativa em teal), as variáveis --6f-…, a Space Grotesk e o escopo body.pag-operacao; o <head>/<header>/<style> legados saíram, o corpo virou a string 'corpo', o JS e o CSS próprio foram pro head_extra. O CSS exclusivo virou css_operacao escopado em .pag-operacao, já em var(--6f-…); as 4 CATEGORIAS DE CARD (eram amarelo/verde/azul/rosa) viraram acento semântico no mundo "um acento só": Matches=teal (sucesso), Confirmação=âmbar (precisa de você), as 2 filas de espera=neutro; botão MATCH e Ativar Porteiro=teal, Desativar=erro; banners/empate/prioridade convertidos. COM ISSO O PADRÃO FULL-DARK ESTÁ FECHADO: as 8 telas operacionais seguem o mesmo molde + a mesma paleta. VERIFICADO: ast.parse OK; renderização real via test_request_context (HTML 23,7 KB com cabeçalho da marca, body.pag-operacao, título "Match", abas; sumiram o header "Painel de Check-in", o #1a1a2e do header, o roxo #8e44ad e qualquer {{ literal; só resta o #fff proposital do botão de erro); o #f0f2f5/#1a1a2e que ainda aparecem vêm do CSS compartilhado do _pagina (igual ao Kanban já escuro), sobrescritos pela classe. Prévia visual mostrada. NÃO testado ao vivo (precisa Voltar ao saguão + Entrar). Falta da pele C7 (não são telas): ícone do app real, grid, lockup em contornos. Falta commitar. — anterior s60 — CAMADA 2: VELOCIDADE DE TRANSFERÊNCIA AO VIVO NA ABA MURAL (estilo ShotPutPro). O idealizador perguntou se haveria problema em mostrar a velocidade de transferência em tempo real (algo que o ShotPutPro faz). Resposta: ZERO problema de segurança — medir é só observar bytes que já estão sendo lidos para o MD5, nunca toca/move/apaga mídia (princípio nº2 intacto). É a Peça 3 da remodelação da s59 ("teste de transferência na aba Mural"). Ele escolheu OS DOIS sabores (ao vivo + histórico); fizemos a FATIA 1 (ao vivo). CONSTRUÍDO: (1) MEDIDOR no copiador.py — calcular_md5 ganhou gancho opcional ao_ler(n_bytes) por bloco de 1 MB (chamadas antigas = custo zero); nova classe MedidorProgresso acumula bytes lidos e publica um BILHETE .gma_copia_status.json a cada ~0,5s (job, arquivo X de Y, nome, %, MB/s instantânea, tempo restante), com troca atômica (.tmp + os.replace, igual ao bilhete do Sheets da s46); ao fim vira "ocioso"; TUDO best-effort (erro de medir/publicar é engolido, NUNCA derruba a cópia — princípio nº2). (2) ROTA /kanban/copia-status no Flask — lê o bilhete e devolve JSON, tolerante a tudo (ausente/vazio/estado≠copiando/bilhete velho>8s → ocioso); só na base. (3) FAIXA NO MURAL (/kanban) — faixa no topo do quadro (full-dark body.pag-kanban, paleta 6floor: borda teal, barra trilho+preenchimento teal, MB/s em destaque) que aparece só enquanto copia e some quando ocioso; usa o mesmo poll do quadro (2º setInterval 1s, sem SSE). Aparece na cópia de CARTÃO FÍSICO e de MATERIAL RECEBIDO (as duas passam por copiador.copiar(), e o medidor mora dentro dela). VERIFICADO: ast.parse OK nos 2 arquivos; cópia real de teste (3 arquivos sintéticos de 80 MB em /tmp, nada de mídia real) — bilhete atualizou ao vivo (33%→66%, ~600 MB/s no SSD), virou ocioso, cópia rodou normal (.sppo gerado, sem erro), o medidor não atrapalhou; rota certa nos 4 casos; prévia visual da faixa renderizada; andaime de teste removido (/tmp limpo). NÃO testado ao vivo no sistema rodando (precisa Voltar ao saguão + Entrar) — a faixa aparece na próxima cópia real. Falta commitar. PRÓXIMO: Fatia 2 (histórico por cartão — duração + velocidade média no banco, Camada 3); refino possível (instrumentar a cópia shutil em si — hoje a barra não anda durante essa fração); ou Peça 2 da s59 (velocidade de DISCO na aba Sistema). REGRESSÃO no teste ao vivo (corrigida): a migração da Match APAGOU sem querer o </style> de fechamento do _pagina (molde compartilhado) → Entrega e Programação (head_extra só com <script>) ficaram BRANCAS (estilo engolia a página) e Cadastros ficou SEM CABEÇALHO (um <style> no corpo fechava tarde, comendo o header); demais telas ilesas (têm <style> no head_extra que fechava por sorte). Lição: o smoke test não pega CSS não-fechado (o header estava no HTML, só era engolido no navegador) → conferir balanceamento <style>/</style>. Fix validado nas 7 telas. Junto: QR do Mural com FUNDO BRANCO embutido (segno gera transparente → sumia no escuro; agora light=#fff/dark=#000 + quiet zone, escaneável) e nome do Cadastros com cor clara explícita. — anterior s59 — CAMADA 5: ABA SISTEMA ENXUGADA. O idealizador contou que tinha remodelado a aba Sistema numa OUTRA conversa (que "só iniciou") e que a mudança SE DESFEZ. Investiguei a fundo: a remodelação NÃO existe em lugar nenhum do Git — árvore limpa, sem stash, sem dangling blob, reflog linear (nenhum reset/checkout que apagasse trabalho), os 2 dangling commits são antigos (s31/s40, nada a ver). Conclusão: nunca foi salva no disco nem commitada → nada a recuperar; refizemos aqui, versionado. Ele descreveu a remodelação em 3 PEÇAS; fizemos a PEÇA 1 (a única segura/contida): REMOVIDA a caixa "Projetos" do Painel (listava projetos + criar novo) — redundante, porque trocar/criar/entrar em projeto já é só no SAGUÃO; a caixa "Projeto ativo" (onde você está agora) FICOU. Conferido antes: o saguão cria E inicializa o banco do projeto sozinho (criar_projeto_novo) → não perde função. Limpeza acoplada: removidos a rota órfã /painel/novo e o ajudante _inicializar_banco_projeto; sobrou só CSS .proj-lista sem uso (deixado de propósito, pra não mexer no PAINEL_CSS escuro da s58). Verificado: ast.parse OK, zero referência órfã, o Painel agora monta 6 caixas em vez de 7. NÃO testado ao vivo (precisa Voltar ao saguão + Entrar). PENDENTE (Peças 2-3, recursos NOVOS p/ desenhar): teste de velocidade de DISCO na aba Sistema e de TRANSFERÊNCIA na aba Mural — disco sob demanda ou observado? transferência ao vivo ou histórico? (leem disco → cuidado com o princípio nº2, nunca tocar na mídia). Commitado no main. — anterior s58 — CAMADA 7: TODAS AS TELAS OPERACIONAIS FULL-DARK (Entrega·Sistema·Posts·Cadastros·Programação·Molde; + Kanban da s55). O idealizador seguiu a C7 e pediu para EU SEGUIR (avançar o full-dark tela a tela, commitar tudo junto no fim). Fiz TODAS as telas operacionais restantes, uma de cada vez e verificando cada uma — o mundo escuro 6floor agora cobre o sistema operacional inteiro; só a página Match/Operação (rota /, mistura o monitor da 2ª máquina) segue clara de propósito. CADASTROS+PROGRAMAÇÃO+MOLDE: builders inline (sem constante CSS), ≈121 hex cravados trocados por var(--6f-…); replace_all usado SÓ após grep confirmar que a string repetida vivia apenas nas telas-alvo (a Match compartilha caixas idênticas e NÃO está no escuro — converter à toa furaria o fundo claro dela). FICHA (aba "Posts", a 3ª/maior): decisão de produto dele (corrigiu a 1ª resposta numa pergunta) = ESCURO NAS DUAS CARAS (operador na base E câmera remota no celular), então o escopo body.pag-ficha cobre as duas; reescrevi o CSS_FICHA inteiro em var(--6f-…) + os muitos hex inline dos builders (chips/tags/toggles teal, grupos de Posts, descanso, banner de programação ativa, ficha enviada); o COR_STATUS_FICHA (cinza/azul/verde) ficou semântico, igual ao Kanban. PLANILHA (aba "Entrega"): escopada por body.pag-planilha (mesmo padrão do Kanban da s55); bloco de overrides cobre a tabela; como a barra de busca, a caixa do Assistente IA e os helpers de célula usam estilo INLINE, troquei os hex cravados por var(--6f-…) um a um (caixa IA teal-trilho, botões teal, destaque da linha que bate na busca, painel de transcrição, link "ver"/botão "Transcrever"). PAINEL (aba "Sistema", /painel + /historico sob body.pag-painel): o corpo é estilizado pelo PAINEL_CSS (injetado via head_extra, EXCLUSIVO de _pagina_painel — grep confirmou), então reescrevi o PAINEL_CSS inteiro em var(--6f-…): seções, projeto ativo (nome teal, item ativo teal-trilho), cards de conexão com as bolinhas de status (ok=teal, aviso=âmbar, off=texto-3, erro=vermelho), botões (Testar elevado/teal-claro, Entrar teal, Encerrar erro), avisos, ajuda do Sheets, código copiável; a /historico tinha estilo inline próprio (bordas/textos cinza), convertido pra var(--6f-borda)/texto-2/texto-3. Nenhum hex novo cravado em nenhuma das duas; sub-tela /molde fica p/ depois. Isolamento conferido por grep: o que converti é usado só nessas telas → Kanban/Ficha/Cadastros/Programação seguem como estavam. Verificado por screenshots estáticos isolados (http.server na 5066 + entrada temporária no launch.json, depois revertida): Planilha (caixa IA teal-trilho, botões teal, linha de match destacada) e Painel (aviso ok, projeto ativo teal, cards c/ bolinhas, hierarquia de botões, Encerrar vermelho, Histórico legível), contraste bom. NÃO testado ao vivo (precisa Voltar ao saguão + Entrar). ACHADO E QUITADO: os mapas estavam UMA SESSÃO ATRÁS do código — dois commits de s57 (4ea51e3, ff343ff) nunca entraram nos mapas; o idealizador pediu backfill da s57 + registro da s58, feito. Falta commitar a s58 (vamos commitar tudo junto). — s57 (BACKFILL, commitada s/ mapas) — REORGANIZAÇÃO DAS TELAS: (1) ABAS RENOMEADAS (Fatia 1, risco zero) — só os rótulos visíveis viraram Posts·Match·Mural·Entrega·Cadastros·Programação·Sistema; URLs e chaves internas (ficha/operacao/kanban/planilha/profissionais/listas/painel) seguem as antigas DE PROPÓSITO, nenhum link quebra. (2) ABA POSTS = TELA DE DESCANSO — inverteu o peso da /ficha do operador: a tela de repouso virou o RELATÓRIO dos Posts (agrupados por status) + botão "Novo Post"; o form abre em /ficha?novo=1 ("← Voltar aos Posts"). Escopado ao operador (câmera remota e edição vão direto ao form; re-render de erro cai no form, não no descanso). Verificado: 11 checagens nos 4 estados. — anterior s56 — CAMADA 7: GLIFO AFINADO — do ∞ cruzado (s54) para DOIS "o" ENCOSTADOS (tangentes, infinito só insinuado) + LOCKUP FLUIDO na palavra. O idealizador pediu para afinar a logo: que os dois "o" em forma de infinito tivessem MAIS UNIDADE com a fonte — nascer da palavra, não ser um ∞ avulso colado no meio. Diagnóstico: o glifo da s54 destoava em PESO (traço 7 vs. haste ~8 das letras), LARGURA (esticado) e ASSENTO (flutuava acima da x-height). Iteramos na tela (widget de prévia) por várias levas: corrigi peso/largura/assento mantendo o cruzado → ele pediu "menos infinito ainda" → testei dois "o" ENCOSTADOS vs. SOBREPOSTOS → escolheu o encostado (lê primeiro como os dois "o" de floor, infinito sugerido). Traço casado com a haste das letras (razão ≈ 0,22), assentado na x-height, cada laço do tamanho de um "o". LOCKUP FLUIDO: apertei o espaçamento até "6fl" e "r" abraçarem o símbolo com o respiro das outras letras — "6floor" lê como UMA palavra só. ANIMAÇÃO "forma e dissolve" segue (CSS keyframes ~6s); como o traço é uma linha contínua, contorna um "o" e depois o outro (esq→dir) = forma um laço por vez, parece a palavra se formando; aprovado ("ficou bom"). Nota de ferramenta: o renderizador de prévia do chat mostra SVG PARADO (não toca CSS/SMIL) — pra ver mexendo, abrir o .svg no navegador (lá a animação CSS funciona). GRAVADO: novo path canônico (2 círculos tangentes raio 50 → ±100×±50, stroke 24 no símbolo cheio) MESMO nos 3 SVGs; o lockup usa em scale(0.369) + non-scaling-stroke 8 (peso do "o"); _marca_simbolo do Flask atualizado (cabeçalho/abas/login pegam o glifo novo no próximo Voltar+Entrar); doc da C7 atualizado (forma, path, animação, rejeitados — o ∞ cruzado virou registro, não caminho). Verificado: py_compile OK + os 3 SVGs validam como XML; NÃO testado ao vivo (precisa Voltar ao saguão + Entrar). 2ª PARTE (mesmo dia): ele pediu o "nome COM o símbolo em TODO lugar, sem logo+6floor" → o _marca_lockup do Flask virou o WORDMARK "6fl∞r" (o símbolo é o "oo" da palavra) no login E no cabeçalho/abas. SAGA de renderização: empilhava ("6fl"/∞/"r" em 3 linhas) por causa do reset svg{display:block} do ambiente (não era largura); fechado como UMA imagem <svg> única (texto "6fl"+glifo+"r" juntos, textLength p/ largura estável) = impossível empilhar. Criada a opção SÓ-∞ (_marca_icone): a marca sem a palavra (favicon/cabeçalho recolhido), disponível no código; onde aplicar fica p/ depois. Falta commitar. Próximo (dito por ele ao fechar): trabalhar com o agente p/ DESENVOLVER as telas (full-dark tela a tela: Planilha→Painel→Ficha); pendências C7: onde usar o só-∞ · ícone do app real · grid · lockup em contornos · ou teste multi-máquina/.app/Missão A com chave real. — anterior s55 — CAMADA 7: a marca 6floor APLICADA NAS TELAS (Fatias 1-2: a porta de entrada + Kanban full-dark). O idealizador escolheu aplicar a marca; recomendei uma fatia contida e de baixo risco — login + cabeçalho/abas — deixando as telas operacionais full-dark pra fatias seguintes (trabalho grande/arriscado no sistema ao vivo). FUNDAÇÃO COMPARTILHADA no flask_gma.py: MARCA_VARS (:root espelhando marca/6floor_paleta.css, um acento só) + MARCA_FONTE (Space Grotesk via Google Fonts; sem internet cai em system-ui, nada quebra, é cosmético/fora do ciclo) + _marca_simbolo/_marca_lockup (o ∞ monoline inline da s54 + a palavra 6floor). Regra: nunca cravar hex novo nas telas, usar var(--6f-…). LOGIN/ACESSO repintado pro mundo escuro real (vars + Space Grotesk + lockup 6floor no lugar do "GMA"; serve /login·/logout·/operadores). CABEÇALHO + ABAS do frame operacional (_pagina + CSS_ABAS) viraram a marca: header escuro --6f-bg-base com ∞ + 6floor + título da página separado por divisória; abas escuras com a aba ATIVA sublinhada em TEAL. FATIA 2 (mesma sessão) — KANBAN FULL-DARK: a 1ª tela operacional foi pro mundo escuro de forma ESCOPADA POR TELA — o _pagina agora marca <body class="pag-{aba}"> e o tema escuro vale só em body.pag-kanban (colunas/cards/post-it/barra Concluído com tinta teal apagada/botão teal); Planilha/Ficha/Painel, que dividem o mesmo _pagina, SEGUEM CLARAS (a classe .pag-… isola). Razão do escopo: full-dark de tudo de uma vez arriscaria a legibilidade no sistema ao vivo. Verificado por screenshot: Kanban escuro a 1360px + Planilha confirmada ainda clara. Corpo das demais telas segue claro até a sua fatia. Verificado: py_compile OK + screenshots (login, frame operacional e Kanban renderizados como HTML estático via app.test_request_context num preview isolado) — login com ∞ teal/6floor/cartão escuro/botão teal, frame com header da marca + abas escuras + aba ativa teal + corpo legível; andaime de preview removido. NÃO testado ao vivo (precisa Voltar ao saguão + Entrar pra o Flask do projeto recarregar). Falta na C7: telas operacionais full-dark uma a uma (Kanban→Planilha→Ficha→Painel) · ícone do app real · grid · lockup em contornos. Próximo: seguir a C7 (full-dark/ícone) · teste multi-máquina · .app · Missão A Fatia 2 com chave real. — anterior s54 — CAMADA 7: GLIFO DO SÍMBOLO + ANIMAÇÃO FECHADOS E SALVOS EM ARQUIVO. Sessão de design conduzida pelo orquestrador, iterada na tela. ACHADO QUE ABRIU A SESSÃO: o idealizador mostrou uma imagem da marca "de outra sessão" e perguntou se eu mudei algo — descobrimos que os rascunhos visuais da s53 NUNCA viraram arquivo (eram desenhos de tela que evaporaram) e que a imagem mostrava um caminho REJEITADO (anéis lado a lado). Isso virou o objetivo: fechar o glifo E SALVAR no disco. GLIFO FECHADO: infinito CRUZADO (linha passa por si mesma, lê como ∞ até pequeno), monoline, espessura MÉDIA (afina pra precisão mas sobrevive no 16px — espessa pesa, fina some). ANIMAÇÃO "TRABALHANDO" = "FORMA E DISSOLVE": o laço se desenha do zero, fica inteiro aceso um instante (o "selo") e dissolve pelo mesmo caminho, lento/espacial (~6s) pra gerar calma. CAMINHO DA ESCOLHA: testei "dados correndo" (fluxo de pontos/pacotes/varredura) → ele achou DEMAIS, pediu mais espacial/calmo → órbita/respiro → ele puxou pra "formação do infinito" → fechamos forma-e-dissolve (as agitadas descartadas). SALVO: 3 SVGs (marca/6floor_simbolo.svg, _trabalhando.svg, _lockup.svg) + doc desenho_camada7_marca_GMA.md = fonte de verdade da C7 (decisões s53+s54, path canônico, cores, keyframes, caminhos rejeitados). Nota: o lockup usa Space Grotesk via @import (precisa de internet) → "lockup em contornos" entrou no que falta. PALETA COMPLETA tb fechada na s54 (depois do commit do glifo): sistema de cor do mundo escuro, um acento só (teal de identidade; vermelho/âmbar só pra alerta) — marca (teal/forte/claro/trilho) + 4 fundos sala-de-controle + borda/3 textos + estados (ok=teal, aviso âmbar, erro vermelho), em marca/6floor_paleta.css; idealizador aprovou de primeira. Falta na C7: ícone do app real, grid, aplicar nas telas, materiais. Próximo: seguir C7 (ícone/aplicar nas telas) · teste multi-máquina · .app · Missão A Fatia 2 com chave real. — anterior s53 — CAMADA 7 INICIADA: a marca do 6floor. Sessão de identidade/design (SEM código), conduzida pelo orquestrador. O idealizador escolheu avançar a C7 (minha recomendação: o teste multi-máquina exige bancada física; a C7 rende entregável de mesa). Conversa longa de marca com vários rascunhos visuais até convergir. NOME — 6floor confirmado (minúsculas): o "6" veio de que a IA mora no 6º andar; pra fora soa estrutura/prédio sólido, pra dentro guarda o sentido pessoal; mistura "6"(pt)+"floor"(en) fica como estilização. FONTE — Space Grotesk (escolha dele, após comparar IBM Plex Mono/Archivo/Sora/JetBrains Mono; eu recomendei uma mono pela credibilidade de "ferramenta séria" e por resolver o l↔1, ele preferiu a Space Grotesk pela cara); "l" reto mantido (rabinho discreto fica disponível se quiser depois). ACENTO — teal (#2BB58C). SÍMBOLO — os dois "o" de floor viram um INFINITO monoline no estilo da fonte; o "olhar/vigilância" (ideia inicial) ficou nas entrelinhas (pupilas literais abandonadas, não funcionaram); ESTADO VIVO: repouso = ∞ calmo, trabalhando = um COMETA percorre o infinito (vira indicador de status, ecoando as barras de progresso por andar e o andar 8/P&D permanente). Caminhos rejeitados: laço cruzado "fita/gravata" (destoava da tipografia) e anéis lado a lado (não liam como infinito). MUNDO VISUAL: ferramenta séria de logagem/DIT moderna (linhagem Hedge/Silverstack/ShotPut + Frame.io/Linear), fundo escuro, um acento só, ícone legível até 16px. Falta (build futuro): refino do glifo, paleta completa, grid, layouts/materiais — a barra do andar 7 saiu do zero. Próximo: aplicar a marca · teste multi-máquina · .app · Missão A Fatia 2 com chave real. — anterior s52 — ANDAR 8 ABERTO: P&D (Pesquisa & Desenvolvimento). Sessão breve de anúncio/identidade (SEM código): o idealizador abriu um novo andar, o 8 · P&D, a COBERTURA do prédio — diferente das camadas 1–7, NÃO é elo da esteira de mídia (não processa cartão). Olha PRA FORA (vigia/pesquisa/testa as melhores ferramentas e processos) e PRA DENTRO (zela pelo pleno funcionamento do sistema — saúde dos processos, regressões, dívidas técnicas, "o que pede atenção agora"). Andar PERMANENTE: não entrega uma peça e fecha, fica sempre aberto (por isso sem barra de progresso). Registrado nos 3 mapas. Próximo: se ele quiser, criar o agente de pesquisa + um ritual de varredura; por ora é identidade — o andar existe no mapa. — anterior s51 — LOGIN DO OPERADOR (Camada 5): a base ganhou identidade + barreira de acesso. Decisões do idealizador (via perguntas): login serve para OS DOIS (identidade E barreira); cada operador tem NOME + SENHA PRÓPRIA; operadores GLOBAIS (a equipe é a mesma de evento pra evento — cadastra uma vez, vale em todos os projetos). DUAS FATIAS na mesma sessão. FATIA 1 — a porta: novo operadores.py = armazém GLOBAL num arquivo na raiz (operadores.json, FORA do git — guarda senhas), senha NUNCA em texto puro (hash pbkdf2_hmac sha256 + sal por operador + 200k iterações, biblioteca padrão, nada instalado; conferência em tempo constante). Barreira: passo 1.5 no _portao_de_acesso exige operador logado na BASE (Painel/Kanban/Planilha/match/listas…); o remoto/câmera NÃO muda (já limitado a /ficha; login é só-base). À prova de tranca: sem operador ativo, /login vira bootstrap (cria o 1º). Telas /login·/logout·/operadores (cadastrar/desativar com travas: não desativa a si mesmo nem o último ativo). Sessão assinada por app.secret_key estável (.gma_secret, fora do git) → login sobrevive a reinícios. FATIA 2 — o carimbo: coluna nova eventos.operador (migra no Entrar); registrar_evento ganhou um contexto por-requisição (threading.local) que o Flask preenche a cada request → TODA ação na base sai carimbada com quem fez, sem passar o operador por cada chamada; ação automática (porteiro/cópia/auditoria/vigias) = NULL = "sistema". "Quem preencheu" do Post puxa do operador logado. Nova tela /historico (quando·quem·o quê). Verificado: teste_login_operadores.py (27 checagens, incl. remoto nunca vê o login) + teste_carimbo_operador.py (13, incl. migração de banco antigo) + suíte existente toda verde. INCIDENTE "não mudou" (resolvido, não era bug): Encerrar/Iniciar não trocava o código porque o login vive no Flask do projeto, que só renasce ao Entrar (subir a sessão); clicar "Iniciar" com o saguão já no ar NÃO reinicia (a trava só reabre o navegador no velho). Regra: mudei flask_gma/banco_dados → Voltar ao saguão + Entrar; mudei saguao.py → Encerrar + Iniciar (esperando o Encerrar terminar). Ação: derrubei o saguão velho (SIGTERM) + removi travas órfãs → estado 100% limpo. Commitado E PUSH no main. Próximo (rumo C5): teste multi-máquina (2-3 cartões) · empacotar .app · ou Camada 7. — anterior s50 — "FECHAR O SAGUÃO" (Camada 5): sessão de consolidação/limpeza da fundação da plataforma, escolhida pelo idealizador ao avançar a C5 — antes de empilhar multi-máquina/login, arrumar o saguão que ficou meio-construído na s42. DUAS PARTES. (1) LIMPEZA do mecanismo de reinício ANTIGO, que o saguão já substituiu mas cujo entulho seguia no código: removidos a constante SINAL_REINICIAR + o ramo .gma_reiniciar do laço do main() do maestro (inicializar_gma.py), as rotas /painel/trocar e /painel/reiniciar + o helper _maestro_rodando + o parâmetro recarregar/script da página "Trocando…" (flask_gma.py), e a instrução velha no ngrok_gma.sh. Preservado o VIVO: .gma_encerrar (o saguão vigia), _painel_criar_sinal (botão Desligar), /painel/novo. Uma referência órfã (limpar_sinais usava a constante removida) viraria NameError em runtime — o py_compile não pegou, a VARREDURA pegou. (2) FEEDBACK "SUBINDO…" no saguão: antes o Entrar BLOQUEAVA alguns segundos (subir_todos espera o Flask responder) e a tela congelava sem sinal de vida; agora o saguão sobe a sessão em SEGUNDO PLANO (thread) e responde NA HORA com uma tela de espera (spinner + "Subindo a sessão de <projeto>…") que faz poll de um endpoint novo GET /entrando-status (JSON fase subindo/pronto/erro); ao ficar pronto redireciona pro Flask do projeto, se der erro mostra o aviso na própria tela com "Voltar ao saguão" — nunca tela morta. Entrar no projeto já rodando pula direto (303). Verificado: 4 arquivos compilam, zero referências órfãs no projeto, teste isolado em porta 5077 com entrar_no_projeto FALSO (sem subir processos reais, pra não colidir com o sistema vivo) passou nos 4 cenários (resposta imediata, subindo→pronto, atalho 303, falha vira erro na tela). NÃO testado ao vivo (precisa Encerrar+Iniciar). Commitado no main. Próximo (rumo C5): login do operador · teste multi-máquina (2-3 cartões) · .app · ou Camada 7. — anterior s49 — MISSÃO A Fatia 2 construída (Camada 6): a BUSCA CONVERSACIONAL, o PRIMEIRO LLM do GMA — rodando em API SIMULADA (custo zero), chave adiada pelo idealizador. assistente_ia.py (NOVO) põe um LLM por cima da busca mecânica da Fatia 1: o editor pergunta em linguagem natural, a IA (1) TRADUZ a pergunta em termos de busca lendo o "cardápio" do evento (grupos/listas/profissionais), (2) roda a Fatia 1 — que continua sendo a VERDADE, a IA nunca inventa arquivo —, (3) REDIGE uma resposta apontando os arquivos/takes. 3 estados: real (chave → chama o Claude), simulado (LLM falso em processo, custo zero, pra ver o fluxo antes de pagar), desligado (cai na busca mecânica, sem regressão). Motor = Claude Haiku 4.5 na caixa isolada .venv_ia via subprocesso (assistente_ia_motor.py), igual ao Whisper — o Python do ciclo crítico nunca ganha a dependência; só TEXTO sobe, a mídia NUNCA. Barra "🤖 Perguntar" na /planilha (decisão s47: barra agora, chat à parte no futuro). 17 testes verdes (motor real trocado por falso + modo simulado de verdade, incl. teste de SEGURANÇA: caminho de mídia não vaza pra API); Fatia 1 segue 20/20; integração via test client (HTTP 200, caixa do Assistente IA renderiza; desligado cai na barra mecânica). NÃO testado com chave real (custo adiado) nem ao vivo (precisa Encerrar+Iniciar). Decisões do idealizador: motor Claude API; comportamento tradutor+redator; rodar simulado agora e "estruturar o que falta" antes do custo; PRÓXIMOS FOCOS = Camada 5 e Camada 7 (um por sessão). Falta commitar. — anterior s48 — TRANSCRIÇÃO AUTOMÁTICA construída (Camada 6): novo vigia_transcricao.py, um laço assíncrono irmão do exportador do Sheets que a cada 60s acha cartões de áudio copiados-e-não-transcritos e dispara a transcrição SOZINHO, fora do ciclo crítico (chama o transcritor.py na caixa .venv_ia como subprocesso; nunca toca na mídia; dorme em silêncio se a caixa não existir). Decisão do idealizador: marca de "já tentei" = CARIMBO no banco (coluna cartoes.transcricao_tentada_em), pra um cartão de áudio sem fala (como o Sound Devices só-metadados da s47) ser tentado UMA vez e sair da fila, em vez de repetir pra sempre. Ligado ao inicializar_gma (sobe/desce com a sessão, prefixo [TRANSCRICAO]); o botão manual 🎙 também carimba pra os dois caminhos não se atropelarem. Bug de teste pego e consertado: a 1ª versão do teste importava o banco_dados antes de apontar pro banco de teste e ESCREVEU cartões de teste no gma.db real — limpei os 5 de teste (os 4 reais intactos) e consertei o teste pra setar GMA_DB no topo. 12 testes verdes; NÃO testado ao vivo (precisa Encerrar+Iniciar) e a transcrição ponta a ponta ainda espera um cartão de áudio com .wav real. Falta commitar. Próximo: Missão A Fatia 2 (LLM) · trilha de áudio dos vídeos · controle por DATA na aba Listas · Camada 7. — anterior s47 — MISSÃO A Fatia 1 + 3 consertos no teste ao vivo do áudio recebido. Sessão escolhida: avançar a IA. Alinhamento: a "IA que analisa o evento" é a 1ª camada (montar o projeto); pela ordem de build combinada (transcrição→Missão A→Missão B), o próximo natural era a Missão A. CONSTRUÍDO (delegado ao ia-gma): MISSÃO A — Fatia 1 = a FUNDAÇÃO da busca conversacional, SEM IA/API — `banco_dados.buscar_na_planilha` faz busca textual mecânica (offline/grátis) cruzando transcrição + classificação + identificação; barra de busca na /planilha que destaca as linhas e aponta quais áudios bateram. NÃO mexe na fonte única (Sheets não muda) — é só filtro da vista. Decisão: barra na planilha agora, tela de chat à parte no futuro (a função já está desacoplada pra a Fatia 2/LLM). 20 testes; achou Volkswagen/Sunset/Péricles no banco real do rock_in_rio. Depois, TESTANDO o áudio recebido ao vivo, caçamos 3 bugs: (1) STATUS DO POST não saía da Operação/Nova Ficha — a auditoria concluía o cartão mas nunca avançava o Post (ficava preso em matched); nova `concluir_formulario_do_cartao` chamada nos 2 pontos de conclusão da auditoria (físico E recebido) + grupo "Concluído/entregue" na Nova Ficha + backfill dos travados (8 testes). (2) "Posts aguardando material" não esvaziava — essa lista lê dos JSONs da fila e o RECEBIDO pula o Matcher que avançaria o JSON; filtro novo cruza pelo db_formulario_id e confia no status do banco + sincronizei os JSONs presos. (3) "CALIFA + CALIFA" na planilha — a coluna Profissional juntava nome + nome_audio iguais; agora só junta quando diferem. (4) s46 reforçada: o Sheets caiu de novo (login gcloud venceu) mas o bilhete mostrou "erro" genérico em vez de "login vencido" — a msg do gcloud era cortada em 200 chars antes da marca de reauth; agora 500 chars + reconhece a falha do print-access-token (imediato: rodar gcloud auth login). TESTE AO VIVO do áudio CALIFA: "Copiar agora" funcionou (MD5/PDF/_COPIADO/auditoria sem Parashoot) MAS o cartão Sound Devices não tinha gravação nenhuma — só metadados; a transcrição rodou e achou 0 áudios (motor OK, falta áudio real). PEDIDO do idealizador: a transcrição deve ser AUTOMÁTICA (gatilho pós-cópia, um vigia assíncrono fora do ciclo crítico) — próxima fatia da C6. Tudo commitado no main. Próximo: transcrição automática · Missão A Fatia 2 (LLM) · controle por DATA na aba Listas · trilha de áudio dos vídeos · Camada 7. — anterior s46 — AVISO DE LOGIN DO GOOGLE NO PAINEL (C3+C5): fim da falha silenciosa do Sheets. Sessão curta. A dor (achada na s43): a sessão do gcloud expira de tempos em tempos e o exportador, rodando não-interativo, falhava EM SILÊNCIO a cada minuto — o Sheet de todos os projetos travava e só se percebia pela planilha parada. Agora o exportador deixa um "bilhete de status" (.gma_sheets_status.json, troca atômica) a cada ciclo: ok / login-vencido / sem-internet / pausado / nao-configurado / erro, com horário e projeto. O Painel lê o bilhete e a caixa do Google Sheets mostra bolinha viva: 🟢 "atualizado HH:MM" / 🔴 "Google precisa de login — gcloud auth login" / 🟡 "sem internet". Detecção do "reauth" do gcloud isolada dos erros genéricos (404/quota/rede); bilhete de outro projeto ou velho (>5min) é ignorado. Offline-first intacto (copiar/MD5/auditar nunca dependeram do login). 10 testes verdes (teste_status_sheets.py). E o recurso provou o valor na 1ª ocasião: ao reiniciar, o bilhete flagrou na hora "o Sheets não funciona" = `erro: no such column: a.transcricao`. RAIZ: a migração da s45 (coluna `transcricao`) nunca rodou nos bancos dos projetos — as migrações vivem em inicializar_banco() mas Flask/exportador abrem com obter_conexao() (não migra), e montar_planilha (fonte única da /planilha E do Sheets) passou a exigir a coluna → quebrava p/ todos. Consertado: migração idempotente rodada nos 3 bancos (planilha do rock_in_rio confirmada ao vivo, bilhete 🟢 ok) + correção da RAIZ (commit bfbf186): o ENTRAR do saguão agora MIGRA o banco do projeto antes de subir os processos — elimina a classe inteira de "apagão silencioso da planilha" quando uma coluna nova entra. Tudo commitado no main. Próximo: Missão A, ou trilha de áudio dos vídeos, ou controle por DATA na aba Listas, ou Camada 7. — anterior s45 — 1º TIJOLO DA CAMADA 6 CONSTRUÍDO: transcrição de áudio (Whisper local) POR ARQUIVO. Alinhamento que abriu a sessão: o tijolo é SÓ a transcrição crua (combustível); o trabalho de guiar qual arquivo usar é a Missão A (2ª camada), construída depois em cima disso. Motor `faster-whisper` LOCAL (modelo small, PT), provado primeiro num áudio real (transcreveu idêntico, offline/grátis), numa CAIXA ISOLADA `.venv_ia/` (fora do Python do ciclo crítico e fora do git); o Flask chama o novo `transcritor.py` como subprocesso. DECISÃO DO IDEALIZADOR (a "troca" da sessão): granularidade POR ARQUIVO, não por card — meu 1º corte guardava uma célula gorda em `cartoes`; ele apontou que incharia a tabela/Sheets E que a Missão A precisa apontar "qual arquivo/qual take". Refatorado: transcrição mora em `arquivos.transcricao` (1 por áudio, degrau do arquivo→trecho→take); a planilha mostra só STATUS compacto ("N áudios transcrito(s)"), e o texto completo vive na tela leve `/cartao/<id>/transcricao` (um bloco por arquivo) — é o que a Missão A vai pesquisar. Botão 🎙 Transcrever só em cartão de ÁUDIO já copiado, roda em background (thread). Aplicada também a reorder de blocos da planilha decidida na s44: classificação variável foi pro FIM (núcleo fixo na frente, senão filtros do Sheets quebram). Escopo: só cartões de áudio (trilha de vídeo = fatia futura). 12 testes verdes + integração via test client. NÃO testado ao vivo no sistema rodando ainda (precisa Encerrar+Iniciar). Commitado no main. Próximo: Missão A, ou controle por DATA na aba Listas, ou Camada 7. — anterior s44 — CAMADA 6 ABERTA (desenho + agente): o idealizador escolheu avançar a IA, mas pediu que eu entendesse PRIMEIRO como ele pensa a IA antes de construir. Sessão de desenho/escopo (sem código). Registrado o mapa das **3 camadas de IA**: (1ª) a IA MONTA O PROJETO a partir de upload de referências + chat (Posts/listas/grupos; operador ajusta depois, não aprova antes); (2ª) BUSCA CONVERSACIONAL p/ o editor (Missão A — "qual arquivo tem tal cena/pessoa/contexto?", sugere takes; cruza classificação do Post + transcrição); (3ª) LEITURA DE IMAGEM (Missão B) mirando profundidade até o take/timecode = poder de venda. Tudo converge na planilha + barra de busca conversacional. Decisões: nuvem/API permitida nas camadas de IA pela QUALIDADE (só o ciclo crítico é offline-sagrado; mídia nunca sobe); ordem de BUILD = transcrição (Whisper local, grátis) → Missão A → Missão B (a 3ª alimenta a 2ª); ordem das COLUNAS da planilha = núcleo fixo na frente, classificação variável no fim (senão filtros do Sheets quebram no meio do evento). Criados `desenho_camada6_IA_GMA.md` + agente `ia-gma`. Pré-requisito levantado pelo idealizador: controle por DATA na aba Listas (grupo por dia, como os shows do Rock in Rio). Primeiro tijolo definido (não construído): transcrição Whisper local → coluna fixa na planilha. — anterior s43 — ARCO RECEBIDOS FECHADO (C2+C4), mergeado no main: material que NÃO vem por cartão (pasta satélite `RECEBIDOS/<NOME>_<idPost>/`) agora COPIA e AUDITA. Dor que abriu a sessão: o idealizador criou um Post de material avulso (DANIEL PARDAL, 115 RAW), clicou em "pronto para copiar" e nada aconteceu — porque o arco tinha só as Fatias 1-3 (s41) e o botão SÓ marcava. Construído: **Fatia 4 (C2)** — 2º botão "Copiar agora" cria o material JÁ CASADO com o Post (sem Matcher — a pasta já é dele pelo id no nome), copia com MD5/.sppo/PDF igual a cartão, e renomeia a pasta de origem `_COPIADO` (nunca apaga); marca `origem_material=recebido` no banco. **Fatia 5 (C4)** — audita contagem+tamanho normal mas PULA o Parashoot (não há cartão pra ejetar); cartão físico segue COM Parashoot. Decisões do idealizador: dois passos (marcar × copiar) e não apagar (renomeia). Testes verdes (25+3). **TESTADO AO VIVO:** o idealizador copiou o Pardal no sp2b (cartão casado, auditado sem Parashoot, pasta `_COPIADO`) — funciona. A queixa "a planilha não atualizou" NÃO era do arco recebidos: era o **login do Google (gcloud) expirado** (~21:50, falhava em silêncio travando o Sheet de todos os projetos) + um descompasso de projeto ativo (sessão=sp2b, painel=rock_in_rio); ambos resolvidos (relogin + entrar no sp2b), planilha do sp2b confirmada com o Pardal. DEFERIDO: aviso de login no Painel (pra falha nunca mais ser silenciosa) + esticar a sessão Google no admin do serafa.me. Próxima fatia pedida: OK remoto da cópia (acionar pelo celular). Próxima SESSÃO: avançar Camada 6 ou 7. — anterior s42 — SAGUÃO DE 2 NÍVEIS construído (Camada 5): novo `saguao.py` = o "térreo" do sistema, um servidorzinho próprio na porta fixa 5055 que NUNCA cai. Mostra a lista de projetos; **Entrar** sobe a sessão daquele projeto (Flask na 5050 + processos, reusando o motor do maestro); **Voltar ao saguão** desce SÓ a sessão e volta ao térreo (que continuou de pé) — fim do reinício frágil na troca de projeto. Trava de instância única própria (.gma_saguao.lock), encerramento limpo por SIGTERM, abre o navegador sozinho. Atalhos "Iniciar/Encerrar GMA" repontados pro saguão; Painel do projeto ganhou "⬅ Voltar ao saguão". Decisão: ABANDONAR o "maestro robusto" da s41 (o saguão o substitui); as mudanças sem commit da s41 não foram apagadas, só deixaram de ser o caminho. Testado ponta a ponta (subir/descer sessão real, trava, SIGTERM). Sem commit. — anterior s41 — ARCO RECEBIDOS avança + MAESTRO robusto: pergunta de ORIGEM no Post ("Como o material chega?" Cartão físico × Pasta recebida) · PASTA LOCAL por Post + LINK por Post (acesso externo) + GATILHO do operador ("pronto para copiar", só marca) · BLINDAGEM do maestro (troca de projeto não derruba mais o sistema) · ESPERA DA PORTA 5050 na subida do Flask (corrige o "sem tela" na troca: o Flask não subia porque a porta não tinha liberado) · AUTO-RECARREGAMENTO do painel (fim da página enganosa "maestro não rodando"). DECISÕES: link direção A (sistema oferece) + 1 pasta/link por Post; modelo SAGUÃO DE 2 NÍVEIS aprovado como rumo da C5 (substitui o reinício-na-troca; a blindagem de hoje é o 1º tijolo). Sem commit. — anterior s40 — 4 BUILDS mergeados no main: RÉGUA ÚNICA do que é mídia (função compartilhada C2+C4, fecha o "108 vs 106" da s39) · caixa de PASTA DE RECEBIDOS no Painel (1ª fatia do arco satélite: config + Testar com detecção do Drive "só na nuvem") · TRAVA de instância única do maestro (flock — clicar Iniciar 2x não duplica) · NGROK AUTOMÁTICO (o maestro sobe o túnel junto com o sistema, validado ao vivo). Arco satélite desenhado (memória pasta-satelite-recebidos); lição de git gravada (não deixar o disco num branch-surpresa). — anterior s39: TESTE de cópia real (GoPro 7,7GB) ponta a ponta no projeto SP2B; BUILD: Google Sheets POR PROJETO no exportador (#1), PROXY marcado na cópia (sempre copia + avisa — Fatias A/B), EXCLUIR Post definitivo (#3), DATA DE LOGAGEM pelo relógio do sistema (#4), NOMES CURTOS editáveis (#5: nome_raiz/nome_curto, pasta+cartão+planilha, ASCII), CENTRO DE CONTROLE DOS POSTS na Nova Ficha (grupos recolhíveis por status + cancelar/restaurar/excluir; Operação ficou só com o MATCH). Em desenho: redesenho C2/C4 com "regra única do que é mídia" + benchmark de velocidade. Antes: MATCH MANUAL + GATE DOS CARTÕES + Acompanhamento AO VIVO (s38), PAINEL DE CONTROLE / cockpit (s37), Rock in Rio + programação do dia (s36), Sheets real+dinâmico (s32/s34), grupos editáveis (s33).)

---

## 1. Onde estamos — o prédio de 7 andares (+ a cobertura: andar 8, P&D)

Pense no GMA como um prédio. Cada andar só faz sentido depois do anterior.
O coração do sistema (andares 1 e 2 — o trabalho mais difícil) está pronto e
testado com cartão de verdade.

Acima de todos fica a **cobertura — o andar 8 (P&D)**: ele não é um elo da
esteira de mídia (não processa cartão). Vigia as melhores ferramentas e
processos (pra fora) e o pleno funcionamento do sistema (pra dentro). É
permanente: nunca "termina".

```
ANDAR                                       PROGRESSO
──────────────────────────────────────────────────────────────────
1 · Check-in (identificar o cartão)         ███████████░  QUASE ✅
        └─ Matcher seguro + perfil que aprende cada pessoa
        └─ ficha PRÓPRIA no GMA (gabarito + edição) · online c/ senha · QR
        └─ cartão SEM MÍDIA tratado em 2 níveis (ignora × chama operador)
        └─ Nova Ficha v2 COMPLETA ✅ (Fatias 1-5): cadastro de Profissionais +
           CÂMERA no cadastro; multi-seleção, data inteligente, "quem preencheu" (s33)
        └─ s38: MATCH MANUAL — operador resolve cartão órfão na mão
           (escolhe 1 cartão + 1 Post → dispara a cópia). Cancelar/restaurar Posts.
        └─ NOVO (s39): EXCLUIR Post definitivo (#3, guarda match real) · LEITOR
           classifica PROXY (.LRV→clipe) e RAW (.GPR→foto) · NOMES CURTOS editáveis (#5)
        └─ NOVO (s39): CENTRO DE CONTROLE DOS POSTS na Nova Ficha — grupos recolhíveis
           por status + editar/cancelar/restaurar/excluir; Operação ficou só com o MATCH
        └─ NOVO (s41): pergunta de ORIGEM no Post ("Como o material chega?" Cartão físico ×
           Pasta recebida) — porta de entrada do arco RECEBIDOS (satélite)
        └─ NOVO (s51): "quem preencheu" do Post puxa SOZINHO do operador logado na base (login C5)
        └─ NOVO (s57): ABAS RENOMEADAS (Posts·Match·Mural·Entrega·Cadastros·Programação·Sistema —
           só os rótulos; URLs/chaves seguem as antigas) + aba POSTS vira TELA DE DESCANSO
           (relatório por status + botão "Novo Post"; o form abre em /ficha?novo=1)
        └─ NOVO (s63): TÚNEL CLOUDFLARE = ÚNICO túnel (ngrok REMOVIDO) — QR cai DIRETO na ficha,
           sem a tela de aviso do ngrok grátis + sem o limite de 1 túnel; o MAESTRO sobe o
           cloudflared sozinho com o sistema e o QR auto-detecta a URL (arquivo de estado)
        └─ falta: mural dos câmeras · domínio fixo do túnel (modo nomeado do Cloudflare)
2 · Transferência (copiar com segurança)    ████████████  PRONTO ✅
        └─ s38: pasta de destino configurável (GMA_DESTINO) + falha limpa
           quando o volume some (acaba o "copiando eterno")
        └─ NOVO (s39): PROXY atravessa o pipeline — SEMPRE copia + marca (tipo/proxy_de
           no .sppo+banco) + AVISA; teste de cópia real GoPro 7,7GB OK (106/106)
        └─ NOVO (s40): RÉGUA ÚNICA do que é "mídia real" (compartilhada C2+C4 — fim do
           tropeço em .DS_Store/.fseventsd/.sppo); falta cópia rápida + auto-cura + benchmark
        └─ NOVO (s43): COPIA MATERIAL RECEBIDO (pasta satélite, sem cartão) — botão "Copiar agora"
           cria o material já casado com o Post, copia de RECEBIDOS/<slug>/ e renomeia _COPIADO
        └─ NOVO (s60): VELOCIDADE AO VIVO (estilo ShotPut) — o copiador publica um bilhete
           (.gma_copia_status.json, best-effort, não toca mídia) e a aba MURAL mostra uma faixa
           com MB/s + barra + arquivo X/Y + tempo restante enquanto copia. Fatia 2 (histórico) a fazer
3 · Banco de dados (guardar tudo)           ███████████░  QUASE ✅
        └─ Kanban + Planilha + Google Sheets REAL no ar (s32, via impersonação)
        └─ GRUPOS EDITÁVEIS (s33): 1 ponto de criação → chip na ficha + coluna na
           planilha; Sheets DINÂMICO espelha o molde (s34); montador compartilhado
        └─ s38: GATE DOS CARTÕES (blindagem 3 camadas contra cartão-fantasma)
        └─ NOVO (s39): Google Sheets POR PROJETO no exportador (#1) — cada projeto
           escreve na SUA planilha; projeto real sem planilha PAUSA (não vaza pro global)
        └─ NOVO (s46): BILHETE DE STATUS do exportador → bolinha viva do Sheets no Painel
           (🟢 atualizado HH:MM · 🔴 login do Google vencido · 🟡 sem internet) — fim da falha silenciosa
        └─ NOVO (s51): LOG DE OPERAÇÕES carimba QUEM fez (eventos.operador; "sistema" p/ ação automática)
           + tela /historico — avança o requisito de governança
4 · Auditoria + devolver o cartão           ████████████  PRONTO ✅
        └─ embaralha · ejeta · RESTAURA pelo Parashoot — testado com cartão real
        └─ NOVO (s43): material RECEBIDO (sem cartão) → audita contagem+tamanho e conclui,
           mas PULA o Parashoot (não há cartão pra ejetar); cartão físico segue COM Parashoot
5 · Tela bonita + várias máquinas           ████░░░░░░░░  EM CONSTRUÇÃO
        └─ NOVO (s37): PAINEL DE CONTROLE (cockpit no Flask) — troca de projeto com
           reinício guiado, conexões com Testar, ligar/encerrar por atalho clicável
        └─ projeto-festival Rock in Rio + programação do dia (s36); por-projeto isolado
        └─ NOVO (s40): caixa de PASTA DE RECEBIDOS (satélite) · TRAVA de instância única do
           maestro · NGROK AUTOMÁTICO (o túnel sobe junto com o sistema)
        └─ NOVO (s42): SAGUÃO DE 2 NÍVEIS CONSTRUÍDO ✅ (saguao.py) — térreo na porta 5055 que
           NUNCA cai; Entrar sobe a sessão do projeto (Flask 5050 + processos), Voltar ao saguão
           desce só ela. Fim do reinício frágil na troca. Atalhos repontados; "⬅ Voltar ao saguão"
           no Painel; trava única + SIGTERM limpo. (s41 "maestro robusto" ABANDONADO — o saguão o substitui)
        └─ NOVO (s50): SAGUÃO "FECHADO" ✅ — removido o mecanismo de reinício ANTIGO (código morto:
           .gma_reiniciar + rotas /painel/trocar·/painel/reiniciar + _maestro_rodando) e adicionado
           FEEDBACK "subindo…" no Entrar (tela de espera c/ spinner + poll, sobe em 2º plano, mostra erro sem travar)
        └─ NOVO (s51): LOGIN DO OPERADOR ✅ — operadores.py (armazém GLOBAL, senha em hash pbkdf2);
           barreira na base (operação exige login; câmera remota intacta; à prova de tranca); telas
           /login·/logout·/operadores; carimba o log + "quem preencheu" + tela /historico
        └─ NOVO (s59): ABA SISTEMA ENXUGADA — removida a caixa "Projetos" (lista+criar), redundante
           com o saguão (que já lista/cria/entra projeto); "Projeto ativo" fica (só informa). Rota
           /painel/novo + ajudante _inicializar_banco_projeto removidos por ficarem órfãos
        └─ falta: conexões por-projeto (Fatia 2) · .app · teste multi-máquina (2-3 cartões) ·
           feedback "subindo…" também no wizard de projeto novo · operadores sincronizados entre máquinas
        └─ a desenhar (s59): testes de velocidade — de DISCO na aba Sistema e de TRANSFERÊNCIA na aba Mural
6 · Inteligência artificial (opcional)      █████░░░░░░░  INICIADA (s49 — busca conversacional)
        └─ NOVO (s44): 3 CAMADAS DE IA desenhadas + agente `ia-gma` criado
           (1ª monta o projeto · 2ª busca conversacional p/ editor · 3ª leitura de imagem)
        └─ NOVO (s45): TRANSCRIÇÃO de áudio (Whisper local) CONSTRUÍDA — POR ARQUIVO
           (arquivos.transcricao); caixa isolada .venv_ia + transcritor.py; botão 🎙 na planilha
        └─ NOVO (s47): MISSÃO A — Fatia 1 = busca textual mecânica na planilha (SEM IA/API),
           cruza transcrição + classificação + identificação; barra de busca em /planilha;
           banco_dados.buscar_na_planilha (desacoplada p/ a Fatia 2/LLM e a futura tela de chat)
        └─ NOVO (s48): TRANSCRIÇÃO AUTOMÁTICA — vigia_transcricao.py (irmão do exportador) acha
           cartões de áudio copiados-e-não-transcritos e dispara sozinho, fora do ciclo crítico;
           carimbo cartoes.transcricao_tentada_em evita repetir cartão sem fala; sobe com a sessão
        └─ NOVO (s49): MISSÃO A — Fatia 2 = busca CONVERSACIONAL (o 1º LLM do GMA) — assistente_ia.py
           põe o Claude (Haiku, .venv_ia via subprocesso) por cima da Fatia 1: TRADUZ a pergunta +
           REDIGE a resposta; 3 estados real/SIMULADO/desligado (degrada sem chave); barra 🤖 Perguntar
           na /planilha; rodando em API SIMULADA (custo zero) — chave adiada; só TEXTO sobe, mídia nunca
        └─ tudo converge na planilha + busca conversacional; nuvem permitida pela qualidade
        └─ próximo: Camada 5 ou Camada 7 (rumo do idealizador) · Missão A Fatia 2 com chave real ·
           trilha de áudio dos vídeos (ffmpeg) · controle por DATA na aba Listas
7 · Marca e identidade visual               █████████░░░  INICIADA (s61 — padrão full-dark FECHADO: 8/8 telas)
        └─ NOME: 6floor ✅ (s53) · FONTE: Space Grotesk · ACENTO: teal · mundo escuro "sala de controle"
        └─ GLIFO AFINADO ✅ (s56): saiu do ∞ CRUZADO (s54) para DOIS "o" ENCOSTADOS (tangentes, infinito só insinuado)
           — mais unidade com a fonte: traço casado com a haste das letras (razão ≈ 0,22), assentado na x-height
        └─ LOCKUP FLUIDO ✅ (s56): ∞ encaixado entre "6fl" e "r" com o respiro das letras — "6floor" lê como UMA palavra
        └─ WORDMARK EM TODO LUGAR ✅ (s56): login + cabeçalho/abas usam o "6fl∞r" (sem logo+6floor); feito como UMA imagem
           <svg> (à prova do reset svg{display:block}, que empilhava as 1ªs versões) + opção SÓ-∞ (_marca_icone) disponível
        └─ GLIFO FECHADO (s54, SUPERADO pela s56): infinito CRUZADO monoline, espessura MÉDIA (legível até 16px)
        └─ TRABALHANDO ✅ (s54): "forma e dissolve" — o laço se desenha, fica inteiro aceso e dissolve
           (lento/espacial); descartadas as animações de "dados correndo" (trânsito demais)
        └─ PALETA COMPLETA ✅ (s54): teal (único acento) + 4 fundos sala-de-controle + borda/3 textos
           + estados só-alerta (ok=teal, âmbar, vermelho); marca/6floor_paleta.css (variáveis CSS)
        └─ SALVO EM ARQUIVO ✅ (s54): marca/6floor_simbolo.svg · _trabalhando.svg · _lockup.svg · 6floor_paleta.css
           + doc desenho_camada7_marca_GMA.md (fonte de verdade da C7; rascunhos não evaporam mais)
        └─ MARCA APLICADA NAS TELAS ✅ (s55, Fatia 1): fundação no Flask (MARCA_VARS :root + Space Grotesk +
           ∞ inline); LOGIN repintado (lockup 6floor) + CABEÇALHO/ABAS do frame operacional na marca (aba ativa teal)
        └─ KANBAN FULL-DARK ✅ (s55, Fatia 2): 1ª tela operacional no mundo escuro, ESCOPADA por tela
           (body.pag-kanban); Planilha/Ficha/Painel seguem claras até a sua fatia
        └─ PLANILHA (ENTREGA) FULL-DARK ✅ (s58): 2ª tela operacional no escuro (body.pag-planilha) —
           tabela + barra de busca conversacional/mecânica + caixa do Assistente IA + destaque da busca,
           tudo em var(--6f-…); demais telas seguem claras até a sua fatia
        └─ PAINEL (SISTEMA) + HISTÓRICO FULL-DARK ✅ (s58): 3ª tela (body.pag-painel) — PAINEL_CSS reescrito
           em var(--6f-…): seções, projeto ativo, cards de conexão c/ bolinhas de status, botões, ajuda do Sheets, Histórico
        └─ FICHA (POSTS) FULL-DARK — AS DUAS CARAS ✅ (s58): 4ª tela (body.pag-ficha), operador E câmera remota
           (escolha do idealizador); CSS_FICHA reescrito + hex inline dos builders (chips/tags/toggles teal, grupos de
           Posts, descanso, banner de programação, ficha enviada); status semântico do Post mantido
        └─ CADASTROS + PROGRAMAÇÃO + MOLDE FULL-DARK ✅ (s58): 5ª–7ª telas (só-base), builders inline → ≈121 hex
           trocados por var(--6f-…); replace_all só após grep confirmar que a string não vivia na Match (que segue clara)
        └─ MATCH/OPERAÇÃO FULL-DARK + MIGRADA AO MOLDE ✅ (s61): a última tela clara entrou no escuro e,
           em vez de só repintar, MIGROU para o _pagina (molde das outras 7) — ganhou o cabeçalho da marca
           (∞ 6floor + abas) idêntico; CSS próprio→css_operacao escopado em .pag-operacao; 4 categorias de
           card viraram acento semântico (matches=teal, confirmação=âmbar, filas=neutro); MATCH=teal
        └─ ✅✅ PADRÃO FULL-DARK FECHADO: as 8 telas operacionais seguem o mesmo molde + a mesma paleta
        └─ falta da pele C7 (não são telas): ícone do app real · grid · lockup em contornos

8 · P&D — Pesquisa & Desenvolvimento         ♾  ABERTO (cobertura permanente)
        └─ olha PRA FORA: vigia as melhores ferramentas e processos
        └─ olha PRA DENTRO: zela pelo pleno funcionamento do sistema
        └─ andar que nunca "termina" — acompanha, testa e recomenda (s52)
──────────────────────────────────────────────────────────────────
```

---

## 2. O que o sistema faz — em linguagem de set

Quando um cartão chega na base, isto acontece **sozinho**, sem operador clicando:

```
  📷 Cartão chega na base
        │
        ▼
  🚪 PORTEIRO          "Chegou um cartão!" (detecta sozinho em 2s)
        │
        ▼
  🔍 LEITOR            "É uma GoPro, 106 arquivos, gravado dia 7.
        │               Atenção: tem material de 2 dias diferentes.
        │               Se NÃO houver mídia nenhuma, eu decido:
        │                · só config/lixo  → 'sem mídia, ignoro' (não copia)
        │                · arquivos grandes que não reconheço → 'verificar!'
        │                  (chamo o operador — pode ser footage estranho)."
        ▼
  🔗 MATCHER           "Esse cartão é do João — bate com a ficha.
        │               Se dois empatam, eu NÃO chuto: pergunto ao operador.
        │               E aprendo a 'assinatura' de cada um (câmera, numeração)."
        ▼
  📋 (a ficha do celular, via formulário, entra aqui)
        │
        ▼
  📦 TRANSFERÊNCIA     "É o 3º cartão do João → pasta JOAO_003.
        │               Copiando... conferindo cada arquivo (MD5)...
        │               7,7 GB copiados, 106 de 106 conferidos ✅"
        ▼
  🎞️  FRAMES            "Tirei 10 fotinhas de cada vídeo pro relatório."
        │
        ▼
  📄 RELATÓRIO PDF     "Pronto: relatório com miniaturas pra editora ver."
        │
        ▼
  🗄️  BANCO             "Anotei tudo. (e vou espelhar no Google Sheets)"
        │
        ▼
  ✂️  ANDAR 4 — AUDITORIA E DEVOLUÇÃO ✅
       "1. Confiro a estrutura toda (contagem + tamanho).
        2. Peço pro Parashoot conferir arquivo por arquivo (check).
        3. Tudo certo? Mando embaralhar e ejetar o cartão.
        4. Status → CONCLUÍDO. Cartão pronto pra voltar pro set."
        │
        ▼
  ↩️  RESTORE (quando precisar)
       "Embaralhei um cartão e preciso dele de volta? O Parashoot
        desfaz na hora — o material nunca foi apagado, só escondido."
```

A regra que segura tudo: **os arquivos de vídeo nunca saem do HD físico.**
Pra nuvem só vai *informação sobre* os arquivos (nome, tamanho, quem gravou) —
nunca o vídeo em si.

---

## 3. Linha do tempo — por que tomamos tantas decisões

Nenhuma decisão foi à toa. Cada uma resolveu um problema que apareceu
**testando com cartão de verdade**. As decisões GRANDES (🔶) sempre foram sobre
*organizar quem faz o quê* — o objetivo nunca mudou.

```
06/06  S1  🧪 1º teste real (GoPro 7,7GB) → funcionou ponta a ponta! Achou 4 bugs.

06/06  S2  🔧 Consertou os 4 bugs
           🔶 DECISÃO: chamar de "match" (não "casamento")

06/06  S3  🔶 DECISÃO: arquivo de sistema com erro = AVISO, não estraga a cópia
              (3 arquivinhos da GoPro reprovavam 103 vídeos perfeitos)

07/06  S4  🔶 DECISÃO: numeração de cartão muda de andar + reorganiza o que cada
              andar faz (C3 = só informação · C4 = auditoria · C5 = multi-máquina)

07/06  S5  🗄️ Ligou o banco de dados em todos os processos

07/06  S6  📱 Ficha online (Tally) + segurança (senhas fora do código)

07/06  S7  🧪 2º teste real → passou tudo! Mas achou 1 bug: banco gravou 0 arquivos 🐛

07/06  S8  📄 Relatório PDF bonito, com miniaturas

07/06  S9  🔶 DECISÃO: tirar fotinha do vídeo é trabalho de "robô braçal"
              (grátis, offline) → fica no ciclo.
              ENTENDER a foto é trabalho de IA → só no andar 6 (paga, depois)

07/06  S10 🗺️ Mapa vivo (este documento) — parar e olhar o todo

08/06  S11 🗄️ Exportador Sheets + auditoria.py (andares 3 e 4 ganham código)
08/06  S12 🔍 Revisão crítica: C3 e C4 não estavam fechadas (buracos mapeados)
08/06  S13 📱 Ficha enxuta e personalizável por trabalho (festival ≠ congresso)
           🔶 DECISÃO: câmera/tipo o sistema detecta sozinho; ficha fica mínima
           🔗 Matcher SEGURO: em empate, nunca troca material — pergunta ao operador
           🧠 Perfil do profissional (Fase 1): aprende câmera, modelo, prefixo e
              numeração de cada pessoa a cada match

08/06  S14 ✂️ Agente da Camada 4 criado (auditoria-gma)

09/06  S15 🔍 DESCOBERTA: o Parashoot tem CLI automatizável (check + erase)
           🔶 DECISÃO: o GMA aciona o Parashoot sozinho (sem operador clicar)
              + embaralhamento é REVERSÍVEL (só inverte 2MB; material intacto)
           ✂️ Camada 4 reescrita para usar o CLI do Parashoot

09/06  S16 🧪 3º teste real (Sony "Joe", 1,6GB) → CICLO DE VIDA COMPLETO ✅
              detecta → copia → frames → audita → check → embaralha → ejeta → RESTAURA
           🐛 Achou e consertou 1 bug (Parashoot fala "JSON em linhas")
           ↩️ Restore validado: cartão voltou inteiro pela GUI do Parashoot
           🔶 DECISÃO: feedback — relatório PDF abaixo do esperado;
              Camada 7 (marca/design) vira o próximo foco

10/06  S17 🔶 DESENHO: identidade do cartão em camadas (Matcher = autoridade)
10/06  S18 🔶 DESENHO: fronteira C1 ↔ C3 nas fichas (quem cria o quê)
10/06  S19 🖥️ Telas no ar: Acompanhamento (Kanban) + Planilha, lendo da fonte única
           📌 post-it por cartão testado (grava no banco + registra na auditoria)

10/06  S20 🔶 VIRADA protótipo → produto: planeja a Camada 5 (a plataforma)
           🤖 Cria o agente plataforma-gma + blueprint; NÃO constrói ainda
              (1º o laboratório passa nos testes de 2–3 cartões simultâneos)

10/06  S21 📱 Ficha PRÓPRIA dentro do GMA (não depende mais só do Tally)
           🧩 Gabarito (campos que se sugerem do histórico) + edição de fichas
           🔶 DECISÃO: nossa ficha é o canal PRINCIPAL; Tally vira reserva
           🌐 Ficha ONLINE (túnel Cloudflare) com SENHA — princípio "nunca expor sem senha"
           🔒 Link da câmera é SÓ-FICHA (não vê gestão nem edita ficha alheia)
           📷 QR da ficha na tela de Acompanhamento (auto-detecta a URL do Cloudflare)
           🔶 REPORTADO ao C5: cada trabalho = um novo projeto de sistema
           📋 DESENHO: mural dos câmeras (2º monitor, status em linguagem de set)
           💾 Versão salva no git (1ª foto do sistema inteiro) + README próprio do GMA

14/06  S24 📐 DESENHO: Passo 2 do Matcher — botão de resolução de empate
           🔶 DECISÃO: operador vê nome + câmera + 3–4 primeiros nomes de arquivo
              → clica "Confirmar" → tela de resumo (nome · câmera · nº arq · destino previsto)
              → "Iniciar transferência" registra match, descarta candidatos, dispara cópia
           🔶 DECISÃO: candidatos descartados ficam com status 'descartado' na tabela
              match_candidatos (auditável); fichas voltam a aguardando_match
           🔶 DECISÃO: confirmação chama atualizar_perfil (perfil acumula assinatura)
           📄 Referência: desenho_passo2_matcher_GMA.md · Status: aprovado, NÃO implementado
           ⏭️ Build: agente checkin-gma + banco-dados-gma (sem bloqueios)

12/06  S21+ 🐛 Teste pós-commit pegou um cartão ARRI só de CONFIGURAÇÃO (0 mídia)
              passando reto pelo fluxo → 2 falhas: Porteiro decidia a marca só pelo
              nome da pasta; Leitor via "sem mídia" mas deixava seguir.
           🔧 CORREÇÃO (Camada 1): quando o cartão tem 0 mídia, o Leitor classifica
              em DOIS níveis — 'sem_midia' (config/lixo → ignora, não copia) e
              'revisar' (tem arquivo grande não reconhecido → chama o operador).
           🛡️ A lista EXTENSOES é a guardiã; em dúvida prefere 'revisar' a pular footage.
              ⚠️ mudanças ainda NÃO commitadas (leitor_midia.py, flask_gma.py)

14/06  S25 🛠️ BUILD do Passo 2 do Matcher (resolução de empate no painel)
           🐛 Teste ponta a ponta pegou 2 bugs que os autotestes dos agentes não viram:
              Flask 500 (variável html sombreava o módulo) + Matcher não gravava candidatos
           ✅ Corrigidos; botão "Confirmar" funcionando no painel

15/06  S26 🧪 TESTE ponta a ponta do Passo 2 com o sistema INTEIRO no ar → APROVADO ✅
              empate JOAO×PAULO: operador confirma JOAO → match manual gravado,
              PAULO descartado e devolvido à fila, cartão segue pra Camada 2
           🐛 O produto estava certo; o SCRIPT de teste precisou de 3 ajustes pelo
              descompasso "cartão forjado × processos vigias rodando":
              (1) material marcado como já analisado p/ o Leitor não rebaixar o volume falso;
              (2) modo --verificar com len>=4 (remontava o cenário e apagava o match);
              (3) verificador aceita "matched ou além" (Camada 2 avança o status)
           🔶 NOTA: cada profissional cadastrado ganha uma LETRA (A,B,C…) p/ as câmeras
              de identificação — pista visual, NUNCA autoridade de identidade
              (a "câmera B" do set pode não ser a B). Em desenho_nova_ficha_v2 §5.1
           🔶 NOTA (sessão 28): a aba "Profissionais" é, na verdade, uma FONTE DE
              MATERIAL — quase sempre uma pessoa, mas pode ser um feed/sistema (PGM,
              online), gerido pelo operador. A origem (cartão × pasta satélite/link)
              mora no cadastro mas funciona no check-in. Em desenho_nova_ficha_v2 §12
           💾 Commitado (sessão 26): teste + nota da ficha
           💾 Commitado (sessão 28): Fatia 3 + ativar/desativar/excluir profissional + §12

15/06  S29 🛠️ BUILD Fatia 4 — a CÂMERA saiu da ficha e foi pro cadastro do profissional
           🔶 DECISÃO (já era da S23): câmera não se pergunta mais na ficha; mora no
              cadastro (coluna `camera` em profissionais) — sai de CAMPOS_OBRIGATORIOS
           🔗 Matcher: o critério +3 agora lê a câmera do cadastro pelo nome da ficha
              (cai de volta pra câmera da ficha se não houver cadastro — preserva o Tally)
           🖥️ Aba Profissionais: coluna Câmera com edição inline + campo no cadastro
           🧪 Testado: JOÃO/Sony cadastrado → cartão Sony → +3 SEM campo na ficha ✅
           🐛 Bug pego no teste do idealizador: ao excluir um profissional do MEIO, a letra
              colidia (era por COUNT) e travava qualquer cadastro novo dizendo "nome já existe"
           🔧 _proxima_letra passou a usar a MAIOR letra já dada; letra de quem sai fica
              queimada (não volta) — todo cadastro novo recebe a próxima letra
           💾 Sem commit ainda (a critério do idealizador)

15/06  S30 🛠️ BUILD Fatia 5 (a ÚLTIMA) — a ficha passa a GRAVAR a forma nova de verdade
           🗄️ formularios ganha booleanos tem_foto/tem_audio/tem_video + nome_audio
              (antes o multi-tipo e o 2º nome viajavam em hidden e o backend ignorava)
           🔗 Matcher entende multi-tipo no +1 (predominante do cartão ∈ tipos marcados)
           🖥️ Planilha e fichas recentes exibem multi-tipo (Foto · Vídeo) e o 2º nome (áudio)
           🔶 REGRA: ÁUDIO é SEMPRE transferência à parte (vem em outro cartão). A ficha
              mista vira DUAS fichas ligadas por entrega_id (foto/vídeo + áudio) → cada uma
              com match/linha/transferência próprios. Os 2 nomes na tela = só facilitar a entrada
           🔶 ADIADO p/ Camada 2: foto+vídeo do mesmo profissional na estrutura de PASTAS
           🧪 Testado ponta a ponta: Foto+Áudio → 2 fichas; Foto+Vídeo → 1; só Áudio → 1 ✅
           🎉 Nova Ficha v2 COMPLETA (Fatias 1-5)
           💾 Sem commit ainda (a critério do idealizador)

15/06  S31 📊 DESENHO da Planilha de Entrega — a partir da "Loggagem" (RIO2C) + 5 planilhas
              antigas. Núcleo: BLOCO POR PROFISSIONAL com cartão sequencial (= o NOME_NNN do GMA).
              4 blocos: identificação · classificação · técnicas (o sistema gera) · futuro.
           🔶 DECISÃO: a CLASSIFICAÇÃO (palco/marca/pauta/tags) é preenchida pelo PROFISSIONAL
              na ficha, por chips de listas prontas; operador revisa opcional. Ficha objetiva.
           🔶 DECISÃO: listas de contexto DINÂMICAS, geridas só pelo operador; numeração
              NOME_NNN independente e contínua (a ficha muda de um dia pro outro, o nº não).
           🔶 DECISÃO: bloco de PÓS (editor/edição/upload) incluído, mas VARIÁVEL por evento —
              editores preenchem após a entrega; blocos/colunas ligam-desligam por evento.
           🔶 DECISÃO (IA): Missão A (busca conversacional) + transcrição de áudio LOCAL
              (Whisper, offline/grátis) primeiro; análise de imagem (Missão B) por último.
           🛠️ BUILD Fatia 1: aba "Listas" no painel (tabela listas_contexto + add/ativar/excluir,
              só na base). Testado ponta a ponta. Sem commit.
           🔶 ALINHAMENTO (no papel): Central de Entrada — 2 modos para a MESMA lista:
              (a) ao vivo (aba Listas) · (b) importar fontes (colar/CSV/PDF/print-OCR) →
              Extração → Revisão do operador (gate) → listas_contexto. Nada entra cru.
           ⏭️ A fazer: a "ponte" chips→ficha→planilha (faz tudo aparecer); depois a importação.
           💾 Sem commit ainda (a critério do idealizador)

15/06  S32 🧩 BUILD da ponte chips→ficha→planilha (tabela formularios_chips N-N) —
              chips clicáveis na ficha (vocabulário fechado) → 5 colunas na planilha
           📊 Google Sheets REAL NO AR — via IMPERSONAÇÃO de conta de serviço (sem chave):
              a org bloqueia chaves JSON e o OAuth do gcloud → token curto sob demanda
           🔑 SA gma-exportador + roles/serviceAccountTokenCreator p/ ale@serafa.me
           ⚠️ roda com /usr/bin/python3 (3.9, tem gspread); o python@3.14 do gcloud NÃO tem

15/06  S33 🛠️ BUILD GRUPOS EDITÁVEIS de classificação (peça grande, Camada 3)
           🔶 PRINCÍPIO: 1 PONTO DE CRIAÇÃO — criar um grupo → vira chip na ficha E
              coluna na planilha. Os grupos deixaram de ser fixos no código e viraram DADOS
           🧩 Fatia 1: tabela grupos_classificacao · Fatia 2: ficha lê do banco ·
              Fatia 3: painel de grupos na aba "Listas" · Fatia 4: planilha gera as colunas
           ➕ 2 modos por grupo: "escolhe da lista" (chips) e "escreve na hora" (texto livre)
           📱 Nova Ficha: multi-seleção em todos os grupos · data assume Hoje ·
              "quem está preenchendo?" · campos antigos aposentados
           🗄️ Molde da Planilha (liga/desliga colunas e blocos) · fundação do Log (eventos)
           💾 Tudo commitado (branch melhoria/readme)

15/06  S34 📊 BUILD Sheets DINÂMICO — o exportador deixou de ter 26 colunas FIXAS
           🔶 MONTADOR COMPARTILHADO em banco_dados.py (montar_planilha) = fonte ÚNICA das
              colunas/valores p/ a /planilha local E o Google Sheets — nunca mais divergem
           ➕ "POST IN" na planilha: fichas recebidas sem cartão já aparecem (material a caminho)
           🔶 Multi-projeto virou Camada 5 (Painel de Controle, troca ao vivo) — não aqui

16/06  S35 🔌 Exportador integrado ao sistema completo (loop contínuo de 60s)
           🐛 Raiz: o sistema usava sys.executable (python@3.14 sem libs) → PYTHON fixado
              em /usr/bin/python3 (3.9). 6/6 processos sobem; Sheets atualiza no 1º ciclo
           💾 Commitado

17/06  S36 🎪 BUILD Projeto-festival "Rock in Rio (teste)" + banco POR PROJETO (GMA_DB)
           🌱 Seed: 28 profissionais + grupos do festival (palco/show/lugares/momentos/marcas)
           📅 PROGRAMAÇÃO DO DIA (a "virada das fichas"): a ficha é UMA SÓ; só o grupo SHOW
              troca conforme o DIA ATIVO. Line-up real (155 shows) lido do site com o MCP do Chrome
           🔗 Cascata palco→shows-do-dia · palco virou múltipla (soma os shows) · Fatia B2 (add show)
           💾 Sem commit (lab intocado, backup em gma.db.bak)

18/06  S37 🎛️ BUILD PAINEL DE CONTROLE (Camada 5, Fatia 1) — o "cockpit"
           🔶 Ideia: "ligar os motores e testá-los antes de decolar". Não empacota o .app ainda;
              constrói o Painel como aba web no Flask atual (incremental e seguro)
           ⚙ painel_config.py (novo) = fonte única do "qual projeto + quais conexões"
           🎚️ Maestro virou SUPERVISOR: vigia .gma_reiniciar / .gma_encerrar → troca de projeto
              com reinício guiado dos 6 processos. Testado de verdade (boot→reinício→encerrar)
           🔌 Cockpit de conexões com botão "Testar" (destino escreve, Sheets gera token real,
              túnel checa o 127.0.0.1:4040) · atalhos clicáveis "Iniciar/Encerrar GMA.command"
           🐛 Isolamento: filas/contadores JSON viraram POR-PROJETO (eram globais) → Operação isolada
           💾 Sem commit

18/06  S38 🔗 BUILD MATCH MANUAL — o "último recurso" do operador
           🔶 Dor: um cartão entrou como "detectado" e nada pontuou (score<3) → virou ÓRFÃO
              sem nenhuma forma de dar match na mão. registrar_match_manual resolve o par direto
           🖥️ Operação ganhou seletor de rádio (1 cartão + 1 Post → botão MATCH dispara a cópia)
           🛡️ GATE DOS CARTÕES (falha grave do "cartão-fantasma"): o EOS foi removido fisicamente,
              mas nada o invalidou → o Matcher casou com o fantasma → "copiando eterno".
              Blindagem em 3 camadas: Porteiro invalida volume removido · Matcher confere existência ·
              Transferência falha limpo e sincroniza o banco
           🗂️ Cancelar/restaurar Posts (soft-delete em aba separada) · Descartar cartão · Planilha filtrada
           ⚡ Acompanhamento AO VIVO: reload de 8s → poll de 1s só do quadro (sem flicker)
           🐛 Contaminação entre projetos achada: a ficha remota grava no projeto ATIVO, não no
              destino → AMARRAR A FICHA AO PROJETO é o #2 aprovado (Fatia 2, pausado)
           ✅ Terminologia "casamento" eliminada do projeto (.py) — termo único: "match"
           💾 Sem commit (S37+S38 pendentes na branch fatia5-sheets-multiprojeto)

19/06  S39 🧪 TESTE de cópia real (GoPro HERO7, 107 arq / 7,7 GB) ponta a ponta no projeto SP2B
              1ª cópia FALHOU na auditoria (cartão desconectou 1 instante → 2 arquivos com erro)
              → o sistema agiu CERTO: reprovou e NÃO liberou o cartão. 2ª cópia OK (106/106)
           🐛 C4 travou em loop "108 vs 106": 2 .DS_Store do Finder (ignore-list só cobria
              .sppo/.pdf). Removidos → ciclo fechou (check OK + erase OK → CONCLUIDO)
           🔶 LIÇÃO (vira redesenho): a contagem tropeçou em 3 não-mídias diferentes
              (.fseventsd do cartão · .DS_Store do macOS · .sppo/.pdf do GMA) → falta UMA
              REGRA ÚNICA do que é "mídia real". Redesenho C2/C4 + benchmark em desenho
           🛠️ #1 BUILD: Google Sheets POR PROJETO no exportador — cada projeto na SUA planilha
              (resolução dinâmica do alvo); projeto real sem planilha PAUSA (não vaza pro global)
           🛠️ #2 BUILD PROXY (Fatias A+B): Leitor classifica .LRV (proxy→clipe) e .GPR (RAW→foto)
              🔶 VIRADA: a ideia de "pular o proxy" foi DESCARTADA (pular fere o princípio nº2 —
                 a C4 liberaria o Parashoot apagar material não copiado). Nova regra: SEMPRE
                 copia + marca (tipo/proxy_de no .sppo+banco) + AVISA. Política de 3 modos adiada
              🎞️ Proxy NÃO vira vídeo próprio (não duplica a entrega) MAS é a fonte preferida
                 dos frames (leve/compatível — poupa o destino); sem proxy, extrai do original
           🛠️ #3 BUILD: EXCLUIR Post definitivo (hard delete + cascade; desvincula o Log em vez
              de apagar; guarda recusa Post com match real). Cancelar/restaurar já eram da s38
           🛠️ #4 BUILD: DATA DE LOGAGEM pelo relógio do SISTEMA (a GoPro com relógio de 2016
              mostrava "Concluído 01/01/2016") — usa timestamp da transferência, nunca o mtime
           🛠️ #5 BUILD: NOMES CURTOS editáveis (nome_raiz=pasta do dia, nome_curto=cartão;
              palpite automático + edição manual com TRAVA após 1º cartão; ASCII sem acento;
              planilha ganhou colunas "Nome"+"Cartão") — PR #9, mergeado
           🛠️ BUILD: CENTRO DE CONTROLE DOS POSTS na Nova Ficha — tabela "Fichas recentes" virou
              grupos recolhíveis por status (editar/cancelar/restaurar/excluir); Operação = só o MATCH
           💾 Commitado (branch s39-sheets-por-projeto): #1, proxy A/B, #3, #4 · #5 (PR #9)

20/06  S40 🧱 BUILD RÉGUA ÚNICA do que é "mídia real" — uma função compartilhada (ler_cartao)
              usada pela C2 (copiar) e C4 (auditar); origem e destino contam igual → fim do
              "108 vs 106" da s39 (lixo do SO/cartão/GMA + download). PR #10 mergeado
           📁 BUILD caixa de PASTA DE RECEBIDOS no Painel (1ª fatia do arco satélite): config +
              Testar com detecção do Drive "só na nuvem". Arco satélite inteiro DESENHADO (memória)
           🔶 DESENHO satélite: ficha "Cartão físico?" → recebidos/<post> por Drive/Dropbox →
              gatilho do operador (depois estabilidade/aviso remoto) → cópia → C4 sem Parashoot
21/06  S40 🔒 BUILD TRAVA de instância única do maestro (flock) — clicar "Iniciar" 2x não
              duplica mais (achado ao vivo: 2 maestros, o 2º pendurado no prompt). PR #12
           🔌 BUILD NGROK AUTOMÁTICO — o maestro sobe o túnel junto com o sistema (7º processo
              opcional; verifica no 4040; falha graciosa offline). Validado ao vivo. PR #12
           🎓 Esclarecido: "ativo" do túnel é só intenção; offline o túnel é opcional (rede local)
           🧹 LIÇÃO de git: não deixar o disco num branch-surpresa enquanto ele roda ao vivo
              (a caixa "sumiu" da tela por isso) → tudo consolidado no main ao fim (memória)
           💾 PRs #10/#11/#12 mergeados no main; disco no main, working tree limpo

21/06  S41 📁 BUILD arco RECEBIDOS avança 2 fatias (Camada 1):
              • Fatia 1: pergunta de ORIGEM no Post ("Como o material chega?" Cartão físico ×
                Pasta recebida), logo abaixo do Tipo de material. Campo origem_material; padrão Cartão
              • Fatia 2-3: ao salvar Post satélite cria recebidos/<post>/ local (não quebra o Post se
                o caminho falhar) · LINK por Post (operador cola; aparece no acesso EXTERNO) · GATILHO
                do operador "pronto para copiar" (só MARCA — cópia C2 é a próxima fatia)
           🔶 DECISÕES do link: direção A (o SISTEMA oferece o link) + 1 pasta/link POR POST
           🛡️ BUILD MAESTRO robusto (achado caçando o bug "maestro não está rodando"):
              • BLINDAGEM: troca de projeto não derruba mais o maestro (cada etapa em try/except;
                se a subida falha, processos={} e o maestro SEGUE de pé)
              • ESPERA DA PORTA: a CAUSA RAIZ — na troca o Flask não subia ("Address already in use"
                porque a 5050 não tinha liberado) → agora o maestro espera a porta liberar + 2ª tentativa
              • AUTO-RECARREGAMENTO do painel: a tela de "Trocando…" espera o Flask cair e voltar e
                recarrega sozinha → fim da página enganosa que parecia dizer "maestro não rodando"
           🔶 RUMO APROVADO: SAGUÃO DE 2 NÍVEIS (nível 1 escolhe/cria projeto e nunca cai × nível 2
              sessão do projeto; trocar = volta ao saguão sem reiniciar). Substitui o reinício-na-troca;
              a blindagem de hoje é o 1º tijolo. Próxima sessão dedicada (plataforma-gma). Ver memória
           💾 Sem commit (mudanças em flask_gma.py + inicializar_gma.py + banco_dados.py; testes em /tmp)

21/06  S42 🏛️ BUILD SAGUÃO DE 2 NÍVEIS (Camada 5) — o "térreo" que nunca cai
           🔶 Decisão: construir o saguão e ABANDONAR o "maestro robusto" da s41 (o saguão substitui
              aquele mecanismo de reinício-na-troca inteiro). As mudanças sem commit da s41 não foram
              apagadas, só deixaram de ser o caminho.
           🆕 saguao.py (NOVO) = servidorzinho próprio na PORTA FIXA 5055 (http.server, não um 2º Flask),
              que NUNCA cai. Lista os projetos + criar novo + qual roda agora.
           ▲ ENTRAR sobe a sessão do projeto (Flask 5050 + porteiro/leitor/etc., reusando
              inicializar_gma.subir_todos); ▼ VOLTAR AO SAGUÃO desce só a sessão — o térreo segue de pé
           🔒 Trava única própria (.gma_saguao.lock) · encerramento limpo por SIGTERM (desce a sessão junto)
              · abre o navegador sozinho (tty) · atalhos Iniciar/Encerrar repontados pro saguão
           🖥️ Painel do projeto ganhou "⬅ Voltar ao saguão"; "Trocar para este" (reinício frágil) saiu
           🧪 Testado ponta a ponta: Entrar laboratório → Flask 5050 sobe → Voltar → 5050 cai, saguão
              segue 200, nada vazou; trava recusa o 2º; SIGTERM desce tudo limpo
           💾 Sem commit

21/06  S43 📥 BUILD ARCO RECEBIDOS FECHADO (C2+C4) — pasta satélite vira entrega, sem cartão
           ❗ Dor: Post de material avulso (DANIEL PARDAL, 115 RAW) + "pronto para copiar" = nada
              aconteceu. Causa: arco tinha só as Fatias 1-3 (s41); o botão SÓ marcava, ninguém copiava.
           🔶 Decisão: dois passos (botão "pronto" marca × 2º botão "Copiar agora" dispara) + NÃO apagar
              (a pasta de origem é renomeada _COPIADO depois da cópia OK). Recebido NÃO passa pelo Matcher
              (a pasta já nasce amarrada ao Post pelo id no nome → entra já casado).
           📦 Fatia 4 (C2): "Copiar agora" cria o material casado, copia de RECEBIDOS/<slug>/ com MD5+.sppo+PDF
              igual a cartão; marca origem_material=recebido no banco (a bandeira que a C4 lê)
           ✂️ Fatia 5 (C4): audita contagem+tamanho normal mas PULA o Parashoot (não há cartão); cartão
              físico segue COM Parashoot (confirmado em teste)
           🧪 Testes verdes (copia 25 PASS · auditoria 3 OK); FALTA testar ao vivo com o Post 11 real (sp2b)
           💾 Commitado e MERGEADO no main

21/06  S44 🧠 ABERTA A CAMADA 6 (IA) — sessão de DESENHO + agente (sem código)
           🔶 O idealizador escolheu avançar a IA, mas pediu que eu entendesse PRIMEIRO como ele
              pensa a IA. Sessão inteira foi alinhar a visão e registrá-la fora do chat.
           🗺️ As 3 CAMADAS DE IA: (1ª) a IA MONTA O PROJETO — upload de referências + chat de
              esclarecimento → Posts/listas/grupos; operador AJUSTA depois (não aprova antes).
              (2ª) BUSCA CONVERSACIONAL p/ o editor (Missão A) — "qual arquivo tem tal cena/pessoa/
              contexto?", sugere takes; cruza classificação do Post + transcrição. (3ª) LEITURA DE
              IMAGEM (Missão B) — profundidade até o take/timecode = PODER DE VENDA.
           🎯 Tudo converge na PLANILHA + barra de busca conversacional (as camadas 2/3 enriquecem
              a planilha que já existe, não criam telas novas).
           🔶 DECISÕES: nuvem/API permitida nas camadas de IA pela QUALIDADE (só o ciclo crítico é
              offline-sagrado; mídia nunca sobe) · ordem de BUILD = transcrição (Whisper local, grátis)
              → Missão A → Missão B (a 3ª alimenta a 2ª) · COLUNAS da planilha = núcleo fixo na frente,
              classificação variável no FIM (senão os filtros do Sheets quebram no meio do evento)
           🆕 Criados desenho_camada6_IA_GMA.md + agente ia-gma (.claude/agents/)
           🔶 Pré-requisito levantado pelo idealizador: controle por DATA na aba Listas (grupo por dia,
              como os shows do Rock in Rio) — C1/C3, a 1ª camada vai preencher essa estrutura
           🧱 1º tijolo definido (NÃO construído): transcrição Whisper local → coluna fixa na planilha
           💾 Sem código (só os 2 documentos novos)

22/06  S45 🧱 BUILD 1º TIJOLO DA CAMADA 6 — transcrição de áudio (Whisper local) POR ARQUIVO
           🎯 Alinhamento: o tijolo é SÓ a transcrição crua (combustível); guiar qual arquivo
              usar é a Missão A (2ª camada), construída depois EM CIMA disso
           🔊 Motor faster-whisper LOCAL (small, PT) provado num áudio real (idêntico, offline/grátis);
              vive numa CAIXA ISOLADA .venv_ia/ (fora do Python do ciclo crítico e fora do git);
              o Flask chama transcritor.py (NOVO) como subprocesso
           🔶 DECISÃO DO IDEALIZADOR (a "troca"): POR ARQUIVO, não por card — célula por-card incharia
              a tabela/Sheets E a Missão A precisa apontar "qual arquivo/qual take". Transcrição mora
              em arquivos.transcricao (1 por áudio); coluna de cartoes removida (não commitada)
           📊 Planilha mostra só STATUS compacto ("N áudios transcrito(s)"); texto completo na tela
              leve /cartao/<id>/transcricao (um bloco por arquivo) — é o que a Missão A vai pesquisar
           🧱 Aplicada a reorder de blocos da s44: classificação variável foi pro FIM (núcleo fixo
              na frente, incl. Transcrição) — filtros do Sheets não quebram no meio do evento
           🖥️ Botão 🎙 Transcrever só em cartão de ÁUDIO já copiado; roda em background (thread)
           🧪 12 testes (teste_transcricao.py) + integração via test client; exportador herda a coluna
              pela fonte única. Escopo: só áudio (trilha de vídeo = fatia futura)
           ⚠️ NÃO testado ao vivo no sistema rodando (precisa Encerrar+Iniciar → carrega código + migra)
           💾 Commitado no main (tijolo + papelada da s44)

22/06  S46 🔔 BUILD AVISO DE LOGIN DO GOOGLE NO PAINEL (C3+C5) — fim da falha silenciosa do Sheets
           ❗ Dor (achada na s43): a sessão do gcloud expira (política da org); o exportador roda
              não-interativo, não pode relogar, e falhava EM SILÊNCIO a cada minuto → o Sheet de TODOS
              os projetos travava e só se via pela planilha parada. O log sabia, a tela não.
           📨 C3: o exportador deixa um BILHETE de status (.gma_sheets_status.json, troca atômica) a cada
              ciclo: ok / login-vencido / sem-internet / pausado / nao-configurado / erro (+ horário + projeto).
              Detecção do "reauth" do gcloud (invalid_grant/auth login/token has expired) isolada dos erros
              genéricos (404/quota/rede). Falha de escrita nunca quebra o ciclo (a mídia já está segura).
           🚦 C5: o Painel lê o bilhete e a caixa do Google Sheets mostra bolinha VIVA — 🟢 "atualizado HH:MM"
              / 🔴 "Google precisa de login — gcloud auth login" / 🟡 "sem internet". Ignora bilhete de outro
              projeto (roda um por vez) ou velho >5min (exportador parado = não afirma nada).
           🔒 Offline-first intacto: copiar/MD5/auditar nunca dependeram do login; login vencido = material
              seguro, só o espelho pausa — agora COM aviso visível.
           🧪 teste_status_sheets.py (10 verdes): classificador, gravação atômica, tradução do Painel.
              NÃO testado ao vivo (precisa Encerrar+Iniciar; sem bilhete o Painel cai no comportamento antigo)
           💾 Commitado no main (cbbdb82). Resolve a pendência DEFERIDA na s43.
           🩺 INCIDENTE AO VIVO (mesma sessão) — "o Sheets não funciona": o bilhete NOVO flagrou na hora
              `erro: no such column: a.transcricao` (o recurso provou o valor na 1ª ocasião). Raiz: a
              migração da s45 (coluna `transcricao`) NUNCA rodou nos bancos dos projetos — as migrações
              vivem em inicializar_banco(), mas Flask/exportador abrem com obter_conexao() (não migra) e
              inicializar_banco só rodava oportunisticamente. montar_planilha (fonte única da /planilha E
              do Sheets) passou a exigir a.transcricao → quebrava p/ TODOS os projetos.
           🔧 Conserto imediato: rodei a migração (idempotente, só ADD COLUMN) nos 3 bancos → planilha do
              rock_in_rio confirmada ao vivo (--teste OK); bilhete voltou a 🟢 ok.
           🛡️ Conserto da RAIZ (bfbf186): o ENTRAR do saguão agora MIGRA o banco do projeto antes de subir
              os processos (saguao._migrar_banco_do_projeto) — elimina a classe inteira de "apagão silencioso
              da planilha" quando uma coluna nova entra. Vale no próximo Entrar.

22/06  S47 🔎 BUILD MISSÃO A — Fatia 1 (2ª camada de IA) + 3 consertos no teste ao vivo do áudio recebido
           🎯 Sessão: avançar a IA. Alinhamento — a "IA que analisa o evento" é a 1ª camada (montar o
              projeto); pela ordem de build (transcrição→Missão A→Missão B), o próximo natural era a Missão A
           🔎 Fatia 1 = a FUNDAÇÃO da busca, SEM IA/API: banco_dados.buscar_na_planilha faz busca textual
              mecânica (offline/grátis) cruzando transcrição + classificação + identificação; barra na
              /planilha destaca as linhas e aponta quais áudios bateram. NÃO mexe na fonte única (Sheets
              não muda) — é só filtro. Barra na planilha agora; tela de chat à parte no futuro (função já
              desacoplada p/ a Fatia 2/LLM). 20 testes; achou Volkswagen/Sunset/Péricles no banco real. (ia-gma)
           🩺 Conserto 1 — STATUS DO POST não saía da Operação/Nova Ficha: a auditoria concluía o cartão mas
              nunca avançava o Post (preso em matched). Nova concluir_formulario_do_cartao nos 2 pontos de
              conclusão (físico E recebido) + grupo "📦 Concluído/entregue" + backfill dos travados (8 testes)
           🩺 Conserto 2 — "Posts aguardando material" não esvaziava: a lista lê dos JSONs da fila e o RECEBIDO
              pula o Matcher que avançaria o JSON; filtro novo cruza pelo db_formulario_id e confia no banco
           🩺 Conserto 3 — "CALIFA + CALIFA" na planilha: a coluna Profissional juntava nome + nome_audio
              iguais; agora só junta quando diferem (Fernando mantém "+ CALIFA (áudio)")
           🩺 Conserto 4 (s46 reforçada) — Sheets caiu de novo (login gcloud venceu) e o bilhete mostrou "erro"
              em vez de "login vencido": a msg era cortada em 200 chars antes da marca de reauth; agora 500 +
              reconhece a falha do print-access-token (imediato: rodar gcloud auth login)
           🧪 TESTE AO VIVO do áudio CALIFA: "Copiar agora" OK (MD5/PDF/_COPIADO/auditoria sem Parashoot) MAS
              o cartão Sound Devices não tinha gravação — só metadados; transcrição rodou e achou 0 áudios
              (motor OK, falta áudio real). Pra provar a transcrição ponta a ponta = cartão com .wav de verdade
           🔶 PEDIDO: a transcrição deve ser AUTOMÁTICA (gatilho pós-cópia, vigia assíncrono) — próxima fatia C6
           💾 Commitado no main

22/06  S48 🤖 BUILD TRANSCRIÇÃO AUTOMÁTICA (Camada 6) — o vigia que transcreve sozinho, pós-cópia
           🎯 Sessão: o pedido aberto da s47. Até aqui a transcrição (s45) só rodava por um botão manual 🎙;
              agora roda sozinha. Construído como VIGIA, irmão do exportador do Sheets.
           🤖 vigia_transcricao.py (NOVO): laço a cada 60s que varre a fila de cartões de áudio
              copiados-e-não-transcritos e dispara a transcrição FORA do ciclo crítico; chama o transcritor.py
              na caixa .venv_ia como subprocesso (Whisper contido); nunca toca na mídia; 100% local/offline.
              Se a .venv_ia não existir, dorme em silêncio (recurso opcional). Modo --teste roda uma passada.
           🔖 CARIMBO anti-loop (decisão do idealizador: "carimbo no banco"): coluna nova
              cartoes.transcricao_tentada_em (migração não-destrutiva). O vigia carimba após cada tentativa →
              um cartão de áudio SEM fala (como o Sound Devices só-metadados da s47) é tentado UMA vez e sai
              da fila, sem repetir pra sempre. cartoes_pendentes_transcricao + marcar_/limpar (limpar=reprocessar)
           🔌 LIGADO ao inicializar_gma (subir/descer com a sessão, prefixo [TRANSCRICAO]); o botão manual 🎙
              também carimba ao terminar pra os dois caminhos não se atropelarem (reprocessar pelo botão segue valendo)
           🐛 BUG DE TESTE pego: o banco_dados fixa CAMINHO_BANCO no IMPORT (lê GMA_DB uma vez); a 1ª versão do
              teste importava o módulo ANTES de apontar pro banco de teste → escreveu cartões de teste no gma.db
              REAL. Limpei os 5 de teste (4 reais intactos: Untitled/JOE, SONY_CARD, GOPRO_TESTE, EOS_DIGITAL) e
              consertei o teste pra setar GMA_DB no topo. Lição: testes do GMA setam GMA_DB ANTES de importar banco
           🧪 12 testes verdes (teste_vigia_transcricao.py, com subprocess.run falso); teste_transcricao (s45) segue verde
           ✅ TESTADO AO VIVO (sp2b) — FUNCIONOU: reiniciou, o vigia subiu sozinho e, SEM clicar, transcreveu
              CALIFA_002 (6 áudios, .wav real ~2min) e CALIFA_003 (material novo); CALIFA_001 (só-metadados) tentou
              1× e carimbou (0 áudios, sem loop). Prova ponta a ponta do automático + do motor com .wav real (que faltava na s47)
           🔶 Esperado (não-bug): no 1º boot após a coluna entrar, todos os áudios já existentes são re-olhados 1×
           💾 Falta commitar (vigia_transcricao.py + banco_dados/inicializar_gma/flask_gma + teste novo)

22/06  S49 🧠 BUILD MISSÃO A — Fatia 2 (Camada 6): a BUSCA CONVERSACIONAL, o PRIMEIRO LLM do GMA
           🎯 Sessão: avançar a Missão A → o degrau com LLM. DECISÕES do idealizador: (1) motor = Claude API;
              (2) comportamento = tradutor + redator; (3) rodar em API SIMULADA agora, SEM criar custo — ele vai
              "estruturar o que falta" antes de ligar a chave; (4) PRÓXIMOS FOCOS = Camada 5 e Camada 7
           🧠 assistente_ia.py (NOVO): camada fina que põe um LLM por cima da Fatia 1 — TRADUZ a pergunta em
              linguagem natural em termos de busca (lendo o "cardápio" do evento) → roda buscar_na_planilha (a
              VERDADE, a IA nunca inventa arquivo) → REDIGE uma resposta apontando arquivos/takes. responder() orquestra
           🔀 3 ESTADOS: real (GMA_ANTHROPIC_KEY → chama o Claude) · SIMULADO (GMA_IA_SIMULADA=1, LLM falso em
              processo, custo ZERO, pra ver o fluxo antes de pagar) · desligado (cai na busca mecânica, SEM regressão).
              Honra os 3 princípios: degrada sem chave/net · só chama com pergunta + modelo barato · só TEXTO sobe, mídia NUNCA
           ⚙️ Motor na caixa isolada (igual ao Whisper): assistente_ia_motor.py (NOVO) roda na .venv_ia (biblioteca
              oficial da Anthropic), chamado como SUBPROCESSO — o Python do ciclo crítico nunca ganha a dependência.
              Modelo Claude Haiku 4.5 (rápido/barato), configurável por GMA_IA_MODELO; falha degrada sozinha
           🖥️ Barra "🤖 Perguntar" na /planilha (decisão s47: barra agora, chat à parte no futuro) + caixa de resposta
              com selo do estado ("modo simulado"); a barra mecânica antiga vira a opção "busca exata"
           🧪 17 testes verdes (teste_missao_a_ia.py: motor real trocado por falso + modo simulado de verdade, incl.
              SEGURANÇA — o caminho de mídia /Volumes/… NÃO vaza pra API). Fatia 1 segue 20/20. Integração via test
              client: GET /planilha?pergunta=… → HTTP 200, caixa do Assistente IA renderiza; desligado cai na barra antiga
           🔶 NÃO testado com chave real (custo adiado) nem ao vivo (precisa Encerrar+Iniciar). Pra ligar depois:
              chave no .env + .venv_ia/bin/pip install anthropic. Preview grátis: GMA_IA_SIMULADA=1 + reiniciar
           💾 Commitado no main (cb17f8f)

22/06  S50 🧹 "FECHAR O SAGUÃO" (Camada 5) — consolidar a fundação antes de empilhar multi-máquina/login
           🎯 Sessão: avançar a C5. Recomendei (e o idealizador topou) começar pela fundação — arrumar o saguão
              que ficou meio-construído na s42 — em vez do mais difícil (multi-máquina/.app). Fatia segura: não
              toca no ciclo crítico de cópia. Duas partes: limpeza do reinício antigo + feedback que faltava
           🧹 PARTE 1 — LIMPEZA do mecanismo de reinício ANTIGO (código morto que o saguão já substituiu):
              removidos SINAL_REINICIAR + o ramo .gma_reiniciar do laço do main() do maestro (inicializar_gma.py),
              as rotas /painel/trocar e /painel/reiniciar + o helper _maestro_rodando + o parâmetro recarregar/
              script da página "Trocando…" (flask_gma.py), e a instrução velha no ngrok_gma.sh. PRESERVADO o VIVO:
              .gma_encerrar (o saguão vigia), _painel_criar_sinal (botão Desligar), /painel/novo
           🐛 Achado pela VARREDURA (não pelo py_compile): limpar_sinais() ainda usava a constante removida →
              viraria NameError em runtime. Lição: remover símbolo exige varrer o projeto, não só compilar
           ⏳ PARTE 2 — FEEDBACK "subindo…" no saguão (saguao.py): antes o Entrar BLOQUEAVA alguns segundos
              (subir_todos espera o Flask responder) e a tela congelava sem sinal de vida. Agora o saguão sobe a
              sessão em SEGUNDO PLANO (thread) e responde NA HORA com uma tela de espera (spinner + "Subindo a
              sessão de <projeto>…") que faz poll de GET /entrando-status (JSON fase subindo/pronto/erro); pronto
              → redireciona pro Flask (5050); erro → mostra o aviso na tela com "Voltar ao saguão" (nunca tela morta).
              Entrar no projeto já rodando pula direto (303). Estado próprio (_entrada) separado do _trava_sessao
           🧪 4 arquivos compilam; zero referências órfãs no projeto; teste isolado (porta 5077, entrar_no_projeto
              FALSO pra não subir processos reais e colidir com o sistema vivo) passou nos 4 cenários
           🔶 NÃO testado ao vivo (precisa Encerrar+Iniciar pra ver a tela de "subindo…" de verdade)
           💾 Commitado no main. Próximo (rumo C5): login do operador · teste multi-máquina (2-3 cartões) · .app · ou Camada 7

22/06  S51 🔑 LOGIN DO OPERADOR (Camada 5) — a base ganhou identidade + barreira de acesso
           🎯 Sessão: avançar a C5 pelo login. DECISÕES do idealizador (via perguntas): (1) serve pra OS DOIS —
              identidade E barreira; (2) cada operador tem NOME + SENHA PRÓPRIA; (3) operadores GLOBAIS (equipe é
              a mesma de evento pra evento — cadastra uma vez, vale em todos os projetos). 2 fatias na mesma sessão
           🔑 FATIA 1 — A PORTA (operadores.py NOVO): armazém GLOBAL num arquivo na raiz (operadores.json, FORA
              do git — guarda senhas). Senha NUNCA em texto puro: hash pbkdf2_hmac(sha256) + sal por operador +
              200k iterações (biblioteca padrão, nada instalado); conferência em tempo constante. Barreira: passo
              1.5 no _portao_de_acesso exige operador logado na BASE (Painel/Kanban/Planilha/match/listas); o
              remoto/câmera NÃO muda (já limitado a /ficha). À prova de tranca: sem operador, /login vira bootstrap
              (cria o 1º). Telas /login·/logout·/operadores (travas: não desativa a si mesmo nem o último ativo).
              Sessão assinada por .gma_secret estável (fora do git) → login sobrevive a reinícios
           🏷️ FATIA 2 — O CARIMBO (banco_dados.py): coluna nova eventos.operador (migra no Entrar); registrar_evento
              ganhou um contexto por-requisição (threading.local) que o Flask preenche a cada request → TODA ação na
              base sai carimbada com quem fez, sem passar o operador por cada chamada; ação automática = NULL =
              "sistema". "Quem preencheu" do Post puxa do operador logado. Nova tela /historico (quando·quem·o quê)
           🧪 teste_login_operadores.py (27 checagens, incl. remoto nunca vê o login) + teste_carimbo_operador.py
              (13, incl. migração de banco antigo) + suíte existente toda verde (imports novos não quebraram nada)
           🩺 INCIDENTE "não mudou" (resolvido, NÃO era bug): Encerrar/Iniciar não trocava o código porque o login
              vive no Flask do projeto, que só renasce ao ENTRAR (subir a sessão); clicar "Iniciar" com o saguão já
              no ar NÃO reinicia (a trava .gma_saguao.lock só reabre o navegador no velho), e Entrar no projeto
              já-rodando é no-op. REGRA: mudou flask_gma/banco_dados → Voltar ao saguão + Entrar (Flask novo); mudou
              saguao.py → Encerrar + Iniciar (esperando o Encerrar TERMINAR antes do Iniciar). Ação: derrubei o
              saguão velho (SIGTERM limpo) + removi travas órfãs (.gma_maestro.lock de ontem, .gma_saguao.lock) →
              estado 100% limpo (portas 5050/5055 livres). Memória recarregar-codigo-ao-vivo
           💾 Commitado E PUSH no main. Próximo (rumo C5): teste multi-máquina (2-3 cartões) · empacotar .app · ou Camada 7

24/06  S53 🎨 CAMADA 7 INICIADA — a marca do 6floor (identidade, SEM código)
           🎯 Sessão de design escolhida pelo idealizador. Conversa longa de marca com vários rascunhos
           🏷️ NOME: 6floor ✅ (minúsculas) — o "6" = a IA mora no 6º andar; pra fora soa estrutura/prédio
           🔤 FONTE: Space Grotesk (escolha dele, após comparar Plex Mono/Archivo/Sora/JetBrains); "l" reto
              mantido (eu recomendei uma mono pra resolver o l↔1, ele preferiu a Space Grotesk pela cara)
           🎨 ACENTO: teal (#2BB58C) — "sala de controle", calmo e atemporal
           ♾️ SÍMBOLO: os dois "o" de floor viram um ∞ monoline (estilo da fonte); "olhar/vigilância" nas
              entrelinhas (pupilas literais abandonadas); ESTADO VIVO = cometa percorre o infinito = STATUS
           🚫 Rejeitados: laço cruzado "fita" (destoava da tipografia) e anéis lado a lado (não liam ∞)
           🖥️ MUNDO: ferramenta séria de logagem/DIT moderna (Hedge/Silverstack + Frame.io); ícone até 16px

24/06  S54 ♾️ CAMADA 7 — glifo do símbolo + animação FECHADOS e SALVOS em arquivo
           🔎 Abriu com um achado: o idealizador mostrou uma imagem da marca "de outra sessão" e perguntou
              se eu mudei algo → os rascunhos da s53 nunca viraram arquivo (evaporaram) e a imagem era um
              caminho REJEITADO (anéis lado a lado). Virou o objetivo: fechar o glifo E salvar no disco.
           ♾️ GLIFO: infinito CRUZADO monoline, espessura MÉDIA (afina pra precisão mas sobrevive no 16px)
           🎬 TRABALHANDO: "forma e dissolve" — o laço se desenha, fica inteiro aceso um instante e dissolve
              (lento/espacial). Antes testei "dados correndo" → ele achou DEMAIS → pediu calmo/espacial
           🚫 Descartadas (s54): fluxo de pontos · pacotes · varredura (trânsito demais); órbita/respiro
           💾 SALVO: marca/6floor_simbolo.svg · _trabalhando.svg · _lockup.svg + desenho_camada7_marca_GMA.md
              = fonte de verdade da C7 (a marca para de evaporar entre sessões)
           🎨 PALETA COMPLETA (mesma s54): teal único acento + 4 fundos sala-de-controle + borda/3 textos +
              estados só-alerta (ok=teal, âmbar, vermelho); marca/6floor_paleta.css. Idealizador aprovou de primeira
           🔶 Falta: ícone do app real · grid · aplicar nas telas · lockup em contornos

24/06  S55 🖥️ CAMADA 7 — a marca 6floor APLICADA NAS TELAS (Fatia 1: porta de entrada + Kanban full-dark)
           🧱 Fundação no Flask: MARCA_VARS (:root da paleta) + Space Grotesk + ∞ inline; login + cabeçalho/abas
              repintados pro mundo escuro (aba ativa teal); KANBAN full-dark escopado por tela (body.pag-kanban)
           ✅ Verificado por screenshot (preview isolado); demais telas seguem claras até a sua fatia

24/06  S56 ♾️→oo CAMADA 7 — glifo AFINADO (∞ cruzado → dois "o" encostados) + lockup FLUIDO na palavra
           🎯 Pedido: afinar a logo, dar mais UNIDADE com a fonte — o ∞ nascer da palavra, não ser avulso
           🔎 Diagnóstico: o glifo da s54 destoava em peso (7 vs ~8), largura (esticado) e assento (flutuava)
           🆕 Escolha dele (iterado na tela): "menos infinito ainda" → DOIS "o" ENCOSTADOS (tangentes, ∞ sugerido)
              traço casado com a haste (razão ≈ 0,22), assentado na x-height, cada laço do tamanho de um "o"
           🔤 LOCKUP FLUIDO: "6fl" e "r" abraçam o símbolo com o respiro das letras — "6floor" lê como UMA palavra
           🎬 "forma e dissolve" no glifo novo: traço contínuo contorna um "o" e depois o outro (aprovado: "ficou bom")
           💾 Novo path canônico (2 círculos tangentes ±100×±50) nos 3 SVGs + doc da C7
           🔁 2ª parte: "nome COM o símbolo em todo lugar, sem logo+6floor" → _marca_lockup virou o WORDMARK "6fl∞r"
              (login + cabeçalho). SAGA: empilhava ("6fl"/∞/"r") por causa do reset svg{display:block} (não era largura);
              fechado como UMA imagem <svg> (texto+glifo+texto juntos, textLength p/ largura estável) — impossível empilhar
           ♾️ Opção SÓ-∞ criada (_marca_icone): a marca sem a palavra (favicon/recolhido); onde aplicar fica p/ depois
           🛠️ Nota: a prévia do chat mostra SVG PARADO (não toca CSS/SMIL) → ver animação abrindo o .svg no navegador
           ✅ py_compile OK + SVGs validam + wordmark é 1 svg só; NÃO testado ao vivo (precisa Voltar ao saguão + Entrar)
           🔶 Próximo (dito por ele): trabalhar com o agente p/ desenvolver as telas (full-dark tela a tela)
```

---

## 4. As regras de ouro (não se mexe mais)

| Regra | Por quê |
|---|---|
| 🐍 **Motor de cópia é o `copiador.py` (Python)**, não o ShotPutPro | O ShotPutPro não deixa ser automatizado — seria sempre um gargalo manual |
| 🛡️ **Material insubstituível nunca é apagado/movido sem conferir** | É a regra nº 1. Em dúvida, não destrói |
| ☁️ **Vídeo nunca sobe pra nuvem** — só informação sobre ele | Segurança + custo |
| 💰 **Sem IA no ciclo principal** — só no andar 6, opcional | Custo mínimo; o ciclo roda grátis e offline |
| ⚡ **Tudo funciona sem internet** | A nuvem só sincroniza depois |
| 🤖 **Autonomia máxima** — o operador é o último recurso | Sem filas no set |
| 🎙️ **Áudio é SEMPRE transferência à parte** | Vem em outro cartão (gravador); juntar áudio a vídeo na ficha é só conveniência de digitação — por baixo são match/linha/transferência separados |

---

## 5. O que pede atenção agora

Em ordem de impacto:

0a. 🚇 **TESTAR o túnel Cloudflare no set (s63)** — ngrok REMOVIDO; o **maestro sobe o cloudflared sozinho**
   (verificado ao vivo no maestro). Falta só o teste no set: (1) **Encerrar + Iniciar** (mexeu no maestro —
   não basta Voltar+Entrar), (2) conferir no log que aparece **"Tunel ATIVO: https://…trycloudflare.com"**,
   (3) **escanear o QR no celular** confirmando que cai DIRETO na ficha, sem tela cinza. Pré-requisito já OK:
   `cloudflared` instalado (2026.6.1). Fatia futura (opcional): **modo nomeado** do Cloudflare — subdomínio
   fixo por máquina (resolve a URL que muda a cada subida; precisa conta+domínio).
0. 🎙️ **Transcrição AUTOMÁTICA (pedido do idealizador, s47)** — hoje é botão manual 🎙; deve ser
   um **gatilho assíncrono pós-cópia** (um vigia, igual ao exportador, que pega cartões de áudio
   concluídos e não-transcritos e dispara sozinho, FORA do ciclo crítico). Próxima fatia da C6 (`ia-gma`).
   ⚠️ Para testar a transcrição ponta a ponta falta um **cartão de áudio com `.wav` de verdade** (o
   CALIFA testado na s47 só tinha metadados do gravador, 0 gravações). Depois: **Missão A Fatia 2 (LLM)**.
1. 🔗 **Amarrar a ficha ao projeto (#2, aprovado)** — a ficha remota (QR/ngrok) hoje grava
   no projeto ATIVO no momento do envio, não no destino do link → contaminou o laboratório
   com uma ficha do Rock in Rio (s38). É refactor de roteamento por-requisição (Camada 5,
   Fatia 2). PAUSADO a pedido do idealizador (vai confirmar/delegar aos agentes).
2. ✅ **Ciclo de vida do Post na "Nova Ficha" — FEITO (s39).** A divisão de abas foi implementada:
   Operação = só o MATCH; Nova Ficha = centro de controle dos Posts (grupos recolhíveis por status +
   editar/cancelar/restaurar/excluir). ⏭️ falta só: "reverter ENTREGA" (desfazer cartão já matched —
   hoje só pelo reset manual do teste) e garantir que TODAS as ações gravem no Log + rename "ficha"→"Post".
2b. ✅ **Régua única do que é mídia (s40 — CONSTRUÍDA, PR #10 mergeado)** — `ler_cartao.eh_nao_midia`/
   `eh_pasta_ignorada`, usada pela C2 (copiar) E pela C4 (auditar) → origem e destino contam igual;
   fecha o "108 vs 106" da s39. Desconhecido = copia + marca "revisar" (princípio nº 2). É a FUNDAÇÃO:
   FALTA por cima — C2 copia rápido (checksum durante a cópia) + auto-cura (recopia só o divergente) +
   benchmark sob demanda; frames travam a liberação (com opção de desligar).
2c. ✅ **Entrada por PASTA SATÉLITE (arco próprio — 5 fatias CONSTRUÍDAS)** — material que NÃO
   vem por cartão (fotógrafo foi embora; PGM/feed). ✅ Caixa "Pasta de recebidos" no Painel (s40, PR #11).
   ✅ **s41:** pergunta de ORIGEM no Post ("Como o material chega?") · pasta `recebidos/<post>/` local ao
   salvar Post satélite · LINK por Post (acesso externo) · GATILHO do operador "pronto para copiar" (só marca).
   ✅ **s43:** **a CÓPIA (C2)** — 2º botão "Copiar agora" cria o material já casado e copia de `RECEBIDOS/<slug>/`
   com MD5/.sppo/PDF (renomeia a origem `_COPIADO`); **a AUDITORIA (C4)** — contagem+tamanho e conclui, PULANDO
   o Parashoot. Link decidido: direção A (o sistema oferece) + 1 pasta/link por Post.
   ⏭️ FALTA: testar AO VIVO com o Post 11 real (Encerrar+Iniciar → "Copiar agora"); **OK remoto da cópia**
   (acionar pelo celular — pedido do idealizador, depende do binding ficha↔projeto #2); e (futuro) criar a
   subpasta na nuvem + link automático (API Drive/Dropbox). Ver [[pasta-satelite-recebidos]].
2e. ✅ **SAGUÃO DE 2 NÍVEIS (s42 — CONSTRUÍDO)** — `saguao.py` é o térreo na porta fixa 5055 que NUNCA
   cai; **Entrar** sobe a sessão do projeto (Flask 5050 + processos), **Voltar ao saguão** desce só ela.
   Substituiu o frágil reinício-na-troca (s41 "maestro robusto" abandonado). Trava única + SIGTERM limpo +
   atalhos repontados + "⬅ Voltar ao saguão" no Painel. ⏭️ FALTA por cima: feedback "subindo…" no saguão
   durante a subida; mostrar ngrok/erros da sessão; wizard de projeto novo; e **limpar de vez** o mecanismo
   antigo de reinício (`.gma_reiniciar`, laço do `main()` do maestro, rotas `/painel/trocar`+`/reiniciar`).
   Ver [[saguao-dois-niveis]].
2d. ✅ **Maestro robusto (s40 — CONSTRUÍDO, PR #12)** — (a) **TRAVA de instância única** (`flock` em
   `.gma_maestro.lock`): clicar "Iniciar" 2x não duplica mais o maestro (o 2º sai na hora). (b) **NGROK
   AUTOMÁTICO**: o maestro sobe o túnel como 7º processo opcional quando "ativo" + online (verifica no
   4040, falha graciosa offline; câmeras usam a rede local). Validado ao vivo. Manual só o setup 1x
   (instalar + authtoken) + domínio fixo opcional. Sem IA.
2f. ✅ **Aviso de login do Google no Painel (s46 — CONSTRUÍDO)** — o exportador (C3) deixa um "bilhete de
   status" (`.gma_sheets_status.json`) a cada ciclo (ok/login-vencido/sem-internet/pausado/erro) e o Painel
   (C5) mostra bolinha viva na caixa do Sheets: 🟢 "atualizado HH:MM" / 🔴 "Google precisa de login —
   `gcloud auth login`" / 🟡 "sem internet". Fim da falha silenciosa achada na s43 (parou ~21:50, só visto
   pela planilha parada). 10 testes verdes; falta só ativar ao vivo (Encerrar+Iniciar). ⏭️ FALTA por cima:
   ação do admin — esticar a sessão Google (admin.google.com → Segurança → Controle de sessão do Google
   Cloud) pra reduzir a frequência do relogin. Ver [[sheets-auth-impersonacao]].
3. 🎨 **Marca / identidade visual (andar 7)** — sem prazo de data + o relatório PDF de hoje
   ficou abaixo do esperado. Definir logo, paleta, tipografia e grid ANTES de refazer o PDF.
4. 📄 **PDF Overview** — refazer o gerador no estilo dashboard + folha de contato
   (briefing na §12 do `arquitetura_GMA.md`, material de teste já gerado), com o padrão do andar 7.
5. 🔌 **Ligar frames + PDF ao fluxo automático** — hoje o extrator de frames roda à mão
   depois da cópia; falta plugá-lo dentro da transferência.
6. 🧠 **Fase 2 do perfil** — fazer o sistema USAR o que aprende (câmera, prefixo, numeração)
   para desempatar sozinho. Tira o operador do caminho.
7. 🎛️ **Painel de Controle — Fatia 2 (conexões por-projeto)** — hoje as conexões (Sheets/senha/
   túnel) vêm do `.env` GLOBAL; mover p/ config por projeto + testar de verdade no setup +
   wizard de novo projeto. Fatia 3 = login/troca de usuário.
8. 🖥️ **Mural dos câmeras** (2º monitor) — tela read-only de status em linguagem de set + QR
   fixo (desenho pronto na sessão 21).
9. 📥 **Central de Entrada (importação)** — montar as listas a partir de planilha remota/CSV,
   colar texto, PDF e print (OCR). Desenho alinhado na s31; começar pela planilha/CSV.
10. 📊 **Agrupar a planilha por profissional** (modelo das planilhas antigas), não só por dia.

> ✅ Resolvido desde a S31: a **ponte chips→ficha→planilha** (s32), o **Google Sheets real**
> (s32, impersonação) e **dinâmico** (s34), os **grupos editáveis** (s33), o **multi-projeto**
> com banco isolado (s36) e o **Painel de Controle** (s37). A entrada não depende do Tally (S21).
>
> Pendências menores guardadas: bug do "0 arquivos no banco" (S7); consistência do banco
> quando dois cartões têm o mesmo nome de volume ("Untitled"); loop automático da auditoria.py
> ainda não exercitado em produção; renomear `produtora`→`nome` no Google Forms externo;
> ⚠️ exportador/Flask rodando adotam o código novo da s39 só após **Reiniciar pelo Painel**.

---

# PARTE TÉCNICA — os detalhes do mapa

> As seções acima são o "estou perdido, me situa". As de baixo são o detalhe
> de engenharia, para quando você quiser entrar a fundo.

## 6. Visão de cima — o fluxo em 3 zonas

```
┌─────────────────────────────────────────────────────────────────────┐
│  ZONA 1 — CAMPO / SET                                                 │
│                                                                       │
│   📷 Câmeras  ───►  💾 Cartão de memória  ───►  entregue na base      │
│                                                                       │
│   📱 Formulário (celular do operador)                                 │
│      nome do profissional · câmera · tipo · data de gravação          │
└───────────────────────────────┬─────────────────────────────────────┘
                                 │  (cartão físico + dados do form)
                                 ▼
┌─────────────────────────────────────────────────────────────────────┐
│  ZONA 2 — MÁQUINA GMA  (offline-first · ciclo crítico)               │
│                                                                       │
│   PORTEIRO ─► LEITOR ─► MATCHER ─► TRANSFERÊNCIA ─► FRAMES ─► PDF     │
│   detecta    analisa   material   copiador.py +     fotinhas  relat.  │
│   cartão     conteúdo  + form     checksum MD5      do vídeo          │
│                                                                       │
│                 ▼ tudo grava em ▼                                     │
│        ┌──────────────────────────────────────┐                      │
│        │  FONTE ÚNICA DE VERDADE               │                      │
│        │  SQLite local (gma.db)                │  ← Camada 3          │
│        │  (filas JSON ainda existem de backup) │                      │
│        └──────────────────────────────────────┘                      │
│                                                                       │
│   CAMADA 4 ✅ auditoria → Parashoot check → embaralha → ejeta        │
│             (e RESTAURA quando precisar — material nunca se perde)    │
└───────────────────────────────┬─────────────────────────────────────┘
                                 │  (SÓ metadados — nunca a mídia)
                                 ▼
┌─────────────────────────────────────────────────────────────────────┐
│  ZONA 3 — NUVEM / ENTREGA                                            │
│                                                                       │
│   📊 Google Sheets (espelho de entrega p/ editores) — ✅ NO AR (s32) │
│   📋 Notion (vitrine opcional — espelho do Kanban)                    │
│                                                                       │
│   ⚠️  Os arquivos de mídia NUNCA sobem. Ficam no HD físico.          │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 7. Os 3 pontos de acesso (telas) — UMA fonte, TRÊS vistas

```
                  ┌────────────────────────────────────┐
                  │   FONTE ÚNICA DE VERDADE            │
                  │   SQLite local (gma.db)             │
                  └───────┬───────────┬───────────┬─────┘
                          │           │           │
            ┌─────────────┘           │           └─────────────┐
            ▼                         ▼                         ▼
 ┌────────────────────┐  ┌─────────────────────────┐  ┌────────────────────┐
 │ ACESSO 1           │  │ ACESSO 2                │  │ ACESSO 3           │
 │ PAINEL DO OPERADOR │  │ QUADRO DE ACOMPANHAMENTO│  │ PLANILHA DE ANÁLISE│
 │ (Centro de Comando)│  │ (Kanban dos cartões)    │  │ (Entrega)          │
 ├────────────────────┤  ├─────────────────────────┤  ├────────────────────┤
 │ Para: OPERADOR     │  │ Para: operador + set    │  │ Para: EDITORES +   │
 │ (base + 2ª/3ª máq.)│  │ (equipes, read-only)    │  │ cliente            │
 ├────────────────────┤  ├─────────────────────────┤  ├────────────────────┤
 │ "O que faço agora? │  │ "Em que etapa está cada │  │ "Onde está o       │
 │  Algo travou?"     │  │  cartão? Já devolvo?"   │  │  material X?"      │
 ├────────────────────┤  ├─────────────────────────┤  ├────────────────────┤
 │ • Ativar/Desativar │  │ Colunas (o card anda):  │  │ Tabela filtrável:  │
 │ • Alertas:         │  │  Detectado →            │  │ • profissional     │
 │   – multidia       │  │  Match →                │  │ • câmera · tipo    │
 │   – órfão          │  │  Copiando →             │  │ • data · nº cartão │
 │   – checksum falhou│  │  Verificado ✅ →         │  │ • nº arquivos      │
 │ • Fila atual       │  │  Concluído              │  │ • tamanho          │
 │ • Status dos       │  │ + POST-ITS (observações │  │ • caminho no HD    │
 │   processos        │  │   livres por cartão)    │  │ • status verif.    │
 ├────────────────────┤  ├─────────────────────────┤  ├────────────────────┤
 │ ONDE VIVE:         │  │ ONDE VIVE:              │  │ ONDE VIVE:         │
 │ Flask local :5050  │  │ Flask local :5050       │  │ Google Sheets      │
 │ OFFLINE-FIRST      │  │ (read-only)             │  │ (nuvem)            │
 │                    │  │ + espelho Notion (opc.) │  │                    │
 ├────────────────────┤  ├─────────────────────────┤  ├────────────────────┤
 │ STATUS: no ar +    │  │ STATUS: no ar, AO VIVO  │  │ STATUS: no ar —    │
 │ ⚙Painel (cockpit)  │  │ (poll 1s, s38)          │  │ Google Sheets real │
 │ + Match manual     │  │ + post-it · Concluído   │  │ (s32) + DINÂMICO   │
 │ (s37-38)           │  │   agrupado por dia      │  │ (s34, espelha molde)│
 └────────────────────┘  └─────────────────────────┘  └────────────────────┘

  CRÍTICO / OFFLINE  ◄──────────────────────────────►  ENTREGA / NUVEM
```

**Regra de ouro das telas:** Acessos 1 e 2 são **operação** → offline-first, vivem
no Flask. Acesso 3 é **entrega** → nuvem (Google Sheets). O Notion é sempre só
vitrine espelhada, nunca o operacional.

**Novidades da sessão 21 (a entrada e o acesso remoto):**

- 📥 **Porta de entrada própria — "Nova Ficha"** (`/ficha`): uma aba a mais, servida pelo
  próprio Flask, que alimenta a mesma fonte única. Tem **gabarito** (nome/câmera se sugerem
  do histórico) e **edição** de fichas. É o **canal principal**; o Tally fica de reserva.
- 🔒 **Acesso remoto POR PAPEL** (régua de segurança): a operação completa só existe na
  **base** (localhost). Pela **internet/rede**, o **link da câmera** alcança **só a ficha nova**
  — não vê Kanban/Planilha, não edita ficha de ninguém, não mexe no Porteiro. Exige **senha**.
- 📷 **QR da ficha no Acesso 2:** a tela de Acompanhamento mostra o QR do link (auto-detecta a
  URL ativa do túnel Cloudflare). O operador aponta pros câmeras.
- 🖥️ **Mural dos câmeras (a desenhar):** a **metade read-only do Acesso 2**, para um **2º monitor**,
  com status em linguagem de set ("Material salvo ✅", "Copiando… não retire"). É a tela que
  comunica aos câmeras se o cartão deles já foi copiado.

**Novidades da sessão 31 (a Planilha de Entrega — Acesso 3 — toma forma):**

- 📊 **Planilha de Entrega = ficha do profissional + colunas técnicas do sistema**, em 4 blocos:
  **identificação** (data · nome/fonte · material F/A/V · nº cartão) · **classificação** (conteúdo ·
  tags · palco · marca · pauta — chips escolhidos na ficha) · **técnicas** (nº arquivos · tamanho ·
  íntegro? · status, que o sistema gera) · **futuro** (transcrição do áudio).
- 🧩 **Listas de contexto** (palco/marca/pauta/tags): vocabulário controlado, gerido pelo operador,
  dinâmico por evento. Os itens viram **chips na ficha**; nada entra na planilha sem essa ponte.
- 🧱 **Blocos variáveis por evento:** o operador "monta o molde" — classificação e pós-produção
  (editor/edição/upload, preenchida pelos editores) ligam-desligam conforme o trabalho.
- 📥 **Duas portas de entrada do vocabulário:** ao vivo (aba "Listas") + importação de fontes
  (planilha/CSV · colar · PDF · print-OCR), com revisão do operador antes de gravar.
- 🗂️ Referências reais: Notion "Loggagem" (RIO2C) + 5 planilhas Google antigas.

---

## 8. Organograma dos processos (Zona 2 em detalhe)

```
                        inicializar_gma.py
              (sobe tudo · SUPERVISOR desde a s37:
               vigia .gma_reiniciar / .gma_encerrar —
               troca de projeto com reinício guiado)
                                │
        ┌───────────┬───────────┼───────────┬────────────┐
        ▼           ▼           ▼           ▼            ▼
   ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌──────────┐ ┌───────────────┐
   │PORTEIRO │ │ LEITOR  │ │ MATCHER │ │  FLASK   │ │ TRANSFERÊNCIA │
   │porteiro │ │leitor_  │ │matcher  │ │flask_gma │ │transferencia  │
   │.py      │ │midia.py │ │.py      │ │.py       │ │.py            │
   ├─────────┤ ├─────────┤ ├─────────┤ ├──────────┤ ├───────────────┤
   │detecta  │ │analisa  │ │cruza    │ │recebe    │ │monta destino, │
   │volumes  │ │conteúdo,│ │material │ │Forms,    │ │chama copiador,│
   │novos    │ │multidia │ │+ form   │ │serve     │ │valida, frames,│
   │(2s)     │ │(3s)     │ │(score≥3)│ │painel    │ │gera PDF       │
   └────┬────┘ └────┬────┘ └────┬────┘ └────┬─────┘ └───────┬───────┘
        │           │           │           │               │
        └───────────┴───────────┴───────────┴───────────────┘
                                │
                                ▼
                    🗄️ SQLite (gma.db) — fonte única
                    (filas JSON mantidas como backup)
                                │
                                ▼
                    ┌───────────────────────┐
                    │  AUDITORIA (Camada 4) │  auditoria.py
                    │  detecta cartões       │
                    │  'transferencia_ok'    │
                    └───────────┬───────────┘
                                ▼
        pré-check (contagem+tamanho) → Parashoot check (arquivo a arquivo)
        ⚠️ s39: a contagem precisa de UMA regra única do que é "mídia real" (ignorar
           .fseventsd do cartão · .DS_Store do macOS · .sppo/.pdf do GMA) — em redesenho
                                │
                                ▼
        Parashoot erase → embaralha + ejeta → status CONCLUÍDO
                                │
                                ▼
        ↩️ Parashoot restore (quando precisar desfazer — material intacto)

   Na transferência:
   copiador.py (MOTOR) → cópia + checksum MD5 + gera .sppo
        └─ NOVO (s39): classifica cada arquivo (PROXY .LRV / RAW .GPR via ler_cartao),
           SEMPRE copia, marca proxy (tipo/proxy_de no .sppo+banco) e AVISA no log
        │
        ▼
   extrator_frames.py → 10 frames por vídeo + manifesto.json
        │
        ▼
   gma_relatorio_pdf.py → PDF rico (frames + metadados + auditoria)
   ⚠️ PDF a refazer (estilo Overview + padrão visual do andar 7)

   encerrar_gma.py  →  encerramento de emergência (desliga tudo)
   .gma_ativo       →  sentinela: existe = sistema processando

   NOVO (s37) — Camada 5 / cockpit:
   painel_config.py →  fonte única do "qual projeto + quais conexões"
                       (painel_estado.json · banco e destino por projeto)
   Iniciar/Encerrar GMA.command  →  atalhos clicáveis (semente do .app)
   GMA_DB · GMA_DESTINO          →  banco e pasta de destino por projeto (isolados)
```

---

## 9. Organograma de desenvolvimento (orquestrador + subagentes)

> Como o trabalho de CONSTRUÇÃO do sistema é dividido (não confundir com a operação).

```
                    ┌────────────────────────────┐
                    │  ORQUESTRADOR (Claude Code) │
                    │  visão geral · arquitetura · │
                    │  conversa com o idealizador │
                    │  cuida dos mapas e documentos│
                    └──────────────┬─────────────┘
                                   │ delega por camada
       ┌───────────────┬──────────┼──────────┬───────────────┐
       ▼               ▼          ▼          ▼               ▼
 ┌───────────┐  ┌──────────────┐ ┌────────┐ ┌─────────┐ ┌──────────────┐
 │checkin-gma│  │transferencia-│ │banco-  │ │auditoria│ │plataforma-gma│
 │ Camada 1  │  │gma           │ │dados-  │ │-gma     │ │ Camada 5     │
 │  ✅        │  │ Camada 2 ✅  │ │gma     │ │Camada 4 │ │  🔧          │
 │           │  │              │ │Camada3 │ │  ✅     │ │              │
 │leitura,   │  │copiador.py,  │ │✅quase │ │Parashoot│ │Painel/cockpit│
 │Forms,     │  │checksum MD5, │ │SQLite, │ │check/   │ │supervisor,   │
 │numeração, │  │.sppo, PDF,   │ │Sheets  │ │erase/   │ │por-projeto,  │
 │match      │  │GMA_DESTINO   │ │real+din│ │restore  │ │.app (futuro) │
 │manual     │  │              │ │,3 telas│ │         │ │              │
 └───────────┘  └──────────────┘ └────────┘ └─────────┘ └──────────────┘
   EXISTE         EXISTE          EXISTE     EXISTE ✅    EXISTE 🔧
   (testes / documentação = agentes futuros, ainda a criar)
```

**Onde as 3 telas entram no roadmap:**
- Acesso 1 (Operador): evolui do Flask atual — Camadas 1 → 5.
- Acesso 2 (Kanban): banco (C3) + tela (C5) + espelho Notion.
- Acesso 3 (Planilha): exportação para Google Sheets — Camada 3.

---

## 10. Legenda rápida

| Símbolo | Significado |
|---|---|
| ✅ | Concluído e testado |
| 🔧 | Em construção |
| 🔶 | Decisão grande (mudou a organização do projeto) |
| 🐛 | Bug conhecido a resolver |
| ⚠️ | Prazo ou risco a vigiar |
| ►  / ▼ | Fluxo de dados / dependência |
| Offline-first | Funciona sem internet; nuvem só sincroniza depois |
| Fonte única de verdade | Um banco alimenta todas as telas — nada diverge |

> Para a arquitetura completa e specs, ver `arquitetura_GMA.md`; para o estado e o histórico, `contexto_atual_GMA.md` e `historico_GMA.md`.
