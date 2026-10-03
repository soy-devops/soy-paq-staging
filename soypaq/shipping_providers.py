"""Carrier-agnostic shipping provider interface.

generate_shipment_label() picks a provider by name instead of calling Shippo
directly, so a future EasyShip/UPS/etc. integration is a new class here, not a
rewrite of api.py. Provider is chosen by the `shipping_provider` site config key
(default "manual") - "manual" never calls an external carrier or spends real
money, which is what WMS-testing/prototype flows want; switch a site to
"shippo" or "easyship" once real label purchases are intended.
"""

import frappe


class ShippingProvider:
	"""Contract every carrier integration implements."""

	name = "base"

	def buy_label(self, ship_to: dict | None = None, parcel: dict | None = None) -> dict:
		"""Return {tracking_number, carrier, label_url, transaction_id}.

		ship_to is {name, company, line_1, line_2, city, state, postal_code, country, phone,
		email} and parcel is {weight_kg, length_cm, width_cm, height_cm, items}; each carrier
		client translates them into its own request shape. label_url may be empty for
		providers that don't produce a document (e.g. manual).
		"""
		raise NotImplementedError


class ShippoProvider(ShippingProvider):
	"""Real carrier purchase via Shippo - spends real money, requires SHIPPO_API_KEY."""

	name = "shippo"

	def buy_label(self, ship_to: dict | None = None, parcel: dict | None = None) -> dict:
		from soypaq import shippo_client

		return shippo_client.buy_cheapest_label(
			address_to=shippo_client.address_from_ship_to(ship_to),
			parcel=shippo_client.parcel_from_form(parcel),
		)


class EasyShipProvider(ShippingProvider):
	"""Real carrier purchase via EasyShip - spends real money, requires EASYSHIP_API_KEY."""

	name = "easyship"

	# Shipment Task.carrier is a fixed Select (UPS/FedEx/DHL/USPS/Other). EasyShip can
	# return any courier it partners with (e.g. "USPS Priority Mail", "DHL eCommerce"),
	# so match on a known prefix and fall back to "Other" rather than fail the Ship step.
	_KNOWN_CARRIERS = ("UPS", "FedEx", "DHL", "USPS")

	def buy_label(self, ship_to: dict | None = None, parcel: dict | None = None) -> dict:
		from soypaq import easyship_client

		label = easyship_client.buy_cheapest_label(
			address_to=easyship_client.address_from_ship_to(ship_to),
			parcel=easyship_client.parcel_from_form(parcel),
		)
		carrier_name = label.get("carrier") or ""
		label["carrier"] = next(
			(known for known in self._KNOWN_CARRIERS if known.lower() in carrier_name.lower()),
			"Other",
		)
		return label


class ManualProvider(ShippingProvider):
	"""No external call, no cost. Reserves a tracking placeholder for a human (or a future
	EasyShip/other-carrier integration) to fill in later, so the Ship step can still complete
	during WMS testing without buying a real label.
	"""

	name = "manual"

	def buy_label(self, ship_to: dict | None = None, parcel: dict | None = None) -> dict:
		# Shipment Task.carrier is a fixed Select (UPS/FedEx/DHL/USPS/Other) - "Other" is
		# the correct value for "no real carrier chosen yet", not a new option to add.
		placeholder = frappe.generate_hash(length=10).upper()
		return {
			"tracking_number": f"PENDING-{placeholder}",
			"carrier": "Other",
			"label_url": "",
			"transaction_id": "",
		}


_PROVIDERS = {p.name: p for p in (ShippoProvider, EasyShipProvider, ManualProvider)}


def get_provider() -> ShippingProvider:
	provider_name = frappe.conf.get("shipping_provider") or "manual"
	provider_cls = _PROVIDERS.get(provider_name)
	if not provider_cls:
		frappe.throw(
			f"Unknown shipping_provider '{provider_name}' in site config. Available: {', '.join(_PROVIDERS)}."
		)
	return provider_cls()
