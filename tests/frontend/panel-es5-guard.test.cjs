// Guards the Panel sources against syntax and APIs that old engines (Android 7 WebView,
// old Safari, Kindle) cannot run. Panel code must stay plain ES5 with no build step.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const dir = path.join(__dirname, '../../static/panel');
const files = fs.readdirSync(dir).filter((f) => f.endsWith('.js'));

function stripStringsAndComments(src) {
  let out = '';
  let i = 0;
  while (i < src.length) {
    const c = src[i];
    const n = src[i + 1];
    if (c === '/' && n === '/') { while (i < src.length && src[i] !== '\n') i++; continue; }
    if (c === '/' && n === '*') { i += 2; while (i < src.length && !(src[i] === '*' && src[i + 1] === '/')) i++; i += 2; continue; }
    if (c === '"' || c === "'") {
      const q = c; i++;
      while (i < src.length && src[i] !== q) { if (src[i] === '\\') i++; i++; }
      i++; out += '""'; continue;
    }
    if (c === '`') { out += '`'; i++; continue; }
    out += c; i++;
  }
  return out;
}

const BANNED = [
  ['arrow function', /=>/],
  ['let', /\blet\b/],
  ['const', /\bconst\b/],
  ['class', /\bclass\s+[A-Za-z_$]/],
  ['template literal', /`/],
  ['spread/rest', /\.\.\./],
  ['optional chaining', /\?\./],
  ['nullish coalescing', /\?\?/],
  ['async/await', /\b(async|await)\b/],
  ['for-of', /\bfor\s*\([^)]*\bof\b/],
  ['Promise', /\bPromise\b/],
  ['Map/Set', /\bnew\s+(Map|Set|WeakMap|WeakSet)\b/],
  ['Object.assign', /\bObject\.assign\b/],
  ['Array.from', /\bArray\.from\b/],
  ['includes/startsWith/endsWith', /\.(includes|startsWith|endsWith)\(/],
  ['find/findIndex', /\.(find|findIndex)\(/],
  ['fetch', /\bfetch\s*\(/],
];

test('panel directory has the expected modules', () => {
  ['grid.js', 'registry.js', 'arrange-model.js', 'arrange-ui.js', 'widgets.js', 'pet.js', 'runtime.js']
    .forEach((f) => assert.ok(files.indexOf(f) !== -1, f));
});

files.forEach((file) => {
  test('panel/' + file + ' is plain ES5', () => {
    const src = fs.readFileSync(path.join(dir, file), 'utf8');
    new vm.Script(src, { filename: file }); // must at least parse
    const code = stripStringsAndComments(src);
    BANNED.forEach((pair) => assert.ok(!pair[1].test(code), file + ' uses ' + pair[0]));
  });
});
