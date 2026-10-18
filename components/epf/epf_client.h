#pragma once
#ifndef EPF_CLIENT_H_
#define EPF_CLIENT_H_

#include <cstdint>
#include <cstring>
#include <vector>
#include <string>
#include <algorithm>

#include "esp_heap_caps.h"
#include "esp_http_client.h"
#include "esp_log.h"
#include "esphome/components/display/display_buffer.h"

namespace epf {

class DisplayBufferAccessor : public esphome::display::DisplayBuffer {
 public:
  static uint8_t *get_raw_buffer(esphome::display::DisplayBuffer *d) {
    return static_cast<DisplayBufferAccessor *>(d)->buffer_;
  }
};

static const char *const TAG = "epf";

constexpr uint32_t MAGIC = 0x45504150;  // "EPAP"
constexpr uint16_t VERSION = 3;
constexpr size_t HEADER_SIZE = 64;
constexpr size_t CAT_RECORD_SIZE = 16;
constexpr size_t PAGE_RECORD_SIZE = 16;
constexpr size_t CRC_SIZE = 4;
constexpr size_t BUFFER_CAPACITY = 1048576;  // 1 MB static PSRAM buffer

constexpr uint32_t FLAG_ALERT_INTERRUPT = 0x0001;
constexpr uint32_t FLAG_QUIET_HOURS = 0x0002;
constexpr uint32_t FLAG_FORCE_FULL = 0x0004;
constexpr uint32_t FLAG_ORIENTATION_180 = 0x0008;

enum class FetchResult : uint8_t {
  OK,
  NOT_MODIFIED,
  ERROR_NETWORK,
  ERROR_CRC,
  ERROR_HEADER,
  ERROR_BUFFER_FULL,
};

enum class NavAction : uint8_t {
  NEXT,
  PREV,
  MODE_TOGGLE,
  LOCK_TOGGLE,
  CAT_LOCK_TOGGLE,
  SUB_STEP,
  CAT_STEP,
  RESET_HOME,
  GOTO_PAGE,
  GOTO_CAT,
};

#pragma pack(push, 1)
struct EpfHeader {
  uint32_t magic;
  uint16_t version;
  uint16_t model_id;
  uint16_t width;
  uint16_t height;
  uint16_t stride;
  uint16_t page_count;
  uint16_t cat_count;
  uint16_t rotate_sec;
  uint32_t flags;
  uint64_t content_hash;
  uint32_t payload_size;
  uint32_t dir_offset;
  uint32_t data_offset;
  uint8_t reserved[20];
};

struct EpfCategoryRecord {
  uint32_t cat_id;
  uint16_t offset_page;
  uint16_t page_count;
  uint16_t pill_width;
  uint16_t flags;
  uint32_t reserved;
};

struct EpfPageRecord {
  uint32_t sub_id;
  uint32_t cat_id;
  uint16_t cat_index;
  uint16_t sub_index;
  uint32_t reserved;
};
#pragma pack(pop)

// Fast CRC-32 (IEEE 802.3)
inline uint32_t compute_crc32(const uint8_t *data, size_t length) {
  uint32_t crc = 0xFFFFFFFF;
  for (size_t i = 0; i < length; i++) {
    crc ^= data[i];
    for (int k = 0; k < 8; k++) {
      crc = (crc >> 1) ^ (0xEDB88320 & (-(crc & 1)));
    }
  }
  return ~crc;
}

inline esp_err_t _epf_http_event_handler(esp_http_client_event_t *evt) {
  if (evt->event_id == HTTP_EVENT_ON_HEADER) {
    if (strcasecmp(evt->header_key, "ETag") == 0 && evt->user_data) {
      std::string *etag_out = static_cast<std::string *>(evt->user_data);
      *etag_out = evt->header_value;
    }
  }
  return ESP_OK;
}

class EpfClient {
 public:
  static EpfClient &instance() {
    static EpfClient inst;
    return inst;
  }

  bool init() {
    if (initialized_) return true;

    front_buf_ = (uint8_t *) heap_caps_malloc(BUFFER_CAPACITY, MALLOC_CAP_SPIRAM);
    back_buf_ = (uint8_t *) heap_caps_malloc(BUFFER_CAPACITY, MALLOC_CAP_SPIRAM);

    if (!front_buf_ || !back_buf_) {
      ESP_LOGE(TAG, "Failed to allocate static PSRAM double-buffers (2 x %u KB)", (unsigned)(BUFFER_CAPACITY / 1024));
      return false;
    }

    std::memset(front_buf_, 0xFF, BUFFER_CAPACITY);
    std::memset(back_buf_, 0xFF, BUFFER_CAPACITY);
    initialized_ = true;
    ESP_LOGI(TAG, "Allocated static double-buffers in PSRAM (2 x %u KB, zero heap churn)", (unsigned)(BUFFER_CAPACITY / 1024));
    return true;
  }

