# Copyright (c) 2026, Merch TNA Tracker and contributors
# For license information, please see license.txt

import re
from decimal import Decimal, InvalidOperation

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate, today

# Not real PO references, so the same value may repeat for one buyer.
PLACEHOLDER_PO_NUMBERS = {"TBA", "TBC", "AWTG", "SMS", "NA", "N/A"}

# More than one PO in one value, e.g. "4500263615 / 616" or "A, B". A slash inside a number (PO/2026/1) is fine.
MULTI_PO_PATTERN = re.compile(r"[,;&]|\s/\s")
SCIENTIFIC_PATTERN = re.compile(r"^\d+(\.\d+)?E\+?\d+$")


def normalize_po_number(value):
	"""Undo what Excel does to PO numbers: 26116983.0 and 2.6116983E7 both become 26116983."""
	po = " ".join(str(value or "").split()).upper()
	if not po:
		return ""

	if SCIENTIFIC_PATTERN.match(po):
		try:
			po = format(Decimal(po), "f")
		except InvalidOperation:
			pass

	if re.fullmatch(r"\d+\.0+", po):
		po = po.split(".")[0]

	return po


class BuyerPO(Document):
	def validate(self):
		self.validate_po_number()
		self.validate_po_date()
		self.set_currency()
		self.validate_buyer_change()

	def on_update(self):
		self.sync_season_to_lines()

	def validate_po_number(self):
		self.po_number = normalize_po_number(self.po_number) or None
		if not self.po_number:
			return

		if MULTI_PO_PATTERN.search(self.po_number):
			frappe.throw(
				_("{0} looks like more than one PO number. Create one Buyer PO per PO number.").format(
					frappe.bold(self.po_number)
				)
			)

		if self.po_number in PLACEHOLDER_PO_NUMBERS:
			return

		duplicate = frappe.db.exists(
			"Buyer PO",
			{"buyer": self.buyer, "po_number": self.po_number, "name": ["!=", self.name]},
		)
		if duplicate:
			frappe.throw(
				_("PO Number {0} already exists for {1}: {2}").format(
					frappe.bold(self.po_number),
					frappe.bold(self.buyer),
					frappe.get_desk_link("Buyer PO", duplicate),
				)
			)

	def validate_po_date(self):
		if self.po_date and getdate(self.po_date) > getdate(today()):
			frappe.throw(_("PO Date cannot be in the future."))

	def set_currency(self):
		currency = frappe.db.get_value("Merch Buyer", self.buyer, "order_currency")
		if not currency:
			frappe.throw(
				_("Please set Order Currency on buyer {0} first.").format(
					frappe.get_desk_link("Merch Buyer", self.buyer)
				)
			)
		self.currency = currency

	def validate_buyer_change(self):
		"""Order Lines take their buyer and currency from the PO, so it cannot move to another buyer."""
		if self.is_new() or not self.has_value_changed("buyer"):
			return

		if frappe.db.table_exists("Order Line") and frappe.db.exists("Order Line", {"buyer_po": self.name}):
			frappe.throw(_("Buyer cannot be changed because this PO already has Order Lines."))

	def sync_season_to_lines(self):
		"""Order Lines show the PO's season, so keep them in step when it changes."""
		if self.flags.in_insert or not self.has_value_changed("season"):
			return

		if frappe.db.table_exists("Order Line"):
			frappe.db.set_value(
				"Order Line", {"buyer_po": self.name}, "season", self.season, update_modified=False
			)


def update_po_totals(po_name):
	"""Called from Order Line whenever a line is saved, changed or deleted."""
	if not po_name or not frappe.db.table_exists("Order Line"):
		return

	qty, amount = frappe.db.sql(
		"""
		select coalesce(sum(coalesce(net_qty, qty)), 0), coalesce(sum(amount), 0)
		from `tabOrder Line`
		where buyer_po = %s and ifnull(status, '') != 'Cancelled'
		""",
		po_name,
	)[0]

	frappe.db.set_value(
		"Buyer PO", po_name, {"total_qty": qty, "total_amount": amount}, update_modified=False
	)
