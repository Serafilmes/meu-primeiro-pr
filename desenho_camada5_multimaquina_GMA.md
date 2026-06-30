# Desenho da Camada 5 — Multi-máquina (modelo ESTRELA) + protocolo de teste

> Documento de trabalho aberto na sessão 64 (2026-06-30), véspera do 1º teste de
> bancada com várias máquinas. Fonte de verdade do desenho multi-máquina; o
> `arquitetura_GMA.md` resume, este detalha. Atualizar a cada avanço.

---

## 1. A decisão: modelo ESTRELA (1 servidora central)

Das três topologias possíveis, o idealizador escolheu a **estrela**:

- **1 máquina SERVIDORA** (o "centro"): roda o banco único (`gma.db`), o Flask, a
  numeração e a planilha/Sheets. É a fonte única de verdade.
- **2–3 ESTAÇÕES** (as "pontas"): leem cartão e **copiam a mídia para o STORAGE de
  rede compartilhado** (o destino comum); mandam os **dados** (registro do cartão,
  ficha, status) para a servidora gravar no banco central.

### Dois centros distintos (não confundir)
A estrela tem DOIS centros separados — no SP2B o storage é um **servidor EXTERNO**:

1. **Centro de MÍDIA = servidor externo (NAS).** Todas as máquinas o montam e copiam
   o material para lá pelo sistema de arquivos (`GMA_DESTINO` → pasta no NAS). O GMA
   **não gerencia** esse servidor — só escreve nele. A mídia mora num lugar só,
   alcançável por todos.
2. **Centro de DADOS = uma das máquinas (Mac) servidora GMA.** Roda o `gma.db` +
   Flask + numeração. O banco fica no **disco LOCAL dessa máquina** — NUNCA no NAS
   (SQLite sobre rede compartilhada corromperia). As estações falam com ela por HTTP.

Resumo: **mídia → NAS externo (filesystem); dados → Mac servidora (HTTP).**

Por que estrela e não as outras:
- **Banco em pasta de rede compartilhada** (todas apontam o `gma.db` num NAS) foi
  **descartado**: o SQLite trava e pode corromper sob escrita concorrente pela rede
  — risco inaceitável para material insubstituível. (Atenção: o STORAGE de mídia é
  compartilhado, mas o `gma.db` NÃO — o banco fica central via HTTP, na servidora.)
- **Independentes + merge no fim** foi descartado para o uso ao vivo: não dá visão
  única durante o evento (o operador não vê o todo até o merge).

### A FRONTEIRA DE SEGURANÇA (princípio nº2, com precisão — corrigido na s64)
A mídia **PODE e DEVE** trafegar pela **rede local** até o destino de cópia — esse é
o fluxo normal de DIT. A cópia é feita pelo **sistema de arquivos** (o copiador
escreve no `GMA_DESTINO` montado e relê de lá para o MD5), **fora da camada web**.

O que o princípio nº2 proíbe de verdade:
- mídia indo para a **NUVEM** (Drive / internet) — só informação sobe;
- mídia passando pela **camada web** (Flask / formulário / túnel Cloudflare) — *"o
  Flask controla o processo, nunca o conteúdo"*.

Regra prática: **rede local + sistema de arquivos = OK; camada web / nuvem = nunca.**

---

## 2. O que JÁ EXISTE hoje (e serve à estrela sem mudança)

| Peça | Estado | Observação |
|---|---|---|
| Flask escuta na rede | ✅ | `GMA_HOST=0.0.0.0` (`flask_gma.py` ~8265) — só escuta quando você pede; padrão é só-local |
| Fichas/forms pela rede | ✅ | estações abrindo `http://<ip-servidora>:5050/ficha` já preenchem Posts no banco central |
| Câmera remota (túnel) | ✅ | Cloudflare entrega a ficha pelo celular sem tela de aviso (s63) |
| Pasta satélite (recebidos) | ✅ | a servidora copia material avulso (sem cartão) — testável amanhã |
| Saguão (5055) + sessão (5050) | ✅ | mono-máquina, robusto; cada máquina sobe o seu |
| Login de operador | ✅ | armazém GLOBAL (`operadores.json`), mesma equipe entre eventos |

**Tradução:** a servidora, sozinha, já é um GMA completo. E uma estação **já pode
ser um terminal de FICHA** (navegador apontado para a servidora) hoje, sem código novo.

---

## 3. O que FALTA para a estrela de verdade (a lacuna)

