// Copyright (c) 2026, Merch TNA Tracker and contributors
// For license information, please see license.txt

frappe.ui.form.on("Buyer PO", {
	refresh(frm) {
		refresh_po_totals_preview(frm);
	},

	price_term(frm) {
		// Show the total for the newly selected term immediately, before saving the PO.
		refresh_po_totals_preview(frm);
	},

	after_save(frm) {
		refresh_po_totals_preview(frm);
	},
});

// Other browser tabs can update Order Lines belonging to this PO. The Python
// controller publishes this event after recalculating the totals in the database.
frappe.realtime.on("buyer_po_totals_updated", (data) => {
	const frm = cur_frm;
	if (!frm || frm.doctype !== "Buyer PO" || frm.doc.name !== data.buyer_po) return;

	// Re-fetch using the current form Price Term so an unsaved Price Term change
	// is not overwritten by totals calculated for the previously saved term.
	refresh_po_totals_preview(frm);
});

function refresh_po_totals_preview(frm) {
	if (!frm.doc.name || frm.is_new()) {
		frm.doc.total_qty = 0;
		frm.doc.total_amount = 0;
		frm.refresh_field("total_qty");
		frm.refresh_field("total_amount");
		return;
	}

	const po_name = frm.doc.name;
	const price_term = frm.doc.price_term || "FOB";

	frappe.call({
		method: "merch_tna_tracker.merch_tna_tracker.doctype.buyer_po.buyer_po.get_po_totals_preview",
		args: { po_name, price_term },
		callback(response) {
			// Ignore stale responses if the user navigated to a different PO.
			if (frm.doc.name !== po_name || !response.message) return;
			// These are read-only aggregates; update the form display without marking
			// the Buyer PO itself as manually edited.
			frm.doc.total_qty = flt(response.message.total_qty);
			frm.doc.total_amount = flt(response.message.total_amount);
			frm.refresh_field("total_qty");
			frm.refresh_field("total_amount");
		},
	});
}
