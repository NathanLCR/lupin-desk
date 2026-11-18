const assert = require('node:assert/strict');
const test = require('node:test');

const DeskDictation = require('../../static/dictation.js');

const ALL_MIME_TYPES = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4'];

class FakeBlob {
  constructor(parts, opts) {
    this.parts = parts.slice();
    this.type = (opts && opts.type) || '';
    this.size = parts.reduce((total, part) => total + part.size, 0);
  }
}

class FakeFileReader {
  readAsDataURL(blob) {
    const bytes = Buffer.concat(blob.parts.map((part) => Buffer.from(part.bytes)));
    this.result = 'data:' + blob.type + ';base64,' + bytes.toString('base64');
    queueMicrotask(() => {
      if (this.onload) this.onload();
    });
  }
}

function makeRecorderClass(supported = ALL_MIME_TYPES) {
  const instances = [];
  class FakeRecorder {
    constructor(stream, opts) {
      this.stream = stream;
      this.options = opts || null;
      this.mimeType = (opts && opts.mimeType) || 'audio/webm';
      this.state = 'inactive';
      this.ondataavailable = null;
      this.onstop = null;
      instances.push(this);
    }

    start() {
      this.state = 'recording';
    }

    stop() {
      this.state = 'inactive';
      if (this.onstop) this.onstop();
    }

    static isTypeSupported(type) {
      return supported.includes(type);
    }
  }
  return { FakeRecorder, instances };
}

function makeTrack() {
  return {
    stopped: false,
    stop() {
      this.stopped = true;
    },
  };
}

function makeStream() {
  const tracks = [makeTrack(), makeTrack()];
  return { tracks, getTracks: () => tracks };
}

function chunk(bytes) {
  return { size: bytes.length, bytes };
}

function makeHarness(overrides = {}, recorderOptions) {
  const { FakeRecorder, instances } = makeRecorderClass(recorderOptions && recorderOptions.supported);
  const sent = [];
  const states = [];
  const toasts = [];
  const stream = makeStream();
  let sendOk = true;

  const config = Object.assign(
    {
      sendWs: (payload) => {
        sent.push(payload);
        return sendOk;
      },
      onState: (state) => states.push(state),
      showToast: (text, toastOpts) => toasts.push({ text, isError: Boolean(toastOpts && toastOpts.isError) }),
      getMediaStream: async () => stream,
      MediaRecorderImpl: FakeRecorder,
      BlobImpl: FakeBlob,
      FileReaderImpl: FakeFileReader,
      language: 'en',
    },
    overrides
  );

  return {
    controller: DeskDictation.create(config),
    sent,
    states,
    toasts,
    stream,
    instances,
    setSendOk(value) {
      sendOk = value;
    },
  };
}

// Starts a recording and feeds it enough audio to pass the minimum size check.
async function recordLongClip(h, bytes = Buffer.alloc(500, 7)) {
  await h.controller.toggle();
  h.instances[h.instances.length - 1].ondataavailable({ data: chunk(bytes) });
  return bytes;
}

test('toggle starts recording, then stops and sends base64 audio', async () => {
  const h = makeHarness();

  await h.controller.toggle();
  assert.equal(h.controller.isActive(), true);
  assert.deepEqual(h.sent, [{ type: 'dictation_start' }]);
  assert.deepEqual(h.states, ['listening']);
  assert.equal(h.instances[0].options.mimeType, 'audio/webm;codecs=opus');

  const bytes = Buffer.alloc(500, 7);
  h.instances[0].ondataavailable({ data: chunk(bytes.subarray(0, 200)) });
  h.instances[0].ondataavailable({ data: chunk(bytes.subarray(200)) });

  await h.controller.toggle();
  assert.equal(h.controller.isActive(), false);
  assert.equal(h.sent.length, 2);
  assert.deepEqual(h.sent[1], {
    type: 'dictation_stop',
    data: bytes.toString('base64'),
    mime_type: 'audio/webm;codecs=opus',
    language: 'en',
  });
  assert.deepEqual(h.states, ['listening', 'thinking']);
  assert.ok(h.stream.tracks.every((track) => track.stopped));
});

