#include "text_engine.h"
#include "font_data.h"

// makesweet's text image: lines of 72pt Arial, each centered, on a canvas 20px (at 96px per
// em) larger than the text on every side; that image is then fitted into the locket.
#define PAD_EM (20.0f / 96.0f)
#define LINE_EM 1.15f  // Arial's normal line height

#define MAX_CHARS 96
#define MAX_LINES 4
// Auto-wrapping (when the message has no line breaks) only adds a line if the text gets
// at least this much bigger, so short messages stay on one line like on makesweet.
#define WRAP_GAIN 1.15f

static const FontGlyph *find_glyph(uint16_t code) {
  int lo = 0;
  int hi = FONT_GLYPH_COUNT - 1;
  while (lo <= hi) {
    int mid = (lo + hi) / 2;
    if (FONT_GLYPHS[mid].code == code) {
      return &FONT_GLYPHS[mid];
    }
    if (FONT_GLYPHS[mid].code < code) {
      lo = mid + 1;
    } else {
      hi = mid - 1;
    }
  }
  return NULL;
}

// UTF-8 to code points; invalid bytes become '?'.
static int decode_utf8(const char *s, uint16_t *out, int max) {
  int n = 0;
  const uint8_t *p = (const uint8_t *)s;
  while (*p && n < max) {
    uint32_t c = *p++;
    int extra = 0;
    if (c >= 0xF0) {
      c &= 0x07;
      extra = 3;
    } else if (c >= 0xE0) {
      c &= 0x0F;
      extra = 2;
    } else if (c >= 0xC0) {
      c &= 0x1F;
      extra = 1;
    } else if (c >= 0x80) {
      c = '?';
    }
    for (; extra > 0 && (*p & 0xC0) == 0x80; extra--) {
      c = (c << 6) | (*p++ & 0x3F);
    }
    out[n++] = (extra > 0 || c > 0xFFFF) ? '?' : (uint16_t)c;
  }
  return n;
}

typedef struct {
  int start;
  int end;  // exclusive
} Line;

static int advance_16(uint16_t code) {
  const FontGlyph *g = find_glyph(code);
  if (!g) {
    g = find_glyph('?');
  }
  return g ? g->advance_16 : 0;
}

// Width of text[start, end) without leading/trailing spaces, in 1/16 atlas px.
static int line_width(const uint16_t *text, int start, int end) {
  while (start < end && text[start] == ' ') {
    start++;
  }
  while (end > start && text[end - 1] == ' ') {
    end--;
  }
  int w = 0;
  for (int i = start; i < end; i++) {
    w += advance_16(text[i]);
  }
  return w;
}

// Em size (texels) at which `count` lines of max width `width_16` fit in w x h texels.
static float fit_em(int width_16, int count, float w, float h) {
  float width_em = width_16 / 16.0f / FONT_ATLAS_EM + 2 * PAD_EM;
  float height_em = count * LINE_EM + 2 * PAD_EM;
  float em_w = w / width_em;
  float em_h = h / height_em;
  return em_w < em_h ? em_w : em_h;
}

// Splits the words of text[0, n) into `count` lines with the narrowest widest line.
// Returns that width, or -1 if there aren't enough words.
static int best_split(const uint16_t *text, int n, int count, Line *lines) {
  int gaps[MAX_CHARS];
  int gap_count = 0;
  for (int i = 1; i < n; i++) {
    if (text[i] == ' ' && text[i - 1] != ' ') {
      gaps[gap_count++] = i;
    }
  }
  if (gap_count < count - 1) {
    return -1;
  }
  int best = -1;
  // Up to 3 breaks (MAX_LINES 4): plain nested loops over gap choices.
  int b[MAX_LINES - 1] = { 0 };
  int k = count - 1;
  for (int i = 0; i < k; i++) {
    b[i] = i;
  }
  while (true) {
    int widest = 0;
    int start = 0;
    for (int i = 0; i <= k; i++) {
      int end = i < k ? gaps[b[i]] : n;
      int w = line_width(text, start, end);
      widest = w > widest ? w : widest;
      start = end;
    }
    if (best < 0 || widest < best) {
      best = widest;
      start = 0;
      for (int i = 0; i <= k; i++) {
        int end = i < k ? gaps[b[i]] : n;
        lines[i] = (Line) { start, end };
        start = end;
      }
    }
    // Next combination of k gaps out of gap_count.
    int i = k - 1;
    while (i >= 0 && b[i] == gap_count - k + i) {
      i--;
    }
    if (i < 0) {
      break;
    }
    b[i]++;
    for (int j = i + 1; j < k; j++) {
      b[j] = b[j - 1] + 1;
    }
  }
  return best;
}

