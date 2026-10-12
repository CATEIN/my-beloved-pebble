#!/usr/bin/env node
// Encodes an 80x80 RGB image (raw bytes, row major) to the watch's picture format with the
// settings page's own encoder (src/settings/picture.js). make_locket.py uses it for the
// default picture.
//
// Usage: node tools/encode_picture.js in.rgb out.bin   (needs npm install for image-q)
var fs = require('fs');
var path = require('path');
var iq = require('image-q');
var picture = require(path.join(__dirname, '..', 'src', 'settings', 'picture.js'));

var SIZE = picture.SIZE;
var rgb = fs.readFileSync(process.argv[2]);
var px = new Uint8Array(SIZE * SIZE * 4);
for (var i = 0; i < SIZE * SIZE; i++) {
  px[i * 4] = rgb[i * 3];
  px[i * 4 + 1] = rgb[i * 3 + 1];
  px[i * 4 + 2] = rgb[i * 3 + 2];
  px[i * 4 + 3] = 255;
}
fs.writeFileSync(process.argv[3], Buffer.from(picture.encode(iq, px)));