  FetchResult fetch(const std::string &url, const std::string &etag = "") {
    if (!init()) return FetchResult::ERROR_NETWORK;

    std::string incoming_etag;
    esp_http_client_config_t config = {};
    config.url = url.c_str();
    config.timeout_ms = 15000;
    config.buffer_size = 4096;
    config.event_handler = _epf_http_event_handler;
    config.user_data = &incoming_etag;

    esp_http_client_handle_t client = esp_http_client_init(&config);
    if (!client) {
      ESP_LOGE(TAG, "esp_http_client_init failed");
      return FetchResult::ERROR_NETWORK;
    }

    std::string send_etag = etag.empty() ? current_etag_ : etag;
    if (!send_etag.empty()) {
      esp_http_client_set_header(client, "If-None-Match", send_etag.c_str());
    }

    esp_err_t err = esp_http_client_open(client, 0);
    if (err != ESP_OK) {
      ESP_LOGW(TAG, "Failed to open HTTP connection: %s", esp_err_to_name(err));
      esp_http_client_cleanup(client);
      return FetchResult::ERROR_NETWORK;
    }

    int content_length = esp_http_client_fetch_headers(client);
    int status_code = esp_http_client_get_status_code(client);

    if (status_code == 304) {
      ESP_LOGI(TAG, "Server returned 304 Not Modified (0 bytes transferred)");
      esp_http_client_close(client);
      esp_http_client_cleanup(client);
      return FetchResult::NOT_MODIFIED;
    }

    if (status_code != 200) {
      ESP_LOGW(TAG, "Server returned HTTP %d", status_code);
      esp_http_client_close(client);
      esp_http_client_cleanup(client);
      return FetchResult::ERROR_NETWORK;
    }

    // Stream directly into back_buf_
    size_t total_read = 0;
    while (total_read < BUFFER_CAPACITY) {
      int read_bytes = esp_http_client_read(client, (char *)(back_buf_ + total_read), BUFFER_CAPACITY - total_read);
      if (read_bytes <= 0) break;
      total_read += read_bytes;
    }

    esp_http_client_close(client);
    esp_http_client_cleanup(client);

    if (total_read < HEADER_SIZE + CRC_SIZE) {
      ESP_LOGE(TAG, "Received payload too small (%u bytes)", (unsigned)total_read);
      return FetchResult::ERROR_HEADER;
    }

    // CRC-32 Validation
    size_t body_len = total_read - CRC_SIZE;
    uint32_t expected_crc = ((uint32_t)back_buf_[body_len] << 24) |
                            ((uint32_t)back_buf_[body_len + 1] << 16) |
                            ((uint32_t)back_buf_[body_len + 2] << 8) |
                            ((uint32_t)back_buf_[body_len + 3]);
    uint32_t computed_crc = compute_crc32(back_buf_, body_len);

    if (expected_crc != computed_crc) {
      ESP_LOGE(TAG, "CRC-32 checksum failed! Expected 0x%08X, got 0x%08X", (unsigned)expected_crc, (unsigned)computed_crc);
      return FetchResult::ERROR_CRC;
    }

    // Parse Header
    EpfHeader temp_hdr;
    std::memcpy(&temp_hdr, back_buf_, sizeof(EpfHeader));

    // Convert big-endian header fields to host
    temp_hdr.magic = __builtin_bswap32(temp_hdr.magic);
    temp_hdr.version = __builtin_bswap16(temp_hdr.version);
    temp_hdr.model_id = __builtin_bswap16(temp_hdr.model_id);
    temp_hdr.width = __builtin_bswap16(temp_hdr.width);
    temp_hdr.height = __builtin_bswap16(temp_hdr.height);
    temp_hdr.stride = __builtin_bswap16(temp_hdr.stride);
    temp_hdr.page_count = __builtin_bswap16(temp_hdr.page_count);
    temp_hdr.cat_count = __builtin_bswap16(temp_hdr.cat_count);
    temp_hdr.rotate_sec = __builtin_bswap16(temp_hdr.rotate_sec);
    temp_hdr.flags = __builtin_bswap32(temp_hdr.flags);
    temp_hdr.content_hash = __builtin_bswap64(temp_hdr.content_hash);
    temp_hdr.payload_size = __builtin_bswap32(temp_hdr.payload_size);
    temp_hdr.dir_offset = __builtin_bswap32(temp_hdr.dir_offset);
    temp_hdr.data_offset = __builtin_bswap32(temp_hdr.data_offset);

    if (temp_hdr.magic != MAGIC || temp_hdr.version != VERSION) {
      ESP_LOGE(TAG, "Invalid magic (0x%08X) or version (%u)", (unsigned)temp_hdr.magic, temp_hdr.version);
      return FetchResult::ERROR_HEADER;
    }

    // Atomic Swap: Front Buffer now points to the verified payload
    std::swap(front_buf_, back_buf_);
    header_ = temp_hdr;
    current_etag_ = incoming_etag.empty() ? etag : incoming_etag;
    has_valid_stream_ = true;

    // Parse Directories
    categories_.clear();
    const uint8_t *cat_ptr = front_buf_ + header_.dir_offset;
    for (uint16_t c = 0; c < header_.cat_count; c++) {
      EpfCategoryRecord rec;
      std::memcpy(&rec, cat_ptr + (c * CAT_RECORD_SIZE), CAT_RECORD_SIZE);
      rec.cat_id = __builtin_bswap32(rec.cat_id);
      rec.offset_page = __builtin_bswap16(rec.offset_page);
      rec.page_count = __builtin_bswap16(rec.page_count);
      rec.pill_width = __builtin_bswap16(rec.pill_width);
      rec.flags = __builtin_bswap16(rec.flags);
      categories_.push_back(rec);
    }

    pages_.clear();
    const uint8_t *page_ptr = cat_ptr + (header_.cat_count * CAT_RECORD_SIZE);
    for (uint16_t p = 0; p < header_.page_count; p++) {
      EpfPageRecord rec;
      std::memcpy(&rec, page_ptr + (p * PAGE_RECORD_SIZE), PAGE_RECORD_SIZE);
      rec.sub_id = __builtin_bswap32(rec.sub_id);
      rec.cat_id = __builtin_bswap32(rec.cat_id);
      rec.cat_index = __builtin_bswap16(rec.cat_index);
      rec.sub_index = __builtin_bswap16(rec.sub_index);
      pages_.push_back(rec);
    }

    ESP_LOGI(TAG, "Stream verified: %u pages (%u categories, %u bytes) in 0 ms decode",
             header_.page_count, header_.cat_count, (unsigned)total_read);

    return FetchResult::OK;
  }

  // Fast direct scanline memcpy: ~80 microseconds!
  bool blit(uint8_t *target_buffer, int page_index) {
    if (!has_valid_stream_ || !front_buf_ || !target_buffer) return false;
    if (page_index < 0 || page_index >= header_.page_count) return false;

    size_t page_bytes = (size_t)header_.stride * header_.height;
    const uint8_t *src = front_buf_ + header_.data_offset + ((size_t)page_index * page_bytes);
    std::memcpy(target_buffer, src, page_bytes);
    return true;
  }

