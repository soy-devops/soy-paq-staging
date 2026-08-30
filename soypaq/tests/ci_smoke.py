"""Post-install smoke assertions, run by CI against a freshly created site.

Existence of this file is a direct response to a real bug: the app installed
"successfully" on a clean site while silently missing every field the patches were
supposed to add, because Frappe marks patches as already-executed on a fresh install
and never runs them. `bench migrate` on an existing site did not catch it. Only
installing onto a brand new site did.

Run with:  bench --site <site> execute soypaq.tests.ci_smoke.run
"""

from __future__ import annotations

import frappe

DOCTYPES = [
	"Inbound ASN",
	"Inbound ASN Item",
	"Inbound ASN Package",
	"Inbound Package",
	"Inbound Package Item",
	"Pick Task",
	"Pick Task Item",
	"Pack Task",
	"Pack Task Item",
	"Shipment Task",
	"Shipment Task Item",
	"Receiving Desk",
]

# Fields that used to be created by patches. On a fresh install patches never run,
# so these must come from the DocType JSON itself.
REQUIRED_FIELDS = {
	"Inbound ASN": ["company", "supplier", "purchase_order"],
	"Inbound Package Item": ["received_qty", "assigned_bin"],
	"Pack Task": ["assigned_user", "box_confirmed"],
	"Pack Task Item": ["packed_qty"],
	"Pick Task Item": ["exception_reason"],
	"Shipment Task": ["assigned_user", "shipping_label_url", "shippo_transaction_id"],
}

NAMING_SERIES_DOCTYPES = [
	"Pick Task",
	"Pack Task",
	"Shipment Task",
	"Inbound ASN",
	"Inbound Package",
]


def run() -> None:
	failures: list[str] = []

	# 1. every doctype exists, and is app-owned rather than database-only
	for doctype in DOCTYPES:
		if not frappe.db.exists("DocType", doctype):
			failures.append(f"DocType missing: {doctype}")
			continue
		if frappe.db.get_value("DocType", doctype, "custom"):
			failures.append(f"{doctype}: custom=1 (should be app-owned)")

	# 2. controllers import
	from frappe.model.base_document import get_controller

	for doctype in DOCTYPES:
		if not frappe.db.exists("DocType", doctype):
			continue
		try:
			get_controller(doctype)
		except Exception as exc:
			failures.append(f"{doctype}: controller import failed - {exc}")

	# 3. the ex-patch fields are present as real fields, with real DB columns
	for doctype, fieldnames in REQUIRED_FIELDS.items():
		if not frappe.db.exists("DocType", doctype):
			continue
		meta = frappe.get_meta(doctype)
		columns = {
			row.get("Field") or row.get("column_name")
			for row in frappe.db.sql(f"DESC `tab{doctype}`", as_dict=True)
		}
		for fieldname in fieldnames:
			if not meta.has_field(fieldname):
				failures.append(f"{doctype}.{fieldname}: missing from DocType")
			if fieldname not in columns:
				failures.append(f"tab{doctype}.{fieldname}: missing DB column")

	# 4. no leftover Custom Fields - the DocType JSON owns these now
	stray = frappe.db.count("Custom Field", {"dt": ["in", DOCTYPES]})
	if stray:
		failures.append(f"{stray} Custom Field row(s) still defined on app doctypes")

	# 5. naming series wired up
	for doctype in NAMING_SERIES_DOCTYPES:
		if not frappe.db.exists("DocType", doctype):
			continue
		if frappe.db.get_value("DocType", doctype, "autoname") != "naming_series:":
			failures.append(f"{doctype}: autoname is not 'naming_series:'")
		if not frappe.get_meta(doctype).has_field("naming_series"):
			failures.append(f"{doctype}: no naming_series field")

	# 6. after_install ran (patches would not have)
	if not frappe.db.exists("Desktop Icon", {"label": "SoyPaq WMS"}):
		failures.append("Desktop Icon 'SoyPaq WMS' missing - after_install hook did not run")

	# 7. the API module imports and exposes its whitelisted entry points
	try:
		import soypaq.api as api

		for fn in ("get_mobile_bootstrap", "create_pick_task", "pick_item", "mark_shipment_shipped"):
			if not hasattr(api, fn):
				failures.append(f"soypaq.api.{fn} missing")
	except Exception as exc:
		failures.append(f"soypaq.api import failed - {exc}")

	if failures:
		print("SMOKE FAILURES:")
		for failure in failures:
			print(f"  - {failure}")
		raise SystemExit(1)

	print(f"smoke OK: {len(DOCTYPES)} doctypes, controllers, fields, columns, naming, hooks")
