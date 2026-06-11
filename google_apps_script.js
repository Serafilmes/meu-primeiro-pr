/**
 * google_apps_script.js
 * GMA — Gerenciamento de Mídia Audiovisual
 * Camada 1: Conector Google Forms → Flask local
 *
 * COMO USAR:
 *   1. Abra o Google Forms do evento.
 *   2. Clique em "Mais opções" (três pontos) > "Editor de script".
 *   3. Apague o conteúdo padrão e cole este arquivo inteiro.
 *   4. Troque o valor de IP_FLASK pelo IP da máquina GMA na rede do evento.
 *   5. Salve (Ctrl+S ou Cmd+S).
 *   6. Configure o trigger "aoEnviarFormulario" para rodar em "On form submit".
 *   7. Veja as instruções completas em instrucoes_apps_script.md.
 *
 * ATENÇÃO: este código NÃO roda no seu computador. Ele roda nos servidores do
 * Google sempre que alguém preenche o formulário. O único requisito é que a
 * máquina GMA esteja acessível na rede pelo IP configurado abaixo.
 */


// ── CONFIGURAÇÃO (edite aqui antes de cada evento) ──────────────────────────

// IP da máquina GMA na rede local do evento.
// Para descobrir: abra o Terminal na máquina GMA e rode o comando:
//   ifconfig | grep "inet " | grep -v 127.0.0.1
// O número que aparecer (ex.: 192.168.1.10) é o que você coloca aqui.
const IP_FLASK = "192.168.1.10";  // ← trocar pelo IP real da máquina GMA no evento

// Porta do servidor Flask. Padrão do GMA: 5050. Não altere sem necessidade.
const PORTA_FLASK = "5050";

// Tempo máximo de espera pela resposta do Flask (em milissegundos).
// 5000 = 5 segundos. Se a rede estiver lenta, aumente para 8000 ou 10000.
const TIMEOUT_MS = 5000;


// ── MAPEAMENTO DOS CAMPOS DO FORMULÁRIO ─────────────────────────────────────

// Índice (posição) de cada campo no formulário, contando a partir de 0.
// Se você adicionar ou remover campos no Forms, atualize estes números.
//
// Ordem esperada no formulário:
//   0 → Nome do profissional de captação (fotógrafo, videomaker, técnico de som)
//   1 → Câmera
//   2 → Tipo de material
//   3 → Data de gravação
//   4 → Nome do operador
const IDX_NOME          = 0;
const IDX_CAMERA        = 1;
const IDX_TIPO_MATERIAL = 2;
const IDX_DATA_GRAVACAO = 3;
const IDX_OPERADOR      = 4;


// ── FUNÇÃO AUXILIAR: normalizar data ────────────────────────────────────────

/**
 * Recebe a data como o Forms entrega (pode ser "05/06/2026", "2026-06-05",
 * "June 5, 2026" etc.) e devolve sempre no formato "AAAA-MM-DD".
 * Se não conseguir interpretar, devolve a string original para não perder a info.
 *
 * @param {string} textoData - Data como veio do Forms.
 * @returns {string} Data no formato "AAAA-MM-DD" ou o texto original.
 */
function normalizarData(textoData) {
  if (!textoData || textoData.trim() === "") {
    return "";
  }

  var texto = textoData.trim();

  // Formato ISO já correto: "2026-06-05"
  if (/^\d{4}-\d{2}-\d{2}$/.test(texto)) {
    return texto;
  }

  // Formato brasileiro: "05/06/2026"
  var matchBR = texto.match(/^(\d{2})\/(\d{2})\/(\d{4})$/);
  if (matchBR) {
    // matchBR[1]=dia, matchBR[2]=mês, matchBR[3]=ano
    return matchBR[3] + "-" + matchBR[2] + "-" + matchBR[1];
  }

  // Formato americano: "06/05/2026" (mês/dia/ano)
  // Difícil distinguir do brasileiro automaticamente; o Google Forms em
  // locale pt-BR envia DD/MM/YYYY, então o caso acima já cobre o padrão
  // esperado no Brasil. Se o seu Forms estiver em inglês, ajuste o match acima.

  // Tenta o construtor nativo do JavaScript como último recurso
  try {
    var d = new Date(texto);
    if (!isNaN(d.getTime())) {
      var ano  = d.getFullYear();
      var mes  = String(d.getMonth() + 1).padStart(2, "0");
      var dia  = String(d.getDate()).padStart(2, "0");
      return ano + "-" + mes + "-" + dia;
    }
  } catch (e) {
    // Não conseguiu interpretar — devolve o original
  }

  // Fallback: devolve o texto como está para não perder a informação
  Logger.log("AVISO: não foi possível normalizar a data '" + texto + "'. Enviando como está.");
  return texto;
}


// ── FUNÇÃO PRINCIPAL: acionada pelo trigger "On form submit" ─────────────────

/**
 * Captura a resposta do formulário e envia os dados para o Flask local via POST.
 *
 * Esta função deve ser vinculada ao trigger "On form submit" no editor do
 * Google Apps Script. O Google a executa automaticamente cada vez que alguém
 * submete o formulário.
 *
 * @param {Object} e - Objeto de evento passado automaticamente pelo Google Forms.
 */
