# SoyPaq WMS Changelog

This public changelog starts from the sanitized staging baseline. Earlier
private development notes were intentionally removed before publication.

## v0.4.3-public - 2026-08-30

Public staging baseline.

**Packaging**
- Prepared the app for a Frappe/ERPNext v15 bench.
- Added Frappe Cloud compatibility metadata in `pyproject.toml`.
- Kept app-owned DocTypes exported as JSON with matching controller files.
- Added CI checks for linting, frontend build output, DocType contract, and
  clean-site installation.

**Frontend**
- Committed the built Vue/Vite WMS bundle under `soypaq/public/wms/`.
- Set the Vite asset base to `/assets/soypaq/wms/`.
- Upgraded frontend build tooling and verified `npm audit --omit=dev` reports no
  vulnerabilities.

**Security / public repo hygiene**
- Replaced private project notes with generic public documentation.
- Replaced runtime placeholder company, customer, naming-series, and sender
  address values with generic examples.
- Confirmed no `.env`, API key, database dump, backup archive, private key, or
  credential file is tracked.
