/**
 * Signal notice helpers (/static/signals.js -> window.LupinSignals)
 * Pure functions: no DOM access. Plain ES5 so it runs on old WebViews.
 */
(function () {
  'use strict';

  // What a Body does with a `notice` of kind `signal` (Lupin speaking unprompted).
  // Returns null for any other message. With server audio the voice arrives as `audio`
  // chunks, so only a Body without server audio speaks the text itself (browser TTS).
  function noticePlan(msg, ctx) {
    if (!msg || msg.type !== 'notice' || msg.kind !== 'signal') return null;
    var caption = typeof msg.text === 'string' ? msg.text.trim() : '';
    if (!caption) return null;
    var c = ctx || {};
    return {
      caption: caption,
      speakInBrowser: Boolean(c.ttsEnabled) && Boolean(c.isLupinBody) && c.ttsMode !== 'server',
    };
  }

  var api = { noticePlan: noticePlan };

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = api;
  }
  if (typeof window !== 'undefined') {
    window.LupinSignals = api;
  }
})();
