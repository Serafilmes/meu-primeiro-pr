# Desenho — Passo 2 do Matcher (resolução de empate)
## Referência para o build — sessão 24 (2026-06-14)

> Sessão de desenho conduzida pelo orquestrador com o idealizador.
> Status: **APROVADO, NÃO IMPLEMENTADO**.
> Build: agente `checkin-gma` (Matcher) + `banco-dados-gma` (Flask + banco).

---

## 1. Contexto

O Passo 1 do Matcher (sessão 13) entregou a lógica de empate segura:
quando dois ou mais candidatos empatam, o sistema marca o cartão como
`aguardando_confirmacao`, salva os candidatos em `match_candidatos` e
registra evento `match_ambiguo` no banco. O painel mostra a seção
"Aguardando confirmação" — mas só leitura, sem ação possível.

O Passo 2 fecha o ciclo: dá ao operador um botão para resolver o empate
com 1 clique e libera o fluxo normal de transferência.

---

## 2. O que o operador vê no painel

Na seção "Aguardando confirmação" do painel (`flask_gma.py`), cada cartão
ambíguo exibe:

- **Cabeçalho do cartão:** nome do volume · nº de arquivos · câmera detectada
- **Lista de candidatos:** um bloco por candidato, contendo:
  - Nome do profissional
  - Câmera da ficha
  - 3–4 primeiros nomes de arquivo do cartão (ex: `joe0258.mp4`, `joe0259.mp4`, `joe0260.mp4`)
  - Botão **"Confirmar [NOME]"**

Exemplo visual (referência para o build):

```
┌─────────────────────────────────────────────────────────┐
│ UNTITLED — 57 arquivos · Sony                           │
│ Quem é esse cartão?                                     │
│                                                         │
│  JOAO · Sony FX3                                        │
│  joe0258.mp4 · joe0259.mp4 · joe0260.mp4               │
│  [Confirmar JOAO]                                       │
│                                                         │
│  PAULO · Sony FX3                                       │
│  paulo001.mp4 · paulo002.mp4 · paulo003.mp4            │
│  [Confirmar PAULO]                                      │
└─────────────────────────────────────────────────────────┘
```

---

## 3. Fluxo após o clique

### Passo 3a — Tela de confirmação (resumo enxuto)

Depois de clicar em "Confirmar JOAO", o sistema **não executa ainda** —
mostra uma tela de revisão com uma linha de resumo:

```
Match confirmado — JOAO / Sony FX3 / 57 arquivos → JOAO_002
[Iniciar transferência]
```

Campos do resumo:
- Nome do profissional escolhido
- Câmera detectada
- Nº de arquivos
- Pasta de destino prevista (lida do contador `contadores/JOAO.json` + 1)

Motivo do passo extra: um match errado gera pasta com nome errado no HD;
desfazer no meio de um evento é custoso. O custo de 1 clique a mais é
baixo; o custo de um match errado é alto.

### Passo 3b — Confirmar e liberar

Ao clicar em "Iniciar transferência":

1. Registra o match na tabela `matches` (match confirmado)
2. Atualiza `match_candidatos`:
   - Candidato escolhido → status `escolhido`
   - Demais candidatos → status `descartado`
3. Atualiza status do cartão → `matched`
4. Chama `atualizar_perfil(nome, assinatura)` — o perfil do profissional
   acumula mais uma assinatura confirmada (já previsto na sessão 13)
5. Dispara o fluxo normal de transferência

---

## 4. Candidatos não escolhidos

Ficam na tabela `match_candidatos` com status `descartado` — auditável,
rastreável, sem perda de histórico. As fichas dos candidatos descartados
voltam ao status `aguardando_match`, livres para casar com o próximo
cartão do profissional.

A tabela `match_candidatos` já foi desenhada na sessão 18 com o campo
`status` (pendente / escolhido / descartado) — este build apenas usa
o que já existe.

---

## 5. Arquivos tocados no build

| Arquivo | O que muda |
|---|---|
| `flask_gma.py` | Nova rota `POST /match/<cartao_id>/confirmar` (recebe o nome escolhido); tela de resumo antes de liberar; botões na seção "Aguardando confirmação" |
| `matcher.py` | Função de confirmação manual (registra match + descarta candidatos + chama `atualizar_perfil`) |
| `banco_dados.py` | Função `confirmar_match(conn, cartao_id, nome_escolhido)` — atualiza `matches` + `match_candidatos` atomicamente |

---

## 6. Dados necessários para montar a tela

O painel precisa buscar, para cada cartão `aguardando_confirmacao`:

- Da tabela `cartoes`: volume, n_arquivos, camera_detectada
- Da tabela `match_candidatos`: lista de candidatos (nome, câmera da ficha)
- Da fila JSON do cartão (ou tabela `arquivos` se já populada): primeiros
  3–4 nomes de arquivo de mídia — para exibir como pista ao operador

Se os nomes de arquivo ainda não estiverem no banco neste momento do fluxo
(o cartão ainda não foi transferido), lê diretamente do JSON em
`fila_material/` — que sempre existe neste ponto.

---

## 7. Critério de conclusão do build

- [ ] Seção "Aguardando confirmação" exibe candidatos com câmera + nomes de arquivo
- [ ] Botão "Confirmar [NOME]" leva à tela de resumo
- [ ] Tela de resumo mostra: nome · câmera · nº arquivos · pasta de destino prevista
- [ ] Botão "Iniciar transferência" registra match, descarta candidatos, dispara transferência
- [ ] `atualizar_perfil` é chamado na confirmação
- [ ] Candidatos descartados ficam com status `descartado` na tabela `match_candidatos`
- [ ] Fichas descartadas voltam a `aguardando_match`
- [ ] Testado: empate entre 2 candidatos → operador resolve → transferência inicia

---

## 8. Pendências adiadas (não são deste build)

- **Papel SUPERVISÃO** (acesso remoto de monitoramento) — C5
- **Mural dos câmeras** (2º monitor, layout em aberto) — desenhado na próxima sessão
- **Login multiusuário** — radar da C5
