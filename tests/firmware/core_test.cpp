// Host-side tests for components/epf/epf_core.h, driven by tests/test_firmware.py,
// which writes real frame files from the server's own encoder into a folder.
//
//   core_test <fixture-dir>

#include "../../components/epf/epf_core.h"

#include <chrono>
#include <cstdio>
#include <fstream>
#include <iterator>
#include <set>
#include <sstream>

#include <zlib.h>

// The panel inflates with ESP32 ROM's tinfl; here, zlib, through the same hook (epf::Inflater).
static bool inflate_zlib(const uint8_t *src, size_t len, uint8_t *out, size_t out_len) {
  z_stream z{};
  if (inflateInit2(&z, -15) != Z_OK) return false;
  z.next_in = const_cast<Bytef *>(src);
  z.avail_in = (uInt) len;
  z.next_out = out;
  z.avail_out = (uInt) out_len;
  int r = inflate(&z, Z_FINISH);
  size_t got = out_len - z.avail_out;
  inflateEnd(&z);
  return r == Z_STREAM_END && got == out_len;
}

static int failures = 0;
#define CHECK(cond, ...)                         \
  do {                                           \
    if (!(cond)) {                               \
      failures++;                                \
      std::printf("FAIL %s:%d: ", __FILE__, __LINE__); \
      std::printf(__VA_ARGS__);                  \
      std::printf("\n");                         \
    }                                            \
  } while (0)

static std::vector<uint8_t> read_file(const std::string &path) {
  std::ifstream f(path, std::ios::binary);
  return std::vector<uint8_t>(std::istreambuf_iterator<char>(f), {});
}

// Every orientation: the frame file parses, and to_physical agrees with the
// server's pipeline pixel for pixel (vectors computed with Pillow).
static void test_streams_and_mapping(const std::string &dir) {
  for (int q = 0; q < 4; q++) {
    std::string base = dir + "/orient" + std::to_string(q);
    auto buf = read_file(base + ".epf");
    epf::Stream s;
    auto r = epf::parse_stream(buf.data(), buf.size(), 792, 272, s);
    CHECK(r == epf::FetchResult::OK, "orient %d: parse failed: %s", q, epf::describe(r));
    if (r != epf::FetchResult::OK) continue;
    CHECK(s.geometry.quarter_turns == q, "orient %d: quarter_turns %d", q, s.geometry.quarter_turns);

    std::ifstream vec(base + ".vectors");
    int x, y, px, py, n = 0;
    while (vec >> x >> y >> px >> py) {
      int gx, gy;
      CHECK(epf::to_physical(s.geometry, x, y, gx, gy) && gx == px && gy == py,
            "orient %d: (%d,%d) -> (%d,%d), server says (%d,%d)", q, x, y, gx, gy, px, py);
      n++;
    }
    CHECK(n > 0, "orient %d: no vectors", q);

    // Highlighting the category pill inverts exactly the pixels the server
    // listed as inside that pill, and nothing else.
    std::vector<uint8_t> page(buf.begin() + s.header.data_offset,
                              buf.begin() + s.header.data_offset + (size_t) s.header.stride * s.header.height);
    std::vector<uint8_t> before = page;
    epf::OverlayState st;
    st.cat_pill_w = s.categories[0].pill_width;
    epf::draw_overlays(page.data(), 792, 272, s.geometry, st);
    std::set<std::pair<int, int>> changed;
    for (int py2 = 0; py2 < 272; py2++)
      for (int px2 = 0; px2 < 792; px2++) {
        size_t i = (size_t) py2 * s.header.stride + px2 / 8;
        uint8_t bit = (uint8_t) (1 << (7 - px2 % 8));
        if ((page[i] & bit) != (before[i] & bit)) changed.insert({px2, py2});
      }
    std::ifstream pill(base + ".pill");
    std::set<std::pair<int, int>> expected;
    while (pill >> px >> py) expected.insert({px, py});
    CHECK(!expected.empty() && changed == expected, "orient %d: highlight touched %zu pixels, expected %zu", q,
          changed.size(), expected.size());
  }
}

static void test_rejects_bad_files(const std::string &dir) {
  auto good = read_file(dir + "/orient0.epf");
  epf::Stream s;
  CHECK(epf::parse_stream(good.data(), good.size(), 400, 300, s) == epf::FetchResult::ERROR_WRONG_PANEL,
        "a 792x272 file must not load on a 400x300 panel");
  auto cut = good;
  cut.resize(cut.size() - 100);
  CHECK(epf::parse_stream(cut.data(), cut.size(), 792, 272, s) == epf::FetchResult::ERROR_CRC, "truncated file");
  CHECK(epf::parse_stream(good.data(), 10, 792, 272, s) == epf::FetchResult::ERROR_HEADER, "tiny file");

  // A self-consistent checksum around a lying directory must still be refused.
  auto bad = good;
  bad[14] = 0x7F;  // page_count high byte
  uint32_t crc = epf::compute_crc32(bad.data(), bad.size() - 4);
  for (int i = 0; i < 4; i++) bad[bad.size() - 4 + i] = (uint8_t) (crc >> (24 - 8 * i));
  CHECK(epf::parse_stream(bad.data(), bad.size(), 792, 272, s) == epf::FetchResult::ERROR_LAYOUT, "lying page count");

  auto legacy = read_file(dir + "/legacy180.epf");
  CHECK(epf::parse_stream(legacy.data(), legacy.size(), 792, 272, s) == epf::FetchResult::OK, "legacy file");
  CHECK(s.geometry.quarter_turns == 2 && s.geometry.mirror_x && s.geometry.cat_x0 == 96,
        "legacy geometry from the 180 flag");
}

static void put16(std::vector<uint8_t> &b, size_t at, uint16_t v) {
  b[at] = (uint8_t) (v >> 8);
  b[at + 1] = (uint8_t) v;
}

static void fix_crc(std::vector<uint8_t> &b) {
  uint32_t crc = epf::compute_crc32(b.data(), b.size() - 4);
  for (int i = 0; i < 4; i++) b[b.size() - 4 + i] = (uint8_t) (crc >> (24 - 8 * i));
}

// The 2.9"'s memory is upright (128 x 296): its frame file is, and its footer is
// checked against the page as mounted (296 x 128).
static void test_upright_panel(const std::string &dir) {
  auto buf = read_file(dir + "/upright.epf");
  epf::Stream s;
  auto r = epf::parse_stream(buf.data(), buf.size(), 128, 296, s);
  CHECK(r == epf::FetchResult::OK, "the 2.9\"'s frame file loads on its upright display: %s", epf::describe(r));
  CHECK(s.geometry.quarter_turns == 3 && s.geometry.logical_w == 296 && s.geometry.logical_h == 128,
        "turned 270 degrees, the page as mounted");
  CHECK(epf::parse_stream(buf.data(), buf.size(), 296, 128, s) == epf::FetchResult::ERROR_WRONG_PANEL,
        "a landscape display buffer refuses it");
}

