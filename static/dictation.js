/**
 * Tap-to-talk dictation controller (/static/dictation.js -> window.DeskDictation)
 * Records a short clip from the microphone, sends it to the Brain over the
 * WebSocket, and reacts to the Brain's dictation result.
 * Never logs the audio or the transcribed text.
 */
(function (global) {
  'use strict';

  const MIN_AUDIO_BYTES = 400;
  const PREFERRED_MIME_TYPES = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4'];
  const SNIPPET_LENGTH = 40;

  function messageOf(err, fallback) {
    return err && err.message ? String(err.message) : fallback;
  }

  function snippet(text) {
    const value = String(text || '');
    return value.length > SNIPPET_LENGTH ? value.slice(0, SNIPPET_LENGTH) + '...' : value;
  }

  function stopTracks(mediaStream) {
    if (!mediaStream) return;
    const tracks =
      typeof mediaStream.getTracks === 'function' ? mediaStream.getTracks() : mediaStream.tracks || [];
    tracks.forEach((track) => {
      try {
        track.stop();
      } catch (_err) {
        // Track already stopped.
      }
    });
  }

  function pickMimeType(RecorderImpl) {
    if (typeof RecorderImpl.isTypeSupported !== 'function') return '';
    const found = PREFERRED_MIME_TYPES.find((type) => {
      try {
        return RecorderImpl.isTypeSupported(type);
      } catch (_err) {
        return false;
      }
    });
    return found || '';
  }

  function defaultGetMediaStream() {
    const nav = global.navigator;
    if (!nav || !nav.mediaDevices || typeof nav.mediaDevices.getUserMedia !== 'function') {
      return Promise.reject(new Error('Microphone is not available.'));
    }
    return nav.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
  }

  function stopRecorderQuietly(rec) {
    if (!rec) return;
    try {
      if (rec.state !== 'inactive') rec.stop();
    } catch (_err) {
      // Recorder already stopped or never started.
    }
  }

  // Resolves once the recorder fires its stop event (all chunks delivered).
  function stopRecorder(rec) {
    return new Promise((resolve) => {
      if (!rec) {
        resolve();
        return;
      }
      rec.onstop = () => resolve();
      if (rec.state === 'inactive') {
        resolve();
        return;
      }
      try {
        rec.stop();
      } catch (_err) {
        resolve();
      }
    });
  }

  function blobToBase64(blob, FileReaderImpl) {
    return new Promise((resolve, reject) => {
      const reader = new FileReaderImpl();
      reader.onload = () => {
        const text = String(reader.result || '');
        const comma = text.indexOf(',');
        resolve(comma >= 0 ? text.slice(comma + 1) : text);
      };
      reader.onerror = () => reject(new Error('Could not read the recording.'));
      reader.readAsDataURL(blob);
    });
  }

  /**
   * Create a dictation controller.
   * Statuses: idle -> starting -> listening -> stopping -> processing -> idle.
   */
  function create(options) {
    const opts = options || {};
    const sendWs = typeof opts.sendWs === 'function' ? opts.sendWs : () => false;
    const onState = typeof opts.onState === 'function' ? opts.onState : () => {};
    const showToast = typeof opts.showToast === 'function' ? opts.showToast : () => {};
    const getMediaStream =
      typeof opts.getMediaStream === 'function' ? opts.getMediaStream : defaultGetMediaStream;
    const RecorderImpl = opts.MediaRecorderImpl || global.MediaRecorder;
    const BlobImpl = opts.BlobImpl || global.Blob;
    const FileReaderImpl = opts.FileReaderImpl || global.FileReader;
    const language = opts.language;

    let status = 'idle';
    // Bumped by start() and cancel() so in-flight async work knows it was abandoned.
    let session = 0;
    let recorder = null;
    let mediaStream = null;
    let chunks = [];
    let recordingMime = '';

    function toast(text, isError) {
      showToast(text, { isError: Boolean(isError) });
    }

    function releaseRecording() {
      stopRecorderQuietly(recorder);
      stopTracks(mediaStream);
      recorder = null;
      mediaStream = null;
      chunks = [];
    }

    // Return to idle only if we are still waiting for the Brain's result.
    function settleIfProcessing() {
      if (status === 'processing') status = 'idle';
    }

    async function start() {
      if (status !== 'idle') return;
      const mySession = ++session;
      status = 'starting';
      let stream = null;
      try {
        if (!RecorderImpl) throw new Error('Recording is not supported in this browser.');
        stream = await getMediaStream();
        if (mySession !== session) {
          stopTracks(stream);
          return;
        }
        if (!stream) throw new Error('Microphone is not available.');

        const mime = pickMimeType(RecorderImpl);
        const rec = mime ? new RecorderImpl(stream, { mimeType: mime }) : new RecorderImpl(stream);
        recorder = rec;
        mediaStream = stream;
        recordingMime = mime || rec.mimeType || 'audio/webm';
        chunks = [];
        rec.ondataavailable = (event) => {
          if (event && event.data && event.data.size > 0) chunks.push(event.data);
        };
        rec.start();

        if (!sendWs({ type: 'dictation_start' })) {
          releaseRecording();
          status = 'idle';
          toast('No connection right now.', true);
          onState('error');
          return;
        }
        status = 'listening';
        onState('listening');
      } catch (err) {
        if (mySession !== session) return;
        releaseRecording();
        stopTracks(stream);
        status = 'idle';
        toast(messageOf(err, 'Microphone is not available.'), true);
        onState('idle');
      }
    }

    async function stop() {
      if (status !== 'listening') return;
      const mySession = session;
      const rec = recorder;
      const stream = mediaStream;
      const mime = recordingMime;
      status = 'stopping';

      await stopRecorder(rec);
      if (mySession !== session) {
        stopTracks(stream);
        return;
      }
      stopTracks(stream);
      recorder = null;
      mediaStream = null;
      const parts = chunks;
      chunks = [];

      const blob = new BlobImpl(parts, { type: mime });
      if (blob.size < MIN_AUDIO_BYTES) {
        status = 'idle';
        sendWs({ type: 'dictation_cancel' });
        onState('idle');
        return;
      }

      let data;
      try {
        data = await blobToBase64(blob, FileReaderImpl);
      } catch (err) {
        if (mySession !== session) return;
        status = 'idle';
        toast(messageOf(err, 'Could not read the recording.'), true);
        onState('error');
        return;
      }
      if (mySession !== session) return;

      const payload = { type: 'dictation_stop', data, mime_type: mime };
      if (language) payload.language = language;
      if (!sendWs(payload)) {
        status = 'idle';
        toast('No connection right now.', true);
        onState('error');
        return;
      }
      status = 'processing';
      onState('thinking');
    }

    async function toggle() {
      if (status === 'listening') {
        await stop();
      } else if (status === 'idle') {
        await start();
      }
      // Other statuses (starting, stopping, processing) ignore the tap.
    }

    function cancel() {
      const wasActive = status === 'listening';
      session += 1;
      if (wasActive) releaseRecording();
      status = 'idle';
      if (wasActive) sendWs({ type: 'dictation_cancel' });
      onState('idle');
    }

    function handleMessage(msg) {
      if (!msg || msg.type !== 'dictation') return false;
      switch (msg.status) {
        case 'listening':
          break;
        case 'done':
          settleIfProcessing();
          onState('idle');
          if (msg.inserted) toast('Inserted: ' + snippet(msg.text), false);
          else toast(msg.error || 'Could not insert the text.', true);
          break;
        case 'empty':
          settleIfProcessing();
          onState('idle');
          toast('Did not catch that.', false);
          break;
        case 'error':
          settleIfProcessing();
          onState('error');
          toast(msg.error || 'Dictation failed.', true);
          break;
        default:
          break;
      }
      return true;
    }

    return {
      isActive: () => status === 'listening',
      toggle,
      start,
      stop,
      cancel,
      handleMessage,
    };
  }

  const DeskDictation = { create };

  global.DeskDictation = DeskDictation;
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = DeskDictation;
  }
})(typeof window !== 'undefined' ? window : globalThis);
