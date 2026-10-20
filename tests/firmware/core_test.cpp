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
  p.on_answer(true, false, o, 1000);
  CHECK(!p.low_power() && !p.sleep_due(999999, false), "no header: stays connected");
  p.on_answer(false, false, o, 2000);
  CHECK(!p.sleep_due(999999, false), "never told to sleep: a failed download doesn't make it sleep");

  // Told to sleep on a timer wake: draw, then sleep at once, for what's left.
  p.on_answer(true, true, timer, 10000);
  CHECK(p.sleep_due(10000, false), "awake=0: sleeps as soon as it's done");
  CHECK(!p.sleep_due(10000, true), "...not while it's still drawing");
  CHECK(p.sleep_ms(14000) == 896000, "counted from the answer (%u)", (unsigned) p.sleep_ms(14000));
  CHECK(mem.interval_sec == 900, "remembered for a wake that can't reach the add-on");
  p.hold(true);
  CHECK(!p.sleep_due(20000, false), "never in the middle of an update");
  p.hold(false);

  // A press keeps it awake a minute after the last press.
  p.on_answer(true, true, press, 0);
  CHECK(!p.sleep_due(59000, false) && p.sleep_due(60000, false), "awake=60 after the download");
  p.note_press(50000);
  CHECK(!p.sleep_due(100000, false) && p.sleep_due(110000, false), "a minute after the last press");
  CHECK(p.sleep_ms(110000) == 790000, "less the time awake (%u)", (unsigned) p.sleep_ms(110000));

  // Asked to stay awake for an update: the same field.
  p.on_answer(true, true, stay, 200000);
  CHECK(!p.sleep_due(799000, false) && p.sleep_due(800000, false), "ten minutes awake");
  CHECK(p.sleep_ms(800000) == 300000, "then the rest of the interval");
  CHECK(p.sleep_ms(2000000) == epf::MIN_SLEEP_SEC * 1000u, "never less than the minimum");

  // Low Power Mode turned off in the editor: the next answer has no header.
  p.on_answer(true, false, o, 900000);
  CHECK(!p.low_power() && !p.sleep_due(9000000, false) && mem.interval_sec == 0, "off: stays connected");

  // A timer wake that can't reach the add-on sleeps and tries again, backing off.
  mem.interval_sec = 900;
  mem.failures = 0;
  uint32_t expect[] = {60, 120, 240, 480, 600, 600};
  for (uint32_t want : expect) {
    p.begin(Wake::TIMER, mem, 900000);
    p.on_answer(false, false, o, 5000);
    CHECK(p.low_power() && p.sleep_due(5000, false), "no answer on a timer wake: sleeps");
    CHECK(p.sleep_ms(5000) == want * 1000u, "retry after %u s (got %u)", (unsigned) want, (unsigned) (p.sleep_ms(5000) / 1000));
  }
  mem.interval_sec = 300;
  p.begin(Wake::TIMER, mem, 900000);
  p.on_answer(false, false, o, 0);
  CHECK(p.sleep_ms(0) == 300000, "never longer than its interval");
  p.on_answer(true, true, timer, 1000);
  CHECK(mem.failures == 0, "an answer ends the backoff");
  p.begin(Wake::BUTTON, mem, 900000);
  p.on_answer(false, false, o, 0);
  CHECK(!p.sleep_due(59000, false) && p.sleep_due(60000, false), "a press that can't reach it: awake a minute");
  p.begin(Wake::TIMER, mem, 900000);
  p.on_answer(true, true, timer, 0);
  p.on_answer(false, false, o, 500);
  CHECK(p.sleep_ms(500) == 899500, "a later failure in the same wake keeps the answer it had");

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

int main(int argc, char **argv) {
  if (argc < 2) {
    std::printf("usage: core_test <fixture-dir>\n");
    return 2;
  }
  test_streams_and_mapping(argv[1]);
  test_rejects_bad_files(argv[1]);
  test_controller(argv[1]);
  test_waveform();
  test_sleep();
  test_remote_alerts_and_fetches();
  test_power();
  if (failures) {
    std::printf("%d check(s) failed\n", failures);
    return 1;
  }
  std::printf("all firmware core checks passed\n");
  return 0;
}
