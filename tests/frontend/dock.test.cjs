const assert = require('node:assert/strict');
const test = require('node:test');
const { makeHarness, connected } = require('./harness.cjs');

const makeShortcuts = (n) =>
  Array.from({ length: n }, (_, i) => ({
    id: i + 1,
    slug: `s${i + 1}`,
    title: `Atalho ${i + 1}`,
    action_type: 'keystroke',
    payload: { keys: 'cmd+c' },
    pinned_on_deck: 1,
    sort_order: i,
  }));

function setup({ shortcuts = makeShortcuts(11), active = true } = {}) {
  const harness = makeHarness();
  connected(harness);
  const { app } = harness;
  harness.elements.get('btn-mode-nathan') || harness.document.getElementById('btn-mode-nathan');
  harness.elements.get('btn-mode-nathan').classList.add('hidden');
  app.state.ttsEnabled = false;
  app.state.shortcuts = shortcuts;
  app.handleWsMessage({ type: 'welcome', protocol: 1, active_body: active ? 'web' : 'esp32', active });
  app.setMode('dock');
  return harness;
}

const runTimer = (harness, id) => {
  const cb = harness.timers.get(id);
  assert.ok(cb, 'timer esperado');
  harness.timers.delete(id);
  cb();
};

test('grade 3x3 pagina de 9 em 9 e a última página é Apps abertos', () => {
  const harness = setup();
  const { app, elements } = harness;
  app.renderDock();
  assert.equal(app.dockPageCount(), 3);
  assert.equal(elements.get('shortcuts-grid').children.length, 9);
  app.setDockPage(1);
  assert.equal(elements.get('shortcuts-grid').children.length, 2);
  app.setDockPage(2);
  assert.ok(!elements.get('dock-apps-page').classList.contains('hidden'));
  assert.ok(elements.get('shortcuts-grid').classList.contains('hidden'));
  app.setDockPage(99);
  assert.equal(app.state.dockPage, 2, 'não passa da última página');
  app.setDockPage(-5);
  assert.equal(app.state.dockPage, 0);
});

test('só atalhos fixados entram na grade, ordenados por sort_order', () => {
  const list = makeShortcuts(3);
  list[0].pinned_on_deck = 0;
  list[1].sort_order = 9;
  list[2].sort_order = 1;
  const harness = setup({ shortcuts: list });
  harness.app.renderDock();
  const titles = harness.elements.get('shortcuts-grid').children.map((t) => t.getAttribute('aria-label'));
  assert.equal(titles.length, 2);
  assert.ok(titles[0].startsWith('Atalho 3'));
});

test('sem atalhos fixados mostra a mensagem de estado vazio', () => {
  const harness = setup({ shortcuts: [] });
  harness.app.renderDock();
  const grid = harness.elements.get('shortcuts-grid');
  assert.equal(grid.children.length, 1);
  assert.equal(grid.children[0].textContent, 'Nenhum atalho fixado. Escolha os atalhos no Mac.');
  assert.equal(harness.app.dockPageCount(), 2);
});

test('L2/R2 mudam de página no Dock e L1/R1 mudam de Modo', () => {
  const harness = setup();
  const { app } = harness;
  let handlers;
  harness.window.DeskGamepad = { init(h) { handlers = h; } };
  app.initGamepad();
  assert.equal(handlers.triggersAsPage(), true);
  handlers.onPage(1);
  assert.equal(app.state.dockPage, 1);
  handlers.onPage(-1);
  assert.equal(app.state.dockPage, 0);
  handlers.onModeCycle(1);
  assert.equal(app.state.mode, 'pet');
  assert.equal(app.state.dockPage, 0);
  assert.equal(handlers.triggersAsPage(), false, 'fora do Dock os gatilhos continuam sendo Push-to-Talk');
});