O buraco é o **caminho do cartão na estação**. Hoje, quando uma máquina lê um cartão,
ela detecta (porteiro) → copia (copiador) → registra no **banco LOCAL dela** e pega um
número do **contador LOCAL dela** (`contadores/<NOME>.json`). Numa estrela isso quebra:
duas estações dariam o mesmo número e gravariam em bancos separados.

Peças a construir (NÃO construídas ainda — são o trabalho das próximas sessões):

1. **Numeração CENTRAL.** Hoje `transferencia.proximo_numero_sequencial(nome)` lê/grava
   um JSON local. Na estrela, a estação precisa **pedir o próximo número à servidora**
   (um endpoint HTTP novo, ex. `POST /api/numero {nome}` → devolve `DUMITRIU_004` e já
   incrementa no contador central). Sem isso, números colidem.

2. **Registro do cartão no banco CENTRAL.** Depois de copiar para o storage
   compartilhado, a estação manda o registro (nome do cartão, contagem, tamanho,
   checksum, caminho no storage, status) para a servidora gravar no `gma.db` central
   (endpoint HTTP, ex. `POST /api/cartao`). Como a mídia mora no volume comum, o
   caminho é alcançável por todos — não há "está só na máquina X".

3. **Identidade da estação.** Cada estação precisa de um nome/ID (ex. `EST-1`,`EST-2`)
   — útil para o rastro de governança (qual máquina processou cada cartão), não para
   localizar a mídia (ela está no storage comum).

4. **Auditoria + Parashoot.** Como a mídia está no storage compartilhado, a auditoria
   (contagem+tamanho) pode rodar **na servidora** (ela alcança o volume) — simplifica.
   Só o **Parashoot (ejetar o cartão) é local na estação**, porque o cartão físico
   está plugado nela. A decidir: auditar central × auditar na estação que copiou.

5. **Como a estação "fala" com a servidora.** Decisão de desenho pendente: a estação
   roda um GMA mínimo (porteiro+copiador+auditoria) que, em vez de banco local, usa um
   "banco remoto" (cliente HTTP para a servidora)? Ou a estação roda o GMA inteiro
   local e só **espelha** os registros para a servidora? → **decidir antes de construir.**

---

## 3b. Papéis das máquinas — UM programa só, papel por configuração

A máquina **não vira estação instalando outro programa.** É o MESMO GMA; o papel é
uma **opção de configuração** (igual ao botão "Liberar rede local" que já existe em
Painel → Sistema → Conexões). Desenho:

- **Papel = SERVIDORA:** roda o GMA completo (banco `gma.db` + Flask + numeração) +
  rede ligada (`0.0.0.0`). É o centro de dados.
- **Papel = ESTAÇÃO:** roda porteiro/leitor/copiador localmente (lê o cartão, copia
  para o NAS), MAS em vez de banco próprio, **pergunta à servidora por HTTP** o
  próximo número e manda o registro do cartão. Precisa de um campo "endereço da
  servidora" (ex.: `gma-servidora.local:5050`).

A construir (§3): a "opção de papel" + o modo estação (cliente HTTP no lugar do banco
local). **Hoje o modo estação NÃO existe** — toda máquina que sobe o GMA age como uma
servidora isolada. Por isso o teste de amanhã é graduado.

---

## 4. Protocolo de teste — AMANHÃ (2026-07-01)

Bancada esperada: **2–3 Macs** (3 se conseguir) na mesma rede Wi-Fi/cabo + **cartões
reais** + **arquivos para a pasta satélite**.

O teste é **graduado**: começa pelo que já funciona (recon de rede + fichas) e vai até
mapear na prática o que falta. Não espere a estrela completa amanhã — ela ainda não
está construída. O objetivo de amanhã é **validar a fundação e medir a lacuna com
hardware real**, não rodar 3 cartões em paralelo no banco central (isso vem depois do build).

### Receita rápida — preparar a SERVIDORA (faça isto primeiro)
1. Escolher UMA máquina como servidora. Subir o GMA normal (saguão → Entrar no projeto).
2. Montar o NAS e apontar **Pasta dos materiais** (Painel → Sistema → Conexões →
   "Pasta dos materiais", botão direcionar) para a pasta no NAS.
3. Em Conexões → "Acesso pela rede", clicar **"Liberar rede local"** (vira `0.0.0.0`).
   **Reiniciar** a sessão para aplicar (Voltar ao saguão + Entrar).
4. Descobrir o **IP local** da servidora: menu Apple → Ajustes → Wi-Fi → Detalhes
   (ou `ipconfig getifaddr en0` no Terminal). Anotar (ex.: `192.168.0.42`).

