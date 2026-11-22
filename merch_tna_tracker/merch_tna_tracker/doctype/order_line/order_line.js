// Copyright (c) 2026, Merch TNA Tracker and contributors
// For license information, please see license.txt

frappe.ui.form.on("Order Line", {
	setup(frm) {
		// Only forecasts that still have something left. The server also checks the buyer.
		frm.set_query("forecast", () => {
			return { filters: { status: ["in", ["Projected", "Partly Confirmed"]] } };
		});
	},

	qty(frm) {
		set_amounts(frm);
	},

	unit_price(frm) {
		set_amounts(frm);
	},

	unit_price_ddp(frm) {
		set_amounts(frm);
	},

	add_discount(frm) {
		if (!frm.doc.add_discount) {
			frm.set_value("discount_amount", 0);
		}
		set_amounts(frm);
	},

	discount_amount(frm) {
		set_amounts(frm);
	},

	add_extra(frm) {
		if (!frm.doc.add_extra) {
			frm.set_value("extra_qty", 0);
		}
		set_amounts(frm);
	},

	extra_qty(frm) {
		set_amounts(frm);
	},
});

// Preview only. The server recalculates FOB Price, DDP Price, Amount, Exchange Rate and Amount USD when you save.
function set_amounts(frm) {
	const qty = flt(frm.doc.qty);
	const extra_pct = frm.doc.add_extra ? flt(frm.doc.extra_qty) : 0;
	const effective_qty = qty * (1 + extra_pct / 100);

	const discount_pct = frm.doc.add_discount ? flt(frm.doc.discount_amount) : 0;
	const discount_multiplier = 1 - discount_pct / 100;

	const fob_price = flt(effective_qty * flt(frm.doc.unit_price) * discount_multiplier, 4);
	const ddp_price = flt(effective_qty * flt(frm.doc.unit_price_ddp) * discount_multiplier, 4);
	const total_amount = flt(fob_price + ddp_price, 2);

	frm.set_value("fob_price", fob_price);
	frm.set_value("ddp_price", ddp_price);
	frm.set_value("amount", total_amount);
}
