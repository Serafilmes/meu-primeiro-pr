# Desenho — Nova Ficha v2 (GMA / Camada 1)

> Documento de **desenho aprovado**, ainda **NÃO implementado**. Referência para o build
> da próxima sessão. Decisões batidas com o idealizador em 2026-06-12 (sessão 23).
> Fronteiras de camada: perguntas/entregas = C1 · schema/integridade/listas = C3 ·
> login/papéis = C5 (futuro).

## 1. Por que mexer na ficha

A ficha de check-in v1 funciona, mas três coisas incomodam:

1. **Nomenclatura bagunçada** — hoje o NOME é digitação livre (datalist). Cada um escreve
   de um jeito ("Joao", "joão", "João C.") e isso suja o match e a planilha.
2. **Câmera no lugar errado** — hoje a câmera é um campo que a pessoa preenche. Mas quem
   sabe a câmera de verdade é o **Leitor de Mídia (C1)**, lendo o cartão. Pedir pra pessoa
   digitar é fonte de erro.
3. **Tipo único** — hoje só dá pra marcar UM tipo (VIDEO **ou** FOTO **ou** AUDIO). Na prática
   os câmeras chegam com **material misto** (foto + vídeo no mesmo cartão; às vezes + áudio
   de outra pessoa).

A v2 resolve os três e separa de vez **duas caras da ficha** com regras diferentes.

---

## 2. As duas caras da ficha (mesma rota `/ficha`, regras diferentes)

| | Cara **CÂMERA** (remoto, via túnel) | Cara **OPERADOR** (base, localhost) |
|---|---|---|
| Quem usa | Câmera/fotógrafo preenchendo a própria entrega | Operador (ex.: Serafa) inserindo/corrigindo fichas |
| NOME | **Só dropdown fechado** — não digita, não cria | Dropdown + **cria/edita** nomes |
| CÂMERA/MODELO | **Não aparece** (vem do Leitor) | Vê o que o Leitor detectou; confirma/corrige; cria câmera nova |
| Listas (câmeras, marcas…) | Só consome | **Gerencia** (adiciona opção em tempo real) |
| Fichas recentes / edição / abas | Escondidas | Visíveis |

> Isso já existe parcialmente: a rota `/ficha` hoje tem `_portao_de_acesso`/`_remoto_pode_acessar`
> que escondem abas/recentes/edição no remoto (sessão 21). A v2 **aprofunda** essa diferença
> nos próprios campos.

---

## 3. Os 3 campos, reformulados

### 3.1 NOME
- **Câmera:** dropdown **fechado** (sem digitar, sem criar). Só escolhe entre os profissionais
  já cadastrados — **filtrados pelo tipo** que ele marcou (ver §4).
- **Operador:** dropdown + botão de **criar/editar** profissional.
- **Motivo:** acabar com a bagunça de nomenclatura. Um nome canônico por pessoa.

### 3.2 CÂMERA / MODELO
- **Detectado pelo Leitor de Mídia (C1)** a partir do cartão (assinatura + exiftool + extensões).
  O Leitor é o **analista** dessa informação.
- A ficha **não pergunta** a câmera no caminho normal.
- **Se o Leitor não conseguir detectar** → gera **aviso para o operador**, que então escolhe/cria
  a câmera (dropdown completo + criar nova).
- **Resolve a tensão da sessão 13:** a câmera continua existindo **dos dois lados** do match
  (cartão via Leitor + ficha confirmada pelo operador), mas o **câmera-pessoa não digita nada**.
  Menos erro humano, match preservado.

### 3.3 TIPO DE MATERIAL
- **Multi-seleção** ÁUDIO / FOTO / VÍDEO (hoje é seleção única).
- Enxuto, sem título grande — o motivo da múltipla é óbvio: **material misto**.
- Serve para: separar/organizar o material, **contar na planilha** e descrever a estrutura.

---

## 4. A ordem de preenchimento (a "questão importante")

O fluxo da **cara CÂMERA** inverte a ordem: **primeiro o tipo, depois o nome**.

```
1º  TIPO (multi-seleção):   [ ] Áudio   [ ] Foto   [ ] Vídeo
        │
        ├─ marcou Foto e/ou Vídeo (sem Áudio) ......→ 1 dropdown de NOME
        │
        └─ marcou Foto/Vídeo + Áudio ...............→ 2 dropdowns de NOME:
                                                        • NOME do Foto/Vídeo
                                                        • NOME do Áudio
```

**Por quê 2 nomes quando há áudio:** o áudio quase sempre é **outra pessoa** (operador de som /
gravador). Quando entra áudio junto, o sistema já pede o segundo nome separado, em vez de assumir
que é a mesma pessoa.