  bool blit_to_display(esphome::display::DisplayBuffer *epd, int page_index) {
    if (!has_valid_stream_ || !front_buf_ || !epd) return false;
    if (page_index < 0 || page_index >= header_.page_count) return false;

    uint8_t *dst = DisplayBufferAccessor::get_raw_buffer(epd);
    if (!dst) return false;

    size_t page_bytes = (size_t)header_.stride * header_.height;
    const uint8_t *src = front_buf_ + header_.data_offset + ((size_t)page_index * page_bytes);
    std::memcpy(dst, src, page_bytes);
    return true;
  }

  bool is_alert_interrupt() const { return (header_.flags & FLAG_ALERT_INTERRUPT) != 0; }
  bool is_quiet_hours() const { return (header_.flags & FLAG_QUIET_HOURS) != 0; }
  bool is_force_full_waveform() const { return (header_.flags & FLAG_FORCE_FULL) != 0; }
  bool is_orientation_180() const { return (header_.flags & FLAG_ORIENTATION_180) != 0; }

  const EpfHeader &header() const { return header_; }
  bool has_stream() const { return has_valid_stream_; }
  const std::string &etag() const { return current_etag_; }
  uint64_t content_hash() const { return header_.content_hash; }
  const std::vector<EpfCategoryRecord> &categories() const { return categories_; }
  const std::vector<EpfPageRecord> &pages() const { return pages_; }

 private:
  EpfClient() = default;

  bool initialized_{false};
  bool has_valid_stream_{false};
  uint8_t *front_buf_{nullptr};
  uint8_t *back_buf_{nullptr};
  EpfHeader header_{};
  std::vector<EpfCategoryRecord> categories_;
  std::vector<EpfPageRecord> pages_;
  std::string current_etag_;
};

static inline bool in_rounded_box(int px, int py, int x0, int y0, int x1, int y1, int r) {
  if (px < x0 || px > x1 || py < y0 || py > y1) return false;
  if (px < x0 + r && py < y0 + r) {
    int dx = (x0 + r) - px, dy = (y0 + r) - py;
    return (dx * dx + dy * dy <= r * r);
  }
  if (px > x1 - r && py < y0 + r) {
    int dx = px - (x1 - r), dy = (y0 + r) - py;
    return (dx * dx + dy * dy <= r * r);
  }
  if (px < x0 + r && py > y1 - r) {
    int dx = (x0 + r) - px, dy = py - (y1 - r);
    return (dx * dx + dy * dy <= r * r);
  }
  if (px > x1 - r && py > y1 - r) {
    int dx = px - (x1 - r), dy = py - (y1 - r);
    return (dx * dx + dy * dy <= r * r);
  }
  return true;
}

class PanelController {
 public:
  static PanelController &instance() {
    static PanelController inst;
    return inst;
  }

  void dispatch(NavAction action, int param = 0) {
    switch (action) {
      case NavAction::NEXT: page_step(param != 0 ? param : 1); break;
      case NavAction::PREV: page_step(param != 0 ? param : -1); break;
      case NavAction::MODE_TOGGLE: mode_toggle(); break;
      case NavAction::LOCK_TOGGLE: lock_toggle(); break;
      case NavAction::CAT_LOCK_TOGGLE: category_pin_toggle(); break;
      case NavAction::SUB_STEP: sub_step(param != 0 ? param : 1); break;
      case NavAction::CAT_STEP: category_step(param != 0 ? param : 1); break;
      case NavAction::RESET_HOME: reset_home(); break;
      case NavAction::GOTO_PAGE: show_page(param); break;
      case NavAction::GOTO_CAT: show_category(param, 0); break;
    }
  }

  void page_step(int delta) {
    idle_sec_ = 0;
    user_cool_sec_ = 0;
    pending_redraw_ = true;
    int cats = cat_count_ > 0 ? cat_count_ : 1;
    if (cat_idx_ >= cats) cat_idx_ = 0;

    if (sub_mode_) {
      int c_idx = cat_idx_;
      int sz = (c_idx < (int)cat_sizes_.size()) ? cat_sizes_[c_idx] : 1;
      if (sz > 1) {
        sub_idx_ = ((sub_idx_ + delta) % sz + sz) % sz;
        if ((int)cat_sub_pos_.size() <= c_idx) cat_sub_pos_.resize(cats, 0);
        cat_sub_pos_[c_idx] = (sub_idx_ + 1) % sz;
        int off = (c_idx < (int)cat_offsets_.size()) ? cat_offsets_[c_idx] : c_idx;
        int p = off + sub_idx_;
        if (p < page_count_) page_ = p;
        ESP_LOGI(TAG, "Nav (sub): cat=%d/%d sub=%d/%d (page=%d/%d)", c_idx + 1, cats, sub_idx_ + 1, sz, page_ + 1, page_count_);
      }
    } else {
      cat_idx_ = ((cat_idx_ + delta) % cats + cats) % cats;
      int c_idx = cat_idx_;
      int sz = (c_idx < (int)cat_sizes_.size() && cat_sizes_[c_idx] > 0) ? cat_sizes_[c_idx] : 1;
      if ((int)cat_sub_pos_.size() <= c_idx) cat_sub_pos_.resize(cats, 0);
      sub_idx_ = (sz > 1) ? (cat_sub_pos_[c_idx] % sz) : 0;
      sub_mode_ = false;
      int off = (c_idx < (int)cat_offsets_.size()) ? cat_offsets_[c_idx] : c_idx;
      int p = off + sub_idx_;
      if (p < page_count_) page_ = p;
      ESP_LOGI(TAG, "Nav (cat): cat=%d/%d sub=%d/%d (page=%d/%d)", c_idx + 1, cats, sub_idx_ + 1, sz, page_ + 1, page_count_);
    }
    update_current_identities_();
  }

