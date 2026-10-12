#!/usr/bin/env python3
"""Turn the makesweet heart-locket GIF into watch frames plus the data needed to put a
custom picture and message inside it.

The GIF (assets/heart-locket.gif, 400x300, 34 frames) has a placeholder on the inside of
the cover: four blue corner brackets around "your picture, your words". The brackets are
tracked to get, for every frame, the perspective transform (homography) of the cover's
inner face. The other half has no markings, so its face is tracked with ECC image
alignment against the last frame instead, and by fitting its outline while the cover hides
most of it.

Each watch frame is the GIF frame scaled down and ordered-dithered to the Pebble palette,
except that the pixels of the two inner faces are replaced with "marker" colors that the
locket itself can never produce (the locket is red/white/grey, so its green and blue
channels never exceed its red one). A marker encodes which face (slot 0 = the cover on the
left, slot 1 = the right half) and how brightly that pixel is lit (one of SHADE_LEVELS).
On the watch, src/c/main.c swaps every marker pixel for the picture or the message,
sampled through the frame's inverse homography and darkened by the shade.

Outputs:
  resources/frames/fNN~<platform>.png   one per GIF frame and platform
  resources/default_picture.bin         the default picture (same format the phone sends)
  src/c/locket_data.h                   per-frame homographies, layout, marker colors
  build-preview/                        simulated watch output (with --preview)

Usage: python3 tools/make_locket.py [--preview]
Needs Pillow, numpy, scipy and opencv-python-headless.
"""
import itertools
import subprocess
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy.ndimage import map_coordinates
from scipy.optimize import least_squares

ROOT = Path(__file__).resolve().parent.parent
SRC_GIF = ROOT / "assets" / "heart-locket.gif"
FRAMES_DIR = ROOT / "resources" / "frames"
DEFAULT_PICTURE = ROOT / "resources" / "default_picture.bin"
DEFAULT_PICTURE_SRC = ROOT / "assets" / "pebble-time-front.jpg"  # see pebble-time-front.txt
# Square crop (center x, center y, side, as fractions of the width) framing the watch with
# room to spare, so the heart-shaped face doesn't cut it off; outside the photo is white
# like its background.
DEFAULT_PICTURE_CROP = (0.54, 0.47, 1.2)
HEADER = ROOT / "src" / "c" / "locket_data.h"
PREVIEW_DIR = ROOT / "build-preview"

# Where the GIF lands on each screen: it is scaled to gif_size and its top-left placed at
# offset (so it may hang off the screen; only the locket's bounding box is kept).
PLATFORMS = {
    "emery": dict(screen=(200, 228), gif_size=(200, 150), offset=(0, 34), round=False),
    "gabbro": dict(screen=(260, 260), gif_size=(236, 177), offset=(12, 30), round=True),
}

# Picture texture (sent from the phone, 4-bit palettised) and message texture (drawn on
# the watch). Keep in sync with PICTURE_SIZE in main.c and the config page, and
# TEXT_TEX_SIZE in text_engine.h.
PICTURE_SIZE = 80
TEXT_SIZE = 128
TEXT_FONT = ROOT / "assets" / "fonts" / "LiberationSans-Regular.ttf"

SHADE_LEVELS = 8
Q = 20  # fixed-point fraction bits of the exported homographies

# The cover's face first shows (edge on) in frame 17, the right half's in frame 9.
SLOT_FIRST_FRAME = (17, 8)
# From this frame back, the right face is tracked by its outline instead of ECC.
OUTLINE_FIT_FROM = 14
# Weight of smooth motion against each frame's own tracking (per GIF px of corner jerk).
SMOOTHNESS = 1.0

BAYER4 = np.array([[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]])


def load_gif():
    im = Image.open(SRC_GIF)
    frames, durations = [], []
    for i in range(im.n_frames):
        im.seek(i)
        frames.append(np.asarray(im.convert("RGB")).astype(np.float32))
        durations.append(im.info.get("duration", 100))
    return frames, durations


def is_placeholder(a):
    """The blue brackets and words (the right half has a faint light-blue highlight)."""
    r, b = a[..., 0], a[..., 2]
    return (b > 120) & (b - r > 90)


def outside(a, wall):
    """Background: pixels of the GIF's background color connected to the image border.
    The faces' whites use the very same palette entry; they are usually cut off by the rim,
    but while the cover swings its face meets the background directly, so the fill is also
    stopped at `wall` (the inside of the cover's face)."""
    bg = ((np.abs(a - np.float32([252, 254, 252])).max(2) < 1) & ~wall).astype(np.uint8)
    n, lab = cv2.connectedComponents(bg, connectivity=4)
    border = np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]]))
    return np.isin(lab, border[border > 0])


def is_light(a):
    """Inner-face pixels: white to mid grey, unsaturated (the locket rim is red)."""
    mx, mn = a.max(2), a.min(2)
    return ((mn > 110) & (mx - mn < 60)) | is_placeholder(a)


