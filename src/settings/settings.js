// Settings page logic. On Save it hands the settings back to src/pkjs/index.js as JSON:
// { message, picture, swapSides, openSeconds, celsius }, where picture is the watch format
// (see picture.js) base64 encoded, or '' for the default picture.
(function () {
  var DEFAULTS = { message: 'pebble my beloved', picture: '', swapSides: false, openSeconds: 3, celsius: false };
  var SIZE = picture.SIZE;

  function $(id) {
    return document.getElementById(id);
  }

  function readJson(id) {
    try {
      return JSON.parse($(id).textContent);
    } catch (e) {
      return null;  // opened straight from src/settings, placeholders not filled in
    }
  }

  var state = {};
  var saved = readJson('settings') || {};
  Object.keys(DEFAULTS).forEach(function (k) {
    state[k] = saved[k] !== undefined ? saved[k] : DEFAULTS[k];
  });
  var defaultPicture = $('default-picture').textContent.trim();
  if (defaultPicture.indexOf('__') === 0) {
    defaultPicture = '';
  }

  function b64ToBytes(s) {
    var bin = atob(s);
    var out = new Uint8Array(bin.length);
    for (var i = 0; i < bin.length; i++) {
      out[i] = bin.charCodeAt(i);
    }
    return out;
  }

  function bytesToB64(bytes) {
    var bin = '';
    for (var i = 0; i < bytes.length; i++) {
      bin += String.fromCharCode(bytes[i]);
    }
    return btoa(bin);
  }

  function setStatus(text) {
    $('status').textContent = text;
  }

  // Picture -------------------------------------------------------------------------------

  function drawPreview() {
    var ctx = $('preview').getContext('2d');
    var b64 = state.picture || defaultPicture;
    if (!b64) {
      ctx.clearRect(0, 0, SIZE, SIZE);
      return;
    }
    ctx.putImageData(new ImageData(picture.decode(b64ToBytes(b64)), SIZE, SIZE), 0, 0);
  }

  // Center square of the image, scaled to SIZE x SIZE in halving steps so it stays smooth.
  function squarePixels(image) {
    var side = Math.min(image.naturalWidth, image.naturalHeight);
    var sx = (image.naturalWidth - side) / 2;
    var sy = (image.naturalHeight - side) / 2;
    var size = side;
    while (size / 2 >= SIZE) {
      size = Math.floor(size / 2);
    }
    var canvas = document.createElement('canvas');
    canvas.width = canvas.height = size;
    var ctx = canvas.getContext('2d');
    ctx.imageSmoothingQuality = 'high';
    ctx.fillStyle = '#fff';  // transparent parts show as white, like the locket's face
    ctx.fillRect(0, 0, size, size);
    ctx.drawImage(image, sx, sy, side, side, 0, 0, size, size);
    while (size > SIZE) {
      var next = Math.max(SIZE, Math.floor(size / 2));
      var smaller = document.createElement('canvas');
      smaller.width = smaller.height = next;
      var sctx = smaller.getContext('2d');
      sctx.imageSmoothingQuality = 'high';
      sctx.drawImage(canvas, 0, 0, size, size, 0, 0, next, next);
      canvas = smaller;
      size = next;
    }
    return canvas.getContext('2d').getImageData(0, 0, SIZE, SIZE).data;
  }

  function useImage(image) {
    try {
      state.picture = bytesToB64(picture.encode(imageq, squarePixels(image)));
      drawPreview();
      setStatus('Looks good? Tap Save to send it to your watch.');
    } catch (e) {
      // A cross-origin image without CORS headers can't be read back from the canvas.
      setStatus('Couldn’t read that image. Try saving it and choosing it as a photo.');
    }
  }

  function loadImage(src, crossOrigin) {
    var image = new Image();
    if (crossOrigin) {
      image.crossOrigin = 'anonymous';
    }
    image.onload = function () {
      setStatus('Converting…');
      setTimeout(function () { useImage(image); }, 20);  // let the status paint first
    };
    image.onerror = function () {
      setStatus('Couldn’t load that image.');
    };
    setStatus('Loading…');
    image.src = src;
  }

  $('file').addEventListener('change', function (e) {
    var file = e.target.files && e.target.files[0];
    if (!file) {
      return;
    }
    var reader = new FileReader();
    reader.onload = function () {
      loadImage(reader.result, false);
    };
    reader.readAsDataURL(file);
    e.target.value = '';
  });

  $('load').addEventListener('click', function () {
    var url = $('url').value.trim();
    if (url) {
      loadImage(url, true);
    }
  });

  $('reset').addEventListener('click', function () {
    state.picture = '';
    drawPreview();
    setStatus('Using the default picture.');
  });

  // Message and options -------------------------------------------------------------------

  var message = $('message');
  function updateCount() {
    $('count').textContent = message.value.length + '/' + message.maxLength;
  }
  message.value = state.message;
  message.addEventListener('input', updateCount);
  updateCount();

  $('swap').checked = !!state.swapSides;

  var seconds = $('seconds');
  function updateSeconds() {
    $('seconds-label').textContent = seconds.value + (seconds.value === '1' ? ' second' : ' seconds');
  }
  seconds.value = state.openSeconds;
  seconds.addEventListener('input', updateSeconds);
  updateSeconds();

  document.querySelector('input[name=unit][value=' + (state.celsius ? 'c' : 'f') + ']').checked = true;

  $('save').addEventListener('click', function () {
    var result = {
      message: message.value.trim() ? message.value : DEFAULTS.message,
      picture: state.picture,
      swapSides: $('swap').checked,
      openSeconds: +seconds.value,
      celsius: document.querySelector('input[name=unit]:checked').value === 'c'
    };
    location.href = 'pebblejs://close#' + encodeURIComponent(JSON.stringify(result));
  });

  drawPreview();
  // Animate the controls from now on, not while setting their initial state.
  setTimeout(function () { document.body.classList.add('ready'); }, 50);
})();
