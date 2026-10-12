#include <pebble.h>
#include "locket_data.h"
#include "text_engine.h"

// The heart locket from the makesweet "my beloved" GIF. Flick the wrist and it opens to show
// the picture and message set on the phone, stays open for a few seconds, then closes again.
//
// The frames (see tools/make_locket.py) are the GIF's frames, except that the pixels of the two
// inner faces are "marker" colors that say which face it is and how brightly it is lit. Those
// pixels are swapped for the picture or the message, through the frame's perspective transform.
// The message is rasterized by text_engine.c into a coverage texture and drawn onto the face
// like the picture: in perspective, filtered, and lit by the face's shading.

// Picture: 16-color palette (GColor8) then PICTURE_SIZE^2 4-bit indexes, high nibble first.
// Same format as resources/default_picture.bin and the config page's output.
#define PICTURE_SIZE 80
#define PICTURE_BYTES (16 + PICTURE_SIZE * PICTURE_SIZE / 2)
#define MESSAGE_MAX 96  // bytes of UTF-8
#define DEFAULT_MESSAGE "pebble my beloved"

#define SLOT_COVER 0  // the face inside the cover, on the left once open
#define SLOT_BACK 1   // the face of the back half, on the right

#define WEATHER_INTERVAL_MIN 30
#define DEFAULT_OPEN_SECONDS 3
#define CLOSING_FRAME_MS 70
#define TEMP_UNKNOWN INT32_MIN

#define PERSIST_KEY_TEMPERATURE 1
#define PERSIST_KEY_USE_CELSIUS 2
#define PERSIST_KEY_MESSAGE 3
#define PERSIST_KEY_SWAP_SIDES 4
#define PERSIST_KEY_OPEN_SECONDS 5
#define PERSIST_KEY_PICTURE_STATE 6
#define PERSIST_KEY_PICTURE_BASE 100  // PICTURE_BYTES split over PERSIST_DATA_MAX_LENGTH chunks

typedef enum {
  PICTURE_DEFAULT = 0,
  PICTURE_CUSTOM = 1,
} PictureState;

typedef enum {
  LOCKET_CLOSED,
  LOCKET_OPENING,
  LOCKET_OPEN,
  LOCKET_CLOSING,
} LocketState;

#if defined(PBL_ROUND)
#define TIME_FRAME GRect(0, 6, 260, 32)
#define DATE_FRAME GRect(36, 194, 90, 24)
#define TEMP_FRAME GRect(134, 194, 90, 24)
#else
#define TIME_FRAME GRect(0, 4, 200, 32)
#define DATE_FRAME GRect(6, 200, 90, 24)
#define TEMP_FRAME GRect(104, 200, 90, 24)
#endif

static Window *s_window;
static Layer *s_locket_layer;
static TextLayer *s_time_layer;
static TextLayer *s_date_layer;
static TextLayer *s_temp_layer;
static char s_time_text[8];
static char s_date_text[8];
static char s_temp_text[16];

static GBitmap *s_frame_bitmap;
static int s_frame = 0;
static LocketState s_state = LOCKET_CLOSED;
static AppTimer *s_timer;

static uint8_t s_picture[PICTURE_SIZE * PICTURE_SIZE];  // GColor8 per pixel
static TextTexture s_text;
static uint8_t *s_picture_rx;  // picture being received from the phone

// Marker color (low 6 bits) -> slot << 4 | shade level, or 0xFF for ordinary pixels.
static uint8_t s_marker_lut[64];

static char s_message[MESSAGE_MAX + 1] = DEFAULT_MESSAGE;
static bool s_swap_sides;
static int s_open_seconds = DEFAULT_OPEN_SECONDS;
static bool s_use_celsius;
static int32_t s_temperature = TEMP_UNKNOWN;

static const uint8_t BAYER4[4][4] = {
  { 0, 8, 2, 10 }, { 12, 4, 14, 6 }, { 3, 11, 1, 9 }, { 15, 7, 13, 5 },
};

// ---------------------------------------------------------------------------------------------
// Picture

