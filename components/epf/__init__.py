import esphome.codegen as cg
import esphome.config_validation as cv
from esphome.components import esp32

CODEOWNERS = ["@bek00letz"]
DEPENDENCIES = ["esp32", "psram", "display"]

epf_ns = cg.esphome_ns.namespace("epf")

CONFIG_SCHEMA = cv.Schema({})


async def to_code(config):
    # The client talks HTTP through ESP-IDF directly, and ESPHome leaves that
    # component out of the build unless something asks for it.
    esp32.include_builtin_idf_component("esp_http_client")
    # https addresses (a screen away from home) are checked against the public
    # certificate authorities ESP-IDF ships.
    esp32.add_idf_sdkconfig_option("CONFIG_MBEDTLS_CERTIFICATE_BUNDLE", True)
    esp32.add_idf_sdkconfig_option("CONFIG_MBEDTLS_CERTIFICATE_BUNDLE_DEFAULT_FULL", True)
    cg.add_global(cg.RawStatement('#include "esphome/components/epf/epf_client.h"'))
