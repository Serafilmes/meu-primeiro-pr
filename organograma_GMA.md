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
> Última atualização: 2026-06-21 (sessão 42 — SAGUÃO DE 2 NÍVEIS construído (Camada 5): novo `saguao.py` = o "térreo" do sistema, um servidorzinho próprio na porta fixa 5055 que NUNCA cai. Mostra a lista de projetos; **Entrar** sobe a sessão daquele projeto (Flask na 5050 + processos, reusando o motor do maestro); **Voltar ao saguão** desce SÓ a sessão e volta ao térreo (que continuou de pé) — fim do reinício frágil na troca de projeto. Trava de instância única própria (.gma_saguao.lock), encerramento limpo por SIGTERM, abre o navegador sozinho. Atalhos "Iniciar/Encerrar GMA" repontados pro saguão; Painel do projeto ganhou "⬅ Voltar ao saguão". Decisão: ABANDONAR o "maestro robusto" da s41 (o saguão o substitui); as mudanças sem commit da s41 não foram apagadas, só deixaram de ser o caminho. Testado ponta a ponta (subir/descer sessão real, trava, SIGTERM). Sem commit. — anterior s41 — ARCO RECEBIDOS avança + MAESTRO robusto: pergunta de ORIGEM no Post ("Como o material chega?" Cartão físico × Pasta recebida) · PASTA LOCAL por Post + LINK por Post (acesso externo) + GATILHO do operador ("pronto para copiar", só marca) · BLINDAGEM do maestro (troca de projeto não derruba mais o sistema) · ESPERA DA PORTA 5050 na subida do Flask (corrige o "sem tela" na troca: o Flask não subia porque a porta não tinha liberado) · AUTO-RECARREGAMENTO do painel (fim da página enganosa "maestro não rodando"). DECISÕES: link direção A (sistema oferece) + 1 pasta/link por Post; modelo SAGUÃO DE 2 NÍVEIS aprovado como rumo da C5 (substitui o reinício-na-troca; a blindagem de hoje é o 1º tijolo). Sem commit. — anterior s40 — 4 BUILDS mergeados no main: RÉGUA ÚNICA do que é mídia (função compartilhada C2+C4, fecha o "108 vs 106" da s39) · caixa de PASTA DE RECEBIDOS no Painel (1ª fatia do arco satélite: config + Testar com detecção do Drive "só na nuvem") · TRAVA de instância única do maestro (flock — clicar Iniciar 2x não duplica) · NGROK AUTOMÁTICO (o maestro sobe o túnel junto com o sistema, validado ao vivo). Arco satélite desenhado (memória pasta-satelite-recebidos); lição de git gravada (não deixar o disco num branch-surpresa). — anterior s39: TESTE de cópia real (GoPro 7,7GB) ponta a ponta no projeto SP2B; BUILD: Google Sheets POR PROJETO no exportador (#1), PROXY marcado na cópia (sempre copia + avisa — Fatias A/B), EXCLUIR Post definitivo (#3), DATA DE LOGAGEM pelo relógio do sistema (#4), NOMES CURTOS editáveis (#5: nome_raiz/nome_curto, pasta+cartão+planilha, ASCII), CENTRO DE CONTROLE DOS POSTS na Nova Ficha (grupos recolhíveis por status + cancelar/restaurar/excluir; Operação ficou só com o MATCH). Em desenho: redesenho C2/C4 com "regra única do que é mídia" + benchmark de velocidade. Antes: MATCH MANUAL + GATE DOS CARTÕES + Acompanhamento AO VIVO (s38), PAINEL DE CONTROLE / cockpit (s37), Rock in Rio + programação do dia (s36), Sheets real+dinâmico (s32/s34), grupos editáveis (s33).)

---

## 1. Onde estamos — o prédio de 7 andares

Pense no GMA como um prédio. Cada andar só faz sentido depois do anterior.
O coração do sistema (andares 1 e 2 — o trabalho mais difícil) está pronto e
testado com cartão de verdade.

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
        └─ falta: mural dos câmeras · login do operador (2.3) · domínio fixo do túnel
2 · Transferência (copiar com segurança)    ████████████  PRONTO ✅
        └─ s38: pasta de destino configurável (GMA_DESTINO) + falha limpa
           quando o volume some (acaba o "copiando eterno")
        └─ NOVO (s39): PROXY atravessa o pipeline — SEMPRE copia + marca (tipo/proxy_de
           no .sppo+banco) + AVISA; teste de cópia real GoPro 7,7GB OK (106/106)
        └─ NOVO (s40): RÉGUA ÚNICA do que é "mídia real" (compartilhada C2+C4 — fim do
           tropeço em .DS_Store/.fseventsd/.sppo); falta cópia rápida + auto-cura + benchmark
3 · Banco de dados (guardar tudo)           ███████████░  QUASE ✅
        └─ Kanban + Planilha + Google Sheets REAL no ar (s32, via impersonação)
        └─ GRUPOS EDITÁVEIS (s33): 1 ponto de criação → chip na ficha + coluna na
           planilha; Sheets DINÂMICO espelha o molde (s34); montador compartilhado
        └─ s38: GATE DOS CARTÕES (blindagem 3 camadas contra cartão-fantasma)
        └─ NOVO (s39): Google Sheets POR PROJETO no exportador (#1) — cada projeto
           escreve na SUA planilha; projeto real sem planilha PAUSA (não vaza pro global)
4 · Auditoria + devolver o cartão           ████████████  PRONTO ✅
        └─ embaralha · ejeta · RESTAURA pelo Parashoot — testado com cartão real
5 · Tela bonita + várias máquinas           ███░░░░░░░░░  EM CONSTRUÇÃO
        └─ NOVO (s37): PAINEL DE CONTROLE (cockpit no Flask) — troca de projeto com
           reinício guiado, conexões com Testar, ligar/encerrar por atalho clicável
        └─ projeto-festival Rock in Rio + programação do dia (s36); por-projeto isolado
        └─ NOVO (s40): caixa de PASTA DE RECEBIDOS (satélite) · TRAVA de instância única do
           maestro · NGROK AUTOMÁTICO (o túnel sobe junto com o sistema)
        └─ NOVO (s42): SAGUÃO DE 2 NÍVEIS CONSTRUÍDO ✅ (saguao.py) — térreo na porta 5055 que
           NUNCA cai; Entrar sobe a sessão do projeto (Flask 5050 + processos), Voltar ao saguão
           desce só ela. Fim do reinício frágil na troca. Atalhos repontados; "⬅ Voltar ao saguão"
           no Painel; trava única + SIGTERM limpo. (s41 "maestro robusto" ABANDONADO — o saguão o substitui)
        └─ falta: conexões por-projeto (Fatia 2) · login/usuário (Fatia 3) · .app · feedback "subindo…"
           no saguão + limpar de vez o mecanismo antigo de reinício
6 · Inteligência artificial (opcional)      ░░░░░░░░░░░░  futuro
7 · Marca e identidade visual               ░░░░░░░░░░░░  sem prazo (próximo foco)
        └─ candidato forte a NOME do sistema: "6floor" (s39, a confirmar)
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
           🌐 Ficha ONLINE (ngrok) com SENHA — princípio "nunca expor sem senha"
           🔒 Link da câmera é SÓ-FICHA (não vê gestão nem edita ficha alheia)
           📷 QR da ficha na tela de Acompanhamento (auto-detecta a URL do ngrok)
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
2c. 📁 **Entrada por PASTA SATÉLITE (arco próprio — 3 fatias CONSTRUÍDAS)** — material que NÃO
   vem por cartão (fotógrafo foi embora; PGM/feed). ✅ Caixa "Pasta de recebidos" no Painel (s40, PR #11).
   ✅ **s41:** pergunta de ORIGEM no Post ("Como o material chega?") · pasta `recebidos/<post>/` local ao
   salvar Post satélite · LINK por Post (acesso externo) · GATILHO do operador "pronto para copiar" (só marca).
   🔶 Link decidido: direção A (o sistema oferece) + 1 pasta/link por Post. **FALTA: a CÓPIA (C2)** — ensinar
   a transferência a olhar Posts com `recebido_pronto=1` e copiar de `recebidos/<post>/` (copiador já é
   agnóstico de origem); depois **C4 audita mas NÃO roda Parashoot**; e (futuro) criar a subpasta na nuvem +
   link automático (API Drive/Dropbox). Ver [[pasta-satelite-recebidos]].
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
  URL ativa do ngrok). O operador aponta pros câmeras.
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
