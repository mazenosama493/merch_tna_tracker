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

	refresh(frm) {
		refresh_ship_percentage(frm);
		load_po_price_term(frm);
	},

	buyer_po(frm) {
		load_po_price_term(frm);
	},

	qty(frm) {
		refresh_order_line_amounts(frm);
	},

	extra(frm) {
		refresh_order_line_amounts(frm);
	},

	unit_price(frm) {
		refresh_order_line_amounts(frm);
	},

	unit_price_ddp(frm) {
		refresh_order_line_amounts(frm);
	},

	discount_amount(frm) {
		refresh_order_line_amounts(frm);
	},

	currency(frm) {
		refresh_order_line_amounts(frm);
	},

	validate(frm) {
		const discount = flt(frm.doc.discount_amount);
		if (discount < 0 || discount > 100) {
			frappe.throw(__("Discount must be between 0% and 100%."));
		}

		if (flt(frm.doc.extra) < 0 || flt(frm.doc.extra) > 100) {
			frappe.throw(__("Extra (%) must be between 0% and 100%."));
		}
	},
});

async function load_po_price_term(frm) {
	if (!frm.doc.buyer_po) {
		frm.po_price_term = "FOB";
		update_ddp_fields(frm);
		await refresh_order_line_amounts(frm);
		return;
	}

	const selected_po = frm.doc.buyer_po;
	try {
		await frappe.model.with_doc("Buyer PO", selected_po);
		// Ignore a late response if the user selected another PO in the meantime.
		if (frm.doc.buyer_po !== selected_po) return;

		const po = frappe.model.get_doc("Buyer PO", selected_po);
		if (!po || typeof po.price_term === "undefined") {
			frappe.msgprint(__("The Price Term field was not loaded from the selected Buyer PO. Please sync the Buyer PO DocType and reload."));
			frm.po_price_term = "FOB";
		} else {
			frm.po_price_term = po.price_term || "FOB";
			// Mirror PO-owned fields for immediate UI preview. The server remains authoritative.
			await frm.set_value({
				buyer: po.buyer,
				season: po.season,
				currency: po.currency,
			});
		}

		update_ddp_fields(frm);
		await refresh_order_line_amounts(frm);
	} catch (error) {
		console.error("Could not load Buyer PO pricing details", error);
		frappe.msgprint(__("Could not load the selected Buyer PO pricing details. Please try again."));
	}
}

function update_ddp_fields(frm) {
	const is_ddp = frm.po_price_term === "DDP";
	frm.toggle_display("unit_price_ddp", is_ddp);
	frm.toggle_display("ddp_price", is_ddp);
	frm.toggle_reqd("unit_price_ddp", is_ddp);
	// DDP Price is read-only but is calculated automatically on the client and server.
	frm.toggle_reqd("ddp_price", is_ddp);
}

function get_preview_exchange_rate(frm) {
	const currency = (frm.doc.currency || "").toUpperCase();
	if (currency === "USD") return Promise.resolve(1.0);
	if (!currency) return Promise.resolve(0);

	// Existing Order Lines must retain the rate captured at creation.
	if (!frm.is_new() && flt(frm.doc.exchange_rate) > 0) {
		return Promise.resolve(flt(frm.doc.exchange_rate, 4));
	}

	// New EUR Order Lines use the current Settings rate. Cache it while this form is open.
	if (!frm.__eur_usd_rate_promise) {
		frm.__eur_usd_rate_promise = frappe.db.get_single_value(
			"Order Book Settings",
			"eur_to_usd_rate"
		).then((rate) => {
			const parsed_rate = flt(rate, 4);
			if (parsed_rate <= 0) {
				throw new Error("EUR to USD Rate is missing in Order Book Settings.");
			}
			return parsed_rate;
		}).catch((error) => {
			frm.__eur_usd_rate_promise = null;
			throw error;
		});
	}

	return frm.__eur_usd_rate_promise;
}

/**
 * Recalculate all price outputs in the open form.
 *
 * IMPORTANT: write calculated values directly to frm.doc and refresh the fields.
 * This avoids nested frm.set_value calls while field handlers are already running,
 * and ensures Amount USD is refreshed together with Amount after every edit.
 */
async function refresh_order_line_amounts(frm) {
	// Prevent a slower exchange-rate response from overwriting a newer calculation.
	frm.__order_line_calculation_id = (frm.__order_line_calculation_id || 0) + 1;
	const calculation_id = frm.__order_line_calculation_id;

	const qty = flt(frm.doc.qty);
	const extra_percent = flt(frm.doc.extra);
	const calculated_extra_qty = flt((qty * extra_percent) / 100, 0);
	const calculated_original_qty = Math.max(flt(qty - calculated_extra_qty, 0), 0);
	frm.doc.extra_qty = calculated_extra_qty;
	frm.doc.original_qty = calculated_original_qty;
	frm.refresh_field("extra_qty");
	frm.refresh_field("original_qty");
	refresh_ship_percentage(frm);

	const fob_amount = flt(qty * flt(frm.doc.unit_price), 2);
	const is_ddp = frm.po_price_term === "DDP";
	const ddp_amount = is_ddp ? flt(qty * flt(frm.doc.unit_price_ddp), 2) : 0;
	const gross_amount = flt(fob_amount + ddp_amount, 2);
	const discount_percent = flt(frm.doc.discount_amount);
	const discount_value = flt(gross_amount * discount_percent / 100, 2);
	const net_amount = flt(gross_amount - discount_value, 2);

	// Update local currency values synchronously so the form responds immediately.
	frm.doc.fob_price = fob_amount;
	frm.doc.ddp_price = ddp_amount;
	frm.doc.amount = net_amount;
	frm.refresh_field("fob_price");
	frm.refresh_field("ddp_price");
	frm.refresh_field("amount");

	try {
		const exchange_rate = await get_preview_exchange_rate(frm);
		// Ignore this result if the user changed any price field while the rate was loading.
		if (calculation_id !== frm.__order_line_calculation_id) return;
		if (exchange_rate > 0) {
			frm.doc.exchange_rate = flt(exchange_rate, 4);
			frm.doc.amount_usd = flt(net_amount * exchange_rate, 2);
			frm.refresh_field("exchange_rate");
			frm.refresh_field("amount_usd");
		}
	} catch (error) {
		if (calculation_id === frm.__order_line_calculation_id) {
			console.error("Could not calculate Amount USD preview", error);
			frm.doc.amount_usd = 0;
			frm.refresh_field("amount_usd");
		}
	}
}

// Ship % is calculated from Original Quantity, excluding Extra Qty.
frappe.ui.form.on("Order Shipment", {
	shipped_qty(frm) {
		refresh_ship_percentage(frm);
	},
});

frappe.ui.form.on("Order Line", {
	shipments_add(frm) {
		refresh_ship_percentage(frm);
	},

	shipments_remove(frm) {
		refresh_ship_percentage(frm);
	},
});

function refresh_ship_percentage(frm) {
	const shipments = frm.doc.shipments || [];
	const total_shipped = shipments.reduce((sum, row) => sum + flt(row.shipped_qty), 0);
	const original_qty = flt(frm.doc.original_qty);

	frm.doc.shipped_qty = total_shipped;
	frm.doc.ship_pct = original_qty > 0 ? flt((total_shipped / original_qty) * 100, 2) : 0;
	frm.refresh_field("shipped_qty");
	frm.refresh_field("ship_pct");
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
		const total_qty = rows.reduce((sum, row) => sum + flt(row.qty), 0);
		frm.set_value("qty", total_qty).then(() => refresh_order_line_amounts(frm));
	}
}
