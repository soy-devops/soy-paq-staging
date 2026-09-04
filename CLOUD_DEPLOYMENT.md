# Frappe Cloud Deployment

This app is prepared for a Frappe Cloud bench running Frappe/ERPNext v16. The
frontend build tooling expects Node 20.19 or newer.

## Add the App

1. Create or choose a Frappe Cloud bench on Frappe/ERPNext v16.
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
frappe = ">=16.0.0,<17.0.0"
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
python scripts/check_sanitization.py
python -m compileall -q soypaq scripts
ruff check soypaq scripts
ruff format --check soypaq scripts
cd ui && npm ci && npm run build && npm audit --omit=dev
git diff --exit-code -- soypaq/public/wms
```

`check_sanitization.py` is a CI-enforced gate, not just a local suggestion: it
fails the build if a real client name shows up in a public file, or if this
file's stated Frappe version drifts from `pyproject.toml`'s pin. Add new
client names to its `BANNED_TERMS` list as they're onboarded.

It also runs as a **pre-commit hook**, catching the same problem before it's
even saved to git history. One-time setup per machine:

```bash
git config core.hooksPath .githooks
```

After that, every `git commit` in this repo runs the check automatically. A
blocked commit prints exactly which file/line is wrong.

## Day-to-Day: Getting a Change from Here to Frappe Cloud

This is the only sequence that actually ships something. Skipping the last
step is the single most common mistake - a `git push` alone changes nothing
on the live site.

1. **Commit your change** in this repo (`main` branch for production,
   `staging` for the staging bench). The pre-commit hook above runs
   automatically and blocks the commit if it finds a problem.
2. **Push to GitHub:**
   ```bash
   git push origin main       # or: git push origin staging
   ```
3. **Go to Frappe Cloud → your bench → the target site → Deploy.** Frappe
   Cloud does not auto-deploy on push by default - pushing only updates the
   code sitting on GitHub. You (or a configured auto-deploy rule, if you've
   set one up in Frappe Cloud's bench settings) must trigger the actual
   deploy for the site to pick up the new commit.
4. **Watch the Deploy tab until it shows success**, then spot-check the
   feature in the browser on that site. A deploy can fail (e.g. a version
   mismatch, a failed migration) even after the push succeeded - "pushed"
   and "deployed" are not the same thing.

If you only remember one rule: **GitHub has the code the moment you push;
Frappe Cloud does not have it until a Deploy finishes successfully.**

For a final go/no-go, install from the public repository into a clean local
Frappe/ERPNext v16 bench and run:

```bash
bench --site <site-name> install-app soypaq
bench --site <site-name> execute soypaq.tests.ci_smoke.run
```

## Moving a Live Site to a New Bench

Use this checklist whenever moving an existing Frappe Cloud site (e.g. a live
production site on the Shared bench) onto a private bench, or onto an upgraded
version of a private bench. Skipping the inventory step below is what caused a
mismatched bench, a wrong Frappe version, and a missing-apps rebuild the first
time this was done.

**Step 0 — Inventory the live site first, before creating or touching any bench.**

- Which bench/server is it actually on right now? (Shared bench and a private
  bench are completely separate; deploying one does nothing for the other.)
- What Frappe/ERPNext version is it running?
- Full list of installed apps (Sites -> the site -> Apps).

**Step 1 — Match the target bench to that inventory, not the other way around.**

- Bench's Frappe Framework version must be the same as the live site's current
  version, never lower. A site can only move to an equal or newer version.
- Add the exact app list from Step 0, plus this custom app. Don't default to
  whatever a fresh bench happens to start with.

**Step 2 — Deploy the bench and confirm clean before going near the live site.**

- All apps should show "Latest Version" with no failures in the Deploys tab.
- Check that this app's own version pins (`pyproject.toml` Python/Frappe
  constraints) match what the bench actually runs, to avoid a validation
  failure like "Incompatible Python version" during deploy.

**Step 3 — Decide test-site vs. direct move, as a conscious tradeoff.**

- A throwaway test site costs money (private-bench sites have no free tier,
  ~$25/mo minimum). Skipping it is a deliberate risk decision, not a default.

**Step 4 — Move the live site to the new bench ("Move to Private Bench").**

- This is the one step that touches real data (it installs apps and runs
  migrations against the site's live database), so it should be the last
  step, only after Steps 0-3 are clean.

**Step 5 — Verify after the move.**

- Site's Apps tab shows everything expected, all Active.
- Spot-check the actual feature in the browser.
- Run `soypaq.tests.ci_smoke.run` against the live site.

**Step 6 — Clean up.**

- Archive the old bench once the new one is confirmed stable, so it doesn't
  linger as a half-configured leftover.
