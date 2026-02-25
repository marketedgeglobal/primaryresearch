# How to add GitHub Secrets

## Required secrets

- GOOGLE_SERVICE_ACCOUNT_KEY: Paste the full JSON service account key.
- SPREADSHEET_ID: The Google Sheets ID from the sheet URL.
- AI_API_KEY: API key for the chosen AI provider (use `__MOCK__` for local dry runs).
- GITHUB_TOKEN: Provided automatically by Actions; use a PAT only if you need extra scopes.

## How to add

1. Go to GitHub: Settings -> Secrets and variables -> Actions -> New repository secret.
2. Set the name (for example, GOOGLE_SERVICE_ACCOUNT_KEY).
3. Paste the secret value (for example, paste the full JSON into the value field).
4. Save the secret.

## Security notes

- Do not commit secrets to the repo.
- Rotate keys periodically and remove unused keys.
- Limit the service account to the specific sheet.
- Use readonly scope if possible.

Test: run `tests/run_local_test.sh` with `AI_API_KEY=__MOCK__` and `/tmp/gservice.json` present.

Suggested commit message: "docs: add README_SECRETS.md with instructions for GitHub Secrets"
