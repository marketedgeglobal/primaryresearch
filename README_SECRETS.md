# How to add GitHub Secrets

## Required secrets

- **GOOGLE_SERVICE_ACCOUNT_KEY** — Paste the full JSON service account key.
- **SPREADSHEET_ID** — The Google Sheets spreadsheet ID (from the sheet URL).
- **AI_API_KEY** — API key for the chosen AI provider (allow `__MOCK__` for local dry runs).
- **GITHUB_TOKEN** — Provided automatically by Actions; use a PAT only when you need permissions beyond the default token.

## How to add

1. Open your repository on GitHub.
2. Go to **Settings → Secrets and variables → Actions**.
3. Click **New repository secret**.
4. Enter the secret name exactly (for example, `GOOGLE_SERVICE_ACCOUNT_KEY`).
5. Paste the value and save.

Example: For `GOOGLE_SERVICE_ACCOUNT_KEY`, paste the full JSON key into the secret value field exactly as copied.

## Security notes

- Do not commit secrets to the repository.
- Rotate keys regularly and remove unused keys.
- Limit service account access to only the required sheet.
- Use readonly scope when possible.

Local test: Place the service account JSON at `/tmp/gservice.json`, then run `SPREADSHEET_ID=<ID> AI_API_KEY=__MOCK__ bash tests/run_local_test.sh`.

Suggested commit message: `docs: add README_SECRETS.md with instructions for GitHub Secrets`
