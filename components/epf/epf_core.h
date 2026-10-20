#pragma once
// The panel's logic with no ESP-IDF or ESPHome in it: parsing and checking a
// frame file, mapping overlay pixels into the frame buffer, and the navigation
// state machine. Compiled on the host by tests/firmware so it can be tested
// without a panel. epf_client.h adds the network and display glue.

#include <atomic>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <string>
#include <vector>

#if __has_include("esp_log.h")
#include "esp_log.h"
#else
#define ESP_LOGE(tag, ...) ((void) 0)
#define ESP_LOGW(tag, ...) ((void) 0)
#define ESP_LOGI(tag, ...) ((void) 0)
#define ESP_LOGD(tag, ...) ((void) 0)
#endif

namespace epf {

static const char *const TAG = "epf";

constexpr uint32_t MAGIC = 0x45504150;  // "EPAP"
constexpr uint16_t VERSION = 3;
constexpr size_t HEADER_SIZE = 64;
constexpr size_t CAT_RECORD_SIZE = 16;
constexpr size_t PAGE_RECORD_SIZE = 16;
constexpr size_t CRC_SIZE = 4;

constexpr uint32_t FLAG_ALERT_INTERRUPT = 0x0001;
constexpr uint32_t FLAG_QUIET_HOURS = 0x0002;
constexpr uint32_t FLAG_FORCE_FULL = 0x0004;
constexpr uint32_t FLAG_ORIENTATION_180 = 0x0008;
constexpr uint32_t FLAG_GEOMETRY = 0x0010;

constexpr uint16_t CAT_FLAG_SLEEP = 0x0001;       // category 0 is the sleep screen
constexpr uint16_t CAT_FLAG_SLEEP_AUTO = 0x0002;  // ...and quiet hours want the panel asleep
constexpr int SLEEP_RETURN_SEC = 120;             // quiet hours: back to sleep after this long untouched

enum class FetchResult : uint8_t {
  OK,
  NOT_MODIFIED,
  ERROR_NETWORK,
  ERROR_CRC,
  ERROR_HEADER,
  ERROR_BUFFER_FULL,
  ERROR_WRONG_PANEL,
  ERROR_LAYOUT,
  BUSY,
};

inline const char *describe(FetchResult r) {
  switch (r) {
    case FetchResult::OK: return "ok";
    case FetchResult::NOT_MODIFIED: return "not modified";
    case FetchResult::ERROR_NETWORK: return "network error";
    case FetchResult::ERROR_CRC: return "checksum mismatch";
    case FetchResult::ERROR_HEADER: return "not a frame file";
    case FetchResult::ERROR_BUFFER_FULL: return "frame file too large";
    case FetchResult::ERROR_WRONG_PANEL: return "frame file is for a different panel size";
    case FetchResult::ERROR_LAYOUT: return "frame file is inconsistent";
    case FetchResult::BUSY: return "a download is already running";
  }
  return "unknown";
}

struct Header {
  uint16_t model_id{0}, width{0}, height{0}, stride{0}, page_count{0}, cat_count{0}, rotate_sec{30};
  uint32_t flags{0};
  uint64_t content_hash{0};
  uint32_t payload_size{0}, dir_offset{0}, data_offset{0};
};

// Where the footer pills are, in logical pixels, and how logical pixels map to
// the physical buffer. Sent by the server, which drew the footer.
struct Geometry {
  uint16_t logical_w{0}, logical_h{0};
  uint8_t quarter_turns{0};  // orientation setting / 90
  bool mirror_x{false};
  uint16_t pill_y0{0}, pill_y1{0}, cat_x0{0}, sub_x0{0}, sub_x1{0};
};

struct Category {
  uint32_t cat_id{0};
  uint16_t offset_page{0}, page_count{0}, pill_width{0}, flags{0};
};

struct Page {
  uint32_t sub_id{0}, cat_id{0};
  uint16_t cat_index{0}, sub_index{0};
};

struct Stream {
  Header header;
  Geometry geometry;
  std::vector<Category> categories;
  std::vector<Page> pages;
};

inline uint32_t compute_crc32(const uint8_t *data, size_t length) {
  uint32_t crc = 0xFFFFFFFF;
  for (size_t i = 0; i < length; i++) {
    crc ^= data[i];
    for (int k = 0; k < 8; k++) crc = (crc >> 1) ^ (0xEDB88320 & (-(crc & 1)));
  }
  return ~crc;
}

inline uint16_t be16(const uint8_t *p) { return (uint16_t) ((p[0] << 8) | p[1]); }
inline uint32_t be32(const uint8_t *p) {
  return ((uint32_t) p[0] << 24) | ((uint32_t) p[1] << 16) | ((uint32_t) p[2] << 8) | p[3];
}
inline uint64_t be64(const uint8_t *p) { return ((uint64_t) be32(p) << 32) | be32(p + 4); }

// Geometry for frame files from servers before 0.9.3, which only said whether
// the page was turned 180°. These are the numbers the 5.79" footer used then.
inline Geometry legacy_geometry(const Header &h) {
  Geometry g;
  g.logical_w = h.width;
  g.logical_h = h.height;
  g.quarter_turns = (h.flags & FLAG_ORIENTATION_180) ? 2 : 0;
  g.mirror_x = (h.model_id == 0x0579 || h.model_id == 0x0420);
  g.pill_y0 = h.height - 28;
  g.pill_y1 = h.height - 4;
  g.cat_x0 = h.width >= 400 ? 96 : 71;
  g.sub_x1 = h.width - (h.width >= 400 ? 40 : 16);
  g.sub_x0 = g.sub_x1 - 48;
  return g;
}

// Check everything before anything is trusted: checksum, that the file is for
// this panel's size, and that every offset and count stays inside the file.
// native_w/native_h are the display buffer's dimensions; 0 skips that check.
inline FetchResult parse_stream(const uint8_t *buf, size_t len, int native_w, int native_h, Stream &out) {
  if (len < HEADER_SIZE + CRC_SIZE) return FetchResult::ERROR_HEADER;
  size_t body_len = len - CRC_SIZE;
  if (be32(buf + body_len) != compute_crc32(buf, body_len)) return FetchResult::ERROR_CRC;
  if (be32(buf) != MAGIC || be16(buf + 4) != VERSION) return FetchResult::ERROR_HEADER;

  Header h;
  h.model_id = be16(buf + 6);
  h.width = be16(buf + 8);
  h.height = be16(buf + 10);
  h.stride = be16(buf + 12);
  h.page_count = be16(buf + 14);
  h.cat_count = be16(buf + 16);
  h.rotate_sec = be16(buf + 18);
  h.flags = be32(buf + 20);
  h.content_hash = be64(buf + 24);
  h.payload_size = be32(buf + 32);
  h.dir_offset = be32(buf + 36);
  h.data_offset = be32(buf + 40);

  if (native_w > 0 && native_h > 0 && (h.width != native_w || h.height != native_h)) {
    ESP_LOGE(TAG, "Frame file is %ux%u but this panel is %dx%d", h.width, h.height, native_w, native_h);
    return FetchResult::ERROR_WRONG_PANEL;
  }
  if (h.width == 0 || h.height == 0 || h.stride != (h.width + 7) / 8 || h.page_count == 0 || h.cat_count == 0)
    return FetchResult::ERROR_LAYOUT;
  uint64_t page_bytes = (uint64_t) h.stride * h.height;
  uint64_t dir_end = (uint64_t) HEADER_SIZE + (uint64_t) h.cat_count * CAT_RECORD_SIZE +
                     (uint64_t) h.page_count * PAGE_RECORD_SIZE;
  if (h.dir_offset != HEADER_SIZE || h.data_offset != dir_end ||
      h.payload_size != page_bytes * h.page_count || (uint64_t) h.data_offset + h.payload_size != body_len)
    return FetchResult::ERROR_LAYOUT;

  Stream s;
  s.header = h;
  const uint8_t *cp = buf + h.dir_offset;
  for (uint16_t c = 0; c < h.cat_count; c++, cp += CAT_RECORD_SIZE) {
    Category rec{be32(cp), be16(cp + 4), be16(cp + 6), be16(cp + 8), be16(cp + 10)};
    if (rec.page_count == 0 || (uint32_t) rec.offset_page + rec.page_count > h.page_count)
      return FetchResult::ERROR_LAYOUT;
    s.categories.push_back(rec);
  }
  const uint8_t *pp = cp;
  for (uint16_t p = 0; p < h.page_count; p++, pp += PAGE_RECORD_SIZE) {
    Page rec{be32(pp), be32(pp + 4), be16(pp + 8), be16(pp + 10)};
    if (rec.cat_index >= h.cat_count) return FetchResult::ERROR_LAYOUT;
    s.pages.push_back(rec);
  }

  if (h.flags & FLAG_GEOMETRY) {
    const uint8_t *g = buf + 44;
    Geometry geo;
    geo.logical_w = be16(g);
    geo.logical_h = be16(g + 2);
    geo.quarter_turns = g[4] & 3;
    geo.mirror_x = (g[5] & 1) != 0;
    geo.pill_y0 = be16(g + 6);
    geo.pill_y1 = be16(g + 8);
    geo.cat_x0 = be16(g + 10);
    geo.sub_x0 = be16(g + 12);
    geo.sub_x1 = be16(g + 14);
    bool turned = geo.quarter_turns & 1;
    if ((turned ? geo.logical_h : geo.logical_w) != h.width || (turned ? geo.logical_w : geo.logical_h) != h.height)
      return FetchResult::ERROR_LAYOUT;
    s.geometry = geo;
  } else {
    s.geometry = legacy_geometry(h);
  }
  // The footer the panel draws over must sit inside the screen: a broken or
  // forged file with pills off the edge could keep the panel busy drawing them
  // for seconds (audit #14).
  const Geometry &g = s.geometry;
  if (g.pill_y0 > g.pill_y1 || g.pill_y1 >= g.logical_h || g.cat_x0 >= g.logical_w || g.sub_x0 > g.sub_x1 ||
      g.sub_x1 >= g.logical_w)
    return FetchResult::ERROR_LAYOUT;
  for (const auto &c : s.categories)
    if ((uint32_t) g.cat_x0 + c.pill_width >= g.logical_w) return FetchResult::ERROR_LAYOUT;
  out = std::move(s);
  return FetchResult::OK;
}

// Logical pixel -> physical buffer pixel. Mirrors epf.to_physical on the server.
inline bool to_physical(const Geometry &g, int x, int y, int &px, int &py) {
  int lw = g.logical_w, lh = g.logical_h, pw;
  if (x < 0 || y < 0 || x >= lw || y >= lh) return false;
  switch (g.quarter_turns & 3) {
    case 0: px = x; py = y; pw = lw; break;
    case 1: px = lh - 1 - y; py = x; pw = lh; break;
    case 2: px = lw - 1 - x; py = lh - 1 - y; pw = lw; break;
    default: px = y; py = lw - 1 - x; pw = lh; break;
  }
  if (g.mirror_x) px = pw - 1 - px;
  return true;
}

inline bool in_rounded_box(int px, int py, int x0, int y0, int x1, int y1, int r) {
  if (px < x0 || px > x1 || py < y0 || py > y1) return false;
  int cx = px < x0 + r ? x0 + r : (px > x1 - r ? x1 - r : px);
  int cy = py < y0 + r ? y0 + r : (py > y1 - r ? y1 - r : py);
  int dx = px - cx, dy = py - cy;
  return dx * dx + dy * dy <= r * r;
}

struct OverlayState {
  int cat_pill_w{0};       // 0: this page has no category pill
  bool highlight_sub{false};
  bool has_sub{false};
  bool cat_locked{false};
  bool panel_locked{false};
};

// Draw the highlighted pill and padlocks straight into a 1-bit frame buffer
// (row-major, bit 7 first, 1 = white), in logical coordinates mapped through
// the geometry. Nothing about the footer's layout is assumed here.
inline void draw_overlays(uint8_t *buf, int buf_w, int buf_h, const Geometry &g, const OverlayState &s) {
  if (!buf || buf_w <= 0 || buf_h <= 0) return;
  const size_t stride = (size_t) (buf_w + 7) / 8;
  auto pixel = [&](int x, int y, int mode) {  // mode: 0 black, 1 white, 2 invert
    int px, py;
    if (!to_physical(g, x, y, px, py) || px < 0 || py < 0 || px >= buf_w || py >= buf_h) return;
    uint8_t &b = buf[(size_t) py * stride + (size_t) px / 8];
    uint8_t bit = (uint8_t) (1 << (7 - (px % 8)));
    if (mode == 2) b ^= bit;
    else if (mode == 1) b |= bit;
    else b &= (uint8_t) ~bit;
  };
  auto invert_pill = [&](int x0, int y0, int x1, int y1) {
    for (int y = y0; y <= y1; y++)
      for (int x = x0; x <= x1; x++)
        if (in_rounded_box(x, y, x0, y0, x1, y1, 4)) pixel(x, y, 2);
  };
  auto padlock = [&](int bx, int by) {  // 22 x 20: dark badge, white padlock
    const int bw = 22, bh = 20, cx = bx + bw / 2, cy = by + bh / 2;
    for (int y = by; y < by + bh; y++)
      for (int x = bx; x < bx + bw; x++) {
        if (!in_rounded_box(x, y, bx, by, bx + bw - 1, by + bh - 1, 4)) continue;
        int dx = x - cx, dy = y - cy;
        bool shackle = dy >= -6 && dy <= -2 &&
                       ((dy <= -4) ? (dx >= -4 && dx <= 3) : ((dx >= -5 && dx <= -3) || (dx >= 2 && dx <= 4)));
        bool body = dy >= -1 && dy <= 6 && dx >= -6 && dx <= 5;
        bool keyhole = (dy >= 1 && dy <= 2 && dx >= -1 && dx <= 0) || (dy >= 3 && dy <= 4 && dx == 0);
        pixel(x, y, ((shackle || body) && !keyhole) ? 1 : 0);
      }
  };

  const int y0 = g.pill_y0, y1 = g.pill_y1;
  const int cat_x1 = g.cat_x0 + s.cat_pill_w;
  if (s.highlight_sub && s.has_sub) invert_pill(g.sub_x0, y0, g.sub_x1, y1);
  else if (s.cat_pill_w > 0) invert_pill(g.cat_x0, y0, cat_x1, y1);
  if (s.cat_locked && s.cat_pill_w > 0) padlock(cat_x1 + 8, y0 + 2);
  if (s.panel_locked) padlock(s.has_sub ? (g.sub_x0 - 8 - 22) : (g.sub_x1 - 22), y0 + 2);
}

// ---------------------------------------------------------------------------
// When to do a full (ghost-clearing) refresh instead of a quick partial one.
//
// A full refresh flashes black and white for ~1.8 s; partial ones are quick but
// leave faint ghosts that build up. In the default mode a person never sees a
// flash they caused: scrolling and pressing are always partial. Once enough
// partials have built up, the next change the panel makes on its own
// (auto-rotation, new frames) is done as a full refresh. If someone browses so
// long that no such change comes, it clears after a minute of stillness.
// "Classic" is the driver's old every-Nth-refresh, kept as a one-tap revert.
constexpr uint32_t SLEEP_FULL_EVERY = 8;              // asleep between updates: every 8th change is full
constexpr uint32_t SLEEP_FULL_INTERVAL_SEC = 30 * 60;  // ...and every change, at 30 min or more between checks

class WaveformPolicy {
 public:
  void set_threshold(int n) { threshold_ = n < 2 ? 2 : (n > 200 ? 200 : n); }
  void set_classic(bool on) { classic_ = on; }
  int threshold() const { return threshold_; }
  bool classic() const { return classic_; }
  int partials() const { return partials_; }