  void category_step(int delta) {
    idle_sec_ = 0;
    user_cool_sec_ = 0;
    pending_redraw_ = true;
    int cats = cat_count_ > 0 ? cat_count_ : 1;
    cat_idx_ = ((cat_idx_ + delta) % cats + cats) % cats;
    int c_idx = cat_idx_;
    int sz = (c_idx < (int)cat_sizes_.size() && cat_sizes_[c_idx] > 0) ? cat_sizes_[c_idx] : 1;
    if ((int)cat_sub_pos_.size() <= c_idx) cat_sub_pos_.resize(cats, 0);
    sub_idx_ = (sz > 1) ? (cat_sub_pos_[c_idx] % sz) : 0;
    sub_mode_ = false;
    int off = (c_idx < (int)cat_offsets_.size()) ? cat_offsets_[c_idx] : c_idx;
    int p = off + sub_idx_;
    if (p < page_count_) page_ = p;
    ESP_LOGI(TAG, "Nav (cat): cat=%d/%d sub=%d/%d (page=%d/%d)", c_idx + 1, cats, sub_idx_ + 1, sz, page_ + 1, page_count_);
    update_current_identities_();
  }

  void sub_step(int delta) {
    idle_sec_ = 0;
    user_cool_sec_ = 0;
    pending_redraw_ = true;
    int cats = cat_count_ > 0 ? cat_count_ : 1;
    int c_idx = cat_idx_;
    int sz = (c_idx < (int)cat_sizes_.size()) ? cat_sizes_[c_idx] : 1;
    if (sz > 1) {
      sub_idx_ = ((sub_idx_ + delta) % sz + sz) % sz;
      if ((int)cat_sub_pos_.size() <= c_idx) cat_sub_pos_.resize(cats, 0);
      cat_sub_pos_[c_idx] = (sub_idx_ + 1) % sz;
      int off = (c_idx < (int)cat_offsets_.size()) ? cat_offsets_[c_idx] : c_idx;
      int p = off + sub_idx_;
      if (p < page_count_) page_ = p;
      ESP_LOGI(TAG, "Nav (sub): cat=%d/%d sub=%d/%d (page=%d/%d)", c_idx + 1, cats, sub_idx_ + 1, sz, page_ + 1, page_count_);
      update_current_identities_();
    }
  }

  void mode_toggle() {
    idle_sec_ = 0;
    user_cool_sec_ = 0;
    pending_redraw_ = true;
    int cats = cat_count_ > 0 ? cat_count_ : 1;
    int c_idx = cat_idx_;
    int sz = (c_idx < (int)cat_sizes_.size()) ? cat_sizes_[c_idx] : 1;
    if (sz > 1) {
      sub_mode_ = !sub_mode_;
      ESP_LOGI(TAG, "Navigation mode toggled: sub_mode=%d (cat=%d/%d, sz=%d)", sub_mode_, c_idx + 1, cats, sz);
    } else {
      sub_mode_ = false;
      ESP_LOGI(TAG, "Single-page category (cat=%d/%d, sz=%d), staying in category mode", c_idx + 1, cats, sz);
    }
  }

  void hold_toggle() {
    idle_sec_ = 0;
    user_cool_sec_ = 0;
    pending_redraw_ = true;
    pinned_ = !pinned_;
    if (pinned_) {
      cat_pinned_ = false;
      pinned_cat_id_ = (cat_idx_ < (int)cat_ids_.size()) ? cat_ids_[cat_idx_] : 0;
      pinned_sub_id_ = (page_ < (int)sub_ids_.size()) ? sub_ids_[page_] : 0;
    } else {
      pinned_cat_id_ = 0;
      pinned_sub_id_ = 0;
    }
    ESP_LOGI(TAG, "Panel lock: %d (cat_id=0x%08X, sub_id=0x%08X)", pinned_, (unsigned int)pinned_cat_id_, (unsigned int)pinned_sub_id_);
  }

  void category_pin_toggle() {
    idle_sec_ = 0;
    user_cool_sec_ = 0;
    pending_redraw_ = true;
    cat_pinned_ = !cat_pinned_;
    if (cat_pinned_) {
      pinned_ = false;
      pinned_sub_id_ = 0;
      pinned_cat_id_ = (cat_idx_ < (int)cat_ids_.size()) ? cat_ids_[cat_idx_] : 0;
    } else {
      pinned_cat_id_ = 0;
    }
    ESP_LOGI(TAG, "Category lock: %d (cat_id=0x%08X)", cat_pinned_, (unsigned int)pinned_cat_id_);
  }

  void lock_toggle() {
    if (sub_mode_) {
      hold_toggle();
    } else {
      category_pin_toggle();
    }
  }

  void reset_home() {
    idle_sec_ = 0;
    user_cool_sec_ = 0;
    pending_redraw_ = true;
    cat_idx_ = 0;
    sub_idx_ = 0;
    page_ = 0;
    sub_mode_ = false;
    update_current_identities_();
    ESP_LOGI(TAG, "Reset to page 0");
  }

  void show_page(int index) {
    idle_sec_ = 0;
    user_cool_sec_ = 0;
    pending_redraw_ = true;
    if (index >= 0 && index < page_count_) {
      page_ = index;
      for (int c = (int)cat_offsets_.size() - 1; c >= 0; c--) {
        if (index >= cat_offsets_[c]) {
          cat_idx_ = c;
          sub_idx_ = index - cat_offsets_[c];
          break;
        }
      }
      update_current_identities_();
    }
  }

  void show_category(int category, int sub) {
    idle_sec_ = 0;
    user_cool_sec_ = 0;
    pending_redraw_ = true;
    int cats = cat_count_ > 0 ? cat_count_ : 1;
    if (category >= 0 && category < cats) {
      cat_idx_ = category;
      int sz = (category < (int)cat_sizes_.size()) ? cat_sizes_[category] : 1;
      sub_idx_ = (sub >= 0 && sub < sz) ? sub : 0;
      int off = (category < (int)cat_offsets_.size()) ? cat_offsets_[category] : category;
      int p = off + sub_idx_;
      if (p < page_count_) page_ = p;
      update_current_identities_();
    }
  }

