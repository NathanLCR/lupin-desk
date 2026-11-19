const assert = require('node:assert/strict');
const test = require('node:test');
const presence = require('../../static/presence.js');

test('normalize applies defaults and clamps the interval', () => {
  assert.deepEqual(presence.normalize(null), {
    breakEnabled: true, breakMinutes: 50, breakMin: 20, breakMax: 240, frontApp: false, frontAppLocal: false,
  });
  const s = presence.normalize({ break_enabled: false, break_minutes: 999, front_app: true, front_app_local: true });
  assert.equal(s.breakEnabled, false);
  assert.equal(s.breakMinutes, 240);
  assert.equal(s.frontApp, true);
  assert.equal(s.frontAppLocal, true);
});

test('buildChange validates and clamps', () => {
  assert.deepEqual(presence.buildChange('break_minutes', '5'), { break_minutes: 20 });
  assert.deepEqual(presence.buildChange('break_minutes', 60), { break_minutes: 60 });
  assert.equal(presence.buildChange('break_minutes', 'abc'), null);
  assert.deepEqual(presence.buildChange('front_app', 1), { front_app: true });
  assert.deepEqual(presence.buildChange('break_enabled', false), { break_enabled: false });
  assert.equal(presence.buildChange('other', 1), null);
});

test('receiverLabel names the receiver', () => {
  assert.match(presence.receiverLabel('Proxy (x)'), /Proxy \(x\)/);
  assert.match(presence.receiverLabel(''), /the provider/);
});

test('mount is a no-op without the consent note', () => {
  const doc = { getElementById: () => null };
  presence.mount(doc);
});