  // A panel that sleeps between updates (Low Power Mode), TRMNL's way: the display
  // keeps its picture through deep sleep, so a change after a wake is partial. Every
  // 8th change is full, and with 30 minutes or more between checks every change the
  // panel makes on its own is full: ghosts build up while a partial picture sits for
  // that long. A person still never sees a flash they caused. `changes` is kept in
  // RTC memory, so it counts across wakes. nullptr: always on (the policy below).
  void sleep_between(uint32_t *changes, uint32_t interval_sec) {
    changes_ = changes;
    interval_sec_ = interval_sec;
  }
  bool sleeps_between() const { return changes_ != nullptr; }

  // Decide this refresh and record it. `user_cool_sec`: seconds since the last press.
  bool decide(bool forced, bool by_person, bool automatic, int user_cool_sec) {
    bool full;
    if (changes_) {
      bool due = *changes_ + 1 >= SLEEP_FULL_EVERY || interval_sec_ >= SLEEP_FULL_INTERVAL_SEC;
      full = forced || (!by_person && due);
      *changes_ = full ? 0 : *changes_ + 1;
      partials_ = full ? 0 : partials_ + 1;
      return full;
    }
    if (classic_) full = forced || partials_ + 1 >= threshold_;
    else full = forced || (!by_person && automatic && partials_ >= threshold_ && user_cool_sec >= 15);
    partials_ = full ? 0 : partials_ + 1;
    return full;
  }