// Footer positions off the screen are refused when the file is read (audit #14).
// Offsets: the geometry block starts at byte 44, the first category record at 64.
static void test_footer_inside_the_screen(const std::string &dir) {
  auto good = read_file(dir + "/orient0.epf");
  epf::Stream s;
  CHECK(epf::parse_stream(good.data(), good.size(), 792, 272, s) == epf::FetchResult::OK, "the server's own file");
  struct Case { const char *what; size_t at; uint16_t value; };
  const Case cases[] = {
      {"pill bottom below the screen", 52, 272},       {"pill bottom far below (the audit's file)", 52, 65535},
      {"pill top below its bottom", 50, 300},          {"category pill starts past the edge", 54, 792},
      {"item pill ends past the edge", 58, 65534},     {"item pill starts after it ends", 56, 791},
      {"category pill wider than the screen", 64 + 8, 790},
  };
  for (const auto &c : cases) {
    auto bad = good;
    put16(bad, c.at, c.value);
    fix_crc(bad);
    CHECK(epf::parse_stream(bad.data(), bad.size(), 792, 272, s) == epf::FetchResult::ERROR_LAYOUT, "refused: %s",
          c.what);
  }
  auto both = good;                                   // the audit's 25-second overlay
  put16(both, 52, 65535);
  put16(both, 58, 65534);
  fix_crc(both);
  CHECK(epf::parse_stream(both.data(), both.size(), 792, 272, s) == epf::FetchResult::ERROR_LAYOUT,
        "pill_y1=65535, sub_x1=65534 refused");
}

// The frame parser against mutated files (bounded, fixed seed, so it's the same
// run every time). Built with AddressSanitizer and UndefinedBehaviorSanitizer
// where the compiler has them (tests/test_firmware.py). Whatever parses must
// keep its footer on the screen and draw its overlays quickly.
static void test_fuzz_parser(const std::string &dir) {
  uint32_t seed = 0x2545F491u;
  auto rnd = [&]() { seed ^= seed << 13; seed ^= seed >> 17; seed ^= seed << 5; return seed; };
  std::vector<std::vector<uint8_t>> bases;
  for (const char *name : {"orient0", "orient1", "orient2", "orient3", "nav_a", "nav_b", "legacy180", "nav_alert"})
    bases.push_back(read_file(dir + "/" + name + ".epf"));
  std::vector<uint8_t> screen((size_t) 99 * 272);
  int parsed = 0;
  double slowest_ms = 0;
  for (int i = 0; i < 6000; i++) {
    auto buf = bases[rnd() % bases.size()];
    int edits = 1 + (int) (rnd() % 4);
    for (int e = 0; e < edits; e++) {
      // Mostly the header, geometry and directory, where the numbers are.
      size_t span = (rnd() % 4) ? std::min<size_t>(buf.size() - 4, 64 + 16 * 8) : buf.size() - 4;
      size_t at = rnd() % span;
      switch (rnd() % 3) {
        case 0: buf[at] = (uint8_t) rnd(); break;
        case 1: buf[at] ^= (uint8_t) (1u << (rnd() % 8)); break;
        default: buf[at] = (rnd() & 1) ? 0xFF : 0x00; break;
      }
    }
    if (rnd() % 8) fix_crc(buf);                      // most get past the checksum
    if (rnd() % 16 == 0) buf.resize(rnd() % buf.size());
    epf::Stream s;
    if (epf::parse_stream(buf.data(), buf.size(), 792, 272, s) != epf::FetchResult::OK) continue;
    parsed++;
    const auto &g = s.geometry;
    CHECK(g.pill_y1 < g.logical_h && g.sub_x1 < g.logical_w && g.cat_x0 < g.logical_w, "fuzz %d: footer inside", i);
    for (const auto &c : s.categories) {
      epf::OverlayState st;
      st.cat_pill_w = c.pill_width;
      st.has_sub = true;
      st.cat_locked = st.panel_locked = true;
      for (bool sub : {false, true}) {
        st.highlight_sub = sub;
        auto t0 = std::chrono::steady_clock::now();
        epf::draw_overlays(screen.data(), 792, 272, g, st);
        double ms = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t0).count();
        if (ms > slowest_ms) slowest_ms = ms;
      }
    }
  }
  CHECK(parsed > 100, "the fuzzer reached the overlays (%d files parsed)", parsed);
  CHECK(slowest_ms < 250, "the slowest overlay took %.1f ms", slowest_ms);
}

// Navigation keeps the reader's place and locks across new frame files.
static void test_controller(const std::string &dir) {
  auto &pc = epf::PanelController::instance();
  epf::Stream a, b, alert;
  auto fa = read_file(dir + "/nav_a.epf"), fb = read_file(dir + "/nav_b.epf"), fal = read_file(dir + "/nav_alert.epf");
  CHECK(epf::parse_stream(fa.data(), fa.size(), 792, 272, a) == epf::FetchResult::OK, "nav_a");
  CHECK(epf::parse_stream(fb.data(), fb.size(), 792, 272, b) == epf::FetchResult::OK, "nav_b");
  CHECK(epf::parse_stream(fal.data(), fal.size(), 792, 272, alert) == epf::FetchResult::OK, "nav_alert");

  using A = epf::NavAction;
  pc.on_stream_loaded(a);           // solar, sports(3), temps
  pc.dispatch(A::NEXT);             // -> sports
  pc.dispatch(A::MODE_TOGGLE);      // into its items
  pc.step(1);                       // second match (Home Assistant's page_step)
  CHECK(pc.cat_idx() == 1 && pc.sub_idx() == 1, "on sports 2/3 (cat %d sub %d)", pc.cat_idx(), pc.sub_idx());
  pc.dispatch(A::LOCK_TOGGLE);      // in item mode: lock this match

  pc.on_stream_loaded(b);  // a new category was inserted before sports
  CHECK(pc.pinned() && pc.cat_idx() == 2 && pc.sub_idx() == 1, "lock follows the match (cat %d sub %d)",
        pc.cat_idx(), pc.sub_idx());

  pc.on_stream_loaded(alert);  // an alert takes over...
  CHECK(pc.page() == 0, "alert shows page 0");
  CHECK(!pc.overlay_state().panel_locked, "no padlock drawn over an alert");
  pc.dispatch(A::NEXT);         // ...someone presses a button during it...
  pc.on_stream_loaded(b);      // ...and when it's over the lock is still there
  CHECK(pc.pinned() && pc.cat_idx() == 2 && pc.sub_idx() == 1, "lock survives an alert (cat %d sub %d)",
        pc.cat_idx(), pc.sub_idx());
}

