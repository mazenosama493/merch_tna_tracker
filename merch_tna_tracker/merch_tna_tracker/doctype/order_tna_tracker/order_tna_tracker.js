function style_diff_cell(grid_row) {
    if (!grid_row || !grid_row.doc || !grid_row.columns || !grid_row.columns.diff_days) return;

    // Keep cell uncolored if actual_date is empty
    if (!grid_row.doc.actual_date) {
        grid_row.columns.diff_days.css({
            'background-color': '',
            color: ''
        });
        return;
    }

    const is_negative = Number(grid_row.doc.diff_days) < 0;

    if (is_negative) {
        // Heavy deep red styling for negative/delayed days
        grid_row.columns.diff_days.css({
            'background-color': '#d32f2f',
            'color': '#ffffff',
            'font-weight': 'bold'
        });
    } else {
        // Heavy solid green styling for positive/on-time days
        grid_row.columns.diff_days.css({
            'background-color': '#2e7d32', // Strong material green
            'color': '#ffffff',            // White text for high contrast
            'font-weight': 'bold'
        });
        
        /* 
        // Or if you prefer a heavy soft green tint instead of solid dark green, uncomment below:
        grid_row.columns.diff_days.css({
            'background-color': '#c8e6c9', // Heavy green tint
            'color': '#1b5e20',            // Very dark, high-contrast green text
            'font-weight': 'bold'
        });
        */
    }
}

// Colors for the Order Status field
const ORDER_STATUS_COLORS = {
    'Not yet Started': { bg: '#f57c00', fg: '#ffffff' }, // Orange
    'In Progress':     { bg: '#3542fd', fg: '#ffffff' }, // Yellow (dark text for contrast)
    'Completed':       { bg: '#2e7d32', fg: '#ffffff' }  // Green
};

function style_order_status(frm, status) {
    const field = frm.fields_dict.order_status;
    if (!field || !field.$wrapper) return;

    // Use the status passed in (just calculated) or fall back to the saved value
    status = status || frm.doc.order_status || 'Not yet Started';
    const color = ORDER_STATUS_COLORS[status] || ORDER_STATUS_COLORS['Not yet Started'];

    // Read-only fields render as .control-value, editable ones as input/select
    field.$wrapper.find('.control-value, .control-input input, .control-input select').css({
        'background-color': color.bg,
        'color': color.fg,
        'font-weight': 'bold',
        'border-radius': '6px'
    });
}

