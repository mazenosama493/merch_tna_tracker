// Copyright (c) 2026, Merch TNA Tracker and contributors
// For license information, please see license.txt

frappe.ui.form.on("Merch Buyer", {
	setup(frm) {
		// Buyer Group dropdown: top-level records only, and never the record itself.
		frm.set_query("buyer_group", () => {
			return {
				filters: {
					buyer_group: ["is", "not set"],
					name: ["!=", frm.doc.name],
				},
			};
		});
	},
});