// The waveform policy: no flash from a person, the clear rides on the next
// automatic change, the fallback, forced clears, and the classic revert.
static void test_waveform() {
  epf::WaveformPolicy w;
  w.set_threshold(10);
  for (int i = 0; i < 25; i++)
    CHECK(!w.decide(false, true, false, 0), "a press is never a full refresh (#%d)", i);
  CHECK(w.partials() == 25, "partials counted (%d)", w.partials());
  CHECK(!w.decide(false, false, true, 3), "not right after someone stopped scrolling");
  CHECK(w.decide(false, false, true, 20), "the next automatic change carries the clear");
  CHECK(w.partials() == 0, "count resets after a full refresh");
  for (int i = 0; i < 5; i++) w.decide(false, false, true, 999);
  CHECK(!w.decide(false, false, true, 999), "below the threshold, automatic stays partial");
  CHECK(!w.decide(false, true, true, 999), "a press and an automatic change together: the press wins");
  CHECK(w.decide(true, true, false, 0), "a forced clear (alert, button) is always full");

  for (int i = 0; i < 30; i++) w.decide(false, true, false, 0);
  CHECK(!w.idle_clear_due(59) && w.idle_clear_due(60), "fallback after a minute still, with 3x built up");

  epf::WaveformPolicy c;
  c.set_threshold(10);
  c.set_classic(true);
  int fulls = 0;
  for (int i = 0; i < 30; i++) fulls += c.decide(false, true, false, 0);
  CHECK(fulls == 3, "classic: every 10th refresh is full, scrolling or not (%d)", fulls);
  CHECK(!c.idle_clear_due(999), "classic has no idle fallback");

  // Asleep between updates, TRMNL's way: partial after a wake, every 8th change full,
  // counted across wakes (in RTC memory).
  epf::WaveformPolicy s;
  uint32_t changes = 0;
  s.sleep_between(&changes, 15 * 60);
  int full_at = -1;
  for (int i = 0; i < 8; i++)
    if (s.decide(false, false, true, 999)) { full_at = i; break; }
  CHECK(full_at == 7 && changes == 0, "asleep: the 8th change is full (at %d)", full_at);
  epf::WaveformPolicy after_wake;                     // a new start: only the RTC count is left
  after_wake.sleep_between(&changes, 15 * 60);
  for (int i = 0; i < 5; i++) after_wake.decide(false, false, true, 999);
  CHECK(changes == 5, "counted across wakes (%u)", (unsigned) changes);
  for (int i = 0; i < 20; i++)
    CHECK(!after_wake.decide(false, true, false, 0), "asleep: a press is still never a full refresh (#%d)", i);
  CHECK(after_wake.decide(false, false, true, 999) && changes == 0, "the next change of its own carries the full one");
  CHECK(after_wake.decide(true, true, false, 0), "asleep: a forced clear is full");
  after_wake.sleep_between(&changes, 30 * 60);
  CHECK(after_wake.decide(false, false, true, 999), "30 min or more between checks: every change of its own is full");
  CHECK(!after_wake.decide(false, true, false, 0), "...but a press stays partial");
  after_wake.sleep_between(nullptr, 0);
  CHECK(!after_wake.sleeps_between(), "back to always on");

  // Through the controller: quiet hours starting forces one full refresh.
  auto &pc = epf::PanelController::instance();
  pc.waveform().set_classic(false);
  epf::Stream q;
  q.header.page_count = 1;
  q.header.flags = epf::FLAG_QUIET_HOURS;
  q.categories.push_back({1, 0, 1, 50, 0});
  q.pages.push_back({1, 1, 0, 0});
  pc.on_stream_loaded(q);
  CHECK(pc.begin_redraw(), "quiet hours starting: one full refresh");
  pc.on_stream_loaded(q);
  CHECK(!pc.begin_redraw(), "...and not again while they last");
  pc.dispatch(epf::NavAction::CLEAR_GHOSTING);
  CHECK(pc.begin_redraw(), "the Clear ghosting button is a full refresh");
}

// The sleep state: the file always carries a sleep screen (category 0); the
// dial never lands on it; holding the centre or quiet hours put the panel to
// sleep; the first press only wakes it; a lock wins over quiet hours.
static epf::Stream sleep_stream(bool quiet, uint32_t sleep_text_id = 7100) {
  epf::Stream s;
  s.header.page_count = 3;
  s.header.flags = quiet ? epf::FLAG_QUIET_HOURS : 0;
  uint16_t f = epf::CAT_FLAG_SLEEP | (quiet ? epf::CAT_FLAG_SLEEP_AUTO : 0);
  s.categories.push_back({7000, 0, 1, 0, f});
  s.categories.push_back({7001, 1, 1, 100, 0});
  s.categories.push_back({7002, 2, 1, 100, 0});
  s.pages = {{sleep_text_id, 7000, 0, 0}, {7101, 7001, 1, 0}, {7102, 7002, 2, 0}};
  return s;
}

static void test_sleep() {
  auto &pc = epf::PanelController::instance();
  using A = epf::NavAction;
  epf::Stream day = sleep_stream(false), night = sleep_stream(true, 7199);
  if (pc.pinned()) pc.dispatch(A::PIN_PAGE_TOGGLE);
  if (pc.cat_pinned()) pc.dispatch(A::PIN_CAT_TOGGLE);
  if (pc.sleeping()) pc.dispatch(A::WAKE);

  pc.on_stream_loaded(day);
  pc.dispatch(A::RESET_HOME);
  CHECK(pc.page() == 1, "home is the first real page, not the sleep screen (page %d)", pc.page());
  pc.dispatch(A::PREV);
  CHECK(pc.page() == 2, "the dial skips the sleep screen backwards (page %d)", pc.page());
  pc.dispatch(A::NEXT);
  CHECK(pc.page() == 1, "...and forwards (page %d)", pc.page());
  pc.dispatch(A::GOTO_PAGE, 0);
  CHECK(pc.page() == 1, "show_page(0) is still your first page (page %d)", pc.page());

  // Held centre during the day.
  pc.dispatch(A::GOTO_PAGE, 1);
  pc.dispatch(A::SLEEP_TOGGLE);
  CHECK(pc.sleeping() && pc.page() == 0, "holding the centre sleeps");
  CHECK(pc.begin_redraw(), "going to sleep is one clean full refresh");
  CHECK(!pc.check_auto_rotate(), "no rotation while asleep");
  CHECK(pc.resting(), "no timed downloads while asleep");
  pc.on_stream_loaded(day);
  CHECK(!pc.pending_redraw(), "new frames with the same sleep screen: nothing redrawn");
  pc.dispatch(A::NEXT);
  CHECK(!pc.sleeping() && pc.page() == 2, "the first press only wakes, back to where you were (page %d)", pc.page());
  CHECK(pc.take_wake_fetch() && !pc.take_wake_fetch(), "waking asks for fresh frames once");

  // Quiet hours.
  pc.on_stream_loaded(night);
  CHECK(pc.sleeping() && pc.page() == 0, "quiet hours put the panel to sleep");
  pc.dispatch(A::NEXT);
  CHECK(!pc.sleeping() && pc.page() == 2, "a press wakes it (page %d)", pc.page());
  for (int t = 0; t < epf::SLEEP_RETURN_SEC - 5; t += 5) pc.tick_seconds(5);
  CHECK(!pc.check_auto_rotate() && !pc.sleeping(), "not back to sleep too early");
  pc.tick_seconds(10);
  CHECK(pc.check_auto_rotate() && pc.sleeping(), "back to sleep after two untouched minutes");
  pc.on_stream_loaded(day);
  CHECK(!pc.sleeping() && pc.page() == 2, "morning wakes it (page %d)", pc.page());

  // Woken from Home Assistant during quiet hours: the same two minutes as a press.
  pc.on_stream_loaded(night);
  CHECK(pc.sleeping(), "quiet hours again");
  for (int t = 0; t < 300; t += 5) pc.tick_seconds(5);     // nobody has touched it for a while
  pc.remote(A::WAKE);
  CHECK(!pc.sleeping(), "Home Assistant wakes it");
  pc.tick_seconds(5);
  CHECK(!pc.check_auto_rotate() && !pc.sleeping(), "not straight back to sleep");
  for (int t = 5; t < epf::SLEEP_RETURN_SEC - 5; t += 5) pc.tick_seconds(5);
  CHECK(!pc.check_auto_rotate() && !pc.sleeping(), "awake for nearly two minutes");
  pc.tick_seconds(10);
  CHECK(pc.check_auto_rotate() && pc.sleeping(), "then back to sleep");
  pc.on_stream_loaded(day);

  // A manual sleep outlasts the night.
  pc.on_stream_loaded(night);
  pc.dispatch(A::WAKE);
  pc.dispatch(A::SLEEP);
  pc.on_stream_loaded(day);
  CHECK(pc.sleeping(), "a manual sleep isn't ended by the morning");
  CHECK(pc.pending_redraw(), "...but its sleep screen text changed, so it's redrawn");
  pc.dispatch(A::WAKE);

  // A lock wins over quiet hours.
  pc.dispatch(A::GOTO_PAGE, 1);
  pc.dispatch(A::PIN_PAGE_TOGGLE);
  pc.on_stream_loaded(night);
  CHECK(!pc.sleeping() && pc.page() == 2, "a locked page stays up overnight (page %d)", pc.page());
  pc.dispatch(A::PIN_PAGE_TOGGLE);
}