frappe.ui.form.on('Order TNA Tracker', {
    refresh: function(frm) {
        $(frm.wrapper)
            .off('grid-row-render.diff-days')
            .on('grid-row-render.diff-days', function(event, grid_row) {
                if (grid_row.grid.df.fieldname === 'tna_details') {
                    style_diff_cell(grid_row);
                }
            });

        // Style already-rendered rows on form refresh
        if (frm.fields_dict.tna_details && frm.fields_dict.tna_details.grid) {
            (frm.fields_dict.tna_details.grid.grid_rows || []).forEach(function(grid_row) {
                style_diff_cell(grid_row);
            });
        }

        // Color the Order Status field when the form loads / reloads after save
        style_order_status(frm);
    },

    // Re-color whenever the status value changes
    order_status: function(frm) {
        style_order_status(frm);
    },

    order_received_date: function(frm) {
        frm.trigger('calculate_lead_time_and_fetch_plan');
    },

    ex_fty_date: function(frm) {
        frm.trigger('calculate_lead_time_and_fetch_plan');
    },

    calculate_lead_time_and_fetch_plan: function(frm) {
        if (frm.doc.order_received_date && frm.doc.ex_fty_date) {
            let lead_time = frappe.datetime.get_day_diff(frm.doc.ex_fty_date, frm.doc.order_received_date);
            frm.set_value('lead_time', lead_time);

            if (lead_time <= 0) {
                frappe.msgprint(__('Ex Fty Date must be after Order Received Date.'));
                return;
            }

            // 1. Pick the LONGEST plan that still fits inside the lead time
            //    (delivery_lead_time <= lead_time), e.g. lead time 46 with
            //    plans 45 and 60 -> picks 45.
            frappe.call({
                method: 'frappe.client.get_list',
                args: {
                    doctype: 'TNA Plan Template',
                    filters: {
                        'delivery_lead_time': ['<=', lead_time]
                    },
                    fields: ['name', 'delivery_lead_time'],
                    order_by: 'delivery_lead_time desc',
                    limit_page_length: 1
                },
                callback: function(r) {
                    if (r.message && r.message.length > 0) {
                        let matched_plan = r.message[0].name;
                        frm.set_value('tna_plan', matched_plan);
                        frm.trigger('load_plan_events');
                    } else {
                        // 2. Lead time is shorter than every plan:
                        //    fall back to the shortest available plan
                        frm.trigger('fetch_fallback_plan');
                    }
                }
            });
        }
    },

    fetch_fallback_plan: function(frm) {
        let lead_time = frm.doc.lead_time;
        frappe.call({
            method: 'frappe.client.get_list',
            args: {
                doctype: 'TNA Plan Template',
                fields: ['name', 'delivery_lead_time'],
                order_by: 'delivery_lead_time asc',
                limit_page_length: 1
            },
            callback: function(r) {
                if (r.message && r.message.length > 0) {
                    let fallback_plan = r.message[0].name;
                    frm.set_value('tna_plan', fallback_plan);
                    frm.trigger('load_plan_events');
                    frappe.show_alert({
                        message: __('No plan fits within ') + lead_time + __(' days. Shortest available plan selected automatically.'),
                        indicator: 'orange'
                    }, 5);
                } else {
                    frappe.msgprint(__('No TNA plans are registered in the system!'));
                }
            }
        });
    },

    load_plan_events: function(frm) {
        if (!frm.doc.tna_plan || !frm.doc.order_received_date) return;

        if (frm.doc.tna_details && frm.doc.tna_details.length > 0 && !frm.is_new()) {
            frappe.confirm(
                'Changing the dates will recalculate the entire plan and may clear existing actual dates. Do you want to proceed?',
                function() {
                    frm.trigger('execute_plan_load');
                }
            );
        } else {
            frm.trigger('execute_plan_load');
        }
    },

    execute_plan_load: function(frm) {
        frappe.model.with_doc('TNA Plan Template', frm.doc.tna_plan, function() {
            let plan_doc = frappe.model.get_doc('TNA Plan Template', frm.doc.tna_plan);
            frm.clear_table('tna_details');

            (plan_doc.events || []).forEach(function(row) {
                let child = frm.add_child('tna_details');
                child.event_name = row.event_name;
                child.days_offset = row.days_offset;
                child.plan_date = frappe.datetime.add_days(frm.doc.order_received_date, row.days_offset);
            });

            frm.refresh_field('tna_details');
            frm.set_value('total_events', (plan_doc.events || []).length);
            frm.set_value('failed_events', 0);

            // Freshly loaded plan has no actual dates -> Not yet Started
            frm.trigger('update_order_status');
        });
    },

    update_totals: function(frm) {
        let failed_count = 0;
        let total_count = (frm.doc.tna_details || []).length;
        (frm.doc.tna_details || []).forEach(function(r) {
            if (r.actual_date && r.diff_days < 0) {
                failed_count += 1;
            }
        });
        frm.set_value('total_events', total_count);
        frm.set_value('failed_events', failed_count);

        frm.trigger('update_order_status');
    },

    // Not yet Started : no rows, or no row has an actual date   -> orange
    // In Progress     : at least one row has an actual date     -> yellow
    // Completed       : every row has an actual date            -> green
    update_order_status: function(frm) {
        const rows = frm.doc.tna_details || [];
        const done = rows.filter(function(r) { return r.actual_date; }).length;

        let status = 'Not yet Started';
        if (rows.length && done === rows.length) {
            status = 'Completed';
        } else if (done) {
            status = 'In Progress';
        }

        frm.set_value('order_status', status);

        // Color immediately with the status just calculated
        style_order_status(frm, status);
    }
});

frappe.ui.form.on('TNA Tracker Detail', {
    diff_days: function(frm, cdt, cdn) {
        let grid_row = frm.fields_dict.tna_details.grid.grid_rows_by_docname[cdn];
        if (grid_row) {
            style_diff_cell(grid_row);
        }
    },

    plan_date: function(frm, cdt, cdn) {
        let row = locals[cdt][cdn];
        if (row.plan_date && row.actual_date) {
            let diff = frappe.datetime.get_day_diff(row.plan_date, row.actual_date);
            frappe.model.set_value(cdt, cdn, 'diff_days', diff);
        }
        let grid_row = frm.fields_dict.tna_details.grid.grid_rows_by_docname[cdn];
        if (grid_row) {
            style_diff_cell(grid_row);
        }
        frm.trigger('update_totals');
    },

    actual_date: function(frm, cdt, cdn) {
        let row = locals[cdt][cdn];
        if (row.plan_date && row.actual_date) {
            let diff = frappe.datetime.get_day_diff(row.plan_date, row.actual_date);
            frappe.model.set_value(cdt, cdn, 'diff_days', diff);
        } else {
            frappe.model.set_value(cdt, cdn, 'diff_days', 0);
        }

        // Re-style immediately (handles cases where diff_days was already 0)
        let grid_row = frm.fields_dict.tna_details.grid.grid_rows_by_docname[cdn];
        if (grid_row) {
            style_diff_cell(grid_row);
        }

        frm.trigger('update_totals');
    },

    tna_details_add: function(frm) {
        frm.trigger('update_totals');
    },

    tna_details_remove: function(frm) {
        frm.trigger('update_totals');
    }
});