static void picture_decode(const uint8_t *data) {
  const uint8_t *palette = data;
  const uint8_t *pixels = data + 16;
  for (int i = 0; i < PICTURE_SIZE * PICTURE_SIZE; i++) {
    uint8_t byte = pixels[i / 2];
    uint8_t index = (i & 1) ? (byte & 0x0F) : (byte >> 4);
    s_picture[i] = palette[index] | 0xC0;
  }
}

static void picture_load_default(void) {
  uint8_t *data = malloc(PICTURE_BYTES);
  if (!data) {
    return;
  }
  ResHandle handle = resource_get_handle(RESOURCE_ID_DEFAULT_PICTURE);
  resource_load(handle, data, PICTURE_BYTES);
  picture_decode(data);
  free(data);
}

static bool picture_load_persisted(void) {
  uint8_t *data = malloc(PICTURE_BYTES);
  if (!data) {
    return false;
  }
  bool ok = true;
  for (int offset = 0, key = PERSIST_KEY_PICTURE_BASE; offset < PICTURE_BYTES;
       offset += PERSIST_DATA_MAX_LENGTH, key++) {
    int len = PICTURE_BYTES - offset;
    if (len > PERSIST_DATA_MAX_LENGTH) {
      len = PERSIST_DATA_MAX_LENGTH;
    }
    if (persist_read_data(key, data + offset, len) != len) {
      ok = false;
      break;
    }
  }
  if (ok) {
    picture_decode(data);
  }
  free(data);
  return ok;
}

static void picture_persist(const uint8_t *data) {
  for (int offset = 0, key = PERSIST_KEY_PICTURE_BASE; offset < PICTURE_BYTES;
       offset += PERSIST_DATA_MAX_LENGTH, key++) {
    int len = PICTURE_BYTES - offset;
    if (len > PERSIST_DATA_MAX_LENGTH) {
      len = PERSIST_DATA_MAX_LENGTH;
    }
    if (persist_write_data(key, data + offset, len) < 0) {
      APP_LOG(APP_LOG_LEVEL_WARNING, "Picture didn't fit in storage, will re-request it");
      return;
    }
  }
}

static void picture_forget(void) {
  for (int offset = 0, key = PERSIST_KEY_PICTURE_BASE; offset < PICTURE_BYTES;
       offset += PERSIST_DATA_MAX_LENGTH, key++) {
    persist_delete(key);
  }
}

// ---------------------------------------------------------------------------------------------
// Drawing

static int text_slot(void) {
  return s_swap_sides ? SLOT_COVER : SLOT_BACK;
}

static void render_text(void) {
  text_engine_render(&s_text, s_message, LOCKET_TEXT_RECT[text_slot()]);
}

// Darkens a texture color by a shade level, dithered so the levels blend smoothly.
static inline uint8_t shade_color(uint8_t argb, int level, int threshold) {
  int b = LOCKET_SHADE[level];
  uint8_t out = 0xC0;
  for (int shift = 4; shift >= 0; shift -= 2) {
    int v = ((argb >> shift) & 3) * b;
    int c = (v >> 8) + ((v & 255) > threshold ? 1 : 0);
    out |= (c > 3 ? 3 : c) << shift;
  }
  return out;
}

// Unit texture coordinate U / W as Q15 (32768 = 1.0), clamped to [0, 1).
static inline int32_t unit_q15(int32_t u, int32_t w) {
  if (u <= 0) {
    return 0;
  }
  if (u >= w) {
    return 32767;
  }
  // Shifted so (u << 15) can't overflow: on the face w is within a few times 1 << LOCKET_Q.
  return ((u >> 7) << 15) / (w >> 7);
}

