#!/usr/bin/env bash
set -euo pipefail

if [[ ! -f /tmp/gservice.json ]]; then
  echo "Missing /tmp/gservice.json"
  exit 1
fi

if [[ -z "${AI_API_KEY:-}" ]]; then
  echo "Missing AI_API_KEY (use __MOCK__ for dry run)"
  exit 1
fi

if [[ -z "${SPREADSHEET_ID:-}" ]]; then
  echo "Missing SPREADSHEET_ID"
  exit 1
fi

python scripts/fetch_sheet.py --service-account /tmp/gservice.json --output rows.json
python scripts/call_ai.py --rows rows.json --output analysis.json
python scripts/validate_schema.py --analysis analysis.json --schema schemas/analysis_schema.json

echo "Local test completed successfully"
