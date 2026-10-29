#pragma once
// Network and display glue for the panel. The logic lives in epf_core.h.
//
// Downloads run in their own FreeRTOS task, so the main loop -- buttons, the
// dial, the Home Assistant connection -- never waits on the network. The new
// file lands in a back buffer, is checked completely, and only then swapped in
// by the main loop, which is also the only code that reads the front buffer.
//
// Low Power Mode (PowerPolicy in epf_core.h): the first download after a start
// says why the panel is awake, and every answer may say how long to sleep.
// Always on, every answer may say when the next timed download starts (X-EPF-Next).
// Every download says which panel it is (?mac=), so the add-on finds it in Home
// Assistant by the address Home Assistant knows it by, never by a name.

#include "epf_core.h"

#include "driver/gpio.h"
#include "esp_crt_bundle.h"
#include "esp_heap_caps.h"
#include "esp_http_client.h"
#include "esp_log.h"
#include "esp_sleep.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "soc/soc_caps.h"
#include "esphome/components/display/display_buffer.h"
#include "esphome/core/hal.h"
#include "esphome/core/helpers.h"

#include <sys/time.h>

namespace epf {

class DisplayBufferAccessor : public esphome::display::DisplayBuffer {
 public:
  static uint8_t *raw(esphome::display::DisplayBuffer *d) { return static_cast<DisplayBufferAccessor *>(d)->buffer_; }
};

// A Waveshare driver that refreshes in full when its update count is at 0 and
// has no call for it (ESPHome's 2.90inv2-r2): restart the count, so the next
// refresh is full. Only the redraw script calls this (firmware_gen.FULL_REFRESH).
template <class Driver> inline void full_refresh_next(Driver *display) {
  struct Count : Driver {
    static void restart(Driver *d) { static_cast<Count *>(d)->at_update_ = 0; }
  };
  Count::restart(display);
}

// After a deep sleep that kept the display powered, the screen still shows its
// picture (PowerPolicy::picture_kept), so its driver needn't start with a full
// refresh: the refresh policy decides. Each driver counts its refreshes and does
// a full one first; these start the count past that. Only on_boot calls them
// (firmware_gen.KEEP_PICTURE).
template <class Driver> inline void crowpanel_picture_kept(Driver *display) {
  struct Count : Driver {
    static void skip_first(Driver *d) { static_cast<Count *>(d)->update_count_ = 1; }
  };
  Count::skip_first(display);
}
template <class Driver> inline void waveshare_picture_kept(Driver *display) {
  struct Count : Driver {
    static void skip_first(Driver *d) { static_cast<Count *>(d)->at_update_ = 1; }
  };
  Count::skip_first(display);
}

// The controller's memory of the previous picture is gone after that sleep
// (epf_core.h, "The first refresh after a deep sleep"): these write the picture
// just drawn, inverted, into it, so the refresh that follows drives every pixel.
// Each writes exactly where and how its driver writes that memory before a full
// refresh. Only the display's lambda calls them, once per wake, after drawing
// (PowerPolicy::take_first_refresh, firmware_gen.DRIVE_EVERY_PIXEL).

// The CrowPanel driver (SSD1683, one controller or a cascade of `controllers`):
// RAM 0x26 from the top-left, the second controller from the right (its X
// counts down from the last byte of its share). Its own refresh resets the
// counters. Mid-refresh or still starting (it never is at the first picture
// after a wake), it isn't touched and that refresh is a full one instead.
template <class Driver> inline void crowpanel_drive_every_pixel(Driver *display, int controllers) {
  struct Ram : Driver {
    static void seed(Driver *d, int controllers) {
      auto *s = static_cast<Ram *>(d);
      if (s->state_ != decltype(s->state_)::IDLE) {
        s->force_full_update();
        return;
      }
      const size_t row_bytes = (size_t) s->native_width_() / 8, rows = (size_t) s->native_height_();
      for (int i = 0; i < (controllers == 2 ? 2 : 1); i++) {
        RowShare share = row_share(row_bytes, controllers, i);
        const uint8_t to = i == 0 ? 0x00 : 0x80;   // the second controller of a cascade
        s->spi_command_(0x4E | to);                // X counter
        s->spi_data_(i == 0 ? 0 : (uint8_t) (share.count - 1));
        s->spi_command_(0x4F | to);                // Y counter
        s->spi_data_(0x00);
        s->spi_data_(0x00);
        s->spi_command_(0x26 | to);                // the previous picture
        s->spi_start_data_();
        send_inverted_share(s->buffer_, row_bytes, rows, share, [s](uint8_t b) { s->spi_write_byte_(b); });
        s->spi_end_data_();
      }
    }
  };
  Ram::seed(display, controllers);
}

// ESPHome's Waveshare driver for an SSD1680-type controller (the 2.9"): RAM 0x26
// from the top-left, as its full refresh writes it.
template <class Driver> inline void waveshare_drive_every_pixel(Driver *display) {
  struct Ram : Driver {
    static void seed(Driver *d) {
      auto *s = static_cast<Ram *>(d);
      if (!s->wait_until_idle_()) {
        full_refresh_next(d);
        return;
      }
      const size_t row_bytes = (size_t) s->get_width_controller() / 8, rows = (size_t) s->get_height_internal();
      s->command(0x4E);
      s->data(0x00);
      s->command(0x4F);
      s->data(0x00);
      s->data(0x00);
      s->command(0x26);
      s->start_data_();
      send_inverted_share(s->buffer_, row_bytes, rows, row_share(row_bytes, 1, 0), [s](uint8_t b) { s->write_byte(b); });
      s->end_data_();
    }
  };
  Ram::seed(display);
}

// Per buffer, in PSRAM. Two of the larger size fit an N8R8 board's 8 MB with
// room to spare; a board that can't give that much gets the smaller one. The
// panel tells the add-on which it got (?cap=), and the add-on fits the frame
// file to it.
constexpr size_t BUFFER_CAPACITY = 2 * 1048576;
constexpr size_t BUFFER_CAPACITY_SMALL = 1048576;

// The answer's headers the panel reads.
struct AnswerHeaders {
  std::string etag, sleep, next;
  uint32_t next_at_ms{0};                 // when X-EPF-Next arrived: it counts from then, not from the body's end
};

inline esp_err_t epf_http_event_(esp_http_client_event_t *evt) {
  if (evt->event_id != HTTP_EVENT_ON_HEADER || !evt->user_data) return ESP_OK;
  auto *h = static_cast<AnswerHeaders *>(evt->user_data);
  if (strcasecmp(evt->header_key, "ETag") == 0) h->etag = evt->header_value;
  else if (strcasecmp(evt->header_key, "X-EPF-Sleep") == 0) h->sleep = evt->header_value;
  else if (strcasecmp(evt->header_key, "X-EPF-Next") == 0) {
    h->next = evt->header_value;
    h->next_at_ms = esphome::millis();
  }
  return ESP_OK;
}

class EpfClient {
 public:
  static EpfClient &instance() {
    static EpfClient inst;
    return inst;
  }