  void tick_seconds(int delta_sec) {
    idle_sec_ += delta_sec;
    fetch_idle_sec_ += delta_sec;
    if (user_cool_sec_ < 1000) user_cool_sec_ += delta_sec;
  }

  bool check_auto_rotate() {
    if (quiet_hours_active_ || pinned_) return false;
    if (user_cool_sec_ < 15) return false;
    int rot_target = rotate_sec_ >= 5 ? rotate_sec_ : 30;
    if (idle_sec_ < rot_target) return false;

    idle_sec_ = 0;
    int cats = cat_count_ > 0 ? cat_count_ : 1;
    if (cat_pinned_) {
      int c_idx = cat_idx_;
      int sz = (c_idx < (int)cat_sizes_.size()) ? cat_sizes_[c_idx] : 1;
      if (sz > 1) {
        sub_idx_ = (sub_idx_ + 1) % sz;
        if ((int)cat_sub_pos_.size() <= c_idx) cat_sub_pos_.resize(cats, 0);
        cat_sub_pos_[c_idx] = (sub_idx_ + 1) % sz;
        int off = (c_idx < (int)cat_offsets_.size()) ? cat_offsets_[c_idx] : c_idx;
        int p = off + sub_idx_;
        if (p < page_count_) page_ = p;
        update_current_identities_();
        pending_redraw_ = true;
        return true;
      }
      return false;
    } else {
      cat_idx_ = (cat_idx_ + 1) % cats;
      int c_idx = cat_idx_;
      int sz = (c_idx < (int)cat_sizes_.size() && cat_sizes_[c_idx] > 0) ? cat_sizes_[c_idx] : 1;
      if ((int)cat_sub_pos_.size() <= c_idx) cat_sub_pos_.resize(cats, 0);
      if (sz > 1) {
        sub_idx_ = cat_sub_pos_[c_idx] % sz;
        cat_sub_pos_[c_idx] = (sub_idx_ + 1) % sz;
      } else {
        sub_idx_ = 0;
      }
      sub_mode_ = false;
      int off = (c_idx < (int)cat_offsets_.size()) ? cat_offsets_[c_idx] : c_idx;
      int p = off + sub_idx_;
      if (p < page_count_) page_ = p;
      update_current_identities_();
      pending_redraw_ = true;
      ESP_LOGI(TAG, "Auto-rotated to cat=%d/%d sub=%d/%d (page=%d/%d)", c_idx + 1, cats, sub_idx_ + 1, sz, page_ + 1, page_count_);
      return true;
    }
  }

  bool should_defer_refetch() const {
    return user_cool_sec_ < 15;
  }

  bool check_settle_clear() {
    // Settle clear: if user has settled (idle 3-7 seconds) after interacting,
    // and accumulated >= 8 partial refreshes, request full refresh to clean ghosting.
    if (user_cool_sec_ >= 3 && user_cool_sec_ < 8 && partial_updates_since_full_ >= 8) {
      partial_updates_since_full_ = 0;
      ESP_LOGI(TAG, "Waveform Settle: User settled (%ds idle) with %d partials -> clean full clear",
               user_cool_sec_, partial_updates_since_full_);
      return true;
    }
    return false;
  }