// Breaks into lines: at '\n' if the message has any, otherwise wherever gives the
// biggest text (preferring fewer lines). Returns the number of lines.
static int layout(const uint16_t *text, int n, float w, float h, Line *lines, int *widest) {
  bool explicit_breaks = false;
  for (int i = 0; i < n; i++) {
    explicit_breaks |= text[i] == '\n';
  }
  if (explicit_breaks) {
    int count = 0;
    int start = 0;
    *widest = 0;
    for (int i = 0; i <= n && count < MAX_LINES; i++) {
      if (i == n || text[i] == '\n') {
        lines[count++] = (Line) { start, i };
        int lw = line_width(text, start, i);
        *widest = lw > *widest ? lw : *widest;
        start = i + 1;
      }
    }
    return count;
  }

  int count = 1;
  lines[0] = (Line) { 0, n };
  *widest = line_width(text, 0, n);
  float em = fit_em(*widest, 1, w, h);
  for (int c = 2; c <= 3; c++) {
    Line candidate[MAX_LINES];
    int cw = best_split(text, n, c, candidate);
    if (cw < 0) {
      break;
    }
    float cem = fit_em(cw, c, w, h);
    if (cem > em * WRAP_GAIN) {
      em = cem;
      count = c;
      *widest = cw;
      memcpy(lines, candidate, sizeof(Line) * c);
    }
  }
  return count;
}

static uint8_t s_glyph_bits[FONT_MAX_GLYPH_BYTES];

// 4-bit coverage at integer atlas pixel (x, y) of the loaded glyph, 0 outside.
static inline int glyph_px(const FontGlyph *g, int x, int y) {
  if (x < 0 || y < 0 || x >= g->w || y >= g->h) {
    return 0;
  }
  uint8_t byte = s_glyph_bits[y * ((g->w + 1) / 2) + x / 2];
  return (x & 1) ? (byte & 0x0F) : (byte >> 4);
}

// Bilinear coverage (0..15 * 256) at atlas position (ax, ay) in 1/256 px, pixel centers at .5.
static int glyph_sample(const FontGlyph *g, int32_t ax, int32_t ay) {
  ax -= 128;
  ay -= 128;
  int x = ax >> 8;
  int y = ay >> 8;
  int fx = ax & 255;
  int fy = ay & 255;
  int top = glyph_px(g, x, y) * (256 - fx) + glyph_px(g, x + 1, y) * fx;
  int bottom = glyph_px(g, x, y + 1) * (256 - fx) + glyph_px(g, x + 1, y + 1) * fx;
  return (top * (256 - fy) + bottom * fy) >> 8;
}

