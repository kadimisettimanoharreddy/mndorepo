#!/usr/bin/env bash
set -euo pipefail
: "${AZURE_OPENAI_KEY:?set AZURE_OPENAI_KEY}"
exec python -m app.main
