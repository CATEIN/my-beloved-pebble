#pragma once

#include <pebble.h>

// Renders the locket message the way makesweet does (Arial-metric font, black, centered,
// with a margin) into a coverage texture that main.c maps onto the locket's face.

#define TEXT_TEX_SIZE 128
#define TEXT_MIP_LEVELS 3

typedef struct {
  // Coverage (0 = face, 255 = ink), TEXT_TEX_SIZE >> level square, level 0 first.
  uint8_t level0[TEXT_TEX_SIZE * TEXT_TEX_SIZE];
  uint8_t level1[(TEXT_TEX_SIZE / 2) * (TEXT_TEX_SIZE / 2)];
  uint8_t level2[(TEXT_TEX_SIZE / 4) * (TEXT_TEX_SIZE / 4)];
} TextTexture;

// Lays out `message` (UTF-8, '\n' for line breaks) to fit inside `fit` (x, y, w, h out of
// 256 of the texture) and rasterizes it into `tex`.
void text_engine_render(TextTexture *tex, const char *message, const uint8_t fit[4]);

// Texels per side of a mip level.
static inline int text_level_size(int level) {
  return TEXT_TEX_SIZE >> level;
}

static inline const uint8_t *text_level_data(const TextTexture *tex, int level) {
  return level == 0 ? tex->level0 : level == 1 ? tex->level1 : tex->level2;
}
