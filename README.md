# GMA — Gerenciamento de Mídia Audiovisual

Sistema de **logagem (gerenciamento) de mídia para eventos ao vivo**. O GMA automatiza o ciclo
completo de tratamento dos cartões de memória entregues pelas equipes de captação: identifica o
cartão, transfere os arquivos com verificação de integridade, registra tudo num banco local e
prepara o cartão para reutilização — com **segurança absoluta do material**, que é insubstituível.

> Feito em Python, com foco em **operação offline**, **custo mínimo** e **autonomia** — o operador
> humano é o último recurso, não o primeiro.

---

## Princípios inegociáveis

1. **Offline-first** — o ciclo crítico funciona 100% sem internet. A nuvem só sincroniza depois.
2. **Segurança dos arquivos acima de tudo** — material nunca é apagado, movido ou renomeado sem
   verificação. Vídeo nunca sobe para a nuvem — só informação sobre ele.
3. **Custo mínimo** — ferramentas gratuitas e processamento mecânico (metadados, checksums). IA só
   numa camada opcional e futura.
4. **Autonomia máxima** — o sistema decide sozinho na maioria dos casos.
5. **Velocidade** — ações ágeis no check-in para não gerar filas no set.

---

## As 7 camadas (o "prédio")

| # | Camada | Estado |
|---|---|---|
| 1 | Check-in e identificação do cartão | ✅ Pronto (ficha própria com gabarito + edição; Matcher seguro + resolução de empate no painel; perfil que aprende) |
| 2 | Transferência (cópia + checksum MD5 + relatório) | ✅ Pronto (validado com cartão real) |
| 3 | Banco de dados (fonte única + telas) | ⚠️ Quase (Kanban e Planilha locais no ar; Google Sheets real pendente) |
| 4 | Auditoria e devolução do cartão (Parashoot) | ✅ Pronto (ciclo de vida completo testado) |
| 5 | Plataforma profissional + multi-máquina | 🔧 Em planejamento |
| 6 | Inteligência artificial (opcional) | 📋 Futuro |
| 7 | Marca e identidade visual | 📋 Planejado |

---

## Como rodar

Pré-requisitos: **Python 3** e as ferramentas do ciclo (ffmpeg/exiftool para metadados; Parashoot
para a ejeção). Configuração opcional em `.env` (veja `.env.exemplo`).

```bash
# Liga todos os processos do sistema com um comando
python3 inicializar_gma.py
# Ctrl+C para encerrar

# Encerramento de emergência (mata todos os processos)
python3 encerrar_gma.py
```

Com o sistema no ar, o painel abre em **http://127.0.0.1:5050**.

### As telas (uma fonte de verdade, várias vistas)

| Tela | Endereço | Para quem |
|---|---|---|
| **Nova Ficha** (check-in) | `/ficha` | Câmeras/operador preenchem o cartão que chegou |
| **Operação** (centro de comando) | `/` | Operador da base |
| **Acompanhamento** (Kanban + QR) | `/kanban` | Operador + equipes (acompanhar o status) |
| **Planilha de Entrega** | `/planilha` | Editores e cliente |

A ficha pode ficar **online** (link para o celular do set) via túnel (ngrok), sempre protegida por
senha (`GMA_SENHA`). O link público das câmeras dá acesso **só ao preenchimento da ficha** — as
telas de gestão ficam restritas à máquina da base.

---

## Estrutura do projeto

- **Camada 1 (check-in):** `porteiro.py`, `leitor_midia.py`, `ler_cartao.py`, `matcher.py`,
  `flask_gma.py` (telas + ficha), `google_apps_script.js`.
- **Camada 2 (transferência):** `copiador.py`, `transferencia.py`, `gma_relatorio_pdf.py`,
  `extrator_frames.py`.
- **Camada 3 (banco):** `banco_dados.py` (SQLite `gma.db`), `exportador_sheets.py`.
- **Camada 4 (auditoria):** `auditoria.py` (integra o CLI do Parashoot).
- **Orquestração:** `inicializar_gma.py`, `encerrar_gma.py`, `ngrok_gma.sh`.
- **Configuração:** `.env` (segredos/ajustes — não versionado; modelo em `.env.exemplo`).

> Arquivos de runtime (`gma.db`, `logs/`, filas, contadores) e o `.env` **não** vão para o git —
> são estado local da máquina.

---

## Onde ler mais

- **`documento_mestre_GMA.md`** — arquitetura completa, decisões e histórico de cada sessão.
- **`organograma_GMA.md`** — o "Mapa Vivo": onde estamos, o que fizemos e para onde vamos, em
  linguagem de set.
- **`plano_camada5_GMA.md`** — o blueprint da plataforma (Camada 5).
- **`guia_tally_gma.md`** — como montar o formulário externo (canal de reserva).

---

> **Projeto em desenvolvimento ativo.** As camadas 1, 2 e 4 já foram testadas com cartão real; as
> demais estão em construção. O coração do sistema (identificar e copiar com segurança) já funciona
> ponta a ponta.
