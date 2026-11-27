# Copyright (c) 2026, Merch TNA Tracker and contributors
# For license information, please see license.txt

import re
from decimal import Decimal, InvalidOperation

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate, today

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
		# Recalculate the PO total when its Price Term changes between FOB and DDP.
		update_po_totals(self.name)

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


def _calculate_po_totals(po_name, price_term=None, update_lines=False):
	"""Calculate PO totals from its Order Lines, optionally persisting line totals."""
	if not po_name or not frappe.db.table_exists("Order Line"):
		return {"total_qty": 0.0, "total_amount": 0.0}

	price_term = price_term or frappe.db.get_value("Buyer PO", po_name, "price_term") or "FOB"
	if price_term not in ("FOB", "DDP"):
		frappe.throw(_("Price Term must be FOB or DDP."))

	rows = frappe.get_all(
		"Order Line",
		filters={"buyer_po": po_name},
		fields=["name", "qty", "unit_price", "unit_price_ddp", "discount_amount", "exchange_rate", "status"],
	)

	total_qty = 0.0
	total_amount = 0.0
	for row in rows:
		qty = flt(row.qty)
		fob_amount = flt(qty * flt(row.unit_price), 2)
		ddp_amount = flt(qty * flt(row.unit_price_ddp), 2) if price_term == "DDP" else 0.0
		gross_amount = flt(fob_amount + ddp_amount, 2)
		discount_percent = flt(row.discount_amount)
		if discount_percent < 0 or discount_percent > 100:
			frappe.throw(_("Discount on Order Line {0} must be between 0% and 100%.").format(frappe.bold(row.name)))
		discount_value = flt(gross_amount * discount_percent / 100, 2)
		amount = flt(gross_amount - discount_value, 2)

		if update_lines:
			exchange_rate = flt(row.exchange_rate)
			values = {
				"fob_price": fob_amount,
				"ddp_price": ddp_amount,
				"amount": amount,
			}
			if exchange_rate > 0:
				values["amount_usd"] = flt(amount * exchange_rate, 2)
			if price_term != "DDP":
				# Float columns are NOT NULL; clear the DDP unit price with numeric zero.
				values["unit_price_ddp"] = 0.0
			frappe.db.set_value("Order Line", row.name, values, update_modified=False)

		if (row.status or "") != "Cancelled":
			total_qty += qty
			total_amount += amount

	return {"total_qty": flt(total_qty, 2), "total_amount": flt(total_amount, 2)}


def update_po_totals(po_name):
	"""Recalculate and persist Order Line values and the aggregate Buyer PO totals."""
	if not po_name or not frappe.db.exists("Buyer PO", po_name):
		return

	price_term = frappe.db.get_value("Buyer PO", po_name, "price_term") or "FOB"
	totals = _calculate_po_totals(po_name, price_term=price_term, update_lines=True)
	frappe.db.set_value("Buyer PO", po_name, totals, update_modified=False)

	# Keep an already-open Buyer PO form in sync when an Order Line is saved/deleted
	# or when the PO Price Term is changed.
	frappe.publish_realtime(
		"buyer_po_totals_updated",
		{"buyer_po": po_name, **totals},
		doctype="Buyer PO",
		docname=po_name,
		after_commit=True,
	)


@frappe.whitelist()
def get_po_totals_preview(po_name, price_term=None):
	"""Return current totals for the Buyer PO form without changing the database."""
	if not po_name or not frappe.db.exists("Buyer PO", po_name):
		frappe.throw(_("Buyer PO was not found."))
	if not frappe.has_permission("Buyer PO", "read", po_name):
		frappe.throw(_("You do not have permission to view this Buyer PO."), frappe.PermissionError)

	return _calculate_po_totals(po_name, price_term=price_term, update_lines=False)