def bracket_quads(frames):
    """Outer corners of the four placeholder brackets (TL, TR, BR, BL of the picture
    square), tracked backwards from the fully open last frame."""
    def raw_quad(a):
        ys, xs = np.nonzero(is_placeholder(a))
        hull = cv2.convexHull(np.stack([xs, ys], 1).astype(np.float32))[:, 0]
        best = max(itertools.combinations(range(len(hull)), 4),
                   key=lambda c: cv2.contourArea(hull[list(c)]))
        return hull[list(best)]

    quads = {}
    last = len(frames) - 1
    prev = None
    for i in range(last, SLOT_FIRST_FRAME[0], -1):
        q = raw_quad(frames[i])
        if prev is None:
            c = q.mean(0)
            q = q[np.argsort(np.arctan2(q[:, 1] - c[1], q[:, 0] - c[0]))]
            q = np.roll(q, -int(np.argmin(q.sum(1))), 0)
        else:
            perm = min(itertools.permutations(range(4)),
                       key=lambda p: np.linalg.norm(q[list(p)] - prev, axis=1).sum())
            q = q[list(perm)]
        quads[i] = q
        prev = q
    # In the first frame the cover is edge on and the brackets are clipped; extrapolate.
    f = SLOT_FIRST_FRAME[0]
    quads[f] = 2 * quads[f + 1] - quads[f + 2]
    # The corners are whole pixels of the bracket outlines and jitter by a pixel or two;
    # smooth their paths (Whittaker smoother: close to the data, small second differences).
    idx = list(range(f, last + 1))
    n = len(idx)
    weight = np.ones(n)
    weight[0] = 0.05
    D = np.diff(np.eye(n), 2, axis=0) * SMOOTHNESS
    A = np.vstack([np.diag(weight), D])
    data = np.stack([quads[i].ravel() for i in idx]).astype(np.float64)
    smooth = np.linalg.lstsq(A, np.vstack([data * weight[:, None], np.zeros((n - 2, 8))]),
                             rcond=None)[0]
    return {i: smooth[k].reshape(4, 2) for k, i in enumerate(idx)}


def face_masks_open(a):
    """The two inner faces in the fully open frame: light regions enclosed by the rim."""
    n, lab = cv2.connectedComponents(is_light(a).astype(np.uint8), connectivity=4)
    border = set(np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]])))
    comps = sorted((k for k in range(1, n) if k not in border), key=lambda k: -(lab == k).sum())
    faces = []
    for k in comps[:2]:
        cnts, _ = cv2.findContours((lab == k).astype(np.uint8), cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_NONE)
        f = np.zeros(a.shape[:2], np.uint8)
        cv2.drawContours(f, cnts, -1, 1, -1)
        faces.append(f)
    faces.sort(key=lambda f: np.nonzero(f)[1].mean())
    return faces