// Bilinear ink coverage (0..255) of the message texture at unit coords (Q15).
static inline int sample_text(const uint8_t *data, int size, int32_t uq, int32_t vq) {
  // Texel space in 1/256 texel, with texel centers at .5.
  int32_t x = ((uq * size) >> 7) - 128;
  int32_t y = ((vq * size) >> 7) - 128;
  int x0 = x >> 8;
  int y0 = y >> 8;
  int fx = x & 255;
  int fy = y & 255;
  int x1 = x0 + 1;
  int y1 = y0 + 1;
  x0 = x0 < 0 ? 0 : x0;
  y0 = y0 < 0 ? 0 : y0;
  x1 = x1 >= size ? size - 1 : x1;
  y1 = y1 >= size ? size - 1 : y1;
  const uint8_t *r0 = data + y0 * size;
  const uint8_t *r1 = data + y1 * size;
  int top = r0[x0] * (256 - fx) + r0[x1] * fx;
  int bottom = r1[x0] * (256 - fx) + r1[x1] * fx;
  return (top * (256 - fy) + bottom * fy) >> 16;
}

// The face's white, shaded to `level`, with `ink` (0..255) of black text on it; dithered
// to the Pebble's four greys.
static inline uint8_t ink_on_face(int ink, int level, int threshold) {
  int g = (LOCKET_SHADE[level] * (255 - ink)) >> 8;  // 0..255
  int v = g * 3;                                      // 0..765, 255 per grey step
  int c = v / 255;
  if ((v - c * 255) * 256 > threshold * 255) {
    c++;
  }
  c = c > 3 ? 3 : c;
  return 0xC0 | (c << 4) | (c << 2) | c;
}

// Mip level whose texels are about one screen pixel at this frame's scale.
static int text_mip_level(int32_t footprint_q16) {
  int32_t texels_q16 = footprint_q16 * TEXT_TEX_SIZE;  // texels per px, Q16
  if (texels_q16 < (3 << 15)) {                        // < 1.5
    return 0;
  }
  if (texels_q16 < (3 << 16)) {  // < 3
    return 1;
  }
  return 2;
}

static void locket_update_proc(Layer *layer, GContext *ctx) {
  if (!s_frame_bitmap) {
    return;
  }

  GRect rect = LOCKET_FRAME_RECT;
  const uint8_t *frame = gbitmap_get_data(s_frame_bitmap);
  int stride = gbitmap_get_bytes_per_row(s_frame_bitmap);
  const LocketSlotXform *xforms = LOCKET_XFORM[s_frame];

  int picture_slot = s_swap_sides ? SLOT_BACK : SLOT_COVER;
  int level = text_mip_level(LOCKET_FOOTPRINT[s_frame][1 - picture_slot]);
  const uint8_t *text = text_level_data(&s_text, level);
  int text_size = text_level_size(level);

  GBitmap *fb = graphics_capture_frame_buffer(ctx);
  if (!fb) {
    return;
  }
  for (int fy = 0; fy < rect.size.h; fy++) {
    int y = rect.origin.y + fy;
    GBitmapDataRowInfo row = gbitmap_get_data_row_info(fb, y);
    int x_start = row.min_x > rect.origin.x ? row.min_x : rect.origin.x;
    int x_end = row.max_x < rect.origin.x + rect.size.w - 1 ? row.max_x
                                                             : rect.origin.x + rect.size.w - 1;
    const uint8_t *src = frame + fy * stride;

    // Texture coordinates (u, v, w) at x = 0 of this row, then stepped along it.
    int32_t U[2], V[2], W[2];
    for (int s = 0; s < 2; s++) {
      const int32_t *m = xforms[s].m;
      U[s] = m[1] * fy + m[2];
      V[s] = m[4] * fy + m[5];
      W[s] = m[7] * fy + m[8];
    }

    for (int x = x_start; x <= x_end; x++) {
      int fx = x - rect.origin.x;
      uint8_t c = src[fx];
      uint8_t marker = s_marker_lut[c & 0x3F];
      if (marker == 0xFF) {
        row.data[x] = c | 0xC0;
        continue;
      }
      int s = marker >> 4;
      if (!xforms[s].active) {
        row.data[x] = GColorWhiteARGB8;
        continue;
      }
      const int32_t *m = xforms[s].m;
      int32_t w = W[s] + m[6] * fx;
      if (w < (1 << 10)) {
        row.data[x] = GColorWhiteARGB8;
        continue;
      }
      int32_t uq = unit_q15(U[s] + m[0] * fx, w);
      int32_t vq = unit_q15(V[s] + m[3] * fx, w);
      int threshold = BAYER4[y & 3][x & 3] * 16 + 8;
      if (s == picture_slot) {
        int tu = (uq * PICTURE_SIZE) >> 15;
        int tv = (vq * PICTURE_SIZE) >> 15;
        row.data[x] = shade_color(s_picture[tv * PICTURE_SIZE + tu], marker & 0x0F, threshold);
      } else {
        row.data[x] = ink_on_face(sample_text(text, text_size, uq, vq), marker & 0x0F, threshold);
      }
    }
  }
  graphics_release_frame_buffer(ctx, fb);
}

