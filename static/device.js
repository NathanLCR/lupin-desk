// Stable device identity for the browser (Panels and Bodies).
// Plain ES5 on purpose: must run on Android 7 WebView, old Safari and the Kindle browser.
// Exposes window.DeskDevice. Never throws when storage, navigator, crypto or location are missing.
(function () {
  var root = typeof window !== 'undefined' && window ? window : {};
  var ID_KEY = 'desk.deviceId';
  var NAME_KEY = 'desk.deviceName';
  var ID_PATTERN = /^[A-Za-z0-9_-]{8,64}$/;
  var NAME_MAX = 60;
  var ID_BODY_MAX = 62; // 'd-' prefix + 62 chars = 64 max
  var memoryId = '';

  function getStorage() {
    try {
      return root.localStorage || null;
    } catch (e) {
      return null;
    }
  }

  function readStored(key) {
    try {
      var storage = getStorage();
      if (!storage) return null;
      return storage.getItem(key);
    } catch (e) {
      return null;
    }
  }

  function writeStored(key, value) {
    try {
      var storage = getStorage();
      if (!storage) return false;
      storage.setItem(key, value);
      return true;
    } catch (e) {
      return false;
    }
  }

  function removeStored(key) {
    try {
      var storage = getStorage();
      if (!storage) return false;
      storage.removeItem(key);
      return true;
    } catch (e) {
      return false;
    }
  }

  function userAgent() {
    try {
      return root.navigator && root.navigator.userAgent ? String(root.navigator.userAgent) : '';
    } catch (e) {
      return '';
    }
  }

  function locationSearch() {
    try {
      return root.location && root.location.search ? String(root.location.search) : '';
    } catch (e) {
      return '';
    }
  }

  function mathRandomHex(byteCount) {
    var out = '';
    for (var i = 0; i < byteCount; i++) {
      var b = Math.floor(Math.random() * 256);
      out += (b < 16 ? '0' : '') + b.toString(16);
    }
    return out;
  }

  function cryptoRandomHex(byteCount) {
    var cryptoObj = root.crypto;
    if (!cryptoObj || typeof cryptoObj.getRandomValues !== 'function') return '';
    try {
      var bytes = new Uint8Array(byteCount);
      cryptoObj.getRandomValues(bytes);
      var out = '';
      for (var i = 0; i < bytes.length; i++) {
        out += (bytes[i] < 16 ? '0' : '') + bytes[i].toString(16);
      }
      return out;
    } catch (e) {
      return '';
    }
  }

  function rawRandomId() {
    var cryptoObj = root.crypto;
    try {
      if (cryptoObj && typeof cryptoObj.randomUUID === 'function') {
        return String(cryptoObj.randomUUID());
      }
    } catch (e) {
      // fall through to the next source
    }
    return cryptoRandomHex(16) || mathRandomHex(16);
  }

  function generateId() {
    var body = rawRandomId().replace(/[^A-Za-z0-9_-]/g, '').slice(0, ID_BODY_MAX);
    if (body.length < 6) body += mathRandomHex(8);
    return 'd-' + body.slice(0, ID_BODY_MAX);
  }

  function getId() {
    var stored = readStored(ID_KEY);
    if (stored && ID_PATTERN.test(stored)) {
      memoryId = stored;
      return stored;
    }
    if (memoryId) {
      // Storage was unavailable or unwritable earlier; keep the ID stable for this page load.
      writeStored(ID_KEY, memoryId);
      return memoryId;
    }
    memoryId = generateId();
    writeStored(ID_KEY, memoryId);
    return memoryId;
  }

  function cleanName(value) {
    if (value === null || value === undefined) return '';
    return String(value).replace(/^\s+|\s+$/g, '').slice(0, NAME_MAX);
  }

  function guessName() {
    var ua = userAgent();
    if (ua.indexOf('Kindle') !== -1) return 'Kindle';
    if (ua.indexOf('iPad') !== -1) return 'iPad';
    if (ua.indexOf('iPhone') !== -1) return 'iPhone';
    if (ua.indexOf('Android') !== -1) return 'Android device';
    if (ua.indexOf('Macintosh') !== -1) return 'Mac browser';
    if (ua.indexOf('Windows') !== -1) return 'Windows browser';
    if (ua.indexOf('Linux') !== -1) return 'Linux browser';
    return 'Browser';
  }

  function getName() {
    var stored = cleanName(readStored(NAME_KEY));
    if (stored) return stored;
    return guessName();
  }

  function setName(name) {
    var cleaned = cleanName(name);
    if (cleaned) {
      writeStored(NAME_KEY, cleaned);
    } else {
      removeStored(NAME_KEY);
    }
    return cleaned;
  }

  function firstNumber() {
    for (var i = 0; i < arguments.length; i++) {
      var n = Number(arguments[i]);
      if (n && n > 0) return n;
    }
    return 0;
  }

  function getScreen() {
    var screenObj = root.screen || {};
    var width = firstNumber(root.innerWidth, screenObj.width);
    var height = firstNumber(root.innerHeight, screenObj.height);
    var dpr = firstNumber(root.devicePixelRatio) || 1;
    var orientation = width > height ? 'landscape' : 'portrait';
    var eink = userAgent().indexOf('Kindle') !== -1 || /(^|[?&])eink=1(&|$)/.test(locationSearch());
    return {
      width: width,
      height: height,
      dpr: dpr,
      orientation: orientation,
      eink: eink
    };
  }

  function helloFields() {
    return {
      device_id: getId(),
      name: getName(),
      screen: getScreen()
    };
  }

  root.DeskDevice = {
    getId: getId,
    getName: getName,
    setName: setName,
    getScreen: getScreen,
    helloFields: helloFields
  };
})();
