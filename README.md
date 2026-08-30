# SoyPaq WMS

Mobile-first warehouse management app for ERPNext. The app supports a basic
Receive -> Pick -> Pack -> Ship flow using custom Frappe DocTypes and ERPNext
stock/accounting documents.

This repository is intentionally sanitized for public staging use. It contains
application code, DocType schema, frontend source, and committed frontend build
assets. It does not contain operational data, database backups, API keys, or
site credentials.

## Repository Layout

| Path | What it is |
|---|---|
| `soypaq/api.py` | Whitelisted endpoints used by the mobile WMS frontend |
| `soypaq/soypaq/doctype/` | App-owned DocType JSON and controller files |
| `soypaq/patches/` | Migrations for existing installed sites |
| `soypaq/install.py` | Fresh-install setup hooks |
| `soypaq/public/wms/` | Committed Vite build output served by Frappe |
| `ui/` | Vue 3 + Vite frontend source |
| `scripts/check_doctypes.py` | Schema/controller contract guard |

## Deployment Notes

Frappe Cloud installs custom apps from a Git repository. This app is prepared for
a Frappe/ERPNext v15 bench and declares compatibility in `pyproject.toml`.

Use a separate branch per environment:

| Branch | Purpose |
|---|---|
| `staging` | Cloud staging bench |
| `main` | Production bench after staging verification |

The planned public staging repository is:

```text
https://github.com/soy-devops/soy-paq-staging
```

After that repository exists:

```bash
git remote add origin https://github.com/soy-devops/soy-paq-staging.git
git push -u origin main staging
```

Then add the app in Frappe Cloud from that GitHub repository and install
`soypaq` on a v15 ERPNext site.

## Secrets

Do not commit secrets to this repository.

Shipping labels require a Shippo API token:

```text
SHIPPO_API_KEY=<set in Frappe Cloud, not in git>
```

Configure that value as a Frappe Cloud site/bench secret or environment value
before generating labels. Use a test token for staging and a live token only
after real sender/recipient/parcel capture is configured.

## Frontend Build

Frappe Cloud installs the Python app but does not run this nested frontend build.
For that reason, the compiled bundle in `soypaq/public/wms/` is committed.

After changing frontend source:

```bash
cd ui
npm ci
npm run build
```

Commit both the source changes and the generated `soypaq/public/wms/` changes.

## Local Checks

```bash
python scripts/check_doctypes.py
python -m compileall -q soypaq scripts
ruff check soypaq scripts
ruff format --check soypaq scripts
cd ui && npm ci && npm run build && npm audit --omit=dev
```

For a final install check, clone this app into a clean Frappe/ERPNext v15 bench,
install it on a fresh site, and run:

```bash
bench --site <site-name> execute soypaq.tests.ci_smoke.run
```

## Public Repo Hygiene

- Keep sample names, addresses, customers, warehouses, and credentials generic.
- Keep operational data in site imports/backups, not in git.
- Keep secrets in Frappe Cloud or the hosting provider's secret manager.
- Rewrite history before making a previously private staging repo public if any
  private notes were ever committed.

## License

MIT