// ---------------------------------------------------------------------------------------------
// Animation

static void show_frame(int frame) {
  // Free the current frame first: decoding needs the room on gabbro, whose frames are big.
  if (s_frame_bitmap) {
    gbitmap_destroy(s_frame_bitmap);
    s_frame_bitmap = NULL;
  }
  // The animation moves on even if a frame fails, so it can't get stuck.
  s_frame = frame;
  s_frame_bitmap = gbitmap_create_with_resource(LOCKET_FRAME_RESOURCES[frame]);
  if (!s_frame_bitmap) {
    APP_LOG(APP_LOG_LEVEL_ERROR, "Couldn't load frame %d (%d bytes free)", frame,
            (int)heap_bytes_free());
  } else if (gbitmap_get_format(s_frame_bitmap) != GBitmapFormat8Bit) {
    APP_LOG(APP_LOG_LEVEL_ERROR, "Frame %d has format %d", frame,
            gbitmap_get_format(s_frame_bitmap));
  }
  layer_mark_dirty(s_locket_layer);
}

static void step(void *context);

static void schedule_step(uint32_t ms) {
  s_timer = app_timer_register(ms, step, NULL);
}

static void step(void *context) {
  s_timer = NULL;
  switch (s_state) {
    case LOCKET_OPENING:
      if (s_frame < LOCKET_FRAME_COUNT - 1) {
        show_frame(s_frame + 1);
        if (s_frame < LOCKET_FRAME_COUNT - 1) {
          schedule_step(LOCKET_FRAME_MS[s_frame]);
        } else {
          s_state = LOCKET_OPEN;
          schedule_step(s_open_seconds * 1000);
        }
      }
      break;
    case LOCKET_OPEN:
      s_state = LOCKET_CLOSING;
      // fall through
    case LOCKET_CLOSING:
      if (s_frame > 0) {
        show_frame(s_frame - 1);
      }
      if (s_frame > 0) {
        schedule_step(CLOSING_FRAME_MS);
      } else {
        s_state = LOCKET_CLOSED;
      }
      break;
    case LOCKET_CLOSED:
      break;
  }
}

static void open_locket(void) {
  if (s_timer) {
    app_timer_cancel(s_timer);
    s_timer = NULL;
  }
  if (s_state == LOCKET_OPEN) {
    schedule_step(s_open_seconds * 1000);
    return;
  }
  // From closed, or reversing a close that's under way.
  s_state = LOCKET_OPENING;
  schedule_step(LOCKET_FRAME_MS[s_frame]);
}

static void tap_handler(AccelAxisType axis, int32_t direction) {
  open_locket();
}

// ---------------------------------------------------------------------------------------------
// Time, date, weather

static void update_temperature_text(void) {
  if (s_temperature == TEMP_UNKNOWN) {
    s_temp_text[0] = '\0';
  } else {
    snprintf(s_temp_text, sizeof(s_temp_text), "%d\xc2\xb0%s", (int)s_temperature,
             s_use_celsius ? "C" : "F");
  }
  text_layer_set_text(s_temp_layer, s_temp_text);
}

