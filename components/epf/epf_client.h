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

#include "epf_core.h"

#include "esp_crt_bundle.h"
#include "esp_heap_caps.h"
#include "esp_http_client.h"
#include "esp_log.h"
#include "esp_sleep.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esphome/components/display/display_buffer.h"

#include <sys/time.h>

namespace epf {

class DisplayBufferAccessor : public esphome::display::DisplayBuffer {
 public:
  static uint8_t *raw(esphome::display::DisplayBuffer *d) { return static_cast<DisplayBufferAccessor *>(d)->buffer_; }
};

// Per buffer, in PSRAM. Two of the larger size fit an N8R8 board's 8 MB with
// room to spare; a board that can't give that much gets the smaller one. The
// panel tells the add-on which it got (?cap=), and the add-on fits the frame
// file to it.
constexpr size_t BUFFER_CAPACITY = 2 * 1048576;
constexpr size_t BUFFER_CAPACITY_SMALL = 1048576;

// The answer's headers the panel reads.
struct AnswerHeaders {
  std::string etag, sleep;
};

inline esp_err_t epf_http_event_(esp_http_client_event_t *evt) {
  if (evt->event_id != HTTP_EVENT_ON_HEADER || !evt->user_data) return ESP_OK;
  auto *h = static_cast<AnswerHeaders *>(evt->user_data);
  if (strcasecmp(evt->header_key, "ETag") == 0) h->etag = evt->header_value;
  else if (strcasecmp(evt->header_key, "X-EPF-Sleep") == 0) h->sleep = evt->header_value;
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
    url_ = url + (url.find('?') == std::string::npos ? "?" : "&") + "cap=" + std::to_string(capacity_) + wake_query_;
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

  // Call from the main loop. Returns true once per finished download, with how it went.
  bool poll(FetchResult &result) {
    if (state_.load(std::memory_order_acquire) != FINISHED) return false;
    result = task_result_;
    last_status_ = status_;                 // copies: the next download writes the originals
    last_sleep_ = answer_.sleep;
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
  std::string url_, send_etag_, current_etag_, wake_query_, last_sleep_;
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

// At start-up, before the first download: why it's awake and what it remembers.
inline void power_begin() {
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
  ESP_LOGI(TAG, "Awake: %s", wake_name(wake));
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
}

// Just before deep sleep: how long, and what wakes it. `buttons`: the button pins as a bit mask.
inline uint32_t power_prepare_sleep(uint32_t now_ms, uint64_t buttons) {
  auto &p = PowerPolicy::instance();
  p.before_sleep(now_ms);
  uint32_t ms = p.sleep_ms(now_ms);
  if (p.buttons_wake()) esp_sleep_enable_ext1_wakeup(buttons, ESP_EXT1_WAKEUP_ANY_LOW);
  else esp_sleep_disable_wakeup_source(ESP_SLEEP_WAKEUP_EXT1);
  g_slept_at_us = rtc_now_us_();
  ESP_LOGI(TAG, "Sleeping %u s (awake %u ms)", (unsigned) (ms / 1000), (unsigned) now_ms);
  return ms;
}

}  // namespace epf