  bool idle_clear_due(int still_sec) const {
    return !classic_ && partials_ >= 3 * threshold_ && still_sec >= 60;
  }

 private:
  int threshold_{10};
  bool classic_{false};
  int partials_{0};
  uint32_t *changes_{nullptr};
  uint32_t interval_sec_{0};
};

// Every way a person or Home Assistant can move the panel. dispatch() is the
// only entry point, so every input shares one state machine and one notion of
// "someone is using the panel right now".
enum class NavAction : uint8_t {
  NEXT,             // param: steps (default 1)
  PREV,             // param: steps (default 1)
  MODE_TOGGLE,      // categories <-> the current category's items
  LOCK_TOGGLE,      // context-aware: page lock in item mode, category lock otherwise
  PIN_CAT_TOGGLE,   // category lock
  PIN_PAGE_TOGGLE,  // page lock
  CAT_STEP,         // param: delta
  SUB_STEP,         // param: delta
  RESET_HOME,
  GOTO_PAGE,        // param: page index
  GOTO_CAT_SUB,     // param: category, param2: item
  CLEAR_GHOSTING,   // full refresh of what's on screen now
  SLEEP,            // show the sleep screen, stop rotating and redrawing
  WAKE,
  SLEEP_TOGGLE,     // the dial centre held
};

inline const char *nav_name(NavAction a) {
  switch (a) {
    case NavAction::NEXT: return "next";
    case NavAction::PREV: return "previous";
    case NavAction::MODE_TOGGLE: return "mode toggle";
    case NavAction::LOCK_TOGGLE: return "lock toggle";
    case NavAction::PIN_CAT_TOGGLE: return "category lock";
    case NavAction::PIN_PAGE_TOGGLE: return "page lock";
    case NavAction::CAT_STEP: return "category step";
    case NavAction::SUB_STEP: return "item step";
    case NavAction::RESET_HOME: return "home";
    case NavAction::GOTO_PAGE: return "go to page";
    case NavAction::GOTO_CAT_SUB: return "go to category";
    case NavAction::CLEAR_GHOSTING: return "clear ghosting";
    case NavAction::SLEEP: return "sleep";
    case NavAction::WAKE: return "wake";
    case NavAction::SLEEP_TOGGLE: return "sleep toggle";
  }
  return "?";
}

// ---------------------------------------------------------------------------
// Navigation: which page is shown, locks, auto-rotation. One state machine for
// the dial, the buttons, remotes and Home Assistant actions.
class PanelController {
 public:
  static PanelController &instance() {
    static PanelController inst;
    return inst;
  }

