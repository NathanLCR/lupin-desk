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
  assert.ok(cb, 'expected timer');
  harness.timers.delete(id);
  cb();
};

test('3x3 grid paginates 9 at a time and the last page is Open apps', () => {
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
  assert.equal(app.state.dockPage, 2, 'does not go past the last page');
  app.setDockPage(-5);
  assert.equal(app.state.dockPage, 0);
});

test('only pinned shortcuts enter the grid, ordered by sort_order', () => {
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

test('with no pinned shortcuts shows the empty-state message', () => {
  const harness = setup({ shortcuts: [] });
  harness.app.renderDock();
  const grid = harness.elements.get('shortcuts-grid');
  assert.equal(grid.children.length, 1);
  assert.equal(grid.children[0].textContent, 'No pinned shortcuts. Choose shortcuts on the Mac.');
  assert.equal(harness.app.dockPageCount(), 2);
});

test('L2/R2 change page in the Dock and L1/R1 change Mode', () => {
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
  assert.equal(handlers.triggersAsPage(), false, 'outside the Dock the triggers remain Push-to-Talk');
});

test('vertical swipe changes the page and horizontal changes the Mode', () => {
  const harness = setup();
  const { app } = harness;
  app.applySwipe(0, -200, 200);
  assert.equal(app.state.dockPage, 1);
  app.applySwipe(0, 200, 200);
  assert.equal(app.state.dockPage, 0);
  app.applySwipe(-250, 0, 200);
  assert.equal(app.state.mode, 'pet');
});

test('corner: small Lupin in the Active Body and "Talk to Lupin" in the others', () => {
  const active = setup({ active: true });
  const a = active.app;
  a.syncDockCorner();
  assert.ok(active.document.body.classList.contains('dock-lupin-corner'));
  assert.ok(active.elements.get('btn-dock-talk').classList.contains('hidden'));

  const other = setup({ active: false });
  other.app.syncDockCorner();
  assert.ok(!other.document.body.classList.contains('dock-lupin-corner'));
  const btn = other.elements.get('btn-dock-talk');
  assert.ok(!btn.classList.contains('hidden'));
  assert.equal(btn.textContent, 'Talk to Lupin');
});

test('tapping the small Lupin opens Pet Mode', () => {
  const harness = setup();
  harness.app.handleFaceTap();
  assert.equal(harness.app.state.mode, 'pet');
});

test('"Talk to Lupin": tap opens the text input and holding records the microphone', async () => {
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

test('a short reply stays in the Dock with the speech on one line', () => {
  const harness = setup();
  const { app, elements } = harness;
  app.handleWsMessage({ type: 'sentence', text: 'Oi, tudo bem?' });
  app.handleWsMessage({ type: 'sentence', text: 'Que bom te ver.' });
  assert.equal(app.state.mode, 'dock');
  assert.equal(elements.get('dock-speech-strip').textContent, 'Que bom te ver.');
  app.handleWsMessage({ type: 'done', text: 'Oi, tudo bem? Que bom te ver.' });
  assert.equal(app.state.mode, 'dock');
  assert.equal(app.state.dockSentenceCount, 0);
  // the strip disappears 4 s after the speech ends
  runTimer(harness, app.state.dockStripTimer);
  assert.equal(elements.get('dock-speech-strip').textContent, '');
});

test('the 3rd sentence goes to Pet and returns to the Dock 5 s after the speech', () => {
  const harness = setup();
  const { app } = harness;
  ['Um.', 'Dois.', 'Três.'].forEach((text) => app.handleWsMessage({ type: 'sentence', text }));
  assert.equal(app.state.mode, 'pet');
  assert.equal(app.state.autoPetFromDock, true);
  app.handleWsMessage({ type: 'done', text: 'Um. Dois. Três.' });
  assert.equal(app.state.mode, 'pet', 'has not returned yet');
  runTimer(harness, app.state.dockReturnTimer);
  assert.equal(app.state.mode, 'dock');
  assert.equal(app.state.autoPetFromDock, false);
});

test('First Wake goes to Pet right on the first sentence', () => {
  const harness = setup();
  harness.app.handleWsMessage({ type: 'sentence', text: 'Bom dia!', first_wake: true });
  assert.equal(harness.app.state.mode, 'pet');
  assert.equal(harness.app.state.autoPetFromDock, true);
});

test('any user interaction cancels the automatic return', () => {
  const harness = setup();
  const { app } = harness;
  ['Um.', 'Dois.', 'Três.'].forEach((text) => app.handleWsMessage({ type: 'sentence', text }));
  app.handleWsMessage({ type: 'done', text: 'x' });
  app.noteUserInput();
  assert.equal(app.state.autoPetFromDock, false);
  assert.equal(app.state.dockReturnTimer, null);
  assert.equal(app.state.mode, 'pet');
});

test('whoever went to Pet on their own does not return by themselves', () => {
  const harness = setup();
  const { app } = harness;
  app.setMode('pet');
  ['Um.', 'Dois.', 'Três.'].forEach((text) => app.handleWsMessage({ type: 'sentence', text }));
  app.handleWsMessage({ type: 'done', text: 'x' });
  assert.equal(app.state.autoPetFromDock, false);
  assert.equal(app.state.dockReturnTimer, null);
  assert.equal(app.state.mode, 'pet');
});

test('switching mode manually also cancels the return', () => {
  const harness = setup();
  const { app } = harness;
  ['Um.', 'Dois.', 'Três.'].forEach((text) => app.handleWsMessage({ type: 'sentence', text }));
  app.setMode('dock');
  assert.equal(app.state.autoPetFromDock, false);
});

test('a device outside the Active Body only shows text, with no audio or mode switch', () => {
  const harness = setup({ active: false });
  const { app, elements } = harness;
  app.state.ttsMode = 'browser';
  ['Um.', 'Dois.', 'Três.', 'Quatro.'].forEach((text) => app.handleWsMessage({ type: 'sentence', text }));
  assert.equal(app.state.mode, 'dock');
  assert.equal(app.state.ttsQueue.length, 0);
  assert.equal(app.state.autoPetFromDock, false);
  assert.equal(elements.get('dock-speech-strip').textContent, 'Quatro.');
});

test('list in Settings: read-only off the Mac, editor on the Mac', () => {
  const harness = setup();
  const { app, elements } = harness;
  app.state.isMac = false;
  app.renderSettingsShortcuts();
  assert.ok(elements.get('settings-dock-editor').classList.contains('hidden'));
  app.state.isMac = true;
  app.renderSettingsShortcuts();
  assert.ok(!elements.get('settings-dock-editor').classList.contains('hidden'));
});

test('the return to the Dock is only scheduled after the voice finishes playing', () => {
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

test('Data Consent: text names the receiver; editable only on the Mac', () => {
  const harness = setup();
  const { app, elements } = harness;
  const calendar = harness.document.getElementById('btn-consent-calendar');
  app.state.dataConsent = { calendar: true, email: false, receiver: 'Proxy Local (127.0.0.1:31415)', can_edit: false };
  app.renderDataConsent();
  assert.equal(
    elements.get('consent-calendar-label').textContent,
    'Let Proxy Local (127.0.0.1:31415) see your calendar',
  );
  assert.equal(
    elements.get('consent-email-label').textContent,
    'Let Proxy Local (127.0.0.1:31415) see your emails',
  );
  assert.equal(calendar.disabled, true);
  assert.equal(calendar.textContent, 'On');
  assert.ok(!elements.get('consent-note').classList.contains('hidden'));
  app.state.dataConsent.can_edit = true;
  app.renderDataConsent();
  assert.equal(calendar.disabled, false);
  assert.ok(elements.get('consent-note').classList.contains('hidden'));
});
