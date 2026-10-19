// Host-side tests for components/epf/epf_core.h, driven by tests/test_firmware.py,
// which writes real frame files from the server's own encoder into a folder.
//
//   core_test <fixture-dir>

#include "../../components/epf/epf_core.h"

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

  pc.on_stream_loaded(a);  // solar, sports(3), temps
  pc.page_step(1);         // -> sports
  pc.mode_toggle();        // into its items
  pc.page_step(1);         // second match
  CHECK(pc.cat_idx() == 1 && pc.sub_idx() == 1, "on sports 2/3 (cat %d sub %d)", pc.cat_idx(), pc.sub_idx());
  pc.hold_toggle();        // lock this match

  pc.on_stream_loaded(b);  // a new category was inserted before sports
  CHECK(pc.pinned() && pc.cat_idx() == 2 && pc.sub_idx() == 1, "lock follows the match (cat %d sub %d)",
        pc.cat_idx(), pc.sub_idx());

  pc.on_stream_loaded(alert);  // an alert takes over...
  CHECK(pc.page() == 0, "alert shows page 0");
  CHECK(!pc.overlay_state().panel_locked, "no padlock drawn over an alert");
  pc.page_step(1);             // ...someone presses a button during it...
  pc.on_stream_loaded(b);      // ...and when it's over the lock is still there
  CHECK(pc.pinned() && pc.cat_idx() == 2 && pc.sub_idx() == 1, "lock survives an alert (cat %d sub %d)",
        pc.cat_idx(), pc.sub_idx());
}

int main(int argc, char **argv) {
  if (argc < 2) {
    std::printf("usage: core_test <fixture-dir>\n");
    return 2;
  }
  test_streams_and_mapping(argv[1]);
  test_rejects_bad_files(argv[1]);
  test_controller(argv[1]);
  if (failures) {
    std::printf("%d check(s) failed\n", failures);
    return 1;
  }
  std::printf("all firmware core checks passed\n");
  return 0;
}