static epf::Stream alert_stream() {
  epf::Stream s;
  s.header.page_count = 1;
  s.header.flags = epf::FLAG_ALERT_INTERRUPT;
  s.categories.push_back({7900, 0, 1, 100, 0});
  s.pages = {{7901, 7900, 0, 0}};
  return s;
}

// Audit 2026-10-19: Home Assistant commands, alerts over sleep, retries while
// resting, and huge steps.
static void test_remote_alerts_and_fetches() {
  auto &pc = epf::PanelController::instance();
  using A = epf::NavAction;
  epf::Stream day = sleep_stream(false), night = sleep_stream(true, 7199);
  if (pc.pinned()) pc.dispatch(A::PIN_PAGE_TOGGLE);
  if (pc.cat_pinned()) pc.dispatch(A::PIN_CAT_TOGGLE);
  if (pc.sleeping()) pc.dispatch(A::WAKE);
  pc.on_stream_loaded(day);

  // Home Assistant while asleep: wakes and goes where it was asked.
  pc.dispatch(A::SLEEP);
  pc.tick_seconds(30);
  pc.remote(A::GOTO_PAGE, 1);
  CHECK(!pc.sleeping() && pc.page() == 2, "show_page while asleep wakes and goes to the page (page %d)", pc.page());
  CHECK(!pc.should_defer_refetch(), "a Home Assistant command isn't a person at the panel");

  // Asleep by hand, an alert comes and goes: back to sleep.
  pc.dispatch(A::SLEEP);
  pc.on_stream_loaded(alert_stream());
  CHECK(!pc.sleeping(), "the alert shows over sleep");
  pc.on_stream_loaded(day);
  CHECK(pc.sleeping(), "after the alert the panel goes back to sleep");
  // ...unless someone pressed a button during the alert.
  pc.on_stream_loaded(alert_stream());
  pc.dispatch(A::NEXT);
  pc.on_stream_loaded(day);
  CHECK(!pc.sleeping(), "a press during the alert leaves it awake");

  // A failed download while resting is retried, with a backoff.
  pc.on_stream_loaded(night);
  CHECK(pc.sleeping() && pc.resting(), "quiet hours: asleep and resting");
  pc.reset_fetch_idle();
  pc.tick_seconds(600);
  CHECK(!pc.fetch_due(60), "resting: no timed downloads");
  pc.note_fetch(false);
  pc.tick_seconds(25);
  CHECK(!pc.fetch_due(60), "a failed download isn't retried at once");
  pc.tick_seconds(10);
  CHECK(pc.fetch_due(60), "a failed download is retried while resting");
  pc.reset_fetch_idle();
  pc.note_fetch(false);
  pc.tick_seconds(35);
  CHECK(!pc.fetch_due(3600), "the second retry waits longer");
  pc.tick_seconds(30);
  CHECK(pc.fetch_due(3600), "...60 s");
  pc.note_fetch(true);
  pc.tick_seconds(600);
  CHECK(!pc.fetch_due(60), "once a download works, resting means no timed downloads again");
  pc.dispatch(A::WAKE);

  // A huge step costs nothing.
  auto t0 = std::chrono::steady_clock::now();
  pc.step(2000000000);
  pc.step(-2147483647 - 1);
  double ms = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t0).count();
  CHECK(ms < 5, "page_step(2,000,000,000) took %.1f ms", ms);
}

