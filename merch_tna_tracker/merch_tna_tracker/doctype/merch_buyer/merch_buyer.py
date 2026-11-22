# Copyright (c) 2026, Merch TNA Tracker and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


def clean_text(value):
	"""Trim and collapse repeated spaces so 'CJ  Basic ' and 'CJ Basic' are the same."""
	return " ".join((value or "").split())


class MerchBuyer(Document):
	def before_naming(self):
		# Runs before autoname (field:brand), so the record name itself is clean.
		self.brand = clean_text(self.brand)

	def validate(self):
		self.brand = clean_text(self.brand)
		self.validate_buyer_group()
		self.validate_currency_change()

	def validate_buyer_group(self):
		if not self.buyer_group:
			return

		if self.buyer_group == self.name:
			frappe.throw(_("Buyer Group cannot be the same record ({0}).").format(frappe.bold(self.name)))

		# One level only: the chosen group must not itself sit under another group.
		parent_of_group = frappe.db.get_value("Merch Buyer", self.buyer_group, "buyer_group")
		if parent_of_group:
			frappe.throw(
				_("{0} is already under {1}. Only one level of grouping is allowed.").format(
					frappe.bold(self.buyer_group), frappe.bold(parent_of_group)
				)
			)

		# A record that already has members cannot be moved under another group.
		if frappe.db.exists("Merch Buyer", {"buyer_group": self.name}):
			frappe.throw(
				_("{0} is a group for other buyers, so it cannot be placed under another group.").format(
					frappe.bold(self.name)
				)
			)

	def validate_currency_change(self):
		"""Block changing the currency once orders exist, otherwise old POs would silently change."""
		if self.is_new():
			return

		before = self.get_doc_before_save()
		# Allow the first time a currency is set on an older record that has none.
		if not before or not before.order_currency or before.order_currency == self.order_currency:
			return

		# These DocTypes are created in the next steps; skip until their tables exist.
		for doctype in ("Buyer PO", "Order Forecast"):
			if frappe.db.table_exists(doctype) and frappe.db.exists(doctype, {"buyer": self.name}):
				frappe.throw(
					_("Order Currency cannot be changed because {0} already has {1} records.").format(
						frappe.bold(self.name), frappe.bold(doctype)
					)
				)
