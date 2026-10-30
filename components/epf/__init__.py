import esphome.codegen as cg
import esphome.config_validation as cv
from esphome.components import esp32

CODEOWNERS = ["@bek00letz"]
# PSRAM when the board has it (two frame buffers there); without, one in its own RAM.
DEPENDENCIES = ["esp32", "display"]

epf_ns = cg.esphome_ns.namespace("epf")

# Pages arrive deflated and are inflated as they're shown (epf_client.h): false is the way
# back, every page as it is (firmware_gen.DEFLATE_FRAMES).
CONF_DEFLATE = "deflate"
CONFIG_SCHEMA = cv.Schema({cv.Optional(CONF_DEFLATE, default=True): cv.boolean})


async def to_code(config):
    if config[CONF_DEFLATE]:
        cg.add_define("USE_EPF_DEFLATE")
    # The client talks HTTP through ESP-IDF directly, and ESPHome leaves that
    # component out of the build unless something asks for it.
    esp32.include_builtin_idf_component("esp_http_client")
    # https addresses (a screen away from home) are checked against the public
    # certificate authorities ESP-IDF ships.
    esp32.add_idf_sdkconfig_option("CONFIG_MBEDTLS_CERTIFICATE_BUNDLE", True)
    esp32.add_idf_sdkconfig_option("CONFIG_MBEDTLS_CERTIFICATE_BUNDLE_DEFAULT_FULL", True)
    cg.add_global(cg.RawStatement('#include "esphome/components/epf/epf_client.h"'))