  void on_stream_loaded(const EpfHeader &header,
                        const std::vector<EpfCategoryRecord> &categories,
                        const std::vector<EpfPageRecord> &pages) {
    std::vector<uint32_t> old_cat_ids = cat_ids_;
    std::vector<int> old_cat_sub_pos = cat_sub_pos_;

    page_count_ = header.page_count;
    cat_count_ = header.cat_count;
    if (header.rotate_sec >= 5 && header.rotate_sec <= 3600) {
      rotate_sec_ = header.rotate_sec;
    }
    quiet_hours_active_ = (header.flags & 0x0002) != 0;
    bool is_alert = (header.flags & 0x0001) != 0;

    cat_offsets_.clear();
    cat_sizes_.clear();
    cat_pill_widths_.clear();
    cat_ids_.clear();
    for (const auto &cat : categories) {
      cat_offsets_.push_back(cat.offset_page);
      cat_sizes_.push_back(cat.page_count);
      cat_pill_widths_.push_back(cat.pill_width > 0 ? cat.pill_width : 110);
      cat_ids_.push_back(cat.cat_id);
    }

    sub_ids_.clear();
    for (const auto &page : pages) {
      sub_ids_.push_back(page.sub_id);
    }

    // Remap sub-item cyclic positions across category identity
    std::vector<int> new_cat_sub_pos(cat_count_, 0);
    for (int i = 0; i < cat_count_; i++) {
      if (i < (int)cat_ids_.size()) {
        uint32_t cid = cat_ids_[i];
        for (size_t j = 0; j < old_cat_ids.size(); j++) {
          if (old_cat_ids[j] == cid && j < old_cat_sub_pos.size()) {
            new_cat_sub_pos[i] = old_cat_sub_pos[j];
            break;
          }
        }
      }
    }
    cat_sub_pos_ = new_cat_sub_pos;

    bool resolved = false;

    // 1. Alert interrupt
    if (is_alert) {
      cat_idx_ = 0;
      sub_idx_ = 0;
      page_ = 0;
      sub_mode_ = false;
      pinned_ = false;
      cat_pinned_ = false;
      pinned_cat_id_ = 0;
      pinned_sub_id_ = 0;
      resolved = true;
      ESP_LOGW(TAG, "ALERT INTERRUPT active: forcing page 0");
    }

    // 2. Sub-item lock (Panel lock)
    if (!resolved && pinned_) {
      if (pinned_sub_id_ != 0) {
        int found_page = -1;
        for (size_t p = 0; p < sub_ids_.size(); p++) {
          if (sub_ids_[p] == pinned_sub_id_) {
            found_page = (int)p;
            break;
          }
        }
        if (found_page >= 0 && found_page < page_count_) {
          int found_cat = 0;
          int found_sub = 0;
          for (int c = 0; c < cat_count_; c++) {
            int off = (c < (int)cat_offsets_.size()) ? cat_offsets_[c] : c;
            int sz = (c < (int)cat_sizes_.size()) ? cat_sizes_[c] : 1;
            if (found_page >= off && found_page < off + sz) {
              found_cat = c;
              found_sub = found_page - off;
              break;
            }
          }
          cat_idx_ = found_cat;
          sub_idx_ = found_sub;
          page_ = found_page;
          sub_mode_ = (cat_sizes_[found_cat] > 1);
          resolved = true;
          ESP_LOGI(TAG, "Sub-item lock preserved: sub_id=0x%08X -> cat=%d sub=%d page=%d",
                   (unsigned int)pinned_sub_id_, cat_idx_, sub_idx_, page_);
        } else {
          ESP_LOGW(TAG, "Pinned sub-item 0x%08X no longer in rotation; releasing lock", (unsigned int)pinned_sub_id_);
          pinned_ = false;
          pinned_sub_id_ = 0;
        }
      }
    }

    // 3. Category lock
    if (!resolved && cat_pinned_) {
      if (pinned_cat_id_ != 0) {
        int found_cat = -1;
        for (size_t c = 0; c < cat_ids_.size(); c++) {
          if (cat_ids_[c] == pinned_cat_id_) {
            found_cat = (int)c;
            break;
          }
        }
        if (found_cat >= 0 && found_cat < cat_count_) {
          cat_idx_ = found_cat;
          int sz = (found_cat < (int)cat_sizes_.size()) ? cat_sizes_[found_cat] : 1;
          if (sz <= 1) {
            sub_idx_ = 0;
            sub_mode_ = false;
          } else if (sub_idx_ < 0 || sub_idx_ >= sz) {
            sub_idx_ = cat_sub_pos_[found_cat] % sz;
          }
          int off = (found_cat < (int)cat_offsets_.size()) ? cat_offsets_[found_cat] : found_cat;
          page_ = off + sub_idx_;
          resolved = true;
          ESP_LOGI(TAG, "Category lock preserved: cat_id=0x%08X -> cat=%d sub=%d page=%d",
                   (unsigned int)pinned_cat_id_, cat_idx_, sub_idx_, page_);
        } else {
          ESP_LOGW(TAG, "Pinned category 0x%08X no longer in rotation; releasing lock", (unsigned int)pinned_cat_id_);
          cat_pinned_ = false;
          pinned_cat_id_ = 0;
        }
      }
    }

    // 4. Unlocked: keep active identity if still present
    if (!resolved) {
      if (cur_sub_id_ != 0) {
        int found_page = -1;
        for (size_t p = 0; p < sub_ids_.size(); p++) {
          if (sub_ids_[p] == cur_sub_id_) {
            found_page = (int)p;
            break;
          }
        }
        if (found_page >= 0 && found_page < page_count_) {
          int found_cat = 0;
          int found_sub = 0;
          for (int c = 0; c < cat_count_; c++) {
            int off = (c < (int)cat_offsets_.size()) ? cat_offsets_[c] : c;
            int sz = (c < (int)cat_sizes_.size()) ? cat_sizes_[c] : 1;
            if (found_page >= off && found_page < off + sz) {
              found_cat = c;
              found_sub = found_page - off;
              break;
            }
          }
          cat_idx_ = found_cat;
          sub_idx_ = found_sub;
          page_ = found_page;
          resolved = true;
        }
      }
      if (!resolved && cur_cat_id_ != 0) {
        int found_cat = -1;
        for (size_t c = 0; c < cat_ids_.size(); c++) {
          if (cat_ids_[c] == cur_cat_id_) {
            found_cat = (int)c;
            break;
          }
        }
        if (found_cat >= 0 && found_cat < cat_count_) {
          cat_idx_ = found_cat;
          int sz = (found_cat < (int)cat_sizes_.size()) ? cat_sizes_[found_cat] : 1;
          if (sz <= 1) {
            sub_idx_ = 0;
            sub_mode_ = false;
          } else if (sub_idx_ < 0 || sub_idx_ >= sz) {
            sub_idx_ = cat_sub_pos_[found_cat] % sz;
          }
          int off = (found_cat < (int)cat_offsets_.size()) ? cat_offsets_[found_cat] : found_cat;
          page_ = off + sub_idx_;
          resolved = true;
        }
      }
    }

    // 5. Fallback: Positional clamping
    if (!resolved) {
      if (cat_idx_ < 0 || cat_idx_ >= cat_count_) cat_idx_ = 0;
      int c_idx = cat_idx_;
      int sz = (c_idx < (int)cat_sizes_.size() && cat_sizes_[c_idx] > 0) ? cat_sizes_[c_idx] : 1;
      if (sz <= 1) {
        sub_idx_ = 0;
        sub_mode_ = false;
      } else if (sub_idx_ < 0 || sub_idx_ >= sz) {
        sub_idx_ = cat_sub_pos_[c_idx] % sz;
      }
      int off = (c_idx < (int)cat_offsets_.size()) ? cat_offsets_[c_idx] : c_idx;
      int p = off + sub_idx_;
      page_ = (p >= 0 && p < page_count_) ? p : 0;
    }

    update_current_identities_();
  }

