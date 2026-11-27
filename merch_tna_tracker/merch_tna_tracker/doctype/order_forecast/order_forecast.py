# Copyright (c) 2026, Merch TNA Tracker and contributors
# For license information, please see license.txt

from importlib import import_module

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cstr, flt, get_first_day, getdate, now_datetime, today

# A forecast in one of these statuses still has volume left.
ACTIVE_STATUSES = ("Projected", "Partly Confirmed")


def call_helper(doctype, function_name, *args):
	"""Import the Order Book Settings helper directly from this app."""
	if doctype != "Order Book Settings":
		frappe.throw(_("Unsupported helper DocType: {0}").format(frappe.bold(doctype)))

	module_path = "merch_tna_tracker.merch_tna_tracker.doctype.order_book_settings.order_book_settings"
	try:
		module = import_module(module_path)
	except ImportError as exc:
		frappe.throw(
			_("Could not import helper module {0}: {1}").format(frappe.bold(module_path), frappe.bold(str(exc)))
		)

	helper = getattr(module, function_name, None)
	if not callable(helper):
		frappe.throw(
			_("Helper function {0} was not found in {1}.").format(
				frappe.bold(function_name), frappe.bold(module_path)
			)
		)
	return helper(*args)


def get_buyer_group(buyer):
	"""A brand under a bigger buyer counts as part of that buyer (Merch Buyer.buyer_group)."""
	return frappe.db.get_value("Merch Buyer", buyer, "buyer_group") or buyer


def get_confirmed_qty(forecast):
	"""Sum Original Quantity for active Order Lines linked to this Forecast.

	Older Order Lines created before Original Quantity was introduced may still have
	its default value of 0. For those rows, derive it from qty - extra_qty (or from
	Extra (%) if extra_qty has not yet been populated).
	"""
	if not forecast or not frappe.db.table_exists("Order Line"):
		return 0.0

	confirmed = frappe.db.sql(
		"""
		select coalesce(sum(
			case
				when ifnull(original_qty, 0) > 0 then original_qty
				else greatest(
					ifnull(qty, 0) - case
						when ifnull(extra_qty, 0) > 0 then extra_qty
						else round(ifnull(qty, 0) * ifnull(extra, 0) / 100, 0)
					end,
					0
				)
			end
		), 0)
		from `tabOrder Line`
		where forecast = %s and ifnull(status, '') != 'Cancelled'
		""",
		forecast,
	)[0][0]
	return flt(confirmed)


def has_active_order_lines(forecast):
	"""Return True when at least one non-cancelled Order Line uses this forecast."""
	if not forecast or not frappe.db.table_exists("Order Line"):
		return False

	return bool(
		frappe.db.sql(
			"""
			select name
			from `tabOrder Line`
			where forecast = %s and ifnull(status, '') != 'Cancelled'
			limit 1
			""",
			forecast,
		)
	)


def calculate_remaining_qty(qty, confirmed_qty):
	"""Return the remaining forecast quantity, never below zero."""
	return max(flt(qty) - flt(confirmed_qty), 0.0)


def calculate_progress(qty, value, value_usd, confirmed_qty):
	"""Calculate confirmed and remaining forecast quantities and values."""
	qty = flt(qty)
	confirmed = flt(confirmed_qty)
	remaining = calculate_remaining_qty(qty, confirmed)

	if remaining > 0:
		status = "Partly Confirmed" if confirmed > 0 else "Projected"
	else:
		status = "Confirmed"

	ratio = remaining / qty if qty else 0.0
	return {
		"status": status,
		"confirmed_qty": confirmed,
		"remaining_qty": remaining,
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
		self.validate_locked_values()
		self.set_currency()
		self.set_month()
		self.log_month_change()
		self.check_month_log_not_changed()
		self.set_amounts()
		self.set_progress()
		self.validate_duplicate()
		self.warn_if_past_month()


	def validate_locked_values(self):
		"""Once an active Order Line exists, the Forecast Qty and Value are frozen."""
		before = self.get_doc_before_save()
		if not before or not has_active_order_lines(before.name):
			return

		qty_changed = flt(before.qty) != flt(self.qty)
		value_changed = flt(before.value, 2) != flt(self.value, 2)
		if qty_changed or value_changed:
			changed = []
			if qty_changed:
				changed.append(_("Forecast Qty"))
			if value_changed:
				changed.append(_("Forecast Value"))
			frappe.throw(
				_("{0} cannot be changed because this Forecast already has a confirmed Order Line. "
				  "You can still move the Forecast Month; the remaining quantity will be recorded in the Month Change Log.").format(
					frappe.bold(_(" and ").join(changed))
				)
			)

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
			for fieldname in ("from_month", "to_month", "remaining_qty_moved", "edited_by", "edited_on"):
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
		expected_remaining_qty = calculate_remaining_qty(
			before.qty, get_confirmed_qty(before.name)
		)
		if (
			getdate(log_row.from_month) != getdate(before.forecast_month)
			or getdate(log_row.to_month) != getdate(self.forecast_month)
			or flt(log_row.remaining_qty_moved) != flt(expected_remaining_qty)
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

		remaining_qty_moved = calculate_remaining_qty(
			before.qty, get_confirmed_qty(before.name)
		)
		self.append(
			"month_change_log",
			{
				"from_month": before.forecast_month,
				"to_month": self.forecast_month,
				"remaining_qty_moved": remaining_qty_moved,
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