  // Start a download in the background. False if one is already running or
  // the buffers can't be allocated.
  bool start_fetch(const std::string &url, esphome::display::DisplayBuffer *epd) {
    if (state_.load(std::memory_order_acquire) != IDLE) return false;
    if (!alloc_()) return false;
    url_ = url + (url.find('?') == std::string::npos ? "?" : "&") + "cap=" + std::to_string(capacity_) + "&mac=" +
           mac_() + wake_query_;
    wake_query_.clear();                    // said once, on the first download after a start
    send_etag_ = current_etag_;
    native_w_ = epd ? epd->get_native_width() : 0;
    native_h_ = epd ? epd->get_native_height() : 0;
    state_.store(RUNNING, std::memory_order_release);
    if (xTaskCreate(&EpfClient::task_entry_, "epf_fetch", 8192, this, 3, nullptr) != pdPASS) {
      ESP_LOGE(TAG, "Couldn't start the download task");
      state_.store(IDLE, std::memory_order_release);
      return false;
    }
    return true;
  }

  bool busy() const { return state_.load(std::memory_order_acquire) != IDLE; }

  // Why it's awake, for the first download (only firmware that can sleep says so).
  void set_wake(const char *wake, uint32_t awake_ms) {
    wake_query_ = std::string("&wake=") + wake;
    if (awake_ms) wake_query_ += "&awake_ms=" + std::to_string(awake_ms);
  }

