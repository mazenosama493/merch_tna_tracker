# Copyright (c) 2026, Merch TNA Tracker and contributors
# For license information, please see license.txt

import sys

import frappe
from frappe import _
from frappe.model.base_document import get_controller
from frappe.model.document import Document
from frappe.utils import cstr, flt, get_first_day, getdate, now_datetime, today

# A forecast in one of these statuses still has  volume left.
ACTIVE_STATUSES = ("Projected", "Partly Confirmed")


def call_helper(doctype, function_name, *args):
	"""Call a helper that lives next to another DocType's controller, without needing the app name."""
	module = sys.modules[get_controller(doctype).__module__]
	return getattr(module, function_name)(*args)


def get_buyer_group(buyer):
	"""A brand under a bigger buyer counts as part of that buyer (Merch Buyer.buyer_group)."""
	return frappe.db.get_value("Merch Buyer", buyer, "buyer_group") or buyer


def get_confirmed_qty(forecast):
	"""Qty of the Order Lines that come from this forecast. A cancelled line gives its qty back."""
	if not forecast or not frappe.db.table_exists("Order Line"):
		return 0.0

	confirmed = frappe.db.sql(
		"""
		select coalesce(sum(qty), 0)
		from `tabOrder Line`
		where forecast = %s and ifnull(status, '') != 'Cancelled'
		""",
		forecast,
	)[0][0]  # the first column of the first row
	return flt(confirmed)


def calculate_progress(qty, value, value_usd, confirmed_qty):
	"""Projected qty = confirmed + remaining. Used on save and when an Order Line changes."""
	qty = flt(qty)
	confirmed = flt(confirmed_qty)
	remaining = max(qty - confirmed, 0.0)
	over_forecast = max(confirmed - qty, 0.0)
	over_forecast_percent = (over_forecast / qty * 100) if qty else 0.0

	if remaining > 0:
		status = "Partly Confirmed" if confirmed > 0 else "Projected"
	else:
		status = "Confirmed"

	ratio = remaining / qty if qty else 0.0
	return {
		"status": status,
		"confirmed_qty": confirmed,
		"remaining_qty": remaining,
		"over_forecast_qty": over_forecast,
		"over_forecast_percent": flt(over_forecast_percent, 2),
		"remaining_value": flt(flt(value) * ratio, 2),
		"remaining_value_usd": flt(flt(value_usd) * ratio, 2),
	}


def update_forecast_progress(forecast):
	"""Called from Order Line whenever a line linked to a forecast is saved, changed or deleted."""
	if not forecast:
		return

	row = frappe.db.get_value("Order Forecast", forecast, ["qty", "value", "value_usd"], as_dict=True)
	if not row:
		return

	confirmed = get_confirmed_qty(forecast)
	progress = calculate_progress(row.qty, row.value, row.value_usd, confirmed)
	frappe.db.set_value("Order Forecast", forecast, progress, update_modified=False)


