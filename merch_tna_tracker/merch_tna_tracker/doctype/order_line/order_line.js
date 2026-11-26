// Copyright (c) 2026, Merch TNA Tracker and contributors
// For license information, please see license.txt

frappe.ui.form.on("Order Line", {
	setup(frm) {
		// Only forecasts that still have something left. The server also checks the buyer.
		frm.set_query("forecast", () => {
			return { filters: { status: ["in", ["Projected", "Partly Confirmed"]] } };
		});

		// A shipment can only go to one of the line's destinations.
		frm.set_query("destination", "shipments", () => {
			const names = (frm.doc.destinations || []).map((row) => row.destination).filter(Boolean);
			return names.length ? { filters: { name: ["in", names] } } : {};
		});
	},

	qty(frm) {
		set_amount(frm);
	},

	unit_price(frm) {
		set_amount(frm);
	},
});

// Preview only. The server recalculates Amount, Exchange Rate and Amount USD when you save.
function set_amount(frm) {
	frm.set_value("amount", flt(frm.doc.qty) * flt(frm.doc.unit_price));
}

// With destinations, the qty of the line is the total of the destination quantities.
frappe.ui.form.on("Order Line Destination", {
	qty(frm) {
		set_qty_from_destinations(frm);
	},

	destinations_remove(frm) {
		set_qty_from_destinations(frm);
	},
});

function set_qty_from_destinations(frm) {
	const rows = frm.doc.destinations || [];
	if (rows.length) {
		frm.set_value("qty", rows.reduce((sum, row) => sum + flt(row.qty), 0));
	}
}
