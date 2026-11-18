const assert = require('node:assert/strict');
const fs = require('node:fs');
const nodeCrypto = require('node:crypto');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const sourcePath = path.join(__dirname, '../../static/device.js');
const deviceSource = fs.readFileSync(sourcePath, 'utf8');

const ID_PATTERN = /^[A-Za-z0-9_-]{8,64}$/;

function makeStorage(store, mode) {
  if (mode === 'throw') {
    const deny = () => {
      throw new Error('storage denied');
    };
    return { getItem: deny, setItem: deny, removeItem: deny };
  }
  return {
    getItem: (key) => (store.has(key) ? store.get(key) : null),
    setItem: (key, value) => store.set(key, String(value)),
    removeItem: (key) => store.delete(key),
  };
}

const uuidCrypto = {
  randomUUID: () => nodeCrypto.randomUUID(),
  getRandomValues: (arr) => nodeCrypto.randomFillSync(arr),
};

function loadDevice(options = {}) {
  const store = options.store || new Map();
  const win = {
    innerWidth: 'innerWidth' in options ? options.innerWidth : 1024,
    innerHeight: 'innerHeight' in options ? options.innerHeight : 768,
    devicePixelRatio: options.dpr,
    screen: options.screen,
    localStorage: options.noStorage ? undefined : makeStorage(store, options.storageMode),
    navigator: options.noNavigator ? undefined : { userAgent: options.ua || 'Mozilla/5.0 (X11; Linux x86_64)' },
    crypto: options.crypto === undefined ? uuidCrypto : options.crypto,
    location: options.noLocation ? undefined : { search: options.search || '' },
  };
  win.window = win;
  vm.createContext(win);
  vm.runInContext(deviceSource, win);
  return { device: win.DeskDevice, win, store };
}

test('ID is generated once and stays stable across calls and reloads', () => {
  const store = new Map();
  const first = loadDevice({ store }).device;
  const id1 = first.getId();
  const id2 = first.getId();
  assert.equal(id1, id2);
  assert.equal(store.get('desk.deviceId'), id1);

  const second = loadDevice({ store }).device;
  assert.equal(second.getId(), id1);
});

test('generated ID matches the allowed pattern and carries the d- prefix', () => {
  const { device } = loadDevice();
  const id = device.getId();
  assert.match(id, ID_PATTERN);
  assert.ok(id.startsWith('d-'));
});

test('ID generation works without randomUUID and without crypto at all', () => {
  const noUuid = loadDevice({ crypto: { getRandomValues: (arr) => nodeCrypto.randomFillSync(arr) } });
  assert.match(noUuid.device.getId(), ID_PATTERN);

  const noCrypto = loadDevice({ crypto: undefined });
  assert.match(noCrypto.device.getId(), ID_PATTERN);
});

test('ID stays stable within one page load when localStorage throws', () => {
  const { device, store } = loadDevice({ storageMode: 'throw' });
  const id = device.getId();
  assert.match(id, ID_PATTERN);
  assert.equal(device.getId(), id);
  assert.equal(store.size, 0);
});

test('ID works when localStorage is missing entirely', () => {
  const { device } = loadDevice({ noStorage: true });
  const id = device.getId();
  assert.match(id, ID_PATTERN);
  assert.equal(device.getId(), id);
});

test('an invalid stored ID is replaced with a valid one', () => {
  const store = new Map([['desk.deviceId', 'bad id!']]);
  const { device } = loadDevice({ store });
  const id = device.getId();
  assert.match(id, ID_PATTERN);
  assert.equal(store.get('desk.deviceId'), id);
});

test('name guesses from the user agent', () => {
  const cases = [
    ['Mozilla/5.0 (Linux; U; Android 4.0.3; en-us; Kindle Fire) AppleWebKit', 'Kindle'],
    ['Mozilla/5.0 (iPad; CPU OS 16_0 like Mac OS X)', 'iPad'],
    ['Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)', 'iPhone'],
    ['Mozilla/5.0 (Linux; Android 13; RG406H) Chrome/120', 'Android device'],
    ['Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0)', 'Mac browser'],
    ['Mozilla/5.0 (Windows NT 10.0; Win64; x64)', 'Windows browser'],
    ['Mozilla/5.0 (X11; Linux x86_64)', 'Linux browser'],
    ['SomethingElse/1.0', 'Browser'],
  ];
  for (const [ua, expected] of cases) {
    const { device } = loadDevice({ ua });
    assert.equal(device.getName(), expected, ua);
  }
});

