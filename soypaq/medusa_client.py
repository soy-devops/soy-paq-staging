"""Thin HTTP client for the local Medusa <-> ERPNext prototype loop.

ERPNext is the source of truth for stock (see soyshop-local/docs/MEDUSA_INTEGRATION.md,
Flow B) - this only ever *pushes* a mirror to Medusa, never reads stock back from it.
Auth is a shared secret header, not a password and not a Medusa admin JWT login - this
is a machine-to-machine local-dev credential, configured as a site config secret, the
same category as SHIPPO_API_KEY in shippo_client.py.
"""

import os

import frappe
import requests


def _base_url() -> str:
	return frappe.conf.get("medusa_base_url") or os.environ.get("MEDUSA_BASE_URL") or "http://medusa-app:9000"


def _shared_secret() -> str:
	secret = frappe.conf.get("medusa_erp_shared_secret") or os.environ.get("MEDUSA_ERP_SHARED_SECRET")
	if not secret:
		frappe.throw(
			"medusa_erp_shared_secret is not set. Add it to site_config.json (or the "
			"MEDUSA_ERP_SHARED_SECRET env var) - it must match ERPNEXT_SHARED_SECRET in "
			"soyshop-local's apps/backend/.env."
		)
	return secret


def push_stock_levels(levels: list[dict]) -> dict:
	"""levels: [{sku, quantity}]. Posts the full mirror in one call - fine at prototype
	volume; batch it if this ever needs to run per-SLE instead of on a schedule/manual
	trigger.
	"""
	if not levels:
		return {"updated": 0, "skipped": []}
	response = requests.post(
		f"{_base_url()}/erpnext/inventory-sync",
		json={"levels": levels},
		headers={"X-ERP-Secret": _shared_secret()},
		timeout=15,
	)
	if response.status_code != 200:
		frappe.throw(f"Medusa inventory sync failed ({response.status_code}): {response.text[:500]}")
	return response.json()
