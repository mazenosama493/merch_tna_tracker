# Copyright (c) 2026, Merch TNA Tracker and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class OrderDateRevision(Document):
	# Child table: Frappe does not run validate() on child rows by itself.
	# Its rules (numbering, repeated-date check, editor/timestamp, history lock) live in
	# Order Line.validate(), which is where the parent's dates are available.
	pass
