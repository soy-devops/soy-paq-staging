"""Thin wrapper around the Shippo SDK for buying a shipping label.

Addresses and parcel dimensions are not tracked everywhere in this app yet, so
this intentionally uses public example placeholders until a site provides real
shipment data:
  - DEFAULT_ADDRESS_FROM / DEFAULT_ADDRESS_TO: non-secret example address data.
  - DEFAULT_PARCEL: one standard box preset used for every shipment.
Swap these for site-specific Address/Item data before buying production labels.

TODO(manual-entry): let the warehouse worker type the real ship-to name/address,
weight/dimensions, and carrier preference on the Ship screen before generating a
label. generate_shipment_label() in api.py should accept those as optional params
and pass them through to buy_cheapest_label() instead of relying on these defaults.
"""

import os

import frappe

DEFAULT_ADDRESS_FROM = {
	"name": "Example Sender",
	"company": "Example Company",
	"street1": "123 Example St",
	"city": "San Francisco",
	"state": "CA",
	"zip": "94103",
	"country": "US",
	"phone": "+1 555 0100",
	"email": "shipping@example.com",
}

DEFAULT_ADDRESS_TO = {
	"name": "Mr Hippo",
	"company": "Shippo",
	"street1": "965 Mission St #572",
	"city": "San Francisco",
	"state": "CA",
	"zip": "94103",
	"country": "US",
}

DEFAULT_PARCEL = {
	"length": "12",
	"width": "9",
	"height": "6",
	"distance_unit": "in",
	"weight": "2",
	"mass_unit": "lb",
}


def _api_key() -> str:
	key = os.environ.get("SHIPPO_API_KEY")
	if not key:
		frappe.throw(
			"SHIPPO_API_KEY is not set. Configure it as a site or hosting-provider secret "
			"before generating shipping labels."
		)
	return key


def buy_cheapest_label(
	address_from: dict | None = None,
	address_to: dict | None = None,
	parcel: dict | None = None,
) -> dict:
	"""Request rates for a shipment and buy the cheapest one.

	Returns {tracking_number, carrier, label_url, transaction_id}.
	"""
	from shippo import Shippo
	from shippo.models import components

	sdk = Shippo(api_key_header=_api_key())

	shipment = sdk.shipments.create(
		components.ShipmentCreateRequest(
			address_from=components.AddressCreateRequest(**(address_from or DEFAULT_ADDRESS_FROM)),
			address_to=components.AddressCreateRequest(**(address_to or DEFAULT_ADDRESS_TO)),
			parcels=[components.ParcelCreateRequest(**(parcel or DEFAULT_PARCEL))],
			async_=False,
		)
	)

	rates = shipment.rates or []
	if not rates:
		frappe.throw("Shippo returned no rates for this shipment.")
	cheapest = min(rates, key=lambda rate: float(rate.amount))

	transaction = sdk.transactions.create(
		components.TransactionCreateRequest(
			rate=cheapest.object_id,
			label_file_type="PDF",
			async_=False,
		)
	)

	if transaction.status != "SUCCESS":
		messages = ", ".join(m.text for m in (transaction.messages or []) if getattr(m, "text", None))
		frappe.throw(f"Shippo could not generate a label: {messages or transaction.status}")

	return {
		"tracking_number": transaction.tracking_number,
		"carrier": cheapest.provider,
		"label_url": transaction.label_url,
		"transaction_id": transaction.object_id,
	}
