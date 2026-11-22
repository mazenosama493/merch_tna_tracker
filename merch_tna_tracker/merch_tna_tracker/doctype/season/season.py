# Copyright (c) 2026, Merch TNA Tracker and contributors
# For license information, please see license.txt

import re

import frappe
from frappe import _
from frappe.model.document import Document

# Two letters + two-digit year, optionally followed by a label: "FW 26", "SU27 Chase"
SEASON_PATTERN = re.compile(r"^([A-Z]{2})\s*(\d{2})(?:\s+(.+))?$")


def normalize_season_code(code):
	"""Upper-case, trim, and join letters with the year: 'fw 26' -> 'FW26', 'su27  chase' -> 'SU27 CHASE'."""
	code = " ".join((code or "").split()).upper()
	match = SEASON_PATTERN.match(code)
	if match:
		base = match.group(1) + match.group(2)
		return f"{base} {match.group(3)}" if match.group(3) else base
	return code


class Season(Document):
	def before_naming(self):
		# Runs before autoname (field:season_code), so the record name itself is clean.
		self.season_code = normalize_season_code(self.season_code)

	def validate(self):
		self.season_code = normalize_season_code(self.season_code)
		self.validate_season_code()
		self.description = " ".join((self.description or "").split())

	def validate_season_code(self):
		# Catches stray numeric values such as 202601.0 that came from Excel.
		if not re.search(r"[A-Z]", self.season_code or ""):
			frappe.throw(_("Season Code must contain letters, e.g. SP26 or FW27."))