// Low Power Mode: the add-on's answer decides whether and how long the panel sleeps.
static void test_power() {
  using epf::PowerPolicy;
  using epf::Wake;
  epf::SleepOrder o;

  // The header, and anything else is ignored.
  CHECK(epf::parse_sleep_order("900; awake=60", o) && o.sleep_sec == 900 && o.awake_sec == 60, "the header");
  CHECK(epf::parse_sleep_order(" 900 ", o) && o.sleep_sec == 900 && o.awake_sec == 0, "awake is optional");
  CHECK(epf::parse_sleep_order("900;awake=600", o) && o.awake_sec == 600, "no spaces");
  CHECK(epf::parse_sleep_order("5; awake=0", o) && o.sleep_sec == epf::MIN_SLEEP_SEC, "never a wake loop");
  CHECK(epf::parse_sleep_order("999999; awake=99999", o) && o.sleep_sec == epf::MAX_SLEEP_SEC &&
            o.awake_sec == epf::MAX_AWAKE_SEC, "capped");
  for (const char *bad : {"", "abc", "900 seconds", "900; sleep=5", "-5", "900; awake=", "99999999999", "900;"})
    CHECK(!epf::parse_sleep_order(bad, o), "refused: \"%s\"", bad);
  CHECK(!epf::parse_sleep_order(nullptr, o), "no header");

  auto &p = PowerPolicy::instance();
  epf::Remembered mem{};
  epf::SleepOrder timer{900, 0}, press{900, 60}, stay{900, 600};

  // A fresh start that's never told to sleep stays connected, whatever happens.
  p.begin(Wake::BOOT, mem, 0);
  p.on_answer(200, false, o, 1000);
  CHECK(!p.low_power() && !p.sleep_due(999999, false), "no header: stays connected");
  p.on_answer(0, false, o, 2000);
  CHECK(!p.sleep_due(999999, false), "never told to sleep: a failed download doesn't make it sleep");

  // Told to sleep on a timer wake: draw, then sleep at once, for what's left.
  p.on_answer(200, true, timer, 10000);
  CHECK(p.sleep_due(10000, false), "awake=0: sleeps as soon as it's done");
  CHECK(!p.sleep_due(10000, true), "...not while it's still drawing");
  CHECK(p.sleep_ms(14000) == 896000, "counted from the answer (%u)", (unsigned) p.sleep_ms(14000));
  CHECK(mem.interval_sec == 900, "remembered for a wake that can't reach the add-on");
  p.hold(true);
  CHECK(!p.sleep_due(20000, false), "never in the middle of an update");
  p.hold(false);

  // A press keeps it awake a minute after the last press.
  p.on_answer(200, true, press, 0);
  CHECK(!p.sleep_due(59000, false) && p.sleep_due(60000, false), "awake=60 after the download");
  p.note_press(50000);
  CHECK(!p.sleep_due(100000, false) && p.sleep_due(110000, false), "a minute after the last press");
  CHECK(p.sleep_ms(110000) == 790000, "less the time awake (%u)", (unsigned) p.sleep_ms(110000));

  // Asked to stay awake for an update: the same field.
  p.on_answer(200, true, stay, 200000);
  CHECK(!p.sleep_due(799000, false) && p.sleep_due(800000, false), "ten minutes awake");
  CHECK(p.sleep_ms(800000) == 300000, "then the rest of the interval");
  CHECK(p.sleep_ms(2000000) == epf::MIN_SLEEP_SEC * 1000u, "never less than the minimum");

  // Low Power Mode turned off in the editor: the next answer has no header.
  p.on_answer(200, false, o, 900000);
  CHECK(!p.low_power() && !p.sleep_due(9000000, false) && mem.interval_sec == 0, "off: stays connected");

  // A timer wake that can't reach the add-on sleeps and tries again, backing off.
  mem.interval_sec = 900;
  mem.failures = 0;
  uint32_t expect[] = {60, 120, 240, 480, 600, 600};
  for (uint32_t want : expect) {
    p.begin(Wake::TIMER, mem, 900000);
    p.on_answer(0, false, o, 5000);
    CHECK(p.low_power() && p.sleep_due(5000, false), "no answer on a timer wake: sleeps");
    CHECK(p.sleep_ms(5000) == want * 1000u, "retry after %u s (got %u)", (unsigned) want, (unsigned) (p.sleep_ms(5000) / 1000));
  }
  mem.interval_sec = 300;
  p.begin(Wake::TIMER, mem, 900000);
  p.on_answer(0, false, o, 0);
  CHECK(p.sleep_ms(0) == 300000, "never longer than its interval");
  p.on_answer(200, true, timer, 1000);
  CHECK(mem.failures == 0, "an answer ends the backoff");
  p.begin(Wake::BUTTON, mem, 900000);
  p.on_answer(0, false, o, 0);
  CHECK(!p.sleep_due(59000, false) && p.sleep_due(60000, false), "a press that can't reach it: awake a minute");
  p.begin(Wake::TIMER, mem, 900000);
  p.on_answer(200, true, timer, 0);
  p.on_answer(0, false, o, 500);
  CHECK(p.sleep_ms(500) == 899500, "a later failure in the same wake keeps the answer it had");

  // Only the add-on's own answer (200 or 304) without the header means "stay connected".
  // Home Assistant's 502 while the add-on restarts, a tunnel's 5xx, a 401 or a 429
  // count as no answer: it sleeps and tries again (break-it #4).
  for (int status : {502, 503, 500, 404, 401, 429, 302}) {
    mem.interval_sec = 900;
    mem.failures = 0;
    p.begin(Wake::TIMER, mem, 900000);
    p.on_answer(status, false, o, 5000);
    CHECK(p.low_power() && p.sleep_due(5000, false) && p.sleep_ms(5000) == 60000u,
          "HTTP %d without the header: sleeps and retries in 60 s", status);
    CHECK(mem.interval_sec == 900 && mem.failures == 1, "HTTP %d: still in Low Power Mode, one failure", status);
  }
  mem.interval_sec = 900;
  p.begin(Wake::TIMER, mem, 900000);
  p.on_answer(304, false, o, 0);
  CHECK(!p.low_power() && mem.interval_sec == 0, "a 304 without the header: Low Power Mode is off");
  mem.interval_sec = 900;
  p.begin(Wake::TIMER, mem, 900000);
  p.on_answer(503, true, timer, 0);
  CHECK(p.low_power() && p.sleep_ms(0) == 900000u && mem.failures == 0, "a sleep order is obeyed whatever the status");
  mem.interval_sec = 900;
  p.begin(Wake::BUTTON, mem, 900000);
  p.on_answer(502, false, o, 0);
  CHECK(!p.sleep_due(59000, false) && p.sleep_due(60000, false), "a press during a restart: awake a minute, then sleeps");

  // The panel's own refresh timer is off while the add-on decides when it wakes (break-it #1, #10).
  auto &panel = epf::PanelController::instance();
  panel.note_fetch(false);                            // owed, so it's due even if resting
  panel.tick_seconds(900);
  CHECK(panel.fetch_due(300), "a download is due");
  p.begin(Wake::BOOT, mem, 0);
  p.on_answer(200, false, o, 0);
  CHECK(epf::own_timer_fetch_due(panel, p, 300, 0), "connected: its own timer downloads");
  p.on_answer(200, true, press, 0);
  CHECK(!epf::own_timer_fetch_due(panel, p, 300, 0), "Low Power Mode: its own timer is off");
  panel.note_fetch(true);

  // The picture kept through deep sleep (TRMNL's way), and which refresh policy applies.
  epf::WaveformPolicy wf;
  mem.interval_sec = 900;
  p.begin(Wake::TIMER, mem, 900000);
  p.before_sleep(1000, true);
  p.begin(Wake::TIMER, mem, 900000);
  CHECK(p.picture_kept() && mem.picture_kept == 0, "slept with the display powered: the picture is kept");
  epf::choose_waveform(wf, p, mem);
  CHECK(wf.sleeps_between(), "woke from Low Power Mode: the sleeping policy before any answer");
  p.on_answer(200, true, timer, 0);
  epf::choose_waveform(wf, p, mem);
  CHECK(wf.sleeps_between(), "told to sleep again: still the sleeping policy");
  CHECK(p.take_first_refresh(), "the first picture after it drives every pixel: the display's memory is gone");
  CHECK(!p.take_first_refresh(), "only the first: the display keeps its memory from then on");
  p.before_sleep(2000, false);
  p.begin(Wake::BUTTON, mem, 900000);
  CHECK(!p.picture_kept(), "slept with the display switched off: nothing kept");
  CHECK(!p.take_first_refresh(), "switched off: its driver refreshes in full first, nothing to drive");
  p.before_sleep(3000, true);
  p.begin(Wake::BOOT, mem, 0);
  CHECK(!p.picture_kept(), "a power cut or reset never trusts the display's memory");
  CHECK(!p.take_first_refresh(), "a fresh start refreshes in full first");
  epf::choose_waveform(wf, p, mem);
  CHECK(!wf.sleeps_between(), "a fresh start is always on until told to sleep");
  p.on_answer(200, true, timer, 0);
  epf::choose_waveform(wf, p, mem);
  CHECK(wf.sleeps_between(), "told to sleep: the sleeping policy");
  p.on_answer(200, false, o, 0);
  epf::choose_waveform(wf, p, mem);
  CHECK(!wf.sleeps_between(), "Low Power Mode turned off: the always-on policy, exactly as before");

  // A power cut or a reset is a fresh start.
  p.begin(Wake::BOOT, mem, 0);
  CHECK(mem.interval_sec == 0 && mem.magic == epf::REMEMBERED_MAGIC, "after a reset it stays connected until told");

  // Floating button pins wake it the moment it sleeps: after three, the timer only.
  mem.interval_sec = 900;
  for (int i = 0; i < 3; i++) p.begin(Wake::BUTTON, mem, 300);
  CHECK(!p.buttons_wake(), "three instant button wakes: the buttons stop waking it");
  p.begin(Wake::TIMER, mem, 900000);
  CHECK(p.buttons_wake(), "the next timer wake tries them again");
  p.begin(Wake::BUTTON, mem, 300);
  p.begin(Wake::BUTTON, mem, 45000);
  p.begin(Wake::BUTTON, mem, 300);
  CHECK(p.buttons_wake(), "a real press in between resets the count");
  CHECK(std::string(epf::wake_name(Wake::TIMER)) == "timer" && std::string(epf::wake_name(Wake::BUTTON)) == "button" &&
            std::string(epf::wake_name(Wake::BOOT)) == "boot", "what it tells the add-on");
}

