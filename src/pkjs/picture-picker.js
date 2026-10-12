// Clay component: choose a photo (file or URL), crop it square and convert it to what the
// watch shows inside the locket. The value is the watch format, base64 encoded: a 16-color
// palette (GColor8 bytes) then 80x80 4-bit indexes, high nibble first; '' means the default
// picture. Keep in sync with PICTURE_SIZE in main.c. The item's `imageq` config holds the
// image-q library (src/pkjs/vendor/image-q.js).
//
// Clay serializes this into the config page, so everything the page runs lives inside
// initialize() (no closures over module scope).
module.exports = {
  name: 'picture-picker',
  template:
    '<div class="component picture-picker">' +
    '  <label class="tap-highlight">' +
    '    <span class="label">{{label}}</span>' +
    '  </label>' +
    '  <div class="pp-body">' +
    '    <canvas class="pp-preview" width="80" height="80"></canvas>' +
    '    <div class="pp-controls">' +
    '      <input class="pp-file" type="file" accept="image/*">' +
    '      <div class="pp-url-row">' +
    '        <input class="pp-url" type="url" placeholder="...or an image URL">' +
    '        <button type="button" class="pp-load">Load</button>' +
    '      </div>' +
    '      <button type="button" class="pp-reset">Use default picture</button>' +
    '      <div class="pp-status"></div>' +
    '    </div>' +
    '  </div>' +
    '  <input type="hidden" class="pp-value" data-manipulator-target>' +
    '</div>',
  style:
    '.picture-picker .pp-body { padding: 8px 0; }' +
    '.picture-picker .pp-preview { display: block; width: 120px; height: 120px; margin-bottom: 10px;' +
    '  image-rendering: pixelated; border-radius: 6px; background: #ffaaaa; }' +
    '.picture-picker .pp-controls > * { display: block; width: 100%; box-sizing: border-box;' +
    '  margin-bottom: 8px; }' +
    '.picture-picker .pp-file { max-width: 100%; }' +
    '.picture-picker .pp-url-row { display: flex; gap: 6px; }' +
    '.picture-picker .pp-url { flex: 1; min-width: 0; }' +
    '.picture-picker .pp-load { flex: none; min-width: 0; width: auto; padding: 0 16px; }' +
    '.picture-picker .pp-status { font-size: 0.85em; opacity: 0.8; }',
  manipulator: {
    get: function() {
      return this.$manipulatorTarget.get('value');
    },
    set: function(value) {
      this.$manipulatorTarget.set('value', value || '');
      if (this._ppDraw) {
        this._ppDraw();
      }
      return this;
    }
  },
  defaults: {
    label: ''
  },
  initialize: function() {
    var SIZE = 80;
    var self = this;
    var root = self.$element[0];
    var preview = root.querySelector('.pp-preview');
    var status = root.querySelector('.pp-status');
    var hidden = root.querySelector('.pp-value');

    function setStatus(text) {
      status.textContent = text;
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

    // Shows the encoded picture (or a placeholder for the default one).
    function draw() {
      var ctx = preview.getContext('2d');
      ctx.clearRect(0, 0, SIZE, SIZE);
      if (!hidden.value) {
        ctx.fillStyle = '#ffaaaa';
        ctx.fillRect(0, 0, SIZE, SIZE);
        ctx.fillStyle = '#000';
        ctx.font = '11px sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText('default', SIZE / 2, SIZE / 2 + 4);
        return;
      }
      var bytes = b64ToBytes(hidden.value);
      var img = ctx.createImageData(SIZE, SIZE);
      for (var i = 0; i < SIZE * SIZE; i++) {
        var b = bytes[16 + (i >> 1)];
        var c = bytes[(i & 1) ? (b & 15) : (b >> 4)];
        img.data[i * 4] = ((c >> 4) & 3) * 85;
        img.data[i * 4 + 1] = ((c >> 2) & 3) * 85;
        img.data[i * 4 + 2] = (c & 3) * 85;
        img.data[i * 4 + 3] = 255;
      }
      ctx.putImageData(img, 0, 0);
    }
    self._ppDraw = draw;

    // Center-crops to a square and scales down in halving steps (much smoother than one
    // big drawImage step in most browsers).
    function toSquarePixels(image) {
      var side = Math.min(image.naturalWidth, image.naturalHeight);
      var sx = (image.naturalWidth - side) / 2;
      var sy = (image.naturalHeight - side) / 2;
      var canvas = document.createElement('canvas');
      var size = side;
      while (size / 2 >= SIZE) {
        size = Math.floor(size / 2);
      }
      canvas.width = canvas.height = size;
      var ctx = canvas.getContext('2d');
      ctx.imageSmoothingQuality = 'high';
      ctx.drawImage(image, sx, sy, side, side, 0, 0, size, size);
      while (size > SIZE) {
        var next = Math.max(SIZE, Math.floor(size / 2));
        var c2 = document.createElement('canvas');
        c2.width = c2.height = next;
        var ctx2 = c2.getContext('2d');
        ctx2.imageSmoothingQuality = 'high';
        ctx2.drawImage(canvas, 0, 0, size, size, 0, 0, next, next);
        canvas = c2;
        size = next;
      }
      return canvas.getContext('2d').getImageData(0, 0, SIZE, SIZE).data;
    }

    // image-q (MIT, vendored by tools/vendor_image_q.js) does the color science:
    // CIEDE2000 color distance and Stucki error diffusion.
    var iq = null;
    function imageq() {
      if (!iq) {
        iq = (0, eval)(atob(self.config.imageq));
      }
      return iq;
    }

    // Picks the 16 of the Pebble's 64 colors that best cover the image: greedily adds
    // whichever color most reduces the total (perceptual) error.
    function choosePalette(px) {
      var distance = new (imageq().distance.CIEDE2000)();
      var counts = {};
      for (var i = 0; i < px.length / 4; i++) {
        // Bucket by the 5-bit-per-channel color so the search runs over fewer colors.
        var key = ((px[i * 4] >> 3) << 10) | ((px[i * 4 + 1] >> 3) << 5) | (px[i * 4 + 2] >> 3);
        counts[key] = (counts[key] || 0) + 1;
      }
      var colors = Object.keys(counts).map(function(k) {
        k = +k;
        return [((k >> 10) & 31) * 8 + 4, ((k >> 5) & 31) * 8 + 4, (k & 31) * 8 + 4, counts[k]];
      });
      var dist = [];
      for (var c = 0; c < 64; c++) {
        var row = new Float32Array(colors.length);
        for (var j = 0; j < colors.length; j++) {
          row[j] = distance.calculateRaw(colors[j][0], colors[j][1], colors[j][2], 255,
                                         (c >> 4) * 85, ((c >> 2) & 3) * 85, (c & 3) * 85, 255);
        }
        dist.push(row);
      }
      var best = colors.map(function() { return Infinity; });
      var palette = [];
      var used = {};
      while (palette.length < 16) {
        var pick = -1;
        var pickGain = 0;
        for (c = 0; c < 64; c++) {
          if (used[c]) {
            continue;
          }
          var gain = 0;
          for (j = 0; j < colors.length; j++) {
            if (dist[c][j] < best[j]) {
              gain += (best[j] === Infinity ? 1e9 : best[j] - dist[c][j]) * colors[j][3];
            }
          }
          if (gain > pickGain) {
            pickGain = gain;
            pick = c;
          }
        }
        if (pick < 0) {
          break;
        }
        used[pick] = true;
        palette.push(pick);
        for (j = 0; j < colors.length; j++) {
          best[j] = Math.min(best[j], dist[pick][j]);
        }
      }
      return palette;
    }

    // Dithers to the chosen colors; returns the watch format bytes.
    function encode(px) {
      var lib = imageq();
      var palette = choosePalette(px);
      var iqPalette = new lib.utils.Palette();
      var indexOf = {};
      palette.forEach(function(c, i) {
        var r = (c >> 4) * 85;
        var g = ((c >> 2) & 3) * 85;
        var b = (c & 3) * 85;
        iqPalette.add(lib.utils.Point.createByRGBA(r, g, b, 255));
        indexOf[(r << 16) | (g << 8) | b] = i;
      });
      var opaque = new Uint8Array(px.length);
      for (var i = 0; i < px.length; i += 4) {
        opaque[i] = px[i];
        opaque[i + 1] = px[i + 1];
        opaque[i + 2] = px[i + 2];
        opaque[i + 3] = 255;
      }
      var dither = new lib.image.ErrorDiffusionArray(
        new lib.distance.CIEDE2000(), lib.image.ErrorDiffusionArrayKernel.Stucki, true, 0, false);
      var result = dither.quantizeSync(
        lib.utils.PointContainer.fromUint8Array(opaque, SIZE, SIZE), iqPalette).toUint8Array();

      var out = new Uint8Array(16 + SIZE * SIZE / 2);
      palette.forEach(function(c, i) {
        out[i] = 0xC0 | c;
      });
      for (i = 0; i < SIZE * SIZE; i++) {
        var index = indexOf[(result[i * 4] << 16) | (result[i * 4 + 1] << 8) | result[i * 4 + 2]] || 0;
        out[16 + (i >> 1)] |= (i & 1) ? index : index << 4;
      }
      return out;
    }

    function useImage(image) {
      try {
        var bytes = encode(toSquarePixels(image));
        self.set(bytesToB64(bytes));
        setStatus('Ready. Tap Save to send it to the watch.');
      } catch (e) {
        // A cross-origin image without CORS headers taints the canvas.
        setStatus('Couldn\'t read that image (' + e.message + '). Try saving it and picking the file.');
      }
    }

    function loadFrom(src, crossOrigin) {
      var image = new Image();
      if (crossOrigin) {
        image.crossOrigin = 'anonymous';
      }
      image.onload = function() {
        useImage(image);
      };
      image.onerror = function() {
        setStatus('Couldn\'t load that image.');
      };
      setStatus('Loading...');
      image.src = src;
    }

    root.querySelector('.pp-file').addEventListener('change', function(e) {
      var file = e.target.files && e.target.files[0];
      if (!file) {
        return;
      }
      var reader = new FileReader();
      reader.onload = function() {
        loadFrom(reader.result, false);
      };
      reader.readAsDataURL(file);
    });

    root.querySelector('.pp-load').addEventListener('click', function() {
      var url = root.querySelector('.pp-url').value.trim();
      if (url) {
        loadFrom(url, true);
      }
    });

    root.querySelector('.pp-reset').addEventListener('click', function() {
      self.set('');
      setStatus('Using the default picture.');
    });

    draw();
  }
};
