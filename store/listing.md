# Appstore listing

For the Repebble appstore (the same fields and formats as Rebble's). Assets are in this folder;
regenerate them with `python3 tools/make_store_assets.py`.

- **Name:** My Beloved
- **Type:** Watchface
- **Platforms:** Pebble Time 2 (emery), Pebble Round 2 (gabbro)
- **Large icon:** `icon-large.png` (144x144) · **Small icon:** `icon-small.png` (48x48)
- **Banner:** `banner.png` (720x320)
- **Screenshots** (unframed, max 5 per platform):
  - emery: `screenshots/emery-animation.gif`, `screenshots/emery-open.png`, `screenshots/emery-closed.png`
  - gabbro: `screenshots/gabbro-animation.gif`, `screenshots/gabbro-open.png`, `screenshots/gabbro-closed.png`
- **Release:** `build/my-beloved.pbw` (version from package.json)
- **Source code:** https://github.com/CATEIN/my-beloved-pebble
- **Website:** _(optional)_

## Description (max 1600 characters)

The heart locket from the "my beloved" memes, on your wrist.

Flick your wrist and the locket swings open, frame for frame like the original animation,
to show your picture and your message inside. A few seconds later it closes again.

The message is drawn onto the locket itself: in perspective, lit like the locket, and
hidden by the cover as it swings past.

Settings (in the Pebble app):
- Picture: choose a photo or paste an image URL. It is cropped, reduced to 16 Pebble
  colors and dithered on your phone, then stored on the watch.
- Message: up to 80 characters. Add line breaks where you want them, or let it wrap.
- Picture on the left or the right.
- How long the locket stays open (2-20 seconds, default 3).

The time is shown above the locket, the date (MM/DD) bottom left and the current
temperature bottom right, in °C or °F to match the Pebble app (from its weather; turn on
plugins in its Settings).

Credits: the locket animation is makesweet's Heart Locket by Paul Fitzpatrick
(makesweet.com/my/heart-locket). Default picture: "Pebble Time front" by Frmorrison,
CC BY-SA 3.0, via Wikimedia Commons. Message font: Liberation Sans (OFL). Picture
dithering: image-q (MIT).

## Release notes (1.0.0)

First release.
