# Copyright (c) 2026, Merch TNA Tracker and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

# EUR/USD has never been anywhere near these limits; outside them it is a typo (e.g. 11 instead of 1.1).
MIN_RATE = 0.5
MAX_RATE = 2.0


class OrderBookSettings(Document):
	def validate(self):
		rate = flt(self.eur_to_usd_rate)

		if rate <= 0:
			frappe.throw(_("EUR to USD Rate must be greater than zero."))

		if not (MIN_RATE <= rate <= MAX_RATE):
			frappe.throw(
				_("EUR to USD Rate {0} looks wrong. It should be between {1} and {2} (for example 1.1).").format(
					frappe.bold(rate), MIN_RATE, MAX_RATE
				)
			)


def get_eur_to_usd_rate():
	"""Used by Order Line and Order Forecast. Stops with a clear message if the rate was never saved."""
	rate = flt(frappe.db.get_single_value("Order Book Settings", "eur_to_usd_rate"))
	if rate <= 0:
		frappe.throw(_("Please open Order Book Settings and save the EUR to USD Rate first."))
	return rate


def is_forecast_required():
	"""Used by Order Line: must a new order name the forecast it comes from?"""
	return bool(frappe.db.get_single_value("Order Book Settings", "require_forecast"))