function aoEnviarFormulario(e) {

  // Coleta as respostas do formulário em ordem de posição
  var respostas = e.response.getItemResponses();

  // Lê cada campo pelo seu índice, com fallback para string vazia
  // caso o campo seja opcional e não tenha sido preenchido.
  var nome         = respostas[IDX_NOME]          ? respostas[IDX_NOME].getResponse()          : "";
  var camera       = respostas[IDX_CAMERA]        ? respostas[IDX_CAMERA].getResponse()        : "";
  var tipoMaterial = respostas[IDX_TIPO_MATERIAL] ? respostas[IDX_TIPO_MATERIAL].getResponse() : "";
  var dataRaw      = respostas[IDX_DATA_GRAVACAO] ? respostas[IDX_DATA_GRAVACAO].getResponse() : "";
  var operador     = respostas[IDX_OPERADOR]      ? respostas[IDX_OPERADOR].getResponse()      : "";

  // Normaliza a data para o formato AAAA-MM-DD antes de enviar
  var dataGravacao = normalizarData(dataRaw);

  // Monta o objeto JSON que será enviado ao Flask
  var payload = {
    nome:          nome.trim().toUpperCase(),        // ex.: "JOAO", "PAULO"
    camera:        camera.trim(),                   // ex.: "Blackmagic"
    tipo_material: tipoMaterial.trim().toUpperCase(), // ex.: "VIDEO"
    data_gravacao: dataGravacao,                    // ex.: "2026-06-05"
    operador:      operador.trim()                  // ex.: "João"
  };

  // Monta a URL completa do endpoint Flask
  var url = "http://" + IP_FLASK + ":" + PORTA_FLASK + "/forms";

  // Opções da requisição HTTP POST
  var opcoes = {
    method:             "post",
    contentType:        "application/json",
    payload:            JSON.stringify(payload),
    muteHttpExceptions: true,   // impede que o script trave em caso de erro HTTP
    followRedirects:    true,
    validateHttpsCertificates: false,
    // Nota: o Apps Script não tem opção de timeout direta; o TIMEOUT_MS
    // é registrado no log para referência, mas o controle real é do Google.
  };

  // Log de saída (visível em Apps Script > Execuções)
  Logger.log("GMA check-in | Enviando para: " + url);
  Logger.log("Payload: " + JSON.stringify(payload));

  // Tenta enviar. O try/catch garante que um erro de rede não trave o
  // processo — o set não pode parar por causa de conectividade.
  try {
    var resposta = UrlFetchApp.fetch(url, opcoes);
    var codigo   = resposta.getResponseCode();
    var corpo    = resposta.getContentText();

    if (codigo === 200 || codigo === 201) {
      Logger.log("SUCESSO (" + codigo + "): " + corpo);
    } else {
      // Flask respondeu, mas com erro — registra para diagnóstico
      Logger.log("AVISO — Flask retornou código " + codigo + ": " + corpo);
    }

  } catch (erro) {
    // Falha de rede ou Flask fora do ar — registra e segue
    // O operador pode verificar as execuções mais tarde no Apps Script.
    Logger.log("ERRO de conexão com o Flask: " + erro.toString());
    Logger.log("URL tentada: " + url);
    Logger.log("Dados que não foram entregues: " + JSON.stringify(payload));
    // Não relança o erro propositalmente: o Forms deve continuar funcionando
    // mesmo quando o Flask não está acessível.
  }
}


// ── FUNÇÃO DE TESTE MANUAL ──────────────────────────────────────────────────

/**
 * Use esta função para testar a conexão com o Flask SEM precisar preencher
 * o formulário. Rode ela manualmente no editor do Apps Script clicando em
 * "Executar" com esta função selecionada.
 *
 * Como usar:
 *   1. No editor do Apps Script, escolha "testarConexaoFlask" no menu de funções.
 *   2. Clique no botão "Executar" (triângulo).
 *   3. Acesse "Execuções" no menu lateral para ver o log.
 */
function testarConexaoFlask() {
  var url = "http://" + IP_FLASK + ":" + PORTA_FLASK + "/forms";

  // Dados fictícios para o teste
  var payloadTeste = {
    nome:          "TESTE_GMA",
    camera:        "Blackmagic",
    tipo_material: "VIDEO",
    data_gravacao: "2026-01-01",
    operador:      "Operador Teste"
  };

  var opcoes = {
    method:             "post",
    contentType:        "application/json",
    payload:            JSON.stringify(payloadTeste),
    muteHttpExceptions: true
  };

  Logger.log("=== TESTE DE CONEXÃO GMA ===");
  Logger.log("Alvo: " + url);
  Logger.log("Payload: " + JSON.stringify(payloadTeste));

  try {
    var resposta = UrlFetchApp.fetch(url, opcoes);
    Logger.log("Código HTTP: " + resposta.getResponseCode());
    Logger.log("Resposta:    " + resposta.getContentText());
    Logger.log("=== TESTE CONCLUÍDO ===");
  } catch (erro) {
    Logger.log("FALHA: " + erro.toString());
    Logger.log("Verifique se o Flask está rodando e se o IP está correto.");
    Logger.log("IP configurado: " + IP_FLASK + ":" + PORTA_FLASK);
  }
}
