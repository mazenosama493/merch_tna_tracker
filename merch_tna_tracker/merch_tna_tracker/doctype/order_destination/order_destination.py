# Copyright (c) 2026, Merch TNA Tracker and contributors
# For license information, please see license.txt

import re

import frappe
from frappe import _
from frappe.model.document import Document


def clean_text(value):
	"""Trim and collapse repeated spaces. Capitalisation is kept as typed (USA, EU, Italy)."""
	return " ".join((value or "").split())


class OrderDestination(Document):
	def before_naming(self):
		# Runs before autoname (field:destination_name), so the record name itself is clean.
		self.destination_name = clean_text(self.destination_name)

	def validate(self):
		self.destination_name = clean_text(self.destination_name)

		if not re.search(r"[A-Za-z]", self.destination_name or ""):
			frappe.throw(_("Destination must contain letters, e.g. USA or Italy."))
