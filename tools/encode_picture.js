#!/usr/bin/env node
// Encodes an 80x80 RGB image (raw bytes, row major) to the watch's picture format, exactly
// like the settings page does (src/pkjs/picture-picker.js: choosePalette and encode; keep
// them in sync). make_locket.py uses it for the default picture.
//
// Usage: node tools/encode_picture.js in.rgb out.bin   (needs npm install for image-q)
var fs = require('fs');
var lib = require('image-q');

var SIZE = 80;
var rgb = fs.readFileSync(process.argv[2]);
var px = new Uint8Array(SIZE * SIZE * 4);
for (var i = 0; i < SIZE * SIZE; i++) {
  px[i * 4] = rgb[i * 3];
  px[i * 4 + 1] = rgb[i * 3 + 1];
  px[i * 4 + 2] = rgb[i * 3 + 2];
  px[i * 4 + 3] = 255;
}

function choosePalette(px) {
  var distance = new lib.distance.CIEDE2000();
  var counts = {};
  for (var i = 0; i < px.length / 4; i++) {
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
var dither = new lib.image.ErrorDiffusionArray(
  new lib.distance.CIEDE2000(), lib.image.ErrorDiffusionArrayKernel.Stucki, true, 0, false);
var result = dither.quantizeSync(
  lib.utils.PointContainer.fromUint8Array(px, SIZE, SIZE), iqPalette).toUint8Array();

var out = Buffer.alloc(16 + SIZE * SIZE / 2);
palette.forEach(function(c, i) {
  out[i] = 0xC0 | c;
});
for (i = 0; i < SIZE * SIZE; i++) {
  var index = indexOf[(result[i * 4] << 16) | (result[i * 4 + 1] << 8) | result[i * 4 + 2]] || 0;
  out[16 + (i >> 1)] |= (i & 1) ? index : index << 4;
}
fs.writeFileSync(process.argv[3], out);