  // A person at the panel: its buttons and dial.
  void dispatch(NavAction action, int param = 0, int param2 = 0) { handle_(action, param, param2, true); }

  // Home Assistant, a remote or an automation: nobody is standing at the
  // panel. It wakes and does what was asked (a press only wakes), and it
  // doesn't hold off rotation or ghost clearing as a person would.
  void remote(NavAction action, int param = 0, int param2 = 0) { handle_(action, param, param2, false); }

 private:
  void handle_(NavAction action, int param, int param2, bool person) {
    person_ = person;
    ESP_LOGI(TAG, "Input: %s (%d, %d)%s", nav_name(action), param, param2, person ? "" : " from Home Assistant");
    if (action == NavAction::SLEEP || (action == NavAction::SLEEP_TOGGLE && !sleeping_)) {
      enter_sleep_(true);
      return;
    }
    if (action == NavAction::WAKE || action == NavAction::SLEEP_TOGGLE) {
      if (sleeping_) wake_(person);
      return;
    }
    if (sleeping_ && action != NavAction::CLEAR_GHOSTING) {
      wake_(person);
      if (person) return;                   // the first press only wakes the panel
    }
    switch (action) {
      case NavAction::NEXT: page_step_(param > 0 ? param : 1); break;
      case NavAction::PREV: page_step_(-(param > 0 ? param : 1)); break;
      case NavAction::MODE_TOGGLE: mode_toggle_(); break;
      case NavAction::LOCK_TOGGLE: sub_mode_ ? hold_toggle_() : category_pin_toggle_(); break;
      case NavAction::PIN_CAT_TOGGLE: category_pin_toggle_(); break;
      case NavAction::PIN_PAGE_TOGGLE: hold_toggle_(); break;
      case NavAction::CAT_STEP: category_step_(param); break;
      case NavAction::SUB_STEP: sub_step_(param); break;
      case NavAction::RESET_HOME: reset_home_(); break;
      case NavAction::GOTO_PAGE: show_page_(param); break;
      case NavAction::GOTO_CAT_SUB: show_category_(param, param2); break;
      case NavAction::CLEAR_GHOSTING: redraw_forced_ = true; pending_redraw_ = true; break;
      default: break;
    }
  }

 public:
  // Home Assistant's page_step(delta): forward or back by |delta|.
  void step(int delta) {
    if (delta == 0) return;
    long long n = delta > 0 ? (long long) delta : -(long long) delta;
    remote(delta > 0 ? NavAction::NEXT : NavAction::PREV, (int) (n > 1000000 ? 1000000 : n));
  }

  // Downloads. A failed one is owed: retried with a backoff (30 s, doubling
  // to 10 min) even while resting, because only a download can tell a
  // sleeping panel that quiet hours are over. Otherwise the panel's own
  // interval decides, and resting (asleep, quiet hours) skips it.
  void note_fetch(bool ok) {
    if (ok) { fetch_owed_ = false; owed_retry_sec_ = 30; return; }
    if (fetch_owed_) owed_retry_sec_ = owed_retry_sec_ >= 300 ? 600 : owed_retry_sec_ * 2;
    fetch_owed_ = true;
    fetch_idle_sec_ = 0;
  }
  bool fetch_owed() const { return fetch_owed_; }
  bool fetch_due(int interval_sec) const {
    if (fetch_owed_) return fetch_idle_sec_ >= (owed_retry_sec_ < interval_sec ? owed_retry_sec_ : interval_sec);
    return !resting() && fetch_idle_sec_ >= interval_sec;
  }

  // Called by the redraw script just before the display updates: whether this
  // one should be a full refresh. Consumes what caused the redraw.
  bool begin_redraw() {
    bool full = waveform_.decide(redraw_forced_, redraw_by_person_, redraw_automatic_, user_cool_sec_);
    if (full) ESP_LOGI(TAG, "Full refresh (%s)", redraw_forced_ ? "requested" : "ghosting built up");
    redraw_forced_ = redraw_by_person_ = redraw_automatic_ = false;
    pending_redraw_ = false;
    return full;
  }

  // The fallback: nobody has touched the panel for a minute and no automatic
  // change came along to carry the clear.
  bool idle_clear_due() {
    if (!waveform_.idle_clear_due(user_cool_sec_ < idle_sec_ ? user_cool_sec_ : idle_sec_)) return false;
    redraw_forced_ = true;
    pending_redraw_ = true;
    return true;
  }

  WaveformPolicy &waveform() { return waveform_; }

 private:
  void page_step_(int delta) {
    touch_();
    int cats = cats_();
    if (cat_idx_ >= cats) cat_idx_ = 0;
    if (sub_mode_ && size_(cat_idx_) > 1) {
      int sz = size_(cat_idx_);
      sub_idx_ = ((sub_idx_ + delta) % sz + sz) % sz;
      remember_sub_(cat_idx_, sz);
      go_(cat_idx_, sub_idx_);
      ESP_LOGI(TAG, "Nav (sub): cat=%d/%d sub=%d/%d (page=%d/%d)", cat_idx_ + 1, cats, sub_idx_ + 1, sz, page_ + 1, page_count_);
    } else {
      enter_category_(step_category_(cat_idx_, delta));
      ESP_LOGI(TAG, "Nav (cat): cat=%d/%d sub=%d/%d (page=%d/%d)", cat_idx_ + 1, cats, sub_idx_ + 1, size_(cat_idx_), page_ + 1, page_count_);
    }
  }

  void category_step_(int delta) {
    touch_();
    enter_category_(step_category_(cat_idx_, delta));
  }

  void sub_step_(int delta) {
    touch_();
    int sz = size_(cat_idx_);
    if (sz <= 1) return;
    sub_idx_ = ((sub_idx_ + delta) % sz + sz) % sz;
    remember_sub_(cat_idx_, sz);
    go_(cat_idx_, sub_idx_);
  }

  void mode_toggle_() {
    touch_();
    sub_mode_ = size_(cat_idx_) > 1 ? !sub_mode_ : false;
    ESP_LOGI(TAG, "Navigation mode: %s", sub_mode_ ? "sub-items" : "categories");
  }

  void hold_toggle_() {
    touch_();
    pinned_ = !pinned_;
    if (pinned_) {
      cat_pinned_ = false;
      pinned_cat_id_ = cur_cat_id_;
      pinned_sub_id_ = cur_sub_id_;
    } else {
      pinned_cat_id_ = pinned_sub_id_ = 0;
    }
    ESP_LOGI(TAG, "Panel lock: %d", pinned_);
  }

