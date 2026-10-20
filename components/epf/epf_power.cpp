// What the panel keeps through deep sleep, for Low Power Mode (PowerPolicy).
// RTC memory: kept while it sleeps, cleared by a power cut or a reset.
#include "esp_attr.h"
#include "epf_core.h"

namespace epf {

RTC_DATA_ATTR Remembered g_remembered;
RTC_DATA_ATTR int64_t g_slept_at_us;

}  // namespace epf
