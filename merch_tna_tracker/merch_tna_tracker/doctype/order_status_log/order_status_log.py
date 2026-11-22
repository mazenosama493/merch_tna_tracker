# Copyright (c) 2026, Merch TNA Tracker and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class OrderStatusLog(Document):
	# Child table: Frappe does not run validate() on child rows by itself.
	# Its rules (user filled automatically, old rows locked, a row added when the
	# status changes) live in Order Line.validate().
	pass