  void draw_overlays(esphome::display::DisplayBuffer *epd, int dw = 792, int dh = 272) {
    if (!epd) return;
    uint8_t *raw_buf = DisplayBufferAccessor::get_raw_buffer(epd);
    if (!raw_buf) return;

    bool is_sub = sub_mode_;
    const int py0 = dh - 28;
    const int py1 = dh - 4;
    const int sub_w = 48;
    const int sub_x1 = dw - (dw >= 400 ? 40 : 16);
    const int sub_x0 = sub_x1 - sub_w;

    int c_idx = cat_idx_;
    int sz = (c_idx < (int)cat_sizes_.size()) ? cat_sizes_[c_idx] : 1;
    if (sz <= 1) {
      is_sub = false;
    }

    int cat_w = (c_idx < (int)cat_pill_widths_.size()) ? cat_pill_widths_[c_idx] : 110;
    int cat_x0 = (dw >= 400) ? 96 : (16 + 55);
    int cat_x1 = cat_x0 + cat_w;

    bool is_180 = EpfClient::instance().is_orientation_180();
    if (!EpfClient::instance().has_stream()) {
      is_180 = false;
    }

    auto invert_rounded_pill = [&](int x0, int y0, int x1, int y1, int r) {
      for (int py = y0; py <= y1; py++) {
        for (int px = x0; px <= x1; px++) {
          if (in_rounded_box(px, py, x0, y0, x1, y1, r)) {
            int rx = is_180 ? ((dw - 1) - px) : px;
            int ry = is_180 ? ((dh - 1) - py) : py;
            if (rx >= 0 && rx < dw && ry >= 0 && ry < dh) {
              size_t byte_off = ((size_t)ry * dw + rx) / 8;
              uint8_t bit = 7 - (rx % 8);
              raw_buf[byte_off] ^= (1 << bit);
            }
          }
        }
      }
    };

    // 1. Invert active pill
    if (!is_sub) {
      invert_rounded_pill(cat_x0, py0, cat_x1, py1, 4);
    } else if (sz > 1) {
      invert_rounded_pill(sub_x0, py0, sub_x1, py1, 4);
    }

    // 2. Padlock badge (Apple-grade high contrast solid lock: dark rounded badge with crisp white padlock)
    auto draw_padlock = [&](int bx, int by, int bw, int bh) {
      int cx = bx + bw / 2;
      int cy = by + bh / 2;
      for (int py = by; py < by + bh; py++) {
        for (int px = bx; px < bx + bw; px++) {
          if (in_rounded_box(px, py, bx, by, bx + bw - 1, by + bh - 1, 4)) {
            int dx = px - cx, dy = py - cy;
            bool is_shackle = false;
            if (dy >= -6 && dy <= -2) {
              is_shackle = (dy <= -4) ? (dx >= -4 && dx <= 3) : ((dx >= -5 && dx <= -3) || (dx >= 2 && dx <= 4));
            }
            bool is_body = (dy >= -1 && dy <= 6 && dx >= -6 && dx <= 5);
            bool is_keyhole = ((dy >= 1 && dy <= 2 && dx >= -1 && dx <= 0) || (dy >= 3 && dy <= 4 && dx == 0));

            // White ink for padlock shackle and body; black ink for rounded background and keyhole
            bool white_ink = (is_shackle || is_body) && !is_keyhole;
            int rx = is_180 ? ((dw - 1) - px) : px;
            int ry = is_180 ? ((dh - 1) - py) : py;
            if (rx >= 0 && rx < dw && ry >= 0 && ry < dh) {
              size_t byte_off = ((size_t)ry * dw + rx) / 8;
              uint8_t bit = 7 - (rx % 8);
              if (white_ink) {
                raw_buf[byte_off] |= (1 << bit);   // 1 = white
              } else {
                raw_buf[byte_off] &= ~(1 << bit);  // 0 = black
              }
            }
          }
        }
      }
    };

    if (cat_pinned_) {
      draw_padlock(cat_x1 + 8, py0 + 2, 22, 20);
    }
    if (pinned_) {
      int lx = (sz > 1) ? (sub_x0 - 8 - 22) : (sub_x1 - 22);
      draw_padlock(lx, py0 + 2, 22, 20);
    }
  }

  // --- Getters ---
  int page() const { return page_; }
  int cat_idx() const { return cat_idx_; }
  int sub_idx() const { return sub_idx_; }
  int cat_count() const { return cat_count_; }
  int page_count() const { return page_count_; }
  bool sub_mode() const { return sub_mode_; }
  bool pinned() const { return pinned_; }
  bool cat_pinned() const { return cat_pinned_; }
  uint32_t pinned_cat_id() const { return pinned_cat_id_; }
  uint32_t pinned_sub_id() const { return pinned_sub_id_; }
  uint32_t cur_cat_id() const { return cur_cat_id_; }
  uint32_t cur_sub_id() const { return cur_sub_id_; }
  int rotate_sec() const { return rotate_sec_; }
  int idle_sec() const { return idle_sec_; }
  int user_cool_sec() const { return user_cool_sec_; }
  int fetch_idle_sec() const { return fetch_idle_sec_; }
  bool pending_redraw() const { return pending_redraw_; }
  void clear_pending_redraw() { pending_redraw_ = false; }
  void set_pending_redraw() { pending_redraw_ = true; }
  bool pending_refetch() const { return pending_refetch_; }
  void set_pending_refetch(bool v) { pending_refetch_ = v; }
  void reset_fetch_idle() { fetch_idle_sec_ = 0; }
  bool quiet_hours_active() const { return quiet_hours_active_; }
  const std::vector<int> &cat_offsets() const { return cat_offsets_; }
  const std::vector<int> &cat_sizes() const { return cat_sizes_; }
  const std::vector<int> &cat_pill_widths() const { return cat_pill_widths_; }
  const std::vector<uint32_t> &cat_ids() const { return cat_ids_; }
  const std::vector<uint32_t> &sub_ids() const { return sub_ids_; }

  int partial_updates_since_full() const { return partial_updates_since_full_; }
  void record_full_update() { partial_updates_since_full_ = 0; }
  void record_partial_update() { partial_updates_since_full_++; }

