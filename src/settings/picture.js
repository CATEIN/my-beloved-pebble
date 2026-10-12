// Turns a photo into what the watch shows inside the locket: an 80x80 picture in 16 of the
// Pebble's 64 colors. Used by the settings page and by tools/encode_picture.js (the default
// picture), so both look the same.
//
// Watch format: 16 palette bytes (GColor8, 0b11rrggbb) then 80x80 4-bit palette indexes,
// row major, high nibble first. Keep SIZE in sync with PICTURE_SIZE in src/c/main.c.
//
// image-q (MIT, https://github.com/ibezkrovnyi/image-quantization) does the color science:
// CIEDE2000 color distance and Stucki error diffusion.
(function (root) {
  var SIZE = 80;

  // Picks the 16 of the Pebble's 64 colors that best cover the image: greedily adds
  // whichever color most reduces the total (perceptual) error.
  function choosePalette(iq, px) {
    var distance = new iq.distance.CIEDE2000();
    var counts = {};
    for (var i = 0; i < px.length / 4; i++) {
      // Bucket by the 5-bit-per-channel color so the search runs over fewer colors.
      var key = ((px[i * 4] >> 3) << 10) | ((px[i * 4 + 1] >> 3) << 5) | (px[i * 4 + 2] >> 3);
      counts[key] = (counts[key] || 0) + 1;
    }
    var colors = Object.keys(counts).map(function (k) {
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
    var best = colors.map(function () { return Infinity; });
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

  // px: SIZE x SIZE RGBA bytes. Returns the watch format bytes.
  function encode(iq, px) {
    var palette = choosePalette(iq, px);
    var iqPalette = new iq.utils.Palette();
    var indexOf = {};
    palette.forEach(function (c, i) {
      var r = (c >> 4) * 85;
      var g = ((c >> 2) & 3) * 85;
      var b = (c & 3) * 85;
      iqPalette.add(iq.utils.Point.createByRGBA(r, g, b, 255));
      indexOf[(r << 16) | (g << 8) | b] = i;
    });
    var opaque = new Uint8Array(px.length);
    for (var i = 0; i < px.length; i += 4) {
      opaque[i] = px[i];
      opaque[i + 1] = px[i + 1];
      opaque[i + 2] = px[i + 2];
      opaque[i + 3] = 255;
    }
    var dither = new iq.image.ErrorDiffusionArray(
      new iq.distance.CIEDE2000(), iq.image.ErrorDiffusionArrayKernel.Stucki, true, 0, false);
    var result = dither.quantizeSync(
      iq.utils.PointContainer.fromUint8Array(opaque, SIZE, SIZE), iqPalette).toUint8Array();

    var out = new Uint8Array(16 + SIZE * SIZE / 2);
    palette.forEach(function (c, i) {
      out[i] = 0xC0 | c;
    });
    for (i = 0; i < SIZE * SIZE; i++) {
      var index = indexOf[(result[i * 4] << 16) | (result[i * 4 + 1] << 8) | result[i * 4 + 2]] || 0;
      out[16 + (i >> 1)] |= (i & 1) ? index : index << 4;
    }
    return out;
  }

  // Watch format bytes -> SIZE x SIZE RGBA, for previews.
  function decode(bytes) {
    var rgba = new Uint8ClampedArray(SIZE * SIZE * 4);
    for (var i = 0; i < SIZE * SIZE; i++) {
      var b = bytes[16 + (i >> 1)];
      var c = bytes[(i & 1) ? (b & 15) : (b >> 4)];
      rgba[i * 4] = ((c >> 4) & 3) * 85;
      rgba[i * 4 + 1] = ((c >> 2) & 3) * 85;
      rgba[i * 4 + 2] = (c & 3) * 85;
      rgba[i * 4 + 3] = 255;
    }
    return rgba;
  }

  var api = { SIZE: SIZE, encode: encode, decode: decode };
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = api;
  } else {
    root.picture = api;
  }
})(this);
