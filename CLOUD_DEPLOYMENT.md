# Frappe Cloud Deployment

This app is prepared for a Frappe Cloud bench running Frappe/ERPNext v15. The
frontend build tooling expects Node 20.19 or newer.

## Add the App

1. Create or choose a Frappe Cloud bench on Frappe/ERPNext v15.
2. Ensure ERPNext is installed on the bench.
3. Add this custom app from the public staging repository:

   ```text
   https://github.com/soy-devops/soy-paq-staging
   ```

4. Track `staging` for staging and `main` for production.
5. Install `soypaq` on the target site.

The app declares Frappe compatibility in `pyproject.toml`:

```toml
[tool.bench.frappe-dependencies]
frappe = ">=15.0.0,<16.0.0"
```

## Secrets

Do not commit API keys or credentials to this repository.

Required for shipping labels:

```text
SHIPPO_API_KEY=<your Shippo token>
```

Set this in Frappe Cloud as a site/bench secret or environment value so it is
available to the web process and any background workers that may generate
labels. After changing it, redeploy or restart the affected processes.

Use test credentials in staging. Use live credentials only after real
sender/recipient address capture and parcel details are configured.

## Data

Code deploys through Git. Operational data does not.

Populate items, customers, warehouses, stock balances, prices, and accounting
records through ERPNext data import or controlled migration steps. Opening stock
should be represented with normal ERPNext stock documents, not by writing
directly to derived tables.

## Pre-Deploy Checks

Run these before pushing a branch that a Frappe Cloud bench tracks:

```bash
python scripts/check_doctypes.py
python -m compileall -q soypaq scripts
ruff check soypaq scripts
ruff format --check soypaq scripts
cd ui && npm ci && npm run build && npm audit --omit=dev
git diff --exit-code -- soypaq/public/wms
```

For a final go/no-go, install from the public repository into a clean local
Frappe/ERPNext v15 bench and run:

```bash
bench --site <site-name> install-app soypaq
bench --site <site-name> execute soypaq.tests.ci_smoke.run
```