  void category_pin_toggle_() {
    touch_();
    cat_pinned_ = !cat_pinned_;
    if (cat_pinned_) {
      pinned_ = false;
      pinned_sub_id_ = 0;
      pinned_cat_id_ = cur_cat_id_;
    } else {
      pinned_cat_id_ = 0;
    }
    ESP_LOGI(TAG, "Category lock: %d", cat_pinned_);
  }

  void reset_home_() {
    touch_();
    sub_mode_ = false;
    sub_idx_ = 0;
    cat_idx_ = first_cat_();
    go_(cat_idx_, 0);
  }

  void show_page_(int index) {
    touch_();
    if (has_sleep_) index += 1;             // Home Assistant counts your pages, not the sleep screen
    if (index < 0 || index >= page_count_) return;
    for (int c = (int) offsets_.size() - 1; c >= 0; c--) {
      if (index >= offsets_[c]) {
        cat_idx_ = c;
        sub_idx_ = index - offsets_[c];
        break;
      }
    }
    page_ = index;
    update_ids_();
  }

  void show_category_(int category, int sub) {
    touch_();
    if (has_sleep_) category += 1;
    if (category < 0 || category >= cats_()) return;
    int sz = size_(category);
    cat_idx_ = category;
    sub_idx_ = (sub >= 0 && sub < sz) ? sub : 0;
    go_(cat_idx_, sub_idx_);
  }

 public:
  void tick_seconds(int s) {
    idle_sec_ += s;
    fetch_idle_sec_ += s;
    if (user_cool_sec_ < 1000) user_cool_sec_ += s;
  }

  bool check_auto_rotate() {
    if (sleeping_) return false;
    // Quiet hours: someone woke the panel, then left. Back to sleep.
    if (quiet_ && auto_sleep_ && !pinned_ && !cat_pinned_ && user_cool_sec_ >= SLEEP_RETURN_SEC) {
      ESP_LOGI(TAG, "Untouched for %d s during quiet hours: back to sleep", SLEEP_RETURN_SEC);
      enter_sleep_(false);
      return true;
    }
    if (quiet_ || pinned_ || user_cool_sec_ < 15) return false;
    if (idle_sec_ < (rotate_sec_ >= 5 ? rotate_sec_ : 30)) return false;
    idle_sec_ = 0;
    int sz = size_(cat_idx_);
    if (cat_pinned_) {
      if (sz <= 1) return false;
      sub_idx_ = (sub_idx_ + 1) % sz;
      remember_sub_(cat_idx_, sz);
      go_(cat_idx_, sub_idx_);
    } else {
      int c = step_category_(cat_idx_, 1);
      int csz = size_(c);
      if ((int) sub_pos_.size() <= c) sub_pos_.resize(cats_(), 0);
      int s = csz > 1 ? sub_pos_[c] % csz : 0;
      if (csz > 1) sub_pos_[c] = (s + 1) % csz;
      sub_mode_ = false;
      cat_idx_ = c;
      sub_idx_ = s;
      go_(c, s);
    }
    pending_redraw_ = true;
    redraw_automatic_ = true;
    return true;
  }

  bool should_defer_refetch() const { return user_cool_sec_ < 15; }

  // A new frame file arrived: adopt its directory and keep the reader where
  // they were, by identity rather than by position.
  void on_stream_loaded(const Stream &s) {
    std::vector<uint32_t> old_ids = cat_ids_;
    std::vector<int> old_pos = sub_pos_;
    page_count_ = s.header.page_count;
    if (s.header.rotate_sec >= 5 && s.header.rotate_sec <= 3600) rotate_sec_ = s.header.rotate_sec;
    bool was_quiet = quiet_;
    quiet_ = (s.header.flags & FLAG_QUIET_HOURS) != 0;
    // New frames are a change the panel makes on its own. Alerts, a forced
    // full refresh and the start of quiet hours (held all night) are full.
    pending_redraw_ = true;
    redraw_automatic_ = true;
    if ((s.header.flags & (FLAG_ALERT_INTERRUPT | FLAG_FORCE_FULL)) || (quiet_ && !was_quiet)) redraw_forced_ = true;
    offsets_.clear(); sizes_.clear(); pill_w_.clear(); cat_ids_.clear(); sub_ids_.clear();
    for (const auto &c : s.categories) {
      offsets_.push_back(c.offset_page);
      sizes_.push_back(c.page_count);
      pill_w_.push_back(c.pill_width);
      cat_ids_.push_back(c.cat_id);
    }
    for (const auto &p : s.pages) sub_ids_.push_back(p.sub_id);
    has_sleep_ = !s.categories.empty() && (s.categories[0].flags & CAT_FLAG_SLEEP);
    auto_sleep_ = has_sleep_ && (s.categories[0].flags & CAT_FLAG_SLEEP_AUTO);

    sub_pos_.assign(cat_ids_.size(), 0);
    for (size_t i = 0; i < cat_ids_.size(); i++)
      for (size_t j = 0; j < old_ids.size() && j < old_pos.size(); j++)
        if (old_ids[j] == cat_ids_[i]) { sub_pos_[i] = old_pos[j]; break; }

    if (s.header.flags & FLAG_ALERT_INTERRUPT) {
      // The alert owns the screen, even over sleep. Locks are kept and come
      // back with the rotation when the alert is over, and so does sleep:
      // a panel asleep before the alert goes back to sleep after it, unless
      // someone pressed a button in the meantime.
      if (!alert_) {
        asleep_before_alert_ = sleeping_;
        manual_before_alert_ = sleep_manual_;
      }
      sleeping_ = false;
      cat_idx_ = sub_idx_ = page_ = 0;
      sub_mode_ = false;
      alert_ = true;
      update_ids_(false);
      return;
    }
    bool alert_ended = alert_;
    alert_ = false;

    if (pinned_ && pinned_sub_id_ && find_page_(pinned_sub_id_)) {
      sub_mode_ = size_(cat_idx_) > 1;
    } else if (cat_pinned_ && pinned_cat_id_ && find_cat_(pinned_cat_id_)) {
    } else {
      if (pinned_ && pinned_sub_id_) {
        ESP_LOGW(TAG, "Locked item left the rotation; releasing the lock");
        pinned_ = false;
        pinned_sub_id_ = pinned_cat_id_ = 0;
      }
      if (cat_pinned_ && pinned_cat_id_) {
        ESP_LOGW(TAG, "Locked category left the rotation; releasing the lock");
        cat_pinned_ = false;
        pinned_cat_id_ = 0;
      }
      if (!(cur_sub_id_ && find_page_(cur_sub_id_)) && !(cur_cat_id_ && find_cat_(cur_cat_id_))) {
        if (cat_idx_ < 0 || cat_idx_ >= cats_() || (has_sleep_ && cat_idx_ == 0)) cat_idx_ = first_cat_();
        int sz = size_(cat_idx_);
        if (sz <= 1) { sub_idx_ = 0; sub_mode_ = false; }
        else if (sub_idx_ < 0 || sub_idx_ >= sz) sub_idx_ = sub_pos_[cat_idx_] % sz;
        go_(cat_idx_, sub_idx_);
      }
    }
    update_ids_();

    uint32_t sleep_id = has_sleep_ && !sub_ids_.empty() ? sub_ids_[0] : 0;
    if (!has_sleep_ && sleeping_) {
      sleeping_ = false;                    // no sleep screen in this file: show the pages
    } else if (auto_sleep_ && quiet_ && !was_quiet && !pinned_ && !cat_pinned_) {
      ESP_LOGI(TAG, "Quiet hours: going to sleep");
      enter_sleep_(false);
    } else if (sleeping_ && !sleep_manual_ && was_quiet && !quiet_) {
      ESP_LOGI(TAG, "Quiet hours are over: waking up");
      wake_(false);
    } else if (alert_ended && asleep_before_alert_ && has_sleep_) {
      ESP_LOGI(TAG, "The alert is over: back to sleep");
      enter_sleep_(manual_before_alert_);
    } else if (sleeping_ && sleep_id == sleep_sub_id_) {
      // Still asleep and the sleep screen hasn't changed: nothing to redraw.
      pending_redraw_ = redraw_automatic_ = false;
      redraw_forced_ = false;
    }
    sleep_sub_id_ = sleep_id;
    if (alert_ended) asleep_before_alert_ = false;
  }

