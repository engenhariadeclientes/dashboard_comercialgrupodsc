/**
 * Cole este script em: Google Forms -> menu de tres pontinhos -> Editor de script
 * (ou Extensoes > Apps Script, dependendo da versao do Forms).
 *
 * Depois:
 * 1. Rode a funcao `configurarGatilho` uma vez manualmente (Executar > configurarGatilho).
 *    Na primeira vez ele vai pedir autorizacao — aceite.
 * 2. Pronto. A cada resposta nova do formulario, `aoReceberResposta` roda sozinha
 *    e manda os dados pro nosso webhook.
 *
 * Os nomes em PERGUNTAS abaixo tem que ser EXATAMENTE iguais ao texto da
 * pergunta no formulario (copie e cole do proprio Forms pra evitar erro de
 * digitacao/acento).
 */

var WEBHOOK_URL = 'https://webhook-form-leads-production.up.railway.app/webhook/formulario-lead';

var PERGUNTAS = {
  nome: 'Nome completo',
  email: 'Enviar e-mail',
  telefone: 'Número de telefone',
  cidade: 'Cidade',
  estado: 'Estado',
  cargo: 'Cargo'
};

function configurarGatilho() {
  // remove gatilhos antigos desta funcao pra nao duplicar se rodar de novo
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === 'aoReceberResposta') {
      ScriptApp.deleteTrigger(t);
    }
  });
  var form = FormApp.getActiveForm();
  ScriptApp.newTrigger('aoReceberResposta')
    .forForm(form)
    .onFormSubmit()
    .create();
  Logger.log('Gatilho criado com sucesso.');
}

function aoReceberResposta(e) {
  var valores = e.namedValues; // { "Nome completo": ["Fulano"], ... }

  function pegar(pergunta) {
    var v = valores[pergunta];
    return v && v.length ? v[0] : '';
  }

  var payload = {
    nome: pegar(PERGUNTAS.nome),
    email: pegar(PERGUNTAS.email),
    telefone: pegar(PERGUNTAS.telefone),
    cidade: pegar(PERGUNTAS.cidade),
    estado: pegar(PERGUNTAS.estado),
    cargo: pegar(PERGUNTAS.cargo)
  };

  var opcoes = {
    method: 'post',
    contentType: 'application/json',
    payload: JSON.stringify(payload),
    muteHttpExceptions: true
  };

  var resposta = UrlFetchApp.fetch(WEBHOOK_URL, opcoes);
  Logger.log('Status: ' + resposta.getResponseCode());
  Logger.log('Corpo: ' + resposta.getContentText());
}