static void update_time(struct tm *t) {
  if (clock_is_24h_style()) {
    strftime(s_time_text, sizeof(s_time_text), "%H:%M", t);
  } else {
    strftime(s_time_text, sizeof(s_time_text), "%I:%M", t);
  }
  // Drop the leading zero of 12-hour times ("9:41", not "09:41").
  const char *time = (!clock_is_24h_style() && s_time_text[0] == '0') ? s_time_text + 1
                                                                       : s_time_text;
  text_layer_set_text(s_time_layer, time);
  strftime(s_date_text, sizeof(s_date_text), "%m/%d", t);
  text_layer_set_text(s_date_layer, s_date_text);
}

static void send_request(uint32_t key) {
  DictionaryIterator *iter;
  if (app_message_outbox_begin(&iter) != APP_MSG_OK) {
    return;
  }
  dict_write_uint8(iter, key, 1);
  app_message_outbox_send();
}

static void tick_handler(struct tm *tick_time, TimeUnits units_changed) {
  update_time(tick_time);
  if (tick_time->tm_min % WEATHER_INTERVAL_MIN == 0) {
    send_request(MESSAGE_KEY_REQUEST_WEATHER);
  }
}

// ---------------------------------------------------------------------------------------------
// Messages from the phone

static void receive_picture_chunk(int32_t offset, Tuple *data) {
  if (offset < 0) {
    // Back to the default picture.
    persist_write_int(PERSIST_KEY_PICTURE_STATE, PICTURE_DEFAULT);
    picture_forget();
    picture_load_default();
    layer_mark_dirty(s_locket_layer);
    return;
  }
  if (!data) {
    return;
  }
  if (offset == 0 && !s_picture_rx) {
    s_picture_rx = malloc(PICTURE_BYTES);
  }
  if (!s_picture_rx || offset + data->length > PICTURE_BYTES) {
    return;
  }
  memcpy(s_picture_rx + offset, data->value->data, data->length);
  if (offset + data->length == PICTURE_BYTES) {
    picture_decode(s_picture_rx);
    persist_write_int(PERSIST_KEY_PICTURE_STATE, PICTURE_CUSTOM);
    picture_persist(s_picture_rx);
    free(s_picture_rx);
    s_picture_rx = NULL;
    layer_mark_dirty(s_locket_layer);
  }
}

static void inbox_received_handler(DictionaryIterator *iter, void *context) {
  Tuple *t;
  if ((t = dict_find(iter, MESSAGE_KEY_TEMPERATURE))) {
    s_temperature = t->value->int32;
    persist_write_int(PERSIST_KEY_TEMPERATURE, s_temperature);
    update_temperature_text();
  }
  if ((t = dict_find(iter, MESSAGE_KEY_USE_CELSIUS))) {
    s_use_celsius = t->value->int32 != 0;
    persist_write_bool(PERSIST_KEY_USE_CELSIUS, s_use_celsius);
    update_temperature_text();
  }
  if ((t = dict_find(iter, MESSAGE_KEY_MESSAGE))) {
    strncpy(s_message, t->value->cstring, MESSAGE_MAX);
    s_message[MESSAGE_MAX] = '\0';
    persist_write_string(PERSIST_KEY_MESSAGE, s_message);
    render_text();
    layer_mark_dirty(s_locket_layer);
  }
  if ((t = dict_find(iter, MESSAGE_KEY_SWAP_SIDES))) {
    s_swap_sides = t->value->int32 != 0;
    persist_write_bool(PERSIST_KEY_SWAP_SIDES, s_swap_sides);
    render_text();  // the two faces have different shapes
    layer_mark_dirty(s_locket_layer);
  }
  if ((t = dict_find(iter, MESSAGE_KEY_OPEN_SECONDS))) {
    s_open_seconds = t->value->int32;
    persist_write_int(PERSIST_KEY_OPEN_SECONDS, s_open_seconds);
  }
  if ((t = dict_find(iter, MESSAGE_KEY_PICTURE_OFFSET))) {
    receive_picture_chunk(t->value->int32, dict_find(iter, MESSAGE_KEY_PICTURE_DATA));
  }
}

// ---------------------------------------------------------------------------------------------
// Setup

