# My Beloved

A Pebble watchface with the heart locket from the "my beloved" memes (makesweet's
[Heart Locket](https://makesweet.com/my/heart-locket)). Flick your wrist and the locket
swings open, frame for frame like the GIF, showing your picture and message inside. It stays
open for a few seconds (3 by default), then closes again.

The time is shown above the locket, the date (MM/DD) bottom left and the temperature bottom
right. Weather comes from Open-Meteo (no API key) using the phone's location, falling back
to IP-based location, and refreshes every 30 minutes.

Settings (in the Pebble app):
- **Picture**: pick a photo or paste an image URL. The page crops it square, reduces it to
  80x80 in 16 of the Pebble's colors with [image-q](https://github.com/ibezkrovnyi/image-quantization)
  (CIEDE2000 color distance, Stucki dithering), and shows a preview. "Use default picture"
  puts back the built-in one (a Pebble Time, `assets/pebble-time-front.jpg`).
- **Message**: default "pebble my beloved", in makesweet's font (Arial; here the metric-identical
  Liberation Sans). Line breaks work like on makesweet; without them, long messages wrap.
- **Picture on the right**: swaps the picture and the message.
- **Seconds to stay open**, and **Celsius / Fahrenheit**.

The picture is stored on the watch, so it survives restarts without the phone.

Platforms: Pebble Time 2 (`emery`) and Pebble Round 2 (`gabbro`).

## Build

    pebble build
    pebble install --emulator emery
    pebble emu-tap --emulator emery     # flick

## Settings page

`src/settings/` is the settings page as plain HTML, CSS and JS; open `index.html` in a
browser to work on it. The build (`wscript`) inlines its scripts and the default picture
into one page (`src/pkjs/generated/settings_page.js`), which `src/pkjs/index.js` opens as
a `data:` URL with the saved settings filled in. The picture encoder (`picture.js`) is
shared with `tools/encode_picture.js`, which encodes the default picture.

## How the locket works

`tools/make_locket.py` turns `assets/heart-locket.gif` (makesweet's 34-frame preview) into
the watch frames in `resources/frames/` and the per-frame data in `src/c/locket_data.h`:

- The GIF's placeholder (four blue brackets around "your picture, your words" on the inside
  of the cover) is tracked frame by frame to get the perspective transform of the cover's
  face. The right half's face has no markings, so it is tracked by image alignment instead,
  and by fitting its outline while the cover hides most of it.
- Each frame is scaled down and ordered-dithered to the Pebble palette. The pixels of the two
  inner faces are painted in "marker" colors the red/white locket never uses; each marker
  says which face it is and how brightly it is lit.
- On the watch, `main.c` draws the frame and swaps every marker pixel for the picture or
  the message, sampled through that frame's inverse transform and shaded.
- The message is rendered like makesweet renders it (lines of Arial, centered, with a margin)
  by `text_engine.c` from a glyph atlas into an antialiased coverage texture with mipmaps.
  The compositor samples it bilinearly in perspective, picking the mip level from how much
  of the texture a pixel covers in that frame, and lights it with the face's shading, so the
  text sits on the locket and is hidden by the cover as it swings past.

To regenerate (needs Pillow, numpy, scipy and opencv-python-headless):

    python3 tools/make_locket.py --preview   # also encodes the default picture (needs node + npm install)
    python3 tools/make_font.py          # glyph atlas: resources/font_atlas.bin, src/c/font_data.h
    node tools/vendor_image_q.js        # after npm install: src/settings/vendor/image-q.js

`--preview` simulates the watch's output with the default picture into `build-preview/`
(an animated GIF and a contact sheet per platform). Screen placement of the locket is the
`PLATFORMS` table at the top of the script.

## Appstore

`store/` holds the Repebble appstore listing (`store/listing.md`) and its assets: icons,
banner and screenshots. The screenshots come from the emulators with default settings
(`pebble screenshot --no-correction`); the rest is generated:

    python3 tools/make_locket.py --preview   # simulated frames for the animated screenshots
    python3 tools/make_store_assets.py       # icons, menu icon, animations, banner

## Credits

- The locket animation, and so every frame in `resources/frames/`, comes from makesweet's
  [Heart Locket](https://makesweet.com/my/heart-locket) by Paul Fitzpatrick
  (https://makesweet.com); `assets/heart-locket.gif` is makesweet's preview of it.
- Default picture: ["Pebble Time front"](https://commons.wikimedia.org/wiki/File:Pebble_Time_front.jpg)
  by Frmorrison, [CC BY-SA 3.0](https://creativecommons.org/licenses/by-sa/3.0/), via
  Wikimedia Commons; cropped, scaled and dithered for the watch (the result,
  `resources/default_picture.bin`, is CC BY-SA 3.0 too). See `assets/pebble-time-front.txt`.
- Liberation Sans, by Red Hat / Google, SIL Open Font License 1.1 (`assets/fonts`).
- image-q by Igor Bezkrovnyi, MIT License (bundled in `src/settings/vendor/image-q.js`).

## License

MIT (see `LICENSE`) for this project's own code and assets; the third-party parts above
keep their own licenses.
