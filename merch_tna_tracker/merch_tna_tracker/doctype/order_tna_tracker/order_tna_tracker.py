# Copyright (c) 2026, Your Company and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe import _
from frappe.utils import getdate, nowdate

# Child table fieldname on the parent doctype
CHILD_TABLE = "tna_details"

# Date field on the child doctype "TNA Tracker Detail"
# Change this if your field is named differently
ACTUAL_DATE_FIELD = "actual_date"
ALLOWED_ROLES_TO_DELETE_ROWS = {"System Manager", "TNA Tracker Admin"}

# Role given to merchants, and roles that are never restricted
MERCHANT_ROLE = "TNA Tracker Merchant"
UNRESTRICTED_ROLES = {"System Manager", "TNA Tracker Admin"}

# Parent date fields a restricted merchant is not allowed to change
MERCHANT_LOCKED_DATE_FIELDS = ("order_received_date", "ex_fty_date")


class OrderTNATracker(Document):
    def validate(self):
        # If you already have other logic here (lead_time, tna_plan,
        # total_events, failed_events ...), keep it and just make sure
        # set_order_status() is called.
        self.enforce_merchant_ownership()
        self.prevent_merchant_date_changes()
        self.validate_order_dates()
        self.validate_actual_dates_are_today()
        self.set_order_status()
        self.prevent_row_deletion()

    def enforce_merchant_ownership(self):
        """Restricted merchants can only save trackers assigned to themselves."""
        user = frappe.session.user
        if not _is_restricted(user):
            return

        merchant = _merchant_of(user)
        if not merchant:
            frappe.throw(_("Your user is not linked to a Merchant record."))

        if self.is_new() and not self.merchant:
            self.merchant = merchant

        if self.merchant != merchant:
            frappe.throw(_("You can only save trackers assigned to you."))

    def prevent_merchant_date_changes(self):
        """Restricted merchants cannot change Order Received Date or Ex Fty Date."""
        if self.is_new() or not _is_restricted(frappe.session.user):
            return

        old = self.get_doc_before_save()
        if not old:
            return

        for fieldname in MERCHANT_LOCKED_DATE_FIELDS:
            if _date_str(old.get(fieldname)) != _date_str(self.get(fieldname)):
                frappe.throw(
                    _("You are not allowed to change {0}.").format(
                        frappe.bold(_(self.meta.get_label(fieldname)))
                    ),
                    title=_("Not Allowed"),
                )

    def validate_order_dates(self):
        """
        Ex Fty Date must be after Order Received Date: it cannot be equal to or
        before it. Applies to everyone, System Manager included.

        Only checked on a new record or when one of the two dates was changed,
        so an older record can still be saved for other reasons
        (e.g. when a merchant fills in an actual date).
        """
        # validate() runs before the mandatory-field check, so either may be empty
        if not (self.order_received_date and self.ex_fty_date):
            return

        old = None if self.is_new() else self.get_doc_before_save()

        def changed(fieldname):
            return not old or _date_str(old.get(fieldname)) != _date_str(self.get(fieldname))

        received = getdate(self.order_received_date)
        ex_fty = getdate(self.ex_fty_date)

        if (changed("order_received_date") or changed("ex_fty_date")) and ex_fty <= received:
            frappe.throw(
                _("Ex Fty Date must be after Order Received Date."),
                title=_("Invalid Date"),
            )

    def validate_actual_dates_are_today(self):
        """
        Everyone (TNA Tracker Admin, TNA Tracker Manager, TNA Tracker Merchant,
        any other role) can only set an event's actual date to today.
        Only System Manager is exempt.

        Only rows whose actual date was added or changed in this save are
        checked, so dates that were already saved (e.g. on a previous day)
        never block a later save.
        """
        if not _must_use_today(frappe.session.user):
            return

        today = getdate(nowdate())

        old = self.get_doc_before_save()
        old_dates = {}
        if old:
            old_dates = {
                str(d.name): d.get(ACTUAL_DATE_FIELD) for d in (old.get(CHILD_TABLE) or [])
            }

        for row in self.get(CHILD_TABLE) or []:
            new_value = row.get(ACTUAL_DATE_FIELD)
            if not new_value:
                continue

            # getdate(None) returns today, so guard the old value explicitly
            old_value = old_dates.get(str(row.name))
            if old_value and getdate(old_value) == getdate(new_value):
                continue  # unchanged

            if getdate(new_value) != today:
                frappe.throw(
                    _("Row {0}: You cannot add an actual date that is not today for the event {1}.").format(
                        row.idx, frappe.bold(row.get("event_name") or "")
                    ),
                    title=_("Invalid Actual Date"),
                )

    def set_order_status(self):
        """
        Not yet Started : no event has an actual date (or there are no events)
        In Progress     : at least one event has an actual date, but not all
        Completed       : every event has an actual date

        Recalculated from the rows on every save, so adding rows, deleting
        rows and clearing/setting actual dates are all handled.
        """
        rows = self.get(CHILD_TABLE) or []
        total = len(rows)
        done = sum(1 for row in rows if row.get(ACTUAL_DATE_FIELD))

        # "total and" guard: with zero rows, done == total would be True
        # and the order would wrongly show as Completed.
        if total and done == total:
            self.order_status = "Completed"
        elif done:
            self.order_status = "In Progress"
        else:
            self.order_status = "Not yet Started"

    def prevent_row_deletion(self):
        if self.is_new() or self.flags.allow_row_delete:
            return
        if ALLOWED_ROLES_TO_DELETE_ROWS & set(frappe.get_roles()):
            return

        old = self.get_doc_before_save()
        if not old:
            return

        old_rows = {str(d.name) for d in old.tna_details}
        new_rows = {str(d.name) for d in self.tna_details}
        if old_rows - new_rows:
            frappe.throw(_("You are not allowed to delete TNA Details rows"))