  OverlayState overlay_state() const {
    OverlayState o;
    if (sleeping_) return o;                // nothing drawn over the sleep screen
    int sz = size_(cat_idx_);
    o.cat_pill_w = cat_idx_ < (int) pill_w_.size() ? pill_w_[cat_idx_] : 0;
    o.has_sub = sz > 1;
    o.highlight_sub = sub_mode_ && sz > 1;
    o.cat_locked = cat_pinned_ && !alert_;
    o.panel_locked = pinned_ && !alert_;
    return o;
  }

  int page() const { return sleeping_ ? 0 : page_; }
  bool sleeping() const { return sleeping_; }
  // Asleep or in quiet hours: the panel doesn't fetch on its own timer.
  bool resting() const { return quiet_ || sleeping_; }
  // True once after waking from a sleep that skipped downloads.
  bool take_wake_fetch() {
    bool w = wake_fetch_;
    wake_fetch_ = false;
    return w;
  }
  int cat_idx() const { return cat_idx_; }
  int sub_idx() const { return sub_idx_; }
  int page_count() const { return page_count_; }
  int cat_count() const { return cats_(); }
  bool sub_mode() const { return sub_mode_; }
  bool pinned() const { return pinned_; }
  bool cat_pinned() const { return cat_pinned_; }
  bool quiet_hours_active() const { return quiet_; }
  int user_cool_sec() const { return user_cool_sec_; }
  int fetch_idle_sec() const { return fetch_idle_sec_; }
  void reset_fetch_idle() { fetch_idle_sec_ = 0; }
  void retry_fetch_in(int seconds, int interval) { fetch_idle_sec_ = interval - seconds; }
  bool pending_refetch() const { return pending_refetch_; }
  void set_pending_refetch(bool v) { pending_refetch_ = v; }
  bool pending_redraw() const { return pending_redraw_; }

 private:
  PanelController() = default;

  int cats_() const { return offsets_.empty() ? 1 : (int) offsets_.size(); }
  int size_(int c) const { return (c >= 0 && c < (int) sizes_.size() && sizes_[c] > 0) ? sizes_[c] : 1; }
  int offset_(int c) const { return (c >= 0 && c < (int) offsets_.size()) ? offsets_[c] : c; }
  void touch_() {
    idle_sec_ = 0;
    pending_redraw_ = true;
    if (!person_) { redraw_automatic_ = true; return; }
    user_cool_sec_ = 0;
    redraw_by_person_ = true;
    asleep_before_alert_ = false;           // someone is here: leave it awake after an alert
  }
  void remember_sub_(int c, int sz) {
    if ((int) sub_pos_.size() <= c) sub_pos_.resize(cats_(), 0);
    sub_pos_[c] = (sub_idx_ + 1) % sz;
  }
  void go_(int c, int s) {
    int p = offset_(c) + s;
    page_ = (p >= 0 && p < page_count_) ? p : 0;
    update_ids_();
  }
  int first_cat_() const { return (has_sleep_ && cats_() > 1) ? 1 : 0; }
  // Step through categories, never landing on the sleep screen.
  int step_category_(int from, int delta) const {
    int cats = cats_(), c = from, n = delta < 0 ? -delta : delta, dir = delta < 0 ? -1 : 1;
    int ring = (has_sleep_ && cats > 1) ? cats - 1 : cats;    // the sleep screen isn't stepped onto
    n %= ring;                              // a huge step must not spin the main loop
    for (int i = 0; i < n; i++) {
      c = ((c + dir) % cats + cats) % cats;
      if (has_sleep_ && c == 0 && cats > 1) c = ((c + dir) % cats + cats) % cats;
    }
    return c;
  }
  void enter_sleep_(bool manual) {
    if (!has_sleep_) {
      ESP_LOGW(TAG, "No sleep screen yet (update the add-on); staying awake");
      return;
    }
    if (!sleeping_) wake_sub_id_ = cur_sub_id_;
    sleeping_ = true;
    sleep_manual_ = manual;
    sub_mode_ = false;
    pending_redraw_ = true;
    redraw_forced_ = true;                  // one clean full refresh onto the sleep screen
  }
  void wake_(bool by_person) {
    sleeping_ = false;
    wake_fetch_ = true;
    if (!(wake_sub_id_ && find_page_(wake_sub_id_)) || (has_sleep_ && cat_idx_ == 0)) {
      cat_idx_ = first_cat_();
      sub_idx_ = 0;
      go_(cat_idx_, 0);
    }
    update_ids_();
    if (by_person) touch_();
    else { pending_redraw_ = true; redraw_automatic_ = true; }
    ESP_LOGI(TAG, "Awake");
  }
  void enter_category_(int c) {
    cat_idx_ = c;
    int sz = size_(c);
    if ((int) sub_pos_.size() <= c) sub_pos_.resize(cats_(), 0);
    sub_idx_ = sz > 1 ? sub_pos_[c] % sz : 0;
    sub_mode_ = false;
    go_(c, sub_idx_);
  }
  bool find_page_(uint32_t id) {
    for (size_t p = 0; p < sub_ids_.size(); p++) {
      if (sub_ids_[p] != id) continue;
      for (int c = 0; c < cats_(); c++) {
        if ((int) p >= offset_(c) && (int) p < offset_(c) + size_(c)) {
          cat_idx_ = c;
          sub_idx_ = (int) p - offset_(c);
          page_ = (int) p;
          return true;
        }
      }
    }
    return false;
  }
  bool find_cat_(uint32_t id) {
    for (size_t c = 0; c < cat_ids_.size(); c++) {
      if (cat_ids_[c] != id) continue;
      cat_idx_ = (int) c;
      int sz = size_(cat_idx_);
      if (sz <= 1) { sub_idx_ = 0; sub_mode_ = false; }
      else if (sub_idx_ < 0 || sub_idx_ >= sz) sub_idx_ = sub_pos_[cat_idx_] % sz;
      page_ = offset_(cat_idx_) + sub_idx_;
      if (page_ >= page_count_) page_ = 0;
      return true;
    }
    return false;
  }
  void update_ids_(bool follow_locks = true) {
    cur_cat_id_ = cat_idx_ < (int) cat_ids_.size() ? cat_ids_[cat_idx_] : 0;
    cur_sub_id_ = page_ < (int) sub_ids_.size() ? sub_ids_[page_] : 0;
    if (!follow_locks || alert_) return;    // an alert never moves a lock
    if (pinned_) { pinned_sub_id_ = cur_sub_id_; pinned_cat_id_ = cur_cat_id_; }
    else if (cat_pinned_) pinned_cat_id_ = cur_cat_id_;
  }

