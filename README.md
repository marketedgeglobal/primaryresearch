# primaryresearch

Primary Research Document Analysis pipeline for weekly Google Sheets data.

## Required Secrets (GitHub)

- `GOOGLE_SERVICE_ACCOUNT_KEY`: JSON service account key (full JSON string).
- `SPREADSHEET_ID`: ID of the Google Sheet.
- `AI_API_KEY`: Provider API key (use `__MOCK__` for dry runs).

## Quick Start (Local)

1. Create a virtual environment and install dependencies:
	- `python -m venv .venv`
	- `source .venv/bin/activate`
	- `pip install -r requirements.txt`
2. Place the service account JSON at `/tmp/gservice.json`.
3. Export environment variables:
	- `export SPREADSHEET_ID=...`
	- `export AI_API_KEY=__MOCK__`
4. Run the local test:
	- `tests/run_local_test.sh`

## Outputs

- `rows.json`: Raw rows pulled from the sheet.
- `analysis.json`: Latest analysis output.
- `analyses/weekly-<run_id>.json`: Archived analysis outputs from Actions.

## Testing Instructions

After placing `/tmp/gservice.json` and setting `SPREADSHEET_ID` and `AI_API_KEY`,
run:

- `tests/run_local_test.sh`

## Provider Notes

Update `scripts/call_ai.py` to implement the provider-specific API call.
There is a TODO placeholder that raises a clear error until configured.
