# SoyPaq WMS Project Notes

This is the public-safe project reference for the SoyPaq WMS custom Frappe app.
It intentionally uses generic examples and placeholders only.

## Purpose

SoyPaq WMS is a mobile-first warehouse workflow app for ERPNext. It supports:

- Receive inbound goods.
- Pick items from storage.
- Pack items into outbound containers.
- Ship packed orders and record stock movement.

The app is designed to run inside ERPNext and uses app-owned DocTypes plus
ERPNext stock documents. It is not a standalone inventory database.

## Architecture

- Backend API: `soypaq/api.py`
- Frontend source: `ui/`
- Frontend build output: `soypaq/public/wms/`
- Public page shell: `soypaq/www/soypaq-wms.html`
- DocTypes: `soypaq/soypaq/doctype/`
- Fresh install hook: `soypaq/install.py`
- Migration patches: `soypaq/patches/`

## Data Model

The app includes DocTypes for:

- Inbound ASN and child rows.
- Inbound Package and child rows.
- Pick Task and child rows.
- Pack Task and child rows.
- Shipment Task and child rows.
- Receiving Desk.

DocType schema belongs in source-controlled JSON. Production sites should not
create or edit this app's schema directly in Desk.

## Generic Defaults

This public repo uses generic placeholders:

- Default company: `Example Company`
- Default customer: `Example Customer`
- Example sender address: non-secret placeholder data
- Shipping API token: `SHIPPO_API_KEY`, configured outside git

Replace these through site configuration, data setup, or future feature work
before using live operational data.

## Deployment

The planned public staging repository is:

```text
https://github.com/soy-devops/soy-paq-staging
```

Use a Frappe/ERPNext v16 bench. The app declares compatibility in
`pyproject.toml` and requires ERPNext through `hooks.py`.

## Current Version

v0.4.3-public