# ---------------------------------------------------------------------------
# Merchant-level access (wired up in hooks.py)
# ---------------------------------------------------------------------------

def _merchant_of(user):
    return frappe.db.get_value("Merchant", {"useremail": user}, "name")


def _is_restricted(user):
    roles = set(frappe.get_roles(user))
    return MERCHANT_ROLE in roles and not (UNRESTRICTED_ROLES & roles)


def _date_str(value):
    """Normalise a date/str/None for comparison (getdate(None) would return today)."""
    return str(getdate(value)) if value else ""


def _must_use_today(user):
    """Actual dates must be today for every user except System Manager."""
    return "System Manager" not in set(frappe.get_roles(user))


def get_permission_query_conditions(user=None):
    """Filters list views, reports and link searches."""
    user = user or frappe.session.user
    if not _is_restricted(user):
        return ""

    merchant = _merchant_of(user)
    if not merchant:
        return "1=0"

    return f"`tabOrder TNA Tracker`.merchant = {frappe.db.escape(merchant)}"


def has_permission(doc, ptype=None, user=None, debug=False):
    """Guards direct access (URL, API) to a single document."""
    user = user or frappe.session.user
    if not _is_restricted(user):
        return True

    # New, unsaved docs: validate() assigns/checks the merchant
    if doc.is_new() or not doc.merchant:
        return True

    return doc.merchant == _merchant_of(user)


def refresh_order_status(name):
    """
    Recalculate and store the status of one Order TNA Tracker without
    going through a full save. Use this when child rows are changed
    outside the form (frappe.db.set_value, API, scripts, patches).

    Example:
        from <your_app>.merch_tna_tracker.doctype.order_tna_tracker.order_tna_tracker import refresh_order_status
        refresh_order_status("BUYER-STYLE-SO-0001")
    """
    doc = frappe.get_doc("Order TNA Tracker", name)
    doc.set_order_status()
    doc.db_set("order_status", doc.order_status, update_modified=False)


def refresh_all_order_statuses():
    """
    One-off fix for existing records. Run in `bench console`:

        from <your_app>.merch_tna_tracker.doctype.order_tna_tracker.order_tna_tracker import refresh_all_order_statuses
        refresh_all_order_statuses()
    """
    for name in frappe.get_all("Order TNA Tracker", pluck="name"):
        refresh_order_status(name)
    frappe.db.commit()