test('omits language when none is configured', async () => {
  const h = makeHarness({ language: undefined });
  await recordLongClip(h);
  await h.controller.toggle();
  assert.equal(h.sent[1].type, 'dictation_stop');
  assert.equal('language' in h.sent[1], false);
});

test('prefers webm, then falls back to mp4 when webm is unsupported', async () => {
  const h = makeHarness({}, { supported: ['audio/mp4'] });
  await h.controller.toggle();
  assert.equal(h.instances[0].options.mimeType, 'audio/mp4');
});

test('short recording sends dictation_cancel and nothing else', async () => {
  const h = makeHarness();
  await h.controller.toggle();
  h.instances[0].ondataavailable({ data: chunk(Buffer.alloc(100, 1)) });

  await h.controller.toggle();
  assert.deepEqual(h.sent, [{ type: 'dictation_start' }, { type: 'dictation_cancel' }]);
  assert.deepEqual(h.states, ['listening', 'idle']);
  assert.equal(h.controller.isActive(), false);
});

test('microphone error shows a toast and stays idle', async () => {
  const h = makeHarness({
    getMediaStream: async () => {
      throw new Error('Permission denied');
    },
  });

  await h.controller.toggle();
  assert.equal(h.controller.isActive(), false);
  assert.deepEqual(h.sent, []);
  assert.deepEqual(h.states, ['idle']);
  assert.deepEqual(h.toasts, [{ text: 'Permission denied', isError: true }]);
});

test('missing MediaRecorder shows an error toast and stays idle', async () => {
  const h = makeHarness({ MediaRecorderImpl: undefined });
  await h.controller.toggle();
  assert.equal(h.controller.isActive(), false);
  assert.deepEqual(h.sent, []);
  assert.deepEqual(h.states, ['idle']);
  assert.deepEqual(h.toasts, [{ text: 'Recording is not supported in this browser.', isError: true }]);
});

test('toggle is ignored while processing, and works again after the result', async () => {
  const h = makeHarness();
  await recordLongClip(h);
  await h.controller.toggle();
  assert.deepEqual(h.states, ['listening', 'thinking']);

  await h.controller.toggle();
  assert.equal(h.instances.length, 1);
  assert.equal(h.sent.length, 2);
  assert.equal(h.controller.isActive(), false);

  h.controller.handleMessage({ type: 'dictation', status: 'done', inserted: true, text: 'Hi' });
  await h.controller.toggle();
  assert.equal(h.instances.length, 2);
  assert.equal(h.controller.isActive(), true);
});

test('failed send on stop shows a connection toast and goes idle', async () => {
  const h = makeHarness();
  await recordLongClip(h);
  h.setSendOk(false);

  await h.controller.toggle();
  assert.equal(h.controller.isActive(), false);
  assert.deepEqual(h.states, ['listening', 'error']);
  assert.deepEqual(h.toasts.at(-1), { text: 'No connection right now.', isError: true });

  h.setSendOk(true);
  await h.controller.toggle();
  assert.equal(h.controller.isActive(), true);
});

test('failed send on start shows a connection toast and stays idle', async () => {
  const h = makeHarness();
  h.setSendOk(false);
  await h.controller.toggle();
  assert.equal(h.controller.isActive(), false);
  assert.deepEqual(h.states, ['error']);
  assert.deepEqual(h.toasts, [{ text: 'No connection right now.', isError: true }]);
});

test('cancel while listening stops everything and sends dictation_cancel', async () => {
  const h = makeHarness();
  await h.controller.toggle();
  h.controller.cancel();

  assert.equal(h.controller.isActive(), false);
  assert.deepEqual(h.sent, [{ type: 'dictation_start' }, { type: 'dictation_cancel' }]);
  assert.deepEqual(h.states, ['listening', 'idle']);
  assert.ok(h.stream.tracks.every((track) => track.stopped));
});

test('cancel while idle sends nothing', () => {
  const h = makeHarness();
  h.controller.cancel();
  assert.deepEqual(h.sent, []);
  assert.deepEqual(h.states, ['idle']);
});