static TextLayer *make_text_layer(Layer *root, GRect frame, const char *font_key,
                                  GTextAlignment alignment) {
  TextLayer *layer = text_layer_create(frame);
  text_layer_set_background_color(layer, GColorClear);
  text_layer_set_text_color(layer, GColorBlack);
  text_layer_set_font(layer, fonts_get_system_font(font_key));
  text_layer_set_text_alignment(layer, alignment);
  layer_add_child(root, text_layer_get_layer(layer));
  return layer;
}

static void window_load(Window *window) {
  Layer *root = window_get_root_layer(window);
  GRect bounds = layer_get_bounds(root);

  s_locket_layer = layer_create(bounds);
  layer_set_update_proc(s_locket_layer, locket_update_proc);
  layer_add_child(root, s_locket_layer);

  s_time_layer = make_text_layer(root, TIME_FRAME, FONT_KEY_GOTHIC_24_BOLD, GTextAlignmentCenter);
  s_date_layer = make_text_layer(root, DATE_FRAME, FONT_KEY_GOTHIC_18_BOLD, GTextAlignmentLeft);
  s_temp_layer = make_text_layer(root, TEMP_FRAME, FONT_KEY_GOTHIC_18_BOLD, GTextAlignmentRight);

  show_frame(0);
  time_t now = time(NULL);
  update_time(localtime(&now));
  update_temperature_text();
}

static void window_unload(Window *window) {
  if (s_timer) {
    app_timer_cancel(s_timer);
    s_timer = NULL;
  }
  text_layer_destroy(s_temp_layer);
  text_layer_destroy(s_date_layer);
  text_layer_destroy(s_time_layer);
  layer_destroy(s_locket_layer);
  if (s_frame_bitmap) {
    gbitmap_destroy(s_frame_bitmap);
    s_frame_bitmap = NULL;
  }
}

static void load_settings(void) {
  if (persist_exists(PERSIST_KEY_TEMPERATURE)) {
    s_temperature = persist_read_int(PERSIST_KEY_TEMPERATURE);
  }
  s_use_celsius = persist_read_bool(PERSIST_KEY_USE_CELSIUS);
  s_swap_sides = persist_read_bool(PERSIST_KEY_SWAP_SIDES);
  if (persist_exists(PERSIST_KEY_OPEN_SECONDS)) {
    s_open_seconds = persist_read_int(PERSIST_KEY_OPEN_SECONDS);
  }
  if (persist_exists(PERSIST_KEY_MESSAGE)) {
    persist_read_string(PERSIST_KEY_MESSAGE, s_message, sizeof(s_message));
  }
  render_text();
}

static void init(void) {
  memset(s_marker_lut, 0xFF, sizeof(s_marker_lut));
  for (int s = 0; s < 2; s++) {
    for (int k = 0; k < LOCKET_SHADE_LEVELS; k++) {
      s_marker_lut[LOCKET_MARKERS[s][k] & 0x3F] = (s << 4) | k;
    }
  }
  load_settings();

  bool need_picture = false;
  if (persist_read_int(PERSIST_KEY_PICTURE_STATE) == PICTURE_CUSTOM) {
    need_picture = !picture_load_persisted();
  }
  if (need_picture || persist_read_int(PERSIST_KEY_PICTURE_STATE) != PICTURE_CUSTOM) {
    picture_load_default();
  }

  s_window = window_create();
  window_set_background_color(s_window, GColorWhite);
  window_set_window_handlers(s_window, (WindowHandlers) {
    .load = window_load,
    .unload = window_unload,
  });
  window_stack_push(s_window, true);

  tick_timer_service_subscribe(MINUTE_UNIT, tick_handler);
  accel_tap_service_subscribe(tap_handler);
  app_message_register_inbox_received(inbox_received_handler);
  app_message_open(1024, 64);

  if (need_picture) {
    // The custom picture didn't fit in storage; the phone keeps a copy.
    send_request(MESSAGE_KEY_REQUEST_PICTURE);
  }
}

static void deinit(void) {
  accel_tap_service_unsubscribe();
  tick_timer_service_unsubscribe();
  window_destroy(s_window);
  free(s_picture_rx);
}

int main(void) {
  init();
  app_event_loop();
  deinit();
}
