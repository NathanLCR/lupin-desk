// Real Panel modules wired together (no stubs): runtime + grid + registry + model + widgets + arrange UI.
const assert = require('node:assert/strict');
const path = require('node:path');
const test = require('node:test');
const fakes = require('./panel-fakes.cjs');

const p = (f) => require(path.join(__dirname, '../../static/panel', f));
const PanelGrid = p('grid.js');
const PanelRegistry = p('registry.js');
const PanelArrangeModel = p('arrange-model.js');
const PanelWidgets = p('widgets.js');
const PanelArrangeUI = p('arrange-ui.js');
const runtime = p('runtime.js');

// widgets.js uses the global timers; keep them fake so the node process can exit.
global.setInterval = function () { return 1; };
global.clearInterval = function () {};

const LAYOUT = {
  id: 'starter', name: 'Starter', version: 1,
  grid: { landscape: { cols: 12, rows: 6 }, portrait: { cols: 6, rows: 12 } },
  pages: [{
    id: 'home', title: 'Home',
    landscape: [
      { id: 'a', type: 'clock', x: 0, y: 0, w: 8, h: 6, config: {} },
      { id: 'b', type: 'bomb', x: 8, y: 0, w: 4, h: 3, config: {} },
      { id: 'c', type: 'placeholder', x: 8, y: 3, w: 4, h: 3, config: {} },
    ],
    portrait: [{ id: 'a', type: 'clock', x: 0, y: 0, w: 6, h: 6, config: {} }],
  }],
};

function boot(roles) {
  const clock = fakes.makeClock();
  const net = fakes.makeNetwork();
  const registry = PanelRegistry.create();
  registry.register({ id: 'bomb', title: 'Bomb', render() { throw new Error('kaboom'); } });
  const win = {
    document: fakes.makeDocument(), innerWidth: 1280, innerHeight: 720,
    location: { protocol: 'http:', host: 'x:1' }, navigator: {},
    WebSocket: net.WebSocket, XMLHttpRequest: net.XMLHttpRequest,
    setTimeout: clock.setTimeout, clearTimeout: clock.clearTimeout,
    setInterval: clock.setInterval, clearInterval: clock.clearInterval,
    addEventListener() {},
    PanelGrid, PanelRegistry, PanelArrangeModel, PanelWidgets, PanelArrangeUI,
  };
  const panel = runtime.start({ win, doc: win.document, registry, wsUrl: 'ws://x/ws' });
  const sock = net.sockets[net.sockets.length - 1];
  sock.open();
  sock.message({ type: 'welcome', roles, layout_id: null });
  const get = net.xhrs.filter((x) => x.url.indexOf('/api/layouts/') === 0).pop();
  get.respond(200, LAYOUT);
  return { win, panel, sock, net };
}

test('real modules render the starter-style layout and a throwing widget fails alone', () => {
  const h = boot(['panel']);
  const root = h.win.document.body;
  const errors = fakes.findAll(root, (el) => el.classList.contains('pn-error'));
  assert.equal(errors.length, 1);
  const tiles = fakes.findAll(root, (el) => el.classList.contains('pn-tile'));
  assert.equal(tiles.length, 3);
  const clocks = fakes.findAll(root, (el) => el.classList.contains('pn-clock-time'));
  assert.equal(clocks.length, 1);
  assert.deepEqual(h.sock.sent.filter((m) => m.type === 'subscribe').pop().topics, ['layout']);
});

test('real modules: arranging saves a config-free payload', () => {
  const h = boot(['panel']);
  h.panel.arrange(0);
  assert.equal(h.panel.isArranging(), true);
});
