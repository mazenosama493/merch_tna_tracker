function style_diff_cell(grid_row) {
    if (!grid_row || !grid_row.doc || !grid_row.columns || !grid_row.columns.diff_days) return;

    if (!grid_row.doc.actual_date) {
        grid_row.columns.diff_days.css({
            'background-color': '',
            color: ''
        });
        return;
    }

    const is_negative = Number(grid_row.doc.diff_days) < 0;

    if (is_negative) {
        grid_row.columns.diff_days.css({
            'background-color': '#d32f2f',
            'color': '#ffffff',
            'font-weight': 'bold'
        });
    } else {
        grid_row.columns.diff_days.css({
            'background-color': '#2e7d32',
            'color': '#ffffff',
            'font-weight': 'bold'
        });
    }
}

const ORDER_STATUS_COLORS = {
    'Not yet Started': { bg: '#f57c00', fg: '#ffffff' },
    'In Progress':     { bg: '#3542fd', fg: '#ffffff' },
    'Completed':       { bg: '#2e7d32', fg: '#ffffff' }
};

function style_order_status(frm, status) {
    const field = frm.fields_dict.order_status;
    if (!field || !field.$wrapper) return;

    status = status || frm.doc.order_status || 'Not yet Started';
    const color = ORDER_STATUS_COLORS[status] || ORDER_STATUS_COLORS['Not yet Started'];

    field.$wrapper.find('.control-value, .control-input input, .control-input select').css({
        'background-color': color.bg,
        'color': color.fg,
        'font-weight': 'bold',
        'border-radius': '6px'
    });
}

function is_restricted_merchant() {
    return (
        frappe.user.has_role('Merchant') &&
        !frappe.user.has_role('System Manager') &&
        !frappe.user.has_role('Merch Manager') &&
        frappe.session.user !== 'Administrator'
    );
}

function apply_merchant_restrictions(frm) {
    if (!is_restricted_merchant()) return;

    // 1. Lock manager and merchant fields outside the child table
    const locked_parent_fields = ['manager', 'merchant'];
    locked_parent_fields.forEach(function(field) {
        frm.set_df_property(field, 'read_only', 1);
    });

    // 2. Prevent adding or deleting rows in the child table
    frm.set_df_property('tna_details', 'cannot_add_rows', true);
    frm.set_df_property('tna_details', 'cannot_delete_rows', true);

    let grid = frm.fields_dict.tna_details && frm.fields_dict.tna_details.grid;
    if (grid) {
        grid.cannot_add_rows = true;
        grid.cannot_delete_rows = true;

        // 3. Lock all child table columns except actual_date
        if (grid.docfields) {
            grid.docfields.forEach(function(df) {
                if (df.fieldname !== 'actual_date') {
                    grid.update_docfield_property(df.fieldname, 'read_only', 1);
                } else {
                    grid.update_docfield_property(df.fieldname, 'read_only', 0);
                }
            });
        }

        frm.refresh_field('tna_details');

        grid.wrapper.find('.grid-add-row, .grid-remove-rows, .grid-remove-all-rows, .grid-duplicate-rows').hide();
        grid.wrapper.find('.grid-row-check').hide();

        (grid.grid_rows || []).forEach(function(grid_row) {
            style_diff_cell(grid_row);
        });
    }
}

frappe.ui.form.on('Order TNA Tracker', {
    onload: function(frm) {
        apply_merchant_restrictions(frm);
    },

    refresh: function(frm) {
        apply_merchant_restrictions(frm);

        $(frm.wrapper)
            .off('grid-row-render.diff-days')
            .on('grid-row-render.diff-days', function(event, grid_row) {
                if (grid_row.grid.df.fieldname === 'tna_details') {
                    style_diff_cell(grid_row);
                }
            });

        if (frm.fields_dict.tna_details && frm.fields_dict.tna_details.grid) {
            (frm.fields_dict.tna_details.grid.grid_rows || []).forEach(function(grid_row) {
                style_diff_cell(grid_row);
            });
        }

        style_order_status(frm);
    },

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

            apply_merchant_restrictions(frm);
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
        style_order_status(frm, status);
    }
});

frappe.ui.form.on('TNA Tracker Detail', {
    form_render: function(frm, cdt, cdn) {
        if (is_restricted_merchant()) {
            let grid_row = frm.fields_dict.tna_details.grid.grid_rows_by_docname[cdn];
            if (grid_row && grid_row.grid_form) {
                Object.keys(grid_row.grid_form.fields_dict).forEach(function(fname) {
                    if (fname !== 'actual_date') {
                        grid_row.grid_form.fields_dict[fname].df.read_only = 1;
                        grid_row.grid_form.fields_dict[fname].refresh();
                    }
                });
            }
        }
    },

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