/**
 * Image editor Panel widget: pick or drop a photo, crop with touch handles, resize, compress,
 * remove the background or convert the format, then download the result.
 * The Brain does the work (sips, macOS Vision); the original is deleted after the edit and the
 * result is also saved on the Mac. Registers through PanelKit. ES5 for old WebViews.
 * File names and server text are only ever set with textContent, never innerHTML.
 */
(function (root) {
  'use strict';

  var PanelKit = typeof module !== 'undefined' && module.exports
    ? require('./widget-kit.js')
    : root.PanelKit;

  var MAX_BYTES = 25 * 1024 * 1024;
  var MIN_CROP = 0.05;
  var FULL = { x: 0, y: 0, w: 1, h: 1 };
  var FORMATS = ['', 'png', 'jpg', 'heic'];

  var MESSAGES = {
    not_image: 'That file is not an image.',
    too_large: 'That image is bigger than 25 MB.',
    unavailable: 'This edit is not available on the Mac.',
    no_subject: 'No subject found to cut out.',
    edit_failed: 'The edit failed. Try again.',
    unknown_image: 'That photo is gone. Upload it again.',
    bad_request: 'Those settings are not valid.',
    network: 'Could not reach the Mac.'
  };

  function clamp(value, low, high) {
    return Math.max(low, Math.min(high, value));
  }

  function errorText(code) {
    return Object.prototype.hasOwnProperty.call(MESSAGES, code) ? MESSAGES[code] : MESSAGES.edit_failed;
  }

  // Moves or resizes a crop box (fractions of the image) by a drag of (dx, dy) fractions.
  // mode: 'move' or a corner 'nw' | 'ne' | 'sw' | 'se'. The box always stays inside the image.
  function dragBox(box, mode, dx, dy) {
    var left = box.x;
    var top = box.y;
    var right = box.x + box.w;
    var bottom = box.y + box.h;
    if (mode === 'move') {
      var nx = clamp(box.x + dx, 0, 1 - box.w);
      var ny = clamp(box.y + dy, 0, 1 - box.h);
      return { x: nx, y: ny, w: box.w, h: box.h };
    }
    if (mode.charAt(1) === 'w') left = clamp(left + dx, 0, right - MIN_CROP);
    else right = clamp(right + dx, left + MIN_CROP, 1);
    if (mode.charAt(0) === 'n') top = clamp(top + dy, 0, bottom - MIN_CROP);
    else bottom = clamp(bottom + dy, top + MIN_CROP, 1);
    return { x: left, y: top, w: right - left, h: bottom - top };
  }

  function isFull(box) {
    return box.x <= 0.001 && box.y <= 0.001 && box.w >= 0.999 && box.h >= 0.999;
  }

  function positiveInt(text) {
    var n = parseInt(text, 10);
    return isFinite(n) && n > 0 && n <= 16384 ? n : null;
  }

  // Turns the editor state into the ordered edit list the Brain expects. [] means nothing to do.
  function buildOps(state) {
    var ops = [];
    if (state.crop && !isFull(state.crop)) {
      ops.push({ op: 'crop', x: state.crop.x, y: state.crop.y, w: state.crop.w, h: state.crop.h });
    }
    var width = positiveInt(state.width);
    var height = positiveInt(state.height);
    if (width !== null || height !== null) {
      var resize = { op: 'resize' };
      if (width !== null) resize.width = width;
      if (height !== null) resize.height = height;
      ops.push(resize);
    }
    if (state.removeBackground) ops.push({ op: 'remove_background' });
    if (state.compress) {
      var quality = parseInt(state.quality, 10);
      ops.push({ op: 'compress', quality: isFinite(quality) ? clamp(quality, 1, 100) : 70 });
    }
    if (state.format && FORMATS.indexOf(state.format) > 0) {
      ops.push({ op: 'convert', format: state.format });
    }
    return ops;
  }

  function make(doc, tag, className, text) {
    return PanelKit.el(doc, tag, className, text);
  }

  function pointOf(event) {
    var source = event && event.touches && event.touches.length ? event.touches[0] : event;
    return { x: source ? source.clientX : 0, y: source ? source.clientY : 0 };
  }

  function request(method, url, body, onDone) {
    var Xhr = typeof XMLHttpRequest !== 'undefined' ? XMLHttpRequest : null;
    if (!Xhr) { onDone('network', null); return; }
    var finished = false;
    function finish(code, data) {
      if (finished) return;
      finished = true;
      onDone(code, data);
    }
    try {
      var xhr = new Xhr();
      xhr.open(method, url, true);
      xhr.timeout = 120000;
      if (typeof body === 'string') xhr.setRequestHeader('Content-Type', 'application/json');
      xhr.onload = function () {
        var data = null;
        try { data = JSON.parse(xhr.responseText); } catch (e) { data = null; }
        if (xhr.status >= 200 && xhr.status < 300) { finish(null, data); return; }
        var code = data && typeof data.detail === 'string' ? data.detail : 'edit_failed';
        if (xhr.status === 413) code = 'too_large';
        if (xhr.status === 415) code = 'not_image';
        finish(code, null);
      };
      xhr.onerror = function () { finish('network', null); };
      xhr.ontimeout = function () { finish('network', null); };
      xhr.send(body === undefined ? null : body);
    } catch (e) {
      finish('network', null);
    }
  }

  function mount(el, ctx) {
    var doc = el.ownerDocument;
    var live = true;
    var current = null; // { id }
    var state = { crop: { x: 0, y: 0, w: 1, h: 1 }, width: '', height: '', removeBackground: false,
      compress: false, quality: '70', format: '' };
    var drag = null;
    var busy = false;

    var wrap = make(doc, 'div', 'pn-imged');
    var status = make(doc, 'div', 'pn-imged-status', 'Choose a photo to edit.');
    var pick = make(doc, 'input', 'pn-imged-file');
    pick.type = 'file';
    pick.setAttribute('accept', 'image/*');
    var stage = make(doc, 'div', 'pn-imged-stage');
    var img = make(doc, 'img', 'pn-imged-img');
    img.setAttribute('alt', 'Photo to edit');
    var box = make(doc, 'div', 'pn-imged-crop');
    var corners = { nw: null, ne: null, sw: null, se: null };
    stage.appendChild(img);
    stage.appendChild(box);
    ['nw', 'ne', 'sw', 'se'].forEach(function (name) {
      corners[name] = make(doc, 'div', 'pn-imged-handle pn-imged-' + name);
      box.appendChild(corners[name]);
    });

    var controls = make(doc, 'div', 'pn-imged-controls');

    function field(label, input) {
      var row = make(doc, 'label', 'pn-imged-field');
      row.appendChild(make(doc, 'span', 'pn-imged-label', label));
      row.appendChild(input);
      controls.appendChild(row);
      return input;
    }

    var widthIn = make(doc, 'input', 'pn-imged-input');
    widthIn.type = 'number';
    widthIn.setAttribute('placeholder', 'auto');
    var heightIn = make(doc, 'input', 'pn-imged-input');
    heightIn.type = 'number';
    heightIn.setAttribute('placeholder', 'auto');
    var qualityIn = make(doc, 'input', 'pn-imged-input');
    qualityIn.type = 'number';
    qualityIn.setAttribute('min', '1');
    qualityIn.setAttribute('max', '100');
    qualityIn.value = '70';
    var compressIn = make(doc, 'input', 'pn-imged-check');
    compressIn.type = 'checkbox';
    var bgIn = make(doc, 'input', 'pn-imged-check');
    bgIn.type = 'checkbox';
    var formatIn = make(doc, 'select', 'pn-imged-input');
    var labels = ['Keep format', 'PNG', 'JPG', 'HEIC'];
    for (var i = 0; i < FORMATS.length; i++) {
      var option = make(doc, 'option', '', labels[i]);
      option.value = FORMATS[i];
      formatIn.appendChild(option);
    }
    field('Width (px)', widthIn);
    field('Height (px)', heightIn);
    field('Compress', compressIn);
    field('Quality', qualityIn);
    field('Remove background', bgIn);
    field('Format', formatIn);

    var actions = make(doc, 'div', 'pn-imged-actions');
    var apply = make(doc, 'button', 'pn-imged-btn', 'Apply');
    apply.type = 'button';
    var discard = make(doc, 'button', 'pn-imged-btn', 'Discard');
    discard.type = 'button';
    actions.appendChild(apply);
    actions.appendChild(discard);
    var result = make(doc, 'div', 'pn-imged-result');

    wrap.appendChild(status);
    wrap.appendChild(pick);
    wrap.appendChild(stage);
    wrap.appendChild(controls);
    wrap.appendChild(actions);
    wrap.appendChild(result);
    el.appendChild(wrap);

    function setStatus(text) { status.textContent = text; }

    function setBusy(value) {
      busy = value;
      apply.setAttribute('aria-busy', value ? 'true' : 'false');
      apply.disabled = value;
    }

    function paintBox() {
      var c = state.crop;
      box.style.left = (c.x * 100) + '%';
      box.style.top = (c.y * 100) + '%';
      box.style.width = (c.w * 100) + '%';
      box.style.height = (c.h * 100) + '%';
    }

    function show(info) {
      current = { id: info.id };
      state.crop = { x: 0, y: 0, w: 1, h: 1 };
      result.textContent = '';
      img.setAttribute('src', '/api/images/' + info.id + '/preview');
      stage.style.display = 'block';
      paintBox();
      setStatus('Drag the corners to crop, then Apply.');
    }

    function clearPhoto() {
      current = null;
      stage.style.display = 'none';
      img.setAttribute('src', '');
    }

    function upload(file) {
      if (!file) return;
      if (file.size && file.size > MAX_BYTES) { setStatus(errorText('too_large')); return; }
      setStatus('Uploading...');
      request('POST', '/api/images', file, function (code, data) {
        if (!live) return;
        if (code || !data || typeof data.id !== 'string') { setStatus(errorText(code)); return; }
        show(data);
      });
    }

    pick.addEventListener('change', function () {
      var files = pick.files;
      if (files && files.length) upload(files[0]);
    });
    wrap.addEventListener('dragover', function (event) {
      if (event && event.preventDefault) event.preventDefault();
    });
    wrap.addEventListener('drop', function (event) {
      if (event && event.preventDefault) event.preventDefault();
      var files = event && event.dataTransfer ? event.dataTransfer.files : null;
      if (files && files.length) upload(files[0]);
    });

    function startDrag(mode, event) {
      if (!current) return;
      if (event && event.preventDefault) event.preventDefault();
      if (event && event.stopPropagation) event.stopPropagation();
      var p = pointOf(event);
      drag = { mode: mode, x: p.x, y: p.y, start: { x: state.crop.x, y: state.crop.y, w: state.crop.w, h: state.crop.h } };
    }

    function moveDrag(event) {
      if (!drag) return;
      if (event && event.preventDefault) event.preventDefault();
      var rect = stage.getBoundingClientRect();
      if (!rect.width || !rect.height) return;
      var p = pointOf(event);
      state.crop = dragBox(drag.start, drag.mode, (p.x - drag.x) / rect.width, (p.y - drag.y) / rect.height);
      paintBox();
    }

    function endDrag() { drag = null; }

    ['nw', 'ne', 'sw', 'se'].forEach(function (name) {
      corners[name].addEventListener('mousedown', function (e) { startDrag(name, e); });
      corners[name].addEventListener('touchstart', function (e) { startDrag(name, e); });
    });
    box.addEventListener('mousedown', function (e) { startDrag('move', e); });
    box.addEventListener('touchstart', function (e) { startDrag('move', e); });
    doc.addEventListener('mousemove', moveDrag);
    doc.addEventListener('touchmove', moveDrag);
    doc.addEventListener('mouseup', endDrag);
    doc.addEventListener('touchend', endDrag);

    function showResult(info) {
      result.textContent = '';
      var link = make(doc, 'a', 'pn-imged-download', 'Download ' + info.name);
      link.setAttribute('href', '/api/images/results/' + info.id);
      link.setAttribute('download', info.name);
      result.appendChild(make(doc, 'div', 'pn-imged-saved', 'Saved in Pictures/Lupin on the Mac.'));
      result.appendChild(link);
    }

    apply.addEventListener('click', function () {
      if (!current || busy) return;
      state.width = widthIn.value;
      state.height = heightIn.value;
      state.compress = !!compressIn.checked;
      state.quality = qualityIn.value;
      state.removeBackground = !!bgIn.checked;
      state.format = formatIn.value;
      var ops = buildOps(state);
      if (!ops.length) { setStatus('Nothing to apply yet.'); return; }
      setBusy(true);
      setStatus('Working...');
      var id = current.id;
      request('POST', '/api/images/' + id + '/edit', JSON.stringify({ ops: ops }), function (code, data) {
        if (!live) return;
        setBusy(false);
        if (code || !data) { setStatus(errorText(code)); return; }
        clearPhoto();
        setStatus('Done.');
        showResult(data);
      });
    });

    discard.addEventListener('click', function () {
      if (!current) return;
      var id = current.id;
      clearPhoto();
      result.textContent = '';
      setStatus('Choose a photo to edit.');
      request('DELETE', '/api/images/' + id, undefined, function () {});
    });

    clearPhoto();
    PanelKit.getJson('/api/images/last', function (error, data) {
      if (!live || error || current || !data || !data.pending) return;
      show(data.pending);
    });

    return {
      onTopic: function (topic, data) {
        if (!live || topic !== 'images' || !data) return;
        if (data.result && typeof data.result.id === 'string') {
          clearPhoto();
          setStatus('Done.');
          showResult(data.result);
        } else if (data.pending && typeof data.pending.id === 'string' &&
            (!current || current.id !== data.pending.id)) {
          show(data.pending);
        }
      },
      destroy: function () {
        live = false;
        drag = null;
      }
    };
  }

  var DEFS = [
    {
      id: 'image-editor',
      title: 'Image editor',
      sizes: {
        min: { w: 3, h: 4 },
        max: { w: 6, h: 10 },
        default: { w: 4, h: 6 }
      },
      topics: ['images'],
      actions: ['image.edit', 'image.discard'],
      render: function (el, ctx) { return mount(el, ctx); }
    }
  ];

  function registerAll(registry) {
    PanelKit.registerAll(registry, DEFS);
  }

  var api = {
    registerAll: registerAll,
    DEFS: DEFS,
    dragBox: dragBox,
    buildOps: buildOps,
    errorText: errorText
  };

  root.PanelWidgetsImageEditor = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;

  PanelKit.autoRegister(root, DEFS);
})(typeof window !== 'undefined' ? window : this);