test('getName does not throw when navigator is missing', () => {
  const { device } = loadDevice({ noNavigator: true });
  assert.equal(device.getName(), 'Browser');
});

test('setName stores a trimmed name capped at 60 characters and getName returns it', () => {
  const store = new Map();
  const { device } = loadDevice({ store });
  const long = '   ' + 'x'.repeat(80) + '   ';
  device.setName(long);
  assert.equal(store.get('desk.deviceName'), 'x'.repeat(60));
  assert.equal(device.getName(), 'x'.repeat(60));

  const reloaded = loadDevice({ store }).device;
  assert.equal(reloaded.getName(), 'x'.repeat(60));
});

test('setName does not throw when storage throws', () => {
  const { device } = loadDevice({ storageMode: 'throw' });
  assert.doesNotThrow(() => device.setName('Desk'));
  assert.equal(device.getName(), 'Linux browser');
});

test('getScreen reports size, dpr and landscape orientation', () => {
  const { device } = loadDevice({ innerWidth: 960, innerHeight: 720, dpr: 2 });
  const screen = JSON.parse(JSON.stringify(device.getScreen()));
  assert.deepEqual(screen, {
    width: 960,
    height: 720,
    dpr: 2,
    orientation: 'landscape',
    eink: false,
  });
});

test('getScreen reports portrait orientation and defaults dpr to 1', () => {
  const { device } = loadDevice({ innerWidth: 400, innerHeight: 800 });
  const screen = device.getScreen();
  assert.equal(screen.orientation, 'portrait');
  assert.equal(screen.dpr, 1);
});

test('getScreen falls back to screen dimensions when inner size is missing', () => {
  const { device } = loadDevice({ innerWidth: undefined, innerHeight: undefined, screen: { width: 640, height: 480 } });
  const screen = device.getScreen();
  assert.equal(screen.width, 640);
  assert.equal(screen.height, 480);
});

test('getScreen sets eink when the UA contains Kindle', () => {
  const { device } = loadDevice({ ua: 'Mozilla/5.0 (Linux; Kindle/3.0)' });
  assert.equal(device.getScreen().eink, true);
});

test('getScreen sets eink when the URL has eink=1', () => {
  const { device } = loadDevice({ search: '?foo=bar&eink=1' });
  assert.equal(device.getScreen().eink, true);
});

test('getScreen does not set eink for eink=10 or without the flag', () => {
  assert.equal(loadDevice({ search: '?eink=10' }).device.getScreen().eink, false);
  assert.equal(loadDevice({ search: '' }).device.getScreen().eink, false);
});

test('getScreen does not throw when location is missing', () => {
  const { device } = loadDevice({ noLocation: true });
  assert.equal(device.getScreen().eink, false);
});

test('helloFields returns device_id, name and screen', () => {
  const { device } = loadDevice({ ua: 'Mozilla/5.0 (iPad; CPU OS 16_0)' });
  const hello = device.helloFields();
  assert.deepEqual(Object.keys(hello).sort(), ['device_id', 'name', 'screen']);
  assert.equal(hello.device_id, device.getId());
  assert.equal(hello.name, 'iPad');
  assert.equal(hello.screen.orientation, 'landscape');
});

test('source stays ES5: no arrow functions, template strings, const/let, Object.assign or optional chaining', () => {
  const code = deviceSource
    .split('\n')
    .filter((line) => {
      const trimmed = line.trim();
      return !(trimmed.startsWith('//') || trimmed.startsWith('*') || trimmed.startsWith('/*'));
    })
    .join('\n');
  assert.doesNotMatch(code, /=>/);
  assert.doesNotMatch(code, /`/);
  assert.doesNotMatch(code, /\bconst\s/);
  assert.doesNotMatch(code, /\blet\s/);
  assert.doesNotMatch(code, /Object\.assign/);
  assert.doesNotMatch(code, /\?\./);
});
