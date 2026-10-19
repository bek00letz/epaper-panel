#pragma once
// Network and display glue for the panel. The logic lives in epf_core.h.
//
// Downloads run in their own FreeRTOS task, so the main loop -- buttons, the
// dial, the Home Assistant connection -- never waits on the network. The new
// file lands in a back buffer, is checked completely, and only then swapped in
// by the main loop, which is also the only code that reads the front buffer.

#include "epf_core.h"

#include "esp_heap_caps.h"
#include "esp_http_client.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esphome/components/display/display_buffer.h"

namespace epf {

class DisplayBufferAccessor : public esphome::display::DisplayBuffer {
 public:
  static uint8_t *raw(esphome::display::DisplayBuffer *d) { return static_cast<DisplayBufferAccessor *>(d)->buffer_; }
};

constexpr size_t BUFFER_CAPACITY = 1048576;  // per buffer, in PSRAM

inline esp_err_t epf_http_event_(esp_http_client_event_t *evt) {
  if (evt->event_id == HTTP_EVENT_ON_HEADER && evt->user_data && strcasecmp(evt->header_key, "ETag") == 0)
    *static_cast<std::string *>(evt->user_data) = evt->header_value;
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
    url_ = url;
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

  // Call from the main loop. Returns true once per finished download, with how it went.
  bool poll(FetchResult &result) {
    if (state_.load(std::memory_order_acquire) != FINISHED) return false;
    result = task_result_;
    if (result == FetchResult::OK) {
      std::swap(front_buf_, back_buf_);
      stream_ = std::move(pending_);
      current_etag_ = incoming_etag_;
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
    front_buf_ = (uint8_t *) heap_caps_malloc(BUFFER_CAPACITY, MALLOC_CAP_SPIRAM);
    back_buf_ = (uint8_t *) heap_caps_malloc(BUFFER_CAPACITY, MALLOC_CAP_SPIRAM);
    if (!front_buf_ || !back_buf_) {
      ESP_LOGE(TAG, "Couldn't allocate 2 x %u KB in PSRAM", (unsigned) (BUFFER_CAPACITY / 1024));
      heap_caps_free(front_buf_);
      heap_caps_free(back_buf_);
      front_buf_ = back_buf_ = nullptr;
      return false;
    }
    return true;
  }

  static void task_entry_(void *arg) {
    auto *self = static_cast<EpfClient *>(arg);
    self->task_result_ = self->download_();
    self->state_.store(FINISHED, std::memory_order_release);
    vTaskDelete(nullptr);
  }

  // Runs in the download task. Touches only the back buffer and pending_.
  FetchResult download_() {
    incoming_etag_.clear();
    esp_http_client_config_t config = {};
    config.url = url_.c_str();
    config.timeout_ms = 10000;
    config.buffer_size = 4096;
    config.event_handler = epf_http_event_;
    config.user_data = &incoming_etag_;
    esp_http_client_handle_t client = esp_http_client_init(&config);
    if (!client) return FetchResult::ERROR_NETWORK;
    if (!send_etag_.empty()) esp_http_client_set_header(client, "If-None-Match", send_etag_.c_str());

    FetchResult result = FetchResult::ERROR_NETWORK;
    size_t total = 0;
    if (esp_http_client_open(client, 0) == ESP_OK) {
      esp_http_client_fetch_headers(client);
      int status = esp_http_client_get_status_code(client);
      if (status == 304) {
        result = FetchResult::NOT_MODIFIED;
      } else if (status == 200) {
        bool full = false;
        while (true) {
          if (total >= BUFFER_CAPACITY) { full = true; break; }
          int n = esp_http_client_read(client, (char *) back_buf_ + total, BUFFER_CAPACITY - total);
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
  int native_w_{0}, native_h_{0};
  std::string url_, send_etag_, incoming_etag_, current_etag_;
  Stream stream_, pending_;
  bool has_stream_{false};
};

}  // namespace epf
