# Copyright (c) 2026, Merch TNA Tracker and contributors
# For license information, please see license.txt

import sys

import frappe
from frappe import _
from frappe.model.base_document import get_controller
from frappe.model.document import Document
from frappe.utils import cstr, flt, get_first_day, getdate, now_datetime, today

# Shipping a little over or under the order qty is normal in garments. Change the number if the buyers allow more.
SHIP_TOLERANCE_PERCENT = 5

# While the status is one of these, shipments decide whether it is Partly Shipped or Shipped.
STATUSES_THAT_FOLLOW_SHIPMENTS = (
	"PO Received",
	"Fabric Booked",
	"Fabric In-House",
	"Approvals",
	"In Production",
	"Ready",
	"Partly Shipped",
	"Shipped",
)
STATUSES_NEEDING_SHIPMENTS = ("Partly Shipped", "Shipped", "Delivered")

# Child tables that only grow: (table fieldname, fields that cannot change, label for messages)
HISTORY_TABLES = (
	(
		"revisions",
		("from_date", "revised_date", "reason", "remarks", "changed_by", "changed_on", "revision_no"),
		"Date Revision",
	),
	("status_log", ("log_date", "status", "comment"), "Status Log"),
)


def call_helper(doctype, function_name, *args):
	"""Call a helper that lives next to another DocType's controller, without needing the app name."""
	module = sys.modules[get_controller(doctype).__module__]
	return getattr(module, function_name)(*args)


