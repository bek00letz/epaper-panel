import esphome.codegen as cg
import esphome.config_validation as cv

CODEOWNERS = ["@bek00letz"]

epf_ns = cg.esphome_ns.namespace("epf")

CONFIG_SCHEMA = cv.Schema({})


async def to_code(config):
    cg.add_global(cg.RawStatement('#include "esphome/components/epf/epf_client.h"'))
