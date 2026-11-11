# Copyright (c) 2026, Your Company and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

MERCHANT_ROLE = "TNA Tracker Merchant"


class Merchant(Document):
    def on_update(self):
        # If the linked user was changed, take the role away from the old user
        before = self.get_doc_before_save()
        if before and before.useremail and before.useremail != self.useremail:
            self.remove_role(before.useremail)

        self.add_role(self.useremail)

    def on_trash(self):
        self.remove_role(self.useremail)

    @staticmethod
    def add_role(email):
        if email and frappe.db.exists("User", email):
            frappe.get_doc("User", email).add_roles(MERCHANT_ROLE)

    @staticmethod
    def remove_role(email):
        if email and frappe.db.exists("User", email):
            frappe.get_doc("User", email).remove_roles(MERCHANT_ROLE)