# Mapa Vivo do GMA
## Gerenciamento de Mídia Audiovisual — onde estamos, o que fizemos, pra onde vamos

> Este é o **mapa do processo**. Sempre que bater a sensação de "estou perdido,
> o que já fizemos?", abra este arquivo: ele mostra o quadro inteiro de uma vez.
> Para os detalhes técnicos e o histórico completo, ver `documento_mestre_GMA.md`.
>
> Princípio central de tudo: **UMA fonte de verdade → TRÊS vistas.**
> O sistema guarda o dado em um lugar só; as telas são jeitos diferentes de LER
> esse mesmo dado. Nada diverge.
>
> Última atualização: 2026-06-10 (sessão 21 — ficha própria no GMA: entrada com gabarito/edição, online com senha, link de câmera só-ficha e QR na tela de Acompanhamento)

---

## 1. Onde estamos — o prédio de 7 andares

Pense no GMA como um prédio. Cada andar só faz sentido depois do anterior.
O coração do sistema (andares 1 e 2 — o trabalho mais difícil) está pronto e
testado com cartão de verdade.

```
ANDAR                                       PROGRESSO
──────────────────────────────────────────────────────────────────
1 · Check-in (identificar o cartão)         ████████████  PRONTO ✅
        └─ Matcher seguro + perfil que aprende cada pessoa
        └─ NOVO: ficha PRÓPRIA no GMA (gabarito + edição) · online c/ senha · QR
2 · Transferência (copiar com segurança)    ████████████  PRONTO ✅
3 · Banco de dados (guardar tudo)           ██████████░░  QUASE
                                                          (Kanban + Planilha no ar; falta Google Sheets real)
4 · Auditoria + devolver o cartão           ████████████  PRONTO ✅
        └─ embaralha · ejeta · RESTAURA pelo Parashoot — testado com cartão real
5 · Tela bonita + várias máquinas           █░░░░░░░░░░░  EM PLANEJAMENTO
        └─ agente plataforma-gma + blueprint · acesso por papel e mural já desenhados
6 · Inteligência artificial (opcional)      ░░░░░░░░░░░░  futuro
7 · Marca e identidade visual               ░░░░░░░░░░░░  PRAZO 20/06 ⚠️ (próximo foco)
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
        │               Atenção: tem material de 2 dias diferentes."
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

---

## 5. O que pede atenção agora

Em ordem de impacto:

1. 🎨 **Marca / identidade visual (andar 7)** — prazo 20/06 + o relatório PDF de hoje
   ficou abaixo do esperado (sem padrão, layout fraco). Definir logo, paleta,
   tipografia e grid ANTES de refazer o PDF, pra ele nascer bonito e consistente.
2. 📄 **PDF Overview** — refazer o gerador no estilo dashboard + folha de contato
   (briefing pronto na §13.4 do documento mestre, material de teste já gerado),
   já aplicando o padrão visual do andar 7.
3. 🔌 **Ligar frames + PDF ao fluxo automático** — hoje o extrator de frames roda
   à mão depois da cópia; falta plugá-lo dentro da transferência.
4. 🧠 **Fase 2 do perfil** — fazer o sistema USAR o que aprende (câmera, prefixo,
   numeração) para desempatar sozinho, com tolerância a gaps. Tira o operador do caminho.
5. 📊 **Google Sheets real** (andar 3) — criar a planilha na nuvem + credenciais.
   (O Kanban e a Planilha locais já estão no ar desde a sessão 19, lendo da fonte única.)
6. 🖥️ **Mural dos câmeras** (2º monitor) — construir a tela read-only de status em
   linguagem de set + QR fixo (desenho pronto na sessão 21; layout em aberto).
7. 🌐 **Endereço fixo do túnel** (opcional) — hoje a ficha online usa URL temporária
   do ngrok (o QR se auto-atualiza). Um domínio fixo deixa o link estável.

> ✅ Resolvido na S21: a **entrada de dados** não depende mais do Tally — a ficha própria
> do GMA é o canal principal (Tally vira reserva opcional). Guia do Tally segue válido
> (`guia_tally_gma.md`) só se quiser o canal de reserva.
>
> Pendências menores guardadas: bug do "0 arquivos no banco" (S7); consistência do
> banco quando dois cartões têm o mesmo nome de volume ("Untitled") — visto no teste do Joe;
> Passo 2 (tela de confirmação de match no clique); loop automático da auditoria.py.

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
│   📊 Google Sheets (espelho de entrega para editores) — a integrar   │
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
 │ STATUS: no ar      │  │ STATUS: rascunho        │  │ STATUS: espelho    │
 │ (abas; lê JSON)    │  │ (/kanban + post-it)     │  │ local; Sheets falta│
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

---

## 8. Organograma dos processos (Zona 2 em detalhe)

```
                        inicializar_gma.py
                  (sobe tudo com um comando)
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
                                │
                                ▼
        Parashoot erase → embaralha + ejeta → status CONCLUÍDO
                                │
                                ▼
        ↩️ Parashoot restore (quando precisar desfazer — material intacto)

   Na transferência:
   copiador.py (MOTOR) → cópia + checksum MD5 + gera .sppo
        │
        ▼
   extrator_frames.py → 10 frames por vídeo + manifesto.json
        │
        ▼
   gma_relatorio_pdf.py → PDF rico (frames + metadados + auditoria)
   ⚠️ PDF a refazer (estilo Overview + padrão visual do andar 7)

   encerrar_gma.py  →  encerramento de emergência (desliga tudo)
   .gma_ativo       →  sentinela: existe = sistema processando
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
 │checkin-gma│  │transferencia-│ │banco-  │ │auditoria│ │ testes /     │
 │ Camada 1  │  │gma           │ │dados-  │ │-gma     │ │ documentação │
 │  ✅        │  │ Camada 2 ✅  │ │gma     │ │Camada 4 │ │ (futuros)    │
 │           │  │              │ │Camada3 │ │  ✅     │ │              │
 │leitura,   │  │copiador.py,  │ │🔧      │ │Parashoot│ │              │
 │Forms,     │  │checksum MD5, │ │SQLite, │ │check/   │ │              │
 │numeração  │  │.sppo, PDF    │ │Sheets, │ │erase/   │ │              │
 │           │  │              │ │3 telas │ │restore  │ │              │
 └───────────┘  └──────────────┘ └────────┘ └─────────┘ └──────────────┘
   EXISTE         EXISTE          EXISTE     EXISTE ✅    a criar
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

> Para a arquitetura completa, decisões e estado detalhado, ver `documento_mestre_GMA.md`.