  // The last finished download: its HTTP status (0: nothing answered), and its X-EPF-Sleep ("" when none).
  int status() const { return last_status_; }
  const std::string &etag() const { return current_etag_; }
  // What's on screen, after a deep sleep: the frames are gone from memory, the picture isn't.
  void set_etag(const std::string &etag) { current_etag_ = etag; }
  void forget_etag() { current_etag_.clear(); }
  const std::string &sleep_header() const { return last_sleep_; }
  // Its X-EPF-Next ("" when none), and when that arrived (millis()).
  const std::string &next_header() const { return last_next_; }
  uint32_t next_at_ms() const { return last_next_at_ms_; }

  // Call from the main loop. Returns true once per finished download, with how it went.
  bool poll(FetchResult &result) {
    if (state_.load(std::memory_order_acquire) != FINISHED) return false;
    result = task_result_;
    last_status_ = status_;                 // copies: the next download writes the originals
    last_sleep_ = answer_.sleep;
    last_next_ = answer_.next;
    last_next_at_ms_ = answer_.next_at_ms;
    if (result == FetchResult::OK) {
      std::swap(front_buf_, back_buf_);
      stream_ = std::move(pending_);
      current_etag_ = answer_.etag;
      has_stream_ = true;
      ESP_LOGI(TAG, "New frames: %u pages in %u categories", stream_.header.page_count, stream_.header.cat_count);
    } else if (result != FetchResult::NOT_MODIFIED) {
      ESP_LOGW(TAG, "Download failed: %s. Keeping what's on screen", describe(result));
    }
    state_.store(IDLE, std::memory_order_release);
    return true;
  }

  bool has_stream() const { return has_stream_; }
  const Stream &stream() const { return stream_; }
  bool is_alert_interrupt() const { return (stream_.header.flags & FLAG_ALERT_INTERRUPT) != 0; }
  bool is_force_full_waveform() const { return (stream_.header.flags & FLAG_FORCE_FULL) != 0; }

  // Copy one page into the display buffer. The file was checked against this
  // panel's size, so the copy is exactly one buffer long.
  bool blit(esphome::display::DisplayBuffer *epd, int page) {
    if (!has_stream_ || !epd || page < 0 || page >= stream_.header.page_count) return false;
    uint8_t *dst = DisplayBufferAccessor::raw(epd);
    const Header &h = stream_.header;
    if (!dst || h.width != epd->get_native_width() || h.height != epd->get_native_height() || h.width % 8) return false;
    size_t page_bytes = (size_t) h.stride * h.height;
    std::memcpy(dst, front_buf_ + h.data_offset + (size_t) page * page_bytes, page_bytes);
    return true;
  }

  void draw_overlays(esphome::display::DisplayBuffer *epd, const OverlayState &s) {
    if (!has_stream_ || !epd) return;
    epf::draw_overlays(DisplayBufferAccessor::raw(epd), epd->get_native_width(), epd->get_native_height(),
                       stream_.geometry, s);
  }

 private:
  enum : uint8_t { IDLE = 0, RUNNING = 1, FINISHED = 2 };

  EpfClient() = default;

  bool alloc_() {
    if (front_buf_ && back_buf_) return true;
    for (size_t cap : {BUFFER_CAPACITY, BUFFER_CAPACITY_SMALL}) {
      front_buf_ = (uint8_t *) heap_caps_malloc(cap, MALLOC_CAP_SPIRAM);
      back_buf_ = (uint8_t *) heap_caps_malloc(cap, MALLOC_CAP_SPIRAM);
      if (front_buf_ && back_buf_) {
        capacity_ = cap;
        ESP_LOGI(TAG, "Frame buffers: 2 x %u KB in PSRAM", (unsigned) (cap / 1024));
        return true;
      }
      heap_caps_free(front_buf_);
      heap_caps_free(back_buf_);
      front_buf_ = back_buf_ = nullptr;
    }
    ESP_LOGE(TAG, "Couldn't allocate frame buffers in PSRAM");
    return false;
  }

  static void task_entry_(void *arg) {
    auto *self = static_cast<EpfClient *>(arg);
    self->task_result_ = self->download_();
    self->state_.store(FINISHED, std::memory_order_release);
    vTaskDelete(nullptr);
  }