def track_right_face(frames, face):
    """Homographies mapping last-frame pixels of the right face to each frame's pixels."""
    gray = [cv2.GaussianBlur(cv2.cvtColor(f, cv2.COLOR_RGB2GRAY), (0, 0), 1.5) for f in frames]
    last = len(frames) - 1
    tmask = cv2.dilate(face, np.ones((15, 15), np.uint8))
    crit = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 300, 1e-6)
    W = np.eye(3, dtype=np.float32)
    Ws = {last: W.copy()}
    for i in range(last - 1, OUTLINE_FIT_FROM, -1):
        if i >= 16:
            m = tmask
        else:
            # The cover hides the left part; align on what is still visible.
            m = tmask.copy()
            m[:, :290] = 0
        _, W = cv2.findTransformECC(gray[last], gray[i], W.copy(), cv2.MOTION_HOMOGRAPHY,
                                    crit, m, 5)
        Ws[i] = W.copy()
    Ws = {i: W.astype(np.float64) for i, W in Ws.items()}

    # Further back the cover hides most of the face, which is too plain for image
    # alignment. Fit its outline instead: the cover only hides it from the left, so the
    # right edge of what is visible is the heart's own edge, and everything visible must
    # lie inside the heart.
    inside = cv2.distanceTransform(face, cv2.DIST_L2, 5)
    outside_ = cv2.distanceTransform(1 - face, cv2.DIST_L2, 5)
    signed = (outside_ - inside).astype(np.float64)  # negative inside the face

    def signed_at(H, p):
        q = np.c_[p, np.ones(len(p))] @ np.linalg.inv(H).T
        q = q[:, :2] / q[:, 2:]
        return map_coordinates(signed, [q[:, 1], q[:, 0]], order=1, mode="nearest")

    weights = np.array([1, 1, .02, 1, 1, .02, 1000, 1000]) * 3
    outlines = {}
    for i in range(OUTLINE_FIT_FROM, SLOT_FIRST_FRAME[1], -1):
        a = frames[i]
        light = is_light(a) & ~outside(a, np.zeros(a.shape[:2], bool))
        n, lab = cv2.connectedComponents(light.astype(np.uint8), connectivity=4)
        vis = lab == 1 + np.argmax([(lab == k).sum() for k in range(1, n)])
        edge = np.array([(np.nonzero(r)[0].max() + 0.5, y) for y, r in enumerate(vis) if r.any()])
        ys, xs = np.nonzero(vis)
        area = np.c_[xs, ys][::3].astype(np.float64)
        outlines[i] = edge, area
        prev = Ws[i + 1].ravel()[:8]

        def residuals(h):
            H = np.append(h, 1).reshape(3, 3)
            return np.concatenate([signed_at(H, edge),
                                   np.maximum(signed_at(H, area) + 1, 0) * 0.5,
                                   (h - prev) * weights])  # weak pull toward the next frame

        Ws[i] = np.append(least_squares(residuals, prev, x_scale="jac", max_nfev=2000).x,
                          1).reshape(3, 3)

    # The first frames show only a sliver; extrapolate the face's corners.
    ys, xs = np.nonzero(face)
    box = np.float32([[xs.min(), ys.min()], [xs.max(), ys.min()],
                      [xs.max(), ys.max()], [xs.min(), ys.max()]])
    f = SLOT_FIRST_FRAME[1] + 1
    P = {i: cv2.perspectiveTransform(box[None], Ws[i])[0] for i in (f, f + 1, f + 2)}
    for i in range(f - 1, SLOT_FIRST_FRAME[1] - 1, -1):
        t = f - i
        q = P[f] + (P[f] - P[f + 1]) * t + 0.5 * (P[f] - 2 * P[f + 1] + P[f + 2]) * t * t
        Ws[i] = cv2.getPerspectiveTransform(box, np.float32(q)).astype(np.float64)

    # Each frame on its own is a little off, differently every frame, so the face (and the
    # text on it) would wobble. Solve all frames at once: each stays close to its own
    # evidence (the ECC result, or the outline), and the face's corners must move smoothly.
    first = SLOT_FIRST_FRAME[1]
    tracked = {i: cv2.perspectiveTransform(box[None], Ws[i].astype(np.float32))[0]
               .astype(np.float64) for i in Ws}
    free = list(range(first, last))  # the last frame is the reference

    def corners(x):
        c = {i: x[k * 8:(k + 1) * 8].reshape(4, 2) for k, i in enumerate(free)}
        c[last] = tracked[last]
        return c

    def joint_residuals(x):
        c = corners(x)
        out = []
        for i in free:
            if i in outlines:
                edge, area = outlines[i]
                H = homography(box, c[i])
                out += [signed_at(H, edge), np.maximum(signed_at(H, area) + 1, 0) * 0.5]
            elif i > OUTLINE_FIT_FROM:
                out.append((c[i] - tracked[i]).ravel())
            else:
                out.append((c[i] - tracked[i]).ravel() * 0.05)  # extrapolated, barely trusted
        for i in range(first + 1, last):
            out.append((c[i - 1] - 2 * c[i] + c[i + 1]).ravel() * SMOOTHNESS)
        return np.concatenate(out)

    x0 = np.concatenate([tracked[i].ravel() for i in free])
    c = corners(least_squares(joint_residuals, x0, x_scale="jac", max_nfev=200).x)
    return {i: homography(box, c[i]) for i in range(first, last + 1)}


def homography(src, dst):
    """3x3 homography taking the 4 points src to dst (float64 throughout)."""
    A, b = [], []
    for (x, y), (u, v) in zip(src, dst):
        A += [[x, y, 1, 0, 0, 0, -u * x, -u * y], [0, 0, 0, x, y, 1, -v * x, -v * y]]
        b += [u, v]
    return np.append(np.linalg.solve(np.array(A, np.float64), b), 1).reshape(3, 3)


def square_around(mask_pts):
    """Smallest axis-aligned square (x, y, side) containing the points' bounding box."""
    x0, y0 = mask_pts.min(0)
    x1, y1 = mask_pts.max(0)
    side = max(x1 - x0, y1 - y0)
    return (x0 + x1 - side) / 2, (y0 + y1 - side) / 2, side


def heart_tilt(face):
    """Angle (radians) of the heart's symmetry axis from vertical, positive when its tip
    points down-right: the reflection across that axis that best maps the mask onto itself."""
    ys, xs = np.nonzero(face)
    c = np.array([xs.mean(), ys.mean()])
    best = (-1, 0)
    for deg in np.arange(-40, 40.01, 0.25):
        t = np.radians(deg)
        d = np.array([np.sin(t), np.cos(t)])
        R = 2 * np.outer(d, d) - np.eye(2)
        A = np.hstack([R, (c - R @ c)[:, None]])
        r = cv2.warpAffine(face, A, (face.shape[1], face.shape[0]), flags=cv2.INTER_NEAREST)
        iou = (r & face).sum() / (r | face).sum()
        best = max(best, (iou, t))
    return best[1]