// Always on: the add-on's answer says when the next timed download starts (X-EPF-Next), a
// moment after its render each minute, so the clock on the page is right within seconds.
static void test_aligned_fetches() {
  auto &panel = epf::PanelController::instance();
  auto &p = epf::PowerPolicy::instance();
  using epf::Wake;
  static epf::Remembered mem{};                       // the policy keeps a pointer to it
  epf::SleepOrder none;
  p.begin(Wake::BOOT, mem, 0);
  p.on_answer(200, false, none, 0);
  if (panel.sleeping()) panel.dispatch(epf::NavAction::WAKE);
  panel.on_stream_loaded(sleep_stream(false));
  panel.note_fetch(true);
  CHECK(!panel.resting(), "awake, outside quiet hours");

  uint32_t ms = 0;
  CHECK(epf::parse_next_fetch("44000", ms) && ms == 44000, "milliseconds");
  CHECK(epf::parse_next_fetch(" 60500 ", ms) && ms == 60500, "spaces allowed");
  CHECK(epf::parse_next_fetch("0", ms) && ms == epf::MIN_NEXT_FETCH_MS, "never a download loop");
  CHECK(epf::parse_next_fetch("99999999999", ms) == false, "too large to be a number it takes");
  CHECK(epf::parse_next_fetch("86400000", ms) && ms == epf::MAX_NEXT_FETCH_MS, "an hour at most");
  CHECK(!epf::parse_next_fetch("", ms) && !epf::parse_next_fetch("soon", ms) && !epf::parse_next_fetch("5 s", ms) &&
            !epf::parse_next_fetch("-5", ms) && !epf::parse_next_fetch(nullptr, ms), "anything else is ignored");

  // It booted and fetched at once (10:00:19); the answer says 44 s: 10:01:03, after the render.
  const uint32_t boot = 4000000000u;                  // near millis()' wrap: differences still hold
  panel.reset_fetch_idle();
  panel.aim_fetch(44000, boot);
  panel.tick_seconds(40);
  CHECK(!epf::own_timer_fetch_due(panel, p, 60, boot + 43999), "not before the time it was given");
  panel.tick_seconds(5);
  CHECK(!epf::own_timer_fetch_due(panel, p, 60, boot + 43999),
        "its interval counting from the last download (45 s here) no longer decides... ");
  panel.tick_seconds(20);
  CHECK(!epf::own_timer_fetch_due(panel, p, 60, boot + 43999), "...even past a whole interval");
  CHECK(epf::own_timer_fetch_due(panel, p, 60, boot + 44000), "at the time it was given");
  panel.reset_fetch_idle();                            // the download starts
  CHECK(!panel.fetch_aimed(), "a download starting uses the hint up");

  // The next answer comes back a second later, aimed a minute on: every fetch lands just after a render.
  panel.aim_fetch(59000, boot + 45000);
  CHECK(!epf::own_timer_fetch_due(panel, p, 60, boot + 103999) && epf::own_timer_fetch_due(panel, p, 60, boot + 104000),
        "a minute after the last, to the millisecond");

  // A press, Send or an alert fetches at once, unaligned; that answer's hint realigns.
  panel.reset_fetch_idle();
  CHECK(!epf::own_timer_fetch_due(panel, p, 60, boot + 110000), "a fetch out of turn starts the count again");
  panel.aim_fetch(13000, boot + 111000);
  CHECK(epf::own_timer_fetch_due(panel, p, 60, boot + 124000), "realigned: the next minute's render, not a minute on");

  // An add-on that doesn't send it: every interval from the last download, as before.
  panel.reset_fetch_idle();
  panel.tick_seconds(55);
  CHECK(!epf::own_timer_fetch_due(panel, p, 60, 0), "no hint: the interval...");
  panel.tick_seconds(5);
  CHECK(epf::own_timer_fetch_due(panel, p, 60, 0), "...counted from the last download");

  // A failed download is retried with its backoff, whatever the last hint said.
  panel.reset_fetch_idle();
  panel.aim_fetch(3600000, boot);
  panel.note_fetch(false);
  panel.tick_seconds(30);
  CHECK(epf::own_timer_fetch_due(panel, p, 60, boot + 30000), "owed: retried after 30 s");
  panel.note_fetch(true);

  // Resting (asleep, quiet hours): no timed downloads, hint or not.
  panel.reset_fetch_idle();
  panel.aim_fetch(5000, boot);
  panel.dispatch(epf::NavAction::SLEEP);
  CHECK(!epf::own_timer_fetch_due(panel, p, 60, boot + 600000), "asleep: it waits for the add-on or a press");
  panel.dispatch(epf::NavAction::WAKE);
  CHECK(epf::own_timer_fetch_due(panel, p, 60, boot + 600000), "awake again: the time it was given has passed");

  // Low Power Mode: the add-on's sleep order decides, never the hint.
  epf::SleepOrder order;
  order.sleep_sec = 900;
  p.on_answer(200, true, order, 0);
  CHECK(!epf::own_timer_fetch_due(panel, p, 60, boot + 600000), "sleeping between updates: its own timer is off");
  p.on_answer(200, false, none, 0);
  panel.reset_fetch_idle();
}