  int page_{0}, cat_idx_{0}, sub_idx_{0}, page_count_{1};
  bool sub_mode_{false}, pinned_{false}, cat_pinned_{false}, quiet_{false}, alert_{false};
  bool has_sleep_{false}, auto_sleep_{false}, sleeping_{false}, sleep_manual_{false}, wake_fetch_{false};
  uint32_t wake_sub_id_{0}, sleep_sub_id_{0};
  uint32_t pinned_cat_id_{0}, pinned_sub_id_{0}, cur_cat_id_{0}, cur_sub_id_{0};
  int rotate_sec_{30}, idle_sec_{0}, user_cool_sec_{999}, fetch_idle_sec_{0};
  bool pending_redraw_{false}, pending_refetch_{false};
  bool redraw_forced_{false}, redraw_by_person_{false}, redraw_automatic_{false};
  bool person_{true}, asleep_before_alert_{false}, manual_before_alert_{false}, fetch_owed_{false};
  int owed_retry_sec_{30};
  WaveformPolicy waveform_;
  std::vector<int> offsets_, sizes_, pill_w_, sub_pos_;
  std::vector<uint32_t> cat_ids_, sub_ids_;
};

// ---------------------------------------------------------------- Low Power Mode
//
// One firmware for both modes: the add-on decides on every download. An answer
// with `X-EPF-Sleep: <seconds>; awake=<seconds>` means "check again in that
// many seconds (counted from this answer), and stay awake that long first";
// a 200 or 304 without it means "stay connected", as always. The panel never
// sleeps on its own say-so, except to retry later when a timer wake couldn't
// reach the add-on at all (it was told to sleep before, so it's on a battery).

struct SleepOrder {
  uint32_t sleep_sec{0};
  uint32_t awake_sec{0};
};

constexpr uint32_t MIN_SLEEP_SEC = 30;             // never a wake loop, whatever an answer says
constexpr uint32_t MAX_SLEEP_SEC = 26 * 3600;      // a day, plus quiet hours' margin
constexpr uint32_t MAX_AWAKE_SEC = 3600;
constexpr uint32_t PERSON_AWAKE_SEC = 60;          // after the last press
constexpr uint32_t RETRY_FIRST_SEC = 60;           // couldn't reach the add-on: 60 s, doubling...
constexpr uint32_t RETRY_MAX_SEC = 600;            // ...to 10 min, never past the interval
constexpr uint32_t QUICK_WAKE_MS = 2000;           // a "press" this soon after sleeping is a floating pin
constexpr uint32_t QUICK_WAKES_LIMIT = 3;

// "900" or "900; awake=60" (spaces allowed). False for anything else, which is then ignored.
inline bool parse_sleep_order(const char *v, SleepOrder &out) {
  if (!v) return false;
  auto skip = [&](const char *p) { while (*p == ' ' || *p == '\t') p++; return p; };
  auto number = [&](const char *&p, uint32_t &n) {
    if (*p < '0' || *p > '9') return false;
    uint64_t acc = 0;
    while (*p >= '0' && *p <= '9') {
      acc = acc * 10 + (uint64_t) (*p++ - '0');
      if (acc > 0xFFFFFFFFull) return false;
    }
    n = (uint32_t) acc;
    return true;
  };
  SleepOrder o;
  const char *p = skip(v);
  if (!number(p, o.sleep_sec)) return false;
  p = skip(p);
  if (*p == ';') {
    p = skip(p + 1);
    if (std::strncmp(p, "awake=", 6) != 0) return false;
    p += 6;
    if (!number(p, o.awake_sec)) return false;
    p = skip(p);
  }
  if (*p != '\0') return false;
  o.sleep_sec = o.sleep_sec < MIN_SLEEP_SEC ? MIN_SLEEP_SEC : (o.sleep_sec > MAX_SLEEP_SEC ? MAX_SLEEP_SEC : o.sleep_sec);
  o.awake_sec = o.awake_sec > MAX_AWAKE_SEC ? MAX_AWAKE_SEC : o.awake_sec;
  out = o;
  return true;
}

enum class Wake : uint8_t { BOOT, TIMER, BUTTON };

inline const char *wake_name(Wake w) {
  switch (w) {
    case Wake::TIMER: return "timer";
    case Wake::BUTTON: return "button";
    case Wake::BOOT: break;
  }
  return "boot";
}

// What the panel keeps through deep sleep (in RTC memory, epf_power.cpp). Gone
// after a power cut or a reset, which is right: then it's a fresh start.
struct Remembered {
  uint32_t magic;
  uint32_t interval_sec;      // the last answer's sleep time; 0: stay connected
  uint32_t failures;          // timer wakes in a row that couldn't reach the add-on
  uint32_t awake_ms;          // how long the last wake was awake, for the add-on
  uint32_t quick_wakes;       // button wakes in a row right after falling asleep
  uint32_t buttons_off;       // the buttons woke it in a loop: timer only until the next timer wake
  uint32_t picture_kept;      // it went to sleep with the display powered, its picture in memory
  uint32_t changes;           // picture changes since the last full refresh (WaveformPolicy)
  char etag[40];              // what's on screen, so an unchanged page is a 304: no download, no redraw
};
constexpr uint32_t REMEMBERED_MAGIC = 0x4C504D32;  // "LPM2"

// When to sleep, and for how long. Times are millis(); differences survive its wrap.
class PowerPolicy {
 public:
  static PowerPolicy &instance() {
    static PowerPolicy inst;
    return inst;
  }