def tilted_square_around(face, t):
    """unit->image transform of the smallest square containing the face whose sides follow
    the heart's axis (tilted by t), so the texture's "up" is the heart's up."""
    ys, xs = np.nonzero(face)
    ex = np.array([np.cos(t), -np.sin(t)])  # texture u direction (across the heart)
    ey = np.array([np.sin(t), np.cos(t)])   # texture v direction (down the axis)
    pts = np.stack([xs, ys], 1).astype(np.float64)
    u, v = pts @ ex, pts @ ey
    side = max(u.max() - u.min(), v.max() - v.min())
    cu, cv_ = (u.max() + u.min()) / 2, (v.max() + v.min()) / 2
    origin = (cu - side / 2) * ex + (cv_ - side / 2) * ey
    return np.array([[side * ex[0], side * ey[0], origin[0]],
                     [side * ex[1], side * ey[1], origin[1]], [0, 0, 1]], np.float64)


def unit_to_square(x, y, side):
    return np.array([[side, 0, x], [0, side, y], [0, 0, 1]], np.float64)


def canonical_heart(H_unit_to_img, face, res=256):
    """The face mask in texture space ([0,1]^2 sampled at res x res)."""
    S = np.array([[1 / res, 0, 0.5 / res], [0, 1 / res, 0.5 / res], [0, 0, 1]])
    M = H_unit_to_img @ S
    return cv2.warpPerspective(face.astype(np.float32), np.linalg.inv(M), (res, res),
                               flags=cv2.INTER_LINEAR) > 0.5


