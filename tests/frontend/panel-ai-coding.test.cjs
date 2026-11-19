const assert = require('node:assert/strict');
const path = require('node:path');
const test = require('node:test');

const { makeDocument, findAll } = require('./panel-fakes.cjs');
const Widgets = require(path.join(__dirname, '../../static/panel/widgets-ai-coding.js'));
const PanelRegistry = require(path.join(__dirname, '../../static/panel/registry.js'));

function stubXhr(answers) {
  const calls = [];
  class Xhr {
    open(method, url) { this.url = url; calls.push(url); }
    send() {
      const hit = answers[this.url];
      setTimeout(() => {
        if (hit === undefined) { this.status = 404; this.responseText = ''; } else {
          this.status = 200; this.responseText = JSON.stringify(hit);
        }
        if (this.onload) this.onload();
      }, 0);
    }
  }
  return { Xhr, calls };
}

function render(id, answers, sent) {
  const stub = stubXhr(answers || {});
  const previous = global.XMLHttpRequest;
  global.XMLHttpRequest = stub.Xhr;
  const doc = makeDocument();
  const host = doc.createElement('div');
  doc.body.appendChild(host);
  const def = Widgets.DEFS.filter((d) => d.id === id)[0];
  let instance;
  try {
    instance = def.render(host, { config: {}, sendAction: (a, b) => sent.push([a, b]), now: () => 1000 * 1000, el: host });
  } finally {
    global.XMLHttpRequest = previous;
  }
  return { host, instance, stub };
}

const byClass = (root, name) => findAll(root, (n) => !!n.classList && n.classList.contains(name));
const allText = (root) => findAll(root, () => true).map((n) => n.textContent).join('|');
const tick = () => new Promise((resolve) => setTimeout(resolve, 5));

const SNAPSHOT = {
  sessions: [
    { tool: 'claude', id: 'a', project: 'desk <b>', model: 'claude-x', status: 'active', duration_seconds: 3700, tokens: 12345, cached_tokens: 0 },
    { tool: 'codex', id: 'b', project: 'other', model: 'gpt-x', status: 'ended', duration_seconds: 60, tokens: 50, cached_tokens: 0 },
  ],
  quotas: {
    claude: { limits: [], daily_tokens: [{ day: '2026-11-18', tokens: 100 }, { day: '2026-11-19', tokens: 50 }] },
    codex: { limits: [{ name: 'primary', used_percent: 40, window_minutes: 10080, resets_at: 1000 + 7200,
      forecast: { projected_percent_at_reset: 120, exhausted_in_minutes: 90 } }], daily_tokens: [] },
  },
  github: { available: true, repos: [{ repo: 'me/desk', ci: { conclusion: 'failure', branch: 'main' },
    reviews: [{ number: 3, title: 'Fix it' }] }] },
};

test('registers all four widgets with their topics and actions', () => {
  const registry = PanelRegistry.create();
  Widgets.registerAll(registry);
  Widgets.registerAll(registry); // idempotent
  assert.deepEqual(registry.list().map((d) => d.id).sort(), ['ai-github', 'ai-permissions', 'ai-quotas', 'ai-sessions']);
  assert.deepEqual(registry.get('ai-permissions').actions, ['ai_coding_answer', 'ai_coding_prompt_shown']);
  assert.deepEqual(registry.topicsFor([{ type: 'ai-permissions' }, { type: 'ai-sessions' }]), ['ai-coding', 'ai-coding-prompts']);
});

test('format helpers', () => {
  assert.equal(Widgets.formatTokens(12345), '12.3k');
  assert.equal(Widgets.formatTokens(2500000), '2.5M');
  assert.equal(Widgets.formatTokens(null), '--');
  assert.equal(Widgets.formatDuration(3700), '1 h 1 min');
  assert.equal(Widgets.formatReset(1000 + 7200, 1000 * 1000), 'in 2 h 0 min');
  assert.equal(Widgets.formatReset(5, 1000 * 1000), 'now');
});

test('sessions widget loads the snapshot, then follows the topic; text is never markup', async () => {
  const { host, instance } = render('ai-sessions', { '/api/ai-coding/snapshot': SNAPSHOT }, []);
  await tick();
  assert.deepEqual(byClass(host, 'pn-ai-project').map((n) => n.textContent), ['desk <b>', 'other']);
  assert.ok(allText(host).includes('12.3k tokens'));
  instance.onTopic('ai-coding', { sessions: [] });
  assert.ok(allText(host).includes('No sessions'));
  instance.onTopic('other-topic', SNAPSHOT);
  assert.ok(allText(host).includes('No sessions'));
});

test('a topic message that arrives before the first load is not overwritten by it', async () => {
  const { host, instance } = render('ai-sessions', { '/api/ai-coding/snapshot': SNAPSHOT }, []);
  instance.onTopic('ai-coding', { sessions: [] });
  await tick();
  assert.ok(allText(host).includes('No sessions'));
});

