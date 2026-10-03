"""Thin wrapper around the Shippo SDK for buying a shipping label.

The ship-to address and parcel come from the Ship screen (prefilled from the order
when the source sent one), translated here by address_from_ship_to / parcel_from_form.
The DEFAULT_* values below are public example placeholders, used only when a caller
passes nothing. DEFAULT_ADDRESS_FROM (the sender) is still a placeholder: set the
real warehouse address before buying production labels.
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


def address_from_ship_to(ship_to: dict | None) -> dict | None:
	"""Neutral ship-to dict -> Shippo AddressCreateRequest fields (None keeps the default)."""
	if not ship_to:
		return None
	address = {
		"name": ship_to.get("name"),
		"company": ship_to.get("company") or "",
		"street1": ship_to.get("line_1"),
		"street2": ship_to.get("line_2") or "",
		"city": ship_to.get("city"),
		"state": ship_to.get("state") or "",
		"zip": ship_to.get("postal_code"),
		"country": ship_to.get("country"),
		"phone": ship_to.get("phone") or "",
		"email": ship_to.get("email") or "",
	}
	return {key: value for key, value in address.items() if value}


def parcel_from_form(parcel: dict | None) -> dict | None:
	"""Neutral parcel dict (kg / cm) -> Shippo ParcelCreateRequest fields."""
	if not parcel:
		return None
	return {
		"length": str(parcel["length_cm"]),
		"width": str(parcel["width_cm"]),
		"height": str(parcel["height_cm"]),
		"distance_unit": "cm",
		"weight": str(parcel["weight_kg"]),
		"mass_unit": "kg",
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
