// Runs the settings page, sends the picture and message to the watch, and passes on the
// current temperature from the Pebble app's built-in weather plugin.

var settingsPage = require('./generated/settings_page');

var PICTURE_CHUNK = 512;  // bytes per AppMessage, well under the watch's 1024 inbox
var SETTINGS_KEY = 'settings';
var SENT_PICTURE_KEY = 'sent-picture';

// The saved settings: { message, picture, swapSides, openSeconds, celsius } (see
// src/settings/settings.js). Missing ones are filled in by the page and the watch.
function settings() {
  try {
    var saved = JSON.parse(localStorage.getItem(SETTINGS_KEY));
    if (saved) {
      return saved;
    }
    // Saved by an older version, which used Clay.
    var clay = JSON.parse(localStorage.getItem('clay-settings'));
    if (clay) {
      return {
        message: clay.MESSAGE,
        picture: clay.PICTURE || '',
        swapSides: !!clay.SWAP_SIDES,
        openSeconds: clay.OPEN_SECONDS,
        celsius: !!clay.USE_CELSIUS
      };
    }
  } catch (e) {
    console.log('Bad saved settings: ' + e);
  }
  return {};
}

// The latest temperature from the weather plugin: { value, celsius }, or null until one
// arrives. The plugin reports in the phone's unit, which can differ from the watch's.
var lastTemperature = null;

function sendTemperature() {
  if (!lastTemperature) {
    return;
  }
  var t = lastTemperature.value;
  var wantCelsius = !!settings().celsius;
  if (lastTemperature.celsius && !wantCelsius) {
    t = t * 9 / 5 + 32;
  } else if (!lastTemperature.celsius && wantCelsius) {
    t = (t - 32) * 5 / 9;
  }
  t = Math.round(t);
  console.log('Temperature: ' + t);
  Pebble.sendAppMessage({ TEMPERATURE: t });
}

// Subscribes to the Pebble app's built-in weather source, which pushes the current
// conditions for the user's location whenever they change. It needs plugins enabled in
// the Pebble app (Settings -> Plugins) and the Location permission from package.json.
function subscribeToWeather() {
  if (typeof Pebble.subscribeToSource !== 'function') {
    console.log('This Pebble app has no weather plugin support');
    return;
  }
  Pebble.subscribeToSource({
    category: 'weather',
    item: 'location',
    properties: ['temperature'],
    onData: function (e) {
      var here = e && e.instances && e.instances[0];
      var temp = here && here.properties && here.properties.temperature;
      var n = temp && temp.numericValue;
      if (!n || typeof n.value !== 'number') {
        return;  // the plugin can't serve a temperature right now
      }
      lastTemperature = { value: n.value, celsius: n.unit !== '\u00b0F' };
      sendTemperature();
    },
    onError: function (err) {
      // Not fatal: the subscription carries on and a later update may succeed.
      console.log('Weather error: ' + err.code + ' ' + err.message);
    }
  });
}

// PebbleKit JS has no atob().
function base64ToBytes(s) {
  var alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';
  var out = [];
  var bits = 0;
  var value = 0;
  for (var i = 0; i < s.length; i++) {
    var v = alphabet.indexOf(s.charAt(i));
    if (v < 0) {
      continue;  // padding or whitespace
    }
    value = (value << 6) | v;
    bits += 6;
    if (bits >= 8) {
      bits -= 8;
      out.push((value >> bits) & 0xFF);
    }
  }
  return out;
}

// Sends the picture (base64 from the settings page, '' for the default) in chunks, each
// one after the previous is acknowledged.
function sendPicture(picture, done) {
  if (!picture) {
    Pebble.sendAppMessage({ PICTURE_OFFSET: -1 }, done, function () {
      console.log('Failed to reset picture');
    });
    return;
  }
  var bytes = base64ToBytes(picture);
  function sendFrom(offset) {
    if (offset >= bytes.length) {
      if (done) {
        done();
      }
      return;
    }
    var chunk = bytes.slice(offset, offset + PICTURE_CHUNK);
    Pebble.sendAppMessage({ PICTURE_OFFSET: offset, PICTURE_DATA: chunk }, function () {
      sendFrom(offset + chunk.length);
    }, function () {
      console.log('Failed to send picture chunk at ' + offset);
    });
  }
  sendFrom(0);
}

Pebble.addEventListener('ready', subscribeToWeather);

Pebble.addEventListener('appmessage', function (e) {
  if (e.payload.REQUEST_WEATHER) {
    sendTemperature();
  }
  if (e.payload.REQUEST_PICTURE) {
    sendPicture(settings().picture || '');
  }
});

Pebble.addEventListener('showConfiguration', function () {
  // Escape '<' so nothing in the settings can end the page's <script> early.
  var json = JSON.stringify(settings()).replace(/</g, '\\u003c');
  var html = settingsPage.split('__SETTINGS__').join(json);
  Pebble.openURL('data:text/html;charset=utf-8,' + encodeURIComponent(html));
});

Pebble.addEventListener('webviewclosed', function (e) {
  if (!e || !e.response) {
    return;  // closed without saving
  }
  var s;
  try {
    s = JSON.parse(decodeURIComponent(e.response));
  } catch (err) {
    console.log('Bad settings from the page: ' + err);
    return;
  }
  localStorage.setItem(SETTINGS_KEY, JSON.stringify(s));

  var dict = {
    MESSAGE: s.message,
    SWAP_SIDES: s.swapSides ? 1 : 0,
    OPEN_SECONDS: s.openSeconds,
    USE_CELSIUS: s.celsius ? 1 : 0
  };
  // The picture goes separately, in chunks, and only when it changed.
  var picture = s.picture || '';
  Pebble.sendAppMessage(dict, function () {
    // The unit may have changed, so resend once the settings are through.
    sendTemperature();
    if (localStorage.getItem(SENT_PICTURE_KEY) !== picture) {
      sendPicture(picture, function () {
        localStorage.setItem(SENT_PICTURE_KEY, picture);
      });
    }
  }, function () {
    console.log('Failed to send settings');
  });
});