### Receita rápida — usar uma ESTAÇÃO como terminal de FICHA (funciona hoje)
- Em outra máquina, abrir o navegador em `http://<ip-servidora>:5050/ficha`.
- Preencher → o Post cai no banco da servidora. É o multi-máquina REAL que já roda hoje
  (várias pessoas preenchendo fichas no banco central, do Wi-Fi do set).

### Bloco A — Rede e fundação (DEVE funcionar hoje)
- [ ] **A1.** Numa máquina (a SERVIDORA), subir o GMA e ligar a escuta de rede
      (`GMA_HOST=0.0.0.0`). Anotar o **IP local** dela (ex. `192.168.x.y`).
- [ ] **A2.** De outra máquina (ESTAÇÃO), abrir `http://<ip-servidora>:5050/ficha` no
      navegador. **Esperado:** a ficha carrega.
- [ ] **A3.** Preencher uma ficha na estação. **Esperado:** o Post aparece no banco/Kanban
      da servidora. → confirma que a rede + fichas servem à estrela.
- [ ] **A4.** Repetir A2/A3 com a 3ª máquina (se houver). Várias estações, uma ficha cada.
- [ ] **A5.** Testar o **túnel Cloudflare** da servidora pelo celular (QR) — confirmar
      que o caminho remoto segue ok com a escuta de rede ligada.

### Bloco B — Pasta satélite na servidora (DEVE funcionar hoje)
- [ ] **B1.** Na servidora, criar um Post de material recebido e jogar os **arquivos de
      teste** na pasta `RECEBIDOS/<slug>/`.
- [ ] **B2.** Clicar "Copiar agora". **Esperado:** copia com MD5/.sppo/PDF, audita sem
      Parashoot, renomeia a pasta `_COPIADO`. (caminho da s43)
- [ ] **B3.** Observar a **faixa de velocidade ao vivo** no Mural durante a cópia (s60).
      → já é um teste de velocidade de transferência real.

### Bloco C — Cartão na estação (MEDIR A LACUNA — não vai fechar amanhã)
- [ ] **C0.** Montar o **storage de rede** em todas as máquinas e apontar o
      `GMA_DESTINO` de cada uma para a MESMA pasta no volume compartilhado.
- [ ] **C1.** Numa ESTAÇÃO, subir o GMA local e inserir um cartão real.
- [ ] **C2.** Observar: o porteiro detecta? o leitor classifica? a cópia para o
      **storage compartilhado** roda (com MD5)? **Esperado:** a cópia funciona, MAS o
      registro vai para o banco LOCAL da estação (não o central) e usa o contador
      LOCAL. → **é a lacuna do §3 (banco/numeração central), confirmada na prática.**
- [ ] **C3.** Se duas estações copiarem, observar se os **números colidem** e se cada
      banco local "não enxerga" o cartão da outra. Anotar tudo (números, caminhos, o
      que faltou) para desenhar o build do §3 com dados reais.

### Bloco D — Anotações para o build (preencher durante o teste)
- IPs e nomes das máquinas: _______
- A rede aguenta? latência ao abrir a ficha remota: _______
- Cartões usados (marca/modelo): _______
- O que travou / surpreendeu: _______
- Velocidade de cópia observada (Mural): _______

---

## 5. Sequência de build DEPOIS do teste (rascunho, a confirmar)

1. **Identidade da estação** (`EST-1`…) + decisão do §3.5 (banco remoto × espelho).
2. **Numeração central** (endpoint + cliente) — destrava rodar 2 cartões sem colidir.
3. **Registro do cartão no banco central** (endpoint + cliente).
4. **Auditoria local → veredito remoto.**
5. Teste de bancada COMPLETO (2–3 cartões simultâneos no banco central).

---

## 6. Encaixe das duas tarefas de velocidade (Fatia 5) neste arco

O idealizador também pediu as duas tarefas de velocidade. Elas **encaixam bem na
bancada** multi-máquina (instrumentam o teste), mas são build à parte:

- **Velocidade de TRANSFERÊNCIA — Fatia 2 (histórico por cartão):** persistir no banco
  (C3) a duração + MB/s média de cada cópia. Útil para comparar máquinas/cartões no
  teste. (Fatia 1, ao vivo, já existe — s60.)
- **Velocidade de DISCO na aba Sistema (Peça 2 da s59):** decidir benchmark sob demanda
  (aperta "Testar") × velocidade observada nas cópias já feitas. ⚠️ lê disco → respeitar
  o princípio nº2 (nunca tocar na mídia; medir em área de teste).

Recomendação: rodar o teste de amanhã primeiro (a bancada ensina o que medir), depois
construir as duas velocidades como instrumentação permanente.