test('cancel during a pending microphone request aborts the start', async () => {
  let resolveStream;
  const stream = makeStream();
  const h = makeHarness({
    getMediaStream: () =>
      new Promise((resolve) => {
        resolveStream = resolve;
      }),
  });

  const pending = h.controller.toggle();
  h.controller.cancel();
  resolveStream(stream);
  await pending;

  assert.equal(h.controller.isActive(), false);
  assert.equal(h.instances.length, 0);
  assert.deepEqual(h.sent, []);
  assert.ok(stream.tracks.every((track) => track.stopped));
});

test('handleMessage ignores other message types', () => {
  const h = makeHarness();
  assert.equal(h.controller.handleMessage({ type: 'chat', text: 'hello' }), false);
  assert.equal(h.controller.handleMessage(null), false);
  assert.deepEqual(h.states, []);
  assert.deepEqual(h.toasts, []);
});

test('handleMessage listening changes nothing', () => {
  const h = makeHarness();
  assert.equal(h.controller.handleMessage({ type: 'dictation', status: 'listening' }), true);
  assert.deepEqual(h.states, []);
  assert.deepEqual(h.toasts, []);
});

test('handleMessage done with inserted text shows a short snippet', () => {
  const h = makeHarness();
  assert.equal(
    h.controller.handleMessage({ type: 'dictation', status: 'done', inserted: true, text: 'Call Ana tomorrow' }),
    true
  );
  assert.deepEqual(h.states, ['idle']);
  assert.deepEqual(h.toasts, [{ text: 'Inserted: Call Ana tomorrow', isError: false }]);
});

test('handleMessage done truncates long text to 40 characters', () => {
  const h = makeHarness();
  const text = 'a'.repeat(60);
  h.controller.handleMessage({ type: 'dictation', status: 'done', inserted: true, text });
  assert.deepEqual(h.toasts, [{ text: 'Inserted: ' + 'a'.repeat(40) + '...', isError: false }]);
});

test('handleMessage done without insertion shows the error', () => {
  const h = makeHarness();
  h.controller.handleMessage({ type: 'dictation', status: 'done', inserted: false, error: 'No focused field.' });
  assert.deepEqual(h.states, ['idle']);
  assert.deepEqual(h.toasts, [{ text: 'No focused field.', isError: true }]);

  h.controller.handleMessage({ type: 'dictation', status: 'done', inserted: false });
  assert.deepEqual(h.toasts.at(-1), { text: 'Could not insert the text.', isError: true });
});

test('handleMessage empty goes idle with a friendly toast', () => {
  const h = makeHarness();
  assert.equal(h.controller.handleMessage({ type: 'dictation', status: 'empty' }), true);
  assert.deepEqual(h.states, ['idle']);
  assert.deepEqual(h.toasts, [{ text: 'Did not catch that.', isError: false }]);
});

test('handleMessage error sets the error state and shows the message', () => {
  const h = makeHarness();
  assert.equal(h.controller.handleMessage({ type: 'dictation', status: 'error', error: 'Model offline.' }), true);
  assert.deepEqual(h.states, ['error']);
  assert.deepEqual(h.toasts, [{ text: 'Model offline.', isError: true }]);

  h.controller.handleMessage({ type: 'dictation', status: 'error' });
  assert.deepEqual(h.toasts.at(-1), { text: 'Dictation failed.', isError: true });
});

test('a late dictation result does not interrupt a new recording', async () => {
  const h = makeHarness();
  await h.controller.toggle();
  h.controller.handleMessage({ type: 'dictation', status: 'done', inserted: true, text: 'Late' });
  assert.equal(h.controller.isActive(), true);
});

test('dictated text is never written to the console', () => {
  const h = makeHarness();
  const originals = {};
  const calls = [];
  ['log', 'info', 'warn', 'error', 'debug'].forEach((method) => {
    originals[method] = console[method];
    console[method] = (...args) => calls.push(args);
  });
  try {
    h.controller.handleMessage({ type: 'dictation', status: 'done', inserted: true, text: 'secret words' });
    h.controller.handleMessage({ type: 'dictation', status: 'error', error: 'boom' });
  } finally {
    Object.assign(console, originals);
  }
  assert.deepEqual(calls, []);
});
