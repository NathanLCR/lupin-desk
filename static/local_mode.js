/**
 * Local Mode helpers (/static/local_mode.js -> window.LupinLocalMode)
 * Pure functions: no DOM access. Works as a plain <script> and from Node tests.
 * Plain ES5 on purpose, so it runs on old WebViews (Android 7 / Chrome ~51).
 */
(function () {
  'use strict';

  var SLOW_FALLBACK_TEXT = 'The local model is taking a while...';

  function consentView(dc) {
    var data = dc || {};

    if (data.local === true) {
      return {
        local: true,
        editable: false,
        noteText: 'Runs on this Mac with Ollama, so no permission is needed. Nothing leaves this Mac.',
        rowText: {
          calendar: 'Your calendar stays on this Mac',
          email: 'Your emails stay on this Mac',
        },
        on: { calendar: true, email: true },
      };
    }

    var editable = Boolean(data.can_edit);
    var receiver = data.receiver || 'the provider';

    return {
      local: false,
      editable: editable,
      noteText: editable ? '' : 'This can only be changed on the Mac.',
      rowText: {
        calendar: 'Let ' + receiver + ' see your calendar',
        email: 'Let ' + receiver + ' see your emails',
      },
      on: {
        calendar: Boolean(data.calendar),
        email: Boolean(data.email),
      },
    };
  }

  function isSlowNotice(msg) {
    return Boolean(msg) &&
      typeof msg === 'object' &&
      msg.type === 'notice' &&
      msg.kind === 'slow_model';
  }

  function slowNoticeCaption(msg) {
    if (!isSlowNotice(msg)) return null;
    var text = typeof msg.text === 'string' ? msg.text.trim() : '';
    return text || SLOW_FALLBACK_TEXT;
  }

  var api = {
    consentView: consentView,
    slowNoticeCaption: slowNoticeCaption,
    isSlowNotice: isSlowNotice,
  };

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = api;
  }
  if (typeof window !== 'undefined') {
    window.LupinLocalMode = api;
  }
})();