### Executável / .app (levantado na s64 — "rola?") — SIM, em 3 níveis
Hoje já existem os atalhos clicáveis `Iniciar GMA.command` / `Encerrar GMA.command`
(sobem/descem o saguão). Para virar "app de verdade":
- **Nível 1 (V1 recomendado):** embrulho `.app` com o **ícone 6floor** que faz o que o
  `.command` já faz (sobe o saguão + abre o navegador). Usa o Python/venv da máquina.
  Baixo risco; encaixa na C7 (precisa do ícone do app de qualquer jeito).
- **Nível 2:** janela nativa (pywebview) no lugar da aba do navegador. Médio.
- **Nível 3:** `.app` auto-contido (py2app/PyInstaller empacota Python + deps) p/ rodar
  em máquina SEM nada instalado — a virada protótipo→produto. Alto: subprocessos, a
  caixa `.venv_ia` pesada (Whisper), binários externos (cloudflared/Parashoot/gcloud),
  assinatura/notarização (Gatekeeper). Multi-sessão, empreitada à parte.
- **Não bloqueia o teste multi-máquina** (a estação-ficha é só navegador). Delegar ao
  `plataforma-gma` quando o idealizador pedir. Não construir ainda (s64: era viabilidade).

---

## 7. Trocar a máquina SERVIDORA (continuidade / robustez)

Pergunta do idealizador (s64): se a máquina servidora precisar ser trocada, como a
nova dá continuidade ao projeto?

**Boa notícia da topologia:** a servidora NÃO guarda mídia (ela mora no NAS externo).
O que ela guarda é só o **cérebro de dados**, que é pequeno e portátil:
- `gma.db` (registros — texto/números, leve);
- `contadores/<NOME>.json` (numeração);
- filas (`fila_material/`, `fila_forms/`) e config do projeto.

Logo, **trocar de servidora = mover o caderninho, não o material**. Nenhum arquivo de
mídia corre risco na troca — fica parado e seguro no NAS o tempo todo.

### Duas condições para a troca ser limpa
1. **NAS no MESMO ponto de montagem em toda máquina** (ex.: sempre
   `/Volumes/SP2B_STORAGE`). O banco guarda os caminhos da mídia; se a nova máquina
   montar o NAS com outro nome, os caminhos quebram. Padronizar resolve. (Alternativa
   de build: guardar os caminhos RELATIVOS à raiz do NAS.)
2. **Cópia recente do `gma.db`.** Se a servidora antiga morrer sem aviso, precisa de
   backup. Barato: a servidora copia o `gma.db` para uma pasta no NAS de tempos em
   tempos (é pequeno) → o cérebro nunca fica só num lugar.

   **Onde fica o backup (DESTINO EDITÁVEL):** segue o mesmo padrão dos campos de
   Conexões (Painel → Sistema) — um campo editável "Pasta de backup do banco".
   - **Padrão sugerido:** uma pasta no NAS (`<NAS>/_GMA_BACKUP/<projeto>/`). Razões:
     o NAS está sempre montado, é alcançável por qualquer máquina que vire servidora,
     e fica SEPARADO do banco vivo (servidora morre → backup não morre junto).
   - É uma **cópia/foto** do banco (snapshot periódico). O banco VIVO nunca roda
     direto no NAS — só local na servidora (SQLite sobre rede corrompe).
   - Editável porque cada evento/cliente pode ter um NAS ou pasta diferente.

### Como as estações acham a nova servidora
O IP muda ao trocar de máquina. Para não reconfigurar cada estação, dar à servidora um
**nome fixo de rede** (Bonjour/mDNS, ex.: `gma-servidora.local`) — as estações apontam
para o nome; o IP por baixo pode mudar sem ninguém perceber. (Build futuro.)

### Procedimento de troca (rascunho)
1. Parar o GMA na servidora antiga (ou, se morreu, pegar o backup do `gma.db` no NAS).
2. Na máquina NOVA: montar o MESMO NAS no MESMO ponto; copiar a pasta do projeto
   (`gma.db` + `contadores/` + filas + config) para ela.
3. Apontar `GMA_DB` e `GMA_DESTINO` (e subir o saguão/sessão). A nova servidora
   continua de onde parou — os caminhos da mídia resolvem porque o NAS é o mesmo.
4. Repontar as estações para o novo endereço (ou, com o nome mDNS, nada a fazer).

> Observação: isto vale para troca PLANEJADA ou para recuperação de falha. É o mesmo
> mecanismo — o que dá robustez é o backup periódico do `gma.db` no NAS + o ponto de
> montagem padronizado. Ambos são build futuro pequeno, mas anotados aqui como parte
> do desenho da estrela.
