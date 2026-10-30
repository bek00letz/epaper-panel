#!/bin/bash
# Sets up the AI usage reporter from this checkout (no download): ./setup.sh --address URL --code CODE
# The code and the address are in the editor, Settings › AI usage › Connect a computer.
exec bash "$(cd "$(dirname "$0")" && pwd)/install.sh" --from "$(cd "$(dirname "$0")" && pwd)" "$@"
