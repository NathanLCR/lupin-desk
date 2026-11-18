(function (root) {
  'use strict';

  // REST client for the Mac Layout editor. No DOM access.
  // Every method resolves with the parsed JSON body, or rejects with an Error
  // whose .status is the HTTP status (0 when the Brain could not be reached).
  // Request bodies are never copied into error messages: they can hold credentials.

  var NETWORK_MESSAGE = 'Could not reach the Brain.';

  function messageFor(status, data) {
    if (data && typeof data === 'object') {
      if (typeof data.detail === 'string' && data.detail) return data.detail;
      if (Array.isArray(data.detail) && data.detail.length > 0) {
        var first = data.detail[0];
        if (first && typeof first.msg === 'string' && first.msg) return first.msg;
      }
    }
    return 'HTTP ' + status;
  }

  function parseBody(response) {
    var read = null;
    if (typeof response.text === 'function') {
      read = Promise.resolve(response.text());
    } else if (typeof response.json === 'function') {
      return Promise.resolve(response.json()).catch(function () { return null; });
    } else {
      return Promise.resolve(null);
    }
    return read.then(
      function (text) {
        if (typeof text !== 'string' || text.trim() === '') return null;
        try {
          return JSON.parse(text);
        } catch (err) {
          return null;
        }
      },
      function () { return null; }
    );
  }

  function create(fetchFn) {
    function request(method, url, body) {
      var options = { method: method, headers: {} };
      if (body !== undefined) {
        options.headers['Content-Type'] = 'application/json';
        options.body = JSON.stringify(body);
      }

      var pending;
      try {
        pending = Promise.resolve(fetchFn(url, options));
      } catch (err) {
        pending = Promise.reject(err);
      }

      return pending.then(
        function (response) {
          return parseBody(response).then(function (data) {
            if (response.ok) return data;
            var error = new Error(messageFor(response.status, data));
            error.status = response.status;
            throw error;
          });
        },
        function () {
          var error = new Error(NETWORK_MESSAGE);
          error.status = 0;
          throw error;
        }
      );
    }

    function path(id) {
      return encodeURIComponent(String(id));
    }

    return {
      listLayouts: function () {
        return request('GET', '/api/layouts');
      },
      listTemplates: function () {
        return request('GET', '/api/layout-templates');
      },
      getLayout: function (id) {
        return request('GET', '/api/layouts/' + path(id));
      },
      createLayout: function (name, template) {
        return request('POST', '/api/layouts', { name: name, template: template });
      },
      saveLayout: function (id, layout) {
        return request('PUT', '/api/layouts/' + path(id), layout);
      },
      deleteLayout: function (id) {
        return request('DELETE', '/api/layouts/' + path(id));
      },
      listDevices: function () {
        return request('GET', '/api/devices');
      },
      updateDevice: function (id, fields) {
        return request('PUT', '/api/devices/' + path(id), fields);
      },
      setPriority: function (order) {
        return request('PUT', '/api/devices/priority', { order: order });
      },
      getCredentials: function () {
        return request('GET', '/api/credentials');
      },
      saveCredentials: function (values) {
        return request('PUT', '/api/credentials', { values: values });
      },
      getClientInfo: function () {
        return request('GET', '/api/client-info');
      }
    };
  }

  var api = { create: create };

  root.EditorApi = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : this);