test('deslize vertical muda a página e o horizontal muda o Modo', () => {
  const harness = setup();
  const { app } = harness;
  app.applySwipe(0, -200, 200);
  assert.equal(app.state.dockPage, 1);
  app.applySwipe(0, 200, 200);
  assert.equal(app.state.dockPage, 0);
  app.applySwipe(-250, 0, 200);
  assert.equal(app.state.mode, 'pet');
});

test('canto: Lupin pequeno no Active Body e "Falar com Lupin" nos outros', () => {
  const ativo = setup({ active: true });
  const a = ativo.app;
  a.syncDockCorner();
  assert.ok(ativo.document.body.classList.contains('dock-lupin-corner'));
  assert.ok(ativo.elements.get('btn-dock-talk').classList.contains('hidden'));

  const outro = setup({ active: false });
  outro.app.syncDockCorner();
  assert.ok(!outro.document.body.classList.contains('dock-lupin-corner'));
  const btn = outro.elements.get('btn-dock-talk');
  assert.ok(!btn.classList.contains('hidden'));
  assert.equal(btn.textContent, 'Falar com Lupin');
});

test('tocar no Lupin pequeno abre o Pet Mode', () => {
  const harness = setup();
  harness.app.handleFaceTap();
  assert.equal(harness.app.state.mode, 'pet');
});

test('"Falar com Lupin": toque abre o texto e segurar grava o microfone', async () => {
  const harness = setup({ active: false });
  const { app, elements, mediaRecorders } = harness;
  app.dockTalkDown();
  app.dockTalkUp();
  assert.ok(document_hasTextOpen(harness));
  assert.equal(mediaRecorders.length, 0);

  app.dockTalkDown();
  runTimer(harness, app.state.dockTalk.holdTimer);
  await new Promise((r) => setImmediate(r));
  assert.equal(mediaRecorders.length, 1);
  assert.ok(app.state.ptt.active);
  app.dockTalkUp();
  assert.ok(elements.get('btn-dock-talk'));
});

function document_hasTextOpen(harness) {
  return harness.document.body.classList.contains('dock-text-open');
}

test('resposta curta fica no Dock com a fala em uma linha', () => {
  const harness = setup();
  const { app, elements } = harness;
  app.handleWsMessage({ type: 'sentence', text: 'Oi, tudo bem?' });
  app.handleWsMessage({ type: 'sentence', text: 'Que bom te ver.' });
  assert.equal(app.state.mode, 'dock');
  assert.equal(elements.get('dock-speech-strip').textContent, 'Que bom te ver.');
  app.handleWsMessage({ type: 'done', text: 'Oi, tudo bem? Que bom te ver.' });
  assert.equal(app.state.mode, 'dock');
  assert.equal(app.state.dockSentenceCount, 0);
  // a faixa some 4 s depois que a fala termina
  runTimer(harness, app.state.dockStripTimer);
  assert.equal(elements.get('dock-speech-strip').textContent, '');
});

test('a 3a frase vai para o Pet e volta ao Dock 5 s depois da fala', () => {
  const harness = setup();
  const { app } = harness;
  ['Um.', 'Dois.', 'Três.'].forEach((text) => app.handleWsMessage({ type: 'sentence', text }));
  assert.equal(app.state.mode, 'pet');
  assert.equal(app.state.autoPetFromDock, true);
  app.handleWsMessage({ type: 'done', text: 'Um. Dois. Três.' });
  assert.equal(app.state.mode, 'pet', 'ainda não voltou');
  runTimer(harness, app.state.dockReturnTimer);
  assert.equal(app.state.mode, 'dock');
  assert.equal(app.state.autoPetFromDock, false);
});

test('First Wake vai para o Pet logo na primeira frase', () => {
  const harness = setup();
  harness.app.handleWsMessage({ type: 'sentence', text: 'Bom dia!', first_wake: true });
  assert.equal(harness.app.state.mode, 'pet');
  assert.equal(harness.app.state.autoPetFromDock, true);
});

