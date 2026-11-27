// Copyright (c) 2026, Merch TNA Tracker and contributors
// For license information, please see license.txt

frappe.ui.form.on("Order Forecast", {
	refresh(frm) {
		frm.trigger("apply_confirmed_order_locks");
	},

	confirmed_qty(frm) {
		frm.trigger("apply_confirmed_order_locks");
	},

	apply_confirmed_order_locks(frm) {
		const has_confirmed_order = flt(frm.doc.confirmed_qty) > 0;
		frm.set_df_property("qty", "read_only", has_confirmed_order ? 1 : 0);
		frm.set_df_property("value", "read_only", has_confirmed_order ? 1 : 0);

		if (has_confirmed_order) {
			frm.dashboard.set_headline_alert(
				__("Forecast Qty and Value are locked because confirmed Order Lines already exist. Forecast Month can still be moved; remaining quantity will be logged."),
				"orange"
			);
		} else {
			frm.dashboard.clear_headline();
		}
	}
});
