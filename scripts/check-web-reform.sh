#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT"
bun scripts/dev/check_toolkit.ts
node vendor/pi-web/node_modules/typescript/bin/tsc --noEmit -p vendor/pi-web
node --test vendor/pi-web/lib/pending-requests.test.mjs vendor/pi-web/lib/message-display.test.mjs