def text_safe_rect(heart):
    """Largest rectangle (at least as wide as tall) inside the heart, as fractions of the
    texture: (x, y, w, h)."""
    step = 4
    g = heart[step // 2::step, step // 2::step]
    n = g.shape[0]
    best = (0, 0, 0, 0, 0)
    for y0 in range(n):
        full = np.ones(n, bool)
        for y1 in range(y0, n):
            full &= g[y1]
            h = y1 - y0 + 1
            run = 0
            for x in range(n):
                run = run + 1 if full[x] else 0
                if run >= h and run * h > best[0]:
                    best = (run * h, x - run + 1, y0, run, h)
    _, x0, y0, w, h = best
    s = step / heart.shape[0]
    return x0 * s, y0 * s, w * s, h * s


def marker_colors():
    """2 x SHADE_LEVELS Pebble colors (r, g, b in 0..3) the dithered locket never uses."""
    cands = [(r, g, b) for r in range(4) for g in range(4) for b in range(4) if max(g, b) > r]
    cands.sort(key=lambda c: (c[0], -max(c[1], c[2]), c))
    return [cands[s * SHADE_LEVELS:(s + 1) * SHADE_LEVELS] for s in range(2)]


def argb8(c):
    r, g, b = c
    return 0xC0 | (r << 4) | (g << 2) | b


def dither(rgb, x0, y0):
    """Ordered dither to the 4-level-per-channel Pebble palette, anchored to the screen."""
    h, w, _ = rgb.shape
    ys, xs = np.mgrid[0:h, 0:w]
    t = (BAYER4[(ys + y0) % 4, (xs + x0) % 4] + 0.5) / 16
    lv = np.floor(rgb / 255 * 3 + t[..., None]).clip(0, 3).astype(np.uint8)
    # Keep green and blue at or below red so no locket pixel can look like a marker.
    lv[..., 1] = np.minimum(lv[..., 1], lv[..., 0])
    lv[..., 2] = np.minimum(lv[..., 2], lv[..., 0])
    return lv


def save_palettised(lv, path):
    """Save a (h, w, 3) array of 0..3 channel levels as an exact palettised PNG."""
    flat = lv.reshape(-1, 3)
    colors, idx = np.unique(flat, axis=0, return_inverse=True)
    im = Image.fromarray(idx.reshape(lv.shape[:2]).astype(np.uint8), "P")
    pal = (colors.astype(int) * 85).reshape(-1).tolist()
    im.putpalette(pal + [0] * (768 - len(pal)))
    im.save(path, optimize=True)


def make_default_picture():
    """assets/pebble-time-front.jpg, cropped square around the watch and reduced to 80x80 in the phone's
    format, encoded the way the settings page encodes pictures (tools/encode_picture.js).
    Returns it as Pebble color levels for the preview."""
    im = Image.open(DEFAULT_PICTURE_SRC).convert("RGB")
    cx, cy, side = (v * im.width for v in DEFAULT_PICTURE_CROP)
    canvas = Image.new("RGB", (round(side), round(side)), (255, 255, 255))
    canvas.paste(im, (round(side / 2 - cx), round(side / 2 - cy)))
    im = canvas
    im = im.resize((PICTURE_SIZE, PICTURE_SIZE), Image.LANCZOS)
    with tempfile.NamedTemporaryFile(suffix=".rgb") as raw:
        raw.write(im.tobytes())
        raw.flush()
        subprocess.run(["node", str(ROOT / "tools" / "encode_picture.js"), raw.name,
                        str(DEFAULT_PICTURE)], check=True)
    data = DEFAULT_PICTURE.read_bytes()
    palette = [((c >> 4) & 3, (c >> 2) & 3, c & 3) for c in data[:16]]
    packed = np.frombuffer(data[16:], np.uint8).reshape(PICTURE_SIZE, PICTURE_SIZE // 2)
    idx = np.stack([packed >> 4, packed & 15], 2).reshape(PICTURE_SIZE, PICTURE_SIZE)
    return np.array([[palette[i] for i in row] for row in idx], np.uint8)


def render_text_texture(text, rect):
    """Preview stand-in for text_engine.c: makesweet's layout (Arial metrics via Liberation
    Sans, 20px margin at 96px/em, centered lines) as an ink coverage texture, with mips."""
    pad, line = 20 / 96, 1.15
    x, y, w, h = [v * TEXT_SIZE for v in rect]
    probe = ImageFont.truetype(str(TEXT_FONT), 100)

    def em_for(lines):
        widest = max(probe.getlength(t) for t in lines) / 100
        return min(w / (widest + 2 * pad), h / (len(lines) * line + 2 * pad))

    if "\n" in text:
        lines = text.split("\n")
    else:
        words = text.split()
        lines, best = [text], em_for([text])
        for n in (2, 3):
            if len(words) < n:
                break
            cands = [[" ".join(words[a:b]) for a, b in zip((0,) + cut, cut + (len(words),))]
                     for cut in itertools.combinations(range(1, len(words)), n - 1)]
            cand = min(cands, key=lambda c: max(probe.getlength(t) for t in c))
            if em_for(cand) > best * 1.15:
                lines, best = cand, em_for(cand)
    em = em_for(lines)
    S = 4
    font = ImageFont.truetype(str(TEXT_FONT), max(1, round(em * S)))
    im = Image.new("L", (TEXT_SIZE * S, TEXT_SIZE * S), 0)
    d = ImageDraw.Draw(im)
    asc, desc = font.getmetrics()
    top = y + (h - len(lines) * line * em) / 2
    for i, t in enumerate(lines):
        lx = x + (w - font.getlength(t) / S) / 2
        base = top + i * line * em + (line * em - (asc + desc) / S) / 2 + asc / S
        d.text((lx * S, base * S), t, font=font, fill=255, anchor="ls")
    level0 = np.asarray(im.resize((TEXT_SIZE, TEXT_SIZE), Image.BOX)).astype(np.float32)
    mips = [level0]
    for _ in range(2):
        m = mips[-1]
        mips.append(m.reshape(m.shape[0] // 2, 2, m.shape[1] // 2, 2).mean((1, 3)))
    return mips


def sample_bilinear(tex, u, v):
    size = tex.shape[0]
    x, y = u * size - 0.5, v * size - 0.5
    x0, y0 = int(np.floor(x)), int(np.floor(y))
    fx, fy = x - x0, y - y0
    c = lambda xx, yy: tex[min(max(yy, 0), size - 1), min(max(xx, 0), size - 1)]
    return ((c(x0, y0) * (1 - fx) + c(x0 + 1, y0) * fx) * (1 - fy) +
            (c(x0, y0 + 1) * (1 - fx) + c(x0 + 1, y0 + 1) * fx) * fy)


def main():
    preview = "--preview" in sys.argv
    frames, durations = load_gif()
    n = len(frames)
    last = n - 1

    # --- Inner-face geometry in GIF pixels -------------------------------------------
    quads = bracket_quads(frames)
    faces = face_masks_open(frames[last])
    unit_sq = np.float32([[0, 0], [1, 0], [1, 1], [0, 1]])

    # Slot 0 (cover): texture square = square around the face, in bracket-square units.
    Hb = {i: cv2.getPerspectiveTransform(unit_sq, np.float32(quads[i])).astype(np.float64)
          for i in quads}
    pts = cv2.perspectiveTransform(
        np.stack(np.nonzero(faces[0])[::-1], 1).astype(np.float32)[None],
        np.linalg.inv(Hb[last]))[0]
    T0 = unit_to_square(*square_around(pts))
    G0 = {i: Hb[i] @ T0 for i in Hb}

    # Slot 1 (right half): square around its face in the last frame, tilted with the heart
    # (the open locket leans, and makesweet's text leans with it).
    Wr = track_right_face(frames, faces[1])
    T1 = tilted_square_around(faces[1], heart_tilt(faces[1]))
    G1 = {i: Wr[i].astype(np.float64) @ T1 for i in Wr}
    G = [G0, G1]

    hearts = [canonical_heart(G[s][last], faces[s]) for s in range(2)]
    safe = [text_safe_rect(h) for h in hearts]

    # Per-frame visible face masks and lighting, in GIF pixels.
    vis = np.zeros((n, 2) + frames[0].shape[:2], np.float32)
    shade = np.ones((n,) + frames[0].shape[:2], np.float32)
    clean = []
    for i, a in enumerate(frames):
        regions = [None, None]
        for s in range(2):
            if i in G[s]:
                res = hearts[s].shape[0]
                S = np.array([[1 / res, 0, 0.5 / res], [0, 1 / res, 0.5 / res], [0, 0, 1]])
                regions[s] = cv2.warpPerspective(hearts[s].astype(np.uint8), G[s][i] @ S,
                                                 (a.shape[1], a.shape[0])) > 0
        wall = np.zeros(a.shape[:2], bool)
        if regions[0] is not None:
            wall = cv2.erode(regions[0].astype(np.uint8), np.ones((7, 7), np.uint8)) > 0
        light = is_light(a) & ~outside(a, wall)
        lum = a.max(2)
        ph = is_placeholder(a)
        taken = np.zeros(light.shape, bool)
        for s in range(2):
            if regions[s] is None:
                continue
            region = regions[s]
            m = region & light & ~taken
            m = cv2.morphologyEx(m.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8)) > 0
            m &= region & ~taken
            vis[i, s] = m
            taken |= m
        # Paint out the placeholder (brackets + words) with the surrounding face shading.
        fix = cv2.dilate(ph.astype(np.uint8), np.ones((5, 5), np.uint8))
        lum = cv2.inpaint(lum.clip(0, 255).astype(np.uint8), fix, 3, cv2.INPAINT_TELEA).astype(np.float32)
        shade[i] = lum / 255
        c = a.copy()
        c[fix > 0] = lum[fix > 0, None]
        clean.append(c)

    any_face = vis.sum(1) > 0
    lo = np.percentile(shade[any_face], 1)
    levels = [lo + (1 - lo) * (k + 0.5) / SHADE_LEVELS for k in range(SHADE_LEVELS)]
    markers = marker_colors()
    marker_lookup = {markers[s][k]: (s, k) for s in range(2) for k in range(SHADE_LEVELS)}

    picture = make_default_picture()
    FRAMES_DIR.mkdir(parents=True, exist_ok=True)
    platform_data = {}

    for name, cfg in PLATFORMS.items():
        gw, gh = cfg["gif_size"]
        ox, oy = cfg["offset"]
        sw, sh = cfg["screen"]
        sx, sy = gw / 400, gh / 300
        small = [cv2.resize(c, (gw, gh), interpolation=cv2.INTER_AREA) for c in clean]
        cov = [[cv2.resize(vis[i, s], (gw, gh), interpolation=cv2.INTER_AREA) for s in range(2)]
               for i in range(n)]
        sh_small = [cv2.resize(shade[i] * any_face[i], (gw, gh), interpolation=cv2.INTER_AREA)
                    / np.maximum(cv2.resize(any_face[i].astype(np.float32), (gw, gh),
                                            interpolation=cv2.INTER_AREA), 1e-3)
                    for i in range(n)]

        # Bounding box of the locket over all frames, in screen pixels, clipped to screen.
        ink = np.zeros((gh, gw), bool)
        for c in small:
            ink |= c.min(2) < 245
        ys, xs = np.nonzero(ink)
        bx0, by0 = max(xs.min() + ox, 0), max(ys.min() + oy, 0)
        bx1, by1 = min(xs.max() + ox + 1, sw), min(ys.max() + oy + 1, sh)
        bw, bh = bx1 - bx0, by1 - by0

        frames_lv = []
        mats = []
        footprints = []
        for i in range(n):
            c = small[i][by0 - oy:by1 - oy, bx0 - ox:bx1 - ox].copy()
            c[c.min(2) > 245] = 255
            lv = dither(c, bx0, by0)
            for s in range(2):
                m = cov[i][s][by0 - oy:by1 - oy, bx0 - ox:bx1 - ox] >= 0.5
                shv = sh_small[i][by0 - oy:by1 - oy, bx0 - ox:bx1 - ox]
                k = np.clip(np.rint((shv - lo) / (1 - lo) * SHADE_LEVELS - 0.5), 0,
                            SHADE_LEVELS - 1).astype(int)
                for kk in range(SHADE_LEVELS):
                    lv[m & (k == kk)] = markers[s][kk]
            frames_lv.append(lv)
            save_palettised(lv, FRAMES_DIR / f"f{i:02d}~{name}.png")

            # Frame-bitmap pixel (x, y) -> texture unit coords, Q-format, per slot.
            # GIF px center gx relates to bitmap x by gx = (x + bx0 - ox + 0.5) / sx - 0.5.
            B = np.array([[1 / sx, 0, (bx0 - ox + 0.5) / sx - 0.5],
                          [0, 1 / sy, (by0 - oy + 0.5) / sy - 0.5], [0, 0, 1]])
            row = []
            feet = []
            for s in range(2):
                if i not in G[s] or not (cov[i][s] >= 0.5).any():
                    row.append(None)
                    feet.append(0)
                    continue
                M = np.linalg.inv(G[s][i]) @ B
                yy, xx = np.nonzero(cov[i][s][by0 - oy:by1 - oy, bx0 - ox:bx1 - ox] >= 0.5)
                wmid = M[2] @ [xx.mean(), yy.mean(), 1]
                M = M / wmid
                row.append(np.rint(M * (1 << Q)).astype(np.int64))
                feet.append(footprint(M, xx, yy))
            mats.append(row)
            footprints.append(feet)

        sizes = [(FRAMES_DIR / f"f{i:02d}~{name}.png").stat().st_size for i in range(n)]
        print(f"{name}: frame rect {bx0},{by0} {bw}x{bh}, PNGs {sum(sizes) / 1024:.1f} KB "
              f"(max {max(sizes)} B)")
        platform_data[name] = dict(rect=(bx0, by0, bw, bh), mats=mats, frames=frames_lv,
                                   footprints=footprints)

        if preview:
            simulate(name, cfg, platform_data[name], markers, marker_lookup, levels, lo,
                     safe, picture, durations)

    write_header(platform_data, durations, markers, levels, lo, safe)


def footprint(M, xs, ys):
    """How much of the texture (unit = whole texture) one screen pixel covers on the face:
    the larger singular value of the mapping's Jacobian, 75th percentile over the face."""
    p = np.stack([xs, ys, np.ones_like(xs)], 0).astype(np.float64)
    U, V, W = M @ p
    J = np.empty((len(xs), 2, 2))
    J[:, 0, 0] = (M[0, 0] * W - U * M[2, 0]) / W ** 2
    J[:, 0, 1] = (M[0, 1] * W - U * M[2, 1]) / W ** 2
    J[:, 1, 0] = (M[1, 0] * W - V * M[2, 0]) / W ** 2
    J[:, 1, 1] = (M[1, 1] * W - V * M[2, 1]) / W ** 2
    sv = np.linalg.svd(J, compute_uv=False)[:, 0]
    return float(np.percentile(sv, 75))


def write_header(platform_data, durations, markers, levels, lo, safe):
    n = len(durations)
    out = ["// Generated by tools/make_locket.py, do not edit.", "#pragma once", "",
           "#include <pebble.h>", "",
           f"#define LOCKET_FRAME_COUNT {n}",
           f"#define LOCKET_SHADE_LEVELS {SHADE_LEVELS}",
           f"#define LOCKET_Q {Q}", "",
           "// GIF frame durations (ms).",
           "static const uint16_t LOCKET_FRAME_MS[LOCKET_FRAME_COUNT] = {",
           "  " + ", ".join(str(d) for d in durations) + ",", "};", "",
           "// Marker color (GColor8 argb) for each face slot and shade level.",
           "static const uint8_t LOCKET_MARKERS[2][LOCKET_SHADE_LEVELS] = {"]
    for s in range(2):
        out.append("  { " + ", ".join(f"0x{argb8(c):02X}" for c in markers[s]) + " },")
    out += ["};", "",
            "// Brightness of each shade level, out of 256.",
            "static const uint16_t LOCKET_SHADE[LOCKET_SHADE_LEVELS] = {",
            "  " + ", ".join(str(int(round(v * 256))) for v in levels) + ",", "};", "",
            "// Where the message can go inside each face: x, y, w, h out of 256 of the texture.",
            "static const uint8_t LOCKET_TEXT_RECT[2][4] = {"]
    for s in range(2):
        out.append("  { " + ", ".join(str(min(255, int(round(v * 256)))) for v in safe[s]) + " },")
    out += ["};", "",
            "// Per frame and slot: frame-bitmap pixel (x, y, 1) -> texture (u, v, w), where",
            "// u / w and v / w are in [0, 1) across the texture. Fixed point, LOCKET_Q bits.",
            "typedef struct {",
            "  bool active;",
            "  int32_t m[9];",
            "} LocketSlotXform;", ""]
    resource_ids = ", ".join(f"RESOURCE_ID_FRAME_{i:02d}" for i in range(n))
    for k, (name, data) in enumerate(platform_data.items()):
        out.append(("#if" if k == 0 else "#elif") + f" defined(PBL_PLATFORM_{name.upper()})")
        x, y, w, h = data["rect"]
        out.append(f"#define LOCKET_FRAME_RECT GRect({x}, {y}, {w}, {h})")
        out.append("static const LocketSlotXform LOCKET_XFORM[LOCKET_FRAME_COUNT][2] = {")
        for row in data["mats"]:
            cells = []
            for m in row:
                if m is None:
                    cells.append("{ false, { 0 } }")
                else:
                    cells.append("{ true, { " + ", ".join(str(int(v)) for v in m.reshape(-1)) + " } }")
            out.append("  { " + ", ".join(cells) + " },")
        out.append("};")
        out.append("// Per frame and slot: texture (unit = whole texture) per screen px, Q16.")
        out.append("static const int32_t LOCKET_FOOTPRINT[LOCKET_FRAME_COUNT][2] = {")
        for feet in data["footprints"]:
            out.append("  { " + ", ".join(str(int(round(f * 65536))) for f in feet) + " },")
        out.append("};")
    out += ["#else", '#error "Unsupported platform"', "#endif", "",
            "static const uint32_t LOCKET_FRAME_RESOURCES[LOCKET_FRAME_COUNT] = {",
            "  " + resource_ids + ",", "};", ""]
    HEADER.write_text("\n".join(out))


def simulate(name, cfg, data, markers, marker_lookup, levels, lo, safe, picture, durations):
    """Mimic main.c's compositor to preview the frames with the default contents."""
    PREVIEW_DIR.mkdir(exist_ok=True)
    sw, sh = cfg["screen"]
    x0, y0, w, h = data["rect"]
    text_mips = render_text_texture("pebble my beloved", safe[1])
    out = []
    raw = []  # unscaled RGB screens, for tools/make_store_assets.py
    for i, lv in enumerate(data["frames"]):
        screen = np.full((sh, sw, 3), 3, np.uint8)
        comp = lv.copy()
        for y in range(h):
            for x in range(w):
                key = tuple(int(v) for v in lv[y, x])
                if key not in marker_lookup:
                    continue
                s, k = marker_lookup[key]
                m = data["mats"][i][s]
                if m is None:
                    continue
                U = m[0, 0] * x + m[0, 1] * y + m[0, 2]
                V = m[1, 0] * x + m[1, 1] * y + m[1, 2]
                W_ = m[2, 0] * x + m[2, 1] * y + m[2, 2]
                if W_ <= 0:
                    continue
                uu = min(max(U / W_, 0), 0.99999)
                vv = min(max(V / W_, 0), 0.99999)
                b = int(round(levels[k] * 256))
                t = BAYER4[(y + y0) % 4, (x + x0) % 4] * 16 + 8
                if s == 0:
                    c = picture[int(vv * PICTURE_SIZE), int(uu * PICTURE_SIZE)].astype(int)
                    val = c * b
                    comp[y, x] = (val >> 8) + ((val & 255) > t)
                else:
                    texels = data["footprints"][i][s] * TEXT_SIZE
                    level = 0 if texels < 1.5 else (1 if texels < 3 else 2)
                    ink = sample_bilinear(text_mips[level], uu, vv)
                    g = int(b * (255 - ink)) >> 8
                    v3 = g * 3
                    c = v3 // 255
                    c += (v3 - c * 255) * 256 > t * 255
                    comp[y, x] = min(c, 3)
        screen[y0:y0 + h, x0:x0 + w] = comp
        raw.append(screen * 85)
        img = Image.fromarray(screen * 85)
        if cfg["round"]:
            mask = Image.new("L", (sw, sh), 0)
            ImageDraw.Draw(mask).ellipse([0, 0, sw - 1, sh - 1], fill=255)
            bg = Image.new("RGB", (sw, sh), (40, 40, 40))
            bg.paste(img, (0, 0), mask)
            img = bg
        out.append(img.resize((sw * 2, sh * 2), Image.NEAREST))
    out[0].save(PREVIEW_DIR / f"locket-{name}.gif", save_all=True, append_images=out[1:],
                duration=durations, loop=0)
    cols = 6
    sheet = Image.new("RGB", (cols * sw, ((len(out) + cols - 1) // cols) * sh), "black")
    for i, im in enumerate(out):
        sheet.paste(im.resize((sw, sh), Image.NEAREST), ((i % cols) * sw, (i // cols) * sh))
    sheet.save(PREVIEW_DIR / f"sheet-{name}.png")
    out[-1].save(PREVIEW_DIR / f"open-{name}.png")
    out[0].save(PREVIEW_DIR / f"closed-{name}.png")
    np.savez_compressed(PREVIEW_DIR / f"frames-{name}.npz", screens=np.stack(raw),
                        rect=np.array(data["rect"]), durations=np.array(durations))


if __name__ == "__main__":
    main()