class OrderLine(Document):
	def validate(self):
		self.clean_text()
		self.set_po_details()
		self.validate_forecast()
		self.set_cancellation()
		self.set_amounts()
		self.check_buyer_po_change()
		self.check_history_not_changed()
		self.set_dates()
		self.set_shipping()
		self.set_status()
		self.log_status_change()
		self.warn_if_duplicate()

	def on_update(self):
		call_helper("Buyer PO", "update_po_totals", self.buyer_po)
		call_helper("Order Forecast", "update_forecast_progress", self.forecast)

		before = self.get_doc_before_save()
		if before and before.buyer_po != self.buyer_po:
			call_helper("Buyer PO", "update_po_totals", before.buyer_po)
		if before and before.forecast != self.forecast:
			call_helper("Order Forecast", "update_forecast_progress", before.forecast)

	def on_trash(self):
		if self.shipments:
			frappe.throw(
				_("This Order Line has shipments, so it cannot be deleted. Set its status to Closed instead.")
			)

	def after_delete(self):
		call_helper("Buyer PO", "update_po_totals", self.buyer_po)
		call_helper("Order Forecast", "update_forecast_progress", self.forecast)

	# ---- Order ----------------------------------------------------------------

	def clean_text(self):
		for fieldname in ("style_no", "description", "wash_color", "fabric_ref", "fabric_mill"):
			self.set(fieldname, " ".join(cstr(self.get(fieldname)).split()) or None)

	def set_po_details(self):
		po = frappe.db.get_value(
			"Buyer PO", self.buyer_po, ["buyer", "season", "currency", "po_date"], as_dict=True
		)
		if not po:
			frappe.throw(_("Buyer PO {0} was not found.").format(frappe.bold(self.buyer_po)))
		if not po.currency:
			frappe.throw(_("Buyer PO {0} has no currency. Open it and save it again.").format(frappe.bold(self.buyer_po)))

		self.buyer = po.buyer
		self.season = po.season
		self.currency = po.currency
		self.flags.po_date = po.po_date

	def check_buyer_po_change(self):
		"""A line can move to another PO, but only if the currency stays the same (its prices are in that currency)."""
		before = self.get_doc_before_save()
		if before and before.buyer_po != self.buyer_po and before.currency != self.currency:
			frappe.throw(
				_("This line cannot move to {0}: its currency is {1} but the line is priced in {2}.").format(
					frappe.bold(self.buyer_po), frappe.bold(self.currency), frappe.bold(before.currency)
				)
			)

	def validate_forecast(self):
		"""An order can say which forecast it comes from. Its qty is then taken off that forecast."""
		if not self.forecast:
			if self.is_new() and call_helper("Order Book Settings", "is_forecast_required"):
				frappe.throw(_("Every new order starts as a forecast. Pick the forecast this order comes from."))
			return

		forecast = frappe.db.get_value("Order Forecast", self.forecast, ["buyer", "status"], as_dict=True)
		if not forecast:
			frappe.throw(_("Forecast {0} was not found.").format(frappe.bold(self.forecast)))

		group_of = lambda buyer: call_helper("Order Forecast", "get_buyer_group", buyer)
		if group_of(forecast.buyer) != group_of(self.buyer):
			frappe.throw(
				_("{0} is a forecast for {1}, not for {2}.").format(
					frappe.get_desk_link("Order Forecast", self.forecast),
					frappe.bold(forecast.buyer),
					frappe.bold(self.buyer),
				)
			)

		before = self.get_doc_before_save()
		newly_linked = not before or before.forecast != self.forecast
		if newly_linked and forecast.status == "Confirmed":
			frappe.msgprint(
				_("{0} is already fully confirmed. This order is on top of it.").format(
					frappe.get_desk_link("Order Forecast", self.forecast)
				),
				indicator="orange",
				alert=True,
			)

	# ---- Quantity and value ---------------------------------------------------

	def set_cancellation(self):
		"""Part of an order can be cancelled. Amount, Ship % and the forecast then work on what is left (Net Qty)."""
		qty = flt(self.qty)
		if qty <= 0:
			frappe.throw(_("Qty must be greater than zero."))

		cancelled = flt(self.cancelled_qty)
		if cancelled > qty:
			frappe.throw(_("Cancelled Qty cannot be more than Qty."))

		before = self.get_doc_before_save()
		reopened = bool(before) and before.status == "Cancelled" and self.status != "Cancelled"

		if self.status == "Cancelled":
			cancelled = qty  # the whole line is cancelled
		elif reopened and cancelled >= qty:
			cancelled = 0.0  # reopened, so nothing is cancelled any more
		elif cancelled >= qty:
			self.status = "Cancelled"  # everything was cancelled by qty

		# Once shipping started the whole line cannot be cancelled. A partial cancel is limited by the
		# shipping tolerance on the net qty (checked in set_shipping).
		shipped = sum(flt(row.shipped_qty) for row in self.shipments)
		if cancelled >= qty and shipped > 0:
			frappe.throw(
				_("{0} pcs are already shipped, so the whole line cannot be cancelled.").format(int(shipped))
			)
		self.net_qty = qty

	def set_amounts(self):
		self.amount = flt(flt(self.net_qty) * flt(self.unit_price), 2)

		if self.currency == "USD":
			self.exchange_rate = 1.0
		else:
			self.exchange_rate = flt(call_helper("Order Book Settings", "get_eur_to_usd_rate"), 4)
		self.amount_usd = flt(self.amount * self.exchange_rate, 2)

		if flt(self.unit_price) <= 0:
			frappe.msgprint(_("No unit price entered, so Amount is 0."), indicator="orange", alert=True)

	# ---- Dates ----------------------------------------------------------------

	def set_dates(self):
		if not self.buyer_ex_factory_date:
			frappe.throw(_("Buyer Ex-Factory Date is required."))

		buyer_date = getdate(self.buyer_ex_factory_date)
		po_date = self.flags.po_date

		if po_date and buyer_date < getdate(po_date):
			frappe.throw(_("Buyer Ex-Factory Date cannot be before the PO Date ({0}).").format(po_date))

		# The original date can be corrected only until the first revision is added.
		before = self.get_doc_before_save()
		existing_revision_names = {row.name for row in (before.revisions or [])} if before else set()
		if (
			before
			and before.revisions
			and before.buyer_ex_factory_date
			and getdate(before.buyer_ex_factory_date) != buyer_date
		):
			frappe.throw(
				_("Buyer Ex-Factory Date cannot be changed after a date revision exists. Add a new revision instead.")
			)

		current = buyer_date
		for row in self.revisions:
			if not row.revised_date:
				frappe.throw(_("Date Revision row {0}: Revised Date is required.").format(row.idx))

			revised = getdate(row.revised_date)
			if revised == current:
				frappe.throw(
					_("Date Revision row {0}: {1} is the same as the previous date.").format(row.idx, revised)
				)

			if row.name not in existing_revision_names:
				row.from_date = current
				row.changed_by = frappe.session.user
				row.changed_on = now_datetime()

			row.revision_no = row.idx
			current = revised

		self.current_ex_factory_date = current
		self.ship_month = get_first_day(current)

		if self.actual_ex_factory_date:
			actual = getdate(self.actual_ex_factory_date)
			if actual > getdate(today()):
				frappe.throw(_("Actual Ex-Factory Date cannot be in the future."))
			if po_date and actual < getdate(po_date):
				frappe.throw(_("Actual Ex-Factory Date cannot be before the PO Date ({0}).").format(po_date))

	# ---- History that only grows ---------------------------------------------

	def check_history_not_changed(self):
		"""Date revisions and status log rows are an audit trail: rows can be added, never edited or deleted."""
		before = self.get_doc_before_save()
		if not before:
			return

		for table, locked_fields, label in HISTORY_TABLES:
			old_rows = before.get(table) or []
			new_rows = self.get(table) or []
			current_by_name = {row.name: row for row in new_rows}

			for old in old_rows:
				current = current_by_name.get(old.name)
				if not current:
					frappe.throw(_("{0} rows cannot be deleted. Add a new row instead.").format(label))

				for fieldname in locked_fields:
					if cstr(old.get(fieldname)).strip() != cstr(current.get(fieldname)).strip():
						frappe.throw(_("{0} rows cannot be changed. Add a new row instead.").format(label))

			old_names = {old.name for old in old_rows}
			new_row_seen = False
			for row in new_rows:
				if row.name in old_names:
					if new_row_seen:
						frappe.throw(_("{0}: new rows must be added at the end.").format(label))
				else:
					new_row_seen = True

	# ---- Shipments ------------------------------------------------------------

	def set_shipping(self):
		po_date = self.flags.po_date
		total = 0.0
		last_ship_date = None

		for row in self.shipments:
			if not row.ship_date:
				frappe.throw(_("Shipment row {0}: Ship Date is required.").format(row.idx))

			ship_date = getdate(row.ship_date)
			if ship_date > getdate(today()):
				frappe.throw(_("Shipment row {0}: Ship Date cannot be in the future.").format(row.idx))
			if po_date and ship_date < getdate(po_date):
				frappe.throw(_("Shipment row {0}: Ship Date cannot be before the PO Date ({1}).").format(row.idx, po_date))
			if flt(row.shipped_qty) <= 0:
				frappe.throw(_("Shipment row {0}: Shipped Qty must be greater than zero.").format(row.idx))

			total += flt(row.shipped_qty)
			last_ship_date = max(last_ship_date, ship_date) if last_ship_date else ship_date

		qty = flt(self.net_qty)
		limit = qty * (1 + SHIP_TOLERANCE_PERCENT / 100)
		if total > limit:
			frappe.throw(
				_("Total shipped ({0}) is more than the net qty ({1}) plus the {2}% tolerance.").format(
					frappe.bold(int(total)), frappe.bold(int(qty)), SHIP_TOLERANCE_PERCENT
				)
			)

		self.shipped_qty = total
		self.ship_pct = flt(total / qty * 100, 2) if qty else 0.0

		self.flags.fully_shipped = total > 0 and total >= qty * (1 - SHIP_TOLERANCE_PERCENT / 100)
		if self.flags.fully_shipped and not self.actual_ex_factory_date:
			self.actual_ex_factory_date = last_ship_date

	# ---- Status ---------------------------------------------------------------

	def set_status(self):
		if self.shipments and self.status in STATUSES_THAT_FOLLOW_SHIPMENTS:
			self.status = "Shipped" if self.flags.fully_shipped else "Partly Shipped"

		if self.status in STATUSES_NEEDING_SHIPMENTS and not self.shipments:
			frappe.throw(
				_("Status {0} needs at least one shipment. Add the shipment or change the status.").format(
					frappe.bold(self.status)
				)
			)

	def log_status_change(self):
		for row in self.status_log:
			if not row.user:
				row.user = frappe.session.user
			if not row.log_date:
				row.log_date = today()

		before = self.get_doc_before_save()
		if not before or before.status == self.status:
			return

		# If the user already wrote a log row for this status in the same save, do not add another one.
		old_names = {row.name for row in (before.status_log or [])}
		if any(row.name not in old_names and row.status == self.status for row in self.status_log):
			return

		self.append(
			"status_log",
			{
				"log_date": today(),
				"status": self.status,
				"comment": "Status changed from {0} to {1}".format(before.status, self.status),
				"user": frappe.session.user,
			},
		)

	# ---- Duplicates -----------------------------------------------------------

	def warn_if_duplicate(self):
		duplicate = frappe.db.sql(
			"""
			select name from `tabOrder Line`
			where buyer_po = %s and style_no = %s
				and ifnull(wash_color, '') = %s
				and name != %s
			limit 1
			""",
			(self.buyer_po, self.style_no, self.wash_color or "", self.name),
		)
		if duplicate:
			frappe.msgprint(
				_("Another Order Line has the same PO, Style and Wash: {0}").format(
					frappe.get_desk_link("Order Line", duplicate[0][0])
				),
				indicator="orange",
				alert=True,
			)