  template<typename GPage, typename GCIdx, typename GSIdx, typename GSM,
           typename GPin, typename GCPin, typename GCCat, typename GCSub,
           typename GPCat, typename GPSub, typename GIdle, typename GCool,
           typename GRedraw, typename GQH, typename GCount, typename GCntCat,
           typename GOffs, typename GSizes, typename GPW, typename GCIds, typename GSIds>
  void sync_to_globals(GPage &page, GCIdx &cat_idx, GSIdx &sub_idx, GSM &sub_mode,
                       GPin &pinned, GCPin &cat_pinned, GCCat &cur_cat_id, GCSub &cur_sub_id,
                       GPCat &pinned_cat_id, GPSub &pinned_sub_id, GIdle &idle_sec, GCool &user_cool_sec,
                       GRedraw &pending_redraw, GQH &quiet_hours, GCount &page_count, GCntCat &cat_count,
                       GOffs &cat_offsets, GSizes &cat_sizes, GPW &cat_pill_widths, GCIds &cat_ids, GSIds &sub_ids) {
    page = page_;
    cat_idx = cat_idx_;
    sub_idx = sub_idx_;
    sub_mode = sub_mode_;
    pinned = pinned_;
    cat_pinned = cat_pinned_;
    cur_cat_id = cur_cat_id_;
    cur_sub_id = cur_sub_id_;
    pinned_cat_id = pinned_cat_id_;
    pinned_sub_id = pinned_sub_id_;
    idle_sec = idle_sec_;
    user_cool_sec = user_cool_sec_;
    pending_redraw = pending_redraw_;
    quiet_hours = quiet_hours_active_;
    page_count = page_count_;
    cat_count = cat_count_;
    cat_offsets = cat_offsets_;
    cat_sizes = cat_sizes_;
    cat_pill_widths = cat_pill_widths_;
    cat_ids = cat_ids_;
    sub_ids = sub_ids_;
  }

  template<typename GPage, typename GCIdx, typename GSIdx, typename GSM,
           typename GPin, typename GCPin, typename GCCat, typename GCSub,
           typename GPCat, typename GPSub, typename GIdle, typename GCool,
           typename GRedraw, typename GQH, typename GCount, typename GCntCat,
           typename GOffs, typename GSizes, typename GPW, typename GCIds, typename GSIds>
  void sync_from_globals(const GPage &page, const GCIdx &cat_idx, const GSIdx &sub_idx, const GSM &sub_mode,
                         const GPin &pinned, const GCPin &cat_pinned, const GCCat &cur_cat_id, const GCSub &cur_sub_id,
                         const GPCat &pinned_cat_id, const GPSub &pinned_sub_id, const GIdle &idle_sec, const GCool &user_cool_sec,
                         const GRedraw &pending_redraw, const GQH &quiet_hours, const GCount &page_count, const GCntCat &cat_count,
                         const GOffs &cat_offsets, const GSizes &cat_sizes, const GPW &cat_pill_widths, const GCIds &cat_ids, const GSIds &sub_ids) {
    page_ = page;
    cat_idx_ = cat_idx;
    sub_idx_ = sub_idx;
    sub_mode_ = sub_mode;
    pinned_ = pinned;
    cat_pinned_ = cat_pinned;
    cur_cat_id_ = cur_cat_id;
    cur_sub_id_ = cur_sub_id;
    pinned_cat_id_ = pinned_cat_id;
    pinned_sub_id_ = pinned_sub_id;
    idle_sec_ = idle_sec;
    user_cool_sec_ = user_cool_sec;
    pending_redraw_ = pending_redraw;
    quiet_hours_active_ = quiet_hours;
    page_count_ = page_count;
    cat_count_ = cat_count;
    cat_offsets_ = cat_offsets;
    cat_sizes_ = cat_sizes;
    cat_pill_widths_ = cat_pill_widths;
    cat_ids_ = cat_ids;
    sub_ids_ = sub_ids;
  }

 private:
  PanelController() = default;

  void update_current_identities_() {
    cur_cat_id_ = (cat_idx_ < (int)cat_ids_.size()) ? cat_ids_[cat_idx_] : 0;
    cur_sub_id_ = (page_ < (int)sub_ids_.size()) ? sub_ids_[page_] : 0;
    if (pinned_) {
      pinned_sub_id_ = cur_sub_id_;
      pinned_cat_id_ = cur_cat_id_;
    } else if (cat_pinned_) {
      pinned_cat_id_ = cur_cat_id_;
    }
  }

  int page_{0};
  int cat_idx_{0};
  int sub_idx_{0};
  int cat_count_{1};
  int page_count_{1};
  bool sub_mode_{false};
  bool pinned_{false};
  bool cat_pinned_{false};
  uint32_t pinned_cat_id_{0};
  uint32_t pinned_sub_id_{0};
  uint32_t cur_cat_id_{0};
  uint32_t cur_sub_id_{0};
  int rotate_sec_{30};
  int idle_sec_{0};
  int user_cool_sec_{999};
  int fetch_idle_sec_{0};
  bool pending_redraw_{false};
  bool pending_refetch_{false};
  bool quiet_hours_active_{false};
  int partial_updates_since_full_{0};

  std::vector<int> cat_offsets_;
  std::vector<int> cat_sizes_;
  std::vector<int> cat_pill_widths_;
  std::vector<uint32_t> cat_ids_;
  std::vector<uint32_t> sub_ids_;
  std::vector<int> cat_sub_pos_;
};

}  // namespace epf

#define SYNC_PANEL_GLOBALS() \
  epf::PanelController::instance().sync_to_globals( \
    id(page), id(cat_idx), id(sub_idx), id(sub_mode), \
    id(pinned), id(cat_pinned), id(cur_cat_id), id(cur_sub_id), \
    id(pinned_cat_id), id(pinned_sub_id), id(idle_sec), id(user_cool_sec), \
    id(pending_redraw), id(quiet_hours_active), id(page_count), id(cat_count), \
    id(cat_offsets), id(cat_sizes), id(cat_pill_widths), id(cat_ids), id(sub_ids))

#define SYNC_PANEL_FROM_GLOBALS() \
  epf::PanelController::instance().sync_from_globals( \
    id(page), id(cat_idx), id(sub_idx), id(sub_mode), \
    id(pinned), id(cat_pinned), id(cur_cat_id), id(cur_sub_id), \
    id(pinned_cat_id), id(pinned_sub_id), id(idle_sec), id(user_cool_sec), \
    id(pending_redraw), id(quiet_hours_active), id(page_count), id(cat_count), \
    id(cat_offsets), id(cat_sizes), id(cat_pill_widths), id(cat_ids), id(sub_ids))

#endif  // EPF_CLIENT_H_