**Filtro por tipo:** cada dropdown de nome mostra **só os profissionais cadastrados naquele tipo**
(quem faz Áudio aparece no dropdown de Áudio, etc.).

> Nota de implementação: isso exige um pouco de JavaScript na ficha (mostrar/esconder os dropdowns
> conforme as caixas marcadas). É leve e roda offline no próprio navegador.

---

## 5. Cadastro de profissional (na janela Operação)

- **Eixo único de cadastro: o TIPO.** Um profissional é cadastrado como **nome + caixinhas F / A / V**
  (quais tipos ele faz). Nada além disso.
- **Câmera e materiais NÃO se amarram à pessoa** — variam de entrega para entrega. A câmera vem do
  Leitor; o material varia. (O *perfil aprendido* — memória `perfil-do-profissional` — continua
  acumulando câmera/estrutura por baixo, ao longo do tempo, mas isso é automático, não é cadastro.)
- **Onde:** uma forma fácil na janela **Operação** — campo de nome + caixinhas F/A/V + botão criar.

Exemplo de cadastro:

| Nome | Foto | Áudio | Vídeo |
|---|:---:|:---:|:---:|
| Cadu | ✅ | — | ✅ |
| João | — | — | ✅ |
| Marina (som) | — | ✅ | — |

Resultado: no dropdown de Áudio só aparece "Marina"; no de Foto/Vídeo aparecem "Cadu" e "João".

### 5.1 Letra sequencial do profissional (sessão 26, 2026-06-15)

Ao cadastrar um novo profissional (câmera de vídeo, fotógrafo, operador de áudio), o sistema
atribui uma **letra em sequência alfabética** (A, B, C…). Essa letra vai nas **câmeras de
identificação** (claquete/slate) e serve para **ajudar a reconhecer de quem é o material**.

**Ponto crítico — a letra é pista visual, NÃO autoridade de identidade.** Nem sempre o operador
controla o set: pode chegar uma "câmera B" que **não é** a B atribuída pelo sistema (troca de
equipamento, equipe terceirizada, etiqueta errada). Por isso:

- A letra é **apoio**, exibida na ficha/painel — **nunca critério de match**, nunca confiada
  cegamente. Quem manda na identidade continua sendo o **nome** + os identificadores do cartão
  (serial → assinatura → código). Ver memória `identidade-cartao-camadas` e `perfil-do-profissional`.
- A atribuição **dificilmente muda durante o projeto**, mas é na **montagem inicial do evento**
  (cadastro) que precisa estar correta e que o operador deve estar atento.
- Encaixa no cadastro por tipo (§5): a letra é atribuída automaticamente, sequencial, no momento
  do cadastro.

---

## 6. Listas gerenciadas pelo operador

Além dos profissionais, o operador gerencia **listas de apoio** que as fichas leem (câmeras, marcas,
e as lacunas de contexto por evento). Regras:

- Operador **adiciona uma opção** e ela já aparece nos dropdowns (edição em tempo real).
- **Câmera é lista gerenciada** (dropdown completo + criar nova), mas **não fica colada** a um
  profissional — qualquer um pode usar qualquer câmera.
- É a **fronteira C1 ↔ C3** (sessão 18): C1 é dona das perguntas/entregas; C3 é dona do schema,
  da integridade e de como essas listas viram tabela no banco.

---

## 7. Multi-seleção: como guardar — FECHADO (sessão 23)

A multi-seleção precisa ser guardada de um jeito que **a planilha e a IA da Camada 6 consigam ler
limpo**. Decisão: **não existe um jeito único — o mecanismo depende do TIPO de campo.**

**Regra fechada:** *conjunto fixo pequeno → colunas marca-sim/não; lista aberta → lista estruturada
(JSON), exibida com `·`. **Nunca por espaço.***

| Tipo de campo | Exemplo | Como guardar | Como mostrar pro humano |
|---|---|---|---|
| **Conjunto FIXO pequeno** | Tipo de material (Áudio/Foto/Vídeo) | **Colunas booleanas** `tem_audio` / `tem_foto` / `tem_video` (0/1) | `Foto · Vídeo` (renderizado das colunas) |
| **Lista ABERTA que cresce** | Marcas, lacunas de evento | **Lista estruturada (JSON)** numa coluna (padrão `campos_extras`) | `A · B · C` (join na exibição) |

- ❌ **Nunca "separado por espaço"** — valores têm espaço (`Sony FX3`, `Blackmagic Pocket 6K`) → embola
  e atrapalha a IA.
- ✅ **Booleanos para o Tipo:** triviais de **contar na planilha** ("quantos cartões têm foto?"), ótimos
  pra IA, e idênticos ao cadastro de profissional (§5) — **consistência**. Ajudam o **Matcher** (compara
  "cartão tem vídeo?" × "ficha marcou vídeo?" direto).