test('quotas widget shows a real limit with its forecast and never an invented one', async () => {
  const withLimit = render('ai-quotas', { '/api/ai-coding/snapshot': SNAPSHOT }, []);
  await tick();
  const text = allText(withLimit.host);
  assert.ok(text.includes('40% used') && text.includes('Resets in 2 h 0 min'));
  assert.ok(text.includes('120% at reset') && text.includes('runs out in 1 h 30 min'));

  const noLimit = JSON.parse(JSON.stringify(SNAPSHOT));
  noLimit.quotas.codex.limits = [];
  const bare = render('ai-quotas', { '/api/ai-coding/snapshot': noLimit }, []);
  await tick();
  assert.ok(allText(bare.host).includes('tokens per day'));
  assert.ok(!allText(bare.host).includes('% used'));
});

test('github widget shows CI, reviews and the not-logged-in state', async () => {
  const ok = render('ai-github', { '/api/ai-coding/snapshot': SNAPSHOT }, []);
  await tick();
  const text = allText(ok.host);
  assert.ok(text.includes('me/desk') && text.includes('CI failure on main') && text.includes('Review #3 Fix it'));
  ok.instance.onTopic('ai-coding', { github: { available: false, repos: [] } });
  assert.ok(allText(ok.host).includes('gh auth login'));
});

test('widgets survive a failed load and garbage data', async () => {
  const down = render('ai-sessions', {}, []);
  await tick();
  assert.ok(allText(down.host).includes('Could not reach the Mac'));
  down.instance.onTopic('ai-coding', 'junk');
  down.instance.onTopic('ai-coding', { sessions: [null, 3, { status: 5 }], quotas: 7, github: [] });
  down.instance.destroy();
  down.instance.onTopic('ai-coding', SNAPSHOT);
});

test('permission widget shows the full command and sends Allow or Deny with the one-time id', () => {
  const sent = [];
  const { host, instance } = render('ai-permissions', {}, sent);
  assert.ok(allText(host).includes('No permission prompts'));
  instance.onTopic('ai-coding-prompts', { prompts: [{ id: 'p-1', project: 'desk', tool: 'Bash', args: 'rm -rf build' }] });
  assert.ok(allText(host).includes('Bash: rm -rf build'));
  assert.ok(allText(host).includes('Claude needs you'));
  const [allow] = byClass(host, 'pn-ai-allow');
  const [deny] = byClass(host, 'pn-ai-deny');
  allow.fire('click', {});
  deny.fire('click', {});
  assert.deepEqual(sent.filter((s) => s[0] === 'ai_coding_answer'), [['ai_coding_answer', { id: 'p-1', decision: 'allow' }], ['ai_coding_answer', { id: 'p-1', decision: 'deny' }]]);
  instance.onTopic('ai-coding-prompts', { prompts: [] });
  assert.equal(byClass(host, 'pn-ai-allow').length, 0);
  instance.onTopic('ai-coding-prompts', { prompts: [{ project: 'no id' }, null] });
  assert.equal(byClass(host, 'pn-ai-allow').length, 0);
});

test('permission widget acks a prompt only while its page is visible, and withdraws the ack', () => {
  const sent = [];
  const { host, instance } = render('ai-permissions', {}, sent);
  const doc = host.ownerDocument;
  const acks = () => sent.filter((s) => s[0] === 'ai_coding_prompt_shown').map((s) => s[1]);
  instance.onTopic('ai-coding-prompts', { prompts: [{ id: 'p-1', project: 'd', tool: 'Bash', args: 'ls' }] });
  assert.deepEqual(acks(), [{ id: 'p-1', visible: true }]);
  // the page is hidden: the ack is withdrawn
  doc.visibilityState = 'hidden';
  doc.fire('visibilitychange', {});
  assert.deepEqual(acks().pop(), { id: 'p-1', visible: false });
  const before = sent.length;
  instance.onTopic('ai-coding-prompts', { prompts: [{ id: 'p-1', project: 'd', tool: 'Bash', args: 'ls' }] });
  assert.equal(sent.length, before); // nothing acked while hidden
  // visible again: acked again
  doc.visibilityState = 'visible';
  doc.fire('visibilitychange', {});
  assert.deepEqual(acks().pop(), { id: 'p-1', visible: true });
  // the prompt goes away: withdrawn
  instance.onTopic('ai-coding-prompts', { prompts: [] });
  assert.deepEqual(acks().pop(), { id: 'p-1', visible: false });
  // destroy withdraws whatever is still shown
  instance.onTopic('ai-coding-prompts', { prompts: [{ id: 'p-2', project: 'd', tool: 'Bash', args: 'ls' }] });
  instance.destroy();
  assert.deepEqual(acks().pop(), { id: 'p-2', visible: false });
});
