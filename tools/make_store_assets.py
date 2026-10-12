#!/usr/bin/env python3
"""Rebble appstore assets for My Beloved.

Inputs:
  store/screenshots/<platform>-{closed,open}.png   emulator screenshots, taken with
      pebble screenshot --emulator <platform> --no-correction (fresh install, default settings)
  build-preview/frames-<platform>.npz              from tools/make_locket.py --preview

Outputs:
  store/icon-large.png (144x144), store/icon-small.png (48x48)   red heart
  resources/images/menu_icon.png (25x25)                          the same heart, for the watch
  store/screenshots/<platform>-animation.gif                      a flick: closed, open, closed
  store/banner.png (720x320)                                      marketing banner

Usage: python3 tools/make_store_assets.py   (needs Pillow and numpy)
"""
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
STORE = ROOT / "store"
SHOTS = STORE / "screenshots"
PREVIEW = ROOT / "build-preview"
PLATFORMS = ("emery", "gabbro")
BOLD = "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"
REGULAR = ROOT / "assets" / "fonts" / "LiberationSans-Regular.ttf"

RED = (220, 20, 50)
DARK_RED = (150, 0, 25)

# What the watch does on a flick (main.c): the GIF's own timing to open, stay open
# (DEFAULT_OPEN_SECONDS), close at 70 ms a frame.
CLOSED_MS = 1200
OPEN_MS = 3000
CLOSE_FRAME_MS = 70


def heart_polygon(cx, cy, size, steps=400):
    """The classic heart curve, `size` wide, centered on (cx, cy)."""
    t = np.linspace(0, 2 * np.pi, steps, endpoint=False)
    x = 16 * np.sin(t) ** 3
    y = -(13 * np.cos(t) - 5 * np.cos(2 * t) - 2 * np.cos(3 * t) - np.cos(4 * t))
    s = size / 34
    y0 = (y.max() + y.min()) / 2
    return [(cx + a * s, cy + (b - y0) * s) for a, b in zip(x, y)]


def heart(size, shine=True):
    """A red heart with a soft top-left light, on transparency, `size` px square."""
    ss = 8
    S = size * ss
    pad = S * 0.06
    poly = heart_polygon(S / 2, S / 2, S - 2 * pad)
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).polygon(poly, fill=255)

    # Lit from the top left: a radial blend from red to dark red.
    yy, xx = np.mgrid[0:S, 0:S] / S
    d = np.clip(np.hypot(xx - 0.3, yy - 0.25) / 0.85, 0, 1)[..., None]
    rgb = (np.array(RED) * (1 - d) + np.array(DARK_RED) * d).astype(np.uint8)
    img = Image.fromarray(rgb, "RGB").convert("RGBA")
    img.putalpha(mask)

    if shine:
        glow = Image.new("L", (S, S), 0)
        ImageDraw.Draw(glow).ellipse([S * 0.24, S * 0.2, S * 0.38, S * 0.3], fill=170)
        glow = glow.filter(ImageFilter.GaussianBlur(S * 0.02))
        white = Image.new("RGBA", (S, S), (255, 255, 255, 255))
        white.putalpha(Image.fromarray(np.minimum(np.asarray(glow), np.asarray(mask))))
        img = Image.alpha_composite(img, white)
    return img.resize((size, size), Image.LANCZOS)


def menu_icon():
    """25x25 for the watch, in Pebble colors: a plain heart (no anti-aliasing to muddy it)."""
    S = 25 * 8
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).polygon(heart_polygon(S / 2, S / 2 + 4, S - 16), fill=255)
    mask = mask.resize((25, 25), Image.BOX).point(lambda v: 255 if v >= 128 else 0)
    img = Image.new("RGBA", (25, 25), (0, 0, 0, 0))
    img.paste(Image.new("RGBA", (25, 25), (255, 0, 85, 255)), (0, 0), mask)  # GColorFolly
    return img


def animation(platform):
    """The flick, as the watch shows it: the locket frames from make_locket.py's simulation
    composited into the emulator screenshot (time, date, temperature)."""
    data = np.load(PREVIEW / f"frames-{platform}.npz")
    screens, (x0, y0, w, h), durations = data["screens"], data["rect"], data["durations"]
    base = np.asarray(Image.open(SHOTS / f"{platform}-closed.png").convert("RGB")).copy()
    H, W = base.shape[:2]
    yy, xx = np.mgrid[0:H, 0:W]
    screen = np.zeros((H, W), bool)
    screen[y0:y0 + h, x0:x0 + w] = True
    if platform == "gabbro":  # round display: leave the screenshot's corners alone
        screen &= (xx - (W - 1) / 2) ** 2 + (yy - (H - 1) / 2) ** 2 <= (W / 2) ** 2
    frames = []
    for s in screens:
        f = base.copy()
        f[screen] = s[screen]
        frames.append(Image.fromarray(f))
    n = len(frames)
    seq = [(frames[0], CLOSED_MS)]
    seq += [(frames[i], int(durations[i])) for i in range(1, n - 1)]
    seq += [(frames[-1], OPEN_MS)]
    seq += [(frames[i], CLOSE_FRAME_MS) for i in range(n - 2, 0, -1)]
    imgs, ms = zip(*seq)
    imgs[0].save(SHOTS / f"{platform}-animation.gif", save_all=True, append_images=imgs[1:],
                 duration=list(ms), loop=0, optimize=False, disposal=1)


