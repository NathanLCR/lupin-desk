(function (root) {
  'use strict';

  // Mac Layout editor shell: connects layouts, pages, grid editing,
  // widget inspector, live preview, devices and .env credentials.
  // Builds DOM exclusively with createElement and textContent.

  var PanelGridMod = (typeof module !== 'undefined' && module.exports) ? require('../panel/grid.js') : null;
  var ModelMod = (typeof module !== 'undefined' && module.exports) ? require('./editor-model.js') : null;
  var DevicesMod = (typeof module !== 'undefined' && module.exports) ? require('./editor-devices.js') : null;
  var PreviewMod = (typeof module !== 'undefined' && module.exports) ? require('./editor-preview.js') : null;

  var PREVIEW_PRESETS = [
    { id: '960x720', label: 'RG406H (960x720)', width: 960, height: 720, orientation: 'landscape' },
    { id: '1024x768', label: 'iPad landscape (1024x768)', width: 1024, height: 768, orientation: 'landscape' },
    { id: '768x1024', label: 'iPad portrait (768x1024)', width: 768, height: 1024, orientation: 'portrait' },
    { id: '640x360', label: 'Phone landscape (640x360)', width: 640, height: 360, orientation: 'landscape' },
    { id: '360x640', label: 'Phone portrait (360x640)', width: 360, height: 640, orientation: 'portrait' },
    { id: '600x800', label: 'Kindle portrait (600x800)', width: 600, height: 800, orientation: 'portrait' }
  ];

  function pick(win, name, fallback) {
    if (win && win[name]) return win[name];
    if (fallback) return fallback;
    return root[name] || null;
  }

  function clear(node) {
    while (node.firstChild) node.removeChild(node.firstChild);
  }

  function make(doc, tag, options, children) {
    var node = doc.createElement(tag);
    var opts = options || {};
    if (opts.className) node.className = opts.className;
    if (opts.text !== undefined) node.textContent = String(opts.text);
    if (opts.attrs) {
      Object.keys(opts.attrs).forEach(function (name) {
        node.setAttribute(name, opts.attrs[name]);
      });
    }
    if (opts.props) {
      Object.keys(opts.props).forEach(function (name) {
        node[name] = opts.props[name];
      });
    }
    if (opts.on) {
      Object.keys(opts.on).forEach(function (type) {
        node.addEventListener(type, opts.on[type]);
      });
    }
    (children || []).forEach(function (child) {
      if (child) node.appendChild(child);
    });
    return node;
  }

  function defaultWsUrl(win) {
    var loc = win && win.location ? win.location : null;
    if (!loc || !loc.host) return 'ws://127.0.0.1:8000/ws';
    var proto = loc.protocol === 'https:' ? 'wss:' : 'ws:';
    return proto + '//' + loc.host + '/ws';
  }

  function errorMessage(err) {
    return err && typeof err.message === 'string' && err.message ? err.message : 'Something went wrong.';
  }

  function clone(value) {
    return value === undefined ? undefined : JSON.parse(JSON.stringify(value));
  }

  function mount(containerEl, options) {
    var opts = options || {};
    var win = opts.win || root;
    var doc = opts.doc || (containerEl && containerEl.ownerDocument) || win.document;
    var Grid = opts.grid || pick(win, 'PanelGrid', PanelGridMod);
    var Model = opts.model || pick(win, 'EditorModel', ModelMod);
    var Devices = opts.devices || pick(win, 'EditorDevices', DevicesMod);
    var Preview = opts.preview || pick(win, 'EditorPreview', PreviewMod);
    var Api = opts.apiFactory || pick(win, 'EditorApi', null);
    var api = opts.api || (Api ? Api.create(win.fetch.bind(win)) : null);
    if (!api) throw new Error('EditorApp.mount needs an api.');

    var registry = opts.registry ||
      (win.PanelRegistry && (win.PanelRegistry.shared || win.PanelRegistry.create())) ||
      null;
    if (!opts.registry && registry && win.PanelWidgets && typeof win.PanelWidgets.registerBuiltins === 'function') {
      win.PanelWidgets.registerBuiltins(registry);
    }
    var wsUrl = opts.wsUrl || defaultWsUrl(win);

    var state = {
      destroyed: false,
      layouts: [],
      templates: [],
      saved: null,
      draft: null,
      pageId: null,
      orientation: 'landscape',
      selectedWidgetId: null,
      presetId: PREVIEW_PRESETS[0].id,
      livePreview: false,
      busy: false
    };

    var devicesHandle = null;
    var previewHandle = null;
    var dragState = null;

    var errorEl = null;
    var layoutSelectEl = null;
    var renameLayoutInput = null;
    var saveBtn = null;
    var dupBtn = null;
    var delBtn = null;
    var templateSelectEl = null;
    var newLayoutInput = null;
    var pagesTabsEl = null;
    var pageTitleInput = null;
    var removePageBtn = null;
    var movePageLeftBtn = null;
    var movePageRightBtn = null;
    var landscapeBtn = null;
    var portraitBtn = null;
    var copyVariantBtn = null;
    var gridDimsEl = null;
    var gridCanvasEl = null;
    var widgetTypeSelectEl = null;
    var inspectorEl = null;
    var previewPresetEl = null;
    var previewLiveBox = null;

    function setError(message) {
      if (errorEl) errorEl.textContent = message || '';
    }

    function currentPreset() {
      for (var i = 0; i < PREVIEW_PRESETS.length; i += 1) {
        if (PREVIEW_PRESETS[i].id === state.presetId) return PREVIEW_PRESETS[i];
      }
      return PREVIEW_PRESETS[0];
    }

    function currentPage() {
      return state.draft && state.pageId ? Model.getPage(state.draft, state.pageId) : null;
    }

    function currentWidgets() {
      var page = currentPage();
      if (!page) return [];
      return Array.isArray(page[state.orientation]) ? page[state.orientation] : [];
    }

    function selectedWidget() {
      if (!state.draft || !state.pageId || !state.selectedWidgetId) return null;
      return Model.getWidget(state.draft, state.pageId, state.orientation, state.selectedWidgetId);
    }

    function ensureValidSelection() {
      var pages = state.draft && Array.isArray(state.draft.pages) ? state.draft.pages : [];
      if (!pages.length) {
        state.pageId = null;
        state.selectedWidgetId = null;
        return;
      }
      var hasPage = pages.some(function (p) { return p && p.id === state.pageId; });
      if (!hasPage) state.pageId = pages[0].id;
      var widgets = currentWidgets();
      var hasWidget = widgets.some(function (w) { return w && w.id === state.selectedWidgetId; });
      if (!hasWidget) state.selectedWidgetId = widgets.length ? widgets[0].id : null;
    }

    function isDirty() {
      if (!state.draft || !state.saved) return false;
      return Model.isDirty(state.draft, state.saved);
    }

    function syncPreview() {
      if (!previewHandle || !state.draft || !state.pageId) return;
      var preset = currentPreset();
      var w = preset.width;
      var h = preset.height;
      if (state.orientation === 'portrait' && w > h) {
        w = preset.height;
        h = preset.width;
      } else if (state.orientation === 'landscape' && h > w) {
        w = preset.height;
        h = preset.width;
      }
      previewHandle.show(state.draft, state.pageId, state.orientation, {
        width: w,
        height: h
      });
    }

    function renderLayoutToolbar() {
      if (!layoutSelectEl) return;
      clear(layoutSelectEl);
      state.layouts.forEach(function (item) {
        if (!item || !item.id) return;
        layoutSelectEl.appendChild(make(doc, 'option', {
          text: item.name || item.id,
          props: { value: item.id }
        }));
      });
      if (state.draft && state.draft.id) layoutSelectEl.value = state.draft.id;
      if (renameLayoutInput && state.draft) renameLayoutInput.value = state.draft.name || '';
      if (saveBtn) saveBtn.disabled = state.busy || !isDirty();
      if (dupBtn) dupBtn.disabled = state.busy || !state.draft;
      if (delBtn) {
        var id = state.draft ? state.draft.id : '';
        delBtn.disabled = state.busy || !id || id === 'starter' || id === 'default';
      }
      clear(templateSelectEl);
      state.templates.forEach(function (tpl) {
        if (!tpl || !tpl.id) return;
        templateSelectEl.appendChild(make(doc, 'option', {
          text: tpl.name || tpl.id,
          props: { value: tpl.id }
        }));
      });
    }

    function renderPagesBar() {
      if (!pagesTabsEl) return;
      clear(pagesTabsEl);
      var pages = state.draft && Array.isArray(state.draft.pages) ? state.draft.pages : [];
      var activeIndex = -1;
      pages.forEach(function (page, idx) {
        if (!page) return;
        var active = page.id === state.pageId;
        if (active) activeIndex = idx;
        pagesTabsEl.appendChild(make(doc, 'button', {
          className: active ? 'ed-tab is-active' : 'ed-tab',
          text: page.title || page.id,
          attrs: { type: 'button', 'aria-pressed': String(active) },
          on: {
            click: function () {
              state.pageId = page.id;
              state.selectedWidgetId = null;
              ensureValidSelection();
              renderAll();
            }
          }
        }));
      });
      var activePage = currentPage();
      if (pageTitleInput) pageTitleInput.value = activePage ? (activePage.title || '') : '';
      if (removePageBtn) removePageBtn.disabled = pages.length <= 1;
      if (movePageLeftBtn) movePageLeftBtn.disabled = activeIndex <= 0;
      if (movePageRightBtn) movePageRightBtn.disabled = activeIndex < 0 || activeIndex >= pages.length - 1;
    }

    function renderOrientationBar() {
      var isLand = state.orientation === 'landscape';
      if (landscapeBtn) {
        landscapeBtn.className = isLand ? 'ed-btn is-active' : 'ed-btn';
        landscapeBtn.setAttribute('aria-pressed', String(isLand));
      }
      if (portraitBtn) {
        portraitBtn.className = !isLand ? 'ed-btn is-active' : 'ed-btn';
        portraitBtn.setAttribute('aria-pressed', String(!isLand));
      }
      if (copyVariantBtn) {
        copyVariantBtn.textContent = isLand ? 'Copy to portrait' : 'Copy to landscape';
      }
      if (gridDimsEl && state.draft) {
        var grid = Grid.gridFor(state.draft, state.orientation);
        gridDimsEl.textContent = grid.cols + ' × ' + grid.rows;
      }
    }

    function widgetTitle(typeId) {
      if (registry && typeof registry.get === 'function') {
        var def = registry.get(typeId);
        if (def && def.title) return def.title;
      }
      return typeId || 'widget';
    }

    function startDrag(ev, widget, grid) {
      if (!gridCanvasEl || !widget) return;
      if (ev.button !== undefined && ev.button !== 0) return;
      if (ev.preventDefault) ev.preventDefault();
      var rect = gridCanvasEl.getBoundingClientRect ? gridCanvasEl.getBoundingClientRect() : { left: 0, top: 0, width: 0, height: 0 };
      dragState = {
        widgetId: widget.id,
        grid: grid,
        rect: rect,
        lastX: widget.x,
        lastY: widget.y
      };
      state.selectedWidgetId = widget.id;
      renderAll();
    }

    function moveDrag(ev) {
      if (!dragState || state.destroyed) return;
      var box = dragState.rect;
      if (!box || box.width <= 0 || box.height <= 0) return;
      var px = (ev.clientX || 0) - box.left;
      var py = (ev.clientY || 0) - box.top;
      var cell = Grid.snap(px, py, box.width, box.height, dragState.grid);
      if (cell.x === dragState.lastX && cell.y === dragState.lastY) return;
      var res = Model.updateWidget(state.draft, state.pageId, state.orientation, dragState.widgetId, {
        x: cell.x,
        y: cell.y
      });
      if (res.ok) {
        dragState.lastX = cell.x;
        dragState.lastY = cell.y;
        state.draft = res.layout;
        renderAll();
      }
    }

    function endDrag() {
      dragState = null;
    }

    function renderGridCanvas() {
      if (!gridCanvasEl || !state.draft) return;
      clear(gridCanvasEl);
      var grid = Grid.gridFor(state.draft, state.orientation);
      gridCanvasEl.className = 'ed-grid ed-grid-' + state.orientation;
      gridCanvasEl.style.aspectRatio = grid.cols + ' / ' + grid.rows;

      var cellsLayer = make(doc, 'div', { className: 'ed-grid-cells' });
      for (var row = 0; row < grid.rows; row += 1) {
        for (var col = 0; col < grid.cols; col += 1) {
          var cell = make(doc, 'div', { className: 'ed-grid-cell' });
          cell.style.left = ((col / grid.cols) * 100) + '%';
          cell.style.top = ((row / grid.rows) * 100) + '%';
          cell.style.width = (100 / grid.cols) + '%';
          cell.style.height = (100 / grid.rows) + '%';
          cellsLayer.appendChild(cell);
        }
      }
      gridCanvasEl.appendChild(cellsLayer);

      var tilesLayer = make(doc, 'div', { className: 'ed-grid-tiles' });
      currentWidgets().forEach(function (widget) {
        var rect = Grid.cellRect(widget, grid);
        var selected = widget.id === state.selectedWidgetId;
        var tile = make(doc, 'button', {
          className: selected ? 'ed-tile is-selected' : 'ed-tile',
          attrs: {
            type: 'button',
            'aria-label': widgetTitle(widget.type) + ' (' + widget.id + ')',
            'aria-pressed': String(selected)
          },
          on: {
            click: function () {
              state.selectedWidgetId = widget.id;
              renderAll();
            },
            mousedown: function (ev) {
              startDrag(ev, widget, grid);
            }
          }
        }, [
          make(doc, 'span', { className: 'ed-tile-title', text: widgetTitle(widget.type) }),
          make(doc, 'span', { className: 'ed-tile-meta', text: widget.x + ',' + widget.y + ' · ' + widget.w + '×' + widget.h })
        ]);
        tile.style.left = rect.left + '%';
        tile.style.top = rect.top + '%';
        tile.style.width = rect.width + '%';
        tile.style.height = rect.height + '%';
        tilesLayer.appendChild(tile);
      });
      gridCanvasEl.appendChild(tilesLayer);
    }

    function renderInspector() {
      if (!inspectorEl) return;
      clear(inspectorEl);
      var widget = selectedWidget();
      if (!widget) {
        inspectorEl.appendChild(make(doc, 'p', { className: 'editor-hint', text: 'Select a widget to inspect or resize it.' }));
        return;
      }

      var grid = Grid.gridFor(state.draft, state.orientation);
      var numInputs = {};

      function commitField(key) {
        var raw = Number(numInputs[key].value);
        if (!isFinite(raw)) {
          numInputs[key].value = String(widget[key]);
          return;
        }
        var patch = {};
        patch[key] = Math.round(raw);
        var res = Model.updateWidget(state.draft, state.pageId, state.orientation, widget.id, patch);
        if (!res.ok) {
          setError('Widget overlaps another widget or does not fit the ' + grid.cols + '×' + grid.rows + ' grid.');
          numInputs[key].value = String(widget[key]);
          return;
        }
        setError('');
        state.draft = res.layout;
        renderAll();
      }

      var coords = make(doc, 'div', { className: 'ed-coords' });
      [
        ['x', 'X', 0, grid.cols - 1],
        ['y', 'Y', 0, grid.rows - 1],
        ['w', 'W', 1, grid.cols],
        ['h', 'H', 1, grid.rows]
      ].forEach(function (spec) {
        var key = spec[0];
        var input = make(doc, 'input', {
          className: 'ed-coord-input',
          attrs: {
            type: 'number',
            min: String(spec[2]),
            max: String(spec[3]),
            'aria-label': 'Widget ' + spec[1]
          },
          props: { value: String(widget[key]) },
          on: { change: function () { commitField(key); } }
        });
        numInputs[key] = input;
        coords.appendChild(make(doc, 'label', { className: 'ed-coord' }, [
          make(doc, 'span', { text: spec[1] }),
          input
        ]));
      });

      var configArea = make(doc, 'textarea', {
        className: 'ed-config-input',
        attrs: { rows: '4', 'aria-label': 'Widget config JSON' },
        props: { value: JSON.stringify(widget.config || {}, null, 2) }
      });

      var applyConfigBtn = make(doc, 'button', {
        className: 'ed-btn',
        text: 'Apply config',
        attrs: { type: 'button' },
        on: {
          click: function () {
            var parsed;
            try {
              parsed = JSON.parse(configArea.value || '{}');
            } catch (err) {
              setError('Widget config must be valid JSON.');
              return;
            }
            if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
              setError('Widget config must be a JSON object.');
              return;
            }
            setError('');
            state.draft = Model.setWidgetConfig(state.draft, state.pageId, state.orientation, widget.id, parsed);
            renderAll();
          }
        }
      });

      var removeWidgetBtn = make(doc, 'button', {
        className: 'ed-btn ed-danger',
        text: 'Remove widget',
        attrs: { type: 'button' },
        on: {
          click: function () {
            setError('');
            state.draft = Model.removeWidget(state.draft, state.pageId, state.orientation, widget.id);
            state.selectedWidgetId = null;
            ensureValidSelection();
            renderAll();
          }
        }
      });

      inspectorEl.appendChild(make(doc, 'div', { className: 'ed-inspector-head' }, [
        make(doc, 'strong', { text: widgetTitle(widget.type) }),
        make(doc, 'span', { className: 'ed-muted', text: widget.id + ' (' + widget.type + ')' })
      ]));
      inspectorEl.appendChild(coords);
      inspectorEl.appendChild(make(doc, 'label', { className: 'ed-config-wrap' }, [
        make(doc, 'span', { text: 'Settings (JSON)' }),
        configArea
      ]));
      inspectorEl.appendChild(make(doc, 'div', { className: 'ed-inspector-actions' }, [
        applyConfigBtn,
        removeWidgetBtn
      ]));
    }

    function renderAll() {
      if (state.destroyed) return;
      ensureValidSelection();
      renderLayoutToolbar();
      renderPagesBar();
      renderOrientationBar();
      renderGridCanvas();
      renderInspector();
      syncPreview();
    }

    function refreshLayoutList() {
      return api.listLayouts().then(function (response) {
        if (state.destroyed) return;
        state.layouts = response && Array.isArray(response.layouts) ? response.layouts : [];
        if (devicesHandle) devicesHandle.refresh(state.layouts);
        renderLayoutToolbar();
      });
    }

    function loadLayout(id) {
      if (!id) return Promise.resolve();
      state.busy = true;
      renderLayoutToolbar();
      return api.getLayout(id).then(function (docData) {
        state.busy = false;
        if (state.destroyed) return;
        state.saved = clone(docData);
        state.draft = clone(docData);
        state.pageId = null;
        state.selectedWidgetId = null;
        setError('');
        ensureValidSelection();
        renderAll();
      }).catch(function (err) {
        state.busy = false;
        if (state.destroyed) return;
        setError(errorMessage(err));
        renderLayoutToolbar();
      });
    }

    function saveCurrentLayout() {
      if (!state.draft || state.busy) return Promise.resolve();
      state.busy = true;
      renderLayoutToolbar();
      return api.saveLayout(state.draft.id, state.draft).then(function (saved) {
        state.busy = false;
        if (state.destroyed) return;
        state.saved = clone(saved);
        state.draft = clone(saved);
        setError('');
        return refreshLayoutList().then(function () {
          if (!state.destroyed) renderAll();
        });
      }).catch(function (err) {
        state.busy = false;
        if (state.destroyed) return;
        setError(errorMessage(err));
        renderLayoutToolbar();
      });
    }

    function createLayoutFromTemplate() {
      if (state.busy) return Promise.resolve();
      var name = String(newLayoutInput ? newLayoutInput.value : '').trim();
      var tplId = templateSelectEl ? templateSelectEl.value : 'starter';
      if (!name) {
        setError('Type a name for the new layout.');
        return Promise.resolve();
      }
      state.busy = true;
      renderLayoutToolbar();
      return api.createLayout(name, tplId || 'starter').then(function (created) {
        state.busy = false;
        if (state.destroyed) return;
        if (newLayoutInput) newLayoutInput.value = '';
        state.saved = clone(created);
        state.draft = clone(created);
        state.pageId = null;
        state.selectedWidgetId = null;
        setError('');
        return refreshLayoutList().then(function () {
          if (!state.destroyed) renderAll();
        });
      }).catch(function (err) {
        state.busy = false;
        if (state.destroyed) return;
        setError(errorMessage(err));
        renderLayoutToolbar();
      });
    }

    function duplicateCurrentLayout() {
      if (!state.draft || state.busy) return Promise.resolve();
      var copy = Model.duplicateDoc(state.draft);
      state.busy = true;
      renderLayoutToolbar();
      return api.createLayout(copy.name, 'starter').then(function (created) {
        var payload = Object.assign({}, copy, { id: created.id });
        return api.saveLayout(created.id, payload).then(function (saved) {
          state.busy = false;
          if (state.destroyed) return;
          state.saved = clone(saved);
          state.draft = clone(saved);
          state.pageId = null;
          state.selectedWidgetId = null;
          setError('');
          return refreshLayoutList().then(function () {
            if (!state.destroyed) renderAll();
          });
        }, function (err) {
          state.busy = false;
          if (state.destroyed) return;
          setError(errorMessage(err));
          return refreshLayoutList();
        });
      }).catch(function (err) {
        state.busy = false;
        if (state.destroyed) return;
        setError(errorMessage(err));
        renderLayoutToolbar();
      });
    }

    function deleteCurrentLayout() {
      if (!state.draft || state.busy) return Promise.resolve();
      var id = state.draft.id;
      if (!id || id === 'starter' || id === 'default') return Promise.resolve();
      state.busy = true;
      renderLayoutToolbar();
      return api.deleteLayout(id).then(function () {
        state.busy = false;
        if (state.destroyed) return;
        setError('');
        return api.listLayouts().then(function (response) {
          if (state.destroyed) return;
          state.layouts = response && Array.isArray(response.layouts) ? response.layouts : [];
          if (devicesHandle) devicesHandle.refresh(state.layouts);
          var nextId = state.layouts.length ? state.layouts[0].id : 'starter';
          return loadLayout(nextId);
        });
      }).catch(function (err) {
        state.busy = false;
        if (state.destroyed) return;
        setError(errorMessage(err));
        renderLayoutToolbar();
      });
    }

    function buildWorkspace() {
      clear(containerEl);

      errorEl = make(doc, 'p', { className: 'editor-error', attrs: { role: 'alert' } });
      layoutSelectEl = make(doc, 'select', {
        attrs: { 'aria-label': 'Layout' },
        on: {
          change: function () {
            var nextId = layoutSelectEl.value;
            if (!nextId || (state.draft && nextId === state.draft.id)) return;
            if (isDirty() && typeof win.confirm === 'function' && !win.confirm('Discard unsaved layout changes?')) {
              layoutSelectEl.value = state.draft.id;
              return;
            }
            loadLayout(nextId);
          }
        }
      });

      renameLayoutInput = make(doc, 'input', {
        className: 'ed-text-input',
        attrs: { type: 'text', 'aria-label': 'Layout name', maxlength: '60' }
      });
      var renameBtn = make(doc, 'button', {
        className: 'ed-btn',
        text: 'Rename',
        attrs: { type: 'button' },
        on: {
          click: function () {
            if (!state.draft) return;
            state.draft = Model.renameLayout(state.draft, renameLayoutInput.value);
            renderAll();
          }
        }
      });

      saveBtn = make(doc, 'button', {
        className: 'ed-btn ed-primary',
        text: 'Save',
        attrs: { type: 'button' },
        on: { click: saveCurrentLayout }
      });
      dupBtn = make(doc, 'button', {
        className: 'ed-btn',
        text: 'Duplicate',
        attrs: { type: 'button' },
        on: { click: duplicateCurrentLayout }
      });
      delBtn = make(doc, 'button', {
        className: 'ed-btn ed-danger',
        text: 'Delete',
        attrs: { type: 'button' },
        on: { click: deleteCurrentLayout }
      });

      templateSelectEl = make(doc, 'select', { attrs: { 'aria-label': 'Template' } });
      newLayoutInput = make(doc, 'input', {
        className: 'ed-text-input',
        attrs: { type: 'text', placeholder: 'New layout name', 'aria-label': 'New layout name', maxlength: '60' }
      });
      var createBtn = make(doc, 'button', {
        className: 'ed-btn',
        text: 'Create',
        attrs: { type: 'button' },
        on: { click: createLayoutFromTemplate }
      });

      var header = make(doc, 'header', { className: 'ed-header' }, [
        make(doc, 'div', { className: 'ed-header-title' }, [
          make(doc, 'h1', { text: 'Layout Editor' }),
          make(doc, 'a', { className: 'ed-back-link', text: 'Back to Lupin', attrs: { href: '/' } })
        ]),
        make(doc, 'div', { className: 'ed-toolbar' }, [
          make(doc, 'div', { className: 'ed-group' }, [
            layoutSelectEl,
            renameLayoutInput,
            renameBtn,
            saveBtn,
            dupBtn,
            delBtn
          ]),
          make(doc, 'div', { className: 'ed-group' }, [
            templateSelectEl,
            newLayoutInput,
            createBtn
          ])
        ]),
        errorEl
      ]);

      pagesTabsEl = make(doc, 'div', { className: 'ed-tabs' });
      pageTitleInput = make(doc, 'input', {
        className: 'ed-text-input',
        attrs: { type: 'text', 'aria-label': 'Page title', maxlength: '40' }
      });
      var renamePageBtn = make(doc, 'button', {
        className: 'ed-btn',
        text: 'Rename page',
        attrs: { type: 'button' },
        on: {
          click: function () {
            if (!state.draft || !state.pageId) return;
            state.draft = Model.renamePage(state.draft, state.pageId, pageTitleInput.value);
            renderAll();
          }
        }
      });
      var addPageBtn = make(doc, 'button', {
        className: 'ed-btn',
        text: 'Add page',
        attrs: { type: 'button' },
        on: {
          click: function () {
            if (!state.draft) return;
            var res = Model.addPage(state.draft);
            if (!res.pageId) {
              setError('Maximum number of pages reached.');
              return;
            }
            setError('');
            state.draft = res.layout;
            state.pageId = res.pageId;
            state.selectedWidgetId = null;
            renderAll();
          }
        }
      });
      movePageLeftBtn = make(doc, 'button', {
        className: 'ed-btn',
        text: 'Move left',
        attrs: { type: 'button' },
        on: {
          click: function () {
            if (!state.draft || !state.pageId) return;
            state.draft = Model.movePage(state.draft, state.pageId, -1);
            renderAll();
          }
        }
      });
      movePageRightBtn = make(doc, 'button', {
        className: 'ed-btn',
        text: 'Move right',
        attrs: { type: 'button' },
        on: {
          click: function () {
            if (!state.draft || !state.pageId) return;
            state.draft = Model.movePage(state.draft, state.pageId, 1);
            renderAll();
          }
        }
      });
      removePageBtn = make(doc, 'button', {
        className: 'ed-btn ed-danger',
        text: 'Remove page',
        attrs: { type: 'button' },
        on: {
          click: function () {
            if (!state.draft || !state.pageId) return;
            state.draft = Model.removePage(state.draft, state.pageId);
            state.selectedWidgetId = null;
            ensureValidSelection();
            renderAll();
          }
        }
      });

      landscapeBtn = make(doc, 'button', {
        className: 'ed-btn',
        text: 'Landscape',
        attrs: { type: 'button' },
        on: {
          click: function () {
            state.orientation = 'landscape';
            state.selectedWidgetId = null;
            ensureValidSelection();
            renderAll();
          }
        }
      });
      portraitBtn = make(doc, 'button', {
        className: 'ed-btn',
        text: 'Portrait',
        attrs: { type: 'button' },
        on: {
          click: function () {
            state.orientation = 'portrait';
            state.selectedWidgetId = null;
            ensureValidSelection();
            renderAll();
          }
        }
      });
      copyVariantBtn = make(doc, 'button', {
        className: 'ed-btn',
        text: 'Copy to portrait',
        attrs: { type: 'button' },
        on: {
          click: function () {
            if (!state.draft || !state.pageId) return;
            var other = state.orientation === 'landscape' ? 'portrait' : 'landscape';
            state.draft = Model.copyVariant(state.draft, state.pageId, state.orientation, other);
            renderAll();
          }
        }
      });
      gridDimsEl = make(doc, 'span', { className: 'ed-muted ed-grid-dims' });

      widgetTypeSelectEl = make(doc, 'select', { attrs: { 'aria-label': 'Widget type' } });
      var defs = registry && typeof registry.list === 'function' ? registry.list() : [];
      defs.forEach(function (def) {
        widgetTypeSelectEl.appendChild(make(doc, 'option', {
          text: def.title || def.id,
          props: { value: def.id }
        }));
      });
      var addWidgetBtn = make(doc, 'button', {
        className: 'ed-btn',
        text: 'Add widget',
        attrs: { type: 'button' },
        on: {
          click: function () {
            if (!state.draft || !state.pageId || !registry) return;
            var def = registry.get(widgetTypeSelectEl.value);
            if (!def) return;
            var res = Model.addWidget(state.draft, state.pageId, state.orientation, def);
            if (!res.widgetId) {
              setError('No room on this page for that widget.');
              return;
            }
            setError('');
            state.draft = res.layout;
            state.selectedWidgetId = res.widgetId;
            renderAll();
          }
        }
      });

      gridCanvasEl = make(doc, 'div', { className: 'ed-grid' });
      inspectorEl = make(doc, 'div', { className: 'ed-inspector' });

      var canvasSection = make(doc, 'section', { className: 'editor-section ed-canvas-panel', attrs: { 'aria-label': 'Grid editor' } }, [
        make(doc, 'div', { className: 'ed-pages-bar' }, [
          pagesTabsEl,
          make(doc, 'div', { className: 'ed-group' }, [
            pageTitleInput,
            renamePageBtn,
            addPageBtn,
            movePageLeftBtn,
            movePageRightBtn,
            removePageBtn
          ])
        ]),
        make(doc, 'div', { className: 'ed-variant-bar' }, [
          make(doc, 'div', { className: 'ed-group' }, [
            landscapeBtn,
            portraitBtn,
            copyVariantBtn,
            gridDimsEl
          ]),
          make(doc, 'div', { className: 'ed-group' }, [
            widgetTypeSelectEl,
            addWidgetBtn
          ])
        ]),
        gridCanvasEl,
        inspectorEl
      ]);

      previewPresetEl = make(doc, 'select', {
        attrs: { 'aria-label': 'Preview device size' },
        on: {
          change: function () {
            state.presetId = previewPresetEl.value;
            var preset = currentPreset();
            if (preset.orientation) {
              state.orientation = preset.orientation;
              state.selectedWidgetId = null;
            }
            renderAll();
          }
        }
      });
      PREVIEW_PRESETS.forEach(function (preset) {
        previewPresetEl.appendChild(make(doc, 'option', {
          text: preset.label,
          props: { value: preset.id }
        }));
      });
      previewPresetEl.value = state.presetId;

      previewLiveBox = make(doc, 'input', {
        attrs: { type: 'checkbox' },
        props: { checked: false },
        on: {
          change: function () {
            state.livePreview = !!previewLiveBox.checked;
            if (previewHandle) previewHandle.setLive(state.livePreview);
          }
        }
      });

      var previewHost = make(doc, 'div', { className: 'ed-preview-host' });
      var previewSection = make(doc, 'section', { className: 'editor-section ed-preview-panel', attrs: { 'aria-label': 'Live preview' } }, [
        make(doc, 'div', { className: 'ed-preview-bar' }, [
          make(doc, 'h2', { text: 'Preview' }),
          previewPresetEl,
          make(doc, 'label', { className: 'ed-live-toggle' }, [
            previewLiveBox,
            make(doc, 'span', { text: 'Live data' })
          ])
        ]),
        previewHost
      ]);

      var devicesHost = make(doc, 'div', { className: 'ed-devices-host' });

      var main = make(doc, 'main', { className: 'ed-workspace' }, [
        make(doc, 'div', { className: 'ed-top-row' }, [canvasSection, previewSection]),
        devicesHost
      ]);

      containerEl.appendChild(header);
      containerEl.appendChild(main);

      previewHandle = Preview.create(previewHost, { win: win, registry: registry, wsUrl: wsUrl });
      devicesHandle = Devices.mount(devicesHost, {
        api: api,
        onLayoutsChanged: function () {
          refreshLayoutList();
        }
      });
    }

    if (typeof win.addEventListener === 'function') {
      win.addEventListener('mousemove', moveDrag);
      win.addEventListener('mouseup', endDrag);
    }

    var ready = api.getClientInfo().then(function (info) {
      if (state.destroyed) return;
      if (!info || !info.is_mac) {
        clear(containerEl);
        containerEl.appendChild(make(doc, 'section', { className: 'editor-section ed-denied' }, [
          make(doc, 'h1', { text: 'Layout Editor' }),
          make(doc, 'p', { text: 'The Layout editor is only available on the Mac.' })
        ]));
        return;
      }
      buildWorkspace();
      return Promise.all([api.listLayouts(), api.listTemplates()]).then(function (results) {
        if (state.destroyed) return;
        var layoutsRes = results[0];
        var templatesRes = results[1];
        state.layouts = layoutsRes && Array.isArray(layoutsRes.layouts) ? layoutsRes.layouts : [];
        state.templates = templatesRes && Array.isArray(templatesRes.templates) ? templatesRes.templates : [];
        if (devicesHandle) devicesHandle.refresh(state.layouts);
        var initialId = state.layouts.length ? state.layouts[0].id : 'default';
        return loadLayout(initialId);
      });
    }).catch(function (err) {
      if (state.destroyed) return;
      clear(containerEl);
      containerEl.appendChild(make(doc, 'p', {
        className: 'editor-error',
        attrs: { role: 'alert' },
        text: errorMessage(err)
      }));
    });

    function destroy() {
      if (state.destroyed) return;
      state.destroyed = true;
      dragState = null;
      if (typeof win.removeEventListener === 'function') {
        win.removeEventListener('mousemove', moveDrag);
        win.removeEventListener('mouseup', endDrag);
      }
      if (devicesHandle) {
        devicesHandle.destroy();
        devicesHandle = null;
      }
      if (previewHandle) {
        previewHandle.destroy();
        previewHandle = null;
      }
      clear(containerEl);
    }

    return {
      ready: ready,
      destroy: destroy
    };
  }

  var api = { mount: mount };

  root.EditorApp = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : this);