class OrderForecast(Document):
	def validate(self):
		self.set_currency()
		self.set_month()
		self.log_month_change()
		self.check_month_log_not_changed()
		self.set_amounts()
		self.set_progress()
		self.validate_duplicate()
		self.warn_if_past_month()

	def check_month_log_not_changed(self):
		"""Keep the audit trail immutable except for comments and validate system-created entries."""
		before = self.get_doc_before_save()
		current_rows = list(self.month_change_log or [])

		# A new Forecast must not arrive with user-supplied history rows.
		if not before:
			if current_rows:
				frappe.throw(_("Month change history is generated automatically and cannot be added manually."))
			return

		old_rows = list(before.month_change_log or [])
		old_by_name = {row.name: row for row in old_rows}
		current_by_name = {row.name: row for row in current_rows if row.name}

		# Existing history cannot be removed or have its audit fields changed.
		for old in old_rows:
			current = current_by_name.get(old.name)
			if not current:
				frappe.throw(_("Month change history rows cannot be deleted."))
			for fieldname in ("from_month", "to_month", "edited_by", "edited_on"):
				if cstr(old.get(fieldname)).strip() != cstr(current.get(fieldname)).strip():
					frappe.throw(_("Month change history rows cannot be changed. Only the comment can be edited."))

		new_rows = [row for row in current_rows if not row.name or row.name not in old_by_name]
		month_changed = getdate(before.forecast_month) != getdate(self.forecast_month)

		if not month_changed:
			if new_rows:
				frappe.throw(_("Month change history is generated automatically and cannot be added manually."))
			return

		# Exactly one row must be created for each saved month transition.
		if len(new_rows) != 1:
			frappe.throw(_("Changing Forecast Month must create exactly one Month Change Log entry."))

		log_row = new_rows[0]
		if (
			getdate(log_row.from_month) != getdate(before.forecast_month)
			or getdate(log_row.to_month) != getdate(self.forecast_month)
			or log_row.edited_by != frappe.session.user
			or not log_row.edited_on
		):
			frappe.throw(_("Month Change Log details are generated automatically and cannot be entered manually."))

	def log_month_change(self):
		"""Append one audit row whenever the Forecast Month changes."""
		before = self.get_doc_before_save()
		if not before or getdate(before.forecast_month) == getdate(self.forecast_month):
			return

		old_names = {row.name for row in (before.month_change_log or [])}
		# Avoid duplicate rows if validate is triggered more than once before saving.
		if any(not row.name or row.name not in old_names for row in (self.month_change_log or [])):
			return

		self.append(
			"month_change_log",
			{
				"from_month": before.forecast_month,
				"to_month": self.forecast_month,
				"edited_by": frappe.session.user,
				"edited_on": now_datetime(),
			},
		)

	def set_currency(self):
		currency = frappe.db.get_value("Merch Buyer", self.buyer, "order_currency")
		if not currency:
			frappe.throw(
				_("Please set Order Currency on buyer {0} first.").format(
					frappe.get_desk_link("Merch Buyer", self.buyer)
				)
			)
		self.currency = currency

	def set_month(self):
		if not self.forecast_month:
			frappe.throw(_("Forecast Month is required."))

		# Any day of the month can be picked; it is always saved as the 1st.
		self.forecast_month = get_first_day(self.forecast_month)

	def set_amounts(self):
		if flt(self.qty) <= 0:
			frappe.throw(_("Qty must be greater than zero."))

		self.value = flt(self.value, 2)

		if self.currency == "USD":
			rate = 1.0
		else:
			rate = flt(call_helper("Order Book Settings", "get_eur_to_usd_rate"), 4)
		self.value_usd = flt(self.value * rate, 2)

		if self.value <= 0:
			frappe.msgprint(_("No value entered, so Value USD is 0."), indicator="orange", alert=True)

	def set_progress(self):
		confirmed = get_confirmed_qty(self.name)
		self.update(calculate_progress(self.qty, self.value, self.value_usd, confirmed))

	def validate_duplicate(self):
		"""One active forecast per buyer and month, otherwise the Summary would count it twice."""
		if self.status not in ACTIVE_STATUSES:
			return

		duplicate = frappe.db.exists(
			"Order Forecast",
			{
				"buyer": self.buyer,
				"forecast_month": self.forecast_month,
				"status": ["in", ACTIVE_STATUSES],
				"name": ["!=", self.name],
			},
		)
		if duplicate:
			frappe.throw(
				_("{0} already has an active forecast for this month: {1}. Edit it instead of adding another one.").format(
					frappe.bold(self.buyer), frappe.get_desk_link("Order Forecast", duplicate)
				)
			)

	def warn_if_past_month(self):
		if self.status in ACTIVE_STATUSES and getdate(self.forecast_month) < get_first_day(getdate(today())):
			frappe.msgprint(
				_("This forecast is for a past month. Review it if the plan has changed."),
				indicator="orange",
				alert=True,
			)