  // Runs in the download task. Touches only the back buffer and pending_.
  FetchResult download_() {
    answer_ = AnswerHeaders{};
    status_ = 0;
    esp_http_client_config_t config = {};
    config.url = url_.c_str();
    // An https address (a screen away from home) is checked against ESP-IDF's
    // bundle of public certificate authorities, like a browser would.
    const bool https = url_.rfind("https://", 0) == 0;
    if (https) config.crt_bundle_attach = esp_crt_bundle_attach;
    config.timeout_ms = https ? 20000 : 10000;
    config.buffer_size = 4096;
    config.event_handler = epf_http_event_;
    config.user_data = &answer_;
    esp_http_client_handle_t client = esp_http_client_init(&config);
    if (!client) return FetchResult::ERROR_NETWORK;
    if (!send_etag_.empty()) esp_http_client_set_header(client, "If-None-Match", send_etag_.c_str());

    FetchResult result = FetchResult::ERROR_NETWORK;
    size_t total = 0;
    if (esp_http_client_open(client, 0) == ESP_OK) {
      esp_http_client_fetch_headers(client);
      int status = esp_http_client_get_status_code(client);
      status_ = status > 0 ? status : 0;
      if (status == 304) {
        result = FetchResult::NOT_MODIFIED;
      } else if (status == 200) {
        bool full = false;
        while (true) {
          if (total >= capacity_) {
            char extra;                     // exactly full is fine; one byte more is not
            full = esp_http_client_read(client, &extra, 1) > 0;
            break;
          }
          int n = esp_http_client_read(client, (char *) back_buf_ + total, capacity_ - total);
          if (n < 0) { total = 0; break; }
          if (n == 0) break;
          total += (size_t) n;
        }
        if (full) result = FetchResult::ERROR_BUFFER_FULL;
        else if (total > 0) result = parse_stream(back_buf_, total, native_w_, native_h_, pending_);
      } else {
        ESP_LOGW(TAG, "Server answered HTTP %d", status);
      }
    } else {
      ESP_LOGW(TAG, "Couldn't reach the frame server");
    }
    esp_http_client_close(client);
    esp_http_client_cleanup(client);
    return result;
  }

