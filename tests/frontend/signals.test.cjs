const assert = require('node:assert/strict');
const path = require('node:path');
const test = require('node:test');

const Signals = require(path.join(__dirname, '../../static/signals.js'));

const notice = { type: 'notice', kind: 'signal', text: '  The build failed.  ' };

test('a signal notice becomes a caption', () => {
  const plan = Signals.noticePlan(notice, { ttsEnabled: false, ttsMode: 'browser', isLupinBody: true });
  assert.equal(plan.caption, 'The build failed.');
  assert.equal(plan.speakInBrowser, false);
});

test('a Body without server audio speaks the signal with browser TTS', () => {
  const plan = Signals.noticePlan(notice, { ttsEnabled: true, ttsMode: 'browser', isLupinBody: true });
  assert.equal(plan.speakInBrowser, true);
});

test('server audio mode leaves the voice to the audio chunks', () => {
  const plan = Signals.noticePlan(notice, { ttsEnabled: true, ttsMode: 'server', isLupinBody: true });
  assert.equal(plan.speakInBrowser, false);
});

test('a Body that is not Lupin does not speak', () => {
  const plan = Signals.noticePlan(notice, { ttsEnabled: true, ttsMode: 'browser', isLupinBody: false });
  assert.equal(plan.speakInBrowser, false);
});

test('other or empty notices are ignored', () => {
  assert.equal(Signals.noticePlan({ type: 'notice', kind: 'slow_model', text: 'x' }, {}), null);
  assert.equal(Signals.noticePlan({ type: 'notice', kind: 'signal', text: '  ' }, {}), null);
  assert.equal(Signals.noticePlan(null, {}), null);
});