def framed_emery(shot):
    """A Pebble Time 2-ish frame: black body, screen inset."""
    bw, bh = shot.width + 36, shot.height + 64
    img = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, bw - 1, bh - 1], 30, fill=(28, 28, 32))
    d.rounded_rectangle([3, 3, bw - 4, bh - 4], 28, outline=(70, 70, 78), width=2)
    img.paste(shot, (18, 32))
    return img


def framed_gabbro(shot):
    """A Pebble Round 2-ish frame: round bezel."""
    r = shot.width // 2
    B = 18
    size = shot.width + 2 * B
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse([0, 0, size - 1, size - 1], fill=(28, 28, 32))
    d.ellipse([3, 3, size - 4, size - 4], outline=(70, 70, 78), width=2)
    m = Image.new("L", shot.size, 0)
    ImageDraw.Draw(m).ellipse([0, 0, 2 * r - 1, 2 * r - 1], fill=255)
    img.paste(shot, (B, B), m)
    return img


def shadow(img, blur=10, offset=(0, 8), alpha=90):
    a = np.asarray(img.split()[3]).astype(np.float32) * alpha / 255
    pad = blur * 3
    sh = Image.new("L", (img.width + 2 * pad, img.height + 2 * pad), 0)
    sh.paste(Image.fromarray(a.astype(np.uint8)), (pad + offset[0], pad + offset[1]))
    return sh.filter(ImageFilter.GaussianBlur(blur)), pad


def paste_with_shadow(canvas, img, x, y):
    sh, pad = shadow(img)
    black = Image.new("RGBA", sh.size, (60, 0, 15, 255))
    black.putalpha(sh)
    canvas.alpha_composite(black, (x - pad, y - pad))
    canvas.alpha_composite(img, (x, y))


def banner():
    W, H = 720, 320
    yy, xx = np.mgrid[0:H, 0:W]
    t = np.clip((xx / W) * 0.6 + (yy / H) * 0.4, 0, 1)[..., None]
    top, bottom = np.array([255, 214, 222]), np.array([255, 160, 180])
    canvas = Image.fromarray((top * (1 - t) + bottom * t).astype(np.uint8)).convert("RGBA")

    # A few faint hearts in the background.
    rng = np.random.default_rng(7)
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    placed = 0
    while placed < 12:
        s = int(rng.uniform(18, 46))
        hx, hy = int(rng.uniform(0, W - s)), int(rng.uniform(0, H - s))
        if hx < 310 and hy + s > 50:  # keep the title area clean
            continue
        placed += 1
        h = heart(s, shine=False)
        h.putalpha(h.split()[3].point(lambda v: v * 0.18))
        layer.alpha_composite(h, (hx, hy))
    canvas.alpha_composite(layer)

    emery_shot = Image.open(SHOTS / "emery-open.png").convert("RGB")
    emery = framed_emery(emery_shot.resize((160, 182), Image.LANCZOS))
    gabbro = framed_gabbro(Image.open(SHOTS / "gabbro-open.png").convert("RGB")
                           .resize((172, 172), Image.LANCZOS))
    paste_with_shadow(canvas, emery, 316, (H - emery.height) // 2 - 4)
    paste_with_shadow(canvas, gabbro, W - gabbro.width - 12, (H - gabbro.height) // 2 + 6)

    d = ImageDraw.Draw(canvas)
    title = ImageFont.truetype(BOLD, 48)
    sub = ImageFont.truetype(str(REGULAR), 19)
    canvas.alpha_composite(heart(60), (30, 58))
    d.text((30, 128), "My Beloved", font=title, fill=DARK_RED)
    lines = ["The heart locket meme on your", "wrist. Flick to open it and see", "your picture and message."]
    for i, line in enumerate(lines):
        d.text((32, 192 + i * 25), line, font=sub, fill=(110, 20, 40))
    return canvas.convert("RGB")


def main():
    heart(144).save(STORE / "icon-large.png")
    heart(48).save(STORE / "icon-small.png")
    menu_icon().save(ROOT / "resources" / "images" / "menu_icon.png")
    for p in PLATFORMS:
        animation(p)
    banner().save(STORE / "banner.png")
    for f in sorted(STORE.rglob("*.png")) + sorted(STORE.rglob("*.gif")):
        with Image.open(f) as im:
            print(f"{f.relative_to(ROOT)}: {im.size[0]}x{im.size[1]}, {f.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