  std::atomic<uint8_t> state_{IDLE};
  FetchResult task_result_{FetchResult::OK};
  uint8_t *front_buf_{nullptr};
  uint8_t *back_buf_{nullptr};
  size_t capacity_{0};
  int native_w_{0}, native_h_{0};
  // Its Wi-Fi MAC address, as Home Assistant's ESPHome devices are known by: 12 lower-case hex digits.
  static std::string mac_() {
    uint8_t mac[6];
    esphome::get_mac_address_raw(mac);
    char out[13];
    snprintf(out, sizeof out, "%02x%02x%02x%02x%02x%02x", mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
    return out;
  }

  std::string url_, send_etag_, current_etag_, wake_query_, last_sleep_, last_next_;
  uint32_t last_next_at_ms_{0};
  AnswerHeaders answer_;                  // written by the download task
  int status_{0}, last_status_{0};
  Stream stream_, pending_;
  bool has_stream_{false};
};

// ---------------------------------------------------------------- Low Power Mode glue

// Kept through deep sleep (RTC memory, epf_power.cpp).
extern Remembered g_remembered;
extern int64_t g_slept_at_us;

inline int64_t rtc_now_us_() {
  struct timeval tv;
  gettimeofday(&tv, nullptr);                // keeps counting through deep sleep
  return (int64_t) tv.tv_sec * 1000000 + tv.tv_usec;
}

// The display's power pin, held on through deep sleep; -1 when the display is
// switched off in deep sleep (the way it was before 0.13).
inline int &power_display_pin_() {
  static int pin = -1;
  return pin;
}

// At start-up, before the first download: why it's awake and what it remembers.
// `display_pin`: the display's power pin, to keep it on through deep sleep (TRMNL's
// way: the first change after a wake is partial), or -1 to switch it off.
inline void power_begin(int display_pin) {
  power_display_pin_() = display_pin;
  // Held on through the sleep it just woke from. The pin is an output, already
  // set high (switch epd_power, restore ALWAYS_ON), so letting go changes nothing.
  if (display_pin >= 0) gpio_hold_dis((gpio_num_t) display_pin);
  Wake wake = Wake::BOOT;
  switch (esp_sleep_get_wakeup_cause()) {
    case ESP_SLEEP_WAKEUP_TIMER: wake = Wake::TIMER; break;
    case ESP_SLEEP_WAKEUP_EXT1: wake = Wake::BUTTON; break;
    default: break;
  }
  uint32_t slept_ms = 0;
  if (wake != Wake::BOOT && g_slept_at_us > 0) {
    int64_t d = (rtc_now_us_() - g_slept_at_us) / 1000;
    slept_ms = d <= 0 ? 0 : (d > 0xFFFFFFFFll ? 0xFFFFFFFFu : (uint32_t) d);
  }
  bool kept = g_remembered.magic == REMEMBERED_MAGIC;
  uint32_t awake_ms = kept ? g_remembered.awake_ms : 0;
  PowerPolicy::instance().begin(wake, g_remembered, slept_ms);
  // A timer wake whose page hasn't changed gets a 304 and leaves the screen as it is.
  if (kept && wake == Wake::TIMER) {
    g_remembered.etag[sizeof(g_remembered.etag) - 1] = '\0';
    EpfClient::instance().set_etag(g_remembered.etag);
  }
  EpfClient::instance().set_wake(wake_name(wake), wake == Wake::BOOT ? 0 : awake_ms);
  if (display_pin >= 0) choose_waveform(PanelController::instance().waveform(), PowerPolicy::instance(), g_remembered);
  ESP_LOGI(TAG, "Awake: %s%s", wake_name(wake), PowerPolicy::instance().picture_kept() ? ", picture kept" : "");
}

// After every finished download: what the add-on said about sleeping.
inline void power_note_download(uint32_t now_ms, FetchResult result) {
  auto &c = EpfClient::instance();
  if (result == FetchResult::OK) {
    std::strncpy(g_remembered.etag, c.etag().c_str(), sizeof(g_remembered.etag) - 1);
    g_remembered.etag[sizeof(g_remembered.etag) - 1] = '\0';
  }
  SleepOrder order;
  bool has = !c.sleep_header().empty() && parse_sleep_order(c.sleep_header().c_str(), order);
  if (!c.sleep_header().empty() && !has) ESP_LOGW(TAG, "Ignored an X-EPF-Sleep it can't read: %s", c.sleep_header().c_str());
  PowerPolicy::instance().on_answer(c.status(), has, order, now_ms);
  if (power_display_pin_() >= 0)
    choose_waveform(PanelController::instance().waveform(), PowerPolicy::instance(), g_remembered);
}

// After every finished download: when the add-on says the next timed one should start
// (X-EPF-Next, a moment after its render each minute). Without it, the interval decides.
inline void note_next_fetch() {
  auto &c = EpfClient::instance();
  if (c.next_header().empty()) return;
  uint32_t ms;
  if (parse_next_fetch(c.next_header().c_str(), ms)) PanelController::instance().aim_fetch(ms, c.next_at_ms());
  else ESP_LOGW(TAG, "Ignored an X-EPF-Next it can't read: %s", c.next_header().c_str());
}

// Whether a redraw may go ahead. After a deep sleep the screen still shows its last
// picture but the frames aren't in memory yet, so a press before they arrive would
// replace it with the "waiting for frames" screen. Their arrival redraws. After a
// fresh start there's nothing on screen worth keeping.
inline bool may_redraw() {
  return EpfClient::instance().has_stream() || PowerPolicy::instance().wake() == Wake::BOOT;
}

// Just before deep sleep: how long, and what wakes it. `buttons`: the button pins as a bit mask.
// The display has finished refreshing (sleep_due waits for it). Its driver puts its
// controller to sleep (on_safe_shutdown), and its power pin is held on. Its memory
// of the picture is lost all the same (its reset line isn't held), so the next
// wake's first refresh drives every pixel (PowerPolicy::take_first_refresh).
inline uint32_t power_prepare_sleep(uint32_t now_ms, uint64_t buttons) {
  auto &p = PowerPolicy::instance();
  int pin = power_display_pin_();
  if (pin >= 0) {
    gpio_hold_en((gpio_num_t) pin);
#if !SOC_GPIO_SUPPORT_HOLD_SINGLE_IO_IN_DSLP
    gpio_deep_sleep_hold_en();
#endif
  }
  p.before_sleep(now_ms, pin >= 0);
  uint32_t ms = p.sleep_ms(now_ms);
  if (p.buttons_wake()) esp_sleep_enable_ext1_wakeup(buttons, ESP_EXT1_WAKEUP_ANY_LOW);
  else esp_sleep_disable_wakeup_source(ESP_SLEEP_WAKEUP_EXT1);
  g_slept_at_us = rtc_now_us_();
  ESP_LOGI(TAG, "Sleeping %u s (awake %u ms)", (unsigned) (ms / 1000), (unsigned) now_ms);
  return ms;
}

}  // namespace epf