  // At start-up. `slept_ms`: how long it was asleep (0 if not from deep sleep).
  void begin(Wake wake, Remembered &mem, uint32_t slept_ms) {
    if (mem.magic != REMEMBERED_MAGIC || wake == Wake::BOOT) {
      mem = Remembered{};
      mem.magic = REMEMBERED_MAGIC;
    }
    wake_ = wake;
    mem_ = &mem;
    have_ = held_ = pressed_ = false;
    kept_ = wake != Wake::BOOT && mem.picture_kept;
    mem.picture_kept = 0;                           // until it next sleeps with the display powered
    if (wake == Wake::BUTTON && slept_ms < QUICK_WAKE_MS) {
      if (++mem.quick_wakes >= QUICK_WAKES_LIMIT && !mem.buttons_off) {
        mem.buttons_off = 1;
        ESP_LOGW(TAG, "The buttons woke the panel %u times as it fell asleep: waking on the timer only for now",
                 (unsigned) mem.quick_wakes);
      }
    } else {
      mem.quick_wakes = 0;
      if (wake == Wake::TIMER) mem.buttons_off = 0;   // try them again
    }
  }

  // After every download. `http_status`: the answer's HTTP status, 0 when nothing answered.
  // A sleep order is obeyed whatever the status. Without one, only the add-on's own
  // answer to a download (200 or 304) means "stay connected"; anything else (a 502
  // from Home Assistant while the add-on restarts, a tunnel's 5xx, a 401 or 429)
  // isn't the add-on speaking, so it counts as no answer.
  void on_answer(int http_status, bool has_order, const SleepOrder &order, uint32_t now_ms) {
    if (!mem_) return;
    if (has_order || http_status == 200 || http_status == 304) {
      mem_->failures = 0;
      if (has_order) {
        order_ = order;
        have_ = true;
        answer_ms_ = now_ms;
        mem_->interval_sec = order.sleep_sec;
      } else {
        if (have_) ESP_LOGI(TAG, "Low Power Mode is off: staying connected");
        have_ = false;
        mem_->interval_sec = 0;
      }
      return;
    }
    // No answer. Already told what to do this wake: that stands. Never told: stay connected.
    if (have_ || mem_->interval_sec == 0) return;
    mem_->failures++;
    order_.sleep_sec = retry_sec_();
    order_.awake_sec = wake_ == Wake::TIMER ? 0 : PERSON_AWAKE_SEC;
    have_ = true;
    answer_ms_ = now_ms;
    ESP_LOGW(TAG, "Couldn't reach the add-on: trying again in %u s", (unsigned) order_.sleep_sec);
  }

  // Someone pressed a button: awake a minute after their last press.
  void note_press(uint32_t now_ms) {
    pressed_ = true;
    press_ms_ = now_ms;
  }

  // An update over Wi-Fi is running: never sleep in the middle of it.
  void hold(bool on) { held_ = on; }

  bool low_power() const { return have_; }
  Wake wake() const { return wake_; }
  bool buttons_wake() const { return !mem_ || !mem_->buttons_off; }

  // Whether to sleep now. `busy`: a download, a redraw or a refresh is still going.
  bool sleep_due(uint32_t now_ms, bool busy) const {
    if (!have_ || held_ || busy) return false;
    if (now_ms - answer_ms_ < order_.awake_sec * 1000u) return false;
    uint32_t after_press = order_.awake_sec > PERSON_AWAKE_SEC ? order_.awake_sec : PERSON_AWAKE_SEC;
    if (pressed_ && now_ms - press_ms_ < after_press * 1000u) return false;
    return true;
  }

  // How long to sleep, counted from now: what the answer said, less the time awake since.
  uint32_t sleep_ms(uint32_t now_ms) const {
    uint64_t want = (uint64_t) order_.sleep_sec * 1000u, spent = now_ms - answer_ms_;
    uint64_t left = want > spent ? want - spent : 0;
    return (uint32_t) (left < MIN_SLEEP_SEC * 1000u ? MIN_SLEEP_SEC * 1000u : left);
  }

  // Just before sleeping: what the next wake tells the add-on, and whether the
  // display stays powered with its picture in memory (TRMNL's way).
  void before_sleep(uint32_t now_ms, bool display_kept) {
    if (!mem_) return;
    mem_->awake_ms = now_ms;
    mem_->picture_kept = display_kept;
  }

  // After a deep sleep that kept the display powered: it still holds what's on
  // screen, so the first change can be partial. False after any other start.
  bool picture_kept() const { return kept_; }

 private:
  PowerPolicy() = default;
  uint32_t retry_sec_() const {
    uint32_t s = RETRY_FIRST_SEC;
    for (uint32_t i = 1; i < mem_->failures && s < RETRY_MAX_SEC; i++) s *= 2;
    if (s > RETRY_MAX_SEC) s = RETRY_MAX_SEC;
    return s < mem_->interval_sec ? s : mem_->interval_sec;
  }

  Remembered *mem_{nullptr};
  Wake wake_{Wake::BOOT};
  SleepOrder order_;
  bool have_{false}, held_{false}, pressed_{false}, kept_{false};
  uint32_t answer_ms_{0}, press_ms_{0};
};

// Which refresh policy applies: the sleeping one (WaveformPolicy::sleep_between)
// while answers put the panel to sleep, or once it woke from such a sleep until
// an answer says otherwise; always on otherwise. At start-up and after every answer.
inline void choose_waveform(WaveformPolicy &w, const PowerPolicy &p, Remembered &mem) {
  bool between = p.low_power() || (p.wake() != Wake::BOOT && mem.interval_sec > 0);
  w.sleep_between(between ? &mem.changes : nullptr, mem.interval_sec);
}

// The panel's own download timer. Off while the add-on's answers decide when it
// wakes (Low Power Mode): those downloads would only keep it awake longer.
inline bool own_timer_fetch_due(const PanelController &panel, const PowerPolicy &power, int interval_sec) {
  return !power.low_power() && panel.fetch_due(interval_sec);
}

}  // namespace epf
