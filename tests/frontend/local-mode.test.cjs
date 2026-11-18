const assert = require('node:assert/strict');
const path = require('node:path');
const test = require('node:test');

const LocalMode = require(path.join(__dirname, '../../static/local_mode.js'));

test('local payload locks consent and turns all three sources on', () => {
  const view = LocalMode.consentView({ local: true, calendar: false, email: false, files: false, can_edit: true });

  assert.equal(view.local, true);
  assert.equal(view.editable, false);
  assert.deepEqual(view.on, { calendar: true, email: true, files: true });
  assert.equal(
    view.noteText,
    'Runs on this Mac with Ollama, so no permission is needed. Nothing leaves this Mac.',
  );
  assert.equal(view.rowText.calendar, 'Your calendar stays on this Mac');
  assert.equal(view.rowText.email, 'Your emails stay on this Mac');
  assert.equal(view.rowText.files, 'Your files stay on this Mac');
});

test('non-local payload that can be edited reflects settings and names the receiver', () => {
  const view = LocalMode.consentView({
    local: false,
    calendar: true,
    email: false,
    files: true,
    can_edit: true,
    receiver: 'Claude',
  });

  assert.equal(view.local, false);
  assert.equal(view.editable, true);
  assert.equal(view.noteText, '');
  assert.deepEqual(view.on, { calendar: true, email: false, files: true });
  assert.equal(view.rowText.calendar, 'Let Claude see your calendar');
  assert.equal(view.rowText.email, 'Let Claude see your emails');
  assert.equal(view.rowText.files, 'Let Claude see the contents of your files');
});

test('non-local payload that cannot be edited is read-only with a Mac note', () => {
  const view = LocalMode.consentView({ calendar: true, email: true, files: false, can_edit: false, receiver: 'OpenAI' });

  assert.equal(view.local, false);
  assert.equal(view.editable, false);
  assert.equal(view.noteText, 'This can only be changed on the Mac.');
  assert.deepEqual(view.on, { calendar: true, email: true, files: false });
  assert.equal(view.rowText.calendar, 'Let OpenAI see your calendar');
  assert.equal(view.rowText.files, 'Let OpenAI see the contents of your files');
});

test('non-local payload without a receiver falls back to "the provider"', () => {
  const view = LocalMode.consentView({ calendar: false, email: true, files: false, can_edit: true });

  assert.equal(view.rowText.calendar, 'Let the provider see your calendar');
  assert.equal(view.rowText.email, 'Let the provider see your emails');
  assert.equal(view.rowText.files, 'Let the provider see the contents of your files');
  assert.deepEqual(view.on, { calendar: false, email: true, files: false });
});

test('consentView tolerates a missing payload', () => {
  const view = LocalMode.consentView(null);

  assert.equal(view.local, false);
  assert.equal(view.editable, false);
  assert.deepEqual(view.on, { calendar: false, email: false, files: false });
  assert.equal(view.rowText.email, 'Let the provider see your emails');
  assert.equal(view.rowText.files, 'Let the provider see the contents of your files');
});

test('slowNoticeCaption returns the trimmed text of a valid slow_model notice', () => {
  const msg = { type: 'notice', kind: 'slow_model', text: '  Still thinking about that one.  ' };

  assert.equal(LocalMode.slowNoticeCaption(msg), 'Still thinking about that one.');
  assert.equal(LocalMode.isSlowNotice(msg), true);
});

test('slowNoticeCaption falls back to the default text when the notice text is empty', () => {
  const emptyText = { type: 'notice', kind: 'slow_model', text: '   ' };
  const missingText = { type: 'notice', kind: 'slow_model' };

  assert.equal(LocalMode.slowNoticeCaption(emptyText), 'The local model is taking a while...');
  assert.equal(LocalMode.slowNoticeCaption(missingText), 'The local model is taking a while...');
  assert.equal(LocalMode.isSlowNotice(emptyText), true);
});

test('slowNoticeCaption ignores notices of another kind', () => {
  const msg = { type: 'notice', kind: 'rate_limited', text: 'Slow down' };

  assert.equal(LocalMode.slowNoticeCaption(msg), null);
  assert.equal(LocalMode.isSlowNotice(msg), false);
});

test('slowNoticeCaption ignores messages of another type', () => {
  const msg = { type: 'reply', kind: 'slow_model', text: 'Hello' };

  assert.equal(LocalMode.slowNoticeCaption(msg), null);
  assert.equal(LocalMode.isSlowNotice(msg), false);
});

test('slowNoticeCaption and isSlowNotice handle null and undefined', () => {
  assert.equal(LocalMode.slowNoticeCaption(null), null);
  assert.equal(LocalMode.slowNoticeCaption(undefined), null);
  assert.equal(LocalMode.isSlowNotice(null), false);
  assert.equal(LocalMode.isSlowNotice(undefined), false);
});
