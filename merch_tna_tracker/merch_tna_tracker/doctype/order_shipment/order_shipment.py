# Copyright (c) 2026, Merch TNA Tracker and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class OrderShipment(Document):
	# Child table: Frappe does not run validate() on child rows by itself.
	# Its rules (qty above zero, total vs order qty, shipped qty and status roll-up)
	# live in Order Line.validate(), which is where the order qty is available.
	pass
