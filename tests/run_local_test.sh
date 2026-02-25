#!/usr/bin/env bash
set -euo pipefail

if [[ ! -f /tmp/gservice.json ]]; then
  echo "Error: /tmp/gservice.json not found. Place your service account JSON there first." >&2
  exit 1
fi

if [[ -z "${SPREADSHEET_ID:-}" ]]; then
  echo "Error: SPREADSHEET_ID is not set." >&2
  exit 1
fi

AI_API_KEY="${AI_API_KEY:-__MOCK__}"

python scripts/fetch_sheet.py --service-account /tmp/gservice.json --spreadsheet-id "$SPREADSHEET_ID" --range "Sheet1!A1:J50" --out rows.json
python scripts/call_ai.py --input rows.json --run-id local-test --api-key "$AI_API_KEY" --out analysis.json
python scripts/validate_schema.py --schema schemas/analysis_schema.json --input analysis.json

echo "Local end-to-end dry run passed."

# Suggested commit message: chore: add local end-to-end test script
