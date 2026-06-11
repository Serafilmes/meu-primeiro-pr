# Guia Rápido — Claude Code + Projeto GMA

> Deixe este arquivo na pasta do projeto e consulte sempre que precisar.

## Abrir o projeto

**App de desktop:** abra o Claude Code e aponte para a pasta `GMA`.
**Terminal:** `cd ~/serafa/GMA` e depois `claude`

A sessão que abrir é o seu **orquestrador**. Ele lê o `CLAUDE.md` automaticamente.

## Comandos essenciais

| Comando | O que faz |
|---|---|
| `claude` | Inicia o Claude Code na pasta atual |
| `claude --continue` | Continua a última sessão de onde parou |
| `claude --resume` | Abre uma sessão anterior para escolher |
| `claude --doctor` | Diagnóstico — verifica se está tudo ok |
| `/agents` | Cria e gerencia os subagentes (modo guiado) |
| `/model` | Troca o modelo em uso |
| `/rename` | Renomeia a sessão atual |
| `?` | Mostra a ajuda com todos os comandos |
| `Shift + Tab` | Liga o "Plan Mode" (planeja antes de executar) |
| `/exit` | Sai do Claude Code |

## Primeira mensagem de cada sessão

Cole algo assim para o orquestrador se situar antes de agir:

> "Leia o documento mestre e me diga, com suas palavras, o estado atual do projeto e
> qual deve ser o próximo passo. Não escreva código ainda — quero alinhar o plano primeiro."

Depois de concordar no plano:

> "Ótimo, pode seguir com esse passo, usando o agente checkin-gma."

## O ritmo saudável (um ciclo por sessão)

1. **Alinhar** — o orquestrador propõe um plano curto, você confirma.
2. **Executar** — o orquestrador ou o subagente faz o trabalho.
3. **Testar** — você roda o comando que ele te passar e confere o resultado.
4. **Registrar** — peça para atualizar o `documento_mestre_GMA.md` com o que mudou.
5. **Salvar** — antes de fechar, peça "faça um commit" (salva um ponto de restauração).

Regra de ouro: **um objetivo por sessão, sempre terminando com algo funcionando.**

## Segurança (sempre)

- Antes de tarefas grandes, peça um **commit** — é seu botão de desfazer.
- Nunca deixe o orquestrador apagar ou mover arquivos de mídia sem você confirmar.
- O Flask roda só na rede local — nunca exposto à internet.
- Trabalhe sobre **cópias** dos arquivos de mídia ao testar.

## Os arquivos do projeto

| Arquivo | Função |
|---|---|
| `CLAUDE.md` | Instruções do orquestrador (lido automaticamente) |
| `documento_mestre_GMA.md` | Arquitetura, decisões e estado do projeto |
| `.claude/agents/checkin-gma.md` | Subagente da Camada 1 (check-in) |
| `ler_cartao.py` | Leitura e classificação de cartão |
| `gma_correcao.py` | Correção de registros com auditoria |
| `gma_relatorio_pdf.py` | Relatório PDF da transferência (ShotPutPro) |

## Se algo der errado

- Comando "não encontrado"? Rode `claude --doctor`.
- A sessão ficou confusa ou lenta? Feche e abra de novo com `claude --continue`.
- O subagente não foi acionado? Chame explícito: "use o agente checkin-gma para isso".
- Em dúvida sobre uma ação destrutiva? Peça para o orquestrador explicar antes de executar.

## Próximo passo do projeto

Camada 1 — check-in. Concluir:
1. Saída JSON estruturada no `ler_cartao.py`.
2. Verificação de data (formulário vs EXIF).
3. Receptor Flask + numeração sequencial.
4. Criação automática da pasta no padrão validado.
