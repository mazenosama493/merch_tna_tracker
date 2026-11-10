# Copyright (c) 2026, Your Company and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe import _

# Child table fieldname on the parent doctype
CHILD_TABLE = "tna_details"

# Date field on the child doctype "TNA Tracker Detail"
# Change this if your field is named differently
ACTUAL_DATE_FIELD = "actual_date"
ALLOWED_ROLES_TO_DELETE_ROWS = {"System Manager", "TNA Tracker Admin"}


class OrderTNATracker(Document):
    def validate(self):
        # If you already have other logic here (lead_time, tna_plan,
        # total_events, failed_events ...), keep it and just make sure
        # set_order_status() is called.
        self.set_order_status()
        self.prevent_row_deletion()

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