// Draws one glyph with its pen position at (pen_x, baseline) texels, scaled by `scale`.
static void draw_glyph(uint8_t *tex, const FontGlyph *g, float pen_x, float baseline,
                       float scale) {
  if (g->w == 0 || g->h == 0) {
    return;
  }
  resource_load_byte_range(resource_get_handle(RESOURCE_ID_FONT_ATLAS), g->offset,
                           s_glyph_bits, ((g->w + 1) / 2) * g->h);

  float x0 = pen_x + g->xoff * scale;
  float y0 = baseline + g->yoff * scale;
  int tx0 = (int)x0;
  int ty0 = (int)y0;
  int tx1 = (int)(x0 + g->w * scale) + 1;
  int ty1 = (int)(y0 + g->h * scale) + 1;
  // Average n x n samples per texel, so shrinking acts as a box filter.
  int n = (int)(1.0f / scale) + 1;
  n = n < 1 ? 1 : (n > 4 ? 4 : n);
  // Atlas px per texel and the atlas position of texel (0, 0), in 1/256 px.
  int32_t step = (int32_t)(256.0f / scale);
  int32_t base_x = (int32_t)(-x0 * 256.0f / scale);
  int32_t base_y = (int32_t)(-y0 * 256.0f / scale);

  for (int ty = ty0; ty <= ty1; ty++) {
    if (ty < 0 || ty >= TEXT_TEX_SIZE) {
      continue;
    }
    for (int tx = tx0; tx <= tx1; tx++) {
      if (tx < 0 || tx >= TEXT_TEX_SIZE) {
        continue;
      }
      int sum = 0;
      for (int sy = 0; sy < n; sy++) {
        int32_t ay = base_y + ty * step + (step * (2 * sy + 1)) / (2 * n);
        for (int sx = 0; sx < n; sx++) {
          int32_t ax = base_x + tx * step + (step * (2 * sx + 1)) / (2 * n);
          sum += glyph_sample(g, ax, ay);
        }
      }
      // sum / (n * n) is 0..15*256; scale to 0..255 and add (glyphs may touch).
      int c = sum * 255 / (n * n * 15 * 256);
      int v = tex[ty * TEXT_TEX_SIZE + tx] + c;
      tex[ty * TEXT_TEX_SIZE + tx] = v > 255 ? 255 : v;
    }
  }
}

static void downsample(const uint8_t *src, int size, uint8_t *dst) {
  int half = size / 2;
  for (int y = 0; y < half; y++) {
    for (int x = 0; x < half; x++) {
      const uint8_t *s = src + 2 * y * size + 2 * x;
      dst[y * half + x] = (s[0] + s[1] + s[size] + s[size + 1] + 2) / 4;
    }
  }
}

void text_engine_render(TextTexture *tex, const char *message, const uint8_t fit[4]) {
  memset(tex->level0, 0, sizeof(tex->level0));

  uint16_t text[MAX_CHARS];
  int n = decode_utf8(message, text, MAX_CHARS);
  float fx = fit[0] * TEXT_TEX_SIZE / 256.0f;
  float fy = fit[1] * TEXT_TEX_SIZE / 256.0f;
  float fw = fit[2] * TEXT_TEX_SIZE / 256.0f;
  float fh = fit[3] * TEXT_TEX_SIZE / 256.0f;

  Line lines[MAX_LINES];
  int widest;
  int count = n > 0 ? layout(text, n, fw, fh, lines, &widest) : 0;
  if (count > 0 && widest > 0) {
    float em = fit_em(widest, count, fw, fh);
    float scale = em / FONT_ATLAS_EM;
    // Vertically: the block of lines (LINE_EM each, text centered in its line) is centered.
    float block = count * LINE_EM * em;
    float ascent = FONT_ASCENT_16 / 16.0f * scale;
    float descent = FONT_DESCENT_16 / 16.0f * scale;
    float line_h = LINE_EM * em;
    float top = fy + (fh - block) / 2;
    for (int l = 0; l < count; l++) {
      int start = lines[l].start;
      int end = lines[l].end;
      while (start < end && (text[start] == ' ' || text[start] == '\n')) {
        start++;
      }
      while (end > start && (text[end - 1] == ' ' || text[end - 1] == '\n')) {
        end--;
      }
      float width = line_width(text, start, end) / 16.0f * scale;
      float pen = fx + (fw - width) / 2;
      float baseline = top + l * line_h + (line_h - ascent - descent) / 2 + ascent;
      for (int i = start; i < end; i++) {
        const FontGlyph *g = find_glyph(text[i]);
        if (!g) {
          g = find_glyph('?');
        }
        if (!g) {
          continue;
        }
        draw_glyph(tex->level0, g, pen, baseline, scale);
        pen += g->advance_16 / 16.0f * scale;
      }
    }
  }

  downsample(tex->level0, TEXT_TEX_SIZE, tex->level1);
  downsample(tex->level1, TEXT_TEX_SIZE / 2, tex->level2);
}
