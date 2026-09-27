"""Thin wrapper around the EasyShip REST API for buying a shipping label.

Mirrors shippo_client.py's shape (same DEFAULT_ADDRESS_FROM/TO/PARCEL placeholder
pattern, same {tracking_number, carrier, label_url, transaction_id} return contract) so
shipping_providers.EasyShipProvider is a drop-in alongside ShippoProvider - swapping
providers never touches api.py's Ship-step call site.

EasyShip has no official Python SDK; this calls their REST API directly with
`requests` (already a transitive dependency via frappe). Flow (2024-09 API version):
  1. POST /shipments        - create a shipment, get back rate options
  2. PATCH /shipments/{id}  - select a courier from those rates
  3. POST /labels           - generate the label for the now-rated shipment

Request/response field names verified 2026-09-13 against EasyShip's shipment-creation
reference (items nest under parcels, not top-level; rate cost field is total_charge).
"""

import os

import frappe
import requests

# EasyShip uses a completely different host for sandbox vs. live tokens (not a path
# suffix) - a "sand_"-prefixed key against the live host returns "Invalid token.",
# confirmed 2026-09-14. Pick the host from the key's own prefix so switching a site
# between sandbox/live is just swapping the configured key, nothing else.
_LIVE_BASE_URL = "https://public-api.easyship.com/2024-09"
_SANDBOX_BASE_URL = "https://public-api-sandbox.easyship.com/2024-09"

DEFAULT_ADDRESS_FROM = {
	"contact_name": "Example Sender",
	"company_name": "Example Company",
	"line_1": "123 Example St",
	"city": "San Francisco",
	"state": "CA",
	"postal_code": "94103",
	"country_alpha2": "US",
	"contact_phone": "+15550100",
	"contact_email": "shipping@example.com",
}

DEFAULT_ADDRESS_TO = {
	"contact_name": "Mr Hippo",
	"company_name": "",
	"line_1": "965 Mission St #572",
	"city": "San Francisco",
	"state": "CA",
	"postal_code": "94103",
	"country_alpha2": "US",
	"contact_phone": "+15550101",
	# EasyShip requires contact_email on destination_address, unlike Shippo.
	"contact_email": "customer@example.com",
}

# One parcel, one item, at the mock per-item weight seeded onto every Item
# (real weights aren't tracked yet). actual_weight is in kg and dimensions in cm
# per EasyShip's API - 0.5 lb is
# ~0.23 kg; dimensions are a placeholder box, same role as shippo_client.DEFAULT_PARCEL.
DEFAULT_PARCEL = {
	"parcels": [
		{
			"items": [
				{
					"description": "Merchandise",
					"category": "Fashion",
					"quantity": 1,
					"actual_weight": 0.23,
					"dimensions": {"length": 30, "width": 23, "height": 15},
					"declared_currency": "USD",
					"declared_customs_value": 20,
				}
			],
		}
	],
}


def _api_key() -> str:
	key = os.environ.get("EASYSHIP_API_KEY") or frappe.conf.get("easyship_api_key")
	if not key:
		frappe.throw(
			"EASYSHIP_API_KEY is not set. Configure it as a site or hosting-provider secret "
			"before generating shipping labels via EasyShip."
		)
	return key


def _base_url(key: str) -> str:
	return _SANDBOX_BASE_URL if key.startswith("sand_") else _LIVE_BASE_URL


def _headers() -> dict:
	return {
		"Authorization": f"Bearer {_api_key()}",
		"Content-Type": "application/json",
		"Accept": "application/json",
	}


def _request(method: str, path: str, **kwargs) -> dict:
	response = requests.request(
		method, f"{_base_url(_api_key())}{path}", headers=_headers(), timeout=20, **kwargs
	)
	if not response.ok:
		frappe.throw(f"EasyShip {method} {path} failed ({response.status_code}): {response.text[:500]}")
	return response.json()


def buy_cheapest_label(
	address_from: dict | None = None,
	address_to: dict | None = None,
	parcel: dict | None = None,
) -> dict:
	"""Create a shipment, pick the cheapest courier rate, and generate its label.

	Returns {tracking_number, carrier, label_url, transaction_id}.
	"""
	shipment_payload = {
		"origin_address": address_from or DEFAULT_ADDRESS_FROM,
		"destination_address": address_to or DEFAULT_ADDRESS_TO,
		**(parcel or DEFAULT_PARCEL),
	}
	created = _request("POST", "/shipments", json=shipment_payload)

	shipment = created.get("shipment") or created
	shipment_id = shipment.get("easyship_shipment_id")
	rates = shipment.get("rates") or []
	if not shipment_id or not rates:
		frappe.throw("EasyShip returned no rates for this shipment.")

	# Rates don't carry a flat courier_id - the id lives at courier_service.id
	# (confirmed 2026-09-13 against a live shipment response).
	cheapest = min(rates, key=lambda rate: float(rate.get("total_charge", 0)))
	courier_service_id = cheapest.get("courier_service", {}).get("id")

	_request(
		"PATCH",
		f"/shipments/{shipment_id}",
		json={"selected_courier_service_id": courier_service_id},
	)

	label = _request("POST", "/labels", json={"shipment_ids": [shipment_id]})
	label_result = (label.get("labels") or [label])[0]

	if label_result.get("status") not in ("generated", "success", None):
		frappe.throw(f"EasyShip could not generate a label: {label_result.get('status')}")

	return {
		"tracking_number": label_result.get("tracking_number") or shipment.get("tracking_number") or "",
		"carrier": cheapest.get("courier_service", {}).get("umbrella_name") or "Other",
		"label_url": label_result.get("label_url") or label_result.get("label_file_url") or "",
		"transaction_id": shipment_id,
	}