test('qualquer interação do usuário cancela a volta automática', () => {
  const harness = setup();
  const { app } = harness;
  ['Um.', 'Dois.', 'Três.'].forEach((text) => app.handleWsMessage({ type: 'sentence', text }));
  app.handleWsMessage({ type: 'done', text: 'x' });
  app.noteUserInput();
  assert.equal(app.state.autoPetFromDock, false);
  assert.equal(app.state.dockReturnTimer, null);
  assert.equal(app.state.mode, 'pet');
});

test('quem foi ao Pet por conta própria não volta sozinho', () => {
  const harness = setup();
  const { app } = harness;
  app.setMode('pet');
  ['Um.', 'Dois.', 'Três.'].forEach((text) => app.handleWsMessage({ type: 'sentence', text }));
  app.handleWsMessage({ type: 'done', text: 'x' });
  assert.equal(app.state.autoPetFromDock, false);
  assert.equal(app.state.dockReturnTimer, null);
  assert.equal(app.state.mode, 'pet');
});

test('mudar de modo manualmente também cancela a volta', () => {
  const harness = setup();
  const { app } = harness;
  ['Um.', 'Dois.', 'Três.'].forEach((text) => app.handleWsMessage({ type: 'sentence', text }));
  app.setMode('dock');
  assert.equal(app.state.autoPetFromDock, false);
});

test('aparelho fora do Active Body só mostra texto, sem áudio nem troca de modo', () => {
  const harness = setup({ active: false });
  const { app, elements } = harness;
  app.state.ttsMode = 'browser';
  ['Um.', 'Dois.', 'Três.', 'Quatro.'].forEach((text) => app.handleWsMessage({ type: 'sentence', text }));
  assert.equal(app.state.mode, 'dock');
  assert.equal(app.state.ttsQueue.length, 0);
  assert.equal(app.state.autoPetFromDock, false);
  assert.equal(elements.get('dock-speech-strip').textContent, 'Quatro.');
});

test('lista nos Ajustes: só leitura fora do Mac, editor no Mac', () => {
  const harness = setup();
  const { app, elements } = harness;
  app.state.isMac = false;
  app.renderSettingsShortcuts();
  assert.ok(elements.get('settings-dock-editor').classList.contains('hidden'));
  app.state.isMac = true;
  app.renderSettingsShortcuts();
  assert.ok(!elements.get('settings-dock-editor').classList.contains('hidden'));
});

test('a volta ao Dock só é agendada depois que a voz termina de tocar', () => {
  const harness = setup();
  const { app } = harness;
  ['Um.', 'Dois.', 'Três.'].forEach((text) => app.handleWsMessage({ type: 'sentence', text }));
  app.state.ttsPlaying = true;
  app.handleWsMessage({ type: 'done', text: 'x' });
  assert.equal(app.state.dockReturnTimer, null);
  app.state.ttsPlaying = false;
  app.handleWsMessage({ type: 'error', message: 'fim' });
  assert.notEqual(app.state.dockReturnTimer, null);
});

test('Data Consent: texto nomeia o receptor; editável só no Mac', () => {
  const harness = setup();
  const { app, elements } = harness;
  const agenda = harness.document.getElementById('btn-consent-agenda');
  app.state.dataConsent = { agenda: true, email: false, receiver: 'Proxy Local (127.0.0.1:31415)', can_edit: false };
  app.renderDataConsent();
  assert.equal(
    elements.get('consent-agenda-label').textContent,
    'Permitir que Proxy Local (127.0.0.1:31415) veja sua agenda',
  );
  assert.equal(
    elements.get('consent-email-label').textContent,
    'Permitir que Proxy Local (127.0.0.1:31415) veja seus e-mails',
  );
  assert.equal(agenda.disabled, true);
  assert.equal(agenda.textContent, 'Ligado');
  assert.ok(!elements.get('consent-note').classList.contains('hidden'));
  app.state.dataConsent.can_edit = true;
  app.renderDataConsent();
  assert.equal(agenda.disabled, false);
  assert.ok(elements.get('consent-note').classList.contains('hidden'));
});