// The first refresh after a deep sleep drives every pixel: the previous-picture memory gets the
// new picture inverted, in each controller's share of a row, as its driver sends the picture.
static void test_drive_every_pixel() {
  // One controller (the 4.2", the 2.9"): the whole row.
  auto one = epf::row_share(50, 1, 0);
  CHECK(one.first == 0 && one.count == 50, "one controller: the whole row");
  // The 5.79": 99 bytes a row, two controllers overlapping by a byte (its driver: 0..49, 49..98).
  auto left = epf::row_share(99, 2, 0), right = epf::row_share(99, 2, 1);
  CHECK(left.first == 0 && left.count == 50, "cascade: left half from byte 0, %zu bytes", left.count);
  CHECK(right.first == 49 && right.count == 50, "cascade: right half from byte %zu", right.first);
  CHECK(right.count - 1 == 0x31, "the second controller's X counter starts at its driver's 0x31");
  auto even = epf::row_share(100, 2, 1);
  CHECK(even.first == 50 && even.count == 50, "an even row splits without overlap");

  // Every byte inverted, in order, row by row: every pixel reads as changing.
  const size_t row_bytes = 99, rows = 3;
  std::vector<uint8_t> picture(row_bytes * rows);
  for (size_t i = 0; i < picture.size(); i++) picture[i] = (uint8_t) (i * 37 + 11);
  for (int c = 0; c < 2; c++) {
    auto share = epf::row_share(row_bytes, 2, c);
    std::vector<uint8_t> sent;
    epf::send_inverted_share(picture.data(), row_bytes, rows, share, [&](uint8_t b) { sent.push_back(b); });
    CHECK(sent.size() == share.count * rows, "controller %d: %zu bytes sent", c, sent.size());
    bool ok = true;
    for (size_t r = 0; r < rows; r++)
      for (size_t x = 0; x < share.count; x++)
        ok = ok && sent[r * share.count + x] == (uint8_t) ~picture[r * row_bytes + share.first + x];
    CHECK(ok, "controller %d: each byte of its share, inverted, in the driver's order", c);
  }
  // White (0xFF) where it stays white reads as black before: driven white again, never left as it was.
  uint8_t white = 0xFF;
  std::vector<uint8_t> sent;
  epf::send_inverted_share(&white, 1, 1, epf::row_share(1, 1, 0), [&](uint8_t b) { sent.push_back(b); });
  CHECK(sent.size() == 1 && sent[0] == 0x00, "a white byte's previous picture is black");
}

// Deflated pages (FLAG_DEFLATE): the server's own file loads, each page inflates to exactly the
// pixels of the same page sent as it is, and a page that lies about its length is refused.
static void test_deflated_pages(const std::string &dir) {
  auto deflated = read_file(dir + "/deflated.epf"), as_is = read_file(dir + "/as_is.epf");
  epf::Stream d, r;
  CHECK(epf::parse_stream(deflated.data(), deflated.size(), 800, 480, d) == epf::FetchResult::OK, "deflated file loads");
  CHECK(epf::parse_stream(as_is.data(), as_is.size(), 800, 480, r) == epf::FetchResult::OK, "the same pages as they are");
  CHECK(d.header.flags & epf::FLAG_DEFLATE, "flagged");
  CHECK(deflated.size() * 4 < as_is.size(), "a page of words is far smaller deflated: %zu vs %zu", deflated.size(),
        as_is.size());
  const size_t page_bytes = 100 * 480;
  std::vector<uint8_t> a(page_bytes), b(page_bytes);
  for (int p = 0; p < (int) d.pages.size(); p++) {
    CHECK(epf::page_pixels(d, deflated.data(), p, a.data(), inflate_zlib), "page %d inflates", p);
    CHECK(epf::page_pixels(r, as_is.data(), p, b.data(), nullptr), "page %d copies", p);
    CHECK(a == b, "page %d: the same pixels either way", p);
  }
  CHECK(!epf::page_pixels(d, deflated.data(), 0, a.data(), nullptr), "no inflater: not drawn, never garbage");
  CHECK(!epf::page_pixels(d, deflated.data(), 99, a.data(), inflate_zlib), "no such page");

  // The first page says it's a byte longer than it is: the lengths no longer add up.
  auto bad = deflated;
  size_t rec = epf::HEADER_SIZE + d.header.cat_count * epf::CAT_RECORD_SIZE + 12;
  uint32_t len = epf::be32(bad.data() + rec) + 1;
  for (int i = 0; i < 4; i++) bad[rec + i] = (uint8_t) (len >> (24 - 8 * i));
  fix_crc(bad);
  CHECK(epf::parse_stream(bad.data(), bad.size(), 800, 480, d) == epf::FetchResult::ERROR_LAYOUT, "lying page length");
}

// The moving window, as a conversation with the add-on's own files (window.Window, written by
// test_firmware.py for every place, item and show_page): the panel asks with window_query and
// loads what comes back, as the glue does.
struct AddOn {
  std::string dir, name;
  std::vector<int> wants;
  int downloads{0};
  std::vector<uint8_t> file;               // kept: the stream points into the last one, as the panel's buffer
  AddOn(const std::string &d, const std::string &n) : dir(d), name(n) {
    std::ifstream f(dir + "/" + name + ".wants");
    for (int w; f >> w;) wants.push_back(w);
  }
  static int number(const std::string &q, const char *key, int fallback) {
    size_t at = q.find(key);
    return at == std::string::npos ? fallback : std::atoi(q.c_str() + at + std::strlen(key));
  }
  epf::Stream answer(const std::string &q) {
    downloads++;
    int page = number(q, "&page=", -1), at = number(q, "&at=", 0), item = number(q, "&item=", 0);
    int n = (int) wants.size();
    at = ((at % n) + n) % n;
    item = ((item % wants[at]) + wants[at]) % wants[at];
    std::string path = page >= 0 ? dir + "/" + name + "_p_" + std::to_string(page) + ".epf"
                                 : dir + "/" + name + "_w_" + std::to_string(at) + "_" + std::to_string(item) + ".epf";
    file = read_file(path);
    epf::Stream s;
    CHECK(epf::parse_stream(file.data(), file.size(), 0, 0, s) == epf::FetchResult::OK, "%s parses", path.c_str());
    return s;
  }
  // What the glue does after a move: start any download the panel wants, and load its answer.
  void serve(epf::PanelController &pc) {
    for (int i = 0; i < 4 && pc.take_window_fetch(false); i++) pc.on_stream_loaded(answer(pc.window_query()));
  }
};

static void fresh_panel(epf::PanelController &pc) {
  using A = epf::NavAction;
  if (pc.pinned()) pc.dispatch(A::PIN_PAGE_TOGGLE);
  if (pc.cat_pinned()) pc.dispatch(A::PIN_CAT_TOGGLE);
  if (pc.sleeping()) pc.dispatch(A::WAKE);
  if (pc.sub_mode()) pc.dispatch(A::MODE_TOGGLE);
  pc.window_unanswered();
}

// One timed step of the rotation: the panel's own change, with nobody at it.
static bool rotate(epf::PanelController &pc, AddOn &addon) {
  pc.tick_seconds(30);
  bool moved = pc.check_auto_rotate();
  bool waited = pc.waiting_for_page();
  addon.serve(pc);
  return moved && !waited;
}