- ✅ **JSON para listas abertas:** aguenta valor com espaço, IA lê estruturado, reusa padrão existente.
- **Os dois nomes (§4)** NÃO usam este mecanismo — são dois papéis distintos → **duas colunas**
  (`nome` do Foto/Vídeo, `nome_audio`).
- **Decidido na sessão 23.** O tema maior (integração entrega↔planilha↔IA + unificar a leitura na
  fonte única / banco) segue no radar — mas o **encoding** não é mais bloqueio.

---

## 8. Decisões batidas (sessão 23, 2026-06-12)

1. **Login multiusuário (usuário+senha por pessoa, operador = quem logou)** → **NÃO agora**; fica
   no **radar da Camada 5**. A ficha v2 é desenhada/construída **sem** depender de login.
2. **Câmera detectada pelo Leitor** → **SIM** (caminho confirmado; §3.2).
3. **Encoding da multi-seleção** → **FECHADO** (§7): conjunto fixo (Tipo) = colunas booleanas; lista
   aberta = JSON, exibido com `·`; nunca por espaço.
4. **Cadastro de profissional só por tipo (F/A/V)** → **SIM**; câmera/materiais variam, não se
   amarram à pessoa (§5).

## 9. No radar (próximas sessões, não agora)

- **Login / papéis / multiusuário** — Camada 5 (operador = quem logou; cada um com usuário e senha).
- **Integração entrega ↔ planilha ↔ IA** — unificar a leitura na fonte única (banco): Operação ainda
  lê filas JSON; Kanban/Planilha já leem o banco. (O **encoding** já saiu do radar — fechado em §7.)
- **Mural dos câmeras (2º monitor)** — junto da revisão das outras janelas.
- **Menu de funções na Operação + botão do Matcher** (resolver match ambíguo com 1 clique —
  Passo 2 do Matcher, já no roadmap).

## 10. Quem constrói o quê (quando virar build)

| Pedaço | Camada / agente |
|---|---|
| Perguntas da ficha, ordem de preenchimento, filtro de nome por tipo, alerta "câmera não detectada" | **C1** (`checkin-gma`) |
| Câmera vinda do Leitor de Mídia | **C1** (`checkin-gma` / leitor) |
| Tabelas de apoio (profissionais-por-tipo, câmeras, marcas), encoding multi-seleção, integridade | **C3** (`banco-dados-gma`) |
| Login / papéis / multiusuário | **C5** (`plataforma-gma`) — futuro |

---

## 11. Plano de build (fatias pequenas e testáveis)

Ordem das camadas; uma fatia por sessão (proponho → confirma → construo → digo como testar).
Dependências do §7 já resolvidas → **todas as fatias estão livres**.

```
Fatia 1 (C3) ──→ Fatia 2 (C1) ──→ Fatia 3 (C1) ──→ Fatia 5 (C3/C1)
 tabela           cadastro na      ficha câmera      salvar + matcher
 profissionais    Operação         tipo→nome         + planilha
                                        │
                                   Fatia 4 (C1) — câmera vem do Leitor
```

| # | O que faz | Camada | Como testar | Depende de |
|---|---|---|---|---|
| **1** | Tabela `profissionais` — nome + colunas booleanas `tem_foto`/`tem_audio`/`tem_video` + funções criar/listar/filtrar por tipo | C3 | Criar 3 profissionais; listar "só áudio" → volta só eles | — (livre) |
| **2** | Cadastro na Operação — nome + caixinhas F/A/V + criar + lista | C1 | Pela tela: cadastrar "Marina (áudio)" → aparece na lista e no banco | Fatia 1 |
| **3** | Ficha do câmera: tipo multi-seleção (booleanos) → 1 ou 2 dropdowns de nome (áudio = 2º); dropdown **fechado**, filtrado por tipo | C1 | Marcar Foto+Áudio → 2 dropdowns; nomes batem com o tipo | Fatia 1 (+ §7 ✅) |
| **4** | Câmera sai da ficha do câmera → vem do Leitor; se não detectar → aviso ao operador. Operador mantém dropdown de câmera + criar nova | C1 (+ leitor) | Cartão detectado → câmera sozinha; cartão "mudo" → aviso | Fatia 1 |
| **5** | Salvar a nova forma (multi-tipo booleano + até 2 nomes); matcher lê multi-tipo; Kanban/Planilha exibem | C3/C1 | Enviar ficha mista → grava certo; match e planilha refletem | §7 ✅ |

**Próxima sessão = Fatia 1** (tabela `profissionais` por tipo, em C3, via `banco-dados-gma`).