static void test_moving_window(const std::string &dir) {
  auto &pc = epf::PanelController::instance();
  using A = epf::NavAction;
  fresh_panel(pc);

  // 20 pages of one item, room for 10 at a time: the rotation never waits, every page shows in
  // order, and the next part comes in batches, not a download a page.
  AddOn wide(dir, "wide");
  pc.on_stream_loaded(wide.answer("&window=1"));   // a start: it says nothing of where it is
  CHECK(pc.window(), "a rotation too big to hold is a window");
  CHECK(pc.rotation_place() == 0 && pc.page_count() == 11, "the start of the rotation, the sleep screen and 10 pages (%d, %d)",
        pc.rotation_place(), pc.page_count());
  wide.downloads = 0;
  bool never_waited = true, in_order = true;
  for (int step = 1; step <= 40; step++) {
    never_waited &= rotate(pc, wide);
    in_order &= pc.rotation_place() == step % 20;
  }
  CHECK(never_waited, "timed rotation never waits for a download");
  CHECK(in_order, "every page in rotation order, none skipped");
  CHECK(wide.downloads > 0 && wide.downloads <= 12, "two laps of 20 pages in batches: %d downloads", wide.downloads);

  // A step past what it holds: asked for once, nothing changes until it arrives, then it shows
  // with the window around it again (the one before held for scrolling back).
  int here = pc.rotation_place(), page = pc.page();
  wide.downloads = 0;
  pc.step(12);
  CHECK(pc.waiting_for_page() && pc.page() == page && pc.rotation_place() == here, "asked, not moved yet");
  wide.serve(pc);
  CHECK(wide.downloads == 1, "one download for it: %d", wide.downloads);
  CHECK(pc.rotation_place() == (here + 12) % 20 && !pc.waiting_for_page(), "shown when it arrives (%d)", pc.rotation_place());
  int at = pc.rotation_place();
  pc.dispatch(A::PREV);
  CHECK(pc.rotation_place() == (at + 19) % 20 && !pc.waiting_for_page(), "the one before is held: no download");
  pc.dispatch(A::NEXT);
  wide.serve(pc);

  // Home Assistant's show_page counts every page of the rotation: the add-on finds it.
  pc.remote(A::GOTO_PAGE, 3);
  wide.serve(pc);
  CHECK(pc.rotation_place() == 3, "show_page(3) shows the rotation's fourth page (%d)", pc.rotation_place());
  pc.remote(A::GOTO_CAT_SUB, 4, 0);
  CHECK(pc.rotation_place() == 4 && !pc.waiting_for_page(), "show_category of a held page: no download");

  // A page with nine items, room for six pictures: a run of its items, and every item shows,
  // a visit at a time, with nothing left out.
  fresh_panel(pc);
  AddOn tall(dir, "tall");
  pc.on_stream_loaded(tall.answer("&window=1"));
  std::set<std::pair<int, int>> seen;
  bool tall_in_order = true;
  for (int step = 1; step <= 8 * 10; step++) {
    rotate(pc, tall);
    tall_in_order &= pc.rotation_place() == step % 8;
    seen.insert({pc.rotation_place(), pc.rotation_item()});
  }
  int all = 0;
  for (int w : tall.wants) all += w;
  CHECK(tall_in_order, "the rotation goes on in order past the page too big to hold");
  CHECK((int) seen.size() == all, "every item of every page shown: %zu of %d", seen.size(), all);

  // Stepping through the big page's items by hand: round the run, then the items past it.
  while (pc.rotation_place() != 5) rotate(pc, tall);
  pc.dispatch(A::MODE_TOGGLE);
  CHECK(pc.sub_mode(), "into its items");
  std::set<int> items;
  tall.downloads = 0;
  for (int k = 0; k < 9; k++) {
    items.insert(pc.rotation_item());
    pc.dispatch(A::NEXT);
    tall.serve(pc);
    CHECK(pc.rotation_place() == 5 && pc.sub_mode(), "still on its items (%d)", pc.rotation_place());
  }
  CHECK(items.size() == 9, "all nine items by hand: %zu", items.size());
  CHECK(tall.downloads >= 1 && tall.downloads <= 3, "the items past the run, asked for: %d downloads", tall.downloads);
  pc.dispatch(A::MODE_TOGGLE);

  // A download that brings nothing: the page asked for isn't coming, and it stays put.
  here = pc.rotation_place();
  pc.step(4);
  CHECK(pc.waiting_for_page(), "asked");
  CHECK(pc.take_window_fetch(true), "a page asked for is fetched even while drawing");
  pc.window_query();
  pc.window_unanswered();
  CHECK(!pc.waiting_for_page() && pc.rotation_place() == here, "nothing came: it stays");

  // The whole rotation in one file (everything fits): no window, no downloads of its own.
  epf::Stream whole = sleep_stream(false);
  pc.on_stream_loaded(whole);
  CHECK(!pc.window(), "a file without places is the whole rotation");
  for (int i = 0; i < 4; i++) {
    pc.dispatch(A::NEXT);
    pc.tick_seconds(30);
    pc.check_auto_rotate();
  }
  CHECK(!pc.take_window_fetch(false), "it never asks for more");
  CHECK(pc.window_query().find("&at=") != std::string::npos, "it still says where it is");
}

// A board without PSRAM keeps one buffer in its own RAM: what's left once a download has
// what it needs, in whole KB, and nothing when even one page wouldn't fit.
static void test_internal_capacity() {
  const size_t page = 800 / 8 * 480;          // the 7.5"
  const size_t most = 1048576;
  CHECK(epf::frame_file_size(1, page) == 64 + 16 + 16 + page + 4, "one page's file");
  size_t cap = epf::internal_capacity(200 * 1024, 180 * 1024, 80 * 1024, page, most);
  CHECK(cap == 120 * 1024, "what's free past the reserve: %zu", cap);
  CHECK(cap % 1024 == 0, "whole KB");
  cap = epf::internal_capacity(300 * 1024, 100 * 1024, 40 * 1024, page, most);
  CHECK(cap == 99 * 1024, "no more than the largest piece the heap can hand out: %zu", cap);
  CHECK(epf::internal_capacity(120 * 1024, 120 * 1024, 80 * 1024, page, most) == 0,
        "40 KB left: not one 7.5\" page, so none at all");
  CHECK(epf::internal_capacity(60 * 1024, 60 * 1024, 80 * 1024, page, most) == 0, "less free than the reserve");
  CHECK(epf::internal_capacity(4u << 20, 4u << 20, 40 * 1024, page, most) == most, "never more than the most");
  CHECK(epf::internal_capacity(200 * 1024, 512, 40 * 1024, page, most) == 0, "a heap in crumbs");
}

int main(int argc, char **argv) {
  if (argc < 2) {
    std::printf("usage: core_test <fixture-dir>\n");
    return 2;
  }
  test_streams_and_mapping(argv[1]);
  test_rejects_bad_files(argv[1]);
  test_footer_inside_the_screen(argv[1]);
  test_upright_panel(argv[1]);
  test_fuzz_parser(argv[1]);
  test_controller(argv[1]);
  test_waveform();
  test_sleep();
  test_remote_alerts_and_fetches();
  test_power();
  test_drive_every_pixel();
  test_aligned_fetches();
  test_internal_capacity();
  test_deflated_pages(argv[1]);
  test_moving_window(argv[1]);
  if (failures) {
    std::printf("%d check(s) failed\n", failures);
    return 1;
  }
  std::printf("all firmware core checks passed\n");
  return 0;